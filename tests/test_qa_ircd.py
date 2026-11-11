"""The deterministic test IRC server (tests/qa_ircd.py) itself: lifecycle, many clients, TLS, protocol answers,
scenario control, determinism and cleanup. BChat is only used in the last two tests (it works against it)."""
import base64
import re
import socket
import threading
import time

import pytest

import qa_ircd
from qa_ircd import FIXED_EPOCH, IrcTestClient, QaIrcd, build, iso, parse


def connect(srv, nick=None, caps=(), **kw):
    c = IrcTestClient(srv.host, srv.port, tls=srv.tls, **kw)
    return c.register(nick, caps) if nick else c


# ---- line format -----------------------------------------------------------------------------------------------

def test_parse_and_build_round_trip():
    m = parse("@time=2023-11-14T22:13:21.000Z;+typing=active;k=a\\sb :nick!u@h PRIVMSG #c :hello there")
    assert m.tags == {"time": "2023-11-14T22:13:21.000Z", "+typing": "active", "k": "a b"}
    assert (m.prefix, m.command, m.params) == ("nick!u@h", "PRIVMSG", ["#c", "hello there"])
    assert parse("") is None and parse("@only=tags") is None
    assert build("PRIVMSG", "#c", "hi there", prefix="n!u@h", tags={"time": "x", "k": "a b"}) == "@time=x;k=a\\sb :n!u@h PRIVMSG #c :hi there"
    assert build("MODE", "#c", "+o", "nick") == "MODE #c +o nick"
    assert iso(FIXED_EPOCH + 1) == "2023-11-14T22:13:21.000Z"


# ---- lifecycle -------------------------------------------------------------------------------------------------

def test_localhost_by_default_free_port_and_repeated_start_stop():
    ports = set()
    for _ in range(15):
        srv = QaIrcd()
        assert srv.host == "127.0.0.1" and srv._listener.getsockname()[0] == "127.0.0.1"
        ports.add(srv.port)
        srv.stop()
        assert not srv.alive_threads()
        srv.stop()                                       # stopping twice is harmless
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", srv.port), timeout=1).close()
    assert len(ports) >= 2


def test_independent_servers_with_their_own_names(qa_server):
    servers = [qa_server(name=f"irc{i}.qa.test", network=f"Net{i}") for i in range(3)]
    assert len({s.port for s in servers}) == 3
    for i, s in enumerate(servers):
        c = connect(s, f"user{i}")
        assert f":irc{i}.qa.test 001 user{i} " in c.expect(" 001 ")
        assert f"NETWORK=Net{i}" in c.expect(" 005 ")
        c.close()


def test_many_clients_at_once(qa_server):
    srv = qa_server()
    clients, errors = [None] * 12, []

    def one(i):
        try:
            clients[i] = connect(srv, f"multi{i}")
            clients[i].send("JOIN #crowd")
        except Exception as e:                       # noqa: BLE001 - reported below
            errors.append(e)
    ts = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    assert not errors
    srv.wait_clients(12)
    for i in range(12):
        srv.wait_handled(r"^JOIN #crowd", nick=f"multi{i}")
    mark = clients[0].mark()
    clients[5].send("PRIVMSG #crowd :hello crowd")
    for i, c in enumerate(clients):
        if i != 5:
            assert "PRIVMSG #crowd :hello crowd" in c.expect("hello crowd", since=mark if i == 0 else 0)
    assert len(srv.channels["#crowd"].members) == 12
    for c in clients:
        c.close()


def test_unexpected_client_disconnect_is_seen_by_others_and_cleaned_up(qa_server):
    srv = qa_server()
    a, b = connect(srv, "alice"), connect(srv, "bob")
    a.send("JOIN #c")
    b.send("JOIN #c")
    a.expect(r"bob!\S+ JOIN #c")
    a.sock.close()                                       # alice's program dies
    a.closed = True
    b.expect(r"^:alice!\S+ QUIT :Connection closed")
    srv.wait_for("Connection closed|closed", kind="close", nick="alice")
    assert "alice" not in srv.channels["#c"].members
    b.close()


# ---- registration ----------------------------------------------------------------------------------------------

