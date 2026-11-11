"""Channel Central (0.3.0, mIRC's): one window for a channel's topic, modes and its ban / exception / invite lists.

Only the modes this server has are shown (CHANMODES), with words for the common ones. Apply sends the topic (if
changed) and ONE mode line per MODES-many changes. Without @ everything shows but can't be changed."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QPlainTextEdit, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .session import Buffer, Session
from .tools import ToolWindow, button
from .widgets import icon

FLAG_WORDS = {
    "t": "Only ops change the topic", "n": "No messages from outside", "i": "Invite only",
    "m": "Moderated: only @ and + talk", "s": "Secret", "p": "Private", "c": "No colours", "C": "No CTCPs",
    "R": "Registered users only", "M": "Only registered users talk", "N": "No nick changes", "T": "No notices",
    "S": "Strip colours", "z": "Secure (TLS) users only", "Q": "No kicks", "K": "No /knock", "V": "No invites",
    "G": "Filter bad words", "O": "IRC operators only",
}
FIRST = "tnimsp"
LISTS = (("b", "Bans"), ("e", "Exceptions"), ("I", "Invites"))


def is_op(s: Session, b: Buffer) -> bool:
    me = b.users.get(b.session.fold(s.nick))
    if me is None:
        return False
    order = s.prefix_order
    at = order.find("@")
    return any(p in order and (at < 0 or order.index(p) <= at) for p in me.prefixes)


def mode_lines(old_modes: str, old_args: dict, want_flags: dict, key: str | None, limit: int | None,
               max_modes: int) -> list[tuple[str, list[str]]]:
    """[(modestring, args)] taking `old` to `want`. key/limit: None = leave as is, '' / 0 = remove."""
    changes: list[tuple[str, str, str]] = []
    for c, on in want_flags.items():
        if on and c not in old_modes:
            changes.append(("+", c, ""))
        elif not on and c in old_modes:
            changes.append(("-", c, ""))
    if key is not None:
        had = old_args.get("k", "") if "k" in old_modes else ""
        if key and key != had:
            if had:
                changes.append(("-", "k", had))
            changes.append(("+", "k", key))
        elif not key and "k" in old_modes:
            changes.append(("-", "k", had or "*"))
    if limit is not None:
        had = old_args.get("l", "") if "l" in old_modes else ""
        if limit and str(limit) != had:
            changes.append(("+", "l", str(limit)))
        elif not limit and "l" in old_modes:
            changes.append(("-", "l", ""))
    out = []
    step = max(1, max_modes)
    for i in range(0, len(changes), step):
        chunk = changes[i:i + step]
        text, sign, args = "", "", []
        for sg, c, a in chunk:
            if sg != sign:
                text += sg
                sign = sg
            text += c
            if a:
                args.append(a)
        out.append((text, args))
    return out


class ChannelCentral(ToolWindow):
    def __init__(self, win, s: Session, b: Buffer):
        super().__init__(f"BChat: Channel Central ({b.name})", win, (640, 600))
        self.s, self.b = s, b
        self.waiting: set[str] = set()
        self.body.addWidget(QLabel("<b>Topic</b>"))
        self.topic = QPlainTextEdit()
        self.topic.setFixedHeight(52)
        self.body.addWidget(self.topic)
        self.topic_by = QLabel()
        self.topic_by.setStyleSheet(f"color: {win.cfg.theme.muted};")
        self.body.addWidget(self.topic_by)
        self.body.addWidget(QLabel("<b>Modes</b>"))
        self.grid = QGridLayout()
        self.body.addLayout(self.grid)
        self.flags: dict[str, QCheckBox] = {}
        self.key_box = QCheckBox("Key (+k):")
        self.key = QLineEdit()
        self.key.setFixedWidth(150)
        self.limit_box = QCheckBox("Limit (+l):")
        self.limit = QSpinBox()
        self.limit.setRange(1, 99999)
        self.limit.setValue(50)
        extra = QHBoxLayout()
        self.users_label = QLabel("users")
        for w in (self.key_box, self.key):
            extra.addWidget(w)
        extra.addSpacing(24)
        for w in (self.limit_box, self.limit, self.users_label):
            extra.addWidget(w)
        extra.addStretch(1)
        self.body.addLayout(extra)
        self.not_op = QLabel("You need @ to change these.")
        self.not_op.setStyleSheet(f"color: {win.cfg.theme.muted};")
        self.body.addWidget(self.not_op)
        self.tabs = QTabWidget()
        self.views: dict[str, QTreeWidget] = {}
        self.list_buttons: list = []
        for letter, label in LISTS:
            if letter not in s.modes_list:
                continue
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(4, 4, 4, 4)
            v = QTreeWidget()
            v.setHeaderLabels(["Mask", "From", "Date"])
            v.setRootIsDecorated(False)
            v.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            v.setColumnWidth(0, 250)
            wl.addWidget(v)
            br = QHBoxLayout()
            add = button("Add...", lambda l=letter: self.add_mask(l))
            add.setIcon(icon("add"))
            rm = button("Remove", lambda l=letter: self.remove_selected(l))
            rm.setIcon(icon("remove"))
            br.addWidget(add)
            br.addWidget(rm)
            br.addStretch(1)
            ref = button("Refresh", self.refresh_lists)
            ref.setIcon(icon("refresh"))
            br.addWidget(ref)
            wl.addLayout(br)
            self.list_buttons += [add, rm]
            self.tabs.addTab(w, label)
            self.views[letter] = v
        self.body.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = button("&Close", self.close)
        close.setIcon(icon("close-light"))
        self.apply_btn = button("&Apply", self.apply)
        self.apply_btn.setIcon(icon("save"))
        self.apply_btn.setDefault(True)
        row.addWidget(close)
        row.addWidget(self.apply_btn)
        self.body.addLayout(row)
        s.buffer_changed.connect(self._changed)
        self.fill()

    # --- what the channel is now ------------------------------------------------------

    def _changed(self, b) -> None:
        if b is self.b and self.isVisible():
            self.fill()

    def fill(self) -> None:
        s, b = self.s, self.b
        self.topic.setPlainText(b.topic)
        if b.topic_by:
            when = time.strftime("%a %d %b %H:%M", time.localtime(b.topic_at)) if b.topic_at else ""
            self.topic_by.setText(f"Set by {b.topic_by}" + (f", {when}" if when else ""))
        else:
            self.topic_by.setText("")
        self.topic_by.setVisible(bool(b.topic_by))
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self.flags = {}
        have = [c for c in FIRST if c in s.modes_flags] + [c for c in s.modes_flags if c not in FIRST and c in FLAG_WORDS]
        for i, c in enumerate(have):
            box = QCheckBox(f"{FLAG_WORDS[c]} (+{c})")
            box.setChecked(c in b.modes)
            self.flags[c] = box
            self.grid.addWidget(box, i // 2, i % 2)
        has_key, has_limit = "k" in s.modes_key, "l" in s.modes_on_set
        for w in (self.key_box, self.key):
            w.setVisible(has_key)
        for w in (self.limit_box, self.limit, self.users_label):
            w.setVisible(has_limit)
        self.key_box.setChecked("k" in b.modes)
        self.key.setText(b.mode_args.get("k", "") if "k" in b.modes else "")
        self.limit_box.setChecked("l" in b.modes)
        val = b.mode_args.get("l", "")
        if val.isdigit():
            self.limit.setValue(int(val))
        self._enable()

    def _enable(self) -> None:
        op = is_op(self.s, self.b) and self.s.state == "connected"
        topic_ok = op or ("t" not in self.b.modes and self.s.state == "connected")
        for w in [*self.flags.values(), self.key_box, self.key, self.limit_box, self.limit, *self.list_buttons]:
            w.setEnabled(op)
        self.topic.setReadOnly(not topic_ok)
        self.apply_btn.setEnabled(op or topic_ok)
        self.not_op.setVisible(not op)

    # --- Apply --------------------------------------------------------------------------

    def planned(self) -> tuple[str | None, list[tuple[str, list[str]]]]:
        """(new topic or None, mode lines) that Apply would send."""
        b = self.b
        text = self.topic.toPlainText().replace("\n", " ").strip()
        topic = text if text != b.topic.strip() and not self.topic.isReadOnly() else None
        if not is_op(self.s, b):
            return topic, []
        want = {c: box.isChecked() for c, box in self.flags.items()}
        key = None
        if "k" in self.s.modes_key:
            key = self.key.text().strip() if self.key_box.isChecked() else ""
            if self.key_box.isChecked() and not key:
                key = None                       # ticked with nothing typed: nothing to send
        limit = None
        if "l" in self.s.modes_on_set:
            limit = self.limit.value() if self.limit_box.isChecked() else 0
        return topic, mode_lines(b.modes, b.mode_args, want, key, limit, self.s.max_modes)

    def apply(self) -> None:
        topic, lines = self.planned()
        if topic is not None:
            self.s.send("TOPIC", self.b.name, topic)
        for modes, args in lines:
            self.s.send("MODE", self.b.name, modes, *args)

    # --- the lists ------------------------------------------------------------------------

    def refresh_lists(self) -> None:
        for v in self.views.values():
            v.clear()
        if self.s.state != "connected":
            return
        self.s.ban_sinks[self.s.fold(self.b.name)] = self
        for letter in self.views:
            self.waiting.add(letter)
            self.s.send("MODE", self.b.name, "+" + letter)

    def ban_item(self, letter: str, mask: str, who: str, when: str) -> None:
        v = self.views.get(letter)
        if v is None:
            return
        date = time.strftime("%a %b %d %H:%M", time.localtime(int(when))) if when.isdigit() else ""
        v.addTopLevelItem(QTreeWidgetItem([mask, who.split("!")[0], date]))
        self._titles()

    def ban_end(self, letter: str) -> None:
        self.waiting.discard(letter)
        self._titles()

    def _titles(self) -> None:
        for i, (letter, label) in enumerate([x for x in LISTS if x[0] in self.views]):
            self.tabs.setTabText(i, f"{label} ({self.views[letter].topLevelItemCount()})")

    def add_mask(self, letter: str) -> None:
        label = dict(LISTS)[letter][:-1].lower()
        mask, ok = QInputDialog.getText(self, "Channel Central", f"Mask to add as {'an' if label[0] in 'aeiou' else 'a'} {label} "
                                                                  f"(nick!user@host, * for any part):")
        mask = mask.strip().split()[0] if ok and mask.strip() else ""
        if mask:
            self.s.send("MODE", self.b.name, "+" + letter, mask)

    def remove_selected(self, letter: str) -> None:
        v = self.views.get(letter)
        if v is None:
            return
        masks = [it.text(0) for it in v.selectedItems()]
        step = max(1, self.s.max_modes)
        for i in range(0, len(masks), step):
            chunk = masks[i:i + step]
            self.s.send("MODE", self.b.name, "-" + letter * len(chunk), *chunk)
        for it in v.selectedItems():
            v.takeTopLevelItem(v.indexOfTopLevelItem(it))
        self._titles()
