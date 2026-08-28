#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=========================================================================
4つの「合わせ方」を並べて見比べるプレビュー（研究者用・参加者には配らない）
=========================================================================

何のためのページか
------------------
較正のデータは 2 通りに読める（正答率 / 情報量）。合わせ方も 2 通りある
（形まで合わせる / 中点だけ合わせる）。2×2 で 4 条件になる。

                       形まで合わせる          中点だけ合わせる
    正答率            ① 正答率揃え            ③ 50%正答率揃え
    情報量            ② エントロピー揃え      ④ 50%エントロピー揃え

このページは、**同じ字・同じ方式で 4 条件を縦に並べ**、打ち切り 7 点の絵を
横に並べて見比べる。実時間 300ms の再生ボタンつき。

作り方の要点（build_warp_preview.py / build_warp_preview_info.py と同じ手口）
----------------------------------------------------------------------------
1. **描画は書き直さない。** experiment/transfer.js の
   `const SIZE = CFG.visual.size_px;` 〜 `function loadImage(` の直前までを
   そのまま切り出して貼る。ここに出る絵は参加者が見るものと同じ。
2. **file:// で開けるように外から読むものは全部埋め込む。**
   文字画像は data URI（getImageData を使う 点が増える／端から が canvas 汚染で
   落ちないように）。表・数値は JSON として <script> に埋め込む。
3. 本番の transfer_warp.json / transfer_config.js / transfer.js は読むだけ。
4. `build_hosting.sh` の公開一覧に入れない（あれは明示の許可リストなので、
   足さないかぎり配られない）。念のため noindex,nofollow も入れる。

必要なもの（先に回しておく）
    python3 experiment/tools/analyze_information.py
    python3 experiment/tools/build_warp_v5_info.py
    python3 experiment/tools/build_warp_mid.py

使い方:
    python3 experiment/tools/build_warp_preview_4cond.py
    open experiment/warp_preview_4cond.html
