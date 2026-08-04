// =========================================================================
// 聴覚版 1文字課題 本実験 (統一モデルの C1=∅ = 発話先頭の特殊ケース)
//   - 単一のかなを発話先頭の音高 B3・1文字0.2秒で合成した音声を、frac% まで
//     再生して (truncation) 何の文字かを問う。frac=0 無音 / frac=100 完全 (catch)。
//   - 時間ゲートは再生時に Web Audio でライブ切り出し (audio2char と同方式)。
//   - 時間ゲートは実測の音響的開始(gate_onset_ms)を起点に、量子化済みゲイン(gate_gain)を適用する(2026-07-23修正)。
//   - 回答は固定50音グリッド(68字。を・ぢ・づ・ゔは同音のため除外、同音は併記ボタン)。
//     manifest は公開(回答なし・68刺激)、正解は answer_key。
//
//   2026-08 の改訂 (乙課題で導入済みの参加者体験を移植):
//     1. クリック開始 (自己ペース)。音は自動で鳴らさず、[音をきく] ボタン
//        (またはスペースキー) を押してから鳴らす。押すまでは回答ボタンを押せない。
//     2. 教示と練習のフィードバック。何を答えるのか・難しくて当然であること・
//        勘で答えてよいことを、練習の各問のあとにも繰り返し伝える。
//        なお正解はこの端末に置いていない (answer_key はサーバ側) ため、
//        練習でも正解そのものは表示できない。参加者自身の答えだけを見せる。
//     3. 出題の配り方。frac 水準と刺激を均等に配ってから順序を混ぜる
//        (毎回独立に抽選すると水準と音の出現が偏るため)。総試行数は 200 のまま。
//     4. 本番モード (?prod=1)。同意画面・GAS 送信・完了コードは prod_common.js に一本化。
// =========================================================================

const N_TRIALS = 200;
const N_PRACTICE = 5;
const CATCH_RATE = 0.05;
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);
const FADE_MS = 8;
// 各問の音声の前後に鳴らす合図音(ビープ)。開始と終了が分かるようにするため。
const BEEP_HZ = 880;         // 合図音の高さ
const BEEP_MS = 80;          // 合図音1回の長さ
const BEEP_LEAD_MS = 300;    // 開始の合図音から、文字の音声が始まるまでの間隔
const END_GAP_MS = 500;      // 文字の音声が終わってから、終了の合図音までの間隔
const END_BEEP_GAP_MS = 140; // 終了の合図音を2回鳴らすときの、1回目と2回目の間隔

// 端末環境 (解析用にログ。リフレッシュレートは聴覚課題の成績には関わらないが、
// 端末の素性を視覚課題と同じ形で見比べられるように測っておく)。
const ENV = { ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
  screen: `${window.screen.width}x${window.screen.height}`,
  touch: (navigator.maxTouchPoints || 0) > 0, refreshHz: null };
(function measureRefresh() {
  let n = 0; const t0 = performance.now();
  function f(now) { n++; if (n < 40) requestAnimationFrame(f); else ENV.refreshHz = Math.round(1000 / ((now - t0) / n)); }
  requestAnimationFrame(f);
})();
PROD.setEnv(ENV);

// 68音の固定50音グリッド (pilot_soa_audio.js の GRID_AUDIO と一致=乙課題と統一)。
// を・ぢ・づ は お・じ・ず と同音、ゔ は ぶ と区別されないため、出題・回答から外す。
// 同音の別表記は「じ／ぢ」のように1ボタンに併記する(HOMOPHONE_LABEL。値は代表音)。
const GRID_AUDIO = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","ん"],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","","","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
];
const GRID_FLAT = GRID_AUDIO.flat();
const GRID_COLS = 5;
const GRID_ROWS = GRID_AUDIO.length;
const N_CHOICES = GRID_FLAT.filter(c => c !== "").length;   // 68

