"""Auto-Op, Auto-Voice & Protect (0.5.0, mIRC's Control list). Mockup: mockups/mockup-0.5.0-control.png.

A rule: {"who", "by": "account" | "mask", "give": "@" | "+", "protect", "channels", "network"}.
- "account" = the person's NickServ account (extended-join, account-notify, WHOX): nobody can fake it.
  "mask" = *!*@host style; a nick-only mask is refused, anyone can take a nick.
- BChat only acts where it has @ itself, waits 2-4 s (random) and then skips the person if ChanServ or another op
  has already done it. Each action prints one grey line that says why.
- Protect gives @ / + back when someone else takes it and lifts a ban that matches them. It never kicks anyone,
  never fights services or a server, and stops after 3 give-backs per person per minute (op wars, bots).
"""
from __future__ import annotations

import fnmatch
import random
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem)

from .protocol import lower
from .tools import ToolWindow
from .widgets import FramedDialog, icon

DELAY = (2.0, 4.0)          # seconds, random in between (tests set (0, 0))
GUARD = 3                   # give-backs per person per channel per minute
GREY = "\x0314"
ALL = "All networks"
SERVICES = {"chanserv", "nickserv", "operserv", "botserv", "memoserv", "hostserv", "global"}
MODE = {"@": "o", "+": "v"}
WORD = {"@": "@", "+": "voice"}


def nick_only(mask: str) -> bool:
    """True for masks that only look at the nick (Wira, Wira!*@*, Wira!*): anyone can take a nick."""
    m = mask.strip()
    if "@" not in m:
        return True
    user_host = m.split("!", 1)[-1]
    host = user_host.split("@", 1)[1] if "@" in user_host else ""
    return host.strip("*?") == ""


def tidy_mask(mask: str) -> str:
    m = mask.strip()
    if "@" in m and "!" not in m:
        m = "*!" + m
    return m


def _in(rule: dict, network: str, chan: str) -> bool:
    net = rule.get("network", "")
    if net and lower(net) != lower(network):
        return False
    chans = [lower(c) for c in rule.get("channels", "").split()]
    return not chans or lower(chan) in chans


def matches(rule: dict, nick: str, userhost: str, account: str) -> bool:
    who = rule.get("who", "").strip()
    if not who:
        return False
    if rule.get("by") == "account":
        return bool(account) and lower(account) == lower(who)
    if nick_only(who) or not userhost:
        return False
    return fnmatch.fnmatchcase(lower(f"{nick}!{userhost}"), lower(tidy_mask(who)))


def rule_for(cfg, network: str, chan: str, nick: str, userhost: str, account: str) -> dict | None:
    """The first rule that fits, or None. Rules with a nick-only mask never fit."""
    for r in cfg.control_rules:
        if _in(r, network, chan) and matches(r, nick, userhost, account):
            return r
    return None


def _ban_hits(mask: str, nick: str, userhost: str) -> bool:
    return bool(userhost) and fnmatch.fnmatchcase(lower(f"{nick}!{userhost}"), lower(tidy_mask(mask)))


