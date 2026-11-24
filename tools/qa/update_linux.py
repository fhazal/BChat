"""Linux updater check: a real update from one BChat AppImage to the next, the way a user gets it.
Runs on Linux only (a container or WSL), with a python that has cryptography, inside its own D-Bus session:
    dbus-run-session -- python3 tools/qa/update_linux.py --exe BChat-<v>-TEST1.AppImage --new BChat-<v>-TEST2.AppImage
Needs Xvfb, or --desktop on a real desktop (the AppImage then runs FUSE-mounted, as users get it). Nothing reaches the internet: a local web server hands out the update file and the new AppImage,
signed with a throwaway key that a plugin inside the old BChat swaps in (the shipped app has no test switch).

1 update   old BChat finds the update, downloads it, checks it, Install Now: it quits, the AppImage file is
           replaced under the same name, and the new version starts from it and tidies the download away
2 tampered the download doesn't match the signed checksum: thrown away, the AppImage file stays as it was
3 Windows  an update file signed the Windows way is refused by the Linux BChat
"""
import base64, hashlib, http.server, json, os, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path

if not sys.platform.startswith("linux"):
    sys.exit("update_linux.py runs on Linux only (the AppImage)")

from qa_common import finish, parse_args, wait

ARGS = parse_args("Linux updater: a real AppImage update, a tampered download, a Windows-signed file.",
                  extra=lambda ap: (ap.add_argument("--new", required=True, help="the newer AppImage the update brings"),
                                    ap.add_argument("--desktop", action="store_true",
                                                    help="on this desktop (FUSE-mounted AppImage) instead of Xvfb")))
OLD, NEW = Path(ARGS.exe), Path(ARGS.new).resolve()
TMP = Path(tempfile.mkdtemp(prefix="bchat-update-qa-"))
out: dict = {}
skips: dict = {}

PLUGIN = r'''
__module_name__ = "updprobe"
__module_version__ = "1"
__module_description__ = "linux updater check"
import xchat, json, os, traceback
from PySide6.QtWidgets import QApplication
PLAN = @PLAN@
def note(name, value):
    rep = json.load(open(PLAN["report"])) if os.path.exists(PLAN["report"]) else {}
    rep.setdefault(name, value) if name != "states" else rep.setdefault("states", []).append(value)
    json.dump(rep, open(PLAN["report"], "w"))
def run(_):
    try:
        from bchat import updater as up, full_version
        from bchat.mainwindow import MainWindow
        win = [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)][0]
        v, u = full_version(), win.updater
        files = sorted(os.listdir(u.dir)) if u.dir.exists() else []
        note(v, {"appimage": os.environ.get("APPIMAGE", ""), "pid": os.getpid(), "can_install": u.can_install,
                 "update files": [f for f in files if f.endswith((".AppImage", ".part"))]})
        if v != PLAN["update_from"]:
            return False
        up.PUBLIC_KEY = PLAN["pub"]                    # the throwaway test key
        u.url = PLAN["url"]
        def changed():
            note("states", u.state + ("" if u.state != up.FAILED else ": " + u.reason))
            if u.state == up.AVAILABLE and not getattr(u, "_qa_asked", False):
                u._qa_asked = True
                u.install_now()                        # = Install Now in the update window
        u.changed.connect(changed)
        u.check(manual=True)
    except Exception:
        note("plugin error", traceback.format_exc()[-600:])
    return False
xchat.hook_timer(2500, run)
'''


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def version_of(img: Path) -> str:
    """The version an AppImage reports (bchat/assets/version.txt inside it)."""
    ex = TMP / ("ver-" + img.name)
    ex.mkdir()
    subprocess.run([str(img), "--appimage-extract", "usr/lib/bchat/_internal/bchat/assets/version.txt"], cwd=ex,
                   capture_output=True, timeout=120)
    f = ex / "squashfs-root" / "usr" / "lib" / "bchat" / "_internal" / "bchat" / "assets" / "version.txt"
    return f.read_text().strip() if f.exists() else ""


def keypair():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    return k, base64.b64encode(k.public_key().public_bytes_raw()).decode()


def serve(folder: Path) -> tuple[str, http.server.ThreadingHTTPServer]:
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(folder), **kw)
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv


def scenario(name: str, entry_for, display: str) -> tuple[dict, Path, subprocess.Popen]:
    """Old BChat as BChat-x86_64.AppImage in its own folder, offered the update entry_for(base, key) makes."""
    home, apps, web = TMP / f"{name}-home", TMP / f"{name}-apps", TMP / f"{name}-web"
    for d in (home, apps, web):
        d.mkdir()
    img = apps / "BChat-x86_64.AppImage"                # Option C: the download's own, version-free name
    shutil.copy2(OLD, img)
    shutil.copy2(NEW, web / "BChat-x86_64.AppImage")
    base, srv = serve(web)
    key, pub = keypair()
    (web / "latest.json").write_text(json.dumps({"test": entry_for(base, key, web), "stable": None}))
    cfg, report = home / ".config" / "BChat", TMP / f"{name}.json"   # the default folder: the restart passes no args
    (cfg / "addons").mkdir(parents=True)
    (cfg / "config.json").write_text(json.dumps({"nick": "Badaboom", "imported": True, "skip_network_list": True,
                                                 "networks": [], "update_check": False}))
    plan = {"report": str(report), "update_from": OLD_V, "url": f"{base}/latest.json", "pub": pub}
    (cfg / "addons" / "updprobe.py").write_text(PLUGIN.replace("@PLAN@", repr(plan)))
    keep = ("XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP") if ARGS.desktop else ()
    env = {k: v for k, v in os.environ.items() if k in keep or not k.startswith(("QT_", "BCHAT_", "XDG_", "WAYLAND_"))}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local" / "share"),
               BCHAT_VAULT="memory", BCHAT_REPORT_URL="http://127.0.0.1:9/never")
    if not ARGS.desktop:                                # a container: Xvfb, and no FUSE to mount the AppImage
        env.update(DISPLAY=display, QT_QPA_PLATFORM="xcb", APPIMAGE_EXTRACT_AND_RUN="1")
    log = open(TMP / f"{name}-app.log", "wb")
    p = subprocess.Popen([str(img)], env=env, cwd=str(apps),
                         stdout=log, stderr=subprocess.STDOUT)
    return {"srv": srv, "report": report, "cfg": cfg}, img, p


