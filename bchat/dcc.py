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
OFFER_TIMEOUT = 300
from .filetypes import PROGRAM_TYPES, is_program, mark_from_internet, strip_bidi

# never saved without being asked: these run when opened (one list with the link check, filetypes.py)
RISKY = {"." + e for e in PROGRAM_TYPES}
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name: str) -> str:
    """Only the last part of whatever path they sent, with nothing Windows treats as special."""
    name = strip_bidi(re.split(r"[/\\]", name)[-1])     # no right-to-left tricks hiding the real ending
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name.split(".")[0].upper() in RESERVED:
        name = "_" + (name or "file")
    return name[:200]


def ip_to_int(ip: str) -> int:
    return struct.unpack(">I", socket.inet_aton(ip))[0]


def int_to_ip(n: int) -> str:
    return socket.inet_ntoa(struct.pack(">I", n & 0xFFFFFFFF))


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
        most = {"SEND": 4, "RESUME": 3, "ACCEPT": 3, "CHAT": 2}.get(verb.upper(), len(words) - 1)
        numbers = 0
        while numbers < most and numbers < len(words) - 1 and words[-1 - numbers].isdigit():
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
            if self.server.listen(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), p):
                self.port = self.server.serverPort()
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
        self.started = time.time()
        self._tick_base = (self.started, self.pos)
        if self.kind == "recv":
            self._open_for_receive()
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
            data = bytes(self.sock.readAll())       # acks, four bytes each, the last one counts
            if len(data) >= 4:
                self.acked = struct.unpack(">I", data[-4:])[0]
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
        self.mgr.used(self, len(data))

    def _maybe_done(self) -> None:
        if self.kind == "send" and self.state == "active" and self.pos >= self.size and self.acked >= (self.size & 0xFFFFFFFF):
            self._finish()

    def _finish(self) -> None:
        self.state = "done"
        self.finished_at = time.time()
        self._close_file()
        if self.sock is not None:
            self.sock.disconnectFromHost()
        self.mgr.finished(self)
        self.changed.emit(self)

    def _closed(self) -> None:
        if self.kind == "chat" and self.state == "active":
            self.state = "done"
            self.mgr.chat_closed(self)
        elif self.kind == "send" and self.state == "active" and self.pos >= self.size:
            # some clients close without the last ack
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
        for raw in rows:
            self.mgr.chat_line(self, raw.rstrip(b"\r").decode("utf-8", "replace"))

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
        if self.state == "queued" and self.kind != "chat" and self.server is not None and now - self.created > OFFER_TIMEOUT:
            self.fail("Nobody connected in time")

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
        if s.external_ip:                    # Network > Local found it (this PC, the server or a website)
            return s.external_ip
        return s.sock.localAddress().toString() or "127.0.0.1"

    # --- sending ------------------------------------------------------------------------

    def send_file(self, s, nick: str, path: str, passive: bool = False) -> Transfer | None:
        p = Path(path)
        if not p.is_file():
            s.add(s._front(), "error", "*", f"Cannot access {path}")
            return None
        name = p.name.replace(" ", "_") if self.cfg.dcc_fill_spaces else p.name
        t = self._add(Transfer(self, s, "send", nick, name, p.stat().st_size))
        t.path = str(p)
        quoted = f'"{name}"' if " " in name else name
        if passive:
            t.passive = True
            t.token = str(int(time.time() * 1000) % 1000000)
            s.send("PRIVMSG", nick, f"\x01DCC SEND {quoted} {ip_to_int(self.my_address(s))} 0 {t.size} {t.token}\x01")
        else:
            if not t.listen():
                return t
            s.send("PRIVMSG", nick, f"\x01DCC SEND {quoted} {ip_to_int(self.my_address(s))} {t.port} {t.size}\x01")
        s.add(s._front(), "info", "*", f"Offering {name} ({t.size} bytes) to {nick}")
        if self.cfg.dcc_open_send:
            self.win.open_transfers()
        return t

    # --- what the other side sends ------------------------------------------------------

    def incoming(self, s, nick: str, rest: str) -> None:
        offer = parse_offer(rest)
        if offer is None:
            return
        verb, a = offer
        try:
            if verb == "SEND" and len(a) >= 4:
                self._offer_file(s, nick, a[0], int(a[1]), int(a[2]), int(a[3]), a[4] if len(a) > 4 else "")
            elif verb == "CHAT" and len(a) >= 3:
                self._offer_chat(s, nick, int(a[1]), int(a[2]))
            elif verb == "RESUME" and len(a) >= 3:
                self._resume_asked(s, nick, a[0], int(a[1]), int(a[2]))
            elif verb == "ACCEPT" and len(a) >= 3:
                self._resume_ok(s, nick, a[0], int(a[1]), int(a[2]))
            else:
                s.add(s._front(), "info", "*", f"Received an unknown DCC {verb} from {nick}")
        except (ValueError, OSError, struct.error):
            s.add(s._front(), "error", "*", f"Received a bad DCC from {nick}")

    def _offer_file(self, s, nick, name, ip, port, size, token) -> None:
        # an answer to our passive offer: they listen, we connect
        if token:
            for t in self.items:
                if t.kind == "send" and t.passive and t.token == token and lower_eq(t.nick, nick) and t.state == "queued":
                    t.ip, t.port = int_to_ip(ip), port
                    t.connect_out()
                    return
        clean = safe_name(name)
        t = self._add(Transfer(self, s, "recv", nick, clean, size))
        t.ip, t.port, t.token, t.passive = int_to_ip(ip), port, token, port == 0
        t.path = str(self.target_path(clean, nick))
        s.add(s._front(), "info", "*", f"{nick} has offered {clean} ({size} bytes)")
        s.notify.emit(s._front(), "priv")
        if self.cfg.dcc_auto == 1 and not is_program(clean):
            self.accept(t)
        if self.cfg.dcc_open_recv:
            self.win.open_transfers()

    def target_path(self, clean: str, nick: str) -> Path:
        folder = Path(self.cfg.dcc_dir) if self.cfg.dcc_dir else self.win.cfg_dir / "downloads"
        name = f"{safe_name(nick)}.{clean}" if self.cfg.dcc_with_nick else clean
        return folder / name

    def _fresh_path(self, path: Path) -> Path:
        n = 1
        out = path
        while out.exists():
            out = path.with_name(f"{path.name}.{n}")
            n += 1
        return out

    def accept(self, t: Transfer) -> None:
        if t.kind == "chat":
            if t.state == "queued":
                t.connect_out()
            return
        if t.kind != "recv" or t.state != "queued":
            return
        path = Path(t.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        t.path = str(self._fresh_path(path))
        t.name = Path(t.path).name
        self._go(t)

    def _go(self, t: Transfer) -> None:
        if t.passive:
            if t.listen():
                s = t.session
                quoted = f'"{t.name}"' if " " in t.name else t.name
                s.send("PRIVMSG", t.nick, f"\x01DCC SEND {quoted} {ip_to_int(self.my_address(s))} {t.port} {t.size} {t.token}\x01")
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
        t.session.send("PRIVMSG", t.nick, f"\x01DCC RESUME {quoted} {t.port} {t.resume_from}\x01")

    def _resume_asked(self, s, nick, name, port, pos) -> None:
        for t in self.items:
            if t.kind == "send" and t.port == port and lower_eq(t.nick, nick) and t.state == "queued" and 0 <= pos <= t.size:
                t.pos = t.acked = pos
                quoted = f'"{t.name}"' if " " in t.name else t.name
                s.send("PRIVMSG", nick, f"\x01DCC ACCEPT {quoted} {port} {pos}\x01")
                return

    def _resume_ok(self, s, nick, name, port, pos) -> None:
        for t in self.items:
            if t.kind == "recv" and t.port == port and lower_eq(t.nick, nick) and t.state == "queued" and t.resume_from == pos:
                self._go(t)
                return

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
        t = self._add(Transfer(self, s, "chat", nick, "chat"))
        t.ip, t.port = int_to_ip(ip), port
        s.add(s._front(), "info", "*", f"Received a DCC CHAT offer from {nick}")
        s.notify.emit(s._front(), "priv")
        if self.cfg.dcc_open_chat:
            self.win.open_chats()

    def start_chat(self, s, nick: str) -> Transfer | None:
        for t in self.items:
            if t.kind == "chat" and t.active and lower_eq(t.nick, nick) and t.session is s:
                s.add(s._front(), "error", "*", f"Already in a DCC chat with {nick}")
                return t
        t = self._add(Transfer(self, s, "chat", nick, "chat"))
        if t.listen():
            s.send("PRIVMSG", nick, f"\x01DCC CHAT chat {ip_to_int(self.my_address(s))} {t.port}\x01")
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
