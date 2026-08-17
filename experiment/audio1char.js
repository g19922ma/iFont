// =========================================================================
// 聴覚版 1文字課題 本実験 (統一モデルの C1=∅ = 発話先頭の特殊ケース)
//   - 単一のかなを発話先頭の音高 B3・1文字0.2秒で合成した音声を、frac% まで
//     再生して (truncation) 何の文字かを問う。frac=0 無音 / frac=100 完全 (catch)。
//   - 時間ゲートは再生時に Web Audio でライブ切り出し。実測の音響的開始(gate_onset_ms)を
//     起点に量子化済みゲイン(gate_gain)を適用し、窓の終わりはモーラの実体の末尾
//     (gate_avail_ms)に合わせる(2026-08-06 修正。char_dur_s からの引き算は
//     mp3 の復号遅れと音素長の量子化を見込まないため使わない)。
//   - 回答は固定50音グリッド(68字。を・ぢ・づ・ゔは同音のため除外、同音は併記ボタン)。
//     manifest は公開(回答なし・68刺激)、正解は answer_key(サーバ側)。
//
//   v2.0 (2026-08-17): jsPsych 実装を廃止し、乙課題(pilot_soa_audio.js)と同じ
//   自前実装・同じ参加者体験に書き直した。実験設計(200問・練習5問・frac 21水準・
//   catch 5%・合図音・自己ペース再生・反応時間の定義・記録の列構成)は v1 のまま。
//   追加された体験: 新しい同意文・図解つき教示・音量確認の必須化・進捗バー・
//   五十音表式のかな表・回答の確認(直す/決定)・途中再開(同じブラウザ)・完了コードのコピー。
// =========================================================================
"use strict";

const VERSION = "2.12";    // v1=jsPsych版(先生のmain)。v2=乙課題と同じ自前実装。
const N_TRIALS = 200;
const N_PRACTICE = 5;
const CATCH_RATE = 0.05;
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);
const FADE_MS = 8;
// 各問の音声の前後に鳴らす合図音(ビープ)。開始と終了が分かるようにするため。
const BEEP_HZ = 880;         // 合図音の高さ
const BEEP_MS = 80;          // 合図音1回の長さ
const BEEP_LEAD_MS = 600;    // 開始の合図音から、文字の音声が始まるまでの間隔(v1=300。短すぎて構えが間に合わないため延長・丸山判断 8/17)
const END_GAP_MS = 500;      // 文字の音声が終わってから、終了の合図音までの間隔
const END_BEEP_GAP_MS = 140; // 終了の合図音を2回鳴らすときの、1回目と2回目の間隔

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

// 68音の固定50音グリッド (pilot_soa_audio.js の GRID_AUDIO と一致=乙課題と統一)。
const GRID_AUDIO = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","ん"],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","","","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
];
const N_CHOICES = GRID_AUDIO.flat().filter(c => c !== "").length;   // 68
const HOMOPHONE_LABEL = { "お": "お／を", "じ": "じ／ぢ", "ず": "ず／づ" };
function kanaLabel(ch) { return HOMOPHONE_LABEL[ch] || ch; }

const screen = document.getElementById("screen");
let audioCtx = null;
const bufById = {};
let trials = [], results = [], ti = 0, mainStarted = false;
// 途中再開(本番モードのみ)。elapsedPrior は再開前までの経過秒。
let resumeState = null, elapsedPrior = 0;
let playBtnIntroduced = false;   // 再生ボタンの丁寧な文言は最初の1問だけ(以降は短く)
let manifest = null;
const stimByChar = {};   // サンプル音用: かな→刺激(正解表が読めたときだけ埋まる)

function ensureCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

// ---- 音の切り出し・再生 (v1 と同一の計算) --------------------------------
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
let _nodes = [];   // 予約済みの音声ノード。再生し直すときにまとめて止める。
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
// 1問の再生: 開始の合図音(1回) → 文字の音声 → (0.5秒後に)終了の合図音(2回)。
function playGated(stim) {
  const ctx = ensureCtx();
  stopAll();
  const t0 = ctx.currentTime + 0.02;
  playBeep(t0);
  const stimStart = t0 + BEEP_LEAD_MS / 1000;
  const stimDur = gateAvailS(stim) * stim.frac / 100;
  if (stim.frac > 0) {                              // 無音の問でも合図音は前後に鳴る
    const s = ctx.createBufferSource();
    s.buffer = gatedBuffer(bufById[stim.id], stim);
    s.connect(ctx.destination); s.start(stimStart);
    _nodes.push(s);
  }
  const endAt = stimStart + stimDur + END_GAP_MS / 1000;
  playBeep(endAt);
  playBeep(endAt + END_BEEP_GAP_MS / 1000);
}

