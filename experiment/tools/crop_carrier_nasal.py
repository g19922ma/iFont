#!/usr/bin/env python3
"""
「字＋ん」で合成した音声から、末尾の「ん」を落とす
==================================================
2026-08-24 作成。**2026-08-23 に作った切り出しが壊れていたので作り直した**もの。
以前は対話実行のまま .py として残っていなかった（WORKLOG 2026-08-23 追記2）ので、
同じ事故を繰り返さないようスクリプトとして保存してある。

何を直したか（この工程が壊れていた経緯）
----------------------------------------
聴覚刺激は、あみたろ（COEIROINK）に「あん」「かん」のように**字＋ん**を読ませ、
そこから対象の字（＝最初の1モーラ）だけを切り出して作っている。この
「どこまでが字で、どこからが《ん》か」を見つける処理が壊れていた。

  2026-08-23 の版は、境界の探索を「onset＋260ミリ秒**以降**」に限っていた。
  ところが1モーラの実際の長さは onset から **116〜208ミリ秒**しかない。
  つまり探索を始める時点で《ん》はとっくに始まっており、探索窓の中に境界が
  存在しない。その結果 **68字中62字で「境界が見つからない」** と判定され、
  「見つからなければ長めに残す」という保険の分岐に落ちて、
  **onset＋260ミリ秒までを丸ごと残していた**（＝《ん》が入ったまま）。

  症状: 長い打ち切り条件と全長条件で「か」が「かん」に聞こえる。
        短い条件（60ミリ秒以下）は母音の途中なので無傷。

この版の直し方
--------------
1. **探索の開始を「音量のピークの直後」にする**（固定値の260ミリ秒をやめた）。
   《ん》は必ず母音の山のあとに来るので、山より前を見る必要がない。
   これが前の版の誤りの本体である。
2. **判定に《ん》そのものの音の性質を使う**。鼻音の murmur は
   　・0〜500Hz が優勢（lo > 0.45）
   　・1.5〜5kHz がほぼ消える（hi < しきい値）
   　・母音の山より小さい
   の3つが同時に立つ。これが 30ミリ秒つづいた最初の点を境界とする。
   「音量の谷」で切る方式（2026-08-23 より前の版）は、ば行などで母音の途中の
   へこみ（フォルマント遷移）を境界と誤検出して切り詰めすぎたので採らない。
3. **1.5〜5kHz のしきい値は字ごとに決める**。「い」段の母音はもともと
   この帯域が薄いので、全字共通の固定値だと母音と《ん》を見分けられない。
   その字の母音区間での中央値の 1/4（下限 0.008）を使う。

入力と出力
----------
  入力  experiment/tts_candidates_carrier/あみたろ_norm/<かな>.wav
        （音量そろえ済み。波形そのものは正しいので、末尾を切るだけにする。
          ここから作り直すと 2026-08-23 の音量そろえの成果を捨てることになる）
  出力  experiment/tts_candidates_carrier/あみたろ_cut/<かな>.wav
        （境界の手前まで。末尾に5ミリ秒の余弦フェードアウトをかける）
        <out>/crop_report.json … 字ごとの境界・落とした長さ・検出できたか

使い方
------
  python3 experiment/tools/crop_carrier_nasal.py \
      --src experiment/tts_candidates_carrier/あみたろ_norm \
      --out experiment/tts_candidates_carrier/あみたろ_cut \
      --onsets experiment/transfer_onsets_amitaro.json

  # そのあと打ち切りWAVを作り直す
  python3 experiment/tools/build_transfer_gates.py \
      --src experiment/tts_candidates_carrier/あみたろ_cut --onsets auto \
      --onsets-out experiment/transfer_onsets_amitaro.json \
      --out-dir experiment/transfer_stimuli_amitaro \
      --manifest experiment/transfer_audio_manifest_amitaro.json

検出できなかった字について
--------------------------
さ・し・す・せ・そ は《ん》が見つからない。これは失敗ではなく、
**もともとファイルの末尾までに《ん》が始まっていない**（サ行はモーラが長く、
onset＋260ミリ秒の時点でまだ母音の途中）ためである。この5字は切らずにそのまま出す。
"""
import argparse
import json
import os
import sys
import wave

