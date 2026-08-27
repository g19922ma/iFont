#!/usr/bin/env python3
"""
群B（検証フェーズ）の warp 表を作り直す v3
==========================================
build_warp_b.py / build_warp_b2.py の 3 つの誤りを直した版。

■ ① 視覚の当てはめを **基準アニメ 300ms の試行だけ**に絞る
   生成（逆引き）に使うのは 300ms の曲線だけと決めてある
   （transfer_config.js の visual.calib_speed_probe.generation_level_ms = 300）。
   ところが analyze_calib_full.py / fit_calib2.py の当てはめは base_anim_ms で
   絞っておらず、300ms と 500ms の 2 水準を混ぜて 1 本の曲線にしていた。
   再解析（analysis_families_v2/speed_effect_family_v2.csv）では
   点が増える(reveal) だけ 500ms が +7.6pt [+2.2, +13.1]（Holm後 p=0.018）高い。
   混ぜた曲線はそのぶん甘い。→ 視覚は base_anim_ms == 300 のみで当てはめる。
   聴覚は速さの概念が無いので絞らない。

■ ② ぼやけ(blur) の当てはめから **WebKit 描画不全の試行を除く**
   iPhone/iPad/iPod、または Macintosh+Safari（Chrome/Chromium/Edg/Firefox を
   含まない UA）では canvas の ctx.filter が黙って無視され、ぼかしが
   まったくかからない。判定は analyze_families_v2.py と同一（試行単位）。
   他の 3 方式は端末差が無いので除外しない（丸山指示）。
   比較用に「4方式すべて除外」版の当てはめも CSV に出す。

■ ③ 組み合わせの写し方を **その字自身の窓**にする
   旧: s_x(u) = 100·u^k（k は 8 字平均の μ から決めた固定値）。
       字ごとのばらつきを吸収しないので、μ が「ま」3.9% 〜「ぱ」79.9% と
       20 倍以上開く wipe では両端の字が死ぬ。実際、現行表の
       「が」の fade+wipe は提示の全時間で 85.70→86.02（0.3pt）しか動かない。
   新: P(s) = γ + (λ−γ)·logistic((s−μ)/σ) の
         5%点  s5  = μ − 2.944σ
         95%点 s95 = μ + 2.944σ
       を字ごとに求め、u∈[0,1] を [s5, s95] へ写す。
         linear    : s(u) = s5 + (s95−s5)·u
         loglinear : s(u) = s5·(s95/s5)^u
       ⚠ s5/s95 が**実測した水準の範囲**を出るときは実測範囲に丸める（外挿しない）。
       ⚠ 100% まで到達させない（2026-08-27 丸山判断）。音が要求する範囲を
         覆えれば十分で、絵を完成させる必要はない。以前べき乗にしたのは
         「組み合わせが遅い方に飲まれて 100% まで行かない」を避けるためだったが、
         その制約はもう外してよい。

出力（project/data_calib2_live/warp_v3/）
  transfer_warp_v3_linear.json     写し方=線形
  transfer_warp_v3_loglinear.json  写し方=対数線形
  fit_visual_v3.csv                当てはめ（300ms のみ・blur は WebKit 除外）
  fit_audio_v3.csv                 聴覚の当てはめ（実験1のみ・速さの区別なし）
  fit_speed_compare.csv            ① の効き（300 / 500 / 混ぜ の μ・σ・λ）
  fit_webkit_compare.csv           ② の効き（WebKit 除外の有無 × バッチ）
  composite_window.csv             ③ の窓（字×方式の s5/s95、丸めの有無）
  compare_old_new.csv              現行表との対比（μ・σ・進み具合の可動域・実質の測定点数）
  mapping_quality.csv              ③ 写し方だけを取り替えた比較（曲線は固定）
  bootstrap_pooled.csv             8字プールの μ・σ の95%区間（参加者単位）
  build_log_v3.csv                 逆引きの丸め回数（床/天井）と s の範囲

本番ファイル（experiment/transfer_warp.json / transfer_config.js）には**書かない**。

使い方:
    python3 experiment/tools/build_warp_b3.py [--boot 400]

    # 比較用: 速さの効きが有意だった reveal だけ 300ms に絞り、残り3方式は2水準を束ねる
    python3 experiment/tools/build_warp_b3.py --boot 0 --speed-policy reveal300 \
        --out project/data_calib2_live/warp_v3_reveal300
"""
import argparse
import csv
import io
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_calib_full as acf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHARS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
FAMS = ["fade", "reveal", "blur", "wipe"]
PAIRS = [("fade", "blur"), ("fade", "wipe"), ("reveal", "blur"), ("reveal", "wipe")]
FRAME_MS = 1000.0 / 60.0
GEN_SPEED_MS = 300.0        # transfer_config.js visual.calib_speed_probe.generation_level_ms
BASE_ANIM_MS = 300.0        # transfer_config.js visual.base_anim_ms
DURATION_MS = 300.0         # 表の長さ。対照1（等速 t/base_anim_ms）が 1.0 に届くまで要る
N_MAP = 101
L595 = math.log(19.0)       # = 2.9444…（logistic の 5%点/95%点までの距離、σ 単位）

