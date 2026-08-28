#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=========================================================================
中点だけを合わせた warp 表を書き出す（warp_mid ＝ 条件③④）
=========================================================================

4つの「合わせ方」のうちの右列
-----------------------------
較正のデータは 2 通りに読める（正答率 / 情報量）。合わせ方も 2 通りある
（形まで合わせる / 中点だけ合わせる）。2×2 で 4 条件になる。

                       形まで合わせる          中点だけ合わせる
    正答率            ① warp_v5_acc          ③ warp_mid_acc   ← ここで作る
    情報量            ② warp_v5_info         ④ warp_mid_info  ← ここで作る

  ①② は「時刻 t →〔聴覚の曲線〕→ 目標の値 →〔視覚の曲線を逆引き〕→ 進み具合 s」
     で、進み方そのものを歪める（曲線の形まで写す）。
  ③④ は **進み方を歪めない**。等速のまま、**開始時刻 t0 だけをずらす**。
     ずらし量は「聴覚の中点」と「視覚の中点」が同じ時刻に来るように決める。

        s(t) = clip( 100 * (t - t0) / base_anim_ms , 0, 100 )
        t0   = t_half(聴覚)  −  s_half(視覚)/100 * base_anim_ms

中点の定義
----------
**単調回帰の曲線が最大水準で到達する値（＝天井）の半分に達する、最小の x**。

  ・聴覚 … x は時刻ms。天井は最大打ち切り時刻での値。中点は時刻 t_half。
  ・視覚 … x は進み具合 s(%)。天井は s=100% での値。中点は進み具合 s_half。

  ⚠ 「実測の最大値の半分」ではなく「天井の半分」を採る。単調回帰は測った範囲の
    外へ外挿しないので両者はほとんど一致するが（差は下の [5] で毎回検算して出す）、
    実測の最大値は「7点のうち一番高いところを選ぶ」という最大値選択の偏りを持つ。
    天井（袋詰め PAVA の端の値）は袋の平均なのでその偏りが小さい。

  ⚠ 曲線の下端がすでに半分を超えている字がある（例: 「つ」の正答率は 10ms で
    0.391、天井 0.692 の半分 0.346 をすでに上回る）。このとき BitsCurve.inv は
    測った範囲の下端（＝最初の打ち切り時刻）を返す。中点が窓の外にあるという事実は
    build_log_mid.csv の mid_outside 列に残す。

曲線はどこから来るか
--------------------
project/data_calib2_live/analysis_information/curves_info.csv
（analyze_information.py が袋詰め PAVA ＝ build_warp_b4.pava で推定したもの）。
**推定はやり直さない。** ①②③④ の 4 条件が同じ 1 組の曲線を共有することで、
条件間の違いが「軸の選び方」と「合わせ方」だけから来ることが保証される。

出力（project/data_calib2_live/warp_mid/）
    transfer_warp_mid_acc.json    ③ 50%正答率揃え
    transfer_warp_mid_info.json   ④ 50%エントロピー揃え
    build_log_mid.csv             ③④ のセルごとの中点・ずらし量・可動域
    gate_metrics_4cond.csv        ①②③④ × 4方式 × 8字 の打ち切り7点での数値
    ceiling_vs_observed.csv       「天井の半分」と「実測maxの半分」の食い違い

本番の experiment/transfer_warp.json は**書き換えない**。

使い方:
    python3 experiment/tools/build_warp_mid.py
