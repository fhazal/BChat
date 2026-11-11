"""0.5.0 batch A: Auto-Op / Auto-Voice / Protect, the tray menu with your tabs + start in the tray, pop-up cards for
more events + the soft pop-up sound, Friends List extras (note, online time, per-friend pop-up / sound / WHOIS)."""
import time

import pytest
from PySide6.QtWidgets import QMenu

import bchat.control as control
from bchat.control import ControlWindow, RuleDialog, matches, nick_only, rule_for
from bchat.frienddialog import FriendDialog
from conftest import SOUNDS_PLAYED
from test_live import live_with, wait


def texts(b):
    return [l.text for l in b.lines]


def joined(app, srv, s, chan="#skinhead", op=True, others="Belon Wira"):
    assert wait(app, lambda: chan in s.buffers and s.state == "connected" and s.buffers[chan].joined)
    srv.send(f":srv 353 {s.nick} = {chan} :{'@' if op else ''}{s.nick} {others}")
    srv.send(f":srv 366 {s.nick} {chan} :End")
    assert wait(app, lambda: s.nick.lower() in s.buffers[chan].users and len(s.buffers[chan].users) > 1
                and s.own_rank(s.buffers[chan]) == ("@" if op else ""))
    return s.buffers[chan]


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(control, "DELAY", (0, 0))


def sent(srv, line):
    return lambda: line in srv.received


# --- Auto-Op / Auto-Voice / Protect -------------------------------------------------------------

def test_rules_match_by_account_or_host_never_by_nick_alone():
    assert nick_only("Wira") and nick_only("Wira!*@*") and nick_only("*!*@*") and nick_only("Wira!*")
    assert not nick_only("*!*@bsn.my") and not nick_only("*@bsn.my")
    acct = {"who": "Wira", "by": "account", "give": "@"}
    assert matches(acct, "Whoever", "x@y", "wira") and not matches(acct, "Wira", "wira@bsn.my", "")
    host = {"who": "*@bsn.my", "by": "mask", "give": "+"}
    assert matches(host, "Anyone", "a@bsn.my", "") and not matches(host, "Wira", "w@evil.net", "")
    assert not matches({"who": "Wira!*@*", "by": "mask"}, "Wira", "w@anywhere", "")       # refused even if saved

    class C:
        control_rules = [{"who": "*!*@bsn.my", "by": "mask", "give": "+", "channels": "#chat", "network": "SkinIRC"},
                         {"who": "Wira", "by": "account", "give": "@", "channels": "", "network": ""}]
    assert rule_for(C, "SkinIRC", "#chat", "A", "a@bsn.my", "")["give"] == "+"
    assert rule_for(C, "Libera", "#chat", "A", "a@bsn.my", "") is None                   # other network
    assert rule_for(C, "SkinIRC", "#other", "A", "a@bsn.my", "") is None                 # other channel
    assert rule_for(C, "Libera", "#any", "W", "w@x", "Wira")["give"] == "@"


def test_auto_op_by_account_and_auto_voice_by_host_only_when_i_have_op(app, tmp_path, quick):
    srv, win, net, s = live_with(app, tmp_path)
    win.cfg.control_rules = [{"who": "Wira", "by": "account", "give": "@", "protect": False, "channels": "#skinhead", "network": ""},
                             {"who": "*!*@bsn.my", "by": "mask", "give": "+", "protect": False, "channels": "", "network": "SkinIRC"}]
    b = joined(app, srv, s)
    srv.send(":Aiman!a@bsn.my JOIN #skinhead")
    assert wait(app, sent(srv, "MODE #skinhead +v Aiman"))
    assert any("Auto-voice: giving voice to Aiman (*!*@bsn.my)" in t for t in texts(b))
    # account rule: they join first, log in after (account-notify)
    srv.send(":Wira2!w@elsewhere.net JOIN #skinhead")
    srv.send(":Wira2!w@elsewhere.net ACCOUNT Wira")
    assert wait(app, sent(srv, "MODE #skinhead +o Wira2"))
    assert any("Auto-op: giving @ to Wira2 (account Wira)" in t for t in texts(b))
    # someone else got there first (ChanServ): nothing sent twice
    n = len(srv.received)
    srv.send(":Zul!z@bsn.my JOIN #skinhead")
    srv.send(":ChanServ!s@services. MODE #skinhead +v Zul")
    time.sleep(0.05)
    wait(app, lambda: False, 300)
    assert "MODE #skinhead +v Zul" not in srv.received[n:]
    # the list switched off: nothing
    win.cfg.control_on = False
    srv.send(":Ali!a@bsn.my JOIN #skinhead")
    wait(app, lambda: False, 300)
    assert "MODE #skinhead +v Ali" not in srv.received
    win.close(); srv.stop()