# ぼやけを除外する環境（analyze_families_v2.py と同一の判定）
WEBKIT_FAMILIES = {"blur"}


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------
def load_trials(path):
    d = pd.read_csv(path, low_memory=False)
    for c in ["correct", "is_decoy", "is_filler", "is_test"]:
        if c in d.columns and d[c].dtype == object:
            d[c] = d[c].map({True: True, False: False, "TRUE": True, "FALSE": False,
                             "True": True, "False": False})
    ua = d["ua"].fillna("").astype(str)
    d["webkit"] = (
        ua.str.contains("iPhone|iPad|iPod", regex=True)
        | (ua.str.contains("Macintosh") & ua.str.contains("Safari")
           & ~ua.str.contains("Chrome|Chromium|Edg/|Firefox", regex=True))
    )
    n_test = int((d["is_test"] == True).sum())
    d = d[d["is_test"] != True].copy()
    d["correct_i"] = d["correct"].astype(bool).astype(int)
    d["actual_s_pct"] = (pd.to_numeric(d["actual_s"], errors="coerce") * 100).round(4)
    d["base_anim_ms_i"] = pd.to_numeric(d["base_anim_ms"], errors="coerce")
    d["gate_ms_f"] = pd.to_numeric(d["gate_ms"], errors="coerce")
    print(f"読み込み: {path}  全{len(d) + n_test}行（is_test {n_test}行を除外）")
    return d


def slices(d):
    v = d[d["modality"] == "transfer_visual"].copy()
    a = d[d["modality"] == "transfer_audio"].copy()
    vmain = v[(v["is_decoy"] != True) & (v["is_filler"] != True) & (v["check_kind"].isna())
              & (v["target_char"].isin(CHARS))].copy()
    amain = a[(a["is_decoy"] != True) & (a["check_kind"].isna())
              & (a["target_char"].isin(CHARS))].copy()
    tail = amain["stimulus_id"].fillna("").astype(str).str.split("|").str[-1]
    amain["is_embedded_full"] = (tail == "full") & amain["gate_ms_f"].isna()
    print(f"  視覚 本命8字本命問題 {len(vmain)}行 / {vmain['participant_id'].nunique()}人")
    print(f"  聴覚 はしご {int((~amain['is_embedded_full']).sum())}行 "
          f"/ 埋め込みfull {int(amain['is_embedded_full'].sum())}行")
    return vmain, amain


def gammas(d):
    gv = 1.0 / float(d[d["modality"] == "transfer_visual"]["n_choices"].mode().iloc[0])
    ga = 1.0 / float(d[d["modality"] == "transfer_audio"]["n_choices"].mode().iloc[0])
    print(f"  gamma(下限・固定): 視覚=1/{round(1 / gv)}={gv:.5f} 聴覚=1/{round(1 / ga)}={ga:.5f}")
    return gv, ga


def fit_sub(sub, level_key, gamma, n_starts=8):
    if len(sub) == 0:
        return dict(lam=float("nan"), mu=float("nan"), sigma=float("nan"),
                    converged=False, note="データなし", n_trials=0, n_levels=0)
    t = sub.groupby(level_key)["correct_i"].agg(["sum", "count"])
    return acf.fit_sigmoid(t.index.values.astype(float), t["sum"].values.astype(float),
                           t["count"].values.astype(float), gamma, n_starts=n_starts)


# ---------------------------------------------------------------------------
# 主版の当てはめ（① ②）
# ---------------------------------------------------------------------------
# 方式ごとの「どの速さで当てはめるか」。既定は指示どおり全方式 300ms のみ（①）。
# --speed-policy reveal300 にすると、速さの効きが有意だった reveal だけ 300ms に絞り、
# 残り3方式は2水準を束ねる（試行数が倍になるので当てはめが安定する）。
# ⚠ どちらを採るかは丸山さんの判断。既定は動かさない。
SPEED_BY_FAM = {f: GEN_SPEED_MS for f in FAMS}
_DEFAULT = object()


def visual_rows(vmain, fam, speed=_DEFAULT, webkit_excl=None, phase=None):
    """主版のフィルタ。speed=None で速さを絞らない。"""
    if speed is _DEFAULT:
        speed = SPEED_BY_FAM[fam]
    s = vmain[vmain["family"] == fam]
    if speed is not None:
        s = s[s["base_anim_ms_i"] == speed]
    if phase is not None:
        s = s[s["phase"] == phase]
    excl = (fam in WEBKIT_FAMILIES) if webkit_excl is None else webkit_excl
    if excl:
        s = s[~s["webkit"]]
    return s


