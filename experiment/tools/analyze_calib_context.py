#!/usr/bin/env python3
"""
較正フェーズ(transfer_trials.csv) 追加解析: まだ使っていない観点から
==================================================================

analyze_calib_full.py / analyze_calib_deep.py で使っていない列を対象にする。
本命8字(あ・か・が・ぱ・し・つ・ま・ら)の字ごと分析は上記2本がすでにやっているので、
ここでは基本的に「字を越えてプールした」比較を主軸に置く
(視覚は方式(family)ごとの違いが大きいので、familyだけは崩さずに保つ)。

見る観点(指示書の①~⑤に対応):
  ① 参加者の属性(年齢層・読み書き/聞き取りの支障) -- transfer_post_survey行にしかない列
  ② 提示の乱れ(視覚のみ): endpoint_clamped, max_frame_gap_ms, refresh_hz, 名目値との実測ずれ
  ③ 端末と環境: touch(スマホ/PC), audio_device(無線イヤホン等), audio_check_misses
  ④ 学習・順序の効果: trial_index の前半/後半, resume_count
  ⑤ 回答の中身: resp_in_frequent_set が後半で上がっていないか(出題範囲の学習)

出力(既定 project/data_calib_20260825/analysis_context/): 下記CSV一式。
  ctx_participant_attributes.csv        参加者ごとの属性一覧(年齢層・支障・端末など)
  ctx1_age_band_fit.csv                 年齢層別の A(t)/V(s) (mu, lambda)
  ctx1_hear_difficulty_fit.csv          聞き取り支障の有無別
  ctx1_hear_difficulty_exclusion.csv    「多少ある」34人を除いた場合の比較(cut)
  ctx1_read_difficulty_fit.csv          読み支障の有無別(4人のみ、参考)
  ctx2_endpoint_clamped.csv             止められなかった9%を除いた場合の比較(cut)
  ctx2_frame_gap.csv                    描画が飛んだ試行を除いた場合の比較(cut, 閾値2通り)
  ctx2_refresh_hz_band.csv              リフレッシュレート帯ごとの比較
  ctx2_progress_deviation.csv           狙った水準と実測のずれの分布(方式×水準)
  ctx3_touch_fit.csv                    スマホ/PC別
  ctx3_audio_device_fit.csv             音の出し方(スピーカー/有線/無線)別(聴覚のみ)
  ctx3_audio_check_miss.csv             音の関門でつまずいた人の その後の成績(聴覚のみ)
  ctx4_trial_progress_trend.csv         セッション内の位置(前半→後半)ごとの正答率
  ctx4_resume_cut.csv                   再開の影響(試行単位/参加者単位の除外)
  ctx5_frequent_set_trend.csv           出題範囲の学習の兆候(resp_in_frequent_set の推移)

HTMLレポート: project/data_calib_20260825/context_report.html

使い方
------
  python3 experiment/tools/analyze_calib_context.py

制約
----
  ・is_test が真の行は外す。modality は transfer_audio/transfer_visual (+集計のため
    transfer_post_survey も属性抽出にだけ使う)。post_survey・awareness の行を
    本題の試行に混ぜない。
  ・analyze_calib_full.py / analyze_calib_deep.py は変更しない。読み込み・当てはめの
    共通処理は analyze_calib_full から import して再利用する。
  ・数値は全部このスクリプトが計算する(ハードコード禁止)。人数が少ない比較は
    必ず人数を併記し、目安として20人未満は「参考」と明記する。
  ・git commit・push はしない。
"""
import argparse
import base64
import csv
import io
import os
import sys
from collections import Counter, defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze_calib_full as base_mod  # noqa: E402  (既存スクリプトの再利用。中身は変更しない)

DATA_DIR_DEFAULT = os.path.normpath(os.path.join(HERE, "..", "..", "project", "data_calib_20260825"))
TRIALS_CSV_DEFAULT = os.path.join(DATA_DIR_DEFAULT, "transfer_trials.csv")
OUT_DIR_DEFAULT = os.path.join(DATA_DIR_DEFAULT, "analysis_context")
OUT_HTML_DEFAULT = os.path.join(DATA_DIR_DEFAULT, "context_report.html")

TARGET_CHARS = base_mod.TARGET_CHARS
FAMILIES_ORDER = ["fade", "reveal", "blur", "wipe"]
FAMILY_LABEL = {"fade": "fade(うすい→濃い)", "reveal": "reveal(点が増える)",
                "blur": "blur(ぼやけ→はっきり)", "wipe": "wipe(端から現れる)"}

SMALL_N_WARN = 20  # 参加者数がこれ未満なら note に「参考」を付ける目安


# ---------------------------------------------------------------------------
# 読み込み・下ごしらえ
# ---------------------------------------------------------------------------
def load_and_prepare(path):
    """
    transfer_trials.csv を読み、
      raw          : is_test以外はそのまま残した全行(post_survey等も含む)
      base         : is_test・対象外モダリティ(post_survey/awareness)を除いた行
      main_all     : 本命8字の本命問題(is_decoy偽・check_kind空・対象8字)
      noncheck_all : 確認問題(check_kind有)を除いた通常の較正試行(本命+まぎれ字)
                     -- ⑤の「出題範囲に気づいたか」はまぎれ字も込みで見るのでこちらを使う
    のほか、参加者属性(年齢層・支障)を全行にマージした状態を返す。
    """
    raw = base_mod.load(path)
    raw = base_mod.normalize(raw)

    # --- 参加者属性: アンケートは modality=transfer_post_survey の行1つに入っている ---
    # (is_testが真の行だけ先に外す。base_filterはmodalityも絞ってしまうのでここでは使わない)
    survey_rows = [r for r in raw if (not r["is_test_b"]) and r.get("modality") == "transfer_post_survey"]
    attrs = {}
    for r in survey_rows:
        attrs[r["participant_id"]] = dict(
            age_band=(r.get("age_band") or "").strip(),
            read_difficulty=(r.get("read_difficulty") or "").strip(),
            hear_difficulty=(r.get("hear_difficulty") or "").strip(),
        )
    print(f"  参加者属性(アンケート回答, is_test除く): {len(survey_rows)}人分")

    for r in raw:
        a = attrs.get(r["participant_id"], {})
        r["age_band_p"] = a.get("age_band", "")
        r["read_difficulty_p"] = a.get("read_difficulty", "")
        r["hear_difficulty_p"] = a.get("hear_difficulty", "")

    base = base_mod.base_filter(raw)  # is_test・対象外modalityを除去(post_survey/awarenessもここで落ちる)

    for r in base:
        if r["modality_g"] == "visual":
            r["actual_s_pct"] = round(r["actual_s"] * 100, 4) if r["actual_s"] is not None else None
        r["endpoint_clamped_b"] = None
        if r.get("endpoint_clamped") not in (None, ""):
            r["endpoint_clamped_b"] = base_mod.truthy(r["endpoint_clamped"])
        r["max_frame_gap_ms"] = base_mod.numf(r.get("max_frame_gap_ms"))
        r["audio_check_misses"] = base_mod.numf(r.get("audio_check_misses"))
        r["resp_in_target_set_b"] = base_mod.truthy(r.get("resp_in_target_set"))
        r["resp_in_frequent_set_b"] = base_mod.truthy(r.get("resp_in_frequent_set"))
        r["touch_b"] = base_mod.truthy(r.get("touch"))
        r["trial_index_i"] = int(r["trial_index"]) if str(r.get("trial_index") or "").strip() else None

    main_all = base_mod.main_target_rows(base)
    noncheck_all = [r for r in base if not r["check_kind"]]  # 本命+まぎれ字。確認問題A/Cは除く

    return raw, base, main_all, noncheck_all, attrs