class Control:
    """One per session: watches joins, logins and mode changes, and acts after the short wait."""

    def __init__(self, s):
        self.s = s
        self.gave_back: dict[tuple[str, str], list[float]] = {}
        self.stopped: set[tuple[str, str]] = set()

    def _on(self) -> bool:
        return bool(self.s.cfg.control_on and self.s.cfg.control_rules)

    def _have_op(self, b) -> bool:
        return self.s.own_rank(b) == "@" or "@" in (b.users.get(b.session.fold(self.s.nick)).prefixes if b.users.get(b.session.fold(self.s.nick)) else "")

    def _later(self, fn) -> None:
        lo, hi = DELAY
        QTimer.singleShot(int(random.uniform(lo, hi) * 1000), fn)

    # --- auto-op / auto-voice ---------------------------------------------------------------

    def check(self, b, nick: str) -> None:
        """Someone joined or logged in: give what their rule says, after the wait."""
        if not self._on() or b.kind != "channel" or lower(nick) == lower(self.s.nick):
            return
        u = b.users.get(b.session.fold(nick))
        if u is None or not self._have_op(b):
            return
        r = rule_for(self.s.cfg, self.s.net.name, b.name, u.nick, u.host, u.account)
        if r is None:
            return
        self._later(lambda: self._give(b.name, u.nick, r, "auto"))

    def _give(self, chan: str, nick: str, r: dict, why: str) -> None:
        s = self.s
        b = s.buffers.get(s.fold(chan))
        if s.state != "connected" or b is None or not b.joined or not self._have_op(b):
            return
        u = b.users.get(b.session.fold(nick))
        give = r.get("give", "@")
        if u is None or give in u.prefixes or (give == "+" and "@" in u.prefixes):
            return                                      # gone, or ChanServ / another op already did it
        by = f"account {u.account}" if r.get("by") == "account" else r.get("who", "")
        if why == "auto":
            label = "Auto-op" if give == "@" else "Auto-voice"
            s.add(b, "info", "", f"{GREY}{label}: giving {WORD[give]} to {u.nick} ({by})")
        else:
            s.add(b, "info", "", f"{GREY}Protect: {u.nick} is protected, giving {WORD[give]} back")
        s.send("MODE", b.name, "+" + MODE[give], u.nick)

    # --- protect ----------------------------------------------------------------------------

    def _guard(self, b, nick: str) -> bool:
        """True when another give-back is still allowed; says once when it stops."""
        key = (lower(b.name), lower(nick))
        now = time.time()
        recent = [t for t in self.gave_back.get(key, []) if now - t < 60]
        if len(recent) >= GUARD:
            if key not in self.stopped:
                self.stopped.add(key)
                self.s.add(b, "info", "", f"{GREY}Protect: stopped for {nick} in {b.name}, it kept being taken away. "
                                          "It starts again in a minute.")
            self.gave_back[key] = recent
            return False
        self.stopped.discard(key)
        recent.append(now)
        self.gave_back[key] = recent
        return True

    def _from_someone(self, who: str) -> bool:
        """Changes by me, services or a server are left alone."""
        return bool(who) and "." not in who and lower(who) != lower(self.s.nick) and lower(who) not in SERVICES

    def mode_taken(self, b, who: str, pfx: str, nick: str) -> None:
        if not self._on() or pfx not in MODE or not self._from_someone(who) or not self._have_op(b):
            return
        u = b.users.get(b.session.fold(nick))
        if u is None:
            return
        r = rule_for(self.s.cfg, self.s.net.name, b.name, u.nick, u.host, u.account)
        if r is None or not r.get("protect") or r.get("give") != pfx or not self._guard(b, u.nick):
            return
        self._later(lambda: self._give(b.name, u.nick, r, "protect"))

    def banned(self, b, who: str, mask: str) -> None:
        if not self._on() or not mask or not self._from_someone(who) or not self._have_op(b):
            return
        for u in list(b.users.values()):
            r = rule_for(self.s.cfg, self.s.net.name, b.name, u.nick, u.host, u.account)
            if r and r.get("protect") and _ban_hits(mask, u.nick, u.host) and self._guard(b, u.nick):
                self._later(lambda nick=u.nick: self._unban(b.name, nick, mask))
                return

    def _unban(self, chan: str, nick: str, mask: str) -> None:
        s = self.s
        b = s.buffers.get(s.fold(chan))
        if s.state != "connected" or b is None or not b.joined or not self._have_op(b):
            return
        s.add(b, "info", "", f"{GREY}Protect: {nick} is protected, removing the ban {mask}")
        s.send("MODE", b.name, "-b", mask)


# --- the window and the add / edit dialog ---------------------------------------------------

def describe(r: dict) -> list[str]:
    who = f"{r.get('who', '')}  (account)" if r.get("by") == "account" else tidy_mask(r.get("who", ""))
    return [who, r.get("give", "@"), "Yes" if r.get("protect") else "", r.get("channels", "") or "all where I'm @",
            r.get("network", "") or ALL]


