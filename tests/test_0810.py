"""0.8.10 small leftovers: chat offers get their own choice and both kinds can be ignored (/creq, /sreq), servers that
skip the proxy, /updatenl, /queryrn and /timerN."""
import json
import time

from fake_ircd import FakeIrcd

from bchat import config
from bchat.preferences import PreferencesDialog
from bchat.session import QUERY, skips_proxy
from test_060 import joined
from test_088_net import FakeSocks4, texts, use_proxy
from test_live import live_with, make_win, prefs, wait


def lines(s):
    return [l.text for b in s.all_buffers() for l in b.lines]


def settle(app, ms=300):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


# --- offers ---------------------------------------------------------------------------------------------------

def test_settings_has_two_offer_menus_and_saves_both(app, tmp_path):
    win, _net = make_win(tmp_path, 9)
    win.cfg.dcc_auto, win.cfg.dcc_chat_auto = 1, 3
    d = PreferencesDialog(win, "File transfers")
    items = [d.dcc_auto.itemText(i) for i in range(d.dcc_auto.count())]
    assert items == ["Ask me", "Accept from trusted people", "Accept from everyone", "Ignore them"]
    assert items == [d.chat_auto.itemText(i) for i in range(d.chat_auto.count())]
    assert d.dcc_auto.currentText() == "Accept from everyone" and d.chat_auto.currentText() == "Ignore them"
    d.dcc_auto.setCurrentIndex(3)
    d.chat_auto.setCurrentIndex(1)
    d.accept(); d.deleteLater()
    assert (win.cfg.dcc_auto, win.cfg.dcc_chat_auto) == (3, 2)
    win.close()


def test_older_settings_keep_trusted_chats(tmp_path):
    for auto, chat in ((0, 0), (1, 2), (2, 2)):
        (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "dcc_auto": auto}), encoding="utf-8")
        assert config.load(tmp_path).dcc_chat_auto == chat
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "dcc_auto": 1, "dcc_chat_auto": 0}), encoding="utf-8")
    assert config.load(tmp_path).dcc_chat_auto == 0


