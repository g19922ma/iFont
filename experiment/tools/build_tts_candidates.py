#!/usr/bin/env python3
"""
話者候補の合成音を作り、清濁の手がかり（VOT）を機械測定する
==============================================================
計画書: project/実験計画書_転写検証.md 4.4(刺激)／まとめ: project/合成音声_話者候補.md

**この台本の要点は「音に手を加えない」ことである。**
VOICEVOX に text と speaker を渡して返ってきた設定(audio_query)を、
**1つも書き換えずに**そのまま合成へ回す。話速・音高・抑揚・音量・前後の間、
どれも既定値のまま。長さの統一・音の高さの平坦化・VOT の補正・字ごとのフィルタ・
文脈からの切り出し、いずれも行わない。

以前の刺激づくりは合成音に手を加えた結果、「ぽ」が濁って聞こえる不具合を出した
(project/清濁診断_音響測定.md)。同じ轍を踏まないため、加工の口を最初から作らない。

唯一そろえるのは音量である。1音まるごとに一定の倍率を掛けるだけで、
音の中身の強弱の配分は変えない(自然音声のときと同じ方針・計画書 Q8)。

配信用のハイパスについて
------------------------
自然音声では電源ハム(50/60Hz)を落とすために配信する音そのものに 100Hz の
ハイパスを掛けていた。**合成音にはハムがないので、この 100Hz ハイパスは掛けない。**
（onset を検出するときだけ 150Hz のハイパスを掛けるのは自然音声と同じ。
  これは検出用の一時的な処理で、書き出す音には残らない。）

測る値
------
  onset_ms  … 音の実体が始まる点。`segment_natural_recording.detect_onset` を
              そのまま呼ぶので、自然音声と同じ規則(5ms窓・1ms刻み・
              背景雑音床+10dB が 10ms 続いた最初の点・検出用ハイパス150Hz)
  burst_ms  … 破裂の瞬間。高い帯域(1.5kHz以上)の力が急に立ち上がる点
  voice_ms  … 声帯が鳴り始める点。波形に周期が現れる点
  vot_ms    … voice_ms − burst_ms。**清濁の手がかりそのもの**
              正なら「破裂のあとに声」(無声。か・た・ぱ)
              負なら「破裂の前から声」(有声の中でも強い手がかり。が・だ・ば)

出力
----
  <out>/<話者名>/<かな>.wav      … 無加工の全長(音量そろえ済み)。**コミットしない**
  <out>/measurements.json        … 全話者ぶんの測定値
  <out>/speakers.json            … 話者の一覧とクレジット文言

使い方
------
  # VOICEVOX エンジンを起動しておく(既定 http://127.0.0.1:50021)
  python3 experiment/tools/build_tts_candidates.py
  python3 experiment/tools/build_tts_candidates.py --speakers 108,13,29,8
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
from scipy.signal import butter, sosfiltfilt

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from segment_natural_recording import KANA68, short_time_db, detect_onset  # noqa: E402

# 回答に使うかな表と同じ68字(を・ぢ・づ・ゔ を除く)。自然音声のときと同じ表を使う。
KANA = list(KANA68)

# 清濁の手がかりを見たい組と、以前つまずいた字。試聴ページの上に固定して並べる。
PAIRS = [("か", "が"), ("た", "だ"), ("ぱ", "ば"), ("さ", "ざ"), ("は", "ば")]
WATCH = ["ぽ", "ぴ", "ぷ"]
FOCUS = [k for k in ["か", "が", "た", "だ", "ぱ", "ば", "ぽ", "ぴ", "ぷ"]]

# 破裂で始まる字。VOT はこの字にしか意味がない。
VOICELESS_STOP = set("かきくけこたてとぱぴぷぺぽ")
VOICED_STOP = set("がぎぐげごだでどばびぶべぼ")
STOPS = VOICELESS_STOP | VOICED_STOP

ONSET_HPF_HZ = 150.0      # onset 検出**だけ**に使うハイパス(自然音声と同じ)
BURST_HPF_HZ = 1500.0     # 破裂を探すときに見る帯域の下端
FRAME_MS = 5.0            # 窓長(自然音声の onset 検出と同じ)
HOP_MS = 1.0              # 刻み
VOICE_SUSTAIN_MS = 20.0   # 「声が鳴っている」とみなすのに必要な継続
VOICE_AC_THR = 0.45       # 自己相関の山の高さのしきい値
F0_MIN, F0_MAX = 60.0, 450.0


class _OnsetArgs:
    """`detect_onset` に渡す設定。自然音声(build_adopted_stimuli.py)の既定と同じ。

    ※合成音の頭は事実上の無音なので、背景雑音床は関数内の予備値(-80dBFS)に落ちる。
      しきい値は -70dBFS となる。ピークは -16dBFS 前後なので十分低い。
    """
    onset_win_ms = FRAME_MS
    onset_hop_ms = HOP_MS
    onset_sustain_ms = 10.0
    onset_lookback_ms = 0.0
    noise_win_ms = 60.0
    thr_offset_db = 10.0


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
    return vv(base, "/synthesis", {"speaker": speaker}, data=q)


def speaker_table(base):
    with urllib.request.urlopen(base + "/speakers", timeout=30) as r:
        return json.load(r)


def speaker_policy(base, uuid):
    with urllib.request.urlopen(
            base + "/speaker_info?" + urllib.parse.urlencode({"speaker_uuid": uuid}),
            timeout=30) as r:
        return json.load(r).get("policy", "")


# ---- WAV --------------------------------------------------------------------
def read_wav_bytes(b):
    with wave.open(io.BytesIO(b), "rb") as w:
        n_ch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if n_ch > 1:
        x = x.reshape(-1, n_ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    y = np.clip(x, -1.0, 1.0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(np.round(y * 32767.0).astype("<i2").tobytes())


def hpf(x, sr, hz):
    return sosfiltfilt(butter(4, hz / (sr / 2.0), "highpass", output="sos"), x)


# ---- 測定 --------------------------------------------------------------------
def _first_run(flags, need):
    run = 0
    for i, ok in enumerate(flags):
        run = run + 1 if ok else 0
        if run >= need:
            return i - need + 1
    return None


def periodicity(x, sr, win_ms=40.0, hop_ms=HOP_MS):
    """窓ごとに「波形にどれだけ周期があるか」(0〜1)を返す。窓の**中央**の時刻に対応させる。

    声(母音・有声子音)には周期があり、息の音や破裂の音にはない。
    低い帯域の強さだけで見ると破裂まで「声」に数えてしまうので、**周期**を見る。
    1kHz までを見れば基本周波数とすぐ上の倍音が入り、雑音の影響を受けにくい。

    ※窓は40ms取る。低い声(基本周波数90Hz前後の男声)だと25msでは周期が2つ強しか入らず、
      「周期がある」と判定できない(最初の実装は青山龍星でほぼ全滅した)。
    ※自己相関はずらし幅ごとに重なりが短くなるので、重なる範囲の力で割り直す
      (割り直さないと、ずらし幅の大きい=低い声ほど値が小さく出てしまう)。
    """
    lp = sosfiltfilt(butter(4, 1000.0 / (sr / 2.0), "lowpass", output="sos"), x)
    wl = max(8, int(round(sr * win_ms / 1000.0)))
    hp = max(1, int(round(sr * hop_ms / 1000.0)))
    n = 1 + max(0, (len(lp) - wl) // hp)
    lag_lo, lag_hi = int(sr / F0_MAX), min(int(sr / F0_MIN), wl - 8)
    out = np.zeros(n)
    for i in range(n):
        r = lp[i * hp:i * hp + wl]
        r = r - r.mean()
        best = 0.0
        for lag in range(lag_lo, lag_hi):
            a, b = r[:wl - lag], r[lag:]
            den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
            if den > 1e-14:
                v = float((a * b).sum()) / den
                if v > best:
                    best = v
        out[i] = best
    center_ms = (np.arange(n) * hp + wl / 2.0) / sr * 1000.0
    return out, center_ms


def _band_db(x, sr, lo, hi, win_ms=FRAME_MS):
    """帯域を切り出したうえでの短時間エネルギー(dB)。窓の**先頭**の時刻に対応させる
    (acoustic onset の測り方と同じ扱いにするため)。"""
    if hi is None:
        y = hpf(x, sr, lo)
    else:
        y = sosfiltfilt(butter(4, [lo / (sr / 2.0), hi / (sr / 2.0)], "bandpass",
                               output="sos"), x)
    db, hop = short_time_db(y, sr, win_ms, HOP_MS)
    return db, np.arange(len(db)) * (hop / sr * 1000.0)


def _nccf_at(sig, i, lag, nwin):
    a = sig[i:i + nwin]
    b = sig[i + lag:i + lag + nwin]
    if len(a) < nwin or len(b) < nwin:
        return 0.0
    a = a - a.mean(); b = b - b.mean()
    den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return 0.0 if den <= 1e-14 else float((a * b).sum()) / den


def _voice_onset_refine(x, sr, t_coarse_ms, back_ms=110.0, thr=0.5):
    """声が出はじめる時刻を1ms刻みまで詰める。

    やり方: 声が確かに鳴っている時点で周期の長さ(基本周期)を求め、その長さぶん
    ずらした波形と重なるかを、1msずつ手前へ戻りながら確かめる。重ならなくなった
    ところが声の出はじめ。破裂の音は周期がないので、ここで自然に止まる。

    返す時刻は「窓の先頭」で、acoustic onset の測り方とそろえてある。
    ずれは最大で周期1つぶん(低い男声で約10ms)。
    """
    lp = sosfiltfilt(butter(4, 1000.0 / (sr / 2.0), "lowpass", output="sos"), x)
    i_c = int(round(t_coarse_ms / 1000.0 * sr))
    lag_lo, lag_hi = int(sr / F0_MAX), int(sr / F0_MIN)
    # 基本周期: 確実に声が鳴っている少し後ろの窓で決める
    probe = min(i_c + int(0.01 * sr), max(0, len(lp) - 3 * lag_hi))
    best, lag = 0.0, None
    for L in range(lag_lo, lag_hi):
        v = _nccf_at(lp, probe, L, 2 * L)
        if v > best:
            best, lag = v, L
    if lag is None:
        return round(t_coarse_ms, 1)
    nwin, step = 2 * lag, max(1, int(round(sr / 1000.0)))
    i0 = max(0, i_c - int(back_ms / 1000.0 * sr))
    ref = math.sqrt(float((lp[probe:probe + nwin] ** 2).mean()) + 1e-20)

    def ok(i):
        seg = lp[i:i + nwin]
        if len(seg) < nwin:
            return False
        # 力が声の1/6を下回ったらもう声ではない。**この歯止めがないと破裂まで戻る**
        # (破裂の音にも低い成分が含まれ、たまたま周期が合ってしまうことがある)。
        if math.sqrt(float((seg ** 2).mean())) < ref * 0.16:
            return False
        return _nccf_at(lp, i, lag, nwin) > thr

    i = i_c
    while i - step >= i0 and ok(i - step):
        i -= step
    return round(i / sr * 1000.0, 1)


def measure(x, sr, kana):
    """1字ぶんの測定。時刻はファイル先頭からのミリ秒。"""
    det = hpf(x, sr, ONSET_HPF_HZ)
    on_abs, floor_db, thr_db, found = detect_onset(det, sr, 0, len(det), _OnsetArgs)
    onset_ms = None if not found else round(on_abs / sr * 1000.0, 1)

    out = {"onset_ms": onset_ms, "voice_ms": None, "burst_ms": None,
           "vot_ms": None, "prevoiced": None,
           "dur_ms": round(len(x) / sr * 1000.0, 1),
           "thr_dbfs": round(thr_db, 1)}

    # ---- 声が出はじめる時刻 --------------------------------------------------
    # (1) おおまかに: 周期があり、かつ低い帯域に力がある窓が 20ms 続いた最初の点。
    per, per_ms = periodicity(x, sr)
    low_db, low_ms = _band_db(x, sr, 60.0, 1000.0)
    if len(low_db) < 8:
        return out
    low_peak = float(np.max(low_db))
    loud_at = np.interp(per_ms, low_ms, low_db) > (low_peak - 30.0)
    need_v = max(1, int(round(VOICE_SUSTAIN_MS / HOP_MS)))
    vi = _first_run((per > VOICE_AC_THR) & loud_at, need_v)
    if vi is not None:
        # (2) 細かく: 40ms窓は時刻がぼやけるので、声の周期そのものを手がかりに詰める。
        #     ここで「低い帯域の力が立ち上がる点」を使ってはいけない。破裂の音にも
        #     低い成分は含まれるので、破裂まで戻ってしまう(最初の実装はこれで
        #     東北きりたんの「か」の VOT が 2ms になった)。
        #     声が鳴っている区間で周期の長さを求め、**その長さの繰り返しがあるか**を
        #     1msずつさかのぼって確かめる。
        v = _voice_onset_refine(x, sr, float(per_ms[vi]))
        # 音の実体が始まる前に声だけ鳴ることはない。行き過ぎたら onset で止める。
        out["voice_ms"] = v if onset_ms is None else round(max(v, onset_ms), 1)

    if kana not in STOPS or onset_ms is None:
        return out

    # ---- 破裂の瞬間 ----------------------------------------------------------
    # 高い帯域(1.5kHz以上)の力が急に立ち上がる点。onset の 20ms 手前から 200ms 後ろまで探す。
    # (有声の破裂では破裂の前に声だけが鳴るので、onset は破裂よりかなり手前に付きうる。
    #  だから後ろ側を広く取る。)
    # ※探しはじめを onset より前へ広げすぎてはいけない。区間の先頭では「3ms前との差」が
    #   取れず、そこに偽の立ち上がりが立って破裂が onset より20ms前に出た(最初の実装)。
    hdb, hms = _band_db(x, sr, BURST_HPF_HZ, None)
    i0 = max(0, int(np.searchsorted(hms, onset_ms - 5.0)))
    i1 = min(len(hdb) - 1, int(np.searchsorted(hms, onset_ms + 200.0)))
    if i1 - i0 > 6:
        seg = hdb[i0:i1 + 1]
        rise = seg[3:] - seg[:-3]     # 3ms のあいだにどれだけ上がったか
        peak = float(rise.max())
        if peak > 6.0:
            # 「いちばん急」だけを取ると、破裂の少しあとの母音の立ち上がりを拾うことがある。
            # いちばん急の6割(かつ6dB以上)を超えた**最初の**点を破裂とする。
            j = int(np.argmax(rise >= max(6.0, peak * 0.6)))
            out["burst_ms"] = round(float(hms[i0 + j]), 1)

    if out["burst_ms"] is not None and out["voice_ms"] is not None:
        out["vot_ms"] = round(out["voice_ms"] - out["burst_ms"], 1)
        out["prevoiced"] = bool(out["vot_ms"] < -5.0)
    return out


def rms_dbfs(x):
    return 20 * math.log10(math.sqrt((x ** 2).mean()) + 1e-20)


# ---- 本体 --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:50021")
    ap.add_argument("--speakers", default="108,13,29,8",
                    help="話者(スタイル)IDをカンマ区切り。ノーマル系のみ")
    ap.add_argument("--out", default=os.path.join(EXP, "tts_candidates"))
    args = ap.parse_args()

    ids = [int(v) for v in args.speakers.split(",") if v.strip()]
    info = {}
    for s in speaker_table(args.base):
        for st in s["styles"]:
            info[st["id"]] = (s["name"], st["name"], s.get("speaker_uuid", ""))

    os.makedirs(args.out, exist_ok=True)
    speakers_meta, all_meas = [], {}
    for sid in ids:
        if sid not in info:
            raise SystemExit(f"話者ID {sid} が見つかりません")
        name, style, uuid = info[sid]
        if "ささやき" in style or "ヒソヒソ" in style:
            # 声帯が鳴らないので清濁の手がかり(声の出はじめ)がそもそも存在しない。
            raise SystemExit(f"{name}／{style} は声帯が鳴らないため使えません")
        d = os.path.join(args.out, name)
        os.makedirs(d, exist_ok=True)
        print(f"── {name}／{style}（ID {sid}）", flush=True)

        raw = {}
        for ch in KANA:
            x, sr = read_wav_bytes(synth(args.base, ch, sid))
            raw[ch] = (x, sr)

        # 音量そろえ: 1音まるごとに一定の倍率。いちばん小さい字に合わせ、増幅はしない
        # (倍率は1.0以下)。音の中身の強弱の配分は変えない。
        levels = {ch: rms_dbfs(v[0]) for ch, v in raw.items()}
        target = min(levels.values())
        meas = {}
        for ch, (x, sr) in raw.items():
            gain = 10 ** ((target - levels[ch]) / 20.0)
            y = x * gain
            write_wav(os.path.join(d, ch + ".wav"), y, sr)
            m = measure(y, sr, ch)
            m.update({"gain_db": round(20 * math.log10(gain), 2),
                      "rms_dbfs_before": round(levels[ch], 2), "sr": sr})
            meas[ch] = m

        all_meas[name] = meas
        speakers_meta.append({
            "id": sid, "name": name, "style": style, "uuid": uuid, "dir": name,
            "credit": f"VOICEVOX:{name}",
            "policy": speaker_policy(args.base, uuid).strip(),
        })
        line = "  ".join(f"{k}={meas[k]['vot_ms']}" for k in FOCUS if meas[k]["vot_ms"] is not None)
        print(f"   VOT(ms): {line}", flush=True)

    with io.open(os.path.join(args.out, "measurements.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": {
            "engine": "VOICEVOX", "engine_url": args.base,
            "processing": "無加工(audio_queryは既定のまま)／音量そろえのみ(1音1倍率・増幅なし)",
            "delivery_highpass_hz": None,
            "delivery_highpass_note": "合成音には電源ハムがないため、自然音声で掛けていた"
                                      "配信用100Hzハイパスは掛けていない",
            "onset_detect_highpass_hz": ONSET_HPF_HZ,
            "onset_rule": "背景雑音床+10dB を 10ms 継続(5ms窓・1ms刻み)。"
                          "自然音声と同じ segment_natural_recording.detect_onset",
            "burst_detect_highpass_hz": BURST_HPF_HZ,
            "vot_definition": "voice_ms − burst_ms。負は破裂より前に声が始まっている(有声)",
            "frame_ms": FRAME_MS, "hop_ms": HOP_MS,
        }, "kana": KANA, "focus": FOCUS,
            "pairs": [list(p) for p in PAIRS], "watch": WATCH,
            "speakers": {s["name"]: s for s in speakers_meta},
            "measurements": all_meas}, f, ensure_ascii=False, indent=1)
    with io.open(os.path.join(args.out, "speakers.json"), "w", encoding="utf-8") as f:
        json.dump({"speakers": speakers_meta}, f, ensure_ascii=False, indent=1)

    print(f"\n書き出し: {args.out}  話者{len(ids)} × {len(KANA)}字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
