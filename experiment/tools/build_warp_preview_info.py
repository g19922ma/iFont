#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=========================================================================
情報量を目標にした転写のプレビュー（研究者用・参加者には配らない）
=========================================================================

何のためのページか
------------------
転写(proposed)は「時刻 t →〔聴覚の曲線〕→ 目標の値 →〔視覚の曲線を逆に引く〕
→ 進み具合 s →〔描画〕→ 絵」という流れで作る。この**軸に載っている量**を

    正答率  … どこまで正しく答えられるか
    情報量  … どこまで候補が絞れているか（相互情報量の字ごとの分け前）

の2通りにすると、同じデータから2つのアニメーションができる。
このページは、その2つを**同じ字・同じ方式で上下に並べて**見比べる。

    ⚠ 見どころは「が」。全部聞かせても正答率は 3%（66試行中2）だが、
      57 が「か」と答える＝実質1択まで絞れている。正答率を目標にすると
      「が」は最後まで真っ白のまま、情報量を目標にすると絵が動く。

作り方の要点（experiment/tools/build_warp_preview.py と同じ手口）
----------------------------------------------------------------
1. **描画は書き直さない。** experiment/transfer.js の
   `const SIZE = CFG.visual.size_px;` 〜 `function loadImage(` の直前までを
   そのまま切り出して貼る。ここに出る絵は参加者が見るものと同じ。
2. **file:// で開けるように外から読むものは全部埋め込む。**
   文字画像は data URI（getImageData を使う reveal/wipe が canvas 汚染で
   落ちないように）。表・数値は JSON として <script> に埋め込む。
3. 本番の transfer_warp.json / transfer_config.js / transfer.js は読むだけ。

必要なもの（先に回しておく）
    python3 experiment/tools/analyze_information.py
    python3 experiment/tools/build_warp_v5_info.py

使い方:
    python3 experiment/tools/build_warp_preview_info.py
    open experiment/warp_preview_info.html
