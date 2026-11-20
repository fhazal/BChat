"""DCC: file transfers and direct chat, from XChat's src/common/dcc.c. Nothing starts without the user's OK unless they turned
auto accept on, a name from the network never picks a folder, and programs are never auto accepted."""
from __future__ import annotations

import os
import re
import shutil
import socket
import struct
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

CHUNK = 64 * 1024
OFFER_TIMEOUT = 120        # cfg.dcc_offer_timeout: an offer waiting for Accept, or for the answer to a passive offer
IDLE_TIMEOUT = 300         # cfg.dcc_idle_timeout: a transfer the other side sends nothing to (also our unanswered send)
CHAT_LINE_MAX = 16 * 1024  # a direct chat line longer than this is cut (no endless buffer)
from .config import DCC_IGNORE_EXTS
from .filetypes import PROGRAM_TYPES, is_program, mark_from_internet, strip_bidi

# never saved without being asked: these run when opened (one list with the link check, filetypes.py)
RISKY = {"." + e for e in PROGRAM_TYPES}
EXISTS_CHOICES = ("ask", "resume", "overwrite")   # cfg.dcc_exists: auto accept onto a file that is already there


def auto_risky(name: str) -> bool:
    """True when a file must wait for the user's own Accept: programs are never auto accepted."""
    return is_program(name)


def on_ignore_list(name: str, masks) -> bool:
    """cfg.dcc_ignore_exts (0.8.5): an offer whose name fits one of these masks (*.exe; a bare 'exe' = *.exe) is ignored.
    Only * and ? are wildcards; no case, and Windows' own trailing dots and spaces can't hide the ending."""
    plain = strip_bidi(name).strip().rstrip(". ").lower()
    for mask in masks or ():
        mask = str(mask).strip().lower()
        if not mask:
            continue
        if "*" not in mask and "?" not in mask:
            mask = "*." + mask.lstrip(".")
        glob = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in mask)
        if re.fullmatch(glob, plain, re.S):
            return True
    return False


def _unique_name(path: Path) -> Path:
    """A name that isn't taken yet: 'a.txt', then 'a (1).txt', 'a (2).txt' (the ending stays last)."""
    path = Path(path)
    out, n = path, 1
    while out.exists():
        out = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return out


def decode_line(raw: bytes, cut: bool = False) -> str:
    """A direct chat line: UTF-8, or Windows-1252 (older clients) when it isn't valid UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        if cut and e.reason == "unexpected end of data" and e.start >= len(raw) - 3:   # cut mid-letter
            try:
                return raw[:e.start].decode("utf-8")
            except UnicodeDecodeError:
                pass
        return raw.decode("cp1252", "replace")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name: str) -> str:
    """Only the last part of whatever path they sent, with nothing Windows treats as special."""
    name = strip_bidi(re.split(r"[/\\]", name)[-1])     # no right-to-left tricks hiding the real ending
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name.split(".")[0].upper() in RESERVED:
        name = "_" + (name or "file")
    return name[:200]


def home_address(ip: str) -> bool:
    """192.168.x, 10.x, 172.16-31.x, 127.x, 100.64-127.x (carrier NAT): people on the internet can't reach it."""
    from ipaddress import ip_address, ip_network
    try:
        a = ip_address(ip.strip())
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local or (a.version == 4 and a in ip_network("100.64.0.0/10"))


def ip_to_int(ip: str) -> int:
    return struct.unpack(">I", socket.inet_aton(ip))[0]


def int_to_ip(n: int) -> str:
    return socket.inet_ntoa(struct.pack(">I", n & 0xFFFFFFFF))


def plain_v4(ip: str) -> str:
    """'::ffff:1.2.3.4' (an IPv4 address on a dual-stack socket) -> '1.2.3.4'; anything else as it is."""
    low = ip.lower()
    return ip[7:] if low.startswith("::ffff:") and "." in ip else ip


def is_v6(ip: str) -> bool:
    return ":" in plain_v4(ip)


def address_field(ip: str) -> str:
    """The address as a DCC offer carries it: IPv4 as one big number (classic), IPv6 as it is written."""
    ip = plain_v4(ip)
    return ip if ":" in ip else str(ip_to_int(ip))


def peer_ip(field: str, ipv6_ok: bool) -> str:
    """The address in someone's DCC offer: a number (IPv4) or an IPv6 address. Anything else is refused."""
    if field.isdigit():
        return int_to_ip(int(field))
    if ipv6_ok and ":" in field:
        a = QHostAddress(field)
        if a.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv6Protocol:
            return a.toString()
    raise ValueError(field)


