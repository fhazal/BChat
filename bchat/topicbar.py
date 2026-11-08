"""The topic bar: the topic with its colours, editable like XChat's, with B U I Fg Bg and emoji buttons.

The editor keeps mIRC formatting as real text formatting and turns it back into codes when the topic is set:
\\x02 bold, \\x1d italic, \\x1f underline, \\x03fg[,bg] colour, \\x0f reset. Also the emoji popup used by the input box.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QToolButton, QWidget)

from .config import Theme
from .protocol import EXTENDED, colour_of, parse_format, readable

FG_INDEX = QTextCharFormat.Property.UserProperty + 1   # mIRC colour number kept on the text
BG_INDEX = QTextCharFormat.Property.UserProperty + 2
MONO = QTextCharFormat.Property.UserProperty + 3      # monospace (code 0x11) kept on the text
EMOJI = ("\U0001F600 \U0001F602 \U0001F60A \U0001F60D \U0001F60E \U0001F914 \U0001F622 \U0001F621 \U0001F44D "
         "\U0001F44E \U0001F44F \U0001F64F \U0001F525 \U0001F389 ❤️ ⭐ \U0001F3B5 \U0001F37A ☕ "
         "\U0001F918").split()   # no flags: Windows' emoji font has none, they show as two letters


def _ink(colour: str) -> str:
    return "#11111b" if QColor(colour).lightness() > 140 else "#cdd6f4"


def place(button: QRect, size: QSize, screen: QRect) -> QPoint:
    """Where a popup for this button goes: below it if it fits, else above, always inside the screen's work area."""
    x = max(screen.left(), min(button.left(), screen.right() + 1 - size.width()))
    y = button.bottom() + 1
    if y + size.height() > screen.bottom() + 1:
        y = button.top() - size.height()
    y = max(screen.top(), min(y, screen.bottom() + 1 - size.height()))
    return QPoint(x, y)


