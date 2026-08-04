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

  // クラウドソーシング(Yahoo!クラウドソーシング等)の作業者IDをURLから拾う。
  const workerId = P.get("worker_id") || P.get("wid") || P.get("worker") || "";
  const participantId = workerId || ("anon-" + Math.random().toString(36).slice(2, 10));
  // 12桁の完了コード。報酬照合のためサーバにも各試行とともに記録される。
  const CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
  const completionCode = Array.from({ length: 12 },
    () => CODE_CHARS[Math.floor(Math.random() * CODE_CHARS.length)]).join("");

  let sentTrials = 0;

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
    if (!SUBMIT_URL) return;
    try {
      fetch(SUBMIT_URL, {
        method: "POST", mode: "no-cors",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify(Object.assign({
          participant_id: participantId, worker_id: workerId,
          completion_code: completionCode, ts: Date.now(),
        }, envBody(), body)),
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
  function consentScreen(el, taskLabel, minutes, onOk, headphone) {
    const envNote = headphone
      ? "ヘッドホンやイヤホンを使い、静かな環境でお願いします。"
      : "できればPC（パソコン）で、明るい静かな環境でお願いします。";
    el.innerHTML = `
      <h1>かなの認識に関する研究へのご協力のお願い</h1>
      <p>本実験は、日本語のかな1文字の分かりやすさを文字ごとに測る研究です（津田塾大学）。
      ${taskLabel}を行います。所要時間は約${minutes}分です。</p>
      <ul style="font-size:14px;line-height:1.9;color:#333">
        <li><b>取得するデータ</b>：各設問への回答と所要時間、参加のための識別子、端末の画面サイズなど技術情報。</li>
        <li><b>個人を特定する情報は集めません。</b>取得データは研究目的にのみ用い、統計的に処理して発表します。</li>
        <li>回答の正誤は報酬に影響しません。<b>難しくて当然の課題です。</b>分からなければ勘でお答えください。</li>
        <li>途中でやめる場合はブラウザを閉じてください。完了画面の<b>完了コード</b>を応募元に貼ると報酬の対象になります。</li>
      </ul>
      <p style="margin-top:16px"><label style="font-size:15px"><input type="checkbox" id="cst"> 上記に同意し、18歳以上であることを確認しました。</label></p>
      <p><button class="primary" id="cstGo" disabled style="opacity:.5">同意して始める</button></p>
      <p class="muted">${envNote}</p>`;
    const cb = el.querySelector("#cst"), go = el.querySelector("#cstGo");
    cb.addEventListener("change", () => { go.disabled = !cb.checked; go.style.opacity = cb.checked ? "1" : ".5"; });
    go.addEventListener("click", () => { if (cb.checked) onOk(); });
  }

  // 完了画面のHTML(本番モードのみ)。完了コードを大きく表示。
  function completionHTML(seconds) {
    return `<div style="text-align:center;padding:24px 10px">
      <h1>ご協力ありがとうございました</h1>
      <p>下の<b>完了コード</b>を、応募元の入力欄に貼り付けてください。</p>
      <p style="font-size:30px;font-weight:800;letter-spacing:3px;color:#1E2A5E;
        background:#f2f5f8;border:1px solid #dde3ec;border-radius:10px;padding:14px 8px;margin:14px auto;max-width:360px">${completionCode}</p>
      <p class="muted">参加者ID: ${participantId} ／ 所要 ${seconds} 秒</p></div>`;
  }

  global.PROD = {
    enabled, workerId, participantId, completionCode,
    setEnv, saveTrial, saveDone, saveFracTrial, consentScreen, completionHTML,
    hasEndpoint: !!SUBMIT_URL,
  };
})(window);
