#!/usr/bin/env python3
"""音素セグメント操作パイロットの刺激生成器。

木本実読み「ちは 上」(Kikiwake・読み取りのみ)を素材に、母音のみ/子音のみの長さを
PSOLA で伸縮した変形音声と、決まり字聞き分け用の打ち切り点(伸縮後時刻に変換済み)を
manifest.json に出力する。音声は実読み話者の声のため git に入れない(ローカル生成)。

実行: ~/ifont_env/bin/python experiment/tools/build_segment_pilot.py <出力dir>
"""
import json
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
import parselmouth

KIKIWAKE = os.path.expanduser("~/Documents/GitHub/Kikiwake")
SRC_M4A = os.path.join(KIKIWAKE, "sounds_kimoto", "ちは 上.m4a")
MFA = os.path.join(KIKIWAKE, "mfa_v3", "onset_extracted_v3.json")
SONG = "17"
VOWELS = {"a", "i", "u", "e", "o", "ɯ", "ɨ", "ä", "e̞", "o̞"}
SR = 44100

# 打ち切り点(原音の時刻・秒)。決まり字「ちは」の聞き分けが徐々に可能になる位置
# tɕ途中 / ち母音まで / は子音まで / ちは母音まで / やまで / 全長
GATES = [0.10, 0.26, 0.46, 0.58, 0.95, None]
GATE_LABELS = ["ち子音の途中", "「ち」まで", "は子音まで", "「ちは」まで", "「ちはや」まで", "全長(自然さ評価)"]

CONDS = [("vowel", 0.6), ("vowel", 1.0), ("vowel", 1.5),
         ("cons", 0.6), ("cons", 1.5)]   # (1.0はvowel側で代表=原音)


def load_src():
    tmp = os.path.join(tempfile.gettempdir(), "seg_src.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", SRC_M4A, "-ac", "1", "-ar", str(SR), tmp], check=True)
    with wave.open(tmp, "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    d = json.load(open(MFA))[SONG]
    phones = [(p["xmin_ms"] / 1000, p["xmax_ms"] / 1000, p["text"])
              for p in d["phones"] if p["text"] != "spn"]
    x = load_src()
    T = len(x) / SR

    def rate_at(t, target, scale):
        for (a, b, ph) in phones:
            if a <= t < b:
                is_v = ph in VOWELS
                hit = (target == "vowel" and is_v) or (target == "cons" and not is_v)
                return scale if hit else 1.0
        return 1.0

    def warp_time(t, target, scale):
        """原音の時刻 t が伸縮後に来る時刻(rate の積分)。"""
        out, cur = 0.0, 0.0
        step = 0.001
        while cur < t:
            out += rate_at(cur, target, scale) * step
            cur += step
        return out

    variants = []
    for (target, scale) in CONDS:
        vid = f"{target}_{int(scale*100):03d}"
        out_wav = os.path.join(outdir, vid + ".wav")
        if scale == 1.0:
            y = x.copy()
        else:
            snd = parselmouth.Sound(x, sampling_frequency=SR)
            manip = parselmouth.praat.call(snd, "To Manipulation", 0.01, 100.0, 520.0)
            dt = parselmouth.praat.call("Create DurationTier", "st", 0.0, T)
            EPS = 0.003
            parselmouth.praat.call(dt, "Add point", 0.0, 1.0)
            prev = 1.0
            for (a, b, ph) in phones:
                r = rate_at((a + b) / 2, target, scale)
                parselmouth.praat.call(dt, "Add point", a - EPS, prev)
                parselmouth.praat.call(dt, "Add point", a + EPS, r)
                parselmouth.praat.call(dt, "Add point", b - EPS, r)
                prev = r
            parselmouth.praat.call(dt, "Add point", phones[-1][1] + EPS, 1.0)
            parselmouth.praat.call([dt, manip], "Replace duration tier")
            res = parselmouth.praat.call(manip, "Get resynthesis (overlap-add)")
            y = res.values[0]
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
        gates = [round(warp_time(g, target, scale), 3) if g is not None else None
                 for g in GATES]
        variants.append(dict(id=vid, file=vid + ".wav", target=target, scale=scale,
                             gates_s=gates, dur_s=round(len(y) / SR, 3)))
        print(f"{vid}: {len(y)/SR:.2f}s gates={gates}")

    manifest = dict(
        song="ちはやぶる(17番)・木本読み・上の句",
        choices=["ちはやぶる", "ちぎりきな", "ちぎりおきし"],
        answer=0,
        gate_labels=GATE_LABELS,
        variants=variants,
    )
    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"manifest.json + {len(variants)}変形 を {outdir} に出力")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "segment_pilot_stimuli")
