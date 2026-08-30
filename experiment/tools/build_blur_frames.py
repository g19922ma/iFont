#!/usr/bin/env python3
# =========================================================================
# ぼかし済みの絵を先に作っておく（WebKit 対策）
#
#   ■ なぜ要るか
#   iOS の全ブラウザ・一部の WebView・古い macOS Safari では、canvas の中で使う
#   ctx.filter が黙って無視される。ぼかし解除方式の絵がまったくぼけないため、
#   いまは canvasFilterWorks() で実測して**その端末をお断りしている**
#   （commit de18d5a08）。測定では 325 人中 45 人（13.8%）が該当した。
#
#   断るかわりに、**ぼかした絵をあらかじめ PNG にして配れば**、filter が
#   効かない端末でも同じ絵を出せる。このスクリプトがその PNG を作る。
#
#   ■ 半径をとびとびにする理由
#   進み具合 s は表の 19 コマを線形につないだ連続値なので、半径も連続に動く。
#   すべての半径ぶん作ることはできないので、**とびとびの階段（ladder）**を用意し、
#   画面側はいちばん近い段を選ぶ。段の間隔は、ぼけが弱いところほど細かくする
#   （r=1px と r=1.5px の違いは見えるが、r=60px と r=62px の違いは見えない）。
#
#   ■ CSS と同じぼかしにする
#   canvas / CSS の blur(N px) は「**標準偏差 N** のガウスぼかし」である
#   （CSS Filter Effects: blur(<length>) の引数がそのまま標準偏差）。
#   PIL の GaussianBlur(radius=…) もこの標準偏差そのものなので、**N をそのまま渡す**。
#
#   ⚠ 半分（N/2）ではない。box-shadow のぼかし幅は 2σ なので混同しやすい。
#     2026-08-29 に N/2 で作って blur_compare.html にかけたところ、
#     平均のずれ 18.4／最大 100（256階調中）で不合格になった。
#     Chrome で段差をぼかして実測すると σ ≒ N（N=2,4 で比 1.00〜1.02）だった。
#   一致するかどうかは experiment/tools/blur_compare.html で実際に見比べる。
#
#   出力: experiment/blur_frames/<字>/<段番号3桁>.png
#         experiment/blur_frames/manifest.json
# =========================================================================
import json
import os
import shutil
import sys

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_DIR = os.path.join(ROOT, "experiment", "base")
OUT_DIR = os.path.join(ROOT, "experiment", "blur_frames")

# transfer_config.js の visual.size_px / families.blur.max_radius_px と合わせること。
SIZE_PX = 256
MAX_RADIUS_PX = 72.0

# 実験Cで使う8字（重点測定した字）。
CHARS = ["あ", "か", "が", "し", "つ", "ぱ", "ま", "ら"]

# 半径の階段。(ここまで, 刻み) の順に読む。0 は「ぼかさない」で必ず入れる。
LADDER = [(2.0, 0.25), (6.0, 0.5), (16.0, 1.0), (40.0, 2.0), (MAX_RADIUS_PX, 4.0)]


def build_ladder():
    radii = [0.0]
    lo = 0.0
    for hi, step in LADDER:
        r = lo + step
        while r <= hi + 1e-9:
            radii.append(round(r, 4))
            r += step
        lo = hi
    if abs(radii[-1] - MAX_RADIUS_PX) > 1e-6:
        radii.append(MAX_RADIUS_PX)
    return radii


def main():
    radii = build_ladder()
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    total_bytes = 0
    per_char = {}
    for ch in CHARS:
        src = os.path.join(BASE_DIR, ch + ".png")
        if not os.path.exists(src):
            sys.exit("元の絵が無い: " + src)
        im = Image.open(src).convert("RGB")
        if im.size != (SIZE_PX, SIZE_PX):
            im = im.resize((SIZE_PX, SIZE_PX), Image.LANCZOS)

        d = os.path.join(OUT_DIR, ch)
        os.makedirs(d)
        n_bytes = 0
        for i, r in enumerate(radii):
            # blur(N px) は標準偏差 N のガウスぼかし（半分にしない）。
            out = im if r <= 0.01 else im.filter(ImageFilter.GaussianBlur(radius=r))
            p = os.path.join(d, "%03d.png" % i)
            out.save(p, optimize=True)
            n_bytes += os.path.getsize(p)
        per_char[ch] = n_bytes
        total_bytes += n_bytes

    manifest = {
        "generated_by": "experiment/tools/build_blur_frames.py",
        "note": "canvas の ctx.filter が効かない端末むけ。blur(N px) = 標準偏差 N/2 のガウスぼかし。",
        "size_px": SIZE_PX,
        "max_radius_px": MAX_RADIUS_PX,
        "chars": CHARS,
        "radii": radii,                       # 段番号 → 半径px
        "path": "blur_frames/{char}/{index}.png",
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print("段の数: %d（半径 0〜%.0f px）" % (len(radii), MAX_RADIUS_PX))
    print("字の数: %d" % len(CHARS))
    print("枚数  : %d" % (len(radii) * len(CHARS)))
    print()
    print("1人がダウンロードする量（自分の字のぶんだけ）:")
    for ch in CHARS:
        print("   %s  %6.0f KB" % (ch, per_char[ch] / 1024))
    print()
    print("サーバーに置く合計: %.1f MB" % (total_bytes / 1024 / 1024))
    print()
    print("いちばん粗いところの段の間隔: %.1f px（半径 %.0f 付近）"
          % (LADDER[-1][1], MAX_RADIUS_PX))


if __name__ == "__main__":
    main()
