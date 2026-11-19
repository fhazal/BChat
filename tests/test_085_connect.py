"""0.8.5 mockups D and E (OK'd 2026-11-19): 'If the login fails' per network, and Preferences > Advanced > Connecting
(Retry N times, Connect time-out, Invisible mode +i). Loopback sockets only (plus one TEST-NET address that never answers)."""
import socket

from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow
from bchat.networklist import NetworkEditDialog
from fake_ircd import FakeIrcd
from test_live import _cert, live, make_win, prefs, wait  # noqa: F401  (live is a fixture)


def _texts(s):
    return [l.text for l in s.server_buffer.lines]


def _sasl_fail(app, tmp_path, **kw):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key, caps="sasl", sasl_ok=False)
    win, net = make_win(tmp_path, srv.port, ssl=True, sasl_user="acct", sasl_password="bad", allow_invalid_cert=True, **kw)
    s = win.connect_network(net)
    return srv, win, s


# --- D: If the login fails -------------------------------------------------------------------------------------------

def test_sasl_failure_disconnects_and_does_not_retry_by_default(app, tmp_path):
    srv, win, s = _sasl_fail(app, tmp_path)
    assert wait(app, lambda: any("will not retry" in t for t in _texts(s)), 8000), _texts(s)
    assert any("SASL login failed" in t for t in _texts(s))
    assert s.state == "disconnected" and not s.want_connected and not s._reconnect.isActive()
    assert wait(app, lambda: "QUIT" in srv.received)
    assert "CAP END" not in srv.received
    win.close(); srv.stop()


def test_sasl_failure_can_stay_connected(app, tmp_path):
    srv, win, s = _sasl_fail(app, tmp_path, login_fail="stay")
    assert wait(app, lambda: any("SASL login failed" in t for t in _texts(s)), 8000)
    assert wait(app, lambda: s.state == "connected")
    assert not any("will not retry" in t for t in _texts(s))
    win.close(); srv.stop()


def test_already_logged_in_907_is_not_a_failure(live):
    app, srv, win, s = live
    srv.send(":srv 907 Badaboom :You have already authenticated using SASL")
    assert wait(app, lambda: any("already logged in" in t for t in _texts(s)))
    for _ in range(20):
        app.processEvents()
    assert s.state == "connected" and s.want_connected


def test_network_editor_row_shows_for_sasl_and_cert_and_saves(app, tmp_path):
    win, net = make_win(tmp_path, 1)
    d = NetworkEditDialog(net, win)
    assert d.login_fail.currentIndex() == 0 and d.login_fail.itemText(0) == "Disconnect, don't retry"
    d.login.setCurrentIndex(0)
    assert not d.form.isRowVisible(d.login_fail)
    for i in (1, 2):
        d.login.setCurrentIndex(i)
        assert d.form.isRowVisible(d.login_fail)
    d.login.setCurrentIndex(1)
    start = d._state()
    d.login_fail.setCurrentIndex(1)
    assert d._state() != start               # closing now asks before losing it
    d.accept()
    assert net.login_fail == "stay"
    d2 = NetworkEditDialog(net, win)
    assert d2.login_fail.currentIndex() == 1
    d2.login_fail.setCurrentIndex(0)
    d2.accept()
    assert net.login_fail == "disconnect"
    win.close()


# --- E: Connecting ---------------------------------------------------------------------------------------------------

def test_invisible_mode_is_set_after_connecting(live):
    app, srv, win, s = live
    assert wait(app, lambda: "MODE Badaboom +i" in srv.received)


def test_invisible_mode_off_sends_nothing(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    win.cfg.invisible = False
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected" and "JOIN #skinhead" in srv.received)
    assert not any(x.startswith("MODE Badaboom +i") for x in srv.received)
    win.close(); srv.stop()


def _closed_port():
    so = socket.socket()
    so.bind(("127.0.0.1", 0))
    port = so.getsockname()[1]
    so.close()
    return port


def test_retry_limit_gives_up(app, tmp_path):
    win, net = make_win(tmp_path, _closed_port())
    win.cfg.connect_retries, win.cfg.reconnect_delay = 2, 1
    s = win.connect_network(net)
    assert wait(app, lambda: any("Gave up after 2 retries" in t for t in _texts(s)), 25000), _texts(s)
    assert not s.want_connected and not s._reconnect.isActive()
    assert sum("Reconnect try" in t for t in _texts(s)) == 2
    win.close()


def test_zero_retries_keeps_trying(app, tmp_path):
    win, net = make_win(tmp_path, _closed_port())
    win.cfg.connect_retries, win.cfg.reconnect_delay = 0, 1
    s = win.connect_network(net)
    assert wait(app, lambda: sum("Reconnect try" in t for t in _texts(s)) >= 3, 25000), _texts(s)
    assert s.want_connected and not any("Gave up" in t for t in _texts(s))
    s.disconnect_from_network()
    win.close()


def test_connect_timeout_gives_up_on_a_silent_server(app, tmp_path):
    net = NetworkConfig("Silent", [Server("192.0.2.1", 6667, False)])     # TEST-NET-1: nothing ever answers
    cfg = Config(nick="Badaboom", networks=[net], connect_timeout=1, reconnect_delay=60)
    win = MainWindow(cfg, tmp_path)
    win.skip_quit_prompt = True
    s = win.connect_network(net)
    assert wait(app, lambda: any("No answer from 192.0.2.1 after 1 seconds" in t for t in _texts(s)), 5000), _texts(s)
    assert s.state == "disconnected" and s._reconnect.isActive()             # goes on as for any failed try
    s.disconnect_from_network()
    win.close()


def test_advanced_page_shows_and_saves_connecting(app, tmp_path):
    win, _ = make_win(tmp_path, 2)

    def change(d):
        assert (d.connect_retries.value(), d.connect_timeout.value(), d.invisible.isChecked()) == (0, 30, True)
        d.connect_retries.setValue(5)
        d.connect_timeout.setValue(60)
        d.invisible.setChecked(False)
    prefs(win, change)
    c = win.cfg
    assert (c.connect_retries, c.connect_timeout, c.invisible) == (5, 60, False)
    win.close()
