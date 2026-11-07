"""Safety: certificate trust (ask, once, always, trust on first use, changed) against a real SSL fake server,
and the risky-link check and window."""
import pytest
from fake_ircd import FakeIrcd
from PySide6.QtGui import QDesktopServices, QGuiApplication

from bchat.config import NetworkConfig, Server
from bchat.safety import link_risk
from test_live import _cert, make_win, wait


# --- links ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["https://skinhead.com.my/radio", "http://www.example.org/page.html", "skinhead.com.my",
                                 "https://github.com/x/y/releases", "https://example.com/setup.exe.html"])
def test_ordinary_links_are_not_risky(url):
    assert link_risk(url) == ""


@pytest.mark.parametrize("url,word", [("https://get-free-nitro.example/setup.exe", "program"),
                                      ("http://x.example/a/b/run.PS1?id=3", "program"),
                                      ("https://example.org/tool.msi", "program"),
                                      ("https://xn--pple-43d.com/login", "look-alike"),
                                      ("https://аpple.com/", "look-alike"),
                                      ("http://185.23.4.9/free", "bare internet address"),
                                      ("http://[2001:db8::1]/x", "bare internet address"),
                                      ("https://www.paypal.com@evil.example/", "name@")])
def test_risky_links_say_why(url, word):
    assert word in link_risk(url)


@pytest.fixture
def opened(monkeypatch):
    got = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: got.append(u.toString()) or True))
    return got


def test_ordinary_link_opens_with_one_click(app, tmp_path, opened):
    win, _ = make_win(tmp_path, 1)
    win.open_url("https://skinhead.com.my/radio")
    assert opened == ["https://skinhead.com.my/radio"] and getattr(win, "link_dialog", None) is None
    win.close()


def test_risky_link_asks_cancel_is_default_and_copy_works(app, tmp_path, opened):
    win, _ = make_win(tmp_path, 1)
    url = "https://get-free-nitro.example/setup.exe"
    win.open_url(url, "Spammer", "#skinhead")
    d = win.link_dialog
    assert d.isVisible() and opened == [] and d.cancel_btn.isDefault()
    assert d.question.text() == "This link downloads a program (.exe)"
    assert "From Spammer in #skinhead." in d.why.text()
    d.cancel_btn.click()
    assert wait(app, lambda: not d.isVisible()) and opened == []
    win.open_url(url, "Spammer", "#skinhead")
    win.link_dialog.copy_btn.click()
    assert QGuiApplication.clipboard().text() == url and opened == []
    win.open_url(url)
    win.link_dialog.open_btn.click()
    assert wait(app, lambda: opened == [url])
    win.close()


def test_chat_click_knows_who_posted_it(app, tmp_path, opened):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    srv.send(":Spammer!s@h PRIVMSG #skinhead :grab this https://get-free-nitro.example/setup.exe now")
    assert wait(app, lambda: any("setup.exe" in l.text for l in b.lines))
    from PySide6.QtCore import QUrl
    win.chat._open_url(QUrl("https://get-free-nitro.example/setup.exe"))
    assert "From Spammer in #skinhead." in win.link_dialog.why.text() and opened == []
    win.link_dialog.cancel_btn.click()
    win.close(); srv.stop()


# --- certificates, against a real SSL server with a self-signed certificate ---------------------------------

def test_new_networks_check_certificates():
    assert NetworkConfig("x").allow_invalid_cert is False and NetworkConfig("x").cert_pins == []


def ssl_win(app, tmp_path, **kw):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key)
    win, net = make_win(tmp_path, srv.port, ssl=True, **kw)
    return srv, win, net


def test_connect_once_does_not_remember(app, tmp_path):
    srv, win, net = ssl_win(app, tmp_path)
    s = win.connect_network(net)
    assert wait(app, lambda: getattr(win, "cert_dialog", None) is not None and win.cert_dialog.isVisible(), 8000)
    d = win.cert_dialog
    assert d.no_btn.isDefault() and "can't verify 127.0.0.1" in d.question.text()
    assert s.state != "connected" and not s._reconnect.isActive()        # no retries while asking
    d.once_btn.click()
    assert wait(app, lambda: s.state == "connected", 8000), [l.text for l in s.server_buffer.lines]
    assert net.cert_pins == []
    s.disconnect_from_network(); win.cert_dialog = None
    s.connect_to_network()
    assert wait(app, lambda: getattr(win, "cert_dialog", None) is not None and win.cert_dialog.isVisible(), 8000)  # asks again
    win.cert_dialog.no_btn.click()
    win.close(); srv.stop()


