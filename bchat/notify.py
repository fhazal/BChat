"""BChat's own pop-up notifications above the taskbar (mockup-notify-v2.png, OK'd 2026-11-08).

Calm and flood-safe:
- one card per person per chat: more lines from them update it and count up (+N)
- at most MAX_CARDS cards; anything past that, or arriving faster than one new card a second,
  goes into one summary card ("N more messages from M people")
- only the first MAX_CHARS characters are read, colours and control codes removed, two lines shown
- nothing while Windows says the user is busy (full-screen game, presentation, Do Not Disturb)
- cards never take keyboard focus
"""
from __future__ import annotations

import ctypes
import os
import re
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from . import lucide

W, H = 316, 66          # the card, in points
PAD = 10                # shadow room around it
RIGHT, BOTTOM = 7, 4    # gap from the screen's right edge and the taskbar: where AdiIRC puts its balloon
GAP = 8                 # between stacked cards
SHOW_MS = 6000          # the default; Preferences > Alerts 'Keep pop-ups on screen for' sets Notifier.show_ms (0 = until closed)
# 0.5.0 card kinds: stripe colour (a theme field) and Lucide icon
ACCENT = {"priv": "join", "hilight": "highlight", "chan": "new_highlight", "many": "new_highlight", "kicked": "status_off",
          "disconnect": "status_off", "friend": "join", "invite": "new_highlight", "dcc": "new_highlight", "notice": "highlight"}
ICON = {"priv": "message-circle", "hilight": "at-sign", "chan": "hash", "many": "messages-square", "kicked": "ban",
        "disconnect": "unplug", "friend": "arrow-right", "invite": "send", "dcc": "download", "notice": "info"}
MAX_CARDS = 3
MIN_NEW_MS = 1000
MAX_CHARS = 300
_FORMAT = re.compile(r"\x03\d{0,2}(,\d{1,2})?|\x04[0-9a-fA-F]{0,6}(,[0-9a-fA-F]{6})?|[\x02\x0f\x11\x16\x1d\x1e\x1f]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")      # tabs, line breaks and anything else odd: a space


def clean(text: str) -> str:
    """First MAX_CHARS characters, mIRC colours and control codes gone, runs of spaces folded."""
    return " ".join(_CONTROL.sub(" ", _FORMAT.sub("", text[:MAX_CHARS])).split())


def windows_busy() -> bool:
    """Full-screen game or video, presentation mode, Do Not Disturb / quiet time, or the screen is locked."""
    if os.name != "nt":
        return False
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        return state.value in (1, 2, 3, 4, 6)   # not present, busy, D3D full screen, presentation, quiet time
    except (AttributeError, OSError):
        return False


