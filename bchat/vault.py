"""Passwords in Windows Credential Manager instead of config.json.

Windows encrypts these for the signed-in user, so they're not readable from the settings file, a backup of it or a
copy sent to someone. Honest limit: a program running as the same Windows user can still ask Windows for them.

One settings folder = one set of entries, "BChat:<folder hash>:0", ":1", ... (an entry holds up to 2560 bytes, so a
long list is split). Tests set BCHAT_VAULT=memory and never touch the real Credential Manager.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path

CHUNK = 2000
_memory: dict[str, bytes] = {}


def _target(folder: Path, i: int) -> str:
    h = hashlib.sha256(str(Path(folder).resolve()).lower().encode()).hexdigest()[:12]
    return f"BChat:{h}:{i}"


def _memory_mode(folder: Path | None = None) -> bool:
    """Tests, developer tools and the build checks run BChat with throwaway settings in the temp folder:
    those never write to the real Credential Manager. The installed program ALWAYS uses Credential Manager,
    wherever its settings folder is, unless a build check asks for the stand-in with BCHAT_VAULT=file
    (a password must never end up in a plain file just because someone used --config-dir in %TEMP%)."""
    import sys
    mode = os.environ.get("BCHAT_VAULT", "")
    if mode == "memory" or os.name != "nt":
        return True
    if getattr(sys, "frozen", False) and mode != "file":
        return False
    if folder is not None:
        import tempfile
        try:
            Path(folder).resolve().relative_to(Path(tempfile.gettempdir()).resolve())
            return True
        except ValueError:
            pass
    return False


class _CRED(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_char)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR)]


GENERIC, LOCAL_MACHINE = 1, 2       # CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE (this PC, this user, no roaming)


def _fake_store(folder) -> dict:
    """The stand-in: in memory under pytest, in a file inside a throwaway folder (survives a restart of the exe)."""
    if folder is None or os.environ.get("BCHAT_VAULT") == "memory":
        return _memory
    import json
    f = Path(folder) / "vault-test.json"
    try:
        return {k: bytes.fromhex(v) for k, v in json.loads(f.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def _fake_save(folder, store: dict) -> None:
    if folder is None or os.environ.get("BCHAT_VAULT") == "memory":
        return
    import json
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "vault-test.json").write_text(json.dumps({k: v.hex() for k, v in store.items()}), encoding="utf-8")


def _write(target: str, data: bytes, folder=None) -> bool:
    if _memory_mode(folder):
        store = _fake_store(folder)
        store[target] = data
        _fake_save(folder, store)
        return True
    buf = ctypes.create_string_buffer(data, len(data))
    c = _CRED(Type=GENERIC, TargetName=target, Comment="BChat IRC passwords", CredentialBlobSize=len(data),
              CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)), Persist=LOCAL_MACHINE, UserName="BChat")
    return bool(ctypes.windll.advapi32.CredWriteW(ctypes.byref(c), 0))


def _read(target: str, folder=None) -> bytes | None:
    if _memory_mode(folder):
        return _fake_store(folder).get(target)
    p = ctypes.POINTER(_CRED)()
    if not ctypes.windll.advapi32.CredReadW(target, GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        return ctypes.string_at(p.contents.CredentialBlob, p.contents.CredentialBlobSize)
    finally:
        ctypes.windll.advapi32.CredFree(p)


def _delete(target: str, folder=None) -> None:
    if _memory_mode(folder):
        store = _fake_store(folder)
        store.pop(target, None)
        _fake_save(folder, store)
        return
    ctypes.windll.advapi32.CredDeleteW(target, GENERIC, 0)


def put(folder: Path, text: str) -> bool:
    """Store text for this settings folder. False if Windows refused (the caller then keeps the old way)."""
    data = text.encode("utf-8")
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    try:
        for i, part in enumerate(chunks):
            if not _write(_target(folder, i), part, folder):
                return False
        i = len(chunks)
        while _read(_target(folder, i), folder) is not None:      # a shorter list than last time: drop the leftovers
            _delete(_target(folder, i), folder)
            i += 1
        return True
    except (OSError, AttributeError, ValueError):
        return False


def get(folder: Path) -> str | None:
    """The stored text, or None when there's nothing (or Windows won't give it)."""
    try:
        parts, i = [], 0
        while (part := _read(_target(folder, i), folder)) is not None:
            parts.append(part)
            i += 1
        return b"".join(parts).decode("utf-8") if parts else None
    except (OSError, AttributeError, ValueError, UnicodeDecodeError):
        return None


def clear(folder: Path) -> None:
    i = 0
    while _read(_target(folder, i), folder) is not None:
        _delete(_target(folder, i), folder)
        i += 1
