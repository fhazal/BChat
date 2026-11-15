"""Popups: right-click menus the user edits (Settings > Advanced > Popups...), one list per menu.
Rows are XChat's Userlist Popup rows: Name + Command, SEP, SUB <title> ... ENDSUB. Commands fill in what /alias knows
($1 $2- $nick $chan $me $network and the % codes) and | runs more than one. Your items go under BChat's own, after a line."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .editors import button, rows_for
from .widgets import FramedDialog

MENUS = [("channel", "Channel"), ("query", "Private chat"), ("server", "Server tab"), ("nicklist", "Nick list"), ("menubar", "Menu bar")]
TITLES = dict(MENUS)
WHERE = {"channel": "Your items show under BChat's own in the channel right-click menu.",
         "query": "Your items show under BChat's own in the private chat right-click menu.",
         "server": "Your items show under BChat's own in the server tab right-click menu.",
         "nicklist": "Your items show at the bottom of the nick right-click menu.",
         "menubar": "Your items make a Commands menu in the menu bar. It only shows when it has items."}
HELP = ("$nick the nick (Nick list: each selected nick; Private chat: the other person)\n"
        "$1 the word you right-clicked (Nick list: the nick), $2- from the 2nd word on\n"
        "$chan the channel, $me your nick, $network the network\n"
        "%c channel, %n your nick, %e network\n"
        "Nick list only: %s each selected nick, %a all of them at once\n"
        "a | b runs two commands. !command runs a program on this PC.\n\n"
        "Submenu starts a menu inside the menu; drag rows into it. Separator draws a line.")
SUB, SEP, ITEM = "sub", "sep", "item"


def rows(cfg, key: str) -> list[list[str]]:
    if key == "nicklist":
        return [list(r) for r in rows_for(cfg, "ul_popup")]
    return [list(r) for r in cfg.popups.get(key, [])]


def count(rows_: list[list[str]]) -> int:
    return sum(1 for r in rows_ if r and r[0].upper() not in ("SEP", "SUB", "ENDSUB"))


# --- running an item ------------------------------------------------------------------------------------------

def run_item(win, b, cmd: str, nicks: list[str] | None = None, word: str = "") -> None:
    """One popup command in tab b. Nick list items with $nick or $1 run once per selected nick."""
    from . import commands
    from .session import CHANNEL, ERROR, QUERY
    if b is None:
        return
    cmd = cmd.replace("$$", "$")                     # mIRC's $$1: "only if there is one"; here empty means empty
    s = b.session
    if nicks is not None and not re.search(r"\$(nick\b|\d)", cmd):
        win.nick_command(cmd, nicks)                 # XChat's %s / %a
        return
    chan = b.name if b.kind == CHANNEL else ""
    targets = [(n, [n]) for n in nicks] if nicks is not None else [(b.name if b.kind == QUERY else "", word.split())]
    for query, args in targets:
        for piece in commands._split_bar(cmd):
            if nicks is not None:
                piece = piece.replace("%s", args[0])
            text = commands._expand(piece, s, chan, args, " ".join(args), query)
            if text is None:
                s.add(b, ERROR, "*", f"That menu item needs a value this tab doesn't have: {cmd}")
                return
            if text.startswith("!"):
                commands.start_program(s, b, text[1:])
            else:
                commands.run(win, s, b, "/" + text.lstrip("/"))


def fill_menu(menu: QMenu, rows_: list[list[str]], trigger) -> None:
    stack = [menu]
    for row in rows_:
        name, cmd = (list(row) + ["", ""])[:2]
        word = name.upper()
        if word == "SEP":
            stack[-1].addSeparator()
        elif word == "SUB":
            stack.append(stack[-1].addMenu(cmd))
        elif word == "ENDSUB":
            if len(stack) > 1:
                stack.pop()
        elif name:
            stack[-1].addAction(name, lambda c=cmd: trigger(c))


def add_items(win, menu: QMenu, key: str, b, word: str = "", nicks: list[str] | None = None, line: bool = True) -> None:
    """The user's rows, then the items scripts added, each block after a line."""
    mine = rows(win.cfg, key)
    if mine:
        if line and menu.actions():
            menu.addSeparator()
        fill_menu(menu, mine, lambda c: run_item(win, b, c, nicks, word))
    extra = [x for x in getattr(win.plugins, "menu_items", []) if x.menu == key]
    if extra:
        if menu.actions():
            menu.addSeparator()
        for x in extra:
            menu.addAction(x.name, lambda x=x: win.plugins.run_menu_item(x, b, word, nicks))


