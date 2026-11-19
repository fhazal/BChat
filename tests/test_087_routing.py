"""0.8.7 option A (OK'd): /ctcps on|off + Settings > Advanced > Reply to CTCP requests; Settings > Windows: where
WHOIS, notices, CTCP requests, away replies and nick changes show, and what a double-click does on each kind of window.
Defaults must be what BChat did before. Loopback sockets only."""
import json
import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from bchat import config
from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import strip_format
from bchat.session import CHANNEL, NOTICE, WHOIS
from fake_ircd import FakeIrcd
from test_live import live, make_win, prefs, wait  # noqa: F401  (live is a fixture)

NEW_FIELDS = ("ctcp_reply_enabled", "show_whois", "show_notices", "show_ctcp", "show_away", "show_nicks",
              "dbl_channel", "dbl_query", "dbl_server", "dbl_chat", "dbl_nick",
              "dbl_channel_cmd", "dbl_query_cmd", "dbl_server_cmd", "dbl_chat_cmd", "dbl_nick_cmd")


def _texts(b):
    return [strip_format(l.text) for l in b.lines]


def _has(b, part):
    return any(part in t for t in _texts(b))


def _settle(app, ms=250):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


# --- config ----------------------------------------------------------------------------------------------------------

def test_defaults_are_todays_behaviour():
    c = Config()
    assert c.ctcp_reply_enabled is True
    assert (c.show_whois, c.show_notices, c.show_ctcp, c.show_away, c.show_nicks) == ("active",) * 4 + ("shared",)
    assert (c.dbl_channel, c.dbl_query, c.dbl_server, c.dbl_chat, c.dbl_nick) == ("nothing", "nothing", "expand", "modes", "nothing")
    assert c.ul_double == "QUERY %s" and c.notices_tab is False


def test_old_config_without_new_fields_gets_defaults(tmp_path):
    config.save(Config(nick="Old"), tmp_path)
    p = tmp_path / "config.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for k in NEW_FIELDS:
        d.pop(k, None)
    d["ul_double"], d["notices_tab"] = "WHOIS %s", True
    p.write_text(json.dumps(d), encoding="utf-8")
    c = config.load(tmp_path)
    fresh = Config()
    assert all(getattr(c, k) == getattr(fresh, k) for k in NEW_FIELDS)
    assert c.nick == "Old" and c.ul_double == "WHOIS %s" and c.notices_tab is True


def test_new_fields_round_trip(tmp_path):
    c = Config(ctcp_reply_enabled=False, show_whois="server", show_nicks="active", dbl_chat="custom", dbl_chat_cmd="/echo $chan")
    config.save(c, tmp_path)
    back = config.load(tmp_path)
    assert (back.ctcp_reply_enabled, back.show_whois, back.show_nicks, back.dbl_chat, back.dbl_chat_cmd) == \
        (False, "server", "active", "custom", "/echo $chan")


# --- /ctcps ----------------------------------------------------------------------------------------------------------