import numpy as np

# ---- 検出のつまみ（変えたら crop_report.json の params にも残る） -----------
FRAME_MS = 25.0        # 分析窓
HOP_MS = 2.5           # 窓をずらす幅
HOLD_MS = 30.0         # 鼻音らしさが何ミリ秒つづいたら境界と認めるか
LO_MIN = 0.45          # 0〜500Hz が占める割合の下限
HI_FLOOR = 0.008       # 1.5〜5kHz のしきい値の下限（字ごとの値がこれを下回らない）
HI_REL = 0.25          # 字ごとのしきい値 = 母音区間の中央値 × これ
DROP_DB = 1.0          # 母音の山より何dB以上小さいか
MIN_MORA_MS = 90.0     # これより手前は境界としない（1モーラがこれより短いことはない）
FADE_OUT_MS = 5.0      # 切り口にかける余弦フェードアウト


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sampwidth = w.getsampwidth()
        if sampwidth != 2:
            raise SystemExit(f"16bit PCM 以外は扱えません: {path}")
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    x = x.astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    y = np.clip(x, -1.0, 1.0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767.0).astype(np.int16).tobytes())


def frame_features(x, sr):
    """(時刻ms, 音量dB(ピーク基準), 0-500Hz比, 1.5-5kHz比) の並びを返す。"""
    win = int(sr * FRAME_MS / 1000)
    hop = int(sr * HOP_MS / 1000)
    ref = np.abs(x).max() + 1e-12
    window = np.hanning(win)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    b_lo = freqs < 500
    b_hi = (freqs >= 1500) & (freqs < 5000)
    out = []
    for i in range(0, len(x) - win, hop):
        seg = x[i:i + win]
        db = 20 * np.log10(np.sqrt((seg ** 2).mean()) / ref + 1e-12)
        spec = np.abs(np.fft.rfft(seg * window)) ** 2
        tot = spec.sum() + 1e-12
        out.append((i / sr * 1000.0, db, spec[b_lo].sum() / tot, spec[b_hi].sum() / tot))
    return out


def detect_onset(x, sr, dbfs=-58.0, frame_ms=5.0):
    """build_onsets.py と同じ考え方: ピーク基準 -58dBFS を最初に超えた点。"""
    win = int(sr * frame_ms / 1000)
    ref = np.abs(x).max() + 1e-12
    for i in range(0, len(x) - win, win):
        rms = np.sqrt((x[i:i + win] ** 2).mean())
        if 20 * np.log10(rms / ref + 1e-12) > dbfs:
            return i / sr * 1000.0
    return 0.0


def nasal_boundary(x, sr, onset_ms):
    """末尾の《ん》が始まる時刻(ms)。見つからなければ None。"""
    F = frame_features(x, sr)
    if not F:
        return None, {}
    peak_db = max(f[1] for f in F)
    t_peak = max(F, key=lambda f: f[1])[0]
    # その字の母音区間での 1.5-5kHz 比の中央値から、字ごとのしきい値を決める。
    voiced = [f[3] for f in F if onset_ms + 40 <= f[0] <= t_peak + 40]
    hi_ref = float(np.median(voiced)) if voiced else 0.05
    hi_thr = max(HI_FLOOR, hi_ref * HI_REL)
    start = max(t_peak + 20.0, onset_ms + MIN_MORA_MS)
    need = int(HOLD_MS / HOP_MS) - 1
    info = {"peak_db": round(peak_db, 1), "t_peak_ms": round(t_peak, 1),
            "hi_ref": round(hi_ref, 4), "hi_thr": round(hi_thr, 4)}

    def nasal_like(f):
        return f[3] < hi_thr and f[2] > LO_MIN and f[1] < peak_db - DROP_DB

    for k, f in enumerate(F):
        if f[0] < start:
            continue
        run = [g for g in F[k:] if g[0] < f[0] + HOLD_MS]
        if len(run) >= need and all(nasal_like(g) for g in run):
            return f[0], info
    return None, info


