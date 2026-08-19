#!/usr/bin/env python3
"""
清濁混同の切り分け用 診断音源ビルダー
====================================
目的は「いちばん良い『ぽ』を作る」ことではなく、**どの加工が清濁の聞こえを壊しているか**を
1つずつ戻して切り分けること。project/提案_方針転換_小さく確かめてから広げる.md のB節に対応する。

作る版（1文字あたり最大7種）:
  cur_mp3   本番プールの mp3 をそのままコピー（＝参加者に届いている実物）
  cur_wav   同じ音の「mp3化する前のWAV」。本番と同じ手順で作り直したもの
            （再現の忠実さは、作り直したWAVをmp3にして本番mp3と比べて確認する）
  solo_mp3  「ぽ」だけ: 「オッポ」からの切り出しをやめ、他のぱ行と同じ
  solo_wav               単独合成＋VOT自動修正（子音長を伸ばして破裂から声までの間を確保）で作った版
  soloraw_wav 「ぽ」だけ: 単独合成で VOT自動修正もかけない素の版（修正が何をしているかの基準）
  psola_wav  cur_wav を PSOLA（音の高さだけを書き換える再合成）で「完全に平坦な音の高さ」に
             したもの。次の onsetf0_wav と比べるための対照（PSOLA自体の副作用を打ち消す）
  onsetf0_wav 音の高さを平坦（B3=246.94Hz）に保ちつつ、**母音が始まった直後60ミリ秒だけ**、
             平坦化していない自然な合成が持っていた高さの上下（相対値）を戻した版。
             日本語の清濁は、破裂から声までの間（VOT）だけでなく
             「子音直後の音の高さ」でも区別されるという先行研究にもとづく検証。
  natf0_wav  平坦化そのものをやめた版（VOICEVOXが自然に付ける音の高さのまま）。参考。

出力:
  experiment/tools/seidaku_diag_assets/*.wav / *.mp3
  experiment/tools/seidaku_diag_assets/clips.json   … 再生に必要な切り出し情報（本番と同じ算法で実測）
  experiment/tools/seidaku_diag_assets/build_report.json … 再現の忠実さ・採用パラメータの記録

実行（VOICEVOXを localhost:50021 で起動しておく）:
  ~/ifont_env/bin/python experiment/tools/build_seidaku_diag.py
"""
import json, os, sys, io, math, wave, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
sys.path.insert(0, os.path.join(REPO, "two_char_audio"))
sys.path.insert(0, REPO)

import numpy as np
import parselmouth
from parselmouth.praat import call as praat
import build_2char_pool as b2
import build_1char_pool as b1
import ifont_common as ic

OUT_DIR = os.path.join(HERE, "seidaku_diag_assets")
MANIFEST = os.path.join(EXP, "audio1char_manifest.json")
ANSWERKEY = os.path.join(EXP, "answer_key_merged.json")
STIM_DIR = os.path.join(EXP, "audio1char_stimuli")

VOICELESS = ["ぽ", "ぱ", "ぴ", "か"]      # 診断の対象（無声＝清音）
VOICED = ["ぼ", "ば", "び", "が"]         # 聞き比べの参照（もともと濁音）
CHARS = VOICELESS + VOICED
ROMA = {"ぽ": "po", "ぱ": "pa", "ぴ": "pi", "か": "ka",
        "ぼ": "bo", "ば": "ba", "び": "bi", "が": "ga"}

# 母音開始直後の何ミリ秒ぶんの「音の高さの上下」を戻すか（onsetf0_wav）
ONSET_F0_WINDOW_MS = 60.0

# --- build_onsets.py と同一の定数（本番の切り出し・音量そろえを再現するため） ---
ONSET_DBFS, SUSTAIN_MS, FRAME_MS, PEAK_CAP = -63.0, 15, 5, 0.85


# ---------------------------------------------------------------- 基本ユーティリティ
def wav_np(b):
    with wave.open(io.BytesIO(b), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def np_wav(x, fr):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def decode_file(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
                        "-f", "wav", "pipe:1"], stdout=subprocess.PIPE, check=True)
    return wav_np(p.stdout)


