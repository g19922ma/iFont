#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
較正フェーズの識別率曲線を「文字 × アニメーション方式 × 速さ」で細かく分けて描く。
======================================================================

背景
----
1升(char × family × progress_pct × base_anim_ms)あたりの試行数は 4〜12
(中央値8, 278/512升が10未満)しかない。この粒度のまま線を引くと1問の
当たり外れで正答率が12〜25%動き、読めない図になる(例:「あ×端から」を
progress_pct 単位で見ると 8%→75%、14%→40% と乱高下する)。

そこで本スクリプトは3段階の粒度で描き分ける。

  粗 (約120〜300問/点)……線を引く。95%信頼区間つき。
     主力は「実測値(actual_s)を対数の等間隔で区切って束ねる」方法。
     著者が試した結果いちばん読めた方法で、本命8字だけでなくまぎれ字
     (is_decoy=真の63字)も合算して1区間あたり約300問を確保する。
  中 (約16〜150問/点)……線は引くが、区間が広いことを図中に明示する。
  細 (4〜12問/点)………点だけ打つ。線は引かない(ノイズを知見に見せない)。

入力
----
  project/data_calib_20260825/cube/visual_char_family_level_speed.csv (512升、集計済み)
  project/data_calib_20260825/cube/audio_char_gate.csv               (64升、集計済み)
  project/data_calib_20260825/transfer_trials.csv                     (対数ビン集計の元試行)

