/**
 * Google Apps Script backend for the iFont visual-Kikiwake experiment.
 *
 * Setup (one-time):
 *   1. Create a Google Sheet. Note its ID (from the URL).
 *   2. Tools → Script editor → paste this file.
 *   3. Project Settings → Script Properties:
 *        SPREADSHEET_ID = <your sheet id>
 *        ANSWER_KEY     = (paste the entire contents of answer_key.json)
 *   4. Deploy → New deployment → Web app:
 *        Execute as: Me
 *        Who has access: Anyone
 *      → copy the /exec URL into experiment.js → SUBMIT_URL.
 *   5. The first request you make will trigger an authorization prompt.
 *
 * Schema appended to the "trials" sheet (frac課題):
 *   ts, participant_id, worker_id, completion_code, stimulus_id,
 *   response_char, correct_char, correct, modality, q_set,
 *   k_index, k, r, frac_index, frac, n_choices, font_voice, mode,
 *   replays, rt_ms, is_catch, c1, algo, pitch_scheme, bigram_freq,
 *   actual_ms, actual_frames, ua, dpr, screen, touch, refresh_hz,
 *   char_ms, overlap, tau_ms
 *   - char_ms は視覚1文字課題の提示速度の要因。1文字にかける時間 (ミリ秒) で、
 *     200 (毎秒5.0モーラ・N5聴解相当) と 133 (毎秒7.5モーラ・アナウンサー相当) の2水準。
 *     実際の露光時間は frac × char_ms になる。他の課題では空欄。
 *   - overlap / tau_ms は視覚2文字課題の「先行文字の残存」の要因。
 *     overlap は "none" (統制: C1 が消えてから C2 が出る) か
 *     "decay" (C2 の提示中も C1 が alpha=exp(-t/tau) で薄くなりながら重なって残る)。
 *     tau_ms は減衰の時定数で、統制条件では空欄。C2 の可視時間は条件によらず同一なので、
 *     この要因で増えるのは C1 の可視時間だけである。他の課題では空欄。
 *   - actual_ms / actual_frames は視覚課題の実測。名目の提示時間
 *     (char_ms*frac/100) は画面のリフレッシュ周期に量子化されるため、
 *     ターゲット文字を最初に描画したフレームから消去したフレームまでの
 *     実時間とフレーム数をクライアントが測って送る。聴覚課題では空欄。
 *   - ua / dpr / screen / touch / refresh_hz は端末環境。prod_common.js の
 *     PROD.setEnv() で各ページが登録し、送信本文に自動で載る。
 *   - rt_ms は「刺激の提示が始まってから回答するまで」。frac課題はクリック開始
 *     (自己ペース)にしたため、開始ボタンを押すまでの待ち時間は含まない。
 *
 * Schema appended to the "soa_trials" sheet (乙課題・1試行1行):
 *   ts, participant_id, worker_id, completion_code, task, trial_index,
 *   version, speaker, pitch, S, c1, c2, c3, resp1, resp2, correct1, correct2,
 *   actual_soa1, actual_soa2, actual_dur3, ua, dpr, screen, touch, refresh_hz,
 *   audio_device, resume_count
 *   - actual_* は requestAnimationFrame の実時刻から測った間隔(視覚乙課題)。
 *   - resume_count はその試行までの途中再開の回数(0=中断なし)。
 *
 * Schema appended to the "soa_sessions" sheet (乙課題・セッション完了1行):
 *   ts, participant_id, worker_id, completion_code, task, version, speaker,
 *   speaker_name, pitch, n_trials, duration_s, summary_json,
 *   ua, dpr, screen, touch, refresh_hz, audio_device, resume_count, resume_gap_s
 *
 * 注意: シートのヘッダ行はシートを新規作成するときだけ書き込む。既存のシートに
 *       列を足したときは、ヘッダ行を手で追記するか、シートを作り直すこと。
 *
 * One shared ANSWER_KEY serves the pre-rendered pools. Visual entries carry
 * {font, mode:"f1", k_index, k, r}; audio (truncation) entries carry
 * {modality:"audio", voice, mode:"f1_audio_trunc", frac_index, frac}.
 * The handler logs whichever level fields are present (k* for visual,
 * frac* for audio) and leaves the other blank.
 *
 * 2文字課題 / 1文字課題 (2026-07-02 設計改訂):
 *   - audio2char: answer_key_2char.json のエントリは "audio2char|<id>" を鍵に
 *     {c1, c2, target, f0_c1_hz, f0_c2_hz, corrected, bigram_freq} を持つ。
 *     正解は entry.target。client は pitch_scheme ("B3-E4") と frac を送る。
 *   - audio1char: answer_key_1char.json のエントリは "audio1char|<id>" を鍵に
 *     {char, target, f0_hz, corrected} を持つ。正解は entry.target。
 *     client は pitch_scheme ("B3") と frac を送る。C1=∅ (発話先頭) の特殊ケース。
 *   - visual2char / visual1char: 刺激はブラウザ側で合成するため answer_key が無い。
 *     client が target_char (正解) を申告し、サーバはそれで採点・記録する。
 *     申告ベースであることは全課題共通のチート耐性方針 (catch 試行 + RT フィルタ)
 *     の範囲内。algo (提示アルゴリズム) と font も記録する。
 *   複数の answer_key ファイル (answer_key.json / _2char / _1char) は、本番デプロイ時に
 *   マージして GAS の ANSWER_KEY プロパティに貼る (鍵の接頭辞で衝突しない)。
 *
 * Notes:
 *   - Client posts with mode: "no-cors", so the response body is not read
 *     by the client; we still return text/plain for diagnostic via curl.
 *   - One row per trial. Aggregate (catch accuracy, exclusions) in the sheet
 *     or downstream analysis.
 *   - ANSWER_KEY is held as a Script Property and parsed on each request.
 *     ~100KB JSON parses in <50ms; cache via CacheService if traffic grows.
 */

