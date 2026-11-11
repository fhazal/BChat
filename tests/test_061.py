"""0.6.1: FINDING-01, nicks and channel names folded the way each server says (ISUPPORT CASEMAPPING)."""
import time
from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import folder, lower, parse_line
from bchat.session import Session


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def session(app):
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)]), Config(nick="me"))
    s.nick = "me"
    return s


def test_fold_functions_per_casemapping():
    assert folder("ascii")("A[B]\\~Z") == "a[b]\\~z"
    assert folder("rfc1459")("A[B]\\~") == "a{b}|^"
    assert folder("strict-rfc1459")("A[B]\\~") == "a{b}|~"
    assert folder("RFC8265")("ÄB") == "äb"
    assert folder("")("[x]") == folder("something-new")("[x]") == lower("[x]") == "{x}"
    assert folder("ascii")("É") == "É"            # ascii folds A-Z only


def test_ascii_server_keeps_bracket_nicks_apart(app):
    s = session(app)
    feed(s, ":srv 005 me CASEMAPPING=ascii CHANTYPES=# :are supported",
         ":me!u@h JOIN #Chan", ":a[b!u@h JOIN #chan", ":a{b!u@h JOIN #CHAN")
    b = s.buffers[s.fold("#chan")]
    assert s.casemapping == "ascii"
    assert sorted(u.nick for u in b.users.values()) == ["a[b", "a{b", "me"]
    feed(s, ":a[b!u@h PART #chan")
    assert [u.nick for u in b.users.values() if u.nick.startswith("a")] == ["a{b"]


def test_rfc1459_server_still_treats_brackets_as_one(app):
    s = session(app)
    feed(s, ":srv 005 me CASEMAPPING=rfc1459 :are supported", ":me!u@h JOIN #c", ":a[b!u@h JOIN #c", ":A{B!u@h JOIN #c")
    assert len(s.buffers["#c"].users) == 2


def test_names_held_before_005_are_rekeyed(app):
    s = session(app)
    feed(s, ":me!u@h JOIN #x[1]", ":Bob[m]!u@h JOIN #x[1]", ":Bob[m]!u@h PRIVMSG me :hi")
    assert set(s.buffers) == {"#x{1}", "bob{m}"}                 # rfc1459 until the server says otherwise
    feed(s, ":srv 005 me CASEMAPPING=ascii :are supported")
    assert set(s.buffers) == {"#x[1]", "bob[m]"}
    assert "bob[m]" in s.buffers["#x[1]"].users
    feed(s, ":Bob{m}!u@h PRIVMSG me :other person")              # a different user now: own query
    assert set(s.buffers) == {"#x[1]", "bob[m]", "bob{m}"}
    feed(s, ":Bob[m]!u@h NICK Bob2")
    assert "bob2" in s.buffers and "bob[m]" not in s.buffers


def test_no_casemapping_token_keeps_the_current_one(app):
    s = session(app)
    feed(s, ":srv 005 me CASEMAPPING=ascii :are supported", ":srv 005 me NICKLEN=30 :are supported")
    assert s.casemapping == "ascii"


def test_add_network_opens_the_network_list_on_the_new_network(app, tmp_path, monkeypatch):
    """BR-3 (0.6.0-TEST3): Add Network on a /server tab crashed opening the Network List (tree item data() needs a column)."""
    from fake_ircd import FakeIrcd
    from PySide6.QtCore import Qt
    from test_live import make_win, type_cmd, wait
    from bchat import networklist
    picked = []
    monkeypatch.setattr(networklist.NetworkListDialog, "exec",
                        lambda d: picked.append(d.list.currentItem().data(0, Qt.ItemDataRole.UserRole)) or 0)
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.new_server_tab()
    win.select_buffer(s.server_buffer)
    type_cmd(win, f"/server 127.0.0.1 {srv.port}")
    assert wait(app, lambda: s.state == "connected" and s.network_token, 8000)
    saved = win.add_network_from(s)                 # dialogs on: the real Network List opens
    assert picked == [saved] and saved in win.cfg.networks
    win.close()
    srv.stop()