def parse_offer(rest: str) -> tuple[str, list[str]] | None:
    """'SEND "a b.txt" 123 45 67 [token]' -> ("SEND", ["a b.txt", "123", "45", "67"]). None if it doesn't fit."""
    verb, _, tail = rest.strip().partition(" ")
    m = re.match(r'"([^"]*)"\s*(.*)$', tail)
    if m:
        first, others = m.group(1), m.group(2).split()
    else:
        words = tail.split()
        if not words:
            return None
        # an unquoted name with spaces: the numbers at the end tell where it stops. The last one may be a passive token
        most = {"SEND": 4, "RESUME": 4, "ACCEPT": 4, "CHAT": 2}.get(verb.upper(), len(words) - 1)   # RESUME/ACCEPT: + passive token
        numbers = 0
        def numeric(w: str) -> bool:      # a number, or an IPv6 address in the address place (0.6.0)
            return w.isdigit() or (":" in w and all(c in "0123456789abcdefABCDEF:." for c in w))
        while numbers < most and numbers < len(words) - 1 and numeric(words[-1 - numbers]):
            numbers += 1
        keep = len(words) - numbers
        first, others = " ".join(words[:keep]), words[keep:]
    return verb.upper(), [first, *others]


class Transfer(QObject):
    """One send, receive or chat."""
    changed = Signal(object)

    def __init__(self, mgr, session, kind: str, nick: str, name: str = "", size: int = 0):
        super().__init__(mgr)
        self.mgr, self.session, self.kind, self.nick, self.name, self.size = mgr, session, kind, nick, name, size
        self.state = "queued"    # queued connecting active done failed aborted
        self.pos = self.resume_from = self.acked = 0
        self.ip = ""
        self.port = 0
        self.token = ""
        self.passive = False
        self.path = ""
        self.sock: QTcpSocket | None = None
        self.server: QTcpServer | None = None
        self.file = None
        self.started = 0.0
        self.created = time.time()
        self.finished_at = 0.0
        self.recv_bytes = self.sent_bytes = 0
        self._tick_base = (time.time(), 0)
        self.cps = 0
        self.buffer = None
        self._rx = b""
        self._rx_skip = False       # a too-long chat line was cut: drop the rest of it
        self._ackbuf = b""          # an ack can arrive in pieces
        self.incoming = False       # their offer, waiting for Accept (it expires after the offer timeout)
        self.last_data = self.listening_since = self.created
        self.error = ""
        self.tick_used = 0

    @property
    def active(self) -> bool:
        return self.state in ("queued", "connecting", "active")

    # --- connections --------------------------------------------------------------

    def listen(self) -> bool:
        cfg = self.mgr.cfg
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._incoming)
        first, last = cfg.dcc_first_port, cfg.dcc_last_port
        ports = range(first, max(first, last) + 1) if first else [0]
        for p in ports:
            if self.server.listen(QHostAddress(QHostAddress.SpecialAddress.Any if cfg.dcc_ipv6
                                               else QHostAddress.SpecialAddress.AnyIPv4), p):
                self.port = self.server.serverPort()
                self.listening_since = time.time()
                return True
        self.fail(f"No free port between {first} and {last}")
        return False

    def _incoming(self) -> None:
        sock = self.server.nextPendingConnection()
        if self.sock is not None:     # only the first caller
            sock.abort()
            sock.deleteLater()
            return
        self.server.close()
        self._attach(sock)
        self._connected()

    def connect_out(self) -> None:
        self.state = "connecting"
        self._attach(QTcpSocket(self))
        self.sock.connected.connect(self._connected)
        self.sock.connectToHost(self.ip, self.port)
        self.changed.emit(self)

    def _attach(self, sock: QTcpSocket) -> None:
        self.sock = sock
        sock.readyRead.connect(self._readable)
        sock.bytesWritten.connect(self._writable)
        sock.disconnected.connect(self._closed)
        sock.errorOccurred.connect(self._sock_error)

    def _connected(self) -> None:
        self.state = "active"
        self.started = self.last_data = time.time()
        self._tick_base = (self.started, self.pos)
        if self.kind == "recv":
            self._open_for_receive()
            if self.state == "active" and self.pos >= self.size:     # an empty file: nothing to wait for
                self._finish()
                return
        elif self.kind == "send":
            self._send_more()
        else:
            self.mgr.chat_opened(self)
        self.changed.emit(self)

    def _open_for_receive(self) -> None:
        try:
            self.file = open(self.path, "ab" if self.resume_from else "wb")
            # "downloaded from the internet", like a browser download: Windows SmartScreen checks it before it runs
            net = getattr(getattr(self.session, "net", None), "name", "") or "irc"
            mark_from_internet(self.path, f"irc://{net}/{self.nick}")
            if self.resume_from:
                self.file.truncate(self.resume_from)
                self.pos = self.acked = self.resume_from
        except OSError as e:
            self.fail(f"Couldn't write {self.path}: {e}")

    def _readable(self) -> None:
        if self.sock is None:
            return
        if self.kind == "recv":
            self._receive()
        elif self.kind == "send":
            self._take_acks(bytes(self.sock.readAll()))
            self._maybe_done()
        else:
            self._chat_read()

    def _receive(self) -> None:
        limit = self.mgr.allowance("recv", self)
        if limit == 0 or self.file is None:
            return
        data = bytes(self.sock.read(limit if limit > 0 else CHUNK * 4))
        if not data:
            return
        room = self.size - self.pos if self.size else len(data)
        if len(data) > room:      # they may not write more than they offered
            data = data[:room]
        try:
            self.file.write(data)
        except OSError as e:
            self.fail(f"Couldn't write: {e}")
            return
        self.pos += len(data)
        self.last_data = time.time()
        self.mgr.used(self, len(data))
        self.sock.write(struct.pack(">I", self.pos & 0xFFFFFFFF))
        if self.size and self.pos >= self.size:
            self._finish()
        elif self.sock.bytesAvailable():
            QTimer.singleShot(0 if limit < 0 else 50, self._readable)

    def _writable(self, _n: int = 0) -> None:
        if self.kind == "send" and self.state == "active":
            self._send_more()

    def _send_more(self) -> None:
        if self.sock is None or self.state != "active" or self.pos >= self.size or self.sock.bytesToWrite() > CHUNK * 2:
            self._maybe_done()
            return
        limit = self.mgr.allowance("send", self)
        if limit == 0:
            return
        try:
            if self.file is None:
                self.file = open(self.path, "rb")
            self.file.seek(self.pos)
            data = self.file.read(min(CHUNK, limit) if limit > 0 else CHUNK)
        except OSError as e:
            self.fail(f"Couldn't read {self.path}: {e}")
            return
        if not data:
            self._maybe_done()
            return
        self.sock.write(data)
        self.pos += len(data)
        self.last_data = time.time()
        self.mgr.used(self, len(data))

    def _take_acks(self, data: bytes) -> None:
        """Acks: four bytes each, the last one counts. They are the received total cut to 32 bits, so past 4 GB
        they wrap to 0: count the wraps. The true total is the one value at or below what we sent that fits."""
        data = self._ackbuf + data
        whole = len(data) - len(data) % 4
        self._ackbuf = data[whole:]
        if not whole:
            return
        low = struct.unpack(">I", data[whole - 4:whole])[0]
        total = self.pos - ((self.pos - low) & 0xFFFFFFFF)     # wraps counted: same low 32 bits, never past pos
        if total > self.acked:
            self.acked = total
            self.last_data = time.time()

    def _maybe_done(self) -> None:
        if self.kind == "send" and self.state == "active" and self.pos >= self.size and self.acked >= self.size:
            self._finish()

    def _all_acked_on_close(self) -> bool:
        """They closed after we sent everything. Done when the acks cover the file, or (some clients drop the
        last ack) when only the last chunk is missing and the close was clean: nothing of ours left unsent."""
        if self.acked >= self.size:
            return True
        clean = self.sock is None or self.sock.bytesToWrite() == 0
        return clean and self.size - self.acked <= CHUNK

    def _finish(self) -> None:
        self.state = "done"
        self.finished_at = time.time()
        self._close_file()
        if self.sock is not None:
            # send the final ack now: finished() below may move a big file to another drive first, and the
            # sender only learns it's done once this ack arrives (a slow move made it time out)
            self.sock.flush()
            self.sock.disconnectFromHost()
        self.mgr.finished(self)
        self.changed.emit(self)

    def _closed(self) -> None:
        if self.kind == "send" and self.state == "active" and self.sock is not None and self.sock.bytesAvailable():
            self._take_acks(bytes(self.sock.readAll()))      # acks that came in with the close count too
        if self.kind == "chat" and self.state == "active":
            self.state = "done"
            self.mgr.chat_closed(self)
        elif self.kind == "send" and self.state == "active" and self.pos >= self.size and self._all_acked_on_close():
            self._finish()
        elif self.state == "active":
            self.fail("Connection closed before the end")
        self.changed.emit(self)

    def _sock_error(self, err) -> None:
        if err == QAbstractSocket.SocketError.RemoteHostClosedError or self.sock is None or not self.active:
            return
        self.fail(self.sock.errorString())

    def fail(self, why: str) -> None:
        self.state = "failed"
        self.error = why
        self._drop()
        self.mgr.report(self, f"DCC {self.label()} failed: {why}")
        self.changed.emit(self)

    def abort(self) -> None:
        if not self.active:
            return
        self.state = "aborted"
        self._drop()
        self.mgr.report(self, f"DCC {self.label()} aborted.")
        self.changed.emit(self)

    def _close_file(self) -> None:
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                pass
            self.file = None

    def _drop(self) -> None:
        self._close_file()
        if self.server is not None:
            self.server.close()
        if self.sock is not None:
            self.sock.blockSignals(True)
            self.sock.abort()

    def label(self) -> str:
        return {"send": f'send of "{self.name}" to {self.nick}', "recv": f'receive of "{self.name}" from {self.nick}', "chat": f"chat with {self.nick}"}[self.kind]

    # --- chat ------------------------------------------------------------------------

    def _chat_read(self) -> None:
        self._rx += bytes(self.sock.readAll())
        self.recv_bytes = self.pos = self.pos + 0
        *rows, self._rx = self._rx.split(b"\n")
        out = []
        for raw in rows:
            if self._rx_skip:            # the end of a line already cut and shown
                self._rx_skip = False
                continue
            out.append(raw[:CHAT_LINE_MAX])
        if len(self._rx) > CHAT_LINE_MAX:
            if not self._rx_skip:        # no newline in 16 KB: show what came, drop the rest of that line
                out.append(self._rx[:CHAT_LINE_MAX])
            self._rx_skip = True
            self._rx = b""
        for raw in out:
            self.mgr.chat_line(self, decode_line(raw.rstrip(b"\r"), cut=len(raw) >= CHAT_LINE_MAX))

    def chat_send(self, text: str) -> None:
        data = text.encode("utf-8", "replace") + b"\n"
        self.sock.write(data)
        self.sock.flush()
        self.sent_bytes += len(data)
        self.changed.emit(self)

    # --- numbers for the windows -------------------------------------------------------

    def tick(self) -> None:
        when, at = self._tick_base
        now = time.time()
        if now - when >= 1:
            self.cps = int((self.pos - at) / (now - when))
            self._tick_base = (now, self.pos)
        waited = now - self.created
        offer, idle = self.mgr.timeouts()                 # 0 = wait for ever
        if self.state == "queued":
            if self.server is not None and (self.passive or self.kind == "chat"):
                if offer and now - self.listening_since > offer:   # we listen for a passive answer or a chat
                    self.fail("Nobody connected in time")
            elif self.kind == "send" and self.passive:
                if offer and waited > offer:            # our passive offer: no answer with the token
                    self.fail("Nobody connected in time")
            elif self.server is not None and self.kind != "chat":
                if idle and waited > idle:              # our send offer: nobody connected
                    self.fail("Nobody connected in time")
            elif self.incoming and offer and waited > offer:   # their offer, never accepted
                self.fail("Offer expired")
        elif self.state == "active" and self.kind != "chat" and idle and now - self.last_data > idle:
            self.fail("Transfer timed out")

    def percent(self) -> int:
        return int(self.pos * 100 / self.size) if self.size else 0

    def eta(self) -> str:
        if not self.cps or self.state != "active":
            return ""
        left = (self.size - self.pos) // self.cps
        return f"{left // 3600:02d}:{left % 3600 // 60:02d}:{left % 60:02d}"


