"""A deterministic local IRC server for tests (QA item A). Not a production IRC server and not a complete
implementation of IRC or IRCv3: it answers what BChat uses, the same way every time, and lets a test steer it.

    from qa_ircd import QaIrcd, IrcTestClient

    with QaIrcd(caps={"server-time", "message-tags"}) as srv:      # 127.0.0.1, a free port
        ...BChat or IrcTestClient connects to srv.port...
        srv.wait_for(r"^JOIN #chan", nick="alice")                   # event-based, no sleeps
        srv.inject("bob!b@qa.test", "#chan", "hello")                # a scripted user talks
        srv.give_op("#chan", "alice"); srv.drop("alice")             # scenario control

Parts, top to bottom: line format, certificates, state, server lifecycle + connections, protocol, scenario
control, synchronisation, test client. Standard library only, except `cryptography` (already a BChat dependency)
for the throwaway TLS certificate. Listens on localhost unless told otherwise. Every server is stopped at
interpreter exit, and stop() joins its threads, so nothing keeps running after the tests.
"""
from __future__ import annotations

import atexit
import base64
import datetime
import os
import re
import select
import socket
import ssl
import struct
import threading
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path

LOCAL4 = "127.0.0.1"
LOCAL6 = "::1"
FIXED_EPOCH = 1_700_000_000.0          # 2023-11-14T22:13:20Z: the deterministic clock starts here
DEFAULT_CAPS = frozenset({"multi-prefix", "away-notify", "userhost-in-names", "server-time", "chghost", "cap-notify",
                          "account-notify", "account-tag", "extended-join", "invite-notify", "message-tags", "setname",
                          "batch", "echo-message", "sasl"})
THREAD_PREFIX = "qa_ircd"
_LINGER_RESET = struct.pack("HH" if os.name == "nt" else "ii", 1, 0)   # close = TCP reset
_WOULD_BLOCK = (ssl.SSLWantReadError, ssl.SSLWantWriteError, BlockingIOError, InterruptedError)


# One TLS connection must never be read and written by two threads at once (OpenSSL doesn't allow it), so every
# socket here is non-blocking and every recv/send happens under that connection's own lock.
def locked_recv(sock, lock: threading.Lock, wait: float = 0.1) -> bytes | None:
    """Data, b"" for a closed connection, or None when nothing came within `wait` seconds."""
    pending = sock.pending() if isinstance(sock, ssl.SSLSocket) else 0
    if not pending and not select.select([sock], [], [], wait)[0]:
        return None
    with lock:
        try:
            return sock.recv(65536)
        except _WOULD_BLOCK:
            return None


def locked_sendall(sock, lock: threading.Lock, data: bytes, timeout: float = 10.0) -> None:
    """All of data, or TimeoutError after `timeout` seconds of a peer that doesn't read."""
    view, end = memoryview(data), time.time() + timeout
    while view:
        with lock:
            try:
                n = sock.send(view)
            except _WOULD_BLOCK:
                n = 0
        if n:
            view = view[n:]
            continue
        if time.time() > end:
            raise TimeoutError("send timed out: the other side stopped reading")
        select.select([], [sock], [], 0.05)


# ---- line format -----------------------------------------------------------------------------------------------

@dataclass
class Msg:
    tags: dict
    prefix: str
    command: str
    params: list

    def param(self, i: int, default: str = "") -> str:
        return self.params[i] if len(self.params) > i else default


_TAG_UNESCAPE = {"\\:": ";", "\\s": " ", "\\\\": "\\", "\\r": "\r", "\\n": "\n"}


def parse(line: str) -> Msg | None:
    """IRC line -> Msg (tags, prefix, command, params). None for a line that can't be read."""
    line = line.rstrip("\r\n")
    tags: dict = {}
    if line.startswith("@"):
        raw, _, line = line.partition(" ")
        for item in raw[1:].split(";"):
            if item:
                k, _, v = item.partition("=")
                tags[k] = re.sub(r"\\[:s\\rn]", lambda m: _TAG_UNESCAPE[m.group(0)], v)
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
    line = line.lstrip(" ")
    if not line:
        return None
    head, sep, trailing = line.partition(" :")
    params = head.split()
    if sep:
        params.append(trailing)
    if not params:
        return None
    return Msg(tags, prefix, params[0].upper(), params[1:])


def _escape_tag(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\:").replace(" ", "\\s").replace("\r", "\\r").replace("\n", "\\n")


TEXT_COMMANDS = frozenset({"PRIVMSG", "NOTICE", "KICK", "AWAY", "QUIT", "PART", "TOPIC", "ERROR"})


def build(command: str, *params: str, prefix: str = "", tags: dict | None = None) -> str:
    """Msg parts -> IRC line. The last parameter gets ':' when it needs one, and always for the text of
    PRIVMSG/NOTICE/KICK/AWAY/QUIT/PART/TOPIC/ERROR (as real servers send them)."""
    out = []
    if tags:
        out.append("@" + ";".join(k if v in (None, "") else f"{k}={_escape_tag(str(v))}" for k, v in tags.items()))
    if prefix:
        out.append(":" + prefix)
    out.append(command)
    ps = [str(p) for p in params]
    if ps:
        last = ps[-1]
        out += ps[:-1]
        force = command.upper() in TEXT_COMMANDS and (command.upper() not in ("PART", "KICK") or len(ps) > (1 if command.upper() == "PART" else 2))
        out.append(":" + last if (force or not last or " " in last or last.startswith(":")) else last)
    return " ".join(out)


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{int(round(ts % 1 * 1000)) % 1000:03d}Z"


def lower(s: str) -> str:
    """ascii casemapping (the server says CASEMAPPING=ascii)."""
    return s.lower()


# ---- certificates ----------------------------------------------------------------------------------------------

def make_cert(folder: Path, cn: str = "qa.irc.test") -> tuple[str, str]:
    """A throwaway self-signed certificate (valid 1 day) for localhost / 127.0.0.1 / ::1. Test use only."""
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = x509.SubjectAlternativeName([x509.DNSName(cn), x509.DNSName("localhost"),
                                       x509.IPAddress(ipaddress.ip_address(LOCAL4)), x509.IPAddress(ipaddress.ip_address(LOCAL6))])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1)).add_extension(san, critical=False)
            .sign(key, hashes.SHA256()))
    crt, k = folder / f"{cn}.crt.pem", folder / f"{cn}.key.pem"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(crt), str(k)


