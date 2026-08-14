// iFont パイロット: 聴覚・連続する音の間隔掃引(乙課題)。
// v1.7: 視覚の乙課題と対称に、単音プール(audio1char_stimuli, B3, 0.2秒/モーラ)から3音を選び、
// 「1つ目(S ms) → 2つ目(S ms) → 3つ目(S ms)」と連続再生する。1つ目と2つ目を回答し、3つ目は答えない音
// (2つ目の聞こえ終わりを揃える役)。雑音バーストは廃止した。
// Web Audio でサンプル精度にスケジュールする。間隔Sが音長(200ms)以上なら各音は自然に鳴り終わる。
// 正解の対応づけに answer_key_merged.json が必要(現在はgit管理)。
"use strict";

const VERSION = "3.2";   // パイロットのバージョン(細かい改変ごとにインクリメント)
// v2.3: 音声プールを再合成(VOICEVOX 0.25.2)。う・んの音量をvolumeScaleで底上げ、
//   F0実測の狭域化でま・びのオクターブ誤り補正を解消、切り出し位置を敏感しきい値で作り直し。
//   同名ファイルの中身が変わったので、キャッシュを避けるため取得URLに ?v= を付ける。
// v2.4: 話者候補の聴き比べ(?pool=cand108 など)。candidate_pools/<pool>/ の別プールを読み、
//   点検モード専用で鳴らす(候補プールで本番課題は実施させない)。
//   経緯: 全127話者スタイルをB3で実測した結果、現行の四国めたん(2)はほぼ最下位
//   (うが無声化して割れる・母音が息っぽい)で、話者変更が有力になったため。
const P = new URLSearchParams(location.search);
// 候補話者プール(?pool=cand108 等)。指定時は candidate_pools/<pool>/ から読み、点検モード専用。
const POOL = P.get("pool") || "";
const POOL_BASE = POOL ? `candidate_pools/${POOL}/` : "";
// v3.0: 本番プールを東北きりたん(id108・B3)に切り替えた(PI試聴+全127スタイル実測で決定)。
// 以下は聴き比べの記録として残す候補群。cand108は本番と同一なので一覧から外している。
const POOL_NAMES = { legacy_metan: "参考: 旧 四国めたん", cand94: "候補: 中部つるぎ",
  cand9: "候補: 波音リツ", cand21: "候補: 剣崎雌雄(男)", cand45: "候補: 櫻歌ミコ", cand53: "候補: 麒ヶ島宗麟(男)",
  // 音高違い。E4=かるたのメイン音程(栗原指摘)。
  // C4=男性読手いなばくんの実測主音程(262Hzが75%。オクターブ下げないと判明)。
  cand108e4: "きりたん・E4版", cand21c4: "剣崎雌雄・C4版(いなば音程)", cand53c4: "麒ヶ島宗麟・C4版(いなば音程)" };
const POOL_LABEL = POOL ? (POOL_NAMES[POOL] || POOL) : "本番: 東北きりたん";
const SOA_LEVELS = (P.get("levels") || "50,83,133,200,300,450,700").split(",").map(Number);
const PER_LEVEL = Number(P.get("perlevel") || 6);
const N_PRACTICE = Number(P.get("practice") || 2);
const COUNTDOWN_S = Number(P.get("countdown") ?? 5); // countdownモード時の秒数
const START_MODE = P.get("start") || "click";        // "click"(既定・自己ペース) / "countdown" / "none"
const FADE_S = 0.008;                       // 打ち切りのクリック音を避けるフェード

// 端末環境(解析用にログ)
const ENV = { ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
  screen: `${window.screen.width}x${window.screen.height}`, touch: (navigator.maxTouchPoints || 0) > 0 };

// v1.5: 「区別できる音」68音のグリッド。を・ぢ・づ は現代標準語で お・じ・ず と同音
// (本番プールでも同一の音声ファイル)、ゔ は日本語話者の多くが ぶ と区別して聞かないため、
// 出題と回答の両方から外した(PI決定 2026-07-17)。これらの字形は視覚セットには残り、
// 運用では同じ音の相手(お・じ・ず・ぶ)の聴覚曲線と対応づける。
const GRID_AUDIO = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","ん"],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","","","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
];
const CHARS = GRID_AUDIO.flat().filter(Boolean);   // 68音

// 同音のかなを1つのボタンに併記する。表示は併記、値(採点・記録)は代表音(左)。
// 単音を聞いて綴りを確定できない同音字(お／を・じ／ぢ・ず／づ)を、音のクラスとして正直に名づける。
// frac聴覚課題(audio1char.js)と統一(2026-07-22 PI決定)。
const HOMOPHONE_LABEL = { "お": "お／を", "じ": "じ／ぢ", "ず": "ず／づ" };
function kanaLabel(ch){ return HOMOPHONE_LABEL[ch] || ch; }

