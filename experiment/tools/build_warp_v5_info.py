#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=========================================================================
情報量を目標にした warp 表を書き出す（warp_v5_info）
=========================================================================

何をするか
----------
転写(proposed)の手続きは「時刻 t →〔聴覚の曲線〕→ 目標の値 →〔視覚の曲線を
逆に引く〕→ 進み具合 s」である。この**軸に載っている量**を差し替えるだけで、
正答率を目標にした版と情報量を目標にした版の2つができる。

    正答率版 (acc)  … 軸は「正しく答えられた割合」
    情報量版 (info) … 軸は「その回答を見て、どの字が出たかがどれだけ分かるか」
                      ＝ 相互情報量の字ごとの分け前
                         D_c(x) = KL( P(R|c,x) ‖ P(R|x) )  [bit]

  ⚠ どの情報量指標を使うかは experiment/tools/analyze_information.py の
    検討結果に従う。同スクリプトは ① 応答分布のエントロピー H(R|x)、
    ② 事前分布からの情報利得 KL、③ 相互情報量の字ごとの分け前 D_c(x) の
    3つを出したうえで **③ を転写の目標に選んでいる**（①は「何も届いていない
    ときの偏り」と「1つ隣にずれているときの偏り」を区別できず、②は刺激と
    無関係な回答の移動でも増えてしまう。③ は基準がその水準の実測の周辺分布
    P(R|x) なので、事前の偏りが自動的に差し引かれ、字ごとに分けられる）。
    ここでもそれをそのまま使う。

曲線はどこから来るか
--------------------
analyze_information.py が書いた
  project/data_calib2_live/analysis_information/curves_info.csv
に、袋詰め PAVA（単調回帰）で推定した折れ線がそのまま入っている
（target=info / acc、modality=audio / visual、字×方式ごとに xs|ys）。
**推定はやり直さない**（並べ替え検定つきの袋詰めは重い。やり直すと乱数で
ぶれて、レポートや図と数値が食い違う）。ここでは読み直して逆引きするだけ。
逆引き・単調化・対照1/対照2の作り方は analyze_information.warp_table と同一。

出力（project/data_calib2_live/warp_v5_info/）
    transfer_warp_v5_info.json   情報量を目標にした表（transfer.js が読める形）
    transfer_warp_v5_acc.json    正答率を目標にした表（同じ手続き・軸だけ違う）
    build_log_v5.csv             セルごとの可動域・丸め・成立判定

本番の experiment/transfer_warp.json は**書き換えない**。

使い方:
    python3 experiment/tools/build_warp_v5_info.py