# ---- state -----------------------------------------------------------------------------------------------------

@dataclass
class Client:
    id: int
    sock: socket.socket
    addr: tuple
    nick: str = "*"
    user: str = ""
    realname: str = ""
    host: str = ""
    password: str = ""
    caps: set = field(default_factory=set)
    cap_open: bool = False
    cap_version: int = 0
    registered: bool = False
    account: str = ""
    away: str = ""
    modes: set = field(default_factory=set)
    channels: set = field(default_factory=set)
    sasl_mech: str = ""
    closed: bool = False
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def mask(self) -> str:
        return f"{self.nick}!{self.user or 'user'}@{self.host}"


@dataclass
class Ghost:
    """A scripted user who is in channels but has no connection (big nick lists, bursts)."""
    nick: str
    user: str = "ghost"
    host: str = "ghost.qa.test"
    account: str = ""
    realname: str = "QA ghost"

    @property
    def mask(self) -> str:
        return f"{self.nick}!{self.user}@{self.host}"


@dataclass
class Channel:
    name: str
    members: dict = field(default_factory=dict)       # lower(nick) -> prefix string ("@", "+", "@+", "")
    topic: str = ""
    modes: set = field(default_factory=lambda: {"n", "t"})
    bans: list = field(default_factory=list)


@dataclass
class Event:
    seq: int
    kind: str          # "in" (got from a client), "done" (that line was handled), "out" (sent), "connect", "close", "refused"
    client: int
    nick: str
    line: str


# ---- server lifecycle + connections ----------------------------------------------------------------------------

_LIVE: "weakref.WeakSet[QaIrcd]" = weakref.WeakSet()


@atexit.register
def stop_all() -> None:
    """Stop every server still running (also called by the test suite's cleanup)."""
    for srv in list(_LIVE):
        srv.stop()


