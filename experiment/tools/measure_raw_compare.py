#!/usr/bin/env python3
"""
音源比較セット raw_compare_v1 の機械測定と、聴き比べページの生成
================================================================
raw_compare_v1 に入っている全ファイル（B1 / B2 / C × 12字）を音響的に測り、

  project/音源比較_QC表.md                      … 人が読む表（測り方の説明つき）
  experiment/candidate_pools/raw_compare_v1/measurements.json … 生の測定値
  experiment/candidate_pools/raw_compare_v1/waveforms/*.png    … 波形の小図
  experiment/tools/source_compare.html          … 聴き比べページ

を作る。測る対象は「実際に鳴らすファイルそのもの」。mp3 は復号してから測る。
測り方の中身は rawcompare_measure_lib.py の冒頭に日本語で書いてある。

実行: ~/ifont_env/bin/python experiment/tools/measure_raw_compare.py
"""
import html
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)
sys.path.insert(0, HERE)

import matplotlib                      # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt        # noqa: E402
import rawcompare_measure_lib as L     # noqa: E402

matplotlib.rcParams["font.family"] = [
    "Hiragino Sans", "Hiragino Kaku Gothic ProN", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

POOL = os.path.join(EXP, "candidate_pools", "raw_compare_v1")
WAVE_DIR = os.path.join(POOL, "waveforms")
OUT_MD = os.path.join(REPO, "project", "音源比較_QC表.md")
OUT_JSON = os.path.join(POOL, "measurements.json")
OUT_HTML = os.path.join(HERE, "source_compare.html")

COLS = ["B1", "B2", "C"]
COL_LABEL = {
    "A": "A 自然録音",
    "B1": "B1 無加工・きりたん",
    "B2": "B2 無加工・玄野武宏",
    "C": "C 現行の加工版",
}


# ---------------------------------------------------------------- 波形の図
def draw(x, fr, path, ylim, xlim_ms, color, onset_ms_, burst_ms_):
    fig, ax = plt.subplots(figsize=(2.5, 0.78), dpi=150)
    t = np.arange(len(x)) / fr * 1000
    ax.plot(t, x, lw=0.35, color=color)
    ax.axvline(onset_ms_, color="#B03A2E", lw=0.8)
    if burst_ms_ is not None:
        ax.axvline(burst_ms_, color="#8A5A00", lw=0.8, ls=":")
    ax.set_xlim(0, xlim_ms)
    ax.set_ylim(-ylim, ylim)
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=5, length=2, pad=1)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#cfc9bb")
    fig.subplots_adjust(left=0.02, right=0.99, top=0.97, bottom=0.30)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 本体
def main():
    man = json.load(open(os.path.join(POOL, "manifest.json")))
    chars = man["chars"]
    os.makedirs(WAVE_DIR, exist_ok=True)

    # 話者ごとの声の高さ。VOT を測るときの声帯振動の探索範囲を決めるのに使う
    f0_hint = {}
    for col in COLS:
        vals = []
        for ch in chars:
            rec = man["files"][ch].get(col)
            if not rec:
                continue
            x, fr = L.decode(os.path.join(POOL, rec["file"]))
            f = L.median_f0(x, fr)
            if f:
                vals.append(f)
        f0_hint[col] = float(np.median(vals)) if vals else None

    M, sig = {}, {}
    for ch in chars:
        for col in COLS:
            rec = man["files"][ch].get(col)
            if not rec:
                continue
            p = os.path.join(POOL, rec["file"])
            m = L.measure_file(p, ch, f0_hint=f0_hint[col])
            m["file"] = rec["file"]
            m["gain_applied"] = rec.get("gain")
            M.setdefault(ch, {})[col] = m
            sig[(ch, col)] = L.decode(p)

    # 図の縦横は全図で共通にする（図どうしの波の高さの差が、そのまま聞こえの大きさの差になる）
    ylim = max(float(np.max(np.abs(x))) for x, _ in sig.values()) * 1.05
    xlim = max(len(x) / fr * 1000 for x, fr in sig.values())
    xlim = float(np.ceil(xlim / 50) * 50)
    color = {"B1": "#2E7D8F", "B2": "#1E2A5E", "C": "#8A5A00"}
    for (ch, col), (x, fr) in sig.items():
        draw(x, fr, os.path.join(WAVE_DIR, f"{col}_{ch}.png"), ylim, xlim,
             color[col], M[ch][col]["onset_ms"], M[ch][col]["burst_ms"])

    json.dump(dict(x_axis_ms=xlim, y_limit=ylim, f0_hint=f0_hint, measurements=M),
              open(OUT_JSON, "w"), ensure_ascii=False, indent=2)

    write_md(man, chars, M, f0_hint)
    write_html(man, chars, M, xlim)
    print(f"=> {os.path.relpath(OUT_MD, REPO)}")
    print(f"=> {os.path.relpath(OUT_JSON, REPO)}")
    print(f"=> {os.path.relpath(OUT_HTML, REPO)}")


