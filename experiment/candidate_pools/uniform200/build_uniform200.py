#!/usr/bin/env python3
"""
候補プール uniform200: 子音と母音を同じ倍率で伸縮して1モーラ0.2秒にした単音プールの試作
========================================================================================
本番プール(experiment/audio1char_stimuli)と変えたのは「1モーラ0.2秒の中で子音と母音に
どう時間を配るか」だけである。話者(東北きりたん・番号108)・音高(B3=246.94Hz)・
VOT(破裂から声が出るまでの間)の自動修正・ぱ行の字ごとの処方・ぽ の文脈合成・
音量の均一化・前後余白0.1秒・mp3への変換は、本番とまったく同じ処方を使う。

配り方の2つの方式
-----------------
方式1(本番・現行プール。build_2char_pool.set_mora):
    子音長はエンジンが返した自然値をそのまま残し、母音長 = 0.2秒 - 子音長 とする。
    子音長が 0.16 秒を超えるときだけ 0.16 秒で頭打ちにする(母音を最低40ミリ秒残すため)。
    もともとは競技かるたの「伸ばし・余韻」(母音を保持する操作)のための配り方だった。
    孤立モーラでは子音の長い音(し・す など)の母音が痩せる。実際「し」の母音は
    40ミリ秒まで押し潰されている。

方式2(このプール。uniform):
    子音長と母音長を同じ倍率 k = 0.2秒 / (子音長 + 母音長) で伸縮する。
    子音と母音の比が、エンジンが出した自然な比のまま保たれる。
    PI(栗原氏)が ifont_tool 側のコミット d4a5cf048 で採り入れた配り方と同じ規則である
    (ifont_tool/ifont/audio.py の synth_voicevox_slot の mode="uniform")。

このプールは本番プールの置き換えではなく、聴き比べて判断するための材料である。

VOICEVOX の量子化について
-------------------------
エンジンは音素長を 1/93.75 秒 = 10.6667 ミリ秒の格子に丸める。しかも子音と母音を
別々に丸めるので、0.2 秒を指定しても実際のモーラ長は 192.0 ミリ秒(18フレーム)や
202.67 ミリ秒(19フレーム)に割れる。これは方式1(本番)でも起きていることで、
方式2で新たに生じる問題ではない。実際のモーラ長は
experiment/tools/build_gate_windows.py が各 mp3 の復号後の長さと突き合わせて検算する。

実行(numpy と praat-parselmouth の入った環境で。VOICEVOX を 127.0.0.1:50021 で起動しておく):
  ~/ifont_env/bin/python experiment/candidate_pools/uniform200/build_uniform200.py

このスクリプトの出力(すべて experiment/candidate_pools/uniform200/ の下):
- audio1char_stimuli/<hash>.mp3      68音 + 同音字4字(を・ぢ・づ・ゔ) = 72ファイル
- audio1char_manifest.json           公開メタ(68音)
- answer_key_1char.json              かなとファイルの対応(このプール単体ぶん)
- audio1char_votfix_B3u200_108.json  VOT修正で使った子音長倍率の表

このあと必要な後処理(手順と数値は project/子音母音配分_方式比較.md にまとめてある):
1. merge_answer_key.py  … answer_key_merged.json に pool="uniform200" として統合する
2. build_onsets.py      … 音響的立ち上がり・増幅率の下書きを作る
3. build_gate_windows.py --pool uniform200 … 切り出し窓(gate_*)を確定して manifest に書く
"""
import os
import sys
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(EXP)
sys.path.insert(0, os.path.join(REPO, "two_char_audio"))

import build_2char_pool as b2   # noqa: E402
import build_1char_pool as b1   # noqa: E402

LABEL = "B3u200"    # ハッシュを本番と別にするためのラベル(音高は B3 のまま)
SPEAKER = 108       # 東北きりたん / ノーマル(本番と同じ)
HZ = 246.94         # B3(本番と同じ)


def set_mora_uniform(m, pitch_ln, dur):
    """方式2: 子音長と母音長を同じ倍率で伸縮して合計を dur 秒にする。

    build_2char_pool.set_mora(方式1)と差し替えて使う。規則は
    ifont_tool/ifont/audio.py の synth_voicevox_slot(mode="uniform") と同じ。
    母音だけのモーラ(あ行・ん など)は子音長が 0 なので、母音長がそのまま dur になる。
    """
    m = dict(m)
    c = m.get("consonant_length") or 0.0
    v = m.get("vowel_length") or 0.0
    tot = c + v
    if tot > 0:
        k = dur / tot
        if c:
            m["consonant_length"] = c * k
        m["vowel_length"] = v * k
    else:
        m["vowel_length"] = dur
    m["pitch"] = pitch_ln
    return m


def main():
    # build_1char_pool は b2.set_mora を通して時間を配る。ここだけを方式2に差し替える。
    # モーラ長(b1.MORA_DUR = 0.2秒)も、そのほかの処方もいっさい変えない。
    b2.set_mora = set_mora_uniform
    print(f"配り方=一様伸縮(方式2) / 1モーラ {b1.MORA_DUR * 1000:.0f} ミリ秒 で合成する",
          file=sys.stderr)

    sys.argv = [
        "build_uniform200",
        "--speaker", str(SPEAKER),
        "--hz", str(HZ),
        "--label", LABEL,
        "--out", os.path.join(HERE, "audio1char_stimuli"),
        "--manifest", os.path.join(HERE, "audio1char_manifest.json"),
        "--answerkey", os.path.join(HERE, "answer_key_1char.json"),
    ]
    b1.main()

    # build_1char_pool は子音長倍率の表を experiment/ 直下に書くので、プールの中へ移す
    # (本番のフォルダに候補プールの副産物を残さないため。slot133 と同じ後始末)。
    stray = os.path.join(EXP, f"audio1char_votfix_{LABEL}_{SPEAKER}.json")
    if os.path.exists(stray):
        shutil.move(stray, os.path.join(HERE, os.path.basename(stray)))
        print(f"  子音長倍率の表を {HERE} へ移した", file=sys.stderr)

    # マニフェストに配り方の別を書き添える。
    mpath = os.path.join(HERE, "audio1char_manifest.json")
    man = json.load(open(mpath))
    man["slot_mode"] = "uniform"
    man["note"] = ("候補プール(試作)。本番プールと同じ話者・音高・品質処方で、"
                   "1モーラ0.2秒の中の子音と母音の配り方だけを"
                   "「同じ倍率で伸縮する(一様)」に変えたもの。"
                   "本番は「子音長を保ち母音で帳尻を合わせる」配り方。")
    json.dump(man, open(mpath, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
