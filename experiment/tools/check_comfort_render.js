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
  const known = { fade: 1, reveal: 1, blur: 1, wipe: 1 };
  for (const f of C.families) {
    if (!known[f]) bad(`transfer_comfort_config.js の families に知らない方式 "${f}" がある`);
    if (!CFG.visual.families[f]) bad(`transfer_config.js の visual.families に "${f}" の描画パラメータが無い`);
  }
  const chars = [...new Set([C.single_char].concat(C.sequence))];
  for (const ch of chars) {
    if (CFG.targets.indexOf(ch) < 0) {
      bad(`使う字 "${ch}" が transfer_config.js の targets に入っていない` +
          `(群Bで見せていない字を見え心地だけで聞くことになる)`);
    }
    const png = path.join(EXP, CFG.visual.base_dir, ch + ".png");
    if (!fs.existsSync(png)) bad(`"${ch}" の画像 ${path.relative(EXP, png)} が無い`);
  }
  const knownPres = { single: 1, row5: 1, swap5: 1 };
  for (const p of C.presentations) {
    if (!knownPres[p]) bad(`presentations に知らない提示のしかた "${p}" がある`);
    if (!C.presentation_labels[p]) bad(`presentation_labels に "${p}" の説明が無い`);
  }
  if (C.sequence.length < 2) bad("sequence が2字未満。5字続ける条件が作れない");
  for (const k of (C.choice.presentation.sample_options || [])) {
    if (C.presentations.indexOf(k) < 0) {
      bad(`最後の質問2の選択肢 "${k}" を、本編で1度も見せていない`);
    }
  }

  // ---- 間合いの検算 --------------------------------------------------------
  // 「前の字が現れきってから inter_char_gap_ms 空けて次が始まる」ようになっているか。
  // 視覚的マスキング（前後の刺激が互いの処理を邪魔する現象）が起きるのは、
  // 字と字の**開始どうしの間隔（SOA）が200ミリ秒以下**とされる。そこから十分
  // 離れていることを機械で確かめる（近づけると、見え心地ではなく干渉を測ってしまう）。
  const anim = CFG.visual.base_anim_ms;
  const gap = C.timing.inter_char_gap_ms;
  const soa = anim + gap;
  if (soa < 400) {
    bad(`字と字の開始の間隔(SOA)が ${soa}ms しかない。視覚的マスキングが起きる` +
        `時間帯(200ms以下)に近すぎる。inter_char_gap_ms を増やすこと`);
  } else {
    ok(`字と字の開始の間隔(SOA) ${soa}ms ＝ アニメ${anim}ms ＋ 空き${gap}ms` +
       `（干渉が起きる時間帯200ms以下の ${(soa / 200).toFixed(1)} 倍）`);
  }
  if (C.layout.gap_ratio < 1) {
    bad(`layout.gap_ratio が ${C.layout.gap_ratio}。横並びで字が近すぎる` +
        `（隣の字が邪魔をする crowding の対策として、字間は1文字分以上あける）`);
  } else {
    ok(`横並びの字間は文字幅の ${C.layout.gap_ratio} 倍（crowding 対策）`);
  }

  // ---- 本数と所要のめやす --------------------------------------------------
  const n = C.presentations.length * C.families.length;
  ok(`提示は ${C.families.length}方式 × ${C.presentations.length}通りの出し方 = ${n}本` +
     `（7件法${C.items.length}項目 → ${n * C.items.length}回の回答 ＋ 最後の2問）`);
  const cycSingle = anim + C.timing.single.hold_ms + C.timing.single.gap_ms;
  const cycSeq = C.sequence.length * soa + C.timing.sequence.hold_ms + C.timing.sequence.gap_ms;
  ok(`1周の長さ: 1字条件 ${(cycSingle / 1000).toFixed(1)}秒 ／ ` +
     `5字条件 ${(cycSeq / 1000).toFixed(1)}秒`);
  // 所要 = 前置き100秒 ＋ 1本目の慣れ15秒 ＋ 各本(1周見る時間 ＋ 回答12秒)
  //        ＋ 最後の2問70秒 ＋ 完了画面15秒。
  const nSingle = (C.presentations.indexOf("single") >= 0) ? C.families.length : 0;
  const nSeq = n - nSingle;
  const est = 100 + 15 + nSingle * (cycSingle / 1000 + 12) + nSeq * (cycSeq / 1000 + 12) + 70 + 15;
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
