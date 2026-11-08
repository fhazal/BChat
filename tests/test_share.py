"""/sysinfo and /np: what they send, and that /np never shares anything the user didn't allow."""
import time

from fake_ircd import FakeIrcd

from bchat import commands, nowplaying, sysinfo
from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow
from bchat.nowplaying import Track


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
    return srv, win, s, s.buffers["#skinhead"]


# --- /sysinfo ------------------------------------------------------------------------------

def test_sysinfo_reads_this_pc_and_never_names_it():
    import getpass, os, socket
    info = sysinfo.collect("0.2.0-TEST30")
    assert info["os"].startswith("Windows") and "bit" in info["os"]
    assert " GB" in info["ram"] and "free of" in info["ram"] and "free of" in info["disks"]
    assert info["cpu"] != "?" and info["uptime"].endswith("m") and info["bchat"] == "0.2.0-TEST30"
    line = sysinfo.render(sysinfo.DEFAULT_LINE, info)
    for secret in (socket.gethostname(), getpass.getuser(), os.environ.get("COMPUTERNAME", "")):
        assert not secret or secret.lower() not in line.lower()
    assert "\x02OS\x02 Windows" in line and "\x02Uptime\x02" in line and "\x0314BChat 0.2.0-TEST30\x03" in line
    assert "Screen" not in line and "Audio" not in line


def test_sysinfo_template_and_command(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, sysinfo_line="CPU {cpu} · Uptime {uptime}")
    commands.run(win, s, b, "/sysinfo -e")
    assert any(l.text.startswith("\x02CPU\x02") for l in b.lines)
    assert not any("PRIVMSG #skinhead" in x for x in srv.received)              # -e: only to you
    commands.run(win, s, b, "/sysinfo")
    assert wait(app, lambda: any(x.startswith("PRIVMSG #skinhead :\x02CPU\x02") and "Uptime" in x for x in srv.received))
    win.close(); srv.stop()


# --- /np -----------------------------------------------------------------------------------

APPLE = "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"
CHROME = "Chrome"


def song(app_id=APPLE, artist="MIKA — Life In Cartoon Motion", title="Relax, Take It Easy", music=True, pos=72, length=238):
    return Track(app_id, nowplaying.player_name(app_id), artist, title, "", music, pos, length)


def test_apple_music_artist_and_album_are_split_and_the_line_is_tidy():
    t = nowplaying.tidy(song())
    assert (t.artist, t.album, t.player) == ("MIKA", "Life In Cartoon Motion", "Apple Music")
    line = nowplaying.render(nowplaying.DEFAULT_LINE, t)
    assert line == "is listening to \x02MIKA\x02 – \x02Relax, Take It Easy\x02 (Life In Cartoon Motion) · Apple Music · 1:12 / 3:58"
    single = nowplaying.tidy(song(artist="drSNpro — Cinta", title="Cinta", pos=0, length=0))
    assert nowplaying.render(nowplaying.DEFAULT_LINE, single) == "is listening to \x02drSNpro\x02 – \x02Cinta\x02 · Apple Music"


def test_np_rules_off_music_only_players():
    class C:
        np_players, np_names, np_music_only = {}, {}, True
    t, why = nowplaying.choose([], C)
    assert t is None and "Nothing is playing" in why
    t, why = nowplaying.choose([song(CHROME, "Some", "Private video", music=False)], C)
    assert t is None and C.np_players[CHROME] is False and "isn't ticked" in why       # browsers start unticked
    C.np_players[CHROME] = True
    t, why = nowplaying.choose([song(CHROME, "Some", "Private video", music=False)], C)
    assert t is None and "only thing playing is a video" in why
    t, why = nowplaying.choose([song(CHROME, "a", "v", music=False), nowplaying.tidy(song())], C)
    assert t.player == "Apple Music" and C.np_players[APPLE] is True and C.np_names[APPLE] == "Apple Music"


