# -*- coding: utf-8 -*-
"""一対比較（実験C）の集計。

入力: data/raw/pair_一対比較/wellbeing_comfort.jsonl
出力: pair_tests.csv / thurstone_natural.csv / thurstone_prefer.csv
      thurstone_natural_ci.csv / thurstone_prefer_ci.csv / pair_by_char.csv

やっていること
  1. 本番の比較試行だけを取り出す（is_test を除き、record_kind='clip'）
  2. 同じ人が同じ組を 2 回見た記録は 1 回に数える（やり直しで重複するため）
  3. ペア種ごとに、8 文字をまとめた二項検定（帰無仮説は選択率 0.5）。
     96 本すべてを実施し、Holm 法で補正する
  4. Thurstone Case V で 16 通りを 1 本の尺度に並べる。
     参加者を単位としたブートストラップ（1,000 回）で 95% 信頼区間を付ける
"""
import json, sys, collections
import numpy as np
from scipy.stats import binomtest, norm

FAM = {"fade": "うすい", "reveal": "点ふえ", "blur": "ぼかし", "wipe": "端から"}
COND = {"c1_acc_shape": "c1", "c2_info_shape": "c2",
        "c3_acc_mid": "c3", "c4_info_mid": "c4"}
COND_LABEL = {"c1": "正答率", "c2": "情報量", "c3": "正答率中点", "c4": "情報量中点"}
VARY = {"family": "方式", "condition": "出し方"}
QS = ["natural", "prefer"]


def load(path):
    """比較の記録を (質問, ペア種, 文字, 参加者, どちらを選んだか) に開く。"""
    # やり直しで同じ組が 2 回入ることがある。答えが割れた例が 1 件あるため、
    # 「あとに答えた方を残す」で統一する（時刻の順に読み、同じ鍵を上書きする）。
    recs = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("is_test") or r.get("record_kind") != "clip":
            continue
        w = r.get("wellbeing_json")
        d = json.loads(w) if isinstance(w, str) else w
        if not d or d.get("kind") != "pair":
            continue
        pid = r["participant_id"]
        a = f'{FAM[d["left"]]}·{COND[d["leftCond"]]}'
        b = f'{FAM[d["right"]]}·{COND[d["rightCond"]]}'
        key = (pid, d["ch"], tuple(sorted([a, b])))
        recs[key] = (r.get("ts"), a, b, d)          # 同じ鍵はあとの記録で上書き

    out = []
    for (pid, ch, _), (_ts, a, b, d) in recs.items():
        # ペア種は左右をそろえて数える（どちらが左に出たかは割付で入れ替わるため）
        v1, v2 = (a, b) if a <= b else (b, a)
        for q in QS:
            sc = (d.get("scores") or {}).get(q)
            if sc is None:
                continue
            # 強制二択。値は -1 が左（A）、+1 が右（B）
            win = a if sc < 0 else b
            out.append(dict(q=q, vary=VARY[d["vary"]], v1=v1, v2=v2,
                            char=ch, pid=pid, win1=(win == v1)))
    return out


def holm(ps):
    """Holm 法。元の並びのまま補正後の p を返す。"""
    idx = np.argsort(ps)
    out = np.empty(len(ps)); run = 0.0
    for k, i in enumerate(idx):
        run = max(run, (len(ps) - k) * ps[i])
        out[i] = min(run, 1.0)
    return out


def tests(rows):
    """ペア種ごとに 8 文字をまとめた二項検定。"""
    g = collections.defaultdict(lambda: [0, 0])      # [勝ち, 合計]
    meta = {}
    for r in rows:
        k = (r["q"], r["v1"], r["v2"])
        g[k][0] += int(r["win1"]); g[k][1] += 1
        meta[k] = r["vary"]
    keys = list(g)
    ps = np.array([binomtest(g[k][0], g[k][1], 0.5).pvalue for k in keys])
    ph = holm(ps)
    out = []
    for k, p, q in zip(keys, ps, ph):
        win1, n = g[k]
        out.append(dict(q=k[0], vary=meta[k], v1=k[1], v2=k[2],
                        n=n, win1=win1, P1=win1 / n, p=p, p_holm=q))
    out.sort(key=lambda r: r["p_holm"])
    return out


