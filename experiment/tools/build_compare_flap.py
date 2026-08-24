#!/usr/bin/env python3
"""
ら行の弾き音が聞こえるかを、音源ちがい・切り方ちがいで聞き比べるページを作る
============================================================================
2026-08-24 作成。

**きっかけ。** 刺激を聞いたユーザーから「『り』の子音（弾き音）が消えていて
『い』に聞こえる」という報告があった。本命8字に「ら」が入っているので致命的である。

**機械で調べた結果、切り落としではなかった。**
  ・合成音は発話の前が完全なデジタル無音なので、「最初に音が出る点」が真の onset に
    なる。それと検出値を全68字で突き合わせると、捨てているのは中央10ms・最大20msで、
    **その区間の最大音量は全字 -48dB 以下**（＝聞こえない立ち上がりのごく初期）だった。
  ・「り」の弾き音は onset の直後 0〜16ms に、ピーク比 -20dB で残っている。
  ・**自然音声と比べても弾き音の長さ・強さはほぼ同じ**（ら行5字で、長さの差 -24〜+8ms、
    強さは -20〜-25dB で同等）。つまり「合成音だから弾き音が弱い」わけではない。

**そこで、何が効いているのかを耳で切り分けるためのページ。** 同じ字について
次を並べる。

  1. あみたろ・切り出し後   … いま実験で使おうとしている刺激そのもの
  2. 自然音声・同じ長さで   … 同じ長さに切った録音。**合成音特有の問題かを見分ける決め手**
  3. 自然音声・録音のまま   … 語末の伸びも抑揚も入った、切っていない録音
  4. あみたろ・切り出し前   … 「らさ」の全体。文脈の中なら弾き音が聞こえるかを見る
  5. 弾き音のところだけ     … onset から30ms。弾き音そのものが鳴っているかの確認
  参考: 対応する母音（ら↔あ、り↔い…）。**これと区別が付かなければ子音が効いていない**

出力: experiment/tools/compare_flap.html
      音は experiment/tools/compare_flap/

使い方:
  python3 experiment/tools/build_compare_flap.py
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crop_carrier_stop import read_wav, write_wav, detect_onset_ms, apply_fade_out  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
B2 = os.path.join(ROOT, "experiment", "tts_candidates_carrier2")
REC = os.path.join(ROOT, "recordings_raw")
SND = os.path.join(ROOT, "experiment", "tools", "compare_flap")
OUT = os.path.join(ROOT, "experiment", "tools", "compare_flap.html")

PAIRS = [("ら", "あ"), ("り", "い"), ("る", "う"), ("れ", "え"), ("ろ", "お")]
LEAD_MS = 50.0
FLAP_MS = 30.0


def lead_cut(x, sr, onset_ms, dur_ms=None, fade=True):
    """onset の 50ms 手前から、必要なら dur_ms ぶんだけ切り出す。"""
    i0 = max(0, int(sr * (onset_ms - LEAD_MS) / 1000))
    if dur_ms is None:
        y = x[i0:]
    else:
        i1 = min(len(x), int(sr * (onset_ms + dur_ms) / 1000))
        y = x[i0:i1]
    return apply_fade_out(y.copy(), sr) if fade else y


def norm_to(x, target_rms=0.06, peak_cap=0.85):
    r = float(np.sqrt((x[np.abs(x) > np.abs(x).max() * 0.05] ** 2).mean() + 1e-20))
    g = target_rms / max(r, 1e-9)
    if np.abs(x).max() * g > peak_cap:
        g = peak_cap / (np.abs(x).max() + 1e-12)
    return x * g


def main():
    os.makedirs(SND, exist_ok=True)
    nat = {r["kana"]: r for r in
           json.load(open(os.path.join(REC, "adopted_onsets.json"), encoding="utf-8"))["adopted"]}
    info = {}
    kanas = [k for p in PAIRS for k in p]
    for k in kanas:
        rec = {}
        # 1. あみたろ・切り出し後（実験で使う刺激）
        xa, sra = read_wav(os.path.join(B2, "cut_さ", k + ".wav"))
        ona = detect_onset_ms(xa, sra)
        mora = len(xa) / sra * 1000.0 - ona
        write_wav(os.path.join(SND, f"{k}_amitaro.wav"), norm_to(lead_cut(xa, sra, ona)), sra)
        rec["mora_ms"] = round(mora, 1)
        # 1b. **捨てている区間を戻した版**。合成音は発話前が完全なデジタル無音なので、
        #     「最初に音が出るサンプル」が真の始まりになる。onset 検出はそこから
        #     中央10ms・最大20msを飛ばしているので、その分を戻して聞き比べられるようにする。
        #     弾き音そのものが16msしかない字があるため、20msの差は無視できない。
        nz = np.nonzero(np.abs(xa) > 1e-5)[0]
        true_on = (nz[0] / sra * 1000.0) if len(nz) else ona
        rec["discarded_ms"] = round(ona - true_on, 1)
        seg = xa[int(sra * true_on / 1000):int(sra * ona / 1000)]
        rec["discarded_peak_db"] = (round(float(20 * np.log10(
            np.abs(seg).max() / (np.abs(xa).max() + 1e-12) + 1e-12)), 1) if len(seg) else None)
        write_wav(os.path.join(SND, f"{k}_restored.wav"),
                  norm_to(lead_cut(xa, sra, true_on, mora + (ona - true_on))), sra)
        # 4. あみたろ・切り出し前（「らさ」の全体）
        xr, srr = read_wav(os.path.join(B2, "raw_さ", k + ".wav"))
        onr = detect_onset_ms(xr, srr)
        write_wav(os.path.join(SND, f"{k}_raw.wav"), norm_to(lead_cut(xr, srr, onr, fade=False)), srr)
        # 5. 弾き音のところだけ
        write_wav(os.path.join(SND, f"{k}_flap.wav"),
                  norm_to(lead_cut(xa, sra, ona, FLAP_MS)), sra)
        # 2/3. 自然音声
        r = nat.get(k)
        if r and os.path.exists(os.path.join(REC, r["file"])):
            xn, srn = read_wav(os.path.join(REC, r["file"]))
            onn = float(r["onset_ms"])
            write_wav(os.path.join(SND, f"{k}_nat_cut.wav"),
                      norm_to(lead_cut(xn, srn, onn, mora)), srn)
            write_wav(os.path.join(SND, f"{k}_nat_full.wav"),
                      norm_to(lead_cut(xn, srn, onn, fade=False)), srn)
            rec["nat_type"] = r.get("sound_type", "")
            rec["nat_note"] = r.get("onset_note", "")
            rec["nat_dur_ms"] = round(len(xn) / srn * 1000.0 - onn, 1)
        info[k] = rec
    with open(os.path.join(SND, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)

    def row(k, ref):
        i = info[k]
        b = lambda tag, label, cls: (
            f'<button class="p {cls}" data-k="{k}" data-l="{label}" '
            f'data-f="{k}_{tag}.wav">{label}</button>')
        return (
            f'<tr><th>{k}<div class="sub">対 {ref}</div></th>'
            f'<td>{b("amitaro", "あみたろ・切り出し後", "am")}'
            f'<div class="ms">{i["mora_ms"]:.0f}ms（実験で使う刺激）</div></td>'
            f'<td>{b("restored", "捨てた区間を戻した版", "rest")}'
            f'<div class="ms">頭に{i["discarded_ms"]:.0f}ms戻した'
            f'<br>その区間の最大 {i["discarded_peak_db"]}dB</div></td>'
            f'<td>{b("nat_cut", "自然音声・同じ長さ", "nat")}'
            f'<div class="ms">{i["mora_ms"]:.0f}ms</div></td>'
            f'<td>{b("nat_full", "自然音声・録音のまま", "nat2")}'
            f'<div class="ms">{i.get("nat_dur_ms", 0):.0f}ms</div></td>'
            f'<td>{b("raw", "あみたろ・切り出し前", "raw")}'
            f'<div class="ms">「{k}さ」全体</div></td>'
            f'<td>{b("flap", "子音のところだけ", "flap")}'
            f'<div class="ms">頭{FLAP_MS:.0f}ms</div></td>'
            f'<td class="refc">{b("amitaro", "　", "hidden")}</td></tr>')

    rows = []
    for k, ref in PAIRS:
        rows.append(row(k, ref))
        i = info[ref]
        rows.append(
            f'<tr class="ref"><th>{ref}<div class="sub">くらべる母音</div></th>'
            f'<td><button class="p am" data-k="{ref}" data-l="あみたろ・切り出し後" '
            f'data-f="{ref}_amitaro.wav">あみたろ・切り出し後</button>'
            f'<div class="ms">{i["mora_ms"]:.0f}ms</div></td>'
            f'<td><button class="p rest" data-k="{ref}" data-l="捨てた区間を戻した版" '
            f'data-f="{ref}_restored.wav">捨てた区間を戻した版</button></td>'
            f'<td><button class="p nat" data-k="{ref}" data-l="自然音声・同じ長さ" '
            f'data-f="{ref}_nat_cut.wav">自然音声・同じ長さ</button></td>'
            f'<td></td>'
            f'<td><button class="p raw" data-k="{ref}" data-l="あみたろ・切り出し前" '
            f'data-f="{ref}_raw.wav">あみたろ・切り出し前</button></td>'
            f'<td></td><td class="refc"></td></tr>')

    body = f"""<!doctype html><meta charset="utf-8">
