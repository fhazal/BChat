"""Draws bchat/assets/tick.png: the dark tick inside a ticked checkbox (box colour is Theme.check).
Drawn large and scaled down so it stays smooth at every display scale. Needs Pillow; only run it to change the design."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BIG, OUT = 192, 48
CRUST = (17, 17, 27, 255)

if __name__ == "__main__":
    im = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.line([(38, 100), (78, 140), (154, 52)], fill=CRUST, width=28, joint="curve")
    for x, y in ((38, 100), (154, 52)):   # round ends
        d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=CRUST)
    im.resize((OUT, OUT), Image.LANCZOS).save(ROOT / "bchat/assets/tick.png")
    print("tick written")
