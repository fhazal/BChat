"""0.8.6 mockup A + B (OK'd 2026-11-19): one (messages) tab for private messages (Preferences > General >
Channels and Private Chats), and 'Move a server to the top of its network's list when I connect to it'
(Preferences > Advanced > Connecting). Loopback sockets only."""
import socket

from bchat.config import Server
from bchat.protocol import strip_format
from fake_ircd import FakeIrcd
from test_live import live, make_win, prefs, wait  # noqa: F401  (live is a fixture)

M = "(messages)"


def _on(win, friends=False, copy=False):
    win.cfg.single_msg_window, win.cfg.single_msg_friends, win.cfg.single_msg_copy = True, friends, copy


def _rows(b):
    return [(l.kind, strip_format(l.left), strip_format(l.text)) for l in b.lines]


# --- A: one Messages tab -----------------------------------------------------------------------------------------------

def test_off_by_default_private_message_opens_its_own_tab(live):
    app, srv, win, s = live
    assert not win.cfg.single_msg_window and not win.cfg.move_to_top
    srv.send(":alice!a@h PRIVMSG Badaboom :hello there")
    assert wait(app, lambda: "alice" in s.buffers)
    assert M not in s.buffers


def test_private_messages_from_two_nicks_land_in_one_tab(live):
    app, srv, win, s = live
    _on(win)
    srv.send(":alice!a@h PRIVMSG Badaboom :hello there")
    srv.send(":bob!b@h PRIVMSG Badaboom :\x01ACTION waves\x01")
    assert wait(app, lambda: M in s.buffers and len(s.buffers[M].lines) >= 2)
    rows = _rows(s.buffers[M])
    assert any(r[1] == "alice" and r[2] == "hello there" for r in rows), rows
    assert any(r[1] == "*" and r[2] == "bob waves" for r in rows), rows
    assert "alice" not in s.buffers and "bob" not in s.buffers
    assert win.recent_private(s)[:2] == ["bob", "alice"]       # empty-box Tab cycles them, newest first


def test_open_private_chat_still_gets_its_lines(live):
    app, srv, win, s = live
    _on(win)
    win.run_command(s, "/query carol")
    assert "carol" in s.buffers
    srv.send(":carol!c@h PRIVMSG Badaboom :to my tab")
    assert wait(app, lambda: any(l.text == "to my tab" for l in s.buffers["carol"].lines))
    assert M not in s.buffers or not any("to my tab" in l.text for l in s.buffers[M].lines)


def test_typing_in_messages_tab_explains_how_to_reply(live):
    app, srv, win, s = live
    _on(win)
    srv.send(":alice!a@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: M in s.buffers)
    before = len(srv.received)
    from bchat import commands
    commands.run(win, s, s.buffers[M], "hello?")
    assert any("Reply with /msg nick" in l.text for l in s.buffers[M].lines)
    for _ in range(20):
        app.processEvents()
    assert not any(x.startswith("PRIVMSG (messages)") for x in srv.received[before:])


def test_friends_still_get_their_own_private_chat(live, monkeypatch):
    app, srv, win, s = live
    _on(win, friends=True)
    monkeypatch.setattr(s, "_friends_here", lambda: ["dave"])
    srv.send(":dave!d@h PRIVMSG Badaboom :friend here")
    srv.send(":erin!e@h PRIVMSG Badaboom :stranger here")
    assert wait(app, lambda: "dave" in s.buffers and M in s.buffers)
    assert "erin" not in s.buffers


def test_copy_conversation_into_new_private_chat(live):
    app, srv, win, s = live
    _on(win, copy=True)
    srv.send(":alice!a@h PRIVMSG Badaboom :first")
    srv.send(":bob!b@h PRIVMSG Badaboom :not yours")
    srv.send(":alice!a@h PRIVMSG Badaboom :\x01ACTION smiles\x01")
    assert wait(app, lambda: M in s.buffers and len(s.buffers[M].lines) >= 3)
    win.run_command(s, "/query alice")
    texts = [strip_format(l.text) for l in s.buffers["alice"].lines]
    assert "first" in texts and "alice smiles" in texts and "not yours" not in texts


def test_no_copy_when_sub_option_off(live):
    app, srv, win, s = live
    _on(win)
    srv.send(":alice!a@h PRIVMSG Badaboom :first")
    assert wait(app, lambda: M in s.buffers)
    win.run_command(s, "/query alice")
    assert not any(l.text == "first" for l in s.buffers["alice"].lines)


def test_preferences_rows_save_and_sub_options_grey_out(live):
    app, srv, win, s = live
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    assert not d.single_msg.isChecked() and not d.single_friends.isEnabled() and not d.single_copy.isEnabled()
    d.single_msg.setChecked(True)
    assert d.single_friends.isEnabled() and d.single_copy.isEnabled()
    d.single_copy.setChecked(True)
    d.move_top.setChecked(True)
    d.accept(); d.deleteLater()
    c = win.cfg
    assert c.single_msg_window and c.single_msg_copy and not c.single_msg_friends and c.move_to_top


# --- B: move to top on connect -----------------------------------------------------------------------------------------

def test_server_that_connected_moves_to_top_and_is_saved(app, tmp_path, monkeypatch):
    dead = socket.socket(); dead.bind(("127.0.0.1", 0)); port = dead.getsockname()[1]; dead.close()
    srv = FakeIrcd()
    win, net = make_win(tmp_path, port)
    net.servers.append(Server("127.0.0.1", srv.port, False))
    net.cycle = True
    win.cfg.move_to_top, win.cfg.reconnect_delay = True, 1
    saved = []
    monkeypatch.setattr(win, "save_config", lambda: saved.append([x.port for x in net.servers]))
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 15000), [l.text for l in s.server_buffer.lines]
    assert [x.port for x in net.servers] == [srv.port, port] and s.server_index == 0
    assert saved and saved[-1] == [srv.port, port]
    win.close(); srv.stop()


def test_option_off_keeps_order(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    net.servers.append(Server("127.0.0.1", 1, False))
    s = win.connect_network(net)
    s.server_index = 1           # as if the second server had let us in
    s._move_to_top()
    assert [x.port for x in net.servers] == [srv.port, 1]
    win.close(); srv.stop()


def test_empty_download_folder_shows_where_files_go(live):
    app, srv, win, s = live
    from bchat.preferences import PreferencesDialog
    win.cfg.dcc_dir = ""
    d = PreferencesDialog(win)
    assert d.dcc_dir.text() == "" and d.dcc_dir.placeholderText() == str(win.cfg_dir / "downloads")
    assert d.dcc_done.placeholderText()
    d.accept(); d.deleteLater()
    assert win.cfg.dcc_dir == ""          # the hint is never saved as a real setting


def test_me_say_sysinfo_in_messages_tab_send_nothing(live):
    """QA BUG-2: /me (and anything else that sends to the current tab) must never PRIVMSG "(messages)"."""
    app, srv, win, s = live
    _on(win)
    srv.send(":alice!a@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: M in s.buffers)
    from bchat import commands
    before = len(srv.received)
    for line in ("/me waves", "/say hello", "/sysinfo", "/action waves"):
        commands.run(win, s, s.buffers[M], line)
    srv.send("PING :done")
    assert wait(app, lambda: any(x.startswith("PONG") for x in srv.received[before:]))
    assert not any("(messages)" in x for x in srv.received[before:]), srv.received[before:]
    assert sum("Reply with /msg nick" in l.text for l in s.buffers[M].lines) >= 4
