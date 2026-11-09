"""A tab in its own window: XChat's Detach (Ctrl+I). Chat, topic, list and input of its own; the buffer stays the same one."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout, QWidget

from . import commands
from .chatview import ChatView
from .protocol import strip_format
from .session import CHANNEL, SERVER, Buffer
from .userlist import UserList
from .widgets import FramedDialog


class DetachedWindow(FramedDialog):
    def __init__(self, win, b: Buffer):
        from .mainwindow import InputBox
        super().__init__(f"BChat: {b.name}", win)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.win, self.b = win, b
        self.resize(760, 480)
        s = b.session
        row = QHBoxLayout()
        self.topic = QLabel()
        self.topic.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.topic, 1)
        self.attach_btn = QPushButton("Attach")
        self.attach_btn.setAutoDefault(False)
        self.attach_btn.clicked.connect(lambda _=False: win.attach(b))
        row.addWidget(self.attach_btn)
        self.body.addLayout(row)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.chat = ChatView(win.cfg, split)
        self.chat.menu_provider = self._chat_menu
        self.chat.colour_rule = win.chat_colour_rule
        self.chat.reply_jump = win.reply_jump
        self.chat.channel_double_clicked.connect(win._join_clicked)
        self.chat.show_buffer(b)
        split.addWidget(self.chat)
        side = QWidget(split)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 0)
        self.count = QLabel()
        lay.addWidget(self.count)
        self.userlist = UserList(win.cfg.theme, side, win.cfg)
        self.userlist.customContextMenuRequested.connect(self._nick_menu)
        lay.addWidget(self.userlist, 1)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([600, 150])
        side.setVisible(b.kind == CHANNEL)
        self.body.addWidget(split, 1)
        self.input = InputBox(win)
        self.input.fixed = b
        self.input.returnPressed.connect(self._entered)
        self.body.addWidget(self.input)
        s.line_added.connect(self.chat.add_line)
        s.users_changed.connect(self._users)
        s.buffer_changed.connect(self._changed)
        self._changed(b)
        self._users(b)

    def _chat_menu(self, pos):
        return self.win._chat_menu(pos, self.chat, self.b)

    def _nick_menu(self, pos) -> None:
        users = self.userlist.selected_users()
        if users:
            self.win.build_nick_menu(self.b, users).exec(self.userlist.viewport().mapToGlobal(pos))

    def _changed(self, b: Buffer) -> None:
        if b is self.b:
            self.titlebar.set_title(f"BChat: {b.name}")
            self.topic.setText(strip_format(b.topic))

    def _users(self, b: Buffer) -> None:
        if b is self.b and b.kind == CHANNEL:
            self.userlist.set_buffer(b)
            ops, total = b.counts()
            self.count.setText(f"{ops} ops, {total} total")

    def _entered(self) -> None:
        text = self.input.text()
        self.input.clear()
        if text:
            self.input.remember(text)
            commands.run(self.win, self.b.session, self.b, self.win.expand_input(text, self.b))

    def unhook(self) -> None:
        s = self.b.session
        for sig, slot in ((s.line_added, self.chat.add_line), (s.users_changed, self._users), (s.buffer_changed, self._changed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def reject(self) -> None:
        """The red button closes the tab, as XChat's does. A server tab goes back in the tree instead: it holds the connection."""
        if self.b.kind == SERVER:
            self.win.attach(self.b)
        else:
            self.win.close_buffer(self.b)
