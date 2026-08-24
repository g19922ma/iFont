#!/usr/bin/env python3
"""
「さ」＋核あり の68字を五十音表で全部聞く
==========================================
2026-08-24 作成。

**なぜこれを作るのか。**
丸山さんが本命8字を聞き比べて、**核あり（accent=1）を採用**と判断した
（experiment/tools/compare_target_accent.html での判定）。
核なし（acc=0）は「り」が「り」に聞こえるようになる代わりに、
**本命の「か」と「つ」で後続の「さ」が末尾に残る**（高域割合 0.72 / 0.97）ため却下。

**あわせて分かったこと。** いま配信されている544本
（experiment/transfer_stimuli_amitaro/）は、来歴をたどると

    raw_ぱ → cut → norm → transfer_stimuli_amitaro/

で、**後続音が「ぱ」のまま**である（cut/crop_report.json の src が raw_ぱ）。
HANDOFF 2.2 で後続音を「さ」に決めたあと、544本を作り直していない。
したがって**作り直しは必要**で、作り直す先が「さ」＋核ありになる。

そこで、544本を作る前に、**その材料である68字を耳で確かめる**ためのページを作る。
ここで合格しなければ、そのあとの音量そろえ・打ち切り点・544本生成をやっても無駄になる。

⚠ **音声は base64 で埋め込む。**
   隣のフォルダから読む方式はローカルで開くと鳴らないことがある（HANDOFF 2.5）。

⚠ **機械の数値を信用しすぎないこと。** 過去2回、機械が「問題なし」と判定したものを
   丸山さんが聞いて問題を見つけている（「ん」の残り 0/68→実際34/68、「り」の弾き音）。
   **合否は耳で決める。** 数値は目印にすぎない。

入力（既存。このスクリプトは合成も切り出しもしない）
  experiment/tts_candidates_carrier2/prev_cut_さ/   … 「字＋さ」accent=1 の切り出し68字
  experiment/tts_candidates_carrier2/prev_raw_さ/   … その切り出し前の全体

出力
  experiment/tools/check_sa_acc1.html

使い方
  python3 experiment/tools/build_check_sa_acc1.py
"""
import base64
import json
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crop_carrier_stop import read_wav, detect_onset_ms  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
C2 = os.path.join(ROOT, "experiment", "tts_candidates_carrier2")
CUT = os.path.join(C2, "prev_cut_さ")     # 「字＋さ」accent=1 の切り出し
RAW = os.path.join(C2, "prev_raw_さ")     # その全体
OUT = os.path.join(HERE, "check_sa_acc1.html")

# transfer_config.js の answer_grid と同じ。空欄 "" は五十音表の穴。
GRID = [
    ["あ", "い", "う", "え", "お"], ["か", "き", "く", "け", "こ"], ["さ", "し", "す", "せ", "そ"],
    ["た", "ち", "つ", "て", "と"], ["な", "に", "ぬ", "ね", "の"], ["は", "ひ", "ふ", "へ", "ほ"],
    ["ま", "み", "む", "め", "も"], ["や", "", "ゆ", "", "よ"], ["ら", "り", "る", "れ", "ろ"],
    ["わ", "", "", "", "ん"],
    ["が", "ぎ", "ぐ", "げ", "ご"], ["ざ", "じ", "ず", "ぜ", "ぞ"], ["だ", "", "", "で", "ど"],
    ["ば", "び", "ぶ", "べ", "ぼ"], ["ぱ", "ぴ", "ぷ", "ぺ", "ぽ"],
]
SPLIT_AT = 10                                    # 表を2段に折り返す位置
TARGETS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]   # 本命8字
# 字自身に摩擦・破擦があるので、末尾の高域では「さ」の漏れを判定できない字
SELF_FRIC = set("さしすせそはひふへほざじずぜぞちつ")

HI_LO, HI_HI = 4000, 10000
TAIL_MS = 25.0


def tail_leak(path):
    """末尾25ms（フェード5msを除く）の 4〜10kHz の割合と音量。"""
    x, sr = read_wav(path)
    k, off = int(sr * TAIL_MS / 1000), int(sr * 0.005)
    seg = x[-k - off:-off] if len(x) > k + off else x[-k:]
    if len(seg) < 32:
        return None, None
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1.0 / sr)
    hi = sp[(f >= HI_LO) & (f < HI_HI)].sum()
    return float(hi / (sp[f < HI_HI].sum() + 1e-14)), \
        float(20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-12))


def b64(p):
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def dur_ms(p):
    with wave.open(p, "rb") as w:
        return w.getnframes() / w.getframerate() * 1000.0


