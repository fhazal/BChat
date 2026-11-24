"""Packaged check for Linux: the built BChat AppImage, run the way a user runs it, with throwaway settings.
Runs on Linux only (WSL Ubuntu 22.04 or a container), with the venv's python, inside its own D-Bus session:
    dbus-run-session -- python tools/qa/frozen_linux.py --exe BChat-<v>-x86_64.AppImage --expect <v>
Needs: Xvfb, weston (Wayland, headless), gnome-keyring-daemon, desktop-file-validate, ImageMagick's import.

A  the bundle: assets identical to the source, version, Qt plugins, every library resolves, the .desktop file is valid
B  X11 (Xvfb): a probe plugin inside the app checks the Linux parts (menu/autostart point at the AppImage, system
   info, speech, sound decoding, the keyring) and a real DCC file comes in over a local socket
C  Wayland (weston headless): starts and joins as a Wayland app; with no keyring answering BChat says so
D  portable: portable.txt next to the AppImage keeps every setting in BChat-data beside it, nothing in the home folder
"""
import json, os, shutil, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path

if not sys.platform.startswith("linux"):
    sys.exit("frozen_linux.py runs on Linux only (the AppImage)")

from qa_common import ROOT, finish, parse_args, wait
sys.path.insert(0, str(ROOT / "tests"))
from fake_ircd import FakeIrcd

ARGS = parse_args("Packaged Linux app: the AppImage's bundle, X11, Wayland, portable mode and the keyring.")
IMG = ARGS.exe
TMP = Path(tempfile.mkdtemp(prefix="bchat-linux-qa-"))
out: dict = {}
skips: dict = {}


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


# ---------------------------------------------------------------- A: the bundle
def bundle() -> None:
    ex = TMP / "extract"
    ex.mkdir()
    subprocess.run([IMG, "--appimage-extract"], cwd=ex, capture_output=True, timeout=120)
    root = ex / "squashfs-root"
    app = root / "usr" / "lib" / "bchat"
    out["bundle: extracts"] = (app / "BChat").is_file()
    if not out["bundle: extracts"]:
        return
    out["bundle: AppRun runs the app"] = os.access(root / "AppRun", os.X_OK) and "usr/lib/bchat/BChat" in (root / "AppRun").read_text()
    inner = app / "_internal"
    src = ROOT / "bchat" / "assets"
    bad = [str(p.relative_to(src)) for p in src.rglob("*") if p.is_file() and p.name != "version.txt"
           and (not (inner / "bchat" / "assets" / p.relative_to(src)).is_file()
                or (inner / "bchat" / "assets" / p.relative_to(src)).read_bytes() != p.read_bytes())]
    out["bundle: assets identical to the source"] = not bad
    if bad:
        out["bundle: assets differing"] = bad[:10]
    v = inner / "bchat" / "assets" / "version.txt"
    out["bundle: version.txt = expected"] = v.is_file() and v.read_text().strip() == ARGS.expect
    plug = inner / "PySide6" / "Qt" / "plugins"
    for name, rel in (("X11", "platforms/libqxcb.so"), ("Wayland", "platforms/libqwayland.so"),
                      ("offscreen", "platforms/libqoffscreen.so"), ("FFmpeg sound", "multimedia/libffmpegmediaplugin.so"),
                      ("speech", "texttospeech/libqtexttospeech_speechd.so"), ("TLS", "tls/libqopensslbackend.so"),
                      ("SVG icons", "imageformats/libqsvg.so")):
        out[f"bundle: Qt plugin {name}"] = (plug / rel).is_file()
    out["bundle: spell-check word lists"] = any((inner / "spellchecker" / "resources").glob("en*"))
    for left_out in ("libstdc++.so.6", "libX11.so.6", "libfontconfig.so.1", "libdbus-1.so.3", "libgtk-3.so.0"):
        out[f"bundle: host library {left_out} not bundled"] = not list(app.rglob(left_out))
    missing = set()
    env = dict(os.environ, LD_LIBRARY_PATH=f"{inner}:{inner / 'PySide6' / 'Qt' / 'lib'}")
    for so in [app / "BChat", *inner.rglob("*.so*")]:
        if so.is_symlink() or not so.is_file():
            continue
        r = subprocess.run(["ldd", str(so)], capture_output=True, text=True, env=env)
        missing |= {f"{so.name}: {line.split()[0]}" for line in r.stdout.splitlines() if "not found" in line}
    # Qt's optional pieces this desktop doesn't have are fine (Vulkan/EGL-device paths); everything else must resolve
    out["bundle: every library resolves (ldd)"] = not missing
    if missing:
        out["bundle: unresolved"] = sorted(missing)[:15]
    desk = root / "bchat.desktop"
    if have("desktop-file-validate"):
        r = subprocess.run(["desktop-file-validate", str(desk)], capture_output=True, text=True)
        out["bundle: .desktop file valid"] = r.returncode == 0 and not r.stdout.strip()
        if r.stdout.strip():
            out["bundle: .desktop warnings"] = r.stdout.strip()
    else:
        out["bundle: .desktop file valid"] = None
        skips["bundle: .desktop file valid"] = "desktop-file-validate not installed"
    out["bundle: .desktop opens irc:// links"] = "x-scheme-handler/irc;" in desk.read_text()
    out["bundle: icon"] = (root / "bchat.png").is_file() and (root / ".DirIcon").exists()


