#!/usr/bin/env python3
"""
「字＋無声破裂音」から、対象の字（1モーラ）だけを切り出す
==========================================================
2026-08-24 作成。**後続音を「ん」から無声破裂音に変えたことに伴う作り直し。**

なぜ切る位置が一意に決まるのか
------------------------------
後続が「ん」（鼻音）だと、母音から鼻音へ**地続きに**移るので境目が無い。
実際 2026-08-23／08-24 の2版とも境目の自動検出に失敗し、68字中34字で《ん》が
残った（経緯は project/刺激作成_キャリアフレーズ.md）。

後続が無声破裂音（か・た・ぱ）だと、母音のあとに**閉鎖区間**が来る。
唇や舌で息の通り道を完全に塞ぐ区間なので、**音がほぼ消える**。
つまり「音量が大きく落ちて、その状態が続く点」を探すだけで境目が決まる。
母音の種類にも子音の種類にも依存しない——これが「ん」方式との決定的な違いである。

判定のしかた
------------
  1. onset（音の実体が始まる点）を絶対 -58dBFS で検出する
     （build_transfer_gates.py・build_onsets.py と同じ考え方）
  2. 発話の最大音量 peak を求める
  3. onset + MIN_MORA_MS 以降で、音量が **peak より CLOSE_DROP_DB 以上小さい**状態が
     CLOSE_HOLD_MS 続く最初の点を「閉鎖の始まり」＝切り口とする
  4. 切り口の手前に FADE_OUT_MS の余弦フェードアウトをかける

**しきい値は母音ごとに変えない。** 前の版は「1.5〜5kHz の割合」で鼻音を見分けようと
して、母音の種類ごとにしきい値を変える必要があり、そこが破綻の元だった。
閉鎖区間は「音が無い」だけなので、全字共通の落差で判定できる。

入力と出力
----------
  入力  <src>/<かな>.wav        … build_carrier_takes.py が合成した「字＋後続音」
  出力  <out>/<かな>.wav        … 切り口まで（末尾に5msのフェードアウト）
        <out>/crop_report.json  … 字ごとの onset・モーラ長・閉鎖の深さと長さ

使い方
------
  # 後続音を選ぶための下見（書き出さずに数値だけ）
  python3 experiment/tools/crop_carrier_stop.py \\
      --src experiment/tts_candidates_carrier2/raw_ぱ --dry-run

  # 切り出し
  python3 experiment/tools/crop_carrier_stop.py \\
      --src experiment/tts_candidates_carrier2/raw_ぱ \\
      --out experiment/tts_candidates_carrier2/cut
"""
import argparse
import json
import os
import sys
import wave

import numpy as np

# ---- 検出のつまみ（変えたら crop_report.json の params にも残る） -----------
FRAME_MS = 20.0        # 音量をはかる窓（閉鎖の検出には短めの窓が要る）
HOP_MS = 2.5           # 窓をずらす幅
CLOSE_DROP_DB = 22.0   # 発話の最大音量より何dB以上小さければ「閉鎖」とみなすか
CLOSE_HOLD_MS = 25.0   # その状態が何ミリ秒続いたら閉鎖と認めるか
MIN_MORA_MS = 80.0     # これより手前は閉鎖としない（1モーラがこれより短いことはない）
FADE_OUT_MS = 5.0      # 切り口にかける余弦フェードアウト
ONSET_DBFS = -58.0     # onset の絶対しきい値（build_transfer_gates.py と同じ）
ONSET_FRAME_MS = 5.0
ONSET_HOLD_MS = 15.0


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if width != 2:
            raise SystemExit(f"16bit PCM 以外は扱えません: {path}")
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
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
        w.writeframes((y * 32767.0).astype("<i2").tobytes())


def detect_onset_ms(x, sr):
    """5ms フレームの実効値が -58dBFS を 15ms 以上続けて超えた最初の点。"""
    fr = max(1, int(round(sr * ONSET_FRAME_MS / 1000.0)))
    hold = max(1, int(round(ONSET_HOLD_MS / ONSET_FRAME_MS)))
    n = len(x) // fr
    if n == 0:
        return 0.0
    rms = np.sqrt((x[:n * fr].reshape(n, fr) ** 2).mean(axis=1) + 1e-20)
    over = 20 * np.log10(rms) > ONSET_DBFS
    run = 0
    for i, ok in enumerate(over):
        run = run + 1 if ok else 0
        if run >= hold:
            return (i - hold + 1) * ONSET_FRAME_MS
    return 0.0


def level_series(x, sr):
    """(時刻ms, 音量dBFS) の並び。dBFS は絶対（フルスケール基準）。"""
    win = int(sr * FRAME_MS / 1000)
    hop = int(sr * HOP_MS / 1000)
    out = []
    for i in range(0, max(1, len(x) - win), hop):
        seg = x[i:i + win]
        out.append((i / sr * 1000.0,
                    20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-12)))
    return out