def fit_visual_main(vmain, gv, n_starts):
    """字×方式の当てはめ（300ms のみ・blur は WebKit 除外）。"""
    out = {}
    rows = []
    for fam in FAMS:
        base = visual_rows(vmain, fam)
        for ch in CHARS:
            sub = base[base["target_char"] == ch]
            f = fit_sub(sub, "actual_s_pct", gv, n_starts)
            full = sub[sub["progress_pct"] == 100]
            lam_obs = float(full["correct_i"].mean()) if len(full) else float("nan")
            out[(ch, fam)] = dict(g=gv, lam=f["lam"], mu=f["mu"], sg=f["sigma"],
                                  obs=(None if math.isnan(lam_obs) else lam_obs))
            rows.append(dict(char=ch, family=fam, gamma=round(gv, 5),
                             webkit_excluded=(fam in WEBKIT_FAMILIES),
                             speed_ms=(int(SPEED_BY_FAM[fam]) if SPEED_BY_FAM[fam] else "2水準"),
                             lam=f["lam"], mu=f["mu"], sigma=f["sigma"],
                             s5_pct=f["mu"] - L595 * f["sigma"],
                             s95_pct=f["mu"] + L595 * f["sigma"],
                             converged=f["converged"], n_trials=f["n_trials"],
                             n_levels=f["n_levels"],
                             n_participants=int(sub["participant_id"].nunique()),
                             lambda_observed_full=lam_obs, n_full=int(len(full)),
                             note=f["note"]))
    return out, rows


def fit_audio_main(amain, ga, n_starts):
    """聴覚は実験1（phase=calib）にしか無い。速さの概念が無いので絞らない。"""
    ladder = amain[~amain["is_embedded_full"]]
    full = amain[amain["is_embedded_full"]]
    out, rows = {}, []
    for ch in CHARS:
        sub = ladder[ladder["target_char"] == ch]
        f = fit_sub(sub, "gate_ms_f", ga, n_starts)
        fl = full[full["target_char"] == ch]
        lam_obs = float(fl["correct_i"].mean()) if len(fl) else float("nan")
        out[ch] = dict(g=ga, lam=f["lam"], mu=f["mu"], sg=f["sigma"],
                       obs=(None if math.isnan(lam_obs) else lam_obs))
        rows.append(dict(char=ch, gamma=round(ga, 5), lam=f["lam"], mu=f["mu"],
                         sigma=f["sigma"], converged=f["converged"],
                         n_trials=f["n_trials"],
                         n_participants=int(sub["participant_id"].nunique()),
                         lambda_observed_full=lam_obs, n_full=int(len(fl)),
                         note=f["note"]))
    return out, rows


# ---------------------------------------------------------------------------
# ①② の効きを見る比較表
# ---------------------------------------------------------------------------
def speed_compare(vmain, gv, n_starts, out):
    rows = []
    for fam in FAMS:
        excl = fam in WEBKIT_FAMILIES
        for speed in (300.0, 500.0, None):
            for ch in CHARS + ["(8字プール)"]:
                s = visual_rows(vmain, fam, speed=speed, webkit_excl=excl)
                if ch != "(8字プール)":
                    s = s[s["target_char"] == ch]
                f = fit_sub(s, "actual_s_pct", gv, n_starts)
                rows.append(dict(family=fam, char=ch,
                                 speed=("pooled" if speed is None else int(speed)),
                                 webkit_excluded=excl,
                                 lam=f["lam"], mu=f["mu"], sigma=f["sigma"],
                                 n_trials=f["n_trials"], converged=f["converged"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "fit_speed_compare.csv"), index=False)
    p = df[df.char == "(8字プール)"].pivot(index="family", columns="speed",
                                           values=["mu", "sigma", "lam"])
    print("\n[①] 速さで絞ると曲線がどう動くか（8字プール）")
    print(p.round(3).to_string())
    return df


def webkit_compare(vmain, gv, n_starts, out):
    rows = []
    for fam in FAMS:
        for phase in ("calib", "calib2", None):
            for excl in (True, False):
                for speed in (300.0, None):
                    s = visual_rows(vmain, fam, speed=speed, webkit_excl=excl, phase=phase)
                    f = fit_sub(s, "actual_s_pct", gv, n_starts)
                    rows.append(dict(family=fam,
                                     batch=("both" if phase is None else phase),
                                     webkit_excluded=excl,
                                     speed=("pooled" if speed is None else int(speed)),
                                     lam=f["lam"], mu=f["mu"], sigma=f["sigma"],
                                     n_trials=f["n_trials"],
                                     n_webkit_trials=int(s["webkit"].sum()) if not excl else 0,
                                     converged=f["converged"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "fit_webkit_compare.csv"), index=False)
    print("\n[②] ぼやけ: バッチ × WebKit除外 × 速さ（8字プール）")
    print(df[df.family == "blur"][["batch", "webkit_excluded", "speed", "mu", "sigma",
                                   "lam", "n_trials"]].round(3).to_string(index=False))
    return df


def bootstrap_pooled(vmain, gv, nboot, seed, n_starts, out):
    """8字プールの μ・σ の95%区間（参加者単位・主版の絞り込み）。"""
    rng = np.random.default_rng(seed)
    rows = []
    for fam in FAMS:
        base = visual_rows(vmain, fam)
        by = {p: g for p, g in base.groupby("participant_id")}
        pids = sorted(by.keys())
        acc = {"mu": [], "sigma": [], "lam": []}
        for b in range(nboot):
            draw = rng.choice(pids, size=len(pids), replace=True)
            rb = pd.concat([by[p] for p in draw])
            f = fit_sub(rb, "actual_s_pct", gv, n_starts)
            acc["mu"].append(f["mu"]); acc["sigma"].append(f["sigma"]); acc["lam"].append(f["lam"])
        pt = fit_sub(base, "actual_s_pct", gv, 8)

        def q(a):
            x = np.asarray(a, dtype=float)
            if not np.any(~np.isnan(x)):
                return (float("nan"),) * 3
            return tuple(np.nanpercentile(x, [50, 2.5, 97.5]))
        mu_m, mu_lo, mu_hi = q(acc["mu"])
        sg_m, sg_lo, sg_hi = q(acc["sigma"])
        lm_m, lm_lo, lm_hi = q(acc["lam"])
        rows.append(dict(family=fam, webkit_excluded=(fam in WEBKIT_FAMILIES),
                         speed_ms=(int(SPEED_BY_FAM[fam]) if SPEED_BY_FAM[fam] else "2水準"),
                         n_participants=len(pids), n_boot=nboot,
                         mu_point=pt["mu"], mu_median=mu_m, mu_lo95=mu_lo, mu_hi95=mu_hi,
                         sigma_point=pt["sigma"], sigma_median=sg_m,
                         sigma_lo95=sg_lo, sigma_hi95=sg_hi,
                         lambda_point=pt["lam"], lambda_median=lm_m,
                         lambda_lo95=lm_lo, lambda_hi95=lm_hi))
        print(f"  ブートストラップ {fam}: μ={pt['mu']:.2f} "
              f"[{mu_lo:.2f}, {mu_hi:.2f}] σ={pt['sigma']:.2f} [{sg_lo:.2f}, {sg_hi:.2f}]")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "bootstrap_pooled.csv"), index=False)
    return df