<title>ら行の弾き音の聞き比べ</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:1100px}}
h1{{font-size:19px;margin:0 0 8px}}
p.note{{line-height:1.85;font-size:14px;max-width:880px}}
table{{border-collapse:collapse;margin-top:12px;width:100%}}
th,td{{border:1px solid #dde1ea;padding:7px 8px;text-align:center;vertical-align:top;
      background:#fff}}
thead th{{background:#eef1f6;font-size:12.5px;line-height:1.4}}
tbody th{{width:78px;font-size:22px;font-weight:700;background:#f7f8fb}}
tr.ref th{{font-size:18px;color:#666}}
tr.ref td{{background:#fbfbfd}}
.sub{{font-size:10.5px;color:#8a90a0;font-weight:400;margin-top:2px}}
button.p{{width:100%;font-size:11.5px;padding:6px 2px;border-radius:6px;cursor:pointer;
     border:1px solid #b9c0cf;font-weight:700;line-height:1.3}}
button.am{{background:#eef6f8;border-color:#2E7D8F;color:#1f5f6d}}
button.nat{{background:#eef7ef;border-color:#3d7a4a;color:#2b5c36}}
button.nat2{{background:#f4faf5;border-color:#7aa886;color:#3d6b48}}
button.rest{{background:#fff6e5;border-color:#b98a2a;color:#8a6413}}
button.raw{{background:#f4f1fb;border-color:#6b5bb5;color:#4a3f80}}
button.flap{{background:#fdf1ec;border-color:#b5502f;color:#8d3d23}}
button.hidden{{display:none}}
td.refc{{display:none}}
button.playing{{background:#1b2030!important;color:#fff!important;border-color:#1b2030!important}}
.ms{{font-size:10px;color:#7a8090;margin-top:4px}}
#bar{{position:sticky;top:0;background:#fff9db;border:1px solid #e0d090;border-radius:8px;
     padding:9px 13px;margin:10px 0;z-index:5}}
#bar button{{font-size:14px;padding:5px 12px;border-radius:6px;border:1px solid #99a;
     background:#fff;cursor:pointer;margin-right:4px}}
#now{{margin-left:10px;font-weight:700;font-size:15px}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:10px 14px;
     margin:12px 0;font-size:13.5px;line-height:1.8}}
</style>
<h1>ら行の弾き音（r）が聞こえるかの聞き比べ</h1>
<p class="note">
「『り』の子音が消えて『い』に聞こえる」というご報告を受けて作ったページです。<br>
<b>まず各行の左から順に押して、どこから「り」に聞こえ始めるかを確かめてください。</b>
そのあと、下の<b>くらべる母音</b>（り なら「い」）と聞き比べて、<b>区別が付くか</b>を見てください。
区別が付かなければ、子音の手がかりが効いていないことになります。<br>
<b>3つのどれなのかが、この並びで分かります。</b>
⑤の「切り出し前」の時点で変なら<b>合成そのものがおかしい</b>。
②の「戻した版」の方がよく聞こえるなら<b>切り出しが削りすぎ</b>。
①②⑤が同じで③だけちゃんと聞こえるなら<b>短く切って単独で聞かせることの限界</b>です。
</p>
<div class="box">
<b>機械で調べた結果（先にお伝えします）</b><br>
・<b>切り落としではありません。</b>onset より前に捨てている音は全68字で -48dB 以下（聞こえない立ち上がりのごく初期）だけでした。
「り」の弾き音は onset の直後 0〜16ms に、ピーク比 -20dB で残っています。<br>
・<b>自然音声と比べても、弾き音の長さ・強さはほぼ同じです。</b>
ら行5字で長さの差は -24〜+8ms、強さはどちらも -20〜-25dB でした。<br>
→ 機械の上では「切り落としではない」「合成音だから弱いとも言えない」となります。<br>
<b>ただし、この機械の判定は前回まちがえた前科があります。</b>捨てている区間は最大20msあり、
弾き音そのものが16msしかない字もあるので、「-48dB以下だから聞こえない」は
うのみにしないでください。<b>②で耳で確かめられるようにしてあります。</b>
</div>
<div id="bar">
  <button id="allRow">▶ 上から順に全部</button>
  <button id="allAm">▶ あみたろだけ続けて</button>
  <button id="allNat">▶ 自然音声（同じ長さ）だけ続けて</button>
  <button id="stop">■ 停止</button>
  <span id="now"></span>
</div>
<table>
<thead><tr><th>字</th>
<th>① あみたろ<br>切り出し後<br>（実験で使う刺激）</th>
<th>② 捨てた区間を<br>戻した版<br>★削りすぎ？</th>
<th>③ 自然音声<br>同じ長さに切ったもの<br>★合成のせい？</th>
<th>④ 自然音声<br>録音のまま</th>
<th>⑤ あみたろ<br>切り出し前<br>★合成が変？</th>
<th>⑥ 子音の<br>ところだけ</th>
<th></th></tr></thead>
<tbody>
{"".join(rows)}
</tbody></table>
<script>
const DIR="compare_flap/";
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
  play(b); }});
document.getElementById("stop").onclick=stop;
function runList(list){{ stop(); let i=0;
  (function next(){{ if(i>=list.length){{document.getElementById("now").textContent="おわり";return;}}
    const b=list[i++];
    document.getElementById("now").textContent=b.dataset.k+" ／ "+b.dataset.l+"（"+i+"/"+list.length+"）";
    const a=play(b);
    a.onended=()=>{{b.classList.remove("playing"); timer=setTimeout(next,520);}};
    a.onerror=()=>{{timer=setTimeout(next,120);}};
  }})();
}}
document.getElementById("allRow").onclick=()=>runList(
  [...document.querySelectorAll("tbody button.p")].filter(b=>!b.classList.contains("hidden")));
document.getElementById("allAm").onclick=()=>runList([...document.querySelectorAll("button.am")]);
document.getElementById("allNat").onclick=()=>runList([...document.querySelectorAll("button.nat")]);
</script>
"""
    open(OUT, "w", encoding="utf-8").write(body)
    print(f"  {len(kanas)} 字ぶん・{len(os.listdir(SND))-1} 本の音を書きました")
    print(f"  → {OUT}")


if __name__ == "__main__":
    main()
