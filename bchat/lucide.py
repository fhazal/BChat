"""Lucide icons (https://lucide.dev, ISC) coloured from the theme. One outline style for the whole app:
menus and buttons in the theme's text colour, chat line pictures in their meaning's colour (join, part, info)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

DIR = Path(__file__).parent / "assets" / "lucide"

# BChat's icon names (the old XChat stock names, kept so callers don't change) -> Lucide icon
NAMES = {
    "close-light": "x", "close": "x", "cancel": "x", "save": "save", "clear": "eraser", "help": "circle-help",
    "connect": "plug", "disconnect": "unplug", "quit": "log-out", "dialog": "app-window", "justify": "list",
    "jump": "hash", "find": "search", "add": "plus", "remove": "minus", "revert": "puzzle", "open": "folder-open",
    "new": "square-plus", "preferences": "settings", "copy": "copy", "about": "info", "book": "server",
    "info": "info", "file": "file-text", "no": "ban", "support": "heart", "web": "globe",
    # 0.2.0: highlight rules, favourite channels
    "edit": "pencil", "play": "play", "favourite": "star", "up": "arrow-up", "down": "arrow-down",
    # updates (11-08): check again, done, get it, new, problem, install, ready
    "refresh": "refresh-cw", "done": "check", "download": "download", "new-version": "sparkles", "problem": "circle-alert",
    "install": "rotate-cw", "ready": "package-check",
    # 0.3.0 problem reports
    "report": "bug", "send": "send", "alert": "triangle-alert",
    # chat line pictures
    "te-join": "arrow-right", "te-part": "arrow-left", "te-action": "asterisk",
}
_svg: dict[str, bytes] = {}


def has(name: str) -> bool:
    return name in NAMES


def image(name: str, colour: str, px: int) -> QImage:
    """The icon drawn px x px in colour, on transparent."""
    lucide = NAMES.get(name, name)
    if lucide not in _svg:
        _svg[lucide] = (DIR / f"{lucide}.svg").read_bytes()
    data = _svg[lucide].replace(b"currentColor", colour.encode())
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(data)).render(p, QRectF(0, 0, px, px))
    p.end()
    return img
