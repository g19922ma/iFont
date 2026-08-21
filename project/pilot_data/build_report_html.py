#!/usr/bin/env python3
"""
パイロット分析の1枚ものHTMLを作る
=================================
project/パイロット分析_20260821.md と pilot_data/out/*.png をもとに、
外部への参照を持たない自己完結のHTMLを書き出す。図はbase64で埋め込む。

  python3 project/pilot_data/build_report_html.py

出力: project/パイロット分析_20260821.html
"""
import base64
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
OUT = os.path.join(PROJ, "パイロット分析_20260821.html")


def img(name):
    """PNG を data: URI にして返す（外部ファイルを参照しないため）。"""
    path = os.path.join(HERE, "out", name)
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


CSS = """
:root{
  --bg:#fbfbfa; --fg:#22252b; --muted:#61666f; --line:#e2e3e6; --card:#ffffff;
  --accent:#2E7D8F; --accent2:#1E2A5E; --warn-bg:#fff6e8; --warn-line:#e6c98f;
  --warn-fg:#6b4a10; --ok:#2E7D8F; --ng:#b4483c; --chip:#eef2f4;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#15171b; --fg:#e6e8ec; --muted:#a2a8b3; --line:#2c3037; --card:#1c1f25;
    --accent:#63b6c7; --accent2:#9fb0e8; --warn-bg:#2c2413; --warn-line:#6b5622;
    --warn-fg:#f0d9a8; --ok:#63b6c7; --ng:#e0857a; --chip:#252a31;
  }
}
:root[data-theme="dark"]{
  --bg:#15171b; --fg:#e6e8ec; --muted:#a2a8b3; --line:#2c3037; --card:#1c1f25;
  --accent:#63b6c7; --accent2:#9fb0e8; --warn-bg:#2c2413; --warn-line:#6b5622;
  --warn-fg:#f0d9a8; --ok:#63b6c7; --ng:#e0857a; --chip:#252a31;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--fg);
  font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",
    "Noto Sans JP","Meiryo",system-ui,sans-serif;
  font-size:16px; line-height:1.85; letter-spacing:.01em;
}
.wrap{max-width:840px; margin:0 auto; padding:40px 20px 80px}
h1{font-size:26px; line-height:1.45; margin:0 0 6px; letter-spacing:.02em}
h2{font-size:19px; margin:52px 0 14px; padding-bottom:8px;
   border-bottom:2px solid var(--line); letter-spacing:.02em}
h3{font-size:16px; margin:28px 0 10px; color:var(--accent2)}
p{margin:0 0 14px}
a{color:var(--accent)}
.sub{color:var(--muted); font-size:14px; margin:0 0 4px}
.meta{color:var(--muted); font-size:13.5px; line-height:1.9; margin:18px 0 0;
      padding-top:14px; border-top:1px solid var(--line)}
.warn{background:var(--warn-bg); border:1px solid var(--warn-line); color:var(--warn-fg);
      border-radius:10px; padding:18px 20px; margin:26px 0 30px}
.warn h2{margin:0 0 10px; border:0; padding:0; font-size:17px; color:inherit}
.warn ol{margin:10px 0 10px; padding-left:1.3em}
.warn li{margin:4px 0}
.warn .tail{margin:12px 0 0; font-size:14.5px}
.cards{display:flex; flex-wrap:wrap; gap:12px; margin:22px 0 8px}
.card{flex:1 1 190px; background:var(--card); border:1px solid var(--line);
      border-radius:10px; padding:14px 16px}
.card .k{font-size:12.5px; color:var(--muted); margin:0 0 4px; letter-spacing:.04em}
.card .v{font-size:24px; font-weight:700; color:var(--accent); line-height:1.3; margin:0}
.card .n{font-size:13px; color:var(--muted); margin:4px 0 0; line-height:1.6}
.scroll{overflow-x:auto; -webkit-overflow-scrolling:touch; margin:14px 0 6px;
        border:1px solid var(--line); border-radius:10px; background:var(--card)}
table{border-collapse:collapse; width:100%; min-width:min-content; font-size:14.5px}
/* 文章の入るセルは折り返す。数値と○×の列だけ1行に保つ（下の .c / .n）。 */
th,td{padding:9px 13px; text-align:left; border-bottom:1px solid var(--line);
      white-space:normal; vertical-align:top; line-height:1.7}
thead th{white-space:nowrap}
td:first-child{white-space:nowrap}
thead th{background:var(--chip); font-weight:600; font-size:13.5px; letter-spacing:.03em}
tbody tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap}
td.c,th.c{text-align:center; white-space:nowrap}
/* コードの断片が長いときは、その語の途中でも折り返してよい。 */
td code{white-space:nowrap}
td.wrapcode{white-space:normal}
.ok{color:var(--ok); font-weight:700}
.ng{color:var(--ng); font-weight:700}
.dim{color:var(--muted)}
figure{margin:22px 0 8px}
figure img{width:100%; height:auto; display:block; border:1px solid var(--line);
           border-radius:10px; background:#fff}
figcaption{color:var(--muted); font-size:13.5px; margin-top:8px; line-height:1.75}
.note{background:var(--card); border-left:3px solid var(--accent); border-radius:0 8px 8px 0;
      padding:12px 16px; margin:18px 0; font-size:15px}
.note b{color:var(--accent2)}
code{background:var(--chip); padding:1px 6px; border-radius:5px; font-size:13.5px;
     font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
ul{padding-left:1.3em; margin:0 0 14px}
li{margin:5px 0}
.tag{display:inline-block; background:var(--chip); color:var(--muted); border-radius:999px;
     padding:2px 11px; font-size:12.5px; margin-right:6px}
/* RQ の節 */
.rq{border:1px solid var(--line); border-radius:12px; background:var(--card);
    padding:22px 24px; margin:26px 0}
.rq > h2{margin:0 0 4px; border:0; padding:0}
.rq .q{color:var(--muted); font-size:14.5px; margin:0 0 14px}
.rq h3{margin:20px 0 8px; font-size:15px}
.rq h3:first-of-type{margin-top:16px}
.rq > *:last-child{margin-bottom:0}
.badge{display:inline-block; border-radius:999px; padding:4px 14px; font-size:13px;
       font-weight:700; letter-spacing:.03em; margin:0 0 12px; border:1px solid transparent;
       white-space:nowrap}
.b-none{background:#efe6e4; color:#8c4034; border-color:#dcc4bf}
.b-hint{background:#e8f0e4; color:#3d6b30; border-color:#c6dbbc}
.b-todo{background:#e9eaee; color:#4f5560; border-color:#d3d6dd}
.b-ok{background:#e2eff2; color:#1f5c6b; border-color:#bcd9e0}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]) .b-none{background:#3a2320; color:#f0b3a8; border-color:#5c3830}
  :root:not([data-theme="light"]) .b-hint{background:#22301c; color:#b4d9a4; border-color:#3c5232}
  :root:not([data-theme="light"]) .b-todo{background:#272a30; color:#b6bcc7; border-color:#3b4048}
  :root:not([data-theme="light"]) .b-ok{background:#193038; color:#9fd4e0; border-color:#2b4d59}
}
:root[data-theme="dark"] .b-none{background:#3a2320; color:#f0b3a8; border-color:#5c3830}
:root[data-theme="dark"] .b-hint{background:#22301c; color:#b4d9a4; border-color:#3c5232}
:root[data-theme="dark"] .b-todo{background:#272a30; color:#b6bcc7; border-color:#3b4048}
:root[data-theme="dark"] .b-ok{background:#193038; color:#9fd4e0; border-color:#2b4d59}
blockquote{margin:16px 0; padding:14px 18px; border-left:3px solid var(--accent2);
           background:var(--chip); border-radius:0 8px 8px 0; font-size:15px}
blockquote p:last-child{margin-bottom:0}
details{margin:16px 0; border:1px solid var(--line); border-radius:9px; background:var(--bg)}
details > summary{cursor:pointer; padding:11px 15px; font-size:14.5px; font-weight:600;
                  color:var(--accent2); list-style:none}
details > summary::-webkit-details-marker{display:none}
details > summary::before{content:"▸ "; color:var(--muted)}
details[open] > summary::before{content:"▾ "}
details .body{padding:0 15px 12px}
@media (max-width:560px){
  .wrap{padding:28px 14px 60px}
  h1{font-size:22px} h2{font-size:17.5px} body{font-size:15.5px}
  .card .v{font-size:21px}
  .rq{padding:16px 15px}
}
"""

HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>パイロット分析 8/21</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">

<h1>パイロット分析 8/21</h1>
<p class="sub">転写検証実験・研究者自身による通し（聴覚94問＋視覚117問＝211行）</p>
<p class="sub"><span class="tag">設定版 prov-2026-08-20b</span><span class="tag">実装 v3.0</span><span class="tag">2026-08-21</span></p>

<div class="warn">
<h2>⚠ これは実験の結果ではありません</h2>
<p style="margin:0">数字を「この字は何ミリ秒で分かる」と読まないでください。
天井に張り付くのが正常で、実際に張り付きました。理由は4つあり、どれも正答しやすい向きに効きます。</p>
<ol>
<li><b>1人ぶんしかない。</b>1つのマス目に回答が1つなので、正答率は0%か100%しか取りません。傾きも中点も推定できません。</li>
<li><b>答えた人が実験の作者本人。</b>出題される8字も、まぎれ字が混ざることも、打ち切りの時点も全部知っています。</li>
<li><b>正解を知っている。</b>刺激を作った本人なので、断片から候補が絞れます。</li>
<li><b>同じ人が短時間に2回通している</b>（先に聴覚、あとで視覚）。</li>
</ol>
</div>

<h2>RQ対応表</h2>

<p>計画書3章で立てた4つの問いに対して、このパイロットがどこまで届いたかの一覧です。</p>

