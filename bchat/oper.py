"""Oper tools (0.9.3): an add-on that is built in. Mockup: mockups/mockup-oper-tools.png.

On while Settings > Add-ons > Oper tools is ticked (it is, by default) AND the server says you are an IRC operator on
the network of the tab you are looking at (numeric 381 or user mode +o; `Session.is_oper`). Then the menu bar has an
Oper menu and a nick's right-click menu has an Oper submenu; both hide again on -o, a lost link or a new one.
- Every oper action is a click by the user; there are no robots. Typed /commands work as they always did.
- Kill, Ban from server, Wallops and Global notice show "Sends: ..." with the exact line BChat sends.
- The ban command depends on the server software, found from the 004 version reply (see ircd_family):
    Solanum / charybdis family (also ratbox, hybrid):  KLINE [minutes] user@host :reason     DLINE [minutes] ip :reason
    InspIRCd:   GLINE user@host 1d :reason   ZLINE ip 1d :reason   SHUN user@host 1d :reason   KLINE user@host 1d :reason
    UnrealIRCd: the same, with the mask written +user@host and 1d / 0 for the time
    BeeIRCd:    GLINE / ZLINE / SHUN mask 1d :reason (0 = forever);  KLINE [+1d] user@host :reason
    anything else: KLINE, the charybdis way
"""
from __future__ import annotations

import fnmatch
import ipaddress
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QTreeWidget, QTreeWidgetItem)

from .session import INFO
from .tools import ToolWindow
from .widgets import FramedDialog, icon

# --- which server software it is ------------------------------------------------------------

CHARYBDIS_FAMILY = ("solanum", "charybdis", "ircd-seven", "ratbox", "hybrid", "plexus")


def ircd_family(version: str) -> str:
    """'charybdis' (Solanum, charybdis, ircd-seven, ratbox, hybrid), 'inspircd', 'unreal', 'beeircd' or 'unknown'."""
    v = (version or "").lower()
    if any(k in v for k in CHARYBDIS_FAMILY):
        return "charybdis"
    if "inspircd" in v:
        return "inspircd"
    if "unreal" in v:
        return "unreal"
    if "beeircd" in v:
        return "beeircd"
    return "unknown"


BAN_TYPES = {
    "charybdis": ("KLINE", "DLINE"),
    "inspircd": ("GLINE", "ZLINE", "SHUN", "KLINE"),
    "unreal": ("GLINE", "ZLINE", "SHUN", "KLINE"),
    "beeircd": ("GLINE", "ZLINE", "SHUN", "KLINE"),
    "unknown": ("KLINE",),
}
TYPE_LABEL = {
    "GLINE": "GLINE  (whole network)", "ZLINE": "ZLINE  (an IP, before it logs in)", "SHUN": "SHUN  (can connect, can't talk)",
    "KLINE": "KLINE  (this server)", "DLINE": "DLINE  (an IP, this server)",
}
IP_TYPES = ("DLINE", "ZLINE")           # these take an address, not user@host
FOR = (("1 hour", 60), ("1 day", 1440), ("7 days", 10080), ("30 days", 43200), ("Forever", 0))
SHORT = {60: "1h", 1440: "1d", 10080: "7d", 43200: "30d"}
DEFAULT_REASON = "Banned"
REMEMBER = 12                           # how many reasons are kept for next time


def family_of(s) -> str:
    return ircd_family(getattr(s, "ircd_version", ""))


def ban_types(family: str) -> tuple[str, ...]:
    return BAN_TYPES.get(family, BAN_TYPES["unknown"])


def _length(mins: int) -> str:
    return "0" if not mins else SHORT.get(mins, f"{mins}m")


