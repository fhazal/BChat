"""0.7.0 Everyday commands: what each one sends, saves and shows."""
import time

from fake_ircd import FakeIrcd

from bchat import commands, everyday, tabopts
from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow
from bchat.session import QUERY


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


def sent(app, srv, start, ms=8000):
    assert wait(app, lambda: any(x.startswith(start) for x in srv.received), ms), (start, srv.received[-8:])
    return [x for x in srv.received if x.startswith(start)]


def said(b, text):
    return any(text in ln.text for ln in b.lines)


def test_every_new_command_has_help_and_completes():
    for name in everyday.NAMES:
        assert name in commands.COMMAND_NAMES and commands.HELP.get(name), name


def test_talking(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    commands.run(win, s, b, "/describe Belon waves  hello")
    assert sent(app, srv, "PRIVMSG Belon :\x01ACTION waves  hello\x01")
    assert "belon" not in s.buffers and said(b, "waves  hello")      # no new tab, shown here
    commands.run(win, s, b, "/omsg ops only")
    assert said(b, "can't send a message to the ops only")           # the server didn't say STATUSMSG
    srv.send(":srv 005 Badaboom STATUSMSG=@+ :are supported")
    assert wait(app, lambda: "@" in s.statusmsg)
    commands.run(win, s, b, "/omsg ops only")
    assert sent(app, srv, "PRIVMSG @#skinhead :ops only")
    q1, q2 = s.buffer("Belon"), s.buffer("Fhazal")
    assert q1.kind == QUERY and q2.kind == QUERY
    commands.run(win, s, b, "/qmsg brb  5")
    assert sent(app, srv, "PRIVMSG Belon :brb  5") and sent(app, srv, "PRIVMSG Fhazal :brb  5")
    assert said(b, "Sent to 2 private chats")
    commands.run(win, s, b, "/qme is away")
    assert sent(app, srv, "PRIVMSG Fhazal :\x01ACTION is away\x01")
    assert not any(x.startswith("PRIVMSG #skinhead") for x in srv.received)
    commands.run(win, s, b, "/ctcpreply Belon version BChat 0.7")
    assert sent(app, srv, "NOTICE Belon :\x01VERSION BChat 0.7\x01")
    win.close()


def test_nick_and_name(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    commands.run(win, s, b, "/tnick Temp")
    assert sent(app, srv, "NICK Temp") and win.cfg.nick == "Badaboom"
    commands.run(win, s, b, "/mnick Saved")
    assert sent(app, srv, "NICK Saved") and win.cfg.nick == "Saved"
    commands.run(win, s, b, "/fullname Belon the Bee")
    assert win.cfg.realname == "Belon the Bee" and said(b, "next time you connect")
    s.net.use_global, s.net.nick = False, "OwnNick"                # a network with its own nick keeps it there
    commands.run(win, s, b, "/mnick Other")
    assert s.net.nick == "Other" and win.cfg.nick == "Saved"
    from bchat import config
    assert config.load(tmp_path).realname == "Belon the Bee"         # saved
    win.close()


def test_autojoin_perform_and_join_behind(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    commands.run(win, s, b, "/autojoin #quiz")
    commands.run(win, s, b, "/autojoin secret k3y")
    assert everyday.parse_autojoin(s.net.autojoin) == [("#secret", "k3y"), ("#skinhead", ""), ("#quiz", "")]
    commands.run(win, s, b, "/autojoin -r #skinhead")
    assert [c for c, _k in everyday.parse_autojoin(s.net.autojoin)] == ["#secret", "#quiz"]
    commands.run(win, s, b, "/autojoin -r #nope")
    assert said(b, "isn't on the join list")
    commands.run(win, s, b, "/perform /mode Badaboom +x")
    commands.run(win, s, b, "/perform msg NickServ hi")
    assert s.net.commands == ["mode Badaboom +x", "msg NickServ hi"]
    commands.run(win, s, b, "/perform -r 1")
    assert s.net.commands == ["msg NickServ hi"]
    commands.run(win, s, b, "/perform")
    assert said(b, "1. /msg NickServ hi")
    commands.run(win, s, b, "/join -n #behind")
    assert wait(app, lambda: "#behind" in s.buffers and s.buffers["#behind"].joined)
    wait(app, lambda: False, 200)
    assert win.buf is b                                             # stayed where we were
    commands.run(win, s, b, "/join -x #front")
    assert wait(app, lambda: "#front" in s.buffers and win.buf is s.buffers["#front"])
    win.close()


def test_hop_still_cycles(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    commands.run(win, s, s.buffers["#skinhead"], "/hop")
    assert sent(app, srv, "PART #skinhead") and sent(app, srv, "JOIN #skinhead")
    win.close()


def test_tabs_and_text(app, tmp_path, monkeypatch):
    monkeypatch.setattr(everyday, "documents", lambda: tmp_path / "docs")
    srv, win, s = live(app, tmp_path, log_asked=True)
    b = s.buffers["#skinhead"]
    srv.send(":Belon!b@h PRIVMSG #skinhead :\x0304red\x03 words")
    assert wait(app, lambda: said(b, "red"))
    commands.run(win, s, b, "/savebuf")
    files = list((tmp_path / "docs").glob("SkinIRC-#skinhead-*.txt"))
    assert len(files) == 1 and "<Belon> red words" in files[0].read_text("utf-8")
    commands.run(win, s, b, "/savebuf mine.txt")
    assert (tmp_path / "docs" / "mine.txt").is_file()
    (tmp_path / "docs" / "notes.txt").write_text("line one\nline two\n", "utf-8")
    before = len(srv.received)
    commands.run(win, s, b, "/loadbuf notes.txt")
    assert said(b, "line two") and len(srv.received) == before       # shown, nothing sent
    commands.run(win, s, b, "/strip on")
    assert tabopts.get(win.cfg, b, "strip") and "red" in win.chat.toPlainText()
    commands.run(win, s, b, "/strip")
    assert said(b, "Colours stripped in #skinhead: on")
    commands.run(win, s, b, "/strip off")
    assert not tabopts.has_own(win.cfg, b, "strip")                  # back to what Preferences says
    commands.run(win, s, b, "/timestamp off")
    assert tabopts.get(win.cfg, b, "timestamps") is False
    commands.run(win, s, b, "/log on")
    assert win._log_key(b) in win.cfg.log_tabs
    commands.run(win, s, b, "/log off")
    assert win._log_key(b) not in win.cfg.log_tabs
    commands.run(win, s, b, "/titlebar at work")
    assert win.windowTitle().endswith(" - at work")
    commands.run(win, s, b, "/titlebar")
    assert "at work" not in win.windowTitle()
    other = s.buffer("Belon")
    other.activity, other.unread = 2, 4
    commands.run(win, s, b, "/markasread -a")
    assert other.activity == 0 and other.unread == 0
    commands.run(win, s, b, "/clearall")
    assert not b.lines and not other.lines
    win.close()


def test_lists(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    b.users[s.fold("Belon")].host = "b@" + "home.example"            # user@host, split so it never reads as an email
    commands.run(win, s, b, "/aop Belon #skinhead")
    r = win.cfg.control_rules[-1]
    assert r["who"] == "*!*@home.example" and r["give"] == "@" and r["channels"] == "#skinhead" and r["network"] == "SkinIRC"
    commands.run(win, s, b, "/avoice *!*@x.example")
    assert win.cfg.control_rules[-1]["give"] == "+"
    commands.run(win, s, b, "/avoice Belon!*@*")
    assert said(b, "anyone can take a nick")
    commands.run(win, s, b, "/aop -r Belon")
    assert all(x["give"] != "@" for x in win.cfg.control_rules)
    commands.run(win, s, b, "/aop Nobody")
    assert said(b, "Can't see Nobody")
    commands.run(win, s, b, "/cnick Belon teal")
    assert {"mask": "Belon", "colour": "teal", "net": ""} in win.cfg.nick_colours
    commands.run(win, s, b, "/cnick Belon purple")
    assert said(b, "No colour called purple")
    commands.run(win, s, b, "/cnick Belon -r")
    assert not win.cfg.nick_colours
    w = None
    commands.run(win, s, b, "/abook Belon")
    w = win.tools.get("addressbook")
    assert w is not None and w.isVisible()
    commands.run(win, s, b, "/aop")
    assert win.tools["control"].isVisible()
    win.close()


def test_do_not_disturb_stops_alerts(app, tmp_path, monkeypatch):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    played = []
    monkeypatch.setattr(win, "_play_sound", lambda *a, **k: played.append(a) or True)
    commands.run(win, s, b, "/donotdisturb on")
    assert win.cfg.do_not_disturb
    win._on_notify(b, "hilight")
    assert not played
    commands.run(win, s, b, "/donotdisturb off")
    win._on_notify(b, "hilight")
    assert played
    from PySide6.QtWidgets import QMenu
    menu = QMenu()
    win.fill_tray_menu(menu)
    dnd = next(a for a in menu.actions() if a.text() == "Do not disturb")
    dnd.setChecked(True)
    assert win.cfg.do_not_disturb
    win.close()


def test_play_sends_a_file_paced_and_stops(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    f = tmp_path / "song.txt"
    f.write_text("one\n\ntwo\nthree\nfour\n", "utf-8")
    commands.run(win, s, b, f'/play "{f}" 500')
    assert sent(app, srv, "PRIVMSG #skinhead one")
    assert not any(x.startswith("PRIVMSG #skinhead two") for x in srv.received)   # paced, not all at once
    assert sent(app, srv, "PRIVMSG #skinhead two", 1500)
    commands.run(win, s, b, "/play stop")
    assert s.player is None and said(b, "stopped (2 lines)")
    wait(app, lambda: False, 700)
    assert not any(x.endswith(" three") for x in srv.received)
    commands.run(win, s, b, f'/play -e Belon "{f}"')               # only to you: nothing sent
    assert wait(app, lambda: s.player is None, 9000)
    assert not any(x.startswith("PRIVMSG Belon") for x in srv.received) and said(s.buffers["belon"], "four")
    win.close()


def test_run_asks_before_a_program(app, tmp_path, monkeypatch):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    opened, asked = [], []
    monkeypatch.setattr(everyday, "open_path", lambda p: opened.append(p) or True)
    monkeypatch.setattr(everyday, "confirm_program", lambda ui, p: asked.append(p) or False)
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "tool.exe").write_bytes(b"MZ")
    commands.run(win, s, b, f"/run {tmp_path / 'a.txt'}")
    assert opened and not asked
    commands.run(win, s, b, f"/run {tmp_path / 'tool.exe'}")
    assert len(asked) == 1 and len(opened) == 1 and said(b, "Not started")
    monkeypatch.setattr(everyday, "confirm_program", lambda ui, p: asked.append(p) or True)
    commands.run(win, s, b, f"/run {tmp_path / 'tool.exe'}")
    commands.run(win, s, b, f"/run {tmp_path / 'tool.exe'}")           # asked once only
    assert len(asked) == 2 and len(opened) == 3
    commands.run(win, s, b, "/run nothing-here.txt")
    assert said(b, "No such file or folder")
    win.close()


def test_dns_and_links(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    commands.run(win, s, b, "/dns localhost")                       # no dot: asks the server first
    assert sent(app, srv, "USERHOST localhost")
    srv.send(":srv 302 Badaboom :")                                 # not on IRC: a host name then
    assert wait(app, lambda: said(b, "localhost is ")) and said(b, "isn't on IRC now")
    commands.run(win, s, b, "/dns 127.0.0.1")
    assert wait(app, lambda: said(b, "127.0.0.1 is ") or said(b, "127.0.0.1 has no name"))
    commands.run(win, s, b, "/dns Stranger")
    assert sent(app, srv, "USERHOST Stranger")
    srv.send(":srv 302 Badaboom :Stranger=+s@localhost")
    assert wait(app, lambda: said(b, "Stranger (localhost) is "))
    commands.run(win, s, b, "/links")
    assert sent(app, srv, "LINKS") and said(b, "shows in the SkinIRC tab")
    srv.send(":hub.skin 364 Badaboom leaf.skin hub.skin :1 Leaf server")
    srv.send(":hub.skin 364 Badaboom hub.skin hub.skin :0 Hub server")
    srv.send(":hub.skin 365 Badaboom * :End of /LINKS list.")
    st = s.server_buffer
    assert wait(app, lambda: said(st, "2 servers on SkinIRC."))
    assert said(st, "leaf.skin: 1 hop away, via hub.skin (Leaf server)") and said(st, "hub.skin: the server you're on")
    win.close()


def test_uwho_shows_the_card_and_asks_whois(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    commands.run(win, s, b, "/uwho Belon")
    assert sent(app, srv, "WHOIS Belon")
    assert win.uwho_menu.isVisible()
    win.uwho_menu.close()
    win.close()


def test_local_commands_work_without_a_server(app, tmp_path):
    win = MainWindow(Config(nick="Badaboom", skip_network_list=True, welcome_done=True), tmp_path)
    win.skip_quit_prompt = True
    s = win.session_for(NetworkConfig("Empty", []))
    commands.run(win, s, s.server_buffer, "/titlebar hello")
    assert win.title_extra == "hello"
    commands.run(win, s, s.server_buffer, "/donotdisturb on")
    assert win.cfg.do_not_disturb
    win.close()