class Popup(QFrame):
    """A small grid that closes on a pick or a click outside."""
    picked = Signal(object)

    def __init__(self, title: str, theme: Theme, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setStyleSheet(f"Popup {{ background: {theme.popup}; border: 1px solid {theme.border}; }}")
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.grid.setSpacing(4)
        self.title = QLabel(f"<b>{title}</b>", self)
        self.grid.addWidget(self.title, 0, 0, 1, 5)

    def add(self, i: int, cols: int, b: QPushButton, value) -> None:
        b.clicked.connect(lambda _=False, v=value: (self.picked.emit(v), self.close()))
        self.grid.addWidget(b, 1 + i // cols, i % cols)

    def show_below(self, w: QWidget) -> None:
        """Below the button, or above it when the screen (taskbar) has no room below, e.g. the input box maximized."""
        self.adjustSize()
        top_left = w.mapToGlobal(QPoint(0, 0))
        self.move(place(QRect(top_left, w.size()), self.size(), w.screen().availableGeometry()))
        self.show()


def colour_popup(title: str, theme: Theme, parent=None) -> Popup:
    p = Popup(title, theme, parent)
    cells = [("None", None)] + [(str(i), i) for i in range(16)]
    for i, (text, idx) in enumerate(cells):
        b = QPushButton(text, p)
        b.setFixedSize(32, 24)
        bg = theme.palette[idx] if idx is not None else theme.panel
        b.setStyleSheet(f"QPushButton {{ background: {bg}; color: {_ink(bg)}; border: 1px solid {theme.border};"
                        f" border-radius: 3px; font-size: 7pt; padding: 0; min-height: 0; }}"
                        f"QPushButton:hover {{ border: 1px solid {theme.text}; }}")
        p.add(i, 4, b, idx)
    return p


def emoji_popup(theme: Theme, parent=None) -> Popup:
    p = Popup("Emoji", theme, parent)
    for i, e in enumerate(EMOJI):
        b = QPushButton(e, p)
        b.setFixedSize(32, 30)
        b.setStyleSheet("QPushButton { font-family: 'Segoe UI Emoji'; font-size: 13pt; background: transparent;"
                        " border: 0; padding: 0; min-height: 0; } QPushButton:hover { background: rgba(255,255,255,30); }")
        p.add(i, 5, b, e)
    return p


class TopicEdit(QTextEdit):
    """One-line rich editor. Enter sets the topic, Esc puts the last one back."""
    submitted = Signal()

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.exact = False      # Preferences: show colours exactly as sent (no readability guard)
        self.raw = ""
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        self.setFixedHeight(self.fontMetrics().height() + 10)

    # --- codes <-> formatting ---------------------------------------------------------

    def set_topic(self, raw: str) -> None:
        self.raw = raw
        self.clear()
        cur = QTextCursor(self.document())
        for sp in parse_format(raw.replace("\n", " ")):
            cur.insertText(sp.text, self._fmt(sp))
        self.setCurrentCharFormat(QTextCharFormat())
        self.document().setModified(False)
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def _fmt(self, sp) -> QTextCharFormat:
        f = QTextCharFormat()
        if sp.bold:
            f.setFontWeight(QFont.Weight.Bold)
        if sp.italic:
            f.setFontItalic(True)
        if sp.underline:
            f.setFontUnderline(True)
        if sp.strike:
            f.setFontStrikeOut(True)
        if sp.mono:
            f.setFontFamilies(["Consolas", "Courier New", "monospace"])
            f.setProperty(MONO, True)
        fg, bg = sp.fg, sp.bg
        if sp.reverse:
            fg, bg = bg if bg is not None else 1, fg if fg is not None else 0
        # the code itself (0-98 or "#rrggbb") stays on the text, so saving the topic sends it back unchanged
        fgc, bgc = colour_of(fg, self.theme.palette), colour_of(bg, self.theme.palette)
        if fgc and not self.exact and not (isinstance(fg, int) and fg <= 15):
            # same readability guard as the chat; only the shade on screen changes, the saved code stays as sent
            fgc = readable(fgc, bgc or self.palette().color(self.backgroundRole()).name())
        if fgc:
            f.setForeground(QColor(fgc))
            f.setProperty(FG_INDEX, fg)
        if bgc:
            f.setBackground(QColor(bgc))
            f.setProperty(BG_INDEX, bg)
        return f

    def to_irc(self) -> str:
        """The text with mIRC codes, as few as needed."""
        out: list[str] = []
        state = (False, False, False, None, None, False, False)
        block = self.document().begin()
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            f = frag.charFormat()
            want = (f.fontWeight() >= QFont.Weight.Bold, f.fontItalic(), f.fontUnderline(),
                    f.property(FG_INDEX) if f.hasProperty(FG_INDEX) else None,
                    f.property(BG_INDEX) if f.hasProperty(BG_INDEX) else None,
                    f.fontStrikeOut(), bool(f.property(MONO)) if f.hasProperty(MONO) else False)
            if want != state:
                out.append(self._switch(state, want))
                state = want
            out.append(frag.text().replace(" ", " ").replace("\n", " "))
            it += 1
        return "".join(out).strip()

    @staticmethod
    def _switch(old, new) -> str:
        ob, oi, ou, ofg, obg, os_, om = old
        nb, ni, nu, nfg, nbg, ns, nm = new
        if (ofg is not None or obg is not None) and nfg is None and nbg is None:
            # colour off: reset everything, then turn back on what stays
            return ("\x0f" + ("\x02" if nb else "") + ("\x1d" if ni else "") + ("\x1f" if nu else "")
                    + ("\x1e" if ns else "") + ("\x11" if nm else ""))
        s = (("\x02" if ob != nb else "") + ("\x1d" if oi != ni else "") + ("\x1f" if ou != nu else "")
             + ("\x1e" if os_ != ns else "") + ("\x11" if om != nm else ""))
        if (nfg, nbg) != (ofg, obg):
            s += TopicEdit._colour_code(nfg, nbg)
        return s

    @staticmethod
    def _colour_code(fg, bg) -> str:
        """The code for a colour pair: \\x03NN[,NN] for colour numbers, \\x04RRGGBB[,RRGGBB] when hex is involved.
        In a hex code, colours 16-98 are written as their fixed hex value. 0-15 are the reader's theme shades and have
        no fixed hex, so in the rare mix of 0-15 with hex the 0-15 side is kept as a number and the other side dropped."""
        if not isinstance(fg, str) and not isinstance(bg, str):
            return f"\x03{fg if fg is not None else 99:02d}" + (f",{bg:02d}" if bg is not None else "")

        def hexpart(c):
            if isinstance(c, str):
                return c[1:]
            return EXTENDED[c - 16] if c is not None and 16 <= c <= 98 else None

        f, b = hexpart(fg), hexpart(bg)
        if f is None:                     # fg is 0-15 or default: it can't go in a hex code
            return f"\x03{fg:02d}" if fg is not None else ""
        return f"\x04{f}" + (f",{b}" if b is not None else "")

    # --- buttons ------------------------------------------------------------------------

    def _apply(self, f: QTextCharFormat, clear: tuple = ()) -> None:
        cur = self.textCursor()
        if cur.hasSelection():
            if clear:   # merge cannot remove a property, so rebuild each piece
                start, end = cur.selectionStart(), cur.selectionEnd()
                c2 = QTextCursor(self.document())
                pos = start
                while pos < end:
                    c2.setPosition(pos)
                    c2.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                    g = c2.charFormat()
                    for p in clear:
                        g.clearProperty(p)
                    g.merge(f)
                    c2.setCharFormat(g)
                    pos += 1
            else:
                cur.mergeCharFormat(f)
        else:
            g = self.currentCharFormat()
            for p in clear:
                g.clearProperty(p)
            g.merge(f)
            self.setCurrentCharFormat(g)
        self.setFocus()

    def toggle_bold(self) -> None:
        on = self.currentCharFormat().fontWeight() < QFont.Weight.Bold
        f = QTextCharFormat()
        f.setFontWeight(QFont.Weight.Bold if on else QFont.Weight.Normal)
        self._apply(f)

    def toggle_italic(self) -> None:
        f = QTextCharFormat()
        f.setFontItalic(not self.currentCharFormat().fontItalic())
        self._apply(f)

    def toggle_underline(self) -> None:
        f = QTextCharFormat()
        f.setFontUnderline(not self.currentCharFormat().fontUnderline())
        self._apply(f)

    def set_fg(self, idx: int | None) -> None:
        f = QTextCharFormat()
        if idx is None:
            self._apply(f, (QTextCharFormat.Property.ForegroundBrush, FG_INDEX))
            return
        f.setForeground(QColor(self.theme.palette[idx]))
        f.setProperty(FG_INDEX, idx)
        self._apply(f)

    def set_bg(self, idx: int | None) -> None:
        f = QTextCharFormat()
        if idx is None:
            self._apply(f, (QTextCharFormat.Property.BackgroundBrush, BG_INDEX))
            return
        f.setBackground(QColor(self.theme.palette[idx]))
        f.setProperty(BG_INDEX, idx)
        self._apply(f)

    def insert_emoji(self, e: str) -> None:
        self.textCursor().insertText(e)
        self.setFocus()

    # --- keys ---------------------------------------------------------------------------

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        k, mod = ev.key(), ev.modifiers()
        ctrl = mod & Qt.KeyboardModifier.ControlModifier
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submitted.emit()
            return
        if k == Qt.Key.Key_Escape:
            self.set_topic(self.raw)
            return
        if ctrl and k == Qt.Key.Key_B:
            self.toggle_bold(); return
        if ctrl and k == Qt.Key.Key_U:
            self.toggle_underline(); return
        if ctrl and k == Qt.Key.Key_I:
            self.toggle_italic(); return
        super().keyPressEvent(ev)

    def insertFromMimeData(self, source) -> None:
        if source.hasText():
            self.textCursor().insertText(source.text().replace("\r", " ").replace("\n", " "))


class TopicBar(QWidget):
    """Topic editor plus its buttons. set_allowed() hides the buttons when we may not change the topic."""
    submitted = Signal(str)

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.edit = TopicEdit(theme, self)
        self.edit.submitted.connect(self._submit)
        lay.addWidget(self.edit, 1)
        h = self.edit.height()
        self.buttons: dict[str, QToolButton] = {}

        self._css: dict[str, str] = {}

        def tb(key, text, tip, slot, css=""):
            b = QToolButton(self)
            b.setText(text)
            b.setToolTip(tip)
            b.setFixedSize(24, h)
            b.clicked.connect(slot)
            lay.addWidget(b)
            self.buttons[key] = b
            self._css[key] = css

        tb("bold", "B", "Bold (Ctrl+B)", self.edit.toggle_bold, "font-weight: bold;")
        tb("underline", "U", "Underline (Ctrl+U)", self.edit.toggle_underline, "text-decoration: underline;")
        tb("italic", "I", "Italic (Ctrl+I)", self.edit.toggle_italic, "font-style: italic;")
        tb("fg", "Fg", "Text colour", lambda: self._pop("fg"), "FG")
        tb("bg", "Bg", "Background colour", lambda: self._pop("bg"))
        tb("emoji", "\U0001F642", "Emoji (Windows: Win + . for all of them)", lambda: self._pop("emoji"),
           "font-family: 'Segoe UI Emoji';")
        self.set_btn = QPushButton("Set", self, objectName="compact")
        self.set_btn.setFixedHeight(h)
        self.set_btn.setToolTip("Set the topic (Enter). Esc puts the old one back.")
        self.set_btn.setAutoDefault(False)
        self.set_btn.clicked.connect(self._submit)
        lay.addWidget(self.set_btn)
        self.popup: Popup | None = None
        self.restyle()

    def restyle(self) -> None:
        """Button colours from the theme (again after a theme change). Without them Qt draws a fixed grey,
        which hides dark text on a light theme."""
        t = self.theme
        for key, b in self.buttons.items():
            css = self._css[key].replace("FG", f"color: {t.palette[4]};")
            text = "" if "color:" in css else f"color: {t.text};"
            b.setStyleSheet(f"QToolButton {{ background: {t.thumb}; border: 1px solid {t.bar}; border-radius: 2px; {text} {css} }}"
                            f"QToolButton:hover {{ background: {t.thumb_hover}; }}"
                            f"QToolButton:disabled {{ color: {t.disabled}; }}")

    def _pop(self, which: str) -> None:
        if which == "emoji":
            self.popup = emoji_popup(self.theme, self)
            self.popup.picked.connect(self.edit.insert_emoji)
        else:
            self.popup = colour_popup("Text colour" if which == "fg" else "Background colour", self.theme, self)
            self.popup.picked.connect(self.edit.set_fg if which == "fg" else self.edit.set_bg)
        self.popup.show_below(self.buttons[which])

    def _submit(self) -> None:
        if self.edit.isReadOnly():
            return
        self.submitted.emit(self.edit.to_irc())

    def set_topic(self, raw: str) -> None:
        if not self.edit.hasFocus():
            self.edit.set_topic(raw)
        else:
            self.edit.raw = raw   # do not throw away what is being typed; Esc brings the new one

    def editing(self) -> bool:
        return self.edit.hasFocus()

    def set_allowed(self, ok: bool, why: str = "") -> None:
        """Can't change the topic (+t and not op, or no channel): the format buttons and Set go away,
        the topic stays readable and the tooltip says why. They come back the moment you may."""
        self.edit.setReadOnly(not ok)
        for b in [*self.buttons.values(), self.set_btn]:
            b.setEnabled(ok)
            b.setVisible(ok)
        self.edit.setToolTip("" if ok else why)
