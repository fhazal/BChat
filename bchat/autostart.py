"""Start with Windows: the BChat value in HKCU\\...\\CurrentVersion\\Run.

The tick in Preferences is the truth. Every start of the installed BChat makes Windows match it (sync), because
the value can vanish behind BChat's back: an antivirus undoing an app's changes, a cleaner tool, a new install path.
Only BChat's own value ("BChat") is ever touched."""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "BChat"


def command(exe: str) -> str:
    return f'"{exe}"'


def installed_exe() -> str | None:
    """The running BChat.exe, or None from source (nothing stable to point Windows at)."""
    return sys.executable if getattr(sys, "frozen", False) else None


def current(key_path: str = RUN_KEY) -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, NAME)
            return str(value)
    except OSError:
        return None


def sync(on: bool, exe: str | None, key_path: str = RUN_KEY) -> str:
    """Makes the Run value match the tick. Answers 'added', 'fixed' (pointed elsewhere), 'removed', 'ok' or
    'skipped' (from source). Never raises: a locked registry must not stop BChat starting."""
    if exe is None:
        return "skipped"
    import winreg
    want = command(exe)
    have = current(key_path)
    try:
        if on:
            if have == want:
                return "ok"
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, want)
            return "added" if have is None else "fixed"
        if have is None or have.lower() != want.lower():
            return "ok"           # unticked here, but the entry is another copy's (e.g. a test build run): leave it
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, NAME)
        return "removed"
    except OSError:
        return "failed"
