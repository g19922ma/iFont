// =========================================================================
// 視覚版 1文字課題 本実験 (統一モデルの C1=∅ = 先頭位置の特殊ケース)
//   - 固定領域に単一のかなを提示する。1文字にかける時間 (CHAR_MS) の中で
//     認識度が上がる提示アルゴリズムを使い、frac% 時点で消去する (時間ゲート)。
//     何の文字かを問う。1文字にかける時間は 200 ミリ秒と 133 ミリ秒の2水準。
//   - 提示アルゴリズムは ALGO_LIST から配る
//     (パイロット pilot_visual2char.html で絞り込んだら書き換える)。
//   - 文字は VISUAL 78字。base/<char>.png からブラウザ側で合成。正解は target_char を
//     申告して GAS が採点 (visual2char と同じチート耐性方針)。
//
//   2026-08 の改訂 (乙課題で導入済みの参加者体験を移植):
//     1. クリック開始 (自己ペース)。刺激は自動で始まらず、開始ボタン (またはスペース)
//        を押してから提示する。押すまでは回答ボタンを押せないようにしてある。
//     2. 教示と練習のフィードバック。何を答えるのか・難しくて当然であること・
//        勘で答えてよいことを、練習の各問のあとにも繰り返し伝える。
//     3. 出題の配り方。frac 水準・文字・アルゴリズムを均等に配ってから順序を混ぜる
//        (毎回独立に抽選すると水準と文字の出現が偏るため)。総試行数は 200 のまま。
//     4. 提示時間の実測 (actual_ms / actual_frames)。名目は CHAR_MS*frac/100 だが、
//        実際にはリフレッシュ周期に量子化されるので、描画フレームの実時刻から測る。
//     5. 本番モード (?prod=1)。同意画面・GAS 送信・完了コードは prod_common.js に一本化。
//
//   2026-08 の改訂その2 (提示速度の要因を追加):
//     1文字にかける時間 (CHAR_MS) を 200 ミリ秒に固定していたのをやめ、
//     200 ミリ秒と 133 ミリ秒の2水準にして参加者内で両方を実施する。
//       ・200 ミリ秒は毎秒 5.0 モーラに相当し、日本語能力試験 N5 の聴解音声
//         (毎秒 5.05 モーラ) とほぼ同じ、最も配慮された遅い読み上げ速度である。
//         聴覚課題の刺激プールがこの速度で作られているため、聴覚と視覚を
//         対応づけるときの基準点になる。
//       ・133 ミリ秒は毎秒 7.5 モーラに相当し、アナウンサーの標準的な
//         読み上げ速度に当たる。
//     frac は「提示アルゴリズムがどこまで進んだか」を表す無次元の量であり、
//     実際の露光時間は frac × CHAR_MS である。したがって速度水準を変えても
//     frac のグリッド (0 から 100 まで5刻みの21水準) はそのまま使える。
// =========================================================================

const N_TRIALS = 200;
const N_PRACTICE = 5;
const CATCH_RATE = 0.05;            // frac=100 (最後まで見せる) の統制試行

// 提示速度の要因。1文字にかける時間 (ミリ秒) の水準。
// 研究者のパイロット用に URL パラメータ ?charms= で上書きできる
// (例: ?charms=200 で1水準に固定、?charms=200,133 で明示的に2水準)。
const URL_PARAMS = new URLSearchParams(location.search);
const CHAR_MS_DEFAULT = [200, 133];
function parseCharMsParam(raw) {
  if (!raw) return CHAR_MS_DEFAULT.slice();
  const vals = raw.split(",")
    .map(s => Number(s.trim()))
    .filter(v => Number.isFinite(v) && v > 0);
  return vals.length ? vals : CHAR_MS_DEFAULT.slice();
}
const CHAR_MS_LIST = parseCharMsParam(URL_PARAMS.get("charms"));
// 教示で参加者に伝える速さの表現 (水準が1つのときはその値だけを書く)。
const SPEED_NOTE = (CHAR_MS_LIST.length > 1)
  ? `1文字あたり ${(Math.min(...CHAR_MS_LIST) / 1000).toFixed(2)} 〜 ${(Math.max(...CHAR_MS_LIST) / 1000).toFixed(2)} 秒`
  : `1文字あたり ${(CHAR_MS_LIST[0] / 1000).toFixed(2)} 秒`;