<div class="scroll"><table>
<thead><tr><th>問い</th><th>中身</th><th>状態</th><th>一行で言うと</th></tr></thead>
<tbody>
<tr><td><b><a href="#rq1">RQ1</a></b></td><td>音声の曲線を文字アニメで再現できるか</td><td><span class="badge b-none">まだ答えられない</span></td><td>生成工程の前なので未回答。測る配管が通ったことだけ確認できた</td></tr>
<tr><td><b><a href="#rq2">RQ2</a></b></td><td>方式によって目標に近づけやすさが違うか</td><td><span class="badge b-hint">予備的な兆候あり</span></td><td>方式差は実在しそう。ワイプだけ大きく崩れ、フェードは二値的に感じられた</td></tr>
<tr><td><b><a href="#rq3">RQ3</a></b></td><td>その表示を続けて見ていられるか</td><td><span class="badge b-todo">未実施</span></td><td>見え心地の画面は検証フェーズにしか出ないので、今回は通っていない</td></tr>
<tr><td><b><a href="#rq4">RQ4</a></b></td><td>識別率は進み具合だけで決まるか、速さにも依存するか</td><td><span class="badge b-ok">仕組みの動作確認済み</span></td><td>2水準が正しく出題されることを確認。両方とも天井で差は測れなかった</td></tr>
</tbody></table></div>

<h2>0. 土台 — 処理経路の検証</h2>

<p>RQに答える前に、<b>測る配管そのものが通っているか</b>を確かめるのがこの通しの主目的でした。
そしてこれは達成できました。</p>

<div class="cards">
  <div class="card"><p class="k">記録の総数</p><p class="v">211 行</p><p class="n">聴覚94＋視覚117。設計どおり</p></div>
  <div class="card"><p class="k">狙いと実測のずれ</p><p class="v">1.07 pt</p><p class="n">1フレーム分手前で止まる設計どおり</p></div>
  <div class="card"><p class="k">確認問題A</p><p class="v">11/11</p><p class="n">刺激は正しく届いている</p></div>
  <div class="card"><p class="k">配管</p><p class="v">全通</p><p class="n">ブラウザ→GAS→シート→集計→図</p></div>
</div>

<div class="scroll"><table>
<thead><tr><th>見たこと</th><th>結果</th></tr></thead>
<tbody>
<tr><td>記録の総数</td><td>聴覚94問・視覚117問。設計どおり</td></tr>
<tr><td>視覚が117問になった理由</td><td>RQ4の速さ2水準ぶん。94問 → 117問と設計どおり増えた</td></tr>
<tr><td>列の中身</td><td><code>target_char</code> <code>gate_ms</code> <code>progress_pct</code> <code>family</code> <code>base_anim_ms</code> <code>rt_ms</code> <code>actual_s</code> すべて期待どおり</td></tr>
<tr><td>狙いと実測のずれ（視覚70問）</td><td>平均 <b>1.07 ポイント手前</b>（最大2.20）。打ち切り判定を描画の前に置いた設計どおり</td></tr>
<tr><td>確認問題A（全部見せ・全部聞かせ）</td><td>聴覚 5/5・視覚 6/6</td></tr>
</tbody></table></div>

