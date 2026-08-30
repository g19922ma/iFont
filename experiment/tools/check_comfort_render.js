#!/usr/bin/env node
/* =========================================================================
 * 見え心地の評価（群C）のページが、群Bと**同じ絵**を出す状態かを見る
 * =========================================================================
 * 掲載の前に必ず通す。ブラウザを開かずに、次の3つを機械的に確かめる。
 *
 *   1. 入口HTMLの参照   … transfer_comfort.html が読む JS・CSS が実在し、
 *                          キャッシュ避けの ?v= が transfer_comfort.js の
 *                          VERSION と一致しているか
 *   2. 描画器の一致     … transfer_comfort.js は、4方式の描画器と進み方の補間を
 *                          transfer.js から**写して**持っている。両者が食い違うと、
 *                          群B（識別課題）と群C（見え心地）で違う絵を見せることになり、
 *                          2つの結果を並べて論じられなくなる。関数の中身を1つずつ比べる。
 *   3. 設定の筋が通っているか … 代表字が transfer_config.js のターゲット字に入っているか、
 *                          方式名が描画器にあるか、代表字の画像が実在するか
 *
 * 使い方:  node experiment/tools/check_comfort_render.js
 * 終了コード: 0=すべて合格 / 1=不合格(掲載してはいけない)
 * ========================================================================= */
"use strict";
const fs = require("fs");
const path = require("path");

const EXP = path.resolve(__dirname, "..");
const problems = [];
const notes = [];
function bad(msg) { problems.push(msg); }
function ok(msg) { notes.push(msg); }

// ---- 設定を読む(実験ページと同じファイル) --------------------------------
global.window = {};
require(path.join(EXP, "transfer_config.js"));
require(path.join(EXP, "transfer_comfort_config.js"));
const CFG = global.window.TRANSFER_CONFIG;
const C = global.window.TRANSFER_COMFORT_CONFIG;

const mainText = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8");
const comfortText = fs.readFileSync(path.join(EXP, "transfer_comfort.js"), "utf8");

// ---- 1. 入口HTMLの参照 ----------------------------------------------------
const vm = comfortText.match(/const VERSION = "([^"]+)"/);
const VERSION = vm ? vm[1] : null;
if (!VERSION) bad("transfer_comfort.js から VERSION を読めない");

{
  const page = "transfer_comfort.html";
  const html = fs.readFileSync(path.join(EXP, page), "utf8");
  const refs = [...html.matchAll(/(?:src|href)="([^"]+?)(?:\?v=([^"]*))?"/g)];
  let found = 0;
  for (const [, file, v] of refs) {
    if (/^https?:/.test(file)) continue;
    found++;
    if (!fs.existsSync(path.join(EXP, file))) bad(`${page}: ${file} が無い`);
    if (v !== undefined && v !== VERSION) {
      bad(`${page}: ${file} の ?v=${v} が transfer_comfort.js の VERSION=${VERSION} と違う`);
    }
  }
  if (found < 5) bad(`${page}: 読み込んでいるファイルが ${found} 個しかない(CSS+JS4本のはず)`);
  else ok(`${page}: 参照 ${found} 件すべて実在・?v=${VERSION} で一致`);
}

// ---- 2. 描画器の一致 ------------------------------------------------------
// 名前で関数を切り出し、空白の入れ方だけを無視して1文字ずつ比べる。
function extractFn(text, name) {
  const head = new RegExp(`\\bfunction\\s+${name}\\s*\\(`).exec(text);
  if (!head) return null;
  let i = text.indexOf("{", head.index);
  if (i < 0) return null;
  let depth = 0;
  for (let j = i; j < text.length; j++) {
    const c = text[j];
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return text.slice(head.index, j + 1); }
  }
  return null;
}
function normalize(s) { return s.replace(/\s+/g, " ").trim(); }