// 同音のかなを1つのボタンに併記する。表示は併記、値(採点・記録)は代表音(左)。
// 単音を聞いて綴りを確定できない同音字(お／を・じ／ぢ・ず／づ)を、音のクラスとして正直に名づける。
const HOMOPHONE_LABEL = { "お": "お／を", "じ": "じ／ぢ", "ず": "ず／づ" };
function kanaLabel(ch) { return HOMOPHONE_LABEL[ch] || ch; }

// 参加者ID・完了コード・送信は prod_common.js に一本化してある (二重管理をなくすため)。
const participantId = PROD.participantId;
const completionCode = PROD.completionCode;

const jsPsych = initJsPsych({
  display_element: document.body,
  show_progress_bar: true,
  message_progress_bar: "進捗",
});

let ctx = null;
const _bufCache = {};
let _replays = 0;          // 「もう一度きく」を押した回数
let _nodes = [];           // 予約済みの音声ノード(合図音・刺激)。再生し直すときにまとめて止める。
let _tTrial = 0;           // 問が画面に出た時刻 (jsPsych の rt の起点)
let _tStim = null;         // 最初に鳴らし始めた時刻 (反応時間の起点)
let _spaceHandler = null;

function ensureCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}
async function decodeStim(stim) {
  if (_bufCache[stim.id]) return _bufCache[stim.id];
  const res = await fetch(`audio1char_stimuli/${stim.id}.mp3`, {cache: "force-cache"});
  if (!res.ok) throw new Error(`audio1char_stimuli/${stim.id}.mp3 ${res.status}`);
  const buf = await ensureCtx().decodeAudioData(await res.arrayBuffer());
  _bufCache[stim.id] = buf;
  return buf;
}
// 実測の音響的開始から、スロット末までの残りの frac% を再生。
function gatedBuffer(buf, stim) {
  const sr = buf.sampleRate;
  const onsetMs = (typeof stim.gate_onset_ms === "number") ? stim.gate_onset_ms : 0;
  const gain = (typeof stim.gate_gain === "number") ? stim.gate_gain : 1.0;
  const start = Math.round((stim.char_onset_s + onsetMs / 1000) * sr);
  const avail = Math.max(0.01, stim.char_dur_s - onsetMs / 1000);
  const len = Math.max(0, Math.round(avail * stim.frac / 100 * sr));
  const src = buf.getChannelData(0);
  const ab = ctx.createBuffer(1, Math.max(1, len), sr);
  const out = ab.getChannelData(0);
  for (let i = 0; i < len; i++) out[i] = (src[start + i] || 0) * gain;
  const fade = Math.min(Math.round(sr * FADE_MS / 1000), len >> 1);
  for (let i = 0; i < fade; i++) {
    out[i] *= i / fade;
    out[len - 1 - i] *= i / fade;
  }
  return ab;
}
// 予約済みの音声ノードをまとめて止める(再生し直し・次の問への移行時)。
function stopAll() {
  for (const n of _nodes) { try { n.stop(); } catch (e) {} }
  _nodes = [];
}
// 合図音(短いビープ)を when 秒に鳴らす。
function playBeep(when) {
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = "sine";
  osc.frequency.value = BEEP_HZ;
  osc.connect(g); g.connect(ctx.destination);
  g.gain.setValueAtTime(0.0001, when);
  g.gain.exponentialRampToValueAtTime(0.12, when + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, when + BEEP_MS / 1000);
  osc.start(when);
  osc.stop(when + BEEP_MS / 1000 + 0.02);
  _nodes.push(osc);
}
// 1問の再生: 開始の合図音 → 文字の音声 → (終わって0.5秒後に)終了の合図音を2回。
function playGated(buf, stim) {
  ensureCtx();
  stopAll();
  const t0 = ctx.currentTime + 0.02;
  playBeep(t0);                                     // 開始の合図音(1回)
  const stimStart = t0 + BEEP_LEAD_MS / 1000;
  const onsetMs = (typeof stim.gate_onset_ms === "number") ? stim.gate_onset_ms : 0;
  const stimDur = Math.max(0, (stim.char_dur_s - onsetMs / 1000)) * stim.frac / 100; // 実際に鳴る音声の長さ(frac=0なら0)
  if (stim.frac > 0) {                              // 無音の問でも合図音は前後に鳴る
    const s = ctx.createBufferSource();
    s.buffer = gatedBuffer(buf, stim);
    s.connect(ctx.destination);
    s.start(stimStart);
    _nodes.push(s);
  }
  const endAt = stimStart + stimDur + END_GAP_MS / 1000;
  playBeep(endAt);                                  // 終了の合図音(開始と区別するため2回)
  playBeep(endAt + END_BEEP_GAP_MS / 1000);
}