// ---- 読み込み -------------------------------------------------------------
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
  let done = 0;
  await Promise.all(pool.map(async st => {
    const r = await fetch(`audio1char_stimuli/${st.id}.mp3`, {cache: "force-cache"});
    if (!r.ok) throw new Error(`audio1char_stimuli/${st.id}.mp3 ${r.status}`);
    bufById[st.id] = await ensureCtx().decodeAudioData(await r.arrayBuffer());
    done++; const bar = document.getElementById("loadBar");
    if (bar) bar.style.width = `${Math.round(done / pool.length * 100)}%`;
  }));
}

// ---- 出題の配り方 (v1 と同一) --------------------------------------------
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
// 混ぜた一組を順に配り、尽きたら混ぜ直して配り続ける。どの要素の出現数も差は高々1。
function dealEven(items, n) {
  const out = [];
  while (out.length < n) out.push(...shuffle([...items]));
  return out.slice(0, n);
}
function buildTrials() {
  const pool = manifest.stimuli;
  const nCatch = Math.round(N_TRIALS * CATCH_RATE);
  const nGraded = N_TRIALS - nCatch;
  const fracs = dealEven(FRAC_GRID, nGraded);
  const stims = dealEven(pool, N_TRIALS);
  const main = [];
  for (let i = 0; i < N_TRIALS; i++) {
    const isCatch = i >= nGraded;
    main.push(Object.assign({}, stims[i], {frac: isCatch ? 100 : fracs[i], is_catch: isCatch, practice: false}));
  }
  shuffle(main);
  // 練習: 聞き取りやすい水準から始めて短い水準も混ぜる(全部/ほぼ無音の両方を体験)。
  const ladder = [100, 80, 60, 40, 20];
  const pstims = dealEven(pool, N_PRACTICE);
  const prac = Array.from({length: N_PRACTICE}, (_, i) =>
    Object.assign({}, pstims[i], {frac: ladder[i % ladder.length], is_catch: false, practice: true}));
  return prac.concat(main);
}

// ---- 画面 -----------------------------------------------------------------
// 進行ヘッダー: 進捗バーは本番のみ。条件(frac)の表示は研究者モードのみ。
function progressHeader(inPractice, t) {
  const dev = (window.PROD && PROD.enabled) ? "" : ` (frac=${t.frac}%${t.is_catch ? "・catch" : ""})`;
  if (inPractice) return `<div class="muted">練習 ${ti+1} / ${N_PRACTICE}${dev}</div>`;
  const nMain = trials.length - N_PRACTICE;
  const done = ti - N_PRACTICE, pct = Math.round(done / nMain * 100);
  return `<div class="muted" style="display:flex;align-items:center;gap:10px">
    <span style="white-space:nowrap">本番</span>
    <span style="flex:1;height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden"><span style="display:block;height:100%;width:${pct}%;background:#2E7D8F"></span></span>
    <span style="white-space:nowrap">${pct}%${dev}</span></div>`;
}

