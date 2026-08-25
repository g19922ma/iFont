/* =========================================================================
 * transfer_firestore.js — 転写検証実験の保存先を Firestore にする窓口
 * -------------------------------------------------------------------------
 * これがやることは2つだけ。
 *
 *   1. **名簿**（どの集団に入れるか・集団の中で何番目か・重複参加でないか）
 *   2. **記録の保存**（1問1件の回答と、見え心地の評価）
 *
 * なぜ GAS から移すのか。GAS は応答の本体を script.googleusercontent.com へ
 * リダイレクトして返す作りで、この中継が一過性で失敗し、JSON のかわりに HTML の
 * エラーページを返すことがある（2026-08-21 に実機で発生し、サーバは正常なのに
 * 参加者をお断りしてしまった）。Firestore は REST を直接叩くので中継が無い。
 *
 * 認証はしない。参加者にログインさせると、同意より前に個人を識別することになり、
 * いまの倫理設計と噛み合わないためである。かわりに**ルールで書ける形を絞る**
 * （firebase/firestore.transfer.rules）。
 *
 * ⚠ ウェブAPIキーについて。Firebase のウェブAPIキーは、設計上ブラウザに埋め込んで
 *   公開するものである。守るのはキーではなく**ルール**で、いまのルールは
 *   「作れるだけ・回答は読めない・消せない」に絞ってある。だからリポジトリに
 *   入れてよい（GAS の DUMP_TOKEN のような「本来秘密であるべき値」とは性質が違う）。
 *
 * -------------------------------------------------------------------------
 * 置いてあるもの（Firestore のコレクション）
 * -------------------------------------------------------------------------
 *   transfer_trials     1問1件の回答
 *   transfer_wellbeing  見え心地の評価（群Bの末尾ぶんと群Cぶん）。1参加者1件
 *   transfer_roster     名簿。1参加者1件。ID は "<フェーズ>_<参加者ID>"
 *   transfer_counters   採番。フェーズごとに1件（ID は "calib"/"test"/"comfort"）。
 *                       中身は n（そのフェーズの通し番号）ひとつだけ。
 *                       試し打ちは別のカウンタ（"calib__test" など）から配るので、
 *                       動作確認をしても本番の連番は動かない
 *
 * -------------------------------------------------------------------------
 * 採番が衝突しない理由（トランザクションを書いていない理由）
 * -------------------------------------------------------------------------
 * 「読んで、1足して、書き戻す」をやると、同時に2人来たとき同じ番号を配ってしまう。
 * ふつうはトランザクションで囲むが、Firestore には **increment 変換**という、
 * サーバ側で不可分に1増やす仕組みがある。こちらのほうが強く、往復も1回で済む。
 *
 * さらに、**増やしたあとの値が書き込みの応答に入って返ってくる**（transformResults）。
 * だから「カウンタの読み出し」を許可しなくても、自分の番号が分かる。
 * ルール側では「n が 1 だけ増える更新」しか通していないので、番号を飛ばしたり
 * 巻き戻したりもできない。
 * ========================================================================= */
