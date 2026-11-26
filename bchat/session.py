"""One IRC network connection and its buffers. Qt networking, but no widgets, so tests can drive it."""
from __future__ import annotations

import contextlib
import fnmatch
from collections import deque
import random
import re
import struct
import sys
import time
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal, QCryptographicHash
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QHostInfo, QNetworkProxy, QSslSocket, QSslCertificate

from .config import Config, NetworkConfig, Server, random_nick
from .textevents import EVENTS, SHORT, render
from .protocol import Message, build_line, folder, lower, mask_ban, parse_line, strip_format

# kinds a line can have; the chat view maps them to colours
MSG, SELF, ACTION, JOIN, PART, TOPIC, INFO, WHOIS, NOW_TALKING, HILITE, NOTICE, ERROR, CONNECT = (
    "msg", "self", "action", "join", "part", "topic", "info", "whois", "now", "hilite", "notice", "error", "connect")

SERVER, CHANNEL, QUERY = "server", "channel", "query"


def look_up(owner: QObject, host: str, done) -> None:
    """QHostInfo.lookupHost, but the answer is dropped when owner is gone by then (a tab closed, a window freed):
    a name lookup can take seconds, and a late answer on a deleted session raised 'Signal source has been deleted'."""
    from shiboken6 import isValid
    QHostInfo.lookupHost(host, lambda info: done(info) if isValid(owner) else None)


def duration(secs: float) -> str:
    """3 h 12 min, 45 min, 20 s: /online and the network tooltip."""
    secs = int(max(0, secs))
    h, m = secs // 3600, secs % 3600 // 60
    if h:
        return f"{h} h {m} min"
    return f"{m} min" if m else f"{secs} s"


@dataclass
class Line:
    kind: str
    left: str
    text: str
    ts: float = field(default_factory=time.time)
    rank: str = ""   # light name (op, voice, ...) the speaker had when the line was said
    colour: str = ""  # a highlight rule's own colour ("" = the theme's)
    msgid: str = ""   # IRCv3 msgid: what a +reply points at
    reply_to: str = ""  # on a quote line: the msgid it quotes (a click jumps there)
    hidden: bool = False  # 0.6.0: a join/part line in a tab set to hide them (still logged, not drawn)


@dataclass
class User:
    nick: str
    prefixes: str = ""
    host: str = ""
    away: bool = False
    realname: str = ""
    server: str = ""
    country: str = ""
    account: str = ""
    away_reason: str = ""
    last_msg: float = 0.0
    oper: bool = False      # 0.9.3: WHO flags have * (an IRC operator): Channel Protection never touches them


class Buffer:
    def __init__(self, session: "Session", name: str, kind: str):
        self.session = session
        self.name = name
        self.kind = kind
        self.lines: list[Line] = []
        self.users: dict[str, User] = {}
        self.topic = ""
        self.placeholder = False   # New > Channel Tab: an empty tab that /join fills
        self.modes = ""
        self.joined = kind != CHANNEL
        self.activity = 0  # 0 none, 1 data, 2 message, 3 highlight
        self.unread = 0               # 0.5.0 tray menu: messages since you last looked at this tab
        self.mentioned = False        # your nick was said since then
        self.marker: int | None = None
        self.history_since = 0.0      # chathistory: lines after this were asked for (0 = the latest)
        self.rejoined_at = 0.0        # last rejoin after a kick
        self.mode_args: dict[str, str] = {}
        self.topic_by = ""            # 333 / TOPIC: who set it and when (Channel Central)
        self.topic_at = 0.0
        self.typing: dict[str, tuple[str, float]] = {}   # lower nick -> (nick, when): +typing=active
        self.key = ""                 # 0.8.5: the channel key (our JOIN, +k, 324), kept for the rejoin

    def mode_text(self) -> str:
        """As XChat's title shows them: letters in the server's order, then their values."""
        if not self.modes:
            return ""
        values = [self.mode_args[c] for c in self.modes if c in self.mode_args]
        return " ".join(["+" + self.modes, *values])

    def rank(self, u: User) -> int:
        order = self.session.prefix_order
        return min((order.index(p) for p in u.prefixes if p in order), default=len(order))

    def sorted_users(self) -> list[User]:
        """XChat's five orders: A-Z ops first, A-Z, Z-A ops last, Z-A, unsorted (as they joined)."""
        order = self.session.cfg.ul_sort
        users = list(self.users.values())
        if order == 4:
            return users
        by_rank = order in (0, 2)
        users.sort(key=lambda u: (self.rank(u) if by_rank else 0, self.session.fold(u.nick)))
        return users[::-1] if order in (2, 3) else users

    def counts(self) -> tuple[int, int]:
        order = self.session.prefix_order
        # "ops" means @ or higher, same as XChat's count box
        at = order.index("@") if "@" in order else 0
        ops = sum(1 for u in self.users.values() if self.rank(u) <= at)
        return ops, len(self.users)


IGNORE_KINDS = "CPNTDI"     # Unignore stays off unless asked for
IGNORE_STATS: dict[str, int] = {}


def skips_proxy(rules: str, host: str) -> bool:
    """0.8.10: Preferences > Network setup > Proxy Server > Not for: names or addresses, commas or spaces
    between them, * for any part, any case. 'localhost, 127.0.0.1, *.lan' -> those connect directly."""
    host = host.strip().strip("[]").rstrip(".").lower()
    if not host:
        return False
    for rule in re.split(r"[,\s;]+", rules.lower()):
        rule = rule.strip().strip("[]").rstrip(".")
        if rule and fnmatch.fnmatchcase(host, rule.replace("[", "[[]")):
            return True
    return False


