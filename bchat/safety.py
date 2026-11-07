"""Two safety windows, built like the quit popup (mockup-safety.png, OK'd 2026-11-08):
the certificate question, and the warning before opening a risky link. Plus the check that decides a link is risky."""
from __future__ import annotations

import ipaddress
import re

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QFont, QGuiApplication, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import lucide
from .widgets import FramedDialog, icon

from .filetypes import PROGRAM_TYPES      # one list for links and DCC


def link_risk(url: str) -> str:
    """Why this link deserves a second look, or "" for an ordinary link (those open with one click)."""
    u = QUrl(url if "://" in url else "http://" + url)
    host = u.host().lower()
    path = u.path().lower()
    ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if ext in PROGRAM_TYPES:
        return f"This link downloads a program (.{ext})"
    if u.userName() or "@" in url.split("://", 1)[-1].split("/", 1)[0]:
        return "This link hides where it really goes (a name@ before the site)"
    if any(part.startswith("xn--") for part in host.split(".")) or any(ord(ch) > 127 for ch in host):
        return "This site's name uses look-alike letters"
    try:
        ipaddress.ip_address(host.strip("[]"))
        return "This link goes to a bare internet address, not a named site"
    except ValueError:
        pass
    return ""


def _pic(name: str, colour: str, size: int, dpr: float) -> QLabel:
    pm = QPixmap.fromImage(lucide.image(name, colour, round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    lab = QLabel()
    lab.setPixmap(pm)
    lab.setFixedSize(size, size)
    return lab


class _Ask(FramedDialog):
    """Icon left, bold question, words, a line, buttons: the quit popup's shape."""

    def __init__(self, parent, title: str, icon_name: str, question: str):
        super().__init__(title, parent)
        self.t = parent.cfg.theme
        self.choice = ""
        self.setFixedWidth(470)
        self.body.setContentsMargins(18, 16, 18, 14)
        self.body.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(_pic(icon_name, self.t.highlight, 40, self.devicePixelRatioF()), 0, Qt.AlignmentFlag.AlignTop)
        self.words = QVBoxLayout()
        self.words.setSpacing(8)
        self.question = QLabel(question)
        self.question.setWordWrap(True)
        f = QFont(self.question.font())
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        self.question.setFont(f)
        self.words.addWidget(self.question)
        top.addLayout(self.words, 1)
        self.body.addLayout(top)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {self.t.border};")
        self.body.addWidget(line)
        self.row = QHBoxLayout()
        self.row.setSpacing(8)
        self.body.addLayout(self.row)

    def text(self, s: str, muted: bool = False) -> QLabel:
        lab = QLabel(s)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if muted:
            lab.setStyleSheet(f"color: {self.t.muted};")
        self.words.addWidget(lab)
        return lab

    def button(self, text: str, choice: str, ico: str = "", default: bool = False) -> QPushButton:
        b = QPushButton(icon(ico), text) if ico else QPushButton(text)
        b.setAutoDefault(False)
        b.setDefault(default)
        b.clicked.connect(lambda: self._pick(choice))
        self.row.addWidget(b)
        return b

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class CertDialog(_Ask):
    def __init__(self, parent, info: dict):
        host = info.get("host") or info.get("network", "")
        q = f"{host}'s certificate has changed" if info.get("changed") else f"BChat can't verify {host}"
        super().__init__(parent, "BChat: Check this server", "shield-alert", q)
        self.info = info
        why = "it wasn't issued by a known authority (self-signed)" if info.get("self_signed") else "; ".join(info.get("reasons", []))
        if info.get("changed"):
            self.text(f"{info.get('network')} now sends a different certificate from the one you trusted. "
                      f"This one {why.replace('it wasn', 'wasn')}." if why.startswith("it wasn") else
                      f"{info.get('network')} now sends a different certificate from the one you trusted ({why}).")
        else:
            self.text(f"{info.get('network')} sent a certificate BChat can't verify: {why}.")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(3)
        fp = info.get("fingerprint", "").upper()
        pretty = ":".join(fp[i:i + 2] for i in range(0, len(fp), 2))
        short = pretty[:23] + " ... " + pretty[-11:] if len(pretty) > 40 else pretty
        rows = [("Issued to:", info.get("subject") or "?"), ("Issued by:", (info.get("issuer") or "?") + (" (itself)" if info.get("self_signed") else "")),
                ("Valid until:", info.get("expires") or "?"), ("Fingerprint:", short)]
        for i, (k, v) in enumerate(rows):
            a = QLabel(k)
            a.setStyleSheet(f"color: {self.t.muted};")
            b = QLabel(v)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if k == "Fingerprint:":
                b.setStyleSheet("font-family: Consolas; font-size: 8pt;")
                b.setToolTip(pretty)
            g.addWidget(a, i, 0, Qt.AlignmentFlag.AlignTop)
            g.addWidget(b, i, 1)
        g.setColumnStretch(1, 1)
        self.words.addLayout(g)
        if info.get("changed"):
            self.text("A certificate can change when a network renews it, but this is also what it looks like when "
                      "someone gets between you and the server. If you're not sure, ask the network first.", muted=True)
        else:
            self.text("Many small IRC networks make their own certificates, and that's fine if you trust the network. "
                      "If you didn't expect this, someone could be listening in.", muted=True)
        self.no_btn = self.button("&Don't Connect", "no", "close-light", default=True)
        self.row.addStretch(1)
        self.once_btn = self.button("Connect &Once", "once")
        self.always_btn = self.button("&Always Trust", "always")


class LinkDialog(_Ask):
    def __init__(self, parent, url: str, reason: str, who: str = "", where: str = ""):
        super().__init__(parent, "BChat: Open this link?", "link-2", reason)
        self.url = url
        u = QUrl(url if "://" in url else "http://" + url)
        host = u.host()
        rest = url.split(host, 1)[-1] if host and host in url else ""
        link = self.text(f"<b>{_esc(host)}</b>{_esc(rest)}")
        link.setTextFormat(Qt.TextFormat.RichText)
        warn = QHBoxLayout()
        warn.setSpacing(6)
        warn.addWidget(_pic("triangle-alert", self.t.marker, 16, self.devicePixelRatioF()), 0, Qt.AlignmentFlag.AlignTop)
        frm = f"From {who} in {where}. " if who and where else (f"From {who}. " if who else "")
        self.why = QLabel(frm + "Links like this can harm your PC. Only open it if you trust the person and expected it.")
        self.why.setWordWrap(True)
        self.why.setStyleSheet(f"color: {self.t.muted};")
        warn.addWidget(self.why, 1)
        self.words.addLayout(warn)
        self.cancel_btn = self.button("&Cancel", "cancel", "close-light", default=True)
        self.row.addStretch(1)
        self.copy_btn = self.button("&Copy Link", "copy", "copy")
        self.open_btn = self.button("&Open", "open")

    def _pick(self, choice: str) -> None:
        if choice == "copy":
            QGuiApplication.clipboard().setText(self.url)
        super()._pick(choice)


class ProgramDialog(_Ask):
    """Before accepting a program over DCC (mockup-dcc-warning.png, OK'd 2026-11-08). Cancel leaves the offer waiting."""

    def __init__(self, parent, name: str, size: int, who: str, network: str):
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        super().__init__(parent, "BChat: Accept this file?", "file-warning", f"This file is a program (.{ext})")
        self.setWindowTitle("BChat: Accept this file?")
        label = self.text(f"<b>{_esc(name)}</b> \u00b7 {_size(size)}")
        label.setTextFormat(Qt.TextFormat.RichText)
        warn = QHBoxLayout()
        warn.setSpacing(6)
        warn.addWidget(_pic("triangle-alert", self.t.marker, 16, self.devicePixelRatioF()), 0, Qt.AlignmentFlag.AlignTop)
        frm = f"From {who} on {network}. " if network else f"From {who}. "
        self.why = QLabel(frm + "Programs can harm your PC. Only accept it if you trust the person and expected it.")
        self.why.setWordWrap(True)
        self.why.setStyleSheet(f"color: {self.t.muted};")
        warn.addWidget(self.why, 1)
        self.words.addLayout(warn)
        self.text("If you accept, Windows will check it before it runs, like a browser download.", muted=True)
        self.cancel_btn = self.button("&Cancel", "cancel", "close-light", default=True)
        self.row.addStretch(1)
        self.accept_btn = self.button("&Accept", "accept")


def _size(n: int) -> str:
    for unit, step in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} bytes"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