// =========================================================================
// 転写検証実験(iFont transfer)の版
// -------------------------------------------------------------------------
// gas/code.gs をそのまま土台にして、gas/transfer_patch.md の3つの差分を当てた。
// 何を足したかは `diff gas/code.gs gas_transfer/code.gs` で一目で分かる。
//
// このファイルは**転写検証専用のスプレッドシートに紐づいた**スクリプト
// (コンテナバインド型)。したがって:
//   ・保存先のシートIDは、スクリプトプロパティではなく下の定数に直書きしてある
//     (clasp から一発で入れ直せるようにするため。秘密の値ではない)。
//   ・ANSWER_KEY は使わない(転写検証の採点は client が申告する target_char で行う)。
//     既存の課題(乙課題・frac課題)の処理も残してあるが、この配信先URLは転写検証の
//     ページからしか呼ばれない(prod_common.js の SUBMIT_URL は空のままにしてある)。
//
// 入れ直し方: リポジトリの gas_transfer/ で
//   clasp push -f  →  clasp deploy -i <デプロイID> -d "説明"
// デプロイIDを変えなければ /exec URL は変わらない。
// =========================================================================

// 転写検証の記録先スプレッドシート。**いまは下見用**。
// 本番は新しいシートを作ってここを差し替える(下見の記録と混ぜないため。
// 掲載前チェックリスト G-1)。
const SPREADSHEET_ID = "1gsJ6_Rucv5uoKsgrs_m-Y41sxh5B0qcPKWyHkxveKMs";

// 疎通確認・画面確認で作った行の目印。参加者IDがこのどれかで始まる行は「試し打ち」と
// みなし、is_test 列に true を立て、action=transfer_purge_test でまとめて消せるようにする。
// 決め打ちの文字列だけを見るので、本物の参加者のデータに手が届くことはない
// (クラウドソーシングの作業者IDがこの形になることはない)。
const TEST_PID_PREFIXES = ["curltest-", "uitest-"];
function isTestPid(pid) {
  const v = String(pid || "");
  for (let i = 0; i < TEST_PID_PREFIXES.length; i++) {
    if (v.indexOf(TEST_PID_PREFIXES[i]) === 0) return true;
  }
  return false;
}

