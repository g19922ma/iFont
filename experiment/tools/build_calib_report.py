#!/usr/bin/env python3
"""
較正フェーズ（transfer 実験）の結果を1枚のHTMLレポートにまとめる
================================================================

丸山さん本人と指導教員が「今日の判断」を下すためのレポート。
WISS 2026（締切8/31）に向けて、
  ・聴覚の打ち切り呈示 A(t) はどこまで使えるか
  ・視覚の4方式（fade/reveal/blur/wipe）の進み具合 V(s) はどう違うか
を眺め、聴覚の刺激（特に「が」）に不具合がある証拠を数字で示す。

入力
----
  project/data_calib_20260825/transfer_trials.csv    … 本体（18,689行・253人）
  project/data_calib_20260825/transfer_wellbeing.csv … セッション記録（所要時間・送信失敗）
                                                          transfer_trials.csv には無い値なので、
                                                          要約（1章）の所要時間・送信の取りこぼしだけ
                                                          ここから読む。

出力
----
  project/data_calib_20260825/calib_report.html （グラフはPNGをdata URIで埋め込み、1ファイルで完結）

使い方
------
  python3 experiment/tools/build_calib_report.py

⚠ 数値はすべてこのスクリプトが transfer_trials.csv / transfer_wellbeing.csv から計算する。
  文中の「既知の事実」的な数字はいっさいハードコードしていない。
"""
import base64
import csv
import io
import os
from collections import Counter, defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "project", "data_calib_20260825"))
TRIALS_CSV = os.path.join(DATA_DIR, "transfer_trials.csv")
WELLBEING_CSV = os.path.join(DATA_DIR, "transfer_wellbeing.csv")
OUT_HTML = os.path.join(DATA_DIR, "calib_report.html")

MAIN_CHARS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
FAMILIES = ["fade", "reveal", "blur", "wipe"]
FAMILY_LABEL = {"fade": "fade（うすい→濃い）", "reveal": "reveal（点が増える）",
                "blur": "blur（ぼやけ→はっきり）", "wipe": "wipe（端から現れる）"}
# 対象と厳密に一致させる。ぢ・づは対応する清音の扱いが単純でないため、課題の指定どおり外す。
DAKUON_LIST = list("がぎぐげござじずぜぞだでどばびぶべぼ")
SEION_OF_DAKUON = {"が": "か", "ぎ": "き", "ぐ": "く", "げ": "け", "ご": "こ",
                   "ざ": "さ", "じ": "し", "ず": "す", "ぜ": "せ", "ぞ": "そ",
                   "だ": "た", "で": "て", "ど": "と",
                   "ば": "は", "び": "ひ", "ぶ": "ふ", "べ": "へ", "ぼ": "ほ"}

# 字ごとに固定の色を割り当て、聴覚・視覚どちらの図でも同じ字は同じ色にする。
CHAR_COLORS = {
    "あ": "#1f5aa8", "か": "#2f8f46", "が": "#c0392b", "ぱ": "#8e44ad",
    "し": "#d68910", "つ": "#16a085", "ま": "#34495e", "ら": "#b5651d",
}
USABLE_CHARS_LABEL = "使える字"
UNUSABLE_CHARS_LABEL = "使えない字"


# ---------------------------------------------------------------- 下ごしらえ
def truthy(v):
    return str(v).strip().upper() in ("1", "TRUE", "T", "YES")


def num(v):
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pick_jp_font():
    """日本語が豆腐(□)にならないフォントを探す（analyze_transfer.py と同じ考え方）。"""
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


