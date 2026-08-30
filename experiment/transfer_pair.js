// =========================================================================
// 見え心地の評価（群C）v c1.2   入口: transfer_comfort.html
//   計画書: project/実験計画書_転写検証.md（3章 RQ3 と 4.5）
//   設定:   experiment/transfer_comfort_config.js（群Cだけの手続き）
//           experiment/transfer_config.js（描画のパラメータと保存先。**読むだけ**）
//
//   ■ 何をする実験か
//   生成した文字アニメーション4方式（フェード・部分表示・ぼかし解除・ワイプ）を、
//   **打ち切らずに繰り返し**流し、「字幕として続けて見ていられるか」を7件法で聞く。
//   かなを当てる課題は一切通らない。
//
//   提示のしかたは3通りある（4方式 × 3提示 = 12本・所要およそ7分）。
//     single … 1字だけ
//     row5   … 5字を左から1字ずつ出し、**出た字はそのまま残す**（字幕的な見せ方）
//     swap5  … 5字を**同じ位置で1字ずつ入れ替える**
//   5字続けるときは「前の字が現れきってから300ミリ秒空けて次が始まる」ようにしてある。
//   前後の字が互いの見え方を邪魔する現象（視覚的マスキング）を避けたうえで、
//   見え心地だけを聞くための間合いである。詳しくは transfer_comfort_config.js の timing。
//
//   ■ もとの実装との関係
//   2026-08-21 まで、この評価は transfer.js の中で群B（検証・視覚）の識別課題が
//   全部終わったあとに続けて行っていた。それを独立の実験に切り出したのがこのファイルである。
//   切り出しにあたって変えたのは次の4点。
//     1. 識別課題を通らない（疲れと印象が混ざらない）
//     2. アニメを1回で止めず、評価しているあいだ繰り返し流す（字幕の実態に近い）
//     3. 5字続ける提示を2通り足した（横に並べて残す／同じ場所で入れ替える）
//     4. 繰り返した周の数と「もう一度みる」を押した回数を別々に数える
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

const VERSION = "p7.7";
const CFG = window.TRANSFER_CONFIG;            // 共用（描画・保存先）。書き換えない。
const C = window.TRANSFER_PAIR_CONFIG;      // 群Cだけの設定
const P = new URLSearchParams(location.search);

// 研究者モード(?prod なし)のときだけ、タブの名前に内部の呼び名を足す。
// 参加者が見るタブ名は入口HTMLの <title> のまま（内容だけを表す名前にしてある）。
if (!(window.PROD && PROD.enabled)) document.title += "［研究者確認：群C］";

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
//
//   保存基盤は transfer_config.js の backend で選ぶ（既定は Firestore）。
//   **Firestore 側は phase="comfort" を知っている**（transfer_config.js の phases と
//   phase_blocks に入れてある）。GAS 側は 2026-08-21 に同じ規則を足したが、
//   反映するにはデプロイし直す必要がある（掲載前チェックリスト H-1）。
//   GAS へ切り戻すつもりがないなら、そのままでよい。
// =========================================================================
const ROSTER = (CFG.roster || {});
const BACKEND = CFG.backend || {};
const FSTORE = window.TRANSFER_FIRESTORE || null;

// ---- 掲載前フラグ（transfer_config.js の pre_launch）------------------------
// **transfer.js と同じ手当て**（片方だけ直さないこと）。true のあいだは、
// 本番モード（?prod=1）で動かしても全レコードに is_test を付け、名簿の連番も
// 本番とは別のカウンタから配る。判定の本体は transfer_firestore.js にある。
function isTestRun() {
  const pid = (window.PROD && PROD.participantId) || "";
  return FSTORE ? FSTORE.isTestRun(pid, PHASE) : (CFG.pre_launch === true);
}

// 掲載前フラグが立っているあいだ、画面の隅に小さく出す帯。
// **false に戻し忘れたまま掲載してしまう事故**を、開いて数秒で気づけるようにする。
function showPreLaunchBadge() {
  if (!(CFG.pre_launch === true)) return;
  console.warn("[pair] 掲載前フラグ pre_launch=true。この回の記録はすべて " +
               "is_test=true で保存され、名簿の連番もテスト用カウンタから配られます。" +
               "掲載申請の直前に transfer_config.js の pre_launch を false にしてください。");
  const el = document.createElement("div");
  el.textContent = "掲載前モード：この記録はテスト扱いです";
  el.setAttribute("style",
    "position:fixed;top:0;right:0;z-index:9999;background:#7a2020;color:#fff;" +
    "font-size:12px;line-height:1.4;padding:4px 10px;border-bottom-left-radius:8px;" +
    "letter-spacing:.02em;opacity:.92;pointer-events:none");
  document.body.appendChild(el);
}

function firestoreReady() { return !!(FSTORE && FSTORE.enabled()); }
function gasRosterReady() { return !!ROSTER.status_url; }
function gasLoggingReady() { return !!(CFG.logging && CFG.logging.submit_url); }

// 「どの順で試すか」の段取り。transfer.js の同名の関数と同じ規則。
// 使えない基盤は最初から外す。fallback が false なら主だけ試す。
function backendPlan(which, ready) {
  const primary = (BACKEND[which] === "gas") ? "gas" : "firestore";
  const order = (BACKEND.fallback === false)
    ? [primary]
    : [primary, primary === "gas" ? "firestore" : "gas"];
  return order
    .filter(b => ready(b))
    .map((b, i) => ({ backend: b, primary: i === 0 && b === primary }));
}

function sourceLabel(step, tries) {
  const base = (step.backend === "gas")
    ? (step.primary ? "server" : "gas-fallback")
    : (step.primary ? "firestore" : "firestore-fallback");
  return tries > 1 ? base + ":retry" + tries : base;
}
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
    "&worker_id=" + encodeURIComponent((window.PROD && PROD.workerId) || "") +
    // 試し打ちの目印（transfer.js と同じ。GAS はこの印の人を本番の人数に数えない）。
    "&is_test=" + (isTestRun() ? "1" : "0");
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

// 名簿の問い合わせ1回ぶん（Firestore 版）。戻り値の形は GAS 版とそろえてある。
// 群Cは集団が1つ（c）なので、決まるのは連番だけ。断る規則（較正・検証に出た人を
// 通さない）は transfer_config.js の phase_blocks に書いてある。
async function rosterQueryOnceFirestore(pid) {
  const r = await FSTORE.resolveAssignment({
    phase: PHASE,
    groups: ((CFG.phases && CFG.phases[PHASE]) || [GROUP]),
    blockers: (CFG.phase_blocks && CFG.phase_blocks[PHASE]) || [],
    pid: pid,
    worker_id: (window.PROD && PROD.workerId) || "",
  });
  if (r.kind === "blocked") return { kind: "blocked", reason: r.reason };
  if (r.kind === "ok") {
    if (r.group !== GROUP) {
      return { kind: "fail", why: "名簿の集団が群C以外だった(" + r.group + ")" };
    }
    return { kind: "ok", j: { group: r.group, assign_index: r.assign_index } };
  }
  return { kind: "fail", why: r.why || "名簿に問い合わせられない" };
}

