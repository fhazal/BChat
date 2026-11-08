"""Favourite Channels (mIRC's Favorites, in BChat's look). One list per person across networks.

Join-on-connect channels stay in each network's auto-join text (XChat's "#a,#b keyA,keyB"), so the network
editor, XChat imports and connecting keep working as before. Channels saved but not joined on connect live in
cfg.fav_saved ("network/#chan key"); notes in cfg.fav_notes."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTreeWidget, QTreeWidgetItem)

from .protocol import lower
from .widgets import FramedDialog, icon


@dataclass
class Fav:
    network: str
    channel: str
    key: str = ""
    join: bool = True
    note: str = ""

    @property
    def id(self) -> str:
        return f"{self.network}/{self.channel}"


def parse_autojoin(text: str) -> list[tuple[str, str]]:
    """XChat's auto-join: "#a,#b keyA" -> [("#a", "keyA"), ("#b", "")]."""
    chans, _, keys = (text or "").strip().partition(" ")
    names = [c.strip() for c in chans.split(",") if c.strip()]
    ks = [k.strip() for k in keys.split(",")] if keys.strip() else []
    return [(n, ks[i] if i < len(ks) else "") for i, n in enumerate(names)]


def build_autojoin(pairs: list[tuple[str, str]]) -> str:
    """Back to XChat's text: channels with a key first, so the keys line up with them."""
    keyed = [(c, k) for c, k in pairs if k]
    plain = [(c, k) for c, k in pairs if not k]
    chans = ",".join(c for c, _ in keyed + plain)
    return chans + (" " + ",".join(k for _, k in keyed) if keyed else "")


def entries(cfg) -> list[Fav]:
    out: list[Fav] = []
    for n in cfg.networks:
        for chan, key in parse_autojoin(n.autojoin):
            out.append(Fav(n.name, chan, key, True, cfg.fav_notes.get(f"{n.name}/{lower(chan)}", "")))
    have = {lower(f.id) for f in out}
    for line in cfg.fav_saved:
        ident, _, key = line.partition(" ")
        net, sep, chan = ident.rpartition("/")
        if sep and lower(ident) not in have:
            out.append(Fav(net, chan, key, False, cfg.fav_notes.get(f"{net}/{lower(chan)}", "")))
            have.add(lower(ident))
    return out


def save(cfg, favs: list[Fav]) -> None:
    """Join-on-connect ones into each network's auto-join (order kept), the rest into fav_saved."""
    for n in cfg.networks:
        n.autojoin = build_autojoin([(f.channel, f.key) for f in favs if f.join and f.network == n.name])
    cfg.fav_saved = [f"{f.id} {f.key}".strip() for f in favs if not f.join or f.network not in {n.name for n in cfg.networks}]
    cfg.fav_notes = {f"{f.network}/{lower(f.channel)}": f.note for f in favs if f.note}


def find(favs: list[Fav], network: str, channel: str) -> Fav | None:
    return next((f for f in favs if f.network == network and lower(f.channel) == lower(channel)), None)


def set_join(cfg, network: str, channel: str, key: str, on: bool) -> None:
    """The tab menu's Join on Connect."""
    favs = entries(cfg)
    f = find(favs, network, channel)
    if f is None:
        favs.append(Fav(network, channel, key, on))
    else:
        f.join = on
        if key and not f.key:
            f.key = key
    save(cfg, favs)


