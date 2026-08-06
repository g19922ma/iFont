#!/usr/bin/env python3
"""
聴覚2文字課題(audio2char)の切り出し位置を、復号後の座標に置き直す
==================================================================
audio2char.js は「ファイル先頭から c2_onset_s + c2_dur_s*frac/100 秒まで」を再生する。
ところが c2_onset_s=0.3 / c2_dur_s=0.2 は合成時に指定した名目値であって、
  (1) VOICEVOX が音素長を 10.6667 ミリ秒の格子へ量子化するぶん
  (2) mp3 の復号で先頭に入る 46.042 ミリ秒の遅れ
のどちらも見込んでいない。実測すると、C2 は実際には 334.04 または 344.71 ミリ秒から
始まり、526.04〜547.38 ミリ秒で終わる。つまり
  - frac=0 の切り出し点(300ms)は C2 の開始より 34〜45 ミリ秒手前にあり、
    全部聞かせるはずの C1 の末尾を削っていた。
  - frac=100 の切り出し点(500ms)は C2 の末尾より 26〜47 ミリ秒手前にあり、
    C2 の母音の後半が鳴っていなかった。
1文字課題と同じ欠陥である。

そこで、刺激ごとに復号後の座標での C2 の実体を manifest に持たせる。
  c2_gate_start_ms … 復号後のファイル先頭から数えた C2 の開始位置(ミリ秒)
  c2_avail_ms      … C2 のモーラ長(量子化後の実際の値。ミリ秒)
再生側は gate = (c2_gate_start_ms + c2_avail_ms * frac/100) / 1000 で切り出す。

モーラ長の求め方と検算は build_gate_windows.py と同じ。全刺激について、復号後の
全長が模型の予測値と一致することを確かめてから書き出す。

実行(VOICEVOX 0.25.2 を 127.0.0.1:50021 で起動しておくこと):
  python3 experiment/tools/build_gate_windows_2char.py
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_gate_windows as G   # noqa: E402

EXP = G.EXP
SR = G.SR
FRAME = G.FRAME_SAMPLES
PRE = G.PRE_FRAMES
DELAY = G.CODEC_DELAY_SAMPLES
GRANULE = G.MP3_GRANULE
MORA_DUR_S = 0.2
SPEAKER = 108


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="検算する刺激数(0=全部)")
    args = ap.parse_args()

    manifest_path = os.path.join(EXP, "audio2char_manifest.json")
    manifest = json.load(open(manifest_path))
    answer_key = json.load(open(os.path.join(EXP, "answer_key_2char.json")))
    stim_dir = os.path.join(EXP, "audio2char_stimuli")

    checked = 0
    stats = {}
    for i, stim in enumerate(manifest["stimuli"]):
        rec = answer_key.get("audio2char|" + stim["id"])
        if rec is None:
            sys.exit(f"正解表に無い刺激がある: {stim['id']}")
        # C1 は素のまま、C2 だけ無声破裂音の VOT 修正(c2_cmul)がかかる(build_2char_pool と同じ)
        f1c, f1v = G.phoneme_frames(rec["c1"], SPEAKER, None, MORA_DUR_S)
        f2c, f2v = G.phoneme_frames(rec["c2"], SPEAKER, rec.get("c2_cmul"), MORA_DUR_S)
        m1, m2 = f1c + f1v, f2c + f2v
        c2_start_ms = (PRE * FRAME + m1 * FRAME + DELAY) / SR * 1000
        c2_len_ms = m2 * FRAME / SR * 1000

        if args.limit == 0 or checked < args.limit:
            wav_n = (PRE + m1 + m2 + PRE) * FRAME
            dec_expect = math.ceil((wav_n + DELAY) / GRANULE) * GRANULE
            x, fr = G.decode_mp3(os.path.join(stim_dir, stim["file"]))
            if len(x) != dec_expect:
                sys.exit(f"{rec['c1']}{rec['c2']} ({stim['id']}): 復号後の長さ {len(x)} が "
                         f"模型の予測 {dec_expect} と違う")
            checked += 1
            if checked % 500 == 0:
                print(f"  検算 {checked} 件…", file=sys.stderr)

        stim["c2_gate_start_ms"] = round(c2_start_ms, 3)
        stim["c2_avail_ms"] = round(c2_len_ms, 3)
        key = (round(c2_start_ms, 2), round(c2_len_ms, 2))
        stats[key] = stats.get(key, 0) + 1

    manifest["codec_delay_ms"] = round(DELAY / SR * 1000, 3)
    manifest["gate_note"] = ("c2_gate_start_ms / c2_avail_ms = 復号後の座標での C2 の開始位置と"
                             "モーラ長(ミリ秒)。再生側は c2_onset_s / c2_dur_s(名目値)ではなく"
                             "この2つを使って切り出す。")
    if not args.dry_run:
        json.dump(manifest, open(manifest_path, "w"), ensure_ascii=False, indent=1)

    print(f"刺激 {len(manifest['stimuli'])} 件 / 復号長を検算した件数 {checked} 件(すべて一致)",
          file=sys.stderr)
    print("C2 の開始とモーラ長の分布(復号後・ミリ秒):", file=sys.stderr)
    for (s, d), n in sorted(stats.items()):
        print(f"  開始 {s:.2f} / 長さ {d:.2f} → {n} 件 "
              f"(旧コードの想定は 開始 300.00 / 長さ 200.00)", file=sys.stderr)
    if args.dry_run:
        print("(dry-run: ファイルは書き換えていない)", file=sys.stderr)
    else:
        print(f"書き出し: {manifest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