const screen = document.getElementById("screen");
let audioCtx = null, stimByChar = {}, bufByChar = {}, onsets = {}, poolMeta = {};
let trials = [], results = [], ti = 0, mainStarted = false;
// v3.0: 話者IDとスタイル名の対応(記録・表示用)。マニフェストのspeakerと突き合わせる。
const SPEAKER_NAMES = { 2: "四国めたん/ノーマル", 108: "東北きりたん/ノーマル", 94: "中部つるぎ/ノーマル",
  9: "波音リツ/ノーマル", 21: "剣崎雌雄/ノーマル", 45: "櫻歌ミコ/ロリ", 53: "麒ヶ島宗麟/ノーマル" };

function ensureCtx(){ if(!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)(); return audioCtx; }

// 正解表(answer_key_merged.json)を読み込む。Git管理外のため、同ディレクトリからの
// fetch に失敗した場合(GitHub Pages 等)は、研究者が手元のファイルを選択して読み込む。
async function loadAnswerKey() {
  if (!P.has("nokey")) {
    try {
      // 候補プールの分も answer_key_merged.json に統合してある。
      // ハッシュは話者IDを含むので、どの話者のプールでもキーは衝突しない。
      // (候補プール側の answer_key_1char.json は .gitignore で公開されないため、
      //  そちらを読むと公開サーバで404になりファイル選択画面が出てしまう)
      const r = await fetch("answer_key_merged.json", {cache:"no-store"});
      if (r.ok) return await r.json();
    } catch (e) { /* fetch不可 → ファイル選択へ */ }
  }
  return await new Promise((resolve) => {
    screen.innerHTML = `<h1>正解表を選択してください</h1>
      <p class="muted">このページはかな→音声ファイルの対応づけに <b>answer_key_merged.json</b>(Git管理外・研究者のみ保有)が必要です。
      公開サーバには置いていないため、手元のファイルを選択してください。ファイルは<b>この端末内でのみ</b>使われ、どこにも送信されません。</p>
      <p><input type="file" id="akfile" accept=".json,application/json"></p>`;
    document.getElementById("akfile").addEventListener("change", (ev) => {
      const f = ev.target.files[0];
      if (!f) return;
      const rd = new FileReader();
      rd.onload = () => {
        try { resolve(JSON.parse(rd.result)); }
        catch (e) { screen.querySelector("p.muted").textContent = "JSONとして読めませんでした: " + e.message; }
      };
      rd.readAsText(f);
    });
  });
}

async function preload() {
  screen.innerHTML = `<h1>読み込み中…</h1><p class="muted">マニフェストと正解表(ローカル)、音声68クリップを読み込んでいます。</p>`;
  const mres = await fetch(`${POOL_BASE}audio1char_manifest.json`, {cache:"no-store"});
  if (!mres.ok) throw new Error("audio1char_manifest.json が読めない");
  const manifest = await mres.json();
  // v3.0: どの話者・音高のプールを鳴らしているかを記録し、結果JSONと画面に出す。
  poolMeta = { speaker: manifest.speaker, speaker_name: SPEAKER_NAMES[manifest.speaker] || `id=${manifest.speaker}`,
               pitch_scheme: manifest.pitch_scheme, mora_dur_s: manifest.mora_dur_s, pool: POOL || "production" };
  // v1.8: 各クリップの「実際に音が始まる位置」(音響的開始)の対応表。
  // スロット先頭を起点に打ち切ると先頭50msがほぼ無音(68音中66音)で、短い間隔の試行が無音になっていたため、
  // 打ち切りの起点を実測した音響的開始に置き直す。
  const ores = await fetch(`${POOL_BASE}audio1char_onsets.json`, {cache:"no-store"});
  if (!ores.ok) throw new Error("audio1char_onsets.json が読めない");
  onsets = await ores.json();
  const akey = await loadAnswerKey();
  for (const s of manifest.stimuli) {
    const rec = akey[`audio1char|${s.id}`];
    if (rec && rec.char) stimByChar[rec.char] = s;
  }
  const have = CHARS.filter(c => stimByChar[c]);
  if (have.length < 60) throw new Error(`正解表と音声の対応が不足(${have.length}/68)`);
  // 68クリップをデコード
  let done = 0;
  await Promise.all(have.map(async ch => {
    const s = stimByChar[ch];
    const r = await fetch(`${POOL_BASE}audio1char_stimuli/${s.file}?v=${VERSION}`);
    bufByChar[ch] = await ensureCtx().decodeAudioData(await r.arrayBuffer());
    done++; if (done % 12 === 0) screen.querySelector("p").textContent = `音声デコード中… ${done}/${have.length}`;
  }));
}

