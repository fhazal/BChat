"""0.9.3: the built-in Oper tools add-on (mockup-oper-tools.png): the Oper menu and the nick's Oper submenu show only
while the server says you're an IRC operator; the ban command differs per server software; server notices get a tab."""
import pytest
from PySide6.QtWidgets import QCheckBox

import bchat.oper as oper
from bchat.config import Config
from bchat.oper import (BanDialog, KillDialog, MessageDialog, OperSettings, ServerBansWindow, ban_line, ban_types,
                        clones_of, global_line, ircd_family, kill_line, list_lines, mask_choices, mask_matches,
                        matching, opers_line, parse_ban, remove_line, wallops_line)
from test_live import live_with, wait

ME = "Badaboom"
VERSIONS = {
    "solanum": "solanum-1.0-dev", "charybdis": "charybdis-4.1.2", "ratbox": "ircd-ratbox-3.0.10",
    "hybrid": "hybrid-8.2.44", "inspircd": "InspIRCd-4.5.0", "unreal": "UnrealIRCd-6.1.7", "beeircd": "beeircd-0.4",
    "unknown": "ircu2.10.12",
}


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(oper, "REMEMBER", 12)


def connected(app, tmp_path, version=None):
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected" and "#skinhead" in s.buffers)
    if version:
        srv.send(f":srv 004 {ME} srv {version} iowghraAsORTVSxNCWqBzvdHtGp bcdefFhiklmnopqrstvzMSX")
        assert wait(app, lambda: s.ircd_version == version)
    return srv, win, s


def make_oper(app, srv, s):
    srv.send(f":srv 381 {ME} :You are now an IRC operator")
    assert wait(app, lambda: s.is_oper)


def done(srv, win):
    win.close()
    srv.stop()


def sent(srv, prefix):
    return [x for x in srv.received if x.startswith(prefix)]


def menu_shown(win):
    return win.oper_menu.menuAction().isVisible()


def texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def join_people(app, srv, s):
    b = s.buffers["#skinhead"]
    for nick, host in (("zed", "~z@203.0.113.7"), ("ana", "a@203.0.113.7"), ("bob", "b@192.0.2.9"), ("opr", "o@203.0.113.7")):
        srv.send(f":{nick}!{host} JOIN #skinhead")
    assert wait(app, lambda: all(n in b.users for n in ("zed", "ana", "bob", "opr")))
    b.users["opr"].oper = True
    return b


# --- the words (no network) --------------------------------------------------------------------------

def test_config_defaults():
    c = Config()
    assert c.addon_oper is True and c.oper_notices is True
    assert c.oper_for == "1 day" and c.oper_reasons[0] == "Spam"


@pytest.mark.parametrize("name,want", [
    ("solanum", "charybdis"), ("charybdis", "charybdis"), ("ratbox", "charybdis"), ("hybrid", "charybdis"),
    ("inspircd", "inspircd"), ("unreal", "unreal"), ("beeircd", "beeircd"), ("unknown", "unknown")])
def test_ircd_family_from_the_version_reply(name, want):
    assert ircd_family(VERSIONS[name]) == want
    assert ircd_family("") == "unknown"


def test_ban_types_per_family():
    assert ban_types("charybdis") == ("KLINE", "DLINE")
    assert ban_types("inspircd") == ("GLINE", "ZLINE", "SHUN", "KLINE")
    assert ban_types("unreal") == ("GLINE", "ZLINE", "SHUN", "KLINE")
    assert ban_types("beeircd") == ("GLINE", "ZLINE", "SHUN", "KLINE")
    assert ban_types("unknown") == ("KLINE",)


