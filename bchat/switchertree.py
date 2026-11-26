"""The server and channel tree: server > Channel: N and Private: N folders > tabs, with icons and thin lines.
Everything is drawn in code so it stays sharp at any screen scale."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QTreeWidget


def _server(p: QPainter) -> None:
    """The monitor: the server icon, with a glass screen and a stand."""
    p.setPen(QPen(QColor("#1e66f5"), 1))
    p.setBrush(QColor("#313244"))
    p.drawRoundedRect(QRectF(1, 1.5, 14, 10), 2, 2)
    g = QLinearGradient(0, 3, 0, 10)
    g.setColorAt(0, QColor("#b4d4ff"))
    g.setColorAt(0.5, QColor("#74a8f7"))
    g.setColorAt(1, QColor("#3a6fd8"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(2.6, 3, 10.8, 7), 1, 1)
    p.setBrush(QColor(255, 255, 255, 90))               # the glare
    p.drawPolygon([QPointF(2.6, 3), QPointF(9, 3), QPointF(5, 10), QPointF(2.6, 10)])
    p.setBrush(QColor("#7f849c"))
    p.drawRect(QRectF(7, 11.5, 2, 2))
    p.drawRoundedRect(QRectF(4, 13.2, 8, 1.6), 0.8, 0.8)


def _folder(p: QPainter) -> None:
    p.setPen(QPen(QColor("#c07a10"), 0.8))
    p.setBrush(QColor("#e8a838"))
    p.drawRoundedRect(QRectF(1, 2.5, 6.5, 4), 1.2, 1.2)
    p.drawRoundedRect(QRectF(1, 4, 14, 9.5), 1.2, 1.2)
    g = QLinearGradient(0, 5.5, 0, 13.5)
    g.setColorAt(0, QColor("#ffe08a"))
    g.setColorAt(1, QColor("#f5b83d"))
    p.setBrush(g)
    p.drawRoundedRect(QRectF(1, 5.8, 14, 7.7), 1.2, 1.2)


def _channel(p: QPainter) -> None:
    """A blue chat bubble with a white #: a room."""
    bubble = QPainterPath()
    bubble.addRoundedRect(QRectF(1, 1.5, 14, 10.5), 3, 3)
    tail = QPainterPath()
    tail.moveTo(3.5, 11)
    tail.lineTo(3.5, 15)
    tail.lineTo(7.5, 11.5)
    tail.closeSubpath()
    g = QLinearGradient(0, 1.5, 0, 12)
    g.setColorAt(0, QColor("#8fb8ff"))
    g.setColorAt(1, QColor("#2f6be0"))
    p.setPen(QPen(QColor("#1d4fb8"), 0.8))
    p.setBrush(g)
    p.drawPath(bubble.united(tail))
    pen = QPen(QColor("white"), 1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(6.4, 3.8), QPointF(5.6, 10))
    p.drawLine(QPointF(10.2, 3.8), QPointF(9.4, 10))
    p.drawLine(QPointF(4, 5.6), QPointF(12.2, 5.6))
    p.drawLine(QPointF(3.6, 8.2), QPointF(11.8, 8.2))


def _private(p: QPainter) -> None:
    """A green person: one other person."""
    head = QRadialGradient(QPointF(7, 4), 4)
    head.setColorAt(0, QColor("#c8f5c0"))
    head.setColorAt(1, QColor("#40a02b"))
    p.setPen(QPen(QColor("#2d7a1f"), 0.8))
    p.setBrush(head)
    p.drawEllipse(QPointF(8, 5), 3.3, 3.3)
    body = QPainterPath()
    body.moveTo(2, 15)
    body.cubicTo(2, 9.5, 14, 9.5, 14, 15)
    body.closeSubpath()
    g = QLinearGradient(0, 9.5, 0, 15)
    g.setColorAt(0, QColor("#8ee07e"))
    g.setColorAt(1, QColor("#3a9a28"))
    p.setBrush(g)
    p.drawPath(body)


def _notices(p: QPainter) -> None:
    """An amber bell: the server notices tab, the server talking rather than a person."""
    bell = QPainterPath()
    bell.moveTo(8, 1.5)
    bell.cubicTo(4, 1.5, 3.6, 5, 3.6, 7.5)
    bell.lineTo(3.6, 10)
    bell.lineTo(2, 12.2)
    bell.lineTo(14, 12.2)
    bell.lineTo(12.4, 10)
    bell.lineTo(12.4, 7.5)
    bell.cubicTo(12.4, 5, 12, 1.5, 8, 1.5)
    bell.closeSubpath()
    g = QLinearGradient(0, 1.5, 0, 12.2)
    g.setColorAt(0, QColor("#ffe08a"))
    g.setColorAt(1, QColor("#e5940f"))
    p.setPen(QPen(QColor("#b06d05"), 0.8))
    p.setBrush(g)
    p.drawPath(bell)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#b06d05"))
    p.drawEllipse(QPointF(8, 13.6), 1.7, 1.5)


_DRAW = {"server": _server, "folder": _folder, "channel": _channel, "query": _private, "notices": _notices}
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
