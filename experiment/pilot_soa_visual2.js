// iFont パイロット: 視覚・連続する文字の間隔掃引(乙課題) 自己完結版。
// v1.7: 較正の視覚課題を乙ひとつに統合した(PI決定 2026-07-17)。
//   ・画面は「1文字目(S ms) → 2文字目が上書き(S ms) → 3文字目が上書き(S ms) → 白紙」。
//   ・1文字目と2文字目を順に回答する。3文字目は答えない字(2文字目の見え終わりを揃える役)。
//   ・モザイクは廃止。採点されるすべての文字が「次の文字」で見え終わる=運用と同じ形。
//   ・判定は乙の内部で完結する: char1の正答率が S=200 で頭打ちの値(450・700)と同じなら0.2秒に干渉なし。
//   ・下限は50ms(60Hzで3フレームの表示安全域)。それより短い水準は ?levels= の研究者調整のみ。
//   ・この課題では小書きかな(っゃゅょ)をどの位置にも使わない(消す力が弱い/まとまり読みが起きるため。PI決定)。
//     小書き自体の見えやすさはfracの1文字課題(78字)で測る。
// jsPsych・音声・サーバ不要。base/<かな>.png を流用。結果は画面表示＋JSONダウンロード。
"use strict";

const VERSION = "2.33";   // パイロットのバージョン(細かい改変ごとにインクリメント)
const P = new URLSearchParams(location.search);
const SOA_LEVELS = (P.get("levels") || "50,83,133,200,300,450,700").split(",").map(Number);
const PER_LEVEL = Number(P.get("perlevel") || 6);   // 各水準の組数(1組=2回答)
const N_PRACTICE = Number(P.get("practice") || 2);
const BLANK_MS = 200;                                // 3文字目のあとの白紙(回答画面への間)
const FIX_MS = 400;
const COUNTDOWN_S = Number(P.get("countdown") ?? 5); // countdownモード時の秒数
const COUNTDOWN_MS = COUNTDOWN_S * 1000;
const START_MODE = P.get("start") || "click";        // "click"(既定・自己ペース) / "countdown" / "none"
const FIX_JITTER = 300;                              // 注視点の追加ゆらぎ上限(ms・先読み防止)
const SIZE = 256;

// 端末・表示環境(実測タイミング解析用にログする)
const ENV = { ua: navigator.userAgent, dpr: window.devicePixelRatio || 1,
  screen: `${window.screen.width}x${window.screen.height}`, touch: (navigator.maxTouchPoints || 0) > 0, refreshHz: null };
(function measureRefresh(){ let n=0; const t0=performance.now();
  function f(now){ n++; if(n<40) requestAnimationFrame(f); else ENV.refreshHz = Math.round(1000/((now-t0)/n)); }
  requestAnimationFrame(f);
})();
// 本番モードの送信本文にも端末環境を載せる(オブジェクトの参照を渡すので、
// あとから確定するリフレッシュレートも送信時の値が読まれる)。
if (window.PROD) PROD.setEnv(ENV);

// 既定は、視覚と聴覚で対応が取れる「独立モーラ72字」。
const GRID_MORA = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],["ゔ","","","",""],
];
// 基礎データモード(?charset=full)では ゐゑ を含む表を使う。小書きかなは表には出るが出題には使わない。
const GRID_FULL = [
  ["あ","い","う","え","お"],["か","き","く","け","こ"],["さ","し","す","せ","そ"],
  ["た","ち","つ","て","と"],["な","に","ぬ","ね","の"],["は","ひ","ふ","へ","ほ"],
  ["ま","み","む","め","も"],["や","","ゆ","","よ"],["ら","り","る","れ","ろ"],
  ["わ","","","","を"],["ん","","","",""],
  ["が","ぎ","ぐ","げ","ご"],["ざ","じ","ず","ぜ","ぞ"],["だ","ぢ","づ","で","ど"],
  ["ば","び","ぶ","べ","ぼ"],["ぱ","ぴ","ぷ","ぺ","ぽ"],
  ["ゃ","","ゅ","","ょ"],["っ","","","",""],
  ["ゐ","","","","ゑ"],["ゔ","","","",""],
];
const SMALL_KANA = ["ゃ","ゅ","ょ","っ"];
const CHARSET = (P.get("charset") === "full") ? "full" : "mora";
const GRID_KANA = CHARSET === "full" ? GRID_FULL : GRID_MORA;
const GRID_CHARS = GRID_KANA.flat().filter(Boolean);
const CHARS = GRID_CHARS.filter(c => !SMALL_KANA.includes(c));   // 出題に使う字(小書きを除く)

