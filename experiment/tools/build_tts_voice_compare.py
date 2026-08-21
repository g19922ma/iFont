#!/usr/bin/env python3
"""
話者の聴き比べページを作る
==========================
`build_tts_candidates.py` が出した音と測定値から、
行=かな × 列=話者 の表を作り、どのセルも押せば鳴るページにする。

音は**ページの中に埋め込む**。刺激の wav 本体は候補が4話者ぶんあって重く、
リポジトリに入れない約束なので、そのままではページを共有しても鳴らない。
そこで再生用にだけ MP3(128kbps・モノラル)へ変換して埋め込み、1ファイルで完結させる。
判断のもとになる音そのものは `experiment/tts_candidates/` の wav であり、
ローカルで開いたときは埋め込みが読めなくてもそちらへ自動で切り替わる。

  python3 experiment/tools/build_tts_voice_compare.py

出力: experiment/tools/tts_voice_compare.html
"""
import base64
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
DIR = os.path.join(EXP, "tts_candidates")
OUT = os.path.join(HERE, "tts_voice_compare.html")

CSS = """
:root{--bg:#fbfbfa;--fg:#22252b;--muted:#61666f;--line:#e2e3e6;--card:#fff;
      --accent:#2E7D8F;--ink:#1E2A5E;--chip:#eef2f4;--warn:#fff6e8;--warnl:#e6c98f;
      --warnf:#6b4a10;--ok:#1f6b45;--ng:#a3402f;--play:#2E7D8F;--done:#dff0e6;}
:root:not([data-theme=light]){}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#15171b;--fg:#e6e8ec;--muted:#a2a8b3;--line:#2c3037;--card:#1c1f25;
  --accent:#63b6c7;--ink:#9fb0e8;--chip:#252a31;--warn:#2c2413;--warnl:#6b5622;
  --warnf:#f0d9a8;--ok:#7fd0a5;--ng:#f0a08e;--play:#63b6c7;--done:#1e3527;}}
:root[data-theme=dark]{
  --bg:#15171b;--fg:#e6e8ec;--muted:#a2a8b3;--line:#2c3037;--card:#1c1f25;
  --accent:#63b6c7;--ink:#9fb0e8;--chip:#252a31;--warn:#2c2413;--warnl:#6b5622;
  --warnf:#f0d9a8;--ok:#7fd0a5;--ng:#f0a08e;--play:#63b6c7;--done:#1e3527;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:"Hiragino Sans","Yu Gothic","Noto Sans JP",system-ui,sans-serif;
  font-size:15px;line-height:1.8;-webkit-text-size-adjust:100%}
.wrap{max-width:1040px;margin:0 auto;padding:34px 18px 120px}
h1{font-size:23px;margin:0 0 6px;letter-spacing:.01em}
h2{font-size:17px;margin:40px 0 8px;padding-bottom:7px;border-bottom:2px solid var(--line)}
p{margin:0 0 12px}
.sub{color:var(--muted);font-size:13.5px;margin:0 0 3px}
.warn{background:var(--warn);border:1px solid var(--warnl);color:var(--warnf);
  border-radius:10px;padding:15px 18px;margin:22px 0}
.note{background:var(--card);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
  padding:11px 15px;margin:14px 0;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px;margin:18px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:13px 15px}
.card h3{margin:0;font-size:16px}
.card .meta{color:var(--muted);font-size:12.5px;margin:1px 0 9px}
.card .score{font-size:13px;margin:0 0 10px}
.card .score b{font-size:16px;color:var(--ink)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card);margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:center;white-space:nowrap}
thead th{background:var(--chip);font-size:13px;position:sticky;top:0;z-index:1}
th.k,td.k{text-align:left;font-size:16px;font-weight:700;position:sticky;left:0;
  background:var(--card);border-right:1px solid var(--line);min-width:80px}
thead th.k{background:var(--chip);z-index:3}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:color-mix(in srgb,var(--chip) 55%,transparent)}
button{font-family:inherit}
.p{font-size:14px;padding:4px 11px;border-radius:999px;border:1px solid var(--accent);
  background:transparent;color:var(--accent);cursor:pointer;min-width:52px}
.p:hover{background:var(--chip)}
.p.on{background:var(--play);color:#fff;border-color:var(--play)}
.p.done{background:var(--done)}
.v{font-size:11.5px;color:var(--muted);margin-left:4px;font-variant-numeric:tabular-nums}
.pairbox{display:flex;gap:6px;align-items:center;justify-content:center}
.d{display:block;font-size:11.5px;margin-top:1px;font-variant-numeric:tabular-nums}
.d.good{color:var(--ok)} .d.bad{color:var(--ng)}
.mini{font-size:12.5px;padding:3px 9px;border-radius:6px;border:1px solid var(--line);
  background:transparent;color:var(--muted);cursor:pointer}
.mini:hover{border-color:var(--accent);color:var(--accent)}
.run{font-size:13px;padding:5px 12px;border-radius:7px;border:1px solid var(--accent);
  background:transparent;color:var(--accent);cursor:pointer;width:100%}
.run:hover{background:var(--chip)}
.run.on{background:var(--play);color:#fff}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);
  padding:9px 18px;display:flex;gap:14px;align-items:center;font-size:13.5px;
  box-shadow:0 -2px 14px rgba(0,0,0,.06)}
.bar .now{font-weight:700;font-size:17px;min-width:2.2em}
.bar .who{color:var(--muted)}
.bar .sp{flex:1}
.stop{font-size:13px;padding:5px 14px;border-radius:7px;border:1px solid var(--ng);
  background:transparent;color:var(--ng);cursor:pointer}
.credit{font-size:13px;color:var(--muted);border-top:1px solid var(--line);
  margin-top:36px;padding-top:14px}
.credit li{margin-bottom:9px}
code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12.5px}
"""


