#!/usr/bin/env node
/* =========================================================================
 * 群A′（視覚較正）の出題一覧を、実際の見た目つきで1枚のHTMLにする
 * =========================================================================
 * 2026-08-25 作成。
 *
 * **なぜ作るのか。** 丸山さんが群A′を途中まで通したところ
 * 「何も見えない、みたいなやつが多すぎる」という報告があった。
 * 水準は [1, 3.25, 5.5, 20, 100]% で、**5水準のうち1人が担当するのは3つ**。
 * その3つは point_subsets["5"] = [0,1,3] を参加者ごと・字ごとに回転させて選ぶので、
 * 平均すると **3問中1.8問が薄い側（1〜7%）** に当たる計算になる。
 * 数字だけでは「薄すぎるのか、ちょうどよいのか」を判断できないので、
 * **参加者が実際に見る絵をそのまま並べて、目で確かめられるようにする。**
 *
 * **実物と同じ絵であることをどう担保するか。**
 * 描画器（fade / reveal / blur / wipe）を書き写すと、transfer.js を直したときに
 * 食い違う。そこで **transfer.js から該当部分をそのまま切り出して埋め込む**。
 * 切り出す範囲は「const SIZE = …」から「const RENDERERS = {…};」までで、
 * この範囲が外に依存しているのは CFG.visual.families だけであることを確認済み。
 *
 * 出題そのものも、推定式ではなく **transfer.js を実際に走らせて組み立てさせる**
 * （check_transfer_stimuli.js と同じ仕掛け）。過去に推定式が実装から遅れて
 * 最大43問ずれた事故があるため。
 *
 * 出力: experiment/tools/visual_trial_list.html
 *
 * 使い方:
 *   node experiment/tools/build_visual_trial_list.js            # 連番0と1の2人ぶん
 *   node experiment/tools/build_visual_trial_list.js 0 1 2      # 連番を指定
 * ========================================================================= */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXP = path.resolve(__dirname, "..");
const OUT = path.join(__dirname, "visual_trial_list.html");
const ASSIGNS = process.argv.slice(2).length
  ? process.argv.slice(2).map(Number) : [0, 1];

// ---- 設定 -----------------------------------------------------------------
global.window = {};
require(path.join(EXP, "transfer_config.js"));
const CFG = global.window.TRANSFER_CONFIG;

// ---- transfer.js から描画器をそのまま切り出す -----------------------------
const jsText = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8");
const lines = jsText.split("\n");
const from = lines.findIndex(l => l.startsWith("const SIZE = CFG.visual.size_px;"));
let to = lines.findIndex(l => l.startsWith("const RENDERERS = {"));
if (from < 0 || to < 0) {
  console.error("transfer.js から描画器の範囲を見つけられない（目印の行が変わった？）");
  process.exit(1);
}
while (to < lines.length && lines[to] !== "};") to++;   // RENDERERS の閉じ括弧まで
const RENDER_SRC = lines.slice(from, to + 1).join("\n");
console.log(`  描画器を transfer.js の ${from + 1}〜${to + 1} 行から切り出しました`);