def sync_menubar(win) -> None:
    """The Commands menu: before Help, only while it has items. Items run in the tab that is in front when clicked."""
    old = getattr(win, "commands_menu", None)
    if old is not None:
        win.menubar_.removeAction(old.menuAction())
        old.setParent(None)
        old.deleteLater()
        win.commands_menu = None
    menu = QMenu("&Commands", win.menubar_)
    fill_menu(menu, rows(win.cfg, "menubar"), lambda c: run_item(win, win.buf, c))
    extra = [x for x in getattr(win.plugins, "menu_items", []) if x.menu == "menubar"]
    if extra and menu.actions():
        menu.addSeparator()
    for x in extra:
        menu.addAction(x.name, lambda x=x: win.plugins.run_menu_item(x, win.buf, "", None))
    if not menu.actions():
        menu.setParent(None)
        menu.deleteLater()
        return
    help_act = next((a for a in win.menubar_.actions() if a.menu() is not None and a.text().replace("&", "") == "Help"), None)
    win.menubar_.insertMenu(help_act, menu)
    win.commands_menu = menu


# --- mIRC popup text -------------------------------------------------------------------------------------------

_MIRC_MENU = {"channel": "channel", "query": "query", "status": "server", "nicklist": "nicklist", "menubar": "menubar"}
_IDENT = re.compile(r"\$\$?(\d+-?\d*|[A-Za-z_]\w*|\+|\?)")
_VAR = re.compile(r"%[A-Za-z_]\w+")


def _problem(name: str, cmd: str, known: set[str]) -> str:
    if "$" in name:
        return "its name changes with $ identifiers; names here are plain text"
    if "{" in cmd or "}" in cmd:
        return "it has a script block { }, which needs a script (Window > Scripts)"
    for m in _IDENT.finditer(cmd):
        w = m.group(1)
        if w == "+":
            return "it joins words with $+"
        if w == "?":
            return "it asks you for text with $?, which needs a script"
        if w[0].isdigit():
            if not re.fullmatch(r"\d-?", w):
                return f"it uses ${w}; BChat has $1 to $9 and $2- style ranges"
        elif w.lower() not in ("nick", "chan", "me", "network"):
            return f"it uses ${w}, which BChat doesn't have"
    m = _VAR.search(cmd)
    if m:
        return f"it uses the variable {m.group(0)}, which needs a script"
    for piece in re.split(r"\s\|\s", cmd):
        first = piece.strip().lstrip("/").split(" ", 1)[0].lower()
        if first and not first.startswith("!") and first not in known:
            return f"/{first} isn't a BChat command"
    return ""


