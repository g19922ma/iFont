#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_information.py の出力を 1 枚の HTML にまとめる（図はインライン SVG・外部読み込みなし）。

    python3 experiment/tools/build_information_report.py

出力: project/data_calib2_live/information_report.html
"""
import argparse
import html
import io
import json
import math
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = {"fade": "うすい", "reveal": "点が増える", "blur": "ぼやけ", "wipe": "端から"}
FAMS = ["fade", "reveal", "blur", "wipe"]
CHARS = list("あかがぱしつまら")
SC = {"fade": "var(--s1)", "reveal": "var(--s2)", "blur": "var(--s3)", "wipe": "var(--s4)"}


def esc(x):
    return html.escape(str(x))


def fmt(x, n=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    return f"{x:,.{n}f}"


# ---------------------------------------------------------------------------
# SVG の道具
# ---------------------------------------------------------------------------
class Panel:
    """1つの座標系。data 座標 → svg 座標。"""

    def __init__(self, x0, y0, w, h, xlim, ylim, logx=False):
        self.x0, self.y0, self.w, self.h = x0, y0, w, h
        self.xa, self.xb = xlim
        self.ya, self.yb = ylim
        self.logx = logx

    def X(self, v):
        if self.logx:
            a, b, v = math.log(max(self.xa, 1e-9)), math.log(self.xb), math.log(max(v, 1e-9))
        else:
            a, b = self.xa, self.xb
        return self.x0 + (v - a) / (b - a) * self.w

    def Y(self, v):
        return self.y0 + self.h - (v - self.ya) / (self.yb - self.ya) * self.h

    def frame(self, xticks, yticks, xfmt=lambda v: f"{v:g}", yfmt=lambda v: f"{v:g}",
              ylab="", xlab="", title=""):
        o = []
        if title:
            o.append(f'<text class="ttl" x="{self.x0}" y="{self.y0 - 12}">{esc(title)}</text>')
        for v in yticks:
            y = self.Y(v)
            o.append(f'<line class="grid" x1="{self.x0}" y1="{y:.1f}" '
                     f'x2="{self.x0 + self.w}" y2="{y:.1f}"/>')
            o.append(f'<text class="lbl tiny" x="{self.x0 - 6}" y="{y + 3.5:.1f}" '
                     f'text-anchor="end">{esc(yfmt(v))}</text>')
        for v in xticks:
            x = self.X(v)
            o.append(f'<line class="grid" x1="{x:.1f}" y1="{self.y0}" '
                     f'x2="{x:.1f}" y2="{self.y0 + self.h}"/>')
            o.append(f'<text class="lbl tiny" x="{x:.1f}" y="{self.y0 + self.h + 14}" '
                     f'text-anchor="middle">{esc(xfmt(v))}</text>')
        o.append(f'<line class="axline" x1="{self.x0}" y1="{self.y0}" '
                 f'x2="{self.x0}" y2="{self.y0 + self.h}"/>')
        o.append(f'<line class="axline" x1="{self.x0}" y1="{self.y0 + self.h}" '
                 f'x2="{self.x0 + self.w}" y2="{self.y0 + self.h}"/>')
        if ylab:
            o.append(f'<text class="lbl tiny" x="{self.x0 - 34}" '
                     f'y="{self.y0 + self.h / 2}" text-anchor="middle" '
                     f'transform="rotate(-90 {self.x0 - 34} {self.y0 + self.h / 2})">'
                     f'{esc(ylab)}</text>')
        if xlab:
            o.append(f'<text class="lbl tiny" x="{self.x0 + self.w / 2}" '
                     f'y="{self.y0 + self.h + 30}" text-anchor="middle">{esc(xlab)}</text>')
        return "".join(o)

    def path(self, xs, ys, color, width=2.0, dash=None, opacity=1.0):
        pts = " ".join(f"{self.X(x):.1f},{self.Y(y):.1f}" for x, y in zip(xs, ys))
        d = f' stroke-dasharray="{dash}"' if dash else ""
        return (f'<polyline points="{pts}" fill="none" stroke="{color}" '
                f'stroke-width="{width}"{d} opacity="{opacity}" '
                f'stroke-linejoin="round" stroke-linecap="round"/>')

    def dots(self, xs, ys, color, r=2.6):
        return "".join(f'<circle cx="{self.X(x):.1f}" cy="{self.Y(y):.1f}" r="{r}" '
                       f'fill="{color}"/>' for x, y in zip(xs, ys))

    def hline(self, v, cls="chance"):
        y = self.Y(v)
        return (f'<line class="{cls}" x1="{self.x0}" y1="{y:.1f}" '
                f'x2="{self.x0 + self.w}" y2="{y:.1f}"/>')


def svg(w, h, body, title):
    return (f'<svg class="fig" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{esc(title)}">{body}</svg>')


def figure(sv, cap, num):
    return (f'<figure><div class="figwrap">{sv}</div>'
            f'<figcaption><b>図{num}</b>　{cap}</figcaption></figure>')


def table(cols, rows, aligns=None, cls="tbl"):
    aligns = aligns or [""] * len(cols)
    th = "".join(f"<th>{esc(c)}</th>" for c in cols)
    tr = []
    for r in rows:
        tds = "".join(f'<td class="{aligns[i]}">{v}</td>' for i, v in enumerate(r))
        tr.append(f"<tr>{tds}</tr>")
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(tr)}</tbody></table>'


# ---------------------------------------------------------------------------
# 図
# ---------------------------------------------------------------------------
def fig_prior(dist, summ):
    """事前分布（何も届いていないときの回答）を一様分布と並べる。"""
    W, H = 940, 300
    o = []
    panels = [("聴覚 10ms（本命8字）", "聴覚 10ms（本命8字）", 68, 40),
              ("視覚 4方式のいちばん薄い水準をまとめて", "視覚 いちばん薄い水準", 72, 40)]
    for i, (scope, ttl, K, ntop) in enumerate(panels):
        s = dist[dist.scope == scope].head(ntop)
        row = summ[summ.scope == scope].iloc[0]
        p = Panel(60 + i * 480, 46, 400, 170, (-0.5, ntop - 0.5), (0, 0.25))
        o.append(p.frame([], [0, 0.05, 0.10, 0.15, 0.20, 0.25],
                         yfmt=lambda v: f"{v * 100:.0f}%",
                         ylab="回答された割合", title=ttl))
        bw = 400 / ntop * 0.78
        for k, (_, r) in enumerate(s.iterrows()):
            x = p.X(k) - bw / 2
            y = p.Y(r.share)
            col = "var(--accent)" if k < 3 else "var(--s2)"
            o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{p.Y(0) - y:.1f}" fill="{col}" opacity="0.85"/>')
            if k < 6:
                o.append(f'<text class="lbl tiny" x="{p.X(k):.1f}" '
                         f'y="{y - 5 - (k % 2) * 11:.1f}" '
                         f'text-anchor="middle">{esc(r.char)} {r.share * 100:.0f}%</text>')
        yu = p.Y(1.0 / K)
        o.append(f'<line class="chance" x1="{p.x0}" y1="{yu:.1f}" '
                 f'x2="{p.x0 + p.w}" y2="{yu:.1f}"/>')
        o.append(f'<text class="lbl tiny" x="{p.x0 + p.w - 2}" y="{yu - 5:.1f}" '
                 f'text-anchor="end">一様分布なら 1/{K} = {100 / K:.1f}%</text>')
        t1 = (f"{int(row.n_trials)}試行・{K}択　エントロピー {row.entropy_bits:.2f} bit"
              f"（一様なら {row.entropy_uniform_bits:.2f}）　実質 {row.perplexity:.0f} 択")
        t2 = (f"一様分布からの隔たり {row.kl_from_uniform_bits:.2f} bit　"
              f"上位{int(row.n_covering_50pct)}字で回答の半分")
        o.append(f'<text class="lbl tiny" x="{p.x0}" y="{p.y0 + p.h + 32}">'
                 f'{esc(t1)}</text>')
        o.append(f'<text class="lbl tiny" x="{p.x0}" y="{p.y0 + p.h + 48}">'
                 f'{esc(t2)}</text>')
    return svg(W, H, "".join(o), "事前分布")


def fig_curves(fd):
    """情報量の曲線と正答率の曲線を、同じ枠に重ねる（5枚）。"""
    W, H = 940, 560
    o = []
    cells = [("audio", "聴覚（打ち切り時間）")] + [(f, LAB[f]) for f in FAMS]
    for i, (key, ttl) in enumerate(cells):
        cx, cy = i % 3, i // 3
        px, py = 62 + cx * 300, 40 + cy * 265
        if key == "audio":
            xs_all = {ch: fd["audio_levels"][ch] for ch in CHARS}
            bits = fd["audio_bits"]
            accs = fd["audio_acc"]
            xlim = (9, 130)
            xt = [10, 20, 40, 80, 125]
            xlab = "打ち切り時間 (ms)"
        else:
            lv = fd["visual_levels"][key]
            xs_all = {ch: lv for ch in CHARS}
            bits = fd["visual_bits"][key]
            accs = fd["visual_acc"][key]
            xlim = (min(lv) * 0.85, 100)
            xt = [x for x in [0.1, 0.5, 1, 3, 10, 30, 100] if xlim[0] <= x <= 100]
            xlab = "進み具合 s (%)"
        p = Panel(px, py, 232, 168, xlim, (0, 3.0), logx=True)
        o.append(p.frame(xt, [0, 1, 2, 3],
                         xfmt=lambda v: f"{v:g}", yfmt=lambda v: f"{v:g}",
                         ylab=("情報量 (bit)" if cx == 0 else ""),
                         xlab=xlab, title=ttl))
        col = SC.get(key, "var(--accent)")
        for ch in CHARS:
            o.append(p.path(xs_all[ch], bits[ch], col, 1.0, opacity=0.32))
            o.append(p.path(xs_all[ch], [v * 3.0 for v in accs[ch]],
                            "var(--muted)", 1.0, dash="3 3", opacity=0.28))
        # 平均（字をまたいだ単純平均）
        L = len(xs_all[CHARS[0]])
        mb = [float(np.mean([bits[ch][j] for ch in CHARS])) for j in range(L)]
        ma = [float(np.mean([accs[ch][j] for ch in CHARS])) * 3.0 for j in range(L)]
        o.append(p.path(xs_all[CHARS[0]], mb, col, 2.6))
        o.append(p.path(xs_all[CHARS[0]], ma, "var(--fg)", 2.0, dash="5 3"))
        o.append(f'<text class="lbl tiny" x="{p.x0 + 5}" y="{p.y0 + p.h - 16}" '
                 f'fill="{col}">情報量</text>')
        o.append(f'<text class="lbl tiny" x="{p.x0 + 5}" y="{p.y0 + p.h - 4}">'
                 f'正答率(×3)</text>')
    o.append('<text class="lbl tiny" x="662" y="330">細い線＝8字それぞれ／'
             '太い線＝8字の平均</text>')
    o.append('<text class="lbl tiny" x="662" y="348">右の軸は共通。正答率は 3 倍して</text>')
    o.append('<text class="lbl tiny" x="662" y="366">同じ枠に重ねている（上限が</text>')
    o.append('<text class="lbl tiny" x="662" y="384">正答率 1.0・情報量 3 bit で揃う）。</text>')
    return svg(W, H, "".join(o), "情報量と正答率の曲線")


def fig_ga(series, warp):
    """「が」の転写。正答率を目標にすると動かない／情報量を目標にすると動く。"""
    W, H = 940, 250
    o = []
    for i, fam in enumerate(FAMS):
        p = Panel(62 + i * 222, 40, 168, 150, (0, 300), (0, 100))
        o.append(p.frame([0, 100, 200, 300], [0, 25, 50, 75, 100],
                         ylab=("進み具合 s (%)" if i == 0 else ""),
                         xlab="経過時間 (ms)", title=LAB[fam]))
        for tag, col, dash, wdt in (("acc", "var(--muted)", "5 3", 2.0),
                                    ("info", SC[fam], None, 2.6)):
            s = series[(series.target == tag) & (series.family == fam)
                       & (series.char == "が")].sort_values("t_ms")
            o.append(p.path(s.t_ms.values, s.proposed_s.values, col, wdt, dash=dash))
        rw = warp[(warp.target == "info") & (warp.family == fam) & (warp.char == "が")]
        ra = warp[(warp.target == "acc") & (warp.family == fam) & (warp.char == "が")]
        o.append(f'<text class="lbl tiny" x="{p.x0 + 4}" y="{p.y0 + 13}" '
                 f'fill="{SC[fam]}">情報量 {float(rw.iloc[0].span_pt_gates):.0f}pt動く</text>')
        o.append(f'<text class="lbl tiny" x="{p.x0 + 4}" y="{p.y0 + 28}">'
                 f'正答率 {float(ra.iloc[0].span_pt_gates):.0f}pt</text>')
    return svg(W, H, "".join(o), "「が」の転写")


def fig_grid(warp):
    """32セルの成立判定を 2 枚並べる。"""
    W, H = 940, 300
    o = []
    colmap = {"成立": "var(--ok)", "一部成立（端で丸め）": "var(--warn)",
              "不成立（動かない）": "var(--bad)"}
    for i, (tag, ttl) in enumerate((("acc", "正答率を目標にしたとき"),
                                    ("info", "情報量を目標にしたとき"))):
        x0, y0 = 80 + i * 460, 56
        cw, chh = 44, 34
        o.append(f'<text class="ttl" x="{x0}" y="{y0 - 22}">{esc(ttl)}</text>')
        for k, ch in enumerate(CHARS):
            o.append(f'<text class="lbl tiny" x="{x0 + k * cw + cw / 2}" y="{y0 - 6}" '
                     f'text-anchor="middle">{esc(ch)}</text>')
        for j, fam in enumerate(FAMS):
            o.append(f'<text class="lbl tiny" x="{x0 - 8}" y="{y0 + j * chh + 21}" '
                     f'text-anchor="end">{esc(LAB[fam])}</text>')
            for k, ch in enumerate(CHARS):
                r = warp[(warp.target == tag) & (warp.family == fam)
                         & (warp.char == ch)].iloc[0]
                c = colmap[r.judgement]
                o.append(f'<rect x="{x0 + k * cw + 2}" y="{y0 + j * chh + 2}" '
                         f'width="{cw - 4}" height="{chh - 4}" rx="4" fill="{c}" '
                         f'opacity="0.72"/>')
                o.append(f'<text class="lbl tiny" x="{x0 + k * cw + cw / 2}" '
                         f'y="{y0 + j * chh + 21}" text-anchor="middle" '
                         f'fill="var(--card)" font-weight="700">'
                         f'{int(r.n_distinct_at_gates)}</text>')
        s = warp[warp.target == tag]
        cap = (f"成立 {int((s.judgement == '成立').sum())} / "
               f"一部成立 {int(s.judgement.str.startswith('一部').sum())} / "
               f"不成立 {int(s.judgement.str.startswith('不成立').sum())}")
        o.append(f'<text class="lbl tiny" x="{x0}" y="{y0 + 4 * chh + 22}">'
                 f'{esc(cap)}</text>')
    lg = [("成立", "var(--ok)"), ("一部成立（端で丸め）", "var(--warn)"),
          ("不成立（動かない）", "var(--bad)")]
    for i, (t, c) in enumerate(lg):
        o.append(f'<rect x="{80 + i * 200}" y="248" width="14" height="14" rx="3" '
                 f'fill="{c}" opacity="0.72"/>')
        o.append(f'<text class="lbl tiny" x="{100 + i * 200}" y="259">{esc(t)}</text>')
    o.append('<text class="lbl tiny" x="80" y="284">'
             'マスの数字＝7つの打ち切り時点のうち、実際に別々の絵になる数（多いほどよい・最大7）'
             '</text>')
    return svg(W, H, "".join(o), "転写の成立")


def fig_rank(bs):
    """方式の順位（ブートストラップの区間つき）。"""
    W, H = 940, 300
    o = []
    for i, (tag, ttl) in enumerate((("acc", "正答率を目標にしたとき"),
                                    ("info", "情報量を目標にしたとき"))):
        p = Panel(150 + i * 470, 50, 280, 170, (0, 0.30), (-0.5, 3.5))
        o.append(p.frame([0, 0.1, 0.2, 0.3], [], xfmt=lambda v: f"{v:.2f}",
                         xlab="提案が対照2より目標に近い差（可動域で割った値）", title=ttl))
        s = bs[bs.target == tag].sort_values("gain_rel_mean")
        for j, (_, r) in enumerate(s.iterrows()):
            y = p.Y(j)
            col = SC[r.family]
            o.append(f'<line x1="{p.X(r.gain_rel_lo):.1f}" y1="{y:.1f}" '
                     f'x2="{p.X(r.gain_rel_hi):.1f}" y2="{y:.1f}" stroke="{col}" '
                     f'stroke-width="3" opacity="0.5" stroke-linecap="round"/>')
            o.append(f'<circle cx="{p.X(r.gain_rel_mean):.1f}" cy="{y:.1f}" r="5.5" '
                     f'fill="{col}"/>')
            o.append(f'<text class="lbl tiny" x="{p.x0 - 8}" y="{y + 4:.1f}" '
                     f'text-anchor="end">{esc(r.family_ja)}</text>')
            o.append(f'<text class="lbl tiny" x="{p.x0 + p.w + 6}" y="{y + 4:.1f}">'
                     f'{esc(f"1位率 {r.p_best * 100:.0f}%")}</text>')
    return svg(W, H, "".join(o), "方式の順位")


def fig_speed(sp):
    """速さの効き（情報量）。"""
    W, H = 300, 230
    o = []
    p = Panel(110, 34, 160, 150, (-0.4, 0.4), (-0.5, 3.5))
    o.append(p.frame([-0.4, -0.2, 0, 0.2, 0.4], [], xfmt=lambda v: f"{v:g}",
                     xlab="500ms − 300ms の情報量差 (bit)", title="速さの効き"))
    o.append(f'<line class="chance" x1="{p.X(0):.1f}" y1="{p.y0}" '
             f'x2="{p.X(0):.1f}" y2="{p.y0 + p.h}"/>')
    s = sp.sort_values("diff_bits")
    for j, (_, r) in enumerate(s.iterrows()):
        y = p.Y(j)
        sig = r.p_holm < 0.05
        col = "var(--bad)" if sig else SC[r.family]
        o.append(f'<line x1="{p.X(r.lo_bits):.1f}" y1="{y:.1f}" '
                 f'x2="{p.X(r.hi_bits):.1f}" y2="{y:.1f}" stroke="{col}" '
                 f'stroke-width="3" opacity="0.5" stroke-linecap="round"/>')
        o.append(f'<circle cx="{p.X(r.diff_bits):.1f}" cy="{y:.1f}" r="5" fill="{col}"/>')
        o.append(f'<text class="lbl tiny" x="{p.x0 - 8}" y="{y + 4:.1f}" '
                 f'text-anchor="end">{esc(r.family_ja)}</text>')
        if sig:
            o.append(f'<text class="lbl tiny" x="{p.X(r.hi_bits) + 6:.1f}" '
                     f'y="{y + 4:.1f}" fill="var(--bad)">p={r.p_holm:.2f}</text>')
    return svg(W, H, "".join(o), "速さの効き")


# ---------------------------------------------------------------------------
CSS = """
:root{
  --bg:#faf8f4; --fg:#1c1a17; --muted:#6b6560; --accent:#b45309; --line:#ded6c8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c; --card:#ffffff;
  --s1:#b45309; --s2:#1d6fa5; --s3:#15803d; --s4:#8a3ea8;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
    --card:#211e19; --ok:#4ade80; --warn:#e8a14c; --bad:#f87171;
    --s1:#e8a14c; --s2:#6fb6e8; --s3:#5cc98a; --s4:#cf95e6;
  }
}
:root[data-theme="dark"]{
  --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
  --card:#211e19; --ok:#4ade80; --warn:#e8a14c; --bad:#f87171;
  --s1:#e8a14c; --s2:#6fb6e8; --s3:#5cc98a; --s4:#cf95e6;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);
  font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  line-height:1.8;max-width:1060px;margin:0 auto;padding:2.5rem 1.5rem 6rem}