def test_add_and_edit_network_while_disconnected(app, tmp_path, monkeypatch):
    """User question on BR-3: the server tab menu offers Add/Edit Network when disconnected too; both must work."""
    from fake_ircd import FakeIrcd
    from PySide6.QtCore import Qt
    from test_live import make_win, type_cmd, wait
    from bchat import networklist
    picked, edited = [], []
    monkeypatch.setattr(networklist.NetworkListDialog, "exec",
                        lambda d: picked.append(d.list.currentItem().data(0, Qt.ItemDataRole.UserRole)) or 0)
    monkeypatch.setattr(networklist.NetworkEditDialog, "exec", lambda d: edited.append(d) or 1)
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    win.cfg.reconnect_delay = 600                  # stay disconnected for the test
    s = win.new_server_tab()
    win.select_buffer(s.server_buffer)
    type_cmd(win, f"/server 127.0.0.1 {srv.port}")
    assert wait(app, lambda: s.state == "connected" and s.network_token, 8000)
    type_cmd(win, "/join #kept")
    assert wait(app, lambda: "#kept" in s.buffers and s.buffers["#kept"].joined)
    s.disconnect_from_network()                    # tab disconnected (same state as a dropped server)
    assert wait(app, lambda: s.state == "disconnected", 8000)
    srv.stop()
    saved = win.add_network_from(s)
    assert picked == [saved] and saved in win.cfg.networks
    assert saved.servers[0].port == srv.port
    assert saved.name == "Fake"                    # the server's NETWORK name is remembered after the drop
    assert saved.autojoin == "#kept"                # the channel tab still open is saved (user 11-12)
    win.edit_network(saved)                        # Edit Network while still disconnected
    assert len(edited) == 1
    win.close()


# --- 0.6.1: Ergo is not a bouncer (known since 0.4.0) ------------------------------------------------

ERGO_CAPS = ("cap-notify chghost draft/chathistory draft/persistence echo-message ergo.chat/nope extended-join "
             "message-tags multi-prefix server-time soju.im/webpush znc.in/playback znc.in/self-message")


def test_soju_webpush_alone_is_not_soju(app):
    s = session(app)
    s._spot_bouncer({"soju.im/webpush", "draft/chathistory"})
    assert s.bouncer == ""
    s._spot_bouncer({"soju.im/bouncer-networks", "soju.im/webpush"})
    assert s.bouncer == "soju"


def test_znc_caps_from_a_server_without_status_are_not_a_bouncer(app):
    s = session(app)
    s._spot_bouncer(set(ERGO_CAPS.split()))
    assert s.bouncer == "ZNC" and s._znc_guess          # only a guess until *status answers
    s._version_wait = 1.0
    errs = len(s.server_buffer.lines)
    feed(s, ":ergo.test 401 me *status :No such nick")
    assert s.bouncer == "" and not s._znc_guess
    assert len(s.server_buffer.lines) == errs           # the quiet question's answer stays quiet


def test_401_for_status_from_a_real_znc_guess_only(app):
    s = session(app)
    feed(s, ":srv 401 me *status :No such nick")         # no guess: shown as usual, nothing changes
    assert s.bouncer == "" and any("No such nick" in l.text for l in s.server_buffer.lines)


def test_ergo_caps_live_say_no_bouncer_but_real_znc_still_does(app, tmp_path):
    from test_live import live_with, wait
    srv, win, net, s = live_with(app, tmp_path, caps=ERGO_CAPS)
    assert wait(app, lambda: any("PRIVMSG *status :version" in x for x in srv.received), 5000)
    srv.send(f":fake.server 401 {s.nick} *status :No such nick")
    assert wait(app, lambda: s.bouncer == "", 3000)
    t = time.time()
    while time.time() - t < 4.6:                          # past the 4 s 'no version answer' fallback
        app.processEvents(); time.sleep(0.02)
    lines = [l.text for l in s.server_buffer.lines]
    assert not any("Connected through" in x for x in lines) and not any("*status" in x for x in lines)
    assert "Through" not in win.buffer_tip(s.server_buffer)
    win.close(); srv.stop()
    srv, win, net, s = live_with(app, tmp_path, caps="znc.in/self-message")
    assert wait(app, lambda: any("PRIVMSG *status :version" in x for x in srv.received), 5000)
    srv.send(f":*status!znc@h PRIVMSG {s.nick} :ZNC 1.10.3 - https://znc.in")
    assert wait(app, lambda: any("Connected through ZNC 1.10.3" in l.text.replace("\x02", "") for l in s.server_buffer.lines), 3000)
    win.close(); srv.stop()


