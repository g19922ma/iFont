#!/usr/bin/env node
/* =========================================================================
 * gamma=1 と gamma=2 を、同じ1フレームで見比べる
 * =========================================================================
 * 2026-08-25 作成。
 *
 * **何を決めるためのものか。**
 * 群A′で出せるいちばん薄い状態は「アニメの最初の1フレーム」である
 * （60Hz・基準アニメ300ms なら進み具合5.6%）。ここが**当て推量の水準（床）**に
 * なっていないと、曲線の下半分を測れず、生成に使う逆引きが定義できない。
 *
 * fade は「濃さ = 進み具合^gamma」なので、gamma を変えると同じ1フレームでも
 * 出てくる濃さが変わる:
 *     gamma=1.0 → 濃さ 5.6%（255段階の14）
 *     gamma=2.0 → 濃さ 0.31%（同 0.8）
 * どちらが床になるかを**目で決める**ためのページである。
 *
 * ⚠ **静止画で見てはいけない。** 本物は1フレーム＝約17msしか映らないので、
 *   止まった絵を眺めるのとは難しさがまるで違う。ここでは本番と同じ規則・
 *   同じ時間で再生する（transfer.js の runVisualTrial と同じ frame() の規則）。
 *
 * ⚠ **判定の非対称性を承知しておくこと。** 見る人は答えの字を知っているので、
 *     「読めなかった」→ 初見の参加者はもっと読めない。**床だと言える**
 *     「読めた」    → 知っているから読めただけかもしれず、**判断できない**
 *   つまり「読めない」側にだけ強い結論が出る。
 *
 * 出力: experiment/tools/gamma_compare.html
 * 使い方: node experiment/tools/build_gamma_compare.js
 * ========================================================================= */
"use strict";
const fs = require("fs");
const path = require("path");

const EXP = path.resolve(__dirname, "..");
const OUT = path.join(__dirname, "gamma_compare.html");

global.window = {};
require(path.join(EXP, "transfer_config.js"));
const CFG = global.window.TRANSFER_CONFIG;

const lines = fs.readFileSync(path.join(EXP, "transfer.js"), "utf8").split("\n");
const from = lines.findIndex(l => l.startsWith("const SIZE = CFG.visual.size_px;"));
let to = lines.findIndex(l => l.startsWith("const RENDERERS = {"));
if (from < 0 || to < 0) { console.error("描画器が見つからない"); process.exit(1); }
while (to < lines.length && lines[to] !== "};") to++;
const RENDER_SRC = lines.slice(from, to + 1).join("\n");

// 本命8字から、字形の違う4字。1字だけで決めると偏るため。
const CHARS = ["あ", "く", "ま", "ぱ"];
const GAMMAS = [1.0, 1.5, 2.0];
const LOWEST = CFG.visual.progress_pct_levels[0];   // いちばん薄い水準
const BASE = CFG.visual.base_anim_ms;

const b64 = {};
for (const ch of CHARS) {
  const p = path.join(EXP, "base", ch + ".png");
  if (!fs.existsSync(p)) { console.error(`画像が無い: ${p}`); process.exit(1); }
  b64[ch] = fs.readFileSync(p).toString("base64");
}

// 60Hz で実際に描かれる最大の進み具合
const frameMs = 1000 / 60;
let actS = 0, nFrames = 0;
for (let k = 1; k < 5000; k++) {
  const s = Math.min(1, k * frameMs / BASE);
  if (s >= LOWEST / 100) break;
  actS = s; nFrames++;
}
const darkness = (g) => (Math.pow(actS, g) * 100);

