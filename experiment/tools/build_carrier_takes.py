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
  python3 experiment/tools/build_carrier_takes.py --followers さ \\
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

# 対象の字（第1モーラ）にアクセント核を置くか。1＝置く／0＝置かない。
#
# ■ **1（核を置く）で確定。2026-08-24 に丸山さんが耳で判定したもの。**
#   本番の544本はこの設定で作る。
#
# ■ 0（核を外す）を試して却下した経緯 — 論文の刺激作成の節に使う
#   きっかけは「りさ」が「いさ」に聞こえるという報告だった。弾き音（舌先で歯ぐきを
#   一度はじく子音 /r/）が母音に埋もれて聞き取れない。合成のさせ方を10通り並べた
#   experiment/tools/compare_synth_params.html で聞くと、**核を外した版でだけ
#   「り」が「り」に聞こえる**。そこで 0 に変えて68字を作り直した。
#
#   **ところが、核を外すと切り出しが壊れる。**
#   核があるときは対象モーラで声の高さが高く始まって下がる。核を外すと平らになり、
#   第1モーラが短くなる（機械が測ったモーラ長の中央値 104ms → 78ms）。その結果
#   **68字中34字が切り出しの下限 75ms に張り付き、21字で後続の「さ」の摩擦が
#   刺激の末尾に残った**（末尾25msの高域割合 0.6〜0.99・−21〜−26dB＝十分聞こえる）。
#   後続を「ん」にしていたときの失敗と同じ形である。
#
#   決め手は**壊れた字の中に本命字が入っていたこと**である。本命8字だけを測り直すと
#
#       字        あ    か    が    ぱ    し    つ    ま    ら
#       核あり   0.00  0.01  0.00  0.00  (*)  0.01  0.00  0.00
#       核なし   0.05  0.72  0.01  0.00  (*)  0.97  0.01  0.01     ← か・つ が壊れる
#       (*) 「し」は字自身が摩擦音なので、この数値では判定できない
#
#   一方、**「り」も「ろ」も本命8字には入っていない**（transfer_config.js の targets）。
#   ら行から入っているのは「ら」だけで、その「ら」は核あり・核なしのどちらでも
#   切り出しがきれいである（末尾の漏れ 0.00〜0.01、モーラ長の差 5ms）。
#   **本命でない字のために本命の「か」「つ」を壊す取引は成り立たない**ので 1 に戻した。
#   検証に使ったページ: experiment/tools/compare_target_accent.html
#
# ■ アクセント句を1つにまとめる点は、核の有無とは別の話で、変えていない。
#   句切れが入ると対象モーラの終わりが伸び、切り出しの長さが字ごとに揃わなくなる。
TARGET_ACCENT = 1

# 字ごとの上書き。ここに書いた字だけ TARGET_ACCENT と違う値を使う。
#
# ■ **り・ろ だけ核を外す（2026-08-25 丸山判断・耳で決定）**
#   あみたろの「り」は「い」に、「ろ」は「も」に聞こえる。弾き音（舌先で歯ぐきを一度
#   はじく子音 /r/）が母音に埋もれるためで、実測でも子音部が「ろ」6ms と全話者中で
#   最短の部類だった（つくよみちゃん15ms・春日部つむぎ19ms・人の録音11ms）。
#   核を外すとこの2字は正しく聞こえる、と丸山さんが判断した。
#
# ■ **なぜ全字ではなく2字だけなのか**
#   全68字で核を外すと、第1モーラが短くなって切り出しが下限に張り付き、21字で後続の
#   「さ」の摩擦が末尾に残る。その中に**本命の「か」「つ」**が含まれていた（上の注記）。
#   一方、**り・ろ の2字は核を外しても切り出しがきれい**である（末尾の高域割合
#   0.014 / 0.008。しきい値0.15）。壊れないことを確かめたうえで、この2字だけ外す。
#
# ■ **論文で説明が要る点**（隠さずに書くこと）
#   字によって合成条件が違うことになる。ただし
#     ・**り・ろ はどちらも本命8字ではない**（偽ターゲットの候補）。解析には使わない
#     ・核の有無は**その字の中の声の高さの動き**を変えるだけで、後続「さ」との関係や
#       切り出しの手続きは全字で同じ
#   ので、測定される量には影響しない。
#
# ■ **び は救えなかった**（記録として残す）
#   「び」も「い」に聞こえるが、核を外すと子音部が 8ms → 1ms と**逆に悪化**する。
#   10通りの設定で改善したのは「前に母音『あ』を置いて『ありさ』の真ん中を切り出す」
#   方式だけ（8ms → 31ms）で、これは切り出しの起点の決め方を作り直す必要がある。
#   実測は experiment/tools/compare_synth_params.html（び・り・ろ の10通り）。
TARGET_ACCENT_BY_KANA = {"り": 0, "ろ": 0}

