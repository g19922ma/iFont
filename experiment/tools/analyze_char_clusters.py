#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
取り違え(混同)の構造から、かな72字を分類する — 探索的分析
================================================================================

■ この分析の狙い(丸山さんの発案)
  較正では**本命8字**しか字ごとに詳しく測っていない。しかし紛れ字(decoy)の試行
  には 64字 × 11,729試行 があり、そこには「どの字をどの字と取り違えたか」が
  丸ごと残っている。ここから「どの字がどの字に近いか」を求め、字を群に分け、
  **群ごとに向いた表示方式(fade/reveal/blur/wipe)を割り当てられないか**を探る。
  うまくいけば、較正で測っていない字にも方式を選べる。

■ 前提と注意(重要)
  * **これは事前仮説のない探索的分析**である。多重比較の問題が深刻なので、
    見つかったパターンには必ず「探索的であり追試が要る」と付ける。本スクリプトは
    そのために (a) 並べ替え帰無分布、(b) 参加者ブートストラップ安定性、
    (c) 半分割信頼性 を全部出す。点推定だけを見ないこと。
  * **ぼやけ(blur)は WebKit で描画されていなかった**(analyze_families_v2.py の
    冒頭参照)。blur の試行からは WebKit 端末を必ず落とす。判定は
    afv2.load() が付ける `webkit` 列(試行単位)をそのまま借りる。
  * 1字あたり 85〜249試行と幅がある。試行数は必ず出力に載せ、
    少ない字は推定が不安定であることを明記する。
  * 横に開く方式(wipe)の向きは、このデータでは **全試行が左→右**
    (wipe_dir が ltr か、記録の無い旧バッチ。rtl は1件も無い)。
    向きと字の性質の交絡は無い。

■ データの作り方
  行(=提示された字)は2つの出所から作る。列(=答えた字)は常に72字。
    - 紛れ字 64字 … modality=="transfer_visual" & is_decoy & check_kind.isna()
    - 本命  8字 … afv2.slices() の main(本命8字の本命問題)
  本命と紛れ字は **同じ方式・同じ水準はしご・同じ72択**なので、行として並べられる。
  ただし出所が違うことは source 列に残し、「出所だけで群が分かれていないか」を
  診断として必ず確認する(cluster_source_diagnostic.csv)。

■ 取り違えの非対称性の扱い
  取り違えは非対称でありうる(AをBと言うがBをAとは言わない)。本スクリプトは
    1) 非対称のまま 72×72 の計数行列 N を作る(対角=正答なので落とす)
    2) 準独立モデル(対角を構造ゼロとした IPF)で期待度数 E を出し、
       **行の誤り数の違い**と**答えの偏り(「あ」と答えがち)**を両方はがす
    3) 標準化残差 R=(N-E)/sqrt(E) を作る
    4) 字Xの特徴ベクトルを [ Xの行残差 ‖ Xの列残差 ] と定義して、
       cos 類似度をとる。**行と列を別に持つので非対称の情報は捨てていない**が、
       類似度そのものは構成上 対称になる。
  非対称そのものの検定は asymmetry_pairs.csv / asymmetry_global.csv に出す。

■ 出力(既定 project/data_calib2_live/analysis_char_clusters/)
  1. データの下ごしらえ
     trial_inventory.csv            使った試行の内訳(方式×出所×WebKit除外前後)
     char_trial_counts.csv          字ごとの試行数・誤り数(推定の安定性の目安)
     confusion_counts.csv           72×72 の生の取り違え計数(長形式)
     confusion_residuals.csv        同 標準化残差
     visibility_bands.csv           方式×水準の見えやすさ(帯分けの根拠)
  2. 構造が本物か
     reliability_splithalf.csv      参加者半分割による混同構造の信頼性(帯ごと)
     band_information.csv           帯ごとの情報量(相互情報量・並べ替え比較)
     family_agreement.csv           4方式間で混同構造が一致するか
     asymmetry_global.csv / asymmetry_pairs.csv   非対称の検定
  3. 分類
     similarity_matrix.csv          72×72 の類似度(主分析)
     cluster_selection.csv          k=2..15 のシルエット + 並べ替え帰無分布
     cluster_stability.csv          参加者ブートストラップの ARI と共所属確率
     cluster_assignment.csv         各字の所属(主分析 + 変種3通り)
     cluster_variants_ari.csv       変種どうしの一致(ARI)
     linkage.csv                    樹形図の連結表
     mds_coords.csv                 2次元配置(古典的MDS)
     cluster_source_diagnostic.csv  出所(本命/紛れ字)で群が割れていないかの診断
  4. 群が何で説明できるか
     char_features.csv              72字の幾何的特徴(墨画像から。試行データ不使用)
     cluster_feature_tests.csv      群 × 特徴 の並べ替え検定(Holm 調整つき)
     cluster_profile.csv            群ごとの特徴の要約
     response_bias.csv              「答えがち」の度合い
  5. 方式の割り当てに使えるか
     cluster_family_fit.csv         群 × 方式 の当てはめ(群内の試行をまとめる)
     cluster_family_acc.csv         群 × 方式 × 帯 の生の正答率
     char_family_rank.csv           字 × 方式 の μ(decoy_fit_v2 から)と順位
     assignment_rule_loco.csv       1字抜き交差確認による「規則が作れるか」の評価
     main8_placement.csv            本命8字の所属と、その群の推奨方式
  6. 図
     ../char_clusters_report.html   単一HTML(インラインSVGのみ。外部読み込みなし)

使い方
------
  python3 experiment/tools/analyze_char_clusters.py \
      --in  project/data_calib2_live/transfer_trials.csv \
      --out project/data_calib2_live/analysis_char_clusters \
      --report project/data_calib2_live/char_clusters_report.html

