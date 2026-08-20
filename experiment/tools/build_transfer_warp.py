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

入力(--curves) の形
-------------------
{
  "audio":  {"あ": {"t_ms": [20,40,...], "q": [0.02,0.10,...]}, ...},
  "visual": {"fade": {"あ": {"s": [0.06,0.13,...], "q": [0.01,0.08,...]}, ...},
             "reveal": {...}, "blur": {...}, "wipe": {...}}
}
q は「まぐれ当たりと押し間違いの分を除いて 0〜1 に直した識別の進み具合」(計画書 6.1)。
曲線の当てはめ(単調性の制約つきの回帰)は分析側で済ませ、ここには**単調な数値列**として渡す。
このスクリプトがするのは逆引き・線形補間・端の丸めと、対照条件の生成だけである。

範囲外の丸め(計画書 6.1「範囲の外に出る部分は端に丸め、丸めが起きた範囲を記録・報告する」)
は clipped_ms として出力に残す。

使い方
------
  # 実データから（較正の分析結果を curves.json にしてから）
  python3 experiment/tools/build_transfer_warp.py --curves curves.json

  # 動作確認用のダミー（S字の仮の曲線から作る。**本番データには使わない**）
  python3 experiment/tools/build_transfer_warp.py --demo --out /tmp/transfer_warp.json
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

    戻り値: (s, 丸めたか)。q_target が測った範囲の外なら端に丸める。
    """
    s = np.asarray(s_grid, float)
    q = monotone(q_grid)
    if q_target <= q[0]:
        return float(s[0]), q_target < q[0] - 1e-9
    if q_target >= q[-1]:
        return float(s[-1]), q_target > q[-1] + 1e-9
    i = int(np.searchsorted(q, q_target))
    q0, q1 = q[i - 1], q[i]
    if q1 - q0 < 1e-12:
        return float(s[i]), False
    f = (q_target - q0) / (q1 - q0)
    return float(s[i - 1] + f * (s[i] - s[i - 1])), False


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


def best_affine(t_ms, qa, s_grid, qv):
    """対照2: qV(a·t+b) が音声の曲線 qA(t) に最も近くなる (a,b) を探す。

    「近さ」は評価時点での差の二乗和(計画書 6.2 の距離 E と同じ考え方)。
    格子を粗く→細かく2段階で探す(閉じた式が無い代わりに、決定的で再現できる探索)。
    """
    t = np.asarray(t_ms, float)
    qa = np.asarray(qa, float)
    best = (None, None, float("inf"))
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
                if err < best[2]:
                    best = (float(a), float(b), err)
        a, b, _ = best
        da, db = (a_hi - a_lo) / 40.0, (b_hi - b_lo) / 40.0
        a_lo, a_hi = max(1e-5, a - da), a + da
        b_lo, b_hi = b - db, b + db
    return best[0], best[1]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--curves", default=None, help="較正の曲線 JSON(上の説明の形)")
    ap.add_argument("--demo", action="store_true", help="仮のS字曲線で動作確認用の表を作る")
    ap.add_argument("--config", default=os.path.join(EXP, "transfer_config.js"))
    ap.add_argument("--out", default=os.path.join(EXP, "transfer_warp.json"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.demo:
        curves = demo_curves(cfg)
    elif args.curves:
        with open(args.curves, encoding="utf-8") as f:
            curves = json.load(f)
    else:
        raise SystemExit("--curves か --demo のどちらかを指定してください")

    base_ms = float(cfg["visual"]["base_anim_ms"])
    # 数値列の長さ: 群Bの最も遅い打ち切り時刻まで(＋余白1フレーム)。
    gate_table = cfg["visual"]["gates_ms"]
    max_gate = max(max(v) for v in gate_table.values())
    dur_ms = max(max_gate, base_ms)

    tables, clipped, affine_log = {}, [], {}
    for fam, per_char in curves["visual"].items():
        tables[fam] = {}
        for ch, v in per_char.items():
            if ch not in curves["audio"]:
                continue
            a_t = curves["audio"][ch]["t_ms"]
            a_q = curves["audio"][ch]["q"]
            s_grid, q_grid = v["s"], v["q"]

            # 提案: 各時点で「音声と同じ分かり具合」になる s を逆引きする。
            s_prop, n_clip = [], 0
            for t, q in zip(a_t, a_q):
                s, was_clipped = invert(s_grid, q_grid, q)
                s_prop.append(s)
                if was_clipped:
                    n_clip += 1
            if n_clip:
                clipped.append({"family": fam, "char": ch, "n_clipped": n_clip, "n_points": len(a_t)})

            # 対照2: 較正データだけから決める最良の1次変換。
            a, b = best_affine(a_t, a_q, s_grid, q_grid)
            affine_log[f"{fam}|{ch}"] = {"a": round(a, 6), "b": round(b, 4)}

            n = int(math.ceil(dur_ms / FRAME_MS)) + 1
            grid = np.arange(n) * FRAME_MS
            tables[fam][ch] = {
                "proposed": series_from_s_of_t(a_t, s_prop, dur_ms),
                "baseline1": [round(float(min(1.0, max(0.0, t / base_ms))), 5) for t in grid],
                "baseline2": [round(float(min(1.0, max(0.0, a * t + b))), 5) for t in grid],
            }

    out = {
        "generated_by": "experiment/tools/build_transfer_warp.py",
        "demo": bool(curves.get("_demo")),
        "frame_ms": round(FRAME_MS, 5),
        "duration_ms": dur_ms,
        "base_anim_ms": base_ms,
        "config_version": cfg.get("config_version", ""),
        "affine": affine_log,
        "clipped": clipped,
        "tables": tables,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    fams = ", ".join(f"{k}:{len(v)}字" for k, v in tables.items())
    print(f"書き出し: {args.out}")
    print(f"  方式ごとの字数: {fams}  数値列の長さ: {len(next(iter(next(iter(tables.values())).values()))['proposed'])} 点"
          f"（{FRAME_MS:.3f}ms 刻み・{dur_ms:.0f}ms まで）")
    if clipped:
        print(f"  端に丸めが起きた組合せ: {len(clipped)}（内訳は出力の clipped）")
    if out["demo"]:
        print("  ※ これは仮のS字曲線から作った動作確認用の表です。本番の生成には使わないこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
