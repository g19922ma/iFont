#!/usr/bin/env python3
"""
ら行の弾き音を、話者・エンジンを変えて聞き比べる
================================================
2026-08-24 作成。

**きっかけ。** あみたろ（COEIROINK）の「りさ」が「いさ」に、「ろさ」も変に聞こえる、
**切り出す前の合成音の時点ですでにおかしい**という報告。本命8字に「ら」が入っているので、
ここが解決しないと実験が成立しない。

**先に分かっていること（機械で確認済み）**
  1. 音素列は正しい。「りさ」は ^ r i ] s a $ で /r/ は入っている。
  2. 合成は**決定的**。同じ設定で作り直すと、ら行5字ともバイト単位で同一だった。
     つまり「もう一度作り直す」ことでは変わらない。
  3. 弾き音が短いのはあみたろ固有ではない。他の話者・エンジンでも 1〜26ms。
     **自然音声（人の録音）の「り」は9msで、あみたろの16msより短い**。
     つまり「子音部の長さ」だけでは説明がつかない。

そこでこのページでは、**話者を変えれば直るのか**を耳で確かめられるようにする。
同じ「らさ」「りさ」…を、複数の話者・エンジンと、人の録音で並べる。

出力: experiment/tools/compare_speakers.html ／ experiment/tools/compare_speakers/

使い方:
  python3 experiment/tools/build_compare_speakers.py
"""
import hashlib
import io
import json
import os
import sys
import urllib.parse
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crop_carrier_stop import read_wav, write_wav, detect_onset_ms, apply_fade_out  # noqa: E402
from crop_carrier_fricative import fricative_start  # noqa: E402
from build_carrier_takes import SPEAKER_UUID, STYLE_ID, SYNTH  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
SND = os.path.join(ROOT, "experiment", "tools", "compare_speakers")
OUT = os.path.join(ROOT, "experiment", "tools", "compare_speakers.html")
REC = os.path.join(ROOT, "recordings_raw")
COE = "http://127.0.0.1:50032"
VV = "http://127.0.0.1:50021"
KANA = list("らりるれろ")
FOL = "さ"
LEAD_MS = 50.0

# 比べる話者。COEIROINK と VOICEVOX の両方から、弾き音の出方が違うものを選んだ。
COE_SPEAKERS = [
    ("amitaro", "あみたろ（現行）", SPEAKER_UUID, STYLE_ID),
    ("tsukuyomi", "つくよみちゃん", "3c37646f-3881-5374-2a83-149267990abc", 0),
]
VV_SPEAKERS = [
    ("tsumugi", "春日部つむぎ", 8),
    ("metan", "四国めたん", 2),
    ("hau", "雨晴はう", 10),
    ("takehiro", "玄野武宏（男声）", 11),
]


def jpost(base, path, payload, raw=False, timeout=60):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if raw else json.loads(b)


def coe_synth(uuid, style, text):
    pr = jpost(COE, "/v1/estimate_prosody",
               {"speakerUuid": uuid, "style_id": style, "text": text})
    pl = {"speakerUuid": uuid, "styleId": style, "text": text, "prosodyDetail": pr["detail"]}
    pl.update(SYNTH)
    return jpost(COE, "/v1/synthesis", pl, raw=True)