def test_always_trust_remembers_and_saves(app, tmp_path):
    srv, win, net = ssl_win(app, tmp_path)
    s = win.connect_network(net)
    assert wait(app, lambda: getattr(win, "cert_dialog", None) is not None and win.cert_dialog.isVisible(), 8000)
    fp = win.cert_dialog.info["fingerprint"]
    assert len(fp) == 64
    win.cert_dialog.always_btn.click()
    assert wait(app, lambda: s.state == "connected", 8000)
    assert net.cert_pins == [fp]
    import json
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["networks"][0]["cert_pins"] == [fp]
    s.disconnect_from_network(); win.cert_dialog = None
    srv.stop()
    srv = FakeIrcd(str(tmp_path / "c.pem"), str(tmp_path / "k.pem"))   # same certificate, fresh fake server
    net.servers = [Server("127.0.0.1", srv.port, True)]
    s.connect_to_network()
    assert wait(app, lambda: s.state == "connected", 8000), [l.text for l in s.server_buffer.lines][-8:]
    assert win.cert_dialog is None    # no question the second time
    win.close(); srv.stop()


def test_older_network_trusts_first_certificate_then_warns_when_it_changes(app, tmp_path):
    srv, win, net = ssl_win(app, tmp_path, allow_invalid_cert=True)
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000)
    assert len(net.cert_pins) == 1 and getattr(win, "cert_dialog", None) is None
    assert any("remembering it" in l.text for l in s.server_buffer.lines)
    s.disconnect_from_network()
    port = srv.port
    srv.stop()
    # same address, a new certificate: the kind of thing a man-in-the-middle looks like
    other = tmp_path / "other"
    other.mkdir()
    crt2, key2 = _cert(other)
    srv2 = FakeIrcd(crt2, key2)
    net.servers = [Server("127.0.0.1", srv2.port, True)]
    s.connect_to_network()
    assert wait(app, lambda: getattr(win, "cert_dialog", None) is not None and win.cert_dialog.isVisible(), 8000)
    d = win.cert_dialog
    assert d.info["changed"] and "has changed" in d.question.text() and s.state != "connected"
    assert any("CHANGED" in l.text for l in s.server_buffer.lines)
    d.always_btn.click()                                   # the user checked with the network: trust the new one
    assert wait(app, lambda: s.state == "connected", 8000)
    assert net.cert_pins == [d.info["fingerprint"]]          # replaces the old one
    win.close(); srv2.stop()


def test_users_flow_server_over_ssl_trust_add_network_rename(app, tmp_path):
    """The owner's real flow (11-08): /server host +port over SSL, trust the certificate, Add Network, rename.
    The tree, the tabs layout and the saved network all follow, and the trust carries over (no second question)."""
    from test_live import type_cmd
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key)
    win, _ = make_win(tmp_path, 1)
    win.skip_dialogs = True
    s = win.new_server_tab()
    win.select_buffer(s.server_buffer)
    type_cmd(win, f"/server 127.0.0.1 +{srv.port}")
    label = lambda: win.items[id(s.server_buffer)].text(0)
    assert label() == "127.0.0.1"                                    # a typed server shows its address, as before
    assert wait(app, lambda: getattr(win, "cert_dialog", None) is not None and win.cert_dialog.isVisible(), 8000)
    win.cert_dialog.always_btn.click()
    assert wait(app, lambda: s.state == "connected" and s.network_token, 8000)
    type_cmd(win, "/join #skinhead")
    assert wait(app, lambda: "#skinhead" in s.buffers and s.buffers["#skinhead"].joined)
    saved = win.add_network_from(s)
    assert label() == saved.name                                    # live: the tree shows the saved network
    assert saved.cert_pins and saved.cert_pins == s.net.cert_pins and saved.servers[0].ssl
    win.set_tab_layout("tabs")
    tab_names = lambda: [win.tabbar.tabText(i) for i in range(win.tabbar.count())]
    assert saved.name in tab_names()
    assert win.rename_network(saved, "JavaNET")
    assert "JavaNET" in tab_names() and saved.name == "JavaNET"
    win.set_tab_layout("tree")
    assert label() == "JavaNET"
    # channels and chat untouched by the renames
    assert "#skinhead" in s.buffers and s.state == "connected"
    # reconnecting the saved network: the certificate trusted on the /server tab is still trusted
    s.disconnect_from_network()
    srv.stop()
    srv = FakeIrcd(crt, key)
    saved.servers = [Server("127.0.0.1", srv.port, True)]
    win.cert_dialog = None
    s.connect_to_network()
    assert wait(app, lambda: s.state == "connected", 8000) and win.cert_dialog is None
    assert label() == "JavaNET"                                     # the server's NETWORK= doesn't undo the rename
    win.close(); srv.stop()