def parse_mirc(text: str, known: set[str]) -> tuple[dict, list[tuple[str, str]]]:
    """mIRC popup text -> ({menu key or None: rows}, [(line, why it was left out)]). None = the menu being edited.
    'Name:command', a line without ':' starts a submenu, dots say how deep, '-' is a line."""
    out: dict = {}
    problems: list[tuple[str, str]] = []
    key = None
    depth = 0

    def close(to: int) -> None:
        nonlocal depth
        while depth > to:
            out.setdefault(key, []).append(["ENDSUB", ""])
            depth -= 1

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        m = re.fullmatch(r"menu\s+([\w,]+)\s*\{?", line, re.I)
        if m:
            close(0)
            first = m.group(1).split(",")[0].lower()
            key = _MIRC_MENU.get(first)
            if key is None:
                problems.append((line, f"BChat has no '{first}' menu; these items go to the menu you are editing"))
            continue
        if line in ("{", "}"):
            if line == "}":
                close(0)
                key = None
            continue
        dots = len(line) - len(line.lstrip("."))
        body = line[dots:].strip()
        if dots > depth:
            problems.append((line, "it belongs to a submenu that was left out"))
            continue
        close(dots)
        if body == "-":
            out.setdefault(key, []).append(["SEP", ""])
            continue
        name, colon, cmd = body.partition(":")
        name, cmd = name.strip(), cmd.strip()
        if not colon:
            if "$" in name:
                problems.append((line, "its name changes with $ identifiers; names here are plain text"))
                continue
            out.setdefault(key, []).append(["SUB", name])
            depth += 1
            continue
        why = _problem(name, cmd, known) if cmd else "it has no command"
        if why:
            problems.append((line, why))
            continue
        pieces = [p.strip().lstrip("/").replace("$$", "$") for p in re.split(r"\s\|\s", cmd)]
        out.setdefault(key, []).append([name, " | ".join(pieces)])
    close(0)
    # a submenu that ended up empty is no use
    for k, rs in out.items():
        changed = True
        while changed:
            changed = False
            for i in range(len(rs) - 1):
                if rs[i][0].upper() == "SUB" and rs[i + 1][0].upper() == "ENDSUB":
                    del rs[i:i + 2]
                    changed = True
                    break
    return {k: v for k, v in out.items() if v}, problems


def known_commands(win) -> set[str]:
    from .commands import command_names
    names = set(command_names(win.cfg))
    names |= {h.name for p in win.plugins.plugins for h in p.hooks if h.kind == "command"}
    return names


# --- the window ------------------------------------------------------------------------------------------------

