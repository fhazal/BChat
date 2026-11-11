"""Local IRC load generator (QA item C), built on the test simulator tests/qa_ircd.py. Localhost only: it never
talks to a public network.

As a tool: start local servers, write a BChat settings folder for them, wait for BChat, run a scenario:

    python tools/qa/loadgen.py --networks 2 --channels 5 --nicks 2000 --scenario flood --rate 200 --duration 30
        then, in another window:  python -m bchat --config-dir <the folder it prints>

Scenarios: flood (messages at a steady rate over every channel), storm (join/part/nick/quit of scripted users),
burst (N messages as fast as possible), history (N lines into one channel), soak (low steady traffic for long).
As a library (tools/qa/perf_bench.py uses it): LoadEnv + the scenario functions below. Deterministic text:
messages are numbered, scripted users are named user0001.. and the order is always the same.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from qa_ircd import QaIrcd  # noqa: E402

MARK = "QA-MARK-"


class LoadEnv:
    """networks x channels on local simulator servers, optional big nick list in the first channel."""

    def __init__(self, networks: int = 1, channels: int = 1, nicks: int = 0, caps=None):
        kw = {"caps": caps} if caps is not None else {}
        self.servers = [QaIrcd(name=f"irc{i + 1}.load.test", network=f"LoadNet{i + 1}", **kw) for i in range(networks)]
        self.channels = [f"#load{j + 1}" for j in range(channels)]
        self.ghosts = []
        if nicks:
            self.ghosts = self.servers[0].add_ghosts(self.channels[0], nicks, op_every=50)
        self.sent = 0                      # PRIVMSGs delivered to clients (one per message per client)
        self._seq = itertools.count(1)

    def targets(self):
        return [(s, c) for s in self.servers for c in self.channels]

    def bchat_config(self, nick: str = "LoadUser") -> dict:
        """A BChat config.json body: every network connects at start and joins every channel."""
        return {"nick": nick, "nick2": nick + "_", "imported": True, "skip_network_list": True, "welcome_done": True,
                "ask_on_quit": False, "update_check": False, "reconnect_delay": 2,
                "networks": [{"name": s.network, "servers": [{"host": s.host, "port": s.port}],
                              "autojoin": ",".join(self.channels), "autoconnect": True} for s in self.servers]}

    def write_config(self, folder: Path, nick: str = "LoadUser") -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text(json.dumps(self.bchat_config(nick)), encoding="utf-8")
        return folder

    def wait_joined(self, timeout: float = 60, pump=None) -> float:
        """Wait until a client joined every channel on every server; returns the seconds it took."""
        t0 = time.time()
        for s in self.servers:
            for c in self.channels:
                s.wait_handled(f"^JOIN .*{c}(,|$)", timeout=max(1, timeout - (time.time() - t0)), pump=pump)
        return time.time() - t0

    def say(self, srv: QaIrcd, chan: str, text: str, sender: str = "talker!t@load.test") -> None:
        self.sent += srv.inject(sender, chan, text)

    def stop(self):
        for s in self.servers:
            s.stop()


def _paced(rate: float, duration: float):
    """Yield i = 0, 1, 2... on a steady schedule (rate per second) for duration seconds."""
    t0 = time.perf_counter()
    for i in itertools.count():
        due = t0 + i / rate
        if due - t0 >= duration:
            return
        now = time.perf_counter()
        if due > now:
            time.sleep(due - now)
        yield i


def flood(env: LoadEnv, rate: float, duration: float) -> dict:
    """Messages at `rate` per second, round-robin over every channel of every network."""
    targets = env.targets()
    before, t0 = env.sent, time.perf_counter()
    for i in _paced(rate, duration):
        s, c = targets[i % len(targets)]
        env.say(s, c, f"flood message {next(env._seq)} in {c}")
    took = time.perf_counter() - t0
    return {"messages": env.sent - before, "seconds": round(took, 2), "rate": round((env.sent - before) / took, 1)}


def storm(env: LoadEnv, rate: float, duration: float) -> dict:
    """Join/part/nick/quit of scripted users at `rate` events per second (first network, first channel)."""
    s, chan = env.servers[0], env.channels[0]
    n = 0
    names = itertools.count(1)
    alive: list[str] = []
    for i in _paced(rate, duration):
        kind = i % 4
        if kind == 0 or not alive:
            nick = f"storm{next(names):05d}"
            s.add_ghost(chan, nick, announce=True)
            alive.append(nick)
        elif kind == 1:
            new = f"storm{next(names):05d}"
            s.ghost_nick(alive.pop(0), new)
            alive.append(new)
        elif kind == 2:
            s.ghost_part(chan, alive.pop(0))
        else:
            s.ghost_quit(alive.pop(0))
        n += 1
    for nick in alive:                     # leave the list as it was
        s.ghost_quit(nick)
    return {"events": n}


def burst(env: LoadEnv, count: int, chan_index: int = 0) -> dict:
    s, c = env.servers[0], env.channels[chan_index]
    t0 = time.perf_counter()
    for i in range(count):
        env.say(s, c, f"burst message {i + 1}")
    return {"messages": count, "send_seconds": round(time.perf_counter() - t0, 3)}


def history(env: LoadEnv, lines: int, chan_index: int = 0) -> dict:
    s, c = env.servers[0], env.channels[chan_index]
    t0 = time.perf_counter()
    for i in range(lines):
        env.say(s, c, f"history line {i + 1} with some text to make it a normal length chat line")
    return {"lines": lines, "send_seconds": round(time.perf_counter() - t0, 3)}


def marker(env: LoadEnv, name: str, targets=None) -> tuple[float, list[str]]:
    """One unique line per channel (default: every channel): QA-MARK-<name>:<network>:<channel>.
    Returns (when it was sent, the marker texts). A marker comes after everything sent before it on the same
    connection, so seeing it means that connection's earlier lines were processed."""
    t = time.time()
    keys = []
    for s, c in (targets or env.targets()):
        k = f"{MARK}{name}:{s.network}:{c}"
        env.say(s, c, k)
        keys.append(k)
    return t, keys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--networks", type=int, default=1)
    ap.add_argument("--channels", type=int, default=3)
    ap.add_argument("--nicks", type=int, default=0, help="scripted users in the first channel")
    ap.add_argument("--scenario", choices=("flood", "storm", "burst", "history", "soak"), default="flood")
    ap.add_argument("--rate", type=float, default=100, help="messages (or events) per second")
    ap.add_argument("--duration", type=float, default=30, help="seconds")
    ap.add_argument("--count", type=int, default=5000, help="burst / history size")
    ap.add_argument("--config-dir", default="", help="where to write BChat's settings (default: a new temp folder)")
    ap.add_argument("--wait", type=float, default=300, help="seconds to wait for BChat to join everything")
    a = ap.parse_args()
    env = LoadEnv(a.networks, a.channels, a.nicks)
    try:
        cfg = env.write_config(Path(a.config_dir) if a.config_dir else Path(tempfile.mkdtemp(prefix="bchat-load-")))
        print(f"servers: {', '.join(f'{s.name} 127.0.0.1:{s.port}' for s in env.servers)}")
        print(f"start BChat with:  python -m bchat --config-dir \"{cfg}\"   (or BChat.exe --config-dir ...)")
        print(f"joined everything after {env.wait_joined(a.wait):.1f} s; running {a.scenario}...", flush=True)
        if a.scenario == "flood":
            r = flood(env, a.rate, a.duration)
        elif a.scenario == "storm":
            r = storm(env, a.rate, a.duration)
        elif a.scenario == "burst":
            r = burst(env, a.count)
        elif a.scenario == "history":
            r = history(env, a.count)
        else:
            r = flood(env, min(a.rate, 20), a.duration)
        marker(env, "done")
        print(json.dumps(r))
    finally:
        env.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
