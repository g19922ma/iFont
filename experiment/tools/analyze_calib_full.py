#!/usr/bin/env python3
"""
較正フェーズ(transfer_trials.csv) の本解析
==============================================================
project/data_calib_20260825/transfer_trials.csv (253人・18689行) を読み、
本命8字(あ・か・が・ぱ・し・つ・ま・ら)について、
「打ち切り時間 t / 進み具合」から正答率へのシグモイド曲線を字ごとに当てはめる。
その他、確認問題による刺激の妥当性チェック、切り方を変えた感度分析、
参加者単位のブートストラップによる不確かさの推定までを行う。

出力(既定 project/data_calib_20260825/analysis/):
  curves_audio.csv         聴覚: 字 × 打ち切りms の正答数・試行数・正答率
  curves_visual.csv        視覚: 字 × 方式 × 水準(名目/実測) の正答数・試行数・正答率
  fit_logistic.csv         字ごと(聴覚)/字×方式ごと(視覚)のシグモイド当てはめ
  confusion_audio.csv      確認問題A(full)での聴覚の混同行列
  confusion_visual.csv     確認問題A(full)での視覚の混同行列
  confusion_seion_dakuon.csv  確認問題A(full)での清濁(半濁)の取り違えだけを抜き出した表
  checks.csv                字ごとの確認問題A(full)・確認問題C(floor)の正答率
  sensitivity.csv           切り方を変えたときの μ の動き
  bootstrap.csv              参加者単位ブートストラップによる μ・λ の95%区間

使い方
------
  python3 experiment/tools/analyze_calib_full.py \
      --in project/data_calib_20260825/transfer_trials.csv \
      --out project/data_calib_20260825/analysis \
      --boot 1000

除外する行
----------
  ・is_test が真の行(動作確認)。
  ・practice 列がもし入力に存在すれば、それが真の行(下見用の短縮CSVにはこの列自体が無いことがある)。
    ⚠ この入力(transfer_trials.csv 2026-08-25版)には practice 列自体が無い。
      列が無い入力ではこの条件は何もしない(全行を素通りさせる)。列が後から
      足された入力を渡しても自動的に効くよう、列の有無で分岐させてある。
  ・modality が transfer_audio / transfer_visual 以外の行(実験後アンケート
    transfer_post_survey や気づき調査 transfer_awareness は、target_char に
    ダミー値 "-" が入るなど本題とは別物なので、最初に落としておく)。

「本命8字の本命問題」は、上の除外のあとさらに
  is_decoy が偽 かつ check_kind が空 かつ target_char が本命8字
に絞ったものを指す(is_decoy が偽でも check_kind が空でも、本命8字以外の
字が来ることは無い設計だが、思い込みで断定せず実データで確認したうえで
念のため字でも絞っている)。
"""
import argparse
import csv
import io
import math
import os
import sys
from collections import defaultdict, Counter

import numpy as np

try:
    from scipy.optimize import minimize
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False


TARGET_CHARS = list("あかがぱしつまら")  # 本命8字(計画書の表記順)

# 清音/濁音/半濁音の組。た行の「ぢ」「づ」も含めて50音の対応をすべて挙げる。
# 3つ組(は行)は (清音, 濁音, 半濁音) の順。
SEION_GROUPS = [
    ("か", "が"), ("き", "ぎ"), ("く", "ぐ"), ("け", "げ"), ("こ", "ご"),
    ("さ", "ざ"), ("し", "じ"), ("す", "ず"), ("せ", "ぜ"), ("そ", "ぞ"),
    ("た", "だ"), ("ち", "ぢ"), ("つ", "づ"), ("て", "で"), ("と", "ど"),
    ("は", "ば", "ぱ"), ("ひ", "び", "ぴ"), ("ふ", "ぶ", "ぷ"),
    ("へ", "べ", "ぺ"), ("ほ", "ぼ", "ぽ"),
]
CHAR_GROUP = {}
CHAR_TYPE = {}
for _gi, _g in enumerate(SEION_GROUPS):
    _labels = ("seion", "dakuon") if len(_g) == 2 else ("seion", "dakuon", "handakuon")
    for _ch, _lab in zip(_g, _labels):
        CHAR_GROUP[_ch] = _gi
        CHAR_TYPE[_ch] = _lab


# ---------------------------------------------------------------------------
# 読み込み・正規化
# ---------------------------------------------------------------------------
def truthy(v):
    return str(v).strip().upper() in ("1", "TRUE", "T", "YES")


def numf(v):
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load(path):
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def normalize(rows):
    """使う列をあらかじめ型変換しておく。元の文字列列はそのまま残す。"""
    for r in rows:
        r["is_test_b"] = truthy(r.get("is_test"))
        r["is_decoy_b"] = truthy(r.get("is_decoy"))
        r["correct_b"] = truthy(r.get("correct"))
        r["check_kind"] = (r.get("check_kind") or "").strip()
        r["family"] = (r.get("family") or "").strip()
        r["gate_ms"] = numf(r.get("gate_ms"))
        r["progress_pct"] = numf(r.get("progress_pct"))
        r["actual_s"] = numf(r.get("actual_s"))
        r["rt_ms"] = numf(r.get("rt_ms"))
        r["refresh_hz"] = numf(r.get("refresh_hz"))
        r["resume_count"] = numf(r.get("resume_count")) or 0.0
        r["replays"] = numf(r.get("replays")) or 0.0
        r["n_choices"] = numf(r.get("n_choices"))
        r["modality_g"] = "audio" if r.get("group") == "acal" else (
            "visual" if r.get("group") == "aprime" else "")
        stim_tail = (r.get("stimulus_id") or "").split("|")[-1]
        r["stim_tail"] = stim_tail
        # 聴覚の主系列(較正のはしご)に埋め込まれた「打ち切りなし」試行。
        # gate_ms が空で stimulus_id の末尾が "full"。確認問題(check_kind=="full")とは別物 --
        # 確認問題は専用のブロックとして別途 check_kind 列に記録されているのに対し、
        # これは通常の較正試行列の中に混ぜて出題されたもの(1人24問中3問)。
        # 実際に鳴らした音声の長さ(ms)は記録されていないので、シグモイドの数値軸には乗せられない。
        r["is_embedded_full"] = (r["modality_g"] == "audio" and stim_tail == "full"
                                  and r["gate_ms"] is None)
    return rows


