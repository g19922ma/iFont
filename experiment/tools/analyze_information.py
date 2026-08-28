#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
転写の目標を「正答率」から「情報量」に置き換える
=================================================================
丸山さんの発案（2026-08-28）。

■ なにが問題か
  聴覚で「が」を打ち切らずに全部聞かせると、66 試行中 57 が「か」と答える
  （正解は 2、正答率 3%）。本当に何も聞こえない 10ms でも正答率は 7% で、
  数字としては大差ない。しかし中身はまったく違う。
    10ms  … 答えが 40 種類にばらける（何も届いていない）
    全部  … 答えが「か」に集中する（届いているが、答えが1つ隣にずれている）
  正答率はこの2つを区別できない。応答分布の情報量なら区別できる。

  さらに、何も聞こえないときの回答は**一様分布ではない**。「つ」に偏る
  （人の事前分布）。だから「正答率0%＝情報ゼロ」も正しくない。

■ 何を測るか（3つ出して、1つを目標に選ぶ）
  ① 応答分布のエントロピー H(R|x) と実質選択肢数 2^H
       … 「何択まで絞れているか」。直感的だが、事前の偏りと届いた情報を混ぜる。
         10ms で「つ」に偏るのも、全部聞かせて「か」に偏るのも、同じく低い H になる。
  ② 事前分布からの情報利得 KL( P(R|x) ‖ P(R|事前) )
       … 事前の偏りを差し引ける。ただし「刺激と無関係に回答が動いた」場合も
         大きくなる（全員が刺激によらず「は」と答えたら、字の情報は0なのに大きい）。
  ③ 相互情報量 I(S;R) と、その**字ごとの分け前**
         D_c(x) = KL( P(R|c,x) ‖ P(R|x) )        （I = Σ_c P(c)·D_c）
       … 「その回答を見て、どの字が出たかがどれだけ分かるか」そのもの。
         基準になる P(R|x) はその水準の実測の周辺分布なので、事前の偏りは
         **自動的に差し引かれる**。何も届いていなければ 0、事前がどれだけ
         偏っていても 0。字ごとに分けられるので、字ごとの転写に直接使える。
  ⇒ **③ を転写の目標に選ぶ**。①②は比較のために全部出す。
     ⚠ 8字なので上限は H(S)=3bit。実運用の字数ではもっと大きくなる（縮尺の話）。

■ 推定の偏り（大事）
  応答は 72 択（視覚）/ 68 択（聴覚）あるのに、1セルの試行は 34〜250 しかない。
  素の（プラグイン）KL・相互情報量は**必ず上に偏る**（有限標本バイアス）。
  そこで **並べ替え検定による差し引き**を使う:
    その水準の試行のあいだで字のラベルだけを入れ替えると、真の情報量は 0 になる。
    そのときのプラグイン値の平均＝バイアスの大きさ。これを引く。
  さらに参加者単位のブートストラップで **袋詰め PAVA**（build_warp_b4.py と同じ）に
  かけ、単調な曲線にする。並べ替えは**袋ごとに引き直す**（袋の中では重複した参加者の
  ぶんだけバイアスが増えるため、外で1回引くと足りない）。

■ 前提（2026-08-27/28 に確定。build_warp_b4.py と同一）
  ・2バッチ（calib / calib2）は1つの較正実験（視覚325人・聴覚90人）
  ・ぼやけは WebKit 端末を試行単位で除外
  ・点が増える は 300ms 限定、他3方式は2水準を束ねる
  ・生の値のみ（λ正規化なし）。曲線は単調回帰（袋詰め PAVA）。外挿しない。

■ 出力（project/data_calib2_live/analysis_information/）
  prior_response_distribution.csv  事前分布そのもの（何と答えたか）
  prior_summary.csv                事前分布が一様からどれだけ離れているか
  info_by_level.csv                水準ごとの ①②③ と正答率（方式・聴覚）
  info_by_char_level.csv           字×水準の D_c（袋詰め PAVA 前後）
  curves_info.csv                  推定した単調曲線（情報量・正答率の両方）
  warp_info_vs_acc.csv             セルごとの転写（情報量版 / 正答率版）の比較
  warp_series.csv                  60fps の s(t) 系列（提案・対照1・対照2 × 2目標）
  transcribability_info.csv         32セルの成立判定（情報量版 / 正答率版）
  family_ranking.csv               方式の順位（情報量基準 / 正答率基準）
  resolution_info.csv              情報量の窓で作れる『別々の絵』の枚数
  speed_effect_info.csv            速さの効き（情報量で見た場合）

使い方:
    python3 experiment/tools/analyze_information.py
    python3 experiment/tools/analyze_information.py --bag 400 --perm 400

