#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=========================================================================
warp 表のプレビューページを組み立てる（研究者用・参加者には配らない）
=========================================================================

何のためのページか
------------------
転写(proposed)とは「**音を途中まで聞いたときの正答率**を、文字アニメーションが
**同じ時刻に同じ正答率**になるように進み具合を決める」やり方である。
このページは、その

    聴覚の曲線 → 逆引き → 進み具合の列 s(t) → 実際の絵

という流れを、**1枚の図と実物の絵**で追えるようにする。

作り方の要点
------------
1. **描画は書き直さない。** experiment/transfer.js の
   `const SIZE = ...` から `function loadImage(` の直前までを **そのまま切り出して**
   ページに貼る（fadeDraw / revealDraw / blurDraw / wipeDraw / compositeDraw /
   compositeSplit / blurApplyFilter / wipeApplyClip / warpSeries / seriesAt /
   progressFn がまるごと入る）。
   experiment/tools/check_warp_playback.js と同じ手口。切り出しの目印が
   transfer.js から消えたら、このスクリプトは止まる。
2. **file:// で開けるように、外から読むものは全部埋め込む。**
   - 文字画像(experiment/base/*.png) → data URI
     （getImageData を使う reveal/wipe は、ふつうのパス参照だと canvas が汚染されて
       file:// では動かない。data URI なら汚染されない）
   - warp 表4種・当てはめの数値(CSV) → JSON として <script> に埋め込む
   - 設定(transfer_config.js) → JSON として埋め込む
3. 本番の transfer_warp.json / transfer_config.js は**読むだけ**。書き換えない。

使い方:
    python3 experiment/tools/build_warp_preview.py
    open experiment/warp_preview.html
========================================================================="""
import io
import os
import json
import base64
import subprocess
import csv
import math

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXP = os.path.join(ROOT, "experiment")
CAL = os.path.join(ROOT, "project", "data_calib2_live")
OUT = os.path.join(EXP, "warp_preview.html")

CHARS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
FAMS = ["fade", "reveal", "blur", "wipe",
        "fade+blur", "fade+wipe", "reveal+blur", "reveal+wipe"]
L595 = math.log(19.0)


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
                 "function wipeDraw", "function blurApplyFilter", "function wipeApplyClip",
                 "function compositeSplit", "function compositeDraw",
                 "const RENDERERS", "function warpSeries", "function seriesAt",
                 "function progressFn"):
        if name not in s:
            raise SystemExit(f"切り出した範囲に {name} が入っていない")
    return s


# ---------------------------------------------------------------------------
# 2. 設定を node で JSON に落とす（transfer_config.js は代入1つだけの決まり）
# ---------------------------------------------------------------------------
def load_config():
    js = ("global.window={};require(%s);"
          "process.stdout.write(JSON.stringify(global.window.TRANSFER_CONFIG));"
          % json.dumps(os.path.join(EXP, "transfer_config.js")))
    out = subprocess.run(["node", "-e", js], capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


# ---------------------------------------------------------------------------
# 3. 画像を data URI に
# ---------------------------------------------------------------------------
def load_images():
    d = {}
    for ch in CHARS:
        p = os.path.join(EXP, "base", ch + ".png")
        with open(p, "rb") as f:
            d[ch] = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    return d


# ---------------------------------------------------------------------------
# 4. warp 表
# ---------------------------------------------------------------------------
TABLE_DEFS = [
    ("current", "現行（本番に置いてある表）", os.path.join(EXP, "transfer_warp.json"), "old"),
    ("v3_lin", "新・線形（4方式とも300ms）",
     os.path.join(CAL, "warp_v3", "transfer_warp_v3_linear.json"), "new"),
    ("v3_log", "新・対数線形（4方式とも300ms）",
     os.path.join(CAL, "warp_v3", "transfer_warp_v3_loglinear.json"), "new"),
    ("r300_lin", "新・線形（点が増えるだけ300ms）",
     os.path.join(CAL, "warp_v3_reveal300", "transfer_warp_v3_linear.json"), "new_r300"),
    ("r300_log", "新・対数線形（点が増えるだけ300ms）",
     os.path.join(CAL, "warp_v3_reveal300", "transfer_warp_v3_loglinear.json"), "new_r300"),
]


def load_tables():
    out = {}
    for key, label, path, fitset in TABLE_DEFS:
        if not os.path.exists(path):
            print(f"  ⚠ 見つからない（飛ばす）: {path}")
            continue
        doc = json.load(io.open(path, encoding="utf-8"))
        n = len(doc["tables"]["fade"]["あ"]["proposed"])
        fr = doc.get("frame_ms", 1000.0 / 60.0)
        out[key] = {"label": label, "fitset": fitset, "doc": doc,
                    "covers_ms": round((n - 1) * fr, 1),
                    "path": os.path.relpath(path, ROOT)}
        print(f"  表 {key:<9} {label}  数値列 {n} 点（{(n-1)*fr:.0f}ms まで）")
    return out


# ---------------------------------------------------------------------------
# 5. 当てはめの数値
#    P(x) = γ + (λ−γ)·logistic((x−μ)/σ)
#    λ は生成と同じく「全部聞かせ/全部見せの実測」で下から押さえる。
# ---------------------------------------------------------------------------
def _rows(path):
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


def _f(x, default=float("nan")):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load_fits():
    fits = {}

    # ---- 新（warp_v3 / warp_v3_reveal300） ----
    for tag, d in (("new", "warp_v3"), ("new_r300", "warp_v3_reveal300")):
        base = os.path.join(CAL, d)
        audio, visual = {}, {}
        for r in _rows(os.path.join(base, "fit_audio_v3.csv")):
            obs = _f(r.get("lambda_observed_full"), 0.0)
            audio[r["char"]] = {"g": _f(r["gamma"]), "lam": max(_f(r["lam"]), obs or 0.0),
                                "mu": _f(r["mu"]), "sg": _f(r["sigma"]),
                                "n_trials": _f(r.get("n_trials"), 0),
                                "n_participants": _f(r.get("n_participants"), 0)}
        for r in _rows(os.path.join(base, "fit_visual_v3.csv")):
            obs = _f(r.get("lambda_observed_full"), 0.0)
            visual[r["char"] + "|" + r["family"]] = {
                "g": _f(r["gamma"]), "lam": max(_f(r["lam"]), obs or 0.0),
                "mu": _f(r["mu"]), "sg": _f(r["sigma"]),
                "s5": _f(r.get("s5_pct")), "s95": _f(r.get("s95_pct")),
                "speed_ms": r.get("speed_ms", ""),
                "n_trials": _f(r.get("n_trials"), 0),
                "n_participants": _f(r.get("n_participants"), 0)}
        # 実測した水準の範囲（窓の丸め先）と、組み合わせの窓
        levels, windows = {}, {}
        for r in _rows(os.path.join(base, "composite_window.csv")):
            if r["mapping"] != "linear" and r["mapping"] != "loglinear":
                continue
            levels[r["family"]] = [_f(r["level_min_tested"]), _f(r["level_max_tested"])]
            windows[r["mapping"] + "|" + r["pair"] + "|" + r["family"] + "|" + r["char"]] = {
                "s5_raw": _f(r["s5_raw"]), "s95_raw": _f(r["s95_raw"]),
                "s5": _f(r["s5_clipped"]), "s95": _f(r["s95_clipped"]),
                "clip_lo": r["clipped_low"] == "True", "clip_hi": r["clipped_high"] == "True"}
        fits[tag] = {"audio": audio, "visual": visual, "levels": levels, "windows": windows}

    # ---- 現行（warp_new/fit_logistic_*.csv。ぼやけだけ実験1の当てはめ） ----
    audio, visual = {}, {}
    for fam_src, path in (("blur", os.path.join(CAL, "warp_new", "fit_logistic_calib1.csv")),
                          ("other", os.path.join(CAL, "warp_new", "fit_logistic_calib2.csv"))):
        for r in _rows(path):
            obs = _f(r.get("lambda_observed_full"), 0.0)
            p = {"g": _f(r["gamma"]), "lam": max(_f(r["lambda"]), obs or 0.0),
                 "mu": _f(r["mu"]), "sg": _f(r["sigma"]),
                 "n_trials": _f(r.get("n_trials"), 0), "n_participants": 0}
            if r["modality"] == "audio":
                audio[r["char"]] = p
            else:
                fam = r["family"]
                if (fam_src == "blur") != (fam == "blur"):
                    continue
                visual[r["char"] + "|" + fam] = p
    fits["old"] = {"audio": audio, "visual": visual,
                   "levels": fits["new"]["levels"], "windows": {}}
    return fits


def load_compare():
    rows = []
    for r in _rows(os.path.join(CAL, "warp_v3", "compare_old_new.csv")):
        rows.append({k: (r[k] if k in ("family", "char", "gates_ms") else _f(r[k]))
                     for k in r})
    return rows


# ---------------------------------------------------------------------------
# 6. HTML を書く
# ---------------------------------------------------------------------------
def main():
    print("[1] transfer.js から描画＋再生を切り出す")
    js_slice = slice_transfer_js()
    print(f"    {js_slice.count(chr(10))} 行")

    print("[2] transfer_config.js を JSON に")
    cfg = load_config()

    print("[3] 文字画像を data URI に")
    imgs = load_images()

    print("[4] warp 表を読む")
    tables = load_tables()

    print("[5] 当てはめの数値を読む")
    fits = load_fits()
    compare = load_compare()

    gates = {ch: cfg["audio"]["gates_ms"].get(ch, cfg["audio"]["gates_ms"]["_default"])
             for ch in CHARS}

    data = {
        "chars": CHARS, "fams": FAMS, "gates": gates,
        "images": imgs,
        "tables": {k: {"label": v["label"], "fitset": v["fitset"],
                       "covers_ms": v["covers_ms"], "path": v["path"], "doc": v["doc"]}
                   for k, v in tables.items()},
        "table_order": [k for k, _, _, _ in TABLE_DEFS if k in tables],
        "fits": fits, "compare": compare,
        "L595": L595,
    }

    html = PAGE.replace("/*__DATA__*/", "const DATA = " + json.dumps(
        data, ensure_ascii=False, separators=(",", ":")) + ";")
    html = html.replace("/*__CFG__*/", "const CFG = window.TRANSFER_CONFIG = " + json.dumps(
        cfg, ensure_ascii=False, separators=(",", ":")) + ";")
    html = html.replace("/*__TRANSFER_JS_SLICE__*/", js_slice)

    io.open(OUT, "w", encoding="utf-8").write(html)
    print(f"\n書き出し: {os.path.relpath(OUT, ROOT)}  ({os.path.getsize(OUT)//1024} KB)")
    print("  open experiment/warp_preview.html")


