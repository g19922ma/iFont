#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自然音声の通し録音を 1かなずつに切り出し・測定し、人が耳で確認するページを作る
=============================================================================

対象: project/録音手順_自然音声12字.md の手順で録った「五十音を通しで複数周読んだ」1本の録音。
正本: project/実験計画書_転写検証.md 3.4節（テイク選択・acoustic onset・QCの定義）。

やること（1コマンドで通す）:
  1. m4a などを 48kHz/16bit/mono の WAV に変換（ffmpeg。無ければ afconvert）
  2. 無音区間で自動切り出し（短時間エネルギー。区間の前後に余白 pad_ms を残す）
  3. 区間ごとの音響測定（peak / RMS / クリッピング標本数 / 長さ）
  4. acoustic onset の自動検出（計画書3.4: 短い窓のエネルギーが背景雑音床 +10dB を
     一定時間連続で超えた最初の時点。時間0＝onset にするための値）
  5. 読み順の推定 — 五十音表の並びを「期待される母音の並び」に直し、各区間から測った
     フォルマント（声道の共鳴周波数。母音ごとに特徴がある）とDPで対応づける。
     周回ごとに「余分な区間（雑音・言い直し）」がどこかを推定して仮ラベルを埋める。
  5b. 読み順の乱れ（隣り合う2字が入れ替わって読まれた）の検定。
     話者から申告のあった組（REPORTED_SWAPS）は、音響がはっきり支持する周だけ仮ラベルを
     入れ替え、支持しない周も含めて全周に「要確認」の印をつける。
     申告のない組も隣接ペアを総当たりして疑いに印をつける（こちらは自動では入れ替えない）。
  6. テイク選択（事前基準）: 同じかなの回のうち、雑音・音割れの回を除き、
     残りから長さが中央値に最も近い回を機械的に採用
  7. 確認ページ recordings_raw/review.html を書き出す（音声を data URI で埋めた自己完結1ファイル）

⚠ 音声ファイルはリポジトリにコミットしない（recordings_raw/ は .gitignore 済み）。
   このスクリプトと QCレポートだけをコミットする。

実行例:
  python3 experiment/tools/segment_natural_recording.py \
      --input recordings_raw/五十音読み上げ_20260820.m4a

主なオプション（既定値は 20260820 の録音に合わせてある）:
  --hpf-hz 120        検出用のハイパスフィルタ。この録音は 50Hz の電源ハム（ブーン音）が
                      大きく、素の波形だと「無音」も -27dBFS ほどある。ハムを削ってから
                      エネルギーを見ないと区間検出も onset検出も成立しない。
                      ※ 切り出す音・測定する音は素のまま（フィルタは検出にしか使わない）
  --thr-offset-db 10  背景雑音床から何dB上を「音あり」とみなすか（計画書3.4の +10dB）
  --merge-ms 250      これより短い無音は同じ発話の中とみなして繋ぐ（破裂音の閉鎖など）
  --min-len-ms 80     これより短い区間は捨てる（クリック雑音よけ）
  --pad-ms 50         切り出し区間の前後に残す余白
  --pass-gap-s 1.6    これより長い無音を「周回の切れ目」とみなす
"""

import argparse
import base64
import csv
import io
import json
import math
import os
import shutil
import subprocess
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfiltfilt, lfilter, resample_poly
from scipy.linalg import solve_toeplitz

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# ---------------------------------------------------------------------------
# 五十音表の並び（この録音で話者が読んだ順の仮説）
# 手順書は68音（を・ぢ・づ・ゔ を除く）を指定したが、話者は五十音表をそのまま
# 読んでおり を・ぢ・づ も入って71音になっている。余分な3音は使わなければよいので
# ここでは「読まれた通りの71音」を既定の並びとする。
# ---------------------------------------------------------------------------
KANA71 = (
    list("あいうえお") + list("かきくけこ") + list("さしすせそ")
    + list("たちつてと") + list("なにぬねの") + list("はひふへほ")
    + list("まみむめも") + list("やゆよ") + list("らりるれろ")
    + ["わ", "を", "ん"]
    + list("がぎぐげご") + list("ざじずぜぞ") + list("だぢづでど")
    + list("ばびぶべぼ") + list("ぱぴぷぺぽ")
)
# 各かなの母音（N＝撥音「ん」。母音を持たないので別扱い）
VOWEL71 = ("aiueo" * 7) + "auo" + "aiueo" + "aoN" + ("aiueo" * 5)

# 実験で本当に必要な68音（を・ぢ・づ を除く）
KANA68 = [k for k in KANA71 if k not in ("を", "ぢ", "づ")]
# ターゲット候補12字（手順書。特に丁寧に録ってもらった字）
PRIORITY12 = list("あいかがぱばただしすまな")

assert len(KANA71) == 71 and len(VOWEL71) == 71
assert len(KANA68) == 68


# ---------------------------------------------------------------------------
# 入出力
# ---------------------------------------------------------------------------
def decode_to_wav(src, dst, sr=48000):
    """m4a等 → 48kHz/16bit/mono WAV。ffmpeg があれば使い、無ければ afconvert。"""
    if src.lower().endswith(".wav"):
        # すでにWAVでも、レートやビット深度を揃えるため通す
        pass
    if shutil.which("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", src, "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", dst],
            check=True)
    elif shutil.which("afconvert"):
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{sr}", "-c", "1", src, dst],
            check=True)
    else:
        sys.exit("ffmpeg も afconvert も見つかりません")
    return dst


def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            sys.exit(f"16bit WAV を想定しています: {path}")
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        if w.getnchannels() > 1:
            x = x.reshape(-1, w.getnchannels()).mean(axis=1)
    return x.astype(np.float64) / 32768.0, sr


def wav_bytes(x_int16, sr):
    """int16 配列 → WAV のバイト列（data URI 用）"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(x_int16.tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 区間検出
# ---------------------------------------------------------------------------
def frame_db(sig, sr, frame_ms):
    fl = max(1, int(round(frame_ms / 1000.0 * sr)))
    n = len(sig) // fl
    if n == 0:
        return np.array([-120.0]), fl
    f = sig[:n * fl].reshape(n, fl)
    rms = np.sqrt((f ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9)), fl


def detect_segments(det, sr, args):
    """det: 検出用（ハイパス済み）の波形。→ [(start_sample, end_sample), ...]"""
    db, fl = frame_db(det, sr, 10.0)
    floor_db = float(np.percentile(db, args.floor_pct))
    thr = floor_db + args.thr_offset_db
    active = np.where(db > thr)[0]
    if len(active) == 0:
        sys.exit("発話区間が検出できませんでした。--thr-offset-db を下げてください。")
    merge_fr = max(1, int(round(args.merge_ms / 10.0)))
    runs = []
    s = p = active[0]
    for i in active[1:]:
        if i - p > merge_fr:
            runs.append((s, p))
            s = i
        p = i
    runs.append((s, p))
    min_fr = max(1, int(round(args.min_len_ms / 10.0)))
    runs = [(a, b) for a, b in runs if (b - a + 1) >= min_fr]
    segs = [(a * fl, min((b + 1) * fl, len(det))) for a, b in runs]
    return segs, floor_db, thr