def test_np_is_off_until_turned_on(app, tmp_path):
    srv, win, s, b = live(app, tmp_path)
    win.np_reader = lambda: [nowplaying.tidy(song())]
    commands.run(win, s, b, "/np")
    assert any("Now playing is off" in l.text for l in b.lines)
    wait(app, lambda: False, 300)
    assert not any("ACTION" in x for x in srv.received)
    win.close(); srv.stop()


def test_np_shows_the_line_first_then_sends_as_an_action(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, np_enabled=True)
    win.np_reader = lambda: [nowplaying.tidy(song())]
    commands.run(win, s, b, "/np")
    assert wait(app, lambda: getattr(win, "np_dialog", None) is not None and win.np_dialog.isVisible())
    d = win.np_dialog
    assert d.head.text() == "Send this to #skinhead?" and "MIKA – Relax, Take It Easy" in d.line.text()
    assert not any("ACTION" in x for x in srv.received)                         # nothing before Send
    d.cancel_btn.click()
    wait(app, lambda: False, 300)
    assert not any("ACTION" in x for x in srv.received)
    win.np_dialog = None
    commands.run(win, s, b, "/np")
    assert wait(app, lambda: win.np_dialog is not None and win.np_dialog.isVisible())
    win.np_dialog.again.setChecked(True)
    win.np_dialog.send_btn.click()
    assert wait(app, lambda: any(x.startswith("PRIVMSG #skinhead :\x01ACTION is listening to") for x in srv.received))
    assert win.cfg.np_ask is False                                              # Don't ask again
    win.close(); srv.stop()


def test_np_only_to_me_and_video_is_never_sent(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, np_enabled=True, np_ask=False, np_players={CHROME: True})
    win.np_reader = lambda: [song(CHROME, "x", "my private video", music=False)]
    commands.run(win, s, b, "/np")
    assert wait(app, lambda: any("only thing playing is a video" in l.text for l in b.lines))
    win.np_reader = lambda: [nowplaying.tidy(song())]
    commands.run(win, s, b, "/np -e")
    assert wait(app, lambda: any("is listening to" in l.text for l in b.lines))
    wait(app, lambda: False, 300)
    assert not any("ACTION" in x or "private video" in x for x in srv.received)
    win.close(); srv.stop()


def test_winamp_window_title_is_read(monkeypatch):
    import ctypes

    class U:
        def FindWindowW(self, cls, name): return 1 if cls == "Winamp v1.x" else 0
        def GetWindowTextLengthW(self, h): return 64
        def GetWindowTextW(self, h, buf, n): buf.value = "12. Nujabes - Aruarian Dance - Winamp"
    monkeypatch.setattr(ctypes.windll, "user32", U(), raising=False)
    [t] = nowplaying._winamp()
    assert (t.player, t.artist, t.title, t.music) == ("Winamp", "Nujabes", "Aruarian Dance", True)


# --- 0.2.0: live time, announce each new song, right-click Share ---------------------------

def test_the_clock_moves_on_while_the_preview_is_open():
    t = nowplaying.tidy(song(pos=20, length=201))
    assert nowplaying.at(t, 7).position == 27 and nowplaying.at(t, 500).position == 201       # never past the end
    assert nowplaying.at(song(pos=0, length=0), 9).position == 0                                # no time: stays
    assert "0:27 / 3:21" in nowplaying.render(nowplaying.DEFAULT_LINE, nowplaying.at(t, 7))


def test_send_sends_the_time_as_it_is_when_pressed(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, np_enabled=True)
    win.np_reader = lambda: [nowplaying.tidy(song(pos=20, length=201))]
    commands.run(win, s, b, "/np")
    assert wait(app, lambda: getattr(win, "np_dialog", None) is not None and win.np_dialog.isVisible())
    d = win.np_dialog
    assert "0:20 / 3:21" in d.line.text()
    wait(app, lambda: "0:21 / 3:21" in d.line.text(), 2500)
    assert "0:21 / 3:21" in d.line.text()                                   # counts while open
    d.send_btn.click()
    assert wait(app, lambda: any("ACTION is listening to" in x for x in srv.received))
    sent = next(x for x in srv.received if "ACTION is listening to" in x)
    assert "0:20 / 3:21" not in sent and "/ 3:21" in sent
    win.close(); srv.stop()