<div class="rq" id="rq1">
<h2>RQ1 — 音声の曲線を文字アニメで再現できるか</h2>
<p class="q">仮説1（転写は効く）・仮説2（速さ合わせでは足りない）</p>
<span class="badge b-none">まだ答えられない</span>

<h3>(a) このパイロットから言えること</h3>
<ul>
<li>音声側の<b>目標曲線を作るための測定が、実際に動く</b>ことを確認しました。8字すべてについて7時点ぶんの回答が欠けなく記録されました。</li>
<li>打ち切り7時点（20〜220ミリ秒）が、少なくとも本人では<b>正答率の動く範囲を覆えていました</b>。最も遅い「ら」が110ミリ秒なので、上限220ミリ秒には余裕があります。</li>
</ul>

<h3>(b) 言えない理由</h3>
<ul>
<li><b>生成工程をまだ回していません。</b>RQ1の判定に要るのは「群Bの曲線」と「群Atestの曲線」の比較ですが、どちらもまだ取っていません。較正すら本番のものではありません。</li>
<li>n=1 なので曲線は階段にしかならず、逆引きの材料になる形をしていません。</li>
</ul>

<h3>(c) いつ・どのデータが答えるか</h3>
<p><b>検証フェーズ</b>で、群B（生成アニメを見た初見の人）と群Atest（音声を聞いた初見の人）の曲線の距離Eで判定します。
その前に較正フェーズの群Acal・群A′が要ります。</p>

<h3>参考: 音声の段位（このパイロットの生データ）</h3>
<p>ターゲット56問の正答率82%、まぎれ字28問で61%。各マスは1問です。
8字が4段に分かれ、<b>最速と最遅の差は約90ミリ秒</b>ありました。</p>

<div class="scroll"><table>
<thead><tr><th>字</th><th class="c">20ms</th><th class="c">40ms</th><th class="c">60ms</th><th class="c">80ms</th><th class="c">110ms</th><th class="c">150ms</th><th class="c">220ms</th><th>ここから上は全部正解</th></tr></thead>
<tbody>
{audio_rows}
</tbody></table></div>
<p class="sub"><span class="ok">○</span>=正解　<span class="ng">×</span>=誤答</p>

<figure>
  <img src="{img_audio}" alt="音声の字ごとの識別率曲線">
  <figcaption>字ごとの識別率曲線（音声）。1人ぶんだと正答率が0%と100%しか取らず線が重なるため、
  字ごとに縦へ最大±1.4ポイントずらし、線の種類も変えてあります。</figcaption>
</figure>

<div class="note">
<p style="margin:0"><b>順序は音の性質と一致しています。</b>
<b>あ・が が早い</b>のは、母音「あ」は最初から声が出ており、「が」も有声の破裂で閉鎖のあいだから声帯が鳴っているため。
<b>ら が遅い</b>のは、はじき音が短く弱く、直後の母音が来るまで決まらないため。
<b>つ が中間</b>なのは、破擦音が「閉鎖→破裂→摩擦」と進み、摩擦が始まるまで「た」と区別できないためです。</p>
</div>

<div class="note">
<p style="margin:0"><b>時点の配置への宿題。</b>下限20ミリ秒は あ・が に易しすぎました。
一般参加者ではもっと下がるはずですが、A2で配置を決めるときの材料になります。</p>
</div>
</div>

<div class="rq" id="rq2">
<h2>RQ2 — 方式によって目標に近づけやすさが違うか</h2>
<p class="q">同じ較正のやり方を4方式に使ったとき、外から与えた目標の曲線にどれだけ近づけられるか</p>
<span class="badge b-hint">予備的な兆候あり</span>

