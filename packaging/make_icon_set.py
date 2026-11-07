"""Makes a transparent icon set (16-1024 px PNGs + BChat.ico) from one transparent master picture.

Usage: python packaging/make_icon_set.py <master.png> <out_dir>
Trims empty space, centres the logo on a square with a small margin, and scales down with good quality.
"""
import sys
from pathlib import Path

from PIL import Image

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO = (16, 24, 32, 48, 64, 128, 256)
MARGIN = 0.03   # of the side, so the outline never touches the edge


def square(src: Path) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    im = im.crop(im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox())
    side = round(max(im.size) * (1 + 2 * MARGIN))
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return sq


def scaled(im: Image.Image, s: int) -> Image.Image:
    return im.convert("RGBa").resize((s, s), Image.LANCZOS).convert("RGBA")


if __name__ == "__main__":
    master, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    sq = square(master)
    scaled(sq, 1024).save(out / "BChat_Master_1024.png")
    for s in SIZES:
        scaled(sq, s).save(out / f"BChat_{s}.png")
    big = scaled(sq, 256)
    big.save(out / "BChat.ico", sizes=[(s, s) for s in ICO],
             append_images=[scaled(sq, s) for s in ICO if s != 256])
    print("icon set written to", out)
