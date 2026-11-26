"""The server and channel tree: server > (notices), Channel: N and Private: N folders > tabs, with icons and thin lines.
Icons are Lucide outlines drawn from SVG at the screen's real size, so they stay sharp at any scale."""
from __future__ import annotations

import colorsys

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QTreeWidget


# 0.9.3 (owner's pick, "Line A + Lucide"): the tree uses the app's one icon style, Lucide outlines in theme colours.
_LUCIDE = {"server": "monitor", "folder": "folder", "channel": "hash", "query": "user", "notices": "bell"}
_INK = {"server": "new_highlight", "folder": "highlight", "channel": "text", "query": "join", "notices": "highlight"}
# 0.9.3 "C2": folder, bell, monitor and person get a soft fill of their own colour; # is open lines and stays an outline.
_FILL = {"server": 0.22, "folder": 0.22, "query": 0.22, "notices": 0.22}
# Contrast guard: an icon colour fainter than this against the tree's panel (WCAG ratio; 4.5 = as clear as text)
# is made darker (light panel) or lighter (dark panel) on the same hue, so amber stays amber. Works for custom colours too.
ICON_CONTRAST = 4.5
_theme = None


def set_tree_theme(theme) -> None:
    """The theme the tree icons take their colours from (set at start and after Preferences > OK)."""
    global _theme
    _theme = theme


def _rgb(colour: str) -> tuple[float, float, float]:
    c = QColor(colour)
    return c.redF(), c.greenF(), c.blueF()


def _luminance(colour: str) -> float:
    lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in _rgb(colour)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two colours, 1 to 21."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def guard(colour: str, panel: str, target: float = ICON_CONTRAST) -> str:
    """colour, or the nearest shade of the same hue that reaches target contrast on panel."""
    if not QColor(colour).isValid() or not QColor(panel).isValid() or contrast(colour, panel) >= target:
        return colour
    h, l, s = colorsys.rgb_to_hls(*_rgb(colour))
    darker = _luminance(panel) > 0.18           # light panel: go darker; dark panel: go lighter

    def shade(light: float) -> str:
        return QColor.fromRgbF(*colorsys.hls_to_rgb(h, light, s)).name()
    lo, hi = (0.0, l) if darker else (l, 1.0)   # the side that passes: lo (darker) or hi (lighter)
    for _ in range(24):
        mid = (lo + hi) / 2
        if (contrast(shade(mid), panel) >= target) == darker:
            lo = mid
        else:
            hi = mid
    return shade(lo if darker else hi)


def _ink(kind: str) -> str:
    t = _theme
    if t is None:
        from .config import Theme
        t = Theme()
    return guard(getattr(t, _INK[kind]), t.panel)


_cache: dict[tuple[str, float, str], QIcon] = {}


def _dpr() -> float:
    screen = QApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def icon_points() -> int:
    """mIRC's tree icons are 16 real pixels. Same here, never under 11 points so they don't vanish on a very high scale."""
    return max(11, round(16 / _dpr()))


def tree_icon(kind: str) -> QIcon:
    from . import lucide
    dpr = _dpr()
    colour = _ink(kind)
    key = (kind, dpr, colour)
    if key not in _cache:
        size = max(16, int(icon_points() * dpr))
        pm = QPixmap.fromImage(lucide.image(_LUCIDE[kind], colour, size, _FILL.get(kind, 0.0)))
        pm.setDevicePixelRatio(dpr)
        icon = QIcon()
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
            icon.addPixmap(pm, mode)   # the same colours when selected, Qt would tint them
        _cache[key] = icon
    return _cache[key]


class SwitcherTree(QTreeWidget):
    """Thin connector lines and a boxed +/-."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("switcher")
        self.setIndentation(16)
        self.setIconSize(QSize(icon_points(), icon_points()))

    def drawBranches(self, p, rect, index):
        """Thin solid lines, one real pixel at any screen scale. Each server stands alone: no line joins one to the next."""
        t = self.theme
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        line = QPen(QColor(t.tree_line), 1)
        line.setCosmetic(True)
        p.setPen(line)
        ind = self.indentation()
        chain = []
        i = index
        while i.isValid():
            chain.append(i)
            i = i.parent()
        mid = rect.center().y()
        left = rect.right() + 1 - ind * len(chain)
        for level, node in enumerate(reversed(chain)):
            x = left + ind * level + ind // 2
            more = node.sibling(node.row() + 1, 0).isValid()
            if node == index:
                if level:
                    p.drawLine(x, rect.top(), x, rect.bottom() if more else mid)
                    p.drawLine(x, mid, x + ind // 2 + 1, mid)
                if self.model().hasChildren(node):
                    box = QPen(QColor(t.tree_box), 1)
                    box.setCosmetic(True)
                    p.setPen(box)
                    p.setBrush(QColor(t.panel))
                    p.drawRect(x - 4, mid - 4, 8, 8)
                    sign = QPen(QColor(t.text), 1)
                    sign.setCosmetic(True)
                    p.setPen(sign)
                    p.drawLine(x - 2, mid, x + 2, mid)
                    if not self.isExpanded(node):
                        p.drawLine(x, mid - 2, x, mid + 2)
                    p.setPen(line)
            elif more and level:
                p.drawLine(x, rect.top(), x, rect.bottom())
        p.restore()
