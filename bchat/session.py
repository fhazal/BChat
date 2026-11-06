"""One IRC network connection and its buffers. Qt networking, but no widgets, so tests can drive it."""
from __future__ import annotations

import time
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QSslSocket

from .config import Config, NetworkConfig, Server
from .protocol import Message, build_line, lower, mask_ban, parse_line

# kinds a line can have; the chat view maps them to colours
MSG, SELF, ACTION, JOIN, PART, TOPIC, INFO, WHOIS, NOW_TALKING, HILITE, NOTICE, ERROR = (
    "msg", "self", "action", "join", "part", "topic", "info", "whois", "now", "hilite", "notice", "error")

SERVER, CHANNEL, QUERY = "server", "channel", "query"


@dataclass
class Line:
    kind: str
    left: str
    text: str
    ts: float = field(default_factory=time.time)


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


class Buffer:
    def __init__(self, session: "Session", name: str, kind: str):
        self.session = session
        self.name = name
        self.kind = kind
        self.lines: list[Line] = []
        self.users: dict[str, User] = {}
        self.topic = ""
        self.modes = ""
        self.joined = kind != CHANNEL
        self.activity = 0  # 0 none, 1 data, 2 message, 3 highlight
        self.marker: int | None = None

    def rank(self, u: User) -> int:
        order = self.session.prefix_order
        return min((order.index(p) for p in u.prefixes if p in order), default=len(order))

    def sorted_users(self) -> list[User]:
        return sorted(self.users.values(), key=lambda u: (self.rank(u), lower(u.nick)))

    def counts(self) -> tuple[int, int]:
        order = self.session.prefix_order
        # "ops" means @ or higher, same as XChat's count box
        at = order.index("@") if "@" in order else 0
        ops = sum(1 for u in self.users.values() if self.rank(u) <= at)
        return ops, len(self.users)


