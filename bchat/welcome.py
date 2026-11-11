"""First start: pick a nickname and a network, and you're talking. Shown once, only when there are no networks yet
(people who come from XChat get their own networks imported instead and never see it)."""
from __future__ import annotations

import random
import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QVBoxLayout)

from .config import NetworkConfig, Server, random_nick
from .session import INFO
from .widgets import FramedDialog, icon
from . import lucide

ASSETS = Path(__file__).resolve().parent / "assets"
NICK_RX = re.compile(r"^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}-]{0,29}$")

# (network name, host, port, channels to join, short address line, what it is)
CHOICES = [
    ("BajuBesi Community", "irc.bajubesi.org", 6697, "#BChat,#chat", "irc.bajubesi.org · joins #BChat and #chat",
     "BChat's home network: friendly help and chat with other BChat users."),
    ("Libera.Chat", "irc.libera.chat", 6697, "", "irc.libera.chat · pick channels after",
     "The big home of open-source and tech communities."),
    ("Wixchat", "chat.bajubesi.org", 9999, "", "chat.bajubesi.org · pick channels after",
     "Malaysia's largest chat community. Come say hi at #kampung."),
]


def nick_problem(nick: str) -> str:
    """Why this can't be a nickname, or "" when it's fine."""
    if not nick:
        return "Type a nickname."
    if " " in nick:
        return "Nicknames can't have spaces."
    if nick[0].isdigit() or nick[0] == "-":
        return "Nicknames start with a letter."
    if len(nick) > 30:
        return "That's a bit long: 30 characters at most."
    if not NICK_RX.match(nick):
        return "Use letters, numbers and _ - [ ] { } | ^ only."
    return ""


