#!/usr/bin/env node
/* =========================================================================
 * 視覚の「水準」と「ぼかしの強さ」を目で決めるためのページ
 * =========================================================================
 * 2026-08-25 作成。
 *
 * **なぜ要るのか。** 2026-08-25 の自己テストで、群A′の水準配置に穴が見つかった。
 *   ・7%と20%のあいだに水準が1つも無く、曲線が立ち上がる帯を跨いでいる
 *   ・「ぼやけ→はっきり」だけ床が無い（最大ぼかし24pxでも読めてしまう）
 * どちらも **数字だけでは決められない**（見えるかどうかは目で判断するしかない）。
 * そこで、**実際の描画コードで描いた絵を並べて、値を選べるようにする**。
 *
 * 実物と同じ絵であることの担保は build_visual_trial_list.js と同じで、
 * transfer.js から描画器をそのまま切り出して埋め込む。
 *
 * 出力: experiment/tools/level_chooser.html
 *
 * 使い方:
 *   node experiment/tools/build_level_chooser.js
 * ========================================================================= */
"use strict";
const fs = require("fs");
const path = require("path");

const EXP = path.resolve(__dirname, "..");
const OUT = path.join(__dirname, "level_chooser.html");

global.window = {};
require(path.join(EXP, "transfer_config.js"));
const CFG = global.window.TRANSFER_CONFIG;

// ---- 描画器を transfer.js からそのまま切り出す ----------------------------
const lines = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8").split("\n");
const from = lines.findIndex(l => l.startsWith("const SIZE = CFG.visual.size_px;"));
let to = lines.findIndex(l => l.startsWith("const RENDERERS = {"));
if (from < 0 || to < 0) { console.error("描画器の範囲が見つからない"); process.exit(1); }
while (to < lines.length && lines[to] !== "};") to++;
const RENDER_SRC = lines.slice(from, to + 1).join("\n");

// ---- 見比べに使う字 -------------------------------------------------------
// 本命8字から、画数の少ない字と多い字の両端＋中くらいを取る。
// （難しさは字形で変わるので、1字だけで決めると偏る）
const CHARS = ["あ", "く", "ま", "ぱ"];
const FAMILIES = ["fade", "reveal", "blur", "wipe"];
const FAMILY_JA = { fade: "うすい→濃い", reveal: "点が増える",
                    blur: "ぼやけ→はっきり", wipe: "端から現れる" };

const BYFAM = CFG.visual.progress_pct_levels_by_family || {};
const levelsOf = (f) => (BYFAM[f] || CFG.visual.progress_pct_levels);
const BLUR_RADII = [24, 32, 40, 48, 56, 64, 80];            // 48 がいまの値

const b64 = {};
for (const ch of CHARS) {
  const p = path.join(EXP, "base", ch + ".png");
  if (!fs.existsSync(p)) { console.error(`画像が無い: ${p}`); process.exit(1); }
  b64[ch] = fs.readFileSync(p).toString("base64");
}

// 60Hz の端末で、その水準を指定したときに**実際に描かれる最大の進み具合**。
// transfer.js の frame() と同じ規則（打ち切りは描く前に判定）で求める。
function actualPct(target, base, hz) {
  const frame = 1000 / hz, st = target / 100;
  let k = 1, last = 0, n = 0;
  while (k < 5000) {
    const s = Math.min(1, k * frame / base);
    if (s >= st) break;
    last = s; n++; k++;
  }
  return { pct: last * 100, frames: n };
}

function cellsFor(levels, fam) {
  const base = CFG.visual.base_anim_ms;
  return levels.map(p => {
    const a = actualPct(p, base, 60);
    // 2026-08-25 に提示規則を直したので、**狙った値がそのまま出る**。
    // 端末で変わるのは「その1枚を何ms見るか」だけになった。
    const shown = (p >= 100) ? "完成形" : `60Hzで約${Math.round(1000 / 60)}ms表示`;
    // ⚠ **静止画では出さない。** 本物は 6%（実測5.6%）なら 60Hz で1枚＝約17ms しか
    //   映らないので、静止画をじっくり見るのとはまったく難しさが違う。
    //   ここでは**実際の再生と同じ規則・同じ時間**で動かす（下の play()）。
    return `<td><canvas class="anim" data-ch="{{CH}}" data-fam="${fam}" data-pct="${p}"></canvas>
     <button class="play" data-ch="{{CH}}" data-fam="${fam}" data-pct="${p}">▶ 再生</button>
     <div class="cap"><b>${p}%</b><br>${shown}</div>
     <div class="cap meas"></div>
     <div class="judge" data-fam="${fam}" data-pct="${p}">
       <button data-v="0" title="まったく分からない">×</button>
       <button data-v="1" title="どちらとも言えない">△</button>
       <button data-v="2" title="はっきり分かる">○</button>
     </div></td>`;
  }).join("");
}

