#!/usr/bin/env python3
"""配布した設問ファイルの作業者IDを、transfer_config.js に書き込む。

**なぜ要るか**: 本番の参加者は、募集サイトの設問ごとに違うURLから来るので
**必ずこの一覧のどれかのID**になる。だから「一覧に無いID＝動作確認」と見なせる。
これで、動作確認のたびに `uitest-` のような前置きを覚える必要がなくなり、
**本番の通し番号を誤って消費する事故**（2集団の振り分けがずれる）を防げる。

⚠ **設問ファイルを作り直したら、必ずこれも走らせること。**
  食い違うと、本物の参加者がテスト扱いになる（記録は残るが分析から外れる）。

使い方:
    python3 experiment/tools/write_distributed_ids.py \\
        --phase calib --tsv "project/設問データ_..._v2.tsv"
    python3 experiment/tools/write_distributed_ids.py --phase calib --clear
"""
import argparse, io, json, re, sys
from pathlib import Path

CFG = Path("experiment/transfer_config.js")
MARK_A = "  // ---- 配布した作業者ID（ここは自動生成）"
MARK_B = "  // ---- 配布した作業者ID ここまで ----"


def read_ids(path: Path) -> list:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"エラー: {path} の文字コードが読めない")
    ids = []
    for i, line in enumerate(text.replace("\r\n", "\n").rstrip("\n").split("\n")):
        if i == 0 or not line.strip():
            continue
        cell = (line.split("\t")[0] if "\t" in line else line.split(",")[0]).strip().strip('"')
        if cell:
            ids.append(cell)
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["calib", "test", "comfort"])
    ap.add_argument("--tsv", help="配布した設問ファイル（TSV）か対応表（CSV）")
    ap.add_argument("--clear", action="store_true", help="そのフェーズの一覧を消す")
    a = ap.parse_args()
    if not a.clear and not a.tsv:
        print("エラー: --tsv か --clear のどちらかを指定すること。", file=sys.stderr)
        return 1

    src = CFG.read_text(encoding="utf-8")
    m = re.search(re.escape(MARK_A) + r".*?" + re.escape(MARK_B) + r"\n", src, re.S)
    current = {}
    if m:
        body = m.group(0)
        j = re.search(r"distributed_wids:\s*(\{.*?\}),\n", body, re.S)
        if j:
            current = json.loads(j.group(1).replace("\n", " "))

    if a.clear:
        current.pop(a.phase, None)
        print(f"{a.phase} の一覧を消しました")
    else:
        ids = read_ids(Path(a.tsv))
        if len(ids) != len(set(ids)):
            print("エラー: 作業者IDが重複している。", file=sys.stderr)
            return 1
        bad = [x for x in ids if not (x.isalnum() and x.isascii())]
        if bad:
            print(f"エラー: 半角英数字でないIDがある: {bad[:5]}", file=sys.stderr)
            return 1
        current[a.phase] = ids
        print(f"{a.phase}: {len(ids)} 件を書き込みました（{a.tsv}）")

    lines = [MARK_A,
             "  //",
             "  // ⚠ **手で書かないこと。** experiment/tools/write_distributed_ids.py が入れる。",
             "  //   設問ファイルを作り直したら必ず走らせ直すこと。食い違うと、本物の参加者が",
             "  //   テスト扱いになる（記録は残るが、分析の既定から外れる）。",
             "  //",
             "  // ここに載っているIDだけが**本番の通し番号**を使う。載っていないIDは",
             "  // 自動的に試し打ち扱いになり、テスト用のカウンタから配られる。",
             "  // これで、動作確認のたびに前置き（uitest- など）を覚える必要がなくなる。",
             "  distributed_wids: " + json.dumps(current, ensure_ascii=False, separators=(",", ":")) + ",",
             MARK_B]
    block = "\n".join(lines) + "\n"

    if m:
        src = src[:m.start()] + block + src[m.end():]
    else:
        anchor = "  phases: {"
        i = src.index(anchor)
        src = src[:i] + block + "\n" + src[i:]
    CFG.write_text(src, encoding="utf-8")
    for k, v in current.items():
        print(f"  {k}: {len(v)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
