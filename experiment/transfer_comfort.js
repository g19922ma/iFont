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

const VERSION = "c1.5";
const CFG = window.TRANSFER_CONFIG;            // 共用（描画・保存先）。書き換えない。
const C = window.TRANSFER_COMFORT_CONFIG;      // 群Cだけの設定
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
  return FSTORE ? FSTORE.isTestRun(pid) : (CFG.pre_launch === true);
}

// 掲載前フラグが立っているあいだ、画面の隅に小さく出す帯。
// **false に戻し忘れたまま掲載してしまう事故**を、開いて数秒で気づけるようにする。
function showPreLaunchBadge() {
  if (!(CFG.pre_launch === true)) return;
  console.warn("[comfort] 掲載前フラグ pre_launch=true。この回の記録はすべて " +
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
        console.warn(`[comfort] 名簿(${step.backend})への問い合わせ ${i + 1}/${attempts} 回目が失敗: ${res.why}`);
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
    console.warn("[comfort] 記録の送信先が1つも設定されていないので記録が残りません");
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
        if (tries > 1) { sendRetries++; console.warn(`[comfort] 記録の送信は ${tries} 回目(${step.backend})で通りました`); }
        if (BACKEND.dual_write_logging) {
          const other = (step.backend === "firestore") ? "gas" : "firestore";
          const ready = (other === "firestore") ? firestoreReady() : gasLoggingReady();
          if (ready) sendOnce(other, envelope).catch(() => {});
        }
        return true;
      }
      console.warn(`[comfort] 記録の送信(${step.backend}) ${i + 1}/${attempts} 回目が失敗: ${r.why}`);
    }
  }
  sendFailures++;
  console.error(`[comfort] 記録を ${tries} 回試して送れませんでした`);
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
    stimulus_id: "comfort|" + GROUP + "|" + clip.family + "|" + clip.presentation,
    target_char: "-", response_char: "-",
    modality: (C.logging && C.logging.modality) || "transfer_wellbeing",
    q_set: "transfer", phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    n_choices: C.families.length,
    wellbeing_json: JSON.stringify(clip),
    choice: clip.family + "|" + clip.presentation,
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
    n_trials: (answers && answers.clips) ? answers.clips.length : 0,
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
function wipeDraw(ctx, ch, s) {
  const p = Math.max(0, Math.min(1, s));
  drawBlank(ctx);
  if (!imgs[ch]) return;
  const dir = CFG.visual.families.wipe.direction || "ltr";
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
  if (rw <= 0 || rh <= 0) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(rx, ry, rw, rh);
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

// この実験で画面に出る字（1字条件の字 ＋ 5字続ける条件の並び ＋ 見え方の確認の「あ」）。
function neededChars() {
  return [...new Set([C.single_char].concat(C.sequence).concat(["あ"]))];
}

async function preload() {
  screenEl.innerHTML = `<div style="min-height:60vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">読み込み中…</h1>
    <div style="width:min(320px,80%);height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden;margin-top:10px">
      <div id="loadBar" style="height:100%;width:0%;background:#2E7D8F"></div></div></div>`;
  const setBar = (p) => { const b = document.getElementById("loadBar"); if (b) b.style.width = Math.round(p * 100) + "%"; };

  const need = neededChars();
  let done = 0;
  await Promise.all(need.map(async ch => {
    try { imgs[ch] = await loadImage(ch); } catch (e) { console.warn("[comfort]", e.message); }
    done++; setBar(0.6 * done / need.length);
  }));
  if (!need.every(ch => imgs[ch])) throw new Error("代表字の画像が読めません");

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
//   4方式 × 3つの提示のしかた = 12本。**方式も提示のしかたも混ぜて**並べる。
//   何番目に出したかは order 列として記録に残す（順序の効果を後から見るため）。
// =========================================================================
function buildClips() {
  const out = [];
  C.presentations.forEach(pres => C.families.forEach(fam => out.push({ presentation: pres, family: fam })));
  return shuffle(out).map((c, i) => Object.assign(c, { order: i + 1 }));
}

// その本で出す字の並び。1字条件は1字、5字条件は決められた並び。
function clipChars(presentation) {
  return (presentation === "single") ? [C.single_char] : C.sequence.slice();
}

// =========================================================================
// 再生の土台（3つの提示のしかたを1つの仕組みで動かす）
//   single … キャンバス1枚。1字が現れて、しばらく残って、消える
//   row5   … キャンバス5枚。左から1字ずつ現れ、**出た字はそのまま残る**
//   swap5  … キャンバス1枚。同じ場所で1字ずつ**入れ替わる**
//
//   間合いは transfer_comfort_config.js の timing で決める。要点は
//   「**前の字が現れきってから inter_char_gap_ms だけ空けて次が始まる**」ことで、
//   これにより字と字の開始の間隔は 600 + 300 = 約900ミリ秒になる。
//   視覚的マスキング（前後の刺激が干渉する現象）が起きる時間帯は
//   開始どうしの間隔が200ミリ秒以下とされるので、その4倍以上離れている。
//   干渉を避けたうえで見え心地だけを聞く、という設計である。
// =========================================================================

// 1字ぶんの表示幅px。**3条件で同じ値**を使う（1字条件だけ大きく出すと、
// 提示のしかたではなく字の大きさの違いを答えられてしまうため）。
// 5字を横に並べ、字と字のすき間を gap_ratio 文字ぶん空けたときの1字ぶんの幅にそろえる。
function charPx(host) {
  // 幅は**実際に置く場所の内側**で測る。clientWidth には左右の余白(padding)が
  // 入っているので引く。引き忘れると、5字が枠からはみ出して右端が切れる。
  // host を渡さないときはカード全体の幅で計算する。
  const el = (host && host.clientWidth > 60) ? host : screenEl;
  const cs = getComputedStyle(el);
  const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
  const n = C.sequence.length, r = C.layout.gap_ratio;
  // キャンバスには左右1pxずつの枠が付くので、その2px×n も引いておく。
  const w = Math.max(200, (el.clientWidth || 640) - pad - 2 * n - 2);
  return Math.max(28, Math.min(C.layout.max_char_px, Math.floor(w / (n + (n - 1) * r))));
}

// 描く場所を作る。row5 は5枚、それ以外は1枚。
// row5 では**最初から5枚ぶんの空き枠を置く**（字が出るたびに位置がずれないように）。
function buildStage(host, presentation, opts) {
  const chars = clipChars(presentation);
  const px = (opts && opts.px) || charPx(host);
  const gap = Math.round(px * C.layout.gap_ratio);
  const n = (presentation === "row5") ? chars.length : 1;
  host.innerHTML = "";
  host.style.cssText = `display:flex;justify-content:center;align-items:center;gap:${gap}px;flex-wrap:nowrap`;
  const ctxs = [];
  for (let i = 0; i < n; i++) {
    const cv = document.createElement("canvas");
    cv.width = SIZE; cv.height = SIZE;
    cv.style.cssText = `width:${px}px;height:${px}px;flex:0 0 auto;background:#fff;` +
                       `border:1px solid #ddd;border-radius:4px;display:block`;
    host.appendChild(cv);
    ctxs.push(cv.getContext("2d"));
  }
  ctxs.forEach(drawBlank);
  return { chars, ctxs, px, gap, presentation };
}

// 1本ぶんの再生器。返り値の stop() を呼ぶまで、くりかえし流れつづける。
//   opts.maxCycles … 何周で止めるか（0で設定の上限まで）
//   opts.onEnd     … 止まったときに呼ぶ
function makePlayer(stage, family, opts) {
  const o = opts || {};
  const chars = stage.chars, ctxs = stage.ctxs;
  const single = (stage.presentation === "single");
  const renderer = RENDERERS[family] || RENDERERS.fade;
  const progs = chars.map(ch => progressFor(family, ch));
  const t = C.timing;
  const animMax = Math.max(...progs.map(p => p.dur_ms));
  // 1字ぶんの持ち時間。5字条件は「現れきる時間 ＋ 空ける時間」。
  const step = single ? animMax : (animMax + t.inter_char_gap_ms);
  const hold = single ? t.single.hold_ms : t.sequence.hold_ms;
  const gapMs = single ? t.single.gap_ms : t.sequence.gap_ms;
  const cycleMs = chars.length * step + hold + gapMs;
  const maxCycles = o.maxCycles || t.max_cycles || 0;

  let raf = null, stopped = false, t0 = null;
  let lastCycle = -1, curIdx = -1, done = [], cycles = 0;

  const ctxFor = (i) => (ctxs.length > 1 ? ctxs[i] : ctxs[0]);

  // 取りこぼしの穴埋め。**横並びのときだけ**要る。
  // 画面が重いときや、参加者が別のタブに移っているあいだは、ブラウザが描画のコマを
  // 飛ばす。そのまま進むと「2文字目だけ出ていない」といった抜けが残ってしまう。
  // そこで次の字に移るときに、まだ描き終わっていない手前の字を、
  // **完成した姿で描き足して**から進む。
  function fillSkipped(upTo) {
    if (ctxs.length <= 1) return;
    for (let k = 0; k < upTo && k < chars.length; k++) {
      if (done[k]) continue;
      renderer.begin(chars[k], ctxFor(k));
      renderer.draw(ctxFor(k), chars[k], 1);
      done[k] = true;
    }
  }

  function frame(now) {
    if (stopped) return;
    // 時計は「最初の1コマが描かれた時刻」から数える。play を呼んだ時刻から数えると、
    // 参加者が別のタブに移っているあいだ描画が止まる（ブラウザの仕様）ため、
    // 戻ってきた瞬間に何周ぶんも飛ばしたことになってしまう。
    if (t0 === null) t0 = now;
    const el = now - t0;
    const c = Math.floor(el / cycleMs);
    if (c !== lastCycle) {
      if (maxCycles && c >= maxCycles) {
        stopped = true; ctxs.forEach(drawBlank);
        if (typeof o.onEnd === "function") o.onEnd();
        return;
      }
      lastCycle = c; curIdx = -1; done = []; cycles = c + 1;
      ctxs.forEach(drawBlank);
    }
    const inC = el - c * cycleMs;
    if (inC < chars.length * step) {
      const i = Math.floor(inC / step);
      if (i !== curIdx) {
        fillSkipped(i);                          // 取りこぼしの穴埋め（下の注記）
        curIdx = i;
        // 入れ替えの条件は、次の字を出す前に前の字を消す。
        if (ctxs.length === 1 && !single) drawBlank(ctxs[0]);
        renderer.begin(chars[i], ctxFor(i));
      }
      // 現れきったら描き直さない（横並びでは、そのまま残す）。
      if (!done[i]) {
        const s = progs[i].fn(inC - i * step);
        renderer.draw(ctxFor(i), chars[i], s);
        if (s >= 1) done[i] = true;
      }
    } else if (inC >= chars.length * step + hold) {
      if (curIdx !== -2) { curIdx = -2; ctxs.forEach(drawBlank); }   // 消す時間帯
    } else {
      fillSkipped(chars.length);                 // 全部出そろって残している時間帯
    }
    raf = requestAnimationFrame(frame);
  }

  raf = requestAnimationFrame(frame);
  return {
    stop() { stopped = true; if (raf) cancelAnimationFrame(raf); },
    restart() { t0 = null; lastCycle = -1; curIdx = -1; done = []; ctxs.forEach(drawBlank); },
    cycles: () => cycles,
    info: { step_ms: step, cycle_ms: cycleMs, anim_ms: animMax,
            progress_source: progs[0].source, n_chars: chars.length },
  };
}

// =========================================================================
// 画面
// =========================================================================
let clips = [], idx = 0;
let answers = null;   // {clips:[...], choice_family:"", choice_presentation:"", ...順序も入る}
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
      <li><b>1文字だけ出るもの</b>と、<b>5文字続けて出るもの</b>があります。
          5文字のときは、左から並んでいくものと、同じ場所で入れ替わるものがあります。</li>
      <li>1つの表示は<b>くりかえし流れつづけます</b>。答えているあいだ、何度でも見ていられます。</li>
      <li>「▶ もう一度みる」を押すと、その場で最初から流し直せます。</li>
      <li>最後に、好みについて2問うかがいます。</li>
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
  if (idx >= clips.length) return showChoiceFamily();
  const clip = clips[idx];
  const shownAt = Date.now();

  screenEl.innerHTML = `<div class="muted">見え心地の質問（${idx + 1} / ${clips.length}）</div>
    <div id="vbox" class="vbox"></div>
    <div style="text-align:center;margin:6px 0 10px">
      ${C.allow_replay ? `<button id="again" style="font-size:15px;padding:10px 24px;border-radius:999px;border:2px solid #1E2A5E;background:#fff;color:#1E2A5E;cursor:pointer">▶ もう一度みる</button>` : ""}
      <div class="muted" style="margin-top:6px">この表示はくりかえし流れます。見ながら答えてください。</div>
    </div>
    <div id="wbForm"></div>`;

  const stage = buildStage(document.getElementById("vbox"), clip.presentation);
  const player = makePlayer(stage, clip.family);
  stopPlayback = () => player.stop();

  // 押して流し直した回数（replays）と、自動で流れた周の数（cycles）を分けて数える。
  let replays = 0;
  const againBtn = document.getElementById("again");
  if (againBtn) againBtn.onclick = () => { replays++; player.restart(); };

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
    const cycles = player.cycles();
    stopAnim();
    const one = {
      order: clip.order, family: clip.family, presentation: clip.presentation,
      chars: stage.chars.join(""), condition: C.condition,
      progress_source: player.info.progress_source,
      anim_ms: player.info.anim_ms, step_ms: player.info.step_ms,
      char_px: stage.px, gap_px: stage.gap,
      ratings, cycles, replays,
      view_ms: Date.now() - shownAt,
    };
    answers.clips.push(one);
    sendClipRecord(one);        // 保険。最後の1件が落ちても全損にしないため
    idx++; saveProgress(); showClip();
  };
}

