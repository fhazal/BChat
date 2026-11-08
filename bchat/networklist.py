"""XChat's Network List dialog and its Edit window."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import config
from .config import NetworkConfig, Server
from .widgets import FramedDialog, icon
from .xchat_import import parse_server


def ask_save(parent, name: str) -> str:
    """'save', 'discard' or 'stay' when the Edit window is closed with unsaved changes (tests replace this)."""
    box = QMessageBox(QMessageBox.Icon.Question, "BChat", f"Save changes to {name}?",
                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                      QMessageBox.StandardButton.Cancel, parent)
    box.setDefaultButton(QMessageBox.StandardButton.Save)
    r = box.exec()
    return {QMessageBox.StandardButton.Save: "save", QMessageBox.StandardButton.Discard: "discard"}.get(
        QMessageBox.StandardButton(r), "stay")


class NetworkEditDialog(FramedDialog):
    def __init__(self, net: NetworkConfig, parent=None):
        super().__init__(f"BChat: Edit {net.name}", parent)
        self.net = net
        self.resize(420, 600)
        top = QFormLayout()
        self.name = QLineEdit(net.name, self)
        top.addRow("Network name:", self.name)
        self.body.addLayout(top)
        self.body.addWidget(QLabel("Servers, one per line: host/port. Use /+port for SSL."))
        self.servers = QPlainTextEdit(self)
        self.servers.setPlainText("\n".join(f"{s.host}/{'+' if s.ssl else ''}{s.port}" for s in net.servers))
        self.body.addWidget(self.servers)
        form = QFormLayout()
        self.autojoin = QLineEdit(net.autojoin, self)
        self.commands = QLineEdit("; ".join(net.commands), self)
        self.nick = QLineEdit(net.nick, self)
        self.nick2 = QLineEdit(net.nick2, self)
        self.username = QLineEdit(net.username, self)
        self.realname = QLineEdit(net.realname, self)
        self.password = QLineEdit(net.password, self)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.nickserv = QLineEdit(net.nickserv, self)
        self.nickserv.setEchoMode(QLineEdit.EchoMode.Password)
        self.sasl_user = QLineEdit(net.sasl_user, self)
        self.sasl_password = QLineEdit(net.sasl_password, self)
        self.sasl_password.setEchoMode(QLineEdit.EchoMode.Password)
        for label, w in (("Auto-join channels:", self.autojoin), ("Connect commands:", self.commands),
                         ("Nick name:", self.nick), ("Second choice:", self.nick2), ("User name:", self.username),
                         ("Real name:", self.realname), ("Server password:", self.password), ("NickServ password:", self.nickserv),
                         ("SASL account:", self.sasl_user), ("SASL password:", self.sasl_password)):
            form.addRow(label, w)
        self.body.addLayout(form)
        self.use_global = QCheckBox("Use global user information", self)
        self.use_global.setChecked(net.use_global)
        self.auto = QCheckBox("Auto connect to this network at startup", self)
        self.auto.setChecked(net.autoconnect)
        self.cycle = QCheckBox("Connect to selected server only", self)
        self.cycle.setChecked(not net.cycle)
        self.invalid = QCheckBox("Accept invalid SSL certificate", self)
        self.invalid.setChecked(net.allow_invalid_cert)
        for c in (self.use_global, self.auto, self.cycle, self.invalid):
            self.body.addWidget(c)
        row = QHBoxLayout()
        cancel = QPushButton(icon("close-light"), "&Cancel", self)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(lambda: FramedDialog.reject(self))   # throw changes away, no question
        save = QPushButton(icon("save"), "&Save", self)   # XChat's floppy icon, bottom right next to Cancel
        save.setDefault(True)
        save.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        self.body.addLayout(row)
        self._start = self._state()

    def _state(self) -> tuple:
        return (self.name.text(), self.servers.toPlainText(), self.autojoin.text(), self.commands.text(), self.nick.text(),
                self.nick2.text(), self.username.text(), self.realname.text(), self.password.text(), self.nickserv.text(),
                self.sasl_user.text(), self.sasl_password.text(), self.use_global.isChecked(), self.auto.isChecked(),
                self.cycle.isChecked(), self.invalid.isChecked())

    def reject(self) -> None:
        """Red button or Esc: ask before losing changes (it used to drop them silently)."""
        if self._state() != self._start:
            choice = ask_save(self, self.net.name)
            if choice == "save":
                self.accept()
                return
            if choice == "stay":
                return
        super().reject()

    def accept(self) -> None:
        n = self.net
        win = getattr(self.parent(), "win", self.parent())
        if self.name.text().strip() != n.name and hasattr(win, "rename_network"):
            if not win.rename_network(n, self.name.text()):
                self.name.setText(n.name)   # empty or already used: keep the old name, stay open
                self.name.setFocus()
                return
        n.servers = [parse_server(l.strip(), False) for l in self.servers.toPlainText().splitlines() if l.strip()]
        n.autojoin = self.autojoin.text().strip()
        n.commands = [c.strip() for c in self.commands.text().split(";") if c.strip()]
        n.nick, n.nick2 = self.nick.text().strip(), self.nick2.text().strip()
        n.username, n.realname = self.username.text().strip(), self.realname.text().strip()
        n.password, n.nickserv = self.password.text(), self.nickserv.text()
        n.sasl_user, n.sasl_password = self.sasl_user.text().strip(), self.sasl_password.text()
        n.use_global = self.use_global.isChecked()
        n.autoconnect = self.auto.isChecked()
        n.cycle = not self.cycle.isChecked()
        n.allow_invalid_cert = self.invalid.isChecked()
        super().accept()


class NetItem(QTreeWidgetItem):
    """A row of the Network List; text() without a column, like the old list's items."""
    def text(self, column: int = 0) -> str:
        return super().text(column)

    def setText(self, *args) -> None:
        super().setText(*(args if len(args) == 2 else (0, args[0])))


