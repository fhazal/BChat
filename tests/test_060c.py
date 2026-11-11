"""0.6.0 batch C: connecting (ports, WebSocket, VPN-only bind, IPv6, server features), small IRC things (channel notices,
account bans, friends with WATCH), URL Grabber extras, start options + portable + Lock."""
import json
import socket
import time

import pytest
from fake_ircd import FakeIrcd
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from bchat import config as config_mod, lock
from bchat.config import Config, NetworkConfig, Server, server_text
from bchat.dcc import address_field, peer_ip
from bchat.mainwindow import MainWindow
from bchat.session import Session
from bchat.xchat_import import parse_server
from test_live import _cert, live, make_win, prefs, wait  # noqa: F401  (live is a fixture)


def free_port() -> int:
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def lines(b):
    return [l.text for l in b.lines]


# --- 1 connecting --------------------------------------------------------------------------------

def test_server_lines_several_ports_and_websocket():
    sv = parse_server("irc.x/+6697,7000", False)
    assert (sv.port, sv.more_ports, sv.ssl) == (6697, [7000], True)
    assert server_text(sv) == "irc.x/+6697,7000"
    assert parse_server("irc.x/6667,abc,6667,6668", False).more_ports == [6668]
    ws = parse_server("wss://web.x/irc", False)
    assert (ws.host, ws.port, ws.ssl, ws.ws_path, ws.ws_plain) == ("web.x", 443, True, "/irc", False)
    assert server_text(ws) == "wss://web.x/irc"
    assert server_text(parse_server("wss://web.x:8097/", False)) == "wss://web.x:8097/"
    assert server_text(parse_server("wss://[::1]:9/z", False)) == "wss://[::1]:9/z"
    assert parse_server("ws://w.x/a", False).ws_plain
    for old in ("irc.x/+6697", "irc.x/*6667", "irc.x/6667"):
        assert server_text(parse_server(old, False)) == old


def test_ports_are_tried_in_random_order_then_the_next(app):
    net = NetworkConfig("N", [Server("a", 1, False, False, [2, 3]), Server("b", 9)])
    s = Session(net, Config(nick="x"))
    seen = set()
    for _ in range(40):
        s.server_index, s._ports_left, s._repeat = -1, [], False
        sv, p = s._pick_server()
        seen.add(p)
        got = [p] + [s._pick_server()[1] for _ in range(2)]
        assert sorted(got) == [1, 2, 3] and sv.host == "a"
        assert s._pick_server() == (net.servers[1], 9)            # then the next server
    assert seen == {1, 2, 3}
    s.server_index, s._cur_port, s._repeat = 0, 2, True
    assert s._pick_server() == (net.servers[0], 2)               # 'the same again' keeps the port


def test_dead_port_falls_through_to_the_live_one(app, tmp_path):
    srv = FakeIrcd()
    net = NetworkConfig("SkinIRC", [Server("127.0.0.1", free_port(), False, False, [srv.port])], autojoin="#skinhead")
    cfg = Config(nick="Badaboom", networks=[net], reconnect_delay=1)
    win = MainWindow(cfg, tmp_path)
    win.skip_quit_prompt = True
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), lines(s.server_buffer)
    assert any("picked from" in t for t in lines(s.server_buffer))
    win.close(); srv.stop()


def test_plain_ws_is_never_connected(app, tmp_path):
    win, net = make_win(tmp_path, 1)
    net.servers = [parse_server("ws://127.0.0.1:1/irc", False)]
    s = win.connect_network(net)
    assert wait(app, lambda: any("isn't encrypted" in t for t in lines(s.server_buffer)))
    assert s.state == "disconnected" and not s.want_connected
    win.close()