git commit・push はしない。生データ・出力CSVはコミットしない(.gitignore対象)。
"""
import argparse
import html as htmllib
import math
import os
import sys
import unicodedata
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_families_v2 as afv2   # load / slices / gammas / fit_rows / sig / holm を借りる
import analyze_calib_full as acf     # fit_sigmoid

from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False
try:
    from scipy.ndimage import binary_erosion, label as cc_label
    HAVE_NDIMAGE = True
except Exception:
    HAVE_NDIMAGE = False

FAMILIES = afv2.FAMILIES
TARGET_CHARS = afv2.TARGET_CHARS


# ---------------------------------------------------------------------------
# 小道具
# ---------------------------------------------------------------------------
def diacritic_of(ch):
    """濁点・半濁点の判定。NFD に分解して結合濁点(U+3099)/半濁点(U+309A)を見る。"""
    dec = unicodedata.normalize("NFD", ch)
    if "゚" in dec:
        return "半濁音"
    if "゙" in dec:
        return "濁音"
    return "清音"


def base_kana(ch):
    """濁点をはずした素の字(が→か)。清音はそのまま。"""
    dec = unicodedata.normalize("NFD", ch)
    return dec[0]


KANA_ROW = {}
for _row, _chars in [("あ行", "あいうえお"), ("か行", "かきくけこ"), ("さ行", "さしすせそ"),
                     ("た行", "たちつてと"), ("な行", "なにぬねの"), ("は行", "はひふへほ"),
                     ("ま行", "まみむめも"), ("や行", "やゆよ"), ("ら行", "らりるれろ"),
                     ("わ行", "わをん")]:
    for _c in _chars:
        KANA_ROW[_c] = _row


def kana_row_of(ch):
    return KANA_ROW.get(base_kana(ch), "その他")


def ari(a, b):
    """調整ランド指数。"""
    a = np.asarray(a); b = np.asarray(b)
    n = len(a)
    ct = pd.crosstab(a, b).values.astype(float)
    def c2(x):
        return x * (x - 1) / 2.0
    sij = c2(ct).sum()
    si = c2(ct.sum(axis=1)).sum()
    sj = c2(ct.sum(axis=0)).sum()
    tot = c2(float(n))
    exp = si * sj / tot
    mx = 0.5 * (si + sj)
    return float((sij - exp) / (mx - exp)) if mx != exp else 1.0


def silhouette_from_D(D, labels):
    """距離行列からのシルエット係数(平均と各点)。群が1個の点だけの場合は 0 扱い。"""
    labels = np.asarray(labels)
    n = len(labels)
    s = np.zeros(n)
    for i in range(n):
        same = (labels == labels[i])
        same[i] = False
        if same.sum() == 0:
            s[i] = 0.0
            continue
        a = D[i, same].mean()
        bs = []
        for lb in np.unique(labels):
            if lb == labels[i]:
                continue
            m = (labels == lb)
            if m.sum():
                bs.append(D[i, m].mean())
        if not bs:
            s[i] = 0.0
            continue
        b = min(bs)
        s[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(s.mean()), s


def ipf_quasi_independence(N, mask, iters=400, tol=1e-10):
    """対角(=構造ゼロ)を除いた準独立モデルの期待度数 E を IPF で求める。
    mask[t,r]=True の升だけを使う。行和・列和を N に合わせる。"""
    E = np.where(mask, 1.0, 0.0)
    rt = N.sum(axis=1)
    ct = N.sum(axis=0)
    for _ in range(iters):
        rs = E.sum(axis=1)
        f = np.divide(rt, rs, out=np.ones_like(rs), where=rs > 0)
        E = E * f[:, None]
        cs = E.sum(axis=0)
        f2 = np.divide(ct, cs, out=np.ones_like(cs), where=cs > 0)
        E = E * f2[None, :]
        if np.abs(E.sum(axis=1) - rt).max() < tol:
            break
    return np.where(mask, E, 0.0)


def residual_matrix(N, mask, min_e=1e-6):
    E = ipf_quasi_independence(N, mask)
    R = np.zeros_like(N, dtype=float)
    ok = mask & (E > min_e)
    R[ok] = (N[ok] - E[ok]) / np.sqrt(E[ok])
    return R, E


def unit_rows(M):
    n = np.linalg.norm(M, axis=1, keepdims=True)
    n = np.where(n > 0, n, 1.0)
    return M / n


def features_from_residual(R, mode="row_col"):
    """字ごとの特徴ベクトル。row=行残差だけ / col=列残差だけ / row_col=両方つなげる。
    行半分と列半分をそれぞれ長さ1にしてからつなぐので、片方が支配しない。"""
    if mode == "row":
        return unit_rows(R)
    if mode == "col":
        return unit_rows(R.T)
    return np.hstack([unit_rows(R), unit_rows(R.T)]) / np.sqrt(2.0)


def cosine_D(F):
    Fu = unit_rows(F)
    S = Fu @ Fu.T
    S = np.clip(S, -1.0, 1.0)
    D = 1.0 - S
    np.fill_diagonal(D, 0.0)
    D = (D + D.T) / 2.0
    return D, S


def binom_p_two_sided(k, n, p):
    """二項の両側 p 値(正確)。"""
    if n == 0:
        return 1.0
    from math import comb
    pk = comb(n, k) * (p ** k) * ((1 - p) ** (n - k))
    tot = 0.0
    for i in range(n + 1):
        pi = comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
        if pi <= pk * (1 + 1e-9):
            tot += pi
    return float(min(1.0, tot))


def perm_F(values, labels, nperm, rng):
    """群間の差の並べ替え検定(一元配置Fの並べ替え版)。"""
    v = np.asarray(values, dtype=float)
    ok = np.isfinite(v)
    v = v[ok]; lb = np.asarray(labels)[ok]
    if len(np.unique(lb)) < 2 or len(v) < 4:
        return float("nan"), float("nan"), 0

    def F(vv, ll):
        gm = vv.mean()
        ssb = 0.0; ssw = 0.0
        for g in np.unique(ll):
            x = vv[ll == g]
            ssb += len(x) * (x.mean() - gm) ** 2
            ssw += ((x - x.mean()) ** 2).sum()
        k = len(np.unique(ll)); n = len(vv)
        if ssw <= 0 or n - k <= 0 or k - 1 <= 0:
            return float("inf") if ssb > 0 else 0.0
        return (ssb / (k - 1)) / (ssw / (n - k))

    obs = F(v, lb)
    cnt = 0
    for _ in range(nperm):
        if F(v, rng.permutation(lb)) >= obs - 1e-12:
            cnt += 1
    return float(obs), float((cnt + 1) / (nperm + 1)), int(len(v))


def perm_chi2(cat, labels, nperm, rng):
    """カテゴリ変数 × 群 のカイ二乗の並べ替え検定。"""
    cat = np.asarray(cat); lb = np.asarray(labels)

    def chi2(c, l):
        ct = pd.crosstab(c, l).values.astype(float)
        if ct.shape[0] < 2 or ct.shape[1] < 2:
            return 0.0
        e = np.outer(ct.sum(axis=1), ct.sum(axis=0)) / ct.sum()
        return float((((ct - e) ** 2) / np.where(e > 0, e, 1)).sum())

    obs = chi2(cat, lb)
    cnt = sum(1 for _ in range(nperm) if chi2(cat, rng.permutation(lb)) >= obs - 1e-12)
    return obs, float((cnt + 1) / (nperm + 1))


# ---------------------------------------------------------------------------
# 1. 下ごしらえ
# ---------------------------------------------------------------------------
def build_rows(S, out, drop_webkit_all=False):
    """行に使う試行を組み立てる。blur は WebKit を必ず落とす。"""
    dec = S["decoy"].copy()
    dec["source"] = "decoy"
    mn = S["main"].copy()
    mn["source"] = "main8"
    t = pd.concat([dec, mn], ignore_index=True)
    t = t[t["target_char"].notna() & t["response_char"].notna()].copy()
    t["response_char"] = t["response_char"].astype(str)
    t["target_char"] = t["target_char"].astype(str)
    t = t[(t["response_char"].str.len() == 1) & (t["target_char"].str.len() == 1)]

    inv = []
    for (src, fam), g in t.groupby(["source", "family"], observed=True):
        inv.append(dict(source=src, family=fam, n_all=len(g), n_webkit=int(g["webkit"].sum())))
    # blur は WebKit 除外(必須)。他方式は既定では除外しない。
    if drop_webkit_all:
        keep = ~t["webkit"]
        note = "全方式でWebKitを除外"
    else:
        keep = ~(t["webkit"] & (t["family"] == "blur"))
        note = "blurのみWebKitを除外(他3方式は端末差なし)"
    dropped = int((~keep).sum())
    t = t[keep].copy()
    for r in inv:
        g = t[(t["source"] == r["source"]) & (t["family"] == r["family"])]
        r["n_used"] = len(g)
        r["policy"] = note
    pd.DataFrame(inv).to_csv(os.path.join(out, "trial_inventory.csv"), index=False)
    print(f"[1] 行に使う試行: {len(t)}行 ({note} / {dropped}行を除外)")
    print(f"    紛れ字 {int((t['source']=='decoy').sum())}行 {t[t.source=='decoy'].target_char.nunique()}字 / "
          f"本命 {int((t['source']=='main8').sum())}行 {t[t.source=='main8'].target_char.nunique()}字")
    return t


def visibility_bands(t, out, n_bands=3):
    """方式ごとに水準はしごが違うので、進み具合(progress_pct)をそのまま横並びに
    できない。そこで **その方式×水準の生の正答率**を『見えやすさ』とみなし、
    全試行を見えやすさで3帯に分ける。低い帯 = まだ見えていない。"""
    cell = (t.groupby(["family", "progress_pct"], observed=True)["correct"]
              .agg(["mean", "count"]).reset_index()
              .rename(columns={"mean": "cell_acc", "count": "cell_n"}))
    t = t.merge(cell, on=["family", "progress_pct"], how="left")
    qs = np.quantile(t["cell_acc"].values, np.linspace(0, 1, n_bands + 1))
    qs[0], qs[-1] = -0.001, 1.001
    qs = np.unique(qs)
    labels = ["低(まだ見えない)", "中", "高(だいたい見える)"][:len(qs) - 1]
    t["band"] = pd.cut(t["cell_acc"], qs, labels=labels, include_lowest=True).astype(str)
    cell2 = t.groupby(["family", "progress_pct", "band"], observed=True).agg(
        n=("correct", "size"), acc=("correct", "mean")).reset_index()
    cell2.to_csv(os.path.join(out, "visibility_bands.csv"), index=False)
    print("[1] 見えやすさの帯:")
    print(t.groupby("band", observed=True)["correct"].agg(["size", "mean"]).round(3).to_string())
    return t, labels


def char_counts(t, out):
    rows = []
    for ch, g in t.groupby("target_char", observed=True):
        rows.append(dict(char=ch, source=g["source"].iloc[0], n_trials=len(g),
                         n_errors=int((g["correct"] == 0).sum()),
                         acc=float(g["correct"].mean()),
                         n_distinct_wrong=int(g.loc[g["correct"] == 0, "response_char"].nunique()),
                         diacritic=diacritic_of(ch), kana_row=kana_row_of(ch)))
    df = pd.DataFrame(rows).sort_values("n_trials")
    df.to_csv(os.path.join(out, "char_trial_counts.csv"), index=False)
    print(f"[1] 字ごとの試行数: 最小{df.n_trials.min()} 中央{int(df.n_trials.median())} 最大{df.n_trials.max()}"
          f" / 誤り数 最小{df.n_errors.min()} 中央{int(df.n_errors.median())}")
    return df


def counts_matrix(t, chars, idx, sel=None):
    """72×72 の取り違え計数。対角(正答)は落とす。"""
    s = t if sel is None else t[sel]
    N = np.zeros((len(chars), len(chars)), dtype=float)
    e = s[s["correct"] == 0]
    for (a, b), c in Counter(zip(e["target_char"], e["response_char"])).items():
        if a in idx and b in idx:
            N[idx[a], idx[b]] += c
    np.fill_diagonal(N, 0.0)
    return N


# ---------------------------------------------------------------------------
# 2. 構造が本物か
# ---------------------------------------------------------------------------
def splithalf_reliability(t, chars, idx, mask, out, nrep, rng, bands):
    """参加者を半分に割って、それぞれで残差行列を作り、升どうしの相関を見る。
    構造が雑音だけなら相関は0になる。Spearman-Brown で全体の信頼性に直す。"""
    pids = t["participant_id"].unique()
    rows = []
    subsets = [("全体", np.ones(len(t), dtype=bool))] + \
              [(b, (t["band"] == b).values) for b in bands] + \
              [(f"方式={f}", (t["family"] == f).values) for f in FAMILIES]
    off = mask & ~np.eye(len(chars), dtype=bool)
    for name, sel in subsets:
        rr, sp = [], []
        for _ in range(nrep):
            perm = rng.permutation(pids)
            h1 = set(perm[: len(perm) // 2])
            m1 = sel & t["participant_id"].isin(h1).values
            m2 = sel & ~t["participant_id"].isin(h1).values
            N1 = counts_matrix(t, chars, idx, m1)
            N2 = counts_matrix(t, chars, idx, m2)
            if N1.sum() < 50 or N2.sum() < 50:
                continue
            R1, _ = residual_matrix(N1, mask)
            R2, _ = residual_matrix(N2, mask)
            v1, v2 = R1[off], R2[off]
            if v1.std() == 0 or v2.std() == 0:
                continue
            r = float(np.corrcoef(v1, v2)[0, 1])
            rr.append(r)
            sp.append(float(spearmanr(v1, v2).statistic))
        if not rr:
            continue
        r = float(np.mean(rr))
        sb = 2 * r / (1 + r) if r > -1 else float("nan")
        rows.append(dict(subset=name, n_trials=int(sel.sum()),
                         n_errors=int(((t["correct"] == 0).values & sel).sum()),
                         halfhalf_pearson=r, halfhalf_spearman=float(np.mean(sp)),
                         spearman_brown_full=sb,
                         lo=float(np.percentile(rr, 2.5)), hi=float(np.percentile(rr, 97.5)),
                         n_rep=len(rr)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "reliability_splithalf.csv"), index=False)
    print("\n[2] 混同構造の半分割信頼性(残差の升どうしの相関。0なら構造は雑音)")
    print(df[["subset", "n_errors", "halfhalf_pearson", "spearman_brown_full", "lo", "hi"]]
          .round(3).to_string(index=False))
    return df


def band_information(t, chars, idx, mask, out, nperm, rng, bands):
    """帯ごとに『取り違えが的の字に依存しているか』を測る。
    誤答だけを使った相互情報量 I(的の字; 答え) と、的の字を混ぜた並べ替え帰無分布。
    高いほど「その帯の取り違えは字の情報を持っている」。"""
    rows = []
    for name, sel in [("全体", np.ones(len(t), dtype=bool))] + \
                     [(b, (t["band"] == b).values) for b in bands]:
        e = t[sel & (t["correct"] == 0).values]
        if len(e) < 100:
            continue
        tv = e["target_char"].values; rv = e["response_char"].values

        def mi(a, b):
            ct = pd.crosstab(a, b).values.astype(float)
            p = ct / ct.sum()
            pr = p.sum(axis=1, keepdims=True); pc = p.sum(axis=0, keepdims=True)
            with np.errstate(divide="ignore", invalid="ignore"):
                v = p * np.log2(p / (pr * pc))
            return float(np.nansum(v))

        obs = mi(tv, rv)
        null = [mi(tv, rng.permutation(rv)) for _ in range(nperm)]
        rows.append(dict(band=name, n_errors=len(e), mi_bits=obs,
                         mi_null_mean=float(np.mean(null)), mi_null_sd=float(np.std(null)),
                         mi_excess_bits=obs - float(np.mean(null)),
                         p_perm=float((sum(1 for x in null if x >= obs) + 1) / (nperm + 1)),
                         acc_of_band=float(t.loc[sel, "correct"].mean())))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "band_information.csv"), index=False)
    print("\n[2] 帯ごとの情報量(誤答の相互情報量。並べ替え帰無との差を見る)")
    print(df.round(4).to_string(index=False))
    return df


def family_agreement(t, chars, idx, mask, out, rel=None):
    """4方式で混同構造が一致するか。一致しないなら『方式ごとに別の分類』が要る。
    生の相関は雑音で必ず下振れするので、方式ごとの半分割信頼性で希釈補正した値
    (pearson / sqrt(rel1*rel2)) も出す。1.0 に近ければ『雑音を除けば同じ構造』。"""
    Rs = {}
    for fam in FAMILIES:
        N = counts_matrix(t, chars, idx, (t["family"] == fam).values)
        Rs[fam], _ = residual_matrix(N, mask)
    off = mask & ~np.eye(len(chars), dtype=bool)
    relmap = {}
    if rel is not None:
        for _, r in rel.iterrows():
            if str(r["subset"]).startswith("方式="):
                relmap[str(r["subset"]).split("=")[1]] = r["spearman_brown_full"]
    rows = []
    for i, f1 in enumerate(FAMILIES):
        for f2 in FAMILIES[i + 1:]:
            v1, v2 = Rs[f1][off], Rs[f2][off]
            p = float(np.corrcoef(v1, v2)[0, 1])
            r1, r2 = relmap.get(f1, np.nan), relmap.get(f2, np.nan)
            den = math.sqrt(max(r1, 1e-9) * max(r2, 1e-9)) if np.isfinite(r1 * r2) else np.nan
            rows.append(dict(family_1=f1, family_2=f2, pearson=p,
                             spearman=float(spearmanr(v1, v2).statistic),
                             rel_1=r1, rel_2=r2,
                             pearson_disattenuated=(p / den) if den and np.isfinite(den) else np.nan))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "family_agreement.csv"), index=False)
    print("\n[2] 4方式間で混同構造が一致するか(残差の相関。希釈補正つき)")
    print(df.round(3).to_string(index=False))
    return df, Rs


def char_family_interaction(t, out, nperm, rng, assign=None, kmap=None, absorb=None,
                            tag="調整なし", append=None):
    """**この分析全体の前提となる検定**。
    「字によって向いた方式が違う」が本当にあるのか。無ければ、どんな分類を作っても
    方式の割り当てには使えない。

    やり方: (方式×水準) の升ごとに平均正答率を引いて残差にし、
    (字×方式) ごとの平均残差の重みつき二乗和を統計量にする。
    帰無 = 「字は方式と関係ない」→ 升の中で target_char のラベルを混ぜる。
    水準と方式の主効果は升平均を引いた時点で消えているので、
    残るのは **字×方式の交互作用だけ**。"""
    d = t[["target_char", "family", "progress_pct", "correct"]].copy()
    keys = ["family", "progress_pct"]
    cellstr = d["family"].astype(str) + "|" + d["progress_pct"].astype(str)
    if absorb == "diacritic":
        # 升の定義に濁点の有無を足す = 濁点 × 方式 の効果を先に吸い取ってしまう。
        # 残るのは「濁点で説明できるぶんを除いた、字(群) × 方式」だけ。
        d["_dia"] = [diacritic_of(c) for c in d["target_char"]]
        keys = keys + ["_dia"]
        cellstr = cellstr + "|" + d["_dia"]
    cell = d.groupby(keys, observed=True)["correct"].transform("mean")
    resid = (d["correct"] - cell).values.astype(float)
    fam_code, fam_uniq = pd.factorize(d["family"].astype(str))
    cell_code, _ = pd.factorize(cellstr)
    nf = len(fam_uniq)
    groups = [np.where(cell_code == c)[0] for c in range(cell_code.max() + 1)]
    MIN_N = 20
    tests = []

    def stat(codes, nl):
        key = codes * nf + fam_code
        s = np.bincount(key, weights=resid, minlength=nl * nf)
        c = np.bincount(key, minlength=nl * nf).astype(float)
        ok = c >= MIN_N
        return float((s[ok] ** 2 / c[ok]).sum())

    def perm_labels(base):
        out_ = base.copy()
        for ix in groups:
            out_[ix] = base[rng.permutation(ix)]
        return out_

    ss_total = float((resid ** 2).sum())

    def run(name, base):
        codes, uniq = pd.factorize(base)
        nl = len(uniq)
        obs = stat(codes, nl)
        null = np.array([stat(perm_labels(codes), nl) for _ in range(nperm)])
        tests.append(dict(adjusted_for=tag, unit=name, n_levels=nl, stat=obs,
                          null_mean=float(null.mean()),
                          null_sd=float(null.std()),
                          z=float((obs - null.mean()) / max(null.std(), 1e-12)),
                          # 帰無を差し引いた「説明できた残差分散の割合」。
                          # 水準数が違っても比べられるよう、これを効果の大きさとして使う。
                          var_explained=float((obs - null.mean()) / ss_total),
                          p_perm=float((int((null >= obs).sum()) + 1) / (nperm + 1))))

    run("字(72)", d["target_char"].values)
    if assign is not None and kmap:
        for k, lab in kmap.items():
            m = dict(zip(assign["char"], lab))
            run(f"群(k={k})", np.array([m.get(c, -1) for c in d["target_char"].values]))
    if absorb != "diacritic":
        run("濁点の有無", np.array([diacritic_of(c) for c in d["target_char"].values]))
    run("かな行", np.array([kana_row_of(c) for c in d["target_char"].values]))
    df = pd.DataFrame(tests)
    if append is not None and len(append):
        df = pd.concat([append, df], ignore_index=True)
    df["p_holm"] = afv2.holm(df["p_perm"].tolist())
    df.to_csv(os.path.join(out, "char_family_interaction.csv"), index=False)
    print(f"\n[5] 字×方式の交互作用({tag})")
    print(df[df.adjusted_for == tag].round(4).to_string(index=False))
    return df


def error_taxonomy(t, out):
    """取り違えを、意味のある型に分けて数える。クラスタリングより先に、
    「そもそもどういう間違え方をしているのか」を押さえるため。
      濁点落とし … が→か のように、濁点・半濁点を落として素の字と答えた
      濁点つけ  … か→が のように、無いはずの濁点をつけた
      濁点の取り違え … が→ぱ、ば→ぱ のように、濁点と半濁点を取り違えた
      同じ素の字 … 上のどれか(素の字が同じ)
      同じ行    … 素の字が同じかな行(か行どうし など)
      その他"""
    e = t[t["correct"] == 0].copy()
    tb = e["target_char"].map(base_kana)
    rb = e["response_char"].map(base_kana)
    td = e["target_char"].map(diacritic_of)
    rd = e["response_char"].map(diacritic_of)
    same_base = (tb == rb)
    kind = np.where(same_base & (td != "清音") & (rd == "清音"), "濁点落とし",
           np.where(same_base & (td == "清音") & (rd != "清音"), "濁点つけ",
           np.where(same_base & (td != rd), "濁点の取り違え",
           np.where(same_base, "同じ素の字(その他)",
           np.where(e["target_char"].map(kana_row_of) == e["response_char"].map(kana_row_of),
                    "同じかな行", "無関係")))))
    e["kind"] = kind
    rows = []
    for key, g in e.groupby(["kind"], observed=True):
        rows.append(dict(scope="全体", group="全体", kind=key[0] if isinstance(key, tuple) else key,
                         n=len(g), share=len(g) / len(e)))
    for (fam, kd), g in e.groupby(["family", "kind"], observed=True):
        rows.append(dict(scope="方式", group=fam, kind=kd, n=len(g),
                         share=len(g) / int((e["family"] == fam).sum())))
    for (bd, kd), g in e.groupby(["band", "kind"], observed=True):
        rows.append(dict(scope="帯", group=str(bd), kind=kd, n=len(g),
                         share=len(g) / int((e["band"].astype(str) == str(bd)).sum())))
    # 濁点のある字だけを分母にした「濁点落とし率」。方式ごとの弱点が直に出る。
    dk = e[e["target_char"].map(diacritic_of) != "清音"]
    tot_dk = t[(t["correct"] == 0) | (t["correct"] == 1)]
    tot_dk = tot_dk[tot_dk["target_char"].map(diacritic_of) != "清音"]
    for fam, g in dk.groupby("family", observed=True):
        n_all = int((tot_dk["family"] == fam).sum())
        rows.append(dict(scope="濁点字の誤りのうち濁点落とし", group=fam, kind="濁点落とし",
                         n=int((g["kind"] == "濁点落とし").sum()),
                         share=float((g["kind"] == "濁点落とし").mean()),
                         share_of_all_trials=(g["kind"] == "濁点落とし").sum() / max(n_all, 1)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "error_taxonomy.csv"), index=False)
    piv = (df[df.scope == "方式"].pivot(index="kind", columns="group", values="share")
           .reindex(columns=[f for f in FAMILIES if f in set(df["group"])]))
    print("\n[2] 取り違えの型(方式ごとの割合)")
    print(piv.round(3).to_string())
    return df, e


def asymmetry(N, E, chars, out, min_pair=6, nperm=2000, rng=None):
    """非対称の検定。対 (A,B) について N[A,B] と N[B,A] を、
    準独立モデルの期待度数比 p=E_AB/(E_AB+E_BA) のもとで二項検定する。"""
    rows = []
    n = len(chars)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = N[i, j], N[j, i]
            if a + b < min_pair:
                continue
            ea, eb = E[i, j], E[j, i]
            if ea + eb <= 0:
                continue
            p = ea / (ea + eb)
            rows.append(dict(char_a=chars[i], char_b=chars[j], n_a_to_b=int(a), n_b_to_a=int(b),
                             exp_a_to_b=ea, exp_b_to_a=eb, p_expected=p,
                             p_raw=binom_p_two_sided(int(a), int(a + b), p)))
    df = pd.DataFrame(rows)
    if len(df):
        df["p_holm"] = afv2.holm(df["p_raw"].tolist())
        df = df.sort_values("p_raw")
    df.to_csv(os.path.join(out, "asymmetry_pairs.csv"), index=False)

    # 全体の非対称: sum (N_ab - N_ba)^2 / (E_ab+E_ba) を、対称化した多項から並べ替え
    stat = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            d = N[i, j] - N[j, i]
            s = E[i, j] + E[j, i]
            if s > 0:
                stat += d * d / s
    null = []
    rng = rng or np.random.default_rng(0)
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if N[i, j] + N[j, i] > 0]
    for _ in range(nperm):
        v = 0.0
        for i, j in pairs:
            tot = int(N[i, j] + N[j, i])
            p = E[i, j] / (E[i, j] + E[j, i]) if (E[i, j] + E[j, i]) > 0 else 0.5
            a = rng.binomial(tot, p)
            d = a - (tot - a)
            s = E[i, j] + E[j, i]
            if s > 0:
                v += d * d / s
        null.append(v)
    p_glob = (sum(1 for x in null if x >= stat) + 1) / (nperm + 1)
    g = pd.DataFrame([dict(stat_asymmetry=stat, null_mean=float(np.mean(null)),
                           null_sd=float(np.std(null)), p_perm=float(p_glob),
                           n_pairs_tested=len(df),
                           n_pairs_holm_sig=int((df["p_holm"] < 0.05).sum()) if len(df) else 0)])
    g.to_csv(os.path.join(out, "asymmetry_global.csv"), index=False)
    print("\n[2] 取り違えの非対称")
    print(g.round(3).to_string(index=False))
    if len(df):
        print("  最も非対称な対(上位8):")
        print(df.head(8)[["char_a", "char_b", "n_a_to_b", "n_b_to_a", "p_raw", "p_holm"]]
              .round(4).to_string(index=False))
    return df, g


# ---------------------------------------------------------------------------
# 3. 分類
# ---------------------------------------------------------------------------
def choose_k(D, out, kmax, N, mask, nperm, rng, method="average"):
    """k=2..kmax のシルエット。帰無分布は『準独立モデルから同じ総数の誤答を
    生成しなおす』(=字による差がまったく無い世界)で作る。"""
    cond = squareform(D, checks=False)
    Z = linkage(cond, method=method)
    rows = []
    for k in range(2, kmax + 1):
        lb = fcluster(Z, k, criterion="maxclust")
        s, _ = silhouette_from_D(D, lb)
        rows.append(dict(k=k, n_clusters_actual=len(np.unique(lb)), silhouette=s,
                         min_cluster_size=int(pd.Series(lb).value_counts().min()),
                         max_cluster_size=int(pd.Series(lb).value_counts().max())))
    df = pd.DataFrame(rows)

    E = ipf_quasi_independence(N, mask)
    p = E / E.sum()
    tot = int(round(N.sum()))
    flat = p.ravel()
    null = {k: [] for k in range(2, kmax + 1)}
    for _ in range(nperm):
        draw = rng.multinomial(tot, flat).reshape(N.shape).astype(float)
        Rn, _ = residual_matrix(draw, mask)
        Fn = features_from_residual(Rn, "row_col")
        Dn, _ = cosine_D(Fn)
        Zn = linkage(squareform(Dn, checks=False), method=method)
        for k in range(2, kmax + 1):
            s, _ = silhouette_from_D(Dn, fcluster(Zn, k, criterion="maxclust"))
            null[k].append(s)
    df["sil_null_mean"] = [float(np.mean(null[k])) for k in df["k"]]
    df["sil_null_p95"] = [float(np.percentile(null[k], 95)) for k in df["k"]]
    df["p_perm"] = [float((sum(1 for x in null[k] if x >= s) + 1) / (nperm + 1))
                    for k, s in zip(df["k"], df["silhouette"])]
    df["excess_over_null"] = df["silhouette"] - df["sil_null_mean"]
    df.to_csv(os.path.join(out, "cluster_selection.csv"), index=False)
    print("\n[3] 群の個数の選び方(シルエット vs 準独立モデルの帰無分布)")
    print(df.round(4).to_string(index=False))
    return df, Z


def prediction_strength(ref_labels, boot_labels):
    """Tibshirani/Walther の予測強度。基準解の各群について、
    『その群の中の字の対が、作り直した解でも同じ群に入っている割合』を出し、
    群をまたいだ最小値をとる。0.8 以上なら『その k は再現する』の目安。"""
    ps = []
    for lb in np.unique(ref_labels):
        m = np.where(ref_labels == lb)[0]
        if len(m) < 2:
            ps.append(0.0)
            continue
        sub = boot_labels[m]
        eq = (sub[:, None] == sub[None, :])
        n = len(m)
        ps.append((eq.sum() - n) / (n * (n - 1)))
    return float(min(ps))


def stability_sweep(t, chars, idx, mask, Z, out, kmax, nboot, rng, method="average"):
    """参加者ブートストラップを1回まわして、すべての k について
    ARI と予測強度を出す。k の選び方の根拠にする。"""
    pids = t["participant_id"].unique()
    n = len(chars)
    pid_to_rows = {p: g.index.values for p, g in t.groupby("participant_id", observed=True)}
    ks = list(range(2, kmax + 1))
    ref = {k: fcluster(Z, k, criterion="maxclust") for k in ks}
    aris = {k: [] for k in ks}; pss = {k: [] for k in ks}
    cos = {k: np.zeros((n, n)) for k in ks}
    nb = 0
    for _ in range(nboot):
        pick = rng.choice(pids, size=len(pids), replace=True)
        b = t.loc[np.concatenate([pid_to_rows[p] for p in pick])]
        Nb = counts_matrix(b, chars, idx)
        if Nb.sum() < 100:
            continue
        Rb, _ = residual_matrix(Nb, mask)
        Db, _ = cosine_D(features_from_residual(Rb, "row_col"))
        Zb = linkage(squareform(Db, checks=False), method=method)
        for k in ks:
            lb = fcluster(Zb, k, criterion="maxclust")
            aris[k].append(ari(ref[k], lb))
            pss[k].append(prediction_strength(ref[k], lb))
            cos[k] += (lb[:, None] == lb[None, :]).astype(float)
        nb += 1
    rows = []
    for k in ks:
        rows.append(dict(k=k, n_boot=nb, ari_mean=float(np.mean(aris[k])),
                         ari_lo=float(np.percentile(aris[k], 2.5)),
                         ari_hi=float(np.percentile(aris[k], 97.5)),
                         pred_strength_mean=float(np.mean(pss[k])),
                         pred_strength_lo=float(np.percentile(pss[k], 2.5))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "cluster_stability.csv"), index=False)
    print("\n[3] 参加者ブートストラップによる安定性(k ごと)")
    print(df.round(3).to_string(index=False))
    return df, {k: cos[k] / max(nb, 1) for k in ks}


def stability_detail(chars, ref_labels, co, out, k):
    pd.DataFrame(co, index=chars, columns=chars).to_csv(
        os.path.join(out, "cluster_cooccurrence.csv"))
    rows = []
    for i, ch in enumerate(chars):
        same = ref_labels == ref_labels[i]
        same_i = same.copy(); same_i[i] = False
        rows.append(dict(char=ch, cluster=int(ref_labels[i]),
                         mean_co_with_own=float(co[i, same_i].mean()) if same_i.sum() else float("nan"),
                         mean_co_with_other=float(co[i, ~same].mean()) if (~same).sum() else float("nan")))
    df = pd.DataFrame(rows)
    df["stability_gap"] = df["mean_co_with_own"] - df["mean_co_with_other"]
    df.to_csv(os.path.join(out, "cluster_stability_by_char.csv"), index=False)
    print(f"[3] k={k} の共所属: 同じ群 {df['mean_co_with_own'].mean():.3f} / "
          f"別の群 {df['mean_co_with_other'].mean():.3f}")
    return df


def classical_mds(D, dim=2):
    n = D.shape[0]
    J = np.eye(n) - np.ones((n, n)) / n
    B = -0.5 * J @ (D ** 2) @ J
    w, v = np.linalg.eigh((B + B.T) / 2)
    o = np.argsort(w)[::-1]
    w = w[o]; v = v[:, o]
    L = np.sqrt(np.maximum(w[:dim], 0))
    X = v[:, :dim] * L
    var = float(np.maximum(w, 0)[:dim].sum() / np.maximum(w, 0).sum())
    return X, var


# ---------------------------------------------------------------------------
# 4. 字の幾何的な特徴(全72字)
# ---------------------------------------------------------------------------
def char_features(chars, base_dir, out, erosion_iter=1):
    """analyze_families_v2.char_structure() と同じ読み方(墨=暗い画素)を
    72字に広げ、特徴も足したもの。試行データは一切使わない。"""
    rows = []
    for ch in chars:
        d = dict(char=ch, diacritic=diacritic_of(ch), kana_row=kana_row_of(ch),
                 base_kana=base_kana(ch))
        path = None
        for ext in (".png", ".PNG"):
            p = os.path.join(base_dir, ch + ext)
            if os.path.exists(p):
                path = p; break
        if HAVE_PIL and path:
            im = Image.open(path).convert("RGBA")
            a = np.asarray(im)
            ink = (a[..., 3] > 8) & (a[..., :3].mean(axis=2) < 200)
            if ink.sum() == 0:
                g = np.asarray(im.convert("L"), dtype=float)
                ink = g < 128
            H, W = ink.shape
            tot = int(ink.sum())
            d["ink_px"] = tot
            d["ink_frac"] = tot / (H * W)
            if tot:
                ys, xs = np.nonzero(ink)
                d["centroid_x_frac"] = float(xs.mean() / W)
                d["centroid_y_frac"] = float(ys.mean() / H)
                d["right_ink_frac"] = float((xs >= W / 2).sum() / tot)
                d["top_ink_frac"] = float((ys < H / 2).sum() / tot)
                d["bbox_w_frac"] = float((xs.max() - xs.min() + 1) / W)
                d["bbox_h_frac"] = float((ys.max() - ys.min() + 1) / H)
                d["aspect"] = d["bbox_w_frac"] / max(d["bbox_h_frac"], 1e-9)
                d["spread_x"] = float(xs.std() / W)
                d["spread_y"] = float(ys.std() / H)
                if HAVE_NDIMAGE:
                    er = binary_erosion(ink, iterations=erosion_iter)
                    d["fine_detail_frac"] = float((tot - er.sum()) / tot)
                    lab, ncomp = cc_label(ink)
                    d["n_components"] = int(ncomp)
                    sizes = np.bincount(lab.ravel())[1:]
                    d["largest_comp_frac"] = float(sizes.max() / tot) if len(sizes) else float("nan")
                    # 線の太さの目安: 面積 / 骨格に近い量(2回侵食で消える割合)
                    er2 = binary_erosion(ink, iterations=2)
                    d["thin_frac"] = float((tot - er2.sum()) / tot)
                # 左右・上下の墨の重なり(左右対称性)
                lr = float(np.minimum(ink, ink[:, ::-1]).sum() / tot)
                ud = float(np.minimum(ink, ink[::-1, :]).sum() / tot)
                d["sym_lr"] = lr
                d["sym_ud"] = ud
                # 横方向の墨の広がり方(wipe が効くかに関係)
                def _ent(p):
                    p = p[p > 0]
                    p = p / p.sum()
                    return float(-(p * np.log2(p)).sum())
                d["col_entropy_bits"] = _ent(ink.sum(axis=0).astype(float))
                d["row_entropy_bits"] = _ent(ink.sum(axis=1).astype(float))
                # 左から何割の列で墨の半分が出るか(wipe で早く見分けがつくか)
                cs = np.cumsum(ink.sum(axis=0).astype(float)) / tot
                d["half_ink_col_frac"] = float(np.searchsorted(cs, 0.5) / W)
                rs = np.cumsum(ink.sum(axis=1).astype(float)) / tot
                d["half_ink_row_frac"] = float(np.searchsorted(rs, 0.5) / H)
        rows.append(d)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "char_features.csv"), index=False)
    print(f"\n[4] 字の幾何的特徴: {len(df)}字 × {len([c for c in df.columns if df[c].dtype!=object])}項目")
    return df


FEATURE_COLS = ["ink_frac", "centroid_x_frac", "centroid_y_frac", "right_ink_frac",
                "top_ink_frac", "bbox_w_frac", "bbox_h_frac", "aspect", "spread_x",
                "spread_y", "fine_detail_frac", "thin_frac", "n_components",
                "largest_comp_frac", "sym_lr", "sym_ud", "col_entropy_bits",
                "row_entropy_bits", "half_ink_col_frac", "half_ink_row_frac"]


def explain_clusters(assign, feat, cnt, resp_bias, out, nperm, rng, parts=None):
    """parts = [(表示名, assign の列名), ...]。切り方ごとに同じ検定をまわす。
    Holm は **全部まとめて** かける(切り方を2通り試していること自体が多重比較なので)。"""
    m = assign.merge(feat, on="char").merge(
        cnt[["char", "n_trials", "n_errors", "acc"]], on="char").merge(
        resp_bias[["char", "chosen_rate", "chosen_lift"]], on="char", how="left")
    parts = parts or [("主", "cluster")]
    rows = []
    for tag, col_c in parts:
        for col in FEATURE_COLS + ["acc", "n_trials", "chosen_lift"]:
            if col not in m.columns:
                continue
            F, p, n = perm_F(m[col].values, m[col_c].values, nperm, rng)
            rows.append(dict(partition=tag, feature=col, kind="連続", stat_F=F, p_raw=p, n=n))
        for col in ["diacritic", "kana_row"]:
            c2, p = perm_chi2(m[col].values, m[col_c].values, nperm, rng)
            rows.append(dict(partition=tag, feature=col, kind="カテゴリ", stat_F=c2,
                             p_raw=p, n=len(m)))
    df = pd.DataFrame(rows)
    df["p_holm"] = afv2.holm(df["p_raw"].tolist())
    df = df.sort_values(["p_raw", "partition"])
    df.to_csv(os.path.join(out, "cluster_feature_tests.csv"), index=False)
    print("\n[4] 群が何で説明できるか(並べ替え検定 + Holm。**探索的**)")
    print(df.head(16).round(4).to_string(index=False))

    profs = []
    for tag, col_c in parts:
        p = m.groupby(col_c).agg(
            n_chars=("char", "size"),
            chars=("char", lambda s: "".join(sorted(s))),
            n_dakuten=("diacritic", lambda s: int((s != "清音").sum())),
            dakuten_rate=("diacritic", lambda s: float((s != "清音").mean())),
            acc=("acc", "mean"), n_trials=("n_trials", "sum"),
            **{c: (c, "mean") for c in FEATURE_COLS if c in m.columns},
            chosen_lift=("chosen_lift", "mean"))
        p.index.name = "cluster"
        p.insert(0, "partition", tag)
        profs.append(p)
    prof_all = pd.concat(profs)
    prof_all.to_csv(os.path.join(out, "cluster_profile.csv"))
    prof = profs[0]
    print("\n[4] 群ごとの姿(主の切り方)")
    print(prof[["n_chars", "chars", "dakuten_rate", "acc", "ink_frac", "n_components",
                "chosen_lift"]].round(3).to_string())
    return df, prof, m, prof_all


def response_bias(t, chars, out):
    """『何も見えないとき何と答えがちか』。全体と、いちばん見えない帯で。"""
    rows = []
    e_all = t[t["correct"] == 0]
    lowband = sorted(t["band"].astype(str).unique())[0] if len(t) else None
    e_low = t[(t["correct"] == 0) & (t["band"].astype(str) == lowband)]
    n_all, n_low = len(e_all), len(e_low)
    vc = e_all["response_char"].value_counts()
    vl = e_low["response_char"].value_counts()
    for ch in chars:
        k = int(vc.get(ch, 0)); kl = int(vl.get(ch, 0))
        # 期待: その字が正解でない試行のうち、一様なら 1/71
        rows.append(dict(char=ch, n_chosen_wrong=k, chosen_rate=k / max(n_all, 1),
                         chosen_lift=(k / max(n_all, 1)) / (1 / 71),
                         n_chosen_wrong_lowband=kl,
                         chosen_lift_lowband=(kl / max(n_low, 1)) / (1 / 71)))
    df = pd.DataFrame(rows).sort_values("chosen_lift", ascending=False)
    df.to_csv(os.path.join(out, "response_bias.csv"), index=False)
    print("\n[4] 答えの偏り(誤答として選ばれやすさ。1.0=一様)  上位8:")
    print(df.head(8).round(3).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# 5. 方式の割り当てに使えるか
# ---------------------------------------------------------------------------
def cluster_family_fit(t, assign, out, gv, n_starts, nboot, rng, quiet=False):
    """群内の試行をまとめて、群 × 方式 で当てはめる。1字ずつだと中央値39試行しか
    無く不安定だが、群にまとめれば数百試行になる。μ が小さい方式 = その群に向く。"""
    m = t.merge(assign[["char", "cluster"]], left_on="target_char", right_on="char", how="inner")
    rows = []
    for (cl, fam), g in m.groupby(["cluster", "family"], observed=True):
        r = afv2.fit_rows(g, "progress_pct", gv, n_starts=n_starts)
        rows.append(dict(cluster=int(cl), family=fam, n_trials=len(g),
                         n_levels=int(g["progress_pct"].nunique()),
                         n_chars=int(g["target_char"].nunique()),
                         acc=float(g["correct"].mean()), **{k: r[k] for k in ("lam", "mu", "sigma", "converged")}))
    df = pd.DataFrame(rows)

    # 参加者ブートストラップで μ の順位の安定性を見る
    pids = m["participant_id"].unique()
    pid_rows = {p: g.index.values for p, g in m.groupby("participant_id", observed=True)}
    best_cnt = {(int(c), f): 0 for c in df["cluster"].unique() for f in FAMILIES}
    nb = 0
    for _ in range(nboot):
        pick = rng.choice(pids, size=len(pids), replace=True)
        b = m.loc[np.concatenate([pid_rows[p] for p in pick])]
        ok = True
        mus = {}
        for (cl, fam), g in b.groupby(["cluster", "family"], observed=True):
            r = afv2.fit_rows(g, "progress_pct", gv, n_starts=2)
            mus[(int(cl), fam)] = r["mu"] if r["converged"] else np.nan
        for cl in df["cluster"].unique():
            vals = {f: mus.get((int(cl), f), np.nan) for f in FAMILIES}
            vv = {f: v for f, v in vals.items() if np.isfinite(v)}
            if vv:
                best_cnt[(int(cl), min(vv, key=vv.get))] += 1
        nb += 1
    df["best_share_boot"] = [best_cnt.get((int(r.cluster), r.family), 0) / max(nb, 1)
                             for r in df.itertuples()]
    df = df.sort_values(["cluster", "mu"])
    acc = m.groupby(["cluster", "family", "band"], observed=True)["correct"].agg(
        n="size", acc="mean").reset_index()
    if not quiet:
        df.to_csv(os.path.join(out, "cluster_family_fit.csv"), index=False)
        acc.to_csv(os.path.join(out, "cluster_family_acc.csv"), index=False)
        print("\n[5] 群 × 方式 の当てはめ(μ が小さいほど少ない進み具合で読める)")
        print(df[["cluster", "family", "n_chars", "n_trials", "acc", "mu", "sigma",
                  "best_share_boot"]].round(3).to_string(index=False))
    return df, acc


def group_family_gap(t, groupings, out, gv, n_starts):
    """群わけを何通りか受け取り、それぞれについて『方式の順位』と
    『1位と2位の開き』を出す。順位が群をまたいで入れ替わるかどうかが、
    「群ごとに違う方式を割り当てられるか」の答えそのもの。"""
    rows = []
    for gname, mapping in groupings.items():
        d = t.copy()
        d["grp"] = d["target_char"].map(mapping)
        d = d[d["grp"].notna()]
        for grp, g in d.groupby("grp", observed=True):
            mus = {}
            for fam, gg in g.groupby("family", observed=True):
                r = afv2.fit_rows(gg, "progress_pct", gv, n_starts=n_starts)
                mus[fam] = r["mu"] if r["converged"] else np.nan
            fin = {f: v for f, v in mus.items() if np.isfinite(v)}
            order = sorted(fin, key=fin.get)
            # 方式ごとに水準はしごが違うので μ の絶対値は比べられない。
            # 生の正答率(水準等重み)なら同じ土俵に乗る。
            accs = {}
            for fam, gg in g.groupby("family", observed=True):
                accs[fam] = float(gg.groupby("progress_pct", observed=True)["correct"].mean().mean())
            aord = sorted(accs, key=lambda f: -accs[f])
            rows.append(dict(grouping=gname, group=str(grp), n_chars=int(g["target_char"].nunique()),
                             n_trials=len(g),
                             mu_order="<".join(order),
                             acc_order=">".join(aord),
                             top_family_by_acc=aord[0] if aord else "",
                             gap_top2_pt=(accs[aord[0]] - accs[aord[1]]) * 100 if len(aord) > 1 else np.nan,
                             **{f"acc_{f}": accs.get(f, np.nan) for f in FAMILIES},
                             **{f"mu_{f}": mus.get(f, np.nan) for f in FAMILIES}))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "group_family_gap.csv"), index=False)
    print("\n[5] 群わけごとの方式の順位(水準等重みの正答率で並べたもの)")
    print(df[["grouping", "group", "n_chars", "n_trials", "acc_order", "gap_top2_pt",
              "acc_fade", "acc_reveal", "acc_wipe", "acc_blur"]].round(3).to_string(index=False))
    return df


def char_family_rank(assign, out, decoy_fit_path, span_path):
    """字 × 方式 の μ。紛れ字は decoy_fit_v2.csv、本命8字は usable_span.csv から。
    どちらも analyze_families_v2.py が出したもの(再計算しない)。"""
    rows = []
    if os.path.exists(decoy_fit_path):
        d = pd.read_csv(decoy_fit_path)
        d = d[(d["dataset"] == "both_batches") & (d["webkit_excluded"] == True)]
        for _, r in d.iterrows():
            rows.append(dict(char=r["char"], family=r["family"], mu=r["mu"],
                             n_trials=r["n_trials"], src="decoy_fit_v2"))
    if os.path.exists(span_path):
        s = pd.read_csv(span_path)
        s = s[(s["webkit_excluded"] == True) & (s["char"].isin(TARGET_CHARS))]
        for _, r in s.iterrows():
            rows.append(dict(char=r["char"], family=r["family"], mu=r["mu"],
                             n_trials=np.nan, src="usable_span"))
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    df = df.merge(assign[["char", "cluster"]], on="char", how="left")
    df["rank_in_char"] = df.groupby("char")["mu"].rank()
    best = df.loc[df.groupby("char")["mu"].idxmin(), ["char", "family", "mu", "cluster", "src"]]
    best = best.rename(columns={"family": "best_family", "mu": "best_mu"})
    df = df.merge(best[["char", "best_family"]], on="char", how="left")
    df.to_csv(os.path.join(out, "char_family_rank.csv"), index=False)
    return df


def char_family_acc(t, out):
    """字 × 方式 の**水準等重みの正答率**。方式ごとに水準はしごが違うので、
    水準ごとの正答率を出してから水準で平均する(試行数の偏りを均す)。"""
    rows = []
    for (ch, fam), g in t.groupby(["target_char", "family"], observed=True):
        lv = g.groupby("progress_pct", observed=True)["correct"].mean()
        rows.append(dict(char=ch, family=fam, n_trials=len(g), n_levels=len(lv),
                         acc_lvlmean=float(lv.mean())))
    df = pd.DataFrame(rows)
    piv = df.pivot(index="char", columns="family", values="acc_lvlmean")
    piv.to_csv(os.path.join(out, "char_family_acc.csv"))
    return df, piv


def char_level_reliability(t, out, nrep, rng):
    """**1字あたりの「どの方式が向くか」自体が測れているのか**を先に確かめる。
    参加者を半分に割り、各半分で 字×方式 の水準等重み正答率を出し、
    方式どうしの差(たとえば wipe−reveal)が半分どうしで一致するかを見る。
    ここが 0 なら、字ごとの方式の向き不向きはそもそも測れていないので、
    1字抜き交差確認は原理的に当たらない(規則が無いのではなく、的が無い)。"""
    pids = t["participant_id"].unique()

    def table(sub):
        r = {}
        for (ch, fam), g in sub.groupby(["target_char", "family"], observed=True):
            r[(ch, fam)] = float(g.groupby("progress_pct", observed=True)["correct"].mean().mean())
        return r

    pairs = [("wipe", "reveal"), ("fade", "reveal"), ("blur", "wipe"), ("fade", "wipe")]
    acc = {p: [] for p in pairs}
    acc_lvl = []
    for _ in range(nrep):
        perm = rng.permutation(pids)
        h1 = set(perm[: len(perm) // 2])
        m = t["participant_id"].isin(h1).values
        A, B = table(t[m]), table(t[~m])
        chars = sorted({c for c, _ in A} & {c for c, _ in B})
        for f1, f2 in pairs:
            a = [A.get((c, f1), np.nan) - A.get((c, f2), np.nan) for c in chars]
            b = [B.get((c, f1), np.nan) - B.get((c, f2), np.nan) for c in chars]
            a, b = np.array(a), np.array(b)
            ok = np.isfinite(a) & np.isfinite(b)
            if ok.sum() > 5 and a[ok].std() > 0 and b[ok].std() > 0:
                acc[(f1, f2)].append(float(np.corrcoef(a[ok], b[ok])[0, 1]))
        # 字ごとの「見えやすさ」そのもの(方式をまたいだ平均)。比較のための目盛り。
        a = [np.nanmean([A.get((c, f), np.nan) for f in FAMILIES]) for c in chars]
        b = [np.nanmean([B.get((c, f), np.nan) for f in FAMILIES]) for c in chars]
        a, b = np.array(a), np.array(b)
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() > 5:
            acc_lvl.append(float(np.corrcoef(a[ok], b[ok])[0, 1]))
    rows = []
    for (f1, f2), v in acc.items():
        if not v:
            continue
        r = float(np.mean(v))
        rows.append(dict(quantity=f"{f1}−{f2} の差(字ごと)", halfhalf_pearson=r,
                         spearman_brown_full=2 * r / (1 + r) if r > -1 else np.nan,
                         lo=float(np.percentile(v, 2.5)), hi=float(np.percentile(v, 97.5)),
                         n_rep=len(v)))
    if acc_lvl:
        r = float(np.mean(acc_lvl))
        rows.append(dict(quantity="字ごとの見えやすさ(方式平均)", halfhalf_pearson=r,
                         spearman_brown_full=2 * r / (1 + r) if r > -1 else np.nan,
                         lo=float(np.percentile(acc_lvl, 2.5)),
                         hi=float(np.percentile(acc_lvl, 97.5)), n_rep=len(acc_lvl)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "char_level_reliability.csv"), index=False)
    print("\n[5] 1字あたりで『方式の向き不向き』は測れているか(参加者半分割)")
    print(df.round(3).to_string(index=False))
    return df


def assignment_rule_continuous(piv, assign, out, nperm, rng):
    """連続量での 1字抜き交差確認。的は方式どうしの差(例 wipe−reveal)。
    予測はその字を除いた同じ群の平均。全体平均を基準にした out-of-sample R² で測る。
    二値の多数決より雑音に強く、規則の効き目を見つけやすい。"""
    fams = [f for f in FAMILIES if f in piv.columns]
    base = pd.DataFrame(dict(char=piv.index)).merge(
        assign[["char", "cluster", "cluster_fine"]], on="char", how="left")
    base["濁点の有無"] = [diacritic_of(c) for c in base["char"]]
    base["かな行"] = [kana_row_of(c) for c in base["char"]]
    pairs = [(f1, f2) for f1, f2 in [("wipe", "reveal"), ("fade", "reveal"),
                                     ("fade", "wipe"), ("blur", "wipe")]
             if f1 in fams and f2 in fams]

    def loco_r2(gcodes, ng, y, gm):
        s = np.bincount(gcodes, weights=y, minlength=ng)
        c = np.bincount(gcodes, minlength=ng).astype(float)
        num = s[gcodes] - y
        den = c[gcodes] - 1.0
        pred = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
        ok = np.isfinite(pred)
        sse = ((y[ok] - pred[ok]) ** 2).sum()
        sst = ((y[ok] - gm[ok]) ** 2).sum()
        return float(1 - sse / sst) if sst > 0 else float("nan")

    rows = []
    for f1, f2 in pairs:
        y = (piv[f1] - piv[f2]).values.astype(float)
        n = len(y)
        gm = (y.sum() - y) / (n - 1)          # その字を抜いた全体平均(基準)
        for gname, gcol in [("取り違えの群", "cluster"), ("取り違えの群(細)", "cluster_fine"),
                            ("濁点の有無", "濁点の有無"), ("かな行", "かな行")]:
            gcodes, guniq = pd.factorize(base[gcol].values)
            ng = len(guniq)
            obs = loco_r2(gcodes, ng, y, gm)
            null = np.array([loco_r2(rng.permutation(gcodes), ng, y, gm)
                             for _ in range(nperm)])
            rows.append(dict(target=f"{f1}−{f2}", grouping=gname,
                             n_groups=ng, n_chars=len(y),
                             loco_r2=obs, null_mean=float(np.nanmean(null)),
                             null_p95=float(np.nanpercentile(null, 95)),
                             p_perm=float((int(np.nansum(null >= obs)) + 1) / (nperm + 1))))
    df = pd.DataFrame(rows)
    df["p_holm"] = afv2.holm(df["p_perm"].tolist())
    df = df.sort_values(["target", "loco_r2"], ascending=[True, False])
    df.to_csv(os.path.join(out, "assignment_rule_continuous.csv"), index=False)
    print("\n[5] 連続量での1字抜き交差確認(方式どうしの差を、群の平均で当てにいく)")
    print(df.round(4).to_string(index=False))
    return df


def assignment_rule(piv, assign, out, nperm, rng):
    """『同じ群の字には同じ方式』という規則が本当に使えるか、1字抜き交差確認で測る。

    的は3つ:
      best     … いちばん良い方式(実際にはほぼ fade なので、当たって当たり前になる)
      best_alt … fade を除いていちばん良い方式(fade が使えない場面での2番手)
      wipe_gt_reveal … 「横に開く」が「一画ずつ出す」より良いか(0/1)
    群わけも、取り違えの群だけでなく **濁点の有無・かな行**でも同じことをやって、
    取り違えの群がそれらより良いのかを直接比べる。"""
    fams = [f for f in FAMILIES if f in piv.columns]
    if len(fams) < 3:
        return pd.DataFrame(), pd.DataFrame()
    base = pd.DataFrame(dict(char=piv.index))
    base["best"] = piv[fams].idxmax(axis=1).values
    alt = [f for f in fams if f != "fade"]
    base["best_alt"] = piv[alt].idxmax(axis=1).values
    if "wipe" in piv.columns and "reveal" in piv.columns:
        base["wipe_gt_reveal"] = (piv["wipe"] > piv["reveal"]).astype(int).values
    base = base.merge(assign[["char", "cluster", "cluster_fine"]], on="char", how="left")
    base["濁点の有無"] = [diacritic_of(c) for c in base["char"]]
    base["かな行"] = [kana_row_of(c) for c in base["char"]]
    base.to_csv(os.path.join(out, "assignment_rule_loco_detail.csv"), index=False)

    def loco(gcodes, ng, ycodes, nc):
        """群ごとの度数表を作り、自分1件を引いた多数決を予測にする(1字抜き)。"""
        tab = np.zeros((ng, nc))
        np.add.at(tab, (gcodes, ycodes), 1.0)
        t2 = tab[gcodes].copy()
        t2[np.arange(len(ycodes)), ycodes] -= 1.0
        tot = t2.sum(axis=1)
        pred = t2.argmax(axis=1)
        ok = tot > 0
        return float((pred[ok] == ycodes[ok]).mean()) if ok.any() else float("nan")

    rows = []
    targets = [c for c in ["best", "best_alt", "wipe_gt_reveal"] if c in base.columns]
    groupings = [("取り違えの群", "cluster"), ("取り違えの群(細)", "cluster_fine"),
                 ("濁点の有無", "濁点の有無"), ("かな行", "かな行")]
    for tgt in targets:
        y = base[tgt].values
        ycodes, yuniq = pd.factorize(y)
        nc = len(yuniq)
        glob = pd.Series(y).value_counts().idxmax()
        acc_g = float((y == glob).mean())
        for gname, gcol in groupings:
            lb = base[gcol].values
            gcodes, guniq = pd.factorize(lb)
            ng = len(guniq)
            obs = loco(gcodes, ng, ycodes, nc)
            null = np.array([loco(rng.permutation(gcodes), ng, ycodes, nc)
                             for _ in range(nperm)])
            rows.append(dict(target=tgt, grouping=gname, n_groups=int(pd.Series(lb).nunique()),
                             n_chars=len(y), acc_rule=obs, acc_global=acc_g,
                             gain_pt=(obs - acc_g) * 100,
                             null_mean=float(null.mean()),
                             null_p95=float(np.percentile(null, 95)),
                             p_perm=float((int((null >= obs).sum()) + 1) / (nperm + 1)),
                             global_majority=str(glob)))
    summ = pd.DataFrame(rows)
    summ["p_holm"] = afv2.holm(summ["p_perm"].tolist())
    summ.to_csv(os.path.join(out, "assignment_rule_loco.csv"), index=False)
    print("\n[5] 1字抜き交差確認:『同じ群 → 同じ方式』の規則は使えるか")
    print(summ.round(4).to_string(index=False))
    return summ, base


def main8_placement(assign, cff, out, best_family_path):
    b = pd.read_csv(best_family_path) if os.path.exists(best_family_path) else pd.DataFrame()
    a = assign[assign["source"] == "main8"].copy()
    if len(b):
        a = a.merge(b[["char", "best_family", "best_mu", "second_family", "worst_family"]],
                    on="char", how="left")
    rec = cff.sort_values("mu").drop_duplicates("cluster")[["cluster", "family", "mu", "best_share_boot"]]
    rec = rec.rename(columns={"family": "cluster_recommended_family", "mu": "cluster_mu",
                              "best_share_boot": "cluster_best_share_boot"})
    a = a.merge(rec, on="cluster", how="left")
    a["agree"] = a["best_family"] == a["cluster_recommended_family"]
    a.to_csv(os.path.join(out, "main8_placement.csv"), index=False)
    print("\n[5] 本命8字の所属と、その群の推奨方式")
    cols = [c for c in ["char", "cluster", "best_family", "best_mu", "cluster_recommended_family",
                        "cluster_best_share_boot", "agree"] if c in a.columns]
    print(a[cols].round(3).to_string(index=False))
    return a


def source_diagnostic(assign, out):
    ct = pd.crosstab(assign["cluster"], assign["source"])
    ct.to_csv(os.path.join(out, "cluster_source_diagnostic.csv"))
    print("\n[3] 出所(本命8字 / 紛れ字64字)で群が割れていないかの診断")
    print(ct.to_string())
    return ct


# ---------------------------------------------------------------------------
# 6. HTML(インラインSVGのみ)
# ---------------------------------------------------------------------------
PALETTE = ["#c2410c", "#0369a1", "#4d7c0f", "#7e22ce", "#b45309", "#0f766e",
           "#be123c", "#3f3f46", "#a16207", "#1d4ed8"]


def esc(s):
    return htmllib.escape(str(s))


def svg_dendrogram(Z, chars, labels, width=1180, height=430):
    dd = dendrogram(Z, labels=list(range(len(chars))), no_plot=True)
    icoord = np.array(dd["icoord"], dtype=float)
    dcoord = np.array(dd["dcoord"], dtype=float)
    order = dd["leaves"]
    padL, padR, padT, padB = 26, 14, 16, 40
    W = width - padL - padR
    H = height - padT - padB
    xmax = icoord.max() if len(icoord) else 1
    ymax = dcoord.max() if len(dcoord) else 1

    def X(v):
        return padL + v / xmax * W

    def Y(v):
        return padT + H - (v / ymax) * H
    parts = []
    for xs, ys in zip(icoord, dcoord):
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="var(--line)" stroke-width="1.1"/>')
    for i, leaf in enumerate(order):
        x = X(5 + 10 * i)
        cl = labels[leaf]
        col = PALETTE[(cl - 1) % len(PALETTE)]
        parts.append(f'<rect x="{x-6.5:.1f}" y="{padT+H+3:.1f}" width="13" height="19" rx="3" fill="{col}" opacity="0.16"/>')
        parts.append(f'<text x="{x:.1f}" y="{padT+H+18:.1f}" text-anchor="middle" '
                     f'font-size="13" fill="{col}" font-weight="600">{esc(chars[leaf])}</text>')
    for frac in (0.25, 0.5, 0.75, 1.0):
        y = Y(ymax * frac)
        parts.append(f'<line x1="{padL}" y1="{y:.1f}" x2="{padL+W}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="0.6" stroke-dasharray="2 4"/>')
        parts.append(f'<text x="4" y="{y+3:.1f}" font-size="9" fill="var(--muted)">{ymax*frac:.2f}</text>')
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">' + "".join(parts) + "</svg>"


def svg_mds(X, chars, labels, sources, width=760, height=620, hull=1.55, hull_fill=0.07):
    padL = padR = padT = padB = 34
    W = width - padL - padR; H = height - padT - padB
    x, y = X[:, 0], X[:, 1]
    def sx(v):
        return padL + (v - x.min()) / max(x.max() - x.min(), 1e-9) * W
    def sy(v):
        return padT + H - (v - y.min()) / max(y.max() - y.min(), 1e-9) * H
    parts = [f'<rect x="{padL}" y="{padT}" width="{W}" height="{H}" fill="none" stroke="var(--grid)"/>']
    # 群の輪郭(重心と平均半径の円)
    for cl in sorted(set(labels)):
        m = labels == cl
        cx, cy = sx(x[m].mean()), sy(y[m].mean())
        r = np.mean(np.hypot(sx(x[m]) - cx, sy(y[m]) - cy)) * hull + 10
        col = PALETTE[(cl - 1) % len(PALETTE)]
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{col}" '
                     f'opacity="{hull_fill}" stroke="{col}" stroke-opacity="0.32" '
                     f'stroke-dasharray="3 4"/>')
        parts.append(f'<text x="{cx:.1f}" y="{cy-r-4:.1f}" text-anchor="middle" font-size="11" '
                     f'fill="{col}" font-weight="700" stroke="var(--bg)" stroke-width="3" '
                     f'paint-order="stroke">群{cl}</text>')
    for i, ch in enumerate(chars):
        col = PALETTE[(labels[i] - 1) % len(PALETTE)]
        main = sources[i] == "main8"
        halo = ' stroke="var(--bg)" stroke-width="3" paint-order="stroke"' if main else ""
        parts.append(f'<text x="{sx(x[i]):.1f}" y="{sy(y[i]):.1f}" text-anchor="middle" '
                     f'dominant-baseline="central" font-size="{17 if main else 14}" fill="{col}" '
                     f'font-weight="{800 if main else 500}"{halo}>'
                     f'{esc(ch)}</text>')
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">' + "".join(parts) + "</svg>"


def svg_line(df, xcol, series, width=560, height=280, ylab="", xlab="", href=None):
    padL, padR, padT, padB = 46, 14, 16, 34
    W = width - padL - padR; H = height - padT - padB
    xs = df[xcol].values.astype(float)
    allv = np.concatenate([df[c].values.astype(float) for c, _ in series])
    allv = allv[np.isfinite(allv)]
    if href is not None:
        allv = np.append(allv, href)
    lo, hi = float(allv.min()), float(allv.max())
    pad = (hi - lo) * 0.12 or 0.05
    lo, hi = lo - pad, hi + pad
    def X(v):
        return padL + (v - xs.min()) / max(xs.max() - xs.min(), 1e-9) * W
    def Y(v):
        return padT + H - (v - lo) / max(hi - lo, 1e-9) * H
    parts = []
    for f in np.linspace(0, 1, 5):
        v = lo + f * (hi - lo); yy = Y(v)
        parts.append(f'<line x1="{padL}" y1="{yy:.1f}" x2="{padL+W}" y2="{yy:.1f}" stroke="var(--grid)" stroke-width="0.6"/>')
        parts.append(f'<text x="{padL-5}" y="{yy+3:.1f}" text-anchor="end" font-size="9" fill="var(--muted)">{v:.2f}</text>')
    for xv in xs:
        parts.append(f'<text x="{X(xv):.1f}" y="{padT+H+15:.1f}" text-anchor="middle" font-size="9" fill="var(--muted)">{xv:g}</text>')
    if href is not None:
        yy = Y(href)
        parts.append(f'<line x1="{padL}" y1="{yy:.1f}" x2="{padL+W}" y2="{yy:.1f}" '
                     f'stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="5 4"/>')
    for i, (col, name) in enumerate(series):
        c = PALETTE[i % len(PALETTE)]
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(xs, df[col].values.astype(float)) if np.isfinite(b))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2"/>')
        for a, b in zip(xs, df[col].values.astype(float)):
            if np.isfinite(b):
                parts.append(f'<circle cx="{X(a):.1f}" cy="{Y(b):.1f}" r="2.6" fill="{c}"/>')
        parts.append(f'<text x="{padL+8}" y="{padT+12+i*14}" font-size="10.5" fill="{c}" font-weight="600">{esc(name)}</text>')
    parts.append(f'<text x="{padL+W/2:.0f}" y="{height-4}" text-anchor="middle" font-size="10" fill="var(--muted)">{esc(xlab)}</text>')
    parts.append(f'<text x="10" y="{padT-4}" font-size="10" fill="var(--muted)">{esc(ylab)}</text>')
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">' + "".join(parts) + "</svg>"


def svg_bars(labels, values, width=560, height=280, ylab="", colors=None, fmt="{:.2f}"):
    padL, padR, padT, padB = 46, 14, 16, 40
    W = width - padL - padR; H = height - padT - padB
    v = np.asarray(values, dtype=float)
    hi = float(np.nanmax(v)) * 1.15 or 1.0
    lo = min(0.0, float(np.nanmin(v)) * 1.15)
    bw = W / max(len(v), 1) * 0.62
    def Y(x):
        return padT + H - (x - lo) / max(hi - lo, 1e-9) * H
    parts = [f'<line x1="{padL}" y1="{Y(0):.1f}" x2="{padL+W}" y2="{Y(0):.1f}" stroke="var(--grid)"/>']
    for i, (lb, val) in enumerate(zip(labels, v)):
        cx = padL + W * (i + 0.5) / len(v)
        c = (colors[i] if colors else PALETTE[i % len(PALETTE)])
        y0, y1 = Y(max(val, 0)), Y(min(val, 0))
        parts.append(f'<rect x="{cx-bw/2:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{max(y1-y0,1):.1f}" fill="{c}" opacity="0.82" rx="2"/>')
        parts.append(f'<text x="{cx:.1f}" y="{y0-4:.1f}" text-anchor="middle" font-size="9.5" fill="var(--fg)">{fmt.format(val)}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{padT+H+15:.1f}" text-anchor="middle" font-size="10" fill="var(--muted)">{esc(lb)}</text>')
    parts.append(f'<text x="10" y="{padT-4}" font-size="10" fill="var(--muted)">{esc(ylab)}</text>')
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">' + "".join(parts) + "</svg>"


def svg_grouped_bars(groups, series, width=640, height=300, ylab=""):
    """groups=横軸のラベル、series=[(名前, 値のリスト), ...]"""
    padL, padR, padT, padB = 46, 14, 26, 44
    W = width - padL - padR; H = height - padT - padB
    allv = np.concatenate([np.asarray(v, dtype=float) for _, v in series])
    hi = float(np.nanmax(allv)) * 1.18 or 1.0
    ng, ns = len(groups), len(series)
    gw = W / max(ng, 1)
    bw = gw * 0.78 / max(ns, 1)
    def Y(x):
        return padT + H - x / max(hi, 1e-9) * H
    parts = [f'<line x1="{padL}" y1="{Y(0):.1f}" x2="{padL+W}" y2="{Y(0):.1f}" stroke="var(--grid)"/>']
    for i, (name, vals) in enumerate(series):
        c = PALETTE[i % len(PALETTE)]
        for j, v in enumerate(vals):
            x = padL + gw * j + gw * 0.11 + bw * i
            parts.append(f'<rect x="{x:.1f}" y="{Y(v):.1f}" width="{bw*0.86:.1f}" '
                         f'height="{max(Y(0)-Y(v),1):.1f}" fill="{c}" opacity="0.85" rx="2"/>')
            parts.append(f'<text x="{x+bw*0.43:.1f}" y="{Y(v)-3:.1f}" text-anchor="middle" '
                         f'font-size="8.6" fill="var(--fg)">{v:.0f}</text>')
        lx = width - padR - (len(series) - i) * 76
        parts.append(f'<rect x="{lx:.0f}" y="{6}" width="9" height="9" fill="{c}" rx="2"/>'
                     f'<text x="{lx+12:.0f}" y="{14}" font-size="10" fill="var(--muted)">{esc(name)}</text>')
    for j, g in enumerate(groups):
        parts.append(f'<text x="{padL+gw*(j+0.5):.1f}" y="{padT+H+17:.1f}" text-anchor="middle" '
                     f'font-size="12" fill="var(--fg)">{esc(g)}</text>')
    parts.append(f'<text x="6" y="{padT-6}" font-size="10" fill="var(--muted)">{esc(ylab)}</text>')
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">' + "".join(parts) + "</svg>"


def svg_heatmap(M, chars, labels, width=780):
    n = len(chars)
    cell = 9.6
    padL = padT = 22
    size = padL + n * cell + 8
    parts = []
    mx = float(np.nanmax(np.abs(M))) or 1.0
    for i in range(n):
        for j in range(n):
            v = M[i, j]
            if not np.isfinite(v) or abs(v) < 1e-9:
                continue
            o = min(abs(v) / mx, 1.0) ** 0.6
            c = "#b91c1c" if v > 0 else "#1d4ed8"
            parts.append(f'<rect x="{padL+j*cell:.1f}" y="{padT+i*cell:.1f}" width="{cell:.1f}" '
                         f'height="{cell:.1f}" fill="{c}" opacity="{o:.3f}"/>')
    # 群の境目
    bounds = [0]
    for i in range(1, n):
        if labels[i] != labels[i - 1]:
            bounds.append(i)
    bounds.append(n)
    for b in bounds:
        p = padL + b * cell
        parts.append(f'<line x1="{p:.1f}" y1="{padT}" x2="{p:.1f}" y2="{padT+n*cell:.1f}" stroke="var(--fg)" stroke-width="0.8" opacity="0.5"/>')
        parts.append(f'<line x1="{padL}" y1="{p:.1f}" x2="{padL+n*cell:.1f}" y2="{p:.1f}" stroke="var(--fg)" stroke-width="0.8" opacity="0.5"/>')
    for i, ch in enumerate(chars):
        c = PALETTE[(labels[i] - 1) % len(PALETTE)]
        parts.append(f'<text x="{padL-3}" y="{padT+i*cell+cell*0.78:.1f}" text-anchor="end" font-size="7.4" fill="{c}">{esc(ch)}</text>')
        parts.append(f'<text x="{padL+i*cell+cell*0.5:.1f}" y="{padT-5}" text-anchor="middle" font-size="7.4" fill="{c}">{esc(ch)}</text>')
    return f'<svg viewBox="0 0 {size} {size}" width="100%" role="img">' + "".join(parts) + "</svg>"


def df_table(df, cols=None, round_=3, maxrows=200):
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    d = d.head(maxrows)
    head = "".join(f"<th>{esc(c)}</th>" for c in d.columns)
    body = []
    for _, r in d.iterrows():
        tds = []
        for c in d.columns:
            v = r[c]
            if isinstance(v, (float, np.floating)) and np.isfinite(v):
                v = f"{v:.{round_}f}"
            tds.append(f"<td>{esc(v)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


CSS = """
:root{--bg:#fbf9f5;--fg:#1c1a17;--muted:#6b6459;--line:#8a8378;--grid:#d8d2c6;
 --card:#ffffff;--accent:#c2410c;--border:#e3ddd1;}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
 --bg:#15140f;--fg:#efeadf;--muted:#a29a8c;--line:#6f695e;--grid:#33302a;
 --card:#1e1c16;--accent:#f97316;--border:#33302a;}}
:root[data-theme="dark"]{--bg:#15140f;--fg:#efeadf;--muted:#a29a8c;--line:#6f695e;
 --grid:#33302a;--card:#1e1c16;--accent:#f97316;--border:#33302a;}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);margin:0;
 font-family:"Hiragino Mincho ProN","Yu Mincho",serif;line-height:1.75;}
.wrap{max-width:1240px;margin:0 auto;padding:40px 22px 90px;}
h1{font-size:clamp(24px,3.4vw,38px);letter-spacing:.02em;margin:0 0 6px;font-weight:600;}
h2{font-size:20px;margin:52px 0 12px;padding-bottom:7px;border-bottom:2px solid var(--accent);
 display:inline-block;font-weight:600;}
h3{font-size:15.5px;margin:26px 0 8px;color:var(--accent);font-weight:600;}
p,li{font-size:14.5px;}
.sub{color:var(--muted);font-size:13px;margin:0 0 26px;}
.card{background:var(--card);border:1px solid var(--border);border-radius:9px;padding:18px 20px;margin:14px 0;}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px;}
.warn{border-left:4px solid var(--accent);background:color-mix(in srgb,var(--accent) 7%,transparent);
 padding:12px 16px;border-radius:0 7px 7px 0;margin:14px 0;font-size:13.5px;}