const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);
const FONT_TAG = "bizudgothic";
const SIZE = 256;
const STROKE_THRESH = 128;
const BLUR_MAX_PX = 12;

// 本実験に載せる提示アルゴリズム。刺激の強さの測定 (docs/visual_stimulus_intensity.md)
// にもとづき、fade・blur・moya の3種に絞った。stroke は 1/f からの逸脱が高く (ざらつき)、
// slideB・slideR・zoom は動きが速いため、目の疲労の観点で刺激が強いとして除外した。
// ALGOS には7種すべての実装を残してある (論文執筆の検討材料のため)。
const ALGO_LIST = ["fade", "blur", "moya"];

// 端末・表示環境 (実測タイミングの解釈に使う。pilot_soa_visual2.js と同じ測り方)。
const ENV = { ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
  screen: `${window.screen.width}x${window.screen.height}`,
  touch: (navigator.maxTouchPoints || 0) > 0, refreshHz: null };
(function measureRefresh() {
  let n = 0; const t0 = performance.now();
  function f(now) { n++; if (n < 40) requestAnimationFrame(f); else ENV.refreshHz = Math.round(1000 / ((now - t0) / n)); }
  requestAnimationFrame(f);
})();
PROD.setEnv(ENV);

const CHARS = [
  ..."あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん",
  ..."がぎぐげござじずぜぞだぢづでどばびぶべぼ",
  ..."ぱぴぷぺぽ",
  ..."っゃゅょ",
  ..."ゐゑ",
  ..."ゔ",
];
const GRID_78 = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ゃ","","ゅ","","ょ"],["っ","","","",""],
  ["ゐ","","","","ゑ"],
  ["ゔ","","","",""],
];
const GRID_FLAT = GRID_78.flat();
const GRID_COLS = 5;
const GRID_ROWS = GRID_78.length;
const N_CHOICES = CHARS.length;   // 78

// 参加者ID・完了コード・送信は prod_common.js に一本化してある (二重管理をなくすため)。
const participantId = PROD.participantId;
const completionCode = PROD.completionCode;

const jsPsych = initJsPsych({
  display_element: document.body,
  show_progress_bar: true,
  message_progress_bar: "進捗",
});

let _replays = 0;          // 「もう一度みる」を押した回数
let rafId = null;
let _meas = null;          // その問の最初の提示の実測 {actual_ms, actual_frames}
let _tTrial = 0;           // 問が画面に出た時刻 (jsPsych の rt の起点)
let _tStim = null;         // 最初に提示を始めた時刻 (反応時間の起点)
let _spaceHandler = null;

// ---- 描画: 画像読込 + 提示アルゴリズム (visual2char.js と同一) --------------
let imgs = {};
let strokeIdx = {};
let overlayCanvas = null;

