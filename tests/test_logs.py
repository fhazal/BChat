"""0.3.0 daily logs + the Logs window."""
import os
import time
from pathlib import Path

from fake_ircd import FakeIrcd
from bchat import logs
from bchat.session import INFO, JOIN, MSG, NOTICE, PART, SELF
from test_live import make_win, prefs, wait


def _ts(y, mo, d, h=12, mi=0, s=0):
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def test_dated_names():
    t = _ts(2026, 11, 9, 20, 14)
    assert logs.dated_name("day", t) == "2026-11-09.log"
    assert logs.dated_name("month", t) == "2026-11.log"


def test_parse_line_reads_back_what_was_written(tmp_path):
    f = logs.LogFile(tmp_path / "Libera" / "#bchat" / "2026-11-09.log", "Libera", "#bchat", 2026, 11, 9)
    ts, left, text = logs.parse_line("Nov 09 20:14:05 Belon\thello there\n", "%b %d %H:%M:%S ", f)
    assert (left, text) == ("Belon", "hello there")
    assert time.localtime(ts)[:6] == (2026, 11, 9, 20, 14, 5)
    assert logs.parse_line("Nov 09 20:15:00 -->\tWira has joined", "%b %d %H:%M:%S ", f)[1] == "-->"
    assert logs.parse_line("Nov 09 20:15:00 \tan info line", "%b %d %H:%M:%S ", f)[1:] == ("", "an info line")
    ts, left, _ = logs.parse_line("[20:16] Aiman\tsame", "[%H:%M] ", f)
    assert left == "Aiman" and time.localtime(ts)[3:5] == (20, 16)
    assert logs.parse_line("Belon\tno stamps", "%b %d %H:%M:%S ", f)[1:] == ("Belon", "no stamps")
    # a monthly file takes the day from the stamp
    m = logs.LogFile(tmp_path / "x.log", "Libera", "#bchat", 2026, 11, 0)
    assert time.localtime(logs.parse_line("Nov 21 08:00:00 Belon\tx", "%b %d %H:%M:%S ", m)[0])[:3] == (2026, 11, 21)


def test_line_kinds():
    from bchat.logwindow import line_kind
    own = {"belon"}
    assert line_kind("-->", own) == JOIN and line_kind("<--", own) == PART
    assert line_kind("*", own) == INFO and line_kind("", own) == INFO
    assert line_kind("-NickServ-", own) == NOTICE
    assert line_kind("Belon", own) == SELF and line_kind("Wira", own) == MSG