class Card(QWidget):
    clicked = Signal(object)    # the card
    closed = Signal(object)

    def __init__(self, theme, kind: str, key, nick: str, where: str, text: str):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setFixedSize(W + 2 * PAD, H + 2 * PAD)
        self.theme, self.kind, self.key = theme, kind, key
        self.nick, self.where, self.text = nick, where, text
        self.when = time.strftime("%I:%M %p").lstrip("0")
        self.count = 0
        self.hover = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.show_ms = SHOW_MS
        self.timer.start(SHOW_MS)

    def update_text(self, text: str, more: int = 1) -> None:
        self.text, self.count = text, self.count + more
        self.when = time.strftime("%I:%M %p").lstrip("0")
        if not self.hover:
            self._restart()
        self.update()

    def set_time(self, ms: int) -> None:
        """How long it stays: ms, or 0 = until it is closed or clicked."""
        self.show_ms = ms
        self._restart()

    def _restart(self) -> None:
        if self.show_ms:
            self.timer.start(self.show_ms)
        else:
            self.timer.stop()

    def dismiss(self) -> None:
        self.timer.stop()
        self.hide()
        self.closed.emit(self)

    def _close_box(self) -> QRectF:
        return QRectF(PAD + W - 28, PAD + 6, 22, 22)

    def enterEvent(self, ev) -> None:
        self.hover = True
        self.timer.stop()
        self.update()

    def leaveEvent(self, ev) -> None:
        self.hover = False
        if self.show_ms:
            self.timer.start(self.show_ms // 2)
        self.update()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return self.dismiss()
        if self._close_box().contains(ev.position()):
            return self.dismiss()
        self.clicked.emit(self)

    def lines(self, fm: QFontMetrics, width: float) -> list[str]:
        """Two lines at most: wrap by words, then cut the second line with an ellipsis."""
        words, out, cur = self.text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if fm.horizontalAdvance(trial) <= width or not cur:
                cur = trial
            else:
                out.append(cur)
                cur = w
                if len(out) == 2:
                    break
        if len(out) < 2 and cur:
            out.append(cur)
        out = [fm.elidedText(x, Qt.TextElideMode.ElideRight, int(width)) for x in out[:2]]
        if len(out) == 2 and " ".join(out) != " ".join(words):
            out[1] = fm.elidedText(out[1] + " " + " ".join(words), Qt.TextElideMode.ElideRight, int(width))
        return out

    def paintEvent(self, _ev) -> None:
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for i in range(8, 0, -1):                       # soft shadow
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(5 + (8 - i) * 1.5)))
            p.drawRoundedRect(QRectF(PAD - i * 0.5, PAD + 2 - i * 0.3, W + i, H + i * 0.8), 9, 9)
        r = QRectF(PAD, PAD, W, H)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setBrush(QColor(t.popup if self.hover else t.panel))
        p.setPen(QColor(t.border))
        p.drawPath(path)
        accent = getattr(t, ACCENT.get(self.kind, "new_highlight"))
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent))
        p.drawRect(QRectF(r.left(), r.top(), 3, H))
        p.restore()
        bubble = QColor(accent)
        bubble.setAlpha(40)
        p.setBrush(bubble)
        p.drawEllipse(QPointF(r.left() + 25, r.top() + 22), 13, 13)
        dpr = self.devicePixelRatioF()
        name = ICON.get(self.kind, "messages-square")
        im = lucide.image(name, accent, round(16 * dpr))
        im.setDevicePixelRatio(dpr)
        p.drawImage(QPointF(r.left() + 17, r.top() + 14), im)
        x = r.left() + 46
        right = r.right() - 10
        f = QFont("Segoe UI", 9)
        f.setBold(True)
        small = QFont("Segoe UI", 8)
        fs = QFontMetrics(small)
        # the right side of the header: x on hover, else a +N count or the time
        if self.hover:
            xi = lucide.image("x", t.muted, round(14 * dpr))
            xi.setDevicePixelRatio(dpr)
            p.drawImage(QPointF(right - 14, r.top() + 10), xi)
            used = 20
        elif self.count:
            badge = f"+{self.count}"
            bw = fs.horizontalAdvance(badge) + 12
            p.setPen(Qt.PenStyle.NoPen)
            bc = QColor(accent)
            bc.setAlpha(60)
            p.setBrush(bc)
            p.drawRoundedRect(QRectF(right - bw, r.top() + 9, bw, 16), 8, 8)
            p.setPen(QColor(t.text))
            p.setFont(small)
            p.drawText(QRectF(right - bw, r.top() + 9, bw, 16), Qt.AlignmentFlag.AlignCenter, badge)
            used = bw + 6
        else:
            p.setPen(QColor(t.muted))
            p.setFont(small)
            p.drawText(QPointF(right - fs.horizontalAdvance(self.when), r.top() + 21), self.when)
            used = fs.horizontalAdvance(self.when) + 6
        head_w = right - used - x
        fm = QFontMetrics(f)
        nick = fm.elidedText(self.nick, Qt.TextElideMode.ElideRight, int(head_w * 0.6))
        p.setFont(f)
        p.setPen(QColor(t.nick))
        p.drawText(QPointF(x, r.top() + 21), nick)
        nx = x + fm.horizontalAdvance(nick) + 6
        p.setFont(small)
        p.setPen(QColor(t.muted))
        p.drawText(QPointF(nx, r.top() + 21), fs.elidedText(self.where, Qt.TextElideMode.ElideRight, int(x + head_w - nx)))
        body = QFont("Segoe UI", 9)
        p.setFont(body)
        p.setPen(QColor(t.text))
        for i, line in enumerate(self.lines(QFontMetrics(body), right - x)):
            p.drawText(QPointF(x, r.top() + 41 + i * 16), line)
        p.end()


