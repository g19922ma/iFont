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
 *   actual_soa1, actual_soa2, actual_dur3, ua, dpr, screen, touch, refresh_hz
 *   - actual_* は requestAnimationFrame の実時刻から測った間隔(視覚乙課題)。
 *
 * Schema appended to the "soa_sessions" sheet (乙課題・セッション完了1行):
 *   ts, participant_id, worker_id, completion_code, task, version, speaker,
 *   speaker_name, pitch, n_trials, duration_s, summary_json,
 *   ua, dpr, screen, touch, refresh_hz
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

const SHEET_TRIALS = "trials";

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const props = PropertiesService.getScriptProperties();
    const sheetId = props.getProperty("SPREADSHEET_ID");
    if (!sheetId) throw new Error("SPREADSHEET_ID property not set");

    // 乙課題(較正: pilot_soa_audio / pilot_soa_visual2)は、1試行=2回答のセッション形式。
    // answer_key を使わず client が正誤も計算して送るので、専用シートに1試行1行で記録する。
    if (body.kind === "soa_trial" || body.kind === "soa_done") {
      return handleSoa(sheetId, body);
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
        "ua", "dpr", "screen", "touch", "refresh_hz", "audio_device"]);
    }
    s.appendRow([new Date(body.ts || Date.now()), body.participant_id || "", body.worker_id || "",
      body.completion_code || "", body.task || "", body.version || "", body.speaker || "",
      body.speaker_name || "", body.pitch || "", body.n_trials || "", body.duration_s || "",
      JSON.stringify(body.byLevel || ""),
      blank(body.ua), blank(body.dpr), blank(body.screen),
      (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
      body.audio_device || ""]);
    return out({status: "ok"});
  }
  let s = ss.getSheetByName("soa_trials");
  if (!s) {
    s = ss.insertSheet("soa_trials");
    s.appendRow(["ts", "participant_id", "worker_id", "completion_code", "task", "trial_index",
      "version", "speaker", "pitch", "S", "c1", "c2", "c3", "resp1", "resp2",
      "correct1", "correct2",
      "actual_soa1", "actual_soa2", "actual_dur3",
      "ua", "dpr", "screen", "touch", "refresh_hz", "audio_device"]);
  }
  s.appendRow([new Date(body.ts || Date.now()), body.participant_id || "", body.worker_id || "",
    body.completion_code || "", body.task || "", (body.trial_index === undefined ? "" : body.trial_index),
    body.version || "", body.speaker || "", body.pitch || "", body.S,
    body.c1, body.c2, body.c3, body.resp1, body.resp2, !!body.correct1, !!body.correct2,
    // 実測の間隔(視覚乙課題のみ。聴覚乙課題では送られてこないので空欄)。
    blank(body.actual_soa1), blank(body.actual_soa2), blank(body.actual_dur3),
    blank(body.ua), blank(body.dpr), blank(body.screen),
    (body.touch === undefined ? "" : !!body.touch), blank(body.refresh_hz),
    body.audio_device || ""]);
  return out({status: "ok", correct1: !!body.correct1, correct2: !!body.correct2});
}

function doGet(e) {
  // Health check.
  return out({status: "ok", message: "iFont experiment endpoint"});
}

function out(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
