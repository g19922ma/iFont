// =========================================================================
// 見え心地の評価（群C）v c1.0   入口: transfer_comfort.html
//   計画書: project/実験計画書_転写検証.md（3章 RQ3 と 4.5）
//   設定:   experiment/transfer_comfort_config.js（群Cだけの手続き）
//           experiment/transfer_config.js（描画のパラメータと保存先。**読むだけ**）
//
//   ■ 何をする実験か
//   生成した文字アニメーション4方式（フェード・部分表示・ぼかし解除・ワイプ）を、
//   **打ち切らずに繰り返し**流し、「字幕として続けて見ていられるか」を7件法で聞く。
//   かなを当てる課題は一切通らない。所要は代表字2字×4方式＝8本でおよそ4分。
//
//   ■ もとの実装との関係
//   2026-08-21 まで、この評価は transfer.js の中で群B（検証・視覚）の識別課題が
//   全部終わったあとに続けて行っていた。それを独立の実験に切り出したのがこのファイルである。
//   切り出しにあたって変えたのは次の3点。
//     1. 識別課題を通らない（疲れと印象が混ざらない）
//     2. アニメを1回で止めず、評価しているあいだ繰り返し流す（字幕の実態に近い）
//     3. 自動再生の回数と「もう一度みる」を押した回数を別々に数える
//
//   ■ transfer.js を読み込まない理由
//   transfer.js は読み込まれた時点で較正／検証フェーズの手続き（名簿の問い合わせ →
//   同意 → 識別課題）を自分で走らせるので、このページに載せると別の実験が始まってしまう。
//   そこで、4方式の描画器と進み方の補間だけを **transfer.js から一字一句そのまま写して**
//   いる。写した関数は下の「描画器」「進み方」の節にまとめ、
//   experiment/tools/check_comfort_render.js が両者の食い違いを機械的に見つける。
//   **描画器を直すときは必ず両方を直し、このチェックを通すこと**（片方だけ直すと、
//   群Bと群Cで違う絵を見せていることになり、2つの結果を並べて論じられなくなる）。
// =========================================================================
"use strict";

const VERSION = "c1.0";
const CFG = window.TRANSFER_CONFIG;            // 共用（描画・保存先）。書き換えない。
const C = window.TRANSFER_COMFORT_CONFIG;      // 群Cだけの設定
const P = new URLSearchParams(location.search);

const PHASE = (C.roster && C.roster.phase) || "comfort";
const GROUP = (C.roster && C.roster.group) || "c";
const SESSION_V = 1;                           // 途中データの互換版。構造を変えたら上げる。

let ASSIGN = 0;               // 名簿がくれた連番（提示順の記録に添える）
let ASSIGN_SOURCE = "";       // "server" | "cache" | "local_hash" | "forced"

const screenEl = document.getElementById("screen");

// ---- 小道具 ---------------------------------------------------------------
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function backoffMs(cfg, i) {
  const d = (cfg && cfg.delays_ms) || [800, 2000, 4000];
  const base = d[Math.min(i, d.length - 1)] || 800;
  return base + Math.random() * ((cfg && cfg.jitter_ms) || 0);
}
function hashIndexFrom(pid) {
  let h = 0;
  for (let i = 0; i < pid.length; i++) h = (h * 31 + pid.charCodeAt(i)) >>> 0;
  return h % 1000;
}

// =========================================================================
// 名簿（サーバ）への問い合わせ
//   聞くのは2つだけ。「この人は他のフェーズに出ていないか」と「この集団で何番目か」。
//   群Cは集団が1つなので、振り分けの仕事は無い。
//   ⚠ サーバはまだ phase="comfort" を知らない（transfer_comfort_config.js の注記）。
//     知らないうちは {"status":"error"} が返り、require_server が true なら
//     お断り画面になる。掲載前チェックリスト H-1 でサーバ側を先に直すこと。
// =========================================================================
const ROSTER = (CFG.roster || {});
function assignCacheKey(pid) { return "ifont_transfer_assign_" + PHASE + "_" + pid; }
function readAssignCache(pid) {
  try { return JSON.parse(localStorage.getItem(assignCacheKey(pid)) || "null"); } catch (e) { return null; }
}
function writeAssignCache(pid, obj) {
  try { localStorage.setItem(assignCacheKey(pid), JSON.stringify(obj)); } catch (e) {}
}

