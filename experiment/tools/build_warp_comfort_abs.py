#!/usr/bin/env python3
# =========================================================================
# 見え心地（群C）用・絶対値版の進み方の表を作る（2026-08-30）
#
#   ■ 相対版（transfer_warp_comfort.json）と何が違うか
#   相対版は「その曲線自身の到達点＝1」とする物差し（q）で合わせるため、
#   音声が最後まで28%しか分からない「し」でも、視覚は完成形（読める字）で終わる。
#   **実際には聞き取れていないのに、視覚では読める**——ここが嘘になる（丸山指摘）。
#
#   絶対値版は「音声がその時点で伝えている量（正答率／情報量そのもの）」を
#   視覚でも超えないように作る。
#     ①② 形まで: s(t) = V^-1( A(t) )   ※Aは正規化しない生の値
#     ③④ 中点だけ: 開始を t0 ずらした等速。ただし視覚の値が
#                   音声の到達点 U_a に達したところで止める（それ以上進めない）
#   「が」は音声がほぼ何も伝えていない（正答率3.3%）ので、①③はほぼ白のまま。
#   これは失敗ではなく**入力音声の測定結果をそのまま視覚化した出力**として残す。
#
#   出力: experiment/transfer_warp_comfort_abs.json（**配布物には入れない。確認用**）
#         project/data_calib2_live/warp_exp_c/abs_review.csv（全セルの数字）
# =========================================================================
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from analyze_information import BitsCurve  # noqa: E402

CURVES = os.path.join(ROOT, "project", "data_calib2_live",
                      "analysis_information", "curves_info.csv")
MIDS = os.path.join(ROOT, "project", "data_calib2_live",
                    "warp_exp_c", "midpoints_exp_c.csv")
REL = os.path.join(ROOT, "experiment", "transfer_warp_comfort.json")
OUT = os.path.join(ROOT, "experiment", "transfer_warp_comfort_abs.json")
REVIEW = os.path.join(ROOT, "project", "data_calib2_live",
                      "warp_exp_c", "abs_review.csv")

FRAME_MS = 1000.0 / 60.0
BASE_MS = 300.0
CHARS = ["あ", "か", "が", "し", "つ", "ぱ", "ま", "ら"]
FAMS = ["fade", "reveal", "blur", "wipe"]
FJ = {"fade": "うすい", "reveal": "点が増える", "blur": "ぼやけ", "wipe": "端から"}


def load_curves():
    cur = {}
    for x in csv.DictReader(open(CURVES, encoding="utf-8")):
        xs = [float(v) for v in x["xs"].split("|")]
        ys = [float(v) for v in x["ys"].split("|")]
        # 聴覚は打ち切り時刻(ms)が対数間隔なので対数軸、視覚は進み具合(%)。
        cur[(x["target"], x["modality"], x["family"], x["char"])] = \
            BitsCurve(xs, ys, scale="log" if x["modality"] == "audio" else "linear")
    return cur


def load_mids():
    mid = {}
    for x in csv.DictReader(open(MIDS, encoding="utf-8")):
        axis = "acc" if x["axis"] == "acc" else "info"
        key = (axis, x["modality"], x["family"], x["char"])
        # censored_low（つ の正答率）は「10ms以下のどこか」を10msに置いた境界の値。
        # 外すのではなく境界値として使う（2026-08-29 の決定。論文に明記する）。
        mid[key] = dict(midpoint=float(x["midpoint"]) if x["midpoint"] else None,
                        ok=(x["T50_status"] in ("ok", "censored_low")))
    return mid


def series_shape(ca, cv, audio_end):
    """①②: 各コマ時刻の音声の生の値を、視覚の曲線で逆引きする。"""
    n = int(np.ceil(audio_end / FRAME_MS)) + 1
    ts = np.arange(n) * FRAME_MS
    s, lo, hi = [], 0, 0
    for t in ts:
        y = float(ca.v(min(t, audio_end)))
        x, fl = cv.inv(y)
        lo += (fl == "low")
        hi += (fl == "high")
        s.append(x / 100.0)
    s = np.maximum.accumulate(np.array(s))
    return s.tolist(), lo, hi


