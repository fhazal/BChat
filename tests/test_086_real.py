"""0.8.6 release proof over real sockets (no fakes inside BChat):

1. Certificate login: a TLS server that REQUIRES a client certificate and checks SASL EXTERNAL against the
   fingerprint it saw in the handshake (CertFP, the way a real network does it). 904 with the default
   "Disconnect, don't retry" and with "Stay connected without logging in".
2. DCC over IPv6 (::1): BChat's IRC link is IPv6, offers carry the IPv6 address form. GET and SEND, active and
   passive, plus resume both ways. Files are compared by sha256.
3. Files over 4 GB: a sparse (1 << 32) + 12345 byte file (no disk space). Resume from past the 4 GB line both
   ways, and full 4 GB transfers both ways (about 15 s each on loopback; the receive needs ~4.3 GB free
   and is skipped without it, the file is deleted afterwards).

Loopback only, throwaway settings folders (tmp_path), .bin files only. The other side of every transfer is a
real IRC client (qa_ircd.IrcTestClient) on the same local server plus a real socket in a thread."""
import ctypes
import datetime
import hashlib
import msvcrt
import os
import re
import shutil
import socket
import ssl
import struct
import threading
import time
from ctypes import wintypes
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from bchat import certs
from qa_ircd import LOCAL4, LOCAL6, IrcTestClient, QaIrcd
from test_live import make_win

MASK = 0xFFFFFFFF
BIG = (1 << 32) + 12345
PAST = (1 << 32) + 5000                     # a resume that starts past the 4 GB line
MARKERS = [(0, b"BCHAT-START"), (1 << 31, b"HALF-WAY"), ((1 << 32) - 5, b"ACROSS-4GB-LINE"),
           ((1 << 32) + 6000, b"PAST-4GB"), (BIG - 7, b"THE-END")]
HASH_CHUNK = 8 << 20

# ---- helpers: the real event loop, sparse files, hashes ---------------------------------------------------------

def run_until(cond, secs=10.0, every=None) -> bool:
    """Run Qt's real event loop (as the app does, no sleeps in between) until cond() or secs pass."""
    loop = QEventLoop()
    end = time.time() + secs

    def check():
        if every is not None:
            every()
        if cond() or time.time() > end:
            loop.quit()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(20)
    QTimer.singleShot(0, check)
    loop.exec()
    timer.stop()
    return bool(cond())


def settle(secs: float) -> None:
    run_until(lambda: False, secs)


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.DeviceIoControl.restype = wintypes.BOOL
_k32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.GetCompressedFileSizeW.restype = wintypes.DWORD
FSCTL_SET_SPARSE = 0x000900C4


def allocated(path: Path) -> int:
    """Bytes the file really takes on disk (a sparse file: only the parts written)."""
    high = wintypes.DWORD(0)
    low = _k32.GetCompressedFileSizeW(str(path), ctypes.byref(high))
    return (high.value << 32) + low


