#!/usr/bin/env python3
"""
転写検証実験の回答を、字ごとの「分かっていく曲線」にして眺める
==============================================================
計画書: project/実験計画書_転写検証.md の 7章(データの分析方法)

これは**本解析の雛形**である。下見の1〜2人ぶんを見るために作ったが、
本番でも入口(読み込み)と出口(表・図)はこのままで、途中の推定だけを
差し替えて使えるようにしてある。いまの版がやるのは「素の正答率を数えて並べる」
ところまでで、単調回帰・混合モデル・曲線の距離Eは**まだ入っていない**
(計画書 7.1・7.2 の手続きは本番データで足す)。

作るもの
--------
  <out>/accuracy_by_char_gate.csv   … 字 × 時点 の正答表(聴覚は打ち切りms、視覚は進み具合%)
  <out>/curve_<集団>.png            … 字ごとの識別率曲線
  <out>/summary.md                  … 全体のまとめ(操作チェック・まぎれ字・反応時間・混同)

入力
----
  1) GAS の取り出し口が返す JSON
       {"sheet":"transfer_trials","header":[...],"rows":[{列名:値,...},...]}
  2) スプレッドシートをそのまま保存した CSV(列名は上と同じ)
  3) 下見用の短縮 CSV(project/pilot_data/*.csv。列名は p,ti,tgt,resp,ok,... )
  どれを渡しても同じ形に正規化してから処理する。

使い方
------
  python3 experiment/tools/analyze_transfer.py \
      --in project/pilot_data/pilot_20260821_trials.csv \
      --out project/pilot_data/out \
      --label-map A=anon-cdgptgrg,B=anon-olcnwkzp

試し打ちの行について
--------------------
動作確認で作った行には `is_test` 列に真が入っている（参加者IDの頭が `curltest-` /
`uitest-` の回と、掲載前フラグ `pre_launch` が立っていたあいだの回）。
**既定では読み込んだ時点で外す。** 混ぜたいときだけ `--include-test` を付ける。
`is_test` 列そのものが無い入力（下見用の短縮CSVなど）は、全行が本番として扱われる。
"""
import argparse
import csv
import io
import json
import os
import sys
from collections import defaultdict, Counter

# 図はあると分かりやすいが、無い環境でも表とまとめは作れるようにする。
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    HAVE_PLT = True
except Exception:
    HAVE_PLT = False


# ---- 日本語が豆腐(□)にならないようにフォントを選ぶ --------------------------
def pick_jp_font():
    if not HAVE_PLT:
        return None
    for name in ["Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic",
                 "IPAexGothic", "Noto Sans CJK JP", "TakaoPGothic"]:
        try:
            path = font_manager.findfont(font_manager.FontProperties(family=name),
                                         fallback_to_default=False)
            if path and os.path.exists(path):
                return name
        except Exception:
            continue
    return None


# ---- 読み込みと正規化 --------------------------------------------------------
# 短縮CSVの列名 → 正式な列名。
SHORT = {"p": "participant_id", "ti": "trial_index", "tgt": "target_char",
         "resp": "response_char", "ok": "correct", "fam": "family",
         "gate": "gate_ms", "pct": "progress_pct", "fil": "is_filler",
         "chk": "check_kind", "rt": "rt_ms", "base": "base_anim_ms",
         "acts": "actual_s"}


def truthy(v):
    return str(v).strip().upper() in ("1", "TRUE", "T", "YES")


def num(v):
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load(path):
    """JSON でも CSV でも読んで、辞書の並びにそろえて返す。"""
    raw = io.open(path, encoding="utf-8").read()
    if raw.lstrip().startswith("{"):
        obj = json.loads(raw)
        rows = obj.get("rows", [])
        # rows が配列の配列なら columns で名前を付ける。
        if rows and isinstance(rows[0], list):
            cols = obj.get("columns") or obj.get("header")
            rows = [dict(zip(cols, r)) for r in rows]
    else:
        rows = list(csv.DictReader(io.StringIO(raw)))
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            d[SHORT.get(k, k)] = v
        out.append(d)
    return out


def load_id_list(path):
    """配布した設問ファイル（TSV）か対応表（CSV）から、作業者IDの一覧を読む。

    **本番の参加者は、必ずこの一覧のどれかのIDになる**（設問ごとに違うURLを
    配っているため）。研究者や指導教員の試し打ちは別のID（test01 / uitest- /
    anon- など）になるので、この一覧で絞れば自動的に外れる。
    """
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"エラー: {path} の文字コードが読めない")
    ids = set()
    for i, line in enumerate(text.replace("\r\n", "\n").split("\n")):
        if not line.strip() or i == 0:      # 1行目は見出し
            continue
        cell = line.split("\t")[0] if "\t" in line else line.split(",")[0]
        cell = cell.strip().strip('"')
        if cell:
            ids.add(cell)
    return ids


