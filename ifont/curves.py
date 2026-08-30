#!/usr/bin/env python3
# =========================================================================
# ifont: 較正曲線の読み込みと逆引き
#
#   音声 A(t)  … 打ち切り時刻 t(ms) → 正答率（生の値）
#   視覚 V(s)  … 進み具合 s(%) → 正答率（生の値）
#   転写      … s(t) = V^-1( A(t) )。正規化しない（絶対値）。
#               音声がその時点で伝えている量を、視覚が超えないようにする。
#
#   曲線の出どころは3段階に分ける（tier 列）:
#     measured    … 重点測定した8字（あ か が し つ ぱ ま ら）。
#                   聴覚90名・視覚325名の袋詰め単調回帰。
#     provisional … 紛れ字。聴覚59字（1点あたり約7試行）・視覚63字。
#                   試行が薄いので暫定。単調化だけして使う。
#     fallback    … どちらの曲線も無い字。同じ方式の暫定曲線の平均で代用。
# =========================================================================
import csv
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CURVES_MAIN = os.path.join(ROOT, "project", "data_calib2_live",
                           "analysis_information", "curves_info.csv")
CURVES_DECOY_A = os.path.join(ROOT, "project", "data_calib_20260825",
                              "analysis_deep", "curves_decoy_audio.csv")
CURVES_DECOY_V = os.path.join(ROOT, "project", "data_calib_20260825",
                              "analysis_deep", "curves_decoy_visual.csv")

FAMS = ["fade", "reveal", "blur", "wipe"]


def _pava(ys, ws):
    """重み付き単調回帰（隣接違反プール法）。"""
    ys = list(map(float, ys))
    ws = list(map(float, ws))
    vals, wts, cnt = [], [], []
    for y, w in zip(ys, ws):
        vals.append(y); wts.append(w); cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            w2 = wts[-2] + wts[-1]
            v2 = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / w2
            c2 = cnt[-2] + cnt[-1]
            vals = vals[:-2] + [v2]; wts = wts[:-2] + [w2]; cnt = cnt[:-2] + [c2]
    out = []
    for v, c in zip(vals, cnt):
        out += [v] * c
    return out


class Curve:
    """単調非減少の折れ線。測った範囲の外へは伸ばさない（端の値で一定）。"""

    def __init__(self, xs, ys, log_x=False):
        pairs = sorted(zip(map(float, xs), map(float, ys)))
        self.xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        # 単調化（累積最大）
        m = -1.0
        self.ys = []
        for y in ys:
            m = max(m, y); self.ys.append(m)
        self.log_x = log_x
        self.tx = [math.log(max(x, 1e-9)) for x in self.xs] if log_x else list(self.xs)

    @property
    def top(self):
        return self.ys[-1]

    @property
    def bottom(self):
        return self.ys[0]

    @property
    def x_end(self):
        return self.xs[-1]

    def v(self, x):
        x = min(max(x, self.xs[0]), self.xs[-1])
        t = math.log(max(x, 1e-9)) if self.log_x else x
        for i in range(1, len(self.tx)):
            if t <= self.tx[i]:
                t0, t1 = self.tx[i - 1], self.tx[i]
                f = 0.0 if t1 - t0 <= 0 else (t - t0) / (t1 - t0)
                return self.ys[i - 1] * (1 - f) + self.ys[i] * f
        return self.ys[-1]

    def inv(self, y):
        """v(x)=y となる最小の x。範囲外は端に丸める。"""
        if self.top - self.bottom <= 1e-9:
            return self.xs[0] if y <= self.top else self.xs[-1]
        if y <= self.bottom:
            return self.xs[0]
        if y >= self.top:
            return self.xs[-1]
        for i in range(1, len(self.ys)):
            if self.ys[i] >= y:
                y0, y1 = self.ys[i - 1], self.ys[i]
                t0, t1 = self.tx[i - 1], self.tx[i]
                t = t0 if y1 - y0 <= 1e-12 else t0 + (y - y0) / (y1 - y0) * (t1 - t0)
                return math.exp(t) if self.log_x else t
        return self.xs[-1]