// transfer.js から写した関数の一覧。写す対象を増やしたらここにも足すこと。
// 前半は描画器と進み方（群Bと群Cで絵が食い違わないため）。
// 後半は同意画面の追記と試し打ちの判定（文面と記録の扱いが食い違わないため）。
// どちらも「片方だけ直した」が事故になるので、機械で突き合わせる。
const COPIED = [
  "newCanvas", "drawBlank",
  "hashSeed", "mulberry32",
  "revealPrepare", "revealBegin", "revealDraw",
  "blurBegin", "blurDraw",
  "blurFrameIndex", "blurDrawFromFrames", "blurFramesLoad",
  "wipeInkThreshold", "wipeBBoxPrepare", "wipeBegin", "wipeDraw", "fadeAlpha", "fadeDraw",
  "warpSeries", "seriesAt",
  "tidyConsentScreen", "mailLink", "isTestRun",
];
let same = 0;
for (const name of COPIED) {
  const a = extractFn(mainText, name);
  const b = extractFn(comfortText, name);
  if (!a) { bad(`transfer.js に ${name}() が無い(名前が変わった?)`); continue; }
  if (!b) { bad(`transfer_comfort.js に ${name}() が無い`); continue; }
  if (normalize(a) !== normalize(b)) {
    bad(`${name}() の中身が transfer.js と違う。**どちらかだけを直した疑い**。` +
        `群Bと群Cで違う絵を出すことになるので、両方をそろえること`);
  } else same++;
}
if (same === COPIED.length) ok(`描画器と進み方 ${same} 個が transfer.js と一字一句同じ`);

// RENDERERS の並び(方式名→描画器の対応)もそろっているか。
{
  const a = /const RENDERERS = \{[\s\S]*?\n\};/.exec(mainText);
  const b = /const RENDERERS = \{[\s\S]*?\n\};/.exec(comfortText);
  if (!a || !b) bad("RENDERERS の表を読み取れない");
  else if (normalize(a[0]) !== normalize(b[0])) bad("RENDERERS の表が transfer.js と違う");
  else ok("RENDERERS の表が transfer.js と同じ");
}

