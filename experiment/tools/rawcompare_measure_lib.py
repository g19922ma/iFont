#!/usr/bin/env python3
"""
音源比較セット（raw_compare_v1）の音響測定ライブラリ
====================================================
「無加工の音源をそのまま測る」ための共通関数。build / measure / 話者えらびの
下見（probe）から同じ関数を呼ぶことで、どの場面でも同じ物差しで測る。

測る中身（専門用語には日本語の言いかえを添える）:

  acoustic onset（音の立ち上がり）
      ファイルの先頭から数えて、音が鳴りはじめる時刻（ミリ秒）。
      本番プールの切り出しと同じ判定（5ミリ秒ごとの音量が -63 dBFS を
      15ミリ秒continuously超えた最初の点）を使う。

  burst（破裂の瞬間）
      「ぱ」「か」などで唇や舌が離れて空気が弾ける時刻。
      1ミリ秒ごとの音量が最も急に立ち上がる点をとる。

  VOT (voice onset time / 有声開始時間)
      破裂の瞬間から、声帯が震えはじめるまでの時間（ミリ秒）。
      日本語では無声（清音）が およそ +25〜+45 ミリ秒、
      有声（濁音）は 0 前後か、破裂より前から声が出ていて マイナス になる。
      マイナスは prevoicing（前もって声帯が震えている）を意味し、
      濁音だと聞き取るための最も強い手がかり。
      ここでは prevoicing があればその長さを符号マイナスで返し、
      なければ破裂から声の出はじめまでの正の値を返す。

  peak dBFS（最大振幅）
      いちばん大きい瞬間の振幅。0 dBFS が録音の天井で、
      0 に届くと clipping（音が割れる）になる。

  RMS dBFS（実効値）
      鳴っている区間全体をならした音の大きさ。聞いた印象の音量に近い。

声帯振動の探索範囲（pitch floor / ceiling）は話者の声の高さで変えないと、
低い男声で「声が出ていない」と誤判定する。話者ごとに実測した中央値から自動で決める。
"""
import io
import math
import subprocess
import wave

import numpy as np
import parselmouth

# --- 本番プール(build_onsets.py)と同一の立ち上がり判定パラメータ ---
ONSET_DBFS = -63.0   # この音量を超えたら「鳴っている」とみなす
SUSTAIN_MS = 15      # 上記を続けて超えるべき時間（単発のノイズを拾わないため）
FRAME_MS = 5         # 判定に使う窓の長さ

# 破裂音（VOT を測る対象）
PLOSIVES = {"か", "が", "ぱ", "ば", "た", "だ"}
VOICED_PLOSIVES = {"が", "ば", "だ"}


# ---------------------------------------------------------------- 入出力
def decode(path):
    """mp3 でも wav でも、ffmpeg を通して同じ形（-1〜1 の波形と標本化周波数）で読む。"""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-f", "wav", "pipe:1"],
        stdout=subprocess.PIPE, check=True)
    with wave.open(io.BytesIO(p.stdout), "rb") as w:
        fr = w.getframerate()
        ch = w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, fr


