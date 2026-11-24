"""0.8.5: connect, reconnect and rejoin behave the way a standard client does (directly and through ZNC)."""
import time
from types import SimpleNamespace

from bchat import commands
from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import parse_line
from bchat.session import ACTION, CHANNEL, HILITE, Session

REAL = "*status!status@znc.in"          # how ZNC 1.7+ writes its *status lines


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def make(app, **net):
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)], **net), Config(nick="Belon", local_find=False))
    s.out = []
    s.send_raw = lambda line, secret=False, quiet=False: s.out.append(line)
    s._connect_next = lambda: None
    s._conn_gen += 1
    s._last_rx = time.time()
    s.want_connected = True
    s.state = "connected"
    s._welcomed = True
    s.nick = "Belon"
    return s


def joined(s, chan):
    feed(s, f":Belon!u@h JOIN {chan}", f":srv 353 Belon = {chan} :@Belon Ali", f":srv 366 Belon {chan} :End")


def joins(s):
    return [x for x in s.out if x.upper().startswith("JOIN")]


def texts(b):
    return [ln.text for ln in b.lines]


def drop(s):
    """The link goes down; the retry timer is stopped so nothing else runs."""
    s._on_disconnected()
    s._reconnect.stop()


def back(s):
    """The next connect is up again (before its 001)."""
    s._conn_gen += 1
    s.state = "connected"
    s._welcomed = False
    s._joins_sent = s._performed = False
    s.out.clear()


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


def catch_timers(monkeypatch, with_ms=False):
    """QTimer.singleShot calls made from now on are kept, not run (call the kept function to fire one)."""
    import bchat.session as sm
    timers = []
    shot = (lambda ms, fn: timers.append((ms, fn))) if with_ms else (lambda ms, fn: timers.append(fn))
    monkeypatch.setattr(sm, "QTimer", type("T", (), {"singleShot": staticmethod(shot)}))
    return timers


# --- 1: through ZNC, channel tabs the bouncer didn't rejoin --------------------------------------------------------

# --- 2: Perform / connect commands run like typed commands ----------------------------------------------------------

def test_connect_commands_run_as_typed(app):
    s = make(app, commands=["msg NickServ identify x", "/join #a", "/mode $me +x", "  "])
    ui = SimpleNamespace(plugins=SimpleNamespace(on_command=lambda t: False), cfg=s.cfg)
    ran = []

    def run(sess, text):
        ran.append(text)
        commands.run(ui, sess, sess.server_buffer, text)

    s.on_command = run
    s._perform(s._conn_gen)
    assert ran == ["/msg NickServ identify x", "/join #a", "/mode Belon +x"]
    assert "PRIVMSG NickServ :identify x" in s.out
    assert "JOIN #a" in s.out
    assert "MODE Belon +x" in s.out
    assert not any(x.lower().startswith("msg ") for x in s.out)       # never sent raw as 'msg ...'


def test_connect_commands_reach_aliases(app):
    s = make(app, commands=["/hello there"])
    ran = []
    s.on_command = lambda sess, text: ran.append(text)
    s._perform(s._conn_gen)
    assert ran == ["/hello there"]                 # the main window's command runner (aliases included) gets it
    assert not any(x.lower().startswith("hello") for x in s.out)


# --- 3a: away comes back after a reconnect -------------------------------------------------------------------------

def test_away_is_sent_again_after_reconnect(app):
    s = make(app)
    s.set_away(True, "lunch")
    feed(s, ":srv 306 Belon :You have been marked as being away")
    drop(s)
    back(s)
    feed(s, ":srv 001 Belon :Welcome")
    assert any(x.startswith("AWAY") and x.endswith("lunch") for x in s.out)


def test_back_before_reconnect_sends_no_away(app):
    s = make(app)
    s.set_away(True, "lunch")
    s.set_away(False)
    drop(s)
    back(s)
    feed(s, ":srv 001 Belon :Welcome")
    assert not any(x.startswith("AWAY") for x in s.out)


# --- 3b: channel keys are kept for the rejoin ----------------------------------------------------------------------

def test_key_from_our_join_is_used_on_rejoin(app):
    s = make(app)
    s.send("JOIN", "#k", "sekrit")
    joined(s, "#k")
    assert s.buffers["#k"].key == "sekrit"
    drop(s)
    back(s)
    s._join_all(s._conn_gen)
    assert joins(s) == ["JOIN #k sekrit"]


def test_key_from_mode_and_324(app):
    s = make(app)
    joined(s, "#k")
    b = s.buffers["#k"]
    feed(s, ":Op!o@h MODE #k +k newpw")
    assert b.key == "newpw"
    feed(s, ":Op!o@h MODE #k -k newpw")
    assert b.key == ""
    feed(s, ":srv 324 Belon #k +nkt listed")
    assert b.key == "listed"
    feed(s, ":srv 324 Belon #k +nt")
    assert b.key == ""


