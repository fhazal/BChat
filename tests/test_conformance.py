"""IRC / IRCv3 protocol conformance of BChat (QA item B), against the deterministic simulator tests/qa_ircd.py.

Each test checks one behaviour against the spec it names (RFC 1459/2812, modern.ircdocs.horse, ircv3.net).
Where BChat does not do what the spec says, the test stays strict and is marked
xfail(strict=True, reason="FINDING-nn: ...") so the deviation shows in every report; if BChat is changed,
the test turns red and the marker comes off. The status of every area is in docs/PROTOCOL-CONFORMANCE.md.
This is evidence for what is tested, not a claim of full IRC or IRCv3 compliance.
"""
import base64
import time

import pytest

from bchat.protocol import build_line, lower, parse_line
from qa_ircd import IrcTestClient
from test_live import make_win, wait

CH = "#skinhead"          # make_win's autojoin channel


@pytest.fixture
def bchat(app, tmp_path, qa_server):
    """start(srv=None, connect=True, **network settings) -> (server, window, session). Windows close after the test."""
    wins = []

    def start(srv=None, connect=True, **net):
        srv = srv or qa_server()
        if srv.tls:
            net.setdefault("allow_invalid_cert", True)
        w, n = make_win(tmp_path / f"w{len(wins)}", srv.port, ssl=srv.tls, **net)
        wins.append(w)
        return srv, w, (w.connect_network(n) if connect else None)
    yield start
    for w in wins:
        w.close()


def up(app, s, ms=8000):
    return wait(app, lambda: s.state == "connected", ms)


def in_chan(app, s, chan=CH, ms=8000):
    return wait(app, lambda: chan in s.buffers and s.buffers[chan].joined and s.buffers[chan].users, ms)


def texts(b):
    return [ln.text for ln in b.lines]


def sent(srv, nick=None):
    return srv.received(nick)


def peer(srv, nick="peer", caps=(), join=CH):
    c = IrcTestClient(srv.host, srv.port, tls=srv.tls).register(nick, caps)
    if join:
        c.send(f"JOIN {join}")
        c.expect(" 366 ")
    return c


# ==== 1. Line parsing and building (modern.ircdocs.horse "Messages", IRCv3 message-tags) =========================

def test_parse_tags_escapes_per_spec():
    m = parse_line(r"@a=x\:y\sz\\w\r\n;b=;c;+client=v\b;d=end\ :n!u@h CMD p")
    assert m.tags["a"] == "x;y z\\w\r\n"
    assert m.tags["b"] == "" and m.tags["c"] == ""          # empty value and no value are the same
    assert m.tags["+client"] == "vb"                          # unknown escape: the backslash is dropped
    assert m.tags["d"] == "end"                               # a lone trailing backslash is dropped
    assert (m.prefix, m.command, m.params) == ("n!u@h", "CMD", ["p"])


def test_parse_duplicate_tag_last_wins():
    assert parse_line("@k=1;k=2 :s CMD").tags["k"] == "2"


def test_parse_params_spaces_and_trailing():
    m = parse_line(":srv   PRIVMSG   #c   :hello :world  ")
    assert m.params == ["#c", "hello :world  "]               # several spaces between; trailing keeps its text
    assert parse_line("PING :").params == [""]                # an empty trailing parameter is a parameter
    assert parse_line("CMD a b c d e f g h i j k l m n o").params == list("abcdefghijklmno")
    assert parse_line("privmsg #c hi").command == "PRIVMSG"   # commands are case-insensitive


def test_parse_lines_without_prefix_or_tags_and_numeric():
    assert parse_line("PING srv").params == ["srv"]
    m = parse_line(":irc.example 001 me :Welcome")
    assert (m.command, m.params, m.nick) == ("001", ["me", "Welcome"], "irc.example")


def test_build_line_trailing_rules():
    assert build_line("PRIVMSG", "#c", "hi there") == "PRIVMSG #c :hi there"
    assert build_line("PRIVMSG", "#c", ":)") == "PRIVMSG #c ::)"
    assert build_line("PRIVMSG", "#c", "") == "PRIVMSG #c :"
    assert build_line("JOIN", "#c") == "JOIN #c"