# ---------------------------------------------------------------------------
# シグモイド当てはめの共通ラッパ(字を越えてプールし、視覚はfamily別に保つ)
# ---------------------------------------------------------------------------
def fit_and_pack(sub_rows, level_key, gamma, n_starts=6):
    xs, ks, ns = base_mod.aggregate_levels(sub_rows, level_key)
    fit = base_mod.fit_sigmoid(xs, ks, ns, gamma, n_starts=n_starts)
    n_part = len({r["participant_id"] for r in sub_rows})
    n = len(sub_rows)
    acc = (sum(1 for r in sub_rows if r["correct_b"]) / n) if n else float("nan")
    note = fit["note"]
    if 0 < n_part < SMALL_N_WARN:
        note = (note + ";" if note else "") + f"参考(参加者{n_part}人<{SMALL_N_WARN})"
    return dict(n_trials=fit["n_trials"], n_participants=n_part,
                accuracy_overall=round(acc, 4) if n else "",
                mu=base_mod._fmt(fit["mu"]), lam=base_mod._fmt(fit["lam"]),
                converged=fit["converged"], note=note)


def build_cut_records(rows_audio_main, rows_visual_main, cuts, gamma_audio, gamma_visual, n_starts=6,
                       families=None, pool_family=True):
    """
    cuts: {cut名: filter関数(row)->bool} の辞書。cut名ごとに
      - 聴覚: 字を越えてプールした1本
      - 視覚: family別(既定 fade/reveal/blur/wipe) + 全family込み("ALL")
    のfitを作る。visual_axisは実測(actual_s_pct)固定(analyze_calib_fullの既定と揃える)。
    """
    families = families or FAMILIES_ORDER
    records = []
    for name, filt in cuts.items():
        ra = [r for r in rows_audio_main if (not r["is_embedded_full"]) and filt(r)]
        rec = fit_and_pack(ra, "gate_ms", gamma_audio, n_starts)
        rec.update(cut=name, modality="audio", family="")
        records.append(rec)

        rv_all = [r for r in rows_visual_main if filt(r)]
        fam_list = (families + ["ALL"]) if pool_family else families
        for fam in fam_list:
            rv = rv_all if fam == "ALL" else [r for r in rv_all if r["family"] == fam]
            rec = fit_and_pack(rv, "actual_s_pct", gamma_visual, n_starts)
            rec.update(cut=name, modality="visual", family=fam)
            records.append(rec)
    return records


def write_records(path, records, first_col="cut"):
    """
    records は build_cut_records が作る辞書で、グループ名は常にキー "cut" に入っている。
    first_col はCSVの見出し名を差し替えるためだけの引数(例: "age_band")で、
    値の取り出し元は常に "cut"。ここを間違えて first_col をそのままキーとして
    引いてしまうと(record に first_col という名前のキー自体が無いため)全部空欄に
    なってしまうので、必ず "cut" から値を取る。
    """
    cols = [first_col, "modality", "family", "n_trials", "n_participants",
            "accuracy_overall", "mu", "lam", "converged", "note"]
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in records:
            first_val = r.get("cut", r.get(first_col, ""))
            w.writerow([first_val] + [r.get(c, "") for c in cols[1:]])


# ---------------------------------------------------------------------------
# ① 参加者の属性
# ---------------------------------------------------------------------------
AGE_ORDER = ["20代", "30代", "40代", "50代", "60代", "70代"]


def section1_participant_attrs(rows_audio_main, rows_visual_main, gamma_audio, gamma_visual, n_starts, out_dir):
    # 年齢層別
    ages_present = [a for a in AGE_ORDER if any(r["age_band_p"] == a for r in rows_audio_main + rows_visual_main)]
    cuts = {a: (lambda r, a=a: r["age_band_p"] == a) for a in ages_present}
    cuts["(未回答)"] = lambda r: r["age_band_p"] == ""
    recs = build_cut_records(rows_audio_main, rows_visual_main, cuts, gamma_audio, gamma_visual, n_starts)
    for r in recs:
        r["cut"] = r["cut"]  # 名前はそのままage_band値
    write_records(os.path.join(out_dir, "ctx1_age_band_fit.csv"), recs, first_col="age_band")

    # 聞き取り支障の有無別(カテゴリごと)
    hear_cats = sorted({r["hear_difficulty_p"] for r in rows_audio_main + rows_visual_main if r["hear_difficulty_p"]})
    cuts_h = {c: (lambda r, c=c: r["hear_difficulty_p"] == c) for c in hear_cats}
    cuts_h["(未回答)"] = lambda r: r["hear_difficulty_p"] == ""
    recs_h = build_cut_records(rows_audio_main, rows_visual_main, cuts_h, gamma_audio, gamma_visual, n_starts)
    write_records(os.path.join(out_dir, "ctx1_hear_difficulty_fit.csv"), recs_h, first_col="hear_difficulty")

    # 聞き取り「多少ある」34人を除いた場合の比較(baseline vs exclude)
    cuts_hx = {
        "baseline_全員": lambda r: True,
        "多少ある人を除外": lambda r: r["hear_difficulty_p"] != "多少ある（聞き返すことがある等）",
    }
    recs_hx = build_cut_records(rows_audio_main, rows_visual_main, cuts_hx, gamma_audio, gamma_visual, n_starts)
    write_records(os.path.join(out_dir, "ctx1_hear_difficulty_exclusion.csv"), recs_hx, first_col="cut")

    # 読み支障(4人のみ、参考)
    read_cats = sorted({r["read_difficulty_p"] for r in rows_audio_main + rows_visual_main if r["read_difficulty_p"]})
    cuts_r = {c: (lambda r, c=c: r["read_difficulty_p"] == c) for c in read_cats}
    cuts_r["(未回答)"] = lambda r: r["read_difficulty_p"] == ""
    recs_r = build_cut_records(rows_audio_main, rows_visual_main, cuts_r, gamma_audio, gamma_visual, n_starts)
    write_records(os.path.join(out_dir, "ctx1_read_difficulty_fit.csv"), recs_r, first_col="read_difficulty")

    return recs, recs_h, recs_hx, recs_r


