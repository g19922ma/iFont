#!/usr/bin/env python3
"""
群B（検証フェーズ）の進み方 s(t) を作る
======================================
出力は experiment/transfer.js が読む形式：
    {"frame_ms": 16.667,
     "tables": {"<方式>": {"<かな>": {"<条件>": [s0, s1, ...]}}}}
s は 0〜1。添字 i は時刻 i*frame_ms に対応する。

条件は3つ。
  proposed  … s(t) = V̂⁻¹(Â(t))         曲線の形まで写す
  baseline1 … s = t / base_anim_ms      何もしない等速
  baseline2 … s = a·t + b               開始と速さだけ最適に合わせた直線

**転写の対象を2通り作る**（どちらを使うかは未決）。
  rawp  … 生の正答率をそのまま合わせる   Â(t) をそのまま V̂ で逆引き
  qnorm … 各刺激の天井を1に揃えてから合わせる（従来案）

視覚側の天井 λ は、当てはめ値と「100%まで出したときの実測」の大きい方を使う。
当てはめの λ が実測を下回ると、そこだけ逆引きできなくなるため（2026-08-26 に判明）。
"""
import csv, io, json, math, os, sys
from collections import defaultdict

CHARS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]   # 8字ぜんぶ（2026-08-26 丸山判断）
FAMS  = ["fade", "reveal", "blur", "wipe"]
FRAME_MS = 1000.0 / 60.0

def tb(v): return str(v).strip().lower() == "true"
def num(v):
    try: return float(v)
    except: return None
def logi(x, p):
    z = -(x - p["mu"]) / p["sg"]
    z = max(-60.0, min(60.0, z))
    return p["g"] + (p["lam"] - p["g"]) / (1.0 + math.exp(z))

def load_fits(path):
    F = {}
    for r in csv.DictReader(io.open(path, encoding="utf-8-sig")):
        F[(r["modality"], r["char"], r["family"])] = dict(
            g=float(r["gamma"]), lam=float(r["lambda"]),
            mu=float(r["mu"]), sg=float(r["sigma"]),
            obs=float(r["lambda_observed_full"]) if r.get("lambda_observed_full") else None)
    return F

def gates_from_trials(path):
    """字ごとの打ち切り水準（実際に出題したもの）を拾う。"""
    g = defaultdict(set)
    for r in csv.DictReader(io.open(path, encoding="utf-8-sig")):
        if tb(r.get("is_test")) or r.get("check_kind"): continue
        if r.get("group") != "acal": continue
        v = num(r.get("gate_ms"))
        if v is not None and r["target_char"] in CHARS:
            g[r["target_char"]].add(v)
    return {k: sorted(v) for k, v in g.items()}

def invert(pv, y):
    """V̂(s)=y を s について解く。範囲外は端に丸め、丸めたことを返す。"""
    if y <= pv["g"]: return 0.0, "low"
    if y >= pv["lam"]: return 100.0, "high"
    s = pv["mu"] + pv["sg"] * math.log((y - pv["g"]) / (pv["lam"] - y))
    if s < 0.0:   return 0.0, "low"
    if s > 100.0: return 100.0, "high"
    return s, None

# ---- 組み合わせ方式（2026-08-26 追加）---------------------------------------
# 一様に落とす方式（fade / reveal）× 空間的に落とす方式（blur / wipe）の総当たり。
#
# ■ なぜ組み合わせるか
#   較正で分かった弱点が互いを埋め合う。
#     ぼやけ … 床が高い（一番薄い水準でも 26% 当たる）＝「まだ誰も分からない」を作れない
#     一様2つ … 全変化が 0〜5% に詰まっていて、進み具合1%のずれで 27〜38pt 動く
#   一様と空間を掛ければ、床を下げつつ広い範囲を使える**はず**である。
#
# ■ ⚠ 掛け方（重要）
#   同じ進み具合を両方に入れると**遅い方に飲み込まれる**。
#   fade は 0〜3.65% で終わり、blur は 0〜91.96% かかる（持ち場が25倍違う）。
#   そこで**それぞれが実際に働く区間へ進み具合を割り当て直す**。
#   u=50% なら両方が自分の中間点にいる。
#
# ■ ⚠ V(s) は未測定なので、これは**予測**である
#   「2つの劣化が独立に効く」と仮定して q = q1 × q2 と置いた。
#   **この予測が当たるかどうかが群Bで検証されること**の一つになる。
#   外れたら「2つの劣化は独立ではない」という知見になる。
COMBOS = [("fade", "blur"), ("fade", "wipe"), ("reveal", "blur"), ("reveal", "wipe")]