class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now


def announcer(**over):
    cfg = Config(np_enabled=True, np_announce=True, np_announce_in="#chat", **over)
    posted = []
    a = nowplaying.Announcer(cfg, posted.append)
    a.clock = Clock()
    return a, posted


def step(a, tracks, seconds):
    a.clock.now += seconds
    a._seen(tracks)


def test_announce_waits_5_seconds_and_posts_each_song_once(app):
    a, posted = announcer()
    mika, other = [nowplaying.tidy(song())], [nowplaying.tidy(song(title="Grace Kelly"))]
    step(a, mika, 0); step(a, mika, 2)
    assert posted == []                                                    # 2 s: not yet
    step(a, mika, 3.5)
    assert [t.title for t in posted] == ["Relax, Take It Easy"] and posted[0].position == 0   # length only, no "0:05 /"
    step(a, mika, 2); step(a, [], 2); step(a, mika, 2); step(a, mika, 6)    # paused and resumed: not again
    assert len(posted) == 1
    step(a, other, 2); step(a, mika, 2); step(a, mika, 1)                  # skipped after 2 s: never sent
    assert len(posted) == 1
    step(a, other, 2); step(a, other, 5)
    assert [t.title for t in posted] == ["Relax, Take It Easy", "Grace Kelly"]


def test_announce_keeps_the_np_rules_and_is_off_by_default(app):
    assert Config().np_announce is False and Config().np_announce_in == ""
    a, posted = announcer(np_players={CHROME: True})
    video = [song(CHROME, "x", "my private video", music=False)]
    step(a, video, 0); step(a, video, 10)
    assert posted == []                                                    # music only
    for off in ({"np_enabled": False}, {"np_announce": False}, {"np_announce_in": " , "}):
        a, posted = announcer()
        for k, v in off.items():
            setattr(a.cfg, k, v)
        a.refresh()
        assert not a.timer.isActive()
        step(a, [nowplaying.tidy(song())], 0); step(a, [nowplaying.tidy(song())], 10)
        assert posted == []
    a, _ = announcer()
    a.refresh()
    assert a.timer.isActive()
    assert nowplaying.announce_channels("#chat, #Skinhead  #chat,#x") == ["#chat", "#Skinhead", "#x"]


def test_announce_posts_only_in_the_listed_joined_channels(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, np_enabled=True, np_announce=True, np_announce_in="#SKINHEAD, #notjoined")
    commands.run(win, s, b, "/join #other")
    assert wait(app, lambda: "#other" in s.buffers and s.buffers["#other"].joined)
    win._announce(nowplaying.tidy(song()))
    assert wait(app, lambda: any(x.startswith("PRIVMSG #skinhead :\x01ACTION is listening to") for x in srv.received))
    wait(app, lambda: False, 300)
    assert not any("#other" in x and "ACTION" in x for x in srv.received)
    assert not any("#notjoined" in x for x in srv.received)
    assert "3:58" in next(x for x in srv.received if "ACTION" in x)
    win.close(); srv.stop()


def test_right_click_share_menu(app, tmp_path):
    from PySide6.QtCore import QPoint
    srv, win, s, b = live(app, tmp_path)
    win.np_reader = lambda: [nowplaying.tidy(song())]

    def share():
        menu = win._chat_menu(QPoint(1, 1), win.chat, b)
        return next(a.menu() for a in menu.actions() if a.text() == "Share")
    m = share()
    names = [a.text() for a in m.actions() if not a.isSeparator()]
    assert names == ["System Info", "Now Playing", "Announce Songs Here"]
    ann = m.actions()[-1]
    assert not ann.isEnabled() and not ann.isChecked()                      # /np off: can't announce
    m.actions()[1].trigger()
    assert any("Now playing is off" in l.text for l in b.lines)
    m.actions()[0].trigger()
    assert wait(app, lambda: any(x.startswith("PRIVMSG #skinhead :") and "Uptime" in x for x in srv.received))
    win.cfg.np_enabled = True
    ann = share().actions()[-1]
    assert ann.isEnabled()
    ann.trigger()
    assert win.cfg.np_announce and win.cfg.np_announce_in == "SkinIRC/#skinhead" and win.announcer.timer.isActive()
    assert any("Announcing new songs in #skinhead" in l.text for l in b.lines)
    ann = share().actions()[-1]
    assert ann.isChecked()
    ann.trigger()
    assert win.cfg.np_announce_in == "" and not win.announcer.timer.isActive()
    win.close(); srv.stop()