def write_participant_attributes(path, base_rows, attrs):
    """参加者ごとの属性一覧(年齢層・支障・端末など)。分析の前提を確認できるように出す。"""
    by_pid = defaultdict(list)
    for r in base_rows:
        by_pid[r["participant_id"]].append(r)
    rows_out = []
    for pid, rs in sorted(by_pid.items()):
        group = rs[0].get("group", "")
        a = attrs.get(pid, {})
        dev_vals = [r.get("audio_device") for r in rs if r.get("audio_device")]
        device = Counter(dev_vals).most_common(1)[0][0] if dev_vals else ""
        touch_vals = {r["touch_b"] for r in rs}
        touch = "混在" if len(touch_vals) > 1 else (str(next(iter(touch_vals))) if touch_vals else "")
        hz_vals = [r["refresh_hz"] for r in rs if r["refresh_hz"] is not None]
        hz_med = round(float(np.median(hz_vals)), 1) if hz_vals else ""
        miss_vals = [r["audio_check_misses"] for r in rs if r["audio_check_misses"] is not None]
        miss = int(miss_vals[0]) if miss_vals else ""
        rows_out.append(dict(participant_id=pid, group=group, n_trials=len(rs),
                              age_band=a.get("age_band", ""), read_difficulty=a.get("read_difficulty", ""),
                              hear_difficulty=a.get("hear_difficulty", ""), audio_device=device,
                              touch=touch, refresh_hz_median=hz_med, audio_check_misses=miss))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        cols = list(rows_out[0].keys()) if rows_out else []
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    return rows_out


