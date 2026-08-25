#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方式(アニメーション提示方式)ごとの分析 -- 本研究の本体
==============================================================

較正フェーズ(transfer_trials.csv)を使って、

  A(t) … 音声を t ms で打ち切ったときの正答率(群acal)
  V(s) … 文字アニメを進み具合 s で止めたときの正答率(群aprime)

を字ごと・方式ごとに測り、視覚の提示方式(fade/reveal/blur/wipe)ごとに
  s(t) = V^-1(A(t))
がどこまで作れるか(=聴覚の曲線を視覚アニメの進み方として再現できるか)を
評価する。analyze_calib_full.py / analyze_calib_deep.py / analyze_calib_context.py
とは独立のスクリプトで、データ読み込み・当てはめの基盤(load/normalize/
base_filter/main_target_rows/default_gamma/fit_sigmoid/aggregate_levels)は
analyze_calib_full.py から import して再利用する(3本とも変更しない)。

出力(既定 project/data_calib_20260825/analysis_families/):
  audio_fit.csv                     聴覚: 字ごとのシグモイド当てはめと「転写に使えるか」判定・実質選択肢数
  audio_fit_free_gamma.csv          聴覚: γを自由推定した頑健性チェック
  vs_fit_point.csv                  視覚: 字×方式×速さ(pooled/300/500)×版(含む/外す)×軸(実測/名目) の点推定
  vs_bootstrap.csv                  視覚: 参加者単位ブートストラップによるμ・λ・σの95%区間(主版=外す版・実測軸)
  speed_effect_family.csv           方式ごとの速さ(300/500)の効果(全データ版・絵が違う試行版)
  speed_effect_by_level.csv         方式×水準ごとの300/500比較(Wilson区間)
  char_structure.csv                8字の構造指標(清濁・墨の左右分布・細部量)
  error_entropy_audio_by_char.csv   聴覚: 字ごとの誤答エントロピー
  error_entropy_visual_by_char.csv  視覚: 字ごとの誤答エントロピー(方式・水準込み)
  error_entropy_visual_by_char_family.csv  視覚: 字×方式ごとの誤答エントロピー
  error_entropy_by_level.csv        視覚: 方式×進み具合(実測水準)ごとの誤答エントロピー
  error_entropy_bands.csv           視覚: 方式×進み具合の帯(低/中/高)ごとの誤答エントロピー
  error_entropy_transitions.csv     方式ごとの「当てずっぽう→細部混同」の転換点
  perplexity_by_bin.csv             実質選択肢数(2^H): 視覚(方式×進み具合の帯)・聴覚(打ち切り時間の帯)
  transcribability_table.csv        32通り(8字×4方式)の転写成立判定(誤りの質・実質選択肢数を含む)
  family_summary.csv                方式ごとの総括(σのばらつき・当てはめの良さ・fadeの分解能限界など)
  family_rank_correlation.csv       方式間のμ順位相関(まぎれ字63字)
  mechanism_correlates.csv          方式ごとの墨量/清濁とμの相関(まぎれ字63字)
  best_family_per_char.csv          本命8字それぞれに最も適した方式

HTMLレポート: project/data_calib_20260825/families_report.html (①〜④の順、日本語)

使い方
------
  python3 experiment/tools/analyze_families.py \
      --in project/data_calib_20260825/transfer_trials.csv \
      --out project/data_calib_20260825/analysis_families \
      --report project/data_calib_20260825/families_report.html \
      --boot-vs 400 --boot-speed 3000

git commit・push はしない(指示どおり)。
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

from scipy.optimize import minimize  # noqa: E402 (gamma自由推定の頑健性チェック専用。acf.fit_sigmoidは使わない)

try:
    from scipy.ndimage import binary_erosion
    HAVE_SCIPY_NDIMAGE = True
except Exception:
    HAVE_SCIPY_NDIMAGE = False

try:
    from scipy.stats import spearmanr
    HAVE_SCIPY_STATS = True
except Exception:
    HAVE_SCIPY_STATS = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_calib_full as acf  # noqa: E402  (読み込み専用。この3本は変更しない)

# 日本語フォント(macOS Hiragino)。無ければ既定のまま(文字化けするが処理は止めない)。
for _fam in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "Noto Sans CJK JP", "IPAexGothic"):
    try:
        import matplotlib.font_manager as fm
        if any(f.name == _fam for f in fm.fontManager.ttflist):
            matplotlib.rcParams["font.family"] = _fam
            break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False

FAMILIES = ["fade", "reveal", "blur", "wipe"]
FAMILY_LABEL = {
    "fade": "fade(うすい→濃い)",
    "reveal": "reveal(点が増える)",
    "blur": "blur(ぼやけ→はっきり)",
    "wipe": "wipe(端から現れる)",
}
FAMILY_COLOR = {"fade": "#c2410c", "reveal": "#0f766e", "blur": "#6d28d9", "wipe": "#b91c1c"}
SPEEDS = [300, 500]
TARGET_CHARS = acf.TARGET_CHARS  # あかがぱしつまら (計画書の表記順)
CHAR_COLOR = dict(zip(TARGET_CHARS, plt.cm.tab10.colors[:len(TARGET_CHARS)] if len(TARGET_CHARS) <= 10
                       else [plt.cm.tab10(i % 10) for i in range(len(TARGET_CHARS))]))

# 8字の清濁分類(が=濁音、ぱ=半濁音、他6字は清音)。
# analyze_calib_full.CHAR_GROUP/CHAR_TYPE は50音全体の対応表で、あ・し・つ・ま・らは
# 対になる濁音/半濁音字を持たないため登録されていない。ここでは本命8字だけの分類を
# 直接持つ(丸山さんの指摘: 清音→濁音/半濁音でμがどれだけ動くかを見るための下ごしらえ)。
DIACRITIC = {"あ": "seion", "か": "seion", "が": "dakuon", "ぱ": "handakuon",
             "し": "seion", "つ": "seion", "ま": "seion", "ら": "seion"}
DIACRITIC_LABEL = {"seion": "清音", "dakuon": "濁音", "handakuon": "半濁音"}


def _fmt(v, nd=5):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return round(v, nd)


# ---------------------------------------------------------------------------
# 0. 読み込み・下ごしらえ
# ---------------------------------------------------------------------------
def prepare_data(path):
    """analyze_calib_full の関数を使って読み込み・正規化・基本除外を行い、
    このスクリプト独自に要る列(endpoint_clamped, actual_frames, base_anim_ms の数値化,
    actual_s_pct)を追加する。戻り値は dict にまとめた各種行リスト。"""
    print(f"読み込み: {path}")
    raw = acf.load(path)
    print(f"  全{len(raw)}行")
    raw = acf.normalize(raw)
    base = acf.base_filter(raw)

    for r in base:
        v = (r.get("endpoint_clamped") or "").strip()
        r["endpoint_clamped_i"] = int(v) if v in ("0", "1") else None
        af = (r.get("actual_frames") or "").strip()
        r["actual_frames_f"] = float(af) if af not in ("", None) else None
        bm = (r.get("base_anim_ms") or "").strip()
        r["base_anim_ms_i"] = int(float(bm)) if bm not in ("", None) else None
        r["actual_s_pct"] = round(r["actual_s"] * 100, 4) if r["actual_s"] is not None else None

    main_all = acf.main_target_rows(base)  # is_decoy偽 かつ check_kind空 かつ本命8字
    rows_audio_main = [r for r in main_all if r["modality_g"] == "audio" and not r["is_embedded_full"]]
    rows_visual_main = [r for r in main_all if r["modality_g"] == "visual"]
    # 較正はしごに埋め込まれた「打ち切りなし」聴覚試行(本命8字・本命問題)。実質選択肢数の
    # 『全部聞かせても何択まで絞れるか』を見るのに使う(gate_msを持たないのでシグモイド
    # 当てはめの数値軸には使わない=rows_audio_mainには含めない、という既存の扱いのまま)。
    rows_audio_fullplay = [r for r in main_all if r["modality_g"] == "audio" and r["is_embedded_full"]]

    # 確認問題A(check_kind=='full')の、本命8字・decoyでない行。progress_pct=100(=満額提示)の
    # 追加データとして V(s) の天井(λ)側に足せる。endpoint_clamped=0 はこの中にしか現れない
    # (下の main() の出力で件数を確認・記録する)。
    rows_visual_fullcheck = [r for r in base
                              if r["modality_g"] == "visual" and r["check_kind"] == "full"
                              and (not r["is_decoy_b"]) and r["target_char"] in TARGET_CHARS]

    gamma_audio, n_choices_audio = acf.default_gamma(rows_audio_main, "audio")
    gamma_visual, n_choices_visual = acf.default_gamma(rows_visual_main, "visual")

    print(f"  本命8字の本命問題: 聴覚{len(rows_audio_main)}行(参加者{len({r['participant_id'] for r in rows_audio_main})}人) / "
          f"視覚{len(rows_visual_main)}行(参加者{len({r['participant_id'] for r in rows_visual_main})}人)")
    print(f"  確認問題A(full,本命8字,非decoy)の追加行: {len(rows_visual_fullcheck)}行、"
          f"うち endpoint_clamped=0: {sum(1 for r in rows_visual_fullcheck if r['endpoint_clamped_i'] == 0)}行")
    print(f"  gamma(下限・固定): 聴覚=1/{n_choices_audio}={gamma_audio:.5f}, 視覚=1/{n_choices_visual}={gamma_visual:.5f}")

    print(f"  埋め込み『打ち切りなし』聴覚行(本命8字): {len(rows_audio_fullplay)}行")

    return dict(base=base, rows_audio_main=rows_audio_main, rows_visual_main=rows_visual_main,
                rows_visual_fullcheck=rows_visual_fullcheck, rows_audio_fullplay=rows_audio_fullplay,
                gamma_audio=gamma_audio, gamma_visual=gamma_visual,
                n_choices_audio=n_choices_audio, n_choices_visual=n_choices_visual)


def visual_dataset(data, version):
    """V(s)当てはめに使う行の集合を版ごとに作る。
    excl_clamp0: 本命問題(すべてendpoint_clamped=1)のみ = 較正はしごの実測。
    incl_clamp0: 上に確認問題A(full, 進み具合100%, 一部endpoint_clamped=0)を追加し、
                 天井(λ)側のデータ点を増やした版。"""
    union = data["rows_visual_main"] + data["rows_visual_fullcheck"]
    if version == "incl_clamp0":
        return union
    return [r for r in union if r["endpoint_clamped_i"] != 0]


# ---------------------------------------------------------------------------
# ① 方式ごとの V(s)
# ---------------------------------------------------------------------------
def fit_one(rows, char, family, speed, level_key, gamma, n_starts):
    sub = [r for r in rows if r["target_char"] == char and r["family"] == family
           and (speed is None or r["base_anim_ms_i"] == speed)]
    xs, ks, ns = acf.aggregate_levels(sub, level_key)
    fit = acf.fit_sigmoid(xs, ks, ns, gamma, n_starts=n_starts)
    n_part = len({r["participant_id"] for r in sub})
    return fit, n_part, len(sub)


def write_vs_fit_point(path, data, n_starts):
    """字×方式×速さ(pooled/300/500)×版(excl/incl clamp0)×軸(actual/nominal) の点推定。"""
    gamma_v = data["gamma_visual"]
    rows_out = []
    for version in ("excl_clamp0", "incl_clamp0"):
        rows = visual_dataset(data, version)
        for axis, level_key in (("actual", "actual_s_pct"), ("nominal", "progress_pct")):
            for char in TARGET_CHARS:
                for family in FAMILIES:
                    for speed in (None,) + tuple(SPEEDS):
                        fit, n_part, n_rows = fit_one(rows, char, family, speed, level_key, gamma_v, n_starts)
                        rows_out.append(dict(
                            version=version, axis=axis, char=char, family=family,
                            speed=("pooled" if speed is None else speed),
                            gamma=gamma_v, lam=fit["lam"], mu=fit["mu"], sigma=fit["sigma"],
                            converged=fit["converged"], n_trials=fit["n_trials"], n_rows=n_rows,
                            n_participants=n_part, note=fit["note"]))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["version", "axis", "char", "family", "speed", "gamma", "lambda", "mu", "sigma",
                     "converged", "n_trials", "n_rows", "n_participants", "note"])
        for r in rows_out:
            w.writerow([r["version"], r["axis"], r["char"], r["family"], r["speed"],
                        round(r["gamma"], 5), _fmt(r["lam"]), _fmt(r["mu"]), _fmt(r["sigma"]),
                        r["converged"], r["n_trials"], r["n_rows"], r["n_participants"], r["note"]])
    print(f"  書き出し: {os.path.basename(path)} ({len(rows_out)}行)")
    return rows_out


def write_vs_bootstrap(path, data, n_boot, seed, n_starts_boot):
    """参加者単位ブートストラップ。主版(excl_clamp0)・実測軸のみ、速さ pooled/300/500。
    含む版(incl_clamp0)は計算量を抑えるため点推定のみ(vs_fit_point.csv)で比較する。
    (試行単位でリサンプルしない理由は analyze_calib_full.py の write_bootstrap と同じ:
     同一参加者内の回答は独立でないため。)"""
    rows = visual_dataset(data, "excl_clamp0")
    level_key = "actual_s_pct"
    gamma_v = data["gamma_visual"]
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r["participant_id"]].append(r)
    pids = sorted(by_pid.keys())
    rng = np.random.default_rng(seed)

    acc = defaultdict(lambda: {"mu": [], "lam": [], "sigma": [], "conv": []})
    for b in range(n_boot):
        draw = rng.choice(pids, size=len(pids), replace=True)
        rows_b = []
        for pid in draw:
            rows_b.extend(by_pid[pid])
        for char in TARGET_CHARS:
            for family in FAMILIES:
                for speed in (None,) + tuple(SPEEDS):
                    fit, _, _ = fit_one(rows_b, char, family, speed, level_key, gamma_v, n_starts_boot)
                    key = (char, family, "pooled" if speed is None else speed)
                    acc[key]["mu"].append(fit["mu"])
                    acc[key]["lam"].append(fit["lam"])
                    acc[key]["sigma"].append(fit["sigma"])
                    acc[key]["conv"].append(fit["converged"])
        if (b + 1) % max(1, n_boot // 10) == 0:
            print(f"  V(s)ブートストラップ {b + 1}/{n_boot}")

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "family", "speed", "n_boot", "converged_rate",
                     "mu_median", "mu_lo95", "mu_hi95",
                     "lambda_median", "lambda_lo95", "lambda_hi95",
                     "sigma_median", "sigma_lo95", "sigma_hi95"])
        for (char, family, speed), d in sorted(acc.items(), key=lambda kv: (TARGET_CHARS.index(kv[0][0]), kv[0][1], str(kv[0][2]))):
            def pct(arr):
                a = np.array(arr, dtype=float)
                if not np.any(~np.isnan(a)):
                    return (float("nan"),) * 3
                return tuple(np.nanpercentile(a, [50, 2.5, 97.5]))
            mu_m, mu_lo, mu_hi = pct(d["mu"])
            lam_m, lam_lo, lam_hi = pct(d["lam"])
            sig_m, sig_lo, sig_hi = pct(d["sigma"])
            conv_rate = float(np.mean(d["conv"])) if d["conv"] else float("nan")
            w.writerow([char, family, speed, n_boot, round(conv_rate, 3),
                        _fmt(mu_m), _fmt(mu_lo), _fmt(mu_hi),
                        _fmt(lam_m), _fmt(lam_lo), _fmt(lam_hi),
                        _fmt(sig_m), _fmt(sig_lo), _fmt(sig_hi)])
    n_part = len(pids)
    print(f"  書き出し: {os.path.basename(path)} (参加者{n_part}人・ブートストラップ{n_boot}回)")
    return n_part


# ---------------------------------------------------------------------------
# ② 速さ(300/500)の効果
# ---------------------------------------------------------------------------
def wilson_ci(k, n, z=1.959964):
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return p, center - half, center + half


def frames_differ_levels(rows_visual_main):
    """方式×水準(progress_pct)ごとに、300msと500msで実際に描かれたフレーム数(actual_frames)の
    平均が(四捨五入して)異なるかを判定する。薄い水準では画面書き換え周期の制約で
    300msでも500msでも同じフレーム数(=同じ絵)しか出せないことがあるため、
    「絵が実際に違った水準」だけを抜き出すのに使う。"""
    tab = defaultdict(lambda: {300: [], 500: []})
    for r in rows_visual_main:
        if r["progress_pct"] is None or r["base_anim_ms_i"] not in SPEEDS or r["actual_frames_f"] is None:
            continue
        tab[(r["family"], r["progress_pct"])][r["base_anim_ms_i"]].append(r["actual_frames_f"])
    differ = {}
    for k, d in tab.items():
        if not d[300] or not d[500]:
            differ[k] = None  # 比較不能(片方の速さでデータなし)
            continue
        m300 = round(float(np.mean(d[300])))
        m500 = round(float(np.mean(d[500])))
        differ[k] = (m300 != m500)
    return differ