def _pic(name: str, colour: str, size: int, dpr: float) -> QLabel:
    pm = QPixmap.fromImage(lucide.image(name, colour, round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    lab = QLabel()
    lab.setPixmap(pm)
    lab.setFixedSize(size, size)
    return lab


class Card(QFrame):
    """One network to start on: radio, name, address, one line about it. Click anywhere to pick it."""

    def __init__(self, t, choice, recommended: bool, group: QButtonGroup, on_pick):
        super().__init__()
        self.t = t
        self.choice = choice
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        self.radio = QRadioButton()
        self.radio.setAccessibleName(choice[0])
        group.addButton(self.radio)
        self.radio.toggled.connect(lambda _on: on_pick())
        lay.addWidget(self.radio, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel(choice[0])
        f = QFont(name.font())
        f.setBold(True)
        name.setFont(f)
        row.addWidget(name)
        addr = QLabel(choice[4])
        addr.setStyleSheet(f"color: {t.muted}; font-size: 8pt;")
        row.addWidget(addr)
        row.addStretch(1)
        if recommended:
            tag = QLabel("Recommended")
            tag.setStyleSheet(f"color: {t.panel}; background: {t.check}; border-radius: 3px; padding: 0 6px; font-size: 8pt;")
            row.addWidget(tag)
        col.addLayout(row)
        about = QLabel(choice[5])
        about.setWordWrap(True)
        about.setStyleSheet(f"color: {t.muted};")
        col.addWidget(about)
        lay.addLayout(col, 1)

    def mousePressEvent(self, ev) -> None:
        self.radio.setChecked(True)
        super().mousePressEvent(ev)

    def paint_state(self) -> None:
        on = self.radio.isChecked()
        self.setStyleSheet(f"#card {{ border: 1px solid {self.t.check if on else self.t.border}; border-radius: 6px; "
                           f"background: {self.t.popup if on else self.t.panel}; }}")


class WelcomeDialog(FramedDialog):
    def __init__(self, win):
        super().__init__("Welcome to BChat", win)
        self.win = win
        t = self.t = win.cfg.theme
        self.result_choice = ""          # "connect" or "own"
        self.setFixedWidth(560)
        self.body.setContentsMargins(22, 18, 22, 16)
        self.body.setSpacing(14)
        dpr = self.devicePixelRatioF()

        top = QHBoxLayout()
        top.setSpacing(18)
        bee = QLabel()
        pm = QPixmap(str(ASSETS / "bee.png"))
        if not pm.isNull():
            pm = pm.scaledToWidth(round(92 * dpr), Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            bee.setPixmap(pm)
        self.bee = bee
        top.addWidget(bee, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(4)
        head = QLabel("Welcome to BChat")
        head.setStyleSheet(f"color: {t.title}; font-size: 15pt; font-weight: bold;")
        sub = QLabel("Pick a nickname and you're in. No account, no sign-up.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {t.muted};")
        words.addStretch(1)
        words.addWidget(head)
        words.addWidget(sub)
        nl = QHBoxLayout()
        nl.setSpacing(8)
        lab = QLabel("&Nickname")
        self.nick = QLineEdit(win.cfg.nick or random_nick())
        self.nick.setMaxLength(30)
        self.nick.setFixedWidth(180)
        lab.setBuddy(self.nick)
        nl.addWidget(lab)
        nl.addWidget(self.nick)
        nl.addStretch(1)
        words.addSpacing(8)
        words.addLayout(nl)
        self.hint = QLabel()
        words.addWidget(self.hint)
        words.addStretch(1)
        top.addLayout(words, 1)
        self.body.addLayout(top)

        where = QLabel("Where would you like to start?")
        fb = QFont(where.font())
        fb.setBold(True)
        where.setFont(fb)
        self.body.addWidget(where)
        self.group = QButtonGroup(self)
        self.cards = [Card(t, c, i == 0, self.group, self._repaint) for i, c in enumerate(CHOICES)]
        for c in self.cards:
            self.body.addWidget(c)

        safe = QHBoxLayout()
        safe.setSpacing(8)
        safe.addWidget(_pic("shield-check", t.join, 16, dpr), 0, Qt.AlignmentFlag.AlignTop)
        sl = QLabel("Encrypted connection. The network you pick can see your IP address, like any website.")
        sl.setWordWrap(True)
        sl.setStyleSheet(f"color: {t.muted}; font-size: 8pt;")
        safe.addWidget(sl, 1)
        self.body.addLayout(safe)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {t.border};")
        self.body.addWidget(line)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.own_btn = QPushButton(icon("justify"), "I'll &Set Up My Own...")
        self.own_btn.setAutoDefault(False)
        self.own_btn.clicked.connect(self._own)
        row.addWidget(self.own_btn)
        row.addStretch(1)
        self.connect_btn = QPushButton(icon("connect"), "&Connect")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self._connect)
        row.addWidget(self.connect_btn)
        self.body.addLayout(row)

        self.cards[0].radio.setChecked(True)
        self.nick.textChanged.connect(self._check_nick)
        self._check_nick()
        self.nick.selectAll()
        self.nick.setFocus()

    # --- state ------------------------------------------------------------------------

    def _repaint(self) -> None:
        for c in self.cards:
            c.paint_state()

    def _check_nick(self) -> None:
        why = nick_problem(self.nick.text().strip())
        self.connect_btn.setEnabled(not why)
        if why:
            self.hint.setText(why)
            self.hint.setStyleSheet(f"color: {self.t.marker}; font-size: 8pt;")
        else:
            self.hint.setText("Change it any time with /nick.")
            self.hint.setStyleSheet(f"color: {self.t.muted}; font-size: 8pt;")

    def chosen(self):
        return next(c.choice for c in self.cards if c.radio.isChecked())

    # --- buttons ----------------------------------------------------------------------

    def _connect(self) -> None:
        if nick_problem(self.nick.text().strip()):
            return
        self.result_choice = "connect"
        self.accept()

    def _own(self) -> None:
        self.result_choice = "own"
        self.accept()


def network_for(cfg, choice) -> NetworkConfig:
    """The network for a welcome choice: an existing one with that name, or a new one added to the list."""
    name, host, port, chans = choice[:4]
    for n in cfg.networks:
        if n.name.lower() == name.lower():
            return n
    net = NetworkConfig(name, [Server(host, port, True)], autojoin=chans, autoconnect=True)
    cfg.networks.append(net)
    return net


def first_start_action(cfg, has_sessions: bool) -> str:
    """What opens at start: "welcome" (first start, nothing set up), "netlist" (XChat's way), or ""."""
    if not cfg.networks and not cfg.welcome_done:
        return "welcome"
    if not has_sessions and not cfg.skip_network_list:
        return "netlist"
    return ""


def run_welcome(win, on_done=None) -> WelcomeDialog:
    """Open the welcome window (non-blocking). Whatever the user does, it's not shown again."""
    d = WelcomeDialog(win)

    def finished(_code: int) -> None:
        cfg = win.cfg
        cfg.welcome_done = True
        if d.result_choice == "connect":
            nick, was = d.nick.text().strip(), cfg.nick
            cfg.nick = nick
            if not cfg.nick2 or cfg.nick2 == was + "_":      # still the first-start bee choices: follow the new nick
                cfg.nick2 = nick + "_"
            if not cfg.nick3 or cfg.nick3 == was + "__":
                cfg.nick3 = nick + "__"
            net = network_for(cfg, d.chosen())
            win.lists_changed()
            s = win.connect_network(net)
            first = [c for c in net.autojoin.split(",") if c.strip()]
            if first:
                s.focus_next = s.fold(first[0].strip())     # #BChat in front, even if the server joins #chat first
            else:
                _ask_channel_when_in(win, s)
        else:
            win.lists_changed()
            if d.result_choice == "own":
                QTimer.singleShot(0, win.open_network_list)
        if on_done:
            on_done(d.result_choice)

    d.finished.connect(finished)
    d.open()
    win.welcome = d
    return d


def _ask_channel_when_in(win, s) -> None:
    """Networks without a channel of their own: once logged in, ask which channel to join."""
    def changed() -> None:
        if s.state != "connected":
            return
        s.state_changed.disconnect(changed)
        s.add(s.server_buffer, INFO, "*", "You're in! Join a channel with /join #name, or browse them with Server > List of Channels.")
        d = QInputDialog(win)
        d.setWindowTitle("Join a Channel")
        d.setLabelText(f"You're connected to {s.net.name}. Which channel would you like to join?")
        d.setTextValue("#")
        d.textValueSelected.connect(lambda name: len(name.strip()) > 1 and s.send("JOIN", name.strip()))
        win.join_ask = d
        d.open()
    s.state_changed.connect(changed)