class Session(QObject):
    buffer_added = Signal(object)
    buffer_removed = Signal(object)
    buffer_changed = Signal(object)  # topic, modes or name
    users_changed = Signal(object)
    line_added = Signal(object, object)
    state_changed = Signal()
    raw_line = Signal(str, bool)  # text, outgoing
    user_info = Signal(str)  # nick whose silent whois just finished

    MAX_LINES = 5000
    LAG_WARN_MS = 5000
    WANTED_CAPS = {"multi-prefix", "away-notify", "userhost-in-names", "server-time", "znc.in/server-time-iso",
                   "znc.in/self-message", "chghost", "cap-notify", "account-notify", "account-tag", "extended-join",
                   "invite-notify", "message-tags", "setname", "batch"}

    def __init__(self, net: NetworkConfig, cfg: Config, parent=None):
        super().__init__(parent)
        self.net = net
        self.cfg = cfg
        self.server_buffer = Buffer(self, net.name, SERVER)
        self.buffers: dict[str, Buffer] = {}
        self.nick = self._identity("nick") or "BChatUser"
        self.state = "disconnected"
        self.server_name = ""
        self.prefix_modes = "ohv"
        self.prefix_chars = "@%+"
        self.chantypes = "#&"
        self.isupport_chanmodes_param = "beIkfjl"
        self.away = False
        self.server_index = -1
        self.want_connected = False
        self.nick_attempt = 0
        self._welcomed = False
        self._cap_active: set[str] = set()
        self._cap_ending = False
        self._whois_target: Buffer | None = None
        self._whois_nick = ""
        self._silent_whois: dict[str, dict] = {}
        self.whois_cache: dict[str, dict] = {}
        self._names_fresh: set[str] = set()
        self._buf = b""
        self.lag_ms: int | None = None
        self._ping_sent = 0.0
        self._last_rx = 0.0
        self.current: Buffer | None = None
        self.focus_next = ""
        self.statusmsg = ""
        self.whox = False
        self._sasl_state = ""
        self._cap_more: set[str] = set()
        self._cap_offered: dict[str, str] = {}
        self._cap_pending = 0
        self._sts_enforced = False
        self._ctcp_times: list[float] = []
        self._queue: list[str] = []
        self._next_send = 0.0
        self._queue_timer = QTimer(self, interval=500)
        self._queue_timer.timeout.connect(self._drain_queue)

        self.sock = QSslSocket(self)
        self.sock.connected.connect(self._on_tcp)
        self.sock.encrypted.connect(self._on_tls)
        self.sock.readyRead.connect(self._on_read)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.errorOccurred.connect(self._on_socket_error)
        self.sock.sslErrors.connect(self._on_ssl_errors)

        self._reconnect = QTimer(self, singleShot=True)
        self._reconnect.timeout.connect(self._connect_next)
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
        key = lower(name)
        b = self.buffers.get(key)
        if b is None and create:
            b = Buffer(self, name, CHANNEL if self.is_channel(name) else QUERY)
            self.buffers[key] = b
            self.buffer_added.emit(b)
        return b

    def close_buffer(self, b: Buffer) -> None:
        if b.kind == CHANNEL and b.joined and self.state == "connected":
            self.send("PART", b.name, self.cfg.part_reason)
        self.buffers.pop(lower(b.name), None)
        self.buffer_removed.emit(b)

    def all_buffers(self) -> list[Buffer]:
        return [self.server_buffer, *self.buffers.values()]

    def add(self, b: Buffer, kind: str, left: str, text: str, ts: float | None = None) -> None:
        line = Line(kind, left, text, ts if ts is not None else time.time())
        b.lines.append(line)
        if len(b.lines) > self.MAX_LINES:
            del b.lines[: len(b.lines) - self.MAX_LINES]
        self.line_added.emit(b, line)

    def _front(self) -> Buffer:
        return self.current if self.current is not None and self.current.session is self else self.server_buffer

    def clear_buffer(self, b: Buffer) -> None:
        b.lines.clear()
        b.marker = None
        self.buffer_changed.emit(b)

    # --- connecting -----------------------------------------------------------

    def connect_to_network(self) -> None:
        self.want_connected = True
        self.server_index = -1
        self._connect_next()

    def _connect_next(self) -> None:
        if not self.net.servers:
            self.want_connected = False
            self.add(self.server_buffer, ERROR, "*", "This tab has no server yet. Type /server <host> [port or +port for SSL].")
            return
        self.server_index = (self.server_index + 1) % len(self.net.servers) if self.net.cycle else 0
        s = self.net.servers[self.server_index]
        self._set_state("connecting")
        self._buf = b""
        self._welcomed = False
        self._cap_active = set()
        self.nick_attempt = 0
        self.nick = self._identity("nick") or "BChatUser"
        self._queue.clear()
        self._next_send = 0.0
        self.lag_ms = None
        self._ping_sent = 0.0
        self._sasl_state = ""
        self._cap_more = set()
        self._cap_offered = {}
        self._cap_pending = 0
        self.server_name = ""
        host, port, tls = s.host, s.port, s.ssl
        policy = self.cfg.sts.get(host.lower())
        self._sts_enforced = bool(policy and policy.get("expires", 0) > time.time())
        if self._sts_enforced and not tls:
            port, tls = int(policy["port"]), True
            self.add(self.server_buffer, INFO, "*", f"{host} requires secure connections (STS), using SSL port {port}")
        self._tls_now = tls
        self.add(self.server_buffer, INFO, "*", f"Connecting to {host} ({'SSL ' if tls else ''}port {port})...")
        if tls:
            self.sock.connectToHostEncrypted(host, port)
        else:
            self.sock.connectToHost(host, port)

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
            self.buffers.pop(lower(b.name), None)
            self.buffer_removed.emit(b)
        self.net = NetworkConfig(host, [Server(host, port, ssl)], password=password, cycle=False)
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
        if was_live:
            self.sock.abort()
        self.server_index = max(-1, self.server_index - 1)
        self._connect_next()

    def current_lag_ms(self) -> int | None:
        """The last measured lag, or how long the current ping has waited if that is already longer."""
        waiting = int((time.time() - self._ping_sent) * 1000) if self._ping_sent else 0
        if self.lag_ms is None and not waiting:
            return None
        return max(self.lag_ms or 0, waiting)

    def _set_state(self, st: str) -> None:
        self.state = st
        self.state_changed.emit()

    def _on_tcp(self) -> None:
        self.add(self.server_buffer, INFO, "*", "Connected. Now logging in..." if not self._tls_now else "Connected. Starting SSL...")
        if not self._tls_now:
            self._login()

    def _on_tls(self) -> None:
        c = self.sock.sessionCipher()
        self.add(self.server_buffer, INFO, "*", f"SSL connection established ({c.protocolString()}, {c.name()}). Now logging in...")
        self._login()

    def _on_ssl_errors(self, errors) -> None:
        names = ", ".join(e.errorString() for e in errors)
        if self.net.allow_invalid_cert and not self._sts_enforced:
            self.add(self.server_buffer, INFO, "*", f"Accepting server certificate anyway: {names}")
            self.sock.ignoreSslErrors()
        else:
            self.add(self.server_buffer, ERROR, "*",
                     f"Server certificate rejected: {names}. Turn on \"Accept invalid certificate\" in the Network List to connect.")

    def _login(self) -> None:
        self._set_state("registering")
        self._last_rx = time.time()
        self._keepalive.start()
        self.send_raw("CAP LS 302")
        if self.net.password:
            self.send_raw(f"PASS {self.net.password}", secret=True)
        self.send("NICK", self.nick)
        self.send("USER", self._identity("user"), "0", "*", self._identity("real"))

    def _on_read(self) -> None:
        self._buf += bytes(self.sock.readAll())
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            text = text.rstrip("\r")
            if text:
                self._last_rx = time.time()
                self.raw_line.emit(text, False)
                self._handle(parse_line(text))

    def _on_socket_error(self, err) -> None:
        if err == QAbstractSocket.SocketError.RemoteHostClosedError:
            return
        self.add(self.server_buffer, ERROR, "*", f"Connection failed: {self.sock.errorString()}")
        if self.sock.state() == QAbstractSocket.SocketState.UnconnectedState:
            self._on_disconnected()

    def _on_disconnected(self) -> None:
        if self.state == "disconnected":
            return
        self._keepalive.stop()
        self._who.stop()
        self._set_state("disconnected")
        for b in self.all_buffers():
            self.add(b, INFO, "*", "Disconnected.")
            if b.kind == CHANNEL:
                b.joined = False
                b.users.clear()
                self.users_changed.emit(b)
        if self.want_connected:
            self.add(self.server_buffer, INFO, "*", "Reconnecting in 10 seconds...")
            self._reconnect.start(10000)

    def _tick(self) -> None:
        if self.state in ("connected", "registering"):
            if time.time() - self._last_rx > 240:
                self.add(self.server_buffer, ERROR, "*", "Server stopped responding.")
                self.sock.abort()
                return
            if not self._ping_sent:  # keep timing the oldest unanswered ping, so a stalled server keeps counting up
                self._ping_sent = time.time()
            self.send_raw("PING :LAG%d" % int(time.time() * 1000), quiet=True)

    def _poll_who(self) -> None:
        # same idea as XChat's away polling; skipped when the server pushes away changes
        if "away-notify" in self._cap_active:
            return
        for b in self.buffers.values():
            if b.kind == CHANNEL and b.joined and len(b.users) <= 300:
                self.fetch_who(b.name)

    # --- sending ------------------------------------------------------------

    def send_raw(self, line: str, secret: bool = False, quiet: bool = False) -> None:
        if self.sock.state() != QAbstractSocket.SocketState.ConnectedState:
            return
        # a line break inside user text would otherwise become a second IRC command
        line = line.replace("\r", " ").replace("\n", " ").replace("\0", "")
        self.sock.write(line.encode("utf-8", "replace") + b"\r\n")
        if not quiet:
            self.raw_line.emit("PASS ****" if secret else line, True)

    def send(self, command: str, *params: str) -> None:
        line = build_line(command, *params)
        if self.state != "connected":
            self.send_raw(line)
            return
        self._queue.append(line)
        self._drain_queue()

    @staticmethod
    def _is_background(line: str) -> bool:
        """WHO polling and channel mode queries: the user never asked for these directly."""
        word = line.split(" ")
        return word[0] == "WHO" or (word[0] == "MODE" and len(word) == 2)

    def _drain_queue(self) -> None:
        """XChat's tcp_send_queue pacing, improved: background lines leave room, so user commands never wait behind them."""
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
            self._next_send += 2 + len(rest) / 120
            self.send_raw(line)
        self._queue_timer.stop()

    def say(self, target: str, text: str) -> None:
        if self.state != "connected":
            self.add(self._front(), ERROR, "*", "Not connected. Use Server > Reconnect.")
            return
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
                self.add(self.buffer(target), SELF, f"[{self.nick}]", piece)

    def action(self, target: str, text: str) -> None:
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

    def whois(self, nick: str) -> None:
        # asking twice with the same nick gets the idle time from the user's own server
        self._whois_target = self._front()
        self._whois_nick = lower(nick)
        self.send("WHOIS", nick, nick)

    def silent_whois(self, nick: str) -> None:
        """Fills the nick menu's info panel without printing anything, like XChat does."""
        key = lower(nick)
        if self.state == "connected" and key not in self._silent_whois:
            self._silent_whois[key] = {}
            self.send("WHOIS", nick)

    def set_mode_for(self, b: Buffer, sign_mode: str, nicks: list[str]) -> None:
        self.send("MODE", b.name, sign_mode + sign_mode[1] * (len(nicks) - 1), *nicks)

    def ban(self, b: Buffer, nick: str, kind: int, kick: bool = False) -> None:
        u = b.users.get(lower(nick))
        self.send("MODE", b.name, "+b", mask_ban(nick, u.host if u else "", kind))
        if kick:
            self.send("KICK", b.name, nick, self.cfg.part_reason)

    def set_away(self, away: bool) -> None:
        if away:
            self.send("AWAY", self.cfg.away_reason)
        else:
            self.send("AWAY")

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
            wanted = offered & self.WANTED_CAPS
            if "sasl" in offered and self.net.sasl_user and "PLAIN" in (self._cap_offered["sasl"].upper() or "PLAIN"):
                if self._tls_now:
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
                self.server_index -= 1
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

    def _irc_authenticate(self, m: Message) -> None:
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
        self._sasl_state = ""
        self.add(self.server_buffer, INFO if ok else ERROR, "*", text)
        if not self._welcomed:
            self.send_raw("CAP END")

    def _irc_batch(self, m: Message) -> None:
        pass  # lines inside a batch carry their own tags and show normally

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
            u = b.users.get(lower(m.nick))
            if u:
                u.account = acct

    def _irc_setname(self, m: Message) -> None:
        for b in self.buffers.values():
            u = b.users.get(lower(m.nick))
            if u:
                u.realname = m.param(0)

    def _irc_wallops(self, m: Message) -> None:
        self.add(self.server_buffer, NOTICE, f"-{m.nick}/Wallops-", m.param(-1), self._ts(m))

    def _irc_kill(self, m: Message) -> None:
        self.add(self.server_buffer, ERROR, "*", f"You have been killed by {m.nick} ({m.param(-1)})")

    def _irc_error(self, m: Message) -> None:
        if not self._welcomed and "password" in m.param(-1).lower():
            self._login_refused(m.param(-1))
            return
        self.add(self.server_buffer, ERROR, "*", m.param(-1))

    def _irc_privmsg(self, m: Message) -> None:
        target, text = m.param(0), m.param(-1)
        ts = self._ts(m)
        from_me = lower(m.nick) == lower(self.nick)
        target = target.lstrip(self.statusmsg) if self.statusmsg else target
        dest = target if self.is_channel(target) else (target if from_me else m.nick)
        if text.startswith("\x01") :
            body = text.strip("\x01")
            verb, _, rest = body.partition(" ")
            if verb.upper() == "ACTION":
                b = self.buffer(dest)
                self.add(b, ACTION if not self._is_hilite(rest) else HILITE, "*", f"{m.nick} {rest}", ts)
                self._bump(b, 3 if self._is_hilite(rest) else 2)
            else:
                self._ctcp_request(m.nick, verb.upper(), rest)
            return
        b = self.buffer(dest)
        u = b.users.get(lower(m.nick))
        if u:
            u.last_msg = ts
        if from_me:
            self.add(b, SELF, f"[{m.nick}]", text, ts)
            return
        hl = self._is_hilite(text) or b.kind == QUERY
        self.add(b, HILITE if hl else MSG, m.nick, text, ts)
        self._bump(b, 3 if hl else 2)

    def _ctcp_request(self, nick: str, verb: str, rest: str) -> None:
        now = time.time()
        self._ctcp_times = [t for t in self._ctcp_times if now - t < 30]
        self._ctcp_times.append(now)
        self.add(self._front(), INFO, "*", f"Received a CTCP {verb} from {nick}")
        if len(self._ctcp_times) > 5:  # XChat's limit: 5 in 30 s, then no replies
            if len(self._ctcp_times) == 6:
                self.add(self._front(), ERROR, "*", "CTCP flood: not replying for a while.")
            return
        if verb == "VERSION":
            self.send("NOTICE", nick, "\x01VERSION BChat 0.1 by BajuBesi Labs\x01")
        elif verb == "PING":
            self.send("NOTICE", nick, f"\x01PING {rest}\x01")
        elif verb == "TIME":
            self.send("NOTICE", nick, f"\x01TIME {time.ctime()}\x01")

    def _is_hilite(self, text: str) -> bool:
        words = [self.nick] + [w.strip() for w in self.cfg.highlight.split(",") if w.strip()]
        low = lower(text)
        for w in words:
            lw = lower(w)
            at = low.find(lw)
            while at != -1:
                before = low[at - 1] if at else " "
                end = at + len(lw)
                after = low[end] if end < len(low) else " "
                if not (before.isalnum() or before in "_-{}|^") and not (after.isalnum() or after in "_-{}|^"):
                    return True
                at = low.find(lw, at + 1)
        return False

    def _bump(self, b: Buffer, level: int) -> None:
        if b is not self.current and level > b.activity:
            b.activity = level
            self.buffer_changed.emit(b)

    def _irc_notice(self, m: Message) -> None:
        target, text = m.param(0), m.param(-1)
        if lower(m.nick) == "operserv" and "session limit" in text.lower():
            # services count kills, then auto-ban the whole IP (Anope maxsessionkill), so retrying can lock out every client on it
            self.want_connected = False
            self._reconnect.stop()
            self.add(self.server_buffer, ERROR, "*", f"-OperServ- {text} BChat will not retry: repeated attempts can get this IP banned.")
            return
        if text.startswith("\x01") and text.endswith("\x01"):
            verb, _, rest = text.strip("\x01").partition(" ")
            self.add(self._front(), INFO, "*", f"CTCP {verb} reply from {m.nick}: {rest}")
            return
        if not self._welcomed and "invalid password" in text.lower():
            self._login_refused(text)
            return
        if not m.nick or "." in m.nick or self.state != "connected":
            self.add(self.server_buffer, NOTICE, "-" + (m.nick or "server") + "-", text, self._ts(m))
            return
        b = self.buffers.get(lower(target)) if self.is_channel(target) else self._front()
        self.add(b or self._front(), NOTICE, f"-{m.nick}-", text, self._ts(m))

    def _irc_join(self, m: Message) -> None:
        chan = m.param(0)
        b = self.buffer(chan)
        if lower(m.nick) == lower(self.nick):
            b.joined = True
            b.users.clear()
            self._names_fresh.discard(lower(chan))
            self.add(b, NOW_TALKING, "➤", f"Now talking on {b.name}")
            self.send("MODE", b.name)
            self.fetch_who(b.name)
            self.buffer_changed.emit(b)
        else:
            self.add(b, JOIN, "-->", f"{m.nick} ({m.userhost}) has joined {b.name}", self._ts(m))
        joined = User(m.nick, "", m.userhost)
        if "extended-join" in self._cap_active and len(m.params) >= 3:
            joined.account = "" if m.param(1) == "*" else m.param(1)
            joined.realname = m.param(2)
        b.users[lower(m.nick)] = joined
        self.users_changed.emit(b)
        self._bump(b, 1)

    def _irc_part(self, m: Message) -> None:
        b = self.buffer(m.param(0), False)
        if b is None:
            return
        reason = m.param(1) if len(m.params) > 1 else ""
        if lower(m.nick) == lower(self.nick):
            b.joined = False
            b.users.clear()
            self.add(b, PART, "<--", f"You have left channel {b.name}")
            self.users_changed.emit(b)
            self.buffer_changed.emit(b)
            return
        b.users.pop(lower(m.nick), None)
        tail = f" ({reason})" if reason else ""
        self.add(b, PART, "<--", f"{m.nick} ({m.userhost}) has left {b.name}{tail}", self._ts(m))
        self.users_changed.emit(b)
        self._bump(b, 1)

    def _irc_quit(self, m: Message) -> None:
        key = lower(m.nick)
        for b in self.buffers.values():
            if key in b.users:
                del b.users[key]
                self.add(b, PART, "<--", f"{m.nick} has quit ({m.param(-1)})", self._ts(m))
                self.users_changed.emit(b)
                self._bump(b, 1)

    def _irc_kick(self, m: Message) -> None:
        b = self.buffer(m.param(0), False)
        if b is None:
            return
        victim, reason = m.param(1), m.param(2)
        b.users.pop(lower(victim), None)
        if lower(victim) == lower(self.nick):
            b.joined = False
            b.users.clear()
            self.add(b, PART, "<--", f"You have been kicked from {b.name} by {m.nick} ({reason})")
            self.buffer_changed.emit(b)
        else:
            self.add(b, PART, "<--", f"{m.nick} has kicked {victim} from {b.name} ({reason})")
        self.users_changed.emit(b)

    def _irc_nick(self, m: Message) -> None:
        old, new = m.nick, m.param(0)
        was_me = lower(old) == lower(self.nick)
        if was_me:
            self.nick = new
            self.state_changed.emit()
        for b in self.buffers.values():
            u = b.users.pop(lower(old), None)
            if u:
                u.nick = new
                b.users[lower(new)] = u
                text = f"You are now known as {new}" if was_me else f"{old} is now known as {new}"
                self.add(b, INFO, "*", text)
                self.users_changed.emit(b)
        q = self.buffers.pop(lower(old), None)
        if q is not None:
            q.name = new
            self.buffers[lower(new)] = q
            self.buffer_changed.emit(q)
        if was_me:
            self.add(self.server_buffer, INFO, "*", f"You are now known as {new}")

    def _irc_topic(self, m: Message) -> None:
        b = self.buffer(m.param(0))
        b.topic = m.param(1)
        self.add(b, TOPIC, "*", f"{m.nick} has changed the topic to: {b.topic}", self._ts(m))
        self.buffer_changed.emit(b)

    def _irc_mode(self, m: Message) -> None:
        target = m.param(0)
        if not self.is_channel(target):
            self.add(self.server_buffer, INFO, "*", f"Your modes: {' '.join(m.params[1:])}")
            return
        b = self.buffer(target)
        self._apply_modes(b, m.params[1:], m.nick)

    def _apply_modes(self, b: Buffer, params: list[str], who: str = "") -> None:
        if not params:
            return
        letters, args = params[0], list(params[1:])
        sign = "+"
        changed = False
        modes = set(b.modes)
        for c in letters:
            if c in "+-":
                sign = c
            elif c in self.prefix_modes:
                pfx = self.prefix_chars[self.prefix_modes.index(c)]
                nick = args.pop(0) if args else ""
                u = b.users.get(lower(nick))
                if u:
                    u.prefixes = (u.prefixes + pfx) if sign == "+" and pfx not in u.prefixes else u.prefixes.replace(pfx, "") if sign == "-" else u.prefixes
                    changed = True
                if who:
                    label = {"@": "channel operator status", "%": "channel half-operator status", "+": "voice"}.get(pfx, f"mode {c}")
                    self.add(b, INFO, "*", f"{who} {'gives' if sign == '+' else 'removes'} {label} {'to' if sign == '+' else 'from'} {nick}")
            else:
                has_arg = c in self.isupport_chanmodes_param and (sign == "+" or c not in "lj")
                arg = args.pop(0) if has_arg and args else ""
                if sign == "+":
                    modes.add(c)
                else:
                    modes.discard(c)
                if c in "beI":
                    modes.discard(c)
                if who:
                    if c == "b":
                        text = f"{who} {'sets ban on' if sign == '+' else 'removes ban on'} {arg}"
                    elif c == "k" and sign == "+":
                        text = f"{who} sets channel keyword to {arg}"
                    else:
                        text = f"{who} sets mode {sign}{c}{(' ' + arg) if arg else ''}"
                    self.add(b, INFO, "*", text)
        new = "".join(sorted(modes))
        if new != b.modes:
            b.modes = new
            self.buffer_changed.emit(b)
        if changed:
            self.users_changed.emit(b)

    def _irc_away(self, m: Message) -> None:
        away = bool(m.params and m.params[-1])
        key = lower(m.nick)
        for b in self.buffers.values():
            u = b.users.get(key)
            if u and u.away != away:
                u.away = away
                self.users_changed.emit(b)

    def _irc_chghost(self, m: Message) -> None:
        key = lower(m.nick)
        for b in self.buffers.values():
            u = b.users.get(key)
            if u:
                u.host = f"{m.param(0)}@{m.param(1)}"

    def _irc_invite(self, m: Message) -> None:
        if lower(m.param(0)) != lower(self.nick):  # invite-notify: someone else was invited
            b = self.buffer(m.param(1), False)
            if b is not None:
                self.add(b, INFO, "*", f"{m.nick} has invited {m.param(0)} to {m.param(1)}")
            return
        self.add(self._front(), INFO, "*", f"You have been invited to {m.param(1)} by {m.nick} ({m.userhost})")

    # numerics --------------------------------------------------------------------

    def _numeric(self, n: int, m: Message) -> None:
        p = m.params
        rest = " ".join(p[1:])
        if n == 1:
            self.nick = m.param(0)
            self.server_name = m.prefix
            self._welcomed = True
            self._set_state("connected")
            self._who.start()
            self.add(self.server_buffer, INFO, "*", m.param(-1))
            self._after_welcome()
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
                b.modes = "".join(sorted(m.param(2).lstrip("+")))
                self.buffer_changed.emit(b)
                self.add(b, INFO, "*", f"Channel {b.name} modes: {' '.join(p[2:])}")
        elif n == 329:
            pass
        elif n == 331:
            b = self.buffer(m.param(1))
            b.topic = ""
            self.buffer_changed.emit(b)
        elif n == 332:
            b = self.buffer(m.param(1))
            b.topic = m.param(-1)
            self.add(b, TOPIC, "*", f"Topic for {b.name} is: {b.topic}")
            self.buffer_changed.emit(b)
        elif n == 333:
            b = self.buffer(m.param(1))
            when = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(int(m.param(3) or 0)))
            self.add(b, TOPIC, "*", f"Topic for {b.name} set by {m.param(2).split('!')[0]} at {when}")
        elif n == 353:
            self._names(m)
        elif n == 366:
            self._names_fresh.discard(lower(m.param(1)))
        elif n == 352:
            self._who_reply(m)
        elif n == 354:
            self._whox_reply(m)
        elif n == 900:
            self.add(self.server_buffer, INFO, "*", m.param(-1))
        elif n == 903:
            self._sasl_done(True, "SASL login successful.")
        elif n in (902, 904, 905, 906, 907, 908):
            if n != 908:
                self._sasl_done(False, f"SASL login failed: {m.param(-1)}")
        elif n in (464, 465):
            self._login_refused(m.param(-1))
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
        elif n in (311, 312, 317, 318, 319, 301, 313, 320, 330, 335, 338, 344, 378, 379, 671, 276, 307, 275):
            self._whois_line(n, m)
        elif len(p) >= 3 and n < 400 and lower(m.param(1)) in (self._whois_nick, *self._silent_whois):
            # servers add their own whois lines; XChat calls these "WhoIs Special"
            self._whois_line(n, m)
        elif n == 433 or n == 436:
            self._nick_taken()
        elif n == 432:
            self.add(self.server_buffer, ERROR, "*", f"Nick not accepted: {m.param(1)}")
            if not self._welcomed:
                self._nick_taken()
        elif 400 <= n < 600:
            self.add(self._front(), ERROR, "*", " ".join(p[1:]))
        elif n in (372, 375, 376, 422, 2, 3, 4, 42, 250, 251, 252, 253, 254, 255, 265, 266, 396):
            self.add(self.server_buffer, INFO, "*", rest)
        else:
            self.add(self._front() if n in (221, 221) else self.server_buffer, INFO, "*", rest)

    def _isupport(self, tokens: list[str]) -> None:
        for t in tokens:
            k, _, v = t.partition("=")
            if k == "PREFIX" and v.startswith("("):
                modes, _, chars = v[1:].partition(")")
                if modes and len(modes) == len(chars):
                    self.prefix_modes, self.prefix_chars = modes, chars
            elif k == "CHANTYPES" and v:
                self.chantypes = v
            elif k == "STATUSMSG":
                self.statusmsg = v
            elif k == "WHOX":
                self.whox = True
            elif k == "CHANMODES" and v:
                groups = v.split(",")
                self.isupport_chanmodes_param = "".join(groups[:3]) if len(groups) >= 3 else self.isupport_chanmodes_param
            elif k == "NETWORK" and v:
                self.server_buffer.name = v if not self.net.name else self.net.name
                self.buffer_changed.emit(self.server_buffer)

    def _after_welcome(self) -> None:
        if self.net.nickserv:
            self.send_raw(f"PRIVMSG NickServ :IDENTIFY {self.net.nickserv}", secret=True)
        for cmd in self.net.commands:
            self.send_raw(cmd.lstrip("/"))
        rejoin = [b.name for b in self.buffers.values() if b.kind == CHANNEL]
        if self.net.autojoin:
            chans = self.net.autojoin.split(" ", 1)
            self.send("JOIN", *chans)
        for name in rejoin:
            if not self.net.autojoin or lower(name) not in lower(self.net.autojoin):
                self.send("JOIN", name)

    def own_rank(self, b: Buffer) -> str:
        """The prefix char for our own nick in this channel, for the light next to the nick box."""
        u = b.users.get(lower(self.nick))
        if u is None:
            return ""
        return next((c for c in self.prefix_order if c in u.prefixes), "")

    def _names(self, m: Message) -> None:
        b = self.buffer(m.param(2))
        if lower(b.name) not in self._names_fresh:
            self._names_fresh.add(lower(b.name))
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
            prev = old.get(lower(nick))
            b.users[lower(nick)] = User(nick, pfx, host or (prev.host if prev else ""),
                                         prev.away if prev else False, prev.realname if prev else "")
        self.users_changed.emit(b)

    def _who_reply(self, m: Message) -> None:
        # :srv 352 me #chan user host server nick flags :hops real
        b = self.buffers.get(lower(m.param(1)))
        if b is None:
            return
        u = b.users.get(lower(m.param(5)))
        if u is None:
            return
        away = m.param(6).startswith("G")
        real = m.param(-1).partition(" ")[2]
        host = f"{m.param(2)}@{m.param(3)}"
        changed = u.away != away
        u.away, u.host, u.realname, u.server = away, host, real, m.param(4)
        if changed:
            self.users_changed.emit(b)

    def _whox_reply(self, m: Message) -> None:
        # :srv 354 me 152 #chan user host server nick flags account :real
        if m.param(1) != "152":
            self.add(self.server_buffer, INFO, "*", " ".join(m.params[1:]))
            return
        b = self.buffers.get(lower(m.param(2)))
        u = b.users.get(lower(m.param(6))) if b else None
        if u is None:
            return
        away = m.param(7).startswith("G")
        changed = u.away != away
        u.away, u.host, u.server = away, f"{m.param(3)}@{m.param(4)}", m.param(5)
        u.account = "" if m.param(8) == "0" else m.param(8)
        u.realname = m.param(-1)
        if changed:
            self.users_changed.emit(b)

    def _nick_taken(self) -> None:
        if self._welcomed:
            self.add(self._front(), ERROR, "*", f"That nick is already in use.")
            return
        self.nick_attempt += 1
        options = [self._identity("nick2"), self.cfg.nick3]
        pick = options[self.nick_attempt - 1] if self.nick_attempt <= len(options) else ""
        if not pick:
            pick = f"{self._identity('nick')}_{self.nick_attempt}"
        self.nick = pick
        self.add(self.server_buffer, INFO, "*", f"Nick in use, trying {pick}")
        self.send("NICK", pick)

    @staticmethod
    def _country_text(m: Message) -> str:
        """RPL_WHOISCOUNTRY: :srv 344 me nick MY :is connecting from Malaysia"""
        return m.param(-1).rpartition(" from ")[2] or m.param(2)

    def _whois_line(self, n: int, m: Message) -> None:
        key = lower(m.param(1))
        if key in self._silent_whois and self._whois_target is None:
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
        b = self._whois_target or self._front()
        p = m.params
        nick = m.param(1)
        tag = f"\x0312[\x0f{nick}\x0312]\x0f"
        if n == 311:
            text = f"{tag} ({m.param(2)}@{m.param(3)}): {m.param(-1)}"
        elif n == 319:
            text = f"{tag} {m.param(-1)}"
        elif n == 312:
            text = f"{tag} {m.param(2)} :{m.param(-1)}"
        elif n == 317:
            secs = int(m.param(2) or 0)
            idle = f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
            text = f"{tag} idle \x0310{idle}\x0f"
            if len(p) > 4 and p[3].isdigit():
                text += ", signon: \x0310" + time.strftime("%a %b %d %H:%M:%S", time.localtime(int(p[3]))) + "\x0f"
        elif n == 318:
            text = f"{tag} End of WHOIS list."
            self._whois_target = None
            self._whois_nick = ""
        elif n == 301:
            text = f"{tag} is away ({m.param(-1)})"
        elif n == 330:
            text = f"{tag} {m.param(-1)} {m.param(2)}"
        elif n == 344:
            text = f"{tag} {m.param(-1)}"
            country = self._country_text(m)
            for ch in self.buffers.values():
                u = ch.users.get(lower(m.param(1)))
                if u:
                    u.country = country
        else:
            text = f"{tag} {' '.join(p[2:])}"
        self.add(b, WHOIS, "i", text)
