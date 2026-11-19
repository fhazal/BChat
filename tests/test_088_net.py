"""0.8.8 item 6: Socks4 / Socks4a proxies, the ident server and UPnP, all against local fakes only.

Nothing here talks to a real proxy, a real router or the multicast group: the SOCKS4 proxy, the IRC server, the
SSDP responder and the router's SOAP service are all small servers on 127.0.0.1."""
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from fake_ircd import FakeIrcd
from test_live import make_win, prefs, wait

from bchat import identd, upnp
from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow
from bchat.session import ERROR, INFO


def texts(s):
    return [l.text for l in s.server_buffer.lines]


def free_port() -> int:
    with socket.socket() as k:
        k.bind(("127.0.0.1", 0))
        return k.getsockname()[1]


# --- a fake SOCKS4 / 4a proxy ------------------------------------------------------------------------------

class FakeSocks4:
    """Reads one Socks4 request, records it, answers with `code`; on 0x5A it relays to 127.0.0.1:<asked port>."""

    def __init__(self, code=0x5A):
        self.code = code
        self.seen = []                      # (ip, port, user, name)
        self.lst = socket.socket()
        self.lst.bind(("127.0.0.1", 0))
        self.lst.listen(4)
        self.port = self.lst.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    @staticmethod
    def _until_nul(c) -> bytes:
        out = b""
        while not out.endswith(b"\0"):
            ch = c.recv(1)
            if not ch:
                break
            out += ch
        return out[:-1]

    def _serve(self):
        try:
            c, _ = self.lst.accept()
        except OSError:
            return
        head = b""
        while len(head) < 8:
            head += c.recv(8 - len(head))
        ver, cmd, port = struct.unpack(">BBH", head[:4])
        ip = socket.inet_ntoa(head[4:8])
        user = self._until_nul(c).decode()
        name = self._until_nul(c).decode() if ip.startswith("0.0.0.") and ip != "0.0.0.0" else ""
        self.seen.append((ver, cmd, ip, port, user, name))
        c.sendall(bytes([0, self.code, 0, 0, 0, 0, 0, 0]))
        if self.code != 0x5A:
            time.sleep(0.5)
            c.close()
            return
        out = socket.create_connection(("127.0.0.1", port))      # 4a names: the fake looks them all up as 127.0.0.1
        threading.Thread(target=self._relay, args=(c, out), daemon=True).start()
        self._relay(out, c)

    @staticmethod
    def _relay(a, b):
        try:
            while True:
                data = a.recv(4096)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        for k in (a, b):
            try:
                k.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def stop(self):
        self.lst.close()


def socks_win(tmp_path, host, port):
    """make_win with a server name instead of 127.0.0.1."""
    net = NetworkConfig("SkinIRC", [Server(host, port, False)], autojoin="#skinhead")
    win = MainWindow(Config(nick="Badaboom", nick2="b2", networks=[net]), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    return win, net


def use_proxy(win, proxy, index, user=""):
    prefs(win, lambda d: (d.proxy_type.setCurrentIndex(index), d.proxy_host.setText("127.0.0.1"),
                          d.proxy_port.setValue(proxy.port), d.proxy_user.setText(user)))


def test_socks4_reaches_the_server_with_the_user_id(app, tmp_path):
    target, proxy = FakeIrcd(), FakeSocks4()
    win, net = make_win(tmp_path, target.port)
    use_proxy(win, proxy, 3, "beeuser")
    assert win.cfg.proxy_type == "socks4"
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), texts(s)
    assert proxy.seen == [(4, 1, "127.0.0.1", target.port, "beeuser", "")]
    assert any("Connected to the proxy" in t for t in texts(s)) and any(t == "The proxy reached 127.0.0.1." for t in texts(s))
    assert "NICK Badaboom" in target.received
    s.disconnect_from_network()
    win.close(); target.stop(); proxy.stop()


def test_socks4_looks_the_name_up_itself(app, tmp_path):
    target, proxy = FakeIrcd(), FakeSocks4()
    win, net = socks_win(tmp_path, "localhost", target.port)
    use_proxy(win, proxy, 3)
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), texts(s)
    assert proxy.seen == [(4, 1, "127.0.0.1", target.port, "", "")]     # plain Socks4: an IPv4 address, no name
    s.disconnect_from_network()
    win.close(); target.stop(); proxy.stop()


