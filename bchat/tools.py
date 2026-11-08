"""XChat's tool windows: Channel List, Ban List, Ignore List, Friends List, URL Grabber, Character Chart.
Layouts and options follow src/fe-gtk/chanlist.c, banlist.c, ignoregui.c, notifygui.c, urlgrab.c and ascii.c.
Everything shown here comes from the network, so it always goes in as plain text."""
from __future__ import annotations

import fnmatch
import re
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .protocol import lower, strip_format
from .session import IGNORE_KINDS, IGNORE_STATS, Session
from .widgets import FramedDialog


def button(text: str, slot) -> QPushButton:
    b = QPushButton(text)
    b.setAutoDefault(False)
    b.clicked.connect(lambda _=False: slot())
    return b


class _Row(QTreeWidgetItem):
    """Sorts number columns as numbers."""
    NUMERIC = ()

    def __lt__(self, other):
        col = self.treeWidget().sortColumn()
        if col in self.NUMERIC:
            return int(self.text(col) or 0) < int(other.text(col) or 0)
        return self.text(col).lower() < other.text(col).lower()


class ToolWindow(FramedDialog):
    """Stays open beside the main window. Closing only hides it, so it keeps its list."""

    def __init__(self, title: str, win, size=(560, 420)):
        super().__init__(title, win)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.win = win
        self.resize(*size)


# --- Channel List ------------------------------------------------------------------------

class _ChanRow(_Row):
    NUMERIC = (1,)


