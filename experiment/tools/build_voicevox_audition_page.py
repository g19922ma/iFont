#!/usr/bin/env python3
"""
話者の聴き比べページを作る
==========================
`build_voicevox_stimuli.py` が出した音と測定値から、
行=かな × 列=話者 の表を作り、どのセルも押せば鳴るページにする。

  python3 experiment/tools/build_voicevox_audition_page.py

出力: experiment/voicevox_audition.html
"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
DIR = os.path.join(EXP, "voicevox_audition")
OUT = os.path.join(EXP, "voicevox_audition.html")

# 清濁の対。左右で聞き比べると違いが分かりやすいので、対にして上へ置く。
PAIRS = [("ぱ", "ば"), ("か", "が"), ("た", "だ"), ("さ", "ざ"), ("は", "ば")]
# 以前つまずいた字。必ず確かめる。
WATCH = ["ぽ", "ぴ", "ぷ"]

CSS = """
:root{--bg:#fbfbfa;--fg:#22252b;--muted:#61666f;--line:#e2e3e6;--card:#fff;
      --accent:#2E7D8F;--accent2:#1E2A5E;--chip:#eef2f4;--warn:#fff6e8;--warnl:#e6c98f;
      --warnf:#6b4a10;--hit:#dff0e6;}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#15171b;--fg:#e6e8ec;--muted:#a2a8b3;--line:#2c3037;--card:#1c1f25;
  --accent:#63b6c7;--accent2:#9fb0e8;--chip:#252a31;--warn:#2c2413;--warnl:#6b5622;
  --warnf:#f0d9a8;--hit:#1e3527;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:"Hiragino Sans","Yu Gothic","Noto Sans JP",system-ui,sans-serif;
  font-size:15px;line-height:1.8}
.wrap{max-width:900px;margin:0 auto;padding:34px 18px 90px}
h1{font-size:23px;margin:0 0 6px}
h2{font-size:17px;margin:38px 0 10px;padding-bottom:7px;border-bottom:2px solid var(--line)}
p{margin:0 0 12px}
.sub{color:var(--muted);font-size:13.5px;margin:0 0 3px}
.warn{background:var(--warn);border:1px solid var(--warnl);color:var(--warnf);
  border-radius:10px;padding:15px 18px;margin:20px 0}
.warn b{color:inherit}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card);margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:center;white-space:nowrap}
thead th{background:var(--chip);font-size:13px;position:sticky;top:0}
th.k,td.k{text-align:left;font-size:17px;font-weight:700;position:sticky;left:0;
  background:var(--card);border-right:1px solid var(--line);min-width:74px}
thead th.k{background:var(--chip);z-index:2}
tbody tr:last-child td{border-bottom:0}
button.p{font-size:14px;padding:5px 13px;border-radius:999px;border:1px solid var(--accent);
  background:transparent;color:var(--accent);cursor:pointer;min-width:56px}
