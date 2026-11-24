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
SOUNDS_PLAYED: list = []
import bchat.sound, bchat.speech                                      # noqa: E401
if os.name == "nt":
    import winsound
    winsound.PlaySound = lambda path, flags: SOUNDS_PLAYED.append(path)   # tests never make a sound on the user's PC
else:                           # Linux: no Windows player, every sound goes through Qt (muted below); note what it plays
    sys.modules["winsound"] = None      # as on a real Linux desktop, even with a stub winsound.py on the path
    _qt_media = bchat.sound.Player._media
    def _noted_media(self, p, volume):
        SOUNDS_PLAYED.append(str(p))
        return _qt_media(self, p, volume)
    bchat.sound.Player._media = _noted_media
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
    new = [w for w in app.topLevelWidgets() if id(w) not in before]
    for w in new:
        _go_quiet(w)
    for _ in range(3):
        app.processEvents()
    for w in new:
        try:                                   # Settings alone is ~1,000 widgets, a main window more
            w.hide()
            w.deleteLater()
        except RuntimeError:                   # already gone
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _go_quiet(w) -> None:
    """Before a window is freed nothing of it may still run: a main window gets the same shutdown as when BChat
    quits (connections, DCC, router ports, pop-up cards), then every timer it owns stops. Freeing one that was
    still busy is what used to crash Qt, so they were kept alive and piled up until setStyleSheet crawled."""
    from PySide6.QtCore import QTimer
    from bchat.mainwindow import MainWindow
    try:
        if isinstance(w, MainWindow):
            owners = [w]
            for part, how in (("notifier", "clear"), ("dcc", "shutdown"), ("upnp", "shutdown")):
                obj = getattr(w, part, None)
                if obj is None:
                    continue
                owners.append(obj)
                try:
                    getattr(obj, how)()
                except Exception:                  # half-built window (a test that broke early): carry on
                    pass
            for s in list(getattr(w, "sessions", {}).values()):
                owners.append(s)
                try:
                    s.disconnect_from_network()
                except Exception:
                    pass
            tray = getattr(w, "tray", None)
            if tray is not None:
                tray.hide()
        else:
            owners = [w]
        for o in owners:                           # sessions and DCC keep timers of their own (reconnect, keepalive)
            if hasattr(o, "findChildren"):
                for t in o.findChildren(QTimer):
                    t.stop()
    except RuntimeError:                           # already gone
        pass


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
