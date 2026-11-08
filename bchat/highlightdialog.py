"""Add / Edit Highlight: mIRC's Highlight fields (words, match on, from these channels/nicks, colour, sound, flash,
tip) in BChat's look. Colours are theme colour numbers, so a rule follows a theme change."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton)

from .highlights import NEW_RULE, ON, ON_TEXT
from .widgets import FramedDialog, icon

COLOURS = ("", 4, 7, 8, 3, 9, 11, 12, 13, 6)      # "" = the theme's highlight colour, then mIRC colour numbers


def colour_of(theme, value) -> str:
    """A rule's colour as #rrggbb: "" is the theme's highlight colour, a number is that mIRC colour in the theme."""
    if value in ("", None):
        return theme.highlight
    try:
        return theme.palette[int(value) % len(theme.palette)]
    except (TypeError, ValueError, IndexError):
        return theme.highlight


def swatch(theme, value, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(colour_of(theme, value)))
    return QIcon(pm)


def sound_text(sound: str) -> str:
    if not sound:
        return "Default"
    if sound == "none":
        return "None"
    return sound.replace("\\", "/").rsplit("/", 1)[-1]


class HighlightDialog(FramedDialog):
    def __init__(self, parent, theme, r: dict | None = None):
        super().__init__("Edit Highlight" if r else "Add Highlight", parent)
        self.theme = theme
        self.rule = dict(NEW_RULE, **(r or {}))
        self.setFixedWidth(460)
        g = QGridLayout()
        g.setVerticalSpacing(8)
        self.match = QLineEdit(self.rule["match"])
        self.match.setPlaceholderText("restart*, kopitiam")
        self.match.setToolTip("Words separated by commas. Whole words, or wildcards * ? (restart* matches restarting)")
        g.addWidget(QLabel("Highlight:"), 0, 0)
        g.addWidget(self.match, 0, 1, 1, 2)
        self.on = QComboBox()
        self.on.addItems([{"message": "The message", "nick": "The nick who sends it", "both": "Both"}[o] for o in ON])
        self.on.setCurrentIndex(ON.index(self.rule["on"]) if self.rule["on"] in ON else 0)
        g.addWidget(QLabel("Match on:"), 1, 0)
        g.addWidget(self.on, 1, 1, 1, 2)
        self.where = QLineEdit(self.rule["where"])
        self.where.setPlaceholderText("Everywhere")
        self.where.setToolTip("Channels, nicks or networks, separated by commas. Empty means everywhere")
        g.addWidget(QLabel("From:"), 2, 0)
        g.addWidget(self.where, 2, 1, 1, 2)
        g.addWidget(QLabel("Colour:"), 3, 0)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.colour_group = QButtonGroup(self)
        self.colour_buttons = []
        for i, value in enumerate(COLOURS):
            bt = QPushButton()
            bt.setCheckable(True)
            bt.setFixedSize(26, 22)
            bt.setToolTip("The theme's highlight colour" if value == "" else f"Colour {value}")
            c = colour_of(theme, value)
            bt.setStyleSheet(f"QPushButton {{ background: {c}; border: 1px solid {theme.border}; border-radius: 4px; min-height: 0;"
                             f" padding: 0; }} QPushButton:checked {{ border: 2px solid {theme.text}; }}")
            bt.value = value
            self.colour_group.addButton(bt, i)
            self.colour_buttons.append(bt)
            row.addWidget(bt)
            if str(value) == str(self.rule["colour"]):
                bt.setChecked(True)
        if self.colour_group.checkedButton() is None:
            self.colour_buttons[0].setChecked(True)
        row.addStretch(1)
        g.addLayout(row, 3, 1, 1, 2)
        g.addWidget(QLabel("Sound:"), 4, 0)
        self.sound = QComboBox()
        self.sound_value = self.rule["sound"]
        self._fill_sound()
        self.sound.activated.connect(self._sound_picked)
        g.addWidget(self.sound, 4, 1)
        self.play = QPushButton(icon("play"), "Play", objectName="compact")
        self.play.clicked.connect(self._play)
        g.addWidget(self.play, 4, 2)
        g.setColumnStretch(1, 1)
        self.body.addLayout(g)
        self.flash = QCheckBox("Flash the taskbar when BChat isn't in front")
        self.flash.setChecked(bool(self.rule["flash"]))
        self.body.addWidget(self.flash)
        self.tip = QCheckBox("Pop up a card when BChat isn't in front")
        self.tip.setChecked(bool(self.rule["tip"]))
        self.body.addWidget(self.tip)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        b = QHBoxLayout()
        b.addStretch(1)
        cancel = QPushButton(icon("cancel"), "&Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(icon("done"), "&OK")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        b.addWidget(cancel)
        b.addWidget(self.ok)
        self.body.addLayout(b)
        self.match.textChanged.connect(lambda t: self.ok.setEnabled(bool(t.strip())))
        self.ok.setEnabled(bool(self.match.text().strip()))

    def _fill_sound(self) -> None:
        self.sound.clear()
        self.sound.addItem("Default (Sound page)", "")
        self.sound.addItem("None", "none")
        if self.sound_value not in ("", "none"):
            self.sound.addItem(sound_text(self.sound_value), self.sound_value)
        self.sound.addItem("Choose a file...", "?")
        self.sound.setCurrentIndex(max(0, self.sound.findData(self.sound_value)))
        self.sound.setToolTip("Default: the highlight sound on Preferences > Sound")

    def _sound_picked(self, _i: int) -> None:
        value = self.sound.currentData()
        if value == "?":
            path, _ = QFileDialog.getOpenFileName(self, "Highlight sound", "", "Sounds (*.wav)")
            if path:
                self.sound_value = path
        else:
            self.sound_value = value
        self._fill_sound()

    def _play(self) -> None:
        path = self.sound_value
        if path == "none":
            return
        if not path:
            path = getattr(self.parent(), "cfg", None).sounds.get("hilight", "") if getattr(self.parent(), "cfg", None) else ""
        if path:
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except (ImportError, RuntimeError):
                pass

    def result_rule(self) -> dict:
        bt = self.colour_group.checkedButton()
        return dict(self.rule, match=", ".join(w.strip() for w in self.match.text().split(",") if w.strip()),
                    on=ON[self.on.currentIndex()], where=", ".join(w.strip() for w in self.where.text().split(",") if w.strip()),
                    colour=bt.value if bt is not None else "", sound=self.sound_value,
                    flash=self.flash.isChecked(), tip=self.tip.isChecked())


def rule_row(theme, r: dict) -> list[str]:
    return [r.get("match", ""), ON_TEXT.get(r.get("on", "message"), "Message"), r.get("where", "") or "Everywhere", "",
            sound_text(r.get("sound", ""))]
