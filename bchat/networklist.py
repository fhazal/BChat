"""XChat's Network List dialog and its Edit window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout)

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


class NetworkListDialog(FramedDialog):
    def __init__(self, win):
        super().__init__("BChat: Network List", win)
        self.win = win
        self.cfg = win.cfg
        self.resize(340, 470)
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
        self.list = QListWidget(self)
        self.list.itemDoubleClicked.connect(lambda _: self._connect())
        # XChat: click the selected name (or F2) to rename it
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.itemChanged.connect(self._renamed)
        mid.addWidget(self.list, 1)
        buttons = QVBoxLayout()
        buttons.setSpacing(5)
        for text, ico, slot in (("&Add", "add", self._add), ("&Remove", "remove", self._remove), ("&Edit...", "", self._edit),
                                ("&Sort", "", self._sort), ("&Favor", "", self._favor)):
            b = QPushButton(icon(ico), text, self) if ico else QPushButton(text, self)
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        mid.addLayout(buttons)
        self.body.addLayout(mid, 1)
        opts = QHBoxLayout()
        self.skip = QCheckBox("Skip network list on startup", self)
        self.skip.setChecked(self.cfg.skip_network_list)
        self.fav = QCheckBox("Show favorites only", self)
        self.fav.toggled.connect(self._fill)
        opts.addWidget(self.skip)
        opts.addWidget(self.fav)
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

    def _fill(self, *_):
        cur = self._current()
        self.list.clear()
        for n in self.cfg.networks:
            if self.fav.isChecked() and not n.favorite:
                continue
            it = QListWidgetItem(("* " if n.favorite else "") + n.name)
            it.setData(Qt.ItemDataRole.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            self.list.addItem(it)
            if n is cur:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _renamed(self, it: QListWidgetItem) -> None:
        n = it.data(Qt.ItemDataRole.UserRole)
        if n is None:
            return
        text = it.text()
        if n.favorite and text.startswith("* "):
            text = text[2:]
        self.win.rename_network(n, text)
        self.list.blockSignals(True)
        it.setText(("* " if n.favorite else "") + n.name)   # taken or empty names snap back
        self.list.blockSignals(False)

    def _current(self) -> NetworkConfig | None:
        lst = getattr(self, "list", None)
        it = lst.currentItem() if lst is not None else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

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
        if n is None:
            return
        self._store()
        self.accept()
        self.win.connect_network(n)