========================================================================="""
import base64
import io
import json
import os
import subprocess
from collections import Counter

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXP = os.path.join(ROOT, "experiment")
CAL = os.path.join(ROOT, "project", "data_calib2_live")
INFO = os.path.join(CAL, "analysis_information")
V5 = os.path.join(CAL, "warp_v5_info")
OUT = os.path.join(EXP, "warp_preview_info.html")

CHARS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
FAMS = ["fade", "reveal", "blur", "wipe"]
LAB = {"fade": "うすい", "reveal": "点が増える", "blur": "ぼやけ", "wipe": "端から"}


# ---------------------------------------------------------------------------
# 1. transfer.js から描画＋再生をそのまま切り出す
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
        p = os.path.join(EXP, "base", ch + ".png")
        with open(p, "rb") as f:
            d[ch] = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    return d


# ---------------------------------------------------------------------------
# 2. warp 表（情報量版・正答率版）
# ---------------------------------------------------------------------------
def load_tables():
    out = {}
    for key, label, fn in (("info", "情報量を目標", "transfer_warp_v5_info.json"),
                           ("acc", "正答率を目標", "transfer_warp_v5_acc.json")):
        p = os.path.join(V5, fn)
        if not os.path.exists(p):
            raise SystemExit(
                f"{p} が無い。先に:\n"
                "    python3 experiment/tools/analyze_information.py\n"
                "    python3 experiment/tools/build_warp_v5_info.py")
        doc = json.load(io.open(p, encoding="utf-8"))
        n = len(doc["tables"]["fade"]["あ"]["proposed"])
        out[key] = {"label": label, "doc": doc,
                    "covers_ms": round((n - 1) * doc["frame_ms"], 1),
                    "path": os.path.relpath(p, ROOT)}
        print(f"  表 {key:<5} {label}  数値列 {n} 点（{(n-1)*doc['frame_ms']:.0f}ms まで）")
    return out


# ---------------------------------------------------------------------------
# 3. 「が」の回答の中身（同じ低い正答率でも中身が違うことの実物）
# ---------------------------------------------------------------------------
def response_distributions(gates_of):
    """打ち切り点ごとに『何と答えたか』を数える。

    絞り込みは analyze_information.slices と同じにそろえる:
      ・はしご（打ち切りあり）… 聴覚 / まぎれ字でない / check_kind なし / 対象8字
        （= analyze_information の amain から埋め込み full を抜いたもの）
      ・打ち切りなし … 聴覚 / 対象8字 / gate_ms が無い行**すべて**
        （= analyze_information の afull_all。はしごに埋め込んだ full と、
          確認問題 check_kind="full" の両方が入る。「が」で 66 試行）
    """
    p = os.path.join(CAL, "transfer_trials.csv")
    d = pd.read_csv(p, low_memory=False)
    for c in ("is_decoy", "is_filler", "is_test"):
        if c in d.columns and d[c].dtype == object:
            d[c] = d[c].map({True: True, False: False, "TRUE": True, "FALSE": False,
                             "True": True, "False": False})
    d = d[d["is_test"] != True]                                    # noqa: E712
    aud = d[(d["modality"] == "transfer_audio")
            & (d["target_char"].isin(CHARS))].copy()
    aud["gate_ms_f"] = pd.to_numeric(aud["gate_ms"], errors="coerce")
    aud = aud[aud["response_char"].notna() & (aud["response_char"] != "-")]
    lad_all = aud[(aud["is_decoy"] != True) & (aud["check_kind"].isna())   # noqa: E712
                  & aud["gate_ms_f"].notna()]
    full_all = aud[aud["gate_ms_f"].isna()]

    out = {}
    for ch in CHARS:
        g = gates_of[ch]
        lad = lad_all[lad_all["target_char"] == ch]
        per = []
        for ms in g:
            s = lad[(lad["gate_ms_f"] - ms).abs() < 1e-6]
            c = Counter(s["response_char"])
            per.append({"t_ms": float(ms), "n": int(len(s)),
                        "correct": int((s["target_char"] == s["response_char"]).sum()),
                        "n_kinds": len(c),
                        "top": [[k, int(v)] for k, v in c.most_common(6)]})
        full = full_all[full_all["target_char"] == ch]
        cf = Counter(full["response_char"])
        out[ch] = {"gates": per,
                   "full": {"n": int(len(full)),
                            "correct": int((full["target_char"]
                                            == full["response_char"]).sum()),
                            "n_kinds": len(cf),
                            "top": [[k, int(v)] for k, v in cf.most_common(6)]}}

    # 参照: いちばん短い打ち切り 10ms を8字ぶん束ねたもの（＝『何も届いていない』の実物）。
    # analyze_information.py の prior_response_distribution.csv「聴覚 10ms（本命8字）」と同じ数え方。
    s10 = lad_all[(lad_all["gate_ms_f"] - 10.0).abs() < 1e-6]
    c10 = Counter(s10["response_char"])
    out["_pooled10"] = {"n": int(len(s10)), "n_kinds": len(c10),
                        "correct": int((s10["target_char"] == s10["response_char"]).sum()),
                        "top": [[k, int(v)] for k, v in c10.most_common(6)]}
    return out


# ---------------------------------------------------------------------------
def main():
    print("[1] transfer.js から描画＋再生を切り出す")
    js_slice = slice_transfer_js()
    print(f"    {js_slice.count(chr(10))} 行")

    print("[2] transfer_config.js を JSON に")
    cfg = load_config()
    gates = {ch: cfg["audio"]["gates_ms"].get(ch, cfg["audio"]["gates_ms"]["_default"])
             for ch in CHARS}

    print("[3] 文字画像を data URI に")
    imgs = load_images()

    print("[4] warp 表（情報量版・正答率版）を読む")
    tables = load_tables()

    print("[5] 曲線と表を読む")
    fig = json.load(io.open(os.path.join(INFO, "figure_data.json"), encoding="utf-8"))
    log = pd.read_csv(os.path.join(V5, "build_log_v5.csv"))
    bychar = pd.read_csv(os.path.join(INFO, "info_by_char_level.csv"))

    cells = []
    for _, r in log.iterrows():
        cells.append({k: (None if pd.isna(r[k]) else
                          (r[k].item() if hasattr(r[k], "item") else r[k]))
                      for k in ("target", "family", "char", "s_min", "s_max",
                                "span_pt_gates", "n_distinct_at_gates", "judgement",
                                "clip_low_gates", "clip_high_gates", "s_at_gates",
                                "target_first_gate", "target_last_gate",
                                "visual_bottom", "visual_top")})

    def _s(v):
        return "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)

    def _i(v):
        return 0 if (v is None or (isinstance(v, float) and pd.isna(v))) else int(v)

    full = {}
    for _, r in bychar[(bychar.modality == "audio") & (bychar.level_index == 99)].iterrows():
        full[r["char"]] = {"n": int(r["n_trials"]), "acc": float(r["accuracy_raw"]),
                           "bits": float(r["bits_corrected"]),
                           "top1": [_s(r.get("top1_char")), _i(r.get("top1_n"))],
                           "top2": [_s(r.get("top2_char")), _i(r.get("top2_n"))]}

    print("[6] 『何と答えたか』を数える")
    resp = response_distributions(gates)
    gg = resp["が"]
    print(f"    が 打ち切りなし: {gg['full']['n']}試行 / 正答 {gg['full']['correct']} / "
          f"最頻 {gg['full']['top'][0][0]}×{gg['full']['top'][0][1]} / "
          f"答えの種類 {gg['full']['n_kinds']}")
    print(f"    が 10ms: {gg['gates'][0]['n']}試行 / 答えの種類 {gg['gates'][0]['n_kinds']}")
    p10 = resp["_pooled10"]
    print(f"    10ms を8字ぶん束ねる: {p10['n']}試行 / 答えの種類 {p10['n_kinds']} / "
          + "、".join(f"{k}×{v}" for k, v in p10["top"][:4]))

    data = {
        "chars": CHARS, "fams": FAMS, "lab": LAB, "gates": gates,
        "images": imgs,
        "tables": {k: {"label": v["label"], "covers_ms": v["covers_ms"],
                       "path": v["path"], "doc": v["doc"]} for k, v in tables.items()},
        "cells": cells, "curves": fig, "full": full, "resp": resp,
        "src": {"curves": os.path.relpath(os.path.join(INFO, "curves_info.csv"), ROOT),
                "log": os.path.relpath(os.path.join(V5, "build_log_v5.csv"), ROOT),
                "trials": os.path.relpath(os.path.join(CAL, "transfer_trials.csv"), ROOT)},
    }

    html = PAGE.replace("/*__DATA__*/", "const DATA = " + json.dumps(
        data, ensure_ascii=False, separators=(",", ":")) + ";")
    html = html.replace("/*__CFG__*/", "const CFG = window.TRANSFER_CONFIG = " + json.dumps(
        cfg, ensure_ascii=False, separators=(",", ":")) + ";")
    html = html.replace("/*__TRANSFER_JS_SLICE__*/", js_slice)

    io.open(OUT, "w", encoding="utf-8").write(html)
    print(f"\n書き出し: {os.path.relpath(OUT, ROOT)}  ({os.path.getsize(OUT)//1024} KB)")
    print("  open experiment/warp_preview_info.html")


# ===========================================================================
# ページ本体
# ===========================================================================
PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>情報量を目標にした転写（研究者用）</title>
<style>
:root{
  --bg:#faf8f4; --fg:#1c1a17; --muted:#6b6560; --accent:#b45309; --line:#ded6c8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c; --card:#ffffff;
  --acc:#8a3ea8;   /* 正答率を目標 */
  --info:#0f766e;  /* 情報量を目標 */
  --canvasbg:#ffffff;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
    --card:#211e19; --ok:#4ade80; --bad:#f87171;
    --acc:#cf95e6; --info:#5ec8bb;
  }
}
:root[data-theme="dark"]{
  --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
  --card:#211e19; --ok:#4ade80; --bad:#f87171;
  --acc:#cf95e6; --info:#5ec8bb;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);
  font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  line-height:1.75;max-width:1240px;margin:0 auto;padding:2rem 1.2rem 6rem}
h1{font-size:1.6rem;border-bottom:2px solid var(--accent);padding-bottom:.5rem;line-height:1.4}
h2{font-size:1.22rem;margin-top:3rem;color:var(--accent);
   border-bottom:1px solid var(--line);padding-bottom:.3rem}
h3{font-size:1rem;margin-top:1.8rem}
p{margin:.6rem 0}
.lead{color:var(--muted);font-size:.94rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:.9rem 1.2rem;margin:1rem 0}
.card.note{border-left:5px solid var(--accent)}
.card.star{border-left:5px solid var(--info)}
.small{font-size:.83rem;color:var(--muted)}
code{background:color-mix(in srgb,var(--fg) 7%,transparent);padding:.05rem .3rem;
  border-radius:4px;font-size:.88em}
.tbl{border-collapse:collapse;width:100%;font-size:.82rem;margin:.8rem 0}
.tbl th,.tbl td{border:1px solid var(--line);padding:.28rem .5rem;text-align:left}
.tbl th{background:color-mix(in srgb,var(--accent) 12%,var(--card))}
.tbl td.num{text-align:right;font-variant-numeric:tabular-nums}
.tagacc{color:var(--acc);font-weight:700}
.taginfo{color:var(--info);font-weight:700}

#bar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 92%,transparent);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
  padding:.55rem 1.2rem;margin:0 -1.2rem 1.2rem;
  display:flex;flex-wrap:wrap;gap:.5rem 1.1rem;align-items:center;font-size:.85rem}
#bar label{display:flex;align-items:center;gap:.32rem;white-space:nowrap}
#bar select,#bar button{font:inherit;font-size:.85rem;padding:.15rem .4rem;
  background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px}
#bar button{cursor:pointer}
#bar button:hover{border-color:var(--accent)}
.ttlkey{font-weight:700;color:var(--muted)}

.gridwrap{overflow-x:auto;margin:.8rem 0 1.4rem}
table.frames{border-collapse:separate;border-spacing:0;font-size:.75rem}
table.frames th,table.frames td{padding:.18rem .25rem;vertical-align:top}
table.frames th.chh{text-align:left;font-size:1.6rem;font-weight:700;
  padding-right:.6rem;white-space:nowrap;vertical-align:middle}
table.frames th.gh{color:var(--muted);font-weight:600;text-align:center;font-size:.72rem}
table.frames tr.rowinfo td,table.frames tr.rowinfo th{
  background:color-mix(in srgb,var(--info) 7%,transparent)}
table.frames tr.sep td,table.frames tr.sep th{border-bottom:1px solid var(--line)}
.cell{display:flex;flex-direction:column;align-items:center;gap:.15rem}
.cell canvas{width:92px;height:92px;background:var(--canvasbg);
  border:1px solid var(--line);border-radius:4px}
.cell.dead canvas{border:2px solid var(--bad)}
.cell .cap{font-size:.67rem;color:var(--muted);text-align:center;line-height:1.35;
  font-variant-numeric:tabular-nums}
.cell .cap b{color:var(--fg);font-weight:700}
.rowlbl{font-size:.7rem;white-space:nowrap;vertical-align:middle}
.playbtn{font:inherit;font-size:.72rem;padding:.1rem .45rem;cursor:pointer;
  background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:5px}
.playbtn:hover{border-color:var(--accent)}
.deadnote{font-size:.68rem;color:var(--bad);font-weight:700;text-align:center}

figure{margin:1.4rem 0 2rem}
figcaption{font-size:.85rem;margin-top:.4rem;padding-left:.7rem;
  border-left:3px solid var(--accent);color:var(--fg)}
.figwrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);
  border-radius:10px;padding:.5rem}
svg.fig{display:block;max-width:100%;height:auto;margin:0 auto}
svg text{font-family:"Hiragino Sans","Yu Gothic",sans-serif;fill:var(--fg)}
svg .lbl{fill:var(--muted);font-size:11px}
svg .tiny{font-size:9.5px;fill:var(--muted)}
svg .ttl{fill:var(--fg);font-size:12.5px;font-weight:700}
svg .ax{stroke:var(--muted);stroke-width:1.1;fill:none}
svg .grid{stroke:var(--line);stroke-width:1;stroke-dasharray:2 3;fill:none}
.legend{font-size:.78rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:.2rem 1rem;
  margin:.3rem 0 .1rem}
.legend i{display:inline-block;width:16px;height:0;border-top:2.5px solid currentColor;
  vertical-align:middle;margin-right:.25rem}

/* 成立判定のマトリクス */
table.mx{border-collapse:collapse;font-size:.78rem;margin:.6rem 0}
table.mx th,table.mx td{border:1px solid var(--line);padding:.25rem .45rem;text-align:center}
table.mx th{background:color-mix(in srgb,var(--accent) 10%,var(--card));font-weight:600}
table.mx td.j0{background:color-mix(in srgb,var(--bad) 42%,transparent);
  color:var(--fg);font-weight:700}
table.mx td.j1{background:color-mix(in srgb,var(--warn) 20%,transparent)}
table.mx td.j2{background:color-mix(in srgb,var(--ok) 20%,transparent)}
.pill{display:inline-block;border-radius:5px;padding:0 .4rem;font-size:.75rem;font-weight:700}
.pillbad{background:color-mix(in srgb,var(--bad) 20%,transparent);color:var(--bad)}
.pillok{background:color-mix(in srgb,var(--ok) 20%,transparent);color:var(--ok)}
.bigstat{display:flex;flex-wrap:wrap;gap:1.4rem;margin:.8rem 0}
.bigstat div{min-width:150px}
.bigstat b{display:block;font-size:1.7rem;line-height:1.2;font-variant-numeric:tabular-nums}
.bigstat span{font-size:.78rem;color:var(--muted)}
details{margin:.6rem 0}
summary{cursor:pointer;font-size:.88rem;color:var(--accent)}
</style>
</head>
<body>

<h1>情報量を目標にした転写 ― 正答率を目標にした版と見比べる</h1>
<p class="lead">研究者用。参加者には配らない（<code>build_hosting.sh</code> の公開一覧に入れていない）。
描画は <code>experiment/transfer.js</code> の本文をそのまま切り出して動かしているので、
ここに出る絵は<strong>参加者が見るものと同じ</strong>。</p>

<div class="card note">
<h3 style="margin-top:.2rem">同じデータを2通りに読む</h3>
<p>転写とは「<strong>音を途中まで聞いたときの手ごたえ</strong>を、文字アニメーションが
<strong>同じ時刻に同じ手ごたえ</strong>になるように進み具合を決める」やり方である。
この「手ごたえ」に何を置くかで、2通りのアニメーションができる。</p>
<p style="text-align:center;font-size:.95rem;margin:.8rem 0">
<code>時刻 t</code> →〔聴覚の曲線〕→ <code>目標の値</code>
→〔視覚の較正曲線を逆に引く〕→ <code>進み具合 s</code> →〔描画〕→ <code>絵</code></p>
<ul style="font-size:.9rem">
<li><span class="tagacc">正答率を目標</span> … どこまで<strong>正しく答えられる</strong>か。単位は割合。</li>
<li><span class="taginfo">情報量を目標</span> … どこまで<strong>候補が絞れている</strong>か。単位は bit。</li>
</ul>
<p class="small"><strong>手続きは完全に同じ。</strong>軸に載っている量だけが違う。
だから2つの差は「目標の選び方」だけから来る。曲線はどちらも
参加者ブートストラップの<strong>袋詰め PAVA（単調回帰）</strong>で推定していて、
測った範囲の外へは伸ばしていない。</p>
</div>

<div class="card star">
<h3 style="margin-top:.2rem">採用した情報量の指標</h3>
<p><strong>相互情報量の字ごとの分け前</strong>
<code>D<sub>c</sub>(x) = KL( P(R|c,x) ‖ P(R|x) )</code>（単位 bit）。
「その回答を見て、<strong>どの字が出たか</strong>がどれだけ分かるか」そのもの。</p>
<p class="small"><code>analyze_information.py</code> は3つ出して比べている。
① 応答分布のエントロピー <code>H(R|x)</code>（実質何択か）は直感的だが、
<strong>何も聞こえなくて「つ」に偏る</strong>のと
<strong>聞こえていて「か」に偏る</strong>のを区別できない。
② 事前分布からの情報利得 <code>KL</code> は事前の偏りを差し引けるが、
刺激と無関係に回答が動いただけでも大きくなる。
③ は基準がその水準の<strong>実測の周辺分布</strong> <code>P(R|x)</code> なので、
事前の偏りが自動的に差し引かれ、何も届いていなければ 0 になる。字ごとに分けられるので
字ごとの転写にそのまま使える。<strong>③を目標に採った。</strong></p>
<p class="small">⚠ 対象が8字なので上限は <code>H(S)=3 bit</code>。実運用の字数ではもっと大きくなる（縮尺の話）。
⚠ 素の推定は必ず上に偏るので、<strong>字のラベルを並べ替えた偽の情報量を引いて</strong>いる。</p>
</div>

<div id="bar">
  <label><span class="ttlkey">方式</span><select id="selFam"></select></label>
  <label><span class="ttlkey">条件</span><select id="selCond">
    <option value="proposed">転写 proposed</option>
    <option value="baseline1">等速 baseline1</option>
    <option value="baseline2">一次変換 baseline2</option>
  </select></label>
  <label><span class="ttlkey">端からの向き</span><select id="selDir">
    <option value="ltr">左→右</option><option value="rtl">右→左</option>
    <option value="ttb">上→下</option><option value="btt">下→上</option>
  </select></label>
  <button id="btnPlayAll">見えているぶんを順に再生（300ms）</button>
  <span class="small" id="loading">画像を読み込み中…</span>
</div>

<!-- ================= §1 が ================= -->
<h2>1. まず「が」を見る ― いちばんの見どころ</h2>
<div class="card">
<div class="bigstat" id="gastat"></div>
<p class="small" id="gatext"></p>
</div>
<p class="small">横は<strong>聴覚の打ち切り7点</strong>（<code>transfer_config.js</code> の
<code>audio.gates_ms</code>）。その時刻に画面に出ている絵をそのまま描いている。
上段が <span class="tagacc">正答率を目標</span>、下段が <span class="taginfo">情報量を目標</span>。
<span class="pill pillbad">赤枠</span>は7点のあいだで進み具合が 1pt も動かないセル（＝転写できない）。</p>
<div id="frames_ga"></div>
<div class="card">
<p class="small" style="margin:0"><strong>正直に書いておく：</strong>
うすい（fade）は<strong>どちらの目標でも絵としては薄い</strong>。
この方式は見え方の変化がぜんぶ進み具合 0〜3% に詰まっているので、
情報量版の <code>s ≒ 1.0〜2.0%</code> でも不透明度は数％にしかならない。
情報量を目標にして変わったのは「<strong>7点のあいだで絵が動くようになった</strong>」ことであって
（うすい×が の別々の絵は 2枚 → 4枚）、「はっきり見えるようになった」ことではない。
はっきりした違いが出るのは<strong>点が増える・ぼやけ・端から</strong>のほう。
方式を切り替えて見比べること。</p>
</div>

<!-- ================= §2 全部 ================= -->
<h2>2. 8字 × 選んだ方式</h2>
<p class="small">上の操作バーで方式を切り替える。「が」は §1 と同じものを再掲している。</p>
<div id="frames_all"></div>

<!-- ================= §3 何が違うか ================= -->
<h2>3. 何が違うか</h2>

<h3>3-1. 転写できないセル（進み具合が動かない）</h3>
<p class="small">「不成立」＝ 7つの打ち切り点のあいだで進み具合が <strong>1ポイントも動かない</strong>。
その字・その方式では、参加者に何を見せても同じ絵になり、<strong>測定そのものが成立しない</strong>。</p>
<div id="deadsum"></div>
<div style="overflow-x:auto"><div id="mx"></div></div>

<h3>3-2. 打ち切り7点のうち、何点で別の絵になるか</h3>
<p class="small">進み具合が動いても、<strong>絵が変わらなければ</strong>意味がない。
そこで7点の進み具合を実際の描画の段階（うすい＝不透明度、点が増える＝画素数、
ぼやけ＝ぼかし半径、端から＝出ている画素数）に量子化して、<strong>何通りの絵になるか</strong>を数える。
7 なら7点とも別の絵、1 なら全部同じ絵。</p>
<div id="fig_distinct"></div>
<div id="tbl_distinct"></div>

<h3>3-3. 進み具合そのものの違い</h3>
<p class="small">選んだ方式について、8字ぶんの <code>s(t)</code> を重ねて描く。
<span class="tagacc">紫＝正答率を目標</span>／<span class="taginfo">緑＝情報量を目標</span>。
丸は打ち切り7点。縦軸は進み具合（%）。<strong>字ごとに縦軸の上限を変えている</strong>
（うすいのように 0〜3% にすべてが詰まる方式があるため）。</p>
<div id="fig_st"></div>

<!-- ================= §4 目標の軌跡 ================= -->
<h2>4. なぜアニメーションが変わるのか ― 目標の軌跡そのもの</h2>
<p class="small">アニメーションの違いは、<strong>逆引きする前の「目標の軌跡」</strong>の違いから来る。
「が」について、正答率の軌跡と情報量の軌跡を並べる。</p>
<div id="fig_ga"></div>

<h3>4-2. 「が」は何と答えられていたか</h3>
<p class="small">同じ「ほとんど正解しない」でも、中身が違う。
帯は打ち切り点ごとの回答の内訳（多い順に6つ、残りは「その他」）。
出どころ <code id="srcTrials"></code>。</p>
<div id="fig_resp"></div>

<h3>4-3. 8字ぜんぶの軌跡</h3>
<div id="fig_all_traj"></div>

<hr style="border:none;border-top:1px solid var(--line);margin:3rem 0 1rem">
<p class="small" id="prov"></p>

<script>
/*__CFG__*/
const P = { get: function(){ return null; } };   // transfer.js の切り出しが読むクエリ引数（ここでは無し）
const GROUP = "b";
/* ======================================================================
 * ここから experiment/transfer.js の本文をそのまま貼っている。
 *   'const SIZE = CFG.visual.size_px;' 〜 'function loadImage(' の直前まで。
 * 一行も書き換えていない。書き換えたら、参加者が見るものと違うものが出る。
 * ====================================================================== */
/*__TRANSFER_JS_SLICE__*/
/* ======================== 貼りつけここまで ======================== */
</script>

<script>
/*__DATA__*/

const LAB = DATA.lab;
const TKEYS = ["acc", "info"];
const TLAB = {acc:"正答率を目標", info:"情報量を目標"};
const ui = {fam:"fade", cond:"proposed", dir:"ltr"};

function isDark(){
  const t = document.documentElement.getAttribute("data-theme");
  if (t) return t === "dark";
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}
function cssvar(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

// 画像は data URI から。ふつうのパス参照だと file:// で canvas が汚染され、
// 点が増える／端から の getImageData が例外になる。
let imgsReady = false;
function loadAll(){
  return Promise.all(DATA.chars.map(ch => new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => { imgs[ch] = im; res(); };
    im.onerror = () => rej(new Error(ch));
    im.src = DATA.images[ch];
  }))).then(() => { imgsReady = true; });
}

function cellOf(target, fam, ch){
  return DATA.cells.find(c => c.target === target && c.family === fam && c.char === ch);
}
function isDead(target, fam, ch){
  const c = cellOf(target, fam, ch);
  return !!c && c.judgement.indexOf("不成立") === 0;
}

// ---------------------------------------------------------------------------
// 絵を描く（transfer.js の progressFn / RENDERERS をそのまま呼ぶ）
// ---------------------------------------------------------------------------
function drawCell(cv, target, fam, ch, cond, ms){
  warpTables = DATA.tables[target].doc;
  const ctx = cv.getContext("2d", {willReadFrequently:true});
  const R = RENDERERS[fam] || RENDERERS.fade;
  const {fn} = progressFn({play:"warp", family:fam, char:ch, condition:cond});
  R.begin(ch, ctx);
  R.draw(ctx, ch, fn(ms), ui.dir);
  return fn(ms);
}

function buildFrames(host, chars){
  host.innerHTML = "";
  const fam = ui.fam;
  const t = document.createElement("table");
  t.className = "frames";
  let head = "<tr><th></th><th></th>";
  for (let i = 0; i < 7; i++) head += '<th class="gh">打ち切り ' + (i+1) + '</th>';
  head += '<th class="gh">再生</th></tr>';
  t.innerHTML = head;
  chars.forEach(ch => {
    const g = DATA.gates[ch];
    TKEYS.forEach((target, ki) => {
      const tr = document.createElement("tr");
      if (target === "info") tr.className = "rowinfo sep";
      if (ki === 0){
        const th = document.createElement("th");
        th.className = "chh"; th.rowSpan = 2; th.textContent = ch;
        tr.appendChild(th);
      }
      const lab = document.createElement("td");
      lab.className = "rowlbl";
      lab.innerHTML = '<span class="' + (target === "acc" ? "tagacc" : "taginfo") + '">'
                    + (target === "acc" ? "正答率" : "情報量") + '</span>';
      tr.appendChild(lab);
      const dead = isDead(target, fam, ch);
      g.forEach((ms, gi) => {
        const td = document.createElement("td");
        const box = document.createElement("div");
        box.className = "cell" + (dead ? " dead" : "");
        const cv = document.createElement("canvas");
        cv.width = CFG.visual.size_px; cv.height = CFG.visual.size_px;
        box.appendChild(cv);
        const cap = document.createElement("div"); cap.className = "cap";
        box.appendChild(cap);
        td.appendChild(box); tr.appendChild(td);
        const s = drawCell(cv, target, fam, ch, ui.cond, ms);
        cap.innerHTML = "t=" + ms + "ms<br><b>s=" + (s*100).toFixed(2) + "%</b>";
      });
      const tdp = document.createElement("td");
      const b = document.createElement("button");
      b.className = "playbtn"; b.textContent = "▶";
      b.onclick = () => playRow(tr, target, fam, ch);
      tdp.appendChild(b);
      if (dead){
        const d = document.createElement("div");
        d.className = "deadnote"; d.textContent = "動かない";
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

// 実時間 300ms の再生。行の canvas を全部使って動かし、終わったら元の絵に戻す。
let playing = false;
function playRow(tr, target, fam, ch){
  if (playing) return;
  const cvs = Array.from(tr.querySelectorAll("canvas"));
  if (!cvs.length) return;
  playing = true;
  warpTables = DATA.tables[target].doc;
  const R = RENDERERS[fam] || RENDERERS.fade;
  const {fn} = progressFn({play:"warp", family:fam, char:ch, condition:ui.cond});
  const ctxs = cvs.map(c => c.getContext("2d", {willReadFrequently:true}));
  ctxs.forEach(c => R.begin(ch, c));
  const t0 = performance.now();
  const dur = CFG.visual.base_anim_ms;
  // 逃げ道: タブが裏に回ると requestAnimationFrame が来ない。
  const guard = setTimeout(() => {
    if (!playing) return;
    playing = false; redrawRow(tr, target, fam, ch);
  }, dur + 2000);
  function step(now){
    const el = now - t0;
    const s = fn(Math.min(el, dur));
    ctxs.forEach(c => { R.begin(ch, c); R.draw(c, ch, s, ui.dir); });
    if (el < dur) requestAnimationFrame(step);
    else { playing = false; clearTimeout(guard);
           setTimeout(() => redrawRow(tr, target, fam, ch), 400); }
  }
  requestAnimationFrame(step);
}
function redrawRow(tr, target, fam, ch){
  const cvs = Array.from(tr.querySelectorAll("canvas"));
  const g = DATA.gates[ch];
  cvs.forEach((cv, i) => { if (i < g.length) drawCell(cv, target, fam, ch, ui.cond, g[i]); });
}
// 上下2段を続けて再生する（同じ字の正答率版→情報量版）
function playAll(){
  if (playing) return;
  const rows = Array.from(document.querySelectorAll("#frames_ga tr, #frames_all tr"))
                    .filter(r => r.querySelector("canvas"));
  let i = 0;
  const next = () => {
    if (i >= rows.length) return;
    const b = rows[i++].querySelector(".playbtn");
    if (b) b.click();
    setTimeout(next, CFG.visual.base_anim_ms + 300);
  };
  next();
}

// ---------------------------------------------------------------------------
// SVG のこまごま
// ---------------------------------------------------------------------------
function el(name, attrs, text){
  const n = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  return n;
}
function svg(w, h){
  const s = el("svg", {class:"fig", viewBox:"0 0 " + w + " " + h, width:w, height:h});
  return s;
}
function figure(host, s, caption){
  const f = document.createElement("figure");
  const wrap = document.createElement("div"); wrap.className = "figwrap";
  wrap.appendChild(s); f.appendChild(wrap);
  if (caption){
    const c = document.createElement("figcaption");
    c.innerHTML = caption; f.appendChild(c);
  }
  host.appendChild(f);
}
function niceMax(v){
  if (v <= 0) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / e;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * e;
}
function fmtS(v){ return v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2); }

// ---------------------------------------------------------------------------
// §1 の見出し数値
// ---------------------------------------------------------------------------
function buildGaStat(){
  const f = DATA.resp["が"].full;
  const g0 = DATA.resp["が"].gates[0];
  const fi = DATA.full["が"];
  const host = document.getElementById("gastat");
  const acc = (f.correct / Math.max(f.n,1) * 100);
  host.innerHTML =
    '<div><b>' + acc.toFixed(1) + '%</b><span>全部聞かせたときの「が」の正答率<br>'
      + f.n + '試行中 ' + f.correct + '</span></div>' +
    '<div><b>' + f.top[0][1] + '</b><span>そのうち「' + f.top[0][0]
      + '」と答えた数<br>＝実質1択まで絞れている</span></div>' +
    '<div><b>' + f.n_kinds + '種類</b><span>全部聞かせたときの答えの種類</span></div>' +
    '<div><b>' + g0.n_kinds + '種類</b><span>10ms（何も聞こえない）の答えの種類<br>'
      + g0.n + '試行</span></div>' +
    '<div><b style="color:var(--info)">' + fi.bits.toFixed(2) + ' bit</b>'
      + '<span>全部聞かせたときの情報量<br>（上限 3 bit）</span></div>';
  const c_acc = cellOf("acc", "fade", "が"), c_inf = cellOf("info", "fade", "が");
  document.getElementById("gatext").innerHTML =
    '正答率で読むと、「が」の目標は最初の打ち切りで <b>0%</b>、最後でも <b>'
    + (c_acc.target_last_gate*100).toFixed(1) + '%</b> しか上がらない。'
    + '逆引きすると進み具合はほとんど動かず、<b>うすい</b>では7点のあいだで '
    + c_acc.span_pt_gates.toFixed(2) + 'pt（＝ほぼ真っ白のまま）。'
    + '情報量で読むと、同じ「が」の目標は <b>' + c_inf.target_first_gate.toFixed(2)
    + ' bit → ' + c_inf.target_last_gate.toFixed(2) + ' bit</b> と上がっていく。'
    + '「候補が絞れていく」ぶんが見えているからである。';
}

// ---------------------------------------------------------------------------
// §3-1 成立判定のマトリクス
// ---------------------------------------------------------------------------
function jclass(j){ return j.indexOf("不成立") === 0 ? "j0" : (j.indexOf("一部") === 0 ? "j1" : "j2"); }
function jshort(j){ return j.indexOf("不成立") === 0 ? "×" : (j.indexOf("一部") === 0 ? "△" : "○"); }

function buildMatrix(){
  let h = '<table class="mx"><tr><th rowspan="2">方式</th><th rowspan="2">目標</th>';
  DATA.chars.forEach(c => h += '<th>' + c + '</th>');
  h += '<th rowspan="2">不成立</th></tr><tr></tr>';
  DATA.fams.forEach(fam => {
    TKEYS.forEach(target => {
      h += '<tr>';
      if (target === "acc") h += '<th rowspan="2">' + LAB[fam] + '</th>';
      h += '<td class="' + (target==="acc"?"tagacc":"taginfo") + '" style="text-align:left">'
         + (target === "acc" ? "正答率" : "情報量") + '</td>';
      let nd = 0;
      DATA.chars.forEach(ch => {
        const c = cellOf(target, fam, ch);
        if (c.judgement.indexOf("不成立") === 0) nd++;
        h += '<td class="' + jclass(c.judgement) + '" title="'
           + c.judgement + ' / 可動域 ' + c.span_pt_gates.toFixed(2) + 'pt">'
           + jshort(c.judgement) + '<br><span style="font-size:.66rem;color:var(--muted)">'
           + fmtS(c.span_pt_gates) + '</span></td>';
      });
      h += '<td><b>' + nd + '</b></td></tr>';
    });
  });
  h += '</table>';
  h += '<p class="small">○ 成立（7点とも曲線の内側で解けた）／△ 一部成立（端で丸めた点がある）'
     + '／<span class="pill pillbad">× 不成立</span>（7点のあいだで進み具合が1pt も動かない）。'
     + '小さい数字は7点のあいだの進み具合の可動域（ポイント）。</p>';
  document.getElementById("mx").innerHTML = h;

  const dead = {};
  TKEYS.forEach(t => {
    dead[t] = DATA.cells.filter(c => c.target === t && c.judgement.indexOf("不成立") === 0);
  });
  const s = document.getElementById("deadsum");
  const li = dead.acc.map(c => LAB[c.family] + "×" + c.char).join("、");
  s.innerHTML =
    '<div class="bigstat">'
    + '<div><b class="tagacc">' + dead.acc.length + ' / 32</b>'
      + '<span>正答率を目標にしたときの不成立セル<br>' + (li || "なし") + '</span></div>'
    + '<div><b class="taginfo">' + dead.info.length + ' / 32</b>'
      + '<span>情報量を目標にしたときの不成立セル<br>'
      + (dead.info.length ? dead.info.map(c => LAB[c.family]+"×"+c.char).join("、") : "なし")
      + '</span></div></div>';
}

// ---------------------------------------------------------------------------
// §3-2 別々の絵の枚数
// ---------------------------------------------------------------------------
function buildDistinct(){
  const host = document.getElementById("fig_distinct");
  host.innerHTML = "";
  const W = 900, rowH = 30, padT = 40, padL = 110, padR = 62, padB = 46;
  const H = padT + DATA.fams.length * (rowH * 2 + 14) + padB;
  const s = svg(W, H);
  const x0 = padL, x1 = W - padR, yAx = H - padB + 6;
  const sc = v => x0 + (v - 1) / 6 * (x1 - x0);
  s.appendChild(el("text", {x:0, y:16, class:"ttl"},
    "打ち切り7点のうち、何点で別の絵になるか（札の中の字がその値になった字・縦棒は中央値）"));
  for (let v = 1; v <= 7; v++){
    s.appendChild(el("line", {x1:sc(v), y1:padT-6, x2:sc(v), y2:yAx, class:"grid"}));
    s.appendChild(el("text", {x:sc(v), y:yAx+14, class:"tiny", "text-anchor":"middle"}, v));
  }
  s.appendChild(el("text", {x:(x0+x1)/2, y:yAx+32, class:"lbl", "text-anchor":"middle"},
    "別々の絵の枚数（7点中）"));
  let y = padT;
  DATA.fams.forEach(fam => {
    s.appendChild(el("text", {x:x0-10, y:y+rowH-2, class:"lbl", "text-anchor":"end"}, LAB[fam]));
    TKEYS.forEach(target => {
      const col = target === "acc" ? cssvar("--acc") : cssvar("--info");
      const vals = DATA.chars.map(ch => cellOf(target, fam, ch).n_distinct_at_gates);
      const yy = y + (target === "acc" ? 8 : 8 + rowH);
      s.appendChild(el("text", {x:x0-10, y:yy+4, class:"tiny", "text-anchor":"end",
                                fill:col}, target === "acc" ? "正答率" : "情報量"));
      // 中央値の縦棒は札の下に敷く（重なっても読めるように先に描く）
      const sorted = vals.slice().sort((a,b)=>a-b);
      const med = (sorted[3] + sorted[4]) / 2;
      s.appendChild(el("path", {d:"M" + sc(med) + " " + (yy-13) + "v26",
                                stroke:col, "stroke-width":2.4, "stroke-opacity":.9}));
      // 同じ値の字はまとめて1つの札にする（点を縦に積むと隣の行にはみ出すため）
      const bag = {};
      vals.forEach((v, i) => { (bag[v] = bag[v] || []).push(DATA.chars[i]); });
      Object.keys(bag).forEach(v => {
        const chs = bag[v].join("");
        const w = chs.length * 11 + 8;
        s.appendChild(el("rect", {x:sc(+v)-w/2, y:yy-9, width:w, height:18, rx:4,
                                  fill:col, "fill-opacity":.16, stroke:col,
                                  "stroke-opacity":.55}));
        s.appendChild(el("text", {x:sc(+v), y:yy+4, "text-anchor":"middle", fill:col,
                                  style:"font-size:11px;font-weight:700"}, chs));
      });
    });
    y += rowH * 2 + 14;
  });
  figure(host, s,
    "右にあるほどよい（7＝打ち切り7点が全部ちがう絵になる）。"
    + "縦棒はその方式・その目標の中央値。"
    + "<b>うすい</b>だけは目標を替えても右へ動きにくい ―― この方式は"
    + "見え方の変化がぜんぶ進み具合 0〜3% に詰まっていて、"
    + "そもそも刻める絵の枚数が少ないためである（目標の選び方の問題ではない）。");

  // 表
  let h = '<table class="tbl"><tr><th>方式</th><th>目標</th>'
        + '<th class="num">別々の絵の枚数（中央値）</th>'
        + '<th class="num">最小</th><th class="num">7点とも別の絵になった字の数</th>'
        + '<th class="num">可動域の中央値 pt</th></tr>';
  DATA.fams.forEach(fam => {
    TKEYS.forEach(target => {
      const vs = DATA.chars.map(ch => cellOf(target, fam, ch));
      const nd = vs.map(c => c.n_distinct_at_gates).sort((a,b)=>a-b);
      const sp = vs.map(c => c.span_pt_gates).sort((a,b)=>a-b);
      h += '<tr><td>' + (target==="acc" ? LAB[fam] : "") + '</td>'
         + '<td class="' + (target==="acc"?"tagacc":"taginfo") + '">'
         + (target==="acc"?"正答率":"情報量") + '</td>'
         + '<td class="num">' + ((nd[3]+nd[4])/2).toFixed(1) + '</td>'
         + '<td class="num">' + nd[0] + '</td>'
         + '<td class="num">' + vs.filter(c => c.n_distinct_at_gates >= 7).length + '</td>'
         + '<td class="num">' + ((sp[3]+sp[4])/2).toFixed(2) + '</td></tr>';
    });
  });
  h += '</table>';
  document.getElementById("tbl_distinct").innerHTML = h;
}

// ---------------------------------------------------------------------------
// §3-3 s(t) の重ね描き
// ---------------------------------------------------------------------------
function seriesOf(target, fam, ch, cond){
  const d = DATA.tables[target].doc;
  return d.tables[fam][ch][cond || ui.cond];
}
function buildST(){
  const host = document.getElementById("fig_st");
  host.innerHTML = "";
  const fam = ui.fam;
  const cols = 4, cw = 215, ch_ = 155, padL = 44, padB = 30, padT = 26, padR = 12;
  const rows = Math.ceil(DATA.chars.length / cols);
  const s = svg(cols * cw, rows * ch_ + 6);
  DATA.chars.forEach((ch, i) => {
    const gx = (i % cols) * cw, gy = Math.floor(i / cols) * ch_;
    const x0 = gx + padL, x1 = gx + cw - padR, y0 = gy + padT, y1 = gy + ch_ - padB;
    const doc = DATA.tables.acc.doc;
    const frameMs = doc.frame_ms, dur = doc.duration_ms;
    let mx = 0;
    TKEYS.forEach(t => seriesOf(t, fam, ch).forEach(v => { if (v*100 > mx) mx = v*100; }));
    mx = Math.max(niceMax(mx * 1.12), 0.5);
    const sx = t => x0 + t / dur * (x1 - x0);
    const sy = v => y1 - Math.min(v, mx) / mx * (y1 - y0);
    s.appendChild(el("line", {x1:x0, y1:y1, x2:x1, y2:y1, class:"ax"}));
    s.appendChild(el("line", {x1:x0, y1:y0, x2:x0, y2:y1, class:"ax"}));
    s.appendChild(el("text", {x:x0, y:gy+14, class:"ttl"}, ch + "（" + LAB[fam] + "）"));
    s.appendChild(el("text", {x:x0-6, y:y0+4, class:"tiny", "text-anchor":"end"}, fmtS(mx)+"%"));
    s.appendChild(el("text", {x:x0-6, y:y1+3, class:"tiny", "text-anchor":"end"}, "0"));
    s.appendChild(el("text", {x:x1, y:y1+16, class:"tiny", "text-anchor":"end"}, dur+"ms"));
    TKEYS.forEach(target => {
      const col = target === "acc" ? cssvar("--acc") : cssvar("--info");
      const ser = seriesOf(target, fam, ch);
      let d = "";
      ser.forEach((v, k) => { d += (k ? "L" : "M") + sx(k*frameMs).toFixed(2) + " "
                                 + sy(v*100).toFixed(2) + " "; });
      s.appendChild(el("path", {d:d, fill:"none", stroke:col, "stroke-width":2.1}));
      DATA.gates[ch].forEach(ms => {
        const k = Math.min(ser.length-1, ms / frameMs);
        const i0 = Math.floor(k), f = k - i0;
        const v = (ser[i0] * (1-f) + ser[Math.min(i0+1, ser.length-1)] * f) * 100;
        s.appendChild(el("circle", {cx:sx(Math.min(ms,dur)), cy:sy(v), r:2.6,
                                    fill:col, stroke:"var(--card)", "stroke-width":.8}));
      });
    });
  });
  figure(host, s,
    '<span style="color:var(--acc)">紫＝正答率を目標</span>／'
    + '<span style="color:var(--info)">緑＝情報量を目標</span>。'
    + '縦軸の上限は字ごとに違う（右上に表示）。丸は打ち切り7点。'
    + '条件は <b>' + ui.cond + '</b>。');
}

// ---------------------------------------------------------------------------
// §4 目標の軌跡
// ---------------------------------------------------------------------------
function trajPanel(s, gx, gy, cw, chh, ch, kind){
  const padL = 52, padB = 34, padT = 30, padR = 16;
  const x0 = gx + padL, x1 = gx + cw - padR, y0 = gy + padT, y1 = gy + chh - padB;
  const xs = DATA.curves.audio_levels[ch];
  const ys = kind === "acc" ? DATA.curves.audio_acc[ch] : DATA.curves.audio_bits[ch];
  const col = kind === "acc" ? cssvar("--acc") : cssvar("--info");
  const mx = kind === "acc" ? 1 : 3;
  const lo = Math.log(Math.max(xs[0], 1e-6)), hi = Math.log(xs[xs.length-1]);
  const sx = v => x0 + (Math.log(Math.max(v,1e-6)) - lo) / (hi - lo) * (x1 - x0);
  const sy = v => y1 - Math.min(v, mx) / mx * (y1 - y0);
  s.appendChild(el("line", {x1:x0, y1:y1, x2:x1, y2:y1, class:"ax"}));
  s.appendChild(el("line", {x1:x0, y1:y0, x2:x0, y2:y1, class:"ax"}));
  s.appendChild(el("text", {x:x0, y:gy+16, class:"ttl", fill:col},
    kind === "acc" ? (ch + "：正答率の軌跡") : (ch + "：情報量の軌跡")));
  const nt = kind === "acc" ? 5 : 4;
  for (let i = 0; i <= nt; i++){
    const v = mx * i / nt;
    s.appendChild(el("line", {x1:x0, y1:sy(v), x2:x1, y2:sy(v), class:"grid"}));
    s.appendChild(el("text", {x:x0-6, y:sy(v)+3.5, class:"tiny", "text-anchor":"end"},
      kind === "acc" ? (v*100).toFixed(0)+"%" : v.toFixed(1)));
  }
  s.appendChild(el("text", {x:x0-40, y:y0-10, class:"tiny"},
    kind === "acc" ? "正答率" : "bit"));
  let d = "";
  xs.forEach((x, i) => { d += (i ? "L" : "M") + sx(x).toFixed(2) + " " + sy(ys[i]).toFixed(2) + " "; });
  s.appendChild(el("path", {d:d, fill:"none", stroke:col, "stroke-width":2.4}));
  xs.forEach((x, i) => {
    s.appendChild(el("circle", {cx:sx(x), cy:sy(ys[i]), r:3.4, fill:col}));
    s.appendChild(el("text", {x:sx(x), y:y1+14, class:"tiny", "text-anchor":"middle"}, x));
  });
  s.appendChild(el("text", {x:(x0+x1)/2, y:y1+28, class:"tiny", "text-anchor":"middle"},
    "打ち切り時刻（ms・対数目盛）"));
  return {x0:x0, x1:x1, y0:y0, y1:y1, sy:sy, mx:mx};
}

function buildGaTraj(){
  const host = document.getElementById("fig_ga");
  host.innerHTML = "";
  const cw = 440, chh = 220;
  const s = svg(cw * 2, chh);
  const a = trajPanel(s, 0, 0, cw, chh, "が", "acc");
  trajPanel(s, cw, 0, cw, chh, "が", "info");
  // 正答率の頭打ちを示す
  const top = DATA.curves.audio_acc["が"][6];
  s.appendChild(el("text", {x:a.x0+10, y:a.sy(top)-8, class:"tiny", fill:cssvar("--acc"),
                            style:"font-weight:700"},
    "最後まで " + (top*100).toFixed(1) + "% で頭打ち"));
  figure(host, s,
    '左：正答率で読んだ「が」。7点とも 0〜' + (top*100).toFixed(1)
    + '% で、ほとんど動かない。逆引きすると進み具合も動かない。<br>'
    + '右：情報量で読んだ「が」。'
    + DATA.curves.audio_bits["が"][0].toFixed(2) + ' bit → '
    + DATA.curves.audio_bits["が"][6].toFixed(2)
    + ' bit と上がっていく。「候補が絞れていく」ぶんが見えている。<br>'
    + '曲線はどちらも袋詰め PAVA（単調回帰）。出どころ <code>'
    + DATA.src.curves + '</code>。');
}

// 回答の内訳の帯
function buildResp(){
  const host = document.getElementById("fig_resp");
  host.innerHTML = "";
  const R = DATA.resp["が"];
  const rows = [{lab:"参考：10ms・8字ぜんぶ", g: DATA.resp._pooled10, ref:true}]
    .concat(R.gates.map(g => ({lab: "が " + g.t_ms + "ms", g: g})))
    .concat([{lab:"が 打ち切りなし", g: R.full}]);
  const W = 900, rowH = 30, padL = 140, padR = 160, padT = 34;
  const H = padT + rows.length * rowH + 16;
  const s = svg(W, H);
  const x0 = padL, x1 = W - padR;
  s.appendChild(el("text", {x:0, y:18, class:"ttl"},
    "「が」を聞いたとき、参加者は何と答えたか（多い順に6つ＋その他）"));
  const pal = isDark()
    ? ["#5ec8bb","#e8a14c","#cf95e6","#7fb3e8","#e88a8a","#b9c96a","#6b6560"]
    : ["#0f766e","#b45309","#8a3ea8","#1d6fa5","#b91c1c","#5d7a1f","#9a948d"];
  rows.forEach((r, i) => {
    const y = padT + i * rowH;
    const n = Math.max(r.g.n, 1);
    if (r.ref){
      s.appendChild(el("line", {x1:0, y1:y+rowH-3, x2:W, y2:y+rowH-3, class:"grid"}));
    }
    s.appendChild(el("text", {x:x0-8, y:y+16, class:"lbl", "text-anchor":"end",
                              style: r.ref ? "font-style:italic" : ""}, r.lab));
    let acc = 0;
    const top = r.g.top;
    const other = r.g.n - top.reduce((a,b) => a + b[1], 0);
    const segs = top.concat(other > 0 ? [["その他", other]] : []);
    segs.forEach((sg, k) => {
      const w = sg[1] / n * (x1 - x0);
      const col = sg[0] === "その他" ? pal[6] : pal[k % 6];
      s.appendChild(el("rect", {x:x0+acc, y:y+2, width:Math.max(w,0.6), height:rowH-8,
                                fill:col, "fill-opacity": sg[0]==="が" ? 1 : .72,
                                stroke: sg[0]==="が" ? cssvar("--fg") : "none",
                                "stroke-width": sg[0]==="が" ? 1.6 : 0}));
      if (w > 26){
        s.appendChild(el("text", {x:x0+acc+w/2, y:y+17, class:"tiny",
                                  "text-anchor":"middle", fill:"#fff",
                                  style:"font-size:10.5px;font-weight:700"},
                         sg[0] + " " + sg[1]));
      }
      acc += w;
    });
    s.appendChild(el("text", {x:x1+8, y:y+16, class:"tiny"},
      "n=" + r.g.n + " / 答えの種類 " + r.g.n_kinds + " / 正答 " + r.g.correct));
  });
  figure(host, s,
    "いちばん上は参考：<b>10ms を8字ぶん束ねた</b>もの（何も聞こえないときに人が何と答えるか＝事前の偏り）。"
    + "「つ」に寄るので<b>一様分布ではない</b>。<br>"
    + "「が」の10ms では答えが散らばる＝<b>何も届いていない</b>。"
    + "打ち切りなし（いちばん下・" + R.full.n + "試行）では「"
    + R.full.top[0][0] + "」に集中する＝<b>届いているが1つ隣にずれている</b>。"
    + "正答率はこの2つを同じ『ほぼ0%』として扱う。情報量は区別する。"
    + "「が」（正解）の帯だけ縁取りしてある。<br>"
    + "「打ち切りなし」は、はしごに埋め込んだぶんと確認問題の両方を数えている"
    + "（<code>analyze_information.py</code> の参照点と同じ数え方）。");
}

function buildAllTraj(){
  const host = document.getElementById("fig_all_traj");
  host.innerHTML = "";
  const cols = 4, cw = 240, chh = 190;
  const rows = Math.ceil(DATA.chars.length / cols);
  const s = svg(cols * cw, rows * chh);
  DATA.chars.forEach((ch, i) => {
    const gx = (i % cols) * cw, gy = Math.floor(i / cols) * chh;
    const padL = 40, padB = 30, padT = 26, padR = 12;
    const x0 = gx + padL, x1 = gx + cw - padR, y0 = gy + padT, y1 = gy + chh - padB;
    const xs = DATA.curves.audio_levels[ch];
    const lo = Math.log(xs[0]), hi = Math.log(xs[xs.length-1]);
    const sx = v => x0 + (Math.log(v) - lo) / (hi - lo) * (x1 - x0);
    s.appendChild(el("line", {x1:x0, y1:y1, x2:x1, y2:y1, class:"ax"}));
    s.appendChild(el("line", {x1:x0, y1:y0, x2:x0, y2:y1, class:"ax"}));
    s.appendChild(el("text", {x:x0, y:gy+15, class:"ttl"}, ch));
    // 正答率（0〜1）と情報量（0〜3）をそれぞれの上限で正規化して重ねる
    [["acc", DATA.curves.audio_acc[ch], 1], ["info", DATA.curves.audio_bits[ch], 3]]
      .forEach(([k, ys, mx]) => {
        const col = k === "acc" ? cssvar("--acc") : cssvar("--info");
        const sy = v => y1 - Math.min(v, mx) / mx * (y1 - y0);
        let d = "";
        xs.forEach((x, j) => { d += (j ? "L" : "M") + sx(x).toFixed(2) + " " + sy(ys[j]).toFixed(2) + " "; });
        s.appendChild(el("path", {d:d, fill:"none", stroke:col, "stroke-width":2,
                                  "stroke-dasharray": k === "acc" ? "" : ""}));
        xs.forEach((x, j) => s.appendChild(el("circle", {cx:sx(x), cy:sy(ys[j]), r:2.4, fill:col})));
      });
    s.appendChild(el("text", {x:x0-5, y:y0+4, class:"tiny", "text-anchor":"end"}, "100%"));
    s.appendChild(el("text", {x:x0-5, y:y1+3, class:"tiny", "text-anchor":"end"}, "0"));
    s.appendChild(el("text", {x:x1, y:y1+15, class:"tiny", "text-anchor":"end"},
      xs[0] + "〜" + xs[xs.length-1] + "ms"));
  });
  figure(host, s,
    '<span style="color:var(--acc)">紫＝正答率（縦軸 0〜100%）</span>／'
    + '<span style="color:var(--info)">緑＝情報量（縦軸 0〜3 bit）</span>。'
    + '縦軸はそれぞれの上限で正規化して重ねてある（単位が違うので高さそのものは比べない）。'
    + '「が」だけ紫が床に張りついている。');
}

// ---------------------------------------------------------------------------
// 起動
// ---------------------------------------------------------------------------
function rebuild(){
  buildFrames(document.getElementById("frames_ga"), ["が"]);
  buildFrames(document.getElementById("frames_all"), DATA.chars);
  buildST();
}
function init(){
  const sf = document.getElementById("selFam");
  DATA.fams.forEach(f => {
    const o = document.createElement("option");
    o.value = f; o.textContent = LAB[f]; sf.appendChild(o);
  });
  sf.value = ui.fam;
  sf.onchange = () => { ui.fam = sf.value; rebuild(); };
  const sc = document.getElementById("selCond");
  sc.onchange = () => { ui.cond = sc.value; rebuild(); };
  const sd = document.getElementById("selDir");
  sd.onchange = () => { ui.dir = sd.value; rebuild(); };
  document.getElementById("btnPlayAll").onclick = playAll;
  document.getElementById("srcTrials").textContent = DATA.src.trials;

  buildGaStat();
  buildMatrix();
  buildDistinct();
  buildGaTraj();
  buildResp();
  buildAllTraj();

  document.getElementById("prov").innerHTML =
    "出どころ：warp 表 <code>" + DATA.tables.acc.path + "</code> / <code>"
    + DATA.tables.info.path + "</code>（どちらも "
    + DATA.tables.acc.covers_ms + "ms ぶん）、曲線 <code>" + DATA.src.curves
    + "</code>、セルごとの数値 <code>" + DATA.src.log + "</code>。"
    + "描画は <code>experiment/transfer.js</code> の切り出し。"
    + "本番の <code>experiment/transfer_warp.json</code> は書き換えていない。";

  loadAll().then(() => {
    document.getElementById("loading").textContent = "";
    rebuild();
  }).catch(e => {
    document.getElementById("loading").textContent = "画像が読めない: " + e.message;
  });
}
init();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
