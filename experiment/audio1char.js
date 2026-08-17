// =========================================================================
// 1文字課題 統合セッション v3.0 (実験1: 聴覚と視覚の基準曲線を同一参加者で測る)
//   - 1人の参加者が「聞き取り(A)」と「見分け(V)」を SET_TRIALS問×4ブロックで行う。
//     ブロック順は AVAV / VAVA / AVVA / VAAV の4パターンからランダムに割り当て、
//     全レコードに block_order / block_pos として記録する(順序・疲労の釣り合い)。
//   - 既定は 20問×4=合計80問(聴覚40・視覚40)・約8分。?set=50 で50問×4に変更可(研究者用)。
//   - 聴覚: 単一のかな音声(B3・0.2秒/モーラ)を frac% まで再生して打ち切る(v2 と同一)。
//     開始合図音1回 → 音声 → 終了合図音2回。「もう一度きく」可(回数を記録)。
//   - 視覚: 単一のかな(base/<char>.png・256px)を CHAR_MS(200ms)×frac% だけ表示して消す。
//     ＋注視(400ms+ゆらぎ) → 文字 → 白紙 → 回答。描画フレームの実時刻から
//     actual_ms / actual_frames を実測。「もう一度みる」可(回数を記録)。
//   - frac は両モダリティ共通の 21水準(0..100, 5刻み)。catch(frac=100)は各モダリティ5%。
//   - 記録: 聴覚は stimulus_id を answer_key でサーバ採点、視覚は target_char 申告で採点
//     (先生の GAS 契約のまま)。共通で replays / rt_ms / is_catch / version を送る。
//   - 参加者体験は乙課題と統一: 同意(機器3択)→教示→音量確認→見え方確認→ブロック→完了。
//     2問目以降は自動開始・回答の確認(選び直す/決定)・途中再開・進捗バー・完了コードのコピー。
//
//   履歴: v1=jsPsych版(聴覚のみ200問・先生のmain)。v2=乙UXへの書き直し(聴覚のみ)。
//         v3=聴覚+視覚の統合セッション(丸山・栗原の実験1整理と ABAB 釣り合い案・2026-08-17)。
// =========================================================================
"use strict";

const VERSION = "3.12";
const P = new URLSearchParams(location.search);
const SET_TRIALS = Number(P.get("set") || 20);            // 1ブロックの問題数(既定20=合計80問・約8分)
const BLOCK_ORDERS = ["AVAV", "VAVA", "AVVA", "VAAV"];    // A=聴覚, V=視覚
const N_PRACTICE_A = 3, N_PRACTICE_V = 3;                 // 各モダリティ初回ブロック前の練習
const CATCH_RATE = 0.05;
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);
const FADE_MS = 8;
// 聴覚: 合図音。
const BEEP_HZ = 880;
const BEEP_MS = 80;
const BEEP_LEAD_MS = 600;    // 開始合図音→読み上げ(v1=300。構えが間に合わないため延長)
const END_GAP_MS = 500;
const END_BEEP_GAP_MS = 140;
// 視覚: 提示。速度は聴覚プールと同じ 200ms/モーラのみ(実験1の基準点)。
const CHAR_MS = 200;
const SIZE = 256;
const FIX_MS = 400;
const FIX_JITTER = 300;      // 注視点の追加ゆらぎ上限(ms・先読み防止)
const AUTO_START_MS = 700;   // 2問目以降の自動開始までの間

// 端末環境 (解析用にログ)。
const ENV = { ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
  screen: `${window.screen.width}x${window.screen.height}`,
  touch: (navigator.maxTouchPoints || 0) > 0, refreshHz: null };
(function measureRefresh() {
  let n = 0; const t0 = performance.now();
  function f(now) { n++; if (n < 40) requestAnimationFrame(f); else ENV.refreshHz = Math.round(1000 / ((now - t0) / n)); }
  requestAnimationFrame(f);
})();
if (window.PROD) PROD.setEnv(ENV);

// ---- 回答の表 -------------------------------------------------------------
// 聴覚: 68音(を・ぢ・づ・ゔは同音のため除外、同音は併記ボタン)。
const GRID_AUDIO = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","ん"],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","","","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
];
const N_CHOICES_A = GRID_AUDIO.flat().filter(c => c !== "").length;   // 68
const HOMOPHONE_LABEL = { "お": "お／を", "じ": "じ／ぢ", "ず": "ず／づ" };
function kanaLabel(ch) { return HOMOPHONE_LABEL[ch] || ch; }
// 視覚: 独立モーラ72字(乙視覚と同じ。を・ん・ゔは字として区別できるため含む)。
const GRID_VISUAL = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],["ゔ","","","",""],
];
const CHARS_V = GRID_VISUAL.flat().filter(Boolean);   // 72
const N_CHOICES_V = CHARS_V.length;

