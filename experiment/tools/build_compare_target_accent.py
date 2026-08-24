#!/usr/bin/env python3
"""
本命8字を「アクセント核あり／なし」で聞き比べる
================================================
2026-08-24 作成。

**なぜこれを作るのか。**
「りさ」が「いさ」に聞こえる件を直すため、対象モーラのアクセント核を外す（accent=0）
案が出た。ところが acc=0 にすると**切り出しが68字中34字で下限75msに張り付き、
21字で後続の「さ」の摩擦が刺激の末尾に残った**（末尾25msの高域割合が0.6〜0.99、
−21〜−26dB＝十分聞こえる大きさ）。「ん」方式で起きた失敗の再来である。

一方、**本命8字は あ・か・が・ぱ・し・つ・ま・ら で、「り」も「ろ」も入っていない**
（experiment/transfer_config.js 363行目）。ら行から入っているのは「ら」だけで、
その「ら」は acc=1 でも acc=0 でも切り出しがきれいである。

  ・「ら」の高域割合は onset から 110ms まで ずっと 0.01（どちらの版でも）
  ・末尾に「さ」が漏れた量は 0.005（しきい値0.15）
  ・モーラ長の差は 5ms（122ms 対 127ms）

つまり **34字の切り出しを壊してまで acc=0 にする理由は、測定対象の側には無い**。
「り」「ろ」は偽ターゲット59字の候補にすぎない。

そこで、**測定対象である本命8字だけを acc=1 と acc=0 で並べ、耳で決めていただく**。
機械の数値は2回続けて外している（「ん」の残り・「り」の弾き音）ので、判定は耳で行う。

⚠ **音声は base64 で埋め込む。**
   隣のフォルダから読む方式（new Audio(DIR + name)）はローカルで開くと鳴らないことがあり、
   実際に「バグってる」という報告になった。合成し直しは不要で、既にある4フォルダを使う。

入力（すべて既存。このスクリプトは合成しない）
  experiment/tts_candidates_carrier2/prev_raw_さ/  … acc=1 の「字＋さ」全体
  experiment/tts_candidates_carrier2/prev_cut_さ/  … acc=1 の切り出し
  experiment/tts_candidates_carrier2/raw_さ/       … acc=0 の「字＋さ」全体
  experiment/tts_candidates_carrier2/cut_さ/       … acc=0 の切り出し

出力
  experiment/tools/compare_target_accent.html

使い方
  python3 experiment/tools/build_compare_target_accent.py
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
OUT = os.path.join(HERE, "compare_target_accent.html")

# transfer_config.js 363行目の targets と同じ並び。ここを勝手に変えないこと。
KANA = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
FOL = "さ"

# (タグ, 表示名, 全体のフォルダ, 切り出しのフォルダ)
VARIANTS = [
    ("acc1", "核あり（現行・544本はこれで出来ている）", "prev_raw_さ", "prev_cut_さ"),
    ("acc0", "核なし（accent=0・作り直し案）", "raw_さ", "cut_さ"),
]

HI_LO, HI_HI = 4000, 10000   # 「さ」の摩擦が集まる帯域
TAIL_MS = 25.0               # 末尾のどれだけを見るか


def tail_leak(path):
    """切り出しの末尾に後続「さ」の摩擦がどれだけ残っているか。

    末尾25ms（フェードアウト5msは除く）の 4〜10kHz が占める割合。
    母音は 0.01〜0.03、「さ」の摩擦は 0.3 以上なので、0.15 を超えたら漏れている疑い。
    ただし「し」は字自身が摩擦なので、この指標では判定できない（もともと高い）。
    """
    x, sr = read_wav(path)
    k = int(sr * TAIL_MS / 1000)
    off = int(sr * 0.005)
    seg = x[-k - off:-off] if len(x) > k + off else x[-k:]
    if len(seg) < 32:
        return None, None
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1.0 / sr)
    hi = sp[(f >= HI_LO) & (f < HI_HI)].sum()
    tot = sp[f < HI_HI].sum() + 1e-14
    rms = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-12)
    return float(hi / tot), float(rms)


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def dur_ms(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate() * 1000.0


def main():
    for _, _, rd, cd in VARIANTS:
        for d in (rd, cd):
            p = os.path.join(C2, d)
            if not os.path.isdir(p):
                sys.exit(f"フォルダがありません: {p}")

    snd, stats = {}, {}
    for tag, _label, rawdir, cutdir in VARIANTS:
        stats[tag] = {}
        for k in KANA:
            rp = os.path.join(C2, rawdir, f"{k}.wav")
            cp = os.path.join(C2, cutdir, f"{k}.wav")
            for p in (rp, cp):
                if not os.path.exists(p):
                    sys.exit(f"ファイルがありません: {p}")
            snd[f"{k}_{tag}_full"] = b64(rp)
            snd[f"{k}_{tag}_cut"] = b64(cp)
            x, sr = read_wav(rp)
            onset = detect_onset_ms(x, sr)
            leak, rms = tail_leak(cp)
            stats[tag][k] = {"mora_ms": round(dur_ms(cp) - onset, 1),
                             "cut_ms": round(dur_ms(cp), 1),
                             "onset_ms": round(onset, 1),
                             "leak": round(leak, 3) if leak is not None else None,
                             "leak_db": round(rms, 1) if rms is not None else None}
        print(f"  {_label}")
        print("    " + "  ".join(
            f"{k}:{stats[tag][k]['mora_ms']:.0f}ms/漏れ{stats[tag][k]['leak']:.2f}"
            for k in KANA))

    rows = []
    for tag, label, _, _ in VARIANTS:
        cells = []
        for k in KANA:
            s = stats[tag][k]
            # 「し」は字自身が摩擦なので、この指標では漏れを判定できない
            warn = ""
            if k != "し" and s["leak"] is not None and s["leak"] > 0.15:
                warn = ('<div class="warn">「さ」が残っている疑い<br>'
                        f'高域{s["leak"]:.2f}／{s["leak_db"]:.0f}dB</div>')
            cells.append(
                f'<td><button class="p full" data-f="{k}_{tag}_full" '
                f'data-l="{label}／{k}{FOL} 全体">▶ 全体</button>'
                f'<button class="p cut" data-f="{k}_{tag}_cut" '
                f'data-l="{label}／{k} 切り出し">▶ {k}</button>'
                f'<div class="ms">モーラ {s["mora_ms"]:.0f}ms</div>{warn}</td>')
        cls = ' class="cur"' if tag == "acc1" else ""
        rows.append(f'<tr{cls}><th>{label}</th>{"".join(cells)}</tr>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>本命8字の聞き比べ（アクセント核あり／なし）</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:1150px}}
h1{{font-size:19px;margin:0 0 8px}}
p.note{{line-height:1.85;font-size:14px;max-width:920px}}
table{{border-collapse:collapse;margin-top:12px;width:100%}}
th,td{{border:1px solid #dde1ea;padding:6px;background:#fff;text-align:center;vertical-align:top}}
thead th{{background:#eef1f6;font-size:21px}}
tbody th{{text-align:left;font-size:13px;width:250px;background:#f7f8fb;line-height:1.5}}
tr.cur th{{background:#eef6f8}} tr.cur td{{background:#fbfeff}}
button.p{{width:100%;font-size:11.5px;padding:5px 2px;border-radius:5px;cursor:pointer;
     border:1px solid #b9c0cf;font-weight:700;margin-bottom:3px}}
button.full{{background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.cut{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:10px;color:#7a8090;line-height:1.35}}
.warn{{font-size:10px;color:#9a3412;background:#fff4ed;border:1px solid #f0c4a8;
     border-radius:4px;padding:2px 3px;margin-top:3px;line-height:1.35}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:13px;padding:5px 10px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin:2px 4px 2px 0}}
#now{{margin-left:10px;font-weight:700;font-size:15px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:11px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.85}}
.box b.hl{{background:#fff3bf;padding:0 3px;border-radius:3px}}
</style>
<h1>本命8字の聞き比べ（アクセント核あり／なし）</h1>
<p class="note">
測定の対象である<b>本命8字（あ・か・が・ぱ・し・つ・ま・ら）だけ</b>を、
<b>核あり（現行）</b>と<b>核なし（accent=0）</b>で並べました。
紫が<b>切り出す前の全体</b>、青が<b>切り出したモーラ＝実際の刺激</b>です。
</p>
<div class="box">
<b class="hl">確かめていただきたいのは1点だけです。</b>
<b>青いボタン（切り出したモーラ）が、8字とも正しくその字に聞こえるか。</b><br>
上の段（核あり）は、いま出来ている544本の刺激と同じ作り方のものです。
下の段（核なし）は「り」を直すための案ですが、
<b>68字中21字で後続の「さ」が末尾に残ってしまう</b>ことが分かっています
（このページでは該当する字に橙色の印を付けました）。<br><br>
<b>「り」と「ろ」は本命8字に入っていません。</b>ら行から入っているのは「ら」だけで、
その「ら」はどちらの版でも切り出しがきれいです（末尾の漏れ 0.005・モーラ長の差 5ms）。
ですので、<b>上の段（核あり）で8字とも問題なく聞こえるなら、作り直しは不要</b>になります。<br><br>
<span style="color:#7a8090">※「し」は字自身が摩擦音なので、末尾の高域では漏れを判定できません。耳で確かめてください。</span>
</div>
<div id="bar">
  <b style="font-size:12px">字ごとに 核あり→核なし を続けて：</b><br>
  {"".join(f'<button class="ab" data-k="{k}">▶ {k}</button>' for k in KANA)}
  <button id="allcur" style="background:#eef6f8;border-color:#2E7D8F">▶ 核あり8字を続けて</button>
  <button id="stop">■ 停止</button><span id="now"></span>
</div>
<table>
<thead><tr><th style="font-size:13px">合成の設定</th>
{"".join(f"<th>{k}</th>" for k in KANA)}</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
<script>
const SND = {json.dumps(snd)};
const KANA = {json.dumps(KANA, ensure_ascii=False)};
const now = document.getElementById('now');
let cur = null, queue = [], stopped = false;

function url(id){{ return 'data:audio/wav;base64,' + SND[id]; }}

function play(id, label, btn){{
  return new Promise(res => {{
    if (!SND[id]) {{ res(); return; }}
    const a = new Audio(url(id));
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
    await new Promise(r => setTimeout(r, it.gap || 260));
  }}
  if (!stopped) now.textContent = '';
}}

document.querySelectorAll('button.p').forEach(b => {{
  b.addEventListener('click', () => run([{{id: b.dataset.f, label: b.dataset.l, btn: b}}]));
}});

// 字ごとに「核あり → 核なし」を続けて鳴らす。切り出したモーラだけを比べる。
document.querySelectorAll('button.ab').forEach(b => {{
  b.addEventListener('click', () => {{
    const k = b.dataset.k;
    run([
      {{id: k + '_acc1_cut', label: k + '： 核あり（現行）', gap: 500}},
      {{id: k + '_acc0_cut', label: k + '： 核なし（acc0）'}},
    ]);
  }});
}});

document.getElementById('allcur').addEventListener('click', () => {{
  run(KANA.map(k => ({{id: k + '_acc1_cut', label: '核あり： ' + k, gap: 420}})));
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
    mb = os.path.getsize(OUT) / 1024 / 1024
    print(f"\n  → {OUT}  ({mb:.1f} MB・音声は base64 で埋め込み済み)")


if __name__ == "__main__":
    main()