// 1回ぶんの問い合わせ。戻り値は3通り。
//   {kind:"ok", j} / {kind:"blocked", reason} / {kind:"fail", why}
// JSON でない応答（GAS が一過性でHTMLのエラーページを返すことがある）も失敗に数える。
async function rosterQueryOnce(pid) {
  const base = ROSTER.status_url;
  const url = base + (base.indexOf("?") >= 0 ? "&" : "?") +
    "action=transfer_status&phase=" + encodeURIComponent(PHASE) +
    "&participant_id=" + encodeURIComponent(pid) +
    "&worker_id=" + encodeURIComponent((window.PROD && PROD.workerId) || "");
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ROSTER.timeout_ms || 15000);
  let r;
  try {
    r = await fetch(url, { signal: ctl.signal, cache: "no-store" });
  } catch (e) {
    return { kind: "fail", why: "通信できない: " + (e && e.message) };
  } finally {
    clearTimeout(timer);
  }
  if (!r.ok) return { kind: "fail", why: "HTTP " + r.status };
  let text;
  try { text = await r.text(); } catch (e) { return { kind: "fail", why: "本文を読めない" }; }
  let j;
  try { j = JSON.parse(text); } catch (e) {
    return { kind: "fail", why: "JSONでない応答(" + text.slice(0, 40).replace(/\s+/g, " ") + "…)" };
  }
  if (j && j.blocked) return { kind: "blocked", reason: j.reason || "already_participated" };
  if (j && j.group === GROUP) return { kind: "ok", j: j };
  // ここに来るのは、たいてい「サーバが comfort フェーズを知らない」場合である。
  return { kind: "fail", why: "集団が読み取れない応答(サーバが " + PHASE + " を知らない可能性)" };
}

let rosterLastWhy = "";
let onRosterRetry = null;

async function resolveAssignment() {
  const pid = (window.PROD && PROD.participantId) || "anon";
  const researcher = !(window.PROD && PROD.enabled);

  // 研究者モードだけ、連番を URL で強制できる（?pnum=3）。名簿を通さず素通りする。
  if (researcher && P.has("pnum")) {
    const pn = Number(P.get("pnum"));
    return { assign_index: Number.isFinite(pn) ? Math.abs(Math.trunc(pn)) : 0, source: "forced" };
  }
  const cached = readAssignCache(pid);
  if (cached && typeof cached.assign_index === "number") {
    return { assign_index: cached.assign_index, source: "cache" };
  }
  if (ROSTER.status_url) {
    const rc = ROSTER.retry || {};
    const attempts = Math.max(1, Number(rc.attempts) || 1);
    rosterLastWhy = "";
    for (let i = 0; i < attempts; i++) {
      if (i > 0) await sleep(backoffMs(rc, i - 1));
      if (i > 0 && typeof onRosterRetry === "function") onRosterRetry(i + 1, attempts);
      const res = await rosterQueryOnce(pid);
      if (res.kind === "ok") {
        const a = { assign_index: Number(res.j.assign_index) || 0 };
        writeAssignCache(pid, a);
        return Object.assign(a, { source: i > 0 ? "server:retry" + (i + 1) : "server" });
      }
      if (res.kind === "blocked") return { blocked: true, reason: res.reason };
      rosterLastWhy = res.why;
      console.warn(`[comfort] 名簿サーバへの問い合わせ ${i + 1}/${attempts} 回目が失敗: ${res.why}`);
    }
    if (C.roster && C.roster.require_server) {
      return { blocked: true, reason: "server_unavailable", why: rosterLastWhy, tries: attempts };
    }
  }
  const a = { assign_index: hashIndexFrom(pid) };
  writeAssignCache(pid, a);
  return Object.assign(a, { source: "local_hash" });
}

// ---- 端末環境 (解析用にログ) ----------------------------------------------
const ENV = {
  ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
  screen: `${window.screen.width}x${window.screen.height}`,
  touch: (navigator.maxTouchPoints || 0) > 0, refreshHz: null,
};
(function measureRefresh() {
  let n = 0; const t0 = performance.now();
  function f(now) { n++; if (n < 40) requestAnimationFrame(f); else ENV.refreshHz = Math.round(1000 / ((now - t0) / n)); }
  requestAnimationFrame(f);
})();
if (window.PROD) PROD.setEnv(ENV);

// ---- 記録の封筒 -----------------------------------------------------------
// 形は transfer.js と同じにそろえる（GAS 側の列がそのまま埋まるため）。
// 保存先URLと再送の設定は transfer_config.js の logging をそのまま借りる。
let resumeMeta = { count: 0, gapS: 0 };

function serverBody(body) {
  return Object.assign({
    participant_id: (window.PROD && PROD.participantId) || "",
    worker_id: (window.PROD && PROD.workerId) || "",
    completion_code: (window.PROD && PROD.completionCode) || "",
    ts: Date.now(),
    audio_device: "",
    resume_count: resumeMeta.count,
    resume_gap_s: resumeMeta.gapS,
    ua: ENV.ua, dpr: ENV.dpr, screen: ENV.screen, touch: !!ENV.touch,
    refresh_hz: (ENV.refreshHz != null) ? ENV.refreshHz : "",
  }, body);
}

async function postRecord(url, envelope) {
  const rc = (CFG.logging && CFG.logging.retry) || {};
  const attempts = Math.max(1, Number(rc.attempts) || 1);
  const body = JSON.stringify(envelope);
  for (let i = 0; i < attempts; i++) {
    if (i > 0) await sleep(backoffMs(rc, i - 1));
    try {
      await fetch(url, {
        method: "POST", mode: "no-cors",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: body,
      });
      return true;
    } catch (e) {
      console.warn(`[comfort] 記録の送信 ${i + 1}/${attempts} 回目が失敗:`, e && e.message);
    }
  }
  console.error(`[comfort] 記録を ${attempts} 回試して送れませんでした`);
  return false;
}

