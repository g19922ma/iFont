#!/usr/bin/env python3
"""
68字を五十音表の並びで聞ける確認ページを作る
============================================
2026-08-24 作成。**耳で合否を決めるためのページ**である。

なぜ要るのか。聴覚刺激は「字＋ん」で合成した音から最初の1モーラだけを切り出して
作っており、この切り出しが 2026-08-23 版・2026-08-24 版とも失敗した
（末尾に《ん》が残り、「か」が「かん」に聞こえる）。機械の検査は2回とも
「鼻音の残りなし」と判定して見逃したので、**最終的な合否は人が聞いて決める**。
そのために、68字を五十音表の並びで、押せばすぐ鳴る形に並べたページを作る。

出力: experiment/tools/check_gojuon_stimuli.html
      音は ../transfer_stimuli_amitaro/ を参照する（埋め込まない。
      GitHub Pages に置けば同じ場所から鳴るし、リポジトリも太らせない）。

使い方:
  python3 experiment/tools/build_check_gojuon.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "experiment", "transfer_config.js")
CROP = os.path.join(ROOT, "experiment", "tts_candidates_carrier2",
                    "cut", "crop_report.json")
OUT = os.path.join(ROOT, "experiment", "tools", "check_gojuon_stimuli.html")
STIM = os.path.join(ROOT, "experiment", "transfer_stimuli_amitaro")

# 五十音表の並び。右の行から左へ並べる（紙の表と同じ向き）ので、
# 表を書くときは列を逆順にする。"" は表の形をそろえるための空きマス。
SEION = [
    ["わ", "", "", "", ""],
    ["ら", "り", "る", "れ", "ろ"],
    ["や", "", "ゆ", "", "よ"],
    ["ま", "み", "む", "め", "も"],
    ["は", "ひ", "ふ", "へ", "ほ"],
    ["な", "に", "ぬ", "ね", "の"],
    ["た", "ち", "つ", "て", "と"],
    ["さ", "し", "す", "せ", "そ"],
    ["か", "き", "く", "け", "こ"],
    ["あ", "い", "う", "え", "お"],
]
DAKUON = [
    ["ば", "び", "ぶ", "べ", "ぼ"],
    ["だ", "", "", "で", "ど"],
    ["ざ", "じ", "ず", "ぜ", "ぞ"],
    ["が", "ぎ", "ぐ", "げ", "ご"],
]
HANDAKU = [["ぱ", "ぴ", "ぷ", "ぺ", "ぽ"]]
HATSUON = [["ん", "", "", "", ""]]


def load_gates():
    """transfer_config.js から、字ごとの打ち切り時点（7点）を読む。"""
    text = open(CFG, encoding="utf-8").read()
    gates = {}
    for m in re.finditer(r'"([ぁ-ん])":\s*\[([0-9,\s]+)\]', text):
        v = [int(s) for s in m.group(2).split(",") if s.strip()]
        if len(v) == 7:
            gates[m.group(1)] = v
    return gates


def cell(kana, gates, crop):
    if not kana:
        return '<td class="spacer"></td>'
    g = gates.get(kana)
    if not g:
        return f'<td class="miss">{kana}<br>設定なし</td>'
    longest = g[-1]
    c = crop.get(kana, {})
    mora = c.get("mora_ms")
    depth = c.get("closure_depth_db")
    sub = ""
    if mora is not None:
        sub = (f'<div class="ms">モーラ {mora:.0f}ms'
               + (f'<br>閉鎖の深さ {depth:.0f}dB' if depth else '') + '</div>')
    return (
        f'<td>'
        f'<div class="kana">{kana}</div>'
        f'<button class="p long" data-k="{kana}" data-f="{kana}_g{longest:04d}.wav">'
        f'▶ 最長 {longest}ms</button>'
        f'<button class="p full" data-k="{kana}" data-f="{kana}_full.wav">▶ 全長</button>'
        f'{sub}</td>'
    )


def table(rows, gates, crop, cls=""):
    out = [f'<table class="gojuon {cls}"><tbody>']
    # 段（あ・い・う・え・お）を行に、行（あ行・か行…）を列にする。
    for dan in range(5):
        out.append("<tr>")
        for gyo in rows:
            out.append(cell(gyo[dan], gates, crop))
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def main():
    gates = load_gates()
    crop = json.load(open(CROP, encoding="utf-8"))["items"] if os.path.exists(CROP) else {}
    missing = [k for k in gates if not os.path.exists(os.path.join(STIM, f"{k}_full.wav"))]
    if missing:
        print(f"  ⚠ 音のファイルが無い字: {' '.join(missing)}", file=sys.stderr)

    body = f"""<!doctype html><meta charset="utf-8">