// ---- 最後の質問1: どの「現れ方」（方式）がよいか -----------------------------
// 4方式の見本を1字の提示で並べ、見くらべてから選んでもらう。
// 方式は4つとも違うので、部分表示・ぼかし解除の作業用キャンバスの取り合いは起きない
// （同じ方式のアニメを2つ同時に動かすと壊れる。→ 質問2の作り）。
function showChoiceFamily() {
  stopAnim();
  const cfg = C.choice.family;
  const showSamples = !!cfg.show_samples;
  // 見本を並べる順も混ぜる（左端が有利にならないように）。記録に残す。
  const order = (answers.choice_family_order && answers.choice_family_order.length)
    ? answers.choice_family_order.slice() : shuffle(C.families.slice());
  answers.choice_family_order = order;
  const shownAt = Date.now();
  const px = charPx();

  const cell = (f) => `
    <label style="flex:0 1 auto;display:block;cursor:pointer;padding:10px 8px;background:#f7f8fb;
                  border:1px solid #e3e6ee;border-radius:10px;text-align:center;max-width:${px + 26}px">
      ${showSamples ? `<div class="mini" data-fam="${f}" style="margin:0 auto 8px"></div>` : ""}
      <div style="font-size:13px;line-height:1.35;margin-bottom:8px">${cfg.labels[f] || f}</div>
      <input type="radio" name="wbc" value="${f}">
    </label>`;

  screenEl.innerHTML = `<h2 style="color:#1E2A5E">最後の質問（1 / 2）</h2>
    <p>${cfg.text}</p>
    ${showSamples ? `<p class="muted">${cfg.note}</p>` : ""}
    <div id="wbc" style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:10px">
      ${order.map(cell).join("")}</div>
    ${showSamples ? `<p style="text-align:center;margin-top:12px">
      <button id="againAll" style="font-size:15px;padding:10px 24px;border-radius:999px;border:2px solid #1E2A5E;background:#fff;color:#1E2A5E;cursor:pointer">▶ 見本を最初から流す</button></p>` : ""}
    <p style="text-align:center;margin-top:16px">
      <button class="primary" id="wbNext2" disabled style="opacity:.5;background:#1E2A5E">次へ</button></p>`;

  const players = [];
  let replays = 0;
  if (showSamples) {
    order.forEach(f => {
      const holder = screenEl.querySelector(`.mini[data-fam="${f}"]`);
      holder.style.width = px + "px";
      players.push(makePlayer(buildStage(holder, "single", { px }), f, { maxCycles: 0 }));
    });
    const againAll = document.getElementById("againAll");
    if (againAll) againAll.onclick = () => { replays++; players.forEach(p => p.restart()); };
  }
  stopPlayback = () => players.forEach(p => p.stop());

  const next = document.getElementById("wbNext2");
  screenEl.querySelectorAll('input[name="wbc"]').forEach(r => r.addEventListener("change", () => {
    next.disabled = false; next.style.opacity = "1";
  }));
  next.onclick = () => {
    const sel = screenEl.querySelector('input[name="wbc"]:checked');
    stopAnim();
    answers.choice_family = sel ? sel.value : "";
    answers.choice_family_ms = Date.now() - shownAt;
    answers.choice_family_replays = replays;
    saveProgress();
    showChoicePresentation();
  };
}