# --- 0.6.1: 'Host not found' when only the other kind of address exists --------------------------------

def _info(name, *addrs):
    from PySide6.QtNetwork import QHostAddress, QHostInfo
    i = QHostInfo()
    i.setHostName(name)
    i.setAddresses([QHostAddress(a) for a in addrs])
    return i


def _errors(s):
    return [l.text for l in s.server_buffer.lines]


def test_ipv6_only_says_the_server_has_no_ipv6_address(app):
    s = session(app)
    s.cfg.ip_mode = "ipv6"
    s.want_connected = True
    s._family_asked = ("irc.example.org", False)
    s._family_found(_info("irc.example.org", "203.0.113.5"))
    assert any("irc.example.org has no IPv6 address, only IPv4" in t and "Network setup" in t for t in _errors(s))
    assert s.want_connected                              # a saved network keeps retrying, as before


def test_ipv4_only_and_a_typed_name_stops_retrying(app):
    s = session(app)
    s.cfg.ip_mode = "ipv4"
    s.want_connected = True
    s._family_asked = ("v6.example.org", True)
    s._family_found(_info("v6.example.org", "2001:db8::1"))
    assert any("has no IPv4 address, only IPv6" in t for t in _errors(s)) and not s.want_connected


def test_a_name_with_no_address_at_all_is_still_a_typo(app):
    s = session(app)
    s.cfg.ip_mode = "ipv6"
    s.want_connected = True
    s._family_asked = ("irc.exmaple.org", True)
    s._family_found(_info("irc.exmaple.org"))
    assert any("wasn't found, so BChat will not retry" in t for t in _errors(s)) and not s.want_connected
    assert not any("has no" in t for t in _errors(s))


def test_an_answer_for_another_name_or_one_that_now_fits_says_nothing(app):
    s = session(app)
    s.cfg.ip_mode = "ipv6"
    s._family_asked = ("a.example.org", False)
    s._family_found(_info("b.example.org", "203.0.113.5"))
    s._family_found(_info("a.example.org", "2001:db8::1"))
    assert not any("has no" in t for t in _errors(s))


def test_ipv6_only_on_an_ipv4_only_name_live(app, tmp_path):
    """The real path: socket error -> the line. 127.0.0.1 is an address, so no second lookup is needed."""
    from test_live import make_win, wait
    win, net = make_win(tmp_path, 1)
    win.cfg.ip_mode = "ipv6"
    s = win.connect_network(net)
    assert wait(app, lambda: any("127.0.0.1 is an IPv4 address. BChat is set to IPv6 only" in t for t in _errors(s)), 8000)
    win.close()


# --- 0.6.1: a burst of lines no longer freezes the window ----------------------------------------------