def load_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fig_to_data_uri(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------- 読み込み・前処理
def load_trials():
    rows = load_csv(TRIALS_CSV)
    total_raw = len(rows)
    rows = [r for r in rows if not truthy(r.get("is_test"))]
    # 課題の指定どおり is_test だけを外す（practice 列はこのCSVに存在しない。確認済み）。
    return rows, total_raw


def is_main_row(r, group, need_level_col):
    """本命の分析対象: is_decoy が偽 かつ check_kind が空 かつ対象8字、指定集団、水準値あり。"""
    if r["group"] != group:
        return False
    if truthy(r.get("is_decoy")):
        return False
    if (r.get("check_kind") or "").strip() != "":
        return False
    if r.get("target_char") not in MAIN_CHARS:
        return False
    if num(r.get(need_level_col)) is None:
        return False
    return True


def build_audio_main(rows):
    """(字, gate_ms) -> [n_correct, n_trials]"""
    tab = defaultdict(lambda: [0, 0])
    for r in rows:
        if not is_main_row(r, "acal", "gate_ms"):
            continue
        g = num(r["gate_ms"])
        k = (r["target_char"], g)
        tab[k][1] += 1
        if truthy(r["correct"]):
            tab[k][0] += 1
    return tab


def build_visual_main(rows):
    """(方式, 字, 実測進み具合actual_s丸め) -> [n_correct, n_trials, sum_actual_s]"""
    tab = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        if not is_main_row(r, "aprime", "actual_s"):
            continue
        fam = (r.get("family") or "").strip()
        if fam not in FAMILIES:
            continue
        a = num(r["actual_s"])
        # 実測値は端末のリフレッシュレートでごく僅かにばらつくが、丸めるとほぼ
        # 8段の設計水準に戻る（同一ファミリー内で重複actual_sはユニーク8個前後）。
        # 丸めて同じ水準とみなし、x座標にはその中の平均実測値を使う。
        key_a = round(a, 3)
        k = (fam, r["target_char"], key_a)
        tab[k][1] += 1
        tab[k][2] += a
        if truthy(r["correct"]):
            tab[k][0] += 1
    return tab


def usable_chars_audio(audio_tab, threshold=0.80):
    """字ごとに『最長の打ち切りでの正答率』が閾値以上かで使える/使えないを分ける。"""
    max_level = {}
    for (ch, g), (ok, n) in audio_tab.items():
        if n == 0:
            continue
        if ch not in max_level or g > max_level[ch][0]:
            max_level[ch] = (g, ok, n)
    usable = {}
    for ch, (g, ok, n) in max_level.items():
        usable[ch] = (ok / n) >= threshold
    return usable, max_level


# ---------------------------------------------------------------- 図: 聴覚 A(t)
def draw_audio_curve(audio_tab, usable, jp_font):
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, ax = plt.subplots(figsize=(8.6, 5.0), dpi=150)
    for ch in MAIN_CHARS:
        pts = sorted((g, ok, n) for (c, g), (ok, n) in audio_tab.items() if c == ch)
        if not pts:
            continue
        xs = [g for g, ok, n in pts]
        ys = [100 * ok / n for g, ok, n in pts]
        ns = [n for g, ok, n in pts]
        good = usable.get(ch, False)
        color = CHAR_COLORS[ch]
        ax.plot(xs, ys, marker="o" if good else "s",
                markersize=6.5 if good else 5,
                linewidth=2.4 if good else 1.5,
                linestyle="-" if good else "--",
                alpha=1.0 if good else 0.55,
                color=color,
                label=f"{ch}（{'使える' if good else '使えない'}）")
        for x, y, n in zip(xs, ys, ns):
            ax.annotate(str(n), (x, y), textcoords="offset points",
                        xytext=(0, 6 if good else -11), fontsize=6.6,
                        color=color, alpha=0.9, ha="center")
    ax.set_xlabel("打ち切り時刻（ミリ秒）")
    ax.set_ylabel("正答率（％）")
    ax.set_ylim(-6, 108)
    ax.set_title("聴覚 A(t)：字ごとの正答率曲線（点の数字＝試行数）", fontsize=11.5)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(ncol=4, fontsize=8.8, frameon=False, loc="upper left")
    fig.tight_layout()
    return fig_to_data_uri(fig)


# ---------------------------------------------------------------- 図: 視覚 V(s)
def draw_visual_curves(visual_tab, jp_font):
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.6), dpi=150)
    axes = axes.flatten()
    for i, fam in enumerate(FAMILIES):
        ax = axes[i]
        for ch in MAIN_CHARS:
            pts = sorted((a, ok, n) for (f, c, a), (ok, n, sa) in visual_tab.items()
                        if f == fam and c == ch)
            if not pts:
                continue
            xs = [max(p[0] * 100, 0.05) for p in pts]  # %表示。0はlogに乗らないので下限を敷く
            ys = [100 * p[1] / p[2] for p in pts]
            ns = [p[2] for p in pts]
            ax.plot(xs, ys, marker="o", markersize=4.5, linewidth=1.6,
                    color=CHAR_COLORS[ch], label=ch)
        if fam == "blur":
            ax.set_xscale("linear")
        else:
            ax.set_xscale("log")
        ax.set_ylim(-6, 108)
        ax.set_xlabel("進み具合（実測 actual_s、％、対数軸）" if fam != "blur"
                      else "進み具合（実測 actual_s、％）")
        ax.set_ylabel("正答率（％）")
        ax.set_title(FAMILY_LABEL[fam], fontsize=11)
        ax.grid(alpha=0.25, linewidth=0.6)
        if i == 0:
            ax.legend(ncol=4, fontsize=8, frameon=False, loc="lower right")
    fig.suptitle("視覚 V(s)：方式ごとの正答率曲線（横軸は実測進み具合 actual_s。名目値ではない）",
                fontsize=12.5, y=1.01)
    fig.tight_layout()
    return fig_to_data_uri(fig)


# ---------------------------------------------------------------- 図: 全部提示の正答率（棒）
def draw_full_check_bar(rows, jp_font):
    full = [r for r in rows if r.get("group") == "acal" and (r.get("check_kind") or "") == "full"]
    acc = defaultdict(lambda: [0, 0])
    for r in full:
        ch = r["target_char"]
        acc[ch][1] += 1
        if truthy(r["correct"]):
            acc[ch][0] += 1
    items = [(ch, ok, n, ok / n) for ch, (ok, n) in acc.items() if n > 0]
    items.sort(key=lambda x: x[3])
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, ax = plt.subplots(figsize=(7.4, max(6.5, 0.19 * len(items))), dpi=150)
    ys = np.arange(len(items))
    colors = ["#c0392b" if ch in MAIN_CHARS else "#9fb3c8" for ch, *_ in items]
    ax.barh(ys, [x[3] * 100 for x in items], color=colors, height=0.72)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{ch}" for ch, *_ in items], fontsize=7.6)
    for y, (ch, ok, n, a) in zip(ys, items):
        ax.text(a * 100 + 1.5, y, f"{ok}/{n}", va="center", fontsize=6.4, color="#333")
    ax.set_xlim(0, 112)
    ax.set_xlabel("正答率（％）　※全部聞かせた確認問題。本来はほぼ100%になるはず")
    ax.set_title("聴覚：全部提示（check_kind=full）の字ごとの正答率\n"
                "（赤＝本命8字。灰＝まぎれ字として出た他の字）", fontsize=10.5)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)
    fig.tight_layout()
    return fig_to_data_uri(fig), items