const screen = document.getElementById("screen");
let audioCtx = null;
const bufById = {};        // 聴覚: 刺激id → デコード済み音声
const imgs = {};           // 視覚: かな → 画像
let manifest = null;
const stimByChar = {};     // サンプル音用: かな→聴覚刺激(正解表が読めたときだけ埋まる)
let trials = [], results = [], ti = 0;
let blockOrder = "";       // "AVAV" など。全レコードに載せる。
let resumeState = null, elapsedPrior = 0;
let aIntroduced = false, vIntroduced = false;   // 各モダリティの1問目だけ丁寧な文言・手動開始

function ensureCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

// ---- 聴覚: 切り出し・再生 (v1/v2 と同一の計算) ---------------------------
function gateAvailS(stim) {
  if (typeof stim.gate_avail_ms === "number") return Math.max(0.01, stim.gate_avail_ms / 1000);
  const onsetMs = (typeof stim.gate_onset_ms === "number") ? stim.gate_onset_ms : 0;
  return Math.max(0.01, stim.char_dur_s - onsetMs / 1000);
}
function gatedBuffer(buf, stim) {
  const sr = buf.sampleRate;
  const onsetMs = (typeof stim.gate_onset_ms === "number") ? stim.gate_onset_ms : 0;
  const gain = (typeof stim.gate_gain === "number") ? stim.gate_gain : 1.0;
  const start = Math.round((stim.char_onset_s + onsetMs / 1000) * sr);
  const avail = gateAvailS(stim);
  const len = Math.max(0, Math.round(avail * stim.frac / 100 * sr));
  const src = buf.getChannelData(0);
  const ab = ensureCtx().createBuffer(1, Math.max(1, len), sr);
  const out = ab.getChannelData(0);
  for (let i = 0; i < len; i++) out[i] = (src[start + i] || 0) * gain;
  const fade = Math.min(Math.round(sr * FADE_MS / 1000), len >> 1);
  for (let i = 0; i < fade; i++) { out[i] *= i / fade; out[len - 1 - i] *= i / fade; }
  return ab;
}
let _nodes = [];
function stopAll() { for (const n of _nodes) { try { n.stop(); } catch (e) {} } _nodes = []; }
function playBeep(when) {
  const ctx = ensureCtx();
  const osc = ctx.createOscillator(); const g = ctx.createGain();
  osc.type = "sine"; osc.frequency.value = BEEP_HZ;
  osc.connect(g); g.connect(ctx.destination);
  g.gain.setValueAtTime(0.0001, when);
  g.gain.exponentialRampToValueAtTime(0.12, when + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, when + BEEP_MS / 1000);
  osc.start(when); osc.stop(when + BEEP_MS / 1000 + 0.02);
  _nodes.push(osc);
}
function playGated(stim) {
  const ctx = ensureCtx();
  stopAll();
  const t0 = ctx.currentTime + 0.02;
  playBeep(t0);
  const stimStart = t0 + BEEP_LEAD_MS / 1000;
  const stimDur = gateAvailS(stim) * stim.frac / 100;
  if (stim.frac > 0) {
    const s = ctx.createBufferSource();
    s.buffer = gatedBuffer(bufById[stim.id], stim);
    s.connect(ctx.destination); s.start(stimStart);
    _nodes.push(s);
  }
  const endAt = stimStart + stimDur + END_GAP_MS / 1000;
  playBeep(endAt);
  playBeep(endAt + END_BEEP_GAP_MS / 1000);
}

// ---- 視覚: 描画 -----------------------------------------------------------
function newCanvas() { const c = document.createElement("canvas"); c.id = "stim"; c.width = SIZE; c.height = SIZE;
  c.style.background = "#fff"; c.style.border = "1px solid #ddd"; c.style.display = "block"; c.style.margin = "0 auto"; return c; }
function drawBlank(ctx) { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, SIZE, SIZE); }
function drawChar(ctx, ch) { drawBlank(ctx); if (imgs[ch]) ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE); }
function drawFix(ctx) {
  drawBlank(ctx);
  ctx.fillStyle = "#333"; ctx.font = "40px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("+", SIZE / 2, SIZE / 2);
}

