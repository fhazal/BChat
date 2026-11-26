"""0.9.3: Settings > Add-ons and the built-in Channel Protection add-on (mockup-addons.png, mockup-channel-guard.png,
mockup-kick-reasons.png). Off by default; acts only where you have @; one grey line per action."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel

import bchat.protection as protection
from bchat import config
from bchat.addons import AddonsDialog, oper_networks, oper_status
from bchat.config import Config
from bchat.protection import (GREY, PREFIX, REASONS, KickReasonsDialog, ProtectionDialog, ProtectionWindow, describe,
                              kick_reason, new_rule, ordinal, warning)
from bchat.protocol import mask_ban
from test_live import live_with, make_win, wait

HOST = "z@evil.net"
MASK = mask_ban("zed", HOST, 1)


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(protection, "DELAY", (0, 0))
    monkeypatch.setattr(protection, "MINUTE", 0.2)       # "1 minute" = 0.2 s


def grey(b):
    return [l.text for l in b.lines if PREFIX in l.text]


def settle(app, ms=250):
    wait(app, lambda: False, ms)


def acts(srv):
    """What Channel Protection sent: warnings, kicks, bans and locks (not BChat's own join-time requests)."""
    return [x for x in srv.received if x.startswith(("NOTICE zed", "KICK ")) or
            x.startswith(("MODE #skinhead +b ", "MODE #skinhead -b ")) or x in ("MODE #skinhead +i", "MODE #skinhead -i")]


def say(srv, text, nick="zed", host=HOST, cmd="PRIVMSG"):
    srv.send(f":{nick}!{host} {cmd} #skinhead :{text}")


def joined(app, srv, s, op=True, others="Belon Wira"):
    assert wait(app, lambda: "#skinhead" in s.buffers and s.state == "connected" and s.buffers["#skinhead"].joined)
    srv.send(f":srv 353 {s.nick} = #skinhead :{'@' if op else ''}{s.nick} {others}")
    srv.send(f":srv 366 {s.nick} #skinhead :End")
    b = s.buffers["#skinhead"]
    assert wait(app, lambda: s.nick.lower() in b.users and len(b.users) > 1 and s.own_rank(b) == ("@" if op else ""))
    return b


def setup(app, tmp_path, op=True, others="Belon Wira", on=True, **kw):
    srv, win, net, s = live_with(app, tmp_path)
    win.cfg.addon_protection = on
    win.cfg.protect_rules = [new_rule(channel="#skinhead", **kw)]
    b = joined(app, srv, s, op=op, others=others)
    srv.send(f":zed!{HOST} JOIN #skinhead")
    assert wait(app, lambda: "zed" in b.users)
    return srv, win, s, b


def done(srv, win):
    win.close()
    srv.stop()


# --- the words ------------------------------------------------------------------------------------

def test_config_defaults_add_on_off_oper_tools_on_and_an_empty_list():
    c = Config()
    assert c.addon_protection is False and c.addon_oper is True
    assert c.protect_on is True and c.protect_rules == []


def test_kick_reason_defaults_overrides_ban_time_and_warning():
    r = new_rule()
    assert kick_reason(r, "flood") == "Too many lines too fast, please slow down"
    assert kick_reason(r, "flood", ban=True) == "Too many lines too fast, please slow down. Banned for 10 min"
    assert warning(r, "caps") == "Warning: Please turn off caps lock"
    r = new_rule(reasons={"caps": "Mind the caps!", "flood": "   "}, ban_mins=5)
    assert kick_reason(r, "caps") == "Mind the caps!"
    assert kick_reason(r, "caps", ban=True) == "Mind the caps! Banned for 5 min"     # no extra dot after "!"
    assert kick_reason(r, "flood") == REASONS["flood"]                                  # empty = the default
    r = new_rule(reason_ban_time=False, reason_warn=False)
    assert kick_reason(r, "repeat", ban=True) == "Please don't repeat the same line"
    assert warning(r, "repeat") == "Please don't repeat the same line"
    # never repeats the bad word, never says "Guard"
    for key in REASONS:
        text = kick_reason(new_rule(), key, ban=True)
        assert "nitro" not in text.lower() and "guard" not in text.lower() and text


def test_ordinals_and_the_list_columns():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th"]
    assert describe(new_rule(channel="#chat", network="SkinIRC")) == [
        "#chat", "SkinIRC", "flood, repeats, CAPS, CTCP, nick flood, mass join, bad words (3)", "warn > kick > ban 10 min"]
    assert describe(new_rule(steps=["kick", "kick", "nothing"]))[:2] == ["all where I'm @", "All networks"]
    assert describe(new_rule(steps=["kick", "kick", "nothing"]))[3] == "kick > nothing"


# --- off by default ------------------------------------------------------------------------------

def test_default_off_does_nothing(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, on=False)
    for i in range(6):
        say(srv, "SAME LINE IN CAPITALS FOR EVERYONE")
    say(srv, "get free nitro")
    for i in range(7):
        srv.send(f":j{i}!j@x{i}.net JOIN #skinhead")
    settle(app, 400)
    assert not acts(srv) and not grey(b)
    # the add-on on, but the list switched off: still nothing
    win.cfg.addon_protection, win.cfg.protect_on = True, False
    for i in range(6):
        say(srv, "again and again")
    settle(app, 300)
    assert not acts(srv) and not grey(b)
    # on, with an empty list: nothing
    win.cfg.protect_on, win.cfg.protect_rules = True, []
    for i in range(6):
        say(srv, "once more")
    settle(app, 300)
    assert not acts(srv) and not grey(b)
    done(srv, win)


# --- each catch: at its threshold, not below -----------------------------------------------------

def test_flood_one_grey_line_and_a_warning_notice(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path)
    for i in range(4):
        say(srv, f"line {i}")
    settle(app)
    assert not acts(srv) and not grey(b)
    say(srv, "line 4")
    assert wait(app, lambda: grey(b))
    settle(app, 150)
    assert grey(b) == [f"{GREY}{PREFIX}zed sent 5 lines in 3 s: warning by notice (1st)"]       # exactly one line
    assert wait(app, lambda: "NOTICE zed :Warning: Too many lines too fast, please slow down" in srv.received)
    assert len(acts(srv)) == 1
    done(srv, win)


def test_repeat_caps_colour_and_long_lines(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, colour=True, colour_codes=3, long=True, long_chars=20,
                           steps=["warn", "warn", "warn", "warn"])
    say(srv, "hello there")
    say(srv, "hello  there")                           # same line (spaces and case don't matter)
    settle(app)
    assert not grey(b)
    say(srv, "Hello there")
    assert wait(app, lambda: len(grey(b)) == 1)
    assert grey(b)[0] == f"{GREY}{PREFIX}zed repeated a line 3 times: warning by notice (1st)"
    settle(app, 3100)                                  # the flood window (5 lines in 3 s) empties

    say(srv, "ABCDEFGHIJKLMNabcdef")                   # exactly 70%: not over
    say(srv, "HELLO WORLD")                            # only 10 letters
    settle(app)
    assert len(grey(b)) == 1
    say(srv, "ABCDEFGHIJKLMNOabcde")                   # 75%
    assert wait(app, lambda: len(grey(b)) == 2)
    assert grey(b)[1].endswith("zed wrote 75% capitals: warning by notice (2nd)")
    settle(app, 3100)

    say(srv, "a\x02b\x02c\x02d")                       # 3 codes: not more than 3
    settle(app)
    assert len(grey(b)) == 2
    say(srv, "a\x02b\x02c\x02d\x02e")
    assert wait(app, lambda: len(grey(b)) == 3)
    assert grey(b)[2].endswith("zed used 4 colour or bold codes in a line: warning by notice (3rd)")
    settle(app, 3100)

    say(srv, "x" * 20)
    settle(app)
    assert len(grey(b)) == 3
    say(srv, "y" * 21)
    assert wait(app, lambda: len(grey(b)) == 4)
    assert grey(b)[3].endswith("zed sent a line of 21 characters: warning by notice (4th)")
    done(srv, win)


def test_ctcp_and_notice_to_the_whole_channel(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, steps=["warn", "warn"])
    say(srv, "\x01ACTION waves\x01")                   # a /me is not a CTCP
    settle(app)
    assert not grey(b)
    say(srv, "\x01VERSION\x01")
    assert wait(app, lambda: len(grey(b)) == 1)
    assert grey(b)[0].endswith("zed sent a CTCP to the whole channel: warning by notice (1st)")
    say(srv, "hi all", cmd="NOTICE")
    assert wait(app, lambda: len(grey(b)) == 2)
    assert grey(b)[1].endswith("zed sent a notice to the whole channel: warning by notice (2nd)")
    assert "NOTICE zed :Warning: No CTCPs or notices to the whole channel" in srv.received
    done(srv, win)


def test_nick_flood(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path)
    srv.send(f":zed!{HOST} NICK zed1")
    srv.send(f":zed1!{HOST} NICK zed2")
    settle(app)
    assert not grey(b)
    srv.send(f":zed2!{HOST} NICK zed3")
    assert wait(app, lambda: grey(b))
    assert grey(b)[0].endswith("zed3 changed nick 3 times in 60 s: warning by notice (1st)")
    assert wait(app, lambda: any(x.startswith("NOTICE zed3 :Warning: Too many nick changes") for x in srv.received))
    done(srv, win)


def test_mass_join_locks_then_unlocks_and_netsplits_do_not_count(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, massjoin_mins=1)        # zed's join was the 1st
    for i in range(4):
        srv.send(f":j{i}!j@x{i}.net JOIN #skinhead")
    settle(app)
    assert "MODE #skinhead +i" not in srv.received and not grey(b)
    srv.send(":j4!j@x4.net JOIN #skinhead")
    assert wait(app, lambda: "MODE #skinhead +i" in srv.received)
    assert grey(b) == [f"{GREY}{PREFIX}6 joins in 10 s: locking #skinhead with +i for 1 minute"]
    srv.send(f":{s.nick}!b@me.net MODE #skinhead +i")
    assert wait(app, lambda: "i" in b.modes)
    assert wait(app, lambda: "MODE #skinhead -i" in srv.received, 2000)
    assert grey(b)[-1] == f"{GREY}{PREFIX}1 minute is up: unlocking #skinhead"
    assert not any(x.startswith("KICK") for x in srv.received)      # a mass join kicks nobody
    done(srv, win)


def test_netsplit_rejoins_are_not_a_mass_join(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, others="Belon Wira a1 a2 a3 a4 a5 a6")
    for i in range(1, 7):
        srv.send(f":a{i}!a@x{i}.net QUIT :hub.example.net leaf.example.net")
    for i in range(1, 7):
        srv.send(f":a{i}!a@x{i}.net JOIN #skinhead")
    assert wait(app, lambda: "a6" in b.users)
    settle(app, 300)
    assert "MODE #skinhead +i" not in srv.received and not grey(b)
    done(srv, win)


def test_clones_more_than_the_count(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, clones=True, clones_count=3, massjoin=False)
    srv.send(":c1!c@evil.net JOIN #skinhead")
    srv.send(":c2!c@evil.net JOIN #skinhead")               # 3 from one address: not more than 3
    settle(app)
    assert not grey(b)
    srv.send(":c3!c@evil.net JOIN #skinhead")
    assert wait(app, lambda: grey(b))
    assert grey(b) == [f"{GREY}{PREFIX}c3 makes 4 people from one address: warning by notice (1st)"]
    done(srv, win)


def test_bad_words_kick_never_repeats_the_word(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, steps=["kick"])
    say(srv, "free stuff, nitro later")                     # not the phrase
    settle(app)
    assert not grey(b)
    say(srv, "get FREE  Nitro here")
    assert wait(app, lambda: grey(b))
    assert grey(b)[0].endswith("zed said a bad word (free nitro): kicking (1st)")
    assert wait(app, lambda: "KICK #skinhead zed :Please mind your language" in srv.received)
    say(srv, "best casinos online")                         # casino* catches casinos
    assert wait(app, lambda: len(grey(b)) == 2)
    assert grey(b)[1].endswith("zed said a bad word (casino*): kicking (2nd)")
    assert wait(app, lambda: len([x for x in srv.received if x.startswith("KICK")]) == 2)
    kicks = [x for x in srv.received if x.startswith("KICK")]
    assert not any("nitro" in k.lower() or "casino" in k.lower() for k in kicks)
    done(srv, win)


# --- the ladder, timed unban ----------------------------------------------------------------------

def repeat3(app, srv, b, n, text="buy now"):
    for _ in range(3):
        say(srv, text)
    assert wait(app, lambda: len(grey(b)) == n)


def test_ladder_warn_kick_kickban_with_reasons(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path)
    repeat3(app, srv, b, 1)
    assert grey(b)[0].endswith(": warning by notice (1st)")
    assert wait(app, lambda: "NOTICE zed :Warning: Please don't repeat the same line" in srv.received)
    repeat3(app, srv, b, 2, "buy later")
    assert grey(b)[1] == f"{GREY}{PREFIX}zed repeated a line 3 times: kicking (2nd)"
    assert wait(app, lambda: "KICK #skinhead zed :Please don't repeat the same line" in srv.received)
    repeat3(app, srv, b, 3, "buy again")
    assert grey(b)[2] == f"{GREY}{PREFIX}zed repeated a line 3 times: kickbanning {MASK} for 10 min (3rd)"
    assert wait(app, lambda: "KICK #skinhead zed :Please don't repeat the same line. Banned for 10 min" in srv.received)
    i_ban = srv.received.index(f"MODE #skinhead +b {MASK}")
    assert i_ban < srv.received.index("KICK #skinhead zed :Please don't repeat the same line. Banned for 10 min")
    repeat3(app, srv, b, 4, "and again")                    # after the 3rd: the last step again
    assert grey(b)[3].endswith("kickbanning " + MASK + " for 10 min (4th)")
    done(srv, win)


def test_custom_reasons_and_the_nothing_step(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, steps=["warn", "kickban", "nothing"], reasons={"repeat": "No echoes here"},
                           reason_warn=False, reason_ban_time=False)
    repeat3(app, srv, b, 1)
    assert wait(app, lambda: "NOTICE zed :No echoes here" in srv.received)
    repeat3(app, srv, b, 2, "two")
    assert wait(app, lambda: "KICK #skinhead zed :No echoes here" in srv.received)
    n = len(acts(srv))
    repeat3(app, srv, b, 3, "three")
    assert grey(b)[2] == f"{GREY}{PREFIX}zed repeated a line 3 times: doing nothing, as set (3rd)"
    settle(app)
    assert len(acts(srv)) == n
    done(srv, win)


def test_timed_unban_and_it_waits_for_op(app, tmp_path, quick, monkeypatch):
    srv, win, s, b = setup(app, tmp_path, steps=["kickban"], ban_mins=1)
    repeat3(app, srv, b, 1)
    assert wait(app, lambda: f"MODE #skinhead +b {MASK}" in srv.received)
    assert wait(app, lambda: f"MODE #skinhead -b {MASK}" in srv.received, 2000)
    assert grey(b)[-1] == f"{GREY}{PREFIX}1 minute is up: lifting the ban {MASK}"
    # again, but BChat loses @ before the time is up: the lift waits until @ is back
    srv.send(f":zed!{HOST} JOIN #skinhead")
    assert wait(app, lambda: "zed" in b.users)
    monkeypatch.setattr(protection, "MINUTE", 1.5)
    repeat3(app, srv, b, 3, "again")                        # ban line + lift line + this one
    srv.send(f":ChanServ!s@services. MODE #skinhead -o {s.nick}")
    assert wait(app, lambda: s.own_rank(b) == "")
    assert wait(app, lambda: s.protection.due)               # the minute is up, but no @: it waits
    settle(app, 300)
    assert srv.received.count(f"MODE #skinhead -b {MASK}") == 1 and len(grey(b)) == 3
    srv.send(f":ChanServ!s@services. MODE #skinhead +o {s.nick}")
    assert wait(app, lambda: srv.received.count(f"MODE #skinhead -b {MASK}") == 2)
    assert grey(b)[-1] == f"{GREY}{PREFIX}1 minute is up: lifting the ban {MASK}" and not s.protection.due
    done(srv, win)


def test_someone_else_unbanning_cancels_our_unban(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, steps=["kickban"], ban_mins=1, others="Belon @Wira")
    repeat3(app, srv, b, 1)
    assert wait(app, lambda: f"MODE #skinhead +b {MASK}" in srv.received)
    srv.send(f":Wira!w@ops.net MODE #skinhead -b {MASK}")
    settle(app, 600)
    assert f"MODE #skinhead -b {MASK}" not in srv.received and len(grey(b)) == 1
    done(srv, win)


# --- who is never touched, and when BChat stays out of it ----------------------------------------

def test_exemptions(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, others="@Wira %Half +Vee Pal ChanServ Belon")
    win.cfg.friends = ["Pal"]
    win.cfg.control_rules = [{"who": "*!*@good.net", "by": "mask", "give": "", "protect": False, "channels": "#skinhead",
                              "network": ""}]
    srv.send(":Listed!l@good.net JOIN #skinhead")
    srv.send(":Oper!o@staff.net JOIN #skinhead")
    srv.send(":irc.example.net NOTICE #skinhead :server notice")
    assert wait(app, lambda: "oper" in b.users and "listed" in b.users)
    b.users["oper"].oper = True                              # WHO said "*"
    for nick in ("Wira", "Half", "Vee", "Pal", "ChanServ", "Listed", "Oper", s.nick):
        for _ in range(3):
            say(srv, "same thing", nick=nick, host=f"{nick.lower()}@{nick.lower()}.net")
    settle(app, 400)
    assert not grey(b) and not any(x.startswith(("NOTICE ", "KICK ")) and "Warning" in x for x in srv.received)
    # the boxes can be unticked: + and friends then count; @ (and above +) never does
    win.cfg.protect_rules[0].update(leave_voiced=False, leave_friends=False)
    for nick in ("Wira", "Half", "Vee", "Pal"):
        for _ in range(3):
            say(srv, f"another thing {nick}", nick=nick, host=f"{nick.lower()}@{nick.lower()}.net")
    assert wait(app, lambda: len(grey(b)) == 2)
    settle(app, 200)
    who = sorted(t.split(PREFIX)[1].split()[0] for t in grey(b))
    assert who == ["Pal", "Vee"]
    done(srv, win)


def test_only_where_i_have_op(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path, op=False)
    for i in range(6):
        say(srv, f"flood {i}")
    settle(app, 300)
    assert not grey(b) and not acts(srv)
    srv.send(f":ChanServ!s@services. MODE #skinhead +o {s.nick}")
    assert wait(app, lambda: s.own_rank(b) == "@")
    settle(app, 3100)
    for i in range(5):
        say(srv, f"more {i}")
    assert wait(app, lambda: grey(b))
    done(srv, win)


def test_skips_when_someone_else_already_acted(app, tmp_path, quick, monkeypatch):
    srv, win, s, b = setup(app, tmp_path, others="Belon @Wira")
    # another op banned them just before
    srv.send(f":Wira!w@ops.net MODE #skinhead +b *!*@evil.net")
    settle(app, 100)
    for _ in range(3):
        say(srv, "spam spam")
    settle(app, 400)
    assert not grey(b) and not acts(srv)
    # another op kicks them while BChat waits its 1-2 s
    monkeypatch.setattr(protection, "DELAY", (0.4, 0.4))
    monkeypatch.setattr(protection, "SLACK", 0.0)
    srv.send(f":Wira!w@ops.net MODE #skinhead -b *!*@evil.net")
    settle(app, 100)
    b.users.get("zed") or srv.send(f":zed!{HOST} JOIN #skinhead")
    for _ in range(3):
        say(srv, "spam again")
    srv.send(":Wira!w@ops.net KICK #skinhead zed :enough")
    settle(app, 800)
    assert not grey(b) and not acts(srv)
    # and an op voicing them meanwhile: they are left alone too
    srv.send(f":zed!{HOST} JOIN #skinhead")
    assert wait(app, lambda: "zed" in b.users)
    for _ in range(3):
        say(srv, "spam thrice")
    srv.send(":Wira!w@ops.net MODE #skinhead +v zed")
    settle(app, 800)
    assert not grey(b) and not acts(srv)
    done(srv, win)


def test_a_rule_for_the_channel_beats_one_for_every_channel(app, tmp_path, quick):
    srv, win, s, b = setup(app, tmp_path)
    every, here = new_rule(steps=["nothing"]), new_rule(channel="#SKINHEAD", steps=["kick"])
    win.cfg.protect_rules = [every, here]
    assert s.protection._rule(b) is here
    win.cfg.protect_rules = [every]
    assert s.protection._rule(b) is every
    win.cfg.protect_rules = [new_rule(network="OtherNet")]
    assert s.protection._rule(b) is None
    done(srv, win)


# --- the windows ---------------------------------------------------------------------------------

def menu(win, title):
    return next(a.menu() for a in win.menubar_.actions() if a.text() == title)


def texts_of(w):
    return [x.text() for x in w.findChildren(QLabel) + w.findChildren(QAbstractButton)]


def test_menus_and_the_add_ons_window(app, tmp_path):
    win, net = make_win(tmp_path, 6667)
    names = [a.text() for a in menu(win, "S&ettings").actions()]
    assert names[names.index("&Preferences") + 1] == "Add-ons..."
    names = [a.text() for a in menu(win, "&Window").actions()]
    assert names[names.index("Ban List...") + 1] == "Channel Protection..."
    act = win.protection_act
    assert not act.isVisible() and not act.isEnabled()          # off: no Window menu item
    d = win.open_addons()
    assert isinstance(d, AddonsDialog) and d.isVisible()
    assert d.protection.text() == "Channel Protection" and not d.protection.isChecked()
    assert d.oper.text() == "Oper tools" and d.oper.isChecked()
    assert d.protection_btn.isHidden() and not d.oper_btn.isHidden()
    assert d.protection_btn.sizePolicy().retainSizeWhenHidden()
    assert "<i>Now: not an operator on any network, so nothing shows.</i>" in texts_of(d)
    h = d.height()
    d.protection.setChecked(True)                               # tick: the menu item and Settings... show
    assert win.cfg.addon_protection and act.isVisible() and act.isEnabled() and not d.protection_btn.isHidden()
    assert d.height() == h
    assert config.load(tmp_path).addon_protection is True       # saved
    d.protection_btn.click()
    w = win.tools["protection"]
    assert isinstance(w, ProtectionWindow) and w.isVisible()
    act.trigger()
    assert win.tools["protection"] is w and w.isVisible()
    d.protection.setChecked(False)                              # untick: hidden again, the window too
    assert not act.isVisible() and not act.isEnabled() and not w.isVisible() and d.protection_btn.isHidden()
    assert win.open_protection() is None
    assert config.load(tmp_path).addon_protection is False
    d.oper.setChecked(False)
    assert win.cfg.addon_oper is False and d.oper_btn.isHidden()
    assert config.load(tmp_path).addon_oper is False
    d.oper.setChecked(True)
    d.oper_btn.click()                                          # Oper tools > Settings... opens its own window
    w = win.open_oper_tools()
    assert w is win.tools["opersettings"] and w.isVisible()
    d.accept()
    win.close()


def test_oper_status_line():
    nobody = SimpleNamespace(sessions={"a": SimpleNamespace(net=SimpleNamespace(name="Libera"))})
    assert oper_networks(nobody) == []
    assert oper_status(nobody) == "not an operator on any network, so nothing shows."
    oper = SimpleNamespace(sessions={"a": SimpleNamespace(net=SimpleNamespace(name="SkinIRC"), is_oper=True),
                                     "b": SimpleNamespace(net=SimpleNamespace(name="Libera"), is_oper=False)})
    assert oper_networks(oper) == ["SkinIRC"]
    assert oper_status(oper) == "you're an operator on SkinIRC, so the Oper menu is on."


def test_protection_list_editor_and_kick_reasons(app, tmp_path):
    win, net = make_win(tmp_path, 6667)
    win.cfg.addon_protection = True
    win.addons_changed()
    w = win.open_protection()
    assert w.windowTitle() == "BChat: Channel Protection" and w.on.isChecked()
    assert w.view.topLevelItemCount() == 0 and not w.edit_btn.isEnabled() and not w.remove_btn.isEnabled()
    d = w.add()
    assert isinstance(d, ProtectionDialog) and d.isVisible() and d.windowTitle() == "Channel Protection"
    assert not d.boxes["colour"].isChecked() and d.boxes["flood"].isChecked() and d.spins["flood_lines"].value() == 5
    d.channel.setText("chat")
    d.boxes["clones"].setChecked(True)
    d.spins["clones_count"].setValue(4)
    d.steps[2].setCurrentIndex(3)                               # 3rd: Nothing
    d.reasons_btn.click()
    k = d.reasons_dialog
    assert isinstance(k, KickReasonsDialog) and k.isVisible() and k.windowTitle() == "Channel Protection: kick reasons"
    assert k.edits["words"].text() == "Please mind your language" and k.reasons() == {}
    assert k.ban_time.isChecked() and k.warn.isChecked()
    k.edits["words"].setText("Language, please")
    k.edits["flood"].setText("")                                # empty = the default
    k.ban_time.setChecked(False)
    k.accept()
    d.accept()
    r = win.cfg.protect_rules[0]
    assert r["channel"] == "#chat" and r["network"] == "" and r["clones"] and r["clones_count"] == 4
    assert r["steps"] == ["warn", "kick", "nothing"]
    assert r["reasons"] == {"words": "Language, please"} and r["reason_ban_time"] is False and r["reason_warn"] is True
    it = w.view.topLevelItem(0)
    assert [it.text(c) for c in range(4)] == describe(r)
    assert config.load(tmp_path).protect_rules[0]["channel"] == "#chat"
    e = w.edit()
    assert e.windowTitle() == "Channel Protection: #chat" and e.channel.text() == "#chat"
    e.reasons_btn.click()
    assert e.reasons_dialog.edits["words"].text() == "Language, please" and not e.reasons_dialog.ban_time.isChecked()
    for x in (d, k, e, e.reasons_dialog, w):
        assert not any("guard" in t.lower() for t in texts_of(x) + [x.windowTitle()])
    e.reasons_dialog.reject()
    e.reject()
    w.on.setChecked(False)
    assert win.cfg.protect_on is False and config.load(tmp_path).protect_on is False
    w.remove()
    assert win.cfg.protect_rules == [] and w.view.topLevelItemCount() == 0
    win.close()


def test_channel_tab_right_click_opens_this_channels_rule(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)

    def items(m):
        return [a.text() for a in m.actions()]
    assert "Channel Protection..." not in items(win._switcher_menu(b))      # add-on off: hidden
    win.cfg.addon_protection = True
    assert "Channel Protection..." in items(win._switcher_menu(b))
    assert "Channel Protection..." not in items(win._switcher_menu(s.server_buffer))
    d = win.protect_channel(b)                                              # no rule yet: a new one, channel filled in
    assert d.isVisible() and d.channel.text() == "#skinhead"
    d.accept()
    assert win.cfg.protect_rules[0]["channel"] == "#skinhead"
    e = win.protect_channel(b)                                              # now it edits that rule
    assert e.windowTitle() == "Channel Protection: #skinhead"
    e.reject()
    assert len(win.cfg.protect_rules) == 1
    done(srv, win)