// ブラウザ側から渡ってくる試し打ちの申告。
// transfer_config.js の pre_launch（掲載前フラグ）が true のあいだ、ページは
// 参加者IDに関係なく is_test=1 を送ってくる。参加者IDの頭だけを見ていると、
// URL から wid= が落ちて本番モード扱いになった回を拾えないため
// （2026-08-21 に実際に起き、名簿に本物の行が1件混ざった）。
// 値は GET のクエリなら "1"/"0"、POST の本文なら true/false で来る。
function isTestFlag(v) {
  const s = String(v == null ? "" : v).toLowerCase();
  return s === "1" || s === "true" || s === "yes";
}

// この記録／この参加者を試し打ちとして扱うか。**判定はここ1か所に集める。**
function isTestRun(pid, flag) {
  return isTestPid(pid) || isTestFlag(flag);
}

const SHEET_TRIALS = "trials";

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const props = PropertiesService.getScriptProperties();
    const sheetId = SPREADSHEET_ID;
    if (!sheetId) throw new Error("SPREADSHEET_ID not set");

    // 乙課題(較正: pilot_soa_audio / pilot_soa_visual2)は、1試行=2回答のセッション形式。
    // answer_key を使わず client が正誤も計算して送るので、専用シートに1試行1行で記録する。
    if (body.kind === "soa_trial" || body.kind === "soa_done") {
      return handleSoa(sheetId, body);
    }

    // ---- 追加1・2: 転写検証実験(transfer_calib / transfer_test)------------
    // 既存の trials シートとは別のシートに書く(列構成が違うため。既存シートの
    // ヘッダを触らずに済む)。
    if (body.kind === "transfer_wellbeing" || body.modality === "transfer_wellbeing") {
      return handleTransferWellbeing(sheetId, body);
    }
    if (typeof body.modality === "string" && body.modality.indexOf("transfer_") === 0) {
      return handleTransferTrial(sheetId, body);
    }

    const answerKeyJson = props.getProperty("ANSWER_KEY");
    if (!answerKeyJson) throw new Error("ANSWER_KEY property not set");
    const answerKey = JSON.parse(answerKeyJson);

    // 素の id → 見つからなければ modality 接頭辞つきの鍵 (2文字課題の answer_key)。
    let stim = answerKey[body.stimulus_id];
    if (!stim && body.modality) {
      stim = answerKey[body.modality + "|" + body.stimulus_id];
    }
    let correctChar;
    if (stim) {
      // 事前レンダリング系: 正解は answer_key 側。旧形式は answer、2文字課題は target。
      correctChar = (stim.answer !== undefined) ? stim.answer : stim.target;
    } else if (body.modality === "visual2char" || body.modality === "visual1char") {
      // ブラウザ側合成のため answer_key が無い。client 申告の正解で採点する。
      if (!body.target_char) {
        return out({status: "error", reason: body.modality + " requires target_char"});
      }
      stim = {};
      correctChar = body.target_char;
    } else {
      return out({status: "error", reason: "unknown stimulus_id"});
    }
    const correct = body.response_char === correctChar;
    const modality = body.modality || stim.modality || "visual";
    // visual entries store the font under "font"; audio entries the voice.
    // visual2char は client が font を送る。
    const fontVoice = stim.font || stim.voice || body.font || "";
    // Level fields: visual uses k* (k=null means ∞/catch); audio uses frac*.
    // Log whichever the entry has; leave the other column blank.
    // 2文字課題の frac は client が試行ごとに決めるため body 側から取る。
    const hasK = (stim.k_index !== undefined);
    const kIdx = hasK ? stim.k_index : "";
    const kVal = !hasK ? "" : (stim.k === null ? "Inf" : stim.k);
    const rVal = hasK ? stim.r : "";
    const hasFrac = (stim.frac_index !== undefined) || (body.frac !== undefined);
    const fracIdx = (stim.frac_index !== undefined) ? stim.frac_index : "";
    const fracVal = (stim.frac !== undefined) ? stim.frac
                  : (body.frac !== undefined ? body.frac : "");
    // 2文字課題の追加列。c1 は answer_key (audio2char) か client 申告 (visual2char)。
    const c1Char = stim.c1 || body.c1 || "";
    const algo = body.algo || "";
    const pitchScheme = body.pitch_scheme || "";
    const bigramFreq = (stim.bigram_freq !== undefined) ? stim.bigram_freq : "";

    const sheet = SpreadsheetApp.openById(sheetId);
    let trials = sheet.getSheetByName(SHEET_TRIALS);
    if (!trials) {
      trials = sheet.insertSheet(SHEET_TRIALS);
      trials.appendRow([
        "ts", "participant_id", "worker_id", "completion_code",
        "stimulus_id", "response_char", "correct_char", "correct",
        "modality", "q_set", "k_index", "k", "r", "frac_index", "frac",
        "n_choices", "font_voice", "mode", "replays", "rt_ms", "is_catch",
        "c1", "algo", "pitch_scheme", "bigram_freq",
        "actual_ms", "actual_frames", "ua", "dpr", "screen", "touch", "refresh_hz",
        // 2026-08 に追加した実験要因の列。既存シートに足すときは末尾に追記すること。
        "char_ms", "overlap", "tau_ms",
        // 再生機器の申告(聴覚課題のみ。スピーカー/有線。無線は参加不可)
        "audio_device",
        // 1文字統合セッション(v3)のブロック釣り合い(AVAV等)と何ブロック目か
        "block_order", "block_pos",
      ]);
    }
    trials.appendRow([
      new Date(body.ts || Date.now()),
      body.participant_id || "",
      body.worker_id || "",
      body.completion_code || "",
      body.stimulus_id,
      body.response_char,
      correctChar,
      correct,
      modality,
      (stim.q_set !== undefined ? stim.q_set : (body.q_set || "")),
      kIdx,
      kVal,
      rVal,
      fracIdx,
      fracVal,
      body.n_choices,
      fontVoice,
      stim.mode || "",
      (body.replays === undefined ? "" : body.replays),
      body.rt_ms,
      !!body.is_catch,
      c1Char,
      algo,
      pitchScheme,
      bigramFreq,
      // 視覚課題の実測タイミング(聴覚課題では送られてこないので空欄)と端末環境。
      blank(body.actual_ms),
      blank(body.actual_frames),
      blank(body.ua),
      blank(body.dpr),
      blank(body.screen),
      (body.touch === undefined ? "" : !!body.touch),
      blank(body.refresh_hz),
      // 2026-08 に追加した実験要因。視覚1文字課題は char_ms、視覚2文字課題は overlap/tau_ms を送る。
      blank(body.char_ms),
      blank(body.overlap),
      blank(body.tau_ms),
      body.audio_device || "",
      blank(body.block_order),
      blank(body.block_pos),
    ]);

    return out({status: "ok", correct: correct});
  } catch (err) {
    return out({status: "error", reason: String(err)});
  }
}