async function loadManifest() {
  const res = await fetch("audio1char_manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("audio1char_manifest.json fetch failed: " + res.status);
  return await res.json();
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
// 混ぜた一組を順に配り、尽きたら混ぜ直して配り続ける。どの要素の出現数も差は高々1になる。
// 毎回独立に抽選すると、水準や音の出現数が偶然かたよって成績を歪めるため
// (乙課題 pilot_soa_audio.js の dealPairs と同じ考え方)。
function dealEven(items, n) {
  const out = [];
  while (out.length < n) out.push(...shuffle([...items]));
  return out.slice(0, n);
}
// 本番 n 問。プールは68刺激(1音1刺激)なので、刺激を均等に配れば音の偏りもなくなる。
// frac も 21水準に均等に配り、catch(frac=100)を CATCH_RATE 分だけ別に確保する。
function buildMainTrials(manifest, n) {
  const pool = manifest.stimuli || [];
  if (pool.length === 0) throw new Error("audio1char_manifest に刺激がありません");
  const nCatch = Math.round(n * CATCH_RATE);
  const nGraded = n - nCatch;
  const fracs = dealEven(FRAC_GRID, nGraded);
  const stims = dealEven(pool, n);
  const out = [];
  for (let i = 0; i < n; i++) {
    const isCatch = i >= nGraded;
    out.push(Object.assign({}, stims[i], {frac: isCatch ? 100 : fracs[i], is_catch: isCatch}));
  }
  return shuffle(out);
}
// 練習 n 問。聞き取りやすい水準から始めて短い水準も混ぜ、
// 「最後まで聞こえる問も、ほとんど聞こえない問もある」ことを体験してもらう。
function buildPracticeTrials(manifest, n) {
  const pool = manifest.stimuli || [];
  const ladder = [100, 80, 60, 40, 20];
  const stims = dealEven(pool, n);
  return Array.from({length: n}, (_, i) =>
    Object.assign({}, stims[i], {frac: ladder[i % ladder.length], is_catch: false}));
}

function buttonHtml(choice) {
  if (choice === "") return '<button class="jspsych-btn grid-spacer" disabled tabindex="-1"></button>';
  return `<button class="jspsych-btn grid-kana">${kanaLabel(choice)}</button>`;
}

// 回答用の50音ボタン。再生前は押せないようにして、聞いてから答えてもらう。
function answerButtons() {
  const group = document.querySelector("#jspsych-html-button-response-btngroup, .jspsych-html-button-response-btngroup");
  if (!group) return [];
  return Array.from(group.querySelectorAll("button")).filter(b => !b.disabled);
}

function makeTrial(stim, isPractice = false) {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: `
      <div class="audio-controls">
        <button type="button" id="play-btn" class="replay-btn">▶ 準備ができたら音をきく（またはスペースキー）</button>
      </div>
      <div class="trial-prompt">ボタンを押すと、ひらがな1文字の読み上げが流れます。きこえた文字を 50音表から選んでください</div>`,
    choices: GRID_FLAT,
    button_html: buttonHtml,
    grid_rows: GRID_ROWS,
    grid_columns: GRID_COLS,
    on_load: () => {
      _replays = 0; _tStim = null;
      _tTrial = performance.now();
      const btn = document.getElementById("play-btn");
      // 再生前は回答できないようにする (自己ペースで開始してもらうため)。
      const answers = answerButtons();
      answers.forEach(b => { b.disabled = true; b.style.opacity = ".45"; });
      decodeStim(stim).then(buf => {
        const play = () => {
          if (_tStim === null) {
            _tStim = performance.now();                   // 反応時間の起点
            answers.forEach(b => { b.disabled = false; b.style.opacity = ""; });
            if (btn) btn.textContent = "▶ もう一度きく";
          } else {
            _replays += 1;
          }
          playGated(buf, stim);
        };
        if (btn) btn.addEventListener("click", play);
        _spaceHandler = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); play(); } };
        document.addEventListener("keydown", _spaceHandler);
      }).catch(err => {
        const p = document.querySelector(".trial-prompt");
        if (p) p.textContent = "音声の読み込みに失敗しました: " + err.message;
        answers.forEach(b => { b.disabled = false; b.style.opacity = ""; });
      });
    },
    data: {
      task: isPractice ? "practice" : "main",
      stimulus_id: stim.id,
      modality: "audio1char",
      q_set: "all",
      pitch_scheme: "B3",
      frac: stim.frac,
      n_choices: N_CHOICES,
      is_catch: stim.is_catch,
    },
    on_finish: (data) => {
      if (_spaceHandler) { document.removeEventListener("keydown", _spaceHandler); _spaceHandler = null; }
      stopAll();
      data.response_char = GRID_FLAT[data.response];
      data.replays = _replays;
      // 反応時間は「音が鳴り始めてから回答するまで」。開始ボタンを押すまでの待ち時間は含めない
      // (自己ペース開始にしたため、jsPsych の rt をそのまま使うと待ち時間が混ざる)。
      data.rt_ms = (_tStim === null) ? data.rt : Math.round(data.rt - (_tStim - _tTrial));
      if (isPractice) return;
      PROD.saveFracTrial({
        stimulus_id: data.stimulus_id, response_char: data.response_char,
        modality: data.modality, q_set: data.q_set, pitch_scheme: data.pitch_scheme,
        frac: data.frac, n_choices: data.n_choices, replays: data.replays,
        rt_ms: data.rt_ms, is_catch: data.is_catch,
      });
    },
  };
}