def test_learnt_key_fills_an_autojoin_entry_without_one(app):
    s = make(app, autojoin="#k,#open")
    joined(s, "#k")
    feed(s, ":Op!o@h MODE #k +k pw")
    drop(s)
    back(s)
    s._join_all(s._conn_gen)
    assert joins(s) == ["JOIN #k,#open pw"]


# --- 3c: channels we left are not rejoined -------------------------------------------------------------------------

def test_parted_channel_is_not_rejoined_and_stays_grey(app):
    s = make(app, autojoin="#a,#b")
    joined(s, "#a")
    joined(s, "#b")
    joined(s, "#c")
    feed(s, ":Belon!u@h PART #a :bye", ":Belon!u@h PART #c")
    drop(s)
    back(s)
    s._join_all(s._conn_gen)
    assert joins(s) == ["JOIN #b"]
    assert not s.buffers["#a"].joined and not s.buffers["#c"].joined     # the tabs stay, grey


def test_closed_channel_is_not_rejoined(app):
    s = make(app, autojoin="#a")
    joined(s, "#a")
    s.close_buffer(s.buffers["#a"])
    assert "PART #a" in " ".join(s.out)
    drop(s)
    back(s)
    s._join_all(s._conn_gen)
    assert joins(s) == []


def test_joining_again_makes_it_rejoin_once_more(app):
    s = make(app)
    joined(s, "#a")
    feed(s, ":Belon!u@h PART #a")
    joined(s, "#a")
    drop(s)
    back(s)
    s._join_all(s._conn_gen)
    assert joins(s) == ["JOIN #a"]


# --- 3d: one 'Disconnected' per outage, one 'Reconnected' ----------------------------------------------------------

def test_disconnected_once_per_outage_then_reconnected(app):
    s = make(app)
    joined(s, "#c")
    c = s.buffers["#c"]
    drop(s)
    s.state = "connecting"
    drop(s)                                        # try 1 failed
    s.state = "connecting"
    drop(s)                                        # try 2 failed
    assert [t for t in texts(c) if t.startswith("Disconnected")] == ["Disconnected."]
    assert not any("Reconnect try" in t for t in texts(c))
    srv = texts(s.server_buffer)
    assert sum(t.startswith("Disconnected") for t in srv) == 1          # QA BUG-1: once per outage here too
    assert any(t.startswith("Reconnect try 3 in") for t in srv)
    back(s)
    feed(s, ":srv 001 Belon :Welcome")
    assert texts(c).count("Reconnected.") == 1
    drop(s)                                        # a new outage: told again
    assert [t for t in texts(c) if t.startswith("Disconnected")] == ["Disconnected.", "Disconnected."]


# --- 3e: 433 / 437 before 001 ----------------------------------------------------------------------------------------

def test_437_before_welcome_tries_the_alternate_then_underscores(app):
    s = make(app)
    s.cfg.nick2 = "Bel2"
    s._welcomed = False
    feed(s, ":srv 437 * Belon :Nick/channel is temporarily unavailable")
    assert s.out[-1] == "NICK Bel2"
    feed(s, ":srv 433 * Bel2 :Nickname is already in use")
    assert s.out[-1] == "NICK Belon_"
    feed(s, ":srv 437 * Belon_ :Nick/channel is temporarily unavailable")
    assert s.out[-1] == "NICK Belon__"


def test_server_that_cuts_long_nicks_gets_a_new_nick_each_time(app):
    s = make(app)
    s.nick = s.cfg.nick = "LongNick12"
    s._welcomed = False
    feed(s, ":srv 433 * LongNick1 :Nickname is already in use")       # NICKLEN 9: it cut ours
    assert s.out[-1] == "NICK LongNick_"
    feed(s, ":srv 433 * LongNick_ :Nickname is already in use")
    assert s.out[-1] == "NICK LongNic__"


def test_437_for_a_channel_or_after_welcome_sends_no_nick(app):
    s = make(app)
    feed(s, ":srv 437 Belon #chan :Cannot join channel (temporarily unavailable)")
    feed(s, ":srv 437 Belon Other :Nick/channel is temporarily unavailable")
    assert not any(x.startswith("NICK") for x in s.out)


# --- 3f: /nick while waiting to reconnect ----------------------------------------------------------------------------

def test_nick_typed_while_offline_is_kept_for_the_next_connect(app):
    s = make(app)
    drop(s)
    s.out.clear()
    s.send("NICK", "Neo")
    assert s.nick == "Neo" and s._next_nick == "Neo"
    assert s.out == []
    assert any("next connect uses the nick Neo" in t for t in texts(s.server_buffer))
    back(s)
    s.nick = "Neo"
    feed(s, ":srv 001 Neo :Welcome")
    assert s._next_nick == ""


