"""Draws BChat's glass status lights into bchat/assets/lights. Needs Pillow; only run it to change the design.

XChat's 7x7 icons are partly see-through at the top, so its white list shines through as the highlight,
and they get brighter toward the bottom, like light through a marble. A dark list has no white to show,
so these draw that look directly and are fully opaque. Each file is made for one exact pixel size, so no
display scale has to blur it.
"""
import colorsys
import math
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "bchat" / "assets" / "lights"
SIZES = (7, 9, 11, 12, 14, 18, 21)  # 7 logical px at 100, 125, 150, 175, 200, 250 and 300 % scale

# Hue in degrees, measured from the most vivid pixel of each XChat icon (assets/ulist-original)
HUES = {"op": 79, "voice": 46, "hop": 213, "red": 0, "purple": 300}


def smooth(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def hsv(h, s, v):
    return tuple(c * 255 for c in colorsys.hsv_to_rgb(h, s, v))


def orb(px, name, shine=0.92, ss=8):
    h = HUES[name] / 360
    deep, mid, bright, rim = hsv(h, 1.0, 0.50), hsv(h, 1.0, 0.78), hsv(h, 0.72, 1.0), hsv(h, 1.0, 0.30)
    size = px * ss
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    data = im.load()
    c = size / 2
    radius = size / 2 - ss * 0.2
    for j in range(size):
        y = (j + 0.5 - c) / radius
        for i in range(size):
            x = (i + 0.5 - c) / radius
            d = math.hypot(x, y)
            if d > 1:
                continue
            col = mix(deep, mid, smooth(-0.6, 0.15, y))
            col = mix(col, bright, smooth(0.05, 0.85, y))  # glow gathers at the bottom
            col = mix(col, rim, smooth(0.80, 1.0, d) * (1 - 0.55 * smooth(0.2, 0.9, y)))  # round edge, lighter below
            e = (x / 0.70) ** 2 + ((y + 0.42) / 0.44) ** 2  # pale dome with a crisp lower edge, fading at the top
            if e < 1:
                col = mix(col, (255, 255, 255), shine * smooth(1.0, 0.72, e) * (1.0 - 0.55 * smooth(-0.85, -0.05, y)))
            data[i, j] = (int(col[0]), int(col[1]), int(col[2]), 255)
    # premultiplied while shrinking, so the edge doesn't pick up black from the transparent corners
    return im.convert("RGBa").resize((px, px), Image.BOX).convert("RGBA")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name in HUES:
        for px in SIZES:
            orb(px, name).save(OUT / f"{name}-{px}.png")
    print("saved", len(HUES) * len(SIZES), "files to", OUT)