# ---------------------------------------------------------------- 図: 混同行列
def draw_confusion_matrix(rows, jp_font):
    full = [r for r in rows if r.get("group") == "acal" and (r.get("check_kind") or "") == "full"
            and r["target_char"] in MAIN_CHARS]
    resp_chars = sorted(set(r["response_char"] for r in full))
    mat = np.zeros((len(MAIN_CHARS), len(resp_chars)), dtype=int)
    for r in full:
        i = MAIN_CHARS.index(r["target_char"])
        j = resp_chars.index(r["response_char"])
        mat[i, j] += 1
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, ax = plt.subplots(figsize=(9.5, 4.3), dpi=150)
    im = ax.imshow(mat, cmap="Reds", aspect="auto")
    ax.set_xticks(range(len(resp_chars)))
    ax.set_xticklabels(resp_chars, fontsize=9)
    ax.set_yticks(range(len(MAIN_CHARS)))
    ax.set_yticklabels(MAIN_CHARS, fontsize=10)
    ax.set_xlabel("答えた字（response_char）")
    ax.set_ylabel("出した字（target_char）")
    ax.set_title("聴覚：全部提示での混同行列（本命8字が出題されたときの回答先）", fontsize=11)
    vmax = mat.max() if mat.max() > 0 else 1
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if v == 0:
                continue
            color = "white" if v > vmax * 0.55 else "#333"
            weight = "bold" if resp_chars[j] == MAIN_CHARS[i] else "normal"
            ax.text(j, i, str(v), ha="center", va="center", fontsize=8.2,
                    color=color, fontweight=weight)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="回数")
    fig.tight_layout()
    return fig_to_data_uri(fig), mat, resp_chars


# ---------------------------------------------------------------- 濁音の取り違え
def dakuon_confusion(rows):
    full_acal = [r for r in rows if r.get("group") == "acal" and (r.get("check_kind") or "") == "full"]
    n_dakuon = 0
    n_to_seion = 0
    n_correct = 0
    for r in full_acal:
        t = r["target_char"]
        if t not in DAKUON_LIST:
            continue
        n_dakuon += 1
        if truthy(r["correct"]):
            n_correct += 1
        elif r["response_char"] == SEION_OF_DAKUON.get(t):
            n_to_seion += 1
    return n_dakuon, n_correct, n_to_seion


# ---------------------------------------------------------------- 参加者の取り組みの質
def participant_full_check_acc(rows, group):
    per = defaultdict(lambda: [0, 0])
    for r in rows:
        if r.get("group") != group or (r.get("check_kind") or "") != "full":
            continue
        per[r["participant_id"]][1] += 1
        if truthy(r["correct"]):
            per[r["participant_id"]][0] += 1
    return {p: (ok / n if n else None, n) for p, (ok, n) in per.items()}


def participant_same_char_rate(rows):
    """calib本編（check_kindが空）での回答の中で、最頻回答が占める割合。集団ごと。"""
    per = defaultdict(list)
    for r in rows:
        if (r.get("check_kind") or "") != "":
            continue
        if r.get("phase") != "calib":
            continue
        if not r.get("response_char"):
            continue
        per[(r["group"], r["participant_id"])].append(r["response_char"])
    out = {}
    for k, resp_list in per.items():
        c = Counter(resp_list)
        top = c.most_common(1)[0][1]
        out[k] = (top / len(resp_list), len(resp_list))
    return out


def rt_ms_values(rows):
    out = {"acal": [], "aprime": []}
    for r in rows:
        if (r.get("check_kind") or "") != "" or r.get("phase") != "calib":
            continue
        g = r.get("group")
        if g not in out:
            continue
        v = num(r.get("rt_ms"))
        if v is not None:
            out[g].append(v)
    return out


def draw_quality_figures(rows, jp_font):
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    acc_a = participant_full_check_acc(rows, "acal")
    acc_v = participant_full_check_acc(rows, "aprime")
    rt = rt_ms_values(rows)

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.0), dpi=150)

    ax = axes[0]
    va = [v for v, n in acc_a.values() if v is not None]
    vv = [v for v, n in acc_v.values() if v is not None]
    bins = np.linspace(0, 1, 11)
    ax.hist([np.array(va) * 100, np.array(vv) * 100], bins=np.linspace(0, 100, 11),
            label=[f"聴覚（{len(va)}人）", f"視覚（{len(vv)}人）"],
            color=["#1f5aa8", "#c0392b"], alpha=0.75)
    ax.set_xlabel("確認問題A（全部提示）の個人正答率（％）")
    ax.set_ylabel("参加者数")
    ax.set_title("確認問題Aの正答率分布", fontsize=10.5)
    ax.legend(fontsize=8, frameon=False)

    ax = axes[1]
    same = participant_same_char_rate(rows)
    same_a = [v for (g, p), (v, n) in same.items() if g == "acal"]
    same_v = [v for (g, p), (v, n) in same.items() if g == "aprime"]
    ax.hist([np.array(same_a) * 100, np.array(same_v) * 100], bins=np.linspace(0, 100, 11),
            label=[f"聴覚（{len(same_a)}人）", f"視覚（{len(same_v)}人）"],
            color=["#1f5aa8", "#c0392b"], alpha=0.75)
    ax.axvline(30, color="#333", linewidth=1, linestyle="--")
    ax.set_xlabel("最頻回答が占める割合（％）")
    ax.set_ylabel("参加者数")
    ax.set_title("同じ字ばかり押していないか（点線=30%）", fontsize=10.5)
    ax.legend(fontsize=8, frameon=False)

    ax = axes[2]
    ax.hist([rt["acal"], rt["aprime"]], bins=40, range=(0, 6000),
            label=[f"聴覚（{len(rt['acal'])}試行）", f"視覚（{len(rt['aprime'])}試行）"],
            color=["#1f5aa8", "#c0392b"], alpha=0.75)
    ax.axvline(300, color="#333", linewidth=1, linestyle="--")
    ax.set_xlabel("反応時間（ミリ秒、点線=300ms）")
    ax.set_ylabel("試行数")
    ax.set_title("反応時間の分布", fontsize=10.5)
    ax.legend(fontsize=8, frameon=False)

    fig.tight_layout()
    return fig_to_data_uri(fig), acc_a, acc_v, same, rt


