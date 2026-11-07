"""Help > About: XChat 2's About layout in BChat's dark theme, with the user's bee mascot (mockup-about-bee.png, OK'd 2026-11-07)."""
from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import full_version
from .widgets import ASSETS, FramedDialog, icon

TAGLINE = "Handle IRC as a bee does a flower"
SITE = "https://bajubesi.org"
SUPPORT = "https://ko-fi.com/bajubesi"   # the owner's Ko-fi: a quiet link, never a popup
MASCOT_WIDTH = 120     # the bee keeps its headset B and "chat" sign readable at this size


def built_on() -> str:
    """A build shows the day its exe was made; running from source says so."""
    if getattr(sys, "frozen", False):
        try:
            return datetime.fromtimestamp(Path(sys.executable).stat().st_mtime).strftime("%b %d %Y")
        except OSError:
            return "unknown"
    return "source"


def windows_name() -> str:
    build = platform.version().split(".")[-1]
    try:
        if platform.system() == "Windows" and int(build) >= 22000:
            return f"11 (build {build})"      # Windows 11 still reports release "10" on older Pythons
    except ValueError:
        pass
    return f"{platform.release()} (build {build})" if build else platform.release()


def info_rows() -> list[tuple[str, str]]:
    return [("Version", full_version()),
            ("Built", built_on()),
            ("Windows", windows_name()),
            ("Processors", str(os.cpu_count() or "?")),
            ("Python / Qt", f"{platform.python_version()} / {pyside_version}")]


class AboutDialog(FramedDialog):
    def __init__(self, theme, parent=None):
        super().__init__("About BChat", parent)
        self.body.setContentsMargins(22, 18, 22, 14)
        self.body.setSpacing(0)

        top = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addStretch(1)
        self.name = QLabel("BChat")
        self.name.setStyleSheet(f"color: {theme.title}; font-size: 22pt; font-weight: bold;")
        words.addWidget(self.name)
        self.tagline = QLabel(TAGLINE)
        f = QFont(self.tagline.font())
        f.setBold(True)
        self.tagline.setFont(f)
        self.tagline.setStyleSheet(f"color: {theme.muted};")
        words.addWidget(self.tagline)
        words.addStretch(1)
        top.addLayout(words, 1)
        self.logo = QLabel()
        dpr = self.devicePixelRatioF()
        src = QPixmap(str(ASSETS / "bee.png"))
        pm = src.scaledToWidth(int(MASCOT_WIDTH * dpr), Qt.TransformationMode.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.logo.setPixmap(pm)
        self.logo.setFixedSize(MASCOT_WIDTH, round(pm.height() / dpr))
        top.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(top)
        self.body.addSpacing(16)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        self.values: dict[str, QLabel] = {}
        for i, (k, v) in enumerate(info_rows()):
            a = QLabel(k + ":")
            fa = QFont(a.font())
            fa.setBold(True)
            a.setFont(fa)
            a.setStyleSheet(f"color: {theme.text};")
            b = QLabel(v)
            b.setStyleSheet(f"color: {theme.motd_text};")
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)   # copy for a bug report
            grid.addWidget(a, i, 0)
            grid.addWidget(b, i, 1)
            self.values[k] = b
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        self.body.addSpacing(16)

        small = QFont(self.tagline.font())
        small.setBold(False)
        small.setPointSize(max(7, small.pointSize() - 1))
        for text in ("Copyright © 2026 BajuBesi Labs.", "Icons: Lucide (ISC)."):
            lab = QLabel(text)
            lab.setFont(small)
            lab.setStyleSheet(f"color: {theme.muted};")
            self.body.addWidget(lab)
        self.body.addSpacing(10)
        self.link = QLabel(f'<a style="color: {theme.check};" href="{SITE}">bajubesi.org</a>')
        self.link.setOpenExternalLinks(True)
        self.link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.body.addWidget(self.link, 0, Qt.AlignmentFlag.AlignLeft)
        self.body.addSpacing(6)
        support = QHBoxLayout()
        support.setSpacing(6)
        from . import lucide
        dpr = self.devicePixelRatioF()
        heart = QPixmap.fromImage(lucide.image("heart", theme.title, round(14 * dpr)))
        heart.setDevicePixelRatio(dpr)
        self.heart = QLabel()
        self.heart.setPixmap(heart)
        self.heart.setFixedSize(14, 14)
        support.addWidget(self.heart, 0, Qt.AlignmentFlag.AlignVCenter)
        self.support = QLabel(f'BChat is free and has no ads. <a style="color: {theme.check};" href="{SUPPORT}">Support it on Ko-fi</a>')
        self.support.setStyleSheet(f"color: {theme.muted};")
        self.support.setOpenExternalLinks(True)
        self.support.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        support.addWidget(self.support, 1)
        self.body.addLayout(support)
        self.body.addSpacing(14)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {theme.border};")
        self.body.addWidget(line)
        self.body.addSpacing(10)
        row = QHBoxLayout()
        row.addStretch(1)
        self.close_btn = QPushButton(icon("close-light"), "&Close")
        self.close_btn.setDefault(True)
        self.close_btn.setMinimumWidth(110)
        self.close_btn.clicked.connect(self.accept)
        row.addWidget(self.close_btn)
        self.body.addLayout(row)
        self.setFixedWidth(380)

    def text(self) -> str:
        """Everything the window says, for tests and a quick copy."""
        rows = "\n".join(f"{k}: {v.text()}" for k, v in self.values.items())
        return (f"BChat\n{TAGLINE}\n{rows}\nCopyright © 2026 BajuBesi Labs.\nIcons: Lucide (ISC).\n{self.link.text()}\n"
                f"{self.support.text()}")
