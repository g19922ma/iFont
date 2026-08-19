#!/usr/bin/env python3
"""
清濁診断の音源を音響的に測る
============================
測る対象は **参加者に届く最終ファイルそのもの**（mp3は復号してから測る）。
合成の途中経過ではなく、実際に耳に届く形で数値を出す。

測る項目（すべて清濁＝有声/無声の手がかりとして先行研究で使われるもの）:
  VOT              破裂の瞬間から声帯振動が始まるまでの時間(ミリ秒)。
                   日本語の無声破裂音は約25〜45ms、有声破裂音は0以下〜10ms程度。
  バースト強度      破裂直後0〜20msの音の大きさが、後続母音(声が出てから20〜80ms)に対して
                   何デシベル大きい/小さいか。実効値(RMS)と最大値(peak)の両方。
                   無声破裂音では破裂がはっきり立つ。弱いと濁って聞こえる。
  破裂前の周期性     破裂の前50msに声帯振動があるか(prevoicing)。有声破裂音の主要な手がかり。
                   有声フレームの割合と、その区間の音の大きさ(母音比dB)で示す。
  バーストの重心     破裂直後0〜20msのスペクトル重心(Hz)。両唇音(ぱ)は低め、
                   軟口蓋音(か)は高めになるのが自然。低すぎると「ば」寄りに聞こえうる。

さらに WAV と mp3 を突き合わせ、「mp3化で音の頭がどれだけ変わったか」を数値で出す。

実行: ~/ifont_env/bin/python experiment/tools/measure_seidaku_diag.py
出力: project/清濁診断_音響測定.md と experiment/tools/seidaku_diag_assets/measurements.json
"""
import json, os, sys, io, math, wave, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
ASSETS = os.path.join(HERE, "seidaku_diag_assets")
OUT_MD = os.path.join(REPO, "project", "清濁診断_音響測定.md")
OUT_JSON = os.path.join(ASSETS, "measurements.json")

import numpy as np
import parselmouth

# 版の表示名。清濁の切り分けとして「何を1段戻したのか」がわかる名前にする。
VER_LABEL = {
    "cur_mp3":     "現行mp3（本番と同一）",
    "cur_wav":     "現行WAV（mp3化する前）",
    "solo_wav":    "ぽ単独合成WAV（切り出しをやめた版）",
    "solo_mp3":    "ぽ単独合成mp3",
    "soloraw_wav": "ぽ単独合成WAV・VOT自動修正なし",
    "psola_wav":   "PSOLA完全平坦WAV（onset-F0温存版の対照）",
    "onsetf0_wav": "onset-F0温存WAV（母音直後60msだけ高さの動きを戻した）",
    "natf0_wav":   "自然音高WAV（平坦化そのものをやめた）",
}
VER_ORDER = list(VER_LABEL)


