#!/usr/bin/env python3
"""
聴覚刺激の「切り出し窓」をモーラの実体に合わせて作り直す
========================================================
これまでの切り出しは、窓の終わりを「名目のモーラ長」(manifest の char_dur_s)で
決めていた。ところが mp3 は復号すると先頭に符号化遅れが入るため、窓の始まりだけが
実測の音響的立ち上がりに合っていて、終わりは名目の位置に取り残されていた。
その結果、モーラの末尾(母音の後半)が窓の外にこぼれ落ちていた。

このスクリプトは、モーラの実体が復号後の座標のどこからどこまでかを求め、
  - onsets JSON   … かなごとに mora_avail_ms(音響的立ち上がり→モーラ末尾)などを書く
  - manifest      … 刺激ごとに gate_avail_ms(同じ意味。窓の起点は gate_onset_ms)を書く
という形で持たせる。再生側(experiment/audio1char.js, experiment/pilot_soa_audio.js)は
char_dur_s からの引き算をやめ、この値をそのまま窓の長さとして使う。

モーラ末尾をどう決めるか
------------------------
エネルギーのしきい値では、母音の減衰のどこを末尾と呼ぶかが恣意的になる。そこで
「合成時のモーラ長 + 復号遅れ」で決める。根拠は次の2つの実測である。

1. VOICEVOX の音素長は 1/93.75 秒(= 256 サンプル @24kHz = 10.6667 ミリ秒)の格子に
   量子化される。子音と母音が別々に丸められるので、0.2 秒を指定しても実際の
   モーラ長は 202.67 ミリ秒(19 フレーム)と 192.0 ミリ秒(18 フレーム)に割れる。
   前余白(prePhonemeLength=0.1 秒)も同じ格子に落ち、9 フレーム = 96.0 ミリ秒になる。
   合成 WAV の全長が (9 + 子音 + 母音 + 9) フレームちょうどになることで確かめた。
2. mp3 の符号化+復号の遅れは 1105 サンプル = 46.042 ミリ秒で、内容によらず一定である。
   同じ符号化関数(libmp3lame -q:a 4)で往復させ、原波形との相互相関の最大点で測った。

この2つから、復号後の座標での位置が決まる。
  モーラ開始 = 前余白 + 符号化遅れ
  モーラ末尾 = 前余白 + モーラ長 + 符号化遅れ
本スクリプトは、各 mp3 の復号後の全長が上の模型の予測値と一致することを確かめてから
値を書き出す(一致しなければ中断する)。エネルギーによる立ち上がり・立ち下がりの実測は
検算として表に出す。

ついでに再生ゲインも測り直す
----------------------------
窓が変われば、その中の聞こえの大きさ(A特性の実効値)も変わる。窓を作り直したあとの
区間で測り直し、中央値にそろえる増幅率を求め直す(ピーク 0.85 で頭打ち)。

実行(VOICEVOX 0.25.2 を 127.0.0.1:50021 で起動しておくこと):
  python3 experiment/tools/build_gate_windows.py --pool production
  python3 experiment/tools/build_gate_windows.py --pool slot133
"""
import argparse
import io
import json
import math
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)

ENGINE = os.environ.get("VOICEVOX_ENGINE", "http://127.0.0.1:50021")
SR = 24000
FRAME_SAMPLES = 256          # VOICEVOX の音素長の格子(10.6667 ミリ秒)
PRE_FRAMES = 9               # prePhonemeLength=0.1 秒 の量子化後(= 96.0 ミリ秒)
CODEC_DELAY_SAMPLES = 1105   # mp3 の符号化+復号の遅れ(実測。46.042 ミリ秒)
MP3_GRANULE = 576            # MPEG-2 Layer III の1フレーム(24kHz)。復号後の全長はこの倍数になる

ONSET_DBFS = -63.0           # 音響的立ち上がりの判定しきい値(build_onsets.py と同じ)
SUSTAIN_MS = 15
FRAME_MS = 5
PEAK_CAP = 0.85              # 増幅後のピーク上限(割れ防止)

OPPO_SPLICE = {"ぽ"}         # 文脈合成から切り出した音。前余白・モーラ長は Python 側で作る
OPPO_CONSONANT_S = 0.06      # synth_oppo が m_like に書く子音長(母音の始まりの目安)


# --------------------------------------------------------------------------
# VOICEVOX への問い合わせと、モーラ長の量子化
# --------------------------------------------------------------------------
def post(path, params=None, body=None):
    url = ENGINE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=60).read()


