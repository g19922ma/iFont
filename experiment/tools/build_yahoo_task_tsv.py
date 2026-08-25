#!/usr/bin/env python3
"""募集サイトにアップロードする設問ファイル(TSV)を作る。

**なぜ設問を人数分作るのか**: 募集サイトが URL に作業者IDを差し込む仕組みを持つか
確認できなかった(2026-08-25 に公式ページを見たが記載なし)。差し込めないと参加者IDが
毎回ランダムになり、**サーバの名簿による重複参加のお断りが働かない**。
そこで「設問数＝募集人数・1タスク1問・重複出題1回」の設定を使い、
**設問ごとに違うIDを埋めたURLを出す**ことで1人1つのIDを配る。

**IDは連番にしない**。連番だと作業者が番号を書き換えて他人ぶんのURLを開け、
その人の割り当てを消費してしまう。当てにくいランダムな英数字にする。
IDは build_task_widlist.py と同じ規則で作るので、両者は必ず一致する。

**サイトが示すアップロードの条件**(2026-08-25 時点):
  1. 文字コードは UTF-8 か Shift_JIS
  2. ファイルサイズは 90MB 以内
  3. 「"」「<」htmlタグ・特殊文字は削除してからアップロードする
  4. 1設問あたりの最大文字数は 10,000 文字以内
  5. 行数はチェック設問を含め 10,500 行以内(ヘッダを含まない)
このツールは 3・4・5 を書き出す前に検査し、破るときは止まる。

使い方:
    python3 experiment/tools/build_yahoo_task_tsv.py \\
        --template ~/Downloads/3589593482.tsv --n 230 --phase calib
"""
import argparse, csv, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_task_widlist import token          # IDの作り方を1か所にまとめる

# 条件3。サイトが消せと言っている文字。
BANNED = {'"': "二重引用符", "<": "小なり記号", ">": "大なり記号"}
MAX_CHARS_PER_QUESTION = 10_000              # 条件4
MAX_ROWS = 10_500                            # 条件5