def base_filter(rows):
    """is_test・(あれば)practice・対象外モダリティを外す。戻り値は残った行。"""
    has_practice_col = bool(rows) and ("practice" in rows[0])
    n_test = n_practice = n_other_mod = 0
    out = []
    for r in rows:
        if r["is_test_b"]:
            n_test += 1
            continue
        if has_practice_col and truthy(r.get("practice")):
            n_practice += 1
            continue
        if r.get("modality") not in ("transfer_audio", "transfer_visual"):
            n_other_mod += 1
            continue
        out.append(r)
    print(f"  base_filter: is_test={n_test}件, practice={n_practice}件"
          f"({'列あり' if has_practice_col else '列なし・素通り'}), "
          f"対象外モダリティ={n_other_mod}件 を除外 / 残り{len(out)}行")
    return out


def main_target_rows(rows):
    """本命8字の本命問題: is_decoyが偽 かつ check_kindが空 かつ 対象8字。"""
    return [r for r in rows
            if (not r["is_decoy_b"]) and (not r["check_kind"]) and (r["target_char"] in TARGET_CHARS)]


def default_gamma(rows, modality_g):
    """n_choices列の最頻値から 1/n_choices を作る。8/72等の数値を勝手に書かないため。"""
    vals = [r["n_choices"] for r in rows if r["modality_g"] == modality_g and r["n_choices"]]
    if not vals:
        return None, None
    n = Counter(vals).most_common(1)[0][0]
    return 1.0 / n, int(n)


# ---------------------------------------------------------------------------
# シグモイド当てはめ
# ---------------------------------------------------------------------------
def _nll_factory(xs, ks, ns, gamma):
    eps = 1e-9

    def nll(params):
        lam, mu, sigma = params
        sigma = max(sigma, 1e-6)
        z = np.clip(-(xs - mu) / sigma, -500, 500)
        p = gamma + (lam - gamma) / (1.0 + np.exp(z))
        p = np.clip(p, eps, 1 - eps)
        return -float(np.sum(ks * np.log(p) + (ns - ks) * np.log(1 - p)))

    return nll


def fit_sigmoid(xs, ks, ns, gamma, n_starts=6):
    """
    p(x) = gamma + (lambda-gamma) / (1+exp(-(x-mu)/sigma)) を二項最尤で当てはめる。

    gamma(下限)は固定、lambda(上限)は自由推定 -- 刺激の不出来で天井に届かない字が
    実在する(が、など)ので、上限を1に固定すると「立ち上がりが遅い」のか
    「そもそも当て推量から上に行かない」のかを区別できなくなる。lambdaを自由にして
    はじめて、この2つを別の現象として取り出せる。

    xs,ks,ns: 提示水準ごとの (水準値, 正答数, 試行数)。長さが同じ配列。
    n_starts: 初期値を変えて最適化をやり直す回数(局所解対策)。
    戻り値: dict(lam,mu,sigma,converged,note,nll,n_trials,n_levels)
    """
    xs = np.asarray(xs, dtype=float)
    ks = np.asarray(ks, dtype=float)
    ns = np.asarray(ns, dtype=float)
    n_trials = int(ns.sum())
    n_levels = int(len(xs))

    if n_levels == 0 or n_trials == 0:
        return dict(lam=float("nan"), mu=float("nan"), sigma=float("nan"),
                     converged=False, note="データなし", nll=float("nan"),
                     n_trials=0, n_levels=0)

    xlo, xhi = float(xs.min()), float(xs.max())
    rng = xhi - xlo
    if n_levels < 2 or rng <= 0:
        # 水準が1つしかない(またはxの幅がゼロ)ときは mu・sigma が原理的に決まらない。
        # 観測正答率だけを lambda の代わりに残し、当てはめ不可であることを note に書く。
        acc = float(ks.sum() / ns.sum())
        return dict(lam=acc, mu=float("nan"), sigma=float("nan"), converged=False,
                     note="水準が1つしかなく mu・sigma は推定不可(観測正答率のみ)",
                     nll=float("nan"), n_trials=n_trials, n_levels=n_levels)

    nll = _nll_factory(xs, ks, ns, gamma)
    acc_by_level = ks / np.maximum(ns, 1)
    lam0 = float(np.clip(acc_by_level.max(), gamma + 0.02, 0.999))
    mu_candidates = sorted(set(np.percentile(xs, [15, 30, 50, 70, 85]).tolist()))[:max(1, n_starts)]
    sigma_candidates = [rng * f for f in (0.05, 0.15, 0.35, 0.7)][:max(1, min(4, n_starts))]

    if HAVE_SCIPY:
        bounds = [(0.0, 1.0), (xlo - rng, xhi + rng), (max(rng * 1e-3, 1e-6), rng * 8)]
        best = None
        for mu0 in mu_candidates:
            for s0 in sigma_candidates:
                try:
                    res = minimize(nll, [lam0, mu0, s0], method="L-BFGS-B", bounds=bounds)
                except Exception:
                    continue
                if best is None or res.fun < best.fun:
                    best = res
        if best is None:
            return dict(lam=float("nan"), mu=float("nan"), sigma=float("nan"),
                         converged=False, note="最適化が例外で失敗",
                         nll=float("nan"), n_trials=n_trials, n_levels=n_levels)
        lam, mu, sigma = (float(v) for v in best.x)
        notes = []
        if not best.success:
            notes.append(f"収束せず: {best.message}")
        if abs(mu - bounds[1][0]) < 1e-6 or abs(mu - bounds[1][1]) < 1e-6:
            notes.append("muが探索範囲の端(データの外でしか立ち上がりが説明できない)")
        if abs(sigma - bounds[2][1]) < 1e-6:
            notes.append("sigmaが上限に張り付き(傾きが定まらない)")
        if abs(sigma - bounds[2][0]) < 1e-6:
            notes.append("sigmaが下限に張り付き(階段状の急変化、この値より鋭い可能性)")
        return dict(lam=lam, mu=mu, sigma=sigma, converged=bool(best.success),
                     note=";".join(notes), nll=float(best.fun),
                     n_trials=n_trials, n_levels=n_levels)

    # scipy が無い環境向けの自前の探索(粗いグリッド)。
    # 「収束しなかったら黙って通さない」の精神から、ここも converged を明示して残す。
    lam_grid = np.linspace(gamma, 1.0, 25)
    mu_grid = np.linspace(xlo - rng * 0.5, xhi + rng * 0.5, 41)
    sigma_grid = np.geomspace(max(rng * 0.02, 1e-3), rng * 3, 20)
    best_val, best_params = float("inf"), None
    for lam in lam_grid:
        for mu in mu_grid:
            for sigma in sigma_grid:
                v = nll((lam, mu, sigma))
                if v < best_val:
                    best_val, best_params = v, (lam, mu, sigma)
    lam, mu, sigma = best_params
    return dict(lam=float(lam), mu=float(mu), sigma=float(sigma), converged=True,
                note="scipy無し: 粗いグリッド探索(自前実装、精度はscipy版より粗い)",
                nll=float(best_val), n_trials=n_trials, n_levels=n_levels)


