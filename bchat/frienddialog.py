"""Add or edit a friend, like XChat's notify window: the nick and the networks to watch (ALL = every network).
0.5.0: a note (the same one as the person's Address Book card) and, per friend, what happens when they come online
or leave: a pop-up, a sound, a WHOIS."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from .widgets import FramedDialog, icon

ALL = "ALL"


def nets_from_text(text: str) -> str:
    """What the box says -> what is saved: "" for every network (ALL or empty), else a tidy comma list."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts or any(p.upper() == ALL for p in parts):
        return ""
    return ", ".join(parts)


def friend_defaults(cfg) -> dict:
    """What a friend gets when nothing was set for them: pop-up on, sound off, WHOIS as the old global tick."""
    return {"popup": True, "sound": False, "sound_file": "", "whois": bool(cfg.whois_on_notify)}


class FriendDialog(FramedDialog):
    def __init__(self, win, nick: str = "", nets: str = "", edit: bool = False, note: str = "", opts: dict | None = None):
        super().__init__(f"Friend: {nick}" if edit else "Add to Friends List", win)
        t = win.cfg.theme
        self.win = win
        self.editing = edit
        o = {**friend_defaults(win.cfg), **(opts or {})}
        self.setFixedWidth(470)
        self.body.setContentsMargins(18, 14, 18, 12)
        self.body.setSpacing(8)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.nick = QLineEdit(nick)
        self.nick.setMaxLength(64)
        self.nick.setReadOnly(edit)                 # editing: the nick is the friend; remove + add to change it
        self.nets = QLineEdit(nets or ALL)
        self.note = QLineEdit(note)
        self.note.setMaxLength(300)
        lab1, lab2, lab3 = QLabel("&Nickname:" if edit else "&Nickname to add:"), QLabel("Notify on these net&works:"), QLabel("N&ote:")
        lab1.setBuddy(self.nick)
        lab2.setBuddy(self.nets)
        lab3.setBuddy(self.note)
        g.addWidget(lab1, 0, 0, Qt.AlignmentFlag.AlignRight)
        g.addWidget(self.nick, 0, 1)
        g.addWidget(lab2, 1, 0, Qt.AlignmentFlag.AlignRight)
        g.addWidget(self.nets, 1, 1)
        hint = QLabel("ALL for every network, or a comma separated list of network names.")
        hint.setStyleSheet(f"color: {t.muted}; font-size: 7pt;")
        hint.setWordWrap(True)
        g.addWidget(hint, 2, 1)
        g.addWidget(lab3, 3, 0, Qt.AlignmentFlag.AlignRight)
        g.addWidget(self.note, 3, 1)
        hint2 = QLabel("The same note as in their Address Book card.")
        hint2.setStyleSheet(f"color: {t.muted}; font-size: 7pt;")
        g.addWidget(hint2, 4, 1)
        self.body.addLayout(g)
        self.when = QLabel(f"When {nick} comes online or leaves" if edit and nick else "When they come online or leave")
        self.when.setStyleSheet(f"color: {t.title}; font-weight: bold;")
        self.body.addWidget(self.when)
        self.popup = QCheckBox("Show a pop-up (when they come online)")
        self.popup.setChecked(bool(o["popup"]))
        self.sound = QCheckBox("Play a sound")
        self.sound.setChecked(bool(o["sound"]))
        self.whois = QCheckBox("Ask WHOIS (see where they connect from)")
        self.whois.setChecked(bool(o["whois"]))
        self.body.addWidget(self.popup)
        self.body.addWidget(self.sound)
        row = QHBoxLayout()
        row.addSpacing(24)
        self.sound_file = QLineEdit(o.get("sound_file", ""))
        self.sound_file.setPlaceholderText("Default: your pop-up sound (chime or bee)")
        self.sound_file.setReadOnly(True)
        row.addWidget(self.sound_file, 1)
        self.sound_browse = QPushButton(icon("open"), "", objectName="compact")
        self.sound_browse.setToolTip("Pick a .wav file")
        self.sound_browse.setAutoDefault(False)
        self.sound_browse.clicked.connect(self._browse)
        self.sound_clear = QPushButton(icon("close-light"), "", objectName="compact")
        self.sound_clear.setToolTip("Back to the default sound")
        self.sound_clear.setAutoDefault(False)
        self.sound_clear.clicked.connect(lambda: self.sound_file.setText(""))
        self.sound_try = QPushButton(icon("play"), "", objectName="compact")
        self.sound_try.setToolTip("Play it now")
        self.sound_try.setAutoDefault(False)
        self.sound_try.clicked.connect(self._try)
        for b in (self.sound_browse, self.sound_clear, self.sound_try):
            row.addWidget(b)
        self.body.addLayout(row)
        self.sound.toggled.connect(self._sound_row)
        self._sound_row(self.sound.isChecked())
        self.body.addWidget(self.whois)
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
        if edit:
            self.note.setFocus()
        else:
            self.nick.selectAll()
            self.nick.setFocus()

    def _sound_row(self, on: bool) -> None:
        for w in (self.sound_file, self.sound_browse, self.sound_clear, self.sound_try):
            w.setEnabled(on)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Sound file", "", "Sound files (*.wav)")
        if path:
            self.sound_file.setText(path)

    def _try(self) -> None:
        if self.sound_file.text():
            self.win._play_sound("friend", path=self.sound_file.text())
        else:
            self.win.play_soft_chime(force=True)

    def result_values(self) -> tuple[str, str]:
        return self.nick.text().strip(), nets_from_text(self.nets.text())

    def options(self) -> dict:
        return {"popup": self.popup.isChecked(), "sound": self.sound.isChecked(),
                "sound_file": self.sound_file.text().strip(), "whois": self.whois.isChecked()}

    def note_text(self) -> str:
        return " ".join(self.note.text().split())