const screen = document.getElementById("screen");
const imgs = {};
let trials = [], results = [], ti = 0, mainStarted = false;
// 途中再開(本番モードのみ): 読み込み時に PROD.loadState が返した途中状態。
// elapsedPrior は再開前までの経過秒(所要時間の通算用)。
let resumeState = null, elapsedPrior = 0;

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
      <div id="loadBar" style="height:100%;width:0%;background:#1E2A5E"></div></div></div>`;
  let done = 0;
  await Promise.all(CHARS.map(async ch => {
    imgs[ch] = await loadImage(ch);
    done++; const bar = document.getElementById("loadBar");
    if (bar) bar.style.width = `${Math.round(done / CHARS.length * 100)}%`;
  }));
}

function shuffle(a){ for(let i=a.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; } return a; }
function pick(a){ return a[Math.floor(Math.random()*a.length)]; }
// 3文字の組: すべて別の字にする。1文字目と同じ字の再登場は「最初の字」の判断を壊すため。
function pickTriple(){
  const c1 = pick(CHARS);
  let c2 = pick(CHARS); while (c2 === c1) c2 = pick(CHARS);
  let c3 = pick(CHARS); while (c3 === c1 || c3 === c2) c3 = pick(CHARS);
  return [c1, c2, c3];
}

// v2.1: 本番の1文字目・2文字目は、混ぜた字のリストから順に配り、同じ字の繰り返し出題をなくす。
// 完全ランダムでは同じ字が偶然何度も出て、苦手な字の偏りが特定の間隔水準の成績を歪めるため。
function dealPairs(n){
  const grow=d=>{ while(d.length<n+1) d.push(...shuffle([...CHARS])); return d; };
  const d1=grow(shuffle([...CHARS])).slice(0,n);
  const d2=grow(shuffle([...CHARS]));
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
  let pi = 0;
  for (const S of SOA_LEVELS) for (let k=0;k<PER_LEVEL;k++) {
    const [c1,c2] = pairs[pi++];
    let c3 = pick(CHARS); while (c3===c1 || c3===c2) c3 = pick(CHARS);
    main.push({ S, c1, c2, c3, practice:false });
  }
  shuffle(main);
  // 練習は流れを覚えるため、あえて長め(見やすい)間隔の2水準から出す
  const easy = [...SOA_LEVELS].sort((a,b)=>b-a).slice(0,2);
  const prac = [];
  for (let k=0;k<N_PRACTICE;k++) { const [c1,c2,c3]=pickTriple(); prac.push({ S: pick(easy), c1, c2, c3, practice:true }); }
  return prac.concat(main);
}

function newCanvas() { const c=document.createElement("canvas"); c.id="stim"; c.width=SIZE; c.height=SIZE; return c; }
function drawChar(ctx, ch) { ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE); if (imgs[ch]) ctx.drawImage(imgs[ch],0,0,SIZE,SIZE); }
function drawBlank(ctx) { ctx.fillStyle="#fff"; ctx.fillRect(0,0,SIZE,SIZE); }
function drawFix(ctx) {
  drawBlank(ctx);
  ctx.fillStyle="#333"; ctx.font="40px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  ctx.fillText("+", SIZE/2, SIZE/2);
}
function drawCountdown(ctx, sec) {
  drawBlank(ctx);
  ctx.fillStyle="#2E7D8F"; ctx.font="bold 72px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  ctx.fillText(String(sec), SIZE/2, SIZE/2 - 12);
  ctx.fillStyle="#8a93a6"; ctx.font="15px system-ui";
  ctx.fillText("中央を見て準備してください", SIZE/2, SIZE/2 + 52);
}

// 進行ヘッダー: ステップ表示と本番の進捗バー。問題と問題の間でのみ更新する(表示中は動かない)。
function progressHeader(inPractice, t) {
  // 条件(間隔)の表示は研究者モードのみ。参加者には出さない。
  const dev = (window.PROD && PROD.enabled) ? "" : ` (間隔=${t.S}ms)`;
  if (inPractice) return `<div class="muted">練習 ${ti+1} / ${N_PRACTICE}${dev}</div>`;
  const nMain = trials.length - N_PRACTICE;
  const done = ti - N_PRACTICE, pct = Math.round(done / nMain * 100);
  return `<div class="muted" style="display:flex;align-items:center;gap:10px">
    <span style="white-space:nowrap">本番</span>
    <span style="flex:1;height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden"><span style="display:block;height:100%;width:${pct}%;background:#2E7D8F"></span></span>
    <span style="white-space:nowrap">${pct}%${dev}</span></div>`;
}
function runTrial() {
  if (ti >= trials.length) return showResults();
  const t = trials[ti];
  const inPractice = t.practice;
  if (!inPractice && !mainStarted) { mainStarted = true; return showMainGate(runTrial); }
  screen.innerHTML = `${progressHeader(inPractice, t)}<div id="stage"></div>`;
  const stage = document.getElementById("stage");
  startGate(stage, (ctx) => presentTrial(t, inPractice, ctx));
}

// 練習の後、本番に入る前の確認画面。クリック/スペースで本番開始。
function showMainGate(next) {
  const nMain = trials.length - N_PRACTICE;
  screen.innerHTML = `<div style="text-align:center;padding:40px 20px">
    <h2 style="color:#1E2A5E">これから本番です</h2>
    <p>本番では <b>正解は表示されません</b>。ここからの回答が記録されます。</p>
    <p class="muted">本番は <b>${nMain}問</b>です。やり方は練習と同じです。</p>
    <p style="margin-top:20px"><button class="primary" id="mainGo">本番を始める（またはスペースキー）</button></p></div>`;
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go(){ document.removeEventListener("keydown", key); next(); }
  document.getElementById("mainGo").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
}

// 開始ゲート: 文字表示枠(canvas)と「＋」を最初から出し、その下にボタンを置く。
// ボタンは表示枠の外(下)にあるので、押してもカーソルが刺激に被らず、枠も動かない。
function startGate(stage, onStart) {
  stage.style.height = "auto"; stage.innerHTML = "";
  const box = document.createElement("div"); box.style.textAlign = "center";
  const canvas = newCanvas(); canvas.style.display = "block"; canvas.style.margin = "0 auto";
  box.appendChild(canvas); stage.appendChild(box);
  const ctx = canvas.getContext("2d"); drawFix(ctx);

  if (START_MODE === "none") return onStart(ctx);
  if (START_MODE === "countdown") {
    const t0 = performance.now(); let lastSec = -1;
    (function cd(now){ const remain = COUNTDOWN_MS - (now - t0);
      if (remain > 0) { const s = Math.ceil(remain/1000); if (s!==lastSec){ drawCountdown(ctx, s); lastSec=s; } requestAnimationFrame(cd); }
      else { drawFix(ctx); onStart(ctx); }
    })(performance.now());
    return;
  }
  const btnWrap = document.createElement("div"); btnWrap.style.marginTop = "14px";
  btnWrap.innerHTML = `<button class="primary" id="startBtn">準備ができたら開始（またはスペースキー）</button>
    <div class="muted" style="margin-top:6px">上の枠の中央にある ＋ を見たまま、このボタンを押してください</div>`;
  box.appendChild(btnWrap);
  const key = (e) => { if (e.code === "Space" || e.key === " ") { e.preventDefault(); go(); } };
  function go(){ document.removeEventListener("keydown", key); btnWrap.style.visibility = "hidden"; onStart(ctx); }
  document.getElementById("startBtn").addEventListener("click", go, { once: true });
  document.addEventListener("keydown", key);
}

// 刺激提示: 注視(ゆらぎ付き) → c1(S) → c2(S) → c3(S) → 白紙 → 回答。実測の間隔を記録。
function presentTrial(t, inPractice, ctx) {
  drawFix(ctx);
  const fixDur = FIX_MS + Math.floor(Math.random() * FIX_JITTER);   // 先読み防止のゆらぎ
  const t0 = performance.now();
  let phase = "fix", t1 = 0, t2 = 0, t3 = 0, tb = 0;
  function frame(now) {
    const el = now - t0;
    if (phase==="fix" && el >= fixDur) { phase="c1"; drawChar(ctx, t.c1); t1 = now; }
    else if (phase==="c1" && el >= fixDur + t.S) { phase="c2"; drawChar(ctx, t.c2); t2 = now; }
    else if (phase==="c2" && el >= fixDur + 2*t.S) { phase="c3"; drawChar(ctx, t.c3); t3 = now; }
    else if (phase==="c3" && el >= fixDur + 3*t.S) { phase="blank"; drawBlank(ctx); tb = now; }
    else if (phase==="blank" && el >= fixDur + 3*t.S + BLANK_MS) {
      t._soa1 = Math.round(t2 - t1); t._soa2 = Math.round(t3 - t2); t._dur3 = Math.round(tb - t3);
      return respond(t, inPractice);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function respond(t, inPractice) {
  // 回答の記録・送信は「これで決定」を押した時のみ。それまでは選び直せる。
  const sel = { 1: null, 2: null };
  const finish = () => {
    const r1 = sel[1], r2 = sel[2];
    if (!inPractice) {
      const rec = {
        c1: t.c1, c2: t.c2, c3: t.c3, S: t.S,
        actual_soa1: t._soa1, actual_soa2: t._soa2, actual_dur3: t._dur3,
        resp1: r1, resp2: r2,
        correct1: r1 === t.c1, correct2: r2 === t.c2,
      };
      results.push(rec);
      if (window.PROD) PROD.saveTrial("soa_visual", { version:VERSION, charset:CHARSET }, rec, results.length-1);
      ti++;
      // 1問確定するたびに途中状態を保存(出題順ごと)。再開時はこの続きから。
      if (window.PROD && PROD.enabled) PROD.saveState("soa_visual",
        { trials, results, ti, elapsed_s: Math.round(elapsedPrior + (Date.now()-T0)/1000) });
      runTrial(); return;
    }
    // 練習: 3文字の内訳を提示して流れを覚えてもらう
    const ok1 = r1===t.c1, ok2 = r2===t.c2;
    screen.innerHTML = `<div style="text-align:center;padding:30px">
      <p>正解 — 1文字目「<b style="font-size:20px">${t.c1}</b>」<span style="color:${ok1?'#2E7D8F':'#C25B4E'}">${ok1?'◯':'×'}</span>
      ／ 2文字目「<b style="font-size:20px">${t.c2}</b>」<span style="color:${ok2?'#2E7D8F':'#C25B4E'}">${ok2?'◯':'×'}</span></p>
      <p class="muted">3文字目は「${t.c3}」でした（これは<b>答えない</b>字です）。</p>
      <p class="muted">これは練習です。本番も同じ流れ（＋ → 1文字目 → 2文字目 → 3文字目 → 白紙 → 2つ回答）をくり返します。</p></div>`;
    setTimeout(() => { ti++; runTrial(); }, 2000);
  };
  const confirmScreen = () => {
    const stage = document.getElementById("stage");
    stage.style.height = "auto";
    document.getElementById("grid")?.remove();
    stage.innerHTML = `<div style="text-align:center"><div class="ask">この回答で決定しますか？</div>
      <div style="font-size:20px;margin:12px 0">1文字目「<b>${sel[1]}</b>」 ／ 2文字目「<b>${sel[2]}</b>」</div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
        <button id="fix1" style="padding:10px 16px;font-size:15px">1文字目を直す</button>
        <button id="fix2" style="padding:10px 16px;font-size:15px">2文字目を直す</button>
        <button class="primary" id="selOk">これで決定</button></div></div>`;
    document.getElementById("fix1").onclick = () => askOne(t, 1, sel, (ch) => { sel[1]=ch; confirmScreen(); });
    document.getElementById("fix2").onclick = () => askOne(t, 2, sel, (ch) => { sel[2]=ch; confirmScreen(); });
    document.getElementById("selOk").onclick = finish;
  };
  askOne(t, 1, sel, (ch) => { sel[1]=ch;
    askOne(t, 2, sel, (ch2) => { sel[2]=ch2; confirmScreen(); }); });
}
function askOne(t, pos, sel, done) {
  const stage = document.getElementById("stage");
  stage.style.height = "auto";   // 刺激用の空欄を詰めて、かなの表をプロンプト直下に出す
  const label = pos===1 ? "1文字目（最初に出た文字）は？" : "2文字目（2番目に出た文字）は？";
  const picked = [1,2].filter(p => p!==pos && sel[p])
    .map(p => `${p}文字目「<b>${sel[p]}</b>」`).join(" ／ ");
  stage.innerHTML = `<div style="text-align:center"><div class="ask">${label}</div>
    ${picked ? `<div class="muted">選択済み — ${picked}</div>` : ""}
    <div class="muted">分からないときも、もっとも近いと思う文字を選んでください（見えなかったと感じても、あとの文字を答えないでください）</div></div>`;
  document.getElementById("grid")?.remove();
  stage.parentElement.appendChild(buildKanaGrid(done));
}
// かな表(紙の五十音表式): 縦の列=行、右端があ行。上の表が清音(〜ん)、下の表が濁音・半濁音など。
// DOMのグリッドは左から詰めるため、行の並びを逆順にして「右から左」の向きを作る。
function buildKanaGrid(done) {
  const grid = document.createElement("div"); grid.id = "grid"; grid.style.display = "block";
  const blocks = [GRID_KANA.slice(0, 11), GRID_KANA.slice(11)].filter(b => b.length);
  // 列幅を上下の表で揃える: 列数の少ない表は左側を空列で埋め、右(あ行側)に寄せる
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
        const b = document.createElement("button"); b.className = "kana"; b.textContent = ch;
        b.onclick = () => done(ch); g.appendChild(b);
      }
    }
    grid.appendChild(g);
  }
  return grid;
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
  const chance=1/GRID_CHARS.length;
  return `<svg width="${W}" height="${H}" style="background:#fff;border:1px solid #eee">
    <line x1="${ml}" y1="${ys(chance)}" x2="${W-mr}" y2="${ys(chance)}" stroke="#bbb" stroke-dasharray="4"/>
    ${line("acc1","#1E2A5E",false)}
    ${line("acc2","#2E7D8F",true)}
    <text x="${ml}" y="${H-8}" font-size="11">${lo}ms</text>
    <text x="${W-mr-34}" y="${H-8}" font-size="11">${hi}ms</text>
    <text x="8" y="${mt+8}" font-size="11">100%</text>
    <text x="${W/2-56}" y="${H-2}" font-size="11">文字の間隔 S (ms)</text>
    <rect x="${ml+8}" y="${mt+4}" width="10" height="3" fill="#1E2A5E"/><text x="${ml+22}" y="${mt+10}" font-size="10.5">1文字目</text>
    <rect x="${ml+8}" y="${mt+20}" width="10" height="3" fill="#2E7D8F"/><text x="${ml+22}" y="${mt+26}" font-size="10.5">2文字目</text>
  </svg>`;
}
function showResults() {
  const rows = byLevel();
  if (window.PROD && PROD.enabled) {
    const durS = Math.round(elapsedPrior + (Date.now()-T0)/1000);
    PROD.saveDone("soa_visual", { version:VERSION, charset:CHARSET },
      { byLevel: rows, env: ENV, duration_s: durS });
    // 完了印に置き換える: 誤って閉じても期限内なら完了コードを再表示できる(途中状態は消える)
    PROD.saveState("soa_visual", { completed: true, duration_s: durS });
    screen.innerHTML = PROD.completionHTML(durS);
    return;
  }
  const pc=v=>v==null?"-":(v*100).toFixed(0)+"%";
  const tbl = `<table><tr><th>間隔(ms)</th>${rows.map(r=>`<td>${r.S}</td>`).join("")}</tr>
    <tr><th>1文字目</th>${rows.map(r=>`<td>${pc(r.acc1)}</td>`).join("")}</tr>
    <tr><th>2文字目</th>${rows.map(r=>`<td>${pc(r.acc2)}</td>`).join("")}</tr>
    <tr><th>両方</th>${rows.map(r=>`<td>${pc(r.accBoth)}</td>`).join("")}</tr>
    <tr><th>n(組)</th>${rows.map(r=>`<td>${r.n}</td>`).join("")}</tr></table>`;
  screen.innerHTML = `<h1>パイロット完了</h1>
    <p class="muted">文字の間隔Sに対する位置別の識別率。1文字目の正答率が、S=200で頭打ちの値(450・700)と同じなら、0.2秒の間隔に干渉はないと判定できます。</p>
    ${svgCurves(rows)} ${tbl}
    <p><button class="primary" id="dl">結果JSONをダウンロード</button></p>`;
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify({ config:{VERSION,CHARSET,SOA_LEVELS,PER_LEVEL,BLANK_MS,FIX_MS,START_MODE}, env:ENV, byLevel:rows, trials:results }, null, 2)], {type:"application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `pilot_soa_visual2_${Date.now()}.json`; a.click();
  };
}

function start() {
  if (resumeState && resumeState.trials) {
    // 続きから: 出題順・回答済みデータ・位置を保存時のまま復元(順番は作り直さない)
    trials = resumeState.trials; results = resumeState.results || [];
    ti = resumeState.ti || 0; elapsedPrior = resumeState.elapsed_s || 0;
    mainStarted = true;   // 練習と本番前の確認画面はとばす(済んでいるため)
    return runTrial();
  }
  trials = buildTrials(); results = []; ti = 0; mainStarted = false; runTrial();
}
function intro() {
  const pcNote = ENV.touch
    ? `<p class="muted" style="color:#C25B4E">この実験は表示のタイミングが重要です。<b>できればPC（パソコン）での参加を推奨します。</b>スマートフォンの場合は横向き・明るさ最大でお願いします。</p>` : ``;
  const charsetNote = CHARSET==="full"
    ? `<p class="muted" style="color:#2E7D8F">基礎データモードです。回答の表に ゐ・ゑ・小書きかな を含みます（出題は小書きを除く${CHARS.length}字）。</p>` : ``;
  const resumeNote = (resumeState && resumeState.trials)
    ? `<p style="background:#eef7ee;border:1px solid #bcd9bc;border-radius:8px;padding:10px 12px">
       <b>前回の続きから再開します</b>（本番 ${resumeState.ti - N_PRACTICE + 1}問目から）。練習はとばします。</p>` : "";
  screen.innerHTML = `<h1>見分け課題の進め方</h1>
    ${pcNote}${charsetNote}${resumeNote}
    <p>この課題では、同じ場所にかなが<b>3文字</b>続けて表示されます。<b>最初の2文字を、出た順番に答えてください。</b>3文字目は回答しません。</p>
    <svg viewBox="0 0 640 162" style="width:100%;max-width:580px;display:block;margin:4px auto 8px" role="img" aria-label="課題の流れの図">
      <rect x="20" y="22" width="72" height="72" rx="10" fill="#fff" stroke="#1E2A5E"/>
      <text x="56" y="72" font-size="38" text-anchor="middle" fill="#1b2030">か</text>
      <text x="56" y="118" font-size="13" text-anchor="middle" fill="#1b2030">1文字目</text>
      <text x="103" y="64" font-size="16" text-anchor="middle" fill="#6b7280">→</text>
      <rect x="114" y="22" width="72" height="72" rx="10" fill="#fff" stroke="#1E2A5E"/>
      <text x="150" y="72" font-size="38" text-anchor="middle" fill="#1b2030">さ</text>
      <text x="150" y="118" font-size="13" text-anchor="middle" fill="#1b2030">2文字目</text>
      <text x="197" y="64" font-size="16" text-anchor="middle" fill="#6b7280">→</text>
      <rect x="208" y="22" width="72" height="72" rx="10" fill="#f4f4f4" stroke="#b0b6c2" stroke-dasharray="5 4"/>
      <text x="244" y="72" font-size="38" text-anchor="middle" fill="#9aa1ad">と</text>
      <text x="244" y="118" font-size="13" text-anchor="middle" fill="#6b7280">3文字目（答えない）</text>
      <text x="322" y="64" font-size="20" text-anchor="middle" fill="#1E2A5E">➡</text>
      <rect x="356" y="14" width="262" height="88" rx="10" fill="#fff" stroke="#cdd3e6"/>
      ${[0,1].map(r=>[0,1,2,3,4,5,6,7].map(c=>`<rect x="${372+c*29}" y="${26+r*26}" width="22" height="20" rx="4" fill="#fbfcff" stroke="#cdd3e6"/>`).join("")).join("")}
      <rect x="401" y="26" width="22" height="20" rx="4" fill="#1E2A5E"/>
      <text x="412" y="40" font-size="12" text-anchor="middle" fill="#fff">1</text>
      <rect x="459" y="52" width="22" height="20" rx="4" fill="#1E2A5E"/>
      <text x="470" y="66" font-size="12" text-anchor="middle" fill="#fff">2</text>
      <text x="487" y="118" font-size="13" text-anchor="middle" fill="#1b2030">かなの表から 1文字目 → 2文字目 の順に選ぶ</text>
      <text x="150" y="146" font-size="12" text-anchor="middle" fill="#6b7280">※実際は同じ場所に、前の字を上書きしながら表示されます</text>
    </svg>
    <ol style="font-size:15px;line-height:1.9;padding-left:1.2em">
      <li>表示枠の中央にある <b>＋</b> を見つめ、${START_MODE==="countdown" ? `${COUNTDOWN_S}秒のカウントダウンを待ちます` : `準備ができたら<b>「開始」ボタン</b>またはスペースキーを押します`}</li>
      <li>同じ場所にかなが3文字続けて表示されます（前の字は次の字で上書きされます）</li>
      <li><b>1文字目</b>に出たかなを表から選びます</li>
      <li><b>2文字目</b>に出たかなを表から選びます</li>
    </ol>
    <p style="background:#fff8ec;border:1px solid #eadfc8;border-radius:8px;padding:10px 12px">
    文字の切り替わりがとても速い問題もあります。そのため、最初の文字がはっきり見えないことがあります。
    その場合も、1文字目・2文字目それぞれについて、もっとも近いと思う文字を選んでください。</p>
    ${(window.PROD&&PROD.enabled)?"":`<p class="muted">回答はこの端末の中だけで完結します。</p>`}
    <p><button class="primary" id="go">次へ：見え方の確認</button></p>
    <p class="muted" style="text-align:right;font-size:12px;margin-top:6px">${(window.PROD&&PROD.enabled)?"津田塾大学 栗原研究室":"研究者向けパイロット版 v"+VERSION}</p>`;
  document.getElementById("go").onclick = visionCheck;
}
// 2B: 見え方の確認。本番と同じ表示枠・同じ大きさで見本の字を出し、
// 画面の距離・明るさのまま、はっきり見えることを確かめてから始める。
function visionCheck() {
  const resuming = !!(resumeState && resumeState.trials);
  screen.innerHTML = `<h2 style="color:#1E2A5E">見え方の確認</h2>
    <p>本番と同じ枠・同じ大きさで、見本の字「あ」を表示しています。
    ふだん画面を見る距離のまま、<b>はっきり見えること</b>を確認してください。見えにくい場合は画面の明るさを上げてください。</p>
    <div id="vcheck" style="text-align:center"></div>
    <p><label style="cursor:pointer"><input type="checkbox" id="vc"> <b>枠の中の文字がはっきり見えます</b></label></p>
    <p><button class="primary" id="go2" disabled style="opacity:.5">${resuming ? "続きから再開する" : `練習を始める（${N_PRACTICE}問）`}</button></p>`;
  const canvas = newCanvas(); canvas.style.display = "block"; canvas.style.margin = "0 auto";
  document.getElementById("vcheck").appendChild(canvas);
  drawChar(canvas.getContext("2d"), "あ");
  const vc = document.getElementById("vc"), go2 = document.getElementById("go2");
  vc.addEventListener("change", () => { go2.disabled = !vc.checked; go2.style.opacity = vc.checked ? "1" : ".5"; });
  go2.onclick = () => { if (vc.checked) start(); };
}

const T0 = Date.now();   // 所要時間の起点

(async function(){
  try {
    await preload();
    // 本番モード(?prod=1)は同意画面を挟んでから教示へ。研究者パイロットは従来どおり直行。
    if (window.PROD && PROD.enabled) {
      resumeState = PROD.loadState("soa_visual");  // 同じブラウザの途中状態(期限内)を拾う
      if (resumeState && resumeState.completed) {  // 完了済み: 完了コードを再表示するだけ
        screen.innerHTML = PROD.completionHTML(resumeState.duration_s || 0);
        return;
      }
      PROD.consentScreen(screen, "画面に短く表示されたかなを見て、見えた文字を回答する課題", 10, intro, false,
        { noEnvNote: true, desc: "日本語のかな1文字が、短い表示からどの程度認識できるかを調べる研究です" });
    }
    else intro();
  }
  catch(e){ screen.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}<br>このページは experiment/ 内でHTTP配信して開いてください。</p>`; }
})();
