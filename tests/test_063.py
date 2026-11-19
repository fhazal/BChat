"""BR-5: BChat was closed while stuck after the server restarted; the report said 'Crashed' with a survived Windows
error and lost where it was stuck. And: behind ZNC, a server that went down left everyone online, ourselves as op."""
import json
import time

from fake_ircd import FakeIrcd

from bchat import reports
from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow

ZNC = "*status!znc@{}".format("znc.in")          # ZNC's own status sender

SURVIVED = 'Windows fatal exception: code 0x8001010d\n\nStack (most recent call first):\n  File "bchat\\__main__.py", line 214 in main\n'
FATAL = 'Windows fatal exception: access violation\n\nStack (most recent call first):\n  File "bchat/chatview.py", line 9 in paint\n'


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_survived_windows_errors_are_not_a_crash(tmp_path):
    assert reports.real_crash(SURVIVED) == ""
    assert reports.real_crash(SURVIVED * 3) == ""
    both = reports.real_crash(SURVIVED + "\n" + FATAL + SURVIVED)
    assert "access violation" in both and "0x8001010d" not in both and "chatview.py" in both
    (tmp_path / "crash.log").write_text(SURVIVED)
    c = reports.CrashFile(tmp_path)
    assert c.previous == ""
    c.close()


def test_a_freeze_wins_over_the_crash_file(tmp_path):
    (tmp_path / "crash.log").write_text(FATAL)
    (tmp_path / "freeze.json").write_text(json.dumps({"seconds": 31, "stack": 'File "bchat/session.py", line 5 in _irc_mode'}))
    c = reports.CrashFile(tmp_path)
    headline, kind, error, sig, secs = reports.last_run_problem(c, tmp_path)
    assert kind == "Slow" and secs == 31 and "_irc_mode" in error and sig
    c.close()
    (tmp_path / "crash.log").write_text(FATAL)
    c = reports.CrashFile(tmp_path)
    assert reports.last_run_problem(c, tmp_path)[1] == "Crashed"     # no freeze left: the crash as before
    c.close()
    assert reports.last_run_problem(reports.CrashFile(tmp_path), tmp_path) is None


def live(app, tmp_path):
    srv = FakeIrcd()
    net = NetworkConfig("ZNC-Test", [Server("127.0.0.1", srv.port, False)], autojoin="#skinhead")
    win = MainWindow(Config(nick="Badaboom", nick2="b2", networks=[net], skip_network_list=True, welcome_done=True), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers and s.buffers["#skinhead"].joined and len(s.buffers["#skinhead"].users) > 3)
    return srv, win, s


def test_znc_losing_the_server_keeps_the_channels_and_its_rejoin_refreshes_them(app, tmp_path):
    # 0.8.5: a bouncer is a normal server. ZNC losing IRC changes nothing here; its own JOIN on the way back
    # brings the fresh names list
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    srv.send(f":{ZNC} PRIVMSG Badaboom :Disconnected from IRC. Reconnecting...")
    wait(app, lambda: False, 400)                                  # time for BChat to read it
    assert b.joined and len(b.users) > 3
    srv.send(":Badaboom!b@h JOIN #skinhead")                       # ZNC is back on IRC and rejoins
    srv.send(":irc.test 353 Badaboom = #skinhead :@Badaboom Belon Fhazal")
    srv.send(":irc.test 366 Badaboom #skinhead :End of /NAMES list.")
    assert wait(app, lambda: b.joined and len(b.users) == 3)
    win.close()


# --- one chat view per tab (slow tab switch: Qt laid the whole tab out again on every switch) -----------------

def pane(app):
    from bchat.chatview import ChatPane
    p = ChatPane(Config(nick="me", max_lines=500))
    p.resize(800, 400)
    p.show()
    return p


def lines(p, b, n, tag="x"):
    from bchat.session import MSG, Line
    for i in range(n):
        ln = Line(MSG, "nick", f"{tag} {i}", time.time())
        b.lines.append(ln)
        p.add_line(b, ln)


def test_each_tab_keeps_its_own_view_and_layout(app):
    from bchat.session import Buffer
    p = pane(app)
    a, b = Buffer(None, "#a", "channel"), Buffer(None, "#b", "channel")
    p.doc_for(a), p.doc_for(b)
    p.show_buffer(a)
    lines(p, a, 50, "a")
    lines(p, b, 30, "b")                                       # a hidden tab still gets its lines
    va, vb = p.view_of(a), p.view_of(b)
    assert va is not vb and p.view() is va
    doc_a = va.document()
    p.show_buffer(b)
    assert p.view() is vb and "b 29" in p.toPlainText() and "a 1" not in p.toPlainText()
    assert a.marker == 49                                      # leaving a tab still sets its marker line
    p.show_buffer(a)
    assert p.view() is va and va.document() is doc_a          # same document: nothing built or laid out again
    assert p.document().defaultFont().family() == va.chat_font.family()


def test_preferences_rebuild_the_shown_tab_now_and_the_rest_when_shown(app):
    from bchat.session import Buffer
    p = pane(app)
    a, b = Buffer(None, "#a", "channel"), Buffer(None, "#b", "channel")
    p.doc_for(a), p.doc_for(b)
    p.show_buffer(b)
    lines(p, a, 5, "a")
    p.show_buffer(a)
    old_b = p.view_of(b).document()
    p.reload_all()
    assert "a 4" in p.toPlainText()                            # the shown tab right away
    lines(p, b, 3, "late")                                     # waits in the buffer, drawn at the rebuild
    p.show_buffer(b)
    assert p.view_of(b).document() is not old_b and "late 2" in p.toPlainText()


def test_a_tab_in_its_own_window_lets_go_of_its_view(app):
    from bchat.session import Buffer
    p = pane(app)
    a = Buffer(None, "#a", "channel")
    p.doc_for(a)
    p.show_buffer(a)
    lines(p, a, 3)
    p.drop(a)
    assert p.view_of(a) is None and p.view() is p._blank
    lines(p, a, 2, "while away")                               # not drawn twice
    p.doc_for(a)
    p.show_buffer(a)
    assert "while away 1" in p.toPlainText() and "x 2" in p.toPlainText()


def test_a_hidden_tab_skips_scrolling_and_shows_its_end(app):
    from bchat.session import Buffer
    p = pane(app)
    a, b = Buffer(None, "#a", "channel"), Buffer(None, "#b", "channel")
    p.doc_for(a), p.doc_for(b)
    p.show_buffer(b)
    p.show_buffer(a)
    assert p.view_of(b).hidden_tab and not p.view_of(a).hidden_tab
    lines(p, b, 900, "hidden")                                 # over Scrollback (500): trimmed while hidden too
    assert p.view_of(b).document().blockCount() <= 500 + 50
    p.show_buffer(b)
    app.processEvents()
    sb = p.view().verticalScrollBar()
    assert not p.view_of(b).hidden_tab and p.view_of(a).hidden_tab
    assert sb.value() == sb.maximum() and "hidden 899" in p.toPlainText()