def test_casefold_rfc1459():
    assert lower("Nick[]\\~") == "nick{}|^"


# ==== 2. Registration (RFC 2812 3.1, modern.ircdocs "Connection registration", IRCv3 cap 302) ==================

def test_reg_cap_ls_302_first_then_nick_user_and_cap_end_after_ack(app, bchat):
    srv, w, s = bchat()
    assert up(app, s)
    got = sent(srv)
    assert got[0] == "CAP LS 302"
    i_req = next(i for i, x in enumerate(got) if x.startswith("CAP REQ"))
    i_end = got.index("CAP END")
    assert i_req < i_end
    assert any(x.startswith("NICK ") for x in got[:i_end]) and any(x.startswith("USER ") for x in got[:i_end])


def test_reg_pass_is_sent_before_nick(app, bchat, qa_server):
    srv = qa_server(password="test-only-server-pass")
    _, w, s = bchat(srv, password="test-only-server-pass")
    assert up(app, s)
    got = sent(srv)
    assert got.index("PASS test-only-server-pass") < next(i for i, x in enumerate(got) if x.startswith("NICK "))


def test_reg_nick_in_use_takes_the_second_nick(app, bchat, qa_server):
    srv = qa_server()
    holder = IrcTestClient(srv.host, srv.port).register("Badaboom")
    _, w, s = bchat(srv)
    assert up(app, s)
    assert s.nick == "b2"                                     # make_win's nick2
    holder.close()


def test_reg_isupport_is_read(app, bchat, qa_server):
    srv = qa_server(isupport={"PREFIX": "(qaohv)~&@%+", "CHANTYPES": "#&", "EXTBAN": "$,a", "WHOX": "",
                              "CHANMODES": "beI,k,l,imnpst", "MONITOR": "100", "NETWORK": "QANet"})
    _, w, s = bchat(srv)
    assert up(app, s)
    wait(app, lambda: s.prefix_modes == "qaohv" and s.whox and s.modes_list == "beI", 3000)   # 005 lines come after 001
    assert (s.prefix_modes, s.prefix_chars) == ("qaohv", "~&@%+")
    assert s.chantypes == "#&" and s.extban == ("$", "a") and s.whox is True
    assert (s.modes_list, s.modes_key, s.modes_on_set) == ("beI", "k", "l")


@pytest.mark.xfail(strict=True, reason="FINDING-01: CASEMAPPING from ISUPPORT is ignored; BChat always folds nicks "
                                       "rfc1459-style, so on a CASEMAPPING=ascii server 'a[b' and 'a{b' become one user")
def test_reg_casemapping_ascii_is_followed(app, bchat, qa_server):
    srv = qa_server(isupport={"CASEMAPPING": "ascii"})
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    srv.add_ghost(CH, "a[b", announce=True)
    srv.add_ghost(CH, "a{b", announce=True)
    assert wait(app, lambda: len(s.buffers[CH].users) == 3, 4000)


# ==== 3. Capability negotiation (IRCv3 capability-negotiation, cap-notify) =====================================

def test_cap_requests_only_offered_and_wanted(app, bchat, qa_server):
    srv = qa_server(caps={"server-time", "draft/qa-unknown-cap", "multi-prefix"})
    _, w, s = bchat(srv)
    assert up(app, s)
    req = " ".join(x for x in sent(srv) if x.startswith("CAP REQ"))
    assert "server-time" in req and "multi-prefix" in req and "draft/qa-unknown-cap" not in req
    assert s._cap_active == {"server-time", "multi-prefix"}


def test_cap_multiline_ls_is_read_to_the_end(app, bchat, qa_server):
    srv = qa_server(caps={f"draft/qa-filler-{i:02d}" for i in range(40)} | {"server-time", "zzz-last-line-cap"})
    _, w, s = bchat(srv)
    assert up(app, s)
    assert "server-time" in s._cap_active
    assert sum(1 for e in srv.events if e.kind == "out" and " CAP " in e.line and " LS " in e.line) >= 2


