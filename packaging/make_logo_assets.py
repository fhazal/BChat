"""Builds every logo file BChat ships from the user's current transparent set (SET below;
make_icon_set.py makes such a set from one transparent master picture).

- bchat/assets/bchat.ico + bchat.png: app, taskbar, shortcut and installer icon (the set's own .ico, 16-256 px)
- bchat/assets/header/logo-<h>.png: title bar logo, 16 logical px at 100-300 % scale (the set's header_<h>.png if it has them)
- (installer pictures: make_installer_art.py, since 2026-11-08)
The logo is already transparent, so no cut-out is needed (the old simple logo needed one).
Needs Pillow; only run it to change the design.
"""
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "assets/logo/beehex/transparent"   # since 2026-11-11 (make_beehex_set.py); earlier: pinkblue, gradient, bold, simple, detailed
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
        own = SET / f"header_{h}.png"   # a set drawn per size (beehex) brings its own small-tuned title bar logos
        if own.exists():
            shutil.copyfile(own, HEADER / f"logo-{h}.png")
        else:
            fit(logo, 10 * h, h).save(HEADER / f"logo-{h}.png")
    # the installer pictures have their own design now (bee + orange-pink B): make_installer_art.py
    print("logo files written")