def test_registration_pass_nick_user(qa_server):
    srv = qa_server(password="test-only-pass")
    c = connect(srv)
    c.send("JOIN #x")
    c.expect(" 451 ")                                     # not registered yet
    c.send("PASS wrong")
    c.send("NICK alice")
    c.send("USER a 0 * :Alice")
    c.expect(" 464 ")
    c.expect("^ERROR ")
    ok = connect(srv)
    ok.send("PASS test-only-pass")
    ok.register("alice")
    other = connect(srv)
    other.send("NICK alice")
    other.expect(" 433 \\* alice ")
    other.send("NICK 9bad")
    other.expect(" 432 ")
    for x in (c, ok, other):
        x.close()


def test_motd_and_isupport_are_configurable(qa_server):
    srv = qa_server(motd=(), isupport={"MONITOR": "100", "EXTBAN": "$,a"})
    c = connect(srv, "alice")
    c.expect(" 422 ")
    isup = c.expect(" 005 ")
    assert "MONITOR=100" in isup and "EXTBAN=$,a" in isup
    c.close()


# ---- capabilities and SASL -------------------------------------------------------------------------------------

def test_cap_ls_302_values_multiline_req_ack_nak(qa_server):
    many = {f"draft/qa-test-capability-{i:02d}" for i in range(30)} | {"sasl", "server-time"}
    srv = qa_server(caps=many)
    c = connect(srv)
    c.send("CAP LS 302")
    first = c.expect(" CAP \\* LS ")
    assert " LS * :" in first                             # more lines follow
    c.expect(r" CAP \* LS (?!\* )")                       # the last line has no "*"
    assert "sasl=PLAIN,EXTERNAL" in " ".join(c.lines)
    c.send("CAP REQ :server-time no-such-cap")
    c.expect(" CAP \\* NAK :server-time no-such-cap")    # all or nothing
    c.send("CAP REQ :server-time sasl")
    c.expect(" CAP \\* ACK :server-time sasl")
    c.send("NICK alice")
    c.send("USER a 0 * :A")
    time.sleep(0.3)
    assert not any(" 001 " in x for x in c.lines)         # registration waits for CAP END
    c.send("CAP LIST")
    c.expect(" CAP alice LIST :sasl server-time")
    c.send("CAP END")
    c.expect(" 001 ")
    old = connect(srv)
    old.send("CAP LS")
    assert "sasl=" not in old.expect(" CAP \\* LS ")      # values only for 302
    c.close()
    old.close()


def test_different_capability_sets_per_server(qa_server):
    plain = qa_server(caps=set())
    rich = qa_server(caps={"server-time", "account-tag"})
    a, b = connect(plain), connect(rich)
    a.send("CAP LS 302")
    b.send("CAP LS 302")
    assert a.expect(" CAP \\* LS").endswith("LS :")
    assert b.expect(" CAP \\* LS").endswith(":account-tag server-time")
    a.close()
    b.close()


def _sasl(srv, user="acct", pw="test-only-pw", mech="PLAIN"):
    c = connect(srv)
    c.send("CAP LS 302")
    c.send("CAP REQ :sasl")
    c.expect(" ACK ")
    c.send(f"AUTHENTICATE {mech}")
    c.expect("^AUTHENTICATE \\+")
    c.send("AUTHENTICATE " + (base64.b64encode(f"{user}\0{user}\0{pw}".encode()).decode() if mech == "PLAIN" else "+"))
    return c


def test_sasl_success_failure_abort_and_external(qa_server):
    srv = qa_server(accounts={"acct": "test-only-pw"}, caps={"sasl"})
    srv.sasl_result = "accounts"
    good = _sasl(srv)
    good.expect(" 900 \\* \\S+ acct ")
    good.expect(" 903 ")
    bad = _sasl(srv, pw="wrong")
    bad.expect(" 904 ")
    srv.sasl_result = "fail"
    _sasl(srv).expect(" 904 ")
    srv.sasl_result = "abort"
    _sasl(srv).expect(" 906 ")
    srv.sasl_result = "ok"
    srv.external_account = "certuser"
    _sasl(srv, mech="EXTERNAL").expect(" 900 .* certuser ")
    srv.external_account = ""
    _sasl(srv, mech="EXTERNAL").expect(" 904 ")


