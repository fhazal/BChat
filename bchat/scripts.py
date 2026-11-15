"""Window > Scripts...: write, save and reload Python scripts inside BChat (grew from the Plugins window).
Scripts stay files in the addons folder, so XChat scripts and files copied in still work. Save (Ctrl+S) saves and
loads the script again; a mistake lights its line and the version that was running keeps running."""
from __future__ import annotations

import keyword
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QKeySequence, QPainter, QShortcut, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextFormat)
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QSplitter, QTextEdit, QVBoxLayout, QWidget)

from .editors import button
from .tools import ToolWindow

TEMPLATE = '''"""{name}: a short example. A command, an event and a menu item."""
import bchat

__module_name__ = "{name}"
__module_version__ = "1.0"
__module_description__ = "A command, an event and a menu item"


def hello(word, word_eol, userdata):
    # /hello [name]: says hello in this tab. Only you see it.
    who = word[1] if len(word) > 1 else "world"
    bchat.prnt(f"Hello, {{who}}!")
    return bchat.EAT_ALL


def joined(e):
    # e has network, channel, nick, text and me
    if e.nick == e.me:
        bchat.prnt(f"You joined {{e.channel}} on {{e.network}}.")


def count_me(e):
    # Channel right-click menu > Count me. The number is kept between starts.
    n = (bchat.get_pluginpref("count") or 0) + 1
    bchat.set_pluginpref("count", n)
    bchat.prnt(f"Count me: {{n}}")


bchat.hook_command("hello", hello)
bchat.on_join(joined)
bchat.add_menu_item("Channel", "Count me", count_me)
'''

WARNING = "A script can do anything you can do on this PC. Only run scripts you trust."


class PythonColours(QSyntaxHighlighter):
    WORDS = re.compile(r"\b(" + "|".join(keyword.kwlist) + r")\b")
    API = re.compile(r"\b(bchat|xchat|hexchat)\b")
    NUMBER = re.compile(r"\b\d+(\.\d+)?\b")
    STRING = re.compile(r"[rbfu]{0,2}(\"[^\"\\]*(\\.[^\"\\]*)*\"|'[^'\\]*(\\.[^'\\]*)*')", re.I)

    def __init__(self, doc, theme):
        super().__init__(doc)
        self.f_word = self._fmt(theme.topic, bold=True)
        self.f_api = self._fmt(theme.new_highlight)
        self.f_num = self._fmt(theme.new_data)
        self.f_str = self._fmt(theme.join)
        self.f_note = self._fmt(theme.stamp, italic=True)

    @staticmethod
    def _fmt(colour: str, bold=False, italic=False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(QColor(colour))
        if bold:
            f.setFontWeight(QFont.Weight.Bold)
        f.setFontItalic(italic)
        return f

    def highlightBlock(self, text: str) -> None:
        for rx, f in ((self.WORDS, self.f_word), (self.API, self.f_api), (self.NUMBER, self.f_num)):
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        for m in self.STRING.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f_str)
        # a """docstring""" block: state 1 while inside
        start = 0
        if self.previousBlockState() == 1:
            end = text.find('"""')
            if end < 0:
                self.setFormat(0, len(text), self.f_note)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 3, self.f_note)
            start = end + 3
        self.setCurrentBlockState(0)
        while True:
            at = text.find('"""', start)
            if at < 0:
                break
            end = text.find('"""', at + 3)
            if end < 0:
                self.setFormat(at, len(text) - at, self.f_note)
                self.setCurrentBlockState(1)
                break
            self.setFormat(at, end + 3 - at, self.f_note)
            start = end + 3
        hash_at = self._comment_at(text)
        if hash_at >= 0:
            self.setFormat(hash_at, len(text) - hash_at, self.f_note)

    @staticmethod
    def _comment_at(text: str) -> int:
        quote = ""
        for i, ch in enumerate(text):
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                return i
        return -1


class _Numbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.numbers_width(), 0)

    def paintEvent(self, _ev):
        self.editor.paint_numbers(self)


