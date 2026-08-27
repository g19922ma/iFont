#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方式(アニメーション提示方式)ごとの分析 v2 -- WebKit描画不全を除外した全面再解析
================================================================================

■ なぜ v2 が要るのか(2026-08-27 判明)
  WebKit(iOS の全ブラウザ・iOSアプリ内WebView・macOS Safari)では canvas の
  `ctx.filter = "blur(Npx)"` が黙って無視される。例外も警告も出ない。
  そのため **ぼやけ方式の刺激が一切ぼけず、鮮明な字がそのまま提示されていた**。
  実測(本スクリプトが webkit_audit.csv に出す): ぼやけ半径 69.8px(進み具合3%)で
  WebKit端末の正答率は 100%、非WebKit端末では 3.7%。fade/reveal/wipe は端末差なし。

  旧 analyze_families.py には除外処理が一切無い(grep 済み)。したがって
  **ぼやけが絡む数値はすべて汚染されている**。本スクリプトはそれを入れ直したもの。

■ 旧版からの変更(3点)
  1. **WebKit端末を試行単位で除外**(既定)。除外前後の両方を出して差を示す。
     除外は全方式に適用したうえで、fade/reveal/wipe では除外が効かない
     (=端末による差が無い)ことを webkit_audit.csv で示す。
  2. **2バッチ(phase=calib / calib2)を1つの較正実験として扱う**(丸山さんの決定)。
     同じ手続き・同じ8字・同じ4方式・同じ募集で、提示水準の並べ方だけ変えたもの。
     視覚 aprime は 163人 + 162人 = 325人。fade/reveal は前後で同一水準、
     blur/wipe は別の水準はしごなので、2バッチを合わせると**1本の水準軸が広がる**
     (blur 3〜100%、wipe 0.5〜100%)。バッチ一致は phase_consistency.csv で検証する。
  3. **生の正答率のみ**を使う(λ正規化はしない)。**8字すべて**使う。
     多重比較は Holm 法で調整し、raw p と調整後 p の両方を出す。

■ 出力(既定 project/data_calib2_live/analysis_families_v2/)
  A. 汚染の証拠と棚卸し
     webkit_audit_by_level.csv     方式×水準×エンジンの正答率(不具合の直接証拠)
     webkit_audit_family.csv       方式ごとの WebKit / 非WebKit 対比 + Holm
     webkit_vs_android.csv         「描画不具合」と「端末による見え方の違い」の切り分け
     phase_consistency.csv         2バッチの共通水準での一致(前提の検証)
     phase_fits.csv                バッチごとの当てはめ(束ねてよいかの確認)
     contamination_inventory.csv   旧21出力の汚染判定表(根拠つき)
     old_vs_new.csv                主要数値の 旧(汚染) → 新(除外) 対比
  B. 較正曲線と当てはめ
     curves_by_family_level.csv    V_m(s) 生の正答率(方式×水準、除外前後)
     curves_by_char_level.csv      同上を字ごとに
     floor_ceiling.csv             方式ごとの床・天井と偶然水準の比較 + Holm
     floor_pairwise.csv            方式どうしの床の対比較(6対・Holm)
     vs_fit_point_v2.csv           字×方式×速さ×軸×除外有無 の点推定
     vs_bootstrap_v2.csv           参加者単位ブートストラップの95%区間
     family_summary_v2.csv         方式ごとの総括
     usable_span.csv / usable_span_summary.csv  方式ごとの「使える範囲」(u空間での幅)
     resolution_limit.csv          曲線の5〜95%区間で作れる『別々の絵』の枚数
  C. 字の性質
     char_structure.csv            8字の構造指標(データ非依存)
     dakuten_contrast.csv          濁点字(が・ぱ) vs 清音字 + Holm
     decoy_fit_v2.csv              まぎれ字の当てはめ(WebKit除外)
     family_rank_correlation_v2.csv 方式間のμ順位相関
     mechanism_correlates_v2.csv   墨量/清濁とμの相関
     best_family_per_char_v2.csv   字ごとに最も適した方式
  D. 誤りの質
     error_entropy_*_v2.csv        誤答エントロピー各種
     perplexity_by_bin_v2.csv      実質選択肢数
     confusion_similarity.csv      方式間の応答分布の似かた(組み合わせの相補性)
  E. 聴覚(不具合と無関係。値が変わらないことの確認)
     audio_fit_v2.csv / audio_fit_free_gamma_v2.csv
     transcribability_v2.csv       32セルの転写成立判定
  F. 速さ
     speed_effect_family_v2.csv / speed_effect_by_level_v2.csv
  G. 組み合わせ方式
     composite_k_v2.csv            s_x(u)=100·u^k の k の再計算
     composite_projection.csv      組み合わせ曲線の予測(直列モデル/最良モデルの上下限)
     composite_per_char.csv        字ごとの予測
     composite_ranking.csv         4通り+追加候補の順位づけ
     composite_mapping_variants.csv / composite_mapping_summary.csv
                                   進み方の写し方3通り(現行べき乗/同時型/段階型)の比較
     exp2_allocation_power.csv     実験2の条件数 × 人数 と検出できる差

使い方
------
  python3 experiment/tools/analyze_families_v2.py \
      --in  project/data_calib2_live/transfer_trials.csv \
      --out project/data_calib2_live/analysis_families_v2

  (--boot-vs / --boot-speed で反復回数を変えられる。既定は本番設定)