class ChannelListWindow(ToolWindow):
    def __init__(self, win, s: Session):
        super().__init__(f"BChat: Channel List ({s.net.name})", win, (680, 500))
        self.s = s
        self.rows: list[tuple[str, int, str]] = []
        self.pending: list[tuple[str, int, str]] = []
        self.loading = False
        self.flush_timer = QTimer(self, interval=250, timeout=self._flush)

        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Channel", "Users", "Topic"])
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.view.setColumnWidth(0, 170)
        self.view.setColumnWidth(1, 55)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.itemDoubleClicked.connect(lambda *_: self.join_selected())
        self.body.addWidget(self.view, 1)
        self.status = QLabel()
        self.body.addWidget(self.status)

        g = QGridLayout()
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("Find:"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self.find = QLineEdit()
        self.find.returnPressed.connect(self.apply_filter)
        g.addWidget(self.find, 0, 1)
        self.search_btn = button("Search", self.apply_filter)
        g.addWidget(self.search_btn, 0, 2)

        g.addWidget(QLabel("Look in:"), 1, 0, Qt.AlignmentFlag.AlignRight)
        row = QHBoxLayout()
        self.in_name = QCheckBox("Channel name")
        self.in_name.setChecked(True)
        self.in_topic = QCheckBox("Topic")
        self.in_topic.setChecked(True)
        row.addWidget(self.in_name)
        row.addWidget(self.in_topic)
        row.addStretch(1)
        g.addLayout(row, 1, 1)
        self.download_btn = button("Download List", self.download)
        g.addWidget(self.download_btn, 1, 2)

        g.addWidget(QLabel("Search type:"), 2, 0, Qt.AlignmentFlag.AlignRight)
        self.kind = QComboBox()
        self.kind.addItems(["Simple Search", "Pattern Match (Wildcards)", "Regular Expression"])
        g.addWidget(self.kind, 2, 1, Qt.AlignmentFlag.AlignLeft)
        self.save_btn = button("Save List...", self.save)
        g.addWidget(self.save_btn, 2, 2)

        g.addWidget(QLabel("Show only:"), 3, 0, Qt.AlignmentFlag.AlignRight)
        row = QHBoxLayout()
        row.addWidget(QLabel("channels with"))
        self.min_users = QSpinBox()
        self.min_users.setRange(0, 999999)
        self.min_users.valueChanged.connect(lambda _: self.apply_filter())
        row.addWidget(self.min_users)
        row.addWidget(QLabel("to"))
        self.max_users = QSpinBox()
        self.max_users.setRange(0, 999999)
        self.max_users.setSpecialValueText("any")
        self.max_users.valueChanged.connect(lambda _: self.apply_filter())
        row.addWidget(self.max_users)
        row.addWidget(QLabel("users."))
        row.addStretch(1)
        g.addLayout(row, 3, 1)
        self.join_btn = button("Join Channel", self.join_selected)
        g.addWidget(self.join_btn, 3, 2)
        self.body.addLayout(g)
        self._update_status()

    # the session feeds these while a LIST comes in
    def list_item(self, name: str, users: int, topic: str) -> None:
        self.pending.append((name, users, strip_format(topic)))
        if not self.flush_timer.isActive():
            self.flush_timer.start()

    def list_end(self) -> None:
        self.loading = False
        self._flush()
        self.flush_timer.stop()
        self.download_btn.setEnabled(True)
        self._update_status()

    def download(self) -> None:
        if self.s.state != "connected":
            QMessageBox.information(self, "Channel List", "Not connected.")
            return
        self.rows.clear()
        self.pending.clear()
        self.view.clear()
        self.loading = True
        self.download_btn.setEnabled(False)
        self.s.list_sink = self
        self.s.send("LIST")
        self._update_status()

    def _flush(self) -> None:
        if not self.pending:
            return
        fresh, self.pending = self.pending, []
        self.rows.extend(fresh)
        self.view.setSortingEnabled(False)
        self.view.addTopLevelItems([self._item(r) for r in fresh if self._wanted(r)])
        self.view.setSortingEnabled(True)
        self._update_status()

    @staticmethod
    def _item(r) -> _ChanRow:
        return _ChanRow([r[0], str(r[1]), r[2]])

    def _wanted(self, r) -> bool:
        low, high = self.min_users.value(), self.max_users.value()
        if r[1] < low or (high and r[1] > high):
            return False
        text = self.find.text()
        if not text:
            return True
        hay = []
        if self.in_name.isChecked():
            hay.append(r[0])
        if self.in_topic.isChecked():
            hay.append(r[2])
        kind = self.kind.currentIndex()
        if kind == 2:
            rx = self._regex()
            return rx is not None and any(rx.search(h) for h in hay)
        if kind == 1:
            return any(fnmatch.fnmatchcase(h.lower(), text.lower()) for h in hay)
        return any(text.lower() in h.lower() for h in hay)

    def _regex(self):
        try:
            return re.compile(self.find.text(), re.I)
        except re.error:
            return None

    def apply_filter(self) -> None:
        if self.kind.currentIndex() == 2 and self._regex() is None:
            self.status.setText("That regular expression isn't valid.")
            return
        self.view.setSortingEnabled(False)
        self.view.clear()
        self.view.addTopLevelItems([self._item(r) for r in self.rows if self._wanted(r)])
        self.view.setSortingEnabled(True)
        self._update_status()

    def _update_status(self) -> None:
        shown = [self.view.topLevelItem(i) for i in range(self.view.topLevelItemCount())]
        users = sum(int(i.text(1) or 0) for i in shown)
        total = sum(r[1] for r in self.rows)
        tail = " Downloading..." if self.loading else ""
        self.status.setText(f"Displaying {users}/{total} users on {len(shown)}/{len(self.rows)} channels.{tail}")

    def join_selected(self) -> None:
        it = self.view.currentItem()
        if it is not None:
            self.win.run_command(self.s, f"/join {it.text(0)}")

    def save(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save List", f"{self.s.net.name}-channels.txt", "Text files (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for i in range(self.view.topLevelItemCount()):
                it = self.view.topLevelItem(i)
                f.write(f"{it.text(0):<24} {it.text(1):>6}  {it.text(2)}\n")

    def _menu(self, pos) -> None:
        it = self.view.itemAt(pos)
        if it is None:
            return
        self.view.setCurrentItem(it)
        m = QMenu(self)
        m.addAction("Join Channel", self.join_selected)
        m.addAction("Copy Channel Name", lambda: QApplication.clipboard().setText(it.text(0)))
        m.addAction("Copy Topic Text", lambda: QApplication.clipboard().setText(it.text(2)))
        m.exec(self.view.viewport().mapToGlobal(pos))


# --- Ban List ------------------------------------------------------------------------------

class BanListWindow(ToolWindow):
    KINDS = (("b", "Ban"), ("e", "Exempt"), ("I", "Invite"))

    def __init__(self, win, s: Session, channel: str):
        super().__init__(f"BChat: Ban List ({channel})", win, (620, 400))
        self.s, self.channel = s, channel
        self.waiting: set[str] = set()
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Type", "Mask", "From", "Date"])
        self.view.setRootIsDecorated(False)
        self.view.setSortingEnabled(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setColumnWidth(0, 60)
        self.view.setColumnWidth(1, 260)
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.boxes = {}
        for letter, label in self.KINDS:
            box = QCheckBox(label + "s")
            box.setChecked(letter == "b")
            box.setEnabled(letter in s.modes_list)
            box.toggled.connect(lambda _: self.refresh())
            self.boxes[letter] = box
            row.addWidget(box)
        row.addStretch(1)
        self.body.addLayout(row)
        row = QHBoxLayout()
        row.addStretch(1)
        self.remove_btn = button("Remove", self.remove_selected)
        self.crop_btn = button("Crop", self.crop)
        self.clear_btn = button("Clear", self.clear_all)
        self.refresh_btn = button("Refresh", self.refresh)
        for w in (self.remove_btn, self.crop_btn, self.clear_btn, self.refresh_btn):
            row.addWidget(w)
        self.body.addLayout(row)

    def refresh(self) -> None:
        self.view.clear()
        if self.s.state != "connected":
            return
        self.s.ban_sinks[lower(self.channel)] = self
        for letter, box in self.boxes.items():
            if box.isChecked() and box.isEnabled():
                self.waiting.add(letter)
                self.s.send("MODE", self.channel, "+" + letter)

    # the session feeds these
    def ban_item(self, letter: str, mask: str, who: str, when: str) -> None:
        label = dict(self.KINDS)[letter]
        date = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(int(when))) if when.isdigit() else ""
        it = QTreeWidgetItem([label, mask, who.split("!")[0], date])
        it.setData(0, Qt.ItemDataRole.UserRole, letter)
        self.view.addTopLevelItem(it)

    def ban_end(self, letter: str) -> None:
        self.waiting.discard(letter)

    def _take(self, items) -> None:
        """Takes the marks off, grouped by type so the server gets them in as few lines as it allows."""
        by_kind: dict[str, list[str]] = {}
        for it in items:
            by_kind.setdefault(it.data(0, Qt.ItemDataRole.UserRole), []).append(it.text(1))
            self.view.takeTopLevelItem(self.view.indexOfTopLevelItem(it))
        b = self.s.buffers.get(lower(self.channel))
        if b is not None:
            for letter, masks in by_kind.items():
                self.s.set_mode_for(b, "-" + letter, masks)

    def remove_selected(self) -> None:
        items = self.view.selectedItems()
        if not items:
            QMessageBox.information(self, "Ban List", "You must select some bans.")
            return
        self._take(items)

    def crop(self) -> None:
        keep = self.view.selectedItems()
        if not keep:
            QMessageBox.information(self, "Ban List", "You must select some bans.")
            return
        self._take([self.view.topLevelItem(i) for i in range(self.view.topLevelItemCount()) if self.view.topLevelItem(i) not in keep])

    def clear_all(self, confirm: bool = True) -> None:
        n = self.view.topLevelItemCount()
        if not n:
            return
        if confirm and QMessageBox.question(self, "Ban List", f"Are you sure you want to remove all bans in {self.channel}?") != QMessageBox.StandardButton.Yes:
            return
        self._take([self.view.topLevelItem(i) for i in range(n)])


# --- Ignore List ---------------------------------------------------------------------------

class IgnoreWindow(ToolWindow):
    COLUMNS = ("Channel", "Private", "Notice", "CTCP", "DCC", "Invite", "Unignore")

    def __init__(self, win):
        super().__init__("BChat: Ignore list", win, (640, 380))
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Mask", *self.COLUMNS])
        self.view.setRootIsDecorated(False)
        self.view.setColumnWidth(0, 210)
        for i in range(1, 8):
            self.view.setColumnWidth(i, 58)
        self.view.itemChanged.connect(self._changed)
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Ignore Stats:"))
        self.stats: dict[str, QLabel] = {}
        for key, label in (("C", "Channel:"), ("P", "Private:"), ("N", "Notice:"), ("T", "CTCP:"), ("I", "Invite:")):
            row.addWidget(QLabel(label))
            self.stats[key] = QLabel("0")
            row.addWidget(self.stats[key])
        row.addStretch(1)
        self.body.addLayout(row)
        row = QHBoxLayout()
        row.addStretch(1)
        self.add_btn = button("Add...", self.ask_add)
        self.delete_btn = button("Delete", self.delete_selected)
        self.clear_btn = button("Clear", self.clear)
        for w in (self.add_btn, self.delete_btn, self.clear_btn):
            row.addWidget(w)
        self.body.addLayout(row)
        self.timer = QTimer(self, interval=1000, timeout=self.show_stats)
        self.timer.start()
        self.fill()
        self.show_stats()

    def fill(self) -> None:
        cfg = self.win.cfg
        self.view.blockSignals(True)
        self.view.clear()
        for mask in cfg.ignores:
            it = QTreeWidgetItem([mask])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            kinds = cfg.ignore_kinds.get(mask, IGNORE_KINDS)
            for i, k in enumerate("CPNTDIU", 1):
                it.setCheckState(i, Qt.CheckState.Checked if k in kinds else Qt.CheckState.Unchecked)
            it.setData(0, Qt.ItemDataRole.UserRole, mask)
            self.view.addTopLevelItem(it)
        self.view.blockSignals(False)

    def show_stats(self) -> None:
        for key, label in self.stats.items():
            label.setText(str(IGNORE_STATS.get(key, 0)))

    def _changed(self, it: QTreeWidgetItem, col: int) -> None:
        cfg = self.win.cfg
        old = it.data(0, Qt.ItemDataRole.UserRole)
        new = it.text(0).strip()
        if col == 0:
            if not new or (new != old and new in cfg.ignores):
                self.fill()
                return
            cfg.ignores[cfg.ignores.index(old)] = new
            cfg.ignore_kinds[new] = cfg.ignore_kinds.pop(old, IGNORE_KINDS)
            it.setData(0, Qt.ItemDataRole.UserRole, new)
        else:
            cfg.ignore_kinds[new] = "".join(k for i, k in enumerate("CPNTDIU", 1) if it.checkState(i) == Qt.CheckState.Checked)
        self.win.save_config()

    def ask_add(self) -> None:
        mask, ok = QInputDialog.getText(self, "Ignore", "Enter mask to ignore:", text="nick!userid@host.com")
        if ok:
            self.add(mask)

    def add(self, mask: str) -> None:
        mask = mask.strip()
        if not mask:
            return
        if "!" not in mask and "@" not in mask:
            mask += "!*@*"
        cfg = self.win.cfg
        if mask in cfg.ignores:
            QMessageBox.information(self, "Ignore", "That mask already exists.")
            return
        cfg.ignores.append(mask)
        self.fill()
        self.win.save_config()

    def delete_selected(self) -> None:
        it = self.view.currentItem()
        if it is None:
            return
        mask = it.data(0, Qt.ItemDataRole.UserRole)
        self.win.cfg.ignores.remove(mask)
        self.win.cfg.ignore_kinds.pop(mask, None)
        self.fill()
        self.win.save_config()

    def clear(self) -> None:
        self.win.cfg.ignores.clear()
        self.win.cfg.ignore_kinds.clear()
        self.fill()
        self.win.save_config()


# --- Friends List --------------------------------------------------------------------------

class FriendsWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Friends List", win, (520, 340))
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Name", "Status", "Network", "Last Seen"])
        self.view.setRootIsDecorated(False)
        self.view.setSortingEnabled(True)
        self.view.itemDoubleClicked.connect(lambda *_: self.open_dialog())
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.add_btn = button("Add...", self.ask_add)
        self.remove_btn = button("Remove", self.remove_selected)
        self.dialog_btn = button("Open Dialog", self.open_dialog)
        for w in (self.add_btn, self.remove_btn, self.dialog_btn):
            row.addWidget(w)
        self.body.addLayout(row)
        self.timer = QTimer(self, interval=30000, timeout=self.fill)
        self.timer.start()
        self.fill()

    @staticmethod
    def _ago(t: float) -> str:
        if not t:
            return "Never"
        return f"{int((time.time() - t) // 60)} minutes ago"

    def fill(self) -> None:
        keep = self.view.currentItem().text(0) if self.view.currentItem() else ""
        self.view.clear()
        for nick in self.win.cfg.friends:
            on, off = [], []
            seen = 0.0
            for s in self.win.sessions.values():
                st = s.friend_state.get(lower(nick))
                if st is None:
                    continue
                (on if st["online"] else off).append(s.net.name)
                seen = max(seen, st["seen"])
            if on:
                row = [nick, "Online", ", ".join(on), self._ago(seen)]
            else:
                row = [nick, "Offline", "", self._ago(seen)]
            it = QTreeWidgetItem(row)
            self.view.addTopLevelItem(it)
            if nick == keep:
                self.view.setCurrentItem(it)

    def ask_add(self) -> None:
        nick, ok = QInputDialog.getText(self, "Friends List", "Enter nickname to add:")
        if not ok:
            return
        nets, ok = QInputDialog.getText(self, "Friends List", "Notify on these networks (comma separated, empty for all):")
        if ok:
            self.add(nick, nets)

    def add(self, nick: str, nets: str = "") -> None:
        self.win.add_friend(nick, nets)
        self.fill()

    def remove_selected(self) -> None:
        it = self.view.currentItem()
        if it is not None:
            self.win.remove_friend(it.text(0))
            self.fill()

    def open_dialog(self) -> None:
        it = self.view.currentItem()
        if it is None:
            return
        nick = it.text(0)
        online = [s for s in self.win.sessions.values() if s.friend_state.get(lower(nick), {}).get("online")]
        s = online[0] if online else self.win.session
        if s is not None:
            self.win.select_buffer(s.buffer(nick))


# --- URL Grabber ---------------------------------------------------------------------------

class UrlGrabberWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: URL Grabber", win, (560, 340))
        self.view = QTreeWidget()
        self.view.setHeaderHidden(True)
        self.view.setRootIsDecorated(False)
        self.view.itemDoubleClicked.connect(lambda it, _: self.win.open_url(it.text(0)))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.clear_btn = button("Clear", self.clear)
        self.copy_btn = button("Copy", self.copy)
        self.save_btn = button("Save As...", self.save)
        for w in (self.clear_btn, self.copy_btn, self.save_btn):
            row.addWidget(w)
        self.body.addLayout(row)
        self.fill()

    def fill(self) -> None:
        self.view.clear()
        self.view.addTopLevelItems([QTreeWidgetItem([u]) for u in self.win.urls])

    def clear(self) -> None:
        self.win.urls.clear()
        self.fill()

    def copy(self) -> None:
        it = self.view.currentItem()
        if it is not None:
            QApplication.clipboard().setText(it.text(0))

    def save(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save URLs", "urls.txt", "Text files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.win.urls) + "\n")

    def _menu(self, pos) -> None:
        it = self.view.itemAt(pos)
        if it is not None:
            self.view.setCurrentItem(it)
            self.win.url_menu(it.text(0)).exec(self.view.viewport().mapToGlobal(pos))


# --- File Transfers, Direct Chat ------------------------------------------------------------

def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class TransfersWindow(ToolWindow):
    STATUS = {"queued": "Waiting", "connecting": "Connecting", "active": "Active", "done": "Complete", "failed": "Failed", "aborted": "Aborted"}

    def __init__(self, win):
        super().__init__("BChat: File Transfers", win, (760, 340))
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Status", "File", "Size", "Position", "%", "KB/s", "ETA", "Nick"])
        self.view.setRootIsDecorated(False)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for i, w in enumerate((80, 220, 70, 70, 40, 60, 70)):
            self.view.setColumnWidth(i, w)
        self.view.itemSelectionChanged.connect(self._buttons)
        self.body.addWidget(self.view, 1)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.info)
        row = QHBoxLayout()
        self.up_box = QCheckBox("Uploads")
        self.up_box.setChecked(True)
        self.down_box = QCheckBox("Downloads")
        self.down_box.setChecked(True)
        self.up_box.toggled.connect(lambda _: self.fill())
        self.down_box.toggled.connect(lambda _: self.fill())
        row.addWidget(self.up_box)
        row.addWidget(self.down_box)
        row.addStretch(1)
        self.accept_btn = button("Accept", self.do_accept)
        self.resume_btn = button("Resume", self.do_resume)
        self.abort_btn = button("Abort", self.do_abort)
        self.clear_btn = button("Clear", self.win.dcc.clear_finished)
        self.folder_btn = button("Open Folder", self.open_folder)
        for w in (self.accept_btn, self.resume_btn, self.abort_btn, self.clear_btn, self.folder_btn):
            row.addWidget(w)
        self.body.addLayout(row)
        win.dcc.updated.connect(self.fill)
        self._buttons()

    def _rows(self):
        return [t for t in self.win.dcc.items if (t.kind == "send" and self.up_box.isChecked()) or (t.kind == "recv" and self.down_box.isChecked())]

    def fill(self) -> None:
        if not self.isVisible() and self.view.topLevelItemCount():
            return
        picked = [it.data(0, Qt.ItemDataRole.UserRole) for it in self.view.selectedItems()]
        rows = self._rows()
        while self.view.topLevelItemCount() > len(rows):
            self.view.takeTopLevelItem(self.view.topLevelItemCount() - 1)
        while self.view.topLevelItemCount() < len(rows):
            self.view.addTopLevelItem(QTreeWidgetItem())
        for i, t in enumerate(rows):
            it = self.view.topLevelItem(i)
            for col, value in enumerate((self.STATUS[t.state], t.name, _human(t.size), _human(t.pos), str(t.percent()),
                                         f"{t.cps / 1024:.1f}" if t.state == "active" else "", t.eta(), t.nick)):
                it.setText(col, value)
            it.setData(0, Qt.ItemDataRole.UserRole, t)
            it.setSelected(t in picked)
        self._buttons()

    def selected(self):
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.view.selectedItems()]

    def _buttons(self) -> None:
        picked = self.selected()
        self.accept_btn.setEnabled(any(t.kind == "recv" and t.state == "queued" for t in picked))
        self.resume_btn.setEnabled(any(self.win.dcc.can_resume(t) for t in picked))
        self.abort_btn.setEnabled(any(t.active for t in picked))
        self.folder_btn.setEnabled(len(picked) == 1)
        if len(picked) == 1:
            t = picked[0]
            where = t.path or ""
            self.info.setText(f"{t.ip or 'you'}:{t.port}  {where}" + (f"  {t.error}" if t.error else ""))
        else:
            self.info.setText("")

    def do_accept(self) -> None:
        for t in self.selected():
            self.win.accept_transfer(t)

    def do_resume(self) -> None:
        for t in self.selected():
            self.win.dcc.resume(t)

    def do_abort(self) -> None:
        for t in self.selected():
            t.abort()

    def open_folder(self) -> None:
        from pathlib import Path
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        picked = self.selected()
        if picked and picked[0].path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(picked[0].path).parent)))


class DirectChatWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Direct Chat", win, (520, 280))
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Status", "Nick", "Recv", "Sent", "Start Time"])
        self.view.setRootIsDecorated(False)
        for i, w in enumerate((90, 130, 70, 70)):
            self.view.setColumnWidth(i, w)
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.accept_btn = button("Accept", self.do_accept)
        self.abort_btn = button("Abort", self.do_abort)
        row.addWidget(self.accept_btn)
        row.addWidget(self.abort_btn)
        self.body.addLayout(row)
        win.dcc.updated.connect(self.fill)

    def fill(self) -> None:
        picked = self.view.currentItem().data(0, Qt.ItemDataRole.UserRole) if self.view.currentItem() else None
        self.view.clear()
        for t in self.win.dcc.items:
            if t.kind != "chat":
                continue
            when = time.strftime("%H:%M:%S", time.localtime(t.started)) if t.started else ""
            it = QTreeWidgetItem([TransfersWindow.STATUS[t.state], t.nick, str(t.recv_bytes), str(t.sent_bytes), when])
            it.setData(0, Qt.ItemDataRole.UserRole, t)
            self.view.addTopLevelItem(it)
            if t is picked:
                self.view.setCurrentItem(it)

    def _current(self):
        it = self.view.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def do_accept(self) -> None:
        t = self._current()
        if t is not None and t.ip:
            self.win.dcc.accept(t)

    def do_abort(self) -> None:
        t = self._current()
        if t is not None:
            t.abort()