========================================================================="""
import base64
import io
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_warp_mid as MID                                  # noqa: E402
import build_warp_b4 as B4                                    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXP = os.path.join(ROOT, "experiment")
CAL = os.path.join(ROOT, "project", "data_calib2_live")
INFO = os.path.join(CAL, "analysis_information")
OUT = os.path.join(EXP, "warp_preview_4cond.html")

CHARS = B4.CHARS
FAMS = B4.FAMS
LAB = B4.LAB


# ---------------------------------------------------------------------------
def slice_transfer_js():
    src = io.open(os.path.join(EXP, "transfer.js"), encoding="utf-8").read()
    b = src.find("const SIZE = CFG.visual.size_px;")
    e = src.find("function loadImage(")
    if b < 0 or e <= b:
        raise SystemExit(
            "transfer.js から描画部分を切り出せない。\n"
            "  目印: 'const SIZE = CFG.visual.size_px;' 〜 'function loadImage(' \n"
            "  関数の並びが変わったなら、この目印も直すこと。")
    s = src[b:e]
    for name in ("function fadeDraw", "function revealDraw", "function blurDraw",
                 "function wipeDraw", "const RENDERERS", "function warpSeries",
                 "function seriesAt", "function progressFn"):
        if name not in s:
            raise SystemExit(f"切り出した範囲に {name} が入っていない")
    return s


def load_config():
    js = ("global.window={};require(%s);"
          "process.stdout.write(JSON.stringify(global.window.TRANSFER_CONFIG));"
          % json.dumps(os.path.join(EXP, "transfer_config.js")))
    out = subprocess.run(["node", "-e", js], capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def load_images():
    d = {}
    for ch in CHARS:
        with open(os.path.join(EXP, "base", ch + ".png"), "rb") as f:
            d[ch] = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    return d


def load_tables():
    out = {}
    for key, label, path in MID.COND:
        if not os.path.exists(path):
            raise SystemExit(
                f"{path} が無い（条件 {label}）。先に:\n"
                "    python3 experiment/tools/analyze_information.py\n"
                "    python3 experiment/tools/build_warp_v5_info.py\n"
                "    python3 experiment/tools/build_warp_mid.py")
        doc = json.load(io.open(path, encoding="utf-8"))
        n = len(doc["tables"]["fade"]["あ"]["proposed"])
        out[key] = {"label": label, "doc": doc,
                    "covers_ms": round((n - 1) * doc["frame_ms"], 1),
                    "path": os.path.relpath(path, ROOT)}
        print(f"  {key:<11} {label}  {n}点（{(n-1)*doc['frame_ms']:.0f}ms まで）"
              f"  {out[key]['path']}")
    return out


def comfort_facts():
    """群C（見え心地）の実物から、本数・1本の長さ・実際にかかった時間を拾う。

    ⚠ ここは**推測を書かない**。設定ファイルと実データから計算する。
      ・本数 … transfer_comfort_config.js の families × presentations_by_family
      ・1本の長さ … transfer_comfort.js の makePlayer と同じ式
                   cycle = 字数 × (アニメ長 ＋ 字間) ＋ hold ＋ gap
                   （1字だけのときは字間を足さない）
        アニメ長は warp 表の数値列の長さで決まる（(点数−1)×frame_ms）。
        本番 transfer_warp.json は 8点＝116.7ms、今回の4条件は 19点＝300ms。
      ・実際にかかった時間 … transfer_wellbeing.csv の duration_s
    """
    js = ("global.window={};require(%s);"
          "process.stdout.write(JSON.stringify(global.window.TRANSFER_COMFORT_CONFIG));"
          % json.dumps(os.path.join(EXP, "transfer_comfort_config.js")))
    c = json.loads(subprocess.run(["node", "-e", js], capture_output=True,
                                  check=True).stdout.decode("utf-8"))
    items = []
    for fam in c["families"]:
        for pres in c.get("presentations_by_family", {}).get(fam, c["presentations"]):
            items.append((fam, pres))
    t = c["timing"]

    def cycle(pres, anim_ms):
        n = 1 if pres == "single" else len(c["sequence"])
        step = anim_ms if pres == "single" else anim_ms + t["inter_char_gap_ms"]
        k = "single" if pres == "single" else "sequence"
        return n * step + t[k]["hold_ms"] + t[k]["gap_ms"]

    # 本番表（8点）と今回の4条件（19点）でのループ長
    prod = json.load(io.open(os.path.join(EXP, "transfer_warp.json"), encoding="utf-8"))
    anim_prod = (len(prod["tables"]["fade"]["あ"]["proposed"]) - 1) * prod["frame_ms"]
    anim_new = 300.0
    loops = {}
    for pres in ("single", "row5", "swap5"):
        loops[pres] = {"prod_ms": round(cycle(pres, anim_prod)),
                       "new_ms": round(cycle(pres, anim_new))}

    w = pd.read_csv(os.path.join(CAL, "transfer_wellbeing.csv"), low_memory=False)
    w = w[w["is_test"] != True]                                       # noqa: E712
    dur = pd.to_numeric(w["duration_s"], errors="coerce").dropna()
    return {"n_items": len(items),
            "items": [{"family": f, "presentation": p} for f, p in items],
            "families": c["families"], "presentations": c["presentations"],
            "sequence_len": len(c["sequence"]),
            "n_rating_items": len(c["items"]),
            "anim_prod_ms": round(anim_prod, 1), "anim_new_ms": anim_new,
            "loops": loops,
            "n_people": int(len(w)),
            "dur_median_s": float(dur.median()), "dur_mean_s": float(dur.mean()),
            "dur_q1_s": float(dur.quantile(.25)), "dur_q3_s": float(dur.quantile(.75))}


def load_curves():
    """視覚の較正曲線（正答率・単調回帰）。図の縦軸「読み取れる度合い」に使う。"""
    d = pd.read_csv(os.path.join(INFO, "curves_info.csv"))
    out = {}
    for tag in ("acc", "info"):
        s = d[(d["target"] == tag) & (d["modality"] == "visual")]
        for r in s.itertuples():
            out.setdefault(tag, {})[f"{r.char}|{r.family}"] = {
                "xs": [float(x) for x in str(r.xs).split("|")],
                "ys": [float(y) for y in str(r.ys).split("|")]}
        a = d[(d["target"] == tag) & (d["modality"] == "audio")]
        for r in a.itertuples():
            out.setdefault(tag + "_audio", {})[r.char] = {
                "xs": [float(x) for x in str(r.xs).split("|")],
                "ys": [float(y) for y in str(r.ys).split("|")]}
    return out


def check_js(html):
    """書き出した <script> を node で構文検査する。

    ⚠ このページの JavaScript は Python の文字列の中にある。引用符を1つ落としても
      Python は通り、ブラウザで初めて落ちる（実際に一度やった）。書き出すたびに
      機械に読ませて、壊れたページを配らないようにする。
    """
    import re
    import tempfile
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    for i, b in enumerate(blocks):
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8",
                                         delete=False) as f:
            f.write(b)
            p = f.name
        try:
            r = subprocess.run(["node", "--check", p], capture_output=True)
            if r.returncode != 0:
                raise SystemExit("書き出した JavaScript が壊れている"
                                 f"（{i + 1} 個目の <script>）:\n"
                                 + r.stderr.decode("utf-8", "replace"))
        finally:
            os.unlink(p)
    print(f"    構文検査: <script> {len(blocks)} 個 すべて node --check を通過")


# ---------------------------------------------------------------------------
def main():
    print("[1] transfer.js から描画＋再生を切り出す")
    js_slice = slice_transfer_js()
    print(f"    {js_slice.count(chr(10))} 行")

    print("[2] transfer_config.js を JSON に")
    cfg = load_config()
    gates = {ch: cfg["visual"]["gates_ms"].get(ch, cfg["visual"]["gates_ms"]["_default"])
             for ch in CHARS}

    print("[3] 文字画像を data URI に")
    imgs = load_images()

    print("[4] warp 表 4 種を読む")
    tables = load_tables()

    print("[5] 数値（build_warp_mid.py の出力）を読む")
    gm = pd.read_csv(os.path.join(CAL, "warp_mid", "gate_metrics_4cond.csv"))
    lg = pd.read_csv(os.path.join(CAL, "warp_mid", "build_log_mid.csv"))
    cc = pd.read_csv(os.path.join(CAL, "warp_mid", "ceiling_vs_observed.csv"))
    print(f"    gate_metrics_4cond.csv {len(gm)}行 / build_log_mid.csv {len(lg)}行")

    curves = load_curves()

    print("[6] 群C（見え心地）の実物から本数・長さ・所要時間を拾う")
    cf = comfort_facts()
    print(f"    本数 {cf['n_items']}本 / 1本の長さ 1字={cf['loops']['single']['prod_ms']}ms"
          f"（4条件の表なら {cf['loops']['single']['new_ms']}ms）"
          f" 5字={cf['loops']['row5']['prod_ms']}ms（同 {cf['loops']['row5']['new_ms']}ms）")
    print(f"    実績 {cf['n_people']}人 / 所要時間 中央 {cf['dur_median_s']/60:.1f}分"
          f"（四分位 {cf['dur_q1_s']/60:.1f}〜{cf['dur_q3_s']/60:.1f}分）")

    # 実用域（正答率曲線の可動域 5%〜95%）と、③④ がそこを走り抜ける時間
    win = {}
    for fam in FAMS:
        for ch in CHARS:
            r = gm[(gm.family == fam) & (gm.char == ch)].iloc[0]
            win[f"{ch}|{fam}"] = [float(r.usable_lo), float(r.usable_hi),
                                  round((float(r.usable_hi) - float(r.usable_lo)) * 3.0, 1)]

    # 中点（③④の作り方そのもの）
    mid = {}
    for r in lg.itertuples():
        mid[f"{r.target}|{r.char}|{r.family}"] = dict(
            t_half=float(r.t_half_ms), s_half=float(r.s_half_pct), t0=float(r.t0_ms),
            a_bottom=float(r.audio_bottom), a_top=float(r.audio_top),
            v_bottom=float(r.visual_bottom), v_top=float(r.visual_top),
            outside=str(r.mid_outside) if isinstance(r.mid_outside, str) else "")

    cells = gm.to_dict(orient="records")

    data = {
        "chars": CHARS, "fams": FAMS, "lab": LAB, "gates": gates, "images": imgs,
        "conds": [{"key": k, "label": l, "path": tables[k]["path"]}
                  for k, l, _ in MID.COND],
        "tables": {k: v["doc"] for k, v in tables.items()},
        "cells": cells, "win": win, "mid": mid, "curves": curves, "comfort": cf,
        "ceiling": cc.to_dict(orient="records"),
        "src": {
            "curves": os.path.relpath(os.path.join(INFO, "curves_info.csv"), ROOT),
            "metrics": os.path.relpath(
                os.path.join(CAL, "warp_mid", "gate_metrics_4cond.csv"), ROOT),
            "log": os.path.relpath(os.path.join(CAL, "warp_mid", "build_log_mid.csv"), ROOT)},
    }

    html = PAGE.replace("/*__DATA__*/", "const DATA = " + json.dumps(
        data, ensure_ascii=False, separators=(",", ":")) + ";")
    html = html.replace("/*__CFG__*/", "const CFG = window.TRANSFER_CONFIG = " + json.dumps(
        cfg, ensure_ascii=False, separators=(",", ":")) + ";")
    html = html.replace("/*__TRANSFER_JS_SLICE__*/", js_slice)

    io.open(OUT, "w", encoding="utf-8").write(html)
    check_js(html)
    print(f"\n書き出し: {os.path.relpath(OUT, ROOT)}  ({os.path.getsize(OUT)//1024} KB)")
    print("  open experiment/warp_preview_4cond.html")
    print("  ※ build_hosting.sh の FILES に入れていないので配られない")


# ===========================================================================
PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>4つの合わせ方（研究者用）</title>
<style>
:root{
  --bg:#faf8f4; --fg:#1c1a17; --muted:#6b6560; --accent:#b45309; --line:#ded6c8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c; --card:#ffffff; --canvasbg:#ffffff;
  --c1:#8a3ea8; --c2:#0f766e; --c3:#c2410c; --c4:#1d4ed8;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
    --card:#211e19; --ok:#4ade80; --bad:#f87171;
    --c1:#cf95e6; --c2:#5ec8bb; --c3:#f0a06a; --c4:#8fb4ff;
  }
}
:root[data-theme="dark"]{
  --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
  --card:#211e19; --ok:#4ade80; --bad:#f87171;
  --c1:#cf95e6; --c2:#5ec8bb; --c3:#f0a06a; --c4:#8fb4ff;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);
  font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  line-height:1.75;max-width:1280px;margin:0 auto;padding:2rem 1.2rem 6rem}
h1{font-size:1.6rem;border-bottom:2px solid var(--accent);padding-bottom:.5rem;line-height:1.4}
h2{font-size:1.22rem;margin-top:3rem;color:var(--accent);
   border-bottom:1px solid var(--line);padding-bottom:.3rem}
h3{font-size:1rem;margin-top:1.8rem}
p{margin:.6rem 0}
.lead{color:var(--muted);font-size:.94rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:.9rem 1.2rem;margin:1rem 0}
.card.note{border-left:5px solid var(--accent)}
.card.bad{border-left:5px solid var(--bad)}
.small{font-size:.83rem;color:var(--muted)}
code{background:color-mix(in srgb,var(--fg) 7%,transparent);padding:.05rem .3rem;
  border-radius:4px;font-size:.88em}
.tbl{border-collapse:collapse;width:100%;font-size:.8rem;margin:.8rem 0}
.tbl th,.tbl td{border:1px solid var(--line);padding:.26rem .5rem;text-align:left}
.tbl th{background:color-mix(in srgb,var(--accent) 12%,var(--card));font-weight:600}
.tbl td.num,.tbl th.num{text-align:right;font-variant-numeric:tabular-nums}
.tblwrap{overflow-x:auto}
.k1{color:var(--c1);font-weight:700}
.k2{color:var(--c2);font-weight:700}
.k3{color:var(--c3);font-weight:700}
.k4{color:var(--c4);font-weight:700}

/* 2x2 の見取り図 */
table.two{border-collapse:collapse;font-size:.86rem;margin:.8rem auto}
table.two th,table.two td{border:1px solid var(--line);padding:.5rem .9rem;text-align:center}
table.two th{background:color-mix(in srgb,var(--accent) 10%,var(--card));font-weight:600}
table.two td b{font-size:.95rem}
table.two td span{display:block;font-size:.75rem;color:var(--muted)}

#bar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 93%,transparent);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
  padding:.55rem 1.2rem;margin:0 -1.2rem 1.2rem;
  display:flex;flex-wrap:wrap;gap:.5rem 1.1rem;align-items:center;font-size:.85rem}
#bar label{display:flex;align-items:center;gap:.32rem;white-space:nowrap}
#bar select,#bar button{font:inherit;font-size:.85rem;padding:.15rem .4rem;
  background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px}
#bar button{cursor:pointer}
#bar button:hover{border-color:var(--accent)}

.gridwrap{overflow-x:auto;margin:.8rem 0 1.4rem}
table.frames{border-collapse:separate;border-spacing:0;font-size:.75rem}
table.frames th,table.frames td{padding:.16rem .22rem;vertical-align:top}
table.frames th.chh{text-align:left;font-size:1.7rem;font-weight:700;
  padding-right:.6rem;white-space:nowrap;vertical-align:middle}
table.frames th.gh{color:var(--muted);font-weight:600;text-align:center;font-size:.72rem}
table.frames tr.sep td,table.frames tr.sep th{border-bottom:1.5px solid var(--line)}
table.frames tr.r0 td,table.frames tr.r0 th{background:color-mix(in srgb,var(--c1) 6%,transparent)}
table.frames tr.r1 td,table.frames tr.r1 th{background:color-mix(in srgb,var(--c2) 6%,transparent)}
table.frames tr.r2 td,table.frames tr.r2 th{background:color-mix(in srgb,var(--c3) 8%,transparent)}
table.frames tr.r3 td,table.frames tr.r3 th{background:color-mix(in srgb,var(--c4) 8%,transparent)}
.cell{display:flex;flex-direction:column;align-items:center;gap:.12rem}
.cell canvas{width:88px;height:88px;background:var(--canvasbg);
  border:1px solid var(--line);border-radius:4px}
.cell.blank canvas{border:2px solid var(--bad)}
.cell.sat canvas{border:2px solid var(--ok)}
.cell .cap{font-size:.66rem;color:var(--muted);text-align:center;line-height:1.35;
  font-variant-numeric:tabular-nums}
.cell .cap b{color:var(--fg);font-weight:700}
.rowlbl{font-size:.72rem;white-space:nowrap;vertical-align:middle;line-height:1.4}
.playbtn{font:inherit;font-size:.72rem;padding:.1rem .45rem;cursor:pointer;
  background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:5px}
.playbtn:hover{border-color:var(--accent)}
.flag{font-size:.66rem;font-weight:700;text-align:center;line-height:1.3}
.flag.bad{color:var(--bad)}
.flag.ok{color:var(--ok)}

figure{margin:1.4rem 0 2rem}
figcaption{font-size:.85rem;margin-top:.4rem;padding-left:.7rem;
  border-left:3px solid var(--accent);color:var(--fg)}
.figwrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);
  border-radius:10px;padding:.5rem}
svg.fig{display:block;max-width:100%;height:auto;margin:0 auto}
svg text{font-family:"Hiragino Sans","Yu Gothic",sans-serif;fill:var(--fg)}
svg .lbl{fill:var(--muted);font-size:10.5px}
svg .tiny{font-size:9px;fill:var(--muted)}
svg .ttl{fill:var(--fg);font-size:12px;font-weight:700}
svg .ax{stroke:var(--muted);stroke-width:1;fill:none}
svg .grid{stroke:var(--line);stroke-width:1;stroke-dasharray:2 3;fill:none}
.legend{font-size:.78rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:.2rem 1.1rem;
  margin:.3rem 0 .1rem}
.legend i{display:inline-block;width:16px;height:0;border-top:2.5px solid currentColor;
  vertical-align:middle;margin-right:.25rem}
.pill{display:inline-block;border-radius:5px;padding:0 .4rem;font-size:.75rem;font-weight:700}
.pillbad{background:color-mix(in srgb,var(--bad) 20%,transparent);color:var(--bad)}
.pillok{background:color-mix(in srgb,var(--ok) 20%,transparent);color:var(--ok)}
.pillwarn{background:color-mix(in srgb,var(--warn) 22%,transparent);color:var(--warn)}
details{margin:.6rem 0}
summary{cursor:pointer;font-size:.88rem;color:var(--accent)}
td.hot{background:color-mix(in srgb,var(--bad) 30%,transparent);font-weight:700}
td.warm{background:color-mix(in srgb,var(--warn) 18%,transparent)}
td.cool{background:color-mix(in srgb,var(--ok) 16%,transparent)}
</style>
</head>
<body>

<h1>4つの「合わせ方」を並べて見る</h1>
<p class="lead">研究者用。参加者には配らない（<code>build_hosting.sh</code> の公開一覧に入れていない）。
描画は <code>experiment/transfer.js</code> の本文をそのまま切り出して動かしているので、
ここに出る絵は<strong>参加者が見るものと同じ</strong>。
本番の <code>transfer_warp.json</code> / <code>transfer_config.js</code> は読むだけで、書き換えていない。</p>

<div class="card note">
<h3 style="margin-top:.2rem">2×2 で 4 条件</h3>
<p>較正のデータは 2 通りに読める（<strong>正答率</strong> / <strong>情報量</strong>）。
合わせ方も 2 通りある（<strong>形まで合わせる</strong> / <strong>中点だけ合わせる</strong>）。</p>
<table class="two">
<tr><th></th><th>形まで合わせる</th><th>中点だけ合わせる</th></tr>
<tr><th>正答率</th>
    <td><b class="k1">① 正答率揃え</b><span>逆引きで進み方を歪める</span></td>
    <td><b class="k3">③ 50%正答率揃え</b><span>等速のまま開始をずらす</span></td></tr>
<tr><th>情報量</th>
    <td><b class="k2">② エントロピー揃え</b><span>逆引きで進み方を歪める</span></td>
    <td><b class="k4">④ 50%エントロピー揃え</b><span>等速のまま開始をずらす</span></td></tr>
</table>
<p style="font-size:.9rem"><strong>①②（左列）</strong>：
<code>時刻 t</code> →〔聴覚の曲線〕→ <code>目標の値</code> →〔視覚の曲線を逆引き〕→ <code>進み具合 s</code>。
曲線の形まで写すので、進み方そのものが歪む。</p>
<p style="font-size:.9rem"><strong>③④（右列）</strong>：進み方を歪めない。<strong>等速のまま、開始時刻 t0 だけをずらす</strong>。
<code>s(t) = clip(100·(t−t0)/300, 0, 100)</code>、
<code>t0 = t_half(聴覚) − s_half(視覚)/100 × 300</code>。
中点は「単調回帰の曲線が<strong>最大水準で到達する値（天井）の半分</strong>に達する最小の x」。</p>
<p class="small">4条件とも同じ 1 組の曲線
（<code id="src_curves"></code>・袋詰め PAVA）から作ってあるので、
条件間の違いは「軸の選び方」と「合わせ方」だけから来る。</p>
</div>

<div id="bar">
  <label>方式 <select id="sel_fam"></select></label>
  <label>字 <select id="sel_char"></select></label>
  <label>条件 <select id="sel_cond">
    <option value="proposed" selected>提案（転写）</option>
    <option value="baseline1">対照1（等速・ずらしなし）</option>
    <option value="baseline2">対照2（一次変換）</option></select></label>
  <label>向き <select id="sel_dir">
    <option value="ltr">左から</option><option value="rtl">右から</option></select></label>
  <button id="btn_play">▶ 4条件を順に再生</button>
  <button id="btn_theme">明暗</button>
</div>

<h2>1. 数字で確かめる</h2>

<h3>1-1. ③④ が実用域を走り抜ける時間</h3>
<p style="font-size:.92rem">③④ は等速（300ms で 0→100%）なので、進み具合は <code>3ms で 1pt</code> で動く。
だから <strong>実用域の幅（pt）×3 が、その方式が「読めない」から「読み切れる」まで走り抜ける時間（ms）</strong> になる。
これが打ち切りの間隔より短ければ、実用域の中に絵がほとんど落ちない。</p>
<p class="small">実用域＝較正の正答率曲線（単調回帰）の可動域 5%〜95% にあたる進み具合の区間。
4条件を同じ物差しで測るため、条件ごとに変えていない。</p>
<div class="tblwrap"><table class="tbl" id="t_transit"></table></div>

<h3>1-2. 4条件 × 4方式（8字ぶんまとめて）</h3>
<p class="small">「別々の絵」「中間の絵」は 1字あたり打ち切り7点中の平均。ほかは 8字×7点＝56点中の合計。
<strong>中間の絵</strong>＝その進み具合の絵を較正の正答率曲線に通した値が、可動域の 10%〜90% に入っている点の数
（＝床にも天井にも張り付いていない、読み取れ方が途中の絵）。
<strong>別々の絵</strong>だけを見てはいけない — うすいは不透明度が 256 段あるので、
読めない差でも「別の絵」に数えられてしまう。</p>
<p class="small"><strong>t=0 の進み具合</strong>にも注意。③④ は「開始時刻をずらす」ので、
ずらし量 t0 が負になると<strong>アニメが途中から始まる</strong>。
ぼやけの ③④ は平均 44% から始まる ＝ 参加者はいちばん最初のフレームで
すでに半分くっきりした字を見ることになり、「だんだんはっきりする」の出だしが無い。</p>
<div class="tblwrap"><table class="tbl" id="t_summary"></table></div>

<h3>1-3. 潰れているセル</h3>
<p class="small">「中間の絵」が 7点中 1点以下のセル。<strong>真っ白のまま → いきなり読み切れる</strong>に潰れている。</p>
<div id="d_dead"></div>

<h3>1-4. 中点が打ち切り窓の外に出る字</h3>
<div id="d_outside"></div>

<h3>1-5. 検算 ― 「天井の半分」と「実測 max の半分」</h3>
<p class="small">中点は「単調回帰の天井の半分」で採っている。「実測の最大値の半分」で採ったときと、中点がどれだけ動くか。
単調回帰は測った範囲の外へ外挿しないので両者はほぼ一致するが、実測の最大値は
「7点のうち一番高いところを選ぶ」という最大値選択の偏りを持つので、天井を採る。</p>
<div id="d_ceiling"></div>

<h2>2. 絵で見る（4条件を縦に並べる）</h2>
<p class="small">上のバーで方式・字を選ぶ。行は上から
<span class="k1">①</span> <span class="k2">②</span> <span class="k3">③</span> <span class="k4">④</span>。
赤枠＝<strong>s=0 の絵と同一</strong>（真っ白のまま）、緑枠＝<strong>読み取れる度合いが天井（可動域の90%以上）</strong>。
▶ はその行を実時間 300ms で流す。</p>
<div id="frames"></div>

<h2>3. 進み具合 s(t) と、読み取れる度合い</h2>
<div id="figs"></div>

<h2>4. 判定</h2>
<div class="card bad">
<h3 style="margin-top:.2rem">③④ で潰れるのは <span class="pillbad pill">うすい</span>
<span class="pillbad pill">点が増える</span></h3>
<p id="p_verdict" style="font-size:.93rem"></p>
<p class="small">「潰れる」＝打ち切り 7 点のうち、読み取れる度合いが床にも天井にも張り付いていない
「中間の絵」が 1 点以下。上の <a href="#frames">2. 絵で見る</a> で
方式＝うすい・字＝ま を選ぶと、③④ が「真っ白 3 枚 → いきなり読み切れる 4 枚」に
なっているのが目で見える。</p>
</div>
<div class="card">
<h3 style="margin-top:.2rem">ぼやけ・端から は ③④ でも成立する。ただし出だしが無い</h3>
<p id="p_verdict2" style="font-size:.93rem"></p>
</div>
<div class="card note">
<h3 style="margin-top:.2rem">4条件は「見え心地の比較」として成立するか</h3>
<p style="font-size:.93rem">成立する。ただし<strong>比べているものが条件によって違う</strong>ことを
はっきりさせておく必要がある。</p>
<ul style="font-size:.9rem">
<li><span class="k1">①</span><span class="k2">②</span>（形まで合わせる）… 進み方の
<strong>形</strong>が違う 2 本を比べる。どちらも「だんだん現れる」表示。</li>
<li><span class="k3">③</span><span class="k4">④</span>（中点だけ合わせる）… 進み方は
<strong>両方とも等速</strong>で、違うのは<strong>いつ始まるか</strong>だけ。
ぼやけ・端からでは「①②と③④のどちらが心地よいか」という比較になるが、
うすい・点が増えるでは「段階表示 対 ほぼステップ表示」という別の比較になる。</li>
</ul>
<p style="font-size:.9rem">後者は<strong>捨てる理由にならない</strong>。群Cにはすでに
<code>step</code>（中点まで何も出さず、そこで一気に完成形にする）という方式が
比較対象として入っている。③④ のうすい・点が増えるは、実質そこへ寄っていく。
「50%だけ揃えると方式によっては段階表示にならない」こと自体が結果である。</p>
</div>

<h2>5. 群C（見え心地）に何を入れるか</h2>
<div class="card">
<h3 style="margin-top:.2rem">いまの群Cの実物</h3>
<div id="d_comfort_now"></div>
<p class="small">1本の長さは <code>experiment/transfer_comfort.js</code> の
<code>makePlayer</code> と同じ式で計算した
（<code>1周 = 字数 ×（アニメ長 ＋ 字間）＋ 見せておく時間 ＋ 間</code>。1字だけのときは字間を足さない）。
アニメ長は warp 表の数値列の長さで決まるので、<strong>4条件の表に差し替えると 1 本が長くなる</strong>。
所要時間は <code>transfer_wellbeing.csv</code> の実測。</p>
</div>
<div class="card note">
<h3 style="margin-top:.2rem">提案</h3>
<div id="d_comfort_plan"></div>
</div>

<h2>6. 出どころ</h2>
<ul class="small" id="ul_src"></ul>

<script>
/*__CFG__*/
</script>
<script>
/*__TRANSFER_JS_SLICE__*/
</script>
<script>
/*__DATA__*/

const LAB = DATA.lab;
const CK = DATA.conds.map(c => c.key);
const CLAB = {}; DATA.conds.forEach(c => CLAB[c.key] = c.label);
const CCOL = {acc_shape:"--c1", info_shape:"--c2", acc_mid:"--c3", info_mid:"--c4"};
const ui = {fam:"fade", char:"__all__", cond:"proposed", dir:"ltr"};

function cssvar(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function cellOf(cond, fam, ch){
  return DATA.cells.find(c => c.cond === cond && c.family === fam && c.char === ch);
}
function nums(s){ return String(s).split("|").map(Number); }

// 画像は data URI から（file:// で canvas が汚染されないように）
function loadAll(){
  return Promise.all(DATA.chars.map(ch => new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => { imgs[ch] = im; res(); };
    im.onerror = () => rej(new Error(ch));
    im.src = DATA.images[ch];
  })));
}

// ---------------------------------------------------------------------------
// 表
// ---------------------------------------------------------------------------
function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;"); }

// 中央値（偶数個なら真ん中2つの平均。python 側の numpy.median と同じ定義にそろえる）
function median(a){
  const s = a.slice().sort((x,y) => x - y), n = s.length;
  return n % 2 ? s[(n-1)/2] : (s[n/2 - 1] + s[n/2]) / 2;
}

function buildTransit(){
  const t = document.getElementById("t_transit");
  let h = "<tr><th>方式</th><th class='num'>実用域(%)</th><th class='num'>走り抜ける時間(ms)</th>"
        + "<th>字ごと（実用域 → 走り抜ける時間）</th></tr>";
  DATA.fams.forEach(fam => {
    const w = DATA.chars.map(ch => DATA.win[ch + "|" + fam]);
    const lo = Math.min(...w.map(x => x[0])), hi = Math.max(...w.map(x => x[1]));
    const tr = w.map(x => x[2]).sort((a,b) => a-b);
    const med = median(tr);
    const cls = med < 45 ? "hot" : (med < 100 ? "warm" : "cool");
    h += "<tr><td><b>" + LAB[fam] + "</b></td>"
       + "<td class='num'>" + lo.toFixed(1) + "〜" + hi.toFixed(1) + "</td>"
       + "<td class='num " + cls + "'>" + tr[0].toFixed(0) + "〜" + tr[tr.length-1].toFixed(0)
       + "<br><span class='small'>中央 " + med.toFixed(0) + "</span></td><td class='small'>"
       + DATA.chars.map(ch => { const x = DATA.win[ch+"|"+fam];
           return ch + " " + x[0].toFixed(1) + "-" + x[1].toFixed(1) + "% → " + x[2].toFixed(0) + "ms"; })
         .join(" ／ ") + "</td></tr>";
  });
  // 打ち切りの間隔
  let gaps = [];
  DATA.chars.forEach(ch => { const g = DATA.gates[ch];
    for (let i = 1; i < g.length; i++) gaps.push(g[i] - g[i-1]); });
  gaps.sort((a,b) => a-b);
  h += "<tr><td colspan='4' class='small'>参考: 打ち切りの間隔は "
     + gaps[0] + "〜" + gaps[gaps.length-1] + "ms（中央 " + median(gaps)
     + "ms）。走り抜ける時間がこれと同じくらいなら、実用域に落ちる絵は 1〜2 枚しかない。</td></tr>";
  t.innerHTML = h;
}

function agg(cond, fam){
  const rs = DATA.cells.filter(c => c.cond === cond && c.family === fam);
  const sum = k => rs.reduce((a,r) => a + r[k], 0);
  return {n:rs.length, dist:sum("n_distinct")/rs.length, mid:sum("n_read_mid")/rs.length,
          rspan:sum("read_span")/rs.length, blank:sum("n_blank"),
          below:sum("n_below_usable"), above:sum("n_above_usable"),
          zero:sum("s_at_zero")/rs.length,
          span:sum("span_pt")/rs.length};
}

function buildSummary(){
  const t = document.getElementById("t_summary");
  let h = "<tr><th>条件</th><th>方式</th><th class='num'>別々の絵<br>(7点中)</th>"
        + "<th class='num'>中間の絵<br>(7点中)</th><th class='num'>読み取れる度合いの幅</th>"
        + "<th class='num'>真っ白<br>(56点中)</th><th class='num'>実用域より下</th>"
        + "<th class='num'>実用域より上</th><th class='num'>t=0 の進み具合(%)</th>"
        + "<th class='num'>進み具合の可動域(pt)</th></tr>";
  DATA.conds.forEach((c, i) => {
    DATA.fams.forEach((fam, j) => {
      const a = agg(c.key, fam);
      const cls = a.mid <= 1 ? "hot" : (a.mid < 3 ? "warm" : "");
      h += "<tr" + (j === 0 ? " class='sep'" : "") + ">"
         + (j === 0 ? "<td rowspan='4'><b style='color:var(" + CCOL[c.key] + ")'>"
                      + esc(c.label) + "</b></td>" : "")
         + "<td>" + LAB[fam] + "</td>"
         + "<td class='num'>" + a.dist.toFixed(2) + "</td>"
         + "<td class='num " + cls + "'>" + a.mid.toFixed(2) + "</td>"
         + "<td class='num'>" + a.rspan.toFixed(2) + "</td>"
         + "<td class='num'>" + a.blank + "</td>"
         + "<td class='num'>" + a.below + "</td>"
         + "<td class='num'>" + a.above + "</td>"
         + "<td class='num" + (a.zero > 20 ? " warm" : "") + "'>" + a.zero.toFixed(1) + "</td>"
         + "<td class='num'>" + a.span.toFixed(1) + "</td></tr>";
    });
  });
  t.innerHTML = h;
}

function buildDead(){
  const host = document.getElementById("d_dead");
  let h = "<div class='tblwrap'><table class='tbl'><tr><th>条件</th><th class='num'>潰れたセル</th>"
        + "<th>どこ</th></tr>";
  DATA.conds.forEach(c => {
    const d = DATA.cells.filter(x => x.cond === c.key && x.n_read_mid <= 1);
    h += "<tr><td><b style='color:var(" + CCOL[c.key] + ")'>" + esc(c.label) + "</b></td>"
       + "<td class='num'>" + (d.length ? "<span class='pill pillbad'>" + d.length
         + "</span>" : "<span class='pill pillok'>0</span>") + " / 32</td>"
       + "<td class='small'>" + (d.length ? d.map(x => LAB[x.family] + "×" + x.char).join("、")
                                          : "なし") + "</td></tr>";
  });
  host.innerHTML = h + "</table></div>";
}

function buildOutside(){
  const host = document.getElementById("d_outside");
  let rows = [];
  ["acc","info"].forEach(tag => {
    DATA.chars.forEach(ch => {
      const m = DATA.mid[tag + "|" + ch + "|fade"];   // 聴覚側は方式によらない
      if (!m) return;
      const g = DATA.gates[ch];
      const out = m.outside || (m.t_half < g[0] - 1e-9 ? "下" : (m.t_half > g[g.length-1] + 1e-9 ? "上" : ""));
      if (out) rows.push({tag, ch, m, g, out});
    });
  });
  let h = "<div class='tblwrap'><table class='tbl'><tr><th>軸</th><th>字</th>"
        + "<th class='num'>曲線の下端</th><th class='num'>天井</th><th class='num'>半分</th>"
        + "<th class='num'>中点 t_half</th><th>打ち切り窓</th><th>どうなるか</th></tr>";
  if (!rows.length){
    h += "<tr><td colspan='8'>該当なし</td></tr>";
  } else {
    rows.forEach(r => {
      h += "<tr><td>" + (r.tag === "acc" ? "正答率" : "情報量") + "</td><td><b>" + r.ch + "</b></td>"
         + "<td class='num'>" + r.m.a_bottom.toFixed(3) + "</td>"
         + "<td class='num'>" + r.m.a_top.toFixed(3) + "</td>"
         + "<td class='num'>" + (r.m.a_top/2).toFixed(3) + "</td>"
         + "<td class='num'>" + r.m.t_half.toFixed(1) + "ms</td>"
         + "<td class='num'>" + r.g[0] + "〜" + r.g[r.g.length-1] + "ms</td>"
         + "<td class='small'>" + esc(r.out) + "：最初の打ち切りの時点ですでに半分を超えているので、"
         + "中点は測った範囲の下端に張り付く。ずらし量 t0 はそこから決まる。</td></tr>";
    });
  }
  host.innerHTML = h + "</table></div>";
}

function buildCeiling(){
  const host = document.getElementById("d_ceiling");
  const med = (a) => { const s = a.slice().sort((x,y)=>x-y); return s[Math.floor(s.length/2)]; };
  let h = "<div class='tblwrap'><table class='tbl'><tr><th>軸</th><th>どちら</th>"
        + "<th class='num'>中点のずれ 中央値</th><th class='num'>最大</th><th>単位</th></tr>";
  ["acc","info"].forEach(tag => {
    ["audio","visual"].forEach(mo => {
      const d = DATA.ceiling.filter(r => r.target === tag && r.modality === mo);
      if (!d.length) return;
      const v = d.map(r => r.diff);
      h += "<tr><td>" + (tag === "acc" ? "正答率" : "情報量") + "</td>"
         + "<td>" + (mo === "audio" ? "聴覚（時刻）" : "視覚（進み具合）") + "</td>"
         + "<td class='num'>" + med(v).toFixed(3) + "</td>"
         + "<td class='num'>" + Math.max(...v).toFixed(3) + "</td>"
         + "<td>" + (mo === "audio" ? "ms" : "pt") + "</td></tr>";
    });
  });
  host.innerHTML = h + "</table></div>";
}

// ---------------------------------------------------------------------------
// 絵
// ---------------------------------------------------------------------------
function drawCell(cv, cond, fam, ch, condition, ms){
  warpTables = DATA.tables[cond];
  const ctx = cv.getContext("2d", {willReadFrequently:true});
  const R = RENDERERS[fam] || RENDERERS.fade;
  const {fn} = progressFn({play:"warp", family:fam, char:ch, condition:condition});
  R.begin(ch, ctx);
  R.draw(ctx, ch, fn(ms), ui.dir);
  return fn(ms);
}

function charList(){
  return ui.char === "__all__" ? DATA.chars : [ui.char];
}

function buildFrames(){
  const host = document.getElementById("frames");
  host.innerHTML = "";
  const fam = ui.fam;
  const t = document.createElement("table");
  t.className = "frames";
  let head = "<tr><th></th><th></th>";
  for (let i = 0; i < 7; i++) head += '<th class="gh">打ち切り ' + (i+1) + '</th>';
  head += '<th class="gh">再生</th></tr>';
  t.innerHTML = head;
  charList().forEach(ch => {
    const g = DATA.gates[ch];
    CK.forEach((cond, ki) => {
      const tr = document.createElement("tr");
      tr.className = "r" + ki + (ki === 3 ? " sep" : "");
      if (ki === 0){
        const th = document.createElement("th");
        th.className = "chh"; th.rowSpan = 4; th.textContent = ch;
        tr.appendChild(th);
      }
      const c = cellOf(cond, fam, ch);
      const lab = document.createElement("td");
      lab.className = "rowlbl";
      lab.innerHTML = "<span style='color:var(" + CCOL[cond] + ");font-weight:700'>"
                    + esc(CLAB[cond]) + "</span><br><span class='small'>中間の絵 "
                    + (c ? c.n_read_mid : "-") + "/7</span>";
      tr.appendChild(lab);
      const sg = c ? nums(c.s_at_gates) : g.map(() => 0);
      const rd = c ? nums(c.read_at_gates) : g.map(() => 0);
      const lo = Math.min(...rd), hi = Math.max(...rd);
      g.forEach((ms, gi) => {
        const td = document.createElement("td");
        const box = document.createElement("div");
        box.className = "cell";
        const cv = document.createElement("canvas");
        cv.width = CFG.visual.size_px; cv.height = CFG.visual.size_px;
        box.appendChild(cv);
        const cap = document.createElement("div"); cap.className = "cap";
        box.appendChild(cap);
        td.appendChild(box); tr.appendChild(td);
        const s = drawCell(cv, cond, fam, ch, ui.cond, ms);
        cap.innerHTML = "t=" + ms + "ms<br><b>s=" + (s*100).toFixed(2) + "%</b>"
                      + "<br>読 " + rd[gi].toFixed(2);
        if (ui.cond === "proposed" && c){
          const lv = nums(c.quant_levels);
          const z0 = nums(c.quant_levels)[0];
          const blank = (c.n_blank > 0) && (lv[gi] === blankLevel(fam, ch));
          const satur = rd[gi] >= (readLo(c) + 0.9 * (readHi(c) - readLo(c)));
          if (blank) box.className = "cell blank";
          else if (satur) box.className = "cell sat";
        }
      });
      const tdp = document.createElement("td");
      const b = document.createElement("button");
      b.className = "playbtn"; b.textContent = "▶";
      b.onclick = () => playRow(tr, cond, fam, ch);
      tdp.appendChild(b);
      if (c && c.n_read_mid <= 1){
        const d = document.createElement("div");
        d.className = "flag bad"; d.textContent = "潰れる";
        tdp.appendChild(d);
      }
      tr.appendChild(tdp);
      t.appendChild(tr);
    });
  });
  const wrap = document.createElement("div");
  wrap.className = "gridwrap";
  wrap.appendChild(t);
  host.appendChild(wrap);
}

// s=0 の絵の量子化水準（真っ白の判定に使う。build_warp_mid.endpoint_levels と同じ）
function blankLevel(fam, ch){
  if (fam === "blur") return 72;   // ぼかし半径 72px = BLUR_MAX_PX
  return 0;                        // うすい=不透明度0 / 点が増える=0画素 / 端から=0列
}
// その字×方式の較正曲線（正答率）の下端・天井
function readLo(c){ const y = DATA.curves.acc[c.char + "|" + c.family].ys; return y[0]; }
function readHi(c){ const y = DATA.curves.acc[c.char + "|" + c.family].ys; return y[y.length-1]; }

let playing = false;
function playRow(tr, cond, fam, ch){
  if (playing) return;
  const cvs = Array.from(tr.querySelectorAll("canvas"));
  if (!cvs.length) return;
  playing = true;
  warpTables = DATA.tables[cond];
  const R = RENDERERS[fam] || RENDERERS.fade;
  const {fn} = progressFn({play:"warp", family:fam, char:ch, condition:ui.cond});
  const ctxs = cvs.map(c => c.getContext("2d", {willReadFrequently:true}));
  ctxs.forEach(c => R.begin(ch, c));
  const t0 = performance.now();
  const dur = CFG.visual.base_anim_ms;
  const guard = setTimeout(() => {
    if (!playing) return;
    playing = false; redrawRow(tr, cond, fam, ch);
  }, dur + 2000);
  function step(now){
    const el = now - t0;
    const s = fn(Math.min(el, dur));
    ctxs.forEach(c => { R.begin(ch, c); R.draw(c, ch, s, ui.dir); });
    if (el < dur) requestAnimationFrame(step);
    else { playing = false; clearTimeout(guard);
           setTimeout(() => redrawRow(tr, cond, fam, ch), 400); }
  }
  requestAnimationFrame(step);
}
function redrawRow(tr, cond, fam, ch){
  const cvs = Array.from(tr.querySelectorAll("canvas"));
  const g = DATA.gates[ch];
  cvs.forEach((cv, i) => { if (i < g.length) drawCell(cv, cond, fam, ch, ui.cond, g[i]); });
}
function playAll(){
  if (playing) return;
  const rows = Array.from(document.querySelectorAll("#frames tr"))
                    .filter(r => r.querySelector("canvas"));
  let i = 0;
  const next = () => {
    if (i >= rows.length) return;
    const b = rows[i++].querySelector(".playbtn");
    if (b) b.click();
    setTimeout(next, CFG.visual.base_anim_ms + 350);
  };
  next();
}

// ---------------------------------------------------------------------------
// SVG
// ---------------------------------------------------------------------------
function el(name, attrs, text){
  const n = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  return n;
}
function svg(w, h){
  return el("svg", {class:"fig", viewBox:"0 0 " + w + " " + h, width:w, height:h});
}
function figure(host, s, caption){
  const f = document.createElement("figure");
  const wrap = document.createElement("div"); wrap.className = "figwrap";
  wrap.appendChild(s); f.appendChild(wrap);
  if (caption){ const c = document.createElement("figcaption"); c.innerHTML = caption;
                f.appendChild(c); }
  host.appendChild(f);
}
function legend(host){
  const d = document.createElement("div");
  d.className = "legend";
  d.innerHTML = DATA.conds.map(c =>
    "<span style='color:var(" + CCOL[c.key] + ")'><i></i>" + esc(c.label) + "</span>").join("");
  host.appendChild(d);
}

// 折れ線を単調に読む（transfer.js の seriesAt と同じ線形補間）
function seriesRead(arr, frameMs, tMs){
  if (tMs <= 0) return arr[0];
  const x = tMs / frameMs, i = Math.floor(x);
  if (i >= arr.length - 1) return arr[arr.length - 1];
  return arr[i] * (1 - (x - i)) + arr[i+1] * (x - i);
}
// 較正曲線（対数軸の折れ線）を読む
function curveAt(c, x){
  const xs = c.xs, ys = c.ys;
  const lx = Math.log(Math.max(x, 1e-9));
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length-1]) return ys[ys.length-1];
  for (let i = 1; i < xs.length; i++){
    if (x <= xs[i]){
      const a = Math.log(xs[i-1]), b = Math.log(xs[i]);
      const f = (b - a) < 1e-12 ? 0 : (lx - a) / (b - a);
      return ys[i-1] + f * (ys[i] - ys[i-1]);
    }
  }
  return ys[ys.length-1];
}

function panel(g, x0, y0, w, h, ch, fam, kind){
  const gates = DATA.gates[ch];
  const tmax = gates[gates.length-1] * 1.08;
  const win = DATA.win[ch + "|" + fam];
  const acc = DATA.curves.acc[ch + "|" + fam];
  const ymax = kind === "s" ? 100 : 1;
  const X = t => x0 + (t / tmax) * w;
  const Y = v => y0 + h - (v / ymax) * h;

  // 実用域の帯（進み具合の図だけ）
  if (kind === "s"){
    g.appendChild(el("rect", {x:x0, y:Y(Math.min(win[1], 100)), width:w,
      height:Math.max(1, Y(win[0]) - Y(Math.min(win[1], 100))),
      fill:cssvar("--ok"), opacity:.10}));
  }
  // 枠と目盛
  g.appendChild(el("rect", {x:x0, y:y0, width:w, height:h, class:"grid", fill:"none"}));
  for (let k = 0; k <= 4; k++){
    const v = ymax * k / 4;
    g.appendChild(el("line", {x1:x0, y1:Y(v), x2:x0+w, y2:Y(v), class:"grid"}));
    g.appendChild(el("text", {x:x0-4, y:Y(v)+3, class:"tiny", "text-anchor":"end"},
      kind === "s" ? v.toFixed(0) : v.toFixed(1)));
  }
  gates.forEach(ms => {
    g.appendChild(el("line", {x1:X(ms), y1:y0, x2:X(ms), y2:y0+h, class:"grid"}));
  });
  g.appendChild(el("text", {x:x0+w/2, y:y0+h+22, class:"tiny", "text-anchor":"middle"},
    "打ち切り時刻 ms（" + gates[0] + "〜" + gates[gates.length-1] + "）"));
  g.appendChild(el("text", {x:x0, y:y0-6, class:"ttl"}, ch));

  DATA.conds.forEach(c => {
    const doc = DATA.tables[c.key];
    const arr = doc.tables[fam][ch].proposed;
    const fm = doc.frame_ms;
    let d = "", pts = [];
    for (let i = 0; i <= 120; i++){
      const t = tmax * i / 120;
      const s = seriesRead(arr, fm, t) * 100;
      const v = kind === "s" ? s : curveAt(acc, s);
      d += (i ? "L" : "M") + X(t).toFixed(1) + "," + Y(v).toFixed(1);
    }
    g.appendChild(el("path", {d, fill:"none", stroke:cssvar(CCOL[c.key]),
      "stroke-width":1.8, "stroke-linejoin":"round"}));
    gates.forEach(ms => {
      const s = seriesRead(arr, fm, ms) * 100;
      const v = kind === "s" ? s : curveAt(acc, s);
      g.appendChild(el("circle", {cx:X(ms), cy:Y(v), r:2.4,
        fill:cssvar(CCOL[c.key])}));
    });
  });
}

function buildFigs(){
  const host = document.getElementById("figs");
  host.innerHTML = "";
  const chars = charList();
  const cols = chars.length === 1 ? 1 : 4;
  const rows = Math.ceil(chars.length / cols);
  const pw = chars.length === 1 ? 520 : 250, ph = chars.length === 1 ? 260 : 150;
  const mL = 34, mR = 12, mT = 24, mB = 34;

  [["s", "進み具合 s(t)", "縦軸は進み具合（%）。薄い緑の帯は<strong>実用域</strong>"
    + "（較正の正答率曲線の可動域 5%〜95%）。縦の点線が打ち切り7点。"
    + "帯の中を通っている点が多いほど、7段階が意味を持つ。"],
   ["r", "読み取れる度合い", "縦軸は、その進み具合の絵を<strong>較正の正答率曲線に通した値</strong>。"
    + "曲線が早々に天井に張り付き、点が上下の端に固まっていれば「潰れている」。"]]
  .forEach(([kind, title, cap]) => {
    const W = mL + cols * (pw + mR) + 10, H = mT + rows * (ph + mB) + 10;
    const s = svg(W, H);
    const g = el("g", {});
    s.appendChild(g);
    chars.forEach((ch, i) => {
      const cx = i % cols, cy = Math.floor(i / cols);
      panel(g, mL + cx * (pw + mR), mT + cy * (ph + mB), pw, ph, ch, ui.fam, kind);
    });
    const h3 = document.createElement("h3");
    h3.textContent = title + "（" + LAB[ui.fam] + "）";
    host.appendChild(h3);
    legend(host);
    figure(host, s, cap);
  });
}

// ---------------------------------------------------------------------------
function rebuild(){
  buildFrames();
  buildFigs();
}

function buildVerdict(){
  const f = (k, fam) => agg(k, fam);
  const line = (fam) => {
    const a = DATA.conds.map(c => f(c.key, fam));
    const tr = DATA.chars.map(ch => DATA.win[ch + "|" + fam][2]).sort((x,y) => x-y);
    return {fam, a, med:median(tr), lo:tr[0], hi:tr[tr.length-1]};
  };
  const fade = line("fade"), rev = line("reveal"), blur = line("blur"), wipe = line("wipe");
  let gaps = [];
  DATA.chars.forEach(ch => { const g = DATA.gates[ch];
    for (let i = 1; i < g.length; i++) gaps.push(g[i] - g[i-1]); });
  gaps.sort((x,y) => x-y);
  const nd = (k) => DATA.cells.filter(x => x.cond === k && x.n_read_mid <= 1).length;
  // 打ち切り窓の幅（最後の打ち切り − 最初の打ち切り）
  const gw = DATA.chars.map(ch => { const g = DATA.gates[ch]; return g[g.length-1] - g[0]; })
                       .sort((x,y) => x-y);
  document.getElementById("p_verdict").innerHTML =
    "実用域を走り抜ける時間は <b>うすい " + fade.lo.toFixed(0) + "〜" + fade.hi.toFixed(0)
    + "ms（中央 " + fade.med.toFixed(0) + "ms）</b>、<b>点が増える " + rev.lo.toFixed(0)
    + "〜" + rev.hi.toFixed(0) + "ms（中央 " + rev.med.toFixed(0) + "ms）</b>。"
    + "打ち切りの間隔（中央 " + median(gaps) + "ms・最大 " + gaps[gaps.length-1]
    + "ms）と同じか、それより短い。"
    + "そのぶん実用域の中に落ちる絵が減り、7点中の「中間の絵」は "
    + "うすいで ①" + fade.a[0].mid.toFixed(2) + " → ③" + fade.a[2].mid.toFixed(2)
    + " / ②" + fade.a[1].mid.toFixed(2) + " → ④" + fade.a[3].mid.toFixed(2)
    + "、点が増えるで ①" + rev.a[0].mid.toFixed(2) + " → ③" + rev.a[2].mid.toFixed(2)
    + " / ②" + rev.a[1].mid.toFixed(2) + " → ④" + rev.a[3].mid.toFixed(2)
    + " に落ちる。真っ白のままの点は 56点中 うすい③ " + fade.a[2].blank
    + "点・点が増える③ " + rev.a[2].blank + "点。"
    + "潰れたセルは ③ " + nd("acc_mid") + "/32、④ " + nd("info_mid") + "/32"
    + "（①" + nd("acc_shape") + "、②" + nd("info_shape") + "）。";
  document.getElementById("p_verdict2").innerHTML =
    "ぼやけの実用域は幅が広く（走り抜けるのに " + blur.lo.toFixed(0) + "〜"
    + blur.hi.toFixed(0) + "ms、中央 " + blur.med.toFixed(0) + "ms）、端からも "
    + wipe.lo.toFixed(0) + "〜" + wipe.hi.toFixed(0) + "ms（中央 " + wipe.med.toFixed(0)
    + "ms）。どちらも打ち切り窓（" + gw[0] + "〜" + gw[gw.length-1]
    + "ms）と同じ桁なので、③④ でも 7 点が実用域に散る"
    + "（中間の絵 ぼやけ ③" + blur.a[2].mid.toFixed(2) + " / ④" + blur.a[3].mid.toFixed(2)
    + "、端から ③" + wipe.a[2].mid.toFixed(2) + " / ④" + wipe.a[3].mid.toFixed(2) + "）。"
    + "<br>ただし ③④ は t0 が負になるので、<b>ぼやけは t=0 の時点で平均 "
    + ((blur.a[2].zero + blur.a[3].zero) / 2).toFixed(0)
    + "% まで進んだ状態から始まる</b>。いちばん最初のフレームで既に半分くっきりしており、"
    + "「まっさらなぼやけから始まる」という出だしが無い。見え心地を聞くときは、"
    + "これが評価に効く可能性がある。";
}

function buildComfort(){
  const c = DATA.comfort;
  const mm = (ms) => (ms/1000).toFixed(2) + "秒";
  document.getElementById("d_comfort_now").innerHTML =
    "<div class='tblwrap'><table class='tbl'>"
    + "<tr><th>いまの本数</th><td class='num'><b>" + c.n_items + "</b> 本</td>"
    + "<td class='small'>" + c.families.length + "方式 × "
    + c.presentations.length + "出し方（ただし step は 1字だけ）</td></tr>"
    + "<tr><th>1問あたりの評価</th><td class='num'>" + c.n_rating_items + " 項目</td>"
    + "<td class='small'>答えるまでループ再生が流れつづける</td></tr>"
    + "<tr><th>1本の長さ（1字だけ）</th><td class='num'>" + mm(c.loops.single.prod_ms)
    + "</td><td class='small'>本番表のアニメ長 " + c.anim_prod_ms
    + "ms で計算。4条件の表（" + c.anim_new_ms + "ms）に替えると <b>"
    + mm(c.loops.single.new_ms) + "</b></td></tr>"
    + "<tr><th>1本の長さ（5字）</th><td class='num'>" + mm(c.loops.row5.prod_ms)
    + "</td><td class='small'>4条件の表なら <b>" + mm(c.loops.row5.new_ms)
    + "</b></td></tr>"
    + "<tr><th>実績</th><td class='num'>" + c.n_people + " 人</td>"
    + "<td class='small'>所要時間 中央 " + (c.dur_median_s/60).toFixed(1)
    + "分（四分位 " + (c.dur_q1_s/60).toFixed(1) + "〜" + (c.dur_q3_s/60).toFixed(1)
    + "分・平均 " + (c.dur_mean_s/60).toFixed(1) + "分）</td></tr>"
    + "</table></div>";

  // 1画面あたりの実測の目安（全体の所要時間 ÷ 画面数）。
  // 画面数は 13本の評価 ＋ 選択2問＝15画面として割る（教示・後書きも入るので上振れ側の目安）。
  const perScreen = c.dur_median_s / (c.n_items + 2);
  const est = (n) => ((n * perScreen) / 60).toFixed(1);
  // 対応のある比較の必要人数（両側・Holm で 6 組ぶんに割る）。
  // これは**実測ではなく仮定に基づく計算**。効果量 d は仮定値。
  const need = (d) => {
    const a = 0.05 / 6, z = 2.638, zb = 0.8416;   // z_{1-a/2}(a=.00833), z_{.8}
    return Math.ceil(Math.pow(z + zb, 2) / (d * d));
  };
  document.getElementById("d_comfort_plan").innerHTML =
    "<p style='font-size:.93rem'><b>4条件の比較は参加者の中で（within）取る。</b>"
    + "「どの合わせ方が心地よいか」は同じ人が見くらべないと決まらない。"
    + "方式は participant 間で振ってもよい。</p>"
    + "<div class='tblwrap'><table class='tbl'>"
    + "<tr><th>案</th><th>中身</th><th class='num'>本数</th>"
    + "<th class='num'>足す時間</th><th class='num'>合計</th><th>向き不向き</th></tr>"
    + "<tr><td><b>A（推し）</b><br>別掲載にする</td>"
    + "<td class='small'>ぼやけ×4条件（4本）＋ 端から×4条件（4本）＋ "
    + "うすい×③（1本）＋ 点が増える×③（1本）＝10本。1字だけで出す"
    + "（出し方は今の13本で既に聞いているので繰り返さない）。"
    + "＋ 4条件を並べて見くらべる強制選択を方式ごとに2問。</td>"
    + "<td class='num'>10＋2</td><td class='num'>—</td>"
    + "<td class='num'>約 " + est(12) + "分</td>"
    + "<td class='small'>今の群Cよりやや短い。既存の414人ぶんを壊さない。"
    + "潰れる2方式も、いちばん極端な③で1本ずつ見せられる。</td></tr>"
    + "<tr><td>B<br>今の群Cに足す</td>"
    + "<td class='small'>1人につき方式を1つ割り当て、その方式×4条件を4本。"
    + "＋ 4条件の強制選択1問。方式は4通りなので、方式ごとの人数は 1/4 になる。</td>"
    + "<td class='num'>＋5</td><td class='num'>＋" + est(5) + "分</td>"
    + "<td class='num'>約 " + ((c.dur_median_s/60) + Number(est(5))).toFixed(1) + "分</td>"
    + "<td class='small'>短く済むが、方式ごとの人数を確保するのに 4 倍の人が要る。</td></tr>"
    + "<tr><td>C<br>全部入れる</td>"
    + "<td class='small'>4条件 × 4方式 ＝ 16本を within で。</td>"
    + "<td class='num'>＋16</td><td class='num'>＋" + est(16) + "分</td>"
    + "<td class='num'>約 " + ((c.dur_median_s/60) + Number(est(16))).toFixed(1) + "分</td>"
    + "<td class='small'><span class='pill pillbad'>長すぎる</span>"
    + "途中離脱と飽きが出る。すすめない。</td></tr>"
    + "</table></div>"
    + "<p class='small'>時間の見積もりは、いまの群Cの実測（中央 "
    + (c.dur_median_s/60).toFixed(1) + "分 ÷ " + (c.n_items + 2)
    + "画面 ＝ 1画面 " + perScreen.toFixed(0) + "秒）を、そのまま画面数に掛けたもの。"
    + "教示や後書きも割り算に入っているので、<b>上振れ側の目安</b>である。"
    + "ただし4条件の表はアニメが " + c.anim_prod_ms + "ms → " + c.anim_new_ms
    + "ms と長くなるので、1周が " + mm(c.loops.single.prod_ms) + " → "
    + mm(c.loops.single.new_ms) + " に伸びる（答えるまで流れつづける形式なので、"
    + "回答時間そのものは変わらないが、見せられる周回数は減る）。</p>"
    + "<p class='small'><b>人数（仮定にもとづく計算・実測ではない）</b>：4条件から2つずつ選ぶ"
    + "6組を対応のある t 検定で見て、Holm で 6 組ぶんに割る（両側 α=.05/6）、検出力 .8 とすると、"
    + "対応のある効果量 d=0.20 で <b>" + need(0.20) + "人</b>、d=0.25 で <b>"
    + need(0.25) + "人</b>、d=0.30 で <b>" + need(0.30) + "人</b>。"
    + "案Aは方式を within で持つので、この人数がそのまま必要人数になる。"
    + "案Bは方式ごとにこの人数が要るので、4倍（d=0.25 なら " + (need(0.25)*4)
    + "人）必要になる。</p>"
    + "<p class='small'><b>うすい・点が増えるを外さない理由</b>：③④ でそこが潰れるのは"
    + "「見え心地の実験で評価できない」という意味ではない。群Cにはすでに "
    + "<code>step</code>（中点まで何も出さず、そこで一気に完成形にする）が比較対象として"
    + "入っている。③④ のうすい・点が増えるは実質そこへ寄っていくので、"
    + "<b>step と並べて聞けば「50%だけ揃えると段階表示にならない」ことの受け止められ方が"
    + "そのまま測れる</b>。案Aで うすい×③・点が増える×③ を入れているのはそのため。"
    + "なお、うすい・点が増えるの「段階的に出る版」は<b>いまの13本にすでに入っている</b>"
    + "（本番 transfer_warp.json は正答率を目標に形まで合わせた表なので、位置づけとしては ① に近い）。"
    + "新しく足すのは、そこに無い ③ の極端さである。</p>";
}

function init(){
  document.getElementById("src_curves").textContent = DATA.src.curves;
  document.getElementById("ul_src").innerHTML =
    "<li>曲線: <code>" + esc(DATA.src.curves) + "</code>（袋詰め PAVA・推定はやり直していない）</li>"
    + "<li>数値: <code>" + esc(DATA.src.metrics) + "</code> / <code>"
    + esc(DATA.src.log) + "</code></li>"
    + DATA.conds.map(c => "<li>" + esc(c.label) + ": <code>" + esc(c.path) + "</code></li>").join("")
    + "<li>描画: <code>experiment/transfer.js</code> の本文をそのまま切り出し（読むだけ）</li>";

  const sf = document.getElementById("sel_fam");
  DATA.fams.forEach(f => { const o = document.createElement("option");
    o.value = f; o.textContent = LAB[f]; sf.appendChild(o); });
  sf.value = ui.fam;
  sf.onchange = () => { ui.fam = sf.value; rebuild(); };

  const sc = document.getElementById("sel_char");
  const oa = document.createElement("option"); oa.value = "__all__"; oa.textContent = "8字ぜんぶ";
  sc.appendChild(oa);
  DATA.chars.forEach(c => { const o = document.createElement("option");
    o.value = c; o.textContent = c; sc.appendChild(o); });
  sc.value = ui.char;
  sc.onchange = () => { ui.char = sc.value; rebuild(); };

  document.getElementById("sel_cond").onchange = (e) => { ui.cond = e.target.value; rebuild(); };
  document.getElementById("sel_dir").onchange = (e) => { ui.dir = e.target.value; rebuild(); };
  document.getElementById("btn_play").onclick = playAll;
  document.getElementById("btn_theme").onclick = () => {
    const r = document.documentElement;
    const cur = r.getAttribute("data-theme");
    const dark = cur ? cur === "dark"
      : (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    r.setAttribute("data-theme", dark ? "light" : "dark");
    rebuild();
  };

  buildTransit(); buildSummary(); buildDead(); buildOutside(); buildCeiling();
  buildVerdict(); buildComfort();
  loadAll().then(rebuild).catch(e => {
    document.getElementById("frames").innerHTML =
      "<p class='pill pillbad'>文字画像が読めない: " + esc(e.message) + "</p>";
  });
}
init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
