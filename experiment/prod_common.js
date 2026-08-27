// =========================================================================
// 本番化の共通配管 (同意・参加者ID・GAS保存・完了コード)
//   乙課題(pilot_soa_audio / pilot_soa_visual2)と frac課題(audio1char /
//   audio2char / visual1char / visual2char)を、クラウドソーシングで
//   実施できる本番仕様に引き上げるための共通部品。
//
//   使い方: 各実験ページの <script> より前に読み込む。
//     <script src="prod_common.js"></script>
//   ?prod=1 (または ?mode=prod) のときだけ「本番モード」になり、
//     ・冒頭に同意画面を出す ・各試行をGASへ送る ・最後に完了コードを出す。
//   ?prod が無ければ従来どおり(研究者パイロット・ローカルDL)。
//
//   参加者ID・完了コード・送信先URLはここに一本化してある。各実験ページは
//   PROD.participantId / PROD.completionCode を参照し、独自に持たないこと。
//
//   送信の種類は2つある。
//     ・乙課題:   PROD.saveTrial / PROD.saveDone → kind を持つ (soa_trials / soa_sessions シート)
//     ・frac課題: PROD.saveFracTrial            → kind を持たない従来形式 ("trials" シート)
//
//   端末環境は PROD.setEnv(ENV) で各ページから登録する。登録したオブジェクトは
//   参照として保持し、送信のたびに現在値を読む(リフレッシュレートのように
//   読み込み後に非同期で確定する項目があるため)。
//
//   デプロイ時: 下の SUBMIT_URL に GAS ウェブアプリの /exec URL を貼る。
//   空のままだと送信をスキップする(本番モードでも画面は本番仕様になる)。
// =========================================================================
(function (global) {
  "use strict";
  const P = new URLSearchParams(location.search);
  const enabled = P.has("prod") || P.get("mode") === "prod";

  // ▼ デプロイ前に、公開した Google Apps Script の /exec URL を貼る。
  const SUBMIT_URL = "";

  // ▼ Firestore 二重書き込み(推奨)。GASは同時実行30本の上限があり、混雑時に
  //   取りこぼす恐れがあるため、Firestore にも並行保存する(どちらか片方でも可)。
  //   設定手順は docs/FIREBASE_SETUP.md。空のままなら Firestore への送信はスキップ。
  const FIREBASE = { projectId: "", apiKey: "" };

  // クラウドソーシング(Yahoo!クラウドソーシング等)の作業者IDをURLから拾う。
  // participantId / completionCode は途中再開のとき保存時の値へ引き継ぐため let。
  const workerId = P.get("worker_id") || P.get("wid") || P.get("worker") || "";
  let participantId = workerId || ("anon-" + Math.random().toString(36).slice(2, 10));
  // 完了コード。報酬照合のためサーバにも各試行とともに記録される。
  // 使う文字は31種（紛らわしい I・L・O・0・1 を除いてある）。
  //
  // ■ 2026-08-25、**12文字から6文字へ短くした**（丸山判断）。
  //   スマートフォンで貼り付けそこねる・打ち直すときの負担を減らすため。
  //   当てずっぽうで通される心配は無い。6文字なら 31^6 ＝ 8.9億通りあり、
  //   正しいコードは募集人数ぶん（253本）しか存在しない。しかも**1人1回しか
  //   回答できない**設定なので、試行は1回きりで、当たる確率は約350万分の1である。
  const CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
  const CODE_LEN = 6;
  // ■ 2026-08-27、**作業者IDから決まる値に変えた**（丸山判断）。
  //   それまでは毎回ランダムだったが、それだと掲載側のチェック設問（正解の事前登録）が
  //   使えない。IDから決めれば、設問データのC列に正解を書いておけて、
  //   Yahoo!側で完了コードの自動照合ができる。
  //   ⚠ 計算式はこのファイルに載る＝読める人はコードを算出できる。
  //     130円の課題でそこまでやる人は考えにくいが、**サーバ記録との照合は別途行う**
  //     （承認判定の表。experiment/tools/build_yahoo_task_tsv.py と同じ式で作る）。
  //   IDが無いとき（研究者のローカル確認など）は従来どおりランダム。
  // ■ 2026-08-27、6文字の英数字から**3つの番号(各0〜9)**へ変えた（丸山判断）。
  //   掲載側のフォームをセレクトボックス3つに作り替え、チェック設問の自動照合を
  //   使えるようにするため（自由記述欄はチェック設問の対象にできない）。
  //   番号はIDから決まる（Python側と同一の式。FNV-1a → 線形合同法 → 各桁 %10）。
  //   3桁=1000通りなので当てずっぽうは0.1%。IDが鍵なので番号の衝突は問題にならない。
  function codeFromWid(wid) {
    let h = 0x811c9dc5;
    const src = "ifont-cc-2026|" + wid;
    for (let i = 0; i < src.length; i++) {
      h ^= src.charCodeAt(i);
      // ⚠ 普通の掛け算だと 2^53 を超えて桁落ちする。Math.imul で 32bit に収める。
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    let out = "";
    for (let k = 0; k < 3; k++) {
      h = (Math.imul(h, 1664525) + 1013904223) >>> 0;
      out += String(h % 10);
    }
    return out;
  }
  let completionCode = workerId
    ? codeFromWid(workerId)
    : Array.from({ length: 3 }, () => String(Math.floor(Math.random() * 10))).join("");

  let sentTrials = 0;

  // ---- 途中再開(同じブラウザ) -------------------------------------------
  // 進行状況を参加者の端末の localStorage にのみ保存する(進行状況が外部へ送られることはない)。
  // ブラウザクラッシュ・誤ってタブを閉じた場合に、同じブラウザで開き直せば続きから再開できる。
  // 期限は RESUME_TTL_MIN 分。Yahoo側で設定する「制限時間」と同じ値にすること(発注時に要確認)。
  const RESUME_TTL_MIN = 60;
  let resumeInfo = null;     // {count, gapS}: 再開回数と中断合計秒。全送信レコードに載る。
  let resumeAware = false;   // 再開機能を使うページのみ、同意画面に保存についての1行を出す
  function resumeKey(task) { return "ifont_resume_" + task + "_" + (workerId || "anon"); }
  // 保存された途中状態を読む。期限切れは捨てる。見つかったら参加者ID・完了コードを保存時の
  // ものへ引き継ぎ、再開回数と中断秒を数える。ページ読み込みにつき1回だけ呼ぶこと。
  function loadState(task) {
    resumeAware = true;
    if (!enabled) return null;
    try {
      const raw = localStorage.getItem(resumeKey(task));
      if (!raw) return null;
      const st = JSON.parse(raw);
      if (!st || !st.saved_at) return null;
      if (Date.now() - st.saved_at > RESUME_TTL_MIN * 60 * 1000) {
        localStorage.removeItem(resumeKey(task)); return null;
      }
      if (st.participant_id) { participantId = st.participant_id; global.PROD.participantId = participantId; }
      if (st.completion_code) { completionCode = st.completion_code; global.PROD.completionCode = completionCode; }
      resumeInfo = { count: (st.resume_count || 0) + 1,
                     gapS: (st.resume_gap_s || 0) + Math.round((Date.now() - st.saved_at) / 1000) };
      return st;
    } catch (e) { return null; }
  }
  // 途中状態を保存する。data はページ側が決める中身(出題順・何問目か・回答済みデータなど)。
  function saveState(task, data) {
    resumeAware = true;
    if (!enabled) return;
    try {
      localStorage.setItem(resumeKey(task), JSON.stringify(Object.assign({}, data, {
        participant_id: participantId, completion_code: completionCode,
        resume_count: resumeInfo ? resumeInfo.count : 0,
        resume_gap_s: resumeInfo ? resumeInfo.gapS : 0,
        saved_at: Date.now(),
      })));
    } catch (e) { /* 保存できない環境では再開が効かないだけ(課題自体は続行できる) */ }
  }
  function clearState(task) { try { localStorage.removeItem(resumeKey(task)); } catch (e) {} }

  // Firestore REST 用: JSの値を Firestore のフィールド型に変換する。
  function fsValue(v) {
    if (v === null || v === undefined) return { nullValue: null };
    if (typeof v === "boolean") return { booleanValue: v };
    if (typeof v === "number") return Number.isFinite(v) ? { doubleValue: v } : { nullValue: null };
    if (typeof v === "object") return { stringValue: JSON.stringify(v) };
    return { stringValue: String(v) };
  }

  function fsPost(body) {
    if (!FIREBASE.projectId || !FIREBASE.apiKey) return;
    const collection = body.kind === "soa_done" ? "soa_sessions"
                     : body.kind === "soa_trial" ? "soa_trials" : "trials";
    const fields = {};
    for (const k of Object.keys(body)) fields[k] = fsValue(body[k]);
    try {
      fetch(`https://firestore.googleapis.com/v1/projects/${FIREBASE.projectId}` +
            `/databases/(default)/documents/${collection}?key=${FIREBASE.apiKey}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields }),
      }).then(r => { if (!r.ok) console.warn("firestore submit:", r.status); })
        .catch(e => console.warn("firestore submit failed:", e));
    } catch (e) { console.warn("firestore submit failed:", e); }
  }

  // 端末環境。各実験ページが測ったオブジェクトを登録する(参照を保持する)。
  let envRef = null;
  function setEnv(env) { envRef = env || null; }
  // 送信本文に載せる形に整える。ページ側のキー名(refreshHz)と列名(refresh_hz)の橋渡しもここで行う。
  function envBody() {
    if (!envRef) return {};
    const hz = (envRef.refreshHz != null) ? envRef.refreshHz
             : (envRef.refresh_hz != null) ? envRef.refresh_hz : "";
    return {
      ua: envRef.ua || "", dpr: envRef.dpr || "",
      screen: envRef.screen || "", touch: !!envRef.touch, refresh_hz: hz,
    };
  }

  function post(body) {
    const full = Object.assign({
      participant_id: participantId, worker_id: workerId,
      completion_code: completionCode, ts: Date.now(),
      audio_device: audioDevice,
      resume_count: resumeInfo ? resumeInfo.count : 0,
      resume_gap_s: resumeInfo ? resumeInfo.gapS : 0,
    }, envBody(), body);
    fsPost(full);                                   // Firestore(設定時のみ)
    if (!SUBMIT_URL) return;
    try {
      fetch(SUBMIT_URL, {
        method: "POST", mode: "no-cors",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify(full),
      });
    } catch (e) { console.warn("submit failed:", e); }
  }

  // 各試行を送る(乙課題は1試行=2回答なので resp1/resp2 を持つ)。
  function saveTrial(task, meta, trial, index) {
    if (!enabled) return;
    sentTrials++;
    post(Object.assign({ kind: "soa_trial", task: task, trial_index: index }, meta, trial));
  }
  // セッション完了の記録(集計値と所要時間)。
  function saveDone(task, meta, summary) {
    if (!enabled) return;
    post(Object.assign({ kind: "soa_done", task: task, n_trials: sentTrials }, meta, summary));
  }
  // frac課題(audio1char / audio2char / visual1char / visual2char)の1試行を送る。
  // 乙課題と違い kind を持たない従来形式で、GAS 側は answer_key で採点して
  // "trials" シートに1行追記する。参加者ID・完了コード・端末環境・ts は post() が付ける。
  function saveFracTrial(trial) {
    if (!enabled) return;
    sentTrials++;
    post(trial);
  }

  // 同意画面(本番モードのみ冒頭に出す)。opts = {taskLabel, minutes, headphone, onOk}
  // 聴覚課題の再生機器の申告。区分は接続方式で切る: 内蔵・有線接続=OK、無線(Bluetooth)=NG。
  // Bluetoothスピーカーも無線ヘッドホンと同じく音の頭が欠けるため「無線」に含める。
  // 選択は全回答と共に保存される。
  let audioDevice = "";
  const DEVICE_HTML = `
      <div id="devBox" style="margin-top:14px;padding:12px 14px;background:#f6f8fb;border:1px solid #dde3ec;border-radius:8px">
        <p style="margin:0 0 6px;font-size:15px"><b>音の再生に使う機器</b>を選んでください：</p>
        <label style="display:block;font-size:14.5px;margin:4px 0"><input type="radio" name="dev" value="スピーカー"> PC・スマホのスピーカー</label>
        <label style="display:block;font-size:14.5px;margin:4px 0"><input type="radio" name="dev" value="有線ヘッドホン"> 有線のヘッドホン・イヤホン</label>
        <label style="display:block;font-size:14.5px;margin:4px 0"><input type="radio" name="dev" value="無線"> 無線（Bluetooth）の機器（ヘッドホン・イヤホン・スピーカー）</label>
        <p id="devWarn" style="display:none;color:#b3261e;font-size:13.5px;margin:6px 0 0">
          無線（Bluetooth）機器は音の頭が欠けることがあるため、本実験ではご利用いただけません。
          <b>内蔵スピーカーか、ケーブルでつないだ機器に切り替えてから</b>、上の選択を変更してください。</p>
      </div>`;

  // opts.noEnvNote: 乙課題ページ用。機器申告と音量/見え方の確認画面が環境の案内を担うため、
  //   末尾の環境注意文を出さない(frac課題ページは従来どおり表示)。
  // opts.desc: 冒頭の研究説明の一文(「〜を調べる研究です」まで)。ページのモダリティに合わせる。
  //   省略時は従来の汎用文(frac課題ページの互換のため)。
  // opts.allowWireless: 無線(Bluetooth)でも参加可にする(申告は必須のまま・控えめな注意のみ)。
  //   合図音で頭欠けを吸収できるページ(1文字統合セッション)用。乙課題は合図音が無いため禁止のまま。
  function consentScreen(el, taskLabel, minutes, onOk, headphone, opts) {
    const o = opts || {};
    const desc = o.desc || "日本語のかな1文字の分かりやすさを文字ごとに測る研究です";
    const envNote = headphone
      ? "静かな環境でお願いします。音はスピーカーまたは有線ヘッドホンで再生してください（無線は不可）。"
      : "できればPC（パソコン）で、明るい静かな環境でお願いします。";
    el.innerHTML = `
      <h1>研究へのご協力のお願い</h1>
      <p>本実験は、${desc}。</p>
      <ul style="font-size:14px;line-height:1.9;color:#333">
        <li><b>参加できる方</b>：18歳以上の方が参加いただけます。</li>
        <li><b>記録するもの</b>：各設問への回答と回答時間、参加者を区別するための識別子、端末の画面サイズなどの技術情報を記録します。</li>
        <li><b>記録しないもの</b>：氏名やメールアドレスなど、個人を直接特定する情報は記録しません。</li>
        <li><b>データの利用目的</b>：研究目的にのみ使用し、統計的に処理したうえで研究発表等に利用します。</li>
        ${resumeAware ? `<li><b>途中再開</b>：中断しても、同じブラウザでこのページを開き直せば続きから再開できます。そのための進行状況の控えはお使いのブラウザ内に保存され、再開した回数と中断時間は回答データとともに記録されます。</li>` : ""}
        <li><b>中断・完了</b>：途中でやめる場合はブラウザを閉じてください。最後まで完了すると<b>完了コード</b>が表示され、参加したサービス上でこのコードを入力すると報酬の対象となります。</li>
      </ul>
      ${headphone ? DEVICE_HTML : ""}
      <p style="margin-top:16px"><button class="primary" id="cstGo" disabled style="opacity:.5">同意して始める</button></p>
      ${o.noEnvNote ? "" : `<p class="muted">${envNote}</p>`}
`;   // 2026-08-25 丸山決定: 所属（大学名・研究室名）は画面に出さない。「実施：」の行を削除した。
    // 同意はボタン「同意して始める」に集約(チェックボックスは廃止・丸山判断 8/17)。
    // 聴覚課題は機器の申告(無線以外)をするまでボタンを押せない。
    const go = el.querySelector("#cstGo");
    const devRadios = el.querySelectorAll('input[name="dev"]');
    const devWarn = el.querySelector("#devWarn");
    const devOk = () => !headphone || (audioDevice && (o.allowWireless || audioDevice !== "無線"));
    function ready() {
      go.disabled = !devOk(); go.style.opacity = devOk() ? "1" : ".5";
    }
    ready();   // 機器申告のないページ(視覚など)は最初から押せる
    if (o.allowWireless && devWarn) devWarn.remove();   // 無線可のページでは注意書きを出さない
    devRadios.forEach(r => r.addEventListener("change", () => {
      audioDevice = r.value;
      if (devWarn) devWarn.style.display = audioDevice === "無線" ? "block" : "none";
      ready();
    }));
    go.addEventListener("click", () => { if (devOk()) onOk(); });
  }

  // 完了画面のHTML(本番モードのみ)。完了コードを大きく表示。
  //
  // opts.codeNote: 完了コードの上に出す案内文（HTML）。省略時は従来の一文。
  //   ⚠ **「参加したサービス」では、どこへ戻るのか伝わらない**（2026-08-25 丸山指摘）。
  //     募集サイト側の入力欄には「課題の最後に表示される『完了コード』を入力してください」と
  //     出ているので、**その画面へ戻って貼る**と分かる言い方にする。
  //     ⚠ 呼び方は**「タスクの画面」**にそろえる。募集サイト側が「タスク」と呼んでおり、
  //       「募集サイト」では参加者の頭の中の呼び名と合わない（2026-08-25 丸山指摘）。
  // opts.hideMeta: 末尾の「参加者ID ／ 所要 ◯秒」を出さない。
  //   ⚠ **転写検証の課題では出さない**（2026-08-25 丸山判断）。理由は2つ。
  //     ① 参加者IDが完了コードと紛らわしい。**貼るものが2つあるように見え**、
  //        間違ってIDを貼ると「記録に無いコード」として非承認の元になる。
  //        参加者IDを知っていて参加者側が得することは無い（問い合わせも完了コードで受ける）。
  //     ② 所要秒は同意画面からの通算で、**中断した時間もそのまま入る**。
  //        実際、途中で手を止めた回は 1044秒（17分）と出た。参加者の実感と食い違い、
  //        「そんなにかかっていない」と受け取られる。
  //   既定は従来どおり出す（他の実験ページの見た目を変えないため）。
  function completionHTML(seconds, opts) {
    return `<div style="text-align:center;padding:24px 10px">
      <h1>全ての実験が終了しました</h1>
      <p>ご協力ありがとうございました。</p>
      ${(opts && opts.codeNote) || ""}
      ${(opts && opts.hideCode) ? "" : `<div style="margin:14px auto;max-width:300px">
        ${completionCode.split("").map((d, i) =>
          `<div style="margin:10px 0">
             <div style="font-size:14px;color:#556">完了コード${i + 1}文字目</div>
             <div style="font-size:34px;font-weight:800;color:#1E2A5E;background:#f2f5f8;
               border:1px solid #dde3ec;border-radius:10px;padding:8px 0;margin-top:4px">${d}</div>
           </div>`).join("")}
      </div>`}
      ${(opts && opts.hintTable) ? hintTableHTML() : ""}
      ${(opts && opts.hideMeta) ? "" :
        `<p class="muted">参加者ID: ${participantId} ／ 所要 ${seconds} 秒</p>`}</div>`;
  }

  // 完了コードの表示（2026-08-27・全員共通に確定）。
  // ■ 経緯: 個人別コード → ヒント表 と試したが、参加者に分かりにくいため
  //   **全員同じ3桁**に落ち着いた（丸山判断）。掲載は数分で埋まるので、
  //   コードが出回る前に募集が終わる。実験を本当にやったかの確認は、
  //   設問URLのIDとサーバの完了記録の照合で行う（コードは支払いの入口の確認だけ）。
  // ■ この値は設問データ（チェック設問の解答）と一致させること。
  //   project/設問データ_見え方の課題2_0827.tsv の生成時に同じ値を使う。
  const SHARED_CODE = "949";
  function hintTableHTML() {
    return `<div style="margin:14px auto;max-width:300px">
      ${SHARED_CODE.split("").map((d, i) =>
        `<div style="margin:10px 0">
           <div style="font-size:14px;color:#556">完了コード${i + 1}文字目</div>
           <div style="font-size:34px;font-weight:800;color:#1E2A5E;background:#f2f5f8;
             border:1px solid #dde3ec;border-radius:10px;padding:8px 0;margin-top:4px">${d}</div>
         </div>`).join("")}
    </div>`;
  }

  global.PROD = {
    enabled, workerId, participantId, completionCode,
    setEnv, saveTrial, saveDone, saveFracTrial, consentScreen, completionHTML,
    loadState, saveState, clearState,
    hasEndpoint: !!SUBMIT_URL,
  };
})(window);