class RuleDialog(FramedDialog):
    def __init__(self, win, rule: dict | None = None, nick: str = "", account: str = "", host: str = "",
                 network: str = "", channel: str = ""):
        super().__init__("Auto-Op: edit" if rule else "Auto-Op: add a person", win)
        t = win.cfg.theme
        self.setFixedWidth(440)
        self.body.setContentsMargins(20, 16, 20, 14)
        self.body.setSpacing(7)
        r = dict(rule or {})

        def head(text):
            h = QLabel(text)
            h.setStyleSheet(f"color: {t.title}; font-size: 11pt; font-weight: bold;")
            return h

        def hint(text):
            h = QLabel(text)
            h.setStyleSheet(f"color: {t.muted};")
            h.setWordWrap(True)
            return h

        self.body.addWidget(head("Who"))
        self.by = QButtonGroup(self)
        self.by_account = QRadioButton("Their NickServ account:")
        self.by_mask = QRadioButton("Their address:")
        self.by.addButton(self.by_account)
        self.by.addButton(self.by_mask)
        self.account = QLineEdit((r.get("who", "") if r.get("by") == "account" else "") if rule else account)
        self.mask = QLineEdit(r.get("who", "") if r.get("by") == "mask" else (f"*!*@{host.split('@')[-1]}" if host else ""))
        for radio, box in ((self.by_account, self.account), (self.by_mask, self.mask)):
            row = QHBoxLayout()
            row.addWidget(radio)
            box.setFixedWidth(170)
            row.addWidget(box)
            row.addStretch(1)
            self.body.addLayout(row)
            if radio is self.by_account:
                self.body.addWidget(hint("Safest: nobody can fake it. Needs them logged in to NickServ."))
        self.body.addWidget(hint("Nick-only masks (Wira!*@*) aren't allowed: anyone can take a nick."))
        by_mask = r.get("by") == "mask" if rule else (not account and bool(host))   # account unknown: start from the address
        (self.by_mask if by_mask else self.by_account).setChecked(True)
        self.body.addSpacing(4)
        self.body.addWidget(head("Give"))
        self.gives = QButtonGroup(self)
        self.give_op = QRadioButton("Auto-op  @")
        self.give_voice = QRadioButton("Auto-voice  +")
        row = QHBoxLayout()
        for x in (self.give_op, self.give_voice):
            self.gives.addButton(x)
            row.addWidget(x)
        row.addStretch(1)
        self.body.addLayout(row)
        (self.give_voice if r.get("give") == "+" else self.give_op).setChecked(True)
        self.protect = QCheckBox("Protect: if someone takes their @ / + or bans them, give it back")
        self.protect.setChecked(bool(r.get("protect", False)))
        self.body.addWidget(self.protect)
        self.body.addSpacing(4)
        f = QFormLayout()
        f.setHorizontalSpacing(10)
        self.channels = QLineEdit(r.get("channels", channel))
        f.addRow("Channels:", self.channels)
        self.network = QComboBox()
        self.network.addItems([n.name for n in win.cfg.networks] + [ALL])
        net = r.get("network", network) if rule else network
        self.network.setCurrentText(net or ALL)
        f.addRow("Network:", self.network)
        self.body.addLayout(f)
        self.body.addWidget(hint("Empty channels = every channel where you have @."))
        self.problem = QLabel("")
        self.problem.setStyleSheet(f"color: {t.status_off};")
        self.problem.setWordWrap(True)
        self.body.addWidget(self.problem)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(sep)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton(icon("cancel"), "&Cancel")
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton(icon("done"), "&OK" if rule else "&Add")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._ok)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        self.body.addLayout(row)
        for w in (self.account, self.mask):
            w.textChanged.connect(self._check)
        self.by_account.toggled.connect(self._check)
        self._check()

    def _check(self) -> str:
        acct = self.by_account.isChecked()
        self.account.setEnabled(acct)
        self.mask.setEnabled(not acct)
        text = (self.account if acct else self.mask).text().strip()
        problem = ""
        if not text:
            problem = " "
        elif acct and any(c in text for c in "!@*? "):
            problem = "An account is just a name, like Wira."
        elif not acct and nick_only(text):
            problem = "That mask only looks at the nick. Use the address, like *!*@bsn.my."
        self.problem.setText(problem.strip())
        self.problem.setVisible(bool(problem.strip()))
        self.ok_btn.setEnabled(not problem)
        return problem

    def _ok(self) -> None:
        if not self._check():
            self.accept()

    def rule(self) -> dict:
        acct = self.by_account.isChecked()
        net = self.network.currentText()
        return {"who": (self.account if acct else self.mask).text().strip() if acct else tidy_mask(self.mask.text()),
                "by": "account" if acct else "mask", "give": "+" if self.give_voice.isChecked() else "@",
                "protect": self.protect.isChecked(), "channels": " ".join(self.channels.text().split()),
                "network": "" if net == ALL else net}