function sendRecord(body) {
  if (!(window.PROD && PROD.enabled)) return;
  const url = (CFG.logging && CFG.logging.submit_url) || "";
  if (!url) { console.warn("[comfort] logging.submit_url が空なので記録が残りません"); return; }
  postRecord(url, serverBody(body));
}

// =========================================================================
// 視覚: 4方式の描画器
//   ⚠ **transfer.js から写したもの。直すときは両方を直す**
//     （experiment/tools/check_comfort_render.js が食い違いを見つける）。
//   どれも「進み具合 s∈[0,1] を渡すと1フレーム描く」という同じ形にそろえてある。
// =========================================================================
const SIZE = CFG.visual.size_px;
const imgs = {};           // かな → Image (base/<かな>.png)

function newCanvas() {
  const c = document.createElement("canvas");
  c.id = "stim"; c.width = SIZE; c.height = SIZE;
  c.style.background = "#fff"; c.style.border = "1px solid #ddd";
  c.style.display = "block"; c.style.margin = "0 auto";
  return c;
}
function drawBlank(ctx) { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, SIZE, SIZE); }

function hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const revealOrder = {};    // かな → Uint32Array (画素の並び。値は画素の通し番号)
function revealPrepare(ch) {
  if (revealOrder[ch]) return revealOrder[ch];
  const off = document.createElement("canvas"); off.width = SIZE; off.height = SIZE;
  const octx = off.getContext("2d", { willReadFrequently: true });
  octx.fillStyle = "#fff"; octx.fillRect(0, 0, SIZE, SIZE);
  if (imgs[ch]) octx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
  const px = octx.getImageData(0, 0, SIZE, SIZE).data;
  const th = CFG.visual.families.reveal.ink_threshold;
  const idx = [];
  for (let i = 0; i < SIZE * SIZE; i++) {
    // 輝度 ≤ しきい値 の画素を「ストローク画素」とみなす(既存資産と同じ判定)。
    const lum = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2];
    if (lum <= th) idx.push(i);
  }
  const rnd = mulberry32(hashSeed(CFG.visual.families.reveal.seed_prefix + ch));
  for (let i = idx.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1)); const t = idx[i]; idx[i] = idx[j]; idx[j] = t;
  }
  revealOrder[ch] = Uint32Array.from(idx);
  return revealOrder[ch];
}

// 描画のたびに全画素を書き直すと重いので、1試行のあいだは同じ ImageData を使い、
// 増えたぶんの画素だけ黒く塗る(s は試行内で単調に増えるため)。
const revealState = { ch: null, shown: 0, img: null };
function revealBegin(ch, ctx) {
  revealPrepare(ch);
  revealState.ch = ch; revealState.shown = 0;
  revealState.img = ctx.createImageData(SIZE, SIZE);
  revealState.img.data.fill(255);
}
function revealDraw(ctx, ch, s) {
  if (revealState.ch !== ch || revealState.img === null) revealBegin(ch, ctx);
  const order = revealOrder[ch];
  const want = Math.round(order.length * Math.max(0, Math.min(1, s)));
  const d = revealState.img.data;
  if (want < revealState.shown) {           // 戻る場合(練習の再生など)は塗り直す
    d.fill(255); revealState.shown = 0;
  }
  for (let i = revealState.shown; i < want; i++) {
    const p = order[i] * 4;
    d[p] = 0; d[p + 1] = 0; d[p + 2] = 0; d[p + 3] = 255;
  }
  revealState.shown = want;
  ctx.putImageData(revealState.img, 0, 0);
}

// ぼかし解除(blur): ガウスぼかしの半径を単調に減らす。s=0 で最大、s=1 で鮮明。
let blurOff = null, blurOffCtx = null;
function blurBegin(ch) {
  if (!blurOff) {
    blurOff = document.createElement("canvas"); blurOff.width = SIZE; blurOff.height = SIZE;
    blurOffCtx = blurOff.getContext("2d");
  }
  blurOffCtx.fillStyle = "#fff"; blurOffCtx.fillRect(0, 0, SIZE, SIZE);
  if (imgs[ch]) blurOffCtx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
}
function blurDraw(ctx, ch, s) {
  if (!blurOff) blurBegin(ch);
  const r = CFG.visual.families.blur.max_radius_px * (1 - Math.max(0, Math.min(1, s)));
  drawBlank(ctx);
  ctx.save();
  ctx.filter = r > 0.01 ? `blur(${r.toFixed(2)}px)` : "none";
  ctx.drawImage(blurOff, 0, 0, SIZE, SIZE);
  ctx.restore();
  ctx.filter = "none";
}