def test_websocket_server_logs_in(app, tmp_path):
    from PySide6.QtNetwork import QSslCertificate, QSslConfiguration, QSslKey, QSsl, QHostAddress
    from PySide6.QtWebSockets import QWebSocketServer
    crt, key = _cert(tmp_path)
    ws_srv = QWebSocketServer("fake", QWebSocketServer.SslMode.SecureMode)
    conf = QSslConfiguration.defaultConfiguration()
    conf.setLocalCertificate(QSslCertificate.fromPath(crt)[0])
    with open(key, "rb") as f:
        conf.setPrivateKey(QSslKey(f.read(), QSsl.KeyAlgorithm.Rsa))
    ws_srv.setSslConfiguration(conf)
    assert ws_srv.listen(QHostAddress("127.0.0.1"), 0)
    got, conns = [], []

    def arrived():
        c = ws_srv.nextPendingConnection()
        conns.append(c)

        def msg(t, c=c):
            got.append(t)
            if t.startswith("USER"):
                c.sendTextMessage(":srv 001 Badaboom :Welcome over WebSocket")
                c.sendTextMessage(":srv 376 Badaboom :End of MOTD")
        c.textMessageReceived.connect(msg)
    ws_srv.newConnection.connect(arrived)
    net = NetworkConfig("Web", [parse_server(f"wss://127.0.0.1:{ws_srv.serverPort()}/irc", False)], allow_invalid_cert=True)
    win = MainWindow(Config(nick="Badaboom", networks=[net]), tmp_path)
    win.skip_quit_prompt = True
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), lines(s.server_buffer)
    assert "NICK Badaboom" in got and not any("\r" in t or "\n" in t for t in got)   # one line per message
    assert any("WebSocket over SSL" in t for t in lines(s.server_buffer))
    win.close(); ws_srv.close()