# ===========================================================================
# ページ本体
# ===========================================================================
PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>warp 表プレビュー（群B・研究者用）</title>
<style>
:root{
  --bg:#faf8f4; --fg:#1c1a17; --muted:#6b6560; --accent:#b45309; --line:#ded6c8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c; --card:#ffffff;
  --aud:#1d6fa5; --vis:#b45309; --prop:#b45309; --b1:#6b6560; --b2:#15803d;
  --old:#8a3ea8; --new:#0f766e; --canvasbg:#ffffff;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
    --card:#211e19; --ok:#4ade80; --bad:#f87171;
    --aud:#6fb6e8; --vis:#e8a14c; --prop:#e8a14c; --b1:#a89f92; --b2:#5cc98a;
    --old:#cf95e6; --new:#5ec8bb;
  }
}
:root[data-theme="dark"]{
  --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
  --card:#211e19; --ok:#4ade80; --bad:#f87171;
  --aud:#6fb6e8; --vis:#e8a14c; --prop:#e8a14c; --b1:#a89f92; --b2:#5cc98a;
  --old:#cf95e6; --new:#5ec8bb;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);
  font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  line-height:1.75;max-width:1180px;margin:0 auto;padding:2rem 1.2rem 6rem}
h1{font-size:1.6rem;border-bottom:2px solid var(--accent);padding-bottom:.5rem;line-height:1.4}
h2{font-size:1.22rem;margin-top:3rem;color:var(--accent);
   border-bottom:1px solid var(--line);padding-bottom:.3rem}
h3{font-size:1rem;margin-top:1.8rem}
p{margin:.6rem 0}
.lead{color:var(--muted);font-size:.94rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:.9rem 1.2rem;margin:1rem 0}
.card.note{border-left:5px solid var(--accent)}
.card.alert{border-left:5px solid var(--bad)}
.small{font-size:.83rem;color:var(--muted)}
code{background:color-mix(in srgb,var(--fg) 7%,transparent);padding:.05rem .3rem;
  border-radius:4px;font-size:.88em}
.tbl{border-collapse:collapse;width:100%;font-size:.82rem;margin:.8rem 0}
.tbl th,.tbl td{border:1px solid var(--line);padding:.28rem .5rem;text-align:left}
.tbl th{background:color-mix(in srgb,var(--accent) 12%,var(--card));position:sticky;top:0}
.tbl td.num{text-align:right;font-variant-numeric:tabular-nums}
.tbl tr.hi td{background:color-mix(in srgb,var(--accent) 14%,transparent);font-weight:700}

/* ---- 操作バー ---- */
#bar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 92%,transparent);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
  padding:.55rem .2rem;margin:0 -1.2rem 1.2rem;padding-left:1.2rem;padding-right:1.2rem;
  display:flex;flex-wrap:wrap;gap:.5rem 1.1rem;align-items:center;font-size:.85rem}
#bar label{display:flex;align-items:center;gap:.32rem;white-space:nowrap}
#bar select,#bar button{font:inherit;font-size:.85rem;padding:.15rem .4rem;
  background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px}
#bar button{cursor:pointer}
#bar button:hover{border-color:var(--accent)}
.ttlkey{font-weight:700;color:var(--muted)}

/* ---- 絵の一覧 ---- */
.gridwrap{overflow-x:auto;margin:.8rem 0 1.4rem}
table.frames{border-collapse:separate;border-spacing:0;font-size:.75rem}
table.frames th,table.frames td{padding:.18rem .25rem;vertical-align:top}
table.frames th.chh{text-align:left;font-size:1.5rem;font-weight:700;
  padding-right:.6rem;white-space:nowrap;vertical-align:middle}
table.frames th.gh{color:var(--muted);font-weight:600;text-align:center}
.cell{display:flex;flex-direction:column;align-items:center;gap:.15rem}
.cell canvas{width:96px;height:96px;background:var(--canvasbg);
  border:1px solid var(--line);border-radius:4px;image-rendering:auto}
.cell .cap{font-size:.68rem;color:var(--muted);text-align:center;line-height:1.35;
  font-variant-numeric:tabular-nums}
.cell .cap b{color:var(--fg);font-weight:700}
.rowlbl{font-size:.7rem;color:var(--muted);writing-mode:horizontal-tb}
.tagold{color:var(--old);font-weight:700}
.tagnew{color:var(--new);font-weight:700}
.playbtn{font:inherit;font-size:.72rem;padding:.1rem .45rem;cursor:pointer;
  background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:5px}
.playbtn:hover{border-color:var(--accent)}

/* ---- 図 ---- */
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
svg .panel{fill:none;stroke:var(--line);stroke-width:1}
.legend{font-size:.78rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:.2rem 1rem;
  margin:.3rem 0 .1rem}
.legend i{display:inline-block;width:16px;height:0;border-top:2.5px solid currentColor;
  vertical-align:middle;margin-right:.25rem}
details{margin:.6rem 0}
summary{cursor:pointer;font-size:.88rem;color:var(--accent)}
.warnpill{display:inline-block;background:color-mix(in srgb,var(--bad) 18%,transparent);
  color:var(--bad);border-radius:5px;padding:0 .4rem;font-size:.75rem;font-weight:700}
.okpill{display:inline-block;background:color-mix(in srgb,var(--ok) 18%,transparent);
  color:var(--ok);border-radius:5px;padding:0 .4rem;font-size:.75rem;font-weight:700}
</style>
</head>
<body>

<h1>warp 表プレビュー ― 群Bのアニメーションが実際にどう見えるか</h1>
<p class="lead">研究者用。参加者には配らない（<code>build_hosting.sh</code> の公開一覧には入れていない）。
描画は <code>experiment/transfer.js</code> の本文をそのまま切り出して動かしているので、
ここに出る絵は<strong>参加者が見るものと同じ</strong>。</p>

