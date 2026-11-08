"""Problem reports, the parts the user sees: the bar after a crash, Report a Problem, What's Sent, Report Sent."""
from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from . import reports
from .widgets import FramedDialog, icon


def _pic(win, name: str, colour: str, px: int = 16) -> QPixmap:
    from . import lucide
    pm = QPixmap.fromImage(lucide.image(name, colour, px * 2))
    pm.setDevicePixelRatio(2.0)
    return pm


class ProblemBar(QFrame):
    """Above the input box, the invite bar's look: "BChat closed unexpectedly last time. Send a report?"."""

    def __init__(self, win, parent=None):
        super().__init__(parent, objectName="invitebar")
        self.win = win
        self.offer: dict = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 6, 5)
        lay.setSpacing(10)
        self.pic = QLabel()
        lay.addWidget(self.pic)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        lay.addWidget(self.text, 1)
        self.later_btn = QPushButton("&Not now")
        self.later_btn.setAutoDefault(False)
        self.later_btn.setToolTip("Nothing is sent. Help > Report a Problem... works any time.")
        self.later_btn.clicked.connect(self.dismiss)
        self.send_btn = QPushButton(icon("send"), "Send &Report...")
        self.send_btn.setAutoDefault(False)
        self.send_btn.clicked.connect(self.open_report)
        lay.addWidget(self.later_btn)
        lay.addWidget(self.send_btn)
        self.hide()

    def show_offer(self, headline: str, kind: str = "Crashed", error: str = "", sig: str = "", freeze: float = 0.0) -> None:
        if not self.win.cfg.report_offer:
            return
        self.offer = {"kind": kind, "error": error, "sig": sig, "freeze": freeze}
        self.pic.setPixmap(_pic(self.win, "alert", self.win.cfg.theme.palette[7]))
        self.text.setText(f"{headline} <b>Send a report?</b> It takes one click.")
        self.show()

    def dismiss(self) -> None:
        self.offer = {}
        self.hide()

    def open_report(self) -> None:
        o, self.offer = self.offer, {}
        self.hide()
        self.win.report_problem(**o)


