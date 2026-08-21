#!/usr/bin/env python3
"""
VOICEVOX で全68かなを「無加工」で合成する
=========================================
計画書: project/実験計画書_転写検証.md 4.4(刺激)

**この台本の要点は「何もしない」ことである。**
VOICEVOX に text と speaker を渡して返ってきた設定(audio_query)を、
**1つも書き換えずに**そのまま合成へ回す。長さの統一・音の高さの平坦化・
VOT の補正・字ごとのフィルタ・文脈からの切り出し、いずれも行わない。

以前の刺激づくりは合成音に手を加えた結果、「ぽ」が濁って聞こえる不具合を出した
(project/清濁診断_音響測定.md)。同じ轍を踏まないため、加工の口を最初から作らない。

唯一そろえるのは音量である。1音まるごとに一定の倍率を掛けるだけで、
音の中身の強弱の配分は変えない(自然音声のときと同じ方針・計画書 Q8)。
これは別の台本(build_transfer_gates.py)ではなく、ここで onset 表と一緒に出す。

出力
----
  <out>/<話者ID>/<かな>.wav        … 無加工の全長(音量そろえ済み)
  <out>/onsets_<話者ID>.json       … acoustic onset と VOT の測定値
  <out>/speakers.json              … 試聴ページが読む話者の一覧

使い方
------
  # VOICEVOX エンジンを起動しておく(既定 http://127.0.0.1:50021)
  python3 experiment/tools/build_voicevox_stimuli.py \\
      --speakers 108,13,29,8 --out experiment/voicevox_audition
"""
import argparse
import io
import json
import math
import os
import sys
import urllib.parse
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)

# 回答に使うかな表と同じ68字(transfer_config.js の answer_grid)。
KANA = list("あいうえお" "かきくけこ" "さしすせそ" "たちつてと" "なにぬねの"
            "はひふへほ" "まみむめも" "やゆよ" "らりるれろ" "わん"
            "がぎぐげご" "ざじずぜぞ" "だでど" "ばびぶべぼ" "ぱぴぷぺぽ")

# 清濁の手がかりを見たい組。試聴ページの上に固定して並べる。
FOCUS = ["ぱ", "ば", "か", "が", "た", "だ", "ぴ", "ぷ", "ぽ"]

# 検出の刻み(自然音声のときと同じ 5ms 窓)。
FRAME_MS = 5.0
NOISE_OVER_DB = 10.0    # 背景雑音床から何dB超えたら「鳴っている」とみなすか
HOLD_MS = 10.0          # その状態が何ms続いたら本物とみなすか


# ---- VOICEVOX ---------------------------------------------------------------
def vv(base, path, params=None, data=None, timeout=60):
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, data=data, method="POST")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def synth(base, text, speaker):
    """1字を合成して WAV のバイト列を返す。**audio_query は一切書き換えない。**"""
    q = vv(base, "/audio_query", {"text": text, "speaker": speaker})
    return vv(base, "/synthesis", {"speaker": speaker}, data=q), json.loads(q)


def speaker_table(base):
    with urllib.request.urlopen(base + "/speakers", timeout=30) as r:
        return json.load(r)


# ---- WAV --------------------------------------------------------------------
def read_wav_bytes(b):
    with wave.open(io.BytesIO(b), "rb") as w:
        n_ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if n_ch > 1:
        x = x.reshape(-1, n_ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    y = np.clip(x, -1.0, 1.0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y * 32767.0).astype("<i2").tobytes())


