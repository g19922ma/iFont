#!/usr/bin/env python3
# =========================================================================
# ifont: 4方式の描画器（experiment/transfer.js の忠実な移植）
#
#   実験ページと同じ絵を出すことを優先する。定数も乱数も JS と同一にする。
#     fade   … 不透明度 = s（gamma=1.0）
#     reveal … ストローク画素を決まった乱数順で塗る（seed "stroke-mask:字"、
#              しきい値 輝度128。mulberry32 + FNV-1a を JS と同じ式で移植）
#     blur   … ガウスぼかし半径 = 72px × (1−s)。CSS の blur(N px) は標準偏差 N
#              （2026-08-29 に Chrome で実測して確認。半分ではない）
#     wipe   … 字のインクがある範囲(bbox)の左から s の割合まで見せる
# =========================================================================
import os

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE_DIR = os.path.join(ROOT, "experiment", "base")

SIZE = 256
BLUR_MAX_PX = 72.0
INK_THRESHOLD = 128          # reveal / wipe 共通（transfer_config.js と同値）
SEED_PREFIX = "stroke-mask:"
FADE_GAMMA = 1.0


def _hash_seed(s):
    """JS の hashSeed()（FNV-1a 32bit）と同じ。"""
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _mulberry32(seed):
    a = seed & 0xFFFFFFFF

    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (1 | a)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) ^ t
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0
    return rnd


class Glyph:
    def __init__(self, ch):
        p = os.path.join(BASE_DIR, ch + ".png")
        im = Image.open(p).convert("L")
        if im.size != (SIZE, SIZE):
            im = im.resize((SIZE, SIZE), Image.LANCZOS)
        self.ch = ch
        self.img = im
        self.px = np.asarray(im)
        # 輝度 = 0.299R+0.587G+0.114B。base は灰色画像なので L と同じ。
        self.ink_mask = self.px <= INK_THRESHOLD

        # reveal 用の画素順（JS と同一の乱数・同一の Fisher–Yates）
        idx = [int(i) for i in np.flatnonzero(self.ink_mask.ravel())]
        rnd = _mulberry32(_hash_seed(SEED_PREFIX + ch))
        for i in range(len(idx) - 1, 0, -1):
            j = int(rnd() * (i + 1))
            idx[i], idx[j] = idx[j], idx[i]
        self.reveal_order = idx

        cols = np.where(self.ink_mask.any(axis=0))[0]
        self.x_min = int(cols[0]) if len(cols) else 0
        self.x_max = int(cols[-1]) + 1 if len(cols) else 0


_glyphs = {}


def glyph(ch):
    if ch not in _glyphs:
        _glyphs[ch] = Glyph(ch)
    return _glyphs[ch]


def draw(family, ch, s):
    """進み具合 s (0..1) の1コマを L 画像（256×256、白地）で返す。"""
    s = min(max(float(s), 0.0), 1.0)
    g = glyph(ch)
    if family == "fade":
        a = s ** FADE_GAMMA
        out = 255.0 - (255.0 - g.px.astype(np.float64)) * a
        return Image.fromarray(out.astype(np.uint8))
    if family == "reveal":
        n = round(len(g.reveal_order) * s)
        out = np.full(SIZE * SIZE, 255, dtype=np.uint8)
        out[g.reveal_order[:n]] = 0
        return Image.fromarray(out.reshape(SIZE, SIZE))
    if family == "blur":
        r = BLUR_MAX_PX * (1.0 - s)
        if r <= 0.01:
            return g.img.copy()
        return g.img.filter(ImageFilter.GaussianBlur(radius=r))
    if family == "wipe":
        w = int(round(g.x_min + (g.x_max - g.x_min) * s))
        out = np.full((SIZE, SIZE), 255, dtype=np.uint8)
        out[:, :w] = g.px[:, :w]
        return Image.fromarray(out)
    raise KeyError(family)