def test_socks4a_lets_the_proxy_look_the_name_up(app, tmp_path):
    target, proxy = FakeIrcd(), FakeSocks4()
    win, net = socks_win(tmp_path, "irc.example.invalid", target.port)
    use_proxy(win, proxy, 4, "u")
    assert win.cfg.proxy_type == "socks4a"
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), texts(s)
    assert proxy.seen == [(4, 1, "0.0.0.1", target.port, "u", "irc.example.invalid")]
    s.disconnect_from_network()
    win.close(); target.stop(); proxy.stop()


def test_socks4_without_4a_names_an_unknown_host(app, tmp_path):
    proxy = FakeSocks4()
    win, net = socks_win(tmp_path, "irc.example.invalid", 6667)
    use_proxy(win, proxy, 3)
    s = win.connect_network(net)
    assert wait(app, lambda: any("Socks4a lets the proxy look names up" in t for t in texts(s)), 8000), texts(s)
    assert proxy.seen == []
    s.disconnect_from_network()
    win.close(); proxy.stop()


@pytest.mark.parametrize("code, why", [
    (0x5B, "the proxy refused or couldn't make the connection"),
    (0x5C, "the proxy couldn't check who you are (it asks this PC's ident server, which didn't answer)"),
    (0x5D, "the proxy's ident check didn't match the user ID BChat sent"),
])
def test_socks4_refusals_say_why(app, tmp_path, code, why):
    proxy = FakeSocks4(code)
    win, net = make_win(tmp_path, 6667)
    use_proxy(win, proxy, 3)
    s = win.connect_network(net)
    want = f"Socks4 proxy 127.0.0.1: {why} (code {code:#04x})."
    assert wait(app, lambda: any(l.kind == ERROR and l.text == want for l in s.server_buffer.lines), 8000), texts(s)
    assert s.state != "connected"
    assert not any("closed the connection without an answer" in t for t in texts(s))     # said once, not twice
    s.disconnect_from_network()
    win.close(); proxy.stop()


def test_socks4_then_ssl_checks_the_servers_certificate(app, tmp_path):
    from test_live import _cert
    crt, key = _cert(tmp_path)
    target, proxy = FakeIrcd(crt, key), FakeSocks4()
    win, net = make_win(tmp_path, target.port, ssl=True, allow_invalid_cert=True)
    use_proxy(win, proxy, 3)
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 10000), texts(s)
    assert proxy.seen and proxy.seen[0][3] == target.port
    assert any(l.left == "SSL" and l.text.startswith("Protocol: TLS") for l in s.server_buffer.lines)
    s.disconnect_from_network()
    win.close(); target.stop(); proxy.stop()


def test_old_proxy_indexes_unchanged(app, tmp_path):
    from bchat.preferences import PROXY_KINDS
    assert PROXY_KINDS[:3] == ("none", "socks5", "http") and PROXY_KINDS[3:] == ("socks4", "socks4a")


# --- ident server ------------------------------------------------------------------------------------------

def ask_ident(port: int, query: bytes, box: list):
    def go():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=3) as k:
                k.sendall(query)
                got = b""
                while not got.endswith(b"\r\n"):
                    part = k.recv(200)
                    if not part:
                        break
                    got += part
                box.append(got.decode())
        except OSError as e:
            box.append(f"failed {e}")
    threading.Thread(target=go, daemon=True).start()


class SilentServer:
    """An IRC server that accepts and says nothing until told to: the connection stays in its 'connecting' part."""

    def __init__(self):
        self.lst = socket.socket()
        self.lst.bind(("127.0.0.1", 0))
        self.lst.listen(1)
        self.port = self.lst.getsockname()[1]
        self.conn = None
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        try:
            self.conn, _ = self.lst.accept()
            while self.conn.recv(4096):
                pass
        except OSError:
            pass

    def send(self, line: str):
        self.conn.sendall(line.encode() + b"\r\n")

    def stop(self):
        for k in (self.conn, self.lst):
            if k is not None:
                k.close()


@pytest.fixture
def ident_port(monkeypatch):
    port = free_port()
    monkeypatch.setattr(identd, "PORT", port)
    yield port
    assert identd._shared is None or not identd._shared.listening


