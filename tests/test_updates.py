"""Updates against a local fake release server: check, download, checksum, signature, install, the entry after Help."""
import base64
import hashlib
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bchat import updater as up
from bchat.config import Config


def wait(app, cond, ms=5000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Serves tmp_path/www; a test key stands in for the release key."""
    www = tmp_path / "www"
    www.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(www)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)).decode()
    monkeypatch.setattr(up, "PUBLIC_KEY", pub)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def release(version, channel="stable", payload=None, sign=True, sha=None, extra=None):
        data = payload if payload is not None else (b"MZ fake installer " + version.encode()) * 5000
        (www / f"BChat-{version}-setup.exe").write_bytes(data)
        digest = sha or hashlib.sha256(data).hexdigest()
        entry = {"version": version, "date": "12 Nov 2026", "size": len(data), "url": f"{base}/BChat-{version}-setup.exe",
                 "page": f"{base}/page", "sha256": digest, "notes": ["Colours 16-98", "SSL warning"], "notes_url": f"{base}/notes"}
        entry["sig"] = base64.b64encode(key.sign(up.signed_text(entry))).decode() if sign else ""
        entry.update(extra or {})
        mp = www / "latest.json"
        m = json.loads(mp.read_text()) if mp.exists() else {}
        m[channel] = entry
        mp.write_text(json.dumps(m))
        return entry

    yield base, release
    httpd.shutdown()


def make(app, tmp_path, base, current="0.1.0", **cfg):
    c = Config(nick="x")
    for k, v in cfg.items():
        setattr(c, k, v)
    u = up.Updater(c, tmp_path / "cfg", url=f"{base}/latest.json", current=current)
    u.can_install = True
    u.launched = []
    u.launcher = lambda path, restart: u.launched.append((path, restart))
    return u


def test_version_order():
    k = up.version_key
    assert k("0.1.0-TEST17") < k("0.1.0-TEST18") < k("0.1.0") < k("0.1.1") < k("0.2") < k("1.0.0")
    assert k("0.1.0-test.3") == k("0.1.0-TEST3")
    assert up.is_test("0.1.0-TEST17") and not up.is_test("0.1.0")
    assert k("garbage") < k("0.0.1")


def test_up_to_date_shows_nothing_and_manual_check_says_so(app, tmp_path, server):
    base, release = server
    release("0.1.0")
    u = make(app, tmp_path, base)
    u.check()
    assert wait(app, lambda: u.state != up.CHECKING)
    assert u.state == up.NONE and not u.visible() and u.label() == ""
    u.check(manual=True)
    assert wait(app, lambda: u.state == up.UPTODATE)
    assert not u.visible()


def test_available_then_download_then_ready_then_installs_on_quit(app, tmp_path, server):
    base, release = server
    e = release("0.1.1")
    u = make(app, tmp_path, base)
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    assert u.visible() and u.label() == "Update 0.1.1" and "you have 0.1.0" in u.tooltip()
    seen = []
    u.changed.connect(lambda: seen.append(u.label()))
    u.download()
    assert wait(app, lambda: u.state == up.READY)
    assert any(s.startswith("Downloading 0.1.1 · ") for s in seen)
    assert u.label() == "0.1.1 ready · installs when you quit"
    f = Path(u.cfg.update_ready_file)
    assert f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest() == e["sha256"]
    assert not f.with_name(f.name + ".part").exists()
    assert u.install(restart=False) and u.launched == [(str(f), False)]


def test_ready_survives_a_restart_and_is_cleared_after_the_install(app, tmp_path, server):
    base, release = server
    release("0.1.1")
    u = make(app, tmp_path, base)
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    u.download()
    assert wait(app, lambda: u.state == up.READY)
    again = up.Updater(u.cfg, tmp_path / "cfg", url=u.url, current="0.1.0")
    assert again.state == up.READY and again.entry["version"] == "0.1.1"
    path = u.cfg.update_ready_file
    after = up.Updater(u.cfg, tmp_path / "cfg", url=u.url, current="0.1.1")    # the installer ran
    assert after.state == up.NONE and u.cfg.update_ready_file == "" and not Path(path).exists()


def test_tampered_download_is_thrown_away(app, tmp_path, server):
    base, release = server
    release("0.1.1", sha="0" * 64)          # signed, but the file doesn't match
    u = make(app, tmp_path, base)
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    u.download()
    assert wait(app, lambda: u.state == up.FAILED)
    assert "checksum" in u.reason and u.label() == "Update failed" and u.visible()
    assert u.cfg.update_ready_file == "" and not list((tmp_path / "cfg" / "updates").glob("*"))
    assert u.download_page().endswith("/page")
    assert not u.install(restart=False) and u.launched == []


def test_unsigned_release_is_never_offered(app, tmp_path, server):
    base, release = server
    release("0.1.1", sign=False)
    u = make(app, tmp_path, base)
    u.check()
    assert wait(app, lambda: u.state != up.CHECKING)
    assert u.state == up.NONE and "isn't signed" in u.reason      # quiet in the background
    u.check(manual=True)
    assert wait(app, lambda: u.state == up.FAILED) and "isn't signed" in u.reason


def test_signature_covers_the_version(app, tmp_path, server):
    base, release = server
    e = release("0.1.1")
    forged = dict(e, version="9.9.9")       # same file and signature, bigger number
    assert up.signature_ok(e) and not up.signature_ok(forged)


def test_no_network_is_quiet_in_the_background_and_explained_when_asked(app, tmp_path):
    c = Config(nick="x")
    u = up.Updater(c, tmp_path / "cfg", url="http://127.0.0.1:9/latest.json", current="0.1.0")
    u.check()
    assert wait(app, lambda: u.state != up.CHECKING, 25000)
    assert u.state == up.NONE and not u.visible() and u.timer.isActive()      # tries again in an hour
    assert u.timer.remainingTime() > 3500 * 1000
    u.check(manual=True)
    assert wait(app, lambda: u.state != up.CHECKING, 25000)
    assert u.state == up.FAILED and u.reason.startswith("Couldn't check for updates")


def test_no_address_in_this_build(app, tmp_path):
    u = up.Updater(Config(nick="x"), tmp_path / "cfg", url="", current="0.1.0")
    u.start()
    assert not u.timer.isActive()
    u.check()
    assert u.state == up.NONE
    u.check(manual=True)
    assert u.state == up.FAILED and "no update address" in u.reason


def test_test_versions_only_when_wanted_or_running_a_test(app, tmp_path, server):
    base, release = server
    release("0.1.0")
    release("0.1.1-TEST3", channel="test")
    u = make(app, tmp_path, base)
    u.check()
    assert wait(app, lambda: u.state != up.CHECKING) and u.state == up.NONE
    u2 = make(app, tmp_path, base, update_test_versions=True)
    u2.check()
    assert wait(app, lambda: u2.state == up.AVAILABLE) and u2.entry["version"] == "0.1.1-TEST3"
    u3 = make(app, tmp_path, base, current="0.1.0-TEST17")       # a TEST build looks by itself
    u3.check()
    assert wait(app, lambda: u3.state == up.AVAILABLE) and u3.entry["version"] == "0.1.1-TEST3"


def test_auto_download_and_install_now_before_the_download_finished(app, tmp_path, server):
    base, release = server
    release("0.1.1")
    u = make(app, tmp_path, base, update_auto_download=True)
    asked = []
    u.install_requested.connect(lambda: asked.append(True))
    u.check()
    assert wait(app, lambda: u.state in (up.DOWNLOADING, up.READY))
    u.install_now()                        # pressed while downloading
    assert wait(app, lambda: u.state == up.READY)
    assert wait(app, lambda: asked == [True])


def test_cancel_goes_back_to_available(app, tmp_path, server):
    base, release = server
    release("0.1.1", payload=b"x" * 30_000_000)
    u = make(app, tmp_path, base)
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    u.download()
    assert u.state == up.DOWNLOADING
    u.cancel()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    assert not list((tmp_path / "cfg" / "updates").glob("*.part"))


def test_from_source_install_now_explains(app, tmp_path, server):
    base, release = server
    release("0.1.1")
    u = make(app, tmp_path, base)
    u.can_install = False
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    u.download()
    assert wait(app, lambda: u.state == up.READY)
    u.install_now()
    assert u.state == up.FAILED and "runs from source" in u.reason


def test_blocked_installer_offers_the_download_page(app, tmp_path, server):
    base, release = server
    release("0.1.1")
    u = make(app, tmp_path, base)

    def blocked(path, restart):
        raise PermissionError(5, "Access is denied")
    u.launcher = blocked
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    u.download()
    assert wait(app, lambda: u.state == up.READY)
    assert not u.install(restart=True)
    assert u.state == up.FAILED and "Antivirus" in u.reason and u.download_page()


# --- the window -----------------------------------------------------------------------

@pytest.fixture
def win(app, tmp_path):
    from bchat.mainwindow import MainWindow
    w = MainWindow(Config(nick="x", skip_network_list=True), tmp_path / "wcfg")
    w.skip_quit_prompt = True
    w.resize(900, 400)
    w.show()
    wait(app, lambda: False, 100)
    yield w
    if w.update_window:
        w.update_window.close()
    w.updater.cancel()
    w.hide()


def test_entry_after_help_shows_only_with_something_to_do(app, tmp_path, server, win):
    base, release = server
    release("0.1.1")
    u = win.updater
    u.url, u.current = f"{base}/latest.json", "0.1.0"
    acts = win.menubar_.actions()
    assert acts[-1] is win.update_act and acts[-2].text() == "&Help"
    assert not win.update_act.isVisible() and not win.update_badge.isVisible()
    help_names = [a.text() for a in acts[-2].menu().actions()]
    assert "Check for &Updates..." in help_names
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    wait(app, lambda: False, 50)
    assert win.update_act.isVisible() and win.update_badge.isVisible()
    help_geo = win.menubar_.actionGeometry(acts[-2])
    geo = win.menubar_.actionGeometry(win.update_act)
    assert geo.left() >= help_geo.right() and win.update_badge.geometry() == geo
    assert "0.1.1" in win.update_badge.toolTip()
    # the light is amber, and the words fit inside the entry
    img = win.update_badge.grab().toImage()
    cols = {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())}
    assert "#f9e2af" in cols
    # clicking the entry opens the window
    win.update_act.trigger()
    assert win.update_window is not None and win.update_window.isVisible()
    d = win.update_window
    assert d.head.text() == "BChat 0.1.1 is available" and d.on_quit.isVisible() and d.now.isVisible() and d.later.isVisible()
    assert d.on_quit.isDefault() and "Colours 16-98" in d.news.text() and "Full release notes" in d.news.text()
    assert "Networks set to connect on start" in d.note.text()
    # Install When I Quit downloads, the entry turns green
    d.on_quit.click()
    assert wait(app, lambda: u.state == up.READY)
    wait(app, lambda: False, 50)
    img = win.update_badge.grab().toImage()
    assert "#a6e3a1" in {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())}
    assert win.update_badge.width() > 150        # "0.1.1 ready · installs when you quit" has room


def test_manual_check_up_to_date_window_then_entry_stays_hidden(app, tmp_path, server, win):
    base, release = server
    release("0.1.0")
    u = win.updater
    u.url, u.current = f"{base}/latest.json", "0.1.0"
    win.check_updates()
    d = win.update_window
    assert d.isVisible()
    assert wait(app, lambda: u.state == up.UPTODATE)
    assert d.head.text() == "BChat is up to date" and d.close_btn.isVisible() and not d.now.isVisible()
    assert not win.update_act.isVisible()
    d.close_btn.click()
    assert wait(app, lambda: u.state == up.NONE)


def test_failed_window_has_try_again_and_download(app, tmp_path, server, win):
    base, release = server
    release("0.1.1", sha="1" * 64)
    u = win.updater
    u.url, u.current = f"{base}/latest.json", "0.1.0"
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    u.download()
    assert wait(app, lambda: u.state == up.FAILED)
    wait(app, lambda: False, 50)
    img = win.update_badge.grab().toImage()
    assert "#fab387" in {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())}
    d = win.open_update_window()
    assert d.head.text() == "Update failed" and d.retry.isVisible() and d.page.isVisible() and d.retry.isDefault()
    release("0.1.1")                       # fixed on the server
    d.retry.click()
    assert wait(app, lambda: u.state == up.READY)


def test_quit_runs_a_ready_installer_and_install_now_restarts(app, tmp_path, server, win):
    base, release = server
    release("0.1.1")
    u = win.updater
    u.url, u.current = f"{base}/latest.json", "0.1.0"
    u.can_install = True
    launched = []
    u.launcher = lambda path, restart: launched.append(restart)
    u.check()
    assert wait(app, lambda: u.state == up.AVAILABLE)
    u.download()
    assert wait(app, lambda: u.state == up.READY)
    quits = []
    win.quit_requested.connect(lambda: quits.append(True))
    u.install_now()
    assert launched == [True] and quits == [True]
    # settings saved before the installer ran, with the ready file noted
    saved = json.loads((tmp_path / "wcfg" / "config.json").read_text(encoding="utf-8"))
    assert saved["update_ready_file"].endswith("BChat-0.1.1-setup.exe")


def test_preferences_update_options_save(app, tmp_path, win):
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    assert d.upd_check.isChecked() and not d.upd_auto.isChecked() and not d.upd_test.isChecked()
    d.upd_check.setChecked(False)
    d.upd_auto.setChecked(True)
    d.upd_test.setChecked(True)
    win.updater.timer.start(60000)
    d.accept()
    c = win.cfg
    assert (c.update_check, c.update_auto_download, c.update_test_versions) == (False, True, True)
    assert not win.updater.timer.isActive()        # off means no more daily checks


def test_failure_reasons_are_short(app, tmp_path, server):
    base, release = server
    u = up.Updater(Config(nick="x"), tmp_path / "cfg", url=f"{base}/missing.json", current="0.1.0")
    u.check(manual=True)
    assert wait(app, lambda: u.state == up.FAILED)
    assert u.reason == "Couldn't check for updates: the update server answered 404 File not found." and "http" not in u.reason
