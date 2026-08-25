#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
較正フェーズ(transfer_trials.csv) の深掘り解析
==============================================================
experiment/tools/analyze_calib_full.py (以下 af) が出す本命8字の集計に対し、
3つの追加分析を行う。

  依頼1: まぎれ字(decoy)を本格的に解析する(字ごとの曲線・当てはめ・束ね比較・
         本命との比較・視覚方式の安定性)
  依頼2: 参加者を様々な基準で選別し、本命8字のλ・μがどう動くかを表にする
  依頼3: 天井に届かない5字(つ・ぱ・ら・し・が、いずれも聴覚)を、曲線として
         使える形にできないか複数の方法で試す

⚠ 既存ツール af は一切変更しない。この場から `import analyze_calib_full as af`
   して関数を再利用するだけにとどめ、新しい処理はすべてこのファイルに書く。

出力(既定 project/data_calib_20260825/analysis_deep/): 本ファイル末尾の
main() のコメントに一覧を書いた。

使い方
------
  python3 experiment/tools/analyze_calib_deep.py \
      --in project/data_calib_20260825/transfer_trials.csv \
      --out project/data_calib_20260825/analysis_deep \
      --report project/data_calib_20260825/deep_report.html
"""
import argparse
import base64
import csv
import io
import math
import os
import sys
from collections import defaultdict, Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_calib_full as af  # 既存ツール(変更しない)を再利用する

try:
    from scipy.optimize import minimize, isotonic_regression
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

# 図中の日本語(タイトル・凡例・かな1文字のラベル)が豆腐にならないよう、
# macOSに標準で入っている日本語フォントを明示する(DejaVu Sansには和文グリフが無いため)。
plt.rcParams["font.family"] = "Hiragino Sans"
plt.rcParams["axes.unicode_minus"] = False


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # experiment/
BASE_PNG_DIR = os.path.join(BASE_DIR, "base")

# 依頼3の対象5字。天井(λ)が低い(=較正フェーズの当てはめで天井が0.7未満)聴覚の字。
# 数値は project/data_calib_20260825/analysis/fit_logistic.csv (audio) から:
#   つ0.673 ぱ0.426 ら0.415 し0.274 が0.008
# ⚠ コーディネータからの指摘どおり、この5字は「同じ理由で天井が低い」わけではない。
#   つ だけは天井ではなく床(短い側)が取れていない字なので、診断・処置を分けて扱う。
LOWCEIL_CHARS = ["つ", "ぱ", "ら", "し", "が"]
# 参照用(問題なし)の3字。表の対比に使う。
REF_CHARS = ["あ", "か", "ま"]


# ---------------------------------------------------------------------------
# 五十音の行(gyou)・清濁半濁の区分を、まぎれ字(50音全体)にまで拡張する
# ---------------------------------------------------------------------------
def build_gyou_map():
    """
    かな1文字 -> 行(あ/か/さ/た/な/は/ま/や/ら/わ) の対応表。
    af.CHAR_GROUP/af.CHAR_TYPE は清濁半濁の対だけ(か行〜ほ行)しか持たないため、
    行の情報はここで別途作る。促音(っ)は た行、拗音の小書き(ゃゅょ)は や行、
    小書き母音(ぁぃぅぇぉ)と ゔ は あ行、小書き わ(ゎ)・を・ゐ・ゑ・ん は わ行 に
    便宜上まとめた(音韻的な行ではなく「表記上どの行のバリエーションか」という
    実務上の分類。この分類の妥当性そのものは論じない、あくまで束ね方の一つとして使う)。
    """
    g = {}

    def add(name, chars):
        for c in chars:
            g[c] = name

    add("あ", "あいうえおぁぃぅぇぉゔ")
    add("か", "かきくけこがぎぐげご")
    add("さ", "さしすせそざじずぜぞ")
    add("た", "たちつてとだぢづでどっ")
    add("な", "なにぬねの")
    add("は", "はひふへほばびぶべぼぱぴぷぺぽ")
    add("ま", "まみむめも")
    add("や", "やゆよゃゅょ")
    add("ら", "らりるれろ")
    add("わ", "わゐゑをんゎ")
    return g


GYOU_MAP = build_gyou_map()


def char_type_ext(ch):
    """af.CHAR_TYPE を拡張: か行〜ほ行以外(あ/な/ま/や/ら/わ行、小書き類)は
    濁音・半濁音の対を持たないので "seion"(清音扱い)とする。"""
    return af.CHAR_TYPE.get(ch, "seion")


# ---------------------------------------------------------------------------
# 画数の代理指標: experiment/base/<char>.png の墨(黒)画素数
# ---------------------------------------------------------------------------
_INK_CACHE = {}


def ink_pixel_count(ch, threshold=0.5):
    """
    experiment/base/<char>.png を読み、閾値より暗い画素の数を返す。

    画像はグレースケール1chで 0=黒(墨)・1=白(地) の256x256(実測で確認済み)。
    PIL は使わず matplotlib.image.imread (許可された依存だけ)で読む。
    ⚠ あくまで「画数」の代理。太さ・面積の違いで字によっては画数と順位が
    ずれうるが、依頼文に「墨の画素数で代用してよい」とあるのでそのまま使う。
    """
    if ch in _INK_CACHE:
        return _INK_CACHE[ch]
    path = os.path.join(BASE_PNG_DIR, f"{ch}.png")
    if not os.path.exists(path):
        _INK_CACHE[ch] = None
        return None
    img = mpimg.imread(path)
    if img.ndim == 3:
        img = img[:, :, 0] if img.shape[2] >= 1 else img
    n_ink = int(np.sum(img < threshold))
    _INK_CACHE[ch] = n_ink
    return n_ink


def ink_quartile_labels(chars, n_bins=4):
    """文字集合 chars の墨画素数を n_bins 分位に切り、各字にラベルを振る。
    分位境界は対象文字集合自身の分布から決める(絶対値でなく相対順位で束ねる)。"""
    vals = {ch: ink_pixel_count(ch) for ch in chars}
    valid = {ch: v for ch, v in vals.items() if v is not None}
    if not valid:
        return {ch: "" for ch in chars}
    arr = np.array(sorted(valid.values()))
    edges = np.quantile(arr, np.linspace(0, 1, n_bins + 1))
    labels = {}
    for ch, v in vals.items():
        if v is None:
            labels[ch] = ""
            continue
        # edges[0]=min, edges[n_bins]=max。np.searchsortedで区間を決める。
        idx = int(np.clip(np.searchsorted(edges, v, side="right") - 1, 0, n_bins - 1))
        labels[ch] = f"Q{idx + 1}(画素少)" if idx == 0 else (
            f"Q{idx + 1}(画素多)" if idx == n_bins - 1 else f"Q{idx + 1}")
    return labels


# ---------------------------------------------------------------------------
# まぎれ字(decoy)行の抽出
# ---------------------------------------------------------------------------
def decoy_target_rows(rows):
    """本命問題と対になる「まぎれ字の本命同等問題」。
    is_decoy が真 かつ check_kind が空(確認問題ではない、本編のはしごの中)。
    本命8字が混入しないことも念のため確認する(design上入らないはずだが実データで確認)。"""
    out = [r for r in rows if r["is_decoy_b"] and not r["check_kind"]]
    contami = [r for r in out if r["target_char"] in af.TARGET_CHARS]
    if contami:
        print(f"  ⚠ decoy行に本命8字が{len(contami)}件混入している(想定外)")
    return out


# ---------------------------------------------------------------------------
# 1. まぎれ字: 字ごとの曲線・当てはめ
# ---------------------------------------------------------------------------
def write_curves_decoy_audio(path, rows):
    """af.write_curves_audio と同じ形式(字 × 打ち切りms)。埋め込みfullも同様に別枠で残す。"""
    tab = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["is_embedded_full"]:
            level = "full"
        elif r["gate_ms"] is not None:
            level = str(int(r["gate_ms"]))
        else:
            continue
        k = (r["target_char"], level)
        tab[k][1] += 1
        tab[k][0] += 1 if r["correct_b"] else 0

    def sort_key(item):
        (ch, lv), _ = item
        return (ch, 1 if lv == "full" else 0, float(lv) if lv != "full" else 0.0)

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "gate_ms", "n_correct", "n_trials", "accuracy"])
        for (ch, lv), (ok, n) in sorted(tab.items(), key=sort_key):
            w.writerow([ch, lv, ok, n, round(ok / n, 4) if n else ""])


def write_curves_decoy_visual(path, rows):
    """af.write_curves_visual と同じ形式(字 × 方式 × 水準)。軸は実測(actual_s)を主軸にする
    (理由は af.write_fit_logistic のコメントに同じ: 60Hz端末での量子化のため)。"""
    tab_nom = defaultdict(lambda: [0, 0])
    tab_act = defaultdict(lambda: [0, 0])
    for r in rows:
        ch, fam = r["target_char"], r["family"]
        if r["progress_pct"] is not None:
            k = (ch, fam, r["progress_pct"])
            tab_nom[k][1] += 1
            tab_nom[k][0] += 1 if r["correct_b"] else 0
        if r["actual_s"] is not None:
            lv = round(r["actual_s"] * 100, 2)
            k = (ch, fam, lv)
            tab_act[k][1] += 1
            tab_act[k][0] += 1 if r["correct_b"] else 0

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "family", "axis", "level", "n_correct", "n_trials", "accuracy"])
        for axis, tab in (("progress_pct", tab_nom), ("actual_s", tab_act)):
            for (ch, fam, lv), (ok, n) in sorted(tab.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
                w.writerow([ch, fam, axis, lv, ok, n, round(ok / n, 4) if n else ""])


def fit_decoy_audio(rows, gamma, n_starts, lambda_warn, lambda_diff_warn):
    """まぎれ字(聴覚): 字ごとに af.fit_sigmoid を当てはめる。メタ情報(行・清濁半濁・画数)も付す。"""
    chars = sorted({r["target_char"] for r in rows})
    ink_labels = ink_quartile_labels(chars)
    full_obs = af.observed_full_audio(rows)
    out = []
    for ch in chars:
        sub = [r for r in rows if r["target_char"] == ch and not r["is_embedded_full"]]
        xs, ks, ns = af.aggregate_levels(sub, "gate_ms")
        fit = af.fit_sigmoid(xs, ks, ns, gamma, n_starts=n_starts)
        ok_f, n_f = full_obs.get(ch, (0, 0))
        lam_obs = ok_f / n_f if n_f else float("nan")
        note = af._augment_note_with_full(fit["note"], fit["lam"], lam_obs, n_f, lambda_warn, lambda_diff_warn)
        out.append(dict(char=ch, gyou=GYOU_MAP.get(ch, ""), type=char_type_ext(ch),
                         ink_pixels=ink_pixel_count(ch), ink_quartile=ink_labels.get(ch, ""),
                         gamma=gamma, lam=fit["lam"], mu=fit["mu"], sigma=fit["sigma"],
                         converged=fit["converged"], n_trials=fit["n_trials"], note=note,
                         lambda_observed_full=lam_obs, n_full=n_f))
    return out


def fit_decoy_visual(rows, gamma, n_starts, lambda_warn, lambda_diff_warn, visual_axis):
    """まぎれ字(視覚): 字×方式ごとに当てはめる。"""
    level_key = "actual_s_pct" if visual_axis == "actual" else "progress_pct"
    for r in rows:
        r["actual_s_pct"] = round(r["actual_s"] * 100, 4) if r["actual_s"] is not None else None
    chars = sorted({r["target_char"] for r in rows})
    families = sorted({r["family"] for r in rows if r["family"]})
    ink_labels = ink_quartile_labels(chars)
    full_obs = af.observed_full_visual(rows)
    out = []
    for ch in chars:
        for fam in families:
            sub = [r for r in rows if r["target_char"] == ch and r["family"] == fam]
            xs, ks, ns = af.aggregate_levels(sub, level_key)
            fit = af.fit_sigmoid(xs, ks, ns, gamma, n_starts=n_starts)
            ok_f, n_f = full_obs.get((ch, fam), (0, 0))
            lam_obs = ok_f / n_f if n_f else float("nan")
            note = af._augment_note_with_full(fit["note"], fit["lam"], lam_obs, n_f, lambda_warn, lambda_diff_warn)
            out.append(dict(char=ch, family=fam, gyou=GYOU_MAP.get(ch, ""), type=char_type_ext(ch),
                             ink_pixels=ink_pixel_count(ch), ink_quartile=ink_labels.get(ch, ""),
                             gamma=gamma, lam=fit["lam"], mu=fit["mu"], sigma=fit["sigma"],
                             converged=fit["converged"], n_trials=fit["n_trials"], note=note,
                             lambda_observed_full=lam_obs, n_full=n_f))
    return out


def write_fit_decoy(path, rows_out, has_family):
    cols = ["char"] + (["family"] if has_family else []) + \
        ["gyou", "type", "ink_pixels", "ink_quartile", "gamma", "lambda", "mu", "sigma",
         "converged", "n_trials", "note", "lambda_observed_full", "n_full"]
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows_out:
            row = [r["char"]] + ([r["family"]] if has_family else []) + \
                [r["gyou"], r["type"], r["ink_pixels"], r["ink_quartile"],
                 round(r["gamma"], 5) if r["gamma"] is not None else "",
                 af._fmt(r["lam"]), af._fmt(r["mu"]), af._fmt(r["sigma"]),
                 r["converged"], r["n_trials"], r["note"],
                 af._fmt(r["lambda_observed_full"]), r["n_full"]]
            w.writerow(row)


# ---------------------------------------------------------------------------
# 2. まぎれ字: 字の性質で束ねた比較(清濁半濁・行・画数四分位)
# ---------------------------------------------------------------------------
def pool_and_fit(rows, dim_name, dim_of_char, level_key, gamma, n_starts, family_split=False):
    """
    dim_of_char(char)->束ねるグループ名 で行をグループ化し、グループ内の生の試行を
    プールしてから1本のシグモイドを当てはめる(個々の字のばらつきを均した「束ねた曲線」)。

    ⚠ 束ね方の根拠: まぎれ字は本命8字と同じ水準ラダー(同じ gate_ms / progress_pct の
    刻み)で出題される設計なので、同じ水準値は across-char で同じ「打ち切り量」を意味する。
    そのため異なる字の試行を同じ水準の下でそのまま足し合わせても、水準の意味がずれる
    心配はない(視覚は方式が違うと水準の意味が違うので family_split=True で方式ごとに
    分けて束ねる)。
    戻り値: [(group, family_or_None, xs, ks, ns, fit_dict, n_chars), ...]
    """
    groups = defaultdict(list)
    for r in rows:
        g = dim_of_char(r["target_char"])
        if not g:
            continue
        key = (g, r["family"]) if family_split else (g, None)
        groups[key].append(r)

    out = []
    for (g, fam), sub in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        xs, ks, ns = af.aggregate_levels(sub, level_key)
        fit = af.fit_sigmoid(xs, ks, ns, gamma, n_starts=n_starts)
        n_chars = len({r["target_char"] for r in sub})
        out.append((g, fam, xs, ks, ns, fit, n_chars))
    return out


def write_bundle(curve_path, fit_path, bundles, dim_name, modality):
    with io.open(curve_path, "a", encoding="utf-8", newline="") as fc, \
         io.open(fit_path, "a", encoding="utf-8", newline="") as ff:
        wc = csv.writer(fc)
        wf = csv.writer(ff)
        for g, fam, xs, ks, ns, fit, n_chars in bundles:
            for x, k, n in zip(xs, ks, ns):
                wc.writerow([dim_name, g, fam or "", x, k, n, round(k / n, 4) if n else ""])
            wf.writerow([dim_name, g, fam or "", modality, round(fit["lam"], 5) if not math.isnan(fit["lam"]) else "",
                         af._fmt(fit["mu"]), af._fmt(fit["sigma"]), fit["converged"], fit["note"],
                         fit["n_trials"], n_chars])


# ---------------------------------------------------------------------------
# 3. 本命8字 とまぎれ字の比較(最近傍水準マッチング)
# ---------------------------------------------------------------------------
def nearest_match(level, level_to_acc):
    """level_to_acc: {level: (ok,n)} から level に一番近い水準を探し、その正答率を返す。"""
    if not level_to_acc:
        return None, None, None
    lv = min(level_to_acc.keys(), key=lambda x: abs(x - level))
    ok, n = level_to_acc[lv]
    return lv, ok / n if n else None, n


def write_compare_main_vs_decoy(path, curves_main_audio_rows, fit_decoy_audio_rows,
                                 decoy_audio_rows,
                                 curves_main_visual, decoy_visual_rows, visual_axis):
    """
    本命8字の各観測水準に対し、
      (a) まぎれ字「全字プール」の同水準での正答率
      (b) まぎれ字「同じ清濁半濁タイプの字だけプール」の同水準での正答率
    を最近傍水準でマッチングして並べる。

    ⚠ 比べ方の根拠: 本命8字は1字あたりの試行が少なく水準もまばらなため、回帰的な
    比較(同じ水準で厳密に揃える)はできない。一方まぎれ字は全水準に薄く広く散っており、
    「本命のある観測水準に一番近いまぎれ字の水準」を都度探せば、水準のずれが小さい
    (聴覚は5ms刻み、視覚も細かい刻みのラダーを共有)範囲でおおむね対応する値が引ける。
    ズレが大きい場合は note に残す(level_diff列で確認できる)。
    """
    rows_out = []

    # --- 聴覚 ---
    # まぎれ字を字ごとに level->(ok,n) にした上で、全字プール・タイプ別プールを作る
    decoy_all = defaultdict(lambda: [0, 0])
    decoy_by_type = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in decoy_audio_rows:
        if r["is_embedded_full"] or r["gate_ms"] is None:
            continue
        lv = r["gate_ms"]
        decoy_all[lv][1] += 1
        decoy_all[lv][0] += 1 if r["correct_b"] else 0
        t = char_type_ext(r["target_char"])
        decoy_by_type[t][lv][1] += 1
        decoy_by_type[t][lv][0] += 1 if r["correct_b"] else 0
    decoy_all = {k: tuple(v) for k, v in decoy_all.items()}

    main_levels = defaultdict(dict)  # char -> {gate_ms: (ok,n)}
    for row in curves_main_audio_rows:
        ch, lv, ok, n, acc = row
        if lv == "full":
            continue
        main_levels[ch][float(lv)] = (int(ok), int(n))

    for ch, levels in main_levels.items():
        t = char_type_ext(ch)
        typed = {k: tuple(v) for k, v in decoy_by_type.get(t, {}).items()}
        for lv, (ok, n) in levels.items():
            main_acc = ok / n if n else float("nan")
            for grp_name, pool in (("all_decoy", decoy_all), ("same_type_decoy", typed)):
                dlv, dacc, dn = nearest_match(lv, pool)
                rows_out.append(dict(modality="audio", char=ch, family="", type=t, level=lv,
                                      main_accuracy=main_acc, main_n=n, compare_group=grp_name,
                                      decoy_level=dlv, decoy_accuracy=dacc, decoy_n=dn,
                                      level_diff=(abs(dlv - lv) if dlv is not None else ""),
                                      diff=(main_acc - dacc) if (dacc is not None) else ""))

    # --- 視覚: 方式ごとに水準空間が違うので方式内でマッチングする ---
    level_key = "actual_s" if visual_axis == "actual" else "progress_pct"
    decoy_all_v = defaultdict(lambda: defaultdict(lambda: [0, 0]))     # family -> level -> [ok,n]
    decoy_type_v = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))  # type->family->level
    for r in decoy_visual_rows:
        x = r.get(level_key)
        if x is None:
            continue
        lv = round(x * 100, 2) if level_key == "actual_s" else x
        fam = r["family"]
        decoy_all_v[fam][lv][1] += 1
        decoy_all_v[fam][lv][0] += 1 if r["correct_b"] else 0
        t = char_type_ext(r["target_char"])
        decoy_type_v[t][fam][lv][1] += 1
        decoy_type_v[t][fam][lv][0] += 1 if r["correct_b"] else 0

    main_levels_v = defaultdict(dict)  # (char,family) -> {level: (ok,n)}
    axis_name = "actual_s" if visual_axis == "actual" else "progress_pct"
    for row in curves_main_visual:
        ch, fam, axis, lv, ok, n, acc = row
        if axis != axis_name:
            continue
        main_levels_v[(ch, fam)][float(lv)] = (int(ok), int(n))

    for (ch, fam), levels in main_levels_v.items():
        t = char_type_ext(ch)
        pool_all = {k: tuple(v) for k, v in decoy_all_v.get(fam, {}).items()}
        pool_typed = {k: tuple(v) for k, v in decoy_type_v.get(t, {}).get(fam, {}).items()}
        for lv, (ok, n) in levels.items():
            main_acc = ok / n if n else float("nan")
            for grp_name, pool in (("all_decoy", pool_all), ("same_type_decoy", pool_typed)):
                dlv, dacc, dn = nearest_match(lv, pool)
                rows_out.append(dict(modality="visual", char=ch, family=fam, type=t, level=lv,
                                      main_accuracy=main_acc, main_n=n, compare_group=grp_name,
                                      decoy_level=dlv, decoy_accuracy=dacc, decoy_n=dn,
                                      level_diff=(abs(dlv - lv) if dlv is not None else ""),
                                      diff=(main_acc - dacc) if (dacc is not None) else ""))

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["modality", "char", "family", "type", "level", "main_accuracy", "main_n",
                     "compare_group", "decoy_level", "decoy_accuracy", "decoy_n", "level_diff", "diff"])
        for r in rows_out:
            w.writerow([r["modality"], r["char"], r["family"], r["type"], r["level"],
                        af._fmt(r["main_accuracy"]), r["main_n"], r["compare_group"],
                        r["decoy_level"], af._fmt(r["decoy_accuracy"]), r["decoy_n"],
                        af._fmt(r["level_diff"]) if r["level_diff"] != "" else "",
                        af._fmt(r["diff"]) if r["diff"] != "" else ""])
    return rows_out


# ---------------------------------------------------------------------------
# 4. 視覚: 方式(family)ごとの当てはめ安定性(まぎれ字63字を使う)
# ---------------------------------------------------------------------------
def write_family_stability(path, fit_decoy_visual_rows):
    """
    まぎれ字は63字あるので、方式(fade/reveal/blur/wipe)ごとに「当てはめがどれだけ
    きれいに収束するか」を字数を揃えて比較できる(本命8字だけでは字数が少なく方式間の
    差が偶然かどうか言いにくいが、63字あればより確からしく言える)。
    """
    by_fam = defaultdict(list)
    for r in fit_decoy_visual_rows:
        by_fam[r["family"]].append(r)

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family", "n_fits", "converged_rate", "note_nonempty_rate",
                     "mu_median", "mu_iqr", "sigma_median", "sigma_iqr",
                     "lambda_median", "lambda_ge_0.8_rate"])
        for fam in sorted(by_fam.keys()):
            rs = by_fam[fam]
            n = len(rs)
            conv = np.mean([1.0 if r["converged"] else 0.0 for r in rs])
            note_rate = np.mean([1.0 if r["note"] else 0.0 for r in rs])
            mus = np.array([r["mu"] for r in rs if not math.isnan(r["mu"])])
            sigmas = np.array([abs(r["sigma"]) for r in rs if not math.isnan(r["sigma"])])
            lams = np.array([r["lam"] for r in rs if not math.isnan(r["lam"])])
            def med_iqr(a):
                if len(a) == 0:
                    return float("nan"), float("nan")
                q1, med, q3 = np.percentile(a, [25, 50, 75])
                return med, q3 - q1
            mu_med, mu_iqr = med_iqr(mus)
            sig_med, sig_iqr = med_iqr(sigmas)
            lam_med = float(np.median(lams)) if len(lams) else float("nan")
            lam_ge08 = float(np.mean(lams >= 0.8)) if len(lams) else float("nan")
            w.writerow([fam, n, round(conv, 3), round(note_rate, 3),
                        af._fmt(mu_med), af._fmt(mu_iqr), af._fmt(sig_med), af._fmt(sig_iqr),
                        af._fmt(lam_med), af._fmt(lam_ge08)])


# ---------------------------------------------------------------------------
# 5. 参加者の選別(依頼2)
# ---------------------------------------------------------------------------
def extend_participant_stats(pstats, base_rows, main_rows, decoy_rows, args):
    """
    af.build_participant_stats の結果に、以下を追加する:
      - full_acc_healthy: 確認問題A(check_kind=='full')のうち健全字(あ・か・ま)だけでの正答率
        (⚠ 聴覚は「が」等の刺激不良で確認問題A全体の正答率が下がるため、刺激の良し悪しと
        参加者の不真面目さを混同しないよう、健全字だけに絞った版を別途作る)
      - floor_acc: 確認問題C(check_kind=='floor')全体の正答率。当て推量(γ)よりはっきり
        高いと「まぐれ/不正」の疑いが強まる
      - decoy_acc: まぎれ字(本編)全体の正答率。その人の全般的な出来の指標
    """
    by_pid_base = defaultdict(list)
    for r in base_rows:
        by_pid_base[r["participant_id"]].append(r)
    by_pid_decoy = defaultdict(list)
    for r in decoy_rows:
        by_pid_decoy[r["participant_id"]].append(r)

    for pid, st in pstats.items():
        rs = by_pid_base.get(pid, [])
        full_healthy = [r for r in rs if r["check_kind"] == "full" and r["target_char"] in REF_CHARS]
        st["full_acc_healthy"] = (sum(1 for r in full_healthy if r["correct_b"]) / len(full_healthy)
                                   if full_healthy else None)
        floor_rows = [r for r in rs if r["check_kind"] == "floor"]
        st["floor_acc"] = (sum(1 for r in floor_rows if r["correct_b"]) / len(floor_rows)
                            if floor_rows else None)
        st["n_floor"] = len(floor_rows)
        drs = by_pid_decoy.get(pid, [])
        st["decoy_acc"] = (sum(1 for r in drs if r["correct_b"]) / len(drs)) if drs else None
        st["n_decoy"] = len(drs)
    return pstats


def cut_predicates(pstats, args):
    """
    依頼2の切り口を述語(participant_id -> bool、真=残す)の辞書として定義する。
    しきい値は指示された既定値をそのまま使う(引数で変更可能)。
    """
    def get(pid, key):
        st = pstats.get(pid)
        return None if st is None else st.get(key)

    preds = {}
    preds["baseline"] = lambda pid: True

    # 1. 確認問題A(全部提示)の正答率で切る(全字/健全字限定の両方)
    for thr in args.full_acc_thresholds:
        preds[f"full_acc>={thr:.0%}"] = (
            lambda pid, thr=thr: (get(pid, "full_acc") is None or get(pid, "full_acc") >= thr))
        preds[f"full_acc_healthy>={thr:.0%}"] = (
            lambda pid, thr=thr: (get(pid, "full_acc_healthy") is None or get(pid, "full_acc_healthy") >= thr))

    # 2. 同じ字を押し続けた割合で切る
    for thr in args.same_response_thresholds:
        preds[f"same_response<{thr:.0%}"] = (
            lambda pid, thr=thr: (get(pid, "dominant_response_share") is None
                                   or get(pid, "dominant_response_share") < thr))

    # 3. 反応時間(速すぎ・遅すぎ)。IQRベースは試行単位の除外(apply_trial_level_cutで別途)。
    #    ここでは参加者単位で「反応時間の中央値」が極端な人を切る版も足す。
    preds["rt_iqr(試行単位)"] = None  # 特別扱い(下のrun_cutで試行フィルタとして処理)
    preds["rt_min300(試行単位)"] = None

    # 4. 確認問題C(最小提示)で正解しすぎ。当て推量なら正答率はγ近辺のはずなので、
    #    γのargs.floor_overacc_mult倍を超えたら「まぐれ/不正」候補として除外する。
    for mult in args.floor_overacc_mults:
        def pred(pid, mult=mult):
            fa = get(pid, "floor_acc")
            gam = get(pid, "gamma")
            if fa is None or gam is None:
                return True
            return fa < gam * mult
        preds[f"floor_acc<gamma×{mult:g}"] = pred

    # 5. まぎれ字の正答率で切る(下位を除外)
    for thr in args.decoy_acc_thresholds:
        preds[f"decoy_acc>={thr:.0%}"] = (
            lambda pid, thr=thr: (get(pid, "decoy_acc") is None or get(pid, "decoy_acc") >= thr))

    # 6. 組み合わせ(厳しい版): 健全字確認問題が高く・押し続けておらず・
    #    まぎれ字の出来も一定以上・floorで正解しすぎていない人だけを残す。
    def strict(pid):
        fa = get(pid, "full_acc_healthy")
        dr = get(pid, "dominant_response_share")
        da = get(pid, "decoy_acc")
        fl = get(pid, "floor_acc")
        gam = get(pid, "gamma")
        if fa is not None and fa < args.strict_full_acc_healthy:
            return False
        if dr is not None and dr >= args.strict_same_response:
            return False
        if da is not None and da < args.strict_decoy_acc:
            return False
        if fl is not None and gam is not None and fl >= gam * args.strict_floor_overacc_mult:
            return False
        return True
    preds["strict(組み合わせ)"] = strict

    return preds


def write_sensitivity_participant(path, rows_audio_main, rows_visual_main, pstats, gamma_audio, gamma_visual,
                                   visual_axis, n_starts, args):
    """cutごとに、本命8字(聴覚・視覚)のλ・μと残った参加者数・試行数を出す。"""
    for r in rows_visual_main:
        r["actual_s_pct"] = round(r["actual_s"] * 100, 4) if r["actual_s"] is not None else None
    level_key_v = "actual_s_pct" if visual_axis == "actual" else "progress_pct"
    families = sorted({r["family"] for r in rows_visual_main if r["family"]})

    # gamma を pstats に仕込んでおく(floor_overacc_mult判定用)。聴覚・視覚で別値。
    for pid, st in pstats.items():
        st["gamma"] = gamma_audio if st.get("group") == "acal" else (
            gamma_visual if st.get("group") == "aprime" else None)

    preds = cut_predicates(pstats, args)
    out_rows = []

    def run(cut_name, sub_audio, sub_visual):
        n_part_a = len({r["participant_id"] for r in sub_audio})
        n_part_v = len({r["participant_id"] for r in sub_visual})
        for ch in af.TARGET_CHARS:
            sub = [r for r in sub_audio if r["target_char"] == ch and not r["is_embedded_full"]]
            xs, ks, ns = af.aggregate_levels(sub, "gate_ms")
            fit = af.fit_sigmoid(xs, ks, ns, gamma_audio, n_starts=n_starts)
            out_rows.append(dict(cut=cut_name, modality="audio", char=ch, family="",
                                  mu=fit["mu"], lam=fit["lam"], n_trials=fit["n_trials"],
                                  n_participants=n_part_a, converged=fit["converged"]))
        for ch in af.TARGET_CHARS:
            for fam in families:
                sub = [r for r in sub_visual if r["target_char"] == ch and r["family"] == fam]
                xs, ks, ns = af.aggregate_levels(sub, level_key_v)
                fit = af.fit_sigmoid(xs, ks, ns, gamma_visual, n_starts=n_starts)
                out_rows.append(dict(cut=cut_name, modality="visual", char=ch, family=fam,
                                      mu=fit["mu"], lam=fit["lam"], n_trials=fit["n_trials"],
                                      n_participants=n_part_v, converged=fit["converged"]))

    # baseline
    run("baseline", rows_audio_main, rows_visual_main)

    # 試行単位のcut(反応時間)
    for cut in ("rt_iqr", "rt_min300"):
        sub_a = af.apply_trial_level_cut(rows_audio_main, cut, pstats)
        sub_v = af.apply_trial_level_cut(rows_visual_main, cut, pstats)
        run(cut, sub_a, sub_v)

    # 参加者単位のcut
    for name, pred in preds.items():
        if pred is None or name in ("baseline",):
            continue
        sub_a = [r for r in rows_audio_main if pred(r["participant_id"])]
        sub_v = [r for r in rows_visual_main if pred(r["participant_id"])]
        run(name, sub_a, sub_v)

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cut", "modality", "char", "family", "mu", "lambda", "n_trials",
                     "n_participants", "converged"])
        for r in out_rows:
            w.writerow([r["cut"], r["modality"], r["char"], r["family"],
                        af._fmt(r["mu"]), af._fmt(r["lam"]), r["n_trials"], r["n_participants"], r["converged"]])
    return out_rows, preds


def write_participant_stats_extended(path, pstats):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        cols = ["participant_id", "group", "full_acc", "full_acc_healthy", "floor_acc", "n_floor",
                 "decoy_acc", "n_decoy", "dominant_response_share", "resume_or_replay", "refresh_hz",
                 "audio_device"]
        w.writerow(cols)
        for pid, st in sorted(pstats.items()):
            w.writerow([pid] + [af._fmt(st.get(c)) if isinstance(st.get(c), float) else st.get(c)
                                  for c in cols[1:]])


# ---------------------------------------------------------------------------
# 6. 天井/床に届かない字の深掘り(依頼3)
# ---------------------------------------------------------------------------
def logistic_p(t, gamma, lam, mu, sigma):
    z = np.clip(-(np.asarray(t, dtype=float) - mu) / sigma, -500, 500)
    return gamma + (lam - gamma) / (1.0 + np.exp(z))


def q_normalize(p, gamma, lam):
    """
    正規化した「進み具合」q = (p-γ)/(λ-γ) 。t→∞でp→λなのでq→1になる定義
    (標準的な正規化)。λが低い、あるいはλ-γが小さいと、
      - 現実的な打ち切り時間の範囲では p がλに全然近づかず q が1に届かない
      - λ-γ自体が小さいとpのわずかな誤差でqが大きく暴れる(数値的に退化)
    という2つの意味で「逆引きが頭打ち/破綻する」。この関数はその両方を数値で
    確認するために使う。
    """
    denom = lam - gamma
    if denom <= 0:
        return None
    return (p - gamma) / denom


def inverse_t_for_q(q_target, gamma, lam, mu, sigma):
    """q_target を与える t を返す(ロジスティックの逆関数)。denom<=0なら None。"""
    denom = lam - gamma
    if denom <= 0 or not (0 < q_target < 1):
        return None
    p_target = gamma + denom * q_target
    ratio = (lam - gamma) / (p_target - gamma) - 1.0
    if ratio <= 0:
        return None
    return mu - sigma * math.log(ratio)


def fit_sigmoid_fixed_lambda(xs, ks, ns, gamma, lam_fixed, n_starts=6):
    """
    af.fit_sigmoid の2径版: λを lam_fixed に固定し、μ・σだけ最尤推定する。
    「打ち切りなし(embedded full)で実測した正答率」をそのままλに使うことで、
    『形(μ・σ)は取れているが少ない試行数のせいでλの自由推定が不安定』な字を
    安定させられるかを見る。
    """
    xs = np.asarray(xs, dtype=float)
    ks = np.asarray(ks, dtype=float)
    ns = np.asarray(ns, dtype=float)
    n_trials = int(ns.sum())
    if len(xs) < 2 or n_trials == 0:
        return dict(lam=lam_fixed, mu=float("nan"), sigma=float("nan"), converged=False,
                     note="水準不足で当てはめ不可", nll=float("nan"), n_trials=n_trials)
    xlo, xhi = float(xs.min()), float(xs.max())
    rng = xhi - xlo
    eps = 1e-9

    def nll(params):
        mu, sigma = params
        sigma = max(sigma, 1e-6)
        z = np.clip(-(xs - mu) / sigma, -500, 500)
        p = gamma + (lam_fixed - gamma) / (1.0 + np.exp(z))
        p = np.clip(p, eps, 1 - eps)
        return -float(np.sum(ks * np.log(p) + (ns - ks) * np.log(1 - p)))

    if not HAVE_SCIPY:
        return dict(lam=lam_fixed, mu=float("nan"), sigma=float("nan"), converged=False,
                     note="scipy無し: 未対応", nll=float("nan"), n_trials=n_trials)

    mu_candidates = sorted(set(np.percentile(xs, [15, 30, 50, 70, 85]).tolist()))[:max(1, n_starts)]
    sigma_candidates = [max(rng, 1e-3) * f for f in (0.05, 0.15, 0.35, 0.7)][:max(1, min(4, n_starts))]
    bounds = [(xlo - rng, xhi + rng), (max(rng * 1e-3, 1e-6), max(rng * 8, 1.0))]
    best = None
    for mu0 in mu_candidates:
        for s0 in sigma_candidates:
            try:
                res = minimize(nll, [mu0, s0], method="L-BFGS-B", bounds=bounds)
            except Exception:
                continue
            if best is None or res.fun < best.fun:
                best = res
    if best is None:
        return dict(lam=lam_fixed, mu=float("nan"), sigma=float("nan"), converged=False,
                     note="最適化が例外で失敗", nll=float("nan"), n_trials=n_trials)
    mu, sigma = (float(v) for v in best.x)
    note = "" if best.success else f"収束せず: {best.message}"
    return dict(lam=lam_fixed, mu=mu, sigma=sigma, converged=bool(best.success), note=note,
                nll=float(best.fun), n_trials=n_trials)


def isotonic_curve_and_fit(xs, ks, ns, gamma, n_starts=6):
    """
    非単調な字(し・ら)向け: 観測正答率を水準順に保序回帰(scipy.optimize.isotonic_regression、
    重みは試行数 n)で単調非減少に均してから、均した後の値を新しい「正答数」とみなして
    通常の二項最尤当てはめをやり直す。

    ⚠ 保序回帰は二乗誤差最小化であって二項尤度最小化ではないので、この2段階は
    厳密な最尤推定ではない近似(まず形を単調にする前処理、その後で改めて尤度当てはめ)
    にとどまる。それでも「非単調な凹凸を落とした後にμ・σが安定して取れるか」を
    確認する目的には十分。
    """
    xs = np.asarray(xs, dtype=float)
    ks = np.asarray(ks, dtype=float)
    ns = np.asarray(ns, dtype=float)
    acc = np.divide(ks, ns, out=np.zeros_like(ks), where=ns > 0)
    order = np.argsort(xs)
    xs_s, acc_s, ns_s = xs[order], acc[order], ns[order]
    iso = isotonic_regression(acc_s, weights=ns_s, increasing=True)
    p_iso = np.asarray(iso.x)
    k_iso = np.round(p_iso * ns_s)
    fit = af.fit_sigmoid(xs_s, k_iso, ns_s, gamma, n_starts=n_starts)
    curve = list(zip(xs_s.tolist(), acc_s.tolist(), p_iso.tolist(), ns_s.tolist()))
    return curve, fit


def is_nonmonotonic(xs, ks, ns, drop_threshold):
    """
    観測された生の正答率(水準順)が、途中で明確に下がっている区間を持つかを判定する。

    「それまでの最良水準の正答率」からの下げ幅が drop_threshold を超えたら非単調とみなす。
    しきい値の根拠: 1水準あたりおよそ n=30〜35 試行(較正フェーズの設計値)なので、
    正答率0.5近辺の二項比率の標準誤差は sqrt(0.5*0.5/30)≈0.09。drop_threshold=0.15は
    およそ1.7SE分の下げ幅で、偶然のブレにしては大きいという目安として置いた値
    (根拠は経験則。引数で変更可能)。
    """
    order = np.argsort(xs)
    xs_s = np.asarray(xs)[order]
    acc_s = np.divide(np.asarray(ks)[order], np.asarray(ns)[order],
                       out=np.zeros(len(xs)), where=np.asarray(ns)[order] > 0)
    best_so_far = -1.0
    best_x = None
    worst_drop = 0.0
    worst_detail = ""
    for x, a in zip(xs_s, acc_s):
        if best_so_far >= 0 and (best_so_far - a) > worst_drop:
            worst_drop = best_so_far - a
            worst_detail = f"{best_x:.0f}ms({best_so_far:.2f})→{x:.0f}ms({a:.2f})"
        if a > best_so_far:
            best_so_far = a
            best_x = x
    return (worst_drop > drop_threshold), worst_drop, worst_detail


def lowceil_diagnose_and_summarize(rows_audio_main, decoy_audio_rows, gamma_audio, n_starts,
                                    pstats, cut_preds, args):
    """
    依頼3本体。LOWCEIL_CHARS(つ・ぱ・ら・し・が)+ REF_CHARS(あ・か・ま、対照用)に対し、
    以下の方法をすべて試し、1つの summary(char×method)にまとめる:
      free       : λ自由推定(通常の当てはめ、af.fit_sigmoid そのもの)
      fixed_full : embedded-full(打ち切りなし)実測正答率にλを固定して μ・σ を当てはめる
      isotonic   : 保序回帰で単調化してから当てはめる(し・らにのみ適用)
      strict     : 依頼2の厳しい版参加者選別後に free と同じ当てはめをやり直す
    どの方法についても、q_normalize/inverse_t_for_q を使って「逆引きがどこまで使えるか」
    を数値化する(観測した最大打ち切り時間 t_max_obs での q、q=0.5/0.8/0.95に届くのに
    必要な t、それが観測範囲の中に収まっているか)。

    さらに「床が取れていない(つ)」かどうかを見るため、観測した最小打ち切り時間 t_min_obs
    での q (q_at_tmin) を計算する。これが高い(既にかなり読めている)ならば、その字は
    「天井」でなく「短い側=床」が課題であることの直接の根拠になる。
    """
    t_max_obs_global = max(r["gate_ms"] for r in rows_audio_main + decoy_audio_rows
                             if r["gate_ms"] is not None)  # 観測された最大打ち切り時間(全字共通の上限、150ms)

    summary = []
    isotonic_curves = []

    def q_metrics(gamma, lam, mu, sigma, xs_obs):
        if math.isnan(lam) or math.isnan(mu) or math.isnan(sigma) or (lam - gamma) <= 0:
            return dict(q_at_tmin=None, q_at_tmax_obs=None, q_at_tmax_global=None,
                         t_for_q50=None, t_for_q80=None, t_for_q95=None,
                         degenerate=True, note_q="lambda<=gammaで正規化不能(逆引き完全に退化)")
        t_min_obs, t_max_obs = min(xs_obs), max(xs_obs)
        p_min = logistic_p(t_min_obs, gamma, lam, mu, sigma)
        p_max_obs = logistic_p(t_max_obs, gamma, lam, mu, sigma)
        p_max_global = logistic_p(t_max_obs_global, gamma, lam, mu, sigma)
        q_min = q_normalize(p_min, gamma, lam)
        q_maxobs = q_normalize(p_max_obs, gamma, lam)
        q_maxglobal = q_normalize(p_max_global, gamma, lam)
        t50 = inverse_t_for_q(0.5, gamma, lam, mu, sigma)
        t80 = inverse_t_for_q(0.8, gamma, lam, mu, sigma)
        t95 = inverse_t_for_q(0.95, gamma, lam, mu, sigma)
        notes = []
        if (lam - gamma) < args.lam_gap_degenerate:
            notes.append(f"lambda-gamma={lam - gamma:.3f}が小さく数値的に不安定")
        for lbl, t in (("q50", t50), ("q80", t80), ("q95", t95)):
            if t is not None and t > t_max_obs_global:
                notes.append(f"{lbl}到達には観測最大({t_max_obs_global:.0f}ms)を超える外挿(t={t:.0f}ms)が必要")
        return dict(q_at_tmin=q_min, q_at_tmax_obs=q_maxobs, q_at_tmax_global=q_maxglobal,
                    t_for_q50=t50, t_for_q80=t80, t_for_q95=t95,
                    degenerate=False, note_q=";".join(notes))

    def add_summary(ch, method, gamma, fit, xs_obs, extra_note="", extra_fields=None):
        qm = q_metrics(gamma, fit["lam"], fit["mu"], fit["sigma"], xs_obs) if xs_obs else dict(
            q_at_tmin=None, q_at_tmax_obs=None, q_at_tmax_global=None,
            t_for_q50=None, t_for_q80=None, t_for_q95=None, degenerate=True, note_q="水準なし")
        note = ";".join(p for p in (fit.get("note", ""), extra_note, qm["note_q"]) if p)
        row = dict(char=ch, method=method, gamma=gamma, lam=fit["lam"], mu=fit["mu"],
                   sigma=fit["sigma"], converged=fit.get("converged"), n_trials=fit.get("n_trials"),
                   note=note, **{k: v for k, v in qm.items() if k != "note_q"})
        row.update(extra_fields or {})
        summary.append(row)
        return row

    chars_all = LOWCEIL_CHARS + REF_CHARS
    strict_pred = cut_preds["strict(組み合わせ)"]
    full_obs_all = af.observed_full_audio(rows_audio_main)

    for ch in chars_all:
        sub = [r for r in rows_audio_main if r["target_char"] == ch and not r["is_embedded_full"]]
        xs, ks, ns = af.aggregate_levels(sub, "gate_ms")

        # --- 床/天井の判定に使う「経験的な」q ---
        # モデル自身のλを基準にした q_at_tmin/q_at_tmax_obs (q_metrics内)は、σが極端に
        # 小さい退化的な当てはめだと「モデルの中では自己矛盾なく天井に届いている」ことに
        # なってしまい(例: ぱ)、実際にはfull実測より大幅に低いλで頭打ちしている問題を
        # 見逃す。そこで分類には「打ち切りなし(embedded full)の実測正答率」を基準にした
        # 経験的なqを別途使う: q_emp(t) = (観測正答率(t) - γ) / (full実測 - γ)。
        ok_f0, n_f0 = full_obs_all.get(ch, (0, 0))
        lam_obs_full = ok_f0 / n_f0 if n_f0 else float("nan")
        acc_at_tmin = acc_at_tmax = q_emp_tmin = q_emp_tmax = None
        if len(xs) >= 1:
            order = np.argsort(xs)
            xs_s = np.asarray(xs)[order]; ks_s = np.asarray(ks)[order]; ns_s = np.asarray(ns)[order]
            acc_at_tmin = float(ks_s[0] / ns_s[0]) if ns_s[0] else None
            acc_at_tmax = float(ks_s[-1] / ns_s[-1]) if ns_s[-1] else None
            denom = lam_obs_full - gamma_audio
            if not math.isnan(lam_obs_full) and denom > 0:
                if acc_at_tmin is not None:
                    q_emp_tmin = (acc_at_tmin - gamma_audio) / denom
                if acc_at_tmax is not None:
                    q_emp_tmax = (acc_at_tmax - gamma_audio) / denom

        nonmono, nonmono_drop, nonmono_detail = (
            is_nonmonotonic(xs, ks, ns, args.nonmonotonic_drop_threshold) if len(xs) >= 2 else (False, 0.0, ""))

        # method 1: free(通常のλ自由推定)
        fit_free = af.fit_sigmoid(xs, ks, ns, gamma_audio, n_starts=n_starts)
        add_summary(ch, "free", gamma_audio, fit_free, xs, extra_fields=dict(
            acc_at_tmin=acc_at_tmin, acc_at_tmax=acc_at_tmax, lambda_observed_full=lam_obs_full,
            q_emp_tmin=q_emp_tmin, q_emp_tmax=q_emp_tmax,
            nonmonotonic=nonmono, nonmonotonic_drop=nonmono_drop, nonmonotonic_detail=nonmono_detail))

        # method 2: fixed_full(打ち切りなし実測でλ固定)。REF_CHARSは天井問題が無いので参考として省略しない。
        full_obs = af.observed_full_audio(rows_audio_main)
        ok_f, n_f = full_obs.get(ch, (0, 0))
        if n_f > 0:
            lam_fixed = ok_f / n_f
            fit_fixed = fit_sigmoid_fixed_lambda(xs, ks, ns, gamma_audio, lam_fixed, n_starts=n_starts)
            add_summary(ch, "fixed_full", gamma_audio, fit_fixed, xs,
                        extra_note=f"lambdaをfull実測{lam_fixed:.3f}(n={n_f})に固定")
        else:
            summary.append(dict(char=ch, method="fixed_full", gamma=gamma_audio, lam=float("nan"),
                                 mu=float("nan"), sigma=float("nan"), converged=False, n_trials=0,
                                 note="full実測データなし", q_at_tmin=None, q_at_tmax_obs=None,
                                 q_at_tmax_global=None, t_for_q50=None, t_for_q80=None, t_for_q95=None))

        # method 3: isotonic(非単調字のみ: し・ら)
        if ch in ("し", "ら") and len(xs) >= 2:
            curve, fit_iso = isotonic_curve_and_fit(xs, ks, ns, gamma_audio, n_starts=n_starts)
            for x, acc_raw, acc_iso, n in curve:
                isotonic_curves.append(dict(char=ch, level=x, accuracy_raw=acc_raw,
                                             accuracy_isotonic=acc_iso, n=n))
            add_summary(ch, "isotonic", gamma_audio, fit_iso, xs,
                        extra_note="保序回帰で単調化した後に再当てはめ")

        # method 4: strict(依頼2の厳しい版参加者選別後)
        sub_strict = [r for r in sub if strict_pred(r["participant_id"])]
        xs_s, ks_s, ns_s = af.aggregate_levels(sub_strict, "gate_ms")
        fit_strict = af.fit_sigmoid(xs_s, ks_s, ns_s, gamma_audio, n_starts=n_starts)
        n_part_strict = len({r["participant_id"] for r in sub_strict})
        add_summary(ch, "strict", gamma_audio, fit_strict, xs_s if len(xs_s) else xs,
                    extra_note=f"厳しい版参加者選別後(残り{n_part_strict}人)")

    return summary, isotonic_curves, t_max_obs_global


def write_lowceiling_summary(path, summary):
    cols = ["char", "method", "gamma", "lambda", "mu", "sigma", "converged", "n_trials",
             "q_at_tmin", "q_at_tmax_obs", "q_at_tmax_global", "t_for_q50", "t_for_q80", "t_for_q95",
             "acc_at_tmin", "acc_at_tmax", "lambda_observed_full", "q_emp_tmin", "q_emp_tmax",
             "nonmonotonic", "nonmonotonic_drop", "nonmonotonic_detail", "note"]

    def g(r, k):
        v = r.get(k)
        if v is None:
            return ""
        return af._fmt(v) if isinstance(v, float) else v

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in summary:
            w.writerow([r["char"], r["method"], round(r["gamma"], 5) if r["gamma"] is not None else "",
                        af._fmt(r["lam"]), af._fmt(r["mu"]), af._fmt(r["sigma"]), r["converged"], r["n_trials"],
                        g(r, "q_at_tmin"), g(r, "q_at_tmax_obs"), g(r, "q_at_tmax_global"),
                        g(r, "t_for_q50"), g(r, "t_for_q80"), g(r, "t_for_q95"),
                        g(r, "acc_at_tmin"), g(r, "acc_at_tmax"), g(r, "lambda_observed_full"),
                        g(r, "q_emp_tmin"), g(r, "q_emp_tmax"),
                        g(r, "nonmonotonic"), g(r, "nonmonotonic_drop"), g(r, "nonmonotonic_detail"),
                        r["note"]])


def write_isotonic_curve(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "level_ms", "accuracy_raw", "accuracy_isotonic", "n_trials"])
        for r in rows:
            w.writerow([r["char"], r["level"], round(r["accuracy_raw"], 4), round(r["accuracy_isotonic"], 4), r["n"]])


# ---------------------------------------------------------------------------
# 7. 使用可否の判定表
# ---------------------------------------------------------------------------
def classify_problem(ch, free_row, q_at_tmin_thr, q_at_tmax_thr, lam_gap_degenerate):
    """
    free法の結果から問題の種類を1つに分類する(優先順位: 平坦 > 床未達 > 非単調 > 天井未達 > なし。
    理由は下の⚠を参照)。しきい値は引数(main()のargsから渡す)で、既定値の根拠はargparseのhelpに書く。

    ⚠ 床/天井の判定は、当てはめモデル自身のλを基準にした q_at_tmin/q_at_tmax_obs ではなく、
    「打ち切りなし(embedded full)の実測正答率」を基準にした経験的な q_emp_tmin/q_emp_tmax を
    使う。モデル自身のλ基準だと、σが極端に小さい(ほぼ階段状の)当てはめのときに
    「モデルの中では矛盾なく天井に届いている」ことになってしまい、実際にはfull実測より
    大幅に低いλで頭打ちしている字(例: ぱ)を見逃す。実測full基準ならこの自己整合の罠を避けられる。
    ⚠ 優先順位は 平坦 > 床未達 > 非単調 > 天井未達 > なし。床未達を非単調より先に見る理由:
    「つ」は35ms水準だけ正答率が0.71→0.41へ落ちる区間を持ち、機械的な非単調判定にも
    かかる(nonmonotonic_drop=0.29)。しかしこの落ち込みは1水準だけ(n≈34)であり、
    q_emp_tmin=0.46 と最短水準で既に立ち上がりの半分近くまで来ている(床が見えていない)
    ことのほうが、7水準中1点だけの落ち込み(観測数が少ない下での偶然のブレの可能性が高い)
    より、この字の曲線が使えない理由として本質的・構造的(=追加のより短い水準を測らない限り
    解決しない)である。実際、非単調が明確な し・ら は q_emp_tmin がそれぞれ0.11・-0.03と
    低く、床未達には該当しない(=両者は取り違えていない)。
    """
    lam, gamma = free_row["lam"], free_row["gamma"]
    lam_obs_full = free_row.get("lambda_observed_full")
    # 平坦の判定はfull実測を優先(モデルのλ推定はノイズで負に振れることがある: がのlam=0.008<gamma)。
    # full実測が無ければモデルのλで代用する。
    ceiling_ref = lam_obs_full if (lam_obs_full is not None and not math.isnan(lam_obs_full)) else lam
    if ceiling_ref is None or math.isnan(ceiling_ref) or (ceiling_ref - gamma) < lam_gap_degenerate:
        return "平坦", (f"full実測正答率({af._fmt(lam_obs_full)})とfit λ({af._fmt(lam)})がともに"
                        f"gamma({gamma:.3f})とほぼ同じか下回り、天井が実質存在しない")
    q_tmin = free_row.get("q_emp_tmin")
    q_tmax = free_row.get("q_emp_tmax")
    if q_tmin is not None and q_tmin >= q_at_tmin_thr:
        return "床未達", (f"最短打ち切り時間で既にfull実測基準のq={q_tmin:.2f}"
                         f"(しきい値{q_at_tmin_thr}以上)に達しており、"
                         "立ち上がりの前半(床)が観測範囲より短い側に隠れている")
    if free_row.get("nonmonotonic"):
        detail = free_row.get("nonmonotonic_detail", "")
        return "非単調", f"打ち切り時間を延ばすと正答率が下がる区間がある(観測データそのものが非単調: {detail})"
    if q_tmax is not None and q_tmax < q_at_tmax_thr:
        return "天井未達", (f"観測最大打ち切り時間でもfull実測基準のq={q_tmax:.2f}"
                          f"(しきい値{q_at_tmax_thr}未満)にとどまり、"
                          "天井(full実測)に届く前に打ち切り時間の範囲が尽きている")
    return "なし", "曲線として問題なく使える"


def write_usability_table(path, summary, args):
    """
    char×method の summary から char ごとに1行の判定表を作る。
    列: problem_type(天井未達/床未達/非単調/平坦/なし)、reason(なぜ)、
        q_reversible(逆引きが成り立つか: yes/partial/no)、
        best_method(どの処置が最も有効か)、verdict(使える/条件付き/使えない)。
    """
    by_char = defaultdict(dict)
    for r in summary:
        by_char[r["char"]][r["method"]] = r

    rows_out = []
    for ch in LOWCEIL_CHARS + REF_CHARS:
        methods = by_char.get(ch, {})
        free = methods.get("free")
        if free is None:
            continue
        ptype, reason = classify_problem(ch, free, args.floor_q_threshold, args.ceiling_q_threshold,
                                          args.lam_gap_degenerate)

        # q_reversible: 「観測された打ち切り時間の上限(全字共通150ms)まで使ったとき、
        # モデル自身のλを基準にした正規化qがどこまで届くか」で判定する
        # (q_at_tmax_global。0.8以上=yes、0.3〜0.8=partial、それ未満/退化=no)。
        # ⚠ これは classify_problem の床/天井判定(full実測基準)とは基準が異なる指標であることに注意:
        # ここは「今ある(λ,μ,σ)の当てはめをそのまま転写の逆引きに使って良いか」という
        # 別の問いに答えるためのもの。
        qmax = free["q_at_tmax_global"]
        if free["lam"] is None or math.isnan(free["lam"]) or (free["lam"] - free["gamma"]) < args.lam_gap_degenerate:
            q_rev = "no(退化)"
        elif qmax is None:
            q_rev = "no(算出不可)"
        elif qmax >= 0.8:
            q_rev = "yes"
        elif qmax >= 0.3:
            q_rev = "partial"
        else:
            q_rev = "no"

        # best_method: 問題の種類に応じて、どの処置が理にかなっているかを機械的に選ぶのではなく
        # 診断結果から人が読める形で提案する(処置の効果そのものは各csvの数値で確認する)。
        if ptype == "平坦":
            best = "(なし: が の刺激不良は処置では解決しない)"
        elif ptype == "非単調":
            best = "isotonic"
        elif ptype == "床未達":
            best = "(なし: 短い打ち切り水準の追加測定が必要。fixed_full/strictでは解決しない)"
        elif ptype == "天井未達":
            best = "fixed_full or strict(どちらがλを上げるかはlowceiling_summary.csvで確認)"
        else:
            best = "free(そのままで良い)"

        # verdict
        if ptype == "なし":
            verdict = "使える"
        elif ptype == "平坦":
            verdict = "使えない"
        elif ptype in ("床未達",):
            verdict = "使えない(現状データでは)"
        else:
            verdict = "条件付きで使える" if q_rev in ("yes", "partial") else "使えない"

        rows_out.append(dict(char=ch, problem_type=ptype, reason=reason, q_reversible=q_rev,
                              q_at_tmax_global=free["q_at_tmax_global"], best_method=best, verdict=verdict))

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "problem_type", "reason", "q_reversible", "q_at_tmax_global(free)",
                     "best_method", "verdict"])
        for r in rows_out:
            w.writerow([r["char"], r["problem_type"], r["reason"], r["q_reversible"],
                        af._fmt(r["q_at_tmax_global"]) if r["q_at_tmax_global"] is not None else "",
                        r["best_method"], r["verdict"]])
    return rows_out


# ---------------------------------------------------------------------------
# HTMLレポート
# ---------------------------------------------------------------------------
def fig_to_data_uri(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def build_report(path, ctx):
    """matplotlibで要所の図を作り、data URIとして埋め込んだ単一HTMLを書き出す。"""
    imgs = {}

    # 図1: まぎれ字(聴覚)の清濁半濁タイプ別・束ねた曲線
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for g, fam, xs, ks, ns, fit, n_chars in ctx["bundle_type_audio"]:
        acc = [k / n if n else float("nan") for k, n in zip(ks, ns)]
        ax.plot(xs, acc, "o-", label=f"{g}(字数{n_chars})")
    ax.set_xlabel("打ち切り時間 (ms)")
    ax.set_ylabel("正答率")
    ax.set_title("まぎれ字(聴覚): 清濁半濁タイプ別の束ねた曲線")
    ax.legend(fontsize=8)
    ax.set_ylim(0, 1)
    imgs["bundle_type_audio"] = fig_to_data_uri(fig)

    # 図2: 視覚方式ごとの安定性(λ・σの分布)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    fams = sorted({r["family"] for r in ctx["fit_decoy_visual"]})
    lam_by_fam = {fam: [r["lam"] for r in ctx["fit_decoy_visual"] if r["family"] == fam and not math.isnan(r["lam"])]
                  for fam in fams}
    sig_by_fam = {fam: [abs(r["sigma"]) for r in ctx["fit_decoy_visual"] if r["family"] == fam and not math.isnan(r["sigma"])]
                  for fam in fams}
    axes[0].boxplot([lam_by_fam[f] for f in fams], tick_labels=fams)
    axes[0].set_title("まぎれ字63字: 方式別λの分布")
    axes[0].set_ylim(0, 1.05)
    axes[1].boxplot([sig_by_fam[f] for f in fams], tick_labels=fams)
    axes[1].set_title("まぎれ字63字: 方式別σの分布(絶対値)")
    imgs["family_stability"] = fig_to_data_uri(fig)

    # 図3: 依頼2 感度分析(本命8字λの、cutごとの動き; 聴覚のみ抜粋)
    fig, ax = plt.subplots(figsize=(9, 5))
    cuts = []
    seen = set()
    for r in ctx["sensitivity_participant"]:
        if r["modality"] == "audio" and r["cut"] not in seen:
            cuts.append(r["cut"]); seen.add(r["cut"])
    for ch in af.TARGET_CHARS:
        ys = []
        for cut in cuts:
            match = [r for r in ctx["sensitivity_participant"]
                     if r["modality"] == "audio" and r["char"] == ch and r["cut"] == cut]
            ys.append(match[0]["lam"] if match and not math.isnan(match[0]["lam"]) else np.nan)
        ax.plot(range(len(cuts)), ys, "o-", label=ch, alpha=0.8)
    ax.set_xticks(range(len(cuts)))
    ax.set_xticklabels(cuts, rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("lambda(推定天井)")
    ax.set_title("参加者選別の切り方ごとの本命8字λ(聴覚)")
    ax.legend(fontsize=7, ncol=4)
    ax.set_ylim(-0.05, 1.05)
    imgs["sensitivity_lambda"] = fig_to_data_uri(fig)

    # 図4: 天井/床未達5字の diagnostic curves(free fit + 観測点)
    fig, axes = plt.subplots(2, 3, figsize=(12, 7))
    chars_plot = LOWCEIL_CHARS + REF_CHARS
    for ax, ch in zip(axes.flat, chars_plot):
        sub = [r for r in ctx["rows_audio_main"] if r["target_char"] == ch and not r["is_embedded_full"]]
        xs, ks, ns = af.aggregate_levels(sub, "gate_ms")
        acc = [k / n if n else float("nan") for k, n in zip(ks, ns)]
        ax.plot(xs, acc, "o", color="black", label="観測")
        free = [r for r in ctx["lowceil_summary"] if r["char"] == ch and r["method"] == "free"][0]
        if not math.isnan(free["mu"]):
            tt = np.linspace(min(xs) - 5, max(ctx["t_max_obs_global"], max(xs)) + 5, 200)
            pp = logistic_p(tt, free["gamma"], free["lam"], free["mu"], free["sigma"])
            ax.plot(tt, pp, "-", color="tab:blue", label=f"free(λ={free['lam']:.2f})")
        ax.axhline(ctx["gamma_audio"], color="gray", linestyle=":", linewidth=1)
        ax.set_title(ch)
        ax.set_ylim(0, 1)
    for ax in axes.flat[len(chars_plot):]:
        ax.axis("off")
    fig.suptitle("聴覚: 天井/床未達5字(左)と参照3字(右)の観測点とfree当てはめ")
    imgs["lowceil_curves"] = fig_to_data_uri(fig)

    # 図5: し・らの isotonic 前後比較
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    for ax, ch in zip(axes, ("し", "ら")):
        rows = [r for r in ctx["isotonic_curves"] if r["char"] == ch]
        rows.sort(key=lambda r: r["level"])
        xs = [r["level"] for r in rows]
        ax.plot(xs, [r["accuracy_raw"] for r in rows], "o--", label="観測(生)", color="tab:orange")
        ax.plot(xs, [r["accuracy_isotonic"] for r in rows], "o-", label="保序回帰後", color="tab:blue")
        ax.set_title(ch)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=8)
    fig.suptitle("非単調字(し・ら)の保序回帰による単調化")
    imgs["isotonic"] = fig_to_data_uri(fig)

    html = render_html(ctx, imgs)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(html)


def render_html(ctx, imgs):
    usability_rows = "".join(
        f"<tr><td>{r['char']}</td><td>{r['problem_type']}</td><td>{r['reason']}</td>"
        f"<td>{r['q_reversible']}</td><td>{af._fmt(r['q_at_tmax_global']) if r['q_at_tmax_global'] is not None else '-'}</td>"
        f"<td>{r['best_method']}</td><td><b>{r['verdict']}</b></td></tr>"
        for r in ctx["usability_table"])

    n_part_by_cut = {}
    for r in ctx["sensitivity_participant"]:
        if r["modality"] == "audio" and r["char"] == "あ":
            n_part_by_cut[r["cut"]] = r["n_participants"]
    cut_rows = "".join(
        f"<tr><td>{cut}</td><td>{n}</td></tr>" for cut, n in n_part_by_cut.items())

    return f"""<title>較正フェーズ深掘り解析</title>