def test_ctcps_state_off_on_and_saved(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    win.run_command(s, "/ctcps")
    assert _texts(b)[-1] == "CTCP replies: on"
    win.run_command(s, "/ctcps off")
    assert _texts(b)[-1] == "CTCP replies are off: VERSION, PING, TIME, FINGER, CLIENTINFO get no answer."
    assert win.cfg.ctcp_reply_enabled is False
    assert config.load(win.cfg_dir).ctcp_reply_enabled is False          # saved with the normal config save
    win.run_command(s, "/ctcps")
    assert _texts(b)[-1] == "CTCP replies: off"
    win.run_command(s, "/ctcps on")
    assert _texts(b)[-1] == "CTCP replies are on." and win.cfg.ctcp_reply_enabled
    assert config.load(win.cfg_dir).ctcp_reply_enabled is True
    win.run_command(s, "/ctcps maybe")
    assert _texts(b)[-1].startswith("Usage: CTCPS")


def test_ctcp_replies_off_sends_nothing_but_shows_request(live):
    app, srv, win, s = live
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    win.cfg.ctcp_reply_enabled = False
    for verb in ("VERSION", "PING 123", "TIME", "FINGER", "CLIENTINFO", "USERINFO", "SOURCE"):
        srv.send(f":alice!a@h PRIVMSG Badaboom :\x01{verb}\x01")
    assert wait(app, lambda: sum("Received a CTCP" in t for t in _texts(b)) == 7), _texts(b)[-8:]
    _settle(app, 400)
    assert not any(x.startswith("NOTICE alice") for x in srv.received), srv.received[-10:]
    srv.send(":alice!a@h PRIVMSG #skinhead :\x01ACTION waves\x01")              # /me is never blocked
    assert wait(app, lambda: _has(b, "alice waves"))


def test_ctcp_replies_on_answers(live):
    app, srv, win, s = live
    win.select_buffer(s.buffers["#skinhead"])
    srv.send(":alice!a@h PRIVMSG Badaboom :\x01VERSION\x01")
    assert wait(app, lambda: any(x.startswith("NOTICE alice :\x01VERSION BChat") for x in srv.received)), srv.received[-5:]


def test_ctcp_off_dcc_still_offered(live):
    app, srv, win, s = live
    win.cfg.ctcp_reply_enabled = False
    seen = []
    s.on_dcc = lambda sess, nick, rest: seen.append((nick, rest))
    srv.send(":alice!a@h PRIVMSG Badaboom :\x01DCC CHAT chat 2130706433 5000\x01")
    assert wait(app, lambda: seen), "DCC must never be blocked"


def test_settings_checkbox_is_the_same_setting(live):
    app, srv, win, s = live
    prefs(win, lambda d: d.ctcp_reply.setChecked(False))
    assert win.cfg.ctcp_reply_enabled is False
    assert config.load(win.cfg_dir).ctcp_reply_enabled is False
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    assert d.ctcp_reply.isChecked() is False
    d.reject(); d.deleteLater()


# --- where events show -----------------------------------------------------------------------------------------------

def _query(win, s, nick, ran=None):
    win.run_command(s, f"/query {nick}")
    if ran is not None:
        ran.clear()                                   # the /query itself is not a double-click
    return s.buffers[nick.lower()]


@pytest.mark.parametrize("where", ["active", "server", "messages", "query"])
def test_ctcp_request_routing(live, where):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    q = _query(win, s, "alice") if where == "query" else None
    win.select_buffer(chan)
    win.cfg.show_ctcp = where
    srv.send(":alice!a@h PRIVMSG Badaboom :\x01TIME\x01")
    dest = {"active": chan, "server": s.server_buffer, "query": q}.get(where) or s.buffer(s.MESSAGES)
    assert wait(app, lambda: _has(dest, "Received a CTCP TIME from alice")), _texts(dest)[-3:]


def test_query_choice_falls_back_to_active_window(live):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    win.select_buffer(chan)
    win.cfg.show_ctcp = win.cfg.show_notices = win.cfg.show_away = "query"
    srv.send(":bob!b@h PRIVMSG Badaboom :\x01TIME\x01")
    srv.send(":bob!b@h NOTICE Badaboom :psst")
    srv.send(":srv 301 Badaboom bob :gone fishing")
    assert wait(app, lambda: _has(chan, "Received a CTCP TIME from bob") and _has(chan, "psst") and _has(chan, "gone fishing"))
    assert "bob" not in s.buffers


@pytest.mark.parametrize("where", ["active", "server", "messages", "query"])
def test_private_notice_routing(live, where):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    q = _query(win, s, "carol") if where == "query" else None
    win.select_buffer(chan)
    win.cfg.show_notices = where
    srv.send(":carol!c@h NOTICE Badaboom :hello by notice")
    dest = {"active": chan, "server": s.server_buffer, "query": q}.get(where) or s.buffer(s.MESSAGES)
    assert wait(app, lambda: any(l.kind == NOTICE and "hello by notice" in l.text for l in dest.lines))


def test_channel_and_server_notices_ignore_the_notices_choice(live):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    win.select_buffer(chan)
    win.cfg.show_notices = "messages"
    win.cfg.notices_tab = True                       # server notices: still their own setting
    srv.send(":carol!c@h NOTICE #skinhead :to the channel")
    srv.send(":irc.fake.org NOTICE Badaboom :server says hi")
    assert wait(app, lambda: _has(chan, "to the channel") and "(notices)" in s.buffers
                and _has(s.buffers["(notices)"], "server says hi"))
    assert s.MESSAGES not in s.buffers


@pytest.mark.parametrize("where", ["active", "server", "messages", "query"])
def test_away_reply_routing(live, where):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    q = _query(win, s, "dave") if where == "query" else None
    win.select_buffer(chan)
    win.cfg.show_away = where
    srv.send(":srv 301 Badaboom dave :out to lunch")
    dest = {"active": chan, "server": s.server_buffer, "query": q}.get(where) or s.buffer(s.MESSAGES)
    assert wait(app, lambda: _has(dest, "dave is away: out to lunch")), _texts(dest)[-3:]


@pytest.mark.parametrize("where", ["active", "server", "messages", "query"])
def test_whois_routing(live, where):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    q = _query(win, s, "Oracle") if where == "query" else None
    win.select_buffer(chan)
    win.cfg.show_whois = where
    win.run_command(s, "/whois Oracle")
    dest = {"active": chan, "server": s.server_buffer, "query": q}.get(where) or s.buffer(s.MESSAGES)
    assert wait(app, lambda: any(l.kind == WHOIS and "End of WHOIS" in l.text for l in dest.lines)), _texts(dest)[-3:]
    if where != "active":
        assert not any(l.kind == WHOIS for l in chan.lines)


def test_nick_change_default_shows_in_every_shared_channel(live):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    win.select_buffer(s.server_buffer)
    srv.send(":Belon!b@h NICK Belon2")
    assert wait(app, lambda: _has(chan, "Belon is now known as Belon2")), _texts(chan)[-3:]
    assert not _has(s.server_buffer, "Belon is now known as Belon2")


@pytest.mark.parametrize("where", ["active", "server"])
def test_nick_change_one_line_elsewhere(live, where):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    q = _query(win, s, "Fhazal")
    win.select_buffer(q if where == "active" else chan)
    win.cfg.show_nicks = where
    srv.send(":Fhazal!f@h NICK Fhazal2")
    assert wait(app, lambda: "fhazal2" in s.buffers and "fhazal2" in chan.users)
    _settle(app, 100)
    assert not _has(chan, "is now known as")                                  # not in the shared channel
    assert sum("Fhazal is now known as Fhazal2" in t for t in _texts(q)) == 1      # the renamed query: one line
    if where == "server":
        assert _has(s.server_buffer, "Fhazal is now known as Fhazal2")


def test_nick_change_active_window_other_tab(live):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    win.select_buffer(s.server_buffer)
    win.cfg.show_nicks = "active"
    srv.send(":Psycho!p@h NICK Psycho2")
    assert wait(app, lambda: _has(s.server_buffer, "Psycho is now known as Psycho2"))
    assert not _has(chan, "Psycho is now known as")


def test_cross_server_active_window_uses_own_server_tab(app, tmp_path):
    """Focus on another network's window: the event stays on its own server's tab (as before 0.8.7)."""
    a, b = FakeIrcd(), FakeIrcd()
    win, net = make_win(tmp_path, a.port)
    net2 = NetworkConfig("OtherNet", [Server("127.0.0.1", b.port, False)], autojoin="#skinhead")
    win.cfg.networks.append(net2)
    try:
        s1 = win.connect_network(net)
        s2 = win.connect_network(net2)
        assert wait(app, lambda: "#skinhead" in s1.buffers and "#skinhead" in s2.buffers
                    and len(s1.buffers["#skinhead"].users) == 14 and len(s2.buffers["#skinhead"].users) == 14)
        focus = s1.buffers["#skinhead"]
        win.select_buffer(focus)
        b.send(":zed!z@h PRIVMSG Badaboom :TIME")
        b.send(":zed!z@h NOTICE Badaboom :from afar")
        assert wait(app, lambda: _has(s2.server_buffer, "Received a CTCP TIME from zed") and _has(s2.server_buffer, "from afar")),             _texts(s2.server_buffer)[-4:]
        assert not _has(focus, "from afar")
        a.send(":yan!y@h NOTICE Badaboom :close by")                          # its own server: the focused tab
        assert wait(app, lambda: "close by" in _texts(focus))
    finally:
        win.close()
        a.stop()
        b.stop()


# --- double-click ----------------------------------------------------------------------------------------------------

def _record(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "open_channel_central", lambda b=None: calls.append(("modes", b.name if b else None)))
    monkeypatch.setattr(win, "open_channel_list", lambda s, download=None: calls.append(("list", s.net.name)))
    monkeypatch.setattr(win, "close_buffer", lambda b: calls.append(("close", b.name)))
    ran = []
    real_run = win.run_command
    import bchat.mainwindow as mw
    orig = mw.commands.run

    def fake_run(ui, s, b, text, depth=0):
        ran.append((b.name, text))
        if not text.startswith(("/query", "/echo")):
            return None
        return orig(ui, s, b, text, depth)
    monkeypatch.setattr(mw.commands, "run", fake_run)
    return calls, ran, real_run


def test_tree_double_click_defaults(live, monkeypatch):
    app, srv, win, s = live
    calls, ran, _ = _record(win, monkeypatch)
    q = _query(win, s, "erin", ran)
    top = win.items[id(s.server_buffer)]
    was = top.isExpanded()
    win._tree_double_clicked(top)
    assert top.isExpanded() != was                    # server row: expand/collapse, as before
    win._tree_double_clicked(win.items[id(s.buffers["#skinhead"])])
    win._tree_double_clicked(win.items[id(q)])
    assert calls == [] and ran == [] and not any(x.startswith("WHOIS") for x in srv.received)


def test_tab_double_click_default_does_nothing(live, monkeypatch):
    app, srv, win, s = live
    calls, ran, _ = _record(win, monkeypatch)
    for b in (s.server_buffer, s.buffers["#skinhead"]):
        win._switcher_double(b)                       # a tab: no tree row to fold
    for i in range(win.tabbar.count()):
        win._tab_double_clicked(i)
    assert calls == [] and ran == []


def test_switcher_double_click_choices(live, monkeypatch):
    app, srv, win, s = live
    calls, ran, _ = _record(win, monkeypatch)
    chan, srvb = s.buffers["#skinhead"], s.server_buffer
    q = _query(win, s, "erin", ran)
    c = win.cfg
    for choice, want in (("modes", ("modes", "#skinhead")), ("list", ("list", "SkinIRC")), ("part", ("close", "#skinhead"))):
        c.dbl_channel = choice
        calls.clear()
        win._switcher_double(chan)
        assert calls == [want], choice
    c.dbl_query = "close"; calls.clear()
    win._switcher_double(q)
    assert calls == [("close", "erin")]
    c.dbl_query = "whois"
    win._switcher_double(q)
    assert wait(app, lambda: "WHOIS erin erin" in srv.received)
    c.dbl_server = "list"; calls.clear()
    top = win.items[id(srvb)]
    was = top.isExpanded()
    win._tree_double_clicked(top)
    assert calls == [("list", "SkinIRC")] and top.isExpanded() == was
    c.dbl_server = "nothing"; calls.clear()
    win._tree_double_clicked(top)
    assert calls == [] and top.isExpanded() == was


def test_custom_command_substitutes(live, monkeypatch):
    app, srv, win, s = live
    calls, ran, _ = _record(win, monkeypatch)
    chan = s.buffers["#skinhead"]
    q = _query(win, s, "erin", ran)
    c = win.cfg
    c.dbl_channel, c.dbl_channel_cmd = "custom", "/echo $nick in $chan on $network"
    win._switcher_double(chan)
    assert ran[-1] == ("#skinhead", "/echo Badaboom in #skinhead on SkinIRC")
    assert _texts(chan)[-1] == "Badaboom in #skinhead on SkinIRC"
    c.dbl_query, c.dbl_query_cmd = "custom", "/echo hi $nick"
    win._switcher_double(q)
    assert ran[-1] == ("erin", "/echo hi erin")
    c.dbl_server, c.dbl_server_cmd = "custom", "/echo net $network"
    win._switcher_double(s.server_buffer)
    assert ran[-1][1] == "/echo net SkinIRC"


def test_chat_area_default_opens_channel_modes_only_in_channels(live, monkeypatch):
    app, srv, win, s = live
    calls, ran, _ = _record(win, monkeypatch)
    chan = s.buffers["#skinhead"]
    win.select_buffer(chan)
    view = win.chat.currentWidget()
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(view.viewport().width() - 5, view.viewport().height() - 5))
    assert wait(app, lambda: calls == [("modes", "#skinhead")]), calls
    assert win._chat_double(chan, "", True) is False                # a link: Qt's own handling, as before
    assert win._chat_double(s.server_buffer, "", False) is False   # server tab: the word is selected, as before
    calls.clear()
    assert win._chat_double(chan, "Oracle", False) is True         # nick default: same as the chat area
    assert calls == [("modes", "#skinhead")]