// ---- 最後の質問2: 5文字続けるときの「出し方」がどちらがよいか -----------------
// 見本は**1問目で選ばれた方式**で出す。自分がよいと思った現れ方で、
// 横に並べるのと入れ替えるのを見くらべてもらうためである。
//
// ⚠ 2つの見本は**同じ方式**なので、同時に動かせない。部分表示(reveal)と
//   ぼかし解除(blur)は作業用のキャンバス・画素の並びを1つだけ持つ作りで、
//   同じ方式のアニメを2つ並行して動かすと互いの状態を壊してしまう。
//   そこで**1周ずつ交互に**流し、いま流しているほうを枠の色で示す。
function showChoicePresentation() {
  stopAnim();
  const cfg = C.choice.presentation;
  const fam = answers.choice_family || C.families[0];
  const showSamples = !!cfg.show_samples;
  const opts = (answers.choice_pres_order && answers.choice_pres_order.length)
    ? answers.choice_pres_order.slice()
    : shuffle(cfg.sample_options.slice());
  answers.choice_pres_order = opts;
  // 「どちらでもよい」は見本を持たないので、いつも最後に置く。
  const allOpts = opts.concat(Object.keys(cfg.labels).filter(k => opts.indexOf(k) < 0));
  const shownAt = Date.now();

  const row = (k) => `
    <label data-opt="${k}" style="display:block;cursor:pointer;margin:10px 0;padding:12px 12px;
           background:#f7f8fb;border:2px solid #e3e6ee;border-radius:10px">
      <div style="font-size:15px;margin-bottom:${opts.indexOf(k) >= 0 && showSamples ? "10px" : "0"}">
        <input type="radio" name="wbp" value="${k}" style="vertical-align:middle;margin-right:8px">${cfg.labels[k] || k}</div>
      ${opts.indexOf(k) >= 0 && showSamples ? `<div class="pres" data-opt="${k}"></div>` : ""}
    </label>`;

  screenEl.innerHTML = `<h2 style="color:#1E2A5E">最後の質問（2 / 2）</h2>
    <p>${cfg.text}</p>
    ${showSamples ? `<p class="muted">${cfg.note}（<b>${C.choice.family.labels[fam] || fam}</b>）
      2つの見本を<b>かわりばんこに</b>流しています。</p>` : ""}
    <div id="wbp">${allOpts.map(row).join("")}</div>
    <p style="text-align:center;margin-top:16px">
      <button class="primary" id="wbDone" disabled style="opacity:.5;background:#1E2A5E">回答を送って終わる</button></p>`;

  if (showSamples) {
    // 1周ずつ交互に流す。動かすのは常に1つだけ。
    const stages = opts.map(k => buildStage(screenEl.querySelector(`.pres[data-opt="${k}"]`), k));
    let turn = 0, cur = null, stopped = false;
    const mark = () => opts.forEach((k, i) => {
      const el = screenEl.querySelector(`label[data-opt="${k}"]`);
      el.style.borderColor = (i === turn) ? "#2E7D8F" : "#e3e6ee";
      el.style.background = (i === turn) ? "#f2fafc" : "#f7f8fb";
    });
    const nextTurn = () => {
      if (stopped) return;
      mark();
      cur = makePlayer(stages[turn], fam, { maxCycles: 1, onEnd: () => {
        turn = (turn + 1) % opts.length;
        nextTurn();
      } });
    };
    nextTurn();
    stopPlayback = () => { stopped = true; if (cur) cur.stop(); };
  }

  const done = document.getElementById("wbDone");
  screenEl.querySelectorAll('input[name="wbp"]').forEach(r => r.addEventListener("change", () => {
    done.disabled = false; done.style.opacity = "1";
  }));
  done.onclick = () => {
    const sel = screenEl.querySelector('input[name="wbp"]:checked');
    stopAnim();
    answers.choice_presentation = sel ? sel.value : "";
    answers.choice_presentation_ms = Date.now() - shownAt;
    submitAndFinish();
  };
}