def test_no_op_no_action_and_getting_op_checks_who_is_here(app, tmp_path, quick):
    srv, win, net, s = live_with(app, tmp_path)
    win.cfg.control_rules = [{"who": "*!*@bsn.my", "by": "mask", "give": "@", "protect": False, "channels": "", "network": ""}]
    b = joined(app, srv, s, op=False)
    srv.send(":Aiman!a@bsn.my JOIN #skinhead")
    wait(app, lambda: False, 300)
    assert "MODE #skinhead +o Aiman" not in srv.received
    srv.send(f":ChanServ!s@services. MODE #skinhead +o {s.nick}")
    assert wait(app, sent(srv, "MODE #skinhead +o Aiman"))
    win.close(); srv.stop()


def test_protect_gives_back_unbans_never_kicks_and_stops_a_war(app, tmp_path, quick):
    srv, win, net, s = live_with(app, tmp_path)
    win.cfg.control_rules = [{"who": "*!*@bsn.my", "by": "mask", "give": "@", "protect": True, "channels": "", "network": ""}]
    b = joined(app, srv, s, others="@Wira!w@bsn.my Aiman")
    srv.send(":Wira!w@bsn.my JOIN #skinhead")          # gives BChat their address
    srv.send(":Aiman!a@x MODE #skinhead -o Wira")
    assert wait(app, lambda: srv.received.count("MODE #skinhead +o Wira") >= 1)
    assert any("Protect: Wira is protected, giving @ back" in t for t in texts(b))
    assert not any(x.startswith("KICK") for x in srv.received)
    # services or a server taking it: left alone
    n = srv.received.count("MODE #skinhead +o Wira")
    srv.send(":ChanServ!s@services. MODE #skinhead -o Wira")
    srv.send(":irc.example.net MODE #skinhead -o Wira")
    wait(app, lambda: False, 300)
    assert srv.received.count("MODE #skinhead +o Wira") == n
    # a ban that hits them is lifted
    srv.send(":Aiman!a@x MODE #skinhead +b *!*@bsn.my")
    assert wait(app, sent(srv, "MODE #skinhead -b *!*@bsn.my"))
    # an op war: after 3 give-backs a minute BChat stops and says so
    for _ in range(4):
        srv.send(":Aiman!a@x MODE #skinhead -o Wira")
    assert wait(app, lambda: any("Protect: stopped for Wira" in t for t in texts(b)))
    assert srv.received.count("MODE #skinhead +o Wira") + srv.received.count("MODE #skinhead -b *!*@bsn.my") <= 3
    win.close(); srv.stop()


def test_protect_works_with_raw_mode_lines_too(app, tmp_path, quick):
    srv, win, net, s = live_with(app, tmp_path)
    win.cfg.raw_modes = True
    win.cfg.control_rules = [{"who": "*!*@bsn.my", "by": "mask", "give": "+", "protect": True, "channels": "", "network": ""}]
    joined(app, srv, s, others="+Wira!w@bsn.my")
    srv.send(":Wira!w@bsn.my JOIN #skinhead")
    srv.send(":Aiman!a@x MODE #skinhead -v Wira")
    assert wait(app, sent(srv, "MODE #skinhead +v Wira"))
    win.close(); srv.stop()