def test_chat_area_and_nick_choices(live, monkeypatch):
    app, srv, win, s = live
    calls, ran, _ = _record(win, monkeypatch)
    chan = s.buffers["#skinhead"]
    win.select_buffer(chan)
    c = win.cfg
    c.dbl_chat = "nothing"
    assert win._chat_double(chan, "", False) is False and calls == []
    c.dbl_chat = "list"
    assert win._chat_double(chan, "hello", False) is True and calls == [("list", "SkinIRC")]
    c.dbl_chat, c.dbl_chat_cmd = "custom", "/echo area $chan"
    assert win._chat_double(chan, "", False) is True and ran[-1] == ("#skinhead", "/echo area #skinhead")
    c.dbl_nick = "query"
    assert win.chat.currentWidget().double_click(chan, "Oracle", False) is True       # through the pane's hook
    assert wait(app, lambda: "oracle" in s.buffers)
    c.dbl_nick = "whois"
    win._chat_double(chan, "Belon", False)
    assert wait(app, lambda: "WHOIS Belon Belon" in srv.received)
    c.dbl_nick, c.dbl_nick_cmd = "custom", "/echo poke $nick from $chan"
    win._chat_double(chan, "Psycho", False)
    assert ran[-1] == ("#skinhead", "/echo poke Psycho from #skinhead")
    assert win._chat_double(chan, "notanick", False) is True and ran[-1] == ("#skinhead", "/echo area #skinhead")


