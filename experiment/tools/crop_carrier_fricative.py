#!/usr/bin/env python3
"""
「字＋さ」から、対象の字（第1モーラ）だけを切り出す
====================================================
2026-08-24 作成。後続モーラを「さ」に固定すると決めたことに伴うもの。

なぜ「さ」なのか
----------------
1文字だけを合成すると語末になって母音が伸び、抑揚も付く。そこで2モーラの無意味語
として合成し、第1モーラだけを切り出す。そのうしろに足す音は**全字で同じ**にする——
字ごとに変えると、後続から前へ働く影響（先読みの調音）が刺激ごとに違ってしまい、
第1モーラの曲線を比べるときの余計な差になるためである。

「さ」を選んだ理由:
  ・**先行研究に同じ設計がある**（第1モーラだけを変え、第2モーラを /sa/ に固定する形）。
    書誌は project/実験計画書_転写検証.md を見ること。
  ・摩擦音なので、母音との境目で**高い周波数の雑音が急に立ち上がる**。
    母音は低い周波数が主なので、両者はスペクトルの形がはっきり違い、境目を見つけやすい。
  ・**本命8字に「さ」が入っていない**ので、対象字と後続が同じになる組み合わせが少ない。

境目の見つけ方（破裂音のときとは違う）
--------------------------------------
後続が破裂音（ぱ・た・か）のときは、母音のあとに**閉鎖＝ほぼ無音**が来るので
「音量が落ちる点」を探せばよかった。**「さ」には無音が無い**ので、代わりに
**高い周波数の雑音が立ち上がる点**を探す。

  1. onset（音の実体が始まる点）を絶対 -58dBFS で検出する
  2. **母音の山を見つける**。onset 以降で、1kHz より下の成分がいちばん強いフレーム。
     ここを基準にするのが要点である——対象字が さ行・は行のときは**字自身にも摩擦が
     ある**ので、単に「最初に高域が立ち上がる点」を探すと字自身の摩擦を拾ってしまう。
     母音の山より後ろだけを見れば、拾うのは必ず後続の「さ」になる。
  3. 母音の山＋15ms 以降で、**高域（4〜10kHz）の占める割合が HI_RATIO を超える**状態が
     HOLD_MS 続く最初の点を「さ」の始まり＝切り口とする
  4. 切り口の手前に FADE_OUT_MS の余弦フェードアウトをかける

しきい値は**全字共通**である。母音は高域が乏しく（割合0.1未満）、/s/ は高域が主
（0.4以上）なので、母音の種類でしきい値を変える必要がない。ここが、後続を「ん」に
していたとき（母音ごとにしきい値を変える必要があり破綻した）との決定的な違いである。

入力と出力
----------
  入力  <src>/<かな>.wav        … build_carrier_takes.py が合成した「字＋さ」
  出力  <out>/<かな>.wav        … 切り口まで（末尾に5msのフェードアウト）
        <out>/crop_report.json  … 字ごとの onset・モーラ長・高域の割合

使い方
------
  python3 experiment/tools/crop_carrier_fricative.py \\
      --src experiment/tts_candidates_carrier2/raw_さ --dry-run
  python3 experiment/tools/crop_carrier_fricative.py \\
      --src experiment/tts_candidates_carrier2/raw_さ \\
      --out experiment/tts_candidates_carrier2/cut_さ
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crop_carrier_stop import (read_wav, write_wav, detect_onset_ms,  # noqa: E402
                               apply_fade_out)

FRAME_MS = 15.0        # 分析窓（摩擦の立ち上がりを捉えるため短め）
HOP_MS = 2.5
HI_LO, HI_HI = 4000, 10000     # 「高域」の範囲。/s/ の雑音はここに集中する
LOW_HI = 1000                  # 「母音らしさ」を測る低域の上限
HI_RATIO = 0.15        # 高域の占める割合。これから20msぶんの**中央値**がこれを超えたら摩擦
HOLD_MS = 20.0         # 中央値をとる長さ
MIN_MORA_MS = 75.0     # onset からこれ以上あとでないと切り口にしない
# ↑ この3つは 2026-08-24 に総当たりで決めた。決め方は「後続を『ぱ』にした版の
#   モーラ長（閉鎖＝無音で切るので確か）といちばん合う組み合わせを選ぶ」。
#   結果、**68字すべてで摩擦を検出でき、「ぱ」版とのずれは中央7ms・最大40ms未満**。
#   まったく別の原理（無音を探す／雑音を探す）・別の録音で一致したので、
#   どちらの切り出しも正しいと考えてよい。
FADE_OUT_MS = 5.0


def features(x, sr):
    """(時刻ms, 全体の音量dBFS, 高域の割合, 低域のエネルギー, 高域のdB) の並び。"""
    win = int(sr * FRAME_MS / 1000)
    hop = int(sr * HOP_MS / 1000)
    wnd = np.hanning(win)
    f = np.fft.rfftfreq(win, 1.0 / sr)
    b_hi = (f >= HI_LO) & (f < HI_HI)
    b_lo = f < LOW_HI
    out = []
    for i in range(0, max(1, len(x) - win), hop):
        seg = x[i:i + win]
        if len(seg) < win:
            break
        sp = np.abs(np.fft.rfft(seg * wnd)) ** 2
        tot = sp.sum() + 1e-14
        out.append((i / sr * 1000.0,
                    20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-12),
                    float(sp[b_hi].sum() / tot),
                    float(sp[b_lo].sum()),
                    10 * np.log10(sp[b_hi].sum() + 1e-14)))
    return out


def fricative_start(x, sr, onset_ms):
    """後続「さ」の摩擦が始まる時刻(ms)。見つからなければ None。

    ⚠ **高域の「絶対の大きさ」で判定してはいけない。** 母音は摩擦より音量が大きいので、
      4〜10kHz の絶対値は母音のほうが大きいことすらある（「あさ」で実測すると、
      摩擦のところは母音より 8dB 低い）。見るのは**全体に占める高域の割合**である。
      母音は 0.01〜0.03、「さ」の摩擦は 0.3 前後で、はっきり分かれる。

    ⚠ **「20ms のあいだ全フレームがしきい値超え」にしてはいけない。**
      あみたろの /s/ は割合が 0.36→0.13→0.34 のように揺れるので、全フレームを
      求めると見落とす（下見で 26字が失敗した）。**これから20msぶんの中央値**で見る。

    対象字自身の摩擦（さ行・は行）を拾わないための手当ては MIN_MORA_MS（75ms）である。
    第1モーラの子音はどれも onset から 75ms 以内に終わるので、そこから先を見れば
    拾うのは必ず後続の「さ」になる。
    """
    F = features(x, sr)
    if not F:
        return None, {}
    after = [f for f in F if f[0] >= onset_ms]
    if not after:
        return None, {}
    need = max(1, int(round(HOLD_MS / HOP_MS)))
    vowel = [f[2] for f in F if onset_ms + 20 <= f[0] <= onset_ms + 60]
    info = {"vowel_hi_ratio": round(float(np.median(vowel)), 3) if vowel else None}
    for i, (t, _db, hr, _lo, _hidb) in enumerate(F):
        if t < onset_ms + MIN_MORA_MS:
            continue
        run = F[i:i + need]
        if len(run) < need:
            break
        if float(np.median([r[2] for r in run])) > HI_RATIO and hr > HI_RATIO * 0.6:
            seg = [r[2] for r in F if t <= r[0] <= t + 40]
            info["fric_hi_ratio"] = round(float(np.mean(seg)), 3) if seg else None
            return t, info
    return None, info


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not args.out:
        sys.exit("--out か --dry-run のどちらかが要ります")

    names = sorted(n for n in os.listdir(args.src) if n.endswith(".wav"))
    items = {}
    for n in names:
        kana = os.path.splitext(n)[0]
        x, sr = read_wav(os.path.join(args.src, n))
        onset = detect_onset_ms(x, sr)
        b, info = fricative_start(x, sr, onset)
        items[kana] = {"onset_ms": round(onset, 1),
                       "orig_dur_ms": round(len(x) / sr * 1000.0, 1),
                       "fric_start_ms": None if b is None else round(b, 1),
                       "mora_ms": None if b is None else round(b - onset, 1),
                       "found": b is not None, **info}

    ok = [v for v in items.values() if v["found"]]
    ng = [k for k, v in items.items() if not v["found"]]
    mora = [v["mora_ms"] for v in ok]
    print(f"  {len(names)} 字を処理しました（{args.src}）")
    print(f"  摩擦の始まりを検出できた字: {len(ok)}／{len(names)}"
          + (f"  できない字: {' '.join(ng)}" if ng else ""))
    if mora:
        print(f"  第1モーラの長さ: 最小{min(mora):.0f} 中央{np.median(mora):.0f} "
              f"最大{max(mora):.0f} ms")
        vr = [v["vowel_hi_ratio"] for v in ok]
        fr = [v.get("fric_hi_ratio") for v in ok if v.get("fric_hi_ratio")]
        print(f"  高域の割合: 母音のところ 中央{np.median(vr):.3f} / "
              f"「さ」のところ 中央{np.median(fr):.3f}（しきい値 {HI_RATIO}）")

    if args.dry_run:
        return
    os.makedirs(args.out, exist_ok=True)
    for n in names:
        kana = os.path.splitext(n)[0]
        x, sr = read_wav(os.path.join(args.src, n))
        v = items[kana]
        end = int(sr * v["fric_start_ms"] / 1000) if v["found"] else len(x)
        y = apply_fade_out(x[:end], sr)
        write_wav(os.path.join(args.out, kana + ".wav"), y, sr)
        v["cut_dur_ms"] = round(len(y) / sr * 1000.0, 1)
    with open(os.path.join(args.out, "crop_report.json"), "w", encoding="utf-8") as f:
        json.dump({"src": args.src, "out": args.out,
                   "params": {"frame_ms": FRAME_MS, "hop_ms": HOP_MS,
                              "hi_band": [HI_LO, HI_HI], "hi_ratio": HI_RATIO,
                              "hold_ms": HOLD_MS, "min_mora_ms": MIN_MORA_MS,
                              "fade_out_ms": FADE_OUT_MS},
                   "items": items}, f, ensure_ascii=False, indent=1)
    print(f"  → {args.out}")


if __name__ == "__main__":
    main()