def drop_test_rows(rows, only_ids=None):
    """分析に使わない行を外す。戻り値は (残した行, 外した数)。

    ① `is_test` が真の行（動作確認）。`is_test` 列が無い入力は全行が本番として残る。
    ② `only_ids` を渡したときは、**その一覧に無い参加者IDの行**も外す。
       配布した設問ファイルのIDを渡すのが本来の使い方である（→ load_id_list）。
       ⚠ **本番の参加者が1人も残らないときは、URL に wid が渡っていない**
         恐れがある（参加者IDが anon- で始まる）。そのときは掲載側の設定を疑うこと。
    """
    kept = [r for r in rows if not truthy(r.get("is_test"))]
    if only_ids:
        kept = [r for r in kept if str(r.get("participant_id", "")) in only_ids]
    return kept, len(rows) - len(kept)


def normalize(rows, label_map):
    """分析で使う形に整える。集団は group 列、無ければ視覚の手がかりから推測する。"""
    for r in rows:
        pid = r.get("participant_id", "")
        r["participant_id"] = label_map.get(pid, pid)
        r["correct"] = truthy(r.get("correct"))
        # is_decoy は 2026-08-24 に足した新しい列名。is_filler は同じ意味の旧称なので、
        # どちらか片方でも立っていれば「偽のターゲット（解析から外す行）」とみなす。
        r["is_filler"] = truthy(r.get("is_filler")) or truthy(r.get("is_decoy"))
        r["check_kind"] = (r.get("check_kind") or "").strip()
        r["gate_ms"] = num(r.get("gate_ms"))
        r["progress_pct"] = num(r.get("progress_pct"))
        r["rt_ms"] = num(r.get("rt_ms"))
        r["base_anim_ms"] = num(r.get("base_anim_ms"))
        r["actual_s"] = num(r.get("actual_s"))
        r["family"] = (r.get("family") or "").strip()
        r["trial_index"] = num(r.get("trial_index"))
        if not r.get("group"):
            # 視覚は進み具合%か方式が入る。聴覚は打ち切りmsだけが入る。
            r["group"] = "視覚" if (r["progress_pct"] is not None or r["family"]) else "聴覚"
        # 提示量: 聴覚は ms、視覚は %。図と表ではこの列を横軸にする。
        #
        # ⚠ **視覚は「指定した水準」ではなく「実際に見えた進み具合」を使う。**
        #   実験1（v1）で先生が決めた方針である（project/実験計画書_1文字課題.md）:
        #     > 60Hz端末では1フレーム16.7msの量子化により低fracの水準が実効的に潰れ…
        #     > 記録済みの actual_ms を f(·) の入力とする。
        #     > **名目fracはあくまで割付水準の記録とする。**
        #
        #   画面は1秒に60回しか書き換わらないので、指定した進み具合ちょうどでは止まれない。
        #   たとえば基準アニメ300msで「17%」と指定しても、60Hzで実際に見えるのは 16.7% である。
        #   端末によっても変わる（60Hzは5.6%刻み、120Hzは2.8%刻み）ので、
        #   **名目値で束ねると、中身の違うものを同じ点として数えてしまう。**
        #   逆に実測値で並べれば、端末が混ざるほど横軸が細かく埋まる。
        #
        #   ⚠ **生成（q̂V⁻¹ の逆引き）も必ずこの実測の軸で行うこと。**
        #     名目で当てはめた曲線を逆引きすると、アニメの進み方がずれる。
        #
        #   actual_s は 0〜1 なので %（0〜100）に直してから使う。
        #   記録が無い古いデータのときだけ、名目値に落とす（そのことを警告する）。
        r["level_nominal"] = r["gate_ms"] if r["group"] in ("聴覚", "acal", "atest") else r["progress_pct"]
        if r["group"] in ("聴覚", "acal", "atest"):
            r["level"] = r["gate_ms"]
            r["level_source"] = "gate_ms"
        elif r["actual_s"] is not None:
            r["level"] = round(r["actual_s"] * 100, 2)
            r["level_source"] = "actual_s"
        else:
            r["level"] = r["progress_pct"]
            r["level_source"] = "progress_pct(代用)"
        r["mod"] = "聴覚" if r["group"] in ("聴覚", "acal", "atest") else "視覚"
    return rows


# ---- 集計 --------------------------------------------------------------------
def target_rows(rows):
    """ターゲット字の本番の問題だけ。まぐれ確認用の確認問題とまぎれ字は外す。"""
    return [r for r in rows if not r["is_filler"] and not r["check_kind"]]