def a_weight(f):
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = (12194.0**2 * f**4) / ((f**2 + 20.6**2) *
          np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    ra1k = (12194.0**2 * 1000.0**4) / ((1000.0**2 + 20.6**2) *
            math.sqrt((1000.0**2 + 107.7**2) * (1000.0**2 + 737.9**2)) * (1000.0**2 + 12194.0**2))
    return ra / ra1k


def frame_db(seg, fr):
    fl = max(1, int(FRAME_MS / 1000 * fr))
    n = len(seg) // fl
    rms = np.array([np.sqrt(np.mean(seg[i*fl:(i+1)*fl]**2)) for i in range(n)]) if n else np.array([0.0])
    return 20 * np.log10(np.maximum(rms, 1e-7))


def find_onset_ms(seg, fr):
    db = frame_db(seg, fr)
    need = max(1, int(SUSTAIN_MS / FRAME_MS))
    for i in range(len(db) - need + 1):
        if np.all(db[i:i+need] > ONSET_DBFS):
            return i * FRAME_MS
    return 0


def voiced_end_ms(seg, fr):
    db = frame_db(seg, fr)
    idx = np.where(db > ONSET_DBFS)[0]
    return int(idx[-1] * FRAME_MS) if len(idx) else int(len(seg) / fr * 1000)


def aw_rms(seg, fr):
    if len(seg) < 64:
        return 1e-6
    fl = max(1, int(0.010 * fr)); n = len(seg) // fl
    rms = np.array([np.sqrt(np.mean(seg[i*fl:(i+1)*fl]**2)) for i in range(n)]) if n else np.array([0.0])
    thr = max(rms.max() * 0.08, 1e-4)
    mask = np.repeat(rms > thr, fl)[:len(seg)]
    v = seg[:len(mask)][mask]
    if len(v) < 64:
        return 1e-6
    F = np.fft.rfft(v * np.hanning(len(v)))
    freqs = np.fft.rfftfreq(len(v), 1.0 / fr)
    return float(np.sqrt(np.sum(np.abs(F * a_weight(freqs))**2)) / len(v) * math.sqrt(2))


# ---------------------------------------------------------------- 合成（本番と同じ経路）
class Synth:
    """本番プール（speaker=108 / B3平坦 / 1モーラ0.2秒）と同じ合成を1文字単位で再現する。"""

    def __init__(self, speaker):
        self.speaker = speaker
        self.base_q = None
        self.moras = {}
        self.p_base = math.log(b1.B3)

    def mora(self, ch):
        if ch not in self.moras:
            q = json.loads(b2.post("/audio_query", {"text": b2.to_kata(ch), "speaker": self.speaker}))
            self.moras[ch] = q["accent_phrases"][0]["moras"][0]
            if self.base_q is None:
                self.base_q = q
        return self.moras[ch]

    def raw(self, ch, pitch_ln, vol, cmul=1.0, flatten=True):
        """1モーラを合成する。flatten=False のとき音の高さの平坦化をかけない（自然音高版）。"""
        m0 = dict(self.mora(ch))
        if cmul != 1.0 and m0.get("consonant_length"):
            m0["consonant_length"] = m0["consonant_length"] * cmul
        if flatten:
            m = b2.set_mora(m0, pitch_ln, b1.MORA_DUR)
        else:                                  # 長さだけ本番と同じにし、pitch は問い合わせ既定のまま
            m = b2.set_mora(m0, m0.get("pitch", pitch_ln), b1.MORA_DUR)
        self.mora(ch)
        q = dict(self.base_q)
        q["accent_phrases"] = [{"moras": [m], "accent": 1,
                                "pause_mora": None, "is_interrogative": False}]
        for k, v in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0, volumeScale=vol,
                         prePhonemeLength=0.1, postPhonemeLength=0.1).items():
            q[k] = v
        return b2.post("/synthesis", {"speaker": self.speaker}, q), m, q

    def produce(self, ch, pitch_ln, vol, cmul=1.0, dsp=None, flatten=True):
        wav, m, q = self.raw(ch, pitch_ln, vol, cmul, flatten)
        if dsp:
            wav = b1.apply_dsp(wav, q["prePhonemeLength"], dsp)
        return wav, m, q

    def pitch_ln_for(self, ch, cmul, dsp):
        """本番の第1パスと同じ手順で、その文字に使う対数F0を決める（必要なら1回だけ補正）。"""
        pln = self.p_base
        wav, m, q = self.produce(ch, pln, 1.0, cmul, dsp)
        onset = q["prePhonemeLength"] + (m.get("consonant_length") or 0)
        f0 = b2.med_f0(wav, onset + 0.03, onset + m["vowel_length"] - 0.02)
        if f0 == f0 and abs(b2.cents(f0, b1.B3)) > b2.CORRECT_CENTS:
            pln = self.p_base + (math.log(b1.B3) - math.log(f0))
        return pln, f0

    def vot_ladder(self, ch):
        """本番の「VOT自動修正」と同じラダー。破裂から声までが25ms以上になる最小の子音長倍率を返す。"""
        best = (1.0, None)
        for cm in b1.VOT_CMULS:
            wav, m, q = self.raw(ch, self.p_base, 1.0, cmul=cm)
            vot = b1.measure_vot_ms(wav, q["prePhonemeLength"])
            best = (cm, (round(vot, 1) if vot == vot else None))
            if vot == vot and vot >= b1.VOT_TARGET_MS:
                break
        return best