def split_passes(segs, sr, pass_gap_s):
    """周回（読み直しの周）の切れ目で分ける"""
    passes = [[]]
    prev_end = None
    for a, b in segs:
        if prev_end is not None and (a - prev_end) / sr > pass_gap_s:
            passes.append([])
        passes[-1].append((a, b))
        prev_end = b
    return [p for p in passes if p]


# ---------------------------------------------------------------------------
# acoustic onset（計画書3.4）
# ---------------------------------------------------------------------------
def short_time_db(sig, sr, win_ms, hop_ms):
    """窓長 win_ms・刻み hop_ms の短時間エネルギー（dBFS）"""
    wl = max(1, int(round(win_ms / 1000.0 * sr)))
    hp = max(1, int(round(hop_ms / 1000.0 * sr)))
    m = (len(sig) - wl) // hp + 1
    if m < 1:
        return np.array([-120.0]), hp
    idx = np.arange(m)[:, None] * hp + np.arange(wl)[None, :]
    rms = np.sqrt((sig[idx] ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9)), hp


def detect_onset(det, sr, seg_start, seg_end, args):
    """
    計画書3.4 の acoustic onset。
    短時間エネルギーが「背景雑音床 +10dB」を onset_sustain_ms 連続で超えた最初の時点。

    背景雑音床は区間の直前 noise_win_ms（＝発話と発話のあいだの無音）から測る（区間ごと）。

    ※窓長について: 計画書の文言は「1ms窓」だが、1msのRMSは発話の途中でもしきい値を
      またいで激しく上下するため「連続して超える」がほとんど成立しない（実測: この録音で
      弱い子音の頭を飛ばして母音まで進んでしまう例が20件）。そこで**時間分解能は1ms
      （刻み hop=1ms）のまま、窓長だけ 5ms** にして平滑化している。
      計画書どおりの1ms窓で出したい場合は --onset-win-ms 1 を指定する。

    返り値: (onsetの絶対標本位置, 背景雑音床dB, しきい値dB, 見つかったか)
    """
    # 背景雑音床：区間開始の直前を使う（直前が足りなければ取れるだけ）
    nw = int(args.noise_win_ms / 1000.0 * sr)
    guard = int(0.005 * sr)
    n0 = max(0, seg_start - nw - guard)
    n1 = max(n0 + 1, seg_start - guard)
    noise = det[n0:n1]
    if len(noise) >= int(args.onset_win_ms / 1000.0 * sr):
        ndb, _ = short_time_db(noise, sr, args.onset_win_ms, args.onset_hop_ms)
        floor_db = float(np.median(ndb))
    else:
        floor_db = -80.0
    thr = floor_db + args.thr_offset_db

    # 探索範囲：区間開始の少し手前から区間の終わりまで
    s0 = max(0, seg_start - int(args.onset_lookback_ms / 1000.0 * sr))
    s1 = min(len(det), max(seg_end, seg_start + int(0.05 * sr)))
    db, hp = short_time_db(det[s0:s1], sr, args.onset_win_ms, args.onset_hop_ms)
    need = max(1, int(round(args.onset_sustain_ms / args.onset_hop_ms)))
    above = db > thr
    run = 0
    for i, v in enumerate(above):
        if v:
            run += 1
            if run >= need:
                return s0 + (i - need + 1) * hp, floor_db, thr, True
        else:
            run = 0
    return seg_start, floor_db, thr, False


# ---------------------------------------------------------------------------
# 母音の推定（読み順の照合用）
# ---------------------------------------------------------------------------
def formants(raw, sr, a, b):
    """区間のいちばん大きい60msから LPC でフォルマント（F1,F2）を推定"""
    seg = raw[a:b]
    if len(seg) < int(0.02 * sr):
        return (0.0, 0.0)
    wl = int(0.06 * sr)
    if len(seg) <= wl:
        sg = seg
    else:
        e = np.convolve(seg ** 2, np.ones(wl) / wl, "valid")
        c = int(np.argmax(e))
        sg = seg[c:c + wl]
    sg = resample_poly(sg, 1, 4)          # 12 kHz に落として低次の共鳴だけ見る
    fs = sr / 4.0
    sg = lfilter([1, -0.97], [1], sg) * np.hamming(len(sg))
    order = 12
    if len(sg) <= order + 1:
        return (0.0, 0.0)
    r = np.correlate(sg, sg, "full")[len(sg) - 1: len(sg) + order]
    if r[0] <= 0:
        return (0.0, 0.0)
    r = r / r[0]
    r[0] += 1e-4
    try:
        a_lpc = np.concatenate([[1.0], -solve_toeplitz((r[:order], r[:order]), r[1:order + 1])])
    except Exception:
        return (0.0, 0.0)
    rts = np.roots(a_lpc)
    rts = rts[np.imag(rts) > 0]
    f = sorted(np.arctan2(np.imag(rts), np.real(rts)) * fs / (2 * np.pi))
    f = [v for v in f if 200 < v < 4500]
    return (float(f[0]) if f else 0.0, float(f[1]) if len(f) > 1 else 0.0)


DEFAULT_CENTROIDS = {  # (F1,F2) の目安。話者ごとに下で測り直す
    "a": (750.0, 1625.0), "i": (415.0, 2640.0), "u": (425.0, 2010.0),
    "e": (470.0, 2385.0), "o": (476.0, 987.0), "N": (270.0, 1620.0),
}


def vowel_cost(f, v, cent):
    if f[0] <= 0:
        return 2.0
    c = cent.get(v, DEFAULT_CENTROIDS[v])
    return (math.log(f[0] / c[0])) ** 2 + 2.0 * (math.log(max(f[1], 100.0) / c[1])) ** 2


def align_pass(obs_formants, cent, ins_cost=1.2):
    """
    観測した区間列を「五十音71音の母音列」に対応づける（挿入のみ許すDP）。
    区間数 >= 71 が前提。返り値: [かなのindex or None(＝余分な区間), ...]
    """
    n, M = len(obs_formants), len(VOWEL71)
    if n < M:
        # 足りない場合は素直に前から割り当て（人が直す前提）
        return list(range(n))
    D = np.full((n + 1, M + 1), 1e9)
    B = np.zeros((n + 1, M + 1), dtype=np.int8)
    D[0, 0] = 0.0
    for i in range(n + 1):
        for j in range(M + 1):
            if i == 0 and j == 0:
                continue
            best, bk = 1e9, 0
            if i > 0 and j > 0:
                c = D[i - 1, j - 1] + vowel_cost(obs_formants[i - 1], VOWEL71[j - 1], cent)
                if c < best:
                    best, bk = c, 1
            if i > 0:
                c = D[i - 1, j] + ins_cost
                if c < best:
                    best, bk = c, 2
            D[i, j] = best
            B[i, j] = bk
    i, j = n, M
    out = []
    while i > 0:
        if B[i, j] == 1:
            out.append(j - 1)
            i -= 1
            j -= 1
        else:
            out.append(None)
            i -= 1
    out.reverse()
    return out


