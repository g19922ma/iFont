#!/usr/bin/env python3
"""
聞き取り確認に使う「数字」の音を作る
====================================
2026-08-25 作成。

**なぜ要るのか。** 音量確認の画面は、これまで**サンプルを鳴らすボタンを押しただけ**で
先へ進めた。押しても**実際に聞こえたかを確かめていない**ので、
iPhone の着信スイッチ（マナーモード）で音が消えている人がそのまま通過し、
70問を無音のまま答えてしまう。iOS は既定で **Web Audio もサイレントスイッチで消す**。

そこで「鳴った数字はどれか」を4択で答えてもらい、**正解しないと先へ進めない**ようにする。
音量不足・マナーモード・機器の不調のどれでも、ここで止まる。

**なぜ数字なのか。**
  ・本命8字（あ・か・が・ぱ・し・つ・ま・ら）と無関係なので、刺激の情報が漏れない
    （これまでのサンプルは本番の刺激そのものを5字ぶん聞かせていた）
  ・4つが互いにはっきり違う音なので、音量が足りているかの判定として素直である
  ・話者は本番と同じ**あみたろ**にするので、音量の基準としても正しい

**打ち切らない。** 本番の刺激はわざと曖昧に作ってあるが、この確認音は
**はっきり聞き取れること自体が目的**なので、合成したままの全長を使う。

出力: experiment/audio_check/<数字>.wav（1.wav 〜 4.wav）

使い方（COEIROINK v2 を起動しておくこと）:
  python3 experiment/tools/build_audio_check.py
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_carrier_takes import (SPEAKER_UUID, SPEAKER_NAME, STYLE_ID, STYLE_NAME,  # noqa: E402
                                 CREDIT, SYNTH, check_engine)

ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "experiment", "audio_check")
BASE = "http://127.0.0.1:50032"

# 数字 → 読み。**1〜4に絞る**（5以上を足すと選択肢が増えて画面が窮屈になる。
# 4択なら1回で25%、2回続けて正解を求めれば6%まで下がるので十分である）。
# 「し(4)」ではなく「よん」にする。「し」は本命8字に含まれるうえ、「ひ」と紛れやすい。
# 「7」を足すときも「なな」にすること（「しち」は避ける）。
DIGITS = {"1": "いち", "2": "に", "3": "さん", "4": "よん"}


def post(path, payload, raw=False, timeout=60):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if raw else json.loads(b)


def main():
    check_engine(BASE)
    os.makedirs(OUT, exist_ok=True)
    meta = {"engine": "COEIROINK v2", "speaker": SPEAKER_NAME, "speaker_uuid": SPEAKER_UUID,
            "style": STYLE_NAME, "style_id": STYLE_ID, "credit": CREDIT,
            "synth_params": SYNTH, "digits": DIGITS,
            "note": "聞き取り確認用。打ち切らない全長。本番の刺激とは別物である。"}
    for d, yomi in DIGITS.items():
        # アクセントはエンジン任せでよい（1語として自然に読ませるのが目的で、
        # 本番の刺激のように切り出すわけではないため）。
        pros = post("/v1/estimate_prosody",
                    {"speakerUuid": SPEAKER_UUID, "style_id": STYLE_ID, "text": yomi})
        payload = {"speakerUuid": SPEAKER_UUID, "styleId": STYLE_ID, "text": yomi,
                   "prosodyDetail": pros["detail"]}
        payload.update(SYNTH)
        wav = post("/v1/synthesis", payload, raw=True)
        p = os.path.join(OUT, f"{d}.wav")
        with open(p, "wb") as f:
            f.write(wav)
        print(f"  {d} 「{yomi}」 … {len(wav)/1024:.0f} KB → {p}")
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"\n  → {OUT}")
    print("  ⚠ 配信に含めるには experiment/tools/build_hosting.sh の一覧に足すこと。")


if __name__ == "__main__":
    main()
