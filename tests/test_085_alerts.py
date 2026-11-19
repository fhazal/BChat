"""0.8.5 alerts, friends, whois, CTCP and list fixes: bouncer playback is quiet, highlights see through colour codes,
the friends list survives reconnects and big lists, odd server lines can't break the read loop, CTCP is safer."""
import re
import time
from types import SimpleNamespace

from PySide6.QtNetwork import QAbstractSocket

from bchat import commands
from bchat.config import Config, NetworkConfig, Server
from bchat.highlights import word_hit
from bchat.protocol import parse_line
from bchat.session import Session

ZNC = "***!znc@znc.in"


class Sock:
    """Stands in for the TCP socket: everything sent is kept, nothing leaves the PC."""
    def __init__(self):
        self.out: list[str] = []

    def state(self):
        return QAbstractSocket.SocketState.ConnectedState

    def abort(self):
        pass

    def write(self, data):
        self.out.append(data.decode("utf-8")[:-2])
        return len(data)


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def session(nick="Fhazal"):
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)]), Config(nick=nick))
    s.nick = nick
    s.sock = Sock()
    s._last_rx = time.time()
    return s


def inside(chan="#skinhead"):
    s = session()
    feed(s, f":Fhazal!u@h JOIN {chan}", f":srv 353 Fhazal = {chan} :Fhazal Psycho Bombus",
         f":srv 366 Fhazal {chan} :End of /NAMES list.")
    return s, s.buffers[s.fold(chan)]


def events(s):
    seen = {"notify": [], "alert": []}
    s.notify.connect(lambda b, kind: seen["notify"].append(kind))
    s.alert.connect(lambda b: seen["alert"].append(b.name))
    return seen


def texts(b):
    return [ln.text for ln in b.lines]


# --- 1 bouncer playback: shown, counted and logged, but no sound/flash/tray/pop-up -------------------

def test_playback_makes_no_notify_or_alert_but_counts_unread(app):
    s, b = inside()
    seen = events(s)
    feed(s, f":{ZNC} PRIVMSG #skinhead :Buffer Playback...",
         ":Psycho!p@h PRIVMSG #skinhead :old line",
         ":Psycho!p@h PRIVMSG #skinhead :hey Fhazal, you there?",
         ":Psycho!p@h NOTICE #skinhead :an old notice",
         f":{ZNC} PRIVMSG #skinhead :Playback Complete.")
    assert "old line" in texts(b) and "hey Fhazal, you there?" in texts(b)
    assert seen == {"notify": [], "alert": []}
    assert b.unread >= 2 and b.mentioned                  # the highlight still marks the tab
    assert s._replaying is False
    feed(s, ":Psycho!p@h PRIVMSG #skinhead :Fhazal live now")     # after playback: alerts as usual
    assert seen["notify"] == ["hilight"] and seen["alert"] == ["#skinhead"]


def test_playback_private_lines_and_ctcp_are_not_answered(app):
    s, _ = inside()
    seen = events(s)
    feed(s, f":{ZNC} PRIVMSG Fhazal :Buffer Playback...",
         ":Bob!b@h PRIVMSG Fhazal :you missed this",
         ":Bob!b@h PRIVMSG Fhazal :\x01VERSION\x01",
         f":{ZNC} PRIVMSG Fhazal :Playback Complete.")
    assert "you missed this" in texts(s.buffers[s.fold("Bob")])
    assert seen["notify"] == [] and seen["alert"] == []
    assert not any("VERSION" in x for x in s.sock.out)


def test_playback_flag_resets_after_an_error(app):
    s, b = inside()
    s._handle = lambda m: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        s._show_playback("#skinhead", [parse_line(":Psycho!p@h PRIVMSG #skinhead :x")])
    except RuntimeError:
        pass
    assert s._replaying is False


# --- 2 highlights ----------------------------------------------------------------------------------

def test_highlight_through_colour_codes_and_any_punctuation():
    for text in ("\x0304Badaboom\x03 hi", "\x02Badaboom\x02", "Badaboom-san", "Badaboom: hi", "(Badaboom)",
                 "hi Badaboom!", "@Badaboom", "\x1fBadaboom\x1f's"):
        assert word_hit(text, "Badaboom"), text
    for text in ("Badaboomx", "xBadaboom", "Badaboom2"):
        assert not word_hit(text, "Badaboom"), text


def test_highlight_wildcards():
    assert word_hit("server restarting soon", "restart*")
    assert word_hit("(restarting), sorry", "restart*")
    assert word_hit("\x0304restarted\x03", "restart*")
    assert not word_hit("we start now", "restart*")