function shuffle(a){ for(let i=a.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; } return a; }
function pick(a){ return a[Math.floor(Math.random()*a.length)]; }
function avail(){ return CHARS.filter(c => bufByChar[c]); }
// 3音の組: すべて別の音にする。1音目と同じ音の再登場は「最初の音」の判断を壊すため。
function pickTriple(){
  const A=avail();
  const c1=pick(A);
  let c2=pick(A); while(c2===c1) c2=pick(A);
  let c3=pick(A); while(c3===c1||c3===c2) c3=pick(A);
  return [c1,c2,c3];
}

// v2.1: 本番の1音目・2音目は、混ぜた音のリストから順に配り、同じ音の繰り返し出題をなくす。
// 完全ランダムでは同じ音が偶然何度も出て(例: v1.8〜2.0の3回で「つ」「ぽ」が6回ずつ全敗)、
// 苦手な音の偏りが特定の間隔水準の成績を歪めるため。
function dealPairs(n){
  const A=avail();
  const grow=d=>{ while(d.length<n+1) d.push(...shuffle([...A])); return d; };
  const d1=grow(shuffle([...A])).slice(0,n);
  const d2=grow(shuffle([...A]));
  const pairs=[];
  for(let i=0;i<n;i++){
    const j=d2.findIndex(c=>c!==d1[i]);
    pairs.push([d1[i], d2.splice(j,1)[0]]);
  }
  return pairs;
}

function buildTrials() {
  const main = [];
  const pairs = dealPairs(SOA_LEVELS.length * PER_LEVEL);
  const A = avail();
  let pi = 0;
  for (const S of SOA_LEVELS) for (let k=0;k<PER_LEVEL;k++) {
    const [c1,c2] = pairs[pi++];
    let c3 = pick(A); while (c3===c1 || c3===c2) c3 = pick(A);
    main.push({S,c1,c2,c3,practice:false});
  }
  shuffle(main);
  // 練習は流れを覚えるため、あえて長め(聞き取りやすい)間隔の2水準から出す
  const easy = [...SOA_LEVELS].sort((a,b)=>b-a).slice(0,2);
  const prac = [];
  for (let k=0;k<N_PRACTICE;k++) { const [c1,c2,c3]=pickTriple(); prac.push({S:pick(easy),c1,c2,c3,practice:true}); }
  return prac.concat(main);
}

// クリップの「実際に音が始まる位置から d 秒」をゲートして再生するバッファを作る。
// v1.8: 起点をスロット先頭でなく実測の音響的開始(audio1char_onsets.json)に置く。
// これによりS=50でも「音の先頭50ms」が必ず鳴る(以前はほぼ無音だった)。
function gatedBuffer(ch, gateS) {
  const s = stimByChar[ch], src = bufByChar[ch];
  const sr = src.sampleRate;
  const onMs = (onsets[ch] && onsets[ch].acoustic_onset_ms) || 0;
  // v1.9: クリップ間の音量差(最大36倍)を正規化する。増幅率は事前計算(有音部RMSを中央値に揃え、ピーク0.85で頭打ち)。
  const gain = (onsets[ch] && onsets[ch].gain) || 1.0;
  const start = Math.floor((s.char_onset_s + onMs/1000) * sr);
  const avail = Math.max(0.01, s.char_dur_s - onMs/1000);   // スロット末までの残り
  const dur = Math.min(gateS, avail);
  const n = Math.max(1, Math.floor(dur * sr));
  const out = ensureCtx().createBuffer(1, n, sr);
  const a = src.getChannelData(0), b = out.getChannelData(0);
  for (let i=0;i<n;i++) b[i] = (a[start+i] || 0) * gain;
  const nf = Math.min(Math.floor(FADE_S*sr), n>>1);
  for (let i=0;i<nf;i++){ b[i]*=i/nf; b[n-1-i]*=i/nf; }   // 立上げ/立下げフェード
  return out;
}
// v1.7: 雑音バーストを廃止し、「答えさせない3音目」で2音目の聞こえ終わりを揃える(視覚の乙課題と対称)。
function playSeq(t) {
  const ctx = ensureCtx();
  const t0 = ctx.currentTime + 0.15;
  const S = t.S/1000;
  const s1 = ctx.createBufferSource(); s1.buffer = gatedBuffer(t.c1, S); s1.connect(ctx.destination); s1.start(t0);
  const s2 = ctx.createBufferSource(); s2.buffer = gatedBuffer(t.c2, S); s2.connect(ctx.destination); s2.start(t0 + S);
  const s3 = ctx.createBufferSource(); s3.buffer = gatedBuffer(t.c3, S); s3.connect(ctx.destination); s3.start(t0 + 2*S);
  return (t0 + 3*S + 0.05 - ctx.currentTime) * 1000;   // 終了までのms
}

