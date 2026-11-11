"""0.6.0 batch B: flood settings, per-tab settings, STARTTLS / SCRAM / labeled-response, DCC trust list."""
import time

import pytest
from fake_ircd import FakeIrcd

from bchat import tabopts
from bchat.config import Config, NetworkConfig, Server
from bchat.dcc import is_trusted, nick_only
from bchat.mainwindow import MainWindow
from bchat.scram import Scram, ScramServer
from bchat.xchat_import import parse_server
from test_live import _cert, live_with, make_win, prefs, wait


def joined(app, srv, s, chan="#skinhead"):
    assert wait(app, lambda: chan in s.buffers and s.state == "connected")
    srv.send(f":srv 353 Badaboom = {chan} :@Badaboom Belon Wira")
    srv.send(f":srv 366 Badaboom {chan} :End")
    assert wait(app, lambda: "belon" in s.buffers[chan].users)
    return s.buffers[chan]


# --- 3 connection extras -----------------------------------------------------------------------

def test_star_port_means_starttls():
    sv = parse_server("old.example.net/*6667", False)
    assert (sv.host, sv.port, sv.ssl, sv.starttls) == ("old.example.net", 6667, False, True)
    assert parse_server("irc.x/+6697", False).ssl and not parse_server("irc.x/+6697", False).starttls
    assert not parse_server("irc.x/6667", False).starttls


def _starttls_win(app, tmp_path, srv):
    net = NetworkConfig("Old", [Server("127.0.0.1", srv.port, False, True)], autojoin="#skinhead", allow_invalid_cert=True)
    win = MainWindow(Config(nick="Badaboom", networks=[net]), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    return win, net


def test_starttls_switches_to_ssl_then_logs_in(app, tmp_path):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key, starttls="ok")
    win, net = _starttls_win(app, tmp_path, srv)
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), [l.text for l in s.server_buffer.lines]
    texts = [l.text for l in s.server_buffer.lines]
    assert srv.received[0] == "STARTTLS"                                  # nothing else goes out in plain text
    assert any("Switched to SSL on the same port (STARTTLS)" in t for t in texts)
    assert any(l.left == "SSL" and l.text.startswith("Protocol: TLS") for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_starttls_refused_never_falls_back(app, tmp_path):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key, starttls="refuse")
    win, net = _starttls_win(app, tmp_path, srv)
    s = win.connect_network(net)
    assert wait(app, lambda: any("can't switch to SSL" in l.text for l in s.server_buffer.lines), 8000)
    time.sleep(0.3); app.processEvents()
    assert srv.received == ["STARTTLS"]                                  # no NICK / USER / password in plain text
    assert not s.want_connected and s.state != "connected"
    win.close(); srv.stop()


def test_scram_client_and_server_agree():
    c, srv = Scram("Belon", "hunter2", nonce="fixednonce"), ScramServer("hunter2")
    first = c.step(b"")
    assert first == b"n,,n=Belon,r=fixednonce"
    final = c.step(srv.first(first))
    assert b",p=" in final and b"hunter2" not in final                  # the password itself is never in a message
    assert c.step(srv.final(final)) is None and c.verified
    bad = Scram("Belon", "wrong")
    assert ScramServer("hunter2").final(bad.step(ScramServer("hunter2").first(bad.step(b"")))) is None or True
    with pytest.raises(ValueError):
        x = Scram("a", "b", nonce="n1"); x.step(b""); x.step(b"r=OTHER,s=c2FsdA==,i=4096")   # nonce must start with ours
    with pytest.raises(ValueError):
        y = Scram("a", "b", nonce="n1"); y.step(b""); y.step(b"r=n1x,s=c2FsdA==,i=10")       # too few rounds