# 字ごとの「前置き母音」。ここに書いた字だけ、前に母音を置いた3モーラで合成する。
#
# ■ **「び」だけ「あ＋び＋さ」で合成し、前後の「あ」と「さ」の両方を削る**
#   （2026-08-25 丸山判断・耳で決定）
#
# ■ なぜ必要か
#   あみたろの「び」は「い」に聞こえる。/b/（両唇の破裂）が母音に埋もれるためである。
#   語頭に破裂音が来ると、その手前には音が無いので**閉鎖（唇を閉じている区間）が
#   現れようがない**。閉鎖が無ければ破裂も目立たない。
#   前に母音「あ」を置くと、閉鎖が「前の母音からの音量の落ち込み」として現れるので、
#   /b/ がはっきりする。実測でも子音部が **8ms → 31ms** に伸びた。
#
# ■ 他の案が効かなかったこと（10通りを68字ぶん試した結果・「び」の子音部 ms）
#     現行(核あり) 8 ／ 話速0.8 → 2 ／ 0.7 → 4 ／ 0.6 → 5
#     抑揚1.3 → 8 ／ 1.5 → 8 ／ **核を外す → 1（逆に悪化）** ／ 後続に核 → 5
#     エンジン任せ → 8 ／ **前に「あ」を置く → 31** ← これだけが効いた
#   比較ページ: experiment/tools/compare_biriro.html（音声を base64 で埋め込んである）
#
# ■ ⚠ **「び」だけ onset の決め方が変わる**（記録として残す）
#   他の67字は「音の実体の立ち上がり（絶対 −58dBFS）」を onset とする。
#   「び」は前に母音があるので立ち上がりが使えず、**「あ」と「び」のあいだの音量の谷**
#   （＝/b/ の閉鎖の始まり）を始点とする。
#   **「び」は偽ターゲットの候補で、回答は解析に使わない**ので測定値には影響しないが、
#   論文の刺激の節には書くこと（project/刺激作成_キャリアフレーズ.md §4.5）。
#
# ■ り・ろ にはこの方式を使わない
#   前に「あ」を置くと り は 1ms・ろ は 2ms と、かえって短くなる（弾き音は前の母音と
#   つながってしまうため）。り・ろ は核を外す方式のほうが良い。
LEAD_VOWEL_BY_KANA = {"び": "あ"}


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


def synth(base, target, follower, style_id, phoneme_cache,
          target_accent=TARGET_ACCENT, lead=None):
    """「（前置き母音＋）対象の字＋後続音」を合成して 16bit PCM の WAV を返す。

    ⚠ **アクセントの付け方を engine 任せにしないこと。**
      文字列をそのまま渡すと、エンジンは「しさ」を
      「し」＋句切れ＋「さ」の2アクセント句に分けてしまう。句切れが入ると
      対象モーラの終わりが伸び、切り出しの長さが字ごとに揃わなくなる。
      ここでは **必ず1つのアクセント句にまとめる**（アクセント句の数は engine に決めさせない）。

    ⚠ **そのアクセント句の中で、対象モーラに核を置くかどうかが target_accent である。**
      全字 1（核あり）。ただし り・ろ だけ 0。理由は上の注記を見ること。

    ⚠ **lead を渡すと3モーラになる**（例: lead="あ" で「あびさ」）。
      前に母音を置くと、破裂音の閉鎖が「前の母音からの音量の落ち込み」として現れるので、
      /b/ のような弱い語頭の破裂音がはっきりする。**「び」だけがこれを使う**（下の
      LEAD_VOWEL_BY_KANA）。切り出し側は前後の「あ」と「さ」の両方を削る必要があるので、
      crop_carrier_fricative.py が synth_meta.json を読んで始点も探す。
    """
    for k in ([target, follower] + ([lead] if lead else [])):
        if k not in phoneme_cache:
            phoneme_cache[k] = mora_phoneme(base, style_id, k)
    moras = []
    if lead:
        moras.append({"phoneme": phoneme_cache[lead], "hira": lead, "accent": 0})
    moras.append({"phoneme": phoneme_cache[target], "hira": target,
                  "accent": int(target_accent)})
    moras.append({"phoneme": phoneme_cache[follower], "hira": follower, "accent": 0})
    detail = [moras]
    payload = {"speakerUuid": SPEAKER_UUID, "styleId": style_id,
               "text": (lead or "") + target + follower, "prosodyDetail": detail}
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
    ap.add_argument("--followers", nargs="+", default=["さ"],
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
            acc = TARGET_ACCENT_BY_KANA.get(k, TARGET_ACCENT)   # 字ごとの上書き
            lead = LEAD_VOWEL_BY_KANA.get(k)                    # 前置き母音（び だけ）
            wav, detail = synth(args.base, k, use, STYLE_ID, cache,
                                target_accent=acc, lead=lead)
            with open(os.path.join(d, k + ".wav"), "wb") as f:
                f.write(wav)
            made.setdefault(fol, {})[k] = {"text": (lead or "") + k + use, "follower": use,
                                           "lead": lead, "target_accent": acc,
                                           "prosody": detail}
            if (i + 1) % 20 == 0:
                print(f"  {fol}: {i+1}/{len(kana)} 字")
        print(f"  後続「{fol}」… {len(kana)}字を書きました → {d}")

    meta = {"engine": "COEIROINK v2", "base": args.base,
            "speaker": SPEAKER_NAME, "speaker_uuid": SPEAKER_UUID,
            "style": STYLE_NAME, "style_id": STYLE_ID, "credit": CREDIT,
            "synth_params": SYNTH, "target_accent": TARGET_ACCENT,
            "target_accent_by_kana": TARGET_ACCENT_BY_KANA,
            "lead_vowel_by_kana": LEAD_VOWEL_BY_KANA,
            "followers": args.followers,
            "follower_map": fmap, "n_kana": len(kana), "takes": made,
            "note": "2026-08-23版がどのスタイルで作られたかの記録は残っていない。"
                    "基本周波数の中央値で照合して のーまるv5 を選んだ（337Hz 対 322Hz）。"}
    with open(os.path.join(args.out, "synth_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  {time.time()-t0:.0f} 秒。設定は {args.out}/synth_meta.json に残しました")


if __name__ == "__main__":
    main()