// ---- 送信して終わる -------------------------------------------------------
// 1参加者1行にまとめて送る（transfer_wellbeing。列は群Bのときのまま使える）。
// 1本ごとの数値は wellbeing_json の中に入る。**分析はこの JSON を開いて読むこと。**
//
// ⚠ **この1件は「落ちてもいい記録」ではない。** 群Cは1参加者1レコードなので、
//   これが入らないと completion_code がサーバのどこにも残らず、参加者が貼った
//   完了コードを照合できない（＝最後までやった人を非承認にしてしまう）。
//   そこで次の3段構えにしてある。
//     1. 送信を**待って**、成功するまで作り直す（logging.retry の3回）
//     2. それでも駄目なら**完了コードを出す前に警告画面**を出し、手で再送させる
//     3. 手の再送も駄目なら、コードは出したうえで「控えて問い合わせて」と案内する
//        （参加者を手ぶらで帰らせない。照合は問い合わせで人が行う）
//   さらに保険として、1本ごとの中間レコードを sendClipRecord() で送ってある。
async function submitAndFinish() {
  const durS = Math.round(elapsedPrior + (Date.now() - T0) / 1000);
  answers.duration_s = durS;
  answers.n_clips = clips.length;
  const rec = {
    kind: "transfer_wellbeing",
    record_kind: "final",
    stimulus_id: "comfort|" + GROUP,
    target_char: "-", response_char: "-",
    modality: (C.logging && C.logging.modality) || "transfer_wellbeing",
    q_set: "transfer", phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    n_choices: C.families.length,
    wellbeing_json: JSON.stringify(answers),
    // choice 列は1つしかないので、2問の答えを「方式|出し方」の形で入れる
    // （細かい内訳と所要は wellbeing_json のほうに入っている）。
    choice: answers.choice_family + "|" + answers.choice_presentation,
    version: VERSION, config_version: C.config_version,
  };
  if (window.PROD) PROD.saveFracTrial(rec);
  // 途中状態は「完了・ただし未送信」にしておく。ここでブラウザを閉じられても、
  // 開き直したときに**同じ記録をもう一度送れる**ようにするためである
  // （完了扱いにしないと、最後の2問からやり直させることになる）。
  saveDoneState(durS, rec);

  showSending();
  const ok = await sendRecord(rec);
  if (!ok) { showSendFailure(rec, durS, 0); return; }
  await finishUp(durS);
}