// ---- 読み込み -------------------------------------------------------------
function loadImage(ch) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error(`base/${ch}.png の読込に失敗`));
    im.src = `base/${encodeURIComponent(ch)}.png`;
  });
}
async function preload() {
  screen.innerHTML = `<div style="min-height:60vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">読み込み中…</h1>
    <div style="width:min(320px,80%);height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden;margin-top:10px">
      <div id="loadBar" style="height:100%;width:0%;background:#2E7D8F"></div></div></div>`;
  const res = await fetch("audio1char_manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("audio1char_manifest.json が読めない");
  manifest = await res.json();
  const pool = manifest.stimuli || [];
  if (!pool.length) throw new Error("audio1char_manifest に刺激がありません");
  // サンプル音(あいうえお)用に、公開の正解表から かな→刺激 の対応を引く(無ければランダムに戻る)。
  try {
    const kres = await fetch("answer_key_merged.json", {cache: "no-store"});
    if (kres.ok) {
      const akey = await kres.json();
      for (const st of pool) {
        const rec = akey[`audio1char|${st.id}`];
        if (rec && rec.char) stimByChar[rec.char] = st;
      }
    }
  } catch (e) { /* 対応表なしでも課題は成立する */ }
  const total = pool.length + CHARS_V.length;
  let done = 0;
  const tick = () => { done++; const bar = document.getElementById("loadBar");
    if (bar) bar.style.width = `${Math.round(done / total * 100)}%`; };
  await Promise.all([
    ...pool.map(async st => {
      const r = await fetch(`audio1char_stimuli/${st.id}.mp3`, {cache: "force-cache"});
      if (!r.ok) throw new Error(`audio1char_stimuli/${st.id}.mp3 ${r.status}`);
      bufById[st.id] = await ensureCtx().decodeAudioData(await r.arrayBuffer());
      tick();
    }),
    ...CHARS_V.map(async ch => { imgs[ch] = await loadImage(ch); tick(); }),
  ]);
}

// ---- 出題の配り方 ---------------------------------------------------------
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
function dealEven(items, n) {
  const out = [];
  while (out.length < n) out.push(...shuffle([...items]));
  return out.slice(0, n);
}
// 各モダリティ n 問(catch 込み)を作る。frac は 21水準に均等、刺激/文字も均等。
function buildModality(mod, n) {
  const nCatch = Math.round(n * CATCH_RATE);
  const nGraded = n - nCatch;
  const fracs = dealEven(FRAC_GRID, nGraded);
  const out = [];
  if (mod === "A") {
    const stims = dealEven(manifest.stimuli, n);
    for (let i = 0; i < n; i++) {
      const isCatch = i >= nGraded;
      out.push(Object.assign({}, stims[i], {mod: "A", frac: isCatch ? 100 : fracs[i], is_catch: isCatch, practice: false}));
    }
  } else {
    const chars = dealEven(CHARS_V, n);
    for (let i = 0; i < n; i++) {
      const isCatch = i >= nGraded;
      out.push({mod: "V", char: chars[i], frac: isCatch ? 100 : fracs[i], is_catch: isCatch, practice: false});
    }
  }
  return shuffle(out);
}
// 練習1問(本番前に何度でも・記録しない)。fracは中くらい〜全部の中からランダム。
function buildTryout(mod) {
  const frac = [100, 60, 40, 20][Math.floor(Math.random() * 4)];
  if (mod === "A") {
    const st = manifest.stimuli[Math.floor(Math.random() * manifest.stimuli.length)];
    return Object.assign({}, st, {mod: "A", frac, is_catch: false, practice: true, block_pos: 0});
  }
  const ch = CHARS_V[Math.floor(Math.random() * CHARS_V.length)];
  return {mod: "V", char: ch, frac, is_catch: false, practice: true, block_pos: 0};
}
// セッション全体: ブロック順に従い、区切り画面(gate)と練習を差し込む。
// モダリティごとに SET_TRIALS×2 問を作って半分ずつ配る(2ブロック合計で刺激とfracが均等)。
function buildTrials() {
  blockOrder = BLOCK_ORDERS[Math.floor(Math.random() * BLOCK_ORDERS.length)];
  const allA = buildModality("A", SET_TRIALS * 2);
  const allV = buildModality("V", SET_TRIALS * 2);
  const setsA = [allA.slice(0, SET_TRIALS), allA.slice(SET_TRIALS)];
  const setsV = [allV.slice(0, SET_TRIALS), allV.slice(SET_TRIALS)];
  const seen = { A: false, V: false };
  const out = [];
  [...blockOrder].forEach((mod, bi) => {
    const pos = bi + 1;
    out.push(seen[mod] ? {gate: "block", mod, block_pos: pos}
                       : {gate: "try", mod, block_pos: pos});
    seen[mod] = true;
    const set = (mod === "A" ? setsA : setsV).shift();
    for (const t of set) out.push(Object.assign(t, {block_pos: pos}));
  });
  return out;
}

// ---- 画面 -----------------------------------------------------------------
const N_MAIN = () => SET_TRIALS * 4;
function mainDone() { return results.filter(r => !r.practice).length; }
function progressHeader(t) {
  const modName = t.mod === "A" ? "聞き取り" : "見分け";
  if (t.practice) return `<div class="muted">${modName}の練習</div>`;
  const pct = Math.round(mainDone() / N_MAIN() * 100);
  return `<div class="muted" style="display:flex;align-items:center;gap:10px">
    <span style="white-space:nowrap">${modName}</span>
    <span style="flex:1;height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden"><span style="display:block;height:100%;width:${pct}%;background:#2E7D8F"></span></span>
    <span style="white-space:nowrap">${pct}%</span></div>`;
}

// かな表(紙の五十音表式・列幅を上下の表で統一・右寄せ)。mod で表を切り替える。
function buildKanaGrid(mod, done) {
  const src = mod === "A" ? GRID_AUDIO : GRID_VISUAL;
  const splitAt = mod === "A" ? 10 : 11;
  const grid = document.createElement("div"); grid.id = "grid"; grid.style.display = "block";
  const blocks = [src.slice(0, splitAt), src.slice(splitAt)].filter(b => b.length);
  const maxCols = Math.max(...blocks.map(b => b.length));
  for (const rowsBlock of blocks) {
    const cols = [...rowsBlock].reverse();
    const pad = maxCols - cols.length;
    const g = document.createElement("div");
    g.style.display = "grid"; g.style.gridTemplateColumns = `repeat(${maxCols},1fr)`;
    g.style.gap = "6px"; g.style.marginTop = "14px";
    for (let dan = 0; dan < 5; dan++) {
      for (let k = 0; k < pad; k++) { const s = document.createElement("div"); s.className = "kana spacer"; g.appendChild(s); }
      for (const col of cols) {
        const ch = col[dan] || "";
        if (!ch) { const s = document.createElement("div"); s.className = "kana spacer"; g.appendChild(s); continue; }
        const b = document.createElement("button"); b.className = "kana";
        b.textContent = mod === "A" ? kanaLabel(ch) : ch;
        if (b.textContent.length > 1) b.style.fontSize = "12px";
        b.onclick = () => done(ch); g.appendChild(b);
      }
    }
    grid.appendChild(g);
  }
  return grid;
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  if (t.gate) return showGate(t);
  if (t.mod === "A") return runAudioTrial(t);
  return runVisualTrial(t);
}

// ブロックの区切り画面。
function showGate(t) {
  if (t.gate === "try") return showTryGate(t);
  const modName = t.mod === "A" ? "聞き取り" : "見分け";
  const body = `<h2 style="color:#1E2A5E">ふたたび【${modName}】の課題です（ブロック ${t.block_pos} / 4）</h2>
      <p>やり方はさきほどの${modName}の課題と同じです。</p>`;
  screen.innerHTML = `<div style="text-align:center;padding:40px 20px">${body}
    <p style="margin-top:20px"><button class="primary" id="gateGo">始める（またはスペースキー）</button></p></div>`;
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go() { document.removeEventListener("keydown", key); ti++; saveProgress(); runTrial(); }
  document.getElementById("gateGo").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
}
// 初回ブロックの練習ゲート: その課題の説明+練習(何度でも)。1回以上で本番へ。
function audioGuideHTML() {
  return `
    <p>ひらがな<b>1文字</b>の読み上げが流れます。<b>聞こえた文字を、かなの表から選んでください。</b>
    読み上げは<b>途中までしか流れない</b>ことがあります。</p>
    <svg viewBox="0 0 640 150" style="width:100%;max-width:560px;display:block;margin:4px auto 8px" role="img" aria-label="聞き取りの流れの図">
      <rect x="30" y="22" width="130" height="72" rx="10" fill="#eef4f6" stroke="#2E7D8F"/>
      <rect x="30" y="22" width="52" height="72" rx="10" fill="#d8ecf0"/>
      <text x="70" y="68" font-size="30" text-anchor="middle" fill="#2E7D8F">♪</text>
      <line x1="82" y1="26" x2="82" y2="90" stroke="#2E7D8F" stroke-width="2" stroke-dasharray="4 3"/>
      <text x="95" y="118" font-size="13" text-anchor="middle" fill="#1b2030">途中で切れることがある</text>
      <text x="210" y="64" font-size="20" text-anchor="middle" fill="#2E7D8F">➡</text>
      <rect x="250" y="14" width="262" height="88" rx="10" fill="#fff" stroke="#cdd3e6"/>
      ${[0,1].map(r=>[0,1,2,3,4,5,6,7].map(c=>`<rect x="${266+c*29}" y="${26+r*26}" width="22" height="20" rx="4" fill="#fbfcff" stroke="#cdd3e6"/>`).join("")).join("")}
      <rect x="324" y="52" width="22" height="20" rx="4" fill="#2E7D8F"/>
      <text x="335" y="66" font-size="12" text-anchor="middle" fill="#fff">選</text>
      <text x="381" y="118" font-size="13" text-anchor="middle" fill="#1b2030">聞こえた文字を表から選ぶ</text>
    </svg>
    <p class="muted">「ピッ」1回のあとに読み上げが流れ、終わると「ピッピッ」と2回鳴ります。何度でも聞き直せます。</p>
    <p style="background:#fff8ec;border:1px solid #eadfc8;border-radius:8px;padding:10px 12px">
    ほとんど何も聞こえない問題もあります。その場合も、<b>もっとも近いと思う文字を選んでください</b>。</p>`;
}
function visualGuideHTML() {
  return `
    <p>同じ場所に、ひらがな<b>1文字</b>が短く表示されて消えます。<b>見えた文字を、かなの表から選んでください。</b>
    表示は<b>とても短い</b>ことがあります。</p>
    <svg viewBox="0 0 640 150" style="width:100%;max-width:560px;display:block;margin:4px auto 8px" role="img" aria-label="見分けの流れの図">
      <rect x="20" y="22" width="66" height="66" rx="8" fill="#fff" stroke="#1E2A5E"/>
      <text x="53" y="68" font-size="32" text-anchor="middle" fill="#1b2030">か</text>
      <text x="103" y="60" font-size="14" text-anchor="middle" fill="#6b7280">→</text>
      <rect x="120" y="22" width="66" height="66" rx="8" fill="#f6f6f6" stroke="#b0b6c2" stroke-dasharray="5 4"/>
      <text x="153" y="62" font-size="13" text-anchor="middle" fill="#9aa1ad">白紙</text>
      <text x="103" y="118" font-size="13" text-anchor="middle" fill="#1b2030">短く表示されて消える</text>
      <text x="220" y="64" font-size="20" text-anchor="middle" fill="#1E2A5E">➡</text>
      <rect x="250" y="14" width="262" height="88" rx="10" fill="#fff" stroke="#cdd3e6"/>
      ${[0,1].map(r=>[0,1,2,3,4,5,6,7].map(c=>`<rect x="${266+c*29}" y="${26+r*26}" width="22" height="20" rx="4" fill="#fbfcff" stroke="#cdd3e6"/>`).join("")).join("")}
      <rect x="324" y="52" width="22" height="20" rx="4" fill="#1E2A5E"/>
      <text x="335" y="66" font-size="12" text-anchor="middle" fill="#fff">選</text>
      <text x="381" y="118" font-size="13" text-anchor="middle" fill="#1b2030">見えた文字を表から選ぶ</text>
    </svg>
    <p class="muted">中央の ＋ のあとに表示されます。もう一度表示することもできます。</p>
    <p style="background:#fff8ec;border:1px solid #eadfc8;border-radius:8px;padding:10px 12px">
    ほとんど見えない問題もあります。その場合も、<b>もっとも近いと思う文字を選んでください</b>。</p>`;
}
function showTryGate(t) {
  tryReturn = () => showTryGate(t);
  const modName = t.mod === "A" ? "聞き取り" : "見分け";
  const tried = t.mod === "A" ? triedA : triedV;
  const accent = t.mod === "A" ? "#2E7D8F" : "#1E2A5E";
  screen.innerHTML = `<h2 style="color:#1E2A5E">【${modName}】の課題（ブロック ${t.block_pos} / 4）</h2>
    ${t.mod === "A" ? audioGuideHTML() : visualGuideHTML()}
    <div style="text-align:center;margin-top:16px">
      <p><button id="tryBtn" class="playbtn" style="background:${accent}">${tried ? "もう一度練習する" : `${modName}を1問練習する`}</button></p>
      <p><button class="primary" id="goMain" ${tried ? "" : 'disabled style="opacity:.5"'}>本番を始める</button></p>
      ${tried ? "" : `<p class="muted">1回以上練習すると本番に進めます。</p>`}
    </div>`;
  document.getElementById("tryBtn").onclick = () => {
    if (t.mod === "A") { triedA++; runAudioTrial(buildTryout("A")); }
    else { triedV++; runVisualTrial(buildTryout("V")); }
  };
  document.getElementById("goMain").onclick = () => {
    if (!(t.mod === "A" ? triedA : triedV)) return;
    tryReturn = null; ti++; saveProgress(); runTrial();
  };
}

function saveProgress() {
  if (window.PROD && PROD.enabled) PROD.saveState("audio1char",
    { trials, results, ti, blockOrder, elapsed_s: Math.round(elapsedPrior + (Date.now() - T0) / 1000) });
}

// 記録して次へ。練習は本人の答え(視覚は正解も)を見せる。
function finalizeCommon(t, rec, picked) {
  if (!t.practice) {
    results.push(rec);
    if (window.PROD) PROD.saveFracTrial(rec);
    ti++; saveProgress(); runTrial(); return;
  }
  results.push(Object.assign({practice: true}, rec));
  const isFirst = results.filter(r => r.practice).length === 1;
  let note;
  if (t.mod === "V") {
    const ok = picked === t.char;
    note = `<p style="font-size:17px">正解「<b style="font-size:24px">${t.char}</b>」 ／ あなたの答え「<b style="font-size:24px">${picked || "（未選択）"}</b>」
      <span style="color:${ok ? '#2E7D8F' : '#C25B4E'}">${ok ? '◯' : '×'}</span></p>`;
  } else {
    note = `<p style="font-size:17px">あなたの答え: <b style="font-size:24px">${picked ? kanaLabel(picked) : "（未選択）"}</b></p>`;
  }
  const extra = isFirst
    ? `<p class="muted" style="line-height:1.8">これは練習です（答えは記録されません）。<br>
       ほとんど分からない問もありますが、もっとも近いと思う文字を選べばOKです。</p>`
    : `<p class="muted">これは練習です。</p>`;
  screen.innerHTML = `<div style="text-align:center;padding:30px">${note}${extra}</div>`;
  setTimeout(() => { if (tryReturn) tryReturn(); }, isFirst ? 3000 : 2000);   // 練習後はゲートへ戻る
}

// ---- 聴覚の1問 ------------------------------------------------------------
function runAudioTrial(t) {
  let tStim = null, replays = 0, picked = null, pickedRt = null, autoTimer = null;
  screen.innerHTML = `${progressHeader(t)}
    <div id="stage">
      <div style="text-align:center;margin:30px 0 12px">
        <button id="playBtn" class="playbtn">${aIntroduced ? "▶ 音をきく" : "▶ 準備ができたら音をきく（またはスペースキー）"}</button>
      </div>
      ${aIntroduced ? "" : `<div class="muted" id="prompt" style="text-align:center">ボタンを押すと、ひらがな1文字の読み上げが流れます。聞こえた文字を下の表から選んでください。</div>`}
      <div id="answerArea"></div>
    </div>`;
  const playBtn = document.getElementById("playBtn");
  const answerArea = document.getElementById("answerArea");

  const finalize = () => {
    document.removeEventListener("keydown", keyHandler);
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    stopAll();
    finalizeCommon(t, { stimulus_id: t.id, response_char: picked, modality: "audio1char",
      q_set: "all", pitch_scheme: "B3", frac: t.frac, n_choices: N_CHOICES_A,
      replays, rt_ms: pickedRt, is_catch: t.is_catch,
      block_order: blockOrder, block_pos: t.block_pos, version: VERSION }, picked);
  };
  const showConfirm = () => {
    document.getElementById("grid")?.remove();
    answerArea.innerHTML = `<div style="text-align:center;margin-top:14px">
      <div class="ask" style="font-size:18px">この回答で決定しますか？</div>
      <div style="font-size:20px;margin:12px 0">あなたの答え「<b>${kanaLabel(picked)}</b>」</div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
        <button id="fixBtn" style="padding:10px 16px;font-size:15px">選び直す</button>
        <button class="primary" id="okBtn">これで決定</button></div></div>`;
    document.getElementById("fixBtn").onclick = showGrid;
    document.getElementById("okBtn").onclick = finalize;
  };
  const showGrid = () => {
    answerArea.innerHTML = "";
    const grid = buildKanaGrid("A", (ch) => {
      picked = ch; pickedRt = Math.round(performance.now() - tStim);   // 音の開始→回答選択
      showConfirm();
    });
    answerArea.appendChild(grid);
    if (tStim === null) grid.querySelectorAll("button.kana").forEach(b => { b.disabled = true; });
  };
  const play = () => {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    if (tStim === null) {
      tStim = performance.now();
      document.getElementById("grid")?.querySelectorAll("button.kana").forEach(b => { b.disabled = false; });
      playBtn.textContent = "▶ もう一度きく";
      const pr = document.getElementById("prompt");
      if (pr) pr.textContent = "聞こえた文字を下の表から選んでください。何度でも聞き直せます。";
      aIntroduced = true;
    } else { replays += 1; }
    playGated(t);
  };
  const keyHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); play(); } };
  playBtn.onclick = play;
  document.addEventListener("keydown", keyHandler);
  showGrid();
  // 2問目以降は自動で再生(クリック回数の削減)。各モダリティの初回のみ手動開始。
  if (aIntroduced) autoTimer = setTimeout(play, AUTO_START_MS);
}