def ban_line(family: str, kind: str, mask: str, mins: int, reason: str) -> str:
    """The exact line that adds a server ban. mins 0 = forever. mask: user@host, or an address for DLINE / ZLINE."""
    reason = " ".join((reason or "").split()) or DEFAULT_REASON
    mask = mask.strip()
    if family == "inspircd":
        parts = [kind, mask, _length(mins), ":" + reason]
    elif family == "unreal":
        parts = [kind, "+" + mask, _length(mins), ":" + reason]
    elif family == "beeircd":
        if kind == "KLINE":
            parts = [kind] + ([f"+{_length(mins)}"] if mins else []) + [mask, ":" + reason]
        else:
            parts = [kind, mask, _length(mins), ":" + reason]
    else:                                                    # charybdis family, and anything unknown
        parts = [kind] + ([str(mins)] if mins else []) + [mask, ":" + reason]
    return " ".join(parts)


def remove_line(family: str, kind: str, mask: str) -> str:
    """The exact line that lifts a server ban."""
    if family == "inspircd":
        return f"{'ZLINE' if kind == 'DLINE' else kind} {mask}"   # InspIRCd has no DLINE: an IP ban there is a ZLINE
    if family == "unreal":
        return f"{kind} -{mask}"
    if family == "beeircd":
        return f"UNKLINE {mask}" if kind == "KLINE" else f"{kind} -{mask}"
    return f"UN{kind} {mask}"                                # UNKLINE / UNDLINE


def list_lines(family: str) -> list[str]:
    """The STATS lines whose answers (216 / 223 / 225 / 280) are the server's ban lists."""
    return {
        "charybdis": ["STATS K", "STATS D"],
        "inspircd": ["STATS G", "STATS Z", "STATS K", "STATS H"],
        "unreal": ["STATS gline", "STATS shun"],
        "beeircd": ["STATS k"],
    }.get(family, ["STATS K"])


def kill_line(nick: str, reason: str) -> str:
    return f"KILL {nick} :{' '.join((reason or '').split()) or DEFAULT_REASON}"


def wallops_line(text: str) -> str:
    return f"WALLOPS :{text}"


def global_line(family: str, text: str) -> str:
    return f"NOTICE {'$$*' if family == 'charybdis' else '$*'} :{text}"


def opers_line(family: str) -> str:
    return {"charybdis": "STATS p", "inspircd": "STATS P"}.get(family, "WHO 0 o")


INFO_LINE = {"Uptime": "STATS u", "Links": "LINKS", "Who is on (count)": "LUSERS"}


# --- masks ---------------------------------------------------------------------------------

def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def mask_choices(userhost: str, kind: str) -> list[str]:
    """The masks offered for a person's address (user@host): exact address, the whole domain, user@address."""
    user, _, host = userhost.partition("@")
    if not host:
        return []
    if kind in IP_TYPES:
        return [host] if _is_ip(host) else []
    out = [f"*@{host}"]
    pieces = host.split(".")
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        out.append("*@" + ".".join(pieces[:3]) + ".*")
    elif ":" not in host and len(pieces) > 2:
        out.append("*@*." + ".".join(pieces[1:]))
    if user and user != "*":
        out.append(f"{user}@{host}")
    return list(dict.fromkeys(out))


def mask_ok(kind: str, mask: str) -> bool:
    if not mask or any(c.isspace() for c in mask):
        return False
    if kind in IP_TYPES:
        return bool(re.fullmatch(r"[0-9A-Fa-f:.*/]+", mask))
    return "@" in mask and not mask.startswith("@") and not mask.endswith("@")


def mask_matches(mask: str, userhost: str) -> bool:
    """Does user@host fall under this ban mask (user@host with wildcards, or an address / CIDR / wildcard address)?"""
    mask, uh = mask.strip().lower(), userhost.strip().lower()
    if "@" not in uh:
        return False
    if "@" in mask:
        return fnmatch.fnmatchcase(uh, mask)
    host = uh.partition("@")[2]
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network(mask, strict=False)
    except ValueError:
        return fnmatch.fnmatchcase(host, mask)