def make_sparse(path: Path, size: int, markers) -> Path:
    """A sparse file of size bytes: zeros (costing no disk space) with a few markers written in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    with open(path, "r+b") as f:
        n = wintypes.DWORD(0)
        if not _k32.DeviceIoControl(msvcrt.get_osfhandle(f.fileno()), FSCTL_SET_SPARSE, None, 0, None, 0,
                                    ctypes.byref(n), None):
            pytest.skip(f"this drive can't make sparse files (error {ctypes.get_last_error()})")
        f.seek(size - 1)
        f.write(b"\0")
        f.truncate(size)
        for off, data in markers:
            if off + len(data) <= size:
                f.seek(off)
                f.write(data)
    assert path.stat().st_size == size
    assert allocated(path) < 64 << 20, allocated(path)          # really sparse: no 4 GB on disk
    return path


def file_sha(path: Path, start: int = 0) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(start)
        while True:
            d = f.read(HASH_CHUNK)
            if not d:
                break
            h.update(d)
    return h.hexdigest()


_SHA_CACHE: dict = {}


def big_sha(size: int = BIG) -> str:
    """sha256 of the sparse test file (zeros + MARKERS), worked out once by streaming it (no file needed)."""
    if size not in _SHA_CACHE:
        h, pos = hashlib.sha256(), 0
        zeros = bytes(HASH_CHUNK)
        for off, data in sorted(m for m in MARKERS if m[0] + len(m[1]) <= size) + [(size, b"")]:
            while pos < off:
                n = min(HASH_CHUNK, off - pos)
                h.update(zeros[:n])
                pos += n
            h.update(data)
            pos += len(data)
        _SHA_CACHE[size] = h.hexdigest()
    return _SHA_CACHE[size]


def markers_in(path: Path) -> list:
    with open(path, "rb") as f:
        out = []
        for off, data in MARKERS:
            f.seek(off)
            out.append(f.read(len(data)))
    return out


# ---- the other side of a DCC: real sockets in threads ------------------------------------------------------------

class _Acks:
    """Reads 4-byte acks: they are the received total cut to 32 bits. Counts the wraps past 4 GB."""

    def __init__(self, start: int):
        self.low = start & MASK
        self.total = start              # the unwrapped value
        self.wraps = 0
        self.count = 0
        self.backwards = 0
        self._buf = b""

    def feed(self, data: bytes) -> None:
        data = self._buf + data
        whole = len(data) - len(data) % 4
        self._buf = data[whole:]
        for i in range(0, whole, 4):
            low = struct.unpack(">I", data[i:i + 4])[0]
            step = (low - self.low) & MASK
            if step > 1 << 31:          # went down without a wrap
                self.backwards += 1
                continue
            if low < self.low:
                self.wraps += 1
            self.total += step
            self.low = low
            self.count += 1


class PeerSender:
    """Their side of a file BChat receives: sends src[start:] over one connection and reads BChat's acks."""

    def __init__(self, src: Path, host: str, start: int = 0):
        self.src, self.host, self.start = src, host, start
        self.size = src.stat().st_size
        self.sent = 0
        self.acks = _Acks(start)
        self.error = ""
        self.ls = None
        self.port = 0
        self.thread = None

    def listen(self) -> "PeerSender":
        fam = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        self.ls = socket.socket(fam, socket.SOCK_STREAM)
        self.ls.bind((self.host, 0))
        self.ls.listen(1)
        self.ls.settimeout(30)
        self.port = self.ls.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, name="peer-sender", daemon=True)
        self.thread.start()
        return self

    def connect(self, ip: str, port: int) -> "PeerSender":
        self.thread = threading.Thread(target=lambda: self._talk(socket.create_connection((ip, port), timeout=30)),
                                       name="peer-sender", daemon=True)
        self.thread.start()
        return self

    def _accept(self):
        try:
            c, self.peer_addr = self.ls.accept()
        except OSError as e:
            self.error = f"accept: {e}"
            return
        finally:
            self.ls.close()
        self._talk(c)

    def _talk(self, c: socket.socket):
        c.settimeout(60)
        reader = threading.Thread(target=self._read_acks, args=(c,), name="peer-acks", daemon=True)
        reader.start()
        try:
            with open(self.src, "rb") as f:
                f.seek(self.start)
                while True:
                    d = f.read(1 << 20)
                    if not d:
                        break
                    c.sendall(d)
                    self.sent += len(d)
        except OSError as e:
            self.error = f"send: {e}"
        reader.join(120)
        c.close()

    def _read_acks(self, c):
        try:
            while True:
                d = c.recv(65536)
                if not d:
                    return
                self.acks.feed(d)
        except OSError as e:
            if self.acks.total < self.size:
                self.error = f"acks: {e}"

    def join(self, secs=30):
        # keep Qt's event loop running while waiting: BChat's last bytes (the final ack, the close) only
        # leave through it, so a plain thread.join() would stall them until the peer's socket timed out
        if self.thread is not None:
            run_until(lambda: not self.thread.is_alive(), secs)
            self.thread.join(1)