def span(pv):
    """その方式が実際に働く区間（q が 1% → 99% になる s の範囲）"""
    lo = pv["mu"] + pv["sg"] * math.log(0.01 / 0.99)
    hi = pv["mu"] + pv["sg"] * math.log(0.99 / 0.01)
    return max(0.0, lo), min(100.0, hi)

# 組み合わせの進み具合 u を、各方式の進み具合へ写す表を作る。
#
# ⚠ **区間 [lo, hi] へ線形に写す方式は使えない**（2026-08-26 に実装して判明）。
#   fade の働く区間は「か」で 0〜3.65% しかないので、u=100% でも不透明度が
#   3.65% にしかならず、**文字が最後まで完成しない**。
#   確認問題（全部見せて正答率を見る）が成立しなくなる。
#
# ⚠ **q をそのまま u に対応させる方式も使えない。**
#   q→1 は s→∞ なので u=100% を 100% に丸めることになり、
#   u=99% で 4.5%、u=100% で 100% という**最後だけ飛ぶ**表になる。
#
# ■ 採った写し方：**べき乗**
#       s_x(u) = 100 · u^k        k = ln(μ_x / 100) / ln(0.5)
#   こうすると
#     u=0   → s=0          何も見えない
#     u=0.5 → s=μ_x        その方式の**中間点**（半分の人が読める濃さ）
#     u=1   → s=100%       完全に出る
#   の3点が自然にそろい、途中もなめらかにつながる。
#   2つの方式は**同じ u で、それぞれの中間点を同時に通る**。
#
#   ⚠ μ が 100% に近い方式（「ぱ」の端から は μ=99.5%）では k がほぼ 0 になり、
#     最初からほぼ完全に出た状態になる。これは**そう測れているという事実**なので
#     そのまま通す（無理に補正しない）。k は数値の安全のため [0.05, 20] に丸める。
def qof(pv, s):
    """その方式での識別の進み具合 q（0〜1）"""
    p = logi(s, pv)
    return max(0.0, min(1.0, (p - pv["g"]) / (pv["lam"] - pv["g"])))

N_MAP = 101   # u を 0, 0.01, …, 1.00 の 101 点で刻む

def qmap(pv):
    """u（0〜1）→ その方式の進み具合 s（%）。u=0.5 で μ を通る。"""
    mu = max(0.01, min(99.99, pv["mu"]))
    k = math.log(mu / 100.0) / math.log(0.5)
    k = max(0.05, min(20.0, k))
    out = []
    for i in range(N_MAP):
        u = i / (N_MAP - 1)
        out.append(100.0 * (u ** k))
    for i in range(1, len(out)):
        if out[i] < out[i-1]: out[i] = out[i-1]
    return out

