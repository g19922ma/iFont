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

採番カウンタ（transfer_counters）について
------------------------------------------
既定では**触らない**。カウンタは「そのフェーズに何人来たか」の通し番号である。
掲載の前に0から始めたいときだけ `--reset-counters` を付ける。
**掲載が始まったあとに使わないこと**（既に配った番号と重なる）。
試し打ち用のカウンタ（`calib__test` など。掲載前フラグが立っているあいだ、または
参加者IDの頭が `curltest-` のときはこちらから番号を配る）も一緒に0へ戻す。

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

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from export_transfer_firestore import find_key, DEFAULT_PROJECT  # noqa: E402

COLLECTIONS = ["transfer_trials", "transfer_wellbeing", "transfer_roster"]
PHASES = ["calib", "test", "comfort"]
# 試し打ち用の採番カウンタ。transfer_firestore.js の counterIdFor と同じ規則。
TEST_COUNTER_SUFFIX = "__test"


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
    args = ap.parse_args()

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
