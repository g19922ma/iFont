"""iFont: テキスト・音階・速度から、字幕と音声再生が同期した動画を出力する CLI。

例:
    # 実験用: 一定音高(モノトーン)
    ifont-render --text "ちはやふる" --pitch E4 --speed 5 --out out.mp4
    # 実用: 1文字ごとに音高を設計(旋律)
    ifont-render --text "ちはやふる" --pitch "B3,E4,G4,E4,C4" --speed 4 --out out.mp4

字幕は、各文字の音が流れる区間の中で、文字単位の視聴覚対応 g（gmodel）に従って
fade で立ち上がる。音声は既定でトーン合成（音階=pitch）、--engine voicevox で TTS。
音高は1文字ごとに自由設計できる（--pitch にカンマ区切り）。単音の識別は基本周波数の
広い変動に頑健なため、一定音高で測った g は音高を変えた実用提示にもそのまま生きる。
"""
import argparse
import os
import tempfile

from . import audio, render, video
from .credits import CREDITS

DEFAULT_FONT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "fonts", "BIZUDGothic-Regular.ttf"))


def _tokens_for(text_chars, reading):
    """表示字の並びに対する「読み(音)」トークン列を作る。
    reading 未指定なら各字がそのまま自分を読む。指定時はカンマ区切りで表示字数と一致させ、
    空トークン(例 末尾の ？)は無音として扱う(表示はするが音は出ない)。"""
    if reading is None:
        return list(text_chars)
    toks = [t.strip() for t in str(reading).split(",")]
    if len(toks) != len(text_chars):
        raise ValueError(f"--reading のトークン数({len(toks)})が表示字数({len(text_chars)})と一致しません。")
    return toks


