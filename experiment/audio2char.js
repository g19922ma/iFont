// =========================================================================
// 聴覚版 2文字課題 (C1→C2, C2 を時間ゲート)  ※2026-07-02 設計改訂版
//   - 統一モデル: 先行する1文字目(C1)を全提示し、ターゲットの2文字目(C2)を
//     frac%(0〜100) まで再生して何の文字かを問う。
//   - 語彙は競技かるたに限定しない。C1・C2 とも全72字(音声で区別可能なかな)から
//     ランダム。プールは 72×72 の総当たり。
//   - 音高は競技かるたの読みの規定で固定: C1=B3(246.94Hz), C2=E4(329.63Hz)。
//     提示速度も規定で固定: 1文字 0.2 秒。
//   - 刺激は VOICEVOX 合成の全長音声(C1+C2)。2文字目の時間ゲートは
//     Web Audio で再生時に行う(pilot_audio と同じライブ切り出し)。
//   - 回答は固定50音グリッド(全 72 字)。catch = frac=100(C2 全提示)。
//   - manifest = experiment/audio2char_manifest.json (回答は含まない)。
//
//   2026-08 の改訂 (乙課題で導入済みの参加者体験を移植):
//     1. クリック開始 (自己ペース)。音は自動で鳴らさず、[音をきく] ボタン
//        (またはスペースキー) を押してから鳴らす。押すまでは回答ボタンを押せない。
//     2. 教示と練習のフィードバック。何を答えるのか・難しくて当然であること・
//        勘で答えてよいことを、練習の各問のあとにも繰り返し伝える。
//        なお正解はこの端末に置いていない (answer_key はサーバ側) ため、
//        練習でも正解そのものは表示できない。参加者自身の答えだけを見せる。
//     3. 出題の配り方。frac 水準を均等に配ってから順序を混ぜる。
//        文字の均等配分は、manifest に文字が含まれない(正解を伏せる設計の)ため
//        この課題ではできない。刺激そのものは非復元抽出なので同じ対は出ない。
//        総試行数は 200 のまま。
//     4. 本番モード (?prod=1)。同意画面・GAS 送信・完了コードは prod_common.js に一本化。
// =========================================================================

const N_TRIALS = 200;
const N_PRACTICE = 5;
const CATCH_RATE = 0.05;

// 2文字目を切り出す割合のグリッド(0〜100 を 5 刻み = 21 段階)。ifont_common.FRAC_GRID と一致。
const FRAC_GRID = Array.from({length: 21}, (_, i) => i * 5);

const FADE_MS = 8;   // ゲート切断点の短いフェード(クリック防止)
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