class ControlWindow(ToolWindow):
    def __init__(self, win):
        super().__init__("BChat: Auto-Op, Auto-Voice & Protect", win, (640, 340))
        t = win.cfg.theme
        self.on = QCheckBox("Use this list (BChat only acts in channels where you have @)")
        self.on.setChecked(win.cfg.control_on)
        self.on.toggled.connect(self._toggle)
        self.body.addWidget(self.on)
        self.view = QTreeWidget()
        self.view.setRootIsDecorated(False)
        self.view.setHeaderLabels(["Who", "Gives", "Protect", "Channels", "Network"])
        for c, w in ((0, 170), (1, 50), (2, 60), (3, 150)):
            self.view.setColumnWidth(c, w)
        self.view.itemDoubleClicked.connect(lambda *_: self.edit())
        self.view.currentItemChanged.connect(lambda *_: self._buttons())
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        tip = QLabel("Channels with ChanServ: <b>ChanServ Access</b> is better, it works while you're offline.")
        tip.setStyleSheet(f"color: {t.muted};")
        tip.setWordWrap(True)
        row.addWidget(tip, 1)
        self.add_btn = QPushButton(icon("new"), "Add...", objectName="compact")
        self.add_btn.clicked.connect(lambda: self.add())
        self.edit_btn = QPushButton(icon("edit"), "Edit...", objectName="compact")
        self.edit_btn.clicked.connect(lambda: self.edit())
        self.remove_btn = QPushButton(icon("close-light"), "Remove", objectName="compact")
        self.remove_btn.clicked.connect(self.remove)
        for b in (self.add_btn, self.edit_btn, self.remove_btn):
            row.addWidget(b)
        self.body.addLayout(row)
        self.dialog: RuleDialog | None = None
        self.fill()

    def _toggle(self, on: bool) -> None:
        self.win.cfg.control_on = on
        self.win.save_config()

    def fill(self, keep: int | None = None) -> None:
        self.view.clear()
        for r in self.win.cfg.control_rules:
            self.view.addTopLevelItem(QTreeWidgetItem(describe(r)))
        if keep is not None and 0 <= keep < self.view.topLevelItemCount():
            self.view.setCurrentItem(self.view.topLevelItem(keep))
        self._buttons()

    def _row(self) -> int:
        it = self.view.currentItem()
        return self.view.indexOfTopLevelItem(it) if it is not None else -1

    def _buttons(self) -> None:
        has = self._row() >= 0
        self.edit_btn.setEnabled(has)
        self.remove_btn.setEnabled(has)

    def add(self, **kw) -> RuleDialog:
        d = self.dialog = RuleDialog(self.win, None, **kw)

        def done(code):
            if code:
                self.win.cfg.control_rules.append(d.rule())
                self.win.save_config()
                self.fill(len(self.win.cfg.control_rules) - 1)
        d.finished.connect(done)
        d.open()
        return d

    def edit(self) -> RuleDialog | None:
        i = self._row()
        if i < 0:
            return None
        d = self.dialog = RuleDialog(self.win, self.win.cfg.control_rules[i])

        def done(code):
            if code:
                self.win.cfg.control_rules[i] = d.rule()
                self.win.save_config()
                self.fill(i)
        d.finished.connect(done)
        d.open()
        return d

    def remove(self) -> None:
        i = self._row()
        if i >= 0:
            del self.win.cfg.control_rules[i]
            self.win.save_config()
            self.fill(min(i, len(self.win.cfg.control_rules) - 1))
