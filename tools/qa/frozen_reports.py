"""Problem reports inside the BUILT BChat.exe (0.3.0): things the source tests can't prove.
Throwaway settings, a local receiver (server/report_receiver.py, no Discord) and BCHAT_REPORT_URL pointing at it:
nothing ever reaches the real bajubesi.org.

Run 1: the crash file is armed (faulthandler on, file fresh), a report goes out and comes back with a BR number,
       then the exe really crashes (access violation through ctypes).
Run 2: the bar says "closed unexpectedly" with the crash in it; then the window is frozen for 12 s and the
       watchdog's "stopped responding" bar shows afterwards.

    python tools/qa/frozen_reports.py [--exe path/to/BChat.exe] [--out DIR]
"""
import json, os, subprocess, sys, tempfile, threading, time
from pathlib import Path

from qa_common import ROOT, finish, parse_args
sys.path.insert(0, str(ROOT / "server"))
ARGS = parse_args("Packaged app: crash and freeze reports inside the exe, to a local receiver.")
EXE = ARGS.exe
tmp = Path(tempfile.mkdtemp())
cfgdir = tmp / "cfg"
(cfgdir / "addons").mkdir(parents=True)
(cfgdir / "config.json").write_text(json.dumps({"nick": "Badaboom", "imported": True, "skip_network_list": True,
                                                "welcome_done": True, "networks": []}))
os.environ.update({"BCHAT_RR_DB": str(tmp / "r.db"), "BCHAT_RR_PICTURES": str(tmp / "pics"), "BCHAT_RR_WEBHOOK_FILE": ""})
import report_receiver as rr
srv = rr.serve(port=0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/bchat/report"

PROBE = r'''
__module_name__ = "probe_reports"
__module_version__ = "1"
__module_description__ = "frozen report check"
import xchat, json, traceback, faulthandler, time
from PySide6.QtWidgets import QApplication
OUT = %r
STAGE = %r
results = {}
def save():
    with open(OUT, "w") as f:
        json.dump(results, f)
def note(name, fn):
    try:
        results[name] = bool(fn())
    except Exception:
        results[name] = False
        results[name + " (error)"] = traceback.format_exc()[-400:]
def win():
    from bchat.mainwindow import MainWindow
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)][0]

def run1(userdata):
    from bchat import reports
    w = win()
    note("crash file armed (faulthandler on)", faulthandler.is_enabled)
    note("crash file starts empty", lambda: (w.cfg_dir / "reports" / "crash.log").read_text() == "")
    from PySide6.QtGui import QAction
    note("Help menu has Report a Problem", lambda: any("Report a &Problem" in a.text() for a in w.findChildren(QAction)))
    note("report goes to the test receiver, not the real one", lambda: reports.REPORT_URL.startswith("http://127.0.0.1:"))
    r = reports.build(w, "Something else", "frozen check", "", "")
    s = reports.Sender(w)
    got = []
    s.done.connect(got.append)
    s.failed.connect(lambda why: got.append({"failed": why}))
    s.send(r, keep_on_fail=False)
    end = time.time() + 15
    while not got and time.time() < end:
        QApplication.processEvents(); time.sleep(0.02)
    results["report answer"] = str(got[:1])
    note("report sent from the exe got a BR number", lambda: got and str(got[0].get("id", "")).startswith("BR-"))
    note("BR number remembered for 'fixed your report'", lambda: w.cfg.my_reports and w.cfg.my_reports[-1]["id"] == "BR-1")
    w.save_config()
    save()
    faulthandler._sigsegv()      # a real, fatal crash (CPython's own test hook): faulthandler writes the crash file
    return 0

def run0(userdata):
    import ctypes
    try:
        ctypes.string_at(0)      # an access violation that ctypes catches: BChat lives on
    except OSError:
        pass
    w = win()
    results["survived error written to the crash file"] = "access violation" in (w.cfg_dir / "reports" / "crash.log").read_text().lower()
    save()
    w.skip_quit_prompt = True
    QApplication.instance().quit()   # a normal close
    return 0

def run2(userdata):
    w = win()
    bar = w.report_bar
    note("after the crash: the bar shows on start", lambda: bar.isVisible() and "closed unexpectedly" in bar.text.text())
    note("the bar carries the real crash", lambda: "fatal" in bar.offer.get("error", "").lower())
    note("crash file is fresh again", lambda: (w.cfg_dir / "reports" / "crash.log").read_text() == "")
    bar.dismiss()
    save()
    time.sleep(12)               # the window's thread is stuck: a freeze
    def after(_):
        note("freeze caught: 'stopped responding' bar", lambda: bar.isVisible() and "stopped responding" in bar.text.text())
        note("freeze report kind is Slow", lambda: bar.offer.get("kind") == "Slow" and bar.offer.get("freeze", 0) >= 10)
        save()
        w.skip_quit_prompt = True
        QApplication.instance().quit()
        return 0
    xchat.hook_timer(2500, after)
    return 0

xchat.hook_timer(3000, {0: run0, 1: run1, 2: run2}[STAGE])
'''


def start(stage: int, out: Path) -> subprocess.Popen:
    (cfgdir / "addons" / "probe_reports.py").write_text(PROBE % (str(out), stage))
    env = dict(os.environ, BCHAT_VAULT="file", BCHAT_REPORT_URL=URL)
    return subprocess.Popen([EXE, "--config-dir", str(cfgdir), "--no-autoconnect"], env=env)


def wait(cond, sec):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


res = {}
out0, out1, out2 = tmp / "r0.json", tmp / "r1.json", tmp / "r2.json"
crash = (cfgdir / "reports" / "crash.log")
p = start(0, out0)
res["run 0 closed normally"] = wait(lambda: p.poll() is not None, 60) and p.returncode == 0
if p.poll() is None:
    p.kill()
if out0.exists():
    res.update(json.loads(out0.read_text()))
res["normal close emptied the crash file (no false 'crashed' bar)"] = crash.exists() and crash.read_text(errors="replace") == ""
p = start(1, out1)
res["run 1 ended by the deliberate crash"] = wait(lambda: p.poll() is not None, 60)
if p.poll() is None:
    p.kill()
res["run 1 exit code is a crash"] = p.returncode not in (0, None)
if out1.exists():
    res.update(json.loads(out1.read_text()))
res["crash file written by the crash"] = crash.exists() and "fatal" in crash.read_text(errors="replace").lower()
res["receiver stored the exe's report"] = srv.store.db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
p = start(2, out2)
res["run 2 quit by itself"] = wait(lambda: p.poll() is not None, 90)
if p.poll() is None:
    p.kill()
if out2.exists():
    res.update(json.loads(out2.read_text()))
srv.shutdown()

res = {k: (str(v) if (k.endswith("(error)") or k == "report answer") else v) for k, v in res.items()}   # text = information
finish("frozen_reports", ARGS, res)