def aggregate_levels(rows, level_key):
    """行の列 level_key を水準として (xs, ks, ns) にまとめる。level_key の値がNoneの行は無視。"""
    tab = defaultdict(lambda: [0, 0])
    for r in rows:
        x = r.get(level_key)
        if x is None:
            continue
        tab[x][1] += 1
        tab[x][0] += 1 if r["correct_b"] else 0
    xs = sorted(tab.keys())
    ks = [tab[x][0] for x in xs]
    ns = [tab[x][1] for x in xs]
    return xs, ks, ns


# ---------------------------------------------------------------------------
# 1. 素の正答率表
# ---------------------------------------------------------------------------
def write_curves_audio(path, rows_audio_main):
    """字 × 打ち切り時点 の正答数・試行数・正答率。埋め込みの打ち切りなし試行は
    level="full" という別枠として同じ表に残す(数値軸には混ぜない)。"""
    tab = defaultdict(lambda: [0, 0])
    for r in rows_audio_main:
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


def write_curves_visual(path, rows_visual_main):
    """
    字 × 方式 × 水準 の正答数・試行数・正答率。

    ⚠ 視覚は必ず方式(family)ごとに分ける。同じ「進み具合25%」でも fade では
    ほぼ字が読める天井付近、blur では逆に何も見えない床付近にあたり、方式を
    混ぜて束ねると「25%の正答率」が方式間で意味の違うものの平均になり
    解釈できなくなる。

    水準は axis 列で progress_pct(狙った名目値) と actual_s(実際に出た値、%換算)
    の両方を出す。名目値は「割付けた値の記録」であって、60Hzの端末では1フレーム
    16.7ms刻みの量子化で実効的に潰れる水準があるため、解析(このあとのシグモイド
    当てはめ)は実測値を主軸にする(下の write_fit_logistic のコメント参照)。
    ここではその両方を比較できるよう並べて出す。
    """
    tab_nom = defaultdict(lambda: [0, 0])
    tab_act = defaultdict(lambda: [0, 0])
    for r in rows_visual_main:
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


# ---------------------------------------------------------------------------
# 2. シグモイド当てはめ + λの実測(埋め込みfull/100%)との突き合わせ
# ---------------------------------------------------------------------------
def observed_full_audio(rows_audio_main):
    """字ごとの、聴覚の埋め込み「打ち切りなし」試行の正答率(=λの実測値)。"""
    tab = defaultdict(lambda: [0, 0])
    for r in rows_audio_main:
        if r["is_embedded_full"]:
            tab[r["target_char"]][1] += 1
            tab[r["target_char"]][0] += 1 if r["correct_b"] else 0
    return {ch: (ok, n) for ch, (ok, n) in tab.items()}


def observed_full_visual(rows_visual_main):
    """字×方式ごとの、視覚の進み具合100%(=見た目のフル表示)試行の正答率(=λの実測値)。"""
    tab = defaultdict(lambda: [0, 0])
    for r in rows_visual_main:
        if r["progress_pct"] == 100:
            k = (r["target_char"], r["family"])
            tab[k][1] += 1
            tab[k][0] += 1 if r["correct_b"] else 0
    return {k: (ok, n) for k, (ok, n) in tab.items()}


