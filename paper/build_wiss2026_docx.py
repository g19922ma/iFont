#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper/wiss2026_draft.md を WISS 2026 のテンプレートへ流し込む。

出力は 2 つ:
  1. paper/wiss2026.docx          … テンプレートのコピーに本文を入れたもの
  2. paper/wiss2026_word貼付用.md … 手で貼り直すとき用の作業ファイル（スタイル名つき）

原本 /Users/maruyama/Desktop/WISS_Template_2026_oral.docx は読むだけで書き換えない。
styles.xml・numbering.xml・header/footer・settings.xml には触らない
（python-docx はテンプレートのコピーを開き、document.xml の中身だけを差し替える）。

使い方:
    python3 paper/build_wiss2026_docx.py

マークダウンの書き方の取り決め:
    # 見出し            … 論文タイトル（スタイル WISS論文タイトル）
    ## 概要             … 次の段落が概要本文になる
    ## 1. はじめに      … 章（スタイル 段落番号1）。番号は Word が自動で振るので本文からは外す
    ### 2.1 ...         … 節（スタイル 段落番号2）
    #### 2.1.1 ...      … 項（スタイル 段落番号3）
    「図 1．」「表 1．」で始まる段落 … 図表番号（スタイル 図表番号）
    | ... | ... |       … Word の表に変換する
    ## 参考文献         … 以降の [n] 行が参考文献リスト（スタイル 参考文献。番号は自動）
    ## 執筆メモ         … ここから下は流し込まない
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

import docx
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC_MD = HERE / "wiss2026_draft.md"
TEMPLATE = Path("/Users/maruyama/Desktop/WISS_Template_2026_oral.docx")
OUT_DOCX = HERE / "wiss2026.docx"
OUT_PASTE = HERE / "wiss2026_word貼付用.md"

# スタイル名 → テンプレート内の styleId
STYLE_ID = {
    "WISS論文タイトル": "WISS",
    "著者": "aa",
    "概要本文": "aff0",
    "1 段落番号1": "1",
    "1.1 段落番号2": "2",
    "1.1.1段落番号3": "30",
    "標準": "a1",
    "図表番号": "af6",
    "謝辞，参考文献タイトル": "afe",
    "参考文献": "a",
}

# 本文の 1 段落あたりの表示幅（twips）。A4・左右マージン 1134・2 段組・段間 425。
COL_TWIPS = 4400


# --------------------------------------------------------------------------
# 1. マークダウンを読む
# --------------------------------------------------------------------------

def parse_markdown(text: str):
    """(kind, payload) の列を返す。kind は title/abstract/h1/h2/h3/body/caption/table/ref。"""
    # HTML コメントを落とす
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = text.split("\n")

    blocks: list[tuple[str, object]] = []
    i = 0
    mode = "body"          # body / abstract / refs
    buf: list[str] = []

    def flush():
        nonlocal buf
        if not buf:
            return
        para = " ".join(s.strip() for s in buf).strip()
        buf = []
        if not para:
            return
        if mode == "abstract":
            blocks.append(("abstract", para))
        elif re.match(r"^(図|表)\s*\d", para):
            blocks.append(("caption", para))
        else:
            blocks.append(("body", para))

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        if line.startswith("## 執筆メモ"):
            flush()
            break

        if line.startswith("# "):
            flush()
            blocks.append(("title", line[2:].strip()))
            mode = "body"
            i += 1
            continue

        if line.startswith("#### "):
            flush()
            t = re.sub(r"^\d+(\.\d+)*\.?\s*", "", line[5:].strip())
            blocks.append(("h3", t))
            mode = "body"
            i += 1
            continue

        if line.startswith("### "):
            flush()
            t = re.sub(r"^\d+(\.\d+)*\.?\s*", "", line[4:].strip())
            blocks.append(("h2", t))
            mode = "body"
            i += 1
            continue

        if line.startswith("## "):
            flush()
            title = line[3:].strip()
            if title == "概要":
                mode = "abstract"
            elif title == "参考文献":
                mode = "refs"
                blocks.append(("h_ref", "参考文献"))
            else:
                mode = "body"
                t = re.sub(r"^\d+(\.\d+)*\.?\s*", "", title)
                blocks.append(("h1", t))
            i += 1
            continue

        if mode == "refs":
            m = re.match(r"^\[(\d+)\]\s*(.+)$", line.strip())
            if m:
                blocks.append(("ref", m.group(2).strip()))
            i += 1
            continue

        if line.strip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(("table", rows))
            continue

        if not line.strip():
            flush()
            i += 1
            continue

        buf.append(line)
        i += 1

    flush()
    return blocks


