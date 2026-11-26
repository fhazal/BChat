"""The server and channel tree: server > (notices), Channel: N and Private: N folders > tabs, with icons and thin lines.
Icons are Lucide outlines drawn from SVG at the screen's real size, so they stay sharp at any scale."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QTreeWidget


# 0.9.3 (owner's pick, "Line A + Lucide"): the tree uses the app's one icon style, Lucide outlines in theme colours.
_LUCIDE = {"server": "monitor", "folder": "folder", "channel": "hash", "query": "user", "notices": "bell"}
_INK = {"server": "new_highlight", "folder": "highlight", "channel": "text", "query": "join", "notices": "highlight"}
_theme = None


def set_tree_theme(theme) -> None:
    """The theme the tree icons take their colours from (set at start and after Preferences > OK)."""
    global _theme
    _theme = theme


def _ink(kind: str) -> str:
    t = _theme
    if t is None:
        from .config import Theme
        t = Theme()
    return getattr(t, _INK[kind])


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
        pm = QPixmap.fromImage(lucide.image(_LUCIDE[kind], colour, size))
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
