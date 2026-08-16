"""字幕フレームの描画。

各文字は、その文字の音が流れる区間の中で、g（gmodel）が定めるスケジュールに従って
0→1 に fade で立ち上がる（時間ゲート提示）。読み終えた文字はそのまま表示され続ける。
音声と同じ時点で同じだけ「見えて」いくことを狙う、インクルーシブ字幕の中核描画である。
"""
import os
from PIL import Image, ImageDraw, ImageFont
from . import gmodel

BG = (16, 19, 26)
FG = (240, 243, 250)


def render_frames(chars, char_dur, out_dir, font_path,
                  fps=30, width=1280, height=360, tail=0.6):
    os.makedirs(out_dir, exist_ok=True)
    n = len(chars)
    total = n * char_dur
    total_frames = int(round((total + tail) * fps))

    # フォントサイズを字数に合わせて決める（横1列で収まるように）
    fontsize = 150
    font = ImageFont.truetype(font_path, fontsize)
    while _line_width(font, chars) > width * 0.9 and fontsize > 40:
        fontsize -= 6
        font = ImageFont.truetype(font_path, fontsize)

    widths = [_char_w(font, c) for c in chars]
    gap = int(fontsize * 0.06)
    line_w = sum(widths) + gap * (n - 1)
    x0 = (width - line_w) // 2
    asc, desc = font.getmetrics()
    y = (height - (asc + desc)) // 2

    paths = []
    for fi in range(total_frames):
        t = fi / fps
        img = Image.new("RGBA", (width, height), BG + (255,))
        draw = ImageDraw.Draw(img)
        x = x0
        for i, c in enumerate(chars):
            local = (t - i * char_dur) / char_dur
            if local <= 0:
                opacity = 0.0
            elif local >= 1:
                opacity = 1.0
            else:
                opacity = gmodel.reveal_opacity(c, local)
            a = int(255 * opacity)
            if a > 0:
                draw.text((x, y), c, font=font, fill=FG + (a,))
            x += widths[i] + gap
        p = os.path.join(out_dir, f"f{fi:05d}.png")
        img.convert("RGB").save(p)
        paths.append(p)
    return paths, total + tail


def render_frames_gated(segments, out_dir, font_path, fps=30,
                        width=1280, height=720, tail=0.6, label=None,
                        font_hint_path=None):
    """論文の実験と同じ「時間ゲート提示」の描画。

    横に文字を並べていく方式ではなく、画面中央の固定領域に1文字ずつ提示する。
    各文字は、その文字の音が流れる区間の中で g（gmodel）に従って 0→1 に鮮明化し、
    その区間の間だけ表示され、次の文字に入れ替わる。読み(sound)が表示字(char)と
    違うときは、下に小さく「→sound」を金色で添える(は→ワ 等の対応を示す)。

    segments: [{char, start, dur, sound}] のリスト(start/dur は秒)。
    """
    os.makedirs(out_dir, exist_ok=True)
    if not segments:
        raise ValueError("segments が空です。")
    total = max(s["start"] + s["dur"] for s in segments)
    total_frames = int(round((total + tail) * fps))

    font = ImageFont.truetype(font_path, int(height * 0.42))
    f_hint = ImageFont.truetype(font_hint_path or font_path, int(height * 0.06))
    f_label = ImageFont.truetype(font_hint_path or font_path, int(height * 0.045))
    cx, cy = width // 2, int(height * 0.46)

    def current(t):
        cur = segments[0]
        for s in segments:
            if t >= s["start"]:
                cur = s
            else:
                break
        return cur

    paths = []
    for fi in range(total_frames):
        t = fi / fps
        img = Image.new("RGBA", (width, height), BG + (255,))
        draw = ImageDraw.Draw(img)
        if label:
            draw.text((int(width * 0.03), int(height * 0.04)), label,
                      font=f_label, fill=(150, 156, 170, 255))
        s = current(t)
        # reveal=鮮明化にかける時間。dur(表示し続ける時間)と分けることで、
        # 長く伸ばす音(余韻)でも鮮明化はゆっくりになりすぎず、その後は保持できる。
        local = (t - s["start"]) / max(s.get("reveal", s["dur"]), 1e-3)
        if local >= 1:
            op = 1.0
        elif local <= 0:
            op = 0.0
        else:
            op = gmodel.reveal_opacity(s["char"], local)
        a = int(255 * op)
        if a > 0:
            # 文字は透明な層に描いてから背景へ重ねる。RGBA の画像へ直に描くと
            # 塗りのアルファがそのまま画素に書き込まれ、RGB へ変換した時点で
            # 背景と混ざらないまま不透明になってしまうため(鮮明化が効かない)。
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            bb = ld.textbbox((0, 0), s["char"], font=font)
            ld.text((cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]),
                    s["char"], font=font, fill=FG + (a,))
            snd = s.get("sound")
            if snd and snd != s["char"]:
                hb = ld.textbbox((0, 0), "→" + snd, font=f_hint)
                ld.text((cx - (hb[2] - hb[0]) / 2, int(height * 0.80)),
                        "→" + snd, font=f_hint, fill=(213, 179, 87, a))
            img = Image.alpha_composite(img, layer)
        img.convert("RGB").save(os.path.join(out_dir, f"f{fi:05d}.png"))
        paths.append(os.path.join(out_dir, f"f{fi:05d}.png"))
    return paths, total + tail


def _char_w(font, c):
    box = font.getbbox(c)
    return max(box[2] - box[0], int(font.size * 0.4))


def _line_width(font, chars):
    gap = int(font.size * 0.06)
    return sum(_char_w(font, c) for c in chars) + gap * (len(chars) - 1)