<div class="card note">
<h3 style="margin-top:.2rem">このページの主眼：聴覚と視覚の正答率を合わせること</h3>
<p>転写（proposed）とは、<strong>音を途中まで聞いたときの正答率</strong>を、
文字アニメーションが<strong>同じ時刻に同じ正答率</strong>になるように進み具合を決めることである。</p>
<p style="text-align:center;font-size:.95rem;margin:.8rem 0">
<code>時刻 t</code> →〔聴覚の曲線〕→ <code>目標の正答率 q</code>
→〔視覚の較正曲線を逆に引く〕→ <code>進み具合 s</code> →〔描画〕→ <code>絵</code></p>
<p class="small">当てはめの式は聴覚も視覚も同じ形：
<code>P(x) = γ + (λ−γ)·logistic((x−μ)/σ)</code>。
聴覚は x = 打ち切り時刻 ms、視覚は x = 進み具合 %。
γ は当てずっぽう（1/72 など）、λ は「最後まで見せたときの天井」。</p>
<p class="small"><strong>進み具合は 100% まで行かない。</strong> 目標は「音と同じ正答率」であって
「字を完成させること」ではないので、最後の絵が完成形でなくてよい。
「が」のように<strong>聴覚の曲線がほとんど動かない字は、文字もほとんど動かないのが正しい転写</strong>である。</p>
</div>

<div id="bar">
  <label><span class="ttlkey">表</span><select id="selTable"></select></label>
  <label><span class="ttlkey">条件</span><select id="selCond">
    <option value="proposed">転写 proposed</option>
    <option value="baseline1">等速 baseline1</option>
    <option value="baseline2">一次変換 baseline2</option>
  </select></label>
  <label><span class="ttlkey">方式</span><select id="selFam"></select></label>
  <label><span class="ttlkey">端からの向き</span><select id="selDir">
    <option value="ltr">左→右 ltr</option><option value="rtl">右→左 rtl</option>
    <option value="ttb">上→下 ttb</option><option value="btt">下→上 btt</option>
  </select></label>
  <label><input type="checkbox" id="chkCmp"> 現行と新を並べる</label>
  <label><input type="checkbox" id="chkAllFam"> 8方式ぜんぶ出す</label>
  <label><input type="checkbox" id="chkLog" checked> 振り分けの縦軸を対数に</label>
  <button id="btnPlayAll">全部再生（300ms）</button>
  <span id="filterWarn"></span>
</div>

<div id="warnbox"></div>

<!-- ================= §1 絵の一覧 ================= -->
<h2>1. 打ち切り時刻ごとの絵</h2>
<p class="small">横は<strong>聴覚の打ち切り時刻7点</strong>（<code>transfer_config.js</code> の
<code>audio.gates_ms</code> の字ごとの値）。その時刻に群Bの画面に出ている絵をそのまま描いている。
絵の下は「時刻 → 進み具合 s」。組み合わせは s の内訳（一様側 × 空間側）も出す。
<span class="okpill">再生</span>を押すと実時間 300ms のアニメーションになる。</p>
<div id="frames"></div>

<!-- ================= §2 手法の図 ================= -->
<h2>2. 手法の図 ― 音のグラフ → 逆引き → 進み具合 → 絵</h2>
<p class="small">1字につき1枚。左が<strong>聴覚の曲線（これが目標）</strong>、右が<strong>視覚の較正曲線</strong>、
下が<strong>できあがった s(t)</strong>。点線が逆引き：打ち切り時刻から縦に上げて聴覚の曲線に当て、
そのまま<strong>横に引いて</strong>視覚の曲線に当て、<strong>縦に落として</strong>進み具合を読む。
7つの打ち切り時刻を色分けしてある（早い＝薄い / 遅い＝濃い）。</p>
<div id="figs"></div>

<!-- ================= §3 組み合わせの振り分け ================= -->
<h2 id="h-split">3. 組み合わせの振り分け ― 現行（8字平均のべき乗）と 新（字ごとの窓・線形）</h2>
<p class="small">組み合わせは、全体の進み具合 u を <strong>一様側 s<sub>a</sub>（うすい／点が増える）</strong>と
<strong>空間側 s<sub>b</sub>（ぼやけ／端から）</strong>に振り分ける。
現行は <code>s = 100·u^k</code>（k は8字平均の中点に合わせた1つの値 ＝ <strong>字によらず同じ</strong>）。
新は字ごとの窓 <code>[s5, s95] = [μ−2.944σ, μ+2.944σ]</code>（実測水準の範囲に丸め）へ線形（または対数線形）に写す。</p>
<div id="checkfull"></div>
<div id="splits"></div>

<!-- ================= §4 現行 vs 新 の可動域 ================= -->
<h2>4. 現行 vs 新 ― 提示時間内に進み具合がどれだけ動くか</h2>
<p class="small">「可動域」＝ 7つの打ち切り時刻のあいだで進み具合が動く幅（ポイント）。
「点数」＝ 7点のうち<strong>別の絵になっている点の数</strong>（1 なら全部同じ絵＝測定不能）。
出どころ <code>project/data_calib2_live/warp_v3/compare_old_new.csv</code>。</p>
<div id="cmptbl"></div>

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

// ---------------------------------------------------------------------------
// 下ごしらえ
// ---------------------------------------------------------------------------
const LAB = {fade:"うすい", reveal:"点が増える", blur:"ぼやけ", wipe:"端から"};
const famLabel = f => f.split("+").map(x => LAB[x] || x).join(" × ");
const CONDLAB = {proposed:"転写", baseline1:"等速", baseline2:"一次変換"};
const GATE_COLORS = ["#c9d7e6","#a9c2da","#87abcf","#6494c3","#3f7cb6","#2864a0","#134b80"];
const GATE_COLORS_D = ["#3a4a5c","#4c6379","#5e7c96","#7295b2","#88afce","#a2c8e4","#c2e0f5"];
function gateColor(i){ return isDark() ? GATE_COLORS_D[i] : GATE_COLORS[i]; }
function isDark(){
  const t = document.documentElement.getAttribute("data-theme");
  if (t) return t === "dark";
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

// 画像は data URI から。ふつうのパス参照だと file:// で canvas が汚染され、
// reveal / wipe の getImageData が例外になる。
let imgsReady = false;
function loadAll(){
  return Promise.all(DATA.chars.map(ch => new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => { imgs[ch] = im; res(); };
    im.onerror = () => rej(new Error(ch));
    im.src = DATA.images[ch];
  }))).then(() => { imgsReady = true; });
}

// ---- 曲線の式（build_warp_b3.py の logi / qof / invert と同じ） ----
function logi(x, p){
  let z = -(x - p.mu) / Math.max(p.sg, 1e-9);
  z = Math.max(-60, Math.min(60, z));
  return p.g + (p.lam - p.g) / (1 + Math.exp(z));
}
function qof(p, s){
  const y = logi(s, p), d = p.lam - p.g;
  return d <= 0 ? 0 : Math.max(0, Math.min(1, (y - p.g) / d));
}
function invert(pv, y){
  if (pv.lam <= pv.g || y <= pv.g) return {s:0, clip:"low"};
  if (y >= pv.lam) return {s:100, clip:"high"};
  const s = pv.mu + pv.sg * Math.log((y - pv.g) / (pv.lam - y));
  if (s < 0) return {s:0, clip:"low"};
  if (s > 100) return {s:100, clip:"high"};
  return {s:s, clip:null};
}

// ---- いま選ばれているもの ----
const ui = {table:null, cond:"proposed", fam:"fade", dir:"ltr", cmp:false, allfam:false,
            logsplit:true};