function levelTable(levels, fam, id) {
  const rows = CHARS.map(ch =>
    `<tr><th>${ch}</th>` + cellsFor(levels, fam).replace(/\{\{CH\}\}/g, ch) + `</tr>`).join("");
  return `<table id="${id}"><tr><th></th>` +
    levels.map(p => `<th>${p}%</th>`).join("") + `</tr>${rows}</table>`;
}

function blurTable() {
  const rows = CHARS.map(ch =>
    `<tr><th>${ch}</th>` + BLUR_RADII.map(r =>
      `<td><canvas data-ch="${ch}" data-fam="blur" data-pct="0" data-radius="${r}"></canvas>
       <div class="cap${r === CFG.visual.families.blur.max_radius_px ? " now" : ""}">${r}px${
         r === CFG.visual.families.blur.max_radius_px ? "<br>いま" : ""}</div></td>`).join("")
    + `</tr>`).join("");
  return `<table><tr><th></th>` + BLUR_RADII.map(r => `<th>${r}px</th>`).join("")
    + `</tr>${rows}</table>`;
}

const html = `<!doctype html><meta charset="utf-8">
<title>視覚の水準とぼかしを決める</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:1120px;line-height:1.75}
h1{font-size:20px;margin:0 0 6px}
h2{font-size:16.5px;margin:28px 0 8px;padding-bottom:5px;border-bottom:2px solid #dde1ea}
h3{font-size:14px;margin:16px 0 4px;color:#2b3a52}
p,li{font-size:14px}
table{border-collapse:collapse;margin:8px 0 16px}
th,td{border:1px solid #dde1ea;padding:4px;background:#fff;text-align:center;vertical-align:top}
th{background:#f2f4f8;font-size:12px;color:#59606e}
canvas{width:84px;height:84px;background:#fff;border:1px solid #eceef2;border-radius:4px;display:block}
.cap{font-size:10px;color:#7a8090;margin-top:2px}
.cap.now{color:#9a3412;font-weight:700}
.cap.warn{color:#9a3412;background:#fff0e6;border-radius:3px}
.cap.meas{color:#2f7d4f;min-height:13px}
.judge{display:flex;gap:2px;margin-top:3px}
.judge button{flex:1;font-size:12px;padding:2px 0;border-radius:4px;border:1px solid #cdd3e6;
     background:#fff;cursor:pointer;font-family:inherit;color:#8a90a0}
.judge button.on[data-v="0"]{background:#eef1f6;color:#1b2030;border-color:#8a90a0;font-weight:700}
.judge button.on[data-v="1"]{background:#fff8e6;color:#8a5a00;border-color:#e0c070;font-weight:700}
.judge button.on[data-v="2"]{background:#e9f5ec;color:#245c37;border-color:#8ec39f;font-weight:700}
.verdict{margin:10px 0;padding:11px 14px;border-radius:8px;font-size:13.5px;
     background:#f2f4f8;border:1px solid #dde1ea}
.verdict.ok{background:#f1f9f3;border-color:#a8d3b5}
.verdict.ng{background:#fff8f3;border-color:#f0c4a8}
button.play{width:100%;font-size:11px;padding:3px 0;margin-top:3px;border-radius:5px;
     border:1px solid #2E7D8F;background:#eef6f8;color:#12414c;cursor:pointer;font-family:inherit}
button.play.on{background:#1b2030;color:#fff;border-color:#1b2030}
.box{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:12px 16px;margin:12px 0;
     font-size:13.5px}
.bad{background:#fff8f3;border-color:#f0c4a8}
.good{background:#f1f9f3;border-color:#a8d3b5}
.hl{background:#fff3bf;padding:0 3px;border-radius:3px}
.k{color:#8a90a0;font-size:12.5px}
.tabs button{font-size:13px;padding:5px 12px;margin-right:5px;border-radius:6px;
     border:1px solid #b9c0cf;background:#fff;cursor:pointer;font-family:inherit}
.tabs button.on{background:#1b2030;color:#fff;border-color:#1b2030}
</style>

<h1>視覚の水準とぼかしを決める</h1>
<p class="k">絵は<b>参加者が実際に見るのと同じ描画コード</b>（transfer.js から切り出し）で描いています。
アニメの長さは <b>${CFG.visual.base_anim_ms}ms</b> の設定ですが、ここでは<b>止めた状態</b>を並べています。
実際は動いて止まるので、これより少し分かりにくくなります。</p>

<h2>1. 水準をどこに置くか</h2>
<div class="box bad">
<b class="hl">「▶ 再生」を押すと、本番とまったく同じ規則・同じ時間で動きます。</b><br>
注視点 ＋ が出たあと、字が 0% から伸びて<b>その水準の絵をちょうど1枚出して</b>消えます。
<b>静止画では見ないでください。</b> その1枚は 60Hz なら<b>約17ms</b>しか映らないので、
止まった絵をじっくり見るのとは難しさがまるで違います。<br>
再生すると、実際に描かれた枚数・進み具合・表示時間が下に出ます。
<b>進み具合は狙った値と一致するはず</b>です（2026-08-25 に提示規則を直したため）。<br><br>
<b class="hl">見ていただきたいのは1点だけ:</b>
<b>いちばん左（6%）を再生して、その字が分からないこと。</b><br>
ここが「分からない」でないと、曲線の左端（当て推量に近いところ）が取れません。
逆に分かってしまうなら、水準をもっと薄い側にずらす必要があります。
<div style="margin-top:10px"><button id="playAll" style="font-size:14px;padding:7px 16px;border-radius:8px;
border:1px solid #2E7D8F;background:#eef6f8;color:#12414c;cursor:pointer;font-family:inherit">
▶ いちばん上の字で、薄いほうから順に再生</button></div>
</div>

<div class="tabs" id="famTabs">
${FAMILIES.map((f, i) => `<button data-fam="${f}"${i === 0 ? ' class="on"' : ""}>${FAMILY_JA[f]}</button>`).join("")}
</div>

${FAMILIES.map((f, i) => `<div class="pane" data-fam="${f}" style="display:${i === 0 ? "block" : "none"}">
<h3>${FAMILY_JA[f]}　<span class="k">[${levelsOf(f).join(", ")}]</span>${BYFAM[f] ? ' <span class="k">（この方式だけ別の並び）</span>' : ""}</h3>
${levelTable(levelsOf(f), f, "prop-" + f)}
<div class="verdict" data-fam="${f}"></div>
</div>`).join("")}

<h2>2. ぼかしの最大をいくつにするか</h2>
<div class="box bad">
<b class="hl">見ていただきたいのは1点だけ:</b>
<b>48px（いまの設定）で、その字が分からないこと。</b><br>
これは<b>いちばんぼやけた状態</b>の見た目です。ここで読めてしまうと、
「ぼやけ→はっきり」だけ床が無くなり、曲線を当てはめられません。<br>
もとの24pxでは<b>進み具合1.75%でも4問中4問正解</b>でした（＝読めていた）ので倍にしました。
48pxでもまだ読めるようなら、もっと大きい値にします。
</div>
${blurTable()}

<h2>3. 決めたら</h2>
<p>選んだ値を教えてください。<code>transfer_config.js</code> の
<code>visual.progress_pct_levels</code> と <code>visual.families.blur.max_radius_px</code> に入れ、
出題一覧（<code>visual_trial_list.html</code>）を作り直してもう一度確かめます。</p>
<p class="k">※ 水準を8にしても<b>1人あたりの問題数は70問のまま</b>です（1字につき3水準を担当する仕組みは同じ）。
変わるのはセルの埋まり方だけで、<code>point_subsets</code> には既に <code>"8"</code> があります。</p>

<script>
const IMG_B64 = ${JSON.stringify(b64)};
const CFG = ${JSON.stringify({ visual: CFG.visual })};
const LEVELS = ${JSON.stringify(Object.fromEntries(FAMILIES.map(f => [f, levelsOf(f)])))};
${RENDER_SRC}

(async function () {
  await Promise.all(Object.keys(IMG_B64).map(ch => new Promise(res => {
    const im = new Image();
    im.onload = () => { imgs[ch] = im; res(); };
    im.onerror = () => res();
    im.src = 'data:image/png;base64,' + IMG_B64[ch];
  })));

  const BASE = CFG.visual.base_anim_ms;
  const FIX_MS = CFG.visual.fix_ms;
  const HOLD_END_MS = CFG.visual.endpoint_hold_ms;
  const HOLD_MS = 260;   // 全部見せのときに完成形を残す時間（本番の design.full_hold_ms 相当）

  // ⚠ **transfer.js の runVisualTrial の frame() と同じ規則にすること。**
  //   ・進み具合は s = 経過ms ÷ base_anim_ms の等速
  //   ・打ち切りは**描く前**に判定する（s を過ぎたフレームは1枚も描かない）
  //   ここを変えると、このページの見え方が本番と食い違う。
  function play(cv, btn, meas) {
    return new Promise(resolve => {
      const ch = cv.dataset.ch, fam = cv.dataset.fam;
      const target = Number(cv.dataset.pct);
      const sTarget = Math.max(0, Math.min(1, target / 100));
      const isFull = sTarget >= 1;
      const R = RENDERERS[fam] || RENDERERS.fade;
      cv.width = SIZE; cv.height = SIZE;
      const ctx = cv.getContext('2d');
      try { R.begin(ch, ctx); } catch (e) {}
      if (btn) btn.classList.add('on');
      if (meas) meas.textContent = '';
      // 注視点 ＋（本番と同じ）
      drawBlank(ctx);
      ctx.fillStyle = '#333'; ctx.font = '40px system-ui';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('+', SIZE / 2, SIZE / 2);
      const t0 = performance.now();
      let phase = 'fix', tOn = 0, frames = 0, lastS = 0, lastDraw = 0;
      const done = (now) => {
        drawBlank(ctx);
        if (btn) btn.classList.remove('on');
        if (meas) meas.textContent = frames
          ? '実測 ' + (lastS * 100).toFixed(1) + '% / ' + frames + '枚 / 最後の1枚を'
            + Math.round(now - tOn - lastDraw) + 'ms'
          : '実測 0% / 0枚（何も出ない）';
        resolve();
      };
      // ⚠ **transfer.js の runVisualTrial と同じ規則にすること。**
      //   2026-08-25 に「狙った s ちょうどを必ず1枚描き、**次の**フレームで消す」に変えた。
      //   同じコールバックで消すと、実画面に描かれる前に白紙で上書きされる。
      function frame(now) {
        if (phase === 'fix') {
          if (now - t0 < FIX_MS) { requestAnimationFrame(frame); return; }
          phase = 'char'; tOn = now; frames = 0;
        }
        const el = now - tOn;
        const s = Math.max(0, Math.min(1, el / BASE));
        if (s >= sTarget) {
          if (isFull) {
            R.draw(ctx, ch, 1); lastS = 1; frames++; lastDraw = el;
            setTimeout(() => done(performance.now()), HOLD_MS);
            return;
          }
          R.draw(ctx, ch, sTarget);            // 狙った値にクランプ
          lastS = sTarget; frames++; lastDraw = el;
          // 固定時間だけ残してから消す（transfer.js と同じ規則）。
          setTimeout(() => done(performance.now()), HOLD_END_MS);
          return;
        }
        R.draw(ctx, ch, s); lastS = s; frames++; lastDraw = el;
        requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
  }

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('button.play');
    if (!b) return;
    const td = b.closest('td');
    await play(td.querySelector('canvas.anim'), b, td.querySelector('.meas'));
  });

  // 薄いほうから順に、いま開いている方式のいちばん上の字で再生する
  document.getElementById('playAll').addEventListener('click', async () => {
    const pane = [...document.querySelectorAll('.pane')].find(p => p.style.display !== 'none');
    if (!pane) return;
    const row = pane.querySelector('tr:nth-child(2)');   // 見出し行の次＝いちばん上の字
    for (const td of row.querySelectorAll('td')) {
      await play(td.querySelector('canvas.anim'), td.querySelector('button.play'),
                 td.querySelector('.meas'));
      await new Promise(r => setTimeout(r, 700));
    }
  });

  // 2節（ぼかしの強さくらべ）は静止画のままでよい。
  // ここは「いちばんぼやけた状態で読めるか」を見るところで、時間は関係しないため。
  const io = new IntersectionObserver(es => {
    es.forEach(e => {
      if (!e.isIntersecting) return;
      const cv = e.target;
      io.unobserve(cv);
      if (cv.dataset.done) return;
      cv.dataset.done = '1';
      cv.width = SIZE; cv.height = SIZE;
      const c2 = cv.getContext('2d');
      const keep = CFG.visual.families.blur.max_radius_px;
      if (cv.dataset.radius) CFG.visual.families.blur.max_radius_px = Number(cv.dataset.radius);
      const R = RENDERERS[cv.dataset.fam] || RENDERERS.fade;
      try { R.begin(cv.dataset.ch, c2); R.draw(c2, cv.dataset.ch, Number(cv.dataset.pct) / 100); }
      catch (err) { c2.fillStyle = '#fee'; c2.fillRect(0, 0, SIZE, SIZE); }
      CFG.visual.families.blur.max_radius_px = keep;
    });
  }, { rootMargin: '300px' });
  document.querySelectorAll('canvas[data-radius]').forEach(cv => io.observe(cv));

  // 再生前のキャンバスは白紙にしておく（静止画で判断させないため）
  document.querySelectorAll('canvas.anim').forEach(cv => {
    cv.width = SIZE; cv.height = SIZE;
    const c2 = cv.getContext('2d');
    c2.fillStyle = '#fff'; c2.fillRect(0, 0, SIZE, SIZE);
    c2.fillStyle = '#c8ccd4'; c2.font = '20px system-ui';
    c2.textAlign = 'center'; c2.textBaseline = 'middle';
    c2.fillText('▶', SIZE / 2, SIZE / 2);
  });

  // ---- 判定（曲線が描けるかをその場で見る）--------------------------------
  // 曲線を当てはめるには **床・立ち上がり・天井の3つ**が要る。
  // 床だけ／天井だけでは、傾きも中点も決まらない。
  const marks = {};   // 方式 → { 水準: 0|1|2 }
  function verdict(fam) {
    const lv = LEVELS[fam];
    const m = marks[fam] || {};
    const got = lv.filter(p => m[p] !== undefined);
    const el = document.querySelector('.verdict[data-fam="' + fam + '"]');
    if (!el) return;
    if (got.length < lv.length) {
      el.className = 'verdict';
      el.innerHTML = '<b>判定中…</b> ' + got.length + ' / ' + lv.length +
        ' 個つけました。全部つけると、この並びで曲線が描けるか判定します。';
      return;
    }
    const floor = lv.filter(p => m[p] === 0);
    const mid   = lv.filter(p => m[p] === 1);
    const ceil  = lv.filter(p => m[p] === 2);
    const ng = [];
    if (!floor.length) ng.push('<b>床がありません</b>（いちばん薄い水準でも分かってしまう）。もっと薄い側へずらす必要があります');
    if (!ceil.length)  ng.push('<b>天井がありません</b>（いちばん濃い水準でも分からない）。もっと濃い側へずらす必要があります');
    if (mid.length < 2) ng.push('<b>立ち上がりの点が' + mid.length + '個しかありません</b>（2個以上ほしい）。床と天井のあいだを細かくする必要があります');
    if (floor.length > 3) ng.push('床が' + floor.length + '個あって多すぎます（点の無駄）。薄い側を減らして中間へ回せます');
    if (ceil.length > 3)  ng.push('天井が' + ceil.length + '個あって多すぎます（点の無駄）。濃い側を減らして中間へ回せます');
    const line = '× ' + floor.length + '個 ／ △ ' + mid.length + '個 ／ ○ ' + ceil.length + '個';
    if (!ng.length) {
      el.className = 'verdict ok';
      el.innerHTML = '<b>この並びで曲線が描けます。</b> ' + line +
        '<br><span style="color:#8a90a0">床・立ち上がり・天井がそろっています。</span>';
    } else {
      el.className = 'verdict ng';
      el.innerHTML = '<b>このままでは曲線が描けません。</b> ' + line + '<ul style="margin:6px 0 0">' +
        ng.map(x => '<li>' + x + '</li>').join('') + '</ul>';
    }
  }
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.judge button');
    if (!b) return;
    const box = b.parentElement;
    const fam = box.dataset.fam, pct = Number(box.dataset.pct);
    box.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    (marks[fam] = marks[fam] || {})[pct] = Number(b.dataset.v);
    verdict(fam);
  });
  Object.keys(LEVELS).forEach(verdict);

  document.querySelectorAll('#famTabs button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#famTabs button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.pane').forEach(p => {
      p.style.display = (p.dataset.fam === b.dataset.fam) ? 'block' : 'none';
    });
  }));
})();
</script>
`;
fs.writeFileSync(OUT, html, "utf8");
console.log("  字 " + CHARS.join("") + " × 方式4（方式ごとの水準）＋ ぼかし" + BLUR_RADII.length + "段階");
console.log(`  → ${OUT}  (${(fs.statSync(OUT).size / 1024).toFixed(0)} KB)`);
