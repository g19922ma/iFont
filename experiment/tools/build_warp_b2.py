#!/usr/bin/env python3
"""
群B（検証フェーズ）の warp 表を calib2 の曲線で作り直す
========================================================
build_warp_b.py をそのまま使い、入力の当てはめ表だけ差し替える版。
本番ファイル（experiment/transfer_warp.json / transfer_config.js）には**書かない**。
出力は project/data_calib2_live/warp_new/ に置く。

■ 実験1版との違い（2点）
1. 視覚の曲線を calib2（161人）の当てはめに差し替える。
   ただし **blur だけは実験1版も作る**（同一刺激なのに正答率が13〜20pt違う
   未解決の文脈効果があるため、どちらを採るかはユーザーが決める）。
2. 組み合わせの写し方 s_x(u)=100·u^k の k を、**字によらない固定値**にする。
   build_warp_b.py の qmap は字ごとの μ から k を作っていたが、実際に描画する
   transfer.js は config の composite_axis（字によらない固定 k）を**先に見る**
   ので、字ごとの表で逆引きした s(t) は「実際に見える絵」と一致しない。
   ここでは config に入れる固定 k と同じものを warp 側にも使う。

   固定 k の作り方（config のコメントと同じ流儀）:
       μ̄ = その方式の8字の μ の平均
       k  = ln(μ̄/100) / ln(0.5)      （u=0.5 でその方式の中点を通る）

使い方:
    python3 experiment/tools/build_warp_b2.py
"""
import csv, io, json, math, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_warp_b as B

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "project/data_calib2_live/warp_new")
TRIALS = os.path.join(ROOT, "project/data_calib2_live/transfer_trials.csv")
FIT2 = os.path.join(OUT, "fit_logistic_calib2.csv")
FIT1 = os.path.join(OUT, "fit_logistic_calib1.csv")

PAIRS = [("fade", "blur"), ("fade", "wipe"), ("reveal", "blur"), ("reveal", "wipe")]


def fixed_k(F, fam):
    """その方式の8字の μ の平均から固定指数 k を作る。"""
    mus = [F[("visual", ch, fam)]["mu"] for ch in B.CHARS]
    mubar = sum(mus) / len(mus)
    mubar = max(0.01, min(99.99, mubar))
    k = math.log(mubar / 100.0) / math.log(0.5)
    return mubar, max(0.05, min(20.0, k))


# --- qmap を固定 k 版に差し替える（build() の中から呼ばれる）------------------
_orig_qmap = B.qmap


def qmap_fixed(pv):
    k = pv.get("k_fixed")
    if k is None:
        return _orig_qmap(pv)
    out = [100.0 * ((i / (B.N_MAP - 1)) ** k) for i in range(B.N_MAP)]
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


B.qmap = qmap_fixed


def make_F(fit_visual, fit_audio_and_blur, blur_from):
    """視覚は fit_visual、聴覚は fit_audio_and_blur（実験1にしか無い）から。
    blur_from が 'exp1' なら blur の視覚曲線だけ実験1に差し替える。"""
    F = {}
    for key, v in fit_visual.items():
        if key[0] == "visual":
            F[key] = dict(v)
    for key, v in fit_audio_and_blur.items():
        if key[0] == "audio":
            F[key] = dict(v)
        elif blur_from == "exp1" and key[2] == "blur":
            F[key] = dict(v)
    return F


def main():
    os.makedirs(OUT, exist_ok=True)
    F2 = B.load_fits(FIT2)
    F1 = B.load_fits(FIT1)
    gates = B.gates_from_trials(TRIALS)
    base = 300.0

    krows = []
    for variant in ("blur_calib2", "blur_exp1"):
        F = make_F(F2, F1, "exp1" if variant == "blur_exp1" else "calib2")
        # 固定 k を求めて各当てはめ dict に埋める
        ks = {}
        for fam in B.FAMS:
            mubar, k = fixed_k(F, fam)
            ks[fam] = k
            for ch in B.CHARS:
                F[("visual", ch, fam)]["k_fixed"] = k
            krows.append(dict(variant=variant, family=fam,
                              mu_bar=round(mubar, 4), k=round(k, 4)))
        tables, log, ranges = B.build(F, gates, "rawp", base)
        axis = {}
        for a, b in PAIRS:
            axis[a + "+" + b] = {"uniform_k": round(ks[a], 3),
                                 "spatial_k": round(ks[b], 3)}
        doc = {"frame_ms": round(B.FRAME_MS, 4),
               "meta": {"space": "rawp", "base_anim_ms": base,
                        "made": "2026-08-27", "chars": B.CHARS,
                        "source": "calib2 (視覚161人) / 聴覚は実験1",
                        "blur_curve": "実験1" if variant == "blur_exp1" else "calib2",
                        "composite_k": axis,
                        "note": "生成元 build_warp_b2.py。組み合わせは字によらない固定 k。"
                                "本番反映前に transfer_config.js の composite_axis を同じ k に揃えること。"},
               "composite_axis": axis,
               "composite_map": ranges, "composite_map_n": B.N_MAP,
               "tables": tables}
        p = os.path.join(OUT, f"transfer_warp_rawp_{variant}.json")
        json.dump(doc, io.open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print(f"  書き出し: {os.path.basename(p)} ({os.path.getsize(p)//1024} KB)")
        with io.open(os.path.join(OUT, f"warp_report_{variant}.csv"), "w",
                     encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(log[0].keys()))
            w.writeheader()
            for r in log:
                w.writerow(r)

    with io.open(os.path.join(OUT, "composite_k.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(krows[0].keys()))
        w.writeheader()
        for r in krows:
            w.writerow(r)
    print("  書き出し: composite_k.csv, warp_report_*.csv")


if __name__ == "__main__":
    main()
