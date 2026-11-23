import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BCHAT_VAULT"] = "memory"     # tests never touch the real Windows Credential Manager
os.environ["BCHAT_REPORT_URL"] = "http://127.0.0.1:9/never"   # tests never send a problem report to the real server
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
import bchat.updater
bchat.updater.UPDATE_URL = ""      # tests never ask the real GitHub for releases
import winsound
SOUNDS_PLAYED: list = []
winsound.PlaySound = lambda path, flags: SOUNDS_PLAYED.append(path)   # tests never make a sound on the user's PC
import bchat.sound, bchat.speech                                      # noqa: E401
bchat.sound.MUTED = True            # mp3/ogg players really decode, muted
bchat.speech.ENGINE = "mock"        # Qt's silent speech engine: nothing is read aloud in tests
import bchat.notify                                                     # noqa: E402
bchat.notify.windows_busy = lambda: False   # a full-screen app or Do Not Disturb on the test PC would mute every chime
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(["bchat-test"])


@pytest.fixture(scope="module", autouse=True)
def _free_windows_after_each_file():
    """Windows a test file opened are freed when the file is done. Without this, ~11,000 windows (6+ GB) piled up
    over a full run, and app-wide calls like setStyleSheet crawled until the run timed out."""
    app = QApplication.instance()
    before = set(map(id, app.topLevelWidgets())) if app else set()
    yield
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from bchat.mainwindow import MainWindow
    new = [w for w in app.topLevelWidgets() if id(w) not in before]
    wins = [w for w in new if isinstance(w, MainWindow)]
    for w in wins:
        # Main windows stay alive (freeing one while its sessions, DCC and timers still run crashed Qt), but go quiet.
        try:
            for s in list(w.sessions.values()):
                s.disconnect_from_network()
            w.hide()
        except RuntimeError:
            pass
    for _ in range(3):
        app.processEvents()
    for w in new:
        if any(w is m for m in wins):
            continue
        try:                                   # dialogs, popups and cards: Settings alone is ~1,000 widgets
            w.hide()
            w.deleteLater()
        except RuntimeError:                   # already gone
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture
def qa_server(tmp_path):
    """Factory for tests/qa_ircd.QaIrcd servers (QA item A). Every server made is stopped after the test, and a
    simulator thread still alive afterwards fails the test: nothing may keep running."""
    from qa_ircd import QaIrcd
    made = []

    def make(**kw):
        kw.setdefault("cert_dir", tmp_path / "qa-certs")
        srv = QaIrcd(**kw)
        made.append(srv)
        return srv
    yield make
    for srv in made:
        srv.stop()
    left = [t.name for srv in made for t in srv.alive_threads()]
    assert not left, f"qa_ircd threads still running after the test: {left}"
