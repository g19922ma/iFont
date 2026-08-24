#!/usr/bin/env python3
"""
刺激の末尾に、余分な音や無音が混ざっていないかを数値で確かめる
==============================================================
2026-08-24 作成。**前の版で「鼻音の残りなし（0/68）」と誤判定した反省から作った検査。**

前の版（後続が「ん」）は、鼻音が残っているかを「1.5〜5kHz の割合」で見ていたが、
母音の種類ごとにしきい値を変える必要があり、イ段では母音と鼻音が音響的に区別できず、
**34字で鼻音が残っているのに「残りなし」と判定した**。

いまの版（後続が無声破裂音「ぱ」）では、混ざりうるのは
  ・後続の**閉鎖区間**（＝ほぼ無音）
  ・後続の**破裂**（＝急に大きくなる音）
の2つだけである。どちらも「音量」だけで分かるので、母音の種類に依存しない。
この検査は**その数値をそのまま出す**（合否だけでなく根拠を残すため）。

見るもの
--------
  末尾レベル … 刺激の終わりぎわ（フェードの手前 20ms）の音量が、
               その刺激のピークより何dB下か。
               **これが -40dB より下なら「閉鎖の無音が入り込んだ」疑い**。
  無音の混入 … 刺激の中に、ピークより 45dB 以上小さい状態が 15ms 以上続く区間が
               あるか（頭の前置き 50ms は除く）。破裂音の閉鎖は字の頭にもあるので、
               **onset より後ろだけ**を見る。
  立ち上がり … 終わりぎわ10msが、その手前10msより 12dB 以上大きくなっていないか。
               後続の破裂が入り込むと、こういう急な立ち上がりが出る。
               （「末尾がいちばん大きい」では判定できない——打ち切りは母音の途中で
                 切るので、山が末尾に来るのは普通である。）

使い方
------
  python3 experiment/tools/check_stimulus_tail.py
  python3 experiment/tools/check_stimulus_tail.py --verbose   # 全字の数値を出す
"""
import argparse
import json
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)