git commit・push はしない。生データ・出力CSVはコミットしない(.gitignore対象)。
"""
import argparse
import io
import math
import os
import sys
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_calib_full as acf   # fit_sigmoid だけを借りる(このファイルは変更しない)

try:
    from scipy.stats import spearmanr, norm
    HAVE_SCIPY_STATS = True
except Exception:
    HAVE_SCIPY_STATS = False

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False
try:
    from scipy.ndimage import binary_erosion
    HAVE_NDIMAGE = True
except Exception:
    HAVE_NDIMAGE = False

TARGET_CHARS = list("あかがぱしつまら")
FAMILIES = ["fade", "reveal", "blur", "wipe"]
SPEEDS = [300, 500]
DIACRITIC = {"あ": "清音", "か": "清音", "が": "濁音", "ぱ": "半濁音",
             "し": "清音", "つ": "清音", "ま": "清音", "ら": "清音"}
# 組み合わせ: 一様側(fade/reveal) × 空間側(blur/wipe)。transfer.js の RENDERERS と同じ4通り。
PAIRS_IMPL = [("fade", "blur"), ("fade", "wipe"), ("reveal", "blur"), ("reveal", "wipe")]
# 未実装だが検討する候補(空間×空間、一様×一様)。
PAIRS_EXTRA = [("blur", "wipe"), ("fade", "reveal")]

Z95 = 1.959963985


# ---------------------------------------------------------------------------
# 統計道具
# ---------------------------------------------------------------------------
def wilson(k, n, z=Z95):
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, c - h), min(1.0, c + h)


def two_prop_z(k1, n1, k2, n2):
    """割合差(1−2)のプールz検定。両側p。"""
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    p1, p2 = k1 / n1, k2 / n2
    pp = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    if se <= 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    if HAVE_SCIPY_STATS:
        p = 2 * (1 - norm.cdf(abs(z)))
    else:
        p = math.erfc(abs(z) / math.sqrt(2))
    return z, p


def binom_exact_greater_p(k, n, p0):
    """H0: p<=p0 に対する片側 p 値(正確二項)。床が偶然水準を超えるかの検定に使う。"""
    if n == 0:
        return float("nan")
    # sum_{i>=k} C(n,i) p0^i (1-p0)^(n-i)
    tot = 0.0
    for i in range(k, n + 1):
        tot += math.comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
        if tot > 1:
            break
    return min(1.0, tot)


def holm(pvals):
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    if m == 0:
        return p
    order = np.argsort(np.where(np.isnan(p), 2.0, p))
    adj = np.empty(m)
    prev = 0.0
    for i, idx in enumerate(order):
        if np.isnan(p[idx]):
            adj[idx] = float("nan")
            continue
        val = (m - i) * p[idx]
        prev = max(prev, val)
        adj[idx] = min(1.0, prev)
    return adj


def cluster_boot_diff(df, key, valA, valB, weight_col=None, nboot=4000, rng=None):
    """参加者単位ブートストラップで「A − B」の正答率差の95%CI。
    weight_col を渡すと、その列の水準ごとに平均してから水準を等重みで束ねる。"""
    rng = rng or np.random.default_rng(20260827)
    df = df[df[key].isin([valA, valB])]
    if len(df) == 0:
        return (float("nan"),) * 4
    cells = pd.Series(["_"] * len(df), index=df.index) if weight_col is None else df[weight_col].astype(str)
    cell_codes, cell_names = pd.factorize(cells)
    nc = len(cell_names)
    out = {}
    for g in (valA, valB):
        sel = (df[key] == g).values
        if sel.sum() == 0:
            return (float("nan"),) * 4
        pcodes, pnames = pd.factorize(df.loc[sel, "participant_id"].values)
        K = np.zeros((len(pnames), nc)); N = np.zeros((len(pnames), nc))
        np.add.at(K, (pcodes, cell_codes[sel]), df.loc[sel, "correct"].values.astype(float))
        np.add.at(N, (pcodes, cell_codes[sel]), 1.0)
        out[g] = (K, N, len(pnames))

    def stat(ia, ib):
        vals = []
        for g, idx in ((valA, ia), (valB, ib)):
            K, N, _ = out[g]
            k = K[idx].sum(axis=0); n = N[idx].sum(axis=0)
            ok = n > 0
            if not ok.any():
                return float("nan")
            vals.append(float(np.mean(k[ok] / n[ok])))
        return vals[0] - vals[1]

    allA = np.arange(out[valA][2]); allB = np.arange(out[valB][2])
    point = stat(allA, allB)
    boots = np.empty(nboot)
    for i in range(nboot):
        boots[i] = stat(rng.integers(0, len(allA), len(allA)), rng.integers(0, len(allB), len(allB)))
    boots = boots[~np.isnan(boots)]
    if len(boots) < 100:
        return point, float("nan"), float("nan"), float("nan")
    lo, hi = np.percentile(boots, [2.5, 97.5])
    pv = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    return point, lo, hi, max(pv, 1.0 / len(boots))


def shannon_bits(counter):
    n = sum(counter.values())
    if n == 0:
        return float("nan")
    h = 0.0
    for c in counter.values():
        if c > 0:
            p = c / n
            h -= p * math.log2(p)
    return h


def js_divergence(c1, c2, support):
    """2つの応答分布の Jensen-Shannon ダイバージェンス(bit)。0=同じ、1=完全に別。"""
    n1 = sum(c1.get(s, 0) for s in support); n2 = sum(c2.get(s, 0) for s in support)
    if n1 == 0 or n2 == 0:
        return float("nan")
    p = np.array([c1.get(s, 0) / n1 for s in support])
    q = np.array([c2.get(s, 0) / n2 for s in support])
    m = 0.5 * (p + q)
    def kl(a, b):
        mask = a > 0
        return float(np.sum(a[mask] * np.log2(a[mask] / b[mask])))
    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


# ---------------------------------------------------------------------------
# 0. 読み込み
# ---------------------------------------------------------------------------
def load(path):
    print(f"読み込み: {path}")
    d = pd.read_csv(path, low_memory=False)
    print(f"  全{len(d)}行")
    for c in ["correct", "is_decoy", "is_filler", "is_catch", "is_test", "touch",
              "resp_in_target_set", "resp_in_frequent_set", "endpoint_clamped"]:
        if c in d.columns and d[c].dtype == object:
            d[c] = d[c].map({True: True, False: False, "TRUE": True, "FALSE": False,
                             "True": True, "False": False})
    ua = d["ua"].fillna("").astype(str)
    # WebKit エンジン判定(analyze_calib2.py と同一)。
    #   iOS は全ブラウザが WebKit(Chrome iOS/Firefox iOS も含む)。
    #   macOS は Safari(Chrome/Edge/Firefox を含まない UA)だけが WebKit。
    # **試行単位**で持つ。較正中に端末を替えた参加者が2名いるため(apvegd/zn5fsy)、
    # 参加者単位で丸めると、その人の非WebKit試行まで落とすか、WebKit試行を残すかになる。
    d["webkit"] = (
        ua.str.contains("iPhone|iPad|iPod", regex=True)
        | (ua.str.contains("Macintosh") & ua.str.contains("Safari")
           & ~ua.str.contains("Chrome|Chromium|Edg/|Firefox", regex=True))
    )
    d["engine"] = np.where(
        d["webkit"], "WebKit",
        np.where(ua.str.contains("Firefox"), "Firefox",
                 np.where(ua.str.contains("Edg/"), "Edge",
                          np.where(ua.str.contains("Android"), "Chrome(Android)", "Chrome(Desktop)"))))
    n_test = int((d["is_test"] == True).sum())
    d = d[d["is_test"] != True].copy()
    print(f"  is_test={n_test}行 を除外 / 残り{len(d)}行")
    d["correct_i"] = d["correct"].astype(bool).astype(int)
    d["actual_s_pct"] = (pd.to_numeric(d["actual_s"], errors="coerce") * 100).round(4)
    d["base_anim_ms_i"] = pd.to_numeric(d["base_anim_ms"], errors="coerce")
    return d


def slices(d):
    v = d[d["modality"] == "transfer_visual"].copy()
    v["correct"] = v["correct_i"]
    a = d[d["modality"] == "transfer_audio"].copy()
    a["correct"] = a["correct_i"]
    main = v[(v["is_decoy"] != True) & (v["is_filler"] != True) & (v["check_kind"].isna())
             & (v["target_char"].isin(TARGET_CHARS))].copy()
    decoy = v[(v["is_decoy"] == True) & (v["check_kind"].isna())].copy()
    fullcheck = v[(v["check_kind"] == "full") & (v["is_decoy"] != True)
                  & (v["target_char"].isin(TARGET_CHARS))].copy()
    floorcheck = v[(v["check_kind"] == "floor") & (v["is_decoy"] != True)].copy()
    # 聴覚: 較正はしご(gate_ms あり) と 埋め込み「打ち切りなし」(gate_ms 無し・stimulus_id 末尾 full)
    a_main = a[(a["is_decoy"] != True) & (a["check_kind"].isna())
               & (a["target_char"].isin(TARGET_CHARS))].copy()
    tail = a_main["stimulus_id"].fillna("").astype(str).str.split("|").str[-1]
    a_main["is_embedded_full"] = (tail == "full") & a_main["gate_ms"].isna()
    a_ladder = a_main[~a_main["is_embedded_full"]].copy()
    a_full = a_main[a_main["is_embedded_full"]].copy()
    a_check_full = a[(a["check_kind"] == "full") & (a["target_char"].isin(TARGET_CHARS))].copy()
    print(f"  視覚 本命8字本命問題: {len(main)}行 / 参加者{main['participant_id'].nunique()}人 "
          f"(calib {main[main.phase=='calib']['participant_id'].nunique()}人 + "
          f"calib2 {main[main.phase=='calib2']['participant_id'].nunique()}人)")
    print(f"  視覚 まぎれ字: {len(decoy)}行 / {decoy['target_char'].nunique()}字")
    print(f"  視覚 確認問題A(full): {len(fullcheck)}行 / 確認問題C(floor): {len(floorcheck)}行")
    print(f"  聴覚 はしご: {len(a_ladder)}行 / 参加者{a_ladder['participant_id'].nunique()}人 "
          f"/ 埋め込みfull {len(a_full)}行 / 確認問題full {len(a_check_full)}行")
    return dict(visual=v, audio=a, main=main, decoy=decoy, fullcheck=fullcheck,
                floorcheck=floorcheck, a_ladder=a_ladder, a_full=a_full, a_check_full=a_check_full)


def gammas(d):
    gv = 1.0 / float(d[d["modality"] == "transfer_visual"]["n_choices"].mode().iloc[0])
    ga = 1.0 / float(d[d["modality"] == "transfer_audio"]["n_choices"].mode().iloc[0])
    print(f"  gamma(下限・固定): 視覚=1/{round(1/gv)}={gv:.5f} 聴覚=1/{round(1/ga)}={ga:.5f}")
    return gv, ga


def fit_rows(sub, level_key, gamma, n_starts=8):
    if len(sub) == 0:
        return dict(lam=float("nan"), mu=float("nan"), sigma=float("nan"), converged=False,
                    note="データなし", nll=float("nan"), n_trials=0, n_levels=0)
    t = sub.groupby(level_key)["correct"].agg(["sum", "count"])
    return acf.fit_sigmoid(t.index.values.astype(float), t["sum"].values.astype(float),
                           t["count"].values.astype(float), gamma, n_starts=n_starts)


def sig(x, gamma, lam, mu, sigma):
    z = np.clip(-(np.asarray(x, dtype=float) - mu) / max(sigma, 1e-9), -500, 500)
    return gamma + (lam - gamma) / (1.0 + np.exp(z))


# ---------------------------------------------------------------------------
# A. 汚染の証拠
# ---------------------------------------------------------------------------
def a_webkit_audit(S, out):
    m = S["main"]
    rows = []
    for fam in FAMILIES:
        s = m[m["family"] == fam]
        for lv, g in s.groupby("progress_pct"):
            for eng, gg in g.groupby("engine"):
                p, lo, hi = wilson(gg["correct"].sum(), len(gg))
                rows.append(dict(family=fam, progress_pct=lv, engine=eng, webkit=(eng == "WebKit"),
                                 n=len(gg), n_participants=gg["participant_id"].nunique(),
                                 acc=p, lo95=lo, hi95=hi))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "webkit_audit_by_level.csv"), index=False)

    # 方式ごとに「低水準(<100%)での WebKit vs 非WebKit」。Holm は4方式に対して。
    rows2, ps = [], []
    for fam in FAMILIES:
        s = m[(m["family"] == fam) & (m["progress_pct"] < 100)]
        w = s[s["webkit"]]; nw = s[~s["webkit"]]
        pw, lw, hw = wilson(w["correct"].sum(), len(w))
        pn, ln, hn = wilson(nw["correct"].sum(), len(nw))
        z, p = two_prop_z(w["correct"].sum(), len(w), nw["correct"].sum(), len(nw))
        ps.append(p)
        rows2.append(dict(family=fam, n_webkit=len(w), acc_webkit=pw, lo_webkit=lw, hi_webkit=hw,
                          n_other=len(nw), acc_other=pn, lo_other=ln, hi_other=hn,
                          diff_pt=(pw - pn) * 100, z=z, p_raw=p))
    adj = holm(ps)
    for r, a in zip(rows2, adj):
        r["p_holm"] = a
    df2 = pd.DataFrame(rows2)
    df2.to_csv(os.path.join(out, "webkit_audit_family.csv"), index=False)
    print("\n[A] WebKit 描画不全の証拠(本命8字・低水準<100%)")
    print(df2[["family", "n_webkit", "acc_webkit", "n_other", "acc_other", "diff_pt", "p_raw", "p_holm"]]
          .round(4).to_string(index=False))
    return df, df2


def a_phase_consistency(S, out, nboot, rng):
    """2バッチを1実験として扱えるかの検証。共通水準だけを等重みで比較する。"""
    m = S["main"]
    rows, ps = [], []
    for fam in FAMILIES:
        for excl in (True, False):
            s = m[m["family"] == fam]
            if excl:
                s = s[~s["webkit"]]
            common = sorted(set(s[s.phase == "calib"]["progress_pct"]) &
                            set(s[s.phase == "calib2"]["progress_pct"]))
            s = s[s["progress_pct"].isin(common)]
            d_, lo, hi, pv = cluster_boot_diff(s, "phase", "calib2", "calib",
                                               weight_col="progress_pct", nboot=nboot, rng=rng)
            a1 = s[s.phase == "calib"]; a2 = s[s.phase == "calib2"]
            rows.append(dict(family=fam, webkit_excluded=excl, n_common_levels=len(common),
                             common_levels=";".join(str(x) for x in common),
                             n_calib=len(a1), n_calib2=len(a2),
                             diff_pt_calib2_minus_calib=d_ * 100, lo_pt=lo * 100, hi_pt=hi * 100,
                             p_boot=pv))
            if excl:
                ps.append(pv)
    adj = holm(ps)
    i = 0
    for r in rows:
        if r["webkit_excluded"]:
            r["p_holm_over_4families"] = adj[i]; i += 1
        else:
            r["p_holm_over_4families"] = float("nan")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "phase_consistency.csv"), index=False)
    print("\n[A] 2バッチの一致(共通水準・等重み、WebKit除外)")
    _ = None
    print(df[df.webkit_excluded][["family", "n_common_levels", "diff_pt_calib2_minus_calib",
                                  "lo_pt", "hi_pt", "p_boot", "p_holm_over_4families"]]
          .round(4).to_string(index=False))
    return df


def a_webkit_vs_android(S, out):
    """「描画の不具合」と「端末による見え方の違い」を切り分ける。

    WebKit端末はすべてスマートフォン/タブレットである。もし WebKit と他の端末の差が
    『小さい画面・高精細で見えやすい』という端末効果なら、**同じスマートフォンである
    Chrome(Android) にも同じ向きの差が出るはず**である。出ないなら、その方式でだけ
    起きている描画の不具合である。Holm は4方式に対して。"""
    m = S["main"]
    m = m[m["progress_pct"] < 100]
    rows, ps = [], []
    for fam in FAMILIES:
        s = m[m.family == fam]
        w = s[s.engine == "WebKit"]
        an = s[s.engine == "Chrome(Android)"]
        de = s[s.engine == "Chrome(Desktop)"]
        z1, p1 = two_prop_z(w["correct"].sum(), len(w), an["correct"].sum(), len(an))
        z2, p2 = two_prop_z(an["correct"].sum(), len(an), de["correct"].sum(), len(de))
        ps.append(p1)
        rows.append(dict(family=fam,
                         n_webkit=len(w), acc_webkit=float(w["correct"].mean()),
                         n_android=len(an), acc_android=float(an["correct"].mean()),
                         n_desktop=len(de), acc_desktop=float(de["correct"].mean()),
                         webkit_minus_android_pt=(w["correct"].mean() - an["correct"].mean()) * 100,
                         android_minus_desktop_pt=(an["correct"].mean() - de["correct"].mean()) * 100,
                         p_raw_webkit_vs_android=p1, p_raw_android_vs_desktop=p2))
    for r, adj in zip(rows, holm(ps)):
        r["p_holm_webkit_vs_android"] = adj
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "webkit_vs_android.csv"), index=False)
    print("\n[A] 描画不具合 vs 端末効果の切り分け(低水準<100%)")
    print(df[["family", "acc_webkit", "acc_android", "acc_desktop", "webkit_minus_android_pt",
              "android_minus_desktop_pt", "p_holm_webkit_vs_android"]].round(4).to_string(index=False))
    return df


def a_phase_fits(S, out, gv, n_starts):
    """バッチごとに当てはめて、2つを1本にまとめてよいかを確かめる。
    fade/reveal は同一水準なので直接比較できる。blur/wipe は水準はしごが違うので
    「同じ曲線の別の部分を測っている」ことになり、当てはめの一致で見るしかない。"""
    m = S["main"][~S["main"]["webkit"]]
    rows = []
    for fam in FAMILIES:
        for ph in ("calib", "calib2", "both"):
            s = m[m.family == fam] if ph == "both" else m[(m.family == fam) & (m.phase == ph)]
            f = fit_rows(s, "actual_s_pct", gv, n_starts)
            rows.append(dict(family=fam, phase=ph, lam=f["lam"], mu=f["mu"], sigma=f["sigma"],
                             converged=f["converged"], n_trials=f["n_trials"], n_levels=f["n_levels"],
                             level_min=float(s["progress_pct"].min()) if len(s) else float("nan"),
                             level_max=float(s["progress_pct"].max()) if len(s) else float("nan"),
                             note=f["note"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "phase_fits.csv"), index=False)
    print("\n[A] バッチごとの当てはめ(8字プール・WebKit除外)")
    print(df[["family", "phase", "lam", "mu", "sigma", "n_trials", "n_levels",
              "level_min", "level_max"]].round(3).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# B. 較正曲線
# ---------------------------------------------------------------------------
def b_curves(S, out):
    m = S["main"]
    rows = []
    for fam in FAMILIES:
        for excl in (True, False):
            s = m[m["family"] == fam]
            s = s[~s["webkit"]] if excl else s
            for lv, g in s.groupby("progress_pct"):
                p, lo, hi = wilson(g["correct"].sum(), len(g))
                rows.append(dict(family=fam, webkit_excluded=excl, progress_pct=lv,
                                 phase_source=";".join(sorted(g["phase"].unique())),
                                 actual_s_pct_median=float(g["actual_s_pct"].median()),
                                 n=len(g), k=int(g["correct"].sum()),
                                 n_participants=g["participant_id"].nunique(),
                                 acc=p, lo95=lo, hi95=hi))
    df = pd.DataFrame(rows).sort_values(["family", "webkit_excluded", "progress_pct"])
    df.to_csv(os.path.join(out, "curves_by_family_level.csv"), index=False)

    rows = []
    for fam in FAMILIES:
        s = m[(m["family"] == fam) & (~m["webkit"])]
        for (ch, lv), g in s.groupby(["target_char", "progress_pct"]):
            p, lo, hi = wilson(g["correct"].sum(), len(g))
            rows.append(dict(char=ch, diacritic=DIACRITIC[ch], family=fam, progress_pct=lv,
                             n=len(g), k=int(g["correct"].sum()), acc=p, lo95=lo, hi95=hi))
    pd.DataFrame(rows).to_csv(os.path.join(out, "curves_by_char_level.csv"), index=False)
    print(f"  書き出し: curves_by_family_level.csv / curves_by_char_level.csv")
    return df


def b_floor_ceiling(S, out, gv):
    """方式ごとの床(いちばん情報の少ない水準)と天井(100%)。
    床が偶然水準(1/72)を上回るかを正確二項で検定し、Holm(4方式)で補正。"""
    m = S["main"]
    fl = S["floorcheck"]
    rows, ps = [], []
    for fam in FAMILIES:
        for excl in (True, False):
            s = m[m["family"] == fam]
            s = s[~s["webkit"]] if excl else s
            lv_min = s["progress_pct"].min()
            g = s[s["progress_pct"] == lv_min]
            p, lo, hi = wilson(g["correct"].sum(), len(g))
            # 確認問題C(floor)の同水準ぶんを足した版
            fg = fl[(fl["family"] == fam)]
            fg = fg[~fg["webkit"]] if excl else fg
            fg = fg[fg["progress_pct"] == lv_min]
            kk = int(g["correct"].sum() + fg["correct"].sum()); nn = len(g) + len(fg)
            p2, lo2, hi2 = wilson(kk, nn)
            pv = binom_exact_greater_p(kk, nn, gv)
            c = s[s["progress_pct"] == 100]
            pc, loc, hic = wilson(c["correct"].sum(), len(c))
            rows.append(dict(family=fam, webkit_excluded=excl, floor_level_pct=lv_min,
                             n_main=len(g), acc_main=p, lo95_main=lo, hi95_main=hi,
                             n_plus_check=nn, acc_plus_check=p2, lo95_plus_check=lo2,
                             hi95_plus_check=hi2, chance=gv,
                             p_one_sided_gt_chance=pv,
                             n_ceiling=len(c), acc_ceiling=pc, lo95_ceiling=loc, hi95_ceiling=hic))
            if excl:
                ps.append(pv)
    adj = holm(ps)
    i = 0
    for r in rows:
        if r["webkit_excluded"]:
            r["p_holm_over_4families"] = adj[i]; i += 1
        else:
            r["p_holm_over_4families"] = float("nan")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "floor_ceiling.csv"), index=False)
    print("\n[B] 方式ごとの床と天井(WebKit除外・確認問題C込み)")
    print(df[df.webkit_excluded][["family", "floor_level_pct", "n_plus_check", "acc_plus_check",
                                  "lo95_plus_check", "hi95_plus_check", "p_one_sided_gt_chance",
                                  "p_holm_over_4families", "acc_ceiling"]].round(4).to_string(index=False))

    # 方式どうしの床の比較(6対、Holm)。「blur の床だけ高い」が覆ったことの直接検定。
    rows2, ps2 = [], []
    base = {}
    for fam in FAMILIES:
        s = m[(m["family"] == fam) & (~m["webkit"])]
        lv = s["progress_pct"].min()
        g = s[s["progress_pct"] == lv]
        fg = fl[(fl["family"] == fam) & (~fl["webkit"]) & (fl["progress_pct"] == lv)]
        base[fam] = (int(g["correct"].sum() + fg["correct"].sum()), len(g) + len(fg))
    for i1 in range(len(FAMILIES)):
        for i2 in range(i1 + 1, len(FAMILIES)):
            f1, f2 = FAMILIES[i1], FAMILIES[i2]
            k1, n1 = base[f1]; k2, n2 = base[f2]
            z, p = two_prop_z(k1, n1, k2, n2)
            ps2.append(p)
            rows2.append(dict(family_1=f1, family_2=f2, n1=n1, acc1=k1 / n1, n2=n2, acc2=k2 / n2,
                              diff_pt=(k1 / n1 - k2 / n2) * 100, z=z, p_raw=p))
    for r, a in zip(rows2, holm(ps2)):
        r["p_holm_over_6pairs"] = a
    pd.DataFrame(rows2).to_csv(os.path.join(out, "floor_pairwise.csv"), index=False)
    print("\n[B] 床どうしの対比較(6対・Holm)")
    print(pd.DataFrame(rows2).round(4).to_string(index=False))
    return df


def b_fits(S, out, gv, n_starts):
    m = S["main"]
    fc = S["fullcheck"]
    rows = []
    for excl in (True, False):
        base = m[~m["webkit"]] if excl else m
        fcb = fc[~fc["webkit"]] if excl else fc
        for version in ("excl_clamp0", "incl_clamp0"):
            src = pd.concat([base, fcb]) if version == "incl_clamp0" else base
            for axis, key in (("actual", "actual_s_pct"), ("nominal", "progress_pct")):
                for ch in TARGET_CHARS:
                    for fam in FAMILIES:
                        for sp in [None] + SPEEDS:
                            sub = src[(src["target_char"] == ch) & (src["family"] == fam)]
                            if sp is not None:
                                sub = sub[sub["base_anim_ms_i"] == sp]
                            f = fit_rows(sub, key, gv, n_starts)
                            rows.append(dict(webkit_excluded=excl, version=version, axis=axis,
                                             char=ch, diacritic=DIACRITIC[ch], family=fam,
                                             speed=("pooled" if sp is None else sp), gamma=gv,
                                             lam=f["lam"], mu=f["mu"], sigma=f["sigma"],
                                             converged=f["converged"], n_trials=f["n_trials"],
                                             n_levels=f["n_levels"],
                                             n_participants=sub["participant_id"].nunique(),
                                             note=f["note"]))
        # 方式ごと(8字プール)の当てはめも出す
        for axis, key in (("actual", "actual_s_pct"), ("nominal", "progress_pct")):
            for fam in FAMILIES:
                sub = base[base["family"] == fam]
                f = fit_rows(sub, key, gv, n_starts)
                rows.append(dict(webkit_excluded=excl, version="excl_clamp0", axis=axis,
                                 char="(8字プール)", diacritic="", family=fam, speed="pooled",
                                 gamma=gv, lam=f["lam"], mu=f["mu"], sigma=f["sigma"],
                                 converged=f["converged"], n_trials=f["n_trials"],
                                 n_levels=f["n_levels"],
                                 n_participants=sub["participant_id"].nunique(), note=f["note"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "vs_fit_point_v2.csv"), index=False)
    print(f"  書き出し: vs_fit_point_v2.csv ({len(df)}行)")
    main_fit = df[(df.webkit_excluded) & (df.version == "excl_clamp0") & (df.axis == "actual")
                  & (df.speed == "pooled")]
    print("\n[B] 主版の当てはめ(WebKit除外・実測軸・速さpooled)")
    print(main_fit[main_fit.char == "(8字プール)"][["family", "lam", "mu", "sigma", "n_trials"]]
          .round(4).to_string(index=False))
    return df


def b_bootstrap(S, out, gv, nboot, seed, n_starts):
    """参加者単位ブートストラップ。主版(WebKit除外・実測軸・speed pooled)。"""
    m = S["main"]
    m = m[~m["webkit"]]
    pids = sorted(m["participant_id"].unique())
    by = {p: g for p, g in m.groupby("participant_id")}
    rng = np.random.default_rng(seed)
    acc = defaultdict(lambda: {"mu": [], "lam": [], "sigma": [], "conv": []})
    for b in range(nboot):
        draw = rng.choice(pids, size=len(pids), replace=True)
        rb = pd.concat([by[p] for p in draw])
        for ch in TARGET_CHARS:
            for fam in FAMILIES:
                sub = rb[(rb["target_char"] == ch) & (rb["family"] == fam)]
                f = fit_rows(sub, "actual_s_pct", gv, n_starts)
                a = acc[(ch, fam)]
                a["mu"].append(f["mu"]); a["lam"].append(f["lam"])
                a["sigma"].append(f["sigma"]); a["conv"].append(f["converged"])
        for fam in FAMILIES:
            sub = rb[rb["family"] == fam]
            f = fit_rows(sub, "actual_s_pct", gv, n_starts)
            a = acc[("(8字プール)", fam)]
            a["mu"].append(f["mu"]); a["lam"].append(f["lam"])
            a["sigma"].append(f["sigma"]); a["conv"].append(f["converged"])
        if (b + 1) % max(1, nboot // 10) == 0:
            print(f"  ブートストラップ {b+1}/{nboot}")
    rows = []
    for (ch, fam), a in acc.items():
        def q(arr):
            x = np.asarray(arr, dtype=float)
            if not np.any(~np.isnan(x)):
                return (float("nan"),) * 3
            return tuple(np.nanpercentile(x, [50, 2.5, 97.5]))
        mu_m, mu_lo, mu_hi = q(a["mu"]); lam_m, lam_lo, lam_hi = q(a["lam"])
        s_m, s_lo, s_hi = q(a["sigma"])
        rows.append(dict(char=ch, family=fam, n_boot=nboot, converged_rate=float(np.mean(a["conv"])),
                         mu_median=mu_m, mu_lo95=mu_lo, mu_hi95=mu_hi,
                         lambda_median=lam_m, lambda_lo95=lam_lo, lambda_hi95=lam_hi,
                         sigma_median=s_m, sigma_lo95=s_lo, sigma_hi95=s_hi))
    df = pd.DataFrame(rows)
    order = {c: i for i, c in enumerate(TARGET_CHARS + ["(8字プール)"])}
    df = df.sort_values(["char", "family"], key=lambda s: s.map(order) if s.name == "char" else s)
    df.to_csv(os.path.join(out, "vs_bootstrap_v2.csv"), index=False)
    print(f"  書き出し: vs_bootstrap_v2.csv (参加者{len(pids)}人・{nboot}回)")
    print("\n[B] 方式ごと(8字プール)のμ 95%区間")
    print(df[df.char == "(8字プール)"][["family", "mu_median", "mu_lo95", "mu_hi95",
                                        "sigma_median", "sigma_lo95", "sigma_hi95",
                                        "lambda_median"]].round(3).to_string(index=False))
    return df, len(pids)


def b_usable_span(fit_df, out, gv, levels_min):
    """方式ごとの「使える範囲」。
    (a) s空間: 曲線が q=5% から q=95% まで動く s の区間(q=(p−γ)/(λ−γ))。
    (b) u空間: 組み合わせで使う写し s=100·u^k を通したときの区間の幅。
        u = (s/100)^(1/k)。ここでの k は方式ごとの固定 k(下の composite_k_v2 と同じ)。
    進み具合の軸をどれだけ広く使えるか = 転写で刻める分解能に直結する。"""
    L = math.log(19.0)
    rows = []
    for excl in (True, False):
        ff = fit_df[(fit_df.webkit_excluded == excl) & (fit_df.version == "excl_clamp0")
                    & (fit_df.axis == "actual") & (fit_df.speed == "pooled")]
        for fam in FAMILIES:
            mubar = float(ff[(ff.family == fam) & (ff.char.isin(TARGET_CHARS))]["mu"].mean())
            k = math.log(max(0.01, min(99.99, mubar)) / 100.0) / math.log(0.5)
            lv_min = float(levels_min[fam])
            # **字ごと**に計算する。8字を束ねた当てはめは、字によってμが大きく違う方式
            # (wipe: ま3.8% 〜 ぱ79.9%)では実在しない混合曲線になってしまうため。
            for ch in list(TARGET_CHARS) + ["(8字プール)"]:
                r = ff[(ff.family == fam) & (ff.char == ch)].iloc[0]
                mu, sg = float(r["mu"]), float(r["sigma"])
                s_lo, s_hi = mu - L * sg, mu + L * sg
                s_lo_c = min(max(s_lo, lv_min), 100.0)
                s_hi_c = min(max(s_hi, lv_min), 100.0)
                rows.append(dict(family=fam, char=ch, webkit_excluded=excl, mu=mu, sigma=sg,
                                 level_min_tested_pct=lv_min, s5_pct=s_lo, s95_pct=s_hi,
                                 s5_clipped_pct=s_lo_c, s95_clipped_pct=s_hi_c,
                                 s_span_pct=s_hi_c - s_lo_c,
                                 s_span_log10=(math.log10(s_hi_c) - math.log10(s_lo_c)),
                                 clipped_low=(s_lo < lv_min), clipped_high=(s_hi > 100.0),
                                 mu_bar_8chars=mubar, k=k,
                                 u5=(s_lo_c / 100.0) ** (1.0 / k), u95=(s_hi_c / 100.0) ** (1.0 / k),
                                 u_span=(s_hi_c / 100.0) ** (1.0 / k) - (s_lo_c / 100.0) ** (1.0 / k)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "usable_span.csv"), index=False)
    g = df[(df.webkit_excluded) & (df.char.isin(TARGET_CHARS))]
    agg = g.groupby("family").agg(
        mu_median=("mu", "median"), mu_min=("mu", "min"), mu_max=("mu", "max"),
        sigma_median=("sigma", "median"),
        u_span_median=("u_span", "median"), u_span_min=("u_span", "min"), u_span_max=("u_span", "max"),
        u5_median=("u5", "median"), u95_median=("u95", "median"),
        n_clipped_low=("clipped_low", "sum"), n_clipped_high=("clipped_high", "sum"),
        k=("k", "first")).reindex(FAMILIES)
    agg.to_csv(os.path.join(out, "usable_span_summary.csv"))
    print("\n[B] 方式ごとの使える範囲(字ごとに計算して要約、WebKit除外)")
    print(agg.round(4).to_string())
    return df


def b_family_summary(S, fit_df, boot_df, out, gv):
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")
               & (fit_df.char.isin(TARGET_CHARS))]
    f0 = fit_df[(~fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
                & (fit_df.axis == "actual") & (fit_df.speed == "pooled")
                & (fit_df.char.isin(TARGET_CHARS))]
    m = S["main"][~S["main"]["webkit"]]
    rows = []
    for fam in FAMILIES:
        g = f[f.family == fam]; g0 = f0[f0.family == fam]
        sei = g[g.diacritic == "清音"]["mu"]; dak = g[g.diacritic != "清音"]["mu"]
        # 当てはめの良さ: 水準ごとの実測と予測の重み付き平均絶対誤差
        errs, ws = [], []
        for ch in TARGET_CHARS:
            r = g[g.char == ch].iloc[0]
            sub = m[(m.family == fam) & (m.target_char == ch)]
            t = sub.groupby("actual_s_pct")["correct"].agg(["sum", "count"])
            pred = sig(t.index.values, gv, r["lam"], r["mu"], r["sigma"])
            errs.append(np.sum(np.abs(t["sum"].values / t["count"].values - pred) * t["count"].values))
            ws.append(t["count"].sum())
        rows.append(dict(
            family=fam, n_char_converged=int(g["converged"].sum()),
            sigma_median=float(g["sigma"].median()), sigma_iqr=float(g["sigma"].quantile(.75) - g["sigma"].quantile(.25)),
            lambda_min=float(g["lam"].min()), lambda_median=float(g["lam"].median()), lambda_max=float(g["lam"].max()),
            mu_min=float(g["mu"].min()), mu_max=float(g["mu"].max()), mu_mean=float(g["mu"].mean()),
            mu_seion_median=float(sei.median()), mu_diacritic_median=float(dak.median()),
            mu_diacritic_minus_seion=float(dak.median() - sei.median()),
            fit_error_weighted_mae=float(np.sum(errs) / np.sum(ws)),
            mu_mean_webkit_included=float(g0["mu"].mean()),
            mu_mean_shift_from_exclusion=float(g["mu"].mean() - g0["mu"].mean()),
            sigma_median_webkit_included=float(g0["sigma"].median())))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "family_summary_v2.csv"), index=False)
    print("\n[B] 方式ごとの総括")
    print(df.round(3).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# C. 字の性質
# ---------------------------------------------------------------------------
def char_structure(base_dir, out, erosion_iter=1):
    rows = []
    for ch in TARGET_CHARS:
        cx = rf = fd = float("nan")
        if HAVE_PIL:
            path = None
            for ext in (".png", ".PNG"):
                p = os.path.join(base_dir, ch + ext)
                if os.path.exists(p):
                    path = p; break
            if path:
                im = Image.open(path).convert("RGBA")
                a = np.asarray(im)
                ink = (a[..., 3] > 8) & (a[..., :3].mean(axis=2) < 200) if a.shape[-1] == 4 else None
                if ink is None or ink.sum() == 0:
                    g = np.asarray(im.convert("L"), dtype=float)
                    ink = g < 128
                tot = ink.sum()
                if tot > 0:
                    ys, xs = np.nonzero(ink)
                    cx = float(xs.mean() / ink.shape[1])
                    rf = float((xs >= ink.shape[1] / 2).sum() / tot)
                    if HAVE_NDIMAGE:
                        er = binary_erosion(ink, iterations=erosion_iter)
                        fd = float((tot - er.sum()) / tot)
        rows.append(dict(char=ch, diacritic=DIACRITIC[ch], centroid_x_frac=cx,
                         right_ink_frac=rf, fine_detail_frac=fd))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "char_structure.csv"), index=False)
    return df


def b_resolution_limit(span_df, out, base_dir, fade_gamma=1.0, blur_max_px=72.0):
    """方式ごとの「刻める段数」。曲線の 5%〜95% の区間の中に、
    その方式が物理的に作れる**別々の絵**が何枚あるか。
    段数が少ない方式は、進み具合を細かく指定しても同じ絵しか出せない
    =転写の分解能がそこで頭打ちになる。**この論点は描画不具合と無関係**で、
    fade についての旧レポートの指摘(256階調)はそのまま生きている。
      fade   … 不透明度 round(255·s^gamma) の段数
      reveal … 表示する墨画素の数 round(ink·s) の段数
      blur   … ぼかし半径 blur_max_px·(1−s) の px 段数(小数半径も渡せるので下限の目安)
      wipe   … 見せる列の数 round(bbox幅·s) の段数
    """
    ink, bboxw = {}, {}
    if HAVE_PIL:
        for ch in TARGET_CHARS:
            p = os.path.join(base_dir, ch + ".png")
            if not os.path.exists(p):
                continue
            im = Image.open(p).convert("L")
            a = np.asarray(im, dtype=float)
            m = a < 128
            ink[ch] = int(m.sum())
            xs = np.nonzero(m.any(axis=0))[0]
            bboxw[ch] = int(xs.max() - xs.min() + 1) if len(xs) else 0
    sp = span_df[(span_df.webkit_excluded) & (span_df.char.isin(TARGET_CHARS))]
    rows = []
    for _, r in sp.iterrows():
        fam, ch = r["family"], r["char"]
        s5, s95 = r["s5_clipped_pct"] / 100.0, r["s95_clipped_pct"] / 100.0
        if fam == "fade":
            n = abs(round(255 * s95 ** fade_gamma) - round(255 * s5 ** fade_gamma))
            unit = "不透明度の階調(全256)"
        elif fam == "reveal":
            n = abs(round(ink.get(ch, 0) * s95) - round(ink.get(ch, 0) * s5))
            unit = f"表示する墨画素の数(全{ink.get(ch, 0)})"
        elif fam == "blur":
            n = abs(round(blur_max_px * (1 - s5)) - round(blur_max_px * (1 - s95)))
            unit = f"ぼかし半径px(全{blur_max_px:g})"
        else:
            n = abs(round(bboxw.get(ch, 0) * s95) - round(bboxw.get(ch, 0) * s5))
            unit = f"見せる列数(全{bboxw.get(ch, 0)})"
        rows.append(dict(family=fam, char=ch, s5_pct=r["s5_clipped_pct"], s95_pct=r["s95_clipped_pct"],
                         n_distinct_steps=int(n), unit=unit))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "resolution_limit.csv"), index=False)
    agg = df.groupby("family")["n_distinct_steps"].agg(["median", "min", "max"]).reindex(FAMILIES)
    print("\n[B] 曲線の5〜95%区間の中で作れる『別々の絵』の枚数(描画不具合と無関係)")
    print(agg.to_string())
    return df


def c_dakuten(S, fit_df, out, nboot, rng):
    """濁点字(が・ぱ) vs 清音字(6字)。
    (1) 当てはめμの差、(2) 生の正答率の差(水準等重み・参加者ブートストラップ)。
    Holm は 4方式に対して。"""
    m = S["main"][~S["main"]["webkit"]].copy()
    m["dak"] = np.where(m["target_char"].isin(["が", "ぱ"]), "dakuten", "seion")
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")
               & (fit_df.char.isin(TARGET_CHARS))]
    rows, ps = [], []
    for fam in FAMILIES:
        s = m[m.family == fam]
        d_, lo, hi, pv = cluster_boot_diff(s, "dak", "dakuten", "seion",
                                           weight_col="progress_pct", nboot=nboot, rng=rng)
        g = f[f.family == fam]
        mu_s = g[g.diacritic == "清音"]["mu"].median(); mu_d = g[g.diacritic != "清音"]["mu"].median()
        ps.append(pv)
        rows.append(dict(family=fam, mu_seion_median=mu_s, mu_dakuten_median=mu_d,
                         mu_diff_pt=mu_d - mu_s, mu_ratio=(mu_d / mu_s if mu_s else float("nan")),
                         acc_diff_pt_dakuten_minus_seion=d_ * 100, lo_pt=lo * 100, hi_pt=hi * 100,
                         p_boot=pv, n_dakuten=int((s["dak"] == "dakuten").sum()),
                         n_seion=int((s["dak"] == "seion").sum())))
    for r, a in zip(rows, holm(ps)):
        r["p_holm_over_4families"] = a
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "dakuten_contrast.csv"), index=False)
    print("\n[C] 濁点字(が・ぱ) vs 清音字6字(WebKit除外)")
    print(df.round(4).to_string(index=False))
    return df


def c_decoy(S, out, gv, n_starts, min_trials=8):
    """まぎれ字の字×方式の当てはめ(WebKit除外)。旧版の参照データ
    (analyze_calib_deep.py の fit_decoy_visual.csv、バッチ1のみ・WebKit込み)を置き換える。"""
    dec = S["decoy"]
    rows = []
    # dataset を分けるのは、旧版との差が「WebKit除外」由来か「試行数が倍になったことによる
    # 測定誤差の減少(順位相関の希薄化が弱まる)」由来かを切り分けるため。
    for dataset, base in (("both_batches", dec), ("calib_only", dec[dec.phase == "calib"])):
        for excl in (True, False):
            s = base[~base["webkit"]] if excl else base
            for (ch, fam), g in s.groupby(["target_char", "family"]):
                if len(g) < min_trials:
                    continue
                f = fit_rows(g, "actual_s_pct", gv, n_starts)
                rows.append(dict(dataset=dataset, webkit_excluded=excl, char=ch, family=fam, gamma=gv,
                                 lam=f["lam"], mu=f["mu"], sigma=f["sigma"], converged=f["converged"],
                                 n_trials=f["n_trials"], n_levels=f["n_levels"], note=f["note"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "decoy_fit_v2.csv"), index=False)
    print(f"  書き出し: decoy_fit_v2.csv ({len(df)}行、"
          f"{df[df.webkit_excluded]['char'].nunique()}字)")
    return df


def c_rank_correlation(decoy_df, out):
    if not HAVE_SCIPY_STATS:
        return None, None
    rows = []
    for dataset in ("both_batches", "calib_only"):
        for excl in (True, False):
            d = decoy_df[(decoy_df.dataset == dataset) & (decoy_df.webkit_excluded == excl)
                         & (decoy_df.converged)]
            by = {fam: dict(zip(d[d.family == fam]["char"], d[d.family == fam]["mu"])) for fam in FAMILIES}
            for f1 in FAMILIES:
                for f2 in FAMILIES:
                    common = sorted(set(by[f1]) & set(by[f2]))
                    if len(common) < 5:
                        rows.append(dict(dataset=dataset, webkit_excluded=excl, family_1=f1, family_2=f2,
                                         spearman_rho=float("nan"), n_chars_common=len(common), p_raw=float("nan")))
                        continue
                    rho, p = spearmanr([by[f1][c] for c in common], [by[f2][c] for c in common])
                    rows.append(dict(dataset=dataset, webkit_excluded=excl, family_1=f1, family_2=f2,
                                     spearman_rho=float(rho), n_chars_common=len(common), p_raw=float(p)))
    df = pd.DataFrame(rows)
    # Holm は「異なる方式どうしの6対」(主版=両バッチ・WebKit除外)に対して
    sel = (df.dataset == "both_batches") & (df.webkit_excluded) & (df.family_1 != df.family_2)
    pairs = df[sel].copy()
    pairs["key"] = pairs.apply(lambda r: tuple(sorted([r.family_1, r.family_2])), axis=1)
    uniq = pairs.drop_duplicates("key")
    adj = holm(uniq["p_raw"].values)
    amap = dict(zip(uniq["key"], adj))
    df["p_holm_over_6pairs"] = df.apply(
        lambda r: amap.get(tuple(sorted([r.family_1, r.family_2])), float("nan"))
        if (r.dataset == "both_batches" and r.webkit_excluded and r.family_1 != r.family_2)
        else float("nan"), axis=1)
    df.to_csv(os.path.join(out, "family_rank_correlation_v2.csv"), index=False)
    for dataset in ("both_batches", "calib_only"):
        for excl in (True, False):
            g = df[(df.dataset == dataset) & (df.webkit_excluded == excl)]
            piv = g.pivot(index="family_1", columns="family_2", values="spearman_rho")
            print(f"\n[C] 方式間のμ順位相関(まぎれ字, {dataset}, WebKit"
                  f"{'除外' if excl else '込み'}, n字={int(g['n_chars_common'].max())})")
            print(piv.reindex(FAMILIES)[FAMILIES].round(3).to_string())
    piv = df[(df.dataset == "both_batches") & (df.webkit_excluded)].pivot(
        index="family_1", columns="family_2", values="spearman_rho")
    return df, piv


def c_mechanism(decoy_df, struct_df, S, out):
    """墨量とμの相関、濁音/半濁音のμ比。墨量はまぎれ字の画像から測れないので
    (本命8字しか base 画像を持っていない)、ここでは清濁だけを見る。
    清濁の分類は字そのものから機械的に決める(゛/゜を持つかな)。"""
    DAK = set("がぎぐげござじずぜぞだぢづでどばびぶべぼ")
    HAN = set("ぱぴぷぺぽ")
    rows = []
    for excl in (True, False):
        d = decoy_df[(decoy_df.dataset == "both_batches") & (decoy_df.webkit_excluded == excl)
                     & (decoy_df.converged)]
        for fam in FAMILIES:
            g = d[d.family == fam]
            sei = g[~g["char"].isin(DAK | HAN)]["mu"]
            dak = g[g["char"].isin(DAK | HAN)]["mu"]
            rows.append(dict(webkit_excluded=excl, family=fam, n_chars=len(g),
                             n_seion=len(sei), n_dakuten=len(dak),
                             seion_mu_mean=float(sei.mean()) if len(sei) else float("nan"),
                             dakuten_mu_mean=float(dak.mean()) if len(dak) else float("nan"),
                             mu_ratio=float(dak.mean() / sei.mean()) if len(sei) and sei.mean() else float("nan"),
                             mu_diff_pt=float(dak.mean() - sei.mean()) if len(sei) and len(dak) else float("nan")))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "mechanism_correlates_v2.csv"), index=False)
    print("\n[C] まぎれ字での清濁とμ(WebKit除外)")
    print(df[df.webkit_excluded].round(3).to_string(index=False))
    return df


def c_best_family(fit_df, struct_df, out):
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")
               & (fit_df.char.isin(TARGET_CHARS))]
    st = struct_df.set_index("char")
    rows = []
    for ch in TARGET_CHARS:
        g = f[f.char == ch].sort_values("mu")
        rows.append(dict(char=ch, diacritic=DIACRITIC[ch],
                         best_family=g.iloc[0]["family"], best_mu=g.iloc[0]["mu"],
                         second_family=g.iloc[1]["family"], second_mu=g.iloc[1]["mu"],
                         worst_family=g.iloc[-1]["family"], worst_mu=g.iloc[-1]["mu"],
                         right_ink_frac=st.loc[ch, "right_ink_frac"],
                         fine_detail_frac=st.loc[ch, "fine_detail_frac"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "best_family_per_char_v2.csv"), index=False)
    print("\n[C] 字ごとに最も早く読める方式(μ最小、WebKit除外)")
    print(df.round(3).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# D. 誤りの質
# ---------------------------------------------------------------------------
def err_stats(g, n_choices):
    errs = g[g["correct"] == 0]["response_char"].dropna()
    errs = errs[errs != "-"]
    c = Counter(errs)
    h = shannon_bits(c)
    hmax = math.log2(n_choices - 1) if n_choices and n_choices > 1 else float("nan")
    top = c.most_common(2)
    return dict(n_trials=len(g), n_errors=int(len(errs)), entropy_bits=h,
                entropy_max_bits=hmax, entropy_norm=(h / hmax if hmax and not math.isnan(h) else float("nan")),
                n_distinct_wrong=len(c),
                top1_char=(top[0][0] if top else ""), top1_share=(top[0][1] / len(errs) if top and len(errs) else float("nan")),
                top2_char=(top[1][0] if len(top) > 1 else ""), top2_share=(top[1][1] / len(errs) if len(top) > 1 and len(errs) else float("nan")))


def d_error_entropy(S, out):
    m = S["main"][~S["main"]["webkit"]]
    m_all = S["main"]
    nc_v = 72
    outs = {}
    # 字ごと(視覚)
    rows = []
    for excl, src in ((True, m), (False, m_all)):
        for ch, g in src.groupby("target_char"):
            rows.append(dict(webkit_excluded=excl, char=ch, **err_stats(g, nc_v)))
    outs["visual_by_char"] = pd.DataFrame(rows)
    outs["visual_by_char"].to_csv(os.path.join(out, "error_entropy_visual_by_char_v2.csv"), index=False)
    # 字×方式
    rows = []
    for excl, src in ((True, m), (False, m_all)):
        for (ch, fam), g in src.groupby(["target_char", "family"]):
            rows.append(dict(webkit_excluded=excl, char=ch, family=fam, **err_stats(g, nc_v)))
    outs["visual_by_char_family"] = pd.DataFrame(rows)
    outs["visual_by_char_family"].to_csv(os.path.join(out, "error_entropy_visual_by_char_family_v2.csv"), index=False)
    # 方式×水準
    rows = []
    for excl, src in ((True, m), (False, m_all)):
        for (fam, lv), g in src.groupby(["family", "progress_pct"]):
            rows.append(dict(webkit_excluded=excl, family=fam, progress_pct=lv, **err_stats(g, nc_v)))
    lev = pd.DataFrame(rows)
    outs["by_level"] = lev
    lev.to_csv(os.path.join(out, "error_entropy_by_level_v2.csv"), index=False)
    # 帯(低/中/高、方式ごとに水準を3等分)
    rows = []
    for fam in FAMILIES:
        s = m[m.family == fam]
        lvs = sorted(s["progress_pct"].unique())
        n = len(lvs)
        bands = [lvs[:n // 3], lvs[n // 3:2 * n // 3], lvs[2 * n // 3:]]
        for i, b in enumerate(bands, 1):
            g = s[s["progress_pct"].isin(b)]
            rows.append(dict(family=fam, band_index=i, s_range=f"{min(b)}-{max(b)}%",
                             **err_stats(g, nc_v)))
    outs["bands"] = pd.DataFrame(rows)
    outs["bands"].to_csv(os.path.join(out, "error_entropy_bands_v2.csv"), index=False)
    # 転換点(entropy_norm が 0.6 を下回り続ける最初の水準)
    rows = []
    for fam in FAMILIES:
        g = lev[(lev.webkit_excluded) & (lev.family == fam)].sort_values("progress_pct")
        star, note = None, "転換なし(最後まで entropy_norm>=0.6)"
        vals = list(zip(g["progress_pct"], g["entropy_norm"]))
        for i, (lv, e) in enumerate(vals):
            if all((not math.isnan(v)) and v < 0.6 for _, v in vals[i:]):
                star = lv; note = f"進み具合{lv}%以降で entropy_norm<0.6 が続く"; break
        rows.append(dict(family=fam, transition_s_pct=star, note=note))
    outs["transitions"] = pd.DataFrame(rows)
    outs["transitions"].to_csv(os.path.join(out, "error_entropy_transitions_v2.csv"), index=False)
    # 聴覚
    a = S["a_ladder"]
    rows = [dict(char=ch, **err_stats(g, 68)) for ch, g in a.groupby("target_char")]
    outs["audio_by_char"] = pd.DataFrame(rows)
    outs["audio_by_char"].to_csv(os.path.join(out, "error_entropy_audio_by_char_v2.csv"), index=False)
    print("\n[D] 誤りの質の転換点(WebKit除外)")
    print(outs["transitions"].to_string(index=False))
    return outs


def d_perplexity(S, out, pct_bins, gate_bins):
    """実質選択肢数 2^H。字ごとにHを求めてから試行数で加重平均し、最後に2^H。"""
    def label(edges, i, unit=""):
        return f"{edges[i]:g}〜{edges[i+1]:g}{unit}"
    rows = []
    m = S["main"][~S["main"]["webkit"]]
    m_all = S["main"]
    for excl, src in ((True, m), (False, m_all)):
        for fam in FAMILIES:
            s = src[src.family == fam]
            for i in range(len(pct_bins) - 1):
                g = s[(s["progress_pct"] >= pct_bins[i]) & (s["progress_pct"] < pct_bins[i + 1])]
                if len(g) == 0:
                    rows.append(dict(webkit_excluded=excl, modality="visual", family=fam,
                                     bin_label=label(pct_bins, i, "%"), bin_lo=pct_bins[i], bin_hi=pct_bins[i + 1],
                                     n_trials=0, n_chars_with_data=0, entropy_bits_weighted=float("nan"),
                                     perplexity_2powH=float("nan"))); continue
                hs, ns = [], []
                for ch, gg in g.groupby("target_char"):
                    resp = gg["response_char"].dropna(); resp = resp[resp != "-"]
                    hs.append(shannon_bits(Counter(resp))); ns.append(len(gg))
                h = float(np.average(hs, weights=ns))
                rows.append(dict(webkit_excluded=excl, modality="visual", family=fam,
                                 bin_label=label(pct_bins, i, "%"), bin_lo=pct_bins[i], bin_hi=pct_bins[i + 1],
                                 n_trials=len(g), n_chars_with_data=len(hs),
                                 entropy_bits_weighted=h, perplexity_2powH=2 ** h))
    a = S["a_ladder"]
    for i in range(len(gate_bins) - 1):
        g = a[(a["gate_ms"] >= gate_bins[i]) & (a["gate_ms"] < gate_bins[i + 1])]
        if len(g) == 0:
            continue
        hs, ns = [], []
        for ch, gg in g.groupby("target_char"):
            resp = gg["response_char"].dropna(); resp = resp[resp != "-"]
            hs.append(shannon_bits(Counter(resp))); ns.append(len(gg))
        h = float(np.average(hs, weights=ns))
        rows.append(dict(webkit_excluded=True, modality="audio", family="",
                         bin_label=label(gate_bins, i, "ms"), bin_lo=gate_bins[i], bin_hi=gate_bins[i + 1],
                         n_trials=len(g), n_chars_with_data=len(hs),
                         entropy_bits_weighted=h, perplexity_2powH=2 ** h))
    af = S["a_full"]
    hs, ns = [], []
    for ch, gg in af.groupby("target_char"):
        resp = gg["response_char"].dropna(); resp = resp[resp != "-"]
        hs.append(shannon_bits(Counter(resp))); ns.append(len(gg))
    if hs:
        h = float(np.average(hs, weights=ns))
        rows.append(dict(webkit_excluded=True, modality="audio", family="", bin_label="打ち切りなし",
                         bin_lo=float("nan"), bin_hi=float("nan"), n_trials=len(af),
                         n_chars_with_data=len(hs), entropy_bits_weighted=h, perplexity_2powH=2 ** h))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "perplexity_by_bin_v2.csv"), index=False)
    print("\n[D] 実質選択肢数(WebKit除外・視覚)")
    print(df[(df.webkit_excluded) & (df.modality == "visual") & (df.n_trials > 0)]
          [["family", "bin_label", "n_trials", "perplexity_2powH"]].round(2).to_string(index=False))
    print("[D] 聴覚")
    print(df[df.modality == "audio"][["bin_label", "n_trials", "perplexity_2powH"]].round(2).to_string(index=False))
    return df


def d_confusion_similarity(S, fit_df, out):
    """方式どうしの応答分布の似かた。
    組み合わせ方式が「新しい手がかりを足す」かどうかの目安になる:
    2方式が同じ字を同じように取り違えるなら、その2つは同じ手がかりを運んでいる(冗長)。
    違う取り違えをするなら、組み合わせで情報が足し算になりうる(相補)。
    比較は**正答率をそろえた帯**で行う(見えている量が違うと分布は当然違うため)。
    各方式について、その方式のμに最も近い実測水準を1つ選び、そこの応答分布を使う。"""
    m = S["main"][~S["main"]["webkit"]]
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")
               & (fit_df.char.isin(TARGET_CHARS))]
    # 方式×字ごとに μ に最も近い実測水準を選ぶ
    picked = {}
    for fam in FAMILIES:
        for ch in TARGET_CHARS:
            r = f[(f.family == fam) & (f.char == ch)]
            if len(r) == 0 or math.isnan(r.iloc[0]["mu"]):
                continue
            mu = r.iloc[0]["mu"]
            s = m[(m.family == fam) & (m.target_char == ch)]
            if len(s) == 0:
                continue
            lvs = sorted(s["progress_pct"].unique())
            lv = min(lvs, key=lambda x: abs(x - mu))
            g = s[s["progress_pct"] == lv]
            resp = g["response_char"].dropna(); resp = resp[resp != "-"]
            picked[(fam, ch)] = (lv, Counter(resp), len(g), float(g["correct"].mean()))
    support = sorted({c for (_, cc, _, _) in picked.values() for c in cc})
    rows = []
    for i1 in range(len(FAMILIES)):
        for i2 in range(i1 + 1, len(FAMILIES)):
            f1, f2 = FAMILIES[i1], FAMILIES[i2]
            per_char = []
            for ch in TARGET_CHARS:
                if (f1, ch) in picked and (f2, ch) in picked:
                    jsd = js_divergence(picked[(f1, ch)][1], picked[(f2, ch)][1], support)
                    if not math.isnan(jsd):
                        per_char.append(jsd)
            rows.append(dict(family_1=f1, family_2=f2, n_chars=len(per_char),
                             jsd_mean_bits=float(np.mean(per_char)) if per_char else float("nan"),
                             jsd_median_bits=float(np.median(per_char)) if per_char else float("nan"),
                             acc_1_mean=float(np.mean([picked[(f1, c)][3] for c in TARGET_CHARS if (f1, c) in picked])),
                             acc_2_mean=float(np.mean([picked[(f2, c)][3] for c in TARGET_CHARS if (f2, c) in picked]))))
    df = pd.DataFrame(rows).sort_values("jsd_mean_bits", ascending=False)
    df.to_csv(os.path.join(out, "confusion_similarity.csv"), index=False)
    # 選んだ水準も記録
    pr = pd.DataFrame([dict(family=k[0], char=k[1], level_pct=v[0], n=v[2], acc=v[3])
                       for k, v in picked.items()])
    pr.to_csv(os.path.join(out, "confusion_similarity_levels.csv"), index=False)
    print("\n[D] 方式間の応答分布の違い(μ付近・JSダイバージェンス、大きいほど相補的)")
    print(df.round(4).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# E. 聴覚(不具合と無関係。値が変わらないことの確認)
# ---------------------------------------------------------------------------
def e_audio(S, out, ga, n_starts, lam_thr=0.5):
    a = S["a_ladder"]
    af = S["a_full"]
    rows = []
    for ch in TARGET_CHARS:
        g = a[a.target_char == ch]
        f = fit_rows(g, "gate_ms", ga, n_starts)
        gates = sorted(g["gate_ms"].dropna().unique())
        gf = af[af.target_char == ch]
        usable = bool(f["converged"] and (not math.isnan(f["lam"])) and f["lam"] >= lam_thr
                      and (not math.isnan(f["mu"])) and gates and min(gates) <= f["mu"] <= max(gates))
        resp = gf["response_char"].dropna(); resp = resp[resp != "-"]
        h = shannon_bits(Counter(resp)) if len(resp) else float("nan")
        rows.append(dict(char=ch, gamma=ga, lam=f["lam"], mu=f["mu"], sigma=f["sigma"],
                         converged=f["converged"], n_trials=f["n_trials"],
                         n_participants=g["participant_id"].nunique(),
                         gate_ms_tested=";".join(f"{x:g}" for x in gates),
                         usable_for_transcription=usable, note=f["note"],
                         n_full=len(gf), lambda_observed_full=float(gf["correct"].mean()) if len(gf) else float("nan"),
                         entropy_full_bits=h, perplexity_full=(2 ** h if not math.isnan(h) else float("nan"))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "audio_fit_v2.csv"), index=False)
    print("\n[E] 聴覚の当てはめ(不具合と無関係)")
    print(df[["char", "lam", "mu", "sigma", "converged", "n_trials", "usable_for_transcription"]]
          .round(4).to_string(index=False))
    # 参加者にWebKitが含まれていても影響が無いことの確認(除外版との対比)
    rows2 = []
    for ch in TARGET_CHARS:
        g = a[(a.target_char == ch) & (~a["webkit"])]
        f = fit_rows(g, "gate_ms", ga, n_starts)
        rows2.append(dict(char=ch, lam_webkit_excluded=f["lam"], mu_webkit_excluded=f["mu"],
                          sigma_webkit_excluded=f["sigma"], n_trials=f["n_trials"]))
    d2 = pd.DataFrame(rows2).merge(df[["char", "lam", "mu", "sigma"]], on="char")
    d2["mu_shift"] = d2["mu_webkit_excluded"] - d2["mu"]
    d2.to_csv(os.path.join(out, "audio_fit_webkit_check.csv"), index=False)
    print("[E] 聴覚: WebKit除外しても値が動かないことの確認(μの差)")
    print(d2[["char", "mu", "mu_webkit_excluded", "mu_shift"]].round(4).to_string(index=False))
    return df


def e_audio_free_gamma(S, out, n_starts, gamma_upper=0.5, lam_thr=0.5):
    from scipy.optimize import minimize
    a = S["a_ladder"]
    rows = []
    for ch in TARGET_CHARS:
        g = a[a.target_char == ch]
        t = g.groupby("gate_ms")["correct"].agg(["sum", "count"])
        xs = t.index.values.astype(float); ks = t["sum"].values.astype(float); ns = t["count"].values.astype(float)
        if len(xs) < 3:
            rows.append(dict(char=ch, gamma_free=float("nan"), lam=float("nan"), mu=float("nan"),
                             sigma=float("nan"), converged=False, usable_for_transcription=False,
                             note="水準不足")); continue
        def nll(p):
            gam, lam, mu, sg = p
            sg = max(sg, 1e-6)
            z = np.clip(-(xs - mu) / sg, -500, 500)
            pr = np.clip(gam + (lam - gam) / (1 + np.exp(z)), 1e-9, 1 - 1e-9)
            return -float(np.sum(ks * np.log(pr) + (ns - ks) * np.log(1 - pr)))
        rng_ = xs.max() - xs.min()
        best = None
        for mu0 in np.percentile(xs, [20, 50, 80]):
            for s0 in [rng_ * f for f in (0.05, 0.2, 0.5)]:
                r = minimize(nll, [0.02, 0.9, mu0, s0], method="L-BFGS-B",
                             bounds=[(0, gamma_upper), (0, 1), (xs.min() - rng_, xs.max() + rng_),
                                     (max(rng_ * 1e-3, 1e-6), rng_ * 8)])
                if best is None or r.fun < best.fun:
                    best = r
        gam, lam, mu, sg = best.x
        rows.append(dict(char=ch, gamma_free=float(gam), lam=float(lam), mu=float(mu), sigma=float(sg),
                         converged=bool(best.success),
                         usable_for_transcription=bool(best.success and lam >= lam_thr
                                                       and xs.min() <= mu <= xs.max()),
                         note=("" if best.success else str(best.message))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "audio_fit_free_gamma_v2.csv"), index=False)
    return df


def e_transcribability(S, audio_df, fit_df, out, gv, unfit_thr=0.95):
    """32セル(8字×4方式)の転写成立判定。
    A(t) を字自身の γ,λ で q に直し、V(s)=q となる s を逆引きできるかを、
    聴覚の実測 gate_ms の範囲で見る。q が V の届く範囲 [γ_v, λ_v] を出ると丸めが起きる。"""
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")
               & (fit_df.char.isin(TARGET_CHARS))]
    a = audio_df.set_index("char")
    ee = pd.read_csv(os.path.join(out, "error_entropy_visual_by_char_family_v2.csv"))
    ee = ee[ee.webkit_excluded]
    # 実測の天井: その字×方式を進み具合100%で見せたときの正答率(当てはめを通さない生の値)。
    m100 = S["main"][(~S["main"]["webkit"]) & (S["main"]["progress_pct"] == 100)]
    ceil_obs = {key: (int(g["correct"].sum()), len(g))
                for key, g in m100.groupby(["target_char", "family"])}
    rows = []
    for ch in TARGET_CHARS:
        ar = a.loc[ch]
        gates = [float(x) for x in str(ar["gate_ms_tested"]).split(";") if x]
        ts = np.linspace(min(gates), max(gates), 201) if gates else np.array([])
        for fam in FAMILIES:
            vr = f[(f.family == fam) & (f.char == ch)].iloc[0]
            if not ar["usable_for_transcription"]:
                judge, frac, tclamp = "対象外(聴覚曲線が使えない)", float("nan"), float("nan")
            elif not vr["converged"] or math.isnan(vr["mu"]):
                judge, frac, tclamp = "対象外(視覚曲線が当てはまらない)", float("nan"), float("nan")
            else:
                # 旧版 analyze_families.py と同一の判定: q(t) が視覚の天井 λ_v を超えたら
                # 「その方式ではどれだけアニメを進めても聴覚に追いつけない(s=1へ丸め)」。
                p_a = sig(ts, ar["gamma"], ar["lam"], ar["mu"], ar["sigma"])
                q = np.clip((p_a - ar["gamma"]) / (ar["lam"] - ar["gamma"]), 0, 1)
                over = q > vr["lam"]
                frac = float(np.mean(over))
                tclamp = float(ts[np.argmax(over)]) if over.any() else float("nan")
                judge = "成立" if frac <= 1e-9 else ("不成立" if frac >= unfit_thr else "一部成立")
            # 転写が実際に使う s の範囲(V^-1(q) の最小・最大)と、**厳しい判定**。
            #
            # ⚠ 旧版の判定(q > λ_v で丸め)には抜けがある: λ_v が自由推定で 1.0 ちょうどに
            #   張り付いた字×方式では、q は必ず λ_v 以下になるので**自動的に「成立」**に
            #   なってしまう。しかし λ_v=1.0 のとき q→1 に必要な s は無限大に発散するので、
            #   実際には s=100% を超える(=画面に出せない)。ここでは
            #   「必要な s が実測できる範囲 [最低水準, 100%] に収まるか」で判定し直す。
            k100, n100 = ceil_obs.get((ch, fam), (0, 0))
            ceil = (k100 / n100) if n100 else float("nan")
            s_req_lo = s_req_hi = float("nan")
            frac_s_over = float("nan"); judge_s = judge
            if judge in ("成立", "一部成立"):
                lam_v, mu_v, sg_v = vr["lam"], vr["mu"], vr["sigma"]
                qc = np.clip(q, gv + 1e-9, lam_v - 1e-9)
                ratio = (lam_v - gv) / (qc - gv) - 1.0
                ss = mu_v - sg_v * np.log(np.clip(ratio, 1e-12, None))
                s_req_lo, s_req_hi = float(np.min(ss)), float(np.max(ss))
                # **実測の天井**を超えたら丸め。当てはめの λ ではなく、s=100% での生の正答率を
                # 天井にする。λ が自由推定で 1.0 に張り付いた字では、λ を天井に使うと
                # 「q はいつでも λ 以下」となって自動的に成立になってしまうため。
                over = q > ceil
                frac_s_over = float(np.mean(over))
                judge_s = ("成立" if frac_s_over <= 1e-9
                           else ("不成立" if frac_s_over >= unfit_thr else "一部成立"))
            er = ee[(ee.char == ch) & (ee.family == fam)]
            rows.append(dict(char=ch, family=fam, diacritic=DIACRITIC[ch],
                             audio_usable=bool(ar["usable_for_transcription"]),
                             judgement_old_criterion=judge, judgement=judge_s,
                             frac_clamped_upper=frac, frac_over_observed_ceiling=frac_s_over,
                             observed_ceiling_at_s100=ceil, n_at_s100=n100,
                             t_clamp_start_ms=tclamp,
                             s_required_min_pct=s_req_lo, s_required_max_pct=s_req_hi,
                             t_domain_min_ms=(min(gates) if gates else float("nan")),
                             t_domain_max_ms=(max(gates) if gates else float("nan")),
                             lambda_visual=vr["lam"], gamma_visual=gv, mu_visual=vr["mu"],
                             sigma_visual=vr["sigma"], visual_converged=bool(vr["converged"]),
                             entropy_norm=(float(er.iloc[0]["entropy_norm"]) if len(er) else float("nan"))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "transcribability_v2.csv"), index=False)
    print("\n[E] 転写成立判定(WebKit除外) 旧基準 = q>λ_v だけを見る")
    print(pd.crosstab(df["family"], df["judgement_old_criterion"]).to_string())
    print("[E] 転写成立判定(WebKit除外) 新基準 = 実測の天井(s=100%の生の正答率)を超えないか")
    print(pd.crosstab(df["family"], df["judgement"]).to_string())
    print(df[df.audio_usable][["char", "family", "judgement_old_criterion", "judgement",
                               "frac_clamped_upper", "frac_over_observed_ceiling",
                               "observed_ceiling_at_s100", "n_at_s100", "lambda_visual",
                               "s_required_max_pct"]].round(3).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# F. 速さ
# ---------------------------------------------------------------------------
def f_speed(S, out, nboot, rng):
    m = S["main"][~S["main"]["webkit"]].copy()
    # 「絵が実際に違う」水準: 300/500 で actual_frames の平均が異なる水準
    diff_levels = set()
    for (fam, lv), g in m.groupby(["family", "progress_pct"]):
        a3 = g[g.base_anim_ms_i == 300]["actual_frames"].astype(float)
        a5 = g[g.base_anim_ms_i == 500]["actual_frames"].astype(float)
        if len(a3) and len(a5) and abs(a3.mean() - a5.mean()) > 1e-9:
            diff_levels.add((fam, lv))
    m["frames_differ"] = [(r.family, r.progress_pct) in diff_levels for r in m.itertuples()]
    rows, ps = [], []
    for fam in FAMILIES:
        for subset in ("all", "frames_differ"):
            s = m[m.family == fam]
            if subset == "frames_differ":
                s = s[s["frames_differ"]]
            if len(s) == 0:
                continue
            d_, lo, hi, pv = cluster_boot_diff(s, "base_anim_ms_i", 500, 300,
                                               weight_col="progress_pct", nboot=nboot, rng=rng)
            n3 = int((s.base_anim_ms_i == 300).sum()); n5 = int((s.base_anim_ms_i == 500).sum())
            rows.append(dict(family=fam, subset=subset, n300=n3, n500=n5,
                             acc300=float(s[s.base_anim_ms_i == 300]["correct"].mean()),
                             acc500=float(s[s.base_anim_ms_i == 500]["correct"].mean()),
                             diff_pt_500_minus_300=d_ * 100, lo_pt=lo * 100, hi_pt=hi * 100, p_boot=pv,
                             n_participants=s["participant_id"].nunique(), n_boot=nboot))
            if subset == "frames_differ":
                ps.append(pv)
    adj = holm(ps); i = 0
    for r in rows:
        if r["subset"] == "frames_differ":
            r["p_holm_over_4families"] = adj[i]; i += 1
        else:
            r["p_holm_over_4families"] = float("nan")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "speed_effect_family_v2.csv"), index=False)
    rows = []
    for (fam, lv), g in m.groupby(["family", "progress_pct"]):
        g3 = g[g.base_anim_ms_i == 300]; g5 = g[g.base_anim_ms_i == 500]
        p3, l3, h3 = wilson(g3["correct"].sum(), len(g3)); p5, l5, h5 = wilson(g5["correct"].sum(), len(g5))
        rows.append(dict(family=fam, progress_pct=lv, frames_differ=((fam, lv) in diff_levels),
                         n300=len(g3), acc300=p3, lo300=l3, hi300=h3,
                         n500=len(g5), acc500=p5, lo500=l5, hi500=h5,
                         diff_pt=(p5 - p3) * 100))
    pd.DataFrame(rows).to_csv(os.path.join(out, "speed_effect_by_level_v2.csv"), index=False)
    print("\n[F] 速さの効果(WebKit除外・水準等重み・参加者ブートストラップ)")
    print(df[["family", "subset", "n300", "acc300", "n500", "acc500", "diff_pt_500_minus_300",
              "lo_pt", "hi_pt", "p_boot", "p_holm_over_4families"]].round(4).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# G. 組み合わせ方式
# ---------------------------------------------------------------------------
def g_composite(fit_df, span_df, out, gv):
    """組み合わせ s_x(u)=100·u^k の k と、組み合わせ曲線の予測。

    ■ 前提(重要): 較正データに**組み合わせ方式の試行は1件も無い**(family列は
      fade/reveal/blur/wipe のみ)。したがってここで出す組み合わせの曲線は
      **単体の曲線からの予測**であって実測ではない。上下2つのモデルで挟む:
        直列モデル(悲観): q_comb(u) = q_a(s_a(u)) · q_b(s_b(u))
            2つの劣化が独立に「読めなくする」と仮定。組み合わせの下限。
        最良モデル(楽観): q_comb(u) = min(q_a(s_a(u)), q_b(s_b(u)))
            きつい方の劣化だけが効くと仮定。組み合わせの上限。
      ここで q_x(s) = (V_x(s) − γ)/(λ_x − γ) は「識別できている割合」。
    """
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")]
    # --- k の再計算(旧: バッチ1のみ・WebKit込み → 新: 両バッチ・WebKit除外)
    rows = []
    for excl in (True, False):
        ff = fit_df[(fit_df.webkit_excluded == excl) & (fit_df.version == "excl_clamp0")
                    & (fit_df.axis == "actual") & (fit_df.speed == "pooled")
                    & (fit_df.char.isin(TARGET_CHARS))]
        for fam in FAMILIES:
            mubar = float(ff[ff.family == fam]["mu"].mean())
            mb = max(0.01, min(99.99, mubar))
            k = math.log(mb / 100.0) / math.log(0.5)
            rows.append(dict(webkit_excluded=excl, family=fam, mu_bar_8chars=mubar,
                             k_new=max(0.05, min(20.0, k))))
    kdf = pd.DataFrame(rows)
    cur = {"fade": 5.9302, "reveal": 5.6221, "blur": 1.0997, "wipe": 1.5576}
    kdf["k_config_current"] = kdf["family"].map(cur)
    kdf["k_change_pct"] = (kdf["k_new"] / kdf["k_config_current"] - 1) * 100
    kdf.to_csv(os.path.join(out, "composite_k_v2.csv"), index=False)
    print("\n[G] 組み合わせの写し指数 k = ln(μ̄/100)/ln(0.5)")
    print(kdf.round(4).to_string(index=False))

    kmap = dict(zip(kdf[kdf.webkit_excluded]["family"], kdf[kdf.webkit_excluded]["k_new"]))
    fits = {(fam, ch): f[(f.family == fam) & (f.char == ch)].iloc[0]
            for fam in FAMILIES for ch in list(TARGET_CHARS) + ["(8字プール)"]}

    def qcurve(fam, ch, s_pct):
        r = fits[(fam, ch)]
        p = sig(s_pct, gv, r["lam"], r["mu"], r["sigma"])
        return np.clip((p - gv) / (r["lam"] - gv), 0, 1)

    us = np.linspace(0, 1, 1001)

    def span(q):
        lo = us[q >= 0.05]; hi = us[q >= 0.95]; mid = us[q >= 0.5]
        u5 = lo[0] if len(lo) else float("nan")
        u95 = hi[0] if len(hi) else float("nan")
        return u5, u95, (u95 - u5 if not (math.isnan(u5) or math.isnan(u95)) else float("nan")), \
               (mid[0] if len(mid) else float("nan"))

    proj, per_char = [], []
    # --- 単体(同じ物差し)
    for fam in FAMILIES:
        k = kmap[fam]
        for ch in TARGET_CHARS:
            q = qcurve(fam, ch, 100.0 * us ** k)
            u5, u95, sp, mid = span(q)
            per_char.append(dict(pair=fam, kind="single", implemented=True, char=ch,
                                 model="実測曲線", k_a=k, k_b=float("nan"),
                                 u5=u5, u95=u95, u_span=sp, u_mid=mid, bottleneck=""))
    # --- 組み合わせ
    for a, b in PAIRS_IMPL + PAIRS_EXTRA:
        name = f"{a}+{b}"
        ka, kb = kmap[a], kmap[b]
        sa = 100.0 * us ** ka; sb = 100.0 * us ** kb
        for ch in TARGET_CHARS:
            qa = qcurve(a, ch, sa); qb = qcurve(b, ch, sb)
            i50 = np.argmin(np.abs(us - 0.5))
            for model, q in (("直列(悲観)", qa * qb), ("最良(楽観)", np.minimum(qa, qb))):
                u5, u95, sp, mid = span(q)
                per_char.append(dict(pair=name, kind="composite", implemented=((a, b) in PAIRS_IMPL),
                                     char=ch, model=model, k_a=ka, k_b=kb,
                                     u5=u5, u95=u95, u_span=sp, u_mid=mid,
                                     bottleneck=(a if qa[i50] < qb[i50] else b)))
            for i in range(0, len(us), 25):
                proj.append(dict(pair=name, char=ch, u=us[i], s_a_pct=sa[i], s_b_pct=sb[i],
                                 q_a=qa[i], q_b=qb[i], q_series=qa[i] * qb[i],
                                 q_min=min(qa[i], qb[i])))
    pd.DataFrame(proj).to_csv(os.path.join(out, "composite_projection.csv"), index=False)
    pc = pd.DataFrame(per_char)
    pc.to_csv(os.path.join(out, "composite_per_char.csv"), index=False)

    rank = pc.groupby(["pair", "kind", "implemented", "model"]).agg(
        u_span_median=("u_span", "median"), u_span_min=("u_span", "min"),
        u_span_max=("u_span", "max"), u_mid_median=("u_mid", "median"),
        u5_median=("u5", "median"), u95_median=("u95", "median"),
        n_chars_no_span=("u_span", lambda s: int(s.isna().sum())),
        bottleneck_mode=("bottleneck", lambda s: s.mode().iloc[0] if len(s.mode()) else "")
    ).reset_index()
    # 「死んでいる区間」= 何も伝わらない前半(u<u5)と、もう天井で動かない後半(u>u95)。
    # 組み合わせの狙いの1つ「天井に張り付く区間を動かす」はここに出る。
    rank["dead_low"] = rank["u5_median"]
    rank["dead_high"] = 1.0 - rank["u95_median"]
    rank["dead_total"] = rank["dead_low"] + rank["dead_high"]
    # 単体との比較(その組み合わせを構成する2方式の span に対する増減)
    single_span = {r["pair"]: r["u_span_median"]
                   for _, r in rank[rank.kind == "single"].iterrows()}
    def vs_parents(r):
        if r["kind"] != "composite":
            return (float("nan"), float("nan"))
        a, b = r["pair"].split("+")
        return (r["u_span_median"] / single_span[a] - 1, r["u_span_median"] / single_span[b] - 1)
    rank[["span_change_vs_a", "span_change_vs_b"]] = rank.apply(
        lambda r: pd.Series(vs_parents(r)), axis=1)
    rank = rank.sort_values(["model", "u_span_median"], ascending=[True, False])
    rank.to_csv(os.path.join(out, "composite_ranking.csv"), index=False)
    print("\n[G] u空間で使える幅(8字の中央値。組み合わせは単体曲線からの**予測**)")
    print(rank[["pair", "kind", "implemented", "model", "u_span_median", "u_span_min",
                "u_mid_median", "dead_low", "dead_high", "span_change_vs_a", "span_change_vs_b",
                "bottleneck_mode"]].round(3).to_string(index=False))
    return kdf, rank


def g_mapping_variants(fit_df, span_df, out, gv, kdf):
    """組み合わせの「進み方の写し方」を3通り比べる。

    いまの作り(現行・べき乗): s_x(u) = 100·u^k、k は u=0.5 でその方式の μ̄ を通るよう決める。
      → 2方式の働く区間が u=0.5 付近で**重なる**。重なった部分しか動かないので、
        組み合わせの使える幅は「2つの区間の重なり」に近くなる。

    同時型(log線形・全域): 各方式の s を u∈[0,1] 全体にわたって
      s5 → s95 まで対数線形に動かす。両方が最初から最後まで一緒に動く。

    段階型(log線形・ずらし): 一方を u∈[0, 0.55]、他方を u∈[0.45, 1] に割り当てる。
      前半は片方だけ、後半はもう片方だけが動く。**区間の和**になるので幅が広がる。
      窓の外では、下は「その方式の s5(まだ何も分からない側)」、上は「100%(完成)」で固定。
    """
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")]
    sp = span_df[(span_df.webkit_excluded) & (span_df.char.isin(TARGET_CHARS))]
    kmap = dict(zip(kdf[kdf.webkit_excluded]["family"], kdf[kdf.webkit_excluded]["k_new"]))
    us = np.linspace(0, 1, 1001)

    def q_of(fam, ch, s_pct):
        r = f[(f.family == fam) & (f.char == ch)].iloc[0]
        p = sig(s_pct, gv, r["lam"], r["mu"], r["sigma"])
        return np.clip((p - gv) / (r["lam"] - gv), 0, 1)

    def s_loglin(fam, ch, lo, hi):
        r = sp[(sp.family == fam) & (sp.char == ch)].iloc[0]
        s5, s95 = float(r["s5_clipped_pct"]), float(r["s95_clipped_pct"])
        w = np.clip((us - lo) / max(hi - lo, 1e-9), 0, 1)
        s = s5 * (s95 / s5) ** w
        s = np.where(us >= hi, 100.0, s)
        return s

    rows = []
    for a, b in PAIRS_IMPL + PAIRS_EXTRA:
        name = f"{a}+{b}"
        for ch in TARGET_CHARS:
            variants = {
                "現行(べき乗・重なり)": (100.0 * us ** kmap[a], 100.0 * us ** kmap[b]),
                "同時型(log線形・全域)": (s_loglin(a, ch, 0.0, 1.0), s_loglin(b, ch, 0.0, 1.0)),
                "段階型(log線形・ずらし)": (s_loglin(a, ch, 0.0, 0.55), s_loglin(b, ch, 0.45, 1.0)),
            }
            for vname, (sa, sb) in variants.items():
                qa, qb = q_of(a, ch, sa), q_of(b, ch, sb)
                for model, q in (("直列(悲観)", qa * qb), ("最良(楽観)", np.minimum(qa, qb))):
                    lo = us[q >= 0.05]; hi = us[q >= 0.95]
                    u5 = lo[0] if len(lo) else float("nan")
                    u95 = hi[0] if len(hi) else float("nan")
                    # 直線からのずれ(q が u に対してどれだけまっすぐ伸びるか)。
                    # 小さいほど「u を等間隔に刻めば q も等間隔に増える」= 転写で使いやすい。
                    lin_err = float(np.mean(np.abs(q - us)))
                    rows.append(dict(pair=name, char=ch, mapping=vname, model=model,
                                     u5=u5, u95=u95,
                                     u_span=(u95 - u5 if not (math.isnan(u5) or math.isnan(u95)) else float("nan")),
                                     linearity_mae=lin_err))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "composite_mapping_variants.csv"), index=False)
    agg = df.groupby(["mapping", "model", "pair"]).agg(
        u_span_median=("u_span", "median"), u_span_min=("u_span", "min"),
        linearity_mae_median=("linearity_mae", "median")).reset_index()
    agg = agg.sort_values(["model", "mapping", "u_span_median"], ascending=[True, True, False])
    agg.to_csv(os.path.join(out, "composite_mapping_summary.csv"), index=False)
    print("\n[G] 写し方3通りの比較(8字の中央値)")
    print(agg.round(3).to_string(index=False))
    return df, agg


def g_exp2_power(out, n_participants=(280, 420, 560, 700), n_conditions=(4, 6, 8, 10, 12),
                 n_gates=7, n_chars=8, points_per_char=3, p_base=0.5, alpha=0.05, power=0.80):
    """実験2の条件数と必要人数の関係。
    出題設計(transfer_config.js): 1人 = 8字 × 7時点のうち3時点 = 24問、字ごとに条件1つ。
    条件は conditions[(i·b_step + n) % C] で巡るので、1人は min(8, C) 個の条件に触れる。
      1セル(条件×字×時点)の試行数 = N × (字数 × 担当点数) / (C × 字数 × 点数)
                                  = N × 担当点数 / (C × 点数)
      1つの「条件×時点」(8字を束ねる)の試行数 = 上記 × 字数
    検出できる差(MDD)は、2つの条件を同じ時点で比べる二項検定(片セル独立、
    1人が同じ条件×時点に2回入ることは無いのでクラスタ補正は不要)で計算する。
    """
    from math import sqrt
    z_a = 1.959963985                      # 両側 α=0.05
    z_b = 0.8416212336                     # 片側 80% 検出力
    rows = []
    for C in n_conditions:
        for N in n_participants:
            per_cell = N * points_per_char / (C * n_gates)
            per_cond_gate = per_cell * n_chars
            # MDD: p1=p_base, p2=p_base+d を検出する近似式
            def mdd(n_arm, ntests):
                if n_arm <= 0:
                    return float("nan")
                za = norm.ppf(1 - (alpha / max(1, ntests)) / 2) if HAVE_SCIPY_STATS else z_a
                # 反復して d を解く
                d = 0.05
                for _ in range(200):
                    p2 = min(0.99, p_base + d)
                    se = sqrt(p_base * (1 - p_base) / n_arm + p2 * (1 - p2) / n_arm)
                    d_new = (za + z_b) * se
                    if abs(d_new - d) < 1e-6:
                        break
                    d = d_new
                return d
            rows.append(dict(n_conditions=C, n_participants=N,
                             trials_per_cell=per_cell, trials_per_condition_gate=per_cond_gate,
                             mdd_pt_1test=mdd(per_cond_gate, 1) * 100,
                             mdd_pt_holm7=mdd(per_cond_gate, n_gates) * 100,
                             mdd_pt_holm_all=mdd(per_cond_gate, n_gates * C * (C - 1) // 2) * 100))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "exp2_allocation_power.csv"), index=False)
    print("\n[G] 実験2の条件数と検出できる差(条件×時点、8字を束ねた場合)")
    print(df.round(2).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# H. 棚卸しと新旧対比
# ---------------------------------------------------------------------------
# 旧 analyze_families.py の出力21本の汚染判定。
# 判定基準:
#   汚染        … ぼやけ方式の試行を数値に含む。WebKit端末では字が鮮明なまま出ていたので値が誤り。
#   一部汚染    … 表の一部の行(blur行)だけが汚染。他の行はそのまま使える。
#   無傷        … ぼやけを含まない。ただし「バッチ1のみ163人」である点は更新される。
#   データ非依存… 画像から計算しており試行データを使わない。
CONTAMINATION = [
    ("audio_fit.csv", "無傷", "聴覚のみ(群acal 90人)。視覚の描画不具合と無関係。WebKit除外前後でμの差は|Δ|≤1.2ms(が を除く。が はλ=0.008で曲線自体が退化しておりμは元から意味を持たない)。"),
    ("audio_fit_free_gamma.csv", "無傷", "同上。聴覚のみ。"),
    ("vs_fit_point.csv", "一部汚染", "384行のうち family=blur の96行が汚染。fade/reveal/wipe の288行は描画不具合の影響なし(ただしバッチ1のみ163人の推定値なので、325人版に更新される)。"),
    ("vs_bootstrap.csv", "一部汚染", "96行のうち family=blur の24行が汚染。同上。"),
    ("speed_effect_family.csv", "一部汚染", "8行のうち family=blur の2行が汚染。WebKit端末ではぼやけが効かず速さの効果が測れていない(常に正答)。"),
    ("speed_effect_by_level.csv", "一部汚染", "family=blur の行が汚染。"),
    ("char_structure.csv", "データ非依存", "字の墨画像から計算。試行データを一切使わない。"),
    ("error_entropy_audio_by_char.csv", "無傷", "聴覚のみ。"),
    ("error_entropy_visual_by_char.csv", "汚染", "字ごとに4方式を束ねて集計しているので、blurのWebKit試行(全問正答)が全行に混ざる。"),
    ("error_entropy_visual_by_char_family.csv", "一部汚染", "family=blur の8行が汚染。"),
    ("error_entropy_by_level.csv", "一部汚染", "family=blur の行が汚染。"),
    ("error_entropy_bands.csv", "一部汚染", "family=blur の3行が汚染。"),
    ("error_entropy_transitions.csv", "一部汚染", "family=blur の1行が汚染。"),
    ("perplexity_by_bin.csv", "一部汚染", "modality=visual・family=blur の行が汚染。聴覚の行は無傷。"),
    ("transcribability_table.csv", "一部汚染", "8行(family=blur)が汚染。判定に使う視覚のλ・μがblurだけ誤り。"),
    ("family_summary.csv", "一部汚染", "4行のうち blur 行が汚染。"),
    ("family_rank_correlation.csv", "汚染", "参照した fit_decoy_visual.csv がバッチ1・WebKit込みのため、blurを含む対(3対)は汚染。加えて相関行列は行列全体で解釈されるので、表として汚染扱いにする。"),
    ("mechanism_correlates.csv", "一部汚染", "4行のうち blur 行が汚染。"),
    ("best_family_per_char.csv", "汚染", "8字すべてで「最も不利な方式」の判定にblurのμを使っており、blurのμが低く出ていたぶん順位判定が歪む。"),
    ("families_report.html", "汚染", "上記を本文に埋め込んでいる。とくに『ぼやけは床が高い』『blurのμは45前後』『方式間のμ順位相関はほぼ0』は数値が変わる。"),
    ("(旧レポート本文)『ぼやけは床が高く、まったく分からない状態を作れない』", "汚染・結論が覆る",
     "WebKit端末(13.8%)が全水準で正答していたことによる見かけの床。除外すると最低水準の正答率は他の3方式と区別がつかない。"),
]


def h_inventory(out):
    df = pd.DataFrame(CONTAMINATION, columns=["旧出力", "判定", "根拠"])
    df.to_csv(os.path.join(out, "contamination_inventory.csv"), index=False)
    print("\n[H] 汚染の棚卸し")
    print(df.to_string(index=False))
    return df


def h_old_vs_new(out, fit_df, floor_df, span_df, kdf, rank_corr, summary_df):
    """旧(バッチ1のみ163人・WebKit込み)と新(両バッチ325人・WebKit除外)の主要数値の対比。
    旧の値は旧CSV/旧レポートから転記した実測値であり、ここで再計算はしない。"""
    OLD = {
        ("blur", "mu_あ"): 45.42, ("blur", "mu_か"): 45.6, ("blur", "mu_が"): 56.5,
        ("blur", "mu_し"): 33.4, ("blur", "mu_つ"): 31.4, ("blur", "mu_ま"): 44.5,
        ("blur", "mu_ら"): 47.6,
    }
    f = fit_df[(fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
               & (fit_df.axis == "actual") & (fit_df.speed == "pooled")]
    f0 = fit_df[(~fit_df.webkit_excluded) & (fit_df.version == "excl_clamp0")
                & (fit_df.axis == "actual") & (fit_df.speed == "pooled")]
    rows = []
    for fam in FAMILIES:
        for ch in TARGET_CHARS:
            a = f[(f.family == fam) & (f.char == ch)].iloc[0]
            b = f0[(f0.family == fam) & (f0.char == ch)].iloc[0]
            rows.append(dict(quantity=f"mu ({fam}, {ch})",
                             value_webkit_included_325=b["mu"], value_webkit_excluded_325=a["mu"],
                             shift=a["mu"] - b["mu"],
                             old_report_value=OLD.get((fam, f"mu_{ch}"), float("nan"))))
    for fam in FAMILIES:
        a = f[(f.family == fam) & (f.char == "(8字プール)")].iloc[0]
        b = f0[(f0.family == fam) & (f0.char == "(8字プール)")].iloc[0]
        for col in ("mu", "sigma", "lam"):
            rows.append(dict(quantity=f"{col} (8字プール, {fam})",
                             value_webkit_included_325=b[col], value_webkit_excluded_325=a[col],
                             shift=a[col] - b[col], old_report_value=float("nan")))
    fl = floor_df[floor_df.webkit_excluded]
    fl0 = floor_df[~floor_df.webkit_excluded]
    for fam in FAMILIES:
        a = fl[fl.family == fam].iloc[0]; b = fl0[fl0.family == fam].iloc[0]
        rows.append(dict(quantity=f"床の正答率 ({fam}, 最低水準)",
                         value_webkit_included_325=b["acc_plus_check"],
                         value_webkit_excluded_325=a["acc_plus_check"],
                         shift=a["acc_plus_check"] - b["acc_plus_check"], old_report_value=float("nan")))
    for _, r in kdf[kdf.webkit_excluded].iterrows():
        rows.append(dict(quantity=f"組み合わせ指数 k ({r['family']})",
                         value_webkit_included_325=float(kdf[(~kdf.webkit_excluded) & (kdf.family == r["family"])]["k_new"].iloc[0]),
                         value_webkit_excluded_325=r["k_new"], shift=float("nan"),
                         old_report_value=r["k_config_current"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "old_vs_new.csv"), index=False)
    print(f"  書き出し: old_vs_new.csv ({len(df)}行)")
    return df


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="project/data_calib2_live/transfer_trials.csv")
    ap.add_argument("--out", default="project/data_calib2_live/analysis_families_v2")
    ap.add_argument("--base-dir", default="experiment/base")
    ap.add_argument("--boot-vs", type=int, default=400)
    ap.add_argument("--boot-diff", type=int, default=4000)
    ap.add_argument("--fit-starts", type=int, default=8)
    ap.add_argument("--boot-starts", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260827)
    ap.add_argument("--pct-bins", default="0,1,3,8,20,50,90,101")
    ap.add_argument("--gate-bins", default="0,15,25,35,50,70,100000")
    ap.add_argument("--skip-boot", action="store_true", help="重いブートストラップを飛ばす(点推定のみ)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    d = load(a.inp)
    S = slices(d)
    gv, ga = gammas(d)

    levels_min = S["main"].groupby("family")["progress_pct"].min().to_dict()

    a_webkit_audit(S, a.out)
    a_webkit_vs_android(S, a.out)
    a_phase_consistency(S, a.out, a.boot_diff, rng)
    a_phase_fits(S, a.out, gv, a.fit_starts)
    b_curves(S, a.out)
    floor_df = b_floor_ceiling(S, a.out, gv)
    fit_df = b_fits(S, a.out, gv, a.fit_starts)
    if not a.skip_boot:
        b_bootstrap(S, a.out, gv, a.boot_vs, a.seed, a.boot_starts)
    span_df = b_usable_span(fit_df, a.out, gv, levels_min)
    summary_df = b_family_summary(S, fit_df, None, a.out, gv)
    b_resolution_limit(span_df, a.out, a.base_dir)
    struct = char_structure(a.base_dir, a.out)
    c_dakuten(S, fit_df, a.out, a.boot_diff, rng)
    decoy_df = c_decoy(S, a.out, gv, a.fit_starts)
    rank_corr, _ = c_rank_correlation(decoy_df, a.out)
    c_mechanism(decoy_df, struct, S, a.out)
    c_best_family(fit_df, struct, a.out)
    d_error_entropy(S, a.out)
    d_perplexity(S, a.out, [float(x) for x in a.pct_bins.split(",")],
                 [float(x) for x in a.gate_bins.split(",")])
    d_confusion_similarity(S, fit_df, a.out)
    audio_df = e_audio(S, a.out, ga, a.fit_starts)
    e_audio_free_gamma(S, a.out, a.fit_starts)
    e_transcribability(S, audio_df, fit_df, a.out, gv)
    f_speed(S, a.out, a.boot_diff, rng)
    kdf, rank = g_composite(fit_df, span_df, a.out, gv)
    g_mapping_variants(fit_df, span_df, a.out, gv, kdf)
    g_exp2_power(a.out)
    h_inventory(a.out)
    h_old_vs_new(a.out, fit_df, floor_df, span_df, kdf, rank_corr, summary_df)

    print(f"\n完了: CSV -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
