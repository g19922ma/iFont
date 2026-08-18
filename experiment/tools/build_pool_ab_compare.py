#!/usr/bin/env python3
"""
配り方の聴き比べページ(波形つき)を作る
======================================
1 モーラ 0.2 秒の中で子音と母音に時間をどう配るかの 2 案を、音と波形の両方で
突き合わせて合否を判定するためのページ experiment/tools/pool_ab_compare.html を生成する。

  方式1(現行の本番プール)  子音長は素の値のまま残し、母音長 = 0.2秒 - 子音長。
                           実装は two_char_audio/build_2char_pool.py の set_mora。
  方式2(候補プール uniform200) 子音長と母音長を同じ倍率で伸縮して合計を 0.2 秒にする。
                           実装は experiment/candidate_pools/uniform200/build_uniform200.py。

数値と図の出どころ
------------------
- 子音と母音の境目は、VOICEVOX に /audio_query で問い合わせた音素長を、各方式で配り直し、
  エンジンの格子(1/93.75 秒 = 10.6667 ミリ秒)に丸めた位置である。波形から目で拾った
  位置ではない。境目の求め方は build_gate_windows.phoneme_frames をそのまま使う。
- 波形は、公開されている mp3 を復号したもの。mp3 は復号すると先頭に符号化遅れ
  (1105 標本 = 46.042 ミリ秒)が入るので、モーラの実体の位置はその遅れを足して求める。
  この模型が実体と合っていることは build_gate_windows.py が 68 音すべてで検算済み。
- 縦軸(振幅)は全 26 図で共通。プールは音量をそろえてあるので、図どうしの高さの差は
  そのまま聞こえの大きさの差にあたる。横軸も全図共通で 0〜210 ミリ秒。

実行(VOICEVOX を 127.0.0.1:50021 で起動しておくこと):
  ~/ifont_env/bin/python experiment/tools/build_pool_ab_compare.py

出力:
  experiment/tools/pool_ab_compare.html          ページ本体
  experiment/tools/pool_ab_assets/<かな>_<方式>.png  波形図(26枚)
"""
import json
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# 図の中に日本語(「子音 117.3ms」など)を書くので、和文フォントを指定する。
# 指定しないと豆腐(□)になる。macOS 標準の Hiragino を使う。
matplotlib.rcParams["font.family"] = [
    "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic", "Noto Sans CJK JP", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import build_gate_windows as gw   # noqa: E402
import ifont_common as ic         # noqa: E402

ASSETS = os.path.join(HERE, "pool_ab_assets")
OUT_HTML = os.path.join(HERE, "pool_ab_compare.html")

SPEAKER = 108
MORA_DUR = 0.2
FRAME_MS = gw.FRAME_SAMPLES / gw.SR * 1000      # 10.6667 ミリ秒
X_MAX_MS = 210.0                                # 全図共通の横軸。最長のモーラ 202.67ms が収まる幅
EXCLUDE = set("をぢづゔ")                        # 出題から外す同音字

# 配色。experiment 側のページ(生成りの地に白いカード)に合わせる。
C_CONS = "#C98A16"       # 子音の帯(琥珀)
C_VOWEL = "#2E7D8F"      # 母音の帯(青緑)
C_WAVE = "#1b2030"       # 波形
C_ONSET = "#B03A2E"      # 再生の開始位置

METHODS = [
    dict(key="m1", label="方式1 現行本番", slot_mode="vowel",
         base=EXP, rel="..", votfix=os.path.join(EXP, "audio1char_votfix_B3_108.json"),
         pool_tag="cand108"),
    dict(key="m2", label="方式2 一様伸縮", slot_mode="uniform",
         base=os.path.join(EXP, "candidate_pools", "uniform200"),
         rel="../candidate_pools/uniform200",
         votfix=os.path.join(EXP, "candidate_pools", "uniform200",
                             "audio1char_votfix_B3u200_108.json"),
         pool_tag="uniform200"),
]


# --------------------------------------------------------------------------
# プールを読む
# --------------------------------------------------------------------------
def load_pool(m):
    """1つのプールについて かな -> (manifest の刺激, onsets の実測, 子音長, 母音長) を集める。"""
    manifest = json.load(open(os.path.join(m["base"], "audio1char_manifest.json")))
    onsets = json.load(open(os.path.join(m["base"], "audio1char_onsets.json")))
    onsets.pop("_meta", None)
    akey = json.load(open(os.path.join(EXP, "answer_key_merged.json")))
    cmul = json.load(open(m["votfix"]))

    id2ch = {k.split("|")[1]: v["char"] for k, v in akey.items()
             if k.startswith("audio1char|") and v.get("pool") == m["pool_tag"]}
    out = {}
    for s in manifest["stimuli"]:
        ch = id2ch.get(s["id"])
        if ch is None:
            sys.exit(f"[{m['key']}] かなの対応が取れない刺激がある: {s['id']}")
        if ch in gw.OPPO_SPLICE:
            # 「ぽ」は「オッポ」の文脈合成から切り出した音。配り方の規則を通らないので、
            # 切り出しに使った子音長(0.06 秒)をそのまま境目として扱う。
            cons_ms = gw.OPPO_CONSONANT_S * 1000
            vowel_ms = MORA_DUR * 1000 - cons_ms
            pre_ms = 0.1 * 1000                       # Python 側で作った前余白(量子化なし)
        else:
            fc, fv = gw.phoneme_frames(ch, SPEAKER, cmul.get(ch), MORA_DUR, m["slot_mode"])
            cons_ms, vowel_ms = fc * FRAME_MS, fv * FRAME_MS
            pre_ms = gw.PRE_FRAMES * gw.FRAME_SAMPLES / gw.SR * 1000   # 96.0 ミリ秒
        out[ch] = dict(stim=s, ons=onsets[ch], cons_ms=cons_ms, vowel_ms=vowel_ms,
                       pre_ms=pre_ms, file=s["file"],
                       vol=akey[f"audio1char|{s['id']}"].get("vol_scale"))
    return out


# --------------------------------------------------------------------------
# 並べる音を決める
# --------------------------------------------------------------------------
def pick_rows(p1, p2):
    """判定に要る音だけを選び、(かな, 見出し, 説明) の並びを返す。変化の大きい順。"""
    chars = [c for c in ic.AUDIO_ALL if c not in EXCLUDE and c in p1 and c in p2]
    # 差は格子(10.6667 ミリ秒)の整数倍にしかならない。丸めずに比べると、同じ差のはずの音が
    # 浮動小数点の誤差で順位を入れ替えてしまう(は と け が入れ替わる)ので、3桁で丸める。
    dv = {c: round(p2[c]["vowel_ms"] - p1[c]["vowel_ms"], 3) for c in chars}
    dc = {c: round(p2[c]["cons_ms"] - p1[c]["cons_ms"], 3) for c in chars}

    rows, seen = [], set()

    def add(ch, group, why):
        if ch in seen:
            return False
        seen.add(ch)
        rows.append(dict(ch=ch, group=group, why=why))
        return True

    # 1. 母音長の変化が大きい順トップ8
    top = sorted(chars, key=lambda c: (-abs(dv[c]), -abs(dc[c]), ic.AUDIO_ALL.index(c)))[:8]
    for ch in top:
        add(ch, "変化が大きい8音",
            f"母音が {dv[ch]:+.1f} ミリ秒、子音が {dc[ch]:+.1f} ミリ秒動く")

    # 2. 変化のない代表
    add("つ", "変化のない音",
        "素のモーラ長がほぼ 0.2 秒なので、どちらの方式でも配分が同じになる")
    add("ぽ", "変化のない音",
        "「オッポ」の文脈合成から切り出す処方で、配り方の規則をそもそも通らない。"
        "時間の配分は2つのプールでまったく同じ")

    # 3. 各方式で母音が最短・最長の音
    for m, pool, name in ((1, p1, "方式1"), (2, p2, "方式2")):
        lo = min(chars, key=lambda c: (pool[c]["vowel_ms"], ic.AUDIO_ALL.index(c)))
        hi = max(chars, key=lambda c: (pool[c]["vowel_ms"], -ic.AUDIO_ALL.index(c)))
        for ch, kind in ((lo, "最短"), (hi, "最長")):
            tie = [c for c in chars
                   if abs(pool[c]["vowel_ms"] - pool[ch]["vowel_ms"]) < 0.5 and c != ch]
            why = f"{name}で母音が{kind}({pool[ch]['vowel_ms']:.1f} ミリ秒)"
            if tie:
                why += f"。同じ長さの音が他に {len(tie)} 音ある({'・'.join(tie[:6])}"
                why += "…)" if len(tie) > 6 else ")"
            if not add(ch, "母音の両端", why):
                # すでに上の枠で出ている音。行は増やさず、理由だけ書き足す
                for r in rows:
                    if r["ch"] == ch:
                        r["why"] += "。" + why

    # 4. 参考: 母音が縮む2音
    for ch in sorted([c for c in chars if dv[c] < -0.5],
                     key=lambda c: (dv[c], ic.AUDIO_ALL.index(c))):
        add(ch, "参考: 母音が縮む音",
            f"素のモーラ長が 0.2 秒より短く、伸ばす側にあたる音。母音が {dv[ch]:+.1f} ミリ秒")

    for r in rows:
        r["dv"], r["dc"] = dv[r["ch"]], dc[r["ch"]]
    return rows


# --------------------------------------------------------------------------
# 波形図
# --------------------------------------------------------------------------
def mora_wave(rec, base_dir):
    """mp3 を復号し、モーラの実体の区間だけを取り出す。(波形, 標本化周波数) を返す。"""
    x, fr = gw.decode_mp3(os.path.join(base_dir, "audio1char_stimuli", rec["file"]))
    start_ms = rec["pre_ms"] + gw.CODEC_DELAY_SAMPLES / gw.SR * 1000
    end_ms = start_ms + rec["cons_ms"] + rec["vowel_ms"]
    return x[int(round(start_ms / 1000 * fr)): int(round(end_ms / 1000 * fr))], fr


def draw(ch, rec, seg, fr, ylim, path):
    fig, ax = plt.subplots(figsize=(4.6, 1.55), dpi=150)
    t = np.arange(len(seg)) / fr * 1000
    cons, vowel = rec["cons_ms"], rec["vowel_ms"]

    # 子音・母音の帯
    if cons > 0:
        ax.add_patch(Rectangle((0, -ylim), cons, 2 * ylim, color=C_CONS, alpha=0.20, lw=0))
    ax.add_patch(Rectangle((cons, -ylim), vowel, 2 * ylim, color=C_VOWEL, alpha=0.16, lw=0))
    if cons > 0:
        ax.axvline(cons, color=C_CONS, lw=1.2, ls="--", alpha=0.9)

    ax.plot(t, seg, color=C_WAVE, lw=0.45, alpha=0.85)
    ax.axhline(0, color="#9aa1b5", lw=0.4)

    # 再生の開始位置(音響的な立ち上がり)。実験ではここから鳴らす。
    on = rec["ons"].get("acoustic_onset_ms")
    if on is not None:
        on_rel = on + rec["stim"]["char_onset_s"] * 1000 - \
            (rec["pre_ms"] + gw.CODEC_DELAY_SAMPLES / gw.SR * 1000)
        if 0 < on_rel < cons + vowel:
            ax.axvline(on_rel, color=C_ONSET, lw=0.9, ls=":", alpha=0.85)
            ax.text(on_rel + 2, ylim * 0.80, "再生開始", fontsize=5.6, color=C_ONSET, va="top")

    # 区間の長さの表示
    if cons > 0:
        # 子音の帯が狭い音(ら行など、10〜30ミリ秒)は帯の中央に文字を置くと左へはみ出して
        # 切れてしまうので、帯の右外に左揃えで出す。
        if cons >= 45:
            ax.text(cons / 2, -ylim * 0.80, f"子音 {cons:.1f}ms", fontsize=6.6, color="#8A5A00",
                    ha="center", va="bottom", fontweight="bold")
        else:
            ax.text(cons + 4, -ylim * 0.80, f"子音 {cons:.1f}ms", fontsize=6.6, color="#8A5A00",
                    ha="left", va="bottom", fontweight="bold")
    ax.text(cons + vowel / 2, -ylim * 0.80, f"母音 {vowel:.1f}ms", fontsize=6.6,
            color="#1B5C69", ha="center", va="bottom", fontweight="bold")
    ax.text(cons + vowel, ylim * 0.86, f"モーラ {cons + vowel:.1f}ms ", fontsize=6.0,
            color="#6b7280", ha="right", va="top")

    ax.set_xlim(0, X_MAX_MS)
    ax.set_ylim(-ylim, ylim)
    ax.set_yticks([])
    ax.set_xticks([0, 50, 100, 150, 200])
    ax.tick_params(labelsize=6, length=2, colors="#6b7280")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#d8d3c6")
    ax.set_xlabel("モーラの先頭からの時間 (ミリ秒)", fontsize=6, color="#6b7280", labelpad=1)
    fig.subplots_adjust(left=0.015, right=0.995, top=0.97, bottom=0.30)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------
# ページ
# --------------------------------------------------------------------------
STYLE = """
  :root { color-scheme: light; }
  body { font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",system-ui,sans-serif; margin:0;
         background:#f6f4ef; color:#1b2030; }
  #app { max-width: 1040px; margin:0 auto; padding:24px 20px 60px; }
  .card { background:#fff; border:1px solid #e6e1d6; border-radius:14px; padding:22px;
          box-shadow:0 1px 0 rgba(0,0,0,.03), 0 10px 28px rgba(46,125,143,.08); margin-bottom:18px; }
  h1,h2,h3 { font-family:"Hiragino Mincho ProN","Yu Mincho",serif; letter-spacing:.04em; color:#1E2A5E; }
  h1 { font-size:21px; border-bottom:1px solid #e9e4d8; padding-bottom:10px; margin:0 0 14px; }
  h2 { font-size:15px; margin:26px 0 10px; color:#8A5A00; letter-spacing:.08em; }
  h3 { font-size:17px; margin:0; }
  p { line-height:1.85; font-size:14px; }
  .muted { color:#6b7280; font-size:13px; }
  .row { display:grid; grid-template-columns:64px 1fr 1fr; gap:14px; align-items:start;
         padding:16px 0; border-top:1px solid #efeade; }
  .row:first-of-type { border-top:0; }
  .kana { font-family:"Hiragino Mincho ProN","Yu Mincho",serif; font-size:40px; line-height:1;
          color:#1E2A5E; text-align:center; padding-top:6px; }
  .kana small { display:block; font-family:system-ui,sans-serif; font-size:10px; color:#6b7280;
                margin-top:8px; letter-spacing:.04em; line-height:1.5; }
  .cell { min-width:0; }
  .cell img { width:100%; display:block; border:1px solid #eae5d8; border-radius:8px; background:#fff; }
  .head { display:flex; align-items:baseline; gap:10px; margin-bottom:6px; flex-wrap:wrap; }
  .tag { font-size:11px; letter-spacing:.06em; padding:2px 8px; border-radius:999px;
         background:#eef4f5; color:#1B5C69; border:1px solid #d8e6e9; }
  .tag.now { background:#fdf3e0; color:#8A5A00; border-color:#efdfc0; }
  .nums { font-size:12px; color:#6b7280; }
  .nums b { color:#1b2030; font-weight:600; }
  button.play, button.pair { font-size:14px; padding:7px 18px; border-radius:999px; border:0;
                background:#2E7D8F; color:#fff; cursor:pointer; letter-spacing:.02em;
                transition:filter .15s; }
  button.pair { background:#1E2A5E; font-size:13px; padding:6px 16px; margin-left:8px; }
  button.play:hover, button.pair:hover { filter:brightness(1.12); }
  button.play:disabled { background:#b9c2c9; cursor:default; }
  .why { font-size:12px; color:#6b7280; margin:0 0 10px; grid-column:2 / 4; line-height:1.7; }
  .legend { display:flex; gap:18px; flex-wrap:wrap; font-size:12px; color:#6b7280; margin-top:6px; }
  .sw { display:inline-block; width:22px; height:10px; border-radius:2px; vertical-align:-1px; margin-right:5px; }
  table { border-collapse:collapse; font-size:13px; margin-top:8px; }
  td,th { border:1px solid #e3e6ee; padding:5px 10px; text-align:left; }
  th { background:#faf8f3; font-weight:600; }
"""

SCRIPT = r"""
let ctx = null;
const bufs = {};
function ensureCtx(){ if(!ctx) ctx = new (window.AudioContext||window.webkitAudioContext)(); return ctx; }
// 実験と同じ鳴らし方: 音響的な立ち上がりからモーラ末尾までを切り出し、
// 音量をそろえる増幅率を掛け、両端に 8 ミリ秒のフェードをかける。
async function play(btn){
  const d = JSON.parse(btn.dataset.clip);
  btn.disabled = true;
  try {
    if(!bufs[d.file]){
      const r = await fetch(d.file);
      if(!r.ok) throw new Error("音声が読めない: " + d.file);
      bufs[d.file] = await ensureCtx().decodeAudioData(await r.arrayBuffer());
    }
    const src = bufs[d.file], sr = src.sampleRate, c = ensureCtx();
    await c.resume();
    const start = Math.floor((d.char_onset_s + d.onset_ms/1000) * sr);
    const n = Math.max(1, Math.floor(d.avail_ms/1000 * sr));
    const out = c.createBuffer(1, n, sr);
    const a = src.getChannelData(0), b = out.getChannelData(0);
    for(let i=0;i<n;i++) b[i] = (a[start+i] || 0) * d.gain;
    const nf = Math.min(Math.floor(0.008*sr), n>>1);
    for(let i=0;i<nf;i++){ b[i]*=i/nf; b[n-1-i]*=i/nf; }
    const s = c.createBufferSource(); s.buffer = out; s.connect(c.destination); s.start();
    s.onended = () => { btn.disabled = false; };
  } catch(e){
    btn.disabled = false;
    btn.textContent = "再生できない";
    console.error(e);
  }
}
document.addEventListener("click", e => {
  const b = e.target.closest("button.play");
  if(b) play(b);
});
// 行の左右を続けて鳴らす(方式1 -> 0.7秒あけて -> 方式2)
document.addEventListener("click", e => {
  const b = e.target.closest("button.pair");
  if(!b) return;
  const row = b.closest(".rowwrap");
  const btns = row.querySelectorAll("button.play");
  play(btns[0]);
  setTimeout(() => play(btns[1]), 700);
});
"""


def clip_json(rec, rel):
    return json.dumps(dict(
        file=f"{rel}/audio1char_stimuli/{rec['file']}",
        char_onset_s=rec["stim"]["char_onset_s"],
        onset_ms=rec["ons"]["acoustic_onset_ms"],
        avail_ms=rec["ons"]["mora_avail_ms"],
        gain=rec["ons"]["gain"],
    ), ensure_ascii=False).replace('"', "&quot;")


def main():
    os.makedirs(ASSETS, exist_ok=True)
    pools = {m["key"]: load_pool(m) for m in METHODS}
    p1, p2 = pools["m1"], pools["m2"]
    rows = pick_rows(p1, p2)
    print(f"並べる音 {len(rows)} 行: " + "・".join(r["ch"] for r in rows), file=sys.stderr)

    # 先に全部の波形を取り出し、縦軸(振幅)の共通の上限を決める
    waves = {}
    for r in rows:
        for m in METHODS:
            rec = pools[m["key"]][r["ch"]]
            waves[(r["ch"], m["key"])] = mora_wave(rec, m["base"])
    ylim = max(float(np.abs(w).max()) for w, _ in waves.values()) * 1.08
    print(f"縦軸の共通上限 = {ylim:.3f}", file=sys.stderr)

    # 音量をそろえる倍率のずれ。プール全体の中央値を基準に決まるので、時間の配分が同じ音でも
    # まったく同じ波形にはならない。どのくらいの差なのかを本文に書くために測っておく。
    # 配分そのものが変わった音は、聞こえの大きさが実際に変わるので倍率も変わって当たり前である。
    # ここで知りたいのは「配分が同じなのに波形が一致しない」ぶんなので、配分が同じ音だけで測る。
    same = [c for c in p1 if c in p2 and p1[c].get("vol") and p2[c].get("vol")
            and round(p1[c]["cons_ms"] - p2[c]["cons_ms"], 3) == 0
            and round(p1[c]["vowel_ms"] - p2[c]["vowel_ms"], 3) == 0]
    dbs = {c: 20 * math.log10(p2[c]["vol"] / p1[c]["vol"]) for c in same}
    max_db_ch = max(dbs, key=lambda c: abs(dbs[c]))
    max_db = abs(dbs[max_db_ch])
    print(f"配分が同じ {len(same)} 音での音量倍率のずれ: 最大 {max_db:.3f} dB ({max_db_ch})",
          file=sys.stderr)

    for r in rows:
        for m in METHODS:
            seg, fr = waves[(r["ch"], m["key"])]
            path = os.path.join(ASSETS, f"{r['ch']}_{m['key']}.png")
            draw(r["ch"], pools[m["key"]][r["ch"]], seg, fr, ylim, path)

    # --- HTML ---
    h = []
    h.append("<!DOCTYPE html>\n<html lang=\"ja\">\n<head>")
    h.append('<meta charset="utf-8">')
    h.append('<meta name="robots" content="noindex,nofollow">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    h.append("<title>配り方の聴き比べ: 現行本番(方式1) と 一様伸縮(方式2)</title>")
    h.append(f"<style>{STYLE}</style>\n</head>\n<body>\n<div id=\"app\">")

    h.append('<div class="card">')
    h.append("<h1>1モーラ0.2秒の配り方: 現行本番（方式1）と一様伸縮（方式2）の聴き比べ</h1>")
    h.append(
        "<p><b>各行の左右を聴き比べ、どちらの音か分かるか・不自然でないかを判定してください。</b>"
        "左が現行の本番プール（方式1）、右が候補プール uniform200（方式2）です。"
        "話者・音高・音量のそろえ方・鳴らす区間の決め方はすべて同じで、"
        "<b>1モーラ0.2秒の中で子音と母音に時間をどう配るかだけ</b>が違います。"
        "方式1は子音の長さを合成器が返した値のまま残して母音で0.2秒に帳尻を合わせるので、"
        "子音の長い摩擦音では母音が痩せます。方式2は子音と母音を同じ倍率で伸縮するので、"
        "合成器が出した自然な比がそのまま保たれます。</p>")
    h.append(
        '<p class="muted">再生は実験本番とまったく同じ処理です'
        "（音響的な立ち上がりからモーラ末尾まで・音量をそろえる増幅つき・両端8ミリ秒のフェード）。"
        "「続けて鳴らす」を押すと方式1→0.7秒あけて→方式2の順に鳴ります。"
        "図の横軸は全図共通で0〜210ミリ秒、縦軸（振幅）も全図共通なので、"
        "図どうしの波の高さの差はそのまま聞こえの大きさの差にあたります。</p>")
    h.append('<div class="legend">'
             f'<span><span class="sw" style="background:{C_CONS};opacity:.35"></span>子音の区間</span>'
             f'<span><span class="sw" style="background:{C_VOWEL};opacity:.30"></span>母音の区間</span>'
             f'<span><span class="sw" style="background:{C_ONSET}"></span>再生の開始位置'
             "（音響的な立ち上がり）</span></div>")
    h.append(
        '<p class="muted" style="margin-top:14px">子音と母音の境目は、合成器に問い合わせた音素長を'
        "各方式で配り直し、合成器の格子（10.6667ミリ秒）に丸めた位置です。"
        "波形から目で拾った位置ではありません。モーラの合計が0.2秒ちょうどにならないのは、"
        "子音と母音が別々に丸められるためで、これは方式1でも同じです。</p>")
    h.append(
        '<p class="muted">なお、時間の配分が同じ音（つ・ぽ・あ など）でも、'
        "2つの波形は完全には一致しません。音量をそろえる倍率がプール全体の中央値を基準に決まり、"
        "プールの中身が変われば中央値もわずかに動くためです。"
        f"配分の同じ{len(same)}音で測った差は最大 {max_db:.2f} デシベル（{max_db_ch}）で、"
        "聞き分けられる大きさではありません。"
        "配分そのものが変わった音は、聞こえの大きさが実際に変わるので倍率も変わります。</p>")
    h.append("</div>")

    group = None
    for r in rows:
        ch = r["ch"]
        if r["group"] != group:
            group = r["group"]
            h.append(f'<h2>{group}</h2>')
        h.append('<div class="card rowwrap">')
        h.append('<div class="row">')
        h.append(f'<div class="kana">{ch}<small>母音 {r["dv"]:+.1f}<br>子音 {r["dc"]:+.1f}<br>ミリ秒</small></div>')
        for m in METHODS:
            rec = pools[m["key"]][ch]
            tag = "tag now" if m["key"] == "m1" else "tag"
            h.append('<div class="cell">')
            h.append('<div class="head">')
            h.append(f'<h3>{m["label"]}</h3><span class="{tag}">'
                     f'{"いま本番で使っている音" if m["key"] == "m1" else "候補 uniform200"}</span>')
            h.append("</div>")
            h.append(f'<div class="nums">子音 <b>{rec["cons_ms"]:.1f}</b> ミリ秒 ／ '
                     f'母音 <b>{rec["vowel_ms"]:.1f}</b> ミリ秒 ／ '
                     f'モーラ {rec["cons_ms"] + rec["vowel_ms"]:.1f} ミリ秒</div>')
            h.append(f'<img src="pool_ab_assets/{ch}_{m["key"]}.png" '
                     f'alt="{ch} の波形（{m["label"]}）">')
            h.append(f'<p style="margin:8px 0 0"><button class="play" '
                     f'data-clip="{clip_json(rec, m["rel"])}">▶ 鳴らす</button> '
                     f'<span class="muted">実際に鳴る長さ {rec["ons"]["mora_avail_ms"]:.0f} ミリ秒</span></p>')
            h.append("</div>")
        h.append("</div>")
        # 「続けて鳴らす」に class="play" を付けてはいけない。単体再生のハンドラにも当たり、
        # data-clip の無いボタンで JSON.parse("undefined") が投げられる(2026-08-18 に踏んだ)。
        h.append(f'<p class="why" style="margin-top:2px">{r["why"]}。'
                 '<button class="pair">続けて鳴らす</button></p>')
        h.append("</div>")

    h.append('<div class="card"><h2 style="margin-top:0">この表の見かた</h2>')
    h.append("<table><tr><th>言葉</th><th>意味</th></tr>"
             "<tr><td>モーラ</td><td>かな1文字ぶんの音。ここでは0.2秒に固定している</td></tr>"
             "<tr><td>子音の区間</td><td>「し」なら [ɕ] の摩擦、「た」なら破裂までの部分</td></tr>"
             "<tr><td>母音の区間</td><td>声帯が鳴っている部分。ここが痩せると音色が確かめにくくなる</td></tr>"
             "<tr><td>再生の開始位置</td><td>実験では無音を飛ばし、レベルが一定値を超え続ける"
             "最初の点から鳴らす</td></tr>"
             "<tr><td>実際に鳴る長さ</td><td>再生の開始位置からモーラ末尾まで。"
             "立ち上がりの遅い音ほど短くなる</td></tr></table>")
    h.append('<p class="muted" style="margin-top:14px">'
             "68音すべての数値は <code>project/子音母音配分_方式比較.md</code>。"
             "68音を1音ずつ聴くなら "
             '<a href="../pilot_soa_audio.html?check=1">現行（方式1）の点検モード</a> と '
             '<a href="../pilot_soa_audio.html?pool=uniform200&amp;check=1">'
             "方式2の点検モード</a>。</p></div>")

    h.append(f"</div>\n<script>{SCRIPT}</script>\n</body>\n</html>")
    open(OUT_HTML, "w").write("\n".join(x for x in h if x))
    print(f"書き出し: {OUT_HTML}", file=sys.stderr)
    print(f"          {ASSETS}/ に波形図 {len(rows) * 2} 枚", file=sys.stderr)


if __name__ == "__main__":
    main()