# ---------------------------------------------------------------------------
# 表を作る
# ---------------------------------------------------------------------------
def logi(x, p):
    z = -(x - p["mu"]) / max(p["sg"], 1e-9)
    z = max(-60.0, min(60.0, z))
    return p["g"] + (p["lam"] - p["g"]) / (1.0 + math.exp(z))


def qof(p, s):
    y = logi(s, p)
    d = p["lam"] - p["g"]
    if d <= 0:
        return 0.0
    return max(0.0, min(1.0, (y - p["g"]) / d))


def invert(pv, y):
    """V̂(s)=y を s について解く。範囲外は端に丸める。"""
    if pv["lam"] <= pv["g"]:
        return 0.0, "low"
    if y <= pv["g"]:
        return 0.0, "low"
    if y >= pv["lam"]:
        return 100.0, "high"
    s = pv["mu"] + pv["sg"] * math.log((y - pv["g"]) / (pv["lam"] - y))
    if s < 0.0:
        return 0.0, "low"
    if s > 100.0:
        return 100.0, "high"
    return s, None


def window(pv, lo_meas, hi_meas):
    """③ その字自身の窓 [s5, s95]。実測水準の範囲に丸める（外挿しない）。"""
    s5 = pv["mu"] - L595 * pv["sg"]
    s95 = pv["mu"] + L595 * pv["sg"]
    c5 = min(max(s5, lo_meas), hi_meas)
    c95 = min(max(s95, lo_meas), hi_meas)
    if c95 <= c5:                    # 丸めで潰れたら実測範囲いっぱいに開く
        c5, c95 = lo_meas, hi_meas
    return s5, s95, c5, c95


def qmap_window(c5, c95, mode):
    """u（0〜1）→ その方式の進み具合 s（%）。u=0 で s5、u=1 で s95。"""
    out = []
    for i in range(N_MAP):
        u = i / (N_MAP - 1)
        if mode == "loglinear":
            lo = max(c5, 1e-4)
            out.append(lo * (c95 / lo) ** u)
        else:
            out.append(c5 + (c95 - c5) * u)
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