function rosterQueryOnceVia(backend, pid) {
  return (backend === "firestore") ? rosterQueryOnceFirestore(pid) : rosterQueryOnce(pid);
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
  // 設定した基盤を順に試す（既定では Firestore → だめなら GAS）。
  const plan = backendPlan("roster", b => (b === "firestore") ? firestoreReady() : gasRosterReady());
  if (plan.length) {
    const rc = ROSTER.retry || {};
    const attempts = Math.max(1, Number(rc.attempts) || 1);
    const total = attempts * plan.length;
    let tries = 0;
    rosterLastWhy = "";
    for (const step of plan) {
      for (let i = 0; i < attempts; i++) {
        if (tries > 0) await sleep(backoffMs(rc, i - 1));
        tries++;
        if (tries > 1 && typeof onRosterRetry === "function") onRosterRetry(tries, total);
        const res = await rosterQueryOnceVia(step.backend, pid);
        if (res.kind === "ok") {
          const a = { assign_index: Number(res.j.assign_index) || 0 };
          writeAssignCache(pid, a);
          return Object.assign(a, { source: sourceLabel(step, i + 1) });
        }
        // 断られたのはサーバが答えた結果なので、作り直しても結論は変わらない。
        if (res.kind === "blocked") return { blocked: true, reason: res.reason };
        rosterLastWhy = res.why;
        console.warn(`[pair] 名簿(${step.backend})への問い合わせ ${i + 1}/${attempts} 回目が失敗: ${res.why}`);
      }
    }
    if (C.roster && C.roster.require_server) {
      return { blocked: true, reason: "server_unavailable", why: rosterLastWhy, tries: total };
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
    // 試し打ちの目印。Firestore へ入れるときは transfer_firestore.js が同じ値を
    // 付け直すが、GAS へ回ったときのためにここでも載せておく。
    is_test: isTestRun(),
  }, body);
}

// 1回ぶんの送信。例外は投げず {ok, why} を返す。
// Firestore は応答が読めるので「入ったか」がその場で分かる。GAS は no-cors なので
// 分かるのは「送信そのものが失敗したか」だけ。
function sendOnce(backend, envelope) {
  if (backend === "firestore") {
    return FSTORE.submitRecord(envelope)
      .then(r => (r.kind === "ok") ? { ok: true } : { ok: false, why: r.why });
  }
  const url = (CFG.logging && CFG.logging.submit_url) || "";
  if (!url) return Promise.resolve({ ok: false, why: "GAS の送信先が空" });
  return fetch(url, {
    method: "POST", mode: "no-cors",
    headers: { "Content-Type": "text/plain;charset=utf-8" },
    body: JSON.stringify(envelope),
  }).then(() => ({ ok: true }))
    .catch(e => ({ ok: false, why: (e && e.message) || "送信できない" }));
}

let sendFailures = 0;      // 最後まで送れなかった件数
let sendRetries = 0;       // 作り直して送れた件数

async function deliverRecord(envelope) {
  const plan = backendPlan("logging", b => (b === "firestore") ? firestoreReady() : gasLoggingReady());
  if (!plan.length) {
    console.warn("[pair] 記録の送信先が1つも設定されていないので記録が残りません");
    sendFailures++;
    return false;
  }
  const rc = (CFG.logging && CFG.logging.retry) || {};
  const attempts = Math.max(1, Number(rc.attempts) || 1);
  let tries = 0;
  for (const step of plan) {
    for (let i = 0; i < attempts; i++) {
      if (tries > 0) await sleep(backoffMs(rc, i - 1));
      tries++;
      const r = await sendOnce(step.backend, envelope);
      if (r.ok) {
        if (tries > 1) { sendRetries++; console.warn(`[pair] 記録の送信は ${tries} 回目(${step.backend})で通りました`); }
        if (BACKEND.dual_write_logging) {
          const other = (step.backend === "firestore") ? "gas" : "firestore";
          const ready = (other === "firestore") ? firestoreReady() : gasLoggingReady();
          if (ready) sendOnce(other, envelope).catch(() => {});
        }
        return true;
      }
      console.warn(`[pair] 記録の送信(${step.backend}) ${i + 1}/${attempts} 回目が失敗: ${r.why}`);
    }
  }
  sendFailures++;
  console.error(`[pair] 記録を ${tries} 回試して送れませんでした`);
  return false;
}

// 1レコードを送る。**戻り値は「入ったか」の Promise<boolean>**。
// 群Cは1参加者あたりの本記録が1件しかないので、**この1件が落ちると完了コードが
// サーバのどこにも残らず、承認の照合ができなくなる**。だから submitAndFinish() は
// 必ずこの戻り値を待って、成否を見てから完了コードを出す。
function sendRecord(body) {
  if (!(window.PROD && PROD.enabled)) return Promise.resolve(true);
  return deliverRecord(serverBody(body));
}

// ---- 途中の保険（1本ごとの中間レコード） ------------------------------------
// 7件法に答えるたびに、その1本ぶんだけを1行として送っておく。
// 群Cは最後の1件にすべてが入る作りなので、そこが落ちると全損になる。
// 中間レコードがあれば、少なくとも「誰がどこまで答えたか」と完了コードは残る。
// **分析には使わない**（final の1行が正）。record_kind 列で見分ける。
//   record_kind = "clip"    … 1本ぶんの中間レコード（12行／人）
//   record_kind = "final"   … 従来どおりの1参加者1行（これが分析用）
//   record_kind = "session" … 完走レコード（承認の判定用）
function sendClipRecord(clip) {
  const rec = {
    kind: "transfer_wellbeing",
    record_kind: "clip",
    stimulus_id: "comfort|" + GROUP + "|" + clip.family + "|" + clip.condition + "|" + clip.char,
    target_char: "-", response_char: "-",
    modality: (C.logging && C.logging.modality) || "transfer_wellbeing",
    q_set: "transfer", phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    n_choices: C.families.length * C.conditions.length,
    wellbeing_json: JSON.stringify(clip),
    choice: clip.family + "|" + clip.condition,
    version: VERSION, config_version: C.config_version,
  };
  // 待たない。画面を止めてまで確かめる価値は無い（本命は最後の1行）。
  sendRecord(rec).catch(() => {});
}