def apply_fade_out(x, sr, ms=FADE_OUT_MS):
    n = min(len(x), int(sr * ms / 1000))
    if n <= 1:
        return x
    ramp = 0.5 * (1 + np.cos(np.linspace(0, np.pi, n)))
    y = x.copy()
    y[-n:] *= ramp
    return y


def load_onsets(path):
    if not path or path == "auto":
        return None
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[k] = v.get("acoustic_onset_ms", v.get("onset_ms"))
        else:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="切り出し前(字＋ん)の WAV があるフォルダ")
    ap.add_argument("--out", required=True, help="切り出した WAV を書くフォルダ")
    ap.add_argument("--onsets", default="auto",
                    help="かな→onset(ms) の表。auto ならこのスクリプトが検出する")
    ap.add_argument("--dry-run", action="store_true", help="書き出さずに結果だけ表示")
    args = ap.parse_args()

    onsets = load_onsets(args.onsets)
    names = sorted(n for n in os.listdir(args.src) if n.endswith(".wav"))
    if not names:
        sys.exit(f"WAV が1つもありません: {args.src}")
    if not args.dry_run:
        os.makedirs(args.out, exist_ok=True)

    report = {"src": args.src, "out": args.out,
              "params": {"frame_ms": FRAME_MS, "hop_ms": HOP_MS, "hold_ms": HOLD_MS,
                         "lo_min": LO_MIN, "hi_floor": HI_FLOOR, "hi_rel": HI_REL,
                         "drop_db": DROP_DB, "min_mora_ms": MIN_MORA_MS,
                         "fade_out_ms": FADE_OUT_MS},
              "items": {}}
    n_cut = 0
    removed = []
    for name in names:
        kana = os.path.splitext(name)[0]
        x, sr = read_wav(os.path.join(args.src, name))
        onset = onsets.get(kana) if onsets else None
        if onset is None:
            onset = detect_onset(x, sr)
        b, info = nasal_boundary(x, sr, onset)
        total_ms = len(x) / sr * 1000.0
        if b is None:
            y = x
            cut_ms = total_ms
        else:
            y = apply_fade_out(x[:int(sr * b / 1000)], sr)
            cut_ms = len(y) / sr * 1000.0
            n_cut += 1
            removed.append(total_ms - cut_ms)
        if not args.dry_run:
            write_wav(os.path.join(args.out, name), y, sr)
        report["items"][kana] = {
            "onset_ms": round(onset, 1),
            "orig_dur_ms": round(total_ms, 1),
            "cut_dur_ms": round(cut_ms, 1),
            "mora_ms": round(cut_ms - onset, 1),
            "removed_ms": round(total_ms - cut_ms, 1),
            "nasal_found": b is not None,
            **info,
        }

    report["summary"] = {
        "n_files": len(names),
        "n_nasal_removed": n_cut,
        "n_no_nasal_found": len(names) - n_cut,
        "removed_ms_median": round(float(np.median(removed)), 1) if removed else 0.0,
        "mora_ms_median": round(float(np.median([v["mora_ms"] for v in report["items"].values()])), 1),
    }
    if not args.dry_run:
        with open(os.path.join(args.out, "crop_report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    s = report["summary"]
    print(f"  {s['n_files']} 字を処理しました")
    print(f"  《ん》を落とした字: {s['n_nasal_removed']}（落とした長さの中央値 {s['removed_ms_median']:.0f} ms）")
    print(f"  《ん》が見つからなかった字: {s['n_no_nasal_found']}"
          f"（{' '.join(k for k, v in report['items'].items() if not v['nasal_found'])}）")
    print(f"  モーラ長の中央値: {s['mora_ms_median']:.0f} ms")
    if not args.dry_run:
        print(f"  → {args.out}")


if __name__ == "__main__":
    main()
