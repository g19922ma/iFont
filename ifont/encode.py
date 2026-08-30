#!/usr/bin/env python3
# =========================================================================
# ifont: 音と表示が同期した動画のエンコーダー（コマンドラインツール）
#
#   文字列を入れると、
#     音声   … 較正実験と同じ切り出し音（あみたろ・第1モーラ）を字の順に並べたもの
#     映像   … 各字の音が始まる時刻に、その字の転写アニメーション
#              （その音声の識別の進み方に対応した進み具合）が始まる字幕行
#   を1本の mp4 に書き出す。
#
#   使い方:
#     python3 -m ifont.encode "いぬもあるけば" --family blur --out out.mp4
#     python3 -m ifont.encode "ちはやぶる…" --kimariji ちは \
#         --curve kimariji_curve.csv --out karuta.mp4
#
#   かるたモード（--kimariji/--curve）:
#     決まり字の部分だけ、与えた理解度カーブ（time_ms,value 列の CSV。
#     value は 0..1 の識別の進み具合）に対応させて転写する。
#     それ以外の字は、音声に合わせた一定の時刻に等速で出す。
# =========================================================================
import argparse
import csv
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image

from .curves import load_curves, transfer_series, Curve
from .renderers import draw, glyph, SIZE

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AUDIO_DIR = os.path.join(ROOT, "experiment", "transfer_stimuli_amitaro")

FPS = 60
FRAME_MS = 1000.0 / FPS


def normalize_text(text):
    """入力をエンコード可能な形に整える。

    - カタカナはひらがなに写す（音は同じなので同じクリップ・曲線を使う）
    - 空白・読点は「無音の1拍」に写す（字を出さず、時間だけ進める）
    - 対応できない字（漢字、を・ぢ・づ・ゔ など音声クリップの無い字）は
      黙って飛ばさず、まとめて挙げて断る
    返り値: [(ch or None, kind)] のリスト。None は無音の拍。
    """
    # 漢字まじりの入力は、まず読み（ひらがな）に開く。表示できる字形が
    # かなしか無いため、字幕もひらがなで出す。
    try:
        import pykakasi
        text = "".join(r["hira"] for r in pykakasi.kakasi().convert(text))
    except ImportError:
        pass          # 変換器が無ければ、かな以外は下の検査で字を挙げて断る
    out, bad = [], []
    for ch in text:
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:                    # カタカナ → ひらがな
            ch = chr(o - 0x60)
        if ch in "　 、。，．,. ":
            out.append((None, "rest"))
            continue
        if os.path.exists(clip_path(ch)):
            out.append((ch, "char"))
        else:
            bad.append(ch)
    if bad:
        raise SystemExit(
            "この字は音声クリップが無いので出せません: " + " ".join(sorted(set(bad)))
            + "\n（音声は64かな。を・ぢ・づ・ゔ は元の刺激に無い）")
    return out


def clip_path(ch):
    return os.path.join(AUDIO_DIR, f"{ch}_full.wav")


def clip_ms(ch):
    with wave.open(clip_path(ch), "rb") as w:
        return w.getnframes() * 1000.0 / w.getframerate()


def load_kimariji_curve(path):
    xs, ys = [], []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        xs.append(float(r["time_ms"]))
        ys.append(float(r["value"]))
    return Curve(xs, ys)