# ---------------------------------------------------------------------------
# ② 提示の乱れ(視覚のみ)
# ---------------------------------------------------------------------------
def section2_presentation_noise(rows_audio_main, rows_visual_main, rows_visual_all,
                                 gamma_audio, gamma_visual, n_starts, out_dir):
    # endpoint_clamped: 止められなかった(0)行を除く。
    #
    # ⚠ まず check_kind × endpoint_clamped の関係を確認する。本命8字の本命問題(rows_visual_main)
    # だけを見ると全部 endpoint_clamped=1 になっており、baseline と「除外」後で数字が一致してしまう
    # (下のクロス集計参照)。これはバグではなく、endpoint_clamped=0 が確認問題A(check_kind="full",
    # 進み具合100%で最後まで見せる問題)だけに現れる値だから。100%まで見せる問題には「途中で止める
    # 狙った値」という概念自体が無いため、clampできた/できなかったの判定が意味を持たず0になっている
    # とみられる。つまり止められなかった9%は較正曲線の当てはめに使うデータ(check_kind=空の通常試行)
    # には1件も混ざっていない。以下の cut 比較はこの事実を数値で示すために残す。
    ct = Counter((r["check_kind"] or "(通常試行)", r["endpoint_clamped"]) for r in rows_visual_all)
    with io.open(os.path.join(out_dir, "ctx2_endpoint_clamped_crosstab.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["check_kind", "endpoint_clamped", "n"])
        for (ck, ec), n in sorted(ct.items()):
            w.writerow([ck, ec, n])

    cuts_ec = {
        "baseline_全部": lambda r: True,
        "clamped以外(狙った値で止まらなかった行)を除外": lambda r: r["endpoint_clamped_b"] is not False,
    }
    recs_ec = build_cut_records(rows_audio_main, rows_visual_main, cuts_ec, gamma_audio, gamma_visual, n_starts,
                                 pool_family=True)
    recs_ec = [r for r in recs_ec if r["modality"] == "visual"]  # 聴覚には無い概念なので視覚だけ残す
    write_records(os.path.join(out_dir, "ctx2_endpoint_clamped.csv"), recs_ec, first_col="cut")

    # max_frame_gap_ms: 描画が飛んだ試行を除く(閾値2通り: 33ms≈2フレーム, 50ms)
    cuts_fg = {"baseline_全部": lambda r: True}
    for th in (33.0, 50.0):
        cuts_fg[f"gap>{th:.0f}msの試行を除外"] = (
            lambda r, th=th: r["max_frame_gap_ms"] is None or r["max_frame_gap_ms"] <= th)
    recs_fg = build_cut_records(rows_audio_main, rows_visual_main, cuts_fg, gamma_audio, gamma_visual, n_starts)
    recs_fg = [r for r in recs_fg if r["modality"] == "visual"]
    write_records(os.path.join(out_dir, "ctx2_frame_gap.csv"), recs_fg, first_col="cut")

    # refresh_hz帯ごと(視覚のみ)。0Hzや200Hz超は計測異常の疑いがあるため別枠にする。
    def hz_band(r):
        hz = r["refresh_hz"]
        if hz is None or hz <= 0:
            return "計測異常(0以下)"
        if hz < 45:
            return "45未満(低フレームレート機)"
        if hz <= 65:
            return "45-65(標準的な画面)"
        if hz <= 100:
            return "65-100"
        return "100超(異常値の疑い)"
    bands_present = sorted({hz_band(r) for r in rows_visual_main})
    cuts_hz = {b: (lambda r, b=b: hz_band(r) == b) for b in bands_present}
    recs_hz = build_cut_records([], rows_visual_main, cuts_hz, gamma_audio, gamma_visual, n_starts)
    recs_hz = [r for r in recs_hz if r["modality"] == "visual"]
    write_records(os.path.join(out_dir, "ctx2_refresh_hz_band.csv"), recs_hz, first_col="refresh_hz_band")

    # 狙った水準(progress_pct)と実測(actual_s*100)のずれ
    dev_rows = []
    by_key = defaultdict(list)
    for r in rows_visual_main:
        if r["progress_pct"] is None or r["actual_s"] is None:
            continue
        dev = r["actual_s"] * 100 - r["progress_pct"]
        by_key[(r["family"], r["progress_pct"])].append(dev)
        by_key[(r["family"], "ALL")].append(dev)
    for (fam, lv), devs in sorted(by_key.items(), key=lambda kv: (kv[0][0], 1 if kv[0][1] == "ALL" else 0,
                                                                    kv[0][1] if kv[0][1] != "ALL" else 0)):
        arr = np.array(devs, dtype=float)
        dev_rows.append(dict(family=fam, progress_pct_level=lv, n=len(arr),
                              mean_dev_pt=round(float(np.mean(arr)), 3),
                              sd_dev_pt=round(float(np.std(arr, ddof=1)), 3) if len(arr) > 1 else "",
                              median_dev_pt=round(float(np.median(arr)), 3),
                              p05_dev_pt=round(float(np.percentile(arr, 5)), 3),
                              p95_dev_pt=round(float(np.percentile(arr, 95)), 3)))
    with io.open(os.path.join(out_dir, "ctx2_progress_deviation.csv"), "w", encoding="utf-8", newline="") as f:
        cols = list(dev_rows[0].keys())
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in dev_rows:
            w.writerow(r)

    return recs_ec, recs_fg, recs_hz, dev_rows, ct


# ---------------------------------------------------------------------------
# ③ 端末と環境
# ---------------------------------------------------------------------------
def section3_device_env(rows_audio_main, rows_visual_main, gamma_audio, gamma_visual, n_starts, out_dir):
    # スマホ/PC
    cuts_t = {"スマホ(touch)": lambda r: r["touch_b"] is True, "PC等(touch以外)": lambda r: r["touch_b"] is False}
    recs_t = build_cut_records(rows_audio_main, rows_visual_main, cuts_t, gamma_audio, gamma_visual, n_starts)
    write_records(os.path.join(out_dir, "ctx3_touch_fit.csv"), recs_t, first_col="device_type")

    # 音の出し方(聴覚のみ)
    dev_cats = sorted({r.get("audio_device") for r in rows_audio_main if r.get("audio_device")})
    cuts_d = {c: (lambda r, c=c: r.get("audio_device") == c) for c in dev_cats}
    recs_d = build_cut_records(rows_audio_main, [], cuts_d, gamma_audio, gamma_visual, n_starts)
    recs_d = [r for r in recs_d if r["modality"] == "audio"]
    write_records(os.path.join(out_dir, "ctx3_audio_device_fit.csv"), recs_d, first_col="audio_device")

    # 音の関門でつまずいた人(聴覚のみ。audio_check_missesは参加者単位で一定)
    cuts_m = {
        "つまずきなし(0回)": lambda r: r["audio_check_misses"] == 0,
        "つまずきあり(1回以上)": lambda r: (r["audio_check_misses"] or 0) > 0,
    }
    recs_m = build_cut_records(rows_audio_main, [], cuts_m, gamma_audio, gamma_visual, n_starts)
    recs_m = [r for r in recs_m if r["modality"] == "audio"]
    write_records(os.path.join(out_dir, "ctx3_audio_check_miss.csv"), recs_m, first_col="audio_check_misses_group")

    return recs_t, recs_d, recs_m


# ---------------------------------------------------------------------------
# ④ 学習・順序の効果 / ⑤ 回答の中身(出題範囲の学習)
# ---------------------------------------------------------------------------
def add_rel_pos(rows):
    """参加者ごとの trial_index を 0〜1 に正規化した rel_pos を付与する(戻り値は同じrows)。
    視覚参加者はセッションあたりの試行数がまちまち(4〜120)なので、生のtrial_indexのまま
    束ねると人によって「前半/後半」の意味がずれる。参加者内の最大trial_indexで割ることで
    「そのセッション内でどのあたりか」に揃える。"""
    max_idx = defaultdict(int)
    for r in rows:
        if r["trial_index_i"] is not None:
            max_idx[r["participant_id"]] = max(max_idx[r["participant_id"]], r["trial_index_i"])
    for r in rows:
        mi = max_idx.get(r["participant_id"], 0)
        r["rel_pos"] = (r["trial_index_i"] / mi) if (r["trial_index_i"] is not None and mi > 0) else None
    return rows


def section4_learning_order(rows_audio_main, rows_visual_main, gamma_audio, gamma_visual, n_starts, out_dir):
    add_rel_pos(rows_audio_main)
    add_rel_pos(rows_visual_main)

    # 4-a. セッション内の位置(10分位)ごとの正答率(素の値。字・水準を全部プールした粗い指標)
    trend_rows = []
    for mod, rows in (("audio", rows_audio_main), ("visual", rows_visual_main)):
        bins = np.linspace(0, 1, 11)
        for i in range(10):
            lo, hi = bins[i], bins[i + 1]
            sub = [r for r in rows if r["rel_pos"] is not None and
                   (lo < r["rel_pos"] <= hi if i > 0 else lo <= r["rel_pos"] <= hi)]
            n = len(sub)
            acc = (sum(1 for r in sub if r["correct_b"]) / n) if n else ""
            n_part = len({r["participant_id"] for r in sub})
            trend_rows.append(dict(modality=mod, decile=i + 1, rel_pos_lo=round(lo, 2), rel_pos_hi=round(hi, 2),
                                    n_trials=n, n_participants=n_part,
                                    accuracy=round(acc, 4) if acc != "" else ""))
    with io.open(os.path.join(out_dir, "ctx4_trial_progress_trend.csv"), "w", encoding="utf-8", newline="") as f:
        cols = list(trend_rows[0].keys())
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in trend_rows:
            w.writerow(r)

    # 4-b. 再開の影響: 試行単位(その試行でresume_count>0) と 参加者単位(一度でも再開)
    resumed_pids = {r["participant_id"] for r in (rows_audio_main + rows_visual_main) if (r["resume_count"] or 0) > 0}
    cuts_res = {
        "baseline_全部": lambda r: True,
        "再開した試行そのものを除外": lambda r: (r["resume_count"] or 0) == 0,
        "一度でも再開した参加者を除外": lambda r: r["participant_id"] not in resumed_pids,
    }
    recs_res = build_cut_records(rows_audio_main, rows_visual_main, cuts_res, gamma_audio, gamma_visual, n_starts)
    write_records(os.path.join(out_dir, "ctx4_resume_cut.csv"), recs_res, first_col="cut")

    return trend_rows, recs_res


def section5_frequent_set_awareness(noncheck_all, out_dir):
    """
    出題範囲(本命8字+まぎれ字12字=20字)に気づいて、後半になるほど resp_in_frequent_set
    (回答が20字の中に入っているか)が上がっていないかを見る。

    正答した試行は target_char が必ず20字の中にあるので自動的にresp_in_frequent_set=真になり、
    「範囲に気づいたか」の情報を持たない。誤答した試行(=当てずっぽうや思い違いの回答)だけを
    見たほうが「回答の選び方が20字に収束してきたか」をより直接に見られるため、
    全試行・誤答試行の両方を出す。
    """
    add_rel_pos(noncheck_all)
    rows_out = []
    for mod in ("audio", "visual"):
        rows_mod = [r for r in noncheck_all if r["modality_g"] == mod]
        for subset_name, subset in (("全試行", rows_mod),
                                     ("誤答のみ", [r for r in rows_mod if not r["correct_b"]])):
            bins = np.linspace(0, 1, 11)
            for i in range(10):
                lo, hi = bins[i], bins[i + 1]
                sub = [r for r in subset if r["rel_pos"] is not None and
                       (lo < r["rel_pos"] <= hi if i > 0 else lo <= r["rel_pos"] <= hi)]
                n = len(sub)
                if n == 0:
                    rate_freq = rate_target = ""
                else:
                    rate_freq = round(sum(1 for r in sub if r["resp_in_frequent_set_b"]) / n, 4)
                    rate_target = round(sum(1 for r in sub if r["resp_in_target_set_b"]) / n, 4)
                n_part = len({r["participant_id"] for r in sub})
                rows_out.append(dict(modality=mod, subset=subset_name, decile=i + 1,
                                      rel_pos_lo=round(lo, 2), rel_pos_hi=round(hi, 2),
                                      n_trials=n, n_participants=n_part,
                                      rate_resp_in_frequent_set=rate_freq,
                                      rate_resp_in_target_set=rate_target))
        # 前半/後半の単純比較(サンプルサイズを稼ぐための粗い版)
        for subset_name, subset in (("全試行", rows_mod), ("誤答のみ", [r for r in rows_mod if not r["correct_b"]])):
            for half_name, cond in (("前半(rel_pos<=0.5)", lambda r: r["rel_pos"] is not None and r["rel_pos"] <= 0.5),
                                     ("後半(rel_pos>0.5)", lambda r: r["rel_pos"] is not None and r["rel_pos"] > 0.5)):
                sub = [r for r in subset if cond(r)]
                n = len(sub)
                rate_freq = round(sum(1 for r in sub if r["resp_in_frequent_set_b"]) / n, 4) if n else ""
                rate_target = round(sum(1 for r in sub if r["resp_in_target_set_b"]) / n, 4) if n else ""
                n_part = len({r["participant_id"] for r in sub})
                rows_out.append(dict(modality=mod, subset=subset_name, decile=f"half:{half_name}",
                                      rel_pos_lo="", rel_pos_hi="", n_trials=n, n_participants=n_part,
                                      rate_resp_in_frequent_set=rate_freq, rate_resp_in_target_set=rate_target))

    with io.open(os.path.join(out_dir, "ctx5_frequent_set_trend.csv"), "w", encoding="utf-8", newline="") as f:
        cols = list(rows_out[0].keys())
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    return rows_out


# ---------------------------------------------------------------------------
# HTMLレポート
# ---------------------------------------------------------------------------
def pick_jp_font():
    for name in ["Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic",
                 "IPAexGothic", "Noto Sans CJK JP", "TakaoPGothic"]:
        try:
            path = font_manager.findfont(font_manager.FontProperties(family=name), fallback_to_default=False)
            if path and os.path.exists(path):
                return name
        except Exception:
            continue
    return None


def fig_to_data_uri(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fig_bar_mu_lambda(records, group_key, title, jp_font, order=None, modality="audio", family=""):
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    sub = [r for r in records if r["modality"] == modality and r.get("family", "") == family]
    if order:
        sub = [r for o in order for r in sub if str(r.get(group_key, r.get("cut", ""))) == o]
    labels = [str(r.get(group_key, r.get("cut", ""))) for r in sub]
    mus = [_num(r["mu"]) for r in sub]
    lams = [_num(r["lam"]) for r in sub]
    nps = [r["n_participants"] for r in sub]
    fig, axes = plt.subplots(1, 2, figsize=(9, max(2.2, 0.42 * len(labels) + 1)))
    for ax, vals, name in ((axes[0], mus, "mu(中心)"), (axes[1], lams, "lambda(天井)")):
        y = np.arange(len(labels))
        colors = ["#9aa5b1" if (n is not None and n < SMALL_N_WARN) else "#2f6fab" for n in nps]
        xs = [v if v is not None else 0 for v in vals]
        ax.barh(y, xs, color=colors)
        ax.set_yticks(y)
        ax.set_yticklabels([f"{l} (n={n})" for l, n in zip(labels, nps)], fontsize=8.5)
        ax.set_title(name, fontsize=10)
        ax.invert_yaxis()
        for yy, v in zip(y, vals):
            if v is not None:
                ax.text(v, yy, f" {v:.3f}", va="center", fontsize=7.5)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    return fig_to_data_uri(fig)


def fig_line_trend(rows, x_key, y_key, group_key, title, ylabel, jp_font, y_as_pct=True):
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    groups = sorted({r[group_key] for r in rows})
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(groups), 1)))
    for g, c in zip(groups, colors):
        sub = [r for r in rows if r[group_key] == g and r.get(y_key, "") != "" and isinstance(r[x_key], (int, float))]
        sub = sorted(sub, key=lambda r: r[x_key])
        xs = [r[x_key] for r in sub]
        ys = [float(r[y_key]) * (100 if y_as_pct else 1) for r in sub]
        ns = [r["n_trials"] for r in sub]
        ax.plot(xs, ys, marker="o", markersize=4, label=str(g), color=c)
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=9.5)
    ax.set_xlabel("セッション内の位置(10分位、1=最初/10=最後)", fontsize=9.5)
    ax.legend(fontsize=8.5, frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig_to_data_uri(fig)


def fig_deviation(dev_rows, jp_font):
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    fams = FAMILIES_ORDER
    colors = {"fade": "#2f8f46", "reveal": "#1f5aa8", "blur": "#c0392b", "wipe": "#8e44ad"}
    for fam in fams:
        sub = sorted([r for r in dev_rows if r["family"] == fam and r["progress_pct_level"] != "ALL"],
                      key=lambda r: r["progress_pct_level"])
        xs = [r["progress_pct_level"] for r in sub]
        ys = [r["mean_dev_pt"] for r in sub]
        ax.plot(xs, ys, marker="o", markersize=3.5, label=FAMILY_LABEL[fam], color=colors[fam])
    ax.axhline(0, color="#888", linewidth=1, linestyle="--")
    ax.set_xlabel("狙った水準 progress_pct (%)", fontsize=9.5)
    ax.set_ylabel("実測 - 狙った値 (ポイント)", fontsize=9.5)
    ax.set_title("視覚: 狙った水準と実測のずれ(平均、方式別)", fontsize=11)
    ax.legend(fontsize=8.5, frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig_to_data_uri(fig)


def build_html(ctx, out_path):
    def esc(s):
        return str(s)

    def table(rows, cols, max_rows=200):
        head = "".join(f"<th>{esc(c)}</th>" for c in cols)
        body = ""
        for r in rows[:max_rows]:
            body += "<tr>" + "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols) + "</tr>"
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    css = """
    body{font-family:-apple-system,'Hiragino Sans','Yu Gothic',sans-serif;max-width:980px;margin:32px auto;
         padding:0 20px;color:#1c1f24;line-height:1.75;background:#fbfaf7}
    h1{font-size:1.5rem;border-bottom:3px solid #2f6fab;padding-bottom:8px}
    h2{font-size:1.2rem;margin-top:2.6em;border-left:6px solid #2f6fab;padding-left:10px}
    h3{font-size:1.02rem;margin-top:1.8em;color:#374151}
    .concl{background:#eef4fb;border:1px solid #c9dbef;border-radius:8px;padding:14px 18px;margin:10px 0 18px}
    .warn{background:#fdf3e7;border:1px solid #edcfa0;border-radius:8px;padding:12px 16px;margin:10px 0}
    table{border-collapse:collapse;font-size:0.82rem;margin:10px 0 20px;width:100%}
    th,td{border:1px solid #dde3ea;padding:4px 8px;text-align:right}
    th:first-child,td:first-child{text-align:left}
    thead th{background:#eef1f5}
    img{max-width:100%;display:block;margin:14px 0}
    .note{color:#6b7280;font-size:0.85rem}
    code{background:#eee;padding:1px 5px;border-radius:4px}
    """

    parts = []
    parts.append(f"<title>較正データ追加解析(参加者属性・提示品質・学習効果)</title><style>{css}</style>")
    parts.append("<h1>較正フェーズ データ 追加解析</h1>")
    parts.append(f"<p class='note'>入力: <code>project/data_calib_20260825/transfer_trials.csv</code> "
                  f"({ctx['n_rows_raw']}行) / 分析対象参加者 {ctx['n_participants']}人。"
                  f"is_testを除く、字を横断してプールした粗い指標が中心(視覚はfamily別に保持)。"
                  f"生成スクリプト: <code>experiment/tools/analyze_calib_context.py</code></p>")

    parts.append("<div class='concl'><b>先に結論だけ</b><ul>" + "".join(f"<li>{s}</li>" for s in ctx["headline"]) + "</ul></div>")

    # ① 属性
    parts.append("<h2>① 参加者の属性(年齢層・聞き取り/読みの支障)</h2>")
    parts.append(f"<p class='note'>年齢層・支障の有無はセッション最後の任意アンケート"
                  f"(<code>transfer_post_survey</code>)から取得。分析対象{ctx['n_participants']}人のうち"
                  f"アンケートに何かしら回答したのは{ctx['n_survey_any']}人、年齢層に回答したのは"
                  f"{ctx['n_survey']}人(1人だけ年齢層のみ未回答)。回答なしの人は各表の「(未回答)」に入る。"
                  f"⚠ 任意回答なので回答者バイアスがありうる。</p>")
    parts.append(f"<img src='{ctx['fig_age_counts']}' alt='age counts'>")
    parts.append("<h3>年齢層別 A(t)(聴覚、字プール)</h3>")
    parts.append(f"<img src='{ctx['fig_age_audio']}' alt='age audio'>")
    parts.append("<h3>年齢層別 V(s)(視覚、方式別・字プール)</h3>")
    for fig in ctx["fig_age_visual"]:
        parts.append(f"<img src='{fig}' alt='age visual'>")
    parts.append(table(ctx["age_records"], ["cut", "modality", "family", "n_trials", "n_participants",
                                             "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>聞き取り・読みの支障の有無別</h3>")
    parts.append(table(ctx["hear_records"], ["cut", "modality", "family", "n_trials", "n_participants",
                                              "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>聞き取りに「多少支障がある」34人を除くと聴覚曲線は変わるか</h3>")
    parts.append(f"<img src='{ctx['fig_hear_excl']}' alt='hear excl'>")
    parts.append(table(ctx["hear_excl_records"], ["cut", "modality", "family", "n_trials", "n_participants",
                                                    "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>読みに「多少支障がある」4人(参考)</h3>")
    parts.append(table(ctx["read_records"], ["cut", "modality", "family", "n_trials", "n_participants",
                                              "accuracy_overall", "mu", "lam", "note"]))

    # ② 提示の乱れ
    parts.append("<h2>② 提示の乱れ(視覚のみ)</h2>")
    parts.append("<h3>止められなかった9%(endpoint_clamped=0)はどこで起きているか</h3>")
    parts.append(table(ctx["ec_crosstab"], ["check_kind", "endpoint_clamped", "n"]))
    parts.append(f"<div class='concl'>{ctx['ec_finding']}</div>")
    parts.append("<p class='note'>参考として、機械的に同じcut比較を通常試行にもかけた結果 "
                  "(上の理由により baseline と数字が一致するはず):</p>")
    parts.append(table(ctx["ec_records"], ["cut", "modality", "family", "n_trials", "n_participants",
                                            "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>描画が飛んだ試行(max_frame_gap_ms大)を除くと変わるか</h3>")
    parts.append(table(ctx["fg_records"], ["cut", "modality", "family", "n_trials", "n_participants",
                                            "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>リフレッシュレート帯ごと</h3>")
    parts.append(table(ctx["hz_records"], ["refresh_hz_band", "modality", "family", "n_trials", "n_participants",
                                            "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>狙った水準と実測のずれ</h3>")
    parts.append(f"<div class='concl'>{ctx['dev_finding']}</div>")
    parts.append(f"<img src='{ctx['fig_dev']}' alt='deviation'>")
    parts.append("<p class='note'>方式×水準ごとの詳細値は "
                  "<code>project/data_calib_20260825/analysis_context/ctx2_progress_deviation.csv</code> 参照。</p>")

    # ③ 端末・環境
    parts.append("<h2>③ 端末と環境</h2>")
    parts.append("<h3>スマホ / PC</h3>")
    parts.append(table(ctx["touch_records"], ["device_type", "modality", "family", "n_trials", "n_participants",
                                               "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>音の出し方(聴覚のみ)</h3>")
    parts.append(table(ctx["device_records"], ["audio_device", "modality", "family", "n_trials", "n_participants",
                                                "accuracy_overall", "mu", "lam", "note"]))
    parts.append("<h3>音の関門でつまずいた人(聴覚のみ)</h3>")
    parts.append(table(ctx["miss_records"], ["audio_check_misses_group", "modality", "family", "n_trials",
                                              "n_participants", "accuracy_overall", "mu", "lam", "note"]))

    # ④ 学習・順序
    parts.append("<h2>④ 学習・順序の効果</h2>")
    parts.append(f"<img src='{ctx['fig_trend']}' alt='trend'>")
    parts.append("<h3>再開の影響</h3>")
    parts.append(table(ctx["resume_records"], ["cut", "modality", "family", "n_trials", "n_participants",
                                                "accuracy_overall", "mu", "lam", "note"]))

    # ⑤ 回答の中身
    parts.append("<h2>⑤ 回答の中身(出題範囲の学習の兆候)</h2>")
    parts.append(f"<img src='{ctx['fig_freq_all']}' alt='freq all'>")
    parts.append(f"<img src='{ctx['fig_freq_wrong']}' alt='freq wrong'>")
    parts.append(table([r for r in ctx["freq_records"] if str(r["period"]).startswith("half")],
                        ["modality", "subset", "period", "n_trials", "n_participants",
                         "rate_resp_in_frequent_set", "rate_resp_in_target_set"]))

    parts.append("<div class='warn'>統計的な有意差検定はまだ行っていない(この解析は探索用)。"
                  "傾向として並べているだけで、確定的な結論には別途検定が必要。</div>")

    html = "\n".join(parts)
    with io.open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default=TRIALS_CSV_DEFAULT)
    ap.add_argument("--out", default=OUT_DIR_DEFAULT)
    ap.add_argument("--html", default=OUT_HTML_DEFAULT)
    ap.add_argument("--fit-starts", type=int, default=6)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"読み込み: {args.inp}")
    raw, base, main_all, noncheck_all, attrs = load_and_prepare(args.inp)
    print(f"  base(is_test/対象外modality除去後) {len(base)}行")

    rows_audio_main = [r for r in main_all if r["modality_g"] == "audio"]
    rows_visual_main = [r for r in main_all if r["modality_g"] == "visual"]
    rows_visual_all = [r for r in base if r["modality_g"] == "visual"]
    print(f"  本命8字の本命問題: 聴覚{len(rows_audio_main)}行 / 視覚{len(rows_visual_main)}行")

    gamma_audio, n_choices_audio = base_mod.default_gamma(rows_audio_main, "audio")
    gamma_visual, n_choices_visual = base_mod.default_gamma(rows_visual_main, "visual")
    print(f"  gamma: 聴覚=1/{n_choices_audio}, 視覚=1/{n_choices_visual}")

    part_rows = write_participant_attributes(os.path.join(args.out, "ctx_participant_attributes.csv"), base, attrs)
    n_survey_age = sum(1 for r in part_rows if r["age_band"])
    n_survey_any = sum(1 for r in part_rows if r["age_band"] or r["read_difficulty"] or r["hear_difficulty"])
    n_survey = n_survey_age  # 図・見出しでは年齢層の回答者数を主に使う
    print(f"  参加者属性一覧を書き出し: {len(part_rows)}人 "
          f"(アンケート回答者{n_survey_any}人、うち年齢層に回答{n_survey_age}人)")

    print("① 参加者の属性")
    age_records, hear_records, hear_excl_records, read_records = section1_participant_attrs(
        rows_audio_main, rows_visual_main, gamma_audio, gamma_visual, args.fit_starts, args.out)

    print("② 提示の乱れ")
    ec_records, fg_records, hz_records, dev_rows, ec_crosstab = section2_presentation_noise(
        rows_audio_main, rows_visual_main, rows_visual_all, gamma_audio, gamma_visual, args.fit_starts, args.out)

    print("③ 端末と環境")
    touch_records, device_records, miss_records = section3_device_env(
        rows_audio_main, rows_visual_main, gamma_audio, gamma_visual, args.fit_starts, args.out)

    print("④ 学習・順序の効果")
    trend_rows, resume_records = section4_learning_order(
        rows_audio_main, rows_visual_main, gamma_audio, gamma_visual, args.fit_starts, args.out)

    print("⑤ 回答の中身")
    freq_rows = section5_frequent_set_awareness(noncheck_all, args.out)

    print(f"CSV書き出し完了: {args.out}")

    # ---------------- HTMLレポート ----------------
    print("HTMLレポート作成")
    jp_font = pick_jp_font()

    # 年齢層カウント図
    age_counter = Counter(r["age_band"] for r in part_rows if r["age_band"])
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, ax = plt.subplots(figsize=(6, 3))
    labs = [a for a in AGE_ORDER if a in age_counter]
    ax.bar(labs, [age_counter[a] for a in labs], color="#2f6fab")
    ax.set_title(f"年齢層の分布(アンケート回答{n_survey}人)", fontsize=11)
    for i, a in enumerate(labs):
        ax.text(i, age_counter[a] + 1, str(age_counter[a]), ha="center", fontsize=9)
    fig.tight_layout()
    fig_age_counts = fig_to_data_uri(fig)

    ages_present = [a for a in AGE_ORDER if any(r["cut"] == a for r in age_records)] if False else \
        [a for a in AGE_ORDER if a in age_counter]
    fig_age_audio = fig_bar_mu_lambda(age_records, "cut", "年齢層別 A(t)(聴覚、字プール)", jp_font,
                                       order=ages_present + ["(未回答)"], modality="audio", family="")
    fig_age_visual = [fig_bar_mu_lambda(age_records, "cut", f"年齢層別 V(s) - {FAMILY_LABEL[fam]}", jp_font,
                                         order=ages_present + ["(未回答)"], modality="visual", family=fam)
                       for fam in FAMILIES_ORDER]

    fig_hear_excl = fig_bar_mu_lambda(hear_excl_records, "cut", "聞き取り支障34人の除外(聴覚)", jp_font,
                                       modality="audio", family="")

    fig_dev = fig_deviation(dev_rows, jp_font)

    # 狙った水準と実測のずれ: 見出し文を作る。
    # ⚠ 実際に集計してみると、ほぼ全水準・全方式で ずれ=0.000(sd=0.000) だった。
    # 例外は reveal 方式の最小水準(名目0.25%)だけで、常に+0.05ポイントの系統的なずれがある。
    # これは actual_ms/actual_frames(実際の描画コマ数)を見ると、そちらは水準・端末で
    # ちゃんとばらついている一方、actual_s(このCSVに入っている「実測」の割合)は
    # progress_pct/100 をそのまま(小数点3桁に丸めて)入れているだけのように見える箇所がある、
    # という当てはめの入力データそのものの性質。reveal 0.25%の+0.05ptは 0.0025→0.003 の
    # 丸めで説明がつく(0.003*100-0.25=+0.05)。よって「フレーム量子化による水準のずれ」を
    # actual_s から検出することはこのデータではできなかった、という limitation として書くのが正確。
    dev_nonzero = [r for r in dev_rows if r["progress_pct_level"] != "ALL" and r["mean_dev_pt"] != 0]
    if not dev_nonzero:
        dev_finding = ("狙った水準(progress_pct)と実測(actual_s×100)のずれは、集計した全水準・全方式で"
                       "平均0.000ポイント・sd 0.000だった。60Hz環境ではフレーム量子化で数%のずれが"
                       "出ると想定していたが、この <code>actual_s</code> 列からはそれが検出できなかった。"
                       "⚠ <code>actual_ms</code>/<code>actual_frames</code>(実際の描画コマ数)は水準・端末で"
                       "ばらついているのに対し、<code>actual_s</code> は progress_pct/100 をほぼそのまま"
                       "(小数点3桁に丸めて)格納しているように見え、フレーム量子化を反映した"
                       "『真の実測値』にはなっていない疑いがある。論文の限界として、"
                       "『actual_s は名目値の丸め値に近く、フレーム単位の実測ずれの検証には使えなかった』"
                       "と書くのが正確。")
    else:
        parts_dev = "; ".join(f"{r['family']}@{r['progress_pct_level']}: {r['mean_dev_pt']:+.3f}pt(n={r['n']})"
                              for r in dev_nonzero)
        dev_finding = f"狙った水準と実測のずれが0でない箇所: {parts_dev}"

    fig_trend = fig_line_trend(trend_rows, "decile", "accuracy", "modality",
                                "セッション内の位置ごとの正答率(字・水準プール)", "正答率(%)", jp_font)

    freq_decile_all = [r for r in freq_rows if r["subset"] == "全試行" and isinstance(r["decile"], int)]
    freq_decile_wrong = [r for r in freq_rows if r["subset"] == "誤答のみ" and isinstance(r["decile"], int)]
    fig_freq_all = fig_line_trend(freq_decile_all, "decile", "rate_resp_in_frequent_set", "modality",
                                   "回答が20字(本命+まぎれ)の中に収まる割合(全試行)",
                                   "resp_in_frequent_set の割合(%)", jp_font)
    fig_freq_wrong = fig_line_trend(freq_decile_wrong, "decile", "rate_resp_in_frequent_set", "modality",
                                     "回答が20字の中に収まる割合(誤答のみ)",
                                     "resp_in_frequent_set の割合(%)", jp_font)

    # 見出し用の結論候補(数値はここで再集計。ハードコードしない)
    headline = []
    # 年齢: 50代以上 vs 40代以下の聴覚mu比較
    def _mu(records, cut, modality, family=""):
        for r in records:
            if r["cut"] == cut and r["modality"] == modality and r.get("family", "") == family:
                return _num(r["mu"]), r["n_participants"]
        return None, 0
    mu_50s, n_50s = _mu(age_records, "50代", "audio")
    mu_40s, n_40s = _mu(age_records, "40代", "audio")
    if mu_50s is not None and mu_40s is not None:
        headline.append(f"聴覚A(t)のμ(半分わかる打ち切り時間)は40代{mu_40s:.0f}ms(n={n_40s}人) → "
                         f"50代{mu_50s:.0f}ms(n={n_50s}人)。{'高齢のほうが遅い' if mu_50s > mu_40s else '明確な差なし/逆'}(字プールの粗い指標、要検証)。")

    # endpoint_clamped=0 は check_kind="full" 以外に出ていないか、クロス集計から確認して結論文を作る
    n_unclamped_total = sum(n for (ck, ec), n in ec_crosstab.items() if ec == "0")
    n_unclamped_outside_full = sum(n for (ck, ec), n in ec_crosstab.items() if ec == "0" and ck != "full")
    n_full_total = sum(n for (ck, ec), n in ec_crosstab.items() if ck == "full")
    n_full_unclamped = sum(n for (ck, ec), n in ec_crosstab.items() if ck == "full" and ec == "0")
    if n_unclamped_outside_full == 0 and n_unclamped_total > 0:
        ec_finding = (f"endpoint_clamped=0(狙った値で止められなかった)は視覚{n_unclamped_total}件、"
                      f"すべて確認問題A(check_kind=full、進み具合100%まで見せる問題、全{n_full_total}件)"
                      f"の中で起きていて({n_full_unclamped}/{n_full_total}件、確認問題A全体の"
                      f"{n_full_unclamped/n_full_total*100:.0f}%)、較正曲線の当てはめに使う通常試行"
                      f"(check_kind=空)には1件も無い。100%まで見せる問題には『途中で止める狙った値』"
                      f"という概念自体が無いための表示上の値とみられ、"
                      f"<b>視覚較正曲線(V(s))には影響していない</b>。")
    else:
        ec_finding = (f"endpoint_clamped=0は視覚{n_unclamped_total}件、うち通常試行(check_kind=空)にも"
                      f"{n_unclamped_outside_full}件含まれる。想定と異なり通常試行にも混ざっているため、"
                      f"下のcut比較(baseline vs 除外)の数字の変化を確認すること。")
    headline.append(ec_finding)
    headline.append(dev_finding)

    trend_a = [r for r in trend_rows if r["modality"] == "audio" and r["accuracy"] != ""]
    trend_v = [r for r in trend_rows if r["modality"] == "visual" and r["accuracy"] != ""]
    if trend_a and trend_v:
        da = trend_a[-1]["accuracy"] - trend_a[0]["accuracy"]
        dv = trend_v[-1]["accuracy"] - trend_v[0]["accuracy"]
        headline.append(f"セッション最初の10分位→最後の10分位で正答率は 聴覚{da*100:+.1f}pt、視覚{dv*100:+.1f}pt "
                         f"(字・水準をプールした粗い学習効果の目安)。")

    half_all = [r for r in freq_rows if str(r["decile"]).startswith("half") and r["subset"] == "誤答のみ"]
    mod_label = {"audio": "聴覚", "visual": "視覚"}
    for mod in ("audio", "visual"):
        firsts = [r for r in half_all if r["modality"] == mod and "前半" in str(r["decile"])]
        lasts = [r for r in half_all if r["modality"] == mod and "後半" in str(r["decile"])]
        if firsts and lasts and firsts[0]["rate_resp_in_frequent_set"] != "" and lasts[0]["rate_resp_in_frequent_set"] != "":
            f0 = firsts[0]["rate_resp_in_frequent_set"]
            f1 = lasts[0]["rate_resp_in_frequent_set"]
            headline.append(f"誤答時に回答が20字(本命+まぎれ)の中に収まる割合({mod_label[mod]}): "
                             f"前半{f0*100:.1f}% → 後半{f1*100:.1f}% "
                             f"({'上昇=出題範囲の学習の兆候の疑い' if f1 - f0 > 0.03 else '大きな変化なし'})。")

    ctx = dict(
        n_rows_raw=len(raw), n_participants=len({r["participant_id"] for r in base}),
        n_survey=n_survey, n_survey_any=n_survey_any,
        headline=headline,
        fig_age_counts=fig_age_counts, fig_age_audio=fig_age_audio, fig_age_visual=fig_age_visual,
        age_records=age_records, fig_hear_excl=fig_hear_excl, hear_records=hear_records,
        hear_excl_records=hear_excl_records, read_records=read_records,
        ec_records=ec_records, ec_finding=ec_finding,
        ec_crosstab=[dict(check_kind=ck, endpoint_clamped=ec, n=n)
                     for (ck, ec), n in sorted(ec_crosstab.items())],
        fg_records=fg_records, hz_records=hz_records, fig_dev=fig_dev, dev_finding=dev_finding,
        touch_records=touch_records, device_records=device_records, miss_records=miss_records,
        fig_trend=fig_trend, resume_records=resume_records,
        fig_freq_all=fig_freq_all, fig_freq_wrong=fig_freq_wrong,
        freq_records=[dict(r, period=r["decile"]) for r in freq_rows],
    )
    out_path = build_html(ctx, args.html)
    print(f"書き出し: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
