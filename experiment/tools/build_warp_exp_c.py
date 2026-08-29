#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=========================================================================
実験C（見え心地）で使う 4 条件の進み方を、**新しい中点の定義**で作り直す
=========================================================================

なぜ作り直すか
--------------
これまでの warp_mid（project/data_calib2_live/warp_mid/）は、中点を
「単調回帰の曲線が最大水準で到達する値（＝天井）の半分」で決めていた。
これは誤りだった。当てずっぽうでも一定の割合は当たるので、正答率の「半分」は
0 からではなく**当てずっぽうの水準から**数えなければならない。

新しい定義（analyze_three_indices.py と同じもの）
------------------------------------------------
  下限 L から、その字が到達する上限 U までの、ちょうど半分に達する時刻。

      q(x) = ( v(x) − L ) / ( U − L )        中点 = q(x) = 0.5 になる最小の x

  L … 正答率のとき  聴覚 1/68（回答盤 68 マス）、視覚 1/72（回答盤 72 マス）
      情報量のとき  0（並べ替えで偏りを引いた量なので、届いていなければ 0）
  U … **単調回帰の曲線の終端の値**。観測された最大値ではない
      （最大値は「7点のうち一番高いところを選ぶ」ぶんだけ上に偏る）。

4 つの条件（2×2）
-----------------
                       形まで合わせる          中点だけ合わせる
    正答率            ① acc_shape            ③ acc_mid
    情報量            ② info_shape           ④ info_mid

  ①② 形まで合わせる
      時刻 t →〔聴覚の曲線を q に正規化〕→ q_a(t)
            →〔視覚の曲線の q を逆に引く〕→ 進み具合 s
      進み方そのものを、聴覚で分かっていく形に合わせる。

  ②④ と ①③ の関係
      正規化を①②にも入れたので、**① は必ず中点で③ と同じ点を通る**
      （t = 中点 のとき q_a = 0.5 なので s = 視覚の中点）。
      つまり 2×2 は「軸（正答率／情報量）」×「合わせ方（形まで／中点だけ）」
      だけで違い、中点の決め方は 4 条件で共通になる。

  ③④ 中点だけ合わせる
      進み方は等速のまま。**開始時刻 t0 だけ**をずらして、視覚の中点が
      聴覚の中点と同じ時刻に来るようにする。

          s(t) = clip( 100 * (t − t0) / base_anim_ms , 0, 100 )
          t0   = t_half(聴覚)  −  s_half(視覚)/100 * base_anim_ms

曲線はどこから来るか
--------------------
project/data_calib2_live/analysis_information/curves_info.csv
（analyze_information.py が袋詰め PAVA で推定したもの）。
**推定はやり直さない。** 読み直して逆に引くだけ。
到達点 U が analyze_three_indices.py の U と一致するかは [1] で毎回検算する。

中点が決まらない字
------------------
  ・聴覚 × 正答率 × 「が」 … 到達点 U=3.4%（95%区間 0〜10.2%）が当てずっぽう
    1.47% を含む。到達点そのものが下限と区別できないので、その途中の点も
    定義できない。→ **等速のまま（ずらさない・形も合わせない）**にして、
    build_log の fallback 列に理由を残す。
  ・聴覚 × 正答率 × 「つ」 … いちばん短い打ち切り 10ms ですでに半分を超える。
    中点は測った範囲より前（<10ms）。→ 10ms を中点として使い、
    mid_censored 列に「下（測った範囲より前）」と残す。
  どちらも**実験Cの5字（あ・か・し・ま・ら）には入らない**ので、実験Cの
  提示には影響しない。表を8字ぶん作るのは、確認スクリプトが8字を要求するため。

出力（project/data_calib2_live/warp_exp_c/）
    transfer_warp_c1_acc_shape.json    ① 正答率揃え（形まで）
    transfer_warp_c2_info_shape.json   ② 情報量揃え（形まで）
    transfer_warp_c3_acc_mid.json      ③ 半分・正答率
    transfer_warp_c4_info_mid.json     ④ 半分・情報量
    midpoints_exp_c.csv                中点（聴覚 t_half / 視覚 s_half）と検算
    build_log_exp_c.csv                セルごとの中点・ずらし量・可動域・判定
    gate_progress_exp_c.csv            4条件×4方式×5字 の打ち切り時点ごとの進み具合
    cond_difference_exp_c.csv          条件どうしで絵が実際に違うかの突き合わせ

