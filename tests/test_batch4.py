"""0.3.0 batch: nick colours + address book, /timer + /alias, Channel Central, +typing / +reply."""
import time

import pytest
from fake_ircd import FakeIrcd
from PySide6.QtCore import QPoint

from bchat import commands, people, timers
from bchat.central import ChannelCentral, is_op, mode_lines
from bchat.config import Config
from bchat.session import Line
from test_live import live_with, make_win, wait


def joined(app, srv, s, chan="#skinhead", op=True):
    assert wait(app, lambda: chan in s.buffers and s.state == "connected")
    if op:
        srv.send(f":srv 353 Badaboom = {chan} :@Badaboom Belon Wira")
        srv.send(f":srv 366 Badaboom {chan} :End")
        assert wait(app, lambda: "belon" in s.buffers[chan].users)
    return s.buffers[chan]


# --- nick colours + address book ------------------------------------------------------------

def test_colour_rules_masks_networks_and_cards():
    cfg = Config(nick="me")
    cfg.nick_colours = [{"mask": "Belon", "colour": "sapphire", "net": ""},
                        {"mask": "*!*@staff.bajubesi.org", "colour": "green", "net": ""},
                        {"mask": "Oracle", "colour": "yellow", "net": "SkinIRC"},
                        {"mask": "bel*", "colour": "red", "net": ""}]
    cfg.address_book = [{"nick": "Wira", "other": "Wira_, wira|away", "colour": "mauve"}]
    name = lambda net, nick, host="": people.colour_name(cfg, net, nick, host)   # noqa: E731
    assert name("Libera", "belon") == "sapphire"                        # first match wins, any case
    assert name("Libera", "Belinda") == "red"
    assert name("Libera", "Buzz", "buzz@staff.bajubesi.org") == "green"
    assert name("Libera", "Buzz") is None                               # host unknown: masks can't match
    assert name("SkinIRC", "Oracle") == "yellow" and name("Libera", "Oracle") is None
    assert name("Libera", "wira|away") == "mauve"                       # card: its other nicks too
    assert people.colour_for(cfg, "x", "Belon") == people.shade(cfg, "sapphire")
    people.set_rule(cfg, "Fhazal", "peach")
    assert cfg.nick_colours[0] == {"mask": "Fhazal", "colour": "peach", "net": ""}
    people.set_rule(cfg, "fhazal", "teal")
    assert cfg.nick_colours[0]["colour"] == "teal" and len(cfg.nick_colours) == 5