# ---------------------------------------------------------------------------
# 読み順の乱れ（隣り合う2字が入れ替わって読まれた）の検出
# ---------------------------------------------------------------------------
# 話者からの申告（2026-08-20）: 「が」と「ぎ」を読む順番が逆だった。
# 申告のあった組は、音響が一致していてもいなくても**必ず要確認の印をつける**。
# 音響がはっきり入れ替わりを支持する周だけ、仮ラベルを実際に入れ替える。
REPORTED_SWAPS = [("が", "ぎ")]

# 入れ替えたほうがこれだけコストが下がるなら「入れ替わっている」と判断する
SWAP_APPLY_MARGIN = 1.0   # 申告のあった組を実際に入れ替える基準（はっきりした差だけ）
SWAP_FLAG_MARGIN = 0.3    # 印だけつける基準（申告のない組も走査する）


def swap_gain(rows_in_pass, j, order, cent):
    """
    その周の j 番目と j+1 番目の割り当てを入れ替えたら、母音の当てはまりが
    どれだけ良くなるか。正なら「入れ替えたほうが妥当」。
    """
    if j + 1 >= len(order) or j + 1 >= len(rows_in_pass):
        return None
    a, b = rows_in_pass[j], rows_in_pass[j + 1]
    fa, fb = (a["f1"], a["f2"]), (b["f1"], b["f2"])
    va, vb = kana_vowel(order[j]), kana_vowel(order[j + 1])
    now = vowel_cost(fa, va, cent) + vowel_cost(fb, vb, cent)
    swapped = vowel_cost(fa, vb, cent) + vowel_cost(fb, va, cent)
    return now - swapped


def kana_vowel(k):
    """かな1字 → その母音（Nは撥音「ん」）"""
    try:
        return VOWEL71[KANA71.index(k)]
    except ValueError:
        return "a"


def apply_order_corrections(rows_in_pass, cent):
    """
    1周ぶんの割り当てに対して:
      1. 申告のあった組（REPORTED_SWAPS）を検定し、音響がはっきり支持するなら入れ替える。
         支持しなくても両方に「要確認」の印をつける。
      2. 申告のない組も含めて隣接ペアを総当たりし、入れ替えたほうが妥当なものに印をつける
         （こちらは**自動では入れ替えない**。人が耳で判断する）
    返り値: (この周の並び order, 適用した入れ替えの記録)
    """
    labeled = [r for r in rows_in_pass if r.get("label")]
    order = [r["label"] for r in labeled]
    applied = []

    # 1. 申告のあった組
    for k1, k2 in REPORTED_SWAPS:
        if k1 not in order or k2 not in order:
            continue
        j = order.index(k1)
        if j + 1 >= len(order) or order[j + 1] != k2:
            continue          # 隣り合っていない＝この周では別の乱れ方をしている
        gain = swap_gain(labeled, j, order, cent)
        for r in (labeled[j], labeled[j + 1]):
            r.setdefault("flags", []).append("order_swap_reported")
            r["swap_gain"] = None if gain is None else round(gain, 2)
        if gain is not None and gain > SWAP_APPLY_MARGIN:
            order[j], order[j + 1] = order[j + 1], order[j]
            for t, r in ((j, labeled[j]), (j + 1, labeled[j + 1])):
                r["gojuon_label"] = r["label"]      # 入れ替える前（五十音表そのままの並び）
                r["label"] = r["auto_label"] = order[t]
                # 入れ替え後のラベルで当てはまりを測り直す（古い値のままだと
                # 「ラベル要確認」の印が入れ替え前の判断で残ってしまう）
                r["align_cost"] = round(
                    vowel_cost((r["f1"], r["f2"]), kana_vowel(order[t]), cent), 2)
            for r in (labeled[j], labeled[j + 1]):
                r["flags"].append("order_swap_applied")
            applied.append((k1, k2, round(gain, 2)))

    # 2. 申告のない組も走査（印だけ）
    for j in range(len(order) - 1):
        gain = swap_gain(labeled, j, order, cent)
        if gain is not None and gain > SWAP_FLAG_MARGIN:
            for r in (labeled[j], labeled[j + 1]):
                if "order_swap_suspected" not in r.get("flags", []) \
                        and "order_swap_applied" not in r.get("flags", []):
                    r.setdefault("flags", []).append("order_swap_suspected")
                    r["swap_gain"] = round(gain, 2)
    return order, applied