// ---- 視覚の1問 ------------------------------------------------------------
function runVisualTrial(t) {
  let tStim = null, replays = 0, picked = null, pickedRt = null, autoTimer = null;
  let actualMs = null, actualFrames = null, presenting = false;
  screen.innerHTML = `${progressHeader(t)}
    <div id="stage">
      <div id="vbox" style="text-align:center;margin:10px 0 6px"></div>
      <div style="text-align:center;margin:6px 0 10px">
        <button id="playBtn" class="playbtn" style="background:#1E2A5E">${vIntroduced ? "▶ 表示する" : "▶ 準備ができたら表示する（またはスペースキー）"}</button>
      </div>
      ${vIntroduced ? "" : `<div class="muted" id="prompt" style="text-align:center">中央の ＋ を見つめてボタンを押すと、ひらがな1文字が短く表示されます。見えた文字を下の表から選んでください。</div>`}
      <div id="answerArea"></div>
    </div>`;
  const playBtn = document.getElementById("playBtn");
  const answerArea = document.getElementById("answerArea");
  const canvas = newCanvas();
  document.getElementById("vbox").appendChild(canvas);
  const ctx = canvas.getContext("2d");
  drawFix(ctx);

  const finalize = () => {
    document.removeEventListener("keydown", keyHandler);
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    finalizeCommon(t, { stimulus_id: t.char, target_char: t.char, response_char: picked,
      modality: "visual1char", q_set: "all", frac: t.frac, n_choices: N_CHOICES_V,
      replays, rt_ms: pickedRt, is_catch: t.is_catch,
      actual_ms: actualMs, actual_frames: actualFrames, char_ms: CHAR_MS,
      block_order: blockOrder, block_pos: t.block_pos, version: VERSION }, picked);
  };
  const showConfirm = () => {
    document.getElementById("grid")?.remove();
    answerArea.innerHTML = `<div style="text-align:center;margin-top:14px">
      <div class="ask" style="font-size:18px;color:#1E2A5E">この回答で決定しますか？</div>
      <div style="font-size:20px;margin:12px 0">あなたの答え「<b>${picked}</b>」</div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
        <button id="fixBtn" style="padding:10px 16px;font-size:15px">選び直す</button>
        <button class="primary" id="okBtn" style="background:#1E2A5E">これで決定</button></div></div>`;
    document.getElementById("fixBtn").onclick = showGrid;
    document.getElementById("okBtn").onclick = finalize;
  };
  const showGrid = () => {
    answerArea.innerHTML = "";
    const grid = buildKanaGrid("V", (ch) => {
      picked = ch; pickedRt = tStim === null ? null : Math.round(performance.now() - tStim);
      showConfirm();
    });
    answerArea.appendChild(grid);
    if (tStim === null) grid.querySelectorAll("button.kana").forEach(b => { b.disabled = true; });
  };
  // 提示: ＋(400ms+ゆらぎ) → 文字(CHAR_MS×frac%) → 白紙。描画フレームの実時刻から実測。
  const present = () => {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    if (presenting) return;
    presenting = true;
    const isFirstShow = (tStim === null);
    if (!isFirstShow) replays += 1;
    const nominal = CHAR_MS * t.frac / 100;
    const fixDur = FIX_MS + Math.floor(Math.random() * FIX_JITTER);
    drawFix(ctx);
    const t0 = performance.now();
    let phase = "fix", tOn = 0, frames = 0;
    const unlock = () => {
      if (!isFirstShow) return;
      tStim = performance.now();   // 反応時間の起点=最初の提示開始
      document.getElementById("grid")?.querySelectorAll("button.kana").forEach(b => { b.disabled = false; });
      playBtn.textContent = "▶ もう一度みる";
      const pr = document.getElementById("prompt");
      if (pr) pr.textContent = "見えた文字を下の表から選んでください。もう一度表示することもできます。";
      vIntroduced = true;
    };
    function frame(now) {
      const el = now - t0;
      if (phase === "fix" && el >= fixDur) {
        if (t.frac > 0) { phase = "char"; drawChar(ctx, t.char); tOn = now; frames = 1; unlock(); }
        else {           // frac=0: 何も出さずに終わる(実測0)
          drawBlank(ctx); unlock();
          if (isFirstShow) { actualMs = 0; actualFrames = 0; }
          presenting = false; return;
        }
      }
      else if (phase === "char") {
        if (now - tOn >= nominal) {
          drawBlank(ctx);
          if (isFirstShow) { actualMs = Math.round(now - tOn); actualFrames = frames; }
          presenting = false; return;
        }
        frames++;
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  };
  const keyHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); present(); } };
  playBtn.onclick = present;
  document.addEventListener("keydown", keyHandler);
  showGrid();
  if (vIntroduced) autoTimer = setTimeout(present, AUTO_START_MS);
}

