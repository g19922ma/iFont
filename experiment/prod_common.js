// =========================================================================
// iFont 本番化の共通配管 (同意・参加者ID・GAS保存・完了コード)
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
  // 12桁の完了コード。報酬照合のためサーバにも各試行とともに記録される。
  const CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
  let completionCode = Array.from({ length: 12 },
    () => CODE_CHARS[Math.floor(Math.random() * CODE_CHARS.length)]).join("");

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
  // 聴覚課題の再生機器の申告(スピーカー/有線=OK、無線=NG)。選択は全回答と共に保存される。
  let audioDevice = "";
  const DEVICE_HTML = `
      <div id="devBox" style="margin-top:14px;padding:12px 14px;background:#f6f8fb;border:1px solid #dde3ec;border-radius:8px">
        <p style="margin:0 0 6px;font-size:15px"><b>音の再生に使う機器</b>を選んでください：</p>
        <label style="display:block;font-size:14.5px;margin:4px 0"><input type="radio" name="dev" value="スピーカー"> スピーカー（PC内蔵・外付け）</label>
        <label style="display:block;font-size:14.5px;margin:4px 0"><input type="radio" name="dev" value="有線ヘッドホン"> 有線のヘッドホン・イヤホン</label>
        <label style="display:block;font-size:14.5px;margin:4px 0"><input type="radio" name="dev" value="無線"> 無線（Bluetooth）のヘッドホン・イヤホン</label>
        <p id="devWarn" style="display:none;color:#b3261e;font-size:13.5px;margin:6px 0 0">
          無線（Bluetooth）機器は音の頭が欠けることがあるため、本実験ではご利用いただけません。
          <b>スピーカーか有線の機器に切り替えてから</b>、上の選択を変更してください。</p>
      </div>`;

  // opts.noEnvNote: 乙課題ページ用。機器申告と音量/見え方の確認画面が環境の案内を担うため、
  //   末尾の環境注意文を出さない(frac課題ページは従来どおり表示)。
  // opts.desc: 冒頭の研究説明の一文(「〜を調べる研究です」まで)。ページのモダリティに合わせる。
  //   省略時は従来の汎用文(frac課題ページの互換のため)。
  function consentScreen(el, taskLabel, minutes, onOk, headphone, opts) {
    const o = opts || {};
    const desc = o.desc || "日本語のかな1文字の分かりやすさを文字ごとに測る研究です";
    const envNote = headphone
      ? "静かな環境でお願いします。音はスピーカーまたは有線ヘッドホンで再生してください（無線は不可）。"
      : "できればPC（パソコン）で、明るい静かな環境でお願いします。";
    el.innerHTML = `
      <h1>かなの認識に関する研究へのご協力のお願い</h1>
      <p>本実験は、${desc}。
      ${taskLabel}を行います。所要時間は約${minutes}分です。</p>
      <ul style="font-size:14px;line-height:1.9;color:#333">
        <li><b>取得するデータ</b>：各設問への回答と回答時間、参加者を区別するための識別子、端末の画面サイズなどの技術情報。</li>
        <li>氏名やメールアドレスなど、<b>個人を直接特定する情報は取得しません。</b>取得したデータは研究目的にのみ使用し、統計的に処理したうえで研究発表等に利用します。</li>
        ${resumeAware ? `<li>途中で中断した場合に再開するための記録は、お使いのブラウザ内にのみ保存されます（研究者には送信されません）。</li>` : ""}
        <li>回答の正誤によって報酬が変わることはありません。判別しにくい問題も含まれますので、分からない場合も、もっとも近いと思う文字を選んでください。</li>
        <li>途中で参加をやめる場合はブラウザを閉じてください。最後まで完了すると<b>完了コード</b>が表示されます。参加したサービス上でこのコードを入力すると、報酬の対象となります。</li>
      </ul>
      ${headphone ? DEVICE_HTML : ""}
      <p style="margin-top:16px"><label style="font-size:15px"><input type="checkbox" id="cst"> 上記に同意し、18歳以上であることを確認しました。</label></p>
      <p><button class="primary" id="cstGo" disabled style="opacity:.5">同意して始める</button></p>
      ${o.noEnvNote ? "" : `<p class="muted">${envNote}</p>`}
      <p class="muted" style="text-align:right;margin-top:14px">実施：津田塾大学 栗原研究室</p>`;
    const cb = el.querySelector("#cst"), go = el.querySelector("#cstGo");
    const devRadios = el.querySelectorAll('input[name="dev"]');
    const devWarn = el.querySelector("#devWarn");
    function ready() {
      const devOk = !headphone || (audioDevice && audioDevice !== "無線");
      const ok = cb.checked && devOk;
      go.disabled = !ok; go.style.opacity = ok ? "1" : ".5";
    }
    devRadios.forEach(r => r.addEventListener("change", () => {
      audioDevice = r.value;
      if (devWarn) devWarn.style.display = audioDevice === "無線" ? "block" : "none";
      ready();
    }));
    cb.addEventListener("change", ready);
    go.addEventListener("click", () => {
      if (cb.checked && (!headphone || (audioDevice && audioDevice !== "無線"))) onOk();
    });
  }

  // 完了画面のHTML(本番モードのみ)。完了コードを大きく表示。
  function completionHTML(seconds) {
    return `<div style="text-align:center;padding:24px 10px">
      <h1>ご協力ありがとうございました</h1>
      <p>下の<b>完了コード</b>を、応募元の入力欄に貼り付けてください。</p>
      <p style="font-size:30px;font-weight:800;letter-spacing:3px;color:#1E2A5E;
        background:#f2f5f8;border:1px solid #dde3ec;border-radius:10px;padding:14px 8px;margin:14px auto;max-width:360px">${completionCode}</p>
      <p><button class="primary" onclick="navigator.clipboard.writeText('${completionCode}').then(()=>{this.textContent='コピーしました ✓'},()=>{this.textContent='コピーできませんでした。上のコードを手動で選択してください'})">完了コードをコピー</button></p>
      <p class="muted">参加者ID: ${participantId} ／ 所要 ${seconds} 秒</p></div>`;
  }

  global.PROD = {
    enabled, workerId, participantId, completionCode,
    setEnv, saveTrial, saveDone, saveFracTrial, consentScreen, completionHTML,
    loadState, saveState, clearState,
    hasEndpoint: !!SUBMIT_URL,
  };
})(window);
