"""Preferences > BChat > Updates card, About's update status, the Help menu icon."""
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from bchat import updater as up
from bchat import updatepage as pg
from bchat.config import Config
from bchat.mainwindow import MainWindow
from bchat.preferences import PreferencesDialog

ENTRY = {"version": "0.1.1", "size": 46_600_000, "date": "12 Nov 2026", "notes": ["Welcome screen", "<b>bold?</b> & more"],
         "notes_url": "https://github.com/fhazal/BChat/releases/tag/v0.1.1", "url": "https://x/BChat-0.1.1-setup.exe"}


@pytest.fixture
def win(app, tmp_path):
    w = MainWindow(Config(nick="x", skip_network_list=True), tmp_path)
    w.skip_quit_prompt = True
    w.updater.current = "0.1.0-TEST23"
    yield w
    w.close()


def put(u, state, entry=None, progress=0, reason=""):
    u.entry, u.progress = entry, progress
    u._set(state, reason)


def test_card_text_for_every_state(win):
    u = win.updater
    put(u, up.NONE)
    c = pg.card_text(u)
    assert c["title"] == "BChat 0.1.0-TEST23" and c["status"] == "You're up to date" and c["button"][2] == "check"
    assert "Not checked yet" in c["sub"]
    u.cfg.update_last_check = time.time()
    u.url = "https://api.github.com/repos/fhazal/BChat/releases"
    assert pg.card_text(u)["sub"].startswith("Checked today at ") and "from GitHub" in pg.card_text(u)["sub"]
    put(u, up.AVAILABLE, ENTRY)
    c = pg.card_text(u)
    assert c["title"] == "BChat 0.1.1 is here" and "46.6 MB" in c["sub"] and "12 Nov 2026" in c["sub"]
    assert c["button"][2] == "download" and c["filled"]
    put(u, up.DOWNLOADING, ENTRY, progress=62)
    c = pg.card_text(u)
    assert c["pct"] == "62%" and c["ring"] == 0.62 and c["status"] == "28.9 of 46.6 MB" and c["button"][2] == "cancel"
    put(u, up.READY, ENTRY, progress=100)
    c = pg.card_text(u)
    assert c["title"] == "BChat 0.1.1 is ready" and c["button"][2] == "install" and c["filled"]
    put(u, up.FAILED, None, reason="Couldn't check for updates: not found")
    c = pg.card_text(u)
    assert c["title"] == "Couldn't check for updates" and c["status"] == "Not found" and c["button"][2] == "retry"
    put(u, up.CHECKING)
    assert pg.card_text(u)["status"] == "Checking for updates..." and pg.card_text(u)["button"][2] == ""


def test_card_buttons_call_the_updater(win, monkeypatch):
    u = win.updater
    calls = []
    for name in ("check", "download", "cancel", "install_now", "retry"):
        monkeypatch.setattr(u, name, lambda *a, n=name, **k: calls.append(n))
    card = pg.UpdateCard(win)
    for state, entry, want in ((up.NONE, None, "check"), (up.AVAILABLE, ENTRY, "download"), (up.DOWNLOADING, ENTRY, "cancel"),
                               (up.READY, ENTRY, "install_now"), (up.FAILED, None, "retry")):
        put(u, state, entry)
        assert card.button.isEnabled() and not card.button.icon().isNull()
        card.button.click()
        assert calls[-1] == want
    put(u, up.CHECKING)
    assert not card.button.isEnabled()


def test_whats_new_shows_only_with_a_new_version_and_as_plain_text(app, win):
    u = win.updater
    card = pg.UpdateCard(win)
    card.show()
    put(u, up.AVAILABLE, ENTRY)
    app.processEvents()
    assert card.news.isVisible()
    labels = [w for w in card.news.findChildren(QLabel) if w.text() in ENTRY["notes"]]
    assert len(labels) == 2 and all(w.textFormat() == Qt.TextFormat.PlainText for w in labels)
    assert "github.com/fhazal/BChat/releases/tag/v0.1.1" in card.notes_link.text()
    put(u, up.AVAILABLE, dict(ENTRY, notes_url="javascript:alert(1)", page=""))   # only https links are shown
    app.processEvents()
    assert not card.notes_link.isVisible()
    put(u, up.NONE)
    app.processEvents()
    assert not card.news.isVisible()


def test_preferences_has_bchat_updates_page_and_saves(app, win):
    d = PreferencesDialog(win, "Updates")
    assert d.title.text() == "Updates" and hasattr(d, "upd_card")
    gen = PreferencesDialog(win, "General")                       # the options left General
    assert gen.title.text() == "General"
    d.upd_check.setChecked(False)
    d.upd_auto.setChecked(True)
    d.upd_test.setChecked(True)
    d.accept()
    assert (win.cfg.update_check, win.cfg.update_auto_download, win.cfg.update_test_versions) == (False, True, True)


def test_about_shows_the_update_status(app, win):
    u = win.updater
    d = win._about_box()
    assert d.update_status.text() == ""                           # never checked: nothing to say
    u.cfg.update_last_check = time.time()
    put(u, up.UPTODATE)
    assert "Up to date" in d.update_status.text()
    put(u, up.AVAILABLE, ENTRY)
    assert not d.update_icon.isHidden() and not d.update_icon.pixmap().isNull()
    assert "0.1.1 is here" in d.update_status.text() and "Update" in d.update_status.text()
    put(u, up.READY, ENTRY)
    assert "0.1.1 is ready" in d.update_status.text()
    opened = []
    win.open_update_window = lambda: opened.append(1)
    d2 = win._about_box()
    d2.update_status.linkActivated.emit("bchat:update")
    assert opened == [1]
    d.close()


def test_about_tick_is_sharp_and_beside_the_words(app, win):
    """User (TEST25): the About tick looked off. It was a rich-text <img>: a 28 px picture shrunk to 21 px at 150 %
    without smoothing, sitting on the text's baseline. Now its own label, drawn at the screen's real pixel size."""
    u = win.updater
    u.cfg.update_last_check = time.time()
    put(u, up.UPTODATE)
    d = win._about_box()
    assert "<img" not in d.update_status.text()
    pm = d.update_icon.pixmap()
    dpr = d.devicePixelRatioF()
    assert pm.devicePixelRatio() == dpr
    assert (pm.width(), pm.height()) == (round(14 * dpr), round(14 * dpr))   # drawn 1:1, never rescaled
    from bchat.updatepage import icon_pixmap
    for scale in (1.0, 1.25, 1.5, 2.0):
        p = icon_pixmap("done", "#a6e3a1", 14, scale)
        assert p.width() == round(14 * scale) and abs(p.deviceIndependentSize().width() - 14) <= 0.5
    d.close()


def test_help_check_for_updates_has_an_icon(win):
    help_menu = next(a.menu() for a in win.menubar_.actions() if a.menu() and "Help" in a.text())
    act = next(a for a in help_menu.actions() if "Updates" in a.text().replace("&", ""))
    assert not act.icon().isNull()
    assert all(not a.icon().isNull() for a in help_menu.actions() if not a.isSeparator())