def strip_inline(s: str) -> str:
    """マークダウンの強調記号を外す（Word 側は書式をスタイルで持つため）。"""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    return s


# --------------------------------------------------------------------------
# 2. Word の要素を作る
# --------------------------------------------------------------------------

def _p_xml(style_id: str | None, text: str, extra_ppr: str = "") -> str:
    ppr = ""
    if style_id or extra_ppr:
        st = f'<w:pStyle w:val="{style_id}"/>' if style_id else ""
        ppr = f"<w:pPr>{st}{extra_ppr}</w:pPr>"
    run = ""
    if text:
        run = (
            '<w:r><w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
        )
    return f'<w:p {nsdecls("w")}>{ppr}{run}</w:p>'


def make_p(style_id: str | None, text: str, extra_ppr: str = ""):
    return parse_xml(_p_xml(style_id, text, extra_ppr))


def make_table(rows: list[list[str]]):
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]

    # 列の幅は、その列でいちばん長い文字列の長さに比例させる（下限あり）。
    weights = []
    for c in range(ncol):
        w = max(len(rows[r][c]) for r in range(len(rows)))
        weights.append(max(w, 4))
    total = sum(weights)
    widths = [max(int(COL_TWIPS * w / total), 500) for w in weights]
    # 合計を COL_TWIPS に丸める
    widths[-1] += COL_TWIPS - sum(widths)

    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)

    def cell(txt: str, w: int, header: bool) -> str:
        b = "<w:b/>" if header else ""
        para = (
            "<w:p><w:pPr>"
            '<w:ind w:firstLineChars="0" w:firstLine="0"/><w:jc w:val="left"/>'
            '<w:rPr><w:rStyle w:val="af2"/></w:rPr>'
            "</w:pPr>"
            f'<w:r><w:rPr><w:rStyle w:val="af2"/><w:rFonts w:hint="eastAsia"/>{b}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(txt)}</w:t></w:r></w:p>'
        )
        return (
            f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>'
            "<w:vAlign w:val=\"center\"/></w:tcPr>"
            f"{para}</w:tc>"
        )

    trs = []
    for ri, row in enumerate(rows):
        tcs = "".join(cell(row[c], widths[c], ri == 0) for c in range(ncol))
        trs.append(f'<w:tr><w:trPr><w:jc w:val="center"/></w:trPr>{tcs}</w:tr>')

    xml = (
        f'<w:tbl {nsdecls("w")}>'
        "<w:tblPr>"
        '<w:tblStyle w:val="af7"/>'
        f'<w:tblW w:w="{COL_TWIPS}" w:type="dxa"/>'
        '<w:jc w:val="center"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0"'
        ' w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        + "".join(trs)
        + "</w:tbl>"
    )
    return parse_xml(xml)


# --------------------------------------------------------------------------
# 3. テンプレートへ流し込む
# --------------------------------------------------------------------------

# テンプレートの本文要素の並び（2026 年版 oral テンプレートを解析した結果）。
IDX_TITLE = 0
IDX_ABSTRACT = 2
IDX_BODY_FIRST = 5      # 「はじめに」から
IDX_BODY_LAST = 80      # 「むすび」の後の空段落まで（説明用の本文はすべてここ）
IDX_ACK_TITLE = 81
IDX_REF_TITLE = 84
IDX_REF_FIRST = 85
IDX_REF_LAST = 89
IDX_FUTURE = 90         # 未来ビジョンの説明入りテキストボックス（任意欄なので外す）


