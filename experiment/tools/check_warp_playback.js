#!/usr/bin/env node
/* =========================================================================
 * 生成した「進み方 s(t)」の表を、実験ページと同じコードで再生してみる
 * =========================================================================
 * build_transfer_warp.py が書いた表(transfer_warp.json)を、
 * **transfer.js の中の再生部分をそのまま切り出して**動かし、群Bの画面が
 * 意図どおりに進むかをブラウザ抜きで確かめる。
 *
 * 「同じ計算をこちらでも書く」のでは意味がない(書き写した先だけ正しくても、
 * 本番のページが直るわけではない)ので、transfer.js の本文から
 *   warpSeries / seriesAt / baseAnimMs / progressFn
 * の4つをテキストとして抜き出し、node の上で実行している。
 *
 * 見るところ
 *   1. 表の形     … frame_ms・数値列の長さ・値が 0〜1・単調非減少か
 *   2. 参照       … 実験ページが引く (方式, 字, 条件) が表にあるか。
 *                   無い組合せは代用の進み方に落ちる(記録の warp_source で分かる)
 *   3. 再生       … progressFn が "table" を返し、0ms・各打ち切り時刻・
 *                   数値列の終端より後、のそれぞれで正しい値を返すか
 *   4. 対照1の一致 … 表の baseline1 が、コード側の等速 t/base_anim_ms と合うか
 *   5. 打ち切り時点での進み具合の一覧(目で見て退化していないか確かめる)
 *
 * 使い方:
 *   node experiment/tools/check_warp_playback.js [表のJSON]
 *   （既定は experiment/transfer_warp.json）
 * 終了コード: 0=合格 / 1=不合格
 * ========================================================================= */
"use strict";
const fs = require("fs");
const path = require("path");

const EXP = path.resolve(__dirname, "..");
const tablePath = process.argv[2]
  ? path.resolve(process.cwd(), process.argv[2])
  : path.join(EXP, "transfer_warp.json");

const problems = [];
const notes = [];
const bad = (m) => problems.push(m);
const ok = (m) => notes.push(m);

// ---- 設定と表を読む -------------------------------------------------------
global.window = {};
require(path.join(EXP, "transfer_config.js"));
const CFG = global.window.TRANSFER_CONFIG;

if (!fs.existsSync(tablePath)) {
  console.error(`表が無い: ${tablePath}\n  先に build_transfer_warp.py を走らせること`);
  process.exit(1);
}
const TBL = JSON.parse(fs.readFileSync(tablePath, "utf8"));

// ---- transfer.js から再生部分だけを切り出す -------------------------------
const src = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8");
const begin = src.indexOf("let warpTables = null;");
const end = src.indexOf("function loadImage(");
if (begin < 0 || end < 0 || end <= begin) {
  bad("transfer.js から再生部分(warpTables 〜 progressFn)を切り出せない。"
      + "関数の並びが変わったなら、この切り出しの目印も直すこと");
  report();
}
const slice = src.slice(begin, end);
for (const name of ["function warpSeries", "function seriesAt", "function progressFn"]) {
  if (!slice.includes(name)) bad(`切り出した範囲に ${name} が入っていない`);
}
const make = new Function("CFG", "TABLES", slice
  + "\n warpTables = TABLES;"
  + "\n return { warpSeries, seriesAt, progressFn, get tables() { return warpTables; } };");
const P = make(CFG, TBL);
ok(`transfer.js から再生部分を切り出して実行できた（${slice.split("\n").length} 行）`);

// ---- 1. 表の形 ------------------------------------------------------------
const FRAME = 1000 / 60;
if (Math.abs(TBL.frame_ms - FRAME) > 0.01) {
  bad(`frame_ms=${TBL.frame_ms} が 60Hz(${FRAME.toFixed(3)}) と違う`);
} else {
  ok(`刻みは 60Hz（frame_ms=${TBL.frame_ms}）`);
}
const wantLen = Math.ceil(TBL.duration_ms / FRAME) + 1;
const combos = [];
for (const fam of Object.keys(TBL.tables || {})) {
  for (const ch of Object.keys(TBL.tables[fam])) {
    for (const cond of Object.keys(TBL.tables[fam][ch])) {
      combos.push([fam, ch, cond]);
      const a = TBL.tables[fam][ch][cond];
      if (a.length !== wantLen) bad(`${fam}|${ch}|${cond}: 数値列 ${a.length} 点（${wantLen} 点のはず）`);
      let prev = -1;
      for (let i = 0; i < a.length; i++) {
        if (!(a[i] >= 0 && a[i] <= 1)) { bad(`${fam}|${ch}|${cond}: ${i} 番目が 0〜1 の外（${a[i]}）`); break; }
        if (a[i] < prev - 1e-9) { bad(`${fam}|${ch}|${cond}: ${i} 番目で進み具合が戻っている`); break; }
        prev = a[i];
      }
    }
  }
}
ok(`表の中身: ${combos.length} 通り（方式×字×条件）・各 ${wantLen} 点`);