class PopupsDialog(FramedDialog):
    def __init__(self, win, start: str = "channel"):
        super().__init__("BChat: Popups", win)
        self.win = win
        self.resize(760, 440)
        self.work = {k: rows(win.cfg, k) for k, _t in MENUS}
        self.key = start
        row = QHBoxLayout()
        self.menus = QListWidget()
        self.menus.setFixedWidth(150)
        for k, title in MENUS:
            it = QListWidgetItem(title, self.menus)
            it.setData(Qt.ItemDataRole.UserRole, k)
        row.addWidget(self.menus)
        right = QVBoxLayout()
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        right.addWidget(self.hint)
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Name", "Command"])
        self.view.setColumnWidth(0, 190)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.view.itemChanged.connect(lambda *_: self._counts())
        right.addWidget(self.view, 1)
        self.scripts_note = QLabel()
        self.scripts_note.setWordWrap(True)
        right.addWidget(self.scripts_note)
        btns = QHBoxLayout()
        self.up_btn = button("Up", lambda: self.move(-1))
        self.down_btn = button("Down", lambda: self.move(1))
        self.new_btn = button("New", self.new_row)
        self.sub_btn = button("Submenu", self.new_sub)
        self.sep_btn = button("Separator", self.new_sep)
        self.delete_btn = button("Delete", self.delete_row)
        for w in (self.up_btn, self.down_btn, self.new_btn, self.sub_btn, self.sep_btn, self.delete_btn):
            btns.addWidget(w)
        btns.addStretch(1)
        right.addLayout(btns)
        row.addLayout(right, 1)
        self.body.addLayout(row, 1)
        bottom = QHBoxLayout()
        self.paste_btn = button("Paste mIRC popups...", self.open_paste, "edit")
        self.help_btn = button("Help", self.show_help)
        self.cancel_btn = button("Cancel", self.reject, "close-light")
        self.save_btn = button("Save", self.accept, "save")
        bottom.addWidget(self.paste_btn)
        bottom.addWidget(self.help_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.save_btn)
        self.body.addLayout(bottom)
        self.paste_dialog = None
        self._load(self.work[self.key])
        self.menus.setCurrentRow([k for k, _t in MENUS].index(start))
        self.menus.currentItemChanged.connect(self._switch)
        self._show_key()

    # the field the current list is saved in (tests and the old editor look at this)
    @property
    def field(self) -> str:
        return "ul_popup" if self.key == "nicklist" else "popups"

    def _switch(self, it, _old=None) -> None:
        if it is None:
            return
        self.work[self.key] = self.rows()
        self.key = it.data(Qt.ItemDataRole.UserRole)
        self._load(self.work[self.key])
        self._show_key()

    def _show_key(self) -> None:
        self.hint.setText(WHERE[self.key])
        extra = [x for x in getattr(self.win.plugins, "menu_items", []) if x.menu == self.key]
        self.scripts_note.setText(("Scripts add: " + ", ".join(f"{x.name} ({x.plugin.path.name})" for x in extra)) if extra else "")
        self.scripts_note.setVisible(bool(extra))
        self._counts()

    def _counts(self) -> None:
        if self.view.signalsBlocked():
            return
        current = self.rows()
        for i in range(self.menus.count()):
            it = self.menus.item(i)
            k = it.data(Qt.ItemDataRole.UserRole)
            n = count(current if k == self.key else self.work[k])
            it.setText(f"{TITLES[k]}  ({n})" if n else TITLES[k])

    # --- tree <-> rows

    def _item(self, kind: str, name: str, cmd: str = "") -> QTreeWidgetItem:
        it = QTreeWidgetItem([name, cmd if kind == ITEM else ""])
        it.setData(0, Qt.ItemDataRole.UserRole, kind)
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDragEnabled
        if kind != SEP:
            flags |= Qt.ItemFlag.ItemIsEditable
        if kind == SUB:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
            f = QFont(it.font(0))
            f.setBold(True)
            it.setFont(0, f)
        it.setFlags(flags)
        if kind == SEP:
            it.setForeground(0, self.palette().placeholderText())
        return it

    def _load(self, rows_: list[list[str]]) -> None:
        self.view.blockSignals(True)
        self.view.clear()
        stack = [self.view.invisibleRootItem()]
        for row in rows_:
            name, cmd = (list(row) + ["", ""])[:2]
            word = name.upper()
            if word == "SUB":
                it = self._item(SUB, cmd)
                stack[-1].addChild(it)
                stack.append(it)
                it.setExpanded(True)
            elif word == "ENDSUB":
                if len(stack) > 1:
                    stack.pop()
            elif word == "SEP":
                stack[-1].addChild(self._item(SEP, "SEP"))
            else:
                stack[-1].addChild(self._item(ITEM, name, cmd))
        self.view.expandAll()
        self.view.blockSignals(False)

    def _flatten(self, parent) -> list[list[str]]:
        out = []
        for i in range(parent.childCount()):
            it = parent.child(i)
            kind = it.data(0, Qt.ItemDataRole.UserRole)
            if kind == SUB:
                out.append(["SUB", it.text(0).strip() or "Submenu"])
                out += self._flatten(it)
                out.append(["ENDSUB", ""])
            elif kind == SEP:
                out.append(["SEP", ""])
            elif it.text(0).strip():
                out.append([it.text(0).strip(), it.text(1).strip()])
        return out

    def rows(self) -> list[list[str]]:
        return self._flatten(self.view.invisibleRootItem())

    def _add_row(self, name: str, cmd: str = "") -> QTreeWidgetItem:
        """Kept from the list editor: one row at the end, as typed (SEP and SUB rows too)."""
        it = self._item(SEP if name.upper() == "SEP" else ITEM, name, cmd)
        self.view.addTopLevelItem(it)
        self._counts()
        return it

    # --- buttons

    def _where(self):
        """New rows go at the end of the list the selected row is in, or inside the selected submenu."""
        cur = self.view.currentItem()
        if cur is None:
            return self.view.invisibleRootItem()
        if cur.data(0, Qt.ItemDataRole.UserRole) == SUB:
            return cur
        return cur.parent() or self.view.invisibleRootItem()

    def _insert(self, it: QTreeWidgetItem, edit: bool = True) -> None:
        parent = self._where()
        parent.addChild(it)
        parent.setExpanded(True)
        self.view.setCurrentItem(it)
        self._counts()
        if edit:
            self.view.editItem(it, 0)

    def new_row(self) -> None:
        self._insert(self._item(ITEM, "New item", "say "))

    def new_sub(self) -> None:
        self._insert(self._item(SUB, "New submenu"))

    def new_sep(self) -> None:
        self._insert(self._item(SEP, "SEP"), edit=False)

    def delete_row(self) -> None:
        it = self.view.currentItem()
        if it is not None:
            (it.parent() or self.view.invisibleRootItem()).removeChild(it)
            self._counts()

    def move(self, delta: int) -> None:
        it = self.view.currentItem()
        if it is None:
            return
        parent = it.parent() or self.view.invisibleRootItem()
        at = parent.indexOfChild(it)
        to = at + delta
        if 0 <= to < parent.childCount():
            expanded = it.isExpanded()
            parent.takeChild(at)
            parent.insertChild(to, it)
            it.setExpanded(expanded)
            self.view.setCurrentItem(it)

    def show_help(self) -> None:
        QMessageBox.information(self, "Help", HELP)

    def open_paste(self) -> "PasteMircDialog":
        if self.paste_dialog is None:
            self.paste_dialog = PasteMircDialog(self)
        self.paste_dialog.show()
        self.paste_dialog.raise_()
        return self.paste_dialog

    def add_pasted(self, found: dict) -> dict[str, int]:
        """Rows from Paste mIRC popups, added at the end of their menus. Returns how many items each menu got."""
        self.work[self.key] = self.rows()
        added = {}
        for k, rs in found.items():
            k = k or self.key
            self.work[k] = self.work[k] + rs
            added[k] = added.get(k, 0) + count(rs)
        self._load(self.work[self.key])
        self._counts()
        return added

    def accept(self) -> None:
        self.work[self.key] = self.rows()
        cfg = self.win.cfg
        cfg.ul_popup = self.work["nicklist"]
        cfg.popups = {k: v for k, v in self.work.items() if k != "nicklist" and v}
        self.win.lists_changed()
        super().accept()