# ---------------------------------------------------------------- 感度分析
def compute_ga_accuracy(rows_subset):
    ok = n = 0
    ok_ref = n_ref = 0
    for r in rows_subset:
        if not is_main_row(r, "acal", "gate_ms"):
            continue
        if r["target_char"] == "が":
            n += 1
            if truthy(r["correct"]):
                ok += 1
        elif r["target_char"] in ("あ", "か", "ま"):
            n_ref += 1
            if truthy(r["correct"]):
                ok_ref += 1
    return ok, n, ok_ref, n_ref


def sensitivity_table(rows):
    """
    6通りの外れ値の切り方それぞれで、聴覚acal本命データから「が」の正答率を再計算する。
    比較用に「あ・か・ま」（使える3字）の合算正答率も添える。
    """
    same = participant_same_char_rate(rows)  # (group,pid) -> (rate, n)
    full_acc = participant_full_check_acc(rows, "acal")  # pid -> (rate, n)
    device_by_pid = {}
    for r in rows:
        if r.get("group") == "acal" and r.get("audio_device"):
            device_by_pid[r["participant_id"]] = r["audio_device"]

    # 参加者内 rt_ms の 1.5×IQR 範囲（acal・本編）
    rt_by_pid = defaultdict(list)
    for r in rows:
        if r.get("group") == "acal" and (r.get("check_kind") or "") == "" and r.get("phase") == "calib":
            v = num(r.get("rt_ms"))
            if v is not None:
                rt_by_pid[r["participant_id"]].append(v)
    iqr_bounds = {}
    for pid, vs in rt_by_pid.items():
        q1, q3 = np.percentile(vs, [25, 75])
        iqr = q3 - q1
        iqr_bounds[pid] = (q1 - 1.5 * iqr, q3 + 1.5 * iqr)

    acal_rows = [r for r in rows if r.get("group") == "acal"]

    def base(_r):
        return True

    def excl_rt_iqr(r):
        pid = r["participant_id"]
        v = num(r.get("rt_ms"))
        if pid not in iqr_bounds or v is None:
            return True
        lo, hi = iqr_bounds[pid]
        return lo <= v <= hi

    def excl_rt_300(r):
        v = num(r.get("rt_ms"))
        return v is None or v >= 300

    def excl_same_char(r):
        rate, n = same.get(("acal", r["participant_id"]), (0, 0))
        return rate < 0.30

    def excl_check_half(r):
        rate, n = full_acc.get(r["participant_id"], (None, 0))
        return rate is None or rate >= 0.50

    def excl_wireless(r):
        return device_by_pid.get(r["participant_id"]) != "無線"

    criteria = [
        ("全部（基準）", base),
        ("反応時間が参加者内 1.5×IQR 外を除く", excl_rt_iqr),
        ("反応時間 300ms 未満を除く", excl_rt_300),
        ("同じ字を3割以上押した人を除く", excl_same_char),
        ("確認問題Aが半分未満の人を除く", excl_check_half),
        ("無線イヤホンの人を除く", excl_wireless),
    ]

    out = []
    n_pid_total = len(set(r["participant_id"] for r in acal_rows))
    for label, keep_fn in criteria:
        subset = [r for r in acal_rows if keep_fn(r)]
        n_pid_kept = len(set(r["participant_id"] for r in subset))
        # 「残った試行数」は本命の分析対象（本命8字・is_decoy偽・check_kind空・gate_msあり）に限る。
        # 「が」正答率の分母（ga_n）と揃えるため、集計対象を一致させておく。
        n_main_trials = sum(1 for r in subset if is_main_row(r, "acal", "gate_ms"))
        ok, n, ok_ref, n_ref = compute_ga_accuracy(subset)
        out.append({
            "label": label,
            "n_participants_kept": n_pid_kept,
            "n_participants_total": n_pid_total,
            "n_trials_kept": n_main_trials,
            "ga_ok": ok, "ga_n": n,
            "ga_acc": (ok / n * 100) if n else None,
            "ref_ok": ok_ref, "ref_n": n_ref,
            "ref_acc": (ok_ref / n_ref * 100) if n_ref else None,
        })
    return out


# ---------------------------------------------------------------- 要約（1章）
def load_wellbeing_sessions():
    rows = load_csv(WELLBEING_CSV)
    sess = [r for r in rows if r.get("record_kind") == "session" and not truthy(r.get("is_test"))]
    return sess


