# 転写検証実験のための GAS 差分（貼り付け用・未デプロイ）

対象: `gas/code.gs`（既存の実験が動いているので、**このファイルはまだ書き換えていない**）。
下の3つを足すと、転写検証実験（`experiment/transfer_calib.html` / `transfer_test.html`）の
記録と集団の振り分けが動く。既存の課題（乙課題・frac課題）の処理には触らない。

- 追加1: 回答の保存先を新しいシート `transfer_trials` にする分岐（既存の `trials` シートの列は増やさない）
- 追加2: 見え心地の評価を `transfer_wellbeing` シートに1参加者1行で保存
- 追加3: 集団の自動振り分けと重複参加の照合（`doGet` の `action=transfer_status`）

デプロイの手順は既存と同じ（スクリプトエディタに貼る → 新しいデプロイを作る → `/exec` URL を
`experiment/prod_common.js` の `SUBMIT_URL` と `experiment/transfer_config.js` の
`roster.status_url` の両方に入れる）。**この作業はまだ行っていない。**

---

## 追加1・2: 回答の保存（`doPost` の先頭に分岐を1つ足す）

`doPost` の中、`body.kind === "soa_trial" || body.kind === "soa_done"` の分岐のすぐ下に置く。

```js
    // 転写検証実験(transfer_calib / transfer_test)。既存の trials シートとは別の
    // シートに書く(列構成が違うため。既存シートのヘッダを触らずに済む)。
    if (body.kind === "transfer_wellbeing") {
      return handleTransferWellbeing(sheetId, body);
    }
    if (typeof body.modality === "string" && body.modality.indexOf("transfer_") === 0) {
      return handleTransferTrial(sheetId, body);
    }
```

本体（ファイル末尾に足す）:

```js
// 転写検証実験の1問1行。採点は client 申告の target_char で行う
// (視覚1文字課題と同じ契約。刺激をブラウザ側で合成する課題では answer_key を持てないため)。
function handleTransferTrial(sheetId, body) {
  if (!body.target_char) return out({status: "error", reason: "transfer requires target_char"});
  const ss = SpreadsheetApp.openById(sheetId);
  let s = ss.getSheetByName("transfer_trials");
  if (!s) {
    s = ss.insertSheet("transfer_trials");
    s.appendRow([
      "ts", "participant_id", "worker_id", "completion_code",
      // どの集団の・何問目か
      "phase", "group", "assign_index", "assign_source", "trial_index",
      // 刺激
      "stimulus_id", "target_char", "response_char", "correct",
      "modality", "family", "condition", "gate_ms", "progress_pct",
      "is_filler", "check_kind", "is_catch", "n_choices",
      // 実測
      "rt_ms", "actual_ms", "actual_frames", "actual_s", "progress_source", "base_anim_ms",
      // 端末・再開・版
      "ua", "dpr", "screen", "touch", "refresh_hz", "audio_device",
      "resume_count", "resume_gap_s", "version", "config_version",
    ]);
  }
  const correct = body.response_char === body.target_char;
  s.appendRow([
    new Date(body.ts || Date.now()),
    body.participant_id || "", body.worker_id || "", body.completion_code || "",
    body.phase || "", body.group || "", blank(body.assign_index), body.assign_source || "",
    blank(body.trial_index),
    body.stimulus_id || "", body.target_char, body.response_char, correct,
    body.modality || "", body.family || "", body.condition || "",
    blank(body.gate_ms), blank(body.progress_pct),
    (body.is_filler === undefined ? "" : !!body.is_filler),
    body.check_kind || "", (body.is_catch === undefined ? "" : !!body.is_catch),
    blank(body.n_choices),
    blank(body.rt_ms), blank(body.actual_ms), blank(body.actual_frames), blank(body.actual_s),
    body.progress_source || "", blank(body.base_anim_ms),
    blank(body.ua), blank(body.dpr), blank(body.screen),
    (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
    body.audio_device || "",
    blank(body.resume_count), blank(body.resume_gap_s),
    body.version || "", body.config_version || "",
  ]);
  return out({status: "ok", correct: correct});
}

// 見え心地の評価(群Bの最後)。1参加者1行。clip ごとの7件法は JSON のまま入れる
// (方式×代表字の本数が設定で変わるため、列を固定しない)。
function handleTransferWellbeing(sheetId, body) {
  const ss = SpreadsheetApp.openById(sheetId);
  let s = ss.getSheetByName("transfer_wellbeing");
  if (!s) {
    s = ss.insertSheet("transfer_wellbeing");
    s.appendRow(["ts", "participant_id", "worker_id", "completion_code",
      "phase", "group", "assign_index", "choice", "wellbeing_json",
      "ua", "dpr", "screen", "touch", "refresh_hz", "version", "config_version"]);
  }
  s.appendRow([new Date(body.ts || Date.now()),
    body.participant_id || "", body.worker_id || "", body.completion_code || "",
    body.phase || "", body.group || "", blank(body.assign_index),
    body.choice || "", body.wellbeing_json || "",
    blank(body.ua), blank(body.dpr), blank(body.screen),
    (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
    body.version || "", body.config_version || ""]);
  return out({status: "ok"});
}
```

