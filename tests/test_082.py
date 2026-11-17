"""0.8.2 connect/disconnect: NickServ + commands + joins after the welcome text, numbered reconnect tries,
no reconnect after a KILL, a ban is not a password error, the server time-out setting, joins wait for NickServ."""
import json
import time

from bchat import config
from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import parse_line
from bchat.session import Session


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def texts(b):
    return [l.text for l in b.lines]


def make(app, **net):
    """A session that thinks it is online; every line it would send is kept in s.out."""
    n = NetworkConfig("N", [Server("127.0.0.1", 6667)], **net)
    s = Session(n, Config(nick="Belon", local_find=False))
    s.out = []
    s.send_raw = lambda line, secret=False, quiet=False: s.out.append(line)
    s._connect_next = lambda: None                      # no real sockets in these tests
    s._conn_gen += 1
    s._last_rx = time.time()
    s.want_connected = True
    return s


def welcome(s):
    feed(s, ":srv 001 Belon :Welcome", ":srv 005 Belon NETWORK=N :are supported")


def joins(s):
    return [l for l in s.out if l.upper().startswith("JOIN")]


# ---- fix 1: after the end of the welcome text, not at 001 ---------------------------------------------------

def test_identify_commands_and_joins_wait_for_the_end_of_the_motd(app):
    s = make(app, autojoin="#a,#b", commands=["/MODE Belon +x"], nickserv="pw", join_after_login=False)
    welcome(s)
    app.processEvents()
    assert not any("IDENTIFY" in l for l in s.out) and not joins(s)
    feed(s, ":srv 375 Belon :- motd -", ":srv 372 Belon :- hi", ":srv 376 Belon :End of /MOTD command.")
    assert not joins(s)                                  # a moment after, not on the same line
    assert wait(app, lambda: joins(s), 2500)
    order = [l.split(" ")[0].upper() if not l.startswith("PRIVMSG") else "IDENTIFY" for l in s.out
             if l.startswith(("PRIVMSG NickServ", "MODE", "JOIN"))]
    assert order == ["IDENTIFY", "MODE", "JOIN"]


def test_skip_motd_still_triggers_the_joins(app):
    s = make(app, autojoin="#a")
    s.cfg.skip_motd = True
    welcome(s)
    feed(s, ":srv 422 Belon :MOTD File is missing")
    assert wait(app, lambda: joins(s), 2500)


def test_no_motd_at_all_goes_ahead_after_5_seconds(app):
    s = make(app, autojoin="#a")
    welcome(s)
    t = time.time()
    assert wait(app, lambda: joins(s), 7000)
    assert time.time() - t > 4


def test_a_later_motd_does_not_join_twice(app):
    s = make(app, autojoin="#a")
    welcome(s)
    feed(s, ":srv 376 Belon :End of /MOTD command.")
    assert wait(app, lambda: joins(s), 2500)
    feed(s, ":srv 376 Belon :End of /MOTD command.")     # /motd typed later, or a bouncer replay
    wait(app, lambda: False, 1500)
    assert len(joins(s)) == 1


def test_an_old_connection_timer_does_nothing(app):
    s = make(app, autojoin="#a")
    welcome(s)
    feed(s, ":srv 376 Belon :End of /MOTD command.")
    s._conn_gen += 1                                     # reconnected before the timer fired
    wait(app, lambda: False, 1500)
    assert not joins(s)


# ---- fix 6: joins wait for NickServ ---------------------------------------------------------------------------

def test_joins_wait_for_nickserv_then_go_on_the_answer(app):
    s = make(app, autojoin="#a", nickserv="pw")
    welcome(s)
    feed(s, ":srv 376 Belon :End")
    assert wait(app, lambda: any("IDENTIFY" in l for l in s.out), 2500)
    assert "Waiting for NickServ before joining..." in texts(s.server_buffer)
    wait(app, lambda: False, 300)
    assert not joins(s)
    feed(s, ":NickServ!s@services NOTICE Belon :Password accepted - you are now recognized.")
    assert joins(s)