def vv_synth(sid, text):
    q = urllib.parse.urlencode({"text": text, "speaker": sid})
    req = urllib.request.Request(f"{VV}/audio_query?{q}", method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        aq = r.read()
    req2 = urllib.request.Request(f"{VV}/synthesis?speaker={sid}", data=aq,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req2, timeout=60) as r:
        return r.read()


def decode(b):
    with wave.open(io.BytesIO(b)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
        return x, w.getframerate()


def cons_metrics(x, sr, onset_ms, thr=-20.0):
    pk = np.abs(x).max() + 1e-12
    fr = max(1, int(sr * 0.001))
    m = len(x) // fr
    e = 20 * np.log10(np.sqrt((x[:m * fr].reshape(m, fr) ** 2).mean(axis=1) + 1e-20) / pk + 1e-12)
    i0 = int(onset_ms)
    for t in range(0, 200):
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


def lead_cut(x, sr, onset_ms, dur_ms=None, fade=True):
    i0 = max(0, int(sr * (onset_ms - LEAD_MS) / 1000))
    y = x[i0:] if dur_ms is None else x[i0:min(len(x), int(sr * (onset_ms + dur_ms) / 1000))]
    return apply_fade_out(y.copy(), sr) if fade else y


def emit(tag, k, x, sr, stats):
    on = detect_onset_ms(x, sr)
    b, _ = fricative_start(x, sr, on)
    mora = (b - on) if b else 110.0
    c, lv = cons_metrics(x, sr, on)
    write_wav(os.path.join(SND, f"{k}_{tag}_full.wav"), norm_to(lead_cut(x, sr, on, fade=False)), sr)
    write_wav(os.path.join(SND, f"{k}_{tag}_cut.wav"), norm_to(lead_cut(x, sr, on, mora)), sr)
    stats.setdefault(tag, {})[k] = {"cons_ms": c, "cons_db": lv, "mora_ms": round(mora, 1)}


def main():
    os.makedirs(SND, exist_ok=True)
    stats, labels, notes = {}, {}, {}

    # 現行と「作り直し」。同じ設定で2回作って、バイト単位で比べる。
    same = {}
    for k in KANA:
        cur = open(os.path.join(ROOT, "experiment", "tts_candidates_carrier2",
                                "raw_さ", k + ".wav"), "rb").read()
        again = coe_synth(SPEAKER_UUID, STYLE_ID, k + FOL)
        same[k] = (hashlib.sha256(cur).hexdigest() == hashlib.sha256(again).hexdigest())
        emit("amitaro", k, *decode(cur), stats)
        emit("resynth", k, *decode(again), stats)
    labels["amitaro"] = "あみたろ（現行）"
    labels["resynth"] = "あみたろ（作り直し）"
    n_same = sum(1 for v in same.values() if v)
    notes["resynth"] = (f"ら行5字のうち **{n_same}字がバイト単位で現行と同一**。"
                        + ("合成は決定的なので、作り直しても音は変わりません。"
                           if n_same == len(KANA) else "一部は毎回変わります。"))

    for tag, label, uuid, style in COE_SPEAKERS[1:]:
        for k in KANA:
            emit(tag, k, *decode(coe_synth(uuid, style, k + FOL)), stats)
        labels[tag] = label + "（COEIROINK）"
    for tag, label, sid in VV_SPEAKERS:
        try:
            for k in KANA:
                emit(tag, k, *decode(vv_synth(sid, k + FOL)), stats)
            labels[tag] = label + "（VOICEVOX）"
        except Exception as e:
            print(f"  {label}: 合成できませんでした（{type(e).__name__}）")

    # 人の録音。1モーラだけの読み上げなので「Xさ」ではないが、弾き音の基準になる。
    nat = {r["kana"]: r for r in
           json.load(open(os.path.join(REC, "adopted_onsets.json"), encoding="utf-8"))["adopted"]}
    for k in KANA:
        r = nat.get(k)
        if not r:
            continue
        x, sr = read_wav(os.path.join(REC, r["file"]))
        on = float(r["onset_ms"])
        c, lv = cons_metrics(x, sr, on)
        write_wav(os.path.join(SND, f"{k}_natural_full.wav"),
                  norm_to(lead_cut(x, sr, on, fade=False)), sr)
        write_wav(os.path.join(SND, f"{k}_natural_cut.wav"),
                  norm_to(lead_cut(x, sr, on, stats["amitaro"][k]["mora_ms"])), sr)
        stats.setdefault("natural", {})[k] = {"cons_ms": c, "cons_db": lv,
                                              "mora_ms": stats["amitaro"][k]["mora_ms"]}
    labels["natural"] = "人の録音（自然音声）"
    notes["natural"] = "1モーラだけの読み上げなので「らさ」ではありません。弾き音の基準として。"

    with open(os.path.join(SND, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"labels": labels, "stats": stats, "byte_same": same}, f,
                  ensure_ascii=False, indent=1)

    order = [t for t in ["amitaro", "resynth", "natural", "tsukuyomi", "tsumugi",
                         "metan", "hau", "takehiro"] if t in stats]
    rows = []
    for tag in order:
        cells = []
        for k in KANA:
            s = stats[tag].get(k)
            if not s:
                cells.append("<td></td>")
                continue
            cells.append(
                f'<td><button class="p full" data-l="{labels[tag]}／{k}さ 全体" '
                f'data-f="{k}_{tag}_full.wav">▶ {k}{FOL}</button>'
                f'<button class="p cut" data-l="{labels[tag]}／{k} 切り出し" '
                f'data-f="{k}_{tag}_cut.wav">▶ {k}</button>'
                f'<div class="ms">子音 {s["cons_ms"]}ms<br>{s["cons_db"]}dB</div></td>')
        note = f'<div class="nt">{notes[tag]}</div>' if tag in notes else ""
        cls = ' class="cur"' if tag == "amitaro" else ""
        rows.append(f'<tr{cls}><th>{labels[tag]}{note}</th>{"".join(cells)}</tr>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>ら行の弾き音・話者ちがいの聞き比べ</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:1120px}}
h1{{font-size:19px;margin:0 0 8px}}
p.note{{line-height:1.85;font-size:14px;max-width:900px}}
table{{border-collapse:collapse;margin-top:12px;width:100%}}
th,td{{border:1px solid #dde1ea;padding:7px;background:#fff;text-align:center;vertical-align:top}}
thead th{{background:#eef1f6;font-size:20px}}
tbody th{{text-align:left;font-size:13px;width:186px;background:#f7f8fb;line-height:1.5}}
tr.cur th{{background:#eef6f8}}
tr.cur td{{background:#fbfeff}}
button.p{{width:100%;font-size:12px;padding:5px 2px;border-radius:5px;cursor:pointer;
     border:1px solid #b9c0cf;font-weight:700;margin-bottom:3px}}
button.full{{background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.cut{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:10px;color:#7a8090;line-height:1.35;margin-top:2px}}
.nt{{font-size:10.5px;color:#8a6413;font-weight:400;margin-top:4px;line-height:1.5}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:14px;padding:5px 12px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin-right:4px}}
#now{{margin-left:10px;font-weight:700;font-size:15px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:11px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.85}}
</style>
<h1>ら行の弾き音・話者ちがいの聞き比べ</h1>
<p class="note">
「りさ」が「いさ」に聞こえる件で、<b>話者を変えれば直るのか</b>を確かめるページです。
上の紫のボタンが<b>切り出す前の「らさ」など全体</b>、下の青が<b>切り出した第1モーラ</b>。
「子音 ○ms」は、音が始まってから母音の大きさになるまでの時間（弾き音はここに出ます）。
</p>
<div class="box">
<b>先に分かっていること（機械で確認済み）</b><br>
① <b>音素列は正しい。</b>「りさ」の音素は <code>^ r i ] s a $</code> で /r/ は入っています。<br>
② <b>作り直しても音は変わりません。</b>同じ設定で合成し直すと、ら行5字とも
<b>バイト単位で現行と同一</b>でした（この表の2行目で耳でも確かめられます）。<br>
③ <b>弾き音が短いのはあみたろ固有ではありません。</b>他の話者でも 1〜26ms です。
しかも<b>人の録音の「り」は9msで、あみたろの16msより短い</b>——つまり
「子音部の長さ」だけでは説明がつきません。<br>
→ ですので<b>「人の録音」の行が基準</b>です。これがちゃんと「り」に聞こえて、
合成音が聞こえないなら、長さ以外の何か（弾き音の鋭さ・母音への渡り方）が違うことになります。
</div>
<div id="bar">
  <button id="allFull">▶ 各行の「らさ」を続けて</button>
  <button id="allCut">▶ 各行の切り出しを続けて</button>
  <button id="colRi">▶ 「り」だけ全話者</button>
  <button id="stop">■ 停止</button><span id="now"></span>
</div>
<table>
<thead><tr><th style="font-size:13px">話者・音源</th>{"".join(f"<th>{k}</th>" for k in KANA)}</tr></thead>
<tbody>
{"".join(rows)}
</tbody></table>
<script>
const DIR="compare_speakers/";
const KANA={json.dumps(KANA, ensure_ascii=False)};
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
    a.onended=()=>{{b.classList.remove("playing"); timer=setTimeout(next,540);}};
    a.onerror=()=>{{timer=setTimeout(next,120);}};
  }})();
}}
document.getElementById("allFull").onclick=()=>runList([...document.querySelectorAll("button.full")]);
document.getElementById("allCut").onclick=()=>runList([...document.querySelectorAll("button.cut")]);
document.getElementById("colRi").onclick=()=>{{
  const idx=KANA.indexOf("り");
  const out=[];
  document.querySelectorAll("tbody tr").forEach(tr=>{{
    const td=tr.querySelectorAll("td")[idx];
    if(td) td.querySelectorAll("button").forEach(b=>out.push(b));
  }});
  runList(out); }};
</script>
"""
    open(OUT, "w", encoding="utf-8").write(body)
    print(f"  バイト単位で同一だった字: {n_same}/{len(KANA)}")
    print(f"  {len(os.listdir(SND))-1} 本の音を書きました → {OUT}")


if __name__ == "__main__":
    main()