def test_ident_answers_only_for_its_own_connection(app, tmp_path, ident_port):
    srv = SilentServer()
    win, net = make_win(tmp_path, srv.port)
    prefs(win, lambda d: (d.identd_on.setChecked(True), d.identd_user.setText("bee user")))
    assert win.cfg.identd_on and win.cfg.identd_user == "bee user"
    s = win.connect_network(net)
    assert wait(app, lambda: srv.conn is not None and s.sock.state() == s.sock.SocketState.ConnectedState, 5000)
    assert identd._shared.listening
    ours, theirs = s.sock.localPort(), s.sock.peerPort()
    box = []
    ask_ident(ident_port, f"{ours} , {theirs}\r\n".encode(), box)
    assert wait(app, lambda: box, 4000)
    assert box[0] == f"{ours}, {theirs} : USERID : UNIX : beeuser\r\n"      # no spaces in a user ID
    box.clear()
    ask_ident(ident_port, f"{ours}, {theirs + 1}\r\n".encode(), box)
    assert wait(app, lambda: box, 4000) and box[0] == f"{ours}, {theirs + 1} : ERROR : NO-USER\r\n"
    box.clear()
    ask_ident(ident_port, b"hello\r\n", box)
    assert wait(app, lambda: box, 4000) and box[0] == "0, 0 : ERROR : INVALID-PORT\r\n"
    srv.send(":fake 001 Badaboom :Welcome")                                    # welcomed: the port closes
    assert wait(app, lambda: not identd._shared.listening, 4000)
    s.disconnect_from_network()
    win.close(); srv.stop()


def test_ident_user_defaults_to_the_username(app, tmp_path, ident_port):
    srv = SilentServer()
    win, net = make_win(tmp_path, srv.port)
    prefs(win, lambda d: d.identd_on.setChecked(True))
    s = win.connect_network(net)
    assert wait(app, lambda: s.sock.state() == s.sock.SocketState.ConnectedState, 5000)
    assert identd._shared.holders[s] == identd.clean_user(win.cfg.username or "bchat")
    s.disconnect_from_network()
    assert wait(app, lambda: not identd._shared.listening, 4000)
    win.close(); srv.stop()


def test_ident_is_off_by_default(app, tmp_path, ident_port):
    assert Config().identd_on is False
    srv = SilentServer()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: s.sock.state() == s.sock.SocketState.ConnectedState, 5000)
    assert identd._shared is None or not identd._shared.listening
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", ident_port), timeout=0.5).close()
    s.disconnect_from_network()
    win.close(); srv.stop()


def test_ident_closes_after_a_failed_try(app, tmp_path, ident_port):
    win, net = make_win(tmp_path, free_port())                # nobody listens there: refused
    prefs(win, lambda d: d.identd_on.setChecked(True))
    s = win.connect_network(net)
    assert identd._shared is not None                         # it was opened for this try
    assert wait(app, lambda: not identd._shared.listening and s not in identd._shared.holders, 6000), texts(s)
    s.disconnect_from_network()
    win.close()


def test_ident_closes_after_its_time_is_up(app, tmp_path, ident_port, monkeypatch):
    monkeypatch.setattr(identd, "HOLD_S", 1)
    srv = SilentServer()
    win, net = make_win(tmp_path, srv.port)
    prefs(win, lambda d: d.identd_on.setChecked(True))
    s = win.connect_network(net)
    assert wait(app, lambda: identd._shared is not None and identd._shared.listening, 3000)
    assert wait(app, lambda: not identd._shared.listening, 4000)
    assert s.state != "disconnected"                         # only the ident server stopped
    s.disconnect_from_network()
    win.close(); srv.stop()


def test_ident_port_busy_says_so_and_connects_anyway(app, tmp_path, ident_port):
    busy = socket.socket()
    busy.bind(("0.0.0.0", ident_port))
    busy.listen(1)
    target = FakeIrcd()
    win, net = make_win(tmp_path, target.port)
    prefs(win, lambda d: d.identd_on.setChecked(True))
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), texts(s)
    said = [l for l in s.server_buffer.lines if f"Ident is off: port {ident_port} is in use or blocked" in l.text]
    assert len(said) == 1 and said[0].kind == INFO and said[0].text.endswith("Connecting anyway.")
    s.disconnect_from_network()
    win.close(); target.stop(); busy.close()


def test_ident_listener_is_shared_and_counted(app, ident_port):
    class Holder:
        sock = None
    srv = identd.IdentServer()
    a, b = Holder(), Holder()
    assert srv.acquire(a, "a") == "" and srv.listening
    first = srv.srv
    assert srv.acquire(b, "b:c d") == "" and srv.srv is first and srv.holders[b] == "bcd"
    srv.release(a)
    assert srv.listening
    srv.release(b)
    assert not srv.listening
    assert srv.answer(b"1, 70000") == "1, 70000 : ERROR : INVALID-PORT\r\n"
    assert identd.clean_user("") == "bchat" and identd.clean_user("x\r\ny") == "xy"
    # a port another program holds (even on IPv4 only) is busy: never shared with it
    other = socket.socket()
    other.bind(("0.0.0.0", ident_port))
    other.listen(1)
    assert srv.acquire(a, "a") != "" and not srv.listening and a not in srv.holders
    other.close()