def test_vpn_only_bind_stops_the_connect(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    win.cfg.bind_host, win.cfg.bind_strict = "10.254.253.252", True
    s = win.connect_network(net)
    assert wait(app, lambda: any("not connecting, as you asked" in t for t in lines(s.server_buffer)))
    time.sleep(0.3); app.processEvents()
    assert s.state == "disconnected" and not srv.received
    win.close(); srv.stop()


def test_ipv4_only_still_reaches_ipv4_servers(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    win.cfg.ip_mode = "ipv4"
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected")
    win.close(); srv.stop()


def test_server_features_off_are_never_asked_for(app, tmp_path):
    srv = FakeIrcd(caps="away-notify message-tags")
    win, net = make_win(tmp_path, srv.port, caps_off=["away-notify"])
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected")
    req = " ".join(x for x in srv.received if x.startswith("CAP REQ"))
    assert "message-tags" in req and "away-notify" not in req
    win.close(); srv.stop()


def test_edit_network_keeps_ports_wss_and_features(app, tmp_path):
    from bchat.networklist import NetworkEditDialog, ServerFeaturesDialog
    win, net = make_win(tmp_path, 1)
    d = NetworkEditDialog(net, win)
    d.servers.setPlainText("irc.x/+6697,7000\nwss://web.x/irc")
    f = ServerFeaturesDialog(d, "SkinIRC", [])
    f.boxes[0][0].setChecked(False)
    d.caps_off = f.caps_off()
    d.accept()
    assert server_text(net.servers[0]) == "irc.x/+6697,7000" and net.servers[1].ws_path == "/irc"
    assert net.caps_off == ["message-tags"]
    f.boxes[0][0].setChecked(False)
    [b for b in f.findChildren(QPushButton) if "Normal" in b.text()][0].click()
    assert f.caps_off() == []
    d2 = NetworkEditDialog(net, win)
    assert d2.servers.toPlainText() == "irc.x/+6697,7000\nwss://web.x/irc" and "1 turned off" in d2.features_note.text()
    win.close()


def test_dcc_addresses_ipv4_and_ipv6():
    assert address_field("1.2.3.4") == str((1 << 24) + (2 << 16) + (3 << 8) + 4)
    assert address_field("::ffff:1.2.3.4") == address_field("1.2.3.4")
    assert address_field("2001:db8::6") == "2001:db8::6"
    assert peer_ip("16909060", True) == "1.2.3.4"
    assert peer_ip("2001:db8::6", True) == "2001:db8::6"
    with pytest.raises(ValueError):
        peer_ip("2001:db8::6", False)
    with pytest.raises(ValueError):
        peer_ip("evil.host", True)


def test_ipv6_file_offer_is_understood(live):
    app, srv, win, s = live
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND notes.txt 2001:db8::6 5000 10\x01")
    assert wait(app, lambda: any(t.name == "notes.txt" for t in win.dcc.items))
    assert next(t for t in win.dcc.items if t.name == "notes.txt").ip == "2001:db8::6"


# --- 2 small IRC things -------------------------------------------------------------------------

def test_channel_notices_land_in_the_channel(live):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    win.select_buffer(s.server_buffer)          # so a notice for another place would show in the server tab
    srv.send(":ChanServ!s@services NOTICE Badaboom :[#skinhead] Welcome! Rules: be nice.")
    srv.send("@+draft/channel-context=#skinhead :Bot!b@h NOTICE Badaboom :tagged hello")
    srv.send(":ChanServ!s@services NOTICE Badaboom :[#elsewhere] not joined there")
    assert wait(app, lambda: any("tagged hello" in t for t in lines(chan)))
    assert any("Welcome! Rules" in t for t in lines(chan))
    assert not any("not joined there" in t for t in lines(chan))


def test_ban_by_account(live):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    win.run_command(s, "/ban -a Belon")
    assert wait(app, lambda: any("no account bans" in t for t in lines(s._front())))
    srv.send(":srv 005 Badaboom EXTBAN=~,acjq :are supported")
    assert wait(app, lambda: s.extban == ("~", "acjq"))
    win.select_buffer(chan)
    win.run_command(s, "/ban -a Belon")
    assert wait(app, lambda: any("doesn't know Belon's account" in t for t in lines(chan)))
    chan.users["belon"].account = "belon_acct"
    n = len(srv.received)
    win.run_command(s, "/ban -a Belon")
    assert wait(app, lambda: "MODE #skinhead +b ~a:belon_acct" in srv.received[n:])


def test_friends_with_watch_and_away(live):
    app, srv, win, s = live
    s._monitor = False
    srv.send(":srv 005 Badaboom WATCH=128 :are supported")
    assert wait(app, lambda: s._watch)
    n = len(srv.received)
    win.add_friend("Wira")
    assert wait(app, lambda: "WATCH +Wira" in srv.received[n:]), srv.received[n:]
    assert not any(x.startswith("ISON") for x in srv.received[n:])
    srv.send(":srv 604 Badaboom Wira w h 1 :is online")
    assert wait(app, lambda: s.friend_state.get("wira", {}).get("online"))
    srv.send(":srv 598 Badaboom Wira w h 2 :lunch")
    assert wait(app, lambda: "Wira is away: lunch" in lines(s.server_buffer))
    srv.send(":srv 599 Badaboom Wira w h 3 :is no longer away")
    assert wait(app, lambda: "Wira is back." in lines(s.server_buffer))
    srv.send(":srv 605 Badaboom Wira w h 4 :is offline")
    assert wait(app, lambda: not s.friend_state["wira"]["online"])
    errors = [l.text for l in s.server_buffer.lines if l.kind == "error" and "Wira" in l.text]
    assert not errors, errors                                         # 598/599 are not errors


def test_friend_away_from_away_notify(live):
    app, srv, win, s = live
    win.add_friend("Belon")
    srv.send(":Belon!b@h AWAY :brb")
    assert wait(app, lambda: "Belon is away: brb" in lines(s.server_buffer))
    srv.send(":Belon!b@h AWAY :brb")                                   # same again: no second line
    srv.send(":Belon!b@h AWAY")
    assert wait(app, lambda: "Belon is back." in lines(s.server_buffer))
    assert lines(s.server_buffer).count("Belon is away: brb") == 1


# --- 3 URL Grabber -------------------------------------------------------------------------------

def test_url_grabber_knows_who_where_when(live):
    app, srv, win, s = live
    srv.send(":Belon!b@h PRIVMSG #skinhead :look https://bajubesi.org/x mail me a@b.org")
    assert wait(app, lambda: "https://bajubesi.org/x" in win.urls)
    info = win.url_info["https://bajubesi.org/x"]
    assert (info["nick"], info["where"], info["new"]) == ("Belon", "#skinhead", True)
    assert "a@b.org" not in win.urls                                   # emails off by default
    w = win.open_tool("urls")
    top = w.view.topLevelItem(0)
    assert [top.text(c) for c in range(3)] == ["https://bajubesi.org/x", "Belon", "#skinhead"]
    assert top.font(0).bold()
    w.emails.setChecked(True)
    srv.send(":Belon!b@h PRIVMSG #skinhead :now a@b.org")
    srv.send(":Belon!b@h JOIN #other")                                 # masks in join lines are no emails
    assert wait(app, lambda: "a@b.org" in win.urls)
    assert not any("b@h" in u for u in win.urls)
    w.search.setText("bajubesi")
    assert w.view.topLevelItemCount() == 1
    w.search.setText("")
    w.view.setCurrentItem(w.view.topLevelItem(1))
    w.note("for later")
    assert win.url_info["https://bajubesi.org/x"]["note"] == "for later"
    win.select_buffer(s.buffers["#skinhead"])
    n = len(srv.received)
    w.view.setCurrentItem(w.view.topLevelItem(1))
    w.send()
    assert wait(app, lambda: any(x.startswith("PRIVMSG #skinhead ") and x.endswith("https://bajubesi.org/x")
                                 for x in srv.received[n:])), srv.received[n:]
    w.remove()
    assert "https://bajubesi.org/x" not in win.urls


def test_url_list_kept_after_restart_only_with_the_tick(app, tmp_path):
    win, net = make_win(tmp_path, 1)
    win.urls, win.url_info = ["https://a.org"], {"https://a.org": {"nick": "Wira", "where": "#c", "ts": 5.0, "note": "n", "new": True}}
    win._write_urls()
    assert not (tmp_path / "urls.json").exists()
    win.cfg.url_keep = True
    win._write_urls()
    rows = json.loads((tmp_path / "urls.json").read_text(encoding="utf-8"))
    assert rows == [{"url": "https://a.org", "nick": "Wira", "where": "#c", "ts": 5.0, "note": "n"}]
    win2 = MainWindow(win.cfg, tmp_path)
    assert win2.urls == ["https://a.org"] and win2.url_info["https://a.org"]["note"] == "n"
    win.cfg.url_keep = False
    win2._write_urls()
    assert not (tmp_path / "urls.json").exists()
    win.close(); win2.close()


# --- 4 start options, portable, Lock ------------------------------------------------------------

def test_lock_password_and_sealing():
    d, key = lock.make("hunter22", {"no_dcc": True, "only_channels": "#chat"})
    assert "hunter22" not in json.dumps(d)
    assert lock.unlock(d, "wrong") is None and lock.unlock(d, "hunter22") == key
    blob = lock.seal(key, "secret text")
    assert "secret" not in blob and lock.open_box(key, blob) == "secret text"
    assert lock.open_box(b"x" * 32, blob) is None
    assert lock.open_box(key, blob[:-4] + "AAAA") is None               # tampered
    assert lock.allowed_channels(d) == ["#chat"]


def test_portable_passwords_sealed_with_lock_or_not_kept(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "PORTABLE", True)
    net = NetworkConfig("N", [Server("h")], nickserv="ns-pass", sasl_password="sasl-pass")
    cfg = Config(nick="x", networks=[net])
    monkeypatch.setattr(config_mod, "LOCK_KEY", None)
    config_mod.save(cfg, tmp_path)
    text = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert "ns-pass" not in text and json.loads(text)["secrets"] == "none"
    d, key = lock.make("pw12", {})
    monkeypatch.setattr(config_mod, "LOCK_KEY", key)
    config_mod.save(cfg, tmp_path)
    text = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert "ns-pass" not in text and json.loads(text)["secrets"] == "locked"
    back = config_mod.load(tmp_path)
    assert back.networks[0].nickserv == "ns-pass" and back.networks[0].sasl_password == "sasl-pass"
    monkeypatch.setattr(config_mod, "LOCK_KEY", None)
    later = config_mod.load(tmp_path)
    assert later.networks[0].nickserv == ""
    assert config_mod.open_locked(later, key) and later.networks[0].nickserv == "ns-pass"


def test_portable_folder(tmp_path, monkeypatch):
    from bchat.__main__ import portable_dir
    monkeypatch.chdir(tmp_path)
    assert portable_dir(False) is None
    assert portable_dir(True) == tmp_path / "BChat-data"
    (tmp_path / "portable.txt").write_text("")
    assert portable_dir(False) == tmp_path / "BChat-data"


def _answer_password(app, text, wrong_first=False):
    """Types into the lock window when it opens (it runs its own exec loop)."""
    state = {"tries": 0}

    def go():
        dlg = next((w for w in QApplication.topLevelWidgets() if w.isVisible() and "Lock" in w.windowTitle()
                    or w.isVisible() and w.windowTitle() == "BChat: Locked"), None)
        if dlg is None:
            QTimer.singleShot(50, go)
            return
        edit = dlg.findChild(QLineEdit)
        ok = [b for b in dlg.findChildren(QPushButton) if "Open" in b.text()][0]
        if wrong_first and state["tries"] == 0:
            state["tries"] = 1
            edit.setText("nope")
            ok.click()
            QTimer.singleShot(1300, go)
            return
        edit.setText(text)
        ok.click()
    QTimer.singleShot(50, go)


def test_lock_start_window_and_removed_note(app, tmp_path, monkeypatch):
    from bchat.__main__ import check_lock
    monkeypatch.setattr(config_mod, "LOCK_KEY", None)
    d, _ = lock.make("pw12", {"no_private": True})
    lock.write(tmp_path, d)
    cfg = Config(nick="x")
    win = MainWindow(cfg, tmp_path)
    _answer_password(app, "pw12", wrong_first=True)
    assert check_lock(win, tmp_path, cfg)
    assert cfg.lock_limits["no_private"] and cfg.lock_was_on and config_mod.LOCK_KEY is not None
    lock.remove(tmp_path)                       # 'Forgot password': lock.json deleted by hand
    assert check_lock(win, tmp_path, cfg)
    assert not cfg.lock_was_on and cfg.lock_removed_at > 0 and cfg.lock_limits is None
    from bchat.preferences import PreferencesDialog
    p = PreferencesDialog(win, "Lock")
    assert "The lock was removed on" in p.lock_removed.text()
    p.reject(); win.close()


def test_lock_page_sets_password_and_limits(app, tmp_path, monkeypatch):
    import bchat.preferences as P
    monkeypatch.setattr(config_mod, "LOCK_KEY", None)
    monkeypatch.setattr(P, "new_password", lambda parent: "pw12")
    win, net = make_win(tmp_path, 1)

    def turn_on(d):
        d.lock_on.setChecked(True)
        d.lock_no_dcc.setChecked(True)
        d.lock_only.setChecked(True)
        d.lock_chans.setText("#chat, #BChat")
    prefs(win, turn_on)
    d = lock.read(tmp_path)
    assert d and d["no_dcc"] and d["only_channels"] == "#chat, #BChat" and lock.unlock(d, "pw12")
    assert win.cfg.lock_limits["no_dcc"] and win.cfg.lock_was_on
    p = P.PreferencesDialog(win, "Lock")
    assert not p.lock_on.isEnabled() and p.lock_unlock_btn.isVisibleTo(p)   # locked page needs the password
    p.reject()

    def turn_off(d):
        d.lock_open = True
        d.lock_on.setChecked(False)
    prefs(win, turn_off)
    assert lock.read(tmp_path) is None and win.cfg.lock_limits is None and not win.cfg.lock_removed_at
    win.close()


def test_lock_limits_at_work(live):
    app, srv, win, s = live
    win.cfg.lock_limits = {"no_dcc": True, "no_private": True, "only_channels": "#skinhead, #chat"}
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND evil.txt 16909060 5000 10\x01")
    srv.send(":Wira!w@h PRIVMSG Badaboom :hi there")
    assert wait(app, lambda: any("hi there" in t for t in lines(s.server_buffer)))
    assert "wira" not in s.buffers and not any(t.name == "evil.txt" for t in win.dcc.items)
    assert any("Lock: file transfers" in t for t in lines(s._front()) + lines(s.server_buffer))
    n = len(srv.received)
    win.run_command(s, "/join #chat,#other")
    assert wait(app, lambda: "JOIN #chat" in srv.received[n:])
    assert not any("#other" in x for x in srv.received[n:])
    win.cfg.lock_limits = None


def test_start_options_open_a_server(app, tmp_path):
    from bchat.__main__ import start_network
    srv = FakeIrcd()
    win, net = make_win(tmp_path, 1)
    s = start_network(win, f"127.0.0.1:{srv.port}", "chat,#BChat", "Starter")
    assert wait(app, lambda: s.state == "connected")
    assert s.net.nick == "Starter" and "NICK Starter" in srv.received
    assert wait(app, lambda: any(x.startswith("JOIN #chat") or x == "JOIN #BChat" for x in srv.received))
    assert all(n.name != f"127.0.0.1" for n in win.cfg.networks)        # not saved to the Network List
    win.close(); srv.stop()