// ---- 完了 -----------------------------------------------------------------
function showResults() {
  const durS = Math.round(elapsedPrior + (Date.now() - T0) / 1000);
  if (window.PROD && PROD.enabled) {
    PROD.saveState("audio1char", { completed: true, duration_s: durS });
    screen.innerHTML = PROD.completionHTML(durS);
    return;
  }
  const main = results.filter(r => !r.practice);
  screen.innerHTML = `<h1>パイロット完了</h1>
    <p class="muted">回答 ${main.length} 問（ブロック順 ${blockOrder}）。聴覚の採点は answer_key を持つ解析側で行う。</p>
    <p><button class="primary" id="dl">結果JSONをダウンロード</button></p>`;
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify({
      config: { VERSION, SET_TRIALS, BLOCK_ORDERS, blockOrder, N_PRACTICE_A, N_PRACTICE_V,
        CATCH_RATE, FRAC_GRID, CHAR_MS, pitch_scheme: "B3" },
      env: ENV, duration_s: durS, trials: main }, null, 2)], {type: "application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `onechar_session_${Date.now()}.json`; a.click();
  };
}

let triedA = 0, triedV = 0, tryReturn = null;

function start() {
  ensureCtx();
  if (resumeState && resumeState.trials) {
    trials = resumeState.trials; results = resumeState.results || [];
    ti = resumeState.ti || 0; elapsedPrior = resumeState.elapsed_s || 0;
    blockOrder = resumeState.blockOrder || "";
    aIntroduced = true; vIntroduced = true;   // 丁寧な文言・手動開始は初回扱いにしない
    triedA = 1; triedV = 1;                   // 練習ゲートに戻っても即「本番を始める」を押せる
    return runTrial();
  }
  trials = buildTrials(); results = []; ti = 0;
  runTrial();
}