TAIL_WIN_MS = 20.0     # 末尾のどこを見るか（フェード5msの手前 20ms）
FADE_MS = 5.0
QUIET_DB = -40.0       # 末尾がこれより下なら無音の混入を疑う
GAP_DB = -45.0         # 「無音」と見なす落差
GAP_MS = 15.0          # それが何ミリ秒続いたら混入と見なすか
RISE_DB = 12.0         # 終わりぎわ10msが手前10msより何dB大きければ「破裂の混入」を疑うか


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return x.astype(np.float64) / 32768.0, sr


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest",
                    default=os.path.join(EXP, "transfer_audio_manifest_amitaro.json"))
    ap.add_argument("--dir", default=os.path.join(EXP, "transfer_stimuli_amitaro"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    man = json.load(open(args.manifest, encoding="utf-8"))
    # モーラ長（切り出しの記録）。「終わり近く」の刺激だけを破裂の検査にかけるため。
    crop_path = os.path.join(EXP, "tts_candidates_carrier2", "cut", "crop_report.json")
    mora = {}
    if os.path.exists(crop_path):
        mora = {k: v.get("mora_ms") for k, v in
                json.load(open(crop_path, encoding="utf-8"))["items"].items()}
    rows = []

    def walk(o):
        if isinstance(o, dict):
            if "file" in o and isinstance(o["file"], str):
                rows.append(o)
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(man)
    if not rows:
        sys.exit("索引から刺激を読み取れませんでした")

    worst_tail = []
    gaps = []
    louder = []
    per_kana = {}
    for r in rows:
        f = os.path.basename(r["file"])
        path = os.path.join(args.dir, f)
        if not os.path.exists(path):
            sys.exit(f"ファイルがありません: {path}")
        x, sr = read_wav(path)
        kana = r.get("char") or r.get("kana") or f.split("_")[0]
        lead_ms = float(r.get("lead_ms", 50.0))
        peak = np.abs(x).max() + 1e-12
        n_fade = int(sr * FADE_MS / 1000)
        n_tail = int(sr * TAIL_WIN_MS / 1000)
        seg = x[max(0, len(x) - n_fade - n_tail): len(x) - n_fade]
        tail_db = 20 * np.log10(np.sqrt((seg ** 2).mean()) / peak + 1e-12) if len(seg) else 0.0
        # 刺激の中身（前置きより後ろ）で、**終わりに接している**無音を探す。
        # ⚠ 途中の無音は数えない。ら行の弾き音（舌で一瞬はじく音）は、その字自身の
        #   性質として 15ms ほどの無音を持つので、それを不合格にしてはいけない。
        #   後続の閉鎖が混ざった場合は、必ず**刺激の終わりに接して**現れる。
        body = x[int(sr * lead_ms / 1000):]
        fr = max(1, int(sr * 0.005))
        m = len(body) // fr
        end_gap = 0.0
        if m:
            rms = np.sqrt((body[:m * fr].reshape(m, fr) ** 2).mean(axis=1) + 1e-20)
            db = 20 * np.log10(rms / peak + 1e-12)
            drop = int(round(FADE_MS / 5))          # 終端のフェードぶんは除く
            db = db[:-drop] if drop and len(db) > drop else db
            for d in db[::-1]:                      # 終わりから遡って数える
                if d < GAP_DB:
                    end_gap += 5
                else:
                    break
        # 「後続の破裂が入り込んだ」判定。
        # ⚠ 「末尾がいちばん大きい」では判定できない。打ち切りは母音の途中で切るので、
        #   音の山が末尾に来るのはむしろ普通である（最初はこれで127本を誤って弾いた）。
        #   破裂は**急に立ち上がる**のが特徴なので、終わりぎわ10msが
        #   その手前10msより RISE_DB 以上大きくなったときだけ疑う。
        # 後続の破裂は**閉鎖のあとにしか来ない**。上の2つの検査で「終わりに無音は無い」
        # ことが示せているので、破裂が混ざりうるのは**モーラの終わり際まで残した刺激**
        # だけである。短い打ち切りで出る急な立ち上がりは、その字自身の音
        # （ら行の弾き音の開放、無声破裂音のあとに母音が立ち上がるところ）なので数えない。
        gate = r.get("gate_ms")
        content_ms = (len(x) / sr * 1000.0) - lead_ms
        mm = mora.get(kana)
        near_end = (gate in (None, "full")) or (mm is not None and float(gate) >= mm - 25.0)
        comparable = content_ms >= 30.0 and near_end
        n10 = int(sr * 0.010)
        e = len(x) - n_fade
        last10 = x[max(0, e - n10):e]
        prev10 = x[max(0, e - 2 * n10):max(0, e - n10)]
        rise_db = 0.0
        if len(last10) and len(prev10):
            a = np.sqrt((last10 ** 2).mean()) + 1e-12
            b = np.sqrt((prev10 ** 2).mean()) + 1e-12
            rise_db = 20 * np.log10(a / b)
        rec = {"file": f, "kana": kana, "gate": gate,
               "tail_db": round(float(tail_db), 1), "end_gap_ms": round(float(end_gap), 1),
               "rise_db": round(float(rise_db), 1)}
        per_kana.setdefault(kana, []).append(rec)
        if comparable and tail_db < QUIET_DB:
            worst_tail.append(rec)
        if end_gap >= GAP_MS:
            gaps.append(rec)
        if comparable and rise_db > RISE_DB:
            louder.append(rec)

    print(f"  刺激 {len(rows)} 本を実測しました（{args.dir}）")
    tails = [v["tail_db"] for vs in per_kana.values() for v in vs]
    print(f"  末尾20msの音量（ピーク比）: 最小 {min(tails):.1f} / 中央 {np.median(tails):.1f} / "
          f"最大 {max(tails):.1f} dB")
    print(f"  ── 判定 ──")
    ok = True
    if worst_tail:
        ok = False
        print(f"  ✗ 末尾が {QUIET_DB}dB より静か（閉鎖の無音が入り込んだ疑い）: {len(worst_tail)} 本")
        for v in worst_tail[:12]:
            print(f"      {v['file']}  末尾 {v['tail_db']}dB")
    else:
        print(f"  ✓ 末尾が {QUIET_DB}dB より静かな刺激は 0 本"
              f"（＝後続の閉鎖は1本も入り込んでいない）")
    if gaps:
        ok = False
        print(f"  ✗ 刺激の終わりに接した {GAP_MS}ms 以上の無音がある（閉鎖の混入）: {len(gaps)} 本")
        for v in gaps[:12]:
            print(f"      {v['file']}  終端の無音 {v['end_gap_ms']}ms")
    else:
        print(f"  ✓ 終わりに接した {GAP_MS}ms 以上の無音がある刺激は 0 本"
              f"（途中の無音は数えない。ら行の弾き音は本来もっているため）")
    if louder:
        ok = False
        print(f"  ✗ 終わりぎわが急に {RISE_DB}dB 以上大きくなる（後続の破裂の混入）: {len(louder)} 本")
        for v in louder[:12]:
            print(f"      {v['file']}  立ち上がり +{v['rise_db']}dB")
    else:
        print(f"  ✓ 終わりぎわが {RISE_DB}dB 以上急に大きくなる刺激は 0 本"
              "（モーラの終わり際まで残した刺激だけを見ている。"
              "破裂は閉鎖のあとにしか来ないので、上の2つと合わせて混入なしと言える）")

    if args.verbose:
        print("\n  字ごと（全長の刺激のみ）:")
        for k in sorted(per_kana):
            full = [v for v in per_kana[k] if v["gate"] in (None, "full")]
            for v in full:
                print(f"    {k}  末尾 {v['tail_db']:6.1f}dB  終端の無音 {v['end_gap_ms']:5.1f}ms  立ち上がり {v['rise_db']:+5.1f}dB")

    print()
    print("合格: 末尾に余分な音も無音も混ざっていない。" if ok
          else "不合格: 上の刺激を作り直すこと。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