h1{font-size:1.7rem;border-bottom:2px solid var(--accent);padding-bottom:.5rem;line-height:1.4}
h2{font-size:1.3rem;margin-top:3.4rem;color:var(--accent);
   border-bottom:1px solid var(--line);padding-bottom:.35rem}
h3{font-size:1.05rem;margin-top:2rem}
p{margin:.7rem 0}
.lead{color:var(--muted);font-size:.95rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:1rem 1.3rem;margin:1.2rem 0}
.card.key{border-left:5px solid var(--accent)}
.card.warn{border-left:5px solid var(--bad)}
.card h3{margin-top:.2rem}
.tbl{border-collapse:collapse;width:100%;font-size:.85rem;margin:.9rem 0}
.tbl th,.tbl td{border:1px solid var(--line);padding:.35rem .6rem;text-align:left}
.tbl th{background:color-mix(in srgb,var(--accent) 12%,var(--card))}
.tbl tbody tr:nth-child(even){background:color-mix(in srgb,var(--fg) 4%,var(--card))}
.tbl td.num{text-align:right;font-variant-numeric:tabular-nums}
.tblwrap{overflow-x:auto}
figure{margin:1.6rem 0 2.2rem}
figcaption{font-size:.9rem;color:var(--fg);margin-top:.5rem;padding-left:.7rem;
  border-left:3px solid var(--accent)}
.figwrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);
  border-radius:10px;padding:.6rem}
svg.fig{display:block;max-width:100%;height:auto;margin:0 auto}
svg text{font-family:"Hiragino Sans","Yu Gothic",sans-serif}
svg .lbl{fill:var(--muted);font-size:12px}
svg .tiny{font-size:10.5px}
svg .ttl{fill:var(--fg);font-size:13px;font-weight:700}
svg .axline{stroke:var(--muted);stroke-width:1.1}
svg .grid{stroke:var(--line);stroke-width:1;stroke-dasharray:2 3}
svg .chance{stroke:var(--muted);stroke-width:1;stroke-dasharray:6 4;opacity:.8}
.tag{display:inline-block;padding:.05rem .5rem;border-radius:5px;font-size:.78rem;font-weight:700}
.tag.ok{background:color-mix(in srgb,var(--ok) 22%,transparent);color:var(--ok)}
.tag.warn{background:color-mix(in srgb,var(--warn) 24%,transparent);color:var(--warn)}
.tag.bad{background:color-mix(in srgb,var(--bad) 22%,transparent);color:var(--bad)}
.small{font-size:.83rem;color:var(--muted);margin:.35rem 0 0}
code{background:color-mix(in srgb,var(--fg) 7%,transparent);padding:.05rem .3rem;
  border-radius:4px;font-size:.88em}
