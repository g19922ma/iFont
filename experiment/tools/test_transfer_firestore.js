#!/usr/bin/env node
/* =========================================================================
 * test_transfer_firestore.js — Firestore に移した名簿と記録の疎通確認
 * -------------------------------------------------------------------------
 * 本物の Firestore（ifont-transfer）に**実際に書き込んで**確かめる。
 * 参加者IDはすべて "curltest-" で始めるので、入った行には is_test = true が付く。
 * 解析側（export_transfer_firestore.py）は既定でこの行を外す。
 *
 * 使い方:
 *   node experiment/tools/test_transfer_firestore.js
 *   node experiment/tools/test_transfer_firestore.js --keep   # 後片付けの案内を出さない
 *
 * 確かめること（掲載前チェックリスト C 節・H 節の Firestore 版）:
 *   1. 採番が飛ばない・重複しない（連続 & 同時アクセスの両方）
 *   2. 2集団が交互に配られる（音声と視覚が半々になる）
 *   3. 同じ人が開き直したら、前と同じ集団・同じ連番が返る
 *   4. 重複拒否が **3方向すべて** 効く
 *        較正 → 検証   ／ 較正 → 群C ／ 群C → 検証
 *   5. 回答と見え心地が全件入る
 *   6. ルールが効いている（回答は読めない・書き換えられない・カウンタを飛ばせない）
 *
 * 後片付け（このスクリプトからは消せない。ルールで delete を禁止しているため）:
 *   python3 experiment/tools/purge_transfer_firestore.py --yes
 * ========================================================================= */
"use strict";

const path = require("path");

// ブラウザ用のファイルを Node で読むための下ごしらえ。
global.window = global;
require(path.join(__dirname, "..", "transfer_config.js"));
const FS = require(path.join(__dirname, "..", "transfer_firestore.js"));

const CFG = global.TRANSFER_CONFIG;
const PHASES = CFG.phases;
const BLOCKS = CFG.phase_blocks;

// 走るたびに違う参加者IDにする（前回の行が残っていても影響を受けないため）。
const RUN = "curltest-" + Date.now().toString(36);

let pass = 0, fail = 0;
const failures = [];
function ok(cond, label, detail) {
  if (cond) { pass++; console.log("  \x1b[32m✔\x1b[0m " + label); }
  else {
    fail++; failures.push(label);
    console.log("  \x1b[31m✘\x1b[0m " + label + (detail !== undefined ? "\n      → " + detail : ""));
  }
}
function head(t) { console.log("\n\x1b[1m" + t + "\x1b[0m"); }

function assign(phase, pid) {
  return FS.resolveAssignment({
    phase: phase,
    groups: PHASES[phase],
    blockers: BLOCKS[phase] || [],
    pid: pid,
    worker_id: "w-" + pid,
  });
}

