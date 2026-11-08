"""Add a friend, like XChat's notify window: the nick, and the networks to watch (ALL = every network)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from .widgets import FramedDialog, icon

ALL = "ALL"


def nets_from_text(text: str) -> str:
    """What the box says -> what is saved: "" for every network (ALL or empty), else a tidy comma list."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts or any(p.upper() == ALL for p in parts):
        return ""
    return ", ".join(parts)


class FriendDialog(FramedDialog):
    def __init__(self, win, nick: str = "", nets: str = ""):
        super().__init__("Add to Friends List", win)
        t = win.cfg.theme
        self.setFixedWidth(460)
        self.body.setContentsMargins(18, 14, 18, 12)
        self.body.setSpacing(8)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.nick = QLineEdit(nick)
        self.nick.setMaxLength(64)
        self.nets = QLineEdit(nets or ALL)
        lab1, lab2 = QLabel("&Nickname to add:"), QLabel("Notify on these net&works:")
        lab1.setBuddy(self.nick)
        lab2.setBuddy(self.nets)
        g.addWidget(lab1, 0, 0, Qt.AlignmentFlag.AlignRight)
        g.addWidget(self.nick, 0, 1)
        g.addWidget(lab2, 1, 0, Qt.AlignmentFlag.AlignRight)
        g.addWidget(self.nets, 1, 1)
        hint = QLabel("ALL for every network, or a comma separated list of network names.")
        hint.setStyleSheet(f"color: {t.muted}; font-size: 7pt;")
        hint.setWordWrap(True)
        g.addWidget(hint, 2, 1)
        self.body.addLayout(g)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(sep)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton(icon("cancel"), "&Cancel")
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton(icon("done"), "&OK")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        self.body.addLayout(row)
        self.nick.textChanged.connect(lambda s: self.ok_btn.setEnabled(bool(s.strip())))     # several nicks: spaces between
        self.ok_btn.setEnabled(bool(nick.strip()))
        self.nick.selectAll()
        self.nick.setFocus()

    def result_values(self) -> tuple[str, str]:
        return self.nick.text().strip(), nets_from_text(self.nets.text())
