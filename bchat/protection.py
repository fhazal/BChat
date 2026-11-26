"""Channel Protection (0.9.3): an add-on that is built in. Mockups: mockups/mockup-channel-guard.png,
mockup-kick-reasons.png and mockup-addons.png.

Off until the user ticks it in Settings > Add-ons; then the Window menu has "Channel Protection..." with one rule per
channel (or one for every channel where you have @). A rule says what to catch and what to do the 1st, 2nd and 3rd
time (per person, remembered for 30 minutes).
- BChat only acts in channels where you have @ itself, waits 1-2 s (random) and then skips the person when they left,
  got @ or +, or another op, a bot or services already kicked, banned or moderated them.
- Never touches you, people with @ (or anything above +), services, servers or IRC operators; people with + and
  your friends / Auto-Op list unless the rule says otherwise.
- Every action prints one grey line in that channel that starts with "Channel Protection: ". The kick reason is a
  polite sentence the user can change; it never repeats the bad word.
- Plain RFC 1459 commands only (NOTICE, KICK, MODE +b/-b, +i/+m), so it works the same on every IRCd.
"""
from __future__ import annotations

import copy
import random
import re
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QTreeWidget, QTreeWidgetItem)

from .control import SERVICES, _ban_hits, rule_for

# Network service bots that are not called *Serv (QA 0.9.3): QuakeNet Q / L, Undernet X, Libera ALIS and friends.
BOTS = {"q", "l", "x", "alis", "saslserv", "infoserv", "statserv", "helpserv", "groupserv", "chanfix", "spamserv"}
from .protocol import lower, mask_ban, strip_format
from .tools import ToolWindow
from .widgets import FramedDialog, icon

DELAY = (1.0, 2.0)          # seconds, random in between, before acting (tests set (0, 0))
MINUTE = 60.0               # seconds in a minute, for the timed unban / unlock (tests make it short)
MEMORY = 30 * 60            # the 1st / 2nd / 3rd count per person is forgotten after this many seconds
SLACK = 2.0                 # someone else's kick / ban this close before our catch still counts as "already done"
GREY = "\x0314"
PREFIX = "Channel Protection: "
ALL = "All networks"
MIN_CAPS = 12               # CAPS only looks at lines with this many letters or more
CODES = "\x02\x03\x04\x11\x16\x1d\x1e\x1f"     # bold, colour, hex colour, monospace, reverse, italic, strike, underline
SPLIT_RE = re.compile(r"^[\w.-]+\.[\w-]+ [\w.-]+\.[\w-]+$")     # a netsplit quit: "hub.net leaf.net"

# key, label in the editor, word in the list
CATCHES = [
    ("flood", "Text flood", "flood"),
    ("repeat", "Repeats", "repeats"),
    ("caps", "CAPS", "CAPS"),
    ("colour", "Colour spam", "colours"),
    ("long", "Long lines", "long lines"),
    ("ctcp", "CTCP / notice", "CTCP"),
    ("nicks", "Nick flood", "nick flood"),
    ("massjoin", "Mass join", "mass join"),
    ("clones", "Clones", "clones"),
    ("words", "Bad words", "bad words"),
]
LABEL = {k: label for k, label, _ in CATCHES}

# the default kick reasons: polite, say what to stop doing, never repeat the bad word (mass join locks, it kicks nobody)
REASONS = {
    "flood": "Too many lines too fast, please slow down",
    "repeat": "Please don't repeat the same line",
    "caps": "Please turn off caps lock",
    "colour": "Too many colours, please keep it plain",
    "long": "Line too long, please split it up",
    "ctcp": "No CTCPs or notices to the whole channel",
    "nicks": "Too many nick changes",
    "clones": "Too many connections from one address",
    "words": "Please mind your language",
}

STEPS = [("warn", "Warn (notice)"), ("kick", "Kick"), ("kickban", "Kickban"), ("nothing", "Nothing")]
BAN_BY = [("host", "*!*@host"), ("userhost", "*!*user@host"), ("account", "account")]
LOCKS = ["i", "m"]

DEFAULTS = {
    "channel": "", "network": "",
    "flood": True, "flood_lines": 5, "flood_secs": 3,
    "repeat": True, "repeat_times": 3, "repeat_secs": 60,
    "caps": True, "caps_pct": 70,
    "colour": False, "colour_codes": 15,
    "long": False, "long_chars": 400,
    "ctcp": True,
    "nicks": True, "nicks_count": 3, "nicks_secs": 60,
    "massjoin": True, "massjoin_count": 6, "massjoin_secs": 10, "massjoin_mode": "i", "massjoin_mins": 5,
    "clones": False, "clones_count": 3,
    "words": True, "words_list": "free nitro, cheap followers, casino*",
    "steps": ["warn", "kick", "kickban"], "ban_by": "host", "ban_mins": 10,
    "leave_voiced": True, "leave_friends": True,
    "reasons": {}, "reason_ban_time": True, "reason_warn": True,
}