function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function loadImage(ch) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error(`base/${ch}.png の読み込みに失敗`));
    im.src = `base/${encodeURIComponent(ch)}.png`;
  });
}
async function loadAllImages() {
  const off = document.createElement("canvas");
  off.width = off.height = SIZE;
  const octx = off.getContext("2d", { willReadFrequently: true });
  const meanInk = new Float32Array(SIZE * SIZE);
  for (const ch of CHARS) {
    const im = await loadImage(ch);
    imgs[ch] = im;
    octx.fillStyle = "#fff";
    octx.fillRect(0, 0, SIZE, SIZE);
    octx.drawImage(im, 0, 0, SIZE, SIZE);
    const d = octx.getImageData(0, 0, SIZE, SIZE).data;
    const idx = [];
    for (let i = 0; i < SIZE * SIZE; i++) {
      const lum = (d[i * 4] + d[i * 4 + 1] + d[i * 4 + 2]) / 3;
      if (lum <= STROKE_THRESH) idx.push(i);
      meanInk[i] += 255 - lum;
    }
    const rnd = mulberry32(ch.codePointAt(0) * 2654435761 % 4294967296);
    for (let i = idx.length - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1));
      [idx[i], idx[j]] = [idx[j], idx[i]];
    }
    strokeIdx[ch] = Uint32Array.from(idx);
  }
  overlayCanvas = document.createElement("canvas");
  overlayCanvas.width = overlayCanvas.height = SIZE;
  const oc = overlayCanvas.getContext("2d");
  const od = oc.createImageData(SIZE, SIZE);
  for (let i = 0; i < SIZE * SIZE; i++) {
    const lum = Math.max(0, Math.min(255, 255 - meanInk[i] / CHARS.length));
    od.data[i * 4] = od.data[i * 4 + 1] = od.data[i * 4 + 2] = lum;
    od.data[i * 4 + 3] = 255;
  }
  oc.putImageData(od, 0, 0);
}
function clearStage(ctx) {
  ctx.filter = "none"; ctx.globalAlpha = 1;
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, SIZE, SIZE);
}
const ALGOS = {
  fade(ctx, ch, u) { clearStage(ctx); ctx.globalAlpha = u; ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE); ctx.globalAlpha = 1; },
  stroke(ctx, ch, u) {
    clearStage(ctx);
    const idx = strokeIdx[ch]; const k = Math.floor(idx.length * u);
    const img = ctx.getImageData(0, 0, SIZE, SIZE); const d = img.data;
    for (let i = 0; i < k; i++) { const p = idx[i] * 4; d[p] = d[p + 1] = d[p + 2] = 0; }
    ctx.putImageData(img, 0, 0);
  },
  zoom(ctx, ch, u) { clearStage(ctx); if (u <= 0) return; const s = SIZE * u; ctx.drawImage(imgs[ch], (SIZE - s) / 2, (SIZE - s) / 2, s, s); },
  blur(ctx, ch, u) { clearStage(ctx); ctx.filter = `blur(${(1 - u) * BLUR_MAX_PX}px)`; ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE); ctx.filter = "none"; },
  moya(ctx, ch, u) { clearStage(ctx); ctx.globalAlpha = 1 - u; ctx.drawImage(overlayCanvas, 0, 0); ctx.globalAlpha = u; ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE); ctx.globalAlpha = 1; },
  slideB(ctx, ch, u) { clearStage(ctx); ctx.drawImage(imgs[ch], 0, (1 - u) * SIZE, SIZE, SIZE); },
  slideR(ctx, ch, u) { clearStage(ctx); ctx.drawImage(imgs[ch], (1 - u) * SIZE, 0, SIZE, SIZE); },
};

// 単一のかなを 0→frac/100 まで提示 (名目 0〜charMs*frac/100 ミリ秒) して消去する。
// charMs はその試行の提示速度 (200 または 133 ミリ秒)。frac は無次元の進み具合なので、
// 速度が変わっても frac のグリッドはそのまま使える。
// 名目の提示時間は画面のリフレッシュ周期に量子化されるため、実際に描画した最初の
// フレームから消去したフレームまでの経過時間と、描画したフレーム数を実測して返す。
function playSeq(ctx, ch, frac, algoName, charMs, onDone) {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  const render = ALGOS[algoName];
  const end = charMs * frac / 100;
  const t0 = performance.now();
  let tFirst = null, frames = 0;
  function frame(now) {
    const el = now - t0;
    if (el < end) {
      render(ctx, ch, el / charMs);
      if (tFirst === null) tFirst = now;
      frames += 1;
      rafId = requestAnimationFrame(frame);
      return;
    }
    // 消去したフレーム。frac=0 では一度も描画しないので実測は 0ms・0フレームになる。
    clearStage(ctx);
    rafId = null;
    if (onDone) onDone({ actual_ms: (tFirst === null) ? 0 : Math.round(now - tFirst), actual_frames: frames });
  }
  clearStage(ctx);
  rafId = requestAnimationFrame(frame);
}

