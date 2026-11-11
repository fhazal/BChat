"""Makes the bee-hexagon logo set (BChat's logo since 2026-11-11) in assets/logo/beehex.

Usage: python packaging/make_beehex_set.py
Draws every size natively with headless Chrome (packaging/beehex_render.html), so 16-32 px get the
small-tuned bee instead of a shrunk big one. Writes, in the same layout make_icon_set.py uses:
  transparent/BChat_<s>.png, BChat_Master_1024.png, BChat.ico, header_<h>.png (title bar)
  wordmark-dark-<h>.png / wordmark-light-<h>.png ("BChat" beside the icon, for README / web)
  installer-corner-55.png / -110.png (installer top-right picture, bee + outlined "BChat" under it)
Then run make_logo_assets.py to copy them into bchat/assets.
Needs Chrome and an internet connection (Fredoka font from Google Fonts, wordmark only).
"""
import base64
import io
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets/logo/beehex"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO = (16, 20, 24, 32, 40, 48, 64, 128, 256)
HEADER = (20, 24, 26, 30, 36, 40, 50, 60)   # title bar logo 20 logical px at 100-300 % (0.5.0)


def render() -> dict[str, Image.Image]:
    page = (Path(__file__).parent / "beehex_render.html").resolve().as_uri()
    dom = subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--virtual-time-budget=8000",
                          "--dump-dom", page], capture_output=True, text=True, timeout=60).stdout
    text = dom.split('<pre id="out">', 1)[1].split("</pre>", 1)[0]
    pics = {}
    for line in text.strip().splitlines():
        name, b64 = line.split("=", 1)
        pics[name] = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    assert "icon_16" in pics and "wordmark_dark_90" in pics, "render failed"
    return pics


if __name__ == "__main__":
    pics = render()
    t = OUT / "transparent"
    t.mkdir(parents=True, exist_ok=True)
    pics["icon_1024"].save(t / "BChat_Master_1024.png")
    for s in SIZES:
        pics[f"icon_{s}"].save(t / f"BChat_{s}.png")
    for h in HEADER:
        pics[f"icon_{h}"].save(t / f"header_{h}.png")
    pics["icon_256"].save(t / "BChat.ico", sizes=[(s, s) for s in ICO],
                          append_images=[pics[f"icon_{s}"] for s in ICO if s != 256])
    for name, im in pics.items():
        if name.startswith("wordmark_"):
            _, tone, h = name.split("_")
            im.save(OUT / f"wordmark-{tone}-{h}.png")
        elif name.startswith("corner_"):
            im.save(OUT / f"installer-corner-{name.split('_')[1]}.png")
    print("bee hex set written to", OUT)