def write_fit_logistic(path, rows_audio_main, rows_visual_main, gamma_audio, gamma_visual,
                        visual_axis, n_starts, lambda_warn, lambda_diff_warn):
    """
    字ごと(聴覚)/字×方式ごと(視覚)にシグモイドを当てはめる。

    lambda_observed_full / n_full は、当てはめとは独立に「打ち切りなしで見せた/
    聞かせたときの生の正答率」を字ごとに直接測った値。推定λ(fit)と並べることで、

      - 実測fullも推定λも低い   → 刺激そのものが壊れている疑い(例: が)
      - 実測fullは高いのに推定λだけ低い → 曲線の形の当てはめの問題(データが
        天井付近まで届いていない/水準が粗い、など)の疑い

    という切り分けができる。どちらも刺激ではなく推定手続きの問題である可能性を
    否定はできないため、あくまで「疑い」を note に書き残すだけにとどめる。
    """
    full_audio = observed_full_audio(rows_audio_main)
    full_visual = observed_full_visual(rows_visual_main)

    rows_out = []

    # --- 聴覚: 字ごと、xは gate_ms (埋め込みfullはxが無いので数値当てはめには使わない) ---
    for ch in TARGET_CHARS:
        sub = [r for r in rows_audio_main if r["target_char"] == ch and not r["is_embedded_full"]]
        xs, ks, ns = aggregate_levels(sub, "gate_ms")
        fit = fit_sigmoid(xs, ks, ns, gamma_audio, n_starts=n_starts)
        ok_f, n_f = full_audio.get(ch, (0, 0))
        lam_obs = ok_f / n_f if n_f else float("nan")
        note = fit["note"]
        note = _augment_note_with_full(note, fit["lam"], lam_obs, n_f, lambda_warn, lambda_diff_warn)
        rows_out.append(dict(modality="audio", char=ch, family="", axis="gate_ms",
                              gamma=gamma_audio, lam=fit["lam"], mu=fit["mu"], sigma=fit["sigma"],
                              converged=fit["converged"], n_trials=fit["n_trials"], note=note,
                              lambda_observed_full=lam_obs, n_full=n_f))

    # --- 視覚: 字×方式ごと、xは実測(actual_s)を主軸にする ---
    #
    # ⚠ 実測(actual_s)を使う理由: 60Hzの画面は1/60秒=16.7ms刻みでしか描き替わらないので、
    # 「進み具合17%を指定した」つもりでも実際に見えるのは端末のリフレッシュレートに
    # 量子化された値になる(60Hzなら5.6%刻み、120Hzなら2.8%刻み)。名目値のまま束ねると、
    # 実際には違う量が見えていた試行を同じ点として混ぜてしまう。生成(曲線の逆引きで
    # アニメの進み方を決める)でも実測軸を使う設計方針(project/実験計画書_1文字課題.md)
    # に、この解析の主軸もそろえた。名目値との差は sensitivity.csv のcut=nominal_vs_actual
    # で別途比較できるようにしてある(--visual-axis nominal で全体を切り替えることもできる)。
    level_key = "actual_s_pct" if visual_axis == "actual" else "progress_pct"
    for r in rows_visual_main:
        r["actual_s_pct"] = round(r["actual_s"] * 100, 4) if r["actual_s"] is not None else None

    families = sorted({r["family"] for r in rows_visual_main if r["family"]})
    for ch in TARGET_CHARS:
        for fam in families:
            sub = [r for r in rows_visual_main if r["target_char"] == ch and r["family"] == fam]
            xs, ks, ns = aggregate_levels(sub, level_key)
            fit = fit_sigmoid(xs, ks, ns, gamma_visual, n_starts=n_starts)
            ok_f, n_f = full_visual.get((ch, fam), (0, 0))
            lam_obs = ok_f / n_f if n_f else float("nan")
            note = fit["note"]
            note = _augment_note_with_full(note, fit["lam"], lam_obs, n_f, lambda_warn, lambda_diff_warn)
            rows_out.append(dict(modality="visual", char=ch, family=fam, axis=level_key,
                                  gamma=gamma_visual, lam=fit["lam"], mu=fit["mu"], sigma=fit["sigma"],
                                  converged=fit["converged"], n_trials=fit["n_trials"], note=note,
                                  lambda_observed_full=lam_obs, n_full=n_f))

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["modality", "char", "family", "axis", "gamma", "lambda", "mu", "sigma",
                     "converged", "n_trials", "note", "lambda_observed_full", "n_full"])
        for r in rows_out:
            w.writerow([r["modality"], r["char"], r["family"], r["axis"],
                        round(r["gamma"], 5) if r["gamma"] is not None else "",
                        _fmt(r["lam"]), _fmt(r["mu"]), _fmt(r["sigma"]),
                        r["converged"], r["n_trials"], r["note"],
                        _fmt(r["lambda_observed_full"]), r["n_full"]])
    return rows_out


def _fmt(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return round(v, 5)


def _augment_note_with_full(note, lam_fit, lam_obs, n_full, lambda_warn, lambda_diff_warn):
    """推定λと実測fullの食い違い・両者とも低い/片方だけ低いを note に書き足す。

    しきい値(lambda_warn, lambda_diff_warn)は判断の要る数値なので引数で受け取る。
    既定値の根拠は argparse のhelpに書いた。
    """
    parts = [note] if note else []
    if n_full == 0:
        parts.append("full実測データなし")
        return ";".join(p for p in parts if p)
    if math.isnan(lam_fit):
        parts.append("mu/sigma未定のためlambda推定とfull実測の比較不可")
        return ";".join(p for p in parts if p)
    diff = abs(lam_fit - lam_obs)
    lam_fit_low = lam_fit < lambda_warn
    lam_obs_low = lam_obs < lambda_warn
    if lam_fit_low and lam_obs_low:
        parts.append(f"推定λ({lam_fit:.2f})・full実測({lam_obs:.2f})とも低い: 刺激不良の疑い")
    elif lam_fit_low and not lam_obs_low:
        parts.append(f"推定λ({lam_fit:.2f})だけ低い(full実測{lam_obs:.2f}): 当てはめの問題の疑い")
    elif diff >= lambda_diff_warn:
        parts.append(f"推定λとfull実測が{diff:.2f}ポイント食い違う")
    return ";".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 3. 混同行列(確認問題Aのみ)
# ---------------------------------------------------------------------------
def write_confusion(path, rows_check_full):
    tab = Counter((r["target_char"], r["response_char"]) for r in rows_check_full)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["target_char", "response_char", "count"])
        for (t, resp), c in sorted(tab.items(), key=lambda kv: (kv[0][0], -kv[1])):
            w.writerow([t, resp, c])