# ---------------------------------------------------------------- PSOLA（音の高さの書き換え）
def f0_track(x, fr, floor, ceiling, step=0.005):
    """音の高さの時間変化を追う。1回目で大まかな中央値を出し、その前後だけに範囲を絞って
    2回目を取り直す。範囲を広く取ると1オクターブ下（倍の周期）を拾って、
    母音開始直後のずれが十数半音という有り得ない値になるため（本番の med_f0 と同じ用心）。"""
    pp = parselmouth.Sound(x, fr).to_pitch(step, floor, ceiling)
    f = pp.selected_array["frequency"]
    v = f[f > 0]
    if len(v) >= 5:
        med = float(np.median(v))
        lo, hi = max(60.0, med * 0.65), min(900.0, med * 1.7)
        pp = parselmouth.Sound(x, fr).to_pitch(step, lo, hi)
        f = pp.selected_array["frequency"]
    return pp.xs(), f


def psola_repitch(x, fr, times, freqs, splice_at_s=None, floor=120.0, ceiling=500.0):
    """指定した時刻・周波数の並びに音の高さを書き換えて再合成する（Praatの重畳加算）。
    splice_at_s を渡すと、そこより前は元の波形をそのまま使い、3msでつなぐ
    （破裂の瞬間を再合成で崩さないため）。"""
    snd = parselmouth.Sound(x, fr)
    man = praat(snd, "To Manipulation", 0.005, floor, ceiling)
    pt = praat(man, "Extract pitch tier")
    praat(pt, "Remove points between", 0.0, snd.get_total_duration())
    for t, f in zip(times, freqs):
        praat(pt, "Add point", float(t), float(f))
    praat([pt, man], "Replace pitch tier")
    out = praat(man, "Get resynthesis (overlap-add)")
    y = np.asarray(out.values[0], dtype=np.float64)
    if len(y) < len(x):
        y = np.concatenate([y, np.zeros(len(x) - len(y))])
    y = y[:len(x)]
    if splice_at_s is not None:
        i = int(splice_at_s * fr)
        xf = max(8, int(0.003 * fr))
        i = max(xf, min(i, len(x) - xf - 1))
        w = 0.5 * (1 - np.cos(np.pi * np.arange(xf) / xf))
        z = x.copy()
        z[i:i+xf] = x[i:i+xf] * (1 - w) + y[i:i+xf] * w
        z[i+xf:] = y[i+xf:]
        y = z
    return y