========================================================================="""
import io
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_warp_b4 as B4                                        # noqa: E402
from analyze_information import BitsCurve, invert, fit_affine     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAL = os.path.join(ROOT, "project", "data_calib2_live")
SRC = os.path.join(CAL, "analysis_information", "curves_info.csv")
LEVELS = os.path.join(CAL, "analysis_information", "info_by_char_level.csv")
V5 = os.path.join(CAL, "warp_v5_info")
OUT = os.path.join(CAL, "warp_mid")

CHARS = B4.CHARS
FAMS = B4.FAMS
LAB = B4.LAB
GATES_MS = B4.GATES_MS
FRAME_MS = B4.FRAME_MS
BASE_ANIM_MS = B4.BASE_ANIM_MS
DURATION_MS = B4.DURATION_MS

# 4条件。key は出力・プレビュー共通の識別子。
COND = [
    ("acc_shape",  "① 正答率揃え（形まで）",       os.path.join(V5, "transfer_warp_v5_acc.json")),
    ("info_shape", "② エントロピー揃え（形まで）", os.path.join(V5, "transfer_warp_v5_info.json")),
    ("acc_mid",    "③ 50%正答率揃え",              os.path.join(OUT, "transfer_warp_mid_acc.json")),
    ("info_mid",   "④ 50%エントロピー揃え",        os.path.join(OUT, "transfer_warp_mid_info.json")),
]


# ===========================================================================
# 1. 曲線を読む（build_warp_v5_info.load_curves と同一）
# ===========================================================================
def load_curves(path, scale="log"):
    if not os.path.exists(path):
        raise SystemExit(
            "curves_info.csv が無い。先に情報量の分析を回すこと:\n"
            "    python3 experiment/tools/analyze_information.py\n"
            f"  探した場所: {path}")
    d = pd.read_csv(path)
    out = {}
    for tag in ("acc", "info"):
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


def half_point(curve):
    """天井の半分に達する最小の x。戻り値 (x, flag)。flag は 'low'/'high'/None。"""
    return curve.inv(curve.top / 2.0)


# ===========================================================================
# 2. 絵の量子化（真っ白／完全に見えている の判定に使う）
# ===========================================================================
def endpoint_levels(fam, ch, ink, bw):
    """s=0（何も出ていない絵）と s=100（完全に見えている絵）の量子化水準。"""
    z = B4.quant_levels(fam, ch, np.array([0.0, 100.0]), ink, bw)
    return float(z[0]), float(z[1])


def picture_stats(fam, ch, s_pct, ink, bw, win_lo, win_hi, cva=None):
    """打ち切り7点の s から「絵がどうなっているか」を数える。

    物差しは3つ。どれか1つでは足りない。

    ① 絵として別か（量子化）
       n_distinct … 別々の絵が何枚あるか（量子化水準の異なり数）
       n_blank    … s=0 の絵と**同一**の点の数（うすい=不透明度0 / 点が増える=0画素 /
                    端から=0列 / ぼやけ=ぼかし半径が最大の72px）
       n_full     … s=100 の絵と**同一**の点の数
       ⚠ うすいは不透明度が 0〜255 の256段あるので、実際には読めない差
         （不透明度 1 と 2 の違いなど）でも「別の絵」に数えられてしまう。
         この列だけで「段階的に見える」と言ってはいけない。

    ② 実用域に入っているか
       n_below/n_above … 正答率曲線の可動域 5%〜95% の外に出た点の数。
                        下＝ほぼ何も読み取れない、上＝もう読み切れている。

    ③ 読み取れる度合いそのもの（いちばん直接的）
       read_at_gates … その進み具合の絵を較正の正答率曲線に通した値（0〜1）。
       read_span     … その7点での最大−最小。小さいほど「絵は変わっても
                      読み取れ方が変わっていない」＝潰れている。
       n_read_mid    … 読み取れる度合いが 0.1〜0.9 に入っている点の数
                      （＝天井にも床にも張り付いていない、中間の絵）。
    """
    s = np.asarray(s_pct, dtype=float)
    lv = B4.quant_levels(fam, ch, s, ink, bw)
    z0, z1 = endpoint_levels(fam, ch, ink, bw)
    out = dict(
        n_distinct=int(len(np.unique(lv))),
        n_blank=int((lv == z0).sum()),
        n_full=int((lv == z1).sum()),
        n_below=int((s < win_lo).sum()),
        n_above=int((s > win_hi).sum()),
        levels="|".join(f"{v:.0f}" for v in lv))
    if cva is not None:
        rd = cva.v(s)
        lo = cva.bottom + 0.10 * (cva.top - cva.bottom)
        hi = cva.bottom + 0.90 * (cva.top - cva.bottom)
        out["read"] = "|".join(f"{v:.3f}" for v in rd)
        out["read_span"] = float(rd.max() - rd.min())
        out["n_read_mid"] = int(((rd > lo) & (rd < hi)).sum())
    return out


# ===========================================================================
# 3. ③④ を作る
# ===========================================================================
def build_mid(CA, CV, tag, ts, gates_of, ink, bw, win, CV_acc):
    tables, log = {}, []
    for fam in FAMS:
        tables[fam] = {}
        for ch in CHARS:
            g = gates_of[ch]
            ca, cv = CA[ch], CV[(ch, fam)]
            t_half, fa = half_point(ca)
            s_half, fv = half_point(cv)
            # 等速のまま開始時刻だけずらす
            t0 = t_half - (s_half / 100.0) * BASE_ANIM_MS
            prop = np.clip(100.0 * (ts - t0) / BASE_ANIM_MS, 0.0, 100.0)
            # 対照は①②とまったく同じ物を入れる（条件間で対照が動かないように）
            targ = ca.v(ts)
            a, b = fit_affine(ts, targ, cv)
            b2 = np.clip(a * ts + b, 0.0, 100.0)
            b1 = np.clip(100.0 * ts / BASE_ANIM_MS, 0.0, 100.0)
            tables[fam][ch] = {
                "proposed": [round(float(x) / 100.0, 8) for x in prop],
                "baseline1": [round(float(x) / 100.0, 8) for x in b1],
                "baseline2": [round(float(x) / 100.0, 8) for x in b2]}

            # ⚠ 打ち切り点の値は「式の値」ではなく **書き出した数値列を transfer.js と
            #   同じ線形補間で読み直したもの** を使う。60Hz の枠のあいだは直線で
            #   つながれるので、s が 0 から立ち上がる折れ点が枠と枠のあいだにあると
            #   式の値と食い違う（うすい・点が増える で数ポイント動く）。
            #   参加者が実際に見るのは後者なので、判定も後者でやる。
            pg = series_at(np.array(tables[fam][ch]["proposed"]) * 100.0, g, FRAME_MS)
            st = picture_stats(fam, ch, pg, ink, bw, *win[(ch, fam)],
                               cva=CV_acc[(ch, fam)])
            span_g = float(pg.max() - pg.min())
            if span_g < 1.0:
                judge = "不成立（動かない）"
            elif st["n_read_mid"] <= 1:
                judge = "潰れる（中間の絵が1点以下）"
            elif st["n_distinct"] <= 2:
                judge = "一部成立（絵が2枚以下）"
            else:
                judge = "成立"
            log.append(dict(
                target=tag, family=fam, family_ja=LAB[fam], char=ch,
                target_unit=("bit" if tag == "info" else "正答率"),
                audio_bottom=round(ca.bottom, 5), audio_top=round(ca.top, 5),
                audio_half=round(ca.top / 2.0, 5),
                t_half_ms=round(float(t_half), 3),
                t_half_flag=(fa or ""),
                gate_first_ms=float(g[0]), gate_last_ms=float(g[-1]),
                mid_outside=("下（最初の打ち切りで既に半分超）" if fa == "low"
                             else ("上（最後の打ち切りでも半分未満）" if fa == "high" else "")),
                visual_bottom=round(cv.bottom, 5), visual_top=round(cv.top, 5),
                visual_half=round(cv.top / 2.0, 5),
                s_half_pct=round(float(s_half), 4),
                s_half_flag=(fv or ""),
                t0_ms=round(float(t0), 3),
                # t0 が負なら、アニメは t=0 の時点ですでに途中まで進んでいる
                # （ぼやけは最初のフレームで半分ほどくっきりしている）。
                s_at_zero=round(float(prop[0]), 3),
                s_min=round(float(prop.min()), 4), s_max=round(float(prop.max()), 4),
                span_pt=round(float(prop.max() - prop.min()), 4),
                span_pt_gates=round(span_g, 4),
                s_at_gates="|".join(f"{x:.3f}" for x in pg),
                s_at_gates_exact="|".join(
                    f"{x:.3f}" for x in
                    np.clip(100.0 * (g - t0) / BASE_ANIM_MS, 0.0, 100.0)),
                usable_lo=round(win[(ch, fam)][0], 3),
                usable_hi=round(win[(ch, fam)][1], 3),
                n_distinct_at_gates=st["n_distinct"],
                n_blank=st["n_blank"], n_full=st["n_full"],
                n_below_usable=st["n_below"], n_above_usable=st["n_above"],
                quant_levels_at_gates=st["levels"],
                read_at_gates=st["read"], read_span=round(st["read_span"], 4),
                n_read_mid=st["n_read_mid"],
                judgement=judge, b2_a=round(a, 5), b2_b=round(b, 3)))
    return tables, log


def write_json(path, tables, tag):
    note = ("目標＝相互情報量の字ごとの分け前 D_c = KL(P(R|c,x)‖P(R|x))。"
            if tag == "info" else "目標＝正答率（生の割合。λ正規化しない）。")
    doc = {"generated_by": "experiment/tools/build_warp_mid.py",
           "estimator": "isotonic_bagged / midpoint_shift_only",
           "target": tag,
           "align": "midpoint",
           "frame_ms": round(FRAME_MS, 6),
           "duration_ms": DURATION_MS,
           "base_anim_ms": BASE_ANIM_MS,
           "meta": {"space": "rawp", "made": "2026-08-29", "chars": CHARS,
                    "families": FAMS,
                    "curve_source": os.path.relpath(SRC, ROOT),
                    "rule": "等速のまま開始時刻だけずらす。"
                            "s(t)=clip(100*(t-t0)/base_anim_ms,0,100)、"
                            "t0=t_half(聴覚)-s_half(視覚)/100*base_anim_ms。"
                            "中点は「単調回帰の曲線が最大水準で到達する値の半分」に"
                            "達する最小の x。",
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


# ===========================================================================
# 4. 4条件を同じ物差しで測る
# ===========================================================================
def series_at(arr, ms, frame_ms):
    """transfer.js の seriesAt と同じ線形補間。参加者が実際に見る値をそのまま読む。"""
    n = len(arr)
    x = np.clip(np.asarray(ms, dtype=float) / frame_ms, 0, n - 1)
    lo = np.floor(x).astype(int)
    hi = np.minimum(lo + 1, n - 1)
    f = x - lo
    return arr[lo] * (1 - f) + arr[hi] * f


def gate_metrics(gates_of, ink, bw, win, CV_acc):
    rows = []
    for key, label, path in COND:
        if not os.path.exists(path):
            raise SystemExit(f"{path} が無い（条件 {label}）")
        doc = json.load(io.open(path, encoding="utf-8"))
        fm = float(doc["frame_ms"])
        for fam in FAMS:
            for ch in CHARS:
                g = np.array(gates_of[ch], float)
                arr = np.array(doc["tables"][fam][ch]["proposed"], float) * 100.0
                pg = series_at(arr, g, fm)
                st = picture_stats(fam, ch, pg, ink, bw, *win[(ch, fam)],
                                   cva=CV_acc[(ch, fam)])
                rows.append(dict(
                    cond=key, cond_ja=label, family=fam, family_ja=LAB[fam], char=ch,
                    gates_ms="|".join(f"{x:.0f}" for x in g),
                    s_at_gates="|".join(f"{x:.2f}" for x in pg),
                    s_min=round(float(pg.min()), 3), s_max=round(float(pg.max()), 3),
                    span_pt=round(float(pg.max() - pg.min()), 3),
                    # t=0 の進み具合。③④ は t0 が負になることがあり、そのときアニメは
                    # 「途中から始まる」（ぼやけは最初のフレームで既に半分ほどくっきりしている）。
                    s_at_zero=round(float(arr[0]), 3),
                    n_distinct=st["n_distinct"], n_blank=st["n_blank"], n_full=st["n_full"],
                    n_below_usable=st["n_below"], n_above_usable=st["n_above"],
                    usable_lo=round(win[(ch, fam)][0], 2),
                    usable_hi=round(win[(ch, fam)][1], 2),
                    read_at_gates=st["read"], read_span=round(st["read_span"], 4),
                    n_read_mid=st["n_read_mid"],
                    quant_levels="|".join(f"{v:.0f}" for v in
                                          B4.quant_levels(fam, ch, pg, ink, bw))))
    return pd.DataFrame(rows)


def ceiling_check(CA, CV, tag):
    """「天井の半分」と「実測maxの半分」で中点がどれだけ動くかを実際に測る。"""
    lv = pd.read_csv(LEVELS)
    col = "accuracy_raw" if tag == "acc" else "bits_corrected"
    rows = []
    for ch in CHARS:
        s = lv[(lv.modality == "audio") & (lv.char == ch) & (lv.level_index != 99)]
        obs = float(s[col].max())
        ca = CA[ch]
        t1, f1 = ca.inv(ca.top / 2.0)
        t2, f2 = ca.inv(obs / 2.0)
        rows.append(dict(target=tag, modality="audio", char=ch, family="",
                         ceiling=round(ca.top, 5), observed_max=round(obs, 5),
                         x_from_ceiling=round(float(t1), 4),
                         x_from_observed=round(float(t2), 4),
                         diff=round(abs(float(t1) - float(t2)), 4)))
    lvv = lv[lv.modality == "visual"]
    for fam in FAMS:
        for ch in CHARS:
            s = lvv[(lvv.family == fam) & (lvv.char == ch) & (lvv.level_index != 99)]
            if len(s) == 0:
                continue
            obs = float(s[col].max())
            cv = CV[(ch, fam)]
            s1, _ = cv.inv(cv.top / 2.0)
            s2, _ = cv.inv(obs / 2.0)
            rows.append(dict(target=tag, modality="visual", char=ch, family=fam,
                             ceiling=round(cv.top, 5), observed_max=round(obs, 5),
                             x_from_ceiling=round(float(s1), 4),
                             x_from_observed=round(float(s2), 4),
                             diff=round(abs(float(s1) - float(s2)), 4)))
    return pd.DataFrame(rows)


# ===========================================================================
def main():
    os.makedirs(OUT, exist_ok=True)
    print("[1] 曲線を読む（袋詰め PAVA 済み・推定はやり直さない）")
    print(f"    {os.path.relpath(SRC, ROOT)}")
    curves = load_curves(SRC)

    n = int(math.ceil(DURATION_MS / FRAME_MS)) + 1
    ts = np.array([i * FRAME_MS for i in range(n)])
    gates_of = {ch: np.array(GATES_MS.get(ch, GATES_MS["_default"]), float) for ch in CHARS}
    ink, bw = B4.glyph_stats(os.path.join(ROOT, "experiment", "base"))
    if not ink:
        raise SystemExit("字画像が読めない（PIL が要る）。pip3 install pillow")

    # 実用域は「正答率曲線の可動域 5%〜95%」で固定する。
    # 4条件を同じ物差しで測るため、条件ごとに変えない。
    CA_a, CV_a = curves["acc"]
    win = {(ch, fam): CV_a[(ch, fam)].window(0.05, 0.95) for fam in FAMS for ch in CHARS}
    print("[2] 実用域（正答率曲線の可動域5%〜95%・進み具合 %）と、③④ がそこを走り抜ける時間")
    print("    ③④ は等速（300ms で 0→100%）なので、走り抜ける時間 = 実用域の幅 ×3ms/pt。")
    print("    打ち切りの間隔（10〜40ms）より短ければ、実用域の中に絵が1〜2枚しか落ちない。")
    for fam in FAMS:
        w = [win[(ch, fam)] for ch in CHARS]
        tr = [(b - a) * BASE_ANIM_MS / 100.0 for a, b in w]
        print(f"    {LAB[fam]:6s} 実用域 {min(a for a, _ in w):5.1f}〜{max(b for _, b in w):5.1f}%"
              f"  走り抜ける時間 {min(tr):6.1f}〜{max(tr):6.1f}ms（中央 {np.median(tr):5.1f}ms）")
        print("           " + " ".join(f"{ch}:{a:.1f}-{b:.1f}%={t:.0f}ms"
                                       for ch, (a, b), t in zip(CHARS, w, tr)))
    gaps = [np.diff(gates_of[ch]) for ch in CHARS]
    allg = np.concatenate(gaps)
    print(f"    参考: 打ち切りの間隔は {allg.min():.0f}〜{allg.max():.0f}ms"
          f"（中央 {np.median(allg):.0f}ms）")

    print("[3] ③④ を作る（等速のまま開始時刻だけずらす）")
    logs = []
    for tag, lab in (("acc", "③ 50%正答率揃え"), ("info", "④ 50%エントロピー揃え")):
        CA, CV = curves[tag]
        tables, log = build_mid(CA, CV, tag, ts, gates_of, ink, bw, win, CV_a)
        logs += log
        write_json(os.path.join(OUT, f"transfer_warp_mid_{tag}.json"), tables, tag)
        cnt = pd.Series([r["judgement"] for r in log]).value_counts()
        print(f"    {lab}: " + " / ".join(f"{k} {v}セル" for k, v in cnt.items()))
    df = pd.DataFrame(logs)
    df.to_csv(os.path.join(OUT, "build_log_mid.csv"), index=False)
    print(f"  書き出し: build_log_mid.csv（{len(df)} 行）")

    print("\n[4] 中点が打ち切り窓の外に出る字")
    d = df[(df.family == "fade") & (df.mid_outside != "")]
    if len(d) == 0:
        print("    聴覚側: なし")
    for r in d.itertuples():
        print(f"    聴覚 {r.target}/{r.char}: 下端 {r.audio_bottom} ≥ 半分 {r.audio_half} "
              f"→ 中点は最初の打ち切り {r.t_half_ms}ms（{r.mid_outside}）")
    for tag in ("acc", "info"):
        s = df[df.target == tag]
        out = s[(s.t_half_ms < s.gate_first_ms - 1e-9) | (s.t_half_ms > s.gate_last_ms + 1e-9)]
        chs = sorted(set(out.char))
        print(f"    {tag}: 中点時刻が窓 [最初,最後] の外 … {chs if chs else 'なし'}")

    print("\n[5] 「天井の半分」と「実測maxの半分」の食い違い（検算）")
    cc = []
    for tag in ("acc", "info"):
        CA, CV = curves[tag]
        cc.append(ceiling_check(CA, CV, tag))
    cc = pd.concat(cc, ignore_index=True)
    cc.to_csv(os.path.join(OUT, "ceiling_vs_observed.csv"), index=False)
    a = cc[(cc.modality == "audio")]
    print(f"    聴覚（単位ms）: 中央値 {a['diff'].median():.3f}ms / 最大 {a['diff'].max():.3f}ms")
    v = cc[(cc.modality == "visual")]
    print(f"    視覚（単位 進み具合pt）: 中央値 {v['diff'].median():.3f}pt / 最大 {v['diff'].max():.3f}pt")
    print(f"  書き出し: ceiling_vs_observed.csv（{len(cc)} 行）")

    print("\n[6] 4条件を同じ物差しで測る")
    gm = gate_metrics(gates_of, ink, bw, win, CV_a)
    gm.to_csv(os.path.join(OUT, "gate_metrics_4cond.csv"), index=False)
    print(f"  書き出し: gate_metrics_4cond.csv（{len(gm)} 行）")

    pd.set_option("display.width", 250)
    piv = gm.groupby(["cond_ja", "family_ja"]).agg(
        別々の絵=("n_distinct", "mean"), 中間の絵=("n_read_mid", "mean"),
        読み幅=("read_span", "mean"),
        真っ白=("n_blank", "sum"), 完全一致=("n_full", "sum"),
        下に外れ=("n_below_usable", "sum"), 上に外れ=("n_above_usable", "sum"),
        t0での進み=("s_at_zero", "mean"),
        可動域pt=("span_pt", "mean")).round(2)
    print("\n  --- 4条件×4方式 ---")
    print("      別々の絵/中間の絵 は 1字あたり7点中の平均、真っ白ほかは 8字×7点=56点中の合計")
    print("      中間の絵 … 読み取れる度合いが可動域の 10%〜90% にある点の数")
    print(piv.to_string())

    print("\n  --- 潰れているセル（中間の絵が1点以下） ---")
    for key, lab, _ in COND:
        d = gm[(gm["cond"] == key) & (gm.n_read_mid <= 1)]
        print(f"    {lab}: {len(d)}/32セル"
              + ("" if len(d) == 0 else
                 " … " + "、".join(f"{r.family_ja}×{r.char}" for r in d.itertuples())))

    print("\n完了: " + os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
