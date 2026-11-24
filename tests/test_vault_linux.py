"""Linux passwords: the desktop keyring (Secret Service). Never a plain file when there is no keyring."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from bchat import config, vault

SECRET = "hunter2-linux"


def net_cfg():
    return config.Config(nick="x", networks=[config.NetworkConfig("SkinIRC", [config.Server("irc.example.test", 6697, True)],
                                                                  password=SECRET)])


def test_no_keyring_on_linux_keeps_no_passwords_anywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "LINUX", True)
    monkeypatch.setattr(vault, "put", lambda folder, text: False)
    cfg = net_cfg()
    config.save(cfg, tmp_path)
    text = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert SECRET not in text and json.loads(text)["secrets"] == "nostore"
    assert not (tmp_path / "vault-test.json").exists()
    assert cfg.networks[0].password == SECRET            # this session still has it: only the disk copy is skipped
    back = config.load(tmp_path)
    assert back.networks[0].password == "" and back.no_password_store and back.networks[0].name == "SkinIRC"


def test_windows_without_vault_still_keeps_the_old_file_way(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "LINUX", False)
    monkeypatch.setattr(vault, "put", lambda folder, text: False)
    config.save(net_cfg(), tmp_path)
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["secrets"] == "file"


def test_linux_follows_the_windows_rules_for_the_stand_in(tmp_path, monkeypatch):
    # 0.8.x said "not Windows = stand-in" everywhere, which on Linux meant a plain vault-test.json
    monkeypatch.setenv("BCHAT_VAULT", "")
    monkeypatch.setattr(vault.os, "name", "posix")
    monkeypatch.setattr(vault.sys, "frozen", True, raising=False)
    assert not vault._memory_mode(tmp_path)


def test_keyring_trouble_is_a_refusal_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("BCHAT_VAULT", "")
    monkeypatch.setattr(vault, "LINUX", True)
    monkeypatch.setattr(vault, "_memory_mode", lambda folder=None: False)
    monkeypatch.setitem(sys.modules, "secretstorage", None)          # not installed -> ImportError
    assert vault.put(tmp_path, "x") is False
    assert vault.get(tmp_path) is None
    vault.clear(tmp_path)


KEYRING = pytest.mark.skipif(not sys.platform.startswith("linux") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
                             or shutil.which("gnome-keyring-daemon") is None, reason="needs a Linux keyring on D-Bus")


@pytest.fixture
def keyring(monkeypatch):
    """A throwaway GNOME Keyring on this test's own session bus, unlocked with an empty password."""
    proc = subprocess.run(["gnome-keyring-daemon", "--replace", "--unlock", "--components=secrets", "--daemonize"],
                          input=b"\n", capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    monkeypatch.setenv("BCHAT_VAULT", "")
    monkeypatch.setattr(vault, "_memory_mode", lambda folder=None: False)
    yield


@KEYRING
def test_real_keyring_round_trip(tmp_path, keyring):
    long_text = json.dumps({"networks": {f"n{i}": {"password": "p" * 50} for i in range(80)}})
    assert len(long_text.encode()) > 2 * vault.CHUNK
    assert vault.put(tmp_path, long_text) and vault.get(tmp_path) == long_text
    assert vault.put(tmp_path, "short") and vault.get(tmp_path) == "short"
    assert vault._read(vault._target(tmp_path, 1), tmp_path) is None          # the old chunks went
    import secretstorage
    with secretstorage.dbus_init() as conn:
        items = list(secretstorage.get_default_collection(conn).search_items({"application": "BChat"}))
        assert items and all(i.get_label() == vault.LABEL for i in items)
    vault.clear(tmp_path)
    assert vault.get(tmp_path) is None


@KEYRING
def test_real_keyring_through_config(tmp_path, keyring):
    config.save(net_cfg(), tmp_path)
    text = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert SECRET not in text and json.loads(text)["secrets"] == "vault"
    assert not (tmp_path / "vault-test.json").exists()
    assert config.load(tmp_path).networks[0].password == SECRET
    vault.clear(tmp_path)


# --- what Linux users see (Option C + the Linux wording, OK'd 2026-11-24) -------------------------------------

def test_keyring_check_is_yes_on_windows_and_no_without_dbus(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "LINUX", False)
    assert vault.keyring_ok(tmp_path)
    monkeypatch.setattr(vault, "LINUX", True)
    monkeypatch.setattr(vault, "_memory_mode", lambda folder=None: False)
    monkeypatch.setitem(sys.modules, "secretstorage", None)          # not installed: nothing would be kept
    assert not vault.keyring_ok(tmp_path)


def test_no_keyring_box_text():
    assert "never writes them to a plain file" in vault.NO_KEYRING and "Network List" in vault.NO_KEYRING


@pytest.mark.parametrize("linux,ok,shown", [(True, False, True), (True, True, False), (False, False, False)])
def test_grey_line_under_server_password(app, monkeypatch, linux, ok, shown):
    from bchat.networklist import NetworkEditDialog
    monkeypatch.setattr(vault, "LINUX", linux)
    monkeypatch.setattr(vault, "keyring_ok", lambda folder=None: ok)
    d = NetworkEditDialog(net_cfg().networks[0])
    assert (d.keyring_note is not None) == shown
    if shown:
        row = d.form.getWidgetPosition(d.password)[0]
        assert d.form.itemAt(row + 1, d.form.ItemRole.FieldRole).widget() is d.keyring_note
        assert "forgotten" in d.keyring_note.text()
    d.deleteLater()


def test_linux_wording(app, monkeypatch):
    from bchat import about, nowplaying
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("bchat.sysinfo.linux_os_text", lambda: "Fedora Linux 41 64-bit (kernel 6.11.4)")
    assert ("Linux", "Fedora Linux 41 (kernel 6.11.4)") in about.info_rows()
    cfg = config.Config(nick="x")
    assert "doesn't tell the desktop" in nowplaying.choose([], cfg)[1]


def test_windows_wording_unchanged(app, monkeypatch):
    from bchat import about, nowplaying
    monkeypatch.setattr(sys, "platform", "win32")
    assert any(k == "Windows" for k, _ in about.info_rows())
    assert "doesn't tell Windows" in nowplaying.choose([], config.Config(nick="x"))[1]