def test_channel_word_always_joins(live):
    app, srv, win, s = live
    chan = s.buffers["#skinhead"]
    win.select_buffer(chan)
    win.cfg.dbl_chat = "nothing"
    view = win.chat.currentWidget()
    joined = []
    view.channel_double_clicked.connect(joined.append)
    s.add(chan, "info", "*", "come to #kampung now")
    _settle(app, 100)
    cur = view.document().find("#kampung")
    rect = view.cursorRect(cur)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center() - QPoint(8, 0))
    assert wait(app, lambda: joined == ["#kampung"]), joined


def test_nick_list_choices_and_substitution(live, monkeypatch):
    app, srv, win, s = live
    calls, ran, _ = _record(win, monkeypatch)
    chan = s.buffers["#skinhead"]
    win.select_buffer(chan)
    idx = win.userlist.model().index(6)                        # Oracle
    win._nick_double(idx)
    assert ran[-1] == ("#skinhead", "/QUERY Oracle")              # default: open a private chat, as before
    win.cfg.ul_double = "WHOIS %s"
    win._nick_double(idx)
    assert wait(app, lambda: "WHOIS Oracle Oracle" in srv.received)
    win.cfg.ul_double = "echo %s / $nick / $chan / $network"
    win._nick_double(idx)
    assert ran[-1] == ("#skinhead", "/echo Oracle / Oracle / #skinhead / SkinIRC")