class QaIrcd:
    def __init__(self, *, name: str = "irc.qa.test", network: str = "QANet", host: str = LOCAL4, port: int = 0,
                 tls: bool = False, certfile: str | None = None, keyfile: str | None = None, cert_dir: Path | None = None,
                 caps=DEFAULT_CAPS, cap_values: dict | None = None, isupport: dict | None = None,
                 accounts: dict | None = None, password: str = "", motd: tuple = ("Welcome to the QA test server.",),
                 clock=None, op_first_joiner: bool = True, start: bool = True):
        self.name, self.network, self.host = name, network, host
        self.tls = tls
        if tls and not certfile:
            import tempfile
            certfile, keyfile = make_cert(Path(cert_dir or tempfile.mkdtemp(prefix="qa_ircd_cert_")))
        self.certfile, self.keyfile = certfile, keyfile
        self.caps = set(caps)
        self.cap_values = {"sasl": "PLAIN,EXTERNAL", **(cap_values or {})}
        self.isupport = {"PREFIX": "(ov)@+", "CHANTYPES": "#", "CHANMODES": "beI,k,l,imnpst", "NETWORK": network,
                         "CASEMAPPING": "ascii", "NICKLEN": "30", "EXTBAN": "~,a", "WHOX": "", **(isupport or {})}
        self.accounts = dict(accounts or {})          # account -> password (test-only)
        self.password = password
        self.motd = list(motd)
        self._clock = clock
        self._tick = 0
        self.op_first_joiner = op_first_joiner
        # scenario knobs
        self.delay = 0.0               # seconds before each answer
        self.silent = False            # read everything, answer nothing
        self.refuse = ""               # "" | "reset" | "error": what happens to NEW connections
        self.answer_ping = True
        self.sasl_result = "ok"        # "ok" | "fail" | "abort" (for every attempt) | "accounts" (check self.accounts)
        self.external_account = ""     # SASL EXTERNAL logs in as this account ("" = 904)
        self.deny_op = False           # every MODE change from a client gets 482
        self.nak_caps: set = set()     # a CAP REQ naming any of these gets NAK (even though they are offered)
        # state
        self.clients: dict[int, Client] = {}
        self.ghosts: dict[str, Ghost] = {}
        self.channels: dict[str, Channel] = {}
        self.events: list[Event] = []
        self._cond = threading.Condition(threading.RLock())
        self._lock = self._cond            # one lock for all state + the event log
        self._ids = 0
        self._threads: list[threading.Thread] = []
        self._stopping = threading.Event()
        self._listener: socket.socket | None = None
        self.port = port
        if start:
            self.start()

    # -- lifecycle --
    def start(self) -> "QaIrcd":
        fam = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE if hasattr(socket, "SO_EXCLUSIVEADDRUSE") else socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(64)
        s.settimeout(0.1)
        self._listener = s
        self.port = s.getsockname()[1]
        self._ctx = None
        if self.tls:
            self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._ctx.load_cert_chain(self.certfile, self.keyfile)
        self._spawn(self._accept_loop, "accept")
        _LIVE.add(self)
        return self

    def stop(self, timeout: float = 5.0) -> None:
        """Close the listener and every connection, then wait for every thread of this server to end."""
        if self._stopping.is_set():
            return
        self._stopping.set()
        if self._listener:
            try:
                self._listener.close()
            except OSError:
                pass
        with self._lock:
            clients = list(self.clients.values())
        for c in clients:
            self._close(c, abrupt=True)
        end = time.time() + timeout
        for t in list(self._threads):
            if t is not threading.current_thread():
                t.join(max(0.0, end - time.time()))
        _LIVE.discard(self)

    @property
    def running(self) -> bool:
        return not self._stopping.is_set()

    def alive_threads(self) -> list[threading.Thread]:
        return [t for t in self._threads if t.is_alive()]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()

    def _spawn(self, fn, what, *args):
        t = threading.Thread(target=fn, args=args, name=f"{THREAD_PREFIX}-{self.port}-{what}", daemon=True)
        self._threads.append(t)
        t.start()

    def now(self) -> float:
        """Deterministic by default: FIXED_EPOCH + one second per timestamp handed out."""
        if self._clock:
            return self._clock()
        with self._lock:
            self._tick += 1
            return FIXED_EPOCH + self._tick

    def _accept_loop(self):
        while not self._stopping.is_set():
            try:
                sock, addr = self._listener.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            if self.refuse:
                self._log("refused", 0, "*", self.refuse)
                if self.refuse == "error":
                    try:
                        sock.sendall(b"ERROR :Closing Link: connection refused by the QA server\r\n")
                    except OSError:
                        pass
                    sock.close()
                else:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _LINGER_RESET)
                    sock.close()
                continue
            with self._lock:
                self._ids += 1
                c = Client(self._ids, sock, addr, host=f"host{self._ids}.qa.test")
                self.clients[c.id] = c
            self._spawn(self._serve, f"client{c.id}", c)

    def _serve(self, c: Client):
        if self._ctx:
            try:
                c.sock.settimeout(10)
                c.sock = self._ctx.wrap_socket(c.sock, server_side=True)
            except (ssl.SSLError, OSError) as e:
                self._log("close", c.id, c.nick, f"TLS handshake failed: {e}")
                self._forget(c)
                return
        self._log("connect", c.id, "*", f"{c.addr[0]}:{c.addr[1]}")
        # Reads wait in select() (so stop() is noticed within 0.1 s); a write waits up to 10 s for a slow reader
        # and then closes that client loudly, never drops a line quietly. See locked_recv / locked_sendall.
        c.sock.setblocking(False)
        buf = b""
        while not self._stopping.is_set() and not c.closed:
            try:
                data = locked_recv(c.sock, c.send_lock)
            except (OSError, ValueError):
                break
            if data is None:
                continue
            if not data:
                break
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.rstrip(b"\r").decode("utf-8", "replace")
                self._log("in", c.id, c.nick, line)
                if not self.silent:
                    try:
                        self._handle(c, line)
                    except Exception as e:      # a protocol bug in the simulator must not hang a test
                        self._log("close", c.id, c.nick, f"simulator error: {e!r}")
                self._log("done", c.id, c.nick, line)   # wait_handled(): the state already shows this line
        self._forget(c)

    def _forget(self, c: Client):
        if not c.closed:
            self._close(c, abrupt=False)
        with self._lock:
            if c.registered and c.channels and not self._stopping.is_set():
                self._quit_notice(c, "Connection closed")       # the others see it go, like on a real server
            self.clients.pop(c.id, None)
            for ch in list(self.channels.values()):
                if ch.members.pop(lower(c.nick), None) is not None and not ch.members:
                    self.channels.pop(lower(ch.name), None)

    def _close(self, c: Client, abrupt: bool):
        if c.closed:
            return
        c.closed = True
        if abrupt or self._stopping.is_set():
            try:
                c.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _LINGER_RESET)
                c.sock.close()
            except OSError:
                pass
            self._log("close", c.id, c.nick, "reset" if abrupt else "closed")
            return
        # Graceful, like a real server: stop sending (FIN) now, then read away what the client still sends and close.
        # Closing with unread incoming data makes Windows send a reset, which can make the client drop our last
        # lines (e.g. the ERROR) unread. The draining runs on its own thread: the caller may be the client's own
        # event loop (a Qt test), which must keep running meanwhile.
        try:
            c.sock.shutdown(socket.SHUT_WR)
        except (OSError, ValueError):
            pass
        self._log("close", c.id, c.nick, "closed")
        self._spawn(self._finish_close, f"close{c.id}", c)

    def _finish_close(self, c: Client):
        end = time.time() + 2.0
        try:
            while time.time() < end and not self._stopping.is_set():
                if not select.select([c.sock], [], [], 0.05)[0]:
                    continue
                try:
                    if not c.sock.recv(65536):
                        break                              # the client closed its side too
                except _WOULD_BLOCK:
                    continue
        except (OSError, ValueError):
            pass
        try:
            c.sock.close()
        except OSError:
            pass

    # -- sending --
    def _send(self, c: Client, line: str | bytes):
        if c.closed:
            return
        if self.delay:
            time.sleep(self.delay)
        data = line if isinstance(line, bytes) else (line + "\r\n").encode("utf-8")
        try:
            locked_sendall(c.sock, c.send_lock, data)
        except (OSError, ValueError) as e:
            self._log("close", c.id, c.nick, f"send failed ({e.__class__.__name__}): {data[:80]!r}")
            self._close(c, abrupt=True)
            return
        self._log("out", c.id, c.nick, data.decode("utf-8", "replace").rstrip("\r\n"))

    def _num(self, c: Client, num: str, *params: str):
        self._send(c, build(num, c.nick, *params, prefix=self.name))

    def deliver(self, c: Client, command: str, *params: str, prefix: str = "", account: str = "",
                client_tags: dict | None = None, ts: float | None = None):
        """One message to one client, with the tags its capabilities ask for."""
        tags = {}
        if "server-time" in c.caps:
            tags["time"] = iso(ts if ts is not None else self.now())
        if account and "account-tag" in c.caps:
            tags["account"] = account
        if client_tags and "message-tags" in c.caps:
            tags.update({k: v for k, v in client_tags.items() if k.startswith("+")})
        self._send(c, build(command, *params, prefix=prefix or self.name, tags=tags or None))

    # -- event log --
    def _log(self, kind: str, cid: int, nick: str, line: str):
        with self._cond:
            self.events.append(Event(len(self.events), kind, cid, nick, line))
            self._cond.notify_all()

    # ---- protocol --------------------------------------------------------------------------------------------

    def _find(self, nick: str) -> Client | None:
        n = lower(nick)
        for c in self.clients.values():
            if lower(c.nick) == n and not c.closed:
                return c
        return None

    def _in_use(self, nick: str) -> bool:
        return self._find(nick) is not None or lower(nick) in self.ghosts

    def _shared(self, c: Client) -> list[Client]:
        """Clients sharing a channel with c (not c)."""
        out = {}
        for ch in self.channels.values():
            if lower(c.nick) in ch.members:
                for m in ch.members:
                    o = self._find(m)
                    if o and o is not c:
                        out[o.id] = o
        return list(out.values())

    def _members(self, ch: Channel) -> list[Client]:
        return [o for o in (self._find(m) for m in ch.members) if o]

    def _handle(self, c: Client, line: str):
        m = parse(line)
        if m is None:
            return
        h = getattr(self, "_cmd_" + m.command.replace("-", "_"), None)
        if h is None:
            if c.registered:
                self._num(c, "421", m.command, "Unknown command")
            return
        if not c.registered and m.command not in ("CAP", "PASS", "NICK", "USER", "AUTHENTICATE", "PING", "PONG", "QUIT"):
            self._num(c, "451", "You have not registered")
            return
        with self._lock:
            h(c, m)

    # registration
    def _cmd_PASS(self, c, m):
        c.password = m.param(0)

    def _cmd_NICK(self, c, m):
        new = m.param(0)
        if not new:
            return self._num(c, "431", "No nickname given")
        if not re.fullmatch(r"[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}-]{0,29}", new):
            return self._num(c, "432", new, "Erroneous nickname")
        if self._in_use(new) and lower(new) != lower(c.nick):
            return self._num(c, "433", new, "Nickname is already in use")
        if c.registered:
            self.change_nick(c, new)
        else:
            c.nick = new
            self._try_register(c)

    def _cmd_USER(self, c, m):
        if c.registered:
            return self._num(c, "462", "You may not reregister")
        c.user, c.realname = m.param(0), m.param(3)
        self._try_register(c)

    def _try_register(self, c):
        if c.registered or c.cap_open or c.nick == "*" or not c.user:
            return
        if self.password and c.password != self.password:
            self._num(c, "464", "Password incorrect")
            self._send(c, "ERROR :Closing Link: bad password")
            self._close(c, abrupt=False)
            return
        c.registered = True
        self._num(c, "001", f"Welcome to the {self.network} IRC network {c.mask}")
        self._num(c, "002", f"Your host is {self.name}, running qa_ircd")
        self._num(c, "003", "This server was created for testing")
        self._num(c, "004", self.name, "qa_ircd", "iow", "beIklmnopstv")
        items = [k if v == "" else f"{k}={v}" for k, v in self.isupport.items()]
        for i in range(0, len(items), 12):
            self._num(c, "005", *items[i:i + 12], "are supported by this server")
        if self.motd:
            self._num(c, "375", f"- {self.name} Message of the day -")
            for ln in self.motd:
                self._num(c, "372", f"- {ln}")
            self._num(c, "376", "End of /MOTD command.")
        else:
            self._num(c, "422", "MOTD File is missing")

    # capabilities
    def _cap_text(self, cap: str, c: Client) -> str:
        v = self.cap_values.get(cap, "")
        return f"{cap}={v}" if v and c.cap_version >= 302 else cap

    def _cmd_CAP(self, c, m):
        sub = m.param(0).upper()
        if sub == "LS":
            c.cap_open = True
            try:
                c.cap_version = max(c.cap_version, int(m.param(1) or 0))
            except ValueError:
                pass
            items = [self._cap_text(x, c) for x in sorted(self.caps)]
            chunks, cur = [], []
            for it in items:                                 # several lines when long (302 multi-line LS)
                if cur and len(" ".join(cur + [it])) > 300 and c.cap_version >= 302:
                    chunks.append(cur)
                    cur = []
                cur.append(it)
            chunks.append(cur)
            for i, ch in enumerate(chunks):
                more = ["*"] if i < len(chunks) - 1 else []
                self._send(c, build("CAP", c.nick, "LS", *more, " ".join(ch), prefix=self.name))
        elif sub == "LIST":
            self._send(c, build("CAP", c.nick, "LIST", " ".join(sorted(c.caps)), prefix=self.name))
        elif sub == "REQ":
            want = m.param(1).split()
            names = [w.lstrip("-") for w in want]
            if all(n in self.caps for n in names) and not (set(names) & self.nak_caps):
                for w in want:
                    (c.caps.discard if w.startswith("-") else c.caps.add)(w.lstrip("-"))
                self._send(c, build("CAP", c.nick, "ACK", m.param(1), prefix=self.name))
            else:
                self._send(c, build("CAP", c.nick, "NAK", m.param(1), prefix=self.name))
        elif sub == "END":
            c.cap_open = False
            self._try_register(c)

    # SASL
    def _cmd_AUTHENTICATE(self, c, m):
        arg = m.param(0)
        if not c.sasl_mech:
            if "sasl" not in c.caps:
                return self._num(c, "904", "SASL authentication failed")
            if arg.upper() not in ("PLAIN", "EXTERNAL"):
                return self._num(c, "908", "PLAIN,EXTERNAL", "are available SASL mechanisms")
            c.sasl_mech = arg.upper()
            return self._send(c, "AUTHENTICATE +")
        mech, c.sasl_mech = c.sasl_mech, ""
        if arg == "*" or self.sasl_result == "abort":
            return self._num(c, "906", "SASL authentication aborted")
        account = ""
        if mech == "EXTERNAL":
            account = self.external_account
        else:
            try:
                parts = base64.b64decode(arg).split(b"\0")
                authcid, pw = parts[1].decode(), parts[2].decode()
            except (ValueError, IndexError):
                return self._num(c, "904", "SASL authentication failed")
            if self.sasl_result == "ok" and not self.accounts:
                account = authcid
            elif self.accounts.get(authcid) == pw and self.sasl_result in ("ok", "accounts"):
                account = authcid
        if not account or self.sasl_result == "fail":
            return self._num(c, "904", "SASL authentication failed")
        c.account = account
        self._num(c, "900", c.mask, account, f"You are now logged in as {account}")
        self._num(c, "903", "SASL authentication successful")

    # ping
    def _cmd_PING(self, c, m):
        if self.answer_ping:
            self._send(c, build("PONG", self.name, m.param(0), prefix=self.name))

    def _cmd_PONG(self, c, m):
        pass

    # channels
    def _names(self, c: Client, ch: Channel):
        multi, uh = "multi-prefix" in c.caps, "userhost-in-names" in c.caps
        out = []
        for n, pfx in ch.members.items():
            who = self._find(n) or self.ghosts.get(n)
            name = who.mask if (uh and who) else (who.nick if who else n)
            out.append((pfx if multi else pfx[:1]) + name)
        for i in range(0, max(len(out), 1), 40):
            self._num(c, "353", "=", ch.name, " ".join(out[i:i + 40]))
        self._num(c, "366", ch.name, "End of /NAMES list.")

    def _cmd_JOIN(self, c, m):
        if m.param(0) == "0":
            for name in list(c.channels):
                self._part(c, name, "Left all channels")
            return
        for name in m.param(0).split(","):
            if not name.startswith("#"):
                self._num(c, "403", name, "No such channel")
                continue
            ch = self.channels.get(lower(name))
            if ch is None:
                ch = self.channels[lower(name)] = Channel(name)
                pfx = "@" if self.op_first_joiner else ""
            else:
                if lower(c.nick) in ch.members:
                    continue
                if any(self._ban_matches(b, c) for b in ch.bans):
                    self._num(c, "474", ch.name, "Cannot join channel (+b)")
                    continue
                pfx = ""
            ch.members[lower(c.nick)] = pfx
            c.channels.add(lower(name))
            ts = self.now()
            for o in self._members(ch):
                if "extended-join" in o.caps:
                    self.deliver(o, "JOIN", ch.name, c.account or "*", c.realname, prefix=c.mask, account=c.account, ts=ts)
                else:
                    self.deliver(o, "JOIN", ch.name, prefix=c.mask, account=c.account, ts=ts)
            if ch.topic:
                self._num(c, "332", ch.name, ch.topic)
            self._names(c, ch)

    def _part(self, c: Client, name: str, reason: str = ""):
        ch = self.channels.get(lower(name))
        if ch is None or lower(c.nick) not in ch.members:
            return self._num(c, "442", name, "You're not on that channel")
        ts = self.now()
        for o in self._members(ch):
            self.deliver(o, "PART", ch.name, *([reason] if reason else []), prefix=c.mask, account=c.account, ts=ts)
        ch.members.pop(lower(c.nick), None)
        c.channels.discard(lower(name))
        if not ch.members:
            self.channels.pop(lower(name), None)

    def _cmd_PART(self, c, m):
        for name in m.param(0).split(","):
            self._part(c, name, m.param(1))

    def _cmd_NAMES(self, c, m):
        ch = self.channels.get(lower(m.param(0)))
        if ch:
            self._names(c, ch)
        else:
            self._num(c, "366", m.param(0) or "*", "End of /NAMES list.")

    def _cmd_TOPIC(self, c, m):
        ch = self.channels.get(lower(m.param(0)))
        if ch is None:
            return self._num(c, "403", m.param(0), "No such channel")
        if len(m.params) < 2:
            return self._num(c, "332", ch.name, ch.topic) if ch.topic else self._num(c, "331", ch.name, "No topic is set")
        if "t" in ch.modes and "@" not in ch.members.get(lower(c.nick), ""):
            return self._num(c, "482", ch.name, "You're not channel operator")
        ch.topic = m.param(1)
        ts = self.now()
        for o in self._members(ch):
            self.deliver(o, "TOPIC", ch.name, ch.topic, prefix=c.mask, ts=ts)

    # messages
    def _cmd_PRIVMSG(self, c, m, command="PRIVMSG"):
        target, text = m.param(0), m.param(1)
        if not text and command != "TAGMSG":
            return self._num(c, "412", "No text to send")
        ts = self.now()
        args = (target,) if command == "TAGMSG" else (target, text)
        if target.startswith("#"):
            ch = self.channels.get(lower(target))
            if ch is None:
                return self._num(c, "403", target, "No such channel")
            if "n" in ch.modes and lower(c.nick) not in ch.members:
                return self._num(c, "404", target, "Cannot send to channel")
            for o in self._members(ch):
                if o is not c or "echo-message" in c.caps:
                    self.deliver(o, command, *args, prefix=c.mask, account=c.account, client_tags=m.tags, ts=ts)
        else:
            o = self._find(target)
            if o is None:
                return self._num(c, "401", target, "No such nick/channel")
            self.deliver(o, command, *args, prefix=c.mask, account=c.account, client_tags=m.tags, ts=ts)
            if "echo-message" in c.caps and o is not c:
                self.deliver(c, command, *args, prefix=c.mask, account=c.account, client_tags=m.tags, ts=ts)
            if o.away and command == "PRIVMSG":
                self._num(c, "301", o.nick, o.away)

    def _cmd_NOTICE(self, c, m):
        self._cmd_PRIVMSG(c, m, "NOTICE")

    def _cmd_TAGMSG(self, c, m):
        self._cmd_PRIVMSG(c, m, "TAGMSG")

    def _cmd_AWAY(self, c, m):
        c.away = m.param(0)
        self._num(c, "306" if c.away else "305", "You have been marked as being away" if c.away else "You are no longer marked as being away")
        for o in self._shared(c):
            if "away-notify" in o.caps:
                self.deliver(o, "AWAY", *([c.away] if c.away else []), prefix=c.mask)

    # queries
    def _cmd_WHO(self, c, m):
        target = m.param(0)
        whox = m.param(1).partition("%")[2] if "%" in m.param(1) else None
        fields, _, token = (whox or "").partition(",")
        people = []
        ch = self.channels.get(lower(target))
        if ch:
            people = [(n, ch.members[n]) for n in ch.members]
        elif self._find(target) or lower(target) in self.ghosts:
            people = [(lower(target), "")]
        for n, pfx in people:
            who = self._find(n) or self.ghosts.get(n)
            if who is None:
                continue
            away = isinstance(who, Client) and who.away
            flags = ("G" if away else "H") + pfx
            account = getattr(who, "account", "") or "0"
            if whox is None:
                self._num(c, "352", ch.name if ch else "*", who.user or "user", who.host, self.name, who.nick, flags,
                          f"0 {who.realname}")
                continue
            vals = {"t": token or "0", "c": ch.name if ch else "*", "u": who.user or "user", "i": "255.255.255.255",
                    "h": who.host, "s": self.name, "n": who.nick, "f": flags, "d": "0", "l": "0", "a": account,
                    "o": "n/a", "r": who.realname}
            self._num(c, "354", *[vals[f] for f in "tcuihsnfdlaor" if f in fields])
        self._num(c, "315", target, "End of /WHO list.")

    def _cmd_WHOIS(self, c, m):
        nick = m.params[-1] if m.params else ""
        who = self._find(nick) or self.ghosts.get(lower(nick))
        if who is None:
            self._num(c, "401", nick, "No such nick/channel")
        else:
            self._num(c, "311", who.nick, who.user or "user", who.host, "*", who.realname)
            self._num(c, "312", who.nick, self.name, "QA test server")
            if getattr(who, "account", ""):
                self._num(c, "330", who.nick, who.account, "is logged in as")
        self._num(c, "318", nick, "End of /WHOIS list.")

    def _cmd_USERHOST(self, c, m):
        out = []
        for n in m.params[:5]:
            who = self._find(n)
            if who:
                out.append(f"{who.nick}={'-' if who.away else '+'}{who.user or 'user'}@{who.host}")
        self._num(c, "302", " ".join(out))

    def _cmd_ISON(self, c, m):
        names = " ".join(m.params).split()
        self._num(c, "303", " ".join(n for n in names if self._find(n) or lower(n) in self.ghosts))

    # modes
    def _ban_matches(self, mask: str, c: Client) -> bool:
        if mask.startswith("~a:") or mask.startswith("~account:"):
            return bool(c.account) and lower(mask.split(":", 1)[1]) == lower(c.account)
        rx = "^" + re.escape(lower(mask)).replace(r"\*", ".*").replace(r"\?", ".") + "$"
        return re.match(rx, lower(c.mask)) is not None

    def _cmd_MODE(self, c, m):
        target = m.param(0)
        if not target.startswith("#"):
            if lower(target) != lower(c.nick):
                return self._num(c, "502", "Can't change mode for other users")
            for sign, ch_ in re.findall(r"([+-])([a-zA-Z]+)", m.param(1)):
                for x in ch_:
                    (c.modes.add if sign == "+" else c.modes.discard)(x)
            if len(m.params) > 1:
                self._send(c, build("MODE", c.nick, m.param(1), prefix=c.mask))
            return self._num(c, "221", "+" + "".join(sorted(c.modes)))
        ch = self.channels.get(lower(target))
        if ch is None:
            return self._num(c, "403", target, "No such channel")
        if len(m.params) == 1:
            return self._num(c, "324", ch.name, "+" + "".join(sorted(ch.modes)))
        if m.param(1) in ("b", "+b") and len(m.params) == 2:
            for b in ch.bans:
                self._num(c, "367", ch.name, b, self.name, "0")
            return self._num(c, "368", ch.name, "End of channel ban list")
        if self.deny_op or "@" not in ch.members.get(lower(c.nick), ""):
            return self._num(c, "482", ch.name, "You're not channel operator")
        self.apply_mode(ch.name, m.param(1), *m.params[2:], by=c.mask)

    def _cmd_KICK(self, c, m):
        ch = self.channels.get(lower(m.param(0)))
        if ch is None:
            return self._num(c, "403", m.param(0), "No such channel")
        if self.deny_op or "@" not in ch.members.get(lower(c.nick), ""):
            return self._num(c, "482", ch.name, "You're not channel operator")
        self.kick(ch.name, m.param(1), m.param(2) or c.nick, by=c.mask)

    def _cmd_QUIT(self, c, m):
        reason = m.param(0) or "Client Quit"
        self._quit_notice(c, reason)
        self._send(c, build("ERROR", f"Closing Link: {c.host} ({reason})"))
        self._close(c, abrupt=False)

    def _quit_notice(self, c: Client, reason: str):
        ts = self.now()
        for o in self._shared(c):
            self.deliver(o, "QUIT", reason, prefix=c.mask, ts=ts)
        for name in list(c.channels):
            ch = self.channels.get(name)
            if ch:
                ch.members.pop(lower(c.nick), None)
                if not ch.members:
                    self.channels.pop(name, None)
        c.channels.clear()

    # ---- scenario control ------------------------------------------------------------------------------------

    def client(self, nick: str) -> Client:
        with self._lock:
            c = self._find(nick)
        if c is None:
            raise KeyError(f"no client called {nick!r} on {self.name}")
        return c

    def disconnect(self, nick: str, reason: str = "Closing Link: disconnected by the QA server"):
        """A clean server-side disconnect: ERROR line, then the socket is closed."""
        c = self.client(nick)
        with self._lock:
            self._quit_notice(c, reason)
        self._send(c, build("ERROR", reason))
        self._close(c, abrupt=False)

    def drop(self, nick: str):
        """The connection dies with no goodbye (TCP reset)."""
        c = self.client(nick)
        with self._lock:
            self._quit_notice(c, "Connection reset by peer")
        self._close(c, abrupt=True)

    def drop_all(self):
        for c in list(self.clients.values()):
            self._close(c, abrupt=True)

    def send_raw(self, nick: str, data: str | bytes):
        """Anything, as is: malformed lines, broken UTF-8, missing CRLF (a str gets CRLF added, bytes don't)."""
        self._send(self.client(nick), data)

    def numeric(self, nick: str, num: str, *params: str):
        """A server error or any numeric to one client, e.g. numeric('alice', '465', 'You are banned')."""
        self._num(self.client(nick), num, *params)

    def server_error(self, nick: str, text: str = "Closing Link: server error", close: bool = True):
        c = self.client(nick)
        self._send(c, build("ERROR", text))
        if close:
            self._close(c, abrupt=False)

    def change_nick(self, c_or_nick, new: str):
        """A nick change the client sees as its own (like a services forced change)."""
        c = c_or_nick if isinstance(c_or_nick, Client) else self.client(c_or_nick)
        with self._lock:
            old_mask, old = c.mask, c.nick
            ts = self.now()
            for o in [c] + self._shared(c):
                self.deliver(o, "NICK", new, prefix=old_mask, ts=ts)
            for name in c.channels:
                ch = self.channels[name]
                ch.members[lower(new)] = ch.members.pop(lower(old))
            c.nick = new

    def apply_mode(self, chan: str, modes: str, *args: str, by: str = ""):
        """Channel mode change from the server (or a user mask), sent to every member."""
        with self._lock:
            ch = self.channels[lower(chan)]
            argv = list(args)
            sign = "+"
            for x in modes:
                if x in "+-":
                    sign = x
                elif x in "ov":
                    nick = argv.pop(0) if argv else ""
                    sym = "@" if x == "o" else "+"
                    if lower(nick) in ch.members:
                        p = ch.members[lower(nick)].replace(sym, "")
                        ch.members[lower(nick)] = "".join(s for s in "@+" if s in (p + (sym if sign == "+" else "")))
                elif x == "b":
                    mask = argv.pop(0) if argv else ""
                    if sign == "+" and mask not in ch.bans:
                        ch.bans.append(mask)
                    elif sign == "-" and mask in ch.bans:
                        ch.bans.remove(mask)
                else:
                    (ch.modes.add if sign == "+" else ch.modes.discard)(x)
            ts = self.now()
            for o in self._members(ch):
                self.deliver(o, "MODE", ch.name, modes, *args, prefix=by or self.name, ts=ts)

    def give_op(self, chan: str, nick: str):
        self.apply_mode(chan, "+o", nick)

    def take_op(self, chan: str, nick: str):
        self.apply_mode(chan, "-o", nick)

    def kick(self, chan: str, nick: str, reason: str = "kicked", by: str = ""):
        with self._lock:
            ch = self.channels[lower(chan)]
            ts = self.now()
            for o in self._members(ch):
                self.deliver(o, "KICK", ch.name, nick, reason, prefix=by or self.name, ts=ts)
            ch.members.pop(lower(nick), None)
            c = self._find(nick)
            if c:
                c.channels.discard(lower(chan))

    def set_account(self, nick: str, account: str):
        """Log a client in/out (account-notify to everyone sharing a channel)."""
        c = self.client(nick)
        with self._lock:
            c.account = account
            for o in self._shared(c):
                if "account-notify" in o.caps:
                    self.deliver(o, "ACCOUNT", account or "*", prefix=c.mask)

    def set_host(self, nick: str, user: str, host: str):
        """chghost: the user/host of a client changes."""
        c = self.client(nick)
        with self._lock:
            old = c.mask
            c.user, c.host = user, host
            for o in [c] + self._shared(c):
                if "chghost" in o.caps:
                    self.deliver(o, "CHGHOST", user, host, prefix=old)

    def add_ghost(self, chan: str, nick: str, prefix: str = "", account: str = "", announce: bool = False) -> Ghost:
        """A scripted user in a channel without a connection (creates the channel if needed)."""
        with self._lock:
            g = self.ghosts.setdefault(lower(nick), Ghost(nick, account=account))
            ch = self.channels.setdefault(lower(chan), Channel(chan))
            ch.members[lower(nick)] = prefix
            if announce:
                ts = self.now()
                for o in self._members(ch):
                    self.deliver(o, "JOIN", ch.name, prefix=g.mask, account=g.account, ts=ts)
            return g

    def add_ghosts(self, chan: str, count: int, stem: str = "user", op_every: int = 0) -> list[str]:
        """count ghosts named stem0001.. in a channel (big nick lists). Deterministic names and prefixes."""
        nicks = []
        for i in range(1, count + 1):
            n = f"{stem}{i:04d}"
            self.add_ghost(chan, n, "@" if op_every and i % op_every == 0 else "")
            nicks.append(n)
        return nicks

    def ghost_part(self, chan: str, nick: str, reason: str = "leaving"):
        """A scripted user leaves a channel (PART to its clients)."""
        with self._lock:
            ch = self.channels.get(lower(chan))
            g = self.ghosts.get(lower(nick))
            if not ch or not g or lower(nick) not in ch.members:
                return
            ts = self.now()
            for o in self._members(ch):
                self.deliver(o, "PART", ch.name, reason, prefix=g.mask, ts=ts)
            ch.members.pop(lower(nick), None)

    def ghost_quit(self, nick: str, reason: str = "Quit: bye"):
        """A scripted user quits: QUIT once to every client sharing a channel with it, then it is gone."""
        with self._lock:
            g = self.ghosts.pop(lower(nick), None)
            if not g:
                return
            ts = self.now()
            told = {}
            for ch in self.channels.values():
                if ch.members.pop(lower(nick), None) is not None:
                    for o in self._members(ch):
                        told[o.id] = o
            for o in told.values():
                self.deliver(o, "QUIT", reason, prefix=g.mask, ts=ts)

    def ghost_nick(self, old: str, new: str):
        """A scripted user changes nick (NICK once to every client sharing a channel with it)."""
        with self._lock:
            g = self.ghosts.pop(lower(old), None)
            if not g:
                return
            mask = g.mask
            g.nick = new
            self.ghosts[lower(new)] = g
            ts = self.now()
            told = {}
            for ch in self.channels.values():
                if lower(old) in ch.members:
                    ch.members[lower(new)] = ch.members.pop(lower(old))
                    for o in self._members(ch):
                        told[o.id] = o
            for o in told.values():
                self.deliver(o, "NICK", new, prefix=mask, ts=ts)

    def inject(self, sender: str, target: str, text: str, command: str = "PRIVMSG", tags: dict | None = None,
               account: str = ""):
        """A message from anyone (a mask like 'bob!b@qa.test') to a channel's clients or to one client."""
        with self._lock:
            ts = self.now()
            if target.startswith("#"):
                ch = self.channels.get(lower(target))
                recipients = self._members(ch) if ch else []
            else:
                o = self._find(target)
                recipients = [o] if o else []
            for o in recipients:
                self.deliver(o, command, target, text, prefix=sender, account=account, client_tags=tags, ts=ts)
        return len(recipients)

    def burst(self, target: str, count: int, sender: str = "burst!b@burst.qa.test", text: str = "burst message {i}",
              command: str = "PRIVMSG") -> int:
        """count numbered messages back to back (deterministic text: 'burst message 1'...)."""
        for i in range(1, count + 1):
            self.inject(sender, target, text.format(i=i), command=command)
        return count

    def ping(self, nick: str, token: str = "qa-ping") -> str:
        self._send(self.client(nick), build("PING", token, prefix=self.name))
        return token

    # ---- synchronisation -------------------------------------------------------------------------------------

    def mark(self) -> int:
        """The current end of the event log: pass it as since= to wait only for what happens next."""
        with self._cond:
            return len(self.events)

    def wait_for(self, pattern: str, *, kind: str = "in", nick: str | None = None, since: int = 0,
                 timeout: float = 10.0, pump=None) -> Event:
        """Block until an event matches (regex search on the line). Raises TimeoutError with the recent log.

        pump: called over and over while waiting, outside the server's lock. A test whose client runs on the
        same thread (an event loop, e.g. Qt's app.processEvents) must pass it, or the client can't run."""
        rx = re.compile(pattern)
        end = time.time() + timeout
        i = since
        while True:
            with self._cond:
                while i < len(self.events):
                    e = self.events[i]
                    i += 1
                    if e.kind == kind and (nick is None or lower(e.nick) == lower(nick)) and rx.search(e.line):
                        return e
                left = end - time.time()
                if left <= 0:
                    tail = "\n".join(f"  {e.kind:7} {e.nick:10} {e.line}" for e in self.events[-15:])
                    raise TimeoutError(f"{self.name}: nothing matched {pattern!r} (kind={kind}, nick={nick}) "
                                       f"within {timeout}s; last events:\n{tail}")
                if pump is None:
                    self._cond.wait(left)
                    continue
            pump()
            with self._cond:
                if i >= len(self.events):
                    self._cond.wait(min(0.01, max(0.0, end - time.time())))

    def wait_handled(self, pattern: str, *, nick: str | None = None, since: int = 0, timeout: float = 10.0,
                     pump=None) -> Event:
        """Like wait_for on what a client sent, but only after the server has finished handling that line
        (an "in" event is logged before handling, so its effects may not be there yet)."""
        return self.wait_for(pattern, kind="done", nick=nick, since=since, timeout=timeout, pump=pump)

    def wait_registered(self, nick: str, timeout: float = 10.0) -> Client:
        self.wait_for(r"^:\S+ 001 ", kind="out", nick=nick, timeout=timeout)
        return self.client(nick)

    def wait_clients(self, n: int, timeout: float = 10.0):
        end = time.time() + timeout
        with self._cond:
            while sum(1 for c in self.clients.values() if not c.closed) < n:
                left = end - time.time()
                if left <= 0:
                    raise TimeoutError(f"{self.name}: {n} clients expected, {len(self.clients)} connected")
                self._cond.wait(left)

    def received(self, nick: str | None = None) -> list[str]:
        """Lines the server got (from one client, or from all)."""
        with self._cond:
            return [e.line for e in self.events if e.kind == "in" and (nick is None or lower(e.nick) == lower(nick))]