# ---- 測定 --------------------------------------------------------------------
def frames(x, sr, win_ms=25.0, hop_ms=FRAME_MS):
    """長めの窓を 5ms ずつずらして切り出す。

    窓を 5ms にすると周波数の分解能が 200Hz しかなく、破裂の高い成分と声の低い成分を
    見分けられない(最初の実装はこれで失敗した)。窓は 25ms 取り、位置の細かさは
    ずらし幅 5ms で確保する。
    """
    w = max(8, int(round(sr * win_ms / 1000.0)))
    h = max(1, int(round(sr * hop_ms / 1000.0)))
    n = 1 + max(0, (len(x) - w) // h)
    idx = np.arange(w)[None, :] + h * np.arange(n)[:, None]
    return x[idx] * np.hanning(w)[None, :], h


def band_db(F, sr, lo, hi):
    spec = np.abs(np.fft.rfft(F, axis=1))
    freqs = np.fft.rfftfreq(F.shape[1], 1.0 / sr)
    m = (freqs >= lo) & (freqs < hi)
    return 20 * np.log10(np.sqrt((spec[:, m] ** 2).sum(axis=1)) + 1e-12)


def voiced_flags(F, sr, fmin=60.0, fmax=400.0, thr=0.35):
    """声帯が鳴っているか。窓ごとに自己相関の山の高さで判定する。

    低い帯域の強さだけで見ると、破裂の音も「声」に数えてしまう。
    声には**周期**があるので、そこを見るほうが確かである。
    """
    out = []
    lag_lo = int(sr / fmax)
    lag_hi = int(sr / fmin)
    for row in F:
        r = row - row.mean()
        e0 = float((r * r).sum())
        if e0 <= 1e-12:
            out.append(False); continue
        ac = np.correlate(r, r, mode="full")[len(r) - 1:]
        seg = ac[lag_lo:min(lag_hi, len(ac))]
        out.append(bool(len(seg) and (seg.max() / e0) > thr))
    return np.array(out)


def first_sustained(over, hold_frames):
    run = 0
    for i, ok in enumerate(over):
        run = run + 1 if ok else 0
        if run >= hold_frames:
            return i - hold_frames + 1
    return None


def measure(x, sr):
    """acoustic onset と「声が出はじめるまでの間」を測る。単位はミリ秒。

      onset_ms      … 音の実体が始まる点。自然音声と同じ規則(全帯域が雑音床+10dB)
      voice_ms      … 波形に周期が現れる点。声帯が鳴り始めた点
      voice_lag_ms  … voice_ms − onset_ms。**清濁の手がかりはここに出る**

    voice_lag_ms の読み方:
      無声の破裂(か・ぱ・た)は、破裂と息の音が先に立ち、声はそのあと。→ 数十ms
      有声の破裂(が・だ・ば)は、ほぼ最初から声が鳴っている。       → 0 に近い
    2つの差が小さい話者は、清濁の手がかりが弱いということになる。

    ※ 破裂の瞬間そのもの(burst)を自動で正確に取るのは難しく、最初の実装では
      当てにならない値になった。ここでは**測れるものだけ**を測り、
      破裂を起点とする本来の VOT は名乗らない。
    """
    hold = max(1, int(round(HOLD_MS / FRAME_MS)))
    F, hop = frames(x, sr)
    if len(F) < 4:
        return {"onset_ms": None, "voice_ms": None, "voice_lag_ms": None,
                "dur_ms": round(len(x) / sr * 1000.0, 1)}
    ms = lambda i: None if i is None else round(i * FRAME_MS, 1)

    full = band_db(F, sr, 0, sr / 2)
    q = max(4, len(full) // 10)
    loud = full > np.percentile(full[:q], 50) + NOISE_OVER_DB
    onset_i = first_sustained(loud, hold)
    # **鳴っていることを条件に足す。** 無音のところは振幅がほぼ0で、自己相関の比だけ見ると
    # 数値のゆらぎで「周期あり」と出てしまう(最初の実装はこれで音より前に声を検出した)。
    voice_i = first_sustained(voiced_flags(F, sr) & loud, hold)

    out = {"onset_ms": ms(onset_i), "voice_ms": ms(voice_i),
           "dur_ms": round(len(x) / sr * 1000.0, 1)}
    out["voice_lag_ms"] = (None if (onset_i is None or voice_i is None)
                           else round((voice_i - onset_i) * FRAME_MS, 1))
    return out


def rms_dbfs(x):
    return 20 * math.log10(math.sqrt((x ** 2).mean()) + 1e-20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:50021")
    ap.add_argument("--speakers", default="108,13,29,8",
                    help="話者(スタイル)IDをカンマ区切りで")
    ap.add_argument("--out", default=os.path.join(EXP, "voicevox_audition"))
    args = ap.parse_args()

    ids = [int(v) for v in args.speakers.split(",") if v.strip()]
    table = speaker_table(args.base)
    # スタイルID → (話者名, スタイル名, 話者UUID)
    info = {}
    for s in table:
        for st in s["styles"]:
            info[st["id"]] = (s["name"], st["name"], s.get("speaker_uuid", ""))

    os.makedirs(args.out, exist_ok=True)
    speakers_meta = []
    for sid in ids:
        if sid not in info:
            raise SystemExit(f"話者ID {sid} が見つかりません")
        name, style, uuid = info[sid]
        if "ささやき" in style or "ヒソヒソ" in style:
            raise SystemExit(f"{name}／{style} は声帯が鳴らないため使えません")
        d = os.path.join(args.out, str(sid))
        os.makedirs(d, exist_ok=True)
        print(f"── {name}／{style}（ID {sid}）")

        raw = {}
        for ch in KANA:
            b, q = synth(args.base, ch, sid)
            x, sr = read_wav_bytes(b)
            raw[ch] = (x, sr, q)

        # 音量そろえ: 1音まるごとに一定の倍率。いちばん小さい字の水準に合わせ、
        # 増幅はしない(倍率は1.0以下)。中身の強弱の配分は変えない。
        levels = {ch: rms_dbfs(v[0]) for ch, v in raw.items()}
        target = min(levels.values())
        onsets = {}
        for ch, (x, sr, q) in raw.items():
            gain = 10 ** ((target - levels[ch]) / 20.0)
            y = x * gain
            write_wav(os.path.join(d, ch + ".wav"), y, sr)
            m = measure(y, sr)
            m.update({"gain": round(gain, 4), "gain_db": round(20 * math.log10(gain), 2),
                      "rms_dbfs_before": round(levels[ch], 2), "sr": sr})
            onsets[ch] = m

        with io.open(os.path.join(args.out, f"onsets_{sid}.json"), "w", encoding="utf-8") as f:
            json.dump({"meta": {"speaker_id": sid, "speaker": name, "style": style,
                                "engine": "VOICEVOX", "processing": "無加工(audio_queryは既定のまま)"
                                              "／音量そろえのみ(1音1倍率・増幅なし)",
                                "target_rms_dbfs": round(target, 2),
                                "frame_ms": FRAME_MS},
                       "kana": onsets}, f, ensure_ascii=False, indent=1)

        lags = {ch: onsets[ch]["voice_lag_ms"] for ch in FOCUS if ch in onsets}
        print("   声が出るまで(ms): " + "  ".join(f"{k}={v}" for k, v in lags.items()))
        speakers_meta.append({"id": sid, "name": name, "style": style, "uuid": uuid,
                              "credit": f"VOICEVOX:{name}"})

    with io.open(os.path.join(args.out, "speakers.json"), "w", encoding="utf-8") as f:
        json.dump({"speakers": speakers_meta, "kana": KANA, "focus": FOCUS}, f,
                  ensure_ascii=False, indent=1)
    print(f"\n書き出し: {args.out}  話者{len(ids)} × {len(KANA)}字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
