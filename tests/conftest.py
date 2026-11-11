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
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(["bchat-test"])


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
