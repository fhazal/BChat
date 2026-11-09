"""Nick colours and the Address Book (0.3.0, mIRC's Nick Colors + Address Book).

A colour is stored by its NAME (mauve, peach...), so it follows the theme like the automatic nick colours do.
Rules: nick, nick!user@host mask or *!*@host, for one network or all; the first match wins. After the rules, an
Address Book card's colour colours its nick and other nicks. No match: the automatic colour (when that is on).
The Address Book is only on this PC; its 'Tell me when they come online' tick IS the Friends List."""
from __future__ import annotations

import fnmatch
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QWidget)

from .protocol import lower
from .tools import ToolWindow, button
from .widgets import FramedDialog, icon

COLOURS = ("rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach", "yellow", "green", "teal", "sky",
           "sapphire", "blue", "lavender")
ALL = "All networks"


def shade(cfg, name: str) -> str:
    from .config import MOCHA, PALETTES
    shades = PALETTES.get(cfg.theme.name, MOCHA)
    return shades.get(name) or MOCHA.get(name) or cfg.theme.nick


def swatch(cfg, name: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(shade(cfg, name)))
    return QIcon(pm)


def _matches(mask: str, nick: str, userhost: str) -> bool:
    mask = lower(mask.strip())
    if not mask:
        return False
    if "!" in mask or "@" in mask:
        if not userhost:
            return False
        if "!" not in mask:
            mask = "*!" + mask
        return fnmatch.fnmatchcase(lower(f"{nick}!{userhost}"), mask)
    return fnmatch.fnmatchcase(lower(nick), mask)


def card_for(cfg, nick: str) -> dict | None:
    n = lower(nick)
    for card in cfg.address_book:
        names = [card.get("nick", "")] + [x.strip() for x in card.get("other", "").split(",")]
        if n in {lower(x) for x in names if x}:
            return card
    return None


def colour_name(cfg, network: str, nick: str, userhost: str = "") -> str | None:
    """The rule's (or card's) colour name for this person, or None."""
    for r in cfg.nick_colours:
        net = r.get("net", "")
        if net and lower(net) != lower(network or ""):
            continue
        if _matches(r.get("mask", ""), nick, userhost):
            return r.get("colour") or None
    card = card_for(cfg, nick)
    if card is not None and card.get("colour"):
        return card["colour"]
    return None


def colour_for(cfg, network: str, nick: str, userhost: str = "") -> str | None:
    name = colour_name(cfg, network, nick, userhost)
    return shade(cfg, name) if name else None


def set_rule(cfg, mask: str, colour: str, net: str = "") -> None:
    """Nick Colour... from the nick menu: changes this mask's rule, or adds one at the top (so it wins)."""
    for r in cfg.nick_colours:
        if lower(r.get("mask", "")) == lower(mask) and lower(r.get("net", "")) == lower(net):
            r["colour"] = colour
            return
    cfg.nick_colours.insert(0, {"mask": mask, "colour": colour, "net": net})


# --- windows ------------------------------------------------------------------------------

def colour_box(cfg, current: str = "") -> QComboBox:
    box = QComboBox()
    for name in COLOURS:
        box.addItem(swatch(cfg, name), name.capitalize(), name)
    if current in COLOURS:
        box.setCurrentIndex(COLOURS.index(current))
    return box