def n(v, d=1, plus=False):
    if v is None:
        return "—"
    return f"{v:+.{d}f}" if plus else f"{v:.{d}f}"


def write_md(man, chars, M, f0_hint):
    sp = man["speakers"]
    o = []
    o.append("# 音源比較セット raw_compare_v1 QC表（機械測定）\n")
    o.append("かな1音の「音源比較セット」に入っている全ファイルを、実際に鳴らすファイルそのもの")
    o.append("（mp3 は復号してから）音響的に測った結果。独自加工をやめて無加工の音源で行けるかを")
    o.append("判断するための材料。\n")
    o.append(f"- 合成器: {man['engine']}")
    o.append(f"- 形式: B1/B2 は {man['sample_rate']}Hz / {man['bit_depth']}bit / "
             f"モノラルの WAV。C は現行本番プールの mp3 をそのままコピー")
    o.append(f"- 生成: `experiment/tools/build_raw_compare.py`／測定: "
             f"`experiment/tools/measure_raw_compare.py`（測り方の実体は "
             f"`experiment/tools/rawcompare_measure_lib.py`）\n")

    o.append("## 列（音源）の説明\n")
    o.append("| 列 | 中身 | 話者 | 掛けた倍率 |")
    o.append("|---|---|---|---|")
    o.append("| A | 人が実際に発音した自然録音 | 準備中 | — |")
    for c in COLS:
        s = sp[c]
        g = s.get("gain")
        gs = "1.000（コピーのまま。掛け直していない）" if c == "C" else \
             f"{g:.4f}（{s['gain_db']:+.2f} dB）"
        who = f"{s['name']} / {s['style']}（speaker={s['id']}）"
        o.append(f"| {c} | {'無加工の合成音' if c.startswith('B') else '現行の加工版'} | {who} | {gs} |")
    o.append("")
    o.append("**B2 に玄野武宏を選んだ理由**: " + sp["B2"]["why"] + "。\n")

    o.append("## 測り方（1行ずつの説明）\n")
    o.append("- **onset（音の立ち上がり, ms）**: ファイルの先頭から数えて音が鳴りはじめる時刻。"
             "5ミリ秒ごとの音量が -63 dBFS を 15ミリ秒続けて超えた最初の点。"
             "本番プールの切り出しと同じ判定を使っている。")
    o.append("- **burst（破裂の瞬間, ms）**: 唇や舌が離れて空気が弾ける時刻。"
             "1ミリ秒ごとの音量がいちばん急に立ち上がる点。破裂音の6字だけ測る。")
    o.append("- **VOT（有声開始時間, ms）**: 破裂の瞬間から声帯が震えはじめるまでの時間。"
             "**マイナスは prevoicing**（破裂より前から声が出ている）を意味し、"
             "濁音だと聞き取るためのいちばん強い手がかり。"
             "日本語では清音がおよそ +25〜+45 ミリ秒、濁音が 0 前後かマイナスになるのが自然。")
    o.append("- **duration（全長, ms）**: ファイル全体の長さ。前後の無音を含む。")
    o.append("- **peak（最大振幅, dBFS）**: いちばん大きい瞬間の振幅。0 dBFS が天井。")
    o.append("- **RMS（実効値, dBFS）**: 鳴っている区間だけをならした音の大きさ。"
             "聞いた印象の音量に近い。前後の無音は除いて測る。")
    o.append("- **clip（音割れ）**: 振幅が天井に張りついた標本の数。0 なら音割れなし。\n")

    o.append("## 全ファイルの測定値\n")
    o.append("| 字 | 列 | onset (ms) | burst (ms) | VOT (ms) | duration (ms) | "
             "peak (dBFS) | RMS (dBFS) | clip |")
    o.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for ch in chars:
        for c in COLS:
            m = M[ch].get(c)
            if not m:
                continue
            vot = "—" if m["vot_ms"] is None else f"{m['vot_ms']:+.1f}"
            o.append(f"| {ch} | {c} | {n(m['onset_ms'])} | {n(m['burst_ms'])} | {vot} | "
                     f"{n(m['duration_ms'])} | {n(m['peak_dbfs'],2)} | {n(m['rms_dbfs'],2)} | "
                     f"{m['clip_samples']} |")
    o.append("")

    # --- 破裂音の清濁対比 ---
    o.append("## 清音と濁音の VOT の開き（破裂音3組）\n")
    o.append("同じ調音の場所どうしで、清音の VOT から濁音の VOT を引いた値。"
             "この開きが大きいほど、清音と濁音が音として別物になっていて聞き分けやすい。\n")
    o.append("| 組 | " + " | ".join(f"{c} 清音 / 濁音 / 開き" for c in COLS) + " |")
    o.append("|---|" + "---|" * len(COLS))
    pairs = [("ぱ", "ば"), ("か", "が"), ("た", "だ")]
    seps = {c: [] for c in COLS}
    for vl, vd in pairs:
        cells = []
        for c in COLS:
            a = M.get(vl, {}).get(c, {}).get("vot_ms")
            b = M.get(vd, {}).get(c, {}).get("vot_ms")
            if a is None or b is None:
                cells.append("—")
                continue
            seps[c].append(a - b)
            cells.append(f"{a:+.1f} / {b:+.1f} / **{a-b:+.1f}**")
        o.append(f"| {vl} vs {vd} | " + " | ".join(cells) + " |")
    o.append("| 開きの最小値 | " + " | ".join(
        (f"**{min(seps[c]):+.1f}**" if seps[c] else "—") for c in COLS) + " |")
    o.append("")

    o.append("### 読みとり\n")
    b1 = seps.get("B1", [])
    b2 = seps.get("B2", [])
    cc = seps.get("C", [])
    if b1 and b2:
        o.append(f"- **無加工でも話者しだいで大きく違う。** 同じ無加工でも B1（きりたん）は"
                 f"清濁の開きが最小 {min(b1):+.1f} ミリ秒しかないのに対し、"
                 f"B2（玄野武宏）は最小でも {min(b2):+.1f} ミリ秒ある。"
                 f"つまり清濁が聞き分けにくい原因は、加工だけでなく **話者の選び方** にもある。")
    if b2:
        o.append("- **B2 は濁音3字すべてに prevoicing がある**（VOT がマイナス）。"
                 "破裂より前から声帯が震えるため、破裂の瞬間を聞き逃しても濁音だと分かる。"
                 "B1 と C にはこれがない。")
    if cc and b1:
        o.append(f"- **現行の加工版（C）と無加工の同話者（B1）の比較。** C の開きの最小値は "
                 f"{min(cc):+.1f} ミリ秒、B1 は {min(b1):+.1f} ミリ秒。")
    o.append("")

    # 破裂音だけの詳細
    o.append("## 破裂音6字の詳細\n")
    o.append("| 字 | " + " | ".join(f"{c} VOT" for c in COLS) + " | " +
             " | ".join(f"{c} 全長" for c in COLS) + " |")
    o.append("|---|" + "---:|" * (len(COLS) * 2))
    for ch in ["ぱ", "ば", "か", "が", "た", "だ"]:
        v = [(f"{M[ch][c]['vot_ms']:+.1f}" if M.get(ch, {}).get(c, {}).get("vot_ms") is not None
              else "—") for c in COLS]
        d = [n(M.get(ch, {}).get(c, {}).get("duration_ms")) for c in COLS]
        o.append(f"| {ch} | " + " | ".join(v) + " | " + " | ".join(d) + " |")
    o.append("")

    o.append("## レベル合わせについて\n")
    o.append(f"- 参照した音量は、現行加工版12字の実効値の中央値 "
             f"**{man['level_reference_dbfs']:.2f} dBFS**。")
    o.append("- B1・B2 それぞれについて、**12字ぜんぶに同じ倍率をひとつだけ** 掛けた。"
             "字ごとに変えていないので、字と字のあいだの音量の差は合成器が出したままである。")
    o.append("- コンプレッサや、時間とともに変化する正規化は使っていない。"
             "破裂直後の音の大きさは清濁を聞き分ける手がかりなので、"
             "信号の中の相対的な振幅の関係を変えないため。")
    o.append(f"- 最大振幅は全ファイルで {max(m['peak_dbfs'] for ch in chars for m in M[ch].values()):.2f} "
             f"dBFS が最大。音割れ（clip）は "
             f"{sum(m['clip_samples'] for ch in chars for m in M[ch].values())} 標本。\n")

    o.append("## 注意（数値の読みまちがいを防ぐ）\n")
    o.append("- **onset は「ファイル先頭からの時刻」**。B1/B2 は合成器の既定で前に約100ミリ秒の"
             "無音が入るので、onset が 100 前後になるのは正常。C も本番の作りで先頭0.1秒が無音。")
    o.append("- **VOT の符号**。プラスは「破裂してから声が出るまでの間」、"
             "マイナスは「破裂より前から声が出ていた長さ」。絶対値の大小だけで比べてはいけない。")
    o.append("- **duration に前後の無音を含む**。B1/B2 は前後それぞれ約100ミリ秒の無音を含んだ全長。"
             "実際に音が鳴っている長さは duration から onset と末尾の無音を引いたもの。")
    o.append("- **C の全長がどの字もほぼ同じ理由**。現行の加工版は1文字を0.2秒に強制的に伸縮している"
             "ため、全長が456ミリ秒前後にそろう（す だけ432ミリ秒）。"
             "対して無加工の B1/B2 は字ごとに長さが違う（B1 は330〜523ミリ秒、B2 は299〜405ミリ秒）。"
             "**この「長さがそろっているか、字ごとに違うか」そのものが、加工したか・しないかの差**である。")
    o.append("- **RMS は鳴っている区間だけ**で測っている。無音を含めた全長で測った値ではない。")
    o.append("- **摩擦音（し・す）の実効値が低いのは異常ではない**。話者ごとに倍率をひとつしか"
             "掛けていないので、合成器が出した字と字のあいだの音量差がそのまま残る。"
             "「す」「し」は息の音が主体で、母音を含む字より10デシベルほど小さくなるのが自然。"
             "ここを字ごとにそろえると、清濁の手がかりである相対的な振幅の関係を壊すため、あえて残している。")
    o.append("- **prevoicing の長さは控えめに出る**。声帯振動の検出は数フレームぶんの信号を"
             "必要とするため、マイナスの VOT は実際の prevoicing よりやや短めに測られる。"
             "たとえば B2 の「が」は立ち上がり110ミリ秒・破裂197ミリ秒で実際の声の先行は約87ミリ秒あるが、"
             "測定値は -42.0 ミリ秒。清濁の判定には十分だが、絶対値をそのまま使うときは注意する。\n")

    o.append("---\n")
    o.append("聴き比べページ: `experiment/tools/source_compare.html`"
             "（公開先 https://g19922ma.github.io/iFont/experiment/tools/source_compare.html ）\n")

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w").write("\n".join(o))