(function (root) {
  "use strict";

  // 設定は読み込み時ではなく**呼ばれるたび**に見る。
  // （Node での試験が、読み込んだあとに設定を差し替えられるようにするため。）
  function cfg() { return (root.TRANSFER_CONFIG || {}); }
  function fs() { return cfg().firestore || {}; }

  function enabled() {
    var f = fs();
    return !!(f.enabled && f.project_id && f.api_key);
  }

  function docRoot() {
    return "projects/" + fs().project_id + "/databases/(default)/documents";
  }
  function baseUrl() {
    return "https://firestore.googleapis.com/v1/" + docRoot();
  }
  function keyQ() { return "key=" + encodeURIComponent(fs().api_key); }
  function timeoutMs() { return Number(fs().timeout_ms) || 10000; }

  // ---- ドキュメントIDに使えない字を落とす -------------------------------
  // Firestore のドキュメントIDは "/" を含められない。"." と ".." も使えない。
  // 参加者IDはクラウドソーシングの作業者IDなので、ふつうは英数字だけだが、
  // 変なものが来ても名簿が壊れないようにしておく。
  function docSafe(s) {
    var t = String(s == null ? "" : s).replace(/[\/\\.#\[\]*?\s]/g, "_");
    if (t === "" || t === "_" || t === "__") t = "_empty_";
    return t.slice(0, 180);
  }

  // ---- JS の値 → Firestore のフィールド型 --------------------------------
  // Firestore の REST は値に型の名札を付ける。整数と小数を取り違えると、
  // ルールの `is int` に落ちたり、解析側で型が揺れたりするので注意して分ける。
  function toValue(v) {
    if (v === null || v === undefined) return { nullValue: null };
    if (typeof v === "boolean") return { booleanValue: v };
    if (typeof v === "number") {
      if (!isFinite(v)) return { stringValue: String(v) };     // NaN / Infinity は文字で
      return Number.isInteger(v) ? { integerValue: String(v) } : { doubleValue: v };
    }
    if (Array.isArray(v)) return { arrayValue: { values: v.map(toValue) } };
    if (typeof v === "object") return { mapValue: { fields: toFields(v) } };
    return { stringValue: String(v) };
  }
  function toFields(obj) {
    var out = {};
    Object.keys(obj || {}).forEach(function (k) {
      if (obj[k] === undefined) return;                        // 未定義の列は送らない
      out[k] = toValue(obj[k]);
    });
    return out;
  }

  // ---- Firestore のフィールド型 → JS -------------------------------------
  function fromValue(v) {
    if (!v || typeof v !== "object") return null;
    if ("nullValue" in v) return null;
    if ("booleanValue" in v) return !!v.booleanValue;
    if ("integerValue" in v) return Number(v.integerValue);
    if ("doubleValue" in v) return Number(v.doubleValue);
    if ("stringValue" in v) return v.stringValue;
    if ("timestampValue" in v) return v.timestampValue;
    if ("arrayValue" in v) return ((v.arrayValue && v.arrayValue.values) || []).map(fromValue);
    if ("mapValue" in v) return fromFields((v.mapValue && v.mapValue.fields) || {});
    return null;
  }
  function fromFields(f) {
    var out = {};
    Object.keys(f || {}).forEach(function (k) { out[k] = fromValue(f[k]); });
    return out;
  }

  // ---- 1回ぶんの通信 -------------------------------------------------------
  // 例外を投げない。「通じたか・HTTPは何番か・本文は何か」をそのまま返す。
  // 本文が JSON でないときも失敗として扱えるようにしてある（GAS で踏んだ形）。
  function httpJson(url, opts) {
    var ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, timeoutMs()) : null;
    var o = Object.assign({ cache: "no-store" }, opts || {});
    if (ctl) o.signal = ctl.signal;
    return fetch(url, o).then(function (r) {
      return r.text().then(function (text) {
        var j = null;
        try { j = JSON.parse(text); } catch (e) { /* JSON でない応答 */ }
        return { ok: r.ok, status: r.status, json: j, text: text };
      });
    }).catch(function (e) {
      return { ok: false, status: 0, json: null, text: "", err: (e && e.message) || String(e) };
    }).then(function (res) {
      if (timer) clearTimeout(timer);
      return res;
    });
  }

  // 失敗の理由を短く。画面と console に出すので、原因が一目で分かる形にする。
  function why(res, what) {
    if (res.status === 0) return what + "に通信できない: " + (res.err || "不明");
    var msg = "";
    if (res.json && res.json.error && res.json.error.message) msg = res.json.error.message;
    else if (res.text) msg = res.text.slice(0, 80).replace(/\s+/g, " ");
    return what + "が HTTP " + res.status + (msg ? "（" + msg + "）" : "");
  }

  // =======================================================================
  // 名簿
  // =======================================================================

  // 名簿を1件読む。「ある / 無い / 失敗」の3通りを返す。
  // **無い（404）と失敗を必ず区別すること。** 通信の失敗を「無い」と読むと、
  // 較正に出た人を検証フェーズに通してしまう。
  function getRoster(docId) {
    return httpJson(baseUrl() + "/transfer_roster/" + encodeURIComponent(docId) + "?" + keyQ(), {})
      .then(function (res) {
        if (res.status === 404) return { kind: "absent" };
        if (res.ok && res.json && res.json.fields) {
          return { kind: "present", data: fromFields(res.json.fields) };
        }
        if (res.ok) return { kind: "absent" };                 // 中身が空の応答は無い扱い
        return { kind: "fail", why: why(res, "名簿の読み出し") };
      });
  }

  // フェーズの通し番号を1つ取る。increment 変換なので同時に来ても衝突しない。
  // 戻ってくる n は **1 始まり**（1人目が 1）。
  // counterId は "calib" のようなフェーズ名か、試し打ち用の "calib__test"。
  function bumpCounter(counterId) {
    var body = {
      writes: [{
        transform: {
          document: docRoot() + "/transfer_counters/" + docSafe(counterId),
          fieldTransforms: [{ fieldPath: "n", increment: { integerValue: "1" } }],
        },
      }],
    };
    return httpJson(baseUrl() + ":commit?" + keyQ(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (!res.ok) return { kind: "fail", why: why(res, "採番") };
      var w = res.json && res.json.writeResults && res.json.writeResults[0];
      var t = w && w.transformResults && w.transformResults[0];
      var n = t ? Number(t.integerValue) : NaN;
      if (!isFinite(n) || n < 1) return { kind: "fail", why: "採番の応答に番号が入っていない" };
      return { kind: "ok", n: n };
    });
  }

  // 名簿に1行足す。**すでにあるときは書き換えない**（exists:false の条件を付ける）。
  // ほぼ同時に2つのタブから来たときに、あとから来たほうが上書きしないため。
  function createRoster(docId, data) {
    var body = {
      writes: [{
        update: { name: docRoot() + "/transfer_roster/" + docSafe(docId), fields: toFields(data) },
        currentDocument: { exists: false },
      }],
    };
    return httpJson(baseUrl() + ":commit?" + keyQ(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (res.ok) return { kind: "ok" };
      var msg = (res.json && res.json.error && res.json.error.message) || res.text || "";
      // すでにあった。競合なので、先に入ったほうを読み直して従う。
      if (/already exists|FAILED_PRECONDITION/i.test(msg) || res.status === 409) {
        return { kind: "exists" };
      }
      return { kind: "fail", why: why(res, "名簿への書き込み") };
    });
  }

  // 疎通確認で作った行の目印。GAS の isTestPid と同じ規則にそろえる。
  function isTestPid(pid) {
    var p = String(pid || "");
    return p.indexOf("curltest-") === 0 || p.indexOf("uitest-") === 0;
  }

  // 掲載前フラグ（transfer_config.js の pre_launch）。true のあいだは、
  // **参加者IDが何であっても**その回を試し打ちとして扱う。
  // 参加者IDの頭だけを見ていると、URL から ?group= や wid= が落ちて本番モード扱いに
  // なった回（2026-08-21 に実際に起きた）を拾えないため。
  function preLaunch() { return cfg().pre_launch === true; }

  // この回の記録に is_test を立てるか。**目印の判定はここ1か所に集める**。
  // 配布した作業者IDの一覧（フェーズごと）。設問ファイルと同じ253個が入る。
  //   → tools/build_yahoo_task_tsv.py が transfer_config.js に書き出す
  function distributedIds(phase) {
    var m = cfg().distributed_wids || {};
    return m[phase] || null;
  }

  // この回を試し打ちとして扱うか。
  //
  // ⚠ **2026-08-25 に「配布したIDでなければ試し打ち」を足した**（丸山判断
  //   「本番のカウンタだけ特別扱いできない？」）。
  //   それまでは `uitest-` / `curltest-` で始まるIDだけが試し打ち扱いで、
  //   `test01` のような分かりやすいIDで動作確認すると**本番の通し番号を消費**し、
  //   2集団の振り分けがずれていた。前置きを覚えていないと事故る作りだった。
  //
  //   本番の参加者は、募集サイトの設問ごとに違うURLから来るので
  //   **必ず配布した一覧のどれかのID**になる。だから
  //   **一覧に無いID＝動作確認**と見なしてよい。前置きを覚える必要がなくなる。
  //
  // ⚠ 一覧が設定に無いフェーズ（検証・群C。まだ設問を配っていない）は、
  //   これまでどおり前置きだけで判定する。
  function isTestRun(pid, phase) {
    if (preLaunch() || isTestPid(pid)) return true;
    var ids = distributedIds(phase);
    if (!ids || !ids.length) return false;
    return ids.indexOf(String(pid || "")) < 0;
  }

  // 採番カウンタのドキュメントID。試し打ちは本番と**別のカウンタ**から配るので、
  // 動作確認をしても本番の連番を食いつぶさない（＝2集団の交互の振り分けがずれない）。
  var TEST_COUNTER_SUFFIX = "__test";
  function counterIdFor(phase, isTest) {
    return isTest ? (phase + TEST_COUNTER_SUFFIX) : phase;
  }

  /* -----------------------------------------------------------------------
   * 名簿に問い合わせて、集団と連番を決める（1回ぶん。作り直しは呼び出し側）。
   *
   * opts = { phase, groups, blockers, pid, worker_id }
   *   groups   … そのフェーズの集団の並び（例 ["acal","aprime"]）。交互に配る
   *   blockers … [{phase, reason}, …]。**そのフェーズに出ていたら断る**
   *
   * 戻り値は3通り。呼び出し側は kind だけ見ればよい。
   *   { kind:"ok",      group, assign_index, returning }
   *   { kind:"blocked", reason }
   *   { kind:"fail",    why }
   *
   * 手順は4つ。順番に意味がある。
   *   1. 同じフェーズの名簿に自分がいたら、**そのときの割り当てをそのまま返す**
   *      （途中で開き直した人が別の集団に飛ばされないように）
   *   2. 断るべきフェーズの名簿に自分がいたら、断る
   *   3. 採番する（ここで初めて番号を消費する。断られた人は番号を使わない）
   *      試し打ち（is_test）の人は**テスト用のカウンタ**から配るので、
   *      本番の連番は動かない。
   *   4. 名簿に載せる（is_test の目印を付けて載せる）
   * --------------------------------------------------------------------- */
  // ---- 集団の割り当て（重みつき）--------------------------------------------
  //
  // **2026-08-25 追加。** それまでは groups を順に配るだけ（1:1）だった。
  // 較正フェーズを1つの掲載にまとめたので、**人数の比に合わせて配る**必要が出た
  // （聴覚80人・視覚150人 ＝ 8:15）。
  //
  // ⚠ **乱数を使わない。** 連番から決めることで、同じ人が途中で閉じて開き直しても
  //   同じ集団に戻る（名簿にも残るが、名簿が引けないときの保険として決定的にしておく）。
  //
  // ⚠ **比は「並び」に展開して使う。** 単純に「35%の確率で聴覚」とすると、
  //   途中で募集を止めたときに比が崩れる。ここでは重みを約分した長さの並びを作り、
  //   各集団を**均等にばらけさせて**配る。こうすると**どこで止めても比がほぼ保たれる**。
  //   例: 8:15 なら 23人で1巡し、その中で聴覚8人・視覚15人が散らばる。
  //
  // ⚠ **assign_index は集団ごとの通し番号**である（全体の通し番号ではない）。
  //   出題の割付（方式・速さ・水準の回転）がこの番号を使うので、
  //   集団ごとに 0,1,2,… と続いていなければ割付が偏る。
  function gcd2(a, b) { while (b) { var t = a % b; a = b; b = t; } return a; }

  // ⚠ ここは以前 `CFG` を裸で参照していた。ブラウザでは transfer.js の
  //   `const CFG` が偶然見えるので動いていたが、**このファイル単体では落ちる**。
  //   設定は、このファイルの先頭にある cfg() から取る
  //   （ここで同名の関数をもう一つ作ると、先頭の cfg() を上書きして全体が壊れる）。
  function assignPattern(phase, groups) {
    var w = (cfg().phase_group_weights || {})[phase];
    if (!w) return null;                       // 重みが無ければ従来どおり順に配る
    var ws = groups.map(function (g) { return Math.max(0, Math.round(Number(w[g]) || 0)); });
    if (ws.some(function (x) { return x <= 0; })) return null;   // 0や欠けがあれば従来どおり
    var g0 = ws.reduce(function (a, b) { return gcd2(a, b); });
    ws = ws.map(function (x) { return x / g0; });               // 8:15 のように約分する
    var slots = [];
    groups.forEach(function (g, gi) {
      for (var k = 0; k < ws[gi]; k++) {
        // 0〜1 の位置に等間隔で置く。集団どうしが均等に混ざる。
        slots.push({ g: g, key: (k + 0.5) / ws[gi], gi: gi });
      }
    });
    slots.sort(function (x, y) { return (x.key - y.key) || (x.gi - y.gi); });
    return { order: slots.map(function (x) { return x.g; }), per: ws, groups: groups };
  }

  function assignFor(phase, groups, i0) {
    var pat = assignPattern(phase, groups);
    if (!pat) {   // 従来どおり（1:1で順に配る）
      return { group: groups[i0 % groups.length],
               assignIndex: Math.floor(i0 / groups.length) };
    }
    var L = pat.order.length;
    var cycle = Math.floor(i0 / L);
    var pos = i0 % L;
    var group = pat.order[pos];
    var perCycle = pat.per[groups.indexOf(group)];
    var before = 0;
    for (var i = 0; i < pos; i++) if (pat.order[i] === group) before++;
    return { group: group, assignIndex: cycle * perCycle + before };
  }

  function resolveAssignment(opts) {
    var phase = String(opts.phase || "");
    var pid = String(opts.pid || "");
    var groups = (opts.groups || []).slice();
    var blockers = opts.blockers || [];
    if (!phase || !pid || !groups.length) {
      return Promise.resolve({ kind: "fail", why: "フェーズ・参加者ID・集団のどれかが空" });
    }
    var ownId = phase + "_" + pid;

    // 1. 開き直しか
    return getRoster(ownId).then(function (own) {
      if (own.kind === "fail") return own;
      if (own.kind === "present") {
        return {
          kind: "ok",
          group: String(own.data.group || ""),
          assign_index: Number(own.data.assign_index) || 0,
          returning: true,
        };
      }

      // 2. 他のフェーズに出ていないか（順に見る。1つでも当たれば断る）
      var i = 0;
      function nextBlocker() {
        if (i >= blockers.length) return Promise.resolve(null);
        var b = blockers[i++];
        return getRoster(b.phase + "_" + pid).then(function (r) {
          if (r.kind === "fail") return { kind: "fail", why: r.why };
          if (r.kind === "present") return { kind: "blocked", reason: b.reason };
          return nextBlocker();
        });
      }

      return nextBlocker().then(function (stop) {
        if (stop) return stop;

        // 3. 採番（試し打ちは本番と別のカウンタから配る）
        var testRun = isTestRun(pid, phase);
        return bumpCounter(counterIdFor(phase, testRun)).then(function (c) {
          if (c.kind !== "ok") return { kind: "fail", why: c.why };
          var i0 = c.n - 1;                                    // n は1始まり → 0始まりに
          var a = assignFor(phase, groups, i0);
          var group = a.group;
          var assignIndex = a.assignIndex;

          // 4. 名簿に載せる
          return createRoster(ownId, {
            participant_id: pid,
            worker_id: String(opts.worker_id || ""),
            phase: phase,
            group: group,
            assign_index: assignIndex,
            counter_n: c.n,
            ts: Date.now(),
            // 名簿にも目印を残す（2026-08-22 まで名簿には is_test が無く、
            // 混ざった行を機械で見分けられなかった）。
            is_test: testRun,
          }).then(function (cr) {
            if (cr.kind === "ok") return { kind: "ok", group: group, assign_index: assignIndex };
            if (cr.kind === "exists") {
              // ほぼ同時に2つのタブから来た。先に入ったほうを正とする。
              // （消費した番号は1つ空くが、割り当ての取り違えよりはるかにましである。）
              return getRoster(ownId).then(function (again) {
                if (again.kind === "present") {
                  return {
                    kind: "ok",
                    group: String(again.data.group || ""),
                    assign_index: Number(again.data.assign_index) || 0,
                    returning: true,
                  };
                }
                return { kind: "fail", why: "名簿の書き込みが競合した（読み直しにも失敗）" };
              });
            }
            return cr;                                          // {kind:"fail", why}
          });
        });
      });
    });
  }

  // =======================================================================
  // 記録の保存
  // =======================================================================

  // その記録をどのコレクションへ入れるか。GAS の doPost の振り分けと同じ規則。
  function collectionFor(rec) {
    if (rec && (rec.kind === "transfer_wellbeing" || rec.modality === "transfer_wellbeing")) {
      return "transfer_wellbeing";
    }
    return "transfer_trials";
  }

  // 1件保存する。**応答を読める**のが GAS（no-cors）との一番の違いで、
  // 「入ったかどうか」がその場で分かる。
  //
  // GAS が受け取り側でやっていた2つの後処理を、ここで同じようにやってから入れる。
  //   ・correct（正誤）を target_char と response_char から出す
  //   ・is_test（疎通確認の行かどうか）の目印を付ける
  // こうしておくと、解析側は GAS のシートと同じ列を見ればよくなる。
  function submitRecord(rec) {
    var col = collectionFor(rec);
    var body = Object.assign({}, rec);
    if (col === "transfer_trials") {
      body.correct = (body.response_char === body.target_char);
    }
    body.is_test = isTestRun(body.participant_id, body.phase);
    // GAS 側の分岐にしか使わない値。Firestore では列を増やすだけなので落とす。
    delete body.kind;

    return httpJson(baseUrl() + "/" + col + "?" + keyQ(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields: toFields(body) }),
    }).then(function (res) {
      if (res.ok) return { kind: "ok", collection: col };
      return { kind: "fail", why: why(res, "記録の保存"), status: res.status };
    });
  }

  root.TRANSFER_FIRESTORE = {
    enabled: enabled,
    resolveAssignment: resolveAssignment,
    submitRecord: submitRecord,
    collectionFor: collectionFor,
    isTestPid: isTestPid,
    // 掲載前フラグも含めた判定。ページ側（transfer.js / transfer_comfort.js）は
    // **こちらを使う**（GAS へ送る封筒にも同じ値を入れるため）。
    isTestRun: isTestRun,
    preLaunch: preLaunch,
    // 試験と道具から使う下回り
    _internal: {
      counterIdFor: counterIdFor,
      // サーバが答えないときの予備経路(transfer.js の local_hash)でも
      // **同じ振り分け規則**を使うために外へ出す。
      // これが無いと、名簿が落ちた分だけ 1:1 に戻ってしまい比が崩れる。
      assignFor: assignFor,
      getRoster: getRoster, bumpCounter: bumpCounter, createRoster: createRoster,
      toFields: toFields, fromFields: fromFields, docSafe: docSafe, httpJson: httpJson,
    },
  };
})(typeof window !== "undefined" ? window : globalThis);

if (typeof module !== "undefined" && module.exports) {
  module.exports = (typeof window !== "undefined" ? window : globalThis).TRANSFER_FIRESTORE;
}