def build(FV, FA, levels, mode):
    """warp 表を作る。mode は組み合わせの写し方（linear / loglinear）。"""
    n = int(math.ceil(DURATION_MS / FRAME_MS)) + 1
    ts = [i * FRAME_MS for i in range(n)]
    tables = {}
    log = []
    winrows = []

    for fam in FAMS:
        tables[fam] = {}
        for ch in CHARS:
            pa = dict(FA[ch]); pa["lam"] = max(pa["lam"], pa["obs"] or 0.0)
            pv = dict(FV[(ch, fam)]); pv["lam"] = max(pv["lam"], pv["obs"] or 0.0)
            targ = [logi(t, pa) for t in ts]
            prop, nlo, nhi = [], 0, 0
            for y in targ:
                s, cl = invert(pv, y)
                nlo += (cl == "low"); nhi += (cl == "high")
                prop.append(s)
            for i in range(1, len(prop)):
                if prop[i] < prop[i - 1]:
                    prop[i] = prop[i - 1]
            b1 = [max(0.0, min(100.0, 100.0 * t / BASE_ANIM_MS)) for t in ts]
            # 対照2: 開始と速さだけ最適に合わせた直線（build_warp_b.py と同じ総当たり）
            best = None
            for ai in range(1, 601):
                a = ai * (100.0 / BASE_ANIM_MS) / 100.0 * 2.0
                for bi in range(-40, 41):
                    b = bi * 0.5
                    e = 0.0
                    for t, y in zip(ts, targ):
                        s = max(0.0, min(100.0, a * t + b))
                        e += (logi(s, pv) - y) ** 2
                    if best is None or e < best[0]:
                        best = (e, a, b)
            _, a, b = best
            b2 = [max(0.0, min(100.0, a * t + b)) for t in ts]
            tables[fam][ch] = {
                "proposed": [round(x / 100.0, 8) for x in prop],
                "baseline1": [round(x / 100.0, 8) for x in b1],
                "baseline2": [round(x / 100.0, 8) for x in b2],
            }
            log.append(dict(mapping=mode, family=fam, char=ch, clip_low=int(nlo),
                            clip_high=int(nhi), s_min=round(min(prop), 4),
                            s_max=round(max(prop), 4), b2_a=round(a, 5), b2_b=round(b, 3)))

    # ---- 組み合わせ ----
    ranges = {}
    for fa, fb in PAIRS:
        key = fa + "+" + fb
        tables[key] = {}
        ranges[key] = {}
        for ch in CHARS:
            pa = dict(FA[ch]); pa["lam"] = max(pa["lam"], pa["obs"] or 0.0)
            pva = dict(FV[(ch, fa)]); pva["lam"] = max(pva["lam"], pva["obs"] or 0.0)
            pvb = dict(FV[(ch, fb)]); pvb["lam"] = max(pvb["lam"], pvb["obs"] or 0.0)
            wa = window(pva, *levels[fa])
            wb = window(pvb, *levels[fb])
            ma = qmap_window(wa[2], wa[3], mode)
            mb = qmap_window(wb[2], wb[3], mode)
            for fam_, w_ in ((fa, wa), (fb, wb)):
                winrows.append(dict(mapping=mode, pair=key, family=fam_, char=ch,
                                    mu=FV[(ch, fam_)]["mu"], sigma=FV[(ch, fam_)]["sg"],
                                    s5_raw=w_[0], s95_raw=w_[1],
                                    level_min_tested=levels[fam_][0],
                                    level_max_tested=levels[fam_][1],
                                    s5_clipped=w_[2], s95_clipped=w_[3],
                                    clipped_low=(w_[0] < levels[fam_][0]),
                                    clipped_high=(w_[1] > levels[fam_][1])))
            lam = min(pva["lam"], pvb["lam"])

            def at(m, u):
                x = max(0.0, min(1.0, u / 100.0)) * (N_MAP - 1)
                i = int(x); j = min(i + 1, N_MAP - 1); f = x - i
                return m[i] * (1 - f) + m[j] * f

            def P(u):
                return pva["g"] + (lam - pva["g"]) * qof(pva, at(ma, u)) * qof(pvb, at(mb, u))

            targ = [logi(t, pa) for t in ts]
            bot, top = P(0.0), P(100.0)
            prop, nlo, nhi = [], 0, 0
            for y in targ:
                if y <= bot:
                    prop.append(0.0); nlo += 1; continue
                if y >= top:
                    prop.append(100.0); nhi += 1; continue
                lo_, hi_ = 0.0, 100.0
                for _ in range(50):
                    mid = (lo_ + hi_) / 2
                    if P(mid) < y:
                        lo_ = mid
                    else:
                        hi_ = mid
                prop.append((lo_ + hi_) / 2)
            for i in range(1, len(prop)):
                if prop[i] < prop[i - 1]:
                    prop[i] = prop[i - 1]
            b1 = [max(0.0, min(100.0, 100.0 * t / BASE_ANIM_MS)) for t in ts]
            s0, s1 = prop[0], prop[-1]
            b2 = [max(0.0, min(100.0, s0 + (s1 - s0) * i / max(1, len(ts) - 1)))
                  for i in range(len(ts))]
            tables[key][ch] = {
                "proposed": [round(x / 100.0, 8) for x in prop],
                "baseline1": [round(x / 100.0, 8) for x in b1],
                "baseline2": [round(x / 100.0, 8) for x in b2],
            }
            ranges[key][ch] = {"a": [round(x, 4) for x in ma],
                               "b": [round(x, 4) for x in mb]}
            log.append(dict(mapping=mode, family=key, char=ch, clip_low=int(nlo),
                            clip_high=int(nhi), s_min=round(min(prop), 4),
                            s_max=round(max(prop), 4), b2_a=0, b2_b=0))
    return tables, ranges, log, winrows