function tableOf(key){ return DATA.tables[key]; }
function fitsetOf(key){ return DATA.tables[key].fitset; }
function fitAudio(key, ch){ return DATA.fits[fitsetOf(key)].audio[ch]; }
function fitVisual(key, ch, fam){ return DATA.fits[fitsetOf(key)].visual[ch + "|" + fam]; }
function mappingOf(key){ return key.indexOf("log") >= 0 ? "loglinear" : "linear"; }
function windowOf(key, pair, fam, ch){
  const W = DATA.fits[fitsetOf(key)].windows;
  return W[mappingOf(key) + "|" + pair + "|" + fam + "|" + ch] || null;
}
function levelsOf(key, fam){ return DATA.fits[fitsetOf(key)].levels[fam] || [0,100]; }
// 「現行と新を並べる」で見せる2つの表。いつも 現行 → 新 の順。
function otherKey(){
  return (ui.table === "current")
    ? (DATA.table_order.find(k => k !== "current") || ui.table) : "current";
}
function cmpKeys(){
  const nw = (ui.table === "current")
    ? (DATA.table_order.find(k => k !== "current") || ui.table) : ui.table;
  return (nw === "current") ? ["current"] : ["current", nw];
}

// 表を transfer.js の再生部へ差し込んで s(t) を得る。
function progressFor(key, fam, ch, cond){
  warpTables = tableOf(key).doc;
  return progressFn({play:"warp", family:fam, char:ch, condition:cond});
}
// 組み合わせの内訳（transfer.js の compositeSplit をそのまま呼ぶ）
function splitFor(key, fam, ch, s){
  warpTables = tableOf(key).doc;
  return compositeSplit(fam, ch, s);
}

// ---------------------------------------------------------------------------
// §1 絵の一覧
// ---------------------------------------------------------------------------
function drawCell(cv, key, fam, ch, cond, ms){
  warpTables = tableOf(key).doc;
  const ctx = cv.getContext("2d", {willReadFrequently:true});
  const R = RENDERERS[fam] || RENDERERS.fade;
  const {fn} = progressFn({play:"warp", family:fam, char:ch, condition:cond});
  R.begin(ch, ctx);
  R.draw(ctx, ch, fn(ms), ui.dir);
  return fn(ms);
}

function capFor(key, fam, ch, cond, ms, s){
  let extra = "";
  if (fam.indexOf("+") >= 0){
    const sp = splitFor(key, fam, ch, s);
    const parts = fam.split("+");
    extra = "<br>" + LAB[parts[0]] + " " + (sp.sa*100).toFixed(1) + "%<br>"
          + LAB[parts[1]] + " " + (sp.sb*100).toFixed(1) + "%";
  }
  return "t=" + ms + "ms<br><b>s=" + (s*100).toFixed(1) + "%</b>" + extra;
}

function buildFrames(){
  const host = document.getElementById("frames");
  host.innerHTML = "";
  const fams = ui.allfam ? DATA.fams : [ui.fam];
  const uniq = ui.cmp ? cmpKeys() : [ui.table];

  fams.forEach(fam => {
    const wrap = document.createElement("div");
    wrap.className = "gridwrap";
    const h = document.createElement("h3");
    h.textContent = famLabel(fam) + " ／ " + CONDLAB[ui.cond];
    host.appendChild(h);
    const t = document.createElement("table");
    t.className = "frames";
    // 見出し行：字ごとに時刻が違うので「n 番目の打ち切り」で並べる
    let head = "<tr><th></th>" + (uniq.length > 1 ? "<th></th>" : "");
    for (let i = 0; i < 7; i++) head += '<th class="gh">打ち切り ' + (i+1) + '</th>';
    head += '<th class="gh">再生</th></tr>';
    t.innerHTML = head;
    DATA.chars.forEach(ch => {
      const g = DATA.gates[ch];
      uniq.forEach((key, ki) => {
        const tr = document.createElement("tr");
        let cells = "";
        if (ki === 0){
          cells += '<th class="chh" rowspan="' + uniq.length + '">' + ch
                 + (uniq.length > 1 ? "" : "") + '</th>';
        }
        tr.innerHTML = cells;
        if (uniq.length > 1){
          const lab = document.createElement("td");
          lab.className = "rowlbl";
          lab.innerHTML = '<span class="' + (key === "current" ? "tagold" : "tagnew") + '">'
                        + (key === "current" ? "現行" : "新") + '</span>';
          // 先頭列のあとに差し込む
          tr.appendChild(lab);
        }
        g.forEach((ms, gi) => {
          const td = document.createElement("td");
          const box = document.createElement("div"); box.className = "cell";
          const cv = document.createElement("canvas");
          cv.width = CFG.visual.size_px; cv.height = CFG.visual.size_px;
          box.appendChild(cv);
          const cap = document.createElement("div"); cap.className = "cap";
          box.appendChild(cap);
          td.appendChild(box); tr.appendChild(td);
          const s = drawCell(cv, key, fam, ch, ui.cond, ms);
          cap.innerHTML = capFor(key, fam, ch, ui.cond, ms, s);
          cap.style.borderTop = "2px solid " + gateColor(gi);
        });
        const tdp = document.createElement("td");
        const b = document.createElement("button");
        b.className = "playbtn"; b.textContent = "▶";
        b.onclick = () => playRow(tr, key, fam, ch);
        tdp.appendChild(b); tr.appendChild(tdp);
        t.appendChild(tr);
      });
    });
    wrap.appendChild(t);
    host.appendChild(wrap);
  });
}