# ---- test client -----------------------------------------------------------------------------------------------

class IrcTestClient:
    """A plain IRC client for testing the server itself (and for a second person in a channel)."""

    def __init__(self, host: str, port: int, tls: bool = False, cafile: str | None = None, timeout: float = 10.0):
        s = socket.create_connection((host, port), timeout=timeout)
        if tls:
            ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl._create_unverified_context()
            s = ctx.wrap_socket(s, server_hostname="localhost" if cafile else None)
        s.setblocking(False)
        self.sock = s
        self._io = threading.Lock()
        self.lines: list[str] = []
        self._cond = threading.Condition()
        self.closed = False
        self._t = threading.Thread(target=self._read, name=f"{THREAD_PREFIX}-testclient", daemon=True)
        self._t.start()

    def _read(self):
        buf = b""
        while not self.closed:
            try:
                d = locked_recv(self.sock, self._io)
            except (OSError, ValueError):
                break
            if d is None:
                continue
            if not d:
                break
            buf += d
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                with self._cond:
                    self.lines.append(raw.rstrip(b"\r").decode("utf-8", "replace"))
                    self._cond.notify_all()
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    def send(self, line: str):
        locked_sendall(self.sock, self._io, (line + "\r\n").encode())

    def expect(self, pattern: str, since: int = 0, timeout: float = 10.0) -> str:
        rx = re.compile(pattern)
        end = time.time() + timeout
        with self._cond:
            i = since
            while True:
                while i < len(self.lines):
                    if rx.search(self.lines[i]):
                        return self.lines[i]
                    i += 1
                if self.closed:
                    raise ConnectionError(f"closed before {pattern!r}; got: {self.lines[-5:]}")
                left = end - time.time()
                if left <= 0:
                    raise TimeoutError(f"nothing matched {pattern!r}; last lines: {self.lines[-8:]}")
                self._cond.wait(left)

    def mark(self) -> int:
        with self._cond:
            return len(self.lines)

    def register(self, nick: str, caps: tuple = (), user: str = "qa", realname: str = "QA client") -> "IrcTestClient":
        if caps:
            self.send("CAP LS 302")
            self.send("CAP REQ :" + " ".join(caps))
        self.send(f"NICK {nick}")
        self.send(f"USER {user} 0 * :{realname}")
        if caps:
            self.expect(r" CAP \S+ (ACK|NAK) ")
            self.send("CAP END")
        self.expect(r" 001 ")
        return self

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
        self._t.join(2)