def build_docx(blocks) -> None:
    shutil.copyfile(TEMPLATE, OUT_DOCX)
    doc = docx.Document(str(OUT_DOCX))
    body = doc.element.body
    children = list(body)

    # --- タイトル -----------------------------------------------------------
    title = next(t for k, t in blocks if k == "title")
    tp = children[IDX_TITLE]
    for r in tp.findall(qn("w:r")):
        # 図形（テキストボックス）を含む run は残す。文字だけの run は消す。
        if r.find(".//" + qn("w:drawing")) is None and r.find(".//" + qn("w:pict")) is None:
            if r.findall(qn("w:t")):
                tp.remove(r)
    tp.append(
        parse_xml(
            f'<w:r {nsdecls("w")}><w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(strip_inline(title))}</w:t></w:r>'
        )
    )

    # --- 概要 ---------------------------------------------------------------
    abstract = " ".join(strip_inline(t) for k, t in blocks if k == "abstract")
    ap = children[IDX_ABSTRACT]
    kept = 0
    for child in list(ap):
        tag = child.tag.split("}")[1]
        if tag == "pPr":
            continue
        if tag == "r" and kept < 2:
            kept += 1
            continue
        ap.remove(child)
    ap.append(
        parse_xml(
            f'<w:r {nsdecls("w")}><w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(abstract)}</w:t></w:r>'
        )
    )

    # --- 説明用の本文をすべて外す -------------------------------------------
    for el in children[IDX_BODY_FIRST:IDX_BODY_LAST + 1]:
        body.remove(el)

    # --- 本文を入れる（謝辞の直前へ） ---------------------------------------
    anchor = children[IDX_ACK_TITLE]
    new_elements = []
    pending_table_caption = None

    seq = [b for b in blocks if b[0] not in ("title", "abstract")]
    for idx, (kind, payload) in enumerate(seq):
        if kind == "h_ref":
            break
        if kind == "h1":
            # 章の最後には空行を入れる、というテンプレートの指定に合わせる
            if new_elements:
                new_elements.append(make_p(None, ""))
            new_elements.append(make_p(STYLE_ID["1 段落番号1"], strip_inline(payload)))
        elif kind == "h2":
            new_elements.append(
                make_p(STYLE_ID["1.1 段落番号2"], strip_inline(payload),
                       '<w:ind w:left="386" w:hanging="386"/>')
            )
        elif kind == "h3":
            new_elements.append(
                make_p(STYLE_ID["1.1.1段落番号3"], strip_inline(payload),
                       '<w:ind w:left="386" w:hanging="386"/>')
            )
        elif kind == "caption":
            cap = make_p(STYLE_ID["図表番号"], strip_inline(payload))
            nxt = seq[idx + 1][0] if idx + 1 < len(seq) else None
            if payload.startswith("表") and nxt == "table":
                # 表のキャプションは表の上に置く
                pending_table_caption = cap
            else:
                new_elements.append(cap)
        elif kind == "table":
            if pending_table_caption is not None:
                new_elements.append(pending_table_caption)
                pending_table_caption = None
            new_elements.append(make_table([[strip_inline(c) for c in r] for r in payload]))
            new_elements.append(make_p(None, ""))
        elif kind == "body":
            new_elements.append(make_p(None, strip_inline(payload)))

    # 最後の章のあとにも空行を 1 行置く（テンプレートの指定）
    new_elements.append(make_p(None, ""))

    for el in new_elements:
        anchor.addprevious(el)

    # --- 参考文献 -----------------------------------------------------------
    for el in children[IDX_REF_FIRST:IDX_REF_LAST + 1]:
        body.remove(el)
    ref_anchor = children[IDX_FUTURE]
    for kind, payload in blocks:
        if kind == "ref":
            ref_anchor.addprevious(make_p(STYLE_ID["参考文献"], strip_inline(payload)))

    # --- 未来ビジョン（任意欄）の説明を外す ---------------------------------
    body.remove(children[IDX_FUTURE])

    doc.save(str(OUT_DOCX))


# --------------------------------------------------------------------------
# 4. 貼付用マークダウン
# --------------------------------------------------------------------------

HOWTO = """<!-- 自動生成ファイル。編集しても次回の生成で上書きされる。
     内容の正本は paper/wiss2026_draft.md、生成は paper/build_wiss2026_docx.py -->

# WISS 2026 Word 貼付用（スタイル指定つき）

## 貼り付け手順

1. この作業は `paper/wiss2026.docx` が壊れていたときの保険である．通常はそちらを直接開く．
2. 貼り付け先は WISS テンプレートのコピーであり，原本 `WISS_Template_2026_oral.docx` は開いたまま書き換えない．
3. 貼り付けは必ず「テキストのみ保持」（Ctrl+Shift+V もしくは貼り付けオプションの A のアイコン）で行う．書式ごと貼るとテンプレートのスタイル定義が壊れる．
4. 貼り付けたあと，段落にカーソルを置き，スタイルウィンドウから【スタイル: 】に書かれた名前を選ぶ．
5. 章・節・項の番号と参考文献の番号は Word が自動で振る．本文には番号を打たない．
6. 章の最後には空行を 1 行入れる（テンプレートの指定）．
7. 図のキャプションは図の下，表のキャプションは表の上に置く．
8. 表の中の文字には文字スタイル「表中文字」を当てる．
9. 文体は「である」調，句読点は「，」「．」を使う．
10. 仕上げに，本文からの図表参照（「図 1 に示す」など）の番号がキャプションと合っているかを確認する．

---

"""


