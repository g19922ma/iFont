#!/usr/bin/env python3
"""
あみたろの合成設定を変えて、ら行の弾き音がはっきり出る条件をさがす
==================================================================
2026-08-24 作成。

**きっかけ。** あみたろの「りさ」が「いさ」に、「ろさ」も変に聞こえる。
話者はあみたろで確定（ユーザー決定）なので、**音源は変えず、合成のさせ方だけを変えて**
弾き音がはっきり出る条件をさがす。

**すでに分かっていること**
  ・音素列は正しい（「りさ」は ^ r i ] s a $ で /r/ は入っている）
  ・同じ設定なら合成は決定的（作り直してもバイト単位で同一）
  ・弾き音の「長さ」では説明がつかない
    （人の録音の「り」は9ms、あみたろは16ms。あみたろの方が長いのに聞こえない）
  → だから見るべきは長さではなく、**話速・抑揚・アクセント・前後の文脈**である。

試す設定
--------
  話速     speedScale 1.0 / 0.8 / 0.7 / 0.6
           弾き音は速く話すほど潰れるので、いちばん期待できる。
  抑揚     intonationScale 1.3 / 1.5
  アクセント 対象に核 / 核なし / 後続に核 / エンジン任せ
  文脈     「あ＋対象＋さ」と読ませて**真ん中のモーラ**を切り出す。
           弾き音は前の母音からの渡りが手がかりになるので、前に母音を置くと
           はっきりするかもしれない。切り出しの起点は、前の母音と対象モーラのあいだの
           **音量の谷**（舌が触れて音が弱くなるところ）でとる。

出力: experiment/tools/compare_synth_params.html ／ experiment/tools/compare_synth_params/

使い方:
  python3 experiment/tools/build_compare_synth_params.py
  python3 experiment/tools/build_compare_synth_params.py --kana り ろ   # 字を絞る
"""
import argparse
import io
import json
import os
import sys
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crop_carrier_stop import write_wav, detect_onset_ms, apply_fade_out  # noqa: E402
from crop_carrier_fricative import fricative_start, features  # noqa: E402
from build_carrier_takes import SPEAKER_UUID, STYLE_ID, SYNTH  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
SND = os.path.join(ROOT, "experiment", "tools", "compare_synth_params")
OUT = os.path.join(ROOT, "experiment", "tools", "compare_synth_params.html")
COE = "http://127.0.0.1:50032"
FOL = "さ"
LEAD_MS = 50.0