# ---------------------------------------------------------------- the probe plugin
PROBE = r'''
__module_name__ = "probe"
__module_version__ = "1"
__module_description__ = "linux packaged check"
import xchat, json, os, importlib, traceback
from PySide6.QtWidgets import QApplication
results = {}
REPORT = @REPORT@
MODE = @MODE@
MEDIA = @MEDIA@
def note(name, fn):
    try:
        results[name] = bool(fn())
    except Exception:
        results[name] = False
        results[name + " (error)"] = traceback.format_exc()[-400:]
def decodes(name):
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QAudioDecoder
    dec = QAudioDecoder()
    got, loop = [], QEventLoop()
    dec.bufferReady.connect(lambda: got.append(dec.read().byteCount()))
    dec.finished.connect(loop.quit)
    dec.error.connect(lambda *_: loop.quit())
    QTimer.singleShot(8000, loop.quit)
    dec.setSource(QUrl.fromLocalFile(MEDIA + "/" + name)); dec.start()
    loop.exec()
    return sum(got) > 1000 and dec.error() == QAudioDecoder.Error.NoError
def run(userdata):
    from bchat import linuxdesk, vault, sysinfo, full_version
    from bchat.mainwindow import MainWindow
    win = [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)][0]
    img = os.environ.get("APPIMAGE", "")
    results["platform"] = QApplication.platformName()
    results["version"] = full_version()
    results["running from the AppImage"] = bool(img) and linuxdesk.installed_exe() == img
    results["window shown"] = win.isVisible()
    if MODE == "x11":
        def menu():
            r = linuxdesk.sync_menu(True, True, linuxdesk.installed_exe())
            text = linuxdesk.menu_file().read_text()
            mime = (linuxdesk.config_home() / "mimeapps.list").read_text()
            ok = r == "added" and img in text and "%u" in text and "x-scheme-handler/irc=bchat.desktop" in mime
            ok = ok and linuxdesk.icon_file().is_file()
            return ok and linuxdesk.sync_menu(False, False, linuxdesk.installed_exe()) == "removed" and not linuxdesk.menu_file().exists()
        note("app menu entry points at the AppImage (and goes away)", menu)
        def autostart():
            r = linuxdesk.sync_autostart(True, linuxdesk.installed_exe())
            ok = r == "added" and img in linuxdesk.autostart_file().read_text()
            return ok and linuxdesk.sync_autostart(False, linuxdesk.installed_exe()) == "removed"
        note("start when I log in points at the AppImage (and goes away)", autostart)
        info = sysinfo.collect("x")
        results["system info"] = info
        # the graphics card reads "?" where /sys has no PCI names for it (WSL's virtual GPU); every other part must fill
        note("system info names the Linux distro and kernel", lambda: "(kernel " in info["os"] and "64-bit" in info["os"])
        note("system info: every part filled (graphics card may be unknown)", lambda: all(v != "?" for k, v in info.items() if k != "gpu"))
        from bchat import speech
        results["speech engines"] = speech.Speaker.engines()
        note("speech engine loads", lambda: speech.speaker().available())
        note("mp3 sound decodes (bundled FFmpeg)", lambda: decodes("tone.mp3"))
        note("ogg sound decodes (bundled FFmpeg)", lambda: decodes("tone.ogg"))
        note("wav sound decodes", lambda: decodes("tone.wav"))
        note("keyring answers", lambda: vault.keyring_ok(win.cfg_dir))
        def keyring_round_trip():
            ok = vault.put(win.cfg_dir, "probe-secret") and vault.get(win.cfg_dir) == "probe-secret"
            vault.clear(win.cfg_dir)
            return ok and vault.get(win.cfg_dir) is None
        note("password kept in the keyring and read back", keyring_round_trip)
        note("D-Bus parts are bundled (secretstorage, jeepney)", lambda: importlib.import_module("secretstorage") and importlib.import_module("jeepney.io.blocking"))
        note("/np asks the desktop's players without failing", lambda: importlib.import_module("bchat.nowplaying").playing() is None or True)
        from PySide6.QtWidgets import QSystemTrayIcon
        results["system tray here"] = "yes" if QSystemTrayIcon.isSystemTrayAvailable() else "no (none on this test desktop)"
        # the settings tick "tray icon": it must show where the desktop has a tray, and BChat must cope where none is
        note("tray icon only where the desktop has a tray", lambda: (win.tray is not None) == QSystemTrayIcon.isSystemTrayAvailable())
        if win.tray is not None:
            note("tray icon visible", lambda: win.tray.isVisible())
        missing = []
        for mod in ("json", "re", "os", "time", "random", "datetime", "threading", "socket", "subprocess", "urllib.request", "urllib.parse", "http.client",
                    "sqlite3", "csv", "hashlib", "html", "xml.etree.ElementTree", "collections", "itertools", "math", "string", "textwrap", "shlex", "glob", "tempfile", "queue"):
            try:
                importlib.import_module(mod)
            except Exception:
                missing.append(mod)
        results["plugin imports all there"] = not missing
        if missing:
            results["plugin imports missing"] = str(missing)
        xchat.command("say plugin says hi")
    elif MODE == "nokeyring":
        note("no keyring: BChat knows passwords would not be kept", lambda: vault.keyring_ok(win.cfg_dir) is False)
    results["config folder"] = str(win.cfg_dir)
    with open(REPORT, "w") as f:
        json.dump(results, f)
    return False
xchat.hook_timer(3000, run)
'''


