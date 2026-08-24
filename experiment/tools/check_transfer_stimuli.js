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
 *   5. 1人あたりの問題数     … transfer.js を実際に読み込んで出題を組み立てさせ、
 *                                その配列の長さを集団ごとに数える。掲載文に書く
 *                                分数と報酬の根拠になる数字なので、推定式では数えない
 *                                (2026-08-21 まで画面が推定式で「約91問」と出していて、
 *                                 実際の108/134/94問と最大43問ずれていた)
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

for (const page of ["transfer_calib.html", "transfer_calib_audio.html",
                    "transfer_calib_visual.html", "transfer_test.html"]) {
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

  // 集団を決め打ちしている入口ページ(2026-08-24 追加)は、その集団名が
  // 設定の phases に無いと**黙って振り分け版と同じ挙動になる**ので機械で見る。
  const pageDecl = html.match(/window\.TRANSFER_PAGE\s*=\s*\{([^}]*)\}/);
  const phaseM = pageDecl && pageDecl[1].match(/phase\s*:\s*"([^"]+)"/);
  const forceM = pageDecl && pageDecl[1].match(/force_group\s*:\s*"([^"]+)"/);
  if (forceM) {
    const ph = phaseM ? phaseM[1] : "";
    const list = (CFG.phases && CFG.phases[ph]) || [];
    if (list.indexOf(forceM[1]) < 0) {
      bad(`${page}: force_group "${forceM[1]}" が transfer_config.js の phases.${ph}`
          + `（${JSON.stringify(list)}）に無い。決め打ちが効かず振り分けになる`);
    } else {
      ok(`${page}: 集団を "${forceM[1]}" に決め打ち（phase=${ph}）`);
    }
  }
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
// decoy(偽のターゲット)の候補。実際に誰へどの字が出るかは transfer.js が連番から決める。
const DECOY_CFG = CFG.decoys || {};
const DECOY_POOL = (DECOY_CFG.pool && DECOY_CFG.pool.length)
  ? DECOY_CFG.pool.slice()
  : ALL_KANA.filter(c => TARGETS.indexOf(c) < 0 && ((DECOY_CFG.exclude || []).indexOf(c) < 0));
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
ok(`ターゲット ${TARGETS.join("・")} ／ decoy の候補 ${DECOY_POOL.length} 字`
   + `（除外 ${(DECOY_CFG.exclude || []).join("・") || "なし"}）／ 回答は ${ALL_KANA.length} 択`);
if (DECOY_POOL.length < 30) bad(`decoy の候補が ${DECOY_POOL.length} 字しかない（30字以上必要）`);
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
// decoy は候補59字のどれになるか分からないので、**候補全部**について
// 「その字の時点 + 全長 + いちばん早い時点」を要求する。
DECOY_POOL.forEach(ch => {
  const g = audioGates(ch);
  g.forEach(v => want.add(key(ch, v)));
  want.add(key(ch, null));
  want.add(key(ch, Math.min(...g)));
});
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