// 値が無いときにセルを空欄にする(0 や false を落とさないための小さな補助)。
function blank(v) {
  return (v === undefined || v === null) ? "" : v;
}

// 乙課題(較正)のセッション記録。soa_trials シートに1試行1行、soa_sessions に完了1行。
// クライアント(prod_common.js)は端末環境 ua/dpr/screen/touch/refresh_hz を毎回付けて送る。
function handleSoa(sheetId, body) {
  const ss = SpreadsheetApp.openById(sheetId);
  if (body.kind === "soa_done") {
    let s = ss.getSheetByName("soa_sessions");
    if (!s) {
      s = ss.insertSheet("soa_sessions");
      s.appendRow(["ts", "participant_id", "worker_id", "completion_code", "task",
        "version", "speaker", "speaker_name", "pitch", "n_trials", "duration_s", "summary_json",
        "ua", "dpr", "screen", "touch", "refresh_hz", "audio_device",
        "resume_count", "resume_gap_s"]);
    }
    s.appendRow([new Date(body.ts || Date.now()), body.participant_id || "", body.worker_id || "",
      body.completion_code || "", body.task || "", body.version || "", body.speaker || "",
      body.speaker_name || "", body.pitch || "", body.n_trials || "", body.duration_s || "",
      JSON.stringify(body.byLevel || ""),
      blank(body.ua), blank(body.dpr), blank(body.screen),
      (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
      body.audio_device || "",
      // 途中再開(同一ブラウザ)の統計。0なら中断なしで完走。
      blank(body.resume_count), blank(body.resume_gap_s)]);
    return out({status: "ok"});
  }
  let s = ss.getSheetByName("soa_trials");
  if (!s) {
    s = ss.insertSheet("soa_trials");
    s.appendRow(["ts", "participant_id", "worker_id", "completion_code", "task", "trial_index",
      "version", "speaker", "pitch", "S", "c1", "c2", "c3", "resp1", "resp2",
      "correct1", "correct2",
      "actual_soa1", "actual_soa2", "actual_dur3",
      "ua", "dpr", "screen", "touch", "refresh_hz", "audio_device", "resume_count"]);
  }
  s.appendRow([new Date(body.ts || Date.now()), body.participant_id || "", body.worker_id || "",
    body.completion_code || "", body.task || "", (body.trial_index === undefined ? "" : body.trial_index),
    body.version || "", body.speaker || "", body.pitch || "", body.S,
    body.c1, body.c2, body.c3, body.resp1, body.resp2, !!body.correct1, !!body.correct2,
    // 実測の間隔(視覚乙課題のみ。聴覚乙課題では送られてこないので空欄)。
    blank(body.actual_soa1), blank(body.actual_soa2), blank(body.actual_dur3),
    blank(body.ua), blank(body.dpr), blank(body.screen),
    (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
    body.audio_device || "",
    // その試行までの再開回数(0=中断なし)。中断直後の回答を解析で区別できる。
    blank(body.resume_count)]);
  return out({status: "ok", correct1: !!body.correct1, correct2: !!body.correct2});
}

// ---- 追加3: 集団の自動振り分けと重複参加の照合 -----------------------------
// クラウドソーシングでは「掲載Aに参加した人は掲載Bに参加できない」を強制できない。
// そこで同時期に走る2集団を1つの入口URLにまとめ、サーバ側で人数が釣り合うように
// 振り分ける。フェーズをまたいだ重複(較正に参加した人が検証に来る)は名簿と照合して断る。
// ⚠ ここから下は**切り戻し用の控え**である。2026-08-21 に名簿と記録の本番は
//    Firestore へ移した(experiment/transfer_firestore.js)。
//    transfer_config.js の backend.roster / backend.logging を "gas" に戻したときと、
//    Firestore が落ちたときの受け皿(fallback)としてだけ動く。
//    **Firestore 側と同じ規則を保つこと**(集団の表と、下の重複拒否の表)。

const TRANSFER_PHASE_GROUPS = {
  // 2026-08-24: 較正フェーズは掲載を2本に分けたので、実際には自動振り分けを使わない
  // (入口ページが &group=acal / &group=aprime を送ってくる)。この並びは
  // 「ありうる集団の一覧」として使う。transfer_config.js の phases と同じにすること。
  calib: ["acal", "aprime"],
  // 検証フェーズ。2026-08-24 に検証用の音声集団(atest)を廃止したので群Bだけになった。
  // 集団は1つなので振り分けは起きず、連番だけ配る。
  test: ["b"],
  // 群C(見え心地)。集団は1つだけなので振り分けは起きず、連番だけ配る。
  comfort: ["c"],
};

// 「このフェーズに来た人が、**過去にどのフェーズに出ていたら**断るか」の表。
// 4つの集団(acal・aprime・b・c)は互いに独立なので、同じ人が2つに出ると比較が濁る。
// 群Cと検証フェーズは同時期に走るので、**どちら向きにも**塞ぐ必要がある
// (掲載前チェックリスト H-1)。較正は一番先に走るので断る相手がいない。
// transfer_config.js の phase_blocks と同じ内容にそろえてある。
const TRANSFER_PHASE_BLOCKS = {
  calib: [],
  test: [
    { phase: "calib", reason: "already_in_calib" },
    { phase: "comfort", reason: "already_in_comfort" },
  ],
  comfort: [
    { phase: "calib", reason: "already_in_other_phase" },
    { phase: "test", reason: "already_in_other_phase" },
  ],
};
const TRANSFER_SHEETS = ["transfer_trials", "transfer_wellbeing", "transfer_roster"];

function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.action === "transfer_status") return transferStatus(p);
  if (p.action === "transfer_health") return transferHealth();
  if (p.action === "transfer_purge_test") return transferPurgeTest();
  // Health check.
  return out({status: "ok", message: "iFont experiment endpoint"});
}

