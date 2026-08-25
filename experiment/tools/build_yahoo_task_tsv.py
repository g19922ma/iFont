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
import argparse, csv, re, sys
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
    ap.add_argument("--box-label", default="",
                    help="入力欄(テキストボックス)の見出し。既定は空。"
                         "空だと入力欄が出ない画面だったときに入れ直す")
    ap.add_argument("--id-style", default="token", choices=["token", "serial"],
                    help="設問IDの付け方。token=作業者IDをそのまま入れる(既定。"
                         "回答の一覧から直接ひもづく)。serial=1からの連番"
                         "(サイトの案内が勧める形。token がはねられたときの逃げ道)")
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

    # 各欄に入れる文言。**欄の名前（F01, F02, …）で指定する**ので、
    # テンプレートの列構成が変わっても位置を直さなくてよい。
    # ⚠ 「"」「<」「>」は使えない（条件3）。丸かっこは半角にする。
    # ⚠ 「##」はサイト側の改行の書き方。丸山が「設問データお試し作成」で使っていた。
    # ⚠ **丸山が「設問データお試し作成」で作った見え方をそのまま写す**
    #   （2026-08-25 指示「問題文も私のサンプルの通りに入れて」）。
    #   埋めるのは F02・F03・F04 の3つだけで、他は空にする。
    #   「##」はサイト側の改行の書き方。
    #   ⚠ 「"」「<」「>」は使えない（条件3）。丸かっこは半角にする。
    FIELDS = {
        # F04 にも「課題の最後に表示される」が入るので、こちらは縮めて重複を避ける
        # （2026-08-25 丸山了承）。
        "F02": ("ページを開き、課題を完了させてください。"
                "##最後に表示される「完了コード」を忘れずに書き留めてください。"),
        "F03": None,          # ← リンク。1行ごとに違うURLを入れるので後で埋める
        "F04": "課題の最後に表示される「完了コード」を入力してください",
        # 入力欄（完了コードを打ち込む欄）の見出し。
        # ⚠ **2026-08-25、丸山が空に戻した。**一度は「完了コード(半角6文字)」と
        #   入れたが、実際の画面を見たうえで空にする判断になった。
        #   空でも入力欄が出ることは、その画面で確かめられている前提とする。
        #   `--box-label` で入れ直せる。
    }
    # ⚠ 古い12列のテンプレート用の当て。**その見出しのときだけ使う。**
    #   新しい28列のテンプレートでは F08 が2つ目のテキストボックスなので、
    #   ここで文言を入れると**入力欄が2つ出てしまう**（実際に一度そうなった）。
    is_legacy = any(c.startswith("F05:") and "テキストボックス" in c for c in header)
    LEGACY = ({"F05": "完了コード(半角6文字)", "F08": FIELDS["F19"]} if is_legacy else {})

    # 見出しから、その列が何を入れる場所かを読み取る。
    def slot(col: str) -> str:
        if col.startswith("設問ID"):        return "qid"
        if col.startswith("チェック設問有無"): return "check_flag"
        if col.startswith("チェック設問の解答"): return "check_ans"
        m = re.match(r"(F\d+):(.*)", col)
        if m:
            return "field:" + m.group(1) + ":" + m.group(2)
        return "unknown"

    slots = [slot(c) for c in header]
    # 見出しに無い欄を FIELDS に書いていたら、その文言は**どこにも出ない**。
    have = {x.split(":")[1] for x in slots if x.startswith("field:")}
    unused = [f for f, v in FIELDS.items() if v and f not in have]
    if unused:
        print(f"エラー: FIELDS に書いた {unused} が見出しに無い。"
              "文言がどこにも出ないので、割り当てを直すこと。", file=sys.stderr)
        return 1
    if "unknown" in slots:
        bad = [header[i] for i, x in enumerate(slots) if x == "unknown"]
        print(f"エラー: 見出しに知らない列がある: {bad}\n"
              "  テンプレートが変わった可能性がある。ツールを直すこと。", file=sys.stderr)
        return 1
    if "qid" not in slots:
        print("エラー: 見出しに『設問ID』の列が無い。", file=sys.stderr)
        return 1

    # リンクを置く列と、入力欄になる列を見つける。
    link_fields = [x.split(":")[1] for x in slots if x.startswith("field:") and "リンク" in x]
    box_fields  = [x.split(":")[1] for x in slots
                   if x.startswith("field:") and ("テキストボックス" in x or "テキストエリア" in x)]
    if not link_fields:
        print("エラー: リンク（URL）を入れる列が見出しに無い。", file=sys.stderr)
        return 1
    link_field = link_fields[0]
    FIELDS[link_field] = None            # 1行ごとに埋める

    if a.box_label and box_fields:
        FIELDS[box_fields[0]] = a.box_label

    # 参加者が完了コードを入れる欄が、実際に埋まっているか。
    # **ここが空だと入力欄が出ず、完了コードを受け取れない。**
    # 入力欄を空のままにしてある（丸山のサンプルがそうだった）。
    # ⚠ **空でも入力欄が出るのかは未確認**である。出ないと完了コードを受け取れない。
    #   プレビューで必ず確かめること。出ないようなら FIELDS に文言を足す。
    filled_box = [f for f in box_fields if (FIELDS.get(f) or LEGACY.get(f))]
    if not filled_box:
        print(f"⚠ 入力欄（{'/'.join(box_fields) or 'なし'}）を空にしてある。"
              "プレビューで入力欄が出ることを必ず確かめること。", file=sys.stderr)

    rows = []
    for i in range(1, a.n + 1):
        w = token(a.phase, i, a.seed, a.length)
        url = f"{a.base}{path}?prod=1&wid={w}"
        # 設問IDは既定で作業者IDそのもの。**回答の一覧から直接ひもづく**ので楽である。
        # サイトの案内は「任意の数字・連番」を勧めているので、はねられたら --id-style serial。
        # そのときも作業者IDはURLの中に残るので、対応は build_task_widlist.py の表で付く。
        qid = w if a.id_style == "token" else str(i)
        row = []
        for x in slots:
            if x == "qid":              row.append(qid)
            elif x == "check_flag":     row.append("0")
            elif x == "check_ans":      row.append("")
            else:
                f = x.split(":")[1]
                row.append(url if f == link_field
                           else (FIELDS.get(f) or LEGACY.get(f) or ""))
        rows.append(row)

    # --- 書き出す前の検査 -----------------------------------------------
    ids = [r[0] for r in rows]
    if len(set(ids)) != len(ids):
        print("エラー: 設問IDが重複した。--length を増やすこと。", file=sys.stderr)
        return 1
    # URLに埋めた作業者IDは、設問IDの付け方によらず必ず全部違うこと。
    # ここが崩れると2人が同じ参加者IDになり、名簿が2人を1人と見なす。
    link_col = slots.index("field:" + link_field + ":"
                           + header[[x.split(":")[1] if x.startswith("field:") else ""
                                     for x in slots].index(link_field)].split(":", 1)[1])
    wids = [r[link_col].rsplit("wid=", 1)[-1] for r in rows]
    if len(set(wids)) != len(wids):
        print("エラー: URLの作業者IDが重複した。--length を増やすこと。", file=sys.stderr)
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
    assert len(header) == len(rows[0])      # slots から組み立てているので必ず一致する

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
    print(f"  先頭: 設問ID {rows[0][0]}  {rows[0][link_col]}")
    print(f"  末尾: 設問ID {rows[-1][0]}  {rows[-1][link_col]}")
    print(f"  入力欄: {'/'.join(filled_box)}（ここが空だと完了コードを受け取れない）")
    print("  検査: 設問IDの重複なし／URLの作業者IDの重複なし／禁止文字なし／文字数と行数は上限内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