ul{margin:.5rem 0 .5rem 1.2rem;padding:0}
li{margin:.25rem 0}
.toc{font-size:.9rem;columns:2;column-gap:2rem}
.toc a{color:var(--fg)}
.formula{text-align:center;font-size:1.1rem;margin:1rem 0;font-family:Georgia,serif}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(
        ROOT, "project/data_calib2_live/analysis_information"))
    ap.add_argument("--out", default=os.path.join(
        ROOT, "project/data_calib2_live/information_report.html"))
    a = ap.parse_args()
    D = a.inp

    def rd(n):
        return pd.read_csv(os.path.join(D, n))

    prior_s = rd("prior_summary.csv")
    prior_d = rd("prior_response_distribution.csv")
    lvl = rd("info_by_level.csv")
    warp = rd("warp_info_vs_acc.csv")
    series = rd("warp_series.csv")
    rank = rd("family_ranking.csv")
    sp = rd("speed_effect_info.csv")
    res = rd("resolution_info.csv")
    bs = rd("family_ranking_bootstrap.csv")
    bsraw = rd("family_ranking_bootstrap_raw.csv")
    fd = json.load(io.open(os.path.join(D, "figure_data.json"), encoding="utf-8"))

    def pwin(tag, f1, f2):
        """ブートストラップで f1 が f2 を上回った割合。"""
        p = bsraw[bsraw.target == tag].pivot(index="boot", columns="family",
                                             values="gain_over_b2_rel")
        return float((p[f1] > p[f2]).mean())

    pa = prior_s[prior_s.scope == "聴覚 10ms（本命8字）"].iloc[0]
    pv = prior_s[prior_s.scope == "視覚 4方式のいちばん薄い水準をまとめて"].iloc[0]
    full = lvl[(lvl.modality == "audio") & (lvl.level_label == "打ち切りなし")].iloc[0]
    g10 = lvl[(lvl.modality == "audio") & (lvl.level_label.str.startswith("10〜"))].iloc[0]
    WA = warp[warp.target == "acc"]
    WI = warp[warp.target == "info"]
    bychar = rd("info_by_char_level.csv")
    gaf = bychar[(bychar.modality == "audio") & (bychar.level_index == 99)
                 & (bychar.char == "が")].iloc[0]
    ga_bits = float(gaf.bits_corrected)          # 打ち切りなしで「が」が運んだ情報量
    ga_last = float(WI[WI.char == "が"].target_at_last_gate.iloc[0])
    # いちばん薄い水準での差し引き後の値（＝推定が較正されている証拠）
    floors = lvl[lvl.modality == "visual"].sort_values(["family", "level"]) \
        .groupby("family").first()
    floor_txt = "、".join(
        f"{LAB[f]} {floors.loc[f, 'level']:g}% で {floors.loc[f, 'mi_corrected_bits']:+.2f}"
        for f in FAMS)
    bias_lo = lvl.mi_null_bits.min()
    bias_hi = lvl.mi_null_bits.max()

    o = []
    A = o.append
    A(f'<h1>転写の目標を「正答率」から「情報量」に置き換えたらどうなるか</h1>')
    A('<p class="lead">較正データ（視覚325人・聴覚90人／2バッチを1実験として扱う）の'
      '再解析。生成: <code>experiment/tools/analyze_information.py</code> '
      '→ <code>experiment/tools/build_information_report.py</code>。'
      '本番ファイルには書き込んでいない。</p>')

    A('<div class="card key"><h3>結論を先に</h3><ul>'
      f'<li><b>事前分布は一様ではない。</b>聴覚は 68 択なのに実質 '
      f'{pa.perplexity:.0f} 択（一様からの隔たり {pa.kl_from_uniform_bits:.2f} bit）、'
      f'視覚は 72 択なのに実質 {pv.perplexity:.0f} 択（同 '
      f'{pv.kl_from_uniform_bits:.2f} bit）。「正答率0%＝情報ゼロ」は成り立たない。</li>'
      f'<li><b>「が」は正答率3%でも {fmt(ga_bits)} bit '
      '運んでいる。</b>正答率を目標にすると転写は最後まで動かないが、情報量を目標にすると'
      '4方式すべてで動く。</li>'
      f'<li><b>転写が成立するセルは {int((WA.judgement == "成立").sum())}/32 → '
      f'{int((WI.judgement == "成立").sum())}/32 に増える。</b>'
      f'「動かない」セルは {int(WA.judgement.str.startswith("不成立").sum())} → '
      f'{int(WI.judgement.str.startswith("不成立").sum())}。</li>'
      '<li><b>順位は一部入れ替わる。</b>ぼやけが1位なのは動かない'
      f'（ブートストラップ1位率 '
      f'{bs[(bs.target == "info") & (bs.family == "blur")].iloc[0].p_best * 100:.0f}%）。'
      f'<b>うすいが最下位争いから2位争いに上がり、端からと並ぶ</b>'
      f'（うすい＞端から の確率 {pwin("acc", "fade", "wipe") * 100:.0f}% → '
      f'{pwin("info", "fade", "wipe") * 100:.0f}%）。'
      '点が増えるは情報量で見ても提示時間に弱く、最下位のまま。</li>'
      '</ul></div>')

    A('<h2 id="s1">1. なぜ正答率では足りないのか</h2>')
    A('<p>同じ「ほとんど当たらない」でも、中身は 2 通りある。</p>')
    A(table(["条件", "試行", "正答率", "回答の広がり（実質何択）",
             "その水準で運ばれた情報量"],
            [["聴覚 10ms（ほぼ無音）", f'{int(g10.n_trials)}',
              f'{g10.accuracy * 100:.1f}%', f'{g10.cond_perplexity:.1f} 択',
              f'{g10.mi_corrected_bits:.2f} bit'],
             ["聴覚 打ち切りなし（全部聞かせる）", f'{int(full.n_trials)}',
              f'{full.accuracy * 100:.1f}%', f'{full.cond_perplexity:.1f} 択',
              f'{full.mi_corrected_bits:.2f} bit']],
            ["", "num", "num", "num", "num"]))
    A('<p>「実質何択」は字ごとに応答分布のエントロピーを出して試行数で加重平均した'
      '2<sup>H</sup>（<code>analyze_families_v2.py</code> の '
      '<code>perplexity_by_bin_v2.csv</code> と同じ数え方）。'
      '打ち切りなしの 2.0 択は既存の結果と一致する。</p>')
    A('<div class="card"><h3>「が」を全部聞かせたとき</h3>'
      f'<p>{int(gaf.n_trials)} 試行のうち <b>{int(gaf.top1_n)} が「{esc(gaf.top1_char)}」</b>。'
      f'正解の「が」は正答率 {gaf.accuracy_raw * 100:.1f}%。'
      '答えは 1 か所に集中しているので、<b>「が」と「か」以外の 6 字は消せている</b>。'
      'これは情報が届いているということで、実際 '
      f'{fmt(ga_bits)} bit '
      '（上限 3 bit）を運んでいる。正答率にはこれが一切映らない。</p>'
      f'<p class="small">はしごの最後の打ち切り（85ms）でも {fmt(ga_last)} bit。'
      '転写の目標にはこちらを使う（打ち切りなしは転写の範囲の外）。</p></div>')

    A('<h2 id="s2">2. 事前分布を測る</h2>')
    A('<p>何も届いていないときに人が何と答えるかを、いちばん短い打ち切り／いちばん薄い'
      '水準で測った。視覚は本命8字とまぎれ字64字を合わせている。</p>')
    A(figure(fig_prior(prior_d, prior_s),
             "何も届いていないときの回答分布。破線は一様分布のときの高さ。"
             "聴覚は「つ」に、視覚は「あ」に偏る。"
             "一様どころか、上位数字で回答の半分を占める。", 1))
    rows = []
    for _, r in prior_s.iterrows():
        rows.append([esc(r["scope"]), f'{int(r.n_trials)}', f'{int(r.n_support)}',
                     fmt(r.entropy_bits), fmt(r.entropy_uniform_bits),
                     fmt(r.perplexity, 1), fmt(r.kl_from_uniform_bits),
                     f'{esc(r.top1)} {r.top1_share * 100:.1f}%',
                     f'{int(r.n_covering_50pct)}'])
    A('<div class="tblwrap">' + table(
        ["範囲", "試行", "選択肢", "エントロピー(bit)", "一様なら(bit)",
         "実質何択", "一様からの隔たり(bit)", "いちばん多い回答", "半分を占める字数"],
        rows, ["", "num", "num", "num", "num", "num", "num", "", "num"]) + '</div>')
    A('<p class="small">エントロピーは有限標本で下に偏るので、'
      'Miller-Madow 補正した値も <code>prior_summary.csv</code> に入れてある'
      '（補正しても結論は変わらない）。</p>')

    A('<h2 id="s3">3. どの指標を目標にするか</h2>')
    A('<p>3 つ計算した。</p>')
    A('<div class="card"><ul>'
      '<li><b>① 応答分布のエントロピー H と実質選択肢数 2<sup>H</sup></b>：'
      '何択まで絞れているか。直感的だが、<b>事前の偏りと届いた情報を混ぜてしまう</b>。'
      '10ms で「つ」に集中するのも、全部聞かせて「か」に集中するのも、同じく低い H になる。</li>'
      '<li><b>② 事前分布からの情報利得 KL( P(R|x) ‖ P(R|事前) )</b>：'
      '事前の偏りは差し引ける。しかし<b>刺激と無関係に回答が動いただけでも大きくなる</b>。</li>'
      '<li><b>③ 相互情報量 I(S;R) と、その字ごとの分け前</b>'
      '<div class="formula">D<sub>c</sub>(x) = KL( P(R | 字c, 水準x) ‖ P(R | 水準x) )</div>'
      '「その回答を見て、どの字が出たか<b>がどれだけ分かるか</b>」そのもの。'
      '基準になるのはその水準の実測の周辺分布なので、<b>事前の偏りは自動的に差し引かれる</b>。'
      '何も届いていなければ 0。字ごとに分けられるので、字ごとの転写にそのまま使える。</li>'
      '</ul>'
      '<p><b>③ を目標に選ぶ。</b>理由は 3 つ：(a) 事前分布の扱いが自動で正しい、'
      '(b) 「答えが1つ隣にずれている」を情報として数えられる、'
      '(c) 聴覚と視覚で同じ 8 字・同じ上限（H(S)=3 bit）なので、'
      '<b>2 つの感覚を同じ物差しに載せられる</b>。'
      '正答率も同じ性質を持つが、(b) を数えられない。</p></div>')
    A('<div class="card warn"><h3>推定の偏りをどう扱ったか</h3>'
      '<p>応答は 72 択（視覚）/ 68 択（聴覚）あるのに、1 セルの試行は 34〜250 しかない。'
      '素の相互情報量は<b>必ず上に偏る</b>。そこで、'
      '<b>その水準の中だけで字のラベルを入れ替えた（真の情報量が 0 になる）ときの値</b>を'
      '並べ替えで求め、それを引いている。'
      f'実際、各方式のいちばん薄い水準では引いた後の値がほぼ 0 に落ちる'
      f'（{floor_txt} bit）。推定が正しく較正されている証拠になる。</p>'
      '<p>曲線は <code>build_warp_b4.py</code> と同じ<b>単調回帰（袋詰め PAVA・'
      '参加者単位）</b>で、測った範囲の外へは伸ばさない。'
      '並べ替えは<b>袋の中でも引き直す</b>（袋の中は参加者が重複するぶん偏りが増えるため）。</p>'
      '</div>')

    A('<h2 id="s4">4. 情報量の軌跡は正答率の軌跡とどう違うか</h2>')
    A(figure(fig_curves(fd),
             "情報量（色つき・実線）と正答率（灰・破線、3倍して重ねた）の曲線。"
             "上限が揃うように正答率を3倍している。"
             "情報量の曲線は<b>もっと早く立ち上がり、上でも寝ない</b>。"
             "とくに聴覚は、正答率が頭打ちになった後も情報量が伸び続ける。", 2))
    rows = []
    for fam in FAMS:
        ri = res[(res.target == "info") & (res.family == fam)]
        ra = res[(res.target == "acc") & (res.family == fam)]
        rows.append([LAB[fam],
                     f'{ra.s50.median():.2f}%', f'{ri.s50.median():.2f}%',
                     fmt(ra.curve_range.median()), fmt(ri.curve_range.median()),
                     f'{ra.s5.median():.2f}〜{ra.s95.median():.1f}%',
                     f'{ri.s5.median():.2f}〜{ri.s95.median():.1f}%'])
    A(table(["方式", "正答率が半分になる s", "情報量が半分になる s",
             "正答率の可動域", "情報量の可動域(bit)",
             "正答率の5〜95%区間", "情報量の5〜95%区間"], rows,
            ["", "num", "num", "num", "num", "num", "num"]))

    A('<h2 id="s5">5. 情報量で転写を作り直す</h2>')
    A('<p>手続きは正答率版と<b>まったく同じ</b>——聴覚の曲線 A(t) を目標にして、'
      '視覚の曲線 V(s) を逆に解く。軸に載っている量だけを取り替えた。'
      'だから 2 つの差は「目標の選び方」だけから来る。</p>')
    A(figure(fig_ga(series, warp),
             "「が」の転写。灰の破線＝正答率を目標にしたとき、色の実線＝情報量を目標にしたとき。"
             "正答率版では「が」の聴覚曲線がほぼ床に張りついているので、"
             "うすいでは <b>0.9pt しか動かない（＝最後まで真っ白）</b>。"
             "情報量版ではどの方式でも動きが出る。", 3))
    A(figure(fig_grid(warp),
             "32 セル（8字×4方式）の転写成立判定。"
             "マスの数字は、7 つの打ち切り時点のうち実際に別々の絵になる数（最大7）。"
             "「一部成立」はほぼすべて<b>いちばん短い打ち切り（10ms）だけが端で丸まる</b>もの。", 4))
    rows = []
    for tag, ttl in (("acc", "正答率を目標"), ("info", "情報量を目標")):
        s = warp[warp.target == tag]
        rows.append([ttl,
                     f'{int((s.judgement == "成立").sum())}',
                     f'{int(s.judgement.str.startswith("一部").sum())}',
                     f'{int(s.judgement.str.startswith("不成立").sum())}',
                     fmt(s.span_pt_gates.median(), 1),
                     fmt(s.n_distinct_at_gates.median(), 1),
                     fmt(s.gain_over_b2_rel.mean(), 3),
                     fmt(s.affine_resid_rel.median(), 3)])
    A(table(["目標", "成立", "一部成立", "不成立", "動く幅の中央値(pt)",
             "7点が別々の絵になる数(中央値)", "提案が対照2より近い差（可動域比）",
             "一次変換への潰れ具合"], rows,
            ["", "num", "num", "num", "num", "num", "num", "num"]))
    A('<p class="small">「提案が対照2より近い差」は、目標の単位が違う（正答率 vs bit）ので'
      '<b>その方式の曲線の可動域で割って</b>そろえてある。'
      f'情報量にすると <b>{WA.gain_over_b2_rel.mean():.3f} → '
      f'{WI.gain_over_b2_rel.mean():.3f}</b> と広がる。とくに正答率版で死んでいたセル'
      '（「が」など）で差が大きく開く。'
      '一方、軌跡そのものは情報量版のほうが<b>直線に近くなる</b>'
      f'（潰れ具合 {WA.affine_resid_rel.median():.3f} → '
      f'{WI.affine_resid_rel.median():.3f}）。'
      'これは目標曲線がなめらかになるためで、'
      '対照2との<b>予測のずれ</b>は広がっているので矛盾ではない。</p>')

    A('<h2 id="s6">6. 方式の順位は変わるか</h2>')
    A(figure(fig_rank(bs),
             "提案が対照2（一次変換）よりどれだけ目標に近いか。"
             "点＝300回の参加者ブートストラップの平均、帯＝95%区間、"
             "右の「1位率」＝ブートストラップで1位になった割合。"
             "<b>ぼやけの1位は動かない。うすいが最下位争いから2位争いに上がる。</b>", 5))
    A('<p>ブートストラップでの直接対決（相手を上回った割合）。'
      'うすいと端からは、正答率では差がついていたが、情報量ではほぼ並ぶ。</p>')
    A(table(["対決", "正答率を目標", "情報量を目標"],
            [[f"{LAB[f1]} ＞ {LAB[f2]}",
              f'{pwin("acc", f1, f2) * 100:.0f}%', f'{pwin("info", f1, f2) * 100:.0f}%']
             for f1, f2 in (("blur", "wipe"), ("blur", "fade"), ("fade", "wipe"),
                            ("fade", "reveal"), ("wipe", "reveal"))],
            ["", "num", "num"]))
    rows = []
    for fam in FAMS:
        ra = rank[(rank.target == "acc") & (rank.family == fam)].iloc[0]
        ri = rank[(rank.target == "info") & (rank.family == fam)].iloc[0]
        ba = bs[(bs.target == "acc") & (bs.family == fam)].iloc[0]
        bi = bs[(bs.target == "info") & (bs.family == fam)].iloc[0]
        rows.append([LAB[fam],
                     f'{int(ra.n_success)} / {int(ra.n_partial)} / {int(ra.n_dead)}',
                     f'{int(ri.n_success)} / {int(ri.n_partial)} / {int(ri.n_dead)}',
                     fmt(ra.n_distinct_at_gates_median, 1),
                     fmt(ri.n_distinct_at_gates_median, 1),
                     fmt(ra.gain_over_b2_rel_mean, 3), fmt(ri.gain_over_b2_rel_mean, 3),
                     fmt(ba.mean_rank, 2), fmt(bi.mean_rank, 2)])
    A('<div class="tblwrap">' + table(
        ["方式", "成立/一部/不成立（正答率）", "成立/一部/不成立（情報量）",
         "7点の分かれ方（正答率）", "7点の分かれ方（情報量）",
         "対照2との差（正答率）", "対照2との差（情報量）",
         "平均順位（正答率）", "平均順位（情報量）"], rows,
        ["", "", "", "num", "num", "num", "num", "num", "num"]) + '</div>')

    A('<h3>うすい — 「作れる絵が足りない」は情報量でも残るか</h3>')
    ri = res[(res.target == "info") & (res.family == "fade")]
    ra = res[(res.target == "acc") & (res.family == "fade")]
    wi = warp[(warp.target == "info") & (warp.family == "fade")]
    wa = warp[(warp.target == "acc") & (warp.family == "fade")]
    A(f'<p>5〜95% の窓で作れる別々の絵は '
      f'<b>{ra.n_distinct.median():.0f} 枚 → {ri.n_distinct.median():.0f} 枚</b>に増える'
      f'（情報量の曲線のほうが立ち上がりが早く、使える窓が広いため）。'
      f'転写の成立も <b>{int((wa.judgement == "成立").sum())}/8 → '
      f'{int((wi.judgement == "成立").sum())}/8</b> に増え、'
      f'「動かない」セルは {int(wa.judgement.str.startswith("不成立").sum())} → 0 になる。'
      f'ただし<b>参加者が実際に見る 7 つの打ち切り時点</b>で見ると、'
      f'別々の絵になる数は中央 {wa.n_distinct_at_gates.median():.1f} → '
      f'{wi.n_distinct_at_gates.median():.1f} 枚どまりで、4 方式のうち最も少ない'
      f'（他は 6.5〜7.0）。<b>分解能の弱点は薄まるが消えない。</b></p>')

    A('<h3>点が増える — 情報量で見ても提示時間に弱いか</h3>')
    A(figure(fig_speed(sp),
             "300ms と 500ms の情報量の差（水準等重み・参加者ブートストラップ95%区間・"
             "Holm 調整）。<b>点が増えるだけが有意に速さに引きずられる</b>のは、"
             "正答率で見たときと同じ。", 6))
    rows = []
    for _, r in sp.iterrows():
        tag = ('<span class="tag bad">有意</span>' if r.p_holm < 0.05
               else '<span class="tag ok">差なし</span>')
        rows.append([r.family_ja, f'{int(r.n300)}/{int(r.n500)}',
                     fmt(r.mi300_bits), fmt(r.mi500_bits),
                     f'{r.diff_bits:+.3f}',
                     f'[{r.lo_bits:+.3f}, {r.hi_bits:+.3f}]',
                     fmt(r.p_holm, 3), f'{r.acc_diff_pt:+.1f}pt', tag])
    A(table(["方式", "試行 300/500", "情報量 300ms", "情報量 500ms", "差(bit)",
             "95%区間", "Holm後 p", "参考: 正答率差", "判定"], rows,
            ["", "num", "num", "num", "num", "num", "num", "num", ""]))
    A('<p class="small">正答率で見た +8.8pt（Holm後 p=0.007）と同じ結論。'
      '情報量にしても <b>点が増えるは提示時間に弱い</b>。'
      '落とした理由は情報量の枠組みでも生きている。</p>')

    A('<h2 id="s7">7. 情報量を目標にすべきか</h2>')
    A('<div class="card key"><h3>推奨</h3>'
      '<p><b>転写の目標は情報量（字ごとの相互情報量の分け前）に切り替えるべき。</b>'
      '理由は次の 3 点。</p><ul>'
      '<li><b>正答率は測れない領域が広すぎる。</b>「が」のように正答率が床に'
      'へばりついたまま情報だけが増える字では、正答率を目標にした転写は<b>何もしない</b>。'
      '32 セル中 4 セルが完全に死に、21 セルが端で丸まっていた。'
      '情報量にすると死んだセルは 0 になる。</li>'
      '<li><b>事前分布の扱いが正しくなる。</b>「正答率0%＝情報ゼロ」は誤りで、'
      f'実際には聴覚 10ms でも {g10.mi_corrected_bits:.2f} bit が届いている'
      '（「が」で「か・く」と答える人が 34 人中 18 人＝軟口蓋の手がかりが漏れている）。'
      '相互情報量はこれを自動的に扱う。</li>'
      '<li><b>提案条件が対照条件と区別しやすくなる。</b>提案と対照2（一次変換）の'
      f'差は可動域比で {WA.gain_over_b2_rel.mean():.3f} → '
      f'{WI.gain_over_b2_rel.mean():.3f} に広がり、'
      'とくに正答率版で死んでいたセルで開く。'
      '実験2で見たい効果が、そもそも作れる条件になる。</li>'
      '</ul>'
      '<p><b>ただし残る注意</b>：(a) 8 字なので上限が 3 bit しかなく、'
      '実運用の字数では縮尺が変わる。(b) 1 セル 34〜250 試行では推定に偏りが乗るので、'
      f'並べ替えによる差し引きは必須（差し引く量は {bias_lo:.2f}〜{bias_hi:.2f} bit '
      'にもなる）。'
      '(c) 参加者に「情報量」は説明できない。正答率は説明できる。'
      '<b>目標は情報量、報告は正答率</b>という二本立てを勧める。</p></div>')

    A('<div class="card"><h3>方式の採否は、こう変わる</h3><ul>'
      '<li><b>ぼやけ</b>：<span class="tag ok">採用のまま</span>'
      'どちらの物差しでも 1 位（ブートストラップ 1 位率 '
      f'{bs[(bs.target == "info") & (bs.family == "blur")].iloc[0].p_best * 100:.0f}%）。'
      '対照2との差がいちばん大きく、成立セルも最多。</li>'
      '<li><b>端から</b>：<span class="tag warn">採用は維持、ただし順位は下がる</span>'
      '7 点の分かれ方は最良（7.0）だが、'
      '<b>「ほとんど何も出ていない状態」が作れない</b>（いちばん薄い 0.5% でも '
      f'{warp[(warp.target == "info") & (warp.family == "wipe")].visual_bottom.median():.2f} bit を'
      '運んでしまう）ため、短い打ち切りで端に丸まるセルが 4 つ出る。</li>'
      '<li><b>うすい</b>：<span class="tag warn">再検討に値する</span>'
      '正答率では最下位争いだったが、情報量では端からと 2 位を分け合う。'
      f'成立セルは {int(WA[WA.family == "fade"].judgement.eq("成立").sum())}/8 → '
      f'{int(WI[WI.family == "fade"].judgement.eq("成立").sum())}/8。'
      'ただし打ち切り 7 点の分かれ方は依然最少なので、'
      '<b>組み合わせ（うすい×ぼやけ）で刻みを足す</b>のが現実的。</li>'
      '<li><b>点が増える</b>：<span class="tag bad">不採用のまま</span>'
      '情報量で見ても提示時間に有意に引きずられ（'
      f'{sp[sp.family == "reveal"].iloc[0].diff_bits:+.2f} bit, Holm後 '
      f'p={sp[sp.family == "reveal"].iloc[0].p_holm:.2f}）、'
      'かつ対照2との差が 4 方式で最小。分解能は圧倒的に高いのに、'
      '<b>その分解能が転写の役に立っていない</b>。</li>'
      '</ul></div>')

    A('<h2 id="s8">8. 出力ファイル</h2>')
    A('<p><code>project/data_calib2_live/analysis_information/</code>（.gitignore 対象）</p>')
    A(table(["ファイル", "中身"], [
        ["<code>prior_summary.csv</code> / <code>prior_response_distribution.csv</code>",
         "事前分布と、一様分布からの隔たり"],
        ["<code>info_by_level.csv</code>",
         "水準ごとの ①エントロピー ②事前からの利得 ③相互情報量（素・並べ替え・差し引き後）と正答率"],
        ["<code>info_by_char_level.csv</code>", "字×水準の D<sub>c</sub>（素／差し引き後／袋詰め後・区間つき）"],
        ["<code>curves_info.csv</code>", "推定した単調曲線（情報量・正答率）"],
        ["<code>warp_info_vs_acc.csv</code>", "32セルの転写の比較（成立判定・対照2との差・分解能）"],
        ["<code>warp_series.csv</code>", "60fps の s(t) 系列（提案・対照1・対照2 × 2目標）"],
        ["<code>family_ranking.csv</code> / <code>family_ranking_bootstrap.csv</code>",
         "方式の順位と、その確からしさ"],
        ["<code>resolution_info.csv</code>", "5〜95%の窓で作れる別々の絵の枚数"],
        ["<code>speed_effect_info.csv</code>", "速さの効き（情報量）"],
    ]))
    A('<p class="small">再実行: '
      '<code>python3 experiment/tools/analyze_information.py --bag 400 --perm 300 '
      '--perm-per-bag 6 --boot-rank 300</code> のあと '
      '<code>python3 experiment/tools/build_information_report.py</code>。</p>')

    doc = ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>情報量を目標にした転写 — 較正データ再解析</title>'
           f'<style>{CSS}</style></head><body>' + "".join(o) + '</body></html>')
    io.open(a.out, "w", encoding="utf-8").write(doc)
    print(f"書き出し: {os.path.relpath(a.out, ROOT)} "
          f"({os.path.getsize(a.out) // 1024} KB)")


if __name__ == "__main__":
    main()