// ---- 試行の生成 -------------------------------------------------------------
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
// 混ぜた一組を順に配り、尽きたら混ぜ直して配り続ける。どの要素の出現数も差は高々1になる。
// 毎回独立に抽選すると、水準や文字の出現数が偶然かたよって成績を歪めるため
// (乙課題 pilot_soa_*.js の dealPairs と同じ考え方)。
function dealEven(items, n) {
  const out = [];
  while (out.length < n) out.push(...shuffle([...items]));
  return out.slice(0, n);
}
function specId(ch, algo, frac, charMs) {
  return `v1c-${ch}-${algo}-f${String(frac).padStart(3, "0")}-c${charMs}`;
}
// 速度水準ごとの試行数。総試行数を水準数で割り、割り切れない余りは先頭の水準から1問ずつ配る
// (既定の2水準・総数200問なら 100問ずつになる)。
function splitByLevel(total, nLevels) {
  const base = Math.floor(total / nLevels);
  const rest = total - base * nLevels;
  return Array.from({length: nLevels}, (_, i) => base + (i < rest ? 1 : 0));
}
// 本番 N_TRIALS 問。速度2水準 × frac21水準が均等になるように配り、
// さらに文字とアルゴリズムも全体で均等に配ってから順序を混ぜる。
// frac は速度水準ごとに独立に均等配分する。こうすると「速度水準ごとの試行数」と
// 「速度 × frac のセルの試行数」の両方をできるだけそろえられる。
function buildMainSpecs() {
  const chars = dealEven(CHARS, N_TRIALS);            // 78字にできるだけ均等
  const algos = dealEven(ALGO_LIST, N_TRIALS);
  const perSpeed = splitByLevel(N_TRIALS, CHAR_MS_LIST.length);
  const specs = [];
  let i = 0;
  CHAR_MS_LIST.forEach((charMs, s) => {
    const n = perSpeed[s];
    const nCatch = Math.round(n * CATCH_RATE);        // frac=100 の統制試行
    const nGraded = n - nCatch;
    const fracs = dealEven(FRAC_GRID, nGraded);       // 21水準にできるだけ均等
    for (let j = 0; j < n; j++, i++) {
      const isCatch = j >= nGraded;
      const frac = isCatch ? 100 : fracs[j];
      specs.push({ ch: chars[i], frac, algo: algos[i], char_ms: charMs,
        is_catch: isCatch, id: specId(chars[i], algos[i], frac, charMs) });
    }
  });
  return shuffle(specs);
}
// 練習 N_PRACTICE 問。見やすい水準から始めて短い水準も混ぜ、
// 「最後まで見える問も、ほとんど見えない問もある」ことを体験してもらう。
// 提示速度も両方の水準を体験できるように交互に配る。
function buildPracticeSpecs() {
  const ladder = [100, 80, 60, 40, 20];
  const chars = dealEven(CHARS, N_PRACTICE);
  const algos = dealEven(ALGO_LIST, N_PRACTICE);
  const charMss = dealEven(CHAR_MS_LIST, N_PRACTICE);
  return Array.from({length: N_PRACTICE}, (_, i) => {
    const frac = ladder[i % ladder.length];
    return { ch: chars[i], frac, algo: algos[i], char_ms: charMss[i],
      is_catch: false, id: specId(chars[i], algos[i], frac, charMss[i]) };
  });
}

function buttonHtml(choice) {
  if (choice === "") return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
  return `<button class="jspsych-btn grid-kana">${choice}</button>`;
}

// 回答用の50音ボタン。提示前は押せないようにして、開始してから答えてもらう。
function answerButtons() {
  const group = document.querySelector("#jspsych-html-button-response-btngroup, .jspsych-html-button-response-btngroup");
  if (!group) return [];
  return Array.from(group.querySelectorAll("button")).filter(b => !b.disabled);
}

