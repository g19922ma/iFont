// =========================================================================
// 転写検証実験 v3.0 (共通スクリプト。入口は transfer_calib.html / transfer_test.html)
//   計画書: project/実験計画書_転写検証.md (第2稿。特に4章「実験の構成」と10章「実装(差分)」)
//
//   参加者の集団は5つある。**このファイルが受け持つのは、そのうち4つ**である。
//     acal   … 較正(聴覚)。音声を打ち切って聞かせ、かな表から回答してもらう
//     aprime … 較正(視覚)。4方式の基準アニメを、進み具合 s% で打ち切る
//     atest  … 検証(聴覚)。acal と全く同じ課題を、別の人にもう一度
//     b      … 検証(視覚)。生成した進み方 s(t) のアニメを t ms で打ち切る
//              (**識別課題だけで終わる**。見え心地の評価は 2026-08-21 に切り離した)
//     c      … 見え心地(独立の実験)。**このファイルではなく**
//              experiment/transfer_comfort.html / transfer_comfort.js が受け持つ。
//              群Bの末尾で聞く旧方式に戻したいときだけ、下の wellbeing を true にする
//
//   ただし**入口のURLは2つだけ**にしてある(同時期に走る集団を1つの掲載にまとめ、
//   サイトの中で自動的に振り分ける)。クラウドソーシングでは別々の掲載どうしで
//   「どちらか片方にしか参加できない」を強制できないため、同時期の集団は
//   1つの入口に統合し、参加者IDごとに1つの集団へ割り当てる。
//     transfer_calib.html … 較正フェーズ: acal と aprime に自動で振り分け
//     transfer_test.html  … 検証フェーズ: atest と b に自動で振り分け
//   フェーズ間(較正→検証)の重複は、サーバの参加者名簿と照合して断る(4集団は互いに独立)。
//   割り当ての決め方は resolveAssignment() を参照。
//
//   実験パラメータ(字・時点・水準・割付・比率)は experiment/transfer_config.js に
//   全部出してある。このファイルには数値を直接書かない(A2 で数値だけ差し替えるため)。
//
//   既存の統合セッション experiment/audio1char.js (v3.41) を土台にしている。
//   同意画面・音量の確認・見え方の確認・かな表の回答・選び直しの確認・進捗・
//   完了コード・途中再開は prod_common.js の部品をそのまま使う。
//   ただし土台は1人が聴覚と視覚の両方をやる統合セッションだったのに対し、この実験は
//   1人が片方だけをやる。そのため**準備の画面は集団ごとに出し分ける**。
//     聴覚(acal / atest): 同意(再生機器の申告あり) → 音量の確認 → 聴覚の説明と練習
//     視覚(aprime / b)  : 同意(明るさの案内あり)   → 見え方の確認 → 視覚の説明と練習
//   計画書10章の差分として変えたのは次の4点。
//     1. 聴覚の打ち切りが「割合(frac%)」から「音の実体の開始からの絶対ms」になった。
//        刺激は事前に打ち切って作った WAV を配信する(生成: tools/build_transfer_gates.py)。
//     2. 視覚に4方式(フェード・部分表示・ぼかし解除・ワイプ)の描画器を入れ、
//        「進み具合 s∈[0,1] を渡すと1フレーム描く」という共通の形にそろえた。
//        再生は等速(較正)と、数値列 s(t) をなぞる転写(warp)の2通り。
//     3. 聞き直し・見直しのボタンを廃止した(刺激に触れる回数は1回だけ)。
//     4. 記録に group / family / condition / gate_ms / progress_pct / actual_ms /
//        trial_index の列を足した。
//
//   版の数え方: 土台の audio1char.js とは別の実験なので v3.0 から採番し直す。
// =========================================================================
"use strict";

const VERSION = "3.6";
const CFG = window.TRANSFER_CONFIG;
const P = new URLSearchParams(location.search);

// 研究者モード(?prod なし)のときだけ、タブの名前に内部の呼び名を足す。
// 参加者が見るタブ名は、入口HTMLの <title> のまま「内容だけを表す名前」にしてある
// （較正フェーズと検証フェーズは、参加者から見れば同じ課題である。
//   「前半／後半」と書くと、片方しか参加しない人に両方あるかのように読まれる）。
if (!(window.PROD && PROD.enabled)) {
  document.title += "［研究者確認：" + ((window.TRANSFER_PAGE || {}).phase || "?") + "フェーズ］";
}

// ---- 集団(group) ----------------------------------------------------------
// mode      : "audio" = 聴覚課題 / "visual" = 視覚課題
// play      : 視覚の再生の仕方。"calib" = 等速で s% まで進めて打ち切る /
//             "warp" = 数値列 s(t) をなぞって t ms で打ち切る
// wellbeing : 識別課題のあとに見え心地の評価をするか。
//             **2026-08-21 に既定で切った**。見え心地(RQ3)は群Bの末尾から切り離し、
//             独立の実験(群C・experiment/transfer_comfort.html)にしたため。
//             切り離した理由は transfer_comfort_config.js の冒頭にある。
//             群Bの末尾で聞く形に戻したいときは transfer_config.js の
//             wellbeing.in_group_b を true にする(この行は触らない)。
const GROUPS = {
  acal:   { mode: "audio",  label: "聴覚",   task_label: "かなの聞き取り" },
  atest:  { mode: "audio",  label: "聴覚",   task_label: "かなの聞き取り" },
  aprime: { mode: "visual", label: "視覚", play: "calib", task_label: "かなの見分け" },
  b:      { mode: "visual", label: "視覚", play: "warp",  task_label: "かなの見分け", wellbeing: CFG.wellbeing.in_group_b === true },
};
// このページがどのフェーズの入口か。各HTMLが読み込みの前に埋め込む。
//   <script>window.TRANSFER_PAGE = { phase: "calib" };</script>
const PAGE = window.TRANSFER_PAGE || { phase: "calib" };
const PHASE = PAGE.phase;
const PHASE_GROUPS = (CFG.phases && CFG.phases[PHASE]) || [];

// 集団と割付は起動時に決まる(サーバの参加者名簿に問い合わせる)。
let GROUP = "", G = null, ASSIGN = 0;
let ASSIGN_SOURCE = "";     // "server" | "cache" | "local_hash" | "forced" (記録に残す)

// 参加者IDから決定的に作る番号。サーバに問い合わせられないときの代用。
function hashIndexFrom(pid) {
  let h = 2166136261;
  for (let i = 0; i < pid.length; i++) { h ^= pid.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0) % 10000;
}

// 1人あたりのターゲット問題数。研究者モードの短縮版チェックで小さくできる。
let MAX_TARGET_TRIALS = Number(CFG.design.max_target_trials) || 0;

// ---- 集団の自動振り分け ---------------------------------------------------
// サーバ(GAS)の参加者名簿に問い合わせて、次の2つを決める。
//   1. この参加者をどちらの集団に入れるか(同じフェーズの2集団の人数が釣り合うように)
//   2. 集団の中の連番(何番目の参加者か)。字×条件の割付はこの連番から決まる
// 同じ参加者IDが開き直したときは、名簿にある割り当てをそのまま返す(途中再開と整合)。
// 検証フェーズでは、較正フェーズの名簿に載っている人を断る(4集団は互いに独立)。
// 問い合わせ先・仕様は gas/transfer_patch.md。
const ROSTER = CFG.roster || {};

// ---- 保存基盤(Firestore / GAS)の選び方 ------------------------------------
// 名簿と記録の置き場所は設定で切り替える(transfer_config.js の backend)。
// 主が全部だめだったときは、もう一方も試す(fallback)。**両方だめのときだけ**
// お断り画面へ行く。
//
// 2026-08-21 に Firestore を主にした。GAS は応答の本体を
// script.googleusercontent.com へリダイレクトして返す作りで、この中継が一過性で
// 失敗して HTML を返すことがあるため(実機で発生)。Firestore は REST を直接叩く。
// **切り戻しは backend.roster と backend.logging を "gas" に戻すだけでよい。**
const BACKEND = CFG.backend || {};
const FSTORE = window.TRANSFER_FIRESTORE || null;

// ---- 掲載前フラグ（transfer_config.js の pre_launch）------------------------
// true のあいだは、本番モード（?prod=1）で動かしても全レコードに is_test を付け、
// 名簿の連番も本番とは別のカウンタから配る。判定の本体は transfer_firestore.js に
// あり（そちらが Firestore への書き込みで使う）、ここはページ側の入口である。
// GAS へ回すときは封筒と問い合わせのURLに同じ値を載せる必要があるので、
// ページ側からも同じ判定を引けるようにしてある。
function isTestRun() {
  const pid = (window.PROD && PROD.participantId) || "";
  return FSTORE ? FSTORE.isTestRun(pid) : (CFG.pre_launch === true);
}

// 掲載前フラグが立っているあいだ、画面の隅に小さく出す帯。
// **false に戻し忘れたまま掲載してしまう事故**を、開いて数秒で気づけるようにする
// （気づかないと、本物の参加者のデータが全部テスト扱いになる）。
function showPreLaunchBadge() {
  if (!(CFG.pre_launch === true)) return;
  console.warn("[transfer] 掲載前フラグ pre_launch=true。この回の記録はすべて " +
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

// 「どの順で試すか」の段取りを作る。使えない基盤は最初から外す。
// 戻り値は [{backend:"firestore"|"gas", primary:true|false}, …]。
function backendPlan(which, ready) {
  const primary = (BACKEND[which] === "gas") ? "gas" : "firestore";
  const order = (BACKEND.fallback === false)
    ? [primary]
    : [primary, primary === "gas" ? "firestore" : "gas"];
  return order
    .filter(b => ready(b))
    .map((b, i) => ({ backend: b, primary: i === 0 && b === primary }));
}

// 記録の assign_source 列に何と書くか。あとから
// 「どの基盤で・何回目に通ったか」を数えられるようにしておく。
//   firestore / firestore:retry2 … Firestore が主で通った
//   server / server:retry2       … GAS が主で通った(2026-08-20 までと同じ表記)
//   gas-fallback / …             … Firestore がだめで GAS に落ちて通った
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

// 待つ。再挑戦の間隔に散らし(ジッタ)を足して、皆が同時に押し寄せるのを避ける。
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function backoffMs(cfg, i) {
  const d = (cfg && cfg.delays_ms) || [800, 2000, 4000];
  const base = d[Math.min(i, d.length - 1)] || 800;
  return base + Math.random() * ((cfg && cfg.jitter_ms) || 0);
}

// 名簿サーバへの問い合わせ1回ぶん。
// 戻り値は3通り。 {kind:"ok", j} / {kind:"blocked", reason} / {kind:"fail", why}
//
// **応答が JSON でないときも「失敗」に数える**のが要点である。GAS は一過性の理由で
// HTML のエラーページを 200 で返すことがあり、そのまま JSON として読もうとすると
// 例外になる。ここでいったん本文を文字列で受け取り、読めたときだけ中身を見る。
async function rosterQueryOnce(pid) {
  const base = ROSTER.status_url;
  const url = base + (base.indexOf("?") >= 0 ? "&" : "?") +
    "action=transfer_status&phase=" + encodeURIComponent(PHASE) +
    "&participant_id=" + encodeURIComponent(pid) +
    "&worker_id=" + encodeURIComponent((window.PROD && PROD.workerId) || "") +
    // 試し打ちの目印。GAS 側は参加者IDの頭（curltest- / uitest-）も見るが、
    // 掲載前フラグはブラウザ側にしかないので、こちらから伝える。
    // GAS はこの印が立っている人を**本番の人数に数えない**（連番を消費しない）。
    "&is_test=" + (isTestRun() ? "1" : "0");
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ROSTER.timeout_ms || 8000);
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
    // ここに来るのが「HTMLのエラーページが返った」場合。一過性なので作り直す。
    return { kind: "fail", why: "JSONでない応答(" + text.slice(0, 40).replace(/\s+/g, " ") + "…)" };
  }
  if (j && j.blocked) return { kind: "blocked", reason: j.reason || "already_participated" };
  if (j && PHASE_GROUPS.indexOf(j.group) >= 0) return { kind: "ok", j: j };
  return { kind: "fail", why: "集団が読み取れない応答" };
}

