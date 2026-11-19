"""0.8.5: passwords never reach the chat, the log, the scrollback or the Raw Log; /oper answers; send pacing for typed lines."""
import json
import time

import pytest

from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import parse_line
from bchat.session import Session
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_live import live_with, wait

PW = "hunter2"


def offline():
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)]), Config(nick="Fhazal"))
    s.nick = "Fhazal"
    return s


def connected(app, tmp_path, **kw):
    srv, win, net, s = live_with(app, tmp_path, **kw)
    assert wait(app, lambda: s.state == "connected" and "#skinhead" in s.buffers and len(s.buffers["#skinhead"].users) == 14)
    return srv, win, s


def type_line(win, b, text):
    """What the user does: select the tab, type into the input box, press Enter."""
    win.select_buffer(b)
    win.input.setText(text)
    QTest.keyClick(win.input, Qt.Key.Key_Return)


def fresh_clocks(s):
    s._queue.clear()
    s._next_send = 0.0


# --- 1c / 1b: the match itself ---------------------------------------------------------------------------

SECRET_LINES = [
    f"PRIVMSG NickServ :IDENTIFY {PW}", f"PRIVMSG NickServ :id {PW}", f"PRIVMSG NickServ :GHOST Bob {PW}",
    f"PRIVMSG NickServ :RECOVER Bob {PW}", f"PRIVMSG NickServ :REGISTER {PW} a@b.c", f"PRIVMSG NickServ :LOGIN {PW}",
    f"PRIVMSG NickServ :AUTH {PW}", f"PRIVMSG NickServ :SET PASSWORD {PW}", f"PRIVMSG NickServ :GROUP Old {PW}",
    f"PRIVMSG ChanServ :IDENTIFY #chan {PW}", f"PRIVMSG ChanServ :SET #chan PASSWORD {PW}",
    f"NS IDENTIFY {PW}", f"NS SET PASSWORD {PW}", f"NS GROUP Old {PW}", f"CS IDENTIFY #chan {PW}", f"ns ghost Bob {PW}",
    f"NICKSERV SET PASSWORD {PW}", f"OPER root {PW}", f"PASS {PW}", f"AUTHENTICATE {PW}",
]


@pytest.mark.parametrize("line", SECRET_LINES)
def test_secret_lines_are_hidden(line):
    assert Session.is_secret(line)
    assert PW not in Session._hide_secret(line)
    assert Session._hide_secret(line).endswith("****") or "****" in Session._hide_secret(line)


@pytest.mark.parametrize("line", SECRET_LINES)
@pytest.mark.parametrize("tags", ["@label=bc7 ", "@time=2026-11-19T10:00:00.000Z;label=bc12 ", "@+draft/reply=abc "])
def test_secret_lines_are_hidden_behind_any_ircv3_tags(tags, line):
    tagged = tags + line
    assert Session.is_secret(tagged), tagged
    hidden = Session._hide_secret(tagged)
    assert PW not in hidden and hidden.startswith(tags), hidden


def test_echoed_line_with_a_prefix_is_hidden_too():
    echoed = f"@time=2026-11-19T10:00:00.000Z :Fhazal!u@h PRIVMSG NickServ :IDENTIFY {PW}"
    assert Session.is_secret(echoed) and PW not in Session._hide_secret(echoed)


@pytest.mark.parametrize("line", ["PRIVMSG Bob :hello there", "PRIVMSG NickServ :HELP", "PRIVMSG #serv :id foo", "@label=bc1 PRIVMSG #chan :ghost x y",
                                  "@label=bc1 WHO #chan", "JOIN #chan", "PRIVMSG Bob :set password policy"])
def test_ordinary_lines_stay_as_they_are(line):
    assert not Session.is_secret(line) and Session._hide_secret(line) == line


# --- 1a: plain text typed in a services tab --------------------------------------------------------------

TYPED = ["identify", "id", "ghost Bob", "recover Bob", "register", "login", "auth", "set password", "group Bob"]


