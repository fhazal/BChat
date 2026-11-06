"""BChat against the local fake server: login, SSL, user list, whois, nick menu, every enabled menu item."""
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fake_ircd import FakeIrcd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow
from bchat.protocol import lower, strip_format
from bchat.session import CHANNEL, WHOIS

OPENSSL = shutil.which("openssl") or r"C:\Program Files\Git\usr\bin\openssl.exe"


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


def make_win(tmp_path, port, ssl=False, **kw):
    net = NetworkConfig("SkinIRC", [Server("127.0.0.1", port, ssl)], autojoin="#skinhead", **kw)
    cfg = Config(nick="Badaboom", nick2="b2", networks=[net])
    win = MainWindow(cfg, tmp_path)
    win.skip_quit_prompt = True
    win.show()
    return win, net


@pytest.fixture
def live(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers and len(s.buffers["#skinhead"].users) == 14), s.server_buffer.lines
    yield app, srv, win, s
    win.close()
    srv.stop()


def test_login_sends_identity(live):
    app, srv, win, s = live
    assert "NICK Badaboom" in srv.received
    assert any(x.startswith("USER ") for x in srv.received)
    assert "JOIN #skinhead" in srv.received
    assert "multi-prefix" in s._cap_active


def test_password_goes_to_server_but_not_raw_log(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port, password="hunter2")
    win.connect_network(net)
    assert wait(app, lambda: any(x.startswith("PASS") for x in srv.received))
    assert "PASS hunter2" in srv.received
    assert not any("hunter2" in l for l in win.raw_lines)
    win.close()
    srv.stop()


