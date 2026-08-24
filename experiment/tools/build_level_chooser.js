#!/usr/bin/env node
/* =========================================================================
 * 視覚の「水準」と「ぼかしの強さ」を目で決めるためのページ
 * =========================================================================
 * 2026-08-25 作成。
 *
 * **なぜ要るのか。** 2026-08-25 の自己テストで、群A′の水準配置に穴が見つかった。
 *   ・7%と20%のあいだに水準が1つも無く、曲線が立ち上がる帯を跨いでいる
 *   ・「ぼやけ→はっきり」だけ床が無い（最大ぼかし24pxでも読めてしまう）
 * どちらも **数字だけでは決められない**（見えるかどうかは目で判断するしかない）。
 * そこで、**実際の描画コードで描いた絵を並べて、値を選べるようにする**。
 *
 * 実物と同じ絵であることの担保は build_visual_trial_list.js と同じで、
 * transfer.js から描画器をそのまま切り出して埋め込む。
 *
 * 出力: experiment/tools/level_chooser.html
 *
 * 使い方:
 *   node experiment/tools/build_level_chooser.js
 * ========================================================================= */
"use strict";
const fs = require("fs");
const path = require("path");

const EXP = path.resolve(__dirname, "..");
const OUT = path.join(__dirname, "level_chooser.html");

global.window = {};
require(path.join(EXP, "transfer_config.js"));
const CFG = global.window.TRANSFER_CONFIG;

// ---- 描画器を transfer.js からそのまま切り出す ----------------------------
const lines = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8").split("\n");
const from = lines.findIndex(l => l.startsWith("const SIZE = CFG.visual.size_px;"));
let to = lines.findIndex(l => l.startsWith("const RENDERERS = {"));
if (from < 0 || to < 0) { console.error("描画器の範囲が見つからない"); process.exit(1); }
while (to < lines.length && lines[to] !== "};") to++;
const RENDER_SRC = lines.slice(from, to + 1).join("\n");

// ---- 見比べに使う字 -------------------------------------------------------
// 本命8字から、画数の少ない字と多い字の両端＋中くらいを取る。
// （難しさは字形で変わるので、1字だけで決めると偏る）
const CHARS = ["あ", "く", "ま", "ぱ"];
const FAMILIES = ["fade", "reveal", "blur", "wipe"];
const FAMILY_JA = { fade: "うすい→濃い", reveal: "点が増える",
                    blur: "ぼやけ→はっきり", wipe: "端から現れる" };

const NOW = CFG.visual.progress_pct_levels;                 // [1, 3.25, 5.5, 20, 100]
const PROPOSED = [3, 6, 9, 12, 16, 22, 35, 100];            // 案
const BLUR_RADII = [24, 32, 40, 48, 56, 64, 80];            // 24 がいまの値

const b64 = {};
for (const ch of CHARS) {
  const p = path.join(EXP, "base", ch + ".png");
  if (!fs.existsSync(p)) { console.error(`画像が無い: ${p}`); process.exit(1); }
  b64[ch] = fs.readFileSync(p).toString("base64");
}

function cellsFor(levels, fam) {
  return levels.map(p =>
    `<td><canvas data-ch="{{CH}}" data-fam="${fam}" data-pct="${p}"></canvas>
     <div class="cap">${p}%</div></td>`).join("");
}

function levelTable(levels, fam, id) {
  const rows = CHARS.map(ch =>
    `<tr><th>${ch}</th>` + cellsFor(levels, fam).replace(/\{\{CH\}\}/g, ch) + `</tr>`).join("");
  return `<table id="${id}"><tr><th></th>` +
    levels.map(p => `<th>${p}%</th>`).join("") + `</tr>${rows}</table>`;
}

function blurTable() {
  const rows = CHARS.map(ch =>
    `<tr><th>${ch}</th>` + BLUR_RADII.map(r =>
      `<td><canvas data-ch="${ch}" data-fam="blur" data-pct="0" data-radius="${r}"></canvas>
       <div class="cap${r === CFG.visual.families.blur.max_radius_px ? " now" : ""}">${r}px${
         r === CFG.visual.families.blur.max_radius_px ? "<br>いま" : ""}</div></td>`).join("")
    + `</tr>`).join("");
  return `<table><tr><th></th>` + BLUR_RADII.map(r => `<th>${r}px</th>`).join("")
    + `</tr>${rows}</table>`;
}