# --- UPnP --------------------------------------------------------------------------------------------------

DESC = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
 <device><deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType>
  <deviceList><device><deviceType>urn:schemas-upnp-org:device:WANDevice:1</deviceType>
   <deviceList><device><deviceType>urn:schemas-upnp-org:device:WANConnectionDevice:1</deviceType>
    <serviceList>
     <service><serviceType>urn:schemas-upnp-org:service:WANPPPConnection:1</serviceType><controlURL>/ppp</controlURL></service>
     <service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType><controlURL>/ctl</controlURL></service>
    </serviceList>
   </device></deviceList>
  </device></deviceList>
 </device>
</root>"""

FAULT = """<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault>
<faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring><detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">
<errorCode>718</errorCode><errorDescription>ConflictInMappingEntry</errorDescription></UPnPError></detail></s:Fault></s:Body></s:Envelope>"""


class FakeRouter:
    """An SSDP responder (UDP) plus the router's HTTP side: description XML and the SOAP control URL."""

    def __init__(self, outside="203.0.113.7", fail_add=False, answer=True):
        self.outside, self.fail_add = outside, fail_add
        self.calls = []                          # (action, {field: value}, path)
        self.searches = []
        router = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path != "/desc.xml":
                    self.send_error(404)
                    return
                body = DESC.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                import re
                import xml.etree.ElementTree as ET
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                action = self.headers["SOAPAction"].strip('"').split("#")[1]
                fields = {}
                for e in ET.fromstring(raw).iter():
                    if e.tag.rsplit("}", 1)[-1] == action:
                        fields = {k.tag: (k.text or "") for k in e}
                router.calls.append((action, fields, self.path))
                if action == "AddPortMapping" and router.fail_add:
                    body = FAULT.encode()
                    self.send_response(500)
                else:
                    extra = f"<NewExternalIPAddress>{router.outside}</NewExternalIPAddress>" if action == "GetExternalIPAddress" else ""
                    body = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                            f'<u:{action}Response xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1">{extra}'
                            f'</u:{action}Response></s:Body></s:Envelope>').encode()
                    self.send_response(200)
                self.send_header("Content-Type", 'text/xml; charset="utf-8"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.target = self.udp.getsockname()
        self.answer = answer
        threading.Thread(target=self._ssdp, daemon=True).start()

    def _ssdp(self):
        while True:
            try:
                data, peer = self.udp.recvfrom(4096)
            except OSError:
                return
            self.searches.append(data.decode())
            if self.answer:
                st = data.decode().split("ST: ", 1)[1].split("\r\n", 1)[0]
                self.udp.sendto((f"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=120\r\nST: {st}\r\n"
                                 f"LOCATION: http://127.0.0.1:{self.http.server_port}/desc.xml\r\n\r\n").encode(), peer)

    def actions(self, name):
        return [f for a, f, _ in self.calls if a == name]

    def stop(self):
        self.http.shutdown()
        self.http.server_close()
        self.udp.close()


def upnp_win(tmp_path, router, first=50000, last=50002):
    win, _ = make_win(tmp_path, 1)
    win.upnp.target, win.upnp.timeout = router.target, 1.0       # never the real multicast group
    win.cfg.dcc_first_port, win.cfg.dcc_last_port = first, last
    return win


def test_upnp_finds_the_router_and_opens_the_dcc_range(app, tmp_path):
    router = FakeRouter()
    win = upnp_win(tmp_path, router)
    seen = []
    win.upnp.changed.connect(seen.append)
    prefs(win, lambda d: d.upnp_on.setChecked(True))
    assert win.cfg.upnp_on
    done = "Router found · outside address 203.0.113.7 · ports 50000–50002 open"
    assert wait(app, lambda: win.upnp.status == done, 6000), win.upnp.status
    assert seen[0] == upnp.LOOKING and seen[-1] == done
    adds = router.actions("AddPortMapping")
    assert [a["NewExternalPort"] for a in adds] == ["50000", "50001", "50002"]
    assert all(a["NewProtocol"] == "TCP" and a["NewInternalClient"] == "127.0.0.1" and a["NewInternalPort"] == a["NewExternalPort"]
               and a["NewPortMappingDescription"] == "BChat DCC" for a in adds)
    assert all(p == "/ctl" for a, _, p in router.calls)                      # the WANIPConnection service, not PPP
    assert "M-SEARCH" in router.searches[0] and "ssdp:discover" in router.searches[0]
    # the outside address is the DCC address while that one is automatic
    s = SimpleNamespace(external_ip="198.51.100.1", sock=None)
    assert win.dcc.my_address(s) == "203.0.113.7"
    win.cfg.dcc_ip = "192.0.2.5"
    assert win.dcc.my_address(s) == "192.0.2.5"
    win.cfg.dcc_ip = ""
    # unticked: the ports come off the router again
    prefs(win, lambda d: d.upnp_on.setChecked(False))
    assert wait(app, lambda: len(router.actions("DeletePortMapping")) == 3, 4000)
    assert win.upnp.status == "" and win.upnp.external_ip == ""
    assert win.dcc.my_address(s) == "198.51.100.1"
    win.close(); router.stop()


def test_upnp_takes_the_ports_off_when_bchat_quits(app, tmp_path):
    router = FakeRouter()
    win = upnp_win(tmp_path, router, 50010, 50010)
    prefs(win, lambda d: d.upnp_on.setChecked(True))
    assert wait(app, lambda: win.upnp.status.endswith("port 50010 open"), 6000), win.upnp.status
    win.close()
    assert [d["NewExternalPort"] for d in router.actions("DeletePortMapping")] == ["50010"]
    router.stop()


def test_upnp_moves_the_ports_when_the_range_changes(app, tmp_path):
    router = FakeRouter()
    win = upnp_win(tmp_path, router, 50000, 50001)
    prefs(win, lambda d: d.upnp_on.setChecked(True))
    assert wait(app, lambda: "50000–50001 open" in win.upnp.status, 6000), win.upnp.status
    prefs(win, lambda d: (d.dcc_first.setValue(50005), d.dcc_last.setValue(50005)))
    assert wait(app, lambda: win.upnp.status.endswith("port 50005 open"), 6000), win.upnp.status
    assert [d["NewExternalPort"] for d in router.actions("DeletePortMapping")] == ["50000", "50001"]
    assert len(router.searches) <= len(upnp.SEARCH_FOR)                     # the router was found once
    win.close(); router.stop()


def test_upnp_no_router(app, tmp_path):
    router = FakeRouter(answer=False)
    win = upnp_win(tmp_path, router)
    prefs(win, lambda d: d.upnp_on.setChecked(True))
    t0 = time.monotonic()
    assert wait(app, lambda: win.upnp.status == upnp.NO_ROUTER, 6000), win.upnp.status
    assert time.monotonic() - t0 < 3.5 and win.upnp.external_ip == ""
    assert router.calls == []
    win.close(); router.stop()


def test_upnp_needs_a_dcc_range(app, tmp_path):
    router = FakeRouter()
    win = upnp_win(tmp_path, router, 0, 0)
    prefs(win, lambda d: d.upnp_on.setChecked(True))
    assert win.upnp.status == upnp.NEED_RANGE
    wait(app, lambda: False, 300)
    assert router.searches == [] and router.calls == []
    win.close(); router.stop()


def test_upnp_router_refuses(app, tmp_path):
    router = FakeRouter(fail_add=True)
    win = upnp_win(tmp_path, router, 50000, 50000)
    prefs(win, lambda d: d.upnp_on.setChecked(True))
    want = "Router found, but it refused to open the ports (ConflictInMappingEntry (718))"
    assert wait(app, lambda: win.upnp.status == want, 6000), win.upnp.status
    assert win.upnp.external_ip == ""
    win.close(); router.stop()


def test_upnp_is_off_by_default_and_never_searches(app, tmp_path):
    assert Config().upnp_on is False
    win, _ = make_win(tmp_path, 1)
    assert win.upnp.status == "" and win.upnp._thread is None
    win.close()


def test_upnp_settings_status_line_follows_the_manager(app, tmp_path):
    from bchat.preferences import PreferencesDialog
    router = FakeRouter()
    win = upnp_win(tmp_path, router)
    d = PreferencesDialog(win)
    assert d.upnp_on.isChecked() is False and d.upnp_status.text() == ""
    d.upnp_on.setChecked(True)
    d.accept()
    assert wait(app, lambda: "Router found ·" in d.upnp_status.text(), 6000), d.upnp_status.text()
    d.deleteLater()
    win.close(); router.stop()


def test_upnp_description_from_elsewhere_is_ignored(app):
    assert upnp.describe("127.0.0.1", "http://192.0.2.1:1/desc.xml") is None     # not the device that answered
    assert upnp.describe("127.0.0.1", "file:///c:/x.xml") is None
    assert upnp.ports_text(5, 5) == "port 5" and upnp.ports_text(5, 9) == "ports 5–9"
