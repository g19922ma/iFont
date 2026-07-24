"""連続合成(設計提示)の品質処方。

単音・2文字プールで確立した品質管理(実測→処方→焼き込み)の連続合成版。
experiment/tools/build_karuta_samples.py で karuta_5316/ooyama 向けに検証した処方を、
CLI 本体の設計提示(synth_voicevox_designed)へ一般化して移植したもの。

- 強制有声化: 全モーラの母音を小文字化して文脈無声化を防ぐ(「みずくくる」の く が
  無声子音に挟まれて消える等。披講では母音を保つ読みが自然)。適用は audio.py 側。
- F0適合: 合成→モーラF0実測→30セント超の偏差を減衰付き(0.55倍)で逆補正→再合成を
  繰り返す(最大4回)。VOICEVOX の F0 応答はモーラにより非線形(補正がほぼ効かない/
  2倍以上に増幅される が混在)なので、等倍補正だと発振する。減衰を掛けたうえで
  各反復の最大偏差が最小のものを採用する。
- 音量ならし: モーラ中心を節点とする緩いゲイン補正(±8dB、2dB不感帯、60ms平滑)で
  モーラ間の音量ムラをならす。急峻な変化は掛けない。

parselmouth(Praat) が無い環境では F0 適合だけをスキップする(強制有声化と音量ならしは行う)。
numpy も無ければ品質処方全体をスキップして素の合成を返す。
"""
import io
import math
import wave


def have_numpy():
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def have_parselmouth():
    try:
        import parselmouth  # noqa: F401
        return True
    except ImportError:
        return False


def wav_bytes_to_np(b):
    import numpy as np
    with wave.open(io.BytesIO(b), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, sr


def np_to_wav_bytes(x, sr):
    import numpy as np
    buf = io.BytesIO()
    y = np.clip(x, -1, 1)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def analyze_f0(x, sr, windows):
    """各時間窓 [a,b] の有声フレーム数と F0 中央値(無声なら None)。"""
    import numpy as np
    import parselmouth
    snd = parselmouth.Sound(x, sampling_frequency=sr)
    p = snd.to_pitch(time_step=0.005, pitch_floor=140.0, pitch_ceiling=520.0)
    f0 = p.selected_array["frequency"]
    tt = p.xs()
    res = []
    for a, b in windows:
        m = (tt >= a) & (tt <= b) & (f0 > 0)
        res.append(dict(n_voiced=int(m.sum()),
                        f0=(float(np.median(f0[m])) if m.sum() else None)))
    return res


def f0_windows(onsets, durs, cons):
    """モーラごとの F0 計測窓(母音の中身。子音と境界の遷移を避ける)。"""
    wins = []
    for on, d, c in zip(onsets, durs, cons):
        a, b = on + c + 0.02, on + d - 0.03
        if b - a < 0.04:
            a, b = on + c, on + d - 0.01
        if b - a < 0.03:
            a, b = on, on + d
        wins.append([a, b])
    return wins


def pitch_fit(synth, refs_hz, onsets, durs, max_iter=4, tol_cents=30.0, damp=0.55, log=None):
    """合成→モーラF0実測→偏差の減衰付き逆補正→再合成 を繰り返し、最良の反復を採る。

    synth(ln_targets) -> (x, sr, cons)。返り値は (x, sr, 採用反復の最大偏差セント)。"""
    ln = [math.log(f) for f in refs_hz]
    best = None
    for it in range(max_iter):
        x, sr, cons = synth(ln)
        meas = analyze_f0(x, sr, f0_windows(onsets, durs, cons))
        worst = 0.0
        for i, (m, r) in enumerate(zip(meas, refs_hz)):
            if m["f0"] is None or m["n_voiced"] < 4:
                worst = max(worst, 999.0)   # 無声のままのモーラ(要注意)
                continue
            dc = 1200.0 * math.log2(m["f0"] / r)
            if abs(dc) > tol_cents:
                ln[i] += damp * (math.log(r) - math.log(m["f0"]))
            worst = max(worst, abs(dc))
        if log is not None:
            log.append(f"F0適合 反復{it + 1}: 最大偏差 {worst:.0f}セント")
        if best is None or worst < best[0]:
            best = (worst, x, sr)
        if worst <= tol_cents:
            break
    return best[1], best[2], best[0]


def mora_rms_db(x, sr, on, dur):
    import numpy as np
    a, b = int((on + 0.02) * sr), int((on + min(dur, 0.32)) * sr)
    seg = x[a:b]
    return 20 * np.log10(max(np.sqrt(np.mean(seg ** 2)), 1e-9)) if len(seg) else -120.0


def gain_smooth(x, sr, onsets, durs, log=None):
    """モーラRMSの中央値レベルへ、モーラ中心を節点とする緩いゲインでならす。"""
    import numpy as np
    lv = [mora_rms_db(x, sr, on, d) for on, d in zip(onsets, durs)]
    L0 = float(np.median(lv))
    centers, gains = [], []
    for on, d, l in zip(onsets, durs, lv):
        g = L0 - l
        g = 0.0 if abs(g) < 2.0 else float(np.clip(g, -8, 8))
        centers.append(on + min(d, 0.32) / 2)
        gains.append(g)
    t = np.arange(len(x)) / sr
    gdb = np.interp(t, centers, gains, left=gains[0], right=gains[-1])
    k = max(1, int(0.06 * sr))
    gdb = np.convolve(gdb, np.ones(k) / k, mode="same")
    if log is not None:
        log.append(f"音量ならし: モーラRMS範囲 {max(lv) - min(lv):.1f}dB "
                   f"(中央値 {L0:.1f}dBFS) -> 補正 {[round(g, 1) for g in gains]}")
    return x * 10 ** (gdb / 20), L0


def apply(synth, refs_hz, onsets, durs, log=None):
    """設計提示の品質処方(F0適合+音量ならし)を適用した WAV バイト列を返す。

    synth(ln_targets) -> (wavバイト列, 各モーラの子音長リスト)。強制有声化は synth 側で
    済んでいる前提(audio.py の設計クエリが行う)。"""
    if not have_numpy():
        if log is not None:
            log.append("numpy が無いため品質処方をスキップ(素の合成)")
        wav, _ = synth([math.log(f) for f in refs_hz])
        return wav

    def synth_np(ln_targets):
        wav, cons = synth(ln_targets)
        x, sr = wav_bytes_to_np(wav)
        return x, sr, cons

    if have_parselmouth():
        x, sr, worst = pitch_fit(synth_np, refs_hz, onsets, durs, log=log)
        if log is not None:
            log.append(f"F0適合: 採用反復の最大偏差 {worst:.0f}セント")
    else:
        if log is not None:
            log.append("parselmouth が無いため F0 適合をスキップ(強制有声化と音量ならしのみ)")
        x, sr, _cons = synth_np([math.log(f) for f in refs_hz])
    x, _L0 = gain_smooth(x, sr, onsets, durs, log=log)
    import numpy as np
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0.98:
        x *= 0.98 / peak
    return np_to_wav_bytes(x, sr)
