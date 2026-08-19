#!/usr/bin/env python3
"""
音源比較セット raw_compare_v1 のビルダー（無加工の合成音を作る）
================================================================
研究方針の転換にともなう資材づくり。これまでの独自加工
（声の高さの平坦化・1文字0.2秒への強制伸縮・VOTの自動修正・文脈語からの切り出し・
字ごとのフィルタ）を **いっさい行わず**、合成器が出したそのままの音を並べて聴き比べる。

作るもの（12字 × 話者2種）
  B1_<かな>.wav   東北きりたん（speaker=108／現行の本番プールと同じ話者）
  B2_<かな>.wav   玄野武宏 ノーマル（speaker=11／声質の明らかに違う男声）
  C_<かな>.mp3    現行の本番プール（experiment/audio1char_stimuli）からの参照コピー

無加工であることの中身（ここを破ると比較の意味がなくなる）
  * /audio_query が返した内容を **1か所を除いてそのまま** /synthesis に渡す。
    唯一変えるのは outputSamplingRate（合成器の出力標本化周波数）を 44100 Hz にする点だけ。
    これは合成器の出力設定であって、音の高さ・長さ・音量・音素のならびには触れない。
  * speedScale / pitchScale / intonationScale / volumeScale / 各モーラの長さと高さは既定のまま。
  * prePhonemeLength / postPhonemeLength も既定のまま（前後に約0.1秒の無音が入る）。
  * フェード（音の出入りをなめらかにする処理）は掛けない。
  * 文脈語（「オッポ」など）からの切り出しはしない。1字だけを単独で読ませる。

音量そろえ（レベル合わせ）
  話者ごとに **たった1つの倍率** を全12字に掛けるだけ。字ごとに変えない。
  時間とともに変化する正規化（コンプレッサ等）は使わない。
  破裂直後の音の大きさは清音か濁音かを聞き分ける手がかりなので、
  信号の中の相対的な振幅の関係を絶対に変えてはいけないため。
  倍率は「12字の実効値(RMS)の中央値が参照値に合う」ように決め、
  そのうえで12字のどれも最大振幅が -1 dBFS を超えないよう必要なら下げる。

出力先: experiment/candidate_pools/raw_compare_v1/
  ここは新規ディレクトリ。既存の本番プールや candidate_pools/uniform200 には触れない。

実行（VOICEVOX を localhost:50021 で起動しておく）:
  ~/ifont_env/bin/python experiment/tools/build_raw_compare.py
"""
import argparse
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
sys.path.insert(0, HERE)

import rawcompare_measure_lib as L  # noqa: E402

ENGINE = os.environ.get("VOICEVOX_ENGINE", "http://127.0.0.1:50021")
OUT_DIR = os.path.join(EXP, "candidate_pools", "raw_compare_v1")
PROD_STIM = os.path.join(EXP, "audio1char_stimuli")
PROD_MANIFEST = os.path.join(EXP, "audio1char_manifest.json")
ANSWER_KEY = os.path.join(EXP, "answer_key_merged.json")

CHARS = ["あ", "い", "か", "が", "ぱ", "ば", "た", "だ", "し", "す", "ま", "な"]

# 話者。B1 は現行と同じ、B2 は声質が明らかに違うものを実測で選んだ（下の選定理由を参照）
SPEAKERS = {
    "B1": dict(id=108, name="東北きりたん", style="ノーマル",
               why="現行の本番プールと同じ話者。比較の基準"),
    "B2": dict(id=11, name="玄野武宏", style="ノーマル",
               why=("声の高さが約104Hzの男声で、きりたん(約229Hz)とほぼ1オクターブ違う。"
                    "無加工の下見で、が・ば・だ のいずれにも prevoicing（破裂より前から"
                    "声帯が震える。濁音と聞き取るいちばん強い手がかり）がはっきり出て、"
                    "か・ぱ・た は日本語の無声破裂音として自然な +23〜+42ミリ秒に収まった。"
                    "清音と濁音の VOT の開きは最小でも84ミリ秒で、試した7話者の中で最大")),
}

TARGET_PEAK_DBFS = -1.0   # どの字もこの最大振幅を超えないようにする安全余裕


def post(path, params=None, body=None):
    url = ENGINE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=h, method="POST"), timeout=120).read()


def get(path):
    with urllib.request.urlopen(ENGINE + path, timeout=30) as r:
        return json.loads(r.read())


def to_kata(s):
    """ひらがな→カタカナ。VOICEVOX は単独の「は」「へ」を助詞として /wa/ /e/ と読むため、
    カタカナで問い合わせて字の通りの読みを得る。今回の12字には該当しないが同じ流儀に合わせる。"""
    return "".join(chr(ord(c) + 0x60) if 0x3041 <= ord(c) <= 0x3096 else c for c in s)


def synth_raw(char, speaker_id, sr=44100):
    """無加工の合成。audio_query の中身は outputSamplingRate 以外いっさい変えない。"""
    q = json.loads(post("/audio_query", {"text": to_kata(char), "speaker": speaker_id}))
    q["outputSamplingRate"] = sr
    wav = post("/synthesis", {"speaker": speaker_id}, q)
    return wav, q


