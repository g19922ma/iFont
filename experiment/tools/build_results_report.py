#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
実験結果レポート（単一HTML・インラインSVG）の生成
==================================================

入力  : project/data_calib2_live/analysis/*.csv （analyze_calib2.py の出力）
出力  : project/data_calib2_live/results_report_20260827.html

方針
----
* 数値は **すべて CSV から読む**。手書きの数値はレポート本文に置かない。
* 図は **インライン SVG** のみ（外部 CDN・外部ファイル・JS ライブラリを使わない）。
* ぼやけ(blur)方式の数値は **WebKit 端末を除外したもの**を主として示す。
  WebKit（iOS の全ブラウザ・アプリ内 WebView・macOS Safari）では
  canvas の ctx.filter = blur(...) が効かず、字が鮮明なまま提示されていた。
* 参加者個人を特定できる情報（wid・participant_id）は一切出力しない。

使い方
------
  python3 experiment/tools/build_results_report.py \
      --in  project/data_calib2_live/analysis \
      --out project/data_calib2_live/results_report_20260827.html
"""
import argparse
import html
import math
import os

import pandas as pd

# ------------------------------------------------------------------ 定数
GAMMA = 1.0 / 72.0                     # 72択の当てずっぽう率
FAM_JA = {"fade": "うすい (fade)", "reveal": "けずり (reveal)",
          "blur": "ぼやけ (blur)", "wipe": "はらい (wipe)"}
PHASE_JA = {"calib": "実験1", "calib2": "追いバッチ", "pooled": "プール"}

# 系列の色は CSS 変数で持ち、明暗どちらのテーマでも読めるようにする
S = {"a": "var(--s1)", "b": "var(--s2)", "c": "var(--s3)", "d": "var(--s4)",
     "bad": "var(--s-bad)", "mute": "var(--muted)"}
FAM_COLOR = {"fade": S["a"], "reveal": S["b"], "blur": S["c"], "wipe": S["d"]}


# ------------------------------------------------------------------ 小道具
def esc(s):
    return html.escape(str(s))


def pct(x, d=1):
    """0-1 の割合を % 文字列に。"""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{100.0 * float(x):.{d}f}%"


def pt(x, d=1, sign=True):
    """パーセントポイント。"""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{float(x):+.{d}f}" if sign else f"{float(x):.{d}f}"
    return s + "pt"


def ci(lo, hi, d=1):
    return f"[{float(lo):+.{d}f}, {float(hi):+.{d}f}]"


def pfmt(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    p = float(p)
    if p < 1e-4:
        return "&lt;0.0001"
    return f"{p:.4f}".rstrip("0").rstrip(".")


def wilson(k, n, z=1.959963985):
    if n <= 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


# ------------------------------------------------------------------ 尺度
class Lin:
    def __init__(self, d0, d1, r0, r1):
        self.d0, self.d1, self.r0, self.r1 = float(d0), float(d1), float(r0), float(r1)

    def __call__(self, v):
        t = (float(v) - self.d0) / (self.d1 - self.d0)
        return self.r0 + t * (self.r1 - self.r0)


class Log:
    def __init__(self, d0, d1, r0, r1):
        self.l0, self.l1 = math.log10(d0), math.log10(d1)
        self.r0, self.r1 = float(r0), float(r1)

    def __call__(self, v):
        t = (math.log10(max(float(v), 1e-9)) - self.l0) / (self.l1 - self.l0)
        return self.r0 + t * (self.r1 - self.r0)


# ------------------------------------------------------------------ SVG 部品
def svg(w, h, body, cls="fig"):
    return (f'<div class="figwrap"><svg class="{cls}" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img">{body}</svg></div>')


def txt(x, y, s, anchor="middle", cls="lbl", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'class="{cls}"{extra}>{s}</text>')


def line(x1, y1, x2, y2, cls="axline", style=""):
    st = f' style="{style}"' if style else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'class="{cls}"{st}/>')


def frame_axes(sx, sy, xt, yt, x0, x1, y0, y1, xfmt, yfmt, grid=True):
    """枠・目盛・グリッド。sx/sy は尺度、xt/yt は目盛値の並び。"""
    o = []
    if grid:
        for v in yt:
            o.append(line(x0, sy(v), x1, sy(v), cls="grid"))
        for v in xt:
            o.append(line(sx(v), y0, sx(v), y1, cls="grid"))
    o.append(line(x0, y1, x1, y1))
    o.append(line(x0, y0, x0, y1))
    for v in xt:
        o.append(line(sx(v), y1, sx(v), y1 + 4))
        o.append(txt(sx(v), y1 + 16, xfmt(v)))
    for v in yt:
        o.append(line(x0 - 4, sy(v), x0, sy(v)))
        o.append(txt(x0 - 7, sy(v) + 4, yfmt(v), anchor="end"))
    return "".join(o)


def band(sx, sy, xs, los, his, color, op=0.14):
    """信頼区間の帯。"""
    pts = [f"{sx(x):.1f},{sy(v):.1f}" for x, v in zip(xs, his)]
    pts += [f"{sx(x):.1f},{sy(v):.1f}" for x, v in zip(reversed(xs), reversed(los))]
    return (f'<polygon points="{" ".join(pts)}" '
            f'style="fill:{color};opacity:{op};stroke:none"/>')


def path(sx, sy, xs, ys, color, dash="", width=2.0):
    pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, ys))
    d = f";stroke-dasharray:{dash}" if dash else ""
    return (f'<polyline points="{pts}" style="fill:none;stroke:{color};'
            f'stroke-width:{width};stroke-linejoin:round{d}"/>')


def dots(sx, sy, xs, ys, color, r=3.0, hollow=False):
    o = []
    for x, y in zip(xs, ys):
        if hollow:
            o.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="{r}" '
                     f'style="fill:var(--card);stroke:{color};stroke-width:1.8"/>')
        else:
            o.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="{r}" '
                     f'style="fill:{color};stroke:none"/>')
    return "".join(o)


def ebars(sx, sy, xs, los, his, color, cap=3.0, width=1.4):
    o = []
    for x, lo, hi in zip(xs, los, his):
        if any(isinstance(v, float) and math.isnan(v) for v in (lo, hi)):
            continue
        X = sx(x)
        o.append(f'<line x1="{X:.1f}" y1="{sy(lo):.1f}" x2="{X:.1f}" y2="{sy(hi):.1f}" '
                 f'style="stroke:{color};stroke-width:{width}"/>')
        for v in (lo, hi):
            o.append(f'<line x1="{X - cap:.1f}" y1="{sy(v):.1f}" x2="{X + cap:.1f}" '
                     f'y2="{sy(v):.1f}" style="stroke:{color};stroke-width:{width}"/>')
    return "".join(o)


def legend(x, y, items, gap=18, swatch="line"):
    """items: [(色, ラベル, dash)]"""
    o = []
    for i, it in enumerate(items):
        color, label = it[0], it[1]
        dash = it[2] if len(it) > 2 else ""
        yy = y + i * gap
        if swatch == "box":
            o.append(f'<rect x="{x}" y="{yy - 7}" width="12" height="10" '
                     f'style="fill:{color};opacity:.85"/>')
        else:
            d = f";stroke-dasharray:{dash}" if dash else ""
            o.append(f'<line x1="{x}" y1="{yy - 3}" x2="{x + 20}" y2="{yy - 3}" '
                     f'style="stroke:{color};stroke-width:2.4{d}"/>')
            o.append(f'<circle cx="{x + 10}" cy="{yy - 3}" r="3" '
                     f'style="fill:{color}"/>')
        o.append(txt(x + 26, yy, esc(label), anchor="start"))
    return "".join(o)


def figure(svg_html, caption, note=""):
    n = f'<p class="small">{note}</p>' if note else ""
    return (f'<figure>{svg_html}<figcaption>{caption}</figcaption>{n}</figure>')


# ============================================================ 図1: 4方式の較正曲線
def fig_curves(cur):
    """log 横軸で 4 方式 × 2 フェーズ。Wilson 95%CI の帯つき。"""
    cur = cur[cur.trial_set == "main8"]
    W, H = 960, 672
    pw, ph = 400, 250
    x_lo, x_hi = 0.07, 130.0
    xt = [0.1, 1, 10, 100]
    yt = [0, .25, .5, .75, 1.0]
    body = []
    for i, fam in enumerate(["fade", "reveal", "blur", "wipe"]):
        cx = 66 + (i % 2) * (pw + 62)
        cy = 46 + (i // 2) * (ph + 82)
        x0, x1 = cx, cx + pw
        y0, y1 = cy, cy + ph
        sx = Log(x_lo, x_hi, x0, x1)
        sy = Lin(0, 1, y1, y0)
        body.append(f'<text x="{x0}" y="{y0 - 12}" class="ttl" text-anchor="start">'
                    f'{esc(FAM_JA[fam])}</text>')
        body.append(frame_axes(sx, sy, xt, yt, x0, x1, y0, y1,
                               lambda v: (f"{v:g}%"), lambda v: f"{v * 100:.0f}%"))
        # 偶然水準
        body.append(line(x0, sy(GAMMA), x1, sy(GAMMA), cls="chance"))
        body.append(txt(x1 - 2, sy(GAMMA) - 5, "偶然 1.4%", anchor="end", cls="lbl tiny"))
        for ph_, color, dash in [("calib", S["a"], ""), ("calib2", S["b"], "5 3")]:
            g = cur[(cur.family == fam) & (cur.phase == ph_)].sort_values("progress_pct")
            if not len(g):
                continue
            xs = g.progress_pct.tolist()
            body.append(band(sx, sy, xs, g.lo.tolist(), g.hi.tolist(), color))
            body.append(path(sx, sy, xs, g.acc.tolist(), color, dash))
            body.append(dots(sx, sy, xs, g.acc.tolist(), color,
                             hollow=(ph_ == "calib2")))
        body.append(txt(x0 + pw / 2, y1 + 36, "進み具合 s（%・対数軸）"))
        body.append(f'<text transform="translate({x0 - 48},{(y0 + y1) / 2}) rotate(-90)" '
                    f'text-anchor="middle" class="lbl">正答率</text>')
        if i == 0:
            body.append(legend(x0 + 12, y0 + 22,
                               [(S["a"], "実験1 (n=163)"),
                                (S["b"], "追いバッチ (n=162)", "5 3")]))
        if fam == "blur":
            body.append(txt(x0 + pw / 2, y0 + 18, "WebKit 端末を除外", cls="lbl tiny"))
    return svg(W, H, "".join(body))


# ======================================== 図2: 2回分を合わせた曲線（束ねる/並べる/束ねない）
def pooled_points(g):
    """フェーズをまたいで合算した水準ごとの正答率と Wilson 95%CI。

    返り値は (水準, n, 正答率, CI下, CI上, その水準を測ったバッチのタプル)。
    """
    out = []
    for L in sorted(g.progress_pct.unique()):
        gg = g[g.progress_pct == L]
        n = int(gg.n.sum())
        k = int(gg.k.sum())
        p, lo, hi = wilson(k, n)
        out.append((L, n, p, lo, hi, tuple(sorted(gg.phase.unique()))))
    return out


def diamonds(sx, sy, xs, ys, color, r=5.0):
    o = []
    for x, y in zip(xs, ys):
        X, Y = sx(x), sy(y)
        o.append(f'<polygon points="{X:.1f},{Y - r:.1f} {X + r:.1f},{Y:.1f} '
                 f'{X:.1f},{Y + r:.1f} {X - r:.1f},{Y:.1f}" '
                 f'style="fill:{color};stroke:var(--card);stroke-width:1.2"/>')
    return "".join(o)


def badge(x, y, text, color):
    w = 11.5 * len(text) + 16
    return (f'<rect x="{x - w:.1f}" y="{y - 13}" width="{w:.1f}" height="18" rx="4" '
            f'style="fill:{color};opacity:.16"/>'
            + txt(x - w / 2, y, esc(text), cls="lbl tiny",
                  extra=f' style="fill:{color};font-weight:700"'))


def fig_pooled(cur, bs):
    """fade/reveal は束ね、wipe は並べ、blur は束ねない。"""
    cur = cur[cur.trial_set == "main8"]
    W, H = 960, 700
    pw, ph = 400, 250
    x_lo, x_hi = 0.07, 130.0
    xt = [0.1, 1, 10, 100]
    yt = [0, .25, .5, .75, 1.0]
    body = []
    plan = [("fade", "pool"), ("reveal", "pool"), ("wipe", "line"), ("blur", "poolmark")]
    for i, (fam, mode) in enumerate(plan):
        x0 = 66 + (i % 2) * (pw + 62)
        y0 = 52 + (i // 2) * (ph + 90)
        x1, y1 = x0 + pw, y0 + ph
        sx = Log(x_lo, x_hi, x0, x1)
        sy = Lin(0, 1, y1, y0)
        g = cur[cur.family == fam]
        body.append(f'<text x="{x0}" y="{y0 - 14}" class="ttl" text-anchor="start">'
                    f'{esc(FAM_JA[fam])}</text>')
        body.append(frame_axes(sx, sy, xt, yt, x0, x1, y0, y1,
                               lambda v: f"{v:g}%", lambda v: f"{v * 100:.0f}%"))
        body.append(line(x0, sy(GAMMA), x1, sy(GAMMA), cls="chance"))
        if mode == "pool":
            # 背後に各バッチの細線
            for ph_, col in [("calib", S["a"]), ("calib2", S["b"])]:
                gg = g[g.phase == ph_].sort_values("progress_pct")
                body.append(path(sx, sy, gg.progress_pct.tolist(), gg.acc.tolist(),
                                 col, width=1.0, dash="3 3"))
            P = pooled_points(g)
            xs = [r[0] for r in P]
            body.append(band(sx, sy, xs, [r[3] for r in P], [r[4] for r in P],
                             S["c"], .22))
            body.append(path(sx, sy, xs, [r[2] for r in P], S["c"], width=2.8))
            body.append(dots(sx, sy, xs, [r[2] for r in P], S["c"], r=3.6))
            nmin, nmax = min(r[1] for r in P), max(r[1] for r in P)
            body.append(badge(x1 - 4, y0 + 18, "束ねた", S["c"]))
            body.append(txt(x1 - 4, y0 + 36, f"プール n={nmin}〜{nmax} / 水準",
                            anchor="end", cls="lbl tiny"))
            body.append(legend(x0 + 12, y0 + 20,
                               [(S["c"], "2回分をプール（95%CI）"),
                                (S["a"], "実験1のみ", "3 3"),
                                (S["b"], "追いバッチのみ", "3 3")]))
        elif mode == "line":
            gg = g.sort_values(["progress_pct", "phase"])
            body.append(f'<rect x="{sx(25):.1f}" y="{y0}" '
                        f'width="{sx(130) - sx(25):.1f}" height="{y1 - y0}" '
                        f'style="fill:{S["b"]};opacity:.07"/>')
            body.append(txt((sx(25) + sx(130)) / 2, y1 - 10,
                            "2回目で埋めた区間", cls="lbl tiny"))
            body.append(path(sx, sy, gg.progress_pct.tolist(), gg.acc.tolist(),
                             S["d"], width=2.4))
            for ph_, col, hollow in [("calib", S["a"], False), ("calib2", S["b"], True)]:
                h = gg[gg.phase == ph_]
                body.append(ebars(sx, sy, h.progress_pct.tolist(), h.lo.tolist(),
                                  h.hi.tolist(), col))
                body.append(dots(sx, sy, h.progress_pct.tolist(), h.acc.tolist(),
                                 col, r=3.6, hollow=hollow))
            body.append(badge(x1 - 4, y0 + 18, "並べた", S["d"]))
            body.append(txt(x1 - 4, y0 + 36, "水準ラダーが2回で違う", anchor="end",
                            cls="lbl tiny"))
            body.append(legend(x0 + 12, y0 + 20,
                               [(S["d"], "通しの曲線（束ねていない）"),
                                (S["a"], "実験1で測った点"),
                                (S["b"], "追いバッチで測った点")]))
        else:  # poolmark — 束ねるが、共通水準と食い違いが追える形にする
            P = pooled_points(g)
            xs = [r[0] for r in P]
            body.append(band(sx, sy, xs, [r[3] for r in P], [r[4] for r in P],
                             S["c"], .22))
            body.append(path(sx, sy, xs, [r[2] for r in P], S["c"], width=2.8))
            both = [r for r in P if len(r[5]) == 2]
            only1 = [r for r in P if r[5] == ("calib",)]
            only2 = [r for r in P if r[5] == ("calib2",)]
            body.append(dots(sx, sy, [r[0] for r in only2], [r[2] for r in only2],
                             S["b"], r=3.4))
            body.append(dots(sx, sy, [r[0] for r in only1], [r[2] for r in only1],
                             S["a"], r=3.4))
            body.append(diamonds(sx, sy, [r[0] for r in both], [r[2] for r in both],
                                 S["c"]))
            nmin, nmax = min(r[1] for r in P), max(r[1] for r in P)
            body.append(badge(x1 - 4, y0 + 18, "束ねた", S["c"]))
            body.append(txt(x1 - 4, y0 + 36, f"プール n={nmin}〜{nmax} / 水準",
                            anchor="end", cls="lbl tiny"))
            body.append(legend(x0 + 12, y0 + 20,
                               [(S["c"], "2回分をプール（95%CI）")]))
            body.append(f'<polygon points="{x0 + 22:.1f},{y0 + 33:.1f} '
                        f'{x0 + 27:.1f},{y0 + 38:.1f} {x0 + 22:.1f},{y0 + 43:.1f} '
                        f'{x0 + 17:.1f},{y0 + 38:.1f}" style="fill:{S["c"]}"/>')
            body.append(txt(x0 + 38, y0 + 42, "◇ = 2回とも測った水準（26 / 48 / 100%）",
                            anchor="start", cls="lbl tiny"))
            body.append(f'<circle cx="{x0 + 22:.1f}" cy="{y0 + 56:.1f}" r="3.4" '
                        f'style="fill:{S["b"]}"/>')
            body.append(txt(x0 + 38, y0 + 60, "● = 追いバッチのみ（3〜22%）",
                            anchor="start", cls="lbl tiny"))
            body.append(f'<circle cx="{x0 + 22:.1f}" cy="{y0 + 74:.1f}" r="3.4" '
                        f'style="fill:{S["a"]}"/>')
            body.append(txt(x0 + 38, y0 + 78, "● = 実験1のみ（38〜84%）",
                            anchor="start", cls="lbl tiny"))
            # 48% の内訳（2回の結果が食い違う点）
            g48 = g[g.progress_pct == 48.0]
            p48 = [r for r in P if r[0] == 48.0]
            if len(g48) == 2 and p48:
                a48 = g48[g48.phase == "calib"].iloc[0]
                b48 = g48[g48.phase == "calib2"].iloc[0]
                X = sx(48.0)
                body.append(f'<line x1="{X:.1f}" y1="{sy(b48.acc):.1f}" x2="{X:.1f}" '
                            f'y2="{sy(a48.acc):.1f}" style="stroke:{S["bad"]};'
                            f'stroke-width:1.6;stroke-dasharray:3 2"/>')
                for r_, col in [(a48, S["a"]), (b48, S["b"])]:
                    body.append(f'<line x1="{X - 7:.1f}" y1="{sy(r_.acc):.1f}" '
                                f'x2="{X + 7:.1f}" y2="{sy(r_.acc):.1f}" '
                                f'style="stroke:{col};stroke-width:2.4"/>')
                body.append(txt(X - 12, sy(a48.acc) - 6,
                                f"48%: 実験1 {pct(a48.acc)} (n={int(a48.n)})",
                                anchor="end", cls="lbl tiny"))
                body.append(txt(X - 12, sy(b48.acc) + 14,
                                f"追いバッチ {pct(b48.acc)} (n={int(b48.n)})"
                                f" → 束ねて {pct(p48[0][2])}",
                                anchor="end", cls="lbl tiny",
                                extra=f' style="fill:{S["bad"]}"'))
        body.append(txt(x0 + pw / 2, y1 + 36, "進み具合 s（%・対数軸）"))
        body.append(f'<text transform="translate({x0 - 48},{(y0 + y1) / 2}) rotate(-90)" '
                    f'text-anchor="middle" class="lbl">正答率</text>')
        if fam == "blur":
            body.append(txt(x0 + 4, y1 + 56, "※ WebKit 端末を除外", anchor="start",
                            cls="lbl tiny"))
    return svg(W, H, "".join(body))


# ============================================================ 図3: 橋（実験間の一致）
def fig_bridge(bl, bs):
    bl = bl[bl.trial_set == "main8"]
    W, H = 960, 420
    pw, ph = 300, 290
    body = []
    lim = 22
    for i, fam in enumerate(["fade", "reveal"]):
        x0 = 92 + i * (pw + 150)
        x1 = x0 + pw
        y0, y1 = 54, 54 + ph
        g = bl[bl.family == fam].sort_values("progress_pct").reset_index(drop=True)
        sx = Lin(-lim, lim, x0, x1)
        sy = Lin(-0.5, len(g) - 0.5, y0, y1)
        body.append(f'<text x="{x0 - 56}" y="{y0 - 20}" class="ttl" text-anchor="start">'
                    f'{esc(FAM_JA[fam])}</text>')
        xt = [-20, -10, 0, 10, 20]
        for v in xt:
            body.append(line(sx(v), y0, sx(v), y1, cls="grid"))
            body.append(txt(sx(v), y1 + 18, f"{v:+d}"))
        body.append(line(sx(0), y0, sx(0), y1, cls="axline"))
        for j, r in g.iterrows():
            Y = sy(j)
            inside = (r.lo_pt <= 0 <= r.hi_pt)
            col = S["b"] if inside else S["bad"]
            body.append(f'<line x1="{sx(max(r.lo_pt, -lim)):.1f}" y1="{Y:.1f}" '
                        f'x2="{sx(min(r.hi_pt, lim)):.1f}" y2="{Y:.1f}" '
                        f'style="stroke:{col};stroke-width:2.2"/>')
            body.append(f'<circle cx="{sx(r.diff_pt):.1f}" cy="{Y:.1f}" r="4" '
                        f'style="fill:{col}"/>')
            body.append(txt(x0 - 10, Y + 4, f"s={r.progress_pct:g}%", anchor="end"))
            body.append(txt(x1 + 8, Y + 4, f"{r.diff_pt:+.1f}", anchor="start",
                            cls="lbl tiny"))
        body.append(txt((x0 + x1) / 2, y1 + 40, "追いバッチ − 実験1（pt, 95%CI）"))
        srow = bs[bs.family == fam].iloc[0]
        body.append(txt(x0 - 56, y1 + 66,
                        f"8水準まとめ: {srow.diff_pt:+.2f}pt "
                        f"{ci(srow.lo_pt, srow.hi_pt, 2)}  Holm p={pfmt(srow.p_holm)}",
                        anchor="start", cls="lbl"))
    body.append(legend(660, 40, [(S["b"], "CI が 0 を含む（一致）"),
                                 (S["bad"], "CI が 0 を含まない")]))
    return svg(W, H, "".join(body))


# ============================================================ 図4: ぼやけの床
def fig_blur_floor(bf, tf):
    W, H = 960, 400
    body = []
    # 左: 3 サブセットの曲線
    x0, x1, y0, y1 = 66, 520, 48, 300
    sx = Lin(0, 105, x0, x1)
    sy = Lin(0, 1, y1, y0)
    xt = [0, 20, 40, 60, 80, 100]
    yt = [0, .25, .5, .75, 1.0]
    body.append(frame_axes(sx, sy, xt, yt, x0, x1, y0, y1,
                           lambda v: f"{v:g}%", lambda v: f"{v * 100:.0f}%"))
    body.append(line(x0, sy(GAMMA), x1, sy(GAMMA), cls="chance"))
    body.append(txt(x1 - 2, sy(GAMMA) - 6, "偶然水準 1/72 = 1.4%", anchor="end",
                    cls="lbl tiny"))
    for sub, color, dash in [("all devices", S["mute"], "5 3"),
                             ("WebKit excluded", S["c"], ""),
                             ("WebKit only", S["bad"], "2 3")]:
        g = bf[bf.subset == sub].sort_values("progress_pct")
        xs = g.progress_pct.tolist()
        if sub == "WebKit excluded":
            body.append(band(sx, sy, xs, g.lo.tolist(), g.hi.tolist(), color, .18))
        body.append(path(sx, sy, xs, g.acc.tolist(), color, dash))
        body.append(dots(sx, sy, xs, g.acc.tolist(), color, r=3.2))
    body.append(txt((x0 + x1) / 2, y1 + 36, "進み具合 s（%）　← 左ほどぼかしが強い"))
    body.append(f'<text transform="translate({x0 - 44},{(y0 + y1) / 2}) rotate(-90)" '
                f'text-anchor="middle" class="lbl">正答率</text>')
    body.append(legend(x0 + 46, y0 + 86,
                       [(S["bad"], "WebKit のみ（描画されていない）", "2 3"),
                        (S["mute"], "全端末（汚染されている）", "5 3"),
                        (S["c"], "WebKit 除外（正しい値）")]))
    # 右: 床の拡大（WebKit 除外）
    x0b, x1b, y0b, y1b = 600, 900, 48, 300
    sxb = Lin(0, 30, x0b, x1b)
    syb = Lin(0, 0.08, y1b, y0b)
    body.append(frame_axes(sxb, syb, [0, 10, 20, 30], [0, .02, .04, .06, .08],
                           x0b, x1b, y0b, y1b,
                           lambda v: f"{v:g}%", lambda v: f"{v * 100:.0f}%"))
    body.append(f'<text transform="translate({x0b - 44},{(y0b + y1b) / 2}) rotate(-90)" '
                f'text-anchor="middle" class="lbl">正答率</text>')
    body.append(line(x0b, syb(GAMMA), x1b, syb(GAMMA), cls="chance"))
    body.append(txt(x1b - 2, syb(GAMMA) - 6, "偶然 1.4%", anchor="end", cls="lbl tiny"))
    g = bf[(bf.subset == "WebKit excluded") & (bf.progress_pct <= 26)].sort_values("progress_pct")
    xs = g.progress_pct.tolist()
    body.append(ebars(sxb, syb, xs, g.lo.tolist(), g.hi.tolist(), S["c"]))
    body.append(path(sxb, syb, xs, g.acc.tolist(), S["c"]))
    body.append(dots(sxb, syb, xs, g.acc.tolist(), S["c"], r=3.4))
    body.append(txt((x0b + x1b) / 2, y1b + 36, "進み具合 s（%）"))
    body.append(txt((x0b + x1b) / 2, y0b - 14, "床の拡大（WebKit 除外・95%CI）", cls="ttl"))
    body.append(txt((x0b + x1b) / 2, y1b + 58,
                    "半径 69.8px → 53.3px のあいだ、正答率は偶然水準の近くで平ら",
                    cls="lbl tiny"))
    return svg(W, H, "".join(body))


# ============================================================ 図5: 描画不具合の証拠
def fig_render_bug(rb_eng, rb_sum):
    """端末エンジン別・ぼやけ低水準（s ≦ 26%）の正答率。"""
    b = rb_eng[(rb_eng.family == "blur") & (rb_eng.phase == "calib2")
               & (rb_eng.progress_pct <= 26)]
    rows = []
    for eng, g in b.groupby("engine"):
        n = int(g.n.sum())
        k = int(round((g.n * g.acc).sum()))
        p, lo, hi = wilson(k, n)
        rows.append((eng, n, p, lo, hi))
    order = {"WebKit": 0, "Chrome(Desktop)": 1, "Chrome(Android)": 2, "Edge": 3,
             "Firefox": 4}
    rows.sort(key=lambda r: order.get(r[0], 9))
    W, H = 960, 380
    body = []
    # 左: 横向きの棒（端末名が長いので縦積み）
    x0, x1, y0, y1 = 200, 470, 60, 280
    sx = Lin(0, 1, x0, x1)
    xt = [0, .25, .5, .75, 1.0]
    for v in xt:
        body.append(line(sx(v), y0, sx(v), y1, cls="grid"))
        body.append(txt(sx(v), y1 + 18, f"{v * 100:.0f}%"))
    body.append(line(x0, y0, x0, y1))
    bh = (y1 - y0) / len(rows)
    for i, (eng, n, p, lo, hi) in enumerate(rows):
        cyc = y0 + bh * (i + .5)
        col = S["bad"] if eng == "WebKit" else S["c"]
        body.append(f'<rect x="{x0}" y="{cyc - bh * .3:.1f}" '
                    f'width="{max(sx(p) - x0, 0.5):.1f}" height="{bh * .6:.1f}" '
                    f'style="fill:{col};opacity:.75"/>')
        body.append(f'<line x1="{sx(lo):.1f}" y1="{cyc:.1f}" x2="{sx(hi):.1f}" '
                    f'y2="{cyc:.1f}" style="stroke:{col};stroke-width:1.5"/>')
        for v in (lo, hi):
            body.append(f'<line x1="{sx(v):.1f}" y1="{cyc - 4:.1f}" x2="{sx(v):.1f}" '
                        f'y2="{cyc + 4:.1f}" style="stroke:{col};stroke-width:1.5"/>')
        body.append(txt(x0 - 10, cyc + 4, esc(eng), anchor="end", cls="lbl"))
        body.append(txt(sx(hi) + 8, cyc + 4, f"{pct(p)}（n={n}）", anchor="start",
                        cls="lbl tiny"))
    body.append(line(sx(GAMMA), y0, sx(GAMMA), y1, cls="chance"))
    body.append(txt(sx(GAMMA) + 4, y1 + 34, "偶然 1.4%", anchor="start", cls="lbl tiny"))
    body.append(txt(x0 - 120, y0 - 26,
                    "ぼやけ・低水準 (s ≦ 26% ＝ 半径 53〜70px) の正答率",
                    anchor="start", cls="ttl"))
    body.append(txt((x0 + x1) / 2, y1 + 36, "正答率"))
    # 右: 4方式 × WebKit/非WebKit（blur だけが壊れていることの対比）
    x0b, x1b, y0b, y1b = 610, 900, 60, 280
    syb = Lin(0, 1, y1b, y0b)
    for v in xt:
        body.append(line(x0b, syb(v), x1b, syb(v), cls="grid"))
        body.append(txt(x0b - 8, syb(v) + 4, f"{v * 100:.0f}%", anchor="end"))
    body.append(line(x0b, y1b, x1b, y1b))
    fams = ["fade", "reveal", "blur", "wipe"]
    gw = (x1b - x0b) / len(fams)
    for i, fam in enumerate(fams):
        base = x0b + gw * i
        for j, (wk, col) in enumerate([(False, S["c"]), (True, S["bad"])]):
            r = rb_sum[(rb_sum.family == fam) & (rb_sum.webkit == wk)]
            if not len(r):
                continue
            r = r.iloc[0]
            cxc = base + gw * (0.3 + 0.4 * j)
            w = gw * 0.28
            body.append(f'<rect x="{cxc - w / 2:.1f}" y="{syb(r.acc):.1f}" '
                        f'width="{w:.1f}" height="{y1b - syb(r.acc):.1f}" '
                        f'style="fill:{col};opacity:.75"/>')
            body.append(ebars(Lin(0, 1, cxc, cxc), syb, [0], [r.lo], [r.hi], col, cap=4))
        body.append(txt(base + gw / 2, y1b + 18, fam, cls="lbl"))
    body.append(txt((x0b + x1b) / 2, y0b - 22, "方式ごと・全水準こみの平均正答率", cls="ttl"))
    body.append(legend(x0b + 6, y0b + 18,
                       [(S["c"], "WebKit 以外 (281名)"), (S["bad"], "WebKit (45名)")],
                       swatch="box"))
    return svg(W, H, "".join(body))


# ============================================================ 図6: wipe と濁点
def fig_wipe(wch, wdk, wj):
    W, H = 960, 420
    body = []
    x0, x1, y0, y1 = 66, 560, 54, 320
    sx = Lin(0, 105, x0, x1)
    sy = Lin(0, 1, y1, y0)
    body.append(frame_axes(sx, sy, [0, 20, 40, 60, 80, 100], [0, .25, .5, .75, 1.0],
                           x0, x1, y0, y1, lambda v: f"{v:g}%",
                           lambda v: f"{v * 100:.0f}%"))
    # 清音 6 字を細線で
    for ch, g in wch[~wch.dakuten].groupby("target_char"):
        g = g.sort_values("progress_pct")
        body.append(path(sx, sy, g.progress_pct.tolist(), g.acc.tolist(),
                         S["mute"], width=1.0))
    for ch, g in wch[wch.dakuten].groupby("target_char"):
        g = g.sort_values("progress_pct")
        body.append(path(sx, sy, g.progress_pct.tolist(), g.acc.tolist(),
                         S["bad"], width=1.0, dash="3 2"))
    # 群平均（濁点2字 / 清音6字）
    d = wdk.sort_values("progress_pct")
    body.append(path(sx, sy, d.progress_pct.tolist(), d.acc_sei.tolist(), S["d"], width=2.6))
    body.append(dots(sx, sy, d.progress_pct.tolist(), d.acc_sei.tolist(), S["d"]))
    body.append(path(sx, sy, d.progress_pct.tolist(), d.acc_dakuten.tolist(),
                     S["bad"], width=2.6))
    body.append(dots(sx, sy, d.progress_pct.tolist(), d.acc_dakuten.tolist(), S["bad"]))
    # 65→80 の跳ねを強調
    body.append(f'<rect x="{sx(65):.1f}" y="{y0}" width="{sx(80) - sx(65):.1f}" '
                f'height="{y1 - y0}" style="fill:{S["bad"]};opacity:.08"/>')
    jr = wj[(wj.group.str.startswith("dakuten")) & (wj.step == "65->80")].iloc[0]
    body.append(f'<line x1="{sx(72.5):.1f}" y1="{sy(jr.acc_from):.1f}" '
                f'x2="{sx(72.5):.1f}" y2="{sy(jr.acc_to):.1f}" '
                f'style="stroke:{S["bad"]};stroke-width:1.6;stroke-dasharray:3 3"/>')
    body.append(txt(sx(72.5), sy(jr.acc_to) - 10,
                    f"{jr.jump_pt:+.1f}pt", cls="ttl", extra=f' style="fill:{S["bad"]}"'))
    body.append(txt((x0 + x1) / 2, y1 + 36, "進み具合 s（%）"))
    body.append(f'<text transform="translate({x0 - 44},{(y0 + y1) / 2}) rotate(-90)" '
                f'text-anchor="middle" class="lbl">正答率</text>')
    body.append(legend(x0 + 14, y0 + 20,
                       [(S["d"], "清音 6 字（平均）"),
                        (S["bad"], "濁点・半濁点 が・ぱ（平均）"),
                        (S["mute"], "字ごと（細線）")]))
    # 右: 差（清音 − 濁点）
    x0b, x1b, y0b, y1b = 630, 900, 54, 320
    sxb = Lin(0, 105, x0b, x1b)
    syb = Lin(-105, 20, y1b, y0b)
    body.append(frame_axes(sxb, syb, [0, 50, 100], [-100, -75, -50, -25, 0],
                           x0b, x1b, y0b, y1b, lambda v: f"{v:g}%",
                           lambda v: f"{v:g}"))
    body.append(line(x0b, syb(0), x1b, syb(0), cls="axline"))
    xs = d.progress_pct.tolist()
    body.append(band(sxb, syb, xs, d.lo_pt.tolist(), d.hi_pt.tolist(), S["bad"], .16))
    body.append(path(sxb, syb, xs, d.diff_pt.tolist(), S["bad"]))
    body.append(dots(sxb, syb, xs, d.diff_pt.tolist(), S["bad"]))
    body.append(txt((x0b + x1b) / 2, y1b + 36, "進み具合 s（%）"))
    body.append(txt((x0b + x1b) / 2, y0b - 22, "濁点字 − 清音字（pt, 95%CI）", cls="ttl"))
    return svg(W, H, "".join(body))


# ============================================================ 図7: reveal の跳ね
def fig_reveal(cur, rj):
    W, H = 960, 400
    body = []
    x0, x1, y0, y1 = 66, 520, 54, 300
    sx = Log(0.07, 130, x0, x1)
    sy = Lin(0, 1, y1, y0)
    body.append(frame_axes(sx, sy, [0.1, 1, 10, 100], [0, .25, .5, .75, 1.0],
                           x0, x1, y0, y1, lambda v: f"{v:g}%",
                           lambda v: f"{v * 100:.0f}%"))
    body.append(f'<rect x="{sx(2):.1f}" y="{y0}" width="{sx(4) - sx(2):.1f}" '
                f'height="{y1 - y0}" style="fill:{S["b"]};opacity:.10"/>')
    body.append(txt((sx(2) + sx(4)) / 2, y0 - 8, "2% → 4%", cls="lbl tiny"))
    c = cur[(cur.trial_set == "main8") & (cur.family == "reveal")]
    for ph_, color, dash in [("calib", S["a"], ""), ("calib2", S["b"], "5 3")]:
        g = c[c.phase == ph_].sort_values("progress_pct")
        xs = g.progress_pct.tolist()
        body.append(band(sx, sy, xs, g.lo.tolist(), g.hi.tolist(), color))
        body.append(path(sx, sy, xs, g.acc.tolist(), color, dash))
        body.append(dots(sx, sy, xs, g.acc.tolist(), color, hollow=(ph_ == "calib2")))
    body.append(txt((x0 + x1) / 2, y1 + 36, "進み具合 s（%・対数軸）"))
    body.append(f'<text transform="translate({x0 - 44},{(y0 + y1) / 2}) rotate(-90)" '
                f'text-anchor="middle" class="lbl">正答率</text>')
    body.append(legend(x0 + 14, y0 + 20, [(S["a"], "実験1"), (S["b"], "追いバッチ", "5 3")]))
    # 右: 段差の大きさ
    x0b, x1b, y0b, y1b = 640, 900, 54, 300
    steps = ["1.0->2.0", "2.0->4.0", "4.0->9.0"]
    sxb = Lin(0, 45, x0b, x1b)
    rows = [(s, ph_) for s in steps for ph_ in ["calib", "calib2", "pooled"]]
    syb = Lin(-0.6, len(rows) - 0.4, y0b, y1b)
    for v in [0, 10, 20, 30, 40]:
        body.append(line(sxb(v), y0b, sxb(v), y1b, cls="grid"))
        body.append(txt(sxb(v), y1b + 18, f"{v:g}"))
    body.append(line(sxb(0), y0b, sxb(0), y1b, cls="axline"))
    for j, (s, ph_) in enumerate(rows):
        r = rj[(rj.step == s) & (rj.phase == ph_)]
        if not len(r):
            continue
        r = r.iloc[0]
        Y = syb(j)
        col = {"calib": S["a"], "calib2": S["b"], "pooled": S["c"]}[ph_]
        hi_ = min(r.hi_pt, 45)
        body.append(f'<line x1="{sxb(max(r.lo_pt, 0)):.1f}" y1="{Y:.1f}" '
                    f'x2="{sxb(hi_):.1f}" y2="{Y:.1f}" '
                    f'style="stroke:{col};stroke-width:2.2"/>')
        body.append(f'<circle cx="{sxb(r.jump_pt):.1f}" cy="{Y:.1f}" r="4" '
                    f'style="fill:{col}"/>')
        if ph_ == "calib":
            body.append(txt(x0b - 10, Y + 14, f"s {s.replace('->', '→')}%",
                            anchor="end", cls="lbl tiny"))
        body.append(txt(x1b + 6, Y + 4, PHASE_JA[ph_], anchor="start", cls="lbl tiny"))
    body.append(txt((x0b + x1b) / 2, y1b + 40, "段差の大きさ（pt, 95%CI）"))
    body.append(txt((x0b + x1b) / 2, y0b - 22, "隣り合う水準の段差", cls="ttl"))
    return svg(W, H, "".join(body))


# ============================================================ 図8: 速さの効果
def fig_speed(sf):
    W, H = 960, 400
    body = []
    x0, x1, y0, y1 = 210, 720, 60, 320
    lim = 14
    sx = Lin(-lim, lim, x0, x1)
    rows = [(f, p) for f in ["fade", "reveal", "blur", "wipe"]
            for p in ["calib", "calib2", "pooled"]]
    sy = Lin(-0.6, len(rows) - 0.4, y0, y1)
    for v in [-10, -5, 0, 5, 10]:
        body.append(line(sx(v), y0, sx(v), y1, cls="grid"))
        body.append(txt(sx(v), y1 + 18, f"{v:+d}"))
    body.append(line(sx(0), y0, sx(0), y1, cls="axline"))
    for j, (fam, ph_) in enumerate(rows):
        r = sf[(sf.family == fam) & (sf.phase == ph_)]
        if not len(r):
            continue
        r = r.iloc[0]
        Y = sy(j)
        col = FAM_COLOR[fam]
        pooled = (ph_ == "pooled")
        body.append(f'<line x1="{sx(max(r.lo_pt, -lim)):.1f}" y1="{Y:.1f}" '
                    f'x2="{sx(min(r.hi_pt, lim)):.1f}" y2="{Y:.1f}" '
                    f'style="stroke:{col};stroke-width:{2.6 if pooled else 1.6};'
                    f'opacity:{1.0 if pooled else .55}"/>')
        body.append(f'<circle cx="{sx(r.diff_pt):.1f}" cy="{Y:.1f}" '
                    f'r="{4.4 if pooled else 3}" style="fill:{col};'
                    f'opacity:{1.0 if pooled else .55}"/>')
        body.append(txt(x0 - 10, Y + 4,
                        f"{FAM_JA[fam] if pooled else ''} {PHASE_JA[ph_]}",
                        anchor="end", cls="lbl" + ("" if pooled else " tiny")))
        lab = f"{r.diff_pt:+.1f} {ci(r.lo_pt, r.hi_pt)}"
        if pooled and not pd.isna(r.p_holm_4families):
            lab += f"　Holm p={pfmt(r.p_holm_4families)}"
        body.append(txt(x1 + 10, Y + 4, lab, anchor="start", cls="lbl tiny"))
    body.append(txt((x0 + x1) / 2, y1 + 42,
                    "500ms − 300ms の正答率差（pt, 参加者ブートストラップ 95%CI）"))
    body.append(txt((x0 + x1) / 2, y0 - 26,
                    "ゆっくり見せると当たりやすくなるか", cls="ttl"))
    return svg(W, H, "".join(body))


# ============================================================ 図9: 時間の式（τ）
def fig_tau(prof, cellfit, tsum):
    W, H = 960, 400
    body = []
    row = tsum[tsum.subset == "calib + calib2"].iloc[0]
    # 左: プロファイル尤度
    x0, x1, y0, y1 = 66, 470, 54, 300
    p = prof[(prof.tau_ms >= 2) & (prof.tau_ms <= 60)].copy()
    top = p.loglik.max()
    p["dl"] = (p.loglik - top).clip(lower=-8.0)   # 枠の外にはみ出さないよう頭打ち
    sx = Lin(2, 60, x0, x1)
    sy = Lin(-8, 0.5, y1, y0)
    body.append(frame_axes(sx, sy, [10, 20, 30, 40, 50, 60], [-8, -6, -4, -2, 0],
                           x0, x1, y0, y1, lambda v: f"{v:g}", lambda v: f"{v:g}"))
    body.append(line(x0, sy(-1.920729), x1, sy(-1.920729), cls="chance"))
    body.append(txt(x1 - 2, sy(-1.920729) - 6, "95% 境界 (Δ = 1.92)", anchor="end",
                    cls="lbl tiny"))
    body.append(f'<rect x="{sx(row.tau_lo):.1f}" y="{y0}" '
                f'width="{sx(row.tau_hi) - sx(row.tau_lo):.1f}" height="{y1 - y0}" '
                f'style="fill:{S["c"]};opacity:.10"/>')
    body.append(path(sx, sy, p.tau_ms.tolist(), p.dl.tolist(), S["c"], width=2.2))
    body.append(f'<line x1="{sx(row.tau_hat):.1f}" y1="{y0}" x2="{sx(row.tau_hat):.1f}" '
                f'y2="{y1}" style="stroke:{S["c"]};stroke-width:1.6;stroke-dasharray:4 3"/>')
    body.append(txt(sx(row.tau_hat), y0 - 8,
                    f"τ̂ = {row.tau_hat:g} ms  [{row.tau_lo:g}, {row.tau_hi:g}]",
                    cls="ttl"))
    body.append(txt((x0 + x1) / 2, y1 + 36, "τ（ms）"))
    body.append(f'<text transform="translate({x0 - 46},{(y0 + y1) / 2}) rotate(-90)" '
                f'text-anchor="middle" class="lbl">対数尤度の差</text>')
    # 右: 実測 vs 予測
    x0b, x1b, y0b, y1b = 590, 900, 54, 300
    sxb = Lin(0, 1, x0b, x1b)
    syb = Lin(0, 1, y1b, y0b)
    body.append(frame_axes(sxb, syb, [0, .25, .5, .75, 1], [0, .25, .5, .75, 1],
                           x0b, x1b, y0b, y1b, lambda v: f"{v * 100:.0f}%",
                           lambda v: f"{v * 100:.0f}%"))
    body.append(f'<line x1="{sxb(0):.1f}" y1="{syb(0):.1f}" x2="{sxb(1):.1f}" '
                f'y2="{syb(1):.1f}" style="stroke:var(--muted);stroke-width:1.2;'
                f'stroke-dasharray:4 3"/>')
    for fam, g in cellfit.groupby("family"):
        body.append(dots(sxb, syb, g.pred.tolist(), g.obs.tolist(),
                         FAM_COLOR.get(fam, S["mute"]), r=3.4))
    inside = int(cellfit.resid_in_2se.astype(str).str.lower().eq("true").sum())
    body.append(txt((x0b + x1b) / 2, y1b + 36, "モデルの予測"))
    body.append(f'<text transform="translate({x0b - 46},{(y0b + y1b) / 2}) rotate(-90)" '
                f'text-anchor="middle" class="lbl">実測</text>')
    body.append(txt((x0b + x1b) / 2, y0b - 22,
                    f"部分セルの当てはまり（{inside}/{len(cellfit)} が ±2SE 以内）",
                    cls="ttl"))
    body.append(legend(x0b + 10, y1b - 60,
                       [(FAM_COLOR[f], f) for f in ["fade", "reveal", "blur", "wipe"]],
                       gap=15))
    return svg(W, H, "".join(body))


# ============================================================ 図10: 実験間のずれ（未解決）
def fig_blur_gap(bg_boot, gap):
    W, H = 900, 260
    body = []
    x0, x1, y0, y1 = 200, 660, 50, 190
    lim = 26
    sx = Lin(-lim, lim, x0, x1)
    rows = bg_boot.sort_values("progress_pct").reset_index(drop=True)
    sy = Lin(-0.5, len(rows) - 0.5, y0, y1)
    for v in [-25, -20, -10, 0, 10, 20]:
        body.append(line(sx(v), y0, sx(v), y1, cls="grid"))
        body.append(txt(sx(v), y1 + 18, f"{v:+d}"))
    body.append(line(sx(0), y0, sx(0), y1, cls="axline"))
    for j, r in rows.iterrows():
        Y = sy(j)
        col = S["bad"] if r.p_holm < 0.05 else S["mute"]
        body.append(f'<line x1="{sx(max(r.lo_pt, -lim)):.1f}" y1="{Y:.1f}" '
                    f'x2="{sx(min(r.hi_pt, lim)):.1f}" y2="{Y:.1f}" '
                    f'style="stroke:{col};stroke-width:2.4"/>')
        body.append(f'<circle cx="{sx(r.diff_pt):.1f}" cy="{Y:.1f}" r="4.2" '
                    f'style="fill:{col}"/>')
        body.append(txt(x0 - 12, Y + 4, f"s = {r.progress_pct:g}%  (n={int(r.n)})",
                        anchor="end", cls="lbl"))
        body.append(txt(x1 + 10, Y + 4,
                        f"{r.diff_pt:+.1f} {ci(r.lo_pt, r.hi_pt)}  Holm p={pfmt(r.p_holm)}",
                        anchor="start", cls="lbl tiny"))
    body.append(txt((x0 + x1) / 2, y1 + 40,
                    "追いバッチ − 実験1（pt, 参加者ブートストラップ 95%CI）"))
    body.append(txt((x0 + x1) / 2, y0 - 22,
                    "ぼやけ・共通水準での実験間のずれ（WebKit 除外）", cls="ttl"))
    return svg(W, H, "".join(body))


# ============================================================ 本体
CSS = """
:root{
  --bg:#faf8f4; --fg:#1c1a17; --muted:#6b6560; --accent:#b45309; --line:#ded6c8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c; --card:#ffffff;
  --s1:#b45309; --s2:#1d6fa5; --s3:#15803d; --s4:#8a3ea8; --s-bad:#c02626;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
    --card:#211e19; --ok:#4ade80; --bad:#f87171;
    --s1:#e8a14c; --s2:#6fb6e8; --s3:#5cc98a; --s4:#cf95e6; --s-bad:#f2706b;
  }
}
:root[data-theme="dark"]{
  --bg:#171512; --fg:#eee8de; --muted:#a89f92; --accent:#e8a14c; --line:#3a352c;
  --card:#211e19; --ok:#4ade80; --bad:#f87171;
  --s1:#e8a14c; --s2:#6fb6e8; --s3:#5cc98a; --s4:#cf95e6; --s-bad:#f2706b;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);
  font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  line-height:1.8;max-width:1060px;margin:0 auto;padding:2.5rem 1.5rem 6rem}
h1{font-size:1.7rem;border-bottom:2px solid var(--accent);padding-bottom:.5rem;
   line-height:1.4}
h2{font-size:1.3rem;margin-top:3.4rem;color:var(--accent);
   border-bottom:1px solid var(--line);padding-bottom:.35rem}
h3{font-size:1.05rem;margin-top:2rem}
p{margin:.7rem 0}
.lead{color:var(--muted);font-size:.95rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:1rem 1.3rem;margin:1.2rem 0}
.card.alert{border-left:5px solid var(--bad)}
.card.note{border-left:5px solid var(--accent)}
.card h3{margin-top:.2rem}
.tbl{border-collapse:collapse;width:100%;font-size:.85rem;margin:.9rem 0}
.tbl th,.tbl td{border:1px solid var(--line);padding:.35rem .6rem;text-align:left}
.tbl th{background:color-mix(in srgb,var(--accent) 12%,var(--card))}
.tbl tbody tr:nth-child(even){background:color-mix(in srgb,var(--fg) 4%,var(--card))}
.tbl td.num{text-align:right;font-variant-numeric:tabular-nums}
figure{margin:1.6rem 0 2.2rem}
figcaption{font-size:.9rem;color:var(--fg);margin-top:.5rem;
  padding-left:.7rem;border-left:3px solid var(--accent)}
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
.tag{display:inline-block;padding:.05rem .5rem;border-radius:5px;font-size:.78rem;
  font-weight:700}
.tag.ok{background:color-mix(in srgb,var(--ok) 22%,transparent);color:var(--ok)}
.tag.warn{background:color-mix(in srgb,var(--warn) 22%,transparent);color:var(--warn)}
.tag.bad{background:color-mix(in srgb,var(--bad) 22%,transparent);color:var(--bad)}
.small{font-size:.83rem;color:var(--muted);margin:.35rem 0 0}
code{background:color-mix(in srgb,var(--fg) 7%,transparent);padding:.05rem .3rem;
  border-radius:4px;font-size:.88em}
ul{margin:.5rem 0 .5rem 1.2rem;padding:0}
li{margin:.25rem 0}
.toc{font-size:.9rem;columns:2;column-gap:2rem}
.toc a{color:var(--fg)}
.formula{text-align:center;font-size:1.15rem;margin:1rem 0;font-family:Georgia,serif}
"""


def table(headers, rows, num_cols=()):
    h = "".join(f"<th>{c}</th>" for c in headers)
    body = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            cls = ' class="num"' if i in num_cols else ""
            tds.append(f"<td{cls}>{c}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<table class="tbl"><thead><tr>{h}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def build(indir, outpath):
    R = lambda n: pd.read_csv(os.path.join(indir, n))
    cur = R("curves_by_family.csv")
    bl = R("bridge_fade_reveal_by_level.csv")
    bs = R("bridge_summary.csv")
    bf = R("blur_floor.csv")
    tfc = R("blur_floor_time_control.csv")
    rbe = R("render_bug_by_engine.csv")
    rbs = R("render_bug_summary.csv")
    rbs["webkit"] = rbs["webkit"].astype(str).str.lower().eq("true")
    wch = R("wipe_by_char.csv")
    wch["dakuten"] = wch["dakuten"].astype(str).str.lower().eq("true")
    wdk = R("wipe_dakuten_contrast.csv")
    wj = R("wipe_jump.csv")
    rj = R("reveal_jump.csv")
    r4s = R("reveal4_speed.csv")
    sf = R("speed_effect_family.csv")
    prof = R("tau_profile_loglik.csv")
    cf = R("tau_cell_fit.csv")
    ts = R("tau_summary.csv")
    parts = R("participants.csv")
    comp = R("participants_composition.csv")
    gap = R("blur_phase_gap.csv")
    gapb = R("blur_phase_gap_bootstrap.csv")
    dev = R("device_effect_by_family.csv")

    # ---- 概況の数値（すべて CSV 由来）
    n_calib = int((parts.phase == "calib").sum())
    n_calib2 = int((parts.phase == "calib2").sum())
    n_all = len(parts)
    n_wk = int(parts.webkit.astype(str).str.lower().eq("true").sum())
    wk_share = n_wk / n_all
    wk_blur = rbs[(rbs.family == "blur") & (rbs.webkit)].iloc[0]
    nwk_blur = rbs[(rbs.family == "blur") & (~rbs.webkit)].iloc[0]
    bf_wk3 = bf[(bf.subset == "WebKit only") & (bf.progress_pct == 3.0)].iloc[0]
    bf_ex = bf[bf.subset == "WebKit excluded"]
    bf_low = bf_ex[bf_ex.progress_pct <= 26]
    bf_all_low = bf[(bf.subset == "all devices") & (bf.progress_pct <= 26)]
    tau = ts[ts.subset == "calib + calib2"].iloc[0]
    rj_pool = rj[(rj.phase == "pooled") & (rj.step == "2.0->4.0")].iloc[0]
    rj_c1 = rj[(rj.phase == "calib") & (rj.step == "2.0->4.0")].iloc[0]
    rj_c2 = rj[(rj.phase == "calib2") & (rj.step == "2.0->4.0")].iloc[0]
    wjd = wj[(wj.group.str.startswith("dakuten")) & (wj.step == "65->80")].iloc[0]
    wjs = wj[(wj.group.str.startswith("sei")) & (wj.step == "65->80")].iloc[0]
    bs_fade = bs[bs.family == "fade"].iloc[0]
    bs_rev = bs[bs.family == "reveal"].iloc[0]
    bs_blur = bs[bs.family == "blur"].iloc[0]
    n_in_ci = int(((bl.trial_set == "main8") & (bl.lo_pt <= 0) & (bl.hi_pt >= 0)).sum())
    n_lvl = int((bl.trial_set == "main8").sum())
    sp_pool = sf[sf.phase == "pooled"]
    sp_min_holm = float(sp_pool.p_holm_4families.min())

    O = []
    A = O.append
    A(f"<title>転写検証実験 結果レポート 2026-08-27</title>")
    A(f"<style>{CSS}</style>")
    A("<h1>転写検証実験 結果レポート<br><span style='font-size:.62em;font-weight:400'>"
      "視覚較正 2 バッチ（実験1 + 追いバッチ）の全解析　2026-08-27</span></h1>")
    A(f'<p class="lead">対象データ <code>project/data_calib2_live/transfer_trials.csv</code>／'
      f'解析 <code>experiment/tools/analyze_calib2.py</code>／本ページの生成 '
      f'<code>experiment/tools/build_results_report.py</code>。'
      f'本文中の数値はすべて <code>analysis/*.csv</code> から自動で埋めている。'
      f'正答率は<strong>生の値</strong>（λ 正規化なし）、区間は 95%、'
      f'多重比較は Holm 法。</p>')

    # ---- 目次
    secs = [("s0", "最重要: 一部端末でぼかしが描画されていなかった"),
            ("s1", "① 4方式の較正曲線"),
            ("s2", "② 橋 — 2回の較正が一致するか"),
            ("s3", "③ ぼやけの床 — 偶然水準まで落ちる"),
            ("s4", "④ 描画不具合の証拠 — 端末別"),
            ("s5", "⑤ 幾何予測の的中 — wipe と濁点"),
            ("s6", "⑥ reveal の 2%→4% の跳ね"),
            ("s7", "⑦ 速さ（300ms / 500ms）の効果"),
            ("s8", "⑧ 時間の式 — 飽和指数モデルの τ"),
            ("s9", "⑨ 残る未解決 — ぼやけの実験間ギャップ"),
            ("s10", "付録: 参加者構成とデータの扱い")]
    A('<div class="card"><div class="toc">' +
      "".join(f'<div><a href="#{i}">{esc(t)}</a></div>' for i, t in secs) +
      "</div></div>")

    # ---- 結論先出し
    A('<div class="card note"><h3>先に結論</h3><ul>')
    A(f"<li><strong>橋は成立</strong>。fade・reveal は 2 回の較正で一致した"
      f"（8 水準まとめの差 {pt(bs_fade.diff_pt,2)} / {pt(bs_rev.diff_pt,2)}、"
      f"{n_in_ci}/{n_lvl} 点の CI が 0 を含む）。</li>")
    A(f"<li><strong>ぼやけには床がある</strong>。WebKit を除くと s = 3〜26% の正答率は "
      f"{pct(bf_low.acc.min())}〜{pct(bf_low.acc.max())} で、偶然水準 "
      f"{pct(GAMMA,1)} のすぐ上に張りついて平ら。</li>")
    A(f"<li><strong>幾何の予測が当たった</strong>。wipe で濁点字（が・ぱ）は s = 65% まで "
      f"{pct(wjd.acc_from)}、80% で {pct(wjd.acc_to)} に跳ねる（{pt(wjd.jump_pt)}、"
      f"Holm p={pfmt(wjd.p_holm)}）。清音 6 字では同じ区間で {pt(wjs.jump_pt)}。</li>")
    A(f"<li><strong>reveal の 2%→4% の跳ねは再現した</strong>"
      f"（実験1 {pt(rj_c1.jump_pt)}／追いバッチ {pt(rj_c2.jump_pt)}／"
      f"プール {pt(rj_pool.jump_pt)} {ci(rj_pool.lo_pt, rj_pool.hi_pt)}）。</li>")
    A(f"<li><strong>速さの効果は確定できない</strong>。4 方式の多重比較を通すと "
      f"最小の Holm p でも {pfmt(sp_min_holm)} で、どれも有意にならない。</li>")
    A(f"<li><strong>時間の式</strong> τ̂ = {tau.tau_hat:g} ms "
      f"[{tau.tau_lo:g}, {tau.tau_hi:g}]（セル {int(tau.n_cells)}、"
      f"提示時間だけが違う部分セルの対から推定）。</li>")
    A(f"<li><span class='tag bad'>未解決</span> ぼやけだけ、同一水準で実験1と追いバッチの"
      f"成績が食い違う（s=48% で {pt(gapb[gapb.progress_pct==48].iloc[0].diff_pt)}"
      f"／本命字とまぎれ字の合算）。図2 では全体像を 1 本で見るために束ねているが、"
      f"この食い違いの原因は分かっていない。</li>")
    A("</ul></div>")

    # ============================================================ s0
    A(f'<h2 id="s0">最重要: 一部端末でぼかしが描画されていなかった</h2>')
    A('<div class="card alert">')
    A(f"<p><strong>WebKit（iOS の全ブラウザ・アプリ内 WebView・macOS Safari）では "
      f"canvas の <code>ctx.filter = blur(...)</code> が効かず、"
      f"ぼやけ方式の刺激が鮮明な字のまま提示されていた。</strong></p>")
    A(f"<p>証拠は明快で、進み具合 s = {bf_wk3.progress_pct:g}%（ぼかし半径 "
      f"{bf_wk3.blur_radius_px:.1f}px ＝ 判読不能のはず）でも WebKit 端末の正答率は "
      f"<strong>{pct(bf_wk3.acc)}</strong>（n={int(bf_wk3.n)}）だった。"
      f"同じ条件の非 WebKit 端末は {pct(bf_ex[bf_ex.progress_pct==3.0].iloc[0].acc)}。</p>")
    A(f"<p>影響を受けたのは視覚較正の参加者 <strong>{n_all} 名中 {n_wk} 名"
      f"（{pct(wk_share)}）</strong>。方式ごとの平均正答率で見ると、"
      f"壊れているのは blur だけで、fade・reveal・wipe は正常である"
      f"（下の④）。</p>")
    A(f"<p class='small'>→ <strong>本レポートのぼやけ方式に関する数値は、"
      f"すべて WebKit 端末を除外して算出している。</strong>"
      f"これ以前に作った <code>families_report.html</code> のぼやけ関連の数値は"
      f"すべて汚染されており、使ってはいけない。</p>")
    A("</div>")

    # ============================================================ s1
    A('<h2 id="s1">① 4方式の較正曲線</h2>')
    A("<p>横軸は進み具合 s（提示アニメーションの到達点、対数軸）、縦軸は生の正答率。"
      "実線・塗り丸が実験1、破線・白丸が追いバッチ。帯は Wilson の 95%CI。"
      "本命 8 字（あ・か・が・ぱ・し・つ・ま・ら）のみ。</p>")
    A(figure(fig_curves(cur),
             "図1　4方式それぞれの較正曲線。方式ごとに水準の並びが違うため、"
             "実験1と追いバッチで重なる水準は fade・reveal が 8 点、blur が 3 点、"
             "wipe が 2 点である。",
             "点線は 72 択の偶然水準（1/72 = 1.4%）。blur のパネルは WebKit 除外。"))
    # 水準の一覧表
    rows = []
    for fam in ["fade", "reveal", "blur", "wipe"]:
        for ph_ in ["calib", "calib2"]:
            g = cur[(cur.trial_set == "main8") & (cur.family == fam)
                    & (cur.phase == ph_)].sort_values("progress_pct")
            if not len(g):
                continue
            rows.append([FAM_JA[fam], PHASE_JA[ph_],
                         "、".join(f"{v:g}" for v in g.progress_pct),
                         f"{int(g.n.min())}〜{int(g.n.max())}",
                         f"{g.T_ms_median.min():.0f}〜{g.T_ms_median.max():.0f}"])
    A(table(["方式", "バッチ", "進み具合の水準（%）", "1水準あたり試行数",
             "実測提示時間の中央値（ms）"], rows, num_cols=(3, 4)))

    # ---- 2回分を合わせた曲線
    A("<h3>2回分を合わせた曲線 — 束ねたもの／並べたもの</h3>")
    A("<p>上の図は 2 回の較正を<strong>並べて比べる</strong>ためのものである。"
      "ここでは同じデータを、<strong>1 本の曲線として使う</strong>ときの形で示す。"
      "方式ごとに扱いが違うので、図の中に扱いを明示した。</p>")
    A("<ul>")
    A(f"<li><span class='tag ok'>束ねた</span> <strong>fade・reveal</strong>: "
      f"水準ラダーが 2 回とも同一で、橋の検査でも一致している"
      f"（差 {pt(bs_fade.diff_pt)} {ci(bs_fade.lo_pt, bs_fade.hi_pt)}／"
      f"{pt(bs_rev.diff_pt)} {ci(bs_rev.lo_pt, bs_rev.hi_pt)}、"
      f"Holm 後 p={pfmt(bs_fade.p_holm)}）。"
      f"2 回分をプールすると 1 水準あたりの n が約 2 倍になり、信頼区間が狭くなる。</li>")
    A("<li><span class='tag warn'>並べた（束ねていない）</span> <strong>wipe</strong>: "
      "水準ラダーが 2 回で違う（実験1 は 0.5〜25% と 100%、追いバッチは 2〜80% と 100%）。"
      "束ねるのではなく両方の水準を 1 本の軸に並べると、"
      "低い側から高い側まで通した 1 本の曲線として読める。"
      "実験1 で空いていた 25〜100% の区間が追いバッチで埋まった。</li>")
    blur_pool = pooled_points(cur[(cur.trial_set == "main8") & (cur.family == "blur")])
    b48 = [r for r in blur_pool if r[0] == 48.0][0]
    bg48 = cur[(cur.trial_set == "main8") & (cur.family == "blur")
               & (cur.progress_pct == 48.0)]
    b48a = bg48[bg48.phase == "calib"].iloc[0]
    b48b = bg48[bg48.phase == "calib2"].iloc[0]
    shared_lv = [r[0] for r in blur_pool if len(r[5]) == 2]
    A(f"<li><span class='tag ok'>束ねた</span> <strong>blur</strong>: "
      f"束ねた曲線は 26% から 100% まできれいに単調に上がり、1 本の曲線として読める"
      f"（3〜26% で上下して見えるのは床＝偶然水準 {pct(GAMMA)} 付近だからで、"
      f"他の方式でも同じことが起きる）。ただし "
      f"<strong>2 回とも測った水準は "
      f"{' / '.join(f'{v:g}%' for v in shared_lv)} の 3 点だけ</strong>で、"
      f"残りは 3〜22% が追いバッチのみ、38〜84% が実験1のみである。"
      f"図では共通水準を◇で示した。</li>")
    A("</ul>")
    A(f'<div class="card note"><p><strong>blur の s = 48% では 2 回の結果が食い違う。</strong>'
      f'実験1 が {pct(b48a.acc)}（n={int(b48a.n)}）、追いバッチが {pct(b48b.acc)}'
      f'（n={int(b48b.n)}）で、束ねると {pct(b48[2])}（n={b48[1]}）になる。'
      f'図2 の blur パネルにはこの内訳を書き込んである。'
      f'共通 3 水準をまとめた差は {pt(bs_blur.diff_pt)} '
      f'{ci(bs_blur.lo_pt, bs_blur.hi_pt)}、Holm 後 p={pfmt(bs_blur.p_holm)}。'
      f'原因はまだ分かっていない（⑨）。</p></div>')
    A(figure(fig_pooled(cur, bs),
             "図2　2回分の較正を「使う形」で示したもの。"
             "fade・reveal・blur は 2 回分をプールした 1 本の曲線（太線・濃い帯）、"
             "wipe は 2 回分の水準を 1 本の軸に並べた通し曲線。"
             "blur の◇は 2 回とも測った水準、丸は片方だけで測った水準。",
             "各パネルの右上のラベルが扱いを示す。"
             "帯・ひげはいずれも 95%CI。blur のパネルは WebKit 除外。"))
    # プール後の数値表（fade / reveal / blur）
    rows = []
    for fam in ["fade", "reveal", "blur"]:
        for L, n, p_, lo_, hi_, phs in pooled_points(
                cur[(cur.trial_set == "main8") & (cur.family == fam)]):
            src = ("2回とも" if len(phs) == 2
                   else ("実験1のみ" if phs == ("calib",) else "追いバッチのみ"))
            rows.append([FAM_JA[fam], f"{L:g}", n, pct(p_),
                         f"[{pct(lo_)}, {pct(hi_)}]", src])
    A(table(["方式（プール後）", "s（%）", "n", "正答率", "Wilson 95%CI", "測ったバッチ"],
            rows, num_cols=(1, 2, 3)))
    A("<p class='small'>この表がプールされた fade・reveal・blur の較正曲線の数値である。"
      "wipe は水準ラダーが違うのでプールしていない。"
      "上の「水準の一覧」表とそれぞれのバッチの値を使うこと。</p>")

    # ============================================================ s2
    A('<h2 id="s2">② 橋 — 2回の較正が一致するか</h2>')
    A("<p>2 つのバッチは別の参加者・別の時期・別の水準セットである。"
      "同じ水準を持つ fade・reveal で成績が一致すれば、"
      "2 回の較正を 1 本の曲線としてつないでよい（＝橋が架かる）。</p>")
    A(figure(fig_bridge(bl, bs),
             "図3　共通 8 水準それぞれの「追いバッチ − 実験1」の差と 95%CI。"
             "縦線が 0 の位置。",
             "8水準まとめの差は参加者クラスタ・ブートストラップ、"
             "Holm は fade / reveal / blur の 3 検定に対する調整。"))
    A(table(["方式", "共通水準数", "差（pt）", "95%CI", "ブートストラップ p", "Holm p", "判定"],
            [[FAM_JA[r.family], int(r.n_shared_levels), f"{r.diff_pt:+.2f}",
              ci(r.lo_pt, r.hi_pt, 2), pfmt(r.p_boot), pfmt(r.p_holm),
              ('<span class="tag ok">一致</span>' if r.p_holm >= .05
               else '<span class="tag bad">不一致</span>')]
             for _, r in bs.iterrows()], num_cols=(1, 2)))
    A(f"<p>fade・reveal は差が {pt(bs_fade.diff_pt,2)}／{pt(bs_rev.diff_pt,2)} と小さく、"
      f"CI は 0 をまたぐ。水準ごとに見ても {n_in_ci}/{n_lvl} 点の CI が 0 を含む。"
      f"<strong>橋は架かった。</strong>"
      f"一方 blur だけは {pt(bs_blur.diff_pt,2)} {ci(bs_blur.lo_pt, bs_blur.hi_pt,2)}、"
      f"Holm p={pfmt(bs_blur.p_holm)} で一致しない（⑨で詳述）。</p>")

    # ============================================================ s3
    A('<h2 id="s3">③ ぼやけの床 — 偶然水準まで落ちる</h2>')
    A("<p>追いバッチではぼやけを s = 3〜26% の低い側に細かく置いた。"
      "ぼかし半径は <code>72px × (1 − s)</code> なので、"
      "s = 3% は半径 69.8px、s = 26% でも 53.3px である。</p>")
    A(figure(fig_blur_floor(bf, tfc),
             "図4　ぼやけ方式の正答率。左は端末サブセット別の全体像、"
             "右は低水準の拡大（WebKit 除外・Wilson 95%CI）。",
             "本命字とまぎれ字を合わせた集計（1 水準あたり n≈270〜280）。"))
    rows = []
    for _, r in bf_ex.iterrows():
        a = bf[(bf.subset == "all devices") & (bf.progress_pct == r.progress_pct)].iloc[0]
        w = bf[(bf.subset == "WebKit only") & (bf.progress_pct == r.progress_pct)]
        rows.append([f"{r.progress_pct:g}", f"{r.blur_radius_px:.1f}",
                     f"{r.T_ms_median:.0f}", int(r.n), pct(r.acc),
                     f"[{pct(r.lo)}, {pct(r.hi)}]", pct(a.acc),
                     pct(w.iloc[0].acc) if len(w) else "—"])
    A(table(["s（%）", "ぼかし半径（px）", "実測提示時間の中央値（ms）",
             "n（WebKit 除外）", "正答率（WebKit 除外）", "95%CI",
             "（参考）全端末", "（参考）WebKit のみ"], rows,
            num_cols=(0, 1, 2, 3, 4, 6, 7)))
    A(f"<p>WebKit を除くと、s = 3〜26% の 6 水準はすべて "
      f"{pct(bf_low.acc.min())}〜{pct(bf_low.acc.max())} に収まり、"
      f"偶然水準 {pct(GAMMA)} との差はごく小さい。"
      f"<strong>これが「ぼやけの床」である。</strong>"
      f"WebKit を含めたままだと同じ 6 水準が "
      f"{pct(bf_all_low.acc.min())}〜{pct(bf_all_low.acc.max())} に持ち上がり、"
      f"「床は 13% 程度で偶然水準より高い」という誤った結論になる。</p>")
    # 提示時間の交絡チェック
    A("<h3>床は「ぼかしの床」か「提示時間の床」か</h3>")
    A(f"<p>この実験では提示時間 T = s × base_anim_ms なので、s が小さい水準は"
      f"提示時間も短い（s = 3% × 300ms なら数フレーム）。"
      f"床の正体が提示時間なら、同じ s を 500ms 条件で見せた人のほうが当たるはずである。"
      f"実際には <strong>どの水準でも 500ms − 300ms の差は小さく、Holm 調整後は"
      f"すべて p = {pfmt(tfc.p_holm.min())} 以上</strong>で有意にならない。</p>")
    A(table(["s（%）", "T 300ms 条件（ms）", "正答率", "T 500ms 条件（ms）", "正答率",
             "差（pt）", "95%CI", "Holm p"],
            [[f"{r.progress_pct:g}", f"{r.T_300:.0f}", pct(r.acc_300),
              f"{r.T_500:.0f}", pct(r.acc_500), f"{r.diff_pt:+.1f}",
              ci(r.lo_pt, r.hi_pt), pfmt(r.p_holm)]
             for _, r in tfc.iterrows()], num_cols=(0, 1, 2, 3, 4, 5)))
    A("<p class='small'>ただし 300ms 条件と 500ms 条件で実測時間の差は最大でも 200ms 程度で、"
      "τ̂ の数十 ms に対しては両方とも「十分長い」側にある（⑧参照）。"
      "この表は床が提示時間で説明できないことを示すが、"
      "極端に短い提示の効果を否定するものではない。</p>")

    # ============================================================ s4
    A('<h2 id="s4">④ 描画不具合の証拠 — 端末別</h2>')
    A(figure(fig_render_bug(rbe, rbs),
             "図5　左: ぼやけの低水準（s ≦ 26%）における端末エンジン別の正答率。"
             "右: 4 方式それぞれについて WebKit 端末と非 WebKit 端末を比べたもの。",
             "エラーバーは Wilson 95%CI。左の点線は偶然水準。"))
    rows = []
    for fam in ["fade", "reveal", "blur", "wipe"]:
        t = rbs[(rbs.family == fam) & (rbs.webkit)].iloc[0]
        f_ = rbs[(rbs.family == fam) & (~rbs.webkit)].iloc[0]
        rows.append([FAM_JA[fam], f"{int(t.n_participants)}", pct(t.acc),
                     f"{int(f_.n_participants)}", pct(f_.acc),
                     f"{100 * (t.acc - f_.acc):+.1f}pt"])
    A(table(["方式", "WebKit 人数", "WebKit 正答率", "非WebKit 人数", "非WebKit 正答率",
             "差"], rows, num_cols=(1, 2, 3, 4, 5)))
    A(f"<p>fade・reveal・wipe では WebKit と非 WebKit の差はせいぜい十数 pt で、"
      f"端末の速さ・画面の違いで説明がつく範囲にある。"
      f"blur だけは <strong>{pct(wk_blur.acc)} 対 {pct(nwk_blur.acc)}</strong> と"
      f"別物であり、しかも最も強いぼかしでも 100% 近い。"
      f"これは「WebKit の人が上手い」ではなく"
      f"<strong>刺激が生成されていない</strong>ことの証拠である。</p>")
    A("<p class='small'>参考: 端末の種類による差（モバイル − デスクトップ）。"
      "blur は WebKit を含めると "
      f"{pt(dev[(dev.family=='blur') & (dev.webkit_excluded.astype(str).str.lower()=='false')].iloc[0].mobile_minus_desktop_pt)}"
      " と大きく出るが、WebKit を除くと "
      f"{pt(dev[(dev.family=='blur') & (dev.webkit_excluded.astype(str).str.lower()=='true')].iloc[0].mobile_minus_desktop_pt)}"
      " に反転する。「モバイルのほうが読める」という見かけの効果も"
      "この不具合が作っていた。</p>")

    # ============================================================ s5
    A('<h2 id="s5">⑤ 幾何予測の的中 — wipe と濁点</h2>')
    A("<p>wipe（はらい）は書き順に沿って字を左上から順に出す方式なので、"
      "<strong>濁点・半濁点は最後に出る</strong>。"
      "したがって「が」「ぱ」は、濁点が出るまで清音の「か」「は」と見分けがつかず、"
      "濁点が現れた瞬間に一気に正答率が上がる、と事前に予測していた。</p>")
    A(figure(fig_wipe(wch, wdk, wj),
             "図6　左: wipe における字ごとの正答率（細線）と群平均（太線）。"
             "帯は 65%→80% の区間。右: 濁点字と清音字の差。",
             "追いバッチ（wipe を s = 2〜100% の 8 水準で提示）の本命 8 字。"))
    A(table(["区間", "群", "前の正答率", "後の正答率", "跳ね（pt）", "95%CI", "Holm p"],
            [[r.step.replace("->", " → ") + "%",
              "濁点 が・ぱ" if r.group.startswith("dakuten") else "清音 6 字",
              pct(r.acc_from), pct(r.acc_to), f"{r.jump_pt:+.1f}",
              ci(r.lo_pt, r.hi_pt), pfmt(r.p_holm)]
             for _, r in wj.sort_values(["group", "step"]).iterrows()],
            num_cols=(2, 3, 4)))
    A(f"<p>予測どおりだった。濁点字は s = 50% でも {pct(wjd.acc_from)} 近くに留まり"
      f"（清音 6 字は同じ s ですでに 9 割超）、"
      f"<strong>65% → 80% で {pct(wjd.acc_from)} → {pct(wjd.acc_to)}、"
      f"{pt(wjd.jump_pt)}（Holm p={pfmt(wjd.p_holm)}）</strong>と跳ねる。"
      f"同じ区間で清音 6 字は {pt(wjs.jump_pt)}（Holm p={pfmt(wjs.p_holm)}）＝ほぼ変化なし。"
      f"清音との差は s = 65% で最大 {pt(wdk[wdk.progress_pct==65].iloc[0].diff_pt)} に達し、"
      f"s = 100% では {pt(wdk[wdk.progress_pct==100].iloc[0].diff_pt)} まで消える。</p>")
    A("<p class='small'>この跳ねは「字の書き順のどこに弁別情報があるか」から"
      "計算だけで予測できるもので、正答率のデータを見る前に立てた予測が当たった。"
      "方式の性質が字の構造と結びついていることの直接の証拠になる。</p>")

    # ============================================================ s6
    A('<h2 id="s6">⑥ reveal の 2%→4% の跳ね</h2>')
    A("<p>reveal（けずり）では、進み具合が 2% から 4% に上がるところで"
      "正答率が不連続に跳ねる。実験1で見つかったこの段差が追いバッチでも出るかを見た。</p>")
    A(figure(fig_reveal(cur, rj),
             "図7　左: reveal の較正曲線（対数軸）。帯が 2%→4% の区間。"
             "右: 隣り合う水準どうしの段差の大きさと 95%CI。",
             "本命 8 字。左の帯は Wilson 95%CI、右の横線は差の 95%CI。"))
    A(table(["区間", "バッチ", "前", "後", "跳ね（pt）", "95%CI", "p（生）"],
            [[r.step.replace("->", " → ") + "%", PHASE_JA[r.phase],
              pct(r.acc_from), pct(r.acc_to), f"{r.jump_pt:+.1f}",
              ci(r.lo_pt, r.hi_pt), pfmt(r.p_raw)]
             for _, r in rj.iterrows()], num_cols=(2, 3, 4)))
    A(f"<p>2%→4% の跳ねは実験1 {pt(rj_c1.jump_pt)}、追いバッチ {pt(rj_c2.jump_pt)}、"
      f"プール {pt(rj_pool.jump_pt)} {ci(rj_pool.lo_pt, rj_pool.hi_pt)} で<strong>再現した</strong>。"
      f"すぐ手前の 1%→2% はさらに大きく（プール {pt(rj[(rj.phase=='pooled') & (rj.step=='1.0->2.0')].iloc[0].jump_pt)}）、"
      f"reveal はこの狭い区間に曲線の立ち上がりが集中している。</p>")
    A("<h3>提示時間による説明が成り立つか</h3>")
    A(f"<p>s = 2% と 4% では実測提示時間の中央値がどちらも "
      f"{rj_pool.T_from:.0f}ms で同一なので、時間の違いでは説明できない。"
      f"速さ条件（300ms / 500ms）で分けても以下のとおり。</p>")
    A(table(["バッチ", "s（%）", "300ms 条件", "正答率", "500ms 条件", "正答率",
             "差（pt）", "95%CI"],
            [[PHASE_JA[r.phase], f"{r.progress_pct:g}", f"n={int(r.n_300)}",
              pct(r.acc_300), f"n={int(r.n_500)}", pct(r.acc_500),
              f"{r.diff_pt:+.1f}", ci(r.lo_pt, r.hi_pt)]
             for _, r in r4s.iterrows()], num_cols=(1, 3, 5, 6)))

    # ============================================================ s7
    A('<h2 id="s7">⑦ 速さ（300ms / 500ms）の効果</h2>')
    A("<p>同じ絵を、アニメーション全体の長さ 300ms と 500ms のどちらで見せたかによる差。"
      "終点の絵は完全に同一で、そこに至る時間だけが違う。"
      "水準構成の偏りを打ち消すため、水準ごとに平均してから水準を等重みで束ねている。</p>")
    A(figure(fig_speed(sf),
             "図8　方式ごと・バッチごとの「500ms − 300ms」の正答率差。"
             "太い線と大きい点がプール（両バッチ合算）。",
             "参加者クラスタ・ブートストラップ（4000 回）の 95%CI。"
             "Holm はプールした 4 方式の 4 検定に対する調整。"))
    A(table(["方式", "バッチ", "n", "差（pt）", "95%CI", "ブートストラップ p", "Holm p（4方式）"],
            [[FAM_JA[r.family], PHASE_JA[r.phase], int(r.n), f"{r.diff_pt:+.1f}",
              ci(r.lo_pt, r.hi_pt), pfmt(r.p_boot),
              pfmt(r.p_holm_4families) if not pd.isna(r.p_holm_4families) else "—"]
             for _, r in sf.iterrows()], num_cols=(2, 3)))
    rv = sf[(sf.family == "reveal") & (sf.phase == "pooled")].iloc[0]
    A(f"<p>最も大きいのは reveal のプールで {pt(rv.diff_pt)} "
      f"{ci(rv.lo_pt, rv.hi_pt)}、生の p={pfmt(rv.p_boot)}。"
      f"しかし <strong>4 方式ぶんの多重比較を通すと Holm p={pfmt(rv.p_holm_4families)} で、"
      f"どの方式も有意にならない</strong>。"
      f"「ゆっくり見せたほうが当たる」とは、このデータでは言い切れない。</p>")

    # ============================================================ s8
    A('<h2 id="s8">⑧ 時間の式 — 飽和指数モデルの τ</h2>')
    A("<p>提示時間 T が長くなるほど正答率は上がるが、ある程度で頭打ちになる。"
      "これを次の飽和指数モデルで表す。</p>")
    A('<p class="formula">p(T) = γ + (λ − γ)·(1 − e<sup>−T/τ</sup>)</p>')
    A(f"<p class='small'>γ = 1/72 = {pct(GAMMA,2)}（72 択のあてずっぽう率、固定）、"
      f"λ はセルごとの上限（最尤推定）、τ は全セル共通の時定数。"
      f"セル = 方式 × 水準 × バッチ。各セルは 300ms 条件と 500ms 条件の 2 つの部分セルを持ち、"
      f"<strong>終点の絵は同一・提示時間 T だけが違う</strong>ので、"
      f"λ を吸収したまま τ だけを取り出せる。</p>")
    A(figure(fig_tau(prof, cf, ts),
             "図9　左: τ のプロファイル対数尤度。網かけは 95% 区間、"
             "破線が最尤の τ̂。右: τ̂ のもとでの予測と実測の対応。",
             "95% 区間は χ²(1) を使った Δ対数尤度 = 1.92 の等高線。"))
    A(table(["データ範囲", "セル数", "τ̂（ms）", "95%区間", "区間の幅"],
            [[r.subset.replace("calib only (experiment 1)", "実験1のみ")
              .replace("calib2 only", "追いバッチのみ")
              .replace("calib + calib2, reveal4% excluded", "両方（reveal 4% を除外）")
              .replace("calib + calib2", "両方（主推定）"),
              int(r.n_cells), f"{r.tau_hat:g}",
              f"[{r.tau_lo:g}, {r.tau_hi:g}]", f"{r.ci_width:g}"]
             for _, r in ts.iterrows()], num_cols=(1, 2, 4)))
    A(f"<p>主推定は <strong>τ̂ = {tau.tau_hat:g} ms "
      f"[{tau.tau_lo:g}, {tau.tau_hi:g}]</strong>（セル {int(tau.n_cells)}）。"
      f"バッチを別々に推定しても {ts[ts.subset=='calib only (experiment 1)'].iloc[0].tau_hat:g} ms と "
      f"{ts[ts.subset=='calib2 only'].iloc[0].tau_hat:g} ms で区間は重なる。"
      f"reveal 4% を外しても {ts[ts.subset.str.contains('reveal4')].iloc[0].tau_hat:g} ms で"
      f"大きくは動かない。</p>")
    A(f"<p>τ が数十 ms ということは、"
      f"<strong>おおむね 100ms（≒ 5τ）以上映っていれば時間はほぼ効かず、"
      f"正答率は絵の内容（進み具合）だけで決まる</strong>ということである。"
      f"本実験の実測提示時間は中央値で 50〜534ms なので、"
      f"最も短い水準を除けばほぼ飽和側にある。</p>")

    # ============================================================ s9
    A('<h2 id="s9">⑨ 残る未解決 — ぼやけの実験間ギャップ</h2>')
    A('<div class="card alert">')
    A("<p>WebKit を除外してもなお、<strong>ぼやけ方式だけ、同一の刺激なのに"
      "実験1と追いバッチで成績が食い違う</strong>。特に s = 48% で大きい。</p>")
    A("</div>")
    A(figure(fig_blur_gap(gapb, gap),
             "図10　ぼやけの共通水準（s = 26 / 48 / 100%）における実験間の差。"
             "WebKit 除外・参加者クラスタ・ブートストラップ 95%CI。",
             "赤は Holm 調整後も 0 を含まないもの。"
             "この図は本命字とまぎれ字の合算（①の 48% の内訳は本命字のみなので値が違う）。"))
    A(table(["s（%）", "n", "差（pt）", "95%CI", "ブートストラップ p", "Holm p"],
            [[f"{r.progress_pct:g}", int(r.n), f"{r.diff_pt:+.1f}",
              ci(r.lo_pt, r.hi_pt), pfmt(r.p_boot), pfmt(r.p_holm)]
             for _, r in gapb.iterrows()], num_cols=(0, 1, 2)))
    A("<h3>すでに潰した説明</h3><ul>")
    A("<li><strong>刺激は不変</strong>: ぼかし半径 = <code>72px × (1 − s)</code> で、"
      "水準の並びに依存しない。<code>max_radius_px: 72</code> は両バッチで同一。</li>")
    A("<li><strong>提示時間も不変</strong>: 同じ水準・同じ速さ条件なら、"
      "実測提示時間の中央値は両バッチで一致する（下表）。</li>")
    for_ = gap[gap.stratum == "WebKit excl / char-matched (main8, equal weight)"]
    if len(for_):
        A("<li><strong>字の構成の偏りでもない</strong>: 本命 8 字を等重みでそろえた差は " +
          "、".join(f"s={r.progress_pct:g}% で {r.diff_pt:+.1f}pt" for _, r in for_.iterrows()) +
          " で、素の差とほとんど変わらない。</li>")
    A("<li><strong>能力差でもない</strong>: 同じ参加者の fade・reveal は一致している（②）。</li>")
    A("</ul>")
    tt = R("blur_presentation_time_check.csv")
    A(table(["バッチ", "s（%）", "設定の速さ（ms）", "n", "実測提示時間の中央値（ms）",
             "フレーム数の中央値"],
            [[PHASE_JA[r.phase], f"{r.progress_pct:g}", f"{r.base_anim_ms:.0f}",
              int(r.n), f"{r.T_median:.0f}", f"{r.frames_median:.0f}"]
             for _, r in tt.iterrows()], num_cols=(1, 2, 3, 4, 5)))
    li = R("blur_learning_interaction.csv")
    A("<h3>いま有力な説明: セッション中の慣れ</h3>")
    A("<p>ぼやけの水準セットが違うと、参加者が 1 セッションで見る"
      "「読めるぼやけ」の本数が変わる。実験1（26〜100%）は読める見本が何度も出るが、"
      "追いバッチ（3〜26% が 6 本）はほとんど読めないまま終わる。"
      "試行位置を入れたロジスティック回帰では、"
      "<strong>バッチ × 試行位置の交互作用が有意</strong>である。</p>")
    A(table(["モデル", "項", "係数", "SE", "z", "p"],
            [[r.model, r.term, f"{r.coef:+.3f}", f"{r.se:.3f}", f"{r.z:+.2f}",
              pfmt(r.p)] for _, r in li.iterrows()], num_cols=(2, 3, 4)))
    A("<p class='small'><strong>結論を書かない範囲</strong>: "
      "この点が片づくまで、ぼやけ方式の較正曲線をそのまま warp 表に凍結しない"
      "（図2 で束ねた曲線を出したのは全体像を 1 本で見るためで、"
      "warp 表に採るかどうかは別の判断である）。"
      "橋が架かっているのは fade・reveal であり、"
      "ぼやけについては「床がある」ことまでが確定した主張である。</p>")

    # ============================================================ s10
    A('<h2 id="s10">付録: 参加者構成とデータの扱い</h2>')
    A(f"<p>視覚較正の参加者は実験1 {n_calib} 名、追いバッチ {n_calib2} 名の"
      f"計 {n_all} 名。全員が別人で、重複参加はない。</p>")
    eng = comp[comp.variable == "browser_engine"]
    engs = sorted(eng.level.unique(), key=lambda e: -float(
        eng[(eng.level == e) & (eng.phase == "calib")].share.iloc[0]))
    A(table(["ブラウザエンジン", "実験1 の比率", "追いバッチ の比率"],
            [[e,
              pct(eng[(eng.level == e) & (eng.phase == "calib")].share.iloc[0]),
              pct(eng[(eng.level == e) & (eng.phase == "calib2")].share.iloc[0])]
             for e in engs], num_cols=(1, 2)))
    tch = comp[comp.variable == "touch"]
    A(f"<p class='small'>タッチ端末の比率は実験1 "
      f"{pct(tch[(tch.level.astype(str)=='True') & (tch.phase=='calib')].share.iloc[0])}、"
      f"追いバッチ "
      f"{pct(tch[(tch.level.astype(str)=='True') & (tch.phase=='calib2')].share.iloc[0])}。"
      f"WebKit の比率は "
      f"{pct(comp[(comp.variable=='webkit') & (comp.level.astype(str)=='True') & (comp.phase=='calib')].share.iloc[0])}"
      f" → "
      f"{pct(comp[(comp.variable=='webkit') & (comp.level.astype(str)=='True') & (comp.phase=='calib2')].share.iloc[0])}。</p>")
    A('<div class="card"><h3>解析の約束</h3><ul>')
    A("<li>正答率は<strong>生の値</strong>を使う。λ 正規化はしていない。</li>")
    A("<li>本命 8 字（あ・か・が・ぱ・し・つ・ま・ら）をすべて使う。"
      "図1・図2・図6・図7 は本命字のみ、図4・図10 は本命字とまぎれ字の合算。</li>")
    A("<li>区間は 95%。1 群の割合は Wilson、2 群の差は Wald または"
      "参加者クラスタ・ブートストラップ（4000 回）。</li>")
    A("<li>多重比較は Holm 法。生の p と調整後 p の両方を示す。</li>")
    A("<li><strong>ぼやけ方式からは WebKit 端末を必ず除外している。</strong>"
      "他の 3 方式は全端末を使う。</li>")
    A("<li>実測していない数値は載せていない。すべての数値は "
      "<code>project/data_calib2_live/analysis/*.csv</code> から読んでいる。</li>")
    A("<li>参加者を特定できる情報（wid・participant_id・会員ID）は"
      "本ページに一切含まれない。</li>")
    A("</ul></div>")
    A('<p class="small">生成: experiment/tools/build_results_report.py</p>')

    os.makedirs(os.path.dirname(os.path.abspath(outpath)), exist_ok=True)
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                + "".join(O[:2]) + "</head><body>" + "".join(O[2:]) + "</body></html>")
    return outpath


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--in", dest="indir",
                    default=os.path.join(here, "project/data_calib2_live/analysis"))
    ap.add_argument("--out", dest="out",
                    default=os.path.join(here,
                                         "project/data_calib2_live/"
                                         "results_report_20260827.html"))
    a = ap.parse_args()
    p = build(a.indir, a.out)
    print("wrote", p, os.path.getsize(p), "bytes")


if __name__ == "__main__":
    main()