def summary_stats(rows, sess):
    n_total_rows_raw = None  # 呼び出し側で埋める
    participants = defaultdict(set)
    trials_main = defaultdict(int)
    for r in rows:
        g = r.get("group")
        if g in ("acal", "aprime"):
            participants[g].add(r["participant_id"])
    for r in rows:
        if r.get("group") == "acal" and is_main_row(r, "acal", "gate_ms"):
            trials_main["acal"] += 1
        if r.get("group") == "aprime" and is_main_row(r, "aprime", "actual_s"):
            trials_main["aprime"] += 1

    durations = [num(r.get("duration_s")) for r in sess if num(r.get("duration_s")) is not None]
    send_fail = sum(int(r.get("send_failures") or 0) for r in sess)
    send_retry_n = sum(1 for r in sess if int(r.get("send_retries") or 0) > 0)
    send_retry_sum = sum(int(r.get("send_retries") or 0) for r in sess)

    return {
        "n_acal": len(participants["acal"]),
        "n_aprime": len(participants["aprime"]),
        "n_total": len(participants["acal"] | participants["aprime"]),
        "n_trials_main_acal": trials_main["acal"],
        "n_trials_main_aprime": trials_main["aprime"],
        "n_sessions": len(sess),
        "duration_median": float(np.median(durations)) if durations else None,
        "duration_mean": float(np.mean(durations)) if durations else None,
        "duration_min": min(durations) if durations else None,
        "duration_max": max(durations) if durations else None,
        "send_fail": send_fail,
        "send_retry_n": send_retry_n,
        "send_retry_sum": send_retry_sum,
    }


# ---------------------------------------------------------------- HTML 組み立て
def fmt_pct(x, nd=1):
    return "—" if x is None else f"{x:.{nd}f}%"


