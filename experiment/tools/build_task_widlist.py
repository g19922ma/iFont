#!/usr/bin/env python3
"""募集サイトの設問データ用に、1人1つの作業者IDを埋めた課題URLを作る。

**なぜ必要か**: 募集サイトが URL に作業者IDを差し込む仕組みを持つか確認できなかった
（2026-08-25 に公式ページを確認したが記載なし）。差し込めないと参加者IDが毎回
ランダムになり、**サーバ側の名簿による重複参加のお断りが働かない**。
そこで「設問数＝募集人数・1タスク1問・重複出題1回」の設定を使い、
**設問ごとに違うIDを埋めたURLを出す**ことで、1人1つのIDを配る。

**IDは連番にしない**。連番だと作業者が番号を書き換えて他人ぶんのURLを開け、
その人の割り当てを消費してしまう。当てにくいランダムな英数字にする。

**再現性**: 種を固定しているので、同じ引数なら何度動かしても同じ表が出る。
掲載後に作り直しても対応が変わらない。

使い方:
    python3 experiment/tools/build_task_widlist.py --n 230 --phase calib
"""
import argparse, csv, hashlib, sys
from pathlib import Path

# 紛らわしい文字(0/O/1/l/I)を除く。作業者が目で写す場面はないが、
# 問い合わせのときに読み上げられる形にしておく。
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def token(phase: str, i: int, seed: str, length: int) -> str:
    """設問番号から決まる、当てにくいID。同じ引数なら必ず同じ値になる。"""
    h = hashlib.sha256(f"{seed}|{phase}|{i}".encode()).digest()
    n = int.from_bytes(h, "big")
    out = []
    for _ in range(length):
        n, r = divmod(n, len(ALPHABET))
        out.append(ALPHABET[r])
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True, help="募集人数（＝設問数）")
    ap.add_argument("--phase", default="calib", help="calib / test / comfort")
    ap.add_argument("--base", default="https://kana-task.web.app",
                    help="配信元。末尾のスラッシュは付けない")
    ap.add_argument("--path", default=None,
                    help="入口のパス。省略時は phase から決める")
    ap.add_argument("--seed", default="ifont-transfer-2026",
                    help="種。変えると全部のIDが変わるので、掲載後は変えないこと")
    ap.add_argument("--length", type=int, default=6, help="IDの文字数")
    ap.add_argument("--out", default="project/設問URL一覧",
                    help="出力先。<out>_<phase>.csv と .txt を作る")
    a = ap.parse_args()

    path = a.path or {"calib": "/calib", "test": "/read", "comfort": "/survey"}.get(a.phase)
    if not path:
        print(f"エラー: phase '{a.phase}' の入口が分からない。--path で指定すること。",
              file=sys.stderr)
        return 1
    if a.n < 1:
        print("エラー: --n は1以上にすること。", file=sys.stderr)
        return 1

    rows = []
    for i in range(1, a.n + 1):
        w = token(a.phase, i, a.seed, a.length)
        rows.append((i, w, f"{a.base}{path}?prod=1&wid={w}"))

    # 万一の衝突を検査する（6文字なら 31^6 ≒ 8.9億通りなので実質起きないが、
    # 起きたまま掲載すると2人が同じIDになり、名簿がその2人を1人と見なす）。
    ws = [r[1] for r in rows]
    if len(set(ws)) != len(ws):
        print("エラー: IDが重複した。--length を増やすか --seed を変えること。",
              file=sys.stderr)
        return 1

    csv_path = Path(f"{a.out}_{a.phase}.csv")
    txt_path = Path(f"{a.out}_{a.phase}.txt")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["設問番号", "作業者ID", "課題URL"])
        wr.writerows(rows)
    # 貼り付け用にURLだけの一覧も出す（設問登録の画面が1行1件を受ける場合に使う）。
    txt_path.write_text("\n".join(r[2] for r in rows) + "\n", encoding="utf-8")

    print(f"{a.n} 件を書き出した（phase={a.phase} path={path} 種={a.seed}）")
    print(f"  対応表: {csv_path}")
    print(f"  URLのみ: {txt_path}")
    print("  先頭3件:")
    for r in rows[:3]:
        print(f"    設問{r[0]:<4} {r[2]}")
    print(f"  末尾: 設問{rows[-1][0]} {rows[-1][2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
