"""The server and channel tree: server > Channel: N and Private: N folders > tabs, with icons and thin lines.
Everything is drawn in code so it stays sharp at any screen scale."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QTreeWidget


def _server(p: QPainter) -> None:
    """The monitor: the server icon."""
    p.setPen(QPen(QColor("#89b4fa"), 1.2))
    p.setBrush(QColor("#313244"))
    p.drawRoundedRect(QRectF(1.5, 2, 13, 9.5), 1.5, 1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#74c7ec"))
    p.drawRect(QRectF(3.5, 4, 9, 5.5))
    p.setBrush(QColor("#89b4fa"))
    p.drawRect(QRectF(6.5, 11.5, 3, 1.5))
    p.drawRect(QRectF(4.5, 13, 7, 1.2))


def _folder(p: QPainter) -> None:
    p.setPen(QPen(QColor("#df8e1d"), 1))
    p.setBrush(QColor("#f9e2af"))
    p.drawRoundedRect(QRectF(1.5, 3, 6, 3), 1, 1)
    p.setBrush(QColor("#f9c74f"))
    p.drawRoundedRect(QRectF(1.5, 4.5, 13, 9), 1, 1)


def _channel(p: QPainter) -> None:
    p.setPen(QPen(QColor("#74c7ec"), 1))
    p.setBrush(QColor("#eff1f5"))
    p.drawRoundedRect(QRectF(1.5, 1.5, 13, 13), 1.5, 1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1e66f5"))
    p.drawRect(QRectF(2, 2, 12, 2.2))
    p.setPen(QPen(QColor("#1e1e2e"), 1))
    for x in (6.5, 9.5):
        p.drawLine(QPointF(x, 5.5), QPointF(x, 13.5))
    for y in (7.5, 10.5):
        p.drawLine(QPointF(3.5, y), QPointF(12.5, y))


def _private(p: QPainter) -> None:
    p.setPen(QPen(QColor("#a6e3a1"), 1))
    p.setBrush(QColor("#313244"))
    p.drawRoundedRect(QRectF(1.5, 2, 13, 9), 2.5, 2.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#a6e3a1"))
    for x in (5, 8, 11):
        p.drawEllipse(QPointF(x, 6.5), 0.9, 0.9)
    p.drawPolygon([QPointF(4.5, 10.5), QPointF(8, 10.5), QPointF(4.5, 14)])


_DRAW = {"server": _server, "folder": _folder, "channel": _channel, "query": _private}
_cache: dict[tuple[str, float], QIcon] = {}


def _dpr() -> float:
    screen = QApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def icon_points() -> int:
    """mIRC's tree icons are 16 real pixels. Same here, never under 11 points so they don't vanish on a very high scale."""
    return max(11, round(16 / _dpr()))


def tree_icon(kind: str) -> QIcon:
    dpr = _dpr()
    key = (kind, dpr)
    if key not in _cache:
        size = max(16, int(icon_points() * dpr))
        pm = QPixmap(size, size)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = size / 16 / dpr
        p.scale(k, k)
        _DRAW[kind](p)
        p.end()
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