// 練習の後、本番に入る前の確認画面。クリック/スペースで本番開始。
function showMainGate(next) {
  const nMain = trials.length - N_PRACTICE;
  screen.innerHTML = `<div style="text-align:center;padding:40px 20px">
    <h2 style="color:#1E2A5E">これから本番です</h2>
    <p>本番では <b>正解は表示されません</b>。ここからの回答が記録されます。</p>
    <p class="muted">本番は <b>${nMain}問</b>（各2文字回答）です。やり方は練習と同じです。ヘッドホンの装着を確認してください。</p>
    <p style="margin-top:20px"><button class="primary" id="mainGo">本番を始める（またはスペースキー）</button></p></div>`;
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go(){ document.removeEventListener("keydown", key); next(); }
  document.getElementById("mainGo").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
}

function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  if (!inPractice && !mainStarted) { mainStarted = true; return showMainGate(runTrial); }
  screen.innerHTML = `<div class="muted">${inPractice ? `練習 ${ti+1} / ${N_PRACTICE}` : `本番 ${ti-N_PRACTICE+1} / ${trials.length-N_PRACTICE}`} (間隔=${t.S}ms)</div>
    <div id="stage">♪</div>`;
  const stage = document.getElementById("stage");
  startGate(stage, () => {
    stage.innerHTML = "♪";
    const waitMs = playSeq(t);
    setTimeout(() => respond(t, inPractice), waitMs + 120);
  });
}
// 出題の開始ゲート。既定はクリック/スペースで自己ペース開始(準備を保証)。押下後に短い間をおいて再生。
function startGate(stage, onPlay) {
  const begin = () => {
    stage.innerHTML = `<div style="text-align:center"><div style="font-size:40px;color:#2E7D8F">♪</div><div class="muted">まもなく音が鳴ります…</div></div>`;
    setTimeout(onPlay, 500 + Math.floor(Math.random()*300));   // クリック直後の即発火を避けるゆらぎ
  };
  if (START_MODE === "none") return begin();
  if (START_MODE === "countdown") return runCountdown(stage, begin);
  stage.style.height = "auto";
  stage.innerHTML = `<div style="text-align:center;padding:24px">
    <button class="primary" id="startBtn">準備ができたら開始（またはスペースキー）</button>
    <div class="muted" style="margin-top:8px">押すと少し後に、音が3つ続けて鳴ります。耳を澄ませてください。</div></div>`;
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go(){ document.removeEventListener("keydown", key); begin(); }
  document.getElementById("startBtn").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
}
// カウントダウン(countdownモード用)。COUNTDOWN_S 秒だけ数字を出してから done() を呼ぶ。
function runCountdown(stage, done) {
  if (COUNTDOWN_S <= 0) return done();
  let s = COUNTDOWN_S;
  const render = () => { stage.innerHTML =
    `<div style="text-align:center"><div style="font-size:64px;font-weight:700;color:#2E7D8F">${s}</div>` +
    `<div class="muted">まもなく音が鳴ります（耳を澄ませて）</div></div>`; };
  render();
  const iv = setInterval(() => {
    s -= 1;
    if (s <= 0) { clearInterval(iv); done(); }
    else render();
  }, 1000);
}
function respond(t, inPractice) {
  askOne(t, 1, (r1) => {
    askOne(t, 2, (r2) => {
      if (!inPractice) {
        const rec = { c1:t.c1, c2:t.c2, c3:t.c3, S:t.S, resp1:r1, resp2:r2,
          correct1:r1===t.c1, correct2:r2===t.c2 };
        results.push(rec);
        if (window.PROD) PROD.saveTrial("soa_audio", prodMeta(), rec, results.length-1);
        ti++; runTrial(); return;
      }
      // 練習: 3音の内訳を提示して流れを覚えてもらう
      const ok1 = r1===t.c1, ok2 = r2===t.c2;
      screen.innerHTML = `<div style="text-align:center;padding:30px">
        <p>正解 — 1つ目「<b style="font-size:20px">${t.c1}</b>」<span style="color:${ok1?'#2E7D8F':'#C25B4E'}">${ok1?'◯':'×'}</span>
        ／ 2つ目「<b style="font-size:20px">${t.c2}</b>」<span style="color:${ok2?'#2E7D8F':'#C25B4E'}">${ok2?'◯':'×'}</span></p>
        <p class="muted">3つ目は「${t.c3}」でした（これは<b>答えない</b>音です）。</p>
        <p class="muted">これは練習です。本番も同じ流れ（1つ目 → 2つ目 → 3つ目 → 2つ回答）をくり返します。</p></div>`;
      setTimeout(() => { ti++; runTrial(); }, 2000);
    });
  });
}
function askOne(t, pos, done) {
  const stage = document.getElementById("stage");
  stage.style.height = "auto";   // 聴取エリアの空欄を詰めて、かなの表をプロンプト直下に出す
  const label = pos===1 ? "1つ目（最初に聞こえた音）は？" : "2つ目（2番目に聞こえた音）は？";
  stage.innerHTML = `<div class="ask" style="font-size:18px">${label}</div>
    <div class="muted">分からなければ勘でOK（聞こえなかったと感じても、あとの音を答えずに勘で選んでください）</div>`;
  document.getElementById("grid")?.remove();
  const grid = document.createElement("div"); grid.id="grid";
  for (const row of GRID_AUDIO) for (const ch of row) {
    if (ch==="") { const s=document.createElement("div"); s.className="kana spacer"; grid.appendChild(s); continue; }
    const b=document.createElement("button"); b.className="kana"; b.textContent=kanaLabel(ch);
    b.onclick = () => done(ch);
    grid.appendChild(b);
  }
  stage.parentElement.appendChild(grid);
}