def build_timeline(text, family, audio, visual, fb_a, fb_v,
                   slot_ms=0.0, kimariji="", kcurve=None, first_only=False,
                   onsets=None):
    """[{ch, start_ms, series(0..1 per frame), tier}] と全体の音声リストを返す。

    転写する字の選び方（用途に合わせて3通り）:
      既定        … 全文字を転写する（ドラマの字幕のように、全部が重要な場合）
      first_only  … 1音目だけ転写し、残りは読まれた時刻に一括で出す
                    （いろはかるた。勝負は1音目だけ）
      kimariji    … 決まり字だけを与えたカーブで転写し、残りは読まれた時刻に
                    一括で出す（競技かるた。重要なのは決まり字のタイミングだけ）
    """
    # ---- 外部音声モード（競技かるた）----------------------------------------
    # 決まり字の理解度カーブは**その読手の実際の音声**に対して測られたもの。
    # 合成クリップを鳴らすのは筋違いなので、音声はファイルで受け取り、
    # 各字の表示開始時刻（onsets, ms）だけをこちらで使う。
    if onsets is not None:
        chars = [c for c, k in normalize_text(text) if k == "char"]
        if len(onsets) != len(chars):
            raise SystemExit(f"onsets の数({len(onsets)})が字数({len(chars)})と合いません")
        items = []
        for ch, t0 in zip(chars, onsets):
            if kimariji and ch in kimariji and kcurve is not None:
                cv, _ = visual.get((family, ch), (fb_v.get(family), "fallback"))
                n = int(math.ceil(kcurve.x_end / FRAME_MS)) + 1
                srs, m = [], 0.0
                for k in range(n):
                    tt = min(k * FRAME_MS, kcurve.x_end)
                    m = max(m, cv.inv(kcurve.v(tt)) / 100.0)
                    srs.append(m)
                tier = "kimariji-curve"
            else:
                srs, tier = [1.0], "instant"
            items.append(dict(ch=ch, start_ms=float(t0), series=srs, tier=tier))
        return items, None, max(i["start_ms"] for i in items)

    items, segs, t = [], [], 0.0
    idx = -1
    for ch, kind in normalize_text(text):
        if kind == "rest":
            # 無音の1拍。字は出さず、時間だけ進める。
            segs.append((None, max(slot_ms, 150.0)))
            t += max(slot_ms, 150.0)
            continue
        idx += 1
        dur_a = clip_ms(ch)
        # 1字の持ち時間。クリップより長ければ残りを無音で埋める。
        # 切り出した1音は中央104msしかなく、隙間なく並べると読みとして速すぎる
        # （自然音声の実測はかな1字303〜419ms）。slot_ms で読みの速さを決める。
        slot = max(slot_ms, dur_a)
        if kimariji and ch in kimariji and kcurve is not None:
            # 決まり字: 与えた理解度カーブを目標に、視覚曲線を逆引き
            cv, _ = visual.get((family, ch), (fb_v.get(family), "fallback"))
            n = int(math.ceil(kcurve.x_end / FRAME_MS)) + 1
            s, m = [], 0.0
            for k in range(n):
                tt = min(k * FRAME_MS, kcurve.x_end)
                # カーブの値は「その時点で識別できている割合」（生の値 0..1）。
                # 視覚曲線の到達点を超える分は inv() が端に丸める。
                m = max(m, cv.inv(kcurve.v(tt)) / 100.0)
                s.append(m)
            tier = "kimariji-curve"
        elif (kimariji and ch not in kimariji) or (first_only and idx > 0):
            # 重要でない字: その字が読まれた時刻に、一括で完成形を出す
            s = [1.0]
            tier = "instant"
        else:
            s, tier, _ = transfer_series(ch, family, audio, visual, fb_a, fb_v)
        items.append(dict(ch=ch, start_ms=t, series=s, tier=tier))
        segs.append((clip_path(ch), slot - dur_a))   # (クリップ, 後ろに足す無音ms)
        t += slot
    return items, segs, t


def _write_video(items, out_path, awav, total_ms, tail_ms, char_px, pad):
    n = len(items)
    W = pad * 2 + n * char_px
    H = pad * 2 + char_px
    W += (16 - W % 16) % 16
    H += (16 - H % 16) % 16
    frames = int(math.ceil((total_ms + tail_ms) / FRAME_MS))
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-",
         "-i", awav,
         "-af", "apad", "-t", f"{(total_ms + tail_ms) / 1000.0:.3f}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         out_path], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    base = np.full((H, W), 255, dtype=np.uint8)
    for f in range(frames):
        t = f * FRAME_MS
        fr = base.copy()
        for i, it in enumerate(items):
            rel = t - it["start_ms"]
            if rel < 0:
                continue
            k = rel / FRAME_MS
            sarr = it["series"]
            j = int(k)
            sv = sarr[-1] if j >= len(sarr) - 1 else                 sarr[j] * (1 - (k - j)) + sarr[j + 1] * (k - j)
            im = draw(it["family"], it["ch"], sv)
            x0 = pad + i * char_px
            fr[pad:pad + char_px, x0:x0 + char_px] =                 np.asarray(im.resize((char_px, char_px)))
        try:
            proc.stdin.write(fr.tobytes())
        except BrokenPipeError:
            break
    try:
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    proc.wait()
    if proc.returncode:
        raise RuntimeError("ffmpeg が失敗した:\n" + err[-800:])


