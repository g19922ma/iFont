#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
確定ラベル → 採用テイクの下処理 → onset表 → onset確認ページ
=============================================================

`segment_natural_recording.py` が作った自動ラベルに、**話者本人が耳で確認した訂正**を当てて
確定ラベル表を作り、そこから本番の刺激の素になる採用テイクを書き出す。

正本: `project/実験計画書_転写検証.md` 3.4節。QCの経緯は `project/録音QC_20260820.md`。

処理の順番（この順でないと意味が変わるので注意）:

  1. 確定ラベル — 自動ラベルに CONFIRMED_FIXES を当てる。除外を変えると
     その周の以降のラベルが繰り上がるので、**周ごとに番号を振り直す**。
     最後に「実験で使う68字が3回ずつ揃っているか」を検算する。
  2. テイク選択（事前基準・計画書3.4-2）— 音割れの回を除き、残りから
     **発話長が中央値に最も近い回**を機械的に採用。
  3. ハイパスフィルタ — 100Hz・4次バターワース・**ゼロ位相**（往復掛け）。
     この録音は50Hzの電源ハムでSN比が約10dBしかなく、そのままでは
     打ち切りの短い条件で唸りしか聞こえない恐れがある。話者の声の高さは216Hzなので
     100Hzで切っても声には掛からない。
     ※ゼロ位相にするのは、**位相のずれで音の立ち上がりが時間的にずれるのを防ぐため**。
       この実験は onset を0msの基準にするので、頭が数ms動くだけで測定が狂う。
  4. 音量合わせ — 1音まるごとに**一定の倍率**を掛けるだけ（音の中身の強弱の配分は変えない）。
     倍率は**必ず1.0以下**（増幅はしない＝音割れを増やさない）。
     そのため合わせる先は「全字の中でいちばん小さい字のRMS」になる。
  5. acoustic onset の再検出。
     ※検出に使うハイパスは配信する音(100Hz)とは**別**にしてある(既定150Hz)。
       100Hzだと50Hzハムの残りで背景雑音床が4〜7dB持ち上がり、しきい値(床+10dB)も
       その分きつくなるため、立ち上がりのなだらかな摩擦音(さ し す せ そ ふ へ)の頭を
       30〜50ms取りこぼす。150Hzならハムはほぼ消え、話者のF0(216Hz)には掛からない。
     ※さらに検出用ハイパスを120/150/200Hzと変えて onset のぶれ幅も測る。
       ぶれが大きい字＝「その字のonsetは1点に決まらない」という意味なので、
       計画書3.4-4が求める全数目視の重点対象になる。
  6. `adopted_onsets.json` と `onset_review.html` を書き出す。

⚠ 音声ファイルはリポジトリにコミットしない（`recordings_raw/` は .gitignore 済み）。

実行:
  python3 experiment/tools/build_adopted_stimuli.py