const html = `<!doctype html><meta charset="utf-8">
<title>gamma 1 と 2 の見比べ</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:18px;background:#faf9f6;
     color:#1b2030;max-width:820px;line-height:1.8}
h1{font-size:20px;margin:0 0 6px}
h2{font-size:16px;margin:24px 0 8px;padding-bottom:5px;border-bottom:2px solid #dde1ea}
p,li,td,th{font-size:14px}
table{border-collapse:collapse;margin:10px 0}
th,td{border:1px solid #dde1ea;padding:6px;background:#fff;text-align:center;vertical-align:top}
th{background:#f2f4f8;font-size:12.5px}
canvas{width:130px;height:130px;background:#fff;border:1px solid #eceef2;border-radius:6px;display:block}
button.play{width:100%;font-size:12px;padding:5px 0;margin-top:4px;border-radius:6px;
     border:1px solid #2E7D8F;background:#eef6f8;color:#12414c;cursor:pointer;font-family:inherit}
button.play.on{background:#1b2030;color:#fff;border-color:#1b2030}
.meas{font-size:11px;color:#2f7d4f;min-height:14px;margin-top:2px}
.box{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:12px 16px;margin:12px 0;
     font-size:13.5px}
.bad{background:#fff8f3;border-color:#f0c4a8}
.hl{background:#fff3bf;padding:0 3px;border-radius:3px}
.k{color:#8a90a0;font-size:12.5px}
#bar{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:10px 14px;margin:10px 0;z-index:5}
#bar button{font-size:14px;padding:6px 14px;border-radius:8px;border:1px solid #99a;
     background:#fff;cursor:pointer;font-family:inherit;margin-right:6px}
</style>

<h1>gamma 1 と 2 の見比べ（いちばん薄い水準）</h1>
<p class="k">出せるいちばん薄い状態＝アニメの<b>最初の1フレーム</b>です。
いまの設定（基準アニメ ${BASE}ms・60Hz）では、水準 <b>${LOWEST}%</b> を指定すると
実際には <b>${(actS * 100).toFixed(1)}%</b> まで進んだところで消えます（${nFrames}枚・約${Math.round(nFrames * frameMs)}ms）。</p>

<div class="box bad">
<b class="hl">見ていただきたいこと:</b>
<b>「うっすら何かあるのは分かるが、どの字かは分からない」のはどれか。</b><br>
それが理想の床です。<br>
・<b>読める</b> → 床にならない（曲線の左端が取れない）<br>
・<b>まったく何も出ない</b> → 床にはなるが「無」なので、そこから次の水準まで間が空く<br>
・<b>何かあるが読めない</b> → <b>これがいちばん良い</b><br><br>
<span class="k">すでに分かっていること: gamma=1.0（濃さ5.56%）は読めた。
gamma=2.0（濃さ0.31%）は何も出なかった。だから中間の 1.5 を加えました。</span><br><br>
<b>⚠ 丸山さんは答えの字を知っているので、判定は片側にしか効きません。</b><br>
・<b>読めなかった</b> → 初見の参加者はもっと読めない。<b>床だと言えます</b><br>
・<b>読めた</b> → 知っているから読めただけかもしれず、<b>判断できません</b><br>
<span class="k">だから「gamma=2 で読めない」ことが確認できれば十分です。</span>
</div>

<div id="bar">
  <button id="playAll">▶ 4字ぶん、gamma1 → gamma2 の順に再生</button>
  <span class="k" id="now"></span>
</div>

<table>
<tr><th></th>${GAMMAS.map(g => `<th>gamma = ${g.toFixed(1)}<br><span class="k">濃さ ${darkness(g).toFixed(2)}%</span></th>`).join("")}</tr>
${CHARS.map(ch => `<tr><th style="font-size:20px">${ch}</th>` + GAMMAS.map(g =>
  `<td><canvas data-ch="${ch}" data-gamma="${g}"></canvas>
   <button class="play" data-ch="${ch}" data-gamma="${g}">▶ 再生</button>
   <div class="meas"></div></td>`).join("") + `</tr>`).join("")}
</table>

<h2>参考: これまでの実測（fade・gamma は当時 1.0）</h2>
<table>
<tr><th>濃さ</th><th>先生 600ms</th><th>丸山さん 300ms</th></tr>
<tr><td>2.5〜2.8%</td><td>3/7（43%）</td><td class="k">データなし</td></tr>
<tr><td><b>5.3〜5.9%</b></td><td><b>9/9（100%）</b></td><td class="k">データなし</td></tr>
<tr><td>12.5%</td><td>11/11</td><td>1/1</td></tr>
<tr><td>100%</td><td>12/12</td><td>2/2</td></tr>
</table>
<p class="k">600ms では濃さ5.6%が完全に読めています。300ms（見ている時間が半分）での
データはまだありません。だからこのページで確かめます。</p>

<script>
const IMG_B64 = ${JSON.stringify(b64)};
const CFG = ${JSON.stringify({ visual: CFG.visual })};
${RENDER_SRC}

const BASE = ${BASE};
const FIX_MS = CFG.visual.fix_ms;
const HOLD_END_MS = CFG.visual.endpoint_hold_ms;
const TARGET = ${LOWEST} / 100;

(async function () {
  await Promise.all(Object.keys(IMG_B64).map(ch => new Promise(res => {
    const im = new Image();
    im.onload = () => { imgs[ch] = im; res(); };
    im.onerror = () => res();
    im.src = 'data:image/png;base64,' + IMG_B64[ch];
  })));

  // ⚠ transfer.js の runVisualTrial の frame() と同じ規則にすること。
  //   進み具合は s = 経過ms ÷ base_anim_ms の等速。打ち切りは**描く前**に判定する。
  function play(cv, btn, meas) {
    return new Promise(resolve => {
      const ch = cv.dataset.ch;
      const keep = CFG.visual.families.fade.gamma;
      CFG.visual.families.fade.gamma = Number(cv.dataset.gamma);
      cv.width = SIZE; cv.height = SIZE;
      const ctx = cv.getContext('2d');
      if (btn) btn.classList.add('on');
      if (meas) meas.textContent = '';
      drawBlank(ctx);
      ctx.fillStyle = '#333'; ctx.font = '40px system-ui';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('+', SIZE / 2, SIZE / 2);
      const t0 = performance.now();
      let phase = 'fix', tOn = 0, frames = 0, lastS = 0;
      const done = (now) => {
        drawBlank(ctx);
        CFG.visual.families.fade.gamma = keep;
        if (btn) btn.classList.remove('on');
        if (meas) meas.textContent = frames
          ? '進み ' + (lastS * 100).toFixed(1) + '% / ' + frames + '枚 / '
            + Math.round(now - tOn) + 'ms'
          : '1枚も出ませんでした';
        resolve();
      };
      // ⚠ transfer.js の runVisualTrial と同じ規則にすること（2026-08-25 の変更後）。
      //   較正は「狙った s ちょうどを必ず1枚描き、次のフレームで消す」。
      function frame(now) {
        if (phase === 'fix') {
          if (now - t0 < FIX_MS) { requestAnimationFrame(frame); return; }
          phase = 'char'; tOn = now; frames = 0;
        }
        const el = now - tOn;
        const s = Math.max(0, Math.min(1, el / BASE));
        if (s >= TARGET) {
          RENDERERS.fade.draw(ctx, ch, TARGET);     // 狙った値にクランプ
          lastS = TARGET; frames++;
          setTimeout(() => done(performance.now()), HOLD_END_MS);
          return;
        }
        RENDERERS.fade.draw(ctx, ch, s);
        lastS = s; frames++;
        requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
  }

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('button.play');
    if (!b) return;
    const td = b.closest('td');
    await play(td.querySelector('canvas'), b, td.querySelector('.meas'));
  });

  document.getElementById('playAll').addEventListener('click', async () => {
    const now = document.getElementById('now');
    for (const tr of document.querySelectorAll('table tr')) {
      const tds = tr.querySelectorAll('td');
      if (!tds.length) continue;
      for (const td of tds) {
        const cv = td.querySelector('canvas');
        if (!cv) continue;
        now.textContent = cv.dataset.ch + ' … gamma ' + cv.dataset.gamma;
        await play(cv, td.querySelector('button.play'), td.querySelector('.meas'));
        await new Promise(r => setTimeout(r, 800));
      }
    }
    now.textContent = '';
  });

  // 再生前は白紙にしておく（静止画で判断させないため）
  document.querySelectorAll('canvas').forEach(cv => {
    cv.width = SIZE; cv.height = SIZE;
    const c2 = cv.getContext('2d');
    c2.fillStyle = '#fff'; c2.fillRect(0, 0, SIZE, SIZE);
    c2.fillStyle = '#c8ccd4'; c2.font = '26px system-ui';
    c2.textAlign = 'center'; c2.textBaseline = 'middle';
    c2.fillText('▶', SIZE / 2, SIZE / 2);
  });
})();
</script>
`;
fs.writeFileSync(OUT, html, "utf8");
console.log(`  いちばん薄い水準 ${LOWEST}% → 60Hzでの実測 ${(actS * 100).toFixed(1)}%（${nFrames}枚）`);
console.log(`  そのときの濃さ: gamma=1.0 で ${darkness(1).toFixed(2)}% / gamma=2.0 で ${darkness(2).toFixed(2)}%`);
console.log(`  → ${OUT}`);
