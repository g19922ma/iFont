#!/usr/bin/env python3
"""
び・り・ろ の合成のさせ方10通りを聞き比べる（音声を埋め込む版）
================================================================
2026-08-25 作成。

**なぜ作り直すのか。** build_compare_synth_params.py が出す compare_synth_params.html は、
音を隣のフォルダから読む方式（new Audio(DIR + ファイル名)）なので、
**ローカルで開くと鳴らないことがある**。実際に「バグってる」という報告になった。
中身は同じで、**音声を base64 で埋め込んだ版**を出す。

**この3字は何が問題なのか。**
  び … 「い」に聞こえる（/b/ の破裂が母音に埋もれる）
  り … 「い」に聞こえる（弾き音が母音に埋もれる）
  ろ … 「も」に聞こえる（弾き音が鼻音に化ける）
いずれも**語頭の弱い子音が聞き取れない**という同じ症状である。
り・ろ は「対象の核を外す」で解決し、本番に採用した（build_carrier_takes.py の
TARGET_ACCENT_BY_KANA）。**び だけが未解決**で、核を外すと逆に悪化する（8ms→1ms）。

入力（build_compare_synth_params.py が作ったもの。このスクリプトは合成しない）
  experiment/tools/compare_synth_params/stats.json
  experiment/tools/compare_synth_params/<かな>_<設定>_{full,cut}.wav

出力
  experiment/tools/compare_biriro.html

使い方
  # 先に音を作る（COEIROINK を起動しておくこと）
  python3 experiment/tools/build_compare_synth_params.py --kana び り ろ
  # そのあとで埋め込み版を出す
  python3 experiment/tools/build_compare_biriro_b64.py
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SND = os.path.join(HERE, "compare_synth_params")
OUT = os.path.join(HERE, "compare_biriro.html")

# 本番で採用した設定（丸山判断・2026-08-25）。ページ上で目印を付ける。
ADOPTED = {"り": "acc0", "ろ": "acc0", "び": "current"}
# 未解決の字
UNRESOLVED = ["び"]


def b64(p):
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    sp = os.path.join(SND, "stats.json")
    if not os.path.exists(sp):
        sys.exit(f"{sp} がありません。先に build_compare_synth_params.py --kana び り ろ を走らせてください")
    d = json.load(open(sp, encoding="utf-8"))
    labels, stats, kana = d["labels"], d["stats"], d["kana"]
    tags = list(labels.keys())

    snd = {}
    for t in tags:
        for k in kana:
            for kind in ("full", "cut"):
                p = os.path.join(SND, f"{k}_{t}_{kind}.wav")
                if os.path.exists(p):
                    snd[f"{k}_{t}_{kind}"] = b64(p)
    print(f"  {len(kana)}字 × {len(tags)}通り = {len(snd)} 本を埋め込みました")

    rows = []
    for t in tags:
        cells = []
        for k in kana:
            s = stats[t][k]
            cls = " adopted" if ADOPTED.get(k) == t else ""
            mark = '<div class="tag">本番はこれ</div>' if ADOPTED.get(k) == t else ""
            cells.append(
                f'<td class="{cls.strip()}">'
                f'<button class="p full" data-f="{k}_{t}_full" '
                f'data-l="{labels[t]}／{k}さ 全体">▶ 全体</button>'
                f'<button class="p cut" data-f="{k}_{t}_cut" '
                f'data-l="{labels[t]}／{k} 切り出し">▶ {k}</button>'
                f'<div class="ms">子音 {s["cons_ms"]}ms<br>{s["cons_db"]}dB</div>{mark}</td>')
        cur = ' class="cur"' if t == "current" else ""
        rows.append(f'<tr{cur}><th>{labels[t]}</th>{"".join(cells)}</tr>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>び・り・ろ の合成のさせ方くらべ</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:820px}}
h1{{font-size:19px;margin:0 0 8px}}
p.note{{line-height:1.85;font-size:14px}}
table{{border-collapse:collapse;margin-top:12px;width:100%}}
th,td{{border:1px solid #dde1ea;padding:6px;background:#fff;text-align:center;vertical-align:top}}
thead th{{background:#eef1f6;font-size:21px}}
tbody th{{text-align:left;font-size:12.5px;width:250px;background:#f7f8fb;line-height:1.5}}
tr.cur th{{background:#eef6f8}} tr.cur td{{background:#fbfeff}}
td.adopted{{background:#f1f9f3!important;box-shadow:inset 0 0 0 2px #6aab7e}}
button.p{{width:100%;font-size:11.5px;padding:5px 2px;border-radius:5px;cursor:pointer;
     border:1px solid #b9c0cf;font-weight:700;margin-bottom:3px;font-family:inherit}}
button.full{{background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.cut{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:10px;color:#7a8090;line-height:1.35}}
.tag{{font-size:9.5px;color:#245c37;background:#e6f4ea;border:1px solid #a8d3b5;
     border-radius:3px;padding:1px 2px;margin-top:3px}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:13px;padding:5px 11px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin:2px 4px 2px 0;font-family:inherit}}
#now{{margin-left:8px;font-weight:700;font-size:15px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:11px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.85}}
.box b.hl{{background:#fff3bf;padding:0 3px;border-radius:3px}}
</style>
<h1>び・り・ろ の合成のさせ方くらべ</h1>
<p class="note">
話者はあみたろのまま、<b>合成のさせ方だけ</b>を変えた10通りです。
紫が<b>切り出す前の全体（○さ）</b>、青が<b>切り出したモーラ</b>です。
</p>
<div class="box">
<b class="hl">「び」をどうするか決めるためのページです。</b><br>
り・ろ は「対象の核を外す」で解決し、<b>本番に採用済み</b>です（緑の枠）。<br>
<b>び だけ未解決</b>で、核を外すと子音が 8ms → 1ms と<b>逆に悪化</b>します。
数値の上で唯一伸びるのは<b>いちばん下の「前に『あ』を置く」（8ms → 31ms）</b>ですが、
これは<b>「ありさ」と読ませて真ん中の「り」だけを切り出す</b>方式なので、
採用するには<b>切り出しの起点の決め方を作り直す必要があります</b>
（いまは「母音と対象モーラのあいだの音量の谷」で仮に取っています）。<br><br>
<b>「▶ び を全設定続けて」で通しで聞いて、使えそうな設定があるか教えてください。</b>
どれも駄目なら、び を偽ターゲットの候補から外します（設定1行・本命8字ではないので測定に影響はありません）。
</div>
<div id="bar">
  {"".join(f'<button class="col" data-k="{k}">▶ {k} を全設定続けて</button>' for k in kana)}
  <button id="stop">■ 停止</button><span id="now"></span>
</div>
<table>
<thead><tr><th style="font-size:13px">合成の設定</th>
{"".join(f"<th>{k}</th>" for k in kana)}</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
<script>
const SND = {json.dumps(snd)};
const TAGS = {json.dumps(tags, ensure_ascii=False)};
const LABELS = {json.dumps(labels, ensure_ascii=False)};
const now = document.getElementById('now');
let cur = null, stopped = false;

function play(id, label, btn){{
  return new Promise(res => {{
    if (!SND[id]) {{ res(); return; }}
    const a = new Audio('data:audio/wav;base64,' + SND[id]);
    cur = a;
    if (btn) btn.classList.add('playing');
    now.textContent = label || '';
    a.onended = a.onerror = () => {{ if (btn) btn.classList.remove('playing'); res(); }};
    a.play().catch(() => {{ if (btn) btn.classList.remove('playing'); res(); }});
  }});
}}

async function run(items){{
  stopped = true; if (cur) {{ cur.pause(); cur = null; }}
  document.querySelectorAll('.playing').forEach(b => b.classList.remove('playing'));
  await new Promise(r => setTimeout(r, 60));
  stopped = false;
  for (const it of items) {{
    if (stopped) break;
    await play(it.id, it.label, it.btn);
    if (stopped) break;
    await new Promise(r => setTimeout(r, it.gap || 420));
  }}
  if (!stopped) now.textContent = '';
}}

document.querySelectorAll('button.p').forEach(b => {{
  b.addEventListener('click', () => run([{{id: b.dataset.f, label: b.dataset.l, btn: b}}]));
}});
const btnOf = id => document.querySelector(`button.p[data-f="${{id}}"]`);
document.querySelectorAll('button.col').forEach(b => {{
  b.addEventListener('click', () => {{
    const k = b.dataset.k;
    run(TAGS.map(t => ({{id: `${{k}}_${{t}}_cut`, label: LABELS[t],
                        btn: btnOf(`${{k}}_${{t}}_cut`), gap: 620}})));
  }});
}});
document.getElementById('stop').addEventListener('click', () => {{
  stopped = true;
  if (cur) {{ cur.pause(); cur = null; }}
  document.querySelectorAll('.playing').forEach(b => b.classList.remove('playing'));
  now.textContent = '';
}});
</script>
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  → {OUT}  ({os.path.getsize(OUT)/1024/1024:.1f} MB・base64埋め込み)")


if __name__ == "__main__":
    main()