def matching(s, mask: str) -> list[str]:
    """The people we can see in our channels that this mask would catch (never us, never another IRC operator)."""
    me = s.fold(s.nick)
    out: dict[str, str] = {}
    for b in s.all_buffers():
        for u in b.users.values():
            if "@" in u.host and s.fold(u.nick) != me and not u.oper and mask_matches(mask, u.host):
                out[s.fold(u.nick)] = u.nick
    return list(out.values())


def clones_of(s, nick: str) -> tuple[str, list[str]]:
    """Find clones: (their address, the other nicks we can see on that same address)."""
    host = ""
    for b in s.all_buffers():
        u = b.users.get(s.fold(nick))
        if u is not None and "@" in u.host:
            host = u.host.partition("@")[2]
            break
    if not host:
        return "", []
    me, mine = s.fold(nick), {}
    for b in s.all_buffers():
        for u in b.users.values():
            if s.fold(u.nick) != me and u.host.partition("@")[2].lower() == host.lower():
                mine[s.fold(u.nick)] = u.nick
    return host, list(mine.values())


# --- small helpers -------------------------------------------------------------------------

def _muted(win, text: str) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(f"color: {win.cfg.theme.muted};")
    lb.setWordWrap(True)
    lb.setTextFormat(Qt.TextFormat.RichText)
    return lb


def _sends(win) -> QLabel:
    lb = QLabel()
    lb.setStyleSheet(f"color: {win.cfg.theme.muted}; font-family: Consolas; font-size: 9pt;")
    lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def _buttons(d, lay, label: str) -> QPushButton:
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton(icon("cancel"), "&Cancel")
    cancel.setAutoDefault(False)
    cancel.clicked.connect(d.reject)
    go = QPushButton(icon("done"), label)
    go.setDefault(True)
    go.clicked.connect(d.accept)
    row.addWidget(cancel)
    row.addWidget(go)
    lay.addLayout(row)
    return go


def _reason_box(win) -> QComboBox:
    rs = QComboBox()
    rs.setEditable(True)
    rs.addItems(list(win.cfg.oper_reasons) or ["Spam"])
    rs.setCurrentIndex(0)
    rs.setFixedWidth(300)
    return rs


def remember(win, reason: str, label: str | None = None) -> None:
    """Times and reasons are remembered for next time (Preferences file, never sent anywhere)."""
    reason = " ".join(reason.split())
    if label is not None:
        win.cfg.oper_for = label
    if reason:
        win.cfg.oper_reasons = ([reason] + [r for r in win.cfg.oper_reasons if r != reason])[:REMEMBER]
    win.save_config()


def _person(nick: str, userhost: str) -> str:
    return f"{nick}  ({nick}!{userhost})" if userhost else nick


# --- the dialogs ---------------------------------------------------------------------------

class _OperDialog(FramedDialog):
    """Kill and Ban from server look the same: who, the choices, 'Sends:' and Cancel / the action."""

    def __init__(self, title: str, win, s, width: int = 520):
        super().__init__(title, win)
        self.win, self.s = win, s
        self.setFixedWidth(width)
        self.body.setContentsMargins(20, 16, 20, 14)
        self.body.setSpacing(8)
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(8)
        self.sends = _sends(win)

    def command(self) -> str:
        raise NotImplementedError

    def lines(self) -> list[str]:
        return [self.command()]

    def refresh(self) -> None:
        line = self.command()
        self.sends.setText(line)
        self.go.setEnabled(bool(line))

    def send(self) -> None:
        for line in self.lines():
            self.s.send_raw(line)

    def accept(self) -> None:
        if not self.go.isEnabled():
            return
        if not self.win.oper_active(self.s):                  # QA 0.9.3: no longer an oper since the window opened
            self.sends.setText("You are no longer an IRC operator on this network, so nothing was sent.")
            self.go.setEnabled(False)
            return
        self.send()
        self.done_ok()
        super().accept()

    def done_ok(self) -> None:
        pass