// 練習のフィードバック。難しくて当然であること・勘でよいことを伝える。
// 正解表(answer_key)はサーバ側にあり端末に無いため、正解そのものは表示できない。
function makeFeedback() {
  return {
    type: jsPsychHtmlButtonResponse,
    stimulus: () => {
      const last = jsPsych.data.get().last(1).values()[0] || {};
      const ans = last.response_char ? kanaLabel(last.response_char) : "（未選択）";
      return `<div style="padding:16px 8px">
        <p style="font-size:17px">あなたの答え: <b style="font-size:24px">${ans}</b></p>
        <p style="font-size:14px;color:#555;line-height:1.8">これは練習です。答えは記録されません。<br>
          <b>難しくて当然の課題</b>です。ほとんど何も聞こえない問もあります。
          聞こえなかったと感じても空欄にせず、<b>勘で選んで</b>ください。正誤は報酬に影響しません。<br>
          この課題は正解をお見せできません（答えは端末に置いていないため）。</p></div>`;
    },
    choices: ["次へ"],
    trial_duration: 5000,
    data: { task: "practice_feedback" },
  };
}

function downloadResults() {
  const payload = {
    config: { N_TRIALS, N_PRACTICE, CATCH_RATE, FRAC_GRID, pitch_scheme: "B3" },
    env: ENV,
    trials: jsPsych.data.get().filter({task: "main"}).values(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `audio1char_${Date.now()}.json`;
  a.click();
}

async function run() {
  let manifest;
  try { manifest = await loadManifest(); }
  catch (e) {
    document.body.innerHTML =
      '<p style="padding:40px;color:#900;">音声データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }
  let practiceStims, mainStims;
  try {
    practiceStims = buildPracticeTrials(manifest, N_PRACTICE);
    mainStims = buildMainTrials(manifest, N_TRIALS);
  } catch (e) { document.body.innerHTML = '<p style="padding:40px;color:#900;">' + e.message + '</p>'; return; }

  // 本番モード(?prod=1)は、jsPsych を始める前に同意画面を挟む(聴覚課題はヘッドホン必須)。
  if (PROD.enabled) {
    await new Promise((resolve) => {
      const box = document.createElement("div");
      box.className = "prod-consent";
      document.body.appendChild(box);
      PROD.consentScreen(box, "かなの聞き取りの課題（音声・約20分）", 20,
        () => { box.remove(); resolve(); }, true);
    });
  }

  // 研究者パイロット(?prod なし)のときだけ出す同意ページ。本番モードは prod_common.js の同意画面を使う。
  const consent = {
    type: jsPsychInstructions,
    pages: [
      `<h2>インクルーシブ字幕の研究実験（音声・1文字版）</h2>
       <p>本実験は、音声で呈示された文字の聞き取りやすさを測ることを目的としています。
       所要時間は約 20 分です。ご協力ありがとうございます。</p>
       <p><b>音声を使用します。ヘッドホン・イヤホンをご用意のうえ、
       音量を適切に調整してください。</b></p>
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
       <p>各問は <b>自分のペース</b> で始められます。
       <b>[準備ができたら音をきく]</b> ボタン (またはスペースキー) を押すと、そこで音が鳴り始めます。
       押すまでは何も鳴りませんので、落ち着いてから始めてください。</p>
       <p>まず短い「ピッ」という合図音が1回鳴り、そのあとに、ひらがな1文字の読み上げ音声が流れます。
       読み上げが終わってしばらくすると、今度は合図音が「ピッピッ」と2回鳴り、その問が終わったことをお知らせします。
       始まりの合図音は1回、終わりの合図音は2回で区別できます。</p>
       <p>押したあと、同じボタンが「▶ もう一度きく」に変わり、<b>何度でも</b> 聞き直せます。
       下の <b>50音表</b>(濁音・半濁音を含む 68 字)から、聞こえたと思う 1 文字を選んでください。
       表は毎回同じ並びです。</p>`,
      `<h2>答え方</h2>
       <p>かなは<b>単独で読んだときの音</b>です（「は」はハ、「へ」はヘ）。
       「じ／ぢ」のように<b>同じ音のかなは1つのボタンにまとめて</b>あり、どちらの字かを選ぶ必要はありません。</p>
       <p><b>難しくて当然の課題です。</b>読み上げは、発話のごく途中までしか流れず短くて分かりにくい場合もあれば、
       最後まではっきり聞こえる場合もあります。ほとんど何も聞こえない問もありますが、その場合も合図音は前後に鳴ります。</p>
       <p>聞こえなかったと感じたときも、<b>勘で1文字を選んでください</b>。
       外れた答えも大切なデータです。正誤は報酬に影響しません。
       確信が持てなくても構いません。考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。
       ここで音量を調整してください。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true, button_label_next: "練習を始める",
  };
  // 練習は1問ごとに答え方を確認する画面を挟む (乙課題と同じ流れ)。
  const practiceBlock = practiceStims.flatMap(s => [makeTrial(s, true), makeFeedback()]);
  const mainStart = {
    type: jsPsychInstructions,
    pages: [
      `<h2>練習終了</h2>
       <p>続いて本番 ${mainStims.length} 問に入ります。ここからの回答が記録されます。</p>
       <p>やり方は練習と同じです。分からない問は勘で選んでください。
       静かな環境で、ヘッドホンの装着を確認してから進めてください。</p>
       <p>準備ができたら「本番を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true, button_label_next: "本番を始める",
  };
  const mainBlock = mainStims.map(s => makeTrial(s, false));
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
