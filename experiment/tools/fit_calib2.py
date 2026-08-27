#!/usr/bin/env python3
"""
calib2（追いバッチ・視覚のみ）の曲線当てはめ
=============================================
project/data_calib2_live/transfer_trials.csv には phase 列で
  calib  … 実験1（163人・聴覚＋視覚）
  calib2 … 追いバッチ（161人・視覚のみ）
の2つが入っている。

群Bのwarp表を作るには
  聴覚 … calib（実験1）にしか無いのでそこから
  視覚 … 使いたい phase から
という組み合わせで曲線が要る。analyze_calib_full.py 本体は phase を区別しないので、
ここで phase で切り分けたうえで同じ当てはめ関数を呼び、fit_logistic.csv 互換の表を出す。

出力（既定 project/data_calib2_live/warp_new/）:
  fit_logistic_calib2.csv  聴覚=calib / 視覚=calib2
  fit_logistic_calib1.csv  聴覚=calib / 視覚=calib   （同じ入力からの実験1版・比較用）
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_calib_full as A


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default="project/data_calib2_live/transfer_trials.csv")
    ap.add_argument("--out", default="project/data_calib2_live/warp_new")
    ap.add_argument("--fit-starts", type=int, default=6)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    raw = A.normalize(A.load(args.inp))
    base = A.base_filter(raw)
    main_all = A.main_target_rows(base)

    audio = [r for r in main_all if r["modality_g"] == "audio"]
    ga, na = A.default_gamma(audio, "audio")
    print(f"  聴覚 {len(audio)}行 gamma=1/{na}={ga:.5f}")

    for tag, phase in (("calib2", "calib2"), ("calib1", "calib")):
        vis = [r for r in main_all
               if r["modality_g"] == "visual" and (r.get("phase") or "") == phase]
        gv, nv = A.default_gamma(vis, "visual")
        n_p = len({r["participant_id"] for r in vis})
        print(f"  視覚[{phase}] {len(vis)}行 / {n_p}人 gamma=1/{nv}={gv:.5f}")
        p = os.path.join(args.out, f"fit_logistic_{tag}.csv")
        A.write_fit_logistic(p, audio, vis, ga, gv, "actual", args.fit_starts, 0.5, 0.15)
        print(f"  書き出し: {p}")


if __name__ == "__main__":
    main()