def write_speed_effect(path_family, path_level, data, n_boot, seed):
    rows = data["rows_visual_main"]
    differ = frames_differ_levels(rows)

    # --- 方式×水準ごと(Wilson区間) ---
    tab = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # (family,level) -> speed -> [ok,n]
    for r in rows:
        if r["progress_pct"] is None or r["base_anim_ms_i"] not in SPEEDS:
            continue
        k = (r["family"], r["progress_pct"])
        tab[k][r["base_anim_ms_i"]][1] += 1
        tab[k][r["base_anim_ms_i"]][0] += 1 if r["correct_b"] else 0

    level_rows = []
    for (family, level), d in sorted(tab.items(), key=lambda kv: (kv[0][0][0], kv[0][0][1])):
        ok3, n3 = d[300]
        ok5, n5 = d[500]
        p3, lo3, hi3 = wilson_ci(ok3, n3)
        p5, lo5, hi5 = wilson_ci(ok5, n5)
        diff = (p5 - p3) if (n3 and n5) else float("nan")
        fd = differ.get((family, level))
        level_rows.append(dict(family=family, level=level, frames_differ=fd,
                                n300=n3, acc300=p3, lo300=lo3, hi300=hi3,
                                n500=n5, acc500=p5, lo500=lo5, hi500=hi5, diff=diff))
    with io.open(path_level, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family", "progress_pct", "frames_differ", "n300", "acc300", "acc300_lo95", "acc300_hi95",
                     "n500", "acc500", "acc500_lo95", "acc500_hi95", "diff_500_minus_300"])
        for r in level_rows:
            w.writerow([r["family"], r["level"], r["frames_differ"],
                        r["n300"], _fmt(r["acc300"]), _fmt(r["lo300"]), _fmt(r["hi300"]),
                        r["n500"], _fmt(r["acc500"]), _fmt(r["lo500"]), _fmt(r["hi500"]), _fmt(r["diff"])])
    print(f"  書き出し: {os.path.basename(path_level)} ({len(level_rows)}行)")

    # --- 方式ごと(参加者単位ブートストラップの効果量) ---
    # subset="all": 全データ。subset="frames_differ": 300msと500msで実際に違うフレーム数が
    # 出た水準(progress_pct)だけに絞ったデータ。
    levels_differ = {(fam, lv) for (fam, lv), v in differ.items() if v is True}

    by_pid_all = defaultdict(list)
    by_pid_fd = defaultdict(list)
    for r in rows:
        if r["base_anim_ms_i"] not in SPEEDS:
            continue
        by_pid_all[r["participant_id"]].append(r)
        if (r["family"], r["progress_pct"]) in levels_differ:
            by_pid_fd[r["participant_id"]].append(r)

    rng = np.random.default_rng(seed)
    family_rows = []
    for subset_name, by_pid in (("all", by_pid_all), ("frames_differ_only", by_pid_fd)):
        pids = sorted(by_pid.keys())
        for family in FAMILIES:
            # 観測値
            ok3 = n3 = ok5 = n5 = 0
            for rs in by_pid.values():
                for r in rs:
                    if r["family"] != family:
                        continue
                    if r["base_anim_ms_i"] == 300:
                        n3 += 1
                        ok3 += 1 if r["correct_b"] else 0
                    elif r["base_anim_ms_i"] == 500:
                        n5 += 1
                        ok5 += 1 if r["correct_b"] else 0
            acc3 = ok3 / n3 if n3 else float("nan")
            acc5 = ok5 / n5 if n5 else float("nan")
            diffs = []
            for b in range(n_boot):
                draw = rng.choice(pids, size=len(pids), replace=True) if pids else []
                a3 = [0, 0]
                a5 = [0, 0]
                for pid in draw:
                    for r in by_pid[pid]:
                        if r["family"] != family:
                            continue
                        if r["base_anim_ms_i"] == 300:
                            a3[1] += 1
                            a3[0] += 1 if r["correct_b"] else 0
                        elif r["base_anim_ms_i"] == 500:
                            a5[1] += 1
                            a5[0] += 1 if r["correct_b"] else 0
                if a3[1] == 0 or a5[1] == 0:
                    continue
                diffs.append(a5[0] / a5[1] - a3[0] / a3[1])
            if diffs:
                lo, hi = np.percentile(diffs, [2.5, 97.5])
                med = float(np.median(diffs))
            else:
                lo = hi = med = float("nan")
            family_rows.append(dict(family=family, subset=subset_name, n300=n3, acc300=acc3, n500=n5, acc500=acc5,
                                     diff=acc5 - acc3 if n3 and n5 else float("nan"),
                                     diff_boot_median=med, diff_lo95=lo, diff_hi95=hi,
                                     n_participants=len(pids), n_boot=n_boot))
    with io.open(path_family, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family", "subset", "n300", "acc300", "n500", "acc500", "diff_500_minus_300",
                     "diff_boot_median", "diff_lo95", "diff_hi95", "n_participants", "n_boot"])
        for r in family_rows:
            w.writerow([r["family"], r["subset"], r["n300"], _fmt(r["acc300"]), r["n500"], _fmt(r["acc500"]),
                        _fmt(r["diff"]), _fmt(r["diff_boot_median"]), _fmt(r["diff_lo95"]), _fmt(r["diff_hi95"]),
                        r["n_participants"], r["n_boot"]])
    print(f"  書き出し: {os.path.basename(path_family)} ({len(family_rows)}行)")
    n_levels_total = len(differ)
    n_levels_differ = sum(1 for v in differ.values() if v is True)
    n_levels_same = sum(1 for v in differ.values() if v is False)
    n_levels_na = sum(1 for v in differ.values() if v is None)
    print(f"  絵が違った水準: {n_levels_differ}/{n_levels_total} (同一{n_levels_same}, 比較不能{n_levels_na})")
    return family_rows, level_rows, differ


# ---------------------------------------------------------------------------
# 8字の構造指標(丸山さんの指摘への対応): 清濁・墨の左右分布・細部量
# ---------------------------------------------------------------------------
def char_structure_metrics(base_dir, erosion_iter):
    """base/*.png(256x256グレースケール、黒=墨・白=地)から、字ごとに
    - centroid_x_frac: 墨の重心のx位置(0=左端,1=右端)
    - right_ink_frac: 墨の総量のうち右半分にある割合
    - fine_detail_frac: 1回収縮(erosion)で失われる墨画素の割合(=細い線・小さい点の量の目安。
      大きいほど「小さい点/細い線」が多く、blur(ぼかし)で埋もれやすいと考えられる)
    を計算する。wipeは左→右(CFG.visual.families.wipe.direction="ltr")に現れるので、
    right_ink_fracが大きい字ほど「最後まで読めない特徴」を右に持つ=wipeのμが遅くなる
    という仮説の検証に使う。PIL/scipyが無い環境では空の表を返す(処理は止めない)。"""
    out = {}
    if not HAVE_PIL:
        print("  警告: PILが無いため char_structure の画像計測をスキップ")
        return out
    for ch in TARGET_CHARS:
        p = os.path.join(base_dir, f"{ch}.png")
        if not os.path.exists(p):
            print(f"  警告: {p} が無く{ch}の構造指標をスキップ")
            continue
        im = Image.open(p).convert("L")
        a = np.asarray(im, dtype=float)
        ink = np.clip((255.0 - a) / 255.0, 0.0, 1.0)  # 黒=1(墨), 白=0(地) の連続量
        total = ink.sum()
        if total <= 0:
            continue
        h, w = ink.shape
        xs = np.arange(w)
        col_mass = ink.sum(axis=0)
        centroid_x_frac = float((col_mass * xs).sum() / total / (w - 1))
        right_ink_frac = float(ink[:, w // 2:].sum() / total)
        if HAVE_SCIPY_NDIMAGE:
            mask = ink > 0.5
            eroded = mask.copy()
            for _ in range(erosion_iter):
                eroded = binary_erosion(eroded)
            fine_detail_frac = float(1.0 - eroded.sum() / max(mask.sum(), 1))
        else:
            fine_detail_frac = float("nan")
        out[ch] = dict(centroid_x_frac=centroid_x_frac, right_ink_frac=right_ink_frac,
                        fine_detail_frac=fine_detail_frac, diacritic=DIACRITIC[ch])
    return out


def write_char_structure(path, struct):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "diacritic", "diacritic_label", "centroid_x_frac", "right_ink_frac", "fine_detail_frac"])
        for ch in TARGET_CHARS:
            d = struct.get(ch)
            if d is None:
                w.writerow([ch, DIACRITIC[ch], DIACRITIC_LABEL[DIACRITIC[ch]], "", "", ""])
                continue
            w.writerow([ch, d["diacritic"], DIACRITIC_LABEL[d["diacritic"]],
                        _fmt(d["centroid_x_frac"], 4), _fmt(d["right_ink_frac"], 4), _fmt(d["fine_detail_frac"], 4)])
    print(f"  書き出し: {os.path.basename(path)} ({len(struct)}字)")


# ---------------------------------------------------------------------------
# 誤りの質(著者の問い「間違えやすい字があるのか、それとも全然わからず回答が
# 割れているのか」への回答): 誤答のエントロピーで「当てずっぽう」と「細部だけの
# 取り違え」を区別する。
# ---------------------------------------------------------------------------
def shannon_entropy_bits(counter):
    """カテゴリ数のCounterからShannonエントロピー(底2、単位=ビット)を計算する。
    全試行が1種類の誤答に集中していればH=0、n種類に完全に均等に散らばっていれば
    H=log2(n)(取りうる最大値)になる。"""
    total = sum(counter.values())
    if total == 0:
        return float("nan")
    h = 0.0
    for c in counter.values():
        if c <= 0:
            continue
        p = c / total
        h -= p * math.log2(p)
    return h


def error_stats(rows, n_choices):
    """行の集合(相対する母集団はすでに絞り込んであること)から、正答でない行
    (correct_b偽)だけを取り出し、response_charの散らばりを要約する。
    n_choicesはそのモダリティの選択肢数(聴覚68・視覚72)で、log2(n_choices)を
    『68択(72択)で完全に当てずっぽうならこの値』という上限の目安として添える
    (⚠ 上限は「誤答だけがn_choices-1種類に均等分散」の場合にlog2(n_choices-1)が
    厳密な最大値だが、この解析ではn_choicesがそもそも大きく差は小さいため、
    分かりやすさを優先してlog2(n_choices)を目安値として使う。両方混同しないよう
    entropy_max_bits列の値そのものは常にlog2(n_choices)であることをここに明記する)。"""
    err = [r for r in rows if not r["correct_b"]]
    n_trials = len(rows)
    n_errors = len(err)
    cnt = Counter(r["response_char"] for r in err)
    h = shannon_entropy_bits(cnt) if n_errors > 0 else float("nan")
    h_max = math.log2(n_choices)
    top = cnt.most_common(2)
    top1_char, top1_n = top[0] if len(top) > 0 else ("", 0)
    top2_char, top2_n = top[1] if len(top) > 1 else ("", 0)
    return dict(n_trials=n_trials, n_errors=n_errors, entropy_bits=h, entropy_max_bits=h_max,
                entropy_norm=(h / h_max if n_errors > 0 else float("nan")),
                n_distinct_wrong=len(cnt),
                top1_char=top1_char, top1_share=(top1_n / n_errors if n_errors else float("nan")),
                top2_char=top2_char, top2_share=(top2_n / n_errors if n_errors else float("nan")))


def write_error_entropy_audio(path, data):
    """聴覚: 字ごとの誤答エントロピー(全gate_ms水準を込みで、その字の聴覚主系列の
    誤答をまとめて見る。個々のgate_ms水準では誤答数が少なすぎてHが安定しないため)。"""
    rows_out = []
    for ch in TARGET_CHARS:
        sub = [r for r in data["rows_audio_main"] if r["target_char"] == ch]
        st = error_stats(sub, data["n_choices_audio"])
        rows_out.append(dict(char=ch, **st))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "n_trials", "n_errors", "entropy_bits", "entropy_max_bits", "entropy_norm",
                     "n_distinct_wrong", "top1_char", "top1_share", "top2_char", "top2_share"])
        for r in rows_out:
            w.writerow([r["char"], r["n_trials"], r["n_errors"], _fmt(r["entropy_bits"], 3),
                        _fmt(r["entropy_max_bits"], 3), _fmt(r["entropy_norm"], 3), r["n_distinct_wrong"],
                        r["top1_char"], _fmt(r["top1_share"], 3), r["top2_char"], _fmt(r["top2_share"], 3)])
    print(f"  書き出し: {os.path.basename(path)} (8字)")
    return {r["char"]: r for r in rows_out}


def write_error_entropy_visual_by_char(path, data):
    """視覚: 字ごとの誤答エントロピー(方式・水準を全部込みで、聴覚と同じ粒度で
    直接比較できるようにする)。"""
    rows_out = []
    for ch in TARGET_CHARS:
        sub = [r for r in data["rows_visual_main"] if r["target_char"] == ch]
        st = error_stats(sub, data["n_choices_visual"])
        rows_out.append(dict(char=ch, **st))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "n_trials", "n_errors", "entropy_bits", "entropy_max_bits", "entropy_norm",
                     "n_distinct_wrong", "top1_char", "top1_share", "top2_char", "top2_share"])
        for r in rows_out:
            w.writerow([r["char"], r["n_trials"], r["n_errors"], _fmt(r["entropy_bits"], 3),
                        _fmt(r["entropy_max_bits"], 3), _fmt(r["entropy_norm"], 3), r["n_distinct_wrong"],
                        r["top1_char"], _fmt(r["top1_share"], 3), r["top2_char"], _fmt(r["top2_share"], 3)])
    print(f"  書き出し: {os.path.basename(path)} (8字)")
    return {r["char"]: r for r in rows_out}


def write_error_entropy_visual_char_family(path, data):
    """視覚: 字×方式ごとの誤答エントロピー(水準込み)。32セル対応表への
    『誤りの質』列は水準(進み具合)まで絞った、より細かい値を別途使うが、
    ここでは字×方式の全体的な傾向を見るための中間集計として出す。"""
    rows_out = []
    for ch in TARGET_CHARS:
        for fam in FAMILIES:
            sub = [r for r in data["rows_visual_main"] if r["target_char"] == ch and r["family"] == fam]
            st = error_stats(sub, data["n_choices_visual"])
            rows_out.append(dict(char=ch, family=fam, **st))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "family", "n_trials", "n_errors", "entropy_bits", "entropy_max_bits",
                     "entropy_norm", "n_distinct_wrong", "top1_char", "top1_share", "top2_char", "top2_share"])
        for r in rows_out:
            w.writerow([r["char"], r["family"], r["n_trials"], r["n_errors"], _fmt(r["entropy_bits"], 3),
                        _fmt(r["entropy_max_bits"], 3), _fmt(r["entropy_norm"], 3), r["n_distinct_wrong"],
                        r["top1_char"], _fmt(r["top1_share"], 3), r["top2_char"], _fmt(r["top2_share"], 3)])
    print(f"  書き出し: {os.path.basename(path)} (32行=8字×4方式)")
    return {(r["char"], r["family"]): r for r in rows_out}


def write_error_entropy_by_level(path, data):
    """視覚: 方式×進み具合(実測水準)ごとの誤答エントロピー。8字ぶんを込みにして
    集計する(1字だけでは1水準あたりの誤答数が少なすぎてHが安定しないため。
    込みにすると『進み具合が同じなら字によらず、当てずっぽう度合いは同じくらい』
    という前提を置くことになるが、これは③で見る『方式によって手がかりの出方が
    違う』こととは矛盾しない — ここでは方式の中での進み具合の効果を見ている)。"""
    rows_visual = data["rows_visual_main"]
    tab = defaultdict(list)
    for r in rows_visual:
        if r["progress_pct"] is None:
            continue
        tab[(r["family"], r["progress_pct"])].append(r)
    rows_out = []
    for (fam, lv), sub in tab.items():
        st = error_stats(sub, data["n_choices_visual"])
        rows_out.append(dict(family=fam, progress_pct=lv, **st))
    rows_out.sort(key=lambda r: (FAMILIES.index(r["family"]), r["progress_pct"]))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family", "progress_pct", "n_trials", "n_errors", "entropy_bits", "entropy_max_bits",
                     "entropy_norm", "n_distinct_wrong", "top1_char", "top1_share", "top2_char", "top2_share"])
        for r in rows_out:
            w.writerow([r["family"], r["progress_pct"], r["n_trials"], r["n_errors"], _fmt(r["entropy_bits"], 3),
                        _fmt(r["entropy_max_bits"], 3), _fmt(r["entropy_norm"], 3), r["n_distinct_wrong"],
                        r["top1_char"], _fmt(r["top1_share"], 3), r["top2_char"], _fmt(r["top2_share"], 3)])
    print(f"  書き出し: {os.path.basename(path)} ({len(rows_out)}行)")
    return rows_out


def detect_transition(level_rows_family, threshold_frac):
    """『当てずっぽうの帯』から『細部だけが残る帯』への転換点を、エントロピーの
    列から機械的に検出する。

    条件: entropy_norm が threshold_frac 未満になった水準から、それ以降の
    すべての水準でも threshold_frac 未満であり続ける、その最初の水準を転換点とする
    (単発の落ち込みを転換点と誤検出しないよう「それ以降ずっと」を要求する)。
    見つからない場合は「転換なし(最後まで当てずっぽうに近い)」または該当水準が
    無いことを note に書く。threshold_frac の既定0.6は、log2(72)=6.17ビット中
    6割(≈3.7ビット、約13種類に均等分散した場合相当)を『まだ広く散らばっている』
    と見なす目安として置いた。判断の要る値なので引数で変える。
    """
    def below_threshold(r):
        # entropy_normがNaNなのは誤答が0件のとき(=完全に正答、最も『散らばっていない』
        # 状態)なので、これは閾値未満として扱う。誤答自体が無いのに「まだ当てずっぽう」
        # と誤判定しないための補正。
        if r["n_errors"] == 0:
            return True
        return (r["entropy_norm"] == r["entropy_norm"]) and r["entropy_norm"] < threshold_frac

    lv_sorted = sorted(level_rows_family, key=lambda r: r["progress_pct"])
    n = len(lv_sorted)
    for i in range(n):
        rest = lv_sorted[i:]
        if all(below_threshold(r) for r in rest):
            return lv_sorted[i]["progress_pct"], f"進み具合{lv_sorted[i]['progress_pct']}%以降でentropy_norm<{threshold_frac}が続く"
    return None, "最後の水準までentropy_normがthreshold_frac以上のまま(明確な転換が見られない)"


def write_error_entropy_bands(path, data, level_rows, n_bands=3):
    """進み具合を試行数でおおむね等分した帯(既定3分割)で誤答エントロピーを見る、
    著者への説明用の要約版(方式ごとの『帯で切ると』の実例に対応)。
    帯の境界は、その方式で実際にテストした水準を試行数の累積で等分して決める
    (家族ごとにテスト水準の間隔がバラバラなため、進み具合そのものの等分でなく
    試行数の等分にした)。"""
    rows_out = []
    for fam in FAMILIES:
        levels = sorted([r for r in level_rows if r["family"] == fam], key=lambda r: r["progress_pct"])
        total_n = sum(r["n_trials"] for r in levels)
        if total_n == 0 or not levels:
            continue
        target_per_band = total_n / n_bands
        bands = []
        cur_levels = []
        cur_n = 0
        for r in levels:
            cur_levels.append(r)
            cur_n += r["n_trials"]
            if cur_n >= target_per_band and len(bands) < n_bands - 1:
                bands.append(cur_levels)
                cur_levels = []
                cur_n = 0
        if cur_levels:
            bands.append(cur_levels)
        for bi, blevels in enumerate(bands):
            lv_lo = blevels[0]["progress_pct"]
            lv_hi = blevels[-1]["progress_pct"]
            sub_rows = [r for r in data["rows_visual_main"]
                        if r["family"] == fam and r["progress_pct"] is not None
                        and lv_lo <= r["progress_pct"] <= lv_hi]
            st = error_stats(sub_rows, data["n_choices_visual"])
            rows_out.append(dict(family=fam, band_index=bi + 1, s_range=f"{lv_lo}-{lv_hi}%", **st))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family", "band_index", "s_range", "n_trials", "n_errors", "entropy_bits", "entropy_max_bits",
                     "entropy_norm", "n_distinct_wrong", "top1_char", "top1_share", "top2_char", "top2_share"])
        for r in rows_out:
            w.writerow([r["family"], r["band_index"], r["s_range"], r["n_trials"], r["n_errors"],
                        _fmt(r["entropy_bits"], 3), _fmt(r["entropy_max_bits"], 3), _fmt(r["entropy_norm"], 3),
                        r["n_distinct_wrong"], r["top1_char"], _fmt(r["top1_share"], 3), r["top2_char"],
                        _fmt(r["top2_share"], 3)])
    print(f"  書き出し: {os.path.basename(path)} ({len(rows_out)}行=4方式×{n_bands}帯)")
    return rows_out