// かな表(紙の五十音表式): 縦の列=行、右端があ行。上の表が清音、下の表が濁音・半濁音。
// 列幅は上下の表で揃え、列数の少ない表は左側を空列で埋めて右(あ行側)に寄せる。
function buildKanaGrid(done) {
  const grid = document.createElement("div"); grid.id = "grid"; grid.style.display = "block";
  const blocks = [GRID_AUDIO.slice(0, 10), GRID_AUDIO.slice(10)];
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
        const b = document.createElement("button"); b.className = "kana"; b.textContent = kanaLabel(ch);
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
  const inPractice = t.practice;
  if (!inPractice && !mainStarted) { mainStarted = true; return showMainGate(runTrial); }

  let tStim = null;      // 最初に鳴らし始めた時刻(反応時間の起点)
  let replays = 0;       // 「もう一度きく」を押した回数
  let picked = null, pickedRt = null;
  let autoTimer = null;  // 2問目以降の自動再生タイマー

  screen.innerHTML = `${progressHeader(inPractice, t)}
    <div id="stage">
      <div style="text-align:center;margin:30px 0 12px">
        <button id="playBtn" class="playbtn">${playBtnIntroduced ? "▶ 音をきく" : "▶ 準備ができたら音をきく（またはスペースキー）"}</button>
      </div>
      ${playBtnIntroduced ? "" : `<div class="muted" id="prompt" style="text-align:center">ボタンを押すと、ひらがな1文字の読み上げが流れます。聞こえた文字を下の表から選んでください。</div>`}
      <div id="answerArea"></div>
    </div>`;
  const stage = document.getElementById("stage");
  const playBtn = document.getElementById("playBtn");
  const answerArea = document.getElementById("answerArea");

  const finalize = () => {
    document.removeEventListener("keydown", keyHandler);
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    stopAll();
    const rec = { stimulus_id: t.id, response_char: picked, modality: "audio1char",
      q_set: "all", pitch_scheme: "B3", frac: t.frac, n_choices: N_CHOICES,
      replays, rt_ms: pickedRt, is_catch: t.is_catch, version: VERSION };
    if (!inPractice) {
      results.push(rec);
      if (window.PROD) PROD.saveFracTrial(rec);
      ti++;
      // 1問確定するたびに途中状態を保存。再開時はこの続きから。
      if (window.PROD && PROD.enabled) PROD.saveState("audio1char",
        { trials, results, ti, elapsed_s: Math.round(elapsedPrior + (Date.now() - T0) / 1000) });
      runTrial(); return;
    }
    results.push(Object.assign({practice: true}, rec));
    // 練習: 本人の答えだけを見せる(正解表は端末に無いため正解は表示できない)。
    // 解説は初回だけ詳しく、2問目からは答えの確認のみ(毎回読ませない)。
    const note = (ti === 0)
      ? `<p class="muted" style="line-height:1.8">これは練習です（答えは記録されません）。<br>
         ほとんど聞こえない問もありますが、もっとも近いと思う文字を選べばOKです。※この課題は正解を表示しません。</p>`
      : `<p class="muted">これは練習です。</p>`;
    screen.innerHTML = `<div style="text-align:center;padding:30px">
      <p style="font-size:17px">あなたの答え: <b style="font-size:24px">${picked ? kanaLabel(picked) : "（未選択）"}</b></p>
      ${note}</div>`;
    setTimeout(() => { ti++; runTrial(); }, ti === 0 ? 3000 : 1400);
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
    const grid = buildKanaGrid((ch) => {
      // 反応時間は「音が鳴り始めてから、その答えを選ぶまで」(v1と同じ定義。決定の時刻ではない)。
      picked = ch; pickedRt = Math.round(performance.now() - tStim);
      showConfirm();
    });
    answerArea.appendChild(grid);
    // 再生前は回答できないようにする(自己ペースで開始してもらうため)。
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
      playBtnIntroduced = true;
    } else {
      replays += 1;
    }
    playGated(t);
  };
  const keyHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); play(); } };

  playBtn.onclick = play;
  document.addEventListener("keydown", keyHandler);
  showGrid();
  // 2問目以降は自動で再生を始める(クリック回数の削減・丸山判断 8/17)。初回のみ手動開始。
  if (playBtnIntroduced) autoTimer = setTimeout(play, 700);
}

// 練習の後、本番に入る前の確認画面。
function showMainGate(next) {
  const nMain = trials.length - N_PRACTICE;
  screen.innerHTML = `<div style="text-align:center;padding:40px 20px">
    <h2 style="color:#1E2A5E">これから本番です</h2>
    <p>本番では、ここからの回答が記録されます。</p>
    <p class="muted">本番は <b>${nMain}問</b>です。やり方は練習と同じです。</p>
    <p style="margin-top:20px"><button class="primary" id="mainGo">本番を始める（またはスペースキー）</button></p></div>`;
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go() { document.removeEventListener("keydown", key); next(); }
  document.getElementById("mainGo").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
}

function showResults() {
  const durS = Math.round(elapsedPrior + (Date.now() - T0) / 1000);
  if (window.PROD && PROD.enabled) {
    // 完了印に置き換える: 誤って閉じても期限内なら完了コードを再表示できる。
    PROD.saveState("audio1char", { completed: true, duration_s: durS });
    screen.innerHTML = PROD.completionHTML(durS);
    return;
  }
  const main = results.filter(r => !r.practice);
  screen.innerHTML = `<h1>パイロット完了</h1>
    <p class="muted">回答 ${main.length} 問(正誤の採点は answer_key を持つ解析側で行う)。</p>
    <p><button class="primary" id="dl">結果JSONをダウンロード</button></p>`;
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify({
      config: { VERSION, N_TRIALS, N_PRACTICE, CATCH_RATE, FRAC_GRID, pitch_scheme: "B3" },
      env: ENV, duration_s: durS, trials: main }, null, 2)], {type: "application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `audio1char_${Date.now()}.json`; a.click();
  };
}

function start() {
  ensureCtx();
  if (resumeState && resumeState.trials) {
    // 続きから: 出題順・回答済みデータ・位置を保存時のまま復元(順番は作り直さない)。
    trials = resumeState.trials; results = resumeState.results || [];
    ti = resumeState.ti || 0; elapsedPrior = resumeState.elapsed_s || 0;
    mainStarted = true;   // 練習と本番前の確認画面はとばす(済んでいるため)
    return runTrial();
  }
  trials = buildTrials(); results = []; ti = 0; mainStarted = false; runTrial();
}