# --- Settings > Windows ------------------------------------------------------------------------------------------------

def test_windows_page_saves_and_reloads(live):
    app, srv, win, s = live
    from bchat.preferences import BUILT, CATEGORIES, PreferencesDialog
    assert "Windows" in BUILT and "Windows" in CATEGORIES["Interface"]

    def change(d):
        d.show_page("Windows")
        d.show_whois.setCurrentIndex(d.show_whois.findData("server"))
        d.show_notices.setCurrentIndex(d.show_notices.findData("messages"))
        d.show_ctcp.setCurrentIndex(d.show_ctcp.findData("query"))
        d.show_away.setCurrentIndex(d.show_away.findData("server"))
        d.show_nicks.setCurrentIndex(d.show_nicks.findData("active"))
        d.dbl["channel"].setCurrentIndex(d.dbl["channel"].findData("custom"))
        d.dbl_cmd["channel"].setText("/echo $chan")
        d.dbl["server"].setCurrentIndex(d.dbl["server"].findData("list"))
        d.dbl_ul.setCurrentIndex(1)                                       # WHOIS
    prefs(win, change)
    c = config.load(win.cfg_dir)
    assert (c.show_whois, c.show_notices, c.show_ctcp, c.show_away, c.show_nicks) == ("server", "messages", "query", "server", "active")
    assert (c.dbl_channel, c.dbl_channel_cmd, c.dbl_server) == ("custom", "/echo $chan", "list")
    assert c.ul_double == "WHOIS %s"
    d = PreferencesDialog(win)
    assert d.show_whois.currentData() == "server" and d.dbl["channel"].currentData() == "custom"
    assert d.dbl_ul.currentIndex() == 1 and d.ul_double.text() == "WHOIS %s"
    d.reject(); d.deleteLater()