def series_mid(cv, t_half, s_half_pct, u_audio):
    """③④: 開始を t0 ずらした等速。視覚の値が音声の到達点に達したら止める。"""
    s_cut_pct, _fl = cv.inv(float(u_audio))          # 止める進み具合
    if t_half is None or s_half_pct is None:
        # 中点が決まらない（が の正答率）。合わせられないので、
        # 等速で s_cut まで進めるだけにする（ほぼ白のまま終わる）。
        t0 = 0.0
    else:
        t0 = float(t_half) - (float(s_half_pct) / 100.0) * BASE_MS
    t_end = max(t0 + (s_cut_pct / 100.0) * BASE_MS, FRAME_MS)
    n = int(np.ceil(t_end / FRAME_MS)) + 1
    ts = np.arange(n) * FRAME_MS
    s = np.clip(100.0 * (ts - t0) / BASE_MS, 0.0, s_cut_pct) / 100.0
    return np.maximum.accumulate(s).tolist(), s_cut_pct, t0


def main():
    cur = load_curves()
    mid = load_mids()
    rel = json.load(open(REL, encoding="utf-8"))

    conds = [("c1_acc_shape", "①", "acc", "shape"),
             ("c2_info_shape", "②", "info", "shape"),
             ("c3_acc_mid", "③", "acc", "mid"),
             ("c4_info_mid", "④", "info", "mid")]

    tables = {f: {c: {} for c in CHARS} for f in FAMS}
    rows = []
    for key, no, axis, how in conds:
        for fam in FAMS:
            for ch in CHARS:
                ca = cur[(axis, "audio", "", ch)]
                cv = cur[(axis, "visual", fam, ch)]
                audio_end = ca.xhi
                if how == "shape":
                    s, nlo, nhi = series_shape(ca, cv, audio_end)
                    note = f"下clamp{nlo} 上clamp{nhi}"
                else:
                    ma = mid[(axis, "audio", "", ch)]
                    mv = mid[(axis, "visual", fam, ch)]
                    t_half = ma["midpoint"] if ma["ok"] else None
                    s_half = mv["midpoint"] if mv["ok"] else None
                    s, s_cut, t0 = series_mid(cv, t_half, s_half, ca.top)
                    note = (f"止め{s_cut:.1f}% t0={t0:.0f}ms"
                            + ("" if (t_half is not None) else " 中点なし→合わせず"))
                tables[fam][ch][key] = [round(v, 6) for v in s]
                rows.append(dict(
                    cond=no, family=FJ[fam], char=ch,
                    start_pct=round(s[0] * 100, 1), end_pct=round(s[-1] * 100, 1),
                    dur_ms=round((len(s) - 1) * FRAME_MS),
                    audio_end_ms=round(audio_end),
                    audio_top=round(ca.top, 4), note=note))
        # 等速の対照は相対版から写す
    for fam in FAMS:
        for ch in CHARS:
            tables[fam][ch]["linear"] = rel["tables"][fam][ch]["linear"]

    out = dict(rel)
    out["generated_by"] = "experiment/tools/build_warp_comfort_abs.py"
    out["normalization"] = ("absolute: 音声の生の値（正答率／情報量）を視覚でも超えない。"
                            "③④は音声の到達点相当で止める")
    out["tables"] = tables
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    with open(REVIEW, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("書き出し: %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1024))
    print("確認表 : %s (%d 行)" % (REVIEW, len(rows)))
    print()
    print("%-3s %-7s %-3s %7s %7s %7s %9s  %s" %
          ("条件", "方式", "字", "始め%", "終わり%", "長さms", "音声端ms", "備考"))
    for r in rows:
        print("%-3s %-7s %-3s %7.1f %7.1f %7d %9d  %s" %
              (r["cond"], r["family"], r["char"], r["start_pct"], r["end_pct"],
               r["dur_ms"], r["audio_end_ms"], r["note"]))


if __name__ == "__main__":
    main()