// シートの1行1行について「試し打ちの行か」を返す配列を作る。
// **記録したときの is_test 列を見る**のが本筋である(2026-08-22 に切り替えた)。
// 掲載前フラグ(transfer_config.js の pre_launch)で付いた印は、参加者IDの頭が
// curltest- / uitest- とはかぎらないので、IDの形だけでは拾えないため。
// 列が無い古いシートのために、IDの頭も見る作りは残してある。
function transferTestFlags(sheet) {
  const last = sheet.getLastRow();
  if (last < 2) return [];
  const width = sheet.getLastColumn();
  const header = sheet.getRange(1, 1, 1, width).getValues()[0];
  let testCol = -1, pidCol = -1;
  for (let i = 0; i < header.length; i++) {
    if (String(header[i]) === "is_test") testCol = i;
    if (String(header[i]) === "participant_id") pidCol = i;
  }
  const rows = sheet.getRange(2, 1, last - 1, width).getValues();
  return rows.map(function (r) {
    const byFlag = (testCol >= 0) && isTestFlag(r[testCol]);
    const byPid = (pidCol >= 0) && isTestPid(r[pidCol]);
    return byFlag || byPid;
  });
}

// 各シートの行数(ヘッダを除く)と、そのうち試し打ちの行数を返す。
// POSTした行が本当にシートに入ったかを curl だけで確かめるために使う。
function transferHealth() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const counts = {}, tests = {};
  TRANSFER_SHEETS.forEach(function (name) {
    const s = ss.getSheetByName(name);
    if (!s) { counts[name] = 0; tests[name] = 0; return; }
    counts[name] = Math.max(0, s.getLastRow() - 1);
    tests[name] = transferTestFlags(s).filter(function (t) { return t; }).length;
  });
  return out({status: "ok", spreadsheet_id: SPREADSHEET_ID, rows: counts, test_rows: tests});
}