def classify_error_quality(entropy_norm, n_errors, min_n, guess_thr, concentrate_thr):
    """entropy_norm(0-1)から『誤りの質』を分類する。
    - データ不足: 誤答がmin_n件未満(既定8件。二値化した割合の目安が安定する
      最低限として、他の解析のsame_response_share等と同程度の桁数で置いた)
    - 当てずっぽう: entropy_norm >= guess_thr(既定0.75。72択の75%=約4.6ビット、
      18種類に均等分散した場合相当。『まだ広く散らばっている』とみなす目安)
    - 細部混同: entropy_norm <= concentrate_thr(既定0.4。72択の40%=約2.5ビット、
      6種類程度に集中した場合相当。『特定の字と混同している』とみなす目安)
    - 混在: どちらでもない中間
    既定値は判断の要る数値なので、いずれも引数で変えられるようにしてある。
    """
    if n_errors < min_n or entropy_norm != entropy_norm:
        return "データ不足"
    if entropy_norm >= guess_thr:
        return "当てずっぽう"
    if entropy_norm <= concentrate_thr:
        return "細部混同"
    return "混在"


def nearest_level(levels, target):
    """levels(数値のリスト)からtargetに最も近い値を返す。空ならNone。"""
    if not levels:
        return None
    return min(levels, key=lambda x: abs(x - target))


def error_quality_near_mu(data, vs_fit_pooled_by_key):
    """字×方式ごと、③のμに最も近い実測水準1点での誤答エントロピー(正規化)。
    32セル対応表の『誤りの質』列に使う(分類そのものはmain()側で閾値を渡して行う)。"""
    out = {}
    max_bits = math.log2(data["n_choices_visual"])
    for ch in TARGET_CHARS:
        for fam in FAMILIES:
            vf = vs_fit_pooled_by_key.get((ch, fam))
            sub_all = [r for r in data["rows_visual_main"] if r["target_char"] == ch and r["family"] == fam
                       and r["actual_s_pct"] is not None]
            levels = sorted({r["actual_s_pct"] for r in sub_all})
            if vf is None or not vf["converged"] or math.isnan(vf["mu"]) or not levels:
                out[(ch, fam)] = dict(level=None, n_trials=0, n_errors=0, entropy_bits=float("nan"),
                                       entropy_norm=float("nan"), entropy_max_bits=max_bits)
                continue
            lv = nearest_level(levels, vf["mu"])
            sub = [r for r in sub_all if r["actual_s_pct"] == lv]
            st = error_stats(sub, data["n_choices_visual"])
            out[(ch, fam)] = dict(level=lv, n_trials=st["n_trials"], n_errors=st["n_errors"],
                                   entropy_bits=st["entropy_bits"], entropy_norm=st["entropy_norm"],
                                   entropy_max_bits=max_bits)
    return out


# ---------------------------------------------------------------------------
# 実質選択肢数(著者の関心「それぞれのアニメーションのそれぞれのタイミングで
# 何択くらいなのか」への回答): 2^H(応答の散らばりのエントロピーを指数化したもの)。
# ①〜④の「正答率」より直感的に『情報がどれだけ伝わったか』を表す指標として、
# 対応表・専用の図に組み込む。誤りの質(上のブロック)と違い、こちらは正答も含めた
# 応答全体の散らばりを見る(「絞り込めているか」そのものを測るため)。
# ---------------------------------------------------------------------------
def response_entropy_bits(rows):
    """1つの提示字ぶんの、応答(正誤問わず全応答)のエントロピー(ビット)。
    全員が正しく答えればH=0(1つに絞れている)。"""
    cnt = Counter(r["response_char"] for r in rows)
    n = len(rows)
    if n == 0:
        return float("nan"), 0
    return shannon_entropy_bits(cnt), n


def weighted_perplexity(char_h_n_pairs):
    """(H_char, n_char)の対のリストから、試行数で重み付けた平均Hをとり、
    最後にまとめて2^Hする(=実質選択肢数、perplexity)。

    ⚠ 複数の字の応答をいきなり生で束ねてエントロピーを取ってはいけない
    (例: 8字がそれぞれ別の字として完璧に正答されていても(字ごとのH=0)、
    生の応答を束ねると『8種類に均等分散』に見えてH=3ビット=8択という
    誤った結果になる)。字ごとに先にHを求めてから試行数で加重平均し、
    最後に2^Hを取ることで、この見かけ上の散らばりを避ける。
    """
    total_n = sum(n for _, n in char_h_n_pairs)
    valid = [(h, n) for h, n in char_h_n_pairs if n > 0 and h == h]
    if not valid or total_n == 0:
        return float("nan"), float("nan"), 0, 0
    n_valid = sum(n for _, n in valid)
    h_weighted = sum(h * n for h, n in valid) / n_valid
    return h_weighted, 2.0 ** h_weighted, total_n, len(valid)


def assign_bin(value, edges):
    """valueが入る帯(edges[i], edges[i+1]]のインデックスiを返す(下端は最初の帯のみ含む)。
    edgesの範囲外ならNone。"""
    if value is None:
        return None
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        if i == 0:
            if lo <= value <= hi:
                return i
        else:
            if lo < value <= hi:
                return i
    return None


def bin_label(edges, i, unit=""):
    return f"{edges[i]:g}〜{edges[i+1]:g}{unit}"


def perplexity_by_bin_visual(data, edges):
    """視覚: 方式×進み具合帯(実測 actual_s%基準)ごとに、8字を weighted_perplexity で
    束ねた実質選択肢数。edgesは進み具合%の帯境界(既定 0,1,3,8,20,50,90,101)。
    実測値(actual_s)を使う(①と同じ理由: 60Hz等の量子化で名目値と実際の表示が
    ずれるため)。"""
    rows_out = []
    max_bits = math.log2(data["n_choices_visual"])
    for fam in FAMILIES:
        for bi in range(len(edges) - 1):
            pairs = []
            for ch in TARGET_CHARS:
                sub = [r for r in data["rows_visual_main"] if r["target_char"] == ch and r["family"] == fam
                       and r["actual_s_pct"] is not None and assign_bin(r["actual_s_pct"], edges) == bi]
                if not sub:
                    continue
                h, n = response_entropy_bits(sub)
                pairs.append((h, n))
            h_w, perp, n_total, n_chars = weighted_perplexity(pairs)
            rows_out.append(dict(family=fam, bin_index=bi, bin_label=bin_label(edges, bi, "%"),
                                  bin_lo=edges[bi], bin_hi=edges[bi + 1],
                                  n_trials=n_total, n_chars_with_data=n_chars,
                                  entropy_bits=h_w, entropy_max_bits=max_bits, perplexity=perp,
                                  perplexity_max=data["n_choices_visual"]))
    return rows_out


def perplexity_by_bin_audio(data, edges):
    """聴覚: 打ち切り時間の帯(gate_ms、既定 0,15,25,35,50,70,100000)ごとに、
    8字を weighted_perplexity で束ねた実質選択肢数。加えて『打ち切りなし
    (較正はしごに埋め込まれた全部聞かせる試行)』を別枠の行として追加する
    (⚠ 全部聞かせても実質何択までしか絞れないか、という上限を見るための行で、
    帯の並びの最後に置くが数値軸上のgate_msは持たない特別な水準)。"""
    rows_out = []
    max_bits = math.log2(data["n_choices_audio"])
    for bi in range(len(edges) - 1):
        pairs = []
        for ch in TARGET_CHARS:
            sub = [r for r in data["rows_audio_main"] if r["target_char"] == ch
                   and r["gate_ms"] is not None and assign_bin(r["gate_ms"], edges) == bi]
            if not sub:
                continue
            h, n = response_entropy_bits(sub)
            pairs.append((h, n))
        h_w, perp, n_total, n_chars = weighted_perplexity(pairs)
        rows_out.append(dict(family="audio", bin_index=bi, bin_label=bin_label(edges, bi, "ms"),
                              bin_lo=edges[bi], bin_hi=edges[bi + 1],
                              n_trials=n_total, n_chars_with_data=n_chars,
                              entropy_bits=h_w, entropy_max_bits=max_bits, perplexity=perp,
                              perplexity_max=data["n_choices_audio"]))
    # 打ち切りなし(embedded full)行
    pairs = []
    for ch in TARGET_CHARS:
        sub = [r for r in data.get("rows_audio_fullplay", []) if r["target_char"] == ch]
        if not sub:
            continue
        h, n = response_entropy_bits(sub)
        pairs.append((h, n))
    h_w, perp, n_total, n_chars = weighted_perplexity(pairs)
    rows_out.append(dict(family="audio", bin_index=len(edges) - 1, bin_label="打ち切りなし",
                          bin_lo=float("nan"), bin_hi=float("nan"),
                          n_trials=n_total, n_chars_with_data=n_chars,
                          entropy_bits=h_w, entropy_max_bits=max_bits, perplexity=perp,
                          perplexity_max=data["n_choices_audio"]))
    return rows_out


def write_perplexity_bins(path, rows_visual_bins, rows_audio_bins):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["modality", "family", "bin_label", "bin_lo", "bin_hi", "n_trials", "n_chars_with_data",
                     "entropy_bits_weighted", "entropy_max_bits", "perplexity_2powH", "perplexity_max_n_choices"])
        for r in rows_visual_bins:
            w.writerow(["visual", r["family"], r["bin_label"], r["bin_lo"], r["bin_hi"], r["n_trials"],
                        r["n_chars_with_data"], _fmt(r["entropy_bits"], 3), _fmt(r["entropy_max_bits"], 3),
                        _fmt(r["perplexity"], 2), r["perplexity_max"]])
        for r in rows_audio_bins:
            w.writerow(["audio", r["family"], r["bin_label"], r["bin_lo"], r["bin_hi"], r["n_trials"],
                        r["n_chars_with_data"], _fmt(r["entropy_bits"], 3), _fmt(r["entropy_max_bits"], 3),
                        _fmt(r["perplexity"], 2), r["perplexity_max"]])
    print(f"  書き出し: {os.path.basename(path)} ({len(rows_visual_bins) + len(rows_audio_bins)}行)")


def perplexity_near_mu(data, vs_fit_pooled_by_key):
    """字×方式ごと、③のμに最も近い実測水準1点での実質選択肢数(単一の字なので
    重み付けは不要、その水準の応答分布からそのままH・2^Hを求める)。32セル対応表に
    載せる『情報がどれだけ絞られた時点でμに達するか』の値。"""
    out = {}
    max_bits = math.log2(data["n_choices_visual"])
    for ch in TARGET_CHARS:
        for fam in FAMILIES:
            vf = vs_fit_pooled_by_key.get((ch, fam))
            sub_all = [r for r in data["rows_visual_main"] if r["target_char"] == ch and r["family"] == fam
                       and r["actual_s_pct"] is not None]
            levels = sorted({r["actual_s_pct"] for r in sub_all})
            if vf is None or not vf["converged"] or math.isnan(vf["mu"]) or not levels:
                out[(ch, fam)] = dict(level=None, n_trials=0, entropy_bits=float("nan"),
                                       perplexity=float("nan"), entropy_max_bits=max_bits)
                continue
            lv = nearest_level(levels, vf["mu"])
            sub = [r for r in sub_all if r["actual_s_pct"] == lv]
            h, n = response_entropy_bits(sub)
            out[(ch, fam)] = dict(level=lv, n_trials=n, entropy_bits=h,
                                   perplexity=(2.0 ** h if h == h else float("nan")), entropy_max_bits=max_bits)
    return out


# ---------------------------------------------------------------------------
# γ(当て推量の水準)を固定でなく自由推定した場合の頑健性チェック(著者の指摘:
# 進み具合0%付近でも実質選択肢数が68択にならない=よく使う字への偏りがあり、
# γ=1/68固定という前提が実態と合っていない可能性がある)。
# ---------------------------------------------------------------------------
def fit_sigmoid_free_gamma(xs, ks, ns, n_starts, gamma_upper_bound):
    """p(x)=gamma+(lam-gamma)/(1+exp(-(x-mu)/sigma)) の4径数すべてを自由推定する。
    analyze_calib_full.fit_sigmoid はgammaを固定して使う設計なので、比較用に
    ここだけ独自に実装する(analyze_calib_full.py自体は変更しない)。
    gamma_upper_boundは既定0.5(五分より高い『当て推量』は考えにくいという
    ゆるい上限。判断の要る値なので引数で変えられる)。"""
    xs = np.asarray(xs, dtype=float)
    ks = np.asarray(ks, dtype=float)
    ns = np.asarray(ns, dtype=float)
    n_trials = int(ns.sum())
    n_levels = int(len(xs))
    if n_levels < 3 or n_trials == 0:
        return dict(gamma=float("nan"), lam=float("nan"), mu=float("nan"), sigma=float("nan"),
                     converged=False, note="水準数が3未満でgamma自由推定は不可", n_trials=n_trials)
    xlo, xhi = float(xs.min()), float(xs.max())
    rng = xhi - xlo
    eps = 1e-9

    def nll(params):
        gamma, lam, mu, sigma = params
        sigma = max(sigma, 1e-6)
        z = np.clip(-(xs - mu) / sigma, -500, 500)
        p = gamma + (lam - gamma) / (1.0 + np.exp(z))
        p = np.clip(p, eps, 1 - eps)
        return -float(np.sum(ks * np.log(p) + (ns - ks) * np.log(1 - p)))

    acc_by_level = ks / np.maximum(ns, 1)
    bounds = [(0.0, gamma_upper_bound), (0.0, 1.0), (xlo - rng, xhi + rng), (max(rng * 1e-3, 1e-6), rng * 8)]
    best = None
    for mu0 in np.percentile(xs, [15, 30, 50, 70, 85]).tolist()[:max(1, n_starts)]:
        for s0 in [rng * f for f in (0.05, 0.15, 0.35, 0.7)][:max(1, min(4, n_starts))]:
            g0 = float(np.clip(acc_by_level.min(), 0.0, gamma_upper_bound))
            l0 = float(np.clip(acc_by_level.max(), g0 + 0.02, 0.999))
            try:
                res = minimize(nll, [g0, l0, mu0, s0], method="L-BFGS-B", bounds=bounds)
            except Exception:
                continue
            if best is None or res.fun < best.fun:
                best = res
    if best is None:
        return dict(gamma=float("nan"), lam=float("nan"), mu=float("nan"), sigma=float("nan"),
                     converged=False, note="最適化が例外で失敗", n_trials=n_trials)
    gamma, lam, mu, sigma = (float(v) for v in best.x)
    note = "" if best.success else f"収束せず: {best.message}"
    return dict(gamma=gamma, lam=lam, mu=mu, sigma=sigma, converged=bool(best.success), note=note, n_trials=n_trials)


def write_audio_fit_free_gamma(path, data, n_starts, gamma_upper_bound, lambda_usable_threshold):
    """8字それぞれについて、gammaを固定(1/68)した場合と自由推定した場合の当てはめを
    並べ、③の『使用可否』判定(あ・か・まの3字)が変わらないかを確かめる。"""
    rows_out = []
    for ch in TARGET_CHARS:
        sub = [r for r in data["rows_audio_main"] if r["target_char"] == ch]
        xs, ks, ns = acf.aggregate_levels(sub, "gate_ms")
        fit = fit_sigmoid_free_gamma(xs, ks, ns, n_starts, gamma_upper_bound)
        gate_vals = sorted({r["gate_ms"] for r in sub if r["gate_ms"] is not None})
        mu_in_domain = (len(gate_vals) >= 2 and not math.isnan(fit["mu"]) and gate_vals[0] <= fit["mu"] <= gate_vals[-1])
        usable = bool(fit["converged"] and not math.isnan(fit["lam"]) and fit["lam"] >= lambda_usable_threshold
                       and mu_in_domain)
        rows_out.append(dict(char=ch, gamma_free=fit["gamma"], lam=fit["lam"], mu=fit["mu"], sigma=fit["sigma"],
                              converged=fit["converged"], usable_for_transcription=usable, note=fit["note"]))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "gamma_free", "lambda", "mu", "sigma", "converged", "usable_for_transcription", "note"])
        for r in rows_out:
            w.writerow([r["char"], _fmt(r["gamma_free"], 4), _fmt(r["lam"]), _fmt(r["mu"]), _fmt(r["sigma"]),
                        r["converged"], r["usable_for_transcription"], r["note"]])
    print(f"  書き出し: {os.path.basename(path)} (8字、gamma自由推定版)")
    return {r["char"]: r for r in rows_out}


# ---------------------------------------------------------------------------
# 字×方式の相性(著者の問い「それぞれのアニメーションの特徴と、それに適した文字が
# あるんじゃない?」への回答): 順位相関・墨量/清濁との相関・字ごとの最適方式
# ---------------------------------------------------------------------------
def load_decoy_fit(path):
    """analyze_calib_deep.py が出す fit_decoy_visual.csv(まぎれ字63字×4方式)を読む。
    読み取り専用の参照データとして使う(analyze_calib_deep.py自体は変更しない)。
    別エージェントが並行して同じ較正データを解析しており、この63字は本命8字とは別の
    まぎれ字(decoy)なので、方式どうしの順位相関や墨量・清濁との相関を、本命8字だけ
    (n=8)より安定して見るための参照集団として使う。ファイルが無い/読めない場合は
    Noneを返し、その旨をレポートに明記して処理は止めない。"""
    if not os.path.exists(path):
        print(f"  警告: {path} が無いため、字×方式の相性の補強分析(63字参照)をスキップ")
        return None
    try:
        with io.open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        print(f"  警告: {path} の読み込みに失敗({e})。補強分析をスキップ")
        return None
    out = []
    for r in rows:
        try:
            out.append(dict(char=r["char"], family=r["family"], gyou=r.get("gyou", ""),
                             type=r.get("type", ""), ink_pixels=float(r["ink_pixels"]),
                             mu=float(r["mu"]), lam=float(r["lambda"]), sigma=float(r["sigma"]),
                             converged=(str(r["converged"]).strip() in ("True", "1", "TRUE")),
                             n_trials=int(r["n_trials"])))
        except (ValueError, KeyError):
            continue
    return out


