"""0.2.0: highlight rules (mIRC's Highlight list), the multi-line input box, Favourite Channels,
and Now Playing's Add... window."""
import time

from fake_ircd import FakeIrcd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from bchat import favourites, highlights
from bchat.config import Config, NetworkConfig, Server
from bchat.highlights import rule
from bchat.mainwindow import MainWindow
from bchat.session import HILITE, MSG


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def live(app, tmp_path, autojoin="#skinhead", **cfg):
    srv = FakeIrcd()
    net = NetworkConfig("SkinIRC", [Server("127.0.0.1", srv.port, False)], autojoin=autojoin)
    win = MainWindow(Config(nick="Badaboom", nick2="b2", networks=[net], skip_network_list=True, welcome_done=True, **cfg), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers and s.buffers["#skinhead"].joined)
    win.select_buffer(s.buffers["#skinhead"])
    return srv, win, s, s.buffers["#skinhead"]


# --- highlight rules -----------------------------------------------------------------------

def test_xchat_lists_become_rules_once():
    cfg = Config(highlight="radio, skin*", hilite_always="Boss", hilite_no="Bot*")
    highlights.migrate(cfg)
    assert [(r["match"], r["on"]) for r in cfg.hl_rules] == [("radio", "message"), ("skin*", "message"), ("Boss", "nick")]
    assert cfg.highlight == cfg.hilite_always == "" and cfg.hilite_no == "Bot*"          # Never Highlight stays a list
    highlights.migrate(cfg)
    assert len(cfg.hl_rules) == 3


def test_settings_file_with_old_lists_loads_as_rules(tmp_path):
    import json
    from bchat import config
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "highlight": "kopitiam", "hilite_always": "Azimov"}))
    cfg = config.load(tmp_path)
    assert [r["match"] for r in cfg.hl_rules] == ["kopitiam", "Azimov"] and cfg.hl_on


def test_rules_match_like_mirc():
    cfg = Config(hl_rules=[rule(match="restart*", where="#skinhead, #opers", colour=4),
                           rule(match="kopitiam", colour=3, sound="none"),
                           rule(match="Azimov", on="nick", where="SkinIRC", colour=12)],
                 hilite_no="Oracle, *Serv")
    f = lambda text, sender="x", net="SkinIRC", target="#skinhead": highlights.find(cfg, "Belon", text, sender, net, target)
    assert f("restarting the bot")["colour"] == 4                       # wildcard, in a listed channel
    assert f("restarting the bot", target="#chat") is None             # not from these channels
    assert f("restart") ["colour"] == 4
    assert f("good kopitiam in KL?")["colour"] == 3
    assert f("kopitiams") is None                                       # whole words only, like mIRC
    assert f("hello", sender="Azimov")["colour"] == 12                  # match on nick
    assert f("hello", sender="Azimov", net="Other") is None             # only on SkinIRC
    assert f("Belon you there?") is highlights.OWN                      # your nick always
    assert f("Belon restart now", sender="Oracle") is None             # Never Highlight beats everything
    assert f("kopitiam", sender="NickServ") is None
    cfg.hl_on = False
    assert f("kopitiam") is None and f("Belon?") is highlights.OWN    # rules off, your nick still counts
    cfg.hl_on = True
    cfg.hl_rules.insert(0, rule(match="Belon", colour=13))
    assert f("Belon you there?")["colour"] == 13                        # first rule that matches wins


