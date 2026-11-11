"""ChanServ Access (0.4.0): give someone auto-op or auto-voice in a channel without typing services commands.

Only @ and +: Auto-op, Auto-voice, or No access. BChat asks ChanServ which services run (Anope or Atheme, by its answer
to a CTCP VERSION), then quietly asks what the person has now. The window shows the exact line it will send; ChanServ's
answer to Apply shows in the channel tab like any notice."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton

from .protocol import lower, strip_format
from .session import INFO, Buffer, Session, User
from .widgets import FramedDialog, icon

OP, VOICE, NONE = "op", "voice", "none"
WORDS = {OP: "auto-op (@)", VOICE: "auto-voice (+)", NONE: "no access"}


def can_manage(s: Session, b: Buffer) -> bool:
    """Op or higher in this channel: ChanServ would refuse anyone less."""
    rank = s.own_rank(b)
    order = s.prefix_order
    return bool(rank) and "@" in order and order.index(rank) <= order.index("@")


def knows_accounts(s: Session) -> bool:
    """The server tells us who is logged in (so an empty account really means 'not logged in')."""
    return bool(s._cap_active & {"account-notify", "extended-join", "account-tag"}) or s.whox


def commands(services: str, chan: str, account: str, choice: str, now: str) -> list[str]:
    """What goes to ChanServ. Anope: AOP/VOP ADD and DEL (ADD moves someone between the lists). Atheme: FLAGS +O / +V."""
    if services == "atheme":
        flags = {OP: "+O-V", VOICE: "+V-O", NONE: "-*"}[choice]
        return [f"FLAGS {chan} {account} {flags}"]
    if choice == OP:
        return [f"AOP {chan} ADD {account}"]
    if choice == VOICE:
        return [f"VOP {chan} ADD {account}"]
    if now == OP:
        return [f"AOP {chan} DEL {account}"]
    if now == VOICE:
        return [f"VOP {chan} DEL {account}"]
    return [f"AOP {chan} DEL {account}", f"VOP {chan} DEL {account}"]     # not known: both, ChanServ says which had them


class AccessReader:
    """Reads ChanServ's answers to the quiet 'what do they have now' question. feed() returns True for lines it takes."""

    def __init__(self, services: str, chan: str, account: str):
        self.services = services
        self.chan = lower(chan)
        self.account = lower(account)
        self.asked = ["AOP", "VOP"] if services == "anope" else ["FLAGS"]
        self.found: dict[str, bool] = {}
        self.unknown = False
        self.in_list = ""

    def questions(self, chan: str, account: str) -> list[str]:
        if self.services == "atheme":
            return [f"FLAGS {chan} {account}"]
        return [f"AOP {chan} LIST {account}", f"VOP {chan} LIST {account}"]

    @property
    def done(self) -> bool:
        return self.unknown or len(self.found) >= len(self.asked)

    def now(self) -> str:
        if self.unknown or not self.done:
            return ""
        if self.found.get("AOP") or self.found.get("FLAGS_O"):
            return OP
        if self.found.get("VOP") or self.found.get("FLAGS_V"):
            return VOICE
        return NONE

    def _next(self) -> str:
        return next((q for q in self.asked if q not in self.found), "")

    def feed(self, text: str) -> bool:
        t = strip_format(text).strip()
        low = t.lower()
        if self.done:
            return bool(self.in_list) and bool(re.match(r"^\s*(\d+|number)\b", low))     # the last list's rows
        if "access denied" in low or "permission denied" in low or "not registered" in low or "isn't registered" in low:
            self.unknown = True
            return True
        if self.services == "atheme":
            m = re.search(r"[Ff]lags for \S+ in \S+ are (\S+?)\.?$", t)
            if m:
                flags = m.group(1)
                self.found["FLAGS"] = True
                self.found["FLAGS_O"] = "O" in flags
                self.found["FLAGS_V"] = "V" in flags
                return True
            if "was not found on the access list" in low or "not on the access list" in low:
                self.found["FLAGS"] = True
                return True
            return False
        m = re.match(r"^(aop|vop) list for (\S+)", low)
        if m:
            self.found[m.group(1).upper()] = True       # LIST <account> only lists matching entries: a list = they're on it
            self.in_list = m.group(1).upper()
            return True
        if low.startswith("no matching entries on") or low.endswith("list is empty."):
            q = self._next()
            if q:
                self.found[q] = False
            self.in_list = ""
            return True
        if self.in_list and re.match(r"^\s*(\d+|number)\b", low):
            return True                                  # rows of a list we asked for
        return False