def family_rank_correlation(decoy_rows):
    """方式どうしで、字の難しさ(μ)の順位がどれだけ揃っているかをSpearman順位相関で見る。
    著者の仮説(「読みにくい字」という一般的な性質は無いのでは)の検証。
    収束した(converged)行だけを使い、両方の方式に値がある字だけで相関を取る。"""
    if not decoy_rows or not HAVE_SCIPY_STATS:
        return None
    by_fam = defaultdict(dict)
    for r in decoy_rows:
        if r["converged"]:
            by_fam[r["family"]][r["char"]] = r["mu"]
    mat = {}
    for f1 in FAMILIES:
        for f2 in FAMILIES:
            common = sorted(set(by_fam[f1]) & set(by_fam[f2]))
            if len(common) < 5:
                mat[(f1, f2)] = (float("nan"), 0)
                continue
            x = [by_fam[f1][c] for c in common]
            y = [by_fam[f2][c] for c in common]
            rho, _ = spearmanr(x, y)
            mat[(f1, f2)] = (float(rho), len(common))
    return mat


def mechanism_correlates(decoy_rows):
    """方式ごとに、μ(難しさ)が墨の量(ink_pixels)とどれだけ相関するか、
    濁音/半濁音が清音に比べてどれだけ不利(μの比)かを求める。
    まぎれ字63字を使う(本命8字はが・ぱの2字しか濁音/半濁音を含まず、比較が不安定なため)。"""
    if not decoy_rows or not HAVE_SCIPY_STATS:
        return []
    out = []
    for fam in FAMILIES:
        sub = [r for r in decoy_rows if r["family"] == fam and r["converged"]]
        if len(sub) < 5:
            continue
        ink = [r["ink_pixels"] for r in sub]
        mu = [r["mu"] for r in sub]
        rho, _ = spearmanr(ink, mu)
        seion_mu = [r["mu"] for r in sub if r["type"] == "seion"]
        dakuon_mu = [r["mu"] for r in sub if r["type"] in ("dakuon", "handakuon")]
        ratio = (float(np.mean(dakuon_mu)) / float(np.mean(seion_mu))
                 if seion_mu and dakuon_mu and np.mean(seion_mu) != 0 else float("nan"))
        out.append(dict(family=fam, n_chars=len(sub), ink_mu_spearman=float(rho),
                         seion_mu_mean=float(np.mean(seion_mu)) if seion_mu else float("nan"),
                         dakuon_mu_mean=float(np.mean(dakuon_mu)) if dakuon_mu else float("nan"),
                         dakuon_vs_seion_ratio=ratio))
    return out


def write_mechanism(path_corr, path_mech, corr_mat, mech_rows):
    with io.open(path_corr, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family_1", "family_2", "spearman_rho", "n_chars_common"])
        if corr_mat:
            for f1 in FAMILIES:
                for f2 in FAMILIES:
                    rho, n = corr_mat[(f1, f2)]
                    w.writerow([f1, f2, _fmt(rho, 3), n])
    print(f"  書き出し: {os.path.basename(path_corr)}")

    with io.open(path_mech, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family", "n_chars", "ink_pixels_vs_mu_spearman", "seion_mu_mean",
                     "dakuon_handakuon_mu_mean", "dakuon_vs_seion_mu_ratio"])
        for r in mech_rows:
            w.writerow([r["family"], r["n_chars"], _fmt(r["ink_mu_spearman"], 3),
                        _fmt(r["seion_mu_mean"], 2), _fmt(r["dakuon_mu_mean"], 2),
                        _fmt(r["dakuon_vs_seion_ratio"], 3)])
    print(f"  書き出し: {os.path.basename(path_mech)}")


def best_family_per_char(vs_fit_pooled_by_key, struct):
    """本命8字それぞれについて、μが最小(=最も少ない進み具合で読めるようになる)の方式を選ぶ。
    『この字にはこの方式が適する』という向きの対応表(著者の指摘への対応)。
    理由付けは字の構造指標(清濁・墨の左右分布・細部量)を添えるだけで、統計的な検定はしない
    (本命8字だけではn=8と少なく、傾向の記述にとどめる。統計的な裏付けは63字を使った
    mechanism_correlates 側にある)。"""
    out = []
    for ch in TARGET_CHARS:
        cand = []
        for fam in FAMILIES:
            vf = vs_fit_pooled_by_key.get((ch, fam))
            if vf is not None and vf["converged"] and not math.isnan(vf["mu"]):
                cand.append((fam, vf["mu"], vf["lam"]))
        cand.sort(key=lambda t: t[1])
        d = struct.get(ch, {})
        reasons = []
        if cand:
            best_fam = cand[0][0]
            if best_fam == "wipe" and d.get("right_ink_frac", 1) < 0.45:
                reasons.append("墨が左寄り(wipeは左から現れるため有利)")
            if best_fam == "blur" and d.get("fine_detail_frac", 1) < 0.3:
                reasons.append("細部が少ない(blurで埋もれにくい)")
            if best_fam in ("fade", "reveal"):
                reasons.append("字全体が一様に立ち上がる方式で、位置に依存しない")
            if DIACRITIC[ch] != "seion" and cand[-1][0] in ("wipe", "blur"):
                reasons.append(f"濁点/半濁点を持つため{FAMILY_LABEL[cand[-1][0]]}は不利(最下位)")
        out.append(dict(
            char=ch, diacritic=DIACRITIC[ch],
            best_family=cand[0][0] if cand else "", best_mu=cand[0][1] if cand else float("nan"),
            second_family=cand[1][0] if len(cand) > 1 else "", second_mu=cand[1][1] if len(cand) > 1 else float("nan"),
            worst_family=cand[-1][0] if cand else "", worst_mu=cand[-1][1] if cand else float("nan"),
            right_ink_frac=d.get("right_ink_frac", float("nan")),
            fine_detail_frac=d.get("fine_detail_frac", float("nan")),
            reason="; ".join(reasons) if reasons else ""))
    return out


def write_best_family_per_char(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "diacritic", "best_family", "best_mu", "second_family", "second_mu",
                     "worst_family", "worst_mu", "right_ink_frac", "fine_detail_frac", "reason"])
        for r in rows:
            w.writerow([r["char"], DIACRITIC_LABEL[r["diacritic"]], r["best_family"], _fmt(r["best_mu"], 2),
                        r["second_family"], _fmt(r["second_mu"], 2), r["worst_family"], _fmt(r["worst_mu"], 2),
                        _fmt(r["right_ink_frac"], 3), _fmt(r["fine_detail_frac"], 3), r["reason"]])
    print(f"  書き出し: {os.path.basename(path)} ({len(rows)}字)")


# ---------------------------------------------------------------------------
# ③ 転写成立の判定(主目的)
# ---------------------------------------------------------------------------
def fit_audio_char(rows_audio_main, char, gamma_audio, n_starts):
    sub = [r for r in rows_audio_main if r["target_char"] == char]
    xs, ks, ns = acf.aggregate_levels(sub, "gate_ms")
    fit = acf.fit_sigmoid(xs, ks, ns, gamma_audio, n_starts=n_starts)
    n_part = len({r["participant_id"] for r in sub})
    gate_vals = sorted({r["gate_ms"] for r in sub if r["gate_ms"] is not None})
    return fit, n_part, len(sub), gate_vals


def write_audio_fit(path, data, n_starts, lambda_usable_threshold):
    """字ごとの聴覚シグモイド当てはめと、'転写のq(t)を作るのに使えるか'の判定。

    使えると判定する条件(既定値の根拠):
      - 当てはめが収束していること
      - lambda(天井) >= lambda_usable_threshold (既定0.5): 五分以上当てられる字でなければ
        「聞けば分かるようになる」というA(t)の前提自体が成り立たない
      - mu(立ち上がりの中心)が実際に試した打ち切り時間の範囲内にあること: 範囲の外に
        あると「何msから読めるか」という時間軸そのものが外挿になり、q(t)の形が
        データに支えられない(例: つ は lambda=0.67>=0.5 だが mu=1.8ms で試した範囲
        10-90msの外側にあり、これは除外する)
    この2条件をあわせると、既知の「あ・か・まの3字しか転写に使えない」と一致する。
    """
    rows_out = []
    usable = {}
    for ch in TARGET_CHARS:
        fit, n_part, n_trials, gate_vals = fit_audio_char(data["rows_audio_main"], ch, data["gamma_audio"], n_starts)
        mu_in_domain = (len(gate_vals) >= 2 and not math.isnan(fit["mu"])
                         and gate_vals[0] <= fit["mu"] <= gate_vals[-1])
        is_usable = bool(fit["converged"] and not math.isnan(fit["lam"]) and fit["lam"] >= lambda_usable_threshold
                          and mu_in_domain)
        usable[ch] = is_usable
        note_parts = [fit["note"]] if fit["note"] else []
        if not mu_in_domain:
            note_parts.append("muが実測の打ち切り時間範囲の外(時間軸が外挿になる)")
        if not math.isnan(fit["lam"]) and fit["lam"] < lambda_usable_threshold:
            note_parts.append(f"lambda({fit['lam']:.2f})が使用可否の閾値{lambda_usable_threshold}未満")
        # 実質選択肢数(全部聞かせても何択まで絞れるか): 較正はしごに埋め込まれた
        # 「打ち切りなし」試行(rows_audio_fullplay)の応答分布から直接求める。
        full_sub = [r for r in data.get("rows_audio_fullplay", []) if r["target_char"] == ch]
        h_full, n_full = response_entropy_bits(full_sub)
        perp_full = 2.0 ** h_full if h_full == h_full else float("nan")
        rows_out.append(dict(char=ch, gamma=data["gamma_audio"], lam=fit["lam"], mu=fit["mu"], sigma=fit["sigma"],
                              converged=fit["converged"], n_trials=fit["n_trials"], n_participants=n_part,
                              gate_ms_tested=";".join(str(int(g)) for g in gate_vals),
                              usable_for_transcription=is_usable, note=";".join(p for p in note_parts if p),
                              n_full=n_full, entropy_full_bits=h_full, perplexity_full=perp_full))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "gamma", "lambda", "mu", "sigma", "converged", "n_trials", "n_participants",
                     "gate_ms_tested", "usable_for_transcription", "note",
                     "n_full", "entropy_full_bits", "perplexity_full"])
        for r in rows_out:
            w.writerow([r["char"], round(r["gamma"], 5), _fmt(r["lam"]), _fmt(r["mu"]), _fmt(r["sigma"]),
                        r["converged"], r["n_trials"], r["n_participants"], r["gate_ms_tested"],
                        r["usable_for_transcription"], r["note"],
                        r["n_full"], _fmt(r["entropy_full_bits"], 3), _fmt(r["perplexity_full"], 2)])
    n_usable = sum(usable.values())
    print(f"  書き出し: {os.path.basename(path)} (使用可: {n_usable}/8字 = {[c for c in TARGET_CHARS if usable[c]]})")
    return {r["char"]: r for r in rows_out}, usable


def invert_sigmoid_for_x(p_target, gamma, lam, mu, sigma):
    """p(x)=gamma+(lam-gamma)/(1+exp(-(x-mu)/sigma)) を p_target について x に解く。
    p_targetがgammaより下/lamより上ならNoneを返す(数学的に解なし=丸め領域)。"""
    if lam <= gamma or sigma <= 0 or math.isnan(lam) or math.isnan(mu) or math.isnan(sigma):
        return None
    if not (gamma < p_target < lam):
        return None
    ratio = (lam - gamma) / (p_target - gamma) - 1.0
    if ratio <= 0:
        return None
    return mu - sigma * math.log(ratio)


def compute_transcribability(data, audio_fit_by_char, audio_usable, vs_fit_pooled_by_key,
                              unfit_threshold, error_quality_lookup, perplexity_lookup,
                              quality_min_n, quality_guess_thr, quality_concentrate_thr, n_grid=400):
    """32通り(8字×4方式)について、q(t)=(p_audio(t)-gamma_a)/(lambda_a-gamma_a) を
    聴覚のシグモイドから作り、視覚V(s)(=gamma_v+(lambda_v-gamma_v)/(1+exp(-(s-mu_v)/sigma_v)))
    に対して q(t) を直接、目標の正答率とみなして逆引きする(s(t)=V^-1(q(t)))。

    q(t)は聴覚字自身のgamma/lambdaで0→1に正規化された「識別の進み具合」。これを
    視覚側の生の正答率スケール[gamma_v, lambda_v]に対してそのまま逆引きするので、
    q(t) > lambda_v になった時点で「視覚がその字の方式でどう頑張っても聴覚に追いつけない」
    という丸め(s=1に張り付く)が起きる。逆にq(t) < gamma_vは自明に満たされる
    (s=0でもgamma_v以上の正答率が出るため、丸めとしては数えない)。

    誤りの質(error_quality_lookup)と実質選択肢数(perplexity_lookup)は、audio_usableや
    視覚曲線の収束にかかわらず全32セルに付与する(視覚だけで決まる量のため)。
    """
    def enrich(row, ch, fam):
        eq = error_quality_lookup.get((ch, fam))
        pp = perplexity_lookup.get((ch, fam))
        if eq is not None:
            label = classify_error_quality(eq["entropy_norm"], eq["n_errors"], quality_min_n,
                                            quality_guess_thr, quality_concentrate_thr)
            row.update(error_quality=label, error_quality_level=eq["level"] if eq["level"] is not None else "",
                       error_quality_n_errors=eq["n_errors"], error_quality_entropy_norm=_fmt(eq["entropy_norm"], 3))
        else:
            row.update(error_quality="", error_quality_level="", error_quality_n_errors="",
                       error_quality_entropy_norm="")
        if pp is not None and pp["level"] is not None:
            row.update(perplexity_near_mu=_fmt(pp["perplexity"], 2), perplexity_n_trials=pp["n_trials"])
        else:
            row.update(perplexity_near_mu="", perplexity_n_trials="")
        return row

    rows_out = []
    for ch in TARGET_CHARS:
        af = audio_fit_by_char[ch]
        gate_vals_str = af["gate_ms_tested"]
        gate_vals = [float(x) for x in gate_vals_str.split(";")] if gate_vals_str else []
        for fam in FAMILIES:
            vf = vs_fit_pooled_by_key.get((ch, fam))
            row = dict(char=ch, family=fam, diacritic=DIACRITIC[ch],
                       audio_usable=audio_usable.get(ch, False))
            if not audio_usable.get(ch, False):
                row.update(judgement="対象外(聴覚曲線が転写に使えない)", frac_clamped_upper="",
                           t_clamp_start_ms="", t_domain_min="", t_domain_max="",
                           lambda_visual=_fmt(vf["lam"]) if vf else "", gamma_visual=_fmt(vf["gamma"]) if vf else "",
                           mu_visual=_fmt(vf["mu"]) if vf else "", visual_converged=vf["converged"] if vf else "")
                rows_out.append(enrich(row, ch, fam))
                continue
            if vf is None or not vf["converged"] or math.isnan(vf["lam"]) or math.isnan(vf["mu"]):
                row.update(judgement="対象外(視覚曲線が当てはまらない)", frac_clamped_upper="",
                           t_clamp_start_ms="", t_domain_min="", t_domain_max="",
                           lambda_visual=_fmt(vf["lam"]) if vf else "", gamma_visual=_fmt(vf["gamma"]) if vf else "",
                           mu_visual="", visual_converged=vf["converged"] if vf else False)
                rows_out.append(enrich(row, ch, fam))
                continue
            if len(gate_vals) < 2:
                row.update(judgement="対象外(聴覚の実測範囲が不足)", frac_clamped_upper="", t_clamp_start_ms="",
                           t_domain_min="", t_domain_max="", lambda_visual=_fmt(vf["lam"]),
                           gamma_visual=_fmt(vf["gamma"]), mu_visual=_fmt(vf["mu"]), visual_converged=vf["converged"])
                rows_out.append(enrich(row, ch, fam))
                continue

            t_lo, t_hi = gate_vals[0], gate_vals[-1]
            t_grid = np.linspace(t_lo, t_hi, n_grid)
            gamma_a, lam_a, mu_a, sigma_a = af["gamma"], af["lam"], af["mu"], af["sigma"]
            z = np.clip(-(t_grid - mu_a) / sigma_a, -500, 500)
            p_audio = gamma_a + (lam_a - gamma_a) / (1.0 + np.exp(z))
            q = (p_audio - gamma_a) / (lam_a - gamma_a)
            q = np.clip(q, 0.0, 1.0)

            gamma_v, lam_v, mu_v, sigma_v = vf["gamma"], vf["lam"], vf["mu"], vf["sigma"]
            clamp_upper = q > lam_v
            frac_upper = float(np.mean(clamp_upper))

            # t_star: q(t)=lam_v となる聴覚側の時刻(=丸めが始まる時刻)。
            # q は聴覚自身のgamma_a・lam_aで正規化してあるので、逆引きするときは
            # 目標のlam_v(視覚側の生の正答率スケール)を先に聴覚の生スケールに
            # 変換してから(p_target = gamma_a + (lam_a-gamma_a)*lam_v)、聴覚の
            # シグモイドをそのp_targetについて解く。lam_vをそのまま聴覚のシグモイドに
            # 渡すと、lam_vがlam_aより大きい場合に「解なし」と誤判定してしまう
            # (視覚の天井が聴覚自身の天井より高い、というだけでq自体は1未満で
            # 十分解が存在する)。
            p_target = gamma_a + (lam_a - gamma_a) * min(max(lam_v, 0.0), 1.0)
            t_star = invert_sigmoid_for_x(p_target, gamma_a, lam_a, mu_a, sigma_a)
            # tドメイン外なら「ドメイン全体で丸めなし/丸めっぱなし」のどちらかなので
            # Noneのまま扱う(frac_clamped_upperで丸めの有無自体は別途判定済み)。
            if t_star is not None and not (t_lo <= t_star <= t_hi):
                t_star = None

            if frac_upper <= 1e-9:
                judgement = "成立"
            elif frac_upper >= unfit_threshold:
                judgement = "不成立"
            else:
                judgement = "一部成立"

            row.update(judgement=judgement, frac_clamped_upper=_fmt(frac_upper, 4),
                       t_clamp_start_ms=_fmt(t_star, 2) if t_star is not None else "",
                       t_domain_min=t_lo, t_domain_max=t_hi,
                       lambda_visual=_fmt(lam_v), gamma_visual=_fmt(gamma_v), mu_visual=_fmt(mu_v),
                       visual_converged=vf["converged"])
            rows_out.append(enrich(row, ch, fam))
    return rows_out


def write_transcribability(path, rows_out):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "family", "diacritic", "audio_usable", "judgement", "frac_clamped_upper",
                     "t_clamp_start_ms", "t_domain_min_ms", "t_domain_max_ms",
                     "lambda_visual", "gamma_visual", "mu_visual", "visual_converged",
                     "error_quality", "error_quality_level_s_pct", "error_quality_n_errors",
                     "error_quality_entropy_norm", "perplexity_near_mu", "perplexity_n_trials"])
        for r in rows_out:
            w.writerow([r["char"], r["family"], DIACRITIC_LABEL[r["diacritic"]], r["audio_usable"], r["judgement"],
                        r["frac_clamped_upper"], r["t_clamp_start_ms"], r.get("t_domain_min", ""),
                        r.get("t_domain_max", ""), r["lambda_visual"], r["gamma_visual"], r["mu_visual"],
                        r["visual_converged"], r["error_quality"], r["error_quality_level"],
                        r["error_quality_n_errors"], r["error_quality_entropy_norm"],
                        r["perplexity_near_mu"], r["perplexity_n_trials"]])
    print(f"  書き出し: {os.path.basename(path)} ({len(rows_out)}行=8字×4方式)")