class Session(QObject):
    buffer_added = Signal(object)
    buffer_removed = Signal(object)
    buffer_changed = Signal(object)  # topic, modes or name
    users_changed = Signal(object)
    line_added = Signal(object, object)
    state_changed = Signal()
    raw_line = Signal(str, bool)  # text, outgoing
    user_info = Signal(str)  # nick whose silent whois just finished
    address_found = Signal(str, str)  # 0.8.5: USERHOST answer for /ban, /ignore: nick, user@host ('' = not on IRC)
    alert = Signal(object)   # a highlight or private message that should flash the taskbar
    friends_changed = Signal()
    cert_question = Signal(object)    # a certificate BChat can't verify: the window asks the user
    pins_changed = Signal()
    host_info = Signal(object)    # QHostInfo for our own address (Network > Local), back on the GUI thread
    family_info = Signal(object)  # 0.6.1: QHostInfo for a server name that IPv4/IPv6 only couldn't find
    notify = Signal(object, str)  # buffer, event: chan priv hilight join part kick notice invite connect disconnect
    lines_inserted = Signal(object)  # history went in above existing lines: the tab is drawn again
    invited = Signal(object, str, str)   # session, channel, who: the window offers Join / Ignore (never joins by itself)
    typing_changed = Signal(object)      # buffer: someone started or stopped typing (+typing)
    servers_moved = Signal()             # 0.8.6: 'move to top on connect' changed the network's server order
    oper_changed = Signal()              # 0.9.3: the server made us an IRC operator, or took it away (Oper tools)

    MAX_LINES = 5000
    LAG_WARN_MS = 5000
    LAG_FULL_MS = 1000     # the lag bar is full at 1 second, like XChat's (fe_set_lag)
    WANTED_CAPS = {"multi-prefix", "away-notify", "userhost-in-names", "server-time", "znc.in/server-time-iso",
                   "znc.in/self-message", "chghost", "cap-notify", "account-notify", "account-tag", "extended-join",
                   "invite-notify", "message-tags", "setname", "batch", "draft/chathistory", "chathistory",
                   "labeled-response", "extended-monitor"}
    # 0.6.0 Edit Network > Server Features: what the user sees -> the capabilities behind it (all on by default)
    SERVER_FEATURES = (("Typing notices and replies", ("message-tags",)),
                       ("Message history", ("draft/chathistory", "chathistory")),
                       ("Away notices", ("away-notify",)),
                       ("Account names", ("account-notify", "account-tag", "extended-join")),
                       ("Answers in the right tab", ("labeled-response",)),
                       ("Server time on lines", ("server-time", "znc.in/server-time-iso")),
                       ("Friends' away status", ("extended-monitor",)))
    PACE = {"careful": 1.5, "normal": 1.0, "fast": 0.5}   # Preferences > Network > Flood: how quickly lines go out
    # 477 registered only, 489 TLS only, 520 opers only (+O). 0.8.3: not 405 (too many channels): that is about us,
    # not the channel, and a server at its limit says it even for a channel we are already in.
    JOIN_REFUSED = {471, 473, 474, 475, 477, 489, 520}
    HISTORY_LINES = 50     # asked for on join when the server keeps channel history (IRCv3 chathistory)

    def __init__(self, net: NetworkConfig, cfg: Config, parent=None):
        super().__init__(parent)
        self.net = net
        self.cfg = cfg
        self.server_buffer = Buffer(self, net.name, SERVER)
        self.buffers: dict[str, Buffer] = {}
        self.casemapping = "rfc1459"   # FINDING-01: ISUPPORT CASEMAPPING; until then the IRC default
        self.fold = lower              # this server's nick/channel folding: every key in buffers/users/... uses it
        self.nick = self._identity("nick") or random_nick()
        self.state = "disconnected"
        self.server_name = ""
        self.network_token = ""   # ISUPPORT NETWORK=, the server's own name for its network
        self.prefix_modes = "ohv"
        self.prefix_chars = "@%+"
        self.chantypes = "#&"
        self.modes_list = "beI"    # CHANMODES group A: lists, always carry a value, not channel settings
        self.modes_key = "k"       # group B: a value both ways
        self.modes_on_set = "fjl"  # group C: a value only when set
        self.modes_flags = "imnpst"  # group D: plain on/off (Channel Central shows these)
        self.client_tag_deny = ""    # CLIENTTAGDENY: client tags (+typing, +draft/reply) the server drops
        self.sent_count = 0          # lines handed to the server: a /timer's flood check
        self.max_modes = 3
        self.away = False
        self.server_index = -1
        self._ports_left: list[int] = []     # 0.6.0 host/+6697,7000: the ports of this server not tried yet
        self._cur_port = 0
        self._repeat = False                 # the next connect goes to the same server and port again
        self._ws_path = ""                   # 0.6.0: the current server is a WebSocket one (wss://host/path)
        self.want_connected = False
        self.nick_attempt = 0
        self._welcomed = False
        self._cap_active: set[str] = set()
        self._cap_ending = False
        self._whois_target: Buffer | None = None
        self._whois_nick = ""
        self._away_seen: dict[str, str] = {}
        self._silent_whois: dict[str, dict] = {}
        self.whois_cache: dict[str, dict] = {}
        self._names_fresh: set[str] = set()
        self._buf = b""
        self._rx: deque[bytes] = deque()    # 0.6.1: lines read, not handled yet (see _drain)
        self._drain_queued = False
        self.lag_ms: int | None = None
        self._ping_sent = 0.0
        self._last_rx = 0.0
        self.current: Buffer | None = None
        self.focus_next = ""
        self.stay_back = ""                # /join -n: this channel's tab opens without taking the front
        self.dns_waiting: dict = {}        # /dns <nick>: folded nick -> the tab that asked (USERHOST answer)
        self._addr_waiting: list[str] = []  # 0.8.5: nicks asked with USERHOST for /ban, /ignore, oldest first
        self.player = None                 # /play: the file being sent
        self.typed_by_hand = False
        self.statusmsg = ""
        self.whox = False
        self.chathistory_max = -1          # ISUPPORT CHATHISTORY=: -1 not offered, 0 no limit
        self.join_once: list[tuple[str, str]] = []   # (channel, key) from an irc:// link: joined after login, not saved
        self._history: dict[str, tuple[str, list]] = {}   # open history batch id -> (target, lines)
        self._sasl_state = ""
        self._starttls, self._scram, self._sasl_mech, self._scram_in = "", None, "", ""
        self._labels, self._label_batches, self._route = {}, {}, None
        self.last_ctcp_prefix = ""
        self._cert_loaded = False          # a client certificate is on the socket (Log in with: Certificate)
        self.bouncer = ""                  # 0.4.0: "ZNC", "soju" or "psyBNC" when we talk to one, not the network itself
        self.bouncer_version = ""
        self._bouncer_said = False
        self._version_wait = 0.0           # asked ZNC's *status for its version, quietly
        self._znc_guess = False            # 0.6.1: ZNC only by its caps so far; a 401 for *status means it's the server
        self._playback: dict[str, tuple[str, list]] = {}   # ZNC playback batch id -> (target, lines)
        self._znc_collect: tuple[str, list, float] | None = None   # between ZNC's "Buffer Playback..." and "Playback Complete."
        self.online_since = 0.0            # /online: when this connection got its welcome
        self.motd_asked = False            # /motd typed: show it even with "Skip the MOTD"
        from .control import Control
        self.is_oper = False               # 0.9.3 Oper tools: 381 or user mode +o; off again on -o, on a lost link or a new one
        self.ircd_version = ""              # 0.9.3 Oper tools: the server software, from 004 (oper.ircd_family picks the ban commands)
        self.oper_sink = None              # 0.9.3 the Server bans window reading STATS answers: (n, message) -> consumed
        #                                    (n 0 = a notice from OperServ: BeeIRCd lists AKILL / ZLINE / SHUN that way)
        self.wallops_on = False            # 0.9.3 user mode +w: the server sends us wallops (our own ones too)
        self.control = Control(self)       # 0.5.0 Auto-Op / Auto-Voice / Protect
        from .protection import Protection
        self.protection = Protection(self)  # 0.9.3 Channel Protection (an add-on, off until ticked)
        self.services = ""                 # "anope" or "atheme", from ChanServ's VERSION answer (ChanServ Access)
        self.services_guessed = False
        self._services_wait: list = []
        self.chanserv_sink = None          # the ChanServ Access window reading ChanServ's answers
        self._cap_more: set[str] = set()
        self._cap_offered: dict[str, str] = {}
        self._cap_pending = 0
        self._sts_enforced = False
        self._ctcp_ignored: dict[str, float] = {}   # 0.8.5: nick -> until when their CTCPs are ignored (mIRC /flood)
        self._ctcp_held = False                     # 0.8.5: the flood buffer is in use (its status line was shown)
        self._flood_lines: dict[str, deque] = {}    # 0.8.5 flood buffer: nick -> their held replies
        self._flood_order: deque = deque()          # whose held reply goes out next, one person at a time
        self._flood_feeding = False
        self._ctcp_answer: tuple | None = None      # (folded nick, own) while a CTCP reply-list command answers them
        self._queue: list[str] = []
        self._next_send = 0.0
        self._typed = 0              # 0.8.5: >0 while the user's own input is handled: sent at once, never queued
        self._oper_wait: tuple | None = None    # 0.8.5: (tab, time) where /oper was typed: the 381 answer goes there
        self._queue_timer = QTimer(self, interval=500)
        self._queue_timer.timeout.connect(self._drain_queue)

        self._special_socket = False
        self._socks4 = ""            # 0.8.8: "socks4" / "socks4a" when Network setup uses one (BChat talks it itself)
        self._socks: dict | None = None   # ... the handshake under way: target host, port, SSL, step
        self._uh_typed: list = []    # 0.8.8 /userhost: (buffer, nicks asked (folded), when) per USERHOST typed
        self.on_dcc = None           # the DCC manager
        self.dcc_say = None
        self.server_hook = None      # plugins
        self.print_hook = None
        self.external_ip = ""
        self.local_name = ""               # Network > Local: the host name found for external_ip
        self._local_waiting = 0
        self.userip = False
        self._userhost_waiting = 0
        self.on_command = None       # the main window's way to run a typed-style command
        self.list_sink = None        # Channel List window while it wants 322/323
        self.ban_sinks: dict = {}    # channel -> Ban List window
        self.friend_state: dict[str, dict] = {}
        self._ison_asked: deque = deque()   # 0.8.5: per ISON sent, the friends it asked about (None = typed by the user)
        self._replaying = False      # 0.8.5: lines a bouncer plays back: shown and counted, no sound/flash/tray/pop-up
        self._pings_out: dict = {}   # 0.8.5: (nick, CTCP PING argument) -> when it went out, for replies in ms
        self._monitor = False
        self._watch = False          # 0.6.0: no MONITOR but WATCH (UnrealIRCd and others): Friends List uses it
        self.extban = ("", "")       # 0.6.0: ISUPPORT EXTBAN=~,a... -> ("~", "a..."): /ban -a account bans
        self._trust_once = ""      # a certificate fingerprint the user said Connect Once to
        self._friends_timer = QTimer(self)
        self._friends_timer.timeout.connect(self.poll_friends)
        self._friends_wait = 0       # 0.6.0: >0 = waiting for 005 (end of MOTD) before Friends tracking picks MONITOR/WATCH/ISON
        self._new_socket()

        self._reconnect = QTimer(self, singleShot=True)
        self._reconnect.timeout.connect(self._connect_next)
        self._dial = QTimer(self, singleShot=True)       # 0.8.5: Connect time-out (Preferences > Advanced)
        self._dial.timeout.connect(self._dial_timed_out)
        # 0.8.2 connect/disconnect: one number per connection attempt, so a timer from an old link does nothing
        self._conn_gen = 0
        self._performed = self._joins_sent = False   # NickServ/commands/joins done for this link
        self._ns_wait = 0                 # >0 = joins wait for NickServ (ticket = _conn_gen)
        self._sasl_ok = False
        self._killed = self._banned = False
        self._tries = 0                   # reconnect tries since the link was last up
        self._down_since = 0.0            # when the link dropped by itself (for "Back after X")
        self._drop_why = ""
        # 0.8.5 reconnect: away message to send again, channels we left (never rejoined), keys of our JOINs,
        # a /nick typed while offline, tabs told "Disconnected" this outage, a bouncer rejoin waiting on its timer
        self._away_msg = ""
        self._left: set[str] = set()
        self._join_keys: dict[str, str] = {}
        self._next_nick = ""
        self._told_down: list[Buffer] = []
        self._nick_cut = 0
        self._keepalive = QTimer(self, interval=15000)
        self._keepalive.timeout.connect(self._tick)
        self._who = QTimer(self, interval=120000)
        self._who.timeout.connect(self._poll_who)

    # --- identity ------------------------------------------------------------

    def _identity(self, field_name: str) -> str:
        """Per-network value unless the network says "use global"."""
        n, c = self.net, self.cfg
        if field_name == "nick":
            return (n.nick if not n.use_global else "") or c.nick or n.nick
        if field_name == "nick2":
            return (n.nick2 if not n.use_global else "") or c.nick2
        if field_name == "user":
            return (n.username if not n.use_global else "") or n.username or c.username or "bchat"
        return (n.realname if not n.use_global else "") or n.realname or c.realname or "BChat user"

    @property
    def prefix_order(self) -> str:
        return self.prefix_chars

    # --- buffers ---------------------------------------------------------------

    def is_channel(self, name: str) -> bool:
        return bool(name) and name[0] in self.chantypes

    def buffer(self, name: str, create: bool = True) -> Buffer | None:
        key = self.fold(name)
        b = self.buffers.get(key)
        if b is None and create:
            b = Buffer(self, name, CHANNEL if self.is_channel(name) else QUERY)
            self.buffers[key] = b
            if b.kind == QUERY and self.cfg.single_msg_copy and not name.startswith(("(", "=")):
                self._copy_from_messages(b)
            self.buffer_added.emit(b)
        return b

    # --- 0.8.6: one (messages) tab for private messages ------------------------------------

    MESSAGES = "(messages)"     # brackets: never a nick, like (notices)

    def to_messages(self, nick: str) -> bool:
        """A private message from nick goes to (messages): the option is on and no private chat with them is open."""
        c = self.cfg
        if not c.single_msg_window or not nick or self.fold(nick) in self.buffers:
            return False
        if c.single_msg_friends and any(self.fold(n) == self.fold(nick) for n in self._friends_here()):
            return False
        return True

    def _into_messages(self, m: Message, dest: str, text: str, ts: float, from_me: bool, quiet: bool) -> None:
        """A private line (or /me) for a nick without a private chat, while the (messages) tab option is on."""
        if from_me and "echo-message" in self._cap_active and not self._replaying:
            return                       # our own /msg: msg() already showed '>nick< text' where we typed it
        b = self.buffer(self.MESSAGES)
        msgid = m.tags.get("msgid", "")
        action = text.startswith("\x01ACTION")
        body = text.strip("\x01").removeprefix("ACTION").removeprefix(" ") if action else text
        if from_me:                      # from another client on the bouncer, or played back
            if action:
                self.add(b, ACTION, "*", f"{self.nick} → {dest}: {body}", ts, msgid=msgid)
            else:
                self.add(b, SELF, f">{dest}<", body, ts, msgid=msgid)
            return
        hit = not quiet and self._is_hilite(body, m.nick, b.name)
        if self.print_hook is not None and not action and self.print_hook("Private Message to Dialog", (m.nick, body)):
            return
        if action:
            self.add(b, ACTION if quiet else HILITE, "*", f"{m.nick} {body}", ts,
                     colour=self._hilite_colour() if hit else "", msgid=msgid)
        else:
            self.add(b, MSG if quiet else HILITE, m.nick, body, ts, colour=self._hilite_colour() if hit else "", msgid=msgid)
        self._bump(b, 2 if quiet else 3)
        if not quiet:
            self._notify(b, "priv")

    def _copy_from_messages(self, b: Buffer) -> None:
        """'Copy messages to query': what that nick and I said in (messages) goes to the top of their new tab."""
        src = self.buffers.get(self.fold(self.MESSAGES))
        if src is None:
            return
        who = self.fold(b.name)
        for ln in src.lines:
            left = self.fold(strip_format(ln.left))
            words = strip_format(ln.text).split(" ", 3)
            if ln.kind in (MSG, HILITE) and left == who \
                    or ln.kind == SELF and left == self.fold(f">{b.name}<") \
                    or ln.kind in (ACTION, HILITE) and left == "*" and (
                        self.fold(words[0]) == who
                        or len(words) > 2 and words[1] == "→" and self.fold(words[2].rstrip(":")) == who):
                b.lines.append(Line(ln.kind, ln.left, ln.text, ln.ts, colour=ln.colour, msgid=ln.msgid))

    def close_buffer(self, b: Buffer) -> None:
        if b.kind == CHANNEL and b.joined and self.state == "connected":
            self.send("PART", b.name, self.cfg.part_reason)
        if b.kind == CHANNEL:
            self._left.add(self.fold(b.name))     # 0.8.5: a closed channel isn't joined again on reconnect
        self.buffers.pop(self.fold(b.name), None)
        self.buffer_removed.emit(b)

    def all_buffers(self) -> list[Buffer]:
        return [self.server_buffer, *self.buffers.values()]

    def add(self, b: Buffer, kind: str, left: str, text: str, ts: float | None = None, colour: str = "",
            msgid: str = "", reply_to: str = "", hidden: bool = False) -> None:
        line = Line(kind, left, text, ts if ts is not None else time.time(), colour=colour, msgid=msgid, reply_to=reply_to,
                    hidden=hidden)
        if b.kind == CHANNEL and kind in (MSG, SELF, HILITE) and left and left[0] not in "<>-":
            u = b.users.get(self.fold(left))
            if u is not None:
                from .userlist import icon_name
                line.rank = icon_name(self.prefix_order, u.prefixes) or ""
        b.lines.append(line)
        cap = max(100, self.cfg.max_lines or self.MAX_LINES)
        if len(b.lines) > cap:
            del b.lines[: len(b.lines) - cap]
        self.line_added.emit(b, line)

    def _front(self) -> Buffer:
        if self._route is not None:
            return self._route
        return self.current if self.current is not None and self.current.session is self else self.server_buffer

    # --- 0.8.7: Settings > Windows > Where events show -----------------------------------------
    active_window = None     # set by the main window: () -> the focused chat tab, on any server

    def _active_window(self) -> tuple[Buffer, str]:
        """The focused chat window and the prefix for a line from here; one on another server gets '[Network] '."""
        if self._route is not None:
            return self._route, ""
        b = self.active_window() if self.active_window is not None else None
        if b is None or getattr(b, "session", None) is None:
            return self._front(), ""
        if b.session is self:
            return b, ""
        return self.server_buffer, ""     # another server's window has focus: this server's tab, as before 0.8.7

    def _show_where(self, event: str, nick: str = "", default: Buffer | None = None) -> tuple[Buffer, str]:
        """Where an event's line goes, by the user's choice for it (cfg.show_<event>), with its prefix."""
        where = getattr(self.cfg, "show_" + event, "active")
        if where == "query" and nick:
            q = self.buffers.get(self.fold(nick))
            if q is not None and q.kind == QUERY:
                return q, ""
        elif where == "server":
            return self.server_buffer, ""
        elif where == "messages":
            return self.buffer(self.MESSAGES), ""
        if default is not None:
            return default, ""
        return self._active_window()

    def add_to(self, b: Buffer, kind: str, left: str, text: str, prefix: str = "", **kw) -> None:
        """add(), on the session that owns b (a line shown in another server's window)."""
        owner = b.session if getattr(b, "session", None) is not None else self
        owner.add(b, kind, left, prefix + text if prefix else text, **kw)

    def send_labeled(self, b: Buffer, line: str) -> None:
        """A raw line the user typed: with labeled-response its answer comes back to tab b."""
        if "labeled-response" in self._cap_active and self.state == "connected" and not line.startswith("@"):
            self._label_n = getattr(self, "_label_n", 0) + 1
            label = f"bc{self._label_n}"
            now = time.time()
            self._labels = {k: v for k, v in self._labels.items() if now - v[1] < 120}
            self._labels[label] = (b, now)
            if line[:5].upper() == "OPER ":
                self._oper_wait = (b, now)
            self.send_raw(f"@label={label} {line}")
            return
        if line[:5].upper() == "OPER ":
            self._oper_wait = (b, time.time())      # 0.8.5: the 381 answer shows in the tab where /oper was typed
        self.send_raw(line)

    def clear_buffer(self, b: Buffer) -> None:
        b.lines.clear()
        b.marker = None
        self.buffer_changed.emit(b)

    # --- connecting -----------------------------------------------------------

    def _new_socket(self) -> None:
        old = getattr(self, "sock", None)
        if old is not None:
            old.blockSignals(True)
            old.abort()
            old.deleteLater()
        if self._ws_path:
            from .wsock import WsSocket
            self.sock = WsSocket(self, self._ws_path)
        else:
            self.sock = QSslSocket(self)
        self.sock.connected.connect(self._on_tcp)
        self.sock.encrypted.connect(self._on_tls)
        self.sock.readyRead.connect(self._on_read)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.errorOccurred.connect(self._on_socket_error)
        self.sock.sslErrors.connect(self._on_ssl_errors)

    def _apply_network_settings(self) -> bool:
        """Preferences > Network setup. A failed bind is reported, and the connection still goes out normally,
        unless 'If this address is gone, don't connect at all' is ticked (VPN users): then False = don't connect."""
        c = self.cfg
        kinds = {"socks5": QNetworkProxy.ProxyType.Socks5Proxy, "http": QNetworkProxy.ProxyType.HttpProxy}
        # 0.8.8: Qt has no Socks4: BChat dials the proxy itself and talks Socks4 / 4a before the IRC login
        direct = skips_proxy(c.proxy_skip, getattr(self, "_dial_host", ""))
        self._socks4 = c.proxy_type if c.proxy_type in ("socks4", "socks4a") and c.proxy_host and not direct else ""
        use_proxy = (c.proxy_type in kinds and bool(c.proxy_host) and not direct) or bool(self._socks4)
        # QSslSocket's inner socket keeps its old proxy and bound address, so these need a clean socket
        if use_proxy or c.bind_host or self._special_socket:
            self._new_socket()
        self._special_socket = use_proxy or bool(c.bind_host)
        if self._socks4:
            if self._ws_path:
                self.add(self.server_buffer, ERROR, "*", "A Socks4 proxy can't carry a WebSocket connection, so BChat "
                                                          "didn't connect. Use Socks5 or HTTP (Preferences > Network setup).")
                return False
            self.sock.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
            if c.bind_host:
                self.add(self.server_buffer, INFO, "*", f"Using the proxy, so the address {c.bind_host} isn't used.")
            return True
        if use_proxy:
            p = QNetworkProxy(kinds[c.proxy_type], c.proxy_host, c.proxy_port)
            if c.proxy_auth:
                p.setUser(c.proxy_user)
                p.setPassword(c.proxy_password)
            self.sock.setProxy(p)
            if c.bind_host:
                self.add(self.server_buffer, INFO, "*", f"Using the proxy, so the address {c.bind_host} isn't used.")
            return True
        self.sock.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        if c.bind_host and not self.sock.bind(QHostAddress(c.bind_host)):
            if c.bind_strict:
                self.add(self.server_buffer, ERROR, "*", f"Your bind address {c.bind_host} is gone (VPN off?): "
                                                          "not connecting, as you asked (Preferences > Network setup).")
                return False
            self.add(self.server_buffer, ERROR, "*", f"Couldn't use the address {c.bind_host}: {self.sock.errorString()}")
            self._new_socket()
            self.sock.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        return True

    def connect_to_network(self) -> None:
        self.want_connected = True
        self.server_index = -1
        self._ports_left, self._repeat = [], False
        self._connect_next()

    def _pick_server(self) -> tuple[Server, int]:
        """The server and port for this try: the same again after _repeat, else the next untried port of this
        server (host/+6697,7000 tries them in random order), else the next server in the list."""
        if self._repeat and 0 <= self.server_index < len(self.net.servers):
            self._repeat = False
            return self.net.servers[self.server_index], self._cur_port
        self._repeat = False
        if self._ports_left and 0 <= self.server_index < len(self.net.servers):
            self._cur_port = self._ports_left.pop(0)
            return self.net.servers[self.server_index], self._cur_port
        self.server_index = (self.server_index + 1) % len(self.net.servers) if self.net.cycle else 0
        s = self.net.servers[self.server_index]
        ports = [s.port] + [p for p in s.more_ports if p != s.port]
        if len(ports) > 1:
            random.shuffle(ports)
        self._cur_port, self._ports_left = ports[0], ports[1:]
        return s, self._cur_port

    def _connect_next(self) -> None:
        if not self.net.servers:
            self.want_connected = False
            self.add(self.server_buffer, ERROR, "*", "This tab has no server yet. Type /server <host> [port or +port for SSL].")
            return
        s, picked = self._pick_server()
        if s.ws_plain:
            self.want_connected = False
            self.add(self.server_buffer, ERROR, "*", f"ws://{s.host} isn't encrypted, so BChat won't connect to it. "
                                                     "Use wss:// in Edit Network.")
            return
        self._ws_path = s.ws_path
        self._dial_host = s.host                   # 0.8.10: Proxy Server > Not for: is matched against it
        self._set_state("connecting")
        self.ircd_version = ""
        self._buf = b""
        self._rx.clear()
        self._welcomed = False
        self._conn_gen += 1
        self._performed = self._joins_sent = False
        self._ns_wait = 0
        self._sasl_ok = False
        self._killed = False
        self._drop_why = ""
        self._friends_wait = 0
        self._cap_active = set()
        self.nick_attempt = 0
        self.nick = self._next_nick or self._identity("nick") or random_nick()   # 0.8.5: a /nick typed while offline
        self._nick_cut = 0                        # 0.8.5: the nick length this server cuts to, once a 433 shows it
        self._new_socket()                        # a WebSocket server and a normal one need different sockets
        if not self._apply_network_settings():
            return self._stop_bind()
        self._queue.clear()
        self.flood_clear()                        # 0.8.5: replies held for the last link are not sent on this one
        self._next_send = 0.0
        self.lag_ms = None
        self._ping_sent = 0.0
        self.away = False
        self.whox = False
        self.userip = False
        self.statusmsg = ""
        self._monitor, self._watch, self.extban = False, False, ("", "")
        self.chathistory_max = -1
        self._history = {}
        self.prefix_modes, self.prefix_chars = "ohv", "@%+"
        self.modes_list, self.modes_key, self.modes_on_set, self.max_modes = "beI", "k", "fjl", 3
        self.modes_flags, self.client_tag_deny = "imnpst", ""
        self._sasl_state = ""
        self._cap_more = set()
        self._cap_offered = {}
        self._cap_pending = 0
        self.server_name = ""
        self.network_token = ""
        self.bouncer, self.bouncer_version, self._bouncer_said, self._version_wait = "", "", False, 0.0
        self._znc_guess = False
        self._playback, self._znc_collect = {}, None
        self.online_since, self.motd_asked = 0.0, False
        self.services, self.services_guessed, self._services_wait = "", False, []
        self._cert_loaded = False
        self._starttls = "waiting" if s.starttls and not s.ssl else ""
        self._scram = None
        self._sasl_mech = ""
        self._labels: dict[str, tuple] = {}     # label -> (buffer, when): labeled-response
        self._label_batches: dict[str, object] = {}
        self._route = None
        host, port, tls = s.host, picked, s.ssl
        policy = self.cfg.sts.get(host.lower()) if not s.ws_path else None
        self._sts_enforced = bool(policy and policy.get("expires", 0) > time.time())
        if self._sts_enforced and not tls:
            port, tls = int(policy["port"]), True
            self.add(self.server_buffer, INFO, "*", f"{host} requires secure connections (STS), using SSL port {port}")
        self._tls_now = tls
        if self._starttls and not self._sts_enforced:
            self._new_socket()                    # SSL settings start clean, the switch happens after STARTTLS
            if not self._apply_network_settings():
                return self._stop_bind()
        elif self._starttls:
            self._starttls = ""                   # STS already moved us to a real SSL port
        if tls:
            # a fresh socket: Qt keeps an "ignore certificate errors" from an earlier connection on the old one,
            # and Connect Once must not carry over to the next connection
            self._new_socket()
            if not self._apply_network_settings():
                return self._stop_bind()
            self._use_client_cert()
        elif self.net.login == "cert":
            self.add(self.server_buffer, ERROR, "*", "Certificate login needs an SSL server (+port in Edit Network). "
                                                     "Connecting without it.")
        if s.ws_path:
            shown = f"wss://{host}{'' if port == 443 else f':{port}'}{s.ws_path}"
            self.add(self.server_buffer, CONNECT, "*", f"Connecting to {shown} (WebSocket over SSL)...")
        else:
            many = [s.port] + list(s.more_ports)
            picked_from = f", picked from {', '.join(map(str, many))}" if len(many) > 1 else ""
            self.add(self.server_buffer, CONNECT, "*", f"Connecting to {host} ({'SSL ' if tls else ''}port {port}{picked_from})...")
        proto = {"ipv4": QAbstractSocket.NetworkLayerProtocol.IPv4Protocol,
                 "ipv6": QAbstractSocket.NetworkLayerProtocol.IPv6Protocol}.get(
            self.cfg.ip_mode, QAbstractSocket.NetworkLayerProtocol.AnyIPProtocol)
        mode = QAbstractSocket.OpenModeFlag.ReadWrite
        self._dial_host = host
        self._socks = None
        self._ident_start()
        if self.cfg.connect_timeout > 0:
            self._dial.start(self.cfg.connect_timeout * 1000)
        if self._socks4:
            # 0.8.8: a plain link to the proxy first; Socks4 then reaches the server, and SSL starts after that
            self._socks = {"host": host, "port": port, "tls": tls, "step": "dial", "got": b""}
            self._dial_host = self.cfg.proxy_host
            self.sock.connectToHost(self.cfg.proxy_host, self.cfg.proxy_port, mode, proto)
        elif tls:
            self.sock.connectToHostEncrypted(host, port, mode, proto)
        else:
            self.sock.connectToHost(host, port, mode, proto)

    # --- 0.8.8: ident server while connecting ----------------------------------------------------------

    def _ident_start(self) -> None:
        if not self.cfg.identd_on:
            return self._ident_stop()
        from . import identd
        why = identd.shared().acquire(self, self.cfg.identd_user or self._identity("user"))
        if why:
            self.add(self.server_buffer, INFO, "*", f"Ident is off: port {identd.PORT} is in use or blocked ({why}). "
                                                    "Connecting anyway.")
            return
        if getattr(self, "_ident_timer", None) is None:
            self._ident_timer = QTimer(self, singleShot=True)
            self._ident_timer.timeout.connect(self._ident_stop)
        self._ident_timer.start(identd.HOLD_S * 1000)

    def _ident_stop(self) -> None:
        """Welcome, a failed try or 60 seconds: this connection no longer needs the ident server."""
        timer = getattr(self, "_ident_timer", None)
        if timer is not None:
            timer.stop()
        from . import identd
        if identd._shared is not None:
            identd._shared.release(self)

    # --- 0.8.8: Socks4 / Socks4a ------------------------------------------------------------------------

    SOCKS4_REFUSED = {0x5B: "the proxy refused or couldn't make the connection",
                      0x5C: "the proxy couldn't check who you are (it asks this PC's ident server, which didn't answer)",
                      0x5D: "the proxy's ident check didn't match the user ID BChat sent"}

    def _socks_connected(self) -> None:
        """Connected to the proxy: ask it for the IRC server. Socks4 needs the server's IPv4 address, 4a lets the
        proxy look the name up."""
        st = self._socks
        host = st["host"]
        literal = QHostAddress(host)
        if self._socks4 == "socks4a" and literal.isNull():
            return self._socks_request("0.0.0.1", host)
        if not literal.isNull():
            return self._socks_request(host, "")
        gen = self._conn_gen
        st["step"] = "lookup"
        look_up(self, host, lambda info, g=gen: self._socks_looked_up(info, g))

    def _socks_looked_up(self, info, gen: int) -> None:
        if gen != self._conn_gen or not self._socks or self._socks["step"] != "lookup":
            return
        v4 = [a.toString() for a in info.addresses() if a.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol]
        if not v4:
            why = "wasn't found" if not info.addresses() else "has no IPv4 address, and Socks4 can't reach IPv6"
            return self._socks_failed(f"{self._socks['host']} {why}. Socks4a lets the proxy look names up "
                                      "(Preferences > Network setup).")
        self._socks_request(v4[0], "")

    def _socks_request(self, ip: str, name: str) -> None:
        st = self._socks
        a = QHostAddress(ip)
        if a.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
            return self._socks_failed(f"{ip} is an IPv6 address, and Socks4 can only reach IPv4 addresses.")
        user = self.cfg.proxy_user.strip().encode("utf-8", "replace").replace(b"\0", b"")
        req = struct.pack(">BBHI", 4, 1, st["port"], a.toIPv4Address()) + user + b"\0"
        if name:
            req += name.encode("idna") + b"\0"
        st["step"] = "reply"
        self.sock.write(req)

    def _socks_reply(self) -> None:
        st = self._socks
        st["got"] += bytes(self.sock.readAll())
        if len(st["got"]) < 8:
            return
        head, rest = st["got"][:8], st["got"][8:]
        code = head[1]
        if code != 0x5A:
            why = self.SOCKS4_REFUSED.get(code, f"the proxy answered with an unknown code {code:#04x}")
            return self._socks_failed(f"Socks4 proxy {self.cfg.proxy_host}: {why} (code {code:#04x}).")
        host, tls = st["host"], st["tls"]
        self._socks = None
        self._dial_host = host
        self.add(self.server_buffer, CONNECT, "*", f"The proxy reached {host}.")
        if tls:
            self.sock.setPeerVerifyName(host)        # the certificate must be the server's, not the proxy's
            self.sock.startClientEncryption()
        self._on_tcp()
        if rest and not tls:                         # the server already spoke: those lines go the normal way
            self._buf += rest
            self._on_read()

    def _socks_failed(self, why: str) -> None:
        self._socks = None
        self.add(self.server_buffer, ERROR, "*", why)
        self.sock.abort()
        self._on_disconnected()

    def _dial_timed_out(self) -> None:
        """No answer to the connect in time: give up on this server and go on as for any failed try."""
        if self.state != "connecting" or (self.sock.state() == QAbstractSocket.SocketState.ConnectedState
                                          and not self._socks):
            return
        self.add(self.server_buffer, ERROR, "*", f"No answer from {self._dial_host} after {self.cfg.connect_timeout} seconds.")
        self.sock.abort()
        self._on_disconnected()

    def _stop_bind(self) -> None:
        self.want_connected = False
        self._set_state("disconnected")

    def connect_manual(self, host: str, port: int, ssl: bool, password: str = "") -> None:
        """/server: leave whatever this tab was doing and go to this server, with the global nick and no saved login."""
        self._reconnect.stop()
        self.want_connected = False
        if self.state == "connected":
            self.send_raw(build_line("QUIT", self.cfg.quit_reason))
            self.sock.flush()
        self._set_state("disconnected")
        self._keepalive.stop()
        self._who.stop()
        self.sock.abort()
        for b in list(self.buffers.values()):  # those channels belong to the old server
            self.buffers.pop(self.fold(b.name), None)
            self.buffer_removed.emit(b)
        self._left.clear()
        self.net = NetworkConfig(host, [Server(host, port, ssl)], password=password, cycle=False)
        self.typed_by_hand = True
        self.server_buffer.name = host
        self.buffer_changed.emit(self.server_buffer)
        self.connect_to_network()

    def _login_refused(self, text: str) -> None:
        """A wrong login won't fix itself, so don't keep hammering the server with it."""
        self.want_connected = False
        self._reconnect.stop()
        self.add(self.server_buffer, ERROR, "*", f"{text}. The server refused this login, so BChat will not retry. "
                                                  "Check User name and Server password in Network List > Edit, then use Server > Reconnect.")

    def disconnect_from_network(self, reason: str | None = None) -> None:
        self.want_connected = False
        self._reconnect.stop()
        self._tries, self._down_since, self._banned = 0, 0.0, False
        if self.state == "connected":
            self.send("QUIT", reason if reason is not None else self.cfg.quit_reason)
            self.sock.flush()
            self.sock.disconnectFromHost()
        else:
            self.sock.abort()
            self._set_state("disconnected")

    def reconnect(self) -> None:
        self._reconnect.stop()
        was_live = self.sock.state() != QAbstractSocket.SocketState.UnconnectedState
        self.want_connected = True
        self._tries, self._banned = 0, False
        if was_live:
            self.sock.abort()
        self._repeat = self.server_index >= 0 and self._cur_port > 0
        self._connect_next()

    def current_lag_ms(self) -> int | None:
        """The last measured lag, or how long the current ping has waited if that is already longer."""
        waiting = int((time.time() - self._ping_sent) * 1000) if self._ping_sent else 0
        if self.lag_ms is None and not waiting:
            return None
        return max(self.lag_ms or 0, waiting)

    def _set_state(self, st: str) -> None:
        self.state = st
        if st != "connected":
            self._set_oper(False)               # 0.9.3: a lost link or a new one is never an oper link
            self.wallops_on = False
        self.state_changed.emit()

    def _set_oper(self, on: bool) -> None:
        """0.9.3 Oper tools: the server says we are (381 / +o) or are no more (-o / link gone) an IRC operator."""
        on = bool(on)
        if on == self.is_oper:
            return
        self.is_oper = on
        if on and self.cfg.addon_oper:
            if self.cfg.oper_notices:
                self.buffer("(notices)")             # the Server notices tab shows up under the network
            more = "; server notices go to their own tab." if self.cfg.oper_notices else "."
            self.add(self.server_buffer, INFO, "*", f"14BChat: you're an IRC operator on {self.net.name}. The Oper menu is on{more}")
        self.oper_changed.emit()

    def _use_client_cert(self) -> None:
        """Log in with: Certificate. The certificate goes in the SSL handshake; the key stays on this PC."""
        if self.net.login != "cert":
            return
        from . import certs
        pair = certs.load(self.net.cert_file)
        if pair is None:
            self.add(self.server_buffer, ERROR, "*", "Certificate login: BChat couldn't read the certificate file. "
                                                     "Edit Network > Make New or Choose File.")
            return
        self.sock.setLocalCertificate(pair[0])
        self.sock.setPrivateKey(pair[1])
        self._cert_loaded = True

    def _on_tcp(self) -> None:
        if self._socks and self._socks["step"] == "dial":       # 0.8.8: reached the Socks4 proxy, not the server yet
            self.add(self.server_buffer, CONNECT, "*", f"Connected to the proxy. Asking it for {self._socks['host']}...")
            return self._socks_connected()
        self._dial.stop()
        if self._starttls == "waiting" and not self._tls_now:
            self.add(self.server_buffer, CONNECT, "*", "Connected. Asking the server to switch to SSL (STARTTLS)...")
            self.send_raw("STARTTLS")
            return
        self.add(self.server_buffer, CONNECT, "*", "Connected. Now logging in..." if not self._tls_now else "Connected. Starting SSL...")
        if not self._tls_now:
            self._login()

    def _starttls_answer(self, n: int, m: Message) -> bool:
        """670 = switch now; anything else while waiting = the server can't. Never falls back to plain."""
        if self._starttls != "waiting":
            return False
        if n == 670:
            self._starttls = "tls"
            self._tls_now = True
            self._use_client_cert()
            self.sock.startClientEncryption()
            return True
        if n in (691, 421, 451, 461, 462) or 400 <= n < 600:
            self._starttls = ""
            self.want_connected = False
            self._reconnect.stop()
            self.add(self.server_buffer, ERROR, "*", "This server can't switch to SSL (STARTTLS), so BChat didn't connect: "
                                                     "it never falls back to a plain connection. Use an SSL port (/+port) instead.")
            self.sock.abort()
            self._set_state("disconnected")
            return True
        return False

    def _on_tls(self) -> None:
        c = self.sock.sessionCipher()
        self.add(self.server_buffer, INFO, "SSL", f"Protocol: {c.protocolString()}  Cipher: {c.name()}")
        cert = self.sock.peerCertificate()
        if not cert.isNull():
            def dn(names):
                return ", ".join(f"{k}={v[0]}" for k, v in (("C", names(cert.SubjectInfo.CountryName)),
                                 ("O", names(cert.SubjectInfo.Organization)), ("CN", names(cert.SubjectInfo.CommonName))) if v)
            self.add(self.server_buffer, INFO, "SSL",
                     f"Issuer: {dn(cert.issuerInfo)}   Subject: {dn(cert.subjectInfo)}")
        if self._starttls == "tls":
            self.add(self.server_buffer, INFO, "*", "Switched to SSL on the same port (STARTTLS).")
        self.add(self.server_buffer, CONNECT, "*", "Now logging in...")
        self._login()

    def _on_ssl_errors(self, errors) -> None:
        """A certificate BChat can't verify. Trusted before (Always Trust, or once): connect. An older network set to
        accept invalid certificates: remember this one (trust on first use) and connect. Anything else: ask."""
        names = ", ".join(e.errorString() for e in errors)
        cert = next((e.certificate() for e in errors if not e.certificate().isNull()), self.sock.peerCertificate())
        fp = bytes(cert.digest(QCryptographicHash.Algorithm.Sha256)).hex() if not cert.isNull() else ""
        if self._sts_enforced:
            self.add(self.server_buffer, ERROR, "*", f"Server certificate rejected: {names}. This server requires a valid certificate (STS).")
            return
        if fp and (fp in self.net.cert_pins or fp == self._trust_once):
            self._trust_once = ""
            self.add(self.server_buffer, INFO, "*", "Using the certificate you chose to trust.")
            self.sock.ignoreSslErrors()
            return
        if fp and self.net.allow_invalid_cert and not self.net.cert_pins:
            self.net.cert_pins.append(fp)
            self.pins_changed.emit()
            self.add(self.server_buffer, INFO, "*", f"Accepting this server's certificate ({names}) and remembering it: "
                                                    "if it ever changes, BChat will ask first.")
            self.sock.ignoreSslErrors()
            return
        # ask: no retries meanwhile, the handshake fails and the window shows the question
        self.want_connected = False
        self._reconnect.stop()
        changed = bool(self.net.cert_pins)
        self.add(self.server_buffer, ERROR, "*", ("The server's certificate CHANGED since you trusted it: " if changed
                                                  else "Server certificate not trusted: ") + f"{names}. Asking you what to do.")
        def first(names_list):
            return names_list[0] if names_list else ""
        info = {"host": self.net.servers[self.server_index].host if self.net.servers else "", "network": self.net.name,
                "reasons": [e.errorString() for e in errors], "fingerprint": fp, "changed": changed,
                "self_signed": cert.issuerDisplayName() == cert.subjectDisplayName() if not cert.isNull() else False,
                "subject": first(cert.subjectInfo(QSslCertificate.SubjectInfo.CommonName)) if not cert.isNull() else "",
                "issuer": first(cert.issuerInfo(QSslCertificate.SubjectInfo.CommonName))
                          or first(cert.issuerInfo(QSslCertificate.SubjectInfo.Organization)) if not cert.isNull() else "",
                "expires": cert.expiryDate().toString("d MMM yyyy") if not cert.isNull() else ""}
        QTimer.singleShot(0, lambda: self.cert_question.emit(info))

    def answer_certificate(self, fp: str, choice: str) -> None:
        """The user's answer: "no", "once" (this connection only) or "always" (remember it for this network)."""
        if choice == "no":
            self.add(self.server_buffer, INFO, "*", "Not connected: you chose not to trust the certificate.")
            return
        if choice == "always":
            if fp not in self.net.cert_pins:
                self.net.cert_pins = [fp]        # replaces an old one that changed
            self.pins_changed.emit()
        else:
            self._trust_once = fp
        self.want_connected = True
        self._repeat = True                      # the same server and port again, not the next in the list
        self._connect_next()

    def _login(self) -> None:
        self._set_state("registering")
        self._last_rx = time.time()
        self._keepalive.start()
        self.send_raw("CAP LS 302")
        if self.net.password:
            self.send_raw(f"PASS {self.net.password}", secret=True)
        self.send("NICK", self.nick)
        self.send("USER", self._identity("user"), "0", "*", self._identity("real"))

    READ_SLICE_S = 0.03     # 0.6.1: work through incoming lines 30 ms at a time, so a burst doesn't freeze the window

    def _on_read(self) -> None:
        if self._socks:                       # 0.8.8: the Socks4 proxy's answer comes before any IRC line
            return self._socks_reply()
        self._buf += bytes(self.sock.readAll())
        *lines, self._buf = self._buf.split(b"\n")
        self._rx.extend(lines)
        if not self._drain_queued:             # a slice is already booked: new lines just join the queue
            self._drain()

    def _drain(self, everything: bool = False) -> None:
        """Lines in arrival order. After READ_SLICE_S the rest waits for the next turn of the event loop (paint,
        typing, other networks), so 5000 lines at once no longer stop the whole window. Nested calls (a handler
        that runs the event loop) carry on from the same queue, so order is kept."""
        self._drain_queued = False
        end = time.perf_counter() + self.READ_SLICE_S
        rx = self._rx
        while rx:
            if not everything and time.perf_counter() > end:
                if not self._drain_queued:
                    self._drain_queued = True
                    QTimer.singleShot(1, self, self._drain)      # 1 ms, not 0: Windows starves other timers on 0; self as context: no call once the session is gone
                return
            raw = rx.popleft()
            text = self._decode(raw).rstrip("\r")
            if text:
                self._last_rx = time.time()
                m = parse_line(text)
                # echo-message: our own 'identify pw' comes back from the server; the Raw Log must not show it
                echo = "echo-message" in self._cap_active and m.command in ("PRIVMSG", "NOTICE") and self.fold(m.nick) == self.fold(self.nick) and self.is_secret(text)
                self.raw_line.emit(self._hide_secret(text) if echo else text, False)
                try:
                    if self.server_hook is not None and self.server_hook(self, text, m.command):
                        continue
                    self._handle(m)
                except Exception:
                    # 0.8.5: a line BChat can't handle is reported (console / problem report) and skipped;
                    # the rest of the batch still goes through
                    sys.excepthook(*sys.exc_info())

    @staticmethod
    def _decode(raw: bytes) -> str:
        """UTF-8, else the Windows default cp1252 (it’s €), else latin-1 for the few bytes cp1252 leaves out."""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    def _on_socket_error(self, err) -> None:
        if err == QAbstractSocket.SocketError.RemoteHostClosedError:
            self._drop_why = self._drop_why or "closed by the server"
            return
        if self._welcomed and not self._drop_why:
            self._drop_why = self.sock.errorString().rstrip(".").lower()
        self.add(self.server_buffer, ERROR, "*", f"Connection failed: {self.sock.errorString()}")
        host = getattr(self, "_dial_host", "")
        if err == QAbstractSocket.SocketError.HostNotFoundError and self.cfg.ip_mode in ("ipv4", "ipv6") and host:
            # 0.6.1: 'Host not found' also means 'no address of the one kind we may use'. Ask again for any kind
            # of address, then say which it is (and only then call it a typo).
            if not getattr(self, "_family_wired", False):
                self.family_info.connect(self._family_found)
                self._family_wired = True
            self._family_asked = (host, self.typed_by_hand)
            literal = QHostAddress(host)
            if not literal.isNull():                     # an address typed in: its kind is plain to see
                info = QHostInfo()
                info.setHostName(host)
                info.setAddresses([literal])
                self._family_found(info)
            else:
                look_up(self, host, lambda info: self.family_info.emit(info))
        elif err == QAbstractSocket.SocketError.HostNotFoundError and self.typed_by_hand:
            self._typo_stop()
        if self.sock.state() == QAbstractSocket.SocketState.UnconnectedState:
            self._on_disconnected()

    def _typo_stop(self) -> None:
        # probably a typo, so retrying won't help. Saved networks do retry: their name resolved before, and DNS can blip
        self.want_connected = False
        self._reconnect.stop()
        self.add(self.server_buffer, ERROR, "*", "That server name wasn't found, so BChat will not retry. Check the spelling and use /server again.")

    def _family_found(self, info) -> None:
        host, by_hand = getattr(self, "_family_asked", ("", False))
        if not host or info.hostName().lower() != host.lower():
            return
        self._family_asked = ("", False)
        v6 = QAbstractSocket.NetworkLayerProtocol.IPv6Protocol
        kinds = {"IPv6" if a.protocol() == v6 else "IPv4" for a in info.addresses()}
        want = "IPv6" if self.cfg.ip_mode == "ipv6" else "IPv4"
        if not kinds:
            if by_hand:
                self._typo_stop()
            return
        if want in kinds:
            return                        # it has one now (DNS blip): the normal retry will do
        other = "IPv4" if want == "IPv6" else "IPv6"
        what = f"{host} is an {other} address" if not QHostAddress(host).isNull() else f"{host} has no {want} address, only {other}"
        self.add(self.server_buffer, ERROR, "*", f"{what}. BChat is set to {want} only (Preferences > Network setup > Internet).")
        if by_hand:
            self.want_connected = False   # retrying can't find what isn't there
            self._reconnect.stop()

    def _on_disconnected(self) -> None:
        self._dial.stop()
        self._ident_stop()
        if self._socks:                         # 0.8.8: the Socks4 proxy hung up before it answered
            self._socks = None
            if self.state != "disconnected":
                self.add(self.server_buffer, ERROR, "*", f"The Socks4 proxy {self.cfg.proxy_host} closed the connection "
                                                          "without an answer.")
        if self._rx:
            self._drain(everything=True)       # the server's last words (ERROR :Closing link) before 'Disconnected.'
        if self.state == "disconnected":
            return
        self._keepalive.stop()
        self._who.stop()
        if self.online_since and self.want_connected and not self._down_since:
            self._down_since = time.time()        # dropped by itself: "Back after X" when it returns
        self.online_since = 0.0
        self._ns_wait = 0
        self._set_state("disconnected")
        while self._addr_waiting:              # the answer can't come any more: the waiting commands are told so
            self.address_found.emit(self._addr_waiting.pop(0), "")
        gone = f"Disconnected ({self._drop_why})." if self._drop_why else "Disconnected."
        first = self._tries == 0        # 0.8.5: every tab hears it once per outage; a failed retry says only "Reconnect try N"
        if first:
            self._told_down = []
        for b in self.all_buffers():
            if first:
                self.add(b, INFO, "*", gone)
            if first and b is not self.server_buffer:
                self._told_down.append(b)
            if b.kind == CHANNEL:
                b.joined = False
                b.users.clear()
                self.users_changed.emit(b)
                self.buffer_changed.emit(b)
        self.notify.emit(self.server_buffer, "disconnect")
        if self._killed:
            self.add(self.server_buffer, INFO, "*", "BChat won't reconnect after a kill. Use Server > Reconnect when you're ready.")
        if self.want_connected and self.cfg.connect_retries > 0 and self._tries >= self.cfg.connect_retries:
            self.want_connected = False           # 0.8.5: Retry N times (Preferences > Advanced) used up
            n = self.cfg.connect_retries
            self.add(self.server_buffer, ERROR, "*", f"Gave up after {n} {'retry' if n == 1 else 'retries'}. "
                                                      "Use Server > Reconnect to try again.")
        if self.want_connected:
            self._tries += 1
            delay, note = self.reconnect_wait(self._tries)
            self.add(self.server_buffer, INFO, "*", f"Reconnect try {self._tries} in {delay} seconds...{note}")
            self._reconnect.start(delay * 1000)

    def reconnect_wait(self, tries: int) -> tuple[int, str]:
        """Seconds before reconnect try N: the set delay for 10 tries, then once a minute. Never gives up."""
        if self._banned:
            return 60, ""
        if tries > 10:
            return max(60, self.cfg.reconnect_delay), " (still down, trying less often)"
        return max(1, self.cfg.reconnect_delay), ""

    def _tick(self) -> None:
        if self._znc_collect is not None and time.time() - self._znc_collect[2] > 10:
            self._end_znc_playback()           # "Playback Complete." never came: show what arrived
        if self.state in ("connected", "registering"):
            limit = min(600, max(60, self.cfg.server_timeout))
            if time.time() - self._last_rx > limit:
                span = (("1 minute" if limit == 60 else f"{limit // 60} minutes") if limit % 60 == 0 else f"{limit} seconds")
                self.add(self.server_buffer, ERROR, "*", f"No reply from the server for {span}, so BChat closed the link.")
                self._drop_why = "no reply"
                self.sock.abort()
                return
            if not self._ping_sent:  # keep timing the oldest unanswered ping, so a stalled server keeps counting up
                self._ping_sent = time.time()
            self.send_raw("PING :LAG%d" % int(time.time() * 1000), quiet=True)

    def _poll_who(self) -> None:
        # same idea as XChat's away polling; skipped when the server pushes away changes
        if "away-notify" in self._cap_active or not self.cfg.away_track:
            return
        for b in self.buffers.values():
            if b.kind == CHANNEL and b.joined and len(b.users) <= self.cfg.away_limit:
                self.fetch_who(b.name)

    # --- sending ------------------------------------------------------------

    # passwords typed to services must not reach the raw log or the chat
    # 0.8.5: also GROUP nick pw, SET PASSWORD pw (and SET #chan PASSWORD), RELEASE; any leading IRCv3 tags
    # ('@label=bc1 ...' with labeled-response) and an echoed ':nick!user@host ' prefix no longer hide the password from the match
    _SECRET_VERBS = r"(?:IDENTIFY|ID|GHOST|RECOVER|RELEASE|REGISTER|LOGIN|AUTH|GROUP|SET\s+(?:\S+\s+)?PASSWORD)"
    _SECRET_HEAD = r"(?:@\S+\s+)?(?::\S+\s+)?"
    # a services nick: NickServ, ChanServ, Q@CServe.quakenet.org; not Observer or Server
    _SERV_NICK = r"(?:[^\s@]*@)?[^\s@.]*serve?(?:\.\S*)?"
    _SECRET_LINE = re.compile(r"(?i)^(" + _SECRET_HEAD + r"(?:PRIVMSG|NOTICE)\s+(?![#&+!])" + _SERV_NICK + r"\s+:?\s*" + _SECRET_VERBS + r"\s+).*")
    # 0.6.1: '/ns identify pw' goes out as the server's own alias 'NS IDENTIFY pw', '/oper name pw' as OPER: hide those too
    _SECRET_ALIAS = re.compile(r"(?i)^(" + _SECRET_HEAD + r"(?:NS|CS|MS|OS|HS|BS|\S*SERV)\s+:?\s*" + _SECRET_VERBS + r"\s+).*"
                               r"|^(" + _SECRET_HEAD + r"OPER\s+\S+\s+).*")
    # text typed to a services nick as a plain chat line ('identify pw' in the NickServ tab)
    _SECRET_TEXT = re.compile(r"(?is)^(\s*" + _SECRET_VERBS + r"\s+).*")

    @staticmethod
    def _untag(line: str) -> tuple[str, str]:
        """('@tags ', 'rest') for a line with IRCv3 message tags, ('', line) without."""
        if line.startswith("@"):
            tags, _, rest = line.partition(" ")
            return tags + " ", rest.lstrip(" ")
        return "", line

    @classmethod
    def _hide_secret(cls, line: str) -> str:
        head, body = cls._untag(line)
        if body.upper().startswith(("PASS ", "AUTHENTICATE ")):
            return head + body.split(" ", 1)[0] + " ****"
        line = cls._SECRET_LINE.sub(lambda m: m.group(1) + "****", line)
        return cls._SECRET_ALIAS.sub(lambda m: (m.group(1) or m.group(2)) + "****", line)

    @classmethod
    def is_secret(cls, line: str) -> bool:
        return bool(cls._SECRET_LINE.match(line) or cls._SECRET_ALIAS.match(line)) or \
            cls._untag(line)[1].upper().startswith(("PASS ", "AUTHENTICATE "))

    def hide_typed(self, target: str, text: str) -> str:
        """What the chat, the log and the scrollback may show of a line typed to target: a password to a
        services nick ('identify pw' in the NickServ tab) becomes ****."""
        if not target or self.is_channel(target) or not re.fullmatch(self._SERV_NICK, target, re.I):
            return text
        return self._SECRET_TEXT.sub(lambda m: m.group(1) + "****", text)

    def ignored(self, prefix: str, kind: str = "") -> bool:
        """XChat's ignore_check: a mask only counts for the kinds ticked on it, and Unignore overrides the rest."""
        if not getattr(self.cfg, "ignore_on", True):     # 0.8.5 /ignore off
            return False
        low = self.fold(prefix)
        here = self.fold(self.net.name)
        if kind == "P":       # 0.8.5: a private message from someone whose query tab is open is never hidden
            q = self.buffers.get(self.fold(prefix.partition("!")[0]))
            if q is not None and q.kind == QUERY:
                return False
        hit = False
        for mask in self.cfg.ignores:
            # 0.8.5: only * and ? are wildcards; [ ] \ ^ are nick letters, folded per CASEMAPPING (never a set)
            glob = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in self.fold(mask))
            if not re.fullmatch(glob, low, re.S):
                continue
            nets = self.cfg.ignore_nets.get(mask, "")      # 0.8.5: /ignore without -w is for that network only
            if nets and here not in [self.fold(x.strip()) for x in nets.split(",")]:
                continue
            kinds = self.cfg.ignore_kinds.get(mask, IGNORE_KINDS)
            if "U" in kinds:
                return False
            if not kind or kind in kinds:
                hit = True
        if hit and kind and kind not in "KH":            # K and H change a line, they don't hide it
            IGNORE_STATS[kind] = IGNORE_STATS.get(kind, 0) + 1
        return hit

    # --- Friends List: MONITOR where the server has it, else ISON every 2 minutes, like XChat ---

    def _friends_here(self) -> list[str]:
        out = []
        for nick in self.cfg.friends:
            nets = self.cfg.friend_nets.get(nick, "")
            if not nets or self.fold(self.net.name) in [self.fold(x.strip()) for x in nets.split(",")]:
                out.append(nick)
        return out

    def start_friends(self) -> None:
        self.friend_state = {k: v for k, v in self.friend_state.items() if self.fold(k) in [self.fold(n) for n in self._friends_here()]}
        nicks = self._friends_here()
        if self.state != "connected" or self._friends_wait:
            return
        if self._monitor:
            self.send_raw("MONITOR C", quiet=True)
            for line in self._monitor_lines(nicks):    # 0.8.5: a long list goes out as several lines of <= 512 bytes
                self.send_raw(line, quiet=True)
            self.send_raw("MONITOR S", quiet=True)
        elif self._watch:
            self.send_raw("WATCH C", quiet=True)            # 0.6.0: instant online/offline/away where WATCH exists
            for i in range(0, len(nicks), 20):
                self.send_raw("WATCH " + " ".join("+" + n for n in nicks[i:i + 20]), quiet=True)
        else:
            self._friends_timer.start(max(10, self.cfg.notify_timeout) * 1000)
            self.poll_friends()

    @staticmethod
    def _monitor_lines(nicks: list[str], limit: int = 510) -> list[str]:
        """'MONITOR + a,b,c' lines that each fit an IRC line (512 bytes with the CR LF)."""
        out, cur = [], ""
        for n in nicks:
            add = ("," if cur else "") + n
            if cur and len(("MONITOR + " + cur + add).encode("utf-8")) > limit:
                out.append("MONITOR + " + cur)
                cur, add = "", n
            cur += add
        if cur:
            out.append("MONITOR + " + cur)
        return out

    def _friends_after_005(self, ticket: int = 0) -> None:
        """0.6.0: start Friends tracking once the server's feature list (005) is in: end of MOTD, or 5 s after 001."""
        if self._friends_wait and (not ticket or ticket == self._friends_wait):
            self._friends_wait = 0
            self.start_friends()

    def poll_friends(self) -> None:
        nicks = self._friends_here()
        if self.state == "connected" and nicks and not self._monitor and not self._watch:
            self._ison_asked.append([self.fold(n) for n in nicks])
            self.send_raw("ISON " + " ".join(nicks), quiet=True)

    def _friend_away(self, nick: str, reason: str | None) -> None:
        """0.6.0: a friend went away (reason) or came back (None): one line in the server tab when it changes."""
        key = self.fold(nick)
        name = next((n for n in self._friends_here() if self.fold(n) == key), None)
        if name is None:
            return
        st = self.friend_state.setdefault(key, {"online": True, "seen": time.time(), "known": True, "since": time.time()})
        before = st.get("away")
        st["away"] = reason
        if reason == before or (before is None and reason is None):
            return
        if reason is not None:
            self.add(self.server_buffer, INFO, "*", f"{name} is away" + (f": {reason}" if reason else "."))
        else:
            self.add(self.server_buffer, INFO, "*", f"{name} is back.")

    def _friend_online(self, nick: str, online: bool) -> None:
        key = self.fold(nick)
        name = next((n for n in self.cfg.friends if self.fold(n) == key), None)
        if name is None:
            return
        st = self.friend_state.setdefault(key, {"online": False, "seen": 0.0, "known": False, "since": 0.0})
        changed = st["online"] != online or not st["known"]
        was_known = st["known"]
        st["online"], st["known"] = online, True
        if online:
            st["seen"] = time.time()
            if changed:
                st["since"] = time.time()          # 0.5.0 Friends List 'Online for'
        if changed and (online or was_known):
            self.last_friend = name
            opts = self.cfg.friend_opts.get(key, {})
            if online:
                from .people import card_for
                note = " ".join(((card_for(self.cfg, name) or {}).get("notes") or "").split())
                self.te("Notify Online", self.server_buffer, INFO, (name, self.net.name, f"  Note: {note[:120]}" if note else ""))
                self.notify.emit(self.server_buffer, "friend")
                if opts.get("whois", self.cfg.whois_on_notify):
                    self.whois(name)
            else:
                since = st.get("since", 0.0)
                st["since"] = 0.0
                self.te("Notify Offline", self.server_buffer, INFO,
                        (name, self.net.name, f" Online for {duration(time.time() - since)}." if since else ""))
                self.notify.emit(self.server_buffer, "friend_off")
        self.friends_changed.emit()

    def send_raw(self, line: str, secret: bool = False, quiet: bool = False) -> None:
        if self.sock.state() != QAbstractSocket.SocketState.ConnectedState:
            return
        # a line break inside user text would otherwise become a second IRC command
        line = line.replace("\r", " ").replace("\n", " ").replace("\0", "")
        if line[:5].upper() == "JOIN " and getattr(self.cfg, "lock_limits", None):
            line = self._lock_join(line)
            if not line:
                return
        secret = secret or self.is_secret(line)
        self.sock.write(line.encode("utf-8", "replace") + b"\r\n")
        if not quiet and (line.split(" ", 1)[1] if line.startswith("@") and " " in line else line)[:5].upper() == "ISON ":
            self._ison_asked.append(None)      # 0.8.5: a typed /ison: its answer is shown, not read as friends' status
        if not quiet:
            self.raw_line.emit(self._hide_secret(line) if secret else line, True)

    def _lock_join(self, line: str) -> str:
        """0.6.0 Lock 'Only these channels': a JOIN keeps only the allowed channels (keys stay with theirs)."""
        from .lock import allowed_channels
        allowed = allowed_channels(self.cfg.lock_limits)
        if not allowed:
            return line
        parts = line.split(" ")
        chans = parts[1].split(",") if len(parts) > 1 else []
        keys = parts[2].split(",") if len(parts) > 2 else []
        keep = [(c, keys[i] if i < len(keys) else "") for i, c in enumerate(chans) if self.fold(c) in allowed]
        refused = [c for c in chans if self.fold(c) not in allowed]
        if refused:
            self.add(self._front(), ERROR, "*", f"Lock: only {', '.join(allowed)} can be joined here ({', '.join(refused)} wasn't).")
        if not keep:
            return ""
        out = "JOIN " + ",".join(c for c, _ in keep)
        if any(k for _, k in keep):
            out += " " + ",".join(k or "x" for _, k in keep)
        return out

    def send(self, command: str, *params: str) -> None:
        answer = self._ctcp_answer
        if answer is not None and command.upper() == "NOTICE" and len(params) == 2 and params[1].startswith("\x01") \
                and self.fold(params[0]) == answer[0]:
            self._ctcp_answer = None             # 0.8.5: a reply-list command's CTCP reply goes through the flood buffer too
            try:
                self._ctcp_reply(params[0], answer[1], params[1])
            finally:
                self._ctcp_answer = answer
            return
        if command.upper() == "PRIVMSG" and len(params) == 2 and params[1].upper().startswith("\x01PING"):
            params = self._ctcp_ping_out(*params)
        line = build_line(command, *params)
        self.sent_count += 1
        if command.upper() == "JOIN" and len(params) > 1:
            self._note_join_keys(params[0], params[1])
        if command.upper() == "NICK" and params and self.state != "connected" \
                and self.sock.state() != QAbstractSocket.SocketState.ConnectedState:
            # 0.8.5: /nick while offline or waiting to reconnect: the next connect uses it
            self._next_nick = self.nick = params[0]
            self.state_changed.emit()
            self.add(self._front(), INFO, "*", f"The next connect uses the nick {params[0]}.")
            return
        if self.state != "connected":
            self.send_raw(line)
            return
        if self._typed:
            self.send_raw(line)       # 0.8.5: what the user types is never queued or capped, only automatic lines are paced
            return
        self._queue.append(line)
        self._drain_queue()

    @contextlib.contextmanager
    def typed(self):
        """Everything sent while the user's own input is handled (chat, /msg, /notice, /me, /mode, /kick, aliases...)
        goes straight to the socket; only automatic lines (JOIN/WHO/MODE bursts, CTCP replies, scripts, timers) are paced."""
        self._typed += 1
        try:
            yield
        finally:
            self._typed -= 1

    def _note_join_keys(self, chans: str, keys: str) -> None:
        """0.8.5: the keys of our own JOIN, kept until the server says we're in (then on the tab, for rejoins)."""
        for c, k in zip(chans.split(","), keys.split(",")):
            if k and k != "x":
                self._join_keys[self.fold(c)] = k

    @staticmethod
    def _is_background(line: str) -> bool:
        """WHO polling and channel mode queries: the user never asked for these directly."""
        word = line.split(" ")
        return word[0] == "WHO" or (word[0] == "MODE" and len(word) == 2)

    def _drain_queue(self) -> None:
        """XChat's tcp_send_queue pacing, improved: background lines leave room, so automatic lines never fill the budget."""
        now = time.time()
        while self._queue:
            if self._next_send < now:
                self._next_send = now
            used = self._next_send - now
            at = next((i for i, l in enumerate(self._queue) if not self._is_background(l)), None)
            if at is None and used < 4:
                at = 0
            if at is None or used >= 10:
                if not self._queue_timer.isActive():
                    self._queue_timer.start()
                return
            line = self._queue.pop(at)
            _, _, rest = line.partition(" ")
            self._next_send += (2 + len(rest) / 120) * self.PACE.get(self.cfg.flood_pace, 1.0)
            self.send_raw(line)
        self._queue_timer.stop()
        self._ctcp_queue_empty()

    def _not_a_target(self, target: str) -> bool:
        """QA BUG-2 (0.8.6): "(messages)" and "(notices)" are BChat's own tabs, never a nick to send to."""
        if not target.startswith("("):
            return False
        hint = "Reply with /msg nick message (Tab picks the nick)" if target == self.MESSAGES else "No channel joined. Try /join #channel"
        self.add(self.buffer(target), ERROR, "*", hint)
        return True

    def say(self, target: str, text: str) -> None:
        if target.startswith("=") and self.dcc_say is not None:
            if not self.dcc_say(self, target, text):
                self.add(self.buffer(target), ERROR, "*", f"No active DCC chat with {target[1:]}.")
            return
        if self._not_a_target(target):
            return
        if self.state != "connected":
            self.add(self._front(), ERROR, "*", "Not connected. Use Server > Reconnect.")
            return
        if self.away and self.cfg.auto_unaway:
            self.set_away(False)
        # keep each piece inside the 512-byte IRC limit, split on characters not bytes
        limit = 400
        while text:
            raw = text.encode("utf-8")
            if len(raw) <= limit:
                piece, text = text, ""
            else:
                piece = raw[:limit].decode("utf-8", "ignore")
                text = text[len(piece):]
            self.send("PRIVMSG", target, piece)
            if "echo-message" not in self._cap_active:
                self.add(self.buffer(target), SELF, self.nick, self.hide_typed(target, piece))

    def msg(self, target: str, text: str) -> None:
        """/msg: sends without opening a tab, and shows >target< in the current one, like XChat."""
        if self.state != "connected":
            self.add(self._front(), ERROR, "*", "Not connected. Use Server > Reconnect.")
            return
        shown = self.hide_typed(target, text)
        self.send("PRIVMSG", target, text)
        self.add(self._front(), SELF, f">{target}<", shown)
        open_tab = self.buffers.get(self.fold(target))
        if open_tab is not None and open_tab is not self._front():
            self.add(open_tab, SELF, self.nick, shown)

    def action(self, target: str, text: str) -> None:
        if self._not_a_target(target):
            return
        if self.state != "connected":
            self.add(self._front(), ERROR, "*", "Not connected. Use Server > Reconnect.")
            return
        self.send("PRIVMSG", target, f"\x01ACTION {text}\x01")
        self.add(self.buffer(target), ACTION, "*", f"{self.nick} {text}")

    def fetch_who(self, channel: str) -> None:
        if self.whox:
            self.send("WHO", channel, "%tcuhsnfar,152")
        else:
            self.send("WHO", channel)

    def whois(self, nick: str, target: Buffer | None = None) -> None:
        # asking twice with the same nick gets the idle time from the user's own server
        self._whois_target = target or self._front()
        self._whois_nick = self.fold(nick)
        self.send("WHOIS", nick, nick)

    def silent_whois(self, nick: str) -> None:
        """Fills the nick menu's info panel without printing anything, like XChat does."""
        key = self.fold(nick)
        if self.state == "connected" and key not in self._silent_whois:
            self._silent_whois[key] = {}
            self.send("WHOIS", nick)

    def set_mode_for(self, b: Buffer, sign_mode: str, nicks: list[str]) -> None:
        # servers allow only so many modes per line (MODES=), so a long selection needs several
        for i in range(0, len(nicks), self.max_modes):
            part = nicks[i:i + self.max_modes]
            self.send("MODE", b.name, sign_mode[0] + sign_mode[1] * len(part), *part)

    def account_ban(self, b: Buffer, nick: str, kick: bool = False) -> None:
        """0.6.0 /ban -a nick: ban the account, not the host (EXTBAN ~a: or $a:, whatever the server offers)."""
        pre, types = self.extban
        if not pre or "a" not in types:
            self.add(b, ERROR, "*", "This server has no account bans (EXTBAN a). Use /ban nick instead.")
            return
        u = b.users.get(self.fold(nick))
        account = u.account if u is not None else ""
        if not account:
            self.add(b, ERROR, "*", f"BChat doesn't know {nick}'s account (not logged in, or the server doesn't say). "
                                    "Use /ban nick instead.")
            return
        self.send("MODE", b.name, "+b", f"{pre}a:{account}")
        if kick:
            self.send("KICK", b.name, nick, self.cfg.part_reason)

    def ban(self, b: Buffer, nick: str, kind: int, kick: bool = False, reason: str = "") -> None:
        u = b.users.get(self.fold(nick))
        self.send("MODE", b.name, "+b", mask_ban(nick, u.host if u else "", kind))
        if kick:
            self.send("KICK", b.name, nick, reason.strip() or self.cfg.part_reason)   # 0.8.5: /kickban's own reason

    def set_away(self, away: bool, reason: str = "") -> None:
        reason = reason or self.cfg.away_reason
        self._away_msg = reason if away else ""   # 0.8.5: sent again after a reconnect
        if away:
            self.send("AWAY", reason)
        else:
            self.send("AWAY")
        if self.cfg.announce_away:   # General: "Announce away messages"
            for b in self.buffers.values():
                if b.kind == CHANNEL and b.joined:
                    self.action(b.name, f"is away: {reason}" if away else "is back")

    # --- receiving -----------------------------------------------------------

    def _ts(self, m: Message) -> float:
        t = m.tags.get("time")
        if t:
            try:
                return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
            except ValueError:
                pass
        return time.time()

    def _handle(self, m: Message) -> None:
        """labeled-response: an answer to a labeled line goes to the tab it was typed in (via _front)."""
        label = m.tags.get("label", "")
        route = self._labels.get(label, (None,))[0] if label else None
        bid = m.tags.get("batch")
        if route is None and bid:
            route = self._label_batches.get(bid)
        if m.command == "BATCH" and label and route is not None and m.params and m.params[0].startswith("+"):
            self._label_batches[m.params[0][1:]] = route
        if m.command == "BATCH" and m.params and m.params[0].startswith("-"):
            self._label_batches.pop(m.params[0][1:], None)
        if m.command == "ACK":
            self._labels.pop(label, None)
            return
        if route is not None and route in self.all_buffers():
            self._route = route
            try:
                self._handle_inner(m)
            finally:
                self._route = None
            return
        self._handle_inner(m)

    def _handle_inner(self, m: Message) -> None:
        bid = m.tags.get("batch")
        if bid and bid in self._history and m.command in ("PRIVMSG", "NOTICE"):
            self._history[bid][1].append(m)      # history: kept until the batch ends, then put above the join
            return
        if bid and bid in self._playback and m.command in ("PRIVMSG", "NOTICE"):
            if m.nick != "***":                  # ZNC's own "Buffer Playback..." markers: the header replaces them
                self._playback[bid][1].append(m)     # ZNC playback: shown under one header when the batch ends
            return
        if self._znc_collect is not None and m.command in ("PRIVMSG", "NOTICE") and m.nick != "***":
            self._znc_collect[1].append(m)
            return
        handler = getattr(self, "_irc_" + m.command.lower(), None) if m.command.isalpha() else None
        if handler:
            handler(m)
        elif m.command.isdigit():
            self._numeric(int(m.command), m)
        else:
            self.add(self.server_buffer, INFO, m.command, " ".join(m.params))

    def _irc_ping(self, m: Message) -> None:
        self.send_raw(f"PONG :{m.param(0)}", quiet=True)

    def _irc_pong(self, m: Message) -> None:
        if m.param(-1).startswith("LAG") and self._ping_sent:
            self.lag_ms = int((time.time() - self._ping_sent) * 1000)
            self._ping_sent = 0.0
            self.state_changed.emit()

    def _irc_cap(self, m: Message) -> None:
        sub = m.param(1).upper()
        if sub in ("LS", "NEW"):
            more = sub == "LS" and len(m.params) >= 4 and m.param(2) == "*"
            for item in m.params[-1].split():
                k, _, v = item.partition("=")
                self._cap_offered[k] = v
                self._cap_more.add(k)
            if more:
                return
            offered, self._cap_more = self._cap_more, set()
            if "sts" in offered and self._sts_policy(self._cap_offered["sts"]):
                return
            self._spot_bouncer(offered)
            wanted = offered & self.WANTED_CAPS - set(self.net.caps_off)
            mechs = [x for x in self._cap_offered.get("sasl", "").upper().split(",") if x]
            if self.net.login == "cert":
                if not self._cert_loaded:
                    pass                          # said already: no SSL, or the file couldn't be read
                elif "sasl" not in offered:
                    self.add(self.server_buffer, INFO, "*", "This server has no SASL login: NickServ may still know your certificate.")
                elif mechs and "EXTERNAL" not in mechs:
                    self.add(self.server_buffer, ERROR, "*", "This server doesn't take certificate logins (SASL EXTERNAL).")
                else:
                    wanted.add("sasl")
            elif self.net.login == "none":
                pass
            elif "sasl" in offered and self.net.sasl_user and "SCRAM-SHA-256" in mechs:
                self._sasl_mech = "SCRAM-SHA-256"       # the password itself never crosses the network
                wanted.add("sasl")
            elif "sasl" in offered and self.net.sasl_user and (not mechs or "PLAIN" in mechs):
                if self._tls_now:
                    self._sasl_mech = "PLAIN"
                    wanted.add("sasl")
                else:
                    self.add(self.server_buffer, ERROR, "*", "SASL login skipped: the password would be sent without SSL.")
            if wanted:
                self._cap_pending += 1
                self.send_raw("CAP REQ :" + " ".join(sorted(wanted)))
            elif sub == "LS":
                self.send_raw("CAP END")
        elif sub == "DEL":
            for c in m.params[-1].split():
                self._cap_active.discard(c)
        elif sub in ("ACK", "NAK"):
            if sub == "ACK":
                for c in m.params[-1].split():
                    if c.startswith("-"):
                        self._cap_active.discard(c[1:])
                    else:
                        self._cap_active.add(c)
            if len(m.params) >= 4 and m.param(2) == "*":
                return
            self._cap_pending = max(0, self._cap_pending - 1)
            if sub == "ACK" and "sasl" in m.params[-1].split() and not self._welcomed:
                if self.net.login == "cert":
                    self._sasl_state = "external"
                    self.add(self.server_buffer, INFO, "*", "Logging in with your certificate (SASL EXTERNAL)...")
                    self.send_raw("AUTHENTICATE EXTERNAL")
                elif self._sasl_mech == "SCRAM-SHA-256":
                    from .scram import Scram
                    self._sasl_state = "scram"
                    self._scram = Scram(self.net.sasl_user, self.net.sasl_password)
                    self._scram_in = ""
                    self.send_raw("AUTHENTICATE SCRAM-SHA-256")
                else:
                    self._sasl_state = "plain"
                    self.send_raw("AUTHENTICATE PLAIN")
            elif not self._welcomed and not self._sasl_state:
                self.send_raw("CAP END")

    def _sts_policy(self, value: str) -> bool:
        """Returns True when the connection is being replaced by a secure one."""
        args = dict(p.partition("=")[::2] for p in value.split(",") if p)
        host = self.net.servers[self.server_index].host.lower()
        if not self._tls_now:
            port = args.get("port", "")
            if port.isdigit():
                self.add(self.server_buffer, INFO, "*", f"Server requires SSL (STS), reconnecting on port {port}")
                self.cfg.sts[host] = {"port": int(port), "expires": time.time() + 3600}
                self._repeat = True
                self._set_state("disconnected")
                self._keepalive.stop()
                self.sock.abort()
                self._connect_next()
                return True
            return False
        if "duration" in args and args["duration"].isdigit():
            secs = int(args["duration"])
            if secs:
                port = self.sock.peerPort()
                self.cfg.sts[host] = {"port": port, "expires": time.time() + secs}
            else:
                self.cfg.sts.pop(host, None)
        return False

    def _sasl_send(self, payload: bytes) -> None:
        data = base64.b64encode(payload).decode() if payload else ""
        chunks = [data[i:i + 400] for i in range(0, len(data), 400)] or ["+"]
        if len(chunks[-1]) == 400:
            chunks.append("+")
        for c in chunks:
            self.send_raw(f"AUTHENTICATE {c}", secret=True)

    def _irc_authenticate(self, m: Message) -> None:
        if self._sasl_state == "scram":
            part = m.param(0)
            if part != "+":
                self._scram_in += part
                if len(part) == 400:
                    return                          # more of the same message follows
            text, self._scram_in = self._scram_in, ""
            try:
                answer = self._scram.step(base64.b64decode(text) if text else b"")
            except ValueError as e:
                self.send_raw("AUTHENTICATE *")
                self._sasl_done(False, f"SCRAM login stopped: {e}")
                return
            if answer is None:
                self.send_raw("AUTHENTICATE +")    # the server's last message checked out: nothing more to say
            else:
                self._sasl_send(answer)
            return
        if self._sasl_state == "external" and m.param(0) == "+":
            self.send_raw("AUTHENTICATE +")       # the server takes the account from the certificate
            return
        if self._sasl_state != "plain" or m.param(0) != "+":
            return
        blob = f"{self.net.sasl_user}\0{self.net.sasl_user}\0{self.net.sasl_password}".encode()
        data = base64.b64encode(blob).decode()
        chunks = [data[i:i + 400] for i in range(0, len(data), 400)] or ["+"]
        if len(chunks[-1]) == 400:
            chunks.append("+")
        for c in chunks:
            self.send_raw(f"AUTHENTICATE {c}", secret=True)

    def _sasl_done(self, ok: bool, text: str) -> None:
        if ok and self._sasl_state == "scram":
            if self._scram is None or not self._scram.verified:
                ok, text = False, "SCRAM login: the server couldn't prove it knows your password. Not trusting it."
            else:
                text = f"Logged in as {self.net.sasl_user} with SCRAM-SHA-256: your password itself was never sent."
        self._sasl_state = ""
        self.add(self.server_buffer, INFO if ok else ERROR, "*", text)
        if not ok and not self._welcomed and self.net.login_fail != "stay":
            self._sasl_give_up()                  # 0.8.5: If the login fails: Disconnect, don't retry
            return
        if not self._welcomed:
            self.send_raw("CAP END")

    def _sasl_give_up(self) -> None:
        self.want_connected = False
        self._reconnect.stop()
        self.add(self.server_buffer, ERROR, "*", "BChat disconnected and will not retry. Check the SASL login in "
                                                  "Network List > Edit, then use Server > Reconnect.")
        self.send_raw("QUIT")
        self.sock.flush()
        self.sock.abort()
        self._dial.stop()
        self._set_state("disconnected")

    def _irc_batch(self, m: Message) -> None:
        """Other batches: their lines carry their own tags and show normally. Chathistory batches are collected."""
        ref = m.param(0)
        if ref.startswith("+") and m.param(1).lower() in ("chathistory", "draft/chathistory") and len(m.params) >= 3:
            self._history[ref[1:]] = (m.param(2), [])
        elif ref.startswith("+") and m.param(1).lower() == "znc.in/playback" and len(m.params) >= 3:
            self._playback[ref[1:]] = (m.param(2), [])
            self.bouncer, self._znc_guess = self.bouncer or "ZNC", False
        elif ref.startswith("-") and ref[1:] in self._playback:
            target, msgs = self._playback.pop(ref[1:])
            self._show_playback(target, msgs)
        elif ref.startswith("-") and ref[1:] in self._history:
            target, msgs = self._history.pop(ref[1:])
            self._history_done(target, msgs)

    # --- channel history (IRCv3 chathistory) ------------------------------------------------

    def history_on(self) -> bool:
        return bool(self._cap_active & {"draft/chathistory", "chathistory"}) and self.chathistory_max >= 0

    def _ask_history(self, b: Buffer, since: float) -> None:
        """On join: the last lines said, or (rejoin / reconnect) only what came after the last line we have."""
        n = self.HISTORY_LINES if self.chathistory_max <= 0 else min(self.HISTORY_LINES, self.chathistory_max)
        if since:
            stamp = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self.send_raw(f"CHATHISTORY AFTER {b.name} timestamp={stamp} {n}", quiet=True)
        else:
            self.send_raw(f"CHATHISTORY LATEST {b.name} * {n}", quiet=True)
        b.history_since = since

    def _history_done(self, target: str, msgs: list) -> None:
        b = self.buffer(target, False)
        if b is None:
            return
        since = b.history_since
        lines = []
        for m in msgs:
            ts = self._ts(m)
            if ts <= since or self.ignored(m.prefix, "C" if m.command == "PRIVMSG" else "N"):
                continue
            text, nick = m.param(-1), m.nick
            if self.ignored(m.prefix, "K"):               # 0.8.5 /ignore -k (strip_format keeps the CTCP marks)
                text = strip_format(text)
            me = self.fold(nick) == self.fold(self.nick)
            if m.command == "NOTICE":
                if text.startswith(""):
                    continue
                lines.append(Line(NOTICE, f"-{nick}-", text, ts))
            elif text.startswith("ACTION"):
                lines.append(Line(ACTION, "*", f"{nick} {text.strip(chr(1))[7:]}", ts))
            elif text.startswith(""):
                continue                               # old CTCP requests are never answered
            elif me:
                lines.append(Line(SELF, nick, text, ts))
            else:
                hit = not self.ignored(m.prefix, "H") and self._is_hilite(text, nick, b.name)
                lines.append(Line(HILITE if hit else MSG, nick, text, ts, colour=self._hilite_colour() if hit else ""))
        if not lines:
            return
        word = "messages you missed" if since else "earlier messages, sent before you joined"
        lines.append(Line(INFO, "", f"14────────  above: {word}  ────────", lines[-1].ts))
        at = next((i for i in range(len(b.lines) - 1, -1, -1) if b.lines[i].kind == NOW_TALKING), len(b.lines))
        b.lines[at:at] = lines
        cap = max(100, self.cfg.max_lines or self.MAX_LINES)
        if len(b.lines) > cap:
            del b.lines[: len(b.lines) - cap]
        self.lines_inserted.emit(b)

    def _irc_tagmsg(self, m: Message) -> None:
        pass

    def _standard_reply(self, m: Message) -> None:
        kind = ERROR if m.command == "FAIL" else INFO
        self.add(self._front(), kind, "*", f"{m.command} {m.param(0)}: {m.param(-1)}")

    _irc_fail = _standard_reply
    _irc_warn = _standard_reply
    _irc_note = _standard_reply

    def _irc_account(self, m: Message) -> None:
        acct = "" if m.param(0) == "*" else m.param(0)
        for b in self.buffers.values():
            u = b.users.get(self.fold(m.nick))
            if u:
                u.account = acct
                if acct:
                    self.control.check(b, m.nick)       # logged in after joining: their account rule fits now

    def _irc_setname(self, m: Message) -> None:
        for b in self.buffers.values():
            u = b.users.get(self.fold(m.nick))
            if u:
                u.realname = m.param(0)

    def _irc_wallops(self, m: Message) -> None:
        self.add(self.server_buffer, NOTICE, f"-{m.nick}/Wallops-", m.param(-1), self._ts(m))

    def _irc_kill(self, m: Message) -> None:
        target = m.param(0)
        # before the welcome the server may not know our nick yet and sends KILL * : that is still us
        if self._welcomed and target != "*" and self.fold(target) != self.fold(self.nick):
            self.add(self.server_buffer, INFO, "*", f"{m.param(0)} was killed by {m.nick} ({m.param(-1)})")
            return
        # an oper put us off on purpose: coming straight back is what gets a K-line, so wait for the user
        self._killed = True
        self.want_connected = False
        self._reconnect.stop()
        self.add(self.server_buffer, ERROR, "*", f"You were killed by {m.nick} ({m.param(-1)})")

    BAN_WORDS = ("k-lined", "g-lined", "z-lined", "d-lined", "banned")

    def _ban_seen(self, text: str) -> None:
        """465 or a ban ERROR: not a password problem, and bans are often lifted, so keep trying once a minute."""
        if not self._banned:
            self._banned = True
            self.add(self.server_buffer, ERROR, "*", f"Banned from this server: {text}")
            self.add(self.server_buffer, INFO, "*", "BChat will try again every 60 seconds. Server > Disconnect stops it.")

    def _irc_error(self, m: Message) -> None:
        low = m.param(-1).lower()
        if not self._welcomed and any(w in low for w in self.BAN_WORDS):
            self._ban_seen(m.param(-1))
            return
        if not self._welcomed and "password" in low:
            self._login_refused(m.param(-1))
            return
        self.add(self.server_buffer, ERROR, "*", m.param(-1))

    def _join_refused(self, n: int, m: Message) -> bool:
        """The server says no to a channel whose tab still shows us inside: that list is old (a bouncer's memory
        from before the server restarted, say). Empty it so no one shows as there, ourselves included.
        Returns False so the usual 'Cannot join' line still follows."""
        b = self.buffers.get(self.fold(m.param(1)))
        if b is not None and b.kind == CHANNEL and (b.joined or b.users):
            b.joined = False
            b.users.clear()
            self.add(b, INFO, "*", f"You are not in {b.name}: the server refused the join.")
            self.users_changed.emit(b)
            self.buffer_changed.emit(b)
        return False

    def _irc_privmsg(self, m: Message) -> None:
        target, text = m.param(0), m.param(-1)
        if m.nick == "***" and m.prefix.endswith("@znc.in"):
            if text.strip() == "Buffer Playback...":
                if self._znc_collect is not None:
                    self._end_znc_playback()
                self._znc_collect = (target, [], time.time())
                self.bouncer, self._znc_guess = self.bouncer or "ZNC", False
                return
            if text.strip() == "Playback Complete.":
                self._end_znc_playback()
                return
        if self._version_wait and self.fold(m.nick) == "*status" and time.time() - self._version_wait < 10:
            self._znc_guess = False                # someone answers as *status: a real ZNC
            # ZNC answers 'version' with TWO lines: "ZNC 1.10.3 - https://znc.in" and its build options
            # ("IPv6: yes, SSL: yes, DNS: threads, ..."). Both are taken; anything else from *status shows as usual.
            plain = strip_format(text).strip()
            found = re.search(r"\bZNC[ -]?v?(\d+(?:\.\d+)+)", plain)
            if found and not self.bouncer_version:
                self.bouncer_version = found.group(1)
                if self._bouncer_said:
                    self.state_changed.emit()      # the line went out without it: the tooltip still learns it
                self._say_bouncer()
                return
            if re.match(r"^IPv6: \w+, SSL: \w+", plain):
                return
        ctcp = text.startswith("\x01") and not text.startswith("\x01ACTION")
        dcc = text.startswith("\x01DCC")
        kind = "D" if dcc else "T" if ctcp else "C" if self.is_channel(target) else "P"
        if not self._replaying and "batch" not in m.tags and self.fold(m.nick) != self.fold(self.nick):
            self.protection.heard(target, m.nick, text)     # 0.9.3: before /ignore, an ignored flooder still floods
        if self.ignored(m.prefix, kind):
            return
        if not ctcp and self.ignored(m.prefix, "K"):      # 0.8.5 /ignore -k: their colours, bold and codes taken out
            text = strip_format(text)
        quiet = self.ignored(m.prefix, "H")               # 0.8.5 /ignore -h: never a highlight or an alert
        ts = self._ts(m)
        from_me = self.fold(m.nick) == self.fold(self.nick)
        target = target.lstrip(self.statusmsg) if self.statusmsg else target
        dest = target if self.is_channel(target) else (target if from_me else m.nick)
        if from_me:
            text = self.hide_typed(dest, text)       # echo-message: the server sends our own 'identify pw' back
        if not self.is_channel(target) and (not ctcp) and self.to_messages(dest):
            self._into_messages(m, dest, text, ts, from_me, quiet)
            return
        if not from_me and not self.cfg.auto_dialog and not self.is_channel(target) and self.fold(dest) not in self.buffers \
                and not (text.startswith("\x01") and not text.startswith("\x01ACTION")):
            # "Open a new tab when you receive a private message" is off: it shows where you are
            front = self._front()
            self.add(front, MSG if quiet else HILITE, f"*{m.nick}*", text.strip("\x01").removeprefix("ACTION "), ts)
            if not quiet:
                self._notify(front, "priv")
            return
        if not from_me and not self.is_channel(target) and self.fold(dest) not in self.buffers \
                and not (text.startswith("\x01") and not text.startswith("\x01ACTION")) and self._query_flood(m.nick, time.time()):
            self.add(self.server_buffer, HILITE, f"*{m.nick}*", text.strip("\x01").removeprefix("ACTION "), ts)
            return
        if text.startswith("\x01") :
            body = text.strip("\x01")
            verb, _, rest = body.partition(" ")
            if verb.upper() == "ACTION":
                new = self.fold(dest) not in self.buffers
                b = self.buffer(dest)
                if new and not from_me:
                    self._whois_new_query(b, m.nick)
                # 0.8.5: our own /me (typed in another client of the bouncer) is never unread or a highlight
                hit = not from_me and not quiet and self._is_hilite(rest, m.nick, b.name)
                self.add(b, ACTION if not hit else HILITE, "*", f"{m.nick} {rest}", ts, colour=self._hilite_colour() if hit else "")
                if not from_me:
                    self._bump(b, 3 if hit else 2)
                if not from_me and not quiet:
                    self._notify(b, "priv" if b.kind == QUERY else "hilight" if hit else "chan")
            else:
                # 0.8.5: an old request played back, or our own CTCP to someone else that the bouncer echoes, is not answered
                if self._replaying or (from_me and self.fold(target) != self.fold(self.nick)):
                    return
                self.last_ctcp_prefix = m.prefix          # DCC trust list checks the whole address
                self._ctcp_request(m.nick, verb.upper(), rest, own=from_me)
            return
        new = self.fold(dest) not in self.buffers
        b = self.buffer(dest)
        if new and not from_me:
            self._whois_new_query(b, m.nick)
        u = b.users.get(self.fold(m.nick))
        if u:
            u.last_msg = ts
        msgid = m.tags.get("msgid", "")
        if b.typing.pop(self.fold(m.nick), None) is not None:
            self.typing_changed.emit(b)
        self._quote_reply(b, m.tags.get("+draft/reply") or m.tags.get("+reply", ""), ts)
        if from_me:
            self.add(b, SELF, m.nick, text, ts, msgid=msgid)
            return
        hit = not quiet and self._is_hilite(text, m.nick, b.name)
        hl = hit or (b.kind == QUERY and not quiet)
        if self.print_hook is not None:
            event = "Private Message to Dialog" if b.kind == QUERY else "Channel Msg Hilight" if hit else "Channel Message"
            if self.print_hook(event, (m.nick, text)):
                return
        self.add(b, HILITE if hl else MSG, m.nick, text, ts, colour=self._hilite_colour() if hit else "", msgid=msgid)
        self._bump(b, 3 if hl else 2)
        if not quiet:
            self._notify(b, "priv" if b.kind == QUERY else "hilight" if hit else "chan")

    # --- IRCv3 client tags: +typing and +draft/reply ------------------------------------

    TYPING_SHOWN = 6.0         # seconds 'X is typing...' stays without a new active

    def tags_on(self) -> bool:
        return "message-tags" in self._cap_active and self.state == "connected"

    def client_tag_ok(self, tag: str) -> bool:
        """CLIENTTAGDENY=*,-typing: every client tag dropped except +typing (draft/ prefixes compared both ways)."""
        if not self.tags_on():
            return False
        name = tag.lstrip("+")
        bare = name.removeprefix("draft/")
        deny = [x for x in self.client_tag_deny.split(",") if x]
        allowed = {x[1:].removeprefix("draft/") for x in deny if x.startswith("-")}
        if "*" in deny:
            return bare in allowed
        return bare not in {x.removeprefix("draft/") for x in deny if not x.startswith("-")}

    def _quote_reply(self, b: Buffer, ref: str, ts: float) -> None:
        """A reply to a line we still have: a grey quote of it goes above, and a click on it jumps there."""
        if not ref:
            return
        orig = next((ln for ln in reversed(b.lines) if ln.msgid == ref), None)
        if orig is None:
            return
        who = orig.left if orig.left not in ("*", "") else ""
        text = strip_format(orig.text)
        short = text if len(text) <= 120 else text[:119] + "\u2026"
        self.add(b, INFO, "", f"\x0314\u21aa {who + ': ' if who else ''}{short}", ts, reply_to=ref)

    def _irc_tagmsg(self, m: Message) -> None:
        target = m.param(0)
        if self.fold(m.nick) == self.fold(self.nick) or self.ignored(m.prefix, "C" if self.is_channel(target) else "P"):
            return
        state = m.tags.get("+typing") or m.tags.get("+draft/typing")
        if not state:
            return
        dest = target if self.is_channel(target) else m.nick
        b = self.buffers.get(self.fold(dest))
        if b is None:
            return
        if state == "active":
            b.typing[self.fold(m.nick)] = (m.nick, time.time())
        else:
            b.typing.pop(self.fold(m.nick), None)
        self.typing_changed.emit(b)

    def typing_now(self, b: Buffer) -> list[str]:
        """Nicks typing in this tab right now (old 'active' ones fall off)."""
        now = time.time()
        for k in [k for k, (_n, t) in b.typing.items() if now - t > self.TYPING_SHOWN]:
            del b.typing[k]
        return [n for n, _t in b.typing.values()]

    def send_typing(self, target: str, state: str) -> bool:
        if not self.client_tag_ok("+typing"):
            return False
        self.send_raw(f"@+typing={state} TAGMSG {target}", quiet=True)
        return True

    def say_reply(self, target: str, text: str, msgid: str) -> None:
        """A message that answers msgid. Without tag support it is just the message."""
        if not msgid or not self.client_tag_ok("+draft/reply") or self.state != "connected" or len(text.encode()) > 380:
            self.say(target, text)
            return
        if self.away and self.cfg.auto_unaway:
            self.set_away(False)
        self.sent_count += 1
        self.send_raw(f"@+draft/reply={msgid} " + build_line("PRIVMSG", target, text))
        if "echo-message" not in self._cap_active:
            self.add(self.buffer(target), SELF, self.nick, self.hide_typed(target, text))

    def te(self, event: str, b: Buffer, kind: str, args, ts: float | None = None, prefix: str = "") -> None:
        """Prints a Text Event with the user's format (prefix: '[Network] ' for another server's window)."""
        if self.print_hook is not None and self.print_hook(event, args):
            return
        from . import tabopts
        fmt = self.cfg.text_events.get(event)
        joins = tabopts.get(self.cfg, b, "joins") if event in tabopts.HIDEABLE else "show"
        if not fmt and event in SHORT and joins in ("short", "hide"):
            fmt = SHORT[event]                 # only the default wording: the user's own Text Events stay as they are
        left, text = render(fmt or EVENTS[event][0], args)
        self.add_to(b, kind, left, text, prefix, ts=ts, hidden=joins == "hide")   # hidden: kept and logged, just not drawn

    def _ctcp_reply_list(self) -> list:
        if self.cfg.ctcp_replies is not None:
            return self.cfg.ctcp_replies
        return [["TIME", "nctcp %s TIME %t"], ["PING", "nctcp %s PING %d"]]

    def _ctcp_request(self, nick: str, verb: str, rest: str, own: bool = False) -> None:
        now = time.time()
        if verb == "DCC":
            if own:
                return                          # 0.8.5: our own offer echoed back is not an offer to us
            if self.on_dcc is not None:
                self.on_dcc(self, nick, rest)
            else:
                self.add(self._front(), INFO, "*", f"{nick} offered a file or direct chat. BChat can't accept these here.")
            return
        if not own and not self._ctcp_allowed(nick, now):     # 0.8.5: someone past their share of the flood buffer
            return
        where, prefix = self._show_where("ctcp", nick)        # 0.8.7: Settings > Windows
        self.te("CTCP Generic", where, INFO, (verb, nick), prefix=prefix)
        if not self.cfg.ctcp_reply_enabled:                  # 0.8.7 /ctcps off: shown and logged, never answered
            return
        mine = [c for n, c in self._ctcp_reply_list() if n.upper() == verb.upper()]
        if mine and self.on_command is not None:
            from . import full_version
            values = {"d": rest, "e": self.net.name, "m": "Windows", "n": self.nick, "s": nick, "t": time.ctime(),
                      "v": f"BChat {full_version()}"}
            self._ctcp_answer = (self.fold(nick), own)
            try:
                for cmd in mine:
                    if not cmd.startswith("!"):     # others can trigger these, so never a program
                        self.on_command(self, "/" + re.sub(r"%([demnstv])", lambda m: values[m.group(1)], cmd).lstrip("/"))
            finally:
                self._ctcp_answer = None
            return
        if verb == "VERSION":
            from . import full_version
            self._ctcp_reply(nick, own, f"\x01VERSION BChat {full_version()} by BajuBesi Labs\x01")
        elif verb == "PING":
            self._ctcp_reply(nick, own, f"\x01PING {rest}\x01")
        elif verb == "TIME":
            self._ctcp_reply(nick, own, f"\x01TIME {time.ctime()}\x01")
        elif verb in ("FINGER", "USERINFO"):
            self._ctcp_reply(nick, own, f"\x01{verb} {self._identity('real')}\x01")
        elif verb == "SOURCE":
            self._ctcp_reply(nick, own, "\x01SOURCE BChat by BajuBesi Labs\x01")
        elif verb == "CLIENTINFO":
            self._ctcp_reply(nick, own, "\x01CLIENTINFO ACTION CLIENTINFO FINGER PING SOURCE TIME USERINFO VERSION\x01")

    @staticmethod
    def _matches(nick: str, patterns: str) -> bool:
        low = lower(nick)
        return any(fnmatch.fnmatchcase(low, lower(p.strip())) for p in patterns.split(",") if p.strip())

    def _is_hilite(self, text: str, sender: str = "", target: str = "") -> bool:
        """Highlight rules (highlights.find); the rule that matched is kept in last_hilite for the colour and alerts."""
        from .highlights import find
        self.last_hilite = find(self.cfg, self.nick, text, sender, self.net.name, target)
        return self.last_hilite is not None

    def _hilite_colour(self) -> str:
        """The matched rule's colour as #rrggbb; "" = the theme's highlight colour."""
        r = getattr(self, "last_hilite", None)
        if not r or r.get("colour", "") in ("", None):
            return ""
        from .highlightdialog import colour_of
        return colour_of(self.cfg.theme, r["colour"])

    def _ctcp_ping_out(self, nick: str, text: str) -> tuple:
        """0.8.5: '/ctcp X PING' with nothing after it sends the time, and every PING we send is remembered, so the
        reply shows in milliseconds."""
        now = time.time()
        arg = text.strip("\x01")[4:].strip()
        if not arg:
            arg = str(int(now))
            text = f"\x01PING {arg}\x01"
        self._pings_out = {k: t for k, t in self._pings_out.items() if now - t < 120}
        self._pings_out[(self.fold(nick), arg)] = now
        return nick, text

    def _ping_delay(self, nick: str, rest: str) -> float | None:
        """Seconds a PING took: from when we sent it, else from the time inside the reply; None if it isn't a time."""
        now = time.time()
        rest = rest.strip()
        sent = self._pings_out.pop((self.fold(nick), rest), None)
        if sent is None:
            parts = rest.split()
            try:
                if len(parts) == 2 and all(p.isdigit() for p in parts):      # 'seconds microseconds'
                    sent = int(parts[0]) + int(parts[1]) / 1e6
                elif len(parts) == 1:
                    sent = float(parts[0])
                    if sent > 1e11:                                      # milliseconds
                        sent /= 1000
                else:
                    return None
            except ValueError:
                return None
            if not 0 < sent < 4e9:                                       # not a time (nan, inf, 0)
                return None
        return max(0.0, now - sent)

    def _notify(self, b: Buffer, kind: str) -> None:
        """0.8.5: bouncer playback is shown and counted, but old lines make no sound, flash, tray or pop-up."""
        if not self._replaying:
            self.notify.emit(b, kind)

    def _bump(self, b: Buffer, level: int) -> None:
        if level == 3 and not self._replaying:
            self.alert.emit(b)
        if b is not self.current and level >= 2:
            b.unread += 1
            b.mentioned = b.mentioned or (level == 3 and b.kind == CHANNEL)    # a private chat shows its count
        if b is not self.current and level > b.activity:
            b.activity = level
            self.buffer_changed.emit(b)

    def _notice_channel(self, m: Message, text: str):
        """0.6.0: a private notice about a channel (+draft/channel-context tag, or services' '[#chan] text')
        goes to that channel's tab while we're in it."""
        ctx = m.tags.get("+draft/channel-context") or m.tags.get("+channel-context") or ""
        if not ctx and text.startswith("[") and "] " in text:
            ctx = text[1:text.index("] ")]
        if ctx and self.is_channel(ctx):
            b = self.buffers.get(self.fold(ctx))
            if b is not None and b.kind == CHANNEL and b.joined:
                return b
        return None

    def _irc_notice(self, m: Message) -> None:
        target, text = m.param(0), m.param(-1)
        if self.fold(m.nick) == "operserv" and "session limit" in text.lower():
            # services count kills, then auto-ban the whole IP (Anope maxsessionkill), so retrying can lock out every client on it
            self.want_connected = False
            self._reconnect.stop()
            self.add(self.server_buffer, ERROR, "*", f"-OperServ- {text} BChat will not retry: repeated attempts can get this IP banned.")
            return
        if self.oper_sink is not None and self.fold(m.nick) == "operserv" and self.oper_sink(0, m):
            return                                  # the Server bans window reading OperServ's ban lists
        if not self._welcomed and not self.bouncer and "psybnc" in (m.prefix + " " + text).lower():
            self.bouncer = "psyBNC"
        if not self._replaying and "batch" not in m.tags and self.fold(m.nick) != self.fold(self.nick) and "!" in m.prefix:
            self.protection.heard(target, m.nick, text, notice=True)    # 0.9.3 Channel Protection
        if text.startswith("\x01") and text.endswith("\x01"):
            verb, _, rest = text.strip("\x01").partition(" ")
            if self._services_wait and self.fold(m.nick) == "chanserv" and verb.upper() == "VERSION":
                self._services_known("atheme" if "atheme" in rest.lower() else "anope" if "anope" in rest.lower() else "")
                return
            if self.ignored(m.prefix, "T"):
                return
            secs = self._ping_delay(m.nick, rest) if verb.upper() == "PING" else None
            if secs is not None:
                self.add(self._front(), INFO, "*", f"PING reply from {m.nick}: {secs:.3f} s")
                return
            self.add(self._front(), INFO, "*", f"CTCP {verb} reply from {m.nick}: {rest}")
            return
        if self.ignored(m.prefix, "N"):
            return
        if self.ignored(m.prefix, "K"):                   # 0.8.5 /ignore -k: their colours, bold and codes taken out
            text = strip_format(text)
        if not self._welcomed and "invalid password" in text.lower():
            self._login_refused(text)
            return
        if self._ns_wait and self.fold(m.nick) == "nickserv" and any(
                w in text.lower() for w in ("identified", "recognized", "recognised", "incorrect", "isn't registered", "not registered")):
            self._join_all(self._ns_wait)        # NickServ answered (yes or no): no point waiting longer
        if self.chanserv_sink is not None and self.fold(m.nick) == "chanserv" and self.chanserv_sink(text):
            return
        if not m.nick or "." in m.nick or self.state != "connected":
            snotice = self.is_oper and self.cfg.addon_oper and self.cfg.oper_notices and self.state == "connected"
            where = self.buffer("(notices)") if self.cfg.notices_tab or snotice else self.server_buffer    # 0.9.3: an oper's server notices
            self.add(where, NOTICE, "-" + (m.nick or "server") + "-", text, self._ts(m))
            return
        b = self.buffers.get(self.fold(target)) if self.is_channel(target) else self._notice_channel(m, text)
        prefix = ""
        if b is None:                                   # 0.8.7: a private notice: Settings > Windows > Notices
            b, prefix = self._show_where("notices", m.nick)
        self.add_to(b, NOTICE, f"-{m.nick}-", text, prefix, ts=self._ts(m))
        if self.fold(m.nick) != self.fold(self.nick) and not self.ignored(m.prefix, "H"):     # 0.8.5: our own, echoed by the bouncer: no alert; /ignore -h: none
            self._notify(b, "notice")

    def _irc_join(self, m: Message) -> None:
        chan = m.param(0)
        b = self.buffer(chan)
        if self.fold(m.nick) == self.fold(self.nick):
            since = next((ln.ts for ln in reversed(b.lines) if ln.kind in (MSG, SELF, HILITE, ACTION, NOTICE)), 0.0)
            b.joined = True
            b.users.clear()
            b.modes, b.mode_args = "", {}
            self._left.discard(self.fold(chan))          # 0.8.5: joined again, so rejoined after an outage too
            b.key = self._join_keys.pop(self.fold(chan), "") or b.key
            self._names_fresh.discard(self.fold(chan))
            self.add(b, NOW_TALKING, "➤", f"Now talking on {b.name}")
            self.send("MODE", b.name)
            self.fetch_who(b.name)
            if self.history_on():
                self._ask_history(b, since)
            self.buffer_changed.emit(b)
        elif not self.cfg.hide_joinpart:
            self.te("Join", b, JOIN, (m.nick, b.name, m.userhost), self._ts(m))
            self._notify(b, "join")
        joined = User(m.nick, "", m.userhost)
        if "extended-join" in self._cap_active and len(m.params) >= 3:
            joined.account = "" if m.param(1) == "*" else m.param(1)
            joined.realname = m.param(2)
        b.users[self.fold(m.nick)] = joined
        self.users_changed.emit(b)
        self.control.check(b, m.nick)
        if not self._replaying and "batch" not in m.tags:
            self.protection.joined(b, m.nick)
        if not self.cfg.hide_joinpart:
            self._bump(b, 1)

    def _irc_part(self, m: Message) -> None:
        b = self.buffer(m.param(0), False)
        if b is None:
            return
        reason = m.param(1) if len(m.params) > 1 else ""
        if self.fold(m.nick) == self.fold(self.nick):
            b.joined = False
            b.users.clear()
            self._left.add(self.fold(b.name))            # 0.8.5: left on purpose: a reconnect doesn't join it again
            if not self.cfg.keep_on_part:                # 0.9.2: the tab closes; the line shows in the server tab
                self.te("You Part", self.server_buffer, PART, (b.name,))
                self.close_buffer(b)                     # not joined any more, so no second PART goes out
                return
            self.te("You Part", b, PART, (b.name,))
            self.users_changed.emit(b)
            self.buffer_changed.emit(b)
            return
        b.users.pop(self.fold(m.nick), None)
        if not self.cfg.hide_joinpart:
            if reason:
                self.te("Part with Reason", b, PART, (m.nick, m.userhost, b.name, reason), self._ts(m))
            else:
                self.te("Part", b, PART, (m.nick, m.userhost, b.name), self._ts(m))
            self._bump(b, 1)
            self._notify(b, "part")
        self.users_changed.emit(b)

    def _irc_quit(self, m: Message) -> None:
        key = self.fold(m.nick)
        self.protection.quit(m.nick, m.param(-1))     # 0.9.3: netsplit rejoins are not a mass join
        for b in self.buffers.values():
            if key in b.users:
                del b.users[key]
                if not self.cfg.hide_joinpart:
                    self.te("Quit", b, PART, (m.nick, m.param(-1)), self._ts(m))
                    self._bump(b, 1)
                self.users_changed.emit(b)
        private = self.buffers.get(key)
        if private is not None and private.kind == QUERY:
            self.te("Quit", private, PART, (m.nick, m.param(-1)), self._ts(m))

    def _irc_kick(self, m: Message) -> None:
        b = self.buffer(m.param(0), False)
        victim, reason = m.param(1), m.param(2)
        if b is None or not victim:                 # 0.8.5: a KICK naming nobody kicks nobody (not us)
            return
        self.protection.kicked(b, m.nick, victim)
        b.users.pop(self.fold(victim), None)
        if self.fold(victim) == self.fold(self.nick):
            b.joined = False
            b.users.clear()
            if not self.cfg.keep_on_kick and not self.cfg.rejoin_on_kick:   # 0.9.2: rejoining needs the tab
                self.te("You Kicked", self.server_buffer, PART, (b.name, m.nick, reason))
                self._notify(b, "kicked")
                self._notify(b, "kick")
                self.close_buffer(b)                     # not joined any more, so no PART goes out
                self._left.discard(self.fold(b.name))    # a kick isn't leaving on purpose: autojoin still joins it
                return
            self.te("You Kicked", b, PART, (b.name, m.nick, reason))
            self._notify(b, "kicked")
            self.buffer_changed.emit(b)
            now = time.time()
            if self.cfg.rejoin_on_kick and now - b.rejoined_at > 30:       # once: a kick loop can't flood the channel
                b.rejoined_at = now
                key = b.mode_args.get("k", "")
                QTimer.singleShot(3000, lambda name=b.name, key=key: self._rejoin_after_kick(name, key))
        else:
            self.te("Kick", b, PART, (m.nick, victim, b.name, reason))
        self._notify(b, "kick")
        self.users_changed.emit(b)

    def _rejoin_after_kick(self, name: str, key: str) -> None:
        b = self.buffers.get(self.fold(name))
        if self.state == "connected" and b is not None and not b.joined:
            self.send("JOIN", name, *([key] if key else []))

    # --- Flood protection for automatic CTCP replies (0.8.5: mIRC's Options > Flood and /flood) ----------------
    # Once more than cfg.flood_bytes wait in the paced send queue, replies go into a flood buffer instead: at most
    # flood_lines lines (the rest are dropped), at most flood_per_user per person, and a person past their share has
    # their CTCPs ignored for flood_ignore seconds. The buffer goes out one person at a time, through _drain_queue.
    # The help gives the 400-byte default; it gives none for the other three, so config uses its example, /flood 200 10 2 30.
    # What the user types is never queued (see typed()), so it is never held or dropped here.

    def _pending_bytes(self) -> int:
        """Bytes of automatic lines still waiting in the paced send queue."""
        return sum(len(l.encode("utf-8", "replace")) + 2 for l in self._queue)

    def _ctcp_allowed(self, nick: str, now: float) -> bool:
        """False while this person's CTCPs are ignored for going past their share of the flood buffer."""
        key = self.fold(nick)
        until = self._ctcp_ignored.get(key)
        if until is None:
            return True
        if now < until:
            return False
        del self._ctcp_ignored[key]
        return True

    def _ctcp_reply(self, nick: str, own: bool, text: str) -> None:
        """An automatic CTCP reply: into the paced queue, or into the flood buffer while the queue is busy."""
        c = self.cfg
        if own or not (c.flood_on and c.flood_ctcp_on) or self.state != "connected" \
                or (not self._flood_lines and self._pending_bytes() <= c.flood_bytes):
            self.send("NOTICE", nick, text)
            return
        key = self.fold(nick)
        mine = self._flood_lines.get(key)
        if len(mine or ()) >= c.flood_per_user:              # past their share: dropped, and ignored for a while
            if c.flood_ignore > 0 and key not in self._ctcp_ignored:
                self._ctcp_ignored[key] = time.time() + c.flood_ignore
                self.add(self.server_buffer, ERROR, "*", f"CTCP flood from {nick}: ignoring their CTCP for {c.flood_ignore} seconds.")
            return
        if sum(len(q) for q in self._flood_lines.values()) >= c.flood_lines:
            return                                            # the buffer is full: the rest are dropped
        if mine is None:
            mine = self._flood_lines[key] = deque()
            self._flood_order.append(key)
        mine.append(build_line("NOTICE", nick, text))
        if not self._ctcp_held:
            self._ctcp_held = True
            self.add(self._front(), INFO, "*", "CTCP flood: holding back CTCP replies until the send queue empties.")

    def _ctcp_queue_empty(self) -> None:
        """_drain_queue emptied the queue: hand it held replies, one person at a time, up to flood_bytes."""
        if self._flood_feeding:
            return
        moved = False
        self._flood_feeding = True
        try:
            while self._flood_order and self._pending_bytes() <= self.cfg.flood_bytes:
                key = self._flood_order.popleft()
                mine = self._flood_lines.get(key)
                if mine:
                    self._queue.append(mine.popleft())
                    moved = True
                if mine:
                    self._flood_order.append(key)
                else:
                    self._flood_lines.pop(key, None)
        finally:
            self._flood_feeding = False
        if moved:
            self._drain_queue()
        elif self._ctcp_held and not self._flood_lines:
            self._ctcp_held = False
            self.add(self._front(), INFO, "*", "CTCP flood: the send queue is empty, answering CTCP again.")

    def flood_clear(self) -> int:
        """/flood clear: drops the held replies and ends every flood ignore. Returns how many replies were dropped."""
        dropped = sum(len(q) for q in self._flood_lines.values())
        self._flood_lines.clear()
        self._flood_order.clear()
        self._ctcp_ignored.clear()
        self._ctcp_held = False
        return dropped

    def _query_flood(self, nick: str, now: float) -> bool:
        """True = too many new private chats this minute: show it in the server tab instead of a new tab."""
        limits = getattr(self.cfg, "lock_limits", None)
        if limits and limits.get("no_private"):        # 0.6.0 Lock: no new private chats
            if not getattr(self, "_lock_priv_said", False):
                self._lock_priv_said = True
                self.add(self.server_buffer, INFO, "*", "Lock: new private chats show here instead of new tabs.")
            return True
        limit = self.cfg.flood_queries
        times = [t for t in getattr(self, "_new_queries", []) if now - t < 60]
        self._new_queries = times
        if limit > 0 and len(times) < limit:
            times.append(now)
            return False
        if not getattr(self, "_query_flood_said", 0.0) or now - self._query_flood_said > 60:
            self._query_flood_said = now
            self.add(self.server_buffer, INFO, "*", f"{len(times) + 1} new private chats in a minute: "
                                                    "the rest show here instead of new tabs.")
        return True

    def _whois_new_query(self, b: Buffer, nick: str) -> None:
        """Someone opened a private chat with us: who they are goes at the top of the new tab."""
        if nick.startswith("*"):
            return            # ZNC's own *status, *controlpanel...: not people, a WHOIS only says 'No such nick'
        if self.cfg.whois_on_query and self.state == "connected" and b.kind == QUERY:
            now = time.time()
            times = [t for t in getattr(self, "_auto_whois", []) if now - t < 60]
            self._auto_whois = times
            if self.cfg.flood_whois <= 0 or len(times) >= self.cfg.flood_whois:
                return                              # Preferences > Network > Flood: WhoIs on new private chats
            times.append(now)
            self.whois(nick, b)

    def _irc_nick(self, m: Message) -> None:
        old, new = m.nick, m.param(0)
        was_me = self.fold(old) == self.fold(self.nick)
        if was_me:
            self.nick = new
            self.state_changed.emit()
        shared = self.cfg.show_nicks not in ("active", "server")   # 0.8.7 Settings > Windows: one line elsewhere instead
        seen = False
        for b in self.buffers.values():
            u = b.users.pop(self.fold(old), None)
            if u:
                u.nick = new
                b.users[self.fold(new)] = u
                seen = True
                if not was_me and b.kind == CHANNEL:
                    self.protection.nick_changed(b, old, u)
                if shared and was_me:
                    self.te("Your Nick Changing", b, INFO, (new,))
                elif shared:
                    self.te("Change Nick", b, INFO, (old, new))
                self.users_changed.emit(b)
        q = self.buffers.pop(self.fold(old), None)
        if q is not None:
            q.name = new
            self.buffers[self.fold(new)] = q
            self.te("Change Nick", q, INFO, (old, new))
            self.buffer_changed.emit(q)
        where, prefix = (self.server_buffer, "") if self.cfg.show_nicks == "server" else self._active_window()
        if not shared and seen and not was_me and where is not q:
            self.te("Change Nick", where, INFO, (old, new), prefix=prefix)
        if not shared and was_me and where is not self.server_buffer:
            self.te("Your Nick Changing", where, INFO, (new,), prefix=prefix)
        if was_me:
            self.te("Your Nick Changing", self.server_buffer, INFO, (new,))

    def _irc_topic(self, m: Message) -> None:
        b = self.buffer(m.param(0))
        b.topic = m.param(1)
        b.topic_by, b.topic_at = m.nick, self._ts(m)
        self.te("Topic Change", b, TOPIC, (m.nick, b.topic), self._ts(m))
        self.buffer_changed.emit(b)

    def _irc_mode(self, m: Message) -> None:
        target = m.param(0)
        if not self.is_channel(target):
            if self.fold(target) == self.fold(self.nick):
                self._own_modes(m.param(1))
            self.te("Your Modes", self.server_buffer, INFO, (target, " ".join(m.params[1:])))
            return
        b = self.buffer(target)
        if self.cfg.raw_modes:   # Advanced: "Display MODEs in raw form"
            self.add(b, INFO, "*", f"{m.nick} sets mode {' '.join(m.params[1:])}")
            self._apply_modes(b, m.params[1:], actor=m.nick)
        else:
            self._apply_modes(b, m.params[1:], m.nick)

    def _own_modes(self, modes: str) -> None:
        """0.9.3 Oper tools: our own user modes changed; +o turns the Oper tools on, -o off."""
        sign = "+"
        for c in modes:
            if c in "+-":
                sign = c
            elif c == "o":
                self._set_oper(sign == "+")
            elif c == "w":
                self.wallops_on = sign == "+"

    def _note_ircd(self, n: int, p: list[str], rest: str) -> None:
        """0.9.3 Oper tools: the server software from 004 (version), or from 002 / 351 when 004 didn't say."""
        if n == 4:
            self.ircd_version = p[2] if len(p) > 2 else self.ircd_version
        elif not self.ircd_version:
            found = re.search(r"version (\S+)", rest) if n == 2 else None
            self.ircd_version = found.group(1) if found else (p[1] if n == 351 and len(p) > 1 else "")

    @staticmethod
    def _keep_key(b: Buffer, key: str) -> None:
        """0.8.5: a channel key from +k or 324; '-k' clears it. Servers hide it from non-members as '*'."""
        if not key:
            b.key = ""
        elif key not in ("*", "<key>"):
            b.key = key

    def _apply_modes(self, b: Buffer, params: list[str], who: str = "", actor: str = "") -> None:
        if not params:
            return
        actor = actor or who        # who set it, even when the lines are shown raw (Protect needs it)
        letters, args = params[0], list(params[1:])
        sign = "+"
        changed = False
        before = b.mode_text()
        for c in letters:
            if c in "+-":
                sign = c
            elif c in self.prefix_modes:
                pfx = self.prefix_chars[self.prefix_modes.index(c)]
                nick = args.pop(0) if args else ""
                u = b.users.get(self.fold(nick))
                if u:
                    if sign == "+" and pfx not in u.prefixes:
                        u.prefixes += pfx
                    elif sign == "-":
                        u.prefixes = u.prefixes.replace(pfx, "")
                    changed = True
                    self.protection.mode(b, actor, sign, c, nick, prefix=True)
                    if sign == "-":
                        self.control.mode_taken(b, actor, pfx, nick)
                    elif pfx == "@" and self.fold(nick) == self.fold(self.nick):
                        for other in list(b.users.values()):      # just got @: the people already here
                            self.control.check(b, other.nick)
                if who:
                    event = {("@", "+"): "Channel Operator", ("@", "-"): "Channel DeOp", ("+", "+"): "Channel Voice", ("+", "-"): "Channel DeVoice"}.get((pfx, sign))
                    if event:
                        self.te(event, b, INFO, (who, nick))
                    else:
                        label = {"@": "channel operator status", "%": "channel half-operator status", "+": "voice"}.get(pfx, f"mode {c}")
                        self.add(b, INFO, "*", f"{who} {'gives' if sign == '+' else 'removes'} {label} {'to' if sign == '+' else 'from'} {nick}")
            else:
                has_arg = c in self.modes_list or c in self.modes_key or (c in self.modes_on_set and sign == "+")
                arg = args.pop(0) if has_arg and args else ""
                if c == "b" and sign == "+":
                    self.control.banned(b, actor, arg)
                self.protection.mode(b, actor, sign, c, arg)
                if c not in self.modes_list:
                    if sign == "+":
                        if c not in b.modes:
                            b.modes += c
                        if arg:
                            b.mode_args[c] = arg
                    else:
                        b.modes = b.modes.replace(c, "")
                        b.mode_args.pop(c, None)
                    if c == "k":
                        self._keep_key(b, arg if sign == "+" else "")   # 0.8.5: for the rejoin
                if who:
                    if c == "b":
                        left, text = render(self.cfg.text_events.get("Channel Ban" if sign == "+" else "Channel UnBan") or EVENTS["Channel Ban" if sign == "+" else "Channel UnBan"][0], (who, arg))
                    elif c == "k" and sign == "+":
                        text = f"{who} sets channel keyword to {arg}"
                    else:
                        text = f"{who} sets mode {sign}{c}{(' ' + arg) if arg else ''}"
                    self.add(b, INFO, "*", text)
        if b.mode_text() != before:
            self.buffer_changed.emit(b)
        if changed:
            self.users_changed.emit(b)

    def _irc_away(self, m: Message) -> None:
        if self.fold(m.nick) in {self.fold(n) for n in self._friends_here()}:
            self._friend_away(m.nick, m.params[-1] if m.params and m.params[-1] else None)
        away = bool(m.params and m.params[-1]) and self.cfg.away_track
        key = self.fold(m.nick)
        for b in self.buffers.values():
            u = b.users.get(key)
            if u and u.away != away:
                u.away = away
                self.users_changed.emit(b)

    def _irc_chghost(self, m: Message) -> None:
        key = self.fold(m.nick)
        for b in self.buffers.values():
            u = b.users.get(key)
            if u:
                u.host = f"{m.param(0)}@{m.param(1)}"

    def _irc_invite(self, m: Message) -> None:
        if self.ignored(m.prefix, "I"):
            return
        if self.fold(m.param(0)) != self.fold(self.nick):  # invite-notify: someone else was invited
            b = self.buffer(m.param(1), False)
            if b is not None:
                self.add(b, INFO, "*", f"{m.nick} has invited {m.param(0)} to {m.param(1)}")
            return
        self.te("Invited", self._front(), INFO, (m.param(1), m.nick, m.userhost))
        self.last_invite = (m.param(1), m.nick)
        self._notify(self._front(), "invite")
        b = self.buffers.get(self.fold(m.param(1)))
        if self.is_channel(m.param(1)) and not (b is not None and b.joined):
            self.invited.emit(self, m.param(1), m.nick)

    # numerics --------------------------------------------------------------------

    def userhost_lookup(self, nick: str) -> None:
        """0.8.5: /ban, /ignore for someone whose address BChat doesn't know: a /userhost lookup, as mIRC does.
        The server always answers it (empty when the nick isn't on IRC), so nothing is left waiting."""
        key = self.fold(nick)
        if key not in self._addr_waiting:
            self._addr_waiting.append(key)
            self.send("USERHOST", nick)

    def _addr_answer(self, m: Message) -> bool:
        """302 nick*=+user@host (one nick per ask). True when it was ours. Empty: the oldest ask isn't on IRC."""
        items = m.param(-1).split()
        if not items:
            self.address_found.emit(self._addr_waiting.pop(0), "")
            return True
        mine = False
        for item in items:
            nick, _, host = item.partition("=")
            key = self.fold(nick.rstrip("*"))
            if key in self._addr_waiting:
                self._addr_waiting.remove(key)
                self.address_found.emit(nick.rstrip("*"), host.lstrip("+-"))
                mine = True
        return mine

    def _dns_answer(self, m: Message) -> bool:
        from . import everyday
        return everyday.userhost_answer(self, m)

    def userhost_typed(self, b, nicks: list[str]) -> None:
        """0.8.8 /userhost nick [nick...] (the server takes up to 5): the answer goes to the tab it was typed in."""
        self._uh_typed.append((b, {self.fold(n) for n in nicks}, list(nicks), time.time()))
        self.send("USERHOST", *nicks)

    def _userhost_typed_answer(self, m: Message) -> bool:
        """302 for a typed /userhost: 'ana is ana@host (here), bob is ~bob@10.0.0.2 (away)'. Matched by its nicks,
        so a /ban or /dns lookup that crossed it still gets its own answer. True when it was printed."""
        now = time.time()
        self._uh_typed = [e for e in self._uh_typed if now - e[3] < 30]
        got = {}
        for item in m.param(-1).split():
            nick, eq, host = item.partition("=")
            if eq and nick:
                oper = nick.endswith("*")
                nick = nick.rstrip("*")
                got[self.fold(nick)] = (nick, oper, host[:1] == "-", host.lstrip("+-"))
        others = bool(self._addr_waiting or self.dns_waiting or self._local_waiting)
        for i, (b, asked, typed, _when) in enumerate(self._uh_typed):
            if (got and set(got) <= asked) or (not got and i == 0 and not others):
                break
        else:
            return False
        del self._uh_typed[i]
        parts = []
        for n in typed:
            key = self.fold(n)
            if key in got:
                nick, oper, away, host = got.pop(key)
                parts.append(f"{nick} is {host} ({'away' if away else 'here'})" + (" (IRC operator)" if oper else ""))
            elif not any(p.startswith(f"{n} isn't") for p in parts):
                parts.append(f"{n} isn't on IRC")
        target = b if b in self.all_buffers() else self.server_buffer
        self.add(target, INFO, "*", ", ".join(parts))
        if self._addr_waiting and any(self.fold(n) in self._addr_waiting for n in typed):
            self._addr_answer(m)                      # a /ban lookup for the same nick is answered too
        return True

    def flush_queue(self) -> int:
        """0.8.8 /flush: drop every line still waiting in the flood-protection send queue (and CTCP replies held
        back for it). Returns how many were dropped."""
        dropped = len(self._queue) + sum(len(q) for q in self._flood_lines.values())
        self._queue.clear()
        self._flood_lines.clear()
        self._flood_order.clear()
        self._ctcp_held = False                       # flood ignores stay: /flood clear ends those
        return dropped

    def _numeric(self, n: int, m: Message) -> None:
        if self._starttls == "waiting" and self._starttls_answer(n, m):
            return
        if n in (376, 422) and self._friends_wait:
            self._friends_after_005()
        if n in (376, 422) and self._welcomed and not self._performed:
            gen = self._conn_gen                   # end of the welcome text: log in and join a moment later
            QTimer.singleShot(1000, lambda: self._perform(gen))
        if n == 396 and self._ns_wait:                  # hidden host set: NickServ has logged us in
            self._join_all(self._ns_wait)
        if n in (372, 375, 376, 422):
            if self.cfg.skip_motd and not self.motd_asked:
                return                             # Preferences > General: skip the welcome message (/motd shows it)
            if n == 422:
                self.motd_asked = False
        if n == 401 and self._znc_guess and self.fold(m.param(1)) == "*status":
            # 0.6.1: no *status here, so the znc.in/ caps came from the server itself (Ergo): not a bouncer
            self.bouncer, self._znc_guess, self._version_wait = "", False, 0.0
            self.state_changed.emit()
            return
        p = m.params
        rest = " ".join(p[1:])
        if n in (2, 4, 351):
            self._note_ircd(n, p, rest)             # 0.9.3 Oper tools: which server software this is
        elif n == 221:
            self._set_oper("o" in m.param(1).split("-")[0])      # our own user modes in full (+iow): oper or not
            self.wallops_on = "w" in m.param(1).split("-")[0]
        if self.oper_sink is not None and n in (216, 219, 223, 225, 280) and self.oper_sink(n, m):
            return                                  # the Server bans window's STATS answers
        if n == 1:
            self.nick = m.param(0) or self.nick     # 0.8.5: a 001 without a nick doesn't empty ours
            self._ison_asked.clear()                # 0.8.5: answers to the last link's ISONs never come
            for st in self.friend_state.values():
                st["known"] = False                 # 0.8.5: after a reconnect, friends online are announced again
            self.server_name = m.prefix
            self._welcomed = True
            self._ident_stop()                      # 0.8.8: ident is only for the login
            self.online_since = time.time()
            self._set_state("connected")
            self.notify.emit(self.server_buffer, "connect")
            self._who.start()
            self.add(self.server_buffer, INFO, "*", m.param(-1))
            if self._down_since:
                self.add(self.server_buffer, INFO, "*", f"Connected. Back after {duration(time.time() - self._down_since)}.")
            self._tries, self._down_since, self._banned = 0, 0.0, False
            for b in self._told_down:               # 0.8.5: one line in each tab that was told "Disconnected"
                if self.buffers.get(self.fold(b.name)) is b:
                    self.add(b, INFO, "*", "Reconnected.")
            self._told_down, self._next_nick = [], ""
            if self._away_msg:
                self.send("AWAY", self._away_msg)   # 0.8.5: the new link isn't away until we say so again
            if self.cfg.invisible:
                self.send_raw(f"MODE {self.nick} +i")  # 0.8.5: Invisible mode (Preferences > Advanced)
            self._move_to_top()
            self._after_welcome()
        elif n in (321, 322, 323) and self.list_sink is not None:
            if n == 322:
                self.list_sink.list_item(m.param(1), int(m.param(2)) if m.param(2).isdigit() else 0, m.param(3))
            elif n == 323:
                self.list_sink.list_end()
        elif n in (367, 348, 346) and self.fold(m.param(1)) in self.ban_sinks:
            self.ban_sinks[self.fold(m.param(1))].ban_item({367: "b", 348: "e", 346: "I"}[n], m.param(2), m.param(3), m.param(4))
        elif n in (368, 349, 347) and self.fold(m.param(1)) in self.ban_sinks:
            self.ban_sinks[self.fold(m.param(1))].ban_end({368: "b", 349: "e", 347: "I"}[n])
        elif n in (367, 348, 346, 368, 349, 347):
            self._list_line(n, m)                   # 0.8.5: no Ban List window open: a readable line, not raw text
        elif n == 302 and self._uh_typed and self._userhost_typed_answer(m):
            pass                                               # 0.8.8: a /userhost the user typed
        elif n == 302 and self._addr_waiting and self._addr_answer(m):
            pass
        elif n == 302 and self.dns_waiting and self._dns_answer(m):
            pass
        elif n in (302, 340) and self._local_waiting:          # USERHOST / USERIP for ourselves
            self._local_waiting -= 1
            reply = m.param(-1).strip().split()
            host = reply[0].split("@")[-1] if reply else ""
            self._local_found(host)
        elif n == 364:                                         # /links: one tidy line per server
            hops, _, info = m.param(-1).partition(" ")
            name, uplink = m.param(1), m.param(2)
            self._links_seen = getattr(self, "_links_seen", 0) + 1
            where = "the server you're on" if hops == "0" else f"{hops} hop{'' if hops == '1' else 's'} away, via {uplink}"
            self.add(self.server_buffer, INFO, "*", f"{name}: {where}" + (f" ({info})" if info.strip() else ""))
        elif n == 365:
            count, self._links_seen = getattr(self, "_links_seen", 0), 0
            self.add(self.server_buffer, INFO, "*", f"{count} server{'' if count == 1 else 's'} on {self.net.name}.")
        elif n == 303 and self._ison_asked and self._ison_asked[0] is not None:
            asked = self._ison_asked.popleft()      # 0.8.5: only the friends this ISON asked about
            on = {self.fold(x) for x in m.param(-1).split()}
            for nick in self._friends_here():
                if self.fold(nick) in asked:
                    self._friend_online(nick, self.fold(nick) in on)
        elif n == 303:
            if self._ison_asked:
                self._ison_asked.popleft()          # a typed /ison: shown as it is, friends' status untouched
            self.add(self.server_buffer, INFO, "*", rest)
        elif n in (730, 731):
            for item in m.param(-1).split(","):
                self._friend_online(item.split("!")[0], n == 730)
        elif n == 734:
            # 0.8.5: ERR_MONLISTFULL :srv 734 me <limit> <nicks> :Monitor list is full.
            self.add(self.server_buffer, ERROR, "*", f"Friends List: the server watches at most {m.param(1)} nicks, "
                                                     f"so {m.param(2).replace(',', ', ')} can't be watched.")
        elif n in (732, 733):
            pass
        elif n in (600, 601, 604, 605, 602, 603, 606, 607, 598, 599, 609):
            # WATCH: :srv 604 me nick user host ts :is online / 600 logged on / 601 off / 605 offline / 598 away / 599 back
            if n in (600, 604, 601, 605):
                self._friend_online(m.param(1), n in (600, 604))
                if n in (601, 605):
                    self.friend_state.get(self.fold(m.param(1)), {}).pop("away", None)
            elif n in (598, 609):
                self._friend_online(m.param(1), True)
                self._friend_away(m.param(1), m.param(-1) if n == 598 and len(m.params) > 5 else "")
            elif n == 599:
                self._friend_away(m.param(1), None)
        elif n == 5:
            self._isupport(p[1:-1])
            self.add(self.server_buffer, INFO, "*", " ".join(p[1:]))
        elif n in (305, 306):
            self.away = n == 306
            self.state_changed.emit()
            self.add(self._front(), INFO, "*", m.param(-1))
        elif n == 324:
            b = self.buffer(m.param(1), False)
            if b is not None:
                b.modes = m.param(2).lstrip("+")
                values = list(p[3:])
                b.mode_args = {c: values.pop(0) for c in b.modes if c in self.modes_key + self.modes_on_set and values}
                self._keep_key(b, b.mode_args.get("k", "*") if "k" in b.modes else "")   # 0.8.5: for the rejoin
                self.buffer_changed.emit(b)
                self.add(b, INFO, "*", f"Channel {b.name} modes: {' '.join(p[2:])}")
        elif n == 329:
            pass
        elif n in (331, 332, 333):
            self._topic_numeric(n, m)
        elif n == 353:
            self._names(m)
        elif n == 366:
            self._names_fresh.discard(self.fold(m.param(1)))
            self._rebuilt(m.param(1))
        elif n == 352:
            self._who_reply(m)
        elif n == 354:
            self._whox_reply(m)
        elif n == 900:
            self.add(self.server_buffer, INFO, "*", m.param(-1))
            if self._ns_wait:
                self._join_all(self._ns_wait)
        elif n == 903:
            self._sasl_ok = True
            self._sasl_done(True, "SASL login successful.")
        elif n == 907:
            self._sasl_state = ""                 # 0.8.5: already logged in is not a failure
            self._sasl_done(True, "SASL: already logged in.")
        elif n in (902, 904, 905, 906, 908):
            if n != 908 and self._sasl_state == "external":
                self._sasl_done(False, "Certificate login failed: NickServ doesn't know this certificate yet. Log in once with "
                                       "your password, then Edit Network > Add to NickServ.")
            elif n != 908:
                self._sasl_done(False, f"SASL login failed: {m.param(-1)}")
        elif n == 465:
            self._ban_seen(m.param(-1))
        elif n == 464 and not self._welcomed:
            self._login_refused(m.param(-1))       # 0.8.5: only before 001; a wrong /oper password later is just an error line
        elif n == 381:
            self.add(self._oper_tab(), INFO, "*", rest)
            self._set_oper(True)                    # 0.9.3 Oper tools turn on
        elif n in self.JOIN_REFUSED and self._join_refused(n, m):
            pass
        elif n == 471:
            self.add(self._front(), ERROR, "*", f"Cannot join {m.param(1)} (User limit reached).")
        elif n == 473:
            self.add(self._front(), ERROR, "*", f"Cannot join {m.param(1)} (Channel is invite only).")
        elif n == 474:
            self.add(self._front(), ERROR, "*", f"Cannot join {m.param(1)} (You are banned).")
        elif n == 475:
            self.add(self._front(), ERROR, "*", f"Cannot join {m.param(1)} (Requires keyword).")
        elif n == 315:
            pass
        elif n in (311, 312, 317, 318, 319, 301, 313, 320, 330, 335, 338, 344, 378, 379, 671, 276, 307, 275, 569, 314, 369):
            # 569 = UnrealIRCd's RPL_WHOISASN ("is connecting from AS9930 [provider]"), above 400 so named here
            # 314/369 = /whowas (0.8.5: with its 312, all in the tab it was typed in)
            self._whois_line(n, m)
        elif len(p) >= 3 and n < 400 and self.fold(m.param(1)) in (self._whois_nick, *self._silent_whois):
            # servers add their own whois lines; XChat calls these "WhoIs Special"
            self._whois_line(n, m)
        elif n == 433 or n == 436 or (n == 437 and not self.is_channel(m.param(1))):
            self._nick_taken(m.param(1))           # 0.8.5: 437 'nick temporarily unavailable' is the same
        elif n == 432:
            self.add(self.server_buffer, ERROR, "*", f"Nick not accepted: {m.param(1)}")
            if not self._welcomed:
                self._nick_taken()
        elif 400 <= n < 600:
            self.add(self._front(), ERROR, "*", " ".join(p[1:]))
        elif n == 376 and self.motd_asked:
            self.motd_asked = False
            self.add(self.server_buffer, INFO, "*", rest)
        elif n in (372, 375):
            # MOTD body: the server's own "- " becomes the dim marker, like XChat/AdiIRC
            self.add(self.server_buffer, INFO, "-", rest[2:] if rest.startswith("- ") else rest.lstrip("-"))
        elif n in (376, 422, 2, 3, 4, 42, 250, 251, 252, 253, 254, 255, 265, 266, 396):
            self.add(self.server_buffer, INFO, "*", rest)
        else:
            self.add(self._front() if n in (221, 221) else self.server_buffer, INFO, "*", rest)

    def _oper_tab(self) -> Buffer:
        """0.8.5: the 381 answer ('You are now an IRC operator') shows in the tab where /oper was typed."""
        wait, self._oper_wait = self._oper_wait, None
        if self._route is not None:
            return self._route
        if wait is not None and time.time() - wait[1] < 120 and wait[0] in self.all_buffers():
            return wait[0]
        return self.server_buffer

    def _topic_numeric(self, n: int, m: Message) -> None:
        # /topic #other, for a channel with no tab, shows here and must not open a tab
        name = m.param(1)
        b = self.buffers.get(self.fold(name))
        target = b or self._front()
        if n == 331:
            if b is not None:
                b.topic = ""
                self.buffer_changed.emit(b)
        elif n == 332:
            self.te("Topic", target, TOPIC, (name, m.param(-1)))
            if b is not None:
                b.topic = m.param(-1)
                self.buffer_changed.emit(b)
        else:
            when = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(int(m.param(3) or 0))) if m.param(3).isdigit() else "?"
            self.te("Topic Creation", target, TOPIC, (name, m.param(2).split("!")[0], when))
            if b is not None:
                b.topic_by = m.param(2).split("!")[0]
                b.topic_at = float(m.param(3)) if m.param(3).isdigit() else 0.0
                self.buffer_changed.emit(b)

    def set_casemapping(self, value: str) -> None:
        """FINDING-01: fold nicks and channels the way this server does, and re-key what we already hold."""
        value = (value or "rfc1459").strip().lower()
        fold = folder(value)
        if value == self.casemapping and fold is self.fold:
            return
        self.casemapping, self.fold = value, fold
        # keys made under the old folding: rebuild from the real names where we have them
        self.buffers = {fold(b.name): b for b in self.buffers.values()}
        for b in self.buffers.values():
            b.users = {fold(u.nick): u for u in b.users.values()}
            b.typing = {fold(nick): (nick, when) for nick, when in b.typing.values()}
        self.ban_sinks = {fold(w.channel if hasattr(w, "channel") else w.b.name): w for w in self.ban_sinks.values()}
        # these only hold folded keys; refolding is right for every mapping change seen in practice
        self.friend_state = {fold(k): v for k, v in self.friend_state.items()}
        self._away_seen = {fold(k): v for k, v in self._away_seen.items()}
        self._silent_whois = {fold(k): v for k, v in self._silent_whois.items()}
        self.whois_cache = {fold(k): v for k, v in self.whois_cache.items()}
        self._names_fresh = {fold(x) for x in self._names_fresh}
        self.focus_next = fold(self.focus_next)
        self._whois_nick = fold(self._whois_nick)

    def _isupport(self, tokens: list[str]) -> None:
        for t in tokens:
            k, _, v = t.partition("=")
            if k == "PREFIX" and v.startswith("("):
                modes, _, chars = v[1:].partition(")")
                if modes and len(modes) == len(chars):
                    self.prefix_modes, self.prefix_chars = modes, chars
            elif k == "MONITOR":
                self._monitor = True
            elif k == "WATCH":
                self._watch = True
            elif k == "EXTBAN" and "," in v:
                pre, _, types = v.partition(",")
                self.extban = (pre, types)
            elif k == "CHANTYPES" and v:
                self.chantypes = v
            elif k == "STATUSMSG":
                self.statusmsg = v
            elif k == "WHOX":
                self.whox = True
            elif k == "USERIP":
                self.userip = True
            elif k == "CHATHISTORY":
                self.chathistory_max = int(v) if v.isdigit() else 0
            elif k == "CHANMODES" and v.count(",") >= 2:
                self.modes_list, self.modes_key, self.modes_on_set = v.split(",")[:3]
                if v.count(",") >= 3:
                    self.modes_flags = v.split(",")[3]
            elif k == "CLIENTTAGDENY":
                self.client_tag_deny = v
            elif k == "MODES" and v.isdigit() and int(v) > 0:
                self.max_modes = int(v)
            elif k == "CASEMAPPING":
                self.set_casemapping(v)
            elif k == "NETWORK" and v:
                self.network_token = v
                self.server_buffer.name = v if not self.net.name else self.net.name
                self.buffer_changed.emit(self.server_buffer)

    # --- Network > Local: the address DCC offers carry, found the way mIRC does -------------

    def find_local(self) -> None:
        """Typed IP/host win; else this PC, the IRC server (USERIP if offered, else USERHOST) or a website."""
        c = self.cfg
        if c.dcc_ip.strip() or c.local_host.strip():
            self._local_found(c.dcc_ip.strip() or c.local_host.strip())
        elif c.local_lookup == "server":
            self._local_waiting += 1
            self.send_raw(f"{'USERIP' if self.userip else 'USERHOST'} {self.nick}", quiet=True)
        elif c.local_lookup == "website":
            self._ask_website()
        else:
            self._local_found(self.sock.localAddress().toString())

    def _ask_website(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
        site = self.cfg.local_site.strip() or "icanhazip.com"
        url = QUrl(site if "://" in site else "https://" + site)
        if getattr(self, "_web", None) is None:
            self._web = QNetworkAccessManager(self)
        req = QNetworkRequest(url)
        req.setTransferTimeout(10000)
        reply = self._web.get(req)

        def done():
            text = bytes(reply.readAll()).decode("utf-8", "replace")
            reply.deleteLater()
            m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b|([0-9a-fA-F:]{3,}:[0-9a-fA-F:]+)", text)
            if m:
                self._local_found(m.group(0))
            else:
                self.add(self.server_buffer, ERROR, "*", f"Local host: {site} didn't give an address. "
                                                         "Network > Local can use the IRC server instead.")
        reply.finished.connect(done)

    def _local_found(self, host: str) -> None:
        """host is a name or an address: look up the other half, keep both, print the Local Host line."""
        if not host:
            return
        from ipaddress import ip_address
        try:
            ip_address(host)
            self.external_ip = host            # an address already: DCC can use it now, the name can follow
        except ValueError:
            pass
        self._local_asked = host
        if not getattr(self, "_host_info_wired", False):
            self.host_info.connect(self._own_host_found)
            self._host_info_wired = True
        look_up(self, host, lambda info: self.host_info.emit(info))

    def _own_host_found(self, info) -> None:
        from ipaddress import ip_address
        asked = getattr(self, "_local_asked", "") or info.hostName()
        try:
            ip_address(asked)
            ip, name = asked, info.hostName()
        except ValueError:
            ip, name = "", asked
            for a in info.addresses():
                if a.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                    ip = a.toString()
                    break
        if name == ip:
            name = ""                                           # no name for it: mIRC says unknown
        self.external_ip = ip or self.external_ip
        self.local_name = name
        if self.cfg.local_show:
            self.te("Local Host", self.server_buffer, INFO, (name or "unknown", ip or "unknown"))

    def _move_to_top(self) -> None:
        """0.8.6 'Move to top on connect': the server that just let us in goes first in its network's list."""
        servers = self.net.servers
        if not self.cfg.move_to_top or not 0 < self.server_index < len(servers):
            return
        servers.insert(0, servers.pop(self.server_index))
        self.server_index = 0
        self.servers_moved.emit()

    def _after_welcome(self) -> None:
        self._tick()            # first lag reading now, not after the 15 s keepalive
        if self.bouncer == "ZNC":
            self._version_wait = time.time()       # one quiet question; the answer is taken, not shown
            self.send_raw("PRIVMSG *status :version", quiet=True)
            QTimer.singleShot(4000, self._say_bouncer)
        elif self.bouncer:
            self._say_bouncer()
        self._friends_wait = int(time.time() * 1000) or 1     # FINDING-02: 005 (MONITOR/WATCH) comes after 001
        ticket = self._friends_wait
        QTimer.singleShot(5000, lambda: self._friends_after_005(ticket))
        if self.cfg.local_find:              # the address others can reach us on, for DCC offers
            self.find_local()
        # 0.8.2: NickServ, connect commands and joins wait for the end of the welcome text (376/422, see
        # _numeric), so they don't land in the middle of it. No welcome text at all: go ahead after 5 s.
        gen = self._conn_gen
        QTimer.singleShot(5000, lambda: self._perform(gen))

    def _perform(self, gen: int) -> None:
        if gen != self._conn_gen or self._performed or self.state != "connected":
            return
        self._performed = True
        ns_login = bool(self.net.nickserv)
        if ns_login:
            self.send_raw(f"PRIVMSG NickServ :IDENTIFY {self.net.nickserv}", secret=True)
        for cmd in self.net.commands:
            if self.on_command is not None and cmd.strip():
                # 0.8.5: run as if typed: /msg NickServ, /join, aliases and $me work, and passwords stay hidden
                # the usual way. Before, the line went to the server raw ('msg NickServ ...' isn't a server command)
                line = re.sub(r"\$(me|network)\b", lambda v: self.nick if v.group(1) == "me" else self.net.name,
                              cmd.strip().lstrip("/"))
                self.on_command(self, "/" + line)
            elif cmd.strip():
                self.send_raw(cmd.lstrip("/"))
        has_joins =bool(self.net.autojoin or self.join_once or any(b.kind == CHANNEL for b in self.buffers.values()))
        if ns_login and has_joins and self.net.join_after_login and not self._sasl_ok:
            self._ns_wait = gen                # joined before the login, a +r channel would refuse us
            self.add(self.server_buffer, INFO, "*", "Waiting for NickServ before joining...")
            QTimer.singleShot(10000, lambda: self._join_all(gen))
        else:
            self._join_all(gen)

    def _key_of(self, name: str) -> str:
        """0.8.5: the key we know for this channel (our JOIN, +k or 324), for the rejoin."""
        b = self.buffers.get(self.fold(name))
        return b.key if b is not None and b.kind == CHANNEL else ""

    def _join_all(self, gen: int) -> None:
        if gen != self._conn_gen or self._joins_sent or self.state != "connected":
            return
        self._joins_sent = True
        self._ns_wait = 0
        rejoin = [b.name for b in self.buffers.values() if b.kind == CHANNEL]
        # 0.8.3: a bouncer has already put us back in its channels (JOIN + names before this). Asking again only
        # makes the server answer, and one at its channel limit answers 'too many channels' even for those.
        inside = {k for k, b in self.buffers.items() if b.kind == CHANNEL and b.joined}
        auto = set()
        if self.net.autojoin:
            parts = self.net.autojoin.strip().split(" ", 1)
            names = [n.strip() for n in parts[0].split(",")]
            keys = [k.strip() for k in parts[1].split(",")] if len(parts) > 1 else []
            auto = {self.fold(n) for n in names if n}
            pairs = [(n, keys[i] if i < len(keys) else "") for i, n in enumerate(names)
                     if n and self.fold(n) not in inside and self.fold(n) not in self._left]   # 0.8.5: not ones we left
            pairs = [(n, k or self._key_of(n)) for n, k in pairs]                               # 0.8.5: a key we learnt
            if pairs:
                keyed = [p for p in pairs if p[1]] + [p for p in pairs if not p[1]]   # keys line up from the front
                self.send("JOIN", ",".join(n for n, _ in keyed),
                          *([",".join(k for _, k in keyed if k)] if any(k for _, k in keyed) else []))
        for name in rejoin:
            if self.fold(name) not in auto and self.fold(name) not in inside and self.fold(name) not in self._left:
                key = self._key_of(name)
                self.send("JOIN", name, key) if key else self.send("JOIN", name)
        for name, key in self.join_once:
            if self.fold(name) not in {self.fold(n) for n in rejoin}:
                self.focus_next = self.fold(name)
                self.send("JOIN", name, *([key] if key else []))
        self.join_once = []

    # --- bouncers (0.4.0) ------------------------------------------------------------------

    def _spot_bouncer(self, offered) -> None:
        """By what the bouncer says it can do, never by its name. 0.6.1: servers borrow bouncer capabilities too
        (Ergo offers soju.im/webpush, znc.in/playback and znc.in/self-message), so soju needs its own
        soju.im/bouncer-networks, and znc.in/ caps only make ZNC a guess until *status answers (or isn't there)."""
        if "soju.im/bouncer-networks" in offered:
            self.bouncer = "soju"
        elif any(c.startswith("znc.in/") for c in offered):
            self.bouncer = "ZNC"
            self._znc_guess = True

    def bouncer_text(self) -> str:
        return f"{self.bouncer} {self.bouncer_version}".strip()

    def _say_bouncer(self) -> None:
        """One line in the server tab, once per connection."""
        if self._bouncer_said or not self.bouncer or self.state != "connected":
            return
        self._bouncer_said = True
        self.add(self.server_buffer, INFO, "*", f"\x02Connected through {self.bouncer_text()}\x02 (a bouncer). It keeps you "
                                                f"online on {self.net.name} when BChat is closed.")
        if not self.history_on():
            self.add(self.server_buffer, INFO, "*", f"\x0314History comes from {self.bouncer}'s own playback, so BChat won't "
                                                    "also ask the server: nothing shows twice.")
        self.state_changed.emit()

    def _end_znc_playback(self) -> None:
        if self._znc_collect is None:
            return
        target, msgs, _t = self._znc_collect
        self._znc_collect = None
        self._show_playback(target, msgs)

    def _played_before(self, m: Message, seen: set) -> bool:
        """0.8.5: a played-back line already in the tab: its server time and text match a line there."""
        if "time" not in m.tags:
            return False
        ts, text = round(self._ts(m), 3), m.param(-1)
        if text.startswith("\x01ACTION"):
            text = f"{m.nick} {text.strip(chr(1)).partition(' ')[2]}"
        return (ts, text) in seen

    def _show_playback(self, target: str, msgs: list) -> None:
        """The bouncer's saved lines under one grey header, then 'Now live'. Times are the ones the lines carry."""
        if not msgs:
            return
        first = msgs[0]
        if self.is_channel(target):
            b = self.buffer(target)
        else:
            other = first.param(0) if self.fold(first.nick) == self.fold(self.nick) else first.nick
            b = self.buffer(other or target)
        # 0.8.5: a bouncer that keeps its buffer (ZNC AutoClearChanBuffer off) plays the same lines on every
        # connect: the ones this tab already shows (same server time, same text) aren't shown twice
        seen = {(round(ln.ts, 3), ln.text) for ln in b.lines}
        msgs = [m for m in msgs if not self._played_before(m, seen)]
        if not msgs:
            return
        first = msgs[0]
        n = len(msgs)
        who = self.bouncer or "the bouncer"
        self.add(b, INFO, "", f"\x0314──── Played back by {who}: {n} line{'' if n == 1 else 's'} from while BChat was closed ────",
                 self._ts(first))
        was, self._replaying = self._replaying, True
        try:
            for m in msgs:
                m.tags.pop("batch", None)
                self._handle(m)
        finally:
            self._replaying = was
        self.add(b, INFO, "", "\x0314──── Now live ────", self._ts(msgs[-1]))

    def online_text(self) -> str:
        """'3 h 12 min (since 17:50)' for /online and the network tooltip; '' when not connected."""
        if not self.online_since:
            return ""
        return f"{duration(time.time() - self.online_since)} (since {time.strftime('%H:%M', time.localtime(self.online_since))})"

    # --- services (ChanServ Access) ----------------------------------------------------------

    def ask_services(self, done) -> None:
        """Which services run here: ChanServ's answer to a quiet CTCP VERSION (Anope or Atheme). Calls done() once known."""
        if self.services:
            done()
            return
        self._services_wait.append(done)
        if len(self._services_wait) == 1:
            self.send_raw("PRIVMSG ChanServ :\x01VERSION\x01", quiet=True)
            QTimer.singleShot(4000, lambda: self._services_known(""))

    def _services_known(self, kind: str) -> None:
        if not self._services_wait:
            return
        self.services = kind or "anope"         # no answer: Anope, what most UnrealIRCd networks run
        self.services_guessed = not kind
        waiting, self._services_wait = self._services_wait, []
        for done in waiting:
            done()

    def own_rank(self, b: Buffer) -> str:
        """The prefix char for our own nick in this channel, for the light next to the nick box."""
        u = b.users.get(self.fold(self.nick))
        if u is None:
            return ""
        return next((c for c in self.prefix_order if c in u.prefixes), "")

    def rebuild_nicklist(self, chan: str) -> None:
        """0.8.10 /updatenl: NAMES again; its reply replaces the list (see _names), and 366 prints the count."""
        self.__dict__.setdefault("_rebuild_wait", set()).add(self.fold(chan))
        self.send("NAMES", chan)

    def _rebuilt(self, chan: str) -> None:
        wait = self.__dict__.get("_rebuild_wait")
        if not wait or self.fold(chan) not in wait:
            return
        wait.discard(self.fold(chan))
        b = self.buffers.get(self.fold(chan))
        if b is None:
            return
        users = list(b.users.values())
        ops = sum("@" in u.prefixes for u in users)
        voiced = sum("+" in u.prefixes for u in users)
        self.add(b, INFO, "*", f"Nick list for {b.name} rebuilt: {len(users)} "
                               f"{'person' if len(users) == 1 else 'people'}, {ops} op{'' if ops == 1 else 's'}, {voiced} voiced.")

    def _names(self, m: Message) -> None:
        b = self.buffers.get(self.fold(m.param(2)))
        if b is None:  # /names #other, no tab for it
            self.add(self._front(), INFO, "*", f"Names on {m.param(2)}: {m.param(-1)}")
            return
        if self.fold(b.name) not in self._names_fresh:
            self._names_fresh.add(self.fold(b.name))
            # a fresh NAMES reply replaces the list, but keep what WHO already told us
            b.__dict__["_old"] = b.users
            b.users = {}
        old = b.__dict__.get("_old", {})
        for item in m.param(-1).split():
            i = 0
            while i < len(item) and item[i] in self.prefix_chars:
                i += 1
            pfx, full = item[:i], item[i:]
            nick, _, host = full.partition("!")
            prev = old.get(self.fold(nick))
            b.users[self.fold(nick)] = User(nick, pfx, host or (prev.host if prev else ""),
                                         prev.away if prev else False, prev.realname if prev else "")
            if prev is not None:
                b.users[self.fold(nick)].oper = prev.oper
        self.users_changed.emit(b)

    def _who_reply(self, m: Message) -> None:
        # :srv 352 me #chan user host server nick flags :hops real
        b = self.buffers.get(self.fold(m.param(1)))
        if b is None:
            return
        u = b.users.get(self.fold(m.param(5)))
        if u is None:
            return
        away = m.param(6).startswith("G") and self.cfg.away_track
        real = m.param(-1).partition(" ")[2]
        host = f"{m.param(2)}@{m.param(3)}"
        changed = u.away != away
        u.away, u.host, u.realname, u.server = away, host, real, m.param(4)
        u.oper = "*" in m.param(6)
        if changed:
            self.users_changed.emit(b)

    def _whox_reply(self, m: Message) -> None:
        # :srv 354 me 152 #chan user host server nick flags account :real
        if m.param(1) != "152":
            self.add(self.server_buffer, INFO, "*", " ".join(m.params[1:]))
            return
        b = self.buffers.get(self.fold(m.param(2)))
        u = b.users.get(self.fold(m.param(6))) if b else None
        if u is None:
            return
        away = m.param(7).startswith("G") and self.cfg.away_track
        changed = u.away != away
        u.away, u.host, u.server = away, f"{m.param(3)}@{m.param(4)}", m.param(5)
        u.oper = "*" in m.param(7)
        u.account = "" if m.param(8) == "0" else m.param(8)
        u.realname = m.param(-1)
        if changed:
            self.users_changed.emit(b)

    def _list_line(self, n: int, m: Message) -> None:
        """0.8.5: ban / except / invite list lines with no Ban List window open:
        '#chan ban: *!*@host set by Belon on 18 Nov 2026 21:05'."""
        chan = m.param(1)
        what = {367: "ban", 368: "ban", 348: "except", 349: "except", 346: "invite", 347: "invite"}[n]
        if n in (368, 349, 347):
            self.add(self.server_buffer, INFO, "*", f"End of {chan} {what} list.")
            return
        text = f"{chan} {what}: {m.param(2)}"
        if m.param(3):
            text += f" set by {m.param(3)}"
        if m.param(4).isdigit():
            text += " on " + time.strftime("%d %b %Y %H:%M", time.localtime(int(m.param(4))))
        self.add(self.server_buffer, INFO, "*", text)

    def _nick_taken(self, nick: str = "") -> None:
        if self._welcomed:
            self.add(self._front(), ERROR, "*", f"Nick {nick} is already in use." if nick and nick != "*"
                     else "That nick is already in use.")
            return
        self.nick_attempt += 1
        options = [self._identity("nick2"), self.cfg.nick3]
        pick = options[self.nick_attempt - 1] if self.nick_attempt <= len(options) else ""
        if pick and self.fold(pick) == self.fold(self.nick):
            pick = ""                                # the same nick again would only be refused again
        if not pick:
            # 0.8.5: then Belon_, Belon__, ... A server that cuts long nicks short names the cut one in its 433:
            # the underscores then replace the last letters, so no try is ever the same refused nick again
            base = self._next_nick or self._identity("nick") or self.nick
            extra = max(1, self.nick_attempt - len([o for o in options if o]))
            if nick and nick != "*" and len(nick) < len(self.nick) and self.fold(self.nick).startswith(self.fold(nick)):
                self._nick_cut = len(nick)
            cut = self._nick_cut
            pick = base + "_" * extra
            if cut and len(pick) > cut:
                pick = base[:cut - extra] + "_" * extra if cut - extra >= 1 else random_nick()
        self.nick = pick
        self.add(self.server_buffer, INFO, "*", f"Nick in use, trying {pick}")
        self.send("NICK", pick)

    @staticmethod
    def _country_text(m: Message) -> str:
        """RPL_WHOISCOUNTRY: :srv 344 me nick MY :is connecting from Malaysia"""
        return m.param(-1).rpartition(" from ")[2] or m.param(2)

    def _whois_line(self, n: int, m: Message) -> None:
        key = self.fold(m.param(1))
        # 0.8.5: a background whois stays silent (and finishes) even while a /whois for someone else is showing;
        # one for the same nick as the /whois: the first answer is shown, the second fills the panel quietly
        if key in self._silent_whois and key != self._whois_nick and n not in (314, 369):
            info = self._silent_whois[key]
            if n == 311:
                info.update(user=f"{m.param(2)}@{m.param(3)}", real=m.param(-1))
            elif n == 312:
                info["server"] = m.param(2)
            elif n == 301:
                info["away"] = m.param(-1)
            elif n == 344:
                info["country"] = self._country_text(m)
            elif n == 318:
                self.whois_cache[key] = self._silent_whois.pop(key)
                for b in self.buffers.values():
                    u = b.users.get(key)
                    if u:
                        i = self.whois_cache[key]
                        u.realname = i.get("real", u.realname)
                        u.host = i.get("user", u.host)
                        u.server = i.get("server", u.server)
                        u.away_reason = i.get("away", u.away_reason)
                        u.country = i.get("country", u.country)
                self.user_info.emit(m.param(1))
            return
        if n == 301 and key != self._whois_nick:
            # the server tells you they're away because you messaged them, not a whois. "Show away once" drops repeats
            if self.cfg.away_once and self._away_seen.get(key) == m.param(-1):
                return
            self._away_seen[key] = m.param(-1)
            where, prefix = self._show_where("away", m.param(1))     # 0.8.7: Settings > Windows
            self.te("Away Line", where, INFO, (m.param(1), m.param(-1)), prefix=prefix)
            return
        # 0.8.7 Settings > Windows: "Active window" is still the tab the /whois was typed in
        b, prefix = self._show_where("whois", m.param(1), default=self._whois_target)
        p = m.params
        nick = m.param(1)
        tag = f"\x0312[\x0f{nick}\x0312]\x0f"
        if n == 311:
            text = f"{tag} ({m.param(2)}@{m.param(3)}): {m.param(-1)}"
        elif n == 319:
            text = f"{tag} {m.param(-1)}"
        elif n == 312:
            text = f"{tag} {m.param(2)} :{m.param(-1)}"
        elif n == 317 and m.param(2).isdigit():     # 0.8.5: a server sending words here no longer breaks the line
            secs = int(m.param(2))
            idle = f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
            text = f"{tag} idle \x0310{idle}\x0f"
            if len(p) > 4 and p[3].isdigit():
                text += ", signon: \x0310" + time.strftime("%a %b %d %H:%M:%S", time.localtime(int(p[3]))) + "\x0f"
        elif n == 318:
            text = f"{tag} End of WHOIS list."
            if key == self._whois_nick or not self._whois_nick:     # another nick's end doesn't end this /whois
                self._whois_target = None
                self._whois_nick = ""
        elif n in (314, 369):
            b, prefix = self._front(), ""           # 0.8.5: /whowas stays in the tab it was typed in
            text = f"{tag} was ({m.param(2)}@{m.param(3)}): {m.param(-1)}" if n == 314 else f"{tag} End of WHOWAS list."
        elif n == 301:
            text = f"{tag} is away ({m.param(-1)})"
        elif n == 330:
            text = f"{tag} {m.param(-1)} {m.param(2)}"
        elif n == 569:
            text = f"{tag} {m.param(-1)}"        # the AS number is already in the words; don't print it twice
        elif n == 344:
            text = f"{tag} {m.param(-1)}"
            country = self._country_text(m)
            for ch in self.buffers.values():
                u = ch.users.get(self.fold(m.param(1)))
                if u:
                    u.country = country
        else:
            text = f"{tag} {' '.join(p[2:])}"
        self.add_to(b, WHOIS, "i", text, prefix)