class CodeEditor(QPlainTextEdit):
    """Line numbers on the left, 4-space tabs, one lit error line. Ctrl+S, Ctrl+F and F3 are its own while it has
    the focus, so they never reach the main window's keys (Network List, Search Text) instead."""
    save_key = Signal()
    find_key = Signal()
    next_key = Signal(bool)
    OWN_KEYS = ("Ctrl+S", "Ctrl+F", "F3", "Shift+F3")

    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self.error_line = 0
        self.numbers = _Numbers(self)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(10)
        self.setFont(f)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.blockCountChanged.connect(lambda _n: self.setViewportMargins(self.numbers_width(), 0, 0, 0))
        self.updateRequest.connect(self._scrolled)
        self.setViewportMargins(self.numbers_width(), 0, 0, 0)
        self.colours = PythonColours(self.document(), theme)

    def numbers_width(self) -> int:
        return 14 + self.fontMetrics().horizontalAdvance("9") * max(3, len(str(self.blockCount())))

    def _scrolled(self, rect, dy) -> None:
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        cr = self.contentsRect()
        self.numbers.setGeometry(QRect(cr.left(), cr.top(), self.numbers_width(), cr.height()))

    def paint_numbers(self, w) -> None:
        p = QPainter(w)
        p.fillRect(w.rect(), QColor(self.theme.window))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        h = self.fontMetrics().height()
        while block.isValid() and top <= w.height():
            if block.isVisible():
                n = block.blockNumber() + 1
                p.setPen(QColor(self.theme.marker if n == self.error_line else self.theme.stamp))
                p.drawText(0, top, w.width() - 8, h, Qt.AlignmentFlag.AlignRight, str(n))
            top += round(self.blockBoundingRect(block).height())
            block = block.next()

    @staticmethod
    def _combo(ev) -> str:
        return QKeySequence(ev.keyCombination()).toString()

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.ShortcutOverride and self._combo(ev) in self.OWN_KEYS:
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:
        combo = self._combo(ev)
        if combo in self.OWN_KEYS:
            if combo == "Ctrl+S":
                self.save_key.emit()
            elif combo == "Ctrl+F":
                self.find_key.emit()
            else:
                self.next_key.emit(combo == "Shift+F3")
            return
        if ev.key() == Qt.Key.Key_Tab and not ev.modifiers():
            self.insertPlainText("    ")
            return
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ev.modifiers():
            line = self.textCursor().block().text()
            indent = line[:len(line) - len(line.lstrip(" "))]
            if line.rstrip().endswith(":"):
                indent += "    "
            super().keyPressEvent(ev)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(ev)

    def show_error(self, line: int) -> None:
        self.error_line = line
        sels = []
        if line:
            block = self.document().findBlockByNumber(line - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                bg = QColor(self.theme.marker)
                bg.setAlpha(60)
                sel.format.setBackground(bg)
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                sel.cursor = QTextCursor(block)
                sels.append(sel)
                self.setTextCursor(QTextCursor(block))
                self.centerCursor()
        self.setExtraSelections(sels)
        self.numbers.update()


class ScriptsWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Scripts", win, (860, 520))
        t = win.cfg.theme
        self.path: Path | None = None
        self.saved_text = ""
        warn = QLabel(WARNING)
        warn.setStyleSheet(f"color: {t.highlight};")
        warn.setWordWrap(True)
        self.body.addWidget(warn)
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.view = QListWidget()
        self.view.currentItemChanged.connect(self._picked)
        self.view.itemChanged.connect(self._ticked)
        ll.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.new_btn = button("New", self.new_script, "add")
        self.delete_btn = button("Delete", self.delete_script)
        row.addWidget(self.new_btn)
        row.addWidget(self.delete_btn)
        ll.addLayout(row)
        self.folder_btn = button("Open folder", self.open_folder)
        ll.addWidget(self.folder_btn)
        left.setMinimumWidth(170)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.editor = CodeEditor(t)
        self.editor.textChanged.connect(self._edited)
        self.editor.save_key.connect(self.save)
        self.editor.find_key.connect(self.show_find)
        self.editor.next_key.connect(lambda back: self.find_next(back=back))
        rl.addWidget(self.editor, 1)
        self.find_row = QWidget()
        fr = QHBoxLayout(self.find_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find (Enter: next, Shift+Enter: back)")
        self.find_box.returnPressed.connect(lambda: self.find_next())
        fr.addWidget(self.find_box, 1)
        self.find_close = button("Close", lambda: self.find_row.hide(), "close-light")
        fr.addWidget(self.find_close)
        self.find_row.hide()
        rl.addWidget(self.find_row)
        self.bar = QLabel()
        self.bar.setWordWrap(True)
        self.bar.setTextFormat(Qt.TextFormat.PlainText)
        rl.addWidget(self.bar)
        row = QHBoxLayout()
        self.find_btn = button("Find", self.show_find)
        self.save_btn = button("Save and reload  (Ctrl+S)", self.save, "save")
        row.addWidget(self.find_btn)
        row.addStretch(1)
        row.addWidget(self.save_btn)
        rl.addLayout(row)
        split.addWidget(right)
        split.setSizes([200, 640])
        self.body.addWidget(split, 1)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save)
        QShortcut(QKeySequence("Ctrl+F"), self, self.show_find)
        QShortcut(QKeySequence("F3"), self, lambda: self.find_next())
        QShortcut(QKeySequence("Shift+F3"), self, lambda: self.find_next(back=True))
        back = QShortcut(QKeySequence("Shift+Return"), self.find_box, lambda: self.find_next(back=True))
        back.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.fill()

    # --- the list ---------------------------------------------------------------------------------------------

    @property
    def mgr(self):
        return self.win.plugins

    def files(self) -> list[Path]:
        """Every .py in the addons folder, and scripts loaded from elsewhere (/load C:\\path\\x.py)."""
        found = sorted(self.mgr.folder.glob("*.py"), key=lambda p: p.name.lower()) if self.mgr.folder.is_dir() else []
        for p in self.mgr.plugins:
            if p.path not in found:
                found.append(p.path)
        return found

    def _running(self, path: Path):
        return next((p for p in self.mgr.plugins if p.path == path), None)

    def fill(self) -> None:
        keep = self.path
        self.view.blockSignals(True)
        self.view.clear()
        for path in self.files():
            it = QListWidgetItem(path.name, self.view)
            it.setData(Qt.ItemDataRole.UserRole, str(path))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on = self._running(path) is not None
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            p = self._running(path)
            tip = str(path)
            if p is not None and (p.version or p.description):
                tip = f"{p.name} {p.version}: {p.description}\n{path}".replace(" : ", ": ")
            it.setToolTip(tip + "\nTick: running. Untick: stopped, and not started with BChat.")
        self.view.blockSignals(False)
        if keep is not None:
            self.select(keep)
        elif self.view.count():
            self.view.setCurrentRow(0)
        else:
            self._show(None)

    def item_for(self, path: Path):
        for i in range(self.view.count()):
            it = self.view.item(i)
            if Path(it.data(Qt.ItemDataRole.UserRole)) == Path(path):
                return it
        return None

    def select(self, path: Path) -> bool:
        it = self.item_for(path)
        if it is None:
            return False
        if self.view.currentItem() is it:
            return True
        self.view.setCurrentItem(it)
        return self.path == Path(path)

    def _picked(self, it, old=None) -> None:
        if it is None:
            return
        path = Path(it.data(Qt.ItemDataRole.UserRole))
        if path == self.path:
            return
        if not self.keep_or_drop():
            self.view.blockSignals(True)
            self.view.setCurrentItem(old)
            self.view.blockSignals(False)
            return
        self._show(path)

    def _show(self, path: Path | None) -> None:
        self.path = path
        self.editor.blockSignals(True)
        try:
            text = path.read_text("utf-8", errors="replace") if path is not None else ""
        except OSError as e:
            text = ""
            self.bar.setText(f"Can't read {path.name}: {e.strerror or e}")
        self.editor.setPlainText(text)
        self.editor.setReadOnly(path is None)
        self.editor.blockSignals(False)
        self.saved_text = text
        self.editor.show_error(0)
        self.bar.setText("" if path is not None else "No scripts yet. New starts one from an example.")
        self.save_btn.setEnabled(path is not None)
        self.delete_btn.setEnabled(path is not None and path.parent == self.mgr.folder)
        self._title()
        if path is not None:
            err = self.mgr.last_error
            if err is not None and err[0] == path and self._running(path) is None:
                self.show_problem(err[1], err[2], running=False)

    def _title(self) -> None:
        name = self.path.name if self.path is not None else ""
        star = " *" if self.dirty() else ""
        self.titlebar.set_title(f"BChat: Scripts - {name}{star}" if name else "BChat: Scripts")

    def _edited(self) -> None:
        if self.editor.error_line:
            self.editor.show_error(0)
        self._title()

    def dirty(self) -> bool:
        return self.path is not None and self.editor.toPlainText() != self.saved_text

    def keep_or_drop(self) -> bool:
        """Unsaved changes: Save, Don't save, or stay. True = go on."""
        if not self.dirty():
            return True
        r = QMessageBox.question(self, "BChat", f"Save the changes to {self.path.name}?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def _ticked(self, it) -> None:
        path = Path(it.data(Qt.ItemDataRole.UserRole))
        on = it.checkState() == Qt.CheckState.Checked
        off = [n for n in self.win.cfg.scripts_off if n.lower() != path.name.lower()]
        running = self._running(path)
        if on and running is None:
            plugin, line, msg = self.mgr.replace(path)
            if plugin is None:
                self.view.blockSignals(True)
                it.setCheckState(Qt.CheckState.Unchecked)
                self.view.blockSignals(False)
                if self.path == path or self.select(path):
                    self.show_problem(line, msg, running=False)
                return
        elif not on:
            if running is not None:
                self.mgr.unload(running)
            if path.parent == self.mgr.folder:
                off.append(path.name)
        self.win.cfg.scripts_off = off
        self.win.save_config()
        if self.path == path:
            self.bar.setText(f"{path.name} is running." if on else f"{path.name} is stopped. It won't start with BChat until you tick it.")
            self.bar.setStyleSheet("")

    # --- buttons ----------------------------------------------------------------------------------------------

    def new_script(self) -> Path | None:
        if not self.keep_or_drop():
            return None
        name, ok = QInputDialog.getText(self, "New script", "Name (letters, numbers, _):", text="my_script")
        name = re.sub(r"\.py$", "", name.strip(), flags=re.I)
        if not ok or not name:
            return None
        if not re.fullmatch(r"[A-Za-z_][\w-]{0,40}", name):
            QMessageBox.information(self, "New script", "Use letters, numbers, - and _ only, starting with a letter.")
            return None
        path = self.mgr.folder / f"{name}.py"
        if path.exists():
            QMessageBox.information(self, "New script", f"{path.name} is already there.")
            self.select(path)
            return None
        self.mgr.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE.format(name=name), "utf-8")
        self.mgr.replace(path)
        self.path = None
        self.fill()
        self.select(path)
        self.bar.setText(f"{path.name} made from the example and running. Change it, then Save and reload.")
        self.bar.setStyleSheet("")
        return path

    def delete_script(self) -> bool:
        path = self.path
        if path is None or path.parent != self.mgr.folder:
            return False
        r = QMessageBox.question(self, "Delete script", f"Stop {path.name} and move it to the Recycle Bin?")
        if r != QMessageBox.StandardButton.Yes:
            return False
        running = self._running(path)
        if running is not None:
            self.mgr.unload(running)
        if not QFile.moveToTrash(str(path)):
            try:
                path.unlink()
            except OSError as e:
                self.bar.setText(f"Couldn't delete {path.name}: {e.strerror or e}")
                return False
        self.win.cfg.scripts_off = [n for n in self.win.cfg.scripts_off if n.lower() != path.name.lower()]
        self.win.save_config()
        self.saved_text = self.editor.toPlainText()        # nothing to ask about: it is gone
        self.path = None
        self.fill()
        return True

    def open_folder(self) -> None:
        self.mgr.folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.mgr.folder)))

    def show_find(self) -> None:
        self.find_row.show()
        cur = self.editor.textCursor()
        if cur.hasSelection() and "\u2029" not in cur.selectedText():
            self.find_box.setText(cur.selectedText())
        self.find_box.setFocus()
        self.find_box.selectAll()

    def find_next(self, back: bool = False) -> bool:
        text = self.find_box.text()
        if not text:
            return False
        flags = QTextDocument.FindFlag.FindBackward if back else QTextDocument.FindFlag(0)
        if self.editor.find(text, flags):
            return True
        cur = self.editor.textCursor()             # wrap around once
        cur.movePosition(QTextCursor.MoveOperation.End if back else QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cur)
        found = self.editor.find(text, flags)
        self.bar.setText("" if found else f"'{text}' isn't in {self.path.name if self.path else 'this script'}.")
        self.bar.setStyleSheet("")
        return found

    def save(self) -> bool:
        """Save, then load the script again. On an error the old version keeps running."""
        path = self.path
        if path is None:
            return False
        text = self.editor.toPlainText()
        try:
            path.write_text(text, "utf-8")
        except OSError as e:
            self.bar.setText(f"Couldn't save {path.name}: {e.strerror or e}")
            self.bar.setStyleSheet(f"color: {self.win.cfg.theme.marker};")
            return False
        self.saved_text = text
        self._title()
        it = self.item_for(path)
        if it is not None and it.checkState() != Qt.CheckState.Checked and self._running(path) is None:
            self.bar.setText(f"Saved. {path.name} is stopped; tick it to run it.")
            self.bar.setStyleSheet("")
            return True
        before = self._running(path)
        plugin, line, msg = self.mgr.replace(path)
        if line or msg:
            self.show_problem(line, msg, running=before is not None)
        else:
            self.editor.show_error(0)
            self.bar.setText(f"Saved and reloaded. {plugin.name} {plugin.version} is running.".replace("  ", " "))
            self.bar.setStyleSheet(f"color: {self.win.cfg.theme.join};")
            self.view.blockSignals(True)
            if it is not None:
                it.setCheckState(Qt.CheckState.Checked)
            self.view.blockSignals(False)
        return True

    def show_problem(self, line: int, msg: str, running: bool) -> None:
        where = f"Line {line}: " if line else ""
        tail = " The old version keeps running." if running else " It isn't running."
        head = "Saved, not reloaded. " if running else ""
        self.bar.setText(f"{head}{where}{msg}.{tail}".replace("..", "."))
        self.bar.setStyleSheet(f"color: {self.win.cfg.theme.marker};")
        self.editor.show_error(line)

    def open_at(self, name: str, line: int = 0) -> None:
        """From an error line's 'Open in Scripts' link."""
        path = next((p for p in self.files() if p.name.lower() == name.lower()), None)
        if path is None or not self.select(path):
            return
        p = self._running(path)
        msg = next((m for ln, m in (p.errors_seen if p else ()) if ln == line), "")
        if msg:
            self.bar.setText(f"Line {line}: {msg}. This happened while it ran; fix it, then Save and reload." if line
                             else f"{msg}. This happened while it ran.")
            self.bar.setStyleSheet(f"color: {self.win.cfg.theme.marker};")
        self.editor.show_error(line)

    def reject(self) -> None:
        if self.keep_or_drop():
            super().reject()

    def closeEvent(self, ev) -> None:
        if self.keep_or_drop():
            super().closeEvent(ev)
        else:
            ev.ignore()
