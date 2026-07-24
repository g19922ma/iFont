"""音声の生成。

既定は自己完結のトーン合成（音階=pitch のサイン波を1文字ずつ）。
--engine voicevox を指定し、ローカルに VOICEVOX エンジンが起動していれば、
合成音声(TTS)を用いる（任意・要エンジン）。
"""
import math
import struct
import wave
import urllib.request
import urllib.parse
import json

_NOTE = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
         "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
         "A#": 10, "BB": 10, "B": 11}


def note_to_hz(pitch: str) -> float:
    """音階名(例 'E4','B3','A#4')または数値(Hz)を周波数[Hz]に変換する。"""
    s = str(pitch).strip()
    try:
        return float(s)  # 数値ならそのまま Hz とみなす
    except ValueError:
        pass
    s = s.upper()
    # 末尾の数字(と符号)をオクターブとして切り出し、残りを音名(A, C#, BB=B♭ など)とする
    j = len(s)
    while j > 0 and (s[j - 1].isdigit() or s[j - 1] == "-"):
        j -= 1
    name, octave = s[:j], s[j:]
    if name not in _NOTE or octave == "":
        raise ValueError(f"音階が解釈できない: {pitch}")
    midi = 12 * (int(octave) + 1) + _NOTE[name]
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def build_pitch_list(pitch_arg, n_chars: int, rise: bool = False):
    """--pitch 引数から、1文字ごとの周波数[Hz]リストを作る。

    音高を1音ごとに自由設計できる。文脈のない単音の識別は基本周波数(F0)の広い変動に
    頑健であり(話者正規化)、一定音高で測った対応づけ g は音高を変えた実用提示にもそのまま生きる。
    そこで実験は一定音高(単一指定)で、実用(競技かるた等)は旋律(カンマ区切り)で、と使い分けられる。

    - 単一指定(例 'E4' や '330') は全文字に適用。--rise のときのみ1文字目を完全4度下(かるた風)にする。
    - カンマ区切り(例 'B3,E4,G4,E4,C4') は1音ごとに指定。足りなければ最後の音を繰り返し、多ければ切り詰める。
    """
    parts = [p.strip() for p in str(pitch_arg).split(",") if p.strip()]
    freqs = [note_to_hz(p) for p in parts]
    if len(freqs) <= 1:
        base = freqs[0] if freqs else note_to_hz("E4")
        if rise:
            return [base * 2 ** (-5 / 12.0) if i == 0 else base for i in range(n_chars)]
        return [base] * n_chars
    if len(freqs) < n_chars:
        freqs = freqs + [freqs[-1]] * (n_chars - len(freqs))
    return freqs[:n_chars]


def synth_tones(pitches_hz, char_dur: float, sr: int = 44100):
    """1文字ごとの周波数リスト pitches_hz を、1音ずつトーンにして並べた音を作る（float リスト）。"""
    samples = []
    for f in pitches_hz:
        m = int(char_dur * sr)
        for k in range(m):
            t = k / sr
            # 立ち上がり・減衰の窓（クリック音を避ける）
            env = max(0.0, min(1.0, t / 0.02, (char_dur - t) / 0.04))
            samples.append(0.5 * env * math.sin(2 * math.pi * f * t))
    return samples, sr


