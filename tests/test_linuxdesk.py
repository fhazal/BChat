"""Phase 2 Linux: BChat's own desktop entries (app menu + irc:// links, start when I log in) and their Settings boxes.
The file logic runs on every OS against throwaway XDG folders; the real desktop tools are checked on Linux."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bchat import linuxdesk
from bchat.config import Config


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    exe = tmp_path / "apps" / "BChat-0.9.0-x86_64.AppImage"
    exe.parent.mkdir()
    exe.write_bytes(b"\x7fELF")
    return tmp_path, str(exe)


def mime(tmp_path):
    p = tmp_path / "config" / "mimeapps.list"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_exec_line_quoting():
    assert linuxdesk.exec_line("/opt/BChat.AppImage", True) == "/opt/BChat.AppImage %u"
    assert linuxdesk.exec_line("/home/me/My Apps/BChat.AppImage", False) == '"/home/me/My Apps/BChat.AppImage"'
    # " ` $ \ get a backslash inside the quotes, then every backslash is doubled for the file; % becomes %%
    assert linuxdesk.exec_line('/x/a$b"c\\d 100%.AppImage', True) == '"/x/a\\\\$b\\\\"c\\\\\\\\d 100%%.AppImage" %u'


def test_menu_with_links_added_then_ok(xdg):
    tmp, exe = xdg
    assert linuxdesk.sync_menu(True, True, exe) == "added"
    text = linuxdesk.menu_file().read_text(encoding="utf-8")
    assert f"Exec={linuxdesk.exec_line(exe, True)}\n" in text
    assert "MimeType=x-scheme-handler/irc;x-scheme-handler/ircs;" in text
    assert "Icon=bchat" in text and "Name=BChat" in text
    assert linuxdesk.icon_file().read_bytes() == linuxdesk.ICON.read_bytes()
    m = mime(tmp)
    assert "[Default Applications]" in m
    assert "x-scheme-handler/irc=bchat.desktop" in m and "x-scheme-handler/ircs=bchat.desktop" in m
    assert linuxdesk.sync_menu(True, True, exe) == "ok"
    assert mime(tmp).count("x-scheme-handler/irc=") == 1


def test_menu_without_links_has_no_link_types(xdg):
    tmp, exe = xdg
    assert linuxdesk.sync_menu(True, False, exe) == "added"
    text = linuxdesk.menu_file().read_text(encoding="utf-8")
    assert "MimeType" not in text and "%u" not in text
    assert mime(tmp) == ""
    # the links box is greyed while the menu box is off: links alone write nothing
    linuxdesk.sync_menu(False, False, exe)
    assert linuxdesk.sync_menu(False, True, exe) == "ok"
    assert not linuxdesk.menu_file().exists() and mime(tmp) == ""


def test_moved_appimage_is_fixed_at_next_start(xdg):
    tmp, exe = xdg
    linuxdesk.sync_menu(True, True, exe)
    linuxdesk.sync_autostart(True, exe)
    moved = str(tmp / "BChat.AppImage")
    shutil.move(exe, moved)
    assert linuxdesk.sync_menu(True, True, moved) == "fixed"
    assert linuxdesk.sync_autostart(True, moved) == "fixed"
    assert f"Exec={linuxdesk.exec_line(moved, True)}\n" in linuxdesk.menu_file().read_text(encoding="utf-8")
    assert f"Exec={linuxdesk.exec_line(moved, False)}\n" in linuxdesk.autostart_file().read_text(encoding="utf-8")


def test_untick_removes_only_bchats_own(xdg):
    tmp, exe = xdg
    mp = tmp / "config" / "mimeapps.list"
    mp.parent.mkdir(parents=True)
    mp.write_text("# mine\n[Default Applications]\ntext/html=firefox.desktop\nx-scheme-handler/irc=other.desktop\n\n"
                  "[Added Associations]\nimage/png=gimp.desktop;\n", encoding="utf-8")
    linuxdesk.sync_menu(True, True, exe)
    m = mime(tmp)
    assert "x-scheme-handler/irc=bchat.desktop" in m and "other.desktop" not in m      # ticking makes BChat the default
    assert m.index("x-scheme-handler/ircs=bchat.desktop") < m.index("[Added Associations]")
    assert "# mine" in m and "text/html=firefox.desktop" in m and "image/png=gimp.desktop;" in m
    # links unticked: BChat's two lines go, everything else stays
    assert linuxdesk.sync_menu(True, False, exe) == "fixed"
    m = mime(tmp)
    assert "x-scheme-handler/irc" not in m and "text/html=firefox.desktop" in m and "image/png=gimp.desktop;" in m
    # menu unticked: entry and icon gone
    assert linuxdesk.sync_menu(False, False, exe) == "removed"
    assert not linuxdesk.menu_file().exists() and not linuxdesk.icon_file().exists()


def test_someone_elses_link_default_stays_when_off(xdg):
    tmp, exe = xdg
    linuxdesk.sync_menu(True, False, exe)
    mp = tmp / "config" / "mimeapps.list"
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text("[Default Applications]\nx-scheme-handler/irc=other.desktop\n", encoding="utf-8")
    linuxdesk.sync_menu(True, False, exe)
    linuxdesk.sync_menu(False, False, exe)
    assert "x-scheme-handler/irc=other.desktop" in mime(tmp)


def test_another_copys_entry_is_left_alone(xdg):
    tmp, exe = xdg
    other = str(tmp / "test-build" / "BChat.AppImage")
    linuxdesk.sync_menu(True, True, other)
    linuxdesk.sync_autostart(True, other)
    assert linuxdesk.sync_menu(False, False, exe) == "ok"
    assert linuxdesk.sync_autostart(False, exe) == "ok"
    assert linuxdesk.menu_file().exists() and linuxdesk.autostart_file().exists()
    assert "x-scheme-handler/irc=bchat.desktop" in mime(tmp)


def test_autostart_added_ok_removed(xdg):
    _tmp, exe = xdg
    assert linuxdesk.sync_autostart(True, exe) == "added"
    text = linuxdesk.autostart_file().read_text(encoding="utf-8")
    assert f"Exec={linuxdesk.exec_line(exe, False)}\n" in text and "X-GNOME-Autostart-enabled=true" in text and "MimeType" not in text
    assert linuxdesk.sync_autostart(True, exe) == "ok"
    assert linuxdesk.sync_autostart(False, exe) == "removed"
    assert not linuxdesk.autostart_file().exists()


def test_skipped_from_source_and_off_linux(xdg, monkeypatch):
    _tmp, exe = xdg
    assert linuxdesk.sync_menu(True, True, None) == "skipped"
    assert linuxdesk.sync_autostart(True, None) == "skipped"
    monkeypatch.setattr(linuxdesk, "SUPPORTED", False)
    assert linuxdesk.sync_menu(True, True, exe) == "skipped"
    assert linuxdesk.sync_autostart(True, exe) == "skipped"
    assert not linuxdesk.menu_file().exists() and not linuxdesk.autostart_file().exists()


def test_installed_exe_is_the_appimage(xdg, monkeypatch):
    _tmp, exe = xdg
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert linuxdesk.installed_exe() is None
    monkeypatch.setenv("APPIMAGE", exe)
    assert linuxdesk.installed_exe() == exe
    monkeypatch.setenv("APPIMAGE", exe + ".gone")
    assert linuxdesk.installed_exe() is None


def test_failure_never_raises(xdg, monkeypatch):
    _tmp, exe = xdg
    def boom(*a, **k):
        raise PermissionError("read-only home")
    monkeypatch.setattr(linuxdesk, "_write", boom)
    assert linuxdesk.sync_menu(True, True, exe) == "failed"
    assert linuxdesk.sync_autostart(True, exe) == "failed"


@pytest.mark.skipif(not shutil.which("desktop-file-validate"), reason="desktop-file-validate is a Linux tool")
def test_written_entries_pass_the_desktop_validator(xdg):
    tmp, exe = xdg
    spaced = tmp / "My Apps" / "BChat.AppImage"
    spaced.parent.mkdir()
    spaced.write_bytes(b"x")
    for path in (exe, str(spaced)):
        linuxdesk.sync_menu(True, True, path)
        linuxdesk.sync_autostart(True, path)
        for f in (linuxdesk.menu_file(), linuxdesk.autostart_file()):
            r = subprocess.run(["desktop-file-validate", str(f)], capture_output=True, text=True)
            assert r.returncode == 0 and not r.stdout.strip(), (f.read_text(), r.stdout, r.stderr)


@pytest.mark.skipif(not shutil.which("xdg-mime"), reason="xdg-mime is a Linux tool")
def test_desktop_sees_bchat_as_the_irc_handler(xdg):
    tmp, exe = xdg
    linuxdesk.sync_menu(True, True, exe)
    env = dict(os.environ, XDG_CURRENT_DESKTOP="X-Generic")
    for scheme in linuxdesk.SCHEMES:
        out = subprocess.run(["xdg-mime", "query", "default", scheme], capture_output=True, text=True, env=env).stdout
        assert out.strip() == "bchat.desktop", out
    linuxdesk.sync_menu(True, False, exe)
    out = subprocess.run(["xdg-mime", "query", "default", "x-scheme-handler/irc"], capture_output=True, text=True, env=env).stdout
    assert out.strip() != "bchat.desktop"


# --- the Settings boxes -------------------------------------------------------------------------------------------

def _win(tmp_path):
    from bchat.mainwindow import MainWindow
    win = MainWindow(Config(nick="x", skip_network_list=True), tmp_path)
    win.skip_quit_prompt = True
    return win


def test_windows_settings_unchanged(app, tmp_path, monkeypatch):
    from bchat.preferences import PreferencesDialog
    monkeypatch.setattr(linuxdesk, "SUPPORTED", False)
    win = _win(tmp_path)
    d = PreferencesDialog(win, "General")
    assert d.start_win.text() == "Start with Windows" and d.start_win.toolTip() == "Only for the installed BChat"
    assert not hasattr(d, "app_menu") and not hasattr(d, "irc_links")
    d.reject(); win.close()


def test_linux_settings_boxes(app, tmp_path, monkeypatch):
    from bchat.preferences import PreferencesDialog
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    win = _win(tmp_path)
    calls = []
    monkeypatch.setattr(win, "set_desktop_entry", lambda m, l: calls.append((m, l)))
    monkeypatch.setattr(win, "set_autostart", lambda on: calls.append(("start", on)))
    d = PreferencesDialog(win, "General")
    assert d.start_win.text() == "Start when I log in"
    assert d.app_menu.text() == "Add BChat to the app menu" and not d.app_menu.isChecked()
    assert d.irc_links.text().startswith("Open irc:// and ircs:// links with BChat") and not d.irc_links.isEnabled()
    d.app_menu.setChecked(True)
    assert d.irc_links.isEnabled()
    d.irc_links.setChecked(True)
    assert calls == []                     # nothing written before OK
    d.accept()
    assert calls == [(True, True)] and win.cfg.app_menu and win.cfg.irc_links
    d = PreferencesDialog(win, "General")
    assert d.app_menu.isChecked() and d.irc_links.isChecked() and d.irc_links.isEnabled()
    d.accept()
    assert calls == [(True, True)]         # no change, nothing rewritten
    d = PreferencesDialog(win, "General")
    d.app_menu.setChecked(False)
    assert not d.irc_links.isEnabled()
    d.start_win.setChecked(True)
    d.accept()
    assert calls == [(True, True), ("start", True), (False, True)] and not win.cfg.app_menu
    d = PreferencesDialog(win, "General")
    d.reject()
    win.close()


def test_start_syncs_menu_entry_on_linux(app, tmp_path, monkeypatch):
    from bchat import autostart
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    seen = []
    monkeypatch.setattr(linuxdesk, "sync_menu", lambda m, l, exe: seen.append((m, l, exe)) or "ok")
    monkeypatch.setattr(autostart, "sync", lambda on, exe: "skipped")
    monkeypatch.setattr(autostart, "installed_exe", lambda: "/opt/BChat.AppImage")
    win = _win(tmp_path)
    win.cfg.app_menu, win.cfg.irc_links = True, True
    win.check_autostart()
    assert seen == [(True, True, "/opt/BChat.AppImage")]
    win.close()


@pytest.mark.skipif(os.name == "nt", reason="the AppImage is Linux only")
def test_appimage_portable_folder_and_build_date_follow_the_appimage_file(tmp_path, monkeypatch):
    """An AppImage runs from a read-only temporary mount: BChat-data and the build date go by the AppImage file."""
    import sys
    from bchat import about
    from bchat.__main__ import portable_dir
    mount = tmp_path / ".mount_BChatXY"
    mount.mkdir()
    img = tmp_path / "apps" / "BChat-0.9.0-x86_64.AppImage"
    img.parent.mkdir()
    img.write_bytes(b"\x7fELF")
    os.utime(img, (1_700_000_000, 1_700_000_000))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(mount / "BChat"))
    monkeypatch.setenv("APPIMAGE", str(img))
    assert portable_dir(True) == img.parent / "BChat-data"
    assert portable_dir(False) is None
    (img.parent / "portable.txt").write_text("")
    assert portable_dir(False) == img.parent / "BChat-data"
    from datetime import datetime
    assert about.built_on() == datetime.fromtimestamp(1_700_000_000).strftime("%b %d %Y")


def test_programs_bchat_starts_get_the_desktops_own_libraries(monkeypatch):
    # the packaged app's bootloader points LD_LIBRARY_PATH at the bundle; children (speech-dispatcher, xdg-open)
    # crash on its older glib, so it goes back to the user's own value, or away when there was none
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    monkeypatch.setattr(linuxdesk.sys, "frozen", True, raising=False)
    env = {"LD_LIBRARY_PATH": "/tmp/.mount_BChat/usr/lib/bchat/_internal", "PATH": "/usr/bin"}
    linuxdesk.own_libs_for_children(env)
    assert env == {"PATH": "/usr/bin"}
    env = {"LD_LIBRARY_PATH": "/tmp/.mount_BChat/usr/lib/bchat/_internal", "LD_LIBRARY_PATH_ORIG": "/opt/mine/lib"}
    linuxdesk.own_libs_for_children(env)
    assert env == {"LD_LIBRARY_PATH": "/opt/mine/lib"}
    # from source (not frozen) and on Windows nothing changes
    monkeypatch.setattr(linuxdesk.sys, "frozen", False, raising=False)
    env = {"LD_LIBRARY_PATH": "/opt/dev/lib"}
    linuxdesk.own_libs_for_children(env)
    assert env == {"LD_LIBRARY_PATH": "/opt/dev/lib"}
    monkeypatch.setattr(linuxdesk.sys, "frozen", True, raising=False)
    monkeypatch.setattr(linuxdesk, "SUPPORTED", False)
    linuxdesk.own_libs_for_children(env)
    assert env == {"LD_LIBRARY_PATH": "/opt/dev/lib"}


def test_sound_backend_falls_back_when_pipewire_has_no_client_conf(tmp_path, monkeypatch):
    # Qt's PipeWire backend segfaults at the first sound when libpipewire is there but client.conf is not
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    empty, full = tmp_path / "empty", tmp_path / "full"
    empty.mkdir(); full.mkdir()
    (full / "client.conf").write_text("context.properties = {}\n")
    env = {}
    linuxdesk.safe_sound_backend(env, [empty])
    assert env == {"QT_AUDIO_BACKEND": "pulseaudio"}
    env = {}
    linuxdesk.safe_sound_backend(env, [empty, full])
    assert env == {}                                             # a normal desktop: Qt chooses as it likes
    env = {"QT_AUDIO_BACKEND": "pipewire"}
    linuxdesk.safe_sound_backend(env, [empty])
    assert env == {"QT_AUDIO_BACKEND": "pipewire"}               # the user's own choice wins
    monkeypatch.setattr(linuxdesk, "SUPPORTED", False)
    env = {}
    linuxdesk.safe_sound_backend(env, [empty])
    assert env == {}                                             # Windows: never


def test_pipewire_looks_where_pipewire_looks(tmp_path):
    dirs = linuxdesk.pipewire_conf_dirs({"PIPEWIRE_CONFIG_DIR": "/opt/pw", "XDG_CONFIG_HOME": str(tmp_path)})
    assert dirs == [Path("/opt/pw"), tmp_path / "pipewire", Path("/etc/pipewire"), Path("/usr/share/pipewire")]
    assert linuxdesk.pipewire_conf_dirs({"HOME": "/home/b"})[0] == Path("/home/b/.config/pipewire")


def test_wayland_desktops_run_bchat_through_xwayland(monkeypatch):
    # Wayland ignores where an app puts its windows: KDE centred the notification cards (seen 11-25, Fedora 45)
    monkeypatch.setattr(linuxdesk, "SUPPORTED", True)
    kde = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}
    assert linuxdesk.platform_args(kde) == ["-platform", "xcb"]
    assert linuxdesk.platform_args({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":1"}) == ["-platform", "xcb"]
    assert linuxdesk.platform_args(dict(kde, QT_QPA_PLATFORM="wayland")) == []      # the user's own choice wins
    assert linuxdesk.platform_args({"WAYLAND_DISPLAY": "wayland-0"}) == []           # no XWayland: native Wayland
    assert linuxdesk.platform_args({"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}) == []   # X11 desktop: Qt's own pick
    monkeypatch.setattr(linuxdesk, "SUPPORTED", False)
    assert linuxdesk.platform_args(kde) == []                                         # Windows: never
