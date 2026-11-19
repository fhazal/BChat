"""0.8.5 mockups A, B, C (OK'd 2026-11-19): the 'File already exists' dialog, the DCC rows on File transfers
(time-outs, auto accept onto a file already there, the file type list) and the Flood page with mIRC's flood options.
Loopback sockets only; .txt files only."""
import time

from PySide6.QtWidgets import QLabel

from bchat.safety import FileExistsDialog
from test_085_dcc import LOCAL
from test_live import _sender, live, make_win, prefs, wait  # noqa: F401  (live is a fixture)


def _offer(app, srv, win, tmp_path, old: bytes, payload: bytes, name="notes.txt"):
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_open_recv = False
    (tmp_path / name).write_bytes(old)
    port, got = _sender(payload)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND {name} {LOCAL} {port} {len(payload)}\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    win.dcc.accept(t)
    assert wait(app, lambda: getattr(win, "exists_dialog", None) is not None and win.exists_dialog.isVisible())
    return t, port, win.exists_dialog


def _words(d):
    return [w.text() for w in d.findChildren(QLabel)]


def test_the_window_answers_file_exists_itself(live):
    app, srv, win, s = live
    assert win.dcc.on_exists == win._file_exists


def test_dialog_says_who_what_and_where_and_offers_the_free_name(live, tmp_path):
    app, srv, win, s = live
    t, port, d = _offer(app, srv, win, tmp_path, b"an older and longer file", b"new notes")
    words = " ".join(_words(d))
    assert "Belon is sending" in words and "notes.txt" in words and str(tmp_path) in words
    assert d.name_edit.text() == "notes (1).txt"
    assert not d.resume_btn.isVisible()               # ours is not shorter: nothing to resume
    assert d.overwrite_btn.isDefault() and not d.resume_btn.isDefault()
    d.cancel_btn.click()
    t.abort()


def test_dialog_resume_is_the_default_when_ours_is_shorter_and_asks_for_the_rest(live, tmp_path):
    app, srv, win, s = live
    payload = b"0123456789abcdef"
    t, port, d = _offer(app, srv, win, tmp_path, payload[:6], payload)
    assert d.resume_btn.isVisible() and d.resume_btn.isDefault() and not d.overwrite_btn.isDefault()
    d.resume_btn.click()
    assert wait(app, lambda: any(f"DCC RESUME notes.txt {port} 6" in x for x in srv.received))
    t.abort()


def test_dialog_overwrite_replaces_the_file(live, tmp_path):
    app, srv, win, s = live
    t, port, d = _offer(app, srv, win, tmp_path, b"an older and longer file", b"new notes")
    d.overwrite_btn.click()
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
    assert (tmp_path / "notes.txt").read_bytes() == b"new notes"
    assert not (tmp_path / "notes (1).txt").exists()


def test_dialog_rename_uses_the_typed_name(live, tmp_path):
    app, srv, win, s = live
    t, port, d = _offer(app, srv, win, tmp_path, b"old", b"new notes")
    d.name_edit.setText("theirs.txt")
    d.rename_btn.click()
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
    assert (tmp_path / "theirs.txt").read_bytes() == b"new notes" and (tmp_path / "notes.txt").read_bytes() == b"old"


def test_dialog_rename_needs_a_name(live, tmp_path):
    app, srv, win, s = live
    t, port, d = _offer(app, srv, win, tmp_path, b"old", b"new notes")
    d.name_edit.setText("   ")
    assert not d.rename_btn.isEnabled()
    d.cancel_btn.click()
    t.abort()


def test_dialog_cancel_leaves_the_offer_waiting(live, tmp_path):
    app, srv, win, s = live
    t, port, d = _offer(app, srv, win, tmp_path, b"old", b"new notes")
    d.cancel_btn.click()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.005)
    assert t.state == "queued" and t.sock is None
    assert (tmp_path / "notes.txt").read_bytes() == b"old" and not (tmp_path / "notes (1).txt").exists()
    t.abort()


def test_dialog_shows_a_name_with_angle_brackets_as_typed(app, tmp_path):
    win, _ = make_win(tmp_path, 1)
    d = FileExistsDialog(win, "<b>x</b>.txt", 10, "Ali", 4, str(tmp_path), "<b>x</b> (1).txt", True)
    words = _words(d)
    assert any("&lt;b&gt;x&lt;/b&gt;.txt" in w for w in words)                  # the rich line escapes it
    assert any(w.startswith("You already have <b>x</b>.txt") for w in words)   # the plain line shows it as is
    d.reject(); d.deleteLater(); win.close()