// 名簿の問い合わせ1回ぶん(Firestore 版)。戻り値の形は GAS 版とそろえてある。
//
// 中でやっていることは transfer_firestore.js の resolveAssignment を見ること。
// 要点は3つ。
//   ・開き直した人には、名簿にある**前と同じ集団・同じ連番**を返す
//   ・断るべきフェーズに出ていた人は、採番する前に断る(番号を無駄にしない)
//   ・採番は Firestore の increment 変換なので、同時に来ても番号が衝突しない
async function rosterQueryOnceFirestore(pid) {
  const r = await FSTORE.resolveAssignment({
    phase: PHASE,
    groups: PHASE_GROUPS,
    // 「このフェーズに来た人が、過去にどのフェーズに出ていたら断るか」の表。
    blockers: (CFG.phase_blocks && CFG.phase_blocks[PHASE]) || [],
    pid: pid,
    worker_id: (window.PROD && PROD.workerId) || "",
  });
  if (r.kind === "blocked") return { kind: "blocked", reason: r.reason };
  if (r.kind === "ok") {
    if (PHASE_GROUPS.indexOf(r.group) < 0) {
      return { kind: "fail", why: "名簿の集団が読めない(" + r.group + ")" };
    }
    return { kind: "ok", j: { group: r.group, assign_index: r.assign_index } };
  }
  return { kind: "fail", why: r.why || "名簿に問い合わせられない" };
}

// 基盤を選んで1回問い合わせる。
function rosterQueryOnceVia(backend, pid) {
  return (backend === "firestore") ? rosterQueryOnceFirestore(pid) : rosterQueryOnce(pid);
}

// 直近の問い合わせの様子。研究者向けの表示と、記録の assign_source に使う。
let rosterTries = 0;
let rosterLastWhy = "";
// 作り直しているあいだ、画面に一言出すための差し込み口。
// 何十秒も「読み込み中…」のままだと、参加者は固まったと思って閉じてしまう。
let onRosterRetry = null;

async function resolveAssignment() {
  const pid = (window.PROD && PROD.participantId) || "anon";
  const researcher = !(window.PROD && PROD.enabled);

  // 研究者モードだけ、集団と連番を URL で強制できる(?group=aprime&pnum=3)。
  if (researcher) {
    const forced = (P.get("group") || "").toLowerCase();
    if (GROUPS[forced]) {
      const pn = Number(P.get(CFG.assignment.pnum_param || "pnum"));
      return { group: forced, assign_index: Number.isFinite(pn) ? Math.abs(Math.trunc(pn)) : hashIndexFrom(pid),
               source: "forced" };
    }
  }
  // 一度決まった割り当ては同じ端末では固定(サーバが落ちていても同じ集団に戻る)。
  const cached = readAssignCache(pid);
  if (cached && PHASE_GROUPS.indexOf(cached.group) >= 0) {
    return { group: cached.group, assign_index: cached.assign_index, source: "cache" };
  }
  // 設定した基盤を順に試す(既定では Firestore → だめなら GAS)。
  // それぞれの基盤の中で、間を空けて何度か作り直す。
  const plan = backendPlan("roster", b => (b === "firestore") ? firestoreReady() : gasRosterReady());
  if (plan.length) {
    const rc = ROSTER.retry || {};
    const attempts = Math.max(1, Number(rc.attempts) || 1);
    const total = attempts * plan.length;
    rosterTries = 0;
    rosterLastWhy = "";
    for (const step of plan) {
      for (let i = 0; i < attempts; i++) {
        if (rosterTries > 0) await sleep(backoffMs(rc, i - 1));
        rosterTries++;
        if (rosterTries > 1 && typeof onRosterRetry === "function") onRosterRetry(rosterTries, total);
        const res = await rosterQueryOnceVia(step.backend, pid);
        if (res.kind === "ok") {
          const a = { group: res.j.group, assign_index: Number(res.j.assign_index) || 0 };
          writeAssignCache(pid, a);
          if (rosterTries > 1) {
            console.warn(`[transfer] 名簿への問い合わせは ${rosterTries} 回目(${step.backend})で成功しました`);
          }
          // どの基盤で・何回目に通ったかを記録に残す
          // (列を増やさずに済むよう assign_source に書く)。
          return Object.assign(a, { source: sourceLabel(step, i + 1) });
        }
        // 断られたのは「サーバが答えた結果」なので、作り直しても結論は変わらない。
        if (res.kind === "blocked") return { blocked: true, reason: res.reason };
        rosterLastWhy = res.why;
        console.warn(`[transfer] 名簿(${step.backend})への問い合わせ ${i + 1}/${attempts} 回目が失敗: ${res.why}`);
      }
      if (plan.length > 1 && step === plan[0]) {
        console.warn(`[transfer] ${step.backend} がだめだったので、もう一方の基盤に切り替えます`);
      }
    }
    console.warn(`[transfer] 名簿へ ${total} 回問い合わせて、すべて失敗しました`);
    // サーバが答えないとき: 名簿の照合はできないが、課題は続けられるようにする。
    // (重複参加の除外は、あとから回答データの参加者IDを突き合わせて行う。)
    if (ROSTER.require_server) {
      return { blocked: true, reason: "server_unavailable", why: rosterLastWhy, tries: total };
    }
  }
  const h = hashIndexFrom(pid);
  const a = { group: PHASE_GROUPS[h % PHASE_GROUPS.length], assign_index: Math.floor(h / PHASE_GROUPS.length) };
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
// prod_common.js の SUBMIT_URL は実験1(乙課題・frac課題)と共用なので、**空のまま
// 触らない**。そこを埋めると既存の実験の保存先まで動いてしまうため。
// 転写検証だけの保存先は設定ファイル(logging.submit_url)に持たせてある。
// 封筒の形は prod_common.js の post() が組むものと同じにそろえる(GAS 側の列が
// そのまま埋まるようにするため)。prod_common.js が外に見せていない3つの値
// (再生機器の申告・再開回数・中断していた合計秒)は、下の2か所で同じ規則で作り直す。
let audioDeviceAnswer = "";                 // 同意画面での再生機器の申告(聴覚の集団のみ)
let resumeMeta = { count: 0, gapS: 0 };     // 途中再開の回数と、中断していた合計秒

function serverBody(body) {
  return Object.assign({
    participant_id: (window.PROD && PROD.participantId) || "",
    worker_id: (window.PROD && PROD.workerId) || "",
    completion_code: (window.PROD && PROD.completionCode) || "",
    ts: Date.now(),
    audio_device: audioDeviceAnswer,
    resume_count: resumeMeta.count,
    resume_gap_s: resumeMeta.gapS,
    ua: ENV.ua, dpr: ENV.dpr, screen: ENV.screen, touch: !!ENV.touch,
    refresh_hz: (ENV.refreshHz != null) ? ENV.refreshHz : "",
    // 試し打ちの目印。Firestore へ入れるときは transfer_firestore.js が同じ値を
    // 付け直すが、GAS へ回ったときのためにここでも載せておく。
    is_test: isTestRun(),
  }, body);
}

// 封筒を保存先へ渡す。名簿の問い合わせと同じ一過性の失敗に備えて、
// **間を空けて作り直す**。それでもだめなら、もう一方の基盤へ回す。
//
// 2つの基盤の違い(ここが移行の要点):
//   Firestore … REST を直接叩く。**応答が読めるので「入ったか」がその場で分かる**
//   GAS       … no-cors で投げっぱなし。判断できるのは「送信そのものが失敗したか」
//               だけで、サーバ側で落ちた場合はここでは分からない
let sendFailures = 0;      // 最後まで送れなかった件数(研究者向けの表示に使う)
let sendRetries = 0;       // 作り直して送れた件数

// 1回ぶんの送信。例外は投げず {ok, why} を返す。
function sendOnce(backend, envelope) {
  if (backend === "firestore") {
    return FSTORE.submitRecord(envelope)
      .then(r => (r.kind === "ok") ? { ok: true } : { ok: false, why: r.why });
  }
  const url = (CFG.logging && CFG.logging.submit_url) || "";
  if (!url) return Promise.resolve({ ok: false, why: "GAS の送信先が空" });
  // GAS は許可の事前確認(preflight)が要らない text/plain で受ける。
  return fetch(url, {
    method: "POST", mode: "no-cors",
    headers: { "Content-Type": "text/plain;charset=utf-8" },
    body: JSON.stringify(envelope),
  }).then(() => ({ ok: true }))
    .catch(e => ({ ok: false, why: (e && e.message) || "送信できない" }));
}

async function deliverRecord(envelope) {
  const plan = backendPlan("logging", b => (b === "firestore") ? firestoreReady() : gasLoggingReady());
  if (!plan.length) {
    console.warn("[transfer] 記録の送信先が1つも設定されていないので記録が残りません");
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
        if (tries > 1) {
          sendRetries++;
          console.warn(`[transfer] 記録の送信は ${tries} 回目(${step.backend})で通りました`);
        }
        // 見極め期間だけの二重書き込み。両方に同じ件数が入るかを確かめるためのもので、
        // 常用はしない(GAS の同時実行30本の上限に当たるため)。失敗しても無視する。
        if (BACKEND.dual_write_logging) {
          const other = (step.backend === "firestore") ? "gas" : "firestore";
          const ready = (other === "firestore") ? firestoreReady() : gasLoggingReady();
          if (ready) sendOnce(other, envelope).catch(() => {});
        }
        return true;
      }
      console.warn(`[transfer] 記録の送信(${step.backend}) ${i + 1}/${attempts} 回目が失敗: ${r.why}`);
    }
  }
  sendFailures++;
  console.error(`[transfer] 記録を ${tries} 回試して送れませんでした(この1問は失われます)`);
  return false;
}

// 1レコードを設定ファイルの保存先へ渡す。研究者モード(?prod なし)では渡さない。
// **戻り値は「入ったか」の Promise<boolean>**。1問1行の記録は待たずに投げてよいが、
// 完走レコード(sendSessionRecord)のように「入ったことを確かめてから次へ進みたい」
// 呼び出しがあるので、必ず Promise を返す形にしてある。
function sendRecord(body) {
  if (!(window.PROD && PROD.enabled)) return Promise.resolve(true);
  return deliverRecord(serverBody(body));
}