// ---- 完走レコード（1セッション1行・承認の判定用） ---------------------------
function sessionRecord(durS) {
  return {
    kind: "transfer_wellbeing",
    record_kind: "session",
    modality: "transfer_session",
    phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    n_trials: (answers && answers.trials) ? answers.trials.length : 0,
    duration_s: durS,
    send_failures: sendFailures,
    send_retries: sendRetries,
    version: VERSION, config_version: C.config_version,
  };
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
// ⚠ 中身は transfer.js の blurApplyFilter() と**1文字も違えないこと**。
//   群Bと群Cで違う絵を出すと、両者の比較そのものが成り立たなくなる。
//   check_comfort_render.js が blurDraw() の中身を transfer.js と突き合わせている。
function blurApplyFilter(ctx, src, s) {
  const r = CFG.visual.families.blur.max_radius_px * (1 - Math.max(0, Math.min(1, s)));
  drawBlank(ctx);
  ctx.save();
  ctx.filter = r > 0.01 ? `blur(${r.toFixed(2)}px)` : "none";
  ctx.drawImage(src, 0, 0, SIZE, SIZE);
  ctx.restore();
  ctx.filter = "none";
}
// ---- ぼかし済みの絵（ctx.filter が効かない端末むけ）--------------------------
// あらかじめ PNG にしておいたぼかし画像から、いちばん近い半径の1枚を選んで描く。
// experiment/tools/build_blur_frames.py が作り、tools/blur_compare.html で
// ctx.filter の出す絵と画素ごとに突き合わせてある（2026-08-29・Chrome で実測）:
//   字が読める側（半径36px以下）… 平均のずれ 1.04 以下 ／ 256階調
//   真っ白に近い側（半径72px）  … 平均のずれ 3.24（その絵自体の濃淡の幅は31）
//   段のとなりどうしの違い      … 平均 0.17〜2.14（いちばん近い段を選ぶ誤差はその半分）
//
// ⚠ 上の「見た目を別の作りで再現しない」に**反しない**。
//   CSS の filter で代用するとにじみ方が変わるので不可だが、こちらは
//   canvas と同じ画素を出すことを実測で確かめたうえで差し替えている。
//   blur(N px) は**標準偏差 N** のガウスぼかしである（半分ではない。
//   box-shadow のぼかし幅が 2σ なので混同しやすい）。
//
// 使うのは「ctx.filter が効かない」かつ「その回に出す字がすべて索引にある」ときだけ。
// 1字でも欠けたら使わない（欠けた字だけ鮮明に出る事故を防ぐ）。
const blurFrames = { ready: false, radii: null, byChar: null };

// 半径 r にいちばん近い段の番号。radii は昇順。
function blurFrameIndex(r) {
  const R = blurFrames.radii;
  let lo = 0, hi = R.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (R[m] < r) lo = m + 1; else hi = m; }
  if (lo > 0 && Math.abs(R[lo - 1] - r) <= Math.abs(R[lo] - r)) lo--;
  return lo;
}

function blurDrawFromFrames(ctx, ch, s) {
  const r = CFG.visual.families.blur.max_radius_px * (1 - Math.max(0, Math.min(1, s)));
  const set = blurFrames.byChar[ch];
  drawBlank(ctx);
  if (set) ctx.drawImage(set[blurFrameIndex(r)], 0, 0, SIZE, SIZE);
}

// 読めたら true。呼ぶのは各ページの preload() から（出す字の一覧を渡す）。
async function blurFramesLoad(chars) {
  if (canvasFilterWorks()) return false;              // 効く端末は今までどおり
  const url = (CFG.visual.families.blur || {}).frames_url;
  if (!url) return false;
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) return false;
    const man = await r.json();
    const need = [...new Set(chars)];
    if (!need.every(ch => (man.chars || []).indexOf(ch) >= 0)) return false;
    const dir = url.replace(/[^/]*$/, "");
    const byChar = {};
    for (const ch of need) {
      byChar[ch] = await Promise.all((man.radii || []).map((_, i) => new Promise((res, rej) => {
        const im = new Image();
        im.onload = () => res(im);
        im.onerror = () => rej(new Error("ぼかし画像が読めない: " + ch + " " + i));
        im.src = dir + encodeURIComponent(ch) + "/" + String(i).padStart(3, "0") + ".png";
      })));
    }
    blurFrames.radii = man.radii; blurFrames.byChar = byChar; blurFrames.ready = true;
    return true;
  } catch (e) {
    console.warn("[blur] ぼかし済みの絵を使えません: " + e.message);
    return false;
  }
}

function blurDraw(ctx, ch, s) {
  if (blurFrames.ready) { blurDrawFromFrames(ctx, ch, s); return; }
  if (!blurOff) blurBegin(ch);
  blurApplyFilter(ctx, blurOff, s);
}