class KillDialog(_OperDialog):
    """Oper > Kill... and a nick's Oper > Kill...: disconnect one person from the network."""

    def __init__(self, win, s, nick: str = "", userhost: str = ""):
        super().__init__(f"Kill: {nick}" if nick else "Kill", win, s)
        self.nick = nick
        self.who = QLineEdit()
        if nick:
            self.form.addRow("Nick:", QLabel(_person(nick, userhost)))
        else:
            self.who.setFixedWidth(220)
            self.who.textChanged.connect(lambda *_: self.refresh())
            self.form.addRow("Nick:", self.who)
        self.reason = _reason_box(win)
        self.reason.editTextChanged.connect(lambda *_: self.refresh())
        self.form.addRow("Reason:", self.reason)
        self.form.addRow("Sends:", self.sends)
        self.body.addLayout(self.form)
        self.go = _buttons(self, self.body, "&Kill")
        self.refresh()

    def target(self) -> str:
        return self.nick or self.who.text().strip()

    def command(self) -> str:
        who = self.target()
        return kill_line(who, self.reason.currentText()) if who and " " not in who else ""

    def done_ok(self) -> None:
        remember(self.win, self.reason.currentText())


class BanDialog(_OperDialog):
    """Oper > Ban from server... (no nick: type the mask) and a nick's Oper > Ban from server..."""

    def __init__(self, win, s, nick: str = "", userhost: str = ""):
        super().__init__(f"Ban from server: {nick}" if nick else "Ban from server", win, s)
        self.nick, self.userhost = nick, userhost
        self.family = family_of(s)
        types = ban_types(self.family)
        if nick:
            self.form.addRow("Nick:", QLabel(_person(nick, userhost)))
        self.kind = QComboBox()
        for k in types:
            self.kind.addItem(TYPE_LABEL[k], k)
        if len(types) > 1:                                  # one kind only (an unknown server): nothing to choose
            self.form.addRow("Type:", self.kind)
        self.mask_box = QComboBox()
        self.mask_box.setEditable(True)
        self.mask_box.setFixedWidth(220)
        self.form.addRow("Ban:", self.mask_box)
        self.why = _muted(win, "")
        self.why.setFixedWidth(390)                         # a set width: no stray room above the wrapped hint
        self.form.addRow("", self.why)
        self.length = QComboBox()
        self.length.addItems([name for name, _ in FOR])
        names = [name for name, _ in FOR]
        self.length.setCurrentIndex(names.index(win.cfg.oper_for) if win.cfg.oper_for in names else 1)
        self.length.setFixedWidth(120)
        self.form.addRow("For:", self.length)
        self.reason = _reason_box(win)
        self.form.addRow("Reason:", self.reason)
        self.form.addRow("Sends:", self.sends)
        self.body.addLayout(self.form)
        self.also = QCheckBox()
        self.also.setChecked(True)
        self.body.addWidget(self.also)
        self.go = _buttons(self, self.body, "&Ban")
        self._fill_masks()
        self.kind.currentIndexChanged.connect(lambda *_: self._fill_masks())
        for sig in (self.mask_box.editTextChanged, self.length.currentIndexChanged, self.reason.editTextChanged):
            sig.connect(lambda *_: self.refresh())

    def type(self) -> str:
        return self.kind.currentData() or ban_types(self.family)[0]

    def _fill_masks(self) -> None:
        self.mask_box.blockSignals(True)
        self.mask_box.clear()
        self.mask_box.addItems(mask_choices(self.userhost, self.type()))
        self.mask_box.setCurrentIndex(0 if self.mask_box.count() else -1)
        if not self.mask_box.count():
            self.mask_box.setEditText("")
        self.mask_box.blockSignals(False)
        host = self.userhost.partition("@")[2]
        no_ip = self.type() in IP_TYPES and bool(host) and not _is_ip(host)
        self.why.setText(f"{self.type()} needs an IP address; {host} is a host name. Type the IP, or pick another type."
                         if no_ip else "")
        self.why.setVisible(no_ip)
        self.refresh()

    def mins(self) -> int:
        return FOR[self.length.currentIndex()][1]

    def command(self) -> str:
        mask = self.mask_box.currentText().strip()
        if not mask_ok(self.type(), mask):
            return ""
        return ban_line(self.family, self.type(), mask, self.mins(), self.reason.currentText())

    def victims(self) -> list[str]:
        mask = self.mask_box.currentText().strip()
        return matching(self.s, mask) if mask_ok(self.type(), mask) else []

    def refresh(self) -> None:
        super().refresh()
        who = self.victims()
        self.also.setVisible(bool(who))                       # nobody to disconnect: nothing to tick
        n = len(who)
        self.also.setText(f"Also disconnect the {n} {'person who matches' if n == 1 else 'people who match'} now")
        self.also.setToolTip("Sends " + ", ".join(kill_line(w, self.reason.currentText()) for w in who) if who else "")

    def lines(self) -> list[str]:
        out = [self.command()]
        if self.also.isVisibleTo(self) and self.also.isChecked():
            out += [kill_line(w, self.reason.currentText()) for w in self.victims()]
        return out

    def done_ok(self) -> None:
        remember(self.win, self.reason.currentText(), self.length.currentText())


