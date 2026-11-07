"""Installer pictures (OK'd 2026-11-08, mockup-installer-bee.png + the user's orange-pink B):
- packaging/wizard-side(-2x).bmp: welcome and finish pages, the bee banner ("BChat IRC CLIENT") on dark with a soft
  amber glow and the tagline
- packaging/wizard-small(-2x).bmp: top right of the other pages, the orange-pink B
The app icon and the title bar logo are not touched (make_logo_assets.py). Needs Pillow; run only to change the design.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BANNER = ROOT / "assets/logo/bee/banner-original.png"
SMALL_B = ROOT / "assets/logo/orangepink/original.webp"
CRUST = (17, 17, 27)
WHITE = (255, 255, 255)
TAGLINE = "Handle IRC as a bee does a flower"


def trim(im: Image.Image) -> Image.Image:
    return im.crop(im.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox())


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    k = min(w / im.width, h / im.height)
    return im.convert("RGBa").resize((max(1, round(im.width * k)), max(1, round(im.height * k))),
                                     Image.LANCZOS).convert("RGBA")


def side(k: int) -> Image.Image:
    bg = Image.new("RGBA", (164 * k, 314 * k), CRUST + (255,))
    glow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((20 * k, 70 * k, 144 * k, 200 * k), fill=(250, 179, 60, 70))
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(28 * k)))
    art = fit(trim(Image.open(BANNER).convert("RGBA")), 150 * k, 200 * k)
    bg.alpha_composite(art, ((bg.width - art.width) // 2, 50 * k))
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 9 * k)
    d = ImageDraw.Draw(bg)
    d.text(((bg.width - d.textlength(TAGLINE, font=font)) // 2, 262 * k), TAGLINE, font=font, fill=(166, 173, 200))
    return bg.convert("RGB")


def small(k: int) -> Image.Image:
    bg = Image.new("RGBA", (55 * k, 55 * k), WHITE + (255,))
    b = fit(trim(Image.open(SMALL_B).convert("RGBA")), 49 * k, 49 * k)
    bg.alpha_composite(b, ((bg.width - b.width) // 2, (bg.height - b.height) // 2))
    return bg.convert("RGB")


if __name__ == "__main__":
    for k, suffix in ((1, ""), (2, "-2x")):
        side(k).save(ROOT / f"packaging/wizard-side{suffix}.bmp")
        small(k).save(ROOT / f"packaging/wizard-small{suffix}.bmp")
    print("installer pictures written")