def new_rule(**kw) -> dict:
    r = copy.deepcopy(DEFAULTS)
    r.update(kw)
    return r


def _get(r: dict, key: str):
    """A value of the rule, or its default (rules saved by an older BChat miss newer keys)."""
    return r.get(key, DEFAULTS[key])


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    end = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{end}"


def word_list(r: dict) -> list[str]:
    return [w.strip() for w in str(_get(r, "words_list")).split(",") if w.strip().strip("*")]


def _word_re(entry: str) -> re.Pattern:
    """A whole word (or words), any case; * stands for any letters: casino* catches casinos and casino-online."""
    pat = r"\s+".join(r"\S*".join(re.escape(p) for p in w.split("*")) for w in entry.split())
    return re.compile(r"(?<!\w)" + pat + r"(?!\w)", re.IGNORECASE)


def bad_word(r: dict, plain: str) -> str:
    """The list entry the line hits, or ''."""
    for w in word_list(r):
        if _word_re(w).search(plain):
            return w
    return ""


def kick_reason(r: dict, catch: str, ban: bool = False) -> str:
    """What the channel sees: the user's sentence for this catch (empty = the default), plus the ban time."""
    text = str((_get(r, "reasons") or {}).get(catch, "")).strip() or REASONS.get(catch, "")
    if ban and _get(r, "reason_ban_time"):
        dot = "" if text[-1:] in ".!?" else "."
        text = f"{text}{dot} Banned for {_get(r, 'ban_mins')} min"
    return text


def warning(r: dict, catch: str) -> str:
    text = kick_reason(r, catch)
    return f"Warning: {text}" if _get(r, "reason_warn") else text


def describe(r: dict) -> list[str]:
    """The four columns of the list: Channel, Network, Catches, Then."""
    catches = []
    for key, _, word in CATCHES:
        if _get(r, key):
            catches.append(f"{word} ({len(word_list(r))})" if key == "words" else word)
    then: list[str] = []
    for step in _get(r, "steps"):
        word = f"ban {_get(r, 'ban_mins')} min" if step == "kickban" else step
        if not then or then[-1] != word:
            then.append(word)
    return [r.get("channel") or "all where I'm @", r.get("network") or ALL,
            ", ".join(catches) or "nothing", " > ".join(then) or "nothing"]


def _minutes_up(mins: int) -> str:
    return "1 minute is up" if mins == 1 else f"{mins} minutes are up"


def _host(u) -> str:
    return u.host.partition("@")[2].lower()