def test_cap_nak_still_registers_without_those_caps(app, bchat, qa_server):
    srv = qa_server(caps={"server-time", "multi-prefix"})
    srv.nak_caps = {"server-time"}
    _, w, s = bchat(srv)
    assert up(app, s)
    assert "server-time" not in s._cap_active


def test_cap_network_feature_switch_is_honoured(app, bchat, qa_server):
    srv = qa_server(caps={"server-time", "away-notify"})
    _, w, s = bchat(srv, caps_off=["away-notify"])
    assert up(app, s)
    assert "away-notify" not in s._cap_active and "server-time" in s._cap_active


def test_cap_notify_new_and_del(app, bchat, qa_server):
    srv = qa_server(caps={"cap-notify", "server-time"})
    _, w, s = bchat(srv)
    assert up(app, s)
    srv.caps.add("away-notify")
    m = srv.mark()
    srv.send_raw(s.nick, f":irc.qa.test CAP {s.nick} NEW :away-notify")
    srv.wait_for("^CAP REQ .*away-notify", since=m, pump=app.processEvents)
    assert wait(app, lambda: "away-notify" in s._cap_active)
    srv.send_raw(s.nick, f":irc.qa.test CAP {s.nick} DEL :away-notify")
    assert wait(app, lambda: "away-notify" not in s._cap_active)


# ==== 4. SASL (IRCv3 sasl-3.1/3.2) =============================================================================

def test_sasl_plain_over_tls_logs_in(app, bchat, qa_server):
    srv = qa_server(tls=True, accounts={"qa-acct": "test-only-pw"})
    srv.sasl_result = "accounts"
    _, w, s = bchat(srv, sasl_user="qa-acct", sasl_password="test-only-pw")
    assert up(app, s)
    auth = [x for x in sent(srv) if x.startswith("AUTHENTICATE ")]
    assert auth[0] == "AUTHENTICATE PLAIN"
    assert base64.b64decode(auth[1].split()[1]).split(b"\0")[1:] == [b"qa-acct", b"test-only-pw"]
    assert sent(srv).index("CAP END") > sent(srv).index(auth[1])     # CAP END only after SASL finished
    assert any("SASL login successful" in t for t in texts(s.server_buffer))


def test_sasl_failure_is_reported_and_registration_does_not_hang(app, bchat, qa_server):
    srv = qa_server(tls=True)
    srv.sasl_result = "fail"
    _, w, s = bchat(srv, sasl_user="qa-acct", sasl_password="wrong")
    assert wait(app, lambda: any("SASL login failed" in t for t in texts(s.server_buffer)), 8000)
    assert "CAP END" in sent(srv) or s.state != "connected"   # never stuck waiting in CAP


def test_sasl_plain_is_never_sent_without_tls(app, bchat, qa_server):
    srv = qa_server(tls=False)
    _, w, s = bchat(srv, sasl_user="qa-acct", sasl_password="test-only-pw")
    wait(app, lambda: s.state == "connected", 6000)
    assert not [x for x in sent(srv) if x.startswith("AUTHENTICATE")]   # no PLAIN, no credentials in clear text


def test_sasl_mechanism_list_is_respected(app, bchat, qa_server):
    srv = qa_server(tls=True, cap_values={"sasl": "EXTERNAL"})
    _, w, s = bchat(srv, sasl_user="qa-acct", sasl_password="test-only-pw")
    wait(app, lambda: s.state == "connected", 6000)
    assert "AUTHENTICATE PLAIN" not in sent(srv)              # the server said it has no PLAIN


# ==== 5. Message tags and server-time (IRCv3 message-tags, server-time, account-tag, typing) ===================

