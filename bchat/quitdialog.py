"""The popup before leaving: Minimize to Tray, Cancel or Quit. Cancel is the default, so a stray Enter disconnects nobody."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSystemTrayIcon, QVBoxLayout

from .widgets import FramedDialog, icon


class QuitDialog(FramedDialog):
    def __init__(self, parent, networks: int):
        super().__init__("Quit BChat?", parent)
        self.choice = "cancel"
        self.body.setContentsMargins(18, 16, 18, 14)
        self.body.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(16)
        pic = QLabel()
        t = parent.cfg.theme
        from . import lucide
        dpr = self.devicePixelRatioF()
        warn = QPixmap.fromImage(lucide.image("triangle-alert", t.highlight, round(48 * dpr)))
        warn.setDevicePixelRatio(dpr)
        pic.setPixmap(warn)
        pic.setFixedSize(48, 48)
        top.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(6)
        head = QLabel("Are you sure you want to quit?")
        f = QFont(head.font())
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        head.setFont(f)
        words.addWidget(head)
        self.count = QLabel(f"You are connected to {networks} IRC network{'' if networks == 1 else 's'}.")
        words.addWidget(self.count)
        top.addLayout(words, 1)
        self.body.addLayout(top)
        self.dont_ask = QCheckBox("Don't ask next time")
        self.body.addWidget(self.dont_ask)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.tray_btn = QPushButton("&Minimize to Tray")
        self.tray_btn.setAutoDefault(False)
        self.tray_btn.clicked.connect(lambda _=False: self._pick("tray"))
        self.tray_btn.setVisible(QSystemTrayIcon.isSystemTrayAvailable())
        row.addWidget(self.tray_btn)
        row.addStretch(1)
        self.cancel_btn = QPushButton(icon("close-light"), "&Cancel")
        self.cancel_btn.setDefault(True)
        self.cancel_btn.clicked.connect(lambda _=False: self._pick("cancel"))
        row.addWidget(self.cancel_btn)
        self.quit_btn = QPushButton(icon("quit"), "&Quit")
        self.quit_btn.setAutoDefault(False)
        self.quit_btn.clicked.connect(lambda _=False: self._pick("quit"))
        row.addWidget(self.quit_btn)
        self.body.addLayout(row)
        self.setFixedWidth(430)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def ask(self) -> tuple[str, bool]:
        """(quit, tray or cancel; don't ask next time). The red button and Esc are Cancel."""
        self.cancel_btn.setFocus()
        self.exec()
        return self.choice, self.dont_ask.isChecked()