def thurstone(rows, q):
    """Thurstone Case V。s_i - s_j = z(P_ij) を最小二乗で解く。
       比べていない組があるので、全組合せは埋まらない。"""
    g = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if r["q"] != q:
            continue
        g[(r["v1"], r["v2"])][0] += int(r["win1"]); g[(r["v1"], r["v2"])][1] += 1
    names = sorted({n for k in g for n in k})
    ix = {n: i for i, n in enumerate(names)}
    A, y = [], []
    for (a, b), (w, n) in g.items():
        P = min(max(w / n, 0.5 / n), 1 - 0.5 / n)     # 0 と 1 を避ける
        row = np.zeros(len(names)); row[ix[a]] = 1; row[ix[b]] = -1
        A.append(row); y.append(norm.ppf(P))
    A = np.vstack(A + [np.ones(len(names))])          # 平均 0 の制約を足す
    y = np.array(y + [0.0])
    s = np.linalg.lstsq(A, y, rcond=None)[0]
    s = s - s.min()                                   # 最下位を 0 にそろえる
    return {n: s[ix[n]] for n in names}


def boot_ci(rows, q, n_boot=1000, seed=0):
    """参加者を単位に取り直して 95% 信頼区間を出す。"""
    rng = np.random.default_rng(seed)
    by_pid = collections.defaultdict(list)
    for r in rows:
        if r["q"] == q:
            by_pid[r["pid"]].append(r)
    pids = list(by_pid)
    names = sorted({n for r in rows for n in (r["v1"], r["v2"])})
    acc = {n: [] for n in names}
    for _ in range(n_boot):
        pick = rng.choice(len(pids), len(pids), replace=True)
        sub = [r for i in pick for r in by_pid[pids[i]]]
        try:
            s = thurstone(sub, q)
        except Exception:
            continue
        for n in names:
            if n in s:
                acc[n].append(s[n])
    return {n: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
            for n, v in acc.items() if v}


def by_char(rows):
    g = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = (r["q"], r["v1"], r["v2"], r["char"])
        g[k][0] += int(r["win1"]); g[k][1] += 1
    return [dict(q=k[0], v1=k[1], v2=k[2], char=k[3], win1=v[0], n=v[1])
            for k, v in sorted(g.items())]


def write(path, rows, cols):
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in cols})


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "wellbeing_comfort.jsonl"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    rows = load(src)
    print(f"判定 {len(rows)//2} 件 ／ 参加者 {len({r['pid'] for r in rows})} 名")
    t = tests(rows)
    write(f"{out}/pair_tests.csv", t, ["q", "vary", "v1", "v2", "n", "win1", "P1", "p", "p_holm"])
    sig = [r for r in t if r["p_holm"] < 0.05]
    print(f"補正後に有意 {len(sig)} 本／{len(t)} 本")
    for q in QS:
        s = thurstone(rows, q)
        ci = boot_ci(rows, q)
        srt = sorted(s.items(), key=lambda kv: -kv[1])
        write(f"{out}/thurstone_{q}.csv",
              [dict(variant=k, score=round(v, 3)) for k, v in srt], ["variant", "score"])
        write(f"{out}/thurstone_{q}_ci.csv",
              [dict(variant=k, score=round(v, 3),
                    ci_lo=round(ci[k][0], 3), ci_hi=round(ci[k][1], 3))
               for k, v in srt if k in ci], ["variant", "score", "ci_lo", "ci_hi"])
        print(f"  {q}: 1位 {srt[0][0]} {srt[0][1]:.3f} ／ 最下位 {srt[-1][0]} {srt[-1][1]:.3f}")
    write(f"{out}/pair_by_char.csv", by_char(rows), ["q", "v1", "v2", "char", "win1", "n"])
    print("書き出した:", out)
