#!/usr/bin/env python3
"""
子音と母音の配り方を方式1(本番)と方式2(uniform200)で並べた表を作る
====================================================================
project/子音母音配分_方式比較.md の表の部分を作る。

数値の出どころ
--------------
VOICEVOX に /audio_query で1字ずつ問い合わせて得た音素長(子音長・母音長)を、
それぞれの方式で 1 モーラ 0.2 秒に配り直し、エンジンの格子(1/93.75 秒 =
10.6667 ミリ秒)に丸めた値である。実際の mp3 の波形から測った値ではない。
ただし experiment/tools/build_gate_windows.py が、この配り方から予測される
合成 WAV の全長と、実際の mp3 を復号した長さが一致することを 68 音すべてで
確かめている(一致しなければそこで中断する)ので、実体と食い違ってはいない。

VOT(破裂から声が出るまでの間)の修正で子音長を何倍かに伸ばす音があるので、
その倍率は各プールが実際に使った値(audio1char_votfix_*.json)を用いる。

実行(VOICEVOX を 127.0.0.1:50021 で起動しておくこと):
  ~/ifont_env/bin/python experiment/candidate_pools/uniform200/make_compare_table.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(EXP)
sys.path.insert(0, os.path.join(EXP, "tools"))
sys.path.insert(0, REPO)

import build_gate_windows as gw   # noqa: E402
import ifont_common as ic         # noqa: E402

MORA_DUR = 0.2
SPEAKER = 108
FRAME_MS = gw.FRAME_SAMPLES / gw.SR * 1000     # 10.6667 ミリ秒
# 出題から外す同音字(を・ぢ・づ・ゔ)。公開プールは68音なので表からも外す。
EXCLUDE = set("をぢづゔ")

CMUL_M1 = json.load(open(os.path.join(EXP, "audio1char_votfix_B3_108.json")))
CMUL_M2 = json.load(open(os.path.join(HERE, "audio1char_votfix_B3u200_108.json")))


def alloc(ch, cmul, slot_mode):
    fc, fv = gw.phoneme_frames(ch, SPEAKER, cmul, MORA_DUR, slot_mode)
    return fc * FRAME_MS, fv * FRAME_MS


def main():
    rows = []
    for ch in ic.AUDIO_ALL:
        if ch in EXCLUDE:
            continue
        if ch in gw.OPPO_SPLICE:
            # ぽ は「オッポ」の文脈合成から切り出す処方で、配り方の規則を通らない。
            # 両方式でまったく同じ音になるので、差なしとして表に残す。
            rows.append(dict(ch=ch, c1=None, v1=None, c2=None, v2=None, dv=0.0,
                             note="文脈合成から切り出し(両方式で同一)"))
            continue
        c1, v1 = alloc(ch, CMUL_M1.get(ch), "vowel")
        c2, v2 = alloc(ch, CMUL_M2.get(ch), "uniform")
        note = ""
        if CMUL_M1.get(ch) != CMUL_M2.get(ch):
            note = (f"VOT修正の子音長倍率が方式1では{CMUL_M1.get(ch, 1.0)}倍、"
                    f"方式2では{CMUL_M2.get(ch, 1.0)}倍に収束")
        rows.append(dict(ch=ch, c1=c1, v1=v1, c2=c2, v2=v2,
                         dc=c2 - c1, dv=v2 - v1, note=note))

    # 並べ替えは「子音の差と母音の差の合計」の大きい順。同点なら五十音順。
    rows.sort(key=lambda r: (-(abs(r["dv"]) + abs(r.get("dc", 0.0))),
                             ic.AUDIO_ALL.index(r["ch"])))
    out = []
    out.append("| かな | 方式1 子音 | 方式1 母音 | 方式1 モーラ | "
               "方式2 子音 | 方式2 母音 | 方式2 モーラ | 子音の差 | 母音の差 | 備考 |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rows:
        if r["c1"] is None:
            out.append(f"| {r['ch']} | — | — | — | — | — | — | 0 | 0 | {r['note']} |")
        else:
            out.append(f"| {r['ch']} | {r['c1']:.1f} | {r['v1']:.1f} | {r['c1'] + r['v1']:.1f} | "
                       f"{r['c2']:.1f} | {r['v2']:.1f} | {r['c2'] + r['v2']:.1f} | "
                       f"{r['dc']:+.1f} | {r['dv']:+.1f} | {r['note']} |")
    print("\n".join(out))

    moved = [r for r in rows if abs(r["dv"]) + abs(r.get("dc") or 0.0) > 0.5]
    vmoved = [r for r in rows if abs(r["dv"]) > 0.5]
    print(f"配分が動いた音 {len(moved)} / 68。うち母音長が動いた音 {len(vmoved)}"
          f"(伸びた {sum(1 for r in vmoved if r['dv'] > 0)}、"
          f"縮んだ {sum(1 for r in vmoved if r['dv'] < 0)})", file=sys.stderr)
    for r in rows[:8]:
        if r["c1"] is not None:
            print(f"  {r['ch']}: 母音 {r['v1']:.1f} -> {r['v2']:.1f} ({r['dv']:+.1f})",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