# --- Plugins and Scripts -----------------------------------------------------------------------

class PluginsWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Plugins and Scripts", win, (640, 300))
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Name", "Version", "File", "Description"])
        self.view.setRootIsDecorated(False)
        self.view.setColumnWidth(0, 130)
        self.view.setColumnWidth(1, 60)
        self.view.setColumnWidth(2, 150)
        self.body.addWidget(self.view, 1)
        hint = QLabel(f"Python scripts in {win.plugins.folder} load at start. They run with your full access, so only use ones you trust.")
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setWordWrap(True)
        self.body.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        self.load_btn = button("Load...", self.do_load)
        self.unload_btn = button("Unload", self.do_unload)
        self.reload_btn = button("Reload", self.do_reload)
        for w in (self.load_btn, self.unload_btn, self.reload_btn):
            row.addWidget(w)
        self.body.addLayout(row)
        self.fill()

    def fill(self) -> None:
        self.view.clear()
        for p in self.win.plugins.plugins:
            it = QTreeWidgetItem([p.name, p.version, p.path.name, p.description])
            it.setData(0, Qt.ItemDataRole.UserRole, p)
            self.view.addTopLevelItem(it)

    def _current(self):
        it = self.view.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def do_load(self) -> None:
        self.win.load_plugin_dialog()
        self.fill()

    def do_unload(self) -> None:
        p = self._current()
        if p is not None:
            self.win.plugins.unload(p)
            self.fill()

    def do_reload(self) -> None:
        p = self._current()
        if p is not None:
            self.win.plugins.reload(p)
            self.fill()