const html = `<!doctype html><meta charset="utf-8">
<title>視覚の水準とぼかしを決める</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:1120px;line-height:1.75}
h1{font-size:20px;margin:0 0 6px}
h2{font-size:16.5px;margin:28px 0 8px;padding-bottom:5px;border-bottom:2px solid #dde1ea}
h3{font-size:14px;margin:16px 0 4px;color:#2b3a52}
p,li{font-size:14px}
table{border-collapse:collapse;margin:8px 0 16px}
th,td{border:1px solid #dde1ea;padding:4px;background:#fff;text-align:center;vertical-align:top}
th{background:#f2f4f8;font-size:12px;color:#59606e}
canvas{width:84px;height:84px;background:#fff;border:1px solid #eceef2;border-radius:4px;display:block}
.cap{font-size:10px;color:#7a8090;margin-top:2px}
.cap.now{color:#9a3412;font-weight:700}
.box{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:12px 16px;margin:12px 0;
     font-size:13.5px}
.bad{background:#fff8f3;border-color:#f0c4a8}
.good{background:#f1f9f3;border-color:#a8d3b5}
.hl{background:#fff3bf;padding:0 3px;border-radius:3px}
.k{color:#8a90a0;font-size:12.5px}
.tabs button{font-size:13px;padding:5px 12px;margin-right:5px;border-radius:6px;
     border:1px solid #b9c0cf;background:#fff;cursor:pointer;font-family:inherit}
.tabs button.on{background:#1b2030;color:#fff;border-color:#1b2030}
</style>

<h1>視覚の水準とぼかしを決める</h1>
<p class="k">絵は<b>参加者が実際に見るのと同じ描画コード</b>（transfer.js から切り出し）で描いています。
アニメの長さは <b>${CFG.visual.base_anim_ms}ms</b> の設定ですが、ここでは<b>止めた状態</b>を並べています。
実際は動いて止まるので、これより少し分かりにくくなります。</p>

<h2>1. 水準をどこに置くか</h2>
<div class="box bad">
<b class="hl">見るところ:</b> 左端が「まったく分からない」、右端が「はっきり分かる」になっていて、
<b>そのあいだが飛ばずに埋まっているか</b>。<br>
いまの並びは <b>1〜5.5% と 20% のあいだが空いていて</b>、そこを跨いでいます。
</div>

<div class="tabs" id="famTabs">
${FAMILIES.map((f, i) => `<button data-fam="${f}"${i === 0 ? ' class="on"' : ""}>${FAMILY_JA[f]}</button>`).join("")}
</div>

${FAMILIES.map((f, i) => `<div class="pane" data-fam="${f}" style="display:${i === 0 ? "block" : "none"}">
<h3>いまの5水準　<span class="k">[${NOW.join(", ")}]</span></h3>
${levelTable(NOW, f, "now-" + f)}
<h3>案の8水準　<span class="k">[${PROPOSED.join(", ")}]</span></h3>
${levelTable(PROPOSED, f, "prop-" + f)}
</div>`).join("")}

<h2>2. ぼかしの最大をいくつにするか</h2>
<div class="box bad">
<b class="hl">見るところ:</b> <b>その字が何か分からなくなる最小の値</b>を選んでください。<br>
これは<b>進み具合0%（いちばんぼやけた状態）</b>の見た目です。ここで字が読めてしまうと、
「ぼやけ→はっきり」だけ床が無くなり、曲線を当てはめられません。<br>
実測では <b>いまの24pxで、進み具合1.75%でも4問中4問正解</b>でした（＝読めている）。
</div>
${blurTable()}

<h2>3. 決めたら</h2>
<p>選んだ値を教えてください。<code>transfer_config.js</code> の
<code>visual.progress_pct_levels</code> と <code>visual.families.blur.max_radius_px</code> に入れ、
出題一覧（<code>visual_trial_list.html</code>）を作り直してもう一度確かめます。</p>
<p class="k">※ 水準を8にしても<b>1人あたりの問題数は70問のまま</b>です（1字につき3水準を担当する仕組みは同じ）。
変わるのはセルの埋まり方だけで、<code>point_subsets</code> には既に <code>"8"</code> があります。</p>

<script>
const IMG_B64 = ${JSON.stringify(b64)};
const CFG = ${JSON.stringify({ visual: CFG.visual })};
${RENDER_SRC}

(async function () {
  await Promise.all(Object.keys(IMG_B64).map(ch => new Promise(res => {
    const im = new Image();
    im.onload = () => { imgs[ch] = im; res(); };
    im.onerror = () => res();
    im.src = 'data:image/png;base64,' + IMG_B64[ch];
  })));

  function paint(cv) {
    if (cv.dataset.done) return;
    cv.dataset.done = '1';
    cv.width = SIZE; cv.height = SIZE;
    const c2 = cv.getContext('2d');
    const ch = cv.dataset.ch, fam = cv.dataset.fam;
    const s = Math.max(0, Math.min(1, Number(cv.dataset.pct) / 100));
    // ぼかしの強さを変えて見るとき（2節）は、設定を一時的に差し替えて描く。
    const keep = CFG.visual.families.blur.max_radius_px;
    if (cv.dataset.radius) CFG.visual.families.blur.max_radius_px = Number(cv.dataset.radius);
    const R = RENDERERS[fam] || RENDERERS.fade;
    try { R.begin(ch, c2); R.draw(c2, ch, s); }
    catch (e) { c2.fillStyle = '#fee'; c2.fillRect(0, 0, SIZE, SIZE); }
    CFG.visual.families.blur.max_radius_px = keep;
  }
  // 見えているものだけ描く（全部を一度に描くと重い）
  const io = new IntersectionObserver(es => {
    es.forEach(e => { if (e.isIntersecting) { paint(e.target); io.unobserve(e.target); } });
  }, { rootMargin: '400px' });
  const watch = () => document.querySelectorAll('canvas:not([data-done])').forEach(cv => io.observe(cv));
  watch();

  document.querySelectorAll('#famTabs button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#famTabs button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.pane').forEach(p => {
      p.style.display = (p.dataset.fam === b.dataset.fam) ? 'block' : 'none';
    });
    watch();
  }));
})();
</script>
`;
fs.writeFileSync(OUT, html, "utf8");
console.log(`  字 ${CHARS.join("")} × 方式4 × (いま${NOW.length}水準 + 案${PROPOSED.length}水準) ＋ ぼかし${BLUR_RADII.length}段階`);
console.log(`  → ${OUT}  (${(fs.statSync(OUT).size / 1024).toFixed(0)} KB)`);
