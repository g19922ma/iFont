#!/usr/bin/env python3
"""
字ごとの「打ち切り時点」7点を、その字のモーラ長に収めて決める
==============================================================
2026-08-24 作成。刺激をキャリアフレーズ「字＋ぱ」版に作り直したのに伴うもの。

決め方の考え方
--------------
**点の数は全字7点（＋全長で8点）で固定する。** 数をそろえるのは出題の頻度のためで
ある——1人が担当するのは各字3点なので、点の数が字ごとに違うと頻出20字の
1人あたり出現回数がそろわなくなり、「よく出る字」から本命8字を見分けられてしまう
（頻度差ゼロの設計が崩れる）。

**間隔だけ**を、その字のモーラ長に収まるよう決める。並びの形は音の種類ごとに変える。
Furui (1986) が示したとおり、字を見分けられるようになる時間帯は音の種類で違うので、
**曲線が動く帯を密に測る**のが効率がよい。形は3通り:

  はやい … 母音・破裂音・鼻音。頭の情報だけで早く決まるので、前半を密に
           もとの形 [10,20,30,40,55,70,100]（100で正規化）
  まさつ … 無声摩擦（さ行・は行）。摩擦が続くあいだは決まらず、母音に入って決まる
           ので、後ろ寄りに広く  もとの形 [10,60,90,120,150,190,240]
  なかま … 破擦・はじき音・接近音（ち・つ・ざ行・ら行・や行・わ）。その中間
           もとの形 [10,40,60,80,110,150,200]

そのうえで:
  ・**最短は必ず 10 ミリ秒**（床）。S字曲線を当てはめるには「当て推量に近い正答率に
    なる点」が要る。打ち切りの終端には5ミリ秒のフェードが掛かるので、10ミリ秒の
    刺激で元の大きさのまま鳴るのは頭の約5ミリ秒だけであり、これが物理的な下限。
  ・**最長はモーラの終わりから 15 ミリ秒内側**。母音から後続の閉鎖へ移りかけの
    ところを刺激に入れないため。
  ・そのあいだを、上の形のまま比例で配る。5ミリ秒単位に丸める。

出力
----
  transfer_config.js に貼れる形の JavaScript（標準出力）と、
  --json を付けると素の値も出す。

使い方
------
  python3 experiment/tools/build_gate_ladders.py \\
      --src experiment/tts_candidates_carrier2/norm
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crop_carrier_stop import read_wav, detect_onset_ms  # noqa: E402

FLOOR_MS = 10.0        # いちばん短い点（床）
INSIDE_MS = 15.0       # いちばん長い点を、モーラの終わりから何ミリ秒内側に置くか
STEP_MS = 5            # 丸める単位

SHAPES = {
    "はやい": [10, 20, 30, 40, 55, 70, 100],
    "まさつ": [10, 60, 90, 120, 150, 190, 240],
    "なかま": [10, 40, 60, 80, 110, 150, 200],
}

# 字 → 並びの形。音の種類でまとめてある（transfer_config.js の分類と同じ）。
GROUP = {}
for _ks, _g in [
    ("あいうえお", "はやい"),          # 母音
    ("かきくけこ", "はやい"),          # 無声破裂 k
    ("たてと", "はやい"),              # 無声破裂 t
    ("なにぬねの", "はやい"),          # 鼻音 n
    ("まみむめも", "はやい"),          # 鼻音 m
    ("ん", "はやい"),                  # 撥音
    ("がぎぐげご", "はやい"),          # 有声破裂 g
    ("だでど", "はやい"),              # 有声破裂 d
    ("ばびぶべぼ", "はやい"),          # 有声破裂 b
    ("ぱぴぷぺぽ", "はやい"),          # 無声破裂 p
    ("さしすせそ", "まさつ"),          # 無声摩擦 s/ʃ
    ("はひふへほ", "まさつ"),          # 無声摩擦 h/ç/ɸ
    ("ちつ", "なかま"),                # 破擦
    ("ざじずぜぞ", "なかま"),          # 有声破擦・摩擦
    ("らりるれろ", "なかま"),          # はじき音
    ("やゆよわ", "なかま"),            # 接近音
]:
    for _k in _ks:
        GROUP[_k] = _g


def ladder(shape, mora_ms):
    """その字のモーラ長に収めた7点を返す。"""
    top = mora_ms - INSIDE_MS
    if top <= FLOOR_MS + 6 * STEP_MS:
        # モーラが極端に短い字。5ミリ秒刻みで置けるだけ置く（起こらないはずだが保険）
        return [FLOOR_MS + i * STEP_MS for i in range(7)]
    t0, t6 = shape[0], shape[-1]
    out = []
    for t in shape:
        frac = (t - t0) / float(t6 - t0)
        v = FLOOR_MS + frac * (top - FLOOR_MS)
        out.append(int(round(v / STEP_MS) * STEP_MS))
    out[0] = int(FLOOR_MS)
    # 5ミリ秒刻みで丸めると重なることがあるので、必ず増えるように押し上げる
    for i in range(1, 7):
        if out[i] <= out[i - 1]:
            out[i] = out[i - 1] + STEP_MS
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="音量そろえ済みの1モーラWAVのフォルダ")
    ap.add_argument("--json", default=None, help="素の値も JSON で書き出す")
    args = ap.parse_args()

    names = sorted(n for n in os.listdir(args.src) if n.endswith(".wav"))
    rows = {}
    for n in names:
        kana = os.path.splitext(n)[0]
        x, sr = read_wav(os.path.join(args.src, n))
        onset = detect_onset_ms(x, sr)
        mora = len(x) / sr * 1000.0 - onset
        g = GROUP.get(kana, "はやい")
        rows[kana] = {"onset_ms": round(onset, 1), "mora_ms": round(mora, 1),
                      "shape": g, "gates": ladder(SHAPES[g], mora)}

    # 検算
    bad = [k for k, v in rows.items()
           if len(set(v["gates"])) != 7 or v["gates"][-1] > v["mora_ms"] - 1]
    if bad:
        print(f"⚠ 収まっていない字: {' '.join(bad)}", file=sys.stderr)
    mo = [v["mora_ms"] for v in rows.values()]
    tops = [v["gates"][-1] for v in rows.values()]
    print(f"// モーラ長 {min(mo):.0f}〜{max(mo):.0f}ms ／ "
          f"最長の点 {min(tops)}〜{max(tops)}ms ／ 全字7点", file=sys.stderr)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)

    order = "あいうえお かきくけこ さしすせそ たてと ちつ なにぬねの はひふへほ まみむめも やゆよわ らりるれろ ん がぎぐげご ざじずぜぞ だでど ばびぶべぼ ぱぴぷぺぽ"
    for blk in order.split():
        for k in blk:
            if k in rows:
                v = rows[k]
                print(f'      "{k}": {json.dumps(v["gates"])},'
                      f'   // {v["shape"]}・モーラ{v["mora_ms"]:.0f}ms')


if __name__ == "__main__":
    main()