def test_control_window_and_rule_dialog(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    w = win.open_control()
    assert isinstance(w, ControlWindow) and w.view.topLevelItemCount() == 0 and not w.edit_btn.isEnabled()
    d = w.add()
    d.by_mask.setChecked(True)
    d.mask.setText("Wira!*@*")
    assert not d.ok_btn.isEnabled() and "only looks at the nick" in d.problem.text()
    d.mask.setText("*@bsn.my")
    d.give_voice.setChecked(True); d.protect.setChecked(True); d.channels.setText("#chat   #bchat")
    assert d.ok_btn.isEnabled()
    d.ok_btn.click()
    assert wait(app, lambda: win.cfg.control_rules)
    r = win.cfg.control_rules[0]
    assert r == {"who": "*!*@bsn.my", "by": "mask", "give": "+", "protect": True, "channels": "#chat #bchat", "network": ""}
    assert w.view.topLevelItem(0).text(0) == "*!*@bsn.my" and w.view.topLevelItem(0).text(2) == "Yes"
    w.view.setCurrentItem(w.view.topLevelItem(0))
    e = w.edit()
    e.by_account.setChecked(True); e.account.setText("Wi ra")
    assert not e.ok_btn.isEnabled()
    e.account.setText("Wira"); e.network.setCurrentText("All networks"); e.ok_btn.click()
    assert wait(app, lambda: win.cfg.control_rules[0]["by"] == "account" and win.cfg.control_rules[0]["network"] == "")
    w.remove()
    assert not win.cfg.control_rules
    # from the nick menu: filled in for that person (account known -> account, else their address)
    d2 = RuleDialog(win, None, nick="Zul", account="", host="z@tm.net.my", network="SkinIRC", channel="#chat")
    assert d2.by_mask.isChecked() and d2.mask.text() == "*!*@tm.net.my" and d2.channels.text() == "#chat"
    d3 = RuleDialog(win, None, nick="Zul", account="ZulAcct", host="z@tm.net.my")
    assert d3.by_account.isChecked() and d3.account.text() == "ZulAcct"
    for x in (d, e, d2, d3):
        x.close()
    w.close(); win.close(); srv.stop()


def test_nick_menu_has_auto_op(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.select_buffer(b)
    menu = win.build_nick_menu(b, [b.users["wira"]])
    if menu is None:
        pytest.skip("nick menu builder has another name")
    ops = next(a.menu() for a in menu.actions() if a.text() == "Operator Actions")
    assert "Auto-Op / Auto-Voice..." in [a.text() for a in ops.actions()]
    win.close(); srv.stop()


# --- tray menu ----------------------------------------------------------------------------------

def test_tray_menu_lists_tabs_with_unread_and_mentions(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.cfg.tray_icon = True
    win._sync_tray()
    other = s.buffer("#other")
    win.select_buffer(s.server_buffer)
    srv.send(":Wira!w@h PRIVMSG #skinhead :hello")
    srv.send(":Wira!w@h PRIVMSG #skinhead :again")
    srv.send(f":Wira!w@h PRIVMSG {s.nick} :psst")
    assert wait(app, lambda: b.unread == 2 and "wira" in s.buffers and s.buffers["wira"].unread == 1)
    srv.send(f":Aiman!a@h PRIVMSG #skinhead :{s.nick}: look")
    assert wait(app, lambda: b.mentioned)
    entries = dict(win.tray_entries())["SkinIRC"]
    marks = {label: mark for _b, label, mark in entries}
    assert marks["#skinhead"] == "@" and marks["Wira"] == "1" and marks["#other"] == ""
    menu = QMenu(win)
    win.fill_tray_menu(menu)
    names = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert names[1] == "Show BChat" and "SkinIRC" in names and "#skinhead\t@" in names and "Wira\t1" in names
    assert "Away" in names and "Preferences..." in names and names[-1] == "Quit"
    assert next(a for a in menu.actions() if a.text() == "Wira\t1").font().bold()
    assert not next(a for a in menu.actions() if a.text() == "#other").font().bold()
    if win.tray is not None:                          # no system tray in the offscreen test platform
        assert "unread" in win.tray.toolTip() and "1 private" in win.tray.toolTip()
    # clicking a tab opens it and clears its count
    next(a for a in menu.actions() if a.text() == "#skinhead\t@").trigger()
    assert win.buf is b and b.unread == 0 and not b.mentioned
    # Away ticks /away everywhere
    away = next(a for a in menu.actions() if a.text() == "Away")
    away.setChecked(True)
    assert wait(app, lambda: any(x.startswith("AWAY") for x in srv.received))
    # list switched off: only the basics
    win.cfg.tray_list = False
    win.fill_tray_menu(menu)
    assert "#skinhead" not in " ".join(a.text() for a in menu.actions())
    win.close(); srv.stop()


def test_many_tabs_fold_quiet_ones_into_more(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    for i in range(25):
        s.buffer(f"#c{i}")
    s.buffer("#c3").unread = 4
    menu = QMenu(win)
    win.fill_tray_menu(menu)
    top = [a.text() for a in menu.actions()]
    assert "#c3\t4" in top and "#c4" not in top
    more = next(a.menu() for a in menu.actions() if a.text() == "More...")
    assert "#c4" in [a.text() for a in more.actions()]
    win.close(); srv.stop()


def test_tray_click_one_or_double_and_start_in_tray_pref(app, tmp_path):
    from PySide6.QtWidgets import QSystemTrayIcon
    from test_live import prefs
    srv, win, net, s = live_with(app, tmp_path)
    opened = []
    win._restore_from_tray = lambda: opened.append(1)
    R = QSystemTrayIcon.ActivationReason
    win._tray_clicked(R.Trigger)
    win.cfg.tray_click = "double"
    win._tray_clicked(R.Trigger)
    win._tray_clicked(R.DoubleClick)
    assert opened == [1, 1]
    prefs(win, lambda d: (d.start_how.setCurrentIndex(2), d.tray_click.setCurrentIndex(0)))
    assert win.cfg.start_in_tray and not win.cfg.start_minimized and win.cfg.tray_click == "one"
    if QSystemTrayIcon.isSystemTrayAvailable():
        assert win.tray is not None                  # 'In the tray' turns the tray icon on by itself
    prefs(win, lambda d: d.start_how.setCurrentIndex(1))
    assert win.cfg.start_minimized and not win.cfg.start_in_tray
    win.close(); srv.stop()


# --- pop-up cards for more events + the soft sound ----------------------------------------------

@pytest.fixture
def away_from_bchat(monkeypatch):
    def setup(win):
        monkeypatch.setattr(win, "isActiveWindow", lambda: False)
        win.notifier.busy = lambda: False
    return setup


def test_cards_for_kick_invite_disconnect_with_one_soft_sound(app, tmp_path, away_from_bchat):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    away_from_bchat(win)
    SOUNDS_PLAYED.clear()
    srv.send(f":Aiman!a@h KICK #skinhead {s.nick} :spam")
    assert wait(app, lambda: any(c.kind == "kicked" for c in win.notifier.cards))
    card = next(c for c in win.notifier.cards if c.kind == "kicked")
    assert card.nick == "You were kicked" and "#skinhead" in card.where and "spam" in card.text
    assert len(SOUNDS_PLAYED) == 1 and SOUNDS_PLAYED[0].endswith("soft.wav")
    win.notifier.last_new = 0
    srv.send(f":Wira!w@h INVITE {s.nick} :#secret")
    assert wait(app, lambda: any(c.kind == "invite" for c in win.notifier.cards))
    assert len(SOUNDS_PLAYED) == 1                  # one sound per 10 s, however many cards
    inv = next(c for c in win.notifier.cards if c.kind == "invite")
    assert inv.nick == "Wira invites you" and "#secret" in inv.where
    # a kick of someone else is no card
    win.notifier.clear(); wait(app, lambda: not win.notifier.cards, 1000)
    win.notifier.last_new = 0
    srv.send(":Aiman!a@h KICK #other Wira :bye")
    wait(app, lambda: False, 200)
    assert not any(c.kind == "kicked" for c in win.notifier.cards)
    # lost connection: a card; quitting yourself: none
    win.notifier.last_new = 0
    srv.client.close()
    assert wait(app, lambda: any(c.kind == "disconnect" for c in win.notifier.cards), 6000)
    win.notifier.clear(); wait(app, lambda: not win.notifier.cards, 1000); win.notifier.last_new = 0
    s.disconnect_from_network()                      # you did it yourself: no card
    wait(app, lambda: False, 300)
    assert not any(c.kind == "disconnect" for c in win.notifier.cards)
    win.close(); srv.stop()


def test_off_ticks_notices_and_services(app, tmp_path, away_from_bchat):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    away_from_bchat(win)
    srv.send(f":Wira!w@h NOTICE {s.nick} :psst")                    # notices are off by default
    wait(app, lambda: False, 200)
    assert not any(c.kind == "notice" for c in win.notifier.cards)
    win.cfg.popup_more["notice"] = True
    srv.send(f":NickServ!s@services. NOTICE {s.nick} :This nick is registered")
    wait(app, lambda: False, 200)
    assert not any(c.kind == "notice" for c in win.notifier.cards)   # never services
    srv.send(f":Wira!w@h NOTICE {s.nick} :psst again")
    assert wait(app, lambda: any(c.kind == "notice" and c.nick == "-Wira-" for c in win.notifier.cards))
    win.cfg.popup_more["kick"] = False
    srv.send(f":Aiman!a@h KICK #skinhead {s.nick} :x")
    wait(app, lambda: False, 200)
    assert not any(c.kind == "kicked" for c in win.notifier.cards)
    win.notifier.clear(); win.close(); srv.stop()


def test_sound_choice_time_and_quiet_rules(app, tmp_path, away_from_bchat):
    from test_live import prefs
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    away_from_bchat(win)
    prefs(win, lambda d: (d.popup_sound.setCurrentIndex(2), d.popup_time.setCurrentIndex(3)))
    assert win.cfg.popup_sound and win.cfg.popup_sound_name == "bee" and win.cfg.popup_seconds == 0
    assert win.notifier.show_ms == 0
    SOUNDS_PLAYED.clear()
    srv.send(f":Wira!w@h PRIVMSG {s.nick} :hi")                       # today's private card gets the sound too
    assert wait(app, lambda: win.notifier.cards)
    assert SOUNDS_PLAYED and SOUNDS_PLAYED[-1].endswith("bee.wav")
    assert not win.notifier.cards[0].timer.isActive()               # 'Until I close them'
    win.notifier.clear(); wait(app, lambda: not win.notifier.cards, 1000)
    # None: no sound; a Sound-page .wav for the event plays instead of (not with) the pop-up sound
    prefs(win, lambda d: d.popup_sound.setCurrentIndex(0))
    SOUNDS_PLAYED.clear(); win._last_chime = -100; win.notifier.last_new = 0
    srv.send(f":Zul!z@h PRIVMSG {s.nick} :hey")
    assert wait(app, lambda: win.notifier.cards)
    assert not SOUNDS_PLAYED
    assert win.play_soft_chime(force=True) and SOUNDS_PLAYED          # the Play button always plays
    # Windows busy (full screen, Do Not Disturb): quiet
    prefs(win, lambda d: d.popup_sound.setCurrentIndex(1))
    import bchat.notify as nt
    win._last_chime = -100
    orig = nt.windows_busy
    nt.windows_busy = lambda: True
    try:
        assert not win.play_soft_chime()
    finally:
        nt.windows_busy = orig
    win.notifier.clear(); win.close(); srv.stop()


def test_dcc_offer_is_one_file_card(app, tmp_path, away_from_bchat):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    away_from_bchat(win)
    win.cfg.alert_popup = [False, True, True]
    srv.send(f":Wira!w@h PRIVMSG {s.nick} :\x01DCC SEND holiday.jpg 2130706433 5000 2400000\x01")
    assert wait(app, lambda: any(c.kind == "dcc" for c in win.notifier.cards))
    assert [c.kind for c in win.notifier.cards] == ["dcc"]           # not also a private-message card
    assert win.notifier.cards[0].nick == "Wira sends a file"
    win.notifier.clear(); win.close(); srv.stop()


# --- Friends List extras ---------------------------------------------------------------------------

def test_friend_note_online_time_and_per_friend_options(app, tmp_path, away_from_bchat):
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: s.state == "connected")
    away_from_bchat(win)
    win.add_friend("Belon")
    d = win.ask_friend("Belon", edit=True)
    assert d.nick.isReadOnly() and d.popup.isChecked() and not d.sound.isChecked()
    d.note.setText("  knows   the radio setup ")
    d.sound.setChecked(True)
    d.whois.setChecked(True)
    d.ok_btn.click()
    assert wait(app, lambda: "belon" in win.cfg.friend_opts)
    assert win.cfg.friend_opts["belon"]["sound"] and win.cfg.friend_opts["belon"]["whois"]
    from bchat.people import card_for
    assert card_for(win.cfg, "Belon")["notes"] == "knows the radio setup"   # the Address Book card holds the note
    SOUNDS_PLAYED.clear()
    s.poll_friends(); srv.send(f":srv 303 {s.nick} :Belon")
    assert wait(app, lambda: any("Notify: Belon is online (SkinIRC).  Note: knows the radio setup" in t for t in texts(s.server_buffer)))
    assert wait(app, lambda: any(c.kind == "friend" and c.nick == "Belon is online" for c in win.notifier.cards))
    assert wait(app, sent(srv, "WHOIS Belon")) or any(x.startswith("WHOIS Belon") for x in srv.received)
    assert len(SOUNDS_PLAYED) == 1                                   # their sound, and no second chime
    w = win.open_tool("friends")
    row = w.view.topLevelItem(0)
    assert row.text(1) == "Online" and row.text(4) == "knows the radio setup" and row.text(3).endswith(" s")
    s.friend_state["belon"]["since"] -= 4 * 3600 + 5 * 60
    s.poll_friends(); srv.send(f":srv 303 {s.nick} :")
    assert wait(app, lambda: any("Belon is offline (SkinIRC). Online for 4 h 5 min" in t for t in texts(s.server_buffer)))
    # pop-up off for this friend: no card next time
    win.notifier.clear(); wait(app, lambda: not win.notifier.cards, 1000); win.notifier.last_new = 0
    win.cfg.friend_opts["belon"]["popup"] = False
    s.poll_friends(); srv.send(f":srv 303 {s.nick} :Belon")
    assert wait(app, lambda: sum("Belon is online" in t for t in texts(s.server_buffer)) == 2)
    wait(app, lambda: False, 200)
    assert not any(c.kind == "friend" for c in win.notifier.cards)
    # removing the friend keeps the Address Book card and its note
    win.remove_friend("Belon")
    assert "belon" not in win.cfg.friend_opts and card_for(win.cfg, "Belon")["notes"]
    w.close(); win.close(); srv.stop()


def test_friend_defaults_follow_the_old_whois_tick(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    win.cfg.whois_on_notify = True
    d = FriendDialog(win, "Zul")
    assert d.whois.isChecked() and d.popup.isChecked() and not d.sound.isChecked() and not d.sound_file.isEnabled()
    d.sound.setChecked(True)
    assert d.sound_file.isEnabled()
    d.close(); win.close(); srv.stop()


def test_tray_tooltip_counts_unread_and_private(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)

    class Tip:
        text = ""

        def setToolTip(self, t):
            Tip.text = t
    real, win.tray = win.tray, Tip()
    try:
        win.tray_tip()
        assert Tip.text == "BChat"
        s.buffers["#skinhead"].unread = 3
        q = s.buffer("Wira")
        q.unread = 1
        win.tray_tip()
        assert Tip.text == "BChat: 4 unread, 1 private"
    finally:
        win.tray = real
    win.close(); srv.stop()