class Notifier(QWidget):
    """Owns the cards: places them above the taskbar and applies the flood rules."""
    open_requested = Signal(object)    # the buffer to show, or None for "just open BChat"

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.hide()
        self.theme = theme
        self.cards: list[Card] = []
        self.summary: Card | None = None
        self.held = 0
        self.held_from: set[str] = set()
        self.last_new = 0.0
        self.show_ms: int | None = None      # None = SHOW_MS; MainWindow sets it from Preferences
        self.busy = windows_busy
        self.buffers: dict[int, object] = {}

    def notify(self, kind: str, buffer, key, nick: str, where: str, text: str) -> str:
        """'new' when a card came up, 'more' when a card or the summary counted up, '' when nothing showed."""
        if self.busy():
            return ""
        text = clean(text)
        for c in self.cards:
            if c.key == key and c.isVisible():
                c.update_text(text)
                return "more"
        now = time.monotonic()
        if len(self.cards) >= MAX_CARDS or (now - self.last_new) * 1000 < MIN_NEW_MS:
            self._hold(nick)
            return "more"
        self.last_new = now
        c = Card(self.theme, kind, key, nick, where, text)
        c.set_time(SHOW_MS if self.show_ms is None else self.show_ms)
        self.buffers[id(c)] = buffer
        c.clicked.connect(self._clicked)
        c.closed.connect(self._closed)
        self.cards.append(c)
        self._place()
        c.show()
        return "new"

    def _hold(self, nick: str) -> None:
        self.held += 1
        self.held_from.add(nick.lower())
        people = len(self.held_from)
        title = f"{self.held} more message{'s' if self.held != 1 else ''}"
        where = f"from {people} {'person' if people == 1 else 'people'}"
        if self.summary is None:
            self.summary = Card(self.theme, "many", "summary", title, where, "BChat is holding them. Click to open BChat.")
            self.summary.set_time(SHOW_MS if self.show_ms is None else self.show_ms)
            self.summary.clicked.connect(self._clicked)
            self.summary.closed.connect(self._closed)
            self._place()
            self.summary.show()
        else:
            self.summary.nick, self.summary.where = title, where
            self.summary._restart() if not self.summary.hover else None
            self.summary.update()

    def _clicked(self, card: Card) -> None:
        buf = self.buffers.get(id(card))
        card.dismiss()
        self.open_requested.emit(buf)

    def _closed(self, card: Card) -> None:
        if card is self.summary:
            self.summary, self.held = None, 0
            self.held_from.clear()
        elif card in self.cards:
            self.cards.remove(card)
            self.buffers.pop(id(card), None)
        card.deleteLater()
        self._place()

    def clear(self) -> None:
        for c in [*self.cards, *([self.summary] if self.summary else [])]:
            c.dismiss()

    def _place(self) -> None:
        """Summary at the bottom, then cards upwards in the order they came, right edge and bottom where AdiIRC's
        balloon sits. availableGeometry leaves out the taskbar, wherever it is."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        bottom = area.bottom() + 1 - BOTTOM
        for c in [*([self.summary] if self.summary else []), *self.cards]:
            c.move(area.right() + 1 - RIGHT - W - PAD, bottom - H - PAD)
            bottom -= H + GAP