def load_prod_map():
    """現行本番プール: かな -> mp3 のパス。"""
    man = json.load(open(PROD_MANIFEST))
    ak = json.load(open(ANSWER_KEY))
    by_id = {s["id"]: s for s in man["stimuli"]}
    out = {}
    for key, v in ak.items():
        mod, sid = key.split("|", 1)
        if mod != "audio1char" or sid not in by_id:
            continue
        ch = v.get("char")
        if ch in CHARS:
            out[ch] = dict(path=os.path.join(PROD_STIM, by_id[sid]["file"]),
                           stim=by_id[sid], answer=v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sr", type=int, default=44100)
    args = ap.parse_args()

    ver = get("/version")
    print(f"VOICEVOX {ver} / 出力 {args.sr}Hz 16bit / {len(CHARS)}字 × {len(SPEAKERS)}話者")
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---------------------------------------------------------- C版（現行加工版）を参照コピー
    prod = load_prod_map()
    missing = [c for c in CHARS if c not in prod]
    if missing:
        print(f"  ! 本番プールに見つからない字: {missing}")
    c_rec = {}
    for ch in CHARS:
        if ch not in prod:
            continue
        src = prod[ch]["path"]
        ext = os.path.splitext(src)[1]
        dst = os.path.join(OUT_DIR, f"C_{ch}{ext}")
        shutil.copyfile(src, dst)
        x, fr = L.decode(dst)
        c_rec[ch] = dict(file=os.path.basename(dst), src=os.path.relpath(src, REPO),
                         gain=1.0, note="現行本番プールのファイルをそのままコピー（再加工なし）",
                         prod_stim=prod[ch]["stim"], active_rms_dbfs=L.active_rms_dbfs(x, fr))
        print(f"  C {ch}  <- {os.path.relpath(src, REPO)}")

    # C版の実効値の中央値を、B版のレベル合わせの参照にする
    ref_rms = float(np.median([v["active_rms_dbfs"] for v in c_rec.values()])) if c_rec else -20.0
    print(f"\nレベル合わせの参照値 = 現行加工版12字の実効値の中央値 {ref_rms:.2f} dBFS")

    # ---------------------------------------------------------- B版（無加工の合成）
    manifest = dict(
        set="raw_compare_v1",
        engine=f"VOICEVOX {ver}",
        sample_rate=args.sr, bit_depth=16, channels=1,
        chars=CHARS,
        processing_note=(
            "B1/B2 は audio_query の内容を outputSamplingRate 以外いっさい変えずに合成した無加工音。"
            "声の高さの平坦化・長さの強制・VOT修正・フィルタ・切り出し・フェードはすべて行っていない。"
            "音量そろえは話者ごとに単一の倍率を全12字へ一律に掛けただけ。"),
        level_reference_dbfs=round(ref_rms, 2),
        target_peak_dbfs=TARGET_PEAK_DBFS,
        speakers={}, files={},
    )

    for col, sp in SPEAKERS.items():
        raws = {}
        for ch in CHARS:
            wav, q = synth_raw(ch, sp["id"], args.sr)
            x, fr = L.wav_bytes_to_np(wav)
            raws[ch] = dict(x=x, fr=fr, query=q)

        # --- 話者ごとに単一の倍率を決める ---
        rms_list = [L.active_rms_dbfs(r["x"], r["fr"]) for r in raws.values()]
        med = float(np.median(rms_list))
        gain = 10 ** ((ref_rms - med) / 20)
        peak_after = max(float(np.max(np.abs(r["x"]))) for r in raws.values()) * gain
        cap = 10 ** (TARGET_PEAK_DBFS / 20)
        capped = False
        if peak_after > cap:
            gain *= cap / peak_after
            capped = True
        print(f"\n{col} {sp['name']}/{sp['style']} (speaker={sp['id']})")
        print(f"  実効値の中央値 {med:.2f} dBFS -> 倍率 {gain:.4f} "
              f"({20*np.log10(gain):+.2f} dB){' ※最大振幅の上限で頭打ち' if capped else ''}")

        for ch in CHARS:
            r = raws[ch]
            y = r["x"] * gain
            path = os.path.join(OUT_DIR, f"{col}_{ch}.wav")
            with open(path, "wb") as f:
                f.write(L.np_to_wav_bytes(y, r["fr"]))
            manifest["files"].setdefault(ch, {})[col] = dict(
                file=f"{col}_{ch}.wav", speaker=sp["id"], gain=round(gain, 6),
                pre_gain_rms_dbfs=round(L.active_rms_dbfs(r["x"], r["fr"]), 2),
                pre_phoneme_s=r["query"]["prePhonemeLength"],
                post_phoneme_s=r["query"]["postPhonemeLength"],
                speed=r["query"]["speedScale"], pitch=r["query"]["pitchScale"],
                intonation=r["query"]["intonationScale"], volume=r["query"]["volumeScale"],
            )
            print(f"  {col} {ch}  {os.path.basename(path)}")

        manifest["speakers"][col] = dict(**{k: v for k, v in sp.items()}, gain=round(gain, 6),
                                         gain_db=round(float(20 * np.log10(gain)), 2),
                                         gain_capped_by_peak=capped)

    for ch, rec in c_rec.items():
        manifest["files"].setdefault(ch, {})["C"] = {
            k: v for k, v in rec.items() if k != "active_rms_dbfs"}
    manifest["speakers"]["C"] = dict(
        id=108, name="東北きりたん", style="ノーマル",
        why="現行の本番プール（加工あり）。声の高さB3平坦化・1モーラ0.2秒・VOT修正などを含む",
        gain=1.0, gain_db=0.0, gain_capped_by_peak=False)
    manifest["speakers"]["A"] = dict(
        id=None, name="自然録音", style="準備中",
        why="人が実際に発音した録音。後日追加する枠", gain=None)

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n=> {os.path.relpath(OUT_DIR, REPO)}/manifest.json")


if __name__ == "__main__":
    main()