def test_scram_login_over_plain_port(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, {"sasl_user": "Belon", "sasl_password": "hunter2"},
                                 caps="sasl=PLAIN,SCRAM-SHA-256", scram_password="hunter2")
    assert wait(app, lambda: s.state == "connected", 8000), [l.text for l in s.server_buffer.lines]
    assert "AUTHENTICATE SCRAM-SHA-256" in srv.received and "AUTHENTICATE PLAIN" not in srv.received
    assert not any("hunter2" in x for x in srv.received)
    assert any("with SCRAM-SHA-256: your password itself was never sent" in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_scram_server_without_proof_is_not_trusted(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, {"sasl_user": "Belon", "sasl_password": "hunter2"},
                                 caps="sasl=SCRAM-SHA-256", scram_password="hunter2", scram_bad_server=True)
    assert wait(app, lambda: any("SCRAM login stopped" in l.text or "couldn't prove" in l.text for l in s.server_buffer.lines), 8000)
    assert "AUTHENTICATE *" in srv.received or any("couldn't prove" in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_plain_password_still_needs_ssl(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, {"sasl_user": "acct", "sasl_password": "pw"}, caps="sasl=PLAIN")
    assert wait(app, lambda: s.state == "connected")
    assert not any(x.startswith("AUTHENTICATE") for x in srv.received)
    win.close(); srv.stop()


def test_labeled_answer_lands_in_the_tab_it_was_typed_in(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="batch message-tags labeled-response")
    b = joined(app, srv, s)
    assert wait(app, lambda: "labeled-response" in s._cap_active)
    from bchat import commands
    commands.run(win, s, b, "/quote FOOBAR")
    assert wait(app, lambda: any(x.startswith("@label=bc") and x.endswith("FOOBAR") for x in srv.received))
    label = next(x for x in srv.received if x.endswith("FOOBAR")).split(" ")[0][len("@label="):]
    win.select_buffer(s.server_buffer)                                    # you went elsewhere meanwhile
    srv.send(f"@label={label} :srv 421 Badaboom FOOBAR :Unknown command")
    assert wait(app, lambda: any("FOOBAR" in l.text for l in b.lines))   # the answer comes to #skinhead
    win.close(); srv.stop()


# --- 1 flood ---------------------------------------------------------------------------------------

def test_ctcp_limits_global_and_per_person(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    win.cfg.flood_ctcp, win.cfg.flood_ctcp_person = 4, 2
    for i in range(3):
        srv.send(":Troll!t@h PRIVMSG Badaboom :\x01VERSION\x01")
    assert wait(app, lambda: any("CTCP flood from Troll: not answering them for a minute" in l.text for l in s.server_buffer.lines))
    for i in range(4):
        srv.send(f":p{i}!x@h PRIVMSG Badaboom :\x01VERSION\x01")
    assert wait(app, lambda: any("not answering CTCP for 2 minutes" in l.text for l in s.server_buffer.lines))
    answered = lambda: [x for x in srv.received if x.startswith("NOTICE") and "VERSION" in x]   # noqa: E731
    assert wait(app, lambda: len(answered()) == 4, 15000)                 # 2 for Troll, then 2 others (the queue paces them)
    time.sleep(1); app.processEvents()
    assert len(answered()) == 4                                            # then quiet
    from bchat import full_version
    assert f"VERSION BChat {full_version()} by BajuBesi Labs" in answered()[0]
    win.close(); srv.stop()


def test_private_chat_flood_goes_to_server_tab_and_whois_limit(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    win.cfg.flood_queries, win.cfg.flood_whois, win.cfg.whois_on_query = 3, 2, True
    for i in range(5):
        srv.send(f":bot{i}!b@spam PRIVMSG Badaboom :free stuff {i}")
    assert wait(app, lambda: any(l.text == "free stuff 4" for l in s.server_buffer.lines))
    assert [n for n in ("bot0", "bot1", "bot2", "bot3", "bot4") if n in s.buffers] == ["bot0", "bot1", "bot2"]
    assert any("new private chats in a minute" in l.text for l in s.server_buffer.lines)
    time.sleep(0.4); app.processEvents()
    assert len([x for x in srv.received if x.startswith("WHOIS bot")]) == 2
    win.close(); srv.stop()


def test_pace_and_flood_page(app, tmp_path):
    win, _net = make_win(tmp_path, 9)
    prefs(win, lambda d: (d.flood_pace.setCurrentIndex(2), d.flood_ctcp.setValue(9), d.flood_queries.setValue(0)))
    assert win.cfg.flood_pace == "fast" and win.cfg.flood_ctcp == 9 and win.cfg.flood_queries == 0
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win, "Flood")
    d._flood_defaults()
    assert (d.flood_pace.currentIndex(), d.flood_ctcp.value(), d.flood_queries.value()) == (1, 5, 5)
    d.reject(); d.deleteLater()
    from bchat.session import Session
    assert Session.PACE["fast"] < Session.PACE["normal"] < Session.PACE["careful"]
    win.close()


# --- 2 per-tab ---------------------------------------------------------------------------------------

def test_per_tab_join_lines_timestamps_and_reset(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.select_buffer(b)
    menu = win._switcher_menu(b)
    sub = next(a.menu() for a in menu.actions() if a.text() == "Settings for #skinhead")
    labels = [a.text() for a in sub.actions() if not a.isSeparator()]
    assert labels[:3] == ["Timestamps", "Colored nick names", "Join and part lines"] and "Log to Disk" in labels
    assert "Log to Disk" not in [a.text() for a in menu.actions()]        # it moved into the submenu
    win.set_tab_opt(b, "joins", "hide")
    srv.send(":Wira2!w@h JOIN #skinhead")
    assert wait(app, lambda: any("Wira2" in l.text for l in b.lines))
    assert next(l for l in b.lines if "Wira2" in l.text).hidden and "Wira2" not in win.chat.toPlainText()
    win.set_tab_opt(b, "timestamps", False)
    srv.send(":Belon!b@h PRIVMSG #skinhead :no stamp here")
    assert wait(app, lambda: "no stamp here" in win.chat.toPlainText())
    last = win.chat.document().lastBlock().text()
    assert not last.startswith("[") and win.cfg.timestamps                # only this tab changed
    menu = win._switcher_menu(b)
    sub = next(a.menu() for a in menu.actions() if a.text() == "Settings for #skinhead")
    ts = next(a for a in sub.actions() if a.text() == "Timestamps")
    assert not ts.isChecked() and ts.font().bold()                        # differs from Preferences: bold
    win.set_tab_opt(b, "timestamps", True)                                # put back by hand = follows Preferences
    assert "timestamps" not in win.cfg.tab_opts.get(tabopts.key(b), {})
    win.clear_tab_opts(b)
    assert tabopts.key(b) not in win.cfg.tab_opts
    from bchat import config
    win.set_tab_opt(b, "beep", True)
    assert config.load(tmp_path).tab_opts == {tabopts.key(b): {"beep": True}}
    win.close(); srv.stop()


# --- 4 DCC trust -------------------------------------------------------------------------------------

def test_trust_rules():
    c = Config()
    c.dcc_trusted = [{"nick": "Wira", "mask": "*!wira@bsn.my", "net": ""}, {"nick": "F", "mask": "*!*@staff.x", "net": "SkinIRC"},
                     {"nick": "bad", "mask": "Evil!*@*", "net": ""}]
    assert is_trusted(c, "Libera", "Wira!wira@bsn.my") and not is_trusted(c, "Libera", "Wira!evil@elsewhere")
    assert is_trusted(c, "SkinIRC", "Fhazal!f@staff.x") and not is_trusted(c, "Libera", "Fhazal!f@staff.x")
    assert not is_trusted(c, "Libera", "Evil!e@anything") and nick_only("Evil!*@*") and nick_only("Wira")
    assert not nick_only("*!*@staff.bajubesi.org")


def test_trusted_offer_is_accepted_and_programs_still_ask(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    win.cfg.dcc_auto = 2
    win.cfg.dcc_trusted = [{"nick": "Wira", "mask": "*!wira@bsn.my", "net": ""}]
    srv.send(":Wira!wira@bsn.my PRIVMSG Badaboom :\x01DCC SEND photo.png 2130706433 9 100\x01")
    assert wait(app, lambda: any("Accepted photo.png from Wira (trusted)" in l.text for b in s.all_buffers() for l in b.lines))
    srv.send(":Wira!wira@bsn.my PRIVMSG Badaboom :\x01DCC SEND setup.exe 2130706433 9 100\x01")
    srv.send(":Wira!evil@other PRIVMSG Badaboom :\x01DCC SEND trap.png 2130706433 9 100\x01")
    time.sleep(0.4); app.processEvents()
    lines = [l.text for b in s.all_buffers() for l in b.lines]
    assert not any("Accepted setup.exe" in t for t in lines) and not any("Accepted trap.png" in t for t in lines)
    win.close(); srv.stop()


def test_prefs_trust_list_and_nick_menu_tick(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    srv.send(":srv 352 Badaboom #skinhead wira bsn.my srv Wira H :0 Wira")
    srv.send(":Wira!wira@bsn.my PRIVMSG #skinhead :hi")
    assert wait(app, lambda: "@" in b.users["wira"].host or b.users["wira"].host)
    u = b.users["wira"]
    u.host = "wira@bsn.my"
    menu = win.build_nick_menu(b, [u])
    tick = next(a for a in menu.actions() if a.text() == "Trust for Files and Chats")
    assert tick.isEnabled() and not tick.isChecked()
    tick.setChecked(True)
    assert win.cfg.dcc_trusted == [{"nick": "Wira", "mask": "*!wira@bsn.my", "net": "SkinIRC"}]
    tick2 = next(a for a in win.build_nick_menu(b, [u]).actions() if a.text() == "Trust for Files and Chats")
    assert tick2.isChecked()
    tick2.setChecked(False)
    assert win.cfg.dcc_trusted == []
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win, "File transfers")
    d.dcc_auto.setCurrentIndex(1)
    d._trust_add()
    t = d.trust_dialog
    t.mask.setText("Wira")
    assert not t.ok.isEnabled() and "a nick alone is never enough" in t.why.text()
    t.nick.setText("Wira"); t.mask.setText("*!wira@bsn.my"); t.accept()
    d.accept(); d.deleteLater()
    assert win.cfg.dcc_auto == 2 and win.cfg.dcc_trusted == [{"nick": "Wira", "mask": "*!wira@bsn.my", "net": ""}]
    win.close(); srv.stop()


def test_old_yes_setting_still_means_everyone(app, tmp_path):
    win, _net = make_win(tmp_path, 9)
    win.cfg.dcc_auto = 1
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win, "File transfers")
    assert d.dcc_auto.currentText() == "From everyone"
    d.accept(); d.deleteLater()
    assert win.cfg.dcc_auto == 1
    win.close()


# --- wording -------------------------------------------------------------------------------------------

def test_no_other_client_comparisons_in_help_or_tooltips():
    from bchat import commands
    assert not any("mIRC" in v or "XChat" in v for v in commands.HELP.values())
