"""Packaged app, static check (nothing is started): is everything BChat needs inside the built folder?

Every file in bchat/assets is in the bundle with the same bytes, the version text matches, the Qt plugins and
runtime files BChat loads are on disk, the spell-check word list is there. Seconds, safe to run any time.

    python tools/qa/bundle_check.py [--exe dist/BChat/BChat.exe] [--out DIR]
"""
import hashlib
from pathlib import Path

from qa_common import ROOT, exe_version, finish, parse_args

ARGS = parse_args(__doc__.splitlines()[0])
app = Path(ARGS.exe).parent
inside = app / "_internal"
res, skips = {}, {}


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# version: the exe's resource, the bundled version.txt and what the caller expects must agree
vtxt = inside / "bchat" / "assets" / "version.txt"
res["version.txt is bundled"] = vtxt.exists()
bundled = vtxt.read_text(encoding="utf-8").strip() if vtxt.exists() else ""
res["exe version resource = bundled version.txt"] = bool(bundled) and exe_version(ARGS.exe) == bundled
res[f"version is the expected one ({ARGS.expect})"] = bundled == ARGS.expect

# assets: same files, same bytes (version.txt is made by the build, so it is not in the source)
src = ROOT / "bchat" / "assets"
missing, changed = [], []
count = 0
for f in sorted(src.rglob("*")):
    if not f.is_file() or f.name == "version.txt" or "__pycache__" in f.parts:
        continue
    count += 1
    b = inside / "bchat" / "assets" / f.relative_to(src)
    if not b.exists():
        missing.append(str(f.relative_to(src)))
    elif digest(b) != digest(f):
        changed.append(str(f.relative_to(src)))
res[f"all {count} source assets are bundled"] = not missing
res["bundled assets are identical to the source"] = not changed
if missing:
    res["assets missing"] = ", ".join(missing[:20])
if changed:
    res["assets different"] = ", ".join(changed[:20])

# runtime files and Qt plugins BChat loads (seen loaded in the running app, see frozen_extra.py)
q = inside / "PySide6"
NEEDED = {
    "Python runtime": inside / "python312.dll",
    "standard library": inside / "base_library.zip",
    "VC++ runtime": inside / "VCRUNTIME140.dll",
    "Qt core": q / "Qt6Core.dll", "Qt GUI": q / "Qt6Gui.dll", "Qt widgets": q / "Qt6Widgets.dll",
    "Qt network": q / "Qt6Network.dll", "Qt SVG": q / "Qt6Svg.dll", "Qt WebSockets": q / "Qt6WebSockets.dll",
    "Windows platform plugin": q / "plugins" / "platforms" / "qwindows.dll",
    "TLS backend (Schannel)": q / "plugins" / "tls" / "qschannelbackend.dll",
    "SVG icon plugin": q / "plugins" / "iconengines" / "qsvgicon.dll",
    "SVG image plugin": q / "plugins" / "imageformats" / "qsvg.dll",
    "ICO image plugin": q / "plugins" / "imageformats" / "qico.dll",
    "JPEG image plugin": q / "plugins" / "imageformats" / "qjpeg.dll",
    "GIF image plugin": q / "plugins" / "imageformats" / "qgif.dll",
    "spell-check word list (English)": inside / "spellchecker" / "resources" / "en.json.gz",
    "Python SSL": inside / "_ssl.pyd",
}
for what, p in NEEDED.items():
    res[f"on disk: {what}"] = p.exists()
# python312.dll is tied to the build's Python; a different minor version would be python313.dll etc.
if not (inside / "python312.dll").exists():
    other = sorted(x.name for x in inside.glob("python3*.dll") if x.name != "python3.dll")
    res["on disk: Python runtime"] = bool(other)
    res["python runtime file"] = ", ".join(other)

files = [p for p in app.rglob("*") if p.is_file()]
res["files in the bundle"] = len(files)
res["bundle size (bytes)"] = sum(p.stat().st_size for p in files)
finish("bundle_check", ARGS, res, skips)