// ---- 完走レコード（1セッション1行） ----------------------------------------
// **承認の判定をこの1行だけで済ませるためのもの。** 参加者が最後の画面
// （完了コードが出る画面）に到達したときに1行だけ送る。
//   ・completion_code … 参加者が募集サイトの回答欄に貼る12桁。これで照合する
//   ・n_trials        … その人が答えた問題数（練習を除く）
//   ・duration_s      … 同意画面から完了コードまでの秒数
//   ・send_failures   … 最後まで送れなかった記録の件数（0 なら取りこぼし無し）
//   ・send_retries    … 作り直して送れた件数（サーバの調子を後から見るため）
// 1問1行の記録（transfer_trials）は途中で落ちうるので、「完走したか」を
// そちらの行数から推定すると、通信が悪かった人を非承認にしてしまう。
//
// 置き場所は既存の transfer_wellbeing コレクション。**record_kind 列で見分ける**
// （"session" = この完走レコード / "" = 従来の見え心地の回答）。
// 新しいコレクションを作るとルールの置き直し（firebase deploy）が要るので避けた。
function sessionRecord(durS, nTrials) {
  return {
    kind: "transfer_wellbeing",
    record_kind: "session",
    modality: "transfer_session",
    phase: PHASE, group: GROUP,
    assign_index: ASSIGN, assign_source: ASSIGN_SOURCE,
    n_trials: nTrials,
    duration_s: durS,
    send_failures: sendFailures,
    send_retries: sendRetries,
    version: VERSION, config_version: CFG.config_version,
  };
}

// ---- 回答のかな表 ---------------------------------------------------------
const GRID = CFG.answer_grid;
const ALL_KANA = GRID.flat().filter(c => c !== "");
const N_CHOICES = ALL_KANA.length;
const TARGETS = CFG.targets.slice();
const FILLERS = (CFG.fillers && CFG.fillers.length)
  ? CFG.fillers.slice()
  : ALL_KANA.filter(c => TARGETS.indexOf(c) < 0);
function kanaLabel(ch) { return (CFG.homophone_label && CFG.homophone_label[ch]) || ch; }

const screenEl = document.getElementById("screen");

// ---- 小道具 ---------------------------------------------------------------
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
function pick(a) { return a[Math.floor(Math.random() * a.length)]; }
function gatesFor(table, ch) {
  const t = (table && table[ch]) ? table[ch] : (table && table._default) || [];
  return t.slice();
}

// =========================================================================
// 聴覚: 刺激の読み込みと再生
// =========================================================================
let audioCtx = null;
function ensureCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

// 事前生成した打ち切り済みWAVの索引。tools/build_transfer_gates.py の出力。
//   {"fade_out_ms":5, "items": {"<かな>|<gate_ms>": {"file":"...wav","char":"あ","gate_ms":60,...},
//                               "<かな>|full":      {...}}}
let audioManifest = null;
let audioFallback = null;     // {onsets: {かな: {acoustic_onset_ms}}}  代用モードのとき
const bufCache = {};          // "かな|gate" → AudioBuffer

function audioKey(ch, gateMs) { return ch + "|" + (gateMs === null ? "full" : String(gateMs)); }

// 代用モード(本番刺激が揃うまで): 元の音声をブラウザ側で切る。
// 切り出しは事前生成スクリプトと同じ規則: onset を 0ms とし、t ms で切り、
// 終端の 5ms を余弦で 1→0 に落とす(ランプ区間は [t-5ms, t])。
function cutBuffer(buf, onsetMs, gateMs) {
  const sr = buf.sampleRate;
  const src = buf.getChannelData(0);
  const start = Math.max(0, Math.round(onsetMs / 1000 * sr));
  const want = (gateMs === null) ? (src.length - start) : Math.round(gateMs / 1000 * sr);
  const len = Math.max(1, Math.min(want, src.length - start));
  const out = ensureCtx().createBuffer(1, len, sr);
  const d = out.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = src[start + i] || 0;
  const fade = Math.min(Math.round(sr * CFG.audio.fade_out_ms / 1000), len);
  for (let i = 0; i < fade; i++) {
    // 余弦フェード: 区間の先頭で 1、終端で 0。
    const w = 0.5 * (1 + Math.cos(Math.PI * (i + 1) / fade));
    d[len - fade + i] *= w;
  }
  return out;
}

