"""Flatpak (io.github.fhazal.BChat): Flathub updates it and exports its menu entry, so BChat checks for nothing, writes
no desktop files, and starts at login through the Background portal. The file logic runs on every OS against
throwaway XDG folders; the real portal needs a Linux desktop and is not exercised here."""
import sys
from pathlib import Path

import pytest

from bchat import linuxdesk
from bchat import updater as up
from bchat.config import Config


@pytest.fixture
def flatpak(tmp_path, monkeypatch):
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    monkeypatch.setattr(up, "LINUX", True)
    monkeypatch.setattr(linuxdesk, "FLATPAK_INFO", str(tmp_path / "missing"))     # the FLATPAK_ID alone says it
    monkeypatch.setenv("FLATPAK_ID", linuxdesk.APP_ID)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


def test_in_flatpak_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    none = str(tmp_path / "no-flatpak-info")
    info = tmp_path / ".flatpak-info"
    info.write_text("[Application]\n")
    assert linuxdesk.APP_ID == "io.github.fhazal.BChat"
    assert not linuxdesk.in_flatpak({}, none)
    assert linuxdesk.in_flatpak({"FLATPAK_ID": linuxdesk.APP_ID}, none)
    assert linuxdesk.in_flatpak({}, str(info))
    assert not linuxdesk.in_flatpak({"FLATPAK_ID": ""}, none)
    monkeypatch.setattr(linuxdesk, "SUPPORTED", False)           # Windows and macOS: never
    assert not linuxdesk.in_flatpak({"FLATPAK_ID": linuxdesk.APP_ID}, str(info))


def test_the_appimage_is_not_in_a_flatpak(tmp_path, monkeypatch):
    img = tmp_path / "BChat.AppImage"
    img.write_bytes(b"\x7fELF")
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    monkeypatch.setenv("APPIMAGE", str(img))
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr(linuxdesk, "FLATPAK_INFO", str(tmp_path / "missing"))
    assert not linuxdesk.in_flatpak()
    assert linuxdesk.installed_exe() == str(img)                 # AppImage behaviour as before
    monkeypatch.setenv("FLATPAK_ID", linuxdesk.APP_ID)
    assert linuxdesk.installed_exe() is None


def test_updater_does_nothing_in_a_flatpak(app, flatpak):
    c = Config(nick="x", update_check=True)
    c.update_ready_file, c.update_ready_entry = str(flatpak / "BChat-9.9.9-x86_64.AppImage"), {"version": "9.9.9"}
    u = up.Updater(c, flatpak / "cfg", url="http://127.0.0.1:9/latest.json", current="0.1.0")

    class NoNetwork:
        def get(self, *a):
            raise AssertionError("a Flatpak never touches the network for updates")
    u.net = NoNetwork()
    assert u.inert and not u.can_install
    assert c.update_ready_entry == {"version": "9.9.9"}          # an earlier run's note is left alone, not deleted
    u.start()
    assert not u.timer.isActive()
    u.check()
    u.check(manual=True)
    assert u.state == up.NONE and not u.visible() and u._asking is None
    u.state = up.AVAILABLE                                       # even if something set a state, no menu entry
    assert not u.visible()


def test_updater_still_works_outside_a_flatpak(app, tmp_path, monkeypatch):
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr(linuxdesk, "FLATPAK_INFO", str(tmp_path / "missing"))
    u = up.Updater(Config(nick="x", update_check=True), tmp_path / "cfg", url="http://127.0.0.1:9/latest.json",
                   current="0.1.0")
    assert not u.inert
    u.start()
    assert u.timer.isActive()
    u.state = up.AVAILABLE
    assert u.visible()
    u.timer.stop()                 # else its check fires 5 s later, inside some other test, on a dead updater
    u.deleteLater()


def test_a_flatpak_writes_no_desktop_files(flatpak):
    exe = flatpak / "BChat.AppImage"                             # even if an exe were passed in
    exe.write_bytes(b"\x7fELF")
    assert linuxdesk.sync_menu(True, True, str(exe)) == "skipped"
    linuxdesk.set_default_links(True)
    assert linuxdesk.sync_autostart(False, str(exe)) == "ok"
    assert not (flatpak / "data").exists() and not (flatpak / "config").exists()