class RuleDialog(FramedDialog):
    def __init__(self, win, rule: dict | None = None):
        super().__init__("BChat: Nick Colour", win)
        rule = rule or {}
        g = QGridLayout()
        g.addWidget(QLabel("Nick or mask:"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self.mask = QLineEdit(rule.get("mask", ""))
        self.mask.setPlaceholderText("Belon  or  *!*@staff.bajubesi.org")
        g.addWidget(self.mask, 0, 1)
        g.addWidget(QLabel("Network:"), 1, 0, Qt.AlignmentFlag.AlignRight)
        self.net = QComboBox()
        self.net.addItem(ALL, "")
        for n in win.cfg.networks:
            self.net.addItem(n.name, n.name)
        want = rule.get("net", "")
        if want and self.net.findData(want) < 0:
            self.net.addItem(want, want)
        self.net.setCurrentIndex(max(0, self.net.findData(want)))
        g.addWidget(self.net, 1, 1, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(QLabel("Colour:"), 2, 0, Qt.AlignmentFlag.AlignRight)
        self.colour = colour_box(win.cfg, rule.get("colour", "mauve"))
        g.addWidget(self.colour, 2, 1, Qt.AlignmentFlag.AlignLeft)
        self.body.addLayout(g)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(icon("close-light"), "&Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(icon("save"), "&OK")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        self.body.addLayout(row)
        self.mask.textChanged.connect(lambda t: self.ok.setEnabled(bool(t.strip())))
        self.ok.setEnabled(bool(self.mask.text().strip()))
        self.resize(420, 0)

    def rule(self) -> dict:
        return {"mask": self.mask.text().strip(), "colour": self.colour.currentData(), "net": self.net.currentData() or ""}


class NickColoursWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Nick Colours", win, (540, 360))
        self.auto = QCheckBox("Colour other nicks automatically")
        self.auto.setChecked(win.cfg.color_nicks)
        self.auto.toggled.connect(self._auto)
        self.body.addWidget(self.auto)
        self.view = QTreeWidget()
        self.view.setHeaderLabels(["Colour", "Nick or mask", "Network"])
        self.view.setRootIsDecorated(False)
        self.view.setColumnWidth(0, 90)
        self.view.setColumnWidth(1, 230)
        self.view.itemDoubleClicked.connect(lambda *_: self.edit())
        self.view.currentItemChanged.connect(lambda *_: self._buttons())
        self.body.addWidget(self.view, 1)
        hint = QLabel("First rule that matches wins. A mask like *!*@host colours everyone on that host.")
        hint.setStyleSheet(f"color: {win.cfg.theme.muted};")
        self.body.addWidget(hint)
        row = QHBoxLayout()
        self.add_btn = button("Add...", self.add)
        self.add_btn.setIcon(icon("add"))
        self.edit_btn = button("Edit...", self.edit)
        self.edit_btn.setIcon(icon("edit"))
        self.remove_btn = button("Remove", self.remove)
        self.remove_btn.setIcon(icon("remove"))
        self.up_btn = QPushButton(icon("up"), "")
        self.down_btn = QPushButton(icon("down"), "")
        self.up_btn.setToolTip("Move up (checked first)")
        self.down_btn.setToolTip("Move down")
        for b, d in ((self.up_btn, -1), (self.down_btn, 1)):
            b.setObjectName("compact")
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, d=d: self.move(d))
        for b in (self.add_btn, self.edit_btn, self.remove_btn, self.up_btn, self.down_btn):
            row.addWidget(b)
        row.addStretch(1)
        close = button("&Close", self.close)
        close.setIcon(icon("close-light"))
        row.addWidget(close)
        self.body.addLayout(row)
        self.dialog: RuleDialog | None = None
        self.fill()

    def fill(self, keep: int | None = None) -> None:
        cfg = self.win.cfg
        self.view.clear()
        for r in cfg.nick_colours:
            it = QTreeWidgetItem([r.get("colour", "").capitalize(), r.get("mask", ""), r.get("net", "") or ALL])
            it.setIcon(0, swatch(cfg, r.get("colour", "")))
            self.view.addTopLevelItem(it)
        if keep is not None and 0 <= keep < self.view.topLevelItemCount():
            self.view.setCurrentItem(self.view.topLevelItem(keep))
        self._buttons()

    def _row(self) -> int:
        it = self.view.currentItem()
        return self.view.indexOfTopLevelItem(it) if it is not None else -1

    def _buttons(self) -> None:
        i, n = self._row(), self.view.topLevelItemCount()
        self.edit_btn.setEnabled(i >= 0)
        self.remove_btn.setEnabled(i >= 0)
        self.up_btn.setEnabled(i > 0)
        self.down_btn.setEnabled(0 <= i < n - 1)

    def _auto(self, on: bool) -> None:
        self.win.cfg.color_nicks = on
        self.win.nick_colours_changed()

    def _open(self, rule: dict | None, done) -> RuleDialog:
        d = self.dialog = RuleDialog(self.win, rule)
        d.finished.connect(lambda code: done(d.rule()) if code else None)
        d.open()
        return d

    def add(self) -> RuleDialog:
        def done(r):
            self.win.cfg.nick_colours.append(r)
            self.win.nick_colours_changed()
            self.fill(len(self.win.cfg.nick_colours) - 1)
        return self._open(None, done)

    def edit(self) -> RuleDialog | None:
        i = self._row()
        if i < 0:
            return None

        def done(r):
            self.win.cfg.nick_colours[i] = r
            self.win.nick_colours_changed()
            self.fill(i)
        return self._open(dict(self.win.cfg.nick_colours[i]), done)

    def remove(self) -> None:
        i = self._row()
        if i >= 0:
            del self.win.cfg.nick_colours[i]
            self.win.nick_colours_changed()
            self.fill(min(i, len(self.win.cfg.nick_colours) - 1))

    def move(self, d: int) -> None:
        i, rules = self._row(), self.win.cfg.nick_colours
        j = i + d
        if 0 <= i < len(rules) and 0 <= j < len(rules):
            rules[i], rules[j] = rules[j], rules[i]
            self.win.nick_colours_changed()
            self.fill(j)


class AddressBookWindow(ToolWindow):
    FIELDS = (("nick", "Nick:"), ("other", "Other nicks:"), ("real", "Real name:"), ("email", "Email:"), ("web", "Website:"))

    def __init__(self, win):
        super().__init__("BChat: Address Book", win, (660, 420))
        split = QHBoxLayout()
        self.people = QTreeWidget()
        self.people.setHeaderHidden(True)
        self.people.setRootIsDecorated(False)
        self.people.setFixedWidth(180)
        self.people.currentItemChanged.connect(lambda *_: self._show())
        split.addWidget(self.people)
        self.form = QWidget()
        g = QGridLayout(self.form)
        self.edits: dict[str, QLineEdit] = {}
        for r, (key, label) in enumerate(self.FIELDS):
            g.addWidget(QLabel(label), r, 0, Qt.AlignmentFlag.AlignRight)
            e = QLineEdit()
            e.textEdited.connect(lambda _t, k=key: self._changed(k))
            g.addWidget(e, r, 1)
            self.edits[key] = e
        r = len(self.FIELDS)
        g.addWidget(QLabel("Colour:"), r, 0, Qt.AlignmentFlag.AlignRight)
        self.colour = QComboBox()
        self.colour.addItem("Automatic", "")
        for name in COLOURS:
            self.colour.addItem(swatch(win.cfg, name), name.capitalize(), name)
        self.colour.activated.connect(lambda _i: self._changed("colour"))
        g.addWidget(self.colour, r, 1, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(QLabel("Notes:"), r + 1, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(70)
        self.notes.textChanged.connect(lambda: self._changed("notes"))
        g.addWidget(self.notes, r + 1, 1)
        self.friend = QCheckBox("Tell me when they come online (Friends List)")
        self.friend.toggled.connect(self._friend)
        g.addWidget(self.friend, r + 2, 1)
        self.seen = QLabel()
        self.seen.setStyleSheet(f"color: {win.cfg.theme.muted};")
        g.addWidget(self.seen, r + 3, 1)
        g.setRowStretch(r + 4, 1)
        split.addWidget(self.form, 1)
        self.empty = QLabel("Nobody here yet. Right-click a nick > Address Book..., or Add...")
        self.empty.setStyleSheet(f"color: {win.cfg.theme.muted};")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        split.addWidget(self.empty, 1)
        self.body.addLayout(split, 1)
        row = QHBoxLayout()
        self.add_btn = button("Add...", self.ask_add)
        self.add_btn.setIcon(icon("add"))
        self.remove_btn = button("Remove", self.remove)
        self.remove_btn.setIcon(icon("remove"))
        row.addWidget(self.add_btn)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        close = button("&Close", self.close)
        close.setIcon(icon("close-light"))
        row.addWidget(close)
        self.body.addLayout(row)
        self._loading = False
        self.fill()

    # cards
    def _cards(self) -> list:
        return self.win.cfg.address_book

    def fill(self, pick: str | None = None) -> None:
        keep = pick or (self.people.currentItem().text(0) if self.people.currentItem() else None)
        self.people.blockSignals(True)
        self.people.clear()
        chosen = None
        for card in sorted(self._cards(), key=lambda c: lower(c.get("nick", ""))):
            it = QTreeWidgetItem([card.get("nick", "")])
            name = colour_name(self.win.cfg, "", card.get("nick", "")) or ""
            if name:
                it.setIcon(0, swatch(self.win.cfg, name))
            self.people.addTopLevelItem(it)
            if keep is not None and lower(card.get("nick", "")) == lower(keep):
                chosen = it
        self.people.blockSignals(False)
        if chosen is None and self.people.topLevelItemCount():
            chosen = self.people.topLevelItem(0)
        if chosen is not None:
            self.people.setCurrentItem(chosen)
        self._show()

    def card(self) -> dict | None:
        it = self.people.currentItem()
        return card_for(self.win.cfg, it.text(0)) if it is not None else None

    def _show(self) -> None:
        c = self.card()
        have = c is not None
        self.form.setVisible(have)
        self.empty.setVisible(not have)
        self.remove_btn.setEnabled(have)
        if not have:
            return
        self._loading = True
        for key, e in self.edits.items():
            e.setText(c.get(key, ""))
        i = self.colour.findData(c.get("colour", ""))
        self.colour.setCurrentIndex(max(0, i))
        self.notes.setPlainText(c.get("notes", ""))
        self.friend.setChecked(lower(c.get("nick", "")) in {lower(n) for n in self.win.cfg.friends})
        self.seen.setText(self._seen(c))
        self._loading = False

    def _seen(self, c: dict) -> str:
        names = {lower(x.strip()) for x in [c.get("nick", "")] + c.get("other", "").split(",") if x.strip()}
        for s in self.win.sessions.values():
            for b in s.buffers.values():
                for u in b.users.values():
                    if lower(u.nick) in names:
                        return f"Online now: {s.net.name} · {u.nick}!{u.host}" if u.host else f"Online now: {s.net.name}"
        best = 0.0
        where = ""
        for s in self.win.sessions.values():
            st = s.friend_state.get(lower(c.get("nick", "")))
            if st and st.get("seen", 0) > best:
                best, where = st["seen"], s.net.name
        if best:
            mins = int((time.time() - best) // 60)
            return f"Last seen: {where}, {mins} minutes ago"
        return ""

    def _changed(self, key: str) -> None:
        if self._loading:
            return
        c = self.card()
        if c is None:
            return
        old_nick = c.get("nick", "")
        if key == "colour":
            c["colour"] = self.colour.currentData() or ""
            self.win.nick_colours_changed()
        elif key == "notes":
            c["notes"] = self.notes.toPlainText()
        else:
            c[key] = self.edits[key].text().strip()
        if key == "nick" and not c["nick"]:
            c["nick"] = old_nick                 # a card always has a nick
        self.win.save_config()
        if key in ("nick", "colour"):
            self.fill(c["nick"])

    def _friend(self, on: bool) -> None:
        if self._loading:
            return
        c = self.card()
        if c is None:
            return
        is_friend = lower(c["nick"]) in {lower(n) for n in self.win.cfg.friends}
        if on and not is_friend:
            self.win.add_friend(c["nick"])
        elif not on and is_friend:
            self.win.remove_friend(c["nick"])

    def open_card(self, nick: str, real: str = "") -> dict:
        """The nick menu's Address Book...: that person's card, made on first use."""
        c = card_for(self.win.cfg, nick)
        if c is None:
            c = {"nick": nick, "other": "", "real": real, "email": "", "web": "", "notes": "", "colour": ""}
            self._cards().append(c)
            self.win.save_config()
        self.fill(c["nick"])
        return c

    def ask_add(self) -> None:
        nick, ok = QInputDialog.getText(self, "Address Book", "Nick of the person to add:")
        nick = nick.strip().split()[0] if ok and nick.strip() else ""
        if nick:
            self.open_card(nick)

    def remove(self) -> None:
        c = self.card()
        if c is not None:
            self._cards().remove(c)
            self.win.save_config()
            self.win.nick_colours_changed()
            self.fill()