class Protection:
    """One per session. The session calls message / joined / nick_changed / kicked / mode / quit / got_op;
    each catch waits DELAY and then acts once (one grey line)."""

    def __init__(self, s):
        self.s = s
        self.lines: dict[tuple, list[tuple[float, str]]] = {}      # (chan, person) -> recent lines (time, text)
        self.nicks: dict[tuple, list[float]] = {}                  # (chan, person) -> recent nick changes
        self.joins: dict[str, list[float]] = {}                    # chan -> recent joins
        self.pending: dict[tuple, str] = {}                        # (chan, person) -> nick, waiting to act
        self.strikes: dict[tuple, tuple[int, float]] = {}          # (chan, person) -> (count, last time)
        self.acted: dict[tuple, float] = {}                        # (chan, nick) -> when someone else acted
        self.locking: set[str] = set()                             # chans with a lock on its way
        self.timers: dict[tuple, object] = {}                      # ("ban", chan, mask) / ("lock", chan, mode)
        self.due: list[tuple] = []                                 # lifts that waited for @ or a connection
        self.split: dict[str, float] = {}                          # nicks that left in a netsplit -> when

    # --- when to act ----------------------------------------------------------------------

    def _rule(self, b) -> dict | None:
        """The rule for this channel: one naming it beats one for every channel. None while the add-on is off."""
        cfg = self.s.cfg
        if not (cfg.addon_protection and cfg.protect_on) or b is None or b.kind != "channel":
            return None
        best = None
        for r in cfg.protect_rules:
            net = r.get("network", "")
            if net and lower(net) != lower(self.s.net.name):
                continue
            chan = r.get("channel", "")
            if chan and lower(chan) == lower(b.name):
                return r
            if not chan and best is None:
                best = r
        return best

    def _have_op(self, b) -> bool:
        me = b.users.get(self.s.fold(self.s.nick))
        if me is None:
            return False
        if "@" in me.prefixes:
            return True
        order = self.s.prefix_order
        return "@" in order and any(p in order[:order.index("@")] for p in me.prefixes)    # ~ and & are above @

    def _exempt(self, b, u, r: dict) -> bool:
        s = self.s
        n = lower(u.nick)
        if s.fold(u.nick) == s.fold(s.nick) or n in SERVICES or n in BOTS or "." in u.nick or getattr(u, "oper", False):
            return True
        if "services" in _host(u).split("."):
            return True
        if any(p != "+" for p in u.prefixes):                     # @, and halfop or anything else above +
            return True
        if "+" in u.prefixes and _get(r, "leave_voiced"):
            return True
        if _get(r, "leave_friends"):
            if s.fold(u.nick) in {s.fold(f) for f in s._friends_here()}:
                return True
            if rule_for(s.cfg, s.net.name, b.name, u.nick, u.host, u.account):
                return True
        return False

    def _person(self, u) -> str:
        return _host(u) or "nick:" + self.s.fold(u.nick)

    def _ready(self, b, nick: str):
        """(rule, user) when this person in this channel is ours to watch, else (None, None)."""
        r = self._rule(b)
        if r is None or not b.joined or not self._have_op(b):
            return None, None
        self._flush(b)
        u = b.users.get(self.s.fold(nick))
        if u is None or self._exempt(b, u, r):
            return None, None
        return r, u

    def _later(self, fn) -> None:
        lo, hi = DELAY
        QTimer.singleShot(int(random.uniform(lo, hi) * 1000), fn)

    def _say(self, b, text: str) -> None:
        self.s.add(b, "info", "", f"{GREY}{PREFIX}{text}")

    # --- what people do -------------------------------------------------------------------

    def heard(self, target: str, nick: str, text: str, notice: bool = False) -> None:
        """A PRIVMSG or NOTICE to a channel (not to @#chan: only the whole channel counts)."""
        s = self.s
        if not target or not s.is_channel(target) or not nick:
            return
        b = s.buffers.get(s.fold(target))
        if b is None:
            return
        if notice:
            kind = "notice"
        elif text.startswith("\x01ACTION"):
            kind, text = "action", text[7:].strip("\x01").lstrip(" ")
        elif text.startswith("\x01"):
            kind = "ctcp"
        else:
            kind = "msg"
        self.message(b, nick, text, kind)

    def message(self, b, nick: str, text: str, kind: str = "msg") -> None:
        r, u = self._ready(b, nick)
        if r is None or u is None:
            return
        key = (self.s.fold(b.name), self._person(u))
        if key in self.pending:
            return
        now = time.time()
        plain = strip_format(text)
        norm = " ".join(plain.lower().split())
        keep = max(_get(r, "flood_secs"), _get(r, "repeat_secs"))
        hist = [(t, x) for t, x in self.lines.get(key, []) if now - t <= keep]
        hist.append((now, norm))
        self.lines[key] = hist
        found = self._check(r, u.nick, text, plain, norm, kind, hist, now)
        if found:
            self.lines.pop(key, None)
            self._trigger(b, u, key, *found)

    def _check(self, r, nick, text, plain, norm, kind, hist, now):
        """(catch, detail) for the first catch this line sets off, or None."""
        if _get(r, "words"):
            w = bad_word(r, plain)
            if w:
                return "words", f"{nick} said a bad word ({w})"
        if kind in ("ctcp", "notice") and _get(r, "ctcp"):
            return "ctcp", f"{nick} sent a {'CTCP' if kind == 'ctcp' else 'notice'} to the whole channel"
        if _get(r, "flood"):
            secs = _get(r, "flood_secs")
            n = sum(1 for t, _ in hist if now - t <= secs)
            if n >= _get(r, "flood_lines"):
                return "flood", f"{nick} sent {n} lines in {secs} s"
        if kind in ("ctcp", "notice"):
            return None
        if _get(r, "repeat") and norm:
            secs = _get(r, "repeat_secs")
            n = sum(1 for t, x in hist if x == norm and now - t <= secs)
            if n >= _get(r, "repeat_times"):
                return "repeat", f"{nick} repeated a line {n} times"
        if _get(r, "caps"):
            cased = [c for c in plain if c.isupper() or c.islower()]
            up = sum(1 for c in cased if c.isupper())
            if len(cased) >= MIN_CAPS and up * 100 > _get(r, "caps_pct") * len(cased):
                return "caps", f"{nick} wrote {up * 100 // len(cased)}% capitals"
        if _get(r, "colour"):
            n = sum(text.count(c) for c in CODES)
            if n > _get(r, "colour_codes"):
                return "colour", f"{nick} used {n} colour or bold codes in a line"
        if _get(r, "long") and len(plain) > _get(r, "long_chars"):
            return "long", f"{nick} sent a line of {len(plain)} characters"
        return None

    def joined(self, b, nick: str) -> None:
        s = self.s
        r = self._rule(b)
        if r is None or not b.joined or not self._have_op(b) or s.fold(nick) == s.fold(s.nick):
            return
        self._flush(b)
        now = time.time()
        rejoin = now - self.split.pop(s.fold(nick), 0.0) < 15 * 60      # back from a netsplit: not a mass join
        chan = s.fold(b.name)
        if _get(r, "massjoin") and not rejoin:
            secs, mode = _get(r, "massjoin_secs"), _get(r, "massjoin_mode")
            q = [t for t in self.joins.get(chan, []) if now - t <= secs] + [now]
            self.joins[chan] = q
            if len(q) >= _get(r, "massjoin_count") and mode not in b.modes and chan not in self.locking \
                    and ("lock", chan, mode) not in self.timers:
                self.locking.add(chan)
                self.joins[chan] = []
                n, mins, name = len(q), _get(r, "massjoin_mins"), b.name
                self._later(lambda: self._lock(name, n, secs, mode, mins))
        u = b.users.get(s.fold(nick))
        if _get(r, "clones") and u is not None and _host(u) and not self._exempt(b, u, r):
            same = sum(1 for x in b.users.values() if _host(x) == _host(u))
            key = (chan, self._person(u))
            if same > _get(r, "clones_count") and key not in self.pending:
                self._trigger(b, u, key, "clones", f"{u.nick} makes {same} people from one address")

    def nick_changed(self, b, old: str, u) -> None:
        s = self.s
        for key, nick in self.pending.items():
            if key[0] == s.fold(b.name) and s.fold(nick) == s.fold(old):
                self.pending[key] = u.nick
        r, u = self._ready(b, u.nick)
        if r is None or u is None or not _get(r, "nicks"):
            return
        key = (s.fold(b.name), self._person(u))
        if key in self.pending:
            return
        now, secs = time.time(), _get(r, "nicks_secs")
        q = [t for t in self.nicks.get(key, []) if now - t <= secs] + [now]
        self.nicks[key] = q
        if len(q) >= _get(r, "nicks_count"):
            self.nicks.pop(key, None)
            self._trigger(b, u, key, "nicks", f"{u.nick} changed nick {len(q)} times in {secs} s")

    def quit(self, nick: str, reason: str) -> None:
        if SPLIT_RE.match(reason or ""):
            now = time.time()
            self.split = {k: t for k, t in self.split.items() if now - t < 15 * 60}
            self.split[self.s.fold(nick)] = now

    # --- what other ops do ------------------------------------------------------------------

    def _other(self, who: str) -> bool:
        return bool(who) and self.s.fold(who) != self.s.fold(self.s.nick)

    def kicked(self, b, kicker: str, victim: str) -> None:
        if self._other(kicker):
            self.acted[(self.s.fold(b.name), self.s.fold(victim))] = time.time()

    def mode(self, b, who: str, sign: str, c: str, arg: str, prefix: bool = False) -> None:
        """A channel mode change. Someone else banning, quieting, devoicing or unbanning ours: they took over."""
        s = self.s
        chan = s.fold(b.name)
        if prefix:
            if s.fold(arg) == s.fold(s.nick):
                if sign == "+" and self._have_op(b):
                    self.got_op(b)
            elif self._other(who) and arg:
                self.acted[(chan, s.fold(arg))] = time.time()
            return
        if not self._other(who):
            return
        if sign == "-" and c == "b" and arg:
            job = ("ban", chan, lower(arg))
            self.timers.pop(job, None)
            self.due = [d for d in self.due if d[0] != job]
        elif sign == "-" and c in LOCKS:
            job = ("lock", chan, c)
            self.timers.pop(job, None)
            self.due = [d for d in self.due if d[0] != job]
        elif sign == "+" and arg and c in s.modes_list and c not in "eI":
            now = time.time()
            account = arg.rpartition(":")[2] if ":" in arg and "!" not in arg else ""
            for u in b.users.values():
                if _ban_hits(arg, u.nick, u.host) or (account and lower(u.account) == lower(account)):
                    self.acted[(chan, s.fold(u.nick))] = now

    def got_op(self, b) -> None:
        self._flush(b)

    # --- acting ----------------------------------------------------------------------------

    def _trigger(self, b, u, key, catch: str, detail: str) -> None:
        self.pending[key] = u.nick
        seen, chan = time.time(), b.name
        self._later(lambda: self._act(chan, key, catch, detail, seen))

    def _act(self, chan: str, key, catch: str, detail: str, seen: float) -> None:
        s = self.s
        nick = self.pending.pop(key, None)
        b = s.buffers.get(s.fold(chan))
        if nick is None or s.state != "connected" or b is None or not b.joined or not self._have_op(b):
            return
        r = self._rule(b)
        u = b.users.get(s.fold(nick))
        if r is None or u is None or self._exempt(b, u, r):
            return                                  # off now, gone (kicked, parted), or given @ / + meanwhile
        if self.acted.get((key[0], s.fold(u.nick)), 0.0) >= seen - SLACK:
            return                                  # another op, a bot or services already dealt with it
        now = time.time()
        n, last = self.strikes.get(key, (0, 0.0))
        n = 1 if now - last > MEMORY else n + 1
        self.strikes[key] = (n, now)
        steps = list(_get(r, "steps")) or ["nothing"]
        self._do(b, u, r, catch, detail, steps[min(n, len(steps)) - 1], ordinal(n))

    def _ban_mask(self, b, u, r: dict) -> str:
        pre, types = self.s.extban
        if _get(r, "ban_by") == "account" and u.account and pre and "a" in types:
            return f"{pre}a:{u.account}"
        return mask_ban(u.nick, u.host, 3 if _get(r, "ban_by") == "userhost" else 1)

    def _do(self, b, u, r: dict, catch: str, detail: str, step: str, nth: str) -> None:
        s = self.s
        mask = ""
        if step == "kickban":
            mask = self._ban_mask(b, u, r)
            me = b.users.get(s.fold(s.nick))
            if _ban_hits(mask, s.nick, me.host if me else ""):
                step = "kick"                       # never ban an address we share
        if step == "warn":
            self._say(b, f"{detail}: warning by notice ({nth})")
            s.send("NOTICE", u.nick, warning(r, catch))
        elif step == "kick":
            self._say(b, f"{detail}: kicking ({nth})")
            s.send("KICK", b.name, u.nick, kick_reason(r, catch))
        elif step == "kickban":
            mins = _get(r, "ban_mins")
            self._say(b, f"{detail}: kickbanning {mask} for {mins} min ({nth})")
            s.send("MODE", b.name, "+b", mask)
            s.send("KICK", b.name, u.nick, kick_reason(r, catch, ban=True))
            self._lift_later(("ban", s.fold(b.name), lower(mask)), b.name, mask, mins)
        else:
            self._say(b, f"{detail}: doing nothing, as set ({nth})")

    def _lock(self, chan: str, n: int, secs: int, mode: str, mins: int) -> None:
        s = self.s
        self.locking.discard(s.fold(chan))
        b = s.buffers.get(s.fold(chan))
        if s.state != "connected" or b is None or not b.joined or not self._have_op(b) or self._rule(b) is None:
            return
        if mode in b.modes:
            return                                  # someone else locked it already
        self._say(b, f"{n} joins in {secs} s: locking {b.name} with +{mode} for {mins} minute{'' if mins == 1 else 's'}")
        s.send("MODE", b.name, "+" + mode)
        self._lift_later(("lock", s.fold(b.name), mode), b.name, mode, mins)

    def _lift_later(self, job: tuple, chan: str, what: str, mins: int) -> None:
        token = object()
        self.timers[job] = token
        QTimer.singleShot(int(mins * MINUTE * 1000), lambda: self._expire(job, token, chan, what, mins))

    def _expire(self, job, token, chan: str, what: str, mins: int) -> None:
        if self.timers.get(job) is not token:
            return                                  # someone else lifted it, or a newer timer took over
        del self.timers[job]
        if not self._lift(job, chan, what, mins):
            self.due.append((job, chan, what, mins))

    def _lift(self, job, chan: str, what: str, mins: int) -> bool:
        """Lift our ban / lock. False while we can't (no @, not connected): it waits in self.due."""
        s = self.s
        b = s.buffers.get(s.fold(chan))
        if s.state != "connected" or b is None or not b.joined or not self._have_op(b):
            return False
        if job[0] == "ban":
            self._say(b, f"{_minutes_up(mins)}: lifting the ban {what}")
            s.send("MODE", b.name, "-b", what)
        elif what in b.modes:
            self._say(b, f"{_minutes_up(mins)}: unlocking {b.name}")
            s.send("MODE", b.name, "-" + what)
        return True

    def _flush(self, b) -> None:
        """Lifts that came due while we had no @ in this channel."""
        if not self.due or not self._have_op(b):
            return
        chan = self.s.fold(b.name)
        mine = [d for d in self.due if d[0][1] == chan]
        self.due = [d for d in self.due if d[0][1] != chan]
        for job, name, what, mins in mine:
            if not self._lift(job, name, what, mins):
                self.due.append((job, name, what, mins))


