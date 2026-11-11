"""Packaged app, extra check: what frozen_check / frozen_features don't cover.

Two networks at once (plain + TLS), IRCv3 caps + server-time, channel + private messages both ways, reconnect
after the server drops the connection, PNG/ICO/SVG/JPEG/BMP reading, the image formats list, the Qt files BChat
needs really loaded (platform, TLS backend, image and icon plugins), every main window open while the loaded DLLs
are listed, settings saved -> clean quit -> restart reads them back. Temp settings, local sockets only.

    python tools/qa/frozen_extra.py [--exe ...] [--out DIR] [--mode normal|clean] [--env QT_OPENGL=software ...]

--mode clean: PATH = Windows folders only, no QT_/PYTHON variables, empty APPDATA/LOCALAPPDATA/TEMP (a stand-in
for a PC with nothing else installed). --env adds environment variables (graphics modes, scaling).
"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

from qa_common import ROOT, finish, parse_args, process_memory_cpu, process_modules, self_signed_cert, wait


def _extra(ap):
    ap.add_argument("--mode", choices=("normal", "clean"), default="normal")
    ap.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")


ARGS = parse_args(__doc__.splitlines()[0], _extra)
sys.path.insert(0, str(ROOT / "tests"))
from fake_ircd import FakeIrcd

EXE, OUT = ARGS.exe, ARGS.out
ENV = dict(os.environ, BCHAT_VAULT="file")
tmp = Path(tempfile.mkdtemp(prefix="bchat-qa-extra-"))
if ARGS.mode == "clean":
    ENV["PATH"] = r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem"
    for k in list(ENV):
        if k.upper().startswith(("QT_", "PYTHON", "PYSIDE")):
            ENV.pop(k)
    for k in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        (tmp / k).mkdir()
        ENV[k] = str(tmp / k)
for kv in ARGS.env:
    k, _, v = kv.partition("=")
    ENV[k] = v
crt, key = self_signed_cert(tmp)

plain = FakeIrcd(caps="message-tags echo-message")
tls = FakeIrcd(crt, key)
cfgdir = tmp / "cfg"
(cfgdir / "addons").mkdir(parents=True)
report, flag, go = tmp / "report.json", tmp / "ready.flag", tmp / "go.flag"
(cfgdir / "config.json").write_text(json.dumps({
    "nick": "Badaboom", "imported": True, "skip_network_list": True, "reconnect_delay": 2, "ask_on_quit": False,
    "networks": [
        {"name": "Plain", "servers": [{"host": "127.0.0.1", "port": plain.port}], "autojoin": "#skinhead", "autoconnect": True},
        {"name": "Secure", "servers": [{"host": "127.0.0.1", "port": tls.port, "ssl": True}], "autojoin": "#tls",
         "autoconnect": True, "allow_invalid_cert": True}]}))

PROBE = r'''
__module_name__ = "slimprobe"
__module_version__ = "1"
__module_description__ = "slim check"
import xchat, json, os, traceback
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QImageReader, QIcon, QPixmap
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
REPORT, FLAG, GO = %r, %r, %r
R = {}
state = {"step": 0, "n": 0}
def note(k, fn):
    try:
        R[k] = bool(fn())
    except Exception:
        R[k] = False
        R[k + " (error)"] = traceback.format_exc()[-400:]
def win():
    from bchat.mainwindow import MainWindow
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)][0]
def texts(b):
    return [l.text for l in b.lines]
def images():
    from bchat.mainwindow import ASSETS
    fm = sorted(bytes(f).decode() for f in QImageReader.supportedImageFormats())
    R["image formats"] = " ".join(fm)
    for f in ("png", "ico", "svg", "jpg", "gif", "bmp"):
        note("format listed: " + f, lambda f=f: f in fm)
    note("PNG asset reads (bee.png)", lambda: not QImage(str(ASSETS / "bee.png")).isNull())
    note("ICO reads (bchat.ico)", lambda: not QImage(str(ASSETS / "bchat.ico")).isNull())
    note("ICO window icon has sizes", lambda: len(QIcon(str(ASSETS / "bchat.ico")).availableSizes()) > 0)
    svgs = list(ASSETS.rglob("*.svg"))
    note("SVG asset reads (%%d files, first)" %% len(svgs), lambda: svgs and not QImage(str(svgs[0])).isNull())
    note("SVG icon paints", lambda: svgs and not QIcon(str(svgs[0])).pixmap(32, 32).isNull())
    def rt(fmt):
        img = QImage(8, 8, QImage.Format.Format_ARGB32); img.fill(0xff336699)
        ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, fmt); buf.close()
        back = QImage(); back.loadFromData(ba, fmt)
        c = back.pixelColor(3, 3)
        return not back.isNull() and abs(c.red() - 0x33) < 12 and abs(c.green() - 0x66) < 12 and abs(c.blue() - 0x99) < 12   # JPEG is lossy
    for fmt in ("PNG", "JPG", "BMP", "ICO"):
        note("write + read back " + fmt, lambda fmt=fmt: rt(fmt))
    from bchat import lucide
    note("Lucide picture draws", lambda: not lucide.image("info", "#ffffff", 32).isNull())
    note("lights PNG reads", lambda: any(not QPixmap(str(p)).isNull() for p in (ASSETS / "lights").glob("*.png")))
def tick(userdata):
    try:
        w = win()
        st = state["step"]
        if st == 0:      # both networks up, joined, messages arrived
            s = w.sessions
            ok = ("Plain" in s and "Secure" in s and s["Plain"].state == "connected" and s["Secure"].state == "connected"
                  and "#skinhead" in s["Plain"].buffers and "#tls" in s["Secure"].buffers
                  and any("hello channel" in t for t in texts(s["Plain"].buffers["#skinhead"]))
                  and any(k.lower() == "belon" for k in s["Plain"].buffers))
            state["n"] += 1
            if not ok and state["n"] < 40:
                return True
            note("two networks connected at once", lambda: s["Plain"].state == "connected" and s["Secure"].state == "connected")
            note("TLS network shows TLS details", lambda: any(l.left == "SSL" and l.text.startswith("Protocol: TLS") for l in s["Secure"].server_buffer.lines))
            note("joined #skinhead and #tls", lambda: "#skinhead" in s["Plain"].buffers and "#tls" in s["Secure"].buffers)
            note("channel message shown", lambda: any("hello channel" in t for t in texts(s["Plain"].buffers["#skinhead"])))
            def stamped():
                ln = [l for l in s["Plain"].buffers["#skinhead"].lines if "hello channel" in l.text][0]
                return abs(ln.ts - 1700000000) < 5
            note("IRCv3 server-time used for the line", stamped)
            q = [b for k, b in s["Plain"].buffers.items() if k.lower() == "belon"]
            note("private message opens a tab", lambda: q and any("hello you" in t for t in texts(q[0])))
            xchat.command("msg #skinhead chan reply from bchat")
            xchat.command("msg Belon private reply from bchat")
            images()
            # every main window open while the DLL list is taken
            for key in ("chart", "friends", "ignore", "urls", "plugins"):
                note("window " + key, lambda k=key: w.open_tool(k).isVisible())
            note("window file transfers", lambda: w.open_transfers().isVisible())
            note("window help", lambda: w.open_help().isVisible())
            note("tray icon", lambda: (w._sync_tray(), True)[1])
            open(FLAG, "w").write("1")
            state["step"] = 1
            return True
        if st == 1:      # wait for the outside: DLL list taken, plain server dropped us and we came back
            if not os.path.exists(GO):
                return True
            s = w.sessions["Plain"]
            state["n"] = 0
            state["step"] = 2
            return True
        if st == 2:
            s = w.sessions["Plain"]
            state["n"] += 1
            if not (s.state == "connected" and open(GO).read().strip() == "back") and state["n"] < 30:
                return True
            note("reconnected after the drop", lambda: s.state == "connected")
            for d in QApplication.topLevelWidgets():
                if d is not w and d.isVisible():
                    d.close()
            w.cfg.nick2 = "PersistCheck42"
            w.save_config()
            note("settings saved to config.json", lambda: "PersistCheck42" in (Path(w.cfg_dir) / "config.json").read_text())
            json.dump(R, open(REPORT, "w"))
            w.skip_quit_prompt = True
            w._quit_for_real()
            return False
    except Exception:
        R["probe crash"] = traceback.format_exc()[-600:]
        json.dump(R, open(REPORT, "w"))
        return False
    return True
xchat.hook_timer(1000, tick)
''' % (str(report), str(flag), str(go))
(cfgdir / "addons" / "slimprobe.py").write_text(PROBE)


modules = process_modules


def mem_cpu(pid):
    ws, _, cpu = process_memory_cpu(pid)
    return ws, cpu


def fresh(srv):                         # the fake server welcomes once per object: let it welcome a new login
    srv.nick, srv.user_seen, srv.cap_open, srv.welcomed = "", False, False, False


out = {}
t0 = time.time()
p = subprocess.Popen([EXE, "--config-dir", str(cfgdir)], env=ENV)
out["startup: connected + joined both (s)"] = None
both = wait(lambda: any(x.startswith("JOIN #skinhead") for x in plain.received) and any(x.startswith("JOIN #tls") for x in tls.received), 40)
out["startup: connected + joined both (s)"] = round(time.time() - t0, 2) if both else "TIMEOUT"
out["IRCv3: CAP REQ sent with server-time"] = any(x.startswith("CAP REQ") and "server-time" in x for x in plain.received)
out["IRCv3: message-tags requested"] = any(x.startswith("CAP REQ") and "message-tags" in x for x in plain.received)
plain.send("@time=2023-11-14T22:13:20.000Z :Belon!b@h PRIVMSG #skinhead :hello channel")
plain.send(":Belon!b@h PRIVMSG Badaboom :hello you")
out["probe reached the ready point"] = wait(lambda: flag.exists(), 60)
out["sent channel message"] = any("PRIVMSG #skinhead :chan reply from bchat" in x for x in plain.received)
out["sent private message"] = any("PRIVMSG Belon :private reply from bchat" in x for x in plain.received)
out["dlls_all_windows_open"] = modules(p.pid)
time.sleep(5)
out["ram_busy_MB"] = round(mem_cpu(p.pid)[0] / 1048576, 1)
joins = sum(x.startswith("JOIN #skinhead") for x in plain.received)
fresh(plain)
try:
    plain.client.shutdown(2)
    plain.client.close()
except OSError:
    pass
go.write_text("dropped")
back = wait(lambda: sum(x.startswith("JOIN #skinhead") for x in plain.received) > joins, 30)
out["reconnect: rejoined after drop"] = back
go.write_text("back")
out["probe report written"] = wait(lambda: report.exists(), 40)
try:
    rc = p.wait(20)
    out["clean quit exit code"] = rc
except subprocess.TimeoutExpired:
    out["clean quit exit code"] = "STILL RUNNING"
    p.kill()
out["QUIT sent to plain server"] = any(x.startswith("QUIT") for x in plain.received)
out["QUIT sent to TLS server"] = any(x.startswith("QUIT") for x in tls.received)
probe = json.loads(report.read_text()) if report.exists() else {}

# second start: settings came back, idle numbers (no probe this time)
(cfgdir / "addons" / "slimprobe.py").unlink()
cfg = json.loads((cfgdir / "config.json").read_text())
out["settings kept after restart (file)"] = cfg.get("nick2") == "PersistCheck42"
fresh(plain); fresh(tls)
n_before = sum(x.startswith("JOIN #skinhead") for x in plain.received)
t1 = time.time()
p2 = subprocess.Popen([EXE, "--config-dir", str(cfgdir)], env=ENV)
ok2 = wait(lambda: sum(x.startswith("JOIN #skinhead") for x in plain.received) > n_before, 40)
out["second start connected (s)"] = round(time.time() - t1, 2) if ok2 else "TIMEOUT"
out["second start: NICK from saved config"] = any(x.startswith("NICK Badaboom") for x in plain.received[-20:])
time.sleep(20)                         # settle, then idle sample over 30 s
m1, c1 = mem_cpu(p2.pid)
time.sleep(30)
m2, c2 = mem_cpu(p2.pid)
out["idle_ram_MB"] = round(m2 / 1048576, 1)
out["idle_cpu_percent_one_core"] = round((c2 - c1) / 30 * 100, 2)
out["dlls_idle"] = modules(p2.pid)
p2.kill()
plain.stop(); tls.stop()
# Qt files BChat needs, checked in the DLL list taken with every main window open and a TLS network connected
loaded = {x.lower() for x in out["dlls_all_windows_open"]}
NEEDED = {"Qt6Core.dll": "Qt core", "Qt6Gui.dll": "Qt GUI", "Qt6Widgets.dll": "Qt widgets", "Qt6Network.dll": "Qt network",
          "Qt6Svg.dll": "SVG support", "qwindows.dll": "Windows platform plugin", "qsvg.dll": "SVG image plugin",
          "qsvgicon.dll": "SVG icon plugin", "qico.dll": "ICO image plugin", "qjpeg.dll": "JPEG image plugin"}
info = {}
res = {}
for dll, what in NEEDED.items():
    res[f"loaded: {dll} ({what})"] = dll.lower() in loaded
res["loaded: a TLS backend (qschannelbackend.dll or qopensslbackend.dll)"] = bool(loaded & {"qschannelbackend.dll", "qopensslbackend.dll"})
res["loaded: a Python runtime (python3*.dll)"] = any(x.startswith("python3") and x.endswith(".dll") for x in loaded)

# the checks; numbers and lists are information
for k in ("IRCv3: CAP REQ sent with server-time", "IRCv3: message-tags requested", "probe reached the ready point",
          "sent channel message", "sent private message", "reconnect: rejoined after drop", "probe report written",
          "QUIT sent to plain server", "QUIT sent to TLS server", "settings kept after restart (file)",
          "second start: NICK from saved config"):
    res[k] = bool(out.get(k))
res["startup: connected + joined both networks"] = isinstance(out["startup: connected + joined both (s)"], float)
res["clean quit (exit code 0)"] = out["clean quit exit code"] == 0
res["second start connected"] = isinstance(out["second start connected (s)"], float)
for k, v in probe.items():
    if k.endswith("(error)") or k == "probe crash" or not isinstance(v, bool):
        info["probe: " + k] = v
        if k == "probe crash":
            res["probe ran without crashing"] = False
    else:
        res["probe: " + k] = v
for k in ("startup: connected + joined both (s)", "second start connected (s)", "ram_busy_MB", "idle_ram_MB",
          "idle_cpu_percent_one_core", "clean quit exit code"):
    info[k] = out[k]
info["mode"] = ARGS.mode
info["env"] = ARGS.env
res.update(info)
finish("frozen_extra", ARGS, res, extra={"dlls_all_windows_open": out["dlls_all_windows_open"], "dlls_idle": out["dlls_idle"]})