// ---- 2. 実験ページが引く組合せが表にあるか --------------------------------
// 群Bは「ターゲット8字 × 8条件」を参加者をまたいで全部出す(割付は連番で回る)。
// どのページが引くかは、表が自分で名乗る集団(meta.for_group)で決める。
//   既定 … 群B(transfer.html)。8字 × 12条件 = 96通り(組み合わせ方式を含む)
//   "c"  … 群C(transfer_comfort.html)。transfer_comfort_config.js の
//          使う字 × 見せる方式 × condition だけを引く。群Cは組み合わせ方式を
//          出さないので、そこまで要求すると通らない表を不合格にしてしまう。
//          ステップ表示("step")は表を引かず step_mid_ms を使うので数えない。
let WANT;                 // [{family, char, condition}, ...]
let wantWhat;
if (TBL.meta && TBL.meta.for_group === "c") {
  require(path.join(EXP, "transfer_comfort_config.js"));
  const CC = global.window.TRANSFER_COMFORT_CONFIG;
  const chars = Array.from(new Set([CC.single_char].concat(CC.sequence || [])));
  const fams = (CC.families || []).filter((f) => f !== "step");
  WANT = [];
  for (const ch of chars) for (const f of fams) WANT.push({ family: f, char: ch, condition: CC.condition });
  wantWhat = `群C(見え心地)のページが引きうる ${WANT.length} 通り`
    + `（${fams.length}方式 × ${chars.length}字 × ${CC.condition}）`;
  ok(`この表は群C用と名乗っている（meta.for_group="c"）ので、群Cの設定で見る`);
} else {
  WANT = [];
  for (const ch of CFG.targets) for (const c of CFG.conditions) {
    WANT.push({ family: c.family, char: ch, condition: c.condition });
  }
  wantWhat = `実験ページが引きうる ${WANT.length} 通り`;
}
const missing = [];
for (const w of WANT) {
  if (!P.warpSeries(w.family, w.char, w.condition)) missing.push(`${w.family}|${w.char}|${w.condition}`);
}
if (missing.length) {
  const msg = `${wantWhat} のうち ${missing.length} 通りが表に無い`
    + `（その問題は代用の進み方に落ちる: ${missing.slice(0, 4).join(", ")}${missing.length > 4 ? " …" : ""}）`;
  if (TBL.demo) ok("※ " + msg + " ← 試走用の表なので想定どおり");
  else bad(msg);
} else {
  ok(`${wantWhat} すべてが表にある`);
}

// ---- 3. 再生(progressFn) --------------------------------------------------
// 表にある組合せは "table" を返し、無い組合せは代用に落ちること。
for (const [fam, ch, cond] of combos) {
  const t = { play: "warp", family: fam, char: ch, condition: cond };
  const { fn, source } = P.progressFn(t);
  if (source !== "table") { bad(`${fam}|${ch}|${cond}: 表があるのに再生が ${source} になった`); continue; }
  const a = TBL.tables[fam][ch][cond];
  const at = (ms) => fn(ms);
  if (Math.abs(at(0) - a[0]) > 1e-9) bad(`${fam}|${ch}|${cond}: 0ms の値が数値列の先頭と違う`);
  if (Math.abs(at(-50) - a[0]) > 1e-9) bad(`${fam}|${ch}|${cond}: 負の時刻で先頭に丸まらない`);
  const last = a[a.length - 1];
  if (Math.abs(at(TBL.duration_ms + 500) - last) > 1e-9) bad(`${fam}|${ch}|${cond}: 終端より後で最後の値に留まらない`);
  // 枠と枠のあいだ(線形補間)。3枠目と4枠目のちょうど真ん中で確かめる。
  const mid = (a[3] + a[4]) / 2;
  if (Math.abs(at(3.5 * FRAME) - mid) > 1e-6) bad(`${fam}|${ch}|${cond}: 枠のあいだの補間が合わない`);
  let prev = -1, backs = 0;
  for (let ms = 0; ms <= TBL.duration_ms; ms += 1) { const v = at(ms); if (v < prev - 1e-9) backs++; prev = v; }
  if (backs) bad(`${fam}|${ch}|${cond}: 1ms 刻みで再生すると ${backs} 回さかのぼる`);
}
ok("再生: 表のある組合せはすべて数値列をなぞり、0ms・終端後・枠のあいだの値も期待どおり");