<h3>(a) このパイロットから言えること</h3>
<p><b>方式による違いは実在しそうだ</b>、というところまでです。根拠は3つあります。</p>
<ul>
<li><b>ワイプだけ大きく崩れた。</b>誤答はほぼワイプに集中しました。</li>
<li><b>フェードは「見えるか見えないか」の二値に感じられた</b>（下記の内観報告）。</li>
<li><b>フェード・部分表示・ぼかしは 6% でも全問正解だった。</b>天井の出方も方式で違います。</li>
</ul>

<div class="scroll"><table>
<thead><tr><th>方式</th><th class="n">正答</th><th class="n">率</th></tr></thead>
<tbody>
<tr><td>フェード</td><td class="n">28/28</td><td class="n">100%</td></tr>
<tr><td>部分表示</td><td class="n">14/14</td><td class="n">100%</td></tr>
<tr><td>ぼかし解除</td><td class="n">13/14</td><td class="n">93%</td></tr>
<tr><td><b>ワイプ</b></td><td class="n"><b>5/14</b></td><td class="n"><b class="ng">36%</b></td></tr>
</tbody></table></div>

<h3>(b) 言えない理由</h3>
<ul>
<li><b>字と方式が完全に交絡しています。</b>1人の参加者は1つの字を1つの方式でしか見ない割付なので、「ワイプが難しい」のか「ワイプに当たった か・つ が難しい」のかを分けられません。</li>
<li>n=1 で、しかも<b>本人は正解を知っています</b>。6%で全問正解というのは、方式の性質ではなく出題範囲を知っていることの反映と考えるのが自然です。</li>
<li>RQ2が問うのは「読みやすさ」ではなく<b>「外から与えた目標の曲線にどれだけ近づけられるか」</b>です。目標の曲線がまだ無いので、本来の意味での比較は始まってすらいません。</li>
</ul>

<h3>(c) いつ・どのデータが答えるか</h3>
<p>較正フェーズの<b>群A′</b>で方式ごとの視覚の曲線を測り、検証フェーズの<b>群B</b>で4方式の生成表示を測ります。
忠実さの比較はそこで行います。探索の2方式（ぼかし解除・ワイプ）は対照を持たないので、順位と傾向の報告にとどめます。</p>

<h3>話者本人の内観報告（2026-08-21）</h3>
<blockquote>
<p><b>フェードは「見えるか見えないか」の二択に感じられ、中間の状態がなかった。</b>
文字が大きいため、存在を検出できた時点でほぼ識別もできてしまう——つまり<b>検出と識別が同時に来ている</b>可能性がある。
<b>部分表示はこれと対照的で、「画素は見えるが字は分からない」という中間状態が構造的に存在する。</b></p>
</blockquote>
<p>この見立てが正しければ、フェードでは進み具合を細かく刻んでも正答率が0%と100%のあいだをほとんど通らず、
曲線が階段状になります。<b>初見データの曲線が階段状かどうかが、下見の判定材料になります。</b></p>
<p>下見への備えとして次の2つを仕込みました。どちらも既定では現行と同じ挙動です。</p>
<ul>
<li><b>フェードの濃さの割り当てを設定に出しました。</b><code>visual.families.fade.gamma</code> で「進み具合 → 濃さ」の対応を変えられます。既定の1.0は現行と完全に同一で、1.0より大きくすると序盤を薄めに通せます。</li>
<li><b>視覚の打ち切り水準に、より薄い 3% を下見だけ足しました</b>（<code>visual.pilot_extra_levels</code>）。初見の人の床がどこにあるかを見るためで、本番の掲載前に外します。</li>
</ul>

<h3>参考: 字ごとの割当と結果</h3>
<div class="note">
<p style="margin:0"><b>下の表は「字の曲線」ではなく「字 × 方式の曲線」です。</b>1人は1つの字を1つの方式でしか見ません。</p>
</div>

<div class="scroll"><table>
<thead><tr><th>字</th><th>あ</th><th>か</th><th>が</th><th>し</th><th>つ</th><th>ぱ</th><th>ま</th><th>ら</th></tr></thead>
<tbody><tr><td>方式</td><td>ぼかし</td><td>ワイプ</td><td>フェード</td><td>ぼかし</td><td>ワイプ</td><td>部分表示</td><td>フェード</td><td>部分表示</td></tr></tbody>
</table></div>

