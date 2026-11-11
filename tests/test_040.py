"""0.4.0: bouncer detection + playback, certificate login (SASL EXTERNAL), ChanServ Access, skip MOTD, short joins,
/partall, /online."""
import hashlib
import time

import pytest
from fake_ircd import FakeIrcd

from bchat import certs
from bchat.chanserv import NONE, OP, VOICE, AccessReader, ChanServAccess, commands as cs_commands
from bchat.networklist import NetworkEditDialog
from bchat.quitdialog import QuitDialog
from test_live import _cert, live_with, make_win, wait


def texts(b):
    return [l.text for l in b.lines]


def joined(app, srv, s, chan="#skinhead", op=True):
    assert wait(app, lambda: chan in s.buffers and s.state == "connected" and s.buffers[chan].joined)
    srv.send(f":srv 353 {s.nick} = {chan} :{'@' if op else ''}{s.nick} Belon Wira")
    srv.send(f":srv 366 {s.nick} {chan} :End")
    assert wait(app, lambda: "wira" in s.buffers[chan].users and s.own_rank(s.buffers[chan]) == ("@" if op else ""))
    return s.buffers[chan]


# --- certificates ---------------------------------------------------------------------------

def test_make_load_and_describe_a_certificate(tmp_path):
    p = certs.make(tmp_path / "certs" / f"{certs.safe_name('Skin IRC/1')}.pem", "Belon")
    assert p.name == "Skin_IRC_1.pem" and b"PRIVATE KEY" in p.read_bytes()
    cert, key = certs.load(str(p))
    assert not cert.isNull() and not key.isNull()
    name, made, fp = certs.describe(str(p))
    assert name == "Skin_IRC_1.pem" and made and len(fp.split(":")) == 32
    assert certs.short(fp).count("…") == 1
    assert certs.load(str(tmp_path / "nothing.pem")) is None
    (tmp_path / "only.crt").write_bytes(p.read_bytes().split(b"-----BEGIN PRIVATE KEY")[0])
    assert certs.load(str(tmp_path / "only.crt")) is None             # no key: can't log in with it


def test_certificate_login_uses_sasl_external_and_sends_no_password(app, tmp_path):
    crt, key = _cert(tmp_path)
    mine = certs.make(tmp_path / "mine.pem", "Badaboom")
    srv = FakeIrcd(crt, key, caps="sasl=PLAIN,EXTERNAL", client_ca=str(mine))
    win, net = make_win(tmp_path, srv.port, ssl=True, allow_invalid_cert=True, login="cert", cert_file=str(mine),
                        sasl_user="acct", sasl_password="hunter2")
    s = win.connect_network(net)
    assert wait(app, lambda: any("SASL login successful" in t for t in texts(s.server_buffer)), 8000), texts(s.server_buffer)
    assert "AUTHENTICATE EXTERNAL" in srv.received and "AUTHENTICATE +" in srv.received
    assert not any("hunter2" in x or "PLAIN" in x for x in srv.received if x.startswith("AUTHENTICATE"))
    assert any("Logging in with your certificate" in t for t in texts(s.server_buffer))
    # the server saw exactly the certificate BChat made (the fingerprint NickServ will know)
    assert srv.peer_der and hashlib.sha256(srv.peer_der).hexdigest() == certs.describe(str(mine))[2].replace(":", "")
    assert wait(app, lambda: s.state == "connected")
    win.close(); srv.stop()


def test_certificate_login_failure_says_what_to_do(app, tmp_path):
    crt, key = _cert(tmp_path)
    mine = certs.make(tmp_path / "mine.pem", "Badaboom")
    srv = FakeIrcd(crt, key, caps="sasl", sasl_ok=False, client_ca=str(mine))
    win, net = make_win(tmp_path, srv.port, ssl=True, allow_invalid_cert=True, login="cert", cert_file=str(mine))
    s = win.connect_network(net)
    assert wait(app, lambda: any("Certificate login failed" in t and "Add to NickServ" in t for t in texts(s.server_buffer)), 8000)
    assert wait(app, lambda: s.state == "connected")
    win.close(); srv.stop()