本番の experiment/transfer.js / transfer_config.js / transfer_warp.json には
**書かない**。読むだけ。

使い方:
    python3 experiment/tools/build_warp_exp_c.py
========================================================================="""
import io
import itertools
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
THREE = os.path.join(CAL, "analysis_three_indices", "three_indices.csv")
OUT = os.path.join(CAL, "warp_exp_c")

CHARS = B4.CHARS                     # 8字（表は8字ぶん作る）
FAMS = B4.FAMS                       # fade / reveal / blur / wipe
LAB = B4.LAB
GATES_MS = B4.GATES_MS
FRAME_MS = B4.FRAME_MS
BASE_ANIM_MS = B4.BASE_ANIM_MS
DURATION_MS = B4.DURATION_MS

# 実験Cで実際に出す字（transfer_comfort_config.js の single_char / sequence）
CHARS_C = ["あ", "か", "し", "ま", "ら"]

# 下限 L（当てずっぽうの水準）。transfer_config.js の回答盤のマス数から。
L_ACC_AUDIO = 1.0 / 68.0
L_ACC_VISUAL = 1.0 / 72.0
L_INFO = 0.0

# 到達点が下限と区別できない、と analyze_three_indices.py が判定したセル。
#   （three_indices.csv の U_distinguishable_from_L が False のもの）
#   ここでは読み込んで自動判定するので、この定数は説明のためだけに置く。
DEGENERATE_NOTE = "到達点が当てずっぽうと区別できない"

COND = [
    # key,        番号, 表示名,                   軸,     合わせ方,   出力ファイル
    ("acc_shape",  "①", "正答率揃え（形まで）",   "acc",  "shape", "transfer_warp_c1_acc_shape.json"),
    ("info_shape", "②", "情報量揃え（形まで）",   "info", "shape", "transfer_warp_c2_info_shape.json"),
    ("acc_mid",    "③", "半分・正答率",           "acc",  "mid",   "transfer_warp_c3_acc_mid.json"),
    ("info_mid",   "④", "半分・情報量",           "info", "mid",   "transfer_warp_c4_info_mid.json"),
]


# ===========================================================================
# 1. 曲線を読む（build_warp_v5_info.load_curves / build_warp_mid.load_curves と同一）
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


def load_three_indices(path):
    """analyze_three_indices.py の結果。U の検算と、到達点が下限と区別できるかの判定に使う。"""
    if not os.path.exists(path):
        raise SystemExit(
            "three_indices.csv が無い。先に3指標の分析を回すこと:\n"
            "    python3 experiment/tools/analyze_three_indices.py\n"
            f"  探した場所: {path}")
    d = pd.read_csv(path)
    out = {}
    for r in d.itertuples():
        fam = "" if (isinstance(r.family, float) and math.isnan(r.family)) else str(r.family)
        out[(r.target, r.modality, fam, r.char)] = dict(
            L=float(r.L), U=float(r.U),
            ok=bool(r.U_distinguishable_from_L),
            T50=(None if pd.isna(r.T50) else float(r.T50)),
            T50_status=str(r.T50_status))
    return out


# ===========================================================================
# 2. 新しい中点
# ===========================================================================
def L_of(tag, modality):
    if tag == "info":
        return L_INFO
    return L_ACC_AUDIO if modality == "audio" else L_ACC_VISUAL


def q_of(curve, L, x):
    """正規化した進み具合 q(x) = (v(x) − L)/(U − L)。U は曲線の終端の値。"""
    U = curve.top
    if U - L <= 1e-9:
        return np.zeros_like(np.asarray(x, dtype=float))
    return (curve.v(x) - L) / (U - L)


def half_point(curve, L):
    """q(x) = 0.5 に達する最小の x。戻り値 (x, flag)。flag は 'low'/'high'/None。

    'low'  … 測った範囲のいちばん手前で既に半分を超えている（中点は範囲より前）
    'high' … 測った範囲の終わりでも半分に届かない（曲線の終端が U なので通常起きない）
    """
    U = curve.top
    return curve.inv(L + 0.5 * (U - L))


# ===========================================================================
# 3. 絵の量子化（真っ白／完成形 の判定に使う）
# ===========================================================================
def endpoint_levels(fam, ch, ink, bw):
    z = B4.quant_levels(fam, ch, np.array([0.0, 100.0]), ink, bw)
    return float(z[0]), float(z[1])


def picture_stats(fam, ch, s_pct, ink, bw, cva, L_v):
    """その進み具合の並びで「絵がどうなっているか」を数える。

    n_distinct … 別々の絵が何枚あるか（量子化した水準の異なり数）
    n_blank    … s=0 の絵と**同一**の点の数（真っ白のまま）
    n_full     … s=100 の絵と**同一**の点の数（もう完成形）
    read       … その絵を較正の正答率曲線に通した値（0〜1）
    q_read     … それを q に正規化した値（0=当てずっぽう、1=到達点）
    n_read_mid … q が 0.1〜0.9 に入っている点の数（＝中間の絵）
    """
    s = np.asarray(s_pct, dtype=float)
    lv = B4.quant_levels(fam, ch, s, ink, bw)
    z0, z1 = endpoint_levels(fam, ch, ink, bw)
    rd = cva.v(s)
    U = cva.top
    q = (rd - L_v) / (U - L_v) if (U - L_v) > 1e-9 else np.zeros_like(rd)
    return dict(
        n_distinct=int(len(np.unique(lv))),
        n_blank=int((lv == z0).sum()),
        n_full=int((lv == z1).sum()),
        levels="|".join(f"{v:.0f}" for v in lv),
        read="|".join(f"{v:.3f}" for v in rd),
        q_read="|".join(f"{v:.3f}" for v in q),
        q_span=float(q.max() - q.min()),
        n_read_mid=int(((q > 0.10) & (q < 0.90)).sum()))


def series_at(arr, ms, frame_ms=FRAME_MS):
    """transfer.js / transfer_comfort.js の seriesAt と同じ線形補間。

    参加者が実際に見るのは「書き出した数値列を 60Hz の枠のあいだで直線につないだもの」
    なので、判定もそれで行う（式の値そのままではない）。
    """
    arr = np.asarray(arr, dtype=float)
    n = len(arr)
    x = np.clip(np.asarray(ms, dtype=float) / frame_ms, 0, n - 1)
    lo = np.floor(x).astype(int)
    hi = np.minimum(lo + 1, n - 1)
    f = x - lo
    return arr[lo] * (1 - f) + arr[hi] * f


# ===========================================================================
# 4. 1条件ぶんの表を作る
# ===========================================================================
def build_cond(tag, how, curves, three, ts, gates_of, ink, bw, CV_acc):
    CA, CV = curves[tag]
    CA_a, _ = curves["acc"]
    L_a = L_of(tag, "audio")
    L_v = L_of(tag, "visual")
    L_v_acc = L_ACC_VISUAL              # 読み取れる度合いの物差しは正答率で固定

    tables, log = {}, []
    step_mid = {}
    for fam in FAMS:
        tables[fam] = {}
        for ch in CHARS:
            ca, cv = CA[ch], CV[(ch, fam)]
            ti_a = three.get((tag, "audio", "", ch))
            ti_v = three.get((tag, "visual", fam, ch))
            audio_ok = (ti_a is None) or ti_a["ok"]
            visual_ok = (ti_v is None) or ti_v["ok"]

            t_half, fa = half_point(ca, L_a)
            s_half, fv = half_point(cv, L_v)
            q_a = q_of(ca, L_a, ts)
            # 目標を視覚の軸に載せ替える（q が同じになる視覚の値）
            targ_v = L_v + q_a * (cv.top - L_v)

            fallback = ""
            if not (audio_ok and visual_ok):
                # 中点が決まらない → 等速のまま（合わせない）
                fallback = (DEGENERATE_NOTE
                            + f"（{'聴覚' if not audio_ok else '視覚'}）ので等速のまま")
                prop = np.clip(100.0 * ts / BASE_ANIM_MS, 0.0, 100.0)
                t0 = 0.0
            elif how == "mid":
                t0 = float(t_half) - (float(s_half) / 100.0) * BASE_ANIM_MS
                prop = np.clip(100.0 * (ts - t0) / BASE_ANIM_MS, 0.0, 100.0)
            else:
                prop, _nlo, _nhi = invert(targ_v, cv)   # 単調化まで invert の中でやる
                t0 = float("nan")

            # 対照は4条件で同じ作り方にする（条件間で対照が動かないように）
            a, b = fit_affine(ts, targ_v, cv)
            b2 = np.clip(a * ts + b, 0.0, 100.0)
            b1 = np.clip(100.0 * ts / BASE_ANIM_MS, 0.0, 100.0)
            tables[fam][ch] = {
                "proposed": [round(float(x) / 100.0, 8) for x in prop],
                "baseline1": [round(float(x) / 100.0, 8) for x in b1],
                "baseline2": [round(float(x) / 100.0, 8) for x in b2]}

            g = gates_of[ch]
            pg = series_at(np.array(tables[fam][ch]["proposed"]) * 100.0, g)
            st = picture_stats(fam, ch, pg, ink, bw, CV_acc[(ch, fam)], L_v_acc)
            span_g = float(pg.max() - pg.min())
            s0 = float(np.array(tables[fam][ch]["proposed"])[0] * 100.0)
            s_end = float(np.array(tables[fam][ch]["proposed"])[-1] * 100.0)

            if fallback:
                judge = "合わせていない（中点が決まらない）"
            elif span_g < 1.0:
                judge = "不成立（動かない）"
            elif st["n_read_mid"] <= 1:
                judge = "中間の絵が1点以下"
            elif st["n_distinct"] <= 2:
                judge = "絵が2枚以下"
            else:
                judge = "成立"

            if audio_ok:
                step_mid[ch] = round(float(t_half), 3)

            log.append(dict(
                cond_axis=tag, align=how, family=fam, family_ja=LAB[fam], char=ch,
                used_in_exp_c=(ch in CHARS_C),
                unit=("bit" if tag == "info" else "正答率"),
                L_audio=round(L_a, 6), U_audio=round(ca.top, 5),
                audio_bottom=round(ca.bottom, 5),
                audio_half_value=round(L_a + 0.5 * (ca.top - L_a), 5),
                t_half_ms=round(float(t_half), 3),
                t_half_censored=("下（測った範囲より前）" if fa == "low"
                                 else ("上（測った範囲より後）" if fa == "high" else "")),
                L_visual=round(L_v, 6), U_visual=round(cv.top, 5),
                visual_bottom=round(cv.bottom, 5),
                visual_half_value=round(L_v + 0.5 * (cv.top - L_v), 5),
                s_half_pct=round(float(s_half), 4),
                s_half_censored=("下（測った範囲より前）" if fv == "low"
                                 else ("上（測った範囲より後）" if fv == "high" else "")),
                t0_ms=(None if (isinstance(t0, float) and math.isnan(t0))
                       else round(float(t0), 3)),
                fallback=fallback,
                s_at_0ms=round(s0, 4), s_at_end=round(s_end, 4),
                s_min=round(float(prop.min()), 4), s_max=round(float(prop.max()), 4),
                span_pt_full=round(float(prop.max() - prop.min()), 4),
                span_pt_gates=round(span_g, 4),
                gates_ms="|".join(f"{x:.0f}" for x in g),
                s_at_gates="|".join(f"{x:.3f}" for x in pg),
                n_distinct_at_gates=st["n_distinct"],
                n_blank=st["n_blank"], n_full=st["n_full"],
                quant_levels_at_gates=st["levels"],
                read_at_gates=st["read"], q_read_at_gates=st["q_read"],
                q_span=round(st["q_span"], 4), n_read_mid=st["n_read_mid"],
                judgement=judge, b2_a=round(a, 5), b2_b=round(b, 3)))
    return tables, log, step_mid


def write_json(path, key, num, label, tag, how, tables, step_mid):
    axis = ("相互情報量の字ごとの分け前 D_c = KL(P(R|c,x)‖P(R|x))" if tag == "info"
            else "正答率（生の割合）")
    rule = ("時刻 t →〔聴覚の曲線を q=(v−L)/(U−L) に正規化〕→ q_a(t) "
            "→〔視覚の q を逆に引く〕→ 進み具合 s。"
            if how == "shape" else
            "等速のまま開始時刻だけずらす。s(t)=clip(100*(t−t0)/base_anim_ms,0,100)、"
            "t0=t_half(聴覚)−s_half(視覚)/100*base_anim_ms。")
    doc = {"generated_by": "experiment/tools/build_warp_exp_c.py",
           "estimator": "isotonic_bagged / " + ("shape_match_q" if how == "shape"
                                                else "midpoint_shift_only"),
           "cond_key": key, "cond_no": num, "cond_label": label,
           "target": tag, "align": ("shape" if how == "shape" else "midpoint"),
           "frame_ms": round(FRAME_MS, 6),
           "duration_ms": DURATION_MS,
           "base_anim_ms": BASE_ANIM_MS,
           # 実験C（transfer_comfort.js）の「ステップ表示」が使う切り替え時刻。
           # 定義は「その軸の聴覚の曲線で、下限から到達点までの半分に達する時刻」。
           "step_mid_ms": step_mid,
           "meta": {"space": "rawp", "made": "2026-08-29",
                    "for_group": "c",
                    "chars": CHARS, "chars_used_in_exp_c": CHARS_C,
                    "families": FAMS,
                    "curve_source": os.path.relpath(SRC, ROOT),
                    "midpoint_def": "q(x)=(v(x)−L)/(U−L) が 0.5 に達する最小の x。"
                                    "L は正答率のとき 聴覚1/68・視覚1/72、"
                                    "情報量のとき 0。U は単調回帰の曲線の終端の値。",
                    "axis": axis, "rule": rule,
                    "visual_source": "calib+calib2 両バッチ / 速さ: " + ", ".join(
                        f"{f}={'300ms' if B4.SPEED_BY_FAM[f] else '2水準'}" for f in FAMS),
                    "webkit_excluded_families": sorted(B4.WEBKIT_FAMILIES),
                    "audio_source": "実験1(phase=calib)・速さの区別なし",
                    "warning": "研究者用。本番の transfer_warp.json は書き換えていない。"},
           "composite_map": {}, "composite_map_n": 0,
           "tables": tables}
    json.dump(doc, io.open(path, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"  書き出し: {os.path.basename(path)} ({os.path.getsize(path)//1024} KB)")


# ===========================================================================
def main():
    os.makedirs(OUT, exist_ok=True)
    print("[1] 曲線と3指標を読む（推定はやり直さない）")
    print(f"    曲線 : {os.path.relpath(SRC, ROOT)}")
    print(f"    3指標: {os.path.relpath(THREE, ROOT)}")
    curves = load_curves(SRC)
    three = load_three_indices(THREE)

    # 到達点 U の検算（曲線の終端の値 == analyze_three_indices.py の U か）
    dmax, where = 0.0, ""
    for tag in ("acc", "info"):
        CA, CV = curves[tag]
        for ch in CHARS:
            ti = three.get((tag, "audio", "", ch))
            if ti and abs(ti["U"] - CA[ch].top) > dmax:
                dmax, where = abs(ti["U"] - CA[ch].top), f"{tag}/聴覚/{ch}"
        for fam in FAMS:
            for ch in CHARS:
                ti = three.get((tag, "visual", fam, ch))
                if ti and abs(ti["U"] - CV[(ch, fam)].top) > dmax:
                    dmax, where = abs(ti["U"] - CV[(ch, fam)].top), f"{tag}/{LAB[fam]}/{ch}"
    print(f"    到達点 U の食い違い（この場が使う曲線の終端 vs 3指標の表の U）: "
          f"最大 {dmax:.4f}{'（' + where + '）' if where else ''}")
    print("      ※ ここは curves_info.csv（既存の推定）だけを使い、推定はやり直さない。")
    print("        3指標の表は袋詰めを別に引き直しているので、乱数のぶんだけ数値が違う。")
    print("        その差は analysis_three_indices/curve_check.csv に元から記録されている。")
    print("        使うのは curves_info.csv のほう。3指標の表は『到達点が当てずっぽうと")
    print("        区別できるか』の判定だけに使う（この判定は乱数の差では変わらない）。")

    n = int(math.ceil(DURATION_MS / FRAME_MS)) + 1
    ts = np.array([i * FRAME_MS for i in range(n)])
    gates_of = {ch: np.array(GATES_MS.get(ch, GATES_MS["_default"]), float) for ch in CHARS}
    ink, bw = B4.glyph_stats(os.path.join(ROOT, "experiment", "base"))
    if not ink:
        raise SystemExit("字画像が読めない（PIL が要る）。pip3 install pillow")
    CV_acc = curves["acc"][1]

    # ---- 中点の一覧（新定義） ---------------------------------------------
    print("\n[2] 新しい定義での中点")
    mid_rows = []
    for tag in ("acc", "info"):
        CA, CV = curves[tag]
        L_a, L_v = L_of(tag, "audio"), L_of(tag, "visual")
        for ch in CHARS:
            ti = three.get((tag, "audio", "", ch))
            x, fl = half_point(CA[ch], L_a)
            mid_rows.append(dict(
                axis=tag, modality="audio", modality_ja="聴覚", family="", family_ja="",
                char=ch, used_in_exp_c=(ch in CHARS_C),
                L=round(L_a, 6), U=round(CA[ch].top, 5),
                U_distinguishable_from_L=(ti["ok"] if ti else True),
                half_value=round(L_a + 0.5 * (CA[ch].top - L_a), 5),
                midpoint=round(float(x), 4), unit="ms",
                censored=("下" if fl == "low" else ("上" if fl == "high" else "")),
                T50_from_three_indices=(ti["T50"] if ti else None),
                T50_status=(ti["T50_status"] if ti else "")))
        for fam in FAMS:
            for ch in CHARS:
                ti = three.get((tag, "visual", fam, ch))
                x, fl = half_point(CV[(ch, fam)], L_v)
                mid_rows.append(dict(
                    axis=tag, modality="visual", modality_ja="視覚",
                    family=fam, family_ja=LAB[fam],
                    char=ch, used_in_exp_c=(ch in CHARS_C),
                    L=round(L_v, 6), U=round(CV[(ch, fam)].top, 5),
                    U_distinguishable_from_L=(ti["ok"] if ti else True),
                    half_value=round(L_v + 0.5 * (CV[(ch, fam)].top - L_v), 5),
                    midpoint=round(float(x), 4), unit="%",
                    censored=("下" if fl == "low" else ("上" if fl == "high" else "")),
                    T50_from_three_indices=(ti["T50"] if ti else None),
                    T50_status=(ti["T50_status"] if ti else "")))
    md = pd.DataFrame(mid_rows)
    md.to_csv(os.path.join(OUT, "midpoints_exp_c.csv"), index=False)

    # 中点そのものの検算（3指標の表の T50 と一致するか）
    ok = md[md.T50_from_three_indices.notna()]
    d = (ok["midpoint"] - ok["T50_from_three_indices"]).abs()
    print(f"    中点の食い違い（この場の計算 vs 3指標の表の T50）: 最大 {d.max():.3f}"
          "（単位は聴覚 ms・視覚 進み具合pt が混じった値）")
    print("      ※ 定義は同じ。上に書いたとおり、曲線の引き直しの乱数ぶんだけずれる。")

    bad = md[(md.used_in_exp_c) & ((~md.U_distinguishable_from_L) | (md.censored != ""))]
    print("    実験Cの5字（あ・か・し・ま・ら）で中点が決まらない／範囲外のもの: "
          + ("なし" if len(bad) == 0 else str(len(bad)) + "件"))
    for r in bad.itertuples():
        print(f"      {r.axis}/{r.modality_ja}{('/' + r.family_ja) if r.family_ja else ''}"
              f"/{r.char}: 区別可={r.U_distinguishable_from_L} 打ち切り={r.censored}")
    print("\n    ● 聴覚の中点（ms）")
    for tag in ("acc", "info"):
        s = md[(md.axis == tag) & (md.modality == "audio")].set_index("char")
        print(f"      {'正答率' if tag == 'acc' else '情報量'}: " + "  ".join(
            f"{ch}={s.loc[ch, 'midpoint']:.1f}"
            + ("*" if s.loc[ch, "censored"] or not s.loc[ch, "U_distinguishable_from_L"] else "")
            for ch in CHARS_C))
    print("\n    ● 視覚の中点（進み具合 %）")
    for tag in ("acc", "info"):
        print(f"      {'正答率' if tag == 'acc' else '情報量'}")
        for fam in FAMS:
            s = md[(md.axis == tag) & (md.family == fam)].set_index("char")
            print(f"        {LAB[fam]:6s}: " + "  ".join(
                f"{ch}={s.loc[ch, 'midpoint']:.2f}" for ch in CHARS_C))

    # ---- 4条件を作る -------------------------------------------------------
    print("\n[3] 4条件を作る")
    logs, series = [], {}
    for key, num, label, tag, how, fn in COND:
        tables, log, step_mid = build_cond(tag, how, curves, three, ts,
                                           gates_of, ink, bw, CV_acc)
        logs += [dict(cond=key, cond_no=num, cond_ja=label, **r) for r in log]
        series[key] = tables
        write_json(os.path.join(OUT, fn), key, num, label, tag, how, tables, step_mid)
        c = pd.Series([r["judgement"] for r in log
                       if r["char"] in CHARS_C]).value_counts()
        print(f"    {num} {label}: 5字×4方式=20セル … "
              + " / ".join(f"{k} {v}" for k, v in c.items()))
    lg = pd.DataFrame(logs)
    lg.to_csv(os.path.join(OUT, "build_log_exp_c.csv"), index=False)
    print(f"  書き出し: build_log_exp_c.csv（{len(lg)} 行）")

    # ---- 打ち切り時点ごとの進み具合（4条件×4方式×5字） ---------------------
    print("\n[4] 打ち切り時点ごとの進み具合（4条件×4方式×5字 = 80行）")
    rows = []
    for key, num, label, tag, how, fn in COND:
        for fam in FAMS:
            for ch in CHARS_C:
                g = gates_of[ch]
                arr = np.array(series[key][fam][ch]["proposed"], float) * 100.0
                pg = series_at(arr, g)
                st = picture_stats(fam, ch, pg, ink, bw, CV_acc[(ch, fam)], L_ACC_VISUAL)
                r = dict(cond=key, cond_no=num, cond_ja=label,
                         axis=tag, align=how,
                         family=fam, family_ja=LAB[fam], char=ch,
                         gates_ms="|".join(f"{x:.0f}" for x in g))
                for i, (t, v) in enumerate(zip(g, pg), 1):
                    r[f"s_at_gate{i}_pct"] = round(float(v), 3)
                lv_all = B4.quant_levels(fam, ch, arr, ink, bw)
                z0, z1 = endpoint_levels(fam, ch, ink, bw)
                r.update(
                    n_distinct_full_anim=int(len(np.unique(lv_all))),
                    first_frame_is_blank=bool(float(lv_all[0]) == z0),
                    last_frame_is_blank=bool(float(lv_all[-1]) == z0),
                    first_frame_is_full=bool(float(lv_all[0]) == z1),
                    last_frame_is_full=bool(float(lv_all[-1]) == z1),
                    s_at_0ms=round(float(arr[0]), 3),
                    s_at_100ms=round(float(series_at(arr, [100.0])[0]), 3),
                    s_at_200ms=round(float(series_at(arr, [200.0])[0]), 3),
                    s_at_300ms=round(float(arr[-1]), 3),
                    s_min_gates=round(float(pg.min()), 3),
                    s_max_gates=round(float(pg.max()), 3),
                    span_pt_gates=round(float(pg.max() - pg.min()), 3),
                    n_distinct_at_gates=st["n_distinct"],
                    n_blank=st["n_blank"], n_full=st["n_full"],
                    q_read_at_gates=st["q_read"], n_read_mid=st["n_read_mid"],
                    quant_levels_at_gates=st["levels"])
                rows.append(r)
    gp = pd.DataFrame(rows)
    gp.to_csv(os.path.join(OUT, "gate_progress_exp_c.csv"), index=False)
    print(f"  書き出し: gate_progress_exp_c.csv（{len(gp)} 行）")

    pd.set_option("display.width", 250)
    piv = gp.groupby(["cond_no", "cond_ja", "family_ja"]).agg(
        別々の絵=("n_distinct_at_gates", "mean"),
        中間の絵=("n_read_mid", "mean"),
        真っ白=("n_blank", "sum"), 完成形=("n_full", "sum"),
        開始時の進み=("s_at_0ms", "mean"),
        終了時の進み=("s_at_300ms", "mean"),
        打ち切り間の幅=("span_pt_gates", "mean")).round(2)
    print("\n  --- 4条件×4方式（5字の平均・合計）---")
    print("      別々の絵/中間の絵 は 1字あたり7点中の平均、真っ白・完成形 は 5字×7点=35点中の合計")
    print(piv.to_string())

    # ---- 退化していないか --------------------------------------------------
    print("\n[5] 退化の点検（実験Cの5字ぶんだけ・アニメ全体 0〜300ms の全フレームで見る）")
    print("    実験Cは打ち切らずに最後まで流すので、点検も『アニメ1本ぜんぶ』で行う。")
    print("      真っ白のまま終わる … 最後のフレームの絵が s=0 の絵と同じ")
    print("      最初から完成形     … 最初のフレームの絵が s=100 の絵と同じ")
    print("      絵が2枚以下       … 1本のあいだに別々の絵が2枚しか出ない")
    problems = []
    for key, num, label, tag, how, fn in COND:
        for fam in FAMS:
            for ch in CHARS_C:
                arr = np.array(series[key][fam][ch]["proposed"], float) * 100.0
                lv = B4.quant_levels(fam, ch, arr, ink, bw)
                z0, z1 = endpoint_levels(fam, ch, ink, bw)
                if float(lv[-1]) == z0:
                    problems.append((num, LAB[fam], ch, "真っ白のまま終わる"))
                if float(lv[0]) == z1:
                    problems.append((num, LAB[fam], ch, "最初から完成形"))
                if len(np.unique(lv)) <= 2:
                    problems.append((num, LAB[fam], ch,
                                     f"絵が{len(np.unique(lv))}枚しかない"))
    if problems:
        for p in problems:
            print(f"    ⚠ {p[0]} {p[1]}×{p[2]}: {p[3]}")
    else:
        print("    → 20セル×4条件の全部で、そのどれにも当たらない")
    # 参考: 1本のあいだに出る別々の絵の枚数（多いほど段階的に見える）
    nd = []
    for key, num, label, tag, how, fn in COND:
        for fam in FAMS:
            for ch in CHARS_C:
                arr = np.array(series[key][fam][ch]["proposed"], float) * 100.0
                lv = B4.quant_levels(fam, ch, arr, ink, bw)
                nd.append(dict(cond_no=num, cond_ja=label, family_ja=LAB[fam], char=ch,
                               n=int(len(np.unique(lv)))))
    ndf = pd.DataFrame(nd)
    print("\n    アニメ1本(%d フレーム)のあいだに出る別々の絵の枚数" % n + "（5字の最小〜最大）")
    print(ndf.groupby(["cond_no", "cond_ja", "family_ja"])["n"]
          .agg(["min", "max"]).to_string())
    # 参考: 最初のフレームで既にどれくらい出ているか
    st0 = gp.groupby(["cond_no", "cond_ja"])["s_at_0ms"].agg(["min", "max", "mean"]).round(2)
    print("\n    最初のフレームでの進み具合（%）… 大きいほど『途中から始まる』")
    print(st0.to_string())

    # ---- 条件どうしで絵が違うか --------------------------------------------
    print("\n[6] 4条件で提示される絵が実際に違うか（5字×4方式・0〜300ms 全体）")
    drows = []
    for (ka, *_), (kb, *_) in itertools.combinations(COND, 2):
        dmax_all, ndiff, same = 0.0, 0, []
        for fam in FAMS:
            for ch in CHARS_C:
                a = np.array(series[ka][fam][ch]["proposed"], float) * 100.0
                b = np.array(series[kb][fam][ch]["proposed"], float) * 100.0
                dd = float(np.abs(a - b).max())
                la = B4.quant_levels(fam, ch, a, ink, bw)
                lb = B4.quant_levels(fam, ch, b, ink, bw)
                nfr = int((la != lb).sum())
                drows.append(dict(cond_a=ka, cond_b=kb, family=fam, family_ja=LAB[fam],
                                  char=ch, max_diff_pt=round(dd, 3),
                                  n_frames_different_picture=nfr,
                                  n_frames=len(la)))
                dmax_all = max(dmax_all, dd)
                ndiff += (dd >= 1.0)
                if dd < 1.0:
                    same.append(f"{LAB[fam]}×{ch}")
        print(f"    {ka} vs {kb}: 進み具合の差 最大 {dmax_all:6.2f}pt / "
              f"20セル中 {ndiff} セルで 1pt 以上違う"
              + ("" if not same else "  ⚠ ほぼ同じ: " + "、".join(same)))
    pd.DataFrame(drows).to_csv(os.path.join(OUT, "cond_difference_exp_c.csv"), index=False)
    print(f"  書き出し: cond_difference_exp_c.csv（{len(drows)} 行）")

    print("\n完了: " + os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
