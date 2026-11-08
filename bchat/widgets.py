"""Theme, icons, the macOS-style title bar and the frameless window base."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QHBoxLayout, QLabel, QMainWindow, QSizePolicy,
                               QVBoxLayout, QWidget)

from .config import Theme

ASSETS = Path(__file__).parent / "assets"
RED, YELLOW, GREEN = "#ff5f57", "#febc2e", "#28c840"
_icons: dict[tuple[str, str], QIcon] = {}
_ink = "#cdd6f4"                    # the theme's text colour: what Lucide icons are drawn in
_names_by_key: dict[int, str] = {}  # QIcon cache key -> icon name, to swap icons when the theme changes


def icon(name: str) -> QIcon:
    """Lucide icons in the theme's text colour; anything else (the tray message picture) from its PNG."""
    from . import lucide
    ink = _ink if lucide.has(name) else ""
    if (name, ink) not in _icons:
        if ink:
            ic = QIcon()
            for px in (16, 20, 24, 32, 48):        # sharp at every screen scale
                ic.addPixmap(QPixmap.fromImage(lucide.image(name, ink, px)))
        else:
            p = ASSETS / f"{name}.png"
            if not p.exists():
                p = ASSETS / "stock" / f"{name}.png"
            ic = QIcon(str(p))
        _icons[(name, ink)] = ic
        _names_by_key[ic.cacheKey()] = name
    return _icons[(name, ink)]


def is_light(t: Theme) -> bool:
    return QColor(t.panel).lightness() > 140


_os_palette: QPalette | None = None


def set_light_palette(t: Theme) -> None:
    """Qt colours whatever BChat doesn't style itself (spin boxes, frame lines, plain tool buttons) from Windows,
    and on a PC in dark mode that is dark. A light theme gets its own colours for those; a dark theme gets
    exactly what Windows gave before, so dark themes look as they always did."""
    global _os_palette
    app = QApplication.instance()
    if app is None:
        return
    if _os_palette is None:
        _os_palette = QPalette(app.palette())
    if not is_light(t):
        app.setPalette(_os_palette)
        return
    p = QPalette()
    R = QPalette.ColorRole
    for role, colour in ((R.Window, t.window), (R.WindowText, t.text), (R.Base, t.panel), (R.AlternateBase, t.window),
                         (R.Text, t.text), (R.Button, t.popup), (R.ButtonText, t.text), (R.BrightText, t.marker),
                         (R.Highlight, t.selected), (R.HighlightedText, t.marking_fg), (R.ToolTipBase, t.panel),
                         (R.ToolTipText, t.text), (R.PlaceholderText, t.disabled), (R.Link, t.new_highlight),
                         (R.LinkVisited, t.topic), (R.Light, t.panel), (R.Midlight, t.window), (R.Mid, t.thumb),
                         (R.Dark, t.thumb_hover), (R.Shadow, t.away)):
        p.setColor(role, QColor(colour))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.disabled))
    app.setPalette(p)


def set_icon_theme(t: Theme, root=None) -> None:
    """Icons follow the theme's text colour. Buttons and menu items that already show one get the new colour."""
    global _ink
    _ink = t.text
    if root is None:
        return
    from PySide6.QtGui import QAction
    for w in root.findChildren(QAbstractButton) + root.findChildren(QAction):
        name = _names_by_key.get(w.icon().cacheKey())
        if name:
            w.setIcon(icon(name))


def pixmap(name: str) -> QPixmap:
    p = ASSETS / f"{name}.png"
    if not p.exists():
        p = ASSETS / "stock" / f"{name}.png"
    return QPixmap(str(p))


def header_logo(dpr: float) -> QPixmap:
    height = min((16, 20, 24, 28, 32, 40, 48), key=lambda h: abs(h - 16 * dpr))
    pm = QPixmap(str(ASSETS / "header" / f"logo-{height}.png"))
    pm.setDevicePixelRatio(dpr)
    return pm


def stylesheet(t: Theme) -> str:
    return _sheet(t) + (_light_extra(t) if is_light(t) else "")


def _buttons(t: Theme) -> str:
    """XChat 2's buttons (GTK on Windows 11): soft fill, thin border, round corners, 27 px tall."""
    if is_light(t):
        fill, hover, down, edge, bottom, focus = t.panel, t.window, t.popup, t.thumb, t.thumb_hover, t.disabled
    else:
        fill, hover, down, edge, bottom, focus = t.popup, t.thumb, t.bar, t.thumb, t.thumb, t.thumb_hover
    return f"""    QPushButton {{ background: {fill}; border: 1px solid {edge}; border-bottom-color: {bottom}; border-radius: 4px;
                   padding: 4px 12px; min-height: 17px; }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:pressed {{ background: {down}; }}
    QPushButton:focus {{ border-color: {focus}; }}
    QPushButton:disabled {{ color: {t.disabled}; }}
"""