// 「終わった」ことと「未送信の記録が残っているか」を端末に控える。
// pending が null なら送信済み。
function saveDoneState(durS, pending) {
  if (window.PROD && PROD.enabled) {
    PROD.saveState("transfer_" + PHASE,
      { completed: true, duration_s: durS, pending_rec: pending || null });
  }
}

// 本記録が入ったあとの締め。完走レコードを1行送ってから完了コードを出す。
// 完走レコードが落ちても完了コードは出す（本記録に同じコードが入っているため）。
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

// 送れなかったときの画面。tries は「再送ボタンを押して失敗した回数」。
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
      <b>このコードと、いまの日付・時刻をお手元に控えて</b>、募集の回答欄に貼って提出してください。</p>
      <p style="font-size:26px;font-weight:800;letter-spacing:3px;color:#1E2A5E;text-align:center;
                background:#f2f5f8;border:1px solid #dde3ec;border-radius:10px;padding:12px 8px;margin:12px auto;max-width:340px">
        ${(window.PROD && PROD.completionCode) || ""}</p>
      <p style="margin-bottom:0">記録側にこのコードが残っていない可能性があります。
      承認されない場合は、<b>控えたコードと日時</b>を添えて
      ${mailLink(c.email)}${viaCs}までご連絡ください。
      確認のうえ対応します（${c.pi || "【要確認：研究責任者】"}／${c.institution || "津田塾大学 栗原研究室"}）。</p>
    </div>` : ""}
    <p class="muted" style="text-align:right;margin-top:14px">実施：津田塾大学 栗原研究室</p>`;
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