# --- 3 friends (notify list) -----------------------------------------------------------------------

def test_monitor_lines_stay_under_512_bytes():
    nicks = [f"friend{i:03d}_longername" for i in range(120)]
    lines = Session._monitor_lines(nicks)
    assert len(lines) > 1
    assert all(len(ln.encode()) + 2 <= 512 for ln in lines)
    assert [n for ln in lines for n in ln.removeprefix("MONITOR + ").split(",")] == nicks


def test_monitor_list_full_734_is_shown(app):
    s = session()
    feed(s, ":srv 734 Fhazal 100 Carl,Dave :Monitor list is full.")
    assert any("at most 100" in t and "Carl, Dave" in t for t in texts(s.server_buffer))


def test_friend_online_line_again_after_reconnect(app):
    s = session()
    s.cfg.friends = ["Bob"]
    seen = events(s)
    s._friend_online("Bob", True)
    s._friend_online("Bob", True)
    assert seen["notify"].count("friend") == 1
    feed(s, ":srv 001 Fhazal :Welcome")                # a reconnect: what we knew is old news
    assert not s._ison_asked
    s._friend_online("Bob", True)
    assert seen["notify"].count("friend") == 2


def test_typed_ison_gives_no_false_offline_line(app):
    s = session()
    s.cfg.friends = ["Bob"]
    s._friend_online("Bob", True)
    s.state = "connected"
    s.poll_friends()                                    # its answer never comes: the link drops
    feed(s, ":srv 001 Fhazal :Welcome")                 # reconnected: the old question is forgotten
    s.send_raw("ISON Carl")                             # typed /ison: its answer is shown, not read as friends
    feed(s, ":srv 303 Fhazal :")
    assert s.friend_state[s.fold("Bob")]["online"]
    assert not any("offline" in t.lower() for t in texts(s.server_buffer))


def test_friends_ison_still_marks_offline(app):
    s = session()
    s.cfg.friends = ["Bob"]
    s._friend_online("Bob", True)
    s._ison_asked.append([s.fold("Bob")])
    feed(s, ":srv 303 Fhazal :")
    assert not s.friend_state[s.fold("Bob")]["online"]


# --- 4 robustness ---------------------------------------------------------------------------------

def test_317_with_words_instead_of_seconds(app):
    s = session()
    s.whois("Bob")
    feed(s, ":srv 317 Fhazal Bob abc 123 :seconds idle")
    feed(s, ":srv 318 Fhazal Bob :End of /WHOIS list.")
    assert any("End of WHOIS" in t for t in texts(s.server_buffer))


def test_a_line_that_breaks_a_handler_does_not_stop_the_read_loop(app, monkeypatch):
    import sys
    s = session()
    hooked = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: hooked.append(a[0]))
    real = s._handle

    def handle(m):
        if m.command == "BOOM":
            raise ValueError("bad line")
        real(m)
    s._handle = handle
    s._rx.extend([b":srv BOOM x", b":Bob!b@h PRIVMSG Fhazal :still here"])
    s._drain(everything=True)
    assert hooked == [ValueError]
    assert "still here" in texts(s.buffers[s.fold("Bob")])


def test_001_without_nick_and_kick_without_target(app):
    s, b = inside()
    feed(s, ":srv 001")
    assert s.nick == "Fhazal"
    feed(s, ":Psycho!p@h KICK #skinhead")
    assert b.joined


# --- 5 whois / whowas / 433 ------------------------------------------------------------------------

def test_whowas_stays_in_the_tab_it_was_typed_in(app):
    s, b = inside()
    s.current = b
    feed(s, ":srv 314 Fhazal Gone ident host.example * :Gone Person",
         ":srv 369 Fhazal Gone :End of WHOWAS")
    assert any("was (ident@host.example): Gone Person" in t for t in texts(b))
    assert any("End of WHOWAS list." in t for t in texts(b))


def test_background_whois_stays_apart_from_a_visible_one(app):
    s, b = inside()
    s.state = "connected"
    s.silent_whois("Psycho")
    s.whois("Bombus", b)
    feed(s, ":srv 311 Fhazal Psycho p host * :Psycho Real",
         ":srv 311 Fhazal Bombus bo host2 * :Bombus Real",
         ":srv 318 Fhazal Psycho :End of /WHOIS list.")
    assert s.fold("Psycho") not in s._silent_whois           # finished, not pending
    assert s._whois_nick == s.fold("Bombus")                 # the visible one is still open
    assert not any("Psycho Real" in t for t in texts(b))
    assert any("Bombus Real" in t for t in texts(b))
    feed(s, ":srv 318 Fhazal Bombus :End of /WHOIS list.")
    assert s._whois_nick == "" and s._whois_target is None