def _write(path: Path, text="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_and_labels(tmp_path):
    _write(tmp_path / "Libera" / "#bchat" / "2026-11-09.log")
    _write(tmp_path / "Libera" / "#bchat" / "2026-11-08.log")
    _write(tmp_path / "Libera" / "#bchat" / "2026-10.log")
    _write(tmp_path / "Libera-#old.log")                       # XChat-style one file
    _write(tmp_path / "Libera" / "notes.txt")
    found = logs.scan(tmp_path)
    dated = [f for f in found if f.dated]
    assert [f.path.name for f in dated] == ["2026-10.log", "2026-11-08.log", "2026-11-09.log"]   # oldest first
    assert all((f.network, f.channel) == ("Libera", "#bchat") for f in dated)
    older = [f for f in found if not f.dated]
    assert {f.path.name for f in older} == {"Libera-#old.log", "notes.txt"} and all(f.network == logs.OLDER for f in older)
    assert found[-1].network == logs.OLDER                     # older logs go last
    now = _ts(2026, 11, 9, 15)
    assert dated[2].label(now) == "Today" and dated[1].label(now) == "Yesterday"
    assert dated[0].label(now) == "October 2026"
    assert logs.LogFile(tmp_path / "a", "n", "c", 2026, 11, 1).label(now).endswith("1 Nov")
    assert logs.LogFile(tmp_path / "a", "n", "c", 2025, 11, 1).label(now).endswith("2025")
    assert logs.scan(tmp_path / "missing") == []


def test_clean_up_only_old_dated_files(tmp_path):
    now = _ts(2026, 11, 9, 15)
    old = tmp_path / "Libera" / "#gone" / "2026-01-02.log"
    old_month = tmp_path / "Libera" / "#bchat" / "2026-01.log"
    recent = tmp_path / "Libera" / "#bchat" / "2026-11-01.log"
    legacy = tmp_path / "Libera-#bchat.log"
    for p in (old, old_month, recent, legacy):
        _write(p)
    os.utime(legacy, (now - 900 * 86400, now - 900 * 86400))
    assert logs.clean_up(tmp_path, 0, now) == 0 and old.exists()          # Never = keep everything
    assert logs.clean_up(tmp_path, 31, now) == 2
    assert not old.exists() and not old_month.exists()
    assert recent.exists() and legacy.exists()
    assert not (tmp_path / "Libera" / "#gone").exists()                 # empty folder tidied
    assert (tmp_path / "Libera" / "#bchat").exists()


def test_search_count_and_cache(tmp_path):
    p = tmp_path / "a.log"
    _write(p, "ZNC znc\nnothing\n")
    c = logs.TextCache()
    assert logs.count(c.read(p), "znc") == 2 and logs.count("", "x") == 0 and logs.count("abc", "") == 0
    _write(p, "ZNC znc ZnC and more text\n")
    assert logs.count(c.read(p), "znc") == 3                            # size changed: read again
    assert c.read(tmp_path / "missing.log") == ""


def test_daily_file_logs_window_and_view_log(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    assert win.logs_of(b) == []
    assert not any(a.text() == "View Log" for a in win._switcher_menu(b).actions())   # nothing to read yet
    w = win.open_logs()
    assert w.stack.currentIndex() == 1 and "No logs yet" in w.empty_text.text() and w.find.isHidden()
    win._set_logging(b, True)
    srv.send(":Belon!b@h PRIVMSG #skinhead :\x02ZNC\x02 works fine")
    srv.send(":Wira!w@h PRIVMSG #skinhead :mine too, znc everywhere")
    path = win.log_path(b)
    assert path.parent == tmp_path / "logs" / "SkinIRC" / "#skinhead" and logs.DATED.match(path.name)
    assert wait(app, lambda: path.exists() and "everywhere" in path.read_text(encoding="utf-8"))
    assert "\x02" not in path.read_text(encoding="utf-8")
    assert any(a.text() == "View Log" for a in win._switcher_menu(b).actions())
    w = win.open_logs(b)
    assert w.stack.currentIndex() == 0
    assert w.scope.count() == 2 and not w.find.isHidden()
    assert w.scope.itemText(0) == "In #skinhead"
    assert w.current is not None and w.current.path == path
    assert w.tree.currentItem().text(0) == "Today"
    assert any(l.text == "ZNC works fine" and l.left == "Belon" for l in w.buffer.lines)
    assert "ZNC works fine" in w.view.toPlainText()
    w.find.setText("znc")
    w.fill()
    assert len(w.matches) == 2 and w.at == 0 and w.counts[path] == 2
    assert "(2)" in w.tree.currentItem().text(0)
    assert "1 of 2" in w.status.text()
    w.next_match()
    assert w.at == 1 and "2 of 2" in w.status.text()
    w.next_match()
    assert w.at == 0
    w.prev_match()
    assert w.at == 1
    w.find.setText("no-such-word-anywhere")
    w.fill()
    assert w.stack.currentIndex() == 1 and "Nothing found" in w.empty_text.text()
    w.find.setText("")
    w.fill()
    assert w.stack.currentIndex() == 0 and "lines" in w.status.text()
    # Window > Logs... shows every log, no channel picker
    w = win.open_logs()
    assert w.scope.count() == 1
    win.close(); srv.stop()


def test_prefs_split_keep_and_mask(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win, "Logging")
    assert d.log_split.currentIndex() == 0 and d.log_mask.isHidden()
    assert "#channel" in d.log_saved.text() or "SkinIRC" in d.log_saved.text()
    d.log_split.setCurrentIndex(2)
    assert not d.log_mask.isHidden()
    d.reject(); d.deleteLater()
    prefs(win, lambda d: (d.log_split.setCurrentIndex(1), d.log_keep.setCurrentIndex(3)))
    assert win.cfg.log_split == "month" and win.cfg.log_keep_days == 366
    assert logs.DATED.match(win.log_path(b).name) and len(win.log_path(b).stem) == 7
    from bchat import config
    again = config.load(tmp_path)
    assert again.log_split == "month" and again.log_keep_days == 366
    prefs(win, lambda d: (d.log_split.setCurrentIndex(2), d.log_mask.setText("%n-%c.log")))
    assert win.log_path(b).name == "#skinhead.log".replace("#", "SkinIRC-#", 1)
    old = tmp_path / "logs" / "SkinIRC" / "#skinhead" / "2020-01-01.log"
    _write(old)
    assert win.clean_old_logs() == 1 and not old.exists()
    win.close(); srv.stop()


def _answer(app, win, pick=None):
    """Answers the logging question when it shows: pick = 'Keep logs for' index, None = Cancel."""
    from PySide6.QtCore import QTimer
    seen = []

    def go():
        d = getattr(win, "log_question", None)
        if d is None:
            QTimer.singleShot(20, go)
            return
        seen.append(d.text.text())
        if pick is None:
            d.reject()
        else:
            d.keep.setCurrentIndex(pick)
            d.accept()
    QTimer.singleShot(20, go)
    return seen


def test_first_log_to_disk_asks_once(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    b = s.buffers["#skinhead"]
    assert win.needs_log_question()
    seen = _answer(app, win, None)                       # Cancel: nothing saved
    win._log_to_disk(b, True)
    assert "#skinhead" in seen[0] and "never sent anywhere" in seen[0]
    assert win.cfg.log_tabs == [] and not win.cfg.log_asked
    seen = _answer(app, win, 2)                          # 1 year
    win._log_to_disk(b, True)
    assert seen and win.cfg.log_keep_days == 366 and win.cfg.log_asked and len(win.cfg.log_tabs) == 1
    win._log_to_disk(b, False)
    win.log_question = None
    win._log_to_disk(b, True)                            # asked already: no question this time
    assert win.log_question is None and len(win.cfg.log_tabs) == 1
    from bchat import config
    assert config.load(tmp_path).log_asked
    win.close(); srv.stop()


def test_people_already_logging_are_not_asked(app, tmp_path):
    from bchat.config import Config
    from bchat.mainwindow import MainWindow
    for cfg in (Config(nick="a", log_all=True), Config(nick="a", log_tabs=["net/#x"])):
        w = MainWindow(cfg, tmp_path)
        w.skip_quit_prompt = True
        assert not w.needs_log_question()
        w.close()


def test_prefs_logging_tick_asks_and_counts_only_on_ok(app, tmp_path):
    srv = FakeIrcd()
    win, net = make_win(tmp_path, srv.port)
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win, "Logging")
    _answer(app, win, None)
    d.log_all.setChecked(True)
    assert not d.log_all.isChecked()                     # Cancel puts the tick back
    seen = _answer(app, win, 0)                          # 1 month
    d.log_all.setChecked(True)
    assert "your chats" in seen[0] and d.log_all.isChecked() and d.log_keep.currentIndex() == 1
    assert not win.cfg.log_asked                         # only once Preferences is saved
    d.accept(); d.deleteLater()
    assert win.cfg.log_all and win.cfg.log_asked and win.cfg.log_keep_days == 31
    d = PreferencesDialog(win, "Logging")                # Cancel in Preferences after answering: asked again next time
    win.cfg.log_all, win.cfg.log_asked = False, False
    _answer(app, win, 1)
    d.log_all.setChecked(True)
    d.reject(); d.deleteLater()
    assert not win.cfg.log_asked and not win.cfg.log_all
    win.close(); srv.stop()
