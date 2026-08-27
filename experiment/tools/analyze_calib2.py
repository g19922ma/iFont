#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calib2(追いバッチ)本解析 -- WISS2026 転写検証実験
==============================================================

対象データ: project/data_calib2_live/transfer_trials.csv
  phase="calib"  … 実験1(視覚 aprime 163人 + 聴覚 acal 90人)
  phase="calib2" … 追いバッチ(視覚 aprime 162人)

■ 方針(固定)
  - **生の正答率のみ**を使う。λ正規化はしない。
  - 本命8字(あ か が ぱ し つ ま ら)をすべて使う。
  - 多重比較は Holm 法で調整し、raw p と調整後 p の両方を出す。
  - 実測していない数値は出さない。

■ 本解析で発見した最重要事項(データ品質)
  **WebKit(iOS 全ブラウザ・iOSアプリ内WebView・macOS Safari)では
    canvas の `ctx.filter = blur(...)` が効かない。** ぼやけ方式の刺激が
  一切ぼけず、鮮明な字がそのまま出ていた。実測: WebKit端末のぼやけ正答率は
  進み具合3%(半径69.8px=判読不能のはず)でも 100%。fade/reveal/wipe は正常。
  → **ぼやけの解析からは WebKit 端末を必ず除外する**(本スクリプトの既定)。

使い方
------
  python3 experiment/tools/analyze_calib2.py \
      --in  project/data_calib2_live/transfer_trials.csv \
      --out project/data_calib2_live/analysis