def test_start_at_login_goes_through_the_portal(flatpak, monkeypatch):
    sent = []
    monkeypatch.setattr(linuxdesk, "request_background", lambda on, *a, **k: sent.append(on) or "requested")
    assert linuxdesk.sync_autostart(True, None) == "requested"                    # at start, ticked
    assert linuxdesk.sync_autostart(False, None) == "ok"                          # at start, unticked: nothing to say
    assert linuxdesk.sync_autostart(False, None, changed=True) == "requested"     # the tick was just removed
    assert sent == [True, False]
    assert not (flatpak / "config").exists()


def test_the_window_sets_autostart_through_the_portal(app, flatpak, monkeypatch):
    from bchat.mainwindow import MainWindow
    sent = []
    monkeypatch.setattr(linuxdesk, "request_background", lambda on, *a, **k: sent.append(on) or "requested")
    win = MainWindow.__new__(MainWindow)                         # only the two methods under test; no window needed
    MainWindow.set_autostart(win, True)
    MainWindow.set_autostart(win, False)
    assert sent == [True, False]
    assert not (flatpak / "data").exists() and not (flatpak / "config").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="autostart.sync takes the Windows branch elsewhere")
def test_the_start_check_asks_the_portal_only_when_ticked(app, flatpak, monkeypatch):
    from bchat.mainwindow import MainWindow
    sent = []
    monkeypatch.setattr(linuxdesk, "request_background", lambda on, *a, **k: sent.append(on) or "requested")
    win = MainWindow.__new__(MainWindow)
    win.cfg = Config(nick="x", start_with_windows=True, app_menu=True, irc_links=True)
    MainWindow.check_autostart(win)
    win.cfg.start_with_windows = False
    MainWindow.check_autostart(win)
    assert sent == [True]
    assert not (flatpak / "data").exists() and not (flatpak / "config").exists()


@pytest.fixture
def jeepney():
    return pytest.importorskip("jeepney", reason="the portal call is Linux only (jeepney)")


def test_the_background_request_is_built_for_the_portal(jeepney):
    msg = linuxdesk.background_message(True)
    assert msg.header.message_type.name == "method_call"
    f = msg.header.fields
    assert f[jeepney.HeaderFields.destination] == "org.freedesktop.portal.Desktop"
    assert f[jeepney.HeaderFields.path] == "/org/freedesktop/portal/desktop"
    assert f[jeepney.HeaderFields.interface] == "org.freedesktop.portal.Background"
    assert f[jeepney.HeaderFields.member] == "RequestBackground"
    assert f[jeepney.HeaderFields.signature] == "sa{sv}"
    parent, options = msg.body
    assert parent == ""
    assert options == {"reason": ("s", "Start BChat when you log in"), "autostart": ("b", True),
                       "commandline": ("as", ["bchat"]), "dbus-activatable": ("b", False)}
    assert linuxdesk.background_message(False).body[1]["autostart"] == ("b", False)
    msg.serialise(1)                                            # the body really encodes against its signature


class FakeConn:
    def __init__(self):
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_and_get_reply(self, msg, timeout=None):
        self.sent.append((msg, timeout))


def test_the_request_is_sent_on_the_session_bus_with_a_timeout(jeepney):
    conn, buses = FakeConn(), []

    def opener(bus):
        buses.append(bus)
        return conn
    assert linuxdesk.request_background(True, opener=opener, block=True) == "requested"
    assert buses == ["SESSION"]
    (msg, timeout), = conn.sent
    assert msg.header.fields[jeepney.HeaderFields.member] == "RequestBackground" and 0 < timeout <= 10


def test_a_missing_portal_never_raises(jeepney):
    def broken(bus):
        raise OSError("no session bus")
    assert linuxdesk.request_background(True, opener=broken, block=True) == "requested"


def test_received_files_go_to_downloads_in_a_flatpak(monkeypatch, tmp_path):
    from bchat import dcc
    assert dcc.default_folder(tmp_path) == tmp_path / "downloads"
    monkeypatch.setattr(linuxdesk, "in_flatpak", lambda *a, **k: True)
    assert dcc.default_folder(tmp_path) != tmp_path / "downloads"


