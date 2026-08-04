// =========================================================================
// 視覚版 2文字課題 本実験 (2026-07-02 設計改訂版)
//   - 固定領域に C1→C2 を各 0.2 秒で提示。前の文字は一瞬で消去する
//     (統制条件。残存条件では C1 が薄くなりながら重なって残る。下記の改訂その2)。
//     C2 は frac% 時点で消去 (聴覚 truncation の視覚版)。2文字目を当てる。
//   - 提示アルゴリズムは ALGO_LIST から配る
//     (パイロット pilot_visual2char.html で比較して絞り込んだら書き換える)。
//   - 文字は VISUAL 78字。C1 も C2 も全78字から配る (競技かるた語彙に限定しない)。
//   - 刺激は base/<char>.png からブラウザ側で合成 (事前レンダリング不要)。
//     このため正解はクライアント側にあり、GAS へは target_char を申告して採点する
//     (音声2文字も全長音声がファイルに入るため、チート耐性は同水準。
//      catch 試行と反応時間フィルタで担保する方針は他課題と同じ)。
//
//   2026-08 の改訂 (乙課題で導入済みの参加者体験を移植):
//     1. クリック開始 (自己ペース)。刺激は自動で始まらず、開始ボタン (またはスペース)
//        を押してから提示する。押すまでは回答ボタンを押せないようにしてある。
//     2. 教示と練習のフィードバック。何を答えるのか・難しくて当然であること・
//        勘で答えてよいことを、練習の各問のあとにも繰り返し伝える。
//     3. 出題の配り方。frac 水準・文字・アルゴリズムを均等に配ってから順序を混ぜる。
//        この時点では総試行数は 200 だった (先行文字の残存の要因を足したのにともない
//        400 に増やした。下記の改訂その2を見よ)。
//     4. C2 の提示時間の実測 (actual_ms / actual_frames)。名目は CHAR_MS*frac/100 だが、
//        実際にはリフレッシュ周期に量子化されるので、描画フレームの実時刻から測る。
//     5. 本番モード (?prod=1)。同意画面・GAS 送信・完了コードは prod_common.js に一本化。
//
//   2026-08 の改訂その2 (先行文字の残存の要因を追加):
//     提示方式を2水準にした。
//       ・"none"  (統制・従来どおり): C1 が消えてから C2 が出る。
//       ・"decay" (先行文字の残存):   C2 の提示中も C1 が薄くなりながら同じ枠に
//         重なって残る。C1 の不透明度は C2 の提示開始時刻を起点として
//         alpha = exp(-t / TAU_MS) の指数減衰にする。
//     この条件で増えるのは C1 の可視時間だけであり、C2 の可視時間は一切変わらない。
//     回答対象は C2 なので、「長く見せただけ」という交絡が生じない設計になっている。
//     C2 の提示開始時刻 (CHAR_MS) と打ち切り時刻 (CHAR_MS + CHAR_MS*frac/100) は
//     両条件で完全に同一である。この性質を壊さないこと。
//     要因を1つ足したぶん総試行数も 200 から 400 に増やし、条件ごとに従来と同じ
//     200試行を確保する (精度目標「字ごとに約88観測」を条件ごとに保つため)。
// =========================================================================

const N_PRACTICE = 5;
const CATCH_RATE = 0.05;          // frac=100 (C2 を最後まで見せる) の統制試行
const CHAR_MS = 200;              // 1文字の提示時間 (競技かるたの規定 0.2 秒)
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);

const URL_PARAMS = new URLSearchParams(location.search);

// 先行文字 (C1) の残存の条件。"none" は統制 (従来どおり)、"decay" は指数減衰で重ねて残す。
// 研究者のパイロット用に URL パラメータ ?overlap= で上書きできる
// (例: ?overlap=decay で残存条件だけに固定できる)。
const OVERLAP_LIST_DEFAULT = ["none", "decay"];
function parseOverlapParam(raw) {
  if (!raw) return OVERLAP_LIST_DEFAULT.slice();
  const vals = raw.split(",").map(s => s.trim())
    .filter(v => OVERLAP_LIST_DEFAULT.indexOf(v) >= 0);
  return vals.length ? vals : OVERLAP_LIST_DEFAULT.slice();
}
const OVERLAP_LIST = parseOverlapParam(URL_PARAMS.get("overlap"));