def test_a_rule_colours_the_line_and_picks_its_sound(app, tmp_path, monkeypatch):
    srv, win, s, b = live(app, tmp_path, hl_rules=[rule(match="kopitiam", colour=3, sound="C:/x/ding.wav"),
                                                   rule(match="quiet", sound="none")])
    played = []
    monkeypatch.setattr(win, "_play_sound", lambda kind, path="": played.append((kind, path)))
    srv.send(":Sahak!s@h PRIVMSG #skinhead :anyone know a good kopitiam in KL?")
    assert wait(app, lambda: any("kopitiam" in l.text for l in b.lines))
    ln = next(l for l in b.lines if "kopitiam" in l.text)
    assert ln.kind == HILITE and ln.colour == win.cfg.theme.palette[3]
    assert ("hilight", "C:/x/ding.wav") in played
    played.clear()
    srv.send(":Sahak!s@h PRIVMSG #skinhead :be quiet")
    assert wait(app, lambda: any(l.text == "be quiet" for l in b.lines))
    assert not any(k == "hilight" for k, _ in played)                       # silent rule
    srv.send(":Sahak!s@h PRIVMSG #skinhead :Badaboom hi")
    assert wait(app, lambda: any(l.text == "Badaboom hi" for l in b.lines))
    own = next(l for l in b.lines if l.text == "Badaboom hi")
    assert own.kind == HILITE and own.colour == ""                          # your nick: the theme's colour
    win.close(); srv.stop()


def test_highlights_page_add_edit_move_remove(app, tmp_path):
    from bchat.preferences import CATEGORIES, PreferencesDialog
    assert CATEGORIES["Chatting"][:2] == ["Alerts", "Highlights"]
    win = MainWindow(Config(nick="T", skip_network_list=True, welcome_done=True, highlight="radio"), tmp_path)
    win.skip_quit_prompt = True
    d = PreferencesDialog(win, "Highlights")
    assert d.hl_list.topLevelItemCount() == 2                                # radio + your nick (last, grey)
    assert d.hl_list.topLevelItem(1).text(0) == "T (your nick)"
    assert not (d.hl_list.topLevelItem(1).flags() & Qt.ItemFlag.ItemIsSelectable)
    d.hl_add.click()
    e = d.hl_dialog
    e.match.setText("restart*, reboot"); e.on.setCurrentIndex(2); e.where.setText("#opers")
    e.colour_buttons[1].click(); e.flash.setChecked(False)
    e.ok.click()
    assert d.hl_list.topLevelItemCount() == 3 and d.hl_rules[1]["match"] == "restart*, reboot"
    d.hl_up.click()
    assert d.hl_rules[0]["match"] == "restart*, reboot"
    d.hl_edit.click()
    d.hl_dialog.match.setText("restart*"); d.hl_dialog.ok.click()
    d.hl_list.setCurrentItem(d.hl_list.topLevelItem(1)); d.hl_remove.click()
    d.hl_no.setText("*Serv")
    d.accept()
    [r] = win.cfg.hl_rules
    assert (r["match"], r["on"], r["where"], r["colour"], r["flash"]) == ("restart*", "both", "#opers", 4, False)
    assert win.cfg.hilite_no == "*Serv"
    win.close()


# --- multi-line input ----------------------------------------------------------------------