# ---------------------------------------------------------------------------
# テイク選択（事前基準）
# ---------------------------------------------------------------------------
def choose_takes(rows):
    """
    計画書3.4-2: 読み間違い・雑音・音割れの回を除き、
    残りから「長さが中央値に最も近い回」を機械的に採用。
    ここで機械が判定できるのは音割れ（クリッピング）と極端な短さだけなので、
    読み間違いの除外は確認ページで人が junk を立てて再計算する。
    """
    by_label = {}
    for r in rows:
        if r["junk"] or not r["label"]:
            continue
        by_label.setdefault(r["label"], []).append(r)
    for label, group in by_label.items():
        ok = [r for r in group if not r["clipped"]]
        if not ok:
            ok = group
        med = float(np.median([r["voiced_ms"] for r in ok]))
        best = min(ok, key=lambda r: (abs(r["voiced_ms"] - med), r["index"]))
        for r in group:
            r["selected"] = (r is best)
            r["take_median_ms"] = round(med, 1)
    return by_label


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="録音ファイル（m4a/wav など）")
    ap.add_argument("--outdir", default=None, help="出力先（既定: 入力と同じディレクトリ）")
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--hpf-hz", type=float, default=120.0,
                    help="検出用ハイパス（電源ハム除去）。切り出す音自体には掛けない")
    ap.add_argument("--floor-pct", type=float, default=10.0,
                    help="全体の何パーセンタイルを背景雑音床とみなすか（区間検出用）")
    ap.add_argument("--thr-offset-db", type=float, default=10.0,
                    help="背景雑音床から何dB上を「音あり」とみなすか")
    ap.add_argument("--merge-ms", type=float, default=250.0)
    ap.add_argument("--min-len-ms", type=float, default=80.0)
    ap.add_argument("--pad-ms", type=float, default=50.0)
    ap.add_argument("--pass-gap-s", type=float, default=1.6)
    ap.add_argument("--onset-win-ms", type=float, default=5.0,
                    help="onset検出の窓長。計画書の文言は1msだが1msRMSは上下が激しく"
                         "「連続して超える」が成立しないため既定は5ms（刻みは1ms）")
    ap.add_argument("--onset-hop-ms", type=float, default=1.0,
                    help="onset検出の時間分解能（刻み）")
    ap.add_argument("--onset-sustain-ms", type=float, default=10.0,
                    help="しきい値超えがこの長さ続いたら onset と認める")
    ap.add_argument("--onset-lookback-ms", type=float, default=80.0)
    ap.add_argument("--noise-win-ms", type=float, default=300.0)
    ap.add_argument("--no-wav-export", action="store_true",
                    help="切り出しWAVをディスクに書かない（review.html だけ作る）")
    args = ap.parse_args()

    src = os.path.abspath(args.input)
    outdir = os.path.abspath(args.outdir) if args.outdir else os.path.dirname(src)
    os.makedirs(outdir, exist_ok=True)
    segdir = os.path.join(outdir, "segments")
    if not args.no_wav_export:
        os.makedirs(segdir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(src))[0]
    wav_path = os.path.join(outdir, stem + ".wav")
    if not (src.lower().endswith(".wav") and os.path.abspath(src) == wav_path):
        print(f"[1/7] 変換 → {wav_path}")
        decode_to_wav(src, wav_path, args.sr)
    raw, sr = read_wav(wav_path)
    dur_s = len(raw) / sr
    print(f"      {sr} Hz / {dur_s:.2f} s / peak {np.max(np.abs(raw)):.3f}")

    # 検出用の信号（ハムを削る）
    sos = butter(4, args.hpf_hz / (sr / 2), "highpass", output="sos")
    det = sosfiltfilt(sos, raw)

    print("[2/7] 区間検出")
    segs, floor_db, thr = detect_segments(det, sr, args)
    passes = split_passes(segs, sr, args.pass_gap_s)
    print(f"      背景雑音床(HPF後) {floor_db:.1f} dBFS / しきい値 {thr:.1f} dBFS")
    print(f"      区間 {len(segs)} 個 / 周回 {len(passes)} 周 {[len(p) for p in passes]}")

    print("[3/7] 音響測定と onset 検出")
    pad = int(args.pad_ms / 1000.0 * sr)
    rows = []
    idx = 0
    for pi, part in enumerate(passes):
        for a, b in part:
            c0 = max(0, a - pad)
            c1 = min(len(raw), b + pad)
            clip_raw = raw[c0:c1]
            onset_abs, nfloor, nthr, ok = detect_onset(det, sr, a, b, args)
            onset_abs = max(c0, min(onset_abs, b))
            peak = float(np.max(np.abs(clip_raw))) if len(clip_raw) else 0.0
            rms = float(np.sqrt(np.mean(clip_raw[a - c0:b - c0] ** 2))) if b > a else 0.0
            n_clip = int(np.sum(np.abs(clip_raw) >= 0.999))
            f1, f2 = formants(raw, sr, a, b)
            rows.append(dict(
                index=idx, pass_no=pi + 1, seg_in_pass=len(rows),
                start_s=round(a / sr, 4), end_s=round(b / sr, 4),
                clip_start_s=round(c0 / sr, 4), clip_end_s=round(c1 / sr, 4),
                dur_ms=round((b - a) / sr * 1000, 1),
                onset_s=round(onset_abs / sr, 4),
                onset_ms=round((onset_abs - c0) / sr * 1000, 1),  # 切り出しクリップ先頭からのms
                onset_found=bool(ok),
                voiced_ms=round((b - onset_abs) / sr * 1000, 1),  # onset→区間末
                noise_floor_db=round(nfloor, 1),
                peak_dbfs=round(20 * math.log10(max(peak, 1e-9)), 2),
                rms_dbfs=round(20 * math.log10(max(rms, 1e-9)), 2),
                peak=round(peak, 5),
                n_clipped_samples=n_clip,
                clipped=bool(n_clip > 0),
                f1=round(f1, 1), f2=round(f2, 1),
                _c0=c0, _c1=c1, _a=a, _b=b,
            ))
            idx += 1
    # seg_in_pass を周回内の連番に直す
    for pi in range(len(passes)):
        k = 0
        for r in rows:
            if r["pass_no"] == pi + 1:
                r["seg_in_pass"] = k
                k += 1

    print("[4/7] 読み順の推定（五十音71音との照合）")
    # 話者ごとの母音の重心を、いちばん区間数が71に近い周から作る
    ref_pi = min(range(len(passes)), key=lambda i: abs(len(passes[i]) - 71))
    ref_rows = [r for r in rows if r["pass_no"] == ref_pi + 1]
    cent = dict(DEFAULT_CENTROIDS)
    if len(ref_rows) == 71:
        for v in set(VOWEL71):
            pts = [(ref_rows[i]["f1"], ref_rows[i]["f2"])
                   for i in range(71) if VOWEL71[i] == v and ref_rows[i]["f1"] > 0]
            if pts:
                cent[v] = (float(np.median([p[0] for p in pts])),
                           float(np.median([p[1] for p in pts])))
        print(f"      周{ref_pi+1} を基準に母音の重心を推定")
    n_extra = 0
    for pi in range(len(passes)):
        pr = [r for r in rows if r["pass_no"] == pi + 1]
        obs = [(r["f1"], r["f2"]) for r in pr]
        mapping = align_pass(obs, cent)
        for r, ki in zip(pr, mapping):
            if ki is None:
                r["label"] = ""
                r["auto_label"] = ""
                r["junk"] = True          # 余分な区間＝雑音・言い直しの候補
                r["auto_junk"] = True
                r["align_cost"] = None
                n_extra += 1
            else:
                r["label"] = KANA71[ki]
                r["auto_label"] = KANA71[ki]
                r["junk"] = False
                r["auto_junk"] = False
                r["align_cost"] = round(vowel_cost((r["f1"], r["f2"]), VOWEL71[ki], cent), 2)
        print(f"      周{pi+1}: 区間{len(pr)} → かな{sum(1 for r in pr if r['label'])} "
              f"/ 余分{sum(1 for r in pr if r['auto_junk'])}")

    print("[4b/7] 読み順の乱れ（隣り合う2字の入れ替わり）を検定")
    pass_orders = []
    for pi in range(len(passes)):
        pr = [r for r in rows if r["pass_no"] == pi + 1]
        order, applied = apply_order_corrections(pr, cent)
        pass_orders.append(order)
        for k1, k2, gain in applied:
            print(f"      周{pi+1}: 申告どおり「{k1}」と「{k2}」を入れ替えた"
                  f"（母音の当てはまりが {gain} 改善）")
        if not applied:
            for k1, k2 in REPORTED_SWAPS:
                if k1 in order and k2 in order:
                    print(f"      周{pi+1}: 申告のあった「{k1}」「{k2}」は音響上は入れ替わっていない"
                          f"（仮ラベルはそのまま。印だけ付けた）")
        n_susp = sum(1 for r in pr if "order_swap_suspected" in r.get("flags", []))
        if n_susp:
            print(f"      周{pi+1}: 入れ替わりの疑いで印を付けた区間 {n_susp} 個")

    # 印（フラグ）をまとめる。確認ページの絞り込みと QCレポートで使う
    for r in rows:
        f = r.setdefault("flags", [])
        if r.get("auto_junk"):
            f.append("extra")
        if r.get("clipped"):
            f.append("clipped")
        if not r.get("onset_found"):
            f.append("onset_not_found")
        elif r["onset_ms"] > args.pad_ms + 35:
            f.append("onset_late")
        if r.get("align_cost") is not None and r["align_cost"] > 1.0:
            f.append("low_confidence")
        if r["dur_ms"] > 500:
            f.append("long_segment")
        r["flags"] = sorted(set(f))

    print("[5/7] テイク選択（音割れ除外→長さが中央値に最も近い回）")
    for r in rows:
        r["selected"] = False
        r["take_median_ms"] = None
    groups = choose_takes(rows)
    print(f"      ラベル {len(groups)} 種 / 採用 {sum(1 for r in rows if r['selected'])} 個")

    print("[6/7] 切り出しWAVと波形サムネイル")
    audio_b64 = []
    waves = []
    for r in rows:
        seg_i16 = np.clip(raw[r["_c0"]:r["_c1"]] * 32768.0, -32768, 32767).astype("<i2")
        wb = wav_bytes(seg_i16, sr)
        audio_b64.append(base64.b64encode(wb).decode("ascii"))
        # 波形サムネイル（120本の min/max 包絡）
        n = len(seg_i16)
        nb = 120
        env = []
        step = max(1, n // nb)
        for i in range(nb):
            chunk = seg_i16[i * step:(i + 1) * step]
            if len(chunk) == 0:
                env.append([0, 0])
            else:
                env.append([int(chunk.min()), int(chunk.max())])
        waves.append(env)
        if not args.no_wav_export:
            fn = f"seg_{r['index']:03d}_p{r['pass_no']}.wav"
            with open(os.path.join(segdir, fn), "wb") as f:
                f.write(wb)
            r["wav"] = os.path.join("segments", fn)

    # CSV
    csv_path = os.path.join(outdir, "segments_summary.csv")
    fields = ["index", "pass_no", "seg_in_pass", "auto_label", "label", "junk", "selected",
              "start_s", "end_s", "dur_ms", "onset_s", "onset_ms", "onset_found", "voiced_ms",
              "peak_dbfs", "rms_dbfs", "peak", "n_clipped_samples", "clipped",
              "noise_floor_db", "f1", "f2", "align_cost", "take_median_ms",
              "flags", "swap_gain", "gojuon_label"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        wcsv = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        wcsv.writeheader()
        for r in rows:
            wcsv.writerow(dict(r, flags="|".join(r.get("flags", []))))
    print(f"      {csv_path}")

    print("[7/7] 確認ページ review.html")
    meta = dict(
        source=os.path.basename(src), wav=os.path.basename(wav_path),
        sr=sr, duration_s=round(dur_s, 2),
        n_segments=len(rows), n_passes=len(passes),
        pass_sizes=[len(p) for p in passes],
        pass_orders=pass_orders,
        reported_swaps=[list(t) for t in REPORTED_SWAPS],
        floor_db=round(floor_db, 1), thr_db=round(thr, 1),
        params={k: v for k, v in vars(args).items() if k != "input"},
        kana71=KANA71, kana68=KANA68, priority12=PRIORITY12,
        global_peak=round(float(np.max(np.abs(raw))), 5),
        global_clipped=int(np.sum(np.abs(raw) >= 0.999)),
    )
    clean = []
    for r in rows:
        clean.append({k: v for k, v in r.items() if not k.startswith("_")})
    html_path = os.path.join(outdir, "review.html")
    write_review_html(html_path, meta, clean, waves, audio_b64)
    size_mb = os.path.getsize(html_path) / 1e6
    print(f"      {html_path}  ({size_mb:.1f} MB)")

    json_path = os.path.join(outdir, "segments_auto.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "segments": clean}, f, ensure_ascii=False, indent=1)
    print(f"      {json_path}")
    print("\n開き方:  open " + html_path)


# ---------------------------------------------------------------------------
# 確認ページ
# ---------------------------------------------------------------------------
def write_review_html(path, meta, rows, waves, audio_b64):
    payload = json.dumps({"meta": meta, "rows": rows, "waves": waves},
                         ensure_ascii=False, separators=(",", ":"))
    audio = json.dumps(audio_b64, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("/*__DATA__*/", "window.DATA=" + payload + ";") \
                        .replace("/*__AUDIO__*/", "window.AUDIO=" + audio + ";")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>自然音声 切り出し確認 — 五十音読み上げ</title>
<style>
:root{
  --ink:#211d18; --ink-2:#6b6155; --line:#ddd4c6; --line-2:#efe8dc;
  --bg:#f7f3ec; --card:#fffdf8; --accent:#8a4b2a; --accent-soft:#f0e2d6;
  --ok:#3d6b45; --warn:#a8621b; --bad:#a32f2f;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,sans-serif;
  font-size:14px;line-height:1.5}
header{position:sticky;top:0;z-index:20;background:var(--card);
  border-bottom:1px solid var(--line);padding:12px 20px}
h1{margin:0 0 4px;font-size:17px;letter-spacing:.02em;font-weight:600}
.sub{color:var(--ink-2);font-size:12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
button{font:inherit;padding:5px 11px;border:1px solid var(--line);background:var(--card);
  color:var(--ink);border-radius:4px;cursor:pointer}
button:hover{background:var(--accent-soft);border-color:var(--accent)}
button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
.stat{font-variant-numeric:tabular-nums;color:var(--ink-2);font-size:12px;
  padding:3px 9px;background:var(--bg);border:1px solid var(--line-2);border-radius:3px}
main{padding:16px 20px 120px}
table{border-collapse:collapse;width:100%;background:var(--card)}
th{position:sticky;top:0;background:var(--card);text-align:left;font-size:11px;
  color:var(--ink-2);font-weight:600;padding:6px 7px;border-bottom:1px solid var(--line);
  white-space:nowrap}
td{padding:4px 7px;border-bottom:1px solid var(--line-2);vertical-align:middle;
  font-variant-numeric:tabular-nums}
tr.junk{opacity:.42;background:repeating-linear-gradient(45deg,transparent,transparent 6px,#0000000a 6px,#0000000a 12px)}
tr.sel td{background:#f2f7f2}
tr.playing td{background:var(--accent-soft)}
tr.passtop td{border-top:2px solid var(--accent)}
.k{font-size:20px;font-family:"Hiragino Mincho ProN",serif;letter-spacing:.05em}
.k.prio{color:var(--accent);font-weight:600}
input[type=text]{font:inherit;width:64px;padding:3px 5px;border:1px solid var(--line);
  border-radius:3px;background:var(--bg);text-align:center;font-size:16px}
input[type=text].edited{border-color:var(--accent);background:#fff;font-weight:600}
input.note{width:150px;font-size:12px;text-align:left}
.num{font-size:12px;color:var(--ink-2)}
.bad{color:var(--bad);font-weight:600}
.warn{color:var(--warn)}
.ok{color:var(--ok)}
svg.wf{display:block;background:#fbf8f2;border:1px solid var(--line-2);border-radius:3px}
.play{padding:2px 8px;font-size:12px;min-width:34px}
.play.onset{margin-left:4px;min-width:0;font-size:11px;color:var(--accent)}
.badge{display:inline-block;font-size:10px;padding:1px 5px;border-radius:8px;
  border:1px solid var(--line);color:var(--ink-2);background:var(--bg)}
.badge.sel{background:var(--ok);color:#fff;border-color:var(--ok)}
.fl{display:inline-block;font-size:10px;padding:1px 5px;margin:0 3px 2px 0;border-radius:3px;
  border:1px solid var(--line);background:var(--bg);color:var(--ink-2);white-space:nowrap}
.fl.f-rep{background:#8a4b2a;color:#fff;border-color:#8a4b2a;font-weight:600}
.fl.f-sus{background:#f3e0cd;color:#8a4b2a;border-color:#d8b898}
.fl.f-warn{background:#fdf1e0;color:var(--warn);border-color:#e8cfa8}
.fl.f-bad{background:#fbe6e6;color:var(--bad);border-color:#e5b8b8}
tr.swaprow td{background:#fcf1e7}
tr.swaprow.playing td{background:var(--accent-soft)}
.grp{background:var(--card);border:1px solid var(--line);border-radius:5px;
  padding:10px 12px;margin:0 0 10px}
.grp h3{margin:0 0 8px;font-size:15px;display:flex;align-items:center;gap:10px}
.grp .row{display:flex;align-items:center;gap:10px;padding:4px 0;border-top:1px solid var(--line-2);
  white-space:nowrap;font-size:12px}
.hint{color:var(--ink-2);font-size:12px;max-width:74ch;margin:0 0 12px}
.legend{font-size:11px;color:var(--ink-2);margin-top:6px}
.legend b{color:var(--ink)}
#groups{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px}
.filterbox{font:inherit;padding:4px 7px;border:1px solid var(--line);border-radius:4px;background:var(--card)}
</style>
</head>
<body>
<header>
  <h1>自然音声 切り出し確認 — <span id="src"></span></h1>
  <div class="sub" id="meta"></div>
  <div class="bar">
    <button id="tab-seq" class="on">時系列で確認</button>
    <button id="tab-grp">かなごとに聴き比べ</button>
    <span style="flex:1"></span>
    <select id="filter" class="filterbox">
      <option value="all">すべて表示</option>
      <option value="prio">優先12字だけ</option>
      <option value="junk">余分・除外だけ</option>
      <option value="clip">音割れありだけ</option>
      <option value="lowconf">自動ラベルが怪しいものだけ</option>
      <option value="swap">読み順の入れ替わり（申告＋疑い）だけ</option>
      <option value="onset">onsetが怪しいものだけ</option>
      <option value="edited">手で直したものだけ</option>
    </select>
    <span class="stat" id="counts"></span>
    <button id="export" class="primary">ラベル表を書き出す（JSON）</button>
  </div>
  <div class="legend">
    キー操作: <b>↑↓</b> 行を移動 / <b>Space</b> 全体を再生 / <b>o</b> onsetから再生 / <b>x</b> 除外の切り替え /
    ラベル欄に直接入力すると、その行だけ上書きされます（以降の行はずれません）。
    「除外」にすると、その周回の以降の行のラベルが1つずつ繰り上がります。
  </div>
</header>
<main>
  <p class="hint" id="hint"></p>
  <div id="seqview"><table id="tbl"><thead><tr>
    <th>#</th><th>周</th><th>開始</th><th>長さ</th><th>波形＋onset</th><th>再生</th>
    <th>自動</th><th>ラベル</th><th>除外</th><th>採用</th>
    <th>onset</th><th>発話長</th><th>peak</th><th>RMS</th><th>音割れ</th><th>印</th><th>メモ</th>
  </tr></thead><tbody id="tbody"></tbody></table></div>
  <div id="grpview" style="display:none"><div id="groups"></div></div>
</main>
<script>
/*__DATA__*/
/*__AUDIO__*/
</script>
<script>
const M=DATA.meta, ROWS=DATA.rows, WAVES=DATA.waves;
const KANA71=M.kana71, KANA68=new Set(M.kana68), PRIO=new Set(M.priority12);
// 周ごとの読み順。話者の申告と音響で「が」「ぎ」の入れ替わりを直した周があるので、
// 全周で同じ並びとは限らない
const ORDERS=M.pass_orders||[];
function orderOf(p){ return ORDERS[p-1] && ORDERS[p-1].length ? ORDERS[p-1] : KANA71; }
const FLAG_LABEL={
  order_swap_reported:'順番の申告あり', order_swap_applied:'申告どおり入替済',
  order_swap_suspected:'入替の疑い', low_confidence:'ラベル要確認',
  extra:'余分', clipped:'音割れ', onset_late:'onset遅い',
  onset_not_found:'onset未検出', long_segment:'区間が長い'};
const FLAG_CLASS={order_swap_reported:'f-rep',order_swap_applied:'f-rep',
  order_swap_suspected:'f-sus',low_confidence:'f-warn',clipped:'f-bad',
  onset_late:'f-warn',onset_not_found:'f-bad',extra:'f-dim',long_segment:'f-dim'};
const st=ROWS.map(r=>({junk:!!r.junk, manual:"", note:""}));
let cur=0;
// 再生は Web Audio（<audio>+data URI はタブの状態によって読み込まれないことがある）
let actx=null; const bufCache={}; let curSrc=null;
function ensureCtx(){
  if(!actx) actx=new (window.AudioContext||window.webkitAudioContext)();
  if(actx.state==='suspended') actx.resume();   // await しない（保留したまま返らないことがある）
  return actx;
}
async function getBuf(i){
  if(bufCache[i]) return bufCache[i];
  const bin=atob(AUDIO[i]); const u8=new Uint8Array(bin.length);
  for(let k=0;k<bin.length;k++) u8[k]=bin.charCodeAt(k);
  bufCache[i]=await ensureCtx().decodeAudioData(u8.buffer);
  return bufCache[i];
}

document.getElementById('src').textContent=M.source;
document.getElementById('meta').textContent=
  `${M.sr} Hz / ${M.duration_s} 秒 / 区間 ${M.n_segments} 個 / ${M.n_passes} 周 (${M.pass_sizes.join(' + ')}) `
  +`/ 全体peak ${(20*Math.log10(M.global_peak)).toFixed(2)} dBFS / 全体で振り切れた標本 ${M.global_clipped}`;
(function(){
  const sw=(M.reported_swaps||[]).map(t=>t.join('・')).join('、');
  const applied=ROWS.filter(r=>(r.flags||[]).includes('order_swap_applied'));
  let h='自動ラベルは「五十音表を'+M.n_passes+'周そのまま読んだ」という仮定でつけています。'
   +'上から順に再生して、聞こえた字と「ラベル」欄が合っているか確認してください。'
   +'雑音・言い直し・咳などで1字に対応しない区間は「除外」にすると、その周の以降のラベルが自動で繰り上がります。'
   +'（を・ぢ・づ は今回の実験では使いませんが、読まれているのでそのまま並べています）';
  if(sw){
    h+=' ／ 話者からの申告で「'+sw+'」の読む順番が逆だったとのことなので、この組は全周に印をつけました。'
      +'音響（母音の当てはまり）がはっきり入れ替わりを支持した周だけ仮ラベルを入れ替えてあります'
      +'（該当: '+(applied.length? applied.map(r=>'#'+r.index+'/周'+r.pass_no).join('・') : 'なし')+'）。'
      +'申告のない組も隣どうしの入れ替わりを総当たりで調べ、疑いのあるものに印をつけています'
      +'（こちらは自動では入れ替えていません）。絞り込みメニューの「読み順の入れ替わり」でまとめて出せます。';
  }
  document.getElementById('hint').textContent=h;
})();

// ---- ラベルの再計算：除外を飛ばして、周ごとに五十音順で割り当てる ----
function recompute(){
  const ptr={};
  ROWS.forEach((r,i)=>{
    const p=r.pass_no, ord=orderOf(p);
    if(ptr[p]===undefined) ptr[p]=0;
    if(st[i].junk){ r.label=""; return; }
    r.label = ptr[p]<ord.length ? ord[ptr[p]] : "";
    ptr[p]++;
  });
  ROWS.forEach((r,i)=>{ if(st[i].manual) r.label=st[i].manual; });
  chooseTakes();
}
// ---- テイク選択：音割れを除き、長さが中央値に最も近い回 ----
function chooseTakes(){
  const g={};
  ROWS.forEach((r,i)=>{ if(st[i].junk||!r.label) { r.selected=false; return; }
    (g[r.label]=g[r.label]||[]).push(i); });
  for(const lab in g){
    let idxs=g[lab].filter(i=>!ROWS[i].clipped);
    if(!idxs.length) idxs=g[lab];
    const ds=idxs.map(i=>ROWS[i].voiced_ms).sort((a,b)=>a-b);
    const med = ds.length%2 ? ds[(ds.length-1)/2] : (ds[ds.length/2-1]+ds[ds.length/2])/2;
    let best=idxs[0], bd=Infinity;
    idxs.forEach(i=>{const d=Math.abs(ROWS[i].voiced_ms-med); if(d<bd){bd=d;best=i;}});
    g[lab].forEach(i=>{ROWS[i].selected=(i===best); ROWS[i].take_median_ms=Math.round(med*10)/10;});
  }
  window.GROUPS=g;
}
async function play(i, fromOnset){
  const ctx=ensureCtx();
  if(curSrc){ try{curSrc.stop();}catch(e){} curSrc=null; }
  const buf=await getBuf(i);
  const src=ctx.createBufferSource(); src.buffer=buf; src.connect(ctx.destination);
  // fromOnset: 検出した onset から鳴らす。頭の子音が切れて聞こえたら onset が遅すぎる
  src.start(0, fromOnset ? Math.max(0, ROWS[i].onset_ms/1000) : 0);
  curSrc=src;
  document.querySelectorAll('tr.playing').forEach(e=>e.classList.remove('playing'));
  const tr=document.getElementById('r'+i); if(tr) tr.classList.add('playing');
}
function wfSvg(i){
  const env=WAVES[i], r=ROWS[i], W=190, H=34, n=env.length;
  const dur=(r.clip_end_s-r.clip_start_s)*1000;
  let up=[],dn=[];
  for(let k=0;k<n;k++){
    const x=(k/(n-1))*W;
    up.push(x.toFixed(1)+','+(H/2 - env[k][1]/32768*(H/2-1)).toFixed(1));
    dn.push(x.toFixed(1)+','+(H/2 - env[k][0]/32768*(H/2-1)).toFixed(1));
  }
  const ox = dur>0 ? (r.onset_ms/dur)*W : 0;
  const clipMark = r.clipped ? `<rect x="0" y="0" width="${W}" height="${H}" fill="#a32f2f" opacity=".07"/>` : '';
  return `<svg class="wf" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${clipMark}
   <line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}" stroke="#ddd4c6"/>
   <polyline points="${up.join(' ')}" fill="none" stroke="#5b544a" stroke-width=".8"/>
   <polyline points="${dn.join(' ')}" fill="none" stroke="#5b544a" stroke-width=".8"/>
   <line x1="${ox.toFixed(1)}" y1="0" x2="${ox.toFixed(1)}" y2="${H}" stroke="#c0392b" stroke-width="1.4"/>
  </svg>`;
}
function flagBadges(r){
  return (r.flags||[]).map(f=>{
    let t=FLAG_LABEL[f]||f;
    if(f==='order_swap_applied') t=`申告どおり入替済（${r.gojuon_label}→${r.label}）`;
    else if(f==='order_swap_reported' && !(r.flags||[]).includes('order_swap_applied'))
      t=`順番の申告あり・音響は現状を支持（入替えると${Math.abs(r.swap_gain).toFixed(2)}悪化）`;
    else if(f==='order_swap_suspected')
      t=`隣と入れ替わっている疑い（入替えると${(r.swap_gain).toFixed(2)}改善）`;
    return `<span class="fl ${FLAG_CLASS[f]||''}">${t}</span>`;
  }).join('');
}
function passOf(i){return ROWS[i].pass_no;}
function visible(i){
  const f=document.getElementById('filter').value, r=ROWS[i];
  if(f==='prio')   return PRIO.has(r.label);
  if(f==='junk')   return st[i].junk;
  if(f==='clip')   return r.clipped;
  if(f==='lowconf')return (r.align_cost===null)||(r.align_cost>0.6);
  if(f==='swap')   return (r.flags||[]).some(x=>x.startsWith('order_swap'));
  if(f==='onset')  return (r.flags||[]).some(x=>x==='onset_late'||x==='onset_not_found');
  if(f==='edited') return !!st[i].manual || st[i].junk!==!!r.junk;
  return true;
}
function render(){
  recompute();
  const tb=document.getElementById('tbody'); tb.innerHTML='';
  ROWS.forEach((r,i)=>{
    if(!visible(i)) return;
    const tr=document.createElement('tr'); tr.id='r'+i;
    if(st[i].junk) tr.classList.add('junk');
    if((r.flags||[]).some(x=>x.startsWith('order_swap'))) tr.classList.add('swaprow');
    if(r.selected) tr.classList.add('sel');
    if(i>0 && passOf(i)!==passOf(i-1)) tr.classList.add('passtop');
    const lc=(r.align_cost===null)?'':(r.align_cost>0.6?' warn':'');
    tr.innerHTML=
      `<td class="num">${r.index}</td>`
     +`<td class="num">${r.pass_no}</td>`
     +`<td class="num">${r.start_s.toFixed(2)}</td>`
     +`<td class="num">${Math.round(r.dur_ms)}</td>`
     +`<td>${wfSvg(i)}</td>`
     +`<td style="white-space:nowrap"><button class="play" data-p="${i}">▶</button>`
     +`<button class="play onset" data-p="${i}" data-o="1" title="検出したonsetから鳴らす（頭が切れて聞こえたらonsetが遅すぎる）">▶onset</button></td>`
     +`<td class="num${lc}">${r.auto_label||'—'}</td>`
     +`<td><input type="text" class="lab${st[i].manual?' edited':''}" data-i="${i}" value="${r.label||''}"></td>`
     +`<td style="text-align:center"><input type="checkbox" class="jk" data-i="${i}" ${st[i].junk?'checked':''}></td>`
     +`<td style="text-align:center">${r.selected?'<span class="badge sel">採用</span>':''}</td>`
     +`<td class="num">${r.onset_ms.toFixed(0)}${r.onset_found?'':'<span class="bad">?</span>'}</td>`
     +`<td class="num">${Math.round(r.voiced_ms)}</td>`
     +`<td class="num${r.peak_dbfs>-1?' bad':(r.peak_dbfs>-3?' warn':'')}">${r.peak_dbfs.toFixed(1)}</td>`
     +`<td class="num">${r.rms_dbfs.toFixed(1)}</td>`
     +`<td class="num${r.clipped?' bad':''}">${r.n_clipped_samples||''}</td>`
     +`<td>${flagBadges(r)}</td>`
     +`<td><input type="text" class="note nt" data-i="${i}" value="${st[i].note||''}" placeholder="気づいたこと"></td>`;
    tb.appendChild(tr);
  });
  updCounts();
  if(document.getElementById('grpview').style.display!=='none') renderGroups();
}
function updCounts(){
  const nj=st.filter(s=>s.junk).length;
  const lab={}; ROWS.forEach((r,i)=>{if(!st[i].junk&&r.label)lab[r.label]=(lab[r.label]||0)+1;});
  const missing=M.kana68.filter(k=>!lab[k]);
  const nsel=ROWS.filter(r=>r.selected).length;
  document.getElementById('counts').textContent=
    `除外 ${nj} / ラベル済 ${Object.keys(lab).length} 種 / 採用 ${nsel}`
    +(missing.length?` / ⚠68字のうち未取得 ${missing.length}(${missing.join('')})`:` / 68字すべてあり`);
}
function renderGroups(){
  const box=document.getElementById('groups'); box.innerHTML='';
  const order=KANA71.filter(k=>window.GROUPS[k]);
  const extra=Object.keys(window.GROUPS).filter(k=>!KANA71.includes(k));
  order.concat(extra).forEach(lab=>{
    const idxs=window.GROUPS[lab];
    const d=document.createElement('div'); d.className='grp';
    let h=`<h3><span class="k${PRIO.has(lab)?' prio':''}">${lab}</span>`
        +`<span class="num">${idxs.length}回 / 中央値 ${ROWS[idxs[0]].take_median_ms??'—'} ms</span>`
        +(KANA68.has(lab)?'':'<span class="badge">実験では未使用</span>')+`</h3>`;
    idxs.forEach(i=>{
      const r=ROWS[i];
      h+=`<div class="row"><button class="play" data-p="${i}">▶</button>`
        +`<button class="play onset" data-p="${i}" data-o="1" title="onsetから再生">▶on</button>`
        +`<span class="num">#${r.index} 周${r.pass_no}</span>`
        +wfSvg(i)
        +`<span class="num">${Math.round(r.voiced_ms)}ms</span>`
        +`<span class="num${r.peak_dbfs>-1?' bad':''}">${r.peak_dbfs.toFixed(1)}dB</span>`
        +(r.clipped?'<span class="bad">音割れ</span>':'')
        +(r.selected?'<span class="badge sel">採用</span>':'')
        +flagBadges(r)
        +`</div>`;
    });
    d.innerHTML=h; box.appendChild(d);
  });
}
document.addEventListener('click',e=>{
  const p=e.target.closest('.play'); if(p){ cur=+p.dataset.p; play(cur, !!p.dataset.o); }
});
document.addEventListener('change',e=>{
  if(e.target.classList.contains('jk')){ st[+e.target.dataset.i].junk=e.target.checked; render(); }
});
document.addEventListener('input',e=>{
  if(e.target.classList.contains('lab')){
    const i=+e.target.dataset.i, v=e.target.value.trim();
    const auto=(()=>{const s=st[i].manual;st[i].manual="";recompute();const a=ROWS[i].label;st[i].manual=s;recompute();return a;})();
    st[i].manual = (v && v!==auto) ? v : "";
    e.target.classList.toggle('edited', !!st[i].manual);
    recompute(); updCounts();
  }
  if(e.target.classList.contains('nt')) st[+e.target.dataset.i].note=e.target.value;
});
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT') return;
  if(e.key==='ArrowDown'){cur=Math.min(ROWS.length-1,cur+1);focusRow();e.preventDefault();}
  if(e.key==='ArrowUp'){cur=Math.max(0,cur-1);focusRow();e.preventDefault();}
  if(e.key===' '){play(cur,false);e.preventDefault();}
  if(e.key==='o'){play(cur,true);e.preventDefault();}
  if(e.key==='x'){st[cur].junk=!st[cur].junk;render();focusRow();e.preventDefault();}
});
function focusRow(){const tr=document.getElementById('r'+cur);
  if(tr){document.querySelectorAll('tr.playing').forEach(x=>x.classList.remove('playing'));
    tr.classList.add('playing'); tr.scrollIntoView({block:'center'});}}
document.getElementById('filter').addEventListener('change',render);
document.getElementById('tab-seq').onclick=()=>{
  document.getElementById('seqview').style.display='';document.getElementById('grpview').style.display='none';
  document.getElementById('tab-seq').classList.add('on');document.getElementById('tab-grp').classList.remove('on');};
document.getElementById('tab-grp').onclick=()=>{
  document.getElementById('seqview').style.display='none';document.getElementById('grpview').style.display='';
  document.getElementById('tab-grp').classList.add('on');document.getElementById('tab-seq').classList.remove('on');
  renderGroups();};
document.getElementById('export').onclick=()=>{
  recompute();
  const out={
    checked_at:new Date().toISOString(),
    source:M.source, sr:M.sr, params:M.params,
    note:'label＝確認後のかな。junk＝1字に対応しない区間。selected＝事前基準(音割れ除外→長さが中央値に最も近い回)で採用したテイク。onset_ms は切り出しクリップ先頭からのms。',
    segments:ROWS.map((r,i)=>({
      index:r.index, pass_no:r.pass_no, label:r.label, junk:st[i].junk,
      manual_label:st[i].manual||null, note:st[i].note||null, selected:!!r.selected,
      start_s:r.start_s, end_s:r.end_s, clip_start_s:r.clip_start_s, clip_end_s:r.clip_end_s,
      onset_s:r.onset_s, onset_ms:r.onset_ms, onset_found:r.onset_found,
      dur_ms:r.dur_ms, voiced_ms:r.voiced_ms, take_median_ms:r.take_median_ms,
      peak_dbfs:r.peak_dbfs, rms_dbfs:r.rms_dbfs, n_clipped_samples:r.n_clipped_samples,
      clipped:r.clipped, f1:r.f1, f2:r.f2, auto_label:r.auto_label, align_cost:r.align_cost,
      flags:r.flags||[], swap_gain:r.swap_gain??null, gojuon_label:r.gojuon_label??null
    }))};
  const b=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(b); a.download='labels_checked.json'; a.click();
};
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