def test_ignored_file_offer_is_one_grey_line(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    win.cfg.dcc_auto = 3
    for _ in range(3):
        srv.send(":Spam!s@x PRIVMSG Badaboom :\x01DCC SEND free.zip 2130706433 9 100\x01")
    assert wait(app, lambda: any("Ignored a file offer from Spam" in t for t in lines(s)))
    settle(app)
    assert sum("Ignored a file offer from Spam" in l.text for l in s.server_buffer.lines) == 1
    assert not [t for t in win.dcc.items if t.kind == "recv"]
    assert not any("has offered" in t for t in lines(s))
    win.close(); srv.stop()


def test_chat_offers_follow_their_own_menu(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    win.cfg.dcc_open_chat = False
    win.cfg.dcc_auto, win.cfg.dcc_chat_auto = 1, 3          # files from everyone, chats ignored
    srv.send(":Spam!s@x PRIVMSG Badaboom :\x01DCC CHAT chat 2130706433 9\x01")
    assert wait(app, lambda: any("Ignored a direct chat offer from Spam" in l.text for l in s.server_buffer.lines))
    assert not [t for t in win.dcc.items if t.kind == "chat"]
    win.cfg.dcc_auto, win.cfg.dcc_chat_auto = 3, 0          # files ignored, chats asked: the chat offer still comes
    srv.send(":Wira!wira@bsn.my PRIVMSG Badaboom :\x01DCC CHAT chat 2130706433 9\x01")
    assert wait(app, lambda: any("Received a DCC CHAT offer from Wira" in t for t in lines(s)))
    chat = next(t for t in win.dcc.items if t.kind == "chat")
    assert chat.state not in ("connecting", "active")
    win.close(); srv.stop()


def test_creq_and_sreq_set_the_menus(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    from bchat.commands import run
    run(win, s, b, "/creq ignore")
    run(win, s, b, "/sreq auto")
    assert (win.cfg.dcc_chat_auto, win.cfg.dcc_auto) == (3, 1)
    run(win, s, b, "/sreq trusted")
    run(win, s, b, "/creq")
    run(win, s, b, "/sreq maybe")
    t = [l.text for l in b.lines]
    assert "Direct chat offers: Ignore them. (Settings > File transfers > Options)" in t
    assert "File offers: Accept from everyone. (Settings > File transfers > Options)" in t
    assert "File offers: Accept from trusted people. (Settings > File transfers > Options)" in t
    assert "Direct chat offers: Ignore them." in t
    assert "Use: /sreq ask|auto|trusted|ignore" in t
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["dcc_auto"] == 2
    win.close(); srv.stop()


# --- proxy exceptions -----------------------------------------------------------------------------------------

def test_skip_rules():
    rules = "localhost, 127.0.0.1 *.lan;10.*"
    assert skips_proxy(rules, "LocalHost") and skips_proxy(rules, "irc.home.lan.") and skips_proxy(rules, "10.1.2.3")
    assert not skips_proxy(rules, "irc.libera.chat") and not skips_proxy(rules, "lan") and not skips_proxy("", "x")
    assert skips_proxy("::1", "[::1]") and skips_proxy("[::1]", "::1")


def test_listed_server_connects_directly(app, tmp_path):
    target, proxy = FakeIrcd(), FakeSocks4()
    win, net = make_win(tmp_path, target.port)
    use_proxy(win, proxy, 3, "beeuser")
    prefs(win, lambda d: d.proxy_skip.setText(" localhost, 127.0.0.1 "))
    assert win.cfg.proxy_skip == "localhost, 127.0.0.1"
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), texts(s)
    assert proxy.seen == [] and not any("proxy" in t for t in texts(s))
    s.disconnect_from_network()
    win.close(); target.stop(); proxy.stop()


def test_unlisted_server_still_uses_the_proxy(app, tmp_path):
    target, proxy = FakeIrcd(), FakeSocks4()
    win, net = make_win(tmp_path, target.port)
    use_proxy(win, proxy, 3, "beeuser")
    win.cfg.proxy_skip = "localhost, *.lan"
    s = win.connect_network(net)
    assert wait(app, lambda: s.state == "connected", 8000), texts(s)
    assert proxy.seen == [(4, 1, "127.0.0.1", target.port, "beeuser", "")]
    s.disconnect_from_network()
    win.close(); target.stop(); proxy.stop()


def test_not_for_row_hides_with_the_proxy(app, tmp_path):
    win, _net = make_win(tmp_path, 9)
    d = PreferencesDialog(win, "Network setup")
    d.show()
    d.proxy_type.setCurrentIndex(0)
    assert not d.proxy_skip.isVisible()
    assert d.proxy_skip.placeholderText() == "localhost, 127.0.0.1, *.lan"
    d.proxy_type.setCurrentIndex(1)
    hint = d._proxy_grid.itemAtPosition(4, 1).widget()
    assert d.proxy_skip.isVisible() and hint.isVisible() and "connect directly" in hint.text()
    d.reject(); d.deleteLater()
    win.close()


# --- commands -------------------------------------------------------------------------------------------------

def test_updatenl_rebuilds_the_nick_list(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    from bchat.commands import run
    b.users.pop("badaboom")                      # the list has gone wrong
    run(win, s, b, "/updatenl")
    assert wait(app, lambda: "NAMES #skinhead" in srv.received)
    srv.send(":srv 353 Badaboom = #skinhead :@Fhazal @Psycho +Oracle Badaboom Wira")
    srv.send(":srv 366 Badaboom #skinhead :End of NAMES")
    assert wait(app, lambda: any(l.text == "Nick list for #skinhead rebuilt: 5 people, 2 ops, 1 voiced." for l in b.lines))
    assert sorted(b.users) == ["badaboom", "fhazal", "oracle", "psycho", "wira"]
    srv.send(":srv 366 Badaboom #skinhead :End of NAMES")      # a later plain reply prints nothing
    settle(app)
    assert sum("rebuilt" in l.text for l in b.lines) == 1
    run(win, s, s.server_buffer, "/updatenl")
    assert s.server_buffer.lines[-1].text == "/updatenl needs a channel tab."
    win.close(); srv.stop()


def test_queryrn_renames_a_private_tab(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    from bchat.commands import run
    srv.send(":Dave!d@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: "dave" in s.buffers)
    q = s.buffers["dave"]
    run(win, s, b, "/queryrn Dave Dave_away")
    assert q.name == "Dave_away" and s.buffers["dave_away"] is q and "dave" not in s.buffers and q.kind == QUERY
    assert q.lines[-1].text == "Private tab Dave is now Dave_away."
    run(win, s, b, "/queryrn Nobody x")
    run(win, s, b, "/queryrn #skinhead x")
    run(win, s, b, "/queryrn Dave_away #skinhead")
    t = [l.text for l in b.lines[-3:]]
    assert t == ["No private tab called Nobody.", "No private tab called #skinhead.", "There is already a tab called #skinhead."]
    win.close(); srv.stop()


def test_timer_with_the_name_glued_on(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    from bchat import timers
    from bchat.commands import run
    run(win, s, b, "/timer5 3 10 say Reminder")
    run(win, s, b, "/timernews 0 600 say Read the topic")
    assert set(timers._table(s)) == {"5", "news"}
    got = timers._table(s)["5"]
    assert (got.times, got.seconds, got.command) == (3, 10, "say Reminder")
    run(win, s, b, "/timer5")
    run(win, s, b, "/timer5 off")
    run(win, s, b, "/timer5 off")
    t = [l.text for l in b.lines]
    assert t[-5].startswith("Timer 5: 3 times") and t[-4].startswith("Timer news:")
    assert t[-3].startswith("Timer 5: ") and t[-2:] == ["Timer 5 stopped.", "No timer called 5."]
    assert set(timers._table(s)) == {"news"}
    run(win, s, b, "/timer 2 1 say once")        # the old way still means times + seconds, no name
    assert any(n not in ("news",) for n in timers._table(s))
    timers.stop_all(s)
    win.close(); srv.stop()


# --- Settings tree --------------------------------------------------------------------------------------------

def test_file_transfers_is_its_own_group(app, tmp_path):
    from bchat.preferences import CATEGORIES
    assert list(CATEGORIES) == ["Interface", "Chatting", "Network", "File transfers", "BChat"]
    assert CATEGORIES["Network"] == ["Network setup", "Flood", "Local"]
    win, _net = make_win(tmp_path, 9)
    d = PreferencesDialog(win, "File transfers")
    t = d.tree
    depth = lambda it: 0 if it.parent() is None else 1 + depth(it.parent())
    pages = [it for it in d._items.values()]
    assert {depth(it) for it in pages} == {1}                       # no page hangs a level deeper
    assert {t.visualItemRect(it).x() for it in pages} == {t.visualItemRect(pages[0]).x()}   # one line-up
    opts = d._items["File transfers"]
    assert opts.text(0) == "Options" and t.currentItem() is opts
    assert d.title.text() == "File transfers" and d.pages.currentWidget().isAncestorOf(d.dcc_auto)
    group = opts.parent()
    t.setCurrentItem(group)                                         # the group's own row opens no page
    assert d.pages.currentWidget().isAncestorOf(d.dcc_auto) and d.title.text() == "File transfers"
    t.setCurrentItem(d._items["Trusted people"])
    assert d.title.text() == "Trusted people" and d.pages.currentWidget().isAncestorOf(d.trust_list)
    d.show_page("Local")
    assert d.title.text() == "Local"
    d.reject(); d.deleteLater()
    win.close()