def first_voiced_s(times, freqs, after_s=0.0):
    for t, f in zip(times, freqs):
        if t >= after_s and f > 0:
            return float(t)
    return None


def make_onset_f0(flat_wav, nat_wav, char_onset_s, keep_ms=ONSET_F0_WINDOW_MS):
    """平坦化した音に、自然音高版が母音開始直後に持っていた「相対的な高さの動き」だけを戻す。
    返り値: (温存版WAVバイト列, 完全平坦PSOLA対照WAVバイト列, 記録用の測定値dict)"""
    xf, fr = wav_np(flat_wav)
    xn, frn = wav_np(nat_wav)
    assert fr == frn
    tf, ff = f0_track(xf, fr, 150, 450)
    tn, fn = f0_track(xn, frn, 100, 600)
    v_f = first_voiced_s(tf, ff, char_onset_s)
    v_n = first_voiced_s(tn, fn, char_onset_s)
    if v_f is None or v_n is None:
        return None, None, dict(ok=False, reason="有声区間を検出できない")
    end_s = char_onset_s + b1.MORA_DUR
    med_f = float(np.median([f for t, f in zip(tf, ff) if v_f <= t <= end_s and f > 0]))
    stable = [f for t, f in zip(tn, fn) if v_n + 0.08 <= t <= end_s and f > 0]
    if not stable:
        stable = [f for t, f in zip(tn, fn) if t >= v_n and f > 0]
    med_n = float(np.median(stable))

    def delta_st(dt_s):
        """自然音高版の、母音開始からdt秒後における『定常部からのずれ』（半音単位）。"""
        cand = [(abs(t - (v_n + dt_s)), f) for t, f in zip(tn, fn) if f > 0]
        if not cand:
            return 0.0
        d, f = min(cand)
        if d > 0.02:
            return 0.0
        st = 12.0 * math.log2(f / med_n)
        # 自然発話で子音直後に起きる高さのずれはせいぜい±3半音。それを超える値は
        # 高さの追跡ミス（オクターブ飛び）とみなして採らない。
        return max(-3.0, min(3.0, st))

    keep_s = keep_ms / 1000.0
    pts_keep, pts_flat, prof = [], [], []
    for t, f in zip(tf, ff):
        if f <= 0:
            continue
        dt = t - v_f
        d = 0.0
        if 0 <= dt <= keep_s:
            taper = 0.5 * (1 + math.cos(math.pi * dt / keep_s))   # 60msかけて0へなめらかに戻す
            d = delta_st(dt) * taper
            prof.append((round(dt * 1000, 1), round(d, 3)))
        pts_keep.append((t, med_f * 2 ** (d / 12.0)))
        pts_flat.append((t, med_f))
    y_keep = psola_repitch(xf, fr, [p[0] for p in pts_keep], [p[1] for p in pts_keep], splice_at_s=v_f)
    y_flat = psola_repitch(xf, fr, [p[0] for p in pts_flat], [p[1] for p in pts_flat], splice_at_s=v_f)
    meas = dict(ok=True, flat_median_hz=round(med_f, 2), nat_median_hz=round(med_n, 2),
                voicing_onset_flat_s=round(v_f, 4), voicing_onset_nat_s=round(v_n, 4),
                onset_delta_semitone_profile=prof,
                onset_delta_max_semitone=(round(max((abs(d) for _, d in prof), default=0.0), 3)))
    return np_wav(y_keep, fr), np_wav(y_flat, fr), meas


