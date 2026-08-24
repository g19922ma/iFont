#!/usr/bin/env python3
"""
「り」のアクセント指定を変えて合成し、弾き音の聞こえ方を比べる
==============================================================
2026-08-24 作成。

**きっかけ。** 「り」の弾き音（舌先で一瞬はじく音）が聞こえず「い」に聞こえる、
という報告。**切り出す前の「りさ」の時点ですでにおかしい**とのことなので、
切り出しや後続音ではなく**合成のさせ方**を疑う。

いちばん怪しいのは build_carrier_takes.py が入れている**アクセント核**である。
そこでは「対象モーラを目立たせる」ために第1モーラに核を置いている（accent=1）。
「りさ」の「り」を強く読ませることで、弾き音が不自然になっている可能性がある。

比べるもの
----------
  現行        … り=1・さ=0 を1つのアクセント句に（いまの刺激の作り方）
  核なし      … り=0・さ=0（平板）
  さ側に核    … り=0・さ=1
  エンジン既定 … 文字列「りさ」をそのまま渡したときにエンジンが決める形
                 （実測では「り」と「さ」が別のアクセント句に分かれる）
  旧「りん」   … 後続を「ん」にしていた頃の音源（切り出し済み）

各版について、**切り出す前の全体**と**切り出した第1モーラ**の両方を鳴らせるようにする。

出力: experiment/tools/compare_accent.html ／ experiment/tools/compare_accent/

使い方:
  python3 experiment/tools/build_compare_accent.py
  python3 experiment/tools/build_compare_accent.py --kana ら   # 別の字でも試せる
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
from crop_carrier_stop import read_wav, write_wav, detect_onset_ms, apply_fade_out  # noqa: E402
from crop_carrier_fricative import fricative_start  # noqa: E402
from build_carrier_takes import SPEAKER_UUID, STYLE_ID, SYNTH  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
SND = os.path.join(ROOT, "experiment", "tools", "compare_accent")
OUT = os.path.join(ROOT, "experiment", "tools", "compare_accent.html")
OLD = os.path.join(ROOT, "experiment", "tts_candidates_carrier", "あみたろ_norm")
BASE = "http://127.0.0.1:50032"
LEAD_MS = 50.0


def post(path, payload, raw=False):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return body if raw else json.loads(body)


def prosody(text):
    return post("/v1/estimate_prosody",
                {"speakerUuid": SPEAKER_UUID, "style_id": STYLE_ID, "text": text})


def synth(detail, text=""):
    payload = {"speakerUuid": SPEAKER_UUID, "styleId": STYLE_ID, "text": text,
               "prosodyDetail": detail}
    payload.update(SYNTH)
    wav = post("/v1/synthesis", payload, raw=True)
    with wave.open(io.BytesIO(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
        return x, w.getframerate()


def flap_metrics(x, sr, onset_ms, thr=-20.0):
    """onset から、音量がピーク比 thr を超えるまで＝子音部の長さと、その最大音量。"""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kana", default="り")
    ap.add_argument("--follower", default="さ")
    args = ap.parse_args()
    k, fol = args.kana, args.follower
    os.makedirs(SND, exist_ok=True)

    pk = prosody(k + "ん")["detail"][0][0]["phoneme"]
    pf = prosody(fol + "ん")["detail"][0][0]["phoneme"]
    one = lambda a1, a2: [[{"phoneme": pk, "hira": k, "accent": a1},
                           {"phoneme": pf, "hira": fol, "accent": a2}]]
    variants = [
        ("current", "現行（対象に核）", one(1, 0)),
        ("flat", "核なし（平板）", one(0, 0)),
        ("second", "後続側に核", one(0, 1)),
        ("engine", "エンジン既定", prosody(k + fol)["detail"]),
    ]
    rows = []
    for tag, label, detail in variants:
        x, sr = synth(detail, k + fol)
        on = detect_onset_ms(x, sr)
        b, _ = fricative_start(x, sr, on)
        mora = (b - on) if b else 110.0
        cl, lv = flap_metrics(x, sr, on)
        write_wav(os.path.join(SND, f"{tag}_full.wav"), norm_to(lead_cut(x, sr, on, fade=False)), sr)
        write_wav(os.path.join(SND, f"{tag}_cut.wav"), norm_to(lead_cut(x, sr, on, mora)), sr)
        rows.append({"tag": tag, "label": label, "mora_ms": round(mora, 1),
                     "cons_ms": cl, "cons_db": lv,
                     "accent": json.dumps(detail, ensure_ascii=False)})
        print(f"  {label:16s} 第1モーラ{mora:6.1f}ms  子音部{str(cl):>4}ms / {lv}dB")

    # 参考: 後続が「ん」だった頃の音源（切り出し済み）
    old = os.path.join(OLD, k + ".wav")
    if os.path.exists(old):
        x, sr = read_wav(old)
        on = detect_onset_ms(x, sr)
        cl, lv = flap_metrics(x, sr, on)
        write_wav(os.path.join(SND, "old_full.wav"), norm_to(lead_cut(x, sr, on, fade=False)), sr)
        write_wav(os.path.join(SND, "old_cut.wav"), norm_to(lead_cut(x, sr, on, 110.0)), sr)
        rows.append({"tag": "old", "label": "旧「りん」版", "mora_ms": None,
                     "cons_ms": cl, "cons_db": lv, "accent": "（当時の設定。核は対象モーラ）"})
        print(f"  {'旧「'+k+'ん」版':16s} 子音部{str(cl):>4}ms / {lv}dB")

    with open(os.path.join(SND, "info.json"), "w", encoding="utf-8") as f:
        json.dump({"kana": k, "follower": fol, "rows": rows}, f, ensure_ascii=False, indent=1)

    tr = []
    for r in rows:
        mora = f'{r["mora_ms"]:.0f}ms' if r["mora_ms"] else "—"
        tr.append(
            f'<tr><th>{r["label"]}</th>'
            f'<td><button class="p full" data-l="{r["label"]}／切り出し前" '
            f'data-f="{r["tag"]}_full.wav">▶ 切り出し前（{k}{fol}の全体）</button></td>'
            f'<td><button class="p cut" data-l="{r["label"]}／切り出し後" '
            f'data-f="{r["tag"]}_cut.wav">▶ 切り出した「{k}」</button></td>'
            f'<td class="n">{mora}</td>'
            f'<td class="n">{r["cons_ms"]}ms</td><td class="n">{r["cons_db"]}dB</td></tr>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>「{k}」のアクセント指定ちがいの聞き比べ</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:920px}}
h1{{font-size:19px;margin:0 0 8px}}
p.note{{line-height:1.85;font-size:14px}}
table{{border-collapse:collapse;margin-top:12px;width:100%}}
th,td{{border:1px solid #dde1ea;padding:8px;background:#fff;text-align:center}}
thead th{{background:#eef1f6;font-size:12.5px;line-height:1.4}}
tbody th{{text-align:left;font-size:13.5px;width:150px;background:#f7f8fb}}
td.n{{font-size:12.5px;color:#555;font-variant-numeric:tabular-nums;width:74px}}
button.p{{width:100%;font-size:12.5px;padding:8px 4px;border-radius:6px;cursor:pointer;
     border:1px solid #b9c0cf;font-weight:700}}
button.full{{background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.cut{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:14px;padding:5px 12px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin-right:4px}}
#now{{margin-left:10px;font-weight:700;font-size:15px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:10px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.8}}
</style>
<h1>「{k}」のアクセント指定ちがいの聞き比べ</h1>
<p class="note">
「{k}」の弾き音（舌先で一瞬はじく音）が聞こえない件で、<b>切り出す前の時点ですでにおかしい</b>
とのことでしたので、<b>合成のさせ方</b>を疑って作り直しました。<br>
刺激を作るとき、対象のモーラを目立たせるために<b>アクセント核</b>を置いています。
これが弾き音を不自然にしている可能性があるので、置き方を変えた版を並べます。<br>
<b>「切り出し前」を先に聞いて、「{k}{fol}」として自然に聞こえるものを選んでください。</b>
そのうえで「切り出した「{k}」」も確かめてください。
</p>
<div class="box">
<b>数字の見方</b>：「子音部の長さ」は、音が始まってから母音の大きさになるまでの時間です。
弾き音はここに出ます。短すぎたり弱すぎたりすると「い」に聞こえます。<br>
参考値：自然音声（人の録音）の「{k}」は <b>9ms・-22.6dB</b> でした。
</div>
<div id="bar">
  <button id="allFull">▶ 切り出し前を続けて</button>
  <button id="allCut">▶ 切り出した音を続けて</button>
  <button id="stop">■ 停止</button><span id="now"></span>
</div>
<table>
<thead><tr><th>アクセントの置き方</th><th>切り出す前</th><th>切り出した第1モーラ</th>
<th>第1モーラ<br>の長さ</th><th>子音部<br>の長さ</th><th>子音部<br>の最大</th></tr></thead>
<tbody>
{"".join(tr)}
</tbody></table>
<script>
const DIR="compare_accent/";
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
    a.onended=()=>{{b.classList.remove("playing"); timer=setTimeout(next,560);}};
    a.onerror=()=>{{timer=setTimeout(next,120);}};
  }})();
}}
document.getElementById("allFull").onclick=()=>runList([...document.querySelectorAll("button.full")]);
document.getElementById("allCut").onclick=()=>runList([...document.querySelectorAll("button.cut")]);
</script>
"""
    open(OUT, "w", encoding="utf-8").write(body)
    print(f"  → {OUT}")


if __name__ == "__main__":
    main()
