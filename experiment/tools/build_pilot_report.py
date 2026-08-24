#!/usr/bin/env python3
"""
自己テストの結果を1枚にまとめる（記録 → 図と表 → 分かったこと）
================================================================
2026-08-25 作成。

**なぜ作るのか。** 丸山さんが本番URLで聴覚を最後まで・視覚を途中まで通した。
その記録から「掲載してよいか」を判断するのに要る数字を、**1枚のHTMLに集約する**。
CSVを開き直したり、複数のページを行き来したりしなくて済むようにする。

⚠ **`correct` 列は "TRUE"/"FALSE" の文字列**である（大文字）。
  Python で真偽に直すときは大文字小文字を揃えること。
  2026-08-25 に、ここを取り違えて「全問不正解」と誤って報告した。

入力
  Firestore から書き出した transfer_trials.csv
    python3 experiment/tools/export_transfer_firestore.py --out <folder> --include-test

出力
  experiment/tools/pilot_report_20260825.html

使い方
  python3 experiment/tools/build_pilot_report.py --in <folder>/transfer_trials.csv
"""
import argparse
import collections
import csv
import html
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pilot_report_20260825.html")

# 群A′の水準（transfer_config.js の visual.progress_pct_levels と、参加者ごとのずらし）
LEVELS_BASE = [1, 3.25, 5.5, 20, 100]
FAMILY_JA = {"fade": "うすい→濃い", "reveal": "点が増える",
             "blur": "ぼやけ→はっきり", "wipe": "端から現れる"}


def is_ok(r):
    """⚠ correct 列は "TRUE"/"FALSE" の文字列。大文字小文字を揃えて判定する。"""
    return str(r.get("correct", "")).strip().upper() == "TRUE"


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def curve(rows, key):
    """key（gate_ms か progress_pct）ごとの (正答数, 問題数)。"""
    agg = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        v = num(r.get(key))
        if v is None:
            continue
        a = agg[v]
        a[1] += 1
        a[0] += 1 if is_ok(r) else 0
    return dict(sorted(agg.items()))


def svg_curve(data, unit, width=560, height=210, floor=None):
    """正答率の折れ線。点の大きさで問題数を表す（少ない点を過信しないため）。"""
    if not data:
        return "<p>データなし</p>"
    xs = list(data)
    x0, x1 = min(xs), max(xs)
    pad_l, pad_b, pad_t, pad_r = 44, 30, 14, 14
    W, H = width - pad_l - pad_r, height - pad_t - pad_b

    def px(v):
        if x1 == x0:
            return pad_l + W / 2
        return pad_l + (v - x0) / (x1 - x0) * W

    def py(p):
        return pad_t + (1 - p) * H
    pts, circles = [], []
    for v, (c, n) in data.items():
        p = c / n
        X, Y = px(v), py(p)
        pts.append(f"{X:.1f},{Y:.1f}")
        rr = 2.5 + min(4.5, n * 0.5)
        circles.append(
            f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{rr:.1f}" fill="#2E7D8F">'
            f'<title>{v}{unit} … {c}/{n} 問（{p*100:.0f}%）</title></circle>')
    grid = "".join(
        f'<line x1="{pad_l}" y1="{py(g):.1f}" x2="{pad_l+W}" y2="{py(g):.1f}" '
        f'stroke="#e6e9f0"/><text x="{pad_l-6}" y="{py(g)+4:.1f}" font-size="10" '
        f'fill="#8a90a0" text-anchor="end">{int(g*100)}%</text>'
        for g in (0, .25, .5, .75, 1))
    fl = ""
    if floor is not None:
        fl = (f'<line x1="{pad_l}" y1="{py(floor):.1f}" x2="{pad_l+W}" y2="{py(floor):.1f}" '
              f'stroke="#c7743f" stroke-dasharray="4 3"/>'
              f'<text x="{pad_l+W}" y="{py(floor)-4:.1f}" font-size="9.5" fill="#c7743f" '
              f'text-anchor="end">当て推量の水準 {floor*100:.1f}%</text>')
    xticks = "".join(
        f'<text x="{px(v):.1f}" y="{pad_t+H+14}" font-size="9.5" fill="#8a90a0" '
        f'text-anchor="middle">{v:g}</text>' for v in xs)
    return (f'<svg viewBox="0 0 {width} {height}" style="width:100%;max-width:{width}px">'
            f'{grid}{fl}<polyline points="{" ".join(pts)}" fill="none" stroke="#2E7D8F" '
            f'stroke-width="1.8"/>{"".join(circles)}{xticks}'
            f'<text x="{pad_l+W/2}" y="{height-2}" font-size="10" fill="#59606e" '
            f'text-anchor="middle">{unit}</text></svg>')