class PasteMircDialog(FramedDialog):
    def __init__(self, popups: PopupsDialog):
        super().__init__("BChat: Paste mIRC popups", popups)
        self.popups = popups
        self.resize(620, 460)
        intro = QLabel("Paste mIRC popup text: Name:command lines, dots for submenus, - for a line. "
                       "A 'menu nicklist {' block goes to the Nick list. Lines BChat can't run are listed below, not added.")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Hello:say Hello $chan!\nGreet\n.Hi:say hi $1\n-\nWhois:whois $$1")
        self.body.addWidget(self.text, 2)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.body.addWidget(self.report, 1)
        row = QHBoxLayout()
        self.add_btn = button("Add", self.add, "add")
        self.close_btn = button("Close", self.reject, "close-light")
        row.addStretch(1)
        row.addWidget(self.close_btn)
        row.addWidget(self.add_btn)
        self.body.addLayout(row)

    def add(self) -> tuple[dict, list]:
        found, problems = parse_mirc(self.text.toPlainText(), known_commands(self.popups.win))
        added = self.popups.add_pasted(found) if found else {}
        lines = []
        if added:
            lines.append("Added: " + ", ".join(f"{n} to {TITLES[k]}" for k, n in added.items()) + ". Save in the Popups window keeps them.")
        elif not problems:
            lines.append("Nothing to add: no Name:command lines found.")
        if problems:
            lines.append(f"Not added ({len(problems)}), fix these by hand:")
            lines += [f"  {line}\n      {why}" for line, why in problems]
        self.report.setPlainText("\n".join(lines))
        if found:
            self.text.clear()
        return found, problems