def read_header(path: Path) -> tuple[list[str], str]:
    """テンプレートの見出し行を、文字コードを判別して読む。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        line = text.splitlines()[0] if text.splitlines() else ""
        if "設問ID" in line:
            return line.split("\t"), enc
    raise SystemExit(f"エラー: {path} の見出し行を読めなかった。"
                     "文字コードが UTF-8 でも Shift_JIS でもない可能性がある。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True,
                    help="サイトから落としたテンプレートTSV(見出し行を写す)")
    ap.add_argument("--n", type=int, required=True, help="募集人数(＝設問数)")
    ap.add_argument("--phase", default="calib", help="calib / test / comfort")
    ap.add_argument("--base", default="https://kana-task.web.app")
    ap.add_argument("--path", default=None, help="入口のパス。省略時は phase から決める")
    ap.add_argument("--seed", default="ifont-transfer-2026",
                    help="種。build_task_widlist.py と同じにすること")
    ap.add_argument("--length", type=int, default=6)
    ap.add_argument("--encoding", default="cp932", choices=["cp932", "utf-8"],
                    help="書き出す文字コード。既定はテンプレートに合わせて Shift_JIS")
    ap.add_argument("--out", default=None, help="出力先。省略時は project/設問_<phase>.tsv")
    a = ap.parse_args()

    path = a.path or {"calib": "/calib", "test": "/read", "comfort": "/survey"}.get(a.phase)
    if not path:
        print(f"エラー: phase '{a.phase}' の入口が分からない。--path で指定すること。",
              file=sys.stderr)
        return 1
    if not (1 <= a.n <= MAX_ROWS):
        print(f"エラー: --n は 1〜{MAX_ROWS} にすること(サイトの条件5)。", file=sys.stderr)
        return 1

    header, tmpl_enc = read_header(Path(a.template).expanduser())

    # 各欄に入れる文言。**「\"」「<」「>」は使えない**(条件3)。
    F01 = "下のリンクを開いて、課題を行ってください。所要時間は5〜10分です。"
    # 2026-08-25 丸山決定: 所属(津田塾大学 栗原研究室)は出さない。
    F02 = ("課題は外部サイト(当研究室が運営するページ)で行います。"
           "開いた時点で、音で聞く課題と画面で見る課題のどちらかに自動で振り分けられます。"
           "どちらに振り分けられても報酬は同じです。")
    F04 = "課題の最後の画面に12桁の完了コードが表示されます。下の欄に貼り付けてください。"
    F05 = "完了コード(半角12文字)"
    F06 = ""
    F07 = ""
    # ⚠ 丸かっこは**半角**にすること(条件3の「特殊文字」を避けるため)。
    #   宛先は 2026-08-25 に研究室の共有アドレスから栗原先生の大学アドレスへ変更した。
    F08 = ("完了コードが表示される画面まで到達しないと、報酬をお支払いできません。"
           "ご不明な点は、栗原一貴(kurihara@tsuda.ac.jp)までお問い合わせください。")

    rows = []
    for i in range(1, a.n + 1):
        w = token(a.phase, i, a.seed, a.length)
        url = f"{a.base}{path}?prod=1&wid={w}"
        # 列の並びはテンプレートの見出しに合わせる。
        rows.append([w, "0", "", "", F01, F02, url, F04, F05, F06, F07, F08])

    # --- 書き出す前の検査 -----------------------------------------------
    ids = [r[0] for r in rows]
    if len(set(ids)) != len(ids):
        print("エラー: 設問IDが重複した。--length を増やすこと。", file=sys.stderr)
        return 1
    for w in ids:
        if len(w) > 20 or not w.isalnum() or not w.isascii():
            print(f"エラー: 設問ID '{w}' が『半角英数字20文字以内』を満たさない。",
                  file=sys.stderr)
            return 1
    for r in rows:
        for cell in r:
            for ch, name in BANNED.items():
                if ch in cell:
                    print(f"エラー: {name}『{ch}』が入っている(条件3)。文言を直すこと。\n"
                          f"  該当: {cell[:60]}", file=sys.stderr)
                    return 1
        total = sum(len(c) for c in r)
        if total > MAX_CHARS_PER_QUESTION:
            print(f"エラー: 設問 {r[0]} が {total} 文字で、"
                  f"上限 {MAX_CHARS_PER_QUESTION} を超えた(条件4)。", file=sys.stderr)
            return 1
    if len(header) != len(rows[0]):
        print(f"エラー: テンプレートの列数 {len(header)} と、作った行の列数 "
              f"{len(rows[0])} が合わない。テンプレートが変わった可能性がある。",
              file=sys.stderr)
        return 1

    out = Path(a.out) if a.out else Path(f"project/設問_{a.phase}.tsv")
    out.parent.mkdir(parents=True, exist_ok=True)
    # csv モジュールは使わず自分で連結する。**引用符を一切付けさせないため**である
    # (条件3が「\"」を禁じているので、csv が自動で付けるとその時点で違反になる)。
    # タブ・改行が値に混ざっていないことは上の検査で担保されている。
    for r in rows:
        for cell in r:
            if "\t" in cell or "\n" in cell or "\r" in cell:
                print(f"エラー: 設問 {r[0]} の値にタブか改行が入っている。", file=sys.stderr)
                return 1
    body = "\r\n".join("\t".join(r) for r in [header] + rows) + "\r\n"
    try:
        out.write_bytes(body.encode(a.encoding))
    except UnicodeEncodeError as e:
        print(f"エラー: {a.encoding} で書けない文字がある。--encoding utf-8 にするか、"
              f"文言を直すこと。\n  {e}", file=sys.stderr)
        return 1

    size = out.stat().st_size
    if size > 90 * 1024 * 1024:                     # 条件2
        print(f"エラー: {size} バイトで 90MB を超えた(条件2)。", file=sys.stderr)
        return 1

    print(f"{a.n} 設問を書き出した(phase={a.phase} path={path} 種={a.seed})")
    print(f"  出力: {out}  {size:,} バイト  文字コード={a.encoding}  改行=CRLF")
    print(f"  テンプレートの文字コード: {tmpl_enc}")
    print(f"  列: {len(header)}（見出しはテンプレートのまま）")
    print(f"  1設問の文字数: {sum(len(c) for c in rows[0])}（上限 {MAX_CHARS_PER_QUESTION}）")
    print(f"  先頭: 設問ID {rows[0][0]}  {rows[0][6]}")
    print(f"  末尾: 設問ID {rows[-1][0]}  {rows[-1][6]}")
    print("  検査: 設問IDの重複なし／禁止文字なし／文字数と行数は上限内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