// 試し打ちの行(is_test の印が付いた行)だけを消す。
// 印の付いた行しか触らないので、本物の参加者のデータには手が届かない。
function transferPurgeTest() {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const removed = {};
    TRANSFER_SHEETS.forEach(function (name) {
      removed[name] = 0;
      const s = ss.getSheetByName(name);
      if (!s) return;
      const flags = transferTestFlags(s);
      // 下から消す(消すたびに行番号がずれるのを避ける)。
      for (let i = flags.length - 1; i >= 0; i--) {
        if (flags[i]) { s.deleteRow(i + 2); removed[name]++; }
      }
    });
    return out({status: "ok", removed: removed});
  } catch (err) {
    return out({status: "error", reason: String(err)});
  } finally {
    lock.releaseLock();
  }
}

//   GET <exec>?action=transfer_status&phase=calib&participant_id=xxx&worker_id=yyy
//   → {"status":"ok","group":"acal","assign_index":12}
//   → 既に前のフェーズに参加している人には {"status":"ok","blocked":true,"reason":"already_in_calib"}
//
// 試し打ち（is_test）の扱い（2026-08-22 に足した。Firestore 版と同じ考え方）:
//   ・&is_test=1 が付いているか、参加者IDの頭が curltest- / uitest- なら試し打ち。
//   ・名簿には is_test = true の行として載せる。
//   ・**人数を数えるとき、試し打ちの行と本番の行を混ぜない。** 本番の人は本番の行だけを
//     数えた順番で、試し打ちの人は試し打ちの行だけを数えた順番で振り分ける。
//     こうしないと、動作確認を1回するたびに本番の連番が1つ進み、聴覚と視覚の
//     交互の振り分けがずれる（2026-08-21 に実際に起きた）。
function transferStatus(p) {
  const phase = String(p.phase || "");
  const pid = String(p.participant_id || "");
  const allGroups = TRANSFER_PHASE_GROUPS[phase];
  if (!allGroups || !pid) return out({status: "error", reason: "phase/participant_id required"});
  // 入口ページが集団を決め打ちしてきたとき(&group=acal など)は、その集団だけから配る。
  // 較正フェーズは所要と報酬が違うので掲載を2本に分けており、どちらの掲載から来たかを
  // サーバは URL のこの印でしか知れない(2026-08-24)。
  // 知らない集団名は無視する(決め打ちなしと同じ扱い)。
  const forced = String(p.group || "");
  const groups = (forced && allGroups.indexOf(forced) >= 0) ? [forced] : allGroups;
  const testRun = isTestRun(pid, p.is_test);

  const lock = LockService.getScriptLock();
  // 同時アクセスで同じ番号を2人に配らないように、名簿の読み書きは排他にする。
  lock.waitLock(20000);
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    let s = ss.getSheetByName("transfer_roster");
    if (!s) {
      s = ss.insertSheet("transfer_roster");
      s.appendRow(["ts", "phase", "participant_id", "worker_id", "group", "assign_index", "is_test"]);
    }
    const rows = s.getDataRange().getValues();   // [0] はヘッダ
    // inPhase は「この掲載から何人目か」。決め打ちのときはその集団の人数だけを数える
    // (もう一方の掲載の人数で番号が飛ばないように)。
    let inPhase = 0, inGroup = {};
    allGroups.forEach(function (g) { inGroup[g] = 0; });

    // この人が過去に出たフェーズを集めながら、そのフェーズの人数も数える。
    // **1回のなめで両方やる**(名簿が伸びても読み直さない)。
    const seenPhases = {};
    let mine = null;
    for (let i = 1; i < rows.length; i++) {
      const rPhase = String(rows[i][1]), rPid = String(rows[i][2]), rGroup = String(rows[i][4]);
      const rTest = isTestFlag(rows[i][6]);
      if (rPid === pid) {
        seenPhases[rPhase] = true;
        // 同じフェーズに同じ人が戻ってきた: 前と同じ割り当てを返す(途中再開と整合)。
        if (rPhase === phase) mine = {group: rGroup, assign_index: Number(rows[i][5]) || 0};
      }
      // 人数の勘定は**同じ種類の行どうしだけ**。試し打ちの行は本番の連番を進めない。
      if (rPhase === phase && rTest === testRun) {
        // 決め打ちのときは、その集団の行だけを「何人目か」に数える。
        if (!forced || rGroup === forced) inPhase++;
        if (inGroup[rGroup] !== undefined) inGroup[rGroup]++;
      }
    }

    // 開き直しは、断る判定より**先**に見る(自分のフェーズには当然いるため)。
    if (mine) {
      // 決め打ちの掲載に、もう一方の掲載で登録済みの人が来た＝同じフェーズの
      // 別の集団にすでに出ている。ブラウザ側でも弾いているが、ここでも断る。
      if (forced && mine.group !== forced) {
        return out({status: "ok", blocked: true, reason: "already_in_calib"});
      }
      return out({status: "ok", group: mine.group, assign_index: mine.assign_index, returning: true});
    }
    // 断るべきフェーズに出ていたか(較正→検証・較正→群C・群C→検証・検証→群C)。
    const blocks = TRANSFER_PHASE_BLOCKS[phase] || [];
    for (let b = 0; b < blocks.length; b++) {
      if (seenPhases[blocks[b].phase]) {
        return out({status: "ok", blocked: true, reason: blocks[b].reason});
      }
    }
    // 交互に配るので、2集団の人数は最大1人しか違わない。
    const group = groups[inPhase % groups.length];
    const assignIndex = inGroup[group] || 0;
    s.appendRow([new Date(), phase, pid, String(p.worker_id || ""), group, assignIndex, testRun]);
    return out({status: "ok", group: group, assign_index: assignIndex});
  } catch (err) {
    return out({status: "error", reason: String(err)});
  } finally {
    lock.releaseLock();
  }
}

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
      "is_filler", "is_decoy", "check_kind", "is_catch", "n_choices",
      // 出題範囲の学習を測る列(2026-08-24 追加)
      "resp_in_target_set", "resp_in_frequent_set", "n_frequent",
      // 実測
      "rt_ms", "actual_ms", "actual_frames", "actual_s", "progress_source", "base_anim_ms",
      // 端末・再開・版
      "ua", "dpr", "screen", "touch", "refresh_hz", "audio_device",
      "resume_count", "resume_gap_s", "version", "config_version",
      // 疎通確認で作った行の目印(分析からは必ず外す)
      "is_test",
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
    (body.is_decoy === undefined ? "" : !!body.is_decoy),
    body.check_kind || "", (body.is_catch === undefined ? "" : !!body.is_catch),
    blank(body.n_choices),
    blank(body.resp_in_target_set), blank(body.resp_in_frequent_set), blank(body.n_frequent),
    blank(body.rt_ms), blank(body.actual_ms), blank(body.actual_frames), blank(body.actual_s),
    body.progress_source || "", blank(body.base_anim_ms),
    blank(body.ua), blank(body.dpr), blank(body.screen),
    (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
    body.audio_device || "",
    blank(body.resume_count), blank(body.resume_gap_s),
    body.version || "", body.config_version || "",
    isTestRun(body.participant_id, body.is_test),
  ]);
  return out({status: "ok", correct: correct});
}