# --- the windows ------------------------------------------------------------------------------

def _muted(t, text: str, wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(f"color: {t.muted};")
    lb.setWordWrap(wrap)
    lb.setTextFormat(Qt.TextFormat.RichText)
    return lb


def _heading(t, text: str) -> QLabel:
    from .widgets import is_light
    h = QLabel(text)
    colour = t.text if is_light(t) else t.title             # QA 0.9.3: pink on a light grey was hard to read
    h.setStyleSheet(f"color: {colour}; font-size: 11pt; font-weight: bold;")
    return h


def _num(v: int, lo: int = 1, hi: int = 999, w: int = 56) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(int(v))
    s.setFixedWidth(w)
    return s


def _combo(items: list[str], i: int = 0, w: int | None = None) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setCurrentIndex(i)
    if w:
        c.setFixedWidth(w)
    return c


def _save_cancel(d, lay) -> QPushButton:
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton(icon("cancel"), "&Cancel")
    cancel.setAutoDefault(False)
    cancel.clicked.connect(d.reject)
    save = QPushButton(icon("done"), "&Save")
    save.setDefault(True)
    save.clicked.connect(d.accept)
    row.addWidget(cancel)
    row.addWidget(save)
    lay.addLayout(row)
    return save


class KickReasonsDialog(FramedDialog):
    """One polite sentence per catch (empty = the default), the ban time on a kickban, 'Warning:' on the 1st time."""

    def __init__(self, win, reasons: dict, ban_time: bool, warn: bool, ban_mins: int, parent=None):
        super().__init__("Channel Protection: kick reasons", parent or win)
        t = win.cfg.theme
        self.setFixedWidth(600)
        self.body.setContentsMargins(20, 16, 20, 14)
        self.body.setSpacing(6)
        self.body.addWidget(_muted(t, "Everyone in the channel sees these. Empty = the default."))
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(5)
        self.edits: dict[str, QLineEdit] = {}
        for i, (key, default) in enumerate(REASONS.items()):
            g.addWidget(QLabel(LABEL[key] + ":"), i, 0)
            e = QLineEdit(str(reasons.get(key, "")).strip() or default)
            e.setPlaceholderText(default)
            e.setFixedWidth(370)
            g.addWidget(e, i, 1)
            self.edits[key] = e
        self.body.addLayout(g)
        self.body.addSpacing(4)
        self.ban_time = QCheckBox(f"On a kickban, add how long:  “... Banned for {ban_mins} min”")
        self.ban_time.setChecked(ban_time)
        self.body.addWidget(self.ban_time)
        self.warn = QCheckBox("Say it's a warning on the 1st time:  “Warning: ...” (by notice)")
        self.warn.setChecked(warn)
        self.body.addWidget(self.warn)
        _save_cancel(self, self.body)

    def reasons(self) -> dict:
        """Only the sentences that differ from the default are kept."""
        out = {}
        for key, e in self.edits.items():
            text = " ".join(e.text().split())
            if text and text != REASONS[key]:
                out[key] = text
        return out


class ProtectionDialog(FramedDialog):
    """Add or edit one channel's rule (mockup-channel-guard.png, right side)."""

    def __init__(self, win, rule: dict | None = None, **kw):
        r = new_rule(**kw) if rule is None else {**new_rule(), **copy.deepcopy(rule)}
        chan = r.get("channel", "")
        super().__init__(f"Channel Protection: {chan}" if chan else "Channel Protection", win)
        self.win = win
        t = win.cfg.theme
        self.setFixedWidth(640)
        self.body.setContentsMargins(20, 16, 20, 14)
        self.body.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("Channel:"))
        self.channel = QLineEdit(chan)
        self.channel.setFixedWidth(180)
        row.addWidget(self.channel)
        row.addSpacing(12)
        row.addWidget(QLabel("Network:"))
        self.network = QComboBox()
        self.network.addItems([n.name for n in win.cfg.networks] + [ALL])
        self.network.setCurrentText(r.get("network") or ALL)
        self.network.setFixedWidth(160)
        row.addWidget(self.network)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(_muted(t, "Empty channel = every channel where you have @."))
        self.body.addSpacing(4)

        self.body.addWidget(_heading(t, "Catch"))
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(4)
        self.boxes: dict[str, QCheckBox] = {}
        self.spins: dict[str, QSpinBox] = {}
        lbl = QLabel
        n = self._spin
        self.lock_mode = _combo(["+" + m for m in LOCKS], LOCKS.index(r["massjoin_mode"]) if r["massjoin_mode"] in LOCKS else 0, 56)
        self.words_list = QLineEdit(r["words_list"])
        self.words_list.setFixedWidth(260)
        rows = [
            ("flood", [n(r, "flood_lines"), lbl("lines in"), n(r, "flood_secs"), lbl("seconds")]),
            ("repeat", [lbl("the same line"), n(r, "repeat_times"), lbl("times in"), n(r, "repeat_secs"), lbl("seconds")]),
            ("caps", [lbl("over"), n(r, "caps_pct", hi=100), lbl(f"% capitals (lines of {MIN_CAPS}+ letters)")]),
            ("colour", [lbl("more than"), n(r, "colour_codes"), lbl("colour or bold codes in a line")]),
            ("long", [lbl("over"), n(r, "long_chars", w=64), lbl("characters")]),
            ("ctcp", [lbl("sent to the whole channel")]),
            ("nicks", [n(r, "nicks_count"), lbl("nick changes in"), n(r, "nicks_secs"), lbl("seconds")]),
            ("massjoin", [n(r, "massjoin_count"), lbl("joins in"), n(r, "massjoin_secs"), lbl("s: lock"), self.lock_mode,
                          lbl("for"), n(r, "massjoin_mins"), lbl("min")]),
            ("clones", [lbl("more than"), n(r, "clones_count"), lbl("people from one address")]),
            ("words", [self.words_list, lbl("(commas; * works)")]),
        ]
        for i, (key, parts) in enumerate(rows):
            cb = QCheckBox(LABEL[key])
            cb.setChecked(bool(r[key]))
            g.addWidget(cb, i, 0)
            h = QHBoxLayout()
            h.setSpacing(6)
            for p in parts:
                p.setEnabled(cb.isChecked())
                cb.toggled.connect(p.setEnabled)
                h.addWidget(p)
            h.addStretch(1)
            g.addLayout(h, i, 1)
            self.boxes[key] = cb
        self.body.addLayout(g)
        self.body.addSpacing(4)

        self.body.addWidget(_heading(t, "Then (per person, remembered for 30 minutes)"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.steps: list[QComboBox] = []
        keys = [k for k, _ in STEPS]
        for i, label in enumerate(("1st time:", "2nd:", "3rd:")):
            row.addWidget(QLabel(label))
            have = list(r["steps"])[i] if i < len(r["steps"]) else "nothing"
            c = _combo([text for _, text in STEPS], keys.index(have) if have in keys else len(keys) - 1, 124)
            row.addWidget(c)
            self.steps.append(c)
        row.addStretch(1)
        self.body.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Ban"))
        by = [k for k, _ in BAN_BY]
        self.ban_by = _combo([text for _, text in BAN_BY], by.index(r["ban_by"]) if r["ban_by"] in by else 0, 130)
        row.addWidget(self.ban_by)
        row.addWidget(QLabel("for"))
        self.ban_mins = n(r, "ban_mins")
        row.addWidget(self.ban_mins)
        row.addWidget(QLabel("minutes, then BChat lifts it"))
        row.addStretch(1)
        self.body.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_muted(t, "Kick reasons are polite sentences you can change.", False))
        row.addStretch(1)
        self.reasons_btn = QPushButton("Kick reasons...")
        self.reasons_btn.setAutoDefault(False)
        self.reasons_btn.clicked.connect(lambda: self.edit_reasons())
        row.addWidget(self.reasons_btn)
        self.body.addLayout(row)
        self.body.addSpacing(4)

        self.body.addWidget(_heading(t, "Leave alone"))
        row = QHBoxLayout()
        self.leave_voiced = QCheckBox("People with @ or +")
        self.leave_voiced.setChecked(bool(r["leave_voiced"]))
        self.leave_friends = QCheckBox("Friends and the Auto-Op list")
        self.leave_friends.setChecked(bool(r["leave_friends"]))
        row.addWidget(self.leave_voiced)
        row.addWidget(self.leave_friends)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(_muted(t, "You, services and IRC operators are never touched."))
        self.save_btn = _save_cancel(self, self.body)

        self.reasons = dict(r.get("reasons") or {})
        self.reason_ban_time = bool(r["reason_ban_time"])
        self.reason_warn = bool(r["reason_warn"])
        self.reasons_dialog: KickReasonsDialog | None = None

    def _spin(self, r: dict, key: str, hi: int = 999, w: int = 56) -> QSpinBox:
        s = _num(min(max(int(_get(r, key)), 1), hi), hi=hi, w=w)
        self.spins[key] = s
        return s

    def edit_reasons(self) -> KickReasonsDialog:
        d = self.reasons_dialog = KickReasonsDialog(self.win, self.reasons, self.reason_ban_time, self.reason_warn,
                                                    self.ban_mins.value(), parent=self)

        def done(code):
            if code:
                self.reasons = d.reasons()
                self.reason_ban_time = d.ban_time.isChecked()
                self.reason_warn = d.warn.isChecked()
        d.finished.connect(done)
        d.open()
        return d

    def rule(self) -> dict:
        chan = "".join(self.channel.text().split())
        if chan and chan[0] not in "#&!+":
            chan = "#" + chan
        net = self.network.currentText()
        r: dict = {"channel": chan, "network": "" if net == ALL else net}
        for key, cb in self.boxes.items():
            r[key] = cb.isChecked()
        for key, s in self.spins.items():
            if key != "ban_mins":
                r[key] = s.value()
        r["massjoin_mode"] = LOCKS[self.lock_mode.currentIndex()]
        r["words_list"] = ", ".join(w.strip() for w in self.words_list.text().split(",") if w.strip())
        r["steps"] = [STEPS[c.currentIndex()][0] for c in self.steps]
        r["ban_by"] = BAN_BY[self.ban_by.currentIndex()][0]
        r["ban_mins"] = self.ban_mins.value()
        r["leave_voiced"] = self.leave_voiced.isChecked()
        r["leave_friends"] = self.leave_friends.isChecked()
        r["reasons"] = dict(self.reasons)
        r["reason_ban_time"] = self.reason_ban_time
        r["reason_warn"] = self.reason_warn
        return r


class ProtectionWindow(ToolWindow):
    """The list: one row per channel rule (mockup-channel-guard.png, left side)."""

    def __init__(self, win):
        super().__init__("BChat: Channel Protection", win, (660, 290))
        t = win.cfg.theme
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(8)
        self.on = QCheckBox("Use Channel Protection (BChat only acts in channels where you have @)")
        self.on.setChecked(win.cfg.protect_on)
        self.on.toggled.connect(self._toggle)
        self.body.addWidget(self.on)
        self.view = QTreeWidget()
        self.view.setRootIsDecorated(False)
        self.view.setHeaderLabels(["Channel", "Network", "Catches", "Then"])
        for c, w in ((0, 120), (1, 100), (2, 240)):
            self.view.setColumnWidth(c, w)
        self.view.itemDoubleClicked.connect(lambda *_: self.edit())
        self.view.currentItemChanged.connect(lambda *_: self._buttons())
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(_muted(t, "Off by default. Every action prints one grey line in the channel."), 1)
        self.add_btn = QPushButton(icon("new"), "Add...", objectName="compact")
        self.add_btn.clicked.connect(lambda: self.add())
        self.edit_btn = QPushButton(icon("edit"), "Edit...", objectName="compact")
        self.edit_btn.clicked.connect(lambda: self.edit())
        self.remove_btn = QPushButton(icon("close-light"), "Remove", objectName="compact")
        self.remove_btn.clicked.connect(self.remove)
        for b in (self.add_btn, self.edit_btn, self.remove_btn):
            row.addWidget(b)
        self.body.addLayout(row)
        self.dialog: ProtectionDialog | None = None
        self.fill()

    def _toggle(self, on: bool) -> None:
        self.win.cfg.protect_on = on
        self.win.save_config()

    def fill(self, keep: int | None = None) -> None:
        self.view.clear()
        for r in self.win.cfg.protect_rules:
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

    def select(self, i: int) -> None:
        if 0 <= i < self.view.topLevelItemCount():
            self.view.setCurrentItem(self.view.topLevelItem(i))

    def add(self, **kw) -> ProtectionDialog:
        d = self.dialog = ProtectionDialog(self.win, None, **kw)

        def done(code):
            if code:
                self.win.cfg.protect_rules.append(d.rule())
                self.win.save_config()
                self.fill(len(self.win.cfg.protect_rules) - 1)
        d.finished.connect(done)
        d.open()
        return d

    def edit(self) -> ProtectionDialog | None:
        i = self._row()
        if i < 0:
            return None
        d = self.dialog = ProtectionDialog(self.win, self.win.cfg.protect_rules[i])

        def done(code):
            if code:
                self.win.cfg.protect_rules[i] = d.rule()
                self.win.save_config()
                self.fill(i)
        d.finished.connect(done)
        d.open()
        return d

    def remove(self) -> None:
        i = self._row()
        if i >= 0:
            del self.win.cfg.protect_rules[i]
            self.win.save_config()
            self.fill(min(i, len(self.win.cfg.protect_rules) - 1))