def build(text, reading=None, pitch="E4", speed=5.0, out="out.mp4", engine="tones",
          rise=False, natural=False, speaker=2, fps=30, font=None, hint_font=None,
          label=None, durations=None, pause_after=None, keep_frames=False,
          raw_voice=False):
    """動画を生成して out のパスを返す。

    表示は「時間ゲート提示」(固定領域に1文字ずつ、その音の区間で鮮明化)。
    engine=voicevox で実声。natural=True は自然韻律(現代文向け)、False は設計提示
    (各モーラの音高=pitch・長さ=1/speed 秒に固定。競技かるたの句頭B3・他E4 などに使う)。
    reading で表示字と読み(音)を分けられる(は→ワ 等)。
    durations で1モーラずつ長さを変えられる(競技かるたの伸ばし・余韻。音のあるモーラ数と同数)。
    pause_after で指定モーラの直後に無音を挟める(競技かるたの間合い。(表示字index, 秒) のリスト)。
    """
    disp_chars = [c for c in text if not c.isspace()]
    if not disp_chars:
        raise ValueError("text が空です。")
    tokens = _tokens_for(disp_chars, reading)
    sound_pos = [i for i, tk in enumerate(tokens) if tk]
    if not sound_pos:
        raise ValueError("読み(音)のあるトークンがありません。")
    reading_text = "".join(tokens)
    n_sound = len(sound_pos)

    font = font or DEFAULT_FONT
    if not os.path.exists(font):
        raise FileNotFoundError(f"フォントが見つからない: {font}")
    char_dur = 1.0 / float(speed)
    if durations is not None and len(durations) != n_sound:
        raise ValueError(f"--durations の数({len(durations)})が音のあるモーラ数({n_sound})と一致しません。")
    durs_eff = [float(durations[j]) if durations is not None else char_dur for j in range(n_sound)]
    pitches_hz = audio.build_pitch_list(pitch, n_sound, rise=rise)   # 音のあるモーラごとの音高

    work = tempfile.mkdtemp(prefix="ifont_")
    frames_dir = os.path.join(work, "frames")
    wav_path = os.path.join(work, "audio.wav")

    # --- 音声と、音のある各モーラの開始秒 onsets ---
    used_engine = engine
    onsets = total = wav_bytes = None
    if engine == "voicevox":
        try:
            if natural:
                wav_bytes, onsets, total = audio.synth_voicevox_natural(reading_text, speaker=speaker)
                used_engine = "voicevox(自然韻律)"
            else:
                qlog = []
                wav_bytes, onsets, total = audio.synth_voicevox_designed(
                    reading_text, pitches_hz, char_dur, speaker=speaker,
                    durations=(durs_eff if durations is not None else None),
                    quality=not raw_voice, quality_log=qlog)
                for line in qlog:
                    print(f"[quality] {line}")
                used_engine = "voicevox(設計提示)" if raw_voice else "voicevox(設計提示+品質処方)"
            if len(onsets) != n_sound:
                print(f"[warn] 合成モーラ数({len(onsets)})が読み数({n_sound})と不一致。表示同期がずれる可能性。")
        except Exception as e:
            print(f"[warn] VOICEVOX を使えませんでした({e})。トーン合成に切り替えます。")
            used_engine = "tones"
    if used_engine == "tones":
        samples, sr = audio.synth_tones(pitches_hz, char_dur)
        audio.write_wav(samples, sr, wav_path)
        with open(wav_path, "rb") as f:
            wav_bytes = f.read()
        onsets = [i * char_dur for i in range(n_sound)]
        total = n_sound * char_dur

    # --- 間合い(無音)の挿入。指定モーラの直後に無音を挟み、以降の時間軸をずらす ---
    pos_of = {sound_pos[j]: j for j in range(n_sound)}
    pauses = []                                   # (挿入時刻[元の時間軸], 秒)
    for k, sec in (pause_after or []):
        if k not in pos_of:
            raise ValueError(f"--pause-after の位置 {k} は音のあるモーラではありません。")
        j = pos_of[k]
        pauses.append((onsets[j] + durs_eff[j], float(sec)))
    if pauses:
        wav_bytes, _added = audio.insert_pauses(wav_bytes, pauses)

    def shift(t):                                 # 元の時刻 → 無音挿入後の時刻
        return t + sum(sec for (ti, sec) in pauses if ti <= t + 1e-6)
    onsets = [shift(o) for o in onsets]
    total = shift(total)
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)

    # --- 表示字ごとの提示区間。start=モーラ開始、dur=そのモーラの長さ、reveal=鮮明化にかける時間 ---
    starts = [None] * len(disp_chars)
    dur_by = {}
    for j, i in enumerate(sound_pos):
        starts[i] = onsets[j]
        dur_by[i] = durs_eff[j]
    for i in range(len(disp_chars) - 1, -1, -1):     # 無音の表示字は次の字の開始(なければ総尺)に置く
        if starts[i] is None:
            starts[i] = starts[i + 1] if (i + 1 < len(disp_chars) and starts[i + 1] is not None) else total
    segments = []
    for i, ch in enumerate(disp_chars):
        d = dur_by.get(i)
        if d is None:
            nxt = starts[i + 1] if i + 1 < len(disp_chars) else total
            d = max(nxt - starts[i], 0.3)
        segments.append({"char": ch, "start": starts[i], "dur": d,
                         "reveal": min(d, 0.5), "sound": tokens[i] or None})
    # 間合いは空白セグメント(無音・ブランク表示)として重ねる
    for (ti, sec) in pauses:
        blank_start = ti + sum(s2 for (t2, s2) in pauses if t2 < ti - 1e-6)
        segments.append({"char": "", "start": blank_start, "dur": sec, "reveal": sec, "sound": None})
    segments.sort(key=lambda s: s["start"])

    # --- 字幕フレーム(時間ゲート提示) ---
    frames, dur = render.render_frames_gated(
        segments, frames_dir, font, fps=fps, label=label, font_hint_path=hint_font)

    audio.pad_wav_to(wav_path, dur)       # 音声を映像長にそろえる(末尾の静止を残す)
    out = os.path.abspath(out)
    video.mux(frames_dir, wav_path, out, fps=fps)

    if not keep_frames:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return out, used_engine, dur


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ifont-render", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", required=True, help="画面に表示する字(かな漢字。表記どおり)")
    ap.add_argument("--reading", default=None,
                    help="読み(音)。表示字とカンマ区切りで1対1に対応させる(例 'ち,は,や,...')。"
                         "空トークンは無音(例 末尾の ？)。は→ワ のように表示と音を分けるときに使う。"
                         "未指定なら各字がそのまま自分を読む")
    ap.add_argument("--pitch", default="E4",
                    help="音階名(例 E4, B3, A#4)または周波数[Hz]。カンマ区切りで1モーラごとに指定可"
                         "(例 'B3,E4,G4,E4,C4')。1つだけなら全モーラに適用。設計提示(既定)で有効")
    ap.add_argument("--speed", type=float, default=5.0, help="1秒あたりの文字数（既定5=0.2秒/文字）")
    ap.add_argument("--out", default="out.mp4", help="出力mp4のパス")
    ap.add_argument("--engine", choices=["tones", "voicevox"], default="tones",
                    help="音声エンジン。tones=自己完結のトーン合成 / voicevox=ローカル実声TTS(要エンジン)")
    ap.add_argument("--speaker", type=int, default=2,
                    help="VOICEVOX の話者ID(実声のとき。既定2=四国めたん。東北きりたん=108)")
    ap.add_argument("--natural", action="store_true",
                    help="実声を自然韻律で読む(現代文向け)。既定は設計提示(音高=pitch・長さ=1/speed に固定)")
    ap.add_argument("--rise", action="store_true",
                    help="競技かるた風に1→2文字目で音高を上げる(完全4度)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--font", default=None, help="表示字の TrueType フォント(既定 BIZ UDGothic)")
    ap.add_argument("--hint-font", default=None, help="読みの添え字(→ワ 等)のフォント(既定は本文と同じ)")
    ap.add_argument("--label", default=None, help="画面左上に出す小さな見出し(任意)")
    ap.add_argument("--durations", default=None,
                    help="1モーラごとの長さ[秒]をカンマ区切りで指定(音のあるモーラ数と同数)。"
                         "競技かるたの伸ばし・余韻に使う。省略時は 1/speed 秒で一律")
    ap.add_argument("--pause-after", default=None,
                    help="指定モーラの直後に無音(間合い)を挟む。'表示字index:秒' をカンマ区切り"
                         "(例 '13:1.0')。競技かるたの間合いに使う")
    ap.add_argument("--raw-voice", action="store_true",
                    help="実声の品質処方(強制有声化・F0適合・音量ならし)を切って素の設計合成にする")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args(argv)

    durations = None
    if args.durations:
        durations = [float(x) for x in args.durations.split(",") if x.strip()]
    pause_after = None
    if args.pause_after:
        pause_after = [(int(p.split(":")[0]), float(p.split(":")[1]))
                       for p in args.pause_after.split(",") if p.strip()]

    out, used_engine, dur = build(
        args.text, reading=args.reading, pitch=args.pitch, speed=args.speed, out=args.out,
        engine=args.engine, rise=args.rise, natural=args.natural, speaker=args.speaker,
        fps=args.fps, font=args.font, hint_font=args.hint_font, label=args.label,
        durations=durations, pause_after=pause_after, keep_frames=args.keep_frames,
        raw_voice=args.raw_voice)
    print(f"出力: {out}  ({dur:.1f}s, 音声={used_engine})")
    print(CREDITS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