def enc(path, tmp):
    """再生用の MP3(128kbps・モノラル)へ変換して base64 で返す。"""
    dst = os.path.join(tmp, "a.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                    "-c:a", "libmp3lame", "-b:a", "128k", "-ac", "1", dst], check=True)
    with open(dst, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    M = json.load(io.open(os.path.join(DIR, "measurements.json"), encoding="utf-8"))
    spk = [M["speakers"][k] for k in M["speakers"]]
    spk.sort(key=lambda s: [x["id"] for x in M["speakers"].values()].index(s["id"]))
    kana, meas = M["kana"], M["measurements"]
    pairs = [tuple(p) for p in M["pairs"]]
    watch = M["watch"]

    if not os.path.isdir(DIR):
        raise SystemExit("先に build_tts_candidates.py を走らせてください")

    # ---- 音を埋め込む -------------------------------------------------------
    audio = {}
    with tempfile.TemporaryDirectory() as tmp:
        for s in spk:
            for ch in kana:
                p = os.path.join(DIR, s["dir"], ch + ".wav")
                if os.path.exists(p):
                    audio[f'{s["id"]}|{ch}'] = enc(p, tmp)
            print(f"  埋め込み {s['name']}: {len(kana)}字", flush=True)

    def vot(sid_name, ch):
        return meas[sid_name].get(ch, {}).get("vot_ms")

    # ---- 話者ごとの「清濁の手がかりの強さ」 ---------------------------------
    # 13組の清濁の対それぞれで「無声のVOT − 有声のVOT」を出し、その中央値を代表値にする。
    # 大きいほど、破裂から声までの間の長さで清濁を区別できるということ。
    ALLPAIRS = [("か", "が"), ("き", "ぎ"), ("く", "ぐ"), ("け", "げ"), ("こ", "ご"),
                ("た", "だ"), ("て", "で"), ("と", "ど"),
                ("ぱ", "ば"), ("ぴ", "び"), ("ぷ", "ぶ"), ("ぺ", "べ"), ("ぽ", "ぼ")]

    def contrast(name):
        ds = [vot(name, a) - vot(name, b) for a, b in ALLPAIRS
              if vot(name, a) is not None and vot(name, b) is not None]
        if not ds:
            return None, 0, 0
        ds.sort()
        med = ds[len(ds) // 2] if len(ds) % 2 else (ds[len(ds) // 2 - 1] + ds[len(ds) // 2]) / 2
        weak = sum(1 for d in ds if d < 5)
        return med, weak, len(ds)

    cards = []
    for s in spk:
        med, weak, n = contrast(s["name"])
        cards.append(f"""<div class="card">
<h3>{s['name']}</h3>
<p class="meta">{s['style']}・ID{s['id']}・<code>{s['credit']}</code></p>
<p class="score">清濁の間の差（13組の中央値）: <b>{'—' if med is None else f'{med:+.0f}ms'}</b><br>
<span style="color:var(--muted);font-size:12.5px">差が5ms未満の組: {weak}／{n}</span></p>
<button class="run" data-all="{s['id']}">この話者で全68字を通して聴く</button>
</div>""")

    head = ('<tr><th class="k">かな</th>' + "".join(
        f'<th>{s["name"]}<span class="v">ID{s["id"]}</span></th>' for s in spk) + "</tr>")

    def btn(s, ch, label=None):
        v = vot(s["name"], ch)
        tag = "" if v is None else f'<span class="v">{v:+.0f}</span>'
        return (f'<button class="p" data-s="{s["id"]}" data-k="{ch}">'
                f'{label or ch}</button>{tag}')

    # 清濁の対: 1つのセルに清と濁を並べ、下に差を出す。左右で続けて聞き比べられる。
    pair_rows = []
    for a, b in pairs:
        tds = []
        for s in spk:
            va, vb = vot(s["name"], a), vot(s["name"], b)
            d = "" if va is None or vb is None else (
                f'<span class="d {"good" if va - vb >= 5 else "bad"}">'
                f'差 {va - vb:+.0f}ms</span>')
            tds.append(f'<td><div class="pairbox">{btn(s, a)}{btn(s, b)}</div>{d}</td>')
        pair_rows.append(
            f'<tr><th class="k">{a}／{b}<br>'
            f'<button class="mini" data-seq="{a},{b}">続けて</button></th>' + "".join(tds) + "</tr>")

    watch_rows = []
    for ch in watch:
        tds = "".join(f'<td>{btn(s, ch)}</td>' for s in spk)
        watch_rows.append(f'<tr><th class="k">{ch}<span class="v">要注意</span><br>'
                          f'<button class="mini" data-row="{ch}">横に聴く</button></th>{tds}</tr>')

    all_rows = []
    for ch in kana:
        tds = "".join(f'<td>{btn(s, ch)}</td>' for s in spk)
        all_rows.append(f'<tr><th class="k">{ch}<br>'
                        f'<button class="mini" data-row="{ch}">横に聴く</button></th>{tds}</tr>')

    credits = "\n".join(
        '<li><b>{n}</b>（{st}）… クレジット表記: <code>{c}</code><br>'
        '<span style="font-size:12.5px">{p}</span></li>'.format(
            n=s["name"], st=s["style"], c=s["credit"],
            p=s.get("policy", "").replace("\n", "<br>"))
        for s in spk)

    names_js = json.dumps({str(s["id"]): s["name"] for s in spk}, ensure_ascii=False)
    dirs_js = json.dumps({str(s["id"]): s["dir"] for s in spk}, ensure_ascii=False)
    kana_js = json.dumps(kana, ensure_ascii=False)
    audio_js = json.dumps(audio)

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
<p class="sub">全68かな（を・ぢ・づ・ゔ を除く）× {len(spk)}話者。すべて<b>無加工</b>
——VOICEVOX に1字だけ渡し、返ってきた設定を1つも書き換えずに合成しました。
話速・音の高さ・抑揚・前後の間はすべて既定値のままです。そろえたのは音量だけで、
1音まるごとに一定の倍率を掛けています。</p>

<div class="warn">
<p style="margin:0 0 8px"><b>選ぶときに見てほしいこと</b></p>
<ol style="margin:0;padding-left:1.3em">
<li><b>その字に聞こえるか</b>。68字すべてで、意図した字として聞き取れること。</li>
<li><b>清濁が区別できるか</b>（か／が・た／だ・ぱ／ば など）。ここがいちばん重要です。</li>
<li><b>ぽ・ぴ・ぷ が濁って聞こえないか</b>。以前の刺激づくりで「ぽ」が濁って聞こえる
不具合を出した字です（<code>project/清濁診断_音響測定.md</code>）。</li>
</ol>
<p style="margin:8px 0 0">1話者を選んでいただければ、その声で本刺激を組み込みます。</p>
</div>

<h2>話者の候補</h2>
<div class="cards">
{chr(10).join(cards)}
</div>
<div class="note">
<p style="margin:0"><b>「清濁の間の差」とは</b>：清音（か・た・ぱ など）と濁音（が・だ・ば など）を
13組そろえ、それぞれで「破裂してから声が出るまでの時間」の差を機械で測り、その中央値を出したものです。
プラスが大きいほど、清音のほうが声の出だしが遅く、清濁を時間で区別できるという意味になります。
差が 0ms 前後だと、この手がかりでは清濁を区別できません（別の手がかり——声の高さの出だしや
破裂の強さ——に頼ることになります）。<b>あくまで目安で、決めるのは耳です。</b></p>
</div>

<h2>清濁の対で聴く</h2>
<p class="sub">セルの左が清音、右が濁音。「続けて」を押すと、左の話者から順に 清→濁 と鳴ります。</p>
<div class="scroll"><table><thead>{head}</thead><tbody>
{chr(10).join(pair_rows)}
</tbody></table></div>

<h2>要注意の字</h2>
<div class="scroll"><table><thead>{head}</thead><tbody>
{chr(10).join(watch_rows)}
</tbody></table></div>

<h2>全68字</h2>
<p class="sub">ボタンの横の数字は、破裂で始まる字だけに出る「破裂してから声が出るまで」の
実測値（ミリ秒）です。マイナスは破裂より前に声が始まっていることを表します。</p>
<div class="scroll"><table><thead>{head}</thead><tbody>
{chr(10).join(all_rows)}
</tbody></table></div>

<div class="credit">
<p><b>ライセンス表記</b>（採用した話者のものを実験ページと論文に入れます）</p>
<ul>
{credits}
</ul>
<p>音声合成に <b>VOICEVOX</b>（<code>https://voicevox.hiroshiba.jp/</code>）を使用。</p>
<p>生成: <code>experiment/tools/build_tts_candidates.py</code> →
<code>experiment/tools/build_tts_voice_compare.py</code>。
まとめ: <code>project/合成音声_話者候補.md</code>。
音の実体は <code>experiment/tts_candidates/&lt;話者名&gt;/&lt;かな&gt;.wav</code>
（リポジトリには入れていません。このページには再生用の MP3 を埋め込んであります）。</p>
</div>

</div>

<div class="bar">
  <span class="now" id="bnow">—</span>
  <span class="who" id="bwho">再生していません</span>
  <span class="sp"></span>
  <button class="stop" id="bstop">止める</button>
</div>

<script>
const NAMES = {names_js};
const DIRS  = {dirs_js};
const KANA  = {kana_js};
const AUD   = {audio_js};

const A = new Audio();
let queue = [], qi = 0, marks = [];
const bnow = document.getElementById("bnow"), bwho = document.getElementById("bwho");

function src(sid, k) {{
  const b = AUD[sid + "|" + k];
  return b ? "data:audio/mpeg;base64," + b
           : "../tts_candidates/" + encodeURIComponent(DIRS[sid]) + "/" + encodeURIComponent(k) + ".wav";
}}
function clearMarks() {{
  marks.forEach(b => b && b.classList.remove("on"));
  marks = [];
}}
function stop() {{
  A.pause(); A.onended = null; queue = []; qi = 0;
  clearMarks(); bnow.textContent = "—"; bwho.textContent = "再生していません";
  document.querySelectorAll(".run.on").forEach(b => b.classList.remove("on"));
}}
function step() {{
  clearMarks();
  if (qi >= queue.length) {{ stop(); return; }}
  const it = queue[qi++];
  bnow.textContent = it.k;
  bwho.textContent = NAMES[it.s] + "（" + qi + " / " + queue.length + "）";
  if (it.btn) {{ it.btn.classList.add("on"); it.btn.classList.add("done"); marks = [it.btn]; }}
  A.src = src(it.s, it.k);
  A.onended = () => setTimeout(step, it.gap === undefined ? 260 : it.gap);
  A.play().catch(() => {{ /* 自動再生が止められた場合は次へ進めない */ }});
}}
function run(items) {{ stop(); queue = items; qi = 0; step(); }}
function btnOf(sid, k) {{
  return document.querySelector('.p[data-s="' + sid + '"][data-k="' + k + '"]');
}}

document.getElementById("bstop").addEventListener("click", stop);
document.addEventListener("click", (e) => {{
  const one = e.target.closest("button.p");
  if (one) {{ run([{{s: one.dataset.s, k: one.dataset.k, btn: one}}]); return; }}

  const seq = e.target.closest("button[data-seq]");   // 清→濁 を話者ごとに続けて
  if (seq) {{
    const ks = seq.dataset.seq.split(",");
    const items = [];
    Object.keys(NAMES).forEach(sid => ks.forEach((k, j) =>
      items.push({{s: sid, k, btn: btnOf(sid, k), gap: j === ks.length - 1 ? 520 : 200}})));
    run(items); return;
  }}
  const row = e.target.closest("button[data-row]");   // 1字を話者ぶん横に
  if (row) {{
    const k = row.dataset.row;
    run(Object.keys(NAMES).map(sid => ({{s: sid, k, btn: btnOf(sid, k)}})));
    return;
  }}
  const all = e.target.closest("button[data-all]");   // 1話者で全68字
  if (all) {{
    const sid = all.dataset.all;
    stop(); all.classList.add("on");
    run(KANA.map(k => ({{s: sid, k, btn: btnOf(sid, k)}})));
    all.classList.add("on");
    return;
  }}
}});
document.addEventListener("keydown", (e) => {{ if (e.key === "Escape") stop(); }});
</script>
</body>
</html>
"""
    io.open(OUT, "w", encoding="utf-8").write(html)
    print(f"書き出し: {OUT}  ({len(html.encode('utf-8')) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main() or 0)