// ---- 5. 1人あたりの問題数 --------------------------------------------------
// 掲載文の分数と報酬の根拠になる数字なので、**推定式で数えない**。
// transfer.js を実際に読み込んで出題を組み立てさせ、その配列の長さを数える。
//
// なぜそこまでするか: 2026-08-21 まで、transfer.js の「課題の進め方」画面は
// 推定式で「約91問」と出していた。実際は聴覚108問・群A′134問・群B94問で、
// 最大43問ずれていた（式が①聴覚の全長の1点を数えていない ②群A′の水準を
// 取り違えている ③確認問題の割合をターゲットだけに掛けている の3点で古かった）。
// 式は必ずまた実装から遅れるので、**実物を走らせて数える**ことにした。
function countTrialsByRunningPage() {
  const vmMod = require("vm");
  function stubEl() {
    const el = {
      innerHTML: "", textContent: "", value: "", disabled: false, checked: false,
      style: {}, dataset: {}, parentElement: null,
      querySelector: () => null, querySelectorAll: () => [],
      addEventListener() {}, removeEventListener() {},
      appendChild() {}, remove() {}, insertAdjacentHTML() {},
      getContext: () => null, focus() {},
    };
    return el;
  }
  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    setTimeout, clearTimeout, setInterval, clearInterval,
    URLSearchParams, AbortController, performance,
    // 名簿にも刺激にも触らせない。fetch は必ず失敗させる
    // （失敗すれば require_server が効いて「お断り画面」で止まり、出題には進まない）。
    fetch: () => Promise.reject(new Error("harness: 通信しない")),
    requestAnimationFrame: () => 0,
    location: { search: "" },
    navigator: { userAgent: "node-harness", maxTouchPoints: 0 },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
      title: "",
      getElementById: () => stubEl(),
      createElement: () => stubEl(),
      querySelector: () => null,
      querySelectorAll: () => [],
    },
    devicePixelRatio: 1,
    screen: { width: 1280, height: 800 },
    addEventListener() {}, removeEventListener() {},
  };
  const out = {};
  // transfer.js は `const VERSION = …` のような宣言を持つので、**集団ごとに
  // まっさらな入れ物（context）で読み直す**（同じ入れ物に2回読むと二重宣言になる）。
  for (const [group, phase, nPeople] of [["acal", "calib", 80], ["aprime", "calib", 150],
                                         ["b", "test", 168]]) {
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.TRANSFER_PAGE = { phase };
    const ctx = vmMod.createContext(Object.assign({}, sandbox));
    ctx.window = ctx; ctx.globalThis = ctx;
    for (const f of ["transfer_config.js", "transfer_firestore.js"]) {
      vmMod.runInContext(fs.readFileSync(path.join(EXP, f), "utf8"), ctx, { filename: f });
    }
    const src = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8")
      // 実験ページと同じコードのまま、集団と連番だけ差し込んで組み立てさせる小窓を足す。
      // 画像を要求する視覚の出題も通るように、imgs には全かなの偽物を入れておく。
      + `\n;globalThis.__build = function (g, n) {
             GROUP = g; G = GROUPS[g]; ASSIGN = n; ASSIGN_SOURCE = "harness";
             _freqCache = null;
             ALL_KANA.forEach(c => { imgs[c] = imgs[c] || {}; });
             const t = (G.mode === "audio") ? buildAudioTrials() : buildVisualTrials();
             return { trials: t.map(x => ({ char: x.char, gate_ms: x.gate_ms === null ? "full" : x.gate_ms,
                                            progress_pct: x.progress_pct, family: x.family || "",
                                            condition: x.condition || "", base_anim_ms: x.base_anim_ms || 0,
                                            is_decoy: !!x.is_decoy, check_kind: x.check_kind || "" })),
                      decoys: decoyChars(), frequent: frequentChars(),
                      levels: (g === "aprime" ? progressLevels() : []) }; };`;
    vmMod.runInContext(src, ctx, { filename: "transfer.js" });
    const runs = [];
    for (let n = 0; n < nPeople; n++) runs.push(ctx.__build(group, n));
    const t0 = runs[0].trials;
    out[group] = {
      nPeople,
      total: t0.length,
      target: t0.filter(x => !x.is_decoy && !x.check_kind).length,
      decoy: t0.filter(x => x.is_decoy).length,
      check: t0.filter(x => x.check_kind).length,
      runs,
    };
  }
  return out;
}