def wav_bytes_to_np(b):
    with wave.open(io.BytesIO(b), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def np_to_wav_bytes(x, fr):
    """16bit PCM の WAV を作る。フェードもディザも掛けない（そのまま量子化するだけ）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fr)
        w.writeframes(np.clip(np.rint(x * 32767), -32768, 32767).astype("<i2").tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------- 基本量
def db(v):
    return 20 * math.log10(max(float(v), 1e-12))


def rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def frame_db(x, fr):
    fl = max(1, int(FRAME_MS / 1000 * fr))
    n = len(x) // fl
    if n == 0:
        return np.array([-120.0])
    r = np.sqrt(np.mean(x[:n * fl].reshape(n, fl) ** 2, axis=1))
    return 20 * np.log10(np.maximum(r, 1e-7))


def onset_ms(x, fr):
    """音の立ち上がり（ファイル先頭基準・ミリ秒）。本番プールと同じ判定。"""
    d = frame_db(x, fr)
    need = max(1, int(SUSTAIN_MS / FRAME_MS))
    for i in range(len(d) - need + 1):
        if np.all(d[i:i + need] > ONSET_DBFS):
            return float(i * FRAME_MS)
    return 0.0


def offset_ms(x, fr):
    """音が鳴り終わる時刻（ファイル先頭基準・ミリ秒）。"""
    d = frame_db(x, fr)
    idx = np.where(d > ONSET_DBFS)[0]
    return float(idx[-1] * FRAME_MS + FRAME_MS) if len(idx) else len(x) / fr * 1000


def active_rms_dbfs(x, fr):
    """鳴っている区間だけの実効値。前後の無音でうすまらないようにする。"""
    a = int(onset_ms(x, fr) / 1000 * fr)
    b = int(offset_ms(x, fr) / 1000 * fr)
    seg = x[a:b] if b > a else x
    return db(rms(seg))


def peak_dbfs(x):
    return db(float(np.max(np.abs(x))) if len(x) else 0.0)


def clipping(x, fr):
    """振幅が天井に張りついた標本の数。1つでもあれば音が割れている可能性。"""
    n = int(np.sum(np.abs(x) >= 0.9995))
    return n


# ---------------------------------------------------------------- 声の高さ
def median_f0(x, fr, floor=60, ceiling=600):
    try:
        f = parselmouth.Sound(x, fr).to_pitch(0.005, floor, ceiling).selected_array["frequency"]
        v = f[f > 0]
        return float(np.median(v)) if len(v) else None
    except Exception:
        return None


def pitch_range_for(f0):
    """実測した声の高さから、声帯振動を探すときの下限・上限を決める。
    低い男声に女声用の下限(150Hz)を当てると「声が出ていない」と誤判定するため。"""
    if not f0 or not np.isfinite(f0):
        return 70.0, 500.0
    return max(50.0, f0 * 0.55), min(900.0, f0 * 2.2)


# ---------------------------------------------------------------- 破裂と VOT
def find_burst_s(x, fr, from_s, search_s=0.15):
    """破裂の瞬間: 1ミリ秒ごとの音量がいちばん急に立ち上がる点。"""
    a = max(0, int(from_s * fr))
    seg = x[a: a + int(search_s * fr)]
    ms = max(1, int(fr / 1000))
    n = len(seg) // ms - 4
    if n < 5:
        return from_s
    env = np.array([db(rms(seg[i * ms:(i + 1) * ms])) for i in range(n)])
    i = int(np.argmax(env[2:] - env[:-2]))
    return from_s + i / 1000.0


def voiced_mask(x, fr, floor, ceiling, step=0.002):
    """声帯が震えている時間帯を True/False の並びで返す。"""
    try:
        p = parselmouth.Sound(x, fr).to_pitch(step, floor, ceiling)
        return p.selected_array["frequency"] > 0, p.xs()
    except Exception:
        return np.zeros(0, dtype=bool), np.zeros(0)


def vot_ms(x, fr, burst_s, floor, ceiling):
    """VOT を符号つきで返す。
    prevoicing（破裂より前に声帯が震えている）があれば、その連続長をマイナスで返す。
    なければ破裂から声の出はじめまでの時間をプラスで返す。
    戻り値: (vot_ms, prevoicing_ms, 破裂後の声の出はじめまでの時間 or None)
    """
    m, t = voiced_mask(x, fr, floor, ceiling)
    if len(m) == 0:
        return None, 0.0, None
    step = t[1] - t[0] if len(t) > 1 else 0.002
    bi = int(np.searchsorted(t, burst_s))
    bi = min(max(bi, 0), len(m) - 1)

    # 破裂の直前に連続して声が出ている長さ（prevoicing）
    j = bi
    while j > 0 and m[j - 1]:
        j -= 1
    pre_ms = (bi - j) * step * 1000.0
    # 2フレーム(≒4ms)以下は測定のゆらぎとみなす
    if pre_ms > 4.0:
        return round(-pre_ms, 1), round(pre_ms, 1), None

    # 破裂より後で最初に声が出る時刻
    k = bi
    while k < len(m) and not m[k]:
        k += 1
    if k >= len(m):
        return None, 0.0, None
    post_ms = (t[k] - burst_s) * 1000.0
    return round(post_ms, 1), 0.0, round(post_ms, 1)


def measure_file(path, char, f0_hint=None):
    """1ファイルを測って dict で返す。"""
    x, fr = decode(path)
    on = onset_ms(x, fr)
    f0 = median_f0(x, fr)
    floor, ceiling = pitch_range_for(f0_hint or f0)
    out = dict(
        char=char, sr=fr,
        duration_ms=round(len(x) / fr * 1000, 1),
        onset_ms=round(on, 1),
        peak_dbfs=round(peak_dbfs(x), 2),
        rms_dbfs=round(active_rms_dbfs(x, fr), 2),
        rms_full_dbfs=round(db(rms(x)), 2),
        clip_samples=clipping(x, fr),
        f0_median_hz=round(f0, 1) if f0 else None,
        vot_ms=None, prevoicing_ms=None, burst_ms=None,
    )
    if char in PLOSIVES:
        burst_s = find_burst_s(x, fr, max(0.0, on / 1000 - 0.02), 0.15)
        v, pre, _ = vot_ms(x, fr, burst_s, floor, ceiling)
        out["burst_ms"] = round(burst_s * 1000, 1)
        out["vot_ms"] = v
        out["prevoicing_ms"] = pre
    return out