class PeerReceiver:
    """Their side of a file BChat sends: reads everything from start on, hashes it, acks every read."""

    def __init__(self, size: int, start: int = 0, keep: bool = False):
        self.size, self.start = size, start
        self.total = start
        self.sha = hashlib.sha256()
        self.keep = bytearray() if keep else None
        self.marks = {off: bytearray(len(d)) for off, d in MARKERS}
        self.error = ""
        self.closed_by_them = False
        self.ls = None
        self.port = 0
        self.thread = None

    def listen(self, host: str) -> "PeerReceiver":
        fam = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.ls = socket.socket(fam, socket.SOCK_STREAM)
        self.ls.bind((host, 0))
        self.ls.listen(1)
        self.ls.settimeout(30)
        self.port = self.ls.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, name="peer-receiver", daemon=True)
        self.thread.start()
        return self

    def connect(self, ip: str, port: int) -> "PeerReceiver":
        def go():
            try:
                c = socket.create_connection((ip, port), timeout=30)
            except OSError as e:
                self.error = f"connect: {e}"
                return
            self._talk(c)
        self.thread = threading.Thread(target=go, name="peer-receiver", daemon=True)
        self.thread.start()
        return self

    def _accept(self):
        try:
            c, _ = self.ls.accept()
        except OSError as e:
            self.error = f"accept: {e}"
            return
        finally:
            self.ls.close()
        self._talk(c)

    def _note_markers(self, pos: int, d: bytes) -> None:
        end = pos + len(d)
        for off, buf in self.marks.items():
            a, b = max(pos, off), min(end, off + len(buf))
            if a < b:
                buf[a - off:b - off] = d[a - pos:b - pos]

    def _talk(self, c: socket.socket):
        c.settimeout(60)
        try:
            while self.total < self.size:
                d = c.recv(1 << 20)
                if not d:
                    break
                self.sha.update(d)
                self._note_markers(self.total, d)
                if self.keep is not None:
                    self.keep.extend(d)
                self.total += len(d)
                c.sendall(struct.pack(">I", self.total & MASK))
            self.closed_by_them = c.recv(16) == b""        # BChat closes once the acks cover the file
        except OSError as e:
            self.error = f"recv: {e}"
        c.close()

    def join(self, secs=30):
        # keep Qt's event loop running while waiting: BChat's last bytes (the final ack, the close) only
        # leave through it, so a plain thread.join() would stall them until the peer's socket timed out
        if self.thread is not None:
            run_until(lambda: not self.thread.is_alive(), secs)
            self.thread.join(1)


# ---- one BChat + one other person on a local server --------------------------------------------------------------

def _texts(s):
    return [l.text for l in s.server_buffer.lines]


def _everything(s):
    return [l.text for b in s.all_buffers() for l in b.lines]


def link(app, tmp_path, host):
    """A local QaIrcd on host, BChat (throwaway settings folder) connected to it, and Belon, a real IRC client."""
    srv = QaIrcd(host=host, cert_dir=tmp_path / "srv-cert")
    settings = tmp_path / "settings"
    settings.mkdir()
    win, net = make_win(settings, srv.port)
    net.servers[0].host = host
    win.cfg.local_lookup = "normal"          # Network > Local: this PC's address (no lookups anywhere else)
    win.cfg.dcc_dir = str(tmp_path / "downloads")
    s = win.connect_network(net)
    assert run_until(lambda: s.state == "connected", 15), _texts(s)
    peer = IrcTestClient(host, srv.port).register("Belon")
    assert run_until(lambda: s.external_ip, 10), _texts(s)
    return srv, win, s, peer


@pytest.fixture
def v6(app, tmp_path):
    srv, win, s, peer = link(app, tmp_path, LOCAL6)
    assert s.sock.localAddress().toString() == "::1" and s.external_ip == "::1"   # the IRC link itself is IPv6
    yield srv, win, s, peer
    peer.close()
    win.close()
    srv.stop()


@pytest.fixture
def v4(app, tmp_path):
    srv, win, s, peer = link(app, tmp_path, LOCAL4)
    yield srv, win, s, peer
    peer.close()
    win.close()
    srv.stop()


OFFER = re.compile(r'PRIVMSG Belon :\x01DCC (SEND|ACCEPT|RESUME) (\S+) (\S+) (\S+) ?(\S*) ?(\S*)\x01')


def their_dcc(peer, since, verb="SEND", timeout=10):
    """The next DCC line BChat sent to Belon: (name, field2, field3, field4, field5)."""
    line = peer.expect(rf"PRIVMSG Belon :\x01DCC {verb} ", since=since, timeout=0.01)
    m = OFFER.search(line)
    return m.groups()[1:]