class DccManager(QObject):
    updated = Signal()

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.cfg = win.cfg
        self.items: list[Transfer] = []
        # on_exists(t, free_name): the window asks Overwrite / Resume / Rename, then calls accept(t, how, name)
        self.on_exists = None
        self._used = {"send": 0, "recv": 0}
        self._ticker = QTimer(self, interval=1000, timeout=self._tick)
        self._ticker.start()
        self._pump = QTimer(self, interval=100, timeout=self._throttle_tick)

    def _tick(self) -> None:
        for t in self.items:
            if t.active:
                t.tick()
        self.updated.emit()

    # speed limits, per 100 ms: one transfer's own limit and the shared one, whichever is lower
    def _limit(self, kind: str) -> tuple[int, int]:
        c = self.cfg
        return (c.dcc_max_send, c.dcc_max_send_all) if kind == "send" else (c.dcc_max_get, c.dcc_max_get_all)

    def allowance(self, kind: str, t: Transfer) -> int:
        one, everyone = self._limit(kind)
        if not one and not everyone:
            return -1
        if not self._pump.isActive():
            self._pump.start()
        left = []
        if one:
            left.append(max(0, one * 1024 // 10 - t.tick_used))
        if everyone:
            left.append(max(0, everyone * 1024 // 10 - self._used[kind]))
        return min(left)

    def used(self, t: Transfer, n: int) -> None:
        self._used[t.kind] += n
        t.tick_used += n

    def _throttle_tick(self) -> None:
        self._used = {"send": 0, "recv": 0}
        busy = False
        for t in self.items:
            t.tick_used = 0
            if t.state == "active" and t.kind == "recv" and t.sock is not None:
                t._receive()
                busy = True
            elif t.state == "active" and t.kind == "send":
                t._send_more()
                busy = True
        if not busy:
            self._pump.stop()

    def _add(self, t: Transfer) -> Transfer:
        self.items.append(t)
        t.changed.connect(lambda _t: self.updated.emit())
        self.updated.emit()
        return t

    def report(self, t: Transfer, text: str) -> None:
        s = t.session
        try:
            s.add(s._front(), "info", "*", text)
        except RuntimeError:
            pass

    def my_address(self, s) -> str:
        c = self.cfg
        if c.dcc_ip.strip():
            return c.dcc_ip.strip()
        upnp = getattr(self.win, "upnp", None)
        if upnp is not None and upnp.external_ip:     # 0.8.8: the router opened the ports and told us its address
            return upnp.external_ip
        if s.external_ip:                    # Network > Local found it (this PC, the server or a website)
            return s.external_ip
        return plain_v4(s.sock.localAddress().toString()) or "127.0.0.1"

    def offer_address(self, s) -> str | None:
        """What goes in our DCC offer. An IPv6 address only with Preferences > Network setup's IPv6 tick on."""
        ip = self.my_address(s)
        if is_v6(ip) and not self.cfg.dcc_ipv6:
            s.add(s._front(), "error", "*", "Your connection is IPv6 only and IPv6 for file transfers is off "
                                            "(Preferences > Network setup), so this can't be offered.")
            return None
        try:
            return address_field(ip)
        except OSError:
            s.add(s._front(), "error", "*", f"Couldn't use the address {ip} for a file transfer.")
            return None

    # --- sending ------------------------------------------------------------------------

    def send_passive(self, s) -> bool:
        """0.8.9 Settings > File transfers > Send files. Auto = passive only when nobody outside can reach us:
        a home-network address, no port range set (so none forwarded by hand) and the router (UPnP) opened nothing."""
        mode = self.cfg.dcc_send_mode
        if mode in ("normal", "passive"):
            return mode == "passive"
        upnp = getattr(self.win, "upnp", None)
        if upnp is not None and upnp.ports_open:
            return False
        c = self.cfg
        if c.dcc_first_port and c.dcc_last_port and not getattr(c, "upnp_on", False):
            return False                    # a range without UPnP: maybe forwarded by hand. With UPnP on, the
        ip = c.dcc_ip.strip()               # range was for the router, and it opened nothing (ports_open above)
        if not ip:
            sock = getattr(s, "sock", None)
            ip = plain_v4(sock.localAddress().toString()) if sock is not None else ""
        if not ip or ip.startswith("127.") or ip == "::1":
            return False                # this PC only (a bouncer here, or a test): we can't tell, so send the usual way
        return home_address(ip)

    def send_file(self, s, nick: str, path: str, passive: bool | None = None) -> Transfer | None:
        """passive None = Settings > File transfers > Send files decides (/dcc psend passes True)."""
        if self.locked(s):
            return None
        p = Path(path)
        if not p.is_file():
            s.add(s._front(), "error", "*", f"Cannot access {path}")
            return None
        name = p.name.replace(" ", "_") if self.cfg.dcc_fill_spaces else p.name
        t = self._add(Transfer(self, s, "send", nick, name, p.stat().st_size))
        t.path = str(p)
        quoted = f'"{name}"' if " " in name else name
        addr = self.offer_address(s)
        if addr is None:
            if t in self.items:
                self.items.remove(t)
            self.updated.emit()
            return None
        if passive is None:
            passive = self.send_passive(s)
        if passive:
            t.passive = True
            t.token = self._new_token()
            s.send("PRIVMSG", nick, f"\x01DCC SEND {quoted} {addr} 0 {t.size} {t.token}\x01")
        else:
            if not t.listen():
                return t
            s.send("PRIVMSG", nick, f"\x01DCC SEND {quoted} {addr} {t.port} {t.size}\x01")
        s.add(s._front(), "info", "*", f"Offering {name} ({t.size} bytes) to {nick}" + (" (passive)" if t.passive else ""))
        if self.cfg.dcc_open_send:
            self.win.open_transfers()
        return t

    # --- what the other side sends ------------------------------------------------------

    def locked(self, s) -> bool:
        """0.6.0 Lock 'No file transfers or direct chats'."""
        if (getattr(self.cfg, "lock_limits", None) or {}).get("no_dcc"):
            s.add(s._front(), "info", "*", "Lock: file transfers and direct chats are off on this PC.")
            return True
        return False

    def incoming(self, s, nick: str, rest: str) -> None:
        offer = parse_offer(rest)
        if offer is None:
            return
        if offer[0] in ("SEND", "CHAT") and self.locked(s):
            return
        verb, a = offer
        try:
            if verb == "SEND" and len(a) >= 4:
                self._offer_file(s, nick, a[0], peer_ip(a[1], self.cfg.dcc_ipv6), int(a[2]), int(a[3]), a[4] if len(a) > 4 else "")
            elif verb == "CHAT" and len(a) >= 3:
                self._offer_chat(s, nick, peer_ip(a[1], self.cfg.dcc_ipv6), int(a[2]))
            elif verb == "RESUME" and len(a) >= 3:
                self._resume_asked(s, nick, a[0], int(a[1]), int(a[2]), a[3] if len(a) > 3 else "")
            elif verb == "ACCEPT" and len(a) >= 3:
                self._resume_ok(s, nick, a[0], int(a[1]), int(a[2]), a[3] if len(a) > 3 else "")
            else:
                s.add(s._front(), "info", "*", f"Received an unknown DCC {verb} from {nick}")
        except (ValueError, OSError, struct.error):
            s.add(s._front(), "error", "*", f"Received a bad DCC from {nick}")

    def trusted(self, s, nick: str) -> bool:
        """Preferences > File transfers > Trusted people: the whole address must match (a nick alone never does)."""
        return is_trusted(self.cfg, s.net.name, getattr(s, "last_ctcp_prefix", "") or "")

    def _offer_file(self, s, nick, name, ip, port, size, token) -> None:
        # an answer to our passive offer: they listen, we connect. The token and the name pick which one
        if token and port:
            t = self._pick([t for t in self.items if t.kind == "send" and t.passive and t.token == token
                            and lower_eq(t.nick, nick) and t.state == "queued"], name)
            if t is not None:
                t.ip, t.port = ip, port
                t.connect_out()
                return
        if not self._offer_allowed(s, nick):
            return
        clean = safe_name(name)
        why = self.ignore_reason(clean)
        if why:
            s.add(s.server_buffer, "info", "*", f"DCC Send of {clean} from {nick} ignored ({why})")
            return
        t = self._add(Transfer(self, s, "recv", nick, clean, size))
        t.ip, t.port, t.token, t.passive = ip, port, token, port == 0
        t.incoming = True
        t.path = str(self.target_path(clean, nick))
        s.add(s._front(), "info", "*", f"{nick} has offered {clean} ({size} bytes)")
        s.last_dcc = nick
        trusted = self.trusted(s, nick)
        auto = (self.cfg.dcc_auto == 1 or self.cfg.dcc_auto == 2 and trusted) and not auto_risky(clean)
        s.last_dcc_trusted = auto and trusted
        s.notify.emit(s._front(), "dcc")         # its own card; taskbar / tray blink follow the Private column
        if auto:
            if trusted:
                s.add(s._front(), "info", "*", f"Accepted {clean} from {nick} (trusted).")
            self.accept(t, auto=True)
        if self.cfg.dcc_open_recv:
            self.win.open_transfers()

    def target_path(self, clean: str, nick: str) -> Path:
        folder = Path(self.cfg.dcc_dir) if self.cfg.dcc_dir else self.win.cfg_dir / "downloads"
        name = f"{safe_name(nick)}.{clean}" if self.cfg.dcc_with_nick else clean
        return folder / name

    def _fresh_path(self, path: Path) -> Path:
        return _unique_name(path)

    def _new_token(self) -> str:
        """A passive offer's token, never one an offer still waiting already has."""
        busy = {t.token for t in self.items if t.kind == "send" and t.passive and t.active}
        n = int(time.time() * 1000) % 1000000
        while str(n) in busy:
            n = (n + 1) % 1000000
        return str(n)

    @staticmethod
    def _pick(found: list, name: str):
        """One transfer out of those that fit: the only one, or the only one with this name. Never a guess."""
        if len(found) == 1:
            return found[0]
        named = [t for t in found if lower_eq(t.name, name) or lower_eq(t.name, safe_name(name))
                 or lower_eq(t.name.replace(" ", "_"), name.replace(" ", "_"))]
        return named[0] if len(named) == 1 else None

    def ignore_reason(self, name: str) -> str:
        """Why the DCC ignore list keeps this offer out ('' = it comes in). Off: nothing is kept out. Ignore mode:
        the listed types are kept out. Accept mode: only the listed types come in (programs still wait for Accept)."""
        if not getattr(self.cfg, "dcc_ignore_on", True):
            return ""
        listed = on_ignore_list(name, getattr(self.cfg, "dcc_ignore_exts", DCC_IGNORE_EXTS))
        if getattr(self.cfg, "dcc_ignore_mode", "ignore") == "accept":
            return "" if listed else "file type is not on the DCC accept list"
        return "file type is on the DCC ignore list" if listed else ""

    def ignore_command(self, s, b, args: list[str]) -> None:
        """/dcc ignore [on|off|accept|ignore]: the list on or off, or what it does; nothing = how it is now."""
        word = args[0].lower() if args else ""
        if word in ("on", "off"):
            self.cfg.dcc_ignore_on = word == "on"
        elif word in ("accept", "ignore"):
            self.cfg.dcc_ignore_mode = word
        elif word:
            s.add(b, "error", "*", "Usage: DCC IGNORE [on|off|accept|ignore]")
            return
        if word and hasattr(self.win, "save_config"):
            self.win.save_config()
        types = " ".join(getattr(self.cfg, "dcc_ignore_exts", DCC_IGNORE_EXTS)) or "none"
        if not getattr(self.cfg, "dcc_ignore_on", True):
            s.add(b, "info", "*", f"DCC ignore is off: every file offer comes in (list: {types}).")
        elif getattr(self.cfg, "dcc_ignore_mode", "ignore") == "accept":
            s.add(b, "info", "*", f"DCC ignore is on: only these file types come in: {types}")
        else:
            s.add(b, "info", "*", f"DCC ignore is on: these file types are ignored: {types}")

    def _offer_allowed(self, s, nick: str) -> bool:
        """Every offer reaches the user (the flood guard only limits what we answer). The one exception: someone
        ignored for DCC, or for everything (an ignore with no type). The session drops those first; this is the net."""
        ignored = getattr(s, "ignored", None)
        if ignored is None:
            return True
        prefix = getattr(s, "last_ctcp_prefix", "") or ""
        if not lower_eq(prefix.partition("!")[0], nick):
            prefix = f"{nick}!*@*"
        return not ignored(prefix, "D")

    def timeouts(self) -> tuple[int, int]:
        """(offer, idle) seconds: an offer waiting for Accept or for its passive answer, and a transfer the other
        side sends nothing to. 0 = wait for ever."""
        def secs(key, default):
            try:
                return max(0, int(getattr(self.cfg, key, default)))
            except (TypeError, ValueError):
                return default
        return secs("dcc_offer_timeout", OFFER_TIMEOUT), secs("dcc_idle_timeout", IDLE_TIMEOUT)

    def exists_choice(self) -> str:
        """cfg.dcc_exists: what auto accept does when the file is already there (ask, resume, overwrite)."""
        how = getattr(self.cfg, "dcc_exists", "ask")
        return how if how in EXISTS_CHOICES else "ask"

    def free_name(self, t: Transfer) -> str:
        """The name a Rename starts with: the first free one, 'a (1).txt'."""
        return _unique_name(Path(t.path)).name

    def accept(self, t: Transfer, how: str = "", name: str = "", auto: bool = False) -> None:
        """Start a file offer. When the file is already in the folder, how says what to do: 'overwrite' (the whole
        file again), 'resume' (ask them for the rest), 'rename' (save as name, or the first free name), 'cancel'
        (nothing starts, the offer keeps waiting). With no how, on_exists asks the user; auto accept uses
        cfg.dcc_exists first. Never overwritten without being told to."""
        if t.kind == "chat":
            if t.state == "queued":
                t.connect_out()
            return
        if t.kind != "recv" or t.state != "queued":
            return
        path = Path(t.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not how and path.exists():
            how = self.exists_choice() if auto else "ask"
            if how == "resume" and not self.can_resume(t):
                how = "ask"
            if how == "ask":
                if self.on_exists is not None:
                    self.on_exists(t, self.free_name(t))
                    return
                how = "rename"                  # nobody to ask: keep both files
        if how == "resume":
            if self.can_resume(t):
                self.resume(t)
            return
        if how == "rename":
            path = _unique_name(path.with_name(safe_name(name)) if name and name.strip() else path)
        elif how not in ("", "overwrite"):
            return                              # cancel
        t.resume_from = 0
        t.path = str(path)
        t.name = path.name
        self._go(t)

    def _go(self, t: Transfer) -> None:
        if t.passive:
            if t.listen():
                s = t.session
                quoted = f'"{t.name}"' if " " in t.name else t.name
                s.send("PRIVMSG", t.nick, f"\x01DCC SEND {quoted} {self.offer_address(s) or 0} {t.port} {t.size} {t.token}\x01")
        else:
            t.connect_out()

    def can_resume(self, t: Transfer) -> bool:
        p = Path(t.path)
        return t.kind == "recv" and t.state == "queued" and p.is_file() and 0 < p.stat().st_size < t.size

    def resume(self, t: Transfer) -> None:
        if not self.can_resume(t):
            return
        t.resume_from = Path(t.path).stat().st_size
        quoted = f'"{t.name}"' if " " in t.name else t.name
        token = f" {t.token}" if t.passive and t.token else ""        # passive: the token says which offer
        t.session.send("PRIVMSG", t.nick, f"\x01DCC RESUME {quoted} {t.port} {t.resume_from}{token}\x01")

    @staticmethod
    def _same_offer(t: Transfer, port: int, token: str) -> bool:
        """A RESUME / ACCEPT is about this offer: passive ones by their token, the others by their port."""
        if t.passive:
            return port == 0 and (t.token == token if token else True)
        return not token and port != 0 and t.port == port

    def _resume_asked(self, s, nick, name, port, pos, token: str = "") -> None:
        t = self._pick([t for t in self.items if t.kind == "send" and lower_eq(t.nick, nick) and t.state == "queued"
                        and self._same_offer(t, port, token) and 0 <= pos <= t.size], name)
        if t is None:
            return
        t.pos = t.acked = pos
        quoted = f'"{t.name}"' if " " in t.name else t.name
        s.send("PRIVMSG", nick, f"\x01DCC ACCEPT {quoted} {port} {pos}{f' {token}' if token else ''}\x01")

    def _resume_ok(self, s, nick, name, port, pos, token: str = "") -> None:
        t = self._pick([t for t in self.items if t.kind == "recv" and lower_eq(t.nick, nick) and t.state == "queued"
                        and self._same_offer(t, port, token) and t.resume_from and t.resume_from == pos], name)
        if t is not None:
            self._go(t)

    def finished(self, t: Transfer) -> None:
        s = t.session
        secs = max(0.001, time.time() - t.started)
        if t.kind == "recv" and self.cfg.dcc_done_dir:
            try:
                folder = Path(self.cfg.dcc_done_dir)
                folder.mkdir(parents=True, exist_ok=True)
                moved = self._fresh_path(folder / Path(t.path).name)
                shutil.move(t.path, moved)
                t.path = str(moved)
                # a move to another drive copies only the file itself: put the "from the internet" mark back
                mark_from_internet(t.path, f"irc://{getattr(s.net, 'name', '') or 'irc'}/{t.nick}")
            except OSError as e:
                s.add(s._front(), "error", "*", f"Couldn't move {t.name}: {e}")
        word = "send of" if t.kind == "send" else "receive of"
        s.add(s._front(), "info", "*", f'DCC {word} "{t.name}" complete, {t.size} bytes at {int(t.size / secs / 1024)} KB/s')
        self.updated.emit()

    # --- chat ---------------------------------------------------------------------------

    def _offer_chat(self, s, nick, ip, port) -> None:
        if not self._offer_allowed(s, nick):
            return
        t = self._add(Transfer(self, s, "chat", nick, "chat"))
        t.ip, t.port = ip, port
        t.incoming = True
        s.add(s._front(), "info", "*", f"Received a DCC CHAT offer from {nick}")
        s.notify.emit(s._front(), "priv")
        if self.cfg.dcc_auto in (1, 2) and self.trusted(s, nick):
            s.add(s._front(), "info", "*", f"Direct chat with {nick} accepted (trusted).")
            self.accept(t)
        if self.cfg.dcc_open_chat:
            self.win.open_chats()

    def start_chat(self, s, nick: str) -> Transfer | None:
        if self.locked(s):
            return None
        for t in self.items:
            if t.kind == "chat" and t.active and lower_eq(t.nick, nick) and t.session is s:
                s.add(s._front(), "error", "*", f"Already in a DCC chat with {nick}")
                return t
        t = self._add(Transfer(self, s, "chat", nick, "chat"))
        if t.listen():
            s.send("PRIVMSG", nick, f"\x01DCC CHAT chat {self.offer_address(s) or 0} {t.port}\x01")
            s.add(s._front(), "info", "*", f"Offering DCC CHAT to {nick}")
        if self.cfg.dcc_open_chat:
            self.win.open_chats()
        return t

    def chat_buffer(self, t: Transfer):
        return t.session.buffer("=" + t.nick)

    def chat_opened(self, t: Transfer) -> None:
        b = self.chat_buffer(t)
        t.session.add(b, "connect", "*", f"DCC CHAT connection established to {t.nick} [{t.sock.peerAddress().toString()}]")
        self.win.select_buffer(b)

    def chat_closed(self, t: Transfer) -> None:
        t.session.add(self.chat_buffer(t), "error", "*", f"DCC CHAT to {t.nick} lost.")

    def chat_line(self, t: Transfer, text: str) -> None:
        t.recv_bytes += len(text) + 1
        b = self.chat_buffer(t)
        s = t.session
        if text.startswith("\x01ACTION "):
            s.add(b, "action", "*", f"{t.nick} {text[8:].rstrip(chr(1))}")
        else:
            s.add(b, "msg", t.nick, text)
        s._bump(b, 3)
        s.notify.emit(b, "priv")

    def say(self, s, target: str, text: str) -> bool:
        """A line typed in an =nick tab. False when there's no chat to send it on."""
        for t in self.items:
            if t.kind == "chat" and t.state == "active" and t.session is s and lower_eq("=" + t.nick, target):
                t.chat_send(text)
                b = s.buffer(target)
                if text.startswith("\x01ACTION "):
                    s.add(b, "action", "*", f"{s.nick} {text[8:].rstrip(chr(1))}")
                else:
                    s.add(b, "self", s.nick, text)
                return True
        return False

    def clear_finished(self) -> None:
        self.items = [t for t in self.items if t.active]
        self.updated.emit()

    def shutdown(self) -> None:
        for t in self.items:
            t.blockSignals(True)
            t._drop()


def lower_eq(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def nick_only(mask: str) -> bool:
    """A trust entry must name an address: '*!*@host' or '*!user@host'. 'Wira' or 'Wira!*@*' is refused."""
    m = mask.strip()
    if "@" not in m:
        return True
    host = m.split("@", 1)[1]
    return host.strip("*.") == ""


def is_trusted(cfg, network: str, prefix: str) -> bool:
    import fnmatch
    from .protocol import lower
    if not prefix or "!" not in prefix or "@" not in prefix:
        return False
    for e in cfg.dcc_trusted:
        net = e.get("net", "")
        if net and lower(net) != lower(network or ""):
            continue
        mask = e.get("mask", "")
        if not mask or nick_only(mask):
            continue
        if "!" not in mask:
            mask = "*!" + mask
        if fnmatch.fnmatchcase(lower(prefix), lower(mask)):
            return True
    return False


class TrustDialog:
    """Add or edit one trusted person: nick (a label), address mask, network. Built lazily (Qt only when used)."""

    def __new__(cls, parent, entry: dict, networks: list[str]):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
        from .widgets import FramedDialog, icon

        class _Dialog(FramedDialog):
            def __init__(self):
                super().__init__("BChat: Trusted Person", parent)
                f = QFormLayout()
                self.nick = QLineEdit(entry.get("nick", ""))
                self.mask = QLineEdit(entry.get("mask", ""))
                self.mask.setPlaceholderText("*!user@host  or  *!*@host")
                self.net = QComboBox()
                self.net.addItem("All networks", "")
                for n in networks:
                    self.net.addItem(n, n)
                want = entry.get("net", "")
                if want and self.net.findData(want) < 0:
                    self.net.addItem(want, want)
                self.net.setCurrentIndex(max(0, self.net.findData(want)))
                f.addRow("Nick:", self.nick)
                f.addRow("Address:", self.mask)
                f.addRow("Network:", self.net)
                self.body.addLayout(f)
                self.why = QLabel("")
                self.body.addWidget(self.why)
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
                self.mask.textChanged.connect(self._check)
                self._check()
                self.resize(420, 0)

            def _check(self) -> None:
                bad = nick_only(self.mask.text())
                self.ok.setEnabled(not bad)
                self.why.setText("The address needs a host, like *!*@their.host: a nick alone is never enough." if bad and
                                 self.mask.text().strip() else "")

            def entry(self) -> dict:
                return {"nick": self.nick.text().strip(), "mask": self.mask.text().strip(), "net": self.net.currentData() or ""}

        return _Dialog()