<div class="scroll"><table>
<thead><tr><th>字（方式）</th><th class="c">6%</th><th class="c">13%</th><th class="c">22%</th><th class="c">34%</th><th class="c">50%</th><th class="c">70%</th><th class="c">100%</th></tr></thead>
<tbody>
{visual_rows}
</tbody></table></div>

<figure>
  <img src="{img_visual}" alt="視覚の字ごとの識別率曲線">
  <figcaption>字ごとの識別率曲線（視覚）。オレンジの破線が「か」（ワイプ）で、50%で当たったあと70%で外し、100%で戻っています。
  1問ずつしかないので、この上下は誤差の範囲です。</figcaption>
</figure>

<div class="note">
<p style="margin:0"><b>ワイプの混同は方式の性質と見てよさそうです。</b>
ワイプは<b>左端から順に見せる</b>方式なので、かなの左半分だけでは字が決まりません。
誤答も <b>か→た</b>・<b>か→つ</b>・<b>つ→て</b>・<b>つ→ら</b> と、左側の形が似た字への取り違えばかりでした。</p>
</div>
</div>

<div class="rq" id="rq3">
<h2>RQ3 — その表示を続けて見ていられるか</h2>
<p class="q">継続して閲覧する際の主観的な見やすさ・負担</p>
<span class="badge b-todo">未実施</span>

<h3>(a) このパイロットから言えること</h3>
<p><b>何もありません。</b>見え心地のデータは1件も取れていません。</p>

<h3>(b) 言えない理由</h3>
<p>見え心地の質問は、<b>群Bの識別課題がすべて終わったあとにだけ</b>出る画面です（計画書 4.5）。
今回通したのは較正フェーズ（群Acal・群A′）なので、この画面自体を通っていません。
<code>transfer_wellbeing</code> シートは0行のままです。</p>

<h3>(c) いつ・どのデータが答えるか</h3>
<p><b>検証フェーズの群B</b>の最後です。代表字2字 × 4方式 = 8本を打ち切りなしで見てもらい、
7件法3項目と最後の4択に答えてもらいます。</p>
</div>

<div class="rq" id="rq4">
<h2>RQ4 — 識別率は進み具合だけで決まるか、速さにも依存するか</h2>
<p class="q">同じ進み具合まで見せたとき、そこへ速く着いたかゆっくり着いたかで正答率が変わるか</p>
<span class="badge b-ok">仕組みの動作確認済み・判定は不能</span>

<h3>(a) このパイロットから言えること</h3>
<p><b>仕掛けが設計どおり動いている</b>ことを確認しました。</p>
<ul>
<li><code>base_anim_ms</code> 列が 600 と 1000 に正しく分かれた。</li>
<li>フェードに割り当たった2字（が・ま）だけが、各水準で2回ずつ出題された。</li>
<li>非フェードの字は600のままだった。</li>
<li>この2水準ぶんで、視覚の問題数が 94問 → 117問 と設計どおり増えた。</li>
</ul>

<h3>(b) 言えない理由</h3>
<p><b>両方の速さとも天井に張り付きました。</b>差を見ようにも、比べる2つがどちらも100%では何も分かりません。</p>

<div class="scroll"><table>
<thead><tr><th>基準アニメ</th><th class="n">正答</th><th class="n">率</th><th>7水準の内訳</th></tr></thead>
<tbody>
<tr><td>600ミリ秒</td><td class="n">14/14</td><td class="n">100%</td><td>すべての水準で 2/2</td></tr>
<tr><td>1000ミリ秒</td><td class="n">14/14</td><td class="n">100%</td><td>すべての水準で 2/2</td></tr>
</tbody></table></div>

<h3>(c) いつ・どのデータが答えるか</h3>
<p><b>本番の視覚較正（群A′）</b>が本回答です。効果量と信頼区間を付けて報告します。
さらに検証フェーズの一致（群B vs 群Atest）が、この見方そのものの総合テストを兼ねます。
A2では「本番の人数だとどのくらいの幅の信頼区間が付くか」を先に見積もります。</p>
</div>

<h2>横断: 操作チェック</h2>

