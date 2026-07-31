"""Perceptual Score デモ: 手描きの理解度カーブから音声と動的文字(iFont)を両方生成する。

入力: スコアJSON(文字ごとの [時刻, 目標識別可能性] の点列)
出力: 音声+iFont字幕+スコアの進行カーソルを1画面にした mp4

較正はプレースホルダ(ロジスティック仮曲線)。実験の実データが取れたら差し替える。
- 視覚: 不透明度a→認識率 p_v(a)。目標ι(t)を逆写像して不透明度の時間変化にする
- 聴覚: 有音内容の到達割合f→認識率 p_a(f)。目標ι(t)を逆写像した f(t) になるよう、
  設計合成(今週の伸ばし処方つき)で目標区間の長さの音を作り、PSOLAで微調整ワープする
"""
import json
import math
import os
import shutil
import subprocess
import sys
import wave

import numpy as np
import parselmouth
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "/Users/maruyama/Documents/GitHub/iFont/ifont_tool")
from ifont import audio as ifa

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/maruyama/Documents/GitHub/iFont"
FONT_MAIN = os.path.join(REPO, "fonts", "BIZUDMincho-Regular.ttf")
FONT_SUB = os.path.join(REPO, "fonts", "BIZUDGothic-Regular.ttf")
SR = 44100
FPS = 30
W, H = 1280, 720
B3 = 246.94

# ---------------- 較正のプレースホルダ(実データで差し替え) ----------------
FLOOR, PLAT = 0.02, 0.95

def sigma(x):
    return 1.0 / (1.0 + math.exp(-x))

def p_visual(a):        # 不透明度 a(0..1) -> 認識率
    return FLOOR + (PLAT - FLOOR) * sigma((a - 0.45) / 0.12)

def p_audio(f):         # 有音内容の到達割合 f(0..1) -> 認識率
    return FLOOR + (PLAT - FLOOR) * sigma((f - 0.50) / 0.15)

def inv(pfun, target, lo=0.0, hi=1.0):
    t = min(max(target, FLOOR + 1e-4), PLAT - 1e-4)
    a, b = lo, hi
    for _ in range(40):
        m = (a + b) / 2
        if pfun(m) < t:
            a = m
        else:
            b = m
    return (a + b) / 2

# ---------------- スコアの読み込み ----------------
def load_score(path):
    sc = json.load(open(path))
    T = float(sc["duration"])
    chars = []
    for c in sc["chars"]:
        pts = sorted([(float(t), float(v)) for t, v in c["points"]])
        chars.append(dict(char=c["char"], pts=pts))
    return T, chars

def iota_of(pts, t):
    """点列の折れ線補間(範囲外は端の値)。"""
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            if t1 - t0 < 1e-9:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]

# ---------------- 音声側 ----------------
def synth_char_audio(ch, pts, T):
    """文字 ch の目標カーブから音声(全長Tのトラック)を作る。"""
    grid = np.arange(0, T, 0.01)
    iota = np.array([iota_of(pts, t) for t in grid])
    f = np.array([0.0 if v <= FLOOR + 1e-3 else inv(p_audio, v) for v in iota])
    f = np.maximum.accumulate(f)            # 到達割合は単調非減少
    active = f > 1e-4
    if not active.any():
        return np.zeros(int(T * SR))
    i0, i1 = np.argmax(active), len(f) - np.argmax(active[::-1]) - 1
    t0, t1 = grid[i0], grid[i1]
    span = max(t1 - t0, 0.25)
    # 目標区間の長さの音を設計合成(伸ばし処方が持続を保証する)
    kata = ifa._hira_to_kata(ch)
    qlog = []
    wav, onsets, total = ifa.synth_voicevox_designed(
        kata, [B3], span, speaker=108, durations=[span],
        quality=True, quality_log=qlog)
    x, sr = _wav_np(wav)
    # 有音範囲(素朴なRMSしきい値)
    env_t, env = _envelope(x, sr)
    on = env > env.max() - 35
    s0 = env_t[np.argmax(on)]
    s1 = env_t[len(on) - np.argmax(on[::-1]) - 1]
    voiced = x[int(s0 * sr):int(s1 * sr)]
    L = len(voiced) / sr
    # PSOLAワープ: 出力時刻tで内容到達割合がf(t)になるよう、区間ごとの速度を変える
    # 出力側グリッド(50ms)で必要な source 位置 s(t)=f(t)*L を求め、区間ごとの
    # duration factor = Δt/Δs を DurationTier に置く
    ts = np.arange(t0, t1 + 1e-9, 0.05)
    fs = np.array([f[min(len(f) - 1, int(round(t / 0.01)))] for t in ts])
    ss = fs * L
    snd = parselmouth.Sound(voiced, sampling_frequency=sr)
    manip = parselmouth.praat.call(snd, "To Manipulation", 0.01, 100.0, 520.0)
    dt = parselmouth.praat.call("Create DurationTier", "w", 0.0, L)
    for k in range(len(ts) - 1):
        ds = max(ss[k + 1] - ss[k], 1e-4)
        rate = np.clip((ts[k + 1] - ts[k]) / ds, 0.35, 3.0)
        mid = (ss[k] + ss[k + 1]) / 2
        parselmouth.praat.call(dt, "Add point", float(mid), float(rate))
    parselmouth.praat.call([dt, manip], "Replace duration tier")
    res = parselmouth.praat.call(manip, "Get resynthesis (overlap-add)")
    y = res.values[0]
    need = int((t1 - t0) * sr)
    y = np.pad(y, (0, max(0, need - len(y))))[:need]
    nf = int(0.02 * sr)
    if len(y) > 2 * nf:
        y[:nf] *= np.linspace(0, 1, nf)
        y[-nf:] *= np.linspace(1, 0, nf)
    out = np.zeros(int(T * SR))
    a = int(t0 * SR)
    seg = y if sr == SR else _resample(y, sr, SR)
    out[a:a + len(seg)] += seg[:max(0, len(out) - a)]
    return out