def test_the_ban_line_per_server_software():
    why = "Spam"
    # Solanum / charybdis family: minutes, none = forever
    assert ban_line("charybdis", "KLINE", "*@203.0.113.7", 1440, why) == "KLINE 1440 *@203.0.113.7 :Spam"
    assert ban_line("charybdis", "KLINE", "*@203.0.113.7", 0, why) == "KLINE *@203.0.113.7 :Spam"
    assert ban_line("charybdis", "DLINE", "203.0.113.7", 60, why) == "DLINE 60 203.0.113.7 :Spam"
    # InspIRCd
    assert ban_line("inspircd", "GLINE", "*@203.0.113.7", 1440, why) == "GLINE *@203.0.113.7 1d :Spam"
    assert ban_line("inspircd", "ZLINE", "203.0.113.7", 10080, why) == "ZLINE 203.0.113.7 7d :Spam"
    assert ban_line("inspircd", "SHUN", "*@203.0.113.7", 60, why) == "SHUN *@203.0.113.7 1h :Spam"
    assert ban_line("inspircd", "KLINE", "*@203.0.113.7", 43200, why) == "KLINE *@203.0.113.7 30d :Spam"
    assert ban_line("inspircd", "GLINE", "*@203.0.113.7", 0, why) == "GLINE *@203.0.113.7 0 :Spam"
    # UnrealIRCd: the mask gets a + in front
    assert ban_line("unreal", "GLINE", "*@203.0.113.7", 1440, why) == "GLINE +*@203.0.113.7 1d :Spam"
    assert ban_line("unreal", "ZLINE", "*@203.0.113.7", 0, why) == "ZLINE +*@203.0.113.7 0 :Spam"
    # BeeIRCd: GLINE / ZLINE / SHUN like Unreal's habit; KLINE with +time
    assert ban_line("beeircd", "GLINE", "*@203.0.113.7", 1440, why) == "GLINE *@203.0.113.7 1d :Spam"
    assert ban_line("beeircd", "SHUN", "*@203.0.113.7", 0, why) == "SHUN *@203.0.113.7 0 :Spam"
    assert ban_line("beeircd", "KLINE", "*@203.0.113.7", 10080, why) == "KLINE +7d *@203.0.113.7 :Spam"
    assert ban_line("beeircd", "KLINE", "*@203.0.113.7", 0, why) == "KLINE *@203.0.113.7 :Spam"
    # anything else: KLINE the charybdis way
    assert ban_line("unknown", "KLINE", "*@203.0.113.7", 60, why) == "KLINE 60 *@203.0.113.7 :Spam"


def test_the_reason_is_tidied_and_never_empty():
    assert ban_line("charybdis", "KLINE", "*@h", 0, "  two   words ") == "KLINE *@h :two words"
    assert ban_line("charybdis", "KLINE", "*@h", 0, "") == "KLINE *@h :Banned"
    assert kill_line("zed", "") == "KILL zed :Banned"
    assert kill_line("zed", "Flooding") == "KILL zed :Flooding"


def test_the_remove_line_per_server_software():
    assert remove_line("charybdis", "KLINE", "*@h") == "UNKLINE *@h"
    assert remove_line("charybdis", "DLINE", "203.0.113.7") == "UNDLINE 203.0.113.7"
    assert remove_line("inspircd", "GLINE", "*@h") == "GLINE *@h"
    assert remove_line("inspircd", "ZLINE", "203.0.113.7") == "ZLINE 203.0.113.7"
    assert remove_line("inspircd", "DLINE", "203.0.113.7") == "ZLINE 203.0.113.7"   # InspIRCd has no DLINE
    assert remove_line("unreal", "GLINE", "*@h") == "GLINE -*@h"
    assert remove_line("unreal", "SHUN", "*@h") == "SHUN -*@h"
    assert remove_line("beeircd", "GLINE", "*@h") == "GLINE -*@h"
    assert remove_line("beeircd", "KLINE", "*@h") == "UNKLINE *@h"
    assert remove_line("unknown", "KLINE", "*@h") == "UNKLINE *@h"


def test_the_list_lines_and_the_other_oper_lines():
    assert list_lines("charybdis") == ["STATS K", "STATS D"]
    assert list_lines("inspircd") == ["STATS G", "STATS Z", "STATS K", "STATS H"]
    assert list_lines("beeircd") == ["STATS k"]
    assert list_lines("unknown") == ["STATS K"]
    assert wallops_line("hello all") == "WALLOPS :hello all"
    assert global_line("charybdis", "Restart soon") == "NOTICE $$* :Restart soon"
    assert global_line("inspircd", "Restart soon") == "NOTICE $* :Restart soon"
    assert global_line("unknown", "Restart soon") == "NOTICE $* :Restart soon"
    assert opers_line("charybdis") == "STATS p" and opers_line("inspircd") == "STATS P"
    assert opers_line("unreal") == "WHO 0 o" and opers_line("unknown") == "WHO 0 o"