def main():
    for d in (CUT, RAW):
        if not os.path.isdir(d):
            sys.exit(f"フォルダがありません: {d}")

    kana = [k for row in GRID for k in row if k]
    snd, st = {}, {}
    missing = []
    for k in kana:
        cp, rp = os.path.join(CUT, f"{k}.wav"), os.path.join(RAW, f"{k}.wav")
        if not os.path.exists(cp) or not os.path.exists(rp):
            missing.append(k)
            continue
        snd[f"{k}_cut"] = b64(cp)
        snd[f"{k}_full"] = b64(rp)
        x, sr = read_wav(rp)
        onset = detect_onset_ms(x, sr)
        leak, db = tail_leak(cp)
        st[k] = {"mora_ms": round(dur_ms(cp) - onset, 1), "leak": round(leak, 3),
                 "leak_db": round(db, 1)}
    if missing:
        sys.exit(f"音声がありません: {' '.join(missing)}")

    ms = [v["mora_ms"] for v in st.values()]
    flag = [k for k, v in st.items() if v["leak"] > 0.15 and k not in SELF_FRIC]
    print(f"  {len(st)}字  モーラ長 最小{min(ms):.0f} 中央{np.median(ms):.0f} 最大{max(ms):.0f} ms")
    print(f"  末尾に「さ」が残っている疑い（字自身の摩擦を除く）: "
          f"{len(flag)}字" + (f"  {' '.join(flag)}" if flag else ""))

    def cell(k):
        if not k:
            return '<td class="hole"></td>'
        s = st[k]
        cls = " tgt" if k in TARGETS else ""
        warn = ""
        if s["leak"] > 0.15:
            if k in SELF_FRIC:
                warn = '<div class="dim">字自身が摩擦<br>数値では判定不可</div>'
            else:
                warn = f'<div class="warn">「さ」残り疑い<br>{s["leak"]:.2f}</div>'
        return (f'<td class="c{cls}">'
                f'<button class="p cut" data-f="{k}_cut" data-l="{k}（切り出し）">{k}</button>'
                f'<button class="p full" data-f="{k}_full" data-l="{k}さ（全体）">全体</button>'
                f'<div class="ms">{s["mora_ms"]:.0f}ms</div>{warn}</td>')

    def table(rows):
        return ('<table>' + "".join(
            f'<tr><th>{r[0] if r[0] else ""}行</th>' + "".join(cell(k) for k in r) + '</tr>'
            for r in rows) + '</table>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>「さ」＋核あり 68字の確認</title>
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
td.c{{width:62px}}
td.tgt{{background:#fffdf2;box-shadow:inset 0 0 0 2px #e8c766}}
button.p{{width:100%;border-radius:5px;cursor:pointer;border:1px solid #b9c0cf;
     font-weight:700;margin-bottom:2px;font-family:inherit}}
button.cut{{font-size:19px;padding:3px 0;background:#eef6f8;border-color:#2E7D8F;color:#12414c}}
button.full{{font-size:10px;padding:2px 0;background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:9.5px;color:#7a8090}}
.warn{{font-size:9px;color:#9a3412;background:#fff4ed;border:1px solid #f0c4a8;
     border-radius:3px;padding:1px 2px;margin-top:2px;line-height:1.3}}
.dim{{font-size:9px;color:#98a0ae;line-height:1.3;margin-top:2px}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:13px;padding:5px 11px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin:2px 4px 2px 0;font-family:inherit}}
#now{{margin-left:8px;font-weight:700;font-size:16px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:11px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.85}}
.box b.hl{{background:#fff3bf;padding:0 3px;border-radius:3px}}
.key{{font-size:12px;color:#7a8090;margin-top:8px;line-height:1.7}}
.sw{{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:-1px;
     margin-right:3px}}
</style>
<h1>「さ」＋核あり 68字の確認</h1>
<p class="note">
後続音を<b>「さ」</b>、対象モーラに<b>アクセント核あり（accent=1）</b>で合成し、
第1モーラだけを切り出したものです。<b>これが544本の刺激の材料になります。</b>
</p>
<div class="box">
<b class="hl">大きいボタン（青）を押すと、その字の切り出したモーラが鳴ります。</b>
これが実際に参加者が聞く音です。「全体」は切り出す前の「○さ」で、参考用です。<br><br>
<b>確かめていただきたいこと</b><br>
① 68字とも、その字に聞こえるか<br>
② 末尾に「さ」が混ざって聞こえる字はないか<br>
③ とくに<b>本命8字（黄色い枠）</b>は念入りに<br><br>
<b>おかしい字があれば、その字を教えてください。</b>
ここで合格すれば、音量そろえ→打ち切り点→544本の生成に進みます。
</div>
<div id="bar">
  <button id="all" style="background:#eef6f8;border-color:#2E7D8F">▶ 68字を続けて</button>
  <button id="tgt" style="background:#fffdf2;border-color:#e8c766">▶ 本命8字だけ続けて</button>
  <button id="stop">■ 停止</button><span id="now"></span>
</div>
<div class="tables">
{table(GRID[:SPLIT_AT])}
{table(GRID[SPLIT_AT:])}
</div>
<div class="key">
<span class="sw" style="background:#fffdf2;box-shadow:inset 0 0 0 2px #e8c766"></span>本命8字（測定の対象）
数値は切り出したモーラの長さ。<b>数値は目印にすぎません。</b>
過去2回、機械が「問題なし」と判定したものを聞いて問題が見つかっています。
<b>合否は耳で決めてください。</b>
</div>
<script>
const SND = {json.dumps(snd)};
const KANA = {json.dumps([k for row in GRID for k in row if k], ensure_ascii=False)};
const TARGETS = {json.dumps(TARGETS, ensure_ascii=False)};
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
    await new Promise(r => setTimeout(r, 480));
  }}
  if (!stopped) now.textContent = '';
}}

document.querySelectorAll('button.p').forEach(b => {{
  b.addEventListener('click', () => run([{{id: b.dataset.f, label: b.dataset.l, btn: b}}]));
}});
const btnOf = id => document.querySelector(`button.p[data-f="${{id}}"]`);
document.getElementById('all').addEventListener('click', () =>
  run(KANA.map(k => ({{id: k + '_cut', label: k, btn: btnOf(k + '_cut')}}))));
document.getElementById('tgt').addEventListener('click', () =>
  run(TARGETS.map(k => ({{id: k + '_cut', label: '本命： ' + k, btn: btnOf(k + '_cut')}}))));
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
    print(f"\n  → {OUT}  ({os.path.getsize(OUT)/1024/1024:.1f} MB・base64埋め込み)")


if __name__ == "__main__":
    main()
