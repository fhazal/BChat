"""Settings > Advanced: XChat's list editors (src/fe-gtk/editlist.c), Text Events (textgui.c) and Keyboard Shortcuts (fkeys.c)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem)

from .commands import ALIASES
from .protocol import strip_format
from .textevents import EVENTS, render
from .widgets import FramedDialog, icon

DIALOG_BUTTONS = [["Whois", "whois %s"], ["Send", "dcc send %s"], ["Chat", "dcc chat %s"], ["Clear", "clear"], ["Ping", "ping %s"]]
USERLIST_BUTTONS = [["Op", "op %a"], ["DeOp", "deop %a"], ["Ban", "ban %s"], ["Kick", "kick %s"], ["Sendfile", "dcc send %s"], ["Dialog", "query %s"]]
CTCP_REPLIES = [["TIME", "nctcp %s TIME %t"], ["PING", "nctcp %s PING %d"]]
AUTO_REPLACE = [["teh", "the"]]


def default_commands() -> list[list[str]]:
    return [[name.upper(), cmd] for name, cmd in sorted(ALIASES.items())]


def rows_for(cfg, field: str) -> list[list[str]]:
    """Every list keeps None until the user saves it, so new defaults still reach them."""
    value = getattr(cfg, field)
    if value is not None:
        return value
    return {"user_commands": default_commands, "dlg_buttons": lambda: DIALOG_BUTTONS, "ul_buttons": lambda: USERLIST_BUTTONS,
            "ctcp_replies": lambda: CTCP_REPLIES, "auto_replace": lambda: AUTO_REPLACE,
            "slaps": _default_slaps}.get(field, list)()


def _default_slaps() -> list[list[str]]:
    from .slaps import DEFAULT_SLAPS
    return [[line] for line in DEFAULT_SLAPS]


NICK_HELP = ("%a all selected nicks\n%s the selected nick\n%c current channel\n%n your nick\n%e network\n"
             "!command runs a program on this PC.")
EDITORS = {
    "replace": ("Auto Replace", "auto_replace", ("Text", "Replace with"),
                "When the word you just typed matches Text, it is changed to Replace with, as you press space or Enter."),
    "ctcp": ("CTCP Replies", "ctcp_replies", ("CTCP", "Command"),
             "%d data (the whole CTCP)\n%e network\n%m machine info\n%n your nick\n%s nick who sent the ctcp\n%t current time\n%v BChat version\n\n"
             "A reply can't run a program: other people can trigger these."),
    "commands": ("User Commands", "user_commands", ("Name", "Command"),
                 "%2 to %9 word 2 to 9\n&2 to &9 everything from that word on\n%c channel\n%e network\n%m machine info\n%n your nick\n%s server\n%t time\n%u username\n%v version\n"
                 "!command runs a program on this PC.\n\nSame name twice: both run, in order."),
    "url": ("URL Handlers", "url_handlers", ("Name", "Command"),
            "Added to the right-click menu of a link.\n%s the URL\n!command runs a program on this PC."),
    "dialog": ("Dialog Buttons", "dlg_buttons", ("Name", "Command"),
               "Buttons at the top of a private tab.\n%s the other person's nick\n" + NICK_HELP),
    "ulbuttons": ("Userlist Buttons", "ul_buttons", ("Name", "Command"),
                  "Buttons under the user list.\n" + NICK_HELP),
    "popup": ("Userlist Popup", "ul_popup", ("Name", "Command"),
              "Extra items at the bottom of the nick right-click menu.\n" + NICK_HELP +
              "\n\nName SEP makes a separator. Name SUB with the title as its command starts a submenu, ENDSUB ends it."),
    "slaps": ("Slaps", "slaps", ("Slap",),
              "Right-click a nick > Slap! sends one of these at random, as an action (/me) in the channel.\n"
              "$nick the person you slap\n%B bold, %U underline, %O reset\n%C colour: %C4 red, %C7 orange, %C8 yellow, "
              "%C9 green, %C11 cyan, %C6 purple, %C13 pink; %C alone ends the colour"),
}


def button(text: str, slot, ico: str = "") -> QPushButton:
    b = QPushButton(text)
    if ico:
        b.setIcon(icon(ico))
    b.setAutoDefault(False)
    b.clicked.connect(lambda _=False: slot())
    return b


class EditListDialog(FramedDialog):
    def __init__(self, win, key: str):
        title, self.field, columns, self.help_text = EDITORS[key]
        super().__init__(f"BChat: {title}", win)
        self.win = win
        self.resize(560, 420)
        self.view = QTreeWidget()
        self.view.setHeaderLabels(list(columns))
        self.view.setRootIsDecorated(False)
        self.cols = len(columns)
        if self.cols > 1:
            self.view.setColumnWidth(0, 170)
        self.body.addWidget(self.view, 1)
        for row_ in rows_for(win.cfg, self.field):
            self._add_row(*row_[:self.cols])
        row = QHBoxLayout()
        self.up_btn = button("Up", lambda: self.move(-1))
        self.down_btn = button("Down", lambda: self.move(1))
        self.new_btn = button("New", self.new_row)
        self.delete_btn = button("Delete", self.delete_row)
        self.help_btn = button("Help", self.show_help)
        self.cancel_btn = button("Cancel", self.reject, "close-light")
        self.save_btn = button("Save", self.accept, "save")
        for w in (self.up_btn, self.down_btn, self.new_btn, self.delete_btn, self.help_btn):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.save_btn)
        self.body.addLayout(row)

    def _add_row(self, name: str, cmd: str = "") -> QTreeWidgetItem:
        it = QTreeWidgetItem([name, cmd][:self.cols])
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        self.view.addTopLevelItem(it)
        return it

    def new_row(self) -> None:
        it = self._add_row("EDIT ME") if self.cols == 1 else self._add_row("NEW", "EDIT ME")
        self.view.setCurrentItem(it)
        self.view.editItem(it, 0)

    def delete_row(self) -> None:
        it = self.view.currentItem()
        if it is not None:
            self.view.takeTopLevelItem(self.view.indexOfTopLevelItem(it))

    def move(self, delta: int) -> None:
        it = self.view.currentItem()
        if it is None:
            return
        at = self.view.indexOfTopLevelItem(it)
        to = at + delta
        if 0 <= to < self.view.topLevelItemCount():
            self.view.takeTopLevelItem(at)
            self.view.insertTopLevelItem(to, it)
            self.view.setCurrentItem(it)

    def show_help(self) -> None:
        QMessageBox.information(self, "Help", self.help_text)

    def rows(self) -> list[list[str]]:
        out = []
        for i in range(self.view.topLevelItemCount()):
            it = self.view.topLevelItem(i)
            if it.text(0).strip():
                out.append([it.text(c).strip() for c in range(self.cols)])
        return out

    def accept(self) -> None:
        setattr(self.win.cfg, self.field, self.rows())
        self.win.lists_changed()
        super().accept()


class TextEventsDialog(FramedDialog):
    def __init__(self, win):
        super().__init__("BChat: Text Events", win)
        self.win = win
        self.resize(720, 520)
        self.edited = dict(win.cfg.text_events)
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Event", "Text"])
        self.view.setRootIsDecorated(False)
        self.view.setColumnWidth(0, 170)
        for name in EVENTS:
            self.view.addTopLevelItem(QTreeWidgetItem([name, self._format(name)]))
        self.view.currentItemChanged.connect(self._selected)
        self.body.addWidget(self.view, 1)
        self.edit = QLineEdit()
        self.edit.textEdited.connect(self._typed)
        self.body.addWidget(self.edit)
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.preview)
        self.args = QLabel()
        self.args.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.args)
        self.body.addWidget(QLabel("$t separates the left column from the text. %B bold, %U underline, %C colour, %O reset."))
        row = QHBoxLayout()
        self.reset_btn = button("Reset This", self.reset_one)
        self.reset_all_btn = button("Reset All", self.reset_all)
        self.test_btn = button("Test All", self.test_all)
        self.cancel_btn = button("Cancel", self.reject, "close-light")
        self.save_btn = button("Save", self.accept, "save")
        for w in (self.reset_btn, self.reset_all_btn, self.test_btn):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.save_btn)
        self.body.addLayout(row)
        self.view.setCurrentItem(self.view.topLevelItem(0))

    def _format(self, name: str) -> str:
        return self.edited.get(name, EVENTS[name][0])

    def _selected(self, it, _old=None) -> None:
        if it is None:
            return
        name = it.text(0)
        self.edit.setText(self._format(name))
        self.args.setText("   ".join(f"${i} {a}" for i, a in enumerate(EVENTS[name][1], 1)))
        self._show_preview(name)

    def _show_preview(self, name: str) -> None:
        left, text = render(self._format(name), EVENTS[name][2])
        self.preview.setText(f"{strip_format(left)}  {strip_format(text)}")

    def _typed(self, text: str) -> None:
        it = self.view.currentItem()
        name = it.text(0)
        self.edited[name] = text
        it.setText(1, text)
        self._show_preview(name)

    def reset_one(self) -> None:
        it = self.view.currentItem()
        self.edited.pop(it.text(0), None)
        it.setText(1, self._format(it.text(0)))
        self._selected(it)

    def reset_all(self) -> None:
        self.edited.clear()
        for i in range(self.view.topLevelItemCount()):
            it = self.view.topLevelItem(i)
            it.setText(1, self._format(it.text(0)))
        self._selected(self.view.currentItem())

    def test_all(self) -> None:
        b = self.win.buf
        if b is None:
            return
        for name in EVENTS:
            left, text = render(self._format(name), EVENTS[name][2])
            b.session.add(b, "info", left, text)

    def accept(self) -> None:
        self.win.cfg.text_events = {k: v for k, v in self.edited.items() if v != EVENTS[k][0]}
        self.win.lists_changed()
        super().accept()


class KeysDialog(FramedDialog):
    """Every menu command, with its key. Plus XChat's "Run Command" keys, as a second list."""

    def __init__(self, win):
        super().__init__("BChat: Keyboard Shortcuts", win)
        self.win = win
        self.resize(620, 560)
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Command", "Key"])
        self.view.setRootIsDecorated(False)
        self.view.setColumnWidth(0, 300)
        self.actions_by_name = win.named_actions()
        for name, act in self.actions_by_name.items():
            self.view.addTopLevelItem(QTreeWidgetItem([name, act.shortcut().toString()]))
        self.view.currentItemChanged.connect(self._selected)
        self.body.addWidget(self.view, 2)
        row = QHBoxLayout()
        row.addWidget(QLabel("Key:"))
        self.key = QKeySequenceEdit()
        self.key.setMaximumSequenceLength(1)
        self.key.keySequenceChanged.connect(self._key_set)
        row.addWidget(self.key, 1)
        self.clear_btn = button("No Key", lambda: self.key.setKeySequence(QKeySequence()))
        row.addWidget(self.clear_btn)
        self.body.addLayout(row)
        self.warning = QLabel()
        self.body.addWidget(self.warning)
        self.body.addWidget(QLabel("Keys that run a command:"))
        self.custom = QTreeWidget()
        self.custom.setHeaderLabels(["Key", "Command"])
        self.custom.setRootIsDecorated(False)
        for k, cmd in win.cfg.key_commands:
            self._custom_row(k, cmd)
        self.body.addWidget(self.custom, 1)
        row = QHBoxLayout()
        self.new_btn = button("New", lambda: self._custom_row("Ctrl+Shift+1", "/echo hello"))
        self.delete_btn = button("Delete", self._custom_delete)
        self.cancel_btn = button("Cancel", self.reject, "close-light")
        self.save_btn = button("Save", self.accept, "save")
        row.addWidget(self.new_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.save_btn)
        self.body.addLayout(row)

    def _custom_row(self, key: str, cmd: str) -> None:
        it = QTreeWidgetItem([key, cmd])
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        self.custom.addTopLevelItem(it)

    def _custom_delete(self) -> None:
        it = self.custom.currentItem()
        if it is not None:
            self.custom.takeTopLevelItem(self.custom.indexOfTopLevelItem(it))

    def _selected(self, it, _old=None) -> None:
        if it is not None:
            self.key.blockSignals(True)
            self.key.setKeySequence(QKeySequence(it.text(1)))
            self.key.blockSignals(False)
            self.warning.setText("")

    def _key_set(self, seq: QKeySequence) -> None:
        it = self.view.currentItem()
        if it is None:
            return
        text = seq.toString()
        it.setText(1, text)
        others = [self.view.topLevelItem(i).text(0) for i in range(self.view.topLevelItemCount())
                  if self.view.topLevelItem(i) is not it and text and self.view.topLevelItem(i).text(1) == text]
        self.warning.setText(f"{text} is also used by {others[0]}. Pick another." if others else "")

    def conflicts(self) -> bool:
        seen = set()
        for i in range(self.view.topLevelItemCount()):
            k = self.view.topLevelItem(i).text(1)
            if k and k in seen:
                return True
            seen.add(k)
        return False

    def accept(self) -> None:
        if self.conflicts():
            self.warning.setText("Two commands share a key. Change one of them first.")
            return
        keys = {}
        for i in range(self.view.topLevelItemCount()):
            it = self.view.topLevelItem(i)
            name, key = it.text(0), it.text(1)
            if key != self.win.default_keys.get(name, ""):
                keys[name] = key
        self.win.cfg.keys = keys
        rows = []
        for i in range(self.custom.topLevelItemCount()):
            it = self.custom.topLevelItem(i)
            if it.text(0).strip() and it.text(1).strip():
                rows.append([it.text(0).strip(), it.text(1).strip()])
        self.win.cfg.key_commands = rows
        self.win.lists_changed()
        super().accept()
