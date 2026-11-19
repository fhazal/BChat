"""0.8.7 find bar under the chat (Ctrl+F) and the /filter results window (design option A, OK'd 11-19).

The bar searches the text of the chat on show as you type: every match lit in see-through yellow, the current
one solid yellow with dark text. The marks are extra selections, so the document itself never changes; they go
when the bar closes, when the tab changes and when the chat is built again. New lines recount (after a short
pause, so a busy channel costs one count, not one per line)."""
from __future__ import annotations

import bisect
import re
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit,
                               QToolButton, QWidget)
from shiboken6 import isValid

from .protocol import strip_format
from .widgets import FramedDialog, icon, is_light

_ASTRAL = re.compile("[\U00010000-\U0010FFFF]")    # one Python character, two Qt (UTF-16) positions
MARKS_AROUND = 1000          # matches lit on each side of the current one: a one-letter search can't slow painting
RECOUNT_MS = 150             # new lines: recount once after this pause


def compile_pattern(text: str, case: bool = False, regex: bool = False) -> re.Pattern:
    """The search as a pattern. A bad regular expression raises re.error."""
    return re.compile(text if regex else re.escape(text), 0 if case else re.IGNORECASE)


def find_spans(text: str, pat: re.Pattern) -> list[tuple[int, int]]:
    """Every non-empty match as (start, end) in Qt document positions (UTF-16: an emoji counts two)."""
    astral = [m.start() for m in _ASTRAL.finditer(text)]
    spans = []
    for m in pat.finditer(text):
        a, b = m.span()
        if a == b:
            continue
        if astral:
            a, b = a + bisect.bisect_left(astral, a), b + bisect.bisect_left(astral, b)
        spans.append((a, b))
    return spans


def filter_lines(b, pat: re.Pattern) -> list[str]:
    """/filter: the tab's lines that match ("nick text"), as 'HH:MM nick<tab>text'."""
    out = []
    for ln in b.lines:
        if getattr(ln, "hidden", False):
            continue
        left, text = strip_format(ln.left), strip_format(ln.text)
        if pat.search(f"{left} {text}"):
            out.append(f"{time.strftime('%H:%M', time.localtime(ln.ts))} {left}\t{text}")
    return out


def filter_title(text: str, where: str, n: int) -> str:
    return f'Filter: "{text}" in {where}, {n} line{"" if n == 1 else "s"}'


def find_colours(theme) -> tuple[QColor, QColor, QColor]:
    """(every match, the current match, the current match's text): yellow that reads on dark and light themes."""
    if is_light(theme):
        return QColor(223, 142, 29, 80), QColor("#f6c343"), QColor("#11111b")
    return QColor(249, 226, 175, 110), QColor("#f9e2af"), QColor("#11111b")


