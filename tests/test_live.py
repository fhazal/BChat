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
    assert any(l.left == "Badaboom" and l.kind == "self" and l.text == "hello all" for l in b.lines)
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
    ssl = [l.text for l in s.server_buffer.lines if l.left == "SSL"]
    assert ssl[0].startswith("Protocol: TLS") and "Cipher: " in ssl[0]
    assert ssl[1].startswith("Issuer: ") and "Subject: " in ssl[1] and "CN=" in ssl[1]
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
    assert win.titlebar.logo.height() == 16
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


def test_server_tab_flows_like_adiirc(live):
    """Server tab: stamp, one space, marker, one space, text. Long names are never cut or padded."""
    app, srv, win, s = live
    b = s.server_buffer
    win.select_buffer(b)
    srv.send(":chat.bajubesi.org NOTICE Badaboom :*** Global -- from OperServ")
    srv.send(":srv 372 Badaboom :- Welcome to Irc.Bajubesi.Com.My")
    assert wait(app, lambda: any("Welcome to Irc" in l.text for l in b.lines))
    text = win.chat.doc_for(b).toPlainText().split(chr(10))
    assert len(text) == len(b.lines)
    assert any(t.endswith("] -chat.bajubesi.org- *** Global -- from OperServ") for t in text)
    assert any(t.endswith("] - Welcome to Irc.Bajubesi.Com.My") for t in text)
    assert not any(chr(9) in t for t in text)


def test_channel_tab_is_inline_with_no_line_or_drag(live):
    """User's choice (A): nick follows the time, no column, no line, nothing to drag; wraps sit under the text."""
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    win.resize(700, 500)
    srv.send(":" + "n" * 40 + "!u@h PRIVMSG #skinhead :long nick")
    srv.send(":Belon!b@h PRIVMSG #skinhead :" + "word " * 60)
    assert wait(app, lambda: any(l.text.startswith("word") for l in b.lines))
    text = win.chat.doc_for(b).toPlainText().split(chr(10))
    assert any(t.endswith("] " + "n" * 40 + " long nick") for t in text)   # never cut, never padded
    assert not any(chr(9) in t for t in text)
    assert not hasattr(win.chat, "has_sep") and not hasattr(win.chat, "_drag_x")
    # the long message wraps, and its second row starts under its own text, not under the time
    d = win.chat.document()
    blk = d.begin()
    while not blk.text().endswith("word "):
        blk = blk.next()
    lay = blk.layout()
    assert lay.lineCount() > 1
    head = win.chat.fm.horizontalAdvance(blk.text()[:blk.text().index("Belon ") + len("Belon ")])
    assert abs(lay.lineAt(1).x() - head) <= 2


def test_nick_list_only_shows_on_channel_tabs(live):
    """Server status gets the full width, like XChat."""
    app, srv, win, s = live
    ch = s.buffers["#skinhead"]
    win.select_buffer(ch)
    wait(app, lambda: False, 30)
    assert win.right_panel.isVisible()
    width_in_channel = win.chat.viewport().width()
    win.select_buffer(s.server_buffer)
    wait(app, lambda: False, 30)
    assert not win.right_panel.isVisible()
    assert win.chat.viewport().width() > width_in_channel
    win.select_buffer(s.buffer("Belon"))
    wait(app, lambda: False, 30)
    assert not win.right_panel.isVisible()
    win.select_buffer(ch)
    wait(app, lambda: False, 30)
    assert win.right_panel.isVisible()
    assert win.chat.viewport().width() == width_in_channel
    # the View menu's choice still wins on channel tabs
    win._toggle_userlist(False)
    assert not win.right_panel.isVisible()
    win._toggle_userlist(True)
    assert win.right_panel.isVisible()


def test_mistyped_server_name_does_not_retry_forever(app, tmp_path):
    """Reported from a screenshot: a typo in /server retried every 10 seconds."""
    win, net = make_win(tmp_path, 1)
    t = win.new_server_tab()
    type_cmd(win, "/server no-such-host.invalid +5599")
    assert wait(app, lambda: any("will not retry" in l.text for l in t.server_buffer.lines), 15000), [l.text for l in t.server_buffer.lines]
    assert wait(app, lambda: t.state == "disconnected")
    assert not t._reconnect.isActive() and not t.want_connected
    win.close()


def test_saved_network_still_retries_if_dns_blips(app, tmp_path):
    win, net = make_win(tmp_path, 1)
    net.servers = [Server("no-such-host.invalid", 5599, True)]
    s = win.connect_network(net)
    assert wait(app, lambda: s._reconnect.isActive(), 15000)
    s.disconnect_from_network()
    win.close()


def test_modes_with_values_keep_every_later_argument_right(live):
    """Group C modes like +l take a value only when set. Reading this wrong shifts the +o nick below it."""
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: lower("Oracle") in b.users)
    srv.send(":Fhazal!f@h MODE #skinhead -l+o Oracle")
    assert wait(app, lambda: "@" in b.users[lower("Oracle")].prefixes)
    srv.send(":Fhazal!f@h MODE #skinhead +lo 25 Belon_skd")
    assert wait(app, lambda: "@" in b.users[lower("Belon_skd")].prefixes)
    assert "l" in b.modes and b.mode_args["l"] == "25"
    srv.send(":Fhazal!f@h MODE #skinhead -k+v thekey Oracle")   # k carries its value when removed too
    assert wait(app, lambda: "+" in b.users[lower("Oracle")].prefixes)


def test_title_shows_channel_modes_with_values_in_server_order(live):
    """As XChat's title: (+fnrtP [25j#R5,40m#M15,8n#N15]:10)."""
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: any("modes: +nt" in l.text for l in b.lines))   # the join's own mode reply is in
    s.modes_on_set = "fjl"
    srv.send(":srv 324 Badaboom #skinhead +fnrtP [25j#R5,40m#M15,8n#N15]:10")
    assert wait(app, lambda: "+fnrtP [25j#R5,40m#M15,8n#N15]:10" in win.windowTitle()), win.windowTitle()
    srv.send(":Fhazal!f@h MODE #skinhead -f")
    assert wait(app, lambda: "+nrtP" in win.windowTitle() and "[25j" not in win.windowTitle())