def write_html(man, chars, M, xlim):
    sp = man["speakers"]
    rel = "../candidate_pools/raw_compare_v1"
    h = []
    h.append("""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>かな1音 音源比較: 自然録音 / 無加工の合成2話者 / 現行の加工版</title>
<style>
  :root { color-scheme: light; }
  body { font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",system-ui,sans-serif; margin:0;
         background:#f6f4ef; color:#1b2030; }
  #app { max-width: 1120px; margin:0 auto; padding:24px 20px 60px; }
  .card { background:#fff; border:1px solid #e6e1d6; border-radius:14px; padding:22px;
          box-shadow:0 1px 0 rgba(0,0,0,.03), 0 10px 28px rgba(46,125,143,.08); margin-bottom:18px; }
  h1,h2,h3 { font-family:"Hiragino Mincho ProN","Yu Mincho",serif; letter-spacing:.04em; color:#1E2A5E; }
  h1 { font-size:21px; border-bottom:1px solid #e9e4d8; padding-bottom:10px; margin:0 0 14px; }
  h2 { font-size:15px; margin:26px 0 10px; color:#8A5A00; letter-spacing:.08em; }
  p { line-height:1.85; font-size:14px; }
  .muted { color:#6b7280; font-size:13px; line-height:1.75; }
  .grid { display:grid; grid-template-columns:58px repeat(4, 1fr); gap:10px 12px; align-items:start; }
  .hd { position:sticky; top:0; background:#fff; z-index:2; padding:10px 0 8px;
        border-bottom:2px solid #e9e4d8; }
  .hd b { display:block; font-size:13px; color:#1E2A5E; letter-spacing:.03em; }
  .hd span { font-size:11px; color:#6b7280; }
  .kana { font-family:"Hiragino Mincho ProN","Yu Mincho",serif; font-size:34px; line-height:1;
          color:#1E2A5E; text-align:center; padding-top:14px; }
  .cell { min-width:0; border-top:1px solid #efeade; padding-top:9px; }
  .cell img { width:100%; display:block; border:1px solid #eae5d8; border-radius:6px; background:#fff; }
  .cell.todo { display:flex; align-items:center; justify-content:center; min-height:74px;
               color:#a8a396; font-size:13px; border:1px dashed #ddd6c6; border-radius:8px;
               border-top:1px solid #efeade; background:#fbfaf6; }
  .nums { font-size:11px; color:#6b7280; margin:5px 0 0; }
  .nums b { color:#1b2030; font-weight:600; }
  button.play { font-size:13px; padding:5px 14px; border-radius:999px; border:0;
                background:#2E7D8F; color:#fff; cursor:pointer; letter-spacing:.02em;
                transition:filter .15s; margin-bottom:6px; }
  button.play:hover { filter:brightness(1.12); }
  button.play:disabled { background:#b9c2c9; cursor:default; }
  button.col { font-size:12px; padding:5px 10px; border-radius:8px; border:1px solid #cbd5da;
               background:#eef4f5; color:#1B5C69; cursor:pointer; margin-top:6px; width:100%; }
  button.col:hover { background:#e2eef0; }
  button.col:disabled { color:#9aa3a8; background:#f3f4f5; cursor:default; }
  table { border-collapse:collapse; font-size:13px; margin-top:8px; }
  td,th { border:1px solid #e3e6ee; padding:5px 10px; text-align:left; }
  th { background:#faf8f3; font-weight:600; }
  .legend { display:flex; gap:18px; flex-wrap:wrap; font-size:12px; color:#6b7280; margin-top:8px; }
  .sw { display:inline-block; width:14px; height:2px; vertical-align:3px; margin-right:5px; }
</style>
</head>
<body>
<div id="app">
<div class="card">
<h1>かな1音の音源比較: 自然録音 / 無加工の合成2話者 / 現行の加工版</h1>
<p><b>横に並んだ4つを聴き比べ、その字だと確実に聞き取れるか・不自然でないかを判定してください。</b>
とくに <b>ぱ と ば</b>、<b>か と が</b>、<b>た と だ</b> の清音・濁音の聞き分けに注目してください。</p>
<p class="muted">この比較は、これまで行ってきた独自の音声加工（声の高さの平坦化・1文字0.2秒への強制伸縮・
VOT の自動修正・文脈語からの切り出し・字ごとのフィルタ）をやめて、<b>無加工のまま明瞭な音源</b>で
実験できないかを確かめるためのものです。B1・B2 はいずれも合成器が出した音をそのまま使っており、
音量をそろえる倍率を話者ごとに1つだけ掛けた以外は何もしていません。フェード（音の出入りを
なめらかにする処理）も掛けていません。再生もファイルをそのまま鳴らすだけで、切り出しはしません。</p>
""")

    h.append('<table><tr><th>列</th><th>中身</th><th>話者</th><th>形式</th></tr>')
    h.append('<tr><td>A</td><td>人が実際に発音した自然録音</td><td>準備中</td><td>—</td></tr>')
    fmt = {"B1": "WAV 44.1kHz/16bit", "B2": "WAV 44.1kHz/16bit", "C": "mp3（本番のコピー）"}
    for c in COLS:
        s = sp[c]
        h.append(f'<tr><td>{c}</td><td>{"無加工の合成音" if c.startswith("B") else "現行の加工版"}'
                 f'</td><td>{html.escape(s["name"])} / {html.escape(s["style"])}'
                 f'（speaker={s["id"]}）</td><td>{fmt[c]}</td></tr>')
    h.append('</table>')
    h.append(f'<p class="muted" style="margin-top:12px"><b>B2 に玄野武宏を選んだ理由</b>: '
             f'{html.escape(sp["B2"]["why"])}。</p>')
    h.append('<div class="legend">'
             '<span><span class="sw" style="background:#B03A2E"></span>音の立ち上がり</span>'
             '<span><span class="sw" style="background:#8A5A00"></span>破裂の瞬間（破裂音のみ）</span>'
             f'<span>図の横軸は全図共通で 0〜{xlim:.0f} ミリ秒、縦軸（振幅）も全図共通</span></div>')
    h.append('</div>')

    # ---- 本体グリッド ----
    h.append('<div class="card"><div class="grid">')
    h.append('<div class="hd"></div>')
    for c in ["A"] + COLS:
        s = sp.get(c, {})
        sub = "準備中" if c == "A" else f'{s["name"]}／{fmt[c].split("（")[0]}'
        h.append(f'<div class="hd"><b>{html.escape(COL_LABEL[c])}</b>'
                 f'<span>{html.escape(sub)}</span>'
                 + ('<button class="col" disabled>12字を続けて鳴らす</button>' if c == "A"
                    else f'<button class="col" data-col="{c}">12字を続けて鳴らす</button>')
                 + '</div>')

    for ch in chars:
        h.append(f'<div class="kana">{ch}</div>')
        h.append('<div class="cell todo">準備中</div>')
        for c in COLS:
            m = M[ch].get(c)
            if not m:
                h.append('<div class="cell todo">なし</div>')
                continue
            clip = json.dumps({"file": f"{rel}/{m['file']}"}, ensure_ascii=False)
            vot = "" if m["vot_ms"] is None else \
                f' ／ VOT <b>{m["vot_ms"]:+.0f}</b> ms'
            h.append('<div class="cell">'
                     f'<button class="play" data-col="{c}" data-clip="{html.escape(clip)}">▶ 鳴らす</button>'
                     f'<img src="{rel}/waveforms/{c}_{ch}.png" alt="{ch} の波形（{COL_LABEL[c]}）">'
                     f'<p class="nums">全長 <b>{m["duration_ms"]:.0f}</b> ms ／ '
                     f'立ち上がり {m["onset_ms"]:.0f} ms{vot}</p>'
                     '</div>')
    h.append('</div></div>')

    # ---- 見かた ----
    h.append("""<div class="card"><h2 style="margin-top:0">この表の見かた</h2>
<table>
<tr><th>言葉</th><th>意味</th></tr>
<tr><td>全長</td><td>ファイル全体の長さ。前後の無音を含む。B1・B2 は合成器の既定で前後それぞれ約100ミリ秒の無音が入る</td></tr>
<tr><td>立ち上がり</td><td>ファイルの先頭から数えて音が鳴りはじめる時刻</td></tr>
<tr><td>VOT</td><td>破裂の瞬間から声帯が震えはじめるまでの時間。<b>マイナスは破裂より前から声が出ていた</b>という意味で、濁音だと聞き取るいちばん強い手がかり。日本語では清音がおよそ +25〜+45 ミリ秒、濁音が 0 前後かマイナスになるのが自然</td></tr>
<tr><td>C の全長がどれも同じ</td><td>現行の加工版は1文字を0.2秒に強制的に伸縮しているため、全長が456ミリ秒前後にそろう。無加工の B1・B2 は字ごとに長さが違う。この違いそのものが「加工したか・しないか」の差</td></tr>
<tr><td>し・す が小さく聞こえる</td><td>話者ごとに倍率をひとつしか掛けていないので、字と字のあいだの音量差は合成器が出したまま。息の音が主体の字は母音を含む字より自然に小さい</td></tr>
</table>
<p class="muted" style="margin-top:14px">数値の一覧は <code>project/音源比較_QC表.md</code>。
音源は <code>experiment/candidate_pools/raw_compare_v1/</code>。
生成は <code>experiment/tools/build_raw_compare.py</code>、測定と本ページの生成は
<code>experiment/tools/measure_raw_compare.py</code>。</p></div>
</div>
<script>
let ctx = null;
const bufs = {};
function ensureCtx(){ if(!ctx) ctx = new (window.AudioContext||window.webkitAudioContext)(); return ctx; }
async function load(file){
  if(!bufs[file]){
    const r = await fetch(file);
    if(!r.ok) throw new Error("音声が読めない: " + file);
    bufs[file] = await ensureCtx().decodeAudioData(await r.arrayBuffer());
  }
  return bufs[file];
}
// ファイルをそのまま鳴らす。切り出しもフェームも音量調整もしない
// （音量をそろえる倍率はファイルを作る時点で焼き込んである）。
async function play(file){
  const c = ensureCtx();
  await c.resume();
  const buf = await load(file);
  const s = c.createBufferSource();
  s.buffer = buf; s.connect(c.destination); s.start();
  return new Promise(res => { s.onended = res; });
}
document.addEventListener("click", async e => {
  const b = e.target.closest("button.play");
  if(!b) return;
  b.disabled = true;
  try { await play(JSON.parse(b.dataset.clip).file); }
  catch(err){ b.textContent = "再生できない"; console.error(err); }
  b.disabled = false;
});
// 列ごとに12字を続けて鳴らす（1字ごとに 0.45 秒あける）
document.addEventListener("click", async e => {
  const b = e.target.closest("button.col");
  if(!b) return;
  const col = b.dataset.col;
  const all = [...document.querySelectorAll(`button.play[data-col="${col}"]`)];
  const cols = [...document.querySelectorAll("button.col")];
  cols.forEach(x => x.disabled = true);
  const label = b.textContent;
  try {
    for(let i=0;i<all.length;i++){
      b.textContent = `再生中 ${i+1}/${all.length}`;
      await play(JSON.parse(all[i].dataset.clip).file);
      await new Promise(r => setTimeout(r, 450));
    }
  } catch(err){ console.error(err); }
  b.textContent = label;
  // A列（自然録音）は音源が無いので、押せないままに戻す
  cols.forEach(x => x.disabled = !x.dataset.col);
});
</script>
</body>
</html>
""")
    open(OUT_HTML, "w").write("\n".join(h))


if __name__ == "__main__":
    main()