class NetTree(QTreeWidget):
    """Favourite Networks, Popular Networks and My Networks in one box. count/item/setCurrentRow look only at
    your own networks (favourites + the rest) in cfg.networks order, as the old flat list did, so row numbers
    still match cfg.networks."""
    order: list = []

    def group(self, key: str):
        for i in range(self.topLevelItemCount()):
            g = self.topLevelItem(i)
            if g.data(0, Qt.ItemDataRole.UserRole + 1) == key:
                return g
        return None

    def mine(self) -> list[NetItem]:
        rows = [g.child(i) for g in (self.group("fav"), self.group("mine")) if g is not None for i in range(g.childCount())]
        ids = {id(n): i for i, n in enumerate(self.order)}
        return sorted(rows, key=lambda it: ids.get(id(it.data(0, Qt.ItemDataRole.UserRole)), len(ids)))

    def count(self) -> int:
        return len(self.mine())

    def item(self, row: int):
        m = self.mine()
        return m[row] if 0 <= row < len(m) else None

    def setCurrentRow(self, row: int) -> None:
        it = self.item(row)
        if it is not None:
            self.setCurrentItem(it)

    def editItem(self, item, column: int = 0) -> None:
        super().editItem(item, column)


class NetworkListDialog(FramedDialog):
    def __init__(self, win):
        super().__init__("BChat: Network List", win)
        self.win = win
        self.cfg = win.cfg
        self.resize(470, 620)       # room for the popular networks and their notes
        self.body.addWidget(self._heading("User Information"))
        form = QFormLayout()
        form.setContentsMargins(8, 0, 0, 0)
        self.nick1 = QLineEdit(self.cfg.nick, self)
        self.nick2 = QLineEdit(self.cfg.nick2, self)
        self.nick3 = QLineEdit(self.cfg.nick3, self)
        self.user = QLineEdit(self.cfg.username, self)
        self.real = QLineEdit(self.cfg.realname, self)
        for label, w in (("&Nick name:", self.nick1), ("Second choice:", self.nick2), ("Third choice:", self.nick3),
                         ("&User name:", self.user), ("Real na&me:", self.real)):
            form.addRow(label, w)
        self.body.addLayout(form)
        self.body.addWidget(self._heading("Networks"))
        mid = QHBoxLayout()
        self.list = NetTree(self)
        self.list.setHeaderHidden(True)
        self.list.setColumnCount(2)
        self.list.setIconSize(QSize(16, 16))
        self.list.setIndentation(14)
        self.list.header().setStretchLastSection(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.itemDoubleClicked.connect(lambda it, _c=0: self._connect() if it.parent() is not None else None)
        self.list.currentItemChanged.connect(lambda *_: self._buttons())
        self.list.itemExpanded.connect(lambda it: self._group_open(it, True))
        self.list.itemCollapsed.connect(lambda it: self._group_open(it, False))
        # XChat: click the selected name (or F2) to rename it
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.itemChanged.connect(self._renamed)
        mid.addWidget(self.list, 1)
        buttons = QVBoxLayout()
        buttons.setSpacing(5)
        self.btn: dict[str, QPushButton] = {}
        for text, ico, slot in (("&Add", "add", self._add), ("&Remove", "remove", self._remove), ("&Edit...", "", self._edit),
                                ("&Sort", "", self._sort), ("&Favor", "", self._favor)):
            b = QPushButton(icon(ico), text, self) if ico else QPushButton(text, self)
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            buttons.addWidget(b)
            self.btn[text.replace("&", "")] = b
        buttons.addStretch(1)
        mid.addLayout(buttons)
        self.body.addLayout(mid, 1)
        opts = QHBoxLayout()
        self.skip = QCheckBox("Skip network list on startup", self)
        self.skip.setChecked(self.cfg.skip_network_list)
        opts.addWidget(self.skip)          # no "Show favorites only": Favourite Networks is its own group now (fold the rest)
        self.body.addLayout(opts)
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        row = QHBoxLayout()
        close = QPushButton(icon("close-light"), "&Close", self)
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        connect = QPushButton(icon("connect"), "C&onnect", self)
        connect.setDefault(True)
        connect.clicked.connect(self._connect)
        row.addWidget(close)
        row.addStretch(1)
        row.addWidget(connect)
        self.body.addLayout(row)
        self._fill()

    @staticmethod
    def _heading(text: str) -> QLabel:
        lab = QLabel(f"<b>{text}</b>")
        return lab

    def _shield(self, kind: str) -> QIcon:
        from . import lucide
        t = self.cfg.theme
        name, col = {"ok": ("shield-check", t.join), "ask": ("shield-alert", t.palette[7])}.get(kind, ("shield-alert", t.muted))
        pm = QPixmap.fromImage(lucide.image(name, col, 32))
        pm.setDevicePixelRatio(2.0)
        return QIcon(pm)

    def _star(self) -> QIcon:
        """Favourite networks: Lucide's star in the theme's yellow (the same star as Favourite Channels)."""
        from . import lucide
        pm = QPixmap.fromImage(lucide.image("star", self.cfg.theme.palette[8], 32))
        pm.setDevicePixelRatio(2.0)
        return QIcon(pm)

    @staticmethod
    def _blank() -> QIcon:
        pm = QPixmap(32, 32)
        pm.fill(QColor(0, 0, 0, 0))
        pm.setDevicePixelRatio(2.0)
        return QIcon(pm)

    def _group(self, text: str, key: str) -> QTreeWidgetItem:
        g = QTreeWidgetItem([text])
        f = QFont(self.list.font())
        f.setBold(True)
        g.setFont(0, f)
        g.setFlags(Qt.ItemFlag.ItemIsEnabled)
        g.setData(0, Qt.ItemDataRole.UserRole + 1, key)
        self.list.addTopLevelItem(g)
        g.setExpanded(self.cfg.netlist_open.get(key, True))
        return g

    def _group_open(self, it, on: bool) -> None:
        key = it.data(0, Qt.ItemDataRole.UserRole + 1)
        if key and not getattr(self, "_filling", False):
            self.cfg.netlist_open[key] = on

    def _fill(self, *_):
        from .popular import POPULAR, TLS_TIP, find_saved
        cur = self._current()
        cur_pop = self._popular()
        self._filling = True
        self.list.blockSignals(True)
        self.list.clear()
        muted = QColor(self.cfg.theme.muted)
        self.list.order = list(self.cfg.networks)
        # Favourite Networks on top (only when there is one), then Popular Networks, then My Networks
        favs = self._group("Favourite Networks", "fav") if any(n.favorite for n in self.cfg.networks) else None
        pop = self._group("Popular Networks", "popular")
        mine = self._group("My Networks", "mine")
        for n in self.cfg.networks:
            parent = favs if n.favorite else mine
            if parent is None:
                continue
            it = NetItem([n.name, n.servers[0].host if n.servers else ""])
            it.setIcon(0, self._star() if n.favorite else self._blank())
            if n.favorite:
                it.setToolTip(0, "Favourite: Favor moves it back to My Networks")
            it.setData(0, Qt.ItemDataRole.UserRole, n)
            it.setForeground(1, muted)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            parent.addChild(it)
            if n is cur:
                self.list.setCurrentItem(it)
        if pop is not None:
            for p in POPULAR:
                it = NetItem([p.name, p.about])
                it.setIcon(0, self._shield(p.tls))
                it.setForeground(1, muted)
                it.setData(0, Qt.ItemDataRole.UserRole + 2, p)
                saved = find_saved(self.cfg, p)
                it.setToolTip(0, f"{p.host}:{p.port} · {TLS_TIP[p.tls]}" + (f" · in My Networks as {saved.name}" if saved else ""))
                it.setToolTip(1, it.toolTip(0))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                pop.addChild(it)
                if p == cur_pop:
                    self.list.setCurrentItem(it)
        self.list.resizeColumnToContents(0)
        self.list.blockSignals(False)
        self._filling = False
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._buttons()

    def _popular(self):
        lst = getattr(self, "list", None)
        it = lst.currentItem() if lst is not None else None
        return it.data(0, Qt.ItemDataRole.UserRole + 2) if it is not None else None

    def _buttons(self) -> None:
        mine = self._current() is not None
        for name in ("Remove", "Edit...", "Favor"):
            if name in self.btn:
                self.btn[name].setEnabled(mine)

    def _renamed(self, it, _col: int = 0) -> None:
        n = it.data(0, Qt.ItemDataRole.UserRole)
        if n is None or getattr(self, "_filling", False):
            return
        text = it.text()
        if n.favorite and text.startswith("* "):
            text = text[2:]
        self.win.rename_network(n, text)
        self.list.blockSignals(True)
        it.setText(0, n.name)   # taken or empty names snap back
        self.list.blockSignals(False)

    def _current(self) -> NetworkConfig | None:
        lst = getattr(self, "list", None)
        it = lst.currentItem() if lst is not None else None
        return it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None

    def _store(self) -> None:
        c = self.cfg
        c.nick, c.nick2, c.nick3 = self.nick1.text().strip(), self.nick2.text().strip(), self.nick3.text().strip()
        c.username, c.realname = self.user.text().strip(), self.real.text().strip()
        c.skip_network_list = self.skip.isChecked()
        config.save(c, self.win.cfg_dir)

    def done(self, r):
        self._store()
        super().done(r)

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Network", "Name:")
        if ok and name.strip():
            n = NetworkConfig(name.strip())
            self.cfg.networks.insert(0, n)
            self._fill()
            self.list.setCurrentRow(0)
            self._edit()

    def _remove(self) -> None:
        n = self._current()
        if n is not None:
            self.cfg.networks.remove(n)
            self._fill()

    def _edit(self) -> None:
        n = self._current()
        if n is not None:
            NetworkEditDialog(n, self).exec()
            self._fill()

    def _sort(self) -> None:
        self.cfg.networks.sort(key=lambda n: n.name.lower())
        self._fill()

    def _favor(self) -> None:
        n = self._current()
        if n is not None:
            n.favorite = not n.favorite
            self._fill()

    def _connect(self) -> None:
        n = self._current()
        p = self._popular()
        if n is None and p is not None:               # a popular network: copied into My Networks, then connect
            from .popular import add
            n = add(self.cfg, p)
        if n is None:
            return
        self._store()
        self.accept()
        self.win.connect_network(n)