// 見え心地の評価と、完走レコード。どちらも1行ずつ。clip ごとの7件法は JSON のまま入れる
// (方式×代表字の本数が設定で変わるため、列を固定しない)。
//
// このシートには3種類の行が入る。**record_kind 列で見分ける。**
//   ""/"final" … 見え心地の回答(1参加者1行)。**分析はこれを読む**
//   "clip"     … 群Cの1本ぶんの中間レコード(12行/人)。最後の1行が落ちたときの保険
//   "session"  … 完走レコード(1セッション1行)。**承認の判定はこの行だけで済む**
//                (completion_code・n_trials・duration_s・send_failures が入っている)
//
// ⚠ すでに古い列で作られたシートには、新しい列(record_kind 以降)の見出しが無い。
//   GAS へ切り戻すときは、シートを作り直すか、見出し行に手で足すこと。
function handleTransferWellbeing(sheetId, body) {
  const ss = SpreadsheetApp.openById(sheetId);
  let s = ss.getSheetByName("transfer_wellbeing");
  if (!s) {
    s = ss.insertSheet("transfer_wellbeing");
    s.appendRow(["ts", "participant_id", "worker_id", "completion_code",
      "record_kind", "modality",
      "phase", "group", "assign_index", "assign_source",
      "choice", "wellbeing_json",
      "n_trials", "duration_s", "send_failures", "send_retries",
      "ua", "dpr", "screen", "touch", "refresh_hz", "version", "config_version",
      "is_test"]);
  }
  s.appendRow([new Date(body.ts || Date.now()),
    body.participant_id || "", body.worker_id || "", body.completion_code || "",
    body.record_kind || "", body.modality || "",
    body.phase || "", body.group || "", blank(body.assign_index),
    body.assign_source || "",
    body.choice || "", body.wellbeing_json || "",
    blank(body.n_trials), blank(body.duration_s),
    blank(body.send_failures), blank(body.send_retries),
    blank(body.ua), blank(body.dpr), blank(body.screen),
    (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
    body.version || "", body.config_version || "",
    isTestRun(body.participant_id, body.is_test)]);
  return out({status: "ok"});
}

function out(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