# ---------------------------------------------------------------- メイン
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):        # 前回の生成物を消す（版の名前を変えたときの取り残し防止）
        if f.endswith((".wav", ".mp3", ".json")):
            os.remove(os.path.join(OUT_DIR, f))
    man = json.load(open(MANIFEST))
    ak = json.load(open(ANSWERKEY))
    speaker = man["speaker"]
    stim_by_char = {}
    for s in man["stimuli"]:
        e = ak.get("audio1char|" + s["id"])
        if e and e["char"] in CHARS:
            stim_by_char[e["char"]] = (s, e)
    missing = [c for c in CHARS if c not in stim_by_char]
    if missing:
        sys.exit("本番manifestに見つからない文字: " + "".join(missing))

    print(f"VOICEVOX {b2.get('/version')} / speaker={speaker}", file=sys.stderr)
    syn = Synth(speaker)
    report = dict(speaker=speaker, voicevox=b2.get("/version"),
                  manifest_pool=[stim_by_char[c][1].get("pool") for c in CHARS],
                  chars={}, notes={})

    # --- 本番の「音量そろえの目標値」を復元する ------------------------------
    # 第2パスの volumeScale = 目標A特性RMS / その字のA特性RMS。答えの表に残っている
    # vol_scale から逆算し、複数字で一致することを確かめる（＝再現が正しい傍証）。
    targets = []
    for ch in CHARS:
        s, e = stim_by_char[ch]
        cmul = b1.PRESCRIPTION_CMUL.get(ch, e.get("vot_cmul") or 1.0)
        dsp = b1.PRESCRIPTION_DSP.get(ch)
        if ch in b1.OPPO_SPLICE:
            continue
        pln, _ = syn.pitch_ln_for(ch, cmul, dsp)
        wav, m, q = syn.produce(ch, pln, 1.0, cmul, dsp)
        aw = b1.aweighted_rms(wav, q["prePhonemeLength"],
                              (m.get("consonant_length") or 0) + m["vowel_length"])
        targets.append(aw * e["vol_scale"])
    target_awrms = float(np.median(targets))
    report["notes"]["target_awrms"] = round(target_awrms, 6)
    report["notes"]["target_awrms_spread"] = [round(min(targets), 6), round(max(targets), 6)]
    print(f"音量そろえの目標(A特性RMS)を逆算: {target_awrms:.5f} "
          f"(字ごとの推定 {min(targets):.5f}〜{max(targets):.5f})", file=sys.stderr)

    files = {}     # (char, version) -> filename

    def save_wav(ch, ver, wav_bytes):
        fn = f"{ROMA[ch]}_{ver}.wav"
        open(os.path.join(OUT_DIR, fn), "wb").write(wav_bytes)
        files[(ch, ver + "_wav")] = fn
        return fn

    def save_mp3(ch, ver, wav_bytes):
        fn = f"{ROMA[ch]}_{ver}.mp3"
        open(os.path.join(OUT_DIR, fn), "wb").write(b2.wav_to_mp3(wav_bytes))
        files[(ch, ver + "_mp3")] = fn
        return fn

    def solo_synth(ch, cmul):
        """単独合成（＝ぱ行の通常経路）で1文字を作る。音量は本番と同じ目標にそろえる。"""
        pln, _ = syn.pitch_ln_for(ch, cmul, None)
        w0, m0, q0 = syn.produce(ch, pln, 1.0, cmul, None)
        aw = b1.aweighted_rms(w0, q0["prePhonemeLength"],
                              (m0.get("consonant_length") or 0) + m0["vowel_length"])
        vol = max(b1.VOL_MIN, min(b1.VOL_MAX, target_awrms / max(aw, 1e-6)))
        wav, m, q = syn.produce(ch, pln, vol, cmul, None)
        nat, _, _ = syn.produce(ch, pln, vol, cmul, None, flatten=False)
        return wav, nat, dict(cmul=cmul, vol_scale=round(vol, 3), pitch_ln=round(pln, 5),
                              vot_ms=round(b1.measure_vot_ms(wav, q["prePhonemeLength"]), 1))

    for ch in CHARS:
        s, e = stim_by_char[ch]
        info = dict(pool_id=s["id"], pool_recipe=e.get("recipe"), vol_scale=e["vol_scale"])

        # 1) 本番mp3をそのままコピー（参加者に届いている実物）
        fn = f"{ROMA[ch]}_cur.mp3"
        shutil.copyfile(os.path.join(STIM_DIR, s["file"]), os.path.join(OUT_DIR, fn))
        files[(ch, "cur_mp3")] = fn

        # 2) mp3化する前のWAVを、本番と同じ手順で作り直す
        pln = syn.p_base
        cmul, dsp = 1.0, None
        if ch in b1.OPPO_SPLICE:
            # 「ぽ」は「オッポ」からの切り出し。第1パスの音高補正は行わない仕様。
            wav = _oppo(syn, ch, pln, e["vol_scale"])
            info["route"] = "oppo-splice"
        else:
            cmul = b1.PRESCRIPTION_CMUL.get(ch, e.get("vot_cmul") or 1.0)
            dsp = b1.PRESCRIPTION_DSP.get(ch)
            pln, _ = syn.pitch_ln_for(ch, cmul, dsp)
            wav, m, q = syn.produce(ch, pln, e["vol_scale"], cmul, dsp)
            info["route"] = e.get("recipe")
            info["cmul"] = cmul
        save_wav(ch, "cur", wav)

        # 再現の忠実さ: 作り直したWAVをmp3にして、本番mp3と復号後に比べる
        a, fr = wav_np(subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "wav", "pipe:1"],
            input=b2.wav_to_mp3(wav), stdout=subprocess.PIPE, check=True).stdout)
        r, _ = decode_file(os.path.join(STIM_DIR, s["file"]))
        n = min(len(a), len(r))
        d = a[:n] - r[:n]
        info["repro_rms_diff_db"] = round(20 * math.log10(max(float(np.sqrt(np.mean(d**2))), 1e-9) /
                                                          max(float(np.sqrt(np.mean(r[:n]**2))), 1e-9)), 1)

        # 3) 「ぽ」だけ: 切り出しをやめた単独合成版（瞿2022の直接検証）
        if ch in b1.OPPO_SPLICE:
            cm, vot_ladder = syn.vot_ladder(ch)
            report["notes"]["po_solo_vot_ladder"] = dict(
                cmul=cm, vot_ms=vot_ladder, target_ms=b1.VOT_TARGET_MS)
            print(f"「ぽ」単独合成のVOT自動修正: 子音長x{cm} で VOT={vot_ladder}ms "
                  f"(目標{b1.VOT_TARGET_MS}ms)", file=sys.stderr)
            base, nat, si = solo_synth(ch, cm)          # VOT自動修正あり = 推奨経路
            raw, _, ri = solo_synth(ch, 1.0)            # 修正なしの素（修正の効き目の基準）
            save_wav(ch, "solo", base)
            save_mp3(ch, "solo", base)
            save_wav(ch, "soloraw", raw)
            info["solo"] = dict(fixed=si, raw=ri)
            base_label = "単独合成（VOT自動修正あり）"
        else:
            base, nat = wav, syn.produce(ch, pln, e["vol_scale"], cmul, dsp, flatten=False)[0]
            base_label = "本番と同じ音"

        # 4) 音の高さ: 平坦化しない版 / PSOLA完全平坦（対照）/ 母音直後だけ高さの動きを戻した版
        #    「ぽ」だけは基準を単独合成版にする（切り出し元の「オッポ」は文中の位置が違い、
        #    自然音高の比較対象として不適切なため）。
        save_wav(ch, "natf0", nat)
        keep, flat, meas = make_onset_f0(base, nat, 0.1)
        meas["base"] = base_label
        info["onset_f0"] = meas
        if keep:
            save_wav(ch, "onsetf0", keep)
            save_wav(ch, "psola", flat)

        report["chars"][ch] = info
        print(f"  {ch}: 再現差 {info['repro_rms_diff_db']}dB / F0基準={base_label} / "
              f"母音直後のF0ずれ最大 {meas.get('onset_delta_max_semitone')}半音", file=sys.stderr)

    # --- 各ファイルの切り出し情報（本番と同じ算法で実測）----------------------
    # 本番は「文字の先頭(0.1s) + 実測した音の立ち上がり」から「モーラの終わり」までを窓にする。
    # ここでは版ごとに前置きの長さが違う（mp3は符号化の遅れが約46ms入る）ので、
    # 文字先頭からの相対値ではなく **ファイル内の絶対時刻** で窓を持たせる。
    rec = {}
    for (ch, ver), fn in files.items():
        x, fr = decode_file(os.path.join(OUT_DIR, fn))
        on_ms = find_onset_ms(x, fr)                    # ファイル頭からの立ち上がり(ms)
        end_ms = voiced_end_ms(x, fr) + FRAME_MS        # 最後に音があったフレームの終わり
        a, b = int(on_ms / 1000 * fr), int(end_ms / 1000 * fr)
        played = x[a:b]
        rec[(ch, ver)] = dict(file=fn, sr=fr, start_s=round(on_ms / 1000, 4),
                              avail_ms=round((end_ms - on_ms), 3),
                              awrms=aw_rms(played, fr),
                              peak=float(np.abs(played).max()) if len(played) else 0.0)

    # 音量は「その文字の本番mp3」に合わせる。条件間の差が音量差にならないようにする。
    # cur_wav はcur_mp3と中身が同じ音なので、本番の gate_gain をそのまま使う
    # （WAV/mp3の比較が音量の比較にならないように）。
    clips = {}
    for (ch, ver), r in rec.items():
        base = rec[(ch, "cur_mp3")]
        prod_gain = stim_by_char[ch][0].get("gate_gain", 1.0)
        if ver in ("cur_mp3", "cur_wav"):
            g = prod_gain
        else:
            g = (base["awrms"] * prod_gain) / max(r["awrms"], 1e-6)
        if r["peak"] * g > PEAK_CAP:
            g = PEAK_CAP / max(r["peak"], 1e-6)
        clips.setdefault(ch, {})[ver] = dict(
            file=r["file"], start_s=r["start_s"], avail_ms=r["avail_ms"],
            gain=round(g, 3), sr=r["sr"])
    json.dump(dict(chars=CHARS, voiceless=VOICELESS, voiced=VOICED, roma=ROMA, clips=clips),
              open(os.path.join(OUT_DIR, "clips.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(report, open(os.path.join(OUT_DIR, "build_report.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"完了: {len(files)+len(CHARS)} ファイル -> {OUT_DIR}", file=sys.stderr)


def _oppo(syn, ch, pitch_ln, vol, flatten=True):
    """build_1char_pool.synth_oppo と同じ「オッポ」切り出しを再現する。
    flatten=False のときは各モーラの音の高さを平坦化しない（自然音高版）。"""
    text = b1.OPPO_SPLICE[ch]
    q0 = json.loads(b2.post("/audio_query", {"text": b2.to_kata(text), "speaker": syn.speaker}))
    ms_all = []
    for ap in q0["accent_phrases"]:
        ms_all.extend(ap["moras"])
    if flatten:
        for m in ms_all:
            if m.get("pitch", 0) > 0:
                m["pitch"] = pitch_ln
    q = dict(q0)
    q["accent_phrases"] = [{"moras": ms_all, "accent": 1, "pause_mora": None, "is_interrogative": False}]
    for kk, vv in dict(speedScale=1.0, pitchScale=0.0, intonationScale=1.0, volumeScale=vol,
                       prePhonemeLength=0.1, postPhonemeLength=0.1).items():
        q[kk] = vv
    wav = b2.post("/synthesis", {"speaker": syn.speaker}, q)
    x, fr = wav_np(wav)
    t = q["prePhonemeLength"]
    for m in ms_all[:-1]:
        t += (m.get("consonant_length") or 0) + (m.get("vowel_length") or 0)
    a = int((t - 0.04) * fr)
    seg = x[a: a + int(b1.MORA_DUR * fr)].copy()
    nf = int(0.008 * fr)
    seg[-nf:] *= 0.5 * (1 + np.cos(np.pi * np.arange(nf) / nf))
    pad = np.zeros(int(0.1 * fr))
    return np_wav(np.concatenate([pad, seg, pad]), fr)


if __name__ == "__main__":
    main()
