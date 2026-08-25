#!/usr/bin/env python3
"""
Firestore の「試し打ちの行」を消す／あとから印を付ける
=====================================================

動作確認で作った行には `is_test = true` が付いている（参加者IDの頭が `curltest-` /
`uitest-` の回と、掲載前フラグ `pre_launch` が立っていたあいだの回）。
**印の付いた行だけ**を消す。GAS 版の `action=transfer_purge_test` と同じ役目である。

    python3 experiment/tools/purge_transfer_firestore.py            # 何が消えるかを見るだけ
    python3 experiment/tools/purge_transfer_firestore.py --yes      # 実際に消す

**本物の参加者の行には手が届かない。** `is_test` が真の行しか対象にしないので、
消しすぎる事故が起きない。名簿（transfer_roster）の試し打ちの行も一緒に消えるので、
同じ参加者IDでもう一度疎通確認ができる。

印の付いていない行に、あとから印を付ける（`--mark-test`）
---------------------------------------------------------
掲載前フラグを入れる前（2026-08-22 より前）は、参加者IDの頭だけが目印だったので、
動作確認のつもりが本番扱いで入ってしまった行に印が付いていない。消さずに残したまま
分析から外したいときは、コレクションとドキュメントIDを名指しで印を付ける。

    python3 experiment/tools/purge_transfer_firestore.py \
        --mark-test transfer_roster/calib_anon-eiq54sm9          # 付ける前に中身を見る
    python3 experiment/tools/purge_transfer_firestore.py \
        --mark-test transfer_roster/calib_anon-eiq54sm9 --yes    # 実際に印を付ける

参加者のブラウザからは名簿を書き換えられない（ルールで update を禁止している）が、
この道具は管理者の資格（サービスアカウントの鍵）で動くのでルールを通らずに直せる。

参加者ID・ts の範囲で、まとめて印を付ける／消す（`--participants` / `--ts-from` / `--ts-to`）
-------------------------------------------------------------------------------------------
`--mark-test` は1ドキュメントずつしか指定できない。掲載前フラグが立っていない時間帯に
`anon-` のようなふつうの参加者IDのまま動作確認をしてしまうと `is_test` が付かず、
本物の行と見分けが付かなくなる。しかもドキュメントIDがランダム（回答・見え心地）だと
1件ずつ指定するのは非現実的なので、参加者IDの列挙／ts の範囲で3コレクションを
横断してまとめて対象を絞れるようにしてある。

    # まず対象を見るだけ（コレクション・参加者ID・行数・日時範囲・config_version の一覧）
    python3 experiment/tools/purge_transfer_firestore.py \
        --participants anon-darawfgc,anon-w071hbw7,anon-zwqe3zvc,anon-y0x05w11,anon-tp56ewrj,anon-11pism0f

    # 印を付ける（行は残す。--yes を付けて初めて書き込む）
    python3 experiment/tools/purge_transfer_firestore.py --participants anon-xxxx,... --yes

    # 印ではなく消す
    python3 experiment/tools/purge_transfer_firestore.py --participants anon-xxxx,... --delete --yes

    # ts の範囲でも同じことができる（ISO8601。タイムゾーンを省くとJST扱い）
    python3 experiment/tools/purge_transfer_firestore.py \
        --ts-from 2026-08-24T12:19:00 --ts-to 2026-08-24T16:40:00 --yes

`--participants` と `--ts-from`/`--ts-to` は併用できる（両方を満たす行だけが対象になる）。
`is_test` が既にTrueの行はここでは対象にしない（それは上の既定の一括削除が担当する。
二重に手を出すと「何が原因で消えたか」が追いにくくなるため、役割を分けている）。

採番カウンタ（transfer_counters）について
------------------------------------------
既定では**触らない**。カウンタは「そのフェーズに何人来たか」の通し番号である。
掲載の前に0から始めたいときだけ `--reset-counters` を付ける。
**掲載が始まったあとに使わないこと**（既に配った番号と重なる）。
試し打ち用のカウンタ（`calib__test` など。掲載前フラグが立っているあいだ、または
参加者IDの頭が `curltest-` のときはこちらから番号を配る）も一緒に0へ戻す。

⚠ 名簿（transfer_roster）の行に `is_test` の印を付けても、削除しても、この採番カウンタは
**連動して減らない**。`bumpCounter`（`transfer_firestore.js`）はカウンタドキュメントの
`n` を increment 変換で増やすだけで、名簿の行数や中身を読んでいないためである。
連番を0から出直したいときは、印付け／削除のあとで**必ず別途** `--reset-counters` を使うこと。

鍵について
----------
参加者のブラウザが使うウェブAPIキーでは消せない（ルールで delete を禁止しているため）。
管理者の資格＝サービスアカウントの鍵が要る。置き場所と作り方は
`experiment/tools/export_transfer_firestore.py` の冒頭に書いてある。

掲載前で、まだ本物のデータが1件も無いときは、鍵なしでも丸ごと消せる:

    firebase firestore:delete transfer_trials    -r --project ifont-transfer --force
    firebase firestore:delete transfer_wellbeing -r --project ifont-transfer --force
    firebase firestore:delete transfer_roster    -r --project ifont-transfer --force
    firebase firestore:delete transfer_counters  -r --project ifont-transfer --force

**掲載が始まったあとは絶対に使わないこと**（本物の回答ごと消える）。
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from export_transfer_firestore import find_key, DEFAULT_PROJECT  # noqa: E402

COLLECTIONS = ["transfer_trials", "transfer_wellbeing", "transfer_roster"]
PHASES = ["calib", "test", "comfort"]
# 試し打ち用の採番カウンタ。transfer_firestore.js の counterIdFor と同じ規則。
TEST_COUNTER_SUFFIX = "__test"

# ts はブラウザの Date.now()（UTCエポックms）だが、実験の関係者に見せる時刻は
# 日本時間で報告されている（背景の「12:19〜16:40」もJST）。ここでの表示・
# タイムゾーン省略時の解釈もJSTにそろえる。
JST = timezone(timedelta(hours=9))

# Firestore の in 演算子の実務上の上限（30件）。越えたら分割してもらう。
MAX_IN_VALUES = 30


def parse_ts(s):
    """--ts-from/--ts-to をエポックms（int）に変換する。
    数字ならエポックmsとしてそのまま使い、そうでなければ ISO8601 として読む
    （タイムゾーンが書いていなければ JST とみなす）。"""
    if s is None:
        return None
    s = s.strip()
    if s.lstrip("-").isdigit():
        return int(s)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return int(dt.timestamp() * 1000)


def fmt_ts(ms):
    if ms is None:
        return "?"
    return datetime.fromtimestamp(ms / 1000, JST).strftime("%Y-%m-%d %H:%M:%S")


def run_bulk_select(db, args):
    """--participants / --ts-from / --ts-to で横断的に絞り込み、
    一覧表を出してから（--yes があれば）印を付ける／消す。"""
    ids = [p.strip() for p in (args.participants or "").split(",") if p.strip()]
    if len(ids) > MAX_IN_VALUES:
        sys.exit(f"--participants は一度に{MAX_IN_VALUES}件まで（Firestore の in 演算子の上限）。"
                  "分けて実行してください。")
    ts_from = parse_ts(args.ts_from)
    ts_to = parse_ts(args.ts_to)
    if not ids and ts_from is None and ts_to is None:
        sys.exit("--participants か --ts-from/--ts-to のどちらかを指定してください。")

    # ---- 3コレクションから該当行を集める ---------------------------------
    matched = {}
    for name in COLLECTIONS:
        if ids:
            docs = list(db.collection(name).where("participant_id", "in", ids).stream())
            if ts_from is not None or ts_to is not None:
                # 'in' と ts のレンジを同時にFirestore側へ渡すと複合インデックスが
                # 要ることがあるので、参加者IDで絞った結果にPython側でさらにかける。
                def in_range(d):
                    t = (d.to_dict() or {}).get("ts")
                    if ts_from is not None and (t is None or t < ts_from):
                        return False
                    if ts_to is not None and (t is None or t > ts_to):
                        return False
                    return True
                docs = [d for d in docs if in_range(d)]
        else:
            q = db.collection(name)
            if ts_from is not None:
                q = q.where("ts", ">=", ts_from)
            if ts_to is not None:
                q = q.where("ts", "<=", ts_to)
            docs = list(q.stream())
        matched[name] = [(d, d.to_dict() or {}) for d in docs]

    # is_test が既にTrueの行は、既定の一括削除（is_test==True）が担当ずみなのでここでは外す。
    # 混ぜると「どちらの経路で消えた／印が付いたか」が追えなくなるため。
    target, already_true = {}, {}
    for name, rows in matched.items():
        t = [(d, data) for d, data in rows if not data.get("is_test")]
        a = [(d, data) for d, data in rows if data.get("is_test")]
        target[name] = t
        already_true[name] = a

    # ---- 対象行の一覧表（参加者ID・コレクション・行数・日時範囲・config_version） --------
    print("対象行の一覧（is_test = False のみ。True は既定の一括削除が担当）")
    header = f"{'参加者ID':<16} {'コレクション':<18} {'行数':>4}  {'日時範囲（JST）':<38} config_version"
    print(header)
    total = 0
    grand = {}
    for name in COLLECTIONS:
        rows = target[name]
        by_pid = {}
        for _, data in rows:
            by_pid.setdefault(data.get("participant_id", "?"), []).append(data)
        for pid in sorted(by_pid):
            recs = by_pid[pid]
            tss = [r.get("ts") for r in recs if r.get("ts") is not None]
            trange = f"{fmt_ts(min(tss))} 〜 {fmt_ts(max(tss))}" if tss else "?"
            cvs = sorted({str(r.get("config_version")) for r in recs})
            print(f"{pid:<16} {name:<18} {len(recs):>4}  {trange:<38} {','.join(cvs)}")
            total += len(recs)
        grand[name] = len(rows)

    print()
    print("コレクション別合計: " + ", ".join(f"{k}={v}" for k, v in grand.items()))
    print(f"合計 {total} 行が対象です。")

    extra_true = sum(len(v) for v in already_true.values())
    if extra_true:
        print("\n（参考）同じ参加者ID／ts範囲で is_test = True の行も見つかりましたが、"
              "対象から外しています:")
        for name in COLLECTIONS:
            if already_true[name]:
                print(f"  {name}: {len(already_true[name])} 行")

    if total == 0:
        print("\n対象がありません。")
        return

    action = "削除" if args.delete else "is_test = True を付ける"
    if not args.yes:
        print(f"\n実際に「{action}」を行うには --yes を付けてください。")
        return

    for name in COLLECTIONS:
        rows = target[name]
        for i in range(0, len(rows), 400):
            batch = db.batch()
            for d, _ in rows[i:i + 400]:
                if args.delete:
                    batch.delete(d.reference)
                else:
                    batch.update(d.reference, {"is_test": True})
            batch.commit()
    print(f"\n{action}ました（{total} 行）。")
    print("※ transfer_counters（採番カウンタ）はこの操作では変わりません。"
          "連番を0からやり直すには別途 --reset-counters --yes を使ってください。")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="実際に消す（付けないと数えるだけ）")
    ap.add_argument("--key", default=None, help="サービスアカウントの鍵 JSON")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--reset-counters", action="store_true",
                    help="採番カウンタを0に戻す（掲載前だけ・掲載後は使わない）")
    ap.add_argument("--mark-test", default=None, metavar="コレクション/ID",
                    help="消さずに is_test=true を後付けする（例 transfer_roster/calib_anon-xxxx）")
    ap.add_argument("--participants", default=None, metavar="id1,id2,...",
                    help="参加者IDをコンマ区切りで指定し、3コレクションを横断してまとめて"
                         "対象にする（例: anon-a,anon-b）。--ts-from/--ts-to と併用可")
    ap.add_argument("--ts-from", default=None, metavar="ISO8601 か epoch ms",
                    help="ts の下限。単独でも --participants と組み合わせても使える"
                         "（TZ省略時はJST）")
    ap.add_argument("--ts-to", default=None, metavar="ISO8601 か epoch ms",
                    help="ts の上限（同上）")
    ap.add_argument("--delete", action="store_true",
                    help="--participants/--ts-from/--ts-to で絞った行を、印を付けるかわりに"
                         "削除する（単独では何もしない）")
    args = ap.parse_args()

    bulk_select = bool(args.participants or args.ts_from or args.ts_to)
    if args.mark_test and bulk_select:
        sys.exit("--mark-test と --participants/--ts-from/--ts-to は同時に使えません。"
                  "1件だけなら --mark-test、まとめてなら --participants/--ts-from/--ts-to を使ってください。")
    if args.delete and not bulk_select:
        sys.exit("--delete は --participants/--ts-from/--ts-to と一緒に使ってください"
                  "（単独では対象が決まりません）。")

    key_path = find_key(args.key)
    if not key_path:
        sys.exit(
            "サービスアカウントの鍵が見つかりません。\n"
            "  作り方は experiment/tools/export_transfer_firestore.py の冒頭を見てください。\n"
            "  掲載前でデータが試し打ちしかないなら、鍵なしでも丸ごと消せます:\n"
            "    firebase firestore:delete transfer_trials -r --project "
            f"{args.project} --force   （他のコレクションも同様）"
        )

    from google.cloud import firestore
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(key_path)
    db = firestore.Client(project=args.project, credentials=creds)

    # ---- 印を後付けするだけの用途。消す処理には進まない ----------------------
    if args.mark_test:
        col, _, doc_id = args.mark_test.partition("/")
        if col not in COLLECTIONS or not doc_id:
            sys.exit("--mark-test は「コレクション/ドキュメントID」の形で渡してください。\n"
                     "  コレクションは " + " / ".join(COLLECTIONS) + " のどれか。")
        ref = db.collection(col).document(doc_id)
        snap = ref.get()
        if not snap.exists:
            sys.exit(f"{col}/{doc_id} は見つかりませんでした（もう消されている？）。")
        data = snap.to_dict() or {}
        print(f"  {col}/{doc_id}")
        for k in sorted(data):
            print(f"    {k} = {data[k]!r}")
        if data.get("is_test"):
            print("\n  すでに is_test = True が付いています。何もしません。")
            return
        if not args.yes:
            print("\n  is_test = True を付けるには --yes を足してください。")
            return
        ref.update({"is_test": True})
        print("\n  is_test = True を付けました（行そのものは残しています）。")
        return

    # ---- 参加者ID／ts範囲でのまとめ処理 --------------------------------------
    if bulk_select:
        run_bulk_select(db, args)
        return

    total = 0
    for name in COLLECTIONS:
        docs = list(db.collection(name).where("is_test", "==", True).stream())
        print(f"  {name}: 試し打ち {len(docs)} 行")
        total += len(docs)
        if args.yes and docs:
            # まとめて消す（1回500件までなので小分けにする）。
            for i in range(0, len(docs), 400):
                batch = db.batch()
                for d in docs[i:i + 400]:
                    batch.delete(d.reference)
                batch.commit()

    if args.reset_counters:
        ids = PHASES + [p + TEST_COUNTER_SUFFIX for p in PHASES]
        print(f"  transfer_counters: {len(ids)} 件を0に戻します"
              f"（本番3フェーズ＋試し打ち3フェーズ）")
        if args.yes:
            for p in ids:
                db.collection("transfer_counters").document(p).set({"n": 0})

    if args.yes:
        print(f"\n消しました（{total} 行）。")
    else:
        print(f"\n合計 {total} 行が対象です。実際に消すには --yes を付けてください。")


if __name__ == "__main__":
    main()