def settings(folder: Path, srv: FakeIrcd, inbox: Path, mode: str, report: Path) -> None:
    (folder / "addons").mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps({
        "nick": "Badaboom", "imported": True, "skip_network_list": True, "dcc_auto": 1, "dcc_dir": str(inbox), "tray_icon": True,
        "networks": [{"name": "SkinIRC", "servers": [{"host": "127.0.0.1", "port": srv.port}], "autojoin": "#skinhead",
                      "autoconnect": True}]}))
    (folder / "addons" / "probe.py").write_text(PROBE.replace("@REPORT@", repr(str(report))).replace("@MODE@", repr(mode))
                                                .replace("@MEDIA@", repr((ROOT / "tests" / "data").as_posix())))


def launch(img: str, env: dict, args=()) -> subprocess.Popen:
    log = open(TMP / f"app-{len(list(TMP.glob('app-*.log')))}.log", "wb")
    return subprocess.Popen([img, *args], env=env, stdout=log, stderr=subprocess.STDOUT)


def base_env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("QT_", "BCHAT_", "XDG_", "WAYLAND_"))}
    home.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local" / "share"),
               APPIMAGE_EXTRACT_AND_RUN="1",            # WSL / containers have no FUSE; a desktop mounts it instead
               BCHAT_REPORT_URL="http://127.0.0.1:9/never")
    return env


