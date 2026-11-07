"""Passwords live in Windows Credential Manager, not config.json (a stand-in vault here: BCHAT_VAULT=memory)."""
import json
import tempfile
from pathlib import Path

from bchat import config, vault
from bchat.config import Config, NetworkConfig, Server

SECRETS = ("zncpass:hunter2", "sasl-s3cret", "ns-pass-123", "proxy-pw-9")


def net(name, **kw):
    return NetworkConfig(name, [Server("irc.example.org", 6697, True)], **kw)


def raw(tmp_path):
    return (tmp_path / "config.json").read_text(encoding="utf-8")


def test_passwords_never_in_the_file_and_come_back(tmp_path):
    cfg = Config(nick="x", networks=[net("SkinIRC", password=SECRETS[0], sasl_password=SECRETS[1], nickserv=SECRETS[2]),
                                     net("Libera")], proxy_password=SECRETS[3])
    config.save(cfg, tmp_path)
    text = raw(tmp_path)
    assert not any(s in text for s in SECRETS) and json.loads(text)["secrets"] == "vault"
    back = config.load(tmp_path)
    n = back.networks[0]
    assert (n.password, n.sasl_password, n.nickserv, back.proxy_password) == SECRETS
    assert back.networks[1].password == "" and not getattr(back, "vault_missing", False)


def test_old_plain_text_settings_move_on_the_next_save(tmp_path):
    old = {"nick": "x", "networks": [{"name": "SkinIRC", "servers": [{"host": "h", "port": 6667, "ssl": False}],
                                      "password": SECRETS[0], "nickserv": SECRETS[2]}]}
    (tmp_path / "config.json").write_text(json.dumps(old), encoding="utf-8")
    cfg = config.load(tmp_path)
    assert cfg.networks[0].password == SECRETS[0]           # nothing lost on the way in
    config.save(cfg, tmp_path)
    assert SECRETS[0] not in raw(tmp_path) and SECRETS[2] not in raw(tmp_path)
    assert config.load(tmp_path).networks[0].password == SECRETS[0]


def test_rename_and_same_names_keep_the_right_passwords(tmp_path):
    cfg = Config(nick="x", networks=[net("Twin", password="one"), net("Twin", password="two"), net("Solo", password="three")])
    config.save(cfg, tmp_path)
    back = config.load(tmp_path)
    assert [n.password for n in back.networks] == ["one", "two", "three"]
    back.networks[2].name = "Renamed"
    config.save(back, tmp_path)
    assert config.load(tmp_path).networks[2].password == "three"


def test_windows_refusing_keeps_the_passwords_in_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "put", lambda folder, text: False)
    config.save(Config(nick="x", networks=[net("SkinIRC", password=SECRETS[0])]), tmp_path)
    d = json.loads(raw(tmp_path))
    assert d["secrets"] == "file" and d["networks"][0]["password"] == SECRETS[0]
    monkeypatch.undo()
    assert config.load(tmp_path).networks[0].password == SECRETS[0]


def test_lost_vault_is_noticed_and_nothing_else_breaks(tmp_path):
    config.save(Config(nick="keepme", networks=[net("SkinIRC", password=SECRETS[0])]), tmp_path)
    vault.clear(tmp_path)
    back = config.load(tmp_path)
    assert back.vault_missing and back.nick == "keepme" and back.networks[0].name == "SkinIRC" and back.networks[0].password == ""


def test_long_lists_are_split_across_entries(tmp_path):
    nets = [net(f"Net{i}", password=f"pw-{i}-" + "x" * 60, nickserv=f"ns-{i}") for i in range(80)]
    config.save(Config(nick="x", networks=nets), tmp_path)
    assert vault.get(tmp_path) and vault._read(vault._target(tmp_path, 2), tmp_path) is not None
    back = config.load(tmp_path)
    assert [n.password for n in back.networks] == [n.password for n in nets]
    config.save(Config(nick="x", networks=nets[:1]), tmp_path)           # shorter: old parts removed
    assert vault._read(vault._target(tmp_path, 1), tmp_path) is None


def test_throwaway_folders_never_touch_the_real_credential_manager(monkeypatch, tmp_path):
    monkeypatch.delenv("BCHAT_VAULT", raising=False)
    assert vault._memory_mode(Path(tempfile.gettempdir()) / "anything")
    assert vault._memory_mode(tmp_path)
    if __import__("os").name == "nt":
        assert not vault._memory_mode(Path.home() / "AppData" / "Roaming" / "BChat")
    # a throwaway folder's stand-in survives a restart of the program (a file inside that folder)
    vault.put(tmp_path, "kept")
    vault._memory.clear()
    assert vault.get(tmp_path) == "kept" and (tmp_path / "vault-test.json").exists()


def test_installed_program_always_uses_credential_manager(monkeypatch, tmp_path):
    """The real exe with --config-dir in %TEMP% must not drop passwords into a plain file (found 11-08)."""
    import sys
    monkeypatch.delenv("BCHAT_VAULT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    if __import__("os").name == "nt":
        assert not vault._memory_mode(tmp_path)
        assert not vault._memory_mode(Path(tempfile.gettempdir()) / "bchat-welcome")
    monkeypatch.setenv("BCHAT_VAULT", "file")                         # only the build checks ask for the stand-in
    assert vault._memory_mode(tmp_path)
    monkeypatch.setenv("BCHAT_VAULT", "memory")
    assert vault._memory_mode(tmp_path)