# ---- channels, messages, tags ----------------------------------------------------------------------------------

def test_join_names_who_whox_and_extended_join(qa_server):
    srv = qa_server()
    a = connect(srv, "alice", caps=("multi-prefix", "userhost-in-names", "extended-join", "account-tag"))
    srv.set_account("alice", "AliceAcct")
    a.send("JOIN #c")
    names = a.expect(" 353 ")
    assert "@alice!qa@host1.qa.test" in names              # first joiner is op; userhost-in-names
    b = connect(srv, "bob")
    b.send("JOIN #c")
    assert "@alice" in b.expect(" 353 ") and "alice!" not in b.lines[-2]
    a.expect(r"^:bob!qa@host2.qa.test JOIN #c \* :QA client")       # extended-join, no account (so no tags)
    a.send("WHO #c %tcuhnfa,42")
    rows = [a.expect(r" 354 alice 42 #c qa host1.qa.test alice H@ AliceAcct"), a.expect(r" 354 alice 42 #c qa host2.qa.test bob H 0")]
    assert rows and a.expect(" 315 ")
    a.send("WHO bob")
    a.expect(r" 352 alice \* qa host2.qa.test irc.qa.test bob H :0 QA client")
    a.send("PART #c :bye")
    b.expect(r"alice!\S+ PART #c :bye")
    a.close()
    b.close()


def test_messages_routing_echo_and_deterministic_tags(qa_server):
    srv = qa_server()
    a = connect(srv, "alice", caps=("server-time", "message-tags", "echo-message", "account-tag"))
    b = connect(srv, "bob")
    a.send("JOIN #c")
    b.send("JOIN #c")
    a.expect("bob!.* JOIN")
    srv.set_account("bob", "BobAcct")
    m = a.mark()
    b.send("@+typing=active PRIVMSG #c :hi all")
    got = a.expect("hi all", since=m)
    t = parse(got).tags
    assert t["account"] == "BobAcct" and t["+typing"] == "active" and t["time"].startswith("2023-11-14T22:")
    a.send("@+typing=done PRIVMSG #c :mine")
    a.expect(r"alice!\S+ PRIVMSG #c :mine")                     # echo-message
    assert b.expect("PRIVMSG #c :mine").startswith(":alice!")   # bob asked for no tags: gets none at all
    a.send("NOTICE bob :psst")
    b.expect(r"^:alice!\S+ NOTICE bob :psst")
    a.send("PRIVMSG nobody :x")
    a.expect(" 401 alice nobody ")
    b.send("@+typing=active TAGMSG #c")
    a.expect(r"\+typing=active.* TAGMSG #c")
    a.close()
    b.close()


def test_server_time_is_deterministic_and_clock_can_be_injected(qa_server):
    srv = qa_server()
    a = connect(srv, "alice", caps=("server-time",))
    a.send("JOIN #c")
    srv.wait_handled("^JOIN", nick="alice")
    srv.inject("x!x@qa.test", "#c", "one")
    srv.inject("x!x@qa.test", "#c", "two")
    t1, t2 = (parse(a.expect(f"PRIVMSG #c :{w}$")).tags["time"] for w in ("one", "two"))
    assert (iso_to(t2) - iso_to(t1)) == 1.0
    fixed = qa_server(clock=lambda: 1_800_000_000.5)
    b = connect(fixed, "bob", caps=("server-time",))
    b.send("JOIN #c")
    assert parse(b.expect("JOIN #c")).tags["time"] == "2027-01-15T08:00:00.500Z"
    a.close()
    b.close()


def iso_to(s):
    import datetime
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc).timestamp()


