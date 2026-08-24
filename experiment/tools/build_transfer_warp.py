#!/usr/bin/env python3
"""
転写の「進み方 s(t)」を作る（生成工程の骨組み）
==============================================
計画書: project/実験計画書_転写検証.md の 3.1(生成)・3.2(群Bの条件)・6.1(曲線の推定)

較正で測った2つの曲線から、群Bで再生する進み方を作って JSON に書き出す。
  ・音声の曲線   qA_i(t)  … 打ち切り時刻 t ms → 識別の進み具合(0〜1)   ← 群Acal
  ・視覚の曲線   qV_mi(s) … 進み具合 s(0〜1) → 識別の進み具合(0〜1)    ← 群A′
  ・提案(proposed) s_i(t) = qV_mi^{-1}( qA_i(t) )   … 曲線の形まで写す非線形の時間変形
  ・対照1(baseline1) s = t / base_anim_ms            … 何も工夫しない等速
  ・対照2(baseline2) s = a·t + b                     … 開始時刻と速さだけ最適に合わせる
                       (a,b は較正データだけから、曲線の距離が最小になるように決める)

**この実験の要は「一発生成して凍結する」こと**（計画書 Q3）。検証データを取る前に
出力 JSON をコミットし、そのコミット番号を experiment/transfer_config.js の
visual.warp.frozen_commit に書く。結果を見てから作り直さない。

入力は3通り
-----------
1) --trials  … **較正フェーズの1問1行の記録**(CSV か 取り出し口のJSON)。
   計画書 7.1 の手順を**このスクリプトの中で**全部やる。すなわち
     ① 正答率 p を、まぐれ当たり(床 γ)と押し間違い(天井の欠け λ)で割り戻して
        「識別の進み具合」q = (p − γ)/(1 − γ − λ) に直す
     ② 単調であることだけを条件にした回帰(重み付き PAVA = 保序回帰)で q を推定し、
        軽く平滑化してから、もう一度単調にそろえる
     ③ 逆引き・対照条件の生成へ進む
   **本番の較正データもこの入口に入れる**(パイロットも本番も同じ道を通る)。

2) --curves  … 上の①②を外で済ませた「単調な数値列」を直接渡す形。
   {
     "audio":  {"あ": {"t_ms": [20,40,...], "q": [0.02,0.10,...]}, ...},
     "visual": {"fade": {"あ": {"s": [0.06,0.13,...], "q": [0.01,0.08,...]}, ...},
                "reveal": {...}, "blur": {...}, "wipe": {...}}
   }

3) --demo    … 仮のS字曲線。配線の確認専用。

範囲外の丸め(計画書 7.1「範囲の外に出る部分は端に丸め、丸めが起きた範囲を記録・報告する」)
は clipped に残す。丸めは2種類あり、両方とも記録する。
  ・clip_low / clip_high … 目標の q が視覚の曲線で測った範囲の**外**にあった
  ・pin_low  / pin_high  … 範囲の中だが、逆引きの答えが端の水準に**張り付いた**
                           (視覚の曲線が平ら＝どの s でも同じ q のときに起きる)

使い方
------
  # 本番: 較正フェーズの記録から一発生成する
  python3 experiment/tools/build_transfer_warp.py --trials calib_trials.csv

  # パイロットデータでの試走(**知覚的に正しい生成物ではない**。下の警告を読むこと)
  python3 experiment/tools/build_transfer_warp.py \
      --trials project/pilot_data/pilot_20260821_trials.csv \
      --label-map A=anon-cdgptgrg,B=anon-olcnwkzp \
      --tag pilot-demo \
      --out experiment/transfer_warp_demo.json \
      --curves-out project/pilot_data/demo_curves.json \
      --fig-out project/pilot_data/demo_warp_curves.png

  # 配線の確認だけ(仮のS字曲線)
  python3 experiment/tools/build_transfer_warp.py --demo --out /tmp/transfer_warp.json

⚠ --tag を付けると出力に demo:true と warning が入る。**天井に張り付いた較正データ
(1人ぶん・本人・正解既知)から作った表は、知覚的に正しい生成物ではない**。
凍結の対象は --tag を付けずに本番の較正データから作った transfer_warp.json だけである。
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
ROOT = os.path.dirname(EXP)
sys.path.insert(0, HERE)
import analyze_transfer as AT      # 記録の読み込みと列名の正規化を共有する  # noqa: E402

FRAME_MS = 1000.0 / 60.0        # 数値列の刻み(60Hz)


def load_config(path):
    js = ("global.window={};require(%s);"
          "process.stdout.write(JSON.stringify(window.TRANSFER_CONFIG));" % json.dumps(path))
    out = subprocess.run(["node", "-e", js], capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def monotone(y):
    """数値列を単調非減少にならす(測定のゆらぎで前後が入れ替わるのを均す)。"""
    y = np.asarray(y, dtype=float)
    return np.maximum.accumulate(y)


def invert(s_grid, q_grid, q_target):
    """視覚の曲線 qV(s) を逆に引く: 目標の q を出す s を線形補間で求める。

    戻り値: (s, 状態)。状態は
      "interp"    … 測った水準のあいだを読み取れた(ふつう)
      "clip_low"  … 目標の q が測った範囲より**下**。その q を出す水準は無いので、
                    いちばん薄い水準に丸めた
      "clip_high" … 目標の q が測った範囲より**上**。いちばん濃い水準に丸めた
      "pin_low"   … いちばん薄い水準ですでに目標に届いていた(それ以上薄くは測っていない)
      "pin_high"  … 答えがいちばん濃い水準ちょうどに乗った(それ以上濃くは測っていない)
      "interp"    … 測った水準のあいだを読み取れた(ふつう)
    **同じ q を出す s が複数あるときは、いちばん小さい s を採る**(＝必要最小限の
    提示量を採る)。視覚の曲線が平ら(どの水準でも正答率が同じ)だと、この規則により
    答えは必ず最小の水準に張り付く。天井に張り付いた較正データではこれが常時起きる。
    """
    s = np.asarray(s_grid, float)
    q = monotone(q_grid)
    if q_target < q[0] - 1e-9:
        return float(s[0]), "clip_low"
    if q_target > q[-1] + 1e-9:
        return float(s[-1]), "clip_high"
    # 目標に**最初に**届く区間を探す(同じ q が続くときは、いちばん薄い水準を採る)。
    i = int(np.argmax(q >= q_target - 1e-12))
    if i == 0:
        return float(s[0]), "pin_low"
    q0, q1 = q[i - 1], q[i]
    if q1 - q0 < 1e-12:
        val = float(s[i])
    else:
        f = (q_target - q0) / (q1 - q0)
        val = float(s[i - 1] + f * (s[i] - s[i - 1]))
    return val, ("pin_high" if i == len(q) - 1 and val >= s[-1] - 1e-12 else "interp")


def interp_curve(x_grid, y_grid, x):
    """測った点の間は線形補間、外側は端の値で伸ばす。"""
    return float(np.interp(x, np.asarray(x_grid, float), monotone(y_grid)))


def series_from_s_of_t(t_ms, s_vals, dur_ms):
    """時点ごとの s を、60Hz の数値列(0〜dur_ms)に直す。単調非減少にそろえる。"""
    n = int(math.ceil(dur_ms / FRAME_MS)) + 1
    grid = np.arange(n) * FRAME_MS
    # 原点(0ms, s=0)を足してから補間する。最後は 1 まで伸ばす。
    tx = np.concatenate([[0.0], np.asarray(t_ms, float)])
    sx = np.concatenate([[0.0], np.asarray(s_vals, float)])
    order = np.argsort(tx)
    ys = np.interp(grid, tx[order], monotone(sx[order]))
    ys = np.clip(monotone(ys), 0.0, 1.0)
    return [round(float(v), 5) for v in ys]


def step_mid_from_audio(t_ms, qa, q_half):
    """ステップ表示（群Cの5つ目の見せ方）の切り替え時刻を出す。

    定義: **目標の音声曲線で正答率が50%に達する最初の時刻**（計画書 4.5）。
    曲線は q（床＝まぐれ当たりと天井の欠けを割り戻した進み具合）で持っているので、
    正答率50%にあたる q の値 q_half を渡して、そこを横切る点を線形補間で求める。

    端の扱い:
      ・いちばん早い時点ですでに q_half を超えている → その最初の時点を返す
      ・最後まで届かない                            → 最後の時点を返す
    どちらも「その字ではこの対照が極端になる」ことを意味するので、
    印（"below" / "above" / "interp"）も一緒に返して記録に残す。
    """
    t = np.asarray(t_ms, float)
    q = monotone(np.asarray(qa, float))
    if len(t) == 0:
        return 0.0, "empty"
    if q[0] >= q_half:
        return float(t[0]), "below"      # 最初から半分以上分かっている字
    if q[-1] < q_half:
        return float(t[-1]), "above"     # 最後まで半分に届かない字
    for i in range(1, len(t)):
        if q[i] >= q_half:
            dq = q[i] - q[i - 1]
            f = 0.0 if dq <= 0 else (q_half - q[i - 1]) / dq
            return float(t[i - 1] + f * (t[i] - t[i - 1])), "interp"
    return float(t[-1]), "above"


def best_affine(t_ms, qa, s_grid, qv, base_ms):
    """対照2: qV(a·t+b) が音声の曲線 qA(t) に最も近くなる (a,b) を探す。

    「近さ」は評価時点での差の二乗和(計画書 7.2 の距離 E と同じ考え方)。
    格子を粗く→細かく2段階で探す(閉じた式が無い代わりに、決定的で再現できる探索)。

    **同点のときの決め方(2026-08-22 に明文化)**: 視覚の曲線が平らだと、どの (a,b) を
    入れても予測が変わらず、二乗和が全面的に同じ値になる。この「引き分け」を格子の
    並び順で決めると、探索の実装をいじるたびに対照2の中身が変わってしまう。そこで
    差が 1e-12 以内の候補が複数あるときは、**等速(a = 1/base_ms, b = 0)にいちばん近い
    ものを採る**と決めた。等速は対照1そのものなので、「情報が無いときは何も工夫しない
    ほうへ寄せる」という保守的な決め方になる。
    戻り値: (a, b, degenerate)。degenerate=True は「二乗和が平らで (a,b) が決まらなかった」
    ＝対照2が実質的に意味を持たない、という警告である。
    """
    t = np.asarray(t_ms, float)
    qa = np.asarray(qa, float)
    a_ref = 1.0 / float(base_ms)          # 等速のときの傾き(1msあたりの進み具合)
    best = (None, None, float("inf"), float("inf"))
    err_lo, err_hi = float("inf"), -float("inf")
    a_lo, a_hi = 1e-4, 0.02      # 1ms あたりの進み具合(0.02 = 50ms で満了)
    b_lo, b_hi = -1.0, 1.0
    for stage in range(2):
        a_grid = np.linspace(a_lo, a_hi, 120)
        b_grid = np.linspace(b_lo, b_hi, 120)
        for a in a_grid:
            for b in b_grid:
                s = np.clip(a * t + b, 0.0, 1.0)
                pred = np.array([interp_curve(s_grid, qv, si) for si in s])
                err = float(((pred - qa) ** 2).sum())
                # 等速からの遠さ(引き分けのときだけ効く)。a は base_ms 倍して無次元にする。
                tie = ((a - a_ref) * base_ms) ** 2 + b ** 2
                if stage == 0:
                    err_lo, err_hi = min(err_lo, err), max(err_hi, err)
                if err < best[2] - 1e-12 or (abs(err - best[2]) <= 1e-12 and tie < best[3]):
                    best = (float(a), float(b), err, tie)
        a, b = best[0], best[1]
        da, db = (a_hi - a_lo) / 40.0, (b_hi - b_lo) / 40.0
        a_lo, a_hi = max(1e-5, a - da), a + da
        b_lo, b_hi = b - db, b + db
    degenerate = (err_hi - err_lo) < 1e-9
    return best[0], best[1], bool(degenerate)


def demo_curves(cfg):
    """動作確認用の仮の曲線(S字)。**本番データではない**ことを出力にも書く。"""
    rng = np.random.default_rng(20260820)
    chars = cfg["targets"]
    t_grid = cfg["audio"]["gates_ms"]["_default"]
    s_grid = [p / 100.0 for p in cfg["visual"]["progress_pct_levels"]]
    out = {"audio": {}, "visual": {}, "_demo": True}
    for ch in chars:
        mu = float(rng.uniform(55, 110))
        sc = float(rng.uniform(12, 30))
        out["audio"][ch] = {"t_ms": t_grid,
                            "q": [round(1 / (1 + math.exp(-(t - mu) / sc)), 4) for t in t_grid]}
    for fam in ["fade", "reveal", "blur", "wipe"]:
        out["visual"][fam] = {}
        mid = {"fade": 0.45, "reveal": 0.55, "blur": 0.5, "wipe": 0.6}[fam]
        for ch in chars:
            m = mid + float(rng.uniform(-0.08, 0.08))
            out["visual"][fam][ch] = {
                "s": s_grid,
                "q": [round(1 / (1 + math.exp(-(s - m) / 0.12)), 4) for s in s_grid]}
    return out


# =========================================================================
# 較正フェーズの記録 → 曲線(計画書 7.1 の「生成用」)
# =========================================================================
def isotonic(y, w):
    """重み付きの保序回帰(PAVA)。単調非減少に潰す。scipy が無ければ自前で回す。"""
    y = np.asarray(y, float)
    w = np.asarray(w, float)
    try:
        from scipy.optimize import isotonic_regression
        return np.asarray(isotonic_regression(y, weights=w, increasing=True).x, float)
    except Exception:
        pass
    vals = list(y)
    wts = list(w)
    lens = [1] * len(y)
    i = 0
    while i < len(vals) - 1:
        if vals[i] <= vals[i + 1] + 1e-15:
            i += 1
            continue
        tw = wts[i] + wts[i + 1]
        vals[i] = (vals[i] * wts[i] + vals[i + 1] * wts[i + 1]) / tw
        wts[i] = tw
        lens[i] += lens[i + 1]
        del vals[i + 1], wts[i + 1], lens[i + 1]
        if i > 0:
            i -= 1
    out = []
    for v, n in zip(vals, lens):
        out.extend([v] * n)
    return np.asarray(out, float)


def smooth3(y):
    """[0.25, 0.5, 0.25] の3点平滑化を1回。端は折り返し。そのあと単調にそろえ直す。

    測った水準が8点前後しかないので、これ以上強く均すと段差の位置が動いてしまう。
    「保序回帰のあと軽く均す」(計画書 7.1「単調ノンパラメトリック推定」)の実装である。

    ⚠ 2026-08-24 以降、視覚の水準は**参加者ごとに 0.5% ずつずれる**
    (transfer_config.js の visual.progress_pct_shift)。集団全体をまとめると
    1人あたり8点でも、方式×字のセルでは 20 点前後の細かい格子になる。
    この平滑化は「隣り合う3点」で均すので、格子が細かいほど均す幅(%)は狭くなる
    ——つまり点が増えるぶん均しは弱くなるだけで、悪さはしない。
    ただし1点あたりの回答数は薄くなるので、点ごとのばらつきは大きくなる。
    そこを吸収するのが手前の保序回帰(回答数で重み付け)である。
    """
    y = np.asarray(y, float)
    if len(y) < 3:
        return y
    pad = np.concatenate([[y[0]], y, [y[-1]]])
    z = 0.25 * pad[:-2] + 0.5 * pad[1:-1] + 0.25 * pad[2:]
    return monotone(z)


def to_q(p, gamma, lam):
    """正答率 p → 識別の進み具合 q。床(まぐれ当たり)と天井の欠け(押し間違い)を割り戻す。"""
    return float(np.clip((np.asarray(p, float) - gamma) / max(1e-9, 1.0 - gamma - lam), 0.0, 1.0))


def from_q(q, gamma, lam):
    """q → 正答率 p(逆向き。1つ抜き交差確認の誤差を「正答率ポイント」で言うのに使う)。"""
    return gamma + (1.0 - gamma - lam) * np.asarray(q, float)


def audio_full_lengths(path):
    """打ち切りなし(全長)の音がその字で何msあるかを、刺激の索引から読む。"""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
    except Exception:
        return out
    for key, it in (man.get("items") or {}).items():
        if str(it.get("gate_ms")) == "full" or key.endswith("|full"):
            ms = it.get("after_onset_ms")
            if ms is None and it.get("dur_ms") is not None and it.get("lead_ms") is not None:
                ms = it["dur_ms"] - it["lead_ms"]
            if ms is not None:
                out[it.get("char") or key.split("|")[0]] = float(ms)
    return out


def curves_from_trials(rows, cfg, gamma, lapse_arg, full_len):
    """1問1行の記録から、生成に使う曲線(単調な数値列)を作る。

    計画書 7.1 の「生成用」に対応する。除外の規則もここで当てる。
      ・まぎれ字と確認問題は曲線に入れない(確認問題Aは押し間違い率 λ の推定にだけ使う)
      ・下見だけ足した時点は入れない
        (audio.pilot_extra_gates.enabled が true のときのみ除外。false のときは、
         同じ値が gates_ms 本体に載っている正規の時点なので落とさない)
        ※ 視覚側の同じ仕掛け visual.pilot_extra_levels は 2026-08-24 に削除した
          (薄い水準が本体 progress_pct_levels に入ったため役目を終えた)。
          設定に残っていれば従来どおり除外する後方互換だけ残してある。
      ・視覚は generation_level_ms の速さの水準だけ(計画書 7.1・事前固定)
      ・視覚の水準は**参加者ごとに 0.5% ずつずれる**(visual.progress_pct_shift)。
        ここは記録に入っている progress_pct の値をそのまま格子にするので、
        集団をまとめると格子が細かくなるだけで、除外や補正は要らない。
    """
    log = {"excluded": [], "notes": []}
    ex_g = cfg["audio"].get("pilot_extra_gates") or {}
    drop_gates = set(ex_g.get("gate_ms") or []) if ex_g.get("enabled") else set()
    ex_l = cfg["visual"].get("pilot_extra_levels") or {}
    drop_pcts = set(ex_l.get("progress_pct") or []) if ex_l.get("enabled") else set()
    probe = cfg["visual"].get("calib_speed_probe") or {}
    gen_base = float(probe["generation_level_ms"]) if probe.get("enabled") else None

    # ---- 押し間違い率 λ: 確認問題A(全部見せ・全部聞かせ)の取りこぼし ----
    if lapse_arg == "auto":
        full = [r for r in rows if r["check_kind"] == "full"]
        lam = (1.0 - sum(1 for r in full if r["correct"]) / len(full)) if full else 0.0
        log["notes"].append(f"押し間違い率 λ={lam:.3f}（確認問題A {len(full)}問の取りこぼしから推定）")
    else:
        lam = float(lapse_arg)
        log["notes"].append(f"押し間違い率 λ={lam:.3f}（指定値）")
    log["gamma"] = gamma
    log["lapse"] = lam

    tgt = [r for r in rows if not r["is_filler"] and not r["check_kind"]]

    # ---- 聴覚 qA(t) ----
    acc_a = {}
    for r in tgt:
        if r["mod"] != "聴覚":
            continue
        t = r["gate_ms"]
        if t is None:                      # 打ち切りなし(全長)の点
            t = full_len.get(r["target_char"])
            if t is None:
                log["excluded"].append(f"聴覚 {r['target_char']} の全長の点（索引に長さが無い）")
                continue
        if t in drop_gates:
            log["excluded"].append(f"聴覚 {r['target_char']} {t:.0f}ms（下見だけの時点）")
            continue
        d = acc_a.setdefault(r["target_char"], {}).setdefault(float(t), [0, 0])
        d[1] += 1
        d[0] += 1 if r["correct"] else 0

    # ---- 視覚 qV(s) ----
    acc_v = {}
    for r in tgt:
        if r["mod"] != "視覚" or r["progress_pct"] is None:
            continue
        if r["progress_pct"] in drop_pcts:
            log["excluded"].append(f"視覚 {r['family']} {r['target_char']} {r['progress_pct']:.0f}%（下見だけの水準）")
            continue
        if gen_base is not None and r["base_anim_ms"] is not None and r["base_anim_ms"] != gen_base:
            log["excluded"].append(f"視覚 {r['family']} {r['target_char']} 基準アニメ {r['base_anim_ms']:.0f}ms"
                                   f"（生成に使うのは {gen_base:.0f}ms の水準だけ）")
            continue
        fam = r["family"] or "fade"
        d = acc_v.setdefault(fam, {}).setdefault(r["target_char"], {}).setdefault(r["progress_pct"] / 100.0, [0, 0])
        d[1] += 1
        d[0] += 1 if r["correct"] else 0

    def fit(levels, counts):
        xs = sorted(levels)
        p = [counts[x][0] / counts[x][1] for x in xs]
        n = [counts[x][1] for x in xs]
        q_raw = [to_q(v, gamma, lam) for v in p]
        q_iso = isotonic(q_raw, n)
        q_hat = smooth3(q_iso)
        return xs, p, n, [round(float(v), 5) for v in q_raw], [round(float(v), 5) for v in q_hat]

    curves = {"audio": {}, "visual": {}, "_raw": {"audio": {}, "visual": {}}}
    for ch, counts in acc_a.items():
        xs, p, n, q_raw, q_hat = fit(list(counts), counts)
        curves["audio"][ch] = {"t_ms": xs, "q": q_hat}
        curves["_raw"]["audio"][ch] = {"t_ms": xs, "p": p, "n": n, "q_raw": q_raw}
    for fam, per_char in acc_v.items():
        curves["visual"][fam] = {}
        curves["_raw"]["visual"][fam] = {}
        for ch, counts in per_char.items():
            xs, p, n, q_raw, q_hat = fit(list(counts), counts)
            curves["visual"][fam][ch] = {"s": xs, "q": q_hat}
            curves["_raw"]["visual"][fam][ch] = {"s": xs, "p": p, "n": n, "q_raw": q_raw}
    curves["_fit"] = log
    return curves


def loo_check(curves, gamma, lam):
    """1つ抜き交差確認(計画書 7.1「内挿の確認」)。

    測った水準を1つ伏せ、残りだけで曲線を作り直して、伏せた点の正答率を予測して実測と比べる。
    誤差の単位は**正答率ポイント**(0〜100)。水準の間隔が粗すぎるところを見つけるための手続き。
    """
    out = []
    for mod, group in (("audio", curves["_raw"]["audio"]),
                       ("visual", curves["_raw"]["visual"])):
        items = ([("", ch, v) for ch, v in group.items()] if mod == "audio"
                 else [(fam, ch, v) for fam, per in group.items() for ch, v in per.items()])
        for fam, ch, v in items:
            xs = v["t_ms"] if mod == "audio" else v["s"]
            p, n = v["p"], v["n"]
            if len(xs) < 3:
                continue
            errs = []
            for i in range(len(xs)):
                keep = [j for j in range(len(xs)) if j != i]
                q_raw = [to_q(p[j], gamma, lam) for j in keep]
                q_hat = smooth3(isotonic(q_raw, [n[j] for j in keep]))
                pred_q = float(np.interp(xs[i], [xs[j] for j in keep], q_hat))
                errs.append(abs(float(from_q(pred_q, gamma, lam)) - p[i]) * 100.0)
            out.append({"modality": mod, "family": fam, "char": ch,
                        "mean_pt": round(float(np.mean(errs)), 2),
                        "max_pt": round(float(np.max(errs)), 2),
                        "worst_level": xs[int(np.argmax(errs))]})
    return out


# =========================================================================
# 図: 3条件の進み方
# =========================================================================
def draw_warp_figure(path, tables, dur_ms, base_ms, gate_max, title, note):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    jp = AT.pick_jp_font()
    if jp:
        plt.rcParams["font.family"] = jp
    combos = [(fam, ch) for fam in sorted(tables) for ch in sorted(tables[fam])]
    if not combos:
        return False
    ncol = 4
    nrow = int(math.ceil(len(combos) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.1 * ncol, 2.5 * nrow), dpi=150,
                             squeeze=False, sharex=True, sharey=True)
    n = len(next(iter(next(iter(tables.values())).values()))["proposed"])
    grid = np.arange(n) * FRAME_MS
    style = {"baseline1": ("#9aa3b2", "-", "対照1 等速"),
             "baseline2": ("#E08A2E", "--", "対照2 最適アフィン"),
             "proposed":  ("#2E7D8F", "-", "提案 曲線の形まで写す")}
    for k, (fam, ch) in enumerate(combos):
        ax = axes[k // ncol][k % ncol]
        ax.axvspan(0, gate_max, color="#2E7D8F", alpha=0.05, lw=0)
        for cond in ("baseline1", "baseline2", "proposed"):
            c, ls, lab = style[cond]
            ax.plot(grid, tables[fam][ch][cond], color=c, linestyle=ls,
                    linewidth=2.0 if cond == "proposed" else 1.4, label=lab)
        ax.set_title(f"{fam} ／ {ch}", fontsize=10)
        ax.set_ylim(-0.05, 1.05)
        ax.set_xlim(0, dur_ms)
        ax.grid(alpha=0.25, linewidth=0.6)
    for k in range(len(combos), nrow * ncol):
        axes[k // ncol][k % ncol].axis("off")
    for r in range(nrow):
        axes[r][0].set_ylabel("進み具合 s")
    for c in range(ncol):
        axes[nrow - 1][c].set_xlabel("経過時間（ミリ秒）")
    h, l = axes[0][0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=3,
               frameon=False, fontsize=10)
    fig.suptitle(title, fontsize=13, y=0.99)
    if note:
        fig.text(0.5, 0.925, note, ha="center", fontsize=9.5, color="#a33")
    fig.text(0.5, 0.078, "淡い帯は群Bが実際に打ち切る時間帯（0〜%d ミリ秒）" % gate_max,
             ha="center", fontsize=8.5, color="#667")
    fig.tight_layout(rect=(0, 0.115, 1, 0.90))
    fig.savefig(path)
    plt.close(fig)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", default=None, help="較正フェーズの1問1行の記録(CSV / dump JSON)")
    ap.add_argument("--label-map", default="", help='短縮IDの読み替え。"A=anon-xxx,B=anon-yyy"')
    ap.add_argument("--include-test", action="store_true",
                    help="動作確認の行（is_test）も材料に入れる（既定は外す）")
    ap.add_argument("--guess", default="auto", help="まぐれ当たり率 γ。auto=選択肢数の逆数")
    ap.add_argument("--lapse", default="auto", help="押し間違い率 λ。auto=確認問題Aの取りこぼし")
    ap.add_argument("--audio-manifest", default=os.path.join(EXP, "transfer_audio_manifest.json"),
                    help="打ち切りなし(全長)の点を時間軸に置くために読む")
    ap.add_argument("--curves", default=None, help="較正の曲線 JSON(上の説明の形)")
    ap.add_argument("--demo", action="store_true", help="仮のS字曲線で動作確認用の表を作る")
    ap.add_argument("--tag", default="", help="試走の目印(付けると出力に demo:true と警告が入る)")
    ap.add_argument("--config", default=os.path.join(EXP, "transfer_config.js"))
    ap.add_argument("--out", default=os.path.join(EXP, "transfer_warp.json"))
    ap.add_argument("--curves-out", default=None, help="推定した曲線を書き出す先(任意)")
    ap.add_argument("--fig-out", default=None, help="3条件の進み方の図の書き出し先(任意)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    fit_log, loo = None, None
    # 正答率50%にあたる q を出すための床・天井。--demo / --curves のときは
    # 曲線がすでに q として与えられているので、素の 0.5 を使う。
    step_gamma, step_lapse = 0.0, 0.0
    if args.trials:
        label_map = {}
        for pair in filter(None, args.label_map.split(",")):
            k, _, v = pair.partition("=")
            label_map[k.strip()] = v.strip()
        raw = AT.load(args.trials)
        n_test = 0
        # 動作確認で作った行(is_test)は生成の材料にしない。**凍結する表を試し打ちから
        # 作ってしまう事故**を防ぐため、分析側(analyze_transfer.py)と同じ既定にそろえる。
        if not args.include_test and hasattr(AT, "drop_test_rows"):
            raw, n_test = AT.drop_test_rows(raw)
            if n_test:
                print(f"  試し打ちの行 {n_test} 件を外しました（混ぜるなら --include-test）")
        rows = AT.normalize(raw, label_map)
        n_rows_in = len(raw)
        n_choice = sum(1 for row in cfg["answer_grid"] for c in row if c)
        gamma = (1.0 / n_choice) if args.guess == "auto" else float(args.guess)
        curves = curves_from_trials(rows, cfg, gamma,
                                    args.lapse, audio_full_lengths(args.audio_manifest))
        # ステップ表示の切り替え時刻を出すのに要る(正答率50% が q でいくつかを決める)。
        step_gamma, step_lapse = gamma, float(curves["_fit"]["lapse"])
        fit_log = curves["_fit"]
        fit_log["n_choices"] = n_choice
        fit_log["n_rows"] = n_rows_in
        fit_log["n_test_rows_dropped"] = n_test
        fit_log["source"] = os.path.relpath(os.path.abspath(args.trials), ROOT)
        loo = loo_check(curves, gamma, fit_log["lapse"])
        if args.tag:
            curves["_demo"] = True
    elif args.demo:
        curves = demo_curves(cfg)
    elif args.curves:
        with open(args.curves, encoding="utf-8") as f:
            curves = json.load(f)
    else:
        raise SystemExit("--trials か --curves か --demo のどれかを指定してください")

    if args.curves_out:
        with open(args.curves_out, "w", encoding="utf-8") as f:
            json.dump(curves, f, ensure_ascii=False, indent=1)
        print(f"曲線を書き出し: {args.curves_out}")

    base_ms = float(cfg["visual"]["base_anim_ms"])
    # 数値列の長さ: 群Bの最も遅い打ち切り時刻まで(＋余白1フレーム)。
    gate_table = cfg["visual"]["gates_ms"]
    max_gate = max(max(v) for v in gate_table.values())
    dur_ms = max(max_gate, base_ms)

    n = int(math.ceil(dur_ms / FRAME_MS)) + 1
    grid = np.arange(n) * FRAME_MS

    tables, clipped, affine_log, deviation = {}, [], {}, []
    step_mid_ms, step_mid_kind = {}, {}
    for fam, per_char in curves["visual"].items():
        tables[fam] = {}
        for ch, v in per_char.items():
            if ch not in curves["audio"]:
                continue
            a_t = curves["audio"][ch]["t_ms"]
            a_q = curves["audio"][ch]["q"]
            s_grid, q_grid = v["s"], v["q"]

            # 提案: 各時点で「音声と同じ分かり具合」になる s を逆引きする。
            s_prop, states = [], []
            for t, q in zip(a_t, a_q):
                s, state = invert(s_grid, q_grid, q)
                s_prop.append(s)
                states.append(state)
            kinds = {}
            for t, st in zip(a_t, states):
                if st != "interp":
                    kinds.setdefault(st, []).append(float(t))
            if kinds:
                clipped.append({
                    "family": fam, "char": ch,
                    "n_points": len(a_t),
                    "n_interpolated": sum(1 for s in states if s == "interp"),
                    # どの打ち切り時刻で端に張り付いたか。範囲は [最小ms, 最大ms]。
                    "kinds": {k: {"n": len(ts), "t_ms": ts, "t_range_ms": [min(ts), max(ts)]}
                              for k, ts in kinds.items()},
                })

            # 対照2: 較正データだけから決める最良の1次変換。
            a, b, degen = best_affine(a_t, a_q, s_grid, q_grid, base_ms)
            affine_log[f"{fam}|{ch}"] = {"a": round(a, 6), "b": round(b, 4), "degenerate": degen}

            prop = series_from_s_of_t(a_t, s_prop, dur_ms)
            base1 = [round(float(min(1.0, max(0.0, t / base_ms))), 5) for t in grid]
            base2 = [round(float(min(1.0, max(0.0, a * t + b))), 5) for t in grid]
            tables[fam][ch] = {"proposed": prop, "baseline1": base1, "baseline2": base2}

            # ---- 群C(見え心地)のステップ表示に渡す切り替え時刻 -----------------------
            # 中点まで何も出さず、そこで一気に完成形にする「従来型の字幕」を模した見せ方。
            # 中点は目標の音声曲線で正答率50%に達する時刻。→ 計画書 4.5
            # **群Bの条件ではない**(識別の測定はしない)ので、進み方の数値列は作らず、
            # 時刻だけを字ごとに出す。群Cはこの1つの数字から自分で 0/1 を作る。
            if ch not in step_mid_ms:
                mid, kind = step_mid_from_audio(a_t, a_q, to_q(0.5, step_gamma, step_lapse))
                step_mid_ms[ch] = round(float(mid), 2)
                step_mid_kind[ch] = kind

            # ---- 提案と対照はどれだけ違うか(計画書 7.2 の距離Eに相当する乖離) ----
            # (1) 進み具合 s のうえでの差。群Bが実際に出題する時間帯だけで測る。
            tmax = max(a_t[-1], max(max(x) for x in cfg["visual"]["gates_ms"].values()))
            sel = grid <= tmax
            p_, b1_, b2_ = np.array(prop)[sel], np.array(base1)[sel], np.array(base2)[sel]
            # (2) 正答率ポイントのうえでの差。較正した視覚の曲線に通してから比べる
            #     (「この進み方で出したら何%当たるはず」の予測どうしの差)。
            def pred_pt(series):
                return np.array([interp_curve(s_grid, q_grid, s) for s in series]) * 100.0
            deviation.append({
                "family": fam, "char": ch,
                "eval_upto_ms": round(float(tmax), 1),
                "s_mean_abs_vs_baseline2": round(float(np.abs(p_ - b2_).mean()), 4),
                "s_max_abs_vs_baseline2": round(float(np.abs(p_ - b2_).max()), 4),
                "s_mean_abs_vs_baseline1": round(float(np.abs(p_ - b1_).mean()), 4),
                "pt_mean_abs_vs_baseline2": round(float(np.abs(pred_pt(p_) - pred_pt(b2_)).mean()), 3),
                "pt_mean_abs_vs_baseline1": round(float(np.abs(pred_pt(p_) - pred_pt(b1_)).mean()), 3),
            })

    out = {
        "generated_by": "experiment/tools/build_transfer_warp.py",
        "demo": bool(curves.get("_demo")),
        "tag": args.tag,
        "frame_ms": round(FRAME_MS, 5),
        "duration_ms": dur_ms,
        "base_anim_ms": base_ms,
        "config_version": cfg.get("config_version", ""),
        "affine": affine_log,
        # ステップ表示の切り替え時刻ms。**群C**(experiment/transfer_comfort.js)が字ごとに読む。
        # step_mid_kind は「補間で求めた(interp)／最初の時点で既に50%を超えていた(below)／
        # 最後まで50%に届かなかった(above)」の印。
        "step_mid_ms": step_mid_ms,
        "step_mid_kind": step_mid_kind,
        "clipped": clipped,
        "deviation": deviation,
        "tables": tables,
    }
    if fit_log:
        out["fit"] = fit_log
    if loo:
        out["loo"] = loo
    if args.tag:
        out["warning"] = (
            "試走用。天井に張り付いた較正データ(1人・本人・正解既知)から作った表であり、"
            "知覚的に正しい生成物ではない。凍結の対象ではない。")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    fams = ", ".join(f"{k}:{len(v)}字" for k, v in tables.items())
    print(f"書き出し: {args.out}")
    print(f"  方式ごとの字数: {fams}  数値列の長さ: {len(next(iter(next(iter(tables.values())).values()))['proposed'])} 点"
          f"（{FRAME_MS:.3f}ms 刻み・{dur_ms:.0f}ms まで）")
    if clipped:
        n_pin = sum(sum(k["n"] for k in c["kinds"].values()) for c in clipped)
        print(f"  端に張り付いた/丸めた点: {len(clipped)} 組合せ・のべ {n_pin} 点（内訳は出力の clipped）")
    if any(v["degenerate"] for v in affine_log.values()):
        n_d = sum(1 for v in affine_log.values() if v["degenerate"])
        print(f"  ⚠ 対照2(最適アフィン)が決まらなかった組合せ: {n_d}"
              "（視覚の曲線が平らで、どの(a,b)でも当てはまりが同じ）")
    if deviation:
        m = float(np.mean([d["pt_mean_abs_vs_baseline2"] for d in deviation]))
        print(f"  提案と対照2の乖離: 平均 {m:.2f} 正答率ポイント（較正曲線に通した予測どうしの差）")
    if args.fig_out:
        gate_max = max(max(x) for x in cfg["visual"]["gates_ms"].values())
        title = ("3条件の進み方（試走・パイロットデータ）" if args.tag else "3条件の進み方")
        note = ("※ 天井データからの試走。知覚的に正しい生成物ではない" if args.tag else "")
        if draw_warp_figure(args.fig_out, tables, dur_ms, base_ms, gate_max, title, note):
            print(f"  図: {args.fig_out}")
        else:
            print("  （matplotlib が無いため図は作っていない）")
    if out["demo"]:
        print("  ※ これは試走・動作確認用の表です。本番の生成には使わないこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
