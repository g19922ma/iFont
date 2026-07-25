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


def pitch_fit(synth, refs_hz, onsets, durs, max_iter=4, tol_cents=30.0, damp=0.55, log=None,
              skip=None):
    """合成→モーラF0実測→偏差の減衰付き逆補正→再合成 を繰り返し、最良の反復を採る。

    synth(ln_targets) -> (x, sr, cons)。skip の添字(ー継続モーラなど、後段の PSOLA で
    輪郭を上書きするもの)は採点・補正の対象外。返り値は (x, sr, 採用反復の最大偏差セント)。"""
    skip = set(skip or [])
    ln = [math.log(f) for f in refs_hz]
    best = None
    for it in range(max_iter):
        x, sr, cons = synth(ln)
        meas = analyze_f0(x, sr, f0_windows(onsets, durs, cons))
        worst = 0.0
        for i, (m, r) in enumerate(zip(meas, refs_hz)):
            if i in skip:
                continue
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


def psola_contour(x, sr, t0, t1, points):
    """[t0,t1] の F0 を PSOLA で points(区間相対秒, Hz) の輪郭に置き換えた波形を返す。
    伸ばし・余韻を設計音高に載せ替えるのに使う(接続部は25msクロスフェード)。"""
    import numpy as np
    import parselmouth
    snd = parselmouth.Sound(x, sampling_frequency=sr)
    seg = snd.extract_part(from_time=t0, to_time=t1)
    manip = parselmouth.praat.call(seg, "To Manipulation", 0.01, 100.0, 520.0)
    pt = parselmouth.praat.call("Create PitchTier", "elong", 0.0, t1 - t0)
    for tp, hz in points:
        parselmouth.praat.call(pt, "Add point", tp, hz)
    parselmouth.praat.call([pt, manip], "Replace pitch tier")
    res = parselmouth.praat.call(manip, "Get resynthesis (overlap-add)")
    y = res.values[0]
    a, b = int(t0 * sr), int(t1 * sr)
    m = b - a
    y = np.pad(y, (0, max(0, m - len(y))))[:m]
    out = x.copy()
    nf = int(0.025 * sr)
    w = np.linspace(0, 1, nf)
    out[a:a + nf] = out[a:a + nf] * (1 - w) + y[:nf] * w
    out[a + nf:b] = y[nf:]
    return out


def mora_rms_db(x, sr, on, dur):
    import numpy as np
    a, b = int((on + 0.02) * sr), int((on + min(dur, 0.32)) * sr)
    seg = x[a:b]
    return 20 * np.log10(max(np.sqrt(np.mean(seg ** 2)), 1e-9)) if len(seg) else -120.0


def gain_smooth(x, sr, onsets, durs, log=None, nodes=None):
    """モーラRMSの中央値レベルへ、モーラ中心を節点とする緩いゲインでならす。

    nodes に添字リストを渡すと、そのモーラだけを節点にする(残りは補間)。
    伸ばし・余韻のー継続モーラを節点から外し、自然な減衰をゲインで持ち上げて
    壊さないために使う。"""
    import numpy as np
    idx = list(range(len(onsets))) if nodes is None else list(nodes)
    lv = [mora_rms_db(x, sr, onsets[i], durs[i]) for i in idx]
    L0 = float(np.median(lv))
    centers, gains = [], []
    for i, l in zip(idx, lv):
        g = L0 - l
        g = 0.0 if abs(g) < 2.0 else float(np.clip(g, -8, 8))
        centers.append(onsets[i] + min(durs[i], 0.32) / 2)
        gains.append(g)
    t = np.arange(len(x)) / sr
    gdb = np.interp(t, centers, gains, left=gains[0], right=gains[-1])
    k = max(1, int(0.06 * sr))
    gdb = np.convolve(gdb, np.ones(k) / k, mode="same")
    if log is not None:
        log.append(f"音量ならし: モーラRMS範囲 {max(lv) - min(lv):.1f}dB "
                   f"(中央値 {L0:.1f}dBFS) -> 補正 {[round(g, 1) for g in gains]}")
    return x * 10 ** (gdb / 20), L0


def apply(synth, refs_hz, onsets, durs, log=None, gain_nodes=None, skip_fit=None,
          elongations=None):
    """設計提示の品質処方(F0適合+PSOLA伸ばし整形+音量ならし)を適用した WAV バイト列を返す。

    synth(ln_targets) -> (wavバイト列, 各モーラの子音長リスト)。強制有声化は synth 側で
    済んでいる前提(audio.py の設計クエリが行う)。gain_nodes は音量ならしの節点にする
    モーラの添字(省略時は全モーラ)。skip_fit は F0 適合から外すモーラの添字。
    elongations は (t0, t1, 開始Hz, 終端Hz, 減衰dB) のリストで、その区間の F0 を PSOLA で
    設計輪郭に載せ替え、減衰dB > 0 なら区間の終端へ向けて緩やかに音量を落とす(余韻)。"""
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
        x, sr, worst = pitch_fit(synth_np, refs_hz, onsets, durs, log=log, skip=skip_fit)
        if log is not None:
            log.append(f"F0適合: 採用反復の最大偏差 {worst:.0f}セント")
        import numpy as np
        for (t0, t1, hz0, hz1, decay_db) in (elongations or []):
            x = psola_contour(x, sr, t0, t1, [[0.0, hz0], [t1 - t0, hz1]])
            if decay_db > 0:                      # 余韻: 終端へ-decay_dBの対数線形減衰
                a, b = int(t0 * sr), int(t1 * sr)
                g = -decay_db * np.arange(b - a) / max(1, b - a - 1)
                x[a:b] *= 10 ** (g / 20)
        if elongations and log is not None:
            log.append(f"伸ばし整形: {len(elongations)}区間を PSOLA で設計音高へ載せ替え")
    else:
        if log is not None:
            log.append("parselmouth が無いため F0 適合をスキップ(強制有声化と音量ならしのみ)")
        x, sr, _cons = synth_np([math.log(f) for f in refs_hz])
    x, _L0 = gain_smooth(x, sr, onsets, durs, log=log, nodes=gain_nodes)
    import numpy as np
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0.98:
        x *= 0.98 / peak
    return np_to_wav_bytes(x, sr)