def test_user_order_count_and_away(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    order = [u.nick for u in b.sorted_users()]
    assert order[:3] == ["B3L0N[JVN]", "Belon", "Fhazal"]
    assert order[5:7] == ["DJSkinhead", "Oracle"]
    assert order[7] == "Badaboom"
    assert b.counts() == (5, 14)
    assert win.count.text() == "5 ops, 14 total"
    assert wait(app, lambda: b.users[lower("Psycho")].away)
    assert not b.users[lower("Belon")].away


def test_title_like_xchat(live):
    app, srv, win, s = live
    assert wait(app, lambda: win.windowTitle() == "BChat: Badaboom @ irc.fake.org / #skinhead (+nt 14)"), win.windowTitle()


def test_say_clear_and_me(live):
    app, srv, win, s = live
    win.input.setText("hello all")
    QTest.keyClick(win.input, Qt.Key.Key_Return)
    assert wait(app, lambda: "PRIVMSG #skinhead :hello all" in srv.received)
    b = s.buffers["#skinhead"]
    assert any(l.left == "[Badaboom]" and l.text == "hello all" for l in b.lines)
    win.input.setText("/clear")
    QTest.keyClick(win.input, Qt.Key.Key_Return)
    assert b.lines == []
    assert win.chat.document().isEmpty()
    win.input.setText("/me waves")
    QTest.keyClick(win.input, Qt.Key.Key_Return)
    assert wait(app, lambda: "PRIVMSG #skinhead :\x01ACTION waves\x01" in srv.received)


def test_double_click_whois_prints_lines_with_info_icon(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    rect = win.userlist.visualRect(win.userlist.model().index(6))
    QTest.mouseClick(win.userlist.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(win.userlist.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert wait(app, lambda: any("End of WHOIS" in l.text for l in b.lines)), srv.received[-5:]
    assert "WHOIS Oracle Oracle" in srv.received
    w = [l for l in b.lines if l.kind == WHOIS]
    assert strip_format(w[0].text) == "[Oracle] (oracle@bot.bajubesi.org): Oracle eggdrop"
    assert any(strip_format(l.text).startswith("[Oracle] idle 00:04:12, signon:") for l in w)


def test_nick_menu_matches_xchat_and_info_panel_fills(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    u = b.users[lower("Oracle")]
    menu = win.build_nick_menu(b, [u])
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == ["Oracle", "Open Dialog Window", "Send a File", "User Info (WhoIs)", "Add to Friends List", "Operator Actions"]
    before = sum(1 for l in b.lines if l.kind == WHOIS)
    u.server = ""
    menu.actions()[0].menu().aboutToShow.emit()
    assert wait(app, lambda: u.server == "irc.bajubesi.org")
    assert u.realname == "Oracle eggdrop" and u.host == "oracle@bot.bajubesi.org"
    # the silent whois must not print anything
    assert sum(1 for l in b.lines if l.kind == WHOIS) == before
    menu.deleteLater()


def test_operator_actions_send_right_commands(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    u = b.users[lower("Oracle")]
    menu = win.build_nick_menu(b, [u])
    ops = next(a.menu() for a in menu.actions() if a.text() == "Operator Actions")
    next(a for a in ops.actions() if a.text() == "Give Ops").trigger()
    assert wait(app, lambda: "MODE #skinhead +o Oracle" in srv.received)
    srv.send(":Fhazal!f@h MODE #skinhead +o Oracle")
    assert wait(app, lambda: "@" in u.prefixes)
    assert b.counts()[0] == 6
    srv.send(":Fhazal!f@h MODE #skinhead -o Oracle")
    assert wait(app, lambda: "@" not in u.prefixes)
    menu.deleteLater()


def test_new_tabs_do_not_steal_focus_unless_asked(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    srv.send(":Belon!b@h PRIVMSG Badaboom :psst")
    assert wait(app, lambda: "belon" in s.buffers)
    srv.send(":Badaboom!u@h JOIN #other")
    assert wait(app, lambda: "#other" in s.buffers)
    assert win.buf is b
    win.input.setText("/join #mine")
    QTest.keyClick(win.input, Qt.Key.Key_Return)
    assert wait(app, lambda: win.buf is s.buffers.get("#mine"))


def test_own_light_next_to_nick(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert win.own_light.pixmap().isNull()
    srv.send(":Fhazal!f@h MODE #skinhead +o Badaboom")
    assert wait(app, lambda: not win.own_light.pixmap().isNull())
    srv.send(":Fhazal!f@h MODE #skinhead -o Badaboom")
    assert wait(app, lambda: win.own_light.pixmap().isNull())


def test_events_update_the_list(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    srv.send(":New!n@h JOIN #skinhead")
    assert wait(app, lambda: lower("New") in b.users)
    srv.send(":New!n@h NICK :Newer")
    assert wait(app, lambda: lower("Newer") in b.users and lower("New") not in b.users)
    srv.send(":Newer!n@h AWAY :brb")
    assert wait(app, lambda: b.users[lower("Newer")].away)
    srv.send(":Newer!n@h QUIT :bye")
    assert wait(app, lambda: lower("Newer") not in b.users)
    srv.send(":Belon!b@h PART #skinhead :later")
    assert wait(app, lambda: lower("Belon") not in b.users)


def test_highlight_and_query_open(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    srv.send(":Belon!b@h PRIVMSG #skinhead :Badaboom hello")
    assert wait(app, lambda: any(l.kind == "hilite" and l.text == "Badaboom hello" for l in b.lines))
    srv.send(":Belon!b@h PRIVMSG #skinhead :Badaboomer is not you")
    assert wait(app, lambda: any(l.kind == "msg" and l.text == "Badaboomer is not you" for l in b.lines))
    srv.send(":Belon!b@h PRIVMSG Badaboom :private")
    assert wait(app, lambda: "belon" in s.buffers)
    assert s.buffers["belon"].kind == "query"
    assert s.buffers["belon"].activity == 3 or win.buf is s.buffers["belon"]


def test_nick_taken_falls_back(app, tmp_path):
    srv = FakeIrcd(taken_nicks=["Badaboom"])
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected")
    assert s.nick == "b2"
    win.close()
    srv.stop()


def test_garbage_from_server_does_not_crash(live):
    app, srv, win, s = live
    for line in ("READ x", "TLS y", "TCP", "DISCONNECTED z", ":a!b@c JOIN", ":x 353", "@bad", ":only.prefix", "\x01\x02", ":x MODE #skinhead"):
        srv.send(line)
    srv.send(":Belon!b@h PRIVMSG #skinhead :still alive")
    assert wait(app, lambda: any(l.text == "still alive" for l in s.buffers["#skinhead"].lines))
    assert s.state == "connected"


def test_reconnects_after_drop(live):
    app, srv, win, s = live
    srv.client.close()
    assert wait(app, lambda: s.state == "disconnected")
    assert s._reconnect.isActive()
    s.disconnect_from_network()
    assert not s._reconnect.isActive()


def live_with(app, tmp_path, net_kw=None, **srv_kw):
    srv = FakeIrcd(**srv_kw)
    win, net = make_win(tmp_path, srv.port, **(net_kw or {}))
    s = win.connect_network(net)
    return srv, win, net, s


def test_sasl_needs_ssl_and_keeps_password_off_plain_connections(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, {"sasl_user": "acct", "sasl_password": "hunter2"}, caps="sasl=PLAIN")
    assert wait(app, lambda: s.state == "connected")
    assert not any(x.startswith("AUTHENTICATE") for x in srv.received)
    assert any("SASL login skipped" in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_sasl_plain_over_ssl(app, tmp_path):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key, caps="sasl=PLAIN,EXTERNAL")
    win, net = make_win(tmp_path, srv.port, ssl=True, sasl_user="acct", sasl_password="hunter2")
    s = win.connect_network(net)
    assert wait(app, lambda: any("SASL login successful" in l.text for l in s.server_buffer.lines), 8000), [l.text for l in s.server_buffer.lines]
    import base64
    assert base64.b64decode(srv.auth_blob) == b"acct\0acct\0hunter2"
    assert wait(app, lambda: s.state == "connected")
    assert not any("hunter2" in l or srv.auth_blob in l for l in win.raw_lines)
    win.close(); srv.stop()


def test_sasl_failure_still_finishes_login(app, tmp_path):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key, caps="sasl", sasl_ok=False)
    win, net = make_win(tmp_path, srv.port, ssl=True, sasl_user="acct", sasl_password="bad")
    s = win.connect_network(net)
    assert wait(app, lambda: any("SASL login failed" in l.text for l in s.server_buffer.lines), 8000)
    assert wait(app, lambda: "CAP END" in srv.received)
    assert wait(app, lambda: s.state == "connected")
    win.close(); srv.stop()


def test_sts_moves_to_ssl_and_refuses_a_bad_certificate(app, tmp_path):
    """The test certificate is self-signed, and under STS "accept invalid" must not apply."""
    crt, key = _cert(tmp_path)
    tls = FakeIrcd(crt, key)
    plain = FakeIrcd(caps=f"sts=port={tls.port},duration=300")
    win, net = make_win(tmp_path, plain.port, allow_invalid_cert=True)
    s = win.connect_network(net)
    assert wait(app, lambda: any("certificate rejected" in l.text for l in s.server_buffer.lines), 8000), [l.text for l in s.server_buffer.lines]
    assert win.cfg.sts["127.0.0.1"]["port"] == tls.port
    assert not any(x.startswith("USER") for x in tls.received)
    assert s.state != "connected"
    s.disconnect_from_network()
    win.close(); tls.stop(); plain.stop()


def test_ircv3_events(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="extended-join account-notify setname invite-notify cap-notify chghost batch message-tags")
    assert wait(app, lambda: "#skinhead" in s.buffers and lower("Belon") in s.buffers["#skinhead"].users)
    assert "extended-join" in s._cap_active
    b = s.buffers["#skinhead"]
    srv.send(":New!n@h JOIN #skinhead acctname :Real New")
    assert wait(app, lambda: lower("New") in b.users)
    u = b.users[lower("New")]
    assert (u.account, u.realname) == ("acctname", "Real New")
    srv.send(":New!n@h ACCOUNT *")
    assert wait(app, lambda: u.account == "")
    srv.send(":New!n@h SETNAME :Another")
    assert wait(app, lambda: u.realname == "Another")
    srv.send(":New!n@h CHGHOST nu newhost.my")
    assert wait(app, lambda: u.host == "nu@newhost.my")
    srv.send(":srv CAP Badaboom DEL :setname")
    assert wait(app, lambda: "setname" not in s._cap_active)
    srv.send(":srv BATCH +x netsplit a b")
    srv.send("@batch=x;time=2026-11-07T01:00:00.000Z :New!n@h PRIVMSG #skinhead :old line")
    srv.send(":srv BATCH -x")
    assert wait(app, lambda: any(l.text == "old line" for l in b.lines))
    line = next(l for l in b.lines if l.text == "old line")
    assert int(line.ts) == 1794013200
    srv.send(":srv FAIL JOIN NO_ACCESS #x :You may not join")
    assert wait(app, lambda: any("You may not join" in l.text for l in s._front().lines))
    win.close(); srv.stop()


def test_whox_fills_user_details(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, whox=True)
    assert wait(app, lambda: "#skinhead" in s.buffers and s.buffers["#skinhead"].users.get(lower("Belon")) and s.buffers["#skinhead"].users[lower("Belon")].server == "srv.my")
    u = s.buffers["#skinhead"].users[lower("Belon")]
    assert (u.account, u.realname, u.host) == ("acctBelon", "Whox Belon", "belon@host.example.my")
    assert any("%tcuhsnfar,152" in x for x in srv.received)
    win.close(); srv.stop()


def test_line_breaks_cannot_inject_commands(live):
    app, srv, win, s = live
    s.say("#skinhead", "hello\r\nQUIT :owned")
    assert wait(app, lambda: any("hello" in x for x in srv.received))
    assert not any(x.startswith("QUIT") for x in srv.received)


def test_send_queue_paces_a_flood(live):
    app, srv, win, s = live
    start = len(srv.received)
    for i in range(30):
        s.say("#skinhead", f"m{i}")
    wait(app, lambda: False, 300)
    sent = [x for x in srv.received[start:] if x.startswith("PRIVMSG")]
    assert 1 <= len(sent) <= 7 and len(s._queue) > 20
    s._queue.clear()


def test_user_command_goes_before_background_lines(live):
    app, srv, win, s = live
    s._queue.clear()
    s._next_send = time.time() + 5  # budget partly used, as just after a login
    s.fetch_who("#a")
    s.fetch_who("#b")
    assert s._queue == ["WHO #a", "WHO #b"]
    s.whois("Oracle")
    assert wait(app, lambda: "WHOIS Oracle Oracle" in srv.received)
    assert not any(x in srv.received for x in ("WHO #a", "WHO #b"))
    s._queue.clear()


def test_ctcp_flood_stops_replies(live):
    app, srv, win, s = live
    for _ in range(9):
        srv.send(":x!y@z PRIVMSG Badaboom :\x01TIME\x01")
    assert wait(app, lambda: len(s._ctcp_times) >= 9)
    assert len(s._ctcp_times) == 9
    assert any("CTCP flood" in l.text for b in s.all_buffers() for l in b.lines)


def test_markup_from_network_is_not_rendered(live):
    app, srv, win, s = live
    from PySide6.QtWidgets import QLabel
    assert win.titlebar.title.textFormat() == Qt.TextFormat.PlainText
    assert win.nick_label.textFormat() == Qt.TextFormat.PlainText
    b = s.buffers["#skinhead"]
    u = b.users[lower("Oracle")]
    u.realname = "<img src=x><b>bold</b>"
    menu = win.build_nick_menu(b, [u])
    head = menu.actions()[0].menu()
    vals = [l for l in head.findChildren(QLabel) if l.text() == u.realname]
    assert vals and vals[0].textFormat() == Qt.TextFormat.PlainText
    menu.deleteLater()


def test_silent_whois_only_when_details_are_missing(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    u = b.users[lower("Oracle")]
    assert wait(app, lambda: u.server)
    u.away = False
    srv.received.clear()
    menu = win.build_nick_menu(b, [u])
    menu.actions()[0].menu().aboutToShow.emit()
    wait(app, lambda: False, 200)
    assert not any(x.startswith("WHOIS") for x in srv.received)
    u.server = ""
    menu.actions()[0].menu().aboutToShow.emit()
    assert wait(app, lambda: any(x == "WHOIS Oracle" for x in srv.received))
    menu.deleteLater()


def test_alt_number_and_ctrl_page_keys(live):
    app, srv, win, s = live
    win._change_page(number=1)
    assert win.buf is s.server_buffer
    win._change_page(delta=1)
    assert win.buf is s.buffers["#skinhead"]
    win._change_page(delta=1)
    assert win.buf is s.server_buffer


def _cert(tmp_path: Path):
    if not Path(OPENSSL).exists():
        pytest.skip("no openssl")
    crt, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt),
                    "-days", "1", "-subj", "/CN=fake"], check=True, capture_output=True)
    return str(crt), str(key)


def test_ssl_with_invalid_certificate_allowed(app, tmp_path):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key)
    win, net = make_win(tmp_path, srv.port, ssl=True, allow_invalid_cert=True)
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), [l.text for l in s.server_buffer.lines]
    win.close()
    srv.stop()


def test_ssl_refused_when_invalid_not_allowed(app, tmp_path):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key)
    win, net = make_win(tmp_path, srv.port, ssl=True, allow_invalid_cert=False)
    s = win.connect_network(net)
    assert wait(app, lambda: any("certificate rejected" in l.text for l in s.server_buffer.lines), 8000)
    assert s.state != "connected"
    s.disconnect_from_network()
    win.close()
    srv.stop()


def test_traffic_lights(app, tmp_path):
    win, _ = make_win(tmp_path, 1)
    red, yellow, green = win.titlebar.lights
    assert [b.toolTip() for b in win.titlebar.lights] == ["Close", "Minimize", "Maximize"]
    QTest.mouseClick(green, Qt.MouseButton.LeftButton)
    assert wait(app, win.isMaximized)
    QTest.mouseClick(green, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: not win.isMaximized())
    QTest.mouseClick(red, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: not win.isVisible())


def test_window_buttons_are_top_right_in_windows_order(app, tmp_path):
    win, _ = make_win(tmp_path, 1)
    wait(app, lambda: False, 50)
    red, yellow, green = win.titlebar.lights
    x = lambda b: b.mapTo(win.titlebar, QPoint(0, 0)).x()
    assert x(yellow) < x(green) < x(red)
    assert win.titlebar.width() - x(red) < 30
    logo_x = win.titlebar.logo.mapTo(win.titlebar, QPoint(0, 0)).x()
    assert logo_x < 15 and logo_x < win.titlebar.title.mapTo(win.titlebar, QPoint(0, 0)).x() < 45
    assert not win.titlebar.logo.pixmap().isNull()
    win.close()


def test_dialogs_show_the_logo_too(app, tmp_path):
    from bchat.networklist import NetworkListDialog
    win, _ = make_win(tmp_path, 1)
    d = NetworkListDialog(win)
    assert not d.titlebar.logo.pixmap().isNull()
    d.reject()
    win.close()


def test_dragging_on_the_logo_reaches_the_title_bar(app, tmp_path):
    win, _ = make_win(tmp_path, 1)
    assert win.titlebar.logo.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    win.close()


def test_yellow_button_minimizes(app, tmp_path):
    win, _ = make_win(tmp_path, 1)
    QTest.mouseClick(win.titlebar.lights[1], Qt.MouseButton.LeftButton)
    assert wait(app, win.isMinimized)
    win.close()


def test_network_list_buttons(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QPushButton
    from bchat.networklist import NetworkEditDialog, NetworkListDialog
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    win.cfg.networks.append(NetworkConfig("Aaa"))
    d = NetworkListDialog(win)
    d.show()
    btn = {b.text().replace("&", ""): b for b in d.findChildren(QPushButton)}
    assert set(btn) == {"Add", "Remove", "Edit...", "Sort", "Favor", "Close", "Connect"}
    click = lambda name: QTest.mouseClick(btn[name], Qt.MouseButton.LeftButton)

    click("Sort")
    assert [n.name for n in win.cfg.networks] == ["Aaa", "SkinIRC"]
    d.list.setCurrentRow(0)
    click("Favor")
    assert win.cfg.networks[0].favorite
    d.fav.setChecked(True)
    assert d.list.count() == 1
    d.fav.setChecked(False)

    # Edit saves what is typed, and the password never shows in the field's text mode
    edits = []
    real_exec = NetworkEditDialog.exec
    def fake_exec(dlg):
        edits.append(dlg)
        assert dlg.password.echoMode().name == "Password"
        dlg.servers.setPlainText("irc.new.my/+7000")
        dlg.sasl_user.setText("acct")
        dlg.accept()
        return 1
    monkeypatch.setattr(NetworkEditDialog, "exec", fake_exec)
    click("Edit...")
    assert edits
    a = win.cfg.networks[0]
    assert (a.servers[0].host, a.servers[0].port, a.servers[0].ssl, a.sasl_user) == ("irc.new.my", 7000, True, "acct")

    monkeypatch.setattr(QInputDialog, "getText", lambda *x, **k: ("Fresh", True))
    click("Add")
    assert win.cfg.networks[0].name == "Fresh"
    click("Remove")
    assert "Fresh" not in [n.name for n in win.cfg.networks]

    # Connect joins the selected network and closes the list
    d.list.setCurrentRow([n.name for n in win.cfg.networks].index("SkinIRC"))
    click("Connect")
    assert wait(app, lambda: "SkinIRC" in win.sessions and win.sessions["SkinIRC"].state == "connected")
    assert not d.isVisible()
    win.close(); srv.stop()

    d2 = NetworkListDialog(win)
    d2.show()
    QTest.mouseClick({b.text().replace("&", ""): b for b in d2.findChildren(QPushButton)}["Close"], Qt.MouseButton.LeftButton)
    assert not d2.isVisible()
    d3 = NetworkListDialog(win)
    d3.show()
    QTest.mouseClick(d3.titlebar.lights[0], Qt.MouseButton.LeftButton)
    assert not d3.isVisible()


def test_wrong_password_stops_retrying(app, tmp_path):
    srv = FakeIrcd(refuse=True)
    win, net = make_win(tmp_path, srv.port, password="wrong")
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "disconnected" and any("refused this login" in l.text for l in s.server_buffer.lines))
    wait(app, lambda: False, 200)
    assert not s._reconnect.isActive() and not s.want_connected
    assert sum(x.startswith("USER") for x in srv.received) == 1
    win.close(); srv.stop()


def test_session_limit_stops_retrying(live):
    app, srv, win, s = live
    srv.send(":OperServ!s@services.my NOTICE Badaboom :The session limit for your IP 192.168.50.1 has been exceeded.")
    assert wait(app, lambda: any("will not retry" in l.text for l in s.server_buffer.lines))
    srv.client.close()
    assert wait(app, lambda: s.state == "disconnected")
    wait(app, lambda: False, 200)
    assert not s._reconnect.isActive()


def type_cmd(win, text):
    win.input.setText(text)
    QTest.keyClick(win.input, Qt.Key.Key_Return)


def test_server_command_replaces_a_failing_login(app, tmp_path):
    """The reported bug: /server was sent to ZNC, and BChat kept retrying ZNC."""
    bad = FakeIrcd(refuse=True)
    good = FakeIrcd()
    win, net = make_win(tmp_path, bad.port, password="secret-old")
    win.cfg.networks[0].autojoin = "#old"
    s = win.connect_network(net)
    assert wait(app, lambda: any(x.startswith("USER") for x in bad.received))
    assert wait(app, lambda: s.state == "disconnected")
    type_cmd(win, f"/server 127.0.0.1 {good.port}")
    assert wait(app, lambda: s.state == "connected")
    assert s.nick == "Badaboom" and "NICK Badaboom" in good.received
    assert not any(x.upper().startswith("SERVER") for x in bad.received)
    assert not any(x.startswith("PASS") for x in good.received)   # the old network's password must not travel
    assert not any(x.startswith("JOIN") for x in good.received)
    assert s.server_buffer.name == "127.0.0.1"
    assert win.windowTitle().startswith("BChat: Badaboom @ irc.fake.org")
    assert win.cfg.networks[0].password == "secret-old"           # saved network stays as it was
    assert win.cfg.networks[0].name == "SkinIRC" and "SkinIRC" not in win.sessions and "127.0.0.1" in win.sessions
    win.close(); bad.stop(); good.stop()


def test_server_command_leaves_a_live_server_and_its_channels(live):
    app, srv, win, s = live
    other = FakeIrcd()
    type_cmd(win, f"/server 127.0.0.1 {other.port} letmein")
    assert wait(app, lambda: "NICK Badaboom" in other.received)
    assert wait(app, lambda: s.state == "connected" and "PASS letmein" in other.received)
    assert any(x.startswith("QUIT") for x in srv.received)
    assert s.buffers == {} and win.buf is s.server_buffer
    other.stop()


def test_newserver_opens_its_own_tab(live):
    app, srv, win, s = live
    other = FakeIrcd()
    type_cmd(win, f"/newserver 127.0.0.1 {other.port}")
    assert wait(app, lambda: "NICK Badaboom" in other.received)
    assert s.state == "connected" and "127.0.0.1" in win.sessions and win.session is win.sessions["127.0.0.1"]
    assert win.tree.topLevelItemCount() == 2
    win.sessions["127.0.0.1"].disconnect_from_network()
    other.stop()


def test_server_command_with_no_tab_open(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, 1)
    assert win.buf is None
    type_cmd(win, f"/server 127.0.0.1 {srv.port}")
    assert wait(app, lambda: "NICK Badaboom" in srv.received)
    win.close(); srv.stop()


def test_status_strip_follows_connection_and_op(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    theme = win.cfg.theme
    assert win.status_info()[0] == "off"
    s = win.connect_network(net)
    assert win.status_info()[0] == "connecting"
    assert win._status_colour == theme.status_connecting
    assert wait(app, lambda: s.state == "connected")
    assert win.status_info()[0] == "on" and win._status_colour == theme.status_on
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: lower("Badaboom") in b.users)
    srv.send(":Fhazal!f@h MODE #skinhead +o Badaboom")
    assert wait(app, lambda: win.status_info()[0] == "op")
    assert win._status_colour == theme.status_op
    assert "op in #skinhead" in win.status_info()[1]
    win.select_buffer(s.server_buffer)                # op is per channel
    assert win.status_info()[0] == "on"
    win.select_buffer(b)
    srv.send(":Fhazal!f@h MODE #skinhead -o Badaboom")
    assert wait(app, lambda: win.status_info()[0] == "on")
    srv.send(":Fhazal!f@h MODE #skinhead +v Badaboom")   # voice stays green
    assert wait(app, lambda: "+" in b.users[lower("Badaboom")].prefixes)
    assert win.status_info()[0] == "on"
    srv.client.close()
    assert wait(app, lambda: s.state == "disconnected")
    assert win.status_info()[0] == "off" and win._status_colour == theme.status_off
    s.disconnect_from_network()
    win.close(); srv.stop()


def test_status_strip_lag_beats_op_and_recovers(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    srv.send(":Fhazal!f@h MODE #skinhead +o Badaboom")
    assert wait(app, lambda: win.status_info()[0] == "op")
    s.lag_ms = 42
    assert "lag 42 ms" in win.status_info()[1] and win.status_info()[0] == "op"
    s.lag_ms = 6000                                       # measured high lag
    assert win.status_info()[0] == "lag"
    win._refresh_status()
    assert win._status_colour == win.cfg.theme.status_lag
    s.lag_ms = 10
    s._ping_sent = time.time() - 7                        # a ping nobody has answered yet
    assert win.status_info()[0] == "lag"
    s._ping_sent = 0.0
    s.lag_ms = 10
    assert win.status_info()[0] == "op"
    # a real ping and pong clear it and give a real number
    s._tick()
    assert wait(app, lambda: s._ping_sent == 0.0)
    assert s.lag_ms < 5000 and win.status_info()[0] == "op"


def test_oldest_unanswered_ping_keeps_counting(live):
    app, srv, win, s = live
    s._ping_sent = time.time() - 3
    first = s._ping_sent
    s._tick()
    assert s._ping_sent == first


def test_status_tooltip_cannot_carry_markup(live):
    app, srv, win, s = live
    s.server_name = "<img src=x>"
    win._refresh_status()
    tip = win.status_strip.toolTip()
    assert "<img" not in tip and "&lt;img" in tip


def test_server_tab_opens_an_empty_tab_not_the_network_list(live):
    app, srv, win, s = live
    first = win.buf
    new = next(x for m in win.menubar_.actions() for x in m.menu().actions() if x.menu() and x.text() == "&New")
    tab = next(x for x in new.menu().actions() if x.text() == "Server Tab...")
    tab.trigger()
    assert QApplication.activeModalWidget() is None
    assert win.tree.topLevelItemCount() == 2
    b = win.buf
    assert b is not first and b.name == "<none>"
    assert win.windowTitle() == "BChat" and win.status_info() == ("off", "Not connected")
    assert "/server" in b.lines[-1].text
    assert s.state == "connected"                      # the other server is untouched
    tab.trigger()                                      # a second empty tab gets its own row
    assert win.tree.topLevelItemCount() == 3


def test_typing_server_in_the_empty_tab_connects_only_that_tab(live):
    app, srv, win, s = live
    other = FakeIrcd()
    t = win.new_server_tab()
    type_cmd(win, f"/server 127.0.0.1 {other.port}")
    assert wait(app, lambda: t.state == "connected")
    assert t.server_buffer.name == "127.0.0.1" and "<none>" not in win.sessions
    assert s.state == "connected" and not any(x.startswith("QUIT") for x in srv.received)
    assert win.tree.topLevelItemCount() == 2
    t.disconnect_from_network()
    other.stop()


def test_empty_tab_explains_itself_instead_of_failing_silently(live):
    app, srv, win, s = live
    t = win.new_server_tab()
    for text in ("hello", "/join #x", "/whois me"):
        type_cmd(win, text)
        assert "no server yet" in t.server_buffer.lines[-1].text, text
    assert t.state == "disconnected"
    t.reconnect()
    assert "no server yet" in t.server_buffer.lines[-1].text
    assert not t._reconnect.isActive() and not t.want_connected
    win.close_buffer(t.server_buffer)
    assert win.tree.topLevelItemCount() == 1


def test_whois_country_and_server_special_lines_stay_in_whois(live):
    """Reported: the country line landed on the server tab."""
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    before = len(s.server_buffer.lines)
    s.whois("Fhazal")
    srv.send(":srv 344 Badaboom Fhazal MY :is connecting from Malaysia")
    srv.send(":srv 310 Badaboom Fhazal :looks very helpful")
    srv.send(":srv 318 Badaboom Fhazal :End of /WHOIS list.")
    assert wait(app, lambda: any("Malaysia" in strip_format(l.text) for l in b.lines))
    assert wait(app, lambda: any("very helpful" in strip_format(l.text) for l in b.lines))
    line = next(l for l in b.lines if "Malaysia" in l.text)
    assert line.kind == WHOIS and strip_format(line.text) == "[Fhazal] is connecting from Malaysia"
    assert not any("Malaysia" in l.text for l in s.server_buffer.lines[before:])
    assert b.users[lower("Fhazal")].country == "Malaysia"


def test_unrelated_numerics_do_not_join_a_whois(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    s.whois("Fhazal")
    srv.send(":srv 251 Badaboom :There are 5 users")
    assert wait(app, lambda: any("There are 5 users" in l.text for l in s.server_buffer.lines))
    assert not any("There are 5" in l.text for l in b.lines)


def test_silent_whois_keeps_server_country_for_the_panel(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    u = b.users[lower("Oracle")]
    n = len(b.lines)
    s.silent_whois("Oracle")
    srv.send(":srv 344 Badaboom Oracle MY :is connecting from Malaysia")
    assert wait(app, lambda: u.country == "Malaysia" or not s._silent_whois)
    wait(app, lambda: not s._silent_whois)
    assert not any("Malaysia" in l.text for l in b.lines[n:] + s.server_buffer.lines[-3:])


def test_every_enabled_menu_item_runs(live):
    """Full button check: trigger each enabled menu action; anything that opens a dialog gets closed."""
    from PySide6.QtCore import QTimer
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    skip = {"&Quit", "&Close", "&Disconnect", "&Reconnect", "&Import XChat Settings..."}
    seen = []

    def close_popups():
        w = QApplication.activeModalWidget()
        if w is not None:
            w.close() if not isinstance(w, QDialog) else w.reject()

    def walk(menu):
        for a in menu.actions():
            if a.menu():
                walk(a.menu())
            elif not a.isSeparator() and a.isEnabled() and a.text() not in skip:
                seen.append(a.text())
                if a.isCheckable():
                    a.toggle(); a.toggle()
                else:
                    t = QTimer(); t.setSingleShot(True); t.timeout.connect(close_popups); t.start(50)
                    a.trigger()
                app.processEvents()
    for top in win.menubar_.actions():
        walk(top.menu())
    assert "Network Li&st..." in seen and "C&lear Text" in seen and "&About" in seen
    assert s.state == "connected"
    for d in win.findChildren(QDialog):
        d.close()
