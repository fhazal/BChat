"""0.8.7 design option A (OK'd 2026-11-19): the find bar under the chat (Ctrl+F) and /filter [-w] [-c] [-r] text.
Loopback sockets only (the fake ircd of test_live)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from bchat import findbar
from bchat.config import make_theme
from bchat.findbar import compile_pattern, find_spans
from bchat.session import ERROR, MSG
from test_live import live, wait  # noqa: F401  (live is a fixture)

WORDS = ("zebrafish one", "nothing here", "Zebrafish two", "\U0001F600 zebrafish three")


def _chan(app, win, s, lines=WORDS):
    b = s.buffers["#skinhead"]
    win.select_buffer(b)
    assert wait(app, lambda: win.buf is b)
    for t in lines:
        s.add(b, MSG, "alice", t)
    app.processEvents()
    return b


def _open(app, win, text):
    win.search_action.trigger()
    bar = win.find_bar
    assert bar.isVisible()
    bar.edit.setText(text)
    app.processEvents()
    return bar


def _marks(view):
    """(selected text, is the current one) for every mark on the view."""
    now = findbar.find_colours(view.cfg.theme)[1].rgba()
    return [(e.cursor.selectedText(), e.format.background().color().rgba() == now) for e in view.extraSelections()]


# --- pure helpers ------------------------------------------------------------------------------------------------------

def test_spans_count_utf16_so_marks_after_an_emoji_land_on_the_word():
    text = "\U0001F600 cat \U0001F600\U0001F600 cat"
    spans = find_spans(text, compile_pattern("cat"))
    assert spans == [(3, 6), (12, 15)]           # each emoji is two Qt positions
    assert find_spans("aaa", compile_pattern("x*", regex=True)) == []      # empty matches are skipped


# --- the bar -----------------------------------------------------------------------------------------------------------

def test_ctrl_f_action_opens_the_bar_and_focuses_it(live):
    app, srv, win, s = live
    _chan(app, win, s)
    assert win.search_action.shortcut().toString() == "Ctrl+F"
    assert not win.find_bar.isVisible()
    win.activateWindow()
    win.search_action.trigger()
    assert win.find_bar.isVisible()
    assert wait(app, lambda: win.find_bar.edit.hasFocus() or QGuiApplication.focusWindow() is None, 1000)
    assert win.find_bar.count.text() == ""


def test_count_next_previous_and_wrap(live):
    app, srv, win, s = live
    _chan(app, win, s)
    bar = _open(app, win, "zebrafish")
    assert bar.count.text() == "3 of 3"        # starts at the newest match on screen
    v = win.chat.view()
    marks = _marks(v)
    assert [t for t, _ in marks] == ["zebrafish", "Zebrafish", "zebrafish"]
    assert [t for t, cur in marks if cur] == ["zebrafish"] and marks[-1][1]     # current drawn last, solid
    bar.find_next()
    assert bar.count.text() == "1 of 3"        # wraps past the end
    bar.find_prev()
    assert bar.count.text() == "3 of 3"        # and back past the start
    bar.find_prev()
    assert bar.count.text() == "2 of 3"
    assert [t for t, cur in _marks(v) if cur] == ["Zebrafish"]
    bar.edit.setText("no such words")
    assert bar.count.text() == "No matches" and _marks(v) == []
    assert not bar.next_btn.isEnabled() and bar.filter_btn.isEnabled()
    bar.find_next()                            # nothing to go to: no error
    bar.edit.setText("")
    assert bar.count.text() == "" and not bar.filter_btn.isEnabled()


def test_enter_shift_enter_and_buttons(live):
    app, srv, win, s = live
    _chan(app, win, s)
    bar = _open(app, win, "zebrafish")
    QTest.keyClick(bar.edit, Qt.Key.Key_Return)
    assert bar.count.text() == "1 of 3"
    QTest.keyClick(bar.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert bar.count.text() == "3 of 3"
    bar.next_btn.click()
    bar.next_btn.click()
    assert bar.count.text() == "2 of 3"
    bar.prev_btn.click()
    assert bar.count.text() == "1 of 3"


def test_document_is_never_changed(live):
    app, srv, win, s = live
    _chan(app, win, s)
    v = win.chat.view()
    before = v.document().toHtml()
    bar = _open(app, win, "zebrafish")
    bar.find_next()
    bar.close_bar()
    assert v.document().toHtml() == before


def test_case_and_regex_toggles_and_bad_pattern(live):
    app, srv, win, s = live
    _chan(app, win, s)
    bar = _open(app, win, "Zebrafish")
    assert bar.count.text() == "3 of 3"
    bar.case_btn.setChecked(True)
    assert bar.count.text() == "1 of 1"
    bar.case_btn.setChecked(False)
    bar.edit.setText("zebra.ish")
    assert bar.count.text() == "No matches"    # a dot is a dot until .* is on
    bar.regex_btn.setChecked(True)
    assert bar.count.text() == "2 of 3"        # the search goes on from where it was ("Zebrafish two")
    bar.case_btn.setChecked(True)
    assert bar.count.text() == "2 of 2"
    bar.edit.setText("(unclosed")              # a bad regular expression: said, never a crash
    assert bar.count.text() == "Bad pattern"
    assert _marks(win.chat.view()) == []
    assert not bar.filter_btn.isEnabled() and not bar.next_btn.isEnabled()
    QTest.keyClick(bar.edit, Qt.Key.Key_Return)
    bar.run_filter()                           # does nothing
    assert getattr(win, "filter_window", None) is None
    bar.regex_btn.setChecked(False)
    assert bar.count.text() == "No matches"    # "(unclosed" as plain text is fine


def test_esc_closes_clears_marks_and_returns_to_the_input(live):
    app, srv, win, s = live
    _chan(app, win, s)
    bar = _open(app, win, "zebrafish")
    v = win.chat.view()
    assert len(v.extraSelections()) == 3
    QTest.keyClick(bar.edit, Qt.Key.Key_Escape)
    assert not bar.isVisible()
    assert v.extraSelections() == [] and v.find_marks == ()
    win.search_action.trigger()                # opens again with the last search
    assert bar.isVisible() and bar.edit.text() == "zebrafish" and bar.count.text() == "3 of 3"
    bar.close_btn.click()
    assert not bar.isVisible() and v.extraSelections() == []


def test_tab_switch_leaves_no_stale_marks(live):
    app, srv, win, s = live
    b = _chan(app, win, s)
    bar = _open(app, win, "zebrafish")
    chan_view = win.chat.view()
    assert len(chan_view.extraSelections()) == 3
    win.select_buffer(s.server_buffer)
    assert wait(app, lambda: win.buf is s.server_buffer)
    assert chan_view.extraSelections() == [] and chan_view.find_marks == ()
    assert bar.view() is win.chat.view() and bar.view() is not chan_view
    assert bar.count.text() == "No matches"
    s.add(s.server_buffer, MSG, "server", "a zebrafish on the server tab")
    assert wait(app, lambda: bar.count.text() == "1 of 1", 2000)
    win.select_buffer(b)
    assert wait(app, lambda: win.buf is b)
    assert bar.count.text() == "3 of 3" and len(chan_view.extraSelections()) == 3
    assert win.chat.view_of(s.server_buffer).extraSelections() == []


def test_new_lines_recount_and_keep_the_current_match(live):
    app, srv, win, s = live
    b = _chan(app, win, s)
    bar = _open(app, win, "zebrafish")
    bar.find_next()
    assert bar.count.text() == "1 of 3"
    srv.send(":alice!a@h PRIVMSG #skinhead :one more zebrafish")
    assert wait(app, lambda: bar.count.text() == "1 of 4", 3000), bar.count.text()
    for i in range(300):                        # a busy channel: one recount after the pause, never a crash
        s.add(b, MSG, "bob", f"line {i} zebrafish")
    assert wait(app, lambda: bar.count.text() == "1 of 304", 3000), bar.count.text()
    assert [t for t, cur in _marks(win.chat.view()) if cur] == ["zebrafish"]
    win.chat.reload(b)                          # the chat built again (a new document): old marks never linger
    assert wait(app, lambda: bar.count.text().endswith("of 304"), 3000), bar.count.text()
    for e in win.chat.view().extraSelections():
        assert e.cursor.document() is win.chat.view().document()
        assert e.cursor.selectedText().lower() == "zebrafish"


def test_next_right_after_new_lines_counts_first(live):
    app, srv, win, s = live
    b = _chan(app, win, s)
    bar = _open(app, win, "zebrafish")
    s.add(b, MSG, "bob", "zebrafish at the end")
    bar.find_next()                             # the pending recount runs before the step
    assert bar.count.text() == "4 of 4"


def test_detached_window_has_its_own_bar(live):
    app, srv, win, s = live
    b = _chan(app, win, s)
    win.detach(b)
    w = win.detached[id(b)]
    assert w.find_shortcut.key().toString() == "Ctrl+F"
    assert win._find_bar_for(w.chat) is w.find_bar and win._find_bar_for(win.chat.view()) is win.find_bar
    w.find_shortcut.activated.emit()
    assert w.find_bar.isVisible() and not win.find_bar.isVisible()
    w.find_bar.edit.setText("zebrafish")
    assert w.find_bar.count.text() == "3 of 3"
    w.find_bar.filter_btn.click()
    assert win.filter_window.windowTitle() == 'Filter: "zebrafish" in #skinhead, 3 lines'
    QTest.keyClick(w.find_bar.edit, Qt.Key.Key_Escape)
    assert w.chat.extraSelections() == []
    win.attach(b)


def test_theme_change_restyles_the_bar_and_marks(live):
    app, srv, win, s = live
    _chan(app, win, s)
    bar = _open(app, win, "zebrafish")
    win.cfg.theme = make_theme("Catppuccin Latte")
    win.apply_preferences()
    assert win.cfg.theme.bar in bar.styleSheet()
    assert bar.count.text() == "3 of 3" and len(win.chat.view().extraSelections()) == 3
    assert [t for t, cur in _marks(win.chat.view()) if cur] == ["zebrafish"]
    win.cfg.theme = make_theme("Catppuccin Mocha")      # the app's palette is shared by later tests
    win.apply_preferences()


# --- /filter -----------------------------------------------------------------------------------------------------------

def test_filter_command_with_every_switch(live):
    app, srv, win, s = live
    b = _chan(app, win, s)
    win.run_command(s, "/filter zebrafish")
    fw = win.filter_window
    assert fw.isVisible()
    assert fw.windowTitle() == 'Filter: "zebrafish" in #skinhead, 3 lines'
    rows = fw.view.toPlainText().split("\n")
    assert len(rows) == 3 and rows[0].endswith(" alice\tzebrafish one") and rows[2].endswith("\U0001F600 zebrafish three")
    win.run_command(s, "/filter -c Zebrafish")
    assert win.filter_window is fw              # without -w the one window is used again
    assert fw.windowTitle() == 'Filter: "Zebrafish" in #skinhead, 1 line'
    win.run_command(s, "/filter -r zebra.ish\\s+t")
    assert fw.windowTitle() == 'Filter: "zebra.ish\\s+t" in #skinhead, 2 lines'
    win.run_command(s, "/filter -rc ^alice Zebra")     # the line is matched as shown: "nick text"
    assert fw.windowTitle() == 'Filter: "^alice Zebra" in #skinhead, 1 line'
    win.run_command(s, "/filter alice")         # the nick counts too, as on screen
    assert fw.windowTitle().endswith(", 4 lines")
    win.run_command(s, "/filter -w zebrafish  three")
    assert win.filter_window is fw
    others = [w for w in win.findChildren(findbar.FilterWindow) if w is not fw]
    assert len(others) == 1 and others[0].isVisible()
    assert others[0].windowTitle() == 'Filter: "zebrafish  three" in #skinhead, 0 lines'   # spacing kept
    win.run_command(s, "/filter nobody said this")
    assert fw.windowTitle() == 'Filter: "nobody said this" in #skinhead, 0 lines' and fw.isVisible()
    assert fw.view.toPlainText() == ""


def test_filter_bad_pattern_and_usage_open_nothing_and_send_nothing(live):
    app, srv, win, s = live
    b = _chan(app, win, s)
    n = len(b.lines)
    win.run_command(s, "/filter -r (zebra")
    assert b.lines[-1].kind == ERROR and "bad pattern" in b.lines[-1].text
    assert getattr(win, "filter_window", None) is None
    win.run_command(s, "/filter")
    win.run_command(s, "/filter -c")
    win.run_command(s, "/filter -x word")
    assert [l.kind for l in b.lines[n:]] == [ERROR] * 4
    assert all(l.text.startswith("Usage: FILTER") for l in b.lines[n + 1:])
    app.processEvents()
    assert not any(x.upper().startswith("FILTER") for x in srv.received)
    assert getattr(win, "filter_window", None) is None


def test_filter_is_in_help_and_command_lists(live):
    app, srv, win, s = live
    from bchat import commands
    assert "filter" in commands.COMMAND_NAMES and commands.HELP["filter"].startswith("FILTER [-w] [-c] [-r]")
    b = _chan(app, win, s)
    win.run_command(s, "/help")
    assert "/filter" in b.lines[-1].text


def test_copy_all_and_save(live, tmp_path, monkeypatch):
    app, srv, win, s = live
    _chan(app, win, s)
    win.run_command(s, "/filter zebrafish")
    fw = win.filter_window
    fw.copy_btn.click()
    clip = QGuiApplication.clipboard().text()
    assert clip.count("\n") == 3 and "\U0001F600 zebrafish three" in clip and "nothing here" not in clip
    out = tmp_path / "saved.txt"
    asked = []
    monkeypatch.setattr(findbar.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (asked.append(a[2]), (str(out), "Text files (*.txt)"))[1])
    fw.save_btn.click()
    assert asked == ["filter-#skinhead.txt"]
    assert out.read_text(encoding="utf-8") == clip
    monkeypatch.setattr(findbar.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    out.unlink()
    fw.save_btn.click()                         # Cancel: nothing written
    assert not out.exists()


def test_bar_filter_button_uses_the_toggles(live):
    app, srv, win, s = live
    _chan(app, win, s)
    bar = _open(app, win, "Zebrafish")
    bar.case_btn.setChecked(True)
    bar.filter_btn.click()
    assert win.filter_window.windowTitle() == 'Filter: "Zebrafish" in #skinhead, 1 line'