def load_curves():
    """{ 'audio': {字: (Curve, tier)}, 'visual': {(方式,字): (Curve, tier)} }"""
    audio, visual = {}, {}

    for x in csv.DictReader(open(CURVES_MAIN, encoding="utf-8")):
        if x["target"] != "acc":
            continue
        xs = [float(v) for v in x["xs"].split("|")]
        ys = [float(v) for v in x["ys"].split("|")]
        if x["modality"] == "audio":
            audio[x["char"]] = (Curve(xs, ys, log_x=True), "measured")
        else:
            visual[(x["family"], x["char"])] = (Curve(xs, ys), "measured")

    # 聴覚の紛れ字（1点あたり約7試行。'full' 行は最後の打ち切りの1.3倍の時刻に置く）
    rows = {}
    for x in csv.DictReader(open(CURVES_DECOY_A, encoding="utf-8")):
        rows.setdefault(x["char"], []).append(x)
    for ch, rs in rows.items():
        if ch in audio:
            continue
        num = [(float(r["gate_ms"]), float(r["accuracy"]), float(r["n_trials"]))
               for r in rs if r["gate_ms"] != "full"]
        ful = [(float(r["accuracy"]), float(r["n_trials"]))
               for r in rs if r["gate_ms"] == "full"]
        num.sort()
        xs = [g for g, _, _ in num]
        ys = _pava([a for _, a, _ in num], [n for _, _, n in num])
        if ful and xs:
            xs.append(xs[-1] * 1.3)
            ys.append(max(ys[-1], ful[0][0]))
        if len(xs) >= 3:
            audio[ch] = (Curve(xs, ys, log_x=True), "provisional")

    # 視覚の紛れ字
    rows = {}
    for x in csv.DictReader(open(CURVES_DECOY_V, encoding="utf-8")):
        rows.setdefault((x["family"], x["char"]), []).append(x)
    for key, rs in rows.items():
        if key in visual:
            continue
        num = sorted((float(r["level"]), float(r["accuracy"]), float(r["n_trials"]))
                     for r in rs)
        xs = [g for g, _, _ in num]
        ys = _pava([a for _, a, _ in num], [n for _, _, n in num])
        if len(xs) >= 3:
            visual[key] = (Curve(xs, ys), "provisional")

    # 代用（平均曲線）: どちらかが無い字のため
    def mean_curve(items, log_x):
        grid = [i / 20 for i in range(21)]
        xs_all = sorted({x for c, _ in items for x in c.xs})
        if not xs_all:
            return None
        lo, hi = xs_all[0], xs_all[-1]
        xs = [lo + (hi - lo) * g for g in grid]
        ys = [sum(c.v(x) for c, _ in items) / len(items) for x in xs]
        return Curve(xs, ys, log_x=log_x)

    prov_a = [v for v in audio.values() if v[1] == "provisional"]
    fb_a = mean_curve(prov_a, True) if prov_a else None
    fb_v = {}
    for fam in FAMS:
        pv = [v for (f, _), v in visual.items() if f == fam and v[1] == "provisional"]
        fb_v[fam] = mean_curve(pv, False) if pv else None

    return audio, visual, fb_a, fb_v


def transfer_series(ch, family, audio, visual, fb_a, fb_v,
                    frame_ms=1000.0 / 60.0):
    """字1つぶんの進み具合の列（絶対値の転写）。返り値: (list[s 0..1], tier, dur_ms)"""
    ca, ta = audio.get(ch, (fb_a, "fallback"))
    cv, tv = visual.get((family, ch), (fb_v.get(family), "fallback"))
    if ca is None or cv is None:
        raise KeyError(f"曲線が無い: {ch} × {family}")
    tier = "measured" if (ta == tv == "measured") else \
           ("fallback" if "fallback" in (ta, tv) else "provisional")
    dur = ca.x_end
    n = int(math.ceil(dur / frame_ms)) + 1
    s, m = [], 0.0
    for k in range(n):
        t = min(k * frame_ms, dur)
        y = ca.v(t)
        m = max(m, cv.inv(y) / 100.0)
        s.append(m)
    return s, tier, dur