def build(F, gates, space, base_anim_ms):
    tables = {f: {} for f in FAMS}
    log = []
    for fam in FAMS:
        for ch in CHARS:
            pa = dict(F[("audio", ch, "")])
            # 聴覚側の天井も実測を下回らせない。
            # 「が」は当てはめ λ=0.008 が γ=0.015 を下回り、そのままだと逆引きが退化する。
            # 実測（全部聞かせたとき 0.029）を使えば λ>γ になり、**ほとんど動かない曲線**として
            # 転写できる。「音が最後まで分からないなら、文字も最後まで読めない」を再現する。
            pa["lam"] = max(pa["lam"], pa["obs"] or 0.0)
            pv = dict(F[("visual", ch, fam)])
            pv["lam"] = max(pv["lam"], pv["obs"] or 0.0)   # 天井は実測を下回らせない
            tmax = max(gates[ch])
            n = int(math.ceil(tmax / FRAME_MS)) + 2
            ts = [i * FRAME_MS for i in range(n)]

            # ---- 目標 ----
            if space == "rawp":
                targ = [logi(t, pa) for t in ts]
            else:  # qnorm: 聴覚の天井を1に揃え、視覚の天井に載せ替える
                targ = []
                for t in ts:
                    q = (logi(t, pa) - pa["g"]) / (pa["lam"] - pa["g"])
                    q = max(0.0, min(1.0, q))
                    targ.append(pv["g"] + q * (pv["lam"] - pv["g"]))

            # ---- proposed ----
            prop = []; nlo = nhi = 0
            for y in targ:
                s, cl = invert(pv, y)
                if cl == "low": nlo += 1
                if cl == "high": nhi += 1
                prop.append(s)
            for i in range(1, len(prop)):        # 表示が戻らないようにそろえる
                if prop[i] < prop[i-1]: prop[i] = prop[i-1]

            # ---- baseline1: 等速 ----
            b1 = [max(0.0, min(100.0, 100.0 * t / base_anim_ms)) for t in ts]

            # ---- baseline2: 開始と速さだけ合わせた直線 ----
            best = None
            for ai in range(1, 601):
                a = ai * (100.0 / base_anim_ms) / 100.0 * 2.0   # 傾きの候補
                for bi in range(-40, 41):
                    b = bi * 0.5
                    e = 0.0
                    for t, y in zip(ts, targ):
                        s = max(0.0, min(100.0, a * t + b))
                        e += (logi(s, pv) - y) ** 2
                    if best is None or e < best[0]: best = (e, a, b)
            _, a, b = best
            b2 = [max(0.0, min(100.0, a * t + b)) for t in ts]

            tables[fam][ch] = {
                "proposed":  [round(x / 100.0, 6) for x in prop],
                "baseline1": [round(x / 100.0, 6) for x in b1],
                "baseline2": [round(x / 100.0, 6) for x in b2],
            }
            log.append(dict(space=space, family=fam, char=ch, n_frames=len(ts),
                            t_max_ms=round(tmax, 1),
                            clip_low=nlo, clip_high=nhi,
                            s_min=round(min(prop), 3), s_max=round(max(prop), 3),
                            b2_a=round(a, 5), b2_b=round(b, 3)))
    # ---- 組み合わせ ----
    ranges = {}
    for a, b in COMBOS:
        key = a + "+" + b
        tables[key] = {}; ranges[key] = {}
        for ch in CHARS:
            pa = dict(F[("audio", ch, "")]); pa["lam"] = max(pa["lam"], pa["obs"] or 0.0)
            pva = dict(F[("visual", ch, a)]); pva["lam"] = max(pva["lam"], pva["obs"] or 0.0)
            pvb = dict(F[("visual", ch, b)]); pvb["lam"] = max(pvb["lam"], pvb["obs"] or 0.0)
            ma, mb = qmap(pva), qmap(pvb)
            lam = min(pva["lam"], pvb["lam"])
            def at(m, u):
                x = max(0.0, min(1.0, u / 100.0)) * (N_MAP - 1)
                i = int(x); j = min(i + 1, N_MAP - 1); f = x - i
                return m[i] * (1 - f) + m[j] * f
            def P(u):
                return pva["g"] + (lam - pva["g"]) * qof(pva, at(ma, u)) * qof(pvb, at(mb, u))
            tmax = max(gates[ch])
            n = int(math.ceil(tmax / FRAME_MS)) + 2
            ts = [i * FRAME_MS for i in range(n)]
            if space == "rawp":
                targ = [logi(t, pa) for t in ts]
            else:
                targ = []
                for t in ts:
                    q = (logi(t, pa) - pa["g"]) / (pa["lam"] - pa["g"])
                    targ.append(pva["g"] + max(0.0, min(1.0, q)) * (lam - pva["g"]))
            top = P(100.0); prop = []; nlo = nhi = 0
            for y in targ:
                if y <= pva["g"]: prop.append(0.0); nlo += 1; continue
                if y >= top:      prop.append(100.0); nhi += 1; continue
                lo_, hi_ = 0.0, 100.0
                for _ in range(40):
                    mid = (lo_ + hi_) / 2
                    if P(mid) < y: lo_ = mid
                    else: hi_ = mid
                prop.append((lo_ + hi_) / 2)
            for i in range(1, len(prop)):
                if prop[i] < prop[i-1]: prop[i] = prop[i-1]
            b1 = [max(0.0, min(100.0, 100.0 * t / base_anim_ms)) for t in ts]
            # 直線合わせは提案の始点・終点を結ぶ直線で近似する（総当たり探索は重いので）
            s0, s1 = prop[0], prop[-1]
            b2 = [max(0.0, min(100.0, s0 + (s1 - s0) * i / max(1, len(ts) - 1))) for i in range(len(ts))]
            tables[key][ch] = {
                "proposed":  [round(x / 100.0, 6) for x in prop],
                "baseline1": [round(x / 100.0, 6) for x in b1],
                "baseline2": [round(x / 100.0, 6) for x in b2],
            }
            ranges[key][ch] = {"a": [round(x, 4) for x in ma],
                               "b": [round(x, 4) for x in mb]}
            log.append(dict(space=space, family=key, char=ch, n_frames=len(ts),
                            t_max_ms=round(tmax, 1), clip_low=nlo, clip_high=nhi,
                            s_min=round(min(prop), 3), s_max=round(max(prop), 3),
                            b2_a=0, b2_b=0))
    return tables, log, ranges

