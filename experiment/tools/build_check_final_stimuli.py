#!/usr/bin/env python3
"""
本番の刺激544本を、五十音表で耳で確かめる
==========================================
2026-08-25 作成。

**なにを聞くのか。** experiment/transfer_stimuli_amitaro/ にある**本番の刺激そのもの**を
鳴らす。切り出したモーラ（cut_さ）でも音量そろえ後（norm_さ）でもなく、
**参加者が実際に聞くファイル**である。ここまでの工程（合成→切り出し→音量そろえ→
打ち切り点の配置→544本の生成）を全部通ったあとの姿を確かめるためのもの。

各字について2つ鳴らせる:
  全長  … <かな>_full.wav。打ち切らずに全部聞かせるもの（確認問題Aで使う）
  最長  … その字の打ち切り点のうちいちばん長いもの

⚠ **音声は base64 で埋め込む。**
   隣のフォルダから読む方式はローカルで開くと鳴らないことがある（HANDOFF 2.5）。

⚠ **機械の数値を信用しすぎないこと。** 過去2回、機械が「問題なし」と判定したものを
   丸山さんが聞いて問題を見つけている。**合否は耳で決める。**

入力
  experiment/transfer_stimuli_amitaro/          … 本番の刺激544本
  experiment/transfer_audio_manifest_amitaro.json … その索引

出力
  experiment/tools/check_final_stimuli.html

使い方
  python3 experiment/tools/build_check_final_stimuli.py
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXP = os.path.join(ROOT, "experiment")
SRC = os.path.join(EXP, "transfer_stimuli_amitaro")
MANIFEST = os.path.join(EXP, "transfer_audio_manifest_amitaro.json")
OUT = os.path.join(HERE, "check_final_stimuli.html")

# transfer_config.js の answer_grid と同じ。空欄 "" は五十音表の穴。
GRID = [
    ["あ", "い", "う", "え", "お"], ["か", "き", "く", "け", "こ"], ["さ", "し", "す", "せ", "そ"],
    ["た", "ち", "つ", "て", "と"], ["な", "に", "ぬ", "ね", "の"], ["は", "ひ", "ふ", "へ", "ほ"],
    ["ま", "み", "む", "め", "も"], ["や", "", "ゆ", "", "よ"], ["ら", "り", "る", "れ", "ろ"],
    ["わ", "", "", "", "ん"],
    ["が", "ぎ", "ぐ", "げ", "ご"], ["ざ", "じ", "ず", "ぜ", "ぞ"], ["だ", "", "", "で", "ど"],
    ["ば", "び", "ぶ", "べ", "ぼ"], ["ぱ", "ぴ", "ぷ", "ぺ", "ぽ"],
]
SPLIT_AT = 10
TARGETS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
# 2026-08-25 に合成条件を変えた字。ここを重点的に聞く。
FIXED = ["り", "ろ"]      # 核を外した（accent=0）
LEADV = ["び"]            # 「あ＋び＋さ」で合成し、前後の「あ」と「さ」を削った


def b64(p):
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    if not os.path.isdir(SRC):
        sys.exit(f"刺激のフォルダがありません: {SRC}")
    man = json.load(open(MANIFEST, encoding="utf-8"))
    items = man["items"]

    # 字ごとに「全長」と「いちばん長い打ち切り点」を拾う
    best, full = {}, {}
    for key, it in items.items():
        ch = it["char"]
        # 「打ち切りなし(全長)」は索引では gate_ms が null になっている
        if it["gate_ms"] is None:
            full[ch] = it
        else:
            g = float(it["gate_ms"])
            if ch not in best or g > float(best[ch]["gate_ms"]):
                best[ch] = it

    kana = [k for row in GRID for k in row if k]
    snd, st = {}, {}
    for k in kana:
        if k not in full or k not in best:
            sys.exit(f"索引に足りない字があります: {k}")
        for tag, it in (("full", full[k]), ("max", best[k])):
            p = os.path.join(SRC, it["file"])
            if not os.path.exists(p):
                sys.exit(f"ファイルがありません: {p}")
            snd[f"{k}_{tag}"] = b64(p)
        st[k] = {"max_ms": int(float(best[k]["gate_ms"])),
                 "full_ms": round(float(full[k]["dur_ms"]) - float(full[k]["lead_ms"]), 1)}

    print(f"  {len(kana)}字ぶんを埋め込みました（全長＋最長の2本ずつ＝{len(snd)}本）")

    def cell(k):
        if not k:
            return '<td class="hole"></td>'
        s = st[k]
        cls = ""
        note = ""
        if k in TARGETS:
            cls = " tgt"
        if k in FIXED:
            cls += " fixed"
            note = '<div class="tag ok">核を外した</div>'
        if k in LEADV:
            cls += " leadv"
            note = '<div class="tag lv">あ＋び＋さ<br>から切出</div>'
        return (f'<td class="c{cls}">'
                f'<button class="p max" data-f="{k}_max" data-l="{k}（最長 {s["max_ms"]}ms）">{k}</button>'
                f'<button class="p full" data-f="{k}_full" data-l="{k}（全長）">全長</button>'
                f'<div class="ms">最長{s["max_ms"]} / 全{s["full_ms"]:.0f}ms</div>{note}</td>')

    def table(rows):
        return ('<table>' + "".join(
            f'<tr><th>{r[0] or ""}行</th>' + "".join(cell(k) for k in r) + '</tr>'
            for r in rows) + '</table>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>本番の刺激544本の最終確認</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:900px}}
h1{{font-size:19px;margin:0 0 8px}}
p.note{{line-height:1.85;font-size:14px}}
.tables{{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start}}
table{{border-collapse:collapse;margin-top:10px}}
th,td{{border:1px solid #dde1ea;padding:4px;background:#fff;text-align:center;vertical-align:top}}
th{{background:#f7f8fb;font-size:12px;color:#7a8090;width:26px}}
td.hole{{background:#f4f5f7;border-color:#eceef2}}
td.c{{width:66px}}
td.tgt{{background:#fffdf2;box-shadow:inset 0 0 0 2px #e8c766}}
td.fixed{{background:#f1f9f3;box-shadow:inset 0 0 0 2px #6aab7e}}
td.leadv{{background:#eef2fb;box-shadow:inset 0 0 0 2px #6b7fc7}}
button.p{{width:100%;border-radius:5px;cursor:pointer;border:1px solid #b9c0cf;
     font-weight:700;margin-bottom:2px;font-family:inherit}}
button.max{{font-size:19px;padding:3px 0;background:#eef6f8;border-color:#2E7D8F;color:#12414c}}
button.full{{font-size:10px;padding:2px 0;background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:9px;color:#7a8090}}
.tag{{font-size:9px;border-radius:3px;padding:1px 2px;margin-top:2px;line-height:1.3}}
.tag.ok{{color:#245c37;background:#e6f4ea;border:1px solid #a8d3b5}}
.tag.lv{{color:#2b3a75;background:#eaeffb;border:1px solid #b6c2e6}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:13px;padding:5px 11px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin:2px 4px 2px 0;font-family:inherit}}
#now{{margin-left:8px;font-weight:700;font-size:16px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:11px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.85}}
.box b.hl{{background:#fff3bf;padding:0 3px;border-radius:3px}}
.key{{font-size:12px;color:#7a8090;margin-top:8px;line-height:1.8}}
.sw{{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:-1px;
     margin-right:3px}}
</style>
<h1>本番の刺激544本の最終確認</h1>
<p class="note">
鳴るのは <code>experiment/transfer_stimuli_amitaro/</code> にある
<b>参加者が実際に聞くファイルそのもの</b>です。
合成→切り出し→音量そろえ→打ち切り点の配置→544本の生成、を全部通ったあとの姿です。
</p>
<div class="box">
<b class="hl">大きいボタン（青）＝その字のいちばん長い打ち切り条件。</b>
これがいちばん聞き取りやすいはずの条件なので、ここで字が分からなければその字は使えません。
「全長」は打ち切らずに全部聞かせるもの（確認問題Aで使います）。<br><br>
<b>今回とくに確かめていただきたい字</b><br>
<span class="sw" style="background:#f1f9f3;box-shadow:inset 0 0 0 2px #6aab7e"></span>
<b>り・ろ</b> … 核を外して作り直しました。「り」が「い」に、「ろ」が「も」に
聞こえていたのが直っているかを確かめてください。<br>
<span class="sw" style="background:#eef2fb;box-shadow:inset 0 0 0 2px #6b7fc7"></span>
<b>び</b> … <b>「あ＋び＋さ」で合成し、前後の「あ」と「さ」を削りました。</b>
語頭に破裂音が来ると閉鎖（唇を閉じている区間）が現れようがないので、前に母音を置いて
閉鎖を作っています。「び」が「い」に聞こえていたのが直っているかを確かめてください。
</div>
<div id="bar">
  <button id="chk" style="background:#f1f9f3;border-color:#6aab7e">▶ り・ろ・び を続けて</button>
  <button id="tgt" style="background:#fffdf2;border-color:#e8c766">▶ 本命8字</button>
  <button id="all" style="background:#eef6f8;border-color:#2E7D8F">▶ 68字を続けて</button>
  <button id="stop">■ 停止</button><span id="now"></span>
</div>
<div class="tables">
{table(GRID[:SPLIT_AT])}
{table(GRID[SPLIT_AT:])}
</div>
<div class="key">
<span class="sw" style="background:#fffdf2;box-shadow:inset 0 0 0 2px #e8c766"></span>本命8字（測定の対象）
<span class="sw" style="background:#f1f9f3;box-shadow:inset 0 0 0 2px #6aab7e;margin-left:10px"></span>核を外して作り直した字
<span class="sw" style="background:#eef2fb;box-shadow:inset 0 0 0 2px #6b7fc7;margin-left:10px"></span>前に母音を置いて作り直した字<br>
数値は「最長の打ち切り点 / 全長」。<b>数値は目印にすぎません。合否は耳で決めてください。</b>
</div>
<script>
const SND = {json.dumps(snd)};
const KANA = {json.dumps(kana, ensure_ascii=False)};
const TARGETS = {json.dumps(TARGETS, ensure_ascii=False)};
const CHECK = {json.dumps(FIXED + LEADV, ensure_ascii=False)};
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
    await new Promise(r => setTimeout(r, it.gap || 480));
  }}
  if (!stopped) now.textContent = '';
}}

document.querySelectorAll('button.p').forEach(b => {{
  b.addEventListener('click', () => run([{{id: b.dataset.f, label: b.dataset.l, btn: b}}]));
}});
const btnOf = id => document.querySelector(`button.p[data-f="${{id}}"]`);
const seq = (list, pre) => list.map(k =>
  ({{id: k + '_max', label: (pre || '') + k, btn: btnOf(k + '_max')}}));
document.getElementById('all').addEventListener('click', () => run(seq(KANA)));
document.getElementById('tgt').addEventListener('click', () => run(seq(TARGETS, '本命： ')));
// り・ろ・び は「最長」と「全長」を続けて鳴らす（判断しやすいように）
document.getElementById('chk').addEventListener('click', () => run(
  CHECK.flatMap(k => [
    {{id: k + '_max', label: k + '： 最長', btn: btnOf(k + '_max'), gap: 350}},
    {{id: k + '_full', label: k + '： 全長', btn: btnOf(k + '_full'), gap: 700}},
  ])));
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