def test_asking_about_another_channel_does_not_open_a_tab(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    n = len(s.buffers)
    srv.send(":srv 332 Badaboom #other :their topic")
    srv.send(":srv 333 Badaboom #other Fhazal 1700000000")
    srv.send(":srv 353 Badaboom = #other :a b c")
    srv.send(":srv 366 Badaboom #other :End")
    assert wait(app, lambda: any("Names on #other" in l.text for l in s.buffers["#skinhead"].lines))
    assert len(s.buffers) == n
    assert any("their topic" in l.text for l in s.buffers["#skinhead"].lines)


def test_msg_stays_in_the_current_tab_and_hides_passwords(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    n = len(s.buffers)
    type_cmd(win, "/msg Belon hello")
    assert wait(app, lambda: "PRIVMSG Belon hello" in srv.received or "PRIVMSG Belon :hello" in srv.received)
    assert len(s.buffers) == n and any(l.left == ">Belon<" and l.text == "hello" for l in b.lines)
    type_cmd(win, "/msg NickServ IDENTIFY hunter2")
    assert wait(app, lambda: any("IDENTIFY hunter2" in x for x in srv.received))
    assert not any("hunter2" in l.text for l in b.lines)
    assert not any("hunter2" in l for l in win.raw_lines)
    type_cmd(win, "/id hunter3")
    assert wait(app, lambda: any("IDENTIFY hunter3" in x for x in srv.received))
    assert not any("hunter3" in l for l in win.raw_lines)


def test_join_adds_the_hash_like_xchat(live):
    app, srv, win, s = live
    type_cmd(win, "/join newroom")
    assert wait(app, lambda: "JOIN #newroom" in srv.received)
    assert wait(app, lambda: win.buf is s.buffers.get("#newroom"))


def test_default_xchat_aliases(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    for typed, expect in (("/umode +i", "MODE Badaboom +i"), ("/banlist", "MODE #skinhead +b"), ("/uptime", "STATS u"),
                          ("/wii Oracle", "WHOIS Oracle Oracle"), ("/m Belon hey", "PRIVMSG Belon"), ("/kill Bad Bye now", "KILL Bad :Bye now")):
        s._next_send = 0.0   # the send pacing would otherwise stretch this test past its wait
        type_cmd(win, typed)
        assert wait(app, lambda: any(x.startswith(expect) for x in srv.received)), typed
    s.buffers["#skinhead"].lines.clear()
    type_cmd(win, "/ver")
    assert "needs more" in s.buffers["#skinhead"].lines[-1].text
    s._next_send = 0.0
    type_cmd(win, "/ame waves")
    assert wait(app, lambda: any("ACTION waves" in x for x in srv.received))
    assert not any(x.endswith("me waves") for x in srv.received)
    s._next_send = 0.0
    type_cmd(win, "/allchan say hello all")
    assert wait(app, lambda: any(x.startswith("PRIVMSG #skinhead") and "hello all" in x for x in srv.received))


def test_ignore_hides_a_person_and_can_be_undone(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    type_cmd(win, "/ignore Pest")
    assert s.cfg.ignores == ["Pest!*@*"]
    srv.send(":Pest!p@h PRIVMSG #skinhead :spam spam")
    srv.send(":Pest!p@h NOTICE Badaboom :spam notice")
    srv.send(":Pest!p@h PRIVMSG Badaboom :spam private")
    srv.send(":Belon!b@h PRIVMSG #skinhead :real")
    assert wait(app, lambda: any(l.text == "real" for l in b.lines))
    assert not any("spam" in l.text for x in s.all_buffers() for l in x.lines)
    assert "pest" not in s.buffers
    type_cmd(win, "/unignore Pest")
    srv.send(":PEST!p@h PRIVMSG #skinhead :back again")
    assert wait(app, lambda: any(l.text == "back again" for l in b.lines))


def test_mass_op_splits_by_the_servers_mode_limit(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    srv.received.clear()
    s.max_modes = 2
    s.set_mode_for(b, "+o", ["a", "b", "c"])
    assert wait(app, lambda: "MODE #skinhead -o" not in srv.received and any(x.startswith("MODE #skinhead +o c") for x in srv.received))
    assert "MODE #skinhead +oo a b" in srv.received


def test_highlight_flash_ping_reply_and_dcc_message(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    seen = []
    s.alert.connect(seen.append)
    srv.send(":Belon!b@h PRIVMSG #skinhead :Badaboom look")
    assert wait(app, lambda: seen and seen[0] is b)
    srv.send(f":Belon!b@h NOTICE Badaboom :\x01PING {int(time.time()) - 3}\x01")
    assert wait(app, lambda: any("Ping reply from Belon" in l.text for l in b.lines))
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND a.zip 1 2 3\x01")
    assert wait(app, lambda: any("offered" in l.text for l in b.lines))


def test_quit_and_nick_show_in_private_tab(live):
    app, srv, win, s = live
    q = s.buffer("Belon")
    srv.send(":Belon!b@h NICK :Belon2")
    assert wait(app, lambda: "belon2" in s.buffers and any("known as Belon2" in l.text for l in q.lines))
    srv.send(":Belon2!b@h QUIT :bye")
    assert wait(app, lambda: any("has quit" in l.text for l in q.lines))


def test_input_keys_complete_and_format(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    i = win.input
    i.clear(); i.setText("/whoi"); QTest.keyClick(i, Qt.Key.Key_Tab)
    assert i.text() == "/whois "
    i.clear(); i.setText("/whoi"); QTest.keyClick(i, Qt.Key.Key_Tab)   # again after the text was replaced
    assert i.text() == "/whois "
    i.clear(); i.setText("#sk"); QTest.keyClick(i, Qt.Key.Key_Tab)
    assert i.text() == "#skinhead "
    i.clear(); i.setText("Ora"); QTest.keyClick(i, Qt.Key.Key_Tab)
    assert i.text() == "Oracle: "
    i.clear()
    QTest.keyClick(i, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    assert i.text() == "\x02"
    i.clear()
    for n in range(80):
        s.add(s.buffers["#skinhead"], "msg", "x", f"line {n}")
    bar = win.chat.verticalScrollBar()
    wait(app, lambda: False, 30)
    end = bar.value()
    QTest.keyClick(i, Qt.Key.Key_PageUp)
    assert bar.value() < end
    QTest.keyClick(i, Qt.Key.Key_PageDown)
    assert bar.value() == end


def test_multi_line_paste_sends_messages_never_commands(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    QApplication.clipboard().setText("first line\n/quit\nthird")
    win.input.clear()
    QTest.keyClick(win.input, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert wait(app, lambda: "PRIVMSG #skinhead third" in srv.received or "PRIVMSG #skinhead :third" in srv.received, 8000), srv.received[-4:]
    assert "PRIVMSG #skinhead /quit" in srv.received or "PRIVMSG #skinhead :/quit" in srv.received
    assert not any(x.startswith("QUIT") for x in srv.received)
    assert s.state == "connected"


def test_chat_right_click_offers_nick_link_and_channel(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    win.chat.word_at = lambda pos: "Oracle"
    win.chat.anchorAt = lambda pos: ""
    assert [a.text() for a in win._chat_menu(QPoint(1, 1)).actions() if not a.isSeparator()][0] == "Oracle"
    win.chat.word_at = lambda pos: "#other"
    assert win._chat_menu(QPoint(1, 1)).actions()[0].text() == "Join #other"
    win.chat.word_at = lambda pos: "plain"
    win.chat.anchorAt = lambda pos: "https://a.my/x"
    labels = [a.text() for a in win._chat_menu(QPoint(1, 1)).actions()]
    assert labels[0] == "Open Link in Browser" and "Copy Link" in labels and "Clear Text" in labels
    win.chat.anchorAt = lambda pos: ""
    assert win._chat_menu(QPoint(1, 1)).actions()[0].text() == "Copy Selection"
    win._join_clicked("#clicked")
    assert wait(app, lambda: "JOIN #clicked" in srv.received)


def test_real_word_under_the_mouse(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    s.add(b, "msg", "x", "see [Oracle], ok")
    wait(app, lambda: False, 50)
    cur = win.chat.document().begin()
    while "see [Oracle]" not in cur.text():
        cur = cur.next()
    rect = win.chat.document().documentLayout().blockBoundingRect(cur)
    y = int(rect.top() - win.chat.verticalScrollBar().value() + 5)
    x = int(rect.left() + win.chat.document().documentMargin()) + win.chat.fm.horizontalAdvance(cur.text()[:cur.text().index("see [Or") + 7])
    assert win.chat.word_at(QPoint(x, y)) == "Oracle"


def test_logging_is_per_tab_and_stays_in_the_logs_folder(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    win._set_logging(b, True)
    srv.send(":Belon!b@h PRIVMSG #skinhead :\x02logged\x02 line")
    assert wait(app, lambda: win.log_path(b).exists() and "logged line" in win.log_path(b).read_text(encoding="utf-8"))
    win._set_logging(b, False)
    srv.send(":Belon!b@h PRIVMSG #skinhead :not logged")
    assert wait(app, lambda: any(l.text == "not logged" for l in b.lines))
    assert "not logged" not in win.log_path(b).read_text(encoding="utf-8")
    evil = s.buffer("#../../evil")
    assert (tmp_path / "logs") in win.log_path(evil).parents
    assert ".." not in win.log_path(evil).parts
    win.close(); srv.stop()


def test_window_and_panes_are_remembered(app, tmp_path):
    from bchat import config
    win, _ = make_win(tmp_path, 1)
    win.resize(800, 500)
    win.split.setSizes([160, 500, 140])
    wait(app, lambda: False, 30)
    win.close()
    back = config.load(tmp_path)
    assert back.win_width == 800 and back.pane_left > 120 and not back.win_maximized
    win2 = MainWindow(back, tmp_path)
    win2.skip_quit_prompt = True
    win2.show()
    wait(app, lambda: False, 30)
    assert win2.split.sizes()[0] > 120
    win2.close()


def test_closing_a_server_tab_with_channels_asks_first(live, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app, srv, win, s = live
    win.skip_quit_prompt = False
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.No)[1])
    win.close_buffer(s.server_buffer)
    assert asked and "channels" in asked[0] and s.state == "connected" and "SkinIRC" in win.sessions
    win.skip_quit_prompt = True


def test_own_nick_greys_while_away(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    srv.send(":srv 306 Badaboom :You have been marked as being away")
    assert wait(app, lambda: win.cfg.theme.away in win.nick_label.styleSheet())
    srv.send(":srv 305 Badaboom :You are no longer marked as being away")
    assert wait(app, lambda: win.nick_label.styleSheet() == "")


def test_tab_greys_when_disconnected(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    srv.client.close()
    assert wait(app, lambda: s.state == "disconnected")
    assert win.items[id(b)].foreground(0).color().name() == win.cfg.theme.away
    s.disconnect_from_network()


def test_every_tab_keeps_the_chat_font(live):
    """Reported from a mockup: the server tab showed the UI font until something rebuilt it."""
    app, srv, win, s = live
    for b in (s.server_buffer, s.buffers["#skinhead"], s.server_buffer):
        win.select_buffer(b)
        wait(app, lambda: False, 20)
        assert win.chat.document().defaultFont().family() == win.chat.chat_font.family()


def prefs(win, change):
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    change(d)
    d.accept()
    d.deleteLater()


def test_prefs_only_unbuilt_pages_are_greyed(app, tmp_path):
    from bchat.preferences import BUILT, PreferencesDialog
    win, _ = make_win(tmp_path, 1)
    d = PreferencesDialog(win)
    for name, item in d._items.items():
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled) == (name in BUILT), name
        if name in BUILT:
            d.show_page(name)
            assert d.title.text() == name
    assert "QTreeWidget::item:disabled" in win.styleSheet() and "QRadioButton::indicator:checked" in win.styleSheet()
    d.reject(); win.close()


def test_prefs_input_box_options(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    prefs(win, lambda d: (d.pct_codes.setChecked(True), d.pct_ascii.setChecked(True)))
    type_cmd(win, "%Bbold%O %065 100%%")
    assert wait(app, lambda: any("\x02bold\x0f A 100%" in x for x in srv.received))
    prefs(win, lambda d: (d.pct_codes.setChecked(False), d.pct_ascii.setChecked(False)))
    s._next_send = 0.0
    type_cmd(win, "%Bplain%O")
    assert wait(app, lambda: any("%Bplain%O" in x for x in srv.received))
    prefs(win, lambda d: d.auto_complete.setChecked(True))
    s._next_send = 0.0
    type_cmd(win, "Orac: hi there")
    assert wait(app, lambda: any("Oracle: hi there" in x for x in srv.received))
    s._next_send = 0.0
    type_cmd(win, "Be: two people fit")    # Belon, Belon_skd... stays as typed
    assert wait(app, lambda: any("Be: two people fit" in x for x in srv.received))
    prefs(win, lambda d: d.auto_complete.setChecked(False))
    # suffix and sort on Tab
    prefs(win, lambda d: d.suffix.setText(","))
    win.input.setText("Orac"); QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text() == "Oracle, "
    win.input.clear()
    b.users[lower("Belon_skd")].last_msg = 100.0
    b.users[lower("Belon")].last_msg = 50.0
    prefs(win, lambda d: d.comp_sort.setCurrentIndex(1))
    win.input.setText("Bel"); QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text().startswith("Belon_skd")
    win.input.clear()
    prefs(win, lambda d: d.comp_sort.setCurrentIndex(0))
    win.input.setText("Bel"); QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text().startswith("Belon,")
    win.input.clear()
    prefs(win, lambda d: d.input_font.setChecked(True))
    assert win.cfg.chat_font in win.input.styleSheet()
    prefs(win, lambda d: d.input_font.setChecked(False))
    assert win.input.styleSheet() == ""


def test_prefs_user_list_options(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: lower("Oracle") in b.users)
    names = lambda: [u.nick for u in win.userlist.model_.users]
    prefs(win, lambda d: d.ul_sort.setCurrentIndex(1))
    assert names() == sorted(names(), key=lower)
    prefs(win, lambda d: d.ul_sort.setCurrentIndex(3))
    assert names() == sorted(names(), key=lower, reverse=True)
    prefs(win, lambda d: d.ul_sort.setCurrentIndex(2))
    assert names()[-1] == "B3L0N[JVN]" or "@" in b.users[lower(names()[-1])].prefixes
    prefs(win, lambda d: d.ul_sort.setCurrentIndex(4))
    assert names() == [u.nick for u in b.users.values()]
    prefs(win, lambda d: d.ul_sort.setCurrentIndex(0))
    assert names()[0] == "B3L0N[JVN]"
    # side moves the panel, and back
    prefs(win, lambda d: d.ul_side.setCurrentIndex(1))
    assert win.split.indexOf(win.right_panel) < win.split.indexOf(win.mid_panel)
    prefs(win, lambda d: d.ul_side.setCurrentIndex(0))
    assert win.split.indexOf(win.right_panel) > win.split.indexOf(win.mid_panel)
    # double-click command
    prefs(win, lambda d: d.ul_double.setText("msg %s hello from double click"))
    rect = win.userlist.visualRect(win.userlist.model().index(6))
    QTest.mouseClick(win.userlist.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(win.userlist.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert wait(app, lambda: any("hello from double click" in x and "Oracle" in x for x in srv.received))
    prefs(win, lambda d: d.ul_double.setText("QUOTE WHOIS %s %s"))
    # away tracking off: nobody greys, polling stops
    assert wait(app, lambda: b.users[lower("Psycho")].away)
    prefs(win, lambda d: d.away_track.setChecked(False))
    srv.send(":Oracle!o@h AWAY :gone")
    assert wait(app, lambda: True)
    wait(app, lambda: False, 100)
    assert not b.users[lower("Oracle")].away
    n = len(srv.received)
    s._poll_who()
    wait(app, lambda: False, 100)
    assert not any(x.startswith("WHO") for x in srv.received[n:])
    prefs(win, lambda d: (d.away_track.setChecked(True), d.away_limit.setValue(5)))
    s._cap_active.discard("away-notify")
    n = len(srv.received)
    s._poll_who()
    wait(app, lambda: False, 100)
    assert not any(x.startswith("WHO") for x in srv.received[n:])   # channel is bigger than the limit
    # hostnames draw and don't break the list
    b.users[lower("Oracle")].host = "o@host.my"
    prefs(win, lambda d: d.ul_hosts.setChecked(True))
    wait(app, lambda: False, 50)
    win.userlist.grab()
    prefs(win, lambda d: d.ul_font.setChecked(True))
    assert win.cfg.chat_font in win.userlist.styleSheet()


def test_prefs_highlight_lists(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    prefs(win, lambda d: (d.hl_extra.setText("radio, skin*"), d.hl_no.setText("Bot*"), d.hl_always.setText("Boss")))
    for sender, words, expect in (("Belon", "the radio is on", "hilite"), ("Belon", "skinhead rules", "hilite"), ("Belon", "nothing here", "msg"),
                                  ("BotOne", "Badaboom radio", "msg"), ("Boss", "anything at all", "hilite")):
        srv.send(f":{sender}!x@h PRIVMSG #skinhead :{words}")
        assert wait(app, lambda: any(l.text == words and l.kind == expect for l in b.lines)), (sender, words, [(l.text, l.kind) for l in b.lines[-3:]])


def test_prefs_alerts_each_kind(live, monkeypatch):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    flashes, beeps = [], []
    monkeypatch.setattr(QApplication, "alert", staticmethod(lambda *a: flashes.append(1)))
    monkeypatch.setattr(QApplication, "beep", staticmethod(lambda: beeps.append(1)))
    monkeypatch.setattr(win, "isActiveWindow", lambda: False)
    def set_boxes(d):
        for key in d.alert_boxes:
            for box in d.alert_boxes[key]:
                box.setChecked(False)
    prefs(win, set_boxes)
    win._on_notify(b, "hilight"); win._on_notify(b, "priv"); win._on_notify(b, "chan")
    assert not flashes and not beeps
    prefs(win, lambda d: d.alert_boxes["alert_flash"][0].setChecked(True))
    win._on_notify(b, "chan"); win._on_notify(b, "priv")
    assert len(flashes) == 1
    prefs(win, lambda d: d.alert_boxes["alert_beep"][2].setChecked(True))
    win._on_notify(b, "hilight"); win._on_notify(b, "chan")
    assert len(beeps) == 1
    monkeypatch.setattr(win, "isActiveWindow", lambda: True)   # looking at the window: no alerts
    flashes.clear(); beeps.clear()
    win._on_notify(b, "chan"); win._on_notify(b, "hilight")
    assert not flashes and not beeps


def test_prefs_tray_icon_blinks_balloons_and_quits(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    prefs(win, lambda d: d.tray_icon.setChecked(True))
    assert win.tray is not None
    shown = []
    win.tray.showMessage = lambda *a: shown.append(a)
    prefs(win, lambda d: (d.alert_boxes["alert_tray"][1].setChecked(True), d.alert_boxes["alert_balloon"][1].setChecked(True)))
    monkeypatch.setattr(win, "isActiveWindow", lambda: False)
    s.add(b, "msg", "Belon", "balloon text")
    win._on_notify(b, "priv")
    assert win._blink_timer.isActive() and shown and "balloon text" in shown[0][1]
    win._stop_blink()
    assert not win._blink_timer.isActive()
    assert [a.text() for a in win.tray.contextMenu().actions() if not a.isSeparator()] == ["Show BChat", "Quit"]
    prefs(win, lambda d: d.tray_icon.setChecked(False))
    assert win.tray is None
    win.close(); srv.stop()


def test_prefs_general_messages_and_away(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: b.joined)
    prefs(win, lambda d: (d.away_msg.setText("gone fishing"), d.announce.setChecked(True), d.auto_unaway.setChecked(True)))
    s._next_send = 0.0
    type_cmd(win, "/away")
    assert wait(app, lambda: any(x.startswith("AWAY") and "gone fishing" in x for x in srv.received))
    assert wait(app, lambda: any("ACTION is away: gone fishing" in x for x in srv.received))
    srv.send(":srv 306 Badaboom :You have been marked as being away")
    assert wait(app, lambda: s.away)
    s._next_send = 0.0
    n = len(srv.received)
    type_cmd(win, "talking now")
    assert wait(app, lambda: any(x.strip() == "AWAY" for x in srv.received[n:]))     # auto-unaway
    prefs(win, lambda d: d.part_msg.setText("bye for now"))
    s._next_send = 0.0
    type_cmd(win, "/part")
    assert wait(app, lambda: any(x.startswith("PART #skinhead") and "bye for now" in x for x in srv.received))
    # away once
    srv.send(":srv 301 Badaboom Belon :out to lunch")
    srv.send(":srv 301 Badaboom Belon :out to lunch")
    srv.send(":srv 301 Badaboom Belon :back at two")
    assert wait(app, lambda: any("back at two" in l.text for l in b.lines))
    assert sum("out to lunch" in l.text for l in b.lines) == 1
    # quit message
    prefs(win, lambda d: d.quit_msg.setText("see you"))
    s.disconnect_from_network()
    assert wait(app, lambda: any(x.startswith("QUIT") and "see you" in x for x in srv.received))


def test_prefs_logging_all_mask_stamps_and_replay(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    prefs(win, lambda d: (d.log_all.setChecked(True), d.log_mask.setText("%n/%c-log.txt"), d.log_fmt.setText("<%H> "), d.replay.setChecked(True)))
    srv.send(":Belon!b@h PRIVMSG #skinhead :first logged line")
    path = win.log_path(b)
    assert path.name == "#skinhead-log.txt" and path.parent.name == "SkinIRC" and (tmp_path / "logs") in path.parents
    assert wait(app, lambda: path.exists() and "first logged line" in path.read_text(encoding="utf-8"))
    last = [x for x in path.read_text(encoding="utf-8").split("\n") if "first logged line" in x][0]
    assert last.startswith("<") and "Belon" in last
    prefs(win, lambda d: d.log_stamps.setChecked(False))
    srv.send(":Belon!b@h PRIVMSG #skinhead :second logged line")
    assert wait(app, lambda: "second logged line" in path.read_text(encoding="utf-8"))
    assert [x for x in path.read_text(encoding="utf-8").split("\n") if "second logged line" in x][0].startswith("Belon")
    prefs(win, lambda d: d.log_mask.setText("../../evil-%c.log"))
    assert (tmp_path / "logs") in win.log_path(b).parents
    win.close(); srv.stop()
    # a new run shows the last session's lines when the tab opens
    srv2 = FakeIrcd()
    from bchat import config
    cfg = config.load(tmp_path)
    cfg.networks[0].servers[0].port = srv2.port
    win2 = MainWindow(cfg, tmp_path)
    win2.skip_quit_prompt = True
    win2.show()
    s2 = win2.connect_network(cfg.networks[0])
    assert wait(app, lambda: "#skinhead" in s2.buffers)
    assert any(l.text == "first logged line" for l in s2.buffers["#skinhead"].lines)
    assert "first logged line" in win2.chat.doc_for(s2.buffers["#skinhead"]).toPlainText()
    win2.close(); srv2.stop()


def test_prefs_sound_plays_the_right_file(live, monkeypatch):
    app, srv, win, s = live
    played = []
    monkeypatch.setattr(win, "_play_sound", lambda kind: played.append(kind))
    b = s.buffers["#skinhead"]
    srv.send(":New!n@h JOIN #skinhead")
    srv.send(":Belon!b@h PRIVMSG #skinhead :hello")
    srv.send(":Belon!b@h PRIVMSG Badaboom :private")
    srv.send(":Belon!b@h PRIVMSG #skinhead :Badaboom look")
    srv.send(":Belon!b@h NOTICE Badaboom :a notice")
    for kind in ("join", "chan", "priv", "hilight", "notice"):
        assert wait(app, lambda: kind in played), (kind, played)
    win.cfg.sounds = {}
    monkeypatch.undo()
    prefs(win, lambda d: d.sound_edits["join"].setText("C:/Windows/Media/ding.wav"))
    assert win.cfg.sounds == {"join": "C:/Windows/Media/ding.wav"}
    win._play_sound("join")      # real call, async, and a missing event does nothing
    win._play_sound("kick")


def test_prefs_advanced_reconnect_raw_modes_hide_joins(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: lower("Oracle") in b.users)
    prefs(win, lambda d: (d.raw_modes.setChecked(True), d.hide_jp.setChecked(True), d.reconnect.setValue(33)))
    srv.send(":Fhazal!f@h MODE #skinhead +o Oracle")
    assert wait(app, lambda: any(l.text == "Fhazal sets mode +o Oracle" for l in b.lines))
    assert "@" in b.users[lower("Oracle")].prefixes
    srv.send(":Nobody!n@h JOIN #skinhead")
    assert wait(app, lambda: lower("Nobody") in b.users)
    assert not any("Nobody" in l.text for l in b.lines)
    srv.send(":Nobody!n@h PART #skinhead :x")
    assert wait(app, lambda: lower("Nobody") not in b.users)
    assert not any("Nobody" in l.text for l in b.lines)
    srv.client.close()
    assert wait(app, lambda: s.state == "disconnected")
    assert s._reconnect.interval() == 33000 and any("33 seconds" in l.text for l in s.server_buffer.lines)
    s.disconnect_from_network()


def test_prefs_network_bind_and_real_socks5_proxy(app, tmp_path):
    import socket, struct, threading
    target = FakeIrcd()
    seen = []
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(1)
    proxy_port = listener.getsockname()[1]

    def relay(a, c):
        try:
            while True:
                data = a.recv(4096)
                if not data:
                    break
                c.sendall(data)
        except OSError:
            pass

    def serve():
        conn, _ = listener.accept()
        head = conn.recv(2)
        conn.recv(head[1])
        conn.sendall(b"\x05\x00")
        req = conn.recv(4)
        if req[3] == 1:
            host = socket.inet_ntoa(conn.recv(4))
        else:
            host = conn.recv(conn.recv(1)[0]).decode()
        port = struct.unpack(">H", conn.recv(2))[0]
        seen.append((host, port))
        out = socket.create_connection((host, port))
        conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        threading.Thread(target=relay, args=(conn, out), daemon=True).start()
        relay(out, conn)

    threading.Thread(target=serve, daemon=True).start()
    win, net = make_win(tmp_path, target.port)
    prefs(win, lambda d: (d.proxy_type.setCurrentIndex(1), d.proxy_host.setText("127.0.0.1"), d.proxy_port.setValue(proxy_port)))
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), [l.text for l in s.server_buffer.lines]
    assert seen == [("127.0.0.1", target.port)]
    s.disconnect_from_network()
    assert wait(app, lambda: s.state == "disconnected")
    prefs(win, lambda d: (d.proxy_type.setCurrentIndex(0), d.bind.setText("127.0.0.2")))     # really leaves from this address
    s.connect_to_network()
    assert wait(app, lambda: s.sock.state() == s.sock.SocketState.ConnectedState, 5000), [l.text for l in s.server_buffer.lines[-4:]]
    assert s.sock.localAddress().toString() == "127.0.0.2"
    s.disconnect_from_network()
    assert wait(app, lambda: s.sock.state() == s.sock.SocketState.UnconnectedState)
    prefs(win, lambda d: d.bind.setText("203.0.113.9"))   # an address this PC doesn't have
    s.connect_to_network()
    assert wait(app, lambda: any("Couldn't use the address" in l.text for l in s.server_buffer.lines), 5000)
    s.disconnect_from_network()
    win.close(); target.stop(); listener.close()


def test_prefs_all_new_settings_survive_restart(app, tmp_path):
    from bchat import config
    win, _ = make_win(tmp_path, 1)
    prefs(win, lambda d: (d.suffix.setText(","), d.ul_sort.setCurrentIndex(3), d.hl_no.setText("x*"), d.quit_msg.setText("q"), d.log_mask.setText("%c.log"),
                          d.sound_edits["kick"].setText("k.wav"), d.reconnect.setValue(7), d.proxy_type.setCurrentIndex(2), d.proxy_host.setText("p"),
                          d.proxy_pass.setText("pw"), d.alert_boxes["alert_beep"][0].setChecked(True), d.bg_image.setText("x.png")))
    back = config.load(tmp_path)
    assert (back.nick_suffix, back.ul_sort, back.hilite_no, back.quit_reason, back.log_mask, back.sounds, back.reconnect_delay, back.proxy_type, back.proxy_host,
            back.proxy_password, back.alert_beep[0], back.chat_bg_image) == (",", 3, "x*", "q", "%c.log", {"kick": "k.wav"}, 7, "http", "p", "pw", True, "x.png")
    win.close()


def test_channel_list_window_every_control(live, tmp_path):
    app, srv, win, s = live
    w = win.open_channel_list(s, download=False)
    srv.send(":srv 321 Badaboom Channel :Users Name")
    assert w.isVisible()
    QTest.mouseClick(w.download_btn, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any(x.strip() == "LIST" for x in srv.received))
    assert not w.download_btn.isEnabled()
    for name, users, topic in (("#alpha", 5, "first \x0304topic"), ("#beta", 50, "second"), ("#gamma", 500, "alpha mention")):
        srv.send(f":srv 322 Badaboom {name} {users} :{topic}")
    srv.send(":srv 323 Badaboom :End of /LIST")
    assert wait(app, lambda: w.view.topLevelItemCount() == 3 and w.download_btn.isEnabled())
    assert "555/555 users on 3/3" in w.status.text()
    # numbers sort as numbers
    w.view.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert [w.view.topLevelItem(i).text(0) for i in range(3)] == ["#alpha", "#beta", "#gamma"]
    assert w.view.topLevelItem(0).text(2) == "first topic"     # colours stripped
    # simple search in both, then only one column
    w.find.setText("alpha"); QTest.mouseClick(w.search_btn, Qt.MouseButton.LeftButton)
    assert w.view.topLevelItemCount() == 2
    w.in_topic.setChecked(False); w.apply_filter()
    assert w.view.topLevelItemCount() == 1
    w.in_topic.setChecked(True); w.in_name.setChecked(False); w.apply_filter()
    assert w.view.topLevelItem(0).text(0) == "#gamma"
    w.in_name.setChecked(True)
    w.kind.setCurrentIndex(1); w.find.setText("#?eta"); w.apply_filter()
    assert w.view.topLevelItem(0).text(0) == "#beta" and w.view.topLevelItemCount() == 1
    w.kind.setCurrentIndex(2); w.find.setText("^#(a|g)"); w.apply_filter()
    assert w.view.topLevelItemCount() == 2
    w.find.setText("(("); w.apply_filter()
    assert "isn't valid" in w.status.text()
    w.kind.setCurrentIndex(0); w.find.setText(""); w.apply_filter()
    w.min_users.setValue(10)
    assert w.view.topLevelItemCount() == 2
    w.max_users.setValue(100)
    assert w.view.topLevelItemCount() == 1 and "50/555" in w.status.text()
    w.min_users.setValue(0); w.max_users.setValue(0)
    assert w.view.topLevelItemCount() == 3
    # save
    out = tmp_path / "list.txt"
    w.save(str(out))
    assert "#gamma" in out.read_text(encoding="utf-8")
    # join, by button and by double click
    w.view.setCurrentItem(w.view.findItems("#beta", Qt.MatchFlag.MatchExactly, 0)[0])
    QTest.mouseClick(w.join_btn, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any(x.startswith("JOIN #beta") for x in srv.received))
    # nothing leaks to the server tab while the window listens
    assert not any("#alpha" in l.text for l in s.server_buffer.lines)
    # /list opens it and asks again
    w.hide()
    n = len(srv.received)
    s._next_send = 0.0
    type_cmd(win, "/list")
    assert w.isVisible() and wait(app, lambda: any(x.strip() == "LIST" for x in srv.received[n:]))
    srv.send(":srv 323 Badaboom :End of /LIST")


def test_ban_list_window_every_control(live, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app, srv, win, s = live
    win.select_buffer(s.server_buffer)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
    assert win.open_ban_list() is None                  # needs a channel tab
    win.select_buffer(s.buffers["#skinhead"])
    w = win.open_ban_list()
    assert wait(app, lambda: any("MODE #skinhead +b" in x for x in srv.received))
    assert w.boxes["e"].isEnabled() and not w.boxes["e"].isChecked()
    for mask in ("a!*@*", "b!*@*", "c!*@*"):
        srv.send(f":srv 367 Badaboom #skinhead {mask} Fhazal!f@h 1700000000")
    srv.send(":srv 368 Badaboom #skinhead :End")
    assert wait(app, lambda: w.view.topLevelItemCount() == 3 and "b" not in w.waiting)
    assert w.view.topLevelItem(0).text(2) == "Fhazal" and "2023" in w.view.topLevelItem(0).text(3)
    assert not any("a!*@*" in l.text for l in s.server_buffer.lines)
    # remove
    w.remove_selected()      # nothing selected: only the message
    w.view.topLevelItem(0).setSelected(True)
    QTest.mouseClick(w.remove_btn, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any("-b" in x and "a!*@*" in x for x in srv.received))
    assert w.view.topLevelItemCount() == 2
    # crop keeps only what's selected
    w.view.clearSelection()
    w.view.topLevelItem(0).setSelected(True)
    s._next_send = 0.0
    QTest.mouseClick(w.crop_btn, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any("-b" in x and "c!*@*" in x for x in srv.received))
    assert w.view.topLevelItemCount() == 1 and w.view.topLevelItem(0).text(1) == "b!*@*"
    s._next_send = 0.0
    w.clear_all(confirm=False)
    assert wait(app, lambda: any("-b" in x and "b!*@*" in x for x in srv.received))
    # exempts, a second list on the same refresh
    n = len(srv.received)
    s._next_send = 0.0
    w.boxes["e"].setChecked(True)
    assert wait(app, lambda: any("MODE #skinhead +e" in x for x in srv.received[n:]))
    srv.send(":srv 348 Badaboom #skinhead ok!*@* Fhazal 1700000000")
    assert wait(app, lambda: w.view.topLevelItemCount() == 1 and w.view.topLevelItem(0).text(0) == "Exempt")
    w.view.topLevelItem(0).setSelected(True)
    s._next_send = 0.0
    w.remove_selected()
    assert wait(app, lambda: any("-e" in x and "ok!*@*" in x for x in srv.received))
    # /banlist with no window still prints
    del s.ban_sinks["#skinhead"]
    srv.send(":srv 367 Badaboom #skinhead plain!*@* Fhazal 1700000000")
    assert wait(app, lambda: any("plain!*@*" in l.text for l in s.server_buffer.lines))


def test_ignore_kinds_stats_and_window(live, monkeypatch):
    from bchat import session as sm
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    w = win.open_tool("ignore")
    w.add("Spam")
    assert win.cfg.ignores == ["Spam!*@*"] and w.view.topLevelItemCount() == 1
    sm.IGNORE_STATS.clear()
    srv.send(":Spam!s@h PRIVMSG #skinhead :chan one")
    srv.send(":Spam!s@h PRIVMSG Badaboom :private one")
    srv.send(":Spam!s@h NOTICE Badaboom :notice one")
    srv.send(":Spam!s@h PRIVMSG Badaboom :\x01VERSION\x01")
    srv.send(":Spam!s@h INVITE Badaboom #x")
    srv.send(":Belon!b@h PRIVMSG #skinhead :marker")
    assert wait(app, lambda: any(l.text == "marker" for l in b.lines))
    assert not any("one" in l.text for l in b.lines) and "spam" not in s.buffers
    w.show_stats()
    assert {k: w.stats[k].text() for k in "CPNTI"} == dict.fromkeys("CPNTI", "1")
    # untick Channel: their channel lines show again, privates stay hidden
    it = w.view.topLevelItem(0)
    it.setCheckState(1, Qt.CheckState.Unchecked)
    assert "C" not in win.cfg.ignore_kinds["Spam!*@*"]
    srv.send(":Spam!s@h PRIVMSG #skinhead :chan two")
    srv.send(":Spam!s@h PRIVMSG Badaboom :private two")
    srv.send(":Belon!b@h PRIVMSG #skinhead :marker2")
    assert wait(app, lambda: any(l.text == "marker2" for l in b.lines))
    assert any(l.text == "chan two" for l in b.lines) and "spam" not in s.buffers
    # Unignore beats a wider mask
    w.add("*!*@badhost")
    win.cfg.ignore_kinds["Good!*@*"] = "U"
    win.cfg.ignores.append("Good!*@*")
    assert s.ignored("Evil!e@badhost", "C") and not s.ignored("Good!g@badhost", "C")
    # edit the mask in place
    w.fill()
    it = w.view.findItems("*!*@badhost", Qt.MatchFlag.MatchExactly, 0)[0]
    it.setText(0, "*!*@verybad")
    assert "*!*@verybad" in win.cfg.ignores and "*!*@badhost" not in win.cfg.ignores
    w.view.setCurrentItem(w.view.findItems("*!*@verybad", Qt.MatchFlag.MatchExactly, 0)[0])
    QTest.mouseClick(w.delete_btn, Qt.MouseButton.LeftButton)
    assert "*!*@verybad" not in win.cfg.ignores
    QTest.mouseClick(w.clear_btn, Qt.MouseButton.LeftButton)
    assert win.cfg.ignores == [] and w.view.topLevelItemCount() == 0
    # /ignore with kinds
    s._next_send = 0.0
    type_cmd(win, "/ignore Bad!*@* PRIV NOTI")
    assert win.cfg.ignore_kinds["Bad!*@*"] == "PN"
    assert s.ignored("Bad!x@y", "P") and not s.ignored("Bad!x@y", "C")


def test_friends_with_ison_and_window(live):
    app, srv, win, s = live
    n = len(srv.received)
    w = win.open_tool("friends")
    w.add("Belon")
    assert wait(app, lambda: any(x.startswith("ISON") and "Belon" in x for x in srv.received[n:]))
    assert w.view.topLevelItem(0).text(1) == "Offline"
    srv.send(":srv 303 Badaboom :Belon")
    assert wait(app, lambda: w.view.topLevelItem(0).text(1) == "Online" and w.view.topLevelItem(0).text(2) == "SkinIRC")
    assert any("Notify: Belon is online (SkinIRC)" in l.text for l in s.server_buffer.lines)
    # no repeat while nothing changes, a message when it does
    s.poll_friends(); srv.send(":srv 303 Badaboom :Belon")
    s.poll_friends(); srv.send(":srv 303 Badaboom :")
    assert wait(app, lambda: w.view.topLevelItem(0).text(1) == "Offline")
    assert sum("is online" in l.text for l in s.server_buffer.lines) == 1
    assert any("Notify: Belon is offline" in l.text for l in s.server_buffer.lines)
    assert "minutes ago" in w.view.topLevelItem(0).text(3)
    # a typed /ison still prints
    srv.send(":srv 303 Badaboom :Typed")
    assert wait(app, lambda: any("Typed" in l.text for l in s.server_buffer.lines))
    # open dialog + remove
    w.view.setCurrentItem(w.view.topLevelItem(0))
    QTest.mouseClick(w.dialog_btn, Qt.MouseButton.LeftButton)
    assert win.buf.name == "Belon"
    QTest.mouseClick(w.remove_btn, Qt.MouseButton.LeftButton)
    assert win.cfg.friends == [] and w.view.topLevelItemCount() == 0
    # only on the named network
    win.add_friend("Other", "SomeElse")
    n = len(srv.received)
    s.poll_friends()
    wait(app, lambda: False, 100)
    assert not any("Other" in x for x in srv.received[n:])
    win.remove_friend("Other")
    # nick menu entry
    b = s.buffers["#skinhead"]
    menu = win.build_nick_menu(b, [b.users["oracle"]])
    [a for a in menu.actions() if a.text() == "Add to Friends List"][0].trigger()
    assert win.cfg.friends == ["Oracle"]


def test_friends_with_monitor(live):
    app, srv, win, s = live
    srv.send(":srv 005 Badaboom MONITOR=100 :are supported")
    assert wait(app, lambda: s._monitor)
    n = len(srv.received)
    win.add_friend("Belon")
    assert wait(app, lambda: any(x.startswith("MONITOR + Belon") for x in srv.received[n:]))
    srv.send(":srv 730 Badaboom :Belon!b@h")
    assert wait(app, lambda: s.friend_state["belon"]["online"])
    srv.send(":srv 731 Badaboom :Belon")
    assert wait(app, lambda: not s.friend_state["belon"]["online"])


def test_url_grabber_window(live, tmp_path):
    app, srv, win, s = live
    srv.send(":Belon!b@h PRIVMSG #skinhead :see https://example.com/a. and www.test.org ok")
    srv.send(":Belon!b@h PRIVMSG #skinhead :again https://example.com/a")
    assert wait(app, lambda: len(win.urls) == 2)
    assert win.urls == ["https://example.com/a", "www.test.org"]
    w = win.open_tool("urls")
    assert w.view.topLevelItemCount() == 2
    srv.send(":Belon!b@h PRIVMSG #skinhead :new ftp://f.org/x")
    assert wait(app, lambda: w.view.topLevelItemCount() == 3)
    w.view.setCurrentItem(w.view.topLevelItem(2))
    QTest.mouseClick(w.copy_btn, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == "ftp://f.org/x"
    out = tmp_path / "u.txt"
    w.save(str(out))
    assert out.read_text(encoding="utf-8").count("\n") == 3
    assert [a.text() for a in win.url_menu("https://x.y").actions()][:2] == ["Open Link in Browser", "Copy Link"]
    QTest.mouseClick(w.clear_btn, Qt.MouseButton.LeftButton)
    assert win.urls == [] and w.view.topLevelItemCount() == 0
    win.cfg.url_limit = 2
    for i in range(4):
        srv.send(f":Belon!b@h PRIVMSG #skinhead :https://n.org/{i}")
    assert wait(app, lambda: "https://n.org/3" in win.urls)
    assert win.urls == ["https://n.org/2", "https://n.org/3"]
    win.cfg.url_grabber = False
    srv.send(":Belon!b@h PRIVMSG #skinhead :https://off.org")
    srv.send(":Belon!b@h PRIVMSG #skinhead :off-marker")
    assert wait(app, lambda: any(l.text == "off-marker" for l in s.buffers["#skinhead"].lines))
    assert "https://off.org" not in win.urls


def test_character_chart_inserts_at_cursor(live):
    app, srv, win, s = live
    w = win.open_tool("chart")
    assert len(w.buttons) == 224 - 33
    win.input.setText("ab")
    win.input.setCursorPosition(1)
    QTest.mouseClick(w.buttons[0xE9], Qt.MouseButton.LeftButton)
    assert win.input.text() == "a\u00e9b"
    win.input.clear()
    assert win.open_tool("chart") is w      # one window, reused


def _save_editor(win, key, rows):
    d = win.open_editor(key)
    d.view.clear()
    for n, c in rows:
        d._add_row(n, c)
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    return d


def test_editor_buttons_new_delete_up_down_cancel_help(live, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app, srv, win, s = live
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: shown.append(a[2])))
    for key in ("replace", "ctcp", "commands", "url", "dialog", "ulbuttons", "popup"):
        d = win.open_editor(key)
        n = d.view.topLevelItemCount()
        QTest.mouseClick(d.new_btn, Qt.MouseButton.LeftButton)
        d.view.closePersistentEditor(d.view.currentItem(), 0)
        assert d.view.topLevelItemCount() == n + 1
        QTest.mouseClick(d.help_btn, Qt.MouseButton.LeftButton)
        assert shown[-1]
        d.view.currentItem().setText(0, "AAA")
        QTest.mouseClick(d.up_btn, Qt.MouseButton.LeftButton)
        if n:
            assert d.view.topLevelItem(n - 1).text(0) == "AAA"
            QTest.mouseClick(d.down_btn, Qt.MouseButton.LeftButton)
            assert d.view.topLevelItem(n).text(0) == "AAA"
        QTest.mouseClick(d.delete_btn, Qt.MouseButton.LeftButton)
        assert d.view.topLevelItemCount() == n
        before = getattr(win.cfg, d.field)
        d._add_row("X", "Y")
        QTest.mouseClick(d.cancel_btn, Qt.MouseButton.LeftButton)
        assert getattr(win.cfg, d.field) == before


def test_user_commands_expand_override_and_loop_guard(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    # defaults still work
    type_cmd(win, "/m Belon hi there")
    assert wait(app, lambda: any(x.startswith("PRIVMSG Belon") and "hi there" in x for x in srv.received))
    _save_editor(win, "commands", [["hello", "say hi %2 on %c, also &3"], ["two", "say first"], ["two", "say second"], ["loop", "loop"], ["needs", "say %2"]])
    s._next_send = 0.0
    type_cmd(win, "/hello bob and all %n")
    assert wait(app, lambda: any("hi bob on #skinhead, also and all %n" in x for x in srv.received))
    s._next_send = 0.0
    type_cmd(win, "/two")
    assert wait(app, lambda: any("second" in x for x in srv.received) and any("first" in x for x in srv.received))
    b = s.buffers["#skinhead"]
    type_cmd(win, "/loop")
    assert any("recursive" in l.text for l in b.lines)
    type_cmd(win, "/needs")
    assert any("/needs needs more" in l.text for l in b.lines)
    # the old alias is gone once the user saved their own list, and goes to the server like any unknown command
    n = len(srv.received)
    s._next_send = 0.0
    type_cmd(win, "/m Belon gone")
    assert wait(app, lambda: any(x.upper().startswith("M BELON") for x in srv.received[n:]))
    assert "hello" in [c for c in win.input._candidates("/he", True) if c == "/hello"][0]


def test_exec_runs_without_a_shell(live):
    import sys
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    type_cmd(win, f'/exec "{sys.executable}" -c "print(123+1)"')
    assert wait(app, lambda: any(l.text == "124" for l in b.lines), 8000), [l.text for l in b.lines[-3:]]
    type_cmd(win, "/exec this-program-does-not-exist-xyz")
    assert wait(app, lambda: any("Couldn't run" in l.text for l in b.lines), 5000)
    s._next_send = 0.0
    type_cmd(win, f'/exec -o "{sys.executable}" -c "print(7*6)"')
    assert wait(app, lambda: any("PRIVMSG #skinhead" in x and "42" in x for x in srv.received), 8000)


def test_auto_replace_on_space_and_enter(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    win.input.setFocus()
    QTest.keyClicks(win.input, "teh")
    QTest.keyClick(win.input, Qt.Key.Key_Space)
    assert win.input.text() == "the "
    win.input.clear()
    _save_editor(win, "replace", [["brb", "be right back"]])
    QTest.keyClicks(win.input, "ok brb")
    QTest.keyClick(win.input, Qt.Key.Key_Return)
    assert wait(app, lambda: any("ok be right back" in x for x in srv.received))
    QTest.keyClicks(win.input, "/brb")      # commands stay as typed
    QTest.keyClick(win.input, Qt.Key.Key_Space)
    assert win.input.text() == "/brb "
    win.input.clear()


def test_ctcp_replies_list(live):
    app, srv, win, s = live
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01PING 123 abc\x01")
    assert wait(app, lambda: any("NOTICE Belon" in x and "PING 123 abc" in x for x in srv.received))
    s._ctcp_times.clear()
    _save_editor(win, "ctcp", [["FINGER", "nctcp %s FINGER none of your business"], ["EVIL", "!calc.exe"], ["PING", "nctcp %s PING %d"]])
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01FINGER\x01")
    assert wait(app, lambda: any("FINGER none of your business" in x for x in srv.received))
    started = []
    import bchat.commands as cm
    orig = cm.start_program
    cm.start_program = lambda *a, **k: started.append(a)
    try:
        srv.send(":Belon!b@h PRIVMSG Badaboom :\x01EVIL\x01")
        srv.send(":Belon!b@h PRIVMSG Badaboom :\x01PING marker\x01")
        assert wait(app, lambda: any("PING marker" in x for x in srv.received))
    finally:
        cm.start_program = orig
    assert not started                     # others can't start programs here
    # a value can't smuggle another code in
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01PING %s%t\x01")
    assert wait(app, lambda: any("PING %s%t" in x for x in srv.received))


def test_url_handlers_and_popup_items(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    _save_editor(win, "url", [["Say it", "say seen %s"]])
    acts = win.url_menu("https://x.y/z").actions()
    assert [a.text() for a in acts if a.text()][-1] == "Say it"
    acts[-1].trigger()
    assert wait(app, lambda: any("seen https://x.y/z" in x for x in srv.received))
    _save_editor(win, "popup", [["SEP", ""], ["Hello", "say hello %s"], ["SUB", "More"], ["All", "say all %a"], ["ENDSUB", ""]])
    menu = win.build_nick_menu(b, [b.users["oracle"], b.users["belon"]])
    texts = [a.text() for a in menu.actions()]
    assert "Hello" in texts and "More" in texts
    [a for a in menu.actions() if a.text() == "All" or (a.menu() and a.menu().title() == "More")][0].menu().actions()[0].trigger()
    s._next_send = 0.0
    assert wait(app, lambda: any("all Oracle Belon" in x for x in srv.received))
    [a for a in menu.actions() if a.text() == "Hello"][0].trigger()
    assert wait(app, lambda: any("hello Oracle" in x for x in srv.received) and any("hello Belon" in x for x in srv.received), 5000)


def test_userlist_mode_and_dialog_buttons(live, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QPushButton
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert not win.ul_button_box.isVisible() and not win.mode_bar.isVisible()   # off until asked for: layout stays as it is
    view = win.menubar_.findChildren(type(win.menubar_.actions()[0].menu()))
    acts = win.named_actions()
    acts["View: Userlist Buttons"].trigger()
    acts["View: Mode Buttons"].trigger()
    assert win.ul_button_box.isVisible() and win.mode_bar.isVisible()
    grid = {w.text(): w for w in win.ul_button_box.findChildren(QPushButton)}
    assert sorted(grid) == sorted(["Op", "DeOp", "Ban", "Kick", "Sendfile", "Dialog"])
    idx = win.userlist.model().index(6)
    win.userlist.setCurrentIndex(idx)
    nick = win.userlist.selected_users()[0].nick
    QTest.mouseClick(grid["Op"], Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any("+o" in x and nick in x for x in srv.received))
    QTest.mouseClick(grid["Dialog"], Qt.MouseButton.LeftButton)
    assert win.buf.name == nick and win.dialog_bar.isVisible() and not win.mode_bar.isVisible()
    # dialog buttons
    bar = {w.text(): w for w in win.dialog_bar.findChildren(QPushButton)}
    QTest.mouseClick(bar["Whois"], Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any(x.upper().startswith("WHOIS") and nick in x for x in srv.received))
    q = win.buf
    q.session.add(q, "info", "*", "to be cleared")
    QTest.mouseClick(bar["Clear"], Qt.MouseButton.LeftButton)
    assert not q.lines
    win.select_buffer(b)
    assert not win.dialog_bar.isVisible() and win.mode_bar.isVisible()
    # mode buttons: reflect the channel and ask the server, never flip by themselves
    srv.send(":Fhazal!f@h MODE #skinhead +m")
    assert wait(app, lambda: win.mode_buttons["m"].isChecked())
    s._next_send = 0.0
    QTest.mouseClick(win.mode_buttons["m"], Qt.MouseButton.LeftButton)
    assert win.mode_buttons["m"].isChecked()
    assert wait(app, lambda: any(x.startswith("MODE #skinhead -m") for x in srv.received))
    srv.send(":Fhazal!f@h MODE #skinhead -m")
    assert wait(app, lambda: not win.mode_buttons["m"].isChecked())
    s._next_send = 0.0
    QTest.mouseClick(win.mode_buttons["i"], Qt.MouseButton.LeftButton)
    assert not win.mode_buttons["i"].isChecked()
    assert wait(app, lambda: any(x.startswith("MODE #skinhead +i") for x in srv.received))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("25", True)))
    s._next_send = 0.0
    QTest.mouseClick(win.mode_buttons["l"], Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any(x.startswith("MODE #skinhead +l 25") for x in srv.received))
    srv.send(":Fhazal!f@h MODE #skinhead +k sekret")
    assert wait(app, lambda: win.mode_buttons["k"].isChecked())
    s._next_send = 0.0
    QTest.mouseClick(win.mode_buttons["k"], Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any(x.startswith("MODE #skinhead -k sekret") for x in srv.received))
    QTest.mouseClick(win.mode_buttons["b"], Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any(x.startswith("MODE #skinhead +b") for x in srv.received))
    assert not win.mode_buttons["b"].isChecked()
    # custom buttons replace the defaults
    _save_editor(win, "ulbuttons", [["Wave", "say waves at %s"]])
    assert wait(app, lambda: [w for w in win.ul_button_box.findChildren(QPushButton) if w.isVisible() and w.text() == "Wave"])


def test_text_events_change_what_prints(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    d = win.open_editor("events")
    item = d.view.findItems("Join", Qt.MatchFlag.MatchExactly, 0)[0]
    d.view.setCurrentItem(item)
    assert d.edit.text() == "-->$t$1 ($3) has joined $2" and "$1 nick" in d.args.text()
    assert "Belon (b@host.my) has joined #skinhead" in d.preview.text()
    d.edit.setText("HELLO$t$1 came to $2 %Bbold")
    d._typed(d.edit.text())
    assert "HELLO  Belon came to #skinhead bold" in d.preview.text()
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    srv.send(":New$1!n@h JOIN #skinhead")
    assert wait(app, lambda: any(l.left == "HELLO" and l.text == "New$1 came to #skinhead \x02bold" for l in b.lines)), [(l.left, l.text) for l in b.lines[-2:]]
    # reset, test all, cancel
    d = win.open_editor("events")
    d.view.setCurrentItem(d.view.findItems("Join", Qt.MatchFlag.MatchExactly, 0)[0])
    assert d.edit.text().startswith("HELLO")
    QTest.mouseClick(d.reset_btn, Qt.MouseButton.LeftButton)
    assert d.edit.text().startswith("-->")
    n = len(b.lines)
    QTest.mouseClick(d.test_btn, Qt.MouseButton.LeftButton)
    from bchat.textevents import EVENTS
    assert len(b.lines) == n + len(EVENTS)
    QTest.mouseClick(d.cancel_btn, Qt.MouseButton.LeftButton)
    assert "Join" in win.cfg.text_events
    d = win.open_editor("events")
    QTest.mouseClick(d.reset_all_btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    assert win.cfg.text_events == {}
    srv.send(":Back!n@h JOIN #skinhead")
    assert wait(app, lambda: any(l.left == "-->" and "Back (n@h) has joined" in l.text for l in b.lines))
    # every default event renders with the words the rest of the app expects
    win.cfg.text_events = {"Kick": "BOOT$t$2 out by $1"}
    srv.send(":Fhazal!f@h KICK #skinhead Oracle :bye")
    assert wait(app, lambda: any(l.left == "BOOT" and l.text == "Oracle out by Fhazal" for l in b.lines))


def test_keyboard_shortcuts_editor(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    d = win.open_editor("keys")
    names = d.actions_by_name
    assert "Window: Clear Text" in names and "Window: Ban List" in names and "BChat: Quit" in names
    item = d.view.findItems("Window: Clear Text", Qt.MatchFlag.MatchExactly, 0)[0]
    assert item.text(1) == "Ctrl+L"
    d.view.setCurrentItem(item)
    from PySide6.QtGui import QKeySequence
    d.key.setKeySequence(QKeySequence("Ctrl+Q"))       # already Quit
    assert "also used by BChat: Quit" in d.warning.text()
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    assert "share a key" in d.warning.text() and d.isVisible()
    d.key.setKeySequence(QKeySequence("Ctrl+Shift+L"))
    QTest.mouseClick(d.new_btn, Qt.MouseButton.LeftButton)
    d.custom.topLevelItem(0).setText(0, "Ctrl+Shift+F5")
    d.custom.topLevelItem(0).setText(1, "say from a key")
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    assert win.cfg.keys == {"Window: Clear Text": "Ctrl+Shift+L"} and not d.isVisible()
    assert win.named_actions()["Window: Clear Text"].shortcut().toString() == "Ctrl+Shift+L"
    win._key_shortcuts[0].activated.emit()
    assert wait(app, lambda: any("from a key" in x for x in srv.received))
    # back to the default, nothing stored
    d = win.open_editor("keys")
    item = d.view.findItems("Window: Clear Text", Qt.MatchFlag.MatchExactly, 0)[0]
    d.view.setCurrentItem(item)
    d.key.setKeySequence(QKeySequence("Ctrl+L"))
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    assert win.cfg.keys == {}


def test_switcher_tabs_every_position_and_selection(live):
    from PySide6.QtWidgets import QTabBar
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert win.tree.isVisible() and not win.tabbar.isVisible()
    prefs(win, lambda d: d.sw_type.setCurrentIndex(1))
    assert win.tabbar.isVisible() and not win.tree.isVisible()
    assert win.tabs_act.isChecked() and not win.tree_act.isChecked()
    assert [win.tabbar.tabText(i) for i in range(win.tabbar.count())] == ["SkinIRC", "#skinhead"]
    assert win.tabbar.tabData(win.tabbar.currentIndex()) is b
    # real click on a tab
    QTest.mouseClick(win.tabbar, Qt.MouseButton.LeftButton, pos=win.tabbar.tabRect(0).center())
    assert win.buf is s.server_buffer
    win.select_buffer(b)
    assert win.tabbar.tabData(win.tabbar.currentIndex()) is b
    # a new tab, activity colour, and closing
    srv.send(":Belon!b@h PRIVMSG Badaboom :hello")
    assert wait(app, lambda: win.tabbar.count() == 3)
    assert win.tabbar.tabText(2) == "Belon" and win.tabbar.tabTextColor(2).name() == win.cfg.theme.new_highlight.lower()
    assert win.buf is b
    QTest.mouseClick(win.tabbar, Qt.MouseButton.LeftButton, pos=win.tabbar.tabRect(2).center())
    assert win.buf.name == "Belon" and win.tabbar.tabTextColor(2).name() != win.cfg.theme.new_highlight.lower()
    win.close_buffer(win.buf)
    assert win.tabbar.count() == 2
    # the menu works on tabs too
    assert "Detach" in [x.text() for x in win._switcher_menu(b).actions()]
    # every position, both types, and the chat always keeps the stretch
    for kind in (1, 0):
        for i, pos in enumerate(("left", "right", "top", "bottom", "hidden")):
            prefs(win, lambda d: (d.sw_type.setCurrentIndex(kind), d.sw_pos.setCurrentIndex(i)))
            app.processEvents()
            sw = win.tabbar if kind else win.tree
            assert sw.isVisible() == (pos != "hidden"), (kind, pos)
            mid = win.mid_panel.geometry()
            if pos != "hidden":
                g, chat = sw.mapToGlobal(sw.rect().center()), win.chat.mapToGlobal(win.chat.rect().center())
                assert {"left": g.x() < chat.x(), "right": g.x() > chat.x(), "top": g.y() < chat.y(), "bottom": g.y() > chat.y()}[pos], (kind, pos)
            if kind and pos != "hidden":
                assert win.tabbar.shape() == {"left": QTabBar.Shape.RoundedWest, "right": QTabBar.Shape.RoundedEast, "top": QTabBar.Shape.RoundedNorth, "bottom": QTabBar.Shape.RoundedSouth}[pos]
            assert win.split.widget(win.split.indexOf(win.mid_panel)) is win.mid_panel and win.chat.width() > 200
    prefs(win, lambda d: d.sw_pos.setCurrentIndex(0))
    # user list on the left, with the switcher left too
    prefs(win, lambda d: d.ul_side.setCurrentIndex(1))
    assert win.split.indexOf(win.tree) == 0 and win.split.indexOf(win.right_panel) == 1 and win.split.indexOf(win.mid_panel) == 2
    prefs(win, lambda d: d.ul_side.setCurrentIndex(0))
    # the View menu flips it too
    win.tabs_act.trigger()
    assert win.cfg.tab_layout == "tabs" and win.tabbar.isVisible()
    win.tree_act.trigger()
    assert win.cfg.tab_layout == "tree" and win.tree.isVisible()


def test_switcher_sort_trunc_small_focus_notices_autodialog(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    prefs(win, lambda d: (d.sw_sort.setChecked(True), d.sw_trunc.setValue(3), d.sw_small.setChecked(True)))
    srv.send(":Zed!z@h PRIVMSG Badaboom :hi")
    srv.send(":Abe!a@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: "abe" in s.buffers and "zed" in s.buffers)
    top = win.items[id(s.server_buffer)]
    assert [top.child(i).data(0, Qt.ItemDataRole.UserRole).name for i in range(top.childCount())] == ["#skinhead", "Abe", "Zed"]
    assert top.child(0).text(0) == "#sk.." and "8pt" in win.tree.styleSheet()
    prefs(win, lambda d: (d.sw_trunc.setValue(0), d.sw_small.setChecked(False), d.sw_sort.setChecked(False)))
    assert top.child(0).text(0) == "#skinhead" and win.tree.styleSheet() == ""
    # focus: never
    prefs(win, lambda d: d.sw_focus.setCurrentIndex(0))
    s.focus_next = "#asked"
    srv.send(":Badaboom!x@h JOIN #asked")
    assert wait(app, lambda: "#asked" in s.buffers)
    assert win.buf is b
    # focus: always
    prefs(win, lambda d: d.sw_focus.setCurrentIndex(1))
    srv.send(":Badaboom!x@h JOIN #always")
    assert wait(app, lambda: "#always" in s.buffers and win.buf.name == "#always")
    # only requested
    win.select_buffer(b)
    prefs(win, lambda d: d.sw_focus.setCurrentIndex(2))
    srv.send(":Badaboom!x@h JOIN #quiet")
    assert wait(app, lambda: "#quiet" in s.buffers)
    assert win.buf is b
    s.focus_next = "#wanted"
    srv.send(":Badaboom!x@h JOIN #wanted")
    assert wait(app, lambda: "#wanted" in s.buffers and win.buf.name == "#wanted")
    win.select_buffer(b)
    # server notices tab
    prefs(win, lambda d: d.sw_notices.setChecked(True))
    srv.send(":irc.server.net NOTICE Badaboom :server speaks")
    assert wait(app, lambda: "(notices)" in s.buffers and any("server speaks" in l.text for l in s.buffers["(notices)"].lines))
    win.select_buffer(s.buffers["(notices)"])
    n = len(srv.received)
    type_cmd(win, "typing here")
    assert any("No channel joined" in l.text for l in s.buffers["(notices)"].lines)
    win.select_buffer(b)
    # no new tab on private messages
    prefs(win, lambda d: d.sw_dialog.setChecked(False))
    srv.send(":Quiet!q@h PRIVMSG Badaboom :in front please")
    assert wait(app, lambda: any(l.left == "*Quiet*" and l.text == "in front please" for l in b.lines))
    assert "quiet" not in s.buffers


def test_detach_and_attach(live, monkeypatch):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: lower("oracle") in b.users)
    win.named_actions()["BChat: Detach"].trigger()
    w = win.detached[id(b)]
    assert w.isVisible() and win.buf is s.server_buffer
    # lines reach it, its input talks to its own tab, whatever the main window shows
    srv.send(":Belon!b@h PRIVMSG #skinhead :line for detached")
    assert wait(app, lambda: "line for detached" in w.chat.document().toPlainText())
    QTest.keyClicks(w.input, "from detached")
    QTest.keyClick(w.input, Qt.Key.Key_Return)
    assert wait(app, lambda: any("PRIVMSG #skinhead" in x and "from detached" in x for x in srv.received))
    assert "from detached" in w.chat.document().toPlainText()
    # completion uses its own tab
    w.input.setText("Orac"); QTest.keyClick(w.input, Qt.Key.Key_Tab)
    assert w.input.text().startswith("Oracle")
    w.input.clear()
    # its user list and title follow
    assert w.userlist.model_.rowCount() == len(b.users)
    srv.send(":New!n@h JOIN #skinhead")
    assert wait(app, lambda: w.userlist.model_.rowCount() == len(b.users) and "new" in b.users)
    srv.send(":Fhazal!f@h TOPIC #skinhead :detached topic")
    assert wait(app, lambda: w.topic.text() == "detached topic")
    # clicking its row in the switcher raises the window and leaves the main tab alone
    win.tree.setCurrentItem(win.items[id(b)])
    assert win.buf is s.server_buffer and id(b) in win.detached
    # preferences reach it
    prefs(win, lambda d: d.set_font("Courier New", 11))
    assert w.chat.document().defaultFont().family() == "Courier New"
    # attach by button, chat still all there
    QTest.mouseClick(w.attach_btn, Qt.MouseButton.LeftButton)
    assert id(b) not in win.detached and win.buf is b
    assert "line for detached" in win.chat.document().toPlainText()
    srv.send(":Belon!b@h PRIVMSG #skinhead :after attach")
    assert wait(app, lambda: "after attach" in win.chat.document().toPlainText())
    # red button closes the tab, like XChat
    win.detach(b)
    win.detached[id(b)].reject()
    assert wait(app, lambda: any(x.startswith("PART #skinhead") for x in srv.received))
    assert "#skinhead" not in s.buffers and id(b) not in win.detached
    # dialogs in windows
    prefs(win, lambda d: d.sw_windows.setCurrentIndex(1))
    srv.send(":Belon!b@h PRIVMSG Badaboom :private window")
    assert wait(app, lambda: "belon" in s.buffers and id(s.buffers["belon"]) in win.detached)
    assert "private window" in win.detached[id(s.buffers["belon"])].chat.document().toPlainText()
    win.close_buffer(s.buffers["belon"])
    prefs(win, lambda d: d.sw_windows.setCurrentIndex(0))
    # server tab: red button only attaches
    win.detach(s.server_buffer)
    win.detached[id(s.server_buffer)].reject()
    assert id(s.server_buffer) not in win.detached and s.state == "connected"


def test_empty_channel_tab_and_new_windows(live):
    app, srv, win, s = live
    win.select_buffer(s.server_buffer)
    n = len(s.buffers)
    win.named_actions()["New: Channel Tab"].trigger()
    b = win.buf
    assert b.name == "<none>" and b.placeholder and b.kind == "channel"
    type_cmd(win, "hello")
    assert any("No channel joined" in l.text for l in b.lines)
    type_cmd(win, "/join #filled")
    assert wait(app, lambda: any(x.startswith("JOIN #filled") for x in srv.received))
    assert "<none>" not in s.buffers
    srv.send(":Badaboom!x@h JOIN #filled")
    assert wait(app, lambda: win.buf is not None and win.buf.name == "#filled")
    win.named_actions()["New: Channel Window"].trigger()
    assert any(win.detached[k].b.placeholder for k in win.detached)
    for k in list(win.detached):
        win.detached[k].reject()
    win.named_actions()["New: Server Window"].trigger()
    assert len(win.detached) == 1
    d = next(iter(win.detached.values()))
    assert d.b.kind == "server" and not d.b.session.net.servers
    d.reject()


def test_meters_help_opacity_close_to_tray(live, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    app, srv, win, s = live
    assert not win.lag_bar.isVisible() and not win.meter_text.isVisible()
    acts = win.named_actions()
    acts["Network Meters: Both"].trigger()
    assert win.cfg.meters == 3 and win.lag_bar.isVisible() and win.queue_bar.isVisible() and win.meter_text.isVisible()
    s.lag_ms = s.LAG_WARN_MS // 2
    s._queue.extend(["a"] * 3)
    win._refresh_status()
    assert win.queue_bar.value() == len(s._queue) * 10 >= 30 and f"{len(s._queue)}q" in win.meter_text.text() and win.lag_bar.value() > 0
    s._queue.clear()
    acts["Network Meters: Graph"].trigger()
    assert win.lag_bar.isVisible() and not win.meter_text.isVisible()
    acts["Network Meters: Text"].trigger()
    assert not win.lag_bar.isVisible() and win.meter_text.isVisible()
    acts["Network Meters: Off"].trigger()
    assert not win.meter_text.isVisible()
    # help
    w = win.open_help()
    assert w.view.topLevelItemCount() > 50
    w.find.setText("banlist")
    shown = [w.view.topLevelItem(i).text(0) for i in range(w.view.topLevelItemCount()) if not w.view.topLevelItem(i).isHidden()]
    assert shown == ["/banlist"]
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    type_cmd(win, "/help join")
    assert any("JOIN <channel>" in l.text for l in b.lines)
    prefs(win, lambda d: d.opacity.setValue(70))
    assert abs(win.windowOpacity() - 0.7) < 0.02
    prefs(win, lambda d: d.opacity.setValue(100))
    # close to tray hides, Quit in the tray really quits
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    prefs(win, lambda d: (d.tray_icon.setChecked(True), d.close_tray.setChecked(True)))
    win.close()
    assert not win.isVisible() and s.state == "connected"
    win._restore_from_tray()
    assert win.isVisible()
    # start with Windows only acts for the installed app: from source nothing touches the registry
    called = []
    monkeypatch.setattr(win, "set_autostart", lambda on: called.append(on))
    prefs(win, lambda d: d.start_win.setChecked(True))
    assert called == [True] and win.cfg.start_with_windows
    prefs(win, lambda d: d.start_win.setChecked(True))
    assert called == [True]
    prefs(win, lambda d: (d.close_tray.setChecked(False), d.tray_icon.setChecked(False)))


def _sender(payload, offer_host="127.0.0.1"):
    """Someone offering a file: a real listening socket that sends the bytes and waits for the acks."""
    import socket, threading
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1)
    got = {"acks": 0, "start": 0}
    def serve():
        c, _ = ls.accept()
        c.sendall(payload[got["start"]:])
        try:
            c.settimeout(3)
            while True:
                d = c.recv(4096)
                if not d:
                    break
                got["acks"] = int.from_bytes(d[-4:], "big")
                if got["acks"] >= len(payload):
                    break
        except OSError:
            pass
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    return ls.getsockname()[1], got


def test_dcc_receive_accept_saves_the_exact_bytes(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path / "in")
    payload = bytes(range(256)) * 400
    port, got = _sender(payload)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND \"my file.bin\" 2130706433 {port} {len(payload)}\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    assert t.kind == "recv" and t.state == "queued" and t.name == "my file.bin" and t.ip == "127.0.0.1"
    # the window opens by itself and nothing starts until Accept
    w = win.tools["transfers"]
    assert w.isVisible() and w.view.topLevelItem(0).text(0) == "Waiting" and w.view.topLevelItem(0).text(7) == "Belon"
    w.view.topLevelItem(0).setSelected(True)
    assert w.accept_btn.isEnabled() and not w.resume_btn.isEnabled() and w.abort_btn.isEnabled()
    QTest.mouseClick(w.accept_btn, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: t.state == "done", 8000), (t.state, t.error, t.pos)
    assert (tmp_path / "in" / "my file.bin").read_bytes() == payload
    assert wait(app, lambda: got["acks"] == len(payload))
    assert w.view.topLevelItem(0).text(0) == "Complete" and w.view.topLevelItem(0).text(4) == "100"
    assert any("complete" in l.text for l in s.server_buffer.lines + s._front().lines)
    QTest.mouseClick(w.clear_btn, Qt.MouseButton.LeftButton)
    assert not win.dcc.items and w.view.topLevelItemCount() == 0


def test_dcc_names_from_the_network_cannot_escape_or_overwrite(live, tmp_path):
    from bchat.dcc import safe_name, parse_offer
    app, srv, win, s = live
    assert safe_name("..\\..\\windows\\evil.txt") == "evil.txt"
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("CON.txt") == "_CON.txt" and safe_name("NUL") == "_NUL"
    assert safe_name("a:b?.txt") == "a_b_.txt" and safe_name("...") == "_file"
    assert parse_offer('SEND "a b.txt" 1 2 3') == ("SEND", ["a b.txt", "1", "2", "3"])
    assert parse_offer("SEND plain.txt 1 2 3") == ("SEND", ["plain.txt", "1", "2", "3"])
    assert parse_offer("SEND two words.txt 1 2 3") == ("SEND", ["two words.txt", "1", "2", "3"])
    assert parse_offer("SEND x.txt 1 0 3 99") == ("SEND", ["x.txt", "1", "0", "3", "99"])
    win.cfg.dcc_dir = str(tmp_path)
    (tmp_path / "evil.txt").write_text("keep me")
    payload = b"new data"
    port, _ = _sender(payload)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND ..\\..\\evil.txt 2130706433 {port} {len(payload)}\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    assert Path(t.path).parent == tmp_path
    win.dcc.accept(t)
    assert wait(app, lambda: t.state == "done", 8000)
    assert (tmp_path / "evil.txt").read_text() == "keep me" and (tmp_path / "evil.txt.1").read_bytes() == payload
    # a sender can't write more than it offered
    port, _ = _sender(b"x" * 500)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND short.bin 2130706433 {port} 100\x01")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    t = win.dcc.items[1]
    win.dcc.accept(t)
    assert wait(app, lambda: t.state == "done", 8000)
    assert (tmp_path / "short.bin").stat().st_size == 100
    # junk offers are refused without a crash
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND x.txt notanumber nope 5\x01")
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC\x01")
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC WHATEVER x\x01")
    srv.send(":Belon!b@h PRIVMSG #skinhead :marker")
    assert wait(app, lambda: any(l.text == "marker" for l in s.buffers["#skinhead"].lines))
    assert len(win.dcc.items) == 2


def test_dcc_auto_accept_never_takes_programs(live, tmp_path):
    app, srv, win, s = live
    prefs(win, lambda d: (d.dcc_auto.setCurrentIndex(1), d.dcc_dir.setText(str(tmp_path)), d.dcc_nick.setChecked(True), d.dcc_open_recv.setChecked(False)))
    payload = b"auto"
    port, _ = _sender(payload)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND song.mp3 2130706433 {port} {len(payload)}\x01")
    assert wait(app, lambda: win.dcc.items and win.dcc.items[0].state == "done", 8000)
    assert (tmp_path / "Belon.song.mp3").read_bytes() == payload
    assert "transfers" not in win.tools
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND setup.exe 2130706433 1234 10\x01")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND TRICK.BAT 2130706433 1234 10\x01")
    assert wait(app, lambda: len(win.dcc.items) == 3)
    assert win.dcc.items[1].state == "queued" and win.dcc.items[2].state == "queued"
    # completed folder
    done = tmp_path / "done"
    prefs(win, lambda d: d.dcc_done.setText(str(done)))
    port, _ = _sender(payload)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND moved.txt 2130706433 {port} {len(payload)}\x01")
    assert wait(app, lambda: len(win.dcc.items) == 4 and win.dcc.items[3].state == "done", 8000)
    assert (done / "Belon.moved.txt").read_bytes() == payload


def test_dcc_ignored_offer_does_nothing(live):
    app, srv, win, s = live
    win.cfg.ignores.append("Spam!*@*")
    srv.send(":Spam!s@h PRIVMSG Badaboom :\x01DCC SEND x.txt 2130706433 1234 10\x01")
    srv.send(":Belon!b@h PRIVMSG #skinhead :marker")
    assert wait(app, lambda: any(l.text == "marker" for l in s.buffers["#skinhead"].lines))
    assert not win.dcc.items


def test_dcc_resume_continues_where_it_stopped(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    payload = bytes(range(256)) * 100
    (tmp_path / "part.bin").write_bytes(payload[:1000] + b"")
    port, got = _sender(payload)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND part.bin 2130706433 {port} {len(payload)}\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    w = win.tools["transfers"]
    w.view.topLevelItem(0).setSelected(True)
    assert w.resume_btn.isEnabled()
    got["start"] = 1000
    QTest.mouseClick(w.resume_btn, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: any(f"DCC RESUME part.bin {port} 1000" in x for x in srv.received))
    assert t.state == "queued"
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC ACCEPT part.bin {port} 1000\x01")
    assert wait(app, lambda: t.state == "done", 8000), (t.state, t.error)
    assert (tmp_path / "part.bin").read_bytes() == payload


def test_dcc_send_real_bytes_acks_abort_and_speed_limit(live, tmp_path, monkeypatch):
    import socket
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    src = tmp_path / "out file.bin"
    payload = bytes(range(256)) * 2000
    src.write_bytes(payload)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    type_cmd(win, f"/dcc send Belon {src}")
    assert wait(app, lambda: any("DCC SEND out_file.bin 2130706433" in x for x in srv.received))
    line = [x for x in srv.received if "DCC SEND" in x][-1]
    port = int(line.split()[-2]); size = int(line.split()[-1].rstrip("\x01"))
    assert size == len(payload)
    t = win.dcc.items[0]
    assert t.kind == "send" and win.tools["transfers"].isVisible()
    c = socket.create_connection(("127.0.0.1", port)); c.setblocking(False)
    got = bytearray()
    def pump():
        try:
            while True:
                d = c.recv(65536)
                if not d:
                    break
                got.extend(d)
                c.send(len(got).to_bytes(4, "big"))
        except BlockingIOError:
            pass
        return len(got) >= size and t.state == "done"
    assert wait(app, pump, 10000), (len(got), t.state, t.pos, t.acked)
    assert bytes(got) == payload
    c.close()
    assert t.percent() == 100
    # a second caller on an offer, and abort
    src2 = tmp_path / "two.bin"; src2.write_bytes(b"z" * 1000)
    t2 = win.dcc.send_file(s, "Belon", str(src2))
    assert t2.state == "queued" and t2.port
    w = win.tools["transfers"]
    w.fill()
    w.view.clearSelection()
    w.view.topLevelItem(1).setSelected(True)
    QTest.mouseClick(w.abort_btn, Qt.MouseButton.LeftButton)
    assert t2.state == "aborted" and not t2.server.isListening()
    # missing file
    assert win.dcc.send_file(s, "Belon", str(tmp_path / "nope")) is None
    assert any("Cannot access" in l.text for l in b.lines)
    # port range
    prefs(win, lambda d: (d.dcc_first.setValue(45871), d.dcc_last.setValue(45899)))
    t3 = win.dcc.send_file(s, "Belon", str(src2))
    assert 45871 <= t3.port <= 45899
    t3.abort()
    prefs(win, lambda d: (d.dcc_first.setValue(0), d.dcc_last.setValue(0)))
    # upload limit really slows it
    import time as _t
    prefs(win, lambda d: d.dcc_up.setValue(100))
    src3 = tmp_path / "slow.bin"; src3.write_bytes(b"s" * 60000)
    t4 = win.dcc.send_file(s, "Belon", str(src3))
    c = socket.create_connection(("127.0.0.1", t4.port)); c.setblocking(False)
    got = bytearray(); size = 60000
    t = t4
    start = _t.time()
    assert wait(app, pump, 10000)
    took = _t.time() - start
    assert took > 0.3, took
    c.close()
    prefs(win, lambda d: d.dcc_up.setValue(0))


def test_dcc_passive_both_ways(live, tmp_path):
    import socket
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    win.cfg.dcc_dir = str(tmp_path)
    # they offer passively: we listen and answer with the token, they connect to us
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND p.bin 2130706433 0 5 777\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    assert t.passive
    win.dcc.accept(t)
    assert wait(app, lambda: any("DCC SEND p.bin 2130706433" in x and x.rstrip("\x01").endswith(" 5 777") for x in srv.received))
    c = socket.create_connection(("127.0.0.1", t.port))
    c.sendall(b"hello")
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.pos)
    c.close()
    assert (tmp_path / "p.bin").read_bytes() == b"hello"
    # we offer passively: they answer with an address and the token
    src = tmp_path / "up.bin"; src.write_bytes(b"data!")
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1); ls.setblocking(False)
    t2 = win.dcc.send_file(s, "Belon", str(src), passive=True)
    assert wait(app, lambda: any(" 0 5 " + t2.token in x for x in srv.received))
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND up.bin 2130706433 {ls.getsockname()[1]} 5 {t2.token}\x01")
    got = bytearray()
    conn = []
    def pump():
        try:
            if not conn:
                conn.append(ls.accept()[0]); conn[0].setblocking(False)
            d = conn[0].recv(100)
            got.extend(d)
            if d:
                conn[0].send(len(got).to_bytes(4, "big"))
        except BlockingIOError:
            pass
        return t2.state == "done"
    assert wait(app, pump, 5000), (t2.state, t2.acked, t2.pos)
    assert bytes(got) == b"data!"
    assert len([x for x in win.dcc.items if x.kind == "recv"]) == 1     # the answer isn't a new offer


def test_dcc_chat_both_ways_and_window(live):
    import socket
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    type_cmd(win, "/dcc chat Belon")
    assert wait(app, lambda: any("DCC CHAT chat 2130706433" in x for x in srv.received))
    line = [x for x in srv.received if "DCC CHAT" in x][-1]
    port = int(line.split()[-1].rstrip("\x01"))
    w = win.tools["chats"]
    assert w.isVisible() and w.view.topLevelItem(0).text(1) == "Belon" and w.view.topLevelItem(0).text(0) == "Waiting"
    c = socket.create_connection(("127.0.0.1", port))
    assert wait(app, lambda: "=belon" in s.buffers and win.buf is s.buffers["=belon"])
    q = s.buffers["=belon"]
    c.sendall(b"hi over dcc\n")
    assert wait(app, lambda: any(l.text == "hi over dcc" and l.left == "Belon" for l in q.lines))
    type_cmd(win, "typed back")
    c.settimeout(2)
    assert c.recv(100) == b"typed back\n"
    assert any(l.text == "typed back" for l in q.lines)
    assert not any("typed back" in x for x in srv.received)         # nothing goes through the server
    type_cmd(win, "/me waves")
    assert c.recv(100) == b"\x01ACTION waves\x01\n"
    w.fill()
    assert int(w.view.topLevelItem(0).text(3)) > 0 and int(w.view.topLevelItem(0).text(2)) > 0
    c.sendall(b"\x01ACTION nods\x01\n")
    assert wait(app, lambda: any(l.text == "Belon nods" for l in q.lines))
    c.close()
    assert wait(app, lambda: any("lost" in l.text for l in q.lines))
    type_cmd(win, "anyone there")
    assert any("No active DCC chat" in l.text for l in q.lines)
    # an offer waits for Accept in the window
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1); ls.setblocking(False)
    srv.send(f":Oracle!o@h PRIVMSG Badaboom :\x01DCC CHAT chat 2130706433 {ls.getsockname()[1]}\x01")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    t = win.dcc.items[1]
    assert t.state == "queued"
    w.fill()
    w.view.setCurrentItem(w.view.topLevelItem(1))
    QTest.mouseClick(w.accept_btn, Qt.MouseButton.LeftButton)
    assert wait(app, lambda: t.state == "active" and "=oracle" in s.buffers, 5000)
    w.view.setCurrentItem(w.view.topLevelItem(1))
    QTest.mouseClick(w.abort_btn, Qt.MouseButton.LeftButton)
    assert t.state == "aborted"


def test_dcc_command_forms(live, tmp_path):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    type_cmd(win, "/dcc list")
    assert any("No active DCCs" in l.text for l in b.lines)
    type_cmd(win, "/dcc get Nobody")
    assert any("No file offered" in l.text for l in b.lines)
    type_cmd(win, "/dcc close send Nobody x")
    assert any("No such DCC" in l.text for l in b.lines)
    type_cmd(win, "/dcc nonsense")
    win.cfg.dcc_dir = str(tmp_path)
    port, _ = _sender(b"abc")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND g.txt 2130706433 {port} 3\x01")
    assert wait(app, lambda: win.dcc.items)
    type_cmd(win, "/dcc list")
    assert any("g.txt" in l.text and "queued" in l.text for l in b.lines)
    type_cmd(win, "/dcc get Belon g.txt")
    assert wait(app, lambda: win.dcc.items[0].state == "done", 5000)
    assert (tmp_path / "g.txt").read_bytes() == b"abc"
    menu = win.build_nick_menu(b, [b.users["belon"]])
    assert [a for a in menu.actions() if a.text() == "Send a File"][0].isEnabled()


PLUGIN = """
__module_name__ = "tester"
__module_version__ = "1.2"
__module_description__ = "A test script"
import xchat
seen = []
def on_cmd(word, word_eol, userdata):
    xchat.prnt("cmd " + word[1] + " | " + word_eol[1] + " | " + str(userdata))
    return xchat.EAT_ALL
def on_srv(word, word_eol, userdata):
    if "eatme" in word_eol[0]:
        return xchat.EAT_ALL
    if "shout" in word_eol[0]:
        xchat.command("say heard")
    return xchat.EAT_NONE
def on_print(word, userdata):
    if "hideme" in word[1]:
        return xchat.EAT_ALL
    return xchat.EAT_NONE
def boom(word, word_eol, userdata):
    raise ValueError("kaboom")
count = [0]
def on_timer(userdata):
    count[0] += 1
    xchat.prnt("tick %d" % count[0])
    return count[0] < 2
xchat.hook_command("TESTCMD", on_cmd, "data")
xchat.hook_command("BOOM", boom)
xchat.hook_server("PRIVMSG", on_srv)
xchat.hook_print("Channel Message", on_print)
xchat.hook_timer(30, on_timer)
xchat.hook_unload(lambda u: xchat.prnt("bye from tester"))
def info(word, word_eol, userdata):
    ctx = xchat.get_context()
    names = sorted(u.nick for u in xchat.get_list("users"))
    ctx.prnt(" ".join([xchat.get_info("nick"), xchat.get_info("channel"), xchat.get_info("network"), names[0]]))
    return xchat.EAT_ALL
xchat.hook_command("INFO2", info)
"""


def test_plugins_xchat_api_window_and_errors(live, tmp_path, monkeypatch):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    path = tmp_path / "tester.py"
    path.write_text(PLUGIN)
    type_cmd(win, f"/load {path}")
    assert any("tester 1.2 loaded" in l.text for l in b.lines)
    w = win.open_tool("plugins")
    assert w.view.topLevelItem(0).text(0) == "tester" and w.view.topLevelItem(0).text(3) == "A test script"
    type_cmd(win, "/testcmd one two")
    assert any(l.text == "cmd one | one two | data" for l in b.lines)
    # a plain command still works, and server hooks see lines
    srv.send(":Belon!b@h PRIVMSG #skinhead :eatme now")
    srv.send(":Belon!b@h PRIVMSG #skinhead :hideme please")
    srv.send(":Belon!b@h PRIVMSG #skinhead :shout loud")
    assert wait(app, lambda: any("PRIVMSG #skinhead" in x and "heard" in x for x in srv.received))
    assert not any("eatme" in l.text or "hideme" in l.text for l in b.lines)
    assert any("shout" in l.text for l in b.lines)
    assert wait(app, lambda: any(l.text == "tick 2" for l in b.lines))
    wait(app, lambda: False, 100)
    assert not any(l.text == "tick 3" for l in b.lines)          # a timer returning False stops
    type_cmd(win, "/info2")
    assert any(l.text.startswith("Badaboom #skinhead SkinIRC ") for l in b.lines)
    # an error in a script reports and doesn't take anything down
    type_cmd(win, "/boom")
    assert any("kaboom" in l.text for l in b.lines)
    # a broken script doesn't either
    bad = tmp_path / "bad.py"; bad.write_text("this is not python !!")
    assert win.plugins.load(str(bad)) is None
    assert any("Couldn't load bad.py" in l.text for l in b.lines)
    # reload, unload by button
    w.fill()
    w.view.setCurrentItem(w.view.topLevelItem(0))
    QTest.mouseClick(w.reload_btn, Qt.MouseButton.LeftButton)
    assert any("bye from tester" in l.text for l in b.lines) and len(win.plugins.plugins) == 1
    w.view.setCurrentItem(w.view.topLevelItem(0))
    QTest.mouseClick(w.unload_btn, Qt.MouseButton.LeftButton)
    assert not win.plugins.plugins
    srv.send(":Belon!b@h PRIVMSG #skinhead :eatme after unload")
    assert wait(app, lambda: any("eatme after unload" in l.text for l in b.lines))
    # autoload from the addons folder
    win.plugins.folder.mkdir(parents=True, exist_ok=True)
    (win.plugins.folder / "auto.py").write_text('__module_name__ = "auto"\n')
    win.plugins.autoload()
    assert win.plugins.find("auto") is not None
    type_cmd(win, "/unload auto")
    assert not win.plugins.plugins
    type_cmd(win, "/unload nothing")
    assert any("No such plugin" in l.text for l in b.lines)


def test_files_page_saved(app, tmp_path):
    from bchat import config
    win, _ = make_win(tmp_path, 1)
    prefs(win, lambda d: (d.dcc_auto.setCurrentIndex(1), d.dcc_dir.setText("D:/in"), d.dcc_ip.setText("1.2.3.4"), d.dcc_down_all.setValue(5), d.dcc_open_chat.setChecked(False), d.dcc_from_server.setChecked(False)))
    back = config.load(tmp_path)
    assert (back.dcc_auto, back.dcc_dir, back.dcc_ip, back.dcc_max_get_all, back.dcc_open_chat, back.dcc_ip_from_server) == (1, "D:/in", "1.2.3.4", 5, False, False)
    win.close()


def test_spell_check_marks_suggests_and_learns(live):
    from PySide6.QtWidgets import QMenu
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    box = win.input
    box.setText("helo there wrold ")
    box.mark_spelling()
    assert box.bad_words == []                      # off by default
    prefs(win, lambda d: d.spell.setChecked(True))
    box.setText("helo there wrold ")
    box.mark_spelling()
    words = [box.text()[a:z] for a, z in box.bad_words]
    assert words == ["helo", "wrold"]
    assert box.text() == "helo there wrold "        # marks only, nothing typed changes
    # the red really reaches the screen, and goes when the word is fixed
    win.show()
    marked = box.grab().toImage()
    marked.save(str(Path(win.cfg_dir) / "spell-marked.png"))
    keep = box.bad_words
    from PySide6.QtGui import QInputMethodEvent
    QApplication.sendEvent(box, QInputMethodEvent("", []))
    plain = box.grab().toImage()
    diff = sum(marked.pixelColor(x, y) != plain.pixelColor(x, y) for y in range(plain.height()) for x in range(plain.width()))
    assert diff > 20, diff
    assert box.text() == "helo there wrold "
    box.mark_spelling()
    # suggestions and dictionary in the right-click menu
    menu = QMenu(box)
    span = box.bad_words[0]
    box.fill_spell_menu(menu, span)
    labels = [x.text() for x in menu.actions()]
    assert "hello" in labels and 'Add "helo" to dictionary' in labels
    [x for x in menu.actions() if x.text() == "hello"][0].trigger()
    assert box.text() == "hello there wrold "
    box.mark_spelling()
    assert [box.text()[a:z] for a, z in box.bad_words] == ["wrold"]
    menu = QMenu(box)
    box.fill_spell_menu(menu, box.bad_words[0])
    [x for x in menu.actions() if x.text().startswith("Add")][0].trigger()
    assert win.cfg.spell_words == ["wrold"] and box.bad_words == []
    # nicks, commands, links and the word in progress aren't judged
    box.setText("Oracle https://exampel.com/qqqq ok ")
    box.mark_spelling()
    assert box.bad_words == []
    box.setText("/msg qqqqq zzzzz ")
    box.mark_spelling()
    assert box.bad_words == []
    box.setFocus()
    box.setText("xyzzyq")
    box.mark_spelling()
    if box.hasFocus():
        assert box.bad_words == []
    # sending still sends the plain text
    box.setText("wrongg wordd ")
    box.mark_spelling()
    QTest.keyClick(box, Qt.Key.Key_Return)
    assert wait(app, lambda: any("wrongg wordd" in x for x in srv.received))
    box.clear()
    # off again: marks go
    box.setText("helo there ")
    prefs(win, lambda d: d.spell.setChecked(False))
    box.mark_spelling()
    assert box.bad_words == []
    box.clear()


def test_help_has_no_blank_lines_for_real_commands(live):
    from bchat.commands import COMMAND_NAMES, HELP, ALIASES
    app, srv, win, s = live
    missing = [c for c in COMMAND_NAMES if c not in HELP and c not in ALIASES]
    assert not missing, missing


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


NS_HELP = [  # recorded from irc.bajubesi.org (Unreal 6 + Anope 2.0), 2026-11-07
    "NickServ allows you to register a nickname and", "/msg NickServ HELP command.",
    "    CONFIRM        Confirm a passcode", "    IDENTIFY       Identify yourself with your password", " ",
    "after 365 days if not used.",
]


def test_ns_help_shows_every_nickserv_line(live):
    """XChat lost NickServ's /ns help on the user's Unreal server; BChat must show all of it, spaces kept."""
    app, srv, win, s = live
    b = s.server_buffer
    win.select_buffer(b)
    type_cmd(win, "/ns help")
    assert wait(app, lambda: any(x.upper() == "NS HELP" for x in srv.received))
    for text in NS_HELP:
        srv.send(f":NickServ!services@services.bajubesi.com.my NOTICE Badaboom :{text}")
    assert wait(app, lambda: any("365 days" in l.text for l in b.lines))
    got = [l.text for l in b.lines if l.left == "-NickServ-"]
    assert got == NS_HELP
    doc = win.chat.doc_for(b).toPlainText()
    assert "-NickServ-     CONFIRM        Confirm a passcode" in doc


def _colours_of(win, b, needle):
    """Foreground colour of each character of the first line containing needle."""
    d = win.chat.doc_for(b)
    block = d.begin()
    while block.isValid() and needle not in block.text():
        block = block.next()
    assert block.isValid(), needle
    out, it = [], block.begin()
    while not it.atEnd():
        f = it.fragment()
        out.append((f.text(), f.charFormat().foreground().color().name()))
        it += 1
    return out


def test_xchat_colours_for_brackets_and_connect_lines(live):
    """XChat textevents.in: >nick< green brackets + plain name, -nick- blue dashes + pink name, connect lines purple."""
    app, srv, win, s = live
    t = win.cfg.theme
    sb, ch = s.server_buffer, s.buffers["#skinhead"]
    srv.send(":NickServ!s@services.my NOTICE Badaboom :hello from services")
    win.select_buffer(sb)
    type_cmd(win, "/msg NickServ help")
    assert wait(app, lambda: any(l.text == "hello from services" for l in sb.lines + ch.lines))
    for b in (sb, ch):
        win.select_buffer(b)
        if any(l.left == ">NickServ<" for l in b.lines):
            parts = dict((x, c) for x, c in _colours_of(win, b, ">NickServ<"))
            assert parts[">"] == t.send_bracket.lower() and parts["NickServ"] == t.chat_fg.lower()
        if any(l.text == "hello from services" for l in b.lines):
            parts = _colours_of(win, b, "hello from services")
            assert ("NickServ", t.notice_nick.lower()) in parts and ("-", t.notice_bracket.lower()) in parts
    conn = _colours_of(win, sb, "Connected")
    assert all(c == t.connect.lower() for x, c in conn if "Connected" in x)


def test_own_lines_have_no_brackets_teal_nick_and_tinted_text(live):
    """User's pick: own nick teal with no brackets, own text a light teal tint; mentions keep their colour."""
    app, srv, win, s = live
    t = win.cfg.theme
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    type_cmd(win, "lagu ni best")
    srv.send(":Belon!b@h PRIVMSG #skinhead :Badaboom: aku request")
    assert wait(app, lambda: any("aku request" in l.text for l in b.lines))
    mine = _colours_of(win, b, "lagu ni best")
    assert ("Badaboom ", t.self_nick.lower()) in mine and ("lagu ni best", t.self_text.lower()) in mine
    assert "[Badaboom]" not in win.chat.doc_for(b).toPlainText()
    hl = _colours_of(win, b, "aku request")
    assert all(c == t.highlight.lower() for x, c in hl if "aku request" in x)


def test_add_network_saves_a_typed_server_in_one_click(app, tmp_path):
    """AdiIRC's Add Network: a /server tab becomes a saved network (name from NETWORK=, "(1)" if taken)."""
    from bchat import config
    from bchat.config import NetworkConfig, Server
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    win.skip_dialogs = True
    s = win.new_server_tab()
    win.select_buffer(s.server_buffer)
    type_cmd(win, f"/server 127.0.0.1 {srv.port}")
    assert wait(app, lambda: s.state == "connected" and s.network_token, 8000)
    type_cmd(win, "/join #mine")
    assert wait(app, lambda: "#mine" in s.buffers and s.buffers["#mine"].joined)
    assert s.net not in win.cfg.networks
    saved = win.add_network_from(s)
    assert saved.name == s.network_token and saved.autojoin == "#mine"
    assert saved.servers[0].host == "127.0.0.1" and saved.servers[0].port == srv.port
    assert s.net is saved and saved in win.cfg.networks
    assert win.sessions.get(saved.name) is s and list(win.sessions.values()).count(s) == 1   # filed under the new name
    assert any(n.name == saved.name for n in config.load(win.cfg_dir).networks)   # written to disk
    assert any(l.text.startswith(f"Saved as network {saved.name}") for l in s.server_buffer.lines)
    # saving the same network again (e.g. typed again later) gets "(1)", like AdiIRC's JavaNET(1)
    s.net = NetworkConfig("127.0.0.1", [Server("127.0.0.1", srv.port)])
    assert win.add_network_from(s).name == f"{saved.name}(1)"
    win.close()
    srv.stop()


def test_network_list_rename_by_clicking_the_name(live):
    """XChat: click the selected network's name (or F2), type, Enter. Open tab, logging and saved file follow."""
    from bchat import config
    from bchat.networklist import NetworkListDialog
    app, srv, win, s = live
    win.cfg.networks.append(type(s.net)("Other"))
    old = s.net.name
    win.cfg.log_tabs.append(f"{old.lower()}/#skinhead")
    d = NetworkListDialog(win)
    d.show()
    row = next(i for i in range(d.list.count()) if d.list.item(i).text() == old)
    d.list.setCurrentRow(row)
    it = d.list.item(row)
    d.list.editItem(it)
    wait(app, lambda: False, 50)
    editor = QApplication.focusWidget()
    editor.selectAll()
    QTest.keyClicks(editor, "SKINTERNET")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    wait(app, lambda: False, 50)
    assert s.net.name == "SKINTERNET" and d.list.item(row).text() == "SKINTERNET"
    assert win.sessions.get("SKINTERNET") is s and old not in win.sessions
    assert s.server_buffer.name == "SKINTERNET" and win.items[id(s.server_buffer)].text(0) == "SKINTERNET"
    assert "skinternet/#skinhead" in win.cfg.log_tabs
    assert any(n.name == "SKINTERNET" for n in config.load(win.cfg_dir).networks)
    # a name that is taken (any case) or empty snaps back
    for bad in ("other", "   "):
        d.list.editItem(d.list.item(row)); wait(app, lambda: False, 30)
        e = QApplication.focusWidget(); e.selectAll(); QTest.keyClicks(e, bad); QTest.keyClick(e, Qt.Key.Key_Return)
        wait(app, lambda: False, 30)
        assert s.net.name == "SKINTERNET" and d.list.item(row).text() == "SKINTERNET"
    d.reject()


def test_server_menu_shows_edit_network_for_saved_and_add_for_typed(live, monkeypatch):
    """AdiIRC: right-click a server: Edit Network once saved, Add Network before. Edit can rename too."""
    from PySide6.QtWidgets import QMenu
    from bchat import mainwindow
    from bchat.networklist import NetworkEditDialog
    app, srv, win, s = live
    seen = []

    class Menu(QMenu):   # PySide ignores a patched QMenu.exec, so swap the class the window uses
        def exec(self, *a):
            seen.append([x.text() for x in self.actions()])
    monkeypatch.setattr(mainwindow, "QMenu", Menu)
    item = win.items[id(s.server_buffer)]
    win._tree_menu(win.tree.visualItemRect(item).center())
    assert "Edit Network..." in seen[-1] and "Add Network" not in seen[-1]
    s.net = type(s.net)("typed", list(s.net.servers))           # like a /server tab
    win._tree_menu(win.tree.visualItemRect(item).center())
    assert "Add Network" in seen[-1] and "Edit Network..." not in seen[-1]
    s.net = win.cfg.networks[0]
    d = NetworkEditDialog(s.net, win)
    d.name.setText("SKINTERNET")
    d.accept()
    assert s.net.name == "SKINTERNET" and win.sessions.get("SKINTERNET") is s


def test_edit_network_window_save_cancel_and_red_button(live, monkeypatch):
    """User: the red button dropped a new name silently. Now: Save saves, Cancel drops, red button asks."""
    from bchat import networklist
    from bchat.networklist import NetworkEditDialog
    app, srv, win, s = live
    net = s.net
    answers = []
    monkeypatch.setattr(networklist, "ask_save", lambda parent, name: answers.pop(0))
    # nothing changed: red button closes without asking
    d = NetworkEditDialog(net, win); d.titlebar.close_clicked.emit()
    assert d.result() == 0 and not answers
    # red button, answer Save
    d = NetworkEditDialog(net, win); d.name.setText("SKT"); answers.append("save"); d.titlebar.close_clicked.emit()
    assert net.name == "SKT"
    # red button, answer Discard
    d = NetworkEditDialog(net, win); d.name.setText("Nope"); d.auto.setChecked(not net.autoconnect)
    was = net.autoconnect; answers.append("discard"); d.titlebar.close_clicked.emit()
    assert net.name == "SKT" and net.autoconnect == was
    # red button, answer Cancel: window stays open with the edits
    d = NetworkEditDialog(net, win); d.show(); d.name.setText("Later"); answers.append("stay"); d.titlebar.close_clicked.emit()
    assert d.isVisible() and d.name.text() == "Later" and net.name == "SKT"
    # Cancel button drops without asking; Save button saves
    buttons = {b.text().replace("&", ""): b for b in d.findChildren(networklist.QPushButton)}
    buttons["Cancel"].click()
    assert not d.isVisible() and net.name == "SKT" and not answers
    d = NetworkEditDialog(net, win); d.name.setText("SKINTERNET")
    {b.text().replace("&", ""): b for b in d.findChildren(networklist.QPushButton)}["Save"].click()
    assert net.name == "SKINTERNET"


def _prefs(win):
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    d.show()
    return d


def test_preferences_text_box_settings_take_effect(live):
    """Settings > Preferences > Text box: every setting changes the chat, and is saved."""
    from bchat import config
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    srv.send(":Oracle!o@h PRIVMSG #skinhead :\x0304merah\x03 hello")      # Oracle is +o in the fake channel
    srv.send(":BeerAddict!b@h PRIVMSG #skinhead :plain user")
    assert wait(app, lambda: any(l.text == "plain user" for l in b.lines))
    assert next(l for l in b.lines if l.left == "Oracle").rank == "voice"
    d = _prefs(win)
    d.stamp_fmt.setText("%H:%M:%S")
    d.spacing.setValue(130)
    d.scrollback.setValue(2000)
    d.marker.setChecked(False)
    d.rank_buttons["slot"].setChecked(True)
    d.color_nicks.setChecked(True)
    d.strip.setChecked(True)
    d.set_font("Courier New", 11)
    d.accept()
    c = win.cfg
    assert (c.stamp_format, c.line_spacing, c.max_lines, c.marker_line, c.rank_lights, c.color_nicks, c.strip_colors,
            c.chat_font, c.chat_font_size) == ("%H:%M:%S", 130, 2000, False, "slot", True, True, "Courier New", 11)
    saved = config.load(win.cfg_dir)
    assert saved.rank_lights == "slot" and saved.stamp_format == "%H:%M:%S" and not saved.marker_line
    doc = win.chat.document()
    assert doc.maximumBlockCount() == 2000 and doc.defaultFont().family() == "Courier New"
    blk = doc.begin()
    while "hello" not in blk.text():
        blk = blk.next()
    assert len(blk.text().split(" ")[0]) == 8                      # 12:34:56
    assert blk.blockFormat().lineHeight() == 130
    imgs, colours = [], []
    it = blk.begin()
    while not it.atEnd():
        f = it.fragment()
        if f.charFormat().isImageFormat():
            imgs.append(f.charFormat().toImageFormat().name())
        else:
            colours.append((f.text(), f.charFormat().foreground().color().name()))
        it += 1
    assert any("lights/voice-" in n for n in imgs)                    # Oracle's light
    assert ("Oracle ", win.chat.nick_colour("Oracle")) in colours      # coloured nick
    assert all(c != win.cfg.theme.palette[4].lower() for x, c in colours if "merah" in x)   # colour stripped
    blk = doc.begin()
    while "plain user" not in blk.text():
        blk = blk.next()
    it = blk.begin(); names = []
    while not it.atEnd():
        f = it.fragment()
        if f.charFormat().isImageFormat():
            names.append(f.charFormat().toImageFormat().name())
        it += 1
    assert names == ["bchat:blank"]                                   # empty slot keeps text lined up


def test_preferences_colours_cancel_reset_and_greyed_pages(live):
    app, srv, win, s = live
    t = win.cfg.theme
    before = t.self_nick
    d = _prefs(win)
    d.show_page("Colors")
    assert d.title.text() == "Colors"
    d.set_colour("self_nick", "#ff0000")
    d.set_colour(("palette", 4), "#00ff00")
    d.reject()                                                        # Cancel / red button: nothing changes
    assert t.self_nick == before and t.palette[4] != "#00ff00"
    d = _prefs(win)
    d.set_colour("self_nick", "#ff0000")
    d.set_colour(("palette", 4), "#00ff00")
    d.accept()
    assert t.self_nick == "#ff0000" and t.palette[4] == "#00ff00"
    d = _prefs(win)
    d.reset_colours()
    d.accept()
    from bchat.config import Theme
    assert t.self_nick == Theme().self_nick and t.palette == Theme().palette
    d = _prefs(win)
    from PySide6.QtCore import Qt as _Qt
    assert d._items["Text box"].flags() & _Qt.ItemFlag.ItemIsEnabled
    d.reject()


def test_topic_editor_keeps_formatting_and_sets_it(live):
    """User: set the topic like XChat, with B U I and colours. The old bar stripped colours and sent them back stripped."""
    from PySide6.QtGui import QTextCursor
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    srv.send(":Fhazal!f@h MODE #skinhead +o Badaboom")                    # the test channel is +t
    assert wait(app, lambda: "@" in b.users["badaboom"].prefixes and not win.topic.edit.isReadOnly())
    raw = "\x02\x0304Merdeka\x03\x02 Malaysia \x1f#Vhost\x1f \U0001F389"
    srv.send(f":Fhazal!f@h TOPIC #skinhead :{raw}")
    assert wait(app, lambda: b.topic == raw)
    ed = win.topic.edit
    assert ed.toPlainText() == "Merdeka Malaysia #Vhost \U0001F389"          # shown, not stripped of meaning
    assert parse_round(ed.to_irc()) == parse_round(raw)                      # same formatting back out
    # select "Malaysia", make it bold + colour 12, then press Enter
    ed.setFocus()
    cur = ed.textCursor()
    start = ed.toPlainText().index("Malaysia")
    cur.setPosition(start); cur.setPosition(start + len("Malaysia"), QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(cur)
    win.topic.buttons["bold"].click()
    ed.set_fg(12)
    QTest.keyClick(ed, Qt.Key.Key_Return)
    assert wait(app, lambda: any(x.startswith("TOPIC #skinhead :") for x in srv.received))
    sent = next(x for x in srv.received if x.startswith("TOPIC #skinhead :")).split(" :", 1)[1]
    spans = {sp.text.strip(): sp for sp in __import__("bchat.protocol", fromlist=["parse_format"]).parse_format(sent) if sp.text.strip()}
    assert spans["Malaysia"].bold and spans["Malaysia"].fg == 12
    assert spans["Merdeka"].bold and spans["Merdeka"].fg == 4 and spans["#Vhost"].underline
    # Esc puts the server's topic back
    ed.setFocus(); ed.textCursor().insertText("junk"); QTest.keyClick(ed, Qt.Key.Key_Escape)
    assert "junk" not in ed.toPlainText()


def parse_round(text):
    from bchat.protocol import parse_format
    return [(sp.text, sp.bold, sp.italic, sp.underline, sp.fg, sp.bg) for sp in parse_format(text) if sp.text]


def test_topic_is_read_only_on_plus_t_without_op_and_emoji_goes_into_input(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    srv.send(":Fhazal!f@h MODE #skinhead +t")
    srv.send(":Fhazal!f@h MODE #skinhead -o Badaboom")
    assert wait(app, lambda: "t" in b.modes and win.topic.edit.isReadOnly())
    assert not win.topic.set_btn.isEnabled() and "+t" in win.topic.edit.toolTip()
    srv.send(":Fhazal!f@h MODE #skinhead +o Badaboom")
    assert wait(app, lambda: not win.topic.edit.isReadOnly())
    # emoji button by the input box
    win.input.setText("best ")
    win.input.setCursorPosition(5)
    win._emoji_for_input()
    pop = win._emoji_popup
    pop.picked.emit("\U0001F918")
    assert win.input.text() == "best \U0001F918"
    pop.close()


def test_topic_bar_has_the_same_dark_background_as_other_boxes(live):
    """User: the new topic bar showed a greyish-brown default background (QTextEdit was not styled)."""
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    wait(app, lambda: False, 100)
    img = win.topic.edit.viewport().grab().toImage()
    corner = img.pixelColor(img.width() - 3, img.height() // 2).name()
    assert corner == win.cfg.theme.panel.lower()
    chat = win.chat.viewport().grab().toImage()
    assert chat.pixelColor(chat.width() - 3, 3).name() == win.cfg.theme.chat_bg.lower()   # chat keeps its own