// C1 の減衰の時定数 (ミリ秒)。
// ※これは仮の値である。視覚的な残像・図像記憶の減衰の文献にもとづいて後日確定する。
//   確定するまでは、この1箇所だけを書き換えれば全体に反映される。
//   研究者のパイロット用に URL パラメータ ?tau= で上書きできる (例: ?tau=150)。
const TAU_MS_DEFAULT = 100;
const _tauParam = Number(URL_PARAMS.get("tau"));
const TAU_MS = (Number.isFinite(_tauParam) && _tauParam > 0) ? _tauParam : TAU_MS_DEFAULT;

// 総試行数は「条件水準ごとの試行数 × 水準数」で決める。
//   要因を1つ足したぶん総試行数も増やす必要がある。精度目標は「字ごとに約88観測」であり、
//   これは字ごとの推定の標準誤差を約5.4ポイントに収めるための値で、干渉判定のマージン
//   δ=8ポイントを正当化する根拠になっている。総試行数を据え置いて水準で割ると
//   観測数が半減し、標準誤差が約7.6ポイントに悪化して δ の正当化が成り立たなくなる。
//   そのため、条件ごとに従来と同じ観測数 (200試行) を確保する。
//   2水準なら 400問 (所要 約26分) になる。
const N_PER_LEVEL = 200;
// 研究者のパイロットで1水準に固定したときは、1本が長すぎて試しにくいので従来の 200問に戻す
// (本番の精度目標は2水準そろえて実施したときのものなので、パイロットには適用しない)。
const N_TRIALS_PILOT = 200;
const N_TRIALS = (OVERLAP_LIST.length > 1)
  ? N_PER_LEVEL * OVERLAP_LIST.length
  : N_TRIALS_PILOT;

// 所要時間の目安 (分)。本番設計 (2水準・400問) で約26分。
// 試行数を変えたパイロットでは、それに比例させた見込みを表示する。
const EST_MINUTES_FULL = 26;
const N_TRIALS_FULL = N_PER_LEVEL * OVERLAP_LIST_DEFAULT.length;
const EST_MINUTES = Math.max(1, Math.round(EST_MINUTES_FULL * N_TRIALS / N_TRIALS_FULL));

const FONT_TAG = "bizudgothic";   // base/ 画像のフォント
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

// =========================================================================
// VISUAL 78字と固定50音グリッド (pilot_visual2char.js と一致)
// =========================================================================
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
const N_CHOICES = CHARS.length;   // 78, γ = 1/78

// =========================================================================
// Setup
// =========================================================================
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

// =========================================================================
// 描画: 画像読込 + 提示アルゴリズム (pilot_visual2char.js と同じ方式)
// =========================================================================
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
  ctx.filter = "none";
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, SIZE, SIZE);
}

const ALGOS = {
  fade(ctx, ch, u) {
    clearStage(ctx);
    ctx.globalAlpha = u;
    ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    ctx.globalAlpha = 1;
  },
  stroke(ctx, ch, u) {
    clearStage(ctx);
    const idx = strokeIdx[ch];
    const k = Math.floor(idx.length * u);
    const img = ctx.getImageData(0, 0, SIZE, SIZE);
    const d = img.data;
    for (let i = 0; i < k; i++) {
      const p = idx[i] * 4;
      d[p] = d[p + 1] = d[p + 2] = 0;
    }
    ctx.putImageData(img, 0, 0);
  },
  zoom(ctx, ch, u) {
    clearStage(ctx);
    if (u <= 0) return;
    const s = SIZE * u;
    ctx.drawImage(imgs[ch], (SIZE - s) / 2, (SIZE - s) / 2, s, s);
  },
  blur(ctx, ch, u) {
    clearStage(ctx);
    ctx.filter = `blur(${(1 - u) * BLUR_MAX_PX}px)`;
    ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    ctx.filter = "none";
  },
  moya(ctx, ch, u) {
    clearStage(ctx);
    ctx.globalAlpha = 1 - u;
    ctx.drawImage(overlayCanvas, 0, 0);
    ctx.globalAlpha = u;
    ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
    ctx.globalAlpha = 1;
  },
  slideB(ctx, ch, u) {
    clearStage(ctx);
    ctx.drawImage(imgs[ch], 0, (1 - u) * SIZE, SIZE, SIZE);
  },
  slideR(ctx, ch, u) {
    clearStage(ctx);
    ctx.drawImage(imgs[ch], (1 - u) * SIZE, 0, SIZE, SIZE);
  },
};

// 残存条件で C1 と C2 を重ねて描くための作業用キャンバス。
// 既存の ALGOS の描画関数は先頭で必ず白く塗りつぶすため、そのまま同じ枠に2回呼ぶと
// あとの描画が前の描画を白で消してしまう。そこで、いったん作業用キャンバスにそれぞれを
// 描いてから本番の枠に合成する。
let layer1 = null, layer1Ctx = null, layer2 = null, layer2Ctx = null;
function ensureLayers() {
  if (layer1) return;
  layer1 = document.createElement("canvas");
  layer1.width = layer1.height = SIZE;
  layer1Ctx = layer1.getContext("2d", { willReadFrequently: true });
  layer2 = document.createElement("canvas");
  layer2.width = layer2.height = SIZE;
  layer2Ctx = layer2.getContext("2d", { willReadFrequently: true });
}