def to_kata(s):
    """ひらがな→カタカナ。単独の「は」「へ」を助詞として読ませないため(合成時と同じ)。"""
    return "".join(chr(ord(c) + 0x60) if 0x3041 <= ord(c) <= 0x3096 else c for c in s)


def phoneme_frames(ch, speaker, cmul, mora_dur_s, _cache={}):
    """合成時と同じ手順でモーラの子音長・母音長を決め、格子に量子化したフレーム数を返す。

    build_1char_pool.py の set_mora と同じ規則:
      子音長は mora_dur-0.04 で頭打ち、母音長は残り。子音と母音は別々に丸められる。
    """
    key = (ch, speaker, cmul, mora_dur_s)
    if key in _cache:
        return _cache[key]
    q = json.loads(post("/audio_query", {"text": to_kata(ch), "speaker": speaker}))
    mora = dict(q["accent_phrases"][0]["moras"][0])
    c = mora.get("consonant_length") or 0.0
    if cmul and cmul != 1.0 and c:
        c = c * cmul
    if c > mora_dur_s - 0.04:
        c = mora_dur_s - 0.04
    v = mora_dur_s - c
    fc = int(round(c * SR / FRAME_SAMPLES)) if c else 0
    fv = int(round(v * SR / FRAME_SAMPLES))
    _cache[key] = (fc, fv)
    return fc, fv


# --------------------------------------------------------------------------
# 音の解析
# --------------------------------------------------------------------------
def decode_mp3(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", path, "-f", "wav", "pipe:1"],
                       stdout=subprocess.PIPE, check=True)
    with wave.open(io.BytesIO(p.stdout), "rb") as w:
        fr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return x, fr


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


def find_offset_ms(seg, fr):
    """しきい値を最後に超えていたフレームの終わり(検算用の「音の終わり」)。"""
    db = frame_db(seg, fr)
    idx = np.where(db > ONSET_DBFS)[0]
    return int((idx[-1] + 1) * FRAME_MS) if len(idx) else 0