BUTTON_MIN_WIDTH = 85      # GTK's button box minimum (XChat's Cancel / OK rows)
ICON_GAP = 6               # extra room between a button's icon and its words, like XChat
COMPACT = {"modebtn", "ulbtn", "compact"}


def _gap_icon(ic: QIcon) -> QIcon:
    """The same icon with clear space on its right: Qt's stylesheet puts the words right after the picture."""
    out = QIcon()
    for px in (16, 20, 24, 32, 48):
        src = ic.pixmap(QSize(px, px), 1.0)          # real pixels at this size, whatever the screen scale
        if src.isNull():
            continue
        src.setDevicePixelRatio(1.0)
        gap = round(px * ICON_GAP / 16)
        pm = QPixmap(px + gap, px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.drawPixmap((px - src.width()) // 2, (px - src.height()) // 2, src)
        p.end()
        out.addPixmap(pm)
    return out


def even_button_rows(root: QWidget) -> None:
    """XChat's button boxes: every button in a row of buttons gets the same width, at least 85 px.
    Rows mixing buttons with fields (Browse... beside a box) and small fixed buttons stay as they are."""
    from PySide6.QtWidgets import QPushButton
    for lay in [root.layout()] + root.findChildren(QHBoxLayout):
        if not isinstance(lay, QHBoxLayout):
            continue
        items = [lay.itemAt(i) for i in range(lay.count())]
        widgets = [it.widget() for it in items if it.widget() is not None]
        has_space = any(it.spacerItem() is not None for it in items)
        if not widgets or not all(type(w) is QPushButton for w in widgets) or (len(widgets) < 2 and not has_space):
            continue
        if any(w.objectName() in COMPACT or w.minimumWidth() == w.maximumWidth() or len(w.text().replace("&", "")) < 2
               for w in widgets):
            continue
        for w in widgets:
            w.ensurePolished()
        width = max([BUTTON_MIN_WIDTH] + [w.sizeHint().width() for w in widgets])
        for w in widgets:
            w.setMinimumWidth(width)


class ButtonLook(QObject):
    """App-wide: puts the icon gap on every icon-and-words button, and evens out button rows when a window opens."""

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t in (QEvent.Type.Polish, QEvent.Type.Paint) and type(obj).__name__ == "QPushButton":
            ic = obj.icon()
            if not ic.isNull() and obj.text() and obj.property("bchat_gap") != ic.cacheKey():
                spaced = _gap_icon(ic)
                name = _names_by_key.get(ic.cacheKey())
                if name:
                    _names_by_key[spaced.cacheKey()] = name      # a theme change still finds and recolours it
                obj.setProperty("bchat_gap", spaced.cacheKey())
                obj.setIcon(spaced)
                obj.setIconSize(QSize(16 + ICON_GAP, 16))
        elif t == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            even_button_rows(obj)
        return False


_button_look: ButtonLook | None = None


def install_button_look(app=None) -> None:
    global _button_look
    app = app or QApplication.instance()
    if app is not None and _button_look is None:
        _button_look = ButtonLook(app)
        app.installEventFilter(_button_look)


def _sheet(t: Theme) -> str:
    return f"""
    * {{ font-family: Tahoma, Verdana, sans-serif; font-size: 8pt; color: {t.text}; }}
    QMainWindow, QDialog, #root {{ background: {t.window}; }}
    #root {{ border: 1px solid {t.border}; }}
    #titlebar {{ background: {t.bar}; border-bottom: 1px solid {t.border}; }}
    #titlebar QLabel {{ font-size: 9pt; }}
    QMenuBar {{ background: {t.window}; border-bottom: 1px solid {t.border}; padding: 1px 3px; }}
    QMenuBar::item {{ background: transparent; padding: 2px 6px; }}
    QMenuBar::item:selected {{ background: {t.selected}; color: #fff; }}
    QMenu {{ background: {t.popup}; border: 1px solid {t.border}; padding: 2px; }}
    QMenu::item {{ padding: 3px 24px 3px 24px; }}
    QMenu::icon {{ padding-left: 5px; }}
    QMenu::item:selected {{ background: {t.selected}; color: #fff; }}
    QMenu::item:disabled {{ color: {t.disabled}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 3px 2px; }}
    QTreeWidget, QListView, QListWidget, QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QTableWidget {{
        background: {t.panel}; border: 1px solid {t.border}; selection-background-color: {t.selected};
        selection-color: {t.marking_fg}; outline: 0; }}
    QTreeWidget::item {{ height: 17px; }}
    QTreeWidget::item:selected, QListView::item:selected, QListWidget::item:selected {{ background: {t.selected}; color: {t.marking_fg}; }}
    QTreeWidget::item:disabled {{ color: {t.disabled}; }}
    QTreeWidget#switcher::item {{ height: 20px; }}
    QTreeWidget#switcher::branch {{ background: transparent; border-image: none; image: none; }}
    QHeaderView::section {{ background: {t.bar}; border: 1px solid {t.border}; padding: 2px; }}
    QLineEdit {{ padding: 1px 4px; }}
    QTextBrowser {{ background: {t.chat_bg}; color: {t.chat_fg}; border: 1px solid {t.border}; selection-background-color: {t.selected}; selection-color: {t.marking_fg}; }}
    #count {{ background: {t.bar}; border: 1px solid {t.border}; padding: 2px; qproperty-alignment: AlignCenter; }}
    #nicklabel {{ padding: 0 6px; }}
{_buttons(t)}    QPushButton#modebtn {{ padding: 0; min-width: 0; min-height: 16px; border-radius: 3px; }}
    QPushButton#modebtn:checked {{ background: {t.selected}; color: {t.marking_fg}; }}
    QPushButton#ulbtn {{ padding: 1px 4px; min-width: 0; min-height: 16px; border-radius: 3px; }}
    QPushButton#compact {{ padding: 3px 10px; min-height: 16px; border-radius: 3px; }}
    QToolButton:disabled {{ color: {t.disabled}; }}
    QRadioButton {{ spacing: 7px; }}
    QRadioButton::indicator {{ width: 12px; height: 12px; border: 1px solid {t.disabled}; border-radius: 7px; background: {t.panel}; }}
    QRadioButton::indicator:hover {{ border: 1px solid {t.check}; }}
    QRadioButton::indicator:checked {{ border: 1px solid {t.check}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #11111b, stop:0.42 #11111b, stop:0.52 {t.check}, stop:1 {t.check}); }}
    QCheckBox::indicator {{ width: 12px; height: 12px; border: 1px solid {t.border}; border-radius: 2px; background: {t.panel}; }}
    QCheckBox::indicator:hover {{ border: 1px solid {t.check}; }}
    QCheckBox::indicator:checked {{ background: {t.check}; border: 1px solid {t.check}; image: url({(ASSETS / "tick.png").as_posix()}); }}
    QCheckBox::indicator:checked:disabled {{ background: {t.disabled}; border: 1px solid {t.disabled}; }}
    QScrollBar:vertical {{ background: {t.bar}; width: 13px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t.thumb}; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.thumb_hover}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QScrollBar:horizontal {{ background: {t.bar}; height: 13px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t.thumb}; min-width: 24px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QSplitter::handle {{ background: {t.window}; }}
    QToolTip {{ background: {t.popup}; color: {t.text}; border: 1px solid {t.border}; }}
    """


def _light_extra(t: Theme) -> str:
    """Only on a light theme: selected menu text in the theme's text colour (white is unreadable on light grey),
    and spin boxes in the panel colour like the other entry boxes."""
    return f"""
    QMenuBar::item:selected, QMenu::item:selected {{ color: {t.marking_fg}; }}
    QAbstractSpinBox {{ background: {t.panel}; border: 1px solid {t.border}; selection-background-color: {t.selected};
        selection-color: {t.marking_fg}; }}
    QAbstractSpinBox:disabled {{ color: {t.disabled}; }}
    QPushButton:disabled {{ color: {t.away}; }}
    QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {t.thumb_hover}; }}
    """



class TrafficLight(QAbstractButton):
    """One round macOS-style window button. The glyph shows while the mouse is over the group."""
    SIZE = 12

    def __init__(self, colour: str, glyph: str, tip: str, parent=None):
        super().__init__(parent)
        self.colour = QColor(colour)
        self.glyph = glyph
        self.show_glyph = False
        self.setToolTip(tip)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = self.colour.darker(125) if self.isDown() else self.colour
        p.setPen(QPen(col.darker(130), 0.6))
        p.setBrush(col)
        p.drawEllipse(QRectF(0.5, 0.5, self.SIZE - 1, self.SIZE - 1))
        if not self.show_glyph:
            return
        p.setPen(QPen(QColor(0, 0, 0, 170), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = self.SIZE / 2
        r = 2.6
        if self.glyph == "x":
            p.drawLine(QRectF(c - r, c - r, 2 * r, 2 * r).topLeft(), QRectF(c - r, c - r, 2 * r, 2 * r).bottomRight())
            p.drawLine(QRectF(c - r, c - r, 2 * r, 2 * r).topRight(), QRectF(c - r, c - r, 2 * r, 2 * r).bottomLeft())
        elif self.glyph == "-":
            p.drawLine(QPoint(int(c - r), int(c)), QPoint(int(c + r), int(c)))
        else:
            p.drawLine(QPoint(int(c - r), int(c)), QPoint(int(c + r), int(c)))
            p.drawLine(QPoint(int(c), int(c - r)), QPoint(int(c), int(c + r)))


class TitleBar(QWidget):
    """Drag to move, double click to maximise. Dialogs get the red button only."""
    close_clicked = Signal()
    min_clicked = Signal()
    max_clicked = Signal()

    def __init__(self, parent=None, full: bool = True):
        super().__init__(parent)
        self.setObjectName("titlebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(26)
        self.full = full
        self.lights: list[TrafficLight] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 0, 9, 0)
        lay.setSpacing(8)
        spec = [(RED, "x", "Close", self.close_clicked)]
        if full:
            spec += [(YELLOW, "-", "Minimize", self.min_clicked), (GREEN, "+", "Maximize", self.max_clicked)]
        self.group = QWidget(self)
        self.group.setMouseTracking(True)
        g = QHBoxLayout(self.group)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(8)
        for colour, glyph, tip, sig in spec:
            b = TrafficLight(colour, glyph, tip, self.group)
            b.clicked.connect(sig)
            g.insertWidget(0, b)  # Windows order on screen: minimize, maximize, close
            self.lights.append(b)
        g.insertWidget(1, self.lights[2]) if full else None
        self.group.installEventFilter(self)
        # 16 px tall like XChat's title bar icon, no background, drawn for this display scale
        self.logo = QLabel(self)
        pm = header_logo(self.devicePixelRatioF())
        self.logo.setFixedSize(math.ceil(pm.width() / pm.devicePixelRatio()), 16)
        self.logo.setPixmap(pm)
        self.logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.logo)
        self.title = QLabel(self)
        self.title.setTextFormat(Qt.TextFormat.PlainText)  # channel names come from the network
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.group)

    def eventFilter(self, obj, ev):
        if obj is self.group and ev.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            for b in self.lights:
                b.show_glyph = ev.type() == QEvent.Type.Enter
                b.update()
        return super().eventFilter(obj, ev)

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            h = self.window().windowHandle()
            if h is not None:
                h.startSystemMove()

    def mouseDoubleClickEvent(self, ev):
        if self.full and ev.button() == Qt.MouseButton.LeftButton:
            self.max_clicked.emit()


class _ResizeRoot(QWidget):
    """Root widget whose thin outer edge resizes the window."""
    EDGE = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setMouseTracking(True)

    def _edges(self, pos) -> Qt.Edge:
        e = Qt.Edge(0)
        if self.window().isMaximized():
            return e
        if pos.x() < self.EDGE:
            e |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - self.EDGE:
            e |= Qt.Edge.RightEdge
        if pos.y() < self.EDGE:
            e |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - self.EDGE:
            e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, ev):
        e = self._edges(ev.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if e in (L | T, R | B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif e in (R | T, L | B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif e in (L, R):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif e in (T, B):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, ev):
        e = self._edges(ev.position().toPoint())
        if ev.button() == Qt.MouseButton.LeftButton and e != Qt.Edge(0):
            self.window().windowHandle().startSystemResize(e)


class FramelessWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowSystemMenuHint)
        self.root = _ResizeRoot(self)
        self.outer = QVBoxLayout(self.root)
        self.outer.setContentsMargins(1, 1, 1, 1)
        self.outer.setSpacing(0)
        self.titlebar = TitleBar(self.root)
        self.outer.addWidget(self.titlebar)
        self.setCentralWidget(self.root)
        self.titlebar.close_clicked.connect(self.close)
        self.titlebar.min_clicked.connect(self.showMinimized)
        self.titlebar.max_clicked.connect(self.toggle_max)

    def toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def setWindowTitle(self, text: str) -> None:
        super().setWindowTitle(text)
        self.titlebar.set_title(text)


class FramedDialog(QDialog):
    """Dialog with the same dark title bar and only the red button."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.titlebar = TitleBar(self, full=False)
        self.titlebar.set_title(title)
        self.titlebar.close_clicked.connect(self.reject)
        lay.addWidget(self.titlebar)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(10, 8, 10, 10)
        self.body.setSpacing(6)
        lay.addLayout(self.body, 1)
        super().setWindowTitle(title)