(async function main() {
  console.log("Firestore 疎通確認  project=" + CFG.firestore.project_id +
              "  参加者IDの頭 = " + RUN);
  ok(FS.enabled(), "設定が揃っている（enabled / project_id / api_key）");
  if (!FS.enabled()) process.exit(1);

  // =====================================================================
  head("1. 較正フェーズ: 連続16人ぶんの採番と振り分け");
  // =====================================================================
  const calibIds = [];
  for (let i = 0; i < 16; i++) calibIds.push(RUN + "-calib-" + i);
  const calibRes = [];
  for (const pid of calibIds) calibRes.push(await assign("calib", pid));

  const bad = calibRes.filter(r => r.kind !== "ok");
  ok(bad.length === 0, "16人ぶんすべて割り当てが返る",
     bad.length ? JSON.stringify(bad[0]) : undefined);

  if (bad.length === 0) {
    // 連番は「集団ごとに0から」。16人なら acal も aprime も 0..7 が1回ずつ。
    const byGroup = {};
    calibRes.forEach(r => { (byGroup[r.group] = byGroup[r.group] || []).push(r.assign_index); });
    const gs = Object.keys(byGroup).sort();
    ok(gs.join(",") === "acal,aprime", "集団は acal と aprime の2つだけ", gs.join(","));
    ok(byGroup.acal && byGroup.aprime && byGroup.acal.length === 8 && byGroup.aprime.length === 8,
       "8人ずつ半々に配られる",
       JSON.stringify({ acal: (byGroup.acal || []).length, aprime: (byGroup.aprime || []).length }));

    // 交互か（人数の差が最大1人であること＝各時点で釣り合っている）
    let alternating = true;
    for (let i = 0; i < calibRes.length; i++) {
      if (calibRes[i].group !== PHASES.calib[i % 2]) alternating = false;
    }
    ok(alternating, "acal → aprime → acal … と交互に配られる",
       calibRes.map(r => r.group).join(" "));

    gs.forEach(g => {
      const idx = byGroup[g].slice().sort((a, b) => a - b);
      const want = idx.map((_, i) => i);
      ok(JSON.stringify(idx) === JSON.stringify(want),
         `連番が 0..${idx.length - 1} で飛びも重複もない（${g}）`, JSON.stringify(idx));
    });
  }

  // =====================================================================
  head("2. 開き直し: 同じ参加者IDは同じ集団・同じ連番に戻る");
  // =====================================================================
  const again = await assign("calib", calibIds[3]);
  const first = calibRes[3];
  ok(again.kind === "ok" && again.returning === true, "2回目は returning が付く", JSON.stringify(again));
  ok(again.group === first.group && again.assign_index === first.assign_index,
     "集団と連番が1回目と同じ",
     `1回目 ${first.group}/${first.assign_index} → 2回目 ${again.group}/${again.assign_index}`);

  // 開き直しでは番号を消費しない（＝次の人が連番の続きをもらえる）。
  const nextOne = await assign("calib", RUN + "-calib-16");
  ok(nextOne.kind === "ok" && nextOne.group === "acal" && nextOne.assign_index === 8,
     "開き直しは採番を消費しない（次の人は acal/8）",
     JSON.stringify({ group: nextOne.group, assign_index: nextOne.assign_index }));

  // =====================================================================
  head("3. 同時アクセス: 24人が一斉に来ても番号が衝突しない");
  // =====================================================================
  const raceIds = [];
  for (let i = 0; i < 24; i++) raceIds.push(RUN + "-race-" + i);
  const raceRes = await Promise.all(raceIds.map(pid => assign("test", pid)));

  const raceBad = raceRes.filter(r => r.kind !== "ok");
  ok(raceBad.length === 0, "24人ぶんすべて割り当てが返る",
     raceBad.length ? JSON.stringify(raceBad[0]) : undefined);

  if (raceBad.length === 0) {
    const keys = raceRes.map(r => r.group + "/" + r.assign_index);
    const uniq = new Set(keys);
    ok(uniq.size === 24, "24人ぶんの「集団＋連番」がすべて別（重複なし）",
       `別々の値は ${uniq.size} 個`);

    const byGroup = {};
    raceRes.forEach(r => { (byGroup[r.group] = byGroup[r.group] || []).push(r.assign_index); });
    let gapless = true, detail = [];
    Object.keys(byGroup).sort().forEach(g => {
      const idx = byGroup[g].slice().sort((a, b) => a - b);
      const want = idx.map((_, i) => i);
      if (JSON.stringify(idx) !== JSON.stringify(want)) { gapless = false; }
      detail.push(g + ":" + idx.join(","));
    });
    ok(gapless, "同時に来ても連番に飛びが無い（0から詰まっている）", detail.join(" / "));
    ok((byGroup.atest || []).length === 12 && (byGroup.b || []).length === 12,
       "atest と b に12人ずつ",
       JSON.stringify({ atest: (byGroup.atest || []).length, b: (byGroup.b || []).length }));
  }

  // =====================================================================
  head("4. 重複拒否が3方向すべて効く");
  // =====================================================================
  // (a) 較正に出た人が検証フェーズへ
  const dupA = RUN + "-dup-a";
  const a1 = await assign("calib", dupA);
  const a2 = await assign("test", dupA);
  ok(a1.kind === "ok", "較正フェーズには入れる", JSON.stringify(a1));
  ok(a2.kind === "blocked" && a2.reason === "already_in_calib",
     "較正 → 検証 は断られる（already_in_calib）", JSON.stringify(a2));

  // (b) 較正に出た人が群Cへ
  const dupB = RUN + "-dup-b";
  await assign("calib", dupB);
  const b2 = await assign("comfort", dupB);
  ok(b2.kind === "blocked" && b2.reason === "already_in_other_phase",
     "較正 → 群C は断られる（already_in_other_phase）", JSON.stringify(b2));

  // (c) 群Cに出た人が検証フェーズへ
  const dupC = RUN + "-dup-c";
  const c1 = await assign("comfort", dupC);
  const c2 = await assign("test", dupC);
  ok(c1.kind === "ok" && c1.group === "c", "群Cには入れる（集団は c）", JSON.stringify(c1));
  ok(c2.kind === "blocked" && c2.reason === "already_in_comfort",
     "群C → 検証 は断られる（already_in_comfort）", JSON.stringify(c2));

  // (d) 検証に出た人が群Cへ
  const dupD = RUN + "-dup-d";
  await assign("test", dupD);
  const d2 = await assign("comfort", dupD);
  ok(d2.kind === "blocked" && d2.reason === "already_in_other_phase",
     "検証 → 群C は断られる（already_in_other_phase）", JSON.stringify(d2));

  // (e) 断られた人は名簿にも採番にも載らない
  const afterBlocks = await assign("comfort", RUN + "-comfort-after");
  ok(afterBlocks.kind === "ok" && afterBlocks.assign_index === 1,
     "断られた人は連番を消費していない（群Cの次の人は連番1）",
     JSON.stringify(afterBlocks));

  // =====================================================================
  head("5. 回答と見え心地が入る");
  // =====================================================================
  const trialPid = RUN + "-trials";
  const tAssign = await assign("calib", trialPid);
  const N_TRIALS = 30;
  const trialResults = await Promise.all(
    Array.from({ length: N_TRIALS }, (_, i) => FS.submitRecord({
      participant_id: trialPid, worker_id: "w", completion_code: "",
      phase: "calib", group: tAssign.group, assign_index: tAssign.assign_index,
      assign_source: "server", trial_index: i,
      stimulus_id: "stim-" + i, target_char: "あ",
      response_char: (i % 5 === 0) ? "か" : "あ",     // 5問に1問はわざと誤答
      modality: "transfer_audio", family: "fade", condition: "g1",
      gate_ms: 120, progress_pct: 55.5, is_filler: false, check_kind: "", is_catch: false,
      n_choices: 68, rt_ms: 800 + i, actual_ms: 120, actual_frames: 7, actual_s: 0.12,
      progress_source: "raf", base_anim_ms: 400,
      ua: "node-test", dpr: 2, screen: "1920x1080", touch: false, refresh_hz: 60,
      audio_device: "earphone", resume_count: 0, resume_gap_s: 0,
      version: "test", config_version: CFG.config_version, ts: Date.now(),
    }))
  );
  const tBad = trialResults.filter(r => r.kind !== "ok");
  ok(tBad.length === 0, `回答 ${N_TRIALS} 件が全部入る`,
     tBad.length ? `${tBad.length} 件失敗: ${tBad[0].why}` : undefined);
  ok(trialResults.every(r => r.collection === "transfer_trials"),
     "回答は transfer_trials に入る");

  const wbRes = await FS.submitRecord({
    kind: "transfer_wellbeing",
    participant_id: RUN + "-wb", worker_id: "w", completion_code: "",
    stimulus_id: "comfort|c", target_char: "-", response_char: "-",
    modality: "transfer_wellbeing", q_set: "transfer", phase: "comfort", group: "c",
    assign_index: 0, assign_source: "server", n_choices: 4,
    wellbeing_json: JSON.stringify({ fade: [5, 4, 6] }), choice: "fade",
    version: "test", config_version: CFG.config_version, ts: Date.now(),
  });
  ok(wbRes.kind === "ok" && wbRes.collection === "transfer_wellbeing",
     "見え心地が transfer_wellbeing に入る", JSON.stringify(wbRes));

  // =====================================================================
  head("6. ルールが効いている（できてはいけないこと）");
  // =====================================================================
  const base = "https://firestore.googleapis.com/v1/projects/" + CFG.firestore.project_id +
               "/databases/(default)/documents";
  const key = "key=" + CFG.firestore.api_key;
  const H = FS._internal.httpJson;

  // 回答の一覧は読めない
  let r = await H(base + "/transfer_trials?" + key, {});
  ok(r.status === 403, "回答の一覧は読めない（403）", "HTTP " + r.status);

  // 名簿の一覧も読めない（1件ずつの読み出しだけ許してある）
  r = await H(base + "/transfer_roster?" + key, {});
  ok(r.status === 403, "名簿の一覧は読めない（403）", "HTTP " + r.status);

  // 名簿の1件読みはできる（開き直しと重複判定に要る）
  r = await H(base + "/transfer_roster/" + encodeURIComponent("calib_" + calibIds[0]) + "?" + key, {});
  ok(r.status === 200, "名簿の1件読みはできる（200）", "HTTP " + r.status);

  // カウンタは読めない
  r = await H(base + "/transfer_counters/calib?" + key, {});
  ok(r.status === 403, "採番カウンタは読めない（403）", "HTTP " + r.status);

  // 名簿の書き換えはできない
  r = await H(base + ":commit?" + key, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ writes: [{ update: {
      name: "projects/" + CFG.firestore.project_id + "/databases/(default)/documents/transfer_roster/calib_" + calibIds[0],
      fields: { group: { stringValue: "aprime" }, participant_id: { stringValue: calibIds[0] },
                phase: { stringValue: "calib" }, assign_index: { integerValue: "0" } },
    } }] }),
  });
  ok(r.status === 403, "名簿の書き換えはできない（403）", "HTTP " + r.status);

  // 採番を一気に飛ばすことはできない（+100 の更新）
  r = await H(base + ":commit?" + key, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ writes: [{ transform: {
      document: "projects/" + CFG.firestore.project_id + "/databases/(default)/documents/transfer_counters/calib",
      fieldTransforms: [{ fieldPath: "n", increment: { integerValue: "100" } }],
    } }] }),
  });
  ok(r.status === 403, "採番を一度に100増やすことはできない（403）", "HTTP " + r.status);

  // 列の足りない回答は入らない（形の決まらない書き込みでコレクションを荒らせない）
  r = await H(base + "/transfer_trials?" + key, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields: { junk: { stringValue: "x" } } }),
  });
  ok(r.status === 403, "列の足りない回答は入らない（403）", "HTTP " + r.status);

  // 決めた4つ以外の場所には書けない
  r = await H(base + "/anything_else?" + key, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields: { a: { stringValue: "b" } } }),
  });
  ok(r.status === 403, "決めた4か所以外には書けない（403）", "HTTP " + r.status);

  // =====================================================================
  console.log("\n" + "=".repeat(66));
  if (fail === 0) {
    console.log(`\x1b[32m合格\x1b[0m  ${pass} 項目すべて通った。`);
  } else {
    console.log(`\x1b[31m不合格\x1b[0m  通った ${pass} / 落ちた ${fail}`);
    failures.forEach(f => console.log("  - " + f));
  }
  console.log("=".repeat(66));
  console.log("試し打ちの行を消すには: python3 experiment/tools/purge_transfer_firestore.py --yes");
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error("\n落ちた:", e); process.exit(1); });