class ChanServAccess(FramedDialog):
    def __init__(self, win, b: Buffer, user: User):
        super().__init__("ChanServ Access", win)
        self.win, self.b, self.s = win, b, b.session
        t = win.cfg.theme
        self.muted = t.muted
        self.account = user.account or ("" if knows_accounts(self.s) else user.nick)
        self.nick = user.nick
        self.now = ""
        self.reader: AccessReader | None = None
        self._closed = False
        self.setFixedWidth(460)
        self.body.setContentsMargins(20, 16, 20, 14)
        self.body.setSpacing(8)
        head = QLabel(f"What should ChanServ give {user.nick} in {b.name}?")
        head.setWordWrap(True)
        head.setTextFormat(Qt.TextFormat.PlainText)
        head.setStyleSheet(f"color: {t.title}; font-size: 11pt; font-weight: bold;")
        self.body.addWidget(head)
        acct = (f"Account: {self.account}" + (" (registered)" if user.account else "") if self.account
                else f"{user.nick} isn't logged in to NickServ, so ChanServ can't give them access.")
        self.acct = self._muted(acct)
        self.acct.setWordWrap(True)
        self.body.addWidget(self.acct)
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for key, text, hint in ((OP, "Auto-op  @", "ops every time they join"), (VOICE, "Auto-voice  +", "voice every time they join"),
                                (NONE, "No access", "takes them off the list")):
            r = QRadioButton(text)
            self.group.addButton(r)
            self.radios[key] = r
            row = QHBoxLayout()
            row.addWidget(r)
            row.addWidget(self._muted(hint))
            row.addStretch(1)
            self.body.addLayout(row)
            r.toggled.connect(self._changed)
        self.now_label = self._muted("Now: asking ChanServ...")
        self.body.addWidget(self.now_label)
        self.sends = QLabel()
        self.sends.setTextFormat(Qt.TextFormat.RichText)
        self.sends.setWordWrap(True)
        self.body.addWidget(self.sends)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(icon("cancel"), "&Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.apply_btn = QPushButton(icon("done"), "&Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(self.apply_btn)
        self.body.addLayout(row)
        self.radios[VOICE].setChecked(True)
        if self.account:
            self.s.ask_services(self._ask_now)
        else:
            self.now_label.setText("Now: no access")
            for r in self.radios.values():
                r.setEnabled(False)
        self._changed()

    def _muted(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setTextFormat(Qt.TextFormat.PlainText)
        lb.setStyleSheet(f"color: {self.muted};")
        return lb

    # --- what they have now --------------------------------------------------------------

    def _ask_now(self) -> None:
        if self._closed:
            return
        self.reader = AccessReader(self.s.services, self.b.name, self.account)
        self.s.chanserv_sink = self._feed
        for q in self.reader.questions(self.b.name, self.account):
            self.s.send_raw(f"PRIVMSG ChanServ :{q}", quiet=True)
        QTimer.singleShot(5000, self._give_up)
        self._changed()

    def _feed(self, text: str) -> bool:
        r = self.reader
        if r is None:
            return False
        taken = r.feed(text)
        if r.done and self.now == "" and not r.unknown:
            self._known(r.now())
        elif r.unknown:
            self._known("")
        return taken

    def _known(self, now: str) -> None:
        self.now = now
        if now:
            self.now_label.setText(f"Now: {WORDS[now]}")
            self.radios[VOICE if now == NONE else now].setChecked(True)     # Apply wakes up when the choice differs
        else:
            self.now_label.setText("Now: ChanServ didn't say (you may not be allowed to see the list)")
        QTimer.singleShot(1500, self._stop_reading)      # list rows can trail the header a little
        self._changed()

    def _give_up(self) -> None:
        if self.reader is not None and not self.reader.done:
            self.reader.unknown = True
            self._known("")
        self._stop_reading()

    def _stop_reading(self) -> None:
        if self.s.chanserv_sink == self._feed:
            self.s.chanserv_sink = None

    # --- choice and Apply ---------------------------------------------------------------

    def choice(self) -> str:
        return next((k for k, r in self.radios.items() if r.isChecked()), VOICE)

    def lines(self) -> list[str]:
        return commands(self.s.services or "anope", self.b.name, self.account, self.choice(), self.now)

    def _changed(self, *_) -> None:
        ready = bool(self.account) and bool(self.s.services) and self.s.state == "connected"
        if not self.account:
            self.sends.setText("")
        elif not self.s.services:
            self.sends.setText(f"<span style='color:{self.muted}'>Finding out which services this network runs...</span>")
        else:
            cmds = "<br>".join(f"/msg ChanServ {_esc(c)}" for c in self.lines())
            self.sends.setText(f"<span style='color:{self.muted}'>Sends:</span> <span style='font-family: Consolas'>{cmds}</span>")
        self.apply_btn.setEnabled(ready and self.choice() != self.now)

    def apply(self) -> None:
        self._stop_reading()
        for c in self.lines():
            self.s.send_raw(f"PRIVMSG ChanServ :{c}")
            self.s.add(self.b, INFO, "*", f"\x0314BChat sent: /msg ChanServ {c}")
        self.accept()

    def done(self, r):
        self._closed = True
        self._stop_reading()
        super().done(r)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