def jpost(path, payload, raw=False):
    req = urllib.request.Request(COE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        b = r.read()
    return b if raw else json.loads(b)


def prosody(text):
    return jpost("/v1/estimate_prosody",
                 {"speakerUuid": SPEAKER_UUID, "style_id": STYLE_ID, "text": text})


def synth(text, detail=None, **over):
    pl = {"speakerUuid": SPEAKER_UUID, "styleId": STYLE_ID, "text": text,
          "prosodyDetail": detail if detail is not None else prosody(text)["detail"]}
    pl.update(SYNTH)
    pl.update(over)
    wav = jpost("/v1/synthesis", pl, raw=True)
    with wave.open(io.BytesIO(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
        return x, w.getframerate()


def cons_metrics(x, sr, onset_ms, thr=-20.0):
    """onset から母音の大きさになるまでの長さ＝子音部。弾き音はここに出る。"""
    pk = np.abs(x).max() + 1e-12
    fr = max(1, int(sr * 0.001))
    m = len(x) // fr
    e = 20 * np.log10(np.sqrt((x[:m * fr].reshape(m, fr) ** 2).mean(axis=1) + 1e-20) / pk + 1e-12)
    i0 = int(onset_ms)
    for t in range(0, 250):
        if i0 + t >= len(e):
            break
        if e[i0 + t] > thr:
            seg = e[i0:i0 + t] if t else np.array([e[i0]])
            return t, round(float(seg.max()), 1)
    return None, None


def norm_to(x, target_rms=0.06, peak_cap=0.85):
    loud = x[np.abs(x) > np.abs(x).max() * 0.05]
    r = float(np.sqrt((loud ** 2).mean() + 1e-20)) if len(loud) else 1e-9
    g = target_rms / max(r, 1e-9)
    if np.abs(x).max() * g > peak_cap:
        g = peak_cap / (np.abs(x).max() + 1e-12)
    return x * g


def lead_cut(x, sr, start_ms, dur_ms=None, fade=True):
    i0 = max(0, int(sr * (start_ms - LEAD_MS) / 1000))
    y = x[i0:] if dur_ms is None else x[i0:min(len(x), int(sr * (start_ms + dur_ms) / 1000))]
    return apply_fade_out(y.copy(), sr) if fade else y


def dip_before(x, sr, lo_ms, hi_ms):
    """lo..hi のあいだで音量がいちばん低い時刻。前の母音と対象モーラの切れ目。"""
    F = features(x, sr)
    seg = [(t, db) for t, db, _hr, _lo, _hi in F if lo_ms <= t <= hi_ms]
    if not seg:
        return None
    return min(seg, key=lambda p: p[1])[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kana", nargs="+", default=list("らりるれろ"))
    args = ap.parse_args()
    os.makedirs(SND, exist_ok=True)
    KANA = args.kana

    ph = {}
    for k in set(KANA) | {FOL, "あ"}:
        ph[k] = prosody(k + "ん")["detail"][0][0]["phoneme"]
    two = lambda k, a1, a2: [[{"phoneme": ph[k], "hira": k, "accent": a1},
                              {"phoneme": ph[FOL], "hira": FOL, "accent": a2}]]

    # (tag, ラベル, 作り方) — 作り方は kana を受けて (x, sr, 第1モーラの開始ms, 長さms) を返す
    def plain(over=None, detail_fn=None, label_note=""):
        def f(k):
            d = detail_fn(k) if detail_fn else two(k, 1, 0)
            x, sr = synth(k + FOL, d, **(over or {}))
            on = detect_onset_ms(x, sr)
            b, _ = fricative_start(x, sr, on)
            return x, sr, on, ((b - on) if b else 110.0)
        return f

    def engine_default(k):
        x, sr = synth(k + FOL, prosody(k + FOL)["detail"])
        on = detect_onset_ms(x, sr)
        b, _ = fricative_start(x, sr, on)
        return x, sr, on, ((b - on) if b else 110.0)

    def context(k):
        """「あ＋対象＋さ」の真ん中を切り出す。"""
        d = [[{"phoneme": ph["あ"], "hira": "あ", "accent": 0},
              {"phoneme": ph[k], "hira": k, "accent": 1},
              {"phoneme": ph[FOL], "hira": FOL, "accent": 0}]]
        x, sr = synth("あ" + k + FOL, d)
        on = detect_onset_ms(x, sr)
        b, _ = fricative_start(x, sr, on)
        end = b if b else on + 260
        # 前の母音「あ」と対象モーラのあいだの谷を起点にする
        start = dip_before(x, sr, on + 60, max(on + 70, end - 60)) or (on + 110)
        return x, sr, start, (end - start)

    VARIANTS = [
        ("current", "現行（話速1.0・抑揚1.0・対象に核）", plain()),
        ("sp08", "話速 0.8", plain({"speedScale": 0.8})),
        ("sp07", "話速 0.7", plain({"speedScale": 0.7})),
        ("sp06", "話速 0.6", plain({"speedScale": 0.6})),
        ("in13", "抑揚 1.3", plain({"intonationScale": 1.3})),
        ("in15", "抑揚 1.5", plain({"intonationScale": 1.5})),
        ("acc0", "対象の核を外す", plain(detail_fn=lambda k: two(k, 0, 0))),
        ("acc2", "後続側に核", plain(detail_fn=lambda k: two(k, 0, 1))),
        ("engine", "エンジン任せ", engine_default),
        ("ctx", "前に「あ」を置く（あ＋字＋さ）", context),
    ]

    stats = {}
    for tag, label, fn in VARIANTS:
        for k in KANA:
            x, sr, start, dur = fn(k)
            c, lv = cons_metrics(x, sr, start)
            write_wav(os.path.join(SND, f"{k}_{tag}_full.wav"),
                      norm_to(lead_cut(x, sr, detect_onset_ms(x, sr), fade=False)), sr)
            write_wav(os.path.join(SND, f"{k}_{tag}_cut.wav"),
                      norm_to(lead_cut(x, sr, start, dur)), sr)
            stats.setdefault(tag, {})[k] = {"cons_ms": c, "cons_db": lv,
                                            "mora_ms": round(dur, 1)}
        print(f"  {label:34s} " + "  ".join(
            f"{k}:{stats[tag][k]['cons_ms']}ms/{stats[tag][k]['cons_db']}dB" for k in KANA))

    labels = {t: l for t, l, _ in VARIANTS}
    with open(os.path.join(SND, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"labels": labels, "stats": stats, "kana": KANA}, f,
                  ensure_ascii=False, indent=1)

    rows = []
    for tag, label, _ in VARIANTS:
        cells = []
        for k in KANA:
            s = stats[tag][k]
            cells.append(
                f'<td><button class="p full" data-k="{k}" data-l="{label}／{k}{FOL} 全体" '
                f'data-f="{k}_{tag}_full.wav">▶ 全体</button>'
                f'<button class="p cut" data-k="{k}" data-l="{label}／{k} 切り出し" '
                f'data-f="{k}_{tag}_cut.wav">▶ {k}</button>'
                f'<div class="ms">子音 {s["cons_ms"]}ms<br>{s["cons_db"]}dB</div></td>')
        cls = ' class="cur"' if tag == "current" else ""
        rows.append(f'<tr{cls}><th>{label}</th>{"".join(cells)}</tr>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>合成設定ちがいの聞き比べ（ら行の弾き音）</title>
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
tbody th{{text-align:left;font-size:13px;width:206px;background:#f7f8fb;line-height:1.5}}
tr.cur th{{background:#eef6f8}} tr.cur td{{background:#fbfeff}}
button.p{{width:100%;font-size:11.5px;padding:5px 2px;border-radius:5px;cursor:pointer;
     border:1px solid #b9c0cf;font-weight:700;margin-bottom:3px}}
button.full{{background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.cut{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:10px;color:#7a8090;line-height:1.35}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:14px;padding:5px 12px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin-right:4px}}
#now{{margin-left:10px;font-weight:700;font-size:15px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:11px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.85}}
</style>
<h1>合成設定ちがいの聞き比べ（ら行の弾き音）</h1>
<p class="note">
話者はあみたろのまま、<b>合成のさせ方だけ</b>を変えた版を並べました。
紫が<b>切り出す前の全体</b>、青が<b>切り出したモーラ</b>です。
<b>まず「り を全版続けて」を押して、弾き音がはっきり出る設定を見つけてください。</b>
</p>
<div class="box">
<b>数値は参考程度にしてください。</b>弾き音の「長さ」では説明がつかないことが分かっています
（人の録音の「り」は9ms、あみたろは16msで、あみたろの方が長いのに聞こえません）。
<b>耳で選んでいただくのが目的</b>です。<br>
いちばん下の「前に『あ』を置く」は、<b>「ありさ」と読ませて真ん中の「り」だけを切り出した</b>ものです。
弾き音は前の母音からの渡りが手がかりになるので、これがいちばん自然に聞こえる可能性があります
（ただし採用するには切り出しの起点の決め方を作り直す必要があります）。
</div>
<div id="bar">
  {"".join(f'<button class="col" data-k="{k}">▶ {k} を全版続けて</button>' for k in KANA)}
  <button id="stop">■ 停止</button><span id="now"></span>
</div>
<table>
<thead><tr><th style="font-size:13px">合成の設定</th>
{"".join(f"<th>{k}</th>" for k in KANA)}</tr></thead>
<tbody>
{"".join(rows)}
</tbody></table>
<script>
const DIR="compare_synth_params/";
let cur=null, timer=null;
function stop(){{ if(cur){{cur.pause();cur=null;}} if(timer){{clearTimeout(timer);timer=null;}}
  document.querySelectorAll("button.playing").forEach(b=>b.classList.remove("playing"));
  document.getElementById("now").textContent=""; }}
function play(b){{ if(cur){{cur.pause();cur=null;}}
  document.querySelectorAll("button.playing").forEach(x=>x.classList.remove("playing"));
  const a=new Audio(DIR+encodeURIComponent(b.dataset.f));
  b.classList.add("playing"); a.onended=()=>b.classList.remove("playing");
  cur=a; a.play(); return a; }}
document.querySelectorAll("button[data-f]").forEach(b=>b.onclick=()=>{{
  if(timer){{clearTimeout(timer);timer=null;document.getElementById("now").textContent="";}}
  play(b); }});
document.getElementById("stop").onclick=stop;
function runList(list){{ stop(); let i=0;
  (function next(){{ if(i>=list.length){{document.getElementById("now").textContent="おわり";return;}}
    const b=list[i++];
    document.getElementById("now").textContent=b.dataset.l+"（"+i+"/"+list.length+"）";
    const a=play(b);
    a.onended=()=>{{b.classList.remove("playing"); timer=setTimeout(next,520);}};
    a.onerror=()=>{{timer=setTimeout(next,120);}};
  }})();
}}
document.querySelectorAll("#bar button.col").forEach(btn=>btn.onclick=()=>{{
  const k=btn.dataset.k;
  runList([...document.querySelectorAll(`button.cut[data-k="${{k}}"]`)]); }});
</script>
"""
    open(OUT, "w", encoding="utf-8").write(body)
    print(f"  {len(os.listdir(SND))-1} 本の音を書きました → {OUT}")


if __name__ == "__main__":
    main()
