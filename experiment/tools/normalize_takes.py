#!/usr/bin/env python3
"""
切り出した1モーラの音の大きさをそろえる
=======================================
2026-08-24 作成。**この工程のスクリプトも今まで残っていなかった**ので書き起こした。

なにをそろえるのか
------------------
打ち切り実験では「何ミリ秒聞けば字が分かるか」を測る。**音の大きさが字ごとに
違うと、聞き取りやすさが時間ではなく音量で決まってしまう**（交絡）。そこで
字ごとの聞こえの大きさをそろえる。

「聞こえの大きさ」は、波形の実効値そのままではなく **A特性で重みづけした実効値**
を使う。人の耳は低い音と高い音に鈍いので、実効値が同じでも高い音（サ行の摩擦）は
小さく聞こえる。A特性はその感度の違いを補正する重みで、
experiment/tools/build_onsets.py が同じ考え方を使っている。

⚠ 外れ値の扱い（2026-08-23 の失敗を繰り返さないこと）
-----------------------------------------------------
無声子音＋狭母音の字（く・き・す など）は、**自然にとても小さい**。あみたろの「く」は
-47.3dBFS で、68字中で飛び抜けて小さかった。ここで
**「いちばん小さい字に合わせる」方式を採ると、他の67字すべてが27dB も静かになる**
（2026-08-23 に実際に起きた）。

そこで:
  1. 基準を決めるときは、**四分位範囲（IQR）で外れ値を先に除く**
     （第1四分位 −1.5×IQR より小さい字・第3四分位 +1.5×IQR より大きい字）
  2. 基準は、残った字の**中央値**
  3. **外れ値の字は増幅しない**（そのままの小ささで残す）。無理に持ち上げると
     背景の雑音まで一緒に大きくなるうえ、その字だけ音が荒れる。
     もともと小さい音である事実は、日本語としては自然なので残してよい

使い方
------
  python3 experiment/tools/normalize_takes.py \\
      --src experiment/tts_candidates_carrier2/cut \\
      --out experiment/tts_candidates_carrier2/norm
"""
import argparse
import json
import math
import os
import wave

import numpy as np

PEAK_CAP = 0.85        # 増幅後のピークの上限（クリップ防止）
IQR_K = 1.5            # 外れ値と見なす幅（四分位範囲の何倍か）


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


def a_weight(f):
    """A特性の重み（1kHz を 1 とする）。build_onsets.py と同じ式。"""
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = ((12194.0 ** 2 * f ** 4)
          / ((f ** 2 + 20.6 ** 2)
             * np.sqrt((f ** 2 + 107.7 ** 2) * (f ** 2 + 737.9 ** 2))
             * (f ** 2 + 12194.0 ** 2)))
    k = 1000.0
    ra1k = ((12194.0 ** 2 * k ** 4)
            / ((k ** 2 + 20.6 ** 2)
               * math.sqrt((k ** 2 + 107.7 ** 2) * (k ** 2 + 737.9 ** 2))
               * (k ** 2 + 12194.0 ** 2)))
    return ra / ra1k


def a_weighted_rms(x, sr):
    """A特性で重みづけした実効値。無音の部分は数えない。"""
    n = 1 << int(np.ceil(np.log2(max(len(x), 2))))
    spec = np.fft.rfft(x, n)
    w = a_weight(np.fft.rfftfreq(n, 1.0 / sr))
    y = np.fft.irfft(spec * w, n)[:len(x)]
    # 音のある区間だけで測る（前置きの静けさで薄まらないように）
    fr = max(1, int(sr * 0.005))
    m = len(y) // fr
    if m:
        rms = np.sqrt((y[:m * fr].reshape(m, fr) ** 2).mean(axis=1) + 1e-20)
        loud = rms[rms > rms.max() * 0.05]
        if len(loud):
            return float(np.sqrt((loud ** 2).mean()))
    return float(np.sqrt((y ** 2).mean() + 1e-20))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    names = sorted(n for n in os.listdir(args.src) if n.endswith(".wav"))
    if not names:
        raise SystemExit(f"WAV が1つもありません: {args.src}")

    sig = {}
    for n in names:
        kana = os.path.splitext(n)[0]
        x, sr = read_wav(os.path.join(args.src, n))
        sig[kana] = (x, sr, a_weighted_rms(x, sr))

    vals = np.array([v[2] for v in sig.values()])
    db = 20 * np.log10(vals + 1e-12)
    q1, q3 = np.percentile(db, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - IQR_K * iqr, q3 + IQR_K * iqr
    inliers = {k: v for k, v in sig.items() if lo <= 20 * np.log10(v[2] + 1e-12) <= hi}
    outliers = [k for k in sig if k not in inliers]
    target = float(np.median([v[2] for v in inliers.values()]))

    print(f"  {len(names)} 字。聞こえの大きさ（A特性）の分布: "
          f"{db.min():.1f} 〜 {db.max():.1f} dB（中央 {np.median(db):.1f}）")
    print(f"  外れ値の判定: {lo:.1f} dB 未満 または {hi:.1f} dB 超")
    print(f"  外れ値（増幅しないでそのまま残す）: "
          f"{' '.join(f'{k}({20*math.log10(sig[k][2]+1e-12):.1f}dB)' for k in outliers) or 'なし'}")
    print(f"  基準（外れ値を除いた中央値）: {20*math.log10(target):.1f} dB")

    os.makedirs(args.out, exist_ok=True)
    report = {"src": args.src, "out": args.out,
              "target_a_rms_dbfs": round(20 * math.log10(target), 2),
              "iqr_k": IQR_K, "peak_cap": PEAK_CAP,
              "outliers_left_as_is": outliers, "items": {}}
    capped = []
    for kana, (x, sr, v) in sig.items():
        if kana in outliers:
            gain = 1.0
        else:
            gain = target / max(v, 1e-12)
            peak = np.abs(x).max() * gain
            if peak > PEAK_CAP:
                gain *= PEAK_CAP / peak
                capped.append(kana)
        write_wav(os.path.join(args.out, kana + ".wav"), x * gain, sr)
        report["items"][kana] = {
            "a_rms_dbfs_before": round(20 * math.log10(v + 1e-12), 2),
            "gain_db": round(20 * math.log10(gain), 2),
            "outlier": kana in outliers,
            "peak_after": round(float(np.abs(x).max() * gain), 4),
        }
    if capped:
        print(f"  クリップ防止で増幅を抑えた字: {' '.join(capped)}")
    with open(os.path.join(args.out, "normalize_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  → {args.out}")


if __name__ == "__main__":
    main()