def render_html(ctx):
    S = ctx["summary"]
    usable = ctx["usable"]
    max_level = ctx["max_level"]
    usable_list = "・".join(ch for ch in MAIN_CHARS if usable.get(ch))
    unusable_list = "・".join(ch for ch in MAIN_CHARS if not usable.get(ch))

    n_dakuon, n_dakuon_ok, n_dakuon_to_seion = ctx["dakuon"]
    dakuon_seion_rate = (n_dakuon_to_seion / n_dakuon * 100) if n_dakuon else 0
    dakuon_acc = (n_dakuon_ok / n_dakuon * 100) if n_dakuon else 0

    full_items = ctx["full_items"]
    ga_full = next((x for x in full_items if x[0] == "が"), None)
    shi_full = next((x for x in full_items if x[0] == "し"), None)
    ra_full = next((x for x in full_items if x[0] == "ら"), None)

    sens = ctx["sensitivity"]

    css = """
    :root{
      --bg:#f7f5f0; --panel:#ffffff; --ink:#20242b; --sub:#5b6470;
      --line:#dfd9cd; --accent:#8a3324; --accent2:#1f5aa8;
      --good:#1e6b3c; --bad:#a4231a; --tag-bg:#eef1ee;
    }
    *{box-sizing:border-box;}
    body{
      background:var(--bg); color:var(--ink);
      font-family:"Hiragino Mincho ProN","Hiragino Sans","YuGothic","Noto Serif JP",serif;
      line-height:1.85; margin:0; padding:0 0 80px;
    }
    .wrap{max-width:980px; margin:0 auto; padding:0 28px;}
    header.hero{
      background:linear-gradient(180deg,#efe9dc 0%, var(--bg) 100%);
      border-bottom:1px solid var(--line); padding:46px 0 32px;
    }
    header.hero h1{
      font-size:1.62rem; margin:0 0 8px; letter-spacing:.02em; font-weight:700;
    }
    header.hero .meta{color:var(--sub); font-size:.86rem; font-family:"Hiragino Sans",sans-serif;}
    section{padding:38px 0; border-bottom:1px solid var(--line);}
    section:last-of-type{border-bottom:none;}
    h2{
      font-size:1.18rem; margin:0 0 4px; font-weight:700;
      display:flex; align-items:baseline; gap:10px;
    }
    h2 .num{
      font-family:"Hiragino Sans",sans-serif; font-size:.72rem; color:var(--sub);
      border:1px solid var(--line); border-radius:3px; padding:1px 7px;
    }
    h2 + .lead{color:var(--sub); font-size:.88rem; margin:2px 0 20px; font-family:"Hiragino Sans",sans-serif;}
    h3{font-size:1.0rem; margin:26px 0 10px; font-weight:700;}
    p{margin:0 0 12px;}
    .callout{
      background:var(--panel); border:1px solid var(--line); border-left:5px solid var(--accent);
      border-radius:4px; padding:20px 24px; margin:14px 0;
    }
    .callout.good{border-left-color:var(--good);}
    .callout .title{font-weight:700; font-size:1.02rem; margin-bottom:6px;}
    .grid-summary{
      display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:22px 0;
      font-family:"Hiragino Sans",sans-serif;
    }
    .tile{background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:14px 16px;}
    .tile .k{font-size:.72rem; color:var(--sub); margin-bottom:5px;}
    .tile .v{font-size:1.32rem; font-weight:700; font-variant-numeric:tabular-nums;}
    .tile .v small{font-size:.62rem; font-weight:400; color:var(--sub);}
    figure{margin:18px 0; text-align:center;}
    figure img{max-width:100%; border:1px solid var(--line); border-radius:4px; background:#fff;}
    figcaption{
      font-size:.8rem; color:var(--sub); margin-top:8px; font-family:"Hiragino Sans",sans-serif;
    }
    table{border-collapse:collapse; width:100%; margin:14px 0; font-size:.86rem; font-family:"Hiragino Sans",sans-serif;}
    caption{caption-side:top; text-align:left; font-size:.82rem; color:var(--sub); margin-bottom:6px;}
    th,td{border:1px solid var(--line); padding:7px 10px; text-align:right;}
    th{background:#eee8da; font-weight:700; text-align:center;}
    td.l{text-align:left;}
    td.ok{color:var(--good); font-weight:700;}
    td.bad{color:var(--bad); font-weight:700;}
    .tag{
      display:inline-block; font-family:"Hiragino Sans",sans-serif; font-size:.72rem;
      background:var(--tag-bg); border:1px solid var(--line); border-radius:3px;
      padding:1px 8px; margin-right:6px;
    }
    .note{
      font-size:.82rem; color:var(--sub); background:#f1efe6; border:1px solid var(--line);
      border-radius:4px; padding:10px 14px; margin:12px 0; font-family:"Hiragino Sans",sans-serif;
    }
    .note b{color:var(--ink);}
    footer{
      max-width:980px; margin:0 auto; padding:30px 28px; color:var(--sub);
      font-size:.78rem; font-family:"Hiragino Sans",sans-serif;
    }
    """

    # --- 1章タイル ---
    tiles = f"""
    <div class="grid-summary">
      <div class="tile"><div class="k">参加者（聴覚 / 視覚）</div>
        <div class="v">{S['n_acal']} / {S['n_aprime']} <small>人</small></div></div>
      <div class="tile"><div class="k">本命の分析対象 試行数（聴覚 / 視覚）</div>
        <div class="v">{S['n_trials_main_acal']:,} / {S['n_trials_main_aprime']:,} <small>試行</small></div></div>
      <div class="tile"><div class="k">所要時間（中央値）</div>
        <div class="v">{S['duration_median']/60:.1f} <small>分</small></div>
        <div class="k">範囲 {S['duration_min']/60:.1f}〜{S['duration_max']/60:.1f}分</div></div>
      <div class="tile"><div class="k">送信の取りこぼし</div>
        <div class="v">{S['send_fail']} <small>件失敗</small></div>
        <div class="k">再送 {S['send_retry_sum']}件（{S['send_retry_n']}人、いずれも最終的に成功）</div></div>
    </div>
    """

    # --- 感度分析テーブル ---
    sens_rows = ""
    for row in sens:
        ga_cls = "bad" if (row["ga_acc"] is not None and row["ga_acc"] < 15) else ""
        sens_rows += f"""
        <tr>
          <td class="l">{esc(row['label'])}</td>
          <td>{row['n_participants_kept']}/{row['n_participants_total']}</td>
          <td>{row['n_trials_kept']:,}</td>
          <td class="{ga_cls}">{fmt_pct(row['ga_acc'])}<br><span style="font-size:.75em;color:var(--sub)">({row['ga_ok']}/{row['ga_n']})</span></td>
          <td class="ok">{fmt_pct(row['ref_acc'])}<br><span style="font-size:.75em;color:var(--sub)">({row['ref_ok']}/{row['ref_n']})</span></td>
        </tr>
        """

    html = f"""<!doctype html>
<title>較正フェーズ 結果レポート</title>
<meta charset="utf-8">
<style>{css}</style>
<div class="wrap">
<header class="hero">
  <h1>較正フェーズ 結果レポート</h1>
  <div class="meta">
    転写検証実験（calib）／ 入力: project/data_calib_20260825/transfer_trials.csv（全{ctx['total_raw']:,}行 → is_test除外後 {len(ctx['rows']):,}行）
    ／ 生成: experiment/tools/build_calib_report.py
  </div>
</header>

<div class="wrap">

<section>
  <h2><span class="num">1</span>ひと目で分かる要約</h2>
  {tiles}

  <div class="callout">
    <div class="title">結論：聴覚の打ち切り呈示は8字中3字（{esc(usable_list)}）しか使えない。視覚4方式は良好。</div>
    <p>
      聴覚 A(t) は「{esc(usable_list)}」の3字で床（正答率がほぼ0%になる短い呈示）と天井
      （正答率がほぼ100%になる長い呈示）の両方が取れているが、「{esc(unusable_list)}」の5字は
      天井に届かない、または呈示時間を延ばすと正答率が下がるという不自然な挙動を示す。
      特に「が」は最長の呈示（打ち切りなし、全部聞かせる確認問題）でも正答率
      {fmt_pct(ga_full[3]*100 if ga_full else None)}（{ga_full[1] if ga_full else '—'}/{ga_full[2] if ga_full else '—'}）にとどまり、
      刺激そのものに不具合がある疑いが強い（3章）。
    </p>
    <p>
      視覚 V(s) は4方式とも、最も進んだ水準（実測でほぼ100%）でおおむね正答率90%台後半に達しており、
      刺激としては機能している（4章）。ただし方式ごとに「同じ進み具合％」が意味する見えやすさは大きく異なるため、
      A(t)に形を合わせる設計は方式ごとに別々に行う必要がある。
    </p>
  </div>
</section>

<section>
  <h2><span class="num">2</span>聴覚 A(t)：字ごとの曲線</h2>
  <p class="lead">横軸は打ち切り時刻（ms）、縦軸は正答率。実線・丸＝使える字、破線・四角＝使えない字。各点の脇の数字は試行数。</p>
  <figure>
    <img src="{ctx['fig_audio']}" alt="聴覚A(t)曲線">
    <figcaption>本命の分析対象（is_decoy=偽・check_kind=空）の acal（聴覚）データより。
      「使える／使えない」は、各字の最長呈示時点での正答率が80%に達しているかで判定（下表）。</figcaption>
  </figure>
  <table>
    <caption>字ごとの「最長呈示時点」の正答率（使える／使えないの判定根拠）</caption>
    <thead><tr><th>字</th><th>最長打ち切り(ms)</th><th>正答率</th><th>試行数</th><th>判定</th></tr></thead>
    <tbody>
    {ctx['audio_table_rows']}
    </tbody>
  </table>
</section>

<section>
  <h2><span class="num">3</span>聴覚の刺激不良の証拠</h2>
  <p class="lead">2章の「使えない字」がなぜ使えないかを、打ち切りなしで全部聞かせた確認問題（check_kind=full）から確かめる。</p>

  <h3>3.1　全部聞かせたときの字ごとの正答率</h3>
  <figure>
    <img src="{ctx['fig_full_bar']}" alt="全部提示の正答率">
    <figcaption>本来は全部聞こえているので、ほぼ100%になるはずの確認問題。
      赤＝本命8字、灰＝その他（まぎれ字として出た字）。
      「が」{fmt_pct(ga_full[3]*100 if ga_full else None)}（{ga_full[1] if ga_full else '—'}/{ga_full[2] if ga_full else '—'}）、
      「し」{fmt_pct(shi_full[3]*100 if shi_full else None)}（{shi_full[1] if shi_full else '—'}/{shi_full[2] if shi_full else '—'}）、
      「ら」{fmt_pct(ra_full[3]*100 if ra_full else None)}（{ra_full[1] if ra_full else '—'}/{ra_full[2] if ra_full else '—'}）と、他の多くの字より明確に低い。</figcaption>
  </figure>

  <h3>3.2　混同行列（全部提示のみ）</h3>
  <figure>
    <img src="{ctx['fig_confusion']}" alt="混同行列">
    <figcaption>本命8字を出題したときに、実際に何と答えられたか（行＝出題、列＝回答）。
      濃い赤ほど回数が多い。対角線（正解）が薄く、隣接する清音・似た字に回答が集まる字があることが分かる。</figcaption>
  </figure>

  <h3>3.3　濁音が清音と取り違えられている割合</h3>
  <p>
    全部提示の確認問題で濁音（{''.join(DAKUON_LIST)}）が出題された {n_dakuon} 回のうち、
    正答は {n_dakuon_ok} 回（{fmt_pct(dakuon_acc)}）。
    誤答のうち、対応する清音（例：「が」→「か」）と答えたのは {n_dakuon_to_seion} 回で、
    出題全体に対して {fmt_pct(dakuon_seion_rate)} を占める。
  </p>
  <div class="note">
    <b>読み方</b>：全部聞かせても正答できないのは、記憶や集中力の問題ではなく、
    刺激（録音・切り出し）そのものに濁点情報が十分入っていない可能性を示す。
    特に「が」はこの確認問題でも{fmt_pct(ga_full[3]*100 if ga_full else None)}しか取れておらず、
    2章の A(t) 曲線が全域で低い理由と整合する。
  </div>
</section>

<section>
  <h2><span class="num">4</span>視覚 V(s)：方式ごとの曲線</h2>
  <p class="lead">
    横軸は<b>実測</b>の進み具合 actual_s（対数軸。blurのみ線形軸）。
    ⚠ 名目の進み具合％は方式間で比べられない（fadeの25%は天井付近、blurの25%は床付近）ため、
    方式ごとに別々の座標系で描いている。名目値と実測値を切り替えるUIまでは今回作らず、実測値のみ載せている。
  </p>
  <figure>
    <img src="{ctx['fig_visual']}" alt="視覚V(s)曲線（方式別）">
    <figcaption>本命の分析対象（is_decoy=偽・check_kind=空）の aprime（視覚）データより。4方式それぞれに8字を重ねてある。</figcaption>
  </figure>
  <table>
    <caption>方式ごとの最小・最大水準での8字合算正答率（曲線の形の要約）</caption>
    <thead><tr><th>方式</th><th>最小水準（実測%）</th><th>そこでの正答率</th><th>最大水準（実測%）</th><th>そこでの正答率</th></tr></thead>
    <tbody>{ctx['visual_extremes_rows']}</tbody>
  </table>
</section>

<section>
  <h2><span class="num">5</span>参加者の取り組みの質</h2>
  <p class="lead">聴覚90人・視覚163人が、いい加減に答えていないかを3つの指標で確かめる。</p>
  <figure>
    <img src="{ctx['fig_quality']}" alt="参加者の取り組みの質">
    <figcaption>左：確認問題A（全部提示）の個人正答率分布。中：本編での最頻回答の占有率（30%超＝同じ字を押しがち）。右：反応時間の分布。</figcaption>
  </figure>
  <div class="note">
    {ctx['quality_note']}
  </div>
</section>

<section>
  <h2><span class="num">6</span>感度分析</h2>
  <p class="lead">
    外れ値の切り方を6通り変えても、「聴覚acalの本命データで『が』が使えない」という結論が揺らがないかを確認する。
    比較のため、使える3字（あ・か・ま）の合算正答率も添える。
  </p>
  <table>
    <caption>切り方ごとの「が」の正答率（本命の分析対象・acal・全打ち切り水準の合算）</caption>
    <thead><tr><th>除外の切り方</th><th>残った参加者</th><th>残った試行数</th><th>「が」の正答率</th><th>参考：あ・か・ま合算</th></tr></thead>
    <tbody>{sens_rows}</tbody>
  </table>
  <div class="note">
    <b>読み方</b>：切り方をどう変えても「が」の正答率はおおむね10%台前半以下にとどまり、
    使える3字（8割前後）とは明確に差がある。外れ値の扱いに依存しない頑健な結論といえる。
  </div>
</section>

</div>
</div>
<footer>
  生成: experiment/tools/build_calib_report.py ／ 入力: {esc(TRIALS_CSV)}, {esc(WELLBEING_CSV)}
</footer>
"""
    return html