button.p:hover{background:var(--chip)}
button.p.on{background:var(--accent);color:#fff}
button.p.done{background:var(--hit)}
.lag{display:block;font-size:11px;color:var(--muted);margin-top:2px}
.rowbtn{font-size:12.5px;padding:4px 10px;border-radius:6px;border:1px solid var(--line);
  background:transparent;color:var(--muted);cursor:pointer}
.note{background:var(--card);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
  padding:11px 15px;margin:14px 0;font-size:14.5px}
.credit{font-size:13px;color:var(--muted);border-top:1px solid var(--line);
  margin-top:34px;padding-top:14px}
code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12.5px}
"""


def main():
    meta = json.load(io.open(os.path.join(DIR, "speakers.json"), encoding="utf-8"))
    spk = meta["speakers"]
    kana = meta["kana"]
    lags = {}
    for s in spk:
        o = json.load(io.open(os.path.join(DIR, f"onsets_{s['id']}.json"), encoding="utf-8"))
        lags[s["id"]] = o["kana"]

    def cell(sid, ch):
        v = lags[sid].get(ch, {}).get("voice_lag_ms")
        lag = "" if v is None else f'<span class="lag">{v:g}ms</span>'
        return (f'<td><button class="p" data-s="{sid}" data-k="{ch}">▶</button>{lag}</td>')

    def row(ch, label=None):
        cells = "".join(cell(s["id"], ch) for s in spk)
        return (f'<tr><th class="k">{label or ch}'
                f'<br><button class="rowbtn" data-row="{ch}">続けて</button></th>{cells}</tr>')

    head = '<tr><th class="k">かな</th>' + "".join(
        f'<th>{s["name"]}<br><span class="lag">{s["style"]}・ID{s["id"]}</span></th>' for s in spk) + "</tr>"

    focus_rows = []
    for a, b in PAIRS:
        focus_rows.append(row(a))
        focus_rows.append(row(b))
    for ch in WATCH:
        focus_rows.append(row(ch, ch + "（要注意）"))
    rest = [row(ch) for ch in kana]

    credits = "\n".join(
        f'<li><b>{s["name"]}</b>（{s["style"]}）… クレジット表記: <code>VOICEVOX:{s["name"]}</code></li>'
        for s in spk)

    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>合成音の聴き比べ（話者選び）</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<h1>合成音の聴き比べ（話者選び）</h1>
<p class="sub">転写検証実験の刺激を、自然音声から VOICEVOX の合成音に切り替えるための確認ページ</p>
<p class="sub">全68かな × 4話者。すべて<b>無加工</b>（既定のまま合成し、音量だけそろえた）</p>

<div class="warn">
<p style="margin:0 0 8px"><b>ここで見てほしいこと</b></p>
<p style="margin:0">それぞれの字が<b>意図した字に聞こえるか</b>。とくに次の2点です。</p>
<ul style="margin:8px 0 0">
<li><b>清濁が区別できるか</b>（ぱ／ば・か／が・た／だ・さ／ざ）。上下に並べてあるので、続けて聞き比べてください。</li>
<li><b>ぽ・ぴ・ぷ が濁って聞こえないか</b>。以前の刺激づくりで「ぽ」が濁って聞こえる不具合が出た字です。</li>
</ul>
<p style="margin:8px 0 0">1話者を選んでいただければ、その声で全68字の本刺激を作ります。</p>
</div>

<div class="note">
<p style="margin:0">各ボタンの下の数字は<b>「音が始まってから声が出るまで」</b>の自動測定値です。
無声の破裂（か・ぱ・た）は息が先に出るので大きめ、有声（が・だ・ば）は0に近いのが理屈ですが、
<b>この測定は粗いので目安にとどめてください</b>。判断は耳が主で、数字は補助です。</p>
</div>

<h2>清濁の対と、要注意の字</h2>
<div class="scroll"><table><thead>{head}</thead><tbody>
{chr(10).join(focus_rows)}
</tbody></table></div>

<h2>全68字</h2>
<div class="scroll"><table><thead>{head}</thead><tbody>
{chr(10).join(rest)}
</tbody></table></div>

<div class="credit">
<p><b>ライセンス表記</b>（採用した話者のものを実験ページと論文に入れます）</p>
<ul>
{credits}
</ul>
<p>音声合成に <b>VOICEVOX</b>（<code>https://voicevox.hiroshiba.jp/</code>）を使用。
各キャラクターの利用規約に従い、上記のクレジットを表示します。</p>
<p>生成: <code>experiment/tools/build_voicevox_stimuli.py</code> →
<code>experiment/tools/build_voicevox_audition_page.py</code></p>
</div>

</div>
<script>
const A = new Audio();
let cur = null;
function play(btn) {{
  const s = btn.dataset.s, k = btn.dataset.k;
  if (cur) cur.classList.remove("on");
  btn.classList.add("on"); cur = btn;
  A.src = "voicevox_audition/" + s + "/" + encodeURIComponent(k) + ".wav";
  A.play();
  A.onended = () => {{ btn.classList.remove("on"); btn.classList.add("done"); }};
}}
document.addEventListener("click", (e) => {{
  const b = e.target.closest("button.p");
  if (b) {{ play(b); return; }}
  const r = e.target.closest("button.rowbtn");
  if (!r) return;
  // その行を左から順に鳴らす（話者ごとの違いを続けて聞くため）
  const cells = [...r.closest("tr").querySelectorAll("button.p")];
  let i = 0;
  const next = () => {{
    if (i >= cells.length) return;
    const b2 = cells[i++];
    b2.classList.add("on");
    A.src = "voicevox_audition/" + b2.dataset.s + "/" + encodeURIComponent(b2.dataset.k) + ".wav";
    A.play();
    A.onended = () => {{ b2.classList.remove("on"); b2.classList.add("done"); setTimeout(next, 260); }};
  }};
  next();
}});
</script>
</body>
</html>
"""
    io.open(OUT, "w", encoding="utf-8").write(html)
    print(f"書き出し: {OUT}  ({len(html.encode('utf-8')) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