function makeTrial(spec, isPractice = false) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <div class="stim-wrap">
        <canvas id="stim-canvas" width="${SIZE}" height="${SIZE}"></canvas>
        <button type="button" id="play-btn" class="replay-btn">準備ができたら開始（またはスペースキー）</button>
      </div>
      <div class="trial-prompt">ボタンを押すと、ひらがな1文字が一瞬だけ表示されます。何の文字か、50音表から選んでください</div>`,
    choices: GRID_FLAT,
    button_html: buttonHtml,
    grid_rows: GRID_ROWS,
    grid_columns: GRID_COLS,
    on_load: () => {
      _replays = 0; _meas = null; _tStim = null;
      _tTrial = performance.now();
      const canvas = document.getElementById("stim-canvas");
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      clearStage(ctx);
      const btn = document.getElementById("play-btn");
      // 提示前は回答できないようにする (自己ペースで開始してもらうため)。
      const answers = answerButtons();
      answers.forEach(b => { b.disabled = true; b.style.opacity = ".45"; });
      const play = () => {
        if (_tStim === null) {
          _tStim = performance.now();                     // 反応時間の起点
          answers.forEach(b => { b.disabled = false; b.style.opacity = ""; });
          if (btn) btn.textContent = "▶ もう一度みる";
        } else {
          _replays += 1;
        }
        playSeq(ctx, spec.ch, spec.frac, spec.algo, spec.char_ms, (m) => { if (!_meas) _meas = m; });
      };
      if (btn) btn.addEventListener("click", play);
      _spaceHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); play(); } };
      document.addEventListener("keydown", _spaceHandler);
    },
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: spec.id,
      modality: "visual1char",
      q_set: "all",
      font: FONT_TAG,
      target_char: spec.ch,
      algo: spec.algo,
      frac: spec.frac,
      char_ms: spec.char_ms,     // その試行の提示速度 (200 または 133 ミリ秒)
      n_choices: N_CHOICES,
      is_catch: spec.is_catch,
    },
    on_finish: (data) => {
      if (_spaceHandler) { document.removeEventListener("keydown", _spaceHandler); _spaceHandler = null; }
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      data.response_char = GRID_FLAT[data.response];
      data.replays = _replays;
      // 反応時間は「提示が始まってから回答するまで」。開始ボタンを押すまでの待ち時間は含めない
      // (自己ペース開始にしたため、jsPsych の rt をそのまま使うと待ち時間が混ざる)。
      data.rt_ms = (_tStim === null) ? data.rt : Math.round(data.rt - (_tStim - _tTrial));
      data.actual_ms = _meas ? _meas.actual_ms : "";
      data.actual_frames = _meas ? _meas.actual_frames : "";
      data.refresh_hz = ENV.refreshHz;
      if (isPractice) return;
      PROD.saveFracTrial({
        stimulus_id: data.stimulus_id, response_char: data.response_char,
        target_char: data.target_char, modality: data.modality, q_set: data.q_set,
        font: data.font, algo: data.algo, frac: data.frac, char_ms: data.char_ms,
        n_choices: data.n_choices,
        replays: data.replays, rt_ms: data.rt_ms, is_catch: data.is_catch,
        actual_ms: data.actual_ms, actual_frames: data.actual_frames,
      });
    },
  };
}

// 練習のフィードバック。正解を示しつつ、難しくて当然であること・勘でよいことを伝える。
function makeFeedback(spec) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: () => {
      const last = jsPsych.data.get().last(1).values()[0] || {};
      const ok = last.response_char === spec.ch;
      return `<div style="padding:16px 8px">
        <p style="font-size:17px">正解は「<b style="font-size:24px">${spec.ch}</b>」でした
          <span style="color:${ok ? "#2E7D8F" : "#C25B4E"};font-weight:700">${ok ? "◯" : "×"}</span></p>
        <p style="font-size:14px;color:#555;line-height:1.8">これは練習です。答えは記録されません。<br>
          <b>難しくて当然の課題</b>です。ほとんど見えない問もあります。
          見えなかったと感じても空欄にせず、<b>勘で選んで</b>ください。正誤は報酬に影響しません。</p></div>`;
    },
    choices: ["次へ"],
    trial_duration: 5000,
    data: { task: "practice_feedback" },
  };
}

function downloadResults() {
  const payload = {
    config: { N_TRIALS, N_PRACTICE, CATCH_RATE, CHAR_MS_LIST, FRAC_GRID, ALGO_LIST, FONT_TAG },
    env: ENV,
    trials: jsPsych.data.get().filter({task: "main"}).values(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `visual1char_${Date.now()}.json`;
  a.click();
}

async function run() {
  const loading = document.createElement("p");
  loading.style.cssText = "padding:40px;color:#4a76d6;";
  loading.textContent = "文字画像を読み込み中…";
  document.body.appendChild(loading);
  try { await loadAllImages(); }
  catch (e) { loading.textContent = "画像の読み込みに失敗しました: " + e.message; loading.style.color = "#900"; return; }
  loading.remove();

  // 本番モード(?prod=1)は、jsPsych を始める前に同意画面を挟む。
  if (PROD.enabled) {
    await new Promise((resolve) => {
      const box = document.createElement("div");
      box.className = "prod-consent";
      document.body.appendChild(box);
      PROD.consentScreen(box, "かなの見分けの課題（画面表示・約20分）", 20,
        () => { box.remove(); resolve(); }, false);
    });
  }

  const practiceSpecs = buildPracticeSpecs();
  const mainSpecs = buildMainSpecs();

  // 研究者パイロット(?prod なし)のときだけ出す同意ページ。本番モードは prod_common.js の同意画面を使う。
  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験（視覚・1文字版）</h2>
       <p>本実験は、画面にすばやく表示される文字の読み取りやすさを測ることを目的としています。
       所要時間は約 20 分です。ご協力ありがとうございます。</p>
       <p><b>文字が短い時間 (${SPEED_NOTE}) で表示されます。</b>
       表示の速さは問題ごとに変わります。画面がよく見える明るさ・距離でご参加ください。</p>
       <p>取得するデータ: 各設問への回答とその所要時間、参加識別子。
       個人を特定する情報は収集しません。</p>
       <p><b>続けて参加することに同意される場合は「次へ」を押してください。</b></p>`,
    ],
    show_clickable_nav: true, button_label_next: "同意して次へ",
  };
  const instructions = {
    type: jsPsychInstructions,
    pages: [
      `<h2>課題</h2>
       <p>各問で、ひらがなが <b>1文字だけ</b> 同じ場所に表示されます。
       ${SPEED_NOTE}の速さで、字は「だんだん現れる」ように表示されます
       (現れかたも表示の速さも問題ごとにさまざまです)。</p>
       <p>各問は <b>自分のペース</b> で始められます。表示枠の下の
       <b>[準備ができたら開始]</b> ボタン (またはスペースキー) を押すと、そこで文字が表示されます。
       押すまでは何も起きませんので、落ち着いてから始めてください。</p>
       <p>押したあと、同じボタンが「▶ もう一度みる」に変わり、<b>何度でも</b> 見直せます。
       下の <b>50音表</b>(濁音・半濁音などを含む 78 字)から、見えた 1 文字を選んでください。
       表は毎回同じ並びです。</p>`,
      `<h2>答え方</h2>
       <p><b>難しくて当然の課題です。</b>ごく一瞬で消える問もあれば、最後まで見える問もあります。
       ほとんど何も見えない問も混ざっています。</p>
       <p>見えなかったと感じたときも、<b>勘で1文字を選んでください</b>。
       外れた答えも大切なデータです。正誤は報酬に影響しません。</p>
       <p>確信が持てなくても構いません。考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。
       練習では毎回、正解をお見せします。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true, button_label_next: "練習を始める",
  };
  // 練習は1問ごとに正解を見せる (乙課題と同じ流れ)。
  const practiceBlock = practiceSpecs.flatMap(s => [makeTrial(s, true), makeFeedback(s)]);
  const mainStart = {
    type: jsPsychInstructions,
    pages: [
      `<h2>練習終了</h2>
       <p>続いて本番 ${mainSpecs.length} 問に入ります。
       本番では <b>正解は表示されません</b>。ここからの回答が記録されます。</p>
       <p>やり方は練習と同じです。分からない問は勘で選んでください。
       静かで集中できる環境で挑んでください。</p>
       <p>準備ができたら「本番を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true, button_label_next: "本番を始める",
  };
  const mainBlock = mainSpecs.map(s => makeTrial(s, false));
  const finish = {
    type: jsPsychHtmlButtonResponse,
    stimulus: () => {
      const sec = Math.round(jsPsych.getTotalTime() / 1000);
      if (PROD.enabled) return PROD.completionHTML(sec);
      return `
      <h2>ご協力ありがとうございました</h2>
      <p>下の <b>完了コード</b> を、応募元の入力欄に貼り付けてください。</p>
      <p><span class="completion-code">${completionCode}</span></p>
      <p style="font-size:12px;color:#666;">参加者ID: ${participantId} ／ 所要時間: ${sec} 秒</p>
      <p><button type="button" id="dl-btn" class="replay-btn">結果JSONをダウンロード</button></p>`;
    },
    choices: ["閉じる"],
    on_load: () => {
      const b = document.getElementById("dl-btn");
      if (b) b.addEventListener("click", downloadResults);
    },
  };

  const timeline = [];
  if (!PROD.enabled) timeline.push(consent);
  timeline.push(instructions, ...practiceBlock, mainStart, ...mainBlock, finish);
  jsPsych.run(timeline);
}

run();