{
  let counts = null;
  try { counts = countTrialsByRunningPage(); }
  catch (e) { bad(`transfer.js を読み込んで出題を数えられなかった: ${e.message}`); }
  if (counts) {
    const label = { acal: "聴覚(acal)", aprime: "視覚較正(aprime)", b: "視覚検証(b)" };
    for (const g of ["acal", "aprime", "b"]) {
      const c = counts[g];
      ok(`${label[g]} は1人あたり ${c.total} 問`
         + `（本命${c.target}＋decoy${c.decoy}＋確認問題${c.check}）`);
    }
    checkDesignBalance(counts);
    // 「課題の進め方」画面がこの数を出すこと。推定式に戻していないかを見る。
    const jsHasFormula = /問題数：約\$\{/.test(jsText);
    if (jsHasFormula) {
      bad("transfer.js の「進め方」画面が問題数を推定式で出している"
          + "（実際に組み立てた出題の長さを出すこと）");
    } else {
      ok("「課題の進め方」画面の問題数は、実際に組み立てた出題を数えて出している");
    }
    // 掲載は「フェーズごとに1本」なので、フェーズごとに出す。
    //   較正フェーズの掲載 = acal と aprime のどちらかに割り当たる（だから幅で書く）
    //   検証フェーズの掲載 = b だけ（2026-08-24 に atest を廃止したので幅は要らない）
    const span = (gs) => {
      const v = gs.map(g => counts[g].total);
      return (Math.min(...v) === Math.max(...v))
        ? `${v[0]}問` : `${Math.min(...v)}〜${Math.max(...v)}問`;
    };
    ok(`掲載文に書く問題数: 較正フェーズ 約${span(["acal", "aprime"])}`
       + "（集団によって違うので幅で書く） ／ "
       + `検証フェーズ ${span(["b"])}（群Bだけなので幅は無い）`);
  }
}

// ---- 6. 出題設計の検算（2026-08-24 の作り直しで追加） ----------------------
// 機械で確かめること:
//   (a) よく出る20字（本命8＋decoy12）の出現回数がそろっているか
//   (b) 1問目が確認問題A（全部提示）になっているか・その字が人によって変わるか
//   (c) 同じ字が近くで繰り返されていないか（design.min_same_char_gap）
//   (d) 本命のセル（字×測定点）が集団全体で均等に埋まるか
//   (e) decoy が候補59字に均等に配られるか
function checkDesignBalance(counts) {
  const gap = Number(CFG.design.min_same_char_gap) || 0;
  const label = { acal: "聴覚(acal)", aprime: "視覚較正(aprime)", b: "視覚検証(b)" };
  for (const g of ["acal", "aprime", "b"]) {
    const c = counts[g];
    const runs = c.runs;

    // (a) 頻度の均等性（確認問題を除いた本体）
    let freqBad = 0, freqSeen = new Set();
    runs.forEach(r => {
      const n = {};
      r.trials.filter(x => !x.check_kind).forEach(x => { n[x.char] = (n[x.char] || 0) + 1; });
      const vals = Object.values(n);
      vals.forEach(v => freqSeen.add(v));
      if (Object.keys(n).length !== r.frequent.length) freqBad++;
      if (vals.some(v => v !== vals[0])) freqBad++;
    });
    if (freqBad) bad(`${label[g]}: よく出る字の回数がそろっていない参加者が ${freqBad} 人`);
    else ok(`${label[g]}: よく出る ${runs[0].frequent.length} 字は全員が各 ${[...freqSeen].join("/")} 回`
            + "（確認問題を除く。**頻度から本命を見分けられない**）");

    // (b) 確認問題の位置がばらけているか（1問目に固定していないこと）
    const firstKinds = new Set(runs.map(r => r.trials[0].check_kind || "本題"));
    const posAll = [];
    runs.forEach(r => r.trials.forEach((x, i) => { if (x.check_kind === "full") posAll.push(i); }));
    const nCheckFull = runs[0].trials.filter(x => x.check_kind === "full").length;
    ok(`${label[g]}: 確認問題A は1人 ${nCheckFull} 問で、位置は ${Math.min(...posAll) + 1}〜`
       + `${Math.max(...posAll) + 1}問目に散る（1問目の中身は ${[...firstKinds].join("/")} の`
       + `${firstKinds.size} 通り＝固定していない）`);

    // (c) 同じ字の間隔
    let tooClose = 0;
    runs.forEach(r => {
      const last = {};
      r.trials.forEach((x, i) => {
        if (last[x.char] !== undefined && i - last[x.char] <= gap) tooClose++;
        last[x.char] = i;
      });
    });
    if (tooClose > runs.length * 0.02) {
      bad(`${label[g]}: 同じ字が ${gap} 問以内に再登場した回数 ${tooClose}（多すぎる）`);
    } else {
      ok(`${label[g]}: 同じ字は ${gap} 問以上あけて出る（${runs.length}人ぶんで例外 ${tooClose} 回）`);
    }

    // (d) 本命のセルの埋まり方（設計どおりのセルの単位で数える）
    const cellKey = {
      acal:   (x) => x.char + "|" + x.gate_ms,
      aprime: (x) => x.char + "|" + x.family + "|" + x.base_anim_ms + "|" + x.progress_pct,
      b:      (x) => x.char + "|" + x.family + "|" + x.condition + "|" + x.gate_ms,
    }[g];
    const poolKey = {
      acal:   (x) => x.gate_ms,                            // 8字を合計した1時点あたり
      aprime: (x) => x.family + "|" + x.progress_pct,      // 8字・2速度を合計
      b:      (x) => x.family + "|" + x.condition + "|" + x.gate_ms,  // 8字を合計（距離Eを測る単位）
    }[g];
    const cell = {}, pool = {};
    runs.forEach(r => r.trials.filter(x => !x.is_decoy && !x.check_kind).forEach(x => {
      const k = cellKey(x); cell[k] = (cell[k] || 0) + 1;
      const q = poolKey(x); pool[q] = (pool[q] || 0) + 1;
    }));
    const cv = Object.values(cell), pv = Object.values(pool);
    const avg = (a) => (a.reduce((x, y) => x + y, 0) / a.length).toFixed(1);
    ok(`${label[g]}: ${c.nPeople}人で本命のセルは ${cv.length} 通り・1セル `
       + `${Math.min(...cv)}〜${Math.max(...cv)}回答（平均 ${avg(cv)}）`
       + (g === "aprime" ? "（水準は人ごとにずれるので、名目の水準ではなく実際の値で数えている）" : ""));
    if (g === "aprime") {
      // 名目の水準（薄い側1〜3番目・20%・100%）で数え直す。計画書の「1セル○回答」はこの単位。
      const nom = {};
      runs.forEach(r => r.trials.filter(x => !x.is_decoy && !x.check_kind).forEach(x => {
        const li = r.levels.indexOf(x.progress_pct);
        const k = x.char + "|" + x.family + "|" + x.base_anim_ms + "|L" + li;
        nom[k] = (nom[k] || 0) + 1;
      }));
      const nv = Object.values(nom);
      ok(`${label[g]}: 名目の水準で数えると ${nv.length} セル・1セル ${Math.min(...nv)}〜${Math.max(...nv)}回答`
         + `（平均 ${avg(nv)}）`);
    }
    ok(`${label[g]}: まとめた単位（${g === "acal" ? "1時点あたり・8字合計"
        : g === "aprime" ? "1方式×1水準あたり・8字と2速度を合計" : "1条件×1時点あたり・8字合計"}）は `
       + `${pv.length} 通り・${Math.min(...pv)}〜${Math.max(...pv)}回答（平均 ${avg(pv)}）`);

    // (d2) **偽のターゲットの出方が本命と似ているか**（2026-08-24 追加）
    // 「偽物だけ簡単」「偽物だけ特定の方式に偏る」ことが無いかを、分布の差で見る。
    //   ・提示の強さ … その字の測定点の何番目か（0=いちばん情報が少ない）で数える。
    //     字によって時点の実数値は違うので、**順位**でそろえて比べる
    //   ・視覚は方式・速さ・水準の分布も比べる
    {
      const rankOf = (x, r) => {
        if (g === "aprime") return r.levels.indexOf(x.progress_pct);
        const list = (g === "acal")
          ? audioGates(x.char).concat(["full"])
          : gatesFor(CFG.visual.gates_ms, x.char);
        return list.map(String).indexOf(String(x.gate_ms));
      };
      const dist = (pred, key) => {
        const d = {}; let n = 0;
        runs.forEach(r => r.trials.filter(x => !x.check_kind && pred(x)).forEach(x => {
          const k = key(x, r); d[k] = (d[k] || 0) + 1; n++;
        }));
        Object.keys(d).forEach(k => { d[k] = d[k] / n; });
        return d;
      };
      const gapPP = (a, b) => {
        const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
        let worst = 0, at = "";
        keys.forEach(k => { const v = Math.abs((a[k] || 0) - (b[k] || 0)) * 100;
                            if (v > worst) { worst = v; at = k; } });
        return { worst, at };
      };
      const cmp = (name, key) => {
        const t = dist(x => !x.is_decoy, key);
        const d = dist(x => x.is_decoy, key);
        const { worst, at } = gapPP(t, d);
        const msg = `${label[g]}: 本命と偽のターゲットの「${name}」の分布のずれは最大 `
                  + `${worst.toFixed(1)} 割合ポイント（${at}）`;
        if (worst > 5) bad(msg + " ← 5ポイントを超えている。偏りを直すこと");
        else ok(msg);
      };
      cmp("提示の強さ（その字の測定点の何番目か）", (x, r) => "第" + (rankOf(x, r) + 1) + "点");
      if (g !== "acal") {
        cmp("方式", (x) => x.family);
        if (g === "aprime") cmp("速さ", (x) => x.base_anim_ms + "ms");
        else cmp("条件", (x) => x.condition);
      }
    }

    // (e) decoy の配られ方
    const use = {};
    runs.forEach(r => r.decoys.forEach(ch => { use[ch] = (use[ch] || 0) + 1; }));
    const uv = Object.values(use);
    const nUsed = Object.keys(use).length;
    if (nUsed !== DECOY_POOL.length) {
      bad(`${label[g]}: decoy に使われた字が ${nUsed} 字（候補 ${DECOY_POOL.length} 字を使い切っていない）`);
    } else {
      ok(`${label[g]}: decoy は候補 ${nUsed} 字すべてに配られ、1字あたり `
         + `${Math.min(...uv)}〜${Math.max(...uv)}人（${c.nPeople}人ぶん）`);
    }
    // 本命字が decoy に混ざっていないこと
    if (runs.some(r => r.decoys.some(ch => TARGETS.indexOf(ch) >= 0))) {
      bad(`${label[g]}: decoy に本命字が混ざっている`);
    }
  }
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