def test_a_burst_is_handled_in_slices_in_order(app, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer
    from test_live import live_with, wait
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected", 5000)
    srv.send(f":{s.nick}!u@h JOIN #burst")
    assert wait(app, lambda: "#burst" in s.buffers, 3000)
    b = s.buffers["#burst"]
    slices, gaps, last = [], [], [time.perf_counter()]
    orig = s._drain

    def counted(everything=False):
        slices.append(len(s._rx))
        orig(everything)
    s._drain = counted
    tick = QTimer(); tick.setInterval(20)
    tick.timeout.connect(lambda: (gaps.append(time.perf_counter() - last[0]), last.__setitem__(0, time.perf_counter())))
    srv.client.sendall(b"".join(f":Wira!w@h PRIVMSG #burst :line {i}\r\n".encode() for i in range(3000)) + b":Wira!w@h PRIVMSG #burst :END\r\n")
    loop = QEventLoop(); chk = QTimer(); chk.setInterval(5)
    chk.timeout.connect(lambda: b.lines and b.lines[-1].text == "END" and loop.quit())
    last[0] = time.perf_counter(); tick.start(); chk.start()
    QTimer.singleShot(30000, loop.quit); loop.exec()
    tick.stop(); chk.stop()
    said = [l.text for l in b.lines if l.text.startswith("line ") or l.text == "END"]
    assert said == [f"line {i}" for i in range(3000)] + ["END"]          # nothing lost, nothing out of order
    assert len(slices) > 3                                                # worked through in turns, not in one go
    assert max(gaps) < 0.5, max(gaps)                                     # the window got turns too (was seconds)
    win.close(); srv.stop()


def test_lines_still_queued_are_handled_before_disconnected(app):
    s = session(app)
    feed(s, ":me!u@h JOIN #c")
    s._rx.extend([b":srv NOTICE me :last words\r", b":a!u@h PRIVMSG #c :late line\r"])
    s.state = "connected"
    s._on_disconnected()
    texts = [l.text for l in s.buffers["#c"].lines]
    assert texts.index("late line") < texts.index("Disconnected.") and not s._rx


# --- 0.6.1: passwords typed with // or as /ns, /oper ------------------------------------------------------

def test_double_slash_runs_the_command_the_mirc_way(app, tmp_path):
    """0.6.1 (user: 'mIRC way'): //command runs it. Before, // said the line as chat, so a password went public."""
    from test_live import live_with, type_cmd, wait
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected", 5000)
    srv.send(f":{s.nick}!u@h JOIN #c")
    assert wait(app, lambda: "#c" in s.buffers, 3000)
    b = s.buffers["#c"]
    win.select_buffer(b)
    type_cmd(win, "//ns identify Belon hunter22")
    type_cmd(win, "//msg NickServ IDENTIFY hunter22")
    type_cmd(win, "///oper Belon hunter22")                     # a third slash is still a command
    type_cmd(win, "//me waves")
    type_cmd(win, "/say /me is text here")                     # how to say a line that starts with /
    assert wait(app, lambda: any("/me is text here" in x for x in srv.received), 3000)
    got = srv.received
    assert any(x.upper().startswith("NS IDENTIFY BELON HUNTER22") for x in got)
    assert any(x.upper() == "PRIVMSG NICKSERV :IDENTIFY HUNTER22" for x in got)
    assert any(x.upper() == "OPER BELON HUNTER22" for x in got)
    assert any(x == "PRIVMSG #c :ACTION waves" for x in got)
    assert not any(x.startswith("PRIVMSG #c") and "hunter22" in x for x in got)    # never to the channel
    assert not any("hunter22" in l.text for l in b.lines)
    win.select_buffer(s.server_buffer)                          # the user's case: the server tab
    type_cmd(win, "//ns identify Belon hunter33")
    assert wait(app, lambda: any("HUNTER33" in x.upper() for x in srv.received), 3000)
    assert not any("No channel joined" in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_ns_and_oper_passwords_stay_out_of_the_raw_log(app, tmp_path):
    from test_live import live_with, type_cmd, wait
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected", 5000)
    shown = []
    s.raw_line.connect(lambda line, out: out and shown.append(line))
    win.select_buffer(s.server_buffer)
    type_cmd(win, "/ns identify Belon hunter22")
    type_cmd(win, "/oper Belon hunter22")
    assert wait(app, lambda: any(x.upper().startswith("OPER BELON") for x in srv.received), 3000)
    assert any(x.upper().startswith("NS IDENTIFY") and "hunter22" in x for x in srv.received)   # the server still gets it
    assert any(x.upper() == "NS IDENTIFY ****" for x in shown) and any(x.upper() == "OPER BELON ****" for x in shown)
    assert not any("hunter22" in x for x in shown)
    win.close(); srv.stop()