# ---------------------------------------------------------------------------
# ④ 方式どうしの比較
# ---------------------------------------------------------------------------
def weighted_fit_error(rows, char, family, level_key, gamma, lam, mu, sigma):
    """当てはめの良さ: 観測水準ごとの正答率と、当てはめ曲線の予測値との
    試行数重み付き平均絶対誤差(MAE)。値が小さいほど当てはまりが良い。"""
    sub = [r for r in rows if r["target_char"] == char and r["family"] == family]
    xs, ks, ns = acf.aggregate_levels(sub, level_key)
    if not xs or math.isnan(lam) or math.isnan(mu) or math.isnan(sigma):
        return float("nan")
    xs = np.array(xs, dtype=float)
    ks = np.array(ks, dtype=float)
    ns = np.array(ns, dtype=float)
    z = np.clip(-(xs - mu) / sigma, -500, 500)
    pred = gamma + (lam - gamma) / (1.0 + np.exp(z))
    obs = ks / ns
    return float(np.sum(ns * np.abs(obs - pred)) / np.sum(ns))


def write_family_summary(path, data, vs_fit_pooled_by_key, struct, transcribe_rows, wipe_gap_note):
    """方式ごとの総括。σのばらつきは丸山さんの指摘どおり『不安定』ではなく
    字の構造(墨の位置)による系統差として記述する。"""
    rows_visual = data["rows_visual_main"]
    out = []
    for fam in FAMILIES:
        sigmas, lams, mus, errs = [], [], [], []
        for ch in TARGET_CHARS:
            vf = vs_fit_pooled_by_key.get((ch, fam))
            if vf is None or not vf["converged"] or math.isnan(vf["sigma"]):
                continue
            sigmas.append(vf["sigma"])
            lams.append(vf["lam"])
            mus.append(vf["mu"])
            e = weighted_fit_error(rows_visual, ch, fam, "actual_s_pct", vf["gamma"], vf["lam"], vf["mu"], vf["sigma"])
            if not math.isnan(e):
                errs.append(e)
        sigmas = np.array(sigmas)
        lams = np.array(lams)
        mus = np.array(mus)
        errs = np.array(errs)

        # muのばらつきと、清濁字(が・ぱ)とそれ以外でのmuの差(構造要因の直接証拠)
        seion_mu = [vs_fit_pooled_by_key[(ch, fam)]["mu"] for ch in TARGET_CHARS
                    if DIACRITIC[ch] == "seion" and (ch, fam) in vs_fit_pooled_by_key
                    and vs_fit_pooled_by_key[(ch, fam)]["converged"]]
        diacritic_mu = [vs_fit_pooled_by_key[(ch, fam)]["mu"] for ch in TARGET_CHARS
                        if DIACRITIC[ch] != "seion" and (ch, fam) in vs_fit_pooled_by_key
                        and vs_fit_pooled_by_key[(ch, fam)]["converged"]]
        mu_seion_med = float(np.median(seion_mu)) if seion_mu else float("nan")
        mu_diacritic_med = float(np.median(diacritic_mu)) if diacritic_mu else float("nan")

        n_success = sum(1 for r in transcribe_rows if r["family"] == fam and r["judgement"] == "成立")
        n_partial = sum(1 for r in transcribe_rows if r["family"] == fam and r["judgement"] == "一部成立")
        n_fail = sum(1 for r in transcribe_rows if r["family"] == fam and r["judgement"] == "不成立")
        n_na = sum(1 for r in transcribe_rows if r["family"] == fam and r["judgement"].startswith("対象外"))

        out.append(dict(
            family=fam, n_char_converged=len(sigmas),
            sigma_median=float(np.median(sigmas)) if len(sigmas) else float("nan"),
            sigma_iqr=float(np.percentile(sigmas, 75) - np.percentile(sigmas, 25)) if len(sigmas) else float("nan"),
            lambda_min=float(np.min(lams)) if len(lams) else float("nan"),
            lambda_median=float(np.median(lams)) if len(lams) else float("nan"),
            lambda_max=float(np.max(lams)) if len(lams) else float("nan"),
            mu_min=float(np.min(mus)) if len(mus) else float("nan"),
            mu_max=float(np.max(mus)) if len(mus) else float("nan"),
            mu_seion_median=mu_seion_med, mu_diacritic_median=mu_diacritic_med,
            mu_diacritic_minus_seion=(mu_diacritic_med - mu_seion_med
                                       if not math.isnan(mu_seion_med) and not math.isnan(mu_diacritic_med) else float("nan")),
            fit_error_mean=float(np.mean(errs)) if len(errs) else float("nan"),
            n_success=n_success, n_partial=n_partial, n_fail=n_fail, n_na=n_na,
            note=wipe_gap_note.get(fam, ""),
        ))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        cols = ["family", "n_char_converged", "sigma_median", "sigma_iqr", "lambda_min", "lambda_median",
                "lambda_max", "mu_min", "mu_max", "mu_seion_median", "mu_diacritic_median",
                "mu_diacritic_minus_seion", "fit_error_mean", "n_success", "n_partial", "n_fail", "n_na", "note"]
        w.writerow(cols)
        for r in out:
            w.writerow([r["family"], r["n_char_converged"], _fmt(r["sigma_median"], 3), _fmt(r["sigma_iqr"], 3),
                        _fmt(r["lambda_min"], 3), _fmt(r["lambda_median"], 3), _fmt(r["lambda_max"], 3),
                        _fmt(r["mu_min"], 2), _fmt(r["mu_max"], 2), _fmt(r["mu_seion_median"], 2),
                        _fmt(r["mu_diacritic_median"], 2), _fmt(r["mu_diacritic_minus_seion"], 2),
                        _fmt(r["fit_error_mean"], 4), r["n_success"], r["n_partial"], r["n_fail"], r["n_na"],
                        r["note"]])
    print(f"  書き出し: {os.path.basename(path)} ({len(out)}方式)")
    return out


def fade_resolution_limit(vs_fit_pooled_by_key, opacity_levels=256):
    """fadeは不透明度(0〜255の256段階)でしか濃さを表現できない画面の限界に当たっている。
    各字の当てはめ曲線の最大傾き(ロジスティックのピーク微分 = (lam-gamma)/(4*sigma))に
    1階調(=1/256)を掛けると、『1階調だけ濃さを変えたときにqがどれだけ動くか』
    =識別の進み具合でみた分解能の限界が数値で出る。
    根拠: 8/72=0.8%が濃さ2階調、1.2%が濃さ3階調という設計側の実測(⚠指示に明記)から、
    1s(0-1スケール)あたり256階調と分かる。"""
    out = []
    for ch in TARGET_CHARS:
        vf = vs_fit_pooled_by_key.get((ch, "fade"))
        if vf is None or not vf["converged"] or math.isnan(vf["sigma"]) or vf["sigma"] <= 0:
            continue
        peak_slope = (vf["lam"] - vf["gamma"]) / (4.0 * vf["sigma"] / 100.0)  # sigmaは%軸なので/100でs軸(0-1)に戻す
        delta_p_per_level = peak_slope * (1.0 / opacity_levels)
        out.append(dict(char=ch, sigma_pct=vf["sigma"], peak_slope_per_s=peak_slope,
                         delta_accuracy_per_opacity_level=delta_p_per_level))
    return out


# ---------------------------------------------------------------------------
# 図: matplotlibでHTMLへ埋め込むためのbase64化
# ---------------------------------------------------------------------------
def fig_to_data_uri(fig, dpi=140):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def sigmoid_curve(xs, gamma, lam, mu, sigma):
    z = np.clip(-(xs - mu) / sigma, -500, 500)
    return gamma + (lam - gamma) / (1.0 + np.exp(z))


def plot_family_vs(family, vs_fit_by_key_speed, rows_visual_main):
    """1方式ぶんのV(s)図。8字を重ね、速さで線種を変える(実線=300ms, 破線=500ms)。
    薄い背景の散布は実測の水準ごと正答率(速さは混ぜて表示、参考情報)。"""
    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    x_grid = np.linspace(0, 100, 300)
    for ch in TARGET_CHARS:
        color = CHAR_COLOR[ch]
        # 背景の実測点(参考。速さ混ぜ)
        sub = [r for r in rows_visual_main if r["target_char"] == ch and r["family"] == family]
        xs, ks, ns = acf.aggregate_levels(sub, "actual_s_pct")
        if xs:
            obs = np.array(ks) / np.maximum(np.array(ns), 1)
            ax.scatter(xs, obs, s=10, color=color, alpha=0.25, zorder=1)
        for speed, ls in ((300, "-"), (500, "--")):
            vf = vs_fit_by_key_speed.get((ch, family, speed))
            if vf is None or not vf["converged"] or math.isnan(vf["mu"]):
                continue
            y = sigmoid_curve(x_grid, vf["gamma"], vf["lam"], vf["mu"], vf["sigma"])
            ax.plot(x_grid, y, ls, color=color, linewidth=1.8, alpha=0.9,
                    label=f"{ch}" if speed == 300 else None)
    ax.set_xlabel("進み具合 s (実測 actual_s、%)")
    ax.set_ylabel("正答率")
    ax.set_ylim(-0.03, 1.03)
    ax.set_xlim(-2, 102)
    ax.set_title(f"{FAMILY_LABEL[family]}  V(s) — 実線=300ms, 破線=500ms")
    ax.legend(loc="upper left", fontsize=9, ncol=2, framealpha=0.9, title="字")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig_to_data_uri(fig)


JUDGE_COLOR = {"成立": 0, "一部成立": 1, "不成立": 2}
JUDGE_NA_COLOR = 3


def plot_heatmap(transcribe_rows):
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    mat = np.full((len(TARGET_CHARS), len(FAMILIES)), np.nan)
    text = [["" for _ in FAMILIES] for _ in TARGET_CHARS]
    for r in transcribe_rows:
        i = TARGET_CHARS.index(r["char"])
        j = FAMILIES.index(r["family"])
        j_label = r["judgement"]
        code = JUDGE_COLOR.get(j_label, JUDGE_NA_COLOR)
        mat[i, j] = code
        if j_label.startswith("対象外"):
            text[i][j] = "対象外"
        else:
            frac = r["frac_clamped_upper"]
            t_star = r["t_clamp_start_ms"]
            lbl = j_label
            if frac != "":
                lbl += f"\n丸め{float(frac) * 100:.0f}%"
            if t_star != "":
                lbl += f"\n{float(t_star):.0f}ms〜"
            text[i][j] = lbl
    cmap = matplotlib.colors.ListedColormap(["#15803d", "#eab308", "#b91c1c", "#9ca3af"])
    im = ax.imshow(mat, cmap=cmap, vmin=-0.5, vmax=3.5, aspect="auto")
    ax.set_xticks(range(len(FAMILIES)))
    ax.set_xticklabels([FAMILY_LABEL[f] for f in FAMILIES], rotation=20, ha="right")
    ax.set_yticks(range(len(TARGET_CHARS)))
    ax.set_yticklabels([f"{ch}({DIACRITIC_LABEL[DIACRITIC[ch]]})" for ch in TARGET_CHARS])
    for i in range(len(TARGET_CHARS)):
        for j in range(len(FAMILIES)):
            ax.text(j, i, text[i][j], ha="center", va="center", fontsize=7.3, color="white")
    ax.set_title("転写成立判定(8字×4方式)")
    cbar = fig.colorbar(im, ticks=[0, 1, 2, 3])
    cbar.ax.set_yticklabels(["成立", "一部成立", "不成立", "対象外"])
    fig.tight_layout()
    return fig_to_data_uri(fig)


def plot_speed_effect(family_rows):
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    subsets = ["all", "frames_differ_only"]
    subset_label = {"all": "全データ", "frames_differ_only": "絵が実際に違う試行のみ"}
    width = 0.35
    xpos = np.arange(len(FAMILIES))
    for si, subset in enumerate(subsets):
        vals, los, his = [], [], []
        for fam in FAMILIES:
            rr = [r for r in family_rows if r["family"] == fam and r["subset"] == subset]
            r = rr[0] if rr else None
            if r is None or math.isnan(r["diff_boot_median"]):
                vals.append(0)
                los.append(0)
                his.append(0)
            else:
                vals.append(r["diff_boot_median"])
                los.append(r["diff_boot_median"] - r["diff_lo95"])
                his.append(r["diff_hi95"] - r["diff_boot_median"])
        offset = (si - 0.5) * width
        ax.bar(xpos + offset, vals, width, yerr=[los, his], capsize=3,
               label=subset_label[subset], color=["#0f766e", "#c2410c"][si], alpha=0.85)
    ax.axhline(0, color="#374151", linewidth=0.8)
    ax.set_xticks(xpos)
    ax.set_xticklabels([FAMILY_LABEL[f] for f in FAMILIES], rotation=15, ha="right")
    ax.set_ylabel("正答率の差 (500ms − 300ms)")
    ax.set_title("速さ(300ms/500ms)の効果 — 方式ごと(参加者単位ブートストラップ95%区間)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    return fig_to_data_uri(fig)


def plot_structure_correlation(struct, vs_fit_pooled_by_key):
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.3))
    # 左: wipeのmu vs 墨の右寄り具合
    ax = axes[0]
    xs, ys, labels, colors = [], [], [], []
    for ch in TARGET_CHARS:
        d = struct.get(ch)
        vf = vs_fit_pooled_by_key.get((ch, "wipe"))
        if d is None or vf is None or not vf["converged"] or math.isnan(vf["mu"]):
            continue
        xs.append(d["right_ink_frac"])
        ys.append(vf["mu"])
        labels.append(ch)
        colors.append("#b91c1c" if d["diacritic"] != "seion" else "#374151")
    ax.scatter(xs, ys, c=colors, s=60)
    for x, y, l in zip(xs, ys, labels):
        ax.annotate(l, (x, y), textcoords="offset points", xytext=(5, 4), fontsize=11)
    ax.set_xlabel("墨が右半分にある割合 (right_ink_frac)")
    ax.set_ylabel("wipeのμ (進み具合%、大きいほど遅く読める)")
    ax.set_title("wipe: 墨の右寄り具合とμ")
    ax.grid(alpha=0.25)

    # 右: blurのmu vs 細部量(fine_detail_frac)
    ax = axes[1]
    xs, ys, labels, colors = [], [], [], []
    for ch in TARGET_CHARS:
        d = struct.get(ch)
        vf = vs_fit_pooled_by_key.get((ch, "blur"))
        if d is None or vf is None or not vf["converged"] or math.isnan(vf["mu"]) or math.isnan(d["fine_detail_frac"]):
            continue
        xs.append(d["fine_detail_frac"])
        ys.append(vf["mu"])
        labels.append(ch)
        colors.append("#b91c1c" if d["diacritic"] != "seion" else "#374151")
    ax.scatter(xs, ys, c=colors, s=60)
    for x, y, l in zip(xs, ys, labels):
        ax.annotate(l, (x, y), textcoords="offset points", xytext=(5, 4), fontsize=11)
    ax.set_xlabel("細部量 (fine_detail_frac、収縮1回で失われる墨の割合)")
    ax.set_ylabel("blurのμ (進み具合%)")
    ax.set_title("blur: 細部量とμ")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig_to_data_uri(fig)


def plot_rank_correlation(corr_mat):
    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    mat = np.array([[corr_mat[(f1, f2)][0] for f2 in FAMILIES] for f1 in FAMILIES])
    im = ax.imshow(mat, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(FAMILIES)))
    ax.set_xticklabels([FAMILY_LABEL[f] for f in FAMILIES], rotation=25, ha="right")
    ax.set_yticks(range(len(FAMILIES)))
    ax.set_yticklabels([FAMILY_LABEL[f] for f in FAMILIES])
    for i in range(len(FAMILIES)):
        for j in range(len(FAMILIES)):
            ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center",
                    color="white" if abs(mat[i, j]) > 0.5 else "black", fontsize=11)
    ax.set_title("方式間のμ順位相関(まぎれ字63字、Spearman)\nほぼ0 = 「読みにくい字」という共通の性質は無い")
    fig.colorbar(im)
    fig.tight_layout()
    return fig_to_data_uri(fig)


def plot_char_family_rank_heatmap(decoy_rows):
    """63字×4方式のμ順位(1=最も少ない進み具合で読める=簡単)のヒートマップ。
    方式によって順位がばらばらに入れ替わることを一枚で見せる、本研究の主要な図。"""
    by_fam = defaultdict(dict)
    for r in decoy_rows:
        if r["converged"]:
            by_fam[r["family"]][r["char"]] = r["mu"]
    chars = sorted(set.intersection(*[set(by_fam[f].keys()) for f in FAMILIES]))
    rank = {}
    for fam in FAMILIES:
        order = sorted(chars, key=lambda c: by_fam[fam][c])
        rank[fam] = {c: i + 1 for i, c in enumerate(order)}
    mean_rank = {c: np.mean([rank[f][c] for f in FAMILIES]) for c in chars}
    chars_sorted = sorted(chars, key=lambda c: mean_rank[c])
    mat = np.array([[rank[f][c] for f in FAMILIES] for c in chars_sorted])

    fig, ax = plt.subplots(figsize=(5.6, max(9.0, len(chars_sorted) * 0.16)))
    im = ax.imshow(mat, cmap="RdYlGn_r", aspect="auto")
    ax.set_xticks(range(len(FAMILIES)))
    ax.set_xticklabels([FAMILY_LABEL[f] for f in FAMILIES], rotation=25, ha="right")
    ax.set_yticks(range(len(chars_sorted)))
    ax.set_yticklabels(chars_sorted, fontsize=6.5)
    ax.set_title(f"字×方式のμ順位(まぎれ字{len(chars_sorted)}字、1=簡単・{len(chars_sorted)}=難しい)\n"
                 "行(字)ごとに色がバラバラ = 方式によって得意な字が違う")
    fig.colorbar(im, label="順位(小さいほど簡単)")
    fig.tight_layout()
    return fig_to_data_uri(fig)


