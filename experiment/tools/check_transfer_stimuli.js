#!/usr/bin/env node
/* =========================================================================
 * 転写検証実験の聴覚刺激が「実験ページが要求するとおりに」揃っているかを見る
 * =========================================================================
 * 掲載の前に必ず通す。ブラウザを開かずに、次の4つを機械的に確かめる。
 *
 *   1. 入口HTMLの参照         … transfer_calib.html / transfer_test.html が読む
 *                                JS・CSS が実在し、キャッシュ避けの ?v= が
 *                                transfer.js の VERSION と一致しているか
 *   2. 索引と設定の整合       … transfer_audio_manifest.json に、設定の
 *                                打ち切り時刻表どおりの見出しが全部あるか
 *   3. 実験ページが引く見出し … 出題の組み立て(transfer.js)がありうる限り要求する
 *                                かな×時点の組合せが、1つ残らず索引にあるか
 *   4. 実物のWAV             … 索引の各ファイルが実在し、WAVヘッダから読んだ
 *                                長さが索引の dur_ms と合っているか
 *                                (dur_ms = 前置き lead_ms + 打ち切り gate_ms)
 *
 * 使い方:  node experiment/tools/check_transfer_stimuli.js
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
const CFG = global.window.TRANSFER_CONFIG;

// ---- 1. 入口HTMLの参照 ----------------------------------------------------
const jsText = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8");
const versionMatch = jsText.match(/const VERSION = "([^"]+)"/);
const VERSION = versionMatch ? versionMatch[1] : null;
if (!VERSION) bad("transfer.js から VERSION を読めない");

for (const page of ["transfer_calib.html", "transfer_test.html"]) {
  const html = fs.readFileSync(path.join(EXP, page), "utf8");
  const refs = [...html.matchAll(/(?:src|href)="([^"]+?)(?:\?v=([^"]*))?"/g)];
  let found = 0;
  for (const [, file, v] of refs) {
    if (/^https?:/.test(file)) continue;
    found++;
    if (!fs.existsSync(path.join(EXP, file))) bad(`${page}: ${file} が無い`);
    if (v !== undefined && v !== VERSION) {
      bad(`${page}: ${file} の ?v=${v} が transfer.js の VERSION=${VERSION} と違う`);
    }
  }
  if (found < 4) bad(`${page}: 読み込んでいるファイルが ${found} 個しかない(CSS+JS3本のはず)`);
  ok(`${page}: 参照 ${found} 件すべて実在・?v=${VERSION} で一致`);
}

// ---- 索引を読む -----------------------------------------------------------
const manifestPath = path.join(EXP, CFG.audio.manifest_url);
if (!fs.existsSync(manifestPath)) {
  bad(`${CFG.audio.manifest_url} が無い。build_transfer_gates.py を走らせること`);
  report();
}
const MAN = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const items = MAN.items || {};

if (MAN.config_version !== CFG.config_version) {
  bad(`索引を作ったときの設定版 ${MAN.config_version} が、今の設定 ${CFG.config_version} と違う`
      + "（刺激を作り直すか、設定を戻すこと）");
} else {
  ok(`設定版が索引と一致: ${CFG.config_version}`);
}
if (MAN.fade_out_ms !== CFG.audio.fade_out_ms) {
  bad(`終端フェード 索引 ${MAN.fade_out_ms}ms ≠ 設定 ${CFG.audio.fade_out_ms}ms`);
}
if (CFG.audio.fallback && CFG.audio.fallback.enabled) {
  bad("audio.fallback.enabled が true。索引が読めないとき合成音の代用モードで走ってしまう"
      + "（本番データを取る前に false にすること）");
} else {
  ok("代用モード(合成音への切り替え)は無効。索引が読めなければページはその場で止まる");
}

// ---- 実験ページと同じ導出 -------------------------------------------------
const ALL_KANA = CFG.answer_grid.flat().filter(c => c !== "");
const TARGETS = CFG.targets.slice();
const FILLERS = (CFG.fillers && CFG.fillers.length)
  ? CFG.fillers.slice() : ALL_KANA.filter(c => TARGETS.indexOf(c) < 0);
const gatesFor = (table, ch) => (table[ch] ? table[ch] : table._default).slice();
// 聴覚は下見だけ早い時点を足せる(audio.pilot_extra_gates)。実験ページと同じ規則で混ぜる。
function audioGates(ch) {
  const base = gatesFor(CFG.audio.gates_ms, ch);
  const ex = CFG.audio.pilot_extra_gates;
  if (!(ex && ex.enabled && ex.gate_ms && ex.gate_ms.length)) return base;
  return [...new Set([...base, ...ex.gate_ms])].sort((a, b) => a - b);
}
const key = (ch, g) => ch + "|" + (g === null ? "full" : String(g));

if (TARGETS.length !== 8) bad(`ターゲットが ${TARGETS.length} 字（8字のはず）`);
for (const ch of TARGETS) if (ALL_KANA.indexOf(ch) < 0) bad(`ターゲット ${ch} が回答のかな表に無い`);
for (const ch of CFG.wellbeing.chars) {
  if (TARGETS.indexOf(ch) < 0) bad(`見え心地の代表字 ${ch} がターゲット8字に入っていない`);
}
ok(`ターゲット ${TARGETS.join("・")} ／ まぎれ字 ${FILLERS.length} 字 ／ 回答は ${ALL_KANA.length} 択`);
ok(`見え心地の代表字 ${CFG.wellbeing.chars.join("・")}（ターゲット内から事前固定）`);

// ---- 2+3. 実験ページが引きうる見出しが全部あるか --------------------------
// buildAudioTrials(): ターゲット×その字の時点 ／ まぎれ字×_defaultの時点 ／
//   確認問題A=ターゲットの全長 ／ 確認問題C=**その字の最小の時点** ／ 練習=ターゲットの全長。
// playSample(): 音量確認で あ・い・う・え・お を全長で鳴らす。
// 2026-08-21 から時点は**字ごと**に置く(transfer_config.js の audio.gates_ms)。
// 字によって時点の数が違うので、件数の勘定も字ごとに足し上げる。
const defGates = audioGates("_default");
const want = new Set();
TARGETS.forEach(ch => {
  const g = audioGates(ch);
  g.forEach(v => want.add(key(ch, v)));
  want.add(key(ch, null));                       // 全長の水準・確認問題A・練習
  want.add(key(ch, Math.min(...g)));             // 確認問題C(その字の最小の時点)
});
FILLERS.forEach(ch => defGates.forEach(g => want.add(key(ch, g))));
["あ", "い", "う", "え", "お"].filter(c => ALL_KANA.indexOf(c) >= 0)
  .forEach(ch => want.add(key(ch, null)));       // 音量確認のサンプル

const missing = [...want].filter(k => !items[k]);
if (missing.length) bad(`索引に無い刺激 ${missing.length} 件: ${missing.slice(0, 12).join(", ")}…`);
else ok(`実験ページが引きうる ${want.size} 件の刺激がすべて索引にある`);

// 逆に、全かな × その字の時点 + 全長 が入っているか(まぎれ字の全長も playSample で要る)。
const expected = ALL_KANA.reduce((n, ch) => n + audioGates(ch).length + 1, 0);
if (Object.keys(items).length !== expected) {
  bad(`索引の件数 ${Object.keys(items).length} が、全 ${ALL_KANA.length} かな分の`
      + `「その字の時点 + 全長」の合計 ${expected} と違う`);
} else {
  const per = TARGETS.map(ch => `${ch}:${audioGates(ch).length}`).join(" ");
  ok(`索引の件数 ${expected} 件（まぎれ字は時点${defGates.length}＋全長／ターゲットは ${per}（各＋全長））`);
}

// 字ごとの配置が本当に字ごとに違うか（全字が同じ並びのままなら、変更が効いていない）。
{
  const sigs = new Set(TARGETS.map(ch => audioGates(ch).join(",")));
  if (sigs.size <= 1) {
    bad("ターゲット8字の時点がすべて同じ並び。字ごとの配置(2026-08-21の決定)が効いていない");
  } else {
    ok(`ターゲットの時点は ${sigs.size} 通りの配置に分かれている（字の音の種類ごと）`);
  }
}

// 1人あたりの聴覚の問題数（掲載文の分数の根拠。transfer.js の buildAudioTrials と同じ勘定）。
{
  const nTarget = TARGETS.reduce((n, ch) => n + audioGates(ch).length + (CFG.audio.include_full_gate ? 1 : 0), 0)
                  * (CFG.design.reps || 1);
  const nFiller = Math.round(nTarget * CFG.design.filler_ratio);
  const base = nTarget + nFiller;
  const nCheck = Math.round(base * CFG.design.check_full_rate) + Math.round(base * CFG.design.check_floor_rate);
  ok(`聴覚は1人あたり ${base + nCheck} 問（ターゲット${nTarget}＋まぎれ字${nFiller}＋確認問題${nCheck}）`);
}

// ---- 4. 実物のWAV ---------------------------------------------------------
function wavDurationMs(file) {
  const b = fs.readFileSync(file);
  if (b.toString("ascii", 0, 4) !== "RIFF" || b.toString("ascii", 8, 12) !== "WAVE") return null;
  let pos = 12, fmt = null, dataLen = null;
  while (pos + 8 <= b.length) {
    const id = b.toString("ascii", pos, pos + 4);
    const sz = b.readUInt32LE(pos + 4);
    if (id === "fmt ") {
      fmt = { ch: b.readUInt16LE(pos + 10), sr: b.readUInt32LE(pos + 12), bits: b.readUInt16LE(pos + 22) };
    } else if (id === "data") { dataLen = sz; }
    pos += 8 + sz + (sz % 2);
  }
  if (!fmt || dataLen === null) return null;
  const bytesPerFrame = fmt.ch * (fmt.bits / 8);
  return { ms: dataLen / bytesPerFrame / fmt.sr * 1000, sr: fmt.sr, ch: fmt.ch, bits: fmt.bits };
}

const dir = path.join(EXP, CFG.audio.stimuli_dir);
let checked = 0, worstMs = 0;
const seenFiles = new Set();
for (const [k, it] of Object.entries(items)) {
  const f = path.join(dir, it.file);
  if (seenFiles.has(it.file)) bad(`同じファイル名が2つの見出しに使われている: ${it.file}`);
  seenFiles.add(it.file);
  if (!fs.existsSync(f)) { bad(`${k}: ${it.file} が無い`); continue; }
  const w = wavDurationMs(f);
  if (!w) { bad(`${k}: ${it.file} を WAV として読めない`); continue; }
  if (w.ch !== 1 || w.bits !== 16) bad(`${k}: ${w.ch}ch/${w.bits}bit（モノラル16bitのはず）`);
  const d = Math.abs(w.ms - it.dur_ms);
  if (d > 0.05) bad(`${k}: 実際 ${w.ms.toFixed(2)}ms ≠ 索引 ${it.dur_ms}ms`);
  worstMs = Math.max(worstMs, d);
  // dur_ms = 前置き + 打ち切り。全長(gate_ms=null)は音源の残り全部なので照合しない。
  if (it.gate_ms !== null) {
    const wantMs = it.lead_ms + it.gate_ms;
    if (Math.abs(it.dur_ms - wantMs) > 0.05) {
      bad(`${k}: 全長 ${it.dur_ms}ms が 前置き${it.lead_ms}+打ち切り${it.gate_ms}=${wantMs}ms と合わない`);
    }
  }
  checked++;
}
const extra = fs.readdirSync(dir).filter(f => f.endsWith(".wav") && !seenFiles.has(f));
if (extra.length) bad(`索引に載っていない余分なWAV ${extra.length} 本: ${extra.slice(0, 5).join(", ")}…`);
ok(`WAV ${checked} 本を実測。索引との長さの食い違いは最大 ${worstMs.toFixed(3)}ms`);
ok(`前置き(onsetの手前に残した静かな区間)は ${MAN.lead_ms_actual_range[0]}〜${MAN.lead_ms_actual_range[1]}ms`
   + `（狙い ${MAN.lead_ms}ms。録音の余白がそれに満たない字はあるだけ付けてある）`);
const trunc = Object.entries(items).filter(([, v]) => v.truncated).map(([k]) => k);
if (trunc.length) bad(`音源が短くて指定の時点に届かない刺激 ${trunc.length} 件: ${trunc.slice(0, 8).join(", ")}`);
else ok("すべての字が最長の打ち切り時点まで音源が足りている(truncated なし)");

report();

function report() {
  console.log("── 確かめたこと ──");
  notes.forEach(n => console.log("  ✓ " + n));
  if (problems.length) {
    console.log("── 直すべきこと ──");
    problems.forEach(p => console.log("  ✗ " + p));
    console.log(`\n不合格: ${problems.length} 件。このまま掲載してはいけない。`);
    process.exit(1);
  }
  console.log("\n合格: 聴覚刺激は本番の構成で揃っている。");
  process.exit(0);
}
