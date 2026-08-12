#!/usr/bin/env python3
"""か行5択・セグメント操作パイロットの刺激生成器。

東北きりたん(108)で か/き/く/け/こ をB3・0.3秒で合成し、子音・母音の長さを
PSOLA で独立に伸縮({0.5,1,2}×{0.5,1,2}=9条件)。子音/母音の境界は合成クエリの
consonant_length から正確に得る。manifest.json と wav 群を出力する。

実行(VOICEVOX起動下): ~/ifont_env/bin/python experiment/tools/build_kana_segment_pilot.py <出力dir>
"""
import json
import math
import os
import sys
import wave
import io

import numpy as np
import parselmouth

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ifont_tool"))
from ifont import audio as ifa

KANAS = ["か", "き", "く", "け", "こ"]
SCALES = [0.5, 1.0, 2.0]
B3 = 246.94
DUR = 0.30
SPK = 108
SR = 44100


def synth_kana(ch):
    """1かなを合成し、(波形, 音響的開始s, 子音終了s, 母音終了s) を返す。"""
    kata = ifa._hira_to_kata(ch)
    q = ifa._vv_query(kata, SPK, "http://127.0.0.1:50021")
    m = dict(ifa._flatten_moras(q)[0])
    if m.get("vowel"):
        m["vowel"] = m["vowel"].lower()
    m = ifa._set_mora(m, math.log(B3), DUR)
    cons = m.get("consonant_length") or 0.0
    q["accent_phrases"] = [{"moras": [m], "accent": 1, "pause_mora": None,
                            "is_interrogative": False}]
    q.update(dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0, volumeScale=1.0,
                  prePhonemeLength=0.05, postPhonemeLength=0.10, outputSamplingRate=SR))
    wav = ifa._vv_synth(q, SPK, "http://127.0.0.1:50021")
    with wave.open(io.BytesIO(wav), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    # クエリ上の時間構造: 先頭無音0.05 + 子音cons + 母音(DUR-cons)
    t_on, t_cv, t_end = 0.05, 0.05 + cons, 0.05 + DUR
    return x, t_on, t_cv, t_end


def stretch(x, spans):
    """spans: [(a, b, rate), ...] の区間をそれぞれ rate 倍に PSOLA 伸縮。"""
    snd = parselmouth.Sound(x, sampling_frequency=SR)
    manip = parselmouth.praat.call(snd, "To Manipulation", 0.01, 100.0, 520.0)
    T = len(x) / SR
    dt = parselmouth.praat.call("Create DurationTier", "st", 0.0, T)
    EPS = 0.002
    parselmouth.praat.call(dt, "Add point", 0.0, 1.0)
    prev = 1.0
    for (a, b, r) in spans:
        parselmouth.praat.call(dt, "Add point", a - EPS, prev)
        parselmouth.praat.call(dt, "Add point", a + EPS, r)
        parselmouth.praat.call(dt, "Add point", b - EPS, r)
        prev = r
    parselmouth.praat.call(dt, "Add point", spans[-1][1] + EPS, 1.0)
    parselmouth.praat.call([dt, manip], "Replace duration tier")
    res = parselmouth.praat.call(manip, "Get resynthesis (overlap-add)")
    return res.values[0]


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    variants = []
    for ch in KANAS:
        x, t_on, t_cv, t_end = synth_kana(ch)
        for cs in SCALES:
            for vs in SCALES:
                vid = f"{ch}_c{int(cs*10):02d}_v{int(vs*10):02d}"
                if cs == 1.0 and vs == 1.0:
                    y = x.copy()
                else:
                    y = stretch(x, [(t_on, t_cv, cs), (t_cv, t_end, vs)])
                path = os.path.join(outdir, vid + ".wav")
                with wave.open(path, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(SR)
                    w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
                variants.append(dict(id=vid, file=vid + ".wav", kana=ch,
                                     cons_scale=cs, vowel_scale=vs,
                                     cons_ms=round((t_cv - t_on) * cs * 1000),
                                     vowel_ms=round((t_end - t_cv) * vs * 1000)))
        print(f"{ch}: 子音 {1000*(t_cv-t_on):.0f}ms / 母音 {1000*(t_end-t_cv):.0f}ms → 9変形")
    manifest = dict(choices=KANAS, scales=SCALES, variants=variants,
                    speaker="東北きりたん(108)・B3・0.3秒", note="PSOLAで子音/母音を独立伸縮")
    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"{len(variants)}刺激 + manifest.json を {outdir} に出力")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "kana_segment_stimuli")