// 代用へ落ちる道(表に無い組合せ)。生成前や試走の表でも実験が止まらないことの確認。
{
  const t1 = P.progressFn({ play: "warp", family: "fade", char: "＠", condition: "proposed" });
  const t2 = P.progressFn({ play: "warp", family: "fade", char: "＠", condition: "baseline2" });
  const t3 = P.progressFn({ play: "calib", family: "fade", char: "あ", condition: "calib" });
  if (t1.source !== "linear") bad(`表に無い proposed が ${t1.source} に落ちた（linear のはず）`);
  if (t2.source !== "affine") bad(`表に無い baseline2 が ${t2.source} に落ちた（affine のはず）`);
  if (t3.source !== "linear") bad(`較正(等速)が ${t3.source} になった（linear のはず）`);
  ok("表に無い組合せは代用の進み方に落ちる（proposed→等速 / baseline2→1次変換 / 較正→等速）");
}

// ---- 4. 表の対照1が、コード側の等速と一致するか ---------------------------
for (const [fam, ch] of combos.filter(c => c[2] === "baseline1")) {
  const { fn } = P.progressFn({ play: "warp", family: fam, char: ch, condition: "baseline1" });
  for (const ms of [0, 100, 300, 600, 900]) {
    const want = Math.max(0, Math.min(1, ms / CFG.visual.base_anim_ms));
    if (Math.abs(fn(ms) - want) > 2e-4) {
      bad(`${fam}|${ch}|baseline1: ${ms}ms で ${fn(ms).toFixed(4)}（等速なら ${want.toFixed(4)}）`);
      break;
    }
  }
}
ok(`対照1(等速)は表とコードで一致（基準アニメ ${CFG.visual.base_anim_ms}ms）`);

// ---- 5. 打ち切り時点での進み具合の一覧 ------------------------------------
const gates = CFG.visual.gates_ms._default;
const lines = [];
lines.push("  " + "組合せ".padEnd(16) + gates.map(g => String(g).padStart(7)).join("") + "   ← 打ち切り時刻ms");
for (const fam of Object.keys(TBL.tables)) {
  for (const ch of Object.keys(TBL.tables[fam])) {
    for (const cond of ["proposed", "baseline2", "baseline1"]) {
      if (!TBL.tables[fam][ch][cond]) continue;
      const { fn } = P.progressFn({ play: "warp", family: fam, char: ch, condition: cond });
      const tag = `${fam}|${ch}|${cond.replace("baseline", "対照")}`;
      lines.push("  " + tag.padEnd(16) + gates.map(g => fn(g).toFixed(3).padStart(7)).join(""));
    }
  }
}

// ---- 報告 -----------------------------------------------------------------
function report() {
  console.log(`表: ${path.relative(process.cwd(), tablePath)}`
    + (TBL.demo ? `  ⚠ demo:true（tag=${TBL.tag || "-"}）` : ""));
  if (TBL.warning) console.log(`  ⚠ ${TBL.warning}`);
  notes.forEach(n => console.log("  ✓ " + n));
  if (lines.length > 1) {
    console.log("\n打ち切り時点での進み具合 s（0=何も出ていない / 1=完成）");
    lines.forEach(l => console.log(l));
  }
  if (problems.length) {
    console.log("\n✗ 不合格 " + problems.length + " 件");
    problems.forEach(p => console.log("  - " + p));
    process.exit(1);
  }
  console.log("\n✓ すべて合格");
  process.exit(0);
}
report();