def test_plain_text_in_a_services_tab_is_hidden_everywhere(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    b = s.buffer("NickServ")
    win._set_logging(b, True)
    shown = []
    for verb in TYPED:
        fresh_clocks(s)
        before = len(b.lines)
        text = f"{verb} {PW}"
        type_line(win, b, text)
        assert wait(app, lambda: f"PRIVMSG NickServ :{text}" in srv.received), verb     # the server gets the real thing
        shown += [l.text for l in b.lines[before:]]
    assert len(shown) == len(TYPED) and all("****" in t and PW not in t for t in shown), shown
    assert not any(PW in l for l in win.raw_lines)
    log = win.log_path(b)
    assert log.exists() and PW not in log.read_text(encoding="utf-8")
    replay = win._replay_path(b)
    if replay.exists():
        rows = [json.loads(r) for r in replay.read_text(encoding="utf-8").splitlines()]
        assert rows and not any(PW in str(r) for r in rows)
    win.close(); srv.stop()


def test_chat_with_a_person_or_channel_is_not_touched(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    for target in ("Observer", "#skinhead"):
        fresh_clocks(s)
        b = s.buffer(target)
        type_line(win, b, "id 12345 is my number")
        assert any(l.text == "id 12345 is my number" for l in b.lines), target
    win.close(); srv.stop()


# --- 1b / 1c: /msg, /ns, raw, with and without labeled-response ------------------------------------------

TYPED_COMMANDS = [f"/msg nickserv set password {PW}", f"/msg NickServ group Old {PW}", f"/ns set password {PW}", f"/ns group Old {PW}",
                  f"/ns identify {PW}", f"/cs identify #chan {PW}", f"/ns ghost Bob {PW}", f"/oper root {PW}", f"/quote OPER root {PW}",
                  f"/quote PRIVMSG NickServ :SET PASSWORD {PW}", f"/id {PW}", f"/ghost Bob {PW}"]


@pytest.mark.parametrize("caps", ["", "batch message-tags labeled-response"])
def test_typed_commands_never_show_the_password(app, tmp_path, caps):
    srv, win, s = connected(app, tmp_path, caps=caps)
    if caps:
        assert wait(app, lambda: "labeled-response" in s._cap_active)
    b = s.buffer("NickServ")
    for cmd in TYPED_COMMANDS:
        fresh_clocks(s)
        type_line(win, b, cmd)
    assert wait(app, lambda: sum(PW in x for x in srv.received) >= len(TYPED_COMMANDS))
    if caps:
        assert any(x.startswith("@label=bc") and PW in x for x in srv.received)
    assert not any(PW in l for l in win.raw_lines), [l for l in win.raw_lines if PW in l]
    assert not any(PW in l.text for x in s.all_buffers() for l in x.lines)
    win.close(); srv.stop()


def test_pass_and_authenticate_with_tags_are_hidden_in_the_raw_log(app, tmp_path):
    srv, win, s = connected(app, tmp_path, caps="batch message-tags labeled-response")
    s.send_labeled(s.server_buffer, f"PASS {PW}")
    s.send_labeled(s.server_buffer, f"AUTHENTICATE {PW}")
    assert wait(app, lambda: sum(PW in x for x in srv.received) >= 2)
    assert not any(PW in l for l in win.raw_lines)
    win.close(); srv.stop()


def test_echo_message_does_not_bring_the_password_back(app, tmp_path):
    srv, win, s = connected(app, tmp_path, caps="echo-message")
    s._cap_active.add("echo-message")        # BChat does not ask for it yet; this is the guard for the day it does
    b = s.buffer("NickServ")
    srv.send(f":Badaboom!u@h PRIVMSG NickServ :identify {PW}")
    assert wait(app, lambda: any(l.text.startswith("identify") for l in b.lines))
    assert all(PW not in l.text for l in b.lines)
    assert not any(PW in l for l in win.raw_lines)
    win.close(); srv.stop()


# --- 2a: 381 --------------------------------------------------------------------------------------------

def test_381_shows_in_the_tab_where_oper_was_typed(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    b = s.buffers["#skinhead"]
    type_line(win, b, f"/oper root {PW}")
    win.select_buffer(s.server_buffer)                                   # the user clicked away meanwhile
    srv.send(":srv 381 Badaboom :You are now an IRC operator")
    assert wait(app, lambda: any("You are now an IRC operator" in l.text for l in b.lines))
    assert not any("You are now an IRC operator" in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_381_with_labeled_response_and_without_oper_typed(app, tmp_path):
    srv, win, s = connected(app, tmp_path, caps="batch message-tags labeled-response")
    b = s.buffers["#skinhead"]
    type_line(win, b, f"/oper root {PW}")
    label = next(x for x in srv.received if "OPER root" in x) if wait(app, lambda: any("OPER root" in x for x in srv.received)) else ""
    win.select_buffer(s.server_buffer)
    srv.send(f"@label={label.split(' ')[0][len('@label='):]} :srv 381 Badaboom :You are now an IRC operator")
    assert wait(app, lambda: any("You are now an IRC operator" in l.text for l in b.lines))
    # nobody typed /oper (the server opered us): the server tab, as before
    srv.send(":srv 381 Badaboom :You are now an IRC operator")
    assert wait(app, lambda: any("You are now an IRC operator" in l.text for l in s.server_buffer.lines))
    win.close(); srv.stop()


def test_381_to_a_closed_tab_falls_back_to_the_server_tab():
    s = offline()
    gone = s.buffer("Bob")
    s.send_labeled(gone, f"OPER root {PW}")
    s.remove_buffer(gone) if hasattr(s, "remove_buffer") else s.buffers.pop(s.fold("Bob"))
    s._handle(parse_line(":srv 381 Fhazal :You are now an IRC operator"))
    assert any("You are now an IRC operator" in l.text for l in s.server_buffer.lines)


# --- 2b: 464 --------------------------------------------------------------------------------------------

def test_464_before_001_still_stops_the_reconnecting():
    s = offline()
    s.want_connected = True
    s._welcomed = False
    s._handle(parse_line(":srv 464 * :Password incorrect"))
    assert s.want_connected is False
    assert any("will not retry" in l.text for l in s.server_buffer.lines)


def test_464_after_001_is_only_an_error_line_in_the_active_tab():
    s = offline()
    s.want_connected = True
    s._welcomed = True
    b = s.buffer("Bob")
    s.current = b
    s._handle(parse_line(":srv 464 Fhazal :Password incorrect"))
    assert s.want_connected is True
    assert not any("will not retry" in l.text for l in s.server_buffer.lines)
    assert any("Password incorrect" in l.text and l.kind == "error" for l in b.lines)


# --- 2c: typed lines are never queued; only automatic lines are paced -------------------------------------

def burst_as_after_a_reconnect(s):
    """20 WHO + 6 JOIN queued and the 10 s allowance used up, like the minute after a reconnect."""
    fresh_clocks(s)
    s._next_send = time.time() + 12
    for i in range(20):
        s.send("WHO", f"#w{i}")
    for i in range(6):
        s.send("JOIN", f"#j{i}")
    assert len(s._queue) == 26


def norm(line):
    """The wire form drops the ':' before a one-word trailing parameter."""
    head, sep, tail = line.partition(" :")
    return head + " " + tail if sep and " " not in tail else line


def got(srv, text):
    return norm(text) in [norm(x) for x in srv.received]


def burst_stayed_paced(srv, s):
    return not any(x.startswith(("WHO #w", "JOIN #j")) for x in srv.received) and len(s._queue) == 26


def test_typed_line_is_sent_within_50ms_behind_a_queued_burst(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    burst_as_after_a_reconnect(s)
    t0 = time.perf_counter()
    type_line(win, s.buffers["#skinhead"], "typed now")
    assert wait(app, lambda: got(srv, "PRIVMSG #skinhead :typed now"), 1000)
    assert time.perf_counter() - t0 < 0.05
    assert burst_stayed_paced(srv, s)                                   # the burst itself stays paced
    fresh_clocks(s)
    win.close(); srv.stop()


def test_a_30_line_paste_is_not_held_back_either(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    burst_as_after_a_reconnect(s)
    start = len(srv.received)
    for i in range(30):
        type_line(win, s.buffers["#skinhead"], f"p{i}")
    assert wait(app, lambda: sum(x.startswith("PRIVMSG #skinhead") for x in srv.received[start:]) == 30, 2000)
    assert [norm(x) for x in srv.received[start:] if x.startswith("PRIVMSG")] == [f"PRIVMSG #skinhead p{i}" for i in range(30)]
    assert not s._queue or burst_stayed_paced(srv, s)
    fresh_clocks(s)
    win.close(); srv.stop()


TYPED_AT_ONCE = [("/msg Belon hi", "PRIVMSG Belon hi"), ("/notice Belon psst", "NOTICE Belon psst"), ("/me waves", "PRIVMSG #skinhead :ACTION waves"),
                 ("/mode #skinhead +m", "MODE #skinhead +m"), ("/kick #skinhead Belon bye", "KICK #skinhead Belon bye"),
                 ("/topic #skinhead new topic", "TOPIC #skinhead :new topic"), ("/whois Belon", "WHOIS Belon Belon"),
                 ("/ns identify " + PW, "ns identify " + PW), ("/cs identify #c " + PW, "cs identify #c " + PW),
                 ("/oper root " + PW, "OPER root " + PW)]


@pytest.mark.parametrize("typed,wire", TYPED_AT_ONCE)
def test_every_kind_of_typed_command_is_instant(app, tmp_path, typed, wire):
    srv, win, s = connected(app, tmp_path)
    burst_as_after_a_reconnect(s)
    type_line(win, s.buffers["#skinhead"], typed)
    assert wait(app, lambda: any(norm(x).lower().endswith(norm(wire).lower()) for x in srv.received), 1000), (typed, srv.received[-5:])
    assert burst_stayed_paced(srv, s)
    fresh_clocks(s)
    win.close(); srv.stop()


def test_automatic_lines_are_still_paced(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    fresh_clocks(s)
    start = len(srv.received)
    for i in range(30):
        s.send("PRIVMSG", "Belon", f"auto{i}")                    # outside typed(): a script, a CTCP reply, a timer
    wait(app, lambda: False, 300)
    sent = [x for x in srv.received[start:] if x.startswith("PRIVMSG Belon")]
    assert 4 <= len(sent) <= 7 and len(s._queue) > 20, (len(sent), len(s._queue))
    fresh_clocks(s)
    win.close(); srv.stop()


def test_background_who_and_mode_use_only_what_is_left(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    fresh_clocks(s)
    s._next_send = time.time() + 5          # more than 4 s used: WHO/MODE wait, an ordinary line does not
    s.send("WHO", "#a")
    s.send("MODE", "#a")
    s.send("WHOIS", "Oracle")
    assert wait(app, lambda: got(srv, "WHOIS Oracle"), 1000)
    assert s._queue == ["WHO #a", "MODE #a"]
    fresh_clocks(s)
    s.send("WHO", "#a")
    assert wait(app, lambda: got(srv, "WHO #a"), 1000)                    # a free allowance lets them out
    win.close(); srv.stop()