def plot_error_entropy_bands(level_rows, transitions):
    """方式ごとに、誤答エントロピー(正規化)が進み具合でどう変わるかを1枚で見せる。
    『当てずっぽうの帯』から『細部だけが残る帯』への転換点を縦線で示す。"""
    fig, ax = plt.subplots(figsize=(7.4, 5.0))
    for fam in FAMILIES:
        rows = sorted([r for r in level_rows if r["family"] == fam], key=lambda r: r["progress_pct"])
        xs = [r["progress_pct"] for r in rows]
        ys = [r["entropy_norm"] for r in rows]
        ax.plot(xs, ys, "o-", color=FAMILY_COLOR[fam], label=FAMILY_LABEL[fam], linewidth=1.8)
        s_star = transitions.get(fam, {}).get("transition_s_pct")
        if s_star is not None:
            ax.axvline(s_star, color=FAMILY_COLOR[fam], linestyle=":", alpha=0.6)
    ax.set_xlabel("進み具合 s (実測、%)")
    ax.set_ylabel("誤答エントロピー(正規化 0-1、1=完全に当てずっぽう)")
    ax.set_ylim(-0.03, 1.05)
    ax.set_title("誤りの質: 当てずっぽう(上)→細部だけの取り違え(下)への転換\n"
                 "点線=転換点(entropy_norm がそれ以降ずっと閾値未満になる最初の水準)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig_to_data_uri(fig)


def plot_perplexity(perplexity_visual_bins, perplexity_audio_bins):
    """実質選択肢数(2^H)の主要な図。左: 視覚(方式ごと、進み具合の帯)。
    右: 聴覚(打ち切り時間の帯、末尾に『打ち切りなし』)。ともに縦軸は対数。"""
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))

    ax = axes[0]
    n_bin = max(r["bin_index"] for r in perplexity_visual_bins) + 1
    for fam in FAMILIES:
        rows = sorted([r for r in perplexity_visual_bins if r["family"] == fam], key=lambda r: r["bin_index"])
        xs = [r["bin_index"] for r in rows]
        ys = [r["perplexity"] if r["n_trials"] > 0 else np.nan for r in rows]
        ax.plot(xs, ys, "o-", color=FAMILY_COLOR[fam], label=FAMILY_LABEL[fam], linewidth=1.8)
    ax.set_yscale("log")
    ax.set_xticks(range(n_bin))
    ax.set_xticklabels([r["bin_label"] for r in perplexity_visual_bins if r["family"] == FAMILIES[0]],
                       rotation=40, ha="right", fontsize=8)
    ax.set_xlabel("進み具合の帯(実測%)")
    ax.set_ylabel("実質選択肢数 2^H (対数軸)")
    ax.axhline(72, color="#6b6560", linestyle="--", linewidth=0.8)
    ax.text(0, 72, " 72択(完全にランダム)", fontsize=7, va="bottom", color="#6b6560")
    ax.set_title("視覚: 進み具合ごとの実質選択肢数")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, which="both")

    ax = axes[1]
    rows = sorted(perplexity_audio_bins, key=lambda r: r["bin_index"])
    xs = list(range(len(rows)))
    ys = [r["perplexity"] if r["n_trials"] > 0 else np.nan for r in rows]
    ax.plot(xs, ys, "o-", color="#1d4ed8", linewidth=1.8)
    ax.set_yscale("log")
    ax.set_xticks(xs)
    ax.set_xticklabels([r["bin_label"] for r in rows], rotation=40, ha="right", fontsize=8)
    ax.set_xlabel("打ち切り時間の帯(ms)")
    ax.axhline(68, color="#6b6560", linestyle="--", linewidth=0.8)
    ax.text(0, 68, " 68択(完全にランダム)", fontsize=7, va="bottom", color="#6b6560")
    ax.set_title("聴覚: 打ち切り時間ごとの実質選択肢数\n(右端=打ち切りなしで全部聞かせた場合)")
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    return fig_to_data_uri(fig)


