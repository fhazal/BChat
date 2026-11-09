"""Start with Windows: the Run value follows the tick at every start (a throwaway key, never the real Run key)."""
import winreg

import pytest

from bchat import autostart

KEY = r"Software\BChatTests\Run"


@pytest.fixture
def key():
    yield KEY
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\BChatTests")
    except OSError:
        pass


def test_sync_puts_a_vanished_entry_back_and_fixes_a_moved_one(key):
    exe = r"C:\Users\x\AppData\Local\Programs\BChat\BChat.exe"
    assert autostart.current(key) is None
    assert autostart.sync(True, exe, key) == "added"
    assert autostart.current(key) == f'"{exe}"'
    assert autostart.sync(True, exe, key) == "ok"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:   # gone behind our back
        winreg.DeleteValue(k, "BChat")
    assert autostart.sync(True, exe, key) == "added"
    assert autostart.sync(True, r"D:\BChat\BChat.exe", key) == "fixed"                 # installed somewhere else now
    assert autostart.current(key) == r'"D:\BChat\BChat.exe"'


def test_unticked_removes_only_its_own_entry(key):
    mine, other = r"C:\P\BChat\BChat.exe", r"C:\dev\dist\BChat\BChat.exe"
    autostart.sync(True, mine, key)
    assert autostart.sync(False, other, key) == "ok"            # a test build with fresh settings never removes it
    assert autostart.current(key) == f'"{mine}"'
    assert autostart.sync(False, mine.upper(), key) == "removed"
    assert autostart.current(key) is None
    assert autostart.sync(False, mine, key) == "ok"


def test_from_source_never_touches_windows(key):
    assert autostart.installed_exe() is None                     # tests run from source
    assert autostart.sync(True, None, key) == "skipped" and autostart.current(key) is None


def test_main_window_checks_at_start(app, tmp_path, monkeypatch):
    from bchat.config import Config
    from bchat.mainwindow import MainWindow
    calls = []
    monkeypatch.setattr(autostart, "sync", lambda on, exe, key_path=autostart.RUN_KEY: calls.append((on, exe)) or "ok")
    w = MainWindow(Config(nick="a", start_with_windows=True), tmp_path)
    w.skip_quit_prompt = True
    assert w.check_autostart() == "ok" and calls == [(True, None)]
    w.close()