def test_433_names_the_nick(app):
    s = session()
    s._welcomed = True
    feed(s, ":srv 433 Fhazal Bob :Nickname is already in use")
    assert any("Nick Bob is already in use" in t for t in texts(s.server_buffer))


# --- 6 encoding -----------------------------------------------------------------------------------

def test_non_utf8_falls_back_to_cp1252():
    assert Session._decode("it’s €5".encode("cp1252")) == "it’s €5"
    assert Session._decode("café".encode("utf-8")) == "café"
    assert Session._decode(b"\x81\x8d") == "\x81\x8d"           # bytes cp1252 leaves out still decode


# --- 7 CTCP ---------------------------------------------------------------------------------------

def test_own_ctcp_echoed_by_bouncer_is_not_answered(app):
    s = session()
    feed(s, ":Fhazal!u@h PRIVMSG Bob :\x01VERSION\x01")
    assert not any(x.startswith("NOTICE") for x in s.sock.out)


def test_own_dcc_offer_makes_no_offer(app):
    s = session()
    offers = []
    s.on_dcc = lambda *a: offers.append(a)
    feed(s, ":Fhazal!u@h PRIVMSG Bob :\x01DCC SEND f.txt 2130706433 5000 10\x01",
         ":Fhazal!u@h PRIVMSG Fhazal :\x01DCC SEND f.txt 2130706433 5000 10\x01")
    assert offers == []
    feed(s, ":Bob!b@h PRIVMSG Fhazal :\x01DCC SEND f.txt 2130706433 5000 10\x01")
    assert len(offers) == 1


def test_finger_userinfo_source_and_clientinfo(app):
    s = session()
    s.cfg.realname = "Fhaz Real"
    real = s._identity("real")
    for verb in ("FINGER", "USERINFO", "SOURCE", "CLIENTINFO"):
        feed(s, f":Bob{verb}!b@h PRIVMSG Fhazal :\x01{verb}\x01")
    out = s.sock.out
    assert f"NOTICE BobFINGER :\x01FINGER {real}\x01" in out
    assert f"NOTICE BobUSERINFO :\x01USERINFO {real}\x01" in out
    assert "NOTICE BobSOURCE :\x01SOURCE BChat by BajuBesi Labs\x01" in out
    assert any("CLIENTINFO" in x and "FINGER" in x and "SOURCE" in x and "USERINFO" in x for x in out)


def test_own_ping_is_never_blocked_by_the_flood_guard(app):
    s = session()
    s._ctcp_ignored[s.fold("Bob")] = time.time() + 30   # Bob went past his share; we never are
    s._ctcp_ignored[s.fold("Fhazal")] = time.time() + 30
    feed(s, ":Fhazal!u@h PRIVMSG Fhazal :PING 12345")
    assert "NOTICE Fhazal :PING 12345" in s.sock.out
    feed(s, ":Bob!b@h PRIVMSG Fhazal :PING 12345")
    assert "NOTICE Bob :PING 12345" not in s.sock.out


def test_ping_reply_in_milliseconds(app):
    s = session()
    s.send("PRIVMSG", "Bob", "\x01PING\x01")          # /ctcp Bob PING: the time goes with it
    sent = s.sock.out[-1]
    m = re.fullmatch(r"PRIVMSG Bob :\x01PING (\d+)\x01", sent)
    assert m and abs(int(m.group(1)) - time.time()) < 5
    feed(s, f":Bob!b@h NOTICE Fhazal :\x01PING {m.group(1)}\x01")
    assert any(re.fullmatch(r"PING reply from Bob: \d+\.\d{3} s", t) for t in texts(s.server_buffer))
    feed(s, f":Carl!c@h NOTICE Fhazal :\x01PING {int(time.time()) - 3}\x01")    # not ours: the time inside counts
    line = next(t for t in texts(s.server_buffer) if t.startswith("PING reply from Carl"))
    assert 2.5 < float(line.split(": ")[1].removesuffix(" s")) < 5
    feed(s, ":Dave!d@h NOTICE Fhazal :\x01PING hello\x01", ":Ed!e@h NOTICE Fhazal :\x01PING nan\x01")
    assert "CTCP PING reply from Dave: hello" in texts(s.server_buffer)
    assert "CTCP PING reply from Ed: nan" in texts(s.server_buffer)


