"""Updates: check a small JSON file, download the installer, check its checksum and signature, run it.

The JSON file ("manifest") looks like:
    {"stable": {"version": "0.1.1", "date": "2026-11-12", "size": 38000000,
                "url": "https://.../BChat-0.1.1-setup.exe", "page": "https://.../releases/0.1.1",
                "sha256": "<hex>", "sig": "<base64 ed25519 over 'version\\nsha256'>",
                "notes": ["Colours 16-98", ...], "notes_url": "https://..."},
     "test":   {... same, for TEST builds ...}}
dev-tools/make_manifest.py writes it and signs with the release key, which never leaves the owner's PC.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import full_version

# Where the manifest lives. Empty until the owner picks a home for releases (GitHub or bajubesi.org).
UPDATE_URL = ""
PUBLIC_KEY = "ARhI0vJdhDtK1QX6sN1F7jKkLS0mataG0pUi7uN2830="
DAY_MS = 24 * 3600 * 1000
RETRY_MS = 3600 * 1000

NONE, CHECKING, UPTODATE, AVAILABLE, DOWNLOADING, READY, FAILED = (
    "none", "checking", "uptodate", "available", "downloading", "ready", "failed")


def version_key(v: str) -> tuple:
    """0.1.0-TEST17 < 0.1.0-TEST18 < 0.1.0 < 0.1.1. Unknown text sorts lowest."""
    m = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[-.]?(?:test)[.-]?(\d+))?\s*$", v or "", re.I)
    if not m:
        return ((), 0, 0)
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = nums + (0,) * (4 - len(nums))
    return (nums, 0, int(m.group(2))) if m.group(2) else (nums, 1, 0)


def is_test(v: str) -> bool:
    return version_key(v)[1:] != (1, 0) and version_key(v)[0] != ()


def signed_text(entry: dict) -> bytes:
    return f"{entry.get('version', '')}\n{entry.get('sha256', '').lower()}".encode()


def signature_ok(entry: dict, key_b64: str | None = None) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64 or PUBLIC_KEY))
        key.verify(base64.b64decode(entry.get("sig", "")), signed_text(entry))
        return True
    except Exception:
        return False


def pick(manifest: dict, current: str, want_test: bool) -> dict | None:
    """The newest entry the user wants, if it's newer than what's running."""
    choices = [manifest.get("stable")]
    if want_test:
        choices.append(manifest.get("test"))
    choices = [c for c in choices if isinstance(c, dict) and c.get("version") and c.get("url")]
    if not choices:
        return None
    best = max(choices, key=lambda c: version_key(c["version"]))
    return best if version_key(best["version"]) > version_key(current) else None


def launch_installer(path: str, restart: bool) -> None:
    """Quiet install over the top. Settings and networks live in AppData, the installer doesn't touch them."""
    args = [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    if restart:
        args.append("/RESTART")      # bchat.iss starts BChat again when it sees this
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0     # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, close_fds=True, creationflags=flags)


class Updater(QObject):
    changed = Signal()

    def __init__(self, cfg, cfg_dir: Path, parent=None, url: str | None = None, current: str | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.dir = Path(cfg_dir) / "updates"
        self.url = UPDATE_URL if url is None else url
        self.current = current or full_version()
        self.state = NONE
        self.entry: dict | None = None
        self.reason = ""
        self.progress = 0
        self.manual = False
        self.install_after = False        # Install Now pressed before the download finished
        self._download_after_check = False
        self.launcher = launch_installer
        self.can_install = getattr(sys, "frozen", False)
        self.net = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._file = None
        self._hash = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.check(manual=False))
        self._resume_ready()

    # --- state ----------------------------------------------------------------------

    def _set(self, state: str, reason: str = "") -> None:
        self.state, self.reason = state, reason
        self.changed.emit()

    def want_test(self) -> bool:
        return bool(self.cfg.update_test_versions) or is_test(self.current)

    def visible(self) -> bool:
        """The menu bar entry shows only when there's something to do or something going on."""
        return self.state in (AVAILABLE, DOWNLOADING, READY, FAILED)

    def label(self) -> str:
        v = (self.entry or {}).get("version", "")
        return {AVAILABLE: f"Update {v}",
                DOWNLOADING: f"Downloading {v} · {self.progress}%",
                READY: f"{v} ready · installs when you quit",
                FAILED: "Update failed"}.get(self.state, "")

    def tooltip(self) -> str:
        v = (self.entry or {}).get("version", "")
        return {AVAILABLE: f"BChat {v} is available (you have {self.current}). Click for details.",
                DOWNLOADING: f"Downloading BChat {v}",
                READY: f"BChat {v} is downloaded and installs when you quit. Click to install now.",
                FAILED: self.reason}.get(self.state, "")

    def _resume_ready(self) -> None:
        """A download from an earlier run: still ready if it's newer than what's running and still checks out."""
        path, entry = self.cfg.update_ready_file, self.cfg.update_ready_entry
        if not path:
            return
        ok = (isinstance(entry, dict) and Path(path).is_file()
              and version_key(entry.get("version", "")) > version_key(self.current)
              and signature_ok(entry) and _sha256(Path(path)) == entry.get("sha256", "").lower())
        if ok:
            self.entry, self.state = entry, READY
        else:
            self._forget_ready(delete=True)

    def _forget_ready(self, delete: bool) -> None:
        if delete and self.cfg.update_ready_file:
            try:
                Path(self.cfg.update_ready_file).unlink(missing_ok=True)
            except OSError:
                pass
        self.cfg.update_ready_file, self.cfg.update_ready_entry = "", None

    # --- checking -------------------------------------------------------------------

    def start(self) -> None:
        """At start-up: first check a few seconds in, then once a day."""
        if self.cfg.update_check and self.url:
            self.timer.start(5000)

    def check(self, manual: bool = False) -> None:
        if self.state in (DOWNLOADING, CHECKING):
            return
        self.manual = manual
        if self.state == READY:
            if manual:
                self.changed.emit()
            return
        if not self.url:
            if manual:
                self._set(FAILED, "This build has no update address yet, so it can't look for updates.")
            return
        self._set(CHECKING)
        req = QNetworkRequest(QUrl(self.url))
        req.setRawHeader(b"User-Agent", f"BChat/{self.current}".encode())
        req.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute, QNetworkRequest.CacheLoadControl.AlwaysNetwork)
        req.setTransferTimeout(20000)
        reply = self.net.get(req)
        reply.finished.connect(lambda: self._checked(reply))

    def _checked(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        self.cfg.update_last_check = time.time()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return self._check_failed(f"Couldn't check for updates: {_why(reply)}")
        try:
            manifest = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._check_failed("Couldn't check for updates: the update file is damaged.")
        entry = pick(manifest, self.current, self.want_test())
        if entry is None:
            self.entry = None
            self._set(UPTODATE if self.manual else NONE)
            self.timer.start(DAY_MS) if self.cfg.update_check else None
            return
        if not signature_ok(entry):
            return self._check_failed(f"BChat {entry.get('version')} isn't signed by BajuBesi Labs, so it was left alone.")
        self.entry = entry
        self._set(AVAILABLE)
        if self.cfg.update_check:
            self.timer.start(DAY_MS)
        if self.cfg.update_auto_download or self._download_after_check:
            self._download_after_check = False
            self.download()

    def _check_failed(self, reason: str) -> None:
        """A background check that fails stays quiet and tries again in an hour; only a check you asked for says so."""
        if self.manual:
            self._set(FAILED, reason)
        else:
            self._set(NONE, reason)
            if self.cfg.update_check:
                self.timer.start(RETRY_MS)

    def dismiss(self) -> None:
        """Close on a failure or an up-to-date answer: the entry goes away until the next check."""
        if self.state in (FAILED, UPTODATE, CHECKING):
            self._set(AVAILABLE if self.entry and self.state == FAILED and self._downloadable() else NONE)

    def retry(self) -> None:
        """Try Again: look at the server afresh (it may have been fixed), then carry on where it failed."""
        self._download_after_check = bool(self.entry) and self._downloadable()
        self.state = NONE
        self.check(manual=True)

    def _downloadable(self) -> bool:
        return bool(self.entry) and version_key(self.entry.get("version", "")) > version_key(self.current)

    # --- downloading ----------------------------------------------------------------

    def download(self, install_after: bool = False) -> None:
        self.install_after = self.install_after or install_after
        if self.state == READY:
            if self.install_after:
                self.install_now()
            return
        if self.state == DOWNLOADING or not self.entry:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", f"BChat-{self.entry['version']}-setup.exe")
        self._target = self.dir / name
        self._part = self.dir / (name + ".part")
        try:
            self._file = open(self._part, "wb")
        except OSError as e:
            return self._set(FAILED, f"Couldn't save the update: {e.strerror}")
        self._hash = hashlib.sha256()
        self.progress = 0
        self._set(DOWNLOADING)
        req = QNetworkRequest(QUrl(self.entry["url"]))
        req.setRawHeader(b"User-Agent", f"BChat/{self.current}".encode())
        req.setTransferTimeout(60000)
        self._reply = self.net.get(req)
        self._reply.readyRead.connect(self._chunk)
        self._reply.downloadProgress.connect(self._progress)
        self._reply.finished.connect(self._downloaded)

    def _chunk(self) -> None:
        data = bytes(self._reply.readAll())
        self._hash.update(data)
        self._file.write(data)

    def _progress(self, got: int, total: int) -> None:
        total = total if total > 0 else int(self.entry.get("size") or 0)
        pct = min(99, int(got * 100 / total)) if total > 0 else 0
        if pct != self.progress:
            self.progress = pct
            self.changed.emit()

    def cancel(self) -> None:
        if self.state == DOWNLOADING and self._reply is not None:
            self._cancelled = True
            self._reply.abort()

    def _downloaded(self) -> None:
        reply, self._reply = self._reply, None
        if reply.bytesAvailable():
            self._chunk_from(reply)
        self._file.close()
        reply.deleteLater()
        cancelled = getattr(self, "_cancelled", False)
        self._cancelled = False
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._part.unlink(missing_ok=True)
            self.install_after = False
            if cancelled:
                return self._set(AVAILABLE)
            return self._set(FAILED, f"The download stopped: {_why(reply)}")
        if self._hash.hexdigest() != self.entry.get("sha256", "").lower():
            self._part.unlink(missing_ok=True)
            self.install_after = False
            return self._set(FAILED, "The download didn't match its checksum, so it was thrown away.")
        if not signature_ok(self.entry):
            self._part.unlink(missing_ok=True)
            self.install_after = False
            return self._set(FAILED, "The download isn't signed by BajuBesi Labs, so it was thrown away.")
        try:
            self._target.unlink(missing_ok=True)
            self._part.rename(self._target)
        except OSError as e:
            return self._set(FAILED, f"Couldn't save the update: {e.strerror}")
        self.cfg.update_ready_file, self.cfg.update_ready_entry = str(self._target), dict(self.entry)
        self.progress = 100
        self._set(READY)
        if self.install_after:
            self.install_now()

    def _chunk_from(self, reply) -> None:
        data = bytes(reply.readAll())
        self._hash.update(data)
        self._file.write(data)

    # --- installing -----------------------------------------------------------------

    install_requested = Signal()     # the window closes BChat, then calls install(restart=True)

    def install_now(self) -> None:
        if self.state != READY:
            return self.download(install_after=True)
        if not self.can_install:
            self.install_after = False
            return self._set(FAILED, "Only an installed BChat can update itself. This one runs from source.")
        self.install_requested.emit()

    def install(self, restart: bool) -> bool:
        """Run the installer. Called on quit when an update is ready, and by Install Now."""
        if self.state != READY or not self.cfg.update_ready_file or not self.can_install:
            return False
        path = self.cfg.update_ready_file
        try:
            self.launcher(path, restart)
        except OSError as e:
            self._set(FAILED, f"Windows wouldn't start the installer ({e.strerror}). Antivirus may have blocked it: "
                              "use Download to get it from the website instead.")
            return False
        return True

    def download_page(self) -> str:
        e = self.entry or self.cfg.update_ready_entry or {}
        return e.get("page") or e.get("url") or ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    except OSError:
        return ""
    return h.hexdigest()


def _why(reply: QNetworkReply) -> str:
    """A short reason, without the long web address Qt puts in its own messages."""
    code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    if code:
        text = reply.attribute(QNetworkRequest.Attribute.HttpReasonPhraseAttribute) or ""
        return f"the update server answered {code} {text}".strip() + "."
    E = QNetworkReply.NetworkError
    plain = {E.ConnectionRefusedError: "the update server refused the connection.",
             E.HostNotFoundError: "the update server wasn't found (no internet?).",
             E.TimeoutError: "the update server didn't answer in time.",
             E.OperationCanceledError: "the update server didn't answer in time.",
             E.SslHandshakeFailedError: "the secure connection to the update server failed.",
             E.TemporaryNetworkFailureError: "the network is down.",
             E.NetworkSessionFailedError: "the network is down."}
    return plain.get(reply.error(), reply.errorString().split(" - ")[-1].rstrip(".") + ".")