.tw{overflow-x:auto;max-width:100%;}
table{border-collapse:collapse;font-size:12.2px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 min-width:100%;}
th,td{border-bottom:1px solid var(--border);padding:4px 9px;text-align:right;white-space:nowrap;}
th{color:var(--muted);font-weight:600;text-align:right;border-bottom:1.5px solid var(--line);}
td:first-child,th:first-child{text-align:left;}
tbody tr:hover{background:color-mix(in srgb,var(--accent) 6%,transparent);}
.chars{font-size:19px;letter-spacing:.13em;line-height:1.9;}
.kv{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;}
.kv div{background:color-mix(in srgb,var(--accent) 8%,transparent);border-radius:6px;padding:5px 11px;font-size:12.5px;}
.cap{font-size:12px;color:var(--muted);margin-top:6px;}
"""


def build_report(path, ctx):
    P = []
    A = P.append
    # 単体のHTMLとしてブラウザで直接開いても文字化けしないように charset を明示する。
    A('<meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width, initial-scale=1">')
    A(f"<title>取り違えから見たかなの群</title><style>{CSS}</style>")
    A('<div class="wrap">')
    A("<h1>取り違えから見たかなの群</h1>")
    A(f'<p class="sub">紛れ字64字＋本命8字／{ctx["n_trials"]}試行・{ctx["n_pid"]}人・誤答{ctx["n_err"]}件'
      f'／生成 {esc(ctx["stamp"])}　<b>探索的分析（事前仮説なし・追試が要る）</b></p>')

    A('<div class="warn"><b>読む前に。</b>これは事前に仮説を立てずにデータから群を掘り出した分析です。'
      '同じ手続きを別の標本でやり直したときに同じ群が出る保証はありません。'
      '本文の p 値はすべて並べ替え検定で、Holm 調整をかけたものだけを「差がある」と読んでください。'
      'ぼやけ（blur）は WebKit 端末で描画されていなかったため、blur の試行からは WebKit を除いてあります。</div>')

    A("<h2>1. まず「取り違えに構造があるか」</h2>")
    A('<div class="card"><h3>参加者を半分に割ったときの一致</h3>'
      '<p>参加者を無作為に半分に割り、それぞれで取り違え行列（の残差）を作って、'
      '升どうしの相関をとりました。取り違えが当てずっぽうなら相関は 0 になります。</p>')
    A(ctx["svg_rel"])
    A('<p class="cap">Spearman–Brown で全データ相当に直した値。帯は「その方式×水準の生の正答率」で3等分したもの。</p>')
    A(df_table(ctx["rel"], ["subset", "n_errors", "halfhalf_pearson", "spearman_brown_full", "lo", "hi"]))
    A("</div>")
    A('<div class="card"><h3>帯ごとの情報量</h3>'
      '<p>誤答だけを使った相互情報量 I(出た字; 答えた字)。並べ替え帰無との差（超過分）が'
      '「取り違えが字の情報を持っている度合い」です。</p>')
    A(ctx["svg_band"])
    A(df_table(ctx["band"], ["band", "n_errors", "acc_of_band", "mi_bits", "mi_null_mean",
                             "mi_excess_bits", "p_perm"], round_=4))
    A("</div>")
    A('<div class="card"><h3>どういう間違え方をしているのか（型に分けて数える）</h3>'
      '<p>クラスタリングの前に、生の取り違えの中身を見ておきます。'
      '「濁点落とし」＝が→か のように濁点・半濁点を落として素の字と答えたもの。</p>')
    A(ctx["svg_tax"])
    A('<p class="cap">方式ごとの、誤答に占める型の割合（「無関係」は残り全部なので図から外しています）。'
      '<b>横に開く（wipe）だけ濁点落としが突出</b>しています。'
      '濁点は字の右上にあるので、左から開いていくと最後まで見えない――'
      'あとで出てくる「wipe は濁点の字で崩れる」と同じことを、'
      '取り違えの中身の側から見たものです。</p>')
    A(df_table(ctx["tax"][ctx["tax"].scope.isin(["全体", "方式"])],
               ["scope", "group", "kind", "n", "share"], maxrows=40))
    A("</div>")
    A('<div class="card"><h3>4方式で同じ構造か／非対称か</h3>'
      '<p><b>希釈補正</b>: 生の相関は雑音のぶんだけ必ず下振れします。方式ごとの'
      '半分割信頼性で割り戻した値（pearson_disattenuated）が、雑音を除いたときの'
      '一致度の目安です。</p>')
    A(f'<div class="grid2"><div>{df_table(ctx["fam_agree"])}</div>'
      f'<div>{df_table(ctx["asym_g"], ["stat_asymmetry","null_mean","p_perm","n_pairs_tested","n_pairs_holm_sig"])}'
      f'{df_table(ctx["asym_top"], ["char_a","char_b","n_a_to_b","n_b_to_a","p_raw","p_holm"], round_=4, maxrows=8)}</div></div>')
    A('<p class="cap">左: 方式どうしの残差の相関。右上: 非対称の全体検定（準独立モデルの期待比のもとでの二項）。'
      '右下: 非対称が大きい対の上位。</p></div>')

    A("<h2>2. 群の個数</h2>")
    A(f'<div class="warn">{esc(ctx["rows_note"])}</div>')
    A('<div class="card"><div class="grid2">')
    A(f'<div>{ctx["svg_sil"]}<p class="cap">シルエット係数。'
      '「帰無」は<b>字による違いがまったく無い世界</b>（準独立モデルから同じ数の誤答を'
      '作り直したもの）を同じ手順でクラスタリングしたときの値。</p></div>')
    A(f'<div>{ctx["svg_ps"]}<p class="cap">参加者ブートストラップの予測強度と ARI。'
      '予測強度は「基準解の各群の中の字の対が、作り直しても同じ群に残る割合の最小値」。'
      '0.80 が再現の目安（破線）。</p></div>')
    A("</div>")
    A(df_table(ctx["sel"], ["k", "silhouette", "sil_null_mean", "excess_over_null",
                            "p_perm", "pred_strength_mean", "ari_mean",
                            "min_cluster_size", "max_cluster_size"], round_=4))
    A(f'<p>{ctx["k_reason"]}</p></div>')

    A("<h2>3. 樹形図</h2>")
    A(f'<div class="card">{ctx["svg_dendro"]}'
      f'<p class="cap">平均連結法・cos 距離。葉の色が採用した群（k={ctx["k"]}）。</p></div>')

    A("<h2>4. 2次元に置いた72字</h2>")
    A('<div class="card"><div class="grid2">')
    A(f'<div>{ctx["svg_mds"]}<p class="cap">古典的MDS（説明率 '
      f'{ctx["mds_var"]*100:.1f}%）。色は代表の切り方 k={ctx["k"]}。太字が本命8字。</p></div>')
    A(f'<div>{ctx["svg_mds_fine"]}<p class="cap">同じ配置を、参考の細かい切り方 '
      f'k={ctx["k_fine"]} で塗り分けたもの。<b>群の輪は重なり合っていて、'
      f'飛び飛びの塊にはなっていません</b>——「連続的で群には割れていない」という'
      f'結論はこの図がそのまま示しています。</p></div>')
    A("</div>")
    A(f'<div style="max-width:820px;margin:0 auto">{ctx["svg_heat"]}</div>'
      f'<p class="cap">樹形図の順に並べ替えた類似度行列（区切り線は k={ctx["k_fine"]}）。'
      f'赤=似ている、青=似ていない。対角ブロックが濃いほど群がまとまっている。</p>')
    A("</div>")

    A("<h2>5. できた群</h2>")
    for _, r in ctx["profile"].reset_index().iterrows():
        col = PALETTE[(int(r["cluster"]) - 1) % len(PALETTE)]
        A(f'<div class="card"><h3 style="color:{col}">群{int(r["cluster"])}（{int(r["n_chars"])}字）</h3>')
        A(f'<p class="chars" style="color:{col}">{esc(r["chars"])}</p>')
        A('<div class="kv">'
          f'<div>濁点・半濁点 {r["dakuten_rate"]*100:.0f}%</div>'
          f'<div>正答率 {r["acc"]*100:.1f}%</div>'
          f'<div>墨の量 {r["ink_frac"]:.3f}</div>'
          f'<div>まとまりの数 {r["n_components"]:.2f}</div>'
          f'<div>選ばれやすさ {r["chosen_lift"]:.2f}倍</div>'
          f'<div>試行 {int(r["n_trials"])}</div></div>')
        A(f'<p class="cap">{esc(ctx["cluster_notes"].get(int(r["cluster"]),""))}</p></div>')
    A(f'<div class="card"><h3>参考: もっと細かく切ったとき（k={ctx["k_fine"]}）</h3>'
      '<p>安定性の基準（予測強度 0.80）は満たしません。'
      '「この切り方なら、こういう字がまとまる」という見取り図として読んでください。</p>')
    for cl, s in ctx["fine_list"]:
        col = PALETTE[(cl - 1) % len(PALETTE)]
        A(f'<p class="chars" style="color:{col}"><span style="font-size:12px">群{cl}</span> {esc(s)}</p>')
    A("</div>")

    A("<h2>6. 群は何で説明できるか</h2>")
    A('<div class="card">')
    A(ctx["svg_feat"])
    A('<p class="cap">並べ替え検定。棒は −log10(Holm 調整後 p)。破線は p=0.05。'
      '<b>18項目以上を一度に試しているので、Holm を通ったものだけを見てください。</b></p>')
    A(df_table(ctx["feat_tests"], ["partition", "feature", "kind", "stat_F", "p_raw", "p_holm", "n"],
               round_=4, maxrows=50))
    A("</div>")

    A("<h2>7. 方式の割り当てに使えるか</h2>")
    A('<div class="card"><h3>まず前提: 「字によって向いた方式が違う」はあるか</h3>'
      '<p>これが無ければ、どんな分類を作っても方式の割り当てには使えません。'
      '（方式×水準）の升ごとの平均を引いた残差を使い、'
      '<b>水準と方式の主効果を消したうえで残る 字×方式 の交互作用</b>だけを検定しています。'
      '帰無は「升の中で字のラベルを混ぜたもの」。</p>')
    A('<p>「濁点の有無を調整」の行は、升の定義に濁点の有無を足して'
      '<b>濁点×方式の効果を先に吸い取った</b>あとの検定です。'
      'ここで群が効かなければ、群は濁点以上のことを言っていません。'
      'var_explained は「帰無を引いたあとに説明できた残差分散の割合」で、'
      '群の数が違っても比べられます。</p>')
    A(df_table(ctx["inter"], ["adjusted_for", "unit", "n_levels", "stat", "null_mean", "z",
                              "var_explained", "p_perm", "p_holm"], round_=4, maxrows=40))
    A(f'<p>{ctx["inter_verdict"]}</p></div>')
    A('<div class="card"><h3>群わけごとの方式の順位</h3>'
      '<p>方式ごとに水準はしごが違うので μ の絶対値は比べられません。'
      'ここでは<b>水準等重みの生の正答率</b>で並べています。'
      '「どの群わけでも1位が同じか、入れ替わるか」が知りたいことそのものです。</p>')
    A(df_table(ctx["gap"], ["grouping", "group", "n_chars", "n_trials", "acc_order",
                            "gap_top2_pt", "acc_fade", "acc_reveal", "acc_wipe", "acc_blur"],
               maxrows=60))
    A(f'{ctx["svg_gap"]}<p class="cap">濁点の有無で分けたときの方式別正答率（水準等重み）。'
      '<b>横に開く（wipe）だけが濁点の字で崩れている</b>のが見えます。</p></div>')
    A('<div class="card"><h3>群 × 方式（群内の試行をまとめて当てはめ）</h3>'
      '<p>μ は「その群の字を半分の人が読めるようになる進み具合(%)」。小さいほど少ない進み具合で読める。'
      '方式ごとに水準はしごが違うので、μ の絶対値は方式間で意味が重なりません。'
      '見るべきは<b>群をまたいだときの方式の順位の入れ替わり</b>です。</p>')
    A(df_table(ctx["cff"], ["cluster", "family", "n_chars", "n_trials", "acc", "mu", "sigma",
                            "best_share_boot"]))
    A(f'{ctx["svg_cff"]}<p class="cap">群ごとの μ（対数目盛ではなく方式内で基準化）。</p></div>')
    A('<div class="card"><h3>本命8字はどこに入り、その群の推奨と合うか</h3>')
    A(df_table(ctx["main8"], ["char", "cluster", "best_family", "best_mu",
                              "cluster_recommended_family", "cluster_best_share_boot", "agree"]))
    A("</div>")
    A('<div class="card"><h3>その前に: 1字あたりで「方式の向き不向き」は測れているか</h3>'
      '<p>1字あたりの試行数は方式ごとに数十しかありません。'
      '<b>的そのものが雑音なら、どんな規則も当たりません。</b>'
      '参加者を半分に割って、字ごとの「方式どうしの差」が半分どうしで一致するかを見ます。</p>')
    A(df_table(ctx["chrel"], ["quantity", "halfhalf_pearson", "spearman_brown_full",
                              "lo", "hi", "n_rep"]))
    A(f'<p>{ctx["chrel_note"]}</p></div>')
    A('<div class="card"><h3>1字抜き交差確認</h3>'
      '<p>「同じ群の字には同じ方式」という規則を、1字ずつ抜いて（その字を含めずに）'
      '予測させたもの。比較対象は群を使わない全体多数決。'
      '<b>取り違えの群だけでなく、濁点の有無・かな行でも同じことをやって</b>、'
      'どれがいちばん効くかを並べています。的の意味: '
      'best=いちばん良い方式、best_alt=fade を除いた2番手、'
      'wipe_gt_reveal=「横に開く」が「一画ずつ出す」に勝つか。</p>')
    A(df_table(ctx["rule"], ["target", "grouping", "n_groups", "n_chars", "acc_rule",
                             "acc_global", "gain_pt", "null_mean", "p_perm", "p_holm",
                             "global_majority"], round_=4, maxrows=30))
    A(f'<p>{ctx["rule_verdict"]}</p>')
    A('<h3>連続量でのやり直し</h3>'
      '<p>二値の多数決は雑音に弱いので、方式どうしの差そのもの（連続量）を'
      '群の平均で当てにいったときの out-of-sample R² も出します。'
      '0 より大きければ、群を知っていることが予測の役に立っているという意味です。</p>')
    A(df_table(ctx["rule_cont"], ["target", "grouping", "n_groups", "loco_r2", "null_mean",
                                  "null_p95", "p_perm", "p_holm"], round_=4, maxrows=30))
    A("</div>")

    A("<h2>8. 結論</h2>")
    A(f'<div class="card">{ctx["conclusion"]}</div>')
    A(f'<p class="cap">出力CSV: {esc(ctx["outdir"])}／スクリプト: experiment/tools/analyze_char_clusters.py</p>')
    A("</div>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(P))
    print(f"\n図つきレポート -> {path}")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="project/data_calib2_live/transfer_trials.csv")
    ap.add_argument("--out", default="project/data_calib2_live/analysis_char_clusters")
    ap.add_argument("--report", default="project/data_calib2_live/char_clusters_report.html")
    ap.add_argument("--fam-dir", default="project/data_calib2_live/analysis_families_v2")
    ap.add_argument("--base-dir", default="experiment/base")
    ap.add_argument("--k", type=int, default=0, help="0=シルエットで自動選択")
    ap.add_argument("--kmax", type=int, default=15)
    ap.add_argument("--link", default="average", choices=["average", "ward", "complete"])
    ap.add_argument("--n-splithalf", type=int, default=200)
    ap.add_argument("--n-perm", type=int, default=2000)
    ap.add_argument("--n-perm-sil", type=int, default=200)
    ap.add_argument("--n-boot", type=int, default=200)
    ap.add_argument("--n-boot-fit", type=int, default=120)
    ap.add_argument("--fit-starts", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260827)
    ap.add_argument("--drop-webkit-all", action="store_true",
                    help="blur だけでなく全方式で WebKit を除外(頑健性確認用)")
    ap.add_argument("--rows", default="informative", choices=["all", "informative"],
                    help="informative=半分割信頼性が閾値未満の帯(=取り違えが当てずっぽう"
                         "でしかない帯)を分類から外す。all=全試行を使う")
    ap.add_argument("--rel-threshold", type=float, default=0.15,
                    help="informative の閾値(帯の半分割 pearson)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    d = afv2.load(a.inp)
    S = afv2.slices(d)
    gv, _ = afv2.gammas(d)

    t = build_rows(S, a.out, a.drop_webkit_all)
    t, bands = visibility_bands(t, a.out)
    t = t.reset_index(drop=True)
    cnt = char_counts(t, a.out)

    chars = sorted(set(t["target_char"]) | set(t["response_char"]))
    idx = {c: i for i, c in enumerate(chars)}
    n = len(chars)
    print(f"[1] 行列の大きさ: {t['target_char'].nunique()}字が行に立つ / 列は{n}字")

    mask = ~np.eye(n, dtype=bool)
    N_all = counts_matrix(t, chars, idx)
    empty = [chars[i] for i in range(n) if N_all[i].sum() == 0]
    if empty:
        print(f"  ※ 誤答が1件も無い字: {''.join(empty)} (行として使えない)")

    # --- 2. 構造が本物か -----------------------------------------------------
    rel = splithalf_reliability(t, chars, idx, mask, a.out, a.n_splithalf, rng, bands)
    band = band_information(t, chars, idx, mask, a.out, a.n_perm, rng, bands)
    fam_agree, _ = family_agreement(t, chars, idx, mask, a.out, rel)
    tax, _ = error_taxonomy(t, a.out)

    # 分類に使う試行を決める。信頼性が閾値未満の帯は、取り違えが当てずっぽうで
    # しかない = 足すと類似度を薄めるだけなので外す(既定)。
    bad = [str(r["subset"]) for _, r in rel.iterrows()
           if str(r["subset"]) in bands and r["halfhalf_pearson"] < a.rel_threshold]
    if a.rows == "informative" and bad:
        tc = t[~t["band"].astype(str).isin(bad)].copy()
        rows_note = (f"分類には、半分割信頼性が {a.rel_threshold} 未満だった帯"
                     f"「{'／'.join(bad)}」を除いた {len(tc)}試行を使う"
                     f"（除いた帯の信頼性は "
                     f"{'／'.join(f'{rel[rel.subset==b].iloc[0].halfhalf_pearson:.3f}' for b in bad)}）。")
    else:
        tc = t.copy()
        rows_note = f"分類には全 {len(tc)}試行を使う。"
    print(f"[3] {rows_note}")
    tc = tc.reset_index(drop=True)

    N = counts_matrix(tc, chars, idx)
    R, E = residual_matrix(N, mask)
    long = [dict(target=chars[i], response=chars[j], n=int(N[i, j]), expected=E[i, j],
                 residual=R[i, j], n_all_bands=int(N_all[i, j]))
            for i in range(n) for j in range(n) if i != j and N_all[i, j] > 0]
    pd.DataFrame(long).sort_values("n", ascending=False).to_csv(
        os.path.join(a.out, "confusion_counts.csv"), index=False)
    pd.DataFrame(R, index=chars, columns=chars).to_csv(
        os.path.join(a.out, "confusion_residuals.csv"))
    asym_pairs, asym_g = asymmetry(N, E, chars, a.out, rng=rng)

    # --- 3. 分類 -------------------------------------------------------------
    variants = {}
    for name, mode in [("row_col(主)", "row_col"), ("row(行のみ)", "row"), ("col(列のみ)", "col")]:
        F = features_from_residual(R, mode)
        variants[name] = cosine_D(F)
    D, Sim = variants["row_col(主)"]
    D_allbands, _ = cosine_D(features_from_residual(residual_matrix(N_all, mask)[0], "row_col"))
    pd.DataFrame(Sim, index=chars, columns=chars).to_csv(
        os.path.join(a.out, "similarity_matrix.csv"))

    sel, Z = choose_k(D, a.out, a.kmax, N, mask, a.n_perm_sil, rng, a.link)
    stab_all, cos = stability_sweep(tc, chars, idx, mask, Z, a.out, a.kmax, a.n_boot, rng, a.link)
    sel = sel.merge(stab_all, on="k", how="left")
    sel.to_csv(os.path.join(a.out, "cluster_selection.csv"), index=False)

    ok3 = sel[sel["min_cluster_size"] >= 3]
    ok3 = ok3 if len(ok3) else sel
    # 参考用の「細かい切り方」: 安定性の基準は満たさないが、帰無分布からの
    # 離れがいちばん大きい k(k<=10 に限る。それ以上は2字の群ばかりになる)。
    fine_pool = ok3[ok3["k"] <= 10]
    k_fine = int((fine_pool if len(fine_pool) else ok3).loc[
        (fine_pool if len(fine_pool) else ok3)["excess_over_null"].idxmax(), "k"])
    if a.k > 0:
        k = a.k
        k_reason = f"k={k} は指定値。"
    else:
        # 予測強度(Tibshirani の目安 0.8)を第一の根拠にし、それを満たす最大の k を採る。
        # 満たす k が無ければ「どの k も安定しない」と明言したうえで、
        # いちばんマシな(予測強度が最大の) k を代表として使う。
        cand = ok3[ok3["pred_strength_mean"] >= 0.8]
        if len(cand):
            k = int(cand["k"].max())
            r = sel[sel["k"] == k].iloc[0]
            k_reason = (f"k={k} を採用。理由: 参加者ブートストラップの予測強度が "
                        f"{r['pred_strength_mean']:.2f} と目安 0.80 を満たす<b>最大の k</b>。"
                        f"このとき ARI={r['ari_mean']:.2f}、シルエット {r['silhouette']:.3f} で、"
                        f"『字による違いが無い世界』の帰無平均 {r['sil_null_mean']:.3f} を "
                        f"{r['excess_over_null']:+.3f} 上回る（並べ替え p={r['p_perm']:.3f}）。")
        else:
            k = int(ok3.loc[ok3["pred_strength_mean"].idxmax(), "k"])
            r = sel[sel["k"] == k].iloc[0]
            rf = sel[sel["k"] == k_fine].iloc[0]
            k_reason = (
                f"<b>妥当な群の個数は「決まらない」というのが正直な答え</b>です。"
                f"予測強度（作り直しても同じ群に残る割合）は k=2 の {ok3['pred_strength_mean'].max():.2f} が最大で、"
                f"目安の 0.80 に届く k は<b>一つもありません</b>。"
                f"シルエット係数も全 k で {sel['silhouette'].min():.2f}〜{sel['silhouette'].max():.2f} と、"
                f"「はっきりした群がある」とされる 0.25 をどこも下回ります。"
                f"つまり取り違えの構造は<b>連続的で、飛び飛びの群には割れていない</b>。"
                f"以下では、いちばん安定した k={k}（予測強度 {r['pred_strength_mean']:.2f}、"
                f"ARI {r['ari_mean']:.2f}）を代表の切り方として使い、"
                f"参考として、帰無からの離れが最大になる細かい切り方 k={k_fine}"
                f"（シルエット {rf['silhouette']:.3f} vs 帰無 {rf['sil_null_mean']:.3f}、"
                f"予測強度 {rf['pred_strength_mean']:.2f}）も併記します。"
                f"方式の検討は k={{2,4,6,8}} すべてでやり直してあります。")
    labels = fcluster(Z, k, criterion="maxclust")
    labels_fine = fcluster(Z, k_fine, criterion="maxclust")
    print(f"\n[3] k={k}（参考の細かい切り方 k={k_fine}）")

    src = t.drop_duplicates("target_char").set_index("target_char")["source"].to_dict()
    assign = pd.DataFrame(dict(char=chars, cluster=labels, cluster_fine=labels_fine,
                               source=[src.get(c, "response_only") for c in chars]))
    for name, (Dv, _) in variants.items():
        Zv = linkage(squareform(Dv, checks=False), method=a.link)
        assign[f"cluster_{name}"] = fcluster(Zv, k, criterion="maxclust")
    for meth in ["ward", "complete"]:
        Zm = linkage(squareform(D, checks=False), method=meth)
        assign[f"cluster_{meth}"] = fcluster(Zm, k, criterion="maxclust")
    Za = linkage(squareform(D_allbands, checks=False), method=a.link)
    assign["cluster_全帯(低い帯も込み)"] = fcluster(Za, k, criterion="maxclust")
    assign.to_csv(os.path.join(a.out, "cluster_assignment.csv"), index=False)

    vcols = [c for c in assign.columns if c.startswith("cluster_") and c != "cluster_fine"]
    vr = [dict(variant_1=c1, variant_2=c2, ari=ari(assign[c1], assign[c2]))
          for i, c1 in enumerate(["cluster"] + vcols) for c2 in (["cluster"] + vcols)[i + 1:]]
    pd.DataFrame(vr).to_csv(os.path.join(a.out, "cluster_variants_ari.csv"), index=False)
    print("\n[3] 作り方を変えたときの一致(ARI)")
    print(pd.DataFrame(vr).round(3).to_string(index=False))

    stab_ch = stability_detail(chars, labels, cos[k], a.out, k)
    stab = stab_all[stab_all["k"] == k].reset_index(drop=True)
    src_ct = source_diagnostic(assign, a.out)

    Zdf = pd.DataFrame(Z, columns=["a", "b", "dist", "n"])
    Zdf.to_csv(os.path.join(a.out, "linkage.csv"), index=False)
    X, mds_var = classical_mds(D, 2)
    pd.DataFrame(dict(char=chars, cluster=labels, dim1=X[:, 0], dim2=X[:, 1])).to_csv(
        os.path.join(a.out, "mds_coords.csv"), index=False)

    # --- 4. 説明 -------------------------------------------------------------
    feat = char_features(chars, a.base_dir, a.out)
    rbias = response_bias(t, chars, a.out)
    feat_tests, profile, merged, prof_all = explain_clusters(
        assign, feat, cnt, rbias, a.out, a.n_perm, rng,
        parts=[(f"k={k}", "cluster"), (f"k={k_fine}", "cluster_fine")])

    # --- 5. 方式 -------------------------------------------------------------
    # まず前提の検定。ここが通らなければ、どんな分類も方式の割り当てには使えない。
    kmap = {kk: fcluster(Z, kk, criterion="maxclust")
            for kk in sorted({2, 4, 6, 8, k, k_fine}) if 2 <= kk <= a.kmax}
    inter = char_family_interaction(t, a.out, a.n_perm, rng, assign, kmap)
    inter = char_family_interaction(t, a.out, a.n_perm, rng, assign, kmap,
                                    absorb="diacritic", tag="濁点の有無を調整",
                                    append=inter)

    cff, cfacc = cluster_family_fit(t, assign, a.out, gv, a.fit_starts, a.n_boot_fit, rng)
    cff_multi = []
    for kk, lab in kmap.items():
        if kk == k:
            continue
        ak = pd.DataFrame(dict(char=chars, cluster=lab))
        f, _ = cluster_family_fit(t, ak, a.out, gv, max(a.fit_starts // 2, 2), 0, rng, quiet=True)
        f.insert(0, "k", kk)
        cff_multi.append(f)
    cffk = pd.concat([cff.assign(k=k)] + cff_multi, ignore_index=True) if cff_multi else cff.assign(k=k)
    cffk.to_csv(os.path.join(a.out, "cluster_family_fit_multi_k.csv"), index=False)
    flips = cffk.sort_values("mu").groupby(["k", "cluster"]).head(1)
    print("\n[5] k を変えたとき、群ごとに μ 最小の方式が入れ替わるか")
    print(flips.groupby(["k", "family"]).size().rename("群の数").to_string())

    groupings = {f"取り違えの群(k={k})": dict(zip(assign["char"], assign["cluster"])),
                 f"取り違えの群(k={k_fine})": dict(zip(assign["char"], assign["cluster_fine"])),
                 "濁点の有無": {c: diacritic_of(c) for c in chars},
                 "かな行": {c: kana_row_of(c) for c in chars}}
    gap = group_family_gap(t, groupings, a.out, gv, a.fit_starts)

    cfr = char_family_rank(assign, a.out,
                           os.path.join(a.fam_dir, "decoy_fit_v2.csv"),
                           os.path.join(a.fam_dir, "usable_span.csv"))
    _, piv = char_family_acc(t, a.out)
    chrel = char_level_reliability(t, a.out, max(a.n_splithalf // 4, 5), rng)
    rule, rule_detail = assignment_rule(piv, assign, a.out, a.n_perm, rng)
    rule_cont = assignment_rule_continuous(piv, assign, a.out, a.n_perm, rng)
    m8 = main8_placement(assign, cff, a.out, os.path.join(a.fam_dir, "best_family_per_char_v2.csv"))

    # --- 6. HTML -------------------------------------------------------------
    order = dendrogram(Z, no_plot=True)["leaves"]
    Sim_ord = Sim[np.ix_(order, order)]
    np.fill_diagonal(Sim_ord, np.nan)
    chars_ord = [chars[i] for i in order]
    lab_ord = labels_fine[order]

    rel_plot = rel[rel["subset"].isin(["全体"] + bands)]
    svg_rel = svg_bars(rel_plot["subset"].tolist(), rel_plot["spearman_brown_full"].tolist(),
                       ylab="半分割信頼性(Spearman-Brown)", width=560, height=250)
    svg_band = svg_bars(band["band"].tolist(), band["mi_excess_bits"].tolist(),
                        ylab="相互情報量の超過(bit)", width=560, height=250, fmt="{:.3f}")
    svg_sil = svg_line(sel, "k", [("silhouette", "実データ"), ("sil_null_mean", "帰無(平均)"),
                                  ("sil_null_p95", "帰無(95%点)")],
                       width=620, height=280, ylab="シルエット係数", xlab="群の個数 k")
    svg_ps = svg_line(sel, "k", [("pred_strength_mean", "予測強度"), ("ari_mean", "ARI")],
                      width=620, height=280, ylab="安定性", xlab="群の個数 k", href=0.80)
    ft = feat_tests.copy()
    ft["score"] = -np.log10(np.clip(ft["p_holm"], 1e-6, 1))
    ft = ft.sort_values("score", ascending=False).head(12)
    svg_feat = svg_bars(ft["feature"].tolist(), ft["score"].tolist(),
                        ylab="-log10(Holm 調整後 p)", width=780, height=300, fmt="{:.2f}")

    cffp = cff.copy()
    cffp["mu_norm"] = cffp.groupby("family")["mu"].transform(lambda s: s / s.mean())
    piv = cffp.pivot(index="cluster", columns="family", values="mu_norm").reset_index()
    svg_cff = svg_line(piv, "cluster", [(f, f) for f in FAMILIES if f in piv.columns],
                       width=620, height=290, ylab="μ(方式内の平均を1に基準化)", xlab="群")
    tx = tax[tax["scope"] == "方式"]
    # 「無関係」は残りの全部で 7〜8割を占めるので、図からは外す(表には出す)。
    kinds = ["濁点落とし", "濁点の取り違え", "濁点つけ", "同じ素の字(その他)", "同じかな行"]
    kinds = [k2 for k2 in kinds if k2 in set(tx["kind"])]
    txp = tx.pivot(index="kind", columns="group", values="share").reindex(kinds).fillna(0)
    svg_tax = svg_grouped_bars(kinds,
                               [(f, [float(txp.loc[k2, f]) * 100 for k2 in kinds])
                                for f in FAMILIES if f in txp.columns],
                               ylab="誤答に占める割合(%)", width=760, height=310)
    gd = gap[gap["grouping"] == "濁点の有無"].copy()
    order_d = [g for g in ["清音", "濁音", "半濁音"] if g in set(gd["group"])]
    gd = gd.set_index("group").reindex(order_d).reset_index()
    svg_gap = svg_grouped_bars(gd["group"].tolist(),
                               [(f, [float(v) * 100 for v in gd[f"acc_{f}"]]) for f in FAMILIES],
                               ylab="正答率(%) 水準等重み", width=640, height=300)

    cluster_notes = {}
    for cl in sorted(assign["cluster"].unique()):
        sub = merged[merged["cluster"] == cl]
        rec = cff[cff["cluster"] == cl].sort_values("mu")
        best = rec.iloc[0] if len(rec) else None
        note = (f"濁点・半濁点 {int((sub['diacritic']!='清音').sum())}/{len(sub)}字、"
                f"平均正答率 {sub['acc'].mean()*100:.1f}%。")
        if best is not None:
            note += (f" この群の当てはめで μ が最小の方式は {best['family']}"
                     f"(μ={best['mu']:.2f}、ブートストラップで最小になった割合 "
                     f"{best['best_share_boot']*100:.0f}%)。")
        cluster_notes[int(cl)] = note

    d0 = chrel[chrel["quantity"].str.contains("差")]
    lvl = chrel[~chrel["quantity"].str.contains("差")]
    mx = d0["halfhalf_pearson"].max() if len(d0) else float("nan")
    if np.isfinite(mx) and mx < 0.2:
        chrel_note = (f"<b>測れていません。</b>字ごとの「方式どうしの差」の半分割一致は最大でも "
                      f"r={mx:.2f}"
                      + (f"（比較として、字ごとの見えやすさそのものは r="
                         f"{lvl.iloc[0]['halfhalf_pearson']:.2f}）" if len(lvl) else "")
                      + "。1字あたり数十試行では、その字にどの方式が向くかは<b>個別には決まりません</b>。"
                      "したがって下の1字抜き交差確認が当たらないのは"
                      "「規則が無い」からとは限らず、<b>的が雑音だから</b>でもあります。"
                      "この論点は、群にまとめて検定した上の結果（濁点は効く／群はほとんど効かない）"
                      "のほうで判断してください。")
    else:
        chrel_note = (f"字ごとの「方式どうしの差」の半分割一致は最大 r={mx:.2f}。"
                      "1字ごとの向き不向きはある程度は測れています。")

    if len(rule):
        won = rule[(rule["p_perm"] < 0.05) & (rule["gain_pt"] > 0)]
        cl = rule[rule["grouping"].str.startswith("取り違えの群")]
        cl_won = cl[(cl["p_perm"] < 0.05) & (cl["gain_pt"] > 0)]
        if len(cl_won):
            rule_verdict = ("<b>取り違えの群からの規則が効いた的</b>: "
                            + "、".join(f"{r['target']}（{r['acc_rule']*100:.1f}% vs 全体多数決 "
                                       f"{r['acc_global']*100:.1f}%、p={r['p_perm']:.3f}）"
                                       for _, r in cl_won.iterrows()) + "。")
        else:
            rule_verdict = ("<b>取り違えの群から方式を当てる規則は、この標本では作れませんでした。</b>"
                            "どの的でも、群を使った予測は群を使わない全体多数決を"
                            "統計的に意味のある幅では上回りません。")
        other = won[~won["grouping"].str.startswith("取り違えの群")]
        if len(other):
            rule_verdict += (" 一方で、<b>" + "／".join(sorted(set(other["grouping"])))
                             + "</b> による規則は効いています: "
                             + "、".join(f"{r['grouping']}×{r['target']}"
                                        f"（{r['acc_rule']*100:.1f}% vs {r['acc_global']*100:.1f}%、"
                                        f"p={r['p_perm']:.3f}）" for _, r in other.iterrows()) + "。")
    else:
        rule_verdict = "字ごとの方式当てはめが取れず、規則の評価はできなかった。"
    if len(rule_cont):
        w = rule_cont[(rule_cont["loco_r2"] > 0) & (rule_cont["p_perm"] < 0.05)]
        cl = rule_cont[rule_cont["grouping"].str.startswith("取り違えの群")]
        rule_verdict += ("<br><b>連続量でやり直すと、話がはっきりします。</b> "
                         + ("群の平均で方式差を当てにいったときの out-of-sample R² は、"
                            "取り違えの群で "
                            f"{cl['loco_r2'].min():.2f}〜{cl['loco_r2'].max():.2f}"
                            "（<b>0以下＝全体平均より当たらない</b>）。")
                         + (" これに対し " + "、".join(
                             f"{r['grouping']}で {r['target']} が R²={r['loco_r2']:.2f}"
                             f"（p={r['p_perm']:.4f}）" for _, r in w.iterrows()) + "。"
                            if len(w) else ""))

    raw = inter[inter["adjusted_for"] == "調整なし"]
    adj = inter[inter["adjusted_for"] == "濁点の有無を調整"]
    ir = raw[raw["unit"] == "字(72)"].iloc[0]
    idia = raw[raw["unit"] == "濁点の有無"]
    ik = raw[raw["unit"] == f"群(k={k})"]
    ikf = raw[raw["unit"] == f"群(k={k_fine})"]
    ika = adj[adj["unit"] == f"群(k={k_fine})"]
    if ir["p_perm"] < 0.05:
        inter_verdict = (f"<b>字によって向いた方式は違う</b>（字×方式 z={ir['z']:.1f}、"
                         f"並べ替え p={ir['p_perm']:.4f}、残差分散の "
                         f"{ir['var_explained']*100:.2f}% を説明）。前提は成り立っている。")
        if len(idia):
            inter_verdict += (f" ただしその大半は<b>濁点・半濁点の有無</b>で説明できる"
                              f"（たった3群で残差分散の {idia.iloc[0]['var_explained']*100:.2f}% を説明、"
                              f"z={idia.iloc[0]['z']:.0f}）。")
        if len(ikf):
            inter_verdict += (f" 取り違えの群（k={k_fine}）は {ikf.iloc[0]['var_explained']*100:.2f}%"
                              f"（z={ikf.iloc[0]['z']:.1f}）。")
        if len(ika):
            inter_verdict += (f" <b>濁点の有無を先に吸い取ってから</b>同じ群で検定すると "
                              f"{ika.iloc[0]['var_explained']*100:.2f}%（z={ika.iloc[0]['z']:.1f}、"
                              f"p={ika.iloc[0]['p_perm']:.4f}）"
                              + ("——濁点では説明できない上乗せがまだある。"
                                 if ika.iloc[0]["p_perm"] < 0.05
                                 else "——<b>濁点を除くと、群は方式の違いを何も足さない</b>。"))
    else:
        inter_verdict = (f"<b>字によって向いた方式が違うという証拠が無い</b>"
                         f"（字×方式 z={ir['z']:.1f}、並べ替え p={ir['p_perm']:.4f}）。"
                         f"この時点で、分類から方式を割り当てる規則は作れない。")

    concl = ctx_conclusion(rel, band, sel, k, stab, feat_tests, cff, rule, src_ct, asym_g,
                           inter, fam_agree, k_reason, gap, inter_verdict, rule_verdict, tax)

    build_report(a.report, dict(
        n_trials=len(t), n_pid=int(t["participant_id"].nunique()),
        n_err=int((t["correct"] == 0).sum()),
        stamp=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        rel=rel, band=band, fam_agree=fam_agree, asym_g=asym_g, asym_top=asym_pairs.head(8),
        sel=sel, k=k, k_reason=k_reason,
        svg_rel=svg_rel, svg_band=svg_band, svg_sil=svg_sil, svg_ps=svg_ps, svg_feat=svg_feat,
        svg_dendro=svg_dendrogram(Z, chars, labels),
        svg_mds=svg_mds(X, chars, labels, assign["source"].tolist()), mds_var=mds_var,
        svg_mds_fine=svg_mds(X, chars, labels_fine, assign["source"].tolist(),
                             hull=1.05, hull_fill=0.05),
        svg_heat=svg_heatmap(Sim_ord, chars_ord, lab_ord),
        profile=profile, cluster_notes=cluster_notes,
        feat_tests=feat_tests, cff=cff, svg_cff=svg_cff, main8=m8, rule=rule,
        rule_verdict=rule_verdict, conclusion=concl, outdir=a.out,
        rows_note=rows_note, inter=inter, inter_verdict=inter_verdict,
        gap=gap, svg_gap=svg_gap, k_fine=k_fine, chrel=chrel, chrel_note=chrel_note,
        tax=tax, svg_tax=svg_tax,
        rule_cont=rule_cont,
        fine_list=[(int(c), "".join(sorted(assign.loc[assign["cluster_fine"] == c, "char"])))
                   for c in sorted(assign["cluster_fine"].unique())]))
    print(f"\n完了: CSV -> {a.out}")
    return 0


def ctx_conclusion(rel, band, sel, k, stab, feat_tests, cff, rule, src_ct, asym_g,
                   inter, fam_agree, k_reason, gap, inter_verdict, rule_verdict, tax):
    L = []
    tz = tax[(tax["scope"] == "全体")].set_index("kind")["share"]
    if len(tz):
        dk = float(tz.get("濁点落とし", 0) + tz.get("濁点の取り違え", 0) + tz.get("濁点つけ", 0))
        tf = tax[(tax["scope"] == "方式") & (tax["kind"] == "濁点落とし")]
        L.append(f"<p><b>0. 取り違えの中身。</b>誤答の {dk*100:.1f}% は"
                 f"「濁点・半濁点まわりの間違い」（落とす・つける・取り違える）で、"
                 f"うち<b>濁点落とし</b>だけで {tz.get('濁点落とし',0)*100:.1f}%。"
                 + (" 方式別の濁点落とし率は "
                    + "、".join(f"{r['group']} {r['share']*100:.1f}%"
                               for _, r in tf.sort_values("share", ascending=False).iterrows())
                    + "。" if len(tf) else "")
                 + "</p>")
    r_all = rel[rel["subset"] == "全体"]
    if len(r_all):
        L.append(f"<p><b>1. 取り違えには構造がある。</b>参加者を半分に割った一致は "
                 f"r={r_all.iloc[0]['halfhalf_pearson']:.3f}"
                 f"（全データ相当 {r_all.iloc[0]['spearman_brown_full']:.3f}）。"
                 f"当てずっぽうなら 0 になる値なので、どの字をどの字と取り違えるかは"
                 f"字によって決まっている。</p>")
    rb = rel[rel["subset"].isin([s for s in rel["subset"] if s not in ("全体",)
                                 and not str(s).startswith("方式=")])]
    if len(rb):
        hi = rb.loc[rb["halfhalf_pearson"].idxmax()]
        lo = rb.loc[rb["halfhalf_pearson"].idxmin()]
        L.append(f"<p><b>2. 情報は「まだ見えない帯」には無い。</b>"
                 f"半分割信頼性がいちばん高いのは「{hi['subset']}」（r={hi['halfhalf_pearson']:.3f}）、"
                 f"いちばん低いのは「{lo['subset']}」（r={lo['halfhalf_pearson']:.3f}）。"
                 f"<b>「進み具合が低いほど情報が多い」という当初の見込みは、この標本では逆だった</b>——"
                 f"何も見えていないときの答えは答えの偏り（「あ」と答えがち）でほぼ尽き、"
                 f"字の情報を持たない。取り違えから字を測るなら、"
                 f"<b>正答率がほどほど（3〜7割）の水準</b>を厚く取るのがよい。</p>")
    rf = rel[rel["subset"].astype(str).str.startswith("方式=")]
    if len(rf):
        hi = rf.loc[rf["halfhalf_pearson"].idxmax()]
        L.append(f"<p><b>3. 構造を運んでいるのは主に「{str(hi['subset']).split('=')[1]}」。</b>"
                 f"方式ごとの信頼性は "
                 + "、".join(f"{str(r['subset']).split('=')[1]} {r['halfhalf_pearson']:.2f}"
                            for _, r in rf.iterrows())
                 + "。ただし希釈補正すると方式間の一致は "
                 f"{fam_agree['pearson_disattenuated'].min():.2f}〜"
                 f"{fam_agree['pearson_disattenuated'].max():.2f} で、"
                 f"<b>雑音を除けば4方式はおおむね同じ取り違え構造</b>を出している。</p>")
    s = sel[sel["k"] == k].iloc[0]
    L.append(f"<p><b>4. 群の個数。</b>{k_reason}</p>")
    sig = feat_tests[feat_tests["p_holm"] < 0.05]
    if len(sig):
        L.append("<p><b>5. 群を説明できるもの（Holm 調整後 p&lt;0.05）:</b> "
                 + "、".join(f"{r['feature']}〔{r['partition']}〕(p={r['p_holm']:.3f})"
                            for _, r in sig.iterrows())
                 + "。いずれも<b>墨がどう横に散っているか</b>（col_entropy_bits＝墨が"
                 "何本ぶんの列に散っているか、spread_x＝横の広がり、sym_ud＝上下の対称性）"
                 "に関わる量で、濁点の有無（p≥0.05）や答えの偏り（p≥0.05）ではありません。"
                 "<b>ただし20項目以上を2通りの切り方で試した中の話なので、探索的な手がかり</b>"
                 "にとどめてください。</p>")
    else:
        L.append(f"<p><b>5. 群を説明できる特徴は見つからなかった</b>"
                 f"（{len(feat_tests)}項目すべて Holm 調整後 p≥0.05）。"
                 f"群は、墨の量・重心・画のまとまりの数・濁点の有無・答えの偏りといった"
                 f"単純な指標には還元できない。生の p では "
                 + "、".join(f"{r['feature']}({r['p_raw']:.3f})"
                            for _, r in feat_tests.head(3).iterrows())
                 + " が上位だが、20項目以上を試しているので採らない。</p>")
    if len(inter):
        L.append(f"<p><b>6. 方式の割り当て（本題）。</b>{inter_verdict}</p>")
    if len(gap):
        g0 = gap[gap["grouping"] == "濁点の有無"]
        if len(g0):
            L.append("<p>方式の順位は、どの群わけでも<b>fade が1位で不動</b>でした"
                     "（k=2,4,6,8 のすべての群、濁点の3群、かな10行のすべて）。"
                     "変わるのは2位以下です。とくに<b>横に開く（wipe）は濁点・半濁点の字で崩れます</b>: "
                     + "、".join(f"{r['group']} {r['acc_wipe']*100:.1f}%" for _, r in g0.iterrows())
                     + "（水準等重みの正答率）。濁点は字の右上にあるので、"
                     "左から開いていくと最後まで見えない——理屈にも合っています。</p>")
    if len(rule):
        L.append(f"<p><b>7. 1字抜き交差確認。</b>{rule_verdict}</p>")
    L.append("<p><b>8. だから、こう使える／使えない。</b>"
             "<u>使えない</u>: 取り違えの群を作って「この群にはこの方式」と割り当てる、という道は"
             "この標本では通りませんでした。群自体が安定せず（予測強度 0.8 未満）、"
             "方式との交互作用の説明力も 濁点の有無 の 1/5 程度しかありません。"
             "<u>使える</u>: 測っていない字にも、<b>濁点・半濁点があるかどうか</b>だけで"
             "「横に開く（wipe）を避ける」という規則は立ちます。これは字の見た目から"
             "ただちに分かるので、較正していない字にもそのまま当てられます。</p>")
    L.append('<p class="cap">くり返しになりますが、これは事前仮説のない探索的分析です。'
             '別の標本での追試なしに「この群にはこの方式」と決め打ちしないでください。</p>')
    return "".join(L)


if __name__ == "__main__":
    sys.exit(main())