// 最後の画面。**研究者モードでは完了コードを出さない**。
// 研究者モードの完了コードは、送信もされず照合もできない使い捨ての12桁で、
// 動作確認のつもりで控えると「記録に無いコード」として非承認の元になる。
function finishHTML(durS) {
  if (window.PROD && PROD.enabled) return PROD.completionHTML(durS);
  return `<div style="text-align:center;padding:24px 10px">
    <h1>動作確認が終わりました</h1>
    <p class="muted">研究者向け動作確認モード（URL に <code>?prod=1</code> が無い）です。</p>
    <p><b>完了コードは出ません。</b>このモードでは記録を送らないので、
    コードを出しても記録側に残らず、照合できないためです。</p>
    <p class="muted">v${VERSION} ／ ${PHASE}フェーズ 集団 ${GROUP} ／
    答えた本数 ${(answers && answers.clips) ? answers.clips.length : 0} 本 ／ 所要 ${durS} 秒 ／
    送信できなかった記録 ${sendFailures} 件・作り直して送れた記録 ${sendRetries} 件</p></div>`;
}

// ---- 見え方の確認 ---------------------------------------------------------
function visionCheck() {
  const resuming = !!(answers && answers.clips.length);
  screenEl.innerHTML = `<h2 style="color:#1E2A5E">見え方の確認</h2>
    <p>本番と<b>同じ大きさ・同じ並び</b>で見本を表示しています。
    ふだん画面を見る距離のまま、<b>どの字もはっきり見えること</b>を確認してください。
    見えにくい場合は画面の明るさを上げてください。</p>
    <div id="vcheck" class="vbox"></div>
    <p class="muted" style="text-align:center">画面が横に狭いと、字は自動で小さくなります。
    スマートフォンの方は<b>横向き</b>にすると大きく表示されます。</p>
    <p style="text-align:center;margin-top:16px"><button class="primary" id="go3">${resuming ? "続きから再開する" : "次へ進む"}</button></p>`;
  // 本番と同じ土台で、5字を現れきった状態のまま出す（大きさと字間をそのまま見せる）。
  const stage = buildStage(document.getElementById("vcheck"), "row5");
  stage.chars.forEach((ch, i) => {
    drawBlank(stage.ctxs[i]);
    if (imgs[ch]) stage.ctxs[i].drawImage(imgs[ch], 0, 0, SIZE, SIZE);
  });
  document.getElementById("go3").onclick = () => { resuming ? showClip() : intro(); };
}

