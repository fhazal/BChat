"""Daily comfort: the invite bar (never joins by itself), BChat's paste window, rejoin after a kick, WHOIS on a new query."""
import time

from fake_ircd import FakeIrcd

from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow
from bchat.pastedialog import PasteDialog, send_seconds
from bchat.protocol import lower


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def live(app, tmp_path, **cfg):
    srv = FakeIrcd()
    net = NetworkConfig("SkinIRC", [Server("127.0.0.1", srv.port, False)], autojoin="#skinhead")
    win = MainWindow(Config(nick="Badaboom", nick2="b2", networks=[net], skip_network_list=True, welcome_done=True, **cfg), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers and s.buffers["#skinhead"].joined)
    return srv, win, s


def test_invite_shows_a_bar_and_joins_only_on_click(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    bar = win.invite_bar
    assert not bar.isVisible()
    srv.send(":Belon!b@h INVITE Badaboom :#quiz")
    assert wait(app, bar.isVisible)
    assert "Belon" in bar.text.text() and "#quiz" in bar.text.text() and "SkinIRC" in bar.text.text()
    wait(app, lambda: False, 300)
    assert not any(x.startswith("JOIN #quiz") for x in srv.received)          # nothing joins by itself
    srv.send(":Evil!e@h INVITE Badaboom :#<b>x</b>")                           # names are text, never markup
    assert wait(app, lambda: "&lt;b&gt;" in bar.text.text() and "1 more" in bar.text.text())
    bar.ignore_btn.click()                                                      # forgets the newest, nothing sent
    assert "#quiz" in bar.text.text() and bar.isVisible()
    assert not any("<b>" in x for x in srv.received)
    bar.join_btn.click()
    assert wait(app, lambda: "#quiz" in s.buffers and s.buffers["#quiz"].joined)
    assert wait(app, lambda: win.buf is s.buffers["#quiz"])
    assert not bar.isVisible()
    srv.send(":Belon!b@h INVITE Badaboom :#quiz")                               # already in: no bar
    wait(app, lambda: False, 300)
    assert not bar.isVisible()
    win.close(); srv.stop()


def test_paste_window_previews_and_sends_lines_or_one_line(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    win.skip_quit_prompt = False
    text = "\n".join(f"line {i}" for i in range(1, 13))
    win.paste_lines(text)
    d = win.paste_dialog
    assert isinstance(d, PasteDialog) and d.isVisible()
    assert d.head.text() == "Send 12 lines to #skinhead?"
    assert d.preview.toPlainText().startswith("line 1\nline 2") and "8 more lines" in d.preview.toPlainText()
    assert f"About {send_seconds(text.splitlines())} seconds" in d.note.text()
    assert d.lines_btn.isDefault()
    d.cancel_btn.click()
    wait(app, lambda: False, 300)
    assert not any("line 1" in x for x in srv.received)
    win.paste_lines(text)
    win.paste_dialog.one_btn.click()
    assert wait(app, lambda: any(x == "PRIVMSG #skinhead :" + " ".join(f"line {i}" for i in range(1, 13)) for x in srv.received))
    win.paste_lines(text)
    win.paste_dialog.lines_btn.click()
    assert wait(app, lambda: any(x == "PRIVMSG #skinhead :line 3" for x in srv.received), 8000)
    win.skip_quit_prompt = True
    win.close(); srv.stop()


def test_short_paste_has_no_question_and_timing_is_honest():
    assert send_seconds(["hi"] * 3) == 0
    assert send_seconds(["x" * 10] * 12) == 14


def test_rejoin_after_kick_once_when_asked(app, tmp_path):
    srv, win, s = live(app, tmp_path, rejoin_on_kick=True)
    b = s.buffers["#skinhead"]
    srv.received.clear()
    srv.send(":Fhazal!f@h KICK #skinhead Badaboom :behave")
    assert wait(app, lambda: not b.joined)
    assert wait(app, lambda: "JOIN #skinhead" in srv.received, 6000)
    assert wait(app, lambda: b.joined)
    srv.received.clear()
    srv.send(":Fhazal!f@h KICK #skinhead Badaboom :again")                     # a second kick soon after: no loop
    wait(app, lambda: False, 4000)
    assert "JOIN #skinhead" not in srv.received and not b.joined
    win.close(); srv.stop()


def test_no_rejoin_after_kick_by_default(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    srv.received.clear()
    srv.send(":Fhazal!f@h KICK #skinhead Badaboom :behave")
    wait(app, lambda: False, 3600)
    assert "JOIN #skinhead" not in srv.received
    win.close(); srv.stop()


def test_whois_at_the_top_of_a_new_private_chat(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    srv.send(":Rock!r@h PRIVMSG Badaboom :hello can anybody help me")
    assert wait(app, lambda: lower("Rock") in s.buffers)
    assert wait(app, lambda: "WHOIS Rock Rock" in srv.received)
    q = s.buffers[lower("Rock")]
    assert wait(app, lambda: any("Oracle eggdrop" in l.text for l in q.lines))     # the fake server's WHOIS reply
    n = srv.received.count("WHOIS Rock Rock")
    srv.send(":Rock!r@h PRIVMSG Badaboom :again")                                  # an open chat: no second WHOIS
    wait(app, lambda: False, 300)
    assert srv.received.count("WHOIS Rock Rock") == n
    win.close(); srv.stop()


def test_whois_on_query_can_be_turned_off(app, tmp_path):
    srv, win, s = live(app, tmp_path, whois_on_query=False)
    srv.send(":Rock!r@h PRIVMSG Badaboom :hello")
    assert wait(app, lambda: lower("Rock") in s.buffers)
    wait(app, lambda: False, 300)
    assert not any(x.startswith("WHOIS Rock") for x in srv.received)
    win.close(); srv.stop()


def test_lag_is_measured_right_after_login(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    assert any(x.startswith("PING :LAG") for x in srv.received)          # no 15 s wait for the first reading
    assert wait(app, lambda: s.lag_ms is not None, 3000)
    win.close(); srv.stop()


def test_add_to_friends_asks_like_xchat_and_says_what_happened(app, tmp_path):
    from bchat.frienddialog import FriendDialog, nets_from_text
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    d = win.ask_friend("Overwatch")
    assert isinstance(d, FriendDialog) and d.isVisible()
    assert d.nick.text() == "Overwatch" and d.nets.text() == "ALL" and d.ok_btn.isDefault()
    d.ok_btn.click()
    assert wait(app, lambda: "Overwatch" in win.cfg.friends)
    assert win.cfg.friend_nets.get("Overwatch", "") == ""                       # ALL = every network
    assert any("Overwatch added to your Friends List (all networks)" in l.text for l in b.lines)
    assert wait(app, lambda: any("Overwatch" in x and x.startswith(("ISON", "MONITOR")) for x in srv.received))
    d = win.ask_friend("overwatch")
    d.ok_btn.click()
    assert wait(app, lambda: any("overwatch is already in your Friends List" in l.text for l in b.lines))
    assert [n.lower() for n in win.cfg.friends].count("overwatch") == 1
    d = win.ask_friend("Belon", "SkinIRC, OFTC")
    d.cancel_btn.click()
    assert "Belon" not in win.cfg.friends                                       # Cancel adds nothing
    assert nets_from_text("all") == "" and nets_from_text(" SkinIRC ,OFTC,") == "SkinIRC, OFTC"
    win.close(); srv.stop()


def test_notify_command_adds_and_removes(app, tmp_path):
    from bchat import commands
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    commands.run(win, s, b, "/notify Belon SkinIRC")
    assert "Belon" in win.cfg.friends and win.cfg.friend_nets["Belon"] == "SkinIRC"
    commands.run(win, s, b, "/notify belon")
    assert "Belon" not in win.cfg.friends and "Belon" not in win.cfg.friend_nets
    assert any("taken off your Friends List" in l.text for l in b.lines)
    win.close(); srv.stop()