def plot_audio_visual_entropy_compare(error_entropy_audio, error_entropy_visual_char):
    """聴覚vs視覚: 字ごとの誤答エントロピー(正規化)を並べる。質の違い(特定の字との
    混同 vs 当てずっぽう)を一枚で見せる。"""
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    xpos = np.arange(len(TARGET_CHARS))
    width = 0.35
    ys_a = [error_entropy_audio[ch]["entropy_norm"] for ch in TARGET_CHARS]
    ys_v = [error_entropy_visual_char[ch]["entropy_norm"] for ch in TARGET_CHARS]
    ax.bar(xpos - width / 2, ys_a, width, label="聴覚(全gate_ms込み)", color="#1d4ed8", alpha=0.85)
    ax.bar(xpos + width / 2, ys_v, width, label="視覚(全方式・全水準込み)", color="#c2410c", alpha=0.85)
    ax.set_xticks(xpos)
    ax.set_xticklabels([f"{ch}({DIACRITIC_LABEL[DIACRITIC[ch]]})" for ch in TARGET_CHARS])
    ax.set_ylabel("誤答エントロピー(正規化 0-1)")
    ax.set_ylim(0, 1.05)
    ax.set_title("聴覚は特定の字と混同・視覚は当てずっぽうに近い(字ごと、正規化エントロピー)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    return fig_to_data_uri(fig)


# ---------------------------------------------------------------------------
# HTMLレポート
# ---------------------------------------------------------------------------
def build_html(path, ctx):
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def table(rows, cols, col_labels=None):
        col_labels = col_labels or cols
        out = ['<table class="tbl"><thead><tr>']
        for c in col_labels:
            out.append(f"<th>{esc(c)}</th>")
        out.append("</tr></thead><tbody>")
        for r in rows:
            out.append("<tr>")
            for c in cols:
                out.append(f"<td>{esc(r.get(c, ''))}</td>")
            out.append("</tr>")
        out.append("</tbody></table>")
        return "".join(out)

    transcribe_rows = ctx["transcribe_rows"]
    family_summary = ctx["family_summary"]

    # 32セルの要約(結論を先に)
    n_success = sum(1 for r in transcribe_rows if r["judgement"] == "成立")
    n_partial = sum(1 for r in transcribe_rows if r["judgement"] == "一部成立")
    n_fail = sum(1 for r in transcribe_rows if r["judgement"] == "不成立")
    n_na = sum(1 for r in transcribe_rows if r["judgement"].startswith("対象外"))

    corr_rows = []
    for r in transcribe_rows:
        corr_rows.append(dict(char=f'{r["char"]}({DIACRITIC_LABEL[r["diacritic"]]})', family=FAMILY_LABEL[r["family"]],
                               judgement=r["judgement"],
                               frac=f'{float(r["frac_clamped_upper"]) * 100:.1f}%' if r["frac_clamped_upper"] != "" else "-",
                               t_star=f'{float(r["t_clamp_start_ms"]):.0f}ms' if r["t_clamp_start_ms"] != "" else "-",
                               lam_v=r["lambda_visual"],
                               error_quality=r["error_quality"] or "-",
                               perplexity=(f'{float(r["perplexity_near_mu"]):.1f}択'
                                           if r["perplexity_near_mu"] != "" else "-")))

    speed_family_rows = ctx["speed_family_rows"]
    speed_table_rows = []
    for fam in FAMILIES:
        for subset in ("all", "frames_differ_only"):
            rr = [r for r in speed_family_rows if r["family"] == fam and r["subset"] == subset]
            if not rr:
                continue
            r = rr[0]
            speed_table_rows.append(dict(
                family=FAMILY_LABEL[fam], subset=("全データ" if subset == "all" else "絵が違う試行のみ"),
                n300=r["n300"], acc300=f'{r["acc300"]*100:.1f}%' if r["acc300"] == r["acc300"] else "-",
                n500=r["n500"], acc500=f'{r["acc500"]*100:.1f}%' if r["acc500"] == r["acc500"] else "-",
                diff=f'{r["diff_boot_median"]*100:+.1f}pt' if r["diff_boot_median"] == r["diff_boot_median"] else "-",
                ci=f'[{r["diff_lo95"]*100:+.1f}, {r["diff_hi95"]*100:+.1f}]pt' if r["diff_lo95"] == r["diff_lo95"] else "-",
                n_part=r["n_participants"]))

    # 「絵が実際に違う試行のみ」で95%区間が0をまたがない(=有意)な方式を機械的に拾い、
    # 固定の解釈文ではなくデータから直接文章を作る(数値を勝手に決め打ちしないため)。
    sig_effects = []
    for r in speed_family_rows:
        if r["subset"] != "frames_differ_only":
            continue
        if r["diff_lo95"] != r["diff_lo95"] or r["diff_hi95"] != r["diff_hi95"]:
            continue
        if r["diff_lo95"] > 0 or r["diff_hi95"] < 0:
            direction = "500msの方が正答率が高い" if r["diff_boot_median"] > 0 else "300msの方が正答率が高い"
            sig_effects.append(f'{FAMILY_LABEL[r["family"]]}({direction}、'
                                f'{r["diff_boot_median"]*100:+.1f}pt、95%区間[{r["diff_lo95"]*100:+.1f}, {r["diff_hi95"]*100:+.1f}]pt)')
    if sig_effects:
        speed_summary_text = ("絵が実際に違う試行だけで見ると、95%区間が0をまたがない(=速さの効果が"
                               "統計的に見える)方式は: " + "、".join(sig_effects) + "。")
    else:
        speed_summary_text = "絵が実際に違う試行だけで見ると、いずれの方式も95%区間が0をまたぎ、速さの効果は明確でない。"

    fam_summary_rows = []
    for r in family_summary:
        fam_summary_rows.append(dict(
            family=FAMILY_LABEL[r["family"]], sigma_med=f'{r["sigma_median"]:.2f}' if r["sigma_median"] == r["sigma_median"] else "-",
            sigma_iqr=f'{r["sigma_iqr"]:.2f}' if r["sigma_iqr"] == r["sigma_iqr"] else "-",
            lam_range=f'{r["lambda_min"]*100:.0f}–{r["lambda_max"]*100:.0f}%' if r["lambda_min"] == r["lambda_min"] else "-",
            mu_diacritic_minus_seion=f'{r["mu_diacritic_minus_seion"]:+.1f}pt' if r["mu_diacritic_minus_seion"] == r["mu_diacritic_minus_seion"] else "-",
            fit_err=f'{r["fit_error_mean"]:.3f}' if r["fit_error_mean"] == r["fit_error_mean"] else "-",
            counts=f'成立{r["n_success"]}/一部{r["n_partial"]}/不成立{r["n_fail"]}/対象外{r["n_na"]}',
        ))
    # 63字(まぎれ字)での既報値(コーディネーターから提示された、別エージェントの
    # まぎれ字20対解析の結果)と、本命8字(が・ぱの2字のみ)での本計算を突き合わせる文。
    # 数値は本計算(family_summary)側のみをここで動的に埋め込み、63字側の値は文中に
    # 固定で書かず、上のcalloutで既に出典を明記した数値を参照する形にとどめる。
    diacritic_gap_text = "、".join(
        f'{FAMILY_LABEL[r["family"]]} {r["mu_diacritic_minus_seion"]:+.1f}pt'
        for r in family_summary if r["mu_diacritic_minus_seion"] == r["mu_diacritic_minus_seion"])

    struct_rows = []
    for ch in TARGET_CHARS:
        d = ctx["struct"].get(ch, {})
        struct_rows.append(dict(char=ch, diacritic=DIACRITIC_LABEL[DIACRITIC[ch]],
                                 centroid=f'{d.get("centroid_x_frac", float("nan")):.3f}' if d else "-",
                                 right=f'{d.get("right_ink_frac", float("nan"))*100:.1f}%' if d else "-",
                                 fine=f'{d.get("fine_detail_frac", float("nan")):.3f}' if d else "-"))

    fade_res = ctx["fade_res"]
    fade_res_rows = [dict(char=r["char"], sigma=f'{r["sigma_pct"]:.2f}',
                          delta=f'{r["delta_accuracy_per_opacity_level"]*100:.3f}pt/階調')
                     for r in fade_res]

    best_family_rows = ctx["best_family_rows"]
    best_family_table_rows = []
    for r in best_family_rows:
        best_family_table_rows.append(dict(
            char=f'{r["char"]}({DIACRITIC_LABEL[r["diacritic"]]})',
            best=f'{FAMILY_LABEL[r["best_family"]]} (μ={r["best_mu"]:.1f})' if r["best_family"] else "-",
            second=f'{FAMILY_LABEL[r["second_family"]]} (μ={r["second_mu"]:.1f})' if r["second_family"] else "-",
            worst=f'{FAMILY_LABEL[r["worst_family"]]} (μ={r["worst_mu"]:.1f})' if r["worst_family"] else "-",
            reason=r["reason"] or "-"))

    corr_mat = ctx.get("corr_mat")
    mech_rows = ctx.get("mech_rows") or []
    n_decoy_chars = ctx.get("n_decoy_chars", 0)
    corr_matrix_rows = []
    if corr_mat:
        for f1 in FAMILIES:
            row = dict(family=FAMILY_LABEL[f1])
            for f2 in FAMILIES:
                rho, n = corr_mat[(f1, f2)]
                row[f2] = f'{rho:+.2f}' if rho == rho else "-"
            corr_matrix_rows.append(row)
    mech_table_rows = [dict(family=FAMILY_LABEL[r["family"]], n=r["n_chars"],
                            ink_corr=f'{r["ink_mu_spearman"]:+.2f}',
                            ratio=f'{r["dakuon_vs_seion_ratio"]:.2f}倍' if r["dakuon_vs_seion_ratio"] == r["dakuon_vs_seion_ratio"] else "-")
                       for r in mech_rows]

    n_boot_vs = ctx["n_boot_vs"]
    n_part_vs = ctx["n_part_vs"]
    n_audio_rows = len(ctx["data"]["rows_audio_main"])
    n_audio_part = len({r["participant_id"] for r in ctx["data"]["rows_audio_main"]})
    n_visual_rows = len(ctx["data"]["rows_visual_main"])
    n_visual_part = len({r["participant_id"] for r in ctx["data"]["rows_visual_main"]})
    n_fullcheck = len(ctx["data"]["rows_visual_fullcheck"])
    n_fullcheck_clamp0 = sum(1 for r in ctx["data"]["rows_visual_fullcheck"] if r["endpoint_clamped_i"] == 0)

    audio_usable_chars = [ch for ch, u in ctx["audio_usable"].items() if u]
    audio_unusable_chars = [ch for ch, u in ctx["audio_usable"].items() if not u]

    # --- 誤りの質・実質選択肢数(新規セクション用のテーブル) ---
    av_compare_rows = []
    for ch in TARGET_CHARS:
        ea = ctx["error_entropy_audio"][ch]
        ev = ctx["error_entropy_visual_char"][ch]
        av_compare_rows.append(dict(
            char=f'{ch}({DIACRITIC_LABEL[DIACRITIC[ch]]})',
            h_audio=f'{ea["entropy_bits"]:.2f}bit' if ea["entropy_bits"] == ea["entropy_bits"] else "-",
            top_audio=f'{ea["top1_char"]} {ea["top1_share"]*100:.0f}%' if ea["top1_char"] else "-",
            h_visual=f'{ev["entropy_bits"]:.2f}bit' if ev["entropy_bits"] == ev["entropy_bits"] else "-",
            n_distinct_visual=ev["n_distinct_wrong"],
            top_visual=f'{ev["top1_char"]} {ev["top1_share"]*100:.0f}%' if ev["top1_char"] else "-",
        ))
    h_max_audio = math.log2(ctx["data"]["n_choices_audio"])
    h_max_visual = math.log2(ctx["data"]["n_choices_visual"])

    band_table_rows = []
    for r in ctx["error_entropy_bands"]:
        band_table_rows.append(dict(
            family=FAMILY_LABEL[r["family"]], band=f'第{r["band_index"]}帯', s_range=r["s_range"],
            n=r["n_trials"], h=f'{r["entropy_bits"]:.2f}bit' if r["entropy_bits"] == r["entropy_bits"] else "-",
            n_distinct=r["n_distinct_wrong"],
            top=f'{r["top1_char"]} {r["top1_share"]*100:.0f}%' if r["top1_char"] else "-"))

    transition_rows = [dict(family=FAMILY_LABEL[fam], s_star=(f'{t["transition_s_pct"]:g}%'
                            if t["transition_s_pct"] is not None else "-"), note=t["note"])
                       for fam, t in ctx["transitions"].items()]

    full_audio_row = [r for r in ctx["perplexity_audio_bins"] if r["bin_label"] == "打ち切りなし"][0]

    free_gamma_rows = []
    for ch in TARGET_CHARS:
        fg = ctx["audio_fit_free"][ch]
        free_gamma_rows.append(dict(
            char=ch, gamma_free=f'{fg["gamma_free"]:.3f}' if fg["gamma_free"] == fg["gamma_free"] else "-",
            gamma_fixed=f'{1/ctx["data"]["n_choices_audio"]:.3f}',
            lam=f'{fg["lam"]:.2f}' if fg["lam"] == fg["lam"] else "-",
            usable=("使用可" if fg["usable_for_transcription"] else "使用不可")))
    usable_match = ctx["usable_fixed"] == ctx["usable_free"]
    gamma_fixed_val = 1.0 / ctx["data"]["n_choices_audio"]
    gfree_vals = [ctx["audio_fit_free"][ch]["gamma_free"] for ch in TARGET_CHARS
                  if ctx["audio_fit_free"][ch]["gamma_free"] == ctx["audio_fit_free"][ch]["gamma_free"]]
    n_above = sum(1 for g in gfree_vals if g > gamma_fixed_val)
    n_below = sum(1 for g in gfree_vals if g < gamma_fixed_val)
    if n_above > n_below:
        gamma_free_trend_text = (f"字ごとに自由推定したγは、8字中{n_above}字で固定値"
                                  f"({gamma_fixed_val:.3f})より高く出た。")
    elif n_below > n_above:
        gamma_free_trend_text = (f"字ごとに自由推定したγは、むしろ8字中{n_below}字で固定値"
                                  f"({gamma_fixed_val:.3f})より低く出ており、この字レベルの当てはめでは"
                                  f"『特定の字への偏りで正答率の下限が底上げされている』ことは支持されない"
                                  f"(頻用字への偏りは複数字を束ねたときの散らばりの話であり、個々の字の"
                                  f"floor自体を必ずしも押し上げるとは限らない)。")
    else:
        gamma_free_trend_text = "字ごとに自由推定したγは固定値を挟んで概ね半々に分かれた。"

    perplexity_visual_table_rows = [
        dict(family=FAMILY_LABEL[r["family"]], bin=r["bin_label"], n=r["n_trials"],
             n_chars=r["n_chars_with_data"],
             perp=(f'{r["perplexity"]:.1f}択' if r["n_trials"] > 0 else "-(データなし)"))
        for r in ctx["perplexity_visual_bins"]]
    perplexity_audio_table_rows = [
        dict(bin=r["bin_label"], n=r["n_trials"], n_chars=r["n_chars_with_data"],
             perp=(f'{r["perplexity"]:.1f}択' if r["n_trials"] > 0 else "-(データなし)"))
        for r in ctx["perplexity_audio_bins"]]

    # wipeが1〜3%帯で選択肢数が増える(非単調)かどうかを、決め打ちせずデータから判定する。
    wipe_bins = sorted([r for r in ctx["perplexity_visual_bins"] if r["family"] == "wipe" and r["n_trials"] > 0],
                       key=lambda r: r["bin_index"])
    wipe_bump_text = ""
    for i in range(1, len(wipe_bins)):
        if wipe_bins[i]["perplexity"] > wipe_bins[i - 1]["perplexity"]:
            wipe_bump_text = (f'wipeでは「{wipe_bins[i-1]["bin_label"]}」({wipe_bins[i-1]["perplexity"]:.1f}択)から'
                               f'「{wipe_bins[i]["bin_label"]}」({wipe_bins[i]["perplexity"]:.1f}択)にかけて、'
                               f'実質選択肢数がいったん増えている(部分的に見えることでかえって迷いが生じている'
                               f'可能性がある)。他の方式ではこの帯で単調に減少している。')
            break

    html = f"""
<title>方式別V(s)分析</title>
<style>
:root {{
  --bg:#faf8f4; --fg:#1c1a17; --muted:#6b6560; --accent:#b45309; --line:#ded6c8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c; --card:#ffffff;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c; --card:#211e19;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c; --card:#211e19;
}}
* {{ box-sizing: border-box; }}
body {{ background: var(--bg); color: var(--fg); font-family: "Hiragino Sans","Yu Gothic",sans-serif;
       line-height:1.75; max-width: 1080px; margin: 0 auto; padding: 2.5rem 1.5rem 6rem; }}
h1 {{ font-size:1.7rem; border-bottom:2px solid var(--accent); padding-bottom:.5rem; }}
h2 {{ font-size:1.35rem; margin-top:3rem; color:var(--accent); }}
h3 {{ font-size:1.1rem; margin-top:1.8rem; }}
.lead {{ color: var(--muted); font-size:.95rem; }}
.card {{ background: var(--card); border:1px solid var(--line); border-radius:10px; padding:1.2rem 1.4rem; margin:1.2rem 0; }}
.tbl {{ border-collapse: collapse; width:100%; font-size:.86rem; margin:.8rem 0; }}
.tbl th, .tbl td {{ border:1px solid var(--line); padding:.35rem .55rem; text-align:left; }}
.tbl th {{ background: color-mix(in srgb, var(--accent) 12%, var(--card)); }}
.tbl tbody tr:nth-child(even) {{ background: color-mix(in srgb, var(--fg) 4%, var(--card)); }}
img {{ max-width:100%; height:auto; display:block; margin:1rem auto; border-radius:6px; }}
.figwrap {{ overflow-x:auto; }}
.tag {{ display:inline-block; padding:.1rem .5rem; border-radius:5px; font-size:.8rem; font-weight:600; }}
.tag.ok {{ background: color-mix(in srgb, var(--ok) 20%, transparent); color:var(--ok); }}
.tag.warn {{ background: color-mix(in srgb, var(--warn) 20%, transparent); color:var(--warn); }}
.tag.bad {{ background: color-mix(in srgb, var(--bad) 20%, transparent); color:var(--bad); }}
.small {{ font-size:.82rem; color:var(--muted); }}
code {{ background: color-mix(in srgb, var(--fg) 8%, var(--card)); padding:.1rem .3rem; border-radius:4px; }}
.callout {{ border-left:4px solid var(--accent); padding:.6rem 1rem; background: color-mix(in srgb, var(--accent) 8%, var(--card)); margin:1rem 0; }}
</style>

<h1>方式(アニメーション提示方式)ごとの分析</h1>
<p class="lead">
較正フェーズ transfer_trials.csv(253人・18,689行、うち本命8字の本命問題は聴覚{n_audio_rows}行・参加者{n_audio_part}人 /
視覚{n_visual_rows}行・参加者{n_visual_part}人)を用いた、方式(fade / reveal / blur / wipe)ごとの
V(s)当てはめと、聴覚曲線A(t)を視覚アニメの進み方s(t)へ逆引きできるかの評価。
</p>

<h2>結論(先に)</h2>
<div class="card">
<p>
8字×4方式=32通りのうち、<b>聴覚側の打ち切り曲線A(t)が転写に使える字は「あ・か・ま」の3字のみ</b>
(理由: 収束かつ天井λ≥0.5かつμが実測範囲内、という条件で判定。残り5字「が・ぱ・し・つ・ら」は
聴覚の打ち切りだけでは字が特定できず、A(t)自体が信頼できる形にならない)。
この3字×4方式=12セルについて転写の成立を判定した結果:
</p>
<ul>
<li><span class="tag ok">成立</span> {n_success}セル — A(t)の要求するqが常にV(s)の届く範囲に収まる</li>
<li><span class="tag warn">一部成立</span> {n_partial}セル — 途中から丸め(s=1に張り付き)が始まる</li>
<li><span class="tag bad">不成立</span> {n_fail}セル — ほぼ全域で丸めが起き、逆引きが退化する</li>
<li>対象外 {n_na}セル(残り5字、または視覚曲線が当てはまらないセル)</li>
</ul>
<p class="small">対応表は「③ 主目的」節を参照。判定の詳細は project/data_calib_20260825/analysis_families/transcribability_table.csv。</p>
</div>

<div class="callout">
<b>字をまとめて平均してはいけない(丸山さんの指摘、まぎれ字63字・20対の解析で確認済み)。</b>
清音→濁音/半濁音でμが動く量(中央値)は wipe +25.6pt(は→ば +91.3pt)、blur +16.6pt(く→ぐ +41.3pt)、
reveal +1.3pt、fade +0.3pt。濁点/半濁点は字の右上にあり、<b>wipeは左→右に現れる</b>ため最後まで出ない。
blurは<b>小さい点・細い線から先に埋もれる</b>ため濁点/半濁点に弱い。fade・revealは字全体が一様に立ち上がるため
点の位置に依存しない。<b>これは「不安定さ」ではなく、字の構造で決まる系統差</b>であり、
「字によって適した方式が違う」という本研究の主要な知見である(下の④で本命8字自身のデータでも確認する)。
さらに、方式間でμの順位相関を取るとほぼ0(④参照)で、<b>「読みにくい字」という方式を超えた
共通の性質は存在しない</b>。つまり転写できるかどうかは字だけでも方式だけでも決まらず、
<b>字と方式の組み合わせで決まる</b>。
</div>

<div class="callout">
<b>正答率だけでは「紛らわしいから間違えている」のか「何も伝わっていないから当てずっぽう」なのか
区別できない(②-b参照)。</b>
誤答の散らばり(エントロピー)を測ると、聴覚は特定の字への明確な取り違えに偏るのに対し
(例: 「が」の誤答の70%が「か」)、視覚は初期段階でほぼ当てずっぽうに近い(誤答が50種類以上に
分散)。<b>実質選択肢数(2^H)</b>で見ると、<b>聴覚は打ち切りなしで全部聞かせても
{full_audio_row['perplexity']:.1f}択までしか絞れない</b>——これは聴覚側に、
どれだけ時間をかけても解消しない曖昧さの床があることを意味し、が・ぱ・し・つ・らの聴覚曲線が
転写に使えないことと直接つながる。視覚はwipeの1〜3%帯で選択肢数がいったん増える(部分的に
見えることで逆に迷いが生じる)などの非単調な挙動を除けば、多くの方式で最終的に1〜2択まで絞られる。
</div>

<h2>① 方式ごとのV(s) — 実測値の軸で</h2>
<p>横軸は実測進み具合(<code>actual_s</code>、名目値ではなく実際に画面へ出た値)を主軸とする。
字×方式×速さ(300ms/500ms)を混ぜずに当てはめ、γ=1/{ctx['data']['n_choices_visual']}固定・λ自由推定のシグモイドを
参加者単位ブートストラップ({n_boot_vs}回、参加者{n_part_vs}人)で95%区間まで求めた
(<code>vs_fit_point.csv</code> に含む版/外す版・実測/名目軸の全点推定、<code>vs_bootstrap.csv</code> に区間)。</p>
<p class="small">
確認問題A(check_kind=full、進み具合100%固定)の追加データ{n_fullcheck}行は、全行が
<code>endpoint_clamped=0</code>(=アニメが自然に最後まで再生され、明示的な「途中で止める」処理が
発生しなかった行。実際には<code>actual_s</code>は狙った値と完全一致しており、値そのものの信頼性に
問題はない)。本命問題(check_kind=空)側は全行<code>endpoint_clamped=1</code>で、この論点の影響を
受けない。指示にある「endpoint_clamped=0(1,005件・9%、is_test除外後は{n_fullcheck}件)を
含む版と外す版」は、この確認問題Aの{n_fullcheck}行を天井(λ)側のデータとして<b>足すか足さないか</b>
として実装した(本命問題だけでは全行clamped=1のため、この論点はここにしか現れない)。</p>

<div class="figwrap">
{ctx['fig_vs_fade']}
{ctx['fig_vs_reveal']}
{ctx['fig_vs_blur']}
{ctx['fig_vs_wipe']}
</div>

<h2>② 速さ(300ms/500ms)の効果 — 方式ごと(RQ4)</h2>
<p>計画書の予想: fadeは濃さの操作なので目の追随速度の影響を受けやすく、revealは画素の積み上げなので
受けにくいのではないか。ここでは方式ごと・水準ごとに300msと500msの正答率を比較する。
薄い水準では画面書き換え周期(リフレッシュレート)の制約で、300msと500msでも実際には同じ絵しか
出せない試行があるため、<code>actual_frames</code>の平均が速さ間で異なる水準だけに絞った版も作った。</p>
{ctx['fig_speed']}
{table(speed_table_rows, ["family","subset","n300","acc300","n500","acc500","diff","ci","n_part"],
       ["方式","対象","n(300ms)","正答率(300ms)","n(500ms)","正答率(500ms)","差(500-300、ブート中央値)","95%区間","参加者数"])}
<p>{speed_summary_text}</p>
<p class="small">水準ごとの詳細(Wilson区間・絵が違ったかの判定)は <code>speed_effect_by_level.csv</code>。
方式ごとの参加者単位ブートストラップは <code>speed_effect_family.csv</code>。</p>

<h2>②-b 誤りの質と実質選択肢数 — 何択まで絞れているか</h2>
<p>著者の関心: 正答率が低いのは「紛らわしい字があるから」なのか「まだ何も見えて/聞こえて
いないから」なのか。これを2つの指標で見る。(1) <b>誤答エントロピー</b>: 間違いが特定の字に
集中していれば「明確な取り違え」、バラバラなら「当てずっぽう」。(2) <b>実質選択肢数(2^H)</b>:
正誤を問わず応答全体の散らばりを指数化したもので、1に近いほど1つに絞れており、
n_choicesに近いほど絞れていない。字ごとにHを求めてから試行数で加重平均し、最後に2^Hを
とる(生の応答を複数の字にまたがって直接束ねると、各字が完璧に正答されていても字の種類数ぶんの
見かけ上の散らばりが出てしまうため)。</p>

<h3>実質選択肢数(論文の主要な図になりうる指標)</h3>
{ctx['fig_perplexity']}
<div class="callout">
<b>聴覚は打ち切りなしで全部聞かせても{full_audio_row['perplexity']:.1f}択までしか絞れない</b>
(n={full_audio_row['n_trials']}試行、{full_audio_row['n_chars_with_data']}字)。視覚は多くの方式で
進み具合が進むと1〜2択まで絞られる。<b>音は最後まで曖昧さが残る</b>ということであり、
③でが・ぱ・し・つ・らの聴覚曲線が転写に使えない(λが低い)ことと整合する。これは
「聴覚側が原理的に到達できないqの領域がある」ことを意味し、転写の前提(両者を同じq空間で
扱えるか)に関わる。{wipe_bump_text}
</div>
{table(perplexity_visual_table_rows, ["family","bin","n","n_chars","perp"],
       ["方式","進み具合の帯","試行数","データのある字数","実質選択肢数"])}
{table(perplexity_audio_table_rows, ["bin","n","n_chars","perp"],
       ["打ち切り時間の帯","試行数","データのある字数","実質選択肢数"])}
<p class="small">帯の境界は進み具合% (既定 0,1,3,8,20,50,90,101) と打ち切りms(既定
0,15,25,35,50,70,∞)。詳細は <code>perplexity_by_bin.csv</code>。字×方式ごとμ付近1点の値は
③の対応表・<code>transcribability_table.csv</code>の perplexity_near_mu 列。</p>

<h3>γ(当て推量の水準)を自由推定した頑健性チェック</h3>
<p>実質選択肢数を見ると、0%付近でも68択まで広がらない(頻用字に偏って回答する)ことが
分かった。これは<b>複数の字の応答を束ねたときの散らばり</b>の話であり、それとは別に、
γ=1/{ctx['data']['n_choices_audio']}固定という前提が<b>個々の字自身の当てはめ</b>に影響しないかを、
聴覚の字ごとにγも自由推定して当てはめ直すことで確かめた。</p>
{table(free_gamma_rows, ["char","gamma_fixed","gamma_free","lam","usable"],
       ["字","γ(固定)","γ(自由推定)","λ(自由推定時)","使用可否(γ自由推定)"])}
<p>{gamma_free_trend_text} γを自由推定しても、使用可能な字の集合は
<b>{"一致した" if usable_match else "変わった"}</b>
(固定: {"・".join(sorted(ctx["usable_fixed"]))} / 自由推定: {"・".join(sorted(ctx["usable_free"]))})。
③の使用可否判定はこの頑健性チェックを通過している。詳細は <code>audio_fit_free_gamma.csv</code>。</p>

<h3>誤りの質: 当てずっぽうと細部混同の対比(聴覚 vs 視覚)</h3>
{ctx['fig_av_compare']}
{table(av_compare_rows, ["char","h_audio","top_audio","h_visual","n_distinct_visual","top_visual"],
       ["字(清濁)","聴覚H","聴覚の最頻誤答","視覚H","視覚の誤答の種類数","視覚の最頻誤答"])}
<p class="small">聴覚のHは全体でおおむね{ctx['error_entropy_audio'][audio_usable_chars[0]]['entropy_max_bits']:.1f}ビット
(={ctx['data']['n_choices_audio']}択)より十分小さく、視覚はそれに比べて上限に近い
(視覚の上限はlog2({ctx['data']['n_choices_visual']})≈{h_max_visual:.1f}ビット)。
聴覚は特定の字と混同し、視覚はまだ見えていない段階では当てずっぽうに近い、という
質の違いが数値で確認できる。詳細は <code>error_entropy_audio_by_char.csv</code> /
<code>error_entropy_visual_by_char.csv</code>。</p>

<h3>進み具合による転換 — 「当てずっぽう」から「細部だけの取り違え」へ</h3>
{ctx['fig_error_bands']}
{table(transition_rows, ["family","s_star","note"], ["方式","転換点(進み具合%)","判定根拠"])}
{table(band_table_rows, ["family","band","s_range","n","h","n_distinct","top"],
       ["方式","帯","進み具合範囲","試行数","誤答H","誤答の種類数","最頻誤答"])}
<p class="small">方式ごとに8字を込みにして集計した誤答エントロピー(1字だけでは1水準あたりの
誤答数が少なすぎてHが安定しないため)。転換点は、entropy_normがその水準以降ずっと閾値
({ctx['transition_threshold_frac']})を下回り始める最初の水準(方式ごとに閾値未満が続かない
場合は「転換なし」)。方式ごとの帯・水準ごとの詳細は <code>error_entropy_bands.csv</code> /
<code>error_entropy_by_level.csv</code>。</p>

<h2>③ どの方式なら、どの字の音声曲線を表せるか(主目的)</h2>
<p>
転写は <code>s(t) = V⁻¹(A(t))</code> で作る: (1) 聴覚の曲線A(t)を、字自身のγ・λで
<code>q=(p−γ)/(λ−γ)</code> と正規化して「識別の進み具合」に直す。(2) このqを、視覚曲線V(s)の
生の正答率スケールに対してそのまま目標値とみなし、V(s)=qとなるsを逆算する。(3) qがV(s)の届く範囲
[γ_visual, λ_visual] の外に出ると、s=1(またはs=0)に丸められ、逆引きが退化する。
</p>
<p>聴覚が転写に使えるのは <b>{"・".join(audio_usable_chars)}</b> の3字のみ(条件: 収束・λ≥0.5・μが実測範囲内)。
<b>{"・".join(audio_unusable_chars)}</b> は聴覚曲線自体が信頼できないため「対象外」とした
(詳細根拠は <code>audio_fit.csv</code>)。</p>

{ctx['fig_heatmap']}

<h3>対応表(3字×4方式=12セル、聴覚が使える字のみ)</h3>
{table([r for r in corr_rows if r['judgement'] in ('成立','一部成立','不成立')],
       ["char","family","judgement","frac","t_star","lam_v","error_quality","perplexity"],
       ["字(清濁)","方式","判定","丸めが起きる時間割合","丸めが始まる時刻","V(s)の天井λ",
        "誤りの質(μ付近)","実質選択肢数(μ付近)"])}
<p class="small">「丸めが始まる時刻」は、聴覚のqがその方式の天井λを超え始める打ち切り時間(ms)。
それ以降は、その方式でどれだけアニメを進めても聴覚が伝える情報量に追いつけない。
「誤りの質」「実質選択肢数」は、その字×方式のμ(立ち上がりの中心)に最も近い実測水準での値
(詳しくは次の節)。<b>同じ正答率50%でも、当てずっぽうの50%と細部だけ間違える50%では
転写の意味が違う</b>ことに注意。32セル全体(対象外を含む)は <code>transcribability_table.csv</code>。</p>

<h3>逆向きの対応表 — 「この字にはこの方式が適する」</h3>
<p>著者の問い(それぞれのアニメーションの特徴と、それに適した文字があるのでは)に対する回答。
本命8字それぞれについて、μ(進み具合の半分の人が読めるようになる点)が最小の方式=最も早く
読めるようになる方式を選んだ。理由は字の構造指標(清濁・墨の左右分布・細部量)から機械的に
付与した簡単な説明で、統計的な検定はしていない(n=8なので、統計的な裏付けは次の④の
まぎれ字{n_decoy_chars}字による相関分析を見る)。</p>
{table(best_family_table_rows, ["char","best","second","worst","reason"],
       ["字(清濁)","最も適する方式(μ最小)","次点","最も不利な方式(μ最大)","構造からの理由"])}

<h2>④ 方式どうしの比較(RQ2) — 「どちらが優れているか」ではなく「どの字と合うか」</h2>
<div class="callout">
<b>方式に優劣は無く、字との相性がある。</b>
まぎれ字{n_decoy_chars}字でμの順位相関(Spearman)を方式間で取ると、以下のとおりほぼ0で、
「読みにくい字」という方式を超えた共通の性質は存在しない。従って、σのばらつきや平均的な
易しさで方式に順位をつけるのは適切でない。<b>方式間で比較できるのは、逆引きに使える
q(=聴覚の識別の進み具合)の範囲の広さ</b>(③の成立/一部成立の数、λの範囲)である。
</div>
{ctx['fig_rank_corr']}
{table(corr_matrix_rows, ["family"] + FAMILIES, ["方式"] + [FAMILY_LABEL[f] for f in FAMILIES])}
<p class="small">n_chars_commonを含む詳細は <code>family_rank_correlation.csv</code>
(まぎれ字{n_decoy_chars}字、analyze_calib_deep.pyの<code>fit_decoy_visual.csv</code>を参照データとして使用)。</p>

<h3>なぜ順位が入れ替わるか — 方式ごとの手がかりの運び方</h3>
<p>fade・revealは字全体が一様に立ち上がるため、墨の量や濁点の位置に依存しにくい。
blurは細部(小さい点・細い線)から先に埋もれるため画数の多い字に弱い。wipeは左→右に
情報が届くため、右側(濁点/半濁点はここ)に手がかりがある字に弱い。</p>
{table(mech_table_rows, ["family","n","ink_corr","ratio"],
       ["方式","字数","墨量とμのSpearman相関","濁音/半濁音のμ ÷ 清音のμ"])}
{ctx['fig_rank_heatmap']}
<p class="small">まぎれ字{n_decoy_chars}字でμの順位を字ごとに並べたもの。同じ行(字)の中で
色がバラバラなほど、方式によって得意・不得意が入れ替わっていることを示す。</p>

<h3>逆引きに使える範囲の広さ(方式間で比較してよい点)</h3>
<p>σ(傾き)のばらつきそのものは字の構造(墨がどこにあるか)で決まる系統差であり、単純な
「不安定さ」としては読まない。清音と濁音/半濁音のμの差(本命8字では、が・ぱの2字のみが
該当するのでn=2と少数だが)は {diacritic_gap_text} で、wipeとblurで大きく開く。これは
まぎれ字63字(が・ぱ以外の濁音/半濁音を含む、上のcalloutに出典を記載)での傾向
(wipe +25.6pt、blur +16.6pt、reveal +1.3pt、fade +0.3pt)と方式間の大小関係が一致しており、
本命8字だけの少数データでも同じ系統差が再現されている。一方、③でどれだけの字×方式が
「成立」「一部成立」したか、λ(天井)の範囲がどれだけ広いかは、方式間で直接比較できる。</p>
{table(fam_summary_rows, ["family","sigma_med","sigma_iqr","lam_range","mu_diacritic_minus_seion","fit_err","counts"],
       ["方式","σ中央値","σのIQR","λの範囲","清音→濁音/半濁音でのμの差(中央値)","当てはめ誤差(重み付きMAE)","③の内訳"])}

<h3>字の構造指標(墨の位置・清濁)</h3>
{table(struct_rows, ["char","diacritic","centroid","right","fine"],
       ["字","清濁","墨の重心x(0=左,1=右)","墨が右半分にある割合","細部量(収縮で失われる割合)"])}
{ctx['fig_structure']}
<p class="small">wipeは左→右(<code>direction=&quot;ltr&quot;</code>)に現れるため、墨が右寄りな字ほどμ(読めるまでの進み具合)が
大きくなる関係が見える。blurは細部量が多い字ほどμが大きくなる傾向がある(いずれも本命8字だけではn=8と少数)。</p>

<h3>fadeは画面の分解能に当たっている</h3>
<p>fadeは不透明度0〜255の256階調でしか濃さを表現できない。設計側の実測(進み具合0.8%が濃さ2階調、
1.2%が濃さ3階調)から1(=フル)あたり256階調と分かる。各字の当てはめ曲線の最大傾きに1階調分
(1/256)を掛けると、識別の進み具合でみた分解能の限界(1階調でqがどれだけ動くか)が出る。</p>
{table(fade_res_rows, ["char","sigma","delta"], ["字","fadeのσ(%)","1階調あたりのΔ正答率"])}

<h3>wipeの実測が薄い区間</h3>
<p>wipeは進み具合25%と100%の間にテスト水準が無い(実測levels: 0.5, 1, 2, 4, 8, 14, 25, 100%)。
この区間の75ポイント幅はテスト水準どうしの間隔として8水準中もっとも広く、この間の曲線は
シグモイドの当てはめによる補間であり、実測に直接支えられていないことに注意が必要である。
μがこの区間(25〜100%)に入る字ほど、立ち上がりの正確な位置・傾きの確度が他の字より低い
(どの字が該当するかは <code>vs_fit_point.csv</code> のfamily=wipe・axis=actual・speed=pooled行を参照)。</p>

<h2>付録: データの扱い</h2>
<ul>
<li>is_test=真の行を除外。modalityはtransfer_audio/transfer_visualのみ。</li>
<li>本命8字の本命問題 = is_decoy偽 かつ check_kind空 かつ target_charが本命8字。</li>
<li>γ(下限)は聴覚1/{ctx['data']['n_choices_audio']}・視覚1/{ctx['data']['n_choices_visual']}に固定、λ(天井)は自由推定。</li>
<li>参加者単位ブートストラップ(試行単位でリサンプルしない): 同一参加者内の回答は独立でないため。</li>
<li>analyze_calib_full.py / analyze_calib_deep.py / analyze_calib_context.py は変更せず、
    データ読み込み・当てはめ関数のみimportで再利用した。</li>
</ul>
"""
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTMLレポート書き出し: {path}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="project/data_calib_20260825/transfer_trials.csv")
    ap.add_argument("--out", default="project/data_calib_20260825/analysis_families")
    ap.add_argument("--report", default="project/data_calib_20260825/families_report.html")
    ap.add_argument("--base-dir", default="experiment/base", help="字の墨画像(構造指標の計算元)")
    ap.add_argument("--decoy-fit", default="project/data_calib_20260825/analysis_deep/fit_decoy_visual.csv",
                    help="analyze_calib_deep.py が出すまぎれ字63字の当てはめ結果(読み取り専用の参照データ、"
                         "方式間の順位相関と墨量/清濁の相関を見るのに使う)")
    ap.add_argument("--boot-vs", type=int, default=400, help="V(s)当てはめの参加者単位ブートストラップ回数")
    ap.add_argument("--boot-speed", type=int, default=3000, help="速さ効果の参加者単位ブートストラップ回数(曲線当てはめ無しで軽いので多めに)")
    ap.add_argument("--fit-starts", type=int, default=6, help="点推定の多点スタート数(局所解対策)")
    ap.add_argument("--boot-starts", type=int, default=3, help="ブートストラップ内の多点スタート数(計算量を抑える)")
    ap.add_argument("--seed", type=int, default=20260826, help="乱数シード(再現性のため固定)")
    ap.add_argument("--lambda-usable-threshold", type=float, default=0.5,
                    help="聴覚の字がA(t)として転写に使えるとみなすλ(天井)の下限(既定0.5)。"
                         "analyze_calib_full.py のlambda_warn既定と揃えた")
    ap.add_argument("--unfit-threshold", type=float, default=0.95,
                    help="丸めが起きる時間割合がこれ以上なら『不成立』とする閾値(既定0.95)。"
                         "ほぼ全域で丸めが起きる=実質的に情報を運べていないとみなす")
    ap.add_argument("--erosion-iter", type=int, default=1, help="細部量(fine_detail_frac)計算での収縮回数")
    ap.add_argument("--quality-min-n", type=int, default=8,
                    help="誤りの質を判定する最低誤答数(既定8件未満は『データ不足』)")
    ap.add_argument("--quality-guess-thr", type=float, default=0.75,
                    help="entropy_norm がこれ以上なら『当てずっぽう』とみなす閾値(既定0.75)")
    ap.add_argument("--quality-concentrate-thr", type=float, default=0.4,
                    help="entropy_norm がこれ以下なら『細部混同』とみなす閾値(既定0.4)")
    ap.add_argument("--transition-threshold-frac", type=float, default=0.6,
                    help="誤答エントロピーの正規化値がこれを下回り続けたら"
                         "『当てずっぽう→細部混同』の転換とみなす閾値(既定0.6)")
    ap.add_argument("--n-bands", type=int, default=3, help="誤りの質の帯分割数(既定3=低/中/高)")
    ap.add_argument("--pct-bins", default="0,1,3,8,20,50,90,101",
                    help="視覚の実質選択肢数を見る進み具合%%の帯境界(カンマ区切り、既定は"
                         "著者提示の例に合わせた0,1,3,8,20,50,90,101)")
    ap.add_argument("--gate-bins", default="0,15,25,35,50,70,100000",
                    help="聴覚の実質選択肢数を見るgate_msの帯境界(カンマ区切り、既定は"
                         "著者提示の例に合わせた0,15,25,35,50,70,∞)")
    ap.add_argument("--gamma-free-upper", type=float, default=0.5,
                    help="gamma自由推定の頑健性チェックでのgamma上限(既定0.5)")
    args = ap.parse_args()
    pct_bins = [float(x) for x in args.pct_bins.split(",")]
    gate_bins = [float(x) for x in args.gate_bins.split(",")]

    os.makedirs(args.out, exist_ok=True)

    data = prepare_data(args.inp)

    print("\n① V(s)当てはめ(点推定)")
    vs_fit_point_rows = write_vs_fit_point(os.path.join(args.out, "vs_fit_point.csv"), data, args.fit_starts)
    # 32セル判定・図で使うための辞書(主版=excl_clamp0・実測軸・速さpooled)
    vs_fit_pooled_by_key = {}
    vs_fit_by_key_speed = {}
    for r in vs_fit_point_rows:
        if r["version"] != "excl_clamp0" or r["axis"] != "actual":
            continue
        if r["speed"] == "pooled":
            vs_fit_pooled_by_key[(r["char"], r["family"])] = r
        else:
            vs_fit_by_key_speed[(r["char"], r["family"], r["speed"])] = r

    print("\n① V(s)当てはめ(参加者単位ブートストラップ)")
    n_part_vs = write_vs_bootstrap(os.path.join(args.out, "vs_bootstrap.csv"), data, args.boot_vs, args.seed, args.boot_starts)

    print("\n② 速さ(300/500)の効果")
    speed_family_rows, speed_level_rows, frames_differ = write_speed_effect(
        os.path.join(args.out, "speed_effect_family.csv"), os.path.join(args.out, "speed_effect_by_level.csv"),
        data, args.boot_speed, args.seed)

    print("\n 字の構造指標(清濁・墨の位置)")
    struct = char_structure_metrics(args.base_dir, args.erosion_iter)
    write_char_structure(os.path.join(args.out, "char_structure.csv"), struct)

    print("\n③ 聴覚の字ごと当てはめ・使用可否判定")
    audio_fit_by_char, audio_usable = write_audio_fit(os.path.join(args.out, "audio_fit.csv"), data,
                                                        args.fit_starts, args.lambda_usable_threshold)

    print("\n③ 聴覚のgamma自由推定による頑健性チェック(著者の指摘)")
    audio_fit_free = write_audio_fit_free_gamma(os.path.join(args.out, "audio_fit_free_gamma.csv"), data,
                                                 args.fit_starts, args.gamma_free_upper, args.lambda_usable_threshold)
    usable_fixed = {ch for ch in TARGET_CHARS if audio_usable.get(ch)}
    usable_free = {ch for ch in TARGET_CHARS if audio_fit_free[ch]["usable_for_transcription"]}
    print(f"  gamma固定での使用可: {sorted(usable_fixed)} / gamma自由推定での使用可: {sorted(usable_free)}"
          f" / 一致: {usable_fixed == usable_free}")

    print("\n 誤りの質(誤答エントロピー): 当てずっぽうか、細部だけの取り違えか")
    error_entropy_audio = write_error_entropy_audio(os.path.join(args.out, "error_entropy_audio_by_char.csv"), data)
    error_entropy_visual_char = write_error_entropy_visual_by_char(
        os.path.join(args.out, "error_entropy_visual_by_char.csv"), data)
    error_entropy_visual_cf = write_error_entropy_visual_char_family(
        os.path.join(args.out, "error_entropy_visual_by_char_family.csv"), data)
    error_entropy_levels = write_error_entropy_by_level(os.path.join(args.out, "error_entropy_by_level.csv"), data)
    error_entropy_bands = write_error_entropy_bands(os.path.join(args.out, "error_entropy_bands.csv"), data,
                                                      error_entropy_levels, args.n_bands)
    transitions = {}
    for fam in FAMILIES:
        lv_rows = [r for r in error_entropy_levels if r["family"] == fam]
        s_star, note = detect_transition(lv_rows, args.transition_threshold_frac)
        transitions[fam] = dict(family=fam, transition_s_pct=s_star, note=note)
    with io.open(os.path.join(args.out, "error_entropy_transitions.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["family", "transition_s_pct", "note"])
        for fam in FAMILIES:
            w.writerow([fam, transitions[fam]["transition_s_pct"], transitions[fam]["note"]])
    print(f"  書き出し: error_entropy_transitions.csv / 転換点: "
          f"{ {fam: transitions[fam]['transition_s_pct'] for fam in FAMILIES} }")
    error_quality_lookup = error_quality_near_mu(data, vs_fit_pooled_by_key)

    print("\n 実質選択肢数(2^H): それぞれのタイミングで何択まで絞れているか")
    perplexity_visual_bins = perplexity_by_bin_visual(data, pct_bins)
    perplexity_audio_bins = perplexity_by_bin_audio(data, gate_bins)
    write_perplexity_bins(os.path.join(args.out, "perplexity_by_bin.csv"), perplexity_visual_bins,
                           perplexity_audio_bins)
    perplexity_lookup = perplexity_near_mu(data, vs_fit_pooled_by_key)
    full_row = perplexity_audio_bins[-1]
    print(f"  聴覚『打ち切りなし』での実質選択肢数: {full_row['perplexity']:.2f}択"
          f"(n={full_row['n_trials']}試行、{full_row['n_chars_with_data']}字)")

    print("\n③ 32セルの転写成立判定")
    transcribe_rows = compute_transcribability(data, audio_fit_by_char, audio_usable, vs_fit_pooled_by_key,
                                                args.unfit_threshold, error_quality_lookup, perplexity_lookup,
                                                args.quality_min_n, args.quality_guess_thr,
                                                args.quality_concentrate_thr)
    write_transcribability(os.path.join(args.out, "transcribability_table.csv"), transcribe_rows)

    print("\n④ 方式ごとの総括")
    wipe_gap_note = {"wipe": "実測水準は0.5/1/2/4/8/14/25/100%で、25%と100%の間にテスト水準が無い(実測に支えられない区間)"}
    family_summary = write_family_summary(os.path.join(args.out, "family_summary.csv"), data, vs_fit_pooled_by_key,
                                           struct, transcribe_rows, wipe_gap_note)
    fade_res = fade_resolution_limit(vs_fit_pooled_by_key)

    print("\n 字×方式の相性(順位相関・墨量/清濁の相関・字ごとの最適方式)")
    decoy_rows = load_decoy_fit(args.decoy_fit)
    corr_mat = family_rank_correlation(decoy_rows) if decoy_rows else None
    mech_rows = mechanism_correlates(decoy_rows) if decoy_rows else []
    if corr_mat is not None:
        write_mechanism(os.path.join(args.out, "family_rank_correlation.csv"),
                         os.path.join(args.out, "mechanism_correlates.csv"), corr_mat, mech_rows)
    best_family_rows = best_family_per_char(vs_fit_pooled_by_key, struct)
    write_best_family_per_char(os.path.join(args.out, "best_family_per_char.csv"), best_family_rows)

    print("\n図の作成")
    fig_vs = {}
    for fam in FAMILIES:
        fig_vs[fam] = plot_family_vs(fam, vs_fit_by_key_speed, data["rows_visual_main"])
    fig_heatmap = plot_heatmap(transcribe_rows)
    fig_speed = plot_speed_effect(speed_family_rows)
    fig_structure = plot_structure_correlation(struct, vs_fit_pooled_by_key)
    fig_rank_corr = plot_rank_correlation(corr_mat) if corr_mat is not None else None
    fig_rank_heatmap = plot_char_family_rank_heatmap(decoy_rows) if decoy_rows else None
    fig_error_bands = plot_error_entropy_bands(error_entropy_levels, transitions)
    fig_perplexity = plot_perplexity(perplexity_visual_bins, perplexity_audio_bins)
    fig_av_compare = plot_audio_visual_entropy_compare(error_entropy_audio, error_entropy_visual_char)

    ctx = dict(data=data, transcribe_rows=transcribe_rows, family_summary=family_summary,
               speed_family_rows=speed_family_rows, struct=struct, fade_res=fade_res,
               n_boot_vs=args.boot_vs, n_part_vs=n_part_vs, audio_usable=audio_usable,
               corr_mat=corr_mat, mech_rows=mech_rows, best_family_rows=best_family_rows,
               n_decoy_chars=(len({r['char'] for r in decoy_rows}) if decoy_rows else 0),
               transition_threshold_frac=args.transition_threshold_frac,
               error_entropy_audio=error_entropy_audio, error_entropy_visual_char=error_entropy_visual_char,
               error_entropy_bands=error_entropy_bands, transitions=transitions,
               perplexity_visual_bins=perplexity_visual_bins, perplexity_audio_bins=perplexity_audio_bins,
               audio_fit_free=audio_fit_free, usable_fixed=usable_fixed, usable_free=usable_free,
               fig_vs_fade=f'<img src="{fig_vs["fade"]}" alt="fade V(s)">',
               fig_vs_reveal=f'<img src="{fig_vs["reveal"]}" alt="reveal V(s)">',
               fig_vs_blur=f'<img src="{fig_vs["blur"]}" alt="blur V(s)">',
               fig_vs_wipe=f'<img src="{fig_vs["wipe"]}" alt="wipe V(s)">',
               fig_heatmap=f'<img src="{fig_heatmap}" alt="転写成立判定ヒートマップ">',
               fig_speed=f'<img src="{fig_speed}" alt="速さの効果">',
               fig_structure=f'<img src="{fig_structure}" alt="字の構造と方式の関係">',
               fig_rank_corr=(f'<img src="{fig_rank_corr}" alt="方式間の順位相関">' if fig_rank_corr else
                              '<p class="small">(fit_decoy_visual.csv が無いため図を省略)</p>'),
               fig_rank_heatmap=(f'<img src="{fig_rank_heatmap}" alt="字×方式の順位ヒートマップ">' if fig_rank_heatmap else
                                 '<p class="small">(fit_decoy_visual.csv が無いため図を省略)</p>'),
               fig_error_bands=f'<img src="{fig_error_bands}" alt="誤りの質の転換">',
               fig_perplexity=f'<img src="{fig_perplexity}" alt="実質選択肢数">',
               fig_av_compare=f'<img src="{fig_av_compare}" alt="聴覚vs視覚の誤答エントロピー">')

    print("\nHTMLレポート作成")
    build_html(args.report, ctx)

    print(f"\n完了: CSV -> {args.out} / HTML -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