// 同意画面に足す3項目（データの保管期間・同意の撤回・問い合わせ先）。
// **transfer.js の同名の関数と同じ中身にしておくこと**（片方だけ直さない）。
// 値は transfer_config.js の contact にあり、掲載前にユーザーが【要確認】を埋める。
function consentExtraHTML() {
  const c = CFG.contact || {};
  const viaCs = c.via_crowdsourcing
    ? "、または応募元の募集サイトのメッセージ機能" : "";
  return `
    <li><b>データの保管</b>：${c.retention || "【要確認：保管期間】"}
        保管するのは回答と技術情報だけで、個人を特定できる情報は含みません。</li>
    <li><b>同意の撤回</b>：この調査は<b>無記名</b>で行うため、回答とあなたご本人を
        結びつける情報を研究者は持っていません。参加をやめたい場合は、
        完了コードが表示される前ならブラウザを閉じるだけで結構です（記録は分析に使いません）。
        提出後に削除をご希望のときは、<b>お手元の完了コード</b>を添えて下記へご連絡ください。
        そのコードで記録を特定できた場合にかぎり削除します。</li>
    <li><b>問い合わせ先</b>：${c.pi || "【要確認：研究責任者】"}
        （${c.institution || "津田塾大学 栗原研究室"}）／
        ${mailLink(c.email)}${viaCs}へご連絡ください。</li>`;
}