def test_modes_operator_status_bans_and_kick(qa_server):
    srv = qa_server()
    a, b = connect(srv, "alice"), connect(srv, "bob")
    a.send("JOIN #c")
    a.expect(" 366 ")
    b.send("JOIN #c")
    b.expect(" 366 ")
    b.send("MODE #c +o bob")
    b.expect(" 482 bob #c ")                                  # not an op
    a.send("MODE #c +v bob")
    b.expect(r"alice!\S+ MODE #c \+v bob")
    assert srv.channels["#c"].members["bob"] == "+"
    srv.give_op("#c", "bob")
    b.expect(r":irc.qa.test MODE #c \+o bob")
    assert srv.channels["#c"].members["bob"] == "@+"
    srv.take_op("#c", "bob")
    b.expect(r"MODE #c -o bob")
    srv.deny_op = True
    a.send("MODE #c +m")
    a.expect(" 482 alice #c ")                                # even the op is refused now
    srv.deny_op = False
    a.send("MODE #c")
    a.expect(" 324 alice #c \\+nt")
    srv.set_account("bob", "BobAcct")
    a.send("MODE #c +b ~a:BobAcct")
    a.send("MODE #c b")
    a.expect(" 367 alice #c ~a:BobAcct ")
    a.send("KICK #c bob :out")
    b.expect(r"KICK #c bob :out")
    b.send("JOIN #c")
    b.expect(" 474 bob #c ")                                  # the account ban holds
    a.close()
    b.close()


def test_nick_changes_by_client_and_by_server(qa_server):
    srv = qa_server()
    a, b = connect(srv, "alice"), connect(srv, "bob")
    a.send("JOIN #c")
    b.send("JOIN #c")
    a.expect("bob!.* JOIN")
    a.send("NICK alice2")
    b.expect(r"^:alice!\S+ NICK :?alice2")
    srv.wait_handled("^NICK alice2")
    srv.change_nick("alice2", "Guest42")
    a.expect(r"^:alice2!\S+ NICK :?Guest42")
    b.expect(r"^:alice2!\S+ NICK :?Guest42")
    assert "guest42" in srv.channels["#c"].members
    a.close()
    b.close()


def test_quit_account_notify_chghost_away(qa_server):
    srv = qa_server()
    a = connect(srv, "alice", caps=("account-notify", "chghost", "away-notify"))
    b = connect(srv, "bob")
    a.send("JOIN #c")
    b.send("JOIN #c")
    a.expect("bob!.* JOIN")
    srv.set_account("bob", "BobAcct")
    a.expect(r"^:bob!\S+ ACCOUNT BobAcct")
    srv.set_host("bob", "newuser", "vhost.qa.test")
    a.expect(r"^:bob!qa@host2.qa.test CHGHOST newuser vhost.qa.test")
    b.send("AWAY :lunch")
    a.expect(r"^:bob!\S+ AWAY :lunch")
    b.send("QUIT :see you")
    a.expect(r"^:bob!\S+ QUIT :see you")
    b.expect("^ERROR ")
    a.close()


# ---- scenario control ------------------------------------------------------------------------------------------

def test_disconnect_drop_and_server_error(qa_server):
    srv = qa_server()
    a = connect(srv, "alice")
    srv.disconnect("alice", "Closing Link: test says bye")
    a.expect("^ERROR :Closing Link: test says bye")
    srv.wait_for("closed", kind="close", nick="alice")
    b = connect(srv, "bob")
    srv.drop("bob")
    srv.wait_for("reset", kind="close", nick="bob")
    end = time.time() + 5
    while not b.closed and time.time() < end:
        time.sleep(0.05)
    assert b.closed and not any(x.startswith("ERROR") for x in b.lines)     # no goodbye on a drop
    c = connect(srv, "carol")
    srv.numeric("carol", "465", "You are banned from this server")
    c.expect(" 465 carol :You are banned")
    srv.server_error("carol", "Closing Link: K-lined")
    c.expect("^ERROR :Closing Link: K-lined")


def test_refused_connections(qa_server):
    srv = qa_server()
    srv.refuse = "reset"
    with pytest.raises((ConnectionError, OSError, TimeoutError)):
        c = IrcTestClient(srv.host, srv.port)
        c.send("NICK x")
        c.expect(" 001 ", timeout=3)
    srv.refuse = "error"
    c = IrcTestClient(srv.host, srv.port)
    c.expect("^ERROR :Closing Link: connection refused")
    srv.wait_for("error", kind="refused")
    srv.refuse = ""
    connect(srv, "fine").close()