// ワイプ(wipe): 見せる領域を端から単調に広げる。向きは設定で変えられる。
function wipeDraw(ctx, ch, s) {
  const p = Math.max(0, Math.min(1, s));
  drawBlank(ctx);
  if (!imgs[ch] || p <= 0) return;
  const dir = CFG.visual.families.wipe.direction || "ltr";
  const w = SIZE * p, h = SIZE * p;
  ctx.save();
  ctx.beginPath();
  if (dir === "ltr") ctx.rect(0, 0, w, SIZE);
  else if (dir === "rtl") ctx.rect(SIZE - w, 0, w, SIZE);
  else if (dir === "ttb") ctx.rect(0, 0, SIZE, h);
  else ctx.rect(0, SIZE - h, SIZE, h);
  ctx.clip();
  ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
  ctx.restore();
}

// フェード(fade): 不透明度 = s^gamma。
function fadeAlpha(s) {
  const g = (CFG.visual.families.fade && CFG.visual.families.fade.gamma);
  const t = Math.max(0, Math.min(1, s));
  // gamma が無い/1.0 のときは、余計な計算を挟まず s をそのまま使う。
  if (!(typeof g === "number") || g === 1) return t;
  return Math.pow(t, g);
}
function fadeDraw(ctx, ch, s) {
  drawBlank(ctx);
  if (!imgs[ch]) return;
  ctx.globalAlpha = fadeAlpha(s);
  ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
  ctx.globalAlpha = 1;
}

const RENDERERS = {
  fade:   { begin: () => {},                     draw: fadeDraw },
  reveal: { begin: (ch, ctx) => revealBegin(ch, ctx), draw: revealDraw },
  blur:   { begin: (ch) => blurBegin(ch),        draw: blurDraw },
  wipe:   { begin: () => {},                     draw: wipeDraw },
};

// =========================================================================
// 視覚: 進み方 s(t)
//   生成した数値列(60Hz)を線形補間してなぞる。表が無ければ等速で代用する。
//   ⚠ warpSeries / seriesAt は transfer.js から写したもの（上と同じ注意）。
// =========================================================================
let warpTables = null;      // {frame_ms, tables: {family: {char: {condition: [s,...]}}}}

function warpSeries(family, ch, condition) {
  if (!warpTables || !warpTables.tables) return null;
  const f = warpTables.tables[family];
  if (!f || !f[ch]) return null;
  const s = f[ch][condition];
  return (Array.isArray(s) && s.length) ? s : null;
}
function seriesAt(series, frameMs, tMs) {
  if (tMs <= 0) return series[0];
  const x = tMs / frameMs;
  const i = Math.floor(x);
  if (i >= series.length - 1) return series[series.length - 1];
  const f = x - i;
  return series[i] * (1 - f) + series[i + 1] * f;
}

// 1本ぶんの「経過時間ms → 進み具合 s」と、その1本の長さ(ms)を作る。
// 返り値: {fn, dur_ms, source}  source は記録用("table" / "linear")。
function progressFor(family, ch) {
  const base = CFG.visual.base_anim_ms;
  if (C.condition !== "linear") {
    const series = warpSeries(family, ch, C.condition);
    if (series) {
      const frameMs = (warpTables && warpTables.frame_ms) || (1000 / 60);
      return {
        fn: (ms) => Math.max(0, Math.min(1, seriesAt(series, frameMs, ms))),
        dur_ms: Math.round((series.length - 1) * frameMs),
        source: "table",
      };
    }
  }
  return { fn: (ms) => Math.max(0, Math.min(1, ms / base)), dur_ms: base, source: "linear" };
}

// =========================================================================
// 読み込み
// =========================================================================
function loadImage(ch) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error(`${CFG.visual.base_dir}/${ch}.png の読込に失敗`));
    im.src = `${CFG.visual.base_dir}/${encodeURIComponent(ch)}.png`;
  });
}

function sampleChar() {
  return (C.choice && C.choice.sample_char) || C.chars[0];
}

async function preload() {
  screenEl.innerHTML = `<div style="min-height:60vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">読み込み中…</h1>
    <div style="width:min(320px,80%);height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden;margin-top:10px">
      <div id="loadBar" style="height:100%;width:0%;background:#2E7D8F"></div></div></div>`;
  const setBar = (p) => { const b = document.getElementById("loadBar"); if (b) b.style.width = Math.round(p * 100) + "%"; };

  // この実験で画面に出る字だけを読む（見え方の確認に使う「あ」を含む）。
  const need = [...new Set(C.chars.concat([sampleChar(), "あ"]))];
  let done = 0;
  await Promise.all(need.map(async ch => {
    try { imgs[ch] = await loadImage(ch); } catch (e) { console.warn("[comfort]", e.message); }
    done++; setBar(0.6 * done / need.length);
  }));
  if (!C.chars.every(ch => imgs[ch])) throw new Error("代表字の画像が読めません");

  // 生成した進み方の表。無ければ等速で代用する（研究者の動作確認のとき）。
  if (C.condition !== "linear") {
    try {
      const r = await fetch(CFG.visual.warp.tables_url, { cache: "no-store" });
      if (r.ok) warpTables = await r.json();
    } catch (e) { /* 表が無ければ等速 */ }
    if (!warpTables) console.warn("[comfort] " + CFG.visual.warp.tables_url + " が無いので等速で動かします");
  }
  setBar(1);
}