// =========================================================================
// 全 72 字の固定50音グリッド (audio.js の GRID_AUDIO と一致)
// =========================================================================
const GRID_AUDIO = [
  ["あ","い","う","え","お"],
  ["か","き","く","け","こ"],
  ["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],
  ["な","に","ぬ","ね","の"],
  ["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],
  ["や","",  "ゆ","",  "よ"],
  ["ら","り","る","れ","ろ"],
  ["わ","",  "",  "",  "を"],
  ["ん","",  "",  "",  ""  ],
  ["が","ぎ","ぐ","げ","ご"],
  ["ざ","じ","ず","ぜ","ぞ"],
  ["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],
  ["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ゔ","",  "",  "",  ""  ],
];
const GRID_FLAT = GRID_AUDIO.flat();
const GRID_COLS = 5;
const GRID_ROWS = GRID_AUDIO.length;
const N_CHOICES = GRID_FLAT.filter(c => c !== "").length;   // 72, γ = 1/72

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

// Web Audio: 全長音声をデコードしてキャッシュし、再生時に [0, gate] を切り出す。
let ctx = null;
const _bufCache = {};   // id -> AudioBuffer
let _replays = 0;       // 「もう一度きく」を押した回数
let _nodes = [];        // 予約済みの音声ノード(合図音・刺激)。再生し直すときにまとめて止める。
let _tTrial = 0;        // 問が画面に出た時刻 (jsPsych の rt の起点)
let _tStim = null;      // 最初に鳴らし始めた時刻 (反応時間の起点)
let _spaceHandler = null;

function ensureCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

async function decodeStim(stim) {
  if (_bufCache[stim.id]) return _bufCache[stim.id];
  const res = await fetch(`audio2char_stimuli/${stim.id}.mp3`, {cache: "force-cache"});
  if (!res.ok) throw new Error(`audio2char_stimuli/${stim.id}.mp3 ${res.status}`);
  const buf = await ensureCtx().decodeAudioData(await res.arrayBuffer());
  _bufCache[stim.id] = buf;
  return buf;
}

// C1 を全提示し、C2 を frac% まで残す = ファイル先頭から gate 秒までを再生。
// 切り出し点は manifest の c2_gate_start_ms / c2_avail_ms(復号後の座標での C2 の
// 開始位置とモーラ長)から求める。名目の c2_onset_s / c2_dur_s を使ってはいけない。
// 名目値は VOICEVOX の音素長の量子化(10.667ms格子)も mp3 の復号遅れ(46.042ms)も
// 見込んでおらず、実測では C2 は 334.04 か 344.71 ミリ秒から始まり 526〜547 ミリ秒で終わる。
// 名目値のままだと frac=0 で C1 の末尾を34〜45ミリ秒削り、frac=100 で C2 の母音の後半を
// 26〜47ミリ秒切り落としていた(2026-08-06 修正。1文字課題と同じ欠陥)。
function gateSeconds(stim) {
  if (typeof stim.c2_gate_start_ms === "number" && typeof stim.c2_avail_ms === "number") {
    return (stim.c2_gate_start_ms + stim.c2_avail_ms * stim.frac / 100) / 1000;
  }
  return stim.c2_onset_s + (stim.frac / 100) * stim.c2_dur_s;   // 古いマニフェストへの保険
}
function gatedBuffer(buf, stim) {
  const sr = buf.sampleRate;
  const gate = gateSeconds(stim);
  const src = buf.getChannelData(0);
  const len = Math.max(1, Math.min(src.length, Math.round(gate * sr)));
  const ab = ctx.createBuffer(1, len, sr);
  const out = ab.getChannelData(0);
  for (let i = 0; i < len; i++) out[i] = src[i] || 0;
  const fade = Math.min(Math.round(sr * FADE_MS / 1000), len);
  for (let i = 0; i < fade; i++) out[len - fade + i] *= (1 - i / fade);
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
// 1問の再生: 開始の合図音 → 2文字の音声 → (終わって0.5秒後に)終了の合図音を2回。
function playGated(buf, stim) {
  ensureCtx();
  stopAll();
  const t0 = ctx.currentTime + 0.02;
  playBeep(t0);                                     // 開始の合図音(1回)
  const stimStart = t0 + BEEP_LEAD_MS / 1000;
  // 再生する音声の長さ = 先頭から2文字目のゲート点まで(復号後の座標)
  const stimDur = gateSeconds(stim);
  const s = ctx.createBufferSource();
  s.buffer = gatedBuffer(buf, stim);
  s.connect(ctx.destination);
  s.start(stimStart);                               // 合図音のあと、間隔をおいて文字の音声
  _nodes.push(s);
  const endAt = stimStart + stimDur + END_GAP_MS / 1000;
  playBeep(endAt);                                  // 終了の合図音(開始と区別するため2回)
  playBeep(endAt + END_BEEP_GAP_MS / 1000);
}

// =========================================================================
// Manifest
// =========================================================================
async function loadManifest() {
  const res = await fetch("audio2char_manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("audio2char_manifest.json fetch failed: " + res.status);
  return await res.json();
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
// 混ぜた一組を順に配り、尽きたら混ぜ直して配り続ける。どの要素の出現数も差は高々1になる。
// 毎回独立に抽選すると水準の出現数が偶然かたよって成績を歪めるため
// (乙課題 pilot_soa_audio.js の dealPairs と同じ考え方)。
function dealEven(items, n) {
  const out = [];
  while (out.length < n) out.push(...shuffle([...items]));
  return out.slice(0, n);
}
// 刺激は 5184 対のプールから非復元抽出し、frac は 21水準に均等に配る。
// catch(frac=100)は CATCH_RATE 分だけ別に確保する。
function buildTrials(manifest, n) {
  const pool = manifest.stimuli || [];
  if (pool.length === 0) throw new Error("audio2char_manifest に刺激がありません");
  const picked = jsPsych.randomization.sampleWithoutReplacement(pool, Math.min(n, pool.length));
  const nCatch = Math.round(n * CATCH_RATE);
  const nGraded = n - nCatch;
  const fracs = dealEven(FRAC_GRID, nGraded);
  const out = picked.map((s, i) => {
    const isCatch = i >= nGraded;
    return Object.assign({}, s, {frac: isCatch ? 100 : fracs[i], is_catch: isCatch});
  });
  return shuffle(out);
}
// 練習 n 問。聞き取りやすい水準から始めて短い水準も混ぜ、
// 「最後まで聞こえる問も、ほとんど聞こえない問もある」ことを体験してもらう。
function buildPracticeTrials(manifest, n) {
  const pool = manifest.stimuli || [];
  const ladder = [100, 80, 60, 40, 20];
  const picked = jsPsych.randomization.sampleWithoutReplacement(pool, Math.min(n, pool.length));
  return picked.map((s, i) => Object.assign({}, s, {frac: ladder[i % ladder.length], is_catch: false}));
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
      <div class="trial-prompt">ボタンを押すと2文字つづけて読み上げます。<b>2文字目</b>が何か、50音表から選んでください</div>`,
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
      modality: "audio2char",
      q_set: "all",
      pitch_scheme: "B3-E4",
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
      const ans = last.response_char || "（未選択）";
      return `<div style="padding:16px 8px">
        <p style="font-size:17px">あなたの答え（2文字目）: <b style="font-size:24px">${ans}</b></p>
        <p style="font-size:14px;color:#555;line-height:1.8">これは練習です。答えは記録されません。<br>
          <b>難しくて当然の課題</b>です。2文字目がほとんど聞こえない問もあります。
          聞こえなかったと感じても空欄にせず、<b>勘で選んで</b>ください。
          1文字目を2文字目として答えないように気をつけてください。正誤は報酬に影響しません。<br>
          この課題は正解をお見せできません（答えは端末に置いていないため）。</p></div>`;
    },
    choices: ["次へ"],
    trial_duration: 5000,
    data: { task: "practice_feedback" },
  };
}

function downloadResults() {
  const payload = {
    config: { N_TRIALS, N_PRACTICE, CATCH_RATE, FRAC_GRID, pitch_scheme: "B3-E4" },
    env: ENV,
    trials: jsPsych.data.get().filter({task: "main"}).values(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `audio2char_${Date.now()}.json`;
  a.click();
}

// =========================================================================
// Timeline
// =========================================================================
async function run() {
  let manifest;
  try {
    manifest = await loadManifest();
  } catch (e) {
    document.body.innerHTML =
      '<p style="padding:40px;color:#900;">音声データの読み込みに失敗しました: ' + e.message + '</p>';
    return;
  }

  let practiceStims, mainStims;
  try {
    practiceStims = buildPracticeTrials(manifest, N_PRACTICE);
    mainStims = buildTrials(manifest, N_TRIALS);
  } catch (e) {
    document.body.innerHTML = '<p style="padding:40px;color:#900;">' + e.message + '</p>';
    return;
  }

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
      `<h2>インクルーシブ字幕の研究実験（音声・2文字版）</h2>
       <p>本実験は、競技かるたの読み上げに似た音声で、文字の聞き取りやすさを測ることを目的としています。
       所要時間は約 20 分です。ご協力ありがとうございます。</p>
       <p><b>音声を使用します。ヘッドホン・イヤホンをご用意のうえ、
       音量を適切に調整してください。</b></p>
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
       <p>各問は <b>自分のペース</b> で始められます。
       <b>[準備ができたら音をきく]</b> ボタン (またはスペースキー) を押すと、そこで音が鳴り始めます。
       押すまでは何も鳴りませんので、落ち着いてから始めてください。</p>
       <p>まず短い「ピッ」という合図音が1回鳴り、そのあとに、ひらがなを <b>2文字つづけて</b> 読み上げます。
       読み上げが終わってしばらくすると、今度は合図音が「ピッピッ」と2回鳴り、その問が終わったことをお知らせします。
       始まりの合図音は1回、終わりの合図音は2回で区別できます。</p>
       <p>1文字目は最後まで聞こえますが、<b>2文字目は途中までしか流れない</b>ことがあります。
       答えるのは <b>2文字目</b> です。</p>
       <p>押したあと、同じボタンが「▶ もう一度きく」に変わり、<b>何度でも</b> 聞き直せます。
       下の <b>50音表</b>(濁音・半濁音を含む 72 字)から、<b>2文字目</b>だと思う 1 文字を選んでください。
       表は毎回同じ並びです。</p>`,
      `<h2>答え方</h2>
       <p>2文字のつながりに意味はありません。ことばとして自然かどうかは気にせず、
       聞こえた音だけで答えてください。</p>
       <p><b>難しくて当然の課題です。</b>2文字目はごく短いこともあれば、最後まで聞こえることもあります。
       2文字目がほとんど聞こえない問も混ざっています。</p>
       <p>聞こえなかったと感じたときも、<b>勘で1文字を選んでください</b>。
       1文字目を2文字目として答えないように気をつけてください。
       外れた答えも大切なデータです。正誤は報酬に影響しません。
       確信が持てなくても構いません。考え込まずに次々と答えてください。</p>`,
      `<h2>練習</h2>
       <p>まず ${N_PRACTICE} 問の練習を行います。練習問題の答えは記録されません。
       ここで音量を調整してください。</p>
       <p>準備ができたら「練習を始める」を押してください。</p>`,
    ],
    show_clickable_nav: true,
    button_label_next: "練習を始める",
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
    show_clickable_nav: true,
    button_label_next: "本番を始める",
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