def _hira_to_kata(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def _vv_query(text: str, speaker: int, host: str):
    # VOICEVOX の /audio_query は POST(パラメータはクエリ文字列、本体は空)
    q = urllib.parse.urlencode({"text": _hira_to_kata(text), "speaker": speaker})
    req = urllib.request.Request(f"{host}/audio_query?{q}", data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def _vv_synth(query, speaker: int, host: str):
    data = json.dumps(query).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/synthesis?speaker={speaker}", data=data,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()  # WAV バイト列


def _wav_seconds(wav_bytes: bytes) -> float:
    import io
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / w.getframerate()


def _set_mora(m, pitch_ln, dur):
    """1モーラの音高(対数F0)と長さ(秒)を固定する。子音は最大 dur-0.04 まで、残りを母音に充てる。"""
    m = dict(m)
    c = m.get("consonant_length") or 0.0
    if c > dur - 0.04:
        c = dur - 0.04
        m["consonant_length"] = c
    m["vowel_length"] = dur - c
    m["pitch"] = pitch_ln
    return m


def synth_voicevox(text: str, speaker: int = 2, host: str = "http://127.0.0.1:50021",
                   speed: float = 1.0, sr: int = 44100):
    """VOICEVOX エンジン(ローカル)で TTS 合成する。エンジン未起動なら例外。"""
    query = _vv_query(text, speaker, host)
    query["speedScale"] = speed
    query["outputSamplingRate"] = sr
    return _vv_synth(query, speaker, host)


def _flatten_moras(query):
    """audio_query の全アクセント句のモーラを1列に平坦化して返す(pause は無視)。"""
    ms = []
    for ap in query["accent_phrases"]:
        ms.extend(ap["moras"])
    return ms


def synth_voicevox_designed(reading: str, pitches_hz, char_dur, speaker: int = 108,
                            host: str = "http://127.0.0.1:50021", sr: int = 44100,
                            durations=None, quality: bool = True, quality_log=None):
    """実声で「設計提示」を合成する。各モーラの音高を pitches_hz(モーラごとの周波数)で与え、
    長さを固定する。char_dur は全モーラ一律の秒数。durations(モーラごとの秒数リスト)を渡すと、
    そちらを優先して1モーラずつ長さを変えられる(競技かるたの伸ばし・余韻など)。
    競技かるたの読み(句頭B3・他E4・0.2秒)や実験の一定音高/旋律を実声で作る経路。

    quality=True(既定)で品質処方を適用する(quality.py 参照):
    強制有声化(文脈無声化の防止)・F0適合(実測→減衰付き逆補正)・音量ならし。
    quality_log にリストを渡すと処方の経過を追記する。
    返り値は (wavバイト列, 各モーラの開始秒[list], 総秒)。"""
    import math
    q = _vv_query(reading, speaker, host)
    moras = _flatten_moras(q)
    n = len(moras)

    def dur_at(i):
        if durations is not None:
            return float(durations[min(i, len(durations) - 1)])
        return float(char_dur)

    durs = [dur_at(i) for i in range(n)]
    refs = [float(pitches_hz[min(i, len(pitches_hz) - 1)]) for i in range(n)]
    pre = 0.05
    onsets, t = [], pre
    for d in durs:
        onsets.append(t)
        t += d

    def _synth(ln_targets, force_voiced):
        out = []
        for i, m in enumerate(moras):
            vm = dict(m)
            if force_voiced and vm.get("vowel"):
                vm["vowel"] = vm["vowel"].lower()   # 文脈無声化の防止(強制有声)
            out.append(_set_mora(vm, ln_targets[i], durs[i]))
        q2 = dict(q)
        q2["accent_phrases"] = [{"moras": out, "accent": 1, "pause_mora": None,
                                 "is_interrogative": False}]
        q2.update(dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0, volumeScale=1.0,
                       prePhonemeLength=pre, postPhonemeLength=0.15, outputSamplingRate=sr))
        cons = [(m.get("consonant_length") or 0.0) for m in out]
        return _vv_synth(q2, speaker, host), cons

    ln = [math.log(f) for f in refs]
    if not quality:
        wav, _ = _synth(ln, False)
        return wav, onsets, _wav_seconds(wav)
    from . import quality as _quality
    wav = _quality.apply(lambda l: _synth(l, True), refs, onsets, durs, log=quality_log)
    return wav, onsets, _wav_seconds(wav)


def insert_pauses(wav_bytes, pauses):
    """WAV の指定時刻に無音を挿入する(競技かるたの間合いなど)。
    pauses: (時刻秒, 長さ秒) のリスト(時刻は元の音声の時間軸)。
    返り値は (新しいwavバイト列, 追加した合計秒)。"""
    import io
    import numpy as np
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    parts, prev = [], 0
    for t, d in sorted(pauses):
        s = max(prev, int(round(t * fr)))
        parts.append(x[prev:s])
        parts.append(np.zeros(int(round(d * fr)), dtype="<i2"))
        prev = s
    parts.append(x[prev:])
    y = np.concatenate(parts) if parts else x
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes(y.tobytes())
    return buf.getvalue(), sum(d for _, d in pauses)


def synth_voicevox_natural(reading: str, speaker: int = 108,
                           host: str = "http://127.0.0.1:50021", sr: int = 44100):
    """実声で「自然韻律」を合成する(現代文向け)。音高・長さは VOICEVOX の既定のまま。
    返り値は (wavバイト列, 各モーラの開始秒[list], 総秒)。表示の同期に各モーラ開始時刻を使う。"""
    q = _vv_query(reading, speaker, host)
    q.update(dict(prePhonemeLength=0.05, postPhonemeLength=0.15, outputSamplingRate=sr))
    wav = _vv_synth(q, speaker, host)
    onsets = []
    t = q["prePhonemeLength"]
    for ap in q["accent_phrases"]:
        for m in ap["moras"]:
            onsets.append(t)
            t += (m.get("consonant_length") or 0) + (m.get("vowel_length") or 0)
        if ap.get("pause_mora"):
            t += (ap["pause_mora"].get("vowel_length") or 0)
    return wav, onsets, _wav_seconds(wav)


def write_wav(samples, sr: int, path: str):
    """float(-1..1) のリストを16bit PCM WAV で書き出す。"""
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples)
        w.writeframes(frames)


def pad_wav_to(path: str, target_seconds: float):
    """WAV を target_seconds まで末尾に無音を足して延長する（映像長にそろえる）。"""
    with wave.open(path, "rb") as w:
        params = w.getparams()
        data = w.readframes(w.getnframes())
        sr = w.getframerate()
        nch = w.getnchannels()
        sw = w.getsampwidth()
    have = len(data) // (sw * nch)
    need = int(target_seconds * sr)
    if need > have:
        data += b"\x00" * ((need - have) * sw * nch)
        with wave.open(path, "wb") as w:
            w.setparams(params)
            w.writeframes(data)
