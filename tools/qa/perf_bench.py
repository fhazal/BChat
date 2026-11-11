"""Performance benchmark of the packaged BChat.exe on local test servers (QA item F). Throwaway settings, update
check off, localhost only.

    python tools/qa/perf_bench.py [--exe dist/BChat/BChat.exe] [--out DIR] [--quick] [--soak-min 5]
                                  [--baseline tools/qa/data/perf-baseline.json] [--save-baseline]

Phases:
  A. start-up x5 (1 network): start -> visible window, start -> joined, quit -> process gone
  B. one long session: 3 networks x 5 channels, 2000 scripted users in one channel
     B1 idle         working set, private memory, CPU (% of one core)
     B2 load         300 messages/s over 15 channels + 20 join/part/nick/quit per second: CPU, memory,
                     every message counted inside the app, marker latency, UI stalls (a 20 ms timer in the app)
     B3 burst        5000 messages at once into one channel: how fast BChat works through them
     B4 history      20000 lines into one channel (tabs keep 5000): memory must level off
     B4b fill        every tab filled to its 5000-line limit (15 x 5000 lines)
     B5 soak         steady low traffic for --soak-min minutes on full tabs: memory growth per minute
     B6 after        idle again, then quit time
A probe plugin inside the exe counts messages (hook_print), watches the event loop and quits on request.
Checks that fail the run: the app died or hung, messages lost, a marker never shown. Everything else is a
measurement, compared with the baseline (changes over 15 % are listed as warnings, not failures: a benchmark
on one desktop PC is noisy). Nothing is called better or worse than the numbers show.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from qa_common import ROOT, finish, parse_args, process_memory_cpu
import loadgen
from loadgen import MARK, LoadEnv

DEFAULT_BASELINE = ROOT / "tools" / "qa" / "data" / "perf-baseline.json"
MB = 1048576

PROBE = r'''
__module_name__ = "perfprobe"
__module_version__ = "1"
__module_description__ = "QA performance probe"
import xchat, json, os, time
from PySide6.QtCore import QTimer, QElapsedTimer
from PySide6.QtWidgets import QApplication
STATS, CTL = %r, %r
import collections
st = {"msg": 0, "marks": {}, "gaps": collections.deque(maxlen=3000), "max_gap": 0.0, "since": time.time()}   # last ~60 s
def on_msg(word, *rest):        # BChat calls (word, userdata); XChat docs say (word, word_eol, userdata)
    st["msg"] += 1
    t = word[1] if len(word) > 1 else ""
    if t.startswith("%s") and t not in st["marks"]:
        st["marks"][t] = time.time()
    return xchat.EAT_NONE
for ev in ("Channel Message", "Channel Msg Hilight"):
    xchat.hook_print(ev, on_msg)
clock = QElapsedTimer(); clock.start()
last = [clock.elapsed()]
def beat():                      # every 20 ms; a long gap = the event loop was busy (the UI would not answer)
    now = clock.elapsed(); gap = now - last[0]; last[0] = now
    st["gaps"].append(gap); st["max_gap"] = max(st["max_gap"], gap)
t = QTimer(); t.setInterval(20); t.timeout.connect(beat); t.start()
def report():
    g = sorted(st["gaps"]) or [0]
    out = {"msg": st["msg"], "marks": st["marks"], "lag_max_ms": st["max_gap"],
           "lag_p99_ms": g[min(len(g) - 1, int(len(g) * 0.99))], "lag_n": len(g), "written": time.time()}
    tmp = STATS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, STATS)
    try:
        cmd = open(CTL).read().strip()
    except OSError:
        cmd = ""
    if cmd == "reset-lag":
        st["gaps"].clear(); st["max_gap"] = 0.0
        os.remove(CTL)
    elif cmd == "quit":
        os.remove(CTL)
        from bchat.mainwindow import MainWindow
        w = [x for x in QApplication.topLevelWidgets() if isinstance(x, MainWindow)][0]
        w.skip_quit_prompt = True
        w._quit_for_real()
r = QTimer(); r.setInterval(250); r.timeout.connect(report); r.start()
_keep = (t, r)
'''

u32 = ctypes.windll.user32


def visible_window(pid: int) -> bool:
    found = []

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        p = W.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, b, n + 1)
            if b.value.startswith("BChat"):
                found.append(1)
        return True
    u32.EnumWindows(cb, 0)
    return bool(found)


class App:
    """The exe with a throwaway settings folder and the probe plugin."""

    def __init__(self, exe: str, env: LoadEnv, folder: Path):
        self.folder = folder
        cfg = env.write_config(folder / "cfg")
        (cfg / "addons").mkdir(exist_ok=True)
        self.stats_path, self.ctl = folder / "stats.json", folder / "ctl.txt"
        (cfg / "addons" / "perfprobe.py").write_text(PROBE % (str(self.stats_path), str(self.ctl), MARK), encoding="utf-8")
        e = dict(os.environ, BCHAT_VAULT="file")
        for k in ("APPDATA", "LOCALAPPDATA"):
            (folder / k).mkdir(exist_ok=True)
            e[k] = str(folder / k)
        self.t0 = time.perf_counter()
        self.p = subprocess.Popen([exe, "--config-dir", str(cfg)], env=e)

    def alive(self) -> bool:
        return self.p.poll() is None

    def stats(self) -> dict:
        try:
            return json.loads(self.stats_path.read_text())
        except (OSError, ValueError):
            return {}

    def command(self, cmd: str):
        self.ctl.write_text(cmd)

    def sample(self) -> tuple[float, float, float]:
        ws, priv, cpu = process_memory_cpu(self.p.pid)
        return ws / MB, priv / MB, cpu

    def wait_marks(self, keys: list[str], timeout: float) -> float | None:
        """When the LAST of these markers was shown, or None if not all of them came within timeout."""
        end = time.time() + timeout
        while time.time() < end and self.alive():
            marks = self.stats().get("marks", {})
            if all(k in marks for k in keys):
                return max(marks[k] for k in keys)
            time.sleep(0.05)
        return None

    def wait_count(self, want: int, timeout: float = 30) -> int:
        """Wait until the app counted `want` channel messages in total; returns the count it got."""
        end = time.time() + timeout
        n = self.stats().get("msg", 0)
        while time.time() < end and self.alive() and n < want:
            time.sleep(0.05)
            n = self.stats().get("msg", 0)
        return n

    def quit(self, timeout: float = 30) -> float | None:
        t = time.perf_counter()
        self.command("quit")
        try:
            self.p.wait(timeout)
            return time.perf_counter() - t
        except subprocess.TimeoutExpired:
            self.p.kill()
            return None


def cpu_over(app: App, seconds: float, every: float = 5.0) -> dict:
    """CPU (% of one core) and memory over a window, sampled every few seconds."""
    ws0, pv0, c0 = app.sample()
    t0 = time.perf_counter()
    peak_ws = ws0
    while time.perf_counter() - t0 < seconds and app.alive():
        time.sleep(min(every, max(0.0, seconds - (time.perf_counter() - t0))))
        ws, pv, c = app.sample()
        peak_ws = max(peak_ws, ws)
    ws1, pv1, c1 = app.sample()
    took = time.perf_counter() - t0
    return {"cpu_pct": round((c1 - c0) / took * 100, 2), "ws_mb": round(ws1, 1), "private_mb": round(pv1, 1),
            "peak_ws_mb": round(max(peak_ws, ws1), 1), "seconds": round(took, 1)}


def slope_mb_per_min(points: list[tuple[float, float]]) -> float:
    """Least-squares slope of (seconds, MB) points, in MB per minute."""
    if len(points) < 3:
        return 0.0
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return round(sum((x - mx) * (y - my) for x, y in points) / den * 60, 3) if den else 0.0


def main():
    def extra(ap):
        ap.add_argument("--quick", action="store_true", help="shorter phases (a smoke run, not for comparisons)")
        ap.add_argument("--soak-min", type=float, default=5.0)
        ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
        ap.add_argument("--save-baseline", action="store_true", help="make this run the new baseline")
    args = parse_args("Performance benchmark of the packaged app (local servers only).", extra)
    q = args.quick
    idle_s, load_s, soak_s = (15, 15, 30) if q else (60, 60, args.soak_min * 60)
    starts = 2 if q else 5
    res, m, info = {}, {}, {}
    tmp = Path(tempfile.mkdtemp(prefix="bchat-perf-"))

    # A. start-up
    win, joined, quit_s = [], [], []
    for i in range(starts):
        env = LoadEnv(1, 1)
        app = App(args.exe, env, tmp / f"start{i}")
        tw = None
        while time.perf_counter() - app.t0 < 30 and tw is None and app.alive():
            if visible_window(app.p.pid):
                tw = time.perf_counter() - app.t0
            time.sleep(0.01)
        try:
            env.servers[0].wait_handled("^JOIN ", timeout=30)
            tj = time.perf_counter() - app.t0
        except TimeoutError:
            tj = None
        time.sleep(3)
        qs = app.quit()
        env.stop()
        win.append(tw)
        joined.append(tj)
        quit_s.append(qs)
    res["start-up: window appeared every time"] = all(x is not None for x in win)
    res["start-up: joined the local server every time"] = all(x is not None for x in joined)
    res["start-up: quit cleanly every time (exit within 30 s)"] = all(x is not None for x in quit_s)
    ok = [x for x in win if x is not None]
    if ok:
        m["startup_window_s"] = round(statistics.median(ok), 3)
    ok = [x for x in joined if x is not None]
    if ok:
        m["startup_joined_s"] = round(statistics.median(ok), 3)
    ok = [x for x in quit_s if x is not None]
    if ok:
        m["shutdown_s"] = round(statistics.median(ok), 3)
    info["start-up runs (window s)"] = [round(x, 3) if x else None for x in win]

    # B. the long session
    env = LoadEnv(networks=3, channels=5, nicks=2000)
    app = App(args.exe, env, tmp / "session")
    try:
        m["connect_all_15_channels_s"] = round(env.wait_joined(60), 2)
        res["session: joined 15 channels on 3 networks"] = True
    except TimeoutError:
        res["session: joined 15 channels on 3 networks"] = False
    time.sleep(20)                                                      # settle
    b1 = cpu_over(app, idle_s)
    m.update(idle_cpu_pct=b1["cpu_pct"], idle_ws_mb=b1["ws_mb"], idle_private_mb=b1["private_mb"])

    # B2 load: flood + storm at the same time (storm on a thread)
    import threading
    app.command("reset-lag")
    time.sleep(0.5)
    before = app.stats().get("msg", 0)
    sent0 = env.sent
    storm_res = {}
    th = threading.Thread(target=lambda: storm_res.update(loadgen.storm(env, 20, load_s)), daemon=True)
    th.start()
    w0 = app.sample()
    t_load = time.perf_counter()
    fl = loadgen.flood(env, 300, load_s)
    th.join(load_s + 30)
    load_cpu = app.sample()
    took = time.perf_counter() - t_load
    sent_mark, keys = loadgen.marker(env, "after-load")
    seen = app.wait_marks(keys, 60)                                     # the last of the 15 markers
    flood_sent = env.sent - sent0                                       # includes the 15 marker lines
    got = app.wait_count(before + flood_sent) - before
    st = app.stats()
    m.update(load_cpu_pct=round((load_cpu[2] - w0[2]) / took * 100, 2), load_ws_mb=round(load_cpu[0], 1),
             load_private_mb=round(load_cpu[1], 1), load_rate_sent=fl["rate"],
             load_marker_latency_s=round(seen - sent_mark, 3) if seen else None,
             load_ui_stall_max_ms=st.get("lag_max_ms"), load_ui_stall_p99_ms=st.get("lag_p99_ms"))
    res["load: every message reached the app (counted inside it)"] = got == flood_sent
    info["load: messages sent / counted in the app"] = f"{flood_sent} / {got}"
    info["load: storm events"] = storm_res.get("events")
    res["load: marker after the load was shown"] = seen is not None

    # B3 burst
    app.command("reset-lag")
    time.sleep(0.5)
    b0 = app.stats().get("msg", 0)
    tb = time.time()
    loadgen.burst(env, 5000)                                            # into the first channel of network 1
    _, keys = loadgen.marker(env, "after-burst", targets=[(env.servers[0], env.channels[0])])
    seen = app.wait_marks(keys, 120)
    res["burst: 5000 messages + marker all counted"] = seen is not None and app.wait_count(b0 + 5001) - b0 == 5001
    st = app.stats()
    if seen:
        m["burst_5000_s"] = round(seen - tb, 3)
        m["burst_msgs_per_s"] = round(5000 / max(0.001, seen - tb), 1)
    m["burst_ui_stall_max_ms"] = st.get("lag_max_ms")

    # B4 history: past the 5000-line tab limit, memory should level off
    time.sleep(5)
    h_before = app.sample()[0]
    loadgen.history(env, 10000, chan_index=1)
    app.wait_marks(loadgen.marker(env, "after-history-1", targets=[(env.servers[0], env.channels[1])])[1], 120)
    time.sleep(5)
    h_mid = app.sample()[0]
    loadgen.history(env, 10000, chan_index=1)
    res["history: 20000 lines processed"] = app.wait_marks(
        loadgen.marker(env, "after-history-2", targets=[(env.servers[0], env.channels[1])])[1], 120) is not None
    time.sleep(5)
    h_after = app.sample()[0]
    m.update(history_ws_before_mb=round(h_before, 1), history_ws_10k_mb=round(h_mid, 1), history_ws_20k_mb=round(h_after, 1))
    info["history: second 10000 lines added (MB)"] = round(h_after - h_mid, 1)

    # B4b fill every tab to its 5000-line limit, so the soak below can't be "tabs filling up"
    for ci in range(len(env.channels)):
        for s_ in env.servers:
            for i in range(5000):
                env.say(s_, env.channels[ci], f"fill line {i + 1} with some text to make it a normal length chat line")
    res["fill: every tab filled to its 5000-line limit"] = app.wait_marks(loadgen.marker(env, "after-fill")[1], 300) is not None
    time.sleep(10)
    m["filled_ws_mb"] = round(app.sample()[0], 1)

    # B5 soak (every tab already full: memory should stay flat if nothing leaks)
    points = []
    t_soak = time.perf_counter()
    s0 = app.stats().get("msg", 0)
    sent_soak0 = env.sent
    th = threading.Thread(target=lambda: loadgen.storm(env, 2, soak_s), daemon=True)
    th.start()
    chunk = 15
    while time.perf_counter() - t_soak < soak_s and app.alive():
        loadgen.flood(env, 20, min(chunk, soak_s - (time.perf_counter() - t_soak)))
        points.append((time.perf_counter() - t_soak, app.sample()[0]))
    th.join(30)
    res["soak: marker after the soak was shown"] = app.wait_marks(loadgen.marker(env, "after-soak")[1], 60) is not None
    res["soak: every message reached the app"] = app.wait_count(s0 + env.sent - sent_soak0) - s0 == env.sent - sent_soak0
    half = [p for p in points if p[0] >= soak_s / 2]
    m["soak_minutes"] = round(soak_s / 60, 1)
    m["soak_ws_growth_mb_per_min"] = slope_mb_per_min(half)
    m["soak_ws_end_mb"] = round(points[-1][1], 1) if points else None
    info["soak samples (s, MB)"] = [(round(a), round(b, 1)) for a, b in points]

    # B6 after
    time.sleep(10)
    b6 = cpu_over(app, 30 if not q else 10)
    m.update(after_idle_cpu_pct=b6["cpu_pct"], after_idle_ws_mb=b6["ws_mb"])
    res["session: app alive until the end"] = app.alive()
    qs = app.quit()
    res["session: quit cleanly"] = qs is not None
    if qs is not None:
        m["shutdown_after_session_s"] = round(qs, 3)
    env.stop()

    # baseline comparison
    base_p = Path(args.baseline)
    base = json.loads(base_p.read_text()).get("metrics", {}) if base_p.exists() else {}
    comp, warn = {}, []
    lower_is_better = {k for k in m if not k.endswith(("msgs_per_s", "rate_sent")) and k not in ("soak_minutes",)}
    for k, v in m.items():
        b = base.get(k)
        if isinstance(v, (int, float)) and isinstance(b, (int, float)) and b:
            ch = (v - b) / abs(b) * 100
            comp[k] = {"now": v, "baseline": b, "change_pct": round(ch, 1)}
            worse = ch > 15 if k in lower_is_better else ch < -15
            if worse and abs(v - b) > (0.05 if k.endswith("_s") else 2.0 if k.endswith(("_mb", "_ms")) else 0.5):
                warn.append(f"{k}: {v} vs baseline {b} ({ch:+.1f} %)")
    info["baseline"] = str(base_p) if base else "none (run with --save-baseline to set one)"
    if args.save_baseline and not q:
        base_p.write_text(json.dumps({"_about": "perf_bench.py metrics of the known-good build (docs/QA-BASELINE.md). "
                                                "Update only on purpose (--save-baseline).",
                                      "exe_version": args.expect, "saved": time.strftime("%Y-%m-%d %H:%M"),
                                      "metrics": m}, indent=1), encoding="utf-8")
        info["baseline saved"] = str(base_p)
    for k, v in m.items():
        res[f"metric {k}"] = v
    for w in warn:
        res[f"WARNING {w}"] = "differs from the baseline by more than 15 %"
    res.update(info)
    finish("perf_bench", args, res, extra={"metrics": m, "comparison": comp, "warnings": warn,
                                           "quick": q, "cpu_count": os.cpu_count()})


if __name__ == "__main__":
    main()