def test_ctcp_command_ping_without_argument_sends_a_time(app):
    s, b = inside()
    ui = SimpleNamespace(plugins=SimpleNamespace(on_command=lambda t: False), cfg=s.cfg)
    commands.run(ui, s, b, "/ctcp Bob PING")
    assert any(re.fullmatch(r"PRIVMSG Bob :\x01PING \d{9,}\x01", x) for x in s.sock.out)
    commands.run(ui, s, b, "/ctcp Bob PING mine")
    assert "PRIVMSG Bob :\x01PING mine\x01" in s.sock.out


def busy(s):
    """A connected session whose paced queue already holds more than 400 bytes that can't leave yet."""
    s.state = "connected"
    s._next_send = time.time() + 100
    s._queue[:] = ["PRIVMSG #skinhead :" + "a" * 200] * 2
    assert s._pending_bytes() > 400
    return s


def notices(s):
    return [x.split(" ")[1] for x in s.sock.out if x.startswith("NOTICE ")]


def test_ctcp_flood_buffer_works_like_the_flood_command(app):
    """Defaults from the help's example, /flood 200 10 2 30, with the help's 400-byte trigger: past 400 bytes replies are
    buffered, 10 lines at most, 2 per person, a person past that is ignored for 30 s, and the buffer goes out fairly."""
    s = busy(session())
    c = s.cfg
    assert (c.flood_on, c.flood_ctcp_on, c.flood_bytes, c.flood_lines, c.flood_per_user, c.flood_ignore) == (True, True, 400, 10, 2, 30)
    feed(s, *[":Troll!t@h PRIVMSG Fhazal :VERSION"] * 3)
    assert notices(s) == [] and len(s._flood_lines[s.fold("Troll")]) == 2
    assert any("holding back CTCP replies" in t for t in texts(s.server_buffer))
    assert "CTCP flood from Troll: ignoring their CTCP for 30 seconds." in texts(s.server_buffer)
    assert not s._ctcp_allowed("Troll", time.time() + 20) and s._ctcp_allowed("Other", time.time())
    feed(s, *[f":p{i}!x@h PRIVMSG Fhazal :VERSION" for i in range(10)])
    assert sum(len(q) for q in s._flood_lines.values()) == 10                   # p8 and p9 were dropped
    assert s.fold("p8") not in s._flood_lines and s.fold("p9") not in s._flood_lines
    s._queue[:] = []
    for _ in range(30):                                                          # the queue drains, a few lines at a time
        s._next_send = 0.0
        s._drain_queue()
        if not s._queue and not s._flood_lines:
            break
    assert notices(s) == ["Troll"] + [f"p{i}" for i in range(8)] + ["Troll"]    # one each in turn, nobody hogs it
    assert any("send queue is empty, answering CTCP again" in t for t in texts(s.server_buffer))
    assert s._ctcp_allowed("Troll", time.time() + 31)                            # the 30 s are over


def test_flood_protection_never_holds_typed_lines_and_can_be_turned_off(app):
    s = busy(session())
    feed(s, ":Bob!b@h PRIVMSG Fhazal :TIME")
    assert s._flood_lines
    with s.typed():
        s.send("PRIVMSG", "#skinhead", "my own line")
    assert "PRIVMSG #skinhead :my own line" in s.sock.out                        # straight out, never held or dropped
    for off in ({"flood_on": False}, {"flood_ctcp_on": False}):
        t = busy(session())
        for k, v in off.items():
            setattr(t.cfg, k, v)
        feed(t, ":Bob!b@h PRIVMSG Fhazal :TIME")
        assert not t._flood_lines and any(x.startswith("NOTICE Bob :TIME") for x in t._queue)
    u = busy(session())
    u.cfg.flood_ignore = 0                                                        # 0 = no ignore, the extra ones are just dropped
    feed(u, *[":Troll!t@h PRIVMSG Fhazal :VERSION"] * 4)
    assert not u._ctcp_ignored and len(u._flood_lines[u.fold("Troll")]) == 2


def test_reply_list_answers_go_through_the_flood_buffer(app):
    """TIME and PING are answered by the reply list (/nctcp ...): those answers are held and capped the same way."""
    s = busy(session())
    ui = SimpleNamespace(plugins=SimpleNamespace(on_command=lambda t: False), cfg=s.cfg)
    s.on_command = lambda sess, text: commands.run(ui, sess, sess.server_buffer, text)
    feed(s, *[":Troll!t@h PRIVMSG Fhazal :TIME"] * 3)
    held = s._flood_lines[s.fold("Troll")]
    assert len(held) == 2 and all(x.startswith("NOTICE Troll :TIME ") for x in held)
    assert "CTCP flood from Troll: ignoring their CTCP for 30 seconds." in texts(s.server_buffer)
    with s.typed():
        commands.run(ui, s, s.server_buffer, "/nctcp Troll TIME my own")       # typed by the user: straight out
    assert "NOTICE Troll :TIME my own" in s.sock.out


