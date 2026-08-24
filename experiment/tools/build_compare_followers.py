#!/usr/bin/env python3
"""
後続音「ぱ」版と「あ」版を、68字ぶん並べて聞き比べるページを作る
================================================================
2026-08-24 作成。

キャリアフレーズ（対象の字のうしろに1モーラ足して読ませる作り方）の
**後続音をどれにするか**を、耳で決めるためのページ。

  「ぱ」版 … 後続が無声破裂音。母音のあとに**閉鎖区間**（唇を閉じてほぼ無音に
             なる区間）が来るので、切る位置が音量の落ち込みだけで決まる。
             68字すべてで閉鎖を検出できた（音量が29〜46dB落ちる）。
  「あ」版 … 後続が母音。**閉鎖が無い**ので、音量では境目が決まらない。
             音色の変化で探すと変化量は 8.5〜33.1（中央14.2）と一応あるが、
             「ぱ」版のモーラ長と 45〜125ms もずれる。とくにア段は
             「かあ」が長い「あ」1つになってしまうため、ずれが125msと最大になる。
             そこでこのページの「あ」版は、**同じ話者・同じ話速・同じアクセントで
             作った「ぱ」版のモーラ長で切ってある**（機械では境目が決まらないため）。

出力: experiment/tools/compare_followers.html
      音は experiment/tools/compare_followers/<かな>_pa.wav / _a.wav

使い方:
  python3 experiment/tools/build_compare_followers.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SND = os.path.join(ROOT, "experiment", "tools", "compare_followers")
OUT = os.path.join(ROOT, "experiment", "tools", "compare_followers.html")

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
DEVOICED = set("しすちつ")


def cell(kana, L):
    if not kana:
        return '<td class="spacer"></td>'
    v = L.get(kana, {})
    warn = ' <span class="dv" title="母音が無声化してささやくように聞こえます">◇</span>' if kana in DEVOICED else ""
    return (f'<td><div class="kana">{kana}{warn}</div>'
            f'<button class="p pa" data-k="{kana}" data-f="{kana}_pa.wav">▶ ぱ版</button>'
            f'<button class="p a" data-k="{kana}" data-f="{kana}_a.wav">▶ あ版</button>'
            f'<div class="ms">{v.get("pa", "?")}ms</div></td>')


def table(rows, L):
    out = ['<table class="gojuon"><tbody>']
    for dan in range(5):
        out.append("<tr>")
        for gyo in rows:
            out.append(cell(gyo[dan], L))
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def main():
    L = json.load(open(os.path.join(SND, "lengths.json"), encoding="utf-8"))
    body = f"""<!doctype html><meta charset="utf-8">
<title>後続音の聞き比べ（ぱ版 / あ版）</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:14px;background:#faf9f6;
     color:#1b2030;max-width:1200px}}
h1{{font-size:19px;margin:0 0 8px}}
h2{{font-size:15px;margin:22px 0 6px;color:#2E7D8F}}
p.note{{line-height:1.8;font-size:14px;max-width:860px}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:14px;padding:5px 12px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin-right:4px}}
#now{{margin-left:10px;font-weight:700;font-size:16px}}
table.gojuon{{border-collapse:separate;border-spacing:5px}}
table.gojuon td{{border:1px solid #dde1ea;border-radius:8px;background:#fff;padding:5px 6px;
     text-align:center;vertical-align:top;width:92px}}
td.spacer{{visibility:hidden;border:0;background:none}}
.kana{{font-size:22px;font-weight:700;line-height:1.15}}
.dv{{font-size:12px;color:#b3261e;vertical-align:super}}
button.p{{display:block;width:100%;margin:3px 0 0;font-size:11.5px;padding:3px 2px;
     border-radius:5px;cursor:pointer;border:1px solid #b9c0cf}}
button.pa{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d;font-weight:700}}
button.a{{background:#fdf1ec;border-color:#b5502f;color:#8d3d23;font-weight:700}}
button.playing{{background:#2E7D8F!important;color:#fff!important;border-color:#2E7D8F!important}}
.ms{{font-size:10px;color:#7a8090;margin-top:3px}}
</style>
<h1>後続音の聞き比べ：「ぱ」版 と「あ」版</h1>
<p class="note">
刺激は、対象の字のうしろに1モーラ足して読ませ、対象の字だけを切り出して作っています
（そうしないと語末になって母音が伸び、抑揚も付くため）。その<b>うしろに足す音をどれにするか</b>を
耳で決めるためのページです。<b>同じ字の「ぱ版」と「あ版」を続けて押して比べてください。</b><br>
<b>「ぱ版」</b>＝ うしろに「ぱ」を足した（例:「かぱ」）。母音のあとに唇を閉じる無音区間が来るので、
そこで切っています。<br>
<b>「あ版」</b>＝ うしろに「あ」を足した（例:「かあ」）。<b>母音なので無音区間ができず、
機械では境目が決まりません。</b>そのため「ぱ版」と同じ長さで切ってあります
（とくに「か」「さ」などア段は「かあ」が長い「あ」1つになってしまいます）。<br>
数字はその字の長さ（ミリ秒）。<span class="dv">◇</span> の4字（し・す・ち・つ）は母音が無声化して
ささやくように聞こえます。日本語として自然な現象で、話速を落としても止まりませんでした。
</p>
<div id="bar">
  <button id="allPa">▶ 68字の「ぱ版」を続けて</button>
  <button id="allA">▶ 68字の「あ版」を続けて</button>
  <button id="allBoth">▶ 1字ずつ ぱ→あ で聞き比べ</button>
  <button id="stop">■ 停止</button>
  <span id="now"></span>
</div>
<h2>清音</h2>
{table(SEION, L)}
<h2>濁音</h2>
{table(DAKUON, L)}
<h2>半濁音</h2>
{table(HANDAKU, L)}
<h2>撥音</h2>
{table(HATSUON, L)}
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
function runList(list,label){{ stop(); let i=0;
  (function next(){{ if(i>=list.length){{document.getElementById("now").textContent="おわり";return;}}
    const b=list[i++];
    document.getElementById("now").textContent=b.dataset.k+" "+label(b)+" （"+i+"/"+list.length+"）";
    const a=play(b);
    a.onended=()=>{{b.classList.remove("playing"); timer=setTimeout(next,480);}};
    a.onerror=()=>{{timer=setTimeout(next,120);}};
  }})();
}}
document.getElementById("allPa").onclick=()=>runList([...document.querySelectorAll("button.pa")],()=>"ぱ版");
document.getElementById("allA").onclick=()=>runList([...document.querySelectorAll("button.a")],()=>"あ版");
document.getElementById("allBoth").onclick=()=>{{
  const out=[]; document.querySelectorAll("td").forEach(td=>{{
    const p=td.querySelector("button.pa"), a=td.querySelector("button.a");
    if(p&&a){{out.push(p);out.push(a);}} }});
  runList(out,b=>b.classList.contains("pa")?"ぱ版":"あ版");
}};
</script>
"""
    open(OUT, "w", encoding="utf-8").write(body)
    print(f"  書きました → {OUT}")


if __name__ == "__main__":
    main()
