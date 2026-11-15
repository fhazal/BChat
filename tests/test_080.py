"""0.8.0 Popups + Scripts: the Popups window and the five menus, Paste mIRC popups, the Scripts window,
and what scripts get (mIRC events, add_menu_item, pluginprefs)."""
import json
import time

from fake_ircd import FakeIrcd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from bchat import commands, popups
from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow


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
    assert wait(app, lambda: len(s.buffers["#skinhead"].users) > 1)
    return srv, win, s


def sent(app, srv, start, ms=8000):
    assert wait(app, lambda: any(x.startswith(start) for x in srv.received), ms), (start, srv.received[-8:])
    return [x for x in srv.received if x.startswith(start)]


def said(b, text):
    return any(text in ln.text for ln in b.lines)


def texts(menu):
    return [a.text() for a in menu.actions()]


def act(menu, *path):
    """The action at a path of titles: act(menu, "Greet", "Hello")."""
    for name in path:
        a = next(a for a in menu.actions() if a.text() == name)
        menu = a.menu() if a.menu() is not None else menu
    return a


def chat_menu(win, b):
    win.select_buffer(b)
    chat = win.chat.view() if hasattr(win.chat, "view") else win.chat
    return win._chat_menu(QPoint(2, 2), chat, b)


# --- A. Popups -------------------------------------------------------------------------------------------------