def test_colours_reach_chat_and_nick_list(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.select_buffer(b)
    win.cfg.nick_colours = [{"mask": "Belon", "colour": "peach", "net": ""}]
    win.nick_colours_changed()
    assert win.chat_colour_rule(b, "Belon") == people.shade(win.cfg, "peach")
    assert win.chat_colour_rule(b, "Wira") is None
    assert win.list_colour_rule(s, "Belon", "") == people.shade(win.cfg, "peach")
    srv.send(":Belon!b@h PRIVMSG #skinhead :coloured line")
    assert wait(app, lambda: "coloured line" in win.chat.toPlainText())
    block = win.chat.document().lastBlock()
    fmt = next(f for f in block.textFormats() if block.text()[f.start:f.start + f.length].startswith("Belon"))
    assert fmt.format.foreground().color().name() == people.shade(win.cfg, "peach").lower()
    win.close(); srv.stop()


def test_nick_colours_window_add_edit_move_remove(app, tmp_path):
    win, _net = make_win(tmp_path, 9)
    w = win.open_nick_colours()
    d = w.add()
    d.mask.setText("Belon"); d.colour.setCurrentIndex(people.COLOURS.index("blue")); d.accept()
    d = w.add()
    d.mask.setText("*!*@staff.x"); d.accept()
    assert [r["mask"] for r in win.cfg.nick_colours] == ["Belon", "*!*@staff.x"]
    assert not w.down_btn.isEnabled() and w.up_btn.isEnabled()          # the new one is picked, last
    w.move(-1)
    assert win.cfg.nick_colours[0]["mask"] == "*!*@staff.x"
    d = w.edit(); d.net.setCurrentIndex(1); d.accept()
    assert win.cfg.nick_colours[0]["net"] == "SkinIRC"
    w.remove()
    assert [r["mask"] for r in win.cfg.nick_colours] == ["Belon"]
    w.auto.setChecked(not win.cfg.color_nicks)
    from bchat import config
    assert config.load(tmp_path).nick_colours == win.cfg.nick_colours
    win.close()


def test_address_book_card_friends_and_colour(app, tmp_path):
    win, _net = make_win(tmp_path, 9)
    w = win.open_address_book("Wira", "Wira Hakim")
    c = people.card_for(win.cfg, "Wira")
    assert c["real"] == "Wira Hakim" and w.form.isVisible() and w.edits["real"].text() == "Wira Hakim"
    w.edits["other"].setText("Wira_, wira|away"); w._changed("other")
    assert people.card_for(win.cfg, "WIRA_") is c
    w.colour.setCurrentIndex(w.colour.findData("mauve")); w._changed("colour")
    assert people.colour_name(win.cfg, "any", "wira|away") == "mauve"
    w.friend.setChecked(True)
    assert "Wira" in win.cfg.friends
    w.friend.setChecked(False)
    assert "Wira" not in win.cfg.friends
    w.notes.setPlainText("runs the radio")
    assert c["notes"] == "runs the radio"
    win.open_address_book("Wira")                                       # again: the same card, never twice
    assert len(win.cfg.address_book) == 1
    w.remove()
    assert win.cfg.address_book == [] and w.empty.isVisible()
    win.close()


def test_nick_menu_has_address_book_and_colour(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    texts = [a.text() for a in win.build_nick_menu(b, [b.users["belon"]]).actions()]
    assert "Address Book..." in texts and "Nick Colour..." in texts
    texts = [a.text() for a in win.build_nick_menu(b, [b.users["belon"], b.users["wira"]]).actions()]
    assert "Address Book..." not in texts                               # one person only
    d = win.quick_nick_colour(s, "Belon")
    d.colour.setCurrentIndex(people.COLOURS.index("green")); d.accept()
    assert win.cfg.nick_colours[0] == {"mask": "Belon", "colour": "green", "net": ""}
    win.close(); srv.stop()


# --- /timer + /alias -------------------------------------------------------------------------

def test_timer_runs_lists_stops_and_has_limits(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    run = lambda t: commands.run(win, s, b, t)                          # noqa: E731
    run("/timer news 2 1 /say tick")
    assert any("Timer news: 2 times, every 1 seconds: /say tick" in l.text for l in b.lines)
    assert wait(app, lambda: sum(x in ("PRIVMSG #skinhead tick", "PRIVMSG #skinhead :tick") for x in srv.received) == 2, 5000)
    app.processEvents()
    assert "news" not in s.timers                                       # done after 2
    run("/timer 0 5 /me waits")
    run("/timers")
    assert any(l.text.strip().startswith("1 ") and "until stopped" in l.text for l in b.lines)
    run("/timer 1 off")
    assert not s.timers and any("Timer 1 stopped." in l.text for l in b.lines)
    run("/timer x 1 0.2 /say fast")
    assert any("at most once a second" in l.text for l in b.lines)
    run("/timer oops")
    assert any("Use: /timer" in l.text for l in b.lines)
    for i in range(timers.MAX_PER_NETWORK):
        run(f"/timer t{i} 0 60 /say x")
    run("/timer one-more 0 60 /say x")
    assert any("already 20 timers" in l.text for l in b.lines)
    run("/timers off")
    assert not s.timers
    win.close(); srv.stop()


def test_timer_flood_stop_and_disconnect_stop(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    t = timers.start(win, s, b, "spam", 0, 30, "/say a | /say b")
    commands.run(win, s, b, "/alias two /say one | /say two | /say three")
    t.command = "/two"
    for _ in range(2):
        timers._fire(win, s, t)
    assert "spam" not in s.timers and any("stopped: it sent more than 5 lines" in l.text for l in b.lines)
    timers.start(win, s, b, "later", 0, 30, "/say x")
    s.disconnect_from_network()
    assert wait(app, lambda: not s.timers)
    assert any("1 timer stopped: disconnected." in l.text for l in s.server_buffer.lines)
    win.close(); srv.stop()


def test_alias_adds_runs_with_dollars_bars_and_removes(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    run = lambda t: commands.run(win, s, b, t)                          # noqa: E731
    run("/alias hi /me waves at $1 on $network in $chan")
    assert ["hi", "me waves at $1 on $network in $chan"] in win.cfg.user_commands
    assert any("Alias /hi added" in l.text for l in b.lines)
    run("/hi Wira")
    assert wait(app, lambda: any("ACTION waves at Wira on SkinIRC in #skinhead" in x for x in srv.received))
    run("/hi $2- %c")                                                    # typed text is never read as a code
    assert wait(app, lambda: any("ACTION waves at $2- on SkinIRC" in x for x in srv.received))
    run("/alias bye /say bye $2- | /say J|wang stays")
    run("/bye x all of you")
    assert wait(app, lambda: any("PRIVMSG #skinhead :bye all of you" in x for x in srv.received))
    assert wait(app, lambda: any("PRIVMSG #skinhead :J|wang stays" in x for x in srv.received))
    run("/alias hi /me says hi")
    assert sum(1 for n, _c in win.cfg.user_commands if n == "hi") == 1 and any("Alias /hi changed" in l.text for l in b.lines)
    run("/alias")
    assert any(l.text.startswith("Your commands") and "/hi" in l.text for l in b.lines)
    run("/alias hi")
    assert not any(n == "hi" for n, _c in win.cfg.user_commands)
    run("/alias nope")
    assert any("No alias called /nope" in l.text for l in b.lines)
    run("/alias bad*name x")
    assert any("one word" in l.text for l in b.lines)
    from bchat import config
    assert ["bye", "say bye $2- | /say J|wang stays"] in config.load(tmp_path).user_commands
    win.close(); srv.stop()


# --- Channel Central -------------------------------------------------------------------------

def test_mode_lines_respect_max_modes_key_and_limit():
    lines = mode_lines("tnl", {"l": "50"}, {"t": True, "n": False, "m": True, "s": True}, "secret", 0, 3)
    assert lines == [("-n+ms", []), ("+k-l", ["secret"])]
    assert mode_lines("tk", {"k": "old"}, {"t": True}, "new", None, 4) == [("-k+k", ["old", "new"])]
    assert mode_lines("tk", {"k": "old"}, {"t": True}, "", None, 4) == [("-k", ["old"])]
    assert mode_lines("t", {}, {"t": True}, None, None, 4) == []


def test_channel_central_shows_server_modes_applies_and_lists(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    srv.send(":srv 005 Badaboom CHANMODES=beI,k,l,imnpstcCR MODES=4 :are supported")
    srv.send(":srv 324 Badaboom #skinhead +tnl 50")
    srv.send(":srv 333 Badaboom #skinhead Belon!b@h 1762690000")
    srv.send(":srv 332 Badaboom #skinhead :old topic")
    assert wait(app, lambda: b.topic_by == "Belon" and "l" in b.modes and s.modes_flags == "imnpstcCR")
    w = win.open_channel_central(b)
    assert set(w.flags) == set("imnpstcCR") and w.flags["t"].isChecked() and not w.flags["m"].isChecked()
    assert "Belon" in w.topic_by.text() and w.limit_box.isChecked() and w.limit.value() == 50
    assert is_op(s, b) and w.apply_btn.isEnabled() and not w.not_op.isVisible()
    assert wait(app, lambda: any(x == "MODE #skinhead +b" for x in srv.received))
    srv.send(":srv 367 Badaboom #skinhead *!*@spam.example Belon 1762690000")
    srv.send(":srv 368 Badaboom #skinhead :End")
    assert wait(app, lambda: w.views["b"].topLevelItemCount() == 1)
    assert w.tabs.tabText(0) == "Bans (1)"
    w.flags["m"].setChecked(True); w.flags["C"].setChecked(True); w.limit_box.setChecked(False)
    w.topic.setPlainText("new topic")
    w.apply()
    assert wait(app, lambda: "TOPIC #skinhead :new topic" in srv.received and "MODE #skinhead +mC-l" in srv.received)
    w.views["b"].topLevelItem(0).setSelected(True)
    w.remove_selected("b")
    assert wait(app, lambda: "MODE #skinhead -b *!*@spam.example" in srv.received)
    commands.run(win, s, b, "/channel")
    assert win.tools[("central", id(s), "#skinhead")] is w
    texts = [a.text() for a in win._switcher_menu(b).actions()]
    assert "Channel Central..." in texts
    win.close(); srv.stop()


def test_channel_central_without_op_is_read_only(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    srv.send(":srv 353 Badaboom = #skinhead :Badaboom @Belon")
    srv.send(":srv 366 Badaboom #skinhead :End")
    srv.send(":srv 324 Badaboom #skinhead +nt")
    assert wait(app, lambda: "t" in b.modes)
    w = win.open_channel_central(b)
    assert not is_op(s, b) and w.not_op.isVisible() and not w.apply_btn.isEnabled()
    assert not w.flags["n"].isEnabled() and w.topic.isReadOnly()
    srv.send(":Belon!b@h MODE #skinhead -t")
    assert wait(app, lambda: "t" not in b.modes)
    assert not w.topic.isReadOnly() and w.apply_btn.isEnabled()        # -t: anyone may set the topic
    assert w.planned()[1] == []                                          # never a MODE line without @
    win.close(); srv.stop()


# --- +typing / +reply --------------------------------------------------------------------------

def test_typing_shows_and_goes(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="message-tags")
    b = joined(app, srv, s)
    win.select_buffer(b)
    srv.send("@+typing=active :Belon!b@h TAGMSG #skinhead")
    assert wait(app, lambda: win.typing_label.isVisible() and win.typing_label.text() == "Belon is typing…")
    srv.send("@+typing=active :Wira!w@h TAGMSG #skinhead")
    assert wait(app, lambda: win.typing_label.text() == "Belon and Wira are typing…")
    srv.send(":Belon!b@h PRIVMSG #skinhead :here it is")
    assert wait(app, lambda: win.typing_label.text() == "Wira is typing…")
    srv.send("@+typing=done :Wira!w@h TAGMSG #skinhead")
    assert wait(app, lambda: not win.typing_label.isVisible())
    srv.send("@+typing=active :Wira!w@h TAGMSG #skinhead")
    assert wait(app, lambda: win.typing_label.isVisible())
    b.typing["wira"] = ("Wira", time.time() - 7)                       # 6 s without news: gone
    win.show_typing()
    assert not win.typing_label.isVisible()
    win.close(); srv.stop()


def test_my_typing_is_off_by_default_then_sent_paced(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="message-tags")
    b = joined(app, srv, s)
    win.select_buffer(b)
    assert not win.cfg.send_typing
    win.input.setText("hel")
    app.processEvents()
    assert not any("TAGMSG" in x for x in srv.received)               # off: nothing told
    win.cfg.send_typing = True
    win.input.setText("hello")
    win.input.setText("hello there")
    assert wait(app, lambda: sum("@+typing=active TAGMSG #skinhead" in x for x in srv.received) == 1)
    win.input.setText("")
    assert wait(app, lambda: any("@+typing=done TAGMSG #skinhead" in x for x in srv.received))
    s.client_tag_deny = "*"
    win.input.setText("x")
    app.processEvents()
    assert sum("typing=active" in x for x in srv.received) == 1         # the server drops client tags: never sent
    win.close(); srv.stop()


def test_reply_sends_tag_prefix_and_quotes_incoming(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path, caps="message-tags")
    b = joined(app, srv, s)
    win.select_buffer(b)
    srv.send("@msgid=abc123 :Wira!w@h PRIVMSG #skinhead :does history come back?")
    assert wait(app, lambda: any(l.msgid == "abc123" for l in b.lines))
    win.start_reply(b, "abc123")
    assert win.reply_bar.isVisible() and "Wira" in win.reply_text.text() and win.input.text() == "Wira: "
    win.input.setText("Wira: yes it does")
    win._entered()
    assert wait(app, lambda: "@+draft/reply=abc123 PRIVMSG #skinhead :Wira: yes it does" in srv.received)
    assert not win.reply_bar.isVisible()
    srv.send("@msgid=def456;+draft/reply=abc123 :Belon!b@h PRIVMSG #skinhead :mine does")
    assert wait(app, lambda: any(l.reply_to == "abc123" for l in b.lines))
    quote = next(l for l in b.lines if l.reply_to == "abc123")
    assert "↪ Wira: does history come back?" in quote.text
    assert b.lines.index(quote) == len(b.lines) - 2                     # right above the reply
    assert win.chat.block_of("abc123") is not None
    win.reply_jump(b, "abc123")                                          # a click on the quote: no crash, lit up
    win.reply_to_last()
    assert win.replying is not None and win.replying[1] == "def456"
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(win.input, Qt.Key.Key_Escape)                        # a real Esc in the input box
    assert not win.reply_bar.isVisible()
    win.start_reply(b, "def456")
    other = s.buffer("#other")
    win.select_buffer(other)
    assert win.replying is None                                          # it belongs to its own tab
    win.close(); srv.stop()


def test_no_message_tags_means_no_reply_or_typing(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.select_buffer(b)
    srv.send("@msgid=abc :Wira!w@h PRIVMSG #skinhead :hello")
    assert wait(app, lambda: any(l.msgid == "abc" for l in b.lines))
    assert not s.client_tag_ok("+draft/reply") and not s.send_typing("#skinhead", "active")
    pos = win.chat.cursorRect(win.chat.textCursor()).center()
    texts = [a.text() for a in win._chat_menu(QPoint(5, 5)).actions()]
    assert "Reply" not in texts
    s.say_reply("#skinhead", "plain", "abc")                             # falls back to a normal message
    assert wait(app, lambda: "PRIVMSG #skinhead plain" in srv.received or "PRIVMSG #skinhead :plain" in srv.received)
    win.close(); srv.stop()


def test_clienttagdeny_rules():
    from bchat.session import Session
    s = Session.__new__(Session)
    s._cap_active, s.state = {"message-tags"}, "connected"
    for deny, typing, reply in (("", True, True), ("*", False, False), ("*,-typing", True, False),
                                ("draft/reply", True, False), ("*,-draft/reply,-typing", True, True)):
        s.client_tag_deny = deny
        assert (s.client_tag_ok("+typing"), s.client_tag_ok("+draft/reply")) == (typing, reply), deny


def test_double_click_in_nick_list_opens_a_private_chat(app, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.select_buffer(b)
    assert win.cfg.ul_double == "QUERY %s"
    names = [u.nick for u in win.userlist.model().users]
    i = names.index("Wira")
    rect = win.userlist.visualRect(win.userlist.model().index(i))
    QTest.mouseClick(win.userlist.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(win.userlist.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert wait(app, lambda: win.buf is not None and win.buf.name == "Wira" and win.buf.kind == "query")
    assert not any(x.startswith("WHOIS Wira") for x in srv.received)    # opens the chat, no whois sent
    win.close(); srv.stop()


def test_old_xchat_default_switches_once_custom_stays(tmp_path):
    import json
    from bchat import config
    for old, want in (("QUOTE WHOIS %s %s", "QUERY %s"), ("msg %s hi", "msg %s hi")):
        (tmp_path / "config.json").write_text(json.dumps({"nick": "a", "ul_double": old}), encoding="utf-8")
        cfg = config.load(tmp_path)
        assert cfg.ul_double == want and cfg.ul_double_mirc
    (tmp_path / "config.json").write_text(json.dumps({"nick": "a", "ul_double": "QUOTE WHOIS %s %s", "ul_double_mirc": True}),
                                          encoding="utf-8")
    assert config.load(tmp_path).ul_double == "QUOTE WHOIS %s %s"      # chose it back later: never switched again