def test_mask_choices_from_the_persons_address():
    assert mask_choices("~z@203.0.113.7", "GLINE") == ["*@203.0.113.7", "*@203.0.113.*", "~z@203.0.113.7"]
    assert mask_choices("~z@host.example.net", "KLINE") == ["*@host.example.net", "*@*.example.net", "~z@host.example.net"]
    assert mask_choices("z@example.net", "KLINE") == ["*@example.net", "z@example.net"]
    assert mask_choices("z@2001:db8::1", "GLINE") == ["*@2001:db8::1", "z@2001:db8::1"]
    assert mask_choices("~z@203.0.113.7", "DLINE") == ["203.0.113.7"]
    assert mask_choices("~z@host.example.net", "ZLINE") == []          # not an address: the box stays empty to type in
    assert mask_choices("", "KLINE") == []


def test_masks_must_fit_the_ban_type():
    assert oper.mask_ok("KLINE", "*@1.2.3.4") and not oper.mask_ok("KLINE", "1.2.3.4") and not oper.mask_ok("KLINE", "")
    assert not oper.mask_ok("GLINE", "bad mask@x") and not oper.mask_ok("GLINE", "@x")
    assert oper.mask_ok("DLINE", "1.2.3.4") and oper.mask_ok("ZLINE", "10.0.0.0/8") and not oper.mask_ok("DLINE", "*@1.2.3.4")


def test_which_addresses_a_mask_catches():
    assert mask_matches("*@203.0.113.7", "~z@203.0.113.7")
    assert mask_matches("*@203.0.113.*", "a@203.0.113.9")
    assert mask_matches("*@*.example.net", "a@x.example.net")
    assert not mask_matches("*@203.0.113.7", "a@192.0.2.9")
    assert mask_matches("203.0.113.7", "a@203.0.113.7") and mask_matches("203.0.113.0/24", "a@203.0.113.50")
    assert not mask_matches("203.0.113.0/24", "a@192.0.2.9")
    assert not mask_matches("*@h", "nohost")


def test_parse_ban_from_stats_answers():
    # solanum / charybdis 216:  K host * user :reason     225:  D ip * :reason
    assert parse_ban(216, [ME, "K", "bad.host", "*", "baduser", "Spam"]) == ("KLINE", "baduser@bad.host", "Spam")
    assert parse_ban(225, [ME, "D", "203.0.113.9", "*", "Flood"]) == ("DLINE", "203.0.113.9", "Flood")
    # others: mask first, reason last
    assert parse_ban(223, [ME, "G", "*@203.0.113.9", "setter", "Spam"]) == ("GLINE", "*@203.0.113.9", "Spam")
    assert parse_ban(223, [ME, "H", "*@203.0.113.9", "x"])[0] == "SHUN"
    assert parse_ban(216, [ME]) is None and parse_ban(216, [ME, "1", "x"]) is None


# --- is_oper (live, with the fake server) ------------------------------------------------------------