def _wav_np(b):
    import io
    with wave.open(io.BytesIO(b), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, sr

def _resample(x, sr0, sr1):
    n = int(len(x) * sr1 / sr0)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)

def _envelope(x, sr, hop=0.005, win=0.02):
    h, wl = int(hop * sr), int(win * sr)
    n = max(1, (len(x) - wl) // h)
    t = np.arange(n) * hop + win / 2
    e = np.array([20 * np.log10(max(np.sqrt(np.mean(x[i * h:i * h + wl] ** 2)), 1e-9))
                  for i in range(n)])
    return t, e

# ---------------- 視覚側 + カーブ表示 ----------------
CURVE_COLORS = [(42, 120, 214), (235, 104, 52), (27, 175, 122), (150, 80, 200)]

def render_frames(T, chars, frames_dir):
    os.makedirs(frames_dir, exist_ok=True)
    font_big = ImageFont.truetype(FONT_MAIN, 300)
    font_small = ImageFont.truetype(FONT_SUB, 22)
    n = len(chars)
    plot_h = 240
    # カーブ下地(1回だけ描く)
    plot = Image.new("RGB", (W, plot_h), (250, 250, 248))
    pd = ImageDraw.Draw(plot)
    m_l, m_r, m_t, m_b = 70, 30, 26, 34
    pw, ph = W - m_l - m_r, plot_h - m_t - m_b
    for gy in [0, 0.5, 1.0]:
        y = m_t + ph * (1 - gy)
        pd.line([(m_l, y), (W - m_r, y)], fill=(225, 224, 217), width=1)
        pd.text((m_l - 40, y - 9), f"{gy:.0%}", fill=(110, 110, 106), font=font_small)
    for i, c in enumerate(chars):
        col = CURVE_COLORS[i % len(CURVE_COLORS)]
        prev = None
        for t in np.arange(0, T + 1e-9, 0.02):
            v = iota_of(c["pts"], t)
            xy = (m_l + pw * t / T, m_t + ph * (1 - v))
            if prev:
                pd.line([prev, xy], fill=col, width=3)
            prev = xy
        pd.text((m_l + 8 + i * 150, m_t + 2), c["char"], fill=col, font=font_small)
    pd.text((W - 470, plot_h - 26), "あなたが描いた目標カーブ(Perceptual Score)",
            fill=(110, 110, 106), font=font_small)

    n_frames = int(T * FPS) + 1
    for k in range(n_frames):
        t = k / FPS
        img = Image.new("RGB", (W, H), (18, 18, 20))
        dr = ImageDraw.Draw(img)
        cell = W // n
        for i, c in enumerate(chars):
            iota = iota_of(c["pts"], t)
            a = 0.0 if iota <= FLOOR + 1e-3 else inv(p_visual, iota)
            g = int(240 * a)
            bbox = dr.textbbox((0, 0), c["char"], font=font_big)
            cw, chh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = cell * i + (cell - cw) // 2 - bbox[0]
            y = (H - plot_h - chh) // 2 - bbox[1]
            dr.text((x, y), c["char"], fill=(g, g, g), font=font_big)
        strip = plot.copy()
        sd = ImageDraw.Draw(strip)
        cx = m_l + pw * min(t / T, 1.0)
        sd.line([(cx, m_t - 6), (cx, m_t + ph + 6)], fill=(200, 60, 60), width=3)
        img.paste(strip, (0, H - plot_h))
        dr.text((20, 16), "Perceptual Score デモ: 同じスコアから音声と動的文字(iFont)を生成(較正は仮)",
                fill=(150, 150, 150), font=font_small)
        img.save(os.path.join(frames_dir, f"f{k:05d}.png"))
    return n_frames

# ---------------- 本体 ----------------
def main(score_path, out_mp4):
    T, chars = load_score(score_path)
    work = os.path.join(HERE, "pscore_work")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    mix = np.zeros(int(T * SR))
    for c in chars:
        print(f"音声合成+ワープ: {c['char']}")
        mix += synth_char_audio(c["char"], c["pts"], T)
    peak = np.max(np.abs(mix))
    if peak > 0.95:
        mix *= 0.95 / peak
    wav_path = os.path.join(work, "audio.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    print("フレーム描画")
    frames_dir = os.path.join(work, "frames")
    render_frames(T, chars, frames_dir)
    print("mux")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-framerate", str(FPS), "-i", os.path.join(frames_dir, "f%05d.png"),
                    "-i", wav_path, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", out_mp4], check=True)
    print("出力:", out_mp4)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