# ---------------------------------------------------------------------------
# 対比表
# ---------------------------------------------------------------------------
def series_at(tbl, fam, ch, cond, ms):
    """warp 表の数値列を transfer.js と同じ線形補間で読む。"""
    arr = tbl["tables"][fam][ch][cond]
    fr = tbl["frame_ms"]
    x = max(0.0, ms / fr)
    i = int(math.floor(x))
    if i >= len(arr) - 1:
        return arr[-1]
    f = x - i
    return arr[i] * (1 - f) + arr[i + 1] * f


def span_at_gates(tbl, fam, ch, gates, cond="proposed"):
    vals = [series_at(tbl, fam, ch, cond, g) for g in gates]
    return min(vals), max(vals), max(vals) - min(vals)


def n_levels_at_gates(tbl, fam, ch, gates, cond="proposed", eps=0.01):
    """打ち切り時点で**実質いくつ別の絵**が出るか（進み具合が1pt以上離れた点の数）。
    可動域が広くても最後の1点だけで稼いでいれば、測定点としては使えない。"""
    vals = [series_at(tbl, fam, ch, cond, g) for g in gates]
    n = 1
    for i in range(1, len(vals)):
        if vals[i] - vals[i - 1] > eps:
            n += 1
    return n


# 現行の固定指数（transfer_config.js visual.composite_axis / build_warp_b2.py と同じ値）
K_FIXED_CURRENT = {"fade": 5.9302, "reveal": 5.6221, "blur": 1.0997, "wipe": 1.5576}


def mapping_quality(FV, levels, out):
    """③ 写し方だけを取り替えて比べる（曲線は新しい当てはめで固定）。
    u∈[0,1] を等間隔に刻んだとき、組み合わせの識別の進み具合 q が
      ・どこからどこまで動くか（u5〜u95）
      ・u に対してどれだけまっすぐ伸びるか（|q−u| の平均。小さいほど刻みやすい）
    を見る。"""
    us = [i / 1000.0 for i in range(1001)]
    rows = []
    for fa, fb in PAIRS:
        name = fa + "+" + fb
        for ch in CHARS:
            pva = dict(FV[(ch, fa)]); pvb = dict(FV[(ch, fb)])
            wa = window(pva, *levels[fa]); wb = window(pvb, *levels[fb])
            variants = {
                "現行(べき乗・8字平均のk)": ([100.0 * u ** K_FIXED_CURRENT[fa] for u in us],
                                             [100.0 * u ** K_FIXED_CURRENT[fb] for u in us]),
                "linear(字ごとの窓)": ([wa[2] + (wa[3] - wa[2]) * u for u in us],
                                       [wb[2] + (wb[3] - wb[2]) * u for u in us]),
                "loglinear(字ごとの窓)": ([max(wa[2], 1e-4) * (wa[3] / max(wa[2], 1e-4)) ** u for u in us],
                                          [max(wb[2], 1e-4) * (wb[3] / max(wb[2], 1e-4)) ** u for u in us]),
            }
            for vname, (sa, sb) in variants.items():
                q = [qof(pva, x) * qof(pvb, y) for x, y in zip(sa, sb)]
                # ⚠ 写し方によって届く天井が違う（新しい写しは 100% へ行かないので
                #   q(1)≈0.90 で頭打ち）。そのままだと「95%に届かない＝幅なし」に
                #   なってしまうので、**その写し方自身が届く範囲**に正規化して比べる。
                q0, q1 = q[0], q[-1]
                rng = max(q1 - q0, 1e-9)
                qn = [(v - q0) / rng for v in q]
                u5 = next((u for u, v in zip(us, qn) if v >= 0.05), float("nan"))
                u95 = next((u for u, v in zip(us, qn) if v >= 0.95), float("nan"))
                mae = sum(abs(v - u) for v, u in zip(qn, us)) / len(us)
                rows.append(dict(pair=name, char=ch, mapping=vname, u5=u5, u95=u95,
                                 u_span=(u95 - u5), linearity_mae=mae,
                                 q_at_u0=q0, q_at_u1=q1))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "mapping_quality.csv"), index=False)
    agg = df.groupby("mapping").agg(
        u_span_median=("u_span", "median"), u_span_min=("u_span", "min"),
        n_no_span=("u_span", lambda s: int(s.isna().sum())),
        linearity_mae_median=("linearity_mae", "median"),
        q_at_u1_median=("q_at_u1", "median"))
    print("\n[③] 写し方だけを取り替えた比較（曲線は新しい当てはめで固定・8字×4組の要約）")
    print(agg.round(4).to_string())
    return df


