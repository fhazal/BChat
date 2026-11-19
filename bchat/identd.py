"""0.8.8 ident server (RFC 1413), Preferences > Network setup > Ident.

Open only while a network is connecting: from the dial until the server's welcome (001), a failed try or
60 seconds, whichever comes first. Networks connecting at the same time share one listener; it closes when the
last one lets go. It answers only for a port pair that is one of those connections, so it never tells anyone
anything about other programs on this PC."""
from __future__ import annotations

import re
import socket

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QAbstractSocket, QTcpServer

PORT = 113                 # tests set a free high port
HOLD_S = 60                # the longest one connect keeps it open
_QUERY = re.compile(rb"^\s*(\d{1,5})\s*,\s*(\d{1,5})\s*$")


def clean_user(text: str) -> str:
    """A user ID that fits the reply line: no spaces, colons, commas or line breaks."""
    out = re.sub(r"[\s:,\x00-\x1f]", "", text or "")[:30]
    return out or "bchat"


def _listen(port: int) -> socket.socket:
    """A listening socket on every address that no other program shares. Qt's own listen() lets Windows share a
    port another program already holds, and then nobody knows which of the two answers."""
    try:
        k = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        dual = True
    except OSError:                                    # no IPv6 on this PC
        k, dual = socket.socket(socket.AF_INET, socket.SOCK_STREAM), False
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            k.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if dual:
            k.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        k.bind(("::" if dual else "0.0.0.0", port))
        k.listen(5)
    except OSError:
        k.close()
        raise
    return k


class IdentServer(QObject):
    def __init__(self):
        super().__init__()
        self.srv: QTcpServer | None = None
        self.holders: dict = {}           # session -> user ID

    @property
    def listening(self) -> bool:
        return self.srv is not None and self.srv.isListening()

    def acquire(self, session, user: str) -> str:
        """The session is connecting. '' = listening; else why port PORT couldn't be opened (it connects anyway)."""
        self.holders[session] = clean_user(user)
        if self.listening:
            return ""
        try:
            k = _listen(PORT)
        except OSError as e:
            self.holders.pop(session, None)
            return e.strerror or str(e) or "not allowed"
        srv = QTcpServer(self)
        if not srv.setSocketDescriptor(k.detach()):
            why = srv.errorString() or "not allowed"
            srv.deleteLater()
            self.holders.pop(session, None)
            return why
        srv.newConnection.connect(self._new)
        self.srv = srv
        return ""

    def release(self, session) -> None:
        self.holders.pop(session, None)
        if not self.holders and self.srv is not None:
            self.srv.close()
            self.srv.deleteLater()
            self.srv = None

    def _new(self) -> None:
        while self.srv is not None and self.srv.hasPendingConnections():
            c = self.srv.nextPendingConnection()
            c.setParent(self)
            c.setProperty("got", b"")
            c.readyRead.connect(lambda c=c: self._read(c))
            c.disconnected.connect(c.deleteLater)
            QTimer.singleShot(10000, c, c.abort)          # a silent asker doesn't keep a socket forever

    def _read(self, c) -> None:
        got = bytes(c.property("got") or b"") + bytes(c.readAll())
        if b"\n" not in got and len(got) < 100:
            c.setProperty("got", got)
            return
        c.write(self.answer(got.split(b"\n", 1)[0].rstrip(b"\r")).encode("ascii", "replace"))
        c.disconnectFromHost()

    def answer(self, line: bytes) -> str:
        m = _QUERY.match(line)
        if not m:
            return "0, 0 : ERROR : INVALID-PORT\r\n"
        ours, theirs = int(m.group(1)), int(m.group(2))
        if not (0 < ours < 65536 and 0 < theirs < 65536):
            return f"{ours}, {theirs} : ERROR : INVALID-PORT\r\n"
        connected = QAbstractSocket.SocketState.ConnectedState
        for s, user in self.holders.items():
            sock = getattr(s, "sock", None)
            try:
                if sock is not None and sock.state() == connected and sock.localPort() == ours and sock.peerPort() == theirs:
                    return f"{ours}, {theirs} : USERID : UNIX : {user}\r\n"
            except (RuntimeError, AttributeError):    # a socket Qt already deleted
                continue
        return f"{ours}, {theirs} : ERROR : NO-USER\r\n"


_shared: IdentServer | None = None


def shared() -> IdentServer:
    global _shared
    if _shared is None:
        _shared = IdentServer()
    return _shared