// 残存条件の1フレーム。まず C1 をその不透明度で描き、その上に C2 を重ねる。
//   ・C1 は最終状態 (u=1、完全に現れた状態) を、C2 の提示開始からの経過時間 t に対して
//     alpha = exp(-t / TAU_MS) の不透明度で描く。作業用キャンバスは白地なので、
//     不透明度を下げて重ねると「白に向かって薄くなる」ことになる。
//   ・C2 は乗算合成 (multiply) で上に重ねる。白地どうしの乗算なので、
//     C2 の白い部分では下の C1 の残りがそのまま残り、C2 の墨の部分だけが濃くなる。
//     単純に上書きすると C2 の白い背景で C1 を消してしまうため、乗算にしている。
function drawOverlapped(ctx, render, c1, c2, u2, tSinceC2) {
  ensureLayers();
  const alpha = Math.exp(-tSinceC2 / TAU_MS);
  clearStage(ctx);
  render(layer1Ctx, c1, 1);
  ctx.globalAlpha = alpha;
  ctx.drawImage(layer1, 0, 0);
  ctx.globalAlpha = 1;
  render(layer2Ctx, c2, u2);
  ctx.globalCompositeOperation = "multiply";
  ctx.drawImage(layer2, 0, 0);
  ctx.globalCompositeOperation = "source-over";
}

// C1 を 0→0.2s で提示し、C2 は frac% 時点で消去。経過時間ベース。
// 統制条件 (overlap="none") では 0.2s で C1 を一瞬で消去する。
// 残存条件 (overlap="decay") では C2 の提示中も C1 が指数減衰しながら重なって残る。
// どちらの条件でも C2 の提示開始時刻 (CHAR_MS) と打ち切り時刻 (c2End) は同一であり、
// C2 の可視時間は条件によって変わらない (これがこの要因の設計上の要である)。
// 名目の C2 の提示時間 (CHAR_MS*frac/100) は画面のリフレッシュ周期に量子化されるため、
// C2 を最初に描画したフレームから消去したフレームまでの経過時間とフレーム数を実測して返す。
function playSeq(ctx, c1, c2, frac, algoName, overlap, onDone) {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  const render = ALGOS[algoName];
  const c2End = CHAR_MS + CHAR_MS * frac / 100;
  const t0 = performance.now();
  let tFirst2 = null, frames2 = 0;
  function frame(now) {
    const el = now - t0;
    if (el < CHAR_MS) {
      render(ctx, c1, el / CHAR_MS);
    } else if (el < c2End) {
      if (overlap === "decay") {
        drawOverlapped(ctx, render, c1, c2, (el - CHAR_MS) / CHAR_MS, el - CHAR_MS);
      } else {
        render(ctx, c2, (el - CHAR_MS) / CHAR_MS);
      }
      if (tFirst2 === null) tFirst2 = now;
      frames2 += 1;
    } else {
      // C2 を消去したフレーム。frac=0 では C2 を一度も描画しないので実測は 0ms・0フレーム。
      clearStage(ctx);
      rafId = null;
      if (onDone) onDone({ actual_ms: (tFirst2 === null) ? 0 : Math.round(now - tFirst2), actual_frames: frames2 });
      return;
    }
    rafId = requestAnimationFrame(frame);
  }
  clearStage(ctx);
  rafId = requestAnimationFrame(frame);
}