# --- B: File transfers page -----------------------------------------------------------------------------------------

def test_file_transfers_page_saves_timeouts_exists_and_types(app, tmp_path):
    win, _ = make_win(tmp_path, 2)

    def change(d):
        assert (d.dcc_offer_wait.value(), d.dcc_idle_wait.value(), d.dcc_exists.currentIndex()) == (120, 300, 0)
        assert d.dcc_ignore_on.isChecked() and d.dcc_never.isChecked() and "*.exe" in d.dcc_exts.text()
        d.dcc_offer_wait.setValue(0)
        d.dcc_idle_wait.setValue(60)
        d.dcc_exists.setCurrentIndex(1)
        d.dcc_only.setChecked(True)
        d.dcc_exts.setText("*.txt, *.png  *.jpg")
    prefs(win, change)
    c = win.cfg
    assert (c.dcc_offer_timeout, c.dcc_idle_timeout, c.dcc_exists) == (0, 60, "resume")
    assert c.dcc_ignore_on and c.dcc_ignore_mode == "accept" and c.dcc_ignore_exts == ["*.txt", "*.png", "*.jpg"]
    prefs(win, lambda d: (d.dcc_exists.setCurrentIndex(2), d.dcc_ignore_on.setChecked(False)))
    assert c.dcc_exists == "overwrite" and not c.dcc_ignore_on and c.dcc_ignore_mode == "accept"
    win.close()


def test_file_type_rows_grey_out_when_the_list_is_off(app, tmp_path):
    win, _ = make_win(tmp_path, 3)
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    d.dcc_ignore_on.setChecked(False)
    assert not (d.dcc_never.isEnabled() or d.dcc_only.isEnabled() or d.dcc_exts.isEnabled())
    d.dcc_ignore_on.setChecked(True)
    assert d.dcc_never.isEnabled() and d.dcc_exts.isEnabled()
    d.reject(); d.deleteLater(); win.close()


# --- C: Flood page --------------------------------------------------------------------------------------------------

def test_flood_page_shows_and_saves_the_flood_options(app, tmp_path):
    win, _ = make_win(tmp_path, 4)

    def change(d):
        assert (d.flood_bytes.value(), d.flood_lines.value(), d.flood_per_user.value(), d.flood_ignore.value()) == (400, 10, 2, 30)
        assert d.flood_on.isChecked() and d.flood_ctcp_on.isChecked()
        d.flood_bytes.setValue(200)
        d.flood_ignore.setValue(0)
        d.flood_ctcp_on.setChecked(False)
        d.flood_whois.setValue(1)
    prefs(win, change)
    c = win.cfg
    assert (c.flood_bytes, c.flood_lines, c.flood_per_user, c.flood_ignore) == (200, 10, 2, 0)
    assert c.flood_on and not c.flood_ctcp_on and c.flood_whois == 1
    prefs(win, lambda d: d.flood_on.setChecked(False))
    assert not c.flood_on
    win.close()


def test_flood_rows_grey_out_when_off_and_back_to_normal_resets_all(app, tmp_path):
    win, _ = make_win(tmp_path, 5)
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win, "Flood")
    d.flood_on.setChecked(False)
    assert not (d.flood_ctcp_on.isEnabled() or d.flood_bytes.isEnabled() or d.flood_ignore.isEnabled())
    assert d.flood_queries.isEnabled()                 # private chat limits are their own thing
    d.flood_bytes.setValue(5); d.flood_ignore.setValue(0); d.flood_ctcp_on.setChecked(False); d.flood_whois.setValue(9)
    d._flood_defaults()
    assert d.flood_on.isChecked() and d.flood_ctcp_on.isChecked() and d.flood_bytes.isEnabled()
    assert (d.flood_bytes.value(), d.flood_lines.value(), d.flood_per_user.value(), d.flood_ignore.value(),
            d.flood_queries.value(), d.flood_whois.value()) == (400, 10, 2, 30, 5, 3)
    d.reject(); d.deleteLater(); win.close()