def closure_start(x, sr, onset_ms):
    """閉鎖区間の始まり(ms)。見つからなければ None。あわせて測定値を返す。

    ⚠ **基準にする音量は「発話全体の最大」ではなく「onset からその時点までの最大」**
      （走っている最大値）にすること。全体の最大にすると、後続の「ぱ」の母音 /a/ が
      いちばん大きい字（狭母音の「い」「く」など、対象モーラのほうが小さい字）で、
      **対象モーラの最初から「閉鎖」の条件を満たしてしまう**。
      2026-08-24 の下見では、これで68字中30字以上がモーラ長 82.1ms
      （＝ MIN_MORA_MS の直後）に張り付き、誤検出だと分かった。
      走っている最大値なら、基準は必ず対象モーラ自身の山になる。
    """
    L = level_series(x, sr)
    if not L:
        return None, {}
    need = max(1, int(round(CLOSE_HOLD_MS / HOP_MS)))
    start_after = onset_ms + MIN_MORA_MS
    run_max = -999.0
    info = {}
    for i, (t, d) in enumerate(L):
        if t < onset_ms:
            continue
        run_max = max(run_max, d)
        if t < start_after:
            continue
        peak_db = run_max
        thr = peak_db - CLOSE_DROP_DB
        info = {"peak_dbfs": round(peak_db, 1), "closure_thr_dbfs": round(thr, 1)}
        run = L[i:i + need]
        if len(run) == need and all(dd < thr for _, dd in run):
            # 閉鎖の深さ（閉鎖に入って 10〜35ms の平均）と長さも測る
            deep = [lv for tt, lv in L if t + 10 <= tt <= t + 35]
            info["closure_dbfs"] = round(float(np.mean(deep)), 1) if deep else None
            info["closure_depth_db"] = (round(peak_db - float(np.mean(deep)), 1)
                                        if deep else None)
            # 閉鎖が終わる（破裂で音が戻る）点
            end = None
            for tt, lv in L:
                if tt > t + 10 and lv > thr:
                    end = tt
                    break
            info["closure_len_ms"] = round(end - t, 1) if end else None
            return t, info
    return None, info


def apply_fade_out(x, sr, ms=FADE_OUT_MS):
    n = min(len(x), int(sr * ms / 1000))
    if n <= 1:
        return x
    ramp = 0.5 * (1 + np.cos(np.linspace(0, np.pi, n)))
    y = x.copy()
    y[-n:] *= ramp
    return y


def voiced_ratio(x, sr, lo_hz=120, hi_hz=500):
    """周期性のあるフレームの割合。母音が無声化していれば低くなる。"""
    win = int(sr * 0.03)
    hop = int(sr * 0.005)
    tot = v = 0
    for i in range(0, max(1, len(x) - win), hop):
        s = x[i:i + win]
        if np.sqrt((s ** 2).mean()) < 0.01:
            continue
        tot += 1
        w = s * np.hanning(win)
        ac = np.correlate(w, w, "full")[win - 1:]
        a, b = int(sr / hi_hz), int(sr / lo_hz)
        if b < len(ac) and ac[a:b].max() > 0.35 * ac[0]:
            v += 1
    return (v / tot) if tot else 0.0


def analyze(src, kana_files):
    items = {}
    for kana, path in kana_files:
        x, sr = read_wav(path)
        onset = detect_onset_ms(x, sr)
        b, info = closure_start(x, sr, onset)
        total = len(x) / sr * 1000.0
        items[kana] = {
            "onset_ms": round(onset, 1),
            "orig_dur_ms": round(total, 1),
            "closure_start_ms": None if b is None else round(b, 1),
            "mora_ms": None if b is None else round(b - onset, 1),
            "closure_found": b is not None,
            "voiced_ratio": round(voiced_ratio(x[:int(sr * (b or total) / 1000)], sr), 3),
            **info,
        }
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="「字＋後続音」の WAV があるフォルダ")
    ap.add_argument("--out", default=None, help="切り出した WAV を書くフォルダ")
    ap.add_argument("--dry-run", action="store_true", help="書き出さずに数値だけ出す")
    args = ap.parse_args()

    if not args.dry_run and not args.out:
        sys.exit("--out か --dry-run のどちらかが要ります")

    names = sorted(n for n in os.listdir(args.src) if n.endswith(".wav"))
    if not names:
        sys.exit(f"WAV が1つもありません: {args.src}")
    kana_files = [(os.path.splitext(n)[0], os.path.join(args.src, n)) for n in names]
    items = analyze(args.src, kana_files)

    ok = [v for v in items.values() if v["closure_found"]]
    ng = [k for k, v in items.items() if not v["closure_found"]]
    mora = [v["mora_ms"] for v in ok]
    depth = [v["closure_depth_db"] for v in ok if v.get("closure_depth_db")]
    print(f"  {len(names)} 字を処理しました（{args.src}）")
    print(f"  閉鎖が見つかった字: {len(ok)}／{len(names)}"
          + (f"  見つからない字: {' '.join(ng)}" if ng else ""))
    if mora:
        print(f"  モーラ長: 最小{min(mora):.0f} 中央{np.median(mora):.0f} 最大{max(mora):.0f} ms")
    if depth:
        print(f"  閉鎖の深さ: 最小{min(depth):.0f} 中央{np.median(depth):.0f} 最大{max(depth):.0f} dB")

    if args.dry_run:
        return

    os.makedirs(args.out, exist_ok=True)
    for kana, path in kana_files:
        x, sr = read_wav(path)
        v = items[kana]
        if v["closure_found"]:
            y = apply_fade_out(x[:int(sr * v["closure_start_ms"] / 1000)], sr)
        else:
            y = apply_fade_out(x, sr)
        write_wav(os.path.join(args.out, kana + ".wav"), y, sr)
        v["cut_dur_ms"] = round(len(y) / sr * 1000.0, 1)
    report = {"src": args.src, "out": args.out,
              "params": {"frame_ms": FRAME_MS, "hop_ms": HOP_MS,
                         "close_drop_db": CLOSE_DROP_DB, "close_hold_ms": CLOSE_HOLD_MS,
                         "min_mora_ms": MIN_MORA_MS, "fade_out_ms": FADE_OUT_MS,
                         "onset_dbfs": ONSET_DBFS},
              "items": items}
    with open(os.path.join(args.out, "crop_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  → {args.out}")


if __name__ == "__main__":
    main()
