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
# v2: 十字の5条件(子音か母音の一方だけ動かす+基準)と、打ち切りゲート
CONDS = [(1.0, 1.0), (0.5, 1.0), (2.0, 1.0), (1.0, 0.5), (1.0, 2.0)]
# v3.2: 天井セルを削除し、未測定だった子音終了〜母音1/12の間に母音1/24を新設
GATE_LABELS = ["子音の終わりまで", "母音の1/24まで", "母音の1/12まで", "母音の1/6まで"]
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


TARGET_DB = -26.0     # 断片の目標音量(有音部RMS)
MAX_GAIN_DB = 30.0    # 増幅の上限。これでも届かない断片は「物理的にほぼ無音」として記録


def render_fragment(y, gate_s, path):
    """全長波形 y の先頭〜gate_s を切り出し、末尾2msフェード+音量正規化して保存。
    返り値 (適用ゲインdB, 頭打ちしたか)。"""
    seg = y[:int(gate_s * SR)].copy() if gate_s else y.copy()
    nf = int(0.002 * SR)
    if len(seg) > nf:
        seg[-nf:] *= np.linspace(1, 0, nf)
    body = seg[int(0.05 * SR):]                      # 先頭無音50msを除いた有音部
    rms = float(np.sqrt(np.mean(body ** 2))) if len(body) else 0.0
    cur_db = 20 * math.log10(max(rms, 1e-9))
    gain_db = TARGET_DB - cur_db
    capped = gain_db > MAX_GAIN_DB
    gain_db = min(gain_db, MAX_GAIN_DB)
    seg = seg * (10 ** (gain_db / 20))
    peak = float(np.max(np.abs(seg))) if len(seg) else 0.0
    if peak > 0.95:
        seg *= 0.95 / peak
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(seg, -1, 1) * 32767).astype("<i2").tobytes())
    return round(gain_db, 1), capped


def main(outdir, grid=False):
    os.makedirs(outdir, exist_ok=True)
    conds = ([(c, v) for c in SCALES for v in SCALES] if grid else CONDS)
    variants = []
    for ch in KANAS:
        x, t_on, t_cv, t_end = synth_kana(ch)
        cons, vowel = t_cv - t_on, t_end - t_cv
        for (cs, vs) in conds:
            vid = f"{ch}_c{int(cs*10):02d}_v{int(vs*10):02d}"
            if cs == 1.0 and vs == 1.0:
                y = x.copy()
            else:
                y = stretch(x, [(t_on, t_cv, cs), (t_cv, t_end, vs)])
            # 打ち切りゲート(伸縮後の時刻): 子音終わり / 母音1/24 / 1/12 / 1/6
            cv = t_on + cons * cs
            gates = [round(cv, 3), round(cv + vowel * vs / 24, 3),
                     round(cv + vowel * vs / 12, 3), round(cv + vowel * vs / 6, 3)]
            frags = []
            for gi, g in enumerate(gates):
                fname = f"{vid}_g{gi}.wav"
                gain_db, capped = render_fragment(y, g, os.path.join(outdir, fname))
                frags.append(dict(file=fname, gate_s=g, gain_db=gain_db, capped=capped))
            variants.append(dict(id=vid, kana=ch,
                                 cons_scale=cs, vowel_scale=vs,
                                 cons_ms=round(cons * cs * 1000),
                                 vowel_ms=round(vowel * vs * 1000),
                                 gates_s=gates, fragments=frags))
        print(f"{ch}: 子音 {1000*cons:.0f}ms / 母音 {1000*vowel:.0f}ms → {len(conds)}変形×{len(GATE_LABELS)}断片")
    manifest = dict(choices=KANAS, scales=SCALES, gate_labels=GATE_LABELS,
                    variants=variants,
                    speaker="東北きりたん(108)・B3・0.3秒", note="PSOLAで子音/母音を独立伸縮")
    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"{len(variants)}刺激 + manifest.json を {outdir} に出力")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--grid"]
    main(args[0] if args else "kana_segment_stimuli", grid="--grid" in sys.argv)