"""
import argparse
import os
import sys
import math
import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import minimize_scalar

RNG = np.random.default_rng(20260827)
GAMMA = 1.0 / 72.0          # 72択強制選択の当てずっぽう率
TARGETS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
FAMILIES = ["fade", "reveal", "blur", "wipe"]
NBOOT = 4000


# ---------------------------------------------------------------- 読み込み
def load(path):
    d = pd.read_csv(path, low_memory=False)
    # 真偽値列の正規化(CSV は TRUE/FALSE 文字列)
    for c in ["correct", "is_decoy", "is_filler", "is_catch", "touch",
              "resp_in_target_set", "resp_in_frequent_set"]:
        if c in d.columns:
            d[c] = d[c].map({True: True, False: False, "TRUE": True, "FALSE": False,
                             "True": True, "False": False}).astype("boolean")
    ua = d["ua"].fillna("").astype(str)
    # WebKit エンジン判定。
    #   iOS は全ブラウザが WebKit(Chrome iOS/Firefox iOS も含む)。
    #   macOS は Safari(Chrome/Edge/Firefox を含まない UA)だけが WebKit。
    d["webkit"] = (
        ua.str.contains("iPhone|iPad|iPod", regex=True)
        | (ua.str.contains("Macintosh")
           & ua.str.contains("Safari")
           & ~ua.str.contains("Chrome|Chromium|Edg/|Firefox", regex=True))
    )
    d["engine"] = np.where(
        d["webkit"], "WebKit",
        np.where(ua.str.contains("Firefox"), "Firefox",
                 np.where(ua.str.contains("Edg/"), "Edge",
                          np.where(ua.str.contains("Android"), "Chrome(Android)",
                                   "Chrome(Desktop)"))))
    return d


def visual_all(d):
    """視覚試行すべて(本命・まぎれ字・確認問題を区別できる形で返す)。"""
    v = d[d["modality"] == "transfer_visual"].copy()
    v["correct"] = v["correct"].astype(bool)
    v["T_ms"] = v["actual_ms"].astype(float)      # 字が映っていた実測時間
    return v


def main_rows(v):
    """本命試行(まぎれ字・フィラー・確認問題を除く)。"""
    return v[(v["is_decoy"] != True) & (v["is_filler"] != True)
             & (v["check_kind"].isna())].copy()


def decoy_rows(v):
    return v[(v["is_decoy"] == True) & (v["check_kind"].isna())].copy()


# ---------------------------------------------------------------- 統計道具
def wilson(k, n, z=1.959963985):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def diff_test(k1, n1, k2, n2):
    """2群の割合差(1 − 2)。Wald の95%CI と、プールした z 検定の両側 p。"""
    if n1 == 0 or n2 == 0:
        return dict(diff=np.nan, lo=np.nan, hi=np.nan, z=np.nan, p=np.nan)
    p1, p2 = k1 / n1, k2 / n2
    dd = p1 - p2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    pp = (k1 + k2) / (n1 + n2)
    se0 = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    z = dd / se0 if se0 > 0 else 0.0
    return dict(diff=dd, lo=dd - 1.96 * se, hi=dd + 1.96 * se,
                z=z, p=2 * (1 - norm.cdf(abs(z))))


def holm(pvals):
    """Holm-Bonferroni 調整後 p。"""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    prev = 0.0
    for i, idx in enumerate(order):
        val = (m - i) * p[idx]
        prev = max(prev, val)
        adj[idx] = min(1.0, prev)
    return adj


def cluster_boot_diff(df, key, valA, valB, weight_col=None, nboot=NBOOT):
    """参加者単位ブートストラップで「A群 − B群」の正答率差の95%CI。

    weight_col を渡すと、その列の水準ごとに平均してから水準を等重みで束ねる
    (水準構成の偏りを打ち消した比較になる)。
    実装は numpy 行列で行う(参加者 × セル の 成功数/試行数 を先に作る)。
    """
    df = df[df[key].isin([valA, valB])]
    if len(df) == 0:
        return np.nan, np.nan, np.nan, np.nan
    if weight_col is None:
        cells = pd.Series(["_"] * len(df), index=df.index)
    else:
        cells = df[weight_col].astype(str)
    cell_codes, cell_names = pd.factorize(cells)
    nc = len(cell_names)

    out = {}
    for g in (valA, valB):
        sel = (df[key] == g).values
        if sel.sum() == 0:
            return np.nan, np.nan, np.nan, np.nan
        pid = df.loc[sel, "participant_id"].values
        pcodes, pnames = pd.factorize(pid)
        npart = len(pnames)
        K = np.zeros((npart, nc))
        N = np.zeros((npart, nc))
        np.add.at(K, (pcodes, cell_codes[sel]), df.loc[sel, "correct"].values.astype(float))
        np.add.at(N, (pcodes, cell_codes[sel]), 1.0)
        out[g] = (K, N, npart)

    def stat(idxA, idxB):
        vals = []
        for g, idx in ((valA, idxA), (valB, idxB)):
            K, N, _ = out[g]
            k = K[idx].sum(axis=0)
            n = N[idx].sum(axis=0)
            ok = n > 0
            if not ok.any():
                return np.nan
            vals.append(float(np.mean(k[ok] / n[ok])))
        return vals[0] - vals[1]

    allA = np.arange(out[valA][2])
    allB = np.arange(out[valB][2])
    point = stat(allA, allB)
    boots = np.empty(nboot)
    for i in range(nboot):
        ia = RNG.integers(0, len(allA), len(allA))
        ib = RNG.integers(0, len(allB), len(allB))
        boots[i] = stat(ia, ib)
    boots = boots[~np.isnan(boots)]
    if len(boots) < 100:
        return point, np.nan, np.nan, np.nan
    lo, hi = np.percentile(boots, [2.5, 97.5])
    # 両側 p(ブートストラップ分布が0をまたぐ割合)
    pv = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    return point, lo, hi, max(pv, 1.0 / len(boots))


# ============================================================ 各解析
def a_render_bug(v, out):
    """[A] WebKit のぼやけ描画不全の証拠表。"""
    rows = []
    m = v[v["check_kind"].isna()]
    for fam in FAMILIES:
        s = m[m["family"] == fam]
        for eng in ["WebKit", "Chrome(Desktop)", "Chrome(Android)", "Edge", "Firefox"]:
            for ph in ["calib", "calib2"]:
                for lv, g in s[(s["engine"] == eng) & (s["phase"] == ph)].groupby("progress_pct"):
                    p, lo, hi = wilson(g["correct"].sum(), len(g))
                    rows.append(dict(family=fam, engine=eng, phase=ph, progress_pct=lv,
                                     n=len(g), n_participants=g["participant_id"].nunique(),
                                     acc=p, lo=lo, hi=hi))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "render_bug_by_engine.csv"), index=False)

    # 要約: 方式ごとに「WebKit vs 非WebKit」の低水準(<100%)正答率
    rows = []
    for fam in FAMILIES:
        s = m[(m["family"] == fam) & (m["progress_pct"] < 100)]
        for wk in [True, False]:
            g = s[s["webkit"] == wk]
            p, lo, hi = wilson(g["correct"].sum(), len(g))
            rows.append(dict(family=fam, webkit=wk, n=len(g),
                             n_participants=g["participant_id"].nunique(),
                             acc=p, lo=lo, hi=hi))
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(out, "render_bug_summary.csv"), index=False)

    # 端末の効果(WebKit のぼやけ不全と、それ以外の端末差を区別するため)。
    # 携帯(Android/iOS)と机上(Windows/mac)で、方式ごとに水準を等重みでそろえて比べる。
    ua = m["ua"].fillna("").astype(str)
    m2 = m.copy()
    m2["mobile"] = ua.str.contains("iPhone|iPad|iPod|Android", regex=True)
    rows = []
    for fam in FAMILIES:
        for excl in ([False, True] if fam == "blur" else [False]):
            s = m2[m2["family"] == fam]
            if excl:
                s = s[~s["webkit"]]
            s = s.copy()
            s["cell"] = s["phase"].astype(str) + "|" + s["progress_pct"].astype(str)
            pt, lo, hi, pv = cluster_boot_diff(s, "mobile", True, False, weight_col="cell")
            rows.append(dict(family=fam, webkit_excluded=excl, n=len(s),
                             mobile_minus_desktop_pt=100 * pt,
                             lo_pt=100 * lo, hi_pt=100 * hi, p_boot=pv))
    dv = pd.DataFrame(rows)
    dv.to_csv(os.path.join(out, "device_effect_by_family.csv"), index=False)
    return df, sm


def curves(v, out):
    """[B] 方式×水準×フェーズの生の正答率曲線(ぼやけはWebKit除外)。"""
    rows = []
    m = main_rows(v)
    dc = decoy_rows(v)
    for label, src in [("main8", m), ("decoy", dc)]:
        for fam in FAMILIES:
            s = src[src["family"] == fam]
            if fam == "blur":
                s = s[~s["webkit"]]
            for (ph, lv), g in s.groupby(["phase", "progress_pct"]):
                p, lo, hi = wilson(g["correct"].sum(), len(g))
                rows.append(dict(trial_set=label, family=fam, phase=ph, progress_pct=lv,
                                 n=len(g), k=int(g["correct"].sum()),
                                 T_ms_median=g["T_ms"].median(),
                                 acc=p, lo=lo, hi=hi,
                                 webkit_excluded=(fam == "blur")))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "curves_by_family.csv"), index=False)
    return df


def blur_mystery(v, out):
    """[C] ぼやけの謎: 実験1 vs calib2 の差を速さ・提示時間・端末で層別。"""
    m = main_rows(v)
    dc = decoy_rows(v)
    both = pd.concat([m.assign(trial_set="main8"), dc.assign(trial_set="decoy")],
                     ignore_index=True)
    b = both[(both["family"] == "blur") & (both["progress_pct"].isin([26.0, 48.0, 100.0]))]

    rows = []

    def add(stratum, level, sub):
        c1 = sub[sub["phase"] == "calib"]
        c2 = sub[sub["phase"] == "calib2"]
        k1, n1 = int(c1["correct"].sum()), len(c1)
        k2, n2 = int(c2["correct"].sum()), len(c2)
        r = diff_test(k2, n2, k1, n1)      # calib2 − calib
        rows.append(dict(stratum=stratum, progress_pct=level,
                         n_calib=n1, acc_calib=(k1 / n1 if n1 else np.nan),
                         n_calib2=n2, acc_calib2=(k2 / n2 if n2 else np.nan),
                         diff_pt=100 * r["diff"], lo_pt=100 * r["lo"], hi_pt=100 * r["hi"],
                         z=r["z"], p_raw=r["p"]))

    for lv in [26.0, 48.0, 100.0]:
        s = b[b["progress_pct"] == lv]
        add("all devices / all trials", lv, s)
        add("WebKit excluded", lv, s[~s["webkit"]])
        add("WebKit only", lv, s[s["webkit"]])
        nb = s[~s["webkit"]]
        add("WebKit excl / main8 only", lv, nb[nb["trial_set"] == "main8"])
        add("WebKit excl / decoy only", lv, nb[nb["trial_set"] == "decoy"])
        for sp in [300.0, 500.0]:
            add(f"WebKit excl / base_anim={int(sp)}ms", lv, nb[nb["base_anim_ms"] == sp])
        # 実測提示時間で層別(同一セルなので両フェーズでほぼ同一のはず)
        for lab, q in [("T<=150ms", nb["T_ms"] <= 150), ("T>150ms", nb["T_ms"] > 150)]:
            add(f"WebKit excl / {lab}", lv, nb[q])
        for eng in ["Chrome(Desktop)", "Chrome(Android)", "Edge", "Firefox"]:
            add(f"WebKit excl / {eng}", lv, nb[nb["engine"] == eng])
        for lab, q in [("touch", nb["touch"] == True), ("non-touch", nb["touch"] != True)]:
            add(f"WebKit excl / {lab}", lv, nb[q])
        # 試行順(3分位)
        nb2 = nb.copy()
        try:
            nb2["tert"] = pd.qcut(nb2["trial_index"], 3, labels=["early", "mid", "late"])
            for t in ["early", "mid", "late"]:
                add(f"WebKit excl / order={t}", lv, nb2[nb2["tert"] == t])
        except Exception:
            pass
        # 字をそろえた比較(本命8字のみ、字ごとの差を等重み平均)
        mm = nb[nb["trial_set"] == "main8"]
        per = []
        for ch in TARGETS:
            g = mm[mm["target_char"] == ch]
            a = g[g["phase"] == "calib"]["correct"]
            c = g[g["phase"] == "calib2"]["correct"]
            if len(a) and len(c):
                per.append(c.mean() - a.mean())
        if per:
            rows.append(dict(stratum="WebKit excl / char-matched (main8, equal weight)",
                             progress_pct=lv, n_calib=len(mm[mm["phase"] == "calib"]),
                             acc_calib=np.nan,
                             n_calib2=len(mm[mm["phase"] == "calib2"]), acc_calib2=np.nan,
                             diff_pt=100 * float(np.mean(per)), lo_pt=np.nan, hi_pt=np.nan,
                             z=np.nan, p_raw=np.nan))

    df = pd.DataFrame(rows)
    # 主要3検定(WebKit除外 × 3水準)に Holm
    key = df["stratum"].eq("WebKit excluded")
    df.loc[key, "p_holm_primary"] = holm(df.loc[key, "p_raw"].values)
    df.to_csv(os.path.join(out, "blur_phase_gap.csv"), index=False)

    # 参加者クラスタ・ブートストラップ版(主要判定)
    rows = []
    for lv in [26.0, 48.0, 100.0]:
        sub = b[(b["progress_pct"] == lv) & (~b["webkit"])]
        pt, lo, hi, pv = cluster_boot_diff(sub, "phase", "calib2", "calib")
        rows.append(dict(progress_pct=lv, diff_pt=100 * pt, lo_pt=100 * lo,
                         hi_pt=100 * hi, p_boot=pv, n=len(sub)))
    bt = pd.DataFrame(rows)
    bt["p_holm"] = holm(bt["p_boot"].values)
    bt.to_csv(os.path.join(out, "blur_phase_gap_bootstrap.csv"), index=False)

    # 提示時間が両フェーズで一致していることの証拠表
    tt = (b.groupby(["phase", "progress_pct", "base_anim_ms"])
            .agg(n=("T_ms", "size"), T_median=("T_ms", "median"), T_mean=("T_ms", "mean"),
                 frames_median=("actual_frames", "median"),
                 endpoint_ms_median=("endpoint_actual_ms", "median"))
            .reset_index())
    tt.to_csv(os.path.join(out, "blur_presentation_time_check.csv"), index=False)
    return df, bt, tt


def blur_learning(v, out):
    """[C2] 残差の正体: 「セッション中の慣れ」が実験1にだけ起きている。

    ぼやけの水準セットが違うと、参加者がセッション中に見る「読めるぼやけ」の
    数が変わる。実験1(26〜100%)は読める見本が何度も出るので**慣れて上手くなる**が、
    calib2(3〜100%)はほぼ全部読めないので慣れが起きない(むしろ下がる)。
    水準48%(両実験に共通で、かつ床でも天井でもない唯一の水準)で検証する。
    """
    both = pd.concat([main_rows(v).assign(trial_set="main8"),
                      decoy_rows(v).assign(trial_set="decoy")], ignore_index=True)
    b = both[(both["family"] == "blur") & (~both["webkit"])].copy()

    # 割付の無作為化チェック(試行順と水準が独立か)
    b["tertile"] = pd.qcut(b["trial_index"], 3, labels=["early", "mid", "late"])
    rnd = (b.groupby(["phase", "tertile"], observed=True)["progress_pct"]
             .agg(["size", "mean"]).reset_index())
    rnd.to_csv(os.path.join(out, "blur_order_randomisation_check.csv"), index=False)

    rows = []
    for lv in [26.0, 48.0, 100.0]:
        s = b[b["progress_pct"] == lv]
        for (ph, t), g in s.groupby(["phase", "tertile"], observed=True):
            p, lo, hi = wilson(g["correct"].sum(), len(g))
            rows.append(dict(progress_pct=lv, phase=ph, split="trial_index tertile",
                             bin=str(t), n=len(g), acc=p, lo=lo, hi=hi))
    # 「その参加者にとって何回目のぼやけ試行か」
    b = b.sort_values(["participant_id", "trial_index"])
    b["blur_seq"] = b.groupby(["phase", "participant_id"]).cumcount()
    legible = (b["progress_pct"] >= 48.0).astype(int)
    b["prior_legible"] = legible.groupby(b["participant_id"]).cumsum() - legible
    for lv in [26.0, 48.0]:
        s = b[b["progress_pct"] == lv]
        for (ph, t), g in s.groupby(["phase", pd.cut(s["blur_seq"], [-1, 1, 3, 5, 7, 99])],
                                    observed=True):
            p, lo, hi = wilson(g["correct"].sum(), len(g))
            rows.append(dict(progress_pct=lv, phase=ph, split="blur trial # within session",
                             bin=str(t), n=len(g), acc=p, lo=lo, hi=hi))
        for (ph, t), g in s.groupby(["phase", s["prior_legible"].clip(0, 3)], observed=True):
            p, lo, hi = wilson(g["correct"].sum(), len(g))
            rows.append(dict(progress_pct=lv, phase=ph,
                             split="# of prior blur trials at >=48%",
                             bin=str(t), n=len(g), acc=p, lo=lo, hi=hi))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "blur_learning_by_order.csv"), index=False)

    # 位置 × フェーズ の交互作用(ロジスティック回帰)。blur48 と、対照として fade/reveal。
    rows = []
    try:
        import statsmodels.api as smapi
    except Exception:
        smapi = None
    if smapi is not None:
        def fit(sub, label, level_dummies=False):
            sub = sub.copy()
            sub["ph"] = (sub["phase"] == "calib2").astype(float)
            sub["pos"] = (sub["trial_index"] - 35.5) / 20.0
            X = pd.DataFrame({"phase_calib2": sub["ph"].values,
                              "pos": sub["pos"].values,
                              "phase_x_pos": (sub["ph"] * sub["pos"]).values})
            if level_dummies:
                D = pd.get_dummies(sub["progress_pct"].astype(str),
                                   prefix="lv", drop_first=True).astype(float)
                X = pd.concat([X, D.reset_index(drop=True)], axis=1)
            X = smapi.add_constant(X)
            r = smapi.Logit(sub["correct"].astype(float).values, X).fit(disp=0)
            for term in ["phase_calib2", "pos", "phase_x_pos"]:
                rows.append(dict(model=label, term=term, coef=r.params[term],
                                 se=r.bse[term], z=r.tvalues[term], p=r.pvalues[term]))

        fit(b[b["progress_pct"] == 48.0], "blur 48% (shared level)")
        for fam in ["fade", "reveal"]:
            fit(both[both["family"] == fam], f"{fam} (all levels, level-adjusted)",
                level_dummies=True)
    ia = pd.DataFrame(rows)
    ia.to_csv(os.path.join(out, "blur_learning_interaction.csv"), index=False)
    return df, ia


def bridge(v, out):
    """[D] 橋の確認: fade/reveal は両実験で一致するか(水準は完全共通)。"""
    m = main_rows(v)
    dc = decoy_rows(v)
    both = pd.concat([m.assign(trial_set="main8"), dc.assign(trial_set="decoy")],
                     ignore_index=True)
    rows = []
    for tset in ["main8", "decoy"]:
        for fam in ["fade", "reveal"]:
            s = both[(both["trial_set"] == tset) & (both["family"] == fam)]
            for lv, g in s.groupby("progress_pct"):
                c1 = g[g["phase"] == "calib"]; c2 = g[g["phase"] == "calib2"]
                r = diff_test(int(c2["correct"].sum()), len(c2),
                              int(c1["correct"].sum()), len(c1))
                rows.append(dict(trial_set=tset, family=fam, progress_pct=lv,
                                 n_calib=len(c1), acc_calib=c1["correct"].mean(),
                                 n_calib2=len(c2), acc_calib2=c2["correct"].mean(),
                                 T_calib=c1["T_ms"].median(), T_calib2=c2["T_ms"].median(),
                                 diff_pt=100 * r["diff"], lo_pt=100 * r["lo"],
                                 hi_pt=100 * r["hi"], p_raw=r["p"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "bridge_fade_reveal_by_level.csv"), index=False)

    # 方式ごとの総括(水準を等重みでそろえたブートストラップ差)
    rows = []
    for fam in ["fade", "reveal", "blur"]:
        s = main_rows(v)
        s = s[s["family"] == fam]
        if fam == "blur":
            s = s[(~s["webkit"]) & (s["progress_pct"].isin([26.0, 48.0, 100.0]))]
        pt, lo, hi, pv = cluster_boot_diff(s, "phase", "calib2", "calib",
                                          weight_col="progress_pct")
        rows.append(dict(family=fam, n_shared_levels=s["progress_pct"].nunique(),
                         diff_pt=100 * pt, lo_pt=100 * lo, hi_pt=100 * hi, p_boot=pv))
    sm = pd.DataFrame(rows)
    sm["p_holm"] = holm(sm["p_boot"].values)
    sm.to_csv(os.path.join(out, "bridge_summary.csv"), index=False)
    return df, sm


def blur_floor(v, out):
    """[E] ぼやけの床: 「ぼやけの床」か「提示時間の床」か。"""
    m = main_rows(v)
    dc = decoy_rows(v)
    both = pd.concat([m.assign(trial_set="main8"), dc.assign(trial_set="decoy")],
                     ignore_index=True)
    b = both[(both["family"] == "blur") & (both["phase"] == "calib2")]
    rows = []
    for wk_label, s0 in [("all devices", b), ("WebKit excluded", b[~b["webkit"]]),
                         ("WebKit only", b[b["webkit"]])]:
        for lv, g in s0.groupby("progress_pct"):
            p, lo, hi = wilson(g["correct"].sum(), len(g))
            # ぼかし半径(実装: 72px × (1 − s))
            rows.append(dict(subset=wk_label, progress_pct=lv,
                             blur_radius_px=72.0 * (1 - lv / 100.0),
                             n=len(g), acc=p, lo=lo, hi=hi,
                             T_ms_median=g["T_ms"].median(),
                             frames_median=g["actual_frames"].median(),
                             chance=GAMMA))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "blur_floor.csv"), index=False)

    # 提示時間の交絡を外す: 同じ水準を 300ms / 500ms で比べる(絵は同一、Tだけ違う)
    rows = []
    nb = b[~b["webkit"]]
    for lv, g in nb.groupby("progress_pct"):
        g3 = g[g["base_anim_ms"] == 300.0]; g5 = g[g["base_anim_ms"] == 500.0]
        r = diff_test(int(g5["correct"].sum()), len(g5),
                      int(g3["correct"].sum()), len(g3))
        rows.append(dict(progress_pct=lv,
                         T_300=g3["T_ms"].median(), acc_300=g3["correct"].mean(), n_300=len(g3),
                         T_500=g5["T_ms"].median(), acc_500=g5["correct"].mean(), n_500=len(g5),
                         diff_pt=100 * r["diff"], lo_pt=100 * r["lo"], hi_pt=100 * r["hi"],
                         p_raw=r["p"]))
    tf = pd.DataFrame(rows)
    tf["p_holm"] = holm(tf["p_raw"].fillna(1.0).values)
    tf.to_csv(os.path.join(out, "blur_floor_time_control.csv"), index=False)
    return df, tf


def wipe_geometry(v, out):
    """[F] 幾何予測: wipe で濁点字(が・ぱ)が終盤で跳ねるか。"""
    m = main_rows(v)
    w = m[(m["family"] == "wipe") & (m["phase"] == "calib2")]
    rows = []
    for (ch, lv), g in w.groupby(["target_char", "progress_pct"]):
        p, lo, hi = wilson(g["correct"].sum(), len(g))
        rows.append(dict(target_char=ch, progress_pct=lv, n=len(g), acc=p, lo=lo, hi=hi,
                         dakuten=(ch in ("が", "ぱ"))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "wipe_by_char.csv"), index=False)

    # 濁点字 vs 清音字 の水準ごとの対比
    rows = []
    for lv, g in w.groupby("progress_pct"):
        dk = g[g["target_char"].isin(["が", "ぱ"])]
        se = g[~g["target_char"].isin(["が", "ぱ"])]
        r = diff_test(int(dk["correct"].sum()), len(dk),
                      int(se["correct"].sum()), len(se))
        rows.append(dict(progress_pct=lv, n_dakuten=len(dk), acc_dakuten=dk["correct"].mean(),
                         n_sei=len(se), acc_sei=se["correct"].mean(),
                         diff_pt=100 * r["diff"], lo_pt=100 * r["lo"], hi_pt=100 * r["hi"],
                         p_raw=r["p"]))
    cf = pd.DataFrame(rows)
    cf["p_holm"] = holm(cf["p_raw"].fillna(1.0).values)
    cf.to_csv(os.path.join(out, "wipe_dakuten_contrast.csv"), index=False)

    # 65% → 80% の跳ね(濁点字/清音字それぞれ)
    rows = []
    for lab, sub in [("dakuten(が・ぱ)", w[w["target_char"].isin(["が", "ぱ"])]),
                     ("sei(6 chars)", w[~w["target_char"].isin(["が", "ぱ"])])]:
        for a, bb in [(50.0, 65.0), (65.0, 80.0), (80.0, 100.0)]:
            ga = sub[sub["progress_pct"] == a]; gb = sub[sub["progress_pct"] == bb]
            r = diff_test(int(gb["correct"].sum()), len(gb),
                          int(ga["correct"].sum()), len(ga))
            rows.append(dict(group=lab, step=f"{int(a)}->{int(bb)}",
                             n_from=len(ga), acc_from=ga["correct"].mean(),
                             n_to=len(gb), acc_to=gb["correct"].mean(),
                             jump_pt=100 * r["diff"], lo_pt=100 * r["lo"],
                             hi_pt=100 * r["hi"], p_raw=r["p"]))
    jp = pd.DataFrame(rows)
    jp["p_holm"] = holm(jp["p_raw"].fillna(1.0).values)
    jp.to_csv(os.path.join(out, "wipe_jump.csv"), index=False)
    return df, cf, jp


def reveal_jump(v, out):
    """[G] reveal 2%→4% の跳ね(両実験)。"""
    m = main_rows(v)
    r0 = m[m["family"] == "reveal"]
    rows = []
    for ph in ["calib", "calib2"]:
        s = r0[r0["phase"] == ph]
        for a, b_ in [(1.0, 2.0), (2.0, 4.0), (4.0, 9.0)]:
            ga = s[s["progress_pct"] == a]; gb = s[s["progress_pct"] == b_]
            r = diff_test(int(gb["correct"].sum()), len(gb),
                          int(ga["correct"].sum()), len(ga))
            rows.append(dict(phase=ph, step=f"{a}->{b_}",
                             n_from=len(ga), acc_from=ga["correct"].mean(),
                             T_from=ga["T_ms"].median(),
                             n_to=len(gb), acc_to=gb["correct"].mean(),
                             T_to=gb["T_ms"].median(),
                             jump_pt=100 * r["diff"], lo_pt=100 * r["lo"],
                             hi_pt=100 * r["hi"], p_raw=r["p"]))
    # 両実験プール
    for a, b_ in [(1.0, 2.0), (2.0, 4.0), (4.0, 9.0)]:
        ga = r0[r0["progress_pct"] == a]; gb = r0[r0["progress_pct"] == b_]
        r = diff_test(int(gb["correct"].sum()), len(gb), int(ga["correct"].sum()), len(ga))
        rows.append(dict(phase="pooled", step=f"{a}->{b_}",
                         n_from=len(ga), acc_from=ga["correct"].mean(), T_from=ga["T_ms"].median(),
                         n_to=len(gb), acc_to=gb["correct"].mean(), T_to=gb["T_ms"].median(),
                         jump_pt=100 * r["diff"], lo_pt=100 * r["lo"], hi_pt=100 * r["hi"],
                         p_raw=r["p"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "reveal_jump.csv"), index=False)

    # reveal 4% の速さ効果(τモデルから外れる点として既知)
    rows = []
    for ph in ["calib", "calib2", "pooled"]:
        s = r0 if ph == "pooled" else r0[r0["phase"] == ph]
        for lv in [2.0, 4.0]:
            g = s[s["progress_pct"] == lv]
            g3 = g[g["base_anim_ms"] == 300.0]; g5 = g[g["base_anim_ms"] == 500.0]
            r = diff_test(int(g5["correct"].sum()), len(g5),
                          int(g3["correct"].sum()), len(g3))
            rows.append(dict(phase=ph, progress_pct=lv,
                             n_300=len(g3), acc_300=g3["correct"].mean(), T_300=g3["T_ms"].median(),
                             n_500=len(g5), acc_500=g5["correct"].mean(), T_500=g5["T_ms"].median(),
                             diff_pt=100 * r["diff"], lo_pt=100 * r["lo"],
                             hi_pt=100 * r["hi"], p_raw=r["p"]))
    sp = pd.DataFrame(rows)
    sp.to_csv(os.path.join(out, "reveal4_speed.csv"), index=False)
    return df, sp


def speed_effect(v, out):
    """[H] 速さ(300 vs 500ms)の効果を方式ごとに。水準を等重みでそろえる。"""
    m = main_rows(v)
    rows = []
    for fam in FAMILIES:
        s = m[m["family"] == fam]
        if fam == "blur":
            s = s[~s["webkit"]]
        for ph in ["calib", "calib2", "pooled"]:
            sub = s if ph == "pooled" else s[s["phase"] == ph]
            if len(sub) == 0:
                continue
            # 水準×フェーズを等重みでそろえる(混ぜると水準セットの違いが混入する)
            sub = sub.copy()
            sub["cell"] = sub["phase"].astype(str) + "|" + sub["progress_pct"].astype(str)
            pt, lo, hi, pv = cluster_boot_diff(sub, "base_anim_ms", 500.0, 300.0,
                                               weight_col="cell")
            rows.append(dict(family=fam, phase=ph, n=len(sub),
                             diff_pt=100 * pt, lo_pt=100 * lo, hi_pt=100 * hi, p_boot=pv))
    df = pd.DataFrame(rows)
    key = df["phase"] == "pooled"
    df.loc[key, "p_holm_4families"] = holm(df.loc[key, "p_boot"].values)
    df.to_csv(os.path.join(out, "speed_effect_family.csv"), index=False)

    # 水準ごとの詳細
    rows = []
    for fam in FAMILIES:
        s = m[m["family"] == fam]
        if fam == "blur":
            s = s[~s["webkit"]]
        for (ph, lv), g in s.groupby(["phase", "progress_pct"]):
            g3 = g[g["base_anim_ms"] == 300.0]; g5 = g[g["base_anim_ms"] == 500.0]
            r = diff_test(int(g5["correct"].sum()), len(g5),
                          int(g3["correct"].sum()), len(g3))
            rows.append(dict(family=fam, phase=ph, progress_pct=lv,
                             n_300=len(g3), acc_300=g3["correct"].mean(), T_300=g3["T_ms"].median(),
                             n_500=len(g5), acc_500=g5["correct"].mean(), T_500=g5["T_ms"].median(),
                             diff_pt=100 * r["diff"], lo_pt=100 * r["lo"],
                             hi_pt=100 * r["hi"], p_raw=r["p"]))
    lv = pd.DataFrame(rows)
    lv["p_holm"] = holm(lv["p_raw"].fillna(1.0).values)
    lv.to_csv(os.path.join(out, "speed_effect_by_level.csv"), index=False)
    return df, lv


# ---------------------------------------------------------------- τ 推定
def tau_fit(v, out):
    """[I] 飽和指数モデル p = γ + (λ−γ)(1 − e^(−T/τ)) の τ を再推定。

    セル = 方式 × 水準(× フェーズ)。同一セル内で base_anim_ms が 300/500 の
    2つの部分セルがあり、**終点の絵は完全に同一・提示時間 T だけが違う**。
    λ はセルごとに最尤、τ は全セル共通の1つ。
    """
    m = main_rows(v)
    m = m[~((m["family"] == "blur") & (m["webkit"]))]

    cells = []
    for (ph, fam, lv), g in m.groupby(["phase", "family", "progress_pct"]):
        g3 = g[g["base_anim_ms"] == 300.0]; g5 = g[g["base_anim_ms"] == 500.0]
        if len(g3) < 20 or len(g5) < 20:
            continue
        T3, T5 = g3["T_ms"].median(), g5["T_ms"].median()
        if not (T5 > T3):
            continue
        cells.append(dict(phase=ph, family=fam, progress_pct=lv,
                          T1=float(T3), k1=int(g3["correct"].sum()), n1=len(g3),
                          T2=float(T5), k2=int(g5["correct"].sum()), n2=len(g5)))
    C = pd.DataFrame(cells)

    def cell_ll(c, tau):
        def nll(lam):
            ll = 0.0
            for T, k, n in [(c["T1"], c["k1"], c["n1"]), (c["T2"], c["k2"], c["n2"])]:
                p = GAMMA + (lam - GAMMA) * (1 - math.exp(-T / tau))
                p = min(max(p, 1e-9), 1 - 1e-9)
                ll += k * math.log(p) + (n - k) * math.log(1 - p)
            return -ll
        r = minimize_scalar(nll, bounds=(GAMMA, 1.0), method="bounded",
                            options={"xatol": 1e-6})
        return -r.fun, r.x

    taus = np.concatenate([np.arange(2, 60, 0.5), np.arange(60, 300, 2.0),
                           np.arange(300, 1001, 10.0)])
    lls = []
    for tau in taus:
        tot = 0.0
        for _, c in C.iterrows():
            l, _lam = cell_ll(c, tau)
            tot += l
        lls.append(tot)
    lls = np.array(lls)
    best_i = int(np.argmax(lls))
    tau_hat = float(taus[best_i])
    thr = lls[best_i] - 1.920729      # χ²(1) 95% / 2
    inside = taus[lls >= thr]
    tau_lo, tau_hi = float(inside.min()), float(inside.max())

    prof = pd.DataFrame(dict(tau_ms=taus, loglik=lls))
    prof.to_csv(os.path.join(out, "tau_profile_loglik.csv"), index=False)

    # セルごとの予測 vs 実測(τ̂ のもとで)
    rows = []
    for _, c in C.iterrows():
        _l, lam = cell_ll(c, tau_hat)
        for tag, T, k, n in [("short", c["T1"], c["k1"], c["n1"]),
                             ("long", c["T2"], c["k2"], c["n2"])]:
            pred = GAMMA + (lam - GAMMA) * (1 - math.exp(-T / tau_hat))
            obs = k / n
            se = math.sqrt(max(obs * (1 - obs), 1e-9) / n)
            rows.append(dict(phase=c["phase"], family=c["family"],
                             progress_pct=c["progress_pct"], which=tag,
                             T_ms=T, n=n, obs=obs, pred=pred, lam=lam,
                             resid_pt=100 * (obs - pred),
                             resid_in_2se=abs(obs - pred) <= 2 * se))
    fitdf = pd.DataFrame(rows)
    fitdf.to_csv(os.path.join(out, "tau_cell_fit.csv"), index=False)

    # 実験1のみ / calib2込み で τ の区間がどれだけ締まるか
    def fit_subset(mask, label):
        Cs = C[mask]
        if len(Cs) < 3:
            return None
        ls = []
        for tau in taus:
            ls.append(sum(cell_ll(c, tau)[0] for _, c in Cs.iterrows()))
        ls = np.array(ls)
        i = int(np.argmax(ls))
        ins = taus[ls >= ls[i] - 1.920729]
        return dict(subset=label, n_cells=len(Cs), tau_hat=float(taus[i]),
                    tau_lo=float(ins.min()), tau_hi=float(ins.max()),
                    ci_width=float(ins.max() - ins.min()))

    subs = [fit_subset(C["phase"] == "calib", "calib only (experiment 1)"),
            fit_subset(C["phase"] == "calib2", "calib2 only"),
            fit_subset(C["phase"].notna(), "calib + calib2")]
    # reveal 4% を外した版(既知の外れセル)
    mask = ~((C["family"] == "reveal") & (C["progress_pct"] == 4.0))
    subs.append(fit_subset(mask, "calib + calib2, reveal4% excluded"))
    sub = pd.DataFrame([s for s in subs if s])
    sub.to_csv(os.path.join(out, "tau_summary.csv"), index=False)
    return tau_hat, tau_lo, tau_hi, sub, fitdf


def participants(v, out):
    """[J] 参加者・端末構成の記述統計(フェーズ比較)。"""
    p = (v.sort_values("ts").groupby(["phase", "participant_id"])
         .agg(**{"browser_engine": ("engine", "last"), "webkit": ("webkit", "last"),
                 "dpr": ("dpr", "median"), "touch": ("touch", "last"),
                 "refresh_hz": ("refresh_hz", "median"),
                 "age_band": ("age_band", "last"),
                 "n_trials": ("correct", "size"), "acc": ("correct", "mean")})
         .reset_index())
    p.to_csv(os.path.join(out, "participants.csv"), index=False)
    rows = []
    for col in ["browser_engine", "webkit", "touch", "age_band"]:
        for ph in ["calib", "calib2"]:
            vc = p[p["phase"] == ph][col].value_counts(normalize=True)
            for k, val in vc.items():
                rows.append(dict(variable=col, level=str(k), phase=ph, share=val))
    pd.DataFrame(rows).to_csv(os.path.join(out, "participants_composition.csv"), index=False)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default="project/data_calib2_live/transfer_trials.csv")
    ap.add_argument("--out", dest="out",
                    default="project/data_calib2_live/analysis")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    d = load(a.inp)
    v = visual_all(d)
    print(f"視覚試行 {len(v)} 件 / 参加者 "
          f"{v.groupby('phase').participant_id.nunique().to_dict()}")

    print("[A] WebKit 描画不全の検証 ...")
    _, bugsm = a_render_bug(v, a.out)
    print(bugsm.to_string(index=False))

    print("\n[B] 方式ごとの曲線 ...")
    curves(v, a.out)

    print("\n[C] ぼやけの謎 ...")
    gap, bt, _tt = blur_mystery(v, a.out)
    print(gap[gap["stratum"].isin(["all devices / all trials", "WebKit excluded",
                                   "WebKit only"])].to_string(index=False))
    print(bt.to_string(index=False))

    print("\n[C2] 残差の正体(セッション中の慣れ) ...")
    lrn, ia = blur_learning(v, a.out)
    print(lrn[(lrn["progress_pct"] == 48.0)
              & (lrn["split"] == "trial_index tertile")].to_string(index=False))
    print(ia.to_string(index=False))

    print("\n[D] 橋(fade/reveal)の確認 ...")
    _, bsm = bridge(v, a.out)
    print(bsm.to_string(index=False))

    print("\n[E] ぼやけの床 ...")
    fl, ftc = blur_floor(v, a.out)
    print(fl[fl["subset"] == "WebKit excluded"].to_string(index=False))

    print("\n[F] wipe の幾何予測 ...")
    _, _, jp = wipe_geometry(v, a.out)
    print(jp.to_string(index=False))

    print("\n[G] reveal 2%→4% ...")
    rj, _ = reveal_jump(v, a.out)
    print(rj.to_string(index=False))

    print("\n[H] 速さの効果 ...")
    se, _ = speed_effect(v, a.out)
    print(se.to_string(index=False))

    print("\n[I] τ の再推定 ...")
    tau, lo, hi, tsum, _ = tau_fit(v, a.out)
    print(f"tau = {tau:.1f} ms  95%CI [{lo:.1f}, {hi:.1f}]")
    print(tsum.to_string(index=False))

    print("\n[J] 参加者構成 ...")
    participants(v, a.out)
    print(f"\n出力先: {a.out}")


if __name__ == "__main__":
    main()