本番ファイル（experiment/transfer_warp.json 等）には**書かない**。
"""
import argparse
import io
import json
import math
import os
import sys
import warnings
from collections import Counter

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_warp_b4 as B4   # pava / quant_levels / glyph_stats / 定数を借りる

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHARS = B4.CHARS
FAMS = B4.FAMS
LAB = B4.LAB
GATES_MS = B4.GATES_MS
FRAME_MS = B4.FRAME_MS
BASE_ANIM_MS = B4.BASE_ANIM_MS
DURATION_MS = B4.DURATION_MS
SPEED_BY_FAM = B4.SPEED_BY_FAM
WEBKIT_FAMILIES = B4.WEBKIT_FAMILIES
EPS = 1e-12

# 回答盤（experiment/transfer_config.js の answer_grid / answer_grid_visual と同一）
GRID_AUDIO = [
    "あいうえお", "かきくけこ", "さしすせそ", "たちつてと", "なにぬねの",
    "はひふへほ", "まみむめも", "やゆよ", "らりるれろ", "わん",
    "がぎぐげご", "ざじずぜぞ", "だでど", "ばびぶべぼ", "ぱぴぷぺぽ",
]
GRID_VISUAL = [
    "あいうえお", "かきくけこ", "さしすせそ", "たちつてと", "なにぬねの",
    "はひふへほ", "まみむめも", "やゆよ", "らりるれろ", "わを", "ん", "ゔ",
    "がぎぐげご", "ざじずぜぞ", "だぢづでど", "ばびぶべぼ", "ぱぴぷぺぽ",
]
ANS_AUDIO = [c for row in GRID_AUDIO for c in row]
ANS_VISUAL = [c for row in GRID_VISUAL for c in row]


# ===========================================================================
# 情報量の道具
# ===========================================================================
def entropy_bits(counts):
    counts = np.asarray(counts, dtype=float)
    n = counts.sum()
    if n <= 0:
        return float("nan")
    p = counts[counts > 0] / n
    return float(-(p * np.log2(p)).sum())


def miller_madow(counts):
    """エントロピーの Miller-Madow 補正（見えた種類数 K̂ を使う）。"""
    counts = np.asarray(counts, dtype=float)
    n = counts.sum()
    if n <= 0:
        return float("nan")
    return entropy_bits(counts) + (np.count_nonzero(counts) - 1) / (2.0 * n * math.log(2))


def kl_bits(p_counts, q_probs):
    """KL( p̂ ‖ q )。q は 0 を含まないこと（平滑化済みを渡す）。"""
    p = np.asarray(p_counts, dtype=float)
    n = p.sum()
    if n <= 0:
        return float("nan")
    p = p / n
    m = p > 0
    return float((p[m] * np.log2(p[m] / q_probs[m])).sum())


def info_from_counts(C):
    """C[c, j, r] の数え上げから、字ごとの分け前 D と相互情報量 I を出す。

    D[c, j] = KL( P(R|c,j) ‖ P(R|j) )   … 字 c が水準 j で運んだ情報（bit）
    I[j]    = Σ_c (n_cj/n_j) · D[c, j]  … その水準の相互情報量（bit）
    """
    C = np.asarray(C, dtype=float)
    n_cj = C.sum(axis=2)                                   # (c, j)
    M = C.sum(axis=0)                                      # (j, r)
    n_j = M.sum(axis=1)                                    # (j,)
    P_r = M / np.maximum(n_j, 1.0)[:, None]                # (j, r)
    P_rc = C / np.maximum(n_cj, 1.0)[:, :, None]           # (c, j, r)
    ok = (P_rc > 0) & (P_r[None, :, :] > 0)
    term = np.zeros_like(P_rc)
    term[ok] = P_rc[ok] * np.log2(P_rc[ok] / np.broadcast_to(P_r[None, :, :], P_rc.shape)[ok])
    D = term.sum(axis=2)                                   # (c, j)
    w = n_cj / np.maximum(n_j, 1.0)[None, :]
    I = (w * D).sum(axis=0)                                # (j,)
    return D, I, n_cj, n_j


def counts_from_index(ci, ji, ri, nc, nl, nr):
    flat = (ci * nl + ji) * nr + ri
    return np.bincount(flat, minlength=nc * nl * nr).reshape(nc, nl, nr).astype(float)


# ===========================================================================
# 単調な曲線（bit を値に持つ折れ線。build_warp_b4.PLCurve の bit 版）
# ===========================================================================
class BitsCurve:
    """単調非減少の折れ線。測った範囲の外へは伸ばさない（端の値で一定）。"""

    def __init__(self, xs, ys, scale="log", out_lo=0.0, out_hi=100.0):
        self.xs = np.asarray(xs, dtype=float)
        self.ys = np.maximum.accumulate(np.asarray(ys, dtype=float))
        self.xlo, self.xhi = float(self.xs.min()), float(self.xs.max())
        self.scale = scale
        self.tx = np.log(np.maximum(self.xs, 1e-9)) if scale == "log" else self.xs.copy()
        self.out_lo, self.out_hi = out_lo, out_hi

    def _t(self, x):
        return np.log(np.maximum(x, 1e-9)) if self.scale == "log" else np.asarray(x, float)

    def v(self, x):
        x = np.clip(np.asarray(x, dtype=float), self.xlo, self.xhi)
        return np.interp(self._t(x), self.tx, self.ys)

    @property
    def top(self):
        return float(self.ys[-1])

    @property
    def bottom(self):
        return float(self.ys[0])

    def inv(self, y):
        """v(x) = y を解く（y に達する最小の x）。戻り値 (x, flag)。"""
        if self.top - self.bottom <= 1e-9:
            return (self.out_lo, "low") if y <= self.top else (self.out_hi, "high")
        if y <= self.bottom:
            return self.out_lo, "low"
        if y >= self.top:
            return self.out_hi, "high"
        j = int(np.searchsorted(self.ys, y, side="left"))
        j = min(max(j, 1), len(self.ys) - 1)
        y0, y1 = self.ys[j - 1], self.ys[j]
        if y1 - y0 <= 1e-12:
            t = self.tx[j - 1]
        else:
            t = self.tx[j - 1] + (y - y0) / (y1 - y0) * (self.tx[j] - self.tx[j - 1])
        x = math.exp(t) if self.scale == "log" else t
        return float(min(max(x, self.xlo), self.xhi)), None

    def window(self, frac_lo=0.05, frac_hi=0.95):
        """可動域の 5%〜95% に達する x（正答率版の usable span と同じ考え）。"""
        rng = self.top - self.bottom
        if rng <= 1e-9:
            return self.xlo, self.xhi
        a, _ = self.inv(self.bottom + frac_lo * rng)
        b, _ = self.inv(self.bottom + frac_hi * rng)
        return a, b


# ===========================================================================
# 読み込み（build_warp_b4.py と同じ絞り込み）
# ===========================================================================
def load(path):
    d = pd.read_csv(path, low_memory=False)
    for c in ["correct", "is_decoy", "is_filler", "is_test"]:
        if c in d.columns and d[c].dtype == object:
            d[c] = d[c].map({True: True, False: False, "TRUE": True, "FALSE": False,
                             "True": True, "False": False})
    ua = d["ua"].fillna("").astype(str)
    d["webkit"] = (
        ua.str.contains("iPhone|iPad|iPod", regex=True)
        | (ua.str.contains("Macintosh") & ua.str.contains("Safari")
           & ~ua.str.contains("Chrome|Chromium|Edg/|Firefox", regex=True)))
    n_test = int((d["is_test"] == True).sum())          # noqa: E712
    d = d[d["is_test"] != True].copy()                  # noqa: E712
    d["correct_i"] = d["correct"].astype(bool).astype(int)
    d["actual_s_pct"] = (pd.to_numeric(d["actual_s"], errors="coerce") * 100).round(4)
    d["base_anim_ms_i"] = pd.to_numeric(d["base_anim_ms"], errors="coerce")
    d["gate_ms_f"] = pd.to_numeric(d["gate_ms"], errors="coerce")
    print(f"読み込み: {os.path.relpath(path, ROOT)}  全{len(d) + n_test}行"
          f"（is_test {n_test}行を除外）")
    return d


def slices(d):
    v = d[d["modality"] == "transfer_visual"].copy()
    a = d[d["modality"] == "transfer_audio"].copy()
    vmain = v[(v["is_decoy"] != True) & (v["is_filler"] != True)          # noqa: E712
              & (v["check_kind"].isna()) & (v["target_char"].isin(CHARS))].copy()
    vdecoy = v[(v["is_decoy"] == True) & (v["check_kind"].isna())].copy()  # noqa: E712
    amain = a[(a["is_decoy"] != True) & (a["check_kind"].isna())           # noqa: E712
              & (a["target_char"].isin(CHARS))].copy()
    tail = amain["stimulus_id"].fillna("").astype(str).str.split("|").str[-1]
    amain["is_embedded_full"] = (tail == "full") & amain["gate_ms_f"].isna()
    adecoy = a[(a["is_decoy"] == True) & (a["check_kind"].isna())].copy()   # noqa: E712
    afull_all = a[(a["gate_ms_f"].isna()) & (a["target_char"].isin(CHARS))].copy()
    print(f"  視覚 本命 {len(vmain)}行 / {vmain['participant_id'].nunique()}人"
          f"（WebKit {vmain[vmain['webkit']]['participant_id'].nunique()}人）"
          f" / まぎれ字 {len(vdecoy)}行 {vdecoy['target_char'].nunique()}字")
    lad = amain[~amain["is_embedded_full"]]
    print(f"  聴覚 はしご {len(lad)}行 / {lad['participant_id'].nunique()}人"
          f" / 埋め込みfull {int(amain['is_embedded_full'].sum())}行"
          f" / まぎれ字 {len(adecoy)}行")
    return vmain, vdecoy, amain, adecoy, afull_all


def visual_rows(vmain, fam):
    s = vmain[vmain["family"] == fam]
    if SPEED_BY_FAM[fam] is not None:
        s = s[s["base_anim_ms_i"] == SPEED_BY_FAM[fam]]
    if fam in WEBKIT_FAMILIES:
        s = s[~s["webkit"]]
    return s


# ===========================================================================
# 1. 事前分布
# ===========================================================================
def prior_distributions(vmain, vdecoy, amain, adecoy, out):
    """『何も届いていないとき人は何と答えるか』を測る。

    聴覚 … 最も短い打ち切り 10ms
    視覚 … 各方式の最も薄い水準（本命8字 ＋ まぎれ字64字）
    """
    rows_dist, rows_sum = [], []

    def add(scope, modality, support, resp, note):
        c = Counter(resp)
        idx = {ch: i for i, ch in enumerate(support)}
        cnt = np.zeros(len(support))
        n_out = 0
        for ch, k in c.items():
            if ch in idx:
                cnt[idx[ch]] += k
            else:
                n_out += k
        n = cnt.sum()
        if n == 0:
            return None
        H = entropy_bits(cnt)
        Hmm = miller_madow(cnt)
        K = len(support)
        Hu = math.log2(K)
        u = np.full(K, 1.0 / K)
        kl_u = kl_bits(cnt, u)
        order = np.argsort(-cnt)
        for i in order:
            if cnt[i] > 0:
                rows_dist.append(dict(scope=scope, modality=modality, char=support[i],
                                      n=int(cnt[i]), share=cnt[i] / n))
        rows_sum.append(dict(
            scope=scope, modality=modality, n_trials=int(n), n_support=K,
            n_distinct_used=int(np.count_nonzero(cnt)),
            entropy_bits=H, entropy_bits_miller_madow=Hmm,
            entropy_uniform_bits=Hu, perplexity=2 ** H,
            perplexity_miller_madow=2 ** Hmm, perplexity_uniform=K,
            kl_from_uniform_bits=kl_u,
            gap_from_uniform_bits=Hu - H,
            top1=support[order[0]], top1_share=cnt[order[0]] / n,
            top2=support[order[1]], top2_share=cnt[order[1]] / n,
            top3=support[order[2]], top3_share=cnt[order[2]] / n,
            top5_share=float(cnt[order[:5]].sum() / n),
            n_covering_50pct=int(np.searchsorted(np.cumsum(cnt[order]) / n, 0.5) + 1),
            n_out_of_support=n_out, note=note))
        return cnt

    # --- 聴覚 10ms ---
    lad = amain[~amain["is_embedded_full"]]
    r = lad[lad["gate_ms_f"] == 10]["response_char"].dropna()
    prior_audio = add("聴覚 10ms（本命8字）", "audio", ANS_AUDIO, list(r[r != "-"]),
                      "最も短い打ち切り。刺激はほぼ無音")
    ad10 = adecoy[adecoy["gate_ms_f"] == 10]["response_char"].dropna()
    add("聴覚 10ms（本命＋まぎれ字）", "audio", ANS_AUDIO,
        list(r[r != "-"]) + list(ad10[ad10 != "-"]), "同じ 10ms を全字で束ねた版")

    # --- 視覚 いちばん薄い水準 ---
    vis_all = []
    for fam in FAMS:
        s = visual_rows(vmain, fam)
        lo = float(s["actual_s_pct"].min())
        dsub = vdecoy[vdecoy["family"] == fam]
        if fam in WEBKIT_FAMILIES:
            dsub = dsub[~dsub["webkit"]]
        if SPEED_BY_FAM[fam] is not None:
            dsub = dsub[dsub["base_anim_ms_i"] == SPEED_BY_FAM[fam]]
        rr = list(s[s["actual_s_pct"] == lo]["response_char"].dropna()) + \
             list(dsub[dsub["actual_s_pct"] == lo]["response_char"].dropna())
        rr = [x for x in rr if x != "-"]
        add(f"視覚 {LAB[fam]} {lo:g}%（本命＋まぎれ字）", "visual", ANS_VISUAL, rr,
            f"{LAB[fam]}のいちばん薄い水準")
        vis_all += rr
    prior_visual = add("視覚 4方式のいちばん薄い水準をまとめて", "visual", ANS_VISUAL,
                       vis_all, "視覚の事前分布（本文で使う値）")

    dd = pd.DataFrame(rows_dist)
    ds = pd.DataFrame(rows_sum)
    dd.to_csv(os.path.join(out, "prior_response_distribution.csv"), index=False)
    ds.to_csv(os.path.join(out, "prior_summary.csv"), index=False)
    print("\n[1] 事前分布（何も届いていないときに人が答えるもの）")
    print(ds[["scope", "n_trials", "n_support", "entropy_bits", "entropy_uniform_bits",
              "perplexity", "kl_from_uniform_bits", "top1", "top1_share",
              "n_covering_50pct"]].round(3).to_string(index=False))
    return ds, dd, prior_audio, prior_visual


# ===========================================================================
# 2. 情報量の軌跡（袋詰め PAVA ＋ 並べ替えによるバイアス差し引き）
# ===========================================================================
class InfoData:
    """1つの『場面』（方式ひとつ、または聴覚）の試行を索引配列で持つ。"""

    def __init__(self, sub, level_key, support, name, level_values=None):
        self.name = name
        self.support = support
        ridx = {c: i for i, c in enumerate(support)}
        sub = sub[sub["response_char"].notna() & (sub["response_char"] != "-")]
        sub = sub[sub["response_char"].isin(ridx)]
        sub = sub[sub[level_key].notna()]
        self.levels = np.array(sorted(sub[level_key].unique()), dtype=float) \
            if level_values is None else np.asarray(level_values, dtype=float)
        lidx = {x: j for j, x in enumerate(self.levels)}
        cidx = {c: i for i, c in enumerate(CHARS)}
        pids = sorted(sub["participant_id"].astype(str).unique())
        self.pids = pids
        pidx = {p: i for i, p in enumerate(pids)}
        self.ci = sub["target_char"].map(cidx).values.astype(int)
        self.ji = sub[level_key].astype(float).map(lidx).values.astype(int)
        self.ri = sub["response_char"].map(ridx).values.astype(int)
        self.pi = sub["participant_id"].astype(str).map(pidx).values.astype(int)
        self.correct = sub["correct_i"].values.astype(float)
        self.nc, self.nl, self.nr = len(CHARS), len(self.levels), len(support)
        self.n_trials = len(sub)
        # 参加者ごとの行番号（ブートストラップ用）
        order = np.argsort(self.pi, kind="stable")
        self.rows_by_pid = np.split(order, np.searchsorted(
            self.pi[order], np.arange(1, len(pids))))
        self.rows_of = {p: self.rows_by_pid[i] for i, p in enumerate(pids)}

    def counts(self, rows=None, ci=None):
        c = self.ci if ci is None else ci
        if rows is None:
            return counts_from_index(c, self.ji, self.ri, self.nc, self.nl, self.nr)
        return counts_from_index(c[rows], self.ji[rows], self.ri[rows],
                                 self.nc, self.nl, self.nr)

    def perm_chars(self, rng, rows=None):
        """水準の中だけで字のラベルを入れ替える（真の情報量を 0 にする）。"""
        ji = self.ji if rows is None else self.ji[rows]
        ci = (self.ci if rows is None else self.ci[rows]).copy()
        for j in range(self.nl):
            m = np.where(ji == j)[0]
            if len(m) > 1:
                ci[m] = ci[m][rng.permutation(len(m))]
        return ci

    def acc_by_level(self, rows=None):
        k = np.zeros((self.nc, self.nl))
        n = np.zeros((self.nc, self.nl))
        c = self.ci if rows is None else self.ci[rows]
        j = self.ji if rows is None else self.ji[rows]
        y = self.correct if rows is None else self.correct[rows]
        np.add.at(n, (c, j), 1.0)
        np.add.at(k, (c, j), y)
        return k, n


def bagged_info_curves(dat, bag=200, perm_per_bag=5, perm_point=200, seed=20260828,
                       scale="log"):
    """字ごとの D_c(x) を、並べ替えでバイアスを引いてから袋詰め PAVA でならす。

    戻り値
      D_raw   (c, j)  プラグイン（生）
      D_null  (c, j)  並べ替えの平均（＝バイアスの大きさ）
      D_pt    (c, j)  点推定＝生 − 並べ替え
      D_bag   (c, j)  袋詰め PAVA 後（これを曲線に使う）
      D_lo/D_hi       袋の 2.5/97.5 パーセンタイル（ばらつきの目安）
      I_raw / I_null / I_pt  (j,)  水準ごとの相互情報量
    """
    rng = np.random.default_rng(seed)
    C = dat.counts()
    D_raw, I_raw, n_cj, n_j = info_from_counts(C)
    # --- 点推定用の並べ替え（全データ上で perm_point 回） ---
    accD = np.zeros_like(D_raw)
    accI = np.zeros_like(I_raw)
    for _ in range(perm_point):
        Cp = dat.counts(ci=dat.perm_chars(rng))
        Dp, Ip, _, _ = info_from_counts(Cp)
        accD += Dp
        accI += Ip
    D_null = accD / perm_point
    I_null = accI / perm_point
    D_pt = D_raw - D_null
    I_pt = I_raw - I_null

    # --- 袋詰め PAVA（袋の中で並べ替えも引き直す） ---
    if bag <= 0:
        base = np.maximum.accumulate(
            np.vstack([B4.pava(D_pt[c], np.maximum(n_cj[c], 1e-9))
                       for c in range(dat.nc)]), axis=1)
        return dict(D_raw=D_raw, D_null=D_null, D_pt=D_pt, D_bag=np.maximum(base, 0.0),
                    D_lo=base * np.nan, D_hi=base * np.nan, I_raw=I_raw,
                    I_null=I_null, I_pt=I_pt, I_lo=I_pt * np.nan, I_hi=I_pt * np.nan,
                    n_cj=n_cj, n_j=n_j)
    P = len(dat.pids)
    draws = np.zeros((bag, dat.nc, dat.nl))
    Idraws = np.zeros((bag, dat.nl))
    for b in range(bag):
        pick = rng.integers(0, P, size=P)
        rows = np.concatenate([dat.rows_by_pid[i] for i in pick])
        Cb = dat.counts(rows=rows)
        Db, Ib, ncj_b, nj_b = info_from_counts(Cb)
        an = np.zeros_like(Db)
        anI = np.zeros_like(Ib)
        for _ in range(perm_per_bag):
            cb = dat.perm_chars(rng, rows=rows)
            Cbp = counts_from_index(cb, dat.ji[rows], dat.ri[rows],
                                    dat.nc, dat.nl, dat.nr)
            Dbp, Ibp, _, _ = info_from_counts(Cbp)
            an += Dbp
            anI += Ibp
        Db = Db - an / perm_per_bag
        Idraws[b] = Ib - anI / perm_per_bag
        for c in range(dat.nc):
            draws[b, c] = B4.pava(Db[c], np.maximum(ncj_b[c], 1e-9))
    D_bag = np.maximum(draws.mean(axis=0), 0.0)
    D_bag = np.maximum.accumulate(D_bag, axis=1)
    D_lo = np.percentile(draws, 2.5, axis=0)
    D_hi = np.percentile(draws, 97.5, axis=0)
    return dict(D_raw=D_raw, D_null=D_null, D_pt=D_pt, D_bag=D_bag,
                D_lo=D_lo, D_hi=D_hi, I_raw=I_raw, I_null=I_null, I_pt=I_pt,
                I_lo=np.percentile(Idraws, 2.5, axis=0),
                I_hi=np.percentile(Idraws, 97.5, axis=0),
                n_cj=n_cj, n_j=n_j)


def bagged_acc_curves(dat, bag=200, seed=20260828):
    """同じ袋詰め PAVA を正答率にかける（比べる相手を同じ推定法にそろえるため）。"""
    rng = np.random.default_rng(seed + 1)
    P = len(dat.pids)
    acc = np.zeros((dat.nc, dat.nl))
    for _ in range(bag):
        pick = rng.integers(0, P, size=P)
        rows = np.concatenate([dat.rows_by_pid[i] for i in pick])
        k, n = dat.acc_by_level(rows)
        for c in range(dat.nc):
            acc[c] += B4.pava(k[c] / np.maximum(n[c], 1.0), np.maximum(n[c], 1e-9))
    return np.maximum.accumulate(acc / bag, axis=1)


# ===========================================================================
# 3. 転写（逆引き）
# ===========================================================================
def invert(target_vals, cv):
    s, nlo, nhi = [], 0, 0
    for y in target_vals:
        x, fl = cv.inv(float(y))
        nlo += (fl == "low")
        nhi += (fl == "high")
        s.append(x)
    s = np.maximum.accumulate(np.array(s))
    return s, nlo, nhi


def fit_affine(ts, targ, cv):
    """対照2: 開始と速さだけ最適に合わせた直線（build_warp_b4.fit_b2 と同じ総当たり）。"""
    a = (np.arange(1, 601) * (100.0 / BASE_ANIM_MS) / 100.0 * 2.0)[:, None, None]
    b = (np.arange(-40, 41) * 0.5)[None, :, None]
    t = np.asarray(ts)[None, None, :]
    s = np.clip(a * t + b, 0.0, 100.0)
    pred = cv.v(s.ravel()).reshape(s.shape)
    e = ((pred - np.asarray(targ)[None, None, :]) ** 2).sum(axis=2)
    i, j = np.unravel_index(np.argmin(e), e.shape)
    return float(a[i, 0, 0]), float(b[0, j, 0])


def light_curves(dat, rows, perm, rng):
    """外側ブートストラップ用の軽い版。並べ替えで引いて PAVA するだけ（袋詰めなし）。"""
    C = dat.counts(rows=rows)
    D, _, ncj, _ = info_from_counts(C)
    an = np.zeros_like(D)
    for _ in range(perm):
        cb = dat.perm_chars(rng, rows=rows)
        Cp = counts_from_index(cb, dat.ji[rows], dat.ri[rows], dat.nc, dat.nl, dat.nr)
        Dp, _, _, _ = info_from_counts(Cp)
        an += Dp
    D = D - an / max(perm, 1)
    Dm = np.maximum.accumulate(np.vstack(
        [B4.pava(D[c], np.maximum(ncj[c], 1e-9)) for c in range(dat.nc)]), axis=1)
    k, n = dat.acc_by_level(rows)
    Am = np.maximum.accumulate(np.vstack(
        [B4.pava(k[c] / np.maximum(n[c], 1.0), np.maximum(n[c], 1e-9))
         for c in range(dat.nc)]), axis=1)
    return np.maximum(Dm, 0.0), Am


# ===========================================================================
# 転写の表を作る（目標が正答率でも情報量でも同じ手続き）
# ===========================================================================
def warp_table(CA, CV, tag, gates_of, ink, bw, ts, want_series=False):
    """CA[字] を目標、CV[(字,方式)] を写し先として、s(t) を逆引きする。

    tag は "info"（目標＝bit）か "acc"（目標＝正答率）。手続きは完全に同じで、
    軸に載っている量だけが違う。だから 2 つの差は「目標の選び方」だけから来る。
    """
    n_fr = len(ts)
    wrows, srows = [], []
    for fam in FAMS:
        for ch in CHARS:
            g = gates_of[ch]
            ca, cv = CA[ch], CV[(ch, fam)]
            targ = ca.v(ts)
            prop, nlo, nhi = invert(targ, cv)
            aff_a, aff_b = fit_affine(ts, targ, cv)
            b2 = np.clip(aff_a * ts + aff_b, 0.0, 100.0)
            b1 = np.clip(100.0 * ts / BASE_ANIM_MS, 0.0, 100.0)
            # 打ち切り点での値（参加者が実際に見る7点）
            tg = ca.v(g)
            pg, glo, ghi = invert(tg, cv)
            b2g = np.clip(aff_a * g + aff_b, 0.0, 100.0)
            b1g = np.clip(100.0 * g / BASE_ANIM_MS, 0.0, 100.0)
            # 目標の再現（その方式の曲線を通して測る）
            rp = float(np.sqrt(np.mean((cv.v(pg) - tg) ** 2)))
            r2 = float(np.sqrt(np.mean((cv.v(b2g) - tg) ** 2)))
            r1 = float(np.sqrt(np.mean((cv.v(b1g) - tg) ** 2)))
            try:
                nd = B4.n_distinct(B4.quant_levels(fam, ch, prop, ink, bw))
                ndg = len(np.unique(B4.quant_levels(fam, ch, pg, ink, bw)))
            except Exception:
                nd = ndg = float("nan")
            span_g = float(pg.max() - pg.min())
            # 一次変換への潰れ具合（build_warp_b4 の④と同じ）。
            # 提案の軌跡を「時間の直線」で近似した残差／可動域。
            tw = np.linspace(0.0, float(g.max()), 601)
            pw = np.interp(tw, ts, prop)
            Amat = np.vstack([tw, np.ones_like(tw)]).T
            co, *_ = np.linalg.lstsq(Amat, pw, rcond=None)
            resid = pw - Amat @ co
            free = (pw > 0.02) & (pw < 99.98)
            span_w = float(pw.max() - pw.min())
            aff = float(np.sqrt(np.mean(resid[free] ** 2))) if free.sum() > 3 \
                else float(np.sqrt(np.mean(resid ** 2)))
            rng_curve = cv.top - cv.bottom
            if span_g < 1.0:
                judge = "不成立（動かない）"
            elif (glo + ghi) > 0:
                judge = "一部成立（端で丸め）"
            else:
                judge = "成立"
            wrows.append(dict(
                target=tag, family=fam, char=ch,
                target_unit=("bit" if tag == "info" else "正答率"),
                target_at_first_gate=float(tg[0]), target_at_last_gate=float(tg[-1]),
                target_span=float(tg[-1] - tg[0]),
                visual_bottom=cv.bottom, visual_top=cv.top,
                s_min=float(prop.min()), s_max=float(prop.max()),
                span_pt=float(prop.max() - prop.min()), span_pt_gates=span_g,
                clip_low=int(nlo), clip_high=int(nhi),
                clip_low_gates=int(glo), clip_high_gates=int(ghi),
                judgement=judge,
                d_b2_gates=float(np.abs(pg - b2g).mean()),
                d_b1_gates=float(np.abs(pg - b1g).mean()),
                d_b2_frames=float(np.abs(prop - b2).mean()),
                rmse_target_proposed=rp, rmse_target_b2=r2, rmse_target_b1=r1,
                gain_over_b2=r2 - rp, gain_over_b1=r1 - rp,
                # 目標の単位が違う（正答率 vs bit）ので、曲線の可動域で割って比べる
                curve_range=rng_curve,
                gain_over_b2_rel=(r2 - rp) / max(rng_curve, 1e-9),
                rmse_target_proposed_rel=rp / max(rng_curve, 1e-9),
                affine_resid_pt=aff, affine_resid_rel=aff / max(span_w, 1e-9),
                n_distinct_images=nd, n_distinct_at_gates=ndg,
                b2_a=aff_a, b2_b=aff_b))
            for i in (range(n_fr) if want_series else ()):
                srows.append(dict(target=tag, family=fam, char=ch, frame=i,
                                  t_ms=round(ts[i], 3),
                                  target_value=round(float(targ[i]), 5),
                                  proposed_s=round(float(prop[i]), 4),
                                  baseline1_s=round(float(b1[i]), 4),
                                  baseline2_s=round(float(b2[i]), 4)))
    return wrows, srows


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(
        ROOT, "project/data_calib2_live/transfer_trials.csv"))
    ap.add_argument("--out", default=os.path.join(
        ROOT, "project/data_calib2_live/analysis_information"))
    ap.add_argument("--bag", type=int, default=200, help="袋詰め PAVA の袋の数")
    ap.add_argument("--perm", type=int, default=200, help="点推定の並べ替え回数")
    ap.add_argument("--perm-per-bag", type=int, default=5)
    ap.add_argument("--boot-rank", type=int, default=200,
                    help="方式の順位の確からしさを見る外側ブートストラップの回数")
    ap.add_argument("--boot-perm", type=int, default=20,
                    help="外側ブートストラップ1回あたりの並べ替え回数")
    ap.add_argument("--seed", type=int, default=20260828)
    ap.add_argument("--interp", choices=["log", "linear"], default="log")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    d = load(a.inp)
    vmain, vdecoy, amain, adecoy, afull_all = slices(d)

    # -----------------------------------------------------------------
    # 1. 事前分布
    # -----------------------------------------------------------------
    prior_sum, prior_dist, prior_audio_cnt, prior_visual_cnt = \
        prior_distributions(vmain, vdecoy, amain, adecoy, a.out)

    # -----------------------------------------------------------------
    # 2. 情報量の軌跡
    # -----------------------------------------------------------------
    print(f"\n[2] 情報量の軌跡（袋 {a.bag}・並べ替え 点推定{a.perm}回／袋あたり"
          f"{a.perm_per_bag}回）")
    lad = amain[~amain["is_embedded_full"]].copy()
    # 聴覚は字ごとに打ち切り時刻が違う。共通の軸として『何番目の打ち切りか』を使う。
    gi = []
    for r in lad.itertuples():
        g = GATES_MS.get(r.target_char, GATES_MS["_default"])
        gi.append(int(np.argmin(np.abs(np.array(g, float) - float(r.gate_ms_f)))))
    lad["gate_index"] = gi
    A = InfoData(lad, "gate_index", ANS_AUDIO, "audio",
                 level_values=np.arange(7, dtype=float))
    resA = bagged_info_curves(A, bag=a.bag, perm_per_bag=a.perm_per_bag,
                              perm_point=a.perm, seed=a.seed, scale=a.interp)
    accA = bagged_acc_curves(A, bag=a.bag, seed=a.seed)
    print(f"  聴覚 {A.n_trials}試行 / {len(A.pids)}人 / 打ち切り7点")

    V, resV, accV = {}, {}, {}
    for fam in FAMS:
        s = visual_rows(vmain, fam)
        V[fam] = InfoData(s, "actual_s_pct", ANS_VISUAL, fam)
        resV[fam] = bagged_info_curves(V[fam], bag=a.bag, perm_per_bag=a.perm_per_bag,
                                       perm_point=a.perm, seed=a.seed, scale=a.interp)
        accV[fam] = bagged_acc_curves(V[fam], bag=a.bag, seed=a.seed)
        print(f"  {LAB[fam]:<6} {V[fam].n_trials}試行 / {len(V[fam].pids)}人 "
              f"/ 水準{V[fam].nl}点")

    # --- 水準ごとの ①②③ をまとめる ---
    pv = prior_visual_cnt / prior_visual_cnt.sum()
    pa = prior_audio_cnt / prior_audio_cnt.sum()
    SM = 0.5   # 事前分布の平滑化（KL の分母が 0 にならないように）
    pv_s = (prior_visual_cnt + SM) / (prior_visual_cnt + SM).sum()
    pa_s = (prior_audio_cnt + SM) / (prior_audio_cnt + SM).sum()

    rows = []
    for name, dat, res, acc, prior_s, K in (
            ("audio", A, resA, accA, pa_s, len(ANS_AUDIO)),
            *[(fam, V[fam], resV[fam], accV[fam], pv_s, len(ANS_VISUAL)) for fam in FAMS]):
        C = dat.counts()
        M = C.sum(axis=0)                                  # (j, r)
        k, nn = dat.acc_by_level()
        for j, x in enumerate(dat.levels):
            cnt = M[j]
            n = cnt.sum()
            H = entropy_bits(cnt)
            # 字ごとに H を出して試行数で加重平均＝条件つきエントロピー H(R|S)。
            # analyze_families_v2.d_perplexity（perplexity_by_bin_v2.csv）と同じ数え方。
            hs = np.array([entropy_bits(C[c, j]) for c in range(dat.nc)])
            ws = np.maximum(C[:, j].sum(axis=1), 0.0)
            Hc = float(np.average(hs, weights=np.maximum(ws, 1e-9)))
            rows.append(dict(
                modality=("audio" if name == "audio" else "visual"),
                family=("" if name == "audio" else name),
                level=x,
                level_label=(f"{GATES_MS['あ'][int(x)]}〜{GATES_MS['ま'][int(x)]}ms"
                             if name == "audio" else f"{x:g}%"),
                n_trials=int(n),
                accuracy=float(k[:, j].sum() / max(nn[:, j].sum(), 1)),
                entropy_bits=H, entropy_bits_mm=miller_madow(cnt),
                perplexity=2 ** H, perplexity_uniform=K,
                cond_entropy_bits=Hc, cond_perplexity=2 ** Hc,
                kl_from_prior_bits=kl_bits(cnt, prior_s),
                mi_plugin_bits=float(res["I_raw"][j]),
                mi_null_bits=float(res["I_null"][j]),
                mi_corrected_bits=float(res["I_pt"][j]),
                mi_lo_bits=float(res["I_lo"][j]), mi_hi_bits=float(res["I_hi"][j]),
                mi_norm=float(res["I_pt"][j]) / 3.0,
                mi_from_bagged_bits=float(np.average(res["D_bag"][:, j],
                                                     weights=np.maximum(res["n_cj"][:, j], 1e-9)))))
    # --- 参照点: 聴覚「打ち切りなし」（全部聞かせる）。既存の
    #     perplexity_by_bin_v2.csv の「実質2.0択」と突き合わせる ---
    full_rows = afull_all[afull_all["response_char"].notna()
                          & (afull_all["response_char"] != "-")].copy()
    full_rows["lv0"] = 0.0
    AF = InfoData(full_rows, "lv0", ANS_AUDIO, "audio_full", level_values=[0.0])
    resAF = bagged_info_curves(AF, bag=0, perm_per_bag=1, perm_point=a.perm,
                               seed=a.seed, scale=a.interp)
    CF = AF.counts()
    cntF = CF.sum(axis=0)[0]
    kF, nF = AF.acc_by_level()
    hsF = np.array([entropy_bits(CF[c, 0]) for c in range(AF.nc)])
    HcF = float(np.average(hsF, weights=np.maximum(CF[:, 0].sum(axis=1), 1e-9)))
    rows.append(dict(
        modality="audio", family="", level=99.0, level_label="打ち切りなし",
        n_trials=int(cntF.sum()), accuracy=float(kF.sum() / max(nF.sum(), 1)),
        entropy_bits=entropy_bits(cntF), entropy_bits_mm=miller_madow(cntF),
        perplexity=2 ** entropy_bits(cntF), perplexity_uniform=len(ANS_AUDIO),
        cond_entropy_bits=HcF, cond_perplexity=2 ** HcF,
        kl_from_prior_bits=kl_bits(cntF, pa_s),
        mi_plugin_bits=float(resAF["I_raw"][0]), mi_null_bits=float(resAF["I_null"][0]),
        mi_corrected_bits=float(resAF["I_pt"][0]),
        mi_lo_bits=float("nan"), mi_hi_bits=float("nan"),
        mi_norm=float(resAF["I_pt"][0]) / 3.0,
        mi_from_bagged_bits=float(np.average(resAF["D_bag"][:, 0],
                                             weights=np.maximum(resAF["n_cj"][:, 0], 1e-9)))))
    print("\n  参照: 聴覚を打ち切らずに全部聞かせたとき（8字・"
          f"{int(cntF.sum())}試行）")
    for c, ch in enumerate(CHARS):
        sub = full_rows[full_rows["target_char"] == ch]
        cc = Counter(sub["response_char"])
        tp = cc.most_common(2)
        print(f"    {ch}  n={len(sub):>3}  正答率 {sub['correct_i'].mean():.3f}  "
              f"情報量 {resAF['D_pt'][c, 0]:.2f}bit  "
              f"最頻答 {tp[0][0]}×{tp[0][1]}"
              + (f" / {tp[1][0]}×{tp[1][1]}" if len(tp) > 1 else ""))

    lvl = pd.DataFrame(rows)
    lvl.to_csv(os.path.join(a.out, "info_by_level.csv"), index=False)
    print("\n  水準ごとの指標（相互情報量は 8字＝上限3bit）")
    print(lvl[["modality", "family", "level_label", "n_trials", "accuracy",
               "perplexity", "cond_perplexity", "kl_from_prior_bits",
               "mi_plugin_bits", "mi_null_bits", "mi_corrected_bits",
               "mi_lo_bits", "mi_hi_bits"]].round(3).to_string(index=False))

    # --- 字×水準 ---
    rows = []
    for name, dat, res, acc in (("audio", A, resA, accA),
                                *[(f, V[f], resV[f], accV[f]) for f in FAMS]):
        for c, ch in enumerate(CHARS):
            for j, x in enumerate(dat.levels):
                xm = (GATES_MS.get(ch, GATES_MS["_default"])[int(x)]
                      if name == "audio" else x)
                k, nn = dat.acc_by_level()
                rows.append(dict(
                    modality=("audio" if name == "audio" else "visual"),
                    family=("" if name == "audio" else name), char=ch,
                    level_index=j, level_x=xm,
                    n_trials=int(res["n_cj"][c, j]),
                    accuracy_raw=float(k[c, j] / max(nn[c, j], 1)),
                    accuracy_bagged=float(acc[c, j]),
                    bits_plugin=float(res["D_raw"][c, j]),
                    bits_null=float(res["D_null"][c, j]),
                    bits_corrected=float(res["D_pt"][c, j]),
                    bits_bagged=float(res["D_bag"][c, j]),
                    bits_lo=float(res["D_lo"][c, j]), bits_hi=float(res["D_hi"][c, j])))
    # 聴覚「打ち切りなし」の字ごと（レポートの見出し数値に使う）
    kF2, nF2 = AF.acc_by_level()
    for c, ch in enumerate(CHARS):
        sub = full_rows[full_rows["target_char"] == ch]
        cc = Counter(sub["response_char"])
        tp = cc.most_common(2)
        rows.append(dict(
            modality="audio", family="", char=ch, level_index=99, level_x=float("nan"),
            n_trials=int(resAF["n_cj"][c, 0]),
            accuracy_raw=float(kF2[c, 0] / max(nF2[c, 0], 1)),
            accuracy_bagged=float("nan"),
            bits_plugin=float(resAF["D_raw"][c, 0]),
            bits_null=float(resAF["D_null"][c, 0]),
            bits_corrected=float(resAF["D_pt"][c, 0]),
            bits_bagged=float(resAF["D_bag"][c, 0]),
            bits_lo=float("nan"), bits_hi=float("nan"),
            top1_char=(tp[0][0] if tp else ""), top1_n=(tp[0][1] if tp else 0),
            top2_char=(tp[1][0] if len(tp) > 1 else ""),
            top2_n=(tp[1][1] if len(tp) > 1 else 0)))
    bychar = pd.DataFrame(rows)
    bychar.to_csv(os.path.join(a.out, "info_by_char_level.csv"), index=False)

    # -----------------------------------------------------------------
    # 3. 曲線を作る
    # -----------------------------------------------------------------
    gates_of = {ch: np.array(GATES_MS.get(ch, GATES_MS["_default"]), float) for ch in CHARS}
    CA_info, CA_acc, CV_info, CV_acc = {}, {}, {}, {}
    for c, ch in enumerate(CHARS):
        g = gates_of[ch]
        CA_info[ch] = BitsCurve(g, resA["D_bag"][c], scale=a.interp,
                                out_lo=float(g.min()), out_hi=float(g.max()))
        CA_acc[ch] = BitsCurve(g, accA[c], scale=a.interp,
                               out_lo=float(g.min()), out_hi=float(g.max()))
    for fam in FAMS:
        xs = V[fam].levels
        for c, ch in enumerate(CHARS):
            CV_info[(ch, fam)] = BitsCurve(xs, resV[fam]["D_bag"][c], scale=a.interp,
                                           out_lo=0.0, out_hi=100.0)
            CV_acc[(ch, fam)] = BitsCurve(xs, accV[fam][c], scale=a.interp,
                                          out_lo=0.0, out_hi=100.0)

    crows = []
    for ch in CHARS:
        for tag, cv in (("info", CA_info[ch]), ("acc", CA_acc[ch])):
            crows.append(dict(target=tag, modality="audio", family="", char=ch,
                              xs="|".join(f"{x:g}" for x in cv.xs),
                              ys="|".join(f"{y:.5f}" for y in cv.ys),
                              bottom=cv.bottom, top=cv.top, span=cv.top - cv.bottom))
    for fam in FAMS:
        for ch in CHARS:
            for tag, cv in (("info", CV_info[(ch, fam)]), ("acc", CV_acc[(ch, fam)])):
                crows.append(dict(target=tag, modality="visual", family=fam, char=ch,
                                  xs="|".join(f"{x:g}" for x in cv.xs),
                                  ys="|".join(f"{y:.5f}" for y in cv.ys),
                                  bottom=cv.bottom, top=cv.top, span=cv.top - cv.bottom))
    pd.DataFrame(crows).to_csv(os.path.join(a.out, "curves_info.csv"), index=False)

    # -----------------------------------------------------------------
    # 4. 転写（逆引き）と比較
    # -----------------------------------------------------------------
    n_fr = int(math.ceil(DURATION_MS / FRAME_MS)) + 1
    ts = np.array([i * FRAME_MS for i in range(n_fr)])
    ink, bw = B4.glyph_stats(os.path.join(ROOT, "experiment", "base"))

    wrows, srows = [], []
    for tag, CA, CV in (("info", CA_info, CV_info), ("acc", CA_acc, CV_acc)):
        w, s = warp_table(CA, CV, tag, gates_of, ink, bw, ts, want_series=True)
        wrows += w
        srows += s
    warp = pd.DataFrame(wrows)
    warp.to_csv(os.path.join(a.out, "warp_info_vs_acc.csv"), index=False)
    pd.DataFrame(srows).to_csv(os.path.join(a.out, "warp_series.csv"), index=False)

    # 32セルの成立判定表（横に並べる）
    piv = warp.pivot_table(index=["family", "char"], columns="target",
                           values=["span_pt_gates", "n_distinct_at_gates", "gain_over_b2"],
                           aggfunc="first")
    jt = warp.pivot_table(index=["family", "char"], columns="target",
                          values="judgement", aggfunc="first")
    tab = pd.concat([jt.add_prefix("judgement_"), piv], axis=1).reset_index()
    tab.columns = ["_".join([str(x) for x in c if x != ""]) if isinstance(c, tuple) else c
                   for c in tab.columns]
    tab.to_csv(os.path.join(a.out, "transcribability_info.csv"), index=False)

    print("\n[4] 転写の成立（32セル）")
    for tag, lab in (("acc", "正答率を目標"), ("info", "情報量を目標")):
        s = warp[warp.target == tag]
        print(f"  --- {lab}")
        print(pd.crosstab(s["family"], s["judgement"]).to_string())
    print("\n  「が」だけ取り出す（正答率版では最後まで真っ白になる字）")
    print(warp[warp.char == "が"][["target", "family", "target_at_first_gate",
                                   "target_at_last_gate", "s_min", "s_max",
                                   "span_pt_gates", "n_distinct_at_gates", "judgement"]]
          .round(3).to_string(index=False))

    # -----------------------------------------------------------------
    # 5. 分解能（情報量の窓）
    # -----------------------------------------------------------------
    rrows = []
    for tag, CV in (("info", CV_info), ("acc", CV_acc)):
        for fam in FAMS:
            for ch in CHARS:
                cv = CV[(ch, fam)]
                s5, s95 = cv.window(0.05, 0.95)
                ss = np.linspace(s5, s95, 50001)
                try:
                    nd = B4.n_distinct(B4.quant_levels(fam, ch, ss, ink, bw))
                except Exception:
                    nd = float("nan")
                rng_ = cv.top - cv.bottom
                s50, _ = cv.inv(cv.bottom + 0.5 * rng_)
                rrows.append(dict(target=tag, family=fam, char=ch, s5=s5, s50=s50,
                                  s95=s95, span_s_pt=s95 - s5, curve_range=rng_,
                                  curve_bottom=cv.bottom, curve_top=cv.top,
                                  n_distinct=nd,
                                  unit_per_image=(0.9 * rng_ / max(nd - 1, 1))))
    res_df = pd.DataFrame(rrows)
    res_df.to_csv(os.path.join(a.out, "resolution_info.csv"), index=False)
    print("\n[5] 5〜95% の窓で作れる『別々の絵』の枚数（中央値）")
    print(res_df.pivot_table(index="family", columns="target", values="n_distinct",
                             aggfunc="median").round(1).to_string())

    # -----------------------------------------------------------------
    # 6. 速さの効き（情報量で見た場合）
    # -----------------------------------------------------------------
    print("\n[6] 速さの効き（300ms vs 500ms）を情報量で見る")
    sp_rows, pvals = [], []
    rng = np.random.default_rng(a.seed + 7)
    for fam in FAMS:
        s = vmain[vmain["family"] == fam]
        if fam in WEBKIT_FAMILIES:
            s = s[~s["webkit"]]
        # 「絵が実際に違う」水準だけ（analyze_families_v2.f_speed と同じ考え）
        keep = []
        for lv, g in s.groupby("actual_s_pct"):
            a3 = g[g.base_anim_ms_i == 300]["actual_frames"].astype(float)
            a5 = g[g.base_anim_ms_i == 500]["actual_frames"].astype(float)
            if len(a3) and len(a5) and abs(a3.mean() - a5.mean()) > 1e-9:
                keep.append(lv)
        s = s[s["actual_s_pct"].isin(keep)]
        if len(s) == 0:
            continue
        out_pair = {}
        for sp in (300.0, 500.0):
            sub = s[s.base_anim_ms_i == sp]
            dat = InfoData(sub, "actual_s_pct", ANS_VISUAL, f"{fam}|{sp:.0f}",
                           level_values=sorted(keep))
            r = bagged_info_curves(dat, bag=0, perm_per_bag=1, perm_point=a.perm,
                                   seed=a.seed, scale=a.interp)
            out_pair[sp] = (dat, r)
        # 水準を等重みで束ねた I の差を、参加者ブートストラップで区間推定
        i3 = float(np.mean(out_pair[300.0][1]["I_pt"]))
        i5 = float(np.mean(out_pair[500.0][1]["I_pt"]))
        # ブートストラップ
        diffs = []
        for _ in range(200):
            vals = []
            for sp in (300.0, 500.0):
                dat, r0 = out_pair[sp]
                P = len(dat.pids)
                pick = rng.integers(0, P, size=P)
                rows_ = np.concatenate([dat.rows_by_pid[i] for i in pick])
                Cb = dat.counts(rows=rows_)
                Db, Ib, _, _ = info_from_counts(Cb)
                cb = dat.perm_chars(rng, rows=rows_)
                Cbp = counts_from_index(cb, dat.ji[rows_], dat.ri[rows_],
                                        dat.nc, dat.nl, dat.nr)
                _, Ibp, _, _ = info_from_counts(Cbp)
                vals.append(float(np.mean(Ib - Ibp)))
            diffs.append(vals[1] - vals[0])
        diffs = np.array(diffs)
        p = 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())
        pvals.append(p)
        # 正答率でも同じ束ね方で
        acc3 = s[s.base_anim_ms_i == 300].groupby("actual_s_pct")["correct_i"].mean().mean()
        acc5 = s[s.base_anim_ms_i == 500].groupby("actual_s_pct")["correct_i"].mean().mean()
        sp_rows.append(dict(family=fam, family_ja=LAB[fam], n_levels=len(keep),
                            n300=int((s.base_anim_ms_i == 300).sum()),
                            n500=int((s.base_anim_ms_i == 500).sum()),
                            mi300_bits=i3, mi500_bits=i5, diff_bits=i5 - i3,
                            lo_bits=float(np.percentile(diffs, 2.5)),
                            hi_bits=float(np.percentile(diffs, 97.5)),
                            p_boot=p,
                            acc300=float(acc3), acc500=float(acc5),
                            acc_diff_pt=float((acc5 - acc3) * 100)))
    # Holm
    order = np.argsort(pvals)
    adj = np.empty(len(pvals))
    prev = 0.0
    for i, idx in enumerate(order):
        v = (len(pvals) - i) * pvals[idx]
        prev = max(prev, v)
        adj[idx] = min(1.0, prev)
    for r, pa_ in zip(sp_rows, adj):
        r["p_holm"] = float(pa_)
    sp_df = pd.DataFrame(sp_rows)
    sp_df.to_csv(os.path.join(a.out, "speed_effect_info.csv"), index=False)
    print(sp_df[["family_ja", "n300", "n500", "mi300_bits", "mi500_bits", "diff_bits",
                 "lo_bits", "hi_bits", "p_boot", "p_holm", "acc_diff_pt"]]
          .round(4).to_string(index=False))

    # -----------------------------------------------------------------
    # 7. 方式の順位
    # -----------------------------------------------------------------
    rank_rows = []
    for tag in ("acc", "info"):
        w = warp[warp.target == tag]
        r = res_df[res_df.target == tag]
        for fam in FAMS:
            ws = w[w.family == fam]
            rs = r[r.family == fam]
            sp = sp_df[sp_df.family == fam]
            cv_span = np.median([ (CV_info if tag=="info" else CV_acc)[(ch, fam)].top
                                  - (CV_info if tag=="info" else CV_acc)[(ch, fam)].bottom
                                  for ch in CHARS])
            rank_rows.append(dict(
                target=tag, family=fam, family_ja=LAB[fam],
                curve_range_median=cv_span,
                n_success=int((ws.judgement == "成立").sum()),
                n_partial=int((ws.judgement == "一部成立（端で丸め）").sum()),
                n_dead=int((ws.judgement == "不成立（動かない）").sum()),
                span_pt_gates_median=float(ws.span_pt_gates.median()),
                n_distinct_at_gates_median=float(ws.n_distinct_at_gates.median()),
                n_distinct_at_gates_min=float(ws.n_distinct_at_gates.min()),
                n_cells_gates_all7=int((ws.n_distinct_at_gates >= 7).sum()),
                n_distinct_window_median=float(rs.n_distinct.median()),
                n_distinct_window_min=float(rs.n_distinct.min()),
                unit_per_image_median=float(rs.unit_per_image.median()),
                s50_median=float(rs.s50.median()),
                d_b2_gates_mean=float(ws.d_b2_gates.mean()),
                gain_over_b2_mean=float(ws.gain_over_b2.mean()),
                gain_over_b2_rel_mean=float(ws.gain_over_b2_rel.mean()),
                affine_resid_rel_median=float(ws.affine_resid_rel.median()),
                n_cells_gain_positive=int((ws.gain_over_b2 > 0).sum()),
                rmse_target_proposed=float(ws.rmse_target_proposed.mean()),
                rmse_target_b2=float(ws.rmse_target_b2.mean()),
                speed_diff=float(sp.iloc[0]["diff_bits"] if tag == "info" and len(sp)
                                 else (sp.iloc[0]["acc_diff_pt"] / 100 if len(sp) else float("nan"))),
                speed_p_holm=float(sp.iloc[0]["p_holm"]) if len(sp) else float("nan")))
    rk = pd.DataFrame(rank_rows)
    rk.to_csv(os.path.join(a.out, "family_ranking.csv"), index=False)
    print("\n[7] 方式の順位")
    for tag, lab in (("acc", "正答率を目標にしたとき"), ("info", "情報量を目標にしたとき")):
        print(f"  --- {lab}")
        print(rk[rk.target == tag][
            ["family_ja", "curve_range_median", "n_success", "n_partial", "n_dead",
             "span_pt_gates_median", "n_distinct_at_gates_median",
             "n_distinct_at_gates_min", "n_cells_gates_all7",
             "n_distinct_window_median", "gain_over_b2_mean", "gain_over_b2_rel_mean",
             "affine_resid_rel_median", "n_cells_gain_positive"]]
            .round(3).to_string(index=False))

    # -----------------------------------------------------------------
    # 8. 順位はどれだけ確かか（参加者ブートストラップで並べ直す）
    # -----------------------------------------------------------------
    if a.boot_rank > 0:
        print(f"\n[8] 順位の確からしさ（参加者ブートストラップ {a.boot_rank} 回・"
              f"袋詰めなし・並べ替え {a.boot_perm} 回）")
        rngb = np.random.default_rng(a.seed + 31)
        vis_pids = sorted({p for fam in FAMS for p in V[fam].pids})
        aud_pids = list(A.pids)
        brows = []
        for b in range(a.boot_rank):
            pick_v = [vis_pids[i] for i in rngb.integers(0, len(vis_pids), len(vis_pids))]
            pick_a = [aud_pids[i] for i in rngb.integers(0, len(aud_pids), len(aud_pids))]
            ra = np.concatenate([A.rows_of[p] for p in pick_a if p in A.rows_of])
            Db, Ab = light_curves(A, ra, a.boot_perm, rngb)
            cA_i = {ch: BitsCurve(gates_of[ch], Db[c], scale=a.interp,
                                  out_lo=float(gates_of[ch].min()),
                                  out_hi=float(gates_of[ch].max()))
                    for c, ch in enumerate(CHARS)}
            cA_a = {ch: BitsCurve(gates_of[ch], Ab[c], scale=a.interp,
                                  out_lo=float(gates_of[ch].min()),
                                  out_hi=float(gates_of[ch].max()))
                    for c, ch in enumerate(CHARS)}
            cV_i, cV_a = {}, {}
            for fam in FAMS:
                dat = V[fam]
                rv = [dat.rows_of[p] for p in pick_v if p in dat.rows_of]
                if not rv:
                    continue
                rv = np.concatenate(rv)
                Dv, Av = light_curves(dat, rv, a.boot_perm, rngb)
                for c, ch in enumerate(CHARS):
                    cV_i[(ch, fam)] = BitsCurve(dat.levels, Dv[c], scale=a.interp,
                                                out_lo=0.0, out_hi=100.0)
                    cV_a[(ch, fam)] = BitsCurve(dat.levels, Av[c], scale=a.interp,
                                                out_lo=0.0, out_hi=100.0)
            for tag, CAx, CVx in (("info", cA_i, cV_i), ("acc", cA_a, cV_a)):
                wb = pd.DataFrame(warp_table(CAx, CVx, tag, gates_of, ink, bw, ts)[0])
                for fam in FAMS:
                    s = wb[wb.family == fam]
                    brows.append(dict(boot=b, target=tag, family=fam,
                                      gain_over_b2_rel=float(s.gain_over_b2_rel.mean()),
                                      n_success=int((s.judgement == "成立").sum()),
                                      n_dead=int((s.judgement == "不成立（動かない）").sum()),
                                      n_distinct_at_gates_median=float(
                                          s.n_distinct_at_gates.median())))
        bdf = pd.DataFrame(brows)
        bdf.to_csv(os.path.join(a.out, "family_ranking_bootstrap_raw.csv"), index=False)
        summ = []
        for tag in ("acc", "info"):
            s = bdf[bdf.target == tag]
            piv = s.pivot(index="boot", columns="family", values="gain_over_b2_rel")
            best = piv.idxmax(axis=1)
            rankm = piv.rank(axis=1, ascending=False)
            for fam in FAMS:
                g = s[s.family == fam]
                summ.append(dict(
                    target=tag, family=fam, family_ja=LAB[fam], n_boot=len(g),
                    gain_rel_mean=float(g.gain_over_b2_rel.mean()),
                    gain_rel_lo=float(np.percentile(g.gain_over_b2_rel, 2.5)),
                    gain_rel_hi=float(np.percentile(g.gain_over_b2_rel, 97.5)),
                    p_best=float((best == fam).mean()),
                    mean_rank=float(rankm[fam].mean()),
                    n_success_mean=float(g.n_success.mean()),
                    n_success_lo=float(np.percentile(g.n_success, 2.5)),
                    n_success_hi=float(np.percentile(g.n_success, 97.5)),
                    n_dead_mean=float(g.n_dead.mean()),
                    gates_median_mean=float(g.n_distinct_at_gates_median.mean())))
        sdf = pd.DataFrame(summ)
        sdf.to_csv(os.path.join(a.out, "family_ranking_bootstrap.csv"), index=False)
        for tag, lab in (("acc", "正答率を目標"), ("info", "情報量を目標")):
            print(f"  --- {lab}（gain_rel = 提案が対照2より目標に近い差 ÷ 曲線の可動域）")
            print(sdf[sdf.target == tag][
                ["family_ja", "gain_rel_mean", "gain_rel_lo", "gain_rel_hi",
                 "p_best", "mean_rank", "n_success_mean", "n_success_lo",
                 "n_success_hi", "n_dead_mean", "gates_median_mean"]]
                .round(3).to_string(index=False))

    print(f"\n完了: {os.path.relpath(a.out, ROOT)}")

    # 図を作るのに要る素材を json で残す（build_information_report.py が読む）
    payload = dict(
        chars=CHARS, fams=FAMS, lab=LAB,
        audio_levels={ch: list(map(float, gates_of[ch])) for ch in CHARS},
        visual_levels={f: list(map(float, V[f].levels)) for f in FAMS},
        audio_bits={ch: list(map(float, resA["D_bag"][c])) for c, ch in enumerate(CHARS)},
        audio_bits_raw={ch: list(map(float, resA["D_pt"][c])) for c, ch in enumerate(CHARS)},
        audio_acc={ch: list(map(float, accA[c])) for c, ch in enumerate(CHARS)},
        visual_bits={f: {ch: list(map(float, resV[f]["D_bag"][c]))
                         for c, ch in enumerate(CHARS)} for f in FAMS},
        visual_acc={f: {ch: list(map(float, accV[f][c]))
                        for c, ch in enumerate(CHARS)} for f in FAMS},
    )
    json.dump(payload, io.open(os.path.join(a.out, "figure_data.json"), "w",
                               encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