def test_delay_silence_and_no_pong(qa_server):
    srv = qa_server()
    a = connect(srv, "alice")
    srv.delay = 0.3
    t0 = time.time()
    a.send("PING :x1")
    a.expect("PONG .* x1")
    assert time.time() - t0 >= 0.3
    srv.delay = 0
    srv.answer_ping = False
    a.send("PING :x2")
    with pytest.raises(TimeoutError):
        a.expect("x2", timeout=0.5)
    srv.answer_ping = True
    srv.silent = True
    m = a.mark()
    a.send("PING :x3")
    srv.wait_for("PING :x3", nick="alice")                     # the server got it...
    with pytest.raises(TimeoutError):
        a.expect("x3", since=m, timeout=0.5)                   # ...and said nothing
    srv.silent = False
    srv.ping("alice", "srv-token")
    a.expect("^:irc.qa.test PING srv-token")
    a.close()


def test_malformed_lines_both_ways(qa_server):
    srv = qa_server()
    a = connect(srv, "alice")
    srv.send_raw("alice", b":broken\x00line \xff\xfe no crlf")
    srv.send_raw("alice", b"\r\n")
    srv.send_raw("alice", ":srv 999")
    a.expect("broken")
    a.expect("^:srv 999$")
    for junk in ("", "   ", ":onlyprefix", "@tags=only", "x" * 5000, "\x01\x02\x03"):
        a.send(junk)
    a.send("PING :still-here")
    a.expect("still-here")                                      # the server survived the junk
    a.close()


def test_bursts_and_big_nick_lists_in_order(qa_server):
    srv = qa_server()
    a = connect(srv, "alice")
    a.send("JOIN #big")
    a.expect(" 366 ")
    nicks = srv.add_ghosts("#big", 500, op_every=100)
    assert nicks[0] == "user0001" and nicks[-1] == "user0500"
    m = a.mark()
    a.send("NAMES #big")
    a.expect(" 366 alice #big ", since=m)
    rows = [x for x in a.lines[m:] if " 353 " in x]
    assert len(rows) == 13 and sum(len(x.split(" :", 1)[1].split()) for x in rows) == 501   # 500 ghosts + alice, 40 a line
    assert "@user0100" in " ".join(rows)
    assert srv.burst("#big", 1000) == 1000
    a.expect("burst message 1000")
    got = [int(x.rsplit(" ", 1)[1]) for x in a.lines if "burst message" in x]
    assert got == list(range(1, 1001))                          # all of them, in order
    a.close()


def run_script(srv):
    """The same steps every time; returns what the server sent, with nothing that changes between runs."""
    a = connect(srv, "alice", caps=("server-time", "multi-prefix", "extended-join"))
    b = connect(srv, "bob")
    a.send("JOIN #c")
    a.expect(" 366 ")
    b.send("JOIN #c")
    a.expect("bob!.* JOIN")
    srv.give_op("#c", "bob")
    srv.inject("x!x@qa.test", "#c", "scripted")
    a.expect("scripted")
    b.send("PRIVMSG #c :from bob")
    a.expect("from bob")
    srv.change_nick("bob", "bobby")
    a.expect("bobby")
    a.close()                                        # one at a time, so the ending is the same every run
    b.expect(r"^:alice!\S+ QUIT :Connection closed")
    b.close()
    srv.wait_for("", kind="close", nick="bobby")
    return [e.line for e in srv.events if e.kind == "out"]


def test_same_steps_give_the_same_lines(qa_server):
    one = run_script(qa_server())
    two = run_script(qa_server())
    assert one == two and len(one) > 20


# ---- TLS and IPv6 ----------------------------------------------------------------------------------------------

def test_tls_with_a_verified_certificate_and_a_failed_handshake(qa_server):
    srv = qa_server(tls=True)
    c = IrcTestClient("127.0.0.1", srv.port, tls=True, cafile=srv.certfile)   # real verification against our cert
    c.register("secure")
    assert c.sock.version() in ("TLSv1.2", "TLSv1.3")
    plain = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    plain.sendall(b"NICK x\r\nUSER x 0 * :x\r\n")                # not TLS
    srv.wait_for("TLS handshake failed", kind="close")
    plain.close()
    connect(srv, "after").close()                                # the server still serves
    c.close()


