#!/usr/bin/env python3
"""
Firestore に溜まった転写検証実験の記録を CSV に落とす
=====================================================

`analyze_transfer.py` が**そのまま読める形**で出す。つまり、GAS のスプレッドシートを
CSV に保存したときと**同じ列名・同じ並び**にする。だから解析側のコードは
「GAS から取ったか Firestore から取ったか」を気にしなくてよい。

出るもの（`--out` の下）
------------------------
  transfer_trials.csv     1問1行の回答
  transfer_wellbeing.csv  見え心地の評価（群Bの末尾ぶんと群Cぶん）
  transfer_roster.csv     名簿（誰がどの集団の何番目か）

つなぎ方
--------
  python3 experiment/tools/export_transfer_firestore.py --out project/pilot_data/firestore
  python3 experiment/tools/analyze_transfer.py \
      --in project/pilot_data/firestore/transfer_trials.csv \
      --out project/pilot_data/out

鍵について（**ここだけ人の手が要る**）
--------------------------------------
参加者のブラウザが使うウェブAPIキーでは**読み出せない**。読み出しを禁止するのが
セキュリティルールの要点だからである（`firebase/firestore.transfer.rules`）。
解析するときだけ、管理者の資格で読む。そのための鍵（サービスアカウントの鍵）は
Firebase コンソールで1回だけ作る。

  Firebase コンソール → プロジェクトの設定（歯車）→ サービス アカウント
    → 「新しい秘密鍵の生成」→ ダウンロードした JSON を次の場所に置く
        firebase/ifont-transfer-sa.json

  ⚠ **この鍵は本物の秘密である**（ウェブAPIキーとは性質がまったく違う。
    これがあれば全データを読めるし消せる）。`.gitignore` に入れてあるので
    コミットされないが、**人に渡さない・チャットに貼らない**こと。

鍵の場所は次の順に探す。
  1. --key で渡したパス
  2. 環境変数 GOOGLE_APPLICATION_CREDENTIALS
  3. firebase/ifont-transfer-sa.json（リポジトリ直下から見て）

試し打ちの行について
--------------------
動作確認で作った行には `is_test = true` が付く。付く条件は2つあり、どちらかに
当てはまれば付く。

  1. 参加者IDの頭が `curltest-` / `uitest-`（疎通確認・画面確認）
  2. 掲載前フラグが立っていた（`experiment/transfer_config.js` の `pre_launch`）。
     これが true のあいだは、本番モード（`?prod=1`）で動かしても全レコードに印が付く

印の付いた行は**回答・見え心地・名簿のどれも既定で出力から外す**。混ぜたいときは
`--include-test`。名簿の連番も本番とは別のカウンタ（`calib__test` など）から
配られているので、試し打ちが本番の連番を食いつぶすことはない。
"""
import argparse
import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_KEY = os.path.join(REPO, "firebase", "ifont-transfer-sa.json")
DEFAULT_PROJECT = "ifont-transfer"

# GAS のシートのヘッダと**同じ列・同じ並び**。ここを変えると解析側が読めなくなる。
# 元は gas_transfer/code.gs の handleTransferTrial / handleTransferWellbeing /
# transferStatus が appendRow しているヘッダ行。
COLUMNS = {
    "transfer_trials": [
        "ts", "participant_id", "worker_id", "completion_code",
        "phase", "group", "assign_index", "assign_source", "trial_index",
        "stimulus_id", "target_char", "response_char", "correct",
        "modality", "family", "condition", "gate_ms", "progress_pct",
        "is_filler", "check_kind", "is_catch", "n_choices",
        "rt_ms", "actual_ms", "actual_frames", "actual_s", "progress_source", "base_anim_ms",
        "ua", "dpr", "screen", "touch", "refresh_hz", "audio_device",
        "resume_count", "resume_gap_s", "version", "config_version",
        "is_test",
    ],
    # transfer_wellbeing には3種類の行が混ざる。**record_kind で見分けること。**
    #   ""/"final" … 見え心地の回答（1参加者1行）。**分析はこれを読む**
    #   "clip"     … 群Cの1本ぶんの中間レコード（12行／人）。最後の1行が落ちたときの
    #                 保険なので、分析では使わない
    #   "session"  … 完走レコード（1セッション1行）。較正・検証・群Cのどの集団も送る。
    #                 **承認の判定はこの行だけで済む**（completion_code・n_trials・
    #                 duration_s・send_failures が入っている）
    # 承認作業のときは、まず record_kind == "session" の行から completion_code を引く。
    "transfer_wellbeing": [
        "ts", "participant_id", "worker_id", "completion_code",
        "record_kind", "modality",
        "phase", "group", "assign_index", "assign_source",
        "choice", "wellbeing_json",
        "n_trials", "duration_s", "send_failures", "send_retries",
        "ua", "dpr", "screen", "touch", "refresh_hz", "version", "config_version",
        "is_test",
    ],
    "transfer_roster": [
        "ts", "phase", "participant_id", "worker_id", "group", "assign_index", "is_test",
    ],
}