class MessageDialog(_OperDialog):
    """Oper > Wallops... and Oper > Global notice...: one line to every operator, or to everyone on the network."""

    def __init__(self, win, s, kind: str):
        super().__init__("Wallops" if kind == "wallops" else "Global notice", win, s, 560)
        self.kind, self.family = kind, family_of(s)
        self.text = QLineEdit()
        self.text.setMinimumWidth(380)
        self.text.textChanged.connect(lambda *_: self.refresh())
        self.form.addRow("To:", QLabel("every operator who listens to wallops" if kind == "wallops"
                                       else "everyone on the network"))
        self.form.addRow("Text:", self.text)
        self.form.addRow("Sends:", self.sends)
        self.body.addLayout(self.form)
        self.go = _buttons(self, self.body, "&Send")
        self.refresh()

    def command(self) -> str:
        t = " ".join(self.text.text().split())
        if not t:
            return ""
        return wallops_line(t) if self.kind == "wallops" else global_line(self.family, t)


# --- Server bans ----------------------------------------------------------------------------

LETTER = {"K": "KLINE", "k": "KLINE", "D": "DLINE", "d": "DLINE", "G": "GLINE", "g": "GLINE", "Z": "ZLINE", "z": "ZLINE",
          "H": "SHUN", "s": "SHUN"}


def parse_ban(n: int, params: list[str]) -> tuple[str, str, str] | None:
    """One STATS answer (216 / 223 / 225 / 280) as (type, mask, reason); None when it doesn't look like a ban."""
    if len(params) < 3 or not params[1][:1].isalpha():
        return None
    letter, rest = params[1], params[2:]
    kind = LETTER.get(letter, letter.upper())
    if len(rest) >= 4 and rest[1] == "*" and n == 216:       # charybdis: K host * user :reason
        mask, reason = f"{rest[2]}@{rest[0]}", rest[-1]
    elif len(rest) >= 3 and rest[1] == "*":                   # charybdis: D ip * :reason
        mask, reason = rest[0], rest[-1]
    else:
        mask, reason = rest[0], rest[-1] if len(rest) > 1 else ""
    return kind, mask, reason


