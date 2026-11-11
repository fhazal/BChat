"""Lock (0.6.0): a password when BChat starts, plus optional limits, for a shared or family PC.

Honest by design: it is a house rule, not a safe. Everything lives in lock.json in the settings folder; deleting that
file removes the lock (Forgot password? says so), and BChat then notes on the Lock page that the lock was removed.

The password is never stored: lock.json keeps a salt and a PBKDF2-SHA256 check value. Portable BChat can keep network
passwords in its folder only when a Lock password is set: they are sealed with a key from the same password
(seal/open_box: PBKDF2 key, HMAC-SHA256 keystream, HMAC tag; standard library only).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

FILE = "lock.json"
ITERATIONS = 200_000


def _keys(password: str, salt: bytes, iterations: int) -> tuple[bytes, bytes]:
    k = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=64)
    return k[:32], k[32:]


def path(folder: Path) -> Path:
    return Path(folder) / FILE


def read(folder: Path) -> dict | None:
    """The lock settings, or None when there is no (readable) lock."""
    try:
        d = json.loads(path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("salt") or not d.get("check"):
        return None
    return d


def make(password: str, limits: dict) -> tuple[dict, bytes]:
    """A new lock.json body for this password and these limits, and the key that seals portable passwords."""
    salt = os.urandom(16)
    check_key, box_key = _keys(password, salt, ITERATIONS)
    d = {"salt": base64.b64encode(salt).decode(), "iterations": ITERATIONS,
         "check": hmac.new(check_key, b"bchat-lock", hashlib.sha256).hexdigest(), "set": time.time()}
    d.update(limits_only(limits))
    return d, box_key


def limits_only(d: dict) -> dict:
    return {"no_dcc": bool(d.get("no_dcc")), "no_private": bool(d.get("no_private")),
            "only_channels": str(d.get("only_channels", "") or "").strip()}


def unlock(d: dict, password: str) -> bytes | None:
    """The sealing key when the password is right, else None."""
    try:
        salt = base64.b64decode(d["salt"])
        check_key, box_key = _keys(password, salt, int(d.get("iterations", ITERATIONS)))
    except (KeyError, ValueError, TypeError):
        return None
    good = hmac.compare_digest(hmac.new(check_key, b"bchat-lock", hashlib.sha256).hexdigest(), str(d.get("check", "")))
    return box_key if good else None


def write(folder: Path, d: dict) -> None:
    Path(folder).mkdir(parents=True, exist_ok=True)
    tmp = path(folder).with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(path(folder))


def remove(folder: Path) -> None:
    try:
        path(folder).unlink()
    except FileNotFoundError:
        pass


def allowed_channels(limits: dict | None) -> list[str]:
    if not limits:
        return []
    return [c.strip().lower() for c in str(limits.get("only_channels", "")).replace(",", " ").split() if c.strip()]


# --- sealing portable passwords -------------------------------------------------------------

def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = b""
    i = 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def seal(key: bytes, text: str) -> str:
    nonce = os.urandom(16)
    data = text.encode("utf-8")
    enc_key, mac_key = hashlib.sha256(key + b"enc").digest(), hashlib.sha256(key + b"mac").digest()
    body = bytes(a ^ b for a, b in zip(data, _stream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, nonce + body, hashlib.sha256).digest()
    return base64.b64encode(nonce + tag + body).decode()


def open_box(key: bytes, blob: str) -> str | None:
    try:
        raw = base64.b64decode(blob)
    except (ValueError, TypeError):
        return None
    if len(raw) < 48:
        return None
    nonce, tag, body = raw[:16], raw[16:48], raw[48:]
    enc_key, mac_key = hashlib.sha256(key + b"enc").digest(), hashlib.sha256(key + b"mac").digest()
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + body, hashlib.sha256).digest()):
        return None
    return bytes(a ^ b for a, b in zip(body, _stream(enc_key, nonce, len(body)))).decode("utf-8", "replace")


# --- windows ---------------------------------------------------------------------------------

def ask_password(parent, folder: Path, d: dict, title: str = "BChat: Locked",
                 text: str = "BChat is locked. Password:", quit_label: str = "&Quit") -> bytes | None:
    """The start-up (or Preferences) password window. Returns the sealing key, or None for Quit/Cancel."""
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton
    from .widgets import FramedDialog, icon

    dlg = FramedDialog(title, parent)
    dlg.body.addWidget(QLabel(text, dlg))
    pw = QLineEdit(dlg)
    pw.setEchoMode(QLineEdit.EchoMode.Password)
    dlg.body.addWidget(pw)
    why = QLabel("", dlg)
    dlg.body.addWidget(why)
    forgot = QLabel('<a href="forgot">Forgot password?</a>', dlg)
    forgot.setTextFormat(Qt.TextFormat.RichText)
    forgot.linkActivated.connect(lambda _: forgot_help(dlg, folder))
    dlg.body.addWidget(forgot)
    row = QHBoxLayout()
    row.addStretch(1)
    quit_btn = QPushButton(icon("close-light"), quit_label, dlg)
    quit_btn.setAutoDefault(False)
    quit_btn.clicked.connect(dlg.reject)
    ok = QPushButton(icon("save"), "&Open", dlg)
    ok.setDefault(True)
    row.addWidget(quit_btn)
    row.addWidget(ok)
    dlg.body.addLayout(row)
    found: list[bytes] = []

    def check():
        key = unlock(d, pw.text())
        if key is not None:
            found.append(key)
            dlg.accept()
            return
        pw.clear()
        why.setText("Wrong password.")
        ok.setEnabled(False)                 # a second between tries: guessing stays slow
        QTimer.singleShot(1000, lambda: ok.setEnabled(True))

    ok.clicked.connect(check)
    dlg.resize(340, 0)
    pw.setFocus()
    dlg.exec()
    return found[0] if found else None


def forgot_help(parent, folder: Path) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setWindowTitle("BChat: Forgot Password")
    box.setText("To remove the lock, close BChat and delete lock.json in BChat's settings folder.\n\n"
                "Your networks, logs and friends stay. The limits go with the lock, and BChat's Lock page will "
                "show that the lock was removed." + ("\n\nPortable BChat: saved network passwords were sealed with "
                                                     "this password, so you type them once more." if is_portable(folder) else ""))
    open_btn = box.addButton("Open Settings Folder", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is open_btn:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def is_portable(folder: Path) -> bool:
    return Path(folder).name == "BChat-data"
