#!/usr/bin/env python3
"""
キャリアフレーズの4方式を切り出して比べ、聞き比べページ用の音と数値を作る
==========================================================================
2026-08-24 作成。

1文字だけを合成すると語末になって母音が伸び、抑揚も付いてしまう。そこで
**2モーラの無意味語として合成し、第1モーラだけを切り出す**（キャリアフレーズ法）。
そのうしろに足す音をどれにするかを決めるため、4通りを同じ手順で作って比べる。

  あ   … 後続が母音「あ」（例「かあ」）。母音どうしなので**無音区間ができない**。
  ぱ   … 後続が両唇の無声破裂音（例「かぱ」）。母音のあとに閉鎖（ほぼ無音）が来る。
  た   … 後続が歯茎の無声破裂音（例「かた」）。同上。本命8字と調音位置が重ならない。
  さ   … 後続が無声摩擦音（例「かさ」）。無音はできないが、**高い周波数の雑音が
         急に立ち上がる**ので境目が分かる。第1モーラだけを変えて第2モーラを /sa/ に
         固定する設計は先行研究にもある（書誌は実験計画書）。本命8字に「さ」が
         入っていないので、対象字と後続が同じになる組み合わせも少ない。

境界が決まらない字の扱い
------------------------
**一律の長さでは切らない。** 字ごとにモーラ長が違う（80〜167ms）ので、一律にすると
短い字は後続を巻き込み、長い字は母音を削る。代わりに、
**同じ話者・同じ話速・同じアクセントで作った「ぱ」版のモーラ長**を使って切る。
「ぱ」版は68字すべてで閉鎖を検出できているので、これが一番確かな見積もりになる。
どの字をこの方法で切ったかは stats.json の fallback に残る。

⚠ 切り出したあとに必ず確かめること
----------------------------------
そこでこのスクリプトは、切り出したあとに機械で
  ・末尾に第2モーラの子音（閉鎖＝無音／破裂＝急な立ち上がり／摩擦＝高域の雑音）が
    始まっていないか
  ・母音が2モーラぶんの長さになっていないか（「ぱ」版のモーラ長と比べて長すぎないか）
を必ず確かめ、その数値を stats.json に残す。

出力
----
  experiment/tts_candidates_carrier2/cut_<方式>/   切り出したもの
  experiment/tts_candidates_carrier2/norm_<方式>/  音量をそろえたもの
  experiment/tools/compare_followers/<かな>_<方式>.wav  ページが鳴らす音
  experiment/tools/compare_followers/stats.json         方式ごとの数値

使い方
------
  python3 experiment/tools/compare_methods.py
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crop_carrier_stop import (read_wav, write_wav, detect_onset_ms,  # noqa: E402
                               closure_start, apply_fade_out)
from crop_carrier_fricative import fricative_start  # noqa: E402
from normalize_takes import a_weighted_rms  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
BASE = os.path.join(ROOT, "experiment", "tts_candidates_carrier2")
SND = os.path.join(ROOT, "experiment", "tools", "compare_followers")
LEAD_MS = 50.0
PEAK_CAP = 0.85

KANA = list("あいうえおかきくけこさしすせそたてとちつなにぬねのはひふへほまみむめも"
            "やゆよわらりるれろんがぎぐげござじずぜぞだでどばびぶべぼぱぴぷぺぽ")
METHODS = [("さ", "raw_さ"), ("ぱ", "raw_ぱ"), ("た", "raw_た"), ("あ", "raw_あ")]
DEVOICE_MIN_MS = 25.0


def voiced_ms(x, sr, t0, t1):
    win = int(sr * 0.03)
    hop = int(sr * 0.0025)
    v = 0.0
    i0, i1 = int(sr * t0 / 1000), int(sr * t1 / 1000)
    for i in range(i0, max(i0 + 1, i1 - win), hop):
        s = x[i:i + win]
        if len(s) < win or np.sqrt((s ** 2).mean()) < 0.004:
            continue
        w = s * np.hanning(win)
        ac = np.correlate(w, w, "full")[win - 1:]
        a, b = int(sr / 500), int(sr / 120)
        if b < len(ac) and ac[a:b].max() > 0.35 * ac[0]:
            v += 2.5
    return v


def tail_checks(y, sr, lead_ms=0.0):
    """切り出したものの末尾に、後続の成分が残っていないか。"""
    pk = np.abs(y).max() + 1e-12
    fr = max(1, int(sr * 0.001))
    body = y[int(sr * lead_ms / 1000):]
    m = len(body) // fr
    if m < 20:
        return {"end_gap_ms": 0.0, "rise_db": 0.0, "tail_db": 0.0}
    r = np.sqrt((body[:m * fr].reshape(m, fr) ** 2).mean(axis=1) + 1e-20)
    db = 20 * np.log10(r / pk + 1e-12)
    db = db[:-5] if len(db) > 5 else db          # 終端5msのフェードは除く
    gap = 0.0
    for d in db[::-1]:
        if d < -45:
            gap += 1
        else:
            break
    tail = db[-20:] if len(db) >= 20 else db
    rise = float(tail.max() - tail.min()) if len(tail) > 3 else 0.0
    return {"end_gap_ms": round(gap, 1), "rise_db": round(rise, 1),
            "tail_db": round(float(np.mean(db[-5:])), 1)}


def main():
    os.makedirs(SND, exist_ok=True)
    # まず「ぱ」版のモーラ長を出す（境界が取れない字の代わりに使う）
    pa_mora = {}
    for k in KANA:
        x, sr = read_wav(os.path.join(BASE, "raw_ぱ", k + ".wav"))
        on = detect_onset_ms(x, sr)
        b, _ = closure_start(x, sr, on)
        pa_mora[k] = (b - on) if b else 120.0

    stats = {"lead_ms": LEAD_MS, "methods": {}}
    for name, raw in METHODS:
        cut_dir = os.path.join(BASE, f"cut_{name}")
        norm_dir = os.path.join(BASE, f"norm_{name}")
        os.makedirs(cut_dir, exist_ok=True)
        os.makedirs(norm_dir, exist_ok=True)
        items, cuts = {}, {}
        found = 0
        for k in KANA:
            x, sr = read_wav(os.path.join(BASE, raw, k + ".wav"))
            on = detect_onset_ms(x, sr)
            # 後続が「さ」のときは無音ができないので、摩擦の立ち上がりで境目を探す。
            if name == "さ":
                b, info = fricative_start(x, sr, on)
            else:
                b, info = closure_start(x, sr, on)
            mora = (b - on) if b else None
            # 見つかった境界が「ぱ」版の1.6倍を超えるなら、第2モーラまで飲み込んでいる
            # とみなして採用しない（後続が母音・鼻音の方式で起きる）。
            plausible = mora is not None and mora <= pa_mora[k] * 1.6
            if plausible:
                found += 1
                use = mora
                how = "閉鎖"
            else:
                use = pa_mora[k]
                how = "ぱ版の長さで代用"
            end = int(sr * (on + use) / 1000)
            y = apply_fade_out(x[:end], sr)
            write_wav(os.path.join(cut_dir, k + ".wav"), y, sr)
            cuts[k] = (y, sr, on)
            items[k] = {"onset_ms": round(on, 1), "mora_ms": round(use, 1),
                        "how": how, "raw_boundary_ms": None if mora is None else round(mora, 1),
                        "closure_depth_db": info.get("closure_depth_db"),
                        "voiced_ms": round(voiced_ms(x, sr, on, on + use), 1)}
            items[k].update(tail_checks(y, sr, on - 0))
        # 音量をそろえる（外れ値は四分位範囲で除いて基準を決め、外れ値は増幅しない）
        vals = {k: a_weighted_rms(cuts[k][0], cuts[k][1]) for k in KANA}
        db = np.array([20 * np.log10(v + 1e-12) for v in vals.values()])
        q1, q3 = np.percentile(db, [25, 75])
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        inl = [v for v in vals.values() if lo <= 20 * np.log10(v + 1e-12) <= hi]
        target = float(np.median(inl))
        for k in KANA:
            y, sr, on = cuts[k]
            v = vals[k]
            out = 20 * np.log10(v + 1e-12)
            gain = 1.0 if not (lo <= out <= hi) else target / max(v, 1e-12)
            if np.abs(y).max() * gain > PEAK_CAP:
                gain *= PEAK_CAP / (np.abs(y).max() * gain)
            z = y * gain
            write_wav(os.path.join(norm_dir, k + ".wav"), z, sr)
            i0 = max(0, int(sr * (on - LEAD_MS) / 1000))
            write_wav(os.path.join(SND, f"{k}_{name}.wav"), z[i0:], sr)
        mo = [items[k]["mora_ms"] for k in KANA]
        dv = [k for k in KANA if items[k]["voiced_ms"] < DEVOICE_MIN_MS]
        leak = [k for k in KANA if items[k]["end_gap_ms"] >= 15 or items[k]["rise_db"] > 18]
        stats["methods"][name] = {
            "found": found, "n": len(KANA),
            "mora_min": min(mo), "mora_med": float(np.median(mo)), "mora_max": max(mo),
            "devoiced": dv, "leak": leak,
            "fallback": [k for k in KANA if items[k]["how"] != "閉鎖"],
            "items": items,
        }
        print(f"  {name:3s}: 境界を検出 {found}/{len(KANA)}字  "
              f"モーラ {min(mo):.0f}〜{max(mo):.0f}ms(中央{np.median(mo):.0f})  "
              f"無声化 {len(dv)}字  末尾に後続の疑い {len(leak)}字")
    with open(os.path.join(SND, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(f"  → {SND}/stats.json")


if __name__ == "__main__":
    main()
