"""0.9.0 Linux updater: its own signed update file, and the AppImage swapped in place (Option C: same file name).
The signature checks run on every OS; the file swap needs Linux (rename over a file, exec bits, /bin/sh)."""
import base64
import os
import stat
import subprocess
import sys
import time

import pytest

from bchat import updater as up

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the AppImage swap is Linux only")


def _signed(entry: dict, linux: bool):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    entry = dict(entry, sig=base64.b64encode(key.sign(up.signed_text(entry, linux))).decode())
    return entry, pub


def test_a_linux_entry_never_checks_out_on_windows_and_the_other_way_round():
    e = {"version": "0.9.1", "sha256": "ab" * 32}
    lin, pub = _signed(e, linux=True)
    assert up.signature_ok(lin, pub, linux=True)
    assert not up.signature_ok(lin, pub, linux=False)
    win, pub = _signed(e, linux=False)
    assert up.signature_ok(win, pub, linux=False)
    assert not up.signature_ok(win, pub, linux=True)
    # the Windows signed text is exactly what it always was (every released Windows BChat checks it)
    assert up.signed_text(e, linux=False) == b"0.9.1\n" + b"ab" * 32


def test_each_system_reads_its_own_update_file():
    assert up.UPDATE_ASSET == ("bchat-update-linux.json" if up.LINUX else "bchat-update.json")


def _appimage(path, text):
    path.write_text(f"#!/bin/sh\n{text}\n")
    path.chmod(0o755)
    return path


@linux_only
def test_swap_puts_the_new_appimage_in_place_under_the_same_name(tmp_path):
    apps = tmp_path / "Applications"
    apps.mkdir()
    old = _appimage(apps / "BChat-x86_64.AppImage", "echo old")
    new = _appimage(tmp_path / "download.AppImage", "echo new")
    new.chmod(0o644)                                   # a download has no exec bit; the swap gives it one
    up.swap_appimage(str(new), restart=False, target=str(old))
    assert old.read_text() == new.read_text()
    assert old.stat().st_mode & stat.S_IXUSR
    assert sorted(p.name for p in apps.iterdir()) == ["BChat-x86_64.AppImage"]      # no .new left behind


@linux_only
def test_a_failed_swap_leaves_the_old_appimage_alone(tmp_path):
    apps = tmp_path / "ro"
    apps.mkdir()
    old = _appimage(apps / "BChat-x86_64.AppImage", "echo old")
    new = _appimage(tmp_path / "download.AppImage", "echo new")
    apps.chmod(0o555)                                  # a folder BChat can't write to
    try:
        if os.access(apps, os.W_OK):
            pytest.skip("running as root: folder permissions don't apply")
        with pytest.raises(PermissionError):
            up.swap_appimage(str(new), restart=False, target=str(old))
        assert old.read_text().endswith("echo old\n")
        assert sorted(p.name for p in apps.iterdir()) == ["BChat-x86_64.AppImage"]
    finally:
        apps.chmod(0o755)


@linux_only
def test_restart_waits_for_the_old_bchat_then_starts_the_new_one(tmp_path):
    marker = tmp_path / "started"
    target = _appimage(tmp_path / "BChat-x86_64.AppImage", "old")
    new = _appimage(tmp_path / "dl", f'touch "{marker}"')
    old_bchat = subprocess.Popen(["sleep", "1.5"])     # stands in for the BChat that is quitting
    t0 = time.time()
    up.swap_appimage(str(new), restart=True, target=str(target), wait_pid=old_bchat.pid)
    time.sleep(0.6)
    assert not marker.exists()                         # not while the old one still runs
    old_bchat.wait()
    deadline = time.time() + 10
    while not marker.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert marker.exists() and time.time() - t0 >= 1.4


@linux_only
def test_from_source_on_linux_names_the_appimage(app, tmp_path, monkeypatch):
    from bchat.config import Config
    monkeypatch.delenv("APPIMAGE", raising=False)
    u = up.Updater(Config(), tmp_path, url="")
    assert u.can_install is False and u.launcher is up.swap_appimage
    u.entry, u.state = {"version": "9.9.9"}, up.READY
    u.install_now()
    assert u.state == up.FAILED and "Only the BChat AppImage can update itself" in u.reason