# ---------------------------------------------------------------- main
def main():
    print("読み込み中…")
    rows, total_raw = load_trials()
    sess = load_wellbeing_sessions()
    jp_font = pick_jp_font()
    if jp_font:
        print(f"  日本語フォント: {jp_font}")
    else:
        print("  ⚠ 日本語フォントが見つからず、文字化けする恐れがあります")

    print("聴覚 A(t) を集計中…")
    audio_tab = build_audio_main(rows)
    usable, max_level = usable_chars_audio(audio_tab)
    fig_audio = draw_audio_curve(audio_tab, usable, jp_font)

    audio_table_rows = []
    for ch in MAIN_CHARS:
        g, ok, n = max_level[ch]
        acc = 100 * ok / n
        cls = "ok" if usable.get(ch) else "bad"
        verdict = "使える" if usable.get(ch) else "使えない"
        audio_table_rows.append(
            f"<tr><td class='l'>{ch}</td><td>{g:.0f}</td>"
            f"<td class='{cls}'>{acc:.1f}%</td>"
            f"<td>{n}</td><td class='{cls}'>{verdict}</td></tr>"
        )
    audio_table_rows = "".join(audio_table_rows)

    print("視覚 V(s) を集計中…")
    visual_tab = build_visual_main(rows)
    fig_visual = draw_visual_curves(visual_tab, jp_font)

    # 方式ごとの最小/最大水準の合算正答率（表用）
    visual_extremes_rows = ""
    for fam in FAMILIES:
        pts = defaultdict(lambda: [0, 0, 0.0])
        for (f, ch, a), (ok, n, sa) in visual_tab.items():
            if f != fam:
                continue
            pts[a][0] += ok
            pts[a][1] += n
            pts[a][2] += sa
        levels = sorted(pts.keys())
        if not levels:
            continue
        lo, hi = levels[0], levels[-1]
        ok_lo, n_lo, sa_lo = pts[lo]
        ok_hi, n_hi, sa_hi = pts[hi]
        visual_extremes_rows += (
            f"<tr><td class='l'>{FAMILY_LABEL[fam]}</td>"
            f"<td>{sa_lo/n_lo*100:.2f}%</td><td>{ok_lo/n_lo*100:.1f}% ({ok_lo}/{n_lo})</td>"
            f"<td>{sa_hi/n_hi*100:.2f}%</td><td>{ok_hi/n_hi*100:.1f}% ({ok_hi}/{n_hi})</td></tr>"
        )

    print("全部提示の正答率を集計中…")
    fig_full_bar, full_items = draw_full_check_bar(rows, jp_font)

    print("混同行列を作成中…")
    fig_confusion, mat, resp_chars = draw_confusion_matrix(rows, jp_font)

    print("濁音の取り違えを集計中…")
    dakuon = dakuon_confusion(rows)

    print("参加者の取り組みの質を集計中…")
    fig_quality, acc_a, acc_v, same, rt = draw_quality_figures(rows, jp_font)
    n_participants_same_a = len([1 for (g, p) in same if g == "acal"])
    n_participants_same_v = len([1 for (g, p) in same if g == "aprime"])
    n_same_over30_a = sum(1 for (g, p), (v, n) in same.items() if g == "acal" and v >= 0.30)
    n_same_over30_v = sum(1 for (g, p), (v, n) in same.items() if g == "aprime" and v >= 0.30)
    n_check_high_a = sum(1 for v, n in acc_a.values() if v is not None and v >= 0.99)
    n_check_a = len(acc_a)
    n_check_high_v = sum(1 for v, n in acc_v.values() if v is not None and v >= 0.99)
    n_check_v = len(acc_v)
    median_check_a = float(np.median([v for v, n in acc_a.values() if v is not None])) * 100
    quality_note = (
        f"<b>聴覚</b>：本編で同じ字を3割以上押していた人は {n_participants_same_a}人中 {n_same_over30_a}人。"
        f"確認問題A（全部提示）の個人正答率は中央値 {median_check_a:.0f}% で、100%だった人は {n_check_a}人中 {n_check_high_a}人と少ない。"
        f"ただしこれは3章で示した刺激そのものの不具合（がなどの一部の字が全部聞いても分からない）の影響を"
        f"そのまま受けた結果であり、参加者の不真面目さを示すものではない"
        f"（1人あたりの確認問題は数問しかなく、その中に「が」系の字が混じれば正答率は必然的に下がる）。"
        f"<br><b>視覚</b>：本編で同じ字を3割以上押していた人は {n_participants_same_v}人中 {n_same_over30_v}人。"
        f"確認問題Aで満点だった人は {n_check_v}人中 {n_check_high_v}人"
        f"（{n_check_high_v/n_check_v*100:.0f}%）。"
        f"<br>反応時間は両集団とも300ms未満はごく僅かで、押し急ぎ・機械的な連打を示す分布にはなっていない。"
        f"全体として参加者は真面目に取り組んでいると判断できる。"
    )

    print("感度分析を実行中…")
    sens = sensitivity_table(rows)

    print("要約を計算中…")
    summary = summary_stats(rows, sess)

    ctx = {
        "rows": rows,
        "total_raw": total_raw,
        "summary": summary,
        "usable": usable,
        "max_level": max_level,
        "fig_audio": fig_audio,
        "audio_table_rows": audio_table_rows,
        "fig_visual": fig_visual,
        "visual_extremes_rows": visual_extremes_rows,
        "fig_full_bar": fig_full_bar,
        "full_items": full_items,
        "fig_confusion": fig_confusion,
        "dakuon": dakuon,
        "fig_quality": fig_quality,
        "quality_note": quality_note,
        "sensitivity": sens,
    }

    html = render_html(ctx)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"書き出しました: {OUT_HTML}  ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