"""

import argparse
import base64
import json
import math
import os
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfiltfilt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from segment_natural_recording import (           # noqa: E402
    KANA68, KANA71, PRIORITY12, read_wav, wav_bytes, short_time_db, detect_onset,
)

# ---------------------------------------------------------------------------
# 話者本人による耳での確認結果（2026-08-20）
# ---------------------------------------------------------------------------
# 自動ラベルに対する訂正。ここに書いたもの以外は「自動のままで正しい」と本人が確認済み。
#
# 区間#116（周2・長さ90ms）は自動では「ろ」としていたが、実際には1字に対応しない区間だった。
# 自動処理もこの区間を「onsetが検出できない・異常に短い」と印をつけており、判断は一致した。
# これを除外に回すと周2の以降が1つずつ繰り上がり、#117が「ろ」、#118が「わ」になる。
# （#118 は自動では「余分」と判定していた区間）
CONFIRMED_FIXES = {
    116: {"junk": True,  "label": "",   "why": "1字に対応しない区間（長さ90ms・onset検出不能）"},
    117: {"junk": False, "label": "ろ", "why": "耳で確認。自動の「わ」から訂正"},
    118: {"junk": False, "label": "わ", "why": "耳で確認。自動では「余分」としていた区間"},
}
# 自動のままで正しいと本人が確認した箇所（記録用。処理は変えない）
CONFIRMED_OK = {
    121: "周2の「が」。自動のままで正しい（周1の入れ替わりは周2には及んでいない）",
    122: "周2の「ぎ」。自動のままで正しい",
    "pass1_swap": "周1の「が」「ぎ」の入れ替え（#48→ぎ・#49→が）は適用したままでよい",
    "others": "上記以外の区間・印はすべて問題なし",
}
CHECKED_BY = "話者本人（耳での全数確認）"
CHECKED_AT = "2026-08-20"

# ---------------------------------------------------------------------------
# 音の種類（8字選定の材料・onset確認の並べ替えに使う）
# 頭の子音がどういう音か。onsetの取りやすさは、ほぼこの分類で決まる。
# ---------------------------------------------------------------------------
SOUND_TYPE = {}
for _k in "あいうえお":
    SOUND_TYPE[_k] = ("母音", "声がいきなり始まる。onsetは取りやすい")
for _k in "かきくけこ":
    SOUND_TYPE[_k] = ("無声破裂音 /k/", "無音の閉鎖のあと破裂。破裂の瞬間が明確")
for _k in "たてと":
    SOUND_TYPE[_k] = ("無声破裂音 /t/", "無音の閉鎖のあと破裂。破裂の瞬間が明確")
for _k in "ぱぴぷぺぽ":
    SOUND_TYPE[_k] = ("無声破裂音 /p/", "無音の閉鎖のあと破裂。破裂の瞬間が明確")
for _k in "がぎぐげご":
    SOUND_TYPE[_k] = ("有声破裂音 /g/", "閉鎖中も声帯が鳴る（弱い低音）。どこを頭とするか要確認")
for _k in "でど":
    SOUND_TYPE[_k] = ("有声破裂音 /d/", "閉鎖中も声帯が鳴る（弱い低音）。どこを頭とするか要確認")
SOUND_TYPE["だ"] = ("有声破裂音 /d/", "閉鎖中も声帯が鳴る（弱い低音）。どこを頭とするか要確認")
for _k in "ばびぶべぼ":
    SOUND_TYPE[_k] = ("有声破裂音 /b/", "閉鎖中も声帯が鳴る（弱い低音）。どこを頭とするか要確認")
for _k in "さすせそ":
    SOUND_TYPE[_k] = ("無声摩擦音 /s/", "こすれる音がだんだん強くなる。頭がぼやけやすい")
SOUND_TYPE["し"] = ("無声摩擦音 /ɕ/", "こすれる音がだんだん強くなる。頭がぼやけやすい")
for _k in "はへほ":
    SOUND_TYPE[_k] = ("無声摩擦音 /h/", "息の音。とても弱く、頭が最もぼやけやすい")
SOUND_TYPE["ひ"] = ("無声摩擦音 /ç/", "息の音。とても弱く、頭が最もぼやけやすい")
SOUND_TYPE["ふ"] = ("無声摩擦音 /ɸ/", "息の音。とても弱く、頭が最もぼやけやすい")
SOUND_TYPE["ち"] = ("無声破擦音 /tɕ/", "閉鎖のあと破裂＋こすれる音")
SOUND_TYPE["つ"] = ("無声破擦音 /ts/", "閉鎖のあと破裂＋こすれる音")
for _k in "ざぜぞ":
    SOUND_TYPE[_k] = ("有声破擦音 /dz/", "声を伴う破擦。頭の位置が揺れやすい")
SOUND_TYPE["じ"] = ("有声破擦音 /dʑ/", "声を伴う破擦。頭の位置が揺れやすい")
SOUND_TYPE["ず"] = ("有声破擦音 /dz/", "声を伴う破擦。頭の位置が揺れやすい")
for _k in "なにぬねの":
    SOUND_TYPE[_k] = ("鼻音 /n/", "低くこもった声で始まる。エネルギーが小さく頭が取りにくい")
for _k in "まみむめも":
    SOUND_TYPE[_k] = ("鼻音 /m/", "低くこもった声で始まる。エネルギーが小さく頭が取りにくい")
SOUND_TYPE["ん"] = ("鼻音 /ɴ/", "低くこもった声だけ。母音がない")
for _k in "らりるれろ":
    SOUND_TYPE[_k] = ("弾き音 /ɾ/", "舌を弾く一瞬の音。短く弱い")
for _k in "やゆよ":
    SOUND_TYPE[_k] = ("半母音 /j/", "母音に近く、頭がなだらか")
SOUND_TYPE["わ"] = ("半母音 /w/", "母音に近く、頭がなだらか")
SOUND_TYPE["を"] = ("半母音 /w/", "母音に近く、頭がなだらか")
SOUND_TYPE["ぢ"] = ("有声破擦音 /dʑ/", "声を伴う破擦")
SOUND_TYPE["づ"] = ("有声破擦音 /dz/", "声を伴う破擦")

# 清濁のペア（この実験の中心。8字選定でいちばん効く材料）
VOICING_PAIRS = [("か", "が"), ("た", "だ"), ("ぱ", "ば")]


# ---------------------------------------------------------------------------
# 1. 確定ラベル
# ---------------------------------------------------------------------------
def build_confirmed_labels(auto):
    """自動ラベル + 本人確認の訂正 → 確定ラベル。周ごとに番号を振り直す。"""
    meta, rows = auto["meta"], auto["segments"]
    orders = meta.get("pass_orders") or []

    for r in rows:
        fix = CONFIRMED_FIXES.get(r["index"])
        r["confirmed_fix"] = None
        if fix:
            r["junk"] = fix["junk"]
            r["confirmed_fix"] = fix["why"]

    # 除外を反映して周ごとに順番に割り当て直す
    ptr = {}
    for r in rows:
        p = r["pass_no"]
        ptr.setdefault(p, 0)
        if r["junk"]:
            r["label"] = ""
            continue
        order = orders[p - 1] if p - 1 < len(orders) and orders[p - 1] else KANA71
        r["label"] = order[ptr[p]] if ptr[p] < len(order) else ""
        ptr[p] += 1

    # 訂正で明示されたラベルは、繰り上がりの結果と一致しているか検算する
    for idx, fix in CONFIRMED_FIXES.items():
        r = next((q for q in rows if q["index"] == idx), None)
        if r is None:
            sys.exit(f"訂正の対象 #{idx} が見つかりません")
        if r["label"] != fix["label"]:
            sys.exit(f"⚠ 検算に失敗: #{idx} は繰り上がりの結果 "
                     f"「{r['label'] or '(除外)'}」だが、確認結果は「{fix['label'] or '(除外)'}」。"
                     f"訂正の当て方かデータが食い違っている")
    return rows


def validate(rows):
    """実験で使う68字が3回ずつ揃っているかの検算"""
    groups = {}
    for r in rows:
        if not r["junk"] and r["label"]:
            groups.setdefault(r["label"], []).append(r)
    problems = []
    missing = [k for k in KANA68 if k not in groups]
    if missing:
        problems.append(f"欠けている字: {''.join(missing)}")
    for k in KANA68:
        n = len(groups.get(k, []))
        if n != 3:
            problems.append(f"「{k}」が{n}回（3回でない）")
    dup = [k for k, v in groups.items() if k not in KANA71]
    if dup:
        problems.append(f"五十音表にない字: {dup}")
    return groups, problems


# ---------------------------------------------------------------------------
# 2. テイク選択
# ---------------------------------------------------------------------------
def choose(groups):
    """音割れの回を除き、残りから発話長が中央値に最も近い回を採用"""
    out = {}
    for k, v in groups.items():
        ok = [r for r in v if not r["clipped"]] or v
        med = float(np.median([r["voiced_ms"] for r in ok]))
        best = min(ok, key=lambda r: (abs(r["voiced_ms"] - med), r["index"]))
        for r in v:
            r["selected"] = (r is best)
            r["take_median_ms"] = round(med, 1)
            r["excluded_for_clipping"] = bool(r["clipped"] and len(ok) < len(v))
        out[k] = best
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                                  "recordings_raw"))
    ap.add_argument("--hpf-hz", type=float, default=100.0,
                    help="本番の下処理で掛けるハイパス（電源ハム除去・全字共通）")
    ap.add_argument("--peak-ceiling-dbfs", type=float, default=-3.0,
                    help="音量合わせ後に超えてはいけないピーク")
    ap.add_argument("--onset-hpf-hz", type=float, default=150.0,
                    help="onset検出**だけ**に使うハイパス。配信する音(--hpf-hz)とは別。"
                         "100Hzだと50Hzハムの残りで背景雑音床が4〜7dB持ち上がり、"
                         "立ち上がりのなだらかな摩擦音の頭を30〜50ms取りこぼす")
    ap.add_argument("--onset-hpf-alt", default="120,200",
                    help="onsetのぶれ幅を測るための別のハイパス(カンマ区切り)。"
                         "この3通りの散らばりが大きい字＝onsetが不安定＝要目視")
    ap.add_argument("--onset-win-ms", type=float, default=5.0)
    ap.add_argument("--onset-hop-ms", type=float, default=1.0)
    ap.add_argument("--onset-sustain-ms", type=float, default=10.0)
    ap.add_argument("--onset-lookback-ms", type=float, default=80.0)
    ap.add_argument("--noise-win-ms", type=float, default=300.0)
    ap.add_argument("--thr-offset-db", type=float, default=10.0)
    ap.add_argument("--pad-ms", type=float, default=50.0)
    args = ap.parse_args()

    D = os.path.abspath(args.dir)
    auto_path = os.path.join(D, "segments_auto.json")
    if not os.path.exists(auto_path):
        sys.exit(f"{auto_path} がありません。先に segment_natural_recording.py を実行してください")
    auto = json.load(open(auto_path, encoding="utf-8"))
    meta = auto["meta"]
    wav_path = os.path.join(D, meta["wav"])
    raw, sr = read_wav(wav_path)

    print("[1/6] 確定ラベル（自動ラベル＋話者本人の確認）")
    rows = build_confirmed_labels(auto)
    groups, problems = validate(rows)
    for k, fix in CONFIRMED_FIXES.items():
        r = next(q for q in rows if q["index"] == k)
        print(f"      #{k}: {r['label'] or '(除外)'}  — {fix['why']}")
    if problems:
        print("      ⚠ 検算で問題あり:")
        for p in problems:
            print("        - " + p)
        sys.exit(1)
    print(f"      検算OK: 実験で使う68字がすべて3回ずつ / ラベル{len(groups)}種"
          f"（使わない3字 {''.join(sorted(set(groups) - set(KANA68)))} を含む）")

    print("[2/6] テイク選択（音割れ除外 → 発話長が中央値に最も近い回）")
    best = choose(groups)
    npass = {p: sum(1 for k in KANA68 if best[k]["pass_no"] == p) for p in (1, 2, 3)}
    print(f"      68字を採用。周ごとの内訳: 周1={npass[1]} 周2={npass[2]} 周3={npass[3]}")

    print(f"[3/6] ハイパス {args.hpf_hz:.0f}Hz（ゼロ位相）＋ 音量合わせ")
    sos = butter(4, args.hpf_hz / (sr / 2), "highpass", output="sos")
    filt_full = sosfiltfilt(sos, raw)          # onset検出も同じ波形で行う

    # 各採用テイクの、フィルタ後のRMS（onset→区間末）とピーク（クリップ全体）
    prep = []
    for k in KANA68:
        r = best[k]
        c0 = int(round(r["clip_start_s"] * sr))
        c1 = int(round(r["clip_end_s"] * sr))
        a = int(round(r["onset_s"] * sr))
        b = int(round(r["end_s"] * sr))
        seg = filt_full[c0:c1]
        speech = filt_full[a:b]
        prep.append(dict(kana=k, row=r, c0=c0, c1=c1, a=a, b=b,
                         rms=float(np.sqrt(np.mean(speech ** 2))),
                         peak=float(np.max(np.abs(seg)))))
    ceil_lin = 10 ** (args.peak_ceiling_dbfs / 20.0)
    # 倍率の上限: 1.0を超えない（増幅しない）かつピーク上限を超えない
    for q in prep:
        q["cap"] = min(1.0, ceil_lin / max(q["peak"], 1e-9))
    # 全字を同じRMSに揃える。上限に触れないいちばん低い値を選ぶ＝
    # 「全字の中でいちばん小さい字」に合わせることになる
    target_rms = min(q["rms"] * q["cap"] for q in prep)
    for q in prep:
        q["gain"] = target_rms / max(q["rms"], 1e-9)
        assert q["gain"] <= q["cap"] + 1e-9

    db = lambda v: 20 * math.log10(max(v, 1e-9))
    quietest = min(prep, key=lambda q: q["rms"] * q["cap"])
    print(f"      合わせ先のRMS {db(target_rms):.1f} dBFS"
          f"（いちばん小さい「{quietest['kana']}」に合わせた）")
    print(f"      倍率 {min(q['gain'] for q in prep):.3f}〜{max(q['gain'] for q in prep):.3f}"
          f"（すべて1.0以下＝増幅なし）")
    print(f"      処理後のピーク最大 {max(db(q['peak'] * q['gain']) for q in prep):.1f} dBFS"
          f"（上限 {args.peak_ceiling_dbfs:.0f} dBFS）")

    outdir = os.path.join(D, "adopted")
    os.makedirs(outdir, exist_ok=True)
    for q in prep:
        y = filt_full[q["c0"]:q["c1"]] * q["gain"]
        q["i16"] = np.clip(np.round(y * 32768.0), -32768, 32767).astype("<i2")
        q["fname"] = f"{KANA68.index(q['kana']):02d}_{q['kana']}.wav"
        with open(os.path.join(outdir, q["fname"]), "wb") as f:
            f.write(wav_bytes(q["i16"], sr))
    print(f"      {outdir}/ に {len(prep)} ファイル")

    print(f"[4/6] acoustic onset の再検出（検出用ハイパス {args.onset_hpf_hz:.0f}Hz）")
    class OA:                                  # detect_onset に渡す設定
        onset_win_ms = args.onset_win_ms
        onset_hop_ms = args.onset_hop_ms
        onset_sustain_ms = args.onset_sustain_ms
        onset_lookback_ms = args.onset_lookback_ms
        noise_win_ms = args.noise_win_ms
        thr_offset_db = args.thr_offset_db

    def onsets_at(hz):
        """検出用ハイパスを hz にしたときの、各字の onset（クリップ先頭からのms）"""
        det = sosfiltfilt(butter(4, hz / (sr / 2), "highpass", output="sos"), raw)
        out = []
        for q in prep:
            s0 = int(round(q["row"]["start_s"] * sr))
            on, floor_db, _thr, ok = detect_onset(det, sr, s0, q["b"], OA)
            on = max(q["c0"], min(on, q["b"]))
            out.append((on, (on - q["c0"]) / sr * 1000.0, floor_db, ok))
        return out

    main_on = onsets_at(args.onset_hpf_hz)
    alts = [float(v) for v in args.onset_hpf_alt.split(",") if v.strip()]
    alt_on = {hz: onsets_at(hz) for hz in alts}
    for i, q in enumerate(prep):
        on_abs, on_ms, floor_db, ok = main_on[i]
        q["onset_abs"] = on_abs
        q["onset_ms"] = on_ms
        q["onset_found"] = ok
        q["noise_floor_db"] = floor_db
        q["onset_alt_ms"] = {str(int(hz)): round(alt_on[hz][i][1], 1) for hz in alts}
        cand = [on_ms] + [alt_on[hz][i][1] for hz in alts]
        q["onset_spread_ms"] = max(cand) - min(cand)
        q["onset_shift_ms"] = q["onset_ms"] - q["row"]["onset_ms"]
        # 頭に発話でないもの(息継ぎ等)を巻き込んでいる量
        q["lead_ms"] = on_ms - args.pad_ms

    sp = np.array([q["onset_spread_ms"] for q in prep])
    print(f"      検出用ハイパスを {args.onset_hpf_hz:.0f} / "
          f"{' / '.join(str(int(h)) for h in alts)} Hz と変えたときの onset のぶれ幅: "
          f"中央値 {np.median(sp):.0f} ms / 最大 {sp.max():.0f} ms")
    unstable = [q for q in prep if q["onset_spread_ms"] >= 20]
    late = [q for q in prep if q["onset_ms"] > args.pad_ms + 35]
    lead = [q for q in prep if q["lead_ms"] > 100]
    nf = [q for q in prep if not q["onset_found"]]
    print(f"      要目視: ぶれが20ms以上 {len(unstable)} 字 / 遅い(頭から85ms超) {len(late)} 字 / "
          f"頭に100ms超の余分 {len(lead)} 字 / 検出できず {len(nf)} 字")
    if unstable:
        print("      ぶれの大きい字: " + " ".join(
            f"{q['kana']}({q['onset_spread_ms']:.0f}ms)"
            for q in sorted(unstable, key=lambda z: -z["onset_spread_ms"])[:12]))

    print("[5/6] adopted_onsets.json")
    adopted = []
    for q in prep:
        r = q["row"]
        st, note = SOUND_TYPE.get(q["kana"], ("?", ""))
        adopted.append(dict(
            kana=q["kana"], file=os.path.join("adopted", q["fname"]),
            source_index=r["index"], source_pass=r["pass_no"],
            clip_start_s=r["clip_start_s"], clip_end_s=r["clip_end_s"],
            clip_ms=round((q["c1"] - q["c0"]) / sr * 1000, 1),
            onset_ms=round(q["onset_ms"], 1),
            onset_found=bool(q["onset_found"]),
            onset_shift_from_cut_ms=round(q["onset_shift_ms"], 1),
            onset_alt_ms=q["onset_alt_ms"],
            onset_spread_ms=round(q["onset_spread_ms"], 1),
            lead_ms=round(q["lead_ms"], 1),
            voiced_ms=round((q["b"] - q["onset_abs"]) / sr * 1000, 1),
            take_median_ms=r["take_median_ms"],
            all_takes_voiced_ms=[t["voiced_ms"] for t in sorted(groups[q["kana"]],
                                                                key=lambda z: z["pass_no"])],
            gain=round(q["gain"], 4),
            gain_db=round(db(q["gain"]), 2),
            rms_dbfs_before=round(db(q["rms"]), 2),
            rms_dbfs_after=round(db(q["rms"] * q["gain"]), 2),
            peak_dbfs_before=round(db(q["peak"]), 2),
            peak_dbfs_after=round(db(q["peak"] * q["gain"]), 2),
            noise_floor_db=round(q["noise_floor_db"], 1),
            sound_type=st, onset_note=note,
            priority12=q["kana"] in PRIORITY12,
        ))
    onsets_meta = dict(
        source=meta["source"], sr=sr, checked_by=CHECKED_BY, checked_at=CHECKED_AT,
        n_kana=len(adopted),
        highpass_hz=args.hpf_hz, highpass_order=4, highpass_zero_phase=True,
        gain_rule="1音まるごとに一定倍率。倍率は1.0以下（増幅しない）。"
                  "全字のRMSを、いちばん小さい字の水準にそろえる",
        target_rms_dbfs=round(db(target_rms), 2),
        peak_ceiling_dbfs=args.peak_ceiling_dbfs,
        onset_detect_hpf_hz=args.onset_hpf_hz,
        onset_alt_hpf_hz=alts,
        onset_rule=f"検出用に{args.onset_hpf_hz:.0f}Hzハイパスを掛けた波形で、"
                   f"窓{args.onset_win_ms}ms・刻み{args.onset_hop_ms}ms の"
                   f"短時間エネルギーが「区間直前{args.noise_win_ms}msの背景雑音床"
                   f"+{args.thr_offset_db}dB」を{args.onset_sustain_ms}ms連続で超えた最初の時点",
        onset_ms_origin="切り出したクリップの先頭からのms（クリップの前後には50msの余白がある）",
        unused_kana=sorted(set(groups) - set(KANA68)),
    )
    with open(os.path.join(D, "adopted_onsets.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": onsets_meta, "adopted": adopted}, f, ensure_ascii=False, indent=1)

    # 確定ラベル表（確認ページの書き出しと同じ形）
    labels = dict(
        checked_at=CHECKED_AT, checked_by=CHECKED_BY,
        source=meta["source"], sr=sr, params=meta.get("params"),
        note="label＝確認後のかな。junk＝1字に対応しない区間。"
             "selected＝事前基準(音割れ除外→発話長が中央値に最も近い回)で採用したテイク。"
             "onset_ms は切り出しクリップ先頭からのms（この表は切り出し時の値。"
             "ハイパス後に測り直した値は adopted_onsets.json）。",
        confirmed_fixes={str(k): v for k, v in CONFIRMED_FIXES.items()},
        confirmed_ok=CONFIRMED_OK,
        validation="実験で使う68字がすべて3回ずつ揃っていることを検算済み",
        segments=[{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
    )
    with open(os.path.join(D, "labels_checked.json"), "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, indent=1)
    print(f"      {os.path.join(D, 'labels_checked.json')}")
    print(f"      {os.path.join(D, 'adopted_onsets.json')}")

    print("[6/6] onset_review.html")
    write_onset_review(os.path.join(D, "onset_review.html"), onsets_meta, adopted, prep, sr)
    p = os.path.join(D, "onset_review.html")
    print(f"      {p}  ({os.path.getsize(p)/1e6:.1f} MB)")
    print("\n開き方:  open " + p)


# ---------------------------------------------------------------------------
# onset確認ページ
# ---------------------------------------------------------------------------
def write_onset_review(path, meta, adopted, prep, sr):
    audio, waves, zooms = [], [], []
    for q, a in zip(prep, adopted):
        audio.append(base64.b64encode(wav_bytes(q["i16"], sr)).decode("ascii"))
        x = q["i16"].astype(np.float64) / 32768.0
        # 全体の包絡（min/max 160本）
        nb = 160
        step = max(1, len(x) // nb)
        waves.append([[int(round(x[i*step:(i+1)*step].min() * 1000)),
                       int(round(x[i*step:(i+1)*step].max() * 1000))]
                      if len(x[i*step:(i+1)*step]) else [0, 0] for i in range(nb)])
        # onset前後 ±60ms を拡大（頭の子音を捉えているかはここで見る）
        on = int(a["onset_ms"] / 1000 * sr)
        z0, z1 = max(0, on - int(0.06 * sr)), min(len(x), on + int(0.06 * sr))
        z = x[z0:z1]
        nz = 240
        st = max(1, len(z) // nz)
        zooms.append(dict(
            env=[[int(round(z[i*st:(i+1)*st].min() * 1000)),
                  int(round(z[i*st:(i+1)*st].max() * 1000))]
                 if len(z[i*st:(i+1)*st]) else [0, 0] for i in range(nz)],
            onset_frac=(on - z0) / max(1, (z1 - z0)),
            span_ms=round((z1 - z0) / sr * 1000, 1),
            gain=round(float(1.0 / max(np.max(np.abs(z)), 1e-3)), 2),
        ))
    html = ONSET_HTML.replace("/*__DATA__*/", "window.D=" + json.dumps(
        {"meta": meta, "rows": adopted, "waves": waves, "zooms": zooms},
        ensure_ascii=False, separators=(",", ":")) + ";") \
        .replace("/*__AUDIO__*/", "window.AUDIO=" + json.dumps(audio, separators=(",", ":")) + ";")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


ONSET_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>採用テイクの onset 確認 — 68字</title>
<style>
:root{--ink:#211d18;--ink-2:#6b6155;--line:#ddd4c6;--line-2:#efe8dc;--bg:#f7f3ec;
 --card:#fffdf8;--accent:#8a4b2a;--accent-soft:#f0e2d6;--ok:#3d6b45;--warn:#a8621b;--bad:#a32f2f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.5;
 font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,sans-serif}
header{position:sticky;top:0;z-index:20;background:var(--card);border-bottom:1px solid var(--line);padding:12px 20px}
h1{margin:0 0 4px;font-size:17px;font-weight:600}
.sub{color:var(--ink-2);font-size:12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
button{font:inherit;padding:5px 11px;border:1px solid var(--line);background:var(--card);
 color:var(--ink);border-radius:4px;cursor:pointer}
button:hover{background:var(--accent-soft);border-color:var(--accent)}
button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
select{font:inherit;padding:4px 7px;border:1px solid var(--line);border-radius:4px;background:var(--card)}
.stat{font-size:12px;color:var(--ink-2);padding:3px 9px;background:var(--bg);
 border:1px solid var(--line-2);border-radius:3px}
main{padding:16px 20px 120px}
.hint{color:var(--ink-2);font-size:12px;max-width:78ch;margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(390px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.card.flag{border-color:var(--warn);box-shadow:inset 3px 0 0 var(--warn)}
.card.bad{border-color:var(--bad);box-shadow:inset 3px 0 0 var(--bad)}
.hd{display:flex;align-items:baseline;gap:10px;margin-bottom:6px}
.k{font-size:26px;font-family:"Hiragino Mincho ProN",serif}
.k.prio{color:var(--accent);font-weight:600}
.ty{font-size:11px;color:var(--ink-2)}
.num{font-variant-numeric:tabular-nums;font-size:11px;color:var(--ink-2)}
svg{display:block;background:#fbf8f2;border:1px solid var(--line-2);border-radius:3px;width:100%}
.lab{font-size:10px;color:var(--ink-2);margin:5px 0 2px}
.btns{display:flex;gap:5px;margin-top:7px;flex-wrap:wrap}
.btns button{padding:3px 8px;font-size:12px}
.tbl{width:100%;font-size:11px;margin-top:7px;border-collapse:collapse}
.tbl td{padding:1px 4px;border-top:1px solid var(--line-2);color:var(--ink-2)}
.tbl td:first-child{width:7em}
.tbl td:last-child{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink)}
.fl{display:inline-block;font-size:10px;padding:1px 5px;border-radius:3px;margin-left:6px;
 border:1px solid var(--line);background:var(--bg);color:var(--ink-2)}
.fl.w{background:#fdf1e0;color:var(--warn);border-color:#e8cfa8}
.fl.b{background:#fbe6e6;color:var(--bad);border-color:#e5b8b8}
.note{font-size:11px;color:var(--ink-2);margin-top:5px;font-style:italic}
</style>
</head>
<body>
<header>
  <h1>採用テイクの onset 確認 — 68字</h1>
  <div class="sub" id="meta"></div>
  <div class="bar">
    <select id="sort">
      <option value="type">音の種類ごとに並べる（推奨）</option>
      <option value="gojuon">五十音順</option>
      <option value="onset">onsetが怪しい順（ぶれの大きい順）</option>
    </select>
    <select id="filt">
      <option value="all">68字すべて</option>
      <option value="flag">要確認だけ</option>
      <option value="unstable">onsetがぶれる字だけ</option>
      <option value="prio">候補12字だけ</option>
      <option value="voiced">清濁のペアだけ（か/が・た/だ・ぱ/ば）</option>
    </select>
    <button id="playall">全長を順に試聴（0.9秒間隔）</button>
    <button id="stop">停止</button>
    <span class="stat" id="cnt"></span>
  </div>
</header>
<main>
  <p class="hint" id="hint"></p>
  <div class="grid" id="grid"></div>
</main>
<script>
/*__DATA__*/
/*__AUDIO__*/
</script>
<script>
const M=D.meta, R=D.rows, W=D.waves, Z=D.zooms;
const PAIRS=[["か","が"],["た","だ"],["ぱ","ば"]];
const PAIRSET=new Set(PAIRS.flat());
let actx=null,curSrc=null,timer=null;
function ctx(){ if(!actx) actx=new (window.AudioContext||window.webkitAudioContext)();
  if(actx.state==='suspended') actx.resume(); return actx; }
const cache={};
async function buf(i){ if(cache[i])return cache[i];
  const b=atob(AUDIO[i]),u=new Uint8Array(b.length);
  for(let k=0;k<b.length;k++)u[k]=b.charCodeAt(k);
  cache[i]=await ctx().decodeAudioData(u.buffer); return cache[i]; }
async function play(i,from){ const c=ctx();
  if(curSrc){try{curSrc.stop()}catch(e){}}
  const b=await buf(i); const s=c.createBufferSource(); s.buffer=b; s.connect(c.destination);
  s.start(0, Math.max(0,(from||0)/1000)); curSrc=s;
  document.querySelectorAll('.card').forEach(e=>e.style.outline='');
  const el=document.getElementById('c'+i); if(el){el.style.outline='2px solid #8a4b2a';
    el.scrollIntoView({block:'nearest'});} }
function flagsOf(r){
  const f=[];
  if(!r.onset_found) f.push(['onset検出できず','b']);
  if(r.onset_spread_ms>=20) f.push(['onsetが1点に決まらない（ぶれ'+Math.round(r.onset_spread_ms)+'ms）','b']);
  else if(r.onset_spread_ms>=8) f.push(['onsetが少しぶれる（'+Math.round(r.onset_spread_ms)+'ms）','w']);
  if(r.onset_ms>85) f.push(['onsetが遅い（頭を飛ばした可能性）','w']);
  if(r.lead_ms>100) f.push(['頭に'+Math.round(r.lead_ms)+'msの余分（息継ぎ等）','w']);
  if(r.peak_dbfs_after>-3) f.push(['ピーク超過','b']);
  return f;
}
document.getElementById('meta').textContent=
 `${M.n_kana}字 / ${M.sr} Hz / ハイパス ${M.highpass_hz}Hz 4次ゼロ位相 / `
 +`RMSを ${M.target_rms_dbfs} dBFS にそろえた（倍率は1.0以下＝増幅なし） / 確認: ${M.checked_by}・${M.checked_at}`;
document.getElementById('hint').textContent=
 '上段が刺激の全体、下段が onset の前後±60msを拡大したもの。赤い縦線が acoustic onset。'
 +'見るところは「赤線が子音の始まりに立っているか」。子音より後ろ（母音の頭）に立っていたら遅すぎる。'
 +'「onsetから再生」で頭が切れて聞こえたら、その字は遅い。'
 +'onset は '+M.onset_rule+'。';
function card(i){
  const r=R[i], z=Z[i], fl=flagsOf(r);
  const cls=fl.some(f=>f[1]==='b')?'bad':(fl.length?'flag':'');
  const W1=360,H1=54,W2=360,H2=64;
  const up=[],dn=[];
  W[i].forEach((v,k)=>{const x=k/(W[i].length-1)*W1;
    up.push(x.toFixed(1)+','+(H1/2-v[1]/1000*(H1/2-1)).toFixed(1));
    dn.push(x.toFixed(1)+','+(H1/2-v[0]/1000*(H1/2-1)).toFixed(1));});
  const ox=r.onset_ms/r.clip_ms*W1;
  const zu=[],zd=[],zg=Math.min(z.gain,6);
  z.env.forEach((v,k)=>{const x=k/(z.env.length-1)*W2;
    zu.push(x.toFixed(1)+','+(H2/2-v[1]/1000*zg*(H2/2-1)).toFixed(1));
    zd.push(x.toFixed(1)+','+(H2/2-v[0]/1000*zg*(H2/2-1)).toFixed(1));});
  const zx=z.onset_frac*W2;
  return `<div class="card ${cls}" id="c${i}">
   <div class="hd"><span class="k${r.priority12?' prio':''}">${r.kana}</span>
     <span class="ty">${r.sound_type}</span>
     <span class="num">周${r.source_pass}・#${r.source_index}</span>
     ${fl.map(f=>`<span class="fl ${f[1]}">${f[0]}</span>`).join('')}</div>
   <div class="lab">全体（${r.clip_ms} ms・前後に50msの余白）</div>
   <svg viewBox="0 0 ${W1} ${H1}" height="${H1}">
     <line x1="0" y1="${H1/2}" x2="${W1}" y2="${H1/2}" stroke="#ddd4c6"/>
     <polyline points="${up.join(' ')}" fill="none" stroke="#5b544a" stroke-width=".8"/>
     <polyline points="${dn.join(' ')}" fill="none" stroke="#5b544a" stroke-width=".8"/>
     <line x1="${ox.toFixed(1)}" y1="0" x2="${ox.toFixed(1)}" y2="${H1}" stroke="#c0392b" stroke-width="1.4"/>
   </svg>
   <div class="lab">onset前後 ±60ms を拡大（縦を${zg.toFixed(1)}倍に伸ばしてある）。
     赤＝採用したonset、灰＝検出用フィルタを変えたときの位置</div>
   <svg viewBox="0 0 ${W2} ${H2}" height="${H2}">
     <rect x="0" y="0" width="${zx.toFixed(1)}" height="${H2}" fill="#8a4b2a" opacity=".05"/>
     <line x1="0" y1="${H2/2}" x2="${W2}" y2="${H2/2}" stroke="#ddd4c6"/>
     <polyline points="${zu.join(' ')}" fill="none" stroke="#5b544a" stroke-width=".7"/>
     <polyline points="${zd.join(' ')}" fill="none" stroke="#5b544a" stroke-width=".7"/>
     ${Object.entries(r.onset_alt_ms||{}).map(([hz,ms])=>{
        const ax=zx+(ms-r.onset_ms)/z.span_ms*W2;
        return (ax>-2&&ax<W2+2)?`<line x1="${ax.toFixed(1)}" y1="4" x2="${ax.toFixed(1)}" y2="${H2-4}"
          stroke="#9a9088" stroke-width="1" stroke-dasharray="3 2"/>
          <text x="${(ax+2).toFixed(1)}" y="11" font-size="8" fill="#9a9088">${hz}</text>`:'';
      }).join('')}
     <line x1="${zx.toFixed(1)}" y1="0" x2="${zx.toFixed(1)}" y2="${H2}" stroke="#c0392b" stroke-width="1.4"/>
   </svg>
   <div class="btns">
     <button data-p="${i}" data-f="0">▶ 全長</button>
     <button data-p="${i}" data-f="${r.onset_ms}">▶ onsetから</button>
     <button data-p="${i}" data-f="${Math.max(0,r.onset_ms-30)}">▶ onset30ms前から</button>
   </div>
   <div class="note">${r.onset_note}</div>
   <table class="tbl">
    <tr><td>onset</td><td>${r.onset_ms} ms（検出${M.onset_detect_hpf_hz}Hz）</td></tr>
    <tr><td>onsetのぶれ</td><td>${r.onset_spread_ms} ms（${Object.entries(r.onset_alt_ms||{}).map(([h,v])=>h+'Hz:'+v).join(' / ')}）</td></tr>
    <tr><td>発話長</td><td>${r.voiced_ms} ms（3回=${r.all_takes_voiced_ms.map(v=>Math.round(v)).join(' / ')}・中央値${r.take_median_ms}）</td></tr>
    <tr><td>倍率</td><td>${r.gain} 倍（${r.gain_db} dB）</td></tr>
    <tr><td>RMS</td><td>${r.rms_dbfs_before} → ${r.rms_dbfs_after} dBFS</td></tr>
    <tr><td>ピーク</td><td>${r.peak_dbfs_before} → ${r.peak_dbfs_after} dBFS</td></tr>
    <tr><td>背景雑音床</td><td>${r.noise_floor_db} dBFS</td></tr>
   </table></div>`;
}
function order(){
  const s=document.getElementById('sort').value;
  let idx=R.map((_,i)=>i);
  if(s==='onset') idx.sort((a,b)=>(R[b].onset_spread_ms-R[a].onset_spread_ms)||(R[b].onset_ms-R[a].onset_ms));
  else if(s==='type') idx.sort((a,b)=> R[a].sound_type.localeCompare(R[b].sound_type,'ja')||a-b);
  return idx;
}
function visible(i){
  const f=document.getElementById('filt').value, r=R[i];
  if(f==='flag') return flagsOf(r).length>0;
  if(f==='unstable') return r.onset_spread_ms>=8;
  if(f==='prio') return r.priority12;
  if(f==='voiced') return PAIRSET.has(r.kana);
  return true;
}
function render(){
  const idx=order().filter(visible);
  document.getElementById('grid').innerHTML=idx.map(card).join('');
  document.getElementById('cnt').textContent=
    `表示 ${idx.length} 字 / 要確認 ${R.filter((_,i)=>flagsOf(R[i]).length).length} 字`;
  window.SHOWN=idx;
}
document.addEventListener('click',e=>{
  const b=e.target.closest('button[data-p]');
  if(b) play(+b.dataset.p, +b.dataset.f);
});
document.getElementById('sort').onchange=render;
document.getElementById('filt').onchange=render;
document.getElementById('playall').onclick=()=>{
  clearInterval(timer); let n=0; const list=window.SHOWN;
  play(list[0],0);
  timer=setInterval(()=>{ n++; if(n>=list.length){clearInterval(timer);return;} play(list[n],0); },900);
};
document.getElementById('stop').onclick=()=>{clearInterval(timer);
  if(curSrc){try{curSrc.stop()}catch(e){}}};
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
