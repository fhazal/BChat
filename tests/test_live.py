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
    assert wait(app, lambda: any("can't accept" in l.text for l in b.lines))


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
    assert not (d._items["Logging"].flags() & _Qt.ItemFlag.ItemIsEnabled)   # not built yet: greyed
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