補足:

- **Firestore への二重書き込み**（`prod_common.js` の `fsPost`）では、これらのレコードは
  `kind` を見る既存の分岐に当てはまらないので `trials` コレクションに入る。
  取り出すときは `modality` が `transfer_` で始まる行、または `phase` 列の有無で絞る。
- 転写検証の記録は `modality` が `transfer_audio` / `transfer_visual` / `transfer_wellbeing` の
  3種類だけ。既存の `answer_key` は参照しない。

---

## 追加3: 集団の自動振り分けと重複参加の照合（`doGet` を差し替え）

クラウドソーシングでは「掲載Aに参加した人は掲載Bに参加できない」を強制できない。
そこで**同時期に走る2集団を1つの入口URLにまとめ**、サーバ側で人数が釣り合うように
振り分ける。フェーズをまたいだ重複（較正に参加した人が検証に来る）は名簿と照合して断る。

```js
// 転写検証実験の集団の振り分け。名簿は transfer_roster シート1枚。
//   GET <exec>?action=transfer_status&phase=calib&participant_id=xxx&worker_id=yyy
//   → {"status":"ok","group":"acal","assign_index":12}
//   → 既に前のフェーズに参加している人には {"status":"ok","blocked":true,"reason":"already_in_calib"}
const TRANSFER_PHASE_GROUPS = { calib: ["acal", "aprime", "aprime"], test: ["b"] };  // 2026-08-24: atest 廃止／較正は1:2

function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.action === "transfer_status") return transferStatus(p);
  return out({status: "ok", message: "iFont experiment endpoint"});
}

function transferStatus(p) {
  const phase = String(p.phase || "");
  const pid = String(p.participant_id || "");
  const groups = TRANSFER_PHASE_GROUPS[phase];
  if (!groups || !pid) return out({status: "error", reason: "phase/participant_id required"});

  const lock = LockService.getScriptLock();
  // 同時アクセスで同じ番号を2人に配らないように、名簿の読み書きは排他にする。
  lock.waitLock(20000);
  try {
    const props = PropertiesService.getScriptProperties();
    const sheetId = props.getProperty("SPREADSHEET_ID");
    const ss = SpreadsheetApp.openById(sheetId);
    let s = ss.getSheetByName("transfer_roster");
    if (!s) {
      s = ss.insertSheet("transfer_roster");
      s.appendRow(["ts", "phase", "participant_id", "worker_id", "group", "assign_index"]);
    }
    const rows = s.getDataRange().getValues();   // [0] はヘッダ
    let inPhase = 0, inGroup = {};
    groups.forEach(function (g) { inGroup[g] = 0; });
    for (let i = 1; i < rows.length; i++) {
      const rPhase = String(rows[i][1]), rPid = String(rows[i][2]), rGroup = String(rows[i][4]);
      // 同じフェーズに同じ人が戻ってきた: 前と同じ割り当てを返す(途中再開と整合)。
      if (rPhase === phase && rPid === pid) {
        return out({status: "ok", group: rGroup, assign_index: Number(rows[i][5]) || 0, returning: true});
      }
      // 検証フェーズに、較正フェーズの参加者が来た: 断る(4集団は互いに独立)。
      if (phase === "test" && rPhase === "calib" && rPid === pid) {
        return out({status: "ok", blocked: true, reason: "already_in_calib"});
      }
      if (rPhase === phase) {
        inPhase++;
        if (inGroup[rGroup] !== undefined) inGroup[rGroup]++;
      }
    }
    // 交互に配るので、2集団の人数は最大1人しか違わない。
    const group = groups[inPhase % groups.length];
    const assignIndex = inGroup[group] || 0;
    s.appendRow([new Date(), phase, pid, String(p.worker_id || ""), group, assignIndex]);
    return out({status: "ok", group: group, assign_index: assignIndex});
  } catch (err) {
    return out({status: "error", reason: String(err)});
  } finally {
    lock.releaseLock();
  }
}
```

### 注意

- **`doGet` は既存のものを置き換える**（今のヘルスチェックの応答は残してある）。
- 名簿に載るのは「ページを開いた人」なので、始めただけで離脱した人も1人ぶん数える。
  集団間の人数は最終的に**完了した人**で釣り合わせたいので、募集の終盤は
  `transfer_trials` の完了人数を見て、必要なら片方の集団だけ追加募集する。
- クラウドソーシング経由でないアクセス（`worker_id` が付かない直接アクセス）は、
  開き直すたびに別人として数えられる。動作確認は研究者モード（`?prod` を付けない）で行い、
  そのときは名簿に問い合わせない（`transfer.js` の `resolveAssignment` を参照）。
- 名簿には氏名等は入らない（参加者ID＝クラウドソーシングの作業者ID、または匿名の乱数）。
- 断り画面は完了コードを出さない。文面は「以前ご参加いただいた分の報酬には影響しません」と
  明記してある（`transfer.js` の `blockedScreen`）。
