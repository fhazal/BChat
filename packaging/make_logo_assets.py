"""Builds every logo file BChat ships from the user's current transparent set (SET below;
make_icon_set.py makes such a set from one transparent master picture).

- bchat/assets/bchat.ico + bchat.png: app, taskbar, shortcut and installer icon (the set's own .ico, 16-256 px)
- bchat/assets/header/logo-<h>.png: title bar logo, 16 logical px at 100-300 % scale
- packaging/wizard-side(-2x).bmp, wizard-small(-2x).bmp: installer pictures
The logo is already transparent, so no cut-out is needed (the old simple logo needed one).
Needs Pillow; only run it to change the design.
"""
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "assets/logo/pinkblue/transparent"   # since 2026-11-07 ~11:30 (earlier sets: gradient, bold, simple, detailed)
MASTER = SET / "BChat_Master_1024.png"
HEADER = ROOT / "bchat/assets/header"
HEIGHTS = (16, 20, 24, 28, 32, 40, 48)
CRUST = (17, 17, 27)      # installer side picture background, same as before
WHITE = (255, 255, 255)   # installer header background (Inno draws white there)


def trimmed() -> Image.Image:
    im = Image.open(MASTER).convert("RGBA")
    return im.crop(im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox())


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    k = min(w / im.width, h / im.height)
    return im.convert("RGBa").resize((max(1, round(im.width * k)), max(1, round(im.height * k))),
                                     Image.LANCZOS).convert("RGBA")


def on(bg, size, logo, box_w, box_h, centre_y) -> Image.Image:
    canvas = Image.new("RGBA", size, bg + (255,))
    l = fit(logo, box_w, box_h)
    canvas.alpha_composite(l, ((size[0] - l.width) // 2, int(centre_y - l.height / 2)))
    return canvas.convert("RGB")


if __name__ == "__main__":
    logo = trimmed()
    shutil.copyfile(SET / "BChat.ico", ROOT / "bchat/assets/bchat.ico")
    shutil.copyfile(SET / "BChat_256.png", ROOT / "bchat/assets/bchat.png")
    HEADER.mkdir(parents=True, exist_ok=True)
    for h in HEIGHTS:
        fit(logo, 10 * h, h).save(HEADER / f"logo-{h}.png")
    for scale, suffix in ((1, ""), (2, "-2x")):
        on(CRUST, (164 * scale, 314 * scale), logo, 124 * scale, 124 * scale, 130 * scale).save(
            ROOT / f"packaging/wizard-side{suffix}.bmp")
        on(WHITE, (55 * scale, 55 * scale), logo, 49 * scale, 49 * scale, 27.5 * scale).save(
            ROOT / f"packaging/wizard-small{suffix}.bmp")
    print("logo files written")
