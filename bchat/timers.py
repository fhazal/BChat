"""/timer and /timers (0.3.0, mIRC's timers).

/timer [name] <times> <seconds> <command>   times 0 = until stopped
/timers                                     this network's timers
/timer <name> off   /timers off             stop one / all

Timers belong to the network they were made on and stop when it disconnects. Safety: at least 1 second apart, at
most 20 per network, and a timer that sends more than 5 lines to the server in 10 seconds is stopped."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer

from .session import ERROR, INFO, Buffer, Session

MIN_SECONDS = 1.0
MAX_PER_NETWORK = 20
FLOOD_LINES, FLOOD_SECONDS = 5, 10.0


@dataclass
class Timer:
    name: str
    times: int          # 0 = forever
    seconds: float
    command: str
    buffer: Buffer
    left: int = 0
    qt: QTimer | None = None
    next_at: float = 0.0
    sent: list = field(default_factory=list)   # (when, lines) for the flood check


def _table(s: Session) -> dict[str, Timer]:
    t = getattr(s, "timers", None)
    if t is None:
        t = s.timers = {}
        s.state_changed.connect(lambda s=s: _on_state(s))
    return t


def _on_state(s: Session) -> None:
    if s.state != "connected" and getattr(s, "timers", None):
        n = len(s.timers)
        stop_all(s)
        s.add(s.server_buffer, INFO, "*", f"{n} timer{'s' if n != 1 else ''} stopped: disconnected.")


def _free_number(table: dict) -> str:
    i = 1
    while str(i) in table:
        i += 1
    return str(i)


def _when(t: Timer) -> str:
    if t.times == 1:
        return f"once, in {t.seconds:g} seconds"
    count = "until stopped" if t.times == 0 else f"{t.times} times"
    return f"{count}, every {t.seconds:g} seconds"


def stop(s: Session, name: str) -> bool:
    t = _table(s).pop(name.lower(), None)
    if t is None:
        return False
    if t.qt is not None:
        t.qt.stop()
        t.qt.deleteLater()
    return True


def stop_all(s: Session) -> int:
    names = list(_table(s))
    for n in names:
        stop(s, n)
    return len(names)


def start(ui, s: Session, b: Buffer, name: str, times: int, seconds: float, command: str) -> Timer | str:
    """A new timer, or why not. A timer with the same name is replaced."""
    if seconds < MIN_SECONDS:
        return f"Timers run at most once a second (you asked for {seconds:g})."
    table = _table(s)
    name = (name or _free_number(table)).lower()
    if name not in table and len(table) >= MAX_PER_NETWORK:
        return f"There are already {MAX_PER_NETWORK} timers on {s.net.name}. Stop one with /timer <name> off."
    stop(s, name)
    t = Timer(name, times, seconds, command, b, left=times)
    t.qt = QTimer(s)
    t.qt.setInterval(int(seconds * 1000))
    t.qt.timeout.connect(lambda: _fire(ui, s, t))
    t.next_at = time.time() + seconds
    table[name] = t
    t.qt.start()
    return t


def _fire(ui, s: Session, t: Timer) -> None:
    from . import commands
    if _table(s).get(t.name) is not t:
        return
    b = t.buffer if t.buffer in s.all_buffers() else s.server_buffer
    before = s.sent_count
    try:
        commands.run(ui, s, b, t.command if t.command.startswith("/") else "/say " + t.command)
    finally:
        now = time.time()
        t.sent = [(w, n) for w, n in t.sent if now - w <= FLOOD_SECONDS] + [(now, s.sent_count - before)]
        t.next_at = now + t.seconds
    if sum(n for _w, n in t.sent) > FLOOD_LINES:
        stop(s, t.name)
        s.add(b, ERROR, "*", f"Timer {t.name} stopped: it sent more than {FLOOD_LINES} lines in {FLOOD_SECONDS:g} seconds.")
        return
    if t.times:
        t.left -= 1
        if t.left <= 0:
            stop(s, t.name)


def listing(s: Session) -> list[str]:
    table = _table(s)
    if not table:
        return [f"No timers on {s.net.name}."]
    out = [f"Timers on {s.net.name}:"]
    now = time.time()
    for t in sorted(table.values(), key=lambda x: (not x.name.isdigit(), x.name.zfill(4))):
        left = "until stopped" if t.times == 0 else ("once" if t.times == 1 else f"{t.left} left")
        every = f"in {max(0, int(t.next_at - now))} s" if t.times == 1 else f"every {t.seconds:g} s"
        out.append(f"  {t.name:<8} {every:<12} {left:<14} {t.command}")
    return out


def command(ui, s: Session, b: Buffer, cmd: str, args: list[str], rest: str) -> None:
    say = lambda text, kind=INFO: s.add(b, kind, "*", text)      # noqa: E731
    if cmd == "timers":
        if args and args[0].lower() == "off":
            n = stop_all(s)
            say(f"{n} timer{'s' if n != 1 else ''} stopped.")
        else:
            for line in listing(s):
                say(line)
        return
    if not args:
        for line in listing(s):
            say(line)
        return
    if len(args) == 2 and args[1].lower() == "off":
        say(f"Timer {args[0]} stopped." if stop(s, args[0]) else f"No timer called {args[0]}.", INFO)
        return
    name, tail = "", rest
    first, _, after = rest.partition(" ")
    if first and not first.isdigit():          # /timer news 3 60 ...: a name first
        name, tail = first, after.strip()
    words = tail.split(None, 2)
    try:
        times, seconds, what = int(words[0]), float(words[1]), words[2]
    except (IndexError, ValueError):
        say("Use: /timer [name] <times> <seconds> <command>   (times 0 = until you stop it)", ERROR)
        return
    if times < 0:
        say("Times can't be below 0.", ERROR)
        return
    got = start(ui, s, b, name, times, seconds, what.strip())
    if isinstance(got, str):
        say(got, ERROR)
    else:
        say(f"Timer {got.name}: {_when(got)}: {got.command}")
