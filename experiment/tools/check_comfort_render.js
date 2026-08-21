#!/usr/bin/env node
/* =========================================================================
 * 見え心地の評価（群C）のページが、群Bと**同じ絵**を出す状態かを見る
 * =========================================================================
 * 掲載の前に必ず通す。ブラウザを開かずに、次の3つを機械的に確かめる。
 *
 *   1. 入口HTMLの参照   … transfer_comfort.html が読む JS・CSS が実在し、
 *                          キャッシュ避けの ?v= が transfer_comfort.js の
 *                          VERSION と一致しているか
 *   2. 描画器の一致     … transfer_comfort.js は、4方式の描画器と進み方の補間を
 *                          transfer.js から**写して**持っている。両者が食い違うと、
 *                          群B（識別課題）と群C（見え心地）で違う絵を見せることになり、
 *                          2つの結果を並べて論じられなくなる。関数の中身を1つずつ比べる。
 *   3. 設定の筋が通っているか … 代表字が transfer_config.js のターゲット字に入っているか、
 *                          方式名が描画器にあるか、代表字の画像が実在するか
 *
 * 使い方:  node experiment/tools/check_comfort_render.js
 * 終了コード: 0=すべて合格 / 1=不合格(掲載してはいけない)
 * ========================================================================= */
"use strict";
const fs = require("fs");
const path = require("path");

const EXP = path.resolve(__dirname, "..");
const problems = [];
const notes = [];
function bad(msg) { problems.push(msg); }
function ok(msg) { notes.push(msg); }

// ---- 設定を読む(実験ページと同じファイル) --------------------------------
global.window = {};
require(path.join(EXP, "transfer_config.js"));
require(path.join(EXP, "transfer_comfort_config.js"));
const CFG = global.window.TRANSFER_CONFIG;
const C = global.window.TRANSFER_COMFORT_CONFIG;

const mainText = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8");
const comfortText = fs.readFileSync(path.join(EXP, "transfer_comfort.js"), "utf8");

// ---- 1. 入口HTMLの参照 ----------------------------------------------------
const vm = comfortText.match(/const VERSION = "([^"]+)"/);
const VERSION = vm ? vm[1] : null;
if (!VERSION) bad("transfer_comfort.js から VERSION を読めない");

{
  const page = "transfer_comfort.html";
  const html = fs.readFileSync(path.join(EXP, page), "utf8");
  const refs = [...html.matchAll(/(?:src|href)="([^"]+?)(?:\?v=([^"]*))?"/g)];
  let found = 0;
  for (const [, file, v] of refs) {
    if (/^https?:/.test(file)) continue;
    found++;
    if (!fs.existsSync(path.join(EXP, file))) bad(`${page}: ${file} が無い`);
    if (v !== undefined && v !== VERSION) {
      bad(`${page}: ${file} の ?v=${v} が transfer_comfort.js の VERSION=${VERSION} と違う`);
    }
  }
  if (found < 5) bad(`${page}: 読み込んでいるファイルが ${found} 個しかない(CSS+JS4本のはず)`);
  else ok(`${page}: 参照 ${found} 件すべて実在・?v=${VERSION} で一致`);
}

// ---- 2. 描画器の一致 ------------------------------------------------------
// 名前で関数を切り出し、空白の入れ方だけを無視して1文字ずつ比べる。
function extractFn(text, name) {
  const head = new RegExp(`\\bfunction\\s+${name}\\s*\\(`).exec(text);
  if (!head) return null;
  let i = text.indexOf("{", head.index);
  if (i < 0) return null;
  let depth = 0;
  for (let j = i; j < text.length; j++) {
    const c = text[j];
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return text.slice(head.index, j + 1); }
  }
  return null;
}
function normalize(s) { return s.replace(/\s+/g, " ").trim(); }

// transfer.js から写した関数の一覧。写す対象を増やしたらここにも足すこと。
const COPIED = [
  "newCanvas", "drawBlank",
  "hashSeed", "mulberry32",
  "revealPrepare", "revealBegin", "revealDraw",
  "blurBegin", "blurDraw",
  "wipeDraw", "fadeAlpha", "fadeDraw",
  "warpSeries", "seriesAt",
];
let same = 0;
for (const name of COPIED) {
  const a = extractFn(mainText, name);
  const b = extractFn(comfortText, name);
  if (!a) { bad(`transfer.js に ${name}() が無い(名前が変わった?)`); continue; }
  if (!b) { bad(`transfer_comfort.js に ${name}() が無い`); continue; }
  if (normalize(a) !== normalize(b)) {
    bad(`${name}() の中身が transfer.js と違う。**どちらかだけを直した疑い**。` +
        `群Bと群Cで違う絵を出すことになるので、両方をそろえること`);
  } else same++;
}
if (same === COPIED.length) ok(`描画器と進み方 ${same} 個が transfer.js と一字一句同じ`);

// RENDERERS の並び(方式名→描画器の対応)もそろっているか。
{
  const a = /const RENDERERS = \{[\s\S]*?\n\};/.exec(mainText);
  const b = /const RENDERERS = \{[\s\S]*?\n\};/.exec(comfortText);
  if (!a || !b) bad("RENDERERS の表を読み取れない");
  else if (normalize(a[0]) !== normalize(b[0])) bad("RENDERERS の表が transfer.js と違う");
  else ok("RENDERERS の表が transfer.js と同じ");
}

// ---- 3. 設定の筋 ----------------------------------------------------------
{
  const fams = Object.keys({ fade: 1, reveal: 1, blur: 1, wipe: 1 });
  for (const f of C.families) {
    if (fams.indexOf(f) < 0) bad(`transfer_comfort_config.js の families に知らない方式 "${f}" がある`);
    if (!CFG.visual.families[f]) bad(`transfer_config.js の visual.families に "${f}" の描画パラメータが無い`);
  }
  for (const ch of C.chars) {
    if (CFG.targets.indexOf(ch) < 0) {
      bad(`代表字 "${ch}" が transfer_config.js の targets に入っていない` +
          `(群Bで見せていない字を見え心地だけで聞くことになる)`);
    }
    const png = path.join(EXP, CFG.visual.base_dir, ch + ".png");
    if (!fs.existsSync(png)) bad(`代表字 "${ch}" の画像 ${path.relative(EXP, png)} が無い`);
  }
  const sample = (C.choice && C.choice.sample_char) || C.chars[0];
  if (C.chars.indexOf(sample) < 0) bad(`choice.sample_char "${sample}" が chars に入っていない`);
  const n = C.chars.length * C.families.length;
  ok(`提示は ${C.chars.length}字 × ${C.families.length}方式 = ${n}本` +
     `（7件法${C.items.length}項目 → ${n * C.items.length}回の回答 ＋ 最後の4択1問）`);
  // 所要のめやす。1本あたり12秒(初回だけ25秒)＋最後の4択40秒＋前置き90秒で見積もる。
  const est = 90 + 25 + (n - 1) * 12 + 40;
  ok(`所要のめやす: 約 ${Math.round(est / 60 * 10) / 10} 分（同意から完了コードまで）`);
}

// ---- まとめ ---------------------------------------------------------------
notes.forEach(m => console.log("  ok  " + m));
if (problems.length) {
  console.log("");
  problems.forEach(m => console.log("  NG  " + m));
  console.log(`\n不合格: ${problems.length} 件。掲載してはいけない。`);
  process.exit(1);
}
console.log("\n合格: 群Cのページは群Bと同じ絵を出す状態になっている。");