def test_shift_enter_grows_the_box_and_enter_sends_every_line(app, tmp_path):
    srv, win, s, b = live(app, tmp_path)
    inp = win.input
    inp.setFocus(); inp.setText("ok here are the steps:")
    QTest.keyClick(inp, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert inp.is_multi() and not inp.isVisible()
    m = inp.multi
    QTest.keyClicks(m, "1. open Preferences")
    QTest.keyClick(m, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(m, "2. tick it")
    one_line = m.fontMetrics().lineSpacing()
    assert m.height() >= 3 * one_line and m.toPlainText().count("\n") == 2
    QTest.keyClick(m, Qt.Key.Key_Return)
    for line in ("ok here are the steps:", "1. open Preferences", "2. tick it"):
        assert wait(app, lambda line=line: f"PRIVMSG #skinhead :{line}" in srv.received), srv.received[-4:]
    assert inp.isVisible() and not inp.is_multi() and inp.text() == ""
    QTest.keyClick(inp, Qt.Key.Key_Up)                                       # history brings the lines back
    assert inp.is_multi() and inp.multi.toPlainText().count("\n") == 2
    win.close(); srv.stop()


def test_the_box_shrinks_back_and_caps_at_five_lines(app, tmp_path):
    srv, win, s, b = live(app, tmp_path)
    inp = win.input
    inp.setText("hello")
    QTest.keyClick(inp, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    m = inp.multi
    QTest.keyClick(m, Qt.Key.Key_Backspace)                                  # the new line goes: one line again
    assert wait(app, lambda: inp.isVisible()) and inp.text() == "hello" and not inp.is_multi()
    QTest.keyClick(inp, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    for i in range(8):
        QTest.keyClicks(m, f"line {i}")
        QTest.keyClick(m, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    cap = m.height()
    assert cap <= 5 * m.fontMetrics().lineSpacing() + 20
    win.close(); srv.stop()


def test_tab_and_bold_work_in_the_big_box(app, tmp_path):
    srv, win, s, b = live(app, tmp_path)
    srv.send(":Oracle!o@h JOIN #skinhead")
    assert wait(app, lambda: "oracle" in b.users)
    inp = win.input
    inp.setText("first")
    QTest.keyClick(inp, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    m = inp.multi
    QTest.keyClicks(m, "Ora")
    QTest.keyClick(m, Qt.Key.Key_Tab)
    assert m.toPlainText().endswith("\nOracle: ") or m.toPlainText().endswith("\nOracle" + win.cfg.nick_suffix + " ")
    QTest.keyClick(m, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    assert m.toPlainText().endswith("\x02")
    win.close(); srv.stop()


# --- favourite channels --------------------------------------------------------------------

def test_autojoin_text_round_trip_keeps_keys():
    pairs = favourites.parse_autojoin("#opers,#a,#b sekret")
    assert pairs == [("#opers", "sekret"), ("#a", ""), ("#b", "")]
    assert favourites.build_autojoin([("#a", ""), ("#opers", "sekret")]) == "#opers,#a sekret"
    assert favourites.build_autojoin([]) == ""


def test_favourites_keep_autojoin_as_the_source():
    cfg = Config(networks=[NetworkConfig("A", [Server("h", 1)], autojoin="#x,#y k"), NetworkConfig("B", [Server("h", 1)])],
                 fav_saved=["B/#help"], fav_notes={"A/#x": "home"})
    favs = favourites.entries(cfg)
    assert [(f.network, f.channel, f.key, f.join, f.note) for f in favs] == [
        ("A", "#x", "k", True, "home"), ("A", "#y", "", True, ""), ("B", "#help", "", False, "")]
    favs[2].join = True
    favs[0].join = False
    favourites.save(cfg, favs)
    assert cfg.networks[0].autojoin == "#y" and cfg.networks[1].autojoin == "#help"
    assert cfg.fav_saved == ["A/#x k"] and cfg.fav_notes == {"A/#x": "home"}


def test_tab_menu_join_on_connect(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, autojoin="#skinhead")
    menu = win._switcher_menu(b)
    auto = next(a for a in menu.actions() if a.text() == "Join on Connect")
    assert auto.isChecked()
    auto.trigger()
    assert win.cfg.networks[0].autojoin == "" and win.cfg.fav_saved == ["SkinIRC/#skinhead"]
    assert any("won't be joined on connect" in l.text for l in b.lines)
    auto = next(a for a in win._switcher_menu(b).actions() if a.text() == "Join on Connect")
    assert not auto.isChecked()
    auto.trigger()
    assert win.cfg.networks[0].autojoin == "#skinhead"
    assert any(a.text() == "Favourite Channels..." for a in menu.actions())
    win.close(); srv.stop()


def test_favourites_window_add_tick_join(app, tmp_path):
    srv, win, s, b = live(app, tmp_path)
    win.open_favourites()
    d = win.fav_dialog
    assert d.list.topLevelItemCount() == 1 and d.list.topLevelItem(0).text(0) == "#skinhead"
    d.add_btn.click()
    e = d.edit_dialog
    e.channel.setText("opers"); e.key.setText("sekret"); e.note.setText("staff"); e.join.setChecked(False)
    e.ok.click()
    assert d.list.topLevelItemCount() == 2
    row = d.list.topLevelItem(1)
    assert (row.text(0), row.text(2), row.text(4)) == ("#opers", "••••••", "staff")
    assert win.cfg.fav_saved == ["SkinIRC/#opers sekret"]
    row.setCheckState(3, Qt.CheckState.Checked)                              # tick: joins on connect now
    assert win.cfg.networks[0].autojoin == "#opers,#skinhead sekret"
    d.list.setCurrentItem(row)
    d.join_btn.click()
    assert wait(app, lambda: "JOIN #opers sekret" in srv.received or "JOIN #opers :sekret" in srv.received), srv.received[-3:]
    d.list.setCurrentItem(d.list.topLevelItem(1)); d.remove_btn.click()
    assert win.cfg.networks[0].autojoin == "#skinhead" and d.list.topLevelItemCount() == 1
    d.close(); win.close(); srv.stop()


# --- Now Playing: Add... -------------------------------------------------------------------

def test_now_playing_add_picks_network_and_channel(app, tmp_path):
    from bchat.preferences import PreferencesDialog
    srv, win, s, b = live(app, tmp_path, autojoin="#skinhead,#chat", np_enabled=True)
    win.cfg.networks.append(NetworkConfig("SavedOnly", [Server("irc.example.org", 6697, True)]))   # saved, not connected
    d = PreferencesDialog(win, "Now Playing")
    d.np_ann_add.click()
    a = d.np_add_dialog
    assert [a.net.itemText(i) for i in range(a.net.count())] == ["Every network", "SkinIRC"] and a.net.currentText() == "SkinIRC"
    assert [a.chan.itemText(i) for i in range(a.chan.count())][:2] == ["#skinhead", "#chat"]
    a.chan.setCurrentText("#chat")
    a.accept()
    rows = [(d.np_ann_list.topLevelItem(i).text(0), d.np_ann_list.topLevelItem(i).text(1)) for i in range(d.np_ann_list.topLevelItemCount())]
    assert rows == [("SkinIRC", "#chat")]
    d.accept()
    assert win.cfg.np_announce_in == "SkinIRC/#chat"
    win.close(); srv.stop()


def test_share_tick_means_this_network_only(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, np_enabled=True, np_announce=True, np_announce_in="#skinhead")
    menu = win._chat_menu(QPoint(1, 1), win.chat, b)
    share = next(a.menu() for a in menu.actions() if a.text() == "Share")
    ann = share.actions()[-1]
    assert not ann.isChecked() and "every network" in ann.toolTip()
    ann.trigger()                                                            # one click: just this network
    assert win.cfg.np_announce_in == "SkinIRC/#skinhead"
    win.close(); srv.stop()


# --- Network > Local and your modes on connect ------------------------------------------------

def test_your_modes_is_one_line_in_the_server_tab(app, tmp_path):
    srv, win, s, b = live(app, tmp_path)
    srv.send(":Badaboom MODE Badaboom :+iwxz")
    from bchat.protocol import strip_format
    assert wait(app, lambda: any(strip_format(l.text) == "Badaboom sets mode: [ +iwxz ]" for l in s.server_buffer.lines))
    line = next(l for l in s.server_buffer.lines if "sets mode:" in l.text)
    assert line.text.count("11[") == 1 and line.text.count("11]") == 1          # coloured brackets
    assert not any("Your modes" in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_server_lookup_uses_userip_and_prints_local_host(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, local_find=False)
    s.userip = True
    s.find_local()
    assert wait(app, lambda: "USERIP Badaboom" in srv.received)
    srv.send(":srv 340 Badaboom :Badaboom*=+bee@192.168.1.20")
    assert wait(app, lambda: s.external_ip == "192.168.1.20")
    assert wait(app, lambda: any(l.text.startswith("Local host: ") and l.text.endswith("(192.168.1.20)") for l in s.server_buffer.lines), 15000)
    assert win.dcc.my_address(s) == "192.168.1.20"
    win.close(); srv.stop()


def test_userhost_when_no_userip_and_the_line_can_be_hidden(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, local_find=False, local_show=False)
    s.find_local()
    assert wait(app, lambda: "USERHOST Badaboom" in srv.received)
    srv.send(":srv 302 Badaboom :Badaboom=+bee@127.0.0.1")
    assert wait(app, lambda: s.external_ip == "127.0.0.1")
    wait(app, lambda: False, 300)
    assert not any("Local host" in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_typed_ip_wins_and_normal_asks_this_pc(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, local_find=False, dcc_ip="203.0.113.9")
    s.find_local()
    assert wait(app, lambda: s.external_ip == "203.0.113.9")
    assert not any(x.startswith(("USERHOST", "USERIP")) for x in srv.received)
    win.cfg.dcc_ip = ""; win.cfg.local_lookup = "normal"; s.external_ip = ""
    s.find_local()
    assert wait(app, lambda: s.external_ip == "127.0.0.1")
    win.close(); srv.stop()


def test_website_lookup(app, tmp_path):
    import http.server, threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"203.0.113.5\n")
        def log_message(self, *a):
            pass
    web = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    srv, win, s, b = live(app, tmp_path, local_find=False, local_lookup="website",
                         local_site=f"http://127.0.0.1:{web.server_address[1]}/")
    s.find_local()
    assert wait(app, lambda: s.external_ip == "203.0.113.5", 8000)
    web.shutdown(); win.close(); srv.stop()


def test_local_page_moves_the_fields_and_warns_on_home_addresses(app, tmp_path):
    import json
    from bchat import config
    from bchat.preferences import CATEGORIES, PreferencesDialog, home_address
    assert CATEGORIES["Network"] == ["Network setup", "Flood", "Local", "File transfers"]
    assert home_address("192.168.1.20") and home_address("10.0.0.2") and home_address("100.70.1.1")
    assert not home_address("203.0.113.5".replace("203.0.113", "8.8.8")) and not home_address("")
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "dcc_ip_from_server": False}))
    assert config.load(tmp_path).local_lookup == "normal"                 # older settings keep their choice
    win = MainWindow(Config(nick="T", skip_network_list=True, welcome_done=True, dcc_ip="192.168.1.20"), tmp_path)
    win.skip_quit_prompt = True
    d = PreferencesDialog(win, "Local")
    assert d.pages.currentWidget().isAncestorOf(d.dcc_ip) and d.local_ways["server"].isChecked()
    assert not d.local_warn.isHidden() and "192.168.1.20" in d.local_warn.text()
    d.local_ways["website"].setChecked(True); d.local_site.setText("ifconfig.me"); d.local_show.setChecked(False)
    d.dcc_ip.setText("")
    d.accept()
    c = win.cfg
    assert (c.local_lookup, c.local_site, c.local_show, c.dcc_ip, c.dcc_ip_from_server) == ("website", "ifconfig.me", False, "", False)
    d = PreferencesDialog(win, "File transfers")
    assert not hasattr(d, "dcc_from_server")
    win.close()


# --- Network List: popular networks ------------------------------------------------------------

def test_popular_networks_list_is_checked_and_bajubesi_first():
    from bchat.popular import POPULAR
    assert POPULAR[0].name == "BajuBesi Community" and POPULAR[0].autojoin == "#BChat,#chat"
    assert all(p.tls in ("ok", "ask", "none") for p in POPULAR)
    assert all((p.port == 6697) == p.ssl for p in POPULAR)                    # no encryption -> plain 6667
    assert "freenode" not in {p.name.lower() for p in POPULAR}
    assert len({p.name for p in POPULAR}) == len(POPULAR)


def test_network_list_shows_popular_under_mine_and_connect_copies_once(app, tmp_path, monkeypatch):
    from bchat.networklist import NetworkListDialog
    win = MainWindow(Config(nick="T", networks=[NetworkConfig("Mine", [Server("irc.mine.org", 6697, True)]),
                                                NetworkConfig("MyLibera", [Server("irc.libera.chat", 6697, True)])],
                            skip_network_list=True, welcome_done=True), tmp_path)
    win.skip_quit_prompt = True
    connected = []
    monkeypatch.setattr(win, "connect_network", lambda n: connected.append(n))    # never the real networks
    d = NetworkListDialog(win)
    d.show()
    groups = [d.list.topLevelItem(i).text(0) for i in range(d.list.topLevelItemCount())]
    assert groups == ["Popular Networks", "My Networks"]          # no favourite yet: no empty group
    assert d.list.count() == 2 and d.list.item(0).text() == "Mine"            # rows still count only yours
    pop = d.list.group("popular")
    first = pop.child(0)
    assert first.text(0) == "BajuBesi Community" and "irc.bajubesi.org:6697" in first.toolTip(0)
    d.list.setCurrentItem(first)
    assert not d.btn["Remove"].isEnabled() and not d.btn["Edit..."].isEnabled()  # yours only
    d._connect()
    n = win.cfg.networks[-1]
    assert connected == [n] and (n.name, n.servers[0].host, n.servers[0].port, n.servers[0].ssl, n.autojoin) == (
        "BajuBesi Community", "irc.bajubesi.org", 6697, True, "#BChat,#chat")
    d = NetworkListDialog(win); d.show()
    pop = d.list.group("popular")
    libera = next(pop.child(i) for i in range(pop.childCount()) if pop.child(i).text(0) == "Libera.Chat")
    assert "in My Networks as MyLibera" in libera.toolTip(0)
    d.list.setCurrentItem(libera)
    d._connect()
    assert connected[-1].name == "MyLibera" and len(win.cfg.networks) == 3     # your own copy, not a second one
    d = NetworkListDialog(win); d.show()
    assert not hasattr(d, "fav")                                              # "Show favorites only" is gone (zen)
    d.list.group("popular").setExpanded(False)
    assert win.cfg.netlist_open == {"popular": False}
    d.reject()
    d = NetworkListDialog(win)
    assert not d.list.group("popular").isExpanded()                            # folding is remembered
    d.reject(); win.close()


def test_network_list_favourites_get_their_own_group_on_top(app, tmp_path, monkeypatch):
    from bchat.networklist import NetworkListDialog
    nets = [NetworkConfig(n, [Server("irc.%s.org" % n.lower(), 6697, True)]) for n in ("Alpha", "Beta", "Gamma")]
    win = MainWindow(Config(nick="T", networks=nets, skip_network_list=True, welcome_done=True), tmp_path)
    win.skip_quit_prompt = True
    monkeypatch.setattr(win, "connect_network", lambda n: None)
    d = NetworkListDialog(win); d.show()
    names = lambda key: [d.list.group(key).child(i).text(0) for i in range(d.list.group(key).childCount())] if d.list.group(key) else None
    tops = lambda: [d.list.topLevelItem(i).text(0) for i in range(d.list.topLevelItemCount())]
    assert d.list.group("fav") is None
    d.list.setCurrentRow(2); d._favor()                                          # Gamma moves up
    assert tops() == ["Favourite Networks", "Popular Networks", "My Networks"]
    assert names("fav") == ["Gamma"] and names("mine") == ["Alpha", "Beta"]      # listed once, not twice
    assert d._current() is nets[2]                                              # still selected after the move
    assert [d.list.item(i).text() for i in range(d.list.count())] == ["Alpha", "Beta", "Gamma"]   # rows = cfg.networks
    d.list.setCurrentRow(2); d._favor()                                          # and back down; empty group goes away
    assert d.list.group("fav") is None and names("mine") == ["Alpha", "Beta", "Gamma"]
    d.reject(); win.close()