function byLevel() {
  const m = {};
  for (const S of SOA_LEVELS) m[S] = { n:0, ok1:0, ok2:0, okBoth:0 };
  for (const r of results) { const e=m[r.S]; e.n++; if(r.correct1)e.ok1++; if(r.correct2)e.ok2++; if(r.correct1&&r.correct2)e.okBoth++; }
  return SOA_LEVELS.map(S => ({ S, n:m[S].n,
    acc1:m[S].n?m[S].ok1/m[S].n:null, acc2:m[S].n?m[S].ok2/m[S].n:null, accBoth:m[S].n?m[S].okBoth/m[S].n:null }));
}
function svgCurves(rows) {
  const W=460,H=230,ml=44,mb=30,mt=12,mr=12;
  const lo=Math.min(...SOA_LEVELS), hi=Math.max(...SOA_LEVELS);
  const xs=S=> ml + (S-lo)/(hi-lo)*(W-ml-mr);
  const ys=a=> mt + (1-a)*(H-mt-mb);
  const line=(key,color,dash)=>{
    const pts=rows.filter(r=>r[key]!=null).map(r=>`${xs(r.S).toFixed(1)},${ys(r[key]).toFixed(1)}`).join(" ");
    const dots=rows.filter(r=>r[key]!=null).map(r=>`<circle cx="${xs(r.S)}" cy="${ys(r[key])}" r="4" fill="${color}"/>`).join("");
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" ${dash?`stroke-dasharray="5 3"`:""}/>`+dots;
  };
  const chance=1/CHARS.length;
  return `<svg width="${W}" height="${H}" style="background:#fff;border:1px solid #eee">
    <line x1="${ml}" y1="${ys(chance)}" x2="${W-mr}" y2="${ys(chance)}" stroke="#bbb" stroke-dasharray="4"/>
    ${line("acc1","#1E2A5E",false)}
    ${line("acc2","#2E7D8F",true)}
    <text x="${ml}" y="${H-8}" font-size="11">${lo}ms</text>
    <text x="${W-mr-34}" y="${H-8}" font-size="11">${hi}ms</text>
    <text x="8" y="${mt+8}" font-size="11">100%</text>
    <text x="${W/2-56}" y="${H-2}" font-size="11">音の間隔 S (ms)</text>
    <rect x="${ml+8}" y="${mt+4}" width="10" height="3" fill="#1E2A5E"/><text x="${ml+22}" y="${mt+10}" font-size="10.5">char1(先頭)</text>
    <rect x="${ml+8}" y="${mt+20}" width="10" height="3" fill="#2E7D8F"/><text x="${ml+22}" y="${mt+26}" font-size="10.5">char2(末尾)</text>
  </svg>`;
}
function showResults() {
  const rows = byLevel();
  // 本番モード: セッション完了を記録し、完了コードを表示して終わる(結果グラフは出さない)。
  if (window.PROD && PROD.enabled) {
    PROD.saveDone("soa_audio", prodMeta(),
      { byLevel: rows, env: ENV, duration_s: Math.round((Date.now()-T0)/1000) });
    screen.innerHTML = PROD.completionHTML(Math.round((Date.now()-T0)/1000));
    return;
  }
  const pc=v=>v==null?"-":(v*100).toFixed(0)+"%";
  const tbl = `<table><tr><th>SOA(ms)</th>${rows.map(r=>`<td>${r.S}</td>`).join("")}</tr>
    <tr><th>char1</th>${rows.map(r=>`<td>${pc(r.acc1)}</td>`).join("")}</tr>
    <tr><th>char2</th>${rows.map(r=>`<td>${pc(r.acc2)}</td>`).join("")}</tr>
    <tr><th>両方</th>${rows.map(r=>`<td>${pc(r.accBoth)}</td>`).join("")}</tr>
    <tr><th>n(対)</th>${rows.map(r=>`<td>${r.n}</td>`).join("")}</tr></table>`;
  screen.innerHTML = `<h1>パイロット完了</h1>
    <p class="muted">音の間隔Sに対する位置別の識別率(聴覚)。1つ目の正答率が、S=200で頭打ちの値(450・700)と同じなら、0.2秒の間隔に干渉はないと判定できます。</p>
    ${svgCurves(rows)} ${tbl}
    <p><button class="primary" id="dl">結果JSONをダウンロード</button></p>`;
  document.getElementById("dl").onclick = () => {
    // v3.0: どの話者・音高のプールで採ったデータかを config に残す(話者を変えた前後のデータを取り違えないため)
    const blob = new Blob([JSON.stringify({ config:{VERSION,SOA_LEVELS,PER_LEVEL,
      speaker:poolMeta.speaker, speaker_name:poolMeta.speaker_name, pitch:poolMeta.pitch_scheme,
      mora_dur_s:poolMeta.mora_dur_s, pool:poolMeta.pool,
      ONSET_ANCHORED:true, LOUDNESS_NORMALIZED:"A-weighted", START_MODE}, env:ENV, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_audio_${Date.now()}.json`; a.click();
  };
}

function start() { ensureCtx().resume(); trials = buildTrials(); results = []; ti = 0; mainStarted = false; runTrial(); }
function intro() {
  // v2.3: 古い音源がキャッシュから読まれたまま本番をやるとデータが無効になるので、
  // 音そのものを実測して警告する(点検モードと同じ判定)。
  const fp = poolFingerprint();
  const staleWarn = fp.isNew ? `` :
    `<p style="background:#fdecec;border:1px solid #d9534f;border-radius:8px;padding:10px 12px">
     <b style="color:#a72b2b">★ 古い音源がブラウザのキャッシュから読み込まれています。</b>
     このまま実施するとデータが使えません。<b>強制再読み込み（Macは Command+Shift+R）</b>してから始めてください。
     <span class="muted">(最も小さい音「${fp.minCh}」の音源ピーク=${fp.minPeak.toFixed(3)}、新しい音源なら0.1前後)</span></p>`;
  const startNote = START_MODE==="click"
    ? `各問題は、準備ができたら <b>ボタン（またはスペースキー）</b> を押して自分のペースで始めます。`
    : START_MODE==="countdown" ? `各問題の前に${COUNTDOWN_S}秒のカウントダウンが出ます。` : ``;
  const mobileNote = ENV.touch
    ? `スマートフォンの内蔵スピーカーでは正しく聞き取れません。必ず<b>ヘッドホン／イヤホン</b>を使ってください。` : ``;
  screen.innerHTML = `<h1>iFont パイロット: 聴覚・連続する音の間隔掃引（乙課題）</h1>
    ${staleWarn}
    <p><b>1問で答える音は「2つ」です。</b>かなの音声が<b>3つ</b>つづけて流れます（3つ目は答えない音です）。${startNote}以下の手順で進みます。</p>
    <ol style="font-size:15px;line-height:1.9;padding-left:1.2em">
      <li>準備ができたら <b>開始</b>（ボタン／スペース）</li>
      <li><b>1つ目</b>の音（かな）が鳴る（<b>${SOA_LEVELS.join("・")}ms</b> のいずれかの間隔で次の音に切り替わる）</li>
      <li>すぐ <b>2つ目</b>、つづけて <b>3つ目</b> の音が鳴る</li>
      <li><b>1つ目 → 2つ目</b> の順に、かなの表から選ぶ（<b>3つ目は答えない</b>）</li>
    </ol>
    <p class="muted">かなは<b>単独で読んだときの音</b>です（「は」はハ、「へ」はヘ）。「じ／ぢ」のように<b>同じ音のかなは1つのボタンにまとめて</b>あり、どちらの字かを選ぶ必要はありません。</p>
    <p style="background:#fff8ec;border:1px solid #eadfc8;border-radius:8px;padding:10px 12px">
    <b>必ず3つ鳴ります。</b>間隔が短い問題では、1つ目が聞こえなかったと感じることがあります。
    そのときも、<b>あとから聞こえた音を1つ目として答えず</b>、勘で選んでください。</p>
    <p style="background:#eef4f6;border-radius:8px;padding:10px 12px">まず <b>練習 ${N_PRACTICE}問</b>（正解を表示）→ そのあと <b>本番 ${SOA_LEVELS.length*PER_LEVEL}問</b>（各2文字回答・正解は非表示・記録あり）を行います。所要8〜12分。</p>
    <p class="muted">短く切り替わるので聞き取りにくい音もあります。分からなければ勘でOKです（外れも大切なデータ）。音声は単音プール(B3・0.2秒/モーラ)。</p>
    <p style="background:#fff6f4;border:1px solid #f0d0c8;border-radius:8px;padding:10px 12px">
      <button id="sample" style="font-size:14px;padding:6px 14px;border-radius:6px;border:1px solid #c9a9a0;background:#fff;cursor:pointer">サンプル音を鳴らす（あ・か・ん）</button>
      <span class="muted" style="margin-left:8px">聞き取りやすい音量に合わせてください</span><br>
      <label style="cursor:pointer;display:inline-block;margin-top:8px"><input type="checkbox" id="hp"> <b>ヘッドホン／イヤホンを装着し、音量を確認しました</b></label>
      <span class="muted" style="display:block;margin-top:4px">${mobileNote}この課題はスピーカー再生では正しく測れません。</span></p>
    <p><button class="primary" id="go" disabled style="opacity:.5">練習を始める（${N_PRACTICE}問）</button></p>
    <p class="muted" style="text-align:right;font-size:12px;margin-top:6px">${(window.PROD&&PROD.enabled)?"津田塾大学 認知・知覚研究":"研究者向けパイロット版 v"+VERSION}</p>`;
  const hp = document.getElementById("hp"), go = document.getElementById("go");
  // サンプル音: 各音を打ち切らずに(実音の全長で)0.5秒間隔で3つ鳴らす
  document.getElementById("sample").onclick = () => {
    const ctx = ensureCtx(); ctx.resume();
    ["あ","か","ん"].forEach((ch, i) => {
      if (!bufByChar[ch]) return;
      const src = ctx.createBufferSource();
      src.buffer = gatedBuffer(ch, 0.2);
      src.connect(ctx.destination); src.start(ctx.currentTime + 0.1 + i*0.5);
    });
  };
  hp.addEventListener("change", () => { go.disabled = !hp.checked; go.style.opacity = hp.checked ? "1" : ".5"; });
  go.onclick = () => { if (hp.checked) start(); };
}

// v2.2: 音の点検モード(?check=1)。課題を通さずに、正規化後の68音を1音ずつ確かめる。
// かなを押すとその音が本番と同じ処理(音響的開始からのゲート・A特性の増幅)で1回鳴る。
// 「すべて順に再生」は五十音順に流し、いま鳴っている音のかなを表示する。
function playOne(ch){
  const ctx = ensureCtx(); ctx.resume();
  const s = ctx.createBufferSource(); s.buffer = gatedBuffer(ch, 0.2); s.connect(ctx.destination); s.start();
}

// v2.3: いま鳴らしている音源が再合成後のものかを、メタデータでなく
// 「デコードした音声そのもの」を測って判定する。
// 旧プールは合成が病的に小さい音(う=ピーク約0.013)を含み、増幅で辻褄を合わせていた。
// 新プールは合成時に音量をそろえてあるので、最も小さい音でもピークは0.1前後ある。
// ブラウザが古い音源をキャッシュから返している場合、ここで検出できる。
function poolFingerprint(){
  let minPeak = Infinity, minCh = null;
  const per = {};
  for (const ch of avail()) {
    const s = stimByChar[ch], src = bufByChar[ch], sr = src.sampleRate;
    const a = Math.floor(s.char_onset_s * sr);
    const b = Math.floor((s.char_onset_s + s.char_dur_s) * sr);
    const d = src.getChannelData(0);
    let pk = 0;
    for (let i = a; i < b && i < d.length; i++) { const v = Math.abs(d[i]); if (v > pk) pk = v; }
    per[ch] = pk;
    if (pk < minPeak) { minPeak = pk; minCh = ch; }
  }
  return { minPeak, minCh, uPeak: per["う"] || 0, isNew: minPeak > 0.05 };
}
function showCheck(){
  const A = avail();
  const fp = poolFingerprint();
  // v3.0: 「いま鳴っているのが誰の声か」はマニフェストのspeakerで確定させる(音響指紋より確実)。
  // 音響指紋(poolFingerprint)は、ブラウザが古い音源をキャッシュから返す事故の検出に使う。
  const box = fp.isNew
    ? `<div style="background:#e8f6ec;border:1px solid #57a773;border-radius:8px;padding:10px 12px;margin:10px 0">
         <b style="color:#2b6b45">✓ 話者「${poolMeta.speaker_name}」・音高${poolMeta.pitch_scheme} を鳴らしています（パイロット版 v${VERSION}）</b>
         <div class="muted" style="margin-top:4px">音源の健全性(実測): 最も小さい音「${fp.minCh}」のピーク=${fp.minPeak.toFixed(3)}、
         「う」=${fp.uPeak.toFixed(3)}。病的に小さい音がある古い音源ならピークは0.013前後になります。</div></div>`
    : `<div style="background:#fdecec;border:1px solid #d9534f;border-radius:8px;padding:10px 12px;margin:10px 0">
         <b style="color:#a72b2b">★ 古い音源がブラウザのキャッシュから読み込まれています</b>
         <div class="muted" style="margin-top:4px">最も小さい音「${fp.minCh}」の音源ピーク=${fp.minPeak.toFixed(3)}（健全な音源なら0.1前後）。
         <b>強制再読み込み（Macは Command+Shift+R）</b>してからもう一度お試しください。</div></div>`;
  const btn = c => c ? `<button class="kbtn" data-ch="${c}" style="width:44px;height:44px;margin:2px;font-size:20px">${c}</button>`
                     : `<span style="display:inline-block;width:48px"></span>`;
  const rows = GRID_AUDIO.map(row => `<div>${row.map(btn).join("")}</div>`).join("");
  const poolLink = (q, label) => (POOL === q || (!POOL && !q))
    ? `<b style="padding:4px 10px;border-radius:6px;background:#2E7D8F;color:#fff">${label}</b>`
    : `<a style="padding:4px 10px" href="?check=1${q?`&pool=${q}`:""}">${label}</a>`;
  const links = [["", "本番: 東北きりたん"]].concat(Object.entries(POOL_NAMES));
  screen.innerHTML = `<h1>音の点検モード（全${A.length}音）</h1>
    <p style="font-size:15px;line-height:2.2">話者を切り替えて聴き比べ:
      ${links.map(([q, label]) => poolLink(q, label)).join(" ")}</p>
    ${box}
    <p class="muted">かなを押すと、その音が<b>本番とまったく同じ処理</b>(増幅・200ms)で1回鳴ります。
    「すべて順に再生」は五十音順に0.7秒間隔で流します。弱い・聞こえない・別の音に聞こえるものがあればメモして報告してください。</p>
    <p><button class="primary" id="playAll">すべて順に再生</button>
       <span id="nowCh" style="font-size:32px;font-weight:700;color:#2E7D8F;margin-left:16px"></span></p>
    <div>${rows}</div>`;
  screen.querySelectorAll(".kbtn").forEach(b => b.addEventListener("click", () => {
    document.getElementById("nowCh").textContent = b.dataset.ch;
    playOne(b.dataset.ch);
  }));
  let playing = false;
  document.getElementById("playAll").addEventListener("click", () => {
    if (playing) return; playing = true;
    A.forEach((ch, i) => setTimeout(() => {
      document.getElementById("nowCh").textContent = ch;
      playOne(ch);
      if (i === A.length - 1) playing = false;
    }, i * 700));
  });
}

const T0 = Date.now();   // 所要時間の起点
function prodMeta(){ return { version:VERSION, speaker:poolMeta.speaker,
  speaker_name:poolMeta.speaker_name, pitch:poolMeta.pitch_scheme }; }

(async function(){
  // 候補プール指定時は点検モード専用(候補音源で本番課題は実施させない)
  try {
    await preload();
    if (POOL || P.has("check")) return showCheck();
    // 本番モード(?prod=1)は同意画面を挟んでから教示へ。研究者パイロットは従来どおり直行。
    if (window.PROD && PROD.enabled) PROD.consentScreen(screen, "かなの聞き取りの課題（音声・約10分）", 10, intro, true);
    else intro();
  }
  catch(e){ screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}</p>`; }
})();
