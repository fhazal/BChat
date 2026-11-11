"""Invites: a slim bar above the input box with Join / Ignore. BChat never joins on an invite by itself
(anyone can send one, e.g. through ChanServ INVITE), so the person decides."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from .protocol import lower
from .widgets import icon

KEEP_SECONDS = 600        # an invite nobody answered goes away after 10 minutes
MAX_WAITING = 5


def _ago(seconds: float) -> str:
    m = int(seconds // 60)
    return "just now" if m < 1 else f"{m} min ago"


class InviteBar(QFrame):
    def __init__(self, win, parent=None):
        super().__init__(parent, objectName="invitebar")
        self.win = win
        self.waiting: list[dict] = []          # newest last: {"s", "chan", "nick", "ts"}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 6, 5)
        lay.setSpacing(10)
        self.pic = QLabel()
        lay.addWidget(self.pic)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.text, 1)
        self.ignore_btn = QPushButton("&Ignore")
        self.ignore_btn.setAutoDefault(False)
        self.ignore_btn.setToolTip("Forget this invite. Nothing is sent.")
        self.ignore_btn.clicked.connect(self.ignore)
        self.join_btn = QPushButton(icon("connect"), "&Join")
        self.join_btn.setAutoDefault(False)
        self.join_btn.clicked.connect(self.join)
        lay.addWidget(self.ignore_btn)
        lay.addWidget(self.join_btn)
        self._tick = QTimer(self, interval=30000, timeout=self.refresh)
        self.hide()

    # --- invites ------------------------------------------------------------------------

    def add(self, s, chan: str, nick: str) -> None:
        self.waiting = [w for w in self.waiting if not (w["s"] is s and lower(w["chan"]) == lower(chan))]
        self.waiting.append({"s": s, "chan": chan, "nick": nick, "ts": time.time()})
        del self.waiting[:-MAX_WAITING]
        self.refresh()

    def current(self) -> dict | None:
        return self.waiting[-1] if self.waiting else None

    def join(self) -> None:
        w = self.current()
        if w is None:
            return
        self.waiting.pop()
        s = w["s"]
        if s.state == "connected":
            s.focus_next = s.fold(w["chan"])
            s.send("JOIN", w["chan"])
        self.refresh()

    def ignore(self) -> None:
        if self.waiting:
            self.waiting.pop()
        self.refresh()

    def refresh(self) -> None:
        now = time.time()

        def still_wanted(w) -> bool:
            b = w["s"].buffers.get(w["s"].fold(w["chan"]))
            return now - w["ts"] < KEEP_SECONDS and w["s"].state == "connected" and not (b is not None and b.joined)
        self.waiting = [w for w in self.waiting if still_wanted(w)]
        w = self.current()
        if w is None:
            self._tick.stop()
            self.hide()
            return
        t = self.win.cfg.theme
        from .welcome import _pic
        self.pic.setPixmap(_pic("messages-square", t.check, 16, self.devicePixelRatioF()).pixmap())
        self.pic.setFixedSize(16, 16)
        net = w["s"].net.name or w["s"].server_name
        more = len(self.waiting) - 1
        extra = f" · {more} more" if more else ""
        self.text.setText(f"<b>{html.escape(w['nick'])}</b> invited you to <b>{html.escape(w['chan'])}</b> "
                          f"<span style='color:{t.muted}'>· {html.escape(net)} · {_ago(now - w['ts'])}{extra}</span>")
        self.join_btn.setToolTip(f"Join {w['chan']}")
        self.show()
        if not self._tick.isActive():
            self._tick.start()
