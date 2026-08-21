#!/usr/bin/env python3
"""
Firestore から「試し打ちの行」だけを消す
========================================

疎通確認や画面確認で作った行（参加者IDが `curltest-` / `uitest-` で始まるもの）には
`is_test = true` が付いている。**それだけ**を消す。GAS 版の
`action=transfer_purge_test` と同じ役目である。

    python3 experiment/tools/purge_transfer_firestore.py            # 何が消えるかを見るだけ
    python3 experiment/tools/purge_transfer_firestore.py --yes      # 実際に消す

**本物の参加者の行には手が届かない。** `is_test` が真の行しか対象にしないので、
消しすぎる事故が起きない。名簿（transfer_roster）の試し打ちの行も一緒に消えるので、
同じ参加者IDでもう一度疎通確認ができる。

採番カウンタ（transfer_counters）について
------------------------------------------
既定では**触らない**。カウンタは「そのフェーズに何人来たか」の通し番号で、
試し打ちのぶんも数に入っている。掲載の前に0から始めたいときだけ `--reset-counters`
を付ける。**掲載が始まったあとに使わないこと**（既に配った番号と重なる）。

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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="実際に消す（付けないと数えるだけ）")
    ap.add_argument("--key", default=None, help="サービスアカウントの鍵 JSON")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--reset-counters", action="store_true",
                    help="採番カウンタを0に戻す（掲載前だけ・掲載後は使わない）")
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
        print("  transfer_counters: 3フェーズぶんを0に戻します")
        if args.yes:
            for p in PHASES:
                db.collection("transfer_counters").document(p).set({"n": 0})

    if args.yes:
        print(f"\n消しました（{total} 行）。")
    else:
        print(f"\n合計 {total} 行が対象です。実際に消すには --yes を付けてください。")


if __name__ == "__main__":
    main()