========================================================================="""
import io
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_warp_b4 as B4                      # noqa: E402
from analyze_information import BitsCurve, invert, fit_affine   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAL = os.path.join(ROOT, "project", "data_calib2_live")
SRC = os.path.join(CAL, "analysis_information", "curves_info.csv")
OUT = os.path.join(CAL, "warp_v5_info")

CHARS = B4.CHARS
FAMS = B4.FAMS
LAB = B4.LAB
GATES_MS = B4.GATES_MS
FRAME_MS = B4.FRAME_MS
BASE_ANIM_MS = B4.BASE_ANIM_MS
DURATION_MS = B4.DURATION_MS


def load_curves(path, scale="log"):
    """curves_info.csv → {tag: (CA, CV)}。BitsCurve は analyze_information と同じ物。"""
    if not os.path.exists(path):
        raise SystemExit(
            "curves_info.csv が無い。先に情報量の分析を回すこと:\n"
            "    python3 experiment/tools/analyze_information.py\n"
            f"  探した場所: {path}")
    d = pd.read_csv(path)
    out = {}
    for tag in ("info", "acc"):
        CA, CV = {}, {}
        s = d[d["target"] == tag]
        for r in s.itertuples():
            xs = np.array([float(x) for x in str(r.xs).split("|")])
            ys = np.array([float(y) for y in str(r.ys).split("|")])
            if r.modality == "audio":
                CA[r.char] = BitsCurve(xs, ys, scale=scale,
                                       out_lo=float(xs.min()), out_hi=float(xs.max()))
            else:
                CV[(r.char, r.family)] = BitsCurve(xs, ys, scale=scale,
                                                   out_lo=0.0, out_hi=100.0)
        miss = [ch for ch in CHARS if ch not in CA] + \
               [(ch, f) for f in FAMS for ch in CHARS if (ch, f) not in CV]
        if miss:
            raise SystemExit(f"curves_info.csv に足りない曲線がある（{tag}）: {miss[:5]}")
        out[tag] = (CA, CV)
    return out


def build(CA, CV, tag, ts, gates_of, ink, bw):
    """analyze_information.warp_table と同じ逆引きを、warp 表の形で書き出す。"""
    tables, log = {}, []
    for fam in FAMS:
        tables[fam] = {}
        for ch in CHARS:
            g = gates_of[ch]
            ca, cv = CA[ch], CV[(ch, fam)]
            targ = ca.v(ts)
            prop, nlo, nhi = invert(targ, cv)           # 単調化まで invert の中でやる
            a, b = fit_affine(ts, targ, cv)
            b2 = np.clip(a * ts + b, 0.0, 100.0)
            b1 = np.clip(100.0 * ts / BASE_ANIM_MS, 0.0, 100.0)
            tables[fam][ch] = {
                "proposed": [round(float(x) / 100.0, 8) for x in prop],
                "baseline1": [round(float(x) / 100.0, 8) for x in b1],
                "baseline2": [round(float(x) / 100.0, 8) for x in b2]}
            # 参加者が実際に見る7点での値
            tg = ca.v(g)
            pg, glo, ghi = invert(tg, cv)
            span_g = float(pg.max() - pg.min())
            try:
                ndg = int(len(np.unique(B4.quant_levels(fam, ch, pg, ink, bw))))
            except Exception:
                ndg = -1
            if span_g < 1.0:
                judge = "不成立（動かない）"
            elif (glo + ghi) > 0:
                judge = "一部成立（端で丸め）"
            else:
                judge = "成立"
            jumps = np.diff(prop)
            log.append(dict(
                target=tag, family=fam, family_ja=LAB[fam], char=ch,
                target_unit=("bit" if tag == "info" else "正答率"),
                target_first_gate=round(float(tg[0]), 5),
                target_last_gate=round(float(tg[-1]), 5),
                visual_bottom=round(cv.bottom, 5), visual_top=round(cv.top, 5),
                s_min=round(float(prop.min()), 4), s_max=round(float(prop.max()), 4),
                span_pt=round(float(prop.max() - prop.min()), 4),
                span_pt_gates=round(span_g, 4),
                s_at_gates="|".join(f"{x:.3f}" for x in pg),
                clip_low_gates=int(glo), clip_high_gates=int(ghi),
                n_distinct_at_gates=ndg, judgement=judge,
                max_jump_pt=round(float(jumps.max()) if len(jumps) else 0.0, 4),
                b2_a=round(a, 5), b2_b=round(b, 3)))
    return tables, log


def write_json(path, tables, tag):
    note = ("目標＝相互情報量の字ごとの分け前 D_c = KL(P(R|c,x)‖P(R|x))。"
            "並べ替え検定でバイアスを引き、参加者ブートストラップの袋詰め PAVA で単調化。"
            if tag == "info" else
            "目標＝正答率。曲線は同じ袋詰め PAVA（単調回帰）。"
            "情報量版との違いは『軸に載っている量』だけ。")
    doc = {"generated_by": "experiment/tools/build_warp_v5_info.py",
           "estimator": "isotonic_bagged",
           "target": tag,
           "frame_ms": round(FRAME_MS, 6),
           "duration_ms": DURATION_MS,
           "base_anim_ms": BASE_ANIM_MS,
           "meta": {"space": "rawp", "made": "2026-08-28", "chars": CHARS,
                    "families": FAMS,
                    "curve_source": os.path.relpath(SRC, ROOT),
                    "visual_source": "calib+calib2 両バッチ / 速さ: " + ", ".join(
                        f"{f}={'300ms' if B4.SPEED_BY_FAM[f] else '2水準'}" for f in FAMS),
                    "webkit_excluded_families": sorted(B4.WEBKIT_FAMILIES),
                    "audio_source": "実験1(phase=calib)・速さの区別なし",
                    "note": note,
                    "warning": "研究者用の検討材料。本番には置いていない。"},
           "composite_map": {}, "composite_map_n": 0,
           "tables": tables}
    json.dump(doc, io.open(path, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"  書き出し: {os.path.basename(path)} ({os.path.getsize(path)//1024} KB)")
    return doc


def verify(tables_by_tag, ts):
    """analyze_information.py が出した warp_series.csv と突き合わせる（作り直しの検算）。"""
    p = os.path.join(CAL, "analysis_information", "warp_series.csv")
    if not os.path.exists(p):
        print("  ⚠ warp_series.csv が無いので検算は飛ばす")
        return
    s = pd.read_csv(p)
    worst = 0.0
    where = ""
    for tag, tables in tables_by_tag.items():
        sub = s[s["target"] == tag]
        for fam in FAMS:
            for ch in CHARS:
                g = sub[(sub.family == fam) & (sub.char == ch)].sort_values("frame")
                if len(g) == 0:
                    continue
                mine = np.array(tables[fam][ch]["proposed"]) * 100.0
                ref = g["proposed_s"].to_numpy()
                n = min(len(mine), len(ref))
                dmax = float(np.abs(mine[:n] - ref[:n]).max())
                if dmax > worst:
                    worst, where = dmax, f"{tag}/{LAB[fam]}/{ch}"
    print(f"  検算: warp_series.csv との最大差 {worst:.4f} pt（{where}）"
          + ("  ✓ 一致" if worst < 0.01 else "  ⚠ ずれている"))


def main():
    os.makedirs(OUT, exist_ok=True)
    print("[1] 曲線を読む（袋詰め PAVA 済み・推定はやり直さない）")
    print(f"    {os.path.relpath(SRC, ROOT)}")
    curves = load_curves(SRC)

    n = int(math.ceil(DURATION_MS / FRAME_MS)) + 1
    ts = np.array([i * FRAME_MS for i in range(n)])
    gates_of = {ch: np.array(GATES_MS.get(ch, GATES_MS["_default"]), float) for ch in CHARS}
    ink, bw = B4.glyph_stats(os.path.join(ROOT, "experiment", "base"))

    print(f"[2] 逆引き（{n} 点 = {DURATION_MS:.0f}ms を 60fps で）")
    logs, tabs = [], {}
    for tag in ("info", "acc"):
        CA, CV = curves[tag]
        tables, log = build(CA, CV, tag, ts, gates_of, ink, bw)
        tabs[tag] = tables
        logs += log
        lab = "情報量を目標" if tag == "info" else "正答率を目標"
        cnt = pd.Series([r["judgement"] for r in log]).value_counts()
        print(f"    {lab}: " + " / ".join(f"{k} {v}セル" for k, v in cnt.items()))

    print("[3] 書き出し")
    write_json(os.path.join(OUT, "transfer_warp_v5_info.json"), tabs["info"], "info")
    write_json(os.path.join(OUT, "transfer_warp_v5_acc.json"), tabs["acc"], "acc")
    df = pd.DataFrame(logs)
    df.to_csv(os.path.join(OUT, "build_log_v5.csv"), index=False)
    print(f"  書き出し: build_log_v5.csv（{len(df)} 行）")

    print("[4] 検算")
    verify(tabs, ts)

    print("\n  --- 転写できないセル（7点のあいだで進み具合が 1pt も動かない） ---")
    for tag, lab in (("acc", "正答率を目標"), ("info", "情報量を目標")):
        d = df[(df.target == tag) & (df.judgement == "不成立（動かない）")]
        if len(d) == 0:
            print(f"    {lab}: なし")
        else:
            print(f"    {lab}: {len(d)}セル … "
                  + "、".join(f"{r.family_ja}×{r.char}" for r in d.itertuples()))

    print("\n  --- 「が」だけ取り出す ---")
    print(df[df.char == "が"][["target", "family_ja", "target_first_gate",
                               "target_last_gate", "s_min", "s_max",
                               "span_pt_gates", "n_distinct_at_gates", "judgement"]]
          .to_string(index=False))
    print(f"\n完了: {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