// ---- 出題を transfer.js に組み立てさせる（推定式では数えない） -------------
function stubEl() {
  const el = {
    innerHTML: "", textContent: "", value: "", disabled: false, checked: false,
    style: {}, dataset: {}, parentElement: null,
    appendChild: () => el, insertBefore: () => el, removeChild: () => el, remove() {},
    addEventListener() {}, removeEventListener() {}, focus() {}, blur() {}, click() {},
    setAttribute() {}, removeAttribute() {}, getAttribute: () => null,
    querySelector: () => null, querySelectorAll: () => [],
    insertAdjacentElement() {}, insertAdjacentHTML() {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    getContext: () => ({
      fillStyle: "", font: "", textAlign: "", textBaseline: "", globalAlpha: 1, filter: "",
      fillRect() {}, drawImage() {}, fillText() {}, clearRect() {}, save() {}, restore() {},
      beginPath() {}, arc() {}, fill() {}, clip() {}, translate() {}, scale() {},
      getImageData: () => ({ data: new Uint8ClampedArray(4) }), putImageData() {},
      createImageData: () => ({ data: new Uint8ClampedArray(4) }),
    }),
    width: 0, height: 0,
  };
  return el;
}
const sandbox = {
  console: { log() {}, warn() {}, error() {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  URLSearchParams, AbortController, performance,
  fetch: () => Promise.reject(new Error("harness: 通信しない")),
  requestAnimationFrame: () => 0,
  location: { search: "" },
  navigator: { userAgent: "node-harness", maxTouchPoints: 0 },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  document: {
    title: "", getElementById: () => stubEl(), createElement: () => stubEl(),
    querySelector: () => null, querySelectorAll: () => [],
  },
  devicePixelRatio: 1, screen: { width: 1280, height: 800 },
  addEventListener() {}, removeEventListener() {},
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
sandbox.TRANSFER_PAGE = { phase: "calib" };
const ctx = vm.createContext(Object.assign({}, sandbox));
ctx.window = ctx; ctx.globalThis = ctx;
for (const f of ["transfer_config.js", "transfer_firestore.js"]) {
  vm.runInContext(fs.readFileSync(path.join(EXP, f), "utf8"), ctx, { filename: f });
}
vm.runInContext(jsText + `
;globalThis.__build = function (n) {
   GROUP = "aprime"; G = GROUPS.aprime; ASSIGN = n; ASSIGN_SOURCE = "harness";
   _freqCache = null;
   ALL_KANA.forEach(c => { imgs[c] = imgs[c] || {}; });
   return { trials: buildVisualTrials().map(x => ({
              char: x.char, family: x.family, pct: x.progress_pct,
              anim: x.base_anim_ms || 0, decoy: !!x.is_decoy,
              check: x.check_kind || "" })),
            levels: progressLevels(), decoys: decoyChars() }; };`,
  ctx, { filename: "transfer.js" });

const people = ASSIGNS.map(n => Object.assign({ assign: n }, ctx.__build(n)));
console.log(`  ${people.length}人ぶんの出題を組み立てました（1人 ${people[0].trials.length} 問）`);

// ---- 画像を data URI で埋め込む（ローカルで開いても出るように） -------------
const need = new Set();
people.forEach(p => p.trials.forEach(t => need.add(t.char)));
const b64 = {};
let missing = [];
for (const ch of need) {
  const p = path.join(EXP, "base", ch + ".png");
  if (!fs.existsSync(p)) { missing.push(ch); continue; }
  b64[ch] = fs.readFileSync(p).toString("base64");
}
if (missing.length) console.log(`  ⚠ 画像が無い字: ${missing.join(" ")}`);
console.log(`  ${Object.keys(b64).length}字ぶんの画像を埋め込みました`);

// ---- 集計（薄い側がどれだけを占めるか） -----------------------------------
const THIN_MAX = 10;      // これ以下を「薄い側」と数える
const summary = people.map(p => {
  const main = p.trials.filter(t => !t.check);
  const thin = main.filter(t => t.pct <= THIN_MAX).length;
  return { assign: p.assign, levels: p.levels, total: p.trials.length,
           main: main.length, thin, pctThin: Math.round(thin / main.length * 100) };
});
const allMain = people.flatMap(p => p.trials.filter(t => !t.check));
const byPct = {};
allMain.forEach(t => { byPct[t.pct] = (byPct[t.pct] || 0) + 1; });
console.log("\n  進み具合ごとの問題数（全員ぶん・確認問題を除く）");
Object.keys(byPct).map(Number).sort((a, b) => a - b)
  .forEach(k => console.log(`    ${String(k).padStart(6)}%  ${byPct[k]}問`));
console.log(`\n  ${THIN_MAX}%以下が占める割合: ` +
  `${Math.round(allMain.filter(t => t.pct <= THIN_MAX).length / allMain.length * 100)}%`);

// ---- HTML -----------------------------------------------------------------
const FAMILY_JA = { fade: "うすい→濃い", reveal: "点が増える",
                    blur: "ぼやけ→はっきり", wipe: "端から現れる" };

const html = `<!doctype html><meta charset="utf-8">
<title>群A′の出題一覧（実際の見た目つき）</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:1180px}
h1{font-size:20px;margin:0 0 6px}
h2{font-size:16px;margin:26px 0 8px;padding-bottom:4px;border-bottom:2px solid #dde1ea}
p.note{line-height:1.85;font-size:14px}
.box{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:12px 15px;
     margin:12px 0;font-size:13.5px;line-height:1.9}
.box b.hl{background:#fff3bf;padding:0 3px;border-radius:3px}
.warn{background:#fff8f3;border-color:#f0c4a8}
table{border-collapse:collapse;margin:10px 0;font-size:13px}
th,td{border:1px solid #dde1ea;padding:5px 9px;background:#fff;text-align:center}
th{background:#f2f4f8;font-weight:700}
td.l{text-align:left}
.grid{display:flex;flex-wrap:wrap;gap:7px;margin-top:8px}
.cell{border:1px solid #dde1ea;border-radius:7px;background:#fff;padding:5px;width:104px;
      text-align:center}
.cell.thin{background:#fff8f3;border-color:#f0c4a8}
.cell.chk{background:#f3f6ff;border-color:#b9c6ea}
.cell canvas{width:88px;height:88px;background:#fff;border:1px solid #eceef2;border-radius:4px;
      display:block;margin:0 auto}
.cap{font-size:10.5px;line-height:1.35;color:#59606e;margin-top:3px}
.cap b{color:#1b2030;font-size:12px}
.tag{display:inline-block;font-size:9px;border-radius:3px;padding:0 3px;margin-top:2px}
.tag.d{background:#eef1f6;color:#6b7280}
.tag.c{background:#e7edff;color:#2b3a75}
.legend{font-size:12px;color:#7a8090;line-height:1.8;margin-top:6px}
.sw{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:-1px;margin-right:3px}
.bar{display:inline-block;height:11px;background:#c7743f;border-radius:2px;vertical-align:-1px}
details{margin:10px 0}
summary{cursor:pointer;font-weight:700;font-size:14px;padding:6px 0}
</style>

<h1>群A′（視覚較正）の出題一覧</h1>
<p id="drawing" style="font-size:13px;color:#c7743f">描画中…</p>
<p class="note">
下に出ている絵は、<b>参加者が実際に見るものと同じ描画コード</b>で描いています
（<code>transfer.js</code> の描画器を、この一覧を作るときにそのまま切り出して埋め込んでいます）。
出題も推定式ではなく <b>transfer.js に実際に組み立てさせた</b>ものです。
</p>

<div class="box warn">
<b class="hl">「何も見えない問題が多すぎる」の正体。</b><br>
進み具合の水準は <b>[1, 3.25, 5.5, 20, 100]%</b> の5つで、参加者ごとに下3つが
0.75%ずつずれます。<b>1人が担当するのはこのうち3水準</b>で、その3つは
<code>[0,1,3]</code> を字ごとに回転させて選びます。回転を数えると
<b>平均して3問中1.8問が薄い側（1〜7%）</b>に当たります。<br>
つまり<b>設計上、本題のおよそ6割が「ほとんど見えない」条件</b>です。これは
「見え始めるところを密に測る」というねらい（先生のパイロットで13%以上が天井に張り付いたため）
の裏返しですが、<b>薄すぎて全部が床に張り付くと曲線の立ち上がりが取れず、
その問題は無駄になります。</b><br>
<b>下の絵を見て、1〜7%が「たまに分かる」範囲か「まったく無理」かを判断してください。</b>
まったく無理なら水準を上げる必要があります。
</div>

<h2>進み具合ごとの問題数（${people.length}人ぶん・確認問題を除く）</h2>
<table>
<tr><th>進み具合</th><th>問題数</th><th>割合</th><th></th></tr>
${Object.keys(byPct).map(Number).sort((a, b) => a - b).map(k => {
  const pc = Math.round(byPct[k] / allMain.length * 100);
  return `<tr><td><b>${k}%</b></td><td>${byPct[k]}</td><td>${pc}%</td>` +
         `<td class="l"><span class="bar" style="width:${pc * 4}px"></span></td></tr>`;
}).join("\n")}
</table>
<p class="note"><b>${THIN_MAX}%以下が全体の
${Math.round(allMain.filter(t => t.pct <= THIN_MAX).length / allMain.length * 100)}%</b>を占めます。</p>

<h2>1人あたりの内訳</h2>
<table>
<tr><th>連番</th><th>その人の水準</th><th>全問</th><th>本題</th><th>${THIN_MAX}%以下</th><th>割合</th></tr>
${summary.map(s => `<tr><td>${s.assign}</td><td>${s.levels.join(", ")}%</td>` +
  `<td>${s.total}</td><td>${s.main}</td><td><b>${s.thin}</b></td><td>${s.pctThin}%</td></tr>`).join("\n")}
</table>

${people.map(p => `
<details${p.assign === ASSIGNS[0] ? " open" : ""}>
<summary>連番 ${p.assign} の出題 ${p.trials.length} 問（水準 ${p.levels.join(", ")}%）</summary>
<div class="legend">
<span class="sw" style="background:#fff8f3;border:1px solid #f0c4a8"></span>${THIN_MAX}%以下（薄い側）
<span class="sw" style="background:#f3f6ff;border:1px solid #b9c6ea;margin-left:10px"></span>確認問題
<span class="tag d" style="margin-left:10px">偽</span>偽のターゲット（解析に使わない）
</div>
<div class="grid" data-person="${p.assign}">
${p.trials.map((t, i) => `<div class="cell${t.pct <= THIN_MAX && !t.check ? " thin" : ""}${t.check ? " chk" : ""}">
  <canvas data-ch="${t.char}" data-fam="${t.family}" data-pct="${t.pct}"></canvas>
  <div class="cap"><b>${i + 1}. ${t.char}</b> ${t.pct}%<br>${FAMILY_JA[t.family] || t.family}<br>${t.anim}ms
  ${t.decoy ? '<span class="tag d">偽</span>' : ""}${t.check ? `<span class="tag c">確認${t.check === "full" ? "A" : "C"}</span>` : ""}</div>
</div>`).join("\n")}
</div>
</details>`).join("\n")}

<script>
const IMG_B64 = ${JSON.stringify(b64)};
const CFG = ${JSON.stringify({ visual: CFG.visual })};
${RENDER_SRC}

// 画像を読み込んでから、各セルを1枚ずつ描く。
// ⚠ **一気に描かないこと。** 1枚ずつが重い描画なので、全部を同期で回すと固まる
//   （実際に固まった。6人×70問=420枚で操作を受け付けなくなった）。
//   そこで **画面に入ったものだけを描く**（IntersectionObserver）。
//   これなら人数を増やしても、開いた瞬間から操作できる。
(async function () {
  const note = document.getElementById('drawing');
  await Promise.all(Object.keys(IMG_B64).map(ch => new Promise(res => {
    const im = new Image();
    im.onload = () => { imgs[ch] = im; res(); };
    im.onerror = () => res();
    im.src = 'data:image/png;base64,' + IMG_B64[ch];
  })));
  if (note) note.remove();

  function paint(cv) {
    if (cv.dataset.done) return;
    cv.dataset.done = '1';
    cv.width = SIZE; cv.height = SIZE;
    const c2 = cv.getContext('2d');
    const fam = cv.dataset.fam, ch = cv.dataset.ch;
    const s = Math.max(0, Math.min(1, Number(cv.dataset.pct) / 100));
    const R = RENDERERS[fam] || RENDERERS.fade;
    try { R.begin(ch, c2); } catch (e) {}
    try { R.draw(c2, ch, s); } catch (e) { c2.fillStyle = '#fee'; c2.fillRect(0, 0, SIZE, SIZE); }
  }
  const io = new IntersectionObserver(es => {
    es.forEach(e => { if (e.isIntersecting) { paint(e.target); io.unobserve(e.target); } });
  }, { rootMargin: '300px' });
  document.querySelectorAll('canvas[data-ch]').forEach(cv => io.observe(cv));

  // 折りたたみを開いたときにも、その中身を見張りに加える。
  document.querySelectorAll('details').forEach(d => d.addEventListener('toggle', () => {
    if (d.open) d.querySelectorAll('canvas[data-ch]:not([data-done])').forEach(cv => io.observe(cv));
  }));
})();
</script>
`;
fs.writeFileSync(OUT, html, "utf8");
console.log(`\n  → ${OUT}  (${(fs.statSync(OUT).size / 1024 / 1024).toFixed(1)} MB)`);