def table(head, rows_):
    return ('<table><tr>' + "".join(f"<th>{h}</th>" for h in head) + '</tr>'
            + "".join('<tr>' + "".join(f"<td>{c}</td>" for c in r) + '</tr>' for r in rows_)
            + '</table>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="transfer_trials.csv")
    ap.add_argument("--who", default="test-qurihara", help="参加者IDの先頭")
    args = ap.parse_args()
    if not os.path.exists(args.src):
        sys.exit(f"{args.src} がありません")
    R = list(csv.DictReader(open(args.src, encoding="utf-8")))
    mine = [r for r in R if str(r.get("participant_id", "")).startswith(args.who)]
    real = [r for r in mine if r.get("target_char") not in (None, "", "-")]
    ac = [r for r in real if r.get("group") == "acal"]
    ap_ = [r for r in real if r.get("group") == "aprime"]
    print(f"  聴覚 {len(ac)}問 / 視覚 {len(ap_)}問")

    a_curve = curve(ac, "gate_ms")
    v_curve = curve(ap_, "progress_pct")

    # 方式 × 進み具合（視覚）
    fam = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in ap_:
        p = num(r.get("progress_pct"))
        if p is None:
            continue
        a = fam[r.get("family", "?")][p]
        a[1] += 1
        a[0] += 1 if is_ok(r) else 0
    pcts = sorted({p for f in fam.values() for p in f})

    def cell(f, p):
        c, n = fam[f].get(p, [0, 0])
        if not n:
            return '<td style="color:#c2c7d0">—</td>'
        cls = ' style="background:#e6f4ea;font-weight:700"' if n and c == n else ""
        return f'<td{cls}>{c}/{n}</td>'

    fam_rows = [[FAMILY_JA.get(f, f)] + [cell(f, p) for p in pcts] for f in sorted(fam)]
    fam_tbl = ('<table><tr><th>方式</th>'
               + "".join(f"<th>{p:g}%</th>" for p in pcts) + '</tr>'
               + "".join('<tr><td class="l">' + r[0] + '</td>' + "".join(r[1:]) + '</tr>'
                         for r in fam_rows) + '</table>')

    rt = [num(r.get("rt_ms")) for r in real if num(r.get("rt_ms"))]
    a_rt = [num(r.get("rt_ms")) for r in ac if num(r.get("rt_ms"))]
    v_rt = [num(r.get("rt_ms")) for r in ap_ if num(r.get("rt_ms"))]

    thin = [r for r in ap_ if (num(r.get("progress_pct")) or 0) <= 10]
    thin_ok = sum(1 for r in thin if is_ok(r))

    body = f"""<!doctype html><meta charset="utf-8">
<title>自己テストの結果（2026-08-25）</title>
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:16px;background:#faf9f6;
     color:#1b2030;max-width:880px;line-height:1.75}}
h1{{font-size:21px;margin:0 0 4px}}
h2{{font-size:17px;margin:30px 0 8px;padding-bottom:5px;border-bottom:2px solid #dde1ea}}
h3{{font-size:14.5px;margin:18px 0 6px;color:#2b3a52}}
p,li{{font-size:14px}}
table{{border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{border:1px solid #dde1ea;padding:5px 10px;background:#fff;text-align:center}}
th{{background:#f2f4f8}}
td.l{{text-align:left}}
.box{{background:#fff;border:1px solid #dde1ea;border-radius:8px;padding:12px 16px;margin:12px 0;
     font-size:13.5px}}
.good{{background:#f1f9f3;border-color:#a8d3b5}}
.bad{{background:#fff8f3;border-color:#f0c4a8}}
.hl{{background:#fff3bf;padding:0 3px;border-radius:3px}}
.k{{color:#8a90a0;font-size:12.5px}}
</style>

<h1>自己テストの結果（2026-08-25）</h1>
<p class="k">丸山さんが本番URLで、聴覚を最後まで・視覚を途中まで通した記録の分析です。
記録は <code>pre_launch: true</code> なので試し打ち扱いで、本番データには混ざりません。</p>

<div class="box bad">
<b class="hl">結論を先に。掲載の前に視覚の水準を直す必要があります。</b>
聴覚はきれいな曲線が出ていて、このまま掲載できます。視覚には次の2つの穴があります。
<ol>
<li><b>7%と20%のあいだに水準が1つも無い。</b> 曲線が立ち上がるのはちょうどそこなので、
    いまの配置では**立ち上がりを1点も測れません**。</li>
<li><b>「ぼやけ→はっきり」だけ床がありません。</b> 最大ぼかし（24px）でも読めてしまい、
    いちばん薄い条件で {fam['blur'].get(min(pcts) if pcts else 0,[0,0])[0]}/{fam['blur'].get(min(pcts) if pcts else 0,[0,1])[1]} 正解でした。
    床が無いと曲線を当てはめられません。</li>
</ol>
</div>

<h2>1. 聴覚（群Acal）— <span style="color:#2f7d4f">問題なし</span></h2>
<p>{len(ac)}問・正答 {sum(map(is_ok, ac))}問（{sum(map(is_ok, ac))/max(1,len(ac))*100:.0f}%）。
所要は記録された反応時間の合計で約 {sum(a_rt)/1000/60:.1f} 分（画面の表示は242秒）。</p>
{svg_curve(a_curve, "打ち切り時刻 ms", floor=1/68)}
<p>10ms で {a_curve.get(10.0,[0,1])[0]}/{a_curve.get(10.0,[0,1])[1]}（当て推量に近い）から、
40ms 以降はおおむね当たるところまで上がっています。<b>床と天井の両方があり、
そのあいだが滑らかに埋まっている</b>ので、S字を当てはめられます。これが欲しい形です。</p>

<h2>2. 視覚（群A′）— <span style="color:#9a3412">水準の配置に穴</span></h2>
<p>{len(ap_)}問・正答 {sum(map(is_ok, ap_))}問（{sum(map(is_ok, ap_))/max(1,len(ap_))*100:.0f}%）。
途中までなので数は少なく、以下は<b>傾向を見るためのもの</b>です。</p>
{svg_curve(v_curve, "進み具合 %", floor=1/68)}

<h3>方式ごとに分けると、問題がはっきりします</h3>
{fam_tbl}
<p class="k">緑は全問正解。「—」はその組合せが出なかったところ。</p>

<div class="box bad">
<b>「ぼやけ→はっきり」だけが薄い側で当たっています。</b>
ぼかしの半径は「最大 24px ×（1−進み具合）」なので、進み具合 1.75% ではほぼ最大のぼかしのはず。
それで読めるということは、<b>24px では字が消えていない</b>ということです。<br>
他の3方式は薄い側で全滅しており、<b>同じ「進み具合1.75%」でも方式によって難しさが桁違い</b>です。
方式ごとに曲線を測る設計なのでそれ自体は想定内ですが、
<b>blur は床（当て推量の水準）に一度も届いていない</b>ため、
その曲線の下half を推定できず、生成に使う逆引きが定義できません。
</div>

<h2>3. なぜ「何も見えない問題」が多いのか</h2>
<p>水準は <b>{", ".join(str(v) for v in LEVELS_BASE)}%</b> の5つで、参加者ごとに下3つが
0.75%ずつずれます。<b>1人が担当するのは3水準</b>で、選び方は
<code>[0,1,3]</code> を字ごとに回転させるので、<b>平均して3問中1.8問が薄い側（1〜7%）</b>
に当たります。今回の実測でも
<b>{len(thin)}/{len(ap_)}問（{len(thin)/max(1,len(ap_))*100:.0f}%）が10%以下</b>で、
そのうち正解は {thin_ok}問だけでした。</p>
<p>これは「見え始めるところを密に測る」というねらい（先生のパイロットで13%以上が
天井に張り付いたため薄い側へ寄せた）の裏返しですが、
<b>寄せすぎて全部が床に落ち、肝心の立ち上がりを跨いでしまっています。</b></p>

<h2>3.5 根本原因 — 水準を決めた元データは「アニメ600ms」のものだった</h2>
<div class="box bad">
<b class="hl">2026-08-24 に、逆向きの変更を2つ同時に入れてしまっていました。</b>
<ol>
<li><b>基準アニメを 600ms → 300ms に半減</b>（群Bの対照条件が構造的に不利だったため）</li>
<li><b>提示水準を薄い側へ寄せる</b>（先生のパイロットで13%以上が天井に張り付いたため）</li>
</ol>
ところが<b>②の根拠になった先生のパイロットは 600ms で取ったもの</b>です
（記録の base_anim_ms は 600 と 1000）。①で見ている時間が半分になれば同じ進み具合でも
格段に難しくなるので、<b>水準は上へ動かすべきところを、下へ動かしていました。</b>
</div>

<table>
<tr><th>進み具合</th><th>先生 600ms</th><th>丸山 300ms（ぼかし除く）</th></tr>
<tr><td>3% / 1.75%</td><td><b>61%</b></td><td><b>0%</b></td></tr>
<tr><td>6% / 6.25%</td><td><b>75%</b></td><td><b>0%</b></td></tr>
<tr><td>13%</td><td>86%</td><td class="k">測っていない</td></tr>
<tr><td>20〜22%</td><td>93%</td><td>67%</td></tr>
<tr><td>100%</td><td>97%</td><td>100%</td></tr>
</table>
<p><b>しきい値が「3%未満」から「6〜20%のどこか」へ動いています。</b>
いまの水準 <code>[1, 3.25, 5.5, 20, 100]</code> は、そのしきい値の<b>下と上に離れて置かれていて、
またいでしまっています</b>。</p>
<p class="k">※ 丸山さんのぼかし除きは18問と少ないので、値そのものより
「6.25%以下は0/11、20%以上は6/7」という向きを見てください。</p>

<h2>4. 直しかたの案</h2>
<div class="box">
<h3>案1: 300ms に合わせて水準を置き直す（推奨）</h3>
<p>いまの <code>[1, 3.25, 5.5, 20, 100]</code> を、<b>床・立ち上がり・天井の3つが揃うよう</b>
置き直します。実測から、床は6%以下、立ち上がりは6〜25%あたりです。案:</p>
<p style="font-size:16px;text-align:center"><b><code>[3, 6, 9, 12, 16, 22, 35, 100]</code></b>（8水準）</p>
<table>
<tr><th>区分</th><th>水準</th><th>ねらい</th></tr>
<tr><td>床</td><td>3・6%</td><td class="l">当て推量に近い水準を取る（実測 0/11）</td></tr>
<tr><td>立ち上がり</td><td>9・12・16・22%</td><td class="l"><b>いま1点も無い帯。ここが本体</b></td></tr>
<tr><td>天井</td><td>35・100%</td><td class="l">上端を押さえる</td></tr>
</table>
<p><b>8水準は既に対応済みです</b>— <code>assignment.point_subsets</code> に
<code>"8": [0,3,5]</code> があるので、設定を差し替えるだけで1人3水準の配り方はそのまま動きます。
HANDOFF の「視覚の水準を5→8に（1人3水準・集団で8）」という積み残しとも一致します。</p>

<h3>案2: 「ぼやけ」の最大ぼかしを強くする</h3>
<p><code>visual.families.blur.max_radius_px</code> を <b>24 → 40〜56</b> に上げ、
進み具合0%で字が判別できない状態にする。<b>案1と両方やる必要があります</b>
（案1だけでは blur の床が無いままです）。<br>
ぼかしは<b>600msでも300msでも簡単</b>でした（先生 3%で8/9、丸山 1.75%で4/4）。
つまりアニメの長さの問題ではなく、<b>最大ぼかし24pxが弱いこと自体</b>が原因です。<br>
<span class="k">※ 上げすぎると今度は立ち上がりが上に寄るので、上げたあとに
もう一度自分で通して確かめること。</span></p>

<h3>やってはいけないこと</h3>
<p><b>結果を見てから本命8字を変えないこと。</b>変えるのは水準とぼかしの強さだけにし、
<b>変えたことと理由を計画書に書き残す</b>（データを取る前の変更なので問題ありません）。</p>
</div>

<h2>5. その他に気づいたこと</h2>
<ul>
<li><b>参加者IDに記号が混ざっていました</b>（<code>test-qurihara`|</code>）。
    URLをコピーしたときにバッククォートが入ったものです。
    <b>先生に渡すURLは、記号が混ざらない形で書いて渡してください。</b></li>
<li><b>所要の見込みが実測とずれています。</b> 掲載文は聴覚 約7.5分ですが、実測は約4分でした。
    研究者本人なので一般の方はもう少しかかりますが、見込みは多めです。
    謝礼115円は「時給900円×7.5分」で決めた額なので、実際が4〜6分なら時給1,100〜1,700円相当になります。</li>
<li>反応時間の中央値は聴覚 {statistics.median(a_rt)/1000:.1f}秒 ／ 視覚 {statistics.median(v_rt)/1000 if v_rt else 0:.1f}秒でした。</li>
</ul>

<h2>6. 実際の見た目を確かめるページ</h2>
<p><code>experiment/tools/visual_trial_list.html</code> に、
<b>参加者が実際に見る絵と同じ描画コード</b>で1人ぶん70問を並べてあります。
水準を変えたあとは、そちらを作り直して目で確かめてください。</p>
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  → {OUT}")


if __name__ == "__main__":
    main()
