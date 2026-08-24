#!/usr/bin/env python3
"""
キャリアフレーズ4方式を68字ぶん並べて聞き比べるページを作る
============================================================
2026-08-24 作成（4方式版に更新）。

1文字だけを合成すると語末になって母音が伸び、抑揚も付く。そこで**2モーラの
無意味語として合成し、第1モーラだけを切り出す**。そのうしろに足す音をどれにするかを
耳で決めるためのページ。音と数値は experiment/tools/compare_methods.py が作る。

使い方:
  python3 experiment/tools/compare_methods.py        # 先に音と stats.json を作る
  python3 experiment/tools/build_compare_followers.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SND = os.path.join(ROOT, "experiment", "tools", "compare_followers")
OUT = os.path.join(ROOT, "experiment", "tools", "compare_followers.html")

METHODS = [
    ("さ", "sa", "後続さ（かさ）★採用予定"),
    ("ぱ", "pa", "後続ぱ（かぱ）"),
    ("た", "ta", "後続た（かた）"),
    ("あ", "a", "後続あ（かあ）"),
]

SEION = [
    ["わ", "", "", "", ""], ["ら", "り", "る", "れ", "ろ"], ["や", "", "ゆ", "", "よ"],
    ["ま", "み", "む", "め", "も"], ["は", "ひ", "ふ", "へ", "ほ"],
    ["な", "に", "ぬ", "ね", "の"], ["た", "ち", "つ", "て", "と"],
    ["さ", "し", "す", "せ", "そ"], ["か", "き", "く", "け", "こ"],
    ["あ", "い", "う", "え", "お"],
]
DAKUON = [["ば", "び", "ぶ", "べ", "ぼ"], ["だ", "", "", "で", "ど"],
          ["ざ", "じ", "ず", "ぜ", "ぞ"], ["が", "ぎ", "ぐ", "げ", "ご"]]
HANDAKU = [["ぱ", "ぴ", "ぷ", "ぺ", "ぽ"]]
HATSUON = [["ん", "", "", "", ""]]


def cell(kana, S):
    if not kana:
        return '<td class="spacer"></td>'
    btns = []
    for jp, cls, _ in METHODS:
        m = S["methods"][jp]
        it = m["items"][kana]
        fb = "" if it["how"] == "閉鎖" else " fb"
        btns.append(f'<button class="p {cls}{fb}" data-k="{kana}" data-m="{jp}" '
                    f'data-f="{kana}_{jp}.wav" title="{it["how"]}・{it["mora_ms"]:.0f}ms">'
                    f'{jp}</button>')
    mora = S["methods"]["ぱ"]["items"][kana]["mora_ms"]
    return (f'<td><div class="kana">{kana}</div>'
            f'<div class="btns">{"".join(btns)}</div>'
            f'<div class="ms">{mora:.0f}ms</div></td>')


def table(rows, S):
    out = ['<table class="gojuon"><tbody>']
    for dan in range(5):
        out.append("<tr>")
        for gyo in rows:
            out.append(cell(gyo[dan], S))
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def stats_table(S):
    r = ['<table class="stats"><thead><tr><th>方式</th>'
         '<th>境界を機械で<br>検出できた字</th><th>第1モーラの長さ<br>中央（範囲）ms</th>'
         '<th>母音が無声化<br>する字</th><th>末尾に後続の<br>成分が残る疑い</th>'
         '<th>「ぱ」版の長さで<br>代用した字</th></tr></thead><tbody>']
    for jp, cls, label in METHODS:
        m = S["methods"][jp]
        ok = m["found"]
        cl = "good" if ok == m["n"] else ("bad" if ok == 0 else "warn")
        r.append(
            f'<tr><td class="mname">{label}</td>'
            f'<td class="{cl}">{ok} / {m["n"]}</td>'
            f'<td>{m["mora_med"]:.0f}（{m["mora_min"]:.0f}〜{m["mora_max"]:.0f}）</td>'
            f'<td>{len(m["devoiced"])}字<br><span class="sm">{" ".join(m["devoiced"]) or "—"}</span></td>'
            f'<td>{len(m["leak"])}字<br><span class="sm">{" ".join(m["leak"][:14]) or "—"}</span></td>'
            f'<td>{len(m["fallback"])}字</td></tr>')
    r.append("</tbody></table>")
    return "".join(r)


def main():
    S = json.load(open(os.path.join(SND, "stats.json"), encoding="utf-8"))
    body = f"""<!doctype html><meta charset="utf-8">
<title>キャリアフレーズ4方式の聞き比べ</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:14px;background:#faf9f6;
     color:#1b2030;max-width:1240px}}
