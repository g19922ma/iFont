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

CHARS = ["あ", "か", "ま"]
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

def build(F, gates, space, base_anim_ms):
    tables = {f: {} for f in FAMS}
    log = []
    for fam in FAMS:
        for ch in CHARS:
            pa = dict(F[("audio", ch, "")])
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
    return tables, log

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
        tables, log = build(F, gates, space, base)
        doc = {"frame_ms": round(FRAME_MS, 4),
               "meta": {"space": space, "base_anim_ms": base,
                        "made": "2026-08-26", "chars": CHARS,
                        "note": "生成元 build_warp_b.py。凍結時はコミット番号を config に書くこと。"},
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
    for space in ("rawp", "qnorm"):
        print(f"  ── {'生の正答率' if space=='rawp' else '天井をそろえる(従来案)'}")
        print(f"     {'方式':<12}{'字':<3}{'コマ数':>6}{'床丸め':>7}{'天井丸め':>9}{'sの範囲':>18}")
        for r in allog:
            if r["space"] != space: continue
            print(f"     {LAB[r['family']]:<12}{r['char']:<3}{r['n_frames']:>6}"
                  f"{r['clip_low']:>7}{r['clip_high']:>9}"
                  f"{r['s_min']:>8.2f}%〜{r['s_max']:>6.2f}%")
        print()

if __name__ == "__main__":
    main()
