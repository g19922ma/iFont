#!/usr/bin/env python3
"""
キャリアフレーズ「字＋後続音」を COEIROINK で合成する
=====================================================
2026-08-24 作成。**それまで合成の手順が .py として残っておらず、対話実行のまま
失われていた**（WORKLOG 2026-08-23 追記2 に「まとまった .py としては未保存」と
書いてある）。同じことを繰り返さないようスクリプトにした。

なぜキャリアフレーズを使うのか
------------------------------
聴覚刺激は「音の始まりから t ミリ秒で打ち切った1モーラ」である。1モーラだけを
単独で読ませると、語末になるために母音が伸び、抑揚も付いてしまう。そこで
**うしろに1モーラ足して読ませ、対象の字だけを切り出す**（キャリアフレーズ法）。

後続音を「ん」から無声破裂音に変えた理由
----------------------------------------
2026-08-23／08-24 は後続を「ん」にしていたが、**「ん」は母音と地続きに始まる**ため
「どこまでが字でどこからが《ん》か」を機械で決められず、68字中34字で《ん》が
残った（経緯は project/刺激作成_キャリアフレーズ.md）。
無声破裂音（か・た・ぱ）なら、母音のあとに**閉鎖区間＝ほぼ無音**が来るので、
切る位置が音量の落ち込みだけで一意に決まる。

事前に確かめたこと（2026-08-24）
--------------------------------
狭母音 /i/ /u/ は無声子音にはさまれると日本語では無声化して消える。
「き＋た」「す＋か」がこれに当たるので、**母音が消えないか**を先に実測した。
有声フレームの割合は「ん」後続と比べて多少下がる字はあるが、母音が消えるほどの
無声化は起きなかった（表は記録文書にある）。

使い方
------
  # 後続音を選ぶための下見（68字 × 後続3種）
  python3 experiment/tools/build_carrier_takes.py --followers た か ぱ \\
      --out experiment/tts_candidates_carrier2

  # 本番（選んだ後続音だけ。--follower-map があればそれを優先）
  python3 experiment/tools/build_carrier_takes.py --followers ぱ \\
      --out experiment/tts_candidates_carrier2

出力
----
  <out>/raw_<後続音>/<かな>.wav   … 合成したままの「字＋後続音」
  <out>/synth_meta.json           … 話者・スタイル・合成の設定（再現用）

エンジンについて
----------------
COEIROINK v2 のローカルAPI（既定 http://127.0.0.1:50032）を使う。
**VOICEVOX（50021）とは別のエンジン・別のAPI**なので、
experiment/tools/build_tts_candidates.py（VOICEVOX用）は流用できない。
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave

# あみたろ（COEIROINK）。話者の識別子とスタイルは変えないこと。
# スタイル「のーまるv5」は既定の素の声。**2026-08-23 版がどのスタイルで作られたかは
# 記録が残っていない**（基本周波数の中央値で照合すると 337Hz 対 322Hz でこれが最も近い）。
# 68字すべてを作り直すので、新しい一式の中で一貫していれば実験上は足りる。
SPEAKER_UUID = "d93140ec-d365-11ec-8f1d-0242ac1c0002"
SPEAKER_NAME = "あみたろ"
STYLE_ID = 1564398632
STYLE_NAME = "のーまるv5"
CREDIT = "COEIROINK:あみたろ"

# 68かな。transfer_config.js の打ち切り時点の表と同じ並び。
KANA = list("あいうえおかきくけこさしすせそたてとちつなにぬねのはひふへほまみむめも"
            "やゆよわらりるれろんがぎぐげござじずぜぞだでどばびぶべぼぱぴぷぺぽ")

# 合成の設定。**変えたら synth_meta.json に残るので、あとから差が追える**。
SYNTH = {
    "speedScale": 1.0,        # 話す速さ（1.0 = 既定）
    "volumeScale": 1.0,       # 音量（音量そろえは別工程でやるのでここでは触らない）
    "pitchScale": 0.0,        # 声の高さ
    "intonationScale": 1.0,   # 抑揚の強さ
    "prePhonemeLength": 0.1,  # 発話の前に付ける無音（秒）
    "postPhonemeLength": 0.1, # 発話の後に付ける無音（秒）
    "outputSamplingRate": 44100,
}


def post(base, path, payload, raw=False, timeout=60):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body if raw else json.loads(body)


def mora_phoneme(base, style_id, kana):
    """1モーラの音素表記（例 「し」→"sh-i"）をエンジンに作らせる。"""
    pros = post(base, "/v1/estimate_prosody",
                {"speakerUuid": SPEAKER_UUID, "style_id": style_id, "text": kana + "ん"})
    return pros["detail"][0][0]["phoneme"]


def synth(base, target, follower, style_id, phoneme_cache):
    """「対象の字＋後続音」を合成して 16bit PCM の WAV を返す。

    ⚠ **アクセントの付け方を engine 任せにしないこと。**
      文字列をそのまま渡すと、エンジンは「しぱ」を
      「し」（アクセント核なし）＋句切れ＋「ぱ」の2アクセント句に分けてしまう。
      対象モーラにアクセント核が無いと、
        ・「つ」で母音の終わりが不明瞭になり、切り出しが 309ms まで伸びる誤検出が出る
        ・全字で対象モーラの目立ち方が不揃いになる
      ここでは **1つのアクセント句にまとめ、対象モーラに核（accent=1）を置く**。
      現行の「字＋ん」版も対象モーラが accent=1 だったので、その点は変わらない。
    """
    for k in (target, follower):
        if k not in phoneme_cache:
            phoneme_cache[k] = mora_phoneme(base, style_id, k)
    detail = [[{"phoneme": phoneme_cache[target], "hira": target, "accent": 1},
               {"phoneme": phoneme_cache[follower], "hira": follower, "accent": 0}]]
    payload = {"speakerUuid": SPEAKER_UUID, "styleId": style_id,
               "text": target + follower, "prosodyDetail": detail}
    payload.update(SYNTH)
    return post(base, "/v1/synthesis", payload, raw=True), detail


def check_engine(base):
    try:
        with urllib.request.urlopen(base + "/v1/speakers", timeout=10) as r:
            spk = json.loads(r.read())
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"COEIROINK に繋がりません（{base}）。アプリを起動してください。\n  {e}")
    for s in spk:
        if s.get("speakerUuid") == SPEAKER_UUID:
            ids = [st.get("styleId") for st in s.get("styles", [])]
            if STYLE_ID not in ids:
                sys.exit(f"スタイル {STYLE_ID}（{STYLE_NAME}）がありません。あるのは {ids}")
            return
    sys.exit(f"話者 {SPEAKER_NAME} がエンジンにありません。COEIROINK に導入してください。")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:50032",
                    help="COEIROINK v2 のAPI（VOICEVOX の 50021 ではない）")
    ap.add_argument("--out", required=True, help="書き出し先のフォルダ")
    ap.add_argument("--followers", nargs="+", default=["ぱ"],
                    help="対象字のうしろに足すモーラ（複数渡すと後続音ごとに一式作る）")
    ap.add_argument("--follower-map", default=None,
                    help='字ごとに後続音を変える表(JSON)。例 {"か":"た","た":"ぱ"}。'
                         "この表にある字はここの後続音を使い、無い字は --followers の1つ目を使う")
    ap.add_argument("--kana", nargs="*", default=None, help="作る字を絞る（下見用）")
    args = ap.parse_args()

    check_engine(args.base)
    kana = args.kana if args.kana else KANA
    fmap = json.load(open(args.follower_map, encoding="utf-8")) if args.follower_map else {}
    os.makedirs(args.out, exist_ok=True)

    made = {}
    cache = {}
    t0 = time.time()
    for fol in args.followers:
        d = os.path.join(args.out, f"raw_{fol}")
        os.makedirs(d, exist_ok=True)
        for i, k in enumerate(kana):
            use = fmap.get(k, fol) if fmap else fol
            wav, detail = synth(args.base, k, use, STYLE_ID, cache)
            with open(os.path.join(d, k + ".wav"), "wb") as f:
                f.write(wav)
            made.setdefault(fol, {})[k] = {"text": k + use, "follower": use,
                                           "prosody": detail}
            if (i + 1) % 20 == 0:
                print(f"  {fol}: {i+1}/{len(kana)} 字")
        print(f"  後続「{fol}」… {len(kana)}字を書きました → {d}")

    meta = {"engine": "COEIROINK v2", "base": args.base,
            "speaker": SPEAKER_NAME, "speaker_uuid": SPEAKER_UUID,
            "style": STYLE_NAME, "style_id": STYLE_ID, "credit": CREDIT,
            "synth_params": SYNTH, "followers": args.followers,
            "follower_map": fmap, "n_kana": len(kana), "takes": made,
            "note": "2026-08-23版がどのスタイルで作られたかの記録は残っていない。"
                    "基本周波数の中央値で照合して のーまるv5 を選んだ（337Hz 対 322Hz）。"}
    with open(os.path.join(args.out, "synth_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  {time.time()-t0:.0f} 秒。設定は {args.out}/synth_meta.json に残しました")


if __name__ == "__main__":
    main()