// ---- 教示・確認 -----------------------------------------------------------
function intro() {
  const resumeNote = (resumeState && resumeState.trials)
    ? `<p style="background:#eef7ee;border:1px solid #bcd9bc;border-radius:8px;padding:10px 12px">
       <b>前回の続きから再開します</b>。
       <span class="muted" style="display:block;margin-top:4px;font-size:12.5px">練習はとばします。音量の確認だけもう一度お願いします。</span></p>` : "";
  screen.innerHTML = `<h1>課題の進め方</h1>
    ${resumeNote}
    <p>この課題は<b>2種類</b>（聞き取り・見分け）あり、ブロックで交互に行います。
    どちらも、ひらがな<b>1文字</b>が出題され、<b>分かった文字をかなの表から選びます</b>。</p>
    <p class="muted">それぞれのくわしいやり方は、各課題が始まる前に説明と練習があります。</p>
    <p><button class="primary" id="go">次へ：音量の確認</button></p>
    <p class="muted" style="text-align:right;font-size:12px;margin-top:6px">${(window.PROD&&PROD.enabled)?"津田塾大学 栗原研究室":"研究者向けパイロット版 v"+VERSION}</p>`;
  document.getElementById("go").onclick = volumeCheck;
}

function playSample() {
  const ctx = ensureCtx();
  stopAll();
  const aiueo = ["あ","い","う","え","お"].map(c => stimByChar[c]).filter(Boolean);
  const list = aiueo.length === 5 ? aiueo : shuffle([...manifest.stimuli]).slice(0, 3);
  list.forEach((st, i) => {
    const s = ctx.createBufferSource();
    s.buffer = gatedBuffer(bufById[st.id], Object.assign({}, st, {frac: 100}));
    s.connect(ctx.destination); s.start(ctx.currentTime + 0.1 + i * 0.5);
    _nodes.push(s);
  });
}
function volumeCheck() {
  const mobileNote = ENV.touch
    ? `スマートフォンの場合は、静かな場所で、音量をやや大きめにすると聞き取りやすくなります。` : ``;
  screen.innerHTML = `<h2 style="color:#1E2A5E">音量の確認</h2>
    <p>下のボタンで<b>サンプル音</b>を鳴らし、聞き取りやすい音量になるよう端末の音量を調節してください。
    調節が終わったら、<b>この音量のまま</b>課題に進みます。</p>
    <div style="background:#eef4f6;border:1px solid #d3e2e7;border-radius:8px;padding:16px 14px;text-align:center">
      <button id="sample" class="playbtn">▶ サンプル音を鳴らす（あ・い・う・え・お）</button>
      <div class="muted" style="margin-top:10px">何度でも鳴らせます。${mobileNote}この課題は静かな環境で行ってください。</div></div>
    <p><label style="cursor:pointer"><input type="checkbox" id="hp"> <b>聞き取りやすい音量に調節しました</b></label></p>
    <p><button class="primary" id="go2" disabled style="opacity:.5">次へ：見え方の確認</button></p>
    <p class="muted" id="volHint"></p>`;
  let played = false;
  const hp = document.getElementById("hp"), go2 = document.getElementById("go2");
  const ready = () => { const ok = played && hp.checked; go2.disabled = !ok; go2.style.opacity = ok ? "1" : ".5"; };
  document.getElementById("sample").onclick = () => {
    playSample(); played = true;
    document.getElementById("volHint").textContent = "小さすぎ・大きすぎと感じたら、端末の音量を変えてもう一度鳴らして確認してください。";
    ready();
  };
  hp.addEventListener("change", ready);
  go2.onclick = () => { if (played && hp.checked) visionCheck(); };
}
function visionCheck() {
  const resuming = !!(resumeState && resumeState.trials);
  screen.innerHTML = `<h2 style="color:#1E2A5E">見え方の確認</h2>
    <p>本番と同じ枠・同じ大きさで、見本の字「あ」を表示しています。
    ふだん画面を見る距離のまま、<b>はっきり見えること</b>を確認してください。見えにくい場合は画面の明るさを上げてください。</p>
    <div id="vcheck" style="text-align:center"></div>
    <p><label style="cursor:pointer"><input type="checkbox" id="vc"> <b>枠の中の文字がはっきり見えます</b></label></p>
    <p><button class="primary" id="go3" disabled style="opacity:.5">${resuming ? "続きから再開する" : "課題へ進む"}</button></p>`;
  const canvas = newCanvas();
  document.getElementById("vcheck").appendChild(canvas);
  drawChar(canvas.getContext("2d"), "あ");
  const vc = document.getElementById("vc"), go3 = document.getElementById("go3");
  vc.addEventListener("change", () => { go3.disabled = !vc.checked; go3.style.opacity = vc.checked ? "1" : ".5"; });
  go3.onclick = () => { if (vc.checked) start(); };
}

const T0 = Date.now();

(async function () {
  try {
    await preload();
    if (window.PROD && PROD.enabled) {
      resumeState = PROD.loadState("audio1char");
      if (resumeState && resumeState.completed) {
        screen.innerHTML = PROD.completionHTML(resumeState.duration_s || 0);
        return;
      }
      PROD.consentScreen(screen, "かなの課題", 15, intro, true,
        { noEnvNote: true, allowWireless: true,
          desc: "日本語のかな1文字が、短い音声や短い表示からどの程度認識できるかを調べる研究です" });
    }
    else intro();
  }
  catch (e) { screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}</p>`; }
})();