def read(report: Path) -> dict:
    try:
        return json.loads(report.read_text())
    except (OSError, ValueError):
        return {}


def entry(version: str, sha: str, size: int, url: str, key, linux: bool = True) -> dict:
    text = f"{version}\n{sha}" + ("\nlinux" if linux else "")
    return {"version": version, "date": "25 Nov 2026", "size": size, "url": url, "page": "", "sha256": sha,
            "sig": base64.b64encode(key.sign(text.encode())).decode(), "notes": ["update check"], "notes_url": ""}


def stop(pid: int) -> None:
    try:
        os.kill(pid, 15)
    except OSError:
        pass


OLD_V, NEW_V = version_of(OLD), version_of(NEW)
out["old and new AppImages report their versions"] = bool(OLD_V and NEW_V and OLD_V != NEW_V)
xvfb = subprocess.Popen(["Xvfb", ":79", "-screen", "0", "1024x700x24", "-nolisten", "tcp"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if shutil.which("Xvfb") and not ARGS.desktop else None
if xvfb is None and not ARGS.desktop:
    out["Xvfb here"] = False
started = []
try:
    time.sleep(1.5)
    # ---- 1: the real update ---------------------------------------------------------------------------------
    new_sha, new_size = sha256(NEW), NEW.stat().st_size
    s, img, p = scenario("update", lambda base, key, web: entry(NEW_V, new_sha, new_size,
                                                                 f"{base}/BChat-x86_64.AppImage", key), ":79")
    started.append(p.pid)
    out["update: old BChat starts"] = wait(lambda: OLD_V in read(s["report"]), 60)
    out["update: old BChat can update itself (runs from the AppImage)"] = read(s["report"]).get(OLD_V, {}).get("can_install") is True
    out["update: old BChat quits for the update"] = wait(lambda: p.poll() is not None, 120)
    states = read(s["report"]).get("states", [])
    out["update: found, downloaded and checked"] = all(x in states for x in ("available", "downloading", "ready"))
    out["update: the new version starts by itself"] = wait(lambda: NEW_V in read(s["report"]), 60)
    after = read(s["report"]).get(NEW_V, {})
    if after.get("pid"):
        started.append(after["pid"])
    out["update: AppImage file now holds the new version"] = img.is_file() and sha256(img) == new_sha
    out["update: same file name and folder (menu entries keep working)"] = after.get("appimage") == str(img)
    out["update: still runnable"] = os.access(img, os.X_OK)
    out["update: nothing else left in the AppImage's folder"] = sorted(x.name for x in img.parent.iterdir()) == [img.name]
    out["update: the new version tidied the download away"] = after.get("update files") == []
    out["update: no failure on the way"] = not any(x.startswith("failed") for x in states)
    if not out["update: found, downloaded and checked"] or not out["update: no failure on the way"]:
        out["update: states seen"] = None
        skips["update: states seen"] = str(states)[:400]
    s["srv"].shutdown()

    # ---- 2: a tampered download -----------------------------------------------------------------------------
    old_sha = sha256(OLD)
    s, img, p = scenario("tampered", lambda base, key, web: entry(NEW_V, "0" * 64, new_size,
                                                                   f"{base}/BChat-x86_64.AppImage", key), ":79")
    started.append(p.pid)
    out["tampered: refused with a checksum failure"] = wait(
        lambda: any("checksum" in x for x in read(s["report"]).get("states", [])), 120)
    out["tampered: AppImage file unchanged"] = sha256(img) == old_sha
    out["tampered: BChat keeps running"] = p.poll() is None
    out["tampered: download thrown away"] = not any(x.name.endswith((".AppImage", ".part"))
                                                     for x in (s["cfg"] / "updates").glob("*"))
    stop(p.pid)
    s["srv"].shutdown()

    # ---- 3: an update file signed the Windows way -----------------------------------------------------------
    s, img, p = scenario("windows", lambda base, key, web: entry(NEW_V, new_sha, new_size,
                                                                  f"{base}/BChat-x86_64.AppImage", key, linux=False), ":79")
    started.append(p.pid)
    out["Windows-signed: refused as not signed"] = wait(
        lambda: any("isn't signed" in x for x in read(s["report"]).get("states", [])), 60)
    out["Windows-signed: nothing downloaded, AppImage unchanged"] = (sha256(img) == old_sha
                                                                     and not (s["cfg"] / "updates").exists())
    stop(p.pid)
    s["srv"].shutdown()
finally:
    time.sleep(0.5)
    for pid in started:
        stop(pid)
    if xvfb:
        xvfb.kill()
    for log in sorted(TMP.glob("*-app.log")):
        shutil.copy2(log, ARGS.out / log.name)
    for rep in sorted(TMP.glob("*.json")):
        shutil.copy2(rep, ARGS.out / f"report-{rep.name}")
    subprocess.run(["chmod", "-R", "u+w", str(TMP)], capture_output=True)
    shutil.rmtree(TMP, ignore_errors=True)
finish("update_linux", ARGS, out, skips)