class ServerBansWindow(ToolWindow):
    """Oper > Server bans...: the server's bans (STATS), add one, remove one. Best effort across server software."""

    def __init__(self, win, s):
        super().__init__(f"BChat: Server bans ({s.net.name})", win, (640, 360))
        self.s = s
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(8)
        self.view = QTreeWidget()
        self.view.setRootIsDecorated(False)
        self.view.setHeaderLabels(["Type", "Mask", "Reason"])
        for c, w in ((0, 70), (1, 230)):
            self.view.setColumnWidth(c, w)
        self.view.currentItemChanged.connect(lambda *_: self._buttons())
        self.body.addWidget(self.view, 1)
        self.note = _muted(win, "")
        self.body.addWidget(self.note)
        self.sends = _sends(win)
        self.body.addWidget(self.sends)
        row = QHBoxLayout()
        row.addStretch(1)
        self.add_btn = QPushButton(icon("new"), "Add...", objectName="compact")
        self.add_btn.clicked.connect(lambda: self.add())
        self.remove_btn = QPushButton(icon("close-light"), "Remove", objectName="compact")
        self.remove_btn.clicked.connect(self.remove)
        self.refresh_btn = QPushButton(icon("refresh"), "Refresh", objectName="compact")
        self.refresh_btn.clicked.connect(self.refresh)
        for b in (self.add_btn, self.remove_btn, self.refresh_btn):
            row.addWidget(b)
        self.body.addLayout(row)
        self._wait = 0
        self.dialog = None
        self._giveup = QTimer(self, singleShot=True, interval=15000, timeout=self._stop)     # no end-of-list: stop waiting
        self._soon = QTimer(self, singleShot=True, interval=1500, timeout=self._after_add)
        self.set_session(s)

    def set_session(self, s) -> None:
        self._stop()
        self.s = s
        self.family = family_of(s)
        self.titlebar.set_title(f"BChat: Server bans ({s.net.name})")
        self.setWindowTitle(f"BChat: Server bans ({s.net.name})")
        self.note.setText("GLINE, ZLINE and SHUN are kept by services on this server: type /GLINE (or /ZLINE, /SHUN) "
                          "with no mask to list them. The list here shows the KLINEs (STATS k)." if self.family == "beeircd" else "")
        self.note.setVisible(bool(self.note.text()))
        self.view.clear()
        self._buttons()
        self.refresh()

    def refresh(self) -> None:
        if self.s.state != "connected":
            return
        self.view.clear()
        lines = list_lines(self.family)
        self._wait = len(lines)
        self.s.oper_sink = self.feed
        for line in lines:
            self.s.send_raw(line)
        self._giveup.start()

    def feed(self, n: int, m) -> bool:
        if n == 219:
            self._wait -= 1
            if self._wait <= 0:
                self._stop()
            return True
        got = parse_ban(n, m.params)
        if got is None:
            return False
        self.view.addTopLevelItem(QTreeWidgetItem(list(got)))
        return True

    def _after_add(self) -> None:
        if self.isVisible():
            self.refresh()

    def _stop(self) -> None:
        self._giveup.stop()
        if self.s.oper_sink == self.feed:
            self.s.oper_sink = None
        self._wait = 0

    def hideEvent(self, e) -> None:
        self._stop()
        super().hideEvent(e)

    def _row(self):
        return self.view.currentItem()

    def _buttons(self) -> None:
        it = self._row()
        self.remove_btn.setEnabled(it is not None)
        self.sends.setText("Remove sends:  " + remove_line(self.family, it.text(0), it.text(1)) if it is not None else "")

    def add(self):
        d = self.dialog = BanDialog(self.win, self.s)
        d.finished.connect(lambda code: code and self._soon.start())     # the server needs a moment to list the new ban
        d.open()
        return d

    def remove(self) -> None:
        it = self._row()
        if it is None:
            return
        self.s.send_raw(remove_line(self.family, it.text(0), it.text(1)))
        self.remove_btn.setEnabled(False)
        self.sends.setText("Removing... the list reloads when the server answers.")
        self._soon.start()                                    # QA 0.9.3: the reload shows whether it really went


# --- Add-ons > Oper tools > Settings... ----------------------------------------------------------