def write_confusion_seion_dakuon(path, rows_check_full_audio, rows_check_full_visual):
    """
    確認問題A(打ち切りなし全部提示)における、清音⇄濁音⇄半濁音の取り違えだけを
    抜き出した表。濁音全体(が・ぐ・ど・だ・ず・ぼ 等)の正答率が軒並み低いことを
    示すには、単なる混同行列(全ペア)より「同じ行の中でどちらへ倒れたか」を
    見たほうが分かりやすいため、別出力にした。
    """
    rows_out = []
    for mod, rows in (("audio", rows_check_full_audio), ("visual", rows_check_full_visual)):
        n_target = Counter(r["target_char"] for r in rows)
        pair_count = Counter((r["target_char"], r["response_char"]) for r in rows
                              if r["target_char"] != r["response_char"]
                              and r["target_char"] in CHAR_GROUP
                              and r["response_char"] in CHAR_GROUP
                              and CHAR_GROUP[r["target_char"]] == CHAR_GROUP[r["response_char"]])
        for (t, resp), c in pair_count.items():
            n = n_target[t]
            rows_out.append(dict(modality=mod, target_char=t, response_char=resp,
                                  target_type=CHAR_TYPE[t], response_type=CHAR_TYPE[resp],
                                  direction=f"{CHAR_TYPE[t]}→{CHAR_TYPE[resp]}",
                                  count=c, n_target_trials=n,
                                  rate=round(c / n, 4) if n else ""))
    rows_out.sort(key=lambda r: (r["modality"], r["target_char"], -r["count"]))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["modality", "target_char", "response_char", "target_type", "response_type",
                     "direction", "count", "n_target_trials", "rate"])
        for r in rows_out:
            w.writerow([r["modality"], r["target_char"], r["response_char"], r["target_type"],
                        r["response_type"], r["direction"], r["count"], r["n_target_trials"], r["rate"]])


