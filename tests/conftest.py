import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BCHAT_VAULT"] = "memory"     # tests never touch the real Windows Credential Manager
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
import bchat.updater
bchat.updater.UPDATE_URL = ""      # tests never ask the real GitHub for releases
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(["bchat-test"])