def test_ipv6_loopback_if_this_pc_has_it(qa_server):
    try:
        probe = socket.socket(socket.AF_INET6)
        probe.bind(("::1", 0))
        probe.close()
    except OSError:
        pytest.skip("this PC has no IPv6 loopback (::1)")
    srv = qa_server(host="::1")
    c = connect(srv, "six")
    srv.wait_handled(r"^NICK six")
    assert srv.client("six").addr[0] == "::1"
    c.close()


# ---- cleanup ---------------------------------------------------------------------------------------------------

def test_stop_with_clients_connected_leaves_nothing_running():
    srv = QaIrcd()
    clients = [connect(srv, f"c{i}") for i in range(5)]
    srv.stop()
    assert not srv.alive_threads()
    for c in clients:
        end = time.time() + 5
        while not c.closed and time.time() < end:
            time.sleep(0.05)
        assert c.closed
        c.close()
    assert not [t for t in threading.enumerate() if t.name.startswith(f"qa_ircd-{srv.port}-")]


def test_stop_all_catches_servers_a_failed_test_forgot():
    leaked = [QaIrcd(), QaIrcd()]
    qa_ircd.stop_all()                                          # what atexit does at the end of the run
    assert all(not s.running and not s.alive_threads() for s in leaked)


# ---- BChat against it ------------------------------------------------------------------------------------------

def test_bchat_two_windows_talk_through_the_simulator(app, tmp_path, qa_server):
    from test_live import make_win, wait
    srv = qa_server()
    w1, _ = make_win(tmp_path / "one", srv.port)
    w1.cfg.nick = "BChatOne"
    s1 = w1.connect_network(w1.cfg.networks[0])
    assert wait(app, lambda: "#skinhead" in s1.buffers, 8000)
    w2, _ = make_win(tmp_path / "two", srv.port)
    w2.cfg.nick = "BChatTwo"
    s2 = w2.connect_network(w2.cfg.networks[0])
    assert wait(app, lambda: "#skinhead" in s2.buffers, 8000)
    s2.send("PRIVMSG", "#skinhead", "hello from two")
    assert wait(app, lambda: any("hello from two" in ln.text for ln in s1.buffers["#skinhead"].lines), 8000)
    srv.give_op("#skinhead", s2.nick)
    assert wait(app, lambda: "@" in s1.buffers["#skinhead"].users[s2.nick.lower()].prefixes, 8000)
    w1.close()
    w2.close()


def test_bchat_reconnects_when_the_simulator_drops_it(app, tmp_path, qa_server):
    from test_live import make_win, wait
    srv = qa_server()
    w, net = make_win(tmp_path, srv.port)
    w.cfg.reconnect_delay = 1
    s = w.connect_network(net)
    assert wait(app, lambda: s.state == "connected" and "#skinhead" in s.buffers, 8000)
    m = srv.mark()
    srv.drop(s.nick)
    assert wait(app, lambda: s.state != "connected", 8000)
    srv.wait_for(r"^JOIN #skinhead", since=m, timeout=20, pump=app.processEvents)   # came back and rejoined by itself
    assert wait(app, lambda: s.state == "connected", 8000)
    w.close()


def test_ghost_join_part_quit_and_nick_events(qa_server):
    srv = qa_server()
    a = connect(srv, "alice")
    a.send("JOIN #g")
    a.expect(" 366 ")
    a.send("JOIN #h")
    a.expect(" 366 alice #h ")
    srv.add_ghost("#g", "ghosty", announce=True)
    srv.add_ghost("#h", "ghosty")
    a.expect(r"^:ghosty!ghost@ghost.qa.test JOIN #g")
    srv.ghost_nick("ghosty", "ghost2")
    a.expect(r"^:ghosty!\S+ NICK :?ghost2")
    assert sum(1 for x in a.lines if " NICK " in x) == 1          # once, though it shares two channels
    assert "ghost2" in srv.channels["#g"].members and "ghost2" in srv.channels["#h"].members
    srv.ghost_part("#g", "ghost2", "bye g")
    a.expect(r"^:ghost2!\S+ PART #g :bye g")
    srv.ghost_quit("ghost2", "gone")
    a.expect(r"^:ghost2!\S+ QUIT :gone")
    assert "ghost2" not in srv.channels["#h"].members and "ghost2" not in srv.ghosts
    a.close()