<title>あみたろ 68字 聞き取り確認（五十音表）</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:14px;background:#faf9f6;
     color:#1b2030;max-width:1200px}}
h1{{font-size:19px;margin:0 0 8px}}
h2{{font-size:15px;margin:22px 0 6px;color:#2E7D8F}}
p.note{{line-height:1.8;font-size:14px;max-width:820px}}
b.warn{{color:#b3261e}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:14px;padding:5px 12px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin-right:4px}}
#now{{margin-left:10px;font-weight:700;font-size:16px}}
table.gojuon{{border-collapse:separate;border-spacing:5px}}
table.gojuon td{{border:1px solid #dde1ea;border-radius:8px;background:#fff;padding:5px 6px;
     text-align:center;vertical-align:top;width:96px}}
td.spacer{{visibility:hidden;border:0;background:none}}
td.miss{{background:#fde;color:#a00;font-size:12px}}
.kana{{font-size:23px;font-weight:700;line-height:1.15}}
button.p{{display:block;width:100%;margin:3px 0 0;font-size:11.5px;padding:3px 2px;
     border-radius:5px;cursor:pointer;border:1px solid #b9c0cf;background:#f6f8fc}}
button.long{{border-color:#2E7D8F;color:#1f5f6d;font-weight:700}}
button.full{{color:#555}}
button.playing{{background:#2E7D8F!important;color:#fff!important;border-color:#2E7D8F!important}}
.ms{{font-size:10px;color:#7a8090;margin-top:3px;line-height:1.3}}
</style>
<h1>あみたろ 68字：耳で確かめる（五十音表）</h1>
<p class="note">
<b>2026-08-24 に作り直した版です。</b>「字＋ん」で合成して《ん》を切り落とす作り方をやめ、
<b>「字＋ぱ」で合成して、母音のあとに来る閉鎖（唇を閉じて音が消える区間）の手前で切る</b>
作り方に変えました。閉鎖はただの無音なので、母音の種類によらず同じ物差しで切れます。<br>
<b>「最長」を上から順に聞いてください。</b>「最長」は、参加者が実際に聞く中でいちばん長い刺激です。
正しい状態は、たとえば「か」なら<b>「か」</b>とだけ聞こえること。
<b class="warn">「かん」「かぱ」のように余分な音が付いて聞こえたら不合格</b>です。
「全長」は打ち切る前のモーラ全体です。<br>
機械の検査は前の版で「ん」の残りを2回見逃しています。<b>合否はこのページを聞いて決めてください。</b><br>
<b>なお「し」「す」「ち」「つ」の4字は母音が無声化して、ささやくように聞こえます。</b>
これは「した」「つかう」の母音が実際に無声化するのと同じ、日本語として自然な現象です
（この4字だけ後続音の影響で必ずこうなり、話速を落としても止められませんでした）。
不具合ではありませんが、<b>刺激として許容できるかはご判断ください</b>。
</p>
<div id="bar">
  <button id="allLong">▶ 68字の「最長」を続けて再生</button>
  <button id="allFull">▶ 68字の「全長」を続けて再生</button>
  <button id="stop">■ 停止</button>
  <span id="now"></span>
</div>
<h2>清音</h2>
{table(SEION, gates, crop)}
<h2>濁音</h2>
{table(DAKUON, gates, crop)}
<h2>半濁音</h2>
{table(HANDAKU, gates, crop)}
<h2>撥音</h2>
{table(HATSUON, gates, crop)}
<script>
const DIR="../transfer_stimuli_amitaro/";
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
  play(b);
}});
document.getElementById("stop").onclick=stop;
function runAll(sel){{ stop();
  const list=[...document.querySelectorAll(sel)]; let i=0;
  (function next(){{ if(i>=list.length){{ document.getElementById("now").textContent="おわり"; return; }}
    const b=list[i++];
    document.getElementById("now").textContent=b.dataset.k+" （"+i+"/"+list.length+"）";
    const a=play(b);
    a.onended=()=>{{ b.classList.remove("playing"); timer=setTimeout(next,520); }};
    a.onerror=()=>{{ timer=setTimeout(next,120); }};
  }})();
}}
document.getElementById("allLong").onclick=()=>runAll("button.long");
document.getElementById("allFull").onclick=()=>runAll("button.full");
</script>
"""
    open(OUT, "w", encoding="utf-8").write(body)
    print(f"  {len(gates)} 字ぶんを書きました → {OUT}")


if __name__ == "__main__":
    main()