// =========================================================================
// 提示の組み立て
//   代表字 × 4方式 のすべての組を作り、**方式も字も混ぜて**並べる。
//   何番目に出したかは order 列として記録に残す（順序の効果を後から見るため）。
// =========================================================================
function buildClips() {
  const out = [];
  C.chars.forEach(ch => C.families.forEach(fam => out.push({ char: ch, family: fam })));
  return shuffle(out).map((c, i) => Object.assign(c, { order: i + 1 }));
}

// =========================================================================
// 画面
// =========================================================================
let clips = [], idx = 0;
let answers = null;                 // {clips:[...], choice:"", choice_order:[...]}
let elapsedPrior = 0;
const T0 = Date.now();

// いま動いている再生を止める（画面を切り替える前に必ず呼ぶ）。
let stopPlayback = null;
function stopAnim() { if (stopPlayback) { stopPlayback(); stopPlayback = null; } }

function saveProgress() {
  if (window.PROD && PROD.enabled) PROD.saveState("transfer_" + PHASE, {
    session_v: SESSION_V, phase: PHASE, group: GROUP,
    clips, idx, answers, assign: ASSIGN,
    elapsed_s: Math.round(elapsedPrior + (Date.now() - T0) / 1000),
  });
}

// ---- 説明 -----------------------------------------------------------------
function intro() {
  const n = clips.length;
  screenEl.innerHTML = `<h1>このアンケートの進め方</h1>
    <p>文字が現れる様子を<b>${n}通り</b>、順にお見せします。
    それぞれについて、<b>「字幕として続けて見ていられるか」</b>を7段階で答えてください。</p>
    <ul style="font-size:14px;line-height:1.9;color:#333">
      <li><b>当てる課題ではありません。</b>正解・不正解はありません。感じたとおりに答えてください。</li>
      <li>1つの表示は<b>くりかえし流れつづけます</b>。答えているあいだ、何度でも見ていられます。</li>
      <li>「▶ もう一度みる」を押すと、その場で最初から流し直せます。</li>
      <li>最後に、4つの表示のうちどれを普段使いたいかを1問だけうかがいます。</li>
    </ul>
    <p style="text-align:center;margin-top:18px"><button class="primary" id="go">始める</button></p>
    <p class="muted" style="text-align:right;font-size:12px;margin-top:6px">${(window.PROD && PROD.enabled)
      ? "津田塾大学 栗原研究室"
      : `研究者向け動作確認 v${VERSION} ／ ${PHASE}フェーズ 集団 ${GROUP}（割り当て: ${ASSIGN_SOURCE}） ／ 割付番号 ${ASSIGN}${warpTables ? "" : " ／ <b>進み方の表が無いので等速</b>"}`}</p>`;
  document.getElementById("go").onclick = () => { showClip(); };
}