# 並べ替えの鍵。GAS のシートは追記順（＝おおむね時刻順）なので、それにそろえる。
SORT_KEYS = {
    "transfer_trials": ("participant_id", "trial_index", "ts"),
    "transfer_wellbeing": ("participant_id", "record_kind", "ts"),
    "transfer_roster": ("phase", "assign_index", "ts"),
}


def find_key(explicit):
    for p in (explicit, os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"), DEFAULT_KEY):
        if p and os.path.exists(p):
            return p
    return None


def cell(v):
    """Firestore の値を CSV の1マスにする。GAS のシートの見え方にそろえる。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        # GAS のシートは TRUE / FALSE と入る。analyze_transfer.py は
        # true/TRUE/1/はい のどれでも真と読むので、そちらに合わせる。
        return "TRUE" if v else "FALSE"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def sort_key_for(name, row):
    keys = SORT_KEYS.get(name, ())
    out = []
    for k in keys:
        v = row.get(k)
        # 数と文字が混ざっても落ちないように、(型の順, 値) の組にする。
        if v is None:
            out.append((0, ""))
        elif isinstance(v, bool):
            out.append((1, int(v)))
        elif isinstance(v, (int, float)):
            out.append((1, v))
        else:
            out.append((2, str(v)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="CSV を書く先のフォルダ")
    ap.add_argument("--key", default=None, help="サービスアカウントの鍵 JSON")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--include-test", action="store_true",
                    help="疎通確認の行（is_test）も混ぜて出す")
    ap.add_argument("--collections", default=",".join(COLUMNS.keys()),
                    help="出すコレクション（コンマ区切り）")
    args = ap.parse_args()

    key_path = find_key(args.key)
    if not key_path:
        sys.exit(
            "サービスアカウントの鍵が見つかりません。\n"
            "  Firebase コンソール → プロジェクトの設定 → サービス アカウント\n"
            "    → 「新しい秘密鍵の生成」\n"
            f"  ダウンロードした JSON を {DEFAULT_KEY} に置くか、--key で渡してください。\n"
            "  （この鍵は本物の秘密です。コミットも共有もしないこと。）"
        )

    try:
        from google.cloud import firestore
        from google.oauth2 import service_account
    except ImportError:
        sys.exit("google-cloud-firestore が要ります:  pip install google-cloud-firestore")

    creds = service_account.Credentials.from_service_account_file(key_path)
    db = firestore.Client(project=args.project, credentials=creds)

    os.makedirs(args.out, exist_ok=True)
    total = {}

    for name in [c.strip() for c in args.collections.split(",") if c.strip()]:
        cols = COLUMNS.get(name)
        if not cols:
            print(f"  ! 知らないコレクション {name} は飛ばします")
            continue

        rows, skipped = [], 0
        for doc in db.collection(name).stream():
            d = doc.to_dict() or {}
            if not args.include_test and d.get("is_test"):
                skipped += 1
                continue
            rows.append(d)

        rows.sort(key=lambda r: sort_key_for(name, r))

        # 決めた列に無い列が来たら、落とさず末尾に足して知らせる
        # （コードを直して列を増やしたのに、ここを直し忘れたときに気づけるように）。
        extra = sorted({k for r in rows for k in r} - set(cols))
        if extra:
            print(f"  ! {name}: 表に無い列がありました → 末尾に足します: {', '.join(extra)}")
        header = cols + extra

        path = os.path.join(args.out, name + ".csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            for r in rows:
                w.writerow([cell(r.get(c)) for c in header])

        total[name] = len(rows)
        note = f"（試し打ち {skipped} 行は外した）" if skipped else ""
        print(f"  {name}: {len(rows)} 行 → {path} {note}")

    print("\n合計:", ", ".join(f"{k}={v}" for k, v in total.items()) or "（0件）")
    if total.get("transfer_trials"):
        print("\n次はこれで分析できます:")
        print(f"  python3 experiment/tools/analyze_transfer.py \\")
        print(f"      --in {os.path.join(args.out, 'transfer_trials.csv')} \\")
        print(f"      --out {os.path.join(args.out, 'analysis')}")


if __name__ == "__main__":
    main()