def wait_dcc(peer, since, verb="SEND", secs=10):
    got = []

    def look():
        try:
            got.append(their_dcc(peer, since, verb))
            return True
        except TimeoutError:
            return False
    assert run_until(look, secs), peer.lines[-10:]
    return got[0]


def offer_to_bchat(peer, text):
    peer.send(f"PRIVMSG Badaboom :\x01{text}\x01")


def new_recv(win, name, secs=10):
    assert run_until(lambda: any(t.kind == "recv" and t.name == name for t in win.dcc.items), secs), \
        [(t.kind, t.name) for t in win.dcc.items]
    return [t for t in win.dcc.items if t.kind == "recv" and t.name == name][-1]


# =================================================================================================================
# 1. certificate login
# =================================================================================================================

def _client_cert(folder: Path, kind: str):
    """A throwaway self-signed client certificate. 'rsa': one .pem (PKCS#8 key), 'rsa-traditional': one .pem with
    an old 'RSA PRIVATE KEY', 'ec': client.crt with client.key next to it. Returns (file for BChat, the certificate
    alone for the server to trust, its sha256 fingerprint)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from cryptography.x509.oid import NameOID
    folder.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1()) if kind == "ec" else rsa.generate_private_key(65537, 2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Badaboom")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    crt = cert.public_bytes(serialization.Encoding.PEM)
    fmt = serialization.PrivateFormat.TraditionalOpenSSL if kind == "rsa-traditional" else serialization.PrivateFormat.PKCS8
    k = key.private_bytes(serialization.Encoding.PEM, fmt, serialization.NoEncryption())
    trust = folder / "trusted.pem"
    trust.write_bytes(crt)
    if kind == "ec":
        (folder / "client.crt").write_bytes(crt)
        (folder / "client.key").write_bytes(k)
        mine = folder / "client.crt"
    else:
        mine = folder / "client.pem"
        mine.write_bytes(crt + k)
    return str(mine), str(trust), hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


class CertIrcd(QaIrcd):
    """QaIrcd over TLS that REQUIRES a client certificate and logs SASL EXTERNAL in only when the fingerprint seen
    in the handshake is one it knows (fingerprint -> account), like NickServ CertFP."""

    def __init__(self, client_ca: str, known: dict, **kw):
        self.client_ca, self.known, self.seen = client_ca, dict(known), []
        super().__init__(tls=True, **kw)

    def start(self):
        super().start()
        self._ctx.verify_mode = ssl.CERT_REQUIRED
        self._ctx.load_verify_locations(self.client_ca)
        return self

    def _cmd_AUTHENTICATE(self, c, m):
        if c.sasl_mech == "EXTERNAL":
            der = c.sock.getpeercert(binary_form=True) or b""
            fp = hashlib.sha256(der).hexdigest() if der else ""
            self.seen.append(fp)
            self.external_account = self.known.get(fp, "")
        return super()._cmd_AUTHENTICATE(c, m)

    def links(self) -> list:
        """Every connection that reached the server (TLS handshakes that failed too)."""
        with self._lock:
            return [e for e in self.events if e.kind == "connect" or (e.kind == "close" and "TLS" in e.line)]


def _cert_session(app, tmp_path, kind, known, **net_kw):
    mine, trust, fp = _client_cert(tmp_path / "mycert", kind)
    srv = CertIrcd(trust, {fp: "badacct"} if known else {}, cert_dir=tmp_path / "srv-cert")
    settings = tmp_path / "settings"
    settings.mkdir()
    win, net = make_win(settings, srv.port, ssl=True, allow_invalid_cert=True, login="cert", cert_file=mine, **net_kw)
    win.cfg.reconnect_delay = 1          # a reconnect, if there were one, would come within a second
    s = win.connect_network(net)
    return srv, win, s, fp, mine


@pytest.mark.parametrize("kind", ["rsa", "rsa-traditional", "ec"])
def test_cert_login_sends_the_certificate_in_the_handshake_and_logs_in(app, tmp_path, kind):
    srv, win, s, fp, mine = _cert_session(app, tmp_path, kind, known=True)
    try:
        assert run_until(lambda: s.state == "connected" and any("SASL login successful" in t for t in _texts(s)), 15), \
            (_texts(s), [e.line for e in srv.events[-15:]])
        assert srv.seen == [fp]                                   # the server saw exactly this certificate
        assert certs.describe(mine)[2].replace(":", "") == fp     # and it is the fingerprint BChat shows the user
        assert srv.client("Badaboom").account == "badacct"
        got = srv.received("Badaboom")
        assert "AUTHENTICATE EXTERNAL" in got and "AUTHENTICATE +" in got
        assert not any(x.startswith("AUTHENTICATE") and x not in ("AUTHENTICATE EXTERNAL", "AUTHENTICATE +") for x in got)
        assert any(x.startswith("CAP REQ") and "sasl" in x for x in got)
        assert got.index("CAP END") > got.index("AUTHENTICATE +")  # registration finishes after the login
        assert len(srv.links()) == 1
    finally:
        win.close()
        srv.stop()


def test_cert_login_refused_904_disconnects_and_never_reconnects(app, tmp_path):
    srv, win, s, fp, _ = _cert_session(app, tmp_path, "rsa", known=False)       # NickServ doesn't know it: 904
    try:
        assert run_until(lambda: any("will not retry" in t for t in _texts(s)), 15), _texts(s)
        assert any("Certificate login failed" in t for t in _texts(s))
        assert srv.seen == [fp]                                   # the certificate was sent, the server refused it
        assert s.state == "disconnected" and not s.want_connected and not s._reconnect.isActive()
        assert run_until(lambda: any(e.kind == "close" for e in srv.events), 5)  # the link is really closed
        settle(4)                                                 # 4x the reconnect delay: nothing may come back
        assert len(srv.links()) == 1, [e.line for e in srv.links()]
        assert s.state == "disconnected" and not s._reconnect.isActive()
        assert not any("Reconnect try" in t for t in _texts(s))
        got = srv.received()
        assert "CAP END" not in got and not any(" 001 " in e.line for e in srv.events if e.kind == "out")
    finally:
        win.close()
        srv.stop()


def test_cert_login_refused_904_can_stay_connected(app, tmp_path):
    srv, win, s, fp, _ = _cert_session(app, tmp_path, "ec", known=False, login_fail="stay")
    try:
        assert run_until(lambda: s.state == "connected", 15), _texts(s)
        assert any("Certificate login failed" in t for t in _texts(s))
        assert srv.seen == [fp]
        assert srv.client("Badaboom").account == ""               # connected, not logged in
        assert "CAP END" in srv.received("Badaboom")
        settle(3)
        assert s.state == "connected" and s.want_connected and len(srv.links()) == 1
        assert not any("will not retry" in t for t in _texts(s))
    finally:
        win.close()
        srv.stop()


# =================================================================================================================
# 2. DCC over IPv6
# =================================================================================================================

def _payload(tmp_path, name, size=3 * 1024 * 1024 + 777):
    p = tmp_path / "peer" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(os.urandom(size))
    return p


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_v6_get_active(app, tmp_path, v6):
    srv, win, s, peer = v6
    src = _payload(tmp_path, "v6get.bin")
    tx = PeerSender(src, LOCAL6).listen()
    offer_to_bchat(peer, f"DCC SEND v6get.bin ::1 {tx.port} {tx.size}")      # the IPv6 form, as other clients send it
    t = new_recv(win, "v6get.bin")
    assert t.ip == "::1" and t.port == tx.port and t.size == tx.size and not t.passive
    win.dcc.accept(t)
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos)
    tx.join()
    assert tx.peer_addr[0] == "::1" and not tx.error
    assert file_sha(Path(t.path)) == file_sha(src)
    assert tx.acks.total == tx.size and tx.acks.backwards == 0


def test_v6_get_passive(app, tmp_path, v6):
    srv, win, s, peer = v6
    src = _payload(tmp_path, "v6pget.bin")
    since = peer.mark()
    offer_to_bchat(peer, f"DCC SEND v6pget.bin ::1 0 {src.stat().st_size} 77")
    t = new_recv(win, "v6pget.bin")
    assert t.passive and t.token == "77"
    win.dcc.accept(t)
    name, ip, port, size, token = wait_dcc(peer, since)            # BChat listens and says where, in IPv6 form
    assert (name, ip, size, token) == ("v6pget.bin", "::1", str(src.stat().st_size), "77"), (name, ip, size, token)
    tx = PeerSender(src, LOCAL6).connect("::1", int(port))
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos)
    tx.join()
    assert not tx.error and file_sha(Path(t.path)) == file_sha(src)


def test_v6_send_active(app, tmp_path, v6):
    srv, win, s, peer = v6
    src = _payload(tmp_path, "v6send.bin")
    since = peer.mark()
    t = win.dcc.send_file(s, "Belon", str(src))
    name, ip, port, size, _ = wait_dcc(peer, since)
    assert (name, ip, size) == ("v6send.bin", "::1", str(src.stat().st_size))
    rx = PeerReceiver(int(size), keep=True).connect(ip, int(port))
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos, t.acked)
    rx.join()
    assert not rx.error and rx.closed_by_them
    assert _sha(bytes(rx.keep)) == file_sha(src) and t.acked == t.size


def test_v6_send_passive(app, tmp_path, v6):
    srv, win, s, peer = v6
    src = _payload(tmp_path, "v6psend.bin")
    since = peer.mark()
    t = win.dcc.send_file(s, "Belon", str(src), passive=True)
    name, ip, port, size, token = wait_dcc(peer, since)
    assert (name, ip, port, size) == ("v6psend.bin", "::1", "0", str(src.stat().st_size)) and token == t.token
    rx = PeerReceiver(int(size), keep=True).listen(LOCAL6)
    offer_to_bchat(peer, f"DCC SEND v6psend.bin ::1 {rx.port} {size} {token}")   # they listen; BChat connects
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos, t.acked)
    rx.join()
    assert t.ip == "::1" and not rx.error
    assert _sha(bytes(rx.keep)) == file_sha(src)


def test_v6_resume_get(app, tmp_path, v6):
    srv, win, s, peer = v6
    src = _payload(tmp_path, "v6rget.bin")
    data = src.read_bytes()
    part = Path(win.cfg.dcc_dir) / "v6rget.bin"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(data[:1_000_000])
    tx = PeerSender(src, LOCAL6).listen()
    since = peer.mark()
    offer_to_bchat(peer, f"DCC SEND v6rget.bin ::1 {tx.port} {len(data)}")
    t = new_recv(win, "v6rget.bin")
    assert win.dcc.can_resume(t)
    win.dcc.accept(t, how="resume")
    name, port, pos, _, _ = wait_dcc(peer, since, "RESUME")
    assert (name, port, pos) == ("v6rget.bin", str(tx.port), "1000000")
    tx.start = int(pos)
    tx.acks = _Acks(tx.start)
    offer_to_bchat(peer, f"DCC ACCEPT v6rget.bin {port} {pos}")
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos)
    tx.join()
    assert not tx.error and tx.sent == len(data) - 1_000_000      # only the rest went over the wire
    assert t.path == str(part) and file_sha(part) == _sha(data)


def test_v6_resume_send_passive(app, tmp_path, v6):
    srv, win, s, peer = v6
    src = _payload(tmp_path, "v6rsend.bin")
    data = src.read_bytes()
    since = peer.mark()
    t = win.dcc.send_file(s, "Belon", str(src), passive=True)
    _, _, _, size, token = wait_dcc(peer, since)
    since = peer.mark()
    offer_to_bchat(peer, f"DCC RESUME v6rsend.bin 0 2000000 {token}")
    assert wait_dcc(peer, since, "ACCEPT")[:4] == ("v6rsend.bin", "0", "2000000", token)
    rx = PeerReceiver(len(data), start=2_000_000, keep=True).listen(LOCAL6)
    offer_to_bchat(peer, f"DCC SEND v6rsend.bin ::1 {rx.port} {size} {token}")
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos, t.acked)
    rx.join()
    assert not rx.error and bytes(rx.keep) == data[2_000_000:]
    assert _sha(data[:2_000_000] + bytes(rx.keep)) == _sha(data)


# =================================================================================================================
# 3. files over 4 GB (sparse source files: no disk space)
# =================================================================================================================

def _need_space(folder: Path, n: int):
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if free < n + (2 << 30):
        pytest.skip(f"needs {n + (2 << 30)} bytes free in {folder}, has {free}")


def test_sparse_test_file_is_what_the_tests_think(tmp_path):
    _need_space(tmp_path, 64 << 20)
    src = make_sparse(tmp_path / "big.bin", BIG, MARKERS)
    assert markers_in(src) == [d for _, d in MARKERS]


def test_resume_get_past_4gb(app, tmp_path, v4):
    """They offer a 4 GB+ file, we have the first (1 << 32) + 5000 bytes: only the rest comes, acks wrap right."""
    srv, win, s, peer = v4
    _need_space(tmp_path, 64 << 20)
    src = make_sparse(tmp_path / "peer" / "big.bin", BIG, MARKERS)
    part = make_sparse(Path(win.cfg.dcc_dir) / "big.bin", PAST, MARKERS)
    tx = PeerSender(src, LOCAL4).listen()
    since = peer.mark()
    offer_to_bchat(peer, f"DCC SEND big.bin 2130706433 {tx.port} {BIG}")
    t = new_recv(win, "big.bin")
    assert t.size == BIG and win.dcc.can_resume(t)
    win.dcc.accept(t, how="resume")
    name, port, pos, _, _ = wait_dcc(peer, since, "RESUME")
    assert (name, port, pos) == ("big.bin", str(tx.port), str(PAST))       # the full offset, not cut to 32 bits
    tx.start = PAST
    tx.acks = _Acks(PAST)
    offer_to_bchat(peer, f"DCC ACCEPT big.bin {port} {pos}")
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos)
    tx.join()
    assert not tx.error and tx.sent == BIG - PAST
    assert tx.acks.total == BIG and tx.acks.low == BIG & MASK and tx.acks.backwards == 0
    assert t.pos == BIG and t.percent() == 100
    assert part.stat().st_size == BIG and allocated(part) < 64 << 20     # the first 4 GB were left alone
    assert markers_in(part) == [d for _, d in MARKERS]
    assert file_sha(part) == big_sha()
    assert any(f'"big.bin" complete, {BIG} bytes' in x for x in _everything(s))


def test_resume_send_past_4gb(app, tmp_path, v4):
    """We offer a 4 GB+ file, they ask to resume from (1 << 32) + 5000: only the rest goes, their acks wrap."""
    srv, win, s, peer = v4
    _need_space(tmp_path, 64 << 20)
    src = make_sparse(tmp_path / "big.bin", BIG, MARKERS)
    since = peer.mark()
    t = win.dcc.send_file(s, "Belon", str(src))
    name, ip, port, size, _ = wait_dcc(peer, since)
    assert (name, size) == ("big.bin", str(BIG)) and t.size == BIG      # the offer carries the whole size
    since = peer.mark()
    offer_to_bchat(peer, f"DCC RESUME big.bin {port} {PAST}")
    assert wait_dcc(peer, since, "ACCEPT")[:3] == ("big.bin", port, str(PAST))
    assert t.pos == PAST and t.acked == PAST
    rx = PeerReceiver(BIG, start=PAST, keep=True).connect("127.0.0.1", int(port))
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos, t.acked)
    rx.join()
    assert not rx.error and rx.total == BIG
    with open(src, "rb") as f:
        f.seek(PAST)
        assert bytes(rx.keep) == f.read()
    assert t.acked == BIG and t.percent() == 100
    assert bytes(rx.marks[(1 << 32) + 6000]) == b"PAST-4GB" and bytes(rx.marks[BIG - 7]) == b"THE-END"


class _Progress:
    """Samples a transfer while it runs: percent and position must only go up; the position must pass 4 GB."""

    def __init__(self, t):
        self.t, self.samples = t, []

    def __call__(self):
        self.samples.append((self.t.pos, self.t.percent(), getattr(self.t, "acked", 0)))

    def check(self, size):
        pos = [p for p, _, _ in self.samples]
        pct = [c for _, c, _ in self.samples]
        acked = [a for _, _, a in self.samples]
        assert pos == sorted(pos) and pct == sorted(pct) and acked == sorted(acked)
        assert all(0 <= c <= 100 for c in pct)
        assert any(p > 1 << 32 for p in pos) and any(0 < c < 100 for c in pct)
        assert all(p <= size for p in pos)


def test_full_send_over_4gb(app, tmp_path, v4):
    srv, win, s, peer = v4
    _need_space(tmp_path, 64 << 20)
    src = make_sparse(tmp_path / "big.bin", BIG, MARKERS)
    w = win.open_transfers()
    since = peer.mark()
    t = win.dcc.send_file(s, "Belon", str(src))
    _, ip, port, size, _ = wait_dcc(peer, since)
    assert int(size) == BIG
    rx = PeerReceiver(BIG).connect("127.0.0.1", int(port))
    prog = _Progress(t)
    began = time.time()
    assert run_until(lambda: t.state != "active" and t.state != "queued" and t.state != "connecting", 1800, prog), \
        (t.state, t.pos, t.acked)
    took = time.time() - began
    print(f"\n4 GB send: {BIG} bytes in {took:.1f} s ({BIG / took / 1e6:.0f} MB/s)")
    rx.join()
    assert t.state == "done", (t.state, t.error, t.pos, t.acked)
    assert not rx.error and rx.total == BIG and rx.closed_by_them
    assert rx.sha.hexdigest() == big_sha()
    assert [bytes(rx.marks[o]) for o, _ in MARKERS] == [d for _, d in MARKERS]
    assert t.pos == BIG and t.acked == BIG and t.percent() == 100
    prog.check(BIG)
    assert any(f'"big.bin" complete, {BIG} bytes' in x for x in _everything(s))
    w.fill()
    row = w.view.topLevelItem(0)
    assert [row.text(i) for i in range(5)] == ["Complete", "big.bin", "4.0 GB", "4.0 GB", "100"]


def test_full_get_over_4gb(app, tmp_path, v4):
    srv, win, s, peer = v4
    _need_space(Path(win.cfg.dcc_dir), BIG)          # the received file is real data on disk
    src = make_sparse(tmp_path / "peer" / "big.bin", BIG, MARKERS)
    got = Path(win.cfg.dcc_dir) / "big.bin"
    try:
        w = win.open_transfers()
        tx = PeerSender(src, LOCAL4).listen()
        offer_to_bchat(peer, f"DCC SEND big.bin 2130706433 {tx.port} {BIG}")
        t = new_recv(win, "big.bin")
        assert t.size == BIG
        win.dcc.accept(t)
        prog = _Progress(t)
        began = time.time()
        assert run_until(lambda: t.state not in ("queued", "connecting", "active"), 1800, prog), (t.state, t.pos)
        took = time.time() - began
        print(f"\n4 GB get: {BIG} bytes in {took:.1f} s ({BIG / took / 1e6:.0f} MB/s)")
        tx.join(120)
        assert t.state == "done", (t.state, t.error, t.pos)
        assert not tx.error and tx.sent == BIG
        assert tx.acks.total == BIG and tx.acks.low == BIG & MASK and tx.acks.wraps == 1 and tx.acks.backwards == 0
        assert t.pos == BIG and t.percent() == 100
        prog.check(BIG)
        assert got.stat().st_size == BIG
        assert markers_in(got) == [d for _, d in MARKERS]
        assert file_sha(got) == big_sha()
        w.fill()
        row = w.view.topLevelItem(0)
        assert [row.text(i) for i in range(5)] == ["Complete", "big.bin", "4.0 GB", "4.0 GB", "100"]
    finally:
        try:
            got.unlink()                          # don't leave 4 GB in pytest's kept temp folders
        except OSError:
            pass


def test_final_ack_goes_out_before_the_file_is_moved(app, tmp_path, v4):
    # 0.8.8 QA: the last ack waited in Qt's buffer while finished() moved the file (to another drive it can
    # take long), so the sender could time out on a transfer that had in fact arrived whole
    srv, win, s, peer = v4
    src = _payload(tmp_path, "ack.bin")
    tx = PeerSender(src, LOCAL4).listen()
    unsent = []
    real = win.dcc.finished

    def finished(t):
        unsent.append(t.sock.bytesToWrite() if t.sock is not None else 0)
        real(t)
    win.dcc.finished = finished
    offer_to_bchat(peer, f"DCC SEND ack.bin 2130706433 {tx.port} {tx.size}")
    t = new_recv(win, "ack.bin")
    win.dcc.accept(t)
    assert run_until(lambda: t.state == "done", 30), (t.state, t.error, t.pos)
    tx.join()
    assert unsent == [0]
    assert not tx.error and tx.sent == tx.size