def test_joins_go_on_900_or_396(app):
    for line in (":srv 900 Belon Belon!u@h Belon :You are now logged in as Belon",
                 ":srv 396 Belon cloak.example :is now your displayed host"):
        s = make(app, autojoin="#a", nickserv="pw")
        welcome(s)
        feed(s, ":srv 376 Belon :End")
        assert wait(app, lambda: s._ns_wait, 2500)
        feed(s, line)
        assert joins(s), line


def test_nickserv_silent_joins_after_10_seconds(app):
    s = make(app, autojoin="#a", nickserv="pw")
    welcome(s)
    feed(s, ":srv 376 Belon :End")
    assert wait(app, lambda: s._ns_wait, 2500)
    t = time.time()
    assert wait(app, lambda: joins(s), 12000)
    assert time.time() - t > 9


def test_no_wait_when_turned_off_or_no_password_or_sasl_worked(app):
    for kw, sasl in (({"nickserv": "pw", "join_after_login": False}, False), ({}, False), ({"nickserv": "pw"}, True)):
        s = make(app, autojoin="#a", **kw)
        s._sasl_ok = sasl
        welcome(s)
        feed(s, ":srv 376 Belon :End")
        assert wait(app, lambda: joins(s), 2500), kw
        assert "Waiting for NickServ before joining..." not in texts(s.server_buffer)


# ---- fix 2: numbered tries, slower after 10, "Back after" ---------------------------------------------------

def test_reconnect_tries_are_numbered_and_slow_down_after_ten(app):
    s = make(app)
    s.cfg.reconnect_delay = 5
    assert s.reconnect_wait(1) == (5, "") and s.reconnect_wait(10) == (5, "")
    assert s.reconnect_wait(11) == (60, " (still down, trying less often)")
    s.state = "connecting"
    s._on_disconnected()
    assert "Reconnect try 1 in 5 seconds..." in texts(s.server_buffer)
    s._reconnect.stop()


def test_back_after_shows_how_long_the_link_was_down(app):
    s = make(app)
    welcome(s)
    s._drop_why = "closed by the server"
    s._on_disconnected()
    s._reconnect.stop()
    assert "Disconnected (closed by the server)." in texts(s.server_buffer)
    s._down_since -= 125
    s._tries = 3
    s._welcomed = False
    feed(s, ":srv 001 Belon :Welcome")
    assert "Connected. Back after 2 min." in texts(s.server_buffer)
    assert s._tries == 0 and not s._down_since


def test_old_10_second_default_becomes_5_but_a_chosen_delay_stays(tmp_path):
    for old, new in ((10, 5), (30, 30)):
        d = tmp_path / str(old)
        d.mkdir()
        (d / "config.json").write_text(json.dumps({"nick": "Belon", "reconnect_delay": old}), encoding="utf-8")
        cfg = config.load(d)
        assert cfg.reconnect_delay == new and cfg.reconnect_fast
    d = tmp_path / "again"                               # migrated once: a 10 the user sets later stays 10
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"nick": "Belon", "reconnect_delay": 10, "reconnect_fast": True}), encoding="utf-8")
    assert config.load(d).reconnect_delay == 10
    assert Config().reconnect_delay == 5 and Config().server_timeout == 180


# ---- fix 3: KILL ------------------------------------------------------------------------------------------------

def test_a_kill_of_us_stops_reconnecting(app):
    s = make(app)
    welcome(s)
    feed(s, ":Oper!o@srv KILL Belon :srv!Oper (flooding)")
    assert not s.want_connected
    assert "You were killed by Oper (srv!Oper (flooding))" in texts(s.server_buffer)
    s._on_disconnected()
    t = texts(s.server_buffer)
    assert "BChat won't reconnect after a kill. Use Server > Reconnect when you're ready." in t
    assert not any(x.startswith("Reconnect try") for x in t) and not s._reconnect.isActive()


def test_a_kill_before_the_welcome_is_us(app):
    s = make(app)
    s.state = "registering"
    feed(s, ":Oper!o@srv KILL * :srv!Oper (bye)")
    assert s._killed and not s.want_connected
    assert "You were killed by Oper (srv!Oper (bye))" in texts(s.server_buffer)