def test_certificate_login_needs_ssl_and_a_readable_file(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, {"login": "cert", "cert_file": str(tmp_path / "gone.pem")}, caps="sasl=EXTERNAL")
    assert wait(app, lambda: s.state == "connected")
    assert any("needs an SSL server" in t for t in texts(s.server_buffer))
    assert not any(x.startswith("AUTHENTICATE") for x in srv.received)
    assert not any("sasl" in x for x in srv.received if x.startswith("CAP REQ"))
    win.close(); srv.stop()
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key, caps="sasl=EXTERNAL")
    win, net = make_win(tmp_path, srv.port, ssl=True, allow_invalid_cert=True, login="cert", cert_file=str(tmp_path / "gone.pem"))
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000)
    assert any("couldn't read the certificate file" in t for t in texts(s.server_buffer))
    assert not any(x.startswith("AUTHENTICATE") for x in srv.received)
    win.close(); srv.stop()


def test_login_none_never_sends_the_sasl_password(app, tmp_path):
    crt, key = _cert(tmp_path)
    srv = FakeIrcd(crt, key, caps="sasl=PLAIN")
    win, net = make_win(tmp_path, srv.port, ssl=True, allow_invalid_cert=True, login="none", sasl_user="acct", sasl_password="pw")
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000)
    assert not any(x.startswith("AUTHENTICATE") for x in srv.received)
    win.close(); srv.stop()