// =========================================================================
// 試行の生成 (クライアント側で C1/C2/frac/アルゴリズムを組む)
// =========================================================================
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
function specId(c1, c2, algo, frac, overlap) {
  return `v2c-${c1}${c2}-${algo}-f${String(frac).padStart(3, "0")}-${overlap}`;
}
// 条件水準ごとの試行数。総試行数を水準数で割り、割り切れない余りは先頭の水準から1問ずつ配る
// (既定の2水準・総数200問なら 100問ずつになる)。
function splitByLevel(total, nLevels) {
  const base = Math.floor(total / nLevels);
  const rest = total - base * nLevels;
  return Array.from({length: nLevels}, (_, i) => base + (i < rest ? 1 : 0));
}
// C1 と C2 を配る。採点対象は C2 なので C2 の均等配分を優先し、C1 も別の組から均等に配る。
// C1 と C2 が同じ字になった場合だけ、その位置の C1 を後ろの別の字と入れ替える。
function dealPairs(n) {
  const d1 = dealEven(CHARS, n);
  const d2 = dealEven(CHARS, n);
  for (let i = 0; i < n; i++) {
    if (d1[i] !== d2[i]) continue;
    const j = d1.findIndex((c, k) => k !== i && c !== d2[i] && d2[k] !== d1[i]);
    if (j >= 0) { const t = d1[i]; d1[i] = d1[j]; d1[j] = t; }
  }
  return d1.map((c1, i) => [c1, d2[i]]);
}
// 本番 N_TRIALS 問。提示方式2水準 × frac21水準が均等になるように配り、
// さらに文字とアルゴリズムも全体で均等に配ってから順序を混ぜる。
// frac は提示方式の水準ごとに独立に均等配分する。こうすると「条件ごとの試行数」と
// 「条件 × frac のセルの試行数」の両方をできるだけそろえられる。
function buildMainSpecs() {
  const pairs = dealPairs(N_TRIALS);                  // 78字にできるだけ均等
  const algos = dealEven(ALGO_LIST, N_TRIALS);
  const perCond = splitByLevel(N_TRIALS, OVERLAP_LIST.length);
  const specs = [];
  let i = 0;
  OVERLAP_LIST.forEach((overlap, s) => {
    const n = perCond[s];
    const nCatch = Math.round(n * CATCH_RATE);        // frac=100 の統制試行
    const nGraded = n - nCatch;
    const fracs = dealEven(FRAC_GRID, nGraded);       // 21水準にできるだけ均等
    for (let j = 0; j < n; j++, i++) {
      const isCatch = j >= nGraded;
      const frac = isCatch ? 100 : fracs[j];
      const [c1, c2] = pairs[i];
      specs.push({ c1, c2, frac, algo: algos[i], overlap,
        is_catch: isCatch, id: specId(c1, c2, algos[i], frac, overlap) });
    }
  });
  return shuffle(specs);
}
// 練習 N_PRACTICE 問。見やすい水準から始めて短い水準も混ぜ、
// 「最後まで見える問も、ほとんど見えない問もある」ことを体験してもらう。
// 提示方式も両方の条件を体験できるように交互に配る (重なって見えることに驚かせないため)。
function buildPracticeSpecs() {
  const ladder = [100, 80, 60, 40, 20];
  const pairs = dealPairs(N_PRACTICE);
  const algos = dealEven(ALGO_LIST, N_PRACTICE);
  const overlaps = dealEven(OVERLAP_LIST, N_PRACTICE);
  return Array.from({length: N_PRACTICE}, (_, i) => {
    const frac = ladder[i % ladder.length];
    const [c1, c2] = pairs[i];
    return { c1, c2, frac, algo: algos[i], overlap: overlaps[i],
      is_catch: false, id: specId(c1, c2, algos[i], frac, overlaps[i]) };
  });
}