def test_a_kill_of_someone_else_changes_nothing(app):
    s = make(app)
    welcome(s)
    feed(s, ":Oper!o@srv KILL Other :srv!Oper (bye)")
    assert s.want_connected and not s._killed


# ---- fix 4: bans --------------------------------------------------------------------------------------------------

def test_465_is_a_ban_and_retries_every_minute(app):
    s = make(app)
    s.state = "registering"
    feed(s, ":srv 465 * :You are banned from this server (spam)", "ERROR :Closing Link: 127.0.0.1 (K-Lined)")
    t = texts(s.server_buffer)
    assert "Banned from this server: You are banned from this server (spam)" in t
    assert "BChat will try again every 60 seconds. Server > Disconnect stops it." in t
    assert s.want_connected and not any("password" in x.lower() for x in t)
    s._on_disconnected()
    assert "Reconnect try 1 in 60 seconds..." in texts(s.server_buffer)
    assert s._reconnect.remainingTime() > 55000
    s._reconnect.stop()


def test_ban_error_without_465(app):
    for text in ("Closing Link: 1.2.3.4 (G-Lined)", "Closing Link: x (Z-Lined: proxy)", "You are banned"):
        s = make(app)
        feed(s, f"ERROR :{text}")
        assert s._banned and s.want_connected, text


def test_464_is_still_a_password_error(app):
    s = make(app)
    feed(s, ":srv 464 * :Password incorrect")
    assert not s.want_connected and not s._banned
    assert any("will not retry" in x for x in texts(s.server_buffer))


def test_ban_message_shows_once_and_clears_when_welcomed(app):
    s = make(app)
    feed(s, ":srv 465 * :banned", ":srv 465 * :banned")
    assert sum(x.startswith("Banned from") for x in texts(s.server_buffer)) == 1
    welcome(s)
    assert not s._banned


# ---- fix 5: server time-out -----------------------------------------------------------------------------------

def test_server_timeout_setting(app):
    s = make(app)
    welcome(s)
    s.sock.abort = lambda: None
    s.cfg.server_timeout = 180
    s._last_rx = time.time() - 170
    s._tick()
    assert not any("No reply" in x for x in texts(s.server_buffer))
    s._last_rx = time.time() - 190
    s._tick()
    assert "No reply from the server for 3 minutes, so BChat closed the link." in texts(s.server_buffer)
    assert s._drop_why == "no reply"
    s.cfg.server_timeout = 60
    s._last_rx = time.time() - 70
    s._tick()
    assert "No reply from the server for 1 minute, so BChat closed the link." in texts(s.server_buffer)
    s.cfg.server_timeout = 90
    s._last_rx = time.time() - 100
    s._tick()
    assert "No reply from the server for 90 seconds, so BChat closed the link." in texts(s.server_buffer)


def test_preferences_and_network_edit_rows(app, tmp_path):
    from bchat.mainwindow import MainWindow
    from bchat.networklist import NetworkEditDialog
    from bchat.preferences import PreferencesDialog
    win = MainWindow(Config(nick="Belon", server_timeout=240, skip_network_list=True, welcome_done=True), tmp_path)
    win.skip_quit_prompt = True
    d = PreferencesDialog(win, "Advanced")
    assert d.server_timeout.value() == 240 and d.server_timeout.minimum() == 60 and d.server_timeout.maximum() == 600
    d.server_timeout.setValue(300)
    d.accept()
    assert win.cfg.server_timeout == 300
    net = NetworkConfig("N", [Server("h", 6667)], nickserv="pw")
    e = NetworkEditDialog(net, win)
    e.show()
    assert e.join_wait.isChecked() and e.join_wait.text() == "Join after the NickServ login (wait up to 10 s)"
    assert e.join_wait.isVisible()
    e.login.setCurrentIndex(1)
    assert not e.join_wait.isVisible()
    e.login.setCurrentIndex(0)
    e.join_wait.setChecked(False)
    e.accept()
    assert net.join_after_login is False
    win.close()
