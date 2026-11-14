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


def test_znc_losing_the_server_leaves_the_channels(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    srv.send(f":{ZNC} PRIVMSG Badaboom :Disconnected from IRC. Reconnecting...")
    assert wait(app, lambda: not b.joined and not b.users)
    assert any("bouncer lost the IRC server" in ln.text for ln in b.lines)
    assert s.state == "connected"                                   # still talking to ZNC itself
    srv.send(f":{ZNC} PRIVMSG Badaboom :Connection refused. Reconnecting...")
    srv.send(":Badaboom!b@h JOIN #skinhead")                       # ZNC is back on IRC and rejoins
    srv.send(":irc.test 353 Badaboom = #skinhead :@Badaboom Belon Fhazal")
    srv.send(":irc.test 366 Badaboom #skinhead :End of /NAMES list.")
    assert wait(app, lambda: b.joined and len(b.users) == 3)
    win.close()


def test_only_znc_itself_and_only_news_count(app, tmp_path):
    srv, win, s = live(app, tmp_path)
    b = s.buffers["#skinhead"]
    srv.send(":*status!evil@h PRIVMSG Badaboom :Disconnected from IRC. Reconnecting...")   # not ZNC
    srv.send(":Belon!b@h PRIVMSG Badaboom :Disconnected from IRC. Reconnecting...")
    srv.send(f"@time=2020-01-01T00:00:00.000Z :{ZNC} PRIVMSG Badaboom :Disconnected from IRC.")  # old
    srv.send(":Belon!b@h PRIVMSG #skinhead :marker")
    assert wait(app, lambda: any(ln.text == "marker" for ln in b.lines))
    assert b.joined and len(b.users) > 3
    win.close()