def test_now_playing_has_its_own_page_with_the_announce_list(app, tmp_path):
    from bchat.preferences import CATEGORIES, PreferencesDialog
    assert CATEGORIES["Chatting"].index("Now Playing") == CATEGORIES["Chatting"].index("Advanced") - 1
    win = MainWindow(Config(nick="T", skip_network_list=True, welcome_done=True, np_enabled=True,
                            np_announce_in="ZNC-Belon-BSN/#skinhead, #chat, ZNC-Fhazal-SKN/#help"), tmp_path)
    win.skip_quit_prompt = True
    d = PreferencesDialog(win, "Now Playing")
    assert d.pages.currentWidget().isAncestorOf(d.np_on) and d.pages.currentWidget().isAncestorOf(d.np_ann_list)
    rows = [(d.np_ann_list.topLevelItem(i).text(0), d.np_ann_list.topLevelItem(i).text(1)) for i in range(d.np_ann_list.topLevelItemCount())]
    assert rows == [("ZNC-Belon-BSN", "#skinhead"), ("Every network", "#chat"), ("ZNC-Fhazal-SKN", "#help")]
    assert not d.np_ann.isChecked() and d.np_ann.isEnabled()
    d.np_ann.setChecked(True)
    d.np_ann_list.setCurrentItem(d.np_ann_list.topLevelItem(1)); d.np_ann_remove.click()
    d.accept()
    assert win.cfg.np_announce and win.cfg.np_announce_in == "ZNC-Belon-BSN/#skinhead, ZNC-Fhazal-SKN/#help"
    win.close()


def test_announce_targets_network_and_channel():
    assert nowplaying.announce_targets("Net A/#x, #y") == [("Net A", "#x"), ("", "#y")]
    text = "ZNC-Belon-BSN/#skinhead, #chat"
    assert nowplaying.announces_in(text, "znc-belon-bsn", "#SKINHEAD")
    assert not nowplaying.announces_in(text, "ZNC-Fhazal-SKN", "#skinhead")        # same channel, other network: no
    assert nowplaying.announces_in(text, "anything", "#chat")                       # old plain entry: every network


def test_announce_skips_the_same_channel_on_another_network(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, np_enabled=True, np_announce=True, np_announce_in="OtherNet/#skinhead")
    win._announce(nowplaying.tidy(song()))
    wait(app, lambda: False, 300)
    assert not any("ACTION" in x for x in srv.received)
    win.cfg.np_announce_in = "SkinIRC/#skinhead"
    win._announce(nowplaying.tidy(song()))
    assert wait(app, lambda: any(x.startswith("PRIVMSG #skinhead :ACTION") for x in srv.received))
    win.close(); srv.stop()


def test_ticking_a_tab_replaces_an_old_every_network_entry(app, tmp_path):
    srv, win, s, b = live(app, tmp_path, np_enabled=True, np_announce=True, np_announce_in="#skinhead, #chat")
    win.announce_here(b, True)
    assert win.cfg.np_announce_in == "#chat, SkinIRC/#skinhead"
    win.announce_here(b, False)
    assert win.cfg.np_announce_in == "#chat"
    win.close(); srv.stop()


def test_dialog_lines_are_soft_in_every_theme():
    from bchat.config import THEME_NAMES, make_theme
    from bchat.widgets import stylesheet
    for name in THEME_NAMES:
        t = make_theme(name)
        assert f'QFrame[frameShape="HLine"] {{ border: none; border-top: 1px solid {t.thumb_hover};' in stylesheet(t), name