def a_weight(f):
    f = np.maximum(np.asarray(f, float), 1e-3)
    ra = (12194.0**2 * f**4) / ((f**2 + 20.6**2) *
          np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    ra1k = (12194.0**2 * 1000.0**4) / ((1000.0**2 + 20.6**2) *
            math.sqrt((1000.0**2 + 107.7**2) * (1000.0**2 + 737.9**2)) * (1000.0**2 + 12194.0**2))
    return ra / ra1k


def aw_rms(seg, fr):
    """A特性で重みづけした実効値(聞こえの大きさの近似)。有音部だけを集めて測る。"""
    if len(seg) < 64:
        return 1e-6
    fl = max(1, int(0.010 * fr))
    n = len(seg) // fl
    rms = np.array([np.sqrt(np.mean(seg[i*fl:(i+1)*fl]**2)) for i in range(n)]) if n else np.array([0.0])
    thr = max(rms.max() * 0.08, 1e-4)
    mask = np.repeat(rms > thr, fl)[:len(seg)]
    v = seg[:len(mask)][mask]
    if len(v) < 64:
        return 1e-6
    F = np.fft.rfft(v * np.hanning(len(v)))
    freqs = np.fft.rfftfreq(len(v), 1.0 / fr)
    return float(np.sqrt(np.sum(np.abs(F * a_weight(freqs))**2)) / len(v) * math.sqrt(2))


# --------------------------------------------------------------------------
# 本体
# --------------------------------------------------------------------------
POOLS = {
    "production": dict(pool_tag="cand108", base=EXP, mora_dur_s=0.2, speaker=108),
    "slot133": dict(pool_tag="slot133", base=os.path.join(EXP, "candidate_pools", "slot133"),
                    mora_dur_s=13 / 93.75, speaker=108),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", choices=sorted(POOLS), default="production")
    ap.add_argument("--dry-run", action="store_true", help="書き出さずに表だけ出す")
    ap.add_argument("--report", default=None, help="実測表をJSONで書き出す先")
    args = ap.parse_args()

    cfg = POOLS[args.pool]
    base = cfg["base"]
    manifest_path = os.path.join(base, "audio1char_manifest.json")
    onsets_path = os.path.join(base, "audio1char_onsets.json")
    stim_dir = os.path.join(base, "audio1char_stimuli")

    manifest = json.load(open(manifest_path))
    onsets_old = json.load(open(onsets_path))
    answer_key = json.load(open(os.path.join(EXP, "answer_key_merged.json")))
    id2ch, cmul_of = {}, {}
    for k, v in answer_key.items():
        if k.startswith("audio1char|") and v.get("pool") == cfg["pool_tag"]:
            id2ch[k.split("|")[1]] = v["char"]
            cmul_of[v["char"]] = v.get("vot_cmul")

    mora_dur_s = cfg["mora_dur_s"]
    delay_ms = CODEC_DELAY_SAMPLES / SR * 1000
    rows = []
    for stim in manifest["stimuli"]:
        ch = id2ch.get(stim["id"])
        if ch is None:
            sys.exit(f"かなの対応が取れない刺激がある: {stim['id']}")
        x, fr = decode_mp3(os.path.join(stim_dir, stim["file"]))
        if fr != SR:
            sys.exit(f"{ch}: 標本化周波数が {fr} で想定と違う")

        # --- モーラの実体の位置(復号後の座標, ミリ秒) ---
        if ch in OPPO_SPLICE:
            # 文脈合成の切り出し。前余白もモーラ長も Python 側で整数サンプルとして作った。
            pre_n = int(0.1 * SR)
            mora_n = int(mora_dur_s * SR)
            cons_n = int(OPPO_CONSONANT_S * SR)
            wav_n = pre_n + mora_n + int(0.1 * SR)
            fc = fv = None
        else:
            fc, fv = phoneme_frames(ch, cfg["speaker"], cmul_of.get(ch), mora_dur_s)
            pre_n = PRE_FRAMES * FRAME_SAMPLES
            mora_n = (fc + fv) * FRAME_SAMPLES
            cons_n = fc * FRAME_SAMPLES
            wav_n = (PRE_FRAMES + fc + fv + PRE_FRAMES) * FRAME_SAMPLES

        # 模型の検算: 復号後の全長は (合成WAV長 + 遅れ) を mp3 の1フレームに切り上げた値になる
        dec_expect = math.ceil((wav_n + CODEC_DELAY_SAMPLES) / MP3_GRANULE) * MP3_GRANULE
        if len(x) != dec_expect:
            sys.exit(f"{ch}: 復号後の長さ {len(x)} が模型の予測 {dec_expect} と違う。"
                     f"モーラ長の求め方が合っていない可能性がある")

        mora_start_ms = (pre_n + CODEC_DELAY_SAMPLES) / SR * 1000
        mora_end_ms = (pre_n + mora_n + CODEC_DELAY_SAMPLES) / SR * 1000
        vowel_start_ms = (pre_n + cons_n + CODEC_DELAY_SAMPLES) / SR * 1000

        # --- 窓の起点(音響的立ち上がり)。検出の規則は従来と同じ ---
        seg_from_slot = x[int(stim["char_onset_s"] * SR): int(round(mora_end_ms / 1000 * SR))]
        onset_ms = find_onset_ms(seg_from_slot, SR)
        offset_ms = find_offset_ms(x[int(stim["char_onset_s"] * SR):], SR)
        win_start_ms = stim["char_onset_s"] * 1000 + onset_ms          # onsets 側(5ms格子)
        gate_onset_ms = int(round(onset_ms / 10.0)) * 10               # manifest 側(10ms格子)
        gate_start_ms = stim["char_onset_s"] * 1000 + gate_onset_ms

        # --- 新旧の窓 ---
        old_end_ms = stim["char_onset_s"] * 1000 + stim["char_dur_s"] * 1000   # 名目のスロット末
        new_end_ms = mora_end_ms
        a = int(round(win_start_ms / 1000 * SR))
        b = int(round(new_end_ms / 1000 * SR))
        played = x[a:b]
        rows.append(dict(
            ch=ch, id=stim["id"], fc=fc, fv=fv, mora_len_ms=mora_n / SR * 1000,
            mora_start_ms=mora_start_ms, mora_end_ms=mora_end_ms, vowel_start_ms=vowel_start_ms,
            acoustic_onset_ms=onset_ms, gate_onset_ms=gate_onset_ms,
            win_start_ms=win_start_ms, gate_start_ms=gate_start_ms,
            old_end_ms=old_end_ms, new_end_ms=new_end_ms,
            meas_rise_ms=stim["char_onset_s"] * 1000 + onset_ms,
            meas_fall_ms=stim["char_onset_s"] * 1000 + offset_ms,
            awrms=aw_rms(played, SR), peak=float(np.abs(played).max()) if len(played) else 0.0,
            old_gain=onsets_old.get(ch, {}).get("gain"),
            old_gate_gain=stim.get("gate_gain"),
        ))

    # --- 聞こえの大きさをそろえる増幅率を、新しい窓で測り直す ---
    target = float(np.median([r["awrms"] for r in rows]))
    for r in rows:
        gain = target / max(r["awrms"], 1e-6)
        if r["peak"] * gain > PEAK_CAP:
            gain = PEAK_CAP / max(r["peak"], 1e-6)
        r["gain"] = round(gain, 3)
        r["gate_gain"] = round(gain, 1)

    if args.report:
        json.dump(rows, open(args.report, "w"), ensure_ascii=False, indent=1)

    # --- 書き出し ---
    if not args.dry_run:
        onsets_new = {}
        for r in sorted(rows, key=lambda r: r["ch"]):
            onsets_new[r["ch"]] = dict(
                acoustic_onset_ms=int(r["acoustic_onset_ms"]),
                voiced_end_ms=int(round(r["meas_fall_ms"] - 100)),   # 従来の意味(スロット先頭からのms)を保つ
                mora_len_ms=round(r["mora_len_ms"], 3),
                mora_end_ms=round(r["mora_end_ms"], 3),
                mora_avail_ms=round(r["mora_end_ms"] - r["win_start_ms"], 3),
                gain=r["gain"],
            )
        onsets_new["_meta"] = dict(
            note=("mora_avail_ms = 音響的立ち上がり(char_onset_s + acoustic_onset_ms)から"
                  "モーラ末尾までの長さ(ミリ秒)。再生側はこの値を窓の長さに使う。"
                  "mora_end_ms は復号後のファイル先頭から数えたモーラ末尾の位置。"),
            codec_delay_ms=round(delay_ms, 3),
            pre_phoneme_ms=round(PRE_FRAMES * FRAME_SAMPLES / SR * 1000, 3),
            frame_ms=round(FRAME_SAMPLES / SR * 1000, 4),
            aw_rms_target=round(target, 6),
        )
        json.dump(onsets_new, open(onsets_path, "w"), ensure_ascii=False, indent=1)

        by_id = {r["id"]: r for r in rows}
        for stim in manifest["stimuli"]:
            r = by_id[stim["id"]]
            stim["gate_onset_ms"] = r["gate_onset_ms"]
            stim["gate_avail_ms"] = round(r["mora_end_ms"] - r["gate_start_ms"], 3)
            stim["gate_gain"] = r["gate_gain"]
            stim["mora_len_ms"] = round(r["mora_len_ms"], 3)
        manifest["codec_delay_ms"] = round(delay_ms, 3)
        manifest["gate_note"] = ("gate_avail_ms = 窓の起点(char_onset_s + gate_onset_ms)から"
                                 "モーラ末尾までの長さ(ミリ秒)。再生側は char_dur_s から引き算せず、"
                                 "この値を窓の長さに使う。")
        json.dump(manifest, open(manifest_path, "w"), ensure_ascii=False, indent=1)

    # --- 表示 ---
    order = sorted(rows, key=lambda r: r["new_end_ms"] - r["old_end_ms"], reverse=True)
    print(f"[{args.pool}] n={len(rows)}  復号遅れ={delay_ms:.3f}ms  "
          f"前余白(量子化後)={PRE_FRAMES * FRAME_SAMPLES / SR * 1000:.1f}ms", file=sys.stderr)
    import collections
    print("モーラ長の分布: " + ", ".join(
        f"{k}ms×{v}" for k, v in sorted(collections.Counter(round(r["mora_len_ms"], 2) for r in rows).items())),
        file=sys.stderr)
    print(f"窓の末尾のずれ(新-旧): 最大 {order[0]['new_end_ms'] - order[0]['old_end_ms']:+.2f}ms "
          f"({order[0]['ch']}) / 最小 {order[-1]['new_end_ms'] - order[-1]['old_end_ms']:+.2f}ms "
          f"({order[-1]['ch']})", file=sys.stderr)
    gains = sorted(r["gain"] for r in rows)
    print(f"増幅率: {gains[0]:.3f}〜{gains[-1]:.3f} (中央 {gains[len(gains)//2]:.3f})", file=sys.stderr)
    print("検算(エネルギー実測 vs 模型): "
          + ", ".join(f"{r['ch']}:立上{r['meas_rise_ms']:.0f}/終り{r['meas_fall_ms']:.0f}"
                      f"(モーラ{r['mora_start_ms']:.0f}-{r['mora_end_ms']:.0f})"
                      for r in rows[:5]), file=sys.stderr)
    if args.dry_run:
        print("(dry-run: ファイルは書き換えていない)", file=sys.stderr)
    else:
        print(f"書き出し: {onsets_path}\n          {manifest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
