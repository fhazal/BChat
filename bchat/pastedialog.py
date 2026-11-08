"""Pasting many lines: BChat's own question, with a preview and how long sending takes."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton

from .widgets import FramedDialog, icon

PREVIEW_LINES = 4


def send_seconds(lines: list[str]) -> int:
    """Session._drain_queue's pacing: about 10 seconds of credit at once, then 2 s + length/120 per line."""
    costs = [2 + (len(line) + 12) / 120 for line in lines]       # "#channel :" counts too
    return max(0, round(sum(costs[:-1]) - 10))                  # the last line leaves as soon as there's room


def timing_note(lines: list[str]) -> str:
    secs = send_seconds(lines)
    when = "It all goes right away." if secs < 2 else f"About {secs} seconds."
    return ("BChat sends the first few at once, then one every 2 seconds, so the network doesn't throw you out "
            f"for flooding. {when}")


class PasteDialog(FramedDialog):
    """choice: "lines" (one message per line), "one" (joined with spaces) or "" (Cancel)."""

    def __init__(self, win, target: str, lines: list[str]):
        super().__init__("Paste", win)
        t = win.cfg.theme
        self.lines = lines
        self.choice = ""
        self.setFixedWidth(480)
        self.body.setContentsMargins(22, 18, 22, 16)
        self.body.setSpacing(10)
        self.head = QLabel(f"Send {len(lines)} lines to {target}?")
        self.head.setTextFormat(Qt.TextFormat.PlainText)
        self.head.setStyleSheet(f"color: {t.title}; font-size: 12pt; font-weight: bold;")
        self.body.addWidget(self.head)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(92)
        shown = lines[:PREVIEW_LINES]
        rest = len(lines) - len(shown)
        self.preview.setPlainText("\n".join(shown) + (f"\n… {rest} more line{'s' if rest != 1 else ''}" if rest else ""))
        self.body.addWidget(self.preview)
        self.note = QLabel(timing_note(lines))
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {t.muted};")
        self.body.addWidget(self.note)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(sep)
        row = QHBoxLayout()
        self.cancel_btn = QPushButton(icon("cancel"), "&Cancel")
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        self.one_btn = QPushButton("Send as &One Line")
        self.one_btn.setAutoDefault(False)
        self.one_btn.clicked.connect(lambda: self._pick("one"))
        self.lines_btn = QPushButton(icon("done"), f"&Send {len(lines)} Lines")
        self.lines_btn.setDefault(True)
        self.lines_btn.clicked.connect(lambda: self._pick("lines"))
        row.addWidget(self.one_btn)
        row.addWidget(self.lines_btn)
        self.body.addLayout(row)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()