def render_video(items, total_ms, out_path, segs, tail_ms=800.0,
                 char_px=96, pad=12, ext_audio=None):
    if ext_audio is not None:
        # 外部音声モード: 与えられた音声をそのまま使う（競技かるた）。
        with wave.open(ext_audio, "rb") as w:
            adur = w.getnframes() * 1000.0 / w.getframerate()
        _write_video(items, out_path, ext_audio,
                     max(total_ms, adur), tail_ms, char_px, pad)
        return
    tmp = tempfile.mkdtemp(prefix="ifont_")
    try:
        # 音声: クリップ＋持ち時間ぶんの無音、を順に連結する。
        # 無音を入れずに映像の開始時刻だけずらすと音とズレる（2026-08-30 修正）。
        first = next(pth for pth, _ in segs if pth is not None)
        with wave.open(first, "rb") as w0:
            rate, width, nch = w0.getframerate(), w0.getsampwidth(), w0.getnchannels()
        awav = os.path.join(tmp, "audio.wav")
        with wave.open(awav, "wb") as out:
            out.setnchannels(nch); out.setsampwidth(width); out.setframerate(rate)
            for path, sil_ms in segs:
                if path is not None:
                    with wave.open(path, "rb") as w:
                        out.writeframes(w.readframes(w.getnframes()))
                nsil = int(rate * max(sil_ms, 0.0) / 1000.0)
                out.writeframes(b"\x00" * (nsil * width * nch))
        _write_video(items, out_path, awav, total_ms, tail_ms, char_px, pad)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="iFont: 音と同期した文字アニメ動画を書き出す")
    ap.add_argument("text", help="かなの文字列")
    ap.add_argument("--family", default="blur",
                    choices=["fade", "reveal", "blur", "wipe"])
    ap.add_argument("--out", default="ifont_out.mp4")
    ap.add_argument("--slot-ms", type=float, default=0.0,
                    help="1字の持ち時間ms。クリップより長い分は無音で埋める。"
                         "0=クリップを隙間なく連結（読みは速い）。"
                         "自然な読みの目安は350前後、競技かるたの読みは700〜1000")
    ap.add_argument("--first-only", action="store_true",
                    help="1音目だけ転写し、残りは読まれた時刻に一括表示（いろはかるた）")
    ap.add_argument("--kimariji", default="",
                    help="かるたモード: 決まり字（この字だけ --curve で転写。残りは一括表示）")
    ap.add_argument("--curve", default="",
                    help="かるたモード: 理解度カーブ CSV（time_ms,value）")
    ap.add_argument("--audio", default="",
                    help="外部音声モード: 実際の読み上げ wav（カーブを測った音声）。"
                         "--onsets と併用。合成クリップは使わない")
    ap.add_argument("--onsets", default="",
                    help="外部音声モード: 各字の表示開始時刻 ms をカンマ区切りで")
    a = ap.parse_args(argv)

    audio, visual, fb_a, fb_v = load_curves()
    kcurve = load_kimariji_curve(a.curve) if a.curve else None
    onsets = [float(x) for x in a.onsets.split(",")] if a.onsets else None
    if (a.audio == "") != (onsets is None):
        raise SystemExit("--audio と --onsets は必ず両方指定してください")
    items, segs, total = build_timeline(
        a.text, a.family, audio, visual, fb_a, fb_v,
        slot_ms=a.slot_ms, kimariji=a.kimariji, kcurve=kcurve,
        first_only=a.first_only, onsets=onsets)
    for it in items:
        it["family"] = a.family
    render_video(items, total, a.out, segs, ext_audio=(a.audio or None))
    tiers = {it["ch"]: it["tier"] for it in items}
    print(f"書き出し: {a.out}")
    print(f"  文字数 {len(items)} ／ 音声 {total:.0f} ms ／ 方式 {a.family}")
    print("  曲線の階層:", " ".join(f"{c}:{t}" for c, t in tiers.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