def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fits   = os.path.join(root, "project/data_calib_20260825/analysis/fit_logistic.csv")
    trials = os.path.join(root, "project/data_calib_20260825/transfer_trials.csv")
    outdir = os.path.join(root, "project/data_calib_20260825/warp_b")
    os.makedirs(outdir, exist_ok=True)
    F = load_fits(fits); gates = gates_from_trials(trials)
    base = 300.0
    allog = []
    for space in ("rawp", "qnorm"):
        tables, log, ranges = build(F, gates, space, base)
        doc = {"frame_ms": round(FRAME_MS, 4),
               "meta": {"space": space, "base_anim_ms": base,
                        "made": "2026-08-26", "chars": CHARS,
                        "note": "生成元 build_warp_b.py。凍結時はコミット番号を config に書くこと。"},
               "composite_map": ranges, "composite_map_n": N_MAP,
               "tables": tables}
        p = os.path.join(outdir, f"transfer_warp_{space}.json")
        json.dump(doc, io.open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        allog += log
        print(f"  書き出し: {os.path.basename(p)}  ({os.path.getsize(p)//1024} KB)")
    with io.open(os.path.join(outdir, "warp_b_report.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allog[0].keys())); w.writeheader()
        for r in allog: w.writerow(r)
    print()
    LAB = {"fade":"うすい→濃い","reveal":"点が増える","blur":"ぼやけ","wipe":"端から"}
    def nm(k): return "×".join(LAB.get(x, x) for x in k.split("+"))
    for space in ("rawp", "qnorm"):
        print(f"  ── {'生の正答率' if space=='rawp' else '天井をそろえる(従来案)'}")
        print(f"     {'方式':<12}{'字':<3}{'コマ数':>6}{'床丸め':>7}{'天井丸め':>9}{'sの範囲':>18}")
        for r in allog:
            if r["space"] != space: continue
            print(f"     {nm(r['family']):<22}{r['char']:<3}{r['n_frames']:>6}"
                  f"{r['clip_low']:>7}{r['clip_high']:>9}"
                  f"{r['s_min']:>8.2f}%〜{r['s_max']:>6.2f}%")
        print()

if __name__ == "__main__":
    main()