# ---------------------------------------------------------------------------
# 4. 確認問題の集計(全部提示 vs 最小提示)
# ---------------------------------------------------------------------------
def write_checks(path, rows_check):
    """
    字ごとに、確認問題A(full=打ち切りなし)と確認問題C(floor=最小提示)の正答率を出す。
    全部提示は本来ほぼ100%になるはずの操作チェックなので、低い字は刺激の不具合を示す。
    聴覚・視覚それぞれで別行にする(同じ字でも刺激が別物のため)。
    """
    tab = defaultdict(lambda: {"full": [0, 0], "floor": [0, 0]})
    for r in rows_check:
        if r["check_kind"] not in ("full", "floor"):
            continue
        mod = r["modality_g"]
        k = (mod, r["target_char"])
        ok, n = tab[k][r["check_kind"]]
        tab[k][r["check_kind"]] = [ok + (1 if r["correct_b"] else 0), n + 1]

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["modality", "char", "n_full", "acc_full", "n_floor", "acc_floor"])
        for (mod, ch), d in sorted(tab.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            ok_f, n_f = d["full"]
            ok_l, n_l = d["floor"]
            w.writerow([mod, ch, n_f, round(ok_f / n_f, 4) if n_f else "",
                        n_l, round(ok_l / n_l, 4) if n_l else ""])


# ---------------------------------------------------------------------------
# 参加者ごとの属性(感度分析・ブートストラップで共通に使う)
# ---------------------------------------------------------------------------
def build_participant_stats(base_rows, main_rows):
    """
    参加者ごとに、感度分析の除外判定に要る値をまとめておく。

    - group: acal/aprime
    - full_acc: 確認問題A(check_kind=="full")の正答率(全字)
    - resume_or_replay: resume_count>0 または replays>0 の行が1つでもあるか
    - refresh_hz: 視覚のみ。参加者内の中央値(端末は基本セッション中一定のはずだが念のため中央値)
    - audio_device: 聴覚のみ。参加者内の最頻値
    - dominant_response_share: 本命問題(main_rows)でのresponse_charの最頻値の割合
    - rt_q1, rt_q3: 本命問題でのrt_msの四分位数(Tukeyの外れ値判定に使う)
    """
    by_pid_base = defaultdict(list)
    for r in base_rows:
        by_pid_base[r["participant_id"]].append(r)
    by_pid_main = defaultdict(list)
    for r in main_rows:
        by_pid_main[r["participant_id"]].append(r)

    stats = {}
    for pid, rs in by_pid_base.items():
        group = rs[0].get("group", "")
        full_rows = [r for r in rs if r["check_kind"] == "full"]
        n_full = len(full_rows)
        full_acc = (sum(1 for r in full_rows if r["correct_b"]) / n_full) if n_full else None
        resume_or_replay = any((r["resume_count"] or 0) > 0 or (r["replays"] or 0) > 0 for r in rs)
        hz_vals = [r["refresh_hz"] for r in rs if r["refresh_hz"] is not None]
        refresh_hz = float(np.median(hz_vals)) if hz_vals else None
        dev_vals = [r.get("audio_device") for r in rs if r.get("audio_device")]
        audio_device = Counter(dev_vals).most_common(1)[0][0] if dev_vals else ""

        mrs = by_pid_main.get(pid, [])
        resp = [r["response_char"] for r in mrs]
        dominant_share = (Counter(resp).most_common(1)[0][1] / len(resp)) if resp else 0.0
        rts = sorted(r["rt_ms"] for r in mrs if r["rt_ms"] is not None)
        if rts:
            q1 = float(np.percentile(rts, 25))
            q3 = float(np.percentile(rts, 75))
        else:
            q1 = q3 = None

        stats[pid] = dict(group=group, full_acc=full_acc, resume_or_replay=resume_or_replay,
                           refresh_hz=refresh_hz, audio_device=audio_device,
                           dominant_response_share=dominant_share, rt_q1=q1, rt_q3=q3)
    return stats


# ---------------------------------------------------------------------------
# 5. 感度分析
# ---------------------------------------------------------------------------
def fit_group(rows, level_key, gamma, n_starts):
    """(char[,family])ごとにグルーピングして当てはめ、(mu,lambda,n_trials,n_participants)を返す。"""
    xs, ks, ns = aggregate_levels(rows, level_key)
    fit = fit_sigmoid(xs, ks, ns, gamma, n_starts=n_starts)
    n_part = len({r["participant_id"] for r in rows})
    return fit["mu"], fit["lam"], fit["n_trials"], n_part


def apply_trial_level_cut(rows, cut, pstats):
    """試行単位の除外(cut=rt_iqr / rt_min300)。参加者単位の除外は apply_participant_cut。"""
    if cut == "rt_iqr":
        out = []
        for r in rows:
            st = pstats.get(r["participant_id"])
            if not st or st["rt_q1"] is None or r["rt_ms"] is None:
                out.append(r)
                continue
            iqr = st["rt_q3"] - st["rt_q1"]
            lo, hi = st["rt_q1"] - 1.5 * iqr, st["rt_q3"] + 1.5 * iqr
            if lo <= r["rt_ms"] <= hi:
                out.append(r)
        return out
    if cut == "rt_min300":
        return [r for r in rows if r["rt_ms"] is None or r["rt_ms"] >= 300]
    return rows


def apply_participant_cut(rows, cut, pstats, args):
    """参加者単位の除外(該当participantの行をすべて落とす)。"""
    def keep(pid):
        st = pstats.get(pid)
        if st is None:
            return True
        if cut == "same_response_30pct":
            return st["dominant_response_share"] < args.same_response_share
        if cut == "full_check_lt50pct":
            return st["full_acc"] is None or st["full_acc"] >= args.full_check_min_acc
        if cut == "refresh_hz_out_of_range":
            return st["refresh_hz"] is None or (args.refresh_lo <= st["refresh_hz"] <= args.refresh_hi)
        if cut == "resume_or_replay":
            return not st["resume_or_replay"]
        if cut == "wireless_audio":
            return st["audio_device"] != "無線"
        return True
    return [r for r in rows if keep(r["participant_id"])]


CUTS_BOTH = ["rt_iqr", "rt_min300", "same_response_30pct", "full_check_lt50pct", "resume_or_replay"]
CUTS_VISUAL_ONLY = ["refresh_hz_out_of_range", "nominal_vs_actual"]
CUTS_AUDIO_ONLY = ["wireless_audio"]


def write_sensitivity(path, rows_audio_main, rows_visual_main, pstats, gamma_audio, gamma_visual,
                       visual_axis, n_starts, args):
    """
    切り方を変えたとき、字ごとのμ(立ち上がりの中心)がどれだけ動くかを見る。
    cut="baseline" が基準(全部使う)。他のcutは、そこから該当する行/参加者だけを
    追加で除いた再フィットの結果。
    """
    level_key_visual = "actual_s_pct" if visual_axis == "actual" else "progress_pct"
    for r in rows_visual_main:
        if "actual_s_pct" not in r:
            r["actual_s_pct"] = round(r["actual_s"] * 100, 4) if r["actual_s"] is not None else None

    families = sorted({r["family"] for r in rows_visual_main if r["family"]})
    out_rows = []

    def run_cut(cut, sub_audio, sub_visual, level_key_v):
        for ch in TARGET_CHARS:
            sub = [r for r in sub_audio if r["target_char"] == ch and not r["is_embedded_full"]]
            mu, lam, n_trials, n_part = fit_group(sub, "gate_ms", gamma_audio, n_starts)
            out_rows.append(dict(cut=cut, modality="audio", char=ch, family="",
                                  mu=mu, lam=lam, n_trials=n_trials, n_participants=n_part))
        for ch in TARGET_CHARS:
            for fam in families:
                sub = [r for r in sub_visual if r["target_char"] == ch and r["family"] == fam]
                mu, lam, n_trials, n_part = fit_group(sub, level_key_v, gamma_visual, n_starts)
                out_rows.append(dict(cut=cut, modality="visual", char=ch, family=fam,
                                      mu=mu, lam=lam, n_trials=n_trials, n_participants=n_part))

    # 1. 基準
    run_cut("baseline", rows_audio_main, rows_visual_main, level_key_visual)

    # 2,3: 試行単位の除外(聴覚・視覚それぞれに適用)
    for cut in ("rt_iqr", "rt_min300"):
        sub_a = apply_trial_level_cut(rows_audio_main, cut, pstats)
        sub_v = apply_trial_level_cut(rows_visual_main, cut, pstats)
        run_cut(cut, sub_a, sub_v, level_key_visual)

    # 4,5,7: 参加者単位の除外(聴覚・視覚共通)
    for cut in ("same_response_30pct", "full_check_lt50pct", "resume_or_replay"):
        sub_a = apply_participant_cut(rows_audio_main, cut, pstats, args)
        sub_v = apply_participant_cut(rows_visual_main, cut, pstats, args)
        run_cut(cut, sub_a, sub_v, level_key_visual)

    # 6: refresh_hz範囲外(視覚のみ)
    sub_v = apply_participant_cut(rows_visual_main, "refresh_hz_out_of_range", pstats, args)
    run_cut("refresh_hz_out_of_range", [], sub_v, level_key_visual)
    # 上のrun_cutは聴覚も回してしまうので、視覚のみ有効なcutは聴覚行を出力後に取り除く
    out_rows = [r for r in out_rows if not (r["cut"] == "refresh_hz_out_of_range" and r["modality"] == "audio")]

    # 8: 無線イヤホン(聴覚のみ)
    sub_a = apply_participant_cut(rows_audio_main, "wireless_audio", pstats, args)
    run_cut("wireless_audio", sub_a, [], level_key_visual)
    out_rows = [r for r in out_rows if not (r["cut"] == "wireless_audio" and r["modality"] == "visual")]

    # 9: 視覚のみ、名目水準で当てはめ直す(除外はせず軸だけ変える)
    run_cut("nominal_vs_actual", [], rows_visual_main, "progress_pct")
    out_rows = [r for r in out_rows if not (r["cut"] == "nominal_vs_actual" and r["modality"] == "audio")]

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cut", "modality", "char", "family", "mu", "lambda", "n_trials", "n_participants"])
        for r in out_rows:
            w.writerow([r["cut"], r["modality"], r["char"], r["family"],
                        _fmt(r["mu"]), _fmt(r["lam"]), r["n_trials"], r["n_participants"]])
    return out_rows


# ---------------------------------------------------------------------------
# 6. ブートストラップ(参加者単位)
# ---------------------------------------------------------------------------
def write_bootstrap(path, rows_audio_main, rows_visual_main, gamma_audio, gamma_visual,
                     visual_axis, n_boot, seed, n_starts_boot):
    """
    参加者単位でブートストラップする。

    ⚠ 試行単位でリサンプルしないのは、同じ参加者の複数回答が独立でないため。
    1人の参加者内の答えは、その人の聴力・視力・その日の集中度などで相関するので、
    試行を独立標本として扱うと不確かさを過小評価してしまう(見かけ上、標本数が
    実際の参加者数よりずっと多いかのように振る舞ってしまう)。参加者IDを
    復元抽出し、選ばれた参加者の行を丸ごと束ねて再フィットすることで、
    参加者間のばらつきをそのまま不確かさに反映させる。
    """
    rng = np.random.default_rng(seed)

    level_key_v = "actual_s_pct" if visual_axis == "actual" else "progress_pct"
    for r in rows_visual_main:
        if "actual_s_pct" not in r:
            r["actual_s_pct"] = round(r["actual_s"] * 100, 4) if r["actual_s"] is not None else None

    by_pid_a = defaultdict(list)
    for r in rows_audio_main:
        if not r["is_embedded_full"]:
            by_pid_a[r["participant_id"]].append(r)
    pids_a = sorted(by_pid_a.keys())

    by_pid_v = defaultdict(list)
    for r in rows_visual_main:
        by_pid_v[r["participant_id"]].append(r)
    pids_v = sorted(by_pid_v.keys())

    families = sorted({r["family"] for r in rows_visual_main if r["family"]})

    # 蓄積先: (modality,char[,family]) -> {"mu":[...], "lam":[...], "conv":[...]}
    acc = defaultdict(lambda: {"mu": [], "lam": [], "conv": []})

    for b in range(n_boot):
        # --- 聴覚 ---
        draw_a = rng.choice(pids_a, size=len(pids_a), replace=True) if pids_a else []
        rows_a = []
        for pid in draw_a:
            rows_a.extend(by_pid_a[pid])
        for ch in TARGET_CHARS:
            sub = [r for r in rows_a if r["target_char"] == ch]
            xs, ks, ns = aggregate_levels(sub, "gate_ms")
            fit = fit_sigmoid(xs, ks, ns, gamma_audio, n_starts=n_starts_boot)
            key = ("audio", ch, "")
            acc[key]["mu"].append(fit["mu"])
            acc[key]["lam"].append(fit["lam"])
            acc[key]["conv"].append(fit["converged"])

        # --- 視覚 ---
        draw_v = rng.choice(pids_v, size=len(pids_v), replace=True) if pids_v else []
        rows_v = []
        for pid in draw_v:
            rows_v.extend(by_pid_v[pid])
        for ch in TARGET_CHARS:
            for fam in families:
                sub = [r for r in rows_v if r["target_char"] == ch and r["family"] == fam]
                xs, ks, ns = aggregate_levels(sub, level_key_v)
                fit = fit_sigmoid(xs, ks, ns, gamma_visual, n_starts=n_starts_boot)
                key = ("visual", ch, fam)
                acc[key]["mu"].append(fit["mu"])
                acc[key]["lam"].append(fit["lam"])
                acc[key]["conv"].append(fit["converged"])

        if (b + 1) % max(1, n_boot // 10) == 0:
            print(f"  bootstrap {b + 1}/{n_boot}")

    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["modality", "char", "family", "n_boot", "converged_rate",
                     "mu_median", "mu_lo95", "mu_hi95", "lambda_median", "lambda_lo95", "lambda_hi95"])
        for (mod, ch, fam), d in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
            mu_arr = np.array(d["mu"], dtype=float)
            lam_arr = np.array(d["lam"], dtype=float)
            conv_rate = float(np.mean(d["conv"])) if d["conv"] else float("nan")
            mu_med, mu_lo, mu_hi = (np.nanpercentile(mu_arr, [50, 2.5, 97.5])
                                     if np.any(~np.isnan(mu_arr)) else (float("nan"),) * 3)
            lam_med, lam_lo, lam_hi = (np.nanpercentile(lam_arr, [50, 2.5, 97.5])
                                        if np.any(~np.isnan(lam_arr)) else (float("nan"),) * 3)
            w.writerow([mod, ch, fam, n_boot, round(conv_rate, 3),
                        _fmt(mu_med), _fmt(mu_lo), _fmt(mu_hi),
                        _fmt(lam_med), _fmt(lam_lo), _fmt(lam_hi)])


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="project/data_calib_20260825/transfer_trials.csv")
    ap.add_argument("--out", default="project/data_calib_20260825/analysis")
    ap.add_argument("--boot", type=int, default=1000, help="ブートストラップの繰り返し回数(既定1000)")
    ap.add_argument("--boot-starts", type=int, default=3,
                    help="ブートストラップ内の当てはめの多点スタート数(既定3、"
                         "本フィット/感度分析の6より少なくして計算時間を抑える)")
    ap.add_argument("--fit-starts", type=int, default=6,
                    help="本フィット・感度分析の多点スタート数(局所解対策、既定6)")
    ap.add_argument("--seed", type=int, default=12345, help="ブートストラップの乱数シード(再現性のため固定)")
    ap.add_argument("--visual-axis", choices=["actual", "nominal"], default="actual",
                    help="視覚の主軸。既定actual(実測 actual_s)。"
                         "nominalは進み具合の名目値(progress_pct)。既定を実測にする理由は"
                         "write_fit_logistic のコメント参照。名目との比較はsensitivity.csvの"
                         "cut=nominal_vs_actualで別途出す")
    ap.add_argument("--lambda-warn", type=float, default=0.5,
                    help="λ(天井)がこれ未満なら『低い』とみなす閾値(既定0.5)。"
                         "偶然正答(1/68≈0.015等)よりは十分高いが、"
                         "実用上『読み取れている』と言うには五分以上必要という考えで0.5とした。"
                         "判断の要る数値なので引数で変更できるようにしてある")
    ap.add_argument("--lambda-diff-warn", type=float, default=0.15,
                    help="推定λとfull実測の差がこれ以上なら食い違いとして note に残す(既定0.15=15pt)。"
                         "較正曲線の当てはめ誤差の目安として置いた値で、根拠は経験則。引数で変更可")
    ap.add_argument("--rt-min-ms", type=float, default=300.0, help="反応時間の下限カット(既定300ms、指示どおり)")
    ap.add_argument("--same-response-share", type=float, default=0.3,
                    help="同じ字を押し続けたとみなす割合の閾値(既定0.3、指示どおり)")
    ap.add_argument("--full-check-min-acc", type=float, default=0.5,
                    help="確認問題Aの正答率がこれ未満の参加者を除外(既定0.5、指示どおり)")
    ap.add_argument("--refresh-lo", type=float, default=50.0, help="refresh_hzの下限(既定50、指示どおり)")
    ap.add_argument("--refresh-hi", type=float, default=130.0, help="refresh_hzの上限(既定130、指示どおり)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"読み込み: {args.inp}")
    raw = load(args.inp)
    print(f"  全{len(raw)}行")
    raw = normalize(raw)
    base = base_filter(raw)

    rows_audio_all = [r for r in base if r["modality_g"] == "audio"]
    rows_visual_all = [r for r in base if r["modality_g"] == "visual"]

    main_all = main_target_rows(base)
    rows_audio_main = [r for r in main_all if r["modality_g"] == "audio"]
    rows_visual_main = [r for r in main_all if r["modality_g"] == "visual"]
    print(f"  本命8字の本命問題: 聴覚{len(rows_audio_main)}行 / 視覚{len(rows_visual_main)}行")

    gamma_audio, n_choices_audio = default_gamma(rows_audio_main, "audio")
    gamma_visual, n_choices_visual = default_gamma(rows_visual_main, "visual")
    print(f"  gamma(下限・固定): 聴覚=1/{n_choices_audio}={gamma_audio:.5f}, "
          f"視覚=1/{n_choices_visual}={gamma_visual:.5f}")

    # ---- 1. 素の正答率表 ----
    write_curves_audio(os.path.join(args.out, "curves_audio.csv"), rows_audio_main)
    write_curves_visual(os.path.join(args.out, "curves_visual.csv"), rows_visual_main)
    print("  書き出し: curves_audio.csv, curves_visual.csv")

    # ---- 2. シグモイド当てはめ ----
    write_fit_logistic(os.path.join(args.out, "fit_logistic.csv"), rows_audio_main, rows_visual_main,
                        gamma_audio, gamma_visual, args.visual_axis, args.fit_starts,
                        args.lambda_warn, args.lambda_diff_warn)
    print("  書き出し: fit_logistic.csv")

    # ---- 3. 混同行列(確認問題Aのみ) ----
    check_full_audio = [r for r in rows_audio_all if r["check_kind"] == "full"]
    check_full_visual = [r for r in rows_visual_all if r["check_kind"] == "full"]
    write_confusion(os.path.join(args.out, "confusion_audio.csv"), check_full_audio)
    write_confusion(os.path.join(args.out, "confusion_visual.csv"), check_full_visual)
    write_confusion_seion_dakuon(os.path.join(args.out, "confusion_seion_dakuon.csv"),
                                  check_full_audio, check_full_visual)
    print("  書き出し: confusion_audio.csv, confusion_visual.csv, confusion_seion_dakuon.csv")

    # ---- 4. 確認問題の集計 ----
    write_checks(os.path.join(args.out, "checks.csv"), rows_audio_all + rows_visual_all)
    print("  書き出し: checks.csv")

    # ---- 5. 感度分析 ----
    pstats = build_participant_stats(base, main_all)
    write_sensitivity(os.path.join(args.out, "sensitivity.csv"), rows_audio_main, rows_visual_main,
                       pstats, gamma_audio, gamma_visual, args.visual_axis, args.fit_starts, args)
    print("  書き出し: sensitivity.csv")

    # ---- 6. ブートストラップ ----
    print(f"  ブートストラップ開始(繰り返し{args.boot}回、参加者単位)")
    write_bootstrap(os.path.join(args.out, "bootstrap.csv"), rows_audio_main, rows_visual_main,
                     gamma_audio, gamma_visual, args.visual_axis, args.boot, args.seed, args.boot_starts)
    print("  書き出し: bootstrap.csv")

    print(f"\n完了: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