def accuracy_table(rows):
    """(集団, 字, 提示量) → (正答数, 出題数)"""
    tab = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["level"] is None:
            continue
        k = (r["mod"], r["target_char"], r["level"])
        tab[k][1] += 1
        tab[k][0] += 1 if r["correct"] else 0
    return tab


def first_hit(levels, tab, mod, ch):
    """その字が「最初に当たった」提示量。曲線の立ち上がりの目安に使う。"""
    for lv in levels:
        n_ok, n = tab.get((mod, ch, lv), (0, 0))
        if n > 0 and n_ok > 0:
            return lv
    return None


def all_correct_from(levels, tab, mod, ch):
    """そこから上がすべて正解になった提示量。1人ぶんだと「分かった点」の目安になる。"""
    best = None
    for lv in reversed(levels):
        n_ok, n = tab.get((mod, ch, lv), (0, 0))
        if n == 0:
            continue
        if n_ok == n:
            best = lv
        else:
            break
    return best


# ---- 出力 --------------------------------------------------------------------
def write_table(path, tab, levels_by_mod):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["modality", "char", "level", "n_correct", "n_trials", "accuracy"])
        # level は視覚では**実際に見えた進み具合%**（actual_s×100）。名目値ではない。
        for (mod, ch, lv), (ok, n) in sorted(tab.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
            w.writerow([mod, ch, lv, ok, n, round(ok / n, 4) if n else ""])


def draw_curves(path, tab, mod, chars, levels, jp_font, title):
    if not HAVE_PLT:
        return False
    if jp_font:
        plt.rcParams["font.family"] = jp_font
    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=150)
    # 1人ぶんだと正答率が 0% と 100% しか取らず、線がぴったり重なって見えなくなる。
    # 字ごとに縦へわずかにずらし、線の種類も変えて、8本すべてを見えるようにする。
    # ずらし幅は最大 ±1.4 ポイントで、読み取りに影響しない大きさに収めてある。
    styles = ["-", "--", "-.", ":"]
    span = 2.8
    for i, ch in enumerate(chars):
        xs, ys = [], []
        for lv in levels:
            ok, n = tab.get((mod, ch, lv), (0, 0))
            if n:
                xs.append(lv)
                ys.append(ok / n)
        if xs:
            off = (i - (len(chars) - 1) / 2) * (span / max(1, len(chars) - 1))
            ax.plot(xs, [y * 100 + off for y in ys], marker="o", markersize=4,
                    linewidth=1.4, linestyle=styles[i % len(styles)], label=ch)
    ax.set_xlabel("打ち切り時刻（ミリ秒）" if mod == "聴覚" else "進み具合（％）")
    ax.set_ylabel("正答率（％）")
    ax.set_ylim(-8, 108)
    ax.set_title(title + "（線が重ならないよう字ごとに縦へわずかにずらしてある）", fontsize=10)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(ncol=4, fontsize=9, frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="dump JSON か CSV")
    ap.add_argument("--out", default="analysis_out", help="出力先ディレクトリ")
    ap.add_argument("--label-map", default="", help='短縮IDの読み替え。"A=anon-xxx,B=anon-yyy"')
    ap.add_argument("--only-ids", default=None, metavar="設問ファイル か 対応表",
                    help="配布した設問ファイル(TSV)か対応表(CSV)を指定すると、"
                         "**その一覧にある作業者IDの行だけ**を残す。"
                         "研究者や指導教員の試し打ちは別のIDになるので自動的に外れる。")
    ap.add_argument("--include-test", action="store_true",
                    help="動作確認の行（is_test）も混ぜて集計する（既定は外す）")
    args = ap.parse_args()

    label_map = {}
    for pair in filter(None, args.label_map.split(",")):
        k, _, v = pair.partition("=")
        label_map[k.strip()] = v.strip()

    raw_rows = load(args.inp)
    dropped = 0
    only_ids = load_id_list(args.only_ids) if args.only_ids else None
    if only_ids:
        print(f"  配布した作業者ID {len(only_ids)} 件だけを残します（{args.only_ids}）")
    if not args.include_test:
        raw_rows, dropped = drop_test_rows(raw_rows, only_ids)
        if dropped:
            print(f"  分析に使わない行 {dropped} 件を外しました（混ぜるなら --include-test）")
        if only_ids and not raw_rows:
            print("  ⚠ 本番の参加者が1行も残りませんでした。"
                  "URL に wid が渡っていない恐れがあります（参加者IDが anon- になる）。")
    elif any(truthy(r.get("is_test")) for r in raw_rows):
        print("  ⚠ --include-test なので、試し打ちの行も集計に入っています")
    rows = normalize(raw_rows, label_map)
    os.makedirs(args.out, exist_ok=True)
    jp_font = pick_jp_font()

    tgt = target_rows(rows)
    tab = accuracy_table(tgt)

    levels_by_mod = {}
    chars_by_mod = {}
    for mod in ("聴覚", "視覚"):
        lv = sorted({r["level"] for r in tgt if r["mod"] == mod and r["level"] is not None})
        ch = sorted({r["target_char"] for r in tgt if r["mod"] == mod})
        if lv:
            levels_by_mod[mod] = lv
            chars_by_mod[mod] = ch

    write_table(os.path.join(args.out, "accuracy_by_char_gate.csv"), tab, levels_by_mod)

    made = []
    for mod, levels in levels_by_mod.items():
        f = os.path.join(args.out, f"curve_{'audio' if mod == '聴覚' else 'visual'}.png")
        if draw_curves(f, tab, mod, chars_by_mod[mod], levels, jp_font,
                       f"字ごとの識別率曲線（{mod}）"):
            made.append(f)

    # ---- まとめ ----
    L = []
    L.append("# 転写検証 集計結果\n")
    L.append(f"- 入力: `{args.inp}`")
    L.append(f"- 全レコード {len(rows)} 行 ／ ターゲットの本番の問題 {len(tgt)} 行")
    # 「何を数えたか」を必ず残す。動作確認の行が混ざったまま集計した表と、
    # 外して集計した表を、あとから取り違えないため。
    if args.include_test:
        L.append("- 試し打ちの行（`is_test`）も**混ぜて**集計している（`--include-test`）")
    else:
        L.append(f"- 試し打ちの行（`is_test`）{dropped} 件を外して集計している")
    L.append("")

    for pid in sorted({r["participant_id"] for r in rows}):
        sub = [r for r in rows if r["participant_id"] == pid]
        subt = [r for r in sub if not r["is_filler"] and not r["check_kind"]]
        fil = [r for r in sub if r["is_filler"]]
        full = [r for r in sub if r["check_kind"] == "full"]
        floor = [r for r in sub if r["check_kind"] == "floor"]
        rts = sorted(r["rt_ms"] for r in sub if r["rt_ms"] is not None)
        med = rts[len(rts) // 2] if rts else None
        L.append(f"## {pid}（{sub[0]['mod']}・{len(sub)}問）\n")
        L.append("| 区分 | 問題数 | 正答率 |")
        L.append("|---|---|---|")
        for name, g in [("ターゲット（本番）", subt), ("まぎれ字", fil),
                        ("確認問題A 全部見せ・全部聞かせ", full), ("確認問題C 最小の提示", floor)]:
            if g:
                L.append(f"| {name} | {len(g)} | {sum(1 for r in g if r['correct']) / len(g) * 100:.0f}% |")
        if med is not None:
            L.append(f"\n反応時間の中央値 {med:.0f} ミリ秒"
                     f"（最短 {rts[0]:.0f} ／ 最長 {rts[-1]:.0f}）\n")

    for mod, levels in levels_by_mod.items():
        unit = "ミリ秒" if mod == "聴覚" else "％"
        L.append(f"\n## 字 × 提示量の正答（{mod}）\n")
        L.append("| 字 | " + " | ".join(f"{int(x)}{unit}" for x in levels)
                 + " | 最初に当たった | ここから上は全部正解 |")
        L.append("|---" * (len(levels) + 3) + "|")
        for ch in chars_by_mod[mod]:
            cells = []
            for lv in levels:
                ok, n = tab.get((mod, ch, lv), (0, 0))
                cells.append("—" if n == 0 else ("○" if ok == n else ("×" if ok == 0 else f"{ok}/{n}")))
            fh = first_hit(levels, tab, mod, ch)
            ac = all_correct_from(levels, tab, mod, ch)
            L.append(f"| {ch} | " + " | ".join(cells) + " | "
                     + (f"{int(fh)}{unit}" if fh is not None else "—") + " | "
                     + (f"{int(ac)}{unit}〜" if ac is not None else "—") + " |")
        L.append("\n○=全問正解 ／ ×=全問誤答 ／ —=出題なし\n")

    # 間違え方（混同）。1人ぶんでも「何と取り違えたか」は見ておく価値がある。
    conf = Counter((r["target_char"], r["response_char"]) for r in tgt if not r["correct"])
    if conf:
        L.append("\n## 間違え方（ターゲットの本番の問題）\n")
        L.append("| 正解 | 答えた字 | 回数 |")
        L.append("|---|---|---|")
        for (a, b), c in conf.most_common(20):
            L.append(f"| {a} | {b} | {c} |")

    if made:
        L.append("\n## 図\n")
        for f in made:
            L.append(f"- `{os.path.basename(f)}`")
    else:
        L.append("\n（matplotlib が無いため図は作っていない）")

    io.open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"書き出し: {args.out}/accuracy_by_char_gate.csv, summary.md"
          + (", " + ", ".join(os.path.basename(f) for f in made) if made else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