def test_flood_guard_never_drops_an_incoming_dcc_offer(app):
    """Flood protection only limits our replies: a DCC SEND is an incoming offer, so even someone the guard is ignoring
    gets every offer through (the DCC code decides what to do with it)."""
    s = busy(session())
    offers = []
    s.on_dcc = lambda sess, nick, rest: offers.append((nick, rest))
    feed(s, *[":Belon!b@h PRIVMSG Fhazal :\x01VERSION\x01"] * 3)
    assert not s._ctcp_allowed("Belon", time.time())                             # Belon is now on the 30 s CTCP ignore
    feed(s, *[f":Belon!b@h PRIVMSG Fhazal :\x01DCC SEND f{i}.txt 2130706433 5000 10\x01" for i in range(3)])
    assert [n for n, _ in offers] == ["Belon"] * 3 and offers[2][1].startswith("SEND f2.txt ")
    assert len(s._flood_lines[s.fold("Belon")]) == 2                             # the offers took no reply slot


def test_flood_command(app):
    s, b = inside()
    saved = []
    ui = SimpleNamespace(plugins=SimpleNamespace(on_command=lambda t: False), cfg=s.cfg, save_config=lambda: saved.append(1))
    commands.run(ui, s, b, "/flood -c off 200 5 1 60")
    c = s.cfg
    assert (c.flood_ctcp_on, c.flood_on, c.flood_bytes, c.flood_lines, c.flood_per_user, c.flood_ignore) == (False, False, 200, 5, 1, 60)
    assert saved
    commands.run(ui, s, b, "/flood +c on")
    assert c.flood_ctcp_on and c.flood_on and c.flood_bytes == 200
    busy(s)
    feed(s, ":Bob!b@h PRIVMSG Fhazal :TIME")
    s._ctcp_ignored["x"] = time.time() + 60
    commands.run(ui, s, b, "/flood clear")
    assert not s._flood_lines and not s._ctcp_ignored
    assert "Flood buffer cleared (1 held reply dropped)." in texts(b)
    commands.run(ui, s, b, "/flood")
    assert texts(b)[-1].startswith("Flood protection is on, CTCP replies included: after 200 bytes, 5 lines, 1 per user")
    commands.run(ui, s, b, "/flood 1 2")
    assert texts(b)[-1].startswith("Usage: FLOOD [+c|-c] [on|off|clear]") and c.flood_bytes == 200


# --- 8 /kickban reason -----------------------------------------------------------------------------

def test_kickban_uses_the_typed_reason(app):
    s, b = inside()
    feed(s, ":srv 352 Fhazal #skinhead psy h.net srv Psycho H :0 P", ":srv 352 Fhazal #skinhead bom b.net srv Bombus H :0 B")
    ui = SimpleNamespace(plugins=SimpleNamespace(on_command=lambda t: False), cfg=s.cfg)
    commands.run(ui, s, b, "/kickban Psycho go away now")
    assert "KICK #skinhead Psycho :go away now" in s.sock.out
    commands.run(ui, s, b, "/kickban Bombus")
    assert f"KICK #skinhead Bombus :{s.cfg.part_reason}" in s.sock.out or \
        any(x.startswith("KICK #skinhead Bombus") for x in s.sock.out)
    s.ban(b, "Psycho", 1, kick=True, reason="menu reason")
    assert "KICK #skinhead Psycho :menu reason" in s.sock.out


# --- 9 ban / except / invite lists with no dialog open ---------------------------------------------

def test_list_replies_are_readable(app):
    s = session()
    feed(s, ":srv 367 Fhazal #skinhead *!*@bad.host Psycho!p@h 1700000000",
         ":srv 368 Fhazal #skinhead :End of Channel Ban List",
         ":srv 348 Fhazal #skinhead *!*@good.host Bombus",
         ":srv 349 Fhazal #skinhead :End",
         ":srv 346 Fhazal #skinhead *!*@inv.host",
         ":srv 347 Fhazal #skinhead :End")
    out = texts(s.server_buffer)
    when = time.strftime("%d %b %Y %H:%M", time.localtime(1700000000))
    assert f"#skinhead ban: *!*@bad.host set by Psycho!p@h on {when}" in out
    assert "End of #skinhead ban list." in out
    assert "#skinhead except: *!*@good.host set by Bombus" in out
    assert "#skinhead invite: *!*@inv.host" in out
    assert "End of #skinhead invite list." in out