def build_paste_md(blocks) -> None:
    out = [HOWTO]
    out.append(f'【スタイル: WISS論文タイトル】\n{strip_inline(next(t for k, t in blocks if k == "title"))}\n')
    out.append("【スタイル: 著者】（テンプレート記入済み）\n丸山 礼華*† 栗原 一貴*\n")
    abstract = " ".join(strip_inline(t) for k, t in blocks if k == "abstract")
    out.append("【スタイル: 概要見出し】\n概要．\n")
    out.append(f"【スタイル: 概要本文】\n{abstract}\n")

    seq = [b for b in blocks if b[0] not in ("title", "abstract")]
    for kind, payload in seq:
        if kind == "h1":
            out.append(f"【スタイル: 1 段落番号1】（番号は自動）\n{strip_inline(payload)}\n")
        elif kind == "h2":
            out.append(f"【スタイル: 1.1 段落番号2】（番号は自動）\n{strip_inline(payload)}\n")
        elif kind == "h3":
            out.append(f"【スタイル: 1.1.1段落番号3】（番号は自動）\n{strip_inline(payload)}\n")
        elif kind == "caption":
            out.append(f"【スタイル: 図表番号】\n{strip_inline(payload)}\n")
        elif kind == "table":
            rows = [[strip_inline(c) for c in r] for r in payload]
            body = "\n".join(" | ".join(r) for r in rows)
            out.append(
                "【表：Word の表として作る／中の文字は文字スタイル「表中文字」】\n" + body + "\n"
            )
        elif kind == "body":
            out.append(f"【スタイル: 標準】\n{strip_inline(payload)}\n")
        elif kind == "h_ref":
            out.append("【スタイル: 謝辞，参考文献タイトル】\n参考文献\n")
        elif kind == "ref":
            out.append(f"【スタイル: 参考文献】（番号は自動）\n{strip_inline(payload)}\n")

    OUT_PASTE.write_text("\n".join(out), encoding="utf-8")


def prune_unused_media() -> tuple[int, int]:
    """説明用の図を消したことで参照されなくなった画像と OLE を捨てる。

    テンプレートの説明図は 4MB 近くある。段落を消しても中身は zip に残るので，
    document.xml から参照されていない media/ と embeddings/ だけを落とす。
    styles.xml や header/footer などの暗黙の関係は Target を見て必ず残す。
    """
    import zipfile

    with zipfile.ZipFile(OUT_DOCX) as z:
        items = {n: z.read(n) for n in z.namelist()}

    doc = items["word/document.xml"].decode("utf-8")
    used = set(re.findall(r'r:(?:embed|id|link|pict|dm|lo|qs|cs)="([^"]+)"', doc))
    # header/footer など、他のパーツが持つ関係は各自の .rels にあるので触らない
    other_media = set()
    for name, data in items.items():
        if name.endswith(".rels") and name != "word/_rels/document.xml.rels":
            for t in re.findall(r'Target="([^"]+)"', data.decode("utf-8")):
                if "media/" in t or "embeddings/" in t:
                    other_media.add(t.split("/")[-1])

    from lxml import etree as _et

    rels_name = "word/_rels/document.xml.rels"
    root = _et.fromstring(items[rels_name])
    drop_files: set[str] = set()
    for rel in list(root):
        rid = rel.get("Id")
        target = rel.get("Target") or ""
        is_asset = target.startswith("media/") or target.startswith("embeddings/")
        if is_asset and rid not in used and target.split("/")[-1] not in other_media:
            drop_files.add("word/" + target)
            root.remove(rel)
    items[rels_name] = _et.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    saved = sum(len(items[f]) for f in drop_files if f in items)
    with zipfile.ZipFile(OUT_DOCX, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in items.items():
            if name in drop_files:
                continue
            z.writestr(name, data)
    return len(drop_files), saved


def main() -> None:
    md = SRC_MD.read_text(encoding="utf-8")
    blocks = parse_markdown(md)
    build_docx(blocks)
    n, saved = prune_unused_media()
    print(f"pruned {n} unused media/ole files ({saved/1024/1024:.1f} MB)")
    build_paste_md(blocks)
    kinds: dict[str, int] = {}
    for k, _ in blocks:
        kinds[k] = kinds.get(k, 0) + 1
    print("blocks:", kinds)
    print("wrote:", OUT_DOCX)
    print("wrote:", OUT_PASTE)


if __name__ == "__main__":
    main()
