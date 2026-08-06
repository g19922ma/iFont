#!/usr/bin/env python3
"""
候補プール slot133: 1モーラを「133ミリ秒相当」にした単音プールの試作
====================================================================
本番プール(experiment/audio1char_stimuli, 1モーラ 0.2 秒)の品質処方をそのまま引き継ぎ、
モーラ長だけを短くして 68 音を作り直す。話者・音高・処方はいっさい変えない。
本番プールの置き換えではなく、判断材料としての試作である。

なぜ 13 フレーム(138.67 ミリ秒)なのか
--------------------------------------
VOICEVOX は音素長を 1/93.75 秒 = 10.6667 ミリ秒の格子に量子化する。しかも量子化は
モーラ単位ではなく音素単位で、子音と母音が別々に最近接フレームへ丸められる。
実測(probe)で次を確かめた。

- 本番プール(0.2 秒を指定)の実際のモーラ長は一定ではない。68 音のうち 56 音が
  19 フレーム(202.67 ミリ秒)、12 音が 18 フレーム(192.0 ミリ秒)になっている。
  子音長と母音長が別々に丸められるため、合計が 18 にも 19 にもなるからである。
- 本番と同じ流儀で 1/7.5 秒(133.33 ミリ秒)を指定すると、母音だけのモーラ
  (あ行・ん など)の母音長がちょうど 12.5 フレームになる。ちょうど半分の値は
  丸め方向が浮動小数点の誤差しだいで決まってしまい、再現性がない。
  0.2 秒の指定は 18.75 フレームで半端ではないため、この問題が起きていなかった。
  したがって「指定して量子化に任せる」流儀は 133 ミリ秒には安全に移植できない。
- そこでフレーム数を直接指定する。モーラ長を n フレームちょうどにすると、
  子音長 c を丸めた値と (n - c) を丸めた値の和はかならず n になるので、
  68 音すべてが同じ長さにそろう(実測で確認済み)。
- 12 フレーム(128.0 ミリ秒)と 13 フレーム(138.67 ミリ秒)のどちらも、目標の
  133.33 ミリ秒からの隔たりは 5.33 ミリ秒でまったく同じである(133.33 は 12 と 13 の
  ちょうど中点にあたる)。したがって近さでは決まらない。決め手は品質のほうで、
  13 フレームのほうが子音長の頭打ちにかかる音が少ない(13 フレームで 8 音、
  12 フレームで 10 音)。子音長の頭打ちは VOT の処方をこわす操作なので、
  それが少ないほうを採る。
- 補助的な理由として、本番プールの量子化は 68 音中 56 音が長いほう(19 フレーム)に
  落ちており、実測の平均は 200.8 ミリ秒と指定値よりわずかに長い。長いほうの隣を
  選ぶのは、本番プールの実際のふるまいとも整合する。

実行(numpy と praat-parselmouth の入った環境で):
  <venv>/bin/python experiment/candidate_pools/slot133/build_slot133.py

出力(すべて experiment/candidate_pools/slot133/ の下):
- audio1char_stimuli/<hash>.mp3   68 音 + 同音字4字 = 72 ファイル
- audio1char_manifest.json        公開メタ(68 音)
- answer_key_1char.json           かなとファイルの対応(Git 管理外)
- audio1char_votfix_B3s133_108.json  子音長倍率の表
"""
import os
import sys
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(EXP)
sys.path.insert(0, os.path.join(REPO, "two_char_audio"))

import build_1char_pool as b1  # noqa: E402

FRAME_S = 1.0 / 93.75          # VOICEVOX の音素長の格子(10.6667 ミリ秒)
MORA_FRAMES = 13               # 採用したモーラ長。上の説明を参照
MORA_DUR = MORA_FRAMES * FRAME_S   # 0.1386667 秒 = 138.67 ミリ秒
LABEL = "B3s133"               # ハッシュを本番と別にするためのラベル(音高は B3 のまま)
SPEAKER = 108                  # 東北きりたん / ノーマル(本番と同じ)

# モーラ長だけを差し替える。品質処方(VOT ラダー・ぱ行の字ごとの処方・ぽ の文脈合成・
# 音量の均一化)は build_1char_pool の中身をそのまま使う。
b1.MORA_DUR = MORA_DUR


def main():
    print(f"モーラ長 {MORA_FRAMES} フレーム = {MORA_DUR * 1000:.2f} ミリ秒 で合成する",
          file=sys.stderr)
    sys.argv = [
        "build_slot133",
        "--speaker", str(SPEAKER),
        "--hz", "246.94",
        "--label", LABEL,
        "--out", os.path.join(HERE, "audio1char_stimuli"),
        "--manifest", os.path.join(HERE, "audio1char_manifest.json"),
        "--answerkey", os.path.join(HERE, "answer_key_1char.json"),
    ]
    b1.main()

    # build_1char_pool は子音長倍率の表を experiment/ 直下に書くので、プールの中へ移す
    # (本番のフォルダに候補プールの副産物を残さないため)。
    stray = os.path.join(EXP, f"audio1char_votfix_{LABEL}_{SPEAKER}.json")
    if os.path.exists(stray):
        shutil.move(stray, os.path.join(HERE, os.path.basename(stray)))
        print(f"  子音長倍率の表を {HERE} へ移した", file=sys.stderr)

    # マニフェストにモーラ長の実際の値を書き添える(mora_dur_s は指定値と同じ)。
    mpath = os.path.join(HERE, "audio1char_manifest.json")
    man = json.load(open(mpath))
    man["mora_frames"] = MORA_FRAMES
    man["mora_dur_ms_actual"] = round(MORA_DUR * 1000, 4)
    man["note"] = ("候補プール(試作)。本番プールと同じ話者・音高・品質処方で、"
                   "モーラ長だけを 13 フレーム = 138.67 ミリ秒にしたもの。")
    json.dump(man, open(mpath, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