// =========================================================================
// Trial
// =========================================================================
function buttonHtml(choice) {
  if (choice === "") {
    return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
  }
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
      <div class="trial-prompt">ボタンを押すと2文字つづけて表示されます。<b>2文字目</b>が何か、50音表から選んでください</div>`,
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
        playSeq(ctx, spec.c1, spec.c2, spec.frac, spec.algo, spec.overlap,
          (m) => { if (!_meas) _meas = m; });
      };
      if (btn) btn.addEventListener("click", play);
      _spaceHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); play(); } };
      document.addEventListener("keydown", _spaceHandler);
    },
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: spec.id,
      modality: "visual2char",
      q_set: "all",
      font: FONT_TAG,
      c1: spec.c1,
      target_char: spec.c2,
      algo: spec.algo,
      frac: spec.frac,
      overlap: spec.overlap,     // "none" (統制) か "decay" (先行文字の残存)
      // 減衰の時定数。統制条件では減衰そのものが無いので空欄にする。
      tau_ms: (spec.overlap === "decay") ? TAU_MS : "",
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
        target_char: data.target_char, c1: data.c1, modality: data.modality,
        q_set: data.q_set, font: data.font, algo: data.algo, frac: data.frac,
        overlap: data.overlap, tau_ms: data.tau_ms,
        n_choices: data.n_choices, replays: data.replays, rt_ms: data.rt_ms,
        is_catch: data.is_catch, actual_ms: data.actual_ms, actual_frames: data.actual_frames,
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
      const ok = last.response_char === spec.c2;
      return `<div style="padding:16px 8px">
        <p style="font-size:17px">2文字目の正解は「<b style="font-size:24px">${spec.c2}</b>」でした
          <span style="color:${ok ? "#2E7D8F" : "#C25B4E"};font-weight:700">${ok ? "◯" : "×"}</span></p>
        <p style="font-size:14px;color:#555">1文字目は「${spec.c1}」でした（これは<b>答えない</b>字です）。</p>
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
    config: { N_TRIALS, N_PRACTICE, CATCH_RATE, CHAR_MS, FRAC_GRID, ALGO_LIST, FONT_TAG,
      OVERLAP_LIST, TAU_MS },
    env: ENV,
    trials: jsPsych.data.get().filter({task: "main"}).values(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `visual2char_${Date.now()}.json`;
  a.click();
}

// =========================================================================
// Timeline
// =========================================================================
async function run() {
  const loading = document.createElement("p");
  loading.style.cssText = "padding:40px;color:#4a76d6;";
  loading.textContent = "文字画像を読み込み中…";
  document.body.appendChild(loading);
  try {
    await loadAllImages();
  } catch (e) {
    loading.textContent = "画像の読み込みに失敗しました: " + e.message;
    loading.style.color = "#900";
    return;
  }
  loading.remove();

  // 本番モード(?prod=1)は、jsPsych を始める前に同意画面を挟む。
  if (PROD.enabled) {
    await new Promise((resolve) => {
      const box = document.createElement("div");
      box.className = "prod-consent";
      document.body.appendChild(box);
      PROD.consentScreen(box, `かなの見分けの課題（画面表示・約${EST_MINUTES}分）`, EST_MINUTES,
        () => { box.remove(); resolve(); }, false);
    });
  }

  const practiceSpecs = buildPracticeSpecs();
  const mainSpecs = buildMainSpecs();

  // 研究者パイロット(?prod なし)のときだけ出す同意ページ。本番モードは prod_common.js の同意画面を使う。
  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験（視覚・2文字版）</h2>
       <p>本実験は、画面にすばやく表示される文字の読み取りやすさを測ることを目的としています。
       所要時間は約 ${EST_MINUTES} 分です。ご協力ありがとうございます。</p>
       <p><b>文字が短い時間 (1文字 0.2 秒) で次々に表示されます。</b>
       画面がよく見える明るさ・距離でご参加ください。</p>
       <p>取得するデータ: 各設問への回答とその所要時間、参加識別子。
       個人を特定する情報は収集しません。</p>
       <p><b>続けて参加することに同意される場合は「次へ」を押してください。</b></p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "同意して次へ",
  };

  const instructions = {
    type: jsPsychInstructions,
    pages: [
      `<h2>課題</h2>
       <p>各問で、ひらがなが <b>2文字つづけて同じ場所に</b> 表示されます。
       1文字ずつ 0.2 秒の速さで、字は「だんだん現れる」ように表示されます
       (現れかたは問題ごとにさまざまです)。</p>
       <p>各問は <b>自分のペース</b> で始められます。表示枠の下の
       <b>[準備ができたら開始]</b> ボタン (またはスペースキー) を押すと、そこで文字が表示されます。
       押すまでは何も起きませんので、落ち着いてから始めてください。</p>
       <p>1文字目は最後まで表示されますが、<b>2文字目は途中で消える</b>ことがあります。
       答えるのは <b>2文字目</b> です。</p>
       ${OVERLAP_LIST.indexOf("decay") >= 0 ? `<p>問題によっては、<b>1文字目が薄く残ったまま2文字目が重なって見える</b>ことがあります。
       これは実験の仕組みによるもので、故障や不具合ではありません。</p>` : ""}
       <p>押したあと、同じボタンが「▶ もう一度みる」に変わり、<b>何度でも</b> 見直せます。
       下の <b>50音表</b>(濁音・半濁音などを含む 78 字)から、<b>2文字目</b>だと思う 1 文字を
       選んでください。表は毎回同じ並びです。</p>`,
      `<h2>答え方</h2>
       <p>2文字のつながりに意味はありません。ことばとして自然かどうかは気にせず、
       見えたものだけで答えてください。</p>
       <p><b>難しくて当然の課題です。</b>2文字目がごく一瞬で消える問もあれば、最後まで見える問もあります。
       2文字目がほとんど何も見えない問も混ざっています。</p>
       <p>見えなかったと感じたときも、<b>勘で1文字を選んでください</b>。
       1文字目を2文字目として答えないように気をつけてください。
       外れた答えも大切なデータです。正誤は報酬に影響しません。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。
       練習では毎回、正解をお見せします。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "練習を始める",
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
    show_clickable_nav: true,
    button_label_next: "本番を始める",
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