def test_version_flag_reports_the_build_version(monkeypatch, capsys):
    import pytest
    import bchat
    from bchat import __main__ as m
    monkeypatch.setattr(m, "full_version", lambda: "9.9.9")
    monkeypatch.setattr(bchat, "full_version", lambda: "9.9.9")
    with pytest.raises(SystemExit):
        m.main(["--version"])
    assert "9.9.9" in capsys.readouterr().out


def _window(flatpak):
    from bchat.mainwindow import MainWindow
    win = MainWindow(Config(nick="x", skip_network_list=True), flatpak / "cfg")
    win.skip_quit_prompt = True
    return win


def _help_items(win):
    m = [a for a in win.menubar_.actions() if "Help" in a.text()][0].menu()
    return {a.text().replace("&", ""): a.isVisible() for a in m.actions() if a.text()}


def test_a_flatpak_hides_every_update_control(app, flatpak):
    """Option A: the software centre updates a Flatpak, so BChat shows nothing it can't do."""
    from bchat.about import AboutDialog
    from bchat.preferences import PreferencesDialog
    win = _window(flatpak)
    u = win.updater
    assert u.inert
    u.state, u.entry = up.AVAILABLE, {"version": "9.9.9"}          # even with news, nothing appears
    u.changed.emit()
    assert _help_items(win)["Check for Updates..."] is False
    assert _help_items(win)["About"] is True
    assert not win.update_act.isVisible()
    d = AboutDialog(win.cfg.theme, win, u)
    assert "updated by your software centre" in d.update_status.text()
    assert "9.9.9" not in d.update_status.text() and d.update_icon.isHidden()
    p = PreferencesDialog(win, "General")
    assert p._items["Updates"].isHidden() and not p._items["Lock"].isHidden()
    assert p.app_menu.isHidden() and p.irc_links.isHidden() and not p.start_win.isHidden()
    assert "desktop asks" in p.start_win.toolTip()
    for w in (p, d, win):
        w.close()


def test_outside_a_flatpak_the_update_controls_stay(app, tmp_path, monkeypatch):
    from bchat.about import AboutDialog
    from bchat.preferences import PreferencesDialog
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)               # the AppImage
    monkeypatch.setattr(linuxdesk, "FLATPAK_INFO", str(tmp_path / "missing"))
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    win = _window(tmp_path)
    assert not win.updater.inert
    assert _help_items(win)["Check for Updates..."] is True
    win.updater.cfg.update_last_check = 1
    d = AboutDialog(win.cfg.theme, win, win.updater)
    assert "Up to date" in d.update_status.text() and not d.update_icon.isHidden()
    p = PreferencesDialog(win, "General")
    assert not p._items["Updates"].isHidden()
    assert not p.app_menu.isHidden() and not p.irc_links.isHidden()
    assert "AppImage" in p.start_win.toolTip()
    for w in (p, d, win):
        w.close()


MANIFEST = Path(__file__).resolve().parent.parent / "packaging" / "flatpak" / "io.github.fhazal.BChat.yml"


def _finish_args():
    text = MANIFEST.read_text(encoding="utf-8")
    block = text.split("finish-args:", 1)[1].split("\nbuild-options:", 1)[0]
    return [ln.strip()[2:] for ln in block.splitlines() if ln.strip().startswith("- ")]


def test_the_flatpak_runs_on_x11_so_cards_land_in_the_corner():
    """Wayland ignores move(): the notification cards need X11 (XWayland), the same as the AppImage."""
    args = _finish_args()
    assert "--socket=x11" in args
    assert not any(a in args for a in ("--socket=wayland", "--socket=fallback-x11"))


def test_the_flatpak_can_speak():
    """Qt's speechd engine is built in and reaches the desktop's speech-dispatcher through its socket."""
    args = _finish_args()
    assert "--filesystem=xdg-run/speech-dispatcher:ro" in args
    assert "--env=QT_PLUGIN_PATH=/app/lib/plugins" in args
    text = MANIFEST.read_text(encoding="utf-8")
    assert "name: libspeechd" in text and "name: qtspeech-speechd" in text
    assert "lib/plugins/texttospeech" in text
