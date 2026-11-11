"""IRC over WebSocket (0.6.0): wss://host/path servers, for networks that only offer web access.

WsSocket looks like the QSslSocket the Session already uses (same signals, the few methods it calls), so the rest of
BChat doesn't know the difference. IRCv3 WebSocket: one IRC line per text message, no CR LF; the "text.ircv3.net"
subprotocol is asked for. Only wss:// (encrypted) is ever connected; plain ws:// is refused by the Session.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkRequest, QSslCertificate, QSslCipher

SUBPROTOCOL = "text.ircv3.net"


class WsSocket(QObject):
    connected = Signal()
    encrypted = Signal()
    readyRead = Signal()
    disconnected = Signal()
    errorOccurred = Signal(object)
    sslErrors = Signal(list)

    def __init__(self, parent=None, path: str = "/"):
        super().__init__(parent)
        from PySide6.QtWebSockets import QWebSocket, QWebSocketHandshakeOptions
        self.path = path or "/"
        self.ws = QWebSocket("", parent=self)
        self._opts = QWebSocketHandshakeOptions()
        self._opts.setSubprotocols([SUBPROTOCOL])
        self._in = b""
        self._out = b""
        self._error = ""
        self._cert = QSslCertificate()
        self._key = None
        self.ws.connected.connect(self._on_connected)
        self.ws.disconnected.connect(self.disconnected)
        self.ws.textMessageReceived.connect(lambda t: self._arrived(t.encode("utf-8")))
        self.ws.binaryMessageReceived.connect(lambda b: self._arrived(bytes(b)))
        self.ws.errorOccurred.connect(self._on_error)
        self.ws.sslErrors.connect(lambda errs: self.sslErrors.emit(list(errs)))

    # --- what the Session calls -------------------------------------------------------------

    def connectToHostEncrypted(self, host: str, port: int, *_args) -> None:
        h = f"[{host}]" if ":" in host else host
        req = QNetworkRequest(QUrl(f"wss://{h}:{port}{self.path}"))
        if not self._cert.isNull() and self._key is not None:
            conf = req.sslConfiguration()
            conf.setLocalCertificate(self._cert)
            conf.setPrivateKey(self._key)
            req.setSslConfiguration(conf)
        self.ws.open(req, self._opts)

    def connectToHost(self, host: str, port: int, *_args) -> None:
        self._error = "a WebSocket server needs wss:// (encrypted)"
        self.errorOccurred.emit(QAbstractSocket.SocketError.UnsupportedSocketOperationError)

    def write(self, data) -> int:
        self._out += bytes(data)
        *lines, self._out = self._out.split(b"\n")
        for line in lines:
            line = line.rstrip(b"\r")
            if line:
                self.ws.sendTextMessage(line.decode("utf-8", "replace"))
        return len(data)

    def readAll(self) -> bytes:
        data, self._in = self._in, b""
        return data

    def flush(self) -> bool:
        return True

    def abort(self) -> None:
        self.ws.abort()

    def disconnectFromHost(self) -> None:
        self.ws.close()

    def state(self):
        S = QAbstractSocket.SocketState
        st = self.ws.state()
        return S.ConnectedState if st == S.ConnectedState else S.UnconnectedState if st == S.UnconnectedState else st

    def errorString(self) -> str:
        return self._error or self.ws.errorString()

    def peerCertificate(self) -> QSslCertificate:
        return self.ws.sslConfiguration().peerCertificate()

    def sessionCipher(self) -> QSslCipher:
        return self.ws.sslConfiguration().sessionCipher()

    def ignoreSslErrors(self, errors=None) -> None:
        if errors is None:
            self.ws.ignoreSslErrors()
        else:
            self.ws.ignoreSslErrors(errors)

    def localAddress(self) -> QHostAddress:
        return self.ws.localAddress()

    def peerPort(self) -> int:
        return self.ws.peerPort()

    def setProxy(self, proxy) -> None:
        self.ws.setProxy(proxy)

    def bind(self, *_args) -> bool:
        self._error = "a WebSocket connection can't use a bind address"
        return False

    def setLocalCertificate(self, cert) -> None:
        self._cert = cert

    def setPrivateKey(self, key) -> None:
        self._key = key

    def startClientEncryption(self) -> None:
        pass                                   # wss:// is encrypted from the start

    def blockSignals(self, on: bool) -> bool:
        self.ws.blockSignals(on)
        return super().blockSignals(on)

    def deleteLater(self) -> None:
        super().deleteLater()

    # --- inside -----------------------------------------------------------------------------

    def _on_connected(self) -> None:
        self.connected.emit()
        self.encrypted.emit()                  # the Session logs in after "encrypted" on SSL servers

    def _arrived(self, data: bytes) -> None:
        for line in data.replace(b"\r\n", b"\n").split(b"\n"):
            if line:
                self._in += line + b"\r\n"
        self.readyRead.emit()

    def _on_error(self, err) -> None:
        self._error = self.ws.errorString()
        self.errorOccurred.emit(err)