def test_edit_network_log_in_with_rows_make_new_and_add_to_nickserv(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected")
    d = NetworkEditDialog(net, win)
    d.show()
    assert d.login.currentIndex() == 0                                  # no account yet: Nothing
    rows = lambda: (d.sasl_user.isVisible(), d.sasl_password.isVisible(), d.cert_box.isVisible(), d.nickserv_row.isVisible())  # noqa
    assert rows() == (False, False, False, False)
    d.login.setCurrentIndex(1)
    assert rows() == (True, True, False, False)
    d.login.setCurrentIndex(2)
    assert rows() == (False, False, True, True)
    assert "No certificate yet" in d.cert_label.text() and not d.cert_add.isEnabled() and not d.cert_copy.isEnabled()
    d.cert_new.click()
    path = tmp_path / "certs" / "SkinIRC.pem"
    assert path.exists() and d.cert_path == str(path)
    assert "SkinIRC.pem" in d.cert_label.text() and "SHA-256" in d.cert_label.text()
    assert d.cert_add.isEnabled()                                       # connected: the button works
    d.cert_copy.click()
    fp = certs.describe(str(path))[2].replace(":", "")
    from PySide6.QtWidgets import QApplication
    assert QApplication.clipboard().text() == fp
    d.cert_add.click()
    assert wait(app, lambda: f"PRIVMSG NickServ :CERT ADD {fp}" in srv.received)
    assert any(f"BChat sent: /msg NickServ CERT ADD {fp}" in t for t in texts(s.server_buffer))
    d.accept()
    assert net.login == "cert" and net.cert_file == str(path)
    d2 = NetworkEditDialog(net, win)
    assert d2.login.currentIndex() == 2
    d2.login.setCurrentIndex(0)
    d2.accept()
    assert net.login == "none"
    net.login, net.sasl_user = "", "acct"
    assert NetworkEditDialog(net, win).login.currentIndex() == 1        # older settings: an account = password login
    win.close(); srv.stop()


def test_add_to_nickserv_waits_for_a_connection(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected")
    s.disconnect_from_network()
    assert wait(app, lambda: s.state == "disconnected")
    net.login, net.cert_file = "cert", str(certs.make(tmp_path / "x.pem", "x"))
    d = NetworkEditDialog(net, win)
    assert not d.cert_add.isEnabled() and "connect first" in d.cert_hint.text()
    win.close(); srv.stop()


# --- bouncers -------------------------------------------------------------------------------

def test_znc_is_spotted_and_its_version_asked_quietly(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="znc.in/self-message znc.in/server-time-iso")
    assert wait(app, lambda: "PRIVMSG *status :version" in srv.received)
    assert s.bouncer == "ZNC"
    srv.send(":*status!znc@znc.in PRIVMSG Badaboom :ZNC 1.10.3 - https://znc.in")
    srv.send(":*status!znc@znc.in PRIVMSG Badaboom :IPv6: yes, SSL: yes, DNS: threads, charset: yes, i18n: no, Argon2: yes")
    srv.send(":srv NOTICE Badaboom :marker")
    assert wait(app, lambda: any("Connected through ZNC 1.10.3" in t for t in texts(s.server_buffer)))
    assert any("nothing shows twice" in t for t in texts(s.server_buffer))
    assert wait(app, lambda: any("marker" in t for bb in s.all_buffers() for t in texts(bb)))
    assert "*status" not in s.buffers                                   # both answer lines were taken, no tab opened
    assert not any(x.startswith("WHOIS") and "*status" in x for x in srv.received)
    assert sum("Connected through" in t for t in texts(s.server_buffer)) == 1
    tip = win.buffer_tip(s.server_buffer)
    assert "Through ZNC 1.10.3" in tip and "Online" in tip and "stay online" in tip
    q = QuitDialog(win, 1, [(net.name, s.bouncer)])
    assert q.stay.text() == "SkinIRC is through ZNC: you stay online there."
    win.close(); srv.stop()


def test_znc_module_chats_get_no_auto_whois(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="znc.in/self-message")
    assert wait(app, lambda: s.state == "connected")
    assert win.cfg.whois_on_query
    time.sleep(0.1)
    s._version_wait = 0.0                                                # long after the version question
    srv.send(":*status!znc@znc.in PRIVMSG Badaboom :You have 3 networks")
    srv.send(":Wira!w@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: "*status" in s.buffers and "wira" in s.buffers)
    assert wait(app, lambda: any(x.startswith("WHOIS Wira") for x in srv.received))      # people still get it
    assert not any(x.startswith("WHOIS") and "*status" in x for x in srv.received)
    win.close(); srv.stop()


def test_znc_without_a_version_answer_still_says_it_once(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="znc.in/self-message")
    assert wait(app, lambda: any("Connected through ZNC (a bouncer)" in t.replace("\x02", "") for t in texts(s.server_buffer)), 7000)
    win.close(); srv.stop()


def test_soju_and_plain_servers(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="soju.im/bouncer-networks")
    assert wait(app, lambda: any("Connected through soju" in t for t in texts(s.server_buffer)))
    assert not any("*status" in x for x in srv.received)
    win.close(); srv.stop()
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected")
    app.processEvents()
    assert s.bouncer == "" and not any("Connected through" in t for t in texts(s.server_buffer))
    assert "Through" not in win.buffer_tip(s.server_buffer) and "Online" in win.buffer_tip(s.server_buffer)
    win.close(); srv.stop()


def _iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_znc_playback_lines_get_one_header_and_now_live(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="znc.in/self-message server-time")
    b = joined(app, srv, s, op=False)
    t0 = time.time() - 3600
    srv.send(":***!znc@znc.in PRIVMSG #skinhead :Buffer Playback...")
    srv.send(f"@time={_iso(t0)} :Wira!w@h PRIVMSG #skinhead :anyone up?")
    srv.send(f"@time={_iso(t0 + 60)} :Aiman!a@h PRIVMSG #skinhead :morning")
    srv.send(":***!znc@znc.in PRIVMSG #skinhead :Playback Complete.")
    srv.send(":Wira!w@h PRIVMSG #skinhead :live one")
    assert wait(app, lambda: "live one" in texts(b))
    tx = texts(b)
    head = next(i for i, t in enumerate(tx) if "Played back by ZNC: 2 lines" in t)
    assert tx[head + 1] == "anyone up?" and tx[head + 2] == "morning" and "Now live" in tx[head + 3] and tx[head + 4] == "live one"
    assert not any("Buffer Playback" in t or "Playback Complete" in t for t in tx)
    assert abs(b.lines[head + 1].ts - t0) < 2                          # the real time, not now
    win.close(); srv.stop()


def test_znc_playback_batch(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="znc.in/self-message batch server-time")
    b = joined(app, srv, s, op=False)
    srv.send(":znc.in BATCH +p1 znc.in/playback #skinhead")
    srv.send("@batch=p1 :***!znc@znc.in PRIVMSG #skinhead :Buffer Playback...")
    srv.send("@batch=p1;time=2026-11-11T01:00:00.000Z :Wira!w@h PRIVMSG #skinhead :from the batch")
    srv.send("@batch=p1 :***!znc@znc.in PRIVMSG #skinhead :Playback Complete.")
    srv.send(":znc.in BATCH -p1")
    assert wait(app, lambda: any("Now live" in t for t in texts(b)))
    tx = texts(b)
    assert sum("Played back by ZNC: 1 line " in t for t in tx) == 1 and "from the batch" in tx
    assert not any("Buffer Playback" in t for t in tx)
    win.close(); srv.stop()


def test_znc_query_playback_goes_to_the_private_tab(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="znc.in/self-message")
    assert wait(app, lambda: s.state == "connected")
    srv.send(":***!znc@znc.in PRIVMSG Badaboom :Buffer Playback...")
    srv.send(":Wira!w@h PRIVMSG Badaboom :psst")
    srv.send(":***!znc@znc.in PRIVMSG Badaboom :Playback Complete.")
    assert wait(app, lambda: "wira" in s.buffers and "psst" in texts(s.buffers["wira"]))
    assert any("Played back by ZNC" in t for t in texts(s.buffers["wira"]))
    win.close(); srv.stop()


# --- small things -----------------------------------------------------------------------------

def test_skip_motd_and_motd_command(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: any("MOTD File is missing" in t for t in texts(s.server_buffer)))   # default: shown
    win.close(); srv.stop()
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    win.cfg.skip_motd = True
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected")
    srv.send(":srv 375 Badaboom :- srv Message of the Day -")
    srv.send(":srv 372 Badaboom :- hello there")
    srv.send(":srv 376 Badaboom :End of /MOTD command.")
    srv.send(":srv NOTICE Badaboom :after")
    assert wait(app, lambda: any("after" in t for t in texts(s.server_buffer)))
    assert not any("MOTD" in t or "hello there" in t for t in texts(s.server_buffer)), texts(s.server_buffer)
    win.select_buffer(s.server_buffer)
    win._run_with("/motd")
    assert wait(app, lambda: "MOTD" in srv.received)
    srv.send(":srv 372 Badaboom :- hello there")
    srv.send(":srv 376 Badaboom :End of /MOTD command.")
    assert wait(app, lambda: any("hello there" in t for t in texts(s.server_buffer)))
    assert not s.motd_asked
    win.close(); srv.stop()


def test_short_join_and_part_lines_keep_edited_events(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s, op=False)
    win.cfg.short_joins = True
    srv.send(":Aiman!~aiman@pc.tm.net.my JOIN #skinhead")
    srv.send(":Aiman!~aiman@pc.tm.net.my PART #skinhead :later")
    srv.send(":Joe!j@x.my PART #skinhead")
    assert wait(app, lambda: any("Joe" in t for t in texts(b)))
    tx = texts(b)
    assert "Aiman has joined" in tx and "Aiman has left (later)" in tx and "Joe has left" in tx
    assert not any("tm.net.my" in t for t in tx)
    win.cfg.text_events["Join"] = "-->$t$1 ($3) came in"                 # the user's own wording stays
    srv.send(":Zed!z@z.my JOIN #skinhead")
    assert wait(app, lambda: "Zed (z@z.my) came in" in texts(b))
    win.cfg.short_joins = False
    del win.cfg.text_events["Join"]
    srv.send(":Amy!a@a.my JOIN #skinhead")
    assert wait(app, lambda: "Amy (a@a.my) has joined #skinhead" in texts(b))
    win.close(); srv.stop()


def test_partall_and_online(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s, op=False)
    win._run_with("/join #two")
    assert wait(app, lambda: "#two" in s.buffers and s.buffers["#two"].joined)
    win.select_buffer(s.server_buffer)
    win._run_with("/partall bye all")
    assert wait(app, lambda: any(x.startswith("PART ") and "#skinhead" in x and "#two" in x and "bye all" in x for x in srv.received))
    assert any("Leaving 2 channels on SkinIRC: #skinhead #two" in t for t in texts(s.server_buffer))
    s.online_since = time.time() - (3 * 3600 + 12 * 60 + 5)
    win.started_at = time.time() - (3 * 3600 + 14 * 60)
    win._run_with("/online")
    tx = texts(s.server_buffer)
    assert any(t.startswith("Online on SkinIRC: 3 h 12 min (since ") for t in tx)
    assert "BChat running: 3 h 14 min" in tx
    assert "Online 3 h 12 min" in win.buffer_tip(s.server_buffer)
    win.close(); srv.stop()


def test_new_preferences_ticks_save(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    assert not d.skip_motd.isChecked() and not d.short_joins.isChecked()   # both off by default
    d.skip_motd.setChecked(True)
    d.short_joins.setChecked(True)
    d.accept()
    assert win.cfg.skip_motd and win.cfg.short_joins
    win.close(); srv.stop()


# --- ChanServ Access --------------------------------------------------------------------------

def test_access_reader_anope_and_atheme():
    r = AccessReader("anope", "#chat", "Wira")
    assert r.questions("#chat", "Wira") == ["AOP #chat LIST Wira", "VOP #chat LIST Wira"]
    assert r.feed("No matching entries on #chat access list.") and not r.done
    assert r.feed("VOP list for #chat") and r.feed("  Number  Mask") and r.feed("  3       Wira")
    assert r.done and r.now() == VOICE
    assert r.feed("  4       Wira2") and not r.feed("something else")
    r = AccessReader("anope", "#chat", "Wira")
    r.feed("#chat AOP list is empty."), r.feed("No matching entries on #chat access list.")
    assert r.now() == NONE
    r = AccessReader("anope", "#chat", "Wira")
    assert r.feed("Access denied.") and r.done and r.now() == ""
    r = AccessReader("atheme", "#chat", "Wira")
    assert r.feed("Flags for \x02Wira\x02 in \x02#chat\x02 are \x02+AOiv\x02.") and r.now() == OP
    r = AccessReader("atheme", "#chat", "Wira")
    assert r.feed("\x02Wira\x02 was not found on the access list of \x02#chat\x02.") and r.now() == NONE


def test_chanserv_commands_only_at_and_plus():
    assert cs_commands("anope", "#c", "W", OP, NONE) == ["AOP #c ADD W"]
    assert cs_commands("anope", "#c", "W", VOICE, OP) == ["VOP #c ADD W"]
    assert cs_commands("anope", "#c", "W", NONE, VOICE) == ["VOP #c DEL W"]
    assert cs_commands("anope", "#c", "W", NONE, "") == ["AOP #c DEL W", "VOP #c DEL W"]
    assert cs_commands("atheme", "#c", "W", OP, NONE) == ["FLAGS #c W +O-V"]
    assert cs_commands("atheme", "#c", "W", VOICE, NONE) == ["FLAGS #c W +V-O"]
    assert cs_commands("atheme", "#c", "W", NONE, VOICE) == ["FLAGS #c W -*"]


def _menu_texts(menu):
    out = []
    for a in menu.actions():
        out.append(a.text())
        if a.menu():
            out += [">" + t for t in _menu_texts(a.menu())]
    return out


def test_nick_menu_chanserv_access_needs_op(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s, op=False)
    wira = b.users["wira"]
    tx = _menu_texts(win.build_nick_menu(b, [wira]))
    assert ">ChanServ Access... (you need @ in #skinhead)" in tx
    srv.send(":srv MODE #skinhead +o Badaboom")
    assert wait(app, lambda: s.own_rank(b) == "@")
    menu = win.build_nick_menu(b, [wira])
    ops = next(a.menu() for a in menu.actions() if a.text() == "Operator Actions")
    acc = next(a for a in ops.actions() if a.text() == "ChanServ Access...")
    assert acc.isEnabled()
    assert not any("ChanServ" in t for t in _menu_texts(win.build_nick_menu(b, [wira, b.users["belon"]])))   # one person only
    win.close(); srv.stop()


def test_chanserv_access_window_asks_quietly_then_applies(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.select_buffer(b)
    win.open_chanserv_access(b, b.users["wira"])
    d = win.chanserv_window
    assert wait(app, lambda: "PRIVMSG ChanServ :\x01VERSION\x01" in srv.received)
    assert not d.apply_btn.isEnabled() and "Finding out" in d.sends.text()
    srv.send(":ChanServ!s@services.bajubesi.org NOTICE Badaboom :\x01VERSION Anope-2.0.20 services.bajubesi.org :unreal4\x01")
    assert wait(app, lambda: "PRIVMSG ChanServ :VOP #skinhead LIST Wira" in srv.received)
    assert "PRIVMSG ChanServ :AOP #skinhead LIST Wira" in srv.received and s.services == "anope"
    srv.send(":ChanServ!s@services.bajubesi.org NOTICE Badaboom :No matching entries on #skinhead access list.")
    srv.send(":ChanServ!s@services.bajubesi.org NOTICE Badaboom :No matching entries on #skinhead access list.")
    assert wait(app, lambda: d.now_label.text() == "Now: no access")
    assert not any("No matching" in t for bb in s.all_buffers() for t in texts(bb))     # the quiet answers were taken
    assert "/msg ChanServ VOP #skinhead ADD Wira" in d.sends.text() and d.apply_btn.isEnabled()
    d.radios[OP].setChecked(True)
    assert "AOP #skinhead ADD Wira" in d.sends.text()
    d.radios[NONE].setChecked(True)
    assert not d.apply_btn.isEnabled()                                  # already no access: nothing to send
    d.radios[VOICE].setChecked(True)
    d.apply_btn.click()
    assert wait(app, lambda: "PRIVMSG ChanServ :VOP #skinhead ADD Wira" in srv.received)
    assert "\x0314BChat sent: /msg ChanServ VOP #skinhead ADD Wira" in texts(b)
    assert s.chanserv_sink is None
    srv.send(":ChanServ!s@services.bajubesi.org NOTICE Badaboom :\x02Wira\x02 added to #skinhead VOP list.")
    assert wait(app, lambda: any("added to #skinhead VOP list" in t for t in texts(b)))   # answers show again
    win.close(); srv.stop()


def test_chanserv_access_without_services_answer_and_not_logged_in(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    s._cap_active.add("account-notify")                                 # the server tells us who's logged in
    win.open_chanserv_access(b, b.users["wira"])                         # Wira has no account
    d = win.chanserv_window
    assert "isn't logged in to NickServ" in d.acct.text() and not d.apply_btn.isEnabled()
    assert not any("ChanServ" in x for x in srv.received)
    d.reject()
    b.users["wira"].account = "WiraAcct"
    win.open_chanserv_access(b, b.users["wira"])
    d = win.chanserv_window
    assert wait(app, lambda: s.services == "anope", 6000) and s.services_guessed      # no VERSION answer: Anope
    assert wait(app, lambda: "PRIVMSG ChanServ :AOP #skinhead LIST WiraAcct" in srv.received)
    assert wait(app, lambda: "didn't say" in d.now_label.text(), 7000)              # no list answer either
    d.radios[NONE].setChecked(True)
    assert d.lines() == ["AOP #skinhead DEL WiraAcct", "VOP #skinhead DEL WiraAcct"]
    win.close(); srv.stop()