h1{{font-size:19px;margin:0 0 8px}}
h2{{font-size:15px;margin:22px 0 6px;color:#2E7D8F}}
p.note{{line-height:1.8;font-size:14px;max-width:900px}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:14px;padding:5px 12px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin-right:4px}}
#now{{margin-left:10px;font-weight:700;font-size:16px}}
table.gojuon{{border-collapse:separate;border-spacing:5px}}
table.gojuon td{{border:1px solid #dde1ea;border-radius:8px;background:#fff;padding:5px 5px;
     text-align:center;vertical-align:top;width:104px}}
td.spacer{{visibility:hidden;border:0;background:none}}
.kana{{font-size:21px;font-weight:700;line-height:1.1}}
.btns{{display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-top:4px}}
button.p{{font-size:11.5px;padding:3px 0;border-radius:5px;cursor:pointer;
     border:1px solid #b9c0cf;font-weight:700}}
button.sa{{background:#eef7ef;border-color:#3d7a4a;color:#2b5c36}}
button.pa{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d}}
button.ta{{background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.a{{background:#fdf1ec;border-color:#b5502f;color:#8d3d23}}
button.fb{{border-style:dashed;opacity:.85}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:10px;color:#7a8090;margin-top:3px}}
table.stats{{border-collapse:collapse;font-size:13px;margin:6px 0 4px;background:#fff}}
table.stats th,table.stats td{{border:1px solid #d8dde8;padding:6px 9px;text-align:center;
     vertical-align:top}}
table.stats th{{background:#eef1f6;font-size:12px}}
td.mname{{text-align:left;font-weight:700;white-space:nowrap}}
td.good{{background:#e8f5ea;font-weight:700}}
td.warn{{background:#fdf3e0;font-weight:700}}
td.bad{{background:#fdeaea;font-weight:700}}
.sm{{font-size:11px;color:#666}}
</style>
<h1>キャリアフレーズ4方式の聞き比べ（68字）</h1>
<p class="note">
1文字だけを合成すると語末になって母音が伸び、抑揚も付いてしまいます。そこで
<b>2モーラの無意味語として合成し、第1モーラだけを切り出して</b>刺激にしています。
このページは、<b>うしろに足す音をどれにするか</b>を耳で決めるためのものです。<br>
<b>同じ字の4つのボタンを続けて押して、いちばん自然に聞こえるものを選んでください。</b>
どれも「か」なら「か」とだけ聞こえるのが正しい状態です。<br>
点線のふちのボタンは、<b>境界を機械で決められず「ぱ」版の長さで代用して切った</b>ものです
（下の表の右端の列）。数字は「ぱ」版で測った第1モーラの長さです。
</p>
<h2>機械で測った比較</h2>
{stats_table(S)}
<p class="note" style="font-size:13px">
「境界を機械で検出できた字」… 第1モーラの終わりを機械で決められた字の数。
<b>ぱ・た</b>は母音のあとの無音（唇や舌を閉じる区間）で、<b>さ</b>は高い周波数の雑音が
立ち上がる点で決めています。<b>後続が母音（あ）だと手がかりが無いので0字</b>です。<br>
<b>「さ」版と「ぱ」版のモーラ長は、まったく別の原理で測ったのに中央7msしかずれません</b>
（40ms以上ずれる字は0字）。どちらの切り出しも正しいと考えてよい根拠です。<br>
「末尾に後続の成分が残る疑い」… 末尾に無音が接している、または末尾で急に音量が変わる字。
<b>母音の自然な動きでも引っかかるので、そのまま不合格という意味ではありません</b>。
最終的な合否は耳で判断してください。<br>
「母音が無声化する字」… 「した」「つかう」の母音のように、ささやき声になる字。
日本語として自然な現象で、話速を落としても止まりませんでした。
</p>
<div id="bar">
  <button id="allSa">▶ さを続けて</button>
  <button id="allPa">▶ ぱを続けて</button>
  <button id="allTa">▶ たを続けて</button>
  <button id="allA">▶ あを続けて</button>
  <button id="allBoth">▶ 1字ずつ 4方式を聞き比べ</button>
  <button id="stop">■ 停止</button>
  <span id="now"></span>
</div>
<h2>清音</h2>
{table(SEION, S)}
<h2>濁音</h2>
{table(DAKUON, S)}
<h2>半濁音</h2>
{table(HANDAKU, S)}
<h2>撥音</h2>
{table(HATSUON, S)}
<script>
const DIR="compare_followers/";
let cur=null, timer=null;
function stop(){{ if(cur){{cur.pause();cur=null;}} if(timer){{clearTimeout(timer);timer=null;}}
  document.querySelectorAll("button.playing").forEach(b=>b.classList.remove("playing"));
  document.getElementById("now").textContent=""; }}
function play(btn){{ if(cur){{cur.pause();cur=null;}}
  document.querySelectorAll("button.playing").forEach(b=>b.classList.remove("playing"));
  const a=new Audio(DIR+encodeURIComponent(btn.dataset.f));
  btn.classList.add("playing"); a.onended=()=>btn.classList.remove("playing");
  cur=a; a.play(); return a; }}
document.querySelectorAll("button[data-f]").forEach(b=>b.onclick=()=>{{
  if(timer){{clearTimeout(timer);timer=null;document.getElementById("now").textContent="";}}
  play(b); }});
document.getElementById("stop").onclick=stop;
function runList(list){{ stop(); let i=0;
  (function next(){{ if(i>=list.length){{document.getElementById("now").textContent="おわり";return;}}
    const b=list[i++];
    document.getElementById("now").textContent=b.dataset.k+" ／ "+b.dataset.m+"（"+i+"/"+list.length+"）";
    const a=play(b);
    a.onended=()=>{{b.classList.remove("playing"); timer=setTimeout(next,460);}};
    a.onerror=()=>{{timer=setTimeout(next,120);}};
  }})();
}}
document.getElementById("allSa").onclick=()=>runList([...document.querySelectorAll("button.sa")]);
document.getElementById("allPa").onclick=()=>runList([...document.querySelectorAll("button.pa")]);
document.getElementById("allTa").onclick=()=>runList([...document.querySelectorAll("button.ta")]);
document.getElementById("allA").onclick=()=>runList([...document.querySelectorAll("button.a")]);
document.getElementById("allBoth").onclick=()=>{{
  const out=[]; document.querySelectorAll("td .btns").forEach(g=>{{
    g.querySelectorAll("button").forEach(b=>out.push(b)); }});
  runList(out); }};
</script>
"""
    open(OUT, "w", encoding="utf-8").write(body)
    print(f"  書きました → {OUT}")


if __name__ == "__main__":
    main()