def test_valid_certificate_never_asks(app, tmp_path):
    """A server with a proper certificate (signed by an authority Windows trusts, right name, not expired)
    connects silently: no question, nothing remembered. Here a test authority stands in for Let's Encrypt."""
    import subprocess
    from PySide6.QtNetwork import QSslCertificate, QSslConfiguration
    from test_live import OPENSSL
    from pathlib import Path
    if not Path(OPENSSL).exists():
        pytest.skip("no openssl")
    run = lambda *a: subprocess.run([OPENSSL, *a], check=True, capture_output=True, cwd=tmp_path)
    run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "2", "-subj", "/CN=BChat Test Authority")
    (tmp_path / "ext.cnf").write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n")
    run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "srv.key", "-out", "srv.csr", "-subj", "/CN=localhost")
    run("x509", "-req", "-in", "srv.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out", "srv.pem", "-days", "2", "-extfile", "ext.cnf")
    keep = QSslConfiguration.defaultConfiguration()
    conf = QSslConfiguration.defaultConfiguration()
    conf.addCaCertificates(QSslCertificate.fromPath(str(tmp_path / "ca.pem")))     # as if the authority were trusted by Windows
    QSslConfiguration.setDefaultConfiguration(conf)
    try:
        srv = FakeIrcd(str(tmp_path / "srv.pem"), str(tmp_path / "srv.key"))
        win, net = make_win(tmp_path, srv.port, ssl=True)                         # new network: checks certificates
        assert net.allow_invalid_cert is False
        s = win.connect_network(net)
        assert wait(app, lambda: s.state == "connected", 8000), [l.text for l in s.server_buffer.lines][-6:]
        assert getattr(win, "cert_dialog", None) is None and net.cert_pins == []
        assert not any("certificate" in l.text.lower() and "trust" in l.text.lower() for l in s.server_buffer.lines)
        win.close(); srv.stop()
    finally:
        QSslConfiguration.setDefaultConfiguration(keep)


def test_accepting_a_program_asks_first_and_cancel_leaves_it_waiting(app, tmp_path):
    """A real DCC offer of an .exe: File Transfers' Accept and /dcc get both ask; ordinary files don't."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtTest import QTest
    from test_live import _sender, type_cmd
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    win.cfg.dcc_dir = str(tmp_path / "in")
    payload = b"MZ not really a program" * 50
    port, _ = _sender(payload)
    srv.send(f":B3L0N!b@h PRIVMSG Badaboom :\x01DCC SEND barangbaik.exe 2130706433 {port} {len(payload)}\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    w = win.tools["transfers"]
    w.view.topLevelItem(0).setSelected(True)
    QTest.mouseClick(w.accept_btn, _Qt.MouseButton.LeftButton)
    d = win.program_dialog
    assert d.isVisible() and d.cancel_btn.isDefault() and d.question.text() == "This file is a program (.exe)"
    assert "From B3L0N on SkinIRC." in d.why.text() and "barangbaik.exe" in d.words.itemAt(1).widget().text()
    d.cancel_btn.click()
    assert wait(app, lambda: not d.isVisible())
    app.processEvents()
    assert t.state == "queued"                                    # still waiting, nothing downloaded
    assert not (tmp_path / "in" / "barangbaik.exe").exists()
    type_cmd(win, "/dcc get B3L0N")                               # the command asks too
    d2 = win.program_dialog
    assert d2 is not d and d2.isVisible()
    d2.accept_btn.click()
    assert wait(app, lambda: t.state == "done", 8000), (t.state, t.error)
    assert (tmp_path / "in" / "barangbaik.exe").read_bytes() == payload
    # an ordinary file: one click, no question
    port2, _ = _sender(b"song")
    srv.send(f":B3L0N!b@h PRIVMSG Badaboom :\x01DCC SEND song.mp3 2130706433 {port2} 4\x01")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    win.program_dialog = None
    win.accept_transfer(win.dcc.items[1])
    assert wait(app, lambda: win.dcc.items[1].state == "done", 8000) and win.program_dialog is None
    win.close(); srv.stop()