def test_nick_typed_while_waiting_is_used_on_the_real_reconnect(app):
    from fake_ircd import FakeIrcd
    srv = FakeIrcd()
    s = Session(NetworkConfig("N", [Server("127.0.0.1", srv.port)]), Config(nick="Belon", local_find=False, reconnect_delay=1))
    try:
        s.connect_to_network()
        assert wait(app, lambda: s.state == "connected" and srv.nick == "Belon")
        srv.welcomed, srv.user_seen, srv.nick = False, False, ""
        srv.drop()
        assert wait(app, lambda: s.state == "disconnected")
        s.send("NICK", "Neo")
        assert wait(app, lambda: s.state == "connected" and srv.nick == "Neo", 8000)
        assert s.nick == "Neo"
    finally:
        s.disconnect_from_network()
        srv.stop()


# --- 4: ZNC state ------------------------------------------------------------------------------------------------------

PLAY = [
    "@time=2026-11-19T01:00:00.000Z :Ali!u@h PRIVMSG #c :hello",
    "@time=2026-11-19T01:00:01.000Z :Ali!u@h PRIVMSG #c :\x01ACTION waves\x01",
    "@time=2026-11-19T01:00:02.000Z :Belon!u@h PRIVMSG #c :hi Ali",
]


def playback(s, lines):
    feed(s, ":***!znc@znc.in PRIVMSG #c :Buffer Playback...", *lines, ":***!znc@znc.in PRIVMSG #c :Playback Complete.")


def test_znc_kept_buffer_is_not_shown_twice(app):
    s = make(app)
    joined(s, "#c")
    c = s.buffers["#c"]
    playback(s, PLAY)
    shown = len(c.lines)
    assert any("3 lines" in t for t in texts(c))
    playback(s, PLAY)                              # AutoClearChanBuffer off: the same lines again
    assert len(c.lines) == shown
    playback(s, PLAY + ["@time=2026-11-19T01:05:00.000Z :Ali!u@h PRIVMSG #c :new one"])
    assert any("1 line from" in t for t in texts(c))
    assert texts(c).count("hello") == 1 and texts(c).count("new one") == 1


def test_same_text_at_another_time_is_still_shown(app):
    s = make(app)
    joined(s, "#c")
    c = s.buffers["#c"]
    playback(s, PLAY[:1])
    playback(s, ["@time=2026-11-19T02:00:00.000Z :Ali!u@h PRIVMSG #c :hello"])
    assert texts(c).count("hello") == 2


def test_own_echoed_action_and_notice_are_not_unread_or_alerts(app):
    s = make(app)
    joined(s, "#c")
    joined(s, "#d")
    s.current = s.buffers["#d"]
    c = s.buffers["#c"]
    c.unread = c.activity = 0                      # our own JOIN above counts as activity; start clean
    seen = []
    s.notify.connect(lambda b, kind: seen.append(kind))
    s.alert.connect(lambda b: seen.append("alert"))
    feed(s, ":Belon!u@h PRIVMSG #c :\x01ACTION waves at Belon\x01")
    feed(s, ":Belon!u@h NOTICE #c :a note for Belon")
    assert c.unread == 0 and c.activity == 0
    assert seen == []
    assert c.lines[-2].kind == ACTION and c.lines[-2].kind != HILITE
    feed(s, ":Ali!u@h PRIVMSG #c :\x01ACTION waves at Belon\x01")    # someone else: still a highlight
    assert c.lines[-1].kind == HILITE and c.unread == 1
    assert c.kind == CHANNEL


# --- 0.8.5: a bouncer is a normal server: BChat never joins for ZNC or reads its *status lines ------------------

def test_through_znc_381_and_connected_join_nothing(app, monkeypatch):
    s = make(app)
    s.bouncer = "ZNC"
    joined(s, "#in")
    s.buffer("#grey")
    s.away, s._away_msg = True, "out"
    timers = catch_timers(monkeypatch, with_ms=True)
    s.out.clear()
    feed(s, ":srv 381 Belon :You are now an IRC operator",
         f":{REAL} PRIVMSG Belon :Connected!",
         f":{REAL} PRIVMSG Belon :Disconnected from IRC. Reconnecting...",
         f":{REAL} PRIVMSG Belon :Error from server: Closing link")
    assert joins(s) == [] and timers == []
    b = s.buffers[s.fold("#in")]
    assert b.joined and len(b.users) == 2 and s.away


def test_own_disconnect_greys_and_empties_every_channel_direct_or_through_znc(app):
    """BChat's own link going down: every channel tab greys and its nick list empties, bouncer or not."""
    for bouncer in ("", "ZNC"):
        s = make(app)
        s.bouncer = bouncer
        joined(s, "#a")
        joined(s, "#b")
        assert all(s.buffers[s.fold(c)].users for c in ("#a", "#b"))
        drop(s)
        for c in ("#a", "#b"):
            b = s.buffers[s.fold(c)]
            assert b.joined is False, (bouncer, c)
            assert not b.users, (bouncer, c)