// ---- 1本ぶん: 繰り返し再生 ＋ 7件法3項目 ----------------------------------
function showClip() {
  stopAnim();
  if (idx >= clips.length) return showChoice();
  const clip = clips[idx];
  const prog = progressFor(clip.family, clip.char);
  const renderer = RENDERERS[clip.family] || RENDERERS.fade;
  const shownAt = Date.now();

  screenEl.innerHTML = `<div class="muted">見え心地の質問（${idx + 1} / ${clips.length}）</div>
    <div id="vbox" class="vbox"></div>
    <div style="text-align:center;margin:6px 0 10px">
      ${C.allow_replay ? `<button id="again" style="font-size:15px;padding:10px 24px;border-radius:999px;border:2px solid #1E2A5E;background:#fff;color:#1E2A5E;cursor:pointer">▶ もう一度みる</button>` : ""}
      <div class="muted" style="margin-top:6px">この表示はくりかえし流れます。見ながら答えてください。</div>
    </div>
    <div id="wbForm"></div>`;
  const canvas = newCanvas();
  document.getElementById("vbox").appendChild(canvas);
  const ctx = canvas.getContext("2d");

  // ---- 繰り返し再生 --------------------------------------------------------
  // 自動で流れた回数（auto_plays）と、参加者が押して流し直した回数（replays）を分けて数える。
  let autoPlays = 0, replays = 0;
  let raf = null, timer = null, stopped = false;
  const loop = C.loop || {};
  const maxPlays = Number(loop.max_plays) || 0;

  function play() {
    if (stopped) return;
    renderer.begin(clip.char, ctx);
    // 時計は「最初の1コマが描かれた時刻」から数える。play() を呼んだ時刻から数えると、
    // 参加者が別のタブに移っているあいだ描画が止まる(ブラウザの仕様)ため、戻ってきた
    // 瞬間に「もう終わっている」と判定されて、いきなり完成形が出てしまう。
    let t0 = null;
    function frame(now) {
      if (stopped) return;
      if (t0 === null) t0 = now;
      const s = prog.fn(now - t0);
      renderer.draw(ctx, clip.char, s);
      if (s < 1) { raf = requestAnimationFrame(frame); return; }
      // 現れきった姿をしばらく残し、いったん消してから、また流しはじめる。
      if (!loop.enabled) return;
      if (maxPlays && (autoPlays + replays) >= maxPlays) return;
      timer = setTimeout(() => {
        if (stopped) return;
        drawBlank(ctx);
        timer = setTimeout(() => { if (stopped) return; autoPlays++; play(); }, loop.gap_ms || 0);
      }, loop.hold_ms || 0);
    }
    raf = requestAnimationFrame(frame);
  }
  stopPlayback = () => {
    stopped = true;
    if (raf) cancelAnimationFrame(raf);
    if (timer) clearTimeout(timer);
  };
  const againBtn = document.getElementById("again");
  if (againBtn) againBtn.onclick = () => {
    replays++;
    if (raf) cancelAnimationFrame(raf);
    if (timer) clearTimeout(timer);
    play();
  };
  autoPlays++;   // 画面に出た時点の1回目も自動再生に数える
  play();

  // ---- 7件法の3項目（全部答えるまで次へ進めない） --------------------------
  const form = document.getElementById("wbForm");
  form.innerHTML = C.items.map((it, i) => `
    <div style="margin:14px 0;padding:10px 12px;background:#f7f8fb;border:1px solid #e3e6ee;border-radius:8px">
      <div style="font-size:15px;margin-bottom:6px">${it.text}</div>
      <div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#6b7280">
        <span style="white-space:nowrap">${C.scale_min_label}</span>
        ${[1, 2, 3, 4, 5, 6, 7].map(v => `<label style="flex:1;text-align:center;cursor:pointer">
            <input type="radio" name="wb${i}" value="${v}"><br>${v}</label>`).join("")}
        <span style="white-space:nowrap">${C.scale_max_label}</span>
      </div></div>`).join("") +
    `<p style="text-align:center;margin-top:10px"><button class="primary" id="wbNext" disabled style="opacity:.5;background:#1E2A5E">次へ</button></p>`;
  const next = document.getElementById("wbNext");
  const check = () => {
    const all = C.items.every((_, i) => form.querySelector(`input[name="wb${i}"]:checked`));
    next.disabled = !all; next.style.opacity = all ? "1" : ".5";
  };
  form.querySelectorAll("input[type=radio]").forEach(r => r.addEventListener("change", check));
  next.onclick = () => {
    const ratings = {};
    C.items.forEach((it, i) => {
      ratings[it.key] = Number(form.querySelector(`input[name="wb${i}"]:checked`).value);
    });
    stopAnim();
    answers.clips.push({
      order: clip.order, char: clip.char, family: clip.family,
      condition: C.condition, progress_source: prog.source, anim_ms: prog.dur_ms,
      ratings, auto_plays: autoPlays, replays,
      view_ms: Date.now() - shownAt,
    });
    idx++; saveProgress(); showClip();
  };
}