class OperSettings(ToolWindow):
    """Settings > Add-ons > Oper tools > Settings...: the notices tab, the usual ban time, the remembered reasons."""

    def __init__(self, win):
        super().__init__("BChat: Oper tools", win, (460, 340))
        from .addons import oper_status
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(8)
        self.status = _muted(win, f"<i>Now: {oper_status(win)}</i>")
        self.body.addWidget(self.status)
        self.notices = QCheckBox("Show server notices in their own tab")
        self.notices.setChecked(win.cfg.oper_notices)
        self.notices.toggled.connect(win.set_oper_notices)
        self.body.addWidget(self.notices)
        row = QHBoxLayout()
        row.addWidget(QLabel("Usual ban time:"))
        self.length = QComboBox()
        self.length.addItems([name for name, _ in FOR])
        names = [name for name, _ in FOR]
        self.length.setCurrentIndex(names.index(win.cfg.oper_for) if win.cfg.oper_for in names else 1)
        self.length.currentTextChanged.connect(self._length)
        row.addWidget(self.length)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(QLabel("Remembered reasons:"))
        self.reasons = QListWidget()
        self.body.addWidget(self.reasons, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.remove_btn = QPushButton(icon("close-light"), "Remove", objectName="compact")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        self.body.addLayout(row)
        self.reasons.currentRowChanged.connect(lambda i: self.remove_btn.setEnabled(i >= 0))
        self.fill()

    def fill(self) -> None:
        from .addons import oper_status
        self.status.setText(f"<i>Now: {oper_status(self.win)}</i>")
        self.reasons.clear()
        self.reasons.addItems(list(self.win.cfg.oper_reasons))
        self.notices.blockSignals(True)
        self.notices.setChecked(self.win.cfg.oper_notices)
        self.notices.blockSignals(False)
        self.remove_btn.setEnabled(False)

    def _length(self, label: str) -> None:
        self.win.cfg.oper_for = label
        self.win.save_config()

    def remove(self) -> None:
        i = self.reasons.currentRow()
        if 0 <= i < len(self.win.cfg.oper_reasons):
            del self.win.cfg.oper_reasons[i]
            self.win.save_config()
            self.fill()


# --- what the menus do ---------------------------------------------------------------------------

def _open(win, d):
    win.oper_dialog = d
    d.open()
    return d


def open_kill(win, s, nick: str = "", userhost: str = ""):
    return _open(win, KillDialog(win, s, nick, userhost))


def open_ban(win, s, nick: str = "", userhost: str = ""):
    return _open(win, BanDialog(win, s, nick, userhost))


def open_message(win, s, kind: str):
    return _open(win, MessageDialog(win, s, kind))


def open_server_bans(win, s):
    w = win.tools.get("serverbans")
    if w is None:
        w = win.tools["serverbans"] = ServerBansWindow(win, s)
    else:
        w.set_session(s)
    w.show()
    w.raise_()
    return w


def server_info(win, s, what: str) -> str:
    """Server info > Uptime / Opers online / Links / Who is on (count): the answers print in the server tab."""
    line = opers_line(family_of(s)) if what == "Opers online" else INFO_LINE[what]
    s.send_raw(line)
    win.select_buffer(s.server_buffer)
    return line


def rehash(s) -> str:
    s.send_raw("REHASH")
    return "REHASH"


def stop_being_oper(s) -> str:
    line = f"MODE {s.nick} -o"
    s.send_raw(line)
    return line


def whois_all(s, nick: str) -> str:
    """Whois (all info): asks the person's own server, which adds idle time (and, to an oper, the real address)."""
    line = f"WHOIS {nick} {nick}"
    s.send_raw(line)
    return line


def find_clones(win, s, nick: str) -> str:
    """Find clones: who else we can see in our channels on the same address (a look at what BChat already knows)."""
    host, others = clones_of(s, nick)
    if not host:
        text = f"Find clones: {nick}'s address isn't known yet. Whois them first."
    elif others:
        text = f"Find clones: {len(others)} more on {host} with {nick}: {', '.join(others)}."
    else:
        text = f"Find clones: nobody else in your channels is on {host}."
    s.add(win.buf if win.buf is not None and win.buf.session is s else s.server_buffer, INFO, "", text)
    return text
