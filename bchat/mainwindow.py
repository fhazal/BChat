"""BChat main window, classic XChat 2 layout, dark."""
from __future__ import annotations

import html
import re
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence, QPixmap, QTextDocument
from PySide6.QtWidgets import (QToolButton, QApplication, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetAction)

from . import __version__, commands, config
from .chatview import ChatView
from .config import Config, NetworkConfig, Server
from .protocol import lower, strip_format
from .session import CHANNEL, INFO, QUERY, SERVER, Buffer, Session, User
from .countries import country_of
from .userlist import UserList, icon_name, light_pixmap
from .widgets import ASSETS, FramedDialog, FramelessWindow, icon, stylesheet
from . import xchat_import
from .topicbar import TopicBar, emoji_popup


class _CopyLabel(QLabel):
    """A value in the nick info panel. Plain text only; a click copies it, as XChat does."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.value = ""

    def set_value(self, v: str) -> None:
        self.value = v
        self.setText(v or "Unknown")
        f = self.font()
        f.setItalic(not v)
        self.setFont(f)

    def mousePressEvent(self, ev):
        if self.value:
            QApplication.clipboard().setText(self.value)


class InputBox(QLineEdit):
    """History on up/down, nick completion on Tab."""

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.history: list[str] = []
        self.pos_ = 0
        self._cycle: list[str] = []
        self._cycle_i = 0
        self._cycle_start = 0
        self._cycle_text = ""

    def event(self, ev):
        if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Tab:
            self._complete()
            return True
        return super().event(ev)

    FORMAT_KEYS = {Qt.Key.Key_B: "\x02", Qt.Key.Key_K: "\x03", Qt.Key.Key_U: "\x1f", Qt.Key.Key_O: "\x0f"}

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        bar = self.win.chat.verticalScrollBar()
        if ev.matches(QKeySequence.StandardKey.Paste):
            pasted = QApplication.clipboard().text()
            if "\n" in pasted.strip():
                self.win.paste_lines(pasted)
                return
        if ev.key() in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and mods == Qt.KeyboardModifier.NoModifier:
            bar.setValue(bar.value() + (bar.pageStep() if ev.key() == Qt.Key.Key_PageDown else -bar.pageStep()))
        elif mods == Qt.KeyboardModifier.ShiftModifier and ev.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar.setValue(bar.value() + (bar.singleStep() if ev.key() == Qt.Key.Key_Down else -bar.singleStep()))
        elif mods == Qt.KeyboardModifier.ControlModifier and ev.key() in self.FORMAT_KEYS:
            self.insert(self.FORMAT_KEYS[ev.key()])  # bold, colour, underline, reset
        elif ev.key() == Qt.Key.Key_Up and self.history:
            self.pos_ = max(0, self.pos_ - 1)
            self.setText(self.history[self.pos_])
        elif ev.key() == Qt.Key.Key_Down:
            self.pos_ = min(len(self.history), self.pos_ + 1)
            self.setText(self.history[self.pos_] if self.pos_ < len(self.history) else "")
        else:
            self._cycle = []
            super().keyPressEvent(ev)

    def remember(self, text: str) -> None:
        self.history.append(text)
        del self.history[:-200]
        self.pos_ = len(self.history)

    def _candidates(self, word: str, at_start: bool) -> list[str]:
        b = self.win.buf
        s = b.session
        low = lower(word)
        if at_start and word.startswith("/"):
            return ["/" + c for c in commands.COMMAND_NAMES if c.startswith(low[1:])]
        if s.is_channel(word):
            return [x.name for x in s.buffers.values() if x.kind == CHANNEL and lower(x.name).startswith(low)]
        names = [u.nick for u in b.sorted_users() if lower(u.nick).startswith(low)]
        if b.kind == QUERY and lower(b.name).startswith(low):
            names.append(b.name)
        return names

    def _complete(self) -> None:
        b = self.win.buf
        if b is None:
            return
        text = self.text()
        # the text changed since the last Tab (typing, history), so this is a new completion
        if text != self._cycle_text:
            self._cycle = []
        if not self._cycle:
            cur = self.cursorPosition()
            self._cycle_start = text.rfind(" ", 0, cur) + 1
            word = text[self._cycle_start:cur]
            if not word:
                return
            self._cycle = self._candidates(word, self._cycle_start == 0)
            self._cycle_i = 0
            if not self._cycle:
                return
        item = self._cycle[self._cycle_i % len(self._cycle)]
        self._cycle_i += 1
        is_nick = not item.startswith("/") and not b.session.is_channel(item)
        self.setText(text[: self._cycle_start] + item + (": " if is_nick and self._cycle_start == 0 else " "))
        self._cycle_text = self.text()


class MainWindow(FramelessWindow):
    def __init__(self, cfg: Config, cfg_dir: Path):
        super().__init__()
        self.cfg = cfg
        self.cfg_dir = cfg_dir
        self.sessions: dict[str, Session] = {}
        self.buf: Buffer | None = None
        self.items: dict[int, QTreeWidgetItem] = {}
        self.raw_log: QPlainTextEdit | None = None
        self.raw_lines: list[str] = []
        self.setWindowIcon(QIcon(str(ASSETS / "bchat.ico")))
        self.setStyleSheet(stylesheet(cfg.theme))
        self.resize(cfg.win_width, cfg.win_height)
        if cfg.win_x >= 0 and QGuiApplication.screenAt(QPoint(cfg.win_x + 50, cfg.win_y + 10)) is not None:
            self.move(cfg.win_x, cfg.win_y)
        self._build()
        self._build_menus()
        self._refresh_all()

    # --- layout ---------------------------------------------------------------

    def _build(self) -> None:
        self.menubar_ = self.menuBar()
        self.menubar_.setNativeMenuBar(False)
        self.outer.addWidget(self.menubar_)

        body = QWidget(self.root)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)
        self.split = QSplitter(Qt.Orientation.Horizontal, body)
        self.split.setHandleWidth(3)
        self.split.setChildrenCollapsible(False)

        self.tree = QTreeWidget(self.split)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setRootIsDecorated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._tree_selected)

        mid = QWidget(self.split)
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(3)
        self.topic = TopicBar(self.cfg.theme, mid)
        self.topic.submitted.connect(self._topic_entered)
        ml.addWidget(self.topic)
        self.chat = ChatView(self.cfg, mid)
        self.chat.menu_provider = self._chat_menu
        self.chat.channel_double_clicked.connect(self._join_clicked)
        ml.addWidget(self.chat, 1)

        right = QWidget(self.split)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(3)
        self.count = QLabel(right, objectName="count")
        self.count.setTextFormat(Qt.TextFormat.PlainText)
        rl.addWidget(self.count)
        self.userlist = UserList(self.cfg.theme, right)
        self.userlist.doubleClicked.connect(self._nick_double)
        self.userlist.customContextMenuRequested.connect(self._nick_menu)
        rl.addWidget(self.userlist, 1)
        self.right_panel = right

        self.split.addWidget(self.tree)
        self.split.addWidget(mid)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([self.cfg.pane_left, 720, self.cfg.pane_right])
        lay.addWidget(self.split, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(3)
        self.own_light = QLabel(body)
        self.own_light.setFixedSize(8, 19)  # one spare pixel, as 7 px at 150 % is really 7.33
        self.own_light.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom.addSpacing(4)
        bottom.addWidget(self.own_light)
        self.nick_label = QLabel(body, objectName="nicklabel")
        self.nick_label.installEventFilter(self)
        self.nick_label.setToolTip("Click to change your nick")
        self.nick_label.setTextFormat(Qt.TextFormat.PlainText)
        bottom.addWidget(self.nick_label)
        self.input = InputBox(self)
        self.input.returnPressed.connect(self._entered)
        bottom.addWidget(self.input, 1)
        self.emoji_btn = QToolButton(body)
        self.emoji_btn.setText("\U0001F642")
        self.emoji_btn.setToolTip("Emoji (Windows: Win + . for all of them)")
        self.emoji_btn.setStyleSheet("QToolButton { font-family: 'Segoe UI Emoji'; }")
        self.emoji_btn.clicked.connect(self._emoji_for_input)
        bottom.addWidget(self.emoji_btn)
        self.status_strip = QLabel(body)
        self.status_strip.setFixedWidth(3)
        self._status_colour = ""
        bottom.addWidget(self.status_strip)
        # lag grows while a ping goes unanswered, with no event to react to
        self._status_timer = QTimer(self, interval=1000, timeout=self._refresh_status)
        self._status_timer.start()
        lay.addLayout(bottom)
        self.outer.addWidget(body, 1)

        self.topic.setVisible(self.cfg.show_topic)
        self.menubar_.setVisible(self.cfg.show_menu)

    def _act(self, menu: QMenu, text: str, slot=None, shortcut: str = "", ico: str = "", checkable=False, checked=False) -> QAction:
        a = QAction(text, self)
        if ico:
            a.setIcon(icon(ico))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if checkable:
            a.setCheckable(True)
            a.setChecked(checked)
        if slot is not None:
            (a.toggled if checkable else a.triggered).connect(slot)
        else:
            a.setEnabled(False)
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_menus(self) -> None:
        m = self.menubar_
        x = m.addMenu("&BChat")
        self._act(x, "Network Li&st...", self.open_network_list, "Ctrl+S", "book")
        new = x.addMenu(icon("new"), "&New")
        self._act(new, "Server Tab...", self.new_server_tab, "Ctrl+T")
        self._act(new, "Channel Tab...", self._join_dialog)
        self._act(new, "Server Window...")
        self._act(new, "Channel Window...")
        x.addSeparator()
        self._act(x, "&Load Plugin or Script...", None, "", "revert")
        self._act(x, "&Import XChat Settings...", self._import_settings, "", "open")
        x.addSeparator()
        self._act(x, "&Detach", None, "Ctrl+I", "dialog")
        self._act(x, "&Close", lambda: self.close_buffer(self.buf), "Ctrl+W", "close-light")
        x.addSeparator()
        self._act(x, "&Quit", self.close, "Ctrl+Q", "quit")

        v = m.addMenu("&View")
        self._act(v, "&Menu Bar", self._toggle_menu, "Ctrl+F9", checkable=True, checked=self.cfg.show_menu)
        self._act(v, "&Topic Bar", self._toggle_topic, checkable=True, checked=self.cfg.show_topic)
        self._act(v, "&User List", self._toggle_userlist, "Ctrl+F7", checkable=True, checked=self.cfg.show_userlist)
        self._act(v, "U&serlist Buttons")
        self._act(v, "M&ode Buttons")
        v.addSeparator()
        cs = v.addMenu("&Channel Switcher")
        self._act(cs, "&Tabs")
        self._act(cs, "T&ree", lambda: None, checkable=True, checked=True)
        nm = v.addMenu("&Network Meters")
        self._act(nm, "Off")
        self._act(nm, "Graph")
        self._act(nm, "Text")
        self._act(nm, "Both")

        s = m.addMenu("&Server")
        self._act(s, "&Disconnect", lambda: self.session and self.session.disconnect_from_network(), "", "disconnect")
        self._act(s, "&Reconnect", lambda: self.session and self.session.reconnect(), "", "connect")
        self._act(s, "Join a Channel...", self._join_dialog, "", "jump")
        self._act(s, "List of Channels...", lambda: self.session and self.session.send("LIST"), "", "justify")
        s.addSeparator()
        self.away_act = self._act(s, "Marked Away", self._toggle_away, "Alt+A", checkable=True)

        st = m.addMenu("S&ettings")
        self._act(st, "&Preferences", self.open_preferences, "", "preferences")
        adv = st.addMenu(icon("justify"), "Advanced")
        for name in ("Auto Replace...", "CTCP Replies...", "Dialog Buttons...", "Keyboard Shortcuts...", "Text Events...",
                     "URL Handlers...", "User Commands...", "Userlist Buttons...", "Userlist Popup..."):
            self._act(adv, name)

        w = m.addMenu("&Window")
        for name in ("Ban List...", "Character Chart...", "Direct Chat...", "File Transfers...", "Friends List...",
                     "Ignore List...", "Plugins and Scripts..."):
            self._act(w, name)
        self._act(w, "Raw Log...", self._open_raw_log)
        self._act(w, "URL Grabber...")
        w.addSeparator()
        self._act(w, "Reset Marker Line", self.chat.reset_marker, "Ctrl+M")
        self._act(w, "C&lear Text", self._clear_current, "Ctrl+L", "clear")
        self._act(w, "Search Text...", self._search, "Ctrl+F", "find")
        self._act(w, "Save Text...", self._save_text, "", "save")

        h = m.addMenu("&Help")
        self._act(h, "&Contents", None, "F1", "help")
        self._act(h, "&About", self._about, "", "about")

        for key, delta in (("Ctrl+PgUp", -1), ("Ctrl+PgDown", 1)):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, d=delta: self._change_page(delta=d))
            self.addAction(a)
        for n in range(1, 10):
            a = QAction(self)
            a.setShortcut(QKeySequence(f"Alt+{n}"))
            a.triggered.connect(lambda _=False, i=n: self._change_page(number=i))
            self.addAction(a)

    # --- sessions -------------------------------------------------------------

    @property
    def session(self) -> Session | None:
        return self.buf.session if self.buf is not None else None

    def session_for(self, net: NetworkConfig) -> Session:
        s = self.sessions.get(net.name)
        if s is None:
            s = Session(net, self.cfg, self)
            self.sessions[net.name] = s
            s.buffer_added.connect(self._buffer_added)
            s.buffer_removed.connect(self._buffer_removed)
            s.buffer_changed.connect(self._buffer_changed)
            s.users_changed.connect(self._users_changed)
            s.line_added.connect(self.chat.add_line)
            s.line_added.connect(self._log_line)
            s.alert.connect(self._flash)
            s.state_changed.connect(self._state_changed)
            s.raw_line.connect(self._raw)
            self._buffer_added(s.server_buffer)
        return s

    def connect_network(self, net: NetworkConfig) -> Session:
        s = self.session_for(net)
        if s.state == "disconnected":
            s.connect_to_network()
        self.select_buffer(s.server_buffer)
        return s

    def server_command(self, s: Session, host: str, port: int, ssl: bool, password: str) -> None:
        """/server: this tab now belongs to the new host, so the Network List can still open the old network later."""
        for key, value in list(self.sessions.items()):
            if value is s:
                del self.sessions[key]
        name = host
        n = 2
        while name in self.sessions:
            name = f"{host} ({n})"
            n += 1
        s.connect_manual(host, port, ssl, password)
        self.sessions[name] = s
        self.select_buffer(s.server_buffer)

    def new_server_tab(self) -> Session:
        """An empty tab with no server yet, like XChat's: the user types /server in it."""
        name = "<none>"
        n = 2
        while name in self.sessions:
            name = f"<none> ({n})"
            n += 1
        s = self.session_for(NetworkConfig(name))
        s.add(s.server_buffer, INFO, "*", "Type /server <host> [port or +port for SSL] to connect, for example /server irc.bajubesi.org +6697")
        self.select_buffer(s.server_buffer)
        self.input.setFocus()
        return s

    def autoconnect(self) -> None:
        first = True
        for net in self.cfg.networks:
            if net.autoconnect:
                s = self.session_for(net)
                s.connect_to_network()
                if first:
                    self.select_buffer(s.server_buffer)
                    first = False

    # --- buffers and tree -------------------------------------------------------

    def _buffer_added(self, b: Buffer) -> None:
        it = QTreeWidgetItem()
        it.setText(0, b.name)
        it.setData(0, Qt.ItemDataRole.UserRole, b)
        self.items[id(b)] = it
        self.chat.doc_for(b)
        if b.kind == SERVER:
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)
        else:
            parent = self.items.get(id(b.session.server_buffer))
            parent.addChild(it)
            parent.setExpanded(True)
            # a new tab only takes the front when nothing is being read, or the user asked for it
            asked = lower(b.name) == b.session.focus_next
            reading_server = self.buf is None or (self.buf.kind == SERVER and self.buf.session is b.session)
            if asked or (b.kind == CHANNEL and reading_server):
                b.session.focus_next = ""
                self.select_buffer(b)

    def _buffer_removed(self, b: Buffer) -> None:
        it = self.items.pop(id(b), None)
        if it is not None:
            (it.parent() or self.tree.invisibleRootItem()).removeChild(it)
        self.chat.forget(b)
        if self.buf is b:
            self.buf = None
            self.select_buffer(b.session.server_buffer)

    def _buffer_changed(self, b: Buffer) -> None:
        it = self.items.get(id(b))
        if it is not None:
            it.setText(0, b.name)
            t = self.cfg.theme
            colour = {0: t.text, 1: t.new_data, 2: t.new_msg, 3: t.new_highlight}.get(b.activity, t.text)
            if b.kind == CHANNEL and not b.joined:
                colour = t.away
            it.setForeground(0, QColor(colour))
        if b is self.buf:
            self.topic.set_topic(b.topic)
            self._topic_permission()
            self._refresh_title()
            if not b.lines:
                self.chat.reload(b)

    def _users_changed(self, b: Buffer) -> None:
        if b is self.buf:
            self._topic_permission()   # own op/deop changes who may set the topic
            self.userlist.set_buffer(b)
            self._refresh_count()
            self._refresh_title()

    def _state_changed(self) -> None:
        self._refresh_title()
        s = self.session
        if s is not None:
            self.away_act.blockSignals(True)
            self.away_act.setChecked(s.away)
            self.away_act.blockSignals(False)

    def select_buffer(self, b: Buffer | None) -> None:
        if b is None:
            return
        it = self.items.get(id(b))
        if it is not None and self.tree.currentItem() is not it:
            self.tree.setCurrentItem(it)
        elif it is not None:
            self._show(b)

    def _tree_selected(self, cur, _prev) -> None:
        if cur is not None:
            self._show(cur.data(0, Qt.ItemDataRole.UserRole))

    def _show(self, b: Buffer) -> None:
        self.buf = b
        b.session.current = b
        if b.activity:
            b.activity = 0
            self._buffer_changed(b)
        self.chat.show_buffer(b)
        self._refresh_all()
        self.input.setFocus()

    def reload_buffer(self, b: Buffer) -> None:
        self.chat.reload(b)

    def close_buffer(self, b: Buffer | None) -> None:
        if b is None:
            return
        s = b.session
        if b.kind == SERVER:
            others = len(s.buffers)
            if others and not getattr(self, "skip_quit_prompt", False):
                r = QMessageBox.question(self, "Close server tab", f"This server still has {others} channels or dialogs associated with it. Close them all?")
                if r != QMessageBox.StandardButton.Yes:
                    return
            s.disconnect_from_network()
            for other in list(s.buffers.values()):
                s.close_buffer(other)
            self._buffer_removed_server(s)
        else:
            s.close_buffer(b)

    def _buffer_removed_server(self, s: Session) -> None:
        b = s.server_buffer
        it = self.items.pop(id(b), None)
        if it is not None:
            self.tree.invisibleRootItem().removeChild(it)
        self.chat.forget(b)
        self.sessions.pop(s.net.name, None)
        s.deleteLater()
        if self.buf is b:
            self.buf = None
            first = self.tree.topLevelItem(0)
            if first is not None:
                self.tree.setCurrentItem(first)
            else:
                self.chat.show_buffer(None)
                self._refresh_all()

    def _decide_userlist(self) -> None:
        """XChat's mg_decide_userlist: only channel tabs have a nick list, so server and private tabs get the full width."""
        self.right_panel.setVisible(self.cfg.show_userlist and self.buf is not None and self.buf.kind == CHANNEL)

    def _refresh_all(self) -> None:
        b = self.buf
        self._decide_userlist()
        self.topic.edit.clearFocus()
        self.topic.set_topic(b.topic if b else "")
        self.topic.setEnabled(bool(b and b.kind == CHANNEL))
        self._topic_permission()
        self.userlist.set_buffer(b if b and b.kind == CHANNEL else None)
        self._refresh_count()
        self._refresh_title()

    def _refresh_count(self) -> None:
        b = self.buf
        if b is not None and b.kind == CHANNEL:
            ops, total = b.counts()
            self.count.setText(f"{ops} ops, {total} total")
        else:
            self.count.setText("")

    def _refresh_nick(self) -> None:
        s = self.session
        self.nick_label.setText(s.nick if s else (self.cfg.nick or "BChat"))
        # greyed while away, as in XChat
        self.nick_label.setStyleSheet(f"color: {self.cfg.theme.away};" if s and s.away and s.state == "connected" else "")
        name = icon_name(s.prefix_order, s.own_rank(self.buf)) if s and self.buf.kind == CHANNEL else None
        self.own_light.setPixmap(light_pixmap(name, self.devicePixelRatioF()) or QPixmap())

    def status_info(self) -> tuple[str, str]:
        """The strip's meaning: (state, plain tooltip text). The strip follows the tab being read."""
        s = self.session
        if s is None:
            return "off", "Not connected"
        where = s.server_name or (s.net.servers[s.server_index].host if s.net.servers and s.server_index >= 0 else s.net.name)
        if s.state in ("connecting", "registering"):
            return "connecting", f"Connecting · {where}"
        if s.state != "connected":
            return "off", f"Not connected · {s.net.name}" if s.net.servers else "Not connected"
        parts = ["Connected", where]
        if getattr(s, "_tls_now", False):
            parts.append("SSL")
        lag = s.current_lag_ms()
        if lag is not None:
            parts.append(f"lag {lag} ms")
        order = s.prefix_order
        rank = s.own_rank(self.buf) if self.buf.kind == CHANNEL else ""
        is_op = bool(rank) and "@" in order and order.index(rank) <= order.index("@")
        if is_op:
            parts.append(f"op in {self.buf.name}")
        state = "lag" if lag is not None and lag > s.LAG_WARN_MS else ("op" if is_op else "on")
        return state, " · ".join(parts)

    def _refresh_status(self) -> None:
        state, tip = self.status_info()
        t = self.cfg.theme
        colour = {"off": t.status_off, "connecting": t.status_connecting, "on": t.status_on,
                  "op": t.status_op, "lag": t.status_lag}[state]
        if colour != self._status_colour:
            self._status_colour = colour
            self.status_strip.setStyleSheet(f"background: {colour};")
        # server and channel names come from the network, and tooltips would otherwise read them as markup
        self.status_strip.setToolTip("<qt>" + html.escape(tip) + "</qt>")

    def _refresh_title(self) -> None:
        self._refresh_nick()
        self._refresh_status()
        b = self.buf
        if b is None:
            self.setWindowTitle("BChat")
            return
        s = b.session
        if not s.net.servers:
            self.setWindowTitle("BChat")
            return
        host = s.server_name or s.net.name
        if b.kind == CHANNEL:
            modes = b.mode_text()
            inside = " ".join(x for x in (modes, str(len(b.users)) if b.users else "") if x)
            tail = f" ({inside})" if inside else ""
            self.setWindowTitle(f"BChat: {s.nick} @ {host} / {b.name}{tail}")
        elif b.kind == QUERY:
            self.setWindowTitle(f"BChat: {s.nick} @ {host} / {b.name}")
        else:
            self.setWindowTitle(f"BChat: {s.nick} @ {host}" if s.state != "disconnected" else f"BChat: {host} (not connected)")

    # --- input ------------------------------------------------------------------

    def _entered(self) -> None:
        text = self.input.text()
        self.input.clear()
        if not text:
            return
        self.input.remember(text)
        if self.buf is None:
            word = text.split()
            if word[0].lower() in ("/server", "/newserver"):
                commands.new_server(self, word[1:])
            else:
                self.open_network_list()
            return
        commands.run(self, self.buf.session, self.buf, text)

    def _topic_entered(self, text: str) -> None:
        b = self.buf
        if b is not None and b.kind == CHANNEL:
            b.session.send("TOPIC", b.name, text)
            self.input.setFocus()

    def _emoji_for_input(self) -> None:
        p = emoji_popup(self.cfg.theme, self)
        p.picked.connect(lambda e: (self.input.insert(e), self.input.setFocus()))
        p.show_below(self.emoji_btn)
        self._emoji_popup = p

    def _topic_permission(self) -> None:
        """+t channels: only halfop and up may set the topic (Unreal and InspIRCd allow % too)."""
        b = self.buf
        if b is None or b.kind != CHANNEL:
            return
        s = b.session
        order = s.prefix_order or "@+"
        rank = s.own_rank(b)
        top = order.index("%") if "%" in order else (order.index("@") if "@" in order else -1)
        ok = "t" not in b.modes or (rank != "" and order.index(rank) <= top)
        self.topic.set_allowed(ok, "Only channel operators can change the topic here (+t)")

    # --- nick list actions ---------------------------------------------------------

    def _nick_double(self, index) -> None:
        u: User = index.data(Qt.ItemDataRole.UserRole)
        self.session.whois(u.nick)

    def _nick_menu(self, pos) -> None:
        b = self.buf
        if b is None:
            return
        idx = self.userlist.indexAt(pos)
        if idx.isValid() and not self.userlist.selectionModel().isSelected(idx):
            self.userlist.setCurrentIndex(idx)
        users = self.userlist.selected_users()
        if users:
            self.build_nick_menu(b, users).exec(self.userlist.viewport().mapToGlobal(pos))

    def build_nick_menu(self, b: Buffer, users: list[User]) -> QMenu:
        s = b.session
        menu = QMenu(self)
        nicks = [u.nick for u in users]
        one = users[0]
        if len(users) == 1:
            head = menu.addMenu(one.nick)
            self._info_panel(head, s, b, one)
        else:
            head = menu.addAction(f"{len(users)} nicks selected.")
            head.setEnabled(False)
        menu.addSeparator()
        menu.addAction(icon("dialog"), "Open Dialog Window", lambda: [self.select_buffer(s.buffer(n)) for n in nicks])
        send = menu.addAction(icon("save"), "Send a File")
        send.setEnabled(False)
        menu.addAction(icon("info"), "User Info (WhoIs)", lambda: [s.whois(n) for n in nicks])
        friend = menu.addAction(icon("add"), "Add to Friends List")
        friend.setEnabled(False)
        ops = menu.addMenu("Operator Actions")
        ops.addAction("Give Ops", lambda: s.set_mode_for(b, "+o", nicks))
        ops.addAction("Take Ops", lambda: s.set_mode_for(b, "-o", nicks))
        ops.addSeparator()
        ops.addAction("Give Voice", lambda: s.set_mode_for(b, "+v", nicks))
        ops.addAction("Take Voice", lambda: s.set_mode_for(b, "-v", nicks))
        ops.addSeparator()
        kb = ops.addMenu("Kick/Ban")
        kb.addAction("Kick", lambda: self._kick(b, nicks))
        kb.addAction("Ban", lambda: [s.ban(b, n, 0) for n in nicks])
        kb.addSeparator()
        masks = ("*!*@*.host", "*!*@domain", "*!*user@*.host", "*!*user@domain")
        for i, mask in enumerate(masks):
            kb.addAction(f"Ban {mask}", lambda i=i: [s.ban(b, n, i) for n in nicks])
        kb.addSeparator()
        for i, mask in enumerate(masks):
            kb.addAction(f"KickBan {mask}", lambda i=i: [s.ban(b, n, i, kick=True) for n in nicks])
        return menu

    def _info_panel(self, head: QMenu, s: Session, b: Buffer, u: User) -> None:
        """XChat's nick submenu: click a row to copy it. Text comes from the network, so it is always shown as plain text."""
        box = QWidget(head)
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 6, 12, 6)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        mono = QFont("Consolas", 9)
        mono.setBold(True)
        labels: dict[str, _CopyLabel] = {}
        for i, key in enumerate(("Real Name:", "User:", "Country:", "Server:", "Last Msg:", "Away Msg:")):
            kl = QLabel(key, box)
            kl.setFont(mono)
            kl.setTextFormat(Qt.TextFormat.PlainText)
            vl = _CopyLabel(box)
            grid.addWidget(kl, i, 0)
            grid.addWidget(vl, i, 1)
            labels[key] = vl
            labels[key + "key"] = kl

        def fill() -> None:
            mins = int((time.time() - u.last_msg) // 60) if u.last_msg else None
            values = {"Real Name:": strip_format(u.realname), "User:": u.host, "Country:": u.country or (country_of(u.host) if u.host else ""),
                      "Server:": u.server, "Last Msg:": f"{mins} minutes ago" if mins is not None else ""}
            for key, v in values.items():
                labels[key].set_value(v)
            show_away = u.away
            labels["Away Msg:"].set_value(strip_format(u.away_reason))
            labels["Away Msg:"].setVisible(show_away)
            labels["Away Msg:key"].setVisible(show_away)

        fill()
        act = QWidgetAction(head)
        act.setDefaultWidget(box)
        head.addAction(act)

        def fresh(nick: str) -> None:
            if lower(nick) == lower(u.nick):
                fill()
                box.adjustSize()
                head.adjustSize()

        def shown() -> None:
            # only ask the server when something is really missing, like XChat
            if not (u.host and u.realname and u.server) or (u.away and not u.away_reason):
                s.silent_whois(u.nick)
        head.aboutToShow.connect(shown)
        s.user_info.connect(fresh)
        head.destroyed.connect(lambda: self._safe_disconnect(s, fresh))

    @staticmethod
    def _safe_disconnect(s: Session, slot) -> None:
        try:
            s.user_info.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def _kick(self, b: Buffer, nicks: list[str]) -> None:
        for n in nicks:
            b.session.send("KICK", b.name, n, self.cfg.part_reason)

    def _tree_menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        if it is None:
            return
        b: Buffer = it.data(0, Qt.ItemDataRole.UserRole)
        s = b.session
        menu = QMenu(self)
        title = menu.addAction(b.name)
        title.setEnabled(False)
        menu.addSeparator()
        if b.kind == CHANNEL:
            menu.addAction("Leave Channel", lambda: s.send("PART", b.name, self.cfg.part_reason))
        if b.kind != SERVER:
            menu.addAction("Rejoin Channel" if b.kind == CHANNEL else "WhoIs",
                           (lambda: s.send("JOIN", b.name)) if b.kind == CHANNEL else (lambda: s.whois(b.name)))
        else:
            menu.addAction("Join Channel...", self._join_dialog)
            menu.addAction("Reconnect", s.reconnect)
            menu.addAction("Disconnect", s.disconnect_from_network)
            menu.addAction("Server Links", lambda: s.send("LINKS"))
            menu.addSeparator()
            if s.net in self.cfg.networks:   # AdiIRC: Edit Network once it is saved, Add Network before
                menu.addAction("Edit Network...", lambda: self.edit_network(s.net))
            elif s.net.servers:
                menu.addAction(icon("connect"), "Add Network", lambda: self.add_network_from(s))
        menu.addSeparator()
        log = menu.addAction("Log to Disk")
        log.setCheckable(True)
        log.setChecked(self._log_key(b) in self.cfg.log_tabs)
        log.toggled.connect(lambda on: self._set_logging(b, on))
        menu.addSeparator()
        menu.addAction(icon("close-light"), "Close", lambda: self.close_buffer(b))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # --- menu actions --------------------------------------------------------------

    def _change_page(self, delta: int = 0, number: int = 0) -> None:
        """Ctrl+PageUp/Down and Alt+1-9 move through the tree in order, like XChat's default keys."""
        order = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            order.append(top)
            order.extend(top.child(j) for j in range(top.childCount()))
        if not order:
            return
        if number:
            if number <= len(order):
                self.tree.setCurrentItem(order[number - 1])
            return
        cur = self.tree.currentItem()
        at = order.index(cur) if cur in order else 0
        self.tree.setCurrentItem(order[(at + delta) % len(order)])

    # --- chat clicks ---------------------------------------------------------------

    def open_url(self, url: str) -> None:
        link = QUrl(url if "://" in url else "http://" + url)
        if link.scheme().lower() in ("http", "https", "ftp"):
            QDesktopServices.openUrl(link)

    def _join_clicked(self, name: str) -> None:
        s = self.session
        if s is None or not s.is_channel(name):
            return
        existing = s.buffers.get(lower(name))
        if existing is not None:
            self.select_buffer(existing)
        else:
            s.focus_next = lower(name)
        s.send("JOIN", name)

    def _chat_menu(self, pos) -> QMenu:
        """Right click in the chat: on a link, a nick or a channel it offers those, as in XChat."""
        b, s = self.buf, self.session
        href = self.chat.anchorAt(pos)
        word = self.chat.word_at(pos)
        user = b.users.get(lower(word)) if b is not None and word else None
        if user is not None and not href:
            return self.build_nick_menu(b, [user])
        menu = QMenu(self)
        if href:
            menu.addAction("Open Link in Browser", lambda: self.open_url(href))
            menu.addAction("Copy Link", lambda: QApplication.clipboard().setText(href))
            menu.addSeparator()
        elif s is not None and word and s.is_channel(word):
            menu.addAction(f"Join {word}", lambda: self._join_clicked(word))
            menu.addSeparator()
        copy = menu.addAction(icon("copy"), "Copy Selection", self.chat.copy)
        copy.setEnabled(self.chat.textCursor().hasSelection())
        menu.addAction("Select All", self.chat.selectAll)
        menu.addSeparator()
        menu.addAction(icon("clear"), "Clear Text", self._clear_current)
        menu.addAction(icon("find"), "Search Text...", self._search)
        return menu

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "nick_label", None) and ev.type() == QEvent.Type.MouseButtonPress:
            s = self.session
            if s is not None and s.state == "connected":
                nick, ok = QInputDialog.getText(self, "Change nick", "Enter new nickname:", text=s.nick)
                if ok and nick.strip():
                    s.send("NICK", nick.strip().split()[0])
            return True
        return super().eventFilter(obj, ev)

    def _flash(self, b: Buffer) -> None:
        if not self.isActiveWindow():
            QApplication.alert(self)

    # --- logging: per tab, from the tab's right-click menu ----------------------------

    @staticmethod
    def _log_key(b: Buffer) -> str:
        return f"{lower(b.session.net.name)}/{lower(b.name)}"

    def _set_logging(self, b: Buffer, on: bool) -> None:
        key = self._log_key(b)
        if on and key not in self.cfg.log_tabs:
            self.cfg.log_tabs.append(key)
        elif not on and key in self.cfg.log_tabs:
            self.cfg.log_tabs.remove(key)
        config.save(self.cfg, self.cfg_dir)

    def log_path(self, b: Buffer) -> Path:
        # names come from the network, so nothing in them may reach outside the logs folder
        clean = lambda name: re.sub(r"[^\w#&+-]", "_", name) or "_"
        return self.cfg_dir / "logs" / clean(b.session.net.name) / f"{clean(b.name)}.log"

    def _log_line(self, b: Buffer, ln) -> None:
        if self._log_key(b) not in self.cfg.log_tabs:
            return
        path = self.log_path(b)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%b %d %H:%M:%S', time.localtime(ln.ts))} {ln.left}\t{strip_format(ln.text)}\n")
        except OSError as e:
            b.session.add(b.session.server_buffer, "error", "*", f"Couldn't write the log: {e}")
            self.cfg.log_tabs.remove(self._log_key(b))

    def paste_lines(self, text: str) -> None:
        """Multi-line paste: each line goes as a message. They are never run as commands, so a paste can't /quit."""
        lines = [l for l in text.splitlines() if l.strip()]
        b = self.buf
        if b is None or not lines:
            return
        if b.kind == SERVER:
            b.session.add(b, "error", "*", "No channel joined. Try /join #channel")
            return
        if len(lines) > 5 and not getattr(self, "skip_quit_prompt", False):
            r = QMessageBox.question(self, "Paste", f"Send {len(lines)} lines to {b.name}?")
            if r != QMessageBox.StandardButton.Yes:
                return
        for line in lines:
            b.session.say(b.name, line)

    def _toggle_menu(self, on: bool) -> None:
        self.cfg.show_menu = on
        self.menubar_.setVisible(on)

    def _toggle_topic(self, on: bool) -> None:
        self.cfg.show_topic = on
        self.topic.setVisible(on)

    def _toggle_userlist(self, on: bool) -> None:
        self.cfg.show_userlist = on
        self._decide_userlist()

    def _toggle_away(self, on: bool) -> None:
        if self.session:
            self.session.set_away(on)

    def _join_dialog(self) -> None:
        s = self.session
        if s is None:
            self.open_network_list()
            return
        name, ok = QInputDialog.getText(self, "Join a Channel", "Channel:", text="#")
        if ok and len(name.strip()) > 1:
            s.send("JOIN", name.strip())

    def _clear_current(self) -> None:
        if self.buf is not None:
            self.buf.session.clear_buffer(self.buf)
            self.chat.reload(self.buf)

    def _search(self) -> None:
        text, ok = QInputDialog.getText(self, "Search Text", "Find:")
        if ok and text:
            if not self.chat.find(text, QTextDocument.FindFlag.FindBackward):
                self.chat.moveCursor(self.chat.textCursor().MoveOperation.End)
                self.chat.find(text, QTextDocument.FindFlag.FindBackward)

    def _save_text(self) -> None:
        if self.buf is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Text", f"{self.buf.name}.txt", "Text files (*.txt)")
        if path:
            lines = [f"{time.strftime('%H:%M', time.localtime(l.ts))} {l.left}\t{strip_format(l.text)}" for l in self.buf.lines]
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _raw(self, text: str, outgoing: bool) -> None:
        line = ("<< " if outgoing else ">> ") + text
        self.raw_lines.append(line)
        del self.raw_lines[:-2000]
        if self.raw_log is not None:
            self.raw_log.appendPlainText(line)

    def _open_raw_log(self) -> None:
        d = FramedDialog("BChat: Raw Log", self)
        d.resize(640, 400)
        view = QPlainTextEdit(d)
        view.setReadOnly(True)
        view.setFont(QFont(self.cfg.chat_font, self.cfg.chat_font_size))
        view.setPlainText("\n".join(self.raw_lines))
        d.body.addWidget(view)
        self.raw_log = view
        d.finished.connect(lambda _: setattr(self, "raw_log", None))
        d.show()

    def _about(self) -> None:
        QMessageBox.about(self, "About BChat",
                          f"<b>BChat {__version__}</b><br>Dark IRC client in the classic XChat 2 style.<br>"
                          "BajuBesi Labs. Icons from XChat 2 (GPL).")

    def _import_settings(self) -> None:
        sources = xchat_import.default_sources()
        if not sources:
            QMessageBox.information(self, "Import XChat Settings", "No XChat settings folder found.")
            return
        report = xchat_import.import_into(self.cfg, sources)
        config.save(self.cfg, self.cfg_dir)
        QMessageBox.information(self, "Import XChat Settings", "\n".join(report))

    def _rekey(self, s: Session, name: str) -> None:
        """Sessions are filed by network name; keep that in step when a tab gets a new name."""
        for key, value in list(self.sessions.items()):
            if value is s:
                del self.sessions[key]
        self.sessions[name] = s

    def rename_network(self, net: NetworkConfig, new: str) -> bool:
        """Network List: click the selected name to rename it, as in XChat. False when the name is empty or taken."""
        new = new.strip()
        old = net.name
        if not new or (lower(new) != lower(old) and any(lower(n.name) == lower(new) for n in self.cfg.networks)):
            return False
        if new == old:
            return True
        net.name = new
        prefix_old, prefix_new = f"{lower(old)}/", f"{lower(new)}/"
        self.cfg.log_tabs = [prefix_new + k[len(prefix_old):] if k.startswith(prefix_old) else k for k in self.cfg.log_tabs]
        for s in list(self.sessions.values()):
            if s.net is net:
                self._rekey(s, new)
                if s.server_buffer.name == old:
                    s.server_buffer.name = new
                    self._buffer_changed(s.server_buffer)
        config.save(self.cfg, self.cfg_dir)
        return True

    def edit_network(self, net: NetworkConfig) -> None:
        """Server tab menu > Edit Network: the Network List's Edit window for this network, saved on OK."""
        from .networklist import NetworkEditDialog
        if NetworkEditDialog(net, self).exec():
            config.save(self.cfg, self.cfg_dir)

    def add_network_from(self, s: Session) -> NetworkConfig:
        """AdiIRC's one-click save: this /server connection becomes a network in the Network List."""
        base = s.network_token or s.net.servers[0].host
        taken = {lower(n.name) for n in self.cfg.networks}
        name, i = base, 0
        while lower(name) in taken:
            i += 1
            name = f"{base}({i})"
        chans = [b.name for b in s.buffers.values() if b.kind == CHANNEL and b.joined]
        net = NetworkConfig(name, [Server(sv.host, sv.port, sv.ssl) for sv in s.net.servers],
                            password=s.net.password, autojoin=",".join(chans))
        if s.nick and lower(s.nick) != lower(self.cfg.nick):
            net.nick, net.use_global = s.nick, False
        self.cfg.networks.append(net)
        config.save(self.cfg, self.cfg_dir)
        s.net, s.typed_by_hand = net, False   # this tab now is that network (no second save, reconnect uses it)
        self._rekey(s, name)
        what = f"channels {' '.join(chans)}" if chans else "no channels"
        s.add(s.server_buffer, INFO, "*", f"Saved as network {name} in the Network List (server, nick, {what}).")
        if not getattr(self, "skip_dialogs", False):
            from .networklist import NetworkListDialog
            d = NetworkListDialog(self)
            for row in range(d.list.count()):
                if d.list.item(row).data(Qt.ItemDataRole.UserRole) is net:
                    d.list.setCurrentRow(row)
            d.exec()
        return net

    def open_preferences(self, page: str = "Text box") -> None:
        from .preferences import PreferencesDialog
        PreferencesDialog(self, page).exec()

    def apply_preferences(self) -> None:
        """After Preferences > OK: new colours everywhere, chat redrawn with the new font and text settings."""
        self.setStyleSheet(stylesheet(self.cfg.theme))
        self.chat.apply_font()
        self.chat.reload_all()
        self.userlist.viewport().update()
        for b in [b for s in self.sessions.values() for b in s.all_buffers()]:
            self._buffer_changed(b)
        config.save(self.cfg, self.cfg_dir)

    def open_network_list(self) -> None:
        from .networklist import NetworkListDialog
        NetworkListDialog(self).exec()

    def closeEvent(self, ev):
        live = [s for s in self.sessions.values() if s.state == "connected"]
        if live and not getattr(self, "skip_quit_prompt", False):
            r = QMessageBox.question(self, "Quit BChat", f"Disconnect from {len(live)} network(s) and quit?")
            if r != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
        for s in self.sessions.values():
            s.disconnect_from_network()
        self.cfg.win_maximized = self.isMaximized()
        if not self.isMaximized():
            self.cfg.win_width, self.cfg.win_height = self.width(), self.height()
            self.cfg.win_x, self.cfg.win_y = self.x(), self.y()
        left, _, right = self.split.sizes()
        if left > 0:
            self.cfg.pane_left = left
        if right > 0:
            self.cfg.pane_right = right
        config.save(self.cfg, self.cfg_dir)
        super().closeEvent(ev)