// ---- 最後の1問: 4択（4方式の見本を並べて見直せる） -------------------------
function showChoice() {
  stopAnim();
  const ch = sampleChar();
  const showSamples = !!(C.choice && C.choice.show_samples) && !!imgs[ch];
  // 見本を並べる順も混ぜる（左端が有利にならないように）。記録に残す。
  const order = answers.choice_order && answers.choice_order.length
    ? answers.choice_order.slice() : shuffle(C.families.slice());
  answers.choice_order = order;
  const shownAt = Date.now();
  const px = (C.choice && C.choice.sample_px) || 120;

  const cell = (f) => `
    <label style="flex:1 1 ${px}px;min-width:96px;max-width:${px + 30}px;display:block;cursor:pointer;
                  padding:10px 8px;background:#f7f8fb;border:1px solid #e3e6ee;border-radius:10px;text-align:center">
      ${showSamples ? `<div class="mini" data-fam="${f}" style="margin:0 auto 8px"></div>` : ""}
      <div style="font-size:13.5px;line-height:1.4;margin-bottom:8px">${(C.choice.labels && C.choice.labels[f]) || f}</div>
      <input type="radio" name="wbc" value="${f}">
    </label>`;

  screenEl.innerHTML = `<h2 style="color:#1E2A5E">最後の質問</h2>
    <p>${C.choice.text}</p>
    ${showSamples ? `<p class="muted">4つの見本がくりかえし流れています。見くらべてから選んでください。</p>` : ""}
    <div id="wbc" style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:10px">
      ${order.map(cell).join("")}</div>
    ${showSamples ? `<p style="text-align:center;margin-top:12px">
      <button id="againAll" style="font-size:15px;padding:10px 24px;border-radius:999px;border:2px solid #1E2A5E;background:#fff;color:#1E2A5E;cursor:pointer">▶ 見本を最初から流す</button></p>` : ""}
    <p style="text-align:center;margin-top:16px">
      <button class="primary" id="wbDone" disabled style="opacity:.5;background:#1E2A5E">回答を送って終わる</button></p>`;

  let replays = 0;
  if (showSamples) {
    // 4つを1つの時計でまとめて動かす（別々に requestAnimationFrame を回すと重い）。
    // 部分表示(reveal)とぼかし解除(blur)は内部の作業用キャンバスを1つだけ持つ作りなので、
    // 同じ方式のキャンバスが2つ以上あると壊れる。ここでは方式ごとに1つずつなので問題ない。
    const items = order.map(f => {
      const holder = screenEl.querySelector(`.mini[data-fam="${f}"]`);
      const cv = document.createElement("canvas");
      cv.width = SIZE; cv.height = SIZE;
      cv.style.width = "100%"; cv.style.height = "auto"; cv.style.display = "block";
      cv.style.background = "#fff"; cv.style.border = "1px solid #ddd"; cv.style.borderRadius = "6px";
      holder.appendChild(cv);
      return { fam: f, ctx: cv.getContext("2d"), r: RENDERERS[f] || RENDERERS.fade, prog: progressFor(f, ch) };
    });
    const maxDur = Math.max(...items.map(it => it.prog.dur_ms));
    const hold = (C.loop && C.loop.hold_ms) || 0, gap = (C.loop && C.loop.gap_ms) || 0;
    const cycle = maxDur + hold + gap;
    let raf = null, stopped = false, t0 = performance.now(), lastCycle = -1;
    function tick(now) {
      if (stopped) return;
      const el = now - t0;
      const c = Math.floor(el / cycle);
      if (c !== lastCycle) { lastCycle = c; items.forEach(it => it.r.begin(ch, it.ctx)); }
      const inCycle = el - c * cycle;
      items.forEach(it => {
        if (inCycle < maxDur + hold) it.r.draw(it.ctx, ch, it.prog.fn(inCycle));
        else drawBlank(it.ctx);                    // 次の周まで、いったん消す
      });
      raf = requestAnimationFrame(tick);
    }
    stopPlayback = () => { stopped = true; if (raf) cancelAnimationFrame(raf); };
    raf = requestAnimationFrame(tick);
    const againAll = document.getElementById("againAll");
    if (againAll) againAll.onclick = () => { replays++; t0 = performance.now(); lastCycle = -1; };
  }

  const done = document.getElementById("wbDone");
  screenEl.querySelectorAll('input[name="wbc"]').forEach(r => r.addEventListener("change", () => {
    done.disabled = false; done.style.opacity = "1";
  }));
  done.onclick = () => {
    const sel = screenEl.querySelector('input[name="wbc"]:checked');
    stopAnim();
    answers.choice = sel ? sel.value : "";
    answers.choice_ms = Date.now() - shownAt;
    answers.choice_replays = replays;
    submitAndFinish();
  };
}

// ---- 送信して終わる -------------------------------------------------------
// 1参加者1行にまとめて送る（transfer_wellbeing シート。列は群Bのときのまま使える）。
// 1本ごとの数値は wellbeing_json の中に入る。**分析はこの JSON を開いて読むこと。**
function submitAndFinish() {
  const durS = Math.round(elapsedPrior + (Date.now() - T0) / 1000);
  answers.duration_s = durS;
  answers.n_clips = clips.length;
  const rec = {
    kind: "transfer_wellbeing",
    stimulus_id: "comfort|" + GROUP,
    target_char: "-", response_char: "-",
    modality: (C.logging && C.logging.modality) || "transfer_wellbeing",
    q_set: "transfer", phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    n_choices: C.families.length,
    wellbeing_json: JSON.stringify(answers),
    choice: answers.choice,
    version: VERSION, config_version: C.config_version,
  };
  if (window.PROD) PROD.saveFracTrial(rec);
  sendRecord(rec);
  if (window.PROD && PROD.enabled) PROD.saveState("transfer_" + PHASE, { completed: true, duration_s: durS });
  screenEl.innerHTML = PROD.completionHTML(durS);
}

// ---- 見え方の確認 ---------------------------------------------------------
function visionCheck() {
  const resuming = !!(answers && answers.clips.length);
  screenEl.innerHTML = `<h2 style="color:#1E2A5E">見え方の確認</h2>
    <p>本番と同じ枠・同じ大きさで、見本の字「あ」を表示しています。
    ふだん画面を見る距離のまま、<b>はっきり見えること</b>を確認してください。見えにくい場合は画面の明るさを上げてください。</p>
    <div id="vcheck" style="text-align:center"></div>
    <p style="text-align:center;margin-top:16px"><button class="primary" id="go3">${resuming ? "続きから再開する" : "次へ進む"}</button></p>`;
  const canvas = newCanvas();
  document.getElementById("vcheck").appendChild(canvas);
  const ctx = canvas.getContext("2d");
  drawBlank(ctx);
  if (imgs["あ"]) ctx.drawImage(imgs["あ"], 0, 0, SIZE, SIZE);
  document.getElementById("go3").onclick = () => { resuming ? showClip() : intro(); };
}

