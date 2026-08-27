#!/usr/bin/env python3
"""掲載中の様子を見張る。**掲載直後の数人を必ず確認するためのもの。**

⚠ **いちばん確かめたいのは「本物の参加者が本番扱いで記録されているか」**である。
  URL から wid が落ちると参加者IDが `anon-` になり、配布リストに無いので
  **自動的にテスト扱い**になる。掲載が始まってからこれに気づかないと、
  集めたデータが丸ごと分析の既定から外れる。

⚠ **読み取り回数を抑える。** 前回見た時刻を手元に控え、それ以降の行だけを取る。
  カウンタは2件だけ読む。1回の実行で読むのは「前回から増えたぶん＋2件」である。

使い方:
    python3 experiment/tools/watch_transfer.py                 # 1回だけ見る
    python3 experiment/tools/watch_transfer.py --since 18:00   # 時刻を指定して見直す
    python3 experiment/tools/watch_transfer.py --reset         # 控えを消して最初から
"""
import argparse, datetime, json, sys, warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
STATE = HERE / ".watch_transfer_state.json"
# 配布した wid の一覧。掲載ごとに設問ファイルが増えるので、ここに足していく。
# （calib2 のファイルにはチェック設問の行 chk01〜 が混ざるが、これは wid ではない
#   ので除いて読む。）
IDS_FILES = [
    Path("project/設問データ_一部だけ見えた文字・聞こえた音を当てる問題_0825_v2.tsv"),
    Path("project/設問データ_見え方の課題2_0827.tsv"),
]


def distributed_ids():
    ids = set()
    for p in IDS_FILES:
        if not p.exists():
            continue
        raw = p.read_bytes()
        for enc in ("cp932", "utf-8-sig", "utf-8"):
            try:
                text = raw.decode(enc); break
            except UnicodeDecodeError:
                continue
        else:
            continue
        ids |= {l.split("\t")[0].strip() for i, l in
                enumerate(text.replace("\r\n", "\n").rstrip("\n").split("\n"))
                if i and l.strip() and not l.startswith("chk")}
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="HH:MM か epoch ms。省略時は前回の続きから")
    ap.add_argument("--reset", action="store_true", help="控えを消して最初から見る")
    a = ap.parse_args()
    if a.reset and STATE.exists():
        STATE.unlink(); print("控えを消しました")

    from export_transfer_firestore import find_key, DEFAULT_PROJECT
    from google.oauth2 import service_account
    from google.cloud import firestore
    creds = service_account.Credentials.from_service_account_file(find_key(None))
    db = firestore.Client(project=DEFAULT_PROJECT, credentials=creds)

    if a.since:
        if ":" in a.since:
            now = datetime.datetime.now()
            hh, mm = a.since.split(":")
            since = int(now.replace(hour=int(hh), minute=int(mm), second=0,
                                    microsecond=0).timestamp() * 1000)
        else:
            since = int(a.since)
    elif STATE.exists():
        since = json.loads(STATE.read_text()).get("last_ts", 0)
    else:
        since = int((datetime.datetime.now() - datetime.timedelta(hours=2)).timestamp() * 1000)

    rows = [d.to_dict() or {} for d in
            db.collection("transfer_trials").where("ts", ">", since).stream()]
    counters = {}
    for cid in ("calib", "calib__test", "calib2", "calib2__test"):
        d = db.collection("transfer_counters").document(cid).get()
        counters[cid] = (d.to_dict() or {}).get("n", 0)

    ids = distributed_ids()
    when = datetime.datetime.fromtimestamp(since / 1000).strftime("%m-%d %H:%M")
    print(f"■ {when} 以降の記録：{len(rows)} 行   （配布ID {len(ids)} 件）")
    print(f"  カウンタ  calib 本番 {counters['calib']} テスト {counters['calib__test']}"
          f"  ／  calib2 本番 {counters['calib2']} テスト {counters['calib2__test']}")

    # 累計（読み取りは増やさない。増分を手元の控えに足していくだけ）。
    # 1人ぶんの行数の目安: 本命24 + 紛れ36 + 確認問題 ≒ 60行台。
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    total = state.get("total", {})   # pid → {"n":…, "ok":…, "is_test":…}
    for r in rows:
        pid = str(r.get("participant_id"))
        t = total.setdefault(pid, {"n": 0, "ok": 0, "is_test": bool(r.get("is_test"))})
        t["n"] += 1
        if str(r.get("correct")).lower() in ("true", "1"): t["ok"] += 1
        t["is_test"] = bool(r.get("is_test"))
        ts = r.get("ts") or 0
        if ts:
            t["t0"] = min(t.get("t0") or ts, ts)
            t["t1"] = max(t.get("t1") or 0, ts)
    prod = {p: t for p, t in total.items() if not t["is_test"]}
    if prod:
        ns = sorted(t["n"] for t in prod.values())
        done = sum(1 for n in ns if n >= 60)
        print(f"  累計（本番のみ）: {len(prod)} 人が回答開始 ／ 完走目安(60行以上) {done} 人"
              f" ／ 行数の中央値 {ns[len(ns)//2]}")

    if not rows:
        print("  （新しい記録はありません）")
    else:
        sess = {}
        for r in rows:
            k = (str(r.get("participant_id")), str(r.get("completion_code")))
            s = sess.setdefault(k, {"n": 0, "ts": [], "group": "", "is_test": None, "ok": 0})
            s["n"] += 1
            if r.get("ts"): s["ts"].append(r["ts"])
            s["group"] = str(r.get("group") or "")
            s["is_test"] = r.get("is_test")
            if str(r.get("correct")).lower() in ("true", "1"): s["ok"] += 1
        print()
        print(f"  {'時刻':6s} {'参加者ID':12s} {'コード':8s} {'集団':7s} {'扱い':6s} {'問':>4s} {'正答':>5s}")
        bad = []
        for (pid, code), s in sorted(sess.items(), key=lambda kv: min(kv[1]["ts"] or [0])):
            t = datetime.datetime.fromtimestamp(min(s["ts"]) / 1000).strftime("%H:%M") if s["ts"] else "?"
            listed = pid in ids
            kind = "テスト" if s["is_test"] else "本番"
            mark = "" if (listed and not s["is_test"]) or (not listed and s["is_test"]) else "  ← ⚠"
            print(f"  {t:6s} {pid[:12]:12s} {code[:8]:8s} {s['group']:7s} {kind:6s} "
                  f"{s['n']:>4d} {s['ok']:>5d}{mark}")
            if listed and s["is_test"]:
                bad.append(f"{pid} は配布リストにあるのにテスト扱い")
            if pid.startswith("anon-"):
                bad.append(f"{pid} は wid が渡っていない（URL を確認すること）")
        if bad:
            print()
            print("  ⚠ 要確認:")
            for b in sorted(set(bad)): print("    -", b)

    last = max([r.get("ts") or 0 for r in rows] + [since])
    STATE.write_text(json.dumps({"last_ts": last, "total": total}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