// メールアドレスを、押せばメーラーが開くリンクにする。
// 迷惑メールよけに「[at]」と崩す書き方は**採らない**（クラウドソーシングの参加者が
// 報酬の問い合わせで使う宛先なので、そのままコピーできるほうを優先した。
// 判断の理由は transfer_config.js の contact.email のコメントにある）。
// **transfer.js と transfer_comfort.js で同じ中身にしておくこと。**
function mailLink(addr) {
  const a = String(addr || "").trim();
  if (!a || a.indexOf("@") < 0) return a || "【要確認：メールアドレス】";
  return `<a href="mailto:${a}">${a}</a>`;
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
  const ul = rec ? rec.parentElement : screenEl.querySelector("ul");
  if (ul) ul.insertAdjacentHTML("beforeend", consentExtraHTML());
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
  if (!answers) answers = { clips: [], choice_family: "", choice_presentation: "",
                            choice_family_order: [], choice_pres_order: [] };
  // 第3引数は所要の見込み分（いまの prod_common.js は画面に出さないが、
  // 出すようになったときに嘘にならないよう、実測見込みの7分を渡しておく）。
  PROD.consentScreen(screenEl, "文字の見え心地", 7, visionCheck, false,
    { noEnvNote: true,
      desc: "日本語のかな1文字が現れる様子について、続けて見ていられるかを調べる研究です" });
  tidyConsentScreen();
  return true;
}

(async function () {
  try {
    showPreLaunchBadge();
    // 途中再開の情報は、参加者IDを保存時のものへ戻す働きがあるので名簿より先に読む。
    if (window.PROD && PROD.enabled) {
      const st = PROD.loadState("transfer_" + PHASE);
      if (st && st.saved_at) {
        resumeMeta = { count: (st.resume_count || 0) + 1,
                       gapS: (st.resume_gap_s || 0) + Math.round((Date.now() - st.saved_at) / 1000) };
      }
      if (st && st.completed) {
        const durS = st.duration_s || 0;
        // 前回、記録を送れないまま閉じられていたら、開き直しのついでに送り直す。
        // 送れていれば pending_rec は null なので、そのまま完了画面を出す。
        if (st.pending_rec) {
          showSending();
          const ok = await sendRecord(st.pending_rec);
          if (!ok) { showSendFailure(st.pending_rec, durS, 1); return; }
          await finishUp(durS);
          return;
        }
        screenEl.innerHTML = finishHTML(durS);
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
