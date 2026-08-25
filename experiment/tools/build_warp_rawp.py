#!/usr/bin/env python3
"""
生の正答率 p のまま転写する版の s(t) を作って、何が起きるか見る（検討用）
========================================================================
決定(2026-08-26 検討中): 刺激固有の天井 λ で正規化せず、正答率そのものを合わせる。
    s(t) = V^{-1}( A(t) )     A, V はどちらも生の正答率

既存の build_transfer_warp.py（q正規化版）は触らない。これは比較用の別口。
"""
import csv, io, json, os, sys
from collections import defaultdict

TARGETS = ["あ", "か", "ま"]
FAMS = ["fade", "reveal", "blur", "wipe"]
LAB = {"fade": "うすい→濃い", "reveal": "点が増える", "blur": "ぼやけ", "wipe": "端から"}

def tb(v): return str(v).strip().lower() == "true"
def num(v):
    try: return float(v)
    except: return None

def pava(xs, ys, ws):
    """重み付き保序回帰（単調非減少にそろえる）"""
    lv = [[y, w] for y, w in zip(ys, ws)]
    i = 0
    while i < len(lv) - 1:
        if lv[i][0] <= lv[i + 1][0] + 1e-12:
            i += 1; continue
        y0, w0 = lv[i]; y1, w1 = lv[i + 1]
        lv[i] = [(y0 * w0 + y1 * w1) / (w0 + w1), w0 + w1]
        del lv[i + 1]
        if i > 0: i -= 1
    out = []
    for y, w in lv: out.extend([y] * 0)
    # 重みを元の点数に展開し直す
    res = []; k = 0
    for y, w in lv:
        n = 0; acc = 0
        while k < len(ws) and acc < w - 1e-9:
            acc += ws[k]; k += 1; n += 1
        res.extend([y] * n)
    while len(res) < len(ys): res.append(res[-1] if res else 0.0)
    return res[:len(ys)]

def curve_audio(rows, ch):
    by = defaultdict(list)
    for r in rows:
        if r["group"] != "acal" or r["target_char"] != ch: continue
        if r.get("check_kind"): continue
        g = num(r.get("gate_ms"))
        if g is None: continue          # 打ち切りなしは目標軌跡に入れない
        by[g].append(tb(r["correct"]))
    pts = sorted((g, sum(v) / len(v), len(v)) for g, v in by.items() if len(v) >= 10)
    return pts

def curve_visual(rows, ch, fam):
    by = defaultdict(list)
    for r in rows:
        if r["group"] != "aprime" or r["target_char"] != ch or r["family"] != fam: continue
        if r.get("check_kind"): continue
        L = num(r.get("progress_pct"))
        if L is None: continue
        by[L].append(tb(r["correct"]))
    pts = sorted((L, sum(v) / len(v), len(v)) for L, v in by.items() if len(v) >= 8)
    return pts

def invert(vpts, target):
    """単調化した V(s) を線形補間で逆引き。範囲外は端に丸めて印をつける"""
    ss = [p[0] for p in vpts]; ps = [p[1] for p in vpts]
    if target <= ps[0]:  return ss[0], ("low" if target < ps[0] - 1e-9 else None)
    if target >= ps[-1]: return ss[-1], ("high" if target > ps[-1] + 1e-9 else None)
    for i in range(len(ss) - 1):
        a, b = ps[i], ps[i + 1]
        if a <= target <= b:
            if b - a < 1e-12: return ss[i], None
            return ss[i] + (target - a) / (b - a) * (ss[i + 1] - ss[i]), None
    return ss[-1], "high"

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "project/data_calib_20260825/transfer_trials.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "project/data_calib_20260825/warp_rawp"
    rows = [r for r in csv.DictReader(io.open(src, encoding="utf-8-sig"))
            if not tb(r.get("is_test")) and r.get("response_char")]
    os.makedirs(out, exist_ok=True)
    report = []
    tables = {}
    for mono in (False, True):
        tag = "isotonic" if mono else "raw"
        tables[tag] = {}
        for fam in FAMS:
            tables[tag][fam] = {}
            for ch in TARGETS:
                A = curve_audio(rows, ch)
                V = curve_visual(rows, ch, fam)
                if not A or not V: continue
                if mono:
                    A = list(zip([p[0] for p in A],
                                 pava([p[0] for p in A], [p[1] for p in A], [p[2] for p in A]),
                                 [p[2] for p in A]))
                Vm = list(zip([p[0] for p in V],
                              pava([p[0] for p in V], [p[1] for p in V], [p[2] for p in V]),
                              [p[2] for p in V]))
                seq = []; clip_lo = clip_hi = 0
                for t, p, n in A:
                    s, cl = invert(Vm, p)
                    if cl == "low": clip_lo += 1
                    if cl == "high": clip_hi += 1
                    seq.append({"t_ms": t, "target_p": round(p, 4), "s_pct": round(s, 4),
                                "clipped": cl})
                tables[tag][fam][ch] = seq
                back = [x["s_pct"] for x in seq]
                nonmono = sum(1 for i in range(len(back) - 1) if back[i + 1] < back[i] - 1e-9)
                report.append({
                    "mode": tag, "family": fam, "char": ch,
                    "n_points": len(seq),
                    "clip_low": clip_lo, "clip_high": clip_hi,
                    "s_min": round(min(back), 3), "s_max": round(max(back), 3),
                    "backward_steps": nonmono,
                })
    json.dump(tables, io.open(os.path.join(out, "warp_rawp.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with io.open(os.path.join(out, "warp_rawp_report.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0].keys())); w.writeheader()
        for r in report: w.writerow(r)
    # 画面表示
    print("■ 生の正答率で逆引きした結果\n")
    for tag in ("raw", "isotonic"):
        print(f"  ── {'そのまま' if tag=='raw' else '保序回帰で単調化してから'}")
        print(f"     {'方式':<12}{'字':<3}{'点数':>4}{'床で丸め':>9}{'天井で丸め':>10}"
              f"{'sの範囲':>18}{'逆走':>6}")
        for r in report:
            if r["mode"] != tag: continue
            flag = ""
            if r["clip_low"] or r["clip_high"]: flag = "  ←丸めあり"
            if r["backward_steps"]: flag += "  ←戻る"
            print(f"     {LAB[r['family']]:<12}{r['char']:<3}{r['n_points']:>4}"
                  f"{r['clip_low']:>9}{r['clip_high']:>10}"
                  f"{r['s_min']:>8.2f}%〜{r['s_max']:>6.2f}%{r['backward_steps']:>6}{flag}")
        print()
    print(f"  書き出し: {out}/warp_rawp.json, warp_rawp_report.csv")

if __name__ == "__main__":
    main()