出力
----
  project/data_calib_20260825/figs/*.png   (個別PNG。論文にも流用できる)
  project/data_calib_20260825/curves_report.html (1ファイル完結、data URI埋め込み)

注意
----
- analyze_calib_full.py / analyze_calib_deep.py は一切変更しない。
  清濁半濁の分類(char_type_ext)だけ analyze_calib_deep から再利用する。
- git commit / push は行わない。
"""
import base64
import csv
import math
import os
import sys
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze_calib_deep as acd  # noqa: E402  既存ツール(変更しない)を読み取り専用で再利用

REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
DATA_DIR = os.path.join(REPO_ROOT, "project", "data_calib_20260825")
CUBE_VISUAL = os.path.join(DATA_DIR, "cube", "visual_char_family_level_speed.csv")
CUBE_AUDIO = os.path.join(DATA_DIR, "cube", "audio_char_gate.csv")
TRIALS_CSV = os.path.join(DATA_DIR, "transfer_trials.csv")
FIG_DIR = os.path.join(DATA_DIR, "figs")
REPORT_PATH = os.path.join(DATA_DIR, "curves_report.html")

HONMEI = list("あかがぱしつまら")
FAMILIES = ["fade", "reveal", "blur", "wipe"]
FAMILY_JP = {"fade": "うすい→濃い", "reveal": "点が増える", "blur": "ぼやけ→はっきり", "wipe": "端から現れる"}
FAMILY_COLOR = {"fade": "#3167a8", "reveal": "#3f8f5c", "blur": "#c08a2e", "wipe": "#c1473f"}
SPEED_STYLE = {"300": "-", "500": "--"}
CAT_COLOR = {"seion": "#2e5fa3", "daku": "#b5432f"}
CAT_JP = {"seion": "清音", "daku": "濁音・半濁音"}

CHAR_PALETTE = ["#3167a8", "#c1473f", "#3f8f5c", "#c08a2e",
                "#7a5da0", "#3aa6a0", "#a05a8c", "#6b6b6b"]
CHAR_COLOR = {ch: CHAR_PALETTE[i] for i, ch in enumerate(HONMEI)}

Z975 = 1.959963985  # 標準正規分布の97.5%点


# ---------------------------------------------------------------------------
# 共通ユーティリティ
# ---------------------------------------------------------------------------
def pick_jp_font():
    for name in ["Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic",
                 "IPAexGothic", "Noto Sans CJK JP", "TakaoPGothic"]:
        try:
            path = font_manager.findfont(font_manager.FontProperties(family=name),
                                          fallback_to_default=False)
            if path and os.path.exists(path):
                return name
        except Exception:
            continue
    return None


def truthy(v):
    return str(v).strip().upper() in ("1", "TRUE", "T", "YES")


def wilson_ci(k, n):
    """二項比率の Wilson score 95%区間。n=0 のときは (nan, nan)。"""
    if n <= 0:
        return (float("nan"), float("nan"))
    phat = k / n
    z = Z975
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def log_bin_edges(x, target_n=300, min_bins=3, max_bins=10):
    """実測値(%)を対数の等間隔で区切る。1区間あたりの目標試行数から
    区間の本数を決める(多すぎても少なすぎても読めないので上下限で挟む)。"""
    n = len(x)
    nbins = int(round(n / target_n)) if target_n > 0 else min_bins
    nbins = max(min_bins, min(max_bins, nbins))
    lo, hi = float(np.min(x)), float(np.max(x))
    lo = max(lo, 1e-3)
    if hi <= lo:
        hi = lo * 1.01
    return np.geomspace(lo, hi, nbins + 1)


def bin_stats(x, correct, edges):
    """各区間の (幾何中心, 下端, 上端, n, 正答率, CI下, CI上) を返す。
    n=0の区間は正答率をnanにする → 折れ線がその区間で自然に途切れる
    (「データが無い」ことを線の切れ目として見せるため)。"""
    out = []
    nb = len(edges) - 1
    x = np.asarray(x, dtype=float)
    correct = np.asarray(correct, dtype=float)
    for i in range(nb):
        lo, hi = edges[i], edges[i + 1]
        mask = (x >= lo) & (x <= hi) if i == nb - 1 else (x >= lo) & (x < hi)
        n = int(mask.sum())
        cx = math.sqrt(lo * hi)
        if n == 0:
            out.append(dict(x=cx, lo=lo, hi=hi, n=0, acc=float("nan"),
                             ci_lo=float("nan"), ci_hi=float("nan")))
            continue
        k = int(correct[mask].sum())
        acc = k / n
        cilo, cihi = wilson_ci(k, n)
        out.append(dict(x=cx, lo=lo, hi=hi, n=n, acc=acc, ci_lo=cilo, ci_hi=cihi))
    return out


def plot_binned_series(ax, stats, color, label, linestyle="-", shade_gaps=True, lw=2.2):
    """区間まとめの曲線を1本描く。点の大きさ=試行数、エラーバー=95%CI、
    データの無い区間は網掛け+線を切る。"""
    xs = np.array([s["x"] for s in stats])
    accs = np.array([s["acc"] for s in stats])
    los = np.array([s["ci_lo"] for s in stats])
    his = np.array([s["ci_hi"] for s in stats])
    ns = np.array([s["n"] for s in stats], dtype=float)
    valid = ~np.isnan(accs)

    if shade_gaps:
        for s in stats:
            if s["n"] == 0:
                ax.axvspan(s["lo"], s["hi"], color="0.85", alpha=0.6, zorder=0, linewidth=0)

    ax.plot(xs, accs * 100, linestyle, color=color, linewidth=lw, label=label, zorder=3)
    if valid.any():
        yerr_lo = np.clip((accs - los) * 100, 0, None)
        yerr_hi = np.clip((his - accs) * 100, 0, None)
        ax.errorbar(xs[valid], accs[valid] * 100,
                     yerr=[yerr_lo[valid], yerr_hi[valid]],
                     fmt="none", ecolor=color, elinewidth=1.1, capsize=3, alpha=0.55, zorder=2)
        nmax = ns[valid].max() if ns[valid].max() > 0 else 1.0
        sizes = 18 + 55 * (ns[valid] / nmax)
        ax.scatter(xs[valid], accs[valid] * 100, s=sizes, color=color, zorder=4,
                    edgecolor="white", linewidth=0.6)
    return xs, accs, ns


def fig_to_data_uri(path):
    with open(path, "rb") as f:
        b = f.read()
    return "data:image/png;base64," + base64.b64encode(b).decode("ascii")


def stats_table_html(stats, x_label="実測値(%)"):
    rows = []
    rows.append(f"<tr><th>{x_label} 区間</th><th>n</th><th>正答率</th><th>95%CI</th></tr>")
    for s in stats:
        rng = f"{s['lo']:.2f}〜{s['hi']:.2f}"
        if s["n"] == 0:
            rows.append(f"<tr class='gap'><td>{rng}</td><td>0</td><td colspan='2'>データなし</td></tr>")
        else:
            rows.append(f"<tr><td>{rng}</td><td>{s['n']}</td>"
                         f"<td>{s['acc']*100:.1f}%</td>"
                         f"<td>{s['ci_lo']*100:.1f}–{s['ci_hi']*100:.1f}%</td></tr>")
    return "<table class='bintab'>" + "".join(rows) + "</table>"


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------
def load_cube_visual():
    with open(CUBE_VISUAL, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_cube_audio():
    with open(CUBE_AUDIO, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_visual_trials():
    """transfer_trials.csv から、較正フェーズ・視覚モダリティの使えるターゲット行
    (本命8字 + まぎれ字is_decoy、キャッチ試行は除く)を読み込む。"""
    with open(TRIALS_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    honmei = set(HONMEI)
    out = []
    for r in rows:
        if r.get("modality") != "transfer_visual":
            continue
        if truthy(r.get("is_test")):
            continue
        if truthy(r.get("is_catch")):
            continue
        is_decoy = truthy(r.get("is_decoy"))
        tgt = r.get("target_char", "")
        if not (is_decoy or tgt in honmei):
            continue
        try:
            actual_pct = float(r["actual_s"]) * 100.0
        except (KeyError, ValueError):
            continue
        out.append(dict(
            char=tgt,
            family=r.get("family", ""),
            base_anim_ms=r.get("base_anim_ms", ""),
            correct=1.0 if truthy(r.get("correct")) else 0.0,
            actual_pct=actual_pct,
            is_decoy=is_decoy,
            char_type=acd.char_type_ext(tgt),
        ))
    return out


def load_audio_trials():
    with open(TRIALS_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    honmei = set(HONMEI)
    out = []
    for r in rows:
        if r.get("modality") != "transfer_audio":
            continue
        if truthy(r.get("is_test")):
            continue
        if truthy(r.get("is_catch")):
            continue
        is_decoy = truthy(r.get("is_decoy"))
        tgt = r.get("target_char", "")
        if not (is_decoy or tgt in honmei):
            continue
        out.append(dict(
            char=tgt,
            gate_ms=r.get("gate_ms", ""),
            correct=1.0 if truthy(r.get("correct")) else 0.0,
            is_decoy=is_decoy,
            char_type=acd.char_type_ext(tgt),
        ))
    return out


# ---------------------------------------------------------------------------
# A. 粗い粒度
# ---------------------------------------------------------------------------
def build_A1(vis_trials):
    """方式ごとのV(s)。対数ビンで束ねる(主力図)。8字+まぎれ字合算、速さ合算。"""
    fig, ax = plt.subplots(figsize=(8.0, 5.2), dpi=150)
    table_html = []
    total_n = 0
    for fam in FAMILIES:
        sub = [t for t in vis_trials if t["family"] == fam]
        x = np.array([t["actual_pct"] for t in sub])
        c = np.array([t["correct"] for t in sub])
        edges = log_bin_edges(x, target_n=300, min_bins=5, max_bins=9)
        stats = bin_stats(x, c, edges)
        plot_binned_series(ax, stats, FAMILY_COLOR[fam],
                            f"{FAMILY_JP[fam]}（n={len(sub)}）")
        total_n += len(sub)
        table_html.append(f"<h4>{FAMILY_JP[fam]}（{fam}, 合計n={len(sub)}）</h4>" +
                           stats_table_html(stats))
    ax.set_xscale("log")
    ax.set_xlabel("実測の提示割合 actual_s（%, 対数軸）")
    ax.set_ylabel("正答率（%）")
    ax.set_ylim(-5, 105)
    ax.grid(alpha=0.25, which="both", linewidth=0.5)
    ax.legend(loc="lower right", fontsize=9, frameon=False)
    ax.set_title(f"方式ごとの識別率曲線 V(s)（対数ビン集計、本命8字+まぎれ字、速さ合算, 総n={total_n}）",
                 fontsize=10.5)
    fig.tight_layout()
    path = os.path.join(FIG_DIR, "A1_family_binned.png")
    fig.savefig(path)
    plt.close(fig)
    return path, "".join(table_html)


def build_A2(vis_trials, cube_rows):
    """対数ビン集計(太線)と、生の水準progress_pctごとの集計(細い点線)を並べる。
    丸めの影響を確認するための図。"""
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 8.0), dpi=150, sharey=True)
    for ax, fam in zip(axes.flat, FAMILIES):
        sub = [t for t in vis_trials if t["family"] == fam]
        x = np.array([t["actual_pct"] for t in sub])
        c = np.array([t["correct"] for t in sub])
        edges = log_bin_edges(x, target_n=300, min_bins=5, max_bins=9)
        stats = bin_stats(x, c, edges)
        plot_binned_series(ax, stats, FAMILY_COLOR[fam], "対数ビン集計（束ね）", lw=2.4)

        # 生の水準(progress_pct)ごとの集計: 8字×2速さを合算(cubeを使用)
        crows = [r for r in cube_rows if r["family"] == fam]
        by_level = defaultdict(lambda: [0, 0, []])
        for r in crows:
            k = float(r["progress_pct"])
            by_level[k][0] += int(r["n_trials"])
            by_level[k][1] += int(r["n_correct"])
            by_level[k][2].append(float(r["actual_s_mean_pct"]))
        levels = sorted(by_level)
        rx = [np.mean(by_level[k][2]) for k in levels]
        rn = [by_level[k][0] for k in levels]
        racc = [by_level[k][1] / by_level[k][0] * 100 if by_level[k][0] else np.nan for k in levels]
        ax.plot(rx, racc, ":", color="0.25", linewidth=1.3, marker="x", markersize=5,
                label=f"生の水準ごと（progress_pct基準, n≈{int(np.mean(rn))}/点）", zorder=5)

        ax.set_xscale("log")
        ax.set_title(f"{FAMILY_JP[fam]}（{fam}）", fontsize=10)
        ax.grid(alpha=0.25, which="both", linewidth=0.5)
        ax.set_ylim(-5, 105)
        ax.legend(fontsize=7.5, frameon=False, loc="lower right")
    for ax in axes[-1]:
        ax.set_xlabel("実測の提示割合（%, 対数軸）")
    for ax in axes[:, 0]:
        ax.set_ylabel("正答率（%）")
    fig.suptitle("対数ビン集計 vs 生の水準ごとの集計（丸めの影響を見る）", fontsize=11.5)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = os.path.join(FIG_DIR, "A2_family_binned_vs_raw.png")
    fig.savefig(path)
    plt.close(fig)
    return path


def build_A3(vis_trials):
    """方式×速さで分けた対数ビン曲線(8本)。"""
    fig, ax = plt.subplots(figsize=(8.4, 5.4), dpi=150)
    for fam in FAMILIES:
        for speed in ("300", "500"):
            sub = [t for t in vis_trials if t["family"] == fam and t["base_anim_ms"] == speed]
            if not sub:
                continue
            x = np.array([t["actual_pct"] for t in sub])
            c = np.array([t["correct"] for t in sub])
            edges = log_bin_edges(x, target_n=250, min_bins=4, max_bins=7)
            stats = bin_stats(x, c, edges)
            plot_binned_series(ax, stats, FAMILY_COLOR[fam], f"{FAMILY_JP[fam]} {speed}ms（n={len(sub)}）",
                                linestyle=SPEED_STYLE[speed], shade_gaps=False, lw=1.9)
    ax.set_xscale("log")
    ax.set_xlabel("実測の提示割合 actual_s（%, 対数軸）")
    ax.set_ylabel("正答率（%）")
    ax.set_ylim(-5, 105)
    ax.grid(alpha=0.25, which="both", linewidth=0.5)
    ax.legend(loc="lower right", fontsize=7.5, frameon=False, ncol=2)
    ax.set_title("方式×速さで分けた識別率曲線（実線=300ms／破線=500ms、対数ビン集計）", fontsize=10.5)
    fig.tight_layout()
    path = os.path.join(FIG_DIR, "A3_family_speed_binned.png")
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# B. 中くらいの粒度(字と方式)
# ---------------------------------------------------------------------------
def build_B_family_panels(vis_trials):
    """方式ごとに1枚、8字を重ねる(速さ合算)。本命8字のみ(まぎれ字は別文字なので使えない)。"""
    paths = []
    for fam in FAMILIES:
        fig, ax = plt.subplots(figsize=(7.4, 4.8), dpi=150)
        for ch in HONMEI:
            sub = [t for t in vis_trials if t["family"] == fam and t["char"] == ch and not t["is_decoy"]]
            if len(sub) < 8:
                continue
            x = np.array([t["actual_pct"] for t in sub])
            c = np.array([t["correct"] for t in sub])
            edges = log_bin_edges(x, target_n=45, min_bins=3, max_bins=6)
            stats = bin_stats(x, c, edges)
            plot_binned_series(ax, stats, CHAR_COLOR[ch], f"{ch}（n={len(sub)}）",
                                shade_gaps=False, lw=1.6)
        ax.set_xscale("log")
        ax.set_xlabel("実測の提示割合（%, 対数軸）")
        ax.set_ylabel("正答率（%）")
        ax.set_ylim(-5, 105)
        ax.grid(alpha=0.25, which="both", linewidth=0.5)
        ax.legend(loc="lower right", fontsize=8, frameon=False, ncol=2)
        ax.set_title(f"{FAMILY_JP[fam]}（{fam}）内での字ごとの違い"
                      "（1点あたり約40〜50問、区間は粗めなので目安として見る）", fontsize=9.5)
        fig.tight_layout()
        path = os.path.join(FIG_DIR, f"B_family_{fam}.png")
        fig.savefig(path)
        plt.close(fig)
        paths.append((fam, path))
    return paths


def build_B_char_panels(vis_trials):
    """字ごとに1枚、4方式を重ねる(速さ合算)。"""
    paths = []
    for ch in HONMEI:
        fig, ax = plt.subplots(figsize=(7.0, 4.6), dpi=150)
        for fam in FAMILIES:
            sub = [t for t in vis_trials if t["family"] == fam and t["char"] == ch and not t["is_decoy"]]
            if len(sub) < 8:
                continue
            x = np.array([t["actual_pct"] for t in sub])
            c = np.array([t["correct"] for t in sub])
            edges = log_bin_edges(x, target_n=45, min_bins=3, max_bins=6)
            stats = bin_stats(x, c, edges)
            plot_binned_series(ax, stats, FAMILY_COLOR[fam], f"{FAMILY_JP[fam]}（n={len(sub)}）",
                                shade_gaps=False, lw=1.8)
        ax.set_xscale("log")
        ax.set_xlabel("実測の提示割合（%, 対数軸）")
        ax.set_ylabel("正答率（%）")
        ax.set_ylim(-5, 105)
        ax.grid(alpha=0.25, which="both", linewidth=0.5)
        ax.legend(loc="lower right", fontsize=8.5, frameon=False)
        ax.set_title(f"「{ch}」における方式ごとの違い（1点あたり約40〜50問）", fontsize=10)
        fig.tight_layout()
        path = os.path.join(FIG_DIR, f"B_char_{ch}.png")
        fig.savefig(path)
        plt.close(fig)
        paths.append((ch, path))
    return paths


# ---------------------------------------------------------------------------
# C. 細かい粒度(512升そのまま、点だけ)
# ---------------------------------------------------------------------------
def build_C_grid(cube_rows):
    fig, axes = plt.subplots(len(HONMEI), len(FAMILIES), figsize=(13.5, 24), dpi=140,
                              sharex=False)
    ns_all = [int(r["n_trials"]) for r in cube_rows]
    nmax = max(ns_all)

    for i, ch in enumerate(HONMEI):
        for j, fam in enumerate(FAMILIES):
            ax = axes[i, j]
            sub = [r for r in cube_rows if r["char"] == ch and r["family"] == fam]
            for speed, color in (("300", "#3167a8"), ("500", "#c1473f")):
                ss = [r for r in sub if r["base_anim_ms"] == speed]
                if not ss:
                    continue
                x = [float(r["actual_s_mean_pct"]) for r in ss]
                y = [float(r["accuracy"]) * 100 for r in ss]
                n = [int(r["n_trials"]) for r in ss]
                sizes = [10 + 60 * (nn / nmax) for nn in n]
                ax.scatter(x, y, s=sizes, color=color, alpha=0.8,
                           edgecolor="white", linewidth=0.4,
                           label=f"{speed}ms" if (i == 0 and j == 0) else None)
            ax.set_xscale("log")
            ax.set_ylim(-8, 108)
            ax.tick_params(labelsize=6.5)
            if i == 0:
                ax.set_title(FAMILY_JP[fam], fontsize=9)
            if j == 0:
                ax.set_ylabel(ch, fontsize=12, rotation=0, labelpad=18, va="center")
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#3167a8", markersize=7, label="300ms"),
               plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#c1473f", markersize=7, label="500ms")]
    fig.legend(handles=handles, loc="upper right", fontsize=10, frameon=False)
    fig.suptitle("字×方式×速さの全512升（点のみ、線は引かない／点の大きさ=試行数, 1升4〜12問・中央値8問）",
                 fontsize=13, y=0.995)
    fig.text(0.5, 0.005, "横軸: 実測の提示割合 actual_s（%, 対数軸）／縦軸: 正答率（%）", ha="center", fontsize=9)
    fig.tight_layout(rect=[0.02, 0.015, 1, 0.985])
    path = os.path.join(FIG_DIR, "C_grid_small_multiples.png")
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# D. 聴覚
# ---------------------------------------------------------------------------
def build_D_audio(cube_audio_rows):
    fig, ax = plt.subplots(figsize=(8.2, 5.4), dpi=150)
    by_char = defaultdict(list)
    for r in cube_audio_rows:
        by_char[r["char"]].append(r)

    # 表示用: 数値のgate_msの最大値の1.15倍を「full」の見かけ上の位置にする
    all_numeric = [float(r["gate_ms"]) for r in cube_audio_rows if r["gate_ms"] != "full"]
    full_x = max(all_numeric) * 1.18

    usable, unusable = [], []
    table_rows = []
    for ch in HONMEI:
        rows = by_char[ch]
        full_row = next(r for r in rows if r["gate_ms"] == "full")
        full_acc = float(full_row["accuracy"])
        is_usable = full_acc >= 0.8
        (usable if is_usable else unusable).append(ch)

        xs, accs, los, his, ns = [], [], [], [], []
        for r in sorted(rows, key=lambda r: (r["gate_ms"] == "full", float(r["gate_ms"]) if r["gate_ms"] != "full" else 0)):
            x = full_x if r["gate_ms"] == "full" else float(r["gate_ms"])
            n = int(r["n_trials"])
            k = int(r["n_correct"])
            cilo, cihi = wilson_ci(k, n)
            xs.append(x); accs.append(k / n); los.append(cilo); his.append(cihi); ns.append(n)
        ls = "-" if is_usable else "--"
        ax.plot(xs, [a * 100 for a in accs], ls, color=CHAR_COLOR[ch], linewidth=2,
                marker="o", markersize=5, label=f"{ch}（全長{full_acc*100:.0f}%）")
        ax.errorbar(xs, [a * 100 for a in accs],
                     yerr=[[max(0.0, (a - lo) * 100) for a, lo in zip(accs, los)],
                           [max(0.0, (hi - a) * 100) for hi, a in zip(his, accs)]],
                     fmt="none", ecolor=CHAR_COLOR[ch], elinewidth=0.9, capsize=2.5, alpha=0.5)
        table_rows.append((ch, is_usable, list(zip(xs, ns, accs, los, his))))

    ax.axvline(full_x - (full_x - max(all_numeric)) / 2, color="0.6", linestyle=":", linewidth=1)
    ax.text(full_x, 3, "全長提示\n(目盛りは模式的)", fontsize=7.5, ha="center", color="0.4")
    ax.set_xlabel("打ち切り時刻 gate_ms（ミリ秒）")
    ax.set_ylabel("正答率（%）")
    ax.set_ylim(-5, 105)
    ax.grid(alpha=0.25, linewidth=0.5)
    ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=2)
    ax.set_title(f"聴覚: 字ごとの識別率曲線 A(t)（実線=使える字 {''.join(usable)}／破線=使えない字 {''.join(unusable)}）",
                 fontsize=10)
    fig.tight_layout()
    path = os.path.join(FIG_DIR, "D_audio_chars.png")
    fig.savefig(path)
    plt.close(fig)

    table_html = "<table class='bintab'><tr><th>字</th><th>区分</th><th>gate_ms</th><th>n</th><th>正答率</th><th>95%CI</th></tr>"
    for ch, is_usable, pts in table_rows:
        for k, (x, n, a, lo, hi) in enumerate(pts):
            label = "full" if k == len(pts) - 1 else f"{x:.0f}"
            table_html += (f"<tr><td>{ch if k==0 else ''}</td>"
                            f"<td>{'使える' if is_usable else '使えない' if k==0 else ''}</td>"
                            f"<td>{label}</td><td>{n}</td><td>{a*100:.1f}%</td>"
                            f"<td>{lo*100:.1f}–{hi*100:.1f}%</td></tr>")
    table_html += "</table>"
    return path, table_html


# ---------------------------------------------------------------------------
# E. 清濁半濁の層別(重要な知見)
# ---------------------------------------------------------------------------
def build_E_seion_dakuon(vis_trials):
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 8.0), dpi=150, sharey=True)
    table_html = []
    for ax, fam in zip(axes.flat, FAMILIES):
        sub_fam = [t for t in vis_trials if t["family"] == fam]
        for cat_key, ch_types in (("seion", ("seion",)), ("daku", ("dakuon", "handakuon"))):
            sub = [t for t in sub_fam if t["char_type"] in ch_types]
            if not sub:
                continue
            x = np.array([t["actual_pct"] for t in sub])
            c = np.array([t["correct"] for t in sub])
            edges = log_bin_edges(x, target_n=300, min_bins=3, max_bins=8)
            stats = bin_stats(x, c, edges)
            plot_binned_series(ax, stats, CAT_COLOR[cat_key], f"{CAT_JP[cat_key]}（n={len(sub)}）",
                                lw=2.2)
            table_html.append(f"<h4>{FAMILY_JP[fam]}（{fam}） × {CAT_JP[cat_key]}（合計n={len(sub)}）</h4>"
                               + stats_table_html(stats))
        ax.set_xscale("log")
        ax.set_title(f"{FAMILY_JP[fam]}（{fam}）", fontsize=10.5)
        ax.grid(alpha=0.25, which="both", linewidth=0.5)
        ax.set_ylim(-5, 105)
        ax.legend(loc="lower right", fontsize=8.5, frameon=False)
    for ax in axes[-1]:
        ax.set_xlabel("実測の提示割合（%, 対数軸）")
    for ax in axes[:, 0]:
        ax.set_ylabel("正答率（%）")
    fig.suptitle("清音 vs 濁音・半濁音の識別率曲線（方式ごと、本命8字+まぎれ字63字を合算）", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = os.path.join(FIG_DIR, "E_seion_dakuon.png")
    fig.savefig(path)
    plt.close(fig)
    return path, "".join(table_html)


# ---------------------------------------------------------------------------
# レポート生成
# ---------------------------------------------------------------------------
CSS = """
body{font-family:-apple-system,"Hiragino Sans","Hiragino Kaku Gothic ProN",sans-serif;
     max-width:980px;margin:2.5rem auto;padding:0 1.5rem;line-height:1.75;color:#222;}
h1{font-size:1.55rem;border-bottom:3px solid #2e5fa3;padding-bottom:.4rem;}
h2{font-size:1.25rem;margin-top:3rem;border-left:6px solid #2e5fa3;padding-left:.6rem;}
h3{font-size:1.05rem;margin-top:2rem;color:#333;}
h4{font-size:.92rem;margin-top:1.4rem;color:#555;}
.figwrap{margin:1.2rem 0 2rem;}
.figwrap img{max-width:100%;border:1px solid #ddd;border-radius:4px;}
.caption{font-size:.9rem;color:#444;background:#f4f6f8;border-left:4px solid #8aa9cc;
         padding:.6rem .9rem;margin:.5rem 0 1rem;}
.warn{font-size:.88rem;color:#7a3b1f;background:#fdf1ea;border-left:4px solid #c1473f;
      padding:.6rem .9rem;margin:.5rem 0 1rem;}
.note{font-size:.85rem;color:#666;}
table.bintab{border-collapse:collapse;font-size:.78rem;margin:.4rem 0 1.2rem;width:100%;}
table.bintab th,table.bintab td{border:1px solid #ddd;padding:3px 7px;text-align:right;}
table.bintab th{background:#eef2f6;}
table.bintab td:first-child,table.bintab th:first-child{text-align:left;}
tr.gap td{color:#999;font-style:italic;}
details{margin:.4rem 0 1.5rem;}
summary{cursor:pointer;color:#2e5fa3;font-size:.88rem;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1rem;}
.charhead{font-size:1.5rem;font-weight:700;color:#2e5fa3;}
"""


def build_report(sections):
    html = ["<!doctype html><html lang='ja'><head><meta charset='utf-8'>",
            "<title>較正フェーズ 識別率曲線（細分化）</title>",
            f"<style>{CSS}</style></head><body>"]
    html.append("<h1>較正フェーズ 識別率曲線 ― 文字×アニメーション×時間で分けて見る</h1>")
    html.append("<p class='note'>音声を途中で打ち切って「何ミリ秒聞けば何%の人が字を当てられるか」を測った"
                 "曲線 A(t) と、同じ考え方で視覚アニメーションの進み具合に対する識別率曲線 V(s) を、"
                 "文字・方式・速さの組み合わせで細かく分けて示す。1升あたりの試行数が少ない"
                 "（4〜12問、中央値8問）ため、粒度によって描き方を変えている。"
                 "A・Bは線を引き、Cは点のみで線は引かない。</p>")
    html.extend(sections)
    html.append("</body></html>")
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(html))


def img_block(path, caption_html):
    uri = fig_to_data_uri(path)
    return f"<div class='figwrap'><img src='{uri}' alt=''>{caption_html}</div>"


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    jp_font = pick_jp_font()
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.size"] = 9.5

    print("読み込み中…")
    cube_visual = load_cube_visual()
    cube_audio = load_cube_audio()
    vis_trials = load_visual_trials()
    print(f"  cube(visual) {len(cube_visual)}升 / cube(audio) {len(cube_audio)}升 / "
          f"trials(visual, 使用分) {len(vis_trials)}行")

    sections = []

    # ---- A ----
    sections.append("<h2>A. 粗い粒度 ― 方式ごとの識別率曲線（主力図）</h2>")
    sections.append("<p class='caption'>1区間あたり約120〜300問になるよう、実測値(actual_s)を"
                     "対数の等間隔で区切って束ねた。本命8字だけでなくまぎれ字（is_decoyが真の63字）も"
                     "合算している。データの無い区間は網掛けにし、線を引かず切れ目として見せている。</p>")
    a1_path, a1_table = build_A1(vis_trials)
    sections.append("<h3>A-1. 方式ごとのV(s)（対数ビン集計・95%信頼区間つき）</h3>")
    sections.append("<p class='caption'>4方式を1枚に重ねた最も主力の図。"
                     "うすい→濃い／点が増える は1〜2%あたりで急峻に立ち上がる一方、"
                     "端から現れる は同じ立ち上がりに10倍以上の実測値を要する。"
                     "点の大きさは区間内の試行数、縦のひげは95%信頼区間。</p>")
    sections.append(img_block(a1_path, ""))
    sections.append("<details><summary>区間ごとの数値を見る</summary>" + a1_table + "</details>")

    a2_path = build_A2(vis_trials, cube_visual)
    sections.append("<h3>A-2. 対数ビン集計 vs 生の水準（progress_pct）ごとの集計</h3>")
    sections.append("<p class='caption'>太線＋丸点＝対数ビン集計（主力）、細い点線＋×＝実験で刻んだ"
                     "生の水準(progress_pct)をそのまま8字・2速さで合算したもの。"
                     "両者がほぼ重なっていれば、区間まとめによる丸めの影響は小さいと読める。</p>")
    sections.append(img_block(a2_path, ""))

    a3_path = build_A3(vis_trials)
    sections.append("<h3>A-3. 方式×速さで分けた版（8本）</h3>")
    sections.append("<p class='caption'>300msと500msを線種（実線／破線）で分けた。"
                     "分割したぶん1区間あたりの試行数は約250問に下がるため、区間の本数をやや減らしている。"
                     "速さによる違いが方式による違いより小さければ、V(s)は速さにあまり依存しないと言える。</p>")
    sections.append(img_block(a3_path, ""))

    # ---- B ----
    sections.append("<h2>B. 中くらいの粒度 ― 字と方式の組み合わせ</h2>")
    sections.append("<p class='caption'>本命8字はまぎれ字と別の文字なので、この粒度では合算による"
                     "試行数の底上げはできない。1点あたり約40〜50問（対数ビンで3〜6区間に束ねたもの）。"
                     "Aの図より信頼区間は広く、傾向を読む図として扱う。</p>")

    sections.append("<h3>B-1. 方式ごとに1枚、8字を重ねる（速さ合算）</h3>")
    for fam, p in build_B_family_panels(vis_trials):
        sections.append(img_block(p, f"<p class='note'>{FAMILY_JP[fam]}（{fam}）</p>"))

    sections.append("<h3>B-2. 字ごとに1枚、4方式を重ねる（速さ合算）</h3>")
    sections.append("<p class='caption'>「どの字はどの方式で早く分かるか」を見る図。"
                     "字によって方式間の順位が入れ替わっていれば、"
                     "1つの方式だけでは全字に最適化できないことになる。</p>")
    for ch, p in build_B_char_panels(vis_trials):
        sections.append(img_block(p, f"<p class='note charhead'>{ch}</p>"))

    # ---- C ----
    sections.append("<h2>C. 細かい粒度 ― 字×方式×速さの全512升（点のみ）</h2>")
    sections.append("<p class='warn'>⚠ 1升あたり4〜12問（中央値8問）しかないため、"
                     "この粒度では線を引かない。1問の当たり外れで正答率が12〜25%動くのはノイズであって"
                     "知見ではない。点の大きさで試行数を表し、300msと500msを色分けした。</p>")
    c_path = build_C_grid(cube_visual)
    sections.append(img_block(c_path, ""))

    # ---- D ----
    sections.append("<h2>D. 聴覚 ― 字ごとの識別率曲線 A(t)</h2>")
    d_path, d_table = build_D_audio(cube_audio)
    sections.append("<p class='caption'>音声を途中で打ち切ったときの正答率。実線は全長提示での正答率が"
                     "80%以上の「使える字」（あ・か・ま・つ）、破線はそれ未満の「使えない字」"
                     "（ぱ・ら・し・が）。各点はおよそ33〜35問。凡例の（）内は全長提示時の正答率。</p>")
    sections.append(img_block(d_path, ""))
    sections.append("<details><summary>区間ごとの数値を見る</summary>" + d_table + "</details>")

    # ---- E ----
    sections.append("<h2>E. 清音 vs 濁音・半濁音 ― 方式による手がかりの伝わり方の違い</h2>")
    sections.append("<p class='warn'>⚠ まぎれ字63字（20対で検証済み）を合算して1区間あたり約300問"
                     "（清音側）〜100問前後（濁音・半濁音側）を確保した。"
                     "「端から現れる」はwipeが左→右に広がるため右上にある濁点・半濁点が最後まで出ず、"
                     "「ぼやけ」は小さい点ほどぼけに埋もれる。逆に「うすい→濃い」「点が増える」は"
                     "字全体が一様に変化するため清濁の位置に依存しない。"
                     "既存の別解析（まぎれ字63字・20対）では、清音→濁音・半濁音で立ち上がりμが動く中央値は"
                     "wipe +25.6pt（は→ば +91.3pt）、blur +16.6pt、reveal +1.3pt、fade +0.3ptだった。"
                     "以下は同じ傾向をV(s)曲線そのものとして示したもの。</p>")
    e_path, e_table = build_E_seion_dakuon(vis_trials)
    sections.append(img_block(e_path, ""))
    sections.append("<details><summary>区間ごとの数値を見る</summary>" + e_table + "</details>")

    build_report(sections)
    print(f"レポートを書き出しました: {REPORT_PATH}")
    print(f"図の枚数: {len(os.listdir(FIG_DIR))}")


if __name__ == "__main__":
    main()
