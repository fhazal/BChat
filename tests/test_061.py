"""0.6.1: FINDING-01, nicks and channel names folded the way each server says (ISUPPORT CASEMAPPING)."""
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