// ---- 3. 設定の筋 ----------------------------------------------------------
{
  // "step"(ステップ表示)は 2026-08-24 に足した5つ目の見せ方。独立した描画器を持たず、
  // フェードの描画器に進み具合0か1を渡すだけなので、visual.families に描画パラメータは無い。
  // どの描画器を借りるかは transfer_comfort_config.js の family_renderer にある。
  const known = { fade: 1, reveal: 1, blur: 1, wipe: 1, step: 1 };
  const rendererMap = C.family_renderer || {};
  for (const f of C.families) {
    if (!known[f]) bad(`transfer_comfort_config.js の families に知らない方式 "${f}" がある`);
    const drawnBy = rendererMap[f] || f;
    if (!CFG.visual.families[drawnBy]) {
      bad(`transfer_config.js の visual.families に "${drawnBy}" の描画パラメータが無い`
          + (drawnBy === f ? "" : `（"${f}" が借りようとしている描画器）`));
    }
  }
  // 方式ごとに提示のしかたを絞る表の筋を見る。
  for (const [f, only] of Object.entries(C.presentations_by_family || {})) {
    if (C.families.indexOf(f) < 0) {
      bad(`presentations_by_family に、families に無い方式 "${f}" が書いてある`);
    }
    for (const p of (only || [])) {
      if (C.presentations.indexOf(p) < 0) {
        bad(`presentations_by_family["${f}"] の "${p}" が presentations に無い`);
      }
    }
    if (!(only || []).length) bad(`presentations_by_family["${f}"] が空。1つ以上書くこと`);
  }
  // ---- 4条件（2026-08-29 から）----------------------------------------------
  if (!Array.isArray(C.conditions) || C.conditions.length < 2) {
    bad("conditions が2つ未満。合わせ方を比べられない");
  }
  // 最後の質問は「4条件を並べて選ばせる」。説明の言葉は**出してはいけない**
  // （現れ方を言葉にすると注意がそこへ向いて答えが偏る。丸山指摘 2026-08-29）。
  const cch = (C.choice || {}).condition || {};
  if (!cch.families || !cch.families.length) bad("choice.condition.families が空");
  for (const f of (cch.families || [])) {
    if (C.families.indexOf(f) < 0) bad(`choice.condition.families の "${f}" を本編で見せていない`);
  }
  if (cch.labels) bad("choice.condition.labels がある。現れ方の説明を画面に出してはいけない");
  if ((C.choice || {}).family || (C.choice || {}).presentation) {
    bad("choice に family / presentation が残っている（2026-08-29 に条件版へ差し替え済み）");
  }
  // 使う字は「人ごとに配る字の一覧」ぜんぶを見る（1人1字だが、8字とも出番がある）。
  const chars = [...new Set(
    (C.char_rotation ? (C.chars_pool || []) : []).concat([C.single_char]).concat(C.sequence))];
  for (const ch of chars) {
    if (CFG.targets.indexOf(ch) < 0) {
      bad(`使う字 "${ch}" が transfer_config.js の targets に入っていない` +
          `(群Bで見せていない字を見え心地だけで聞くことになる)`);
    }
    const png = path.join(EXP, CFG.visual.base_dir, ch + ".png");
    if (!fs.existsSync(png)) bad(`"${ch}" の画像 ${path.relative(EXP, png)} が無い`);
  }
  const knownPres = { single: 1, row5: 1, swap5: 1 };
  for (const p of C.presentations) {
    if (!knownPres[p]) bad(`presentations に知らない提示のしかた "${p}" がある`);
    if (!C.presentation_labels[p]) bad(`presentation_labels に "${p}" の説明が無い`);
  }
  // sequence は字の大きさを決めるためだけに残してある（5字を並べる出し方は 2026-08-29 に廃止）。
  if (C.sequence.length < 2) bad("sequence が2字未満。字の大きさの計算が変わってしまう");
  // 進み方の表に、配る字ぜんぶ × 方式ぜんぶ × 条件ぜんぶが入っているか。
  {
    const wpath = path.join(EXP, C.warp_tables_url || "");
    if (!C.warp_tables_url || !fs.existsSync(wpath)) {
      bad(`4条件の進み方の表 ${C.warp_tables_url} が無い` +
          `（experiment/tools/merge_warp_comfort.py で作る）`);
    } else {
      const W = JSON.parse(fs.readFileSync(wpath, "utf8"));
      let miss = 0;
      for (const f of C.families) for (const ch of chars) for (const cd of C.conditions) {
        const a = ((W.tables || {})[f] || {})[ch];
        if (!a || !Array.isArray(a[cd.key]) || !a[cd.key].length) {
          if (miss++ < 5) bad(`進み方の表に ${f} × ${ch} × ${cd.key} が無い`);
        }
      }
      if (!miss) ok(`進み方の表に ${C.families.length}方式 × ${chars.length}字 × ` +
                    `${C.conditions.length}条件 がそろっている`);
      // ---- 4条件が同じ絵になる組み合わせを数える --------------------------
      // ⚠ **これは不合格にしない（2026-08-29 に改めた）。**
      //   「が」では正答率にもとづく①と③がどちらも等速に退化し、同じ絵になる。
      //   これを実験の成立条件にすると、うまくいかない入力を落として都合のよい字
      //   だけを残すことになる。「違う写し方が同じ表示を返すことがある」のは
      //   **手法の出力そのもの**なので、外さずに記録して、分析で層に分ける
      //   （transfer_comfort_config.js の chars_pool の注記を見ること）。
      //   ここでは、どこが同じになるかを掲載前に一望できるようにするだけである。
      const dup = [];
      for (const ch of chars) for (const f of C.families) {
        const a = ((W.tables || {})[f] || {})[ch];
        if (!a) continue;
        for (let i = 0; i < C.conditions.length; i++) {
          for (let j = i + 1; j < C.conditions.length; j++) {
            const x = a[C.conditions[i].key], y = a[C.conditions[j].key];
            if (Array.isArray(x) && Array.isArray(y) && JSON.stringify(x) === JSON.stringify(y)) {
              dup.push(`${ch}×${f}: ${C.conditions[i].no}=${C.conditions[j].no}`);
            }
          }
        }
      }
      if (!dup.length) {
        ok(`配る字すべてで、4条件がどの2つを取っても違う絵になっている`);
      } else {
        const byChar = {};
        dup.forEach(d => { const c = d[0]; (byChar[c] = byChar[c] || []).push(d.split(": ")[1]); });
        ok(`同じ絵になる組がある（外さずに記録する）: ` +
           Object.entries(byChar).map(([c, v]) =>
             `${c} は ${[...new Set(v)].join("・")}（${v.length}方式）`).join(" / ") +
           ` ← 分析では層に分けて扱うこと`);
      }

      // ---- 字の割り当て（ラテン方格）の釣り合い ----------------------------
      // 1人に4字を配り、4方式 × 4条件の16マスへ方格で割り当てる。
      // ここで見るのは3つ。
      //   (1) 1人の中で、どの条件も4字を1回ずつ使うか（使わないと、条件の比較に
      //       字の違いが混ざる）
      //   (2) どの方式も同じか
      //   (3) 人数ぶん通したとき、どの字も同じ本数・同じ人数になるか
      if (C.char_rotation && (C.chars_pool || []).length >= C.families.length) {
        const pool = C.chars_pool, nf = C.families.length, nc = C.conditions.length;
        const N = Number(C.planned_n) || (pool.length * nf);
        const cnt = {}, seen = {}, pick = {};
        const perCond = {}, perFam = {};
        let unbalanced = 0;
        for (let i = 0; i < N; i++) {
          const start = i % pool.length, shift = Math.floor(i / pool.length) % nf;
          const set = [];
          for (let k = 0; k < nf; k++) set.push(pool[(start + k) % pool.length]);
          set.forEach(ch => { seen[ch] = (seen[ch] || 0) + 1; });
          pick[set[shift]] = (pick[set[shift]] || 0) + 1;
          for (let fi = 0; fi < nf; fi++) {
            const row = [];
            for (let ci = 0; ci < nc; ci++) {
              const ch = set[(fi + ci + shift) % nf];
              row.push(ch);
              cnt[ch] = (cnt[ch] || 0) + 1;
              perCond[ci + "|" + ch] = (perCond[ci + "|" + ch] || 0) + 1;
              perFam[fi + "|" + ch] = (perFam[fi + "|" + ch] || 0) + 1;
            }
            if (new Set(row).size !== nf) unbalanced++;    // (2) 方式の行に重複
          }
          for (let ci = 0; ci < nc; ci++) {
            const col = [];
            for (let fi = 0; fi < nf; fi++) col.push(set[(fi + ci + shift) % nf]);
            if (new Set(col).size !== nf) unbalanced++;    // (1) 条件の列に重複
          }
        }
        if (unbalanced) {
          bad(`字の割り当てが方格になっていない（${unbalanced} 箇所で同じ字が重複）。` +
              `条件の比較に字の違いが混ざる`);
        } else {
          const uniq = (o) => [...new Set(Object.values(o))];
          const evenCnt = uniq(cnt).length === 1, evenSeen = uniq(seen).length === 1;
          const evenCond = uniq(perCond).length === 1, evenFam = uniq(perFam).length === 1;
          const evenPick = uniq(pick).length === 1;
          if (evenCnt && evenSeen && evenCond && evenFam && evenPick) {
            ok(`字の割り当ては方格で釣り合っている（${N}人。1字あたり ` +
               `${uniq(seen)[0]}人が見て ${uniq(cnt)[0]}本、条件ごと・方式ごとに ` +
               `${uniq(perCond)[0]}本ずつ、強制選択は ${uniq(pick)[0]}人ずつ）`);
          } else {
            bad(`${N}人では字の出番が均等にならない（本数 ${uniq(cnt).join("/")}、` +
                `人数 ${uniq(seen).join("/")}、強制選択 ${uniq(pick).join("/")}）。` +
                `人数を ${pool.length * nf} の倍数にすること`);
          }
        }
      }
    }
  }

  // ---- 間合いの検算 --------------------------------------------------------
  // 「前の字が現れきってから inter_char_gap_ms 空けて次が始まる」ようになっているか。
  // 視覚的マスキング（前後の刺激が互いの処理を邪魔する現象）が起きるのは、
  // 字と字の**開始どうしの間隔（SOA）が200ミリ秒以下**とされる。そこから十分
  // 離れていることを機械で確かめる（近づけると、見え心地ではなく干渉を測ってしまう）。
  const anim = CFG.visual.base_anim_ms;
  const gap = C.timing.inter_char_gap_ms;
  const soa = anim + gap;
  if (soa < 400) {
    bad(`字と字の開始の間隔(SOA)が ${soa}ms しかない。視覚的マスキングが起きる` +
        `時間帯(200ms以下)に近すぎる。inter_char_gap_ms を増やすこと`);
  } else {
    ok(`字と字の開始の間隔(SOA) ${soa}ms ＝ アニメ${anim}ms ＋ 空き${gap}ms` +
       `（干渉が起きる時間帯200ms以下の ${(soa / 200).toFixed(1)} 倍）`);
  }
  if (C.layout.gap_ratio < 1) {
    bad(`layout.gap_ratio が ${C.layout.gap_ratio}。横並びで字が近すぎる` +
        `（隣の字が邪魔をする crowding の対策として、字間は1文字分以上あける）`);
  } else {
    ok(`横並びの字間は文字幅の ${C.layout.gap_ratio} 倍（crowding 対策）`);
  }

  // ---- 本数と所要のめやす --------------------------------------------------
  // 方式ごとに提示のしかたを絞れるので、掛け算ではなく1本ずつ数える。
  const presFor = (f) => {
    const only = (C.presentations_by_family || {})[f];
    return (only && only.length) ? C.presentations.filter(p => only.indexOf(p) >= 0)
                                 : C.presentations;
  };
  const clips = [];
  for (const f of C.families) for (const p of presFor(f)) for (const cd of C.conditions) {
    clips.push({ family: f, presentation: p, condition: cd.key });
  }
  const n = clips.length;
  const nq = (cch.families || []).length;
  ok(`提示は ${n}本（${C.families.length}方式 × ${C.conditions.length}条件` +
     `${C.presentations.length > 1 ? ` × ${C.presentations.length}通りの出し方` : "・1字だけ"}）` +
     `（7件法${C.items.length}項目 → ${n * C.items.length}回の回答 ＋ 最後の${nq}問）`);
  const cycSingle = anim + C.timing.single.hold_ms + C.timing.single.gap_ms;
  const cycSeq = C.sequence.length * soa + C.timing.sequence.hold_ms + C.timing.sequence.gap_ms;
  ok(`1周の長さ: ${(cycSingle / 1000).toFixed(1)}秒` +
     (C.presentations.indexOf("row5") >= 0 ? ` ／ 5字条件 ${(cycSeq / 1000).toFixed(1)}秒` : ""));
  // 所要 = 前置き100秒 ＋ 1本目の慣れ15秒 ＋ 各本(1周見る時間 ＋ 回答12秒)
  //        ＋ 最後の2問70秒 ＋ 完了画面15秒。
  const nSingle = clips.filter(c => c.presentation === "single").length;
  const nSeq = n - nSingle;
  // 最後の2問: 現れ方の見くらべは選択肢の数に比例して伸びる（1つあたり約14秒）＋
  // 出し方の見くらべ約14秒。以前は4択のときの実測から70秒と置いていた。
  const lastQ = (cch.families || []).length * (C.conditions.length * 14);
  const est = 100 + 15 + nSingle * (cycSingle / 1000 + 12) + nSeq * (cycSeq / 1000 + 12) + lastQ + 15;
  ok(`所要のめやす: 約 ${Math.round(est / 60 * 10) / 10} 分（同意から完了コードまで）`);
}

// ---- まとめ ---------------------------------------------------------------
notes.forEach(m => console.log("  ok  " + m));
if (problems.length) {
  console.log("");
  problems.forEach(m => console.log("  NG  " + m));
  console.log(`\n不合格: ${problems.length} 件。掲載してはいけない。`);
  process.exit(1);
}
console.log("\n合格: 群Cのページは群Bと同じ絵を出す状態になっている。");