def test_tags_server_time_sets_the_line_time(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    srv.inject("bob!b@qa.test", CH, "timed line")
    assert wait(app, lambda: any(ln.text == "timed line" for ln in s.buffers[CH].lines))
    ln = next(ln for ln in s.buffers[CH].lines if ln.text == "timed line")
    sent_tags = [e.line for e in srv.events if e.kind == "out" and "timed line" in e.line][0]
    from qa_ircd import parse as sparse
    import datetime
    want = datetime.datetime.strptime(sparse(sent_tags).tags["time"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=datetime.timezone.utc).timestamp()
    assert abs(ln.ts - want) < 0.01


def test_tags_client_typing_tag(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    p = peer(srv, caps=("message-tags",))
    p.send(f"@+typing=active TAGMSG {CH}")
    assert wait(app, lambda: "peer" in s.buffers[CH].typing)
    p.close()


def test_tags_unknown_tags_are_ignored(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    srv.inject("bob!b@qa.test", CH, "with odd tags", tags={"+example.com/x": "a;b c", "+q": ""})
    assert wait(app, lambda: "with odd tags" in texts(s.buffers[CH]))


# ==== 6. Messages (RFC 2812 3.3, CTCP) =========================================================================

def test_msg_channel_private_notice_action(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    srv.inject("bob!b@qa.test", CH, "to the channel")
    srv.inject("bob!b@qa.test", s.nick, "just for you")
    srv.inject("NickServ!s@services.qa", s.nick, "a notice", command="NOTICE")
    srv.inject("bob!b@qa.test", CH, "\x01ACTION waves\x01")
    assert wait(app, lambda: "to the channel" in texts(s.buffers[CH]))
    assert wait(app, lambda: "bob" in s.buffers and "just for you" in texts(s.buffers["bob"]))
    assert wait(app, lambda: any("a notice" in t for b in s.buffers.values() for t in texts(b))
                or any("a notice" in t for t in texts(s.server_buffer)))
    assert wait(app, lambda: any("waves" in t for t in texts(s.buffers[CH])))


def test_msg_ctcp_version_and_ping_replies(app, bchat):
    srv, w, s = bchat()
    assert up(app, s)
    m = srv.mark()
    srv.inject("bob!b@qa.test", s.nick, "\x01VERSION\x01")
    srv.wait_for("^NOTICE bob :\x01VERSION .+\x01$", since=m, pump=app.processEvents)
    srv.inject("bob!b@qa.test", s.nick, "\x01PING 1234\x01")
    srv.wait_for("^NOTICE bob :\x01PING 1234\x01$", since=m, pump=app.processEvents)


def test_msg_outgoing_lines_are_well_formed(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    m = srv.mark()
    s.send("PRIVMSG", CH, ":starts with a colon")
    s.send("PRIVMSG", CH, "two  spaces")
    srv.wait_for(f"^PRIVMSG {CH} :two  spaces$", since=m, pump=app.processEvents)
    assert f"PRIVMSG {CH} ::starts with a colon" in sent(srv)


# ==== 7. Channels (RFC 2812 3.2, multi-prefix, userhost-in-names, extended-join) ==============================

def test_chan_names_with_multi_prefix_and_userhost(app, bchat, qa_server):
    srv = qa_server(caps={"multi-prefix", "userhost-in-names"})
    srv.add_ghost(CH, "opvoice", prefix="@+")
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    assert wait(app, lambda: "opvoice" in s.buffers[CH].users)   # our own JOIN fills the list before NAMES does
    u = s.buffers[CH].users["opvoice"]
    assert u.prefixes == "@+" and u.host == "ghost@ghost.qa.test"


def test_chan_extended_join_gives_account_and_realname(app, bchat, qa_server):
    srv = qa_server(caps={"extended-join"})
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    p = IrcTestClient(srv.host, srv.port).register("peer", realname="Peer Real Name")
    srv.set_account("peer", "PeerAcct")
    p.send(f"JOIN {CH}")
    assert wait(app, lambda: "peer" in s.buffers[CH].users)
    u = s.buffers[CH].users["peer"]
    assert u.account == "PeerAcct" and u.realname == "Peer Real Name"
    p.close()


def test_chan_part_kick_quit_remove_users(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    a, b, c = (peer(srv, n) for n in ("pa", "pb", "pc"))
    assert wait(app, lambda: {"pa", "pb", "pc"} <= set(s.buffers[CH].users))
    a.send(f"PART {CH} :bye")
    srv.kick(CH, "pb", "out")
    c.send("QUIT :gone")
    assert wait(app, lambda: not {"pa", "pb", "pc"} & set(s.buffers[CH].users))
    for x in (a, b, c):
        x.close()


def test_chan_kicked_ourselves(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    w.cfg.rejoin_on_kick = False                              # the default; rejoin is tested in test_comfort.py
    srv.kick(CH, s.nick, "test kick")
    assert wait(app, lambda: not s.buffers[CH].joined)
    assert any("test kick" in t for t in texts(s.buffers[CH]))


def test_chan_nick_changes_others_and_ours(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    p = peer(srv, "oldnick")
    assert wait(app, lambda: "oldnick" in s.buffers[CH].users)
    p.send("NICK newnick")
    assert wait(app, lambda: "newnick" in s.buffers[CH].users and "oldnick" not in s.buffers[CH].users)
    srv.change_nick(s.nick, "Forced42")                      # e.g. services renaming us
    assert wait(app, lambda: s.nick == "Forced42" and "forced42" in s.buffers[CH].users)
    p.close()


def test_chan_topic_on_join_and_change(app, bchat, qa_server):
    srv = qa_server()
    with srv._lock:
        from qa_ircd import Channel
        srv.channels[CH] = Channel(CH, members={}, topic="first topic")
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    assert wait(app, lambda: s.buffers[CH].topic == "first topic")
    srv.give_op(CH, s.nick)
    s.send("TOPIC", CH, "second topic")
    assert wait(app, lambda: s.buffers[CH].topic == "second topic")


def test_chan_join_errors_are_shown(app, bchat):
    srv, w, s = bchat()
    assert up(app, s)
    for num, text in (("471", "Cannot join channel (+l)"), ("473", "Cannot join channel (+i)"),
                      ("474", "Cannot join channel (+b)"), ("475", "Cannot join channel (+k)")):
        srv.numeric(s.nick, num, "#closed", text)
    every = lambda: [t for b in [s.server_buffer, *s.buffers.values()] for t in texts(b)]   # noqa: E731
    for why in ("User limit reached", "Channel is invite only", "You are banned", "Requires keyword"):
        assert wait(app, lambda: f"Cannot join #closed ({why})." in every())


# ==== 8. Modes (RFC 2811 4, modern.ircdocs MODE, PREFIX/CHANMODES) =============================================

def test_mode_324_and_changes_with_arguments(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    p = peer(srv, "voiced")
    assert wait(app, lambda: "voiced" in s.buffers[CH].users)
    srv.apply_mode(CH, "+ovk", s.nick, "voiced", "sekrit")
    b = s.buffers[CH]
    assert wait(app, lambda: "@" in b.users[lower(s.nick)].prefixes and "+" in b.users["voiced"].prefixes)
    assert wait(app, lambda: "k" in b.modes and b.mode_args.get("k") == "sekrit")
    srv.apply_mode(CH, "-v+l-k", "voiced", "25", "sekrit")
    assert wait(app, lambda: "+" not in b.users["voiced"].prefixes and b.mode_args.get("l") == "25" and "k" not in b.modes)
    srv.apply_mode(CH, "+b", "bad!*@*")
    assert wait(app, lambda: any("bad!*@*" in t for t in texts(b)))
    assert "b" not in b.modes                                 # list modes are not channel flags
    p.close()


def test_mode_custom_prefixes_from_isupport(app, bchat, qa_server):
    srv = qa_server(isupport={"PREFIX": "(qaohv)~&@%+"})
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    srv.apply_mode(CH, "+q", s.nick)
    assert wait(app, lambda: "~" in s.buffers[CH].users[lower(s.nick)].prefixes)


def test_mode_not_operator_error_is_shown(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    srv.take_op(CH, s.nick)
    s.send("MODE", CH, "+m")
    assert wait(app, lambda: any("operator" in t.lower() for b in [s.server_buffer, *s.buffers.values()] for t in texts(b)))


def test_mode_user_modes_do_not_break_anything(app, bchat):
    srv, w, s = bchat()
    assert up(app, s)
    srv.send_raw(s.nick, f":{s.nick} MODE {s.nick} :+iwx")
    srv.numeric(s.nick, "221", "+iwx")
    s.send("PING", "after-umode")
    srv.wait_for("^PING after-umode", pump=app.processEvents)
    assert s.state == "connected"


# ==== 9. Account, host, away, realname notifications (IRCv3 account-notify, chghost, away-notify, setname) ====

def test_notify_account_chghost_away_setname(app, bchat, qa_server):
    srv = qa_server(caps={"account-notify", "chghost", "away-notify", "setname", "multi-prefix"})
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    p = peer(srv, "watched")
    assert wait(app, lambda: "watched" in s.buffers[CH].users)
    u = lambda: s.buffers[CH].users["watched"]                # noqa: E731
    srv.set_account("watched", "WAcct")
    assert wait(app, lambda: u().account == "WAcct")
    srv.set_account("watched", "")
    assert wait(app, lambda: u().account == "")
    srv.set_host("watched", "newid", "new.host.qa")
    assert wait(app, lambda: u().host == "newid@new.host.qa")
    p.send("AWAY :lunch")
    assert wait(app, lambda: u().away is True)
    p.send("AWAY")
    assert wait(app, lambda: u().away is False)
    srv.send_raw(s.nick, f":watched!newid@new.host.qa SETNAME :A New Real Name")
    assert wait(app, lambda: u().realname == "A New Real Name")
    p.close()


# ==== 10. Numerics and errors (RFC 2812 5) =====================================================================

def test_err_no_such_nick_and_unknown_numerics(app, bchat):
    srv, w, s = bchat()
    assert up(app, s)
    s.send("PRIVMSG", "nobody-here", "hi")
    srv.numeric(s.nick, "999", "something only this server sends")
    assert wait(app, lambda: any("nobody-here" in t for b in [s.server_buffer, *s.buffers.values()] for t in texts(b)))
    assert wait(app, lambda: any("something only this server sends" in t for t in texts(s.server_buffer)))


def test_err_error_line_is_shown_and_connection_ends(app, bchat):
    srv, w, s = bchat()
    assert up(app, s)
    srv.server_error(s.nick, "Closing Link: QA says goodbye")
    assert wait(app, lambda: any("QA says goodbye" in t for t in texts(s.server_buffer)))
    assert wait(app, lambda: s.state != "connected")


# ==== 11. Robustness: malformed input (no crash, connection keeps working) =====================================

def test_robust_garbage_lines(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    for junk in (b"\r\n", b"   \r\n", b":onlyprefix\r\n", b"@tags=only\r\n", b"@\r\n", b":\r\n", b"\x00\x01\x02\r\n",
                 b":bob!b@h PRIVMSG\r\n", b":bob!b@h PRIVMSG #skinhead\r\n", b"\xff\xfe broken utf8 \xc3\r\n",
                 b"lone\rcarriage\r\n", b"x" * 20000 + b"\r\n",
                 b"a line in two TCP pieces", b" without CRLF in the first\r\n"):   # one line arriving in parts
        srv.send_raw(s.nick, junk)
    srv.inject("bob!b@qa.test", CH, "still alive")
    assert wait(app, lambda: "still alive" in texts(s.buffers[CH]))
    assert s.state == "connected"


def test_robust_numerics_with_missing_parameters(app, bchat):
    srv, w, s = bchat()
    assert in_chan(app, s)
    for num in ("001", "005", "332", "333", "353", "366", "324", "329", "352", "354", "311", "318", "367", "368",
                "433", "900", "903", "904", "730", "731", "600", "601"):
        srv.send_raw(s.nick, f":irc.qa.test {num}")
        srv.send_raw(s.nick, f":irc.qa.test {num} {s.nick}")
    for cmd in ("JOIN", "PART", "KICK", "MODE", "NICK", "TOPIC", "QUIT", "INVITE", "ACCOUNT", "CHGHOST", "AWAY", "CAP"):
        srv.send_raw(s.nick, f":bob!b@h {cmd}")
    srv.inject("bob!b@qa.test", CH, "survived")
    assert wait(app, lambda: "survived" in texts(s.buffers[CH]))
    assert s.state == "connected"


# ==== 12. Reconnection and connection problems ================================================================

def test_conn_reconnect_after_error_and_rejoin(app, bchat):
    srv, w, s = bchat()
    w.cfg.reconnect_delay = 1
    assert in_chan(app, s)
    m = srv.mark()
    srv.server_error(s.nick, "Closing Link: restart")
    srv.wait_for(f"^JOIN {CH}", since=m, timeout=20, pump=app.processEvents)
    assert in_chan(app, s)


def test_conn_refused_then_accepted(app, bchat, qa_server):
    srv = qa_server()
    srv.refuse = "reset"
    _, w, s = bchat(srv, connect=False)
    w.cfg.reconnect_delay = 1
    s = w.connect_network(w.cfg.networks[0])
    srv.wait_for("reset", kind="refused", pump=app.processEvents)
    srv.refuse = ""
    assert wait(app, lambda: s.state == "connected", 20000)


def test_conn_slow_server_still_registers(app, bchat, qa_server):
    srv = qa_server()
    srv.delay = 0.05                                          # 50 ms before every line
    _, w, s = bchat(srv)
    assert wait(app, lambda: s.state == "connected", 20000)


def test_conn_silent_server_is_noticed(app, bchat):
    srv, w, s = bchat()
    w.cfg.reconnect_delay = 1
    assert up(app, s)
    srv.silent = True
    s._last_rx = time.time() - 300                            # as if 5 minutes passed without a line (limit: 240 s)
    s._tick()
    assert wait(app, lambda: any("stopped responding" in t for t in texts(s.server_buffer)))
    srv.silent = False
    assert wait(app, lambda: s.state == "connected", 20000)   # and it reconnects by itself


def test_conn_server_ping_is_answered(app, bchat):
    srv, w, s = bchat()
    assert up(app, s)
    m = srv.mark()
    srv.ping(s.nick, "qa-check-123")
    srv.wait_for("^PONG :?qa-check-123$", since=m, pump=app.processEvents)


# ==== 13. Feature detection from ISUPPORT ======================================================================

def test_feat_whox_used_when_offered(app, bchat, qa_server):
    srv = qa_server(isupport={"WHOX": ""})
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    srv.wait_for(f"^WHO {CH} %", pump=app.processEvents)


def test_feat_no_whox_means_plain_who(app, bchat, qa_server):
    srv = qa_server()
    del srv.isupport["WHOX"]
    _, w, s = bchat(srv)
    assert in_chan(app, s)
    time.sleep(0.2)
    wait(app, lambda: False, 1500)
    assert not any(x.startswith(f"WHO {CH} %") for x in sent(srv))


F02 = ("FINDING-02: friends tracking starts at 001, before the server's 005 (ISUPPORT) says MONITOR/WATCH, so BChat "
       "polls with ISON even on servers that offer MONITOR or WATCH (instant online/offline never starts on connect)")


def _friends_first_query(app, bchat, qa_server, isupport):
    srv = qa_server(isupport=isupport)
    srv.isupport.pop("WHOX", None)
    _, w, s = bchat(srv, connect=False)
    w.cfg.friends = ["SomeFriend"]
    s = w.connect_network(w.cfg.networks[0])
    assert up(app, s)
    e = srv.wait_for(r"^(MONITOR \+|WATCH \+|ISON )", timeout=20, pump=app.processEvents)
    return e.line


def test_feat_monitor_used_when_offered(app, bchat, qa_server):
    assert _friends_first_query(app, bchat, qa_server, {"MONITOR": "100"}).startswith("MONITOR + SomeFriend")


def test_feat_watch_used_when_offered(app, bchat, qa_server):
    assert _friends_first_query(app, bchat, qa_server, {"WATCH": "128"}).startswith("WATCH +SomeFriend")


def test_feat_ison_without_monitor_or_watch(app, bchat, qa_server):
    assert _friends_first_query(app, bchat, qa_server, {}) == "ISON SomeFriend"