def test_oper_on_381_and_off_on_minus_o(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    assert s.is_oper is False
    make_oper(app, srv, s)
    srv.send(f":{ME} MODE {ME} :-o")
    assert wait(app, lambda: not s.is_oper)
    srv.send(f":{ME} MODE {ME} :+o")
    assert wait(app, lambda: s.is_oper)
    srv.send(f":{ME} MODE {ME} :-o")
    assert wait(app, lambda: not s.is_oper)
    done(srv, win)


def test_oper_from_the_user_modes_reply_and_other_modes_leave_it_alone(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    srv.send(f":srv 221 {ME} +iow")
    assert wait(app, lambda: s.is_oper)
    srv.send(f":{ME} MODE {ME} :+i")
    srv.send(f":{ME} MODE {ME} :-i")
    srv.send(f":zed MODE #skinhead +o {ME}")                  # +o on a channel is not oper
    assert not wait(app, lambda: not s.is_oper, 400)
    srv.send(f":srv 221 {ME} +iw")
    assert wait(app, lambda: not s.is_oper)
    done(srv, win)


def test_channel_ops_are_not_oper(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    srv.send(f":zed MODE #skinhead +o {ME}")
    assert not wait(app, lambda: s.is_oper, 400)
    done(srv, win)


def test_oper_off_when_the_link_drops_and_stays_off_on_a_new_connection(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    got = []
    s.oper_changed.connect(lambda: got.append(s.is_oper))
    srv.drop()
    assert wait(app, lambda: s.state != "connected")
    assert wait(app, lambda: not s.is_oper)
    assert got and got[-1] is False
    assert s.is_oper is False                                  # and a fresh login has to say it again (381)
    done(srv, win)


def test_oper_changed_fires_once_per_change(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    got = []
    s.oper_changed.connect(lambda: got.append(s.is_oper))
    make_oper(app, srv, s)
    srv.send(f":{ME} MODE {ME} :+o")                           # already oper: no second signal
    srv.send(f":{ME} MODE {ME} :-o")
    assert wait(app, lambda: not s.is_oper)
    assert got == [True, False]
    done(srv, win)


def test_you_are_oper_line_in_the_server_tab(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    line = [l.text for l in s.server_buffer.lines if "you're an IRC operator" in l.text]
    assert line and "SkinIRC" in line[0] and "server notices go to their own tab" in line[0]
    done(srv, win)


def test_ircd_version_from_004_and_351(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["solanum"])
    assert oper.family_of(s) == "charybdis"
    done(srv, win)
    srv, win, s = connected(app, tmp_path)
    assert oper.family_of(s) == "unknown"
    done(srv, win)


# --- the menus ---------------------------------------------------------------------------------------

def test_oper_menu_shows_only_while_oper_and_the_add_on_is_on(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    win.select_buffer(s.server_buffer)
    assert not menu_shown(win)
    make_oper(app, srv, s)
    assert menu_shown(win)
    win.cfg.addon_oper = False
    win.addons_changed()
    assert not menu_shown(win)
    win.cfg.addon_oper = True
    win.addons_changed()
    assert menu_shown(win)
    srv.send(f":{ME} MODE {ME} :-o")
    assert wait(app, lambda: not menu_shown(win))
    done(srv, win)


def test_oper_menu_follows_the_network_of_the_tab(app, tmp_path):
    from bchat.config import NetworkConfig, Server
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    win.select_buffer(s.server_buffer)
    assert menu_shown(win)
    other = win.session_for(NetworkConfig("Other", [Server("127.0.0.1", 1, False)]))
    win.select_buffer(other.server_buffer)
    assert not menu_shown(win)                                 # you're an oper on SkinIRC, not on Other
    win.select_buffer(s.server_buffer)
    assert menu_shown(win)
    done(srv, win)


def test_oper_menu_items_and_order(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    labels = []
    for a in win.oper_menu.actions():
        labels.append("-" if a.isSeparator() else a.text())
    assert labels == ["Kill...", "Ban from server...", "Server bans...", "-", "Wallops...", "Global notice...", "-",
                      "Server info", "Rehash server", "-", "Show server notices tab", "Stop being oper"]
    info = [a for a in win.oper_menu.actions() if a.text() == "Server info"][0].menu()
    assert texts(info) == ["Uptime", "Opers online", "Links", "Who is on (count)"]
    notices = [a for a in win.oper_menu.actions() if a.text() == "Show server notices tab"][0]
    assert notices.isCheckable() and notices.isChecked()
    names = [a.text() for a in win.menubar_.actions()]
    assert names.index("&Oper") == names.index("&Server") + 1
    done(srv, win)


def test_oper_menu_actions_send_the_real_commands(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["solanum"])
    make_oper(app, srv, s)
    win.select_buffer(s.server_buffer)
    by = {a.text(): a for a in win.oper_menu.actions() if not a.isSeparator()}
    by["Rehash server"].trigger()
    by["Stop being oper"].trigger()
    info = {a.text(): a for a in by["Server info"].menu().actions()}
    for name in ("Uptime", "Opers online", "Links", "Who is on (count)"):
        info[name].trigger()
    assert wait(app, lambda: "LUSERS" in srv.received)
    for line in ("REHASH", f"MODE {ME} -o", "STATS u", "STATS p", "LINKS", "LUSERS"):
        assert line in srv.received, line
    done(srv, win)


def test_menu_actions_do_nothing_when_not_oper(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    win.select_buffer(s.server_buffer)
    win._oper("rehash")
    win._oper("stop")
    assert not wait(app, lambda: "REHASH" in srv.received, 300)
    done(srv, win)


def test_nick_menu_has_the_oper_submenu_only_for_one_person_while_oper(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    b = join_people(app, srv, s)
    zed, ana = b.users["zed"], b.users["ana"]
    assert "Oper" not in texts(win.build_nick_menu(b, [zed]))
    make_oper(app, srv, s)
    menu = win.build_nick_menu(b, [zed])
    sub = [a for a in menu.actions() if a.text() == "Oper"][0].menu()
    assert texts(sub) == ["Whois (all info)", "Kill...", "Ban from server...", "Find clones"]
    assert "Oper" not in texts(win.build_nick_menu(b, [zed, ana]))
    win.cfg.addon_oper = False
    assert "Oper" not in texts(win.build_nick_menu(b, [zed]))
    done(srv, win)


def test_nick_menu_whois_all_info_and_find_clones(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    b = join_people(app, srv, s)
    make_oper(app, srv, s)
    win.select_buffer(b)
    sub = [a for a in win.build_nick_menu(b, [b.users["zed"]]).actions() if a.text() == "Oper"][0].menu()
    acts = {a.text(): a for a in sub.actions()}
    acts["Whois (all info)"].trigger()
    assert wait(app, lambda: "WHOIS zed zed" in srv.received)
    acts["Find clones"].trigger()
    text = [l.text for l in b.lines if "Find clones" in l.text]
    assert text and "203.0.113.7" in text[0] and "ana" in text[0] and "opr" in text[0] and "bob" not in text[0]
    done(srv, win)


def test_clones_of_a_person_nobody_else_shares_and_an_unknown_address(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    join_people(app, srv, s)
    assert clones_of(s, "bob") == ("192.0.2.9", [])
    assert clones_of(s, "nobody") == ("", [])
    host, others = clones_of(s, "zed")
    assert host == "203.0.113.7" and sorted(others) == ["ana", "opr"]
    done(srv, win)


# --- the dialogs -------------------------------------------------------------------------------------

def test_kill_dialog_shows_and_sends_the_exact_command(app, tmp_path, quick):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    d = KillDialog(win, s, "zed", "~z@203.0.113.7")
    assert d.sends.text() == "KILL zed :Spam" and d.go.isEnabled()
    d.reason.setEditText("Flooding the lobby")
    assert d.sends.text() == "KILL zed :Flooding the lobby"
    d.go.click()
    assert wait(app, lambda: "KILL zed :Flooding the lobby" in srv.received)
    assert win.cfg.oper_reasons[0] == "Flooding the lobby"
    done(srv, win)


def test_kill_dialog_from_the_menu_asks_for_a_nick(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    d = KillDialog(win, s)
    assert d.sends.text() == "" and not d.go.isEnabled()
    d.who.setText("zed")
    assert d.sends.text() == "KILL zed :Spam" and d.go.isEnabled()
    d.who.setText("two words")
    assert not d.go.isEnabled()
    done(srv, win)


@pytest.mark.parametrize("name,line", [
    ("solanum", "KLINE 1440 *@203.0.113.7 :Spam"),
    ("inspircd", "GLINE *@203.0.113.7 1d :Spam"),
    ("unreal", "GLINE +*@203.0.113.7 1d :Spam"),
    ("beeircd", "GLINE *@203.0.113.7 1d :Spam"),
    ("unknown", "KLINE 1440 *@203.0.113.7 :Spam"),
])
def test_ban_dialog_sends_what_the_server_software_wants(app, tmp_path, name, line):
    srv, win, s = connected(app, tmp_path, VERSIONS[name])
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@203.0.113.7")
    assert d.mask_box.currentText() == "*@203.0.113.7"
    assert d.length.currentText() == "1 day"
    assert d.sends.text() == line
    assert d.family == oper.ircd_family(VERSIONS[name])
    d.go.click()
    assert wait(app, lambda: line in srv.received), srv.received
    done(srv, win)


def test_ban_dialog_types_and_durations(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["inspircd"])
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@203.0.113.7")
    assert [d.kind.itemData(i) for i in range(d.kind.count())] == ["GLINE", "ZLINE", "SHUN", "KLINE"]
    d.kind.setCurrentIndex(1)                                  # ZLINE takes an address, not user@host
    assert d.mask_box.currentText() == "203.0.113.7" and d.sends.text() == "ZLINE 203.0.113.7 1d :Spam"
    d.kind.setCurrentIndex(2)
    assert d.sends.text() == "SHUN *@203.0.113.7 1d :Spam"
    assert [d.length.itemText(i) for i in range(d.length.count())] == ["1 hour", "1 day", "7 days", "30 days", "Forever"]
    d.length.setCurrentIndex(4)
    assert d.sends.text() == "SHUN *@203.0.113.7 0 :Spam"
    d.length.setCurrentIndex(0)
    assert d.sends.text() == "SHUN *@203.0.113.7 1h :Spam"
    done(srv, win)


def test_ban_dialog_wildcard_masks_and_an_empty_ip_box(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["solanum"])
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@host.example.net")
    assert [d.mask_box.itemText(i) for i in range(d.mask_box.count())] == ["*@host.example.net", "*@*.example.net", "~z@host.example.net"]
    d.kind.setCurrentIndex(1)                                  # DLINE: not an address, so the box is empty and Ban is off
    assert d.mask_box.currentText() == "" and not d.go.isEnabled() and d.sends.text() == ""
    d.mask_box.setEditText("203.0.113.7")
    assert d.go.isEnabled() and d.sends.text() == "DLINE 1440 203.0.113.7 :Spam"
    d.mask_box.setEditText("bad mask")
    assert not d.go.isEnabled()
    done(srv, win)


def test_ban_dialog_unknown_server_has_no_type_choice(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@203.0.113.7")
    assert d.kind.count() == 1 and d.family == "unknown"
    done(srv, win)


def test_ban_dialog_also_disconnects_the_people_who_match(app, tmp_path, quick):
    srv, win, s = connected(app, tmp_path, VERSIONS["inspircd"])
    join_people(app, srv, s)
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@203.0.113.7")
    # zed, ana and opr are on 203.0.113.7; opr is an IRC operator, and zed is the one being banned (he matches too)
    assert sorted(d.victims()) == ["ana", "zed"]
    assert d.also.isVisibleTo(d) and d.also.isChecked()
    assert d.also.text() == "Also disconnect the 2 people who match now"
    d.reason.setEditText("Spam")
    d.go.click()
    assert wait(app, lambda: "KILL zed :Spam" in srv.received and "KILL ana :Spam" in srv.received)
    assert "GLINE *@203.0.113.7 1d :Spam" in srv.received
    assert not sent(srv, "KILL opr") and not sent(srv, "KILL bob") and not sent(srv, f"KILL {ME}")
    assert srv.received.index("GLINE *@203.0.113.7 1d :Spam") < srv.received.index("KILL zed :Spam")
    done(srv, win)


def test_ban_dialog_unticked_checkbox_only_bans_and_no_match_hides_it(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["inspircd"])
    join_people(app, srv, s)
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@203.0.113.7")
    d.also.setChecked(False)
    d.go.click()
    assert wait(app, lambda: "GLINE *@203.0.113.7 1d :Spam" in srv.received)
    assert not wait(app, lambda: bool(sent(srv, "KILL")), 300)
    d2 = BanDialog(win, s, "", "")
    d2.mask_box.setEditText("*@198.51.100.99")
    assert d2.victims() == [] and not d2.also.isVisibleTo(d2)
    d3 = BanDialog(win, s, "", "")
    d3.mask_box.setEditText("*@192.0.2.9")
    assert d3.victims() == ["bob"] and d3.also.text() == "Also disconnect the 1 person who matches now"
    done(srv, win)


def test_ban_dialog_remembers_the_time_and_the_reason(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["inspircd"])
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@203.0.113.7")
    d.length.setCurrentIndex(2)
    d.reason.setEditText("Clones")
    d.go.click()
    assert win.cfg.oper_for == "7 days"
    assert win.cfg.oper_reasons[:2] == ["Clones", "Spam"] and win.cfg.oper_reasons.count("Clones") == 1
    d = BanDialog(win, s, "zed", "~z@203.0.113.7")             # next time: 7 days, and Clones on top
    assert d.length.currentText() == "7 days" and d.reason.currentText() == "Clones"
    for i in range(20):
        oper.remember(win, f"r{i}")
    assert len(win.cfg.oper_reasons) == 12 and win.cfg.oper_reasons[0] == "r19"
    done(srv, win)


def test_wallops_and_global_notice_dialogs(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["solanum"])
    make_oper(app, srv, s)
    d = MessageDialog(win, s, "wallops")
    assert not d.go.isEnabled() and d.sends.text() == ""
    d.text.setText("Netsplit  coming")
    assert d.sends.text() == "WALLOPS :Netsplit coming" and d.go.isEnabled()
    d.go.click()
    d = MessageDialog(win, s, "global")
    d.text.setText("Restart at noon")
    assert d.sends.text() == "NOTICE $$* :Restart at noon"
    d.go.click()
    assert wait(app, lambda: "NOTICE $$* :Restart at noon" in srv.received)
    assert "WALLOPS :Netsplit coming" in srv.received
    done(srv, win)


def test_dialogs_send_nothing_when_cancelled(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    d = KillDialog(win, s, "zed", "~z@203.0.113.7")
    d.reject()
    assert not wait(app, lambda: bool(sent(srv, "KILL")), 300)
    done(srv, win)


# --- Server bans -------------------------------------------------------------------------------------

def test_server_bans_lists_adds_and_removes(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["solanum"])
    make_oper(app, srv, s)
    w = oper.open_server_bans(win, s)
    assert isinstance(w, ServerBansWindow) and win.tools["serverbans"] is w
    assert wait(app, lambda: "STATS D" in srv.received and "STATS K" in srv.received)
    assert s.oper_sink is not None
    srv.send(f":srv 216 {ME} K bad.host * baduser :Spam")
    srv.send(f":srv 225 {ME} D 203.0.113.9 * :Flood")
    srv.send(f":srv 219 {ME} K :End of /STATS report")
    assert wait(app, lambda: w.view.topLevelItemCount() == 2)
    assert s.oper_sink is not None                             # one end-of-list still to come
    srv.send(f":srv 219 {ME} D :End of /STATS report")
    assert wait(app, lambda: s.oper_sink is None)
    rows = [[w.view.topLevelItem(i).text(c) for c in range(3)] for i in range(2)]
    assert ["KLINE", "baduser@bad.host", "Spam"] in rows and ["DLINE", "203.0.113.9", "Flood"] in rows
    w.view.setCurrentItem(w.view.topLevelItem(0))
    assert w.sends.text() == f"Remove sends:  {remove_line('charybdis', rows[0][0], rows[0][1])}"
    w.remove()
    assert wait(app, lambda: any(x.startswith("UN") and "LINE" in x for x in srv.received))
    assert w.view.topLevelItemCount() == 2 and not w.remove_btn.isEnabled()   # QA 0.9.3: kept until the server says
    assert wait(app, lambda: srv.received.count("STATS K") >= 2, ms=5000)  # the list reloads to show what really went
    done(srv, win)


def test_server_bans_stats_numerics_are_not_swallowed_when_nobody_asked(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    assert s.oper_sink is None
    srv.send(f":srv 216 {ME} K bad.host * baduser :Spam")
    assert wait(app, lambda: any("bad.host" in l.text for b in s.all_buffers() for l in b.lines))
    done(srv, win)


def test_server_bans_window_hides_when_you_stop_being_oper(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    win.select_buffer(s.server_buffer)
    w = oper.open_server_bans(win, s)
    assert w.isVisible()
    srv.send(f":{ME} MODE {ME} :-o")
    assert wait(app, lambda: not w.isVisible())
    assert s.oper_sink is None
    done(srv, win)


def test_server_bans_beeircd_shows_the_services_note(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    w = oper.open_server_bans(win, s)
    assert "kept by services" in w.note.text() and w.note.isVisibleTo(w)
    assert wait(app, lambda: "STATS k" in srv.received)
    done(srv, win)


# --- server notices ----------------------------------------------------------------------------------

NOTE = f":irc.skinirc.net NOTICE {ME} :*** Notice -- Client connecting: ana (a@198.51.100.4) [ana]"


def notices_tab(s):
    return s.buffers.get("(notices)")


def test_server_notices_go_to_their_own_tab_while_oper(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    srv.send(NOTE)                                              # not an oper yet: the server tab, as before
    assert wait(app, lambda: any("Client connecting" in l.text for l in s.server_buffer.lines))
    assert notices_tab(s) is None
    make_oper(app, srv, s)
    assert notices_tab(s) is not None                           # the tab appears with the Oper tools
    srv.send(NOTE.replace("ana", "bob"))
    assert wait(app, lambda: notices_tab(s) is not None and any("bob" in l.text for l in notices_tab(s).lines))
    assert not any("bob" in l.text for l in s.server_buffer.lines)
    done(srv, win)


def test_server_notices_stay_in_the_server_tab_when_you_turn_the_tab_off(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    win.cfg.oper_notices = False
    make_oper(app, srv, s)
    assert notices_tab(s) is None
    srv.send(NOTE)
    assert wait(app, lambda: any("Client connecting" in l.text for l in s.server_buffer.lines))
    assert notices_tab(s) is None
    done(srv, win)


def test_server_notices_when_the_add_on_is_off_stay_in_the_server_tab(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    win.cfg.addon_oper = False
    make_oper(app, srv, s)
    srv.send(NOTE)
    assert wait(app, lambda: any("Client connecting" in l.text for l in s.server_buffer.lines))
    assert notices_tab(s) is None
    done(srv, win)


def test_server_notices_tick_in_the_menu_turns_the_tab_on_and_off(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    act = win.oper_notices_act
    act.setChecked(False)
    assert win.cfg.oper_notices is False
    srv.send(NOTE)
    assert wait(app, lambda: any("Client connecting" in l.text for l in s.server_buffer.lines))
    assert not any("Client connecting" in l.text for l in notices_tab(s).lines) if notices_tab(s) else True
    act.setChecked(True)
    assert win.cfg.oper_notices is True and notices_tab(s) is not None
    srv.send(NOTE.replace("ana", "cy"))
    assert wait(app, lambda: any("cy" in l.text for l in notices_tab(s).lines))
    done(srv, win)


def test_real_nick_notices_are_not_server_notices(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    srv.send(f":zed!z@evil.net NOTICE {ME} :psst")
    assert wait(app, lambda: any("psst" in l.text for b in s.all_buffers() for l in b.lines))
    assert not (notices_tab(s) and any("psst" in l.text for l in notices_tab(s).lines))
    done(srv, win)


# --- Add-ons > Oper tools > Settings... --------------------------------------------------------------

def test_oper_settings_window(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    w = win.open_oper_tools()
    assert isinstance(w, OperSettings) and win.tools["opersettings"] is w
    assert w.notices.isChecked() and w.length.currentText() == "1 day"
    assert w.reasons.count() == 4
    w.notices.setChecked(False)
    assert win.cfg.oper_notices is False and not win.oper_notices_act.isChecked()
    w.length.setCurrentText("30 days")
    assert win.cfg.oper_for == "30 days"
    w.reasons.setCurrentRow(0)
    w.remove()
    assert "Spam" not in win.cfg.oper_reasons and w.reasons.count() == 3
    assert "not an operator" in w.status.text()
    make_oper(app, srv, s)
    assert win.open_oper_tools() is w and "SkinIRC" in w.status.text()
    done(srv, win)


def test_no_other_client_names_in_the_app_text():
    import inspect
    text = inspect.getsource(oper).lower()
    for name in ("xchat", "mirc", "adiirc", "hexchat", "irssi", "weechat"):
        # the module docstring and comments may talk about servers only; user-facing text never names a client
        assert f'"{name}' not in text and f"'{name}" not in text


def test_kill_after_losing_oper_sends_nothing(app, tmp_path):
    srv, win, s = connected(app, tmp_path)
    make_oper(app, srv, s)
    d = KillDialog(win, s, "zed", "~z@203.0.113.7")
    srv.send(f":{ME} MODE {ME} :-o")
    assert wait(app, lambda: not s.is_oper)
    d.accept()
    wait(app, lambda: False, ms=300)
    assert not sent(srv, "KILL") and not d.go.isEnabled() and "no longer" in d.sends.text()
    done(srv, win)


def test_ip_ban_on_a_host_name_says_why(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["solanum"])
    make_oper(app, srv, s)
    d = BanDialog(win, s, "zed", "~z@host.example.net")
    assert not d.why.isVisibleTo(d)
    d.kind.setCurrentIndex(1)                                  # DLINE
    assert d.why.isVisibleTo(d) and "host.example.net is a host name" in d.why.text()
    d.kind.setCurrentIndex(0)
    assert not d.why.isVisibleTo(d)
    done(srv, win)