<div class="scroll"><table>
<thead><tr><th>確認</th><th class="c">聴覚</th><th class="c">視覚</th><th>読み方</th></tr></thead>
<tbody>
<tr><td>確認A　全部見せ・全部聞かせ</td><td class="c">5/5</td><td class="c">6/6</td><td>刺激そのものは正しく届いている</td></tr>
<tr><td>確認C　最小の提示</td><td class="c"><b class="ng">5/5</b></td><td class="c">4/6</td><td><b>本来は低く出るべき問題。天井に張り付いた</b></td></tr>
</tbody></table></div>

<p>確認Cが聴覚で5問すべて正解したのは、この下見の性格をいちばんよく表しています。
20ミリ秒しか聞こえていないのに全問当たるのは、出題範囲と正解を知っているからです。
<b>本番でここが高く出たら、学習の兆候として扱います。</b></p>

<h2>横断: 誤答の内訳</h2>

<div class="scroll"><table>
<thead><tr><th class="c">正解</th><th class="c">答えた字</th><th class="n">回数</th><th>読み方</th></tr></thead>
<tbody>
<tr><td class="c">ら</td><td class="c">な</td><td class="n">3</td><td>音声。弾く音が届かず、有声の子音とだけ分かっている段階</td></tr>
<tr><td class="c">つ</td><td class="c">て</td><td class="n">3</td><td>視覚・ワイプ。左半分が似ている</td></tr>
<tr><td class="c">つ</td><td class="c">ち</td><td class="n">2</td><td>音声。摩擦が始まる前で破擦音の区別がつかない</td></tr>
<tr><td class="c">か</td><td class="c">た</td><td class="n">2</td><td>視覚・ワイプ。左半分が似ている</td></tr>
<tr><td class="c">か</td><td class="c">ぱ</td><td class="n">1</td><td>音声20ms。どちらも無声の破裂で調音位置がまだ届いていない</td></tr>
<tr><td class="c">し</td><td class="c">す</td><td class="n">1</td><td>音声20ms</td></tr>
<tr><td class="c">ら</td><td class="c">ほ</td><td class="n">1</td><td>音声20ms</td></tr>
<tr><td class="c">ぱ</td><td class="c">ぷ</td><td class="n">1</td><td>音声20ms。母音が届いていない</td></tr>
<tr><td class="c">ま</td><td class="c">ふ</td><td class="n">1</td><td>音声20ms</td></tr>
<tr><td class="c">つ</td><td class="c">ら</td><td class="n">1</td><td>視覚・ワイプ</td></tr>
<tr><td class="c">あ</td><td class="c">ら</td><td class="n">1</td><td>視覚・ぼかし6%</td></tr>
<tr><td class="c">か</td><td class="c">ら</td><td class="n">1</td><td>視覚・ワイプ</td></tr>
<tr><td class="c">か</td><td class="c">つ</td><td class="n">1</td><td>視覚・ワイプ</td></tr>
<tr><td class="c">か</td><td class="c">が</td><td class="n">1</td><td>視覚・ワイプ70%。濁点の位置まで届いていない</td></tr>
</tbody></table></div>

<h2>横断: 反応時間と所要時間</h2>

<div class="scroll"><table>
<thead><tr><th>集団</th><th class="n">問題数</th><th class="n">所要（開始〜完了コード）</th><th class="n">反応時間の中央値</th></tr></thead>
<tbody>
<tr><td>聴覚</td><td class="n">94問</td><td class="n"><b>598秒（約10.0分）</b></td><td class="n">1562ms</td></tr>
<tr><td>視覚</td><td class="n">117問</td><td class="n"><b>444秒（約7.4分）</b></td><td class="n">1381ms</td></tr>
</tbody></table></div>

<div class="note">
<p style="margin:0"><b>問題数が多い視覚のほうが短い。</b>
聴覚は1問ごとに「ピッ」の合図音と0.6秒の待ち、刺激の再生、終了の合図音が入るため、
機械が使う時間が固定で乗ります。視覚は注視点400ミリ秒＋提示だけで済みます。</p>
</div>

<p>この実測をもとに、掲載文の所要は <b>「約10分」</b> に確定しました。報酬は200円のままです。
本人は操作に慣れているので、一般参加者では1〜2分延びる見込みです。
なお下見で 3% の水準を足したことにより、視覚の問題数は 117問 → <b>134問</b>（約8.5分見込み）になります。
掲載の「約10分」には収まります。</p>