async function fetchBuffer(url) {
  const r = await fetch(url, { cache: "force-cache" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return await ensureCtx().decodeAudioData(await r.arrayBuffer());
}

// 1つの刺激(かな × 打ち切り時刻)の音を用意する。gateMs=null は打ち切りなし(全長)。
// 同じ刺激を2度取りに行かないよう、キャッシュには**約束(Promise)そのもの**を入れる
// (先読みと本番の再生が同時に同じファイルを要求しても、通信は1回で済む)。
function loadStim(ch, gateMs) {
  const key = audioKey(ch, gateMs);
  if (!bufCache[key]) {
    bufCache[key] = (async () => {
      if (audioManifest) {
        const item = audioManifest.items[key];
        if (!item) throw new Error("刺激が見つかりません: " + key);
        // ファイル名にかなが入る(あ_g0020.wav)。base/<かな>.png と同じく明示的に
        // パーセント符号化する(自動符号化に任せると環境差が出るため)。
        return await fetchBuffer(CFG.audio.stimuli_dir + "/" + encodeURIComponent(item.file));
      }
      // 代用モード: 元ファイルを1度だけ読み、必要な長さに切って使い回す。
      const rawKey = ch + "|raw";
      if (!bufCache[rawKey]) {
        bufCache[rawKey] = fetchBuffer(
          CFG.audio.fallback.dir + "/" + encodeURIComponent(ch) + CFG.audio.fallback.ext);
      }
      const raw = await bufCache[rawKey];
      const on = (audioFallback && audioFallback.onsets && audioFallback.onsets[ch]
                  && audioFallback.onsets[ch].acoustic_onset_ms);
      const onsetMs = (typeof on === "number") ? on : CFG.audio.fallback.default_onset_ms;
      return cutBuffer(raw, onsetMs, gateMs);
    })();
  }
  return bufCache[key];
}
// 出題が決まったあと、使う音を裏で先に取ってくる(1問目の待ち時間を作らないため)。
function prefetchStims(list) {
  const seen = {};
  list.forEach(t => {
    if (t.mod !== "audio") return;
    const key = audioKey(t.char, t.gate_ms);
    if (seen[key]) return;
    seen[key] = true;
    loadStim(t.char, t.gate_ms).catch(() => {});
  });
}

let _nodes = [];
function stopAll() { for (const n of _nodes) { try { n.stop(); } catch (e) {} } _nodes = []; }
function playBeep(when) {
  const ctx = ensureCtx();
  const osc = ctx.createOscillator(); const g = ctx.createGain();
  osc.type = "sine"; osc.frequency.value = CFG.audio.beep_hz;
  osc.connect(g); g.connect(ctx.destination);
  g.gain.setValueAtTime(0.0001, when);
  g.gain.exponentialRampToValueAtTime(0.12, when + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, when + CFG.audio.beep_ms / 1000);
  osc.start(when); osc.stop(when + CFG.audio.beep_ms / 1000 + 0.02);
  _nodes.push(osc);
}
// 合図音「ピッ」→ beep_lead_ms → 刺激 →(end_gap_ms)→「ピッピッ」。
// 無線イヤホンは鳴り始めの数十msが欠けるので、刺激の前に必ず合図音を置く。
function playStim(buf) {
  const ctx = ensureCtx();
  stopAll();
  const t0 = ctx.currentTime + 0.02;
  playBeep(t0);
  const stimStart = t0 + CFG.audio.beep_lead_ms / 1000;
  if (buf && buf.duration > 0) {
    const s = ctx.createBufferSource();
    s.buffer = buf; s.connect(ctx.destination); s.start(stimStart);
    _nodes.push(s);
  }
  const endAt = stimStart + (buf ? buf.duration : 0) + CFG.audio.end_gap_ms / 1000;
  playBeep(endAt);
  playBeep(endAt + CFG.audio.end_beep_gap_ms / 1000);
  return CFG.audio.beep_lead_ms;   // 合図音から刺激開始までの間(反応時間の起点合わせ用)
}

// =========================================================================
// 視覚: 4方式の描画器
//   どれも「進み具合 s∈[0,1] を渡すと1フレーム描く」という同じ形にそろえてある。
//     draw(ctx, ch, s)  … s の状態を1枚描く
//     begin(ch)         … 1試行の描画を始める前の準備(部分表示の内部状態の初期化など)
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
function drawFix(ctx) {
  drawBlank(ctx);
  ctx.fillStyle = "#333"; ctx.font = "40px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("+", SIZE / 2, SIZE / 2);
}

// 部分表示(reveal)用: 字ごとに固定した乱数順のストローク画素の並び。
// 既存資産(generate.py / README.md「マスキング手法」)と同じ考え方だが、
// 101段階の画像には依存せず、その場で並びを作って任意の s を描けるようにした。
// 乱数の並びは Python の random.Random とは別物になるが、**字ごとに固定**であれば
// 実験の要件(同じ字はいつも同じ順で現れる)は満たす。
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
function wipeDraw(ctx, ch, s) {
  const p = Math.max(0, Math.min(1, s));
  drawBlank(ctx);
  if (!imgs[ch] || p <= 0) return;
  const dir = CFG.visual.families.wipe.direction || "ltr";
  const w = SIZE * p, h = SIZE * p;
  ctx.save();
  ctx.beginPath();
  if (dir === "ltr") ctx.rect(0, 0, w, SIZE);
  else if (dir === "rtl") ctx.rect(SIZE - w, 0, w, SIZE);
  else if (dir === "ttb") ctx.rect(0, 0, SIZE, h);
  else ctx.rect(0, SIZE - h, SIZE, h);
  ctx.clip();
  ctx.drawImage(imgs[ch], 0, 0, SIZE, SIZE);
  ctx.restore();
}

// フェード(fade): 不透明度 = s^gamma。
// gamma は「進み具合を画面の濃さにどう配るか」のつまみ(transfer_config.js の
// visual.families.fade.gamma)。**既定の 1.0 では濃さ = s** となり、
// 既存の1文字課題と同じ挙動になる。1.0 より大きくすると序盤を薄めに通せる。
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
  wipe:   { begin: () => {},                     draw: wipeDraw },
};

// =========================================================================
// 視覚: 進み方 s(t)
//   較正(群A′)は等速。検証(群B)は生成した数値列(60Hz)を線形補間してなぞる。
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

// 1試行ぶんの「経過時間ms → 進み具合 s」を作る。
// 返り値: {fn, source} source は記録用("table" / "linear" / "affine")。
// その試行の基準アニメの長さ。RQ4 の速さ2水準では試行ごとに違うので、
// 設定の既定値ではなく試行に書かれた値を使う(書かれていなければ既定値)。
function baseAnimMs(t) {
  return (t && typeof t.base_anim_ms === "number") ? t.base_anim_ms : CFG.visual.base_anim_ms;
}

function progressFn(t) {
  if (t.play === "calib" || t.condition === "calib") {
    const base = baseAnimMs(t);
    return { fn: (ms) => Math.max(0, Math.min(1, ms / base)), source: "linear" };
  }
  const series = warpSeries(t.family, t.char, t.condition);
  if (series) {
    const frameMs = (warpTables && warpTables.frame_ms) || (1000 / 60);
    return { fn: (ms) => Math.max(0, Math.min(1, seriesAt(series, frameMs, ms))), source: "table" };
  }
  // 表が無いとき(生成前・研究者の動作確認)。
  if (t.condition === "baseline2") {
    const a = CFG.visual.warp.fallback_affine.a, b = CFG.visual.warp.fallback_affine.b;
    return { fn: (ms) => Math.max(0, Math.min(1, a * ms + b)), source: "affine" };
  }
  const base = baseAnimMs(t);
  return { fn: (ms) => Math.max(0, Math.min(1, ms / base)), source: "linear" };
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

async function preload() {
  screenEl.innerHTML = `<div style="min-height:60vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">読み込み中…</h1>
    <div style="width:min(320px,80%);height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden;margin-top:10px">
      <div id="loadBar" style="height:100%;width:0%;background:#2E7D8F"></div></div></div>`;
  const setBar = (p) => { const b = document.getElementById("loadBar"); if (b) b.style.width = Math.round(p * 100) + "%"; };

  if (G.mode === "audio") {
    // 打ち切り済みWAVの索引。無ければ代用モード(研究者の動作確認用)。
    try {
      const r = await fetch(CFG.audio.manifest_url, { cache: "no-store" });
      if (r.ok) audioManifest = await r.json();
    } catch (e) { /* 代用モードへ */ }
    if (!audioManifest) {
      if (!CFG.audio.fallback.enabled) throw new Error(CFG.audio.manifest_url + " が読めません");
      audioFallback = { onsets: {} };
      try {
        const r = await fetch(CFG.audio.fallback.onsets_url, { cache: "no-store" });
        if (r.ok) audioFallback.onsets = await r.json();
      } catch (e) { /* onset が無ければ既定値を使う */ }
      console.warn("[transfer] 本番の打ち切り刺激が無いため代用モードで動かします(データ取得には使わないこと)");
    }
    setBar(1);
    return;
  }
  // 視覚: 画面に出しうる字の画像を全部読む(まぎれ字を含む)。
  const chars = ALL_KANA;
  let done = 0;
  await Promise.all(chars.map(async ch => {
    try { imgs[ch] = await loadImage(ch); } catch (e) { /* 無い字はまぎれ字から外れるだけ */ }
    done++; setBar(done / chars.length);
  }));
  if (!TARGETS.every(ch => imgs[ch])) throw new Error("ターゲット字の画像が読めません");
  // 生成した進み方の表(あれば)。群Bのみ必要。
  if (G.play === "warp" || (G.wellbeing && CFG.wellbeing.condition === "proposed")) {
    try {
      const r = await fetch(CFG.visual.warp.tables_url, { cache: "no-store" });
      if (r.ok) warpTables = await r.json();
    } catch (e) { /* 表が無ければ代用の進み方(progressFn 参照) */ }
    if (!warpTables) console.warn("[transfer] " + CFG.visual.warp.tables_url + " が無いので代用の進み方で動かします");
  }
}

// =========================================================================
// 出題の組み立て
// =========================================================================
// 確認問題を混ぜる。full = 打ち切りなし(操作チェックA)、floor = 最小の時点(操作チェックC)。
function addChecks(list, makeFull, makeFloor) {
  const nFull = Math.round(list.length * CFG.design.check_full_rate);
  const nFloor = Math.round(list.length * CFG.design.check_floor_rate);
  for (let i = 0; i < nFull; i++) list.push(makeFull());
  for (let i = 0; i < nFloor; i++) list.push(makeFloor());
  return list;
}

// 聴覚(群Acal / 群Atest): ターゲット8字 × 時点。まぎれ字と確認問題を混ぜる。
function buildAudioTrials() {
  let cells = [];
  for (let rep = 0; rep < CFG.design.reps; rep++) {
    TARGETS.forEach(ch => {
      audioGates(ch).forEach(g => {
        cells.push({ mod: "audio", char: ch, gate_ms: g, is_filler: false, check_kind: "" });
      });
      // 「打ち切りなし(全長)」をその字の1点として足す(transfer_config.js の
      // audio.include_full_gate)。時点を字ごとに置くようにしたので、曲線の天井が
      // 取れているかも字ごとに確かめられるようにしておく。
      if (CFG.audio.include_full_gate) {
        cells.push({ mod: "audio", char: ch, gate_ms: null, is_filler: false, check_kind: "" });
      }
    });
  }
  cells = shuffle(cells);
  if (MAX_TARGET_TRIALS > 0) cells = cells.slice(0, MAX_TARGET_TRIALS);
  const nFiller = Math.round(cells.length * CFG.design.filler_ratio);
  const fillerGates = audioGates("_default");
  for (let i = 0; i < nFiller; i++) {
    cells.push({ mod: "audio", char: pick(FILLERS), gate_ms: pick(fillerGates), is_filler: true, check_kind: "" });
  }
  addChecks(cells,
    () => ({ mod: "audio", char: pick(TARGETS), gate_ms: null, is_filler: false, check_kind: "full" }),
    // 確認問題C(ほとんど情報のない問題)は、**その字にとっていちばん早い時点**を使う。
    // 時点を字ごとに置くようにしたので、全字共通の最小値(20ms)を当てると、
    // その字の表に無い刺激を要求してしまう(例: し は 30ms から始まる)。
    () => { const ch = pick(TARGETS);
            return { mod: "audio", char: ch, gate_ms: Math.min(...audioGates(ch)),
                     is_filler: false, check_kind: "floor" }; });
  return shuffle(cells);
}

// 視覚(群A′ / 群B)。1人の参加者は、1つの字を1つの方式(群B は1つの条件)でだけ見る。
// どの字にどれを当てるかは参加者の連番から決める(釣り合いは集団全体で取る)。
function comboForChar(charIndex) {
  if (GROUP === "aprime") {
    const fams = CFG.assignment.aprime_families;
    return { family: fams[(charIndex + ASSIGN) % fams.length], condition: "calib" };
  }
  const conds = CFG.conditions;
  const step = CFG.assignment.b_step || 1;
  return conds[(charIndex * step + ASSIGN) % conds.length];
}

// 聴覚で使う打ち切り時刻ms。下見のあいだだけ、設定で足した早い時点を混ぜる
// (transfer_config.js の audio.pilot_extra_gates)。切ってあれば本体の表のまま。
// 生成(warp)の材料にするのは gates_ms 本体の時点だけで、足した時点は床を見るためのもの。
function audioGates(ch) {
  const base = gatesFor(CFG.audio.gates_ms, ch);
  const ex = CFG.audio.pilot_extra_gates;
  if (!(ex && ex.enabled && ex.gate_ms && ex.gate_ms.length)) return base;
  return [...new Set([...base, ...ex.gate_ms])].sort((a, b) => a - b);
}

// RQ4 の測定(transfer_config.js の visual.calib_speed_probe)。
// 群A′の決められた方式(既定はフェード)にかぎり、基準アニメの速さを2通り出して
// 「同じ進み具合 s でも、そこへ着くまでの速さで正答率が変わるか」を測る。
// 較正フェーズのあいだはずっと入れておく(下見は予備・本番の群A′が本答え)。
// 生成(warp)に使う視覚の曲線は generation_level_ms の水準だけと事前に決めてあり、
// もう一方の水準は RQ4 に答えるためだけに使う(計画書 3章 RQ4・6.1)。
// 設定を切ると speedsFor は必ず1要素(既定の速さ)を返すので、挙動は元どおりになる。
// 視覚較正で使う打ち切り水準%。下見のあいだだけ、設定で足した薄い水準を混ぜる
// (transfer_config.js の visual.pilot_extra_levels)。切ってあれば本体の並びのまま。
function progressLevels() {
  const base = CFG.visual.progress_pct_levels.slice();
  const ex = CFG.visual.pilot_extra_levels;
  if (!(ex && ex.enabled && ex.progress_pct && ex.progress_pct.length)) return base;
  const set = new Set(base);
  ex.progress_pct.forEach(v => set.add(v));
  return [...set].sort((a, b) => a - b);
}

function speedProbe() {
  const p = CFG.visual.calib_speed_probe;
  return (p && p.enabled && p.base_anim_ms_levels && p.base_anim_ms_levels.length > 1) ? p : null;
}
function speedsFor(family) {
  const p = speedProbe();
  if (!p || GROUP !== "aprime" || family !== p.family) return [CFG.visual.base_anim_ms];
  return p.base_anim_ms_levels.slice();
}

function buildVisualTrials() {
  let cells = [];
  for (let rep = 0; rep < CFG.design.reps; rep++) {
    TARGETS.forEach((ch, i) => {
      const c = comboForChar(i);
      if (GROUP === "aprime") {
        // 速さの水準ぶんだけ繰り返す(RQ4 の測定を切ってあれば1通りだけ)。
        speedsFor(c.family).forEach(baseMs => {
          progressLevels().forEach(pct => {
            cells.push({ mod: "visual", play: "calib", char: ch, family: c.family, condition: "calib",
                         progress_pct: pct, gate_ms: null, is_filler: false, check_kind: "",
                         base_anim_ms: baseMs });
          });
        });
      } else {
        gatesFor(CFG.visual.gates_ms, ch).forEach(g => {
          cells.push({ mod: "visual", play: "warp", char: ch, family: c.family, condition: c.condition,
                       progress_pct: null, gate_ms: g, is_filler: false, check_kind: "" });
        });
      }
    });
  }
  cells = shuffle(cells);
  if (MAX_TARGET_TRIALS > 0) cells = cells.slice(0, MAX_TARGET_TRIALS);

  // まぎれ字。方式・条件は、その参加者が担当している組合せから借りる
  // (まぎれ字だけ見え方が違うと「これは本命ではない」と気づかれるため)。
  const combos = TARGETS.map((_, i) => comboForChar(i));
  const gateList = gatesFor(CFG.visual.gates_ms, "_default");
  const nFiller = Math.round(cells.length * CFG.design.filler_ratio);
  for (let i = 0; i < nFiller; i++) {
    const c = pick(combos);
    const ch = pick(FILLERS.filter(x => imgs[x]));
    if (GROUP === "aprime") {
      // まぎれ字の速さも本命と同じ集合から選ぶ(まぎれ字だけいつも同じ速さだと、
      // 速さの違いが「本命かどうか」の手がかりになってしまうため)。
      cells.push({ mod: "visual", play: "calib", char: ch, family: c.family, condition: "calib",
                   progress_pct: pick(progressLevels()), gate_ms: null, is_filler: true, check_kind: "",
                   base_anim_ms: pick(speedsFor(c.family)) });
    } else {
      cells.push({ mod: "visual", play: "warp", char: ch, family: c.family, condition: c.condition,
                   progress_pct: null, gate_ms: pick(gateList), is_filler: true, check_kind: "" });
    }
  }
  // 確認問題。full は打ち切りなし(進み具合が1に届くまで見せる)。floor は最小の時点。
  const minGate = Math.min(...gateList);
  const minPct = Math.min(...progressLevels());
  const mk = (kind) => {
    const i = Math.floor(Math.random() * TARGETS.length);
    const c = comboForChar(i);
    const base = { mod: "visual", char: TARGETS[i], family: c.family, condition: c.condition,
                   is_filler: false, check_kind: kind };
    if (GROUP === "aprime") {
      // 確認問題は「いつもの速さ」に固定する(操作チェックの基準を1つに保つため)。
      return Object.assign(base, { play: "calib", condition: "calib", gate_ms: null,
                                   progress_pct: kind === "full" ? 100 : minPct,
                                   base_anim_ms: CFG.visual.base_anim_ms });
    }
    return Object.assign(base, { play: "warp", progress_pct: null,
                                 gate_ms: kind === "full" ? null : minGate });
  };
  addChecks(cells, () => mk("full"), () => mk("floor"));
  return shuffle(cells);
}

// 練習(記録しない・何度でも)。よく分かる条件で出す。
function buildTryout() {
  if (G.mode === "audio") {
    return { mod: "audio", char: pick(TARGETS), gate_ms: null, is_filler: false, check_kind: "", practice: true };
  }
  const i = Math.floor(Math.random() * TARGETS.length);
  const c = comboForChar(i);
  if (GROUP === "aprime") {
    return { mod: "visual", play: "calib", char: TARGETS[i], family: c.family, condition: "calib",
             progress_pct: 100, gate_ms: null, is_filler: false, check_kind: "", practice: true };
  }
  return { mod: "visual", play: "warp", char: TARGETS[i], family: c.family, condition: c.condition,
           progress_pct: null, gate_ms: null, is_filler: false, check_kind: "", practice: true };
}

// =========================================================================
// 画面
// =========================================================================
let trials = [], results = [], ti = 0;
let resumeState = null, elapsedPrior = 0;
let introduced = false;        // 1問目だけ丁寧な文言・長めの間
let tried = 0, tryReturn = null;
let wellbeingAnswers = null;   // 群Bの見え心地評価
const T0 = Date.now();
const SESSION_V = 1;           // 途中データの互換版。構造を変えたら上げる。

function mainDone() { return results.filter(r => !r.practice).length; }
function nMain() { return trials.filter(t => !t.practice).length; }

function progressHeader(t) {
  if (t.practice) return `<div class="muted">練習</div>`;
  const pct = nMain() ? Math.round(mainDone() / nMain() * 100) : 0;
  return `<div class="muted" style="display:flex;align-items:center;gap:10px">
    <span style="white-space:nowrap">${G.task_label}</span>
    <span style="flex:1;height:8px;background:#e3e6ee;border-radius:4px;overflow:hidden"><span style="display:block;height:100%;width:${pct}%;background:#2E7D8F"></span></span>
    <span style="white-space:nowrap">${pct}%</span></div>`;
}

// かな表(紙の五十音表式・右寄せ)。聴覚・視覚で同じ表を使う。
function buildKanaGrid(done) {
  const splitAt = CFG.answer_grid_split_at;
  const grid = document.createElement("div"); grid.id = "grid"; grid.style.display = "block";
  const blocks = [GRID.slice(0, splitAt), GRID.slice(splitAt)].filter(b => b.length);
  const maxCols = Math.max(...blocks.map(b => b.length));
  for (const rowsBlock of blocks) {
    const cols = [...rowsBlock].reverse();
    const pad = maxCols - cols.length;
    const g = document.createElement("div");
    g.className = "kblock";
    g.style.gridTemplateColumns = `repeat(${maxCols},1fr)`;
    for (let dan = 0; dan < 5; dan++) {
      for (let k = 0; k < pad; k++) { const s = document.createElement("div"); s.className = "kana spacer"; g.appendChild(s); }
      for (const col of cols) {
        const ch = col[dan] || "";
        if (!ch) { const s = document.createElement("div"); s.className = "kana spacer"; g.appendChild(s); continue; }
        const b = document.createElement("button"); b.className = "kana";
        b.textContent = kanaLabel(ch);
        if (b.textContent.length > 1) b.classList.add("multi");   // 「お／を」などの併記
        b.onclick = () => done(ch); g.appendChild(b);
      }
    }
    grid.appendChild(g);
  }
  // 画面に置いたあとで、視口の残りの高さから1マスの大きさを決める。
  requestAnimationFrame(() => fitKanaGrid(grid));
  return grid;
}

// かな表を画面内に収める(スクロールさせない)。
// 表の上端から画面の下までの残りを段の数で割って1マスの高さにし、文字とすき間も
// それに合わせる。**並び(紙の五十音表と同じ配置)は変えない**。
// 段の数 = 5段 × ブロック数(上=清音、下=濁音・半濁音)。
const KANA_ROWS_PER_BLOCK = 5;
const KANA_CELL_MIN = 18, KANA_CELL_MAX = 40;   // 1マスの高さの下限・上限(px)
function fitKanaGrid(grid) {
  if (!grid || !grid.parentNode) return;
  const blocks = grid.querySelectorAll(".kblock").length;
  if (!blocks) return;
  const rows = blocks * KANA_ROWS_PER_BLOCK;
  const rowGaps = blocks * (KANA_ROWS_PER_BLOCK - 1);
  const avail = window.innerHeight - grid.getBoundingClientRect().top - 8;  // 8px=下端に残す余白
  const solve = (gap, blockGap) => Math.floor((avail - blocks * blockGap - rowGaps * gap) / rows);
  // すき間もマスの大きさに応じて詰める(狭い画面ほど小さく)。
  const rough = solve(6, 14);
  const gap = rough >= 30 ? 6 : rough >= 24 ? 4 : 3;
  const blockGap = rough >= 30 ? 14 : rough >= 24 ? 10 : 6;
  const cell = Math.max(KANA_CELL_MIN, Math.min(KANA_CELL_MAX, solve(gap, blockGap)));
  grid.style.setProperty("--kana-cell-h", cell + "px");
  grid.style.setProperty("--kana-font", Math.max(11, Math.min(19, Math.round(cell * 0.55))) + "px");
  grid.style.setProperty("--kana-gap", gap + "px");
  grid.style.setProperty("--kana-block-gap", blockGap + "px");
}
// 画面の大きさ・向きが変わったら測り直す(窓の変更・スマートフォンの回転)。
window.addEventListener("resize", () => fitKanaGrid(document.getElementById("grid")));
window.addEventListener("orientationchange",
  () => setTimeout(() => fitKanaGrid(document.getElementById("grid")), 250));

function saveProgress() {
  if (window.PROD && PROD.enabled) PROD.saveState("transfer_" + PHASE,
    { session_v: SESSION_V, phase: PHASE, group: GROUP, trials, results, ti, assign: ASSIGN,
      wellbeing: wellbeingAnswers, wb_idx: wbIdx, wb_clips: wbClips,
      elapsed_s: Math.round(elapsedPrior + (Date.now() - T0) / 1000) });
}

// 1問ぶんの記録。列は gas/transfer_patch.md の表に対応する。
function makeRecord(t, picked, extra) {
  return Object.assign({
    // 採点(GAS): target_char を client が申告する方式(視覚1文字課題と同じ契約)。
    stimulus_id: `${GROUP}|${t.char}|${t.family || "audio"}|${t.condition || ""}|${t.gate_ms === null ? "full" : t.gate_ms}`,
    target_char: t.char,
    response_char: picked,
    modality: t.mod === "audio" ? CFG.logging.modality_audio : CFG.logging.modality_visual,
    q_set: "transfer",
    // 転写検証で足した列。
    phase: PHASE,
    group: GROUP,
    assign_source: ASSIGN_SOURCE,
    family: t.family || "",
    condition: t.condition || "",
    gate_ms: (t.gate_ms === null || t.gate_ms === undefined) ? "" : t.gate_ms,
    progress_pct: (t.progress_pct === null || t.progress_pct === undefined) ? "" : t.progress_pct,
    is_filler: !!t.is_filler,
    check_kind: t.check_kind || "",
    is_catch: t.check_kind === "full",       // 既存の列に合わせる(全部見せ・全部聞かせ)
    trial_index: mainDone() + 1,             // 何問目か(学習の検出用・練習は数えない)
    assign_index: ASSIGN,
    n_choices: N_CHOICES,
    replays: 0,                              // 1回だけ提示(聞き直し・見直しなし)
    version: VERSION,
    config_version: CFG.config_version,
  }, extra);
}

function finalizeCommon(t, rec, picked) {
  if (!t.practice) {
    results.push(rec);
    // saveFracTrial は Firestore への控えだけ(prod_common.js の SUBMIT_URL は空)。
    // GAS への保存は sendRecord がこの実験専用の窓口へ行う。
    if (window.PROD) PROD.saveFracTrial(rec);
    sendRecord(rec);
    ti++; saveProgress(); runTrial(); return;
  }
  results.push(Object.assign({ practice: true }, rec));
  const ok = picked === t.char;
  screenEl.innerHTML = `<div style="text-align:center;padding:30px">
    <p style="font-size:17px">正解「<b style="font-size:24px">${kanaLabel(t.char)}</b>」 ／ あなたの答え「<b style="font-size:24px">${picked ? kanaLabel(picked) : "（未選択）"}</b>」
      <span style="color:${ok ? "#2E7D8F" : "#C25B4E"}">${ok ? "◯" : "×"}</span></p>
    <p class="muted">これは練習です。</p></div>`;
  setTimeout(() => { if (tryReturn) tryReturn(); }, 1600);
}

function runTrial() {
  if (ti >= trials.length) return afterTrials();
  const t = trials[ti];
  if (t.mod === "audio") return runAudioTrial(t);
  return runVisualTrial(t);
}

// ---- 聴覚の1問 ------------------------------------------------------------
// 提示は1回だけ(聞き直しボタンは出さない)。回答時間は無制限。
function runAudioTrial(t) {
  let tStim = null, picked = null, pickedRt = null, autoTimer = null;
  screenEl.innerHTML = `${progressHeader(t)}
    <div id="stage">
      <div style="text-align:center;margin:36px 0 12px" id="cue" class="muted">♪</div>
      ${introduced ? "" : `<div class="muted" id="prompt" style="text-align:center">まもなく始まります。</div>`}
      <div id="answerArea"></div>
    </div>`;
  const answerArea = document.getElementById("answerArea");

  const finalize = () => {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    stopAll();
    finalizeCommon(t, makeRecord(t, picked, { rt_ms: pickedRt }), picked);
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
      picked = ch;
      pickedRt = tStim === null ? null : Math.round(performance.now() - tStim);
      showConfirm();
    });
    answerArea.appendChild(grid);
    if (tStim === null) grid.querySelectorAll("button.kana").forEach(b => { b.disabled = true; });
  };
  const play = async () => {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    let buf = null;
    try { buf = await loadStim(t.char, t.gate_ms === undefined ? null : t.gate_ms); }
    catch (e) { console.warn("[transfer] 刺激の読み込みに失敗:", e.message); }
    const lead = playStim(buf);
    // 反応時間の起点は「刺激の音が始まる時点」。合図音のぶんだけ後ろにずらす。
    tStim = performance.now() + lead;
    document.getElementById("grid")?.querySelectorAll("button.kana").forEach(b => { b.disabled = false; });
    const pr = document.getElementById("prompt");
    if (pr) pr.textContent = "聞こえた文字を下の表から選んでください。";
    introduced = true;
  };
  showGrid();
  autoTimer = setTimeout(play, introduced ? CFG.design.auto_start_ms : 1200);
}