class FindBar(QWidget):
    """Find: [text] [up] [down] 2 of 3 [Aa] [.*] [Filter...]  [x]. One per window: the main window's follows the tab."""

    def __init__(self, cfg, parent, view_fn, buf_fn, on_filter, on_close=None):
        super().__init__(parent, objectName="findbar")
        self.cfg = cfg
        self.view_fn, self.buf_fn, self.on_filter, self.on_close = view_fn, buf_fn, on_filter, on_close
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 4, 2)
        lay.setSpacing(4)
        lay.addWidget(QLabel("Find:", self))
        self.edit = QLineEdit(self)
        self.edit.setMinimumWidth(160)
        self.edit.setMaximumWidth(280)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)
        self.prev_btn = self._tool(icon("up"), "", "Previous match (Shift+Enter)")
        self.next_btn = self._tool(icon("down"), "", "Next match (Enter)")
        self.count = QLabel(self, objectName="findcount")
        self.count.setTextFormat(Qt.TextFormat.PlainText)
        self.count.setMinimumWidth(70)
        self.case_btn = self._tool(None, "Aa", "Match case")
        self.regex_btn = self._tool(None, ".*", "Regular expression")
        self.case_btn.setCheckable(True)
        self.regex_btn.setCheckable(True)
        self.filter_btn = QPushButton("Filter...", self, objectName="compact")
        self.filter_btn.setAutoDefault(False)
        self.filter_btn.setToolTip("Copy the matching lines into a window of their own")
        self.close_btn = self._tool(icon("close-light"), "", "Close (Esc)")
        for w in (self.prev_btn, self.next_btn, self.count, self.case_btn, self.regex_btn, self.filter_btn):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(self.close_btn)
        self.prev_btn.clicked.connect(self.find_prev)
        self.next_btn.clicked.connect(self.find_next)
        self.case_btn.toggled.connect(lambda _: self.recount(jump=True))
        self.regex_btn.toggled.connect(lambda _: self.recount(jump=True))
        self.filter_btn.clicked.connect(self.run_filter)
        self.close_btn.clicked.connect(self.close_bar)
        self.edit.textChanged.connect(self._typed)
        self.matches: list[tuple[int, int]] = []
        self.index = -1
        self._view = None          # the chat view searched now
        self._doc = None           # its document when the marks were made
        self._anchor: QTextCursor | None = None    # start of the current match; follows edits and trims
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RECOUNT_MS)
        self._timer.timeout.connect(lambda: self.recount(jump=False))
        self.apply_theme()
        self._update_buttons(False)
        self.hide()

    def _tool(self, ic, text: str, tip: str) -> QToolButton:
        b = QToolButton(self)
        if ic is not None:
            b.setIcon(ic)
        if text:
            b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        return b

    def apply_theme(self) -> None:
        t = self.cfg.theme
        self.setStyleSheet(f"#findbar {{ background: {t.bar}; border-top: 1px solid {t.border}; }}"
                           f" #findcount {{ color: {t.muted}; padding: 0 4px; }}"
                           f" #findbar QToolButton {{ padding: 1px 4px; border-radius: 3px; }}"
                           f" #findbar QToolButton:hover {{ background: {t.popup}; }}"
                           f" #findbar QToolButton:checked {{ background: {t.selected}; color: {t.marking_fg}; }}")
        if self.isVisible():
            self.recount(jump=False)

    # --- open, close, follow the tab -------------------------------------------------------------------------

    def open(self) -> None:
        self.show()
        self.retarget()
        self.edit.setFocus()
        self.edit.selectAll()
        self.recount(jump=True)

    def close_bar(self) -> None:
        self._timer.stop()
        self._unhook()
        self.matches, self.index, self._anchor = [], -1, None
        self.hide()
        if self.on_close is not None:
            self.on_close()

    def retarget(self) -> None:
        """The tab on show changed: let go of the old view (its marks too) and search the new one."""
        v = self.view_fn()
        if v is self._view and v is not None and isValid(v):
            return
        self._unhook()
        self.matches, self.index, self._anchor = [], -1, None
        if v is None or not isValid(v) or not self.isVisible():
            self._show_count()
            return
        self._view = v
        v.textChanged.connect(self._doc_changed)
        self.recount(jump=False)

    def _unhook(self) -> None:
        v, self._view, self._doc = self._view, None, None
        if v is not None and isValid(v):
            try:
                v.textChanged.disconnect(self._doc_changed)
            except (RuntimeError, TypeError):
                pass
            self._set_marks(v, [])

    def view(self):
        return self._view if self._view is not None and isValid(self._view) else None

    # --- keys ------------------------------------------------------------------------------------------------

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.find_prev()
                else:
                    self.find_next()
                return True
            if ev.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(ev)

    # --- searching -------------------------------------------------------------------------------------------

    def _typed(self, text: str) -> None:
        if not text:
            self._anchor = None
        self.recount(jump=True)

    def _doc_changed(self) -> None:
        v = self.view()
        if v is not None and v.document() is not self._doc and self._doc is not None:
            self._set_marks(v, [])       # built again: the old marks point into a document that is gone
            self._doc, self._anchor = None, None
        self._timer.start()

    def pattern(self) -> re.Pattern | None:
        """The bar's search, or None (empty, or a bad regular expression)."""
        text = self.edit.text()
        if not text:
            return None
        try:
            return compile_pattern(text, self.case_btn.isChecked(), self.regex_btn.isChecked())
        except re.error:
            return None

    def recount(self, jump: bool = False) -> None:
        """Find every match again. jump: show the current one (typing, the toggles); a recount after new lines
        keeps the current match and never scrolls."""
        self._timer.stop()
        if not self.isVisible():
            return
        if self._view is None or not isValid(self._view):
            self._view = None
            self.retarget()
            if self._view is not None:
                return             # retarget counted already
        v = self.view()
        self.matches, self.index = [], -1
        text = self.edit.text()
        if v is None or not text:
            if v is not None:
                self._set_marks(v, [])
            self._show_count()
            return
        try:
            pat = compile_pattern(text, self.case_btn.isChecked(), self.regex_btn.isChecked())
        except re.error:
            self._set_marks(v, [])
            self._show_count(bad=True)
            return
        doc = v.document()
        if doc is not self._doc:
            self._anchor = None
        self._doc = doc
        self.matches = find_spans(doc.toPlainText(), pat)
        if self.matches:
            starts = [a for a, _ in self.matches]
            if self._anchor is not None and self._anchor.document() is doc:
                i = bisect.bisect_left(starts, self._anchor.position())
                self.index = i if i < len(starts) else 0
            else:                      # first look: the newest match on screen, or the nearest one above it
                bottom = v.cursorForPosition(QPoint(0, max(0, v.viewport().height() - 1))).position()
                self.index = max(0, bisect.bisect_right(starts, bottom) - 1)
            self._remember()
        self._show_marks(scroll=jump)

    def _remember(self) -> None:
        c = QTextCursor(self._doc)
        c.setPosition(min(self.matches[self.index][0], max(0, self._doc.characterCount() - 1)))
        self._anchor = c

    def _step(self, delta: int) -> None:
        if not self.isVisible():
            return
        if self._timer.isActive() or self.view() is None:
            self.recount(jump=False)
        if not self.matches:
            return
        self.index = (self.index + delta) % len(self.matches)      # wraps at both ends
        self._remember()
        self._show_marks(scroll=True)

    def find_next(self) -> None:
        self._step(1)

    def find_prev(self) -> None:
        self._step(-1)

    # --- drawing ---------------------------------------------------------------------------------------------

    @staticmethod
    def _set_marks(v, sels: list) -> None:
        v.find_marks = tuple(sels)
        v.setExtraSelections(list(sels))

    def _show_marks(self, scroll: bool) -> None:
        v = self.view()
        if v is None:
            return
        self._show_count()
        if not self.matches:
            self._set_marks(v, [])
            return
        every, now_bg, now_fg = find_colours(self.cfg.theme)
        lo, hi = max(0, self.index - MARKS_AROUND), min(len(self.matches), self.index + MARKS_AROUND + 1)
        sels, current = [], None
        for i in range(lo, hi):
            a, b = self.matches[i]
            sel = QTextEdit.ExtraSelection()
            c = QTextCursor(self._doc)
            c.setPosition(a)
            c.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            if i == self.index:
                sel.format.setBackground(now_bg)
                sel.format.setForeground(now_fg)
                current = sel
            else:
                sel.format.setBackground(every)
                sels.append(sel)
        sels.append(current)                 # drawn last: on top
        self._set_marks(v, sels)
        if scroll:
            r = v.cursorRect(current.cursor)
            h = v.viewport().height()
            if r.top() < 0 or r.bottom() > h:
                sb = v.verticalScrollBar()
                sb.setValue(sb.value() + r.center().y() - h // 2)

    def _show_count(self, bad: bool = False) -> None:
        if bad:
            self.count.setText("Bad pattern")
        elif not self.edit.text():
            self.count.setText("")
        elif not self.matches:
            self.count.setText("No matches")
        else:
            self.count.setText(f"{self.index + 1} of {len(self.matches)}")
        self._update_buttons(bool(self.edit.text()) and not bad)

    def _update_buttons(self, ok: bool) -> None:
        self.prev_btn.setEnabled(bool(self.matches))
        self.next_btn.setEnabled(bool(self.matches))
        self.filter_btn.setEnabled(ok)

    def run_filter(self) -> None:
        if self.pattern() is not None and self.buf_fn() is not None:
            self.on_filter(self.buf_fn(), self.edit.text(), self.case_btn.isChecked(), self.regex_btn.isChecked())


class FilterWindow(FramedDialog):
    """/filter's results: the matching lines, Copy all, Save..."""

    def __init__(self, win):
        super().__init__("Filter", win)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.resize(720, 420)
        self.lines: list[str] = []
        self.name = ""
        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFont(QFont(win.cfg.chat_font, win.cfg.chat_font_size))
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.copy_btn = QPushButton(icon("copy"), "Copy all", self)
        self.save_btn = QPushButton(icon("save"), "Save...", self)
        for b in (self.copy_btn, self.save_btn):
            b.setAutoDefault(False)
            row.addWidget(b)
        self.copy_btn.clicked.connect(self.copy_all)
        self.save_btn.clicked.connect(self.save)
        self.body.addLayout(row)

    def show_result(self, title: str, lines: list[str], name: str) -> None:
        self.lines, self.name = lines, name
        self.titlebar.set_title(title)
        self.setWindowTitle(title)
        self.view.setPlainText("\n".join(lines))

    def text(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.lines else "")

    def copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.text())

    def save(self) -> None:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", self.name) or "filter"
        path, _ = QFileDialog.getSaveFileName(self, "Save Text", f"filter-{safe}.txt", "Text files (*.txt)")
        if path:
            Path(path).write_text(self.text(), encoding="utf-8")