// 2A: 教示。
function intro() {
  const resumeNote = (resumeState && resumeState.trials)
    ? `<p style="background:#eef7ee;border:1px solid #bcd9bc;border-radius:8px;padding:10px 12px">
       <b>前回の続きから再開します</b>（本番 ${resumeState.ti - N_PRACTICE + 1}問目から）。
       <span class="muted" style="display:block;margin-top:4px;font-size:12.5px">練習はとばします。音量の確認だけもう一度お願いします。</span></p>` : "";
  screen.innerHTML = `<h1>聞き取り課題の進め方</h1>
    ${resumeNote}
    <p>この課題では、ひらがな<b>1文字</b>の読み上げが流れます。<b>聞こえた文字を、かなの表から選んでください。</b>
    読み上げは<b>途中までしか流れない</b>ことがあります。</p>
    <svg viewBox="0 0 640 150" style="width:100%;max-width:580px;display:block;margin:4px auto 8px" role="img" aria-label="課題の流れの図">
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
    <ol style="font-size:15px;line-height:1.9;padding-left:1.2em">
      <li>準備ができたら<b>「音をきく」ボタン</b>またはスペースキーを押します</li>
      <li>「ピッ」と<b>1回</b>鳴ったあとに読み上げが流れ、終わると「ピッピッ」と<b>2回</b>鳴ります</li>
      <li>聞こえたかなを表から選びます（<b>何度でも聞き直せます</b>）</li>
    </ol>
    <p style="background:#fff8ec;border:1px solid #eadfc8;border-radius:8px;padding:10px 12px">
    読み上げがとても短い問題や、ほとんど何も聞こえない問題もあります。
    その場合も、<b>もっとも近いと思う文字を選んでください</b>。</p>
    <p class="muted">かなは、単独で読んだときの音で流れます（例：「は」は「ハ」、「へ」は「ヘ」）。「じ／ぢ」のように同じ音になるかなは、1つの選択肢にまとめています。</p>
    <p><button class="primary" id="go">次へ：音量の確認</button></p>
    <p class="muted" style="text-align:right;font-size:12px;margin-top:6px">${(window.PROD&&PROD.enabled)?"津田塾大学 栗原研究室":"研究者向けパイロット版 v"+VERSION}</p>`;
  document.getElementById("go").onclick = volumeCheck;
}

// サンプル音: 「あ・い・う・え・お」を全長(frac=100)・0.5秒間隔で順に鳴らす(乙課題と同じ)。
// 正解表が読めず対応が引けない場合は、プールからのランダム3音に切り替える。
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
// 2B: 音量確認の独立画面。サンプル音を一度も鳴らさないうちは先へ進めない。
function volumeCheck() {
  const resuming = !!(resumeState && resumeState.trials);
  const mobileNote = ENV.touch
    ? `スマートフォンの内蔵スピーカーでは正しく聞き取れません。必ず<b>ヘッドホン／イヤホン</b>を使ってください。` : ``;
  screen.innerHTML = `<h2 style="color:#1E2A5E">音量の確認</h2>
    <p>下のボタンで<b>サンプル音</b>を鳴らし、聞き取りやすい音量になるよう端末の音量を調節してください。
    調節が終わったら、<b>この音量のまま</b>課題に進みます。</p>
    <p style="background:#eef4f6;border:1px solid #d3e2e7;border-radius:8px;padding:12px 14px">
      <button id="sample" class="playbtn">▶ サンプル音を鳴らす（あ・い・う・え・お）</button>
      <span class="muted" style="margin-left:8px">何度でも鳴らせます</span>
      <span class="muted" style="display:block;margin-top:6px">${mobileNote}この課題は静かな環境で行ってください。</span></p>
    <p><label style="cursor:pointer"><input type="checkbox" id="hp"> <b>聞き取りやすい音量に調節しました</b></label></p>
    <p><button class="primary" id="go2" disabled style="opacity:.5">${resuming ? "この音量で続きから再開する" : `この音量で練習を始める（${N_PRACTICE}問）`}</button></p>
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
  go2.onclick = () => { if (played && hp.checked) start(); };
}

const T0 = Date.now();   // 所要時間の起点

(async function () {
  try {
    await preload();
    // 本番モード(?prod=1)は同意画面を挟んでから教示へ。研究者パイロットは従来どおり直行。
    if (window.PROD && PROD.enabled) {
      resumeState = PROD.loadState("audio1char");  // 同じブラウザの途中状態(期限内)を拾う
      if (resumeState && resumeState.completed) {  // 完了済み: 完了コードを再表示するだけ
        screen.innerHTML = PROD.completionHTML(resumeState.duration_s || 0);
        return;
      }
      PROD.consentScreen(screen, "かなの音声を聞き、聞こえた文字を回答する課題", 20, intro, true,
        { noEnvNote: true, desc: "日本語のかな1文字が、短い音声からどの程度認識できるかを調べる研究です" });
    }
    else intro();
  }
  catch (e) { screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}</p>`; }
})();