def test_windows_page_defaults_and_custom_line(live):
    app, srv, win, s = live
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    d.show_page("Windows")
    d.show()
    _settle(app, 50)
    assert [d.show_whois.currentText(), d.show_notices.currentText(), d.show_ctcp.currentText(),
            d.show_away.currentText(), d.show_nicks.currentText()] == ["Active window"] * 4 + ["Channels shared"]
    assert [d.dbl[k].currentText() for k in ("channel", "query", "server", "chat", "nick")] == \
        ["Nothing", "Nothing", "Expand/collapse", "Channel modes", "Same as chat area"]
    assert d.dbl_ul.currentText() == "Open query"
    assert not d.dbl_cmd["chat"].isVisible()
    d.dbl["chat"].setCurrentIndex(d.dbl["chat"].findData("custom"))
    assert d.dbl_cmd["chat"].isVisible()
    # the nick list choice and User list > Execute command are one setting
    d.ul_double.setText("QUOTE WHOIS %s %s")
    assert d.dbl_ul.currentIndex() == 1
    d.ul_double.setText("/msg %s hi")
    assert d.dbl_ul.currentIndex() == 2 and d.dbl_ul_cmd.text() == "/msg %s hi"
    d.dbl_ul.setCurrentIndex(0)
    assert d.ul_double.text() == "QUERY %s"
    area = d.pages.currentWidget()
    assert area.widget().minimumSizeHint().width() <= area.viewport().width()     # no sideways scrolling
    d.show_page("Advanced")
    _settle(app, 50)
    area = d.pages.currentWidget()
    assert area.widget().minimumSizeHint().width() <= area.viewport().width()     # no sideways scrolling
    d.reject(); d.deleteLater()
