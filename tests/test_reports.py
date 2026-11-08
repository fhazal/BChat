"""0.3.0 problem reports: privacy filter, last steps, crash file, freezes, the windows, and BChat -> receiver ->
Discord end to end on this PC (a fake Discord catches what would be posted)."""
import base64
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from bchat import reports
from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow


def wait(app, cond, ms=5000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@pytest.fixture
def win(app, tmp_path):
    nets = [NetworkConfig("ZNC-Belon-BSN", [Server("znc.bajubesi.org", 5599, True)], autojoin="#skinhead,#chat")]
    w = MainWindow(Config(nick="Belon", nick2="Belon_", username="belonuser", realname="Real Name Here",
                          networks=nets, skip_network_list=True, welcome_done=True), tmp_path)
    w.skip_quit_prompt = True
    reports.STEPS.items.clear()
    yield w
    w.close()


# --- privacy -------------------------------------------------------------------------------------------------

def test_redactor_hides_names_addresses_paths_and_links(win):
    red = reports.redactor_for(win)
    text = (r'Belon in #skinhead on ZNC-Belon-BSN via znc.bajubesi.org from 161.142.1.2 and fe80::1:2:3, '
            r'mail a@b.com, mask Oracle!o@bot.x, File "C:\Users\Someone\AppData\Local\Programs\BChat\_internal\bchat\mainwindow.py", '
            r'line 3, D:\Music\song.mp3, https://evil.example/a?b=1, Real Name Here, at 01:58:12')
    out = red(text)
    for secret in ("Belon", "#skinhead", "ZNC-Belon-BSN", "znc.bajubesi.org", "161.142", "fe80", "a@b.com", "Oracle!o",
                   "Someone", "Music", "evil.example", "Real Name Here"):
        assert secret not in out, (secret, out)
    assert '"bchat/mainwindow.py", line 3' in out and "01:58:12" in out and "<link>" in out and "<ip>" in out
    assert "#<chan" in out and "<network1>" in out and "<server1>" in out


def test_windows_user_and_pc_name_are_hidden(win, monkeypatch):
    monkeypatch.setenv("USERNAME", "Fhazal99"); monkeypatch.setenv("COMPUTERNAME", "BEAST-PC")
    out = reports.redactor_for(win)("C:/Users/Fhazal99 on BEAST-PC said Fhazal99")
    assert "Fhazal99" not in out and "BEAST-PC" not in out and "<pc>" in out


def test_report_never_has_chat_text_and_steps_are_names_only(app, win):
    reports.command_step("/msg Belon my secret password is hunter2")
    reports.command_step("hello everyone, this is private")
    reports.STEPS.add("Network List > &Connect")
    r = reports.build(win, "Crashed", "it broke while Belon talked", "ValueError: bad", "")
    flat = json.dumps(r)
    assert "hunter2" not in flat and "private" not in flat and "Belon" not in flat
    assert [s for _, s in r["steps"]] == ["typed /msg", "sent a message", "Network List > Connect"]
    assert r["kind"] == "Crashed" and r["bchat"] and r["theme"] == win.cfg.theme.name and "picture" not in r
    text = reports.render(r)
    assert "What happened: Crashed" in text and "Not included in this text: chat text, passwords" in text and "typed /msg" in text
    assert "The picture is different" not in text
    assert "The picture is different" in reports.render(dict(r, picture="iVBORw0KGgo="))   # honest about what a picture shows


def test_fingerprint_groups_the_same_bug_not_line_numbers():
    a = 'Traceback:\n  File "x/bchat/mainwindow.py", line 1532, in slap\nAttributeError: no name'
    b = 'Traceback:\n  File "y/bchat/mainwindow.py", line 1600, in slap\nAttributeError: other text'
    c = 'Traceback:\n  File "y/bchat/session.py", line 3, in send\nAttributeError: x'
    fault = 'Fatal Python error: Segmentation fault\n\n  File "C:/b/bchat/chatview.py", line 9 in paint\n'
    assert reports.fingerprint(a) == reports.fingerprint(b) != reports.fingerprint(c)
    assert reports.fingerprint(fault) and reports.fingerprint("") == ""


def test_clicks_become_steps(app, win):
    from bchat.reports import StepWatcher
    sw = StepWatcher()
    app.installEventFilter(sw)
    try:
        b = QPushButton("&Favor", win)
        b.show()
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        assert reports.STEPS.list()[-1][1].endswith("Favor")
    finally:
        app.removeEventFilter(sw)


# --- crash, error, freeze ------------------------------------------------------------------------------------

def test_crash_file_only_counts_real_crashes(tmp_path):
    c = reports.CrashFile(tmp_path)
    assert c.previous == ""
    c.close()
    assert reports.CrashFile(tmp_path).previous == ""          # a clean run leaves nothing to report
    (tmp_path / "crash.log").write_text('Fatal Python error: Segmentation fault\n  File "bchat/chatview.py", line 9 in paint\n')
    again = reports.CrashFile(tmp_path)
    assert "Segmentation fault" in again.previous
    again.close()


def test_error_in_a_click_offers_a_report_once(app, win):
    catcher = reports.ErrorCatcher(win)
    got = []
    catcher.caught.connect(lambda text, sig: got.append(sig))
    try:
        for _ in range(2):
            try:
                raise ValueError("boom")
            except ValueError:
                catcher._hook(*sys.exc_info())
        assert len(got) == 1                     # the same error twice offers once
    finally:
        catcher.close()


def test_freeze_is_noticed_and_offered(app, win, tmp_path):
    dog = reports.Watchdog(tmp_path, win, limit=1.5)
    got = []
    dog.recovered.connect(lambda secs, stack: got.append((secs, stack)))
    try:
        wait(app, lambda: False, 600)
        time.sleep(3.2)                          # the window's thread is stuck
        assert (tmp_path / "freeze.json").exists()
        assert wait(app, lambda: bool(got), 4000)
        secs, stack = got[0]
        assert secs >= 1.5 and "test_freeze_is_noticed" in stack
        assert not (tmp_path / "freeze.json").exists()
    finally:
        dog.stop()


def test_leftover_freeze_from_a_run_that_never_came_back(tmp_path):
    (tmp_path / "freeze.json").write_text(json.dumps({"seconds": 42, "stack": "in paint"}))
    assert reports.leftover_freeze(tmp_path) == (42.0, "in paint")
    assert reports.leftover_freeze(tmp_path) is None


def test_bar_opens_the_report_window_with_the_error(app, win, monkeypatch):
    opened = []
    monkeypatch.setattr(win, "report_problem", lambda **kw: opened.append(kw))
    win.offer_report("BChat closed unexpectedly last time.", "Crashed", "Traceback ...", "abc")
    assert win.report_bar.isVisibleTo(win) and "closed unexpectedly" in win.report_bar.text.text()
    win.report_bar.send_btn.click()
    assert opened == [{"kind": "Crashed", "error": "Traceback ...", "sig": "abc", "freeze": 0.0}] and not win.report_bar.isVisibleTo(win)
    win.cfg.report_offer = False
    win.offer_report("again", "Crashed")
    assert not win.report_bar.isVisibleTo(win)               # switched off in Preferences: no bar at all


# --- end to end: BChat -> receiver -> fake Discord -----------------------------------------------------------

class FakeDiscord(BaseHTTPRequestHandler):
    posts: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        FakeDiscord.posts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    import report_receiver as rr
    FakeDiscord.posts = []
    fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeDiscord)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    hook = tmp_path / "hook"
    hook.write_text(f"http://127.0.0.1:{fake.server_address[1]}/api/webhooks/1/x")
    for k, v in {"BCHAT_RR_DB": str(tmp_path / "r.db"), "BCHAT_RR_PICTURES": str(tmp_path / "pics"),
                 "BCHAT_RR_WEBHOOK_FILE": str(hook), "BCHAT_RR_DISCORD_USER": "111122223333444455"}.items():
        monkeypatch.setenv(k, v)
    srv = rr.serve(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown(); fake.shutdown()


def test_report_reaches_receiver_and_discord(app, win, receiver, tmp_path):
    from bchat.reportwindow import ReportDialog, ThanksDialog
    srv, base = receiver
    d = ReportDialog(win, "Crashed", 'File "x/bchat/mainwindow.py", line 3, in slap\nAttributeError: no', "")
    d.wrote.setText("clicked Slap! on Belon, see https://evil.example @everyone")
    shown = []
    ThanksDialog.exec = lambda self: shown.append(self.words.text()) or 0
    orig = reports.Sender.__init__
    reports.Sender.__init__ = lambda self, w, url="": orig(self, w, base + "/bchat/report")
    try:
        d.send()
        assert wait(app, lambda: bool(shown), 8000), d.status.text()
    finally:
        reports.Sender.__init__ = orig
    assert "BR-1" in shown[0] and "first to report" in shown[0]
    assert win.cfg.my_reports[-1]["id"] == "BR-1" and win.cfg.my_reports[-1]["kind"] == "Crashed"
    assert wait(app, lambda: bool(FakeDiscord.posts), 5000)
    post = FakeDiscord.posts[0]
    assert post["content"].startswith("<@111122223333444455> 🐞 **BR-1 · Crashed**")
    assert post["allowed_mentions"] == {"users": ["111122223333444455"]}       # nobody else can ever be pinged
    flat = json.dumps(post)
    assert "Belon" not in flat and "evil.example" not in flat                    # BChat hid them before sending
    assert "```" in post["embeds"][0]["description"]                             # user text shown as plain text only
    row = srv.store.db.execute("SELECT who, sig, kind FROM reports").fetchone()
    assert len(row[0]) == 16 and "127.0.0.1" not in row[0] and row[2] == "Crashed"   # no address stored


def test_same_bug_from_others_counts_and_wave_alarm(app, receiver):
    import urllib.request
    srv, base = receiver
    body = {"v": 1, "kind": "Crashed", "bchat": "0.3.0", "sig": "abcdef123456", "steps": [], "error": "x"}
    answers = []
    for i in range(5):
        req = urllib.request.Request(base + "/bchat/report", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Real-IP": f"10.0.0.{i}"})
        answers.append(json.load(urllib.request.urlopen(req)))
    assert [a["id"] for a in answers] == [f"BR-{i}" for i in range(1, 6)]
    assert answers[0]["seen"] == 1
    assert wait(app, lambda: any("Crash wave" in p.get("content", "") for p in FakeDiscord.posts), 5000)


def test_receiver_refuses_junk_floods_and_outsiders(app, receiver):
    import urllib.error
    import urllib.request
    srv, base = receiver

    def post(data, headers=None):
        req = urllib.request.Request(base + "/bchat/report", data=data, method="POST", headers=headers or {})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code
    assert post(b"not json") == 400
    assert post(json.dumps({"v": 1, "kind": "Hacked", "bchat": "x"}).encode()) == 400
    bad_pic = {"v": 1, "kind": "Slow", "bchat": "0.3.0", "picture": base64.b64encode(b"MZ not a png").decode()}
    assert post(json.dumps(bad_pic).encode()) == 400
    ok = json.dumps({"v": 1, "kind": "Slow", "bchat": "0.3.0"}).encode()
    codes = [post(ok) for _ in range(12)]
    assert codes.count(200) == 7 and codes[-1] == 429      # 10 an hour from one place, and the 3 junk ones count too
    with pytest.raises(urllib.error.HTTPError):                               # the list is only for Buzz, inside
        urllib.request.urlopen(urllib.request.Request(base + "/bchat/new", headers={"X-Real-IP": "8.8.8.8"}))
    new = json.load(urllib.request.urlopen(base + "/bchat/new?after=0"))
    assert len(new["reports"]) == 7 and new["reports"][0]["id"] == "BR-1"


def test_offline_report_is_kept_and_sent_later(app, win):
    s = reports.Sender(win, "http://127.0.0.1:9/never")
    why = []
    s.failed.connect(why.append)
    s.send({"v": 1, "kind": "Slow", "bchat": "0.3.0"})
    assert wait(app, lambda: bool(why), 25000)
    assert "saved" in why[0] and len(list((win.cfg_dir / "reports" / "pending").glob("*.json"))) == 1


def test_update_window_names_the_users_fixed_report(app, win):
    import bchat.updater as up
    from bchat.updatewindow import UpdateDialog
    win.cfg.my_reports = [{"id": "BR-42", "sig": "x", "kind": "Crashed", "date": "2026-11-09"}]
    u = win.updater
    u.current, u.entry = "0.3.0", {"version": "0.3.1", "notes": ["Slap! fixed"], "fixes": ["BR-41", "BR-42"]}
    u._set(up.AVAILABLE)
    d = UpdateDialog(win, u)
    d.sync()
    assert d.fixed.isVisibleTo(d) and "BR-42" in d.fixed.text() and "BR-41" not in d.fixed.text()
    u.entry = {"version": "0.3.1", "fixes": ["BR-7"]}
    d.sync()
    assert not d.fixed.isVisibleTo(d)


def test_internal_listener_for_buzz_shares_the_reports(app, receiver):
    import urllib.request
    import report_receiver as rr
    srv, base = receiver
    inner = rr.internal_listener(srv, "127.0.0.1:0")
    try:
        body = json.dumps({"v": 1, "kind": "Slow", "bchat": "0.3.0"}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/bchat/report", data=body, method="POST")).read()
        got = json.load(urllib.request.urlopen(f"http://127.0.0.1:{inner.server_address[1]}/bchat/new?after=0"))
        assert [r["id"] for r in got["reports"]] == ["BR-1"]
        assert rr.internal_listener(srv, "") is None and rr.internal_listener(srv, "10.255.255.1:1") is None   # no tunnel: no crash
    finally:
        inner.shutdown()