class ReportDialog(FramedDialog):
    def __init__(self, win, kind: str = "", error: str = "", sig: str = "", freeze: float = 0.0):
        super().__init__("BChat: Report a Problem", win)
        self.win = win
        self.error, self.sig, self.freeze = error, sig, freeze
        self.picture = b""
        self.resize(540, 300)
        self.body.addWidget(QLabel("<b>What happened?</b>"))
        row = QHBoxLayout()
        self.kinds = QButtonGroup(self)
        t = win.cfg.theme
        for word in reports.KINDS:
            b = QPushButton(word)
            b.setCheckable(True)
            b.setObjectName("compact")
            b.setStyleSheet(f"QPushButton:checked {{ border: 1px solid {t.check}; background: {t.thumb}; color: {t.check}; font-weight: bold; }}")
            b.setChecked(word == (kind or ""))
            self.kinds.addButton(b)
            row.addWidget(b)
        self.kinds.buttonToggled.connect(lambda *_: self._ready())
        self.body.addLayout(row)
        self.wrote = QLineEdit()
        self.wrote.setPlaceholderText("What were you doing? (optional)")
        self.wrote.setMaxLength(500)
        self.body.addWidget(self.wrote)
        opts = QHBoxLayout()
        self.shot = QCheckBox("Add a picture of BChat's window (it shows your chat)")
        self.shot.setToolTip("The picture shows the window exactly as it is now: nicks, channels and chat included.\n"
                             "Names can't be hidden in a picture. You see it in What's Sent before it goes.")
        opts.addWidget(self.shot)
        opts.addStretch(1)
        self.see = QLabel(f'<a style="color:{t.check}" href="#">See what\'s sent</a>')
        self.see.linkActivated.connect(lambda _: self.show_sent())
        opts.addWidget(self.see)
        self.body.addLayout(opts)
        self.note = QLabel("BChat adds the details for you. Never sent: what people said, passwords, IP addresses.\n"
                           "Nicks, channels and server names are replaced.")
        self.note.setStyleSheet(f"color: {t.muted};")
        self.body.addWidget(self.note)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.hide()
        self.body.addWidget(self.status)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cancel_btn = QPushButton(icon("close-light"), "&Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.send_btn = QPushButton(icon("send"), "&Send")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self.send)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.send_btn)
        self.body.addLayout(btns)
        self._ready()

    def kind(self) -> str:
        b = self.kinds.checkedButton()
        return b.text() if b is not None else ""

    def _ready(self) -> None:
        self.send_btn.setEnabled(bool(self.kind()))
        self.send_btn.setToolTip("" if self.kind() else "Pick what happened first")

    def _grab(self) -> bytes:
        """The main window only, never the rest of the screen."""
        pm = self.win.grab()
        if pm.width() > 1600:
            pm = pm.scaledToWidth(1600, Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pm.save(buf, "PNG")
        return bytes(data)

    def report(self) -> dict:
        if self.shot.isChecked() and not self.picture:
            self.picture = self._grab()
        return reports.build(self.win, self.kind() or "Something else", self.wrote.text(), self.error, self.sig,
                             self.freeze, self.picture if self.shot.isChecked() else b"")

    def show_sent(self) -> None:
        WhatsSentDialog(self.win, self.report(), self).exec()

    def send(self) -> None:
        if not self.kind():
            return
        r = self.report()
        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status.setText("Sending...")
        self.status.show()
        s = reports.Sender(self.win)
        s.done.connect(self._sent)
        s.failed.connect(self._failed)
        self.sender_ = s
        s.send(r)

    def _sent(self, ans: dict) -> None:
        self.accept()
        ThanksDialog(self.win, ans).exec()

    def _failed(self, why: str) -> None:
        self.status.setText(why)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("&Close")
        self.send_btn.setEnabled("saved" not in why)


class WhatsSentDialog(FramedDialog):
    def __init__(self, win, report: dict, parent=None):
        super().__init__("BChat: What's Sent", parent or win)
        self.resize(580, 560 if report.get("picture") else 380)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        self.text.setPlainText(reports.render(report))
        self.body.addWidget(self.text, 1)
        if report.get("picture"):
            pm = QPixmap()
            pm.loadFromData(base64.b64decode(report["picture"]))
            pic = QLabel()
            pic.setPixmap(pm.scaledToWidth(520, Qt.TransformationMode.SmoothTransformation))
            area = QScrollArea()
            area.setWidget(pic)
            area.setFixedHeight(180)
            warn = QLabel("The picture shows BChat's window as it is, with nicks, channels and chat. "
                          "Untick the picture if you'd rather not send that.")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {win.cfg.theme.palette[7]};")
            self.body.addWidget(warn)
            self.body.addWidget(area)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(icon("close-light"), "&Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.body.addLayout(row)


class ThanksDialog(FramedDialog):
    def __init__(self, win, ans: dict):
        super().__init__("BChat: Report Sent", win)
        self.resize(420, 160)
        t = win.cfg.theme
        top = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(_pic(win, "ready", t.join, 28))
        top.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        rid = str(ans.get("id", ""))
        seen = int(ans.get("seen", 1) or 1)
        others = {1: "You're the first to report this. It will be looked at,",
                  2: "1 other person hit this too. It's being looked at,"}.get(seen, f"{seen - 1} other people hit this too. It's being looked at,")
        self.words = QLabel(f"<span style='font-size:13pt'><b>Thank you!</b></span><br>Your report is <b>{rid}</b>.<br>"
                            f"<span style='color:{t.muted}'>{others}<br>and BChat tells you when an update fixes it.</span>")
        self.words.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.words, 1)
        self.body.addLayout(top)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("&OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        self.body.addLayout(row)