// ---- 視覚の1問 ------------------------------------------------------------
// 注視点 ＋ → アニメ(進み具合 s を1フレームずつ描く) → 打ち切って白紙 → 回答。
// 提示は1回だけ(見直しボタンは出さない)。描画フレームの実時刻から実測を取る。
function runVisualTrial(t) {
  let tStim = null, picked = null, pickedRt = null, autoTimer = null;
  let actualMs = null, actualFrames = null, actualS = null, presenting = false;
  const prog = progressFn(t);
  const renderer = RENDERERS[t.family] || RENDERERS.fade;

  screenEl.innerHTML = `${progressHeader(t)}
    <div id="stage">
      <div id="vbox" class="vbox"></div>
      ${introduced ? "" : `<div class="muted" id="prompt" style="text-align:center">中央の ＋ に注目してください。</div>`}
      <div id="answerArea"></div>
    </div>`;
  const answerArea = document.getElementById("answerArea");
  const canvas = newCanvas();
  document.getElementById("vbox").appendChild(canvas);
  const ctx = canvas.getContext("2d");
  drawFix(ctx);

  const finalize = () => {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    finalizeCommon(t, makeRecord(t, picked, {
      rt_ms: pickedRt, actual_ms: actualMs, actual_frames: actualFrames,
      actual_s: actualS === null ? "" : Math.round(actualS * 1000) / 1000,
      // RQ4 の速さ2水準では試行ごとに違う。分析はこの列で2群に分ける
      // (生成に使うのは calib_speed_probe.generation_level_ms の側だけ)。
      progress_source: prog.source, base_anim_ms: baseAnimMs(t),
      refresh_hz: ENV.refreshHz,
    }), picked);
  };
  const showConfirm = () => {
    document.getElementById("grid")?.remove();
    answerArea.innerHTML = `<div style="text-align:center;margin-top:14px">
      <div class="ask" style="font-size:18px;color:#1E2A5E">この回答で決定しますか？</div>
      <div style="font-size:20px;margin:12px 0">あなたの答え「<b>${kanaLabel(picked)}</b>」</div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
        <button id="fixBtn" style="padding:10px 16px;font-size:15px">選び直す</button>
        <button class="primary" id="okBtn" style="background:#1E2A5E">これで決定</button></div></div>`;
    document.getElementById("fixBtn").onclick = showGrid;
    document.getElementById("okBtn").onclick = finalize;
  };
  const showGrid = () => {
    answerArea.innerHTML = "";
    const grid = buildKanaGrid((ch) => {
      picked = ch;
      pickedRt = tStim === null ? null : Math.round(performance.now() - tStim);
      showConfirm();
    });
    answerArea.appendChild(grid);
    if (tStim === null) grid.querySelectorAll("button.kana").forEach(b => { b.disabled = true; });
  };

  const present = () => {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    if (presenting) return;
    presenting = true;
    const fixDur = CFG.visual.fix_ms + Math.floor(Math.random() * CFG.visual.fix_jitter_ms);
    // 打ち切りの決め方: 較正は「進み具合が s% に届いたら」、検証は「t ms 経ったら」。
    const sTarget = (t.play === "calib")
      ? Math.max(0, Math.min(1, (t.progress_pct === null ? 100 : t.progress_pct) / 100)) : null;
    const tCut = (t.play === "calib") ? null : t.gate_ms;   // null = 打ち切りなし(1に届くまで)
    // 打ち切りのない問題(確認問題Aと練習)は、最後の姿を少しのあいだ見せてから消す。
    const isFull = (sTarget !== null) ? (sTarget >= 1) : (tCut === null);
    renderer.begin(t.char, ctx);
    drawFix(ctx);
    const t0 = performance.now();
    let phase = "fix", tOn = 0, frames = 0, lastS = 0;
    const unlock = () => {
      tStim = performance.now();
      document.getElementById("grid")?.querySelectorAll("button.kana").forEach(b => { b.disabled = false; });
      const pr = document.getElementById("prompt");
      if (pr) pr.textContent = "見えた文字を下の表から選んでください。";
      introduced = true;
    };
    const finish = (now) => {
      drawBlank(ctx);
      actualMs = Math.round(now - tOn); actualFrames = frames; actualS = lastS;
      presenting = false;
    };
    function frame(now) {
      if (phase === "fix") {
        if (now - t0 < fixDur) { requestAnimationFrame(frame); return; }
        phase = "char"; tOn = now; frames = 0; unlock();
      }
      const el = now - tOn;
      const s = prog.fn(el);
      // 打ち切り判定は描画の前。時点 t (または水準 s%) を過ぎたフレームは1枚も描かない。
      // したがって実際に見えた最大の進み具合は、狙った水準よりフレーム1枚ぶん
      // (60Hz なら 16.7ms ぶん)だけ手前になる。分析ではこの実測値 actual_s を使うこと
      // (名目の progress_pct / gate_ms も別の列に残してある)。
      if ((tCut !== null && el >= tCut) || (sTarget !== null && s >= sTarget) ||
          (tCut === null && sTarget === null && s >= 1)) {
        if (isFull) {   // 全部見せ: 完成した姿を1枚描いて hold のあいだ残す
          renderer.draw(ctx, t.char, 1); lastS = 1; frames++;
          setTimeout(() => finish(performance.now()), CFG.design.full_hold_ms);
          return;
        }
        finish(now); return;   // 時点 t を過ぎたフレームは1枚も描かない
      }
      renderer.draw(ctx, t.char, s);
      lastS = s; frames++;
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  };
  showGrid();
  autoTimer = setTimeout(present, introduced ? CFG.design.auto_start_ms : 1200);
}

// =========================================================================
// 見え心地の評価(群Bのみ・識別課題が全部終わったあと)
// =========================================================================
function buildWellbeingClips() {
  const out = [];
  CFG.wellbeing.chars.forEach(ch => {
    CFG.wellbeing.families.forEach(fam => out.push({ char: ch, family: fam }));
  });
  return shuffle(out);
}
let wbClips = [], wbIdx = 0;

function wellbeingIntro() {
  screenEl.innerHTML = `<h2 style="color:#1E2A5E">最後に：見え心地についての質問</h2>
    <p>ここからは<b>当てる課題ではありません</b>。文字の現れ方を${wbClips.length}通り続けてお見せします。
    それぞれについて、<b>「字幕として続けて見ていられるか」</b>を答えてください。</p>
    <p class="muted">各${wbClips.length}本は最後まで表示され、途中で消えません。</p>
    <p style="text-align:center;margin-top:18px"><button class="primary" id="wbGo">始める</button></p>`;
  document.getElementById("wbGo").onclick = () => { wbIdx = 0; wellbeingClip(); };
}

// 1本を打ち切りなしで再生 → 7件法3項目。
function wellbeingClip() {
  if (wbIdx >= wbClips.length) return wellbeingChoice();
  const clip = wbClips[wbIdx];
  const t = { mod: "visual", play: "warp", char: clip.char, family: clip.family,
              condition: CFG.wellbeing.condition === "linear" ? "calib" : CFG.wellbeing.condition,
              gate_ms: null, progress_pct: null };
  const prog = progressFn(t);
  const renderer = RENDERERS[clip.family] || RENDERERS.fade;
  screenEl.innerHTML = `<div class="muted">見え心地の質問（${wbIdx + 1} / ${wbClips.length}）</div>
    <div id="vbox" class="vbox"></div>
    <div style="text-align:center;margin:6px 0 10px">
      ${CFG.wellbeing.allow_replay ? `<button id="again" style="font-size:15px;padding:10px 24px;border-radius:999px;border:2px solid #1E2A5E;background:#fff;color:#1E2A5E;cursor:pointer">▶ もう一度みる</button>` : ""}
    </div>
    <div id="wbForm"></div>`;
  const canvas = newCanvas();
  document.getElementById("vbox").appendChild(canvas);
  const ctx = canvas.getContext("2d");
  let replays = 0;

  const play = () => {
    renderer.begin(clip.char, ctx);
    const t0 = performance.now();
    function frame(now) {
      const el = now - t0;
      const s = prog.fn(el);
      renderer.draw(ctx, clip.char, s);
      if (s < 1) requestAnimationFrame(frame);        // 最後の姿はそのまま残す(打ち切らない)
    }
    requestAnimationFrame(frame);
  };
  const againBtn = document.getElementById("again");
  if (againBtn) againBtn.onclick = () => { replays++; play(); };
  play();

  // 7件法の3項目。全部答えるまで次へ進めない。
  const form = document.getElementById("wbForm");
  form.innerHTML = CFG.wellbeing.items.map((it, i) => `
    <div style="margin:14px 0;padding:10px 12px;background:#f7f8fb;border:1px solid #e3e6ee;border-radius:8px">
      <div style="font-size:15px;margin-bottom:6px">${it.text}</div>
      <div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#6b7280">
        <span style="white-space:nowrap">${CFG.wellbeing.scale_min_label}</span>
        ${[1, 2, 3, 4, 5, 6, 7].map(v => `<label style="flex:1;text-align:center;cursor:pointer">
            <input type="radio" name="wb${i}" value="${v}"><br>${v}</label>`).join("")}
        <span style="white-space:nowrap">${CFG.wellbeing.scale_max_label}</span>
      </div></div>`).join("") +
    `<p style="text-align:center;margin-top:10px"><button class="primary" id="wbNext" disabled style="opacity:.5;background:#1E2A5E">次へ</button></p>`;
  const next = document.getElementById("wbNext");
  const check = () => {
    const all = CFG.wellbeing.items.every((_, i) => form.querySelector(`input[name="wb${i}"]:checked`));
    next.disabled = !all; next.style.opacity = all ? "1" : ".5";
  };
  form.querySelectorAll("input[type=radio]").forEach(r => r.addEventListener("change", check));
  next.onclick = () => {
    const ans = {};
    CFG.wellbeing.items.forEach((it, i) => {
      ans[it.key] = Number(form.querySelector(`input[name="wb${i}"]:checked`).value);
    });
    wellbeingAnswers.clips.push({ char: clip.char, family: clip.family, replays, ratings: ans });
    wbIdx++; saveProgress(); wellbeingClip();
  };
}

function wellbeingChoice() {
  screenEl.innerHTML = `<h2 style="color:#1E2A5E">最後の質問</h2>
    <p>${CFG.wellbeing.choice_text}</p>
    <div id="wbc">${CFG.wellbeing.families.map(f => `
      <label style="display:block;margin:8px 0;padding:12px 14px;background:#f7f8fb;border:1px solid #e3e6ee;border-radius:8px;cursor:pointer;font-size:15px">
        <input type="radio" name="wbc" value="${f}"> ${CFG.wellbeing.choice_labels[f] || f}</label>`).join("")}</div>
    <p style="text-align:center;margin-top:16px"><button class="primary" id="wbDone" disabled style="opacity:.5;background:#1E2A5E">回答を送って終わる</button></p>`;
  const done = document.getElementById("wbDone");
  screenEl.querySelectorAll('input[name="wbc"]').forEach(r => r.addEventListener("change", () => {
    done.disabled = false; done.style.opacity = "1";
  }));
  done.onclick = () => {
    const sel = screenEl.querySelector('input[name="wbc"]:checked');
    wellbeingAnswers.choice = sel ? sel.value : "";
    // 見え心地の回答はまとめて1レコードで保存する。
    const wbRec = {
      kind: "transfer_wellbeing",
      stimulus_id: "wellbeing|" + GROUP,
      target_char: "-", response_char: "-",
      modality: "transfer_wellbeing", q_set: "transfer", phase: PHASE, group: GROUP,
      assign_index: ASSIGN, assign_source: ASSIGN_SOURCE, n_choices: CFG.wellbeing.families.length,
      wellbeing_json: JSON.stringify(wellbeingAnswers),
      choice: wellbeingAnswers.choice,
      version: VERSION, config_version: CFG.config_version,
    };
    if (window.PROD) PROD.saveFracTrial(wbRec);
    sendRecord(wbRec);
    showResults();
  };
}

// =========================================================================
// 完了・開始
// =========================================================================
function afterTrials() {
  if (G.wellbeing) {
    if (!wellbeingAnswers) { wellbeingAnswers = { clips: [], choice: "" }; wbClips = buildWellbeingClips(); }
    if (!wbClips.length) wbClips = buildWellbeingClips();
    if (wellbeingAnswers.clips.length === 0 && wbIdx === 0) return wellbeingIntro();
    if (wbIdx < wbClips.length) return wellbeingClip();
    return wellbeingChoice();
  }
  showResults();
}

async function showResults() {
  const durS = Math.round(elapsedPrior + (Date.now() - T0) / 1000);
  if (window.PROD && PROD.enabled) PROD.saveState("transfer_" + PHASE, { completed: true, duration_s: durS });
  // 完走レコードを1行送る（承認の判定はこの行だけで済む）。
  // 1問1行の記録はここまでに全部投げてあるので、失敗の件数もここで確定している。
  // **これが送れなくても完了コードは出す。** 1問1行の記録に同じ完了コードが
  // 入っているので、照合の手がかりが完全に消えるわけではないためである。
  // 通信が悪いと作り直しで数秒かかる。最後の問題の画面のままだと固まったように
  // 見えるので、送っているあいだは一言出しておく。
  screenEl.innerHTML = `<div style="min-height:40vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">回答を送っています…</h1>
    <p class="muted">この画面のままお待ちください。閉じないでください。</p></div>`;
  await sendRecord(sessionRecord(durS, mainDone()));
  screenEl.innerHTML = finishHTML(durS);
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
    答えた問題 ${mainDone()} 問 ／ 所要 ${durS} 秒 ／
    送信できなかった記録 ${sendFailures} 件・作り直して送れた記録 ${sendRetries} 件</p></div>`;
}

// 出題を1回だけ組み立てる。**「進め方」の画面で問題数を出すために、本番へ入る前に
// 組み立てておく**（推定式で数えると実装とずれる。→ buildTrialsNow の注記）。
let builtTrials = null;
function buildTrialsNow() {
  builtTrials = (G.mode === "audio") ? buildAudioTrials() : buildVisualTrials();
  return builtTrials;
}

function start() {
  if (G.mode === "audio") ensureCtx();
  if (resumeState && resumeState.trials) {
    trials = resumeState.trials; results = resumeState.results || [];
    ti = resumeState.ti || 0; elapsedPrior = resumeState.elapsed_s || 0;
    wellbeingAnswers = resumeState.wellbeing || null;
    wbClips = resumeState.wb_clips || []; wbIdx = resumeState.wb_idx || 0;
    introduced = true; tried = 1;
    if (G.mode === "audio") prefetchStims(trials);
    return runTrial();
  }
  trials = builtTrials || buildTrialsNow();
  builtTrials = null;
  results = []; ti = 0;
  if (G.mode === "audio") prefetchStims(trials);
  showTryGate();
}

// ---- 教示と練習 -----------------------------------------------------------
function audioGuideHTML() {
  return `
    <p>ひらがな<b>1文字</b>の読み上げが流れます。<b>聞こえた文字を、かなの表から選んでください。</b>
    読み上げは<b>途中までしか流れない</b>ことがあります。</p>
    <svg viewBox="0 0 640 150" style="width:100%;max-width:560px;display:block;margin:4px auto 8px" role="img" aria-label="聴覚課題の流れの図">
      <rect x="30" y="22" width="130" height="72" rx="10" fill="#eef4f6" stroke="#2E7D8F"/>
      <rect x="30" y="22" width="52" height="72" rx="10" fill="#d8ecf0"/>
      <text x="70" y="68" font-size="30" text-anchor="middle" fill="#2E7D8F">♪</text>
      <line x1="82" y1="26" x2="82" y2="90" stroke="#2E7D8F" stroke-width="2" stroke-dasharray="4 3"/>
      <text x="95" y="118" font-size="13" text-anchor="middle" fill="#1b2030">途中で切れることがある</text>
      <text x="210" y="64" font-size="20" text-anchor="middle" fill="#2E7D8F">➡</text>
      <rect x="250" y="14" width="262" height="88" rx="10" fill="#fff" stroke="#cdd3e6"/>
      ${[0, 1].map(r => [0, 1, 2, 3, 4, 5, 6, 7].map(c => `<rect x="${266 + c * 29}" y="${26 + r * 26}" width="22" height="20" rx="4" fill="#fbfcff" stroke="#cdd3e6"/>`).join("")).join("")}
      <rect x="324" y="52" width="22" height="20" rx="4" fill="#2E7D8F"/>
      <text x="335" y="66" font-size="12" text-anchor="middle" fill="#fff">選</text>
      <text x="381" y="118" font-size="13" text-anchor="middle" fill="#1b2030">聞こえた文字を表から選ぶ</text>
    </svg>
    <ul style="font-size:14px;line-height:1.9;color:#333">
      <li>「ピッ」1回のあとに自動で始まります（終わると「ピッピッ」と2回鳴ります）。</li>
      <li><b>読み上げは1問につき1回だけです（聞き直しはできません）。</b></li>
      <li>答える時間に制限はありません。</li>
      <li><b>まったく聞こえない問題も混ざっています。</b>それも大切なデータです。</li>
      <li>聞こえなくても、<b>もっとも近いと思う文字を選んでください。</b></li>
    </ul>`;
}
function visualGuideHTML() {
  return `
    <p>ひらがな<b>1文字</b>が、見えにくい状態から<b>だんだんはっきりしていき、途中で消えます</b>。
    現れ方は問題によって違います（うすい→濃い／点が増える／ぼやけ→はっきり／端から現れる）。
    <b>見えた文字を、かなの表から選んでください。</b></p>
    <svg viewBox="0 0 640 150" style="width:100%;max-width:560px;display:block;margin:4px auto 8px" role="img" aria-label="視覚課題の流れの図">
      <rect x="14" y="22" width="54" height="66" rx="8" fill="#fff" stroke="#1E2A5E"/>
      <text x="41" y="68" font-size="30" text-anchor="middle" fill="#1b2030" opacity="0.15">か</text>
      <rect x="76" y="22" width="54" height="66" rx="8" fill="#fff" stroke="#1E2A5E"/>
      <text x="103" y="68" font-size="30" text-anchor="middle" fill="#1b2030" opacity="0.5">か</text>
      <text x="140" y="60" font-size="14" text-anchor="middle" fill="#6b7280">→</text>
      <rect x="152" y="22" width="54" height="66" rx="8" fill="#f6f6f6" stroke="#b0b6c2" stroke-dasharray="5 4"/>
      <text x="179" y="62" font-size="13" text-anchor="middle" fill="#9aa1ad">白紙</text>
      <text x="110" y="118" font-size="13" text-anchor="middle" fill="#1b2030">はっきりする途中で消える</text>
      <text x="220" y="64" font-size="20" text-anchor="middle" fill="#1E2A5E">➡</text>
      <rect x="250" y="14" width="262" height="88" rx="10" fill="#fff" stroke="#cdd3e6"/>
      ${[0, 1].map(r => [0, 1, 2, 3, 4, 5, 6, 7].map(c => `<rect x="${266 + c * 29}" y="${26 + r * 26}" width="22" height="20" rx="4" fill="#fbfcff" stroke="#cdd3e6"/>`).join("")).join("")}
      <rect x="324" y="52" width="22" height="20" rx="4" fill="#1E2A5E"/>
      <text x="335" y="66" font-size="12" text-anchor="middle" fill="#fff">選</text>
      <text x="381" y="118" font-size="13" text-anchor="middle" fill="#1b2030">見えた文字を表から選ぶ</text>
    </svg>
    <ul style="font-size:14px;line-height:1.9;color:#333">
      <li>中央の ＋ のあとに自動で始まります。</li>
      <li><b>表示は1問につき1回だけです（見直しはできません）。</b></li>
      <li>答える時間に制限はありません。</li>
      <li><b>まったく見えない問題も混ざっています。</b>それも大切なデータです。</li>
      <li>見えなくても、<b>もっとも近いと思う文字を選んでください。</b></li>
    </ul>`;
}

function showTryGate() {
  tryReturn = showTryGate;
  const accent = G.mode === "audio" ? "#2E7D8F" : "#1E2A5E";
  const enough = tried >= CFG.design.practice_min;
  screenEl.innerHTML = `<h2 style="color:#1E2A5E">${G.task_label}の課題</h2>
    ${G.mode === "audio" ? audioGuideHTML() : visualGuideHTML()}
    <div style="text-align:center;margin-top:16px">
      <p><button id="tryBtn" class="playbtn" style="background:${accent}">${tried ? "もう一度練習する" : "1問練習する"}</button></p>
      <p><button class="primary" id="goMain" ${enough ? "" : 'disabled style="opacity:.5"'}>本番を始める</button></p>
      ${enough ? "" : `<p class="muted">${CFG.design.practice_min}回以上練習すると本番に進めます。</p>`}
    </div>`;
  document.getElementById("tryBtn").onclick = () => {
    tried++;
    const t = buildTryout();
    if (t.mod === "audio") runAudioTrial(t); else runVisualTrial(t);
  };
  document.getElementById("goMain").onclick = () => {
    if (tried < CFG.design.practice_min) return;
    tryReturn = null; saveProgress(); runTrial();
  };
}

// ---- 導入・音量・見え方の確認 ---------------------------------------------
function intro() {
  const resumeNote = (resumeState && resumeState.trials)
    ? `<p style="background:#eef7ee;border:1px solid #bcd9bc;border-radius:8px;padding:10px 12px">
       <b>前回の続きから再開します</b>。
       <span class="muted" style="display:block;margin-top:4px;font-size:12.5px">練習はとばします。${G.mode === "audio" ? "音量の確認だけ" : "見え方の確認だけ"}もう一度お願いします。</span></p>` : "";
  // 問題数は**実際に組み立てた出題の配列を数えて**出す。
  // 2026-08-21 まではここで推定式を立てていたが、実装と3か所ずれていて、
  // 画面には「約91問」と出るのに本当は 108/134/94 問だった（最大43問のずれ）。
  //   ① 聴覚の「全長」の1点（audio.include_full_gate）を数えていなかった
  //   ② 群A′は progress_pct_levels（8水準）で出すのに visual.gates_ms（7点）を見ていた
  //   ③ 確認問題の割合を「ターゲットのみ」に掛けていたが、
  //      実装は「ターゲット＋まぎれ字」に掛けている
  // **式を直すのではなく、数える対象を実物にした。** 式は必ずまた実装から遅れる。
  const nQuestions = (resumeState && resumeState.trials)
    ? resumeState.trials.filter(t => !t.practice).length
    : buildTrialsNow().length;
  screenEl.innerHTML = `<h1>課題の進め方</h1>
    ${resumeNote}
    <p>ひらがな1文字の${G.mode === "audio" ? "読み上げを聞いて" : "表示を見て"}、
    どの文字かを<b>かなの表から選ぶ</b>課題です。</p>
    <p style="font-size:15px">問題数：<span id="nq">${nQuestions}</span>問</p>
    <p style="text-align:center;margin-top:18px"><button class="primary" id="go">次へ：${G.mode === "audio" ? "音量の確認" : "見え方の確認"}</button></p>
    ${(window.PROD && PROD.enabled) ? "" : `<p class="muted" style="text-align:center"><label style="cursor:pointer"><input type="checkbox" id="shortRun"> 短縮版（${CFG.design.short_run_trials}問・動作確認用）</label></p>`}
    <p class="muted" style="text-align:right;font-size:12px;margin-top:6px">${(window.PROD && PROD.enabled) ? "津田塾大学 栗原研究室" : `研究者向け動作確認 v${VERSION} ／ ${PHASE}フェーズ → 集団 ${GROUP}（割り当て: ${ASSIGN_SOURCE}） ／ 割付番号 ${ASSIGN}${audioManifest === null && G.mode === "audio" ? " ／ <b>音声は代用モード</b>" : ""}`}</p>`;
  const shortRun = document.getElementById("shortRun");
  if (shortRun) shortRun.addEventListener("change", () => {
    MAX_TARGET_TRIALS = shortRun.checked ? CFG.design.short_run_trials : (Number(CFG.design.max_target_trials) || 0);
    // 上限を変えたら出題を組み直し、画面の問題数もその場で合わせる
    // （組み立て済みのものを使い回すと、表示と実際がまた食い違う）。
    document.getElementById("nq").textContent = buildTrialsNow().length;
  });
  document.getElementById("go").onclick = (G.mode === "audio") ? volumeCheck : visionCheck;
}

// 音量確認のサンプル(あ・い・う・え・お を打ち切りなしで続けて鳴らす)。
// 全部読み終えてから並べて鳴らす(読み込みの遅れで間隔がばらつかないように)。
async function playSample() {
  const list = ["あ", "い", "う", "え", "お"].filter(c => ALL_KANA.indexOf(c) >= 0);
  const ctx = ensureCtx();
  stopAll();
  const bufs = await Promise.all(list.map(ch => loadStim(ch, null).catch(() => null)));
  const t0 = ctx.currentTime + 0.15;
  bufs.forEach((buf, i) => {
    if (!buf) return;
    const s = ctx.createBufferSource();
    s.buffer = buf; s.connect(ctx.destination); s.start(t0 + i * 0.5);
    _nodes.push(s);
  });
}
// 音量の確認。**聴覚の集団(acal / atest)だけ**が通る画面。
function volumeCheck() {
  const resuming = !!(resumeState && resumeState.trials);
  const mobileNote = ENV.touch
    ? `スマートフォンの場合は、静かな場所で、音量をやや大きめにすると聞き取りやすくなります。` : ``;
  screenEl.innerHTML = `<h2 style="color:#1E2A5E">音量の確認</h2>
    <p>下のボタンで<b>サンプル音</b>を鳴らし、聞き取りやすい音量になるよう端末の音量を調節してください。
    調節が終わったら、<b>この音量のまま</b>課題に進みます。</p>
    <div style="background:#eef4f6;border:1px solid #d3e2e7;border-radius:8px;padding:16px 14px;text-align:center">
      <button id="sample" style="font-size:16px;padding:12px 26px;border-radius:999px;border:2px solid #2E7D8F;background:#fff;color:#2E7D8F;cursor:pointer">▶ サンプル音を鳴らす（あ・い・う・え・お）</button>
      <div class="muted" style="margin-top:10px">何度でも鳴らせます。${mobileNote}この課題は静かな環境で行ってください。</div></div>
    <p style="text-align:center;margin-top:14px"><button class="primary" id="go2" disabled style="opacity:.5">${resuming ? "続きから再開する" : "課題へ進む"}</button></p>
    <p class="muted" id="volHint"></p>`;
  let played = false;
  const go2 = document.getElementById("go2");
  document.getElementById("sample").onclick = () => {
    playSample(); played = true;
    document.getElementById("volHint").textContent = "小さすぎ・大きすぎと感じたら、端末の音量を変えてもう一度鳴らして確認してください。";
    go2.disabled = false; go2.style.opacity = "1";
  };
  // 聴覚の集団は「見え方の確認」を通らない(見る刺激が無いため)。ここから本番へ。
  go2.onclick = () => { if (played) start(); };
}
// 見え方の確認。**視覚の集団(aprime / b)だけ**が通る画面。
function visionCheck() {
  const resuming = !!(resumeState && resumeState.trials);
  screenEl.innerHTML = `<h2 style="color:#1E2A5E">見え方の確認</h2>
    <p>本番と同じ枠・同じ大きさで、見本の字「あ」を表示しています。
    ふだん画面を見る距離のまま、<b>はっきり見えること</b>を確認してください。見えにくい場合は画面の明るさを上げてください。</p>
    <div id="vcheck" style="text-align:center"></div>
    <p style="text-align:center;margin-top:16px"><button class="primary" id="go3">${resuming ? "続きから再開する" : "課題へ進む"}</button></p>`;
  const canvas = newCanvas();
  document.getElementById("vcheck").appendChild(canvas);
  const ctx = canvas.getContext("2d");
  drawBlank(ctx);
  // この画面に来るのは視覚の集団だけなので、本番と同じ画像をそのまま出す。
  if (imgs["あ"]) ctx.drawImage(imgs["あ"], 0, 0, SIZE, SIZE);
  document.getElementById("go3").onclick = start;
}

// 同意画面に足す3項目（データの保管期間・同意の撤回・問い合わせ先）。
// docs/informed_consent.md が「同意画面に載せること」と定めているのに、
// prod_common.js の同意画面に入っていない項目である。値は transfer_config.js の
// contact に置いてあり、**掲載前にユーザーが【要確認】を実際の値へ書き換える**。
// 群C（transfer_comfort.js）にも同じ関数を写してある。片方だけ直さないこと。
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

// 同意画面の文言を、この実験の方針(同じことは1か所だけ・お願い口調の環境注意は書かない)に
// そろえる。**prod_common.js は実験1と共用なので触らない**——描かれたあとに、この実験の
// ページの中だけで直す。直すのは次の3つ。
//   1. 見出し「研究へのご協力のお願い」を消す(本文から始める)
//   2. 「途中再開」の項目を「記録するもの」の項目にたたむ
//      (再開した回数と中断していた時間は"記録するもの"なので、そこに書くのが素直)
//   3. 保管期間・撤回の方法・問い合わせ先の3項目を足す(倫理審査で要る項目)
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
// すでに前のフェーズに参加した人へのお断り。報酬の説明を丁寧に添える。
function blockedScreen(reason, info) {
  // 「もう参加済み」で断る理由は4通りある(較正・群C・その他・GAS 版の古い呼び名)。
  // どれも文面は同じでよいが、**接続できなかっただけ**の場合と区別する必要がある
  // (あちらは「もう一度試す」ボタンを出して、その場でやり直せるようにするため)。
  const already = (reason === "already_participated" ||
                   reason === "already_in_calib" ||
                   reason === "already_in_test" ||
                   reason === "already_in_comfort" ||
                   reason === "already_in_other_phase");
  // 接続できなかっただけの場合は、その場でもう一度試せるようにする。
  // 一過性の失敗で参加者を取りこぼさないため(2026-08-21 に実機で発生)。
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

// 名簿に問い合わせて集団を決め、同意画面までを組み立てる。
// お断り画面の「もう一度試す」からも呼ばれるので、**何度呼んでも安全**に書いてある。
async function startSession() {
  screenEl.innerHTML = `<div style="min-height:40vh;display:flex;flex-direction:column;justify-content:center;align-items:center">
    <h1 style="border:none">読み込み中…</h1>
    <p class="muted" id="loadNote" style="margin-top:10px"></p></div>`;
  // 混んでいて作り直しているときは、その旨を出して待ってもらう。
  // 何十秒も「読み込み中…」のままだと、参加者は固まったと思って閉じてしまう。
  onRosterRetry = (i, n) => {
    const el = document.getElementById("loadNote");
    if (el) el.textContent = `混み合っています。接続をやり直しています（${i}/${n}）…`;
  };
  const a = await resolveAssignment();
  onRosterRetry = null;
  if (a.blocked) { blockedScreen(a.reason, a); return false; }
  GROUP = a.group; G = GROUPS[GROUP]; ASSIGN = a.assign_index; ASSIGN_SOURCE = a.source;
  // 途中再開のデータが別の集団のものなら捨てる(割り当てが変わった場合の保険)。
  if (resumeState && resumeState.group && resumeState.group !== GROUP) resumeState = null;
  await preload();
  // 研究者モード(?prod なし)でも本番と同じ流れ。送信と途中保存だけが無効。
  // 説明文・機器の申告・環境の案内は、割り当てられた集団に合うものだけを出す。
  //   聴覚(acal/atest): 再生機器の申告あり → このあと「音量の確認」だけ
  //   視覚(aprime/b)  : 機器の申告なし・明るさの案内あり → このあと「見え方の確認」だけ
  const isAudio = (G.mode === "audio");
  // 第3引数は所要の見込み分（いまの prod_common.js は画面に出さないが、
  // 出すようになったときに嘘にならないよう、集団ごとの見込みを渡す。
  // 聴覚108問≒11.5分／視覚134問≒8.5分。一般の方はさらに1〜2分延びる）。
  PROD.consentScreen(screenEl, G.task_label, isAudio ? 12 : 9, intro, isAudio,
    { noEnvNote: true, allowWireless: true,
      desc: isAudio
        ? "日本語のかな1文字が、どこまで聞こえれば分かるかを調べる研究です"
        : "日本語のかな1文字が、どこまで表示されれば分かるかを調べる研究です" });
  tidyConsentScreen();
  // 同意画面で申告された再生機器を控える(prod_common.js は自分の送信にしか使わず、
  // 外に見せていないため)。無線のイヤホンは音の頭が欠けるので、解析で要る列。
  screenEl.querySelectorAll('input[name="dev"]').forEach(r =>
    r.addEventListener("change", () => { audioDeviceAnswer = r.value; }));
  return true;
}

(async function () {
  try {
    showPreLaunchBadge();
    if (!PHASE_GROUPS.length) {
      screenEl.innerHTML = `<h1>設定エラー</h1>
        <p class="muted">transfer_config.js の phases に "${PHASE}" がありません。</p>`;
      return;
    }
    // 途中再開の情報は、参加者IDを保存時のものへ戻す働きがあるので、
    // 集団の問い合わせより先に読む(同じ人が同じ集団に戻るようにするため)。
    if (window.PROD && PROD.enabled) {
      resumeState = PROD.loadState("transfer_" + PHASE);
      // 再開の回数と中断秒は prod_common.js が内側に持っていて外から読めないので、
      // 同じ規則(前回の値 + 1 / 前回の値 + 今回あいた秒数)でここでも作る。
      // 途中状態をこのあと捨てる場合(版ちがい・別の集団)でも、開き直した事実は残す。
      if (resumeState && resumeState.saved_at) {
        resumeMeta = { count: (resumeState.resume_count || 0) + 1,
                       gapS: (resumeState.resume_gap_s || 0)
                             + Math.round((Date.now() - resumeState.saved_at) / 1000) };
      }
      if (resumeState && !resumeState.completed && resumeState.session_v !== SESSION_V) resumeState = null;
      if (resumeState && resumeState.completed) {
        screenEl.innerHTML = PROD.completionHTML(resumeState.duration_s || 0);
        return;
      }
    }
    await startSession();
  } catch (e) {
    screenEl.innerHTML = `<h1>読み込みエラー</h1><p class="muted">${e.message}</p>`;
  }
})();