def test_popups_window_edits_every_menu_and_saves_rows(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    d = win.open_editor("popups")
    assert d.key == "channel" and d.menus.count() == 5 and d.hint.text().startswith("Your items show under")
    QTest.mouseClick(d.new_btn, Qt.MouseButton.LeftButton)
    d.view.closePersistentEditor(d.view.currentItem(), 0)
    d.view.currentItem().setText(0, "Who is here")
    d.view.currentItem().setText(1, "names $chan")
    d.view.setCurrentItem(None)
    QTest.mouseClick(d.sub_btn, Qt.MouseButton.LeftButton)          # a submenu, then a row inside it
    d.view.closePersistentEditor(d.view.currentItem(), 0)
    d.view.currentItem().setText(0, "Greet")
    QTest.mouseClick(d.new_btn, Qt.MouseButton.LeftButton)
    d.view.closePersistentEditor(d.view.currentItem(), 0)
    d.view.currentItem().setText(0, "Hello")
    d.view.currentItem().setText(1, "say Hello $chan | say bye")
    d.view.setCurrentItem(None)
    QTest.mouseClick(d.sep_btn, Qt.MouseButton.LeftButton)
    assert d.rows() == [["Who is here", "names $chan"], ["SUB", "Greet"], ["Hello", "say Hello $chan | say bye"], ["ENDSUB", ""], ["SEP", ""]]
    assert d.menus.item(0).text() == "Channel  (2)"
    QTest.mouseClick(d.up_btn, Qt.MouseButton.LeftButton)           # the line moves above the submenu
    assert d.rows()[1] == ["SEP", ""]
    QTest.mouseClick(d.down_btn, Qt.MouseButton.LeftButton)
    # another menu keeps its own list
    d.menus.setCurrentRow(1)
    assert d.key == "query" and d.rows() == []
    QTest.mouseClick(d.new_btn, Qt.MouseButton.LeftButton)
    d.view.closePersistentEditor(d.view.currentItem(), 0)
    d.view.currentItem().setText(1, "whois $nick")
    QTest.mouseClick(d.delete_btn, Qt.MouseButton.LeftButton)
    assert d.rows() == []
    d._add_row("Whois", "whois $nick")
    d.menus.setCurrentRow(0)
    assert d.rows()[0] == ["Who is here", "names $chan"]
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    assert win.cfg.popups["channel"][2] == ["Hello", "say Hello $chan | say bye"]
    assert win.cfg.popups["query"] == [["Whois", "whois $nick"]] and "server" not in win.cfg.popups
    # Cancel keeps what was saved
    d = win.open_editor("popups")
    d.view.clear()
    QTest.mouseClick(d.cancel_btn, Qt.MouseButton.LeftButton)
    assert len(win.cfg.popups["channel"]) == 5


def test_your_items_go_under_bchats_own_and_run(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    plain = texts(chat_menu(win, b))
    win.cfg.popups = {"channel": [["Who is here", "names $chan"], ["SUB", "Greet"], ["Hello", "say Hello $chan! | say and $me"], ["ENDSUB", ""]],
                      "query": [["Whois", "whois $nick"]], "server": [["Lusers", "lusers"]]}
    menu = chat_menu(win, b)
    assert texts(menu)[:len(plain)] == plain                        # BChat's own, unchanged
    assert texts(menu)[len(plain)] == "" and texts(menu)[len(plain) + 1:] == ["Who is here", "Greet"]
    act(menu, "Greet", "Hello").trigger()
    assert sent(app, srv, "PRIVMSG #skinhead :Hello #skinhead!")
    s._next_send = 0.0
    assert sent(app, srv, "PRIVMSG #skinhead :and Badaboom")
    act(menu, "Who is here").trigger()
    assert sent(app, srv, "NAMES #skinhead")
    q = s.buffer("Belon")
    act(chat_menu(win, q), "Whois").trigger()
    assert sent(app, srv, "WHOIS Belon")
    act(chat_menu(win, s.server_buffer), "Lusers").trigger()
    assert sent(app, srv, "lusers")
    assert "Whois" not in texts(chat_menu(win, b))                  # each tab kind has its own menu


def test_nick_list_items_keep_xchat_codes_and_learn_dollar_nick(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    win.cfg.ul_popup = [["All", "say all %a"], ["Each", "say hi $nick on $chan"], ["SEP", ""], ["First", "say first $1"]]
    users = [b.users["oracle"], b.users["belon"]]
    menu = win.build_nick_menu(b, users)
    act(menu, "All").trigger()
    assert sent(app, srv, "PRIVMSG #skinhead :all Oracle Belon")
    s._next_send = 0.0
    act(menu, "Each").trigger()
    assert sent(app, srv, "PRIVMSG #skinhead :hi Oracle on #skinhead") and sent(app, srv, "PRIVMSG #skinhead :hi Belon on #skinhead")
    s._next_send = 0.0
    act(menu, "First").trigger()
    assert sent(app, srv, "PRIVMSG #skinhead :first Belon")
    d = win.open_editor("popup")                                   # the old Userlist Popup entry: the Nick list page
    assert d.key == "nicklist" and d.field == "ul_popup" and d.rows()[0] == ["All", "say all %a"]
    d.reject()


def test_commands_menu_shows_only_with_items_before_help(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    titles = lambda: [a.text().replace("&", "") for a in win.menubar_.actions() if a.menu() is not None]
    assert "Commands" not in titles()
    d = win.open_editor("popups")
    d.menus.setCurrentRow(4)
    assert "Commands menu" in d.hint.text()
    d._add_row("Away lunch", "away lunch")
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    assert titles()[titles().index("Commands") + 1] == "Help"
    assert "Commands: Away lunch" in win.named_actions()            # it can have a key, like any menu command
    win.select_buffer(s.buffers["#skinhead"])
    act(win.commands_menu, "Away lunch").trigger()
    assert sent(app, srv, "AWAY lunch")
    win.cfg.popups = {}
    win.lists_changed()
    assert "Commands" not in titles() and win.commands_menu is None


def test_paste_mirc_popups_adds_what_runs_and_lists_the_rest(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    known = popups.known_commands(win)
    found, problems = popups.parse_mirc(
        "Hello:/say Hello $chan!\n"
        "Greet\n"
        ".Hi:say hi $1 | say and $$2-\n"
        ".-\n"
        ".Away:away $?=\"Why?\"\n"
        "-\n"
        "Slap $1:me slaps $1\n"
        "$iif($me isop $chan,Op stuff)\n"
        ".Op:op $1\n"
        "Count:{ inc %n | echo %n }\n"
        "Who:whoami\n"
        "menu nicklist {\n"
        "Whois:whois $$1\n"
        "}\n", known)
    assert found[None] == [["Hello", "say Hello $chan!"], ["SUB", "Greet"], ["Hi", "say hi $1 | say and $2-"], ["SEP", ""],
                           ["ENDSUB", ""], ["SEP", ""]]
    assert found["nicklist"] == [["Whois", "whois $1"]]
    why = dict(problems)
    assert "$?" in why['.Away:away $?="Why?"'] and "plain text" in why["Slap $1:me slaps $1"]
    assert "plain text" in why["$iif($me isop $chan,Op stuff)"] and "left out" in why[".Op:op $1"]
    assert "script block" in why["Count:{ inc %n | echo %n }"] and "isn't a BChat command" in why["Who:whoami"]
    # through the window: the paste adds to the right menus, the rest is listed, nothing is saved until Save
    d = win.open_editor("popups")
    p = d.open_paste()
    p.text.setPlainText("Hello:say hi $chan\nNope:$readini(x)\nmenu nicklist {\nWhois:whois $$1\n}")
    QTest.mouseClick(p.add_btn, Qt.MouseButton.LeftButton)
    report = p.report.toPlainText()
    assert "Added: 1 to Channel, 1 to Nick list" in report and "Nope:$readini(x)" in report
    assert d.rows() == [["Hello", "say hi $chan"]] and d.work["nicklist"][-1] == ["Whois", "whois $1"]
    assert not win.cfg.popups
    QTest.mouseClick(d.save_btn, Qt.MouseButton.LeftButton)
    assert win.cfg.popups["channel"] == [["Hello", "say hi $chan"]] and win.cfg.ul_popup[-1] == ["Whois", "whois $1"]


# --- B. Scripts window -----------------------------------------------------------------------------------------

def test_new_script_from_the_example_runs_and_keeps_its_count(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    w = win.open_tool("scripts")
    assert w.bar.text().startswith("No scripts yet")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("greeter", True)))
    QTest.mouseClick(w.new_btn, Qt.MouseButton.LeftButton)
    path = win.plugins.folder / "greeter.py"
    assert path.exists() and w.path == path and "import bchat" in w.editor.toPlainText()
    assert w.item_for(path).checkState() == Qt.CheckState.Checked and win.plugins.find("greeter")
    commands.run(win, s, b, "/hello Belon")
    assert said(b, "Hello, Belon!")
    menu = chat_menu(win, b)
    act(menu, "Count me").trigger()
    act(menu, "Count me").trigger()
    assert said(b, "Count me: 2")
    assert json.loads((tmp_path / "scriptprefs.json").read_text("utf-8")) == {"greeter": {"count": 2}}
    d = win.open_editor("popups")
    assert "Count me (greeter.py)" in d.scripts_note.text()          # the Popups window says what scripts add
    d.reject()


def test_save_with_a_mistake_keeps_the_old_version_running(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    win.plugins.folder.mkdir(parents=True)
    path = win.plugins.folder / "one.py"
    path.write_text('import bchat\n\ndef hi(w, we, u):\n    bchat.prnt("version one")\n    return bchat.EAT_ALL\n\nbchat.hook_command("hi", hi)\n')
    win.plugins.autoload()
    w = win.open_tool("scripts")
    assert w.select(path)
    w.editor.setPlainText(w.editor.toPlainText().replace("def hi(w, we, u):", "def hi(w, we, u)").replace("one", "two"))
    assert w.windowTitle() or w.dirty()
    QTest.keyClick(w.editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert "version two" in path.read_text() and not w.dirty()                 # saved
    assert w.editor.error_line == 3 and "Line 3" in w.bar.text() and "old version keeps running" in w.bar.text()
    commands.run(win, s, b, "/hi")
    assert said(b, "version one")                                              # still the old one
    # a mistake that only shows when it runs at load: same
    w.editor.setPlainText(w.editor.toPlainText().replace("def hi(w, we, u)", "def hi(w, we, u):") + "nothing_here()\n")
    QTest.mouseClick(w.save_btn, Qt.MouseButton.LeftButton)
    assert w.editor.error_line == 8 and "NameError" in w.bar.text()
    commands.run(win, s, b, "/hi")
    assert sum(ln.text == "version one" for ln in b.lines) == 2
    # fixed: the new version takes over
    w.editor.setPlainText(w.editor.toPlainText().replace("nothing_here()\n", ""))
    QTest.mouseClick(w.save_btn, Qt.MouseButton.LeftButton)
    assert w.editor.error_line == 0 and w.bar.text().startswith("Saved and reloaded")
    commands.run(win, s, b, "/hi")
    assert said(b, "version two") and len(win.plugins.plugins) == 1


def test_untick_stops_a_script_and_it_stays_off_at_start(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    win.plugins.folder.mkdir(parents=True)
    path = win.plugins.folder / "auto.py"
    path.write_text('__module_name__ = "auto"\n')
    win.plugins.autoload()
    w = win.open_tool("scripts")
    w.item_for(path).setCheckState(Qt.CheckState.Unchecked)
    assert not win.plugins.plugins and win.cfg.scripts_off == ["auto.py"] and "stopped" in w.bar.text()
    win.plugins.autoload()
    assert not win.plugins.plugins                                   # not started with BChat either
    w.item_for(path).setCheckState(Qt.CheckState.Checked)
    assert win.plugins.find("auto") and win.cfg.scripts_off == []
    # a script that can't start doesn't get a tick, and says why
    bad = win.plugins.folder / "bad.py"
    bad.write_text("x = (\n")
    w.fill()
    w.item_for(bad).setCheckState(Qt.CheckState.Checked)
    assert w.item_for(bad).checkState() == Qt.CheckState.Unchecked and w.path == bad and w.editor.error_line >= 1


def test_find_wraps_and_unsaved_changes_ask_first(app, tmp_path, monkeypatch):
    srv, win, s = live(app, tmp_path)
    win.plugins.folder.mkdir(parents=True)
    a = win.plugins.folder / "a.py"
    a.write_text("x = 1\ny = 2\nx = 3\n")
    c = win.plugins.folder / "c.py"
    c.write_text("z = 1\n")
    w = win.open_tool("scripts")
    assert w.select(a)
    QTest.keyClick(w.editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert w.find_row.isVisible()
    w.find_box.setText("x =")
    assert w.find_next() and w.editor.textCursor().blockNumber() == 0
    assert w.find_next() and w.editor.textCursor().blockNumber() == 2
    assert w.find_next() and w.editor.textCursor().blockNumber() == 0           # round again
    w.find_box.setText("nope")
    assert not w.find_next() and "isn't in a.py" in w.bar.text()
    w.editor.insertPlainText("# changed\n")
    answers = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *x, **k: answers.pop(0)))
    w.view.setCurrentItem(w.item_for(c))
    assert w.path == a and w.dirty()                                 # Cancel: stays, edit kept
    w.view.setCurrentItem(w.item_for(c))
    assert w.path == c and "# changed" not in a.read_text()          # Don't save


def test_runtime_error_prints_once_with_an_open_in_scripts_link(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    win.plugins.folder.mkdir(parents=True)
    path = win.plugins.folder / "oops.py"
    path.write_text('import bchat\n\ndef go(e):\n    bchat.prnt(e.nick)\n    1 / 0\n\nbchat.on_text(go)\n')
    win.plugins.autoload()
    srv.send(":Belon!b@h PRIVMSG #skinhead :one")
    srv.send(":Belon!b@h PRIVMSG #skinhead :two")
    assert wait(app, lambda: sum(ln.text == "Belon" for ln in b.lines) == 2)
    errs = [ln for ln in s.server_buffer.lines if "ZeroDivisionError" in ln.text]
    assert len(errs) == 1 and "Script oops.py, line 5" in errs[0].text and "bchat-script://oops.py/5" in errs[0].text
    win.select_buffer(s.server_buffer)
    app.processEvents()
    chat = win.chat.view() if hasattr(win.chat, "view") else win.chat
    assert "Open in Scripts" in chat.toPlainText() and "bchat-script://" not in chat.toPlainText()
    from PySide6.QtCore import QUrl
    chat._open_url(QUrl("bchat-script://oops.py/5"))
    w = win.tools["scripts"]
    assert w.isVisible() and w.path == path and w.editor.error_line == 5 and "ZeroDivisionError" in w.bar.text()


# --- C. What scripts get ---------------------------------------------------------------------------------------

EVENTS_SCRIPT = '''
import bchat
got = []
def keep(e):
    got.append((e.event, e.network, e.channel, e.nick, e.text, e.target, e.newnick))
for name in ("text", "action", "notice", "join", "part", "quit", "kick", "nick", "mode", "topic", "invite", "ctcp", "connect", "disconnect"):
    bchat.on(name, keep)
bchat.on_text(lambda e, u: got.append(("userdata", u)), "extra")
'''


def test_mirc_events_reach_scripts(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    path = tmp_path / "ev.py"
    path.write_text(EVENTS_SCRIPT)
    p = win.plugins.load(str(path))
    got = p.api  # the script's globals are not reachable; read them through a hook's function
    keep = next(h.cb for h in p.hooks if h.kind == "event" and h.name == "text")
    got = keep.__globals__["got"]
    for line in (":Belon!b@h PRIVMSG #skinhead :hello all", ":Belon!b@h PRIVMSG Badaboom :psst",
                 ":Belon!b@h PRIVMSG #skinhead :\x01ACTION waves\x01", ":Belon!b@h NOTICE Badaboom :note",
                 ":Belon!b@h PRIVMSG Badaboom :\x01VERSION\x01", ":Kid!k@h JOIN #skinhead", ":Kid!k@h PART #skinhead :later",
                 ":Belon!b@h KICK #skinhead Oracle :bye", ":Belon!b@h NICK Belon2", ":Belon2!b@h MODE #skinhead +m",
                 ":Belon2!b@h TOPIC #skinhead :new topic", ":Belon2!b@h INVITE Badaboom #other", ":Fhazal!f@h QUIT :gone"):
        srv.send(line)
    assert wait(app, lambda: any(g[0] == "quit" for g in got))
    by = {}
    for g in got:
        by.setdefault(g[0], []).append(g)
    assert ("text", "SkinIRC", "#skinhead", "Belon", "hello all", "", "") in by["text"]
    assert ("text", "SkinIRC", "", "Belon", "psst", "", "") in by["text"]          # private: no channel
    assert by["action"][0][4] == "waves" and by["notice"][0][4] == "note" and by["ctcp"][0][4] == "VERSION"
    assert by["join"][0][2:4] == ("#skinhead", "Kid") and by["part"][0][4] == "later"
    assert by["kick"][0][3:6] == ("Belon", "bye", "Oracle") and by["nick"][0][6] == "Belon2"
    assert by["mode"][0][4] == "+m" and by["topic"][0][4] == "new topic" and by["invite"][0][2] == "#other"
    assert by["quit"][0][3:5] == ("Fhazal", "gone") and ("userdata", "extra") in got
    s.disconnect_from_network()
    assert wait(app, lambda: any(g[0] == "disconnect" for g in got))
    srv.welcomed = False                                             # the fake server welcomes once per login
    s.reconnect()
    assert wait(app, lambda: any(g[0] == "connect" for g in got), 8000)


def test_add_menu_item_and_pluginprefs(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    path = tmp_path / "menus.py"
    path.write_text('''
import bchat
def who(e):
    bchat.prnt("picked " + ",".join(e.nicks) + " on " + e.channel + " as " + e.me)
bchat.add_menu_item("Nick list", "Who are they", who)
bchat.add_menu_item("Channel", "Names", "names $chan")
gone = bchat.add_menu_item("Channel", "Gone", "say gone")
bchat.del_menu_item(gone)
bchat.add_menu_item("Menu bar", "Hello bar", "echo hello from the bar")
bchat.set_pluginpref("a", 1)
bchat.set_pluginpref("b", "two")
bchat.del_pluginpref("a")
bchat.prnt("prefs " + ",".join(bchat.list_pluginpref()) + " " + bchat.get_pluginpref("b"))
import bchat as again
bchat.prnt("same api " + str(again is bchat))
''')
    win.plugins.load(str(path))
    assert said(b, "prefs b two") and said(b, "same api True")
    menu = win.build_nick_menu(b, [b.users["oracle"], b.users["belon"]])
    act(menu, "Who are they").trigger()
    assert said(b, "picked Oracle,Belon on #skinhead as Badaboom")
    cm = chat_menu(win, b)
    assert "Names" in texts(cm) and "Gone" not in texts(cm)
    act(cm, "Names").trigger()
    assert sent(app, srv, "NAMES #skinhead")
    act(win.commands_menu, "Hello bar").trigger()
    assert said(b, "hello from the bar")
    import bchat
    assert bchat.full_version()                                      # BChat's own import is untouched
    win.plugins.unload(win.plugins.plugins[0])
    assert "Names" not in texts(chat_menu(win, b)) and win.commands_menu is None
    p = win.plugins.load(str(path))
    assert p.api.get_pluginpref("b") == "two" and p.api.get_pluginpref("a") is None