<style>
  :root {{ --bg:#faf8f3; --fg:#1d1a15; --sub:#6b6255; --line:#ddd6c8; --accent:#8a5a34; --card:#fff; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{ --bg:#181511; --fg:#ece7dc; --sub:#a89e8c; --line:#3a352b; --accent:#d3a373; --card:#221e18; }}
  }}
  :root[data-theme="dark"] {{ --bg:#181511; --fg:#ece7dc; --sub:#a89e8c; --line:#3a352b; --accent:#d3a373; --card:#221e18; }}
  body {{ background:var(--bg); color:var(--fg); font-family:"Hiragino Mincho ProN","Yu Mincho",serif;
          max-width:980px; margin:0 auto; padding:2.5rem 1.5rem 6rem; line-height:1.85; }}
  h1 {{ font-size:1.6rem; border-bottom:2px solid var(--accent); padding-bottom:.5rem; }}
  h2 {{ font-size:1.25rem; margin-top:3rem; color:var(--accent); }}
  h3 {{ font-size:1.05rem; margin-top:1.8rem; }}
  table {{ border-collapse:collapse; width:100%; margin:1rem 0; font-size:.88rem; }}
  th, td {{ border:1px solid var(--line); padding:.4rem .6rem; text-align:left; vertical-align:top; }}
  th {{ background:var(--card); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:1.2rem 1.5rem; margin:1.2rem 0; }}
  img {{ max-width:100%; display:block; margin:1rem auto; }}
  code {{ background:var(--card); padding:.1rem .3rem; border-radius:3px; }}
  .note {{ color:var(--sub); font-size:.85rem; }}
  .verdict-ok {{ color:#3a7d3a; }}
</style>

<h1>較正フェーズ深掘り解析</h1>
<p class="note">project/data_calib_20260825/transfer_trials.csv 253人 を用いた追加解析。
既存の analyze_calib_full.py による本命8字の解析(analysis/ 以下)を前提に、まぎれ字・参加者選別・
天井/床未達字の3点を掘り下げた。</p>

<h2>結論(先出し)</h2>
<div class="card">
<h3>依頼1: まぎれ字</h3>
<p>聴覚のまぎれ字59字の当てはめから、λ(天井)が低い字は濁音・半濁音に集中しており、
清音の刺激はおおむね天井に届いている一方、濁音全体で天井が崩れていることが本命8字だけでなく
59字規模で確認できた(<code>fit_decoy_audio.csv</code>、束ねた曲線は<code>bundle_fit_audio.csv</code>)。
視覚は63字全体でも方式間の当てはめ収束率・σのばらつきに大きな差はなく、本命8字だけで見えていた
傾向が字数を増やしても崩れないことを確認した(<code>family_stability_visual.csv</code>)。</p>

<h3>依頼2: 参加者選別</h3>
<p>切り方を変えても本命8字のλ・μの並び(あ・か・まが高く、が が最低という順序)は崩れなかった。
ただし厳しくするほど残る人数は減り、区間は広くなる(下表、詳細は<code>sensitivity_participant.csv</code>)。</p>
<table><tr><th>cut</th><th>残った参加者数(聴覚、参考にあ字)</th></tr>{cut_rows}</table>

<h3>依頼3: 天井/床未達5字</h3>
<p><b>「つ」と他4字は問題の種類が異なる。</b>つ は床(短い側)が取れておらず、ぱ・ら・し は天井、
し・ら は非単調、が は平坦(λがγを下回り正規化が数値的に破綻)。処置ごとの効果は
<code>lowceiling_summary.csv</code>に、最終判定は下表(<code>usability_table.csv</code>)にまとめた。</p>
<table>
<tr><th>字</th><th>問題の種類</th><th>理由</th><th>逆引き</th><th>q(観測最大)</th><th>有効そうな処置</th><th>判定</th></tr>
{usability_rows}
</table>
</div>

<h2>依頼1: まぎれ字の分析</h2>
<p>まぎれ字は聴覚59字・視覚63字あり、本命8字と同じ水準ラダー・同じ方式で出題されている。
字ごとの生曲線は<code>curves_decoy_audio.csv</code>/<code>curves_decoy_visual.csv</code>、
字ごとの当てはめは<code>fit_decoy_audio.csv</code>/<code>fit_decoy_visual.csv</code>
(行・清濁半濁・画数四分位のメタ情報つき)。</p>
<img src="{imgs['bundle_type_audio']}" alt="清濁半濁タイプ別の束ねた曲線">
<p class="note">清音は10ms付近から立ち上がって100ms前後で天井に近づくのに対し、濁音は終始低い水準に
張り付く。半濁音(ぱ含む)は中間的。束ね方の根拠: 同じ水準ラダーを共有しているため、
異なる字の試行を同じ水準でそのまま合算しても水準の意味はずれない(<code>pool_and_fit</code>のコメント参照)。</p>

<img src="{imgs['family_stability']}" alt="視覚方式ごとのλ・σの分布">
<p class="note">まぎれ字63字ぶんで見ても、方式間でλの中央値・ばらつきに極端な差はない
(<code>family_stability_visual.csv</code>)。本命8字だけでは字数が少なく方式の優劣を言い切れなかったが、
63字規模でも同様の傾向であることが確認できた。</p>

<p>本命8字とまぎれ字の比較は、本命側の観測水準ごとに最も近いまぎれ字側の水準を探して対応づける
「最近傍水準マッチング」で行った(<code>compare_main_vs_decoy.csv</code>、
全まぎれ字プールとの比較・同タイプ(清濁半濁)まぎれ字プールとの比較の両方を出している)。
本命は水準が少なく回帰的な比較はできないため、この方式にした。</p>

<h2>依頼2: 参加者選別</h2>
<img src="{imgs['sensitivity_lambda']}" alt="参加者選別ごとの本命8字λ(聴覚)">
<p class="note">聴覚は「が」がどの切り方でもλ0近辺に留まる一方、あ・か・まは常に高い。
切り方によって多少上下はするが、字の順序(どれが読み取りやすいか)は入れ替わらない。
詳細な数値と残存人数は<code>sensitivity_participant.csv</code>、
参加者ごとの拡張指標は<code>participant_stats_extended.csv</code>。</p>

<h2>依頼3: 天井/床未達5字の掘り下げ</h2>
<img src="{imgs['lowceil_curves']}" alt="5字+参照3字の観測点とfree当てはめ">
<p class="note">つ は最短打ち切り時間(10ms)で既に正答率が高く、観測範囲の左端より前で
既にかなり立ち上がっていることが見て取れる(床未達)。ぱ・ら・し は右端(観測最大)でも
天井に届いていない(天井未達)。が は全域が下限γ付近に張り付いたまま(平坦)。</p>

<img src="{imgs['isotonic']}" alt="し・らの保序回帰前後">
<p class="note">し・ら は保序回帰で単調化すると滑らかな立ち上がりになる。単調化後に
再当てはめしたλ・μ・σは<code>lowceiling_summary.csv</code>(method=isotonic)。</p>

<h3>使用可否の判定(詳細)</h3>
<table>
<tr><th>字</th><th>問題の種類</th><th>理由</th><th>逆引き可否</th><th>q(観測最大打ち切り時間)</th><th>有効そうな処置</th><th>判定</th></tr>
{usability_rows}
</table>
<p class="note">q_reversible は q=(p-γ)/(λ-γ) の正規化がどこまで機能するかを表す
(yes: 観測範囲内でq≥0.8に到達 / partial: q≥0.3だが0.8未満 / no: それ未満、
退化はλがγを実質下回り正規化自体が成立しない場合)。詳しい算出方法は
analyze_calib_deep.py の q_metrics/inverse_t_for_q のコメントを参照。</p>
"""


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="project/data_calib_20260825/transfer_trials.csv")
    ap.add_argument("--out", default="project/data_calib_20260825/analysis_deep")
    ap.add_argument("--report", default="project/data_calib_20260825/deep_report.html")
    ap.add_argument("--fit-starts", type=int, default=6)
    ap.add_argument("--visual-axis", choices=["actual", "nominal"], default="actual")
    ap.add_argument("--lambda-warn", type=float, default=0.5)
    ap.add_argument("--lambda-diff-warn", type=float, default=0.15)

    # 依頼2: 参加者選別のしきい値(指示どおりの既定値)
    ap.add_argument("--full-acc-thresholds", type=float, nargs="+", default=[0.5, 0.67, 0.83, 1.0],
                    help="確認問題A正答率のカットライン(既定 指示どおり50/67/83/100%)")
    ap.add_argument("--same-response-thresholds", type=float, nargs="+", default=[0.2, 0.3, 0.5],
                    help="同一反応割合のカットライン(既定 指示どおり20/30/50%)")
    ap.add_argument("--floor-overacc-mults", type=float, nargs="+", default=[2.0, 3.0],
                    help="floor(最小提示)正答率がgammaの何倍を超えたら除外するか(既定2倍・3倍。"
                         "偶然のブレ(二項分布)より明確に高いと言えるラインの目安として置いた値)")
    ap.add_argument("--decoy-acc-thresholds", type=float, nargs="+", default=[0.1, 0.2, 0.3],
                    help="まぎれ字正答率の下限カットライン(既定0.1/0.2/0.3。まぎれ字はγ=1/68,1/72に近い"
                         "水準も多く全体正答率は低めに出るため、本命確認問題より緩い値にした)")
    ap.add_argument("--strict-full-acc-healthy", type=float, default=0.83,
                    help="厳しい版: 健全字確認問題A正答率の下限(既定0.83)")
    ap.add_argument("--strict-same-response", type=float, default=0.3,
                    help="厳しい版: 同一反応割合の上限(既定0.3)")
    ap.add_argument("--strict-decoy-acc", type=float, default=0.2,
                    help="厳しい版: まぎれ字正答率の下限(既定0.2)")
    ap.add_argument("--strict-floor-overacc-mult", type=float, default=3.0,
                    help="厳しい版: floor正答率がgammaの何倍を超えたら除外するか(既定3倍)")

    # 依頼3: 天井/床未達の判定しきい値
    ap.add_argument("--floor-q-threshold", type=float, default=0.3,
                    help="観測最小打ち切り時間でのqがこれ以上なら『床未達』とみなす(既定0.3)。"
                         "根拠: 最短時間で既に立ち上がりの3割以上を消化しているなら、"
                         "本当の床(chance近辺)はそれより短い側にあると考えられるため")
    ap.add_argument("--ceiling-q-threshold", type=float, default=0.8,
                    help="観測最大打ち切り時間でのqがこれ未満なら『天井未達』とみなす(既定0.8)")
    ap.add_argument("--lam-gap-degenerate", type=float, default=0.05,
                    help="lambda-gammaがこれ未満なら正規化(q)が数値的に退化しているとみなす(既定0.05)")
    ap.add_argument("--nonmonotonic-drop-threshold", type=float, default=0.15,
                    help="観測正答率が『それまでの最良水準』からこれ以上下がったら非単調とみなす"
                         "(既定0.15。1水準あたりn≈30〜35試行での二項比率の標準誤差≈0.09の"
                         "約1.7倍で、偶然のブレでは説明しにくい下げ幅の目安)")

    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    print(f"読み込み: {args.inp}")
    raw = af.load(args.inp)
    raw = af.normalize(raw)
    base = af.base_filter(raw)

    rows_audio_all = [r for r in base if r["modality_g"] == "audio"]
    rows_visual_all = [r for r in base if r["modality_g"] == "visual"]
    main_all = af.main_target_rows(base)
    rows_audio_main = [r for r in main_all if r["modality_g"] == "audio"]
    rows_visual_main = [r for r in main_all if r["modality_g"] == "visual"]

    decoy_all = decoy_target_rows(base)
    decoy_audio = [r for r in decoy_all if r["modality_g"] == "audio"]
    decoy_visual = [r for r in decoy_all if r["modality_g"] == "visual"]
    print(f"  まぎれ字: 聴覚{len(decoy_audio)}行({len({r['target_char'] for r in decoy_audio})}字) / "
          f"視覚{len(decoy_visual)}行({len({r['target_char'] for r in decoy_visual})}字)")

    gamma_audio, n_choices_audio = af.default_gamma(rows_audio_main, "audio")
    gamma_visual, n_choices_visual = af.default_gamma(rows_visual_main, "visual")
    print(f"  gamma: 聴覚=1/{n_choices_audio}={gamma_audio:.5f}, 視覚=1/{n_choices_visual}={gamma_visual:.5f}")

    out = args.out

    # ============ 依頼1: まぎれ字 ============
    write_curves_decoy_audio(os.path.join(out, "curves_decoy_audio.csv"), decoy_audio)
    write_curves_decoy_visual(os.path.join(out, "curves_decoy_visual.csv"), decoy_visual)
    print("  書き出し: curves_decoy_audio.csv, curves_decoy_visual.csv")

    fit_decoy_a = fit_decoy_audio(decoy_audio, gamma_audio, args.fit_starts, args.lambda_warn, args.lambda_diff_warn)
    fit_decoy_v = fit_decoy_visual(decoy_visual, gamma_visual, args.fit_starts, args.lambda_warn,
                                    args.lambda_diff_warn, args.visual_axis)
    write_fit_decoy(os.path.join(out, "fit_decoy_audio.csv"), fit_decoy_a, has_family=False)
    write_fit_decoy(os.path.join(out, "fit_decoy_visual.csv"), fit_decoy_v, has_family=True)
    n_low_lambda = sum(1 for r in fit_decoy_a if not math.isnan(r["lam"]) and r["lam"] < args.lambda_warn)
    print(f"  書き出し: fit_decoy_audio.csv(λ<{args.lambda_warn}の字: {n_low_lambda}/{len(fit_decoy_a)}), "
          f"fit_decoy_visual.csv")

    # 束ねた比較(清濁半濁・行・画数四分位)
    curve_bundle_a_path = os.path.join(out, "bundle_curves_audio.csv")
    fit_bundle_a_path = os.path.join(out, "bundle_fit_audio.csv")
    with io.open(curve_bundle_a_path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["dimension", "group", "family", "level_ms", "n_correct", "n_trials", "accuracy"])
    with io.open(fit_bundle_a_path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["dimension", "group", "family", "modality", "lambda", "mu", "sigma",
                                  "converged", "note", "n_trials", "n_chars"])
    chars_decoy_audio = sorted({r["target_char"] for r in decoy_audio})
    ink_q_audio = ink_quartile_labels(chars_decoy_audio)
    bundles_type = pool_and_fit(decoy_audio, "type", char_type_ext, "gate_ms", gamma_audio, args.fit_starts)
    bundles_gyou = pool_and_fit(decoy_audio, "gyou", lambda c: GYOU_MAP.get(c, ""), "gate_ms", gamma_audio, args.fit_starts)
    bundles_ink = pool_and_fit(decoy_audio, "ink_quartile", lambda c: ink_q_audio.get(c, ""), "gate_ms", gamma_audio, args.fit_starts)
    write_bundle(curve_bundle_a_path, fit_bundle_a_path, bundles_type, "type", "audio")
    write_bundle(curve_bundle_a_path, fit_bundle_a_path, bundles_gyou, "gyou", "audio")
    write_bundle(curve_bundle_a_path, fit_bundle_a_path, bundles_ink, "ink_quartile", "audio")

    curve_bundle_v_path = os.path.join(out, "bundle_curves_visual.csv")
    fit_bundle_v_path = os.path.join(out, "bundle_fit_visual.csv")
    with io.open(curve_bundle_v_path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["dimension", "group", "family", "level_pct", "n_correct", "n_trials", "accuracy"])
    with io.open(fit_bundle_v_path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["dimension", "group", "family", "modality", "lambda", "mu", "sigma",
                                  "converged", "note", "n_trials", "n_chars"])
    level_key_v = "actual_s_pct" if args.visual_axis == "actual" else "progress_pct"
    chars_decoy_visual = sorted({r["target_char"] for r in decoy_visual})
    ink_q_visual = ink_quartile_labels(chars_decoy_visual)
    bundles_type_v = pool_and_fit(decoy_visual, "type", char_type_ext, level_key_v, gamma_visual, args.fit_starts, family_split=True)
    bundles_gyou_v = pool_and_fit(decoy_visual, "gyou", lambda c: GYOU_MAP.get(c, ""), level_key_v, gamma_visual, args.fit_starts, family_split=True)
    bundles_ink_v = pool_and_fit(decoy_visual, "ink_quartile", lambda c: ink_q_visual.get(c, ""), level_key_v, gamma_visual, args.fit_starts, family_split=True)
    write_bundle(curve_bundle_v_path, fit_bundle_v_path, bundles_type_v, "type", "visual")
    write_bundle(curve_bundle_v_path, fit_bundle_v_path, bundles_gyou_v, "gyou", "visual")
    write_bundle(curve_bundle_v_path, fit_bundle_v_path, bundles_ink_v, "ink_quartile", "visual")
    print("  書き出し: bundle_curves_audio.csv, bundle_fit_audio.csv, bundle_curves_visual.csv, bundle_fit_visual.csv")

    write_family_stability(os.path.join(out, "family_stability_visual.csv"), fit_decoy_v)
    print("  書き出し: family_stability_visual.csv")

    # 本命8字とまぎれ字の比較には、既存curves_audio/visual(analysis/)ではなくここで作り直した
    # 本命側の集計を使う(af.write_curves_audio と同じロジックをこの場で複製するのではなく、
    # 既存出力ファイルをそのまま読み直すことで analyze_calib_full.py 側のロジック変更リスクをゼロにする)。
    curves_main_audio_path = os.path.join(os.path.dirname(args.inp), "analysis", "curves_audio.csv")
    curves_main_visual_path = os.path.join(os.path.dirname(args.inp), "analysis", "curves_visual.csv")
    if os.path.exists(curves_main_audio_path) and os.path.exists(curves_main_visual_path):
        with io.open(curves_main_audio_path, encoding="utf-8") as f:
            r = csv.reader(f); next(r)
            curves_main_audio_rows = list(r)
        with io.open(curves_main_visual_path, encoding="utf-8") as f:
            r = csv.reader(f); next(r)
            curves_main_visual_rows = list(r)
        compare_rows = write_compare_main_vs_decoy(
            os.path.join(out, "compare_main_vs_decoy.csv"), curves_main_audio_rows, fit_decoy_a,
            decoy_audio, curves_main_visual_rows, decoy_visual, args.visual_axis)
        print(f"  書き出し: compare_main_vs_decoy.csv({len(compare_rows)}行)")
    else:
        print("  ⚠ analysis/curves_audio.csv / curves_visual.csv が無いため compare_main_vs_decoy.csv はスキップ"
              "(先に analyze_calib_full.py を実行してください)")

    # ============ 依頼2: 参加者選別 ============
    pstats = af.build_participant_stats(base, main_all)
    pstats = extend_participant_stats(pstats, base, main_all, decoy_all, args)
    write_participant_stats_extended(os.path.join(out, "participant_stats_extended.csv"), pstats)
    sens_rows, cut_preds = write_sensitivity_participant(
        os.path.join(out, "sensitivity_participant.csv"), rows_audio_main, rows_visual_main,
        pstats, gamma_audio, gamma_visual, args.visual_axis, args.fit_starts, args)
    n_cuts = len({r["cut"] for r in sens_rows})
    print(f"  書き出し: participant_stats_extended.csv, sensitivity_participant.csv({n_cuts}種類の切り方)")

    # ============ 依頼3: 天井/床未達5字 ============
    lowceil_summary, isotonic_curves, t_max_obs_global = lowceil_diagnose_and_summarize(
        rows_audio_main, decoy_audio, gamma_audio, args.fit_starts, pstats, cut_preds, args)
    write_lowceiling_summary(os.path.join(out, "lowceiling_summary.csv"), lowceil_summary)
    write_isotonic_curve(os.path.join(out, "lowceiling_isotonic_curve.csv"), isotonic_curves)
    print(f"  書き出し: lowceiling_summary.csv({len(lowceil_summary)}行), lowceiling_isotonic_curve.csv "
          f"(観測最大打ち切り時間={t_max_obs_global:.0f}ms)")

    usability_rows = write_usability_table(os.path.join(out, "usability_table.csv"), lowceil_summary, args)
    print("  書き出し: usability_table.csv")
    for r in usability_rows:
        print(f"    {r['char']}: {r['problem_type']} / 逆引き={r['q_reversible']} / 判定={r['verdict']}")

    # ============ HTMLレポート ============
    ctx = dict(
        bundle_type_audio=bundles_type, fit_decoy_visual=fit_decoy_v,
        sensitivity_participant=sens_rows, rows_audio_main=rows_audio_main,
        lowceil_summary=lowceil_summary, t_max_obs_global=t_max_obs_global,
        gamma_audio=gamma_audio, isotonic_curves=isotonic_curves,
        usability_table=usability_rows,
    )
    build_report(args.report, ctx)
    print(f"  書き出し: {args.report}")

    print(f"\n完了: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
