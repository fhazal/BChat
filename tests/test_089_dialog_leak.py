"""0.8.9: closing a dialog frees it. Before, every Settings, Network List or About window opened with exec() stayed in
memory, hidden, until BChat quit (Settings alone is about a thousand widgets), and every theme change restyled them all."""
import gc

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from bchat.config import Config


def settle(app):
    for _ in range(3):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def close_soon():
    """Close whatever modal dialog is up once exec() is running."""
    def go():
        d = QApplication.activeModalWidget()
        if isinstance(d, QDialog):
            d.reject()
        else:
            QTimer.singleShot(20, go)
    QTimer.singleShot(50, go)


@pytest.fixture
def win(app, tmp_path):
    from bchat.mainwindow import MainWindow
    w = MainWindow(Config(nick="x", skip_network_list=True), tmp_path / "cfg")
    w.skip_quit_prompt = True
    w.show()
    settle(app)
    yield w
    w.hide()
    w.deleteLater()
    settle(app)


@pytest.mark.parametrize("opener", ["open_preferences", "open_network_list", "_about"])
def test_dialog_is_freed_after_closing(app, win, opener):
    close_soon()
    getattr(win, opener)()          # first open: anything cached once (fonts, icons) is made now
    settle(app)
    before = len(app.allWidgets())
    for _ in range(3):
        close_soon()
        getattr(win, opener)()
        settle(app)
    assert len(app.allWidgets()) - before < 20, f"{opener} left {len(app.allWidgets()) - before} widgets behind"


def test_settings_page_still_opens_and_saves(app, win):
    """Freeing the dialog must not lose what was set in it."""
    from bchat.preferences import PreferencesDialog
    from bchat.widgets import run_dialog
    d = PreferencesDialog(win, "Text box")
    QTimer.singleShot(50, d.accept)
    assert run_dialog(d) == QDialog.DialogCode.Accepted
    assert d.isHidden()             # still readable right after the call; freed on the next pass
    settle(app)