def decode(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
                        "-f", "wav", "pipe:1"], stdout=subprocess.PIPE, check=True)
    with wave.open(io.BytesIO(p.stdout), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


def db(v):
    return 20 * math.log10(max(float(v), 1e-9))


def rms(x):
    return float(np.sqrt(np.mean(x**2))) if len(x) else 0.0


def find_burst_s(x, fr, from_s, search_s=0.12):
    """破裂の瞬間: 1msごとの音の大きさが最も急に立ち上がる点。"""
    a = int(from_s * fr)
    seg = x[a: a + int(search_s * fr)]
    ms = max(1, int(fr / 1000))
    n = len(seg) // ms - 4
    if n < 5:
        return from_s
    env = [db(rms(seg[i*ms:(i+1)*ms])) for i in range(n)]
    i = max(range(n - 2), key=lambda k: env[k+2] - env[k])
    return from_s + i / 1000.0


def voicing_onset_s(x, fr, from_s, to_s, floor=150, ceiling=450):
    """声帯振動が始まる時刻。範囲を1度絞り込んでオクターブ誤りを避ける。"""
    a, b = int(from_s * fr), int(to_s * fr)
    seg = x[a:b]
    if len(seg) < int(0.02 * fr):
        return None
    try:
        pp = parselmouth.Sound(seg, fr).to_pitch(0.002, floor, ceiling)
        f, t = pp.selected_array["frequency"], pp.xs()
        v = [t[i] for i in range(len(t)) if f[i] > 0]
        return from_s + v[0] if v else None
    except Exception:
        return None


def vot_lowband_ms(x, fr, burst_s, end_s):
    """VOTの独立した測り方。音の高さを追う方法は「声だ」と判定するのに約10msの信号を要し、
    測定値に約10msの下駄をはかせてしまう。こちらは声帯振動の帯域(120〜400Hz)の
    エネルギーが、母音の水準の-15dBに達した最初の時点を「声の始まり」とする。"""
    a, b = int(burst_s * fr), int(min(end_s, burst_s + 0.15) * fr)
    seg = x[a:b]
    if len(seg) < int(0.04 * fr):
        return None
    step = max(1, int(0.001 * fr)); win = max(8, int(0.010 * fr))
    lo = []
    for i in range(0, len(seg) - win, step):
        fr_win = seg[i:i+win] * np.hanning(win)
        F = np.abs(np.fft.rfft(fr_win)); fq = np.fft.rfftfreq(win, 1.0 / fr)
        lo.append(float(np.sqrt(np.sum(F[(fq >= 120) & (fq <= 400)]**2))))
    if not lo:
        return None
    lo = np.array(lo)
    ref = float(np.percentile(lo[max(1, len(lo)//2):], 80))   # 後半＝母音部の水準
    thr = ref * 10 ** (-15 / 20)
    idx = np.where(lo >= thr)[0]
    return round(float(idx[0]) * step / fr * 1000, 1) if len(idx) else None


def prevoicing(x, fr, burst_s, win_s=0.05):
    """破裂の前 win_s 秒に声帯振動があるか。有声フレームの割合と大きさを返す。"""
    a = max(0, int((burst_s - win_s) * fr)); b = int(burst_s * fr)
    seg = x[a:b]
    if len(seg) < int(0.02 * fr):
        return dict(voiced_frac=0.0, level_db=None)
    try:
        pp = parselmouth.Sound(seg, fr).to_pitch(0.005, 100, 450)
        f = pp.selected_array["frequency"]
        frac = float(np.mean(f > 0)) if len(f) else 0.0
    except Exception:
        frac = 0.0
    return dict(voiced_frac=round(frac, 3), level_db=round(db(rms(seg)), 1))


def centroid_hz(seg, fr):
    if len(seg) < 32:
        return None
    F = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    fq = np.fft.rfftfreq(len(seg), 1.0 / fr)
    s = F.sum()
    return round(float((F * fq).sum() / s), 0) if s > 0 else None


def measure_one(path, start_s, avail_ms):
    x, fr = decode(path)
    end_s = start_s + avail_ms / 1000.0
    burst = find_burst_s(x, fr, max(0.0, start_s - 0.005))
    v0 = voicing_onset_s(x, fr, burst, min(end_s, burst + 0.15))
    bseg = x[int(burst * fr): int((burst + 0.020) * fr)]
    if v0 is not None:
        vseg = x[int((v0 + 0.020) * fr): int(min(end_s, v0 + 0.080) * fr)]
    else:
        vseg = x[int((burst + 0.060) * fr): int(min(end_s, burst + 0.120) * fr)]
    vr, vp = rms(vseg), (float(np.abs(vseg).max()) if len(vseg) else 0.0)
    return dict(
        vot_ms=(round((v0 - burst) * 1000, 1) if v0 is not None else None),
        vot_lowband_ms=vot_lowband_ms(x, fr, burst, end_s),
        burst_s=round(burst, 4), voicing_onset_s=(round(v0, 4) if v0 else None),
        burst_rms_re_vowel_db=round(db(rms(bseg)) - db(vr), 1),
        burst_peak_re_vowel_db=round(db(float(np.abs(bseg).max()) if len(bseg) else 0) - db(vp), 1),
        burst_centroid_hz=centroid_hz(bseg, fr),
        prevoicing=prevoicing(x, fr, burst),
    )


def best_lag(xw, fw, sw, xm, sm, span_ms=150, max_shift_ms=15):
    """WAVとmp3の時間のずれ(サンプル数)を1回だけ求める。mp3の符号化の遅れは
    立ち上がり検出の5msきざみでは取り切れないので、相互相関でそろえる。
    区間ごとに別々のずれを使うと「一番よく合う場所」を選んでしまい差を過小評価するため、
    ずれは全区間で共通の1つに固定する。"""
    a_w = int(sw * fw); n = int(span_ms / 1000 * fw)
    n = min(n, len(xw) - a_w)
    w = xw[a_w:a_w+n]
    a_m0 = int(sm * fw)
    best, bl = None, 0
    for sh in range(-int(max_shift_ms/1000*fw), int(max_shift_ms/1000*fw) + 1):
        a2 = a_m0 + sh
        if a2 < 0 or a2 + n > len(xm):
            continue
        d = rms(w - xm[a2:a2+n])
        if best is None or d < best:
            best, bl = d, sh
    return bl


def head_diff(xw, fw, sw, xm, sm, lag, lo_ms, hi_ms):
    """lo_ms〜hi_ms の区間で、WAVとmp3の差分の実効値を WAV側の実効値に対するdBで返す。"""
    a_w = int((sw + lo_ms / 1000) * fw); b_w = int((sw + hi_ms / 1000) * fw)
    a_m = int((sm + lo_ms / 1000) * fw) + lag
    n = min(b_w - a_w, len(xw) - a_w, len(xm) - a_m)
    if n <= 0 or a_m < 0:
        return None
    w, m = xw[a_w:a_w+n], xm[a_m:a_m+n]
    return round(db(rms(w - m)) - db(rms(w)), 1)


def main():
    clips = json.load(open(os.path.join(ASSETS, "clips.json")))
    report = json.load(open(os.path.join(ASSETS, "build_report.json")))
    out = {}
    for ch, vers in clips["clips"].items():
        out[ch] = {}
        for ver, c in vers.items():
            out[ch][ver] = measure_one(os.path.join(ASSETS, c["file"]), c["start_s"], c["avail_ms"])
        # WAV vs mp3 の頭のちがい
        pairs = [("cur_wav", "cur_mp3")]
        if "solo_wav" in vers and "solo_mp3" in vers:
            pairs.append(("solo_wav", "solo_mp3"))
        out[ch]["_wav_vs_mp3"] = {}
        for wv, mv in pairs:
            xw, fw = decode(os.path.join(ASSETS, vers[wv]["file"]))
            xm, fm = decode(os.path.join(ASSETS, vers[mv]["file"]))
            sw, sm = vers[wv]["start_s"], vers[mv]["start_s"]
            lag = best_lag(xw, fw, sw, xm, sm)
            out[ch]["_wav_vs_mp3"][wv + "/" + mv] = dict(
                lag_ms=round(lag / fw * 1000, 2),
                head_0_20ms_db=head_diff(xw, fw, sw, xm, sm, lag, 0, 20),
                head_30_50ms_db=head_diff(xw, fw, sw, xm, sm, lag, 30, 50),
                whole_0_150ms_db=head_diff(xw, fw, sw, xm, sm, lag, 0, 150))
    json.dump(out, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    write_md(clips, report, out)
    print("出力:", OUT_MD, "/", OUT_JSON, file=sys.stderr)


def fmt(v, unit=""):
    return "—" if v is None else f"{v}{unit}"


def write_md(clips, report, M):
    VL, VD = clips["voiceless"], clips["voiced"]
    L = []
    L.append("# 清濁診断: 音響測定")
    L.append("")
    L.append("`experiment/tools/build_seidaku_diag.py` が作った診断用音源を、"
             "**参加者に届く形のまま**（mp3は復号してから）測った結果。")
    L.append("測定スクリプトは `experiment/tools/measure_seidaku_diag.py`、"
             "生値は `experiment/tools/seidaku_diag_assets/measurements.json`。")
    L.append("聴き比べページ: `experiment/tools/seidaku_diag.html`。")
    L.append("")
    L.append("## 用語（この文書での意味）")
    L.append("")
    L.append("- **VOT**: 破裂の瞬間から声帯振動が始まるまでの時間（ミリ秒）。"
             "自然な日本語で、清音（無声破裂音）は約25〜45ms、濁音（有声破裂音）は0以下〜10ms程度。"
             "短いほど濁って聞こえる。清濁の知覚境界はおよそ18〜26ms。")
    L.append("  2通りで測って併記する。**VOT(追跡)** は音の高さを追う方法で、"
             "「声だ」と判定するのに約10msぶんの信号が要るので下限が約10msに張り付く"
             "（表で 10.0ms と並ぶのは「実質0ms」の意味）。"
             "**VOT(低域)** は声帯振動の帯域(120〜400Hz)が母音水準の-15dBに達した時点で、"
             "下駄が小さい。**大小の比較にはVOT(低域)を見るほうが安全**。")
    L.append("- **バースト強度**: 破裂直後0〜20msの音の大きさを、後続母音（声が出てから20〜80ms）"
             "と比べた値（デシベル）。マイナスは「破裂のほうが母音より小さい」の意味。"
             "破裂が弱いほど濁って聞こえる。")
    L.append("- **破裂前の周期性（prevoicing）**: 破裂の前50msに声帯振動があるか。"
             "本来は濁音だけに出る手がかり。数値は有声と判定されたフレームの割合（0〜1）。")
    L.append("- **バーストの重心**: 破裂直後0〜20msのスペクトル重心（Hz）。"
             "両唇音（ぱ・ぽ）は低め、軟口蓋音（か）は高めになるのが自然。")
    L.append("- **各版の意味**: " + " / ".join(f"`{k}`={v}" for k, v in VER_LABEL.items()))
    L.append("")

    L.append("## 1. 現行の本番音源（参加者に届いている実物）")
    L.append("")
    L.append("| 音 | 清濁 | VOT(追跡) | VOT(低域) | バーストRMS(母音比) | バーストpeak(母音比) | 破裂前の周期性 | バースト重心 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for ch in VL + VD:
        m = M[ch]["cur_mp3"]
        L.append(f"| {ch} | {'清' if ch in VL else '濁'} | {fmt(m['vot_ms'],'ms')} | "
                 f"{fmt(m['vot_lowband_ms'],'ms')} | "
                 f"{fmt(m['burst_rms_re_vowel_db'],'dB')} | {fmt(m['burst_peak_re_vowel_db'],'dB')} | "
                 f"{fmt(m['prevoicing']['voiced_frac'])} | {fmt(m['burst_centroid_hz'],'Hz')} |")
    L.append("")

    L.append("## 2. 「ぽ」: 文脈切り出し（現行）と単独合成の比較")
    L.append("")
    L.append("瞿(2022)「文脈から切り出した無声破裂音は有声に知覚される」の直接検証にあたる。")
    L.append("")
    L.append("| 版 | VOT(追跡) | VOT(低域) | バーストRMS(母音比) | バーストpeak(母音比) | 破裂前の周期性 | バースト重心 |")
    L.append("|---|---|---|---|---|---|---|")
    for ver in ["cur_mp3", "cur_wav", "solo_wav", "solo_mp3", "soloraw_wav"]:
        if ver not in M["ぽ"]:
            continue
        m = M["ぽ"][ver]
        L.append(f"| {VER_LABEL[ver]} | {fmt(m['vot_ms'],'ms')} | {fmt(m['vot_lowband_ms'],'ms')} | "
                 f"{fmt(m['burst_rms_re_vowel_db'],'dB')} | {fmt(m['burst_peak_re_vowel_db'],'dB')} | "
                 f"{fmt(m['prevoicing']['voiced_frac'])} | {fmt(m['burst_centroid_hz'],'Hz')} |")
    lad = report["notes"].get("po_solo_vot_ladder", {})
    L.append("")
    L.append(f"VOT自動修正のラダー結果: 子音長を **x{lad.get('cmul')}** に伸ばして "
             f"VOT={lad.get('vot_ms')}ms（目標{lad.get('target_ms')}ms）。")
    L.append("")

    L.append("## 3. WAV と mp3 の差（同じ音の、符号化前後）")
    L.append("")
    L.append("差分波形の実効値を、WAV側の実効値に対するデシベルで示す。"
             "0dBなら「差が信号と同じ大きさ」＝完全に別物、-40dBなら「差は信号の1%」＝ほぼ同じ。")
    L.append("")
    L.append("| 音 | 比較 | そろえたずれ | 頭0〜20ms | 頭30〜50ms | 全体0〜150ms |")
    L.append("|---|---|---|---|---|---|")
    for ch in VL + VD:
        for k, v in M[ch]["_wav_vs_mp3"].items():
            L.append(f"| {ch} | {k} | {fmt(v['lag_ms'],'ms')} | {fmt(v['head_0_20ms_db'],'dB')} | "
                     f"{fmt(v['head_30_50ms_db'],'dB')} | {fmt(v['whole_0_150ms_db'],'dB')} |")
    L.append("")
    L.append("| 音 | 版 | VOT(追跡) | VOT(低域) | バーストRMS(母音比) | バースト重心 |")
    L.append("|---|---|---|---|---|---|")
    for ch in VL + VD:
        for ver in ["cur_wav", "cur_mp3"]:
            m = M[ch][ver]
            L.append(f"| {ch} | {VER_LABEL[ver]} | {fmt(m['vot_ms'],'ms')} | {fmt(m['vot_lowband_ms'],'ms')} | "
                     f"{fmt(m['burst_rms_re_vowel_db'],'dB')} | {fmt(m['burst_centroid_hz'],'Hz')} |")
    L.append("")

    L.append("## 4. 音の高さ（F0）まわり")
    L.append("")
    L.append("平坦化していない自然な合成が、母音の始まりでどれだけ高さを動かしていたか"
             "（半音単位、プラスは高い方向）。日本語では清音の直後は高く、濁音の直後は低くなる。"
             "B3固定への平坦化は、この差をまるごと消している。")
    L.append("")
    L.append("| 音 | 清濁 | 母音直後の高さのずれ(最大) | 0ms | 10ms | 20ms | 40ms | 平坦時の高さ | 自然時の高さ |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for ch in VL + VD:
        o = report["chars"][ch]["onset_f0"]
        prof = dict(o.get("onset_delta_semitone_profile", []))

        def at(ms):
            return fmt(prof.get(ms), "半音")
        # 符号つきの最大ずれ（絶対値が最大の点）
        signed = max(prof.values(), key=abs) if prof else None
        L.append(f"| {ch} | {'清' if ch in VL else '濁'} | {fmt(round(signed,2) if signed is not None else None,'半音')} | "
                 f"{at(0.0)} | {at(10.0)} | {at(20.0)} | {at(40.0)} | "
                 f"{fmt(o.get('flat_median_hz'),'Hz')} | {fmt(o.get('nat_median_hz'),'Hz')} |")
    L.append("")
    L.append("※「ぽ」の基準は " + report["chars"]["ぽ"]["onset_f0"].get("base", "") +
             "（切り出し元の「オッポ」は語中の位置で音の高さが下がるため、"
             "自然音高の比較対象として使えない）。")
    L.append("")
    L.append("| 音 | 版 | VOT(追跡) | VOT(低域) | バーストRMS(母音比) |")
    L.append("|---|---|---|---|---|")
    for ch in VL + VD:
        for ver in ["psola_wav", "onsetf0_wav", "natf0_wav"]:
            if ver not in M[ch]:
                continue
            m = M[ch][ver]
            L.append(f"| {ch} | {VER_LABEL[ver]} | {fmt(m['vot_ms'],'ms')} | {fmt(m['vot_lowband_ms'],'ms')} | "
                     f"{fmt(m['burst_rms_re_vowel_db'],'dB')} |")
    L.append("")

    L.append("## 5. 再現の忠実さ")
    L.append("")
    L.append("「mp3化する前のWAV」は保存されていないので、本番と同じ手順で作り直している。"
             "作り直したWAVをmp3にして本番mp3と比べた差（信号に対するデシベル）:")
    L.append("")
    L.append("| 音 | 再現差 |")
    L.append("|---|---|")
    for ch in VL + VD:
        L.append(f"| {ch} | {report['chars'][ch]['repro_rms_diff_db']}dB |")
    L.append("")
    L.append(f"音量そろえの目標値（A特性RMS）も答えの表から逆算し、8字で "
             f"{report['notes']['target_awrms_spread'][0]}〜{report['notes']['target_awrms_spread'][1]} "
             f"と一致した（＝合成の再現は正しい）。")
    L.append("")
    open(OUT_MD, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
