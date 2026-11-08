"""irc:// and ircs:// links: read them, and ask before joining (never joins on its own: links can come from anyone)."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .widgets import FramedDialog, icon

TLS_PORTS = {6697, 7000, 7070, 9999}     # usual encrypted ports, for irc:// links that point at one


@dataclass
class IrcLink:
    host: str
    port: int
    tls: bool
    channels: list[str] = field(default_factory=list)
    key: str = ""

    @property
    def what(self) -> str:
        return self.channels[0] if self.channels else self.host


def parse_irc_url(url: str) -> IrcLink | None:
    """irc://host[:port]/[#]channel[,needkey][?key=...]  and ircs://...  None when it isn't a usable link."""
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return None
    scheme = u.scheme.lower()
    if scheme not in ("irc", "ircs") or not u.hostname:
        return None
    host = u.hostname.lower()
    if any(c in host for c in " /\\@") or "." not in host and host != "localhost":
        return None
    try:
        port = u.port
    except ValueError:
        return None
    tls = scheme == "ircs" or (port in TLS_PORTS)
    port = port or (6697 if tls else 6667)
    path = unquote(u.path.lstrip("/")) + (("#" + unquote(u.fragment)) if u.fragment else "")
    if any(w in path.lower().split(",") for w in ("isnick", "isuser")):
        return IrcLink(host, port, tls)                  # a link to a person: just the server
    chans = []
    for part in path.split(","):
        part = part.strip()
        if not part or part.lower() in ("needkey", "isnick", "isuser", "isserver", "needpass"):
            continue
        if part[0] not in "#&+!":
            part = "#" + part
        if any(c in part for c in " \x07\r\n\x00") or len(part) > 64:
            return None
        chans.append(part)
    key = ""
    for kv in u.query.split("&"):
        k, _, v = kv.partition("=")
        if k.lower() == "key":
            key = unquote(v)
    return IrcLink(host, port, tls, chans[:1], key)


def _pic(name: str, colour: str, size: int, dpr: float) -> QLabel:
    from .welcome import _pic as pic
    return pic(name, colour, size, dpr)


class IrcLinkDialog(FramedDialog):
    """Join #chan? Network card says what will happen; the badge on the left says if the link is encrypted."""

    def __init__(self, win, link: IrcLink, net_name: str, line: str):
        super().__init__("Open IRC Link", win)
        self.link = link
        self.choice = ""
        t = win.cfg.theme
        self.setFixedWidth(470)
        self.body.setContentsMargins(22, 18, 22, 16)
        self.body.setSpacing(14)
        dpr = self.devicePixelRatioF()
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(_pic("messages-square", t.check, 26, dpr), 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.head = QLabel(f"Join {link.channels[0]}" if link.channels else f"Connect to {link.host}")
        self.head.setTextFormat(Qt.TextFormat.PlainText)
        self.head.setStyleSheet(f"color: {t.title}; font-size: 12pt; font-weight: bold;")
        sub = QLabel("Someone shared a link to this channel." if link.channels else "Someone shared a link to this server.")
        sub.setStyleSheet(f"color: {t.muted};")
        words.addWidget(self.head)
        words.addWidget(sub)
        top.addLayout(words, 1)
        self.body.addLayout(top)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(f"#card {{ border: 1px solid {t.border}; border-radius: 6px; background: {t.panel}; }}")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(12)
        cl.addWidget(_pic("server", t.text, 22, dpr), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel(net_name)
        name.setTextFormat(Qt.TextFormat.PlainText)
        f = QFont(name.font())
        f.setBold(True)
        name.setFont(f)
        row.addWidget(name)
        addr = link.host if net_name.lower() != link.host else ""
        addr = " · ".join(x for x in (addr, str(link.port)) if x)
        self.addr = QLabel(addr)
        self.addr.setTextFormat(Qt.TextFormat.PlainText)
        self.addr.setStyleSheet(f"color: {t.muted}; font-size: 8pt;")
        row.addWidget(self.addr)
        row.addStretch(1)
        col.addLayout(row)
        self.line = QLabel(line)
        self.line.setTextFormat(Qt.TextFormat.PlainText)
        self.line.setWordWrap(True)
        self.line.setStyleSheet(f"color: {t.muted};")
        col.addWidget(self.line)
        cl.addLayout(col, 1)
        self.body.addWidget(card)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {t.border};")
        self.body.addWidget(sep)
        row = QHBoxLayout()
        row.setSpacing(8)
        colour = t.join if link.tls else t.status_lag
        row.addWidget(_pic("shield-check" if link.tls else "shield-alert", colour, 16, dpr), 0, Qt.AlignmentFlag.AlignVCenter)
        self.lock = QLabel("Encrypted" if link.tls else "Not encrypted")
        self.lock.setStyleSheet(f"color: {colour}; font-weight: bold;")
        self.lock.setToolTip("The connection to this server is encrypted with SSL/TLS." if link.tls else
                             "This server link has no SSL/TLS: what you write travels unencrypted.")
        row.addWidget(self.lock)
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        self.join_btn = QPushButton(icon("connect"), "&Join" if link.channels else "&Connect")
        self.join_btn.setDefault(True)
        self.join_btn.clicked.connect(self._join)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.join_btn)
        self.body.addLayout(row)

    def _join(self) -> None:
        self.choice = "join"
        self.accept()