<h2>ここから本番へ持っていく宿題</h2>

<ul>
<li><b>時点の配置（A2）</b>：聴覚の下限20ミリ秒は あ・が に易しすぎました。より短い時点を足すか、下限を下げることを検討します。</li>
<li><b>視覚の水準（A2）</b>：6%で全問正解だったため、この下見からは判断できません。下見で足した3%とあわせて、初見のデータで床を確かめます。</li>
<li><b>フェードが階段状かどうかの確認</b>：内観報告のとおりなら、初見データでもフェードの曲線が0%と100%のあいだをほとんど通らないはずです。そうなっていたら <code>fade.gamma</code> を1.0より大きくすることをA2で検討します。</li>
<li><b>ワイプの扱い</b>：RQ2の結果を読むときに「左から見せる方式は左右非対称な字で不利」という交絡を意識しておきます。</li>
<li><b>分析の続き</b>：いまの <code>analyze_transfer.py</code> は素の正答率を数えるところまで。単調回帰・混合モデル・曲線の距離Eは本番データで足します。</li>
<li><b>この2人ぶんの記録をシートから消す</b>：本番の名簿と混ざらないようにします。控えは <code>project/pilot_data/</code> に残してあります。</li>
<li><b>下見だけの仕掛けを本番前に外す</b>：<code>visual.pilot_extra_levels.enabled</code> を false へ。<code>calib_speed_probe</code> のほうは較正フェーズのあいだ入れたままにします。</li>
</ul>

<p class="meta">
元データ: <code>project/pilot_data/pilot_20260821_trials.csv</code>（211行）<br>
分析: <code>experiment/tools/analyze_transfer.py</code> ／ 出力: <code>project/pilot_data/out/</code><br>
本文（Markdown版）: <code>project/パイロット分析_20260821.md</code><br>
このページの生成: <code>project/pilot_data/build_report_html.py</code>（図はbase64で埋め込み・外部参照なし）
</p>

</div>
</body>
</html>
"""


def audio_table():
    # 字 → 20/40/60/80/110/150/220 の正誤（○=正解, ×=誤答）と、全部正解になる時点
    data = [
        ("あ", "○○○○○○○", "20ms〜", True),
        ("が", "○○○○○○○", "20ms〜", True),
        ("か", "×○○○○○○", "40ms〜", False),
        ("し", "×○○○○○○", "40ms〜", False),
        ("ぱ", "×○○○○○○", "40ms〜", False),
        ("ま", "×○○○○○○", "40ms〜", False),
        ("つ", "××○○○○○", "60ms〜", False),
        ("ら", "××××○○○", "110ms〜", True),
    ]
    out = []
    for ch, marks, when, strong in data:
        cells = "".join(
            f'<td class="c"><span class="{"ok" if m == "○" else "ng"}">{m}</span></td>'
            for m in marks)
        w = f"<b>{when}</b>" if strong else when
        out.append(f"<tr><td><b>{ch}</b></td>{cells}<td>{w}</td></tr>")
    return "\n".join(out)


def visual_table():
    data = [
        ("が（フェード）", "○○○○○○○"),
        ("ま（フェード）", "○○○○○○○"),
        ("ぱ（部分表示）", "○○○○○○○"),
        ("ら（部分表示）", "○○○○○○○"),
        ("し（ぼかし）", "○○○○○○○"),
        ("あ（ぼかし）", "×○○○○○○"),
        ("つ（ワイプ）", "××××○○○"),
        ("か（ワイプ）", "××××○×○"),
    ]
    out = []
    for label, marks in data:
        cells = "".join(
            f'<td class="c"><span class="{"ok" if m == "○" else "ng"}">{m}</span></td>'
            for m in marks)
        out.append(f"<tr><td>{label}</td>{cells}</tr>")
    return "\n".join(out)


def main():
    html = HTML.format(
        css=CSS,
        audio_rows=audio_table(),
        visual_rows=visual_table(),
        img_audio=img("curve_audio.png"),
        img_visual=img("curve_visual.png"),
    )
    io.open(OUT, "w", encoding="utf-8").write(html)
    print(f"書き出し: {OUT}  ({len(html.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