// ワイプ(wipe): 見せる領域を端から単調に広げる。向きは設定で変えられる。
//
// 進み具合 s は「画面の端(0)から端(SIZE)まで」ではなく、**字のインクが実際にある
// 範囲(bbox)の中だけ**で動かす。そのままだと、字によっては書き出しの位置が
// 画像の端から離れている(左右・上下に余白がある)ため、s の前半ぶんが余白を
// なぞるだけの「何も起きない区間」になってしまう(丸山・2026-08-22の下見で発覚)。
// bbox の外側は s によらずつねに欠けたまま/つねに映ったままなので、
// s=0 でちょうど「インクが何も見えない」、s=1 でちょうど「インクが全部見える」に
// そろう。字ごとに余白の量が違う(字形しだい)ので、そろえないと同じ s でも
// 字によって実質の情報量が変わってしまう(較正データの字間比較を歪める)。
const wipeBBox = {};   // かな → {xMin, xMax, yMin, yMax}(xMax/yMaxは「最後のインク列/行+1」)
function wipeInkThreshold() {
  const w = CFG.visual.families.wipe;
  return (w && typeof w.ink_threshold === "number") ? w.ink_threshold
    : CFG.visual.families.reveal.ink_threshold;
}
function wipeBBoxPrepare(ch) {
  if (wipeBBox[ch]) return wipeBBox[ch];
  const off = document.createElement("canvas"); off.width = SIZE; off.height = SIZE;
  const octx = off.getContext("2d", { willReadFrequently: true });
  octx.fillStyle = "#fff"; octx.fillRect(0, 0, SIZE, SIZE);
  if (imgs[ch]) octx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
  const px = octx.getImageData(0, 0, SIZE, SIZE).data;
  const th = wipeInkThreshold();
  let xMin = SIZE, xMax = 0, yMin = SIZE, yMax = 0, found = false;
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      const i = y * SIZE + x;
      const lum = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2];
      if (lum <= th) {
        found = true;
        if (x < xMin) xMin = x; if (x + 1 > xMax) xMax = x + 1;
        if (y < yMin) yMin = y; if (y + 1 > yMax) yMax = y + 1;
      }
    }
  }
  // インク画素が1つも無い(白紙の画像など)ときは、bboxを使わず元の挙動(0..SIZE)に落とす。
  const bbox = found ? { xMin, xMax, yMin, yMax } : { xMin: 0, xMax: SIZE, yMin: 0, yMax: SIZE };
  wipeBBox[ch] = bbox;
  return bbox;
}
function wipeBegin(ch) { wipeBBoxPrepare(ch); }
// ⚠ 中身は transfer.js の wipeClipRect()／wipeApplyClip() と**1文字も違えないこと**。
//   check_comfort_render.js が wipeDraw() の中身を transfer.js と突き合わせている。
//   dirArg は群Bの向き反転実験（wipedir）で使う引数。群Cは渡さないので、
//   設定の direction（既定 ltr）に落ちる＝従来と同じ絵になる。
function wipeClipRect(ch, s, dirArg) {
  const p = Math.max(0, Math.min(1, s));
  const dir = dirArg || CFG.visual.families.wipe.direction || "ltr";
  const b = wipeBBoxPrepare(ch);
  let rx = 0, ry = 0, rw = 0, rh = SIZE;
  // 端から広げる向きによって、bboxのどちら側から growing edge が伸びるかが逆になる。
  // ltr/ttb は0側(左/上)を固定してインク側の遠い端へ伸ばす → w/hはxMin→xMaxで増える。
  // rtl/btt はSIZE側(右/下)を固定してインク側の遠い端へ伸ばす → w/hは(SIZE-xMax)→(SIZE-xMin)で増える。
  if (dir === "ltr" || dir === "rtl") {
    const w = (dir === "ltr")
      ? b.xMin + (b.xMax - b.xMin) * p        // 0:xMin(何も新しく見えない) → 1:xMax(インク全部)
      : (SIZE - b.xMax) + (b.xMax - b.xMin) * p;
    rw = w; rh = SIZE;
    rx = (dir === "ltr") ? 0 : SIZE - w;
    ry = 0;
  } else {
    const h = (dir === "ttb")
      ? b.yMin + (b.yMax - b.yMin) * p
      : (SIZE - b.yMax) + (b.yMax - b.yMin) * p;
    rw = SIZE; rh = h;
    rx = 0;
    ry = (dir === "ttb") ? 0 : SIZE - h;
  }
  return { rx, ry, rw, rh };
}
function wipeApplyClip(ctx, src, ch, s, dirArg) {
  drawBlank(ctx);
  if (!src) return;
  const { rx, ry, rw, rh } = wipeClipRect(ch, s, dirArg);
  if (rw <= 0 || rh <= 0) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(rx, ry, rw, rh);
  ctx.clip();
  ctx.drawImage(src, 0, 0, SIZE, SIZE);
  ctx.restore();
}
function wipeDraw(ctx, ch, s, dirArg) {
  wipeApplyClip(ctx, imgs[ch], ch, s, dirArg);
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
  wipe:   { begin: (ch) => wipeBegin(ch),        draw: wipeDraw },
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

// 方式名 → 実際に絵を描く描画器。ステップ表示("step")は独立した描画器を持たず、
// フェードの描画器に進み具合0か1を渡すだけである。対応は設定の family_renderer にある。
// （RENDERERS の表そのものは transfer.js と1文字も違ってはいけないので触らない。
//   experiment/tools/check_comfort_render.js が突き合わせている。）
function rendererFor(family) {
  const map = C.family_renderer || {};
  return RENDERERS[map[family] || family] || RENDERERS.fade;
}

// ステップ表示の切り替え時刻ms(字ごと)。生成工程が出した表にあればそれを使い、
// 無ければ設定の代用値(全字共通)を使う。表から取れたかどうかは記録の
// progress_source に残る("step" か "step_fallback")。
function stepMidMs(ch) {
  const m = warpTables && warpTables.step_mid_ms;
  const v = m && m[ch];
  return (typeof v === "number" && isFinite(v) && v >= 0)
    ? { ms: v, fromTable: true }
    : { ms: Number(CFG.visual.warp.fallback_step_mid_ms) || 0, fromTable: false };
}

// 1本ぶんの「経過時間ms → 進み具合 s」と、その1本の長さ(ms)を作る。
// 返り値: {fn, dur_ms, source}  source は記録用("table" / "linear" / "step" / "step_fallback")。
function progressFor(family, ch, condition) {
  const base = CFG.visual.base_anim_ms;
  // ステップ表示。中点までは何も出さず、そこで一気に完成形にする。
  // 1本の長さは他の方式とそろえる(同じ間合いで流れないと見え心地を比べられない)。
  if (family === "step") {
    const mid = stepMidMs(ch);
    return {
      fn: (ms) => (ms < mid.ms ? 0 : 1),
      dur_ms: Math.max(base, Math.ceil(mid.ms)),
      source: mid.fromTable ? "step" : "step_fallback",
    };
  }
  const cond = C.force_condition || condition;
  if (cond && cond !== "linear") {
    const series = warpSeries(family, ch, cond);
    if (series) {
      const frameMs = (warpTables && warpTables.frame_ms) || (1000 / 60);
      // ---- 終端に達したらアニメを終える（2026-08-29）--------------------------
      // 音声は60〜125msで終わるので、①②は表の前半で終端値に達し、残りは
      // 同じ絵が並ぶだけになる。そこで**値が最後に動いたコマまで**をアニメの
      // 長さとし、以後は再生器の「完成形のまま据え置く時間」（hold_ms）に譲る。
      // こうすると据え置きの長さが4条件で同じ1200msにそろう
      // （表のままだと①②だけ枠の余り175〜240msぶん完成形を余分に見る）。
      // 絵のコマは1枚も変わらない。変わるのは1周の長さだけである。
      const last = series[series.length - 1];
      let nEff = series.length;
      while (nEff > 1 && series[nEff - 2] >= last - 1e-9) nEff--;
      return {
        fn: (ms) => Math.max(0, Math.min(1, seriesAt(series, frameMs, ms))),
        dur_ms: Math.round((nEff - 1) * frameMs),
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

// この人に割り当てる字。16本すべてがこの1字になる。
// 人ごとに配ることで、400人で8字を50人ずつ覆う（設定 char_rotation）。
// 1人の中では字が変わらないので、条件どうし・方式どうしの比較は同じ人の中で成立する。



// ---- transfer_comfort.js から流用したユーティリティ ----
let stopPlayback = null;
let elapsedPrior = 0;
let _canvasFilterOK = null;

function stopAnim() { if (stopPlayback) { stopPlayback(); stopPlayback = null; } }

function saveProgress() {
  if (window.PROD && PROD.enabled) PROD.saveState("transfer_" + PHASE, {
    session_v: SESSION_V, phase: PHASE, group: GROUP,
    clips, idx, answers, assign: ASSIGN,
    elapsed_s: Math.round(elapsedPrior + (Date.now() - T0) / 1000),
  });
}

function saveDoneState(durS, pending) {
  if (window.PROD && PROD.enabled) {
    PROD.saveState("transfer_" + PHASE,
      { completed: true, duration_s: durS, pending_rec: pending || null });
  }
}

async function finishUp(durS) {
  saveDoneState(durS, null);
  await sendRecord(sessionRecord(durS)).catch(() => false);
  screenEl.innerHTML = finishHTML(durS);
}

function showSending() {
  screenEl.innerHTML = `<div style="min-height:40vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">回答を送っています…</h1>
    <p class="muted">この画面のままお待ちください。閉じないでください。</p></div>`;
}

function showSendFailure(rec, durS, tries) {
  const c = CFG.contact || {};
  const viaCs = c.via_crowdsourcing ? "、または応募元の募集サイトのメッセージ機能" : "";
  // 1回も手で再送していないうちは、コードを出さずに再送だけを勧める。
  // 手の再送も失敗したら、参加者を手ぶらで帰らせないためにコードを出す。
  const giveUp = tries >= 1;
  screenEl.innerHTML = `<h1>回答の送信に失敗しました</h1>
    <p>通信の一時的な不調のことが多いので、<b>下のボタンでもう一度送ってください</b>。
    このページを閉じると、回答が記録に残りません。</p>
    <p style="text-align:center;margin-top:16px">
      <button class="primary" id="resend">回答を送りなおす</button></p>
    <p class="muted" id="resendNote" style="text-align:center"></p>
    ${giveUp ? `
    <div style="margin-top:18px;background:#fff7ed;border:1px solid #f0c98a;border-radius:8px;padding:14px 14px">
      <p style="margin-top:0">何度試しても送れないため、<b>完了コード</b>をここに出します。
      <b>このコードと、いまの日付・時刻をお手元に控えて</b>、募集の回答欄で選んで提出してください。</p>
      <p style="font-size:26px;font-weight:800;letter-spacing:3px;color:#1E2A5E;text-align:center;
                background:#f2f5f8;border:1px solid #dde3ec;border-radius:10px;padding:12px 8px;margin:12px auto;max-width:340px">
        ${(window.PROD && PROD.sharedCode) || ""}</p>
      <p style="margin-bottom:0">記録側にこのコードが残っていない可能性があります。
      承認されない場合は、<b>控えたコードと日時</b>を添えて
      ${mailLink(c.email)}${viaCs}までご連絡ください。
      確認のうえ対応します（${c.pi || "【要確認：研究責任者】"}）。</p>
    </div>` : ""}
`;   // 2026-08-25 丸山決定: 所属（大学名・研究室名）は画面に出さない。「実施：」の行を削除した。
  const btn = document.getElementById("resend");
  const note = document.getElementById("resendNote");
  btn.onclick = async () => {
    btn.disabled = true; btn.style.opacity = ".5";
    note.textContent = "送っています…";
    const ok = await sendRecord(rec);
    if (ok) { await finishUp(durS); return; }
    showSendFailure(rec, durS, tries + 1);
  };
}

function finishHTML(durS) {
  // ■ 完了コードは全員共通の3桁（prod_common.js の SHARED_CODE。2026-08-30 に 275 へ変更）。
  //   募集サイトの設問がセレクトボックス3つ（自由記述はチェック設問の自動照合に
  //   使えないため）に変わったので、案内の文言も「コピーして貼り付け」から
  //   「順番に選ぶ」に直してある。個人別コード codeFromWid() は記録に残すだけで
  //   **参加者には見せない**（hideCode: true）。
  if (window.PROD && PROD.enabled) return PROD.completionHTML(durS, { hideMeta: true, hintTable: true, hideCode: true, codeNote: `<p>下の<b>完了コード</b>を、<b>このページを開いたタスクの画面に戻り</b>、<br>選択欄で順番に選んで提出してください。</p><p style="font-size:14px;color:#8a4a00;background:#fff7ec;border:1px solid #f0dcc0;border-radius:8px;padding:8px 12px;max-width:360px;margin:10px auto"><b>入力画面は2回あります。</b><br>どちらにも同じ完了コードを選んでください。</p><p class="muted" style="font-size:13px">提出するまで、報酬のお支払い手続きが始まりません。</p>` });
  return `<div style="text-align:center;padding:24px 10px">
    <h1>動作確認が終わりました</h1>
    <p class="muted">研究者向け動作確認モード（URL に <code>?prod=1</code> が無い）です。</p>
    <p><b>完了コードは出ません。</b>このモードでは記録を送らないので、
    コードを出しても記録側に残らず、照合できないためです。</p>
    <p class="muted">v${VERSION} ／ ${PHASE}フェーズ 集団 ${GROUP} ／
    答えた本数 ${(answers && answers.trials) ? answers.trials.length : 0} 本 ／ 所要 ${durS} 秒 ／
    送信できなかった記録 ${sendFailures} 件・作り直して送れた記録 ${sendRetries} 件</p></div>`;
}

function canvasFilterWorks() {
  if (P.get("nofilter") === "1") return false;      // 研究者の動作確認用
  if (_canvasFilterOK !== null) return _canvasFilterOK;
  try {
    const c = document.createElement("canvas");
    c.width = c.height = 32;
    const x = c.getContext("2d");
    x.fillStyle = "#fff"; x.fillRect(0, 0, 32, 32);
    x.filter = "blur(4px)";
    x.fillStyle = "#000"; x.fillRect(12, 12, 8, 8);   // 中央に 8×8 の黒い四角
    x.filter = "none";
    // ⚠ **四角の中央**を見る（1画素だと、効いていても真っ白と区別が付かない）。
    _canvasFilterOK = x.getImageData(16, 16, 1, 1).data[0] > 40;
  } catch (e) {
    _canvasFilterOK = false;
  }
  return _canvasFilterOK;
}

function usesBlurFamily() {
  return (C.families || []).some(f => String(f || "").indexOf("blur") >= 0);
}

function unsupportedDeviceScreen() {
  screenEl.innerHTML = `
    <p>ご参加いただきありがとうございます。</p>
    <p>申し訳ございません。<b>お使いの端末では、この課題の画面を正しく表示できないことが分かりました。</b>
    ご利用の環境に問題があるわけではなく、こちらの課題の作りによるものです。</p>
    <p>お手数ですが、<b>この作業は辞退して</b>ページを閉じてください。
    別の端末（パソコン、または Android のスマートフォン）をお持ちでしたら、
    そちらから改めてお試しいただけます。</p>
    <p class="muted" style="font-size:13px">ご迷惑をおかけして申し訳ありません。</p>
    ${(window.PROD && PROD.enabled) ? "" :
      `<p class="muted" style="font-size:12px;text-align:right">研究者向け: canvas の filter が効かない端末
       （ぼかしが描けない）。v${VERSION}</p>`}`;
}

function mailLink(addr) {
  const a = String(addr || "").trim();
  if (!a || a.indexOf("@") < 0) return a || "【要確認：メールアドレス】";
  return `<a href="mailto:${a}">${a}</a>`;
}

function tidyConsentScreen() {
  const h1 = screenEl.querySelector("h1");
  if (h1 && h1.textContent.indexOf("ご協力") >= 0) h1.remove();
  // prod_common.js が書いた説明の箇条書きは**まるごと消す**（募集ページが本体）。
  const ul = screenEl.querySelector("ul");
  if (ul) ul.remove();
  // リード文（「本実験は、〜を調べる研究です。」）の直後に、残す1行だけを足す。
  //
  // ⚠ **問い合わせ先は 2026-08-25 に外した**（丸山判断。「募集サイトに書いてあれば十分」）。
  //   募集サイトのタスク説明文に、研究責任者・宛先・取り消しの案内を書いてある。
  //   ⚠ 外部サイトに移ったあとで困った人（音が出ない・送信が失敗した等）は、
  //     募集サイトの画面に戻らないと宛先が分からない。承知のうえでの判断である。
  //     戻せるように mailLink() と CFG.contact はそのまま残してある。
  const add = document.createElement("p");
  add.innerHTML = "募集ページに記載した内容にご同意のうえ、開始してください。";
  const lead = screenEl.querySelector("p");
  if (lead) lead.insertAdjacentElement("afterend", add);
  else screenEl.insertBefore(add, screenEl.firstChild);
  // 1画面に収めるための入れ物。**要素は移すだけにすること**——作り直すと
  // ボタンと機器のラジオのリスナーが消えて、押しても何も起きなくなる。
  const box = document.createElement("div");
  box.className = "consent-min";
  while (screenEl.firstChild) box.appendChild(screenEl.firstChild);
  screenEl.appendChild(box);
}

function blockedScreen(reason, info) {
  const already = (reason === "already_participated" || reason === "already_in_calib" ||
                   reason === "already_in_test" || reason === "already_in_other_phase");
  const canRetry = !already;
  // 重複参加のときは**見出しを出さない**。「ご参加いただけません」と大きく出すより、
  // 感謝から始めたほうが、弾かれた人が不快になりにくい（2026-08-24 ユーザー判断）。
  // 接続できなかっただけのときは、これまでどおり見出しを出す。
  screenEl.innerHTML = `${already ? "" : "<h1>接続できませんでした</h1>"}
    ${already ? `
    <p>ご参加いただきありがとうございます。</p>
    <p>確認したところ、以前の関連実験にご参加いただいていたため、今回は対象外となります。</p>
    <p>恐れ入りますが、このままページを閉じていただけますと幸いです。<br>
    以前の実験の報酬には影響ございません。</p>`
    : `<p>ただいまサーバに接続できませんでした。通信の一時的な不調のことが多いので、
    <b>下のボタンでもう一度お試しください</b>。</p>
    <p>何度試しても同じ場合は、お手数ですがこの作業は辞退してページを閉じてください。
    しばらく経ってから、改めて掲載をご確認いただけますと幸いです。</p>
    <p style="text-align:center;margin-top:18px">
      <button class="primary" id="retryBtn">もう一度試す</button></p>
    <p class="muted" id="retryNote" style="text-align:center"></p>`}
`;   // 2026-08-25 丸山決定: 所属（大学名・研究室名）は画面に出さない。「実施：」の行を削除した。
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

// =========================================================================
// ここから下がペア比較（第2版）の本体。上の土台（名簿・記録・描画器・表の読み込みの
// 部品）は transfer_comfort.js から流用している。
// =========================================================================

// ---- 字の配り方: 8字から連続する4字 ----------------------------------------
let CHARS4 = null;   // 名前は歴史的経緯。中身は全員共通の8字（30j から）。
function charsForParticipant() {
  return C.chars.slice();
}
function neededChars() {
  if (!CHARS4) CHARS4 = charsForParticipant();
  return CHARS4.slice();
}

// ---- 進み方の列（出し方は引数で指定・終端補正つき）--------------------------
function seriesFor(family, ch, endcap, condition) {
  const s = warpSeries(family, ch, condition);
  if (!s) return null;
  const frameMs = (warpTables && warpTables.frame_ms) || (1000 / 60);
  let arr = s.slice();
  // 値が動かなくなった尾を落とす（較正・検証の打ち切り規則と同じ）
  const last = arr[arr.length - 1];
  let n = arr.length;
  while (n > 1 && arr[n - 2] >= last - 1e-9) n--;
  arr = arr.slice(0, n);
  if (endcap && last < 0.999) {
    // 終端補正: 音声終了後 ramp_ms で完成形（進み具合1.0）へ遷移させる。
    // 音声が鳴っている区間の対応は生成のまま、終了後だけを足す。
    const add = Math.max(1, Math.round(C.endcap.ramp_ms / frameMs));
    for (let k = 1; k <= add; k++) arr.push(last + (1.0 - last) * (k / add));
  }
  return { arr, frameMs, dur_ms: (arr.length - 1) * frameMs };
}

// （音声は 2026-08-30 に廃止。質問が「動きの自然さ・好ましさ」だけになり、
//   音声に触れなくなったため。転写の進み方の表は音声の識別実測から来ており、
//   それは warp_tables に焼き込まれている。音声チェックも同時に廃止。）

// ---- 読み込み ---------------------------------------------------------------
async function preload() {
  screenEl.innerHTML = '<div style="min-height:60vh;display:flex;flex-direction:column;justify-content:center;align-items:center"><h1 style="border:none">読み込み中…</h1><div style="width:min(320px,80%);height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden;margin-top:10px"><div id="loadBar" style="height:100%;width:0%;background:#2E7D8F"></div></div></div>';
  const setBar = (p) => { const b = document.getElementById("loadBar"); if (b) b.style.width = Math.round(p * 100) + "%"; };
  const need = neededChars();
  let done = 0, total = need.length + 1;
  for (const ch of need) {
    imgs[ch] = await loadImage(ch); done++; setBar(done / total);
  }
  await blurFramesLoad(need);
  const r = await fetch(C.warp_tables_url, { cache: "no-store" });
  if (!r.ok) throw new Error(C.warp_tables_url + " が読めません");
  warpTables = await r.json();
  setBar(1);
}

// ---- 試行の組み立て ---------------------------------------------------------
// ペア種48通り = 方式だけ違う(同じ出し方) 6×4 + 出し方だけ違う(同じ方式) 6×4。
// 全員共通の固定順（種 "pairtypes-v1" で混ぜ、方式違いと出し方違いを交互に
// 並べる）から、割付番号を頭にした連続24種を取る。交互なので、どこから
// 取っても方式違い12・出し方違い12になる。
// 字は8字を3回ずつ（順は人ごとに無作為）。左右は (割付番号÷2 + 通し番号) の
// 偶奇で入れ替える。割付番号そのもの＋通し番号だと、窓の開始位置と通し番号が
// 連動して同じペア種が全員同じ向きになる（2026-08-30 の検算で発覚）。
function pairTypes() {
  const F = C.families, K = C.conditions;
  const fam = [], cond = [];
  for (let i = 0; i < F.length; i++)
    for (let j = i + 1; j < F.length; j++)
      K.forEach(c => fam.push({ vary: "family", lf: F[i], lc: c, rf: F[j], rc: c }));
  for (let i = 0; i < K.length; i++)
    for (let j = i + 1; j < K.length; j++)
      F.forEach(f => cond.push({ vary: "condition", lf: f, lc: K[i], rf: f, rc: K[j] }));
  const rnd = mulberry32(hashSeed("pairtypes-v1"));
  const mix = (a) => {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  };
  mix(fam); mix(cond);
  const out = [];
  for (let i = 0; i < fam.length; i++) { out.push(fam[i]); out.push(cond[i]); }
  return out;
}

function buildTrials() {
  const types = pairTypes();
  const start = Math.abs(ASSIGN) % types.length;
  const chars = [];
  C.chars.forEach(ch => chars.push(ch, ch, ch));
  shuffle(chars);
  const main = [];
  for (let k = 0; k < 24; k++) {
    const t = types[(start + k) % types.length];
    const flip = ((Math.abs(ASSIGN) >> 1) + k) % 2 === 1;
    main.push({ kind: "pair", vary: t.vary, ch: chars[k],
                left: flip ? t.rf : t.lf, leftCond: flip ? t.rc : t.lc,
                right: flip ? t.lf : t.rf, rightCond: flip ? t.lc : t.rc,
                leftCap: false, rightCap: false });
  }
  shuffle(main);
  return main.map((t, i) => Object.assign(t, { order: i + 1 }));
}

// ---- ペアの再生器 -----------------------------------------------------------
// 2つのキャンバスを同じ周期で回す。周の頭で両方のアニメを同時に始める。
function makePairPlayer(ctxL, ctxR, trial) {
  const sl = seriesFor(trial.left, trial.ch, trial.leftCap, trial.leftCond);
  const sr = seriesFor(trial.right, trial.ch, trial.rightCap, trial.rightCond);
  // 各側の見せ方は較正・検証と同じ: 変化が終わったコマを endpoint_hold_ms
  // （34ms・較正/生成/検証と共通の値）だけ見せて、その側だけ消す。
  // 左右は自分の時刻で消えるので、消えるタイミングは一般にずれる（設計どおり）。
  // 研究者モードでは URL で間隔を試せる（例 ?gap=1500）。本番では設定値のみ。
  const tweak = (name, v) => {
    if (window.PROD && PROD.enabled) return v;
    const x = Number(P.get(name)); return Number.isFinite(x) && P.get(name) !== null ? x : v;
  };
  const holdMs = tweak("hold", (CFG.visual && CFG.visual.endpoint_hold_ms) || 34);
  const gapMs = tweak("gap", C.timing.gap_ms || 0);
  const offL = sl.dur_ms + holdMs, offR = sr.dur_ms + holdMs;
  const cycle = Math.max(offL, offR) + gapMs;
  const rL = rendererFor(trial.left), rR = rendererFor(trial.right);
  let raf = null, stopped = false, t0 = null, lastCycle = -1, cycles = 0;

  function at(sd, ms) {
    const x = ms / sd.frameMs, i = Math.floor(x);
    if (i >= sd.arr.length - 1) return sd.arr[sd.arr.length - 1];
    const f = x - i;
    return sd.arr[i] * (1 - f) + sd.arr[i + 1] * f;
  }
  function frame(now) {
    if (stopped) return;
    if (t0 === null) t0 = now;
    const el = now - t0, c = Math.floor(el / cycle);
    if (c !== lastCycle) {
      lastCycle = c; cycles = c + 1;
      drawBlank(ctxL); drawBlank(ctxR);
      rL.begin(trial.ch, ctxL); rR.begin(trial.ch, ctxR);
    }
    const inC = el - c * cycle;
    if (inC < offL) rL.draw(ctxL, trial.ch, at(sl, inC)); else drawBlank(ctxL);
    if (inC < offR) rR.draw(ctxR, trial.ch, at(sr, inC)); else drawBlank(ctxR);
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);
  return {
    stop() { stopped = true; if (raf) cancelAnimationFrame(raf); },
    restart() { t0 = null; lastCycle = -1; },
    cycles: () => cycles,
  };
}

// ---- 記録（ペア版の中身に差し替え）------------------------------------------
function sendClipRecord(row) {
  const rec = {
    kind: "transfer_wellbeing", record_kind: "clip",
    stimulus_id: "pair|" + GROUP + "|" + row.vary + "|" + row.left + "." + row.leftCond + "|" + row.right + "." + row.rightCond + "|" + row.ch,
    target_char: row.ch, response_char: "-",
    modality: (C.logging && C.logging.modality) || "transfer_wellbeing",
    q_set: "transfer", phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    n_choices: 3,
    wellbeing_json: JSON.stringify(row),
    choice: row.choice || "",
    version: VERSION, config_version: C.config_version,
  };
  sendRecord(rec).catch(() => {});
}

// ---- 画面 -------------------------------------------------------------------
let trials = [], tIdx = 0, answers = null;

function saveProgress() {
  if (window.PROD && PROD.enabled) {
    PROD.saveState("transfer_pair", { session_v: 2, trials, idx: tIdx, answers,
                                      elapsed_s: elapsedPrior, saved_at: Date.now() });
  }
}

// 音の確認: 数字の読み上げを1問。ヘッドホン・音量の確認を兼ねる。
function visionCheckPair() {
  if (CFG.visual.require_canvas_filter !== false && !canvasFilterWorks() && !blurFrames.ready) {
    unsupportedDeviceScreen(); return;
  }
  screenEl.innerHTML = '<h2 style="color:#1E2A5E">見え方の確認</h2>' +
    '<p>本番と<b>同じ大きさ</b>で見本を表示しています。ふだん画面を見る距離のまま、<b>字がはっきり見えること</b>を確認してください。</p>' +
    '<div id="vbox" style="display:flex;justify-content:center"></div>' +
    '<p style="text-align:center;margin-top:16px"><button class="primary" id="go">次へ進む</button></p>';
  const cv = document.createElement("canvas"); cv.width = SIZE; cv.height = SIZE;
  cv.style.cssText = "width:" + C.layout.pair_char_px + "px;height:" + C.layout.pair_char_px + "px;border:1px solid #ddd;border-radius:4px;background:#fff";
  document.getElementById("vbox").appendChild(cv);
  const ctx = cv.getContext("2d");
  drawBlank(ctx); if (imgs[CHARS4[0]]) ctx.drawImage(imgs[CHARS4[0]], 0, 0, SIZE, SIZE);
  document.getElementById("go").onclick = () => intro();
}

function intro() {
  screenEl.innerHTML = '<h1>進め方</h1>' +
    '<p>1つの字が現れる<b>2種類のアニメーション（A・B）</b>を、並べてお見せします。全部で <b>' + trials.length + ' 回</b>です。</p>' +
    '<ul style="font-size:14px;line-height:1.9;color:#333">' +
    '<li>アニメーションは<b>くりかえし流れます</b>。回答中は、何度でも見比べられます。</li>' +
    '<li>1回ごとに、<b>2つの観点（動きの自然さ・好ましさ）</b>について、AかBのどちらかを選びます。</li>' +
    '<li>迷った場合も、<b>より近いと感じる方を選んでください</b>。</li>' +
    '</ul>' +
    '<p style="text-align:center;margin-top:18px"><button class="primary" id="go">始める</button></p>' +
    '<p class="muted" style="text-align:right;font-size:12px;margin-top:6px">' +
    ((window.PROD && PROD.enabled) ? "" : ("研究者向け動作確認 v" + VERSION + " ／ 字 " + CHARS4.join("") + " ／ 割付 " + ASSIGN)) + '</p>';
  document.getElementById("go").onclick = () => showTrial();
}

function showTrial() {
  stopAnim();
  if (tIdx >= trials.length) return finishSession();
  const tr = trials[tIdx];
  const px = C.layout.pair_char_px;
  // 強制二択。値は A = -1, B = +1。
  const scaleRow = (qi) => {
    const w = C.pair_questions[qi].word;
    return '<div style="display:flex;gap:10px;justify-content:center;margin:4px 0 12px">' +
      [["-1", "Aの方が" + w], ["1", "Bの方が" + w]].map(([v, l]) =>
        '<label style="cursor:pointer;display:inline-block;box-sizing:border-box;width:11.5em;text-align:center;padding:10px 0;border:1px solid #ccd;border-radius:8px;background:#f7f8fb;font-size:14px">' +
        '<input type="radio" name="q' + qi + '" value="' + v + '" style="margin-right:6px">' + l + '</label>').join("") +
      '</div>';
  };
  screenEl.innerHTML = '<div style="display:flex;align-items:center;gap:12px">' +
    '<div style="font-size:18px;font-weight:800;color:#1E2A5E">' + (tIdx + 1) + ' <span style="font-weight:400;color:#667;font-size:14px">/ ' + trials.length + '</span></div>' +
    '<div style="flex:1;height:6px;background:#e3e6ee;border-radius:3px;overflow:hidden"><div style="height:100%;width:' + Math.round(100 * tIdx / trials.length) + '%;background:#2E7D8F"></div></div></div>' +
    '<div style="display:flex;gap:' + C.layout.gap_px + 'px;justify-content:center;align-items:flex-end;margin:14px 0 4px">' +
    ['A', 'B'].map(l => '<div style="text-align:center"><div style="font-size:15px;font-weight:700;color:#1E2A5E;margin-bottom:6px">' + l + '</div><canvas id="cv' + l + '" width="' + SIZE + '" height="' + SIZE + '" style="width:' + px + 'px;height:' + px + 'px;border:1px solid #ddd;border-radius:4px;background:#fff"></canvas></div>').join("") +
    '</div>' +
    '<div style="text-align:center;margin:6px 0 10px"><button id="again" style="font-size:15px;padding:9px 22px;border-radius:999px;border:2px solid #1E2A5E;background:#fff;color:#1E2A5E;cursor:pointer">▶ もう一度みる</button>' +
    '<div style="margin-top:8px;text-align:left;display:inline-block;font-size:14.5px;color:#1c2540;line-height:1.8">・表示は<b>くりかえし流れます</b>。見ながら答えてください。<br>・迷った場合も、<b>より近いと感じる方</b>を選んでください。</div></div>' +
    C.pair_questions.map((q, qi) =>
      '<p style="font-size:15px;text-align:center;margin:10px 0 2px">' + q.text + '</p>' + scaleRow(qi)).join("") +
    '<p style="text-align:center"><button class="primary" id="next" disabled style="opacity:.5;background:#1E2A5E">次へ</button></p>';
  const ctxL = document.getElementById("cvA").getContext("2d");
  const ctxR = document.getElementById("cvB").getContext("2d");
  const player = makePairPlayer(ctxL, ctxR, tr);
  stopPlayback = () => player.stop();
  let replays = 0;
  const shownAt = Date.now();
  document.getElementById("again").onclick = () => { replays++; player.restart(); };
  const btn = document.getElementById("next");
  const check = () => {
    const ok = C.pair_questions.every((_, qi) =>
      screenEl.querySelector('input[name="q' + qi + '"]:checked'));
    btn.disabled = !ok; btn.style.opacity = ok ? "1" : ".5";
  };
  screenEl.querySelectorAll("input").forEach(r => r.addEventListener("change", check));
  btn.onclick = () => {
    player.stop();
    const scores = {};
    C.pair_questions.forEach((q, qi) => {
      scores[q.key] = Number(screenEl.querySelector('input[name="q' + qi + '"]:checked').value);
    });
    const row = Object.assign({}, tr, {
      scores, cycles: player.cycles(), replays, view_ms: Date.now() - shownAt,
    });
    answers.trials.push(row);
    sendClipRecord(row);
    tIdx++; saveProgress(); showTrial();
  };
}

// ---- 終了: 全試行を答え終えたら、そのまま送って終わる ------------------------
//   （初版〜p5.1にあった4方式の順位づけ1問は 2026-08-30 に廃止。6ペアの二択から
//     1人の中の順序は組み立てられて重複するうえ、「よいと思う順」という第3の
//     曖昧な基準になるため。記録の answers.ranking は null のまま残る。）
function finishSession() {
  stopAnim();
  saveProgress();
  if ((C.post_survey || {}).enabled && !(answers && answers.survey)) return postSurveyScreen();
  submitAndFinish();
}

// ---- 課題のあとの任意2問（較正の postSurveyScreen の移植・2026-08-30）--------
// ⚠ すべて任意。答えずに「次へ」で進める。除外には使わず感度分析用。
function postSurveyScreen() {
  const qs = (C.post_survey && C.post_survey.questions) || [];
  const picked = {};
  screenEl.innerHTML = '<h2 style="color:#1E2A5E">最後に：任意のアンケート</h2>' +
    '<p>回答は任意です。答えたくない項目は回答せず、そのまま「次へ」を押してください。' +
    '回答内容によって報酬が変わることはありません。</p>' +
    '<div id="qs"></div>' +
    '<p style="text-align:center;margin-top:20px"><button class="primary" id="qDone">次へ</button></p>';
  const box = document.getElementById("qs");
  qs.forEach((q, qi) => {
    const wrap = document.createElement("div");
    wrap.style.cssText = "margin-top:18px";
    const t = document.createElement("div");
    t.style.cssText = "font-size:15px;font-weight:700;margin-bottom:7px";
    t.textContent = "Q" + (qi + 1) + ". " + q.label;
    wrap.appendChild(t);
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:7px;flex-wrap:wrap";
    (q.options || []).forEach(op => {
      const b = document.createElement("button");
      b.textContent = op;
      b.style.cssText = "font-size:14px;padding:8px 14px;border-radius:8px;" +
        "border:1px solid #b9c0cf;background:#fff;cursor:pointer;font-family:inherit";
      b.onclick = () => {
        // もう一度押したら選択を外せる（誤って押したときのため）
        const off = picked[q.id] === op;
        picked[q.id] = off ? undefined : op;
        row.querySelectorAll("button").forEach(x => {
          const on = !off && x === b;
          x.style.background = on ? "#1E2A5E" : "#fff";
          x.style.color = on ? "#fff" : "";
          x.style.borderColor = on ? "#1E2A5E" : "#b9c0cf";
        });
      };
      row.appendChild(b);
    });
    wrap.appendChild(row);
    box.appendChild(wrap);
  });
  document.getElementById("qDone").onclick = () => {
    const survey = {};
    // 答えなかった項目は空文字（「聞かれたが答えなかった」と
    // 「そもそも聞いていない」を区別するため）。
    qs.forEach(q => { survey[q.id] = picked[q.id] || ""; });
    answers.survey = survey;
    const rec = {
      kind: "transfer_post_survey",
      stimulus_id: "post_survey|" + GROUP,
      target_char: "-", response_char: "-",
      modality: "transfer_post_survey", q_set: "transfer", phase: PHASE, group: GROUP,
      assign_index: ASSIGN, assign_source: ASSIGN_SOURCE, n_choices: 2,
      version: VERSION, config_version: C.config_version,
    };
    qs.forEach(q => { rec[q.id] = survey[q.id]; });
    sendRecord(rec).catch(() => {});
    saveProgress();
    submitAndFinish();
  };
}

// ---- 送信 -------------------------------------------------------------------
function finalRecord(durS) {
  return {
    kind: "transfer_wellbeing", record_kind: "final",
    stimulus_id: "pair|" + GROUP + "|final",
    modality: (C.logging && C.logging.modality) || "transfer_wellbeing",
    q_set: "transfer", phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    chars: CHARS4.join(""),
    n_trials: answers.trials.length,
    wellbeing_json: JSON.stringify(answers),
    duration_s: durS,
    version: VERSION, config_version: C.config_version,
  };
}

async function submitAndFinish() {
  stopAnim();
  const durS = Math.round((Date.now() - startedAt) / 1000) + (elapsedPrior || 0);
  showSending();
  const rec = finalRecord(durS);
  let ok = await sendRecord(rec);
  if (ok) ok = await sendRecord(sessionRecord(durS));
  if (!ok) { showSendFailure(rec, durS, 1); return; }
  saveDoneState(durS, null);
  await finishUp(durS);
}

// ---- 起動 -------------------------------------------------------------------
let startedAt = Date.now();
async function startSession() {
  screenEl.innerHTML = '<div style="min-height:40vh;display:flex;align-items:center;justify-content:center"><h1 style="border:none">読み込み中…</h1></div>';
  const a = await resolveAssignment();
  if (a.blocked) { blockedScreen(a.reason, a); return; }
  ASSIGN = a.assign_index; ASSIGN_SOURCE = a.source;
  CHARS4 = charsForParticipant();
  await preload();
  if (!trials.length) trials = buildTrials();
  if (!answers) answers = { trials: [], chars: CHARS4.slice(), assign_index: ASSIGN };
  PROD.consentScreen(screenEl, "文字の見え方", 10, visionCheckPair, false,
    { noEnvNote: true, desc: "文字表示の見え方の評価です" });
  tidyConsentScreen();
}

(async function () {
  try {
    showPreLaunchBadge();
    if (window.PROD && PROD.enabled) {
      const st = PROD.loadState("transfer_pair");
      if (st && st.completed) { screenEl.innerHTML = finishHTML(st.duration_s || 0); return; }
      if (st && st.session_v === 2 && Array.isArray(st.trials) && st.trials.length) {
        trials = st.trials; tIdx = st.idx || 0; answers = st.answers || null;
        elapsedPrior = st.elapsed_s || 0;
      }
    }
    await startSession();
  } catch (e) {
    screenEl.innerHTML = "<h1>読み込みエラー</h1><p class='muted'>" + e.message + "</p>";
  }
})();
