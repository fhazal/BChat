"""Window > Logs... (0.3.0): read and search the chat logs on disk.
Left: Network > channel > day (newest first). Right: the day in the same look as the chat. A search keeps only the
days with matches, with the count, and marks them; the arrows (or Enter / Shift+Enter, F3) jump between them."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QStackedWidget, QTextEdit,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import logs
from .chatview import ChatView
from .protocol import lower
from .session import ACTION, INFO, JOIN, MSG, NOTICE, PART, SELF, Buffer, Line
from .tools import ToolWindow, button
from .widgets import icon

MAX_LINES = 50000          # a huge one-file log shows its last lines


class LogView(ChatView):
    """The chat view, without the scrollback limit (a whole day stays readable)."""

    def _new_doc(self) -> QTextDocument:
        d = super()._new_doc()
        d.setMaximumBlockCount(0)
        return d


def line_kind(left: str, own: set[str]) -> str:
    if left == "-->":
        return JOIN
    if left == "<--":
        return PART
    if left in ("*", "-", "SSL", ""):
        return INFO
    if len(left) > 2 and left[0] == "-" and left[-1] == "-":
        return NOTICE
    if lower(left) in own:
        return SELF
    return MSG


class LogsWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Logs", win, (940, 560))
        self.cache = logs.TextCache()
        self.focus: tuple[str, str] | None = None     # (network, channel) folder names from View Log
        self.files: list[logs.LogFile] = []
        self.current: logs.LogFile | None = None
        self.buffer: Buffer | None = None
        self.matches: list[QTextCursor] = []
        self.at = -1
        self.counts: dict = {}

        top = QHBoxLayout()
        self.find_label = QLabel("Search:")
        top.addWidget(self.find_label)
        self.find = QLineEdit()
        self.find.setClearButtonEnabled(True)
        self.find.setPlaceholderText("a word or a nick")
        self.find.textChanged.connect(lambda _t: self._search_timer.start())
        self.find.returnPressed.connect(self.next_match)
        top.addWidget(self.find, 1)
        self.scope = QComboBox()
        self.scope.currentIndexChanged.connect(lambda _i: self.fill())
        top.addWidget(self.scope)
        self.body.addLayout(top)
        self._search_timer = QTimer(self, singleShot=True, interval=250, timeout=self.fill)

        self.stack = QStackedWidget()
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda it, _old: self._picked(it))
        split.addWidget(self.tree)
        self.view = LogView(win.cfg)
        split.addWidget(self.view)
        split.setSizes([230, 700])
        split.setStretchFactor(1, 1)
        self.stack.addWidget(split)
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        self.empty_text = QLabel()
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text.setWordWrap(True)
        el.addWidget(self.empty_text)
        row = QHBoxLayout()
        row.addStretch(1)
        self.settings_btn = button("Logging Settings...", lambda: win.open_preferences("Logging"))
        self.settings_btn.setIcon(icon("preferences"))
        row.addWidget(self.settings_btn)
        row.addStretch(1)
        el.addLayout(row)
        el.addStretch(2)
        self.stack.addWidget(empty)
        self.body.addWidget(self.stack, 1)

        bot = QHBoxLayout()
        self.status = QLabel()
        bot.addWidget(self.status)
        self.up_btn = QPushButton(icon("up"), "")
        self.up_btn.setToolTip("Previous match (Shift+Enter)")
        self.up_btn.clicked.connect(self.prev_match)
        self.down_btn = QPushButton(icon("down"), "")
        self.down_btn.setToolTip("Next match (Enter, F3)")
        self.down_btn.clicked.connect(self.next_match)
        for b in (self.up_btn, self.down_btn):
            b.setObjectName("compact")
            b.setAutoDefault(False)
            bot.addWidget(b)
        bot.addStretch(1)
        self.folder_btn = button("Open Folder", self.open_folder)
        self.folder_btn.setIcon(icon("open"))
        bot.addWidget(self.folder_btn)
        close = button("&Close", self.close)
        close.setIcon(icon("close-light"))
        bot.addWidget(close)
        self.body.addLayout(bot)
        QShortcut(QKeySequence("F3"), self, self.next_match)
        QShortcut(QKeySequence("Shift+F3"), self, self.prev_match)
        QShortcut(QKeySequence("Shift+Return"), self.find, self.prev_match)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: (self.find.setFocus(), self.find.selectAll()))

    # --- what is shown ------------------------------------------------------------------

    def show_for(self, network: str | None = None, channel: str | None = None) -> None:
        """Window > Logs... (everything) or View Log on a tab (that channel, its newest day)."""
        self.focus = (network, channel) if network is not None else None
        self.scope.blockSignals(True)
        self.scope.clear()
        if self.focus:
            self.scope.addItems([f"In {channel}", "In all logs"])
        else:
            self.scope.addItems(["In all logs"])
        self.scope.setCurrentIndex(0)
        self.scope.setVisible(self.focus is not None)
        self.scope.blockSignals(False)
        self.current = None
        self.fill()

    def _in_scope(self, f: logs.LogFile) -> bool:
        if self.focus and self.scope.currentIndex() == 0:
            return (f.network, f.channel) == self.focus
        return True

    def fill(self) -> None:
        word = self.find.text().strip()
        everything = logs.scan(self.win.logs_dir())
        self.files = [f for f in everything if self._in_scope(f)]
        self.counts = {}
        if word:
            for f in self.files:
                n = logs.count(self.cache.read(f.path), word)
                if n:
                    self.counts[f.path] = n
            shown = [f for f in self.files if f.path in self.counts]
        else:
            shown = self.files
        for w in (self.find_label, self.find):
            w.setVisible(bool(everything))        # nothing to search yet
        self.scope.setVisible(bool(everything) and self.focus is not None)
        if not everything:
            self.empty_text.setText("No logs yet.\nTurn on logging in Preferences, or right-click a tab > Log to Disk.")
            self.settings_btn.show()
            self.stack.setCurrentIndex(1)
        elif not shown:
            self.empty_text.setText(f"Nothing found for “{word}”." if word else "No logs for this channel yet.")
            self.settings_btn.setVisible(not word)
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)
        keep = self.current.path if self.current is not None else None
        self.tree.blockSignals(True)
        self.tree.clear()
        nets: dict[str, QTreeWidgetItem] = {}
        chans: dict[tuple[str, str], QTreeWidgetItem] = {}
        pick = None
        first_of_focus = None
        for f in shown:
            net = nets.get(f.network)
            if net is None:
                net = nets[f.network] = QTreeWidgetItem([f.network])
                self.tree.addTopLevelItem(net)
            parent = net
            if f.channel:
                parent = chans.get((f.network, f.channel))
                if parent is None:
                    parent = chans[(f.network, f.channel)] = QTreeWidgetItem([f.channel])
                    net.addChild(parent)
            text = f.label()
            if word:
                text += f"   ({self.counts[f.path]})"
            it = QTreeWidgetItem([text])
            it.setData(0, Qt.ItemDataRole.UserRole, str(f.path))
            # newest first: dated files arrive oldest first
            parent.insertChild(0, it) if f.dated else parent.addChild(it)
            if f.path == keep:
                pick = it
            if self.focus and (f.network, f.channel) == self.focus:
                first_of_focus = it           # the last one seen = the newest
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if pick is None:
            pick = first_of_focus or self._first_leaf()
        if pick is not None:
            self.tree.setCurrentItem(pick)
            self.tree.scrollToItem(pick)
            if self.current is not None and str(self.current.path) == pick.data(0, Qt.ItemDataRole.UserRole):
                self._mark()                  # same file: only the marks change
            else:
                self._picked(pick)
        else:
            self.current = None
            self._update_status()

    def _first_leaf(self) -> QTreeWidgetItem | None:
        def walk(it: QTreeWidgetItem):
            if it.data(0, Qt.ItemDataRole.UserRole):
                return it
            for i in range(it.childCount()):
                got = walk(it.child(i))
                if got is not None:
                    return got
            return None
        for i in range(self.tree.topLevelItemCount()):
            got = walk(self.tree.topLevelItem(i))
            if got is not None:
                return got
        return None

    def _picked(self, it: QTreeWidgetItem | None) -> None:
        if it is None:
            return
        path = it.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        f = next((x for x in self.files if str(x.path) == path), None)
        if f is not None:
            self.load(f)

    def _own_nicks(self, f: logs.LogFile) -> set[str]:
        own = {lower(self.win.cfg.nick)} if self.win.cfg.nick else set()
        for s in self.win.sessions.values():
            if self.win._clean(s.net.name) == f.network and s.nick:
                own.add(lower(s.nick))
        return own

    def load(self, f: logs.LogFile) -> None:
        self.current = f
        text = self.cache.read(f.path)
        rows = text.splitlines()
        cut = len(rows) > MAX_LINES
        if cut:
            rows = rows[-MAX_LINES:]
        own = self._own_nicks(f)
        b = Buffer(None, f.channel or f.path.stem, "channel")
        stamp_format = self.win.cfg.log_stamp_format
        for raw in rows:
            if not raw.strip():
                continue
            ts, left, body = logs.parse_line(raw, stamp_format, f)
            b.lines.append(Line(line_kind(left, own), left, body, ts))
        if cut:
            b.lines.insert(0, Line(INFO, "*", f"Showing the last {MAX_LINES} lines. Open Folder has the whole file."))
        old = self.buffer
        self.buffer = b
        self.view.show_buffer(b)
        if old is not None:
            self.view.forget(old)
        self._mark()

    # --- search marks ---------------------------------------------------------------------

    def _mark(self) -> None:
        word = self.find.text().strip()
        self.matches = []
        doc = self.view.document()
        if word:
            cur = QTextCursor(doc)
            while True:
                cur = doc.find(word, cur)
                if cur.isNull():
                    break
                self.matches.append(QTextCursor(cur))
        self.at = 0 if self.matches else -1
        self._paint()
        if self.matches:
            self._go()
        else:
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        self._update_status()

    def _paint(self) -> None:
        t = self.win.cfg.theme
        sels = []
        for i, c in enumerate(self.matches):
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(t.palette[7] if i == self.at else t.palette[8]))
            fmt.setForeground(QColor("#11111b"))
            s = QTextEdit.ExtraSelection()
            s.cursor, s.format = c, fmt
            sels.append(s)
        self.view.setExtraSelections(sels)

    def _go(self) -> None:
        c = QTextCursor(self.matches[self.at])
        c.clearSelection()
        self.view.setTextCursor(c)
        self.view.ensureCursorVisible()

    def next_match(self) -> None:
        self._step(1)

    def prev_match(self) -> None:
        self._step(-1)

    def _step(self, d: int) -> None:
        if not self.matches:
            return
        self.at = (self.at + d) % len(self.matches)
        self._paint()
        self._go()
        self._update_status()

    def _update_status(self) -> None:
        word = self.find.text().strip()
        here = "this day" if self.current is not None and self.current.day else "this log"
        if word:
            total = sum(self.counts.values())
            where = self.scope.currentText().replace("In ", "in ", 1) if self.scope.count() else "in all logs"
            n = len(self.matches)
            self.status.setText(f"{self.at + 1 if n else 0} of {n} in {here}, {total} {where}" if n else f"0 in {here}, {total} {where}")
        elif self.current is not None and self.buffer is not None:
            self.status.setText(f"{len(self.buffer.lines)} lines")
        else:
            self.status.setText("")
        for b in (self.up_btn, self.down_btn):
            b.setVisible(bool(word))
            b.setEnabled(len(self.matches) > 1)

    def open_folder(self) -> None:
        d = self.current.path.parent if self.current is not None else self.win.logs_dir()
        if not d.is_dir():
            self.win.open_logs_folder()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