def load_old_fits(path):
    F = {}
    for r in csv.DictReader(io.open(path, encoding="utf-8-sig")):
        if r["modality"] != "visual":
            continue
        F[(r["char"], r["family"])] = (float(r["mu"]), float(r["sigma"]))
    return F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default=os.path.join(ROOT, "project/data_calib2_live/transfer_trials.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "project/data_calib2_live/warp_v3"))
    ap.add_argument("--old", default=os.path.join(ROOT, "experiment/transfer_warp.json"))
    ap.add_argument("--fit-starts", type=int, default=8)
    ap.add_argument("--boot", type=int, default=400)
    ap.add_argument("--boot-starts", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260827)
    ap.add_argument("--speed-policy", choices=["all300", "reveal300"], default="all300",
                    help="all300(既定): 4方式とも 300ms のみ。"
                         "reveal300: 速さの効きが有意だった reveal だけ 300ms、"
                         "残り3方式は2水準を束ねる（比較用）")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.speed_policy == "reveal300":
        for f in FAMS:
            SPEED_BY_FAM[f] = GEN_SPEED_MS if f == "reveal" else None
    print(f"  速さの絞り方: " + " ".join(
        f"{f}={'300ms' if SPEED_BY_FAM[f] else '2水準'}" for f in FAMS))

    d = load_trials(a.inp)
    vmain, amain = slices(d)
    gv, ga = gammas(d)

    # ---- 当てはめ（主版） ----
    FV, vrows = fit_visual_main(vmain, gv, a.fit_starts)
    FA, arows = fit_audio_main(amain, ga, a.fit_starts)
    pd.DataFrame(vrows).to_csv(os.path.join(a.out, "fit_visual_v3.csv"), index=False)
    pd.DataFrame(arows).to_csv(os.path.join(a.out, "fit_audio_v3.csv"), index=False)
    print("  書き出し: fit_visual_v3.csv, fit_audio_v3.csv")

    # ---- ①② の効き ----
    speed_compare(vmain, gv, a.fit_starts, a.out)
    webkit_compare(vmain, gv, a.fit_starts, a.out)
    if a.boot > 0:
        print(f"\n[①②] 8字プールのブートストラップ（{a.boot}回・参加者単位）")
        bootstrap_pooled(vmain, gv, a.boot, a.seed, a.boot_starts, a.out)

    # ---- 実測した水準の範囲（外挿しないための丸め先） ----
    levels = {}
    for fam in FAMS:
        s = visual_rows(vmain, fam)["actual_s_pct"].dropna()
        levels[fam] = (float(s.min()), float(s.max()))
    print("\n[③] 実測した水準の範囲（この外へは丸める）")
    for fam in FAMS:
        print(f"     {fam:<7}{levels[fam][0]:>8.2f}% 〜 {levels[fam][1]:>7.2f}%")

    mapping_quality(FV, levels, a.out)

    # ---- 表を作る ----
    built = {}
    allwin, alllog = [], []
    for mode in ("linear", "loglinear"):
        tables, ranges, log, win = build(FV, FA, levels, mode)
        doc = {"generated_by": "experiment/tools/build_warp_b3.py",
               "frame_ms": round(FRAME_MS, 6),   # ⚠ 桁を削ると枠のあいだの補間がずれ、check_warp_playback.js が落ちる
               "duration_ms": DURATION_MS,
               "base_anim_ms": BASE_ANIM_MS,
               "meta": {"space": "rawp", "made": "2026-08-27", "chars": CHARS,
                        "visual_source": "calib+calib2 両バッチ / 速さの絞り方: " + ", ".join(
                            f"{f}={'300ms' if SPEED_BY_FAM[f] else '2水準'}" for f in FAMS),
                        "webkit_excluded_families": sorted(WEBKIT_FAMILIES),
                        "audio_source": "実験1(phase=calib)・速さの区別なし",
                        "composite_mapping": mode,
                        "composite_window": "s5=μ−2.944σ, s95=μ+2.944σ（実測水準の範囲に丸め）",
                        "note": "本番反映は未定。組み合わせは字ごとの窓なので "
                                "transfer.js の compositeSplit が composite_map を先に読むこと。"},
               "composite_map": ranges, "composite_map_n": N_MAP,
               "tables": tables}
        p = os.path.join(a.out, f"transfer_warp_v3_{mode}.json")
        json.dump(doc, io.open(p, "w", encoding="utf-8"), ensure_ascii=False,
                  separators=(",", ":"))
        print(f"  書き出し: {os.path.basename(p)} ({os.path.getsize(p)//1024} KB)")
        built[mode] = doc
        allwin += win
        alllog += log
    pd.DataFrame(allwin).to_csv(os.path.join(a.out, "composite_window.csv"), index=False)
    pd.DataFrame(alllog).to_csv(os.path.join(a.out, "build_log_v3.csv"), index=False)

    # ---- 対比表 ----
    old = json.load(io.open(a.old, encoding="utf-8"))
    oldfit2 = load_old_fits(os.path.join(ROOT,
                            "project/data_calib2_live/warp_new/fit_logistic_calib2.csv"))
    oldfit1 = load_old_fits(os.path.join(ROOT,
                            "project/data_calib2_live/warp_new/fit_logistic_calib1.csv"))
    gates_cfg = {
        "_default": [20, 40, 60, 80, 110, 150, 220],
        "あ": [10, 20, 30, 35, 50, 65, 90], "か": [10, 20, 25, 35, 45, 60, 85],
        "が": [10, 20, 25, 35, 45, 60, 85], "ぱ": [10, 15, 25, 30, 40, 50, 70],
        "し": [10, 20, 30, 35, 40, 50, 60], "つ": [10, 20, 30, 35, 50, 65, 85],
        "ま": [10, 25, 35, 50, 65, 85, 125], "ら": [10, 25, 35, 50, 65, 85, 110],
    }
    rows = []
    for fam in FAMS + [x + "+" + y for x, y in PAIRS]:
        for ch in CHARS:
            g = gates_cfg.get(ch, gates_cfg["_default"])
            # 曲線のパラメータ（単体のみ。組み合わせは2方式の合成なので空欄）
            if fam in FAMS:
                mo, so = (oldfit1 if fam == "blur" else oldfit2)[(ch, fam)]
                mn, sn = FV[(ch, fam)]["mu"], FV[(ch, fam)]["sg"]
            else:
                mo = so = mn = sn = float("nan")
            o = span_at_gates(old, fam, ch, g)
            l = span_at_gates(built["linear"], fam, ch, g)
            g2 = span_at_gates(built["loglinear"], fam, ch, g)
            rows.append(dict(family=fam, char=ch,
                             mu_old=mo, sigma_old=so, mu_new=mn, sigma_new=sn,
                             mu_diff=mn - mo, sigma_diff=sn - so,
                             s_min_old=o[0], s_max_old=o[1], span_pt_old=o[2] * 100,
                             s_min_lin=l[0], s_max_lin=l[1], span_pt_lin=l[2] * 100,
                             s_min_log=g2[0], s_max_log=g2[1], span_pt_log=g2[2] * 100,
                             n_levels_old=n_levels_at_gates(old, fam, ch, g),
                             n_levels_lin=n_levels_at_gates(built["linear"], fam, ch, g),
                             n_levels_log=n_levels_at_gates(built["loglinear"], fam, ch, g),
                             gates_ms="|".join(str(x) for x in g)))
    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(os.path.join(a.out, "compare_old_new.csv"), index=False)
    print("  書き出し: compare_old_new.csv, composite_window.csv, build_log_v3.csv")

    LAB = {"fade": "うすい", "reveal": "点", "blur": "ぼやけ", "wipe": "端から"}
    print("\n[対比] 提示時間内で進み具合がどれだけ動くか（ポイント。0=測定不能）")
    print(f"     {'方式':<14}{'字':<3}{'現行':>8}{'線形':>8}{'対数線形':>10}")
    for _, r in cmp_df.iterrows():
        nm = "×".join(LAB.get(x, x) for x in r["family"].split("+"))
        print(f"     {nm:<16}{r['char']:<3}{r['span_pt_old']:>8.2f}"
              f"{r['span_pt_lin']:>8.2f}{r['span_pt_log']:>10.2f}")

    print("\n[対比] 単体の曲線（μ・σ）")
    print(f"     {'方式':<10}{'字':<3}{'μ旧':>8}{'μ新':>8}{'差':>8}{'σ旧':>8}{'σ新':>8}")
    for _, r in cmp_df[cmp_df.family.isin(FAMS)].iterrows():
        print(f"     {LAB[r['family']]:<12}{r['char']:<3}{r['mu_old']:>8.2f}{r['mu_new']:>8.2f}"
              f"{r['mu_diff']:>+8.2f}{r['sigma_old']:>8.2f}{r['sigma_new']:>8.2f}")

    comp = cmp_df[cmp_df.family.str.contains(r"\+")]
    sing = cmp_df[cmp_df.family.isin(FAMS)]
    print("\n[まとめ] 可動域(pt) と 実質の測定点数（7つの打ち切り時点のうち別の絵になる数）")
    print(f"     {'':<12}{'可動域中央':>10}{'最小':>8}{'1pt未満':>9}{'点数中央':>9}{'点数最小':>9}")
    for lab, sub in (("組み合わせ32", comp), ("単体32", sing), ("全64", cmp_df)):
        for tag, sc, nc in (("現行", "span_pt_old", "n_levels_old"),
                            ("線形", "span_pt_lin", "n_levels_lin"),
                            ("対数線形", "span_pt_log", "n_levels_log")):
            print(f"     {lab + '/' + tag:<14}{sub[sc].median():>10.2f}{sub[sc].min():>8.2f}"
                  f"{int((sub[sc] < 1.0).sum()):>9}{sub[nc].median():>9.1f}{sub[nc].min():>9}")
    print(f"\n完了: {a.out}")


if __name__ == "__main__":
    main()