class FavEditDialog(FramedDialog):
    def __init__(self, parent, networks: list[str], fav: Fav | None = None):
        super().__init__("Edit Favourite" if fav else "Add Favourite", parent)
        self.setFixedWidth(400)
        g = QGridLayout()
        g.setVerticalSpacing(8)
        self.channel = QLineEdit(fav.channel if fav else "#")
        self.net = QComboBox()
        self.net.addItems(networks)
        if fav and fav.network in networks:
            self.net.setCurrentText(fav.network)
        self.key = QLineEdit(fav.key if fav else "")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("None")
        self.note = QLineEdit(fav.note if fav else "")
        for r, (label, w) in enumerate((("Channel:", self.channel), ("Network:", self.net), ("Key:", self.key), ("Note:", self.note))):
            g.addWidget(QLabel(label), r, 0)
            g.addWidget(w, r, 1)
        g.setColumnStretch(1, 1)
        self.body.addLayout(g)
        self.join = QCheckBox("Join when I connect")
        self.join.setChecked(fav.join if fav else True)
        self.body.addWidget(self.join)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(icon("cancel"), "&Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(icon("done"), "&OK")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        self.body.addLayout(row)
        self.channel.textChanged.connect(lambda t: self.ok.setEnabled(len(t.strip()) > 1 and bool(self.net.currentText())))
        self.ok.setEnabled(len(self.channel.text().strip()) > 1 and bool(self.net.currentText()))

    def result_fav(self) -> Fav:
        chan = self.channel.text().strip().split()[0]
        if chan[0] not in "#&!+":
            chan = "#" + chan
        return Fav(self.net.currentText(), chan, self.key.text().strip(), self.join.isChecked(), self.note.text().strip())


class FavouritesDialog(FramedDialog):
    """Server > Favourite Channels. Changes are saved as they are made."""

    def __init__(self, win):
        super().__init__("BChat: Favourite Channels", win)
        self.win = win
        self.cfg = win.cfg
        self.resize(660, 380)
        self.list = QTreeWidget()
        self.list.setRootIsDecorated(False)
        self.list.setHeaderLabels(["Channel", "Network", "Key", "Join on connect", "Note"])
        for c, w in ((0, 120), (1, 150), (2, 70), (3, 120)):
            self.list.setColumnWidth(c, w)
        self.list.itemDoubleClicked.connect(lambda *_: self.join_selected())
        self.list.itemChanged.connect(self._ticked)
        self.list.currentItemChanged.connect(lambda *_: self._buttons())
        self.body.addWidget(self.list, 1)
        hint = QLabel("Double-click to join. Ticked channels join when you connect, with their key.")
        hint.setStyleSheet(f"color: {self.cfg.theme.muted};")
        self.body.addWidget(hint)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        row = QHBoxLayout()
        self.add_btn = QPushButton(icon("new"), "Add...")
        self.add_btn.clicked.connect(lambda: self.edit(new=True))
        self.edit_btn = QPushButton(icon("edit"), "Edit...")
        self.edit_btn.clicked.connect(lambda: self.edit())
        self.remove_btn = QPushButton(icon("close-light"), "Remove")
        self.remove_btn.clicked.connect(self.remove)
        for b in (self.add_btn, self.edit_btn, self.remove_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.join_btn = QPushButton(icon("connect"), "&Join")
        self.join_btn.clicked.connect(self.join_selected)
        close = QPushButton(icon("close-light"), "Close")
        close.clicked.connect(self.reject)
        row.addWidget(self.join_btn)
        row.addWidget(close)
        self.body.addLayout(row)
        self.favs = entries(self.cfg)
        self.fill()

    def networks(self) -> list[str]:
        return [n.name for n in self.cfg.networks if n.servers]

    def fill(self, select: int = -1) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for f in self.favs:
            it = QTreeWidgetItem([f.channel, f.network, "••••••" if f.key else "", "", f.note])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(3, Qt.CheckState.Checked if f.join else Qt.CheckState.Unchecked)
            self.list.addTopLevelItem(it)
        self.list.blockSignals(False)
        if 0 <= select < len(self.favs):
            self.list.setCurrentItem(self.list.topLevelItem(select))
        self._buttons()

    def _index(self) -> int:
        it = self.list.currentItem()
        return self.list.indexOfTopLevelItem(it) if it is not None else -1

    def _buttons(self) -> None:
        on = self._index() >= 0
        for b in (self.edit_btn, self.remove_btn, self.join_btn):
            b.setEnabled(on)

    def _save(self) -> None:
        save(self.cfg, self.favs)
        self.win.save_config()

    def _ticked(self, it, col: int) -> None:
        if col != 3:
            return
        i = self.list.indexOfTopLevelItem(it)
        if 0 <= i < len(self.favs):
            self.favs[i].join = it.checkState(3) == Qt.CheckState.Checked
            self._save()

    def edit(self, new: bool = False) -> None:
        i = -1 if new else self._index()
        if not new and i < 0:
            return
        nets = self.networks()
        cur = getattr(self.win, "session", None)
        d = FavEditDialog(self, nets, None if new else self.favs[i])
        if new and cur is not None and cur.net.name in nets:
            d.net.setCurrentText(cur.net.name)
        self.edit_dialog = d

        def done(code: int) -> None:
            if not code:
                return
            f = d.result_fav()
            other = find(self.favs, f.network, f.channel)
            if new:
                if other is not None:
                    self.favs.remove(other)
                self.favs.append(f)
                at = len(self.favs) - 1
            else:
                if other is not None and other is not self.favs[i]:
                    self.favs.remove(other)
                    i2 = self.favs.index(self.favs[i]) if i < len(self.favs) else len(self.favs) - 1
                else:
                    i2 = i
                self.favs[i2] = f
                at = i2
            self._save()
            self.fill(at)
        d.finished.connect(done)
        d.open()

    def remove(self) -> None:
        i = self._index()
        if i >= 0:
            del self.favs[i]
            self._save()
            self.fill(min(i, len(self.favs) - 1))

    def join_selected(self) -> None:
        i = self._index()
        if i < 0:
            return
        self.win.join_favourite(self.favs[i])