# --- Help ----------------------------------------------------------------------------------

class HelpWindow(ToolWindow):
    def __init__(self, win):
        from .commands import COMMAND_NAMES, HELP, user_commands
        super().__init__("BChat: Help", win, (680, 520))
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a command")
        self.find.textChanged.connect(self._filter)
        self.body.addWidget(self.find)
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Command", "What it does"])
        self.view.setRootIsDecorated(False)
        self.view.setColumnWidth(0, 120)
        rows = {name: text for name, text in HELP.items()}
        for name, cmd in user_commands(win.cfg):
            rows.setdefault(name.lower(), f"User command: {cmd}")
        for name in COMMAND_NAMES:
            rows.setdefault(name, "")
        for name in sorted(rows):
            self.view.addTopLevelItem(QTreeWidgetItem(["/" + name, rows[name]]))
        self.body.addWidget(self.view, 1)
        keys = QLabel("Keys: Tab completes a nick. Ctrl+B bold, Ctrl+K colour, Ctrl+U underline, Ctrl+Shift+I italic, Ctrl+R reverse, Ctrl+E strikethrough, Ctrl+O reset. Alt+1-9 and Ctrl+PageUp/Down switch tabs. "
                      "Settings > Advanced > Keyboard Shortcuts lists the rest.")
        keys.setWordWrap(True)
        self.body.addWidget(keys)

    def _filter(self, text: str) -> None:
        low = text.lower()
        for i in range(self.view.topLevelItemCount()):
            it = self.view.topLevelItem(i)
            it.setHidden(low not in it.text(0).lower() and low not in it.text(1).lower())


# --- Character Chart -----------------------------------------------------------------------

class CharChartWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Character Chart", win, (528, 400))
        grid_box = QWidget()
        g = QGridLayout(grid_box)
        g.setSpacing(1)
        g.setContentsMargins(0, 0, 0, 0)
        self.buttons = {}
        for code in range(32, 256):
            if 127 <= code < 160:      # control codes: nothing to show or send
                continue
            ch = chr(code)
            b = QPushButton(ch, objectName="compact")
            b.setAutoDefault(False)
            b.setFixedSize(30, 26)
            b.setToolTip(f"{code} (0x{code:02X})")
            b.clicked.connect(lambda _=False, c=ch: self.insert(c))
            r = code - 32 if code < 127 else code - 32 - 33
            g.addWidget(b, r // 16, r % 16)
            self.buttons[code] = b
        self.body.addWidget(grid_box)
        self.adjustSize()

    def insert(self, ch: str) -> None:
        self.win.input.insert(ch)