def read_report(report: Path, prefix: str, sec: float = 40) -> dict:
    got = wait(lambda: report.exists(), sec)
    out[f"{prefix}: probe plugin finished"] = got
    return json.loads(report.read_text()) if got else {}


# ---------------------------------------------------------------- B: X11 + keyring + DCC
def x11() -> None:
    if not have("Xvfb"):
        out["X11: runs"] = None
        skips["X11: runs"] = "Xvfb not installed"
        return
    xvfb = subprocess.Popen(["Xvfb", ":77", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    srv = FakeIrcd()
    home, cfg, inbox, report = TMP / "x11-home", TMP / "x11-cfg", TMP / "x11-in", TMP / "x11.json"
    settings(cfg, srv, inbox, "x11", report)
    kr = subprocess.run(["gnome-keyring-daemon", "--replace", "--unlock", "--components=secrets", "--daemonize"],
                        input=b"\n", capture_output=True, timeout=20) if have("gnome-keyring-daemon") else None
    payload = bytes(range(256)) * 2000
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1)
    acks = {"n": 0}

    def serve():
        c, _ = ls.accept()
        c.sendall(payload)
        c.settimeout(5)
        try:
            while acks["n"] < len(payload):
                d = c.recv(4096)
                if not d:
                    break
                acks["n"] = int.from_bytes(d[-4:], "big")
        except OSError:
            pass
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    env = dict(base_env(home), DISPLAY=":77", QT_QPA_PLATFORM="xcb")      # BCHAT_VAULT unset: the real keyring
    p = launch(IMG, env, ["--config-dir", str(cfg)])
    try:
        out["X11: joined the fake server"] = wait(lambda: "JOIN #skinhead" in srv.received, 40)
        time.sleep(1)
        srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND song.mp3 2130706433 {ls.getsockname()[1]} {len(payload)}\x01")
        done = inbox / "song.mp3"
        out["X11: DCC file arrives, exact bytes"] = wait(lambda: done.exists() and done.read_bytes() == payload and acks["n"] == len(payload))
        out["X11: received file is not executable"] = done.exists() and done.stat().st_mode & 0o111 == 0
        srv.send(":Belon!b@h PRIVMSG Badaboom :\x01PING 12345\x01")
        out["X11: CTCP reply"] = wait(lambda: any("PING 12345" in x for x in srv.received))
        r = read_report(report, "X11")
        out["X11: runs as an X11 app"] = r.get("platform") == "xcb"
        out["X11: reports the expected version"] = r.get("version") == ARGS.expect
        if kr is None or kr.returncode != 0:
            for k in ("keyring answers", "password kept in the keyring and read back"):
                r.pop(k, None)
                out["X11: " + k] = None
                skips["X11: " + k] = "no gnome-keyring-daemon here"
        for k, v in r.items():
            if k not in ("platform", "version"):
                out["X11: " + k] = v
        out["X11: plugin's command reached the server"] = wait(lambda: any("plugin says hi" in x for x in srv.received), 5)
        if have("import"):
            shot = ARGS.out / "linux-x11.png"
            subprocess.run(["import", "-display", ":77", "-window", "root", str(shot)], capture_output=True, timeout=20)
            out["X11: screenshot"] = str(shot) if shot.exists() else "none"
        out["X11: still running at the end"] = p.poll() is None
    finally:
        p.kill(); p.wait()
        srv.stop()
        xvfb.kill()
        if kr is not None:
            subprocess.run(["pkill", "-f", "gnome-keyring-daemon --replace"], capture_output=True)


# ---------------------------------------------------------------- C: Wayland, no keyring
def wayland() -> None:
    if not have("weston"):
        out["Wayland: runs"] = None
        skips["Wayland: runs"] = "weston not installed"
        return
    rt = TMP / "xdg-run"
    rt.mkdir(mode=0o700)
    wenv = dict(os.environ, XDG_RUNTIME_DIR=str(rt))
    weston = subprocess.Popen(["weston", "--backend=headless-backend.so", "--socket=bchat-qa", "--idle-time=0"], env=wenv,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait(lambda: (rt / "bchat-qa").exists(), 15):
        out["Wayland: test compositor started"] = False
        weston.kill()
        return
    srv = FakeIrcd()
    home, cfg, report = TMP / "wl-home", TMP / "wl-cfg", TMP / "wl.json"
    settings(cfg, srv, TMP / "wl-in", "nokeyring", report)
    env = dict(base_env(home), XDG_RUNTIME_DIR=str(rt), WAYLAND_DISPLAY="bchat-qa", QT_QPA_PLATFORM="wayland",
               DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent")               # no keyring answers
    env.pop("DISPLAY", None)
    p = launch(IMG, env, ["--config-dir", str(cfg)])
    try:
        out["Wayland: joined the fake server"] = wait(lambda: "JOIN #skinhead" in srv.received, 40)
        r = read_report(report, "Wayland")
        out["Wayland: runs as a Wayland app"] = r.get("platform") == "wayland"
        out["Wayland: window shown"] = r.get("window shown")
        for k, v in r.items():
            if k.startswith("no keyring"):
                out["Wayland: " + k] = v
        out["Wayland: still running at the end"] = p.poll() is None
    finally:
        p.kill(); p.wait()
        srv.stop()
        weston.kill()


# ---------------------------------------------------------------- D: portable
def portable() -> None:
    if not have("Xvfb"):
        out["portable: runs"] = None
        skips["portable: runs"] = "Xvfb not installed"
        return
    xvfb = subprocess.Popen(["Xvfb", ":78", "-screen", "0", "1024x700x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stick = TMP / "usb stick"                         # a space in the path, as on a real USB stick label
    stick.mkdir()
    img = stick / Path(IMG).name
    shutil.copy2(IMG, img)
    (stick / "portable.txt").write_text("")
    srv = FakeIrcd()
    home, report = TMP / "pt-home", TMP / "pt.json"
    settings(stick / "BChat-data", srv, TMP / "pt-in", "portable", report)
    env = dict(base_env(home), DISPLAY=":78", QT_QPA_PLATFORM="xcb", BCHAT_VAULT="file")
    p = launch(str(img), env)
    try:
        out["portable: joined (settings read from BChat-data next to the AppImage)"] = wait(lambda: "JOIN #skinhead" in srv.received, 40)
        r = read_report(report, "portable")
        out["portable: settings folder is BChat-data next to the AppImage"] = r.get("config folder") == str(stick / "BChat-data")
        out["portable: nothing written to the home folder"] = not any((home / ".config").rglob("*")) if (home / ".config").exists() else True
        out["portable: still running at the end"] = p.poll() is None
    finally:
        p.kill(); p.wait()
        srv.stop()
        xvfb.kill()


try:
    for part in (bundle, x11, wayland, portable):
        try:
            part()
        except Exception as e:                         # one broken part must not hide the others' results
            import traceback
            out[f"{part.__name__}: ran without a tool error"] = False
            out[f"{part.__name__}: tool error"] = traceback.format_exc()[-600:]
finally:
    for log in sorted(TMP.glob("app-*.log")):
        shutil.copy2(log, ARGS.out / log.name)
    subprocess.run(["chmod", "-R", "u+w", str(TMP)], capture_output=True)
    shutil.rmtree(TMP, ignore_errors=True)
finish("frozen_linux", ARGS, out, skips)