// 実時間 300ms の再生。行の先頭の canvas を使って動かし、終わったら元の絵に戻す。
let playing = false;
function playRow(tr, key, fam, ch){
  if (playing) return;
  const cvs = Array.from(tr.querySelectorAll("canvas"));
  if (!cvs.length) return;
  playing = true;
  warpTables = tableOf(key).doc;
  const R = RENDERERS[fam] || RENDERERS.fade;
  const {fn} = progressFn({play:"warp", family:fam, char:ch, condition:ui.cond});
  const ctxs = cvs.map(c => c.getContext("2d", {willReadFrequently:true}));
  ctxs.forEach(c => R.begin(ch, c));
  const t0 = performance.now();
  const dur = CFG.visual.base_anim_ms;
  // 逃げ道: タブが裏に回ると requestAnimationFrame が来ない。
  // そのまま playing が立ちっぱなしになると二度と再生できなくなるので、時間でも解く。
  const guard = setTimeout(() => {
    if (!playing) return;
    playing = false; redrawRow(tr, key, fam, ch);
  }, dur + 2000);
  function step(now){
    const el = now - t0;
    const s = fn(Math.min(el, dur));
    ctxs.forEach(c => { R.begin(ch, c); R.draw(c, ch, s, ui.dir); });
    if (el < dur) requestAnimationFrame(step);
    else { playing = false; clearTimeout(guard);
           setTimeout(() => redrawRow(tr, key, fam, ch), 400); }
  }
  requestAnimationFrame(step);
}
function redrawRow(tr, key, fam, ch){
  const cvs = Array.from(tr.querySelectorAll("canvas"));
  const g = DATA.gates[ch];
  cvs.forEach((cv, i) => { if (i < g.length) drawCell(cv, key, fam, ch, ui.cond, g[i]); });
}
function playAll(){
  if (playing) return;
  const rows = Array.from(document.querySelectorAll("#frames tr")).filter(r => r.querySelector("canvas"));
  let i = 0;
  const next = () => {
    if (i >= rows.length) return;
    const r = rows[i++];
    const b = r.querySelector(".playbtn");
    if (b) b.click();
    setTimeout(next, CFG.visual.base_anim_ms + 260);
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
function niceMax(v){
  if (v <= 0) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / e;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * e;
}
function fmtPct(v){ return v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2); }

// ---------------------------------------------------------------------------
// §2 手法の図
// ---------------------------------------------------------------------------
const FIG_W = 1080, FIG_H = 500;
const PA = {x:56, y:40, w:330, h:200};      // 聴覚
const PB = {x:600, y:40, w:400, h:200};     // 視覚
const PC = {x:56, y:310, w:944, h:150};     // s(t)

// 組み合わせのときの「有効な視覚曲線」P(u)。build_warp_b3.py の build() と同じ式。
function compositeCurve(key, fam, ch){
  const parts = fam.split("+");
  const pva = fitVisual(key, ch, parts[0]), pvb = fitVisual(key, ch, parts[1]);
  if (!pva || !pvb) return null;
  const lam = Math.min(pva.lam, pvb.lam);
  return function(u){          // u は 0〜100
    const sp = splitFor(key, fam, ch, u / 100);
    return pva.g + (lam - pva.g) * qof(pva, sp.sa * 100) * qof(pvb, sp.sb * 100);
  };
}

function makeFigure(ch){
  const key = ui.table, fam = ui.fam, isComp = fam.indexOf("+") >= 0;
  const g = DATA.gates[ch];
  const pa = fitAudio(key, ch);
  const other = otherKey();
  const svg = el("svg", {class:"fig", viewBox:"0 0 " + FIG_W + " " + FIG_H,
                         width:FIG_W, height:FIG_H});

  // ---- 軸の範囲 ----
  const tMax = Math.max(300, g[g.length-1] * 1.1);
  const {fn:fProp} = progressFor(key, fam, ch, "proposed");
  const {fn:fB1} = progressFor(key, fam, ch, "baseline1");
  const {fn:fB2} = progressFor(key, fam, ch, "baseline2");
  let sHi = 0;
  for (let t = 0; t <= 300; t += 5) sHi = Math.max(sHi, fProp(t)*100, fB2(t)*100);
  const pv = isComp ? null : fitVisual(key, ch, fam);
  if (pv) sHi = Math.max(sHi, pv.s95 != null && isFinite(pv.s95) ? pv.s95 : pv.mu + 3*pv.sg);
  let sMax = isComp ? 100 : Math.min(100, niceMax(sHi * 1.25));
  if (!(sMax > 0)) sMax = 100;

  const ax = t => PA.x + PA.w * Math.min(1, t / tMax);
  const ay = q => PA.y + PA.h * (1 - Math.max(0, Math.min(1, q)));
  const bx = s => PB.x + PB.w * Math.min(1, Math.max(0, s) / sMax);
  const by = q => PB.y + PB.h * (1 - Math.max(0, Math.min(1, q)));
  const cx = t => PC.x + PC.w * Math.min(1, t / 300);
  const cy = s => PC.y + PC.h * (1 - Math.max(0, Math.min(1, s / sMax)));

  // ---- 枠と軸 ----
  function frame(p, title, xlab, ylab){
    svg.appendChild(el("rect", {x:p.x, y:p.y, width:p.w, height:p.h, class:"panel"}));
    svg.appendChild(el("text", {x:p.x, y:p.y-12, class:"ttl"}, title));
    svg.appendChild(el("text", {x:p.x+p.w, y:p.y+p.h+30, class:"lbl", "text-anchor":"end"}, xlab));
    const yl = el("text", {x:p.x-40, y:p.y+p.h/2, class:"lbl", "text-anchor":"middle",
                           transform:"rotate(-90 " + (p.x-40) + " " + (p.y+p.h/2) + ")"}, ylab);
    svg.appendChild(yl);
  }
  frame(PA, "① 聴覚の曲線（目標）", "打ち切り時刻 t (ms)", "正答率");
  frame(PB, isComp ? "② 視覚の較正曲線（組み合わせの合成）" : "② 視覚の較正曲線",
        isComp ? "全体の進み具合 u (%)" : "進み具合 s (%)", "正答率");
  frame(PC, "④ できあがった s(t)", "時刻 t (ms)", "進み具合 s (%)");

  // 正答率の目盛（①②共通）
  [0, .25, .5, .75, 1].forEach(q => {
    [[PA, ax, ay], [PB, bx, by]].forEach(([p, fx, fy]) => {
      svg.appendChild(el("line", {x1:p.x, y1:fy(q), x2:p.x+p.w, y2:fy(q), class:"grid"}));
    });
    svg.appendChild(el("text", {x:PA.x-6, y:ay(q)+3.5, class:"tiny", "text-anchor":"end"},
                       (q*100).toFixed(0) + "%"));
    svg.appendChild(el("text", {x:PB.x-6, y:by(q)+3.5, class:"tiny", "text-anchor":"end"},
                       (q*100).toFixed(0) + "%"));
  });
  // x 目盛
  [0, tMax].forEach((t, i) => {
    svg.appendChild(el("text", {x:ax(t), y:PA.y+PA.h+14, class:"tiny",
      "text-anchor": i ? "end" : "start"}, t.toFixed(0)));
  });
  [0, sMax/2, sMax].forEach((v, i) => {
    svg.appendChild(el("text", {x:bx(v), y:PB.y+PB.h+14, class:"tiny",
      "text-anchor": i === 0 ? "start" : i === 2 ? "end" : "middle"}, fmtPct(v)));
  });
  for (let i = 0; i <= 6; i++){
    const t = 50 * i;
    svg.appendChild(el("line", {x1:cx(t), y1:PC.y, x2:cx(t), y2:PC.y+PC.h, class:"grid"}));
    svg.appendChild(el("text", {x:cx(t), y:PC.y+PC.h+14, class:"tiny", "text-anchor":"middle"}, t));
  }
  for (let i = 0; i <= 2; i++){
    const s = sMax * i / 2;
    svg.appendChild(el("line", {x1:PC.x, y1:cy(s), x2:PC.x+PC.w, y2:cy(s), class:"grid"}));
    svg.appendChild(el("text", {x:PC.x-6, y:cy(s)+3.5, class:"tiny", "text-anchor":"end"}, fmtPct(s)));
  }

  // ---- ① 聴覚の曲線 ----
  let d = "";
  for (let i = 0; i <= 200; i++){
    const t = tMax * i / 200;
    d += (i ? "L" : "M") + ax(t).toFixed(1) + " " + ay(logi(t, pa)).toFixed(1);
  }
  svg.appendChild(el("path", {d:d, fill:"none", stroke:"var(--aud)", "stroke-width":2.4}));
  svg.appendChild(el("text", {x:PA.x+PA.w-4, y:PA.y+14, class:"tiny", "text-anchor":"end",
                              fill:"var(--aud)"},
    "μ=" + pa.mu.toFixed(1) + "ms σ=" + pa.sg.toFixed(2) + " λ=" + pa.lam.toFixed(2)));

  // ---- ② 視覚の曲線 ----
  const vcurve = isComp ? compositeCurve(key, fam, ch)
                        : (s => pv ? logi(s, pv) : 0);
  if (vcurve){
    let dv = "";
    for (let i = 0; i <= 240; i++){
      const s = sMax * i / 240;
      dv += (i ? "L" : "M") + bx(s).toFixed(1) + " " + by(vcurve(s)).toFixed(1);
    }
    svg.appendChild(el("path", {d:dv, fill:"none", stroke:"var(--vis)", "stroke-width":2.4}));
  }
  if (pv) svg.appendChild(el("text", {x:PB.x+PB.w-4, y:PB.y+14, class:"tiny",
      "text-anchor":"end", fill:"var(--vis)"},
      "μ=" + pv.mu.toFixed(2) + "% σ=" + pv.sg.toFixed(2) + " λ=" + pv.lam.toFixed(2)));

  // 比べる表の視覚曲線（薄い破線）
  if (ui.cmp && other && !isComp){
    const pv2 = fitVisual(other, ch, fam);
    if (pv2){
      let dv = "";
      for (let i = 0; i <= 240; i++){
        const s = sMax * i / 240;
        dv += (i ? "L" : "M") + bx(s).toFixed(1) + " " + by(logi(s, pv2)).toFixed(1);
      }
      svg.appendChild(el("path", {d:dv, fill:"none",
        stroke: (other === "current" ? "var(--old)" : "var(--new)"),
        "stroke-width":1.6, "stroke-dasharray":"5 4", opacity:.85}));
    }
  }

  // ---- ③ 逆引きの矢印 ----
  // ラベルは近すぎると重なって読めなくなるので、前に置いた位置から
  // 一定の間があいたときだけ書く（表は図の下に別に出す）。
  const lastLab = {a:-1e9, b:-1e9};
  function labelIf(side, x, y, txt, col){
    if (x - lastLab[side] < 17) return;
    lastLab[side] = x;
    svg.appendChild(el("text", {x:x, y:y, class:"tiny", "text-anchor":"middle", fill:col}, txt));
  }
  g.forEach((t, gi) => {
    const col = gateColor(gi);
    const q = logi(t, pa);
    const s = fProp(t) * 100;              // 表から読んだ実際の進み具合
    // t から上へ
    svg.appendChild(el("line", {x1:ax(t), y1:PA.y+PA.h, x2:ax(t), y2:ay(q),
      stroke:col, "stroke-width":1.4, "stroke-dasharray":"3 3"}));
    svg.appendChild(el("circle", {cx:ax(t), cy:ay(q), r:3.2, fill:col}));
    labelIf("a", ax(t), PA.y+PA.h+27, String(t), col);
    // 横へ（パネルをまたぐ）
    svg.appendChild(el("line", {x1:ax(t), y1:ay(q), x2:bx(s), y2:by(q),
      stroke:col, "stroke-width":1.2, "stroke-dasharray":"3 3", opacity:.75}));
    // 下へ
    svg.appendChild(el("circle", {cx:bx(s), cy:by(q), r:3.2, fill:col}));
    svg.appendChild(el("line", {x1:bx(s), y1:by(q), x2:bx(s), y2:PB.y+PB.h,
      stroke:col, "stroke-width":1.4, "stroke-dasharray":"3 3"}));
    labelIf("b", bx(s), PB.y+PB.h+27, fmtPct(s), col);
    // ④ に印
    svg.appendChild(el("circle", {cx:cx(t), cy:cy(s), r:3.4, fill:col,
      stroke:"var(--card)", "stroke-width":1}));
  });
  // 矢印の向きの合図
  svg.appendChild(el("text", {x:(PA.x+PA.w+PB.x)/2, y:PA.y-12, class:"tiny",
    "text-anchor":"middle"}, "③ 横に引いて → 縦に落とす"));

  // ---- ④ s(t) の3本 ----
  const lines = [["proposed", fProp, "var(--prop)", 2.6, ""],
                 ["baseline1", fB1, "var(--b1)", 1.6, "6 4"],
                 ["baseline2", fB2, "var(--b2)", 1.8, "2 3"]];
  lines.forEach(([nm, fn, col, w, dash]) => {
    let dd = "";
    for (let i = 0; i <= 300; i += 2){
      dd += (i ? "L" : "M") + cx(i).toFixed(1) + " " + cy(fn(i)*100).toFixed(1);
    }
    const p = el("path", {d:dd, fill:"none", stroke:col, "stroke-width":w});
    if (dash) p.setAttribute("stroke-dasharray", dash);
    svg.appendChild(p);
  });
  // 比べる表の proposed
  if (ui.cmp && other){
    const {fn} = progressFor(other, fam, ch, "proposed");
    let dd = "";
    for (let i = 0; i <= 300; i += 2) dd += (i ? "L" : "M") + cx(i).toFixed(1) + " " + cy(fn(i)*100).toFixed(1);
    svg.appendChild(el("path", {d:dd, fill:"none",
      stroke:(other === "current" ? "var(--old)" : "var(--new)"),
      "stroke-width":2, "stroke-dasharray":"7 4", opacity:.9}));
  }
  // 打ち切り時刻の縦線
  g.forEach((t, gi) => {
    svg.appendChild(el("line", {x1:cx(t), y1:PC.y, x2:cx(t), y2:PC.y+PC.h,
      stroke:gateColor(gi), "stroke-width":1, opacity:.55}));
  });
  return svg;
}

function buildFigs(){
  const host = document.getElementById("figs");
  host.innerHTML = "";
  const key = ui.table, fam = ui.fam;
  const other = otherKey();
  const leg = document.createElement("div");
  leg.className = "legend";
  leg.innerHTML =
    '<span style="color:var(--aud)"><i></i>聴覚の曲線</span>' +
    '<span style="color:var(--vis)"><i></i>視覚の較正曲線</span>' +
    '<span style="color:var(--prop)"><i></i>s(t) 転写</span>' +
    '<span style="color:var(--b1)"><i></i>s(t) 等速</span>' +
    '<span style="color:var(--b2)"><i></i>s(t) 一次変換</span>' +
    (ui.cmp ? '<span style="color:' + (other === "current" ? "var(--old)" : "var(--new)") +
              '"><i></i>' + (other === "current" ? "現行" : "新") + 'の曲線 / s(t)（破線）</span>' : "");
  host.appendChild(leg);
  DATA.chars.forEach(ch => {
    const fig = document.createElement("figure");
    const w = document.createElement("div"); w.className = "figwrap";
    w.appendChild(makeFigure(ch));
    fig.appendChild(w);
    const cap = document.createElement("figcaption");
    const a = spanU(ui.table, fam, ch, ui.cond);
    cap.innerHTML = "<b>" + ch + "</b>（" + famLabel(fam) + "／" + tableOf(ui.table).label
      + "／" + CONDLAB[ui.cond] + "）"
      + " 打ち切り7点での進み具合 " + fmtPct(a.lo) + "% 〜 " + fmtPct(a.hi)
      + "%（可動域 " + a.span.toFixed(2) + "pt・別の絵になる点は " + a.n + " / 7）"
      + (a.n <= 1 ? ' <span class="warnpill">全部同じ絵＝測定不能</span>'
                  : (a.span < 1 ? ' <span class="warnpill">可動域 1pt 未満</span>' : ""))
      + (ui.cmp ? (function(){ const b = spanU(otherKey(), fam, ch, ui.cond);
          return ' ／ <span class="' + (otherKey()==="current"?"tagold":"tagnew") + '">'
            + (otherKey()==="current"?"現行":"新") + " は " + b.span.toFixed(2)
            + "pt・" + b.n + "/7</span>"; })() : "");
    fig.appendChild(cap);
    fig.appendChild(gateTable(ch));
    host.appendChild(fig);
  });
}

// 図の下に置く、打ち切り7点ぶんの数値。「なぜこの絵になるのか」を数で追えるように。
function gateTable(ch){
  const key = ui.table, fam = ui.fam, isComp = fam.indexOf("+") >= 0;
  const g = DATA.gates[ch];
  const pa = fitAudio(key, ch);
  const pv = isComp ? null : fitVisual(key, ch, fam);
  const vc = isComp ? compositeCurve(key, fam, ch) : null;
  const {fn} = progressFor(key, fam, ch, ui.cond);
  const cmpFn = ui.cmp ? progressFor(otherKey(), fam, ch, ui.cond).fn : null;
  const parts = fam.split("+");
  const d = document.createElement("div");
  d.className = "gridwrap";
  let h = '<table class="tbl" style="max-width:900px"><thead><tr>'
    + '<th>打ち切り t (ms)</th>' + g.map(t => '<th class="num">' + t + '</th>').join("")
    + '</tr></thead><tbody>';
  h += '<tr><td>① 聴覚の目標 q</td>'
     + g.map(t => '<td class="num">' + (logi(t, pa)*100).toFixed(1) + '%</td>').join("") + '</tr>';
  h += '<tr><td>④ ' + (isComp ? "全体の進み具合 u" : "進み具合 s") + '</td>'
     + g.map(t => '<td class="num"><b>' + fmtPct(fn(t)*100) + '%</b></td>').join("") + '</tr>';
  if (isComp){
    [["a", parts[0]], ["b", parts[1]]].forEach(([side, f]) => {
      h += '<tr><td>　└ ' + LAB[f] + '</td>'
         + g.map(t => { const sp = splitFor(key, fam, ch, fn(t));
             return '<td class="num">' + fmtPct((side === "a" ? sp.sa : sp.sb)*100) + '%</td>'; }).join("")
         + '</tr>';
    });
  }
  h += '<tr><td>その進み具合で出る正答率</td>'
     + g.map(t => { const v = isComp ? vc(fn(t)*100) : logi(fn(t)*100, pv);
         return '<td class="num">' + (v*100).toFixed(1) + '%</td>'; }).join("") + '</tr>';
  if (cmpFn){
    h += '<tr><td class="' + (otherKey()==="current"?"tagold":"tagnew") + '">'
       + (otherKey()==="current"?"現行":"新") + 'の進み具合</td>'
       + g.map(t => '<td class="num">' + fmtPct(cmpFn(t)*100) + '%</td>').join("") + '</tr>';
  }
  h += '</tbody></table>';
  d.innerHTML = h;
  return d;
}

// ---------------------------------------------------------------------------
// §3 組み合わせの振り分け（現行 vs 新）
// ---------------------------------------------------------------------------
const SP_W = 1000, SP_H = 250;
function makeSplitFig(ch){
  const fam = ui.fam, parts = fam.split("+");
  const svg = el("svg", {class:"fig", viewBox:"0 0 " + SP_W + " " + SP_H,
                         width:SP_W, height:SP_H});
  const panels = [{x:60, y:30, w:400, h:170, fam:parts[0], side:"a", ttl:"一様側 " + LAB[parts[0]]},
                  {x:560, y:30, w:400, h:170, fam:parts[1], side:"b", ttl:"空間側 " + LAB[parts[1]]}];
  const newKey = DATA.table_order.find(k => k !== "current") || "v3_lin";
  const showKey = (ui.table === "current") ? newKey : ui.table;
  const useLog = ui.logsplit;
  const FLOOR = 0.05, LO = Math.log10(FLOOR), SPAN = 2 - LO;
  panels.forEach(p => {
    // 縦軸。現行（u^k で 100% まで伸びる）と 新（字ごとの窓。字によっては 1% 前後）は
    // けた違いに離れるので、既定では**対数目盛**にして両方見えるようにする。
    let hi = 0;
    for (let i = 0; i <= 100; i += 2){
      const so = splitFor("current", fam, ch, i/100), sn = splitFor(showKey, fam, ch, i/100);
      hi = Math.max(hi, (p.side === "a" ? so.sa : so.sb)*100, (p.side === "a" ? sn.sa : sn.sb)*100);
    }
    const yMax = Math.min(100, Math.max(1, niceMax(hi * 1.1)));
    const X = u => p.x + p.w * u / 100;
    const Y = useLog
      ? (s => p.y + p.h * (1 - Math.min(1, Math.max(0,
            (Math.log10(Math.max(s, FLOOR)) - LO) / SPAN))))
      : (s => p.y + p.h * (1 - Math.min(1, Math.max(0, s / yMax))));
    svg.appendChild(el("rect", {x:p.x, y:p.y, width:p.w, height:p.h, class:"panel"}));
    svg.appendChild(el("text", {x:p.x, y:p.y-10, class:"ttl"}, p.ttl));
    svg.appendChild(el("text", {x:p.x+p.w, y:p.y+p.h+28, class:"lbl", "text-anchor":"end"},
                       "全体の進み具合 u (%)"));
    svg.appendChild(el("text", {x:p.x-46, y:p.y+p.h/2, class:"lbl", "text-anchor":"middle",
      transform:"rotate(-90 " + (p.x-46) + " " + (p.y+p.h/2) + ")"},
      "この方式の進み具合 (%)" + (useLog ? "・対数目盛" : "")));
    const yticks = useLog ? [0.1, 1, 10, 100] : [0, yMax/2, yMax];
    yticks.forEach(v => {
      svg.appendChild(el("line", {x1:p.x, y1:Y(v), x2:p.x+p.w, y2:Y(v), class:"grid"}));
      svg.appendChild(el("text", {x:p.x-6, y:Y(v)+3.5, class:"tiny", "text-anchor":"end"},
                         (v < 1 ? v.toFixed(1) : v.toFixed(0)) + "%"));
    });
    for (let i = 0; i <= 4; i++){
      const u = 25*i;
      svg.appendChild(el("text", {x:X(u), y:p.y+p.h+14, class:"tiny", "text-anchor":"middle"}, u));
    }
    // 現行（8字平均のべき乗）と 新（字ごとの窓）
    [["current", "var(--old)", "5 4"], [showKey, "var(--new)", ""]].forEach(([k, col, dash]) => {
      let d = "";
      for (let i = 0; i <= 100; i++){
        const sp = splitFor(k, fam, ch, i/100);
        const v = (p.side === "a" ? sp.sa : sp.sb) * 100;
        d += (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1);
      }
      const path = el("path", {d:d, fill:"none", stroke:col, "stroke-width":2.3});
      if (dash) path.setAttribute("stroke-dasharray", dash);
      svg.appendChild(path);
    });
    // 新の窓 [s5, s95]
    const w = windowOf(showKey, fam, p.fam, ch);
    if (w){
      [["s5", w.s5], ["s95", w.s95]].forEach(([nm, v]) => {
        if (!useLog && v > yMax) return;
        svg.appendChild(el("line", {x1:p.x, y1:Y(v), x2:p.x+p.w, y2:Y(v),
          stroke:"var(--new)", "stroke-width":1, "stroke-dasharray":"2 4", opacity:.7}));
        svg.appendChild(el("text", {x:p.x+p.w-2, y:Y(v)-3, class:"tiny",
          "text-anchor":"end", fill:"var(--new)"}, nm + "=" + fmtPct(v) + "%"));
      });
    }
    // その表で実際に使われる u の範囲（打ち切り7点）
    const g = DATA.gates[ch];
    [["current", "var(--old)"], [showKey, "var(--new)"]].forEach(([k, col]) => {
      const {fn} = progressFor(k, fam, ch, "proposed");
      g.forEach((t, gi) => {
        const u = fn(t)*100;
        const sp = splitFor(k, fam, ch, u/100);
        const v = (p.side === "a" ? sp.sa : sp.sb) * 100;
        svg.appendChild(el("circle", {cx:X(u), cy:Y(v), r:3, fill:col, opacity:.9}));
      });
    });
  });
  return svg;
}

// 確認問題A（全部見せ）は transfer.js が **s=1 を直接描く**
//   （present の中の `renderer.draw(ctx, t.char, 1, t.wipe_dir)`）。
// 組み合わせでは s=1 が composite_map の終端に写るので、
// 「字ごとの窓」だと**終端が s95 止まり＝字が完成しない**。ここを目で確かめる。
function buildCheckFull(){
  const host = document.getElementById("checkfull");
  host.innerHTML = "";
  if (ui.fam.indexOf("+") < 0) return;
  const newKey = (ui.table === "current")
    ? (DATA.table_order.find(k => k !== "current") || "v3_lin") : ui.table;
  const keys = ["current", newKey];
  const d = document.createElement("div");
  d.className = "card alert";
  let h = '<h3 style="margin-top:.2rem">確認問題A（全部見せ）で出る絵</h3>'
    + '<p class="small">transfer.js は確認問題Aで <code>renderer.draw(ctx, ch, 1)</code> と'
    + '<strong>進み具合1を直に描く</strong>。組み合わせではその1が振り分けの終端に写るので、'
    + '<strong>「字ごとの窓」だと終端が s95 止まりになり、字が完成しない</strong>。'
    + '（transfer.js の compositeSplit の注記が警告しているのはこの点。'
    + '現行のべき乗は u=1 で 100% に届くので完成する。）</p>'
    + '<div class="gridwrap"><table class="frames"><tr><th></th>'
    + DATA.chars.map(c => '<th class="gh">' + c + '</th>').join("") + '</tr>';
  h += "</table></div>";
  d.innerHTML = h;
  const tbl = d.querySelector("table");
  keys.forEach(key => {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td class="rowlbl"><span class="'
      + (key === "current" ? "tagold" : "tagnew") + '">'
      + (key === "current" ? "現行" : "新") + "</span></td>";
    DATA.chars.forEach(ch => {
      const td = document.createElement("td");
      const box = document.createElement("div"); box.className = "cell";
      const cv = document.createElement("canvas");
      cv.width = cv.height = CFG.visual.size_px;
      box.appendChild(cv);
      warpTables = tableOf(key).doc;
      const R = RENDERERS[ui.fam];
      R.begin(ch, cv.getContext("2d", {willReadFrequently:true}));
      R.draw(cv.getContext("2d", {willReadFrequently:true}), ch, 1, ui.dir);
      const sp = splitFor(key, ui.fam, ch, 1);
      const cap = document.createElement("div"); cap.className = "cap";
      const parts = ui.fam.split("+");
      cap.innerHTML = LAB[parts[0]] + " " + (sp.sa*100).toFixed(1) + "%<br>"
                    + LAB[parts[1]] + " " + (sp.sb*100).toFixed(1) + "%";
      box.appendChild(cap);
      td.appendChild(box); tr.appendChild(td);
    });
    tbl.appendChild(tr);
  });
  host.appendChild(d);
}

function buildSplits(){
  const host = document.getElementById("splits");
  const h2 = document.getElementById("h-split");
  host.innerHTML = "";
  if (ui.fam.indexOf("+") < 0){
    h2.style.opacity = .45;
    host.innerHTML = '<p class="small">方式に組み合わせ（うすい×ぼやけ など）を選ぶと出る。</p>';
    return;
  }
  h2.style.opacity = 1;
  const newKey = (ui.table === "current")
    ? (DATA.table_order.find(k => k !== "current") || "v3_lin") : ui.table;
  const leg = document.createElement("div");
  leg.className = "legend";
  leg.innerHTML = '<span style="color:var(--old)"><i></i>現行（8字平均のべき乗・字によらず同じ）</span>'
    + '<span style="color:var(--new)"><i></i>' + tableOf(newKey).label + '（字ごとの窓）</span>'
    + '<span class="small">● は打ち切り7点で実際に使われる点</span>';
  host.appendChild(leg);
  DATA.chars.forEach(ch => {
    const fig = document.createElement("figure");
    const w = document.createElement("div"); w.className = "figwrap";
    w.appendChild(makeSplitFig(ch));
    fig.appendChild(w);
    const cap = document.createElement("figcaption");
    const uo = spanU("current", ui.fam, ch), un = spanU(newKey, ui.fam, ch);
    cap.innerHTML = "<b>" + ch + "</b>（" + famLabel(ui.fam) + "） 打ち切り7点で u が動く幅："
      + '<span class="tagold">現行 ' + uo.span.toFixed(2) + "pt（"
      + fmtPct(uo.lo) + "%→" + fmtPct(uo.hi) + "%・別の絵 " + uo.n + "/7）</span> ／ "
      + '<span class="tagnew">新 ' + un.span.toFixed(2) + "pt（"
      + fmtPct(un.lo) + "%→" + fmtPct(un.hi) + "%・別の絵 " + un.n + "/7）</span>";
    fig.appendChild(cap);
    host.appendChild(fig);
  });
}
// 打ち切り7点で「実質いくつ別の絵になるか」。build_warp_b3.py の
// n_levels_at_gates と同じ数え方（隣り合う点で 1pt 以上進めば別の絵と数える）。
function nLevels(ss){
  let n = 1;
  for (let i = 1; i < ss.length; i++) if (ss[i] - ss[i-1] > 1.0) n++;
  return n;
}
function spanU(key, fam, ch, cond){
  const g = DATA.gates[ch];
  const {fn} = progressFor(key, fam, ch, cond || "proposed");
  const ss = g.map(t => fn(t)*100);
  return {lo:Math.min.apply(null, ss), hi:Math.max.apply(null, ss),
          span:Math.max.apply(null, ss) - Math.min.apply(null, ss), n:nLevels(ss)};
}

// ---------------------------------------------------------------------------
// §4 現行 vs 新 の表
// ---------------------------------------------------------------------------
function buildCompareTable(){
  const host = document.getElementById("cmptbl");
  let h = '<div class="gridwrap"><table class="tbl"><thead><tr>'
        + '<th>方式</th><th>字</th><th>可動域 現行</th><th>可動域 新・線形</th>'
        + '<th>可動域 新・対数線形</th><th>点数 現行</th><th>点数 新・線形</th>'
        + '<th>μ 旧→新</th><th>σ 旧→新</th></tr></thead><tbody>';
  DATA.compare.forEach(r => {
    const hi = (r.char === "が" || r.char === "ぱ") && r.family.indexOf("+") >= 0;
    h += '<tr' + (hi ? ' class="hi"' : '') + '><td>' + famLabel(r.family) + '</td><td>' + r.char + '</td>'
      + '<td class="num">' + r.span_pt_old.toFixed(2) + '</td>'
      + '<td class="num">' + r.span_pt_lin.toFixed(2) + '</td>'
      + '<td class="num">' + r.span_pt_log.toFixed(2) + '</td>'
      + '<td class="num">' + r.n_levels_old + '</td>'
      + '<td class="num">' + r.n_levels_lin + '</td>'
      + '<td class="num">' + (isFinite(r.mu_old) ? r.mu_old.toFixed(2) + " → " + r.mu_new.toFixed(2) : "—") + '</td>'
      + '<td class="num">' + (isFinite(r.sigma_old) ? r.sigma_old.toFixed(2) + " → " + r.sigma_new.toFixed(2) : "—") + '</td>'
      + '</tr>';
  });
  h += '</tbody></table></div>';
  host.innerHTML = h;
}

// ---------------------------------------------------------------------------
// 注意書き
// ---------------------------------------------------------------------------
function buildWarn(){
  const host = document.getElementById("warnbox");
  let h = "";
  const t = tableOf(ui.table);
  const gmax = Math.max.apply(null, DATA.chars.map(c => DATA.gates[c][6]));
  if (t.covers_ms < gmax){
    h += '<div class="card alert"><b>この表は ' + t.covers_ms + 'ms までしか数値が入っていない。</b>'
      + ' いちばん遅い打ち切りは ' + gmax + 'ms（ま）なので、'
      + 'それより後は<strong>最後の値のまま止まる</strong>（<code>seriesAt</code> の決まり）。'
      + '<span class="small">出どころ ' + t.path + '</span></div>';
  }
  if (!canvasFilterWorks()){
    h += '<div class="card alert"><b>この端末では canvas の filter が効かない。</b>'
      + 'ぼやけ（blur）と、それを含む組み合わせが<strong>鮮明なまま出る</strong>。'
      + 'WebKit（iOS の全ブラウザ・macOS Safari）はこれに当たる。Chrome で開き直すこと。</div>';
  }
  host.innerHTML = h;
}

// ---------------------------------------------------------------------------
// 組み立て
// ---------------------------------------------------------------------------
function rebuild(){
  buildWarn();
  buildFrames();
  buildFigs();
  buildCheckFull();
  buildSplits();
}

function init(){
  const st = document.getElementById("selTable");
  DATA.table_order.forEach(k => {
    const o = document.createElement("option");
    o.value = k; o.textContent = tableOf(k).label;
    st.appendChild(o);
  });
  const sf = document.getElementById("selFam");
  DATA.fams.forEach(f => {
    const o = document.createElement("option");
    o.value = f; o.textContent = famLabel(f);
    sf.appendChild(o);
  });
  ui.table = DATA.table_order.indexOf("v3_lin") >= 0 ? "v3_lin" : DATA.table_order[0];
  st.value = ui.table;
  sf.value = ui.fam;
  st.onchange = () => { ui.table = st.value; rebuild(); };
  sf.onchange = () => { ui.fam = sf.value; rebuild(); };
  document.getElementById("selCond").onchange = e => { ui.cond = e.target.value; rebuild(); };
  document.getElementById("selDir").onchange = e => { ui.dir = e.target.value; rebuild(); };
  document.getElementById("chkCmp").onchange = e => { ui.cmp = e.target.checked; rebuild(); };
  document.getElementById("chkAllFam").onchange = e => { ui.allfam = e.target.checked; rebuild(); };
  document.getElementById("chkLog").onchange = e => { ui.logsplit = e.target.checked; buildSplits(); };
  document.getElementById("btnPlayAll").onclick = playAll;

  document.getElementById("prov").innerHTML =
    "出どころ: 描画＝<code>experiment/transfer.js</code>（切り出してそのまま）／"
    + "設定＝<code>experiment/transfer_config.js</code>／"
    + "表＝" + DATA.table_order.map(k => "<code>" + tableOf(k).path + "</code>").join("・")
    + "／当てはめ＝<code>project/data_calib2_live/warp_v3/fit_audio_v3.csv</code>・"
    + "<code>fit_visual_v3.csv</code>・<code>composite_window.csv</code>・"
    + "<code>project/data_calib2_live/warp_new/fit_logistic_calib1.csv</code>（ぼやけ・現行）・"
    + "<code>fit_logistic_calib2.csv</code>（現行）。"
    + "組み立て＝<code>experiment/tools/build_warp_preview.py</code>。";

  buildCompareTable();
  loadAll().then(rebuild).catch(e => {
    document.getElementById("warnbox").innerHTML =
      '<div class="card alert">文字画像を読めなかった: ' + e.message + '</div>';
  });
}
init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