// 同意画面の文言を、この実験の方針にそろえる（transfer.js と同じ手当て）。
// prod_common.js は実験1と共用なので触らず、描かれたあとにこのページの中だけで直す。
function tidyConsentScreen() {
  const h1 = screenEl.querySelector("h1");
  if (h1 && h1.textContent.indexOf("ご協力") >= 0) h1.remove();
  const items = [...screenEl.querySelectorAll("li")];
  const rec = items.find(li => li.textContent.indexOf("記録するもの") >= 0);
  const resume = items.find(li => li.textContent.indexOf("途中再開") >= 0);
  if (rec && resume) {
    rec.insertAdjacentHTML("beforeend",
      "中断して開き直した場合は、再開した回数と中断していた時間も記録します" +
      "（進行状況の控えは、お使いのブラウザの中にだけ保存されます）。");
    resume.remove();
  }
}

// =========================================================================
// 起動
// =========================================================================
function blockedScreen(reason, info) {
  const already = (reason === "already_participated" || reason === "already_in_calib" ||
                   reason === "already_in_test" || reason === "already_in_other_phase");
  const canRetry = !already;
  screenEl.innerHTML = `<h1>${already ? "この実験にはご参加いただけません" : "接続できませんでした"}</h1>
    ${already ? `
    <p>ありがとうございます。ただ、この実験は<b>以前の関連実験に参加していない方のみ</b>を対象としています。
    記録を確認したところ、あなたはすでに関連する実験にご参加いただいているため、
    今回はご協力いただけません。</p>
    <p>この作業は<b>お受け取りいただかず（辞退して）ページを閉じてください</b>。
    <b>以前ご参加いただいた分の報酬には影響しません</b>。重ねてお礼申し上げます。</p>`
    : `<p>ただいまサーバに接続できませんでした。通信の一時的な不調のことが多いので、
    <b>下のボタンでもう一度お試しください</b>。</p>
    <p>何度試しても同じ場合は、お手数ですがこの作業は辞退してページを閉じてください。
    しばらく経ってから、改めて掲載をご確認いただけますと幸いです。</p>
    <p style="text-align:center;margin-top:18px">
      <button class="primary" id="retryBtn">もう一度試す</button></p>
    <p class="muted" id="retryNote" style="text-align:center"></p>`}
    <p class="muted" style="text-align:right;margin-top:14px">実施：津田塾大学 栗原研究室</p>`;
  if (!canRetry) return;
  const btn = document.getElementById("retryBtn");
  const note = document.getElementById("retryNote");
  if (!(window.PROD && PROD.enabled) && info && info.why) {
    note.textContent = `研究者向け: ${info.tries || "?"}回試して失敗（${info.why}）`;
  }
  btn.onclick = async () => {
    btn.disabled = true; btn.style.opacity = ".5";
    note.textContent = "接続しています…";
    try {
      await startSession();
    } catch (e) {
      btn.disabled = false; btn.style.opacity = "1";
      note.textContent = "まだ接続できません。少し待ってからもう一度お試しください。";
    }
  };
}

// 名簿に問い合わせ、同意画面までを組み立てる。何度呼んでも安全に書いてある。
async function startSession() {
  screenEl.innerHTML = `<div style="min-height:40vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">読み込み中…</h1>
    <p class="muted" id="loadNote" style="margin-top:10px"></p></div>`;
  onRosterRetry = (i, n) => {
    const el = document.getElementById("loadNote");
    if (el) el.textContent = `混み合っています。接続をやり直しています（${i}/${n}）…`;
  };
  const a = await resolveAssignment();
  onRosterRetry = null;
  if (a.blocked) { blockedScreen(a.reason, a); return false; }
  ASSIGN = a.assign_index; ASSIGN_SOURCE = a.source;
  await preload();
  if (!clips.length) clips = buildClips();
  if (!answers) answers = { clips: [], choice: "", choice_order: [] };
  PROD.consentScreen(screenEl, "文字の見え心地", 4, visionCheck, false,
    { noEnvNote: true,
      desc: "日本語のかな1文字が現れる様子について、続けて見ていられるかを調べる研究です" });
  tidyConsentScreen();
  return true;
}

(async function () {
  try {
    // 途中再開の情報は、参加者IDを保存時のものへ戻す働きがあるので名簿より先に読む。
    if (window.PROD && PROD.enabled) {
      const st = PROD.loadState("transfer_" + PHASE);
      if (st && st.saved_at) {
        resumeMeta = { count: (st.resume_count || 0) + 1,
                       gapS: (st.resume_gap_s || 0) + Math.round((Date.now() - st.saved_at) / 1000) };
      }
      if (st && st.completed) {
        screenEl.innerHTML = PROD.completionHTML(st.duration_s || 0);
        return;
      }
      if (st && st.session_v === SESSION_V && Array.isArray(st.clips) && st.clips.length) {
        clips = st.clips; idx = st.idx || 0; answers = st.answers || null;
        elapsedPrior = st.elapsed_s || 0;
      }
    }
    await startSession();
  } catch (e) {
    screenEl.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}</p>`;
  }
})();
