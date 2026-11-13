"""Problem reports (0.3.0): BChat writes the report, the user only says yes.

What is in a report: version, Windows version, scaling, theme, what happened (one word), what the user typed,
the error and where it happened, the last steps (clicks and command NAMES, never message text), the open tab
kind and size, the number of plugins. Before anything leaves the PC, nicks, channels, networks, servers, the
Windows user and PC name, IP addresses, e-mail addresses, hostmasks and links are replaced (Redactor), and the
user sees every word in "See what's sent". Chat text and passwords are never collected at all.

Crashes: faulthandler writes a crash file only on a fatal error, so a bar on the next start means a real crash
(a Windows restart or a killed BChat never looks like one). Errors inside a click keep BChat running: the same
bar shows at once, once per error. Freezes: a watchdog thread sees the window stuck for FREEZE_SECONDS.
"""
from __future__ import annotations

import base64
import faulthandler
import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

KINDS = ("Crashed", "Won't connect", "Looks wrong", "Slow", "Something else")
REPORT_URL = os.environ.get("BCHAT_REPORT_URL", "https://bajubesi.org/bchat/report")
MAX_STEPS = 20
FREEZE_SECONDS = 10
MAX_PICTURE = 2_000_000          # bytes of PNG
MAX_TEXT = 4000                  # characters per free-text field


# --- last steps ------------------------------------------------------------------------------------------------

class Steps:
    """The last clicks and command names, newest last. Never what was typed into a chat."""

    def __init__(self) -> None:
        self.items: deque[tuple[str, str]] = deque(maxlen=MAX_STEPS)

    def add(self, text: str) -> None:
        text = " ".join(text.replace("&&", "\0").replace("&", "").replace("\0", "&").split())
        if text:
            self.items.append((time.strftime("%H:%M:%S"), text[:80]))

    def list(self) -> list[list[str]]:
        return [[t, s] for t, s in self.items]


STEPS = Steps()


class StepWatcher(QObject):
    """App-wide: remembers which button or menu item was clicked (its words only)."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonRelease:
            try:
                self._clicked(obj, ev)
            except Exception:       # a report helper must never break a click
                pass
        return False

    @staticmethod
    def _clicked(obj, ev) -> None:
        from PySide6.QtWidgets import QAbstractButton, QMenu
        if isinstance(obj, QMenu):
            a = obj.actionAt(ev.position().toPoint())
            if a is not None and a.isEnabled() and not a.isSeparator() and a.menu() is None and a.text():
                head = obj.title() or ""
                STEPS.add(f"{head} > {a.text()}" if head else a.text())
        elif isinstance(obj, QAbstractButton) and obj.isEnabled() and obj.text():
            win = obj.window()
            title = (win.windowTitle() or "").replace("BChat: ", "") if win is not None else ""
            STEPS.add(f"{title} > {obj.text()}" if title else obj.text())


def command_step(text: str) -> None:
    """Typed input: only the command's name ("/join"), or that a message was sent. Never the words."""
    if text.startswith("/") and len(text) > 1:
        STEPS.add("typed /" + text[1:].split(None, 1)[0].lower()[:20])
    elif text.strip():
        STEPS.add("sent a message")


# --- privacy -------------------------------------------------------------------------------------------------

_NICK_EDGE = r"[\w\[\]\\`^{}|-]"
_OWN_WORDS = re.compile(r'(?<=\.py"), line \d+, in (?=[\w<])|\b(?:Ctrl|Shift|Alt|Meta)\+(?=\w)')
_IP4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# full form (8 groups) or any form with "::"; plain times like 01:58:12 never match
_IP6 = re.compile(r"(?<![\w:])(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:)*:(?::?[0-9a-fA-F]{1,4})*(?:\.\d{1,3}){0,3})(?![\w:])")
_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_MASK = re.compile(r"\b[^\s!@]+![^\s!@]+@[^\s!@]+")
_URL = re.compile(r"\b(?:https?|ircs?|ftp)://\S+", re.I)
_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/][^\s\"'<>|]*?[\\/](bchat[\\/][\w\\/.-]+\.py)|(?<![A-Za-z])[A-Za-z]:[\\/][^\s\"'<>|]*[\\/]([\w.-]+)")


class Redactor:
    """Replaces names that say who or where someone is. Longest names first; nicks only as whole words."""

    def __init__(self, nicks=(), channels=(), networks=(), servers=(), extra=()) -> None:
        self.rules: list[tuple[re.Pattern, str]] = []
        seen: set[str] = set()
        groups = (("network", networks, False), ("server", servers, False), ("chan", channels, False), ("nick", nicks, True))
        found: list[tuple[str, str, bool]] = []
        for kind, names, word in groups:
            n = 0
            for name in sorted({x for x in names if x and len(x) >= 2}, key=lambda x: (-len(x), x.lower())):
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                n += 1
                label = f"#<chan{n}>" if kind == "chan" else f"<{kind}{n}>"
                found.append((name, label, word))
        for name, label in extra:
            if name and len(name) >= 2 and name.lower() not in seen:
                seen.add(name.lower())
                found.append((name, label, True))
        for name, label, word in sorted(found, key=lambda f: -len(f[0])):
            esc = re.escape(name)
            pat = rf"(?<!{_NICK_EDGE}){esc}(?!{_NICK_EDGE})" if word or not name.startswith(("#", "&")) else rf"{esc}(?!{_NICK_EDGE})"
            self.rules.append((re.compile(pat, re.I), label))

    def __call__(self, text: str) -> str:
        if not text:
            return text
        text = _URL.sub("<link>", text)
        text = _PATH.sub(lambda m: m.group(1).replace("\\", "/") if m.group(1) else "<path>/" + m.group(2), text)
        text = _MASK.sub("<mask>", text)
        text = _MAIL.sub("<email>", text)
        text = _IP6.sub("<ip>", text)
        text = _IP4.sub("<ip>", text)
        # BChat's own wording, never a name: a nick 'line' or 'Ctrl' made 'line 153' / 'Ctrl+V' unreadable (BR-4)
        kept: list[str] = []

        def hold(m: re.Match) -> str:
            kept.append(m.group(0))
            return f"\x00{len(kept) - 1}\x00"
        text = _OWN_WORDS.sub(hold, text)
        for pat, label in self.rules:
            text = pat.sub(label, text)
        return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text) if kept else text


def redactor_for(win) -> Redactor:
    """Every name this BChat knows that could say who or where someone is."""
    c = win.cfg
    nicks, chans, nets, servers = {c.nick, c.nick2, c.nick3, c.username, c.realname}, set(), set(), set()
    nicks.update(getattr(c, "friends", []) or [])
    for n in c.networks:
        nets.add(n.name)
        servers.update(s.host for s in n.servers)
        for word in re.split(r"[,\s]+", n.autojoin or ""):
            if word.startswith(("#", "&")):
                chans.add(word)
        for attr in ("nick", "nick2", "username", "realname"):
            nicks.add(getattr(n, attr, "") or "")
    sessions = getattr(win, "sessions", {}) or {}
    for s in (sessions.values() if isinstance(sessions, dict) else sessions):
        nets.add(s.net.name)
        nicks.add(s.nick)
        if getattr(s, "server_name", ""):
            servers.add(s.server_name)
        for b in s.all_buffers():
            (chans if b.name.startswith(("#", "&")) else nicks).add(b.name)
            for u in b.users.values():
                nicks.add(u.nick)
    extra = []
    for key, label in (("USERNAME", "<user>"), ("COMPUTERNAME", "<pc>"), ("USERDOMAIN", "<pc>")):
        if os.environ.get(key):
            extra.append((os.environ[key], label))
    return Redactor(nicks, chans, nets, servers, extra)


# --- errors --------------------------------------------------------------------------------------------------

def error_text(etype, value, tb) -> str:
    lines = traceback.format_exception(etype, value, tb)
    return "".join(lines[-14:]).strip()[-MAX_TEXT:]


def fingerprint(text: str) -> str:
    """Same bug, same fingerprint: the error's type and the BChat functions it went through (no line numbers,
    no values), so one bug reported by many people groups together on the server."""
    if not text:
        return ""
    kind = text.strip().splitlines()[-1].split(":", 1)[0].strip()
    where = re.findall(r"bchat[\\/](\w+)\.py\", line \d+, in (\w+)", text) or re.findall(r"File \"[^\"]*?(\w+)\.py\", line \d+ in (\w+)", text)
    raw = kind + "|" + "|".join(f"{f}.{fn}" for f, fn in where[-6:])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


class ErrorCatcher(QObject):
    """sys.excepthook + threading.excepthook: remember the error, tell the window (once per fingerprint)."""
    caught = Signal(str, str)        # text, fingerprint

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.seen: set[str] = set()
        self._old = sys.excepthook
        self._old_thread = threading.excepthook
        sys.excepthook = self._hook
        threading.excepthook = lambda a: self._hook(a.exc_type, a.exc_value, a.exc_traceback)

    def _hook(self, etype, value, tb) -> None:
        try:
            self._old(etype, value, tb)
        except Exception:
            pass
        if etype in (KeyboardInterrupt, SystemExit):
            return
        text = error_text(etype, value, tb)
        sig = fingerprint(text)
        if sig not in self.seen:
            self.seen.add(sig)
            self.caught.emit(text, sig)      # queued into the window's thread when it comes from another one

    def close(self) -> None:
        sys.excepthook, threading.excepthook = self._old, self._old_thread


class CrashFile:
    """faulthandler writes here on a crash. Read at start: something in it = last run crashed. A normal close
    empties it (close()), because on Windows faulthandler also logs errors that were caught and survived."""

    def __init__(self, folder: Path) -> None:
        self.path = folder / "crash.log"
        folder.mkdir(parents=True, exist_ok=True)
        self.previous = ""
        try:
            self.previous = self.path.read_text(encoding="utf-8", errors="replace").strip()[-MAX_TEXT:]
        except OSError:
            pass
        self._f = None
        try:
            self._f = open(self.path, "w", encoding="utf-8")
            faulthandler.enable(self._f, all_threads=False)
        except (OSError, RuntimeError, ValueError):
            self._f = None

    def close(self) -> None:
        if self._f is not None:
            try:
                faulthandler.disable()
                self._f.close()
            except Exception:
                pass
            self._f = None
        # BChat closed normally, so nothing in the file was fatal. (On Windows faulthandler also writes errors that
        # were caught and survived, e.g. an access violation turned into an OSError by ctypes: found by the frozen
        # check 11-09. Emptying it here means only a run that never closed normally can leave a crash behind.)
        try:
            self.path.write_text("", encoding="utf-8")
        except OSError:
            pass


class Watchdog(QObject):
    """A heartbeat on the window's thread; a thread watches it. Stuck FREEZE_SECONDS = a freeze. A gap in the
    watcher's own sleep (PC asleep, BChat paused) is never a freeze."""
    recovered = Signal(float, str)   # seconds stuck, where it was stuck

    def __init__(self, folder: Path, parent=None, limit: float = FREEZE_SECONDS) -> None:
        super().__init__(parent)
        self.limit = limit
        self.file = folder / "freeze.json"
        self.beat = time.monotonic()
        self.main_id = threading.main_thread().ident
        self.stuck_since = 0.0
        self.stack = ""
        self.done: tuple[float, str] | None = None
        self._stop = threading.Event()
        self.timer = QTimer(self, interval=500, timeout=self._tick)
        self.timer.start()
        threading.Thread(target=self._watch, name="bchat-watchdog", daemon=True).start()

    def _tick(self) -> None:
        self.beat = time.monotonic()
        if self.done is not None:
            secs, stack = self.done
            self.done = None
            try:
                self.file.unlink()
            except OSError:
                pass
            self.recovered.emit(secs, stack)

    def _watch(self) -> None:
        last = time.monotonic()
        while not self._stop.wait(1.0):
            now = time.monotonic()
            if now - last > 5:              # this thread slept far too long: the PC slept, not BChat froze
                self.beat = now
                self.stuck_since = 0.0
            last = now
            gap = now - self.beat
            if gap >= self.limit and not self.stuck_since:
                self.stuck_since = self.beat
                frame = sys._current_frames().get(self.main_id)
                self.stack = "".join(traceback.format_stack(frame)[-12:]).strip()[-MAX_TEXT:] if frame else ""
                try:
                    self.file.write_text(json.dumps({"seconds": round(gap), "stack": self.stack}), encoding="utf-8")
                except OSError:
                    pass
            elif gap < 2 and self.stuck_since:
                self.done = (now - self.stuck_since, self.stack)
                self.stuck_since = 0.0

    def stop(self) -> None:
        self._stop.set()
        self.timer.stop()


def leftover_freeze(folder: Path) -> tuple[float, str] | None:
    """A freeze file left by a run that never came back (closed while stuck)."""
    f = folder / "freeze.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        f.unlink()
        return float(d.get("seconds", 0)), str(d.get("stack", ""))
    except (OSError, ValueError):
        return None


# --- the report ----------------------------------------------------------------------------------------------

def _open_text(win) -> str:
    b = getattr(win, "buf", None)
    if b is None:
        return "main window"
    kind = {"channel": "channel", "query": "private chat", "server": "server tab"}.get(b.kind, b.kind)
    users = f", {len(b.users)} users" if b.kind == "channel" else ""
    return f"main window, tab {b.name} ({kind}{users})"


def build(win, kind: str, wrote: str = "", error: str = "", sig: str = "", freeze: float = 0.0,
          picture: bytes = b"") -> dict:
    from . import full_version, sysinfo
    red = redactor_for(win)
    try:
        osname = sysinfo.os_text()
    except Exception:
        osname = "Windows"
    try:
        scale = f"{round(win.devicePixelRatioF() * 100)} %"
    except Exception:
        scale = "?"
    plugins = getattr(getattr(win, "plugins", None), "plugins", [])
    r = {
        "v": 1,
        "bchat": full_version(),
        "os": osname,
        "scale": scale,
        "theme": win.cfg.theme.name,
        "kind": kind if kind in KINDS else "Something else",
        "wrote": red(wrote.strip())[:MAX_TEXT],
        "error": red(error)[:MAX_TEXT],
        "sig": sig or fingerprint(error),
        "freeze": round(freeze),
        "steps": [[t, red(s)] for t, s in STEPS.list()],
        "open": red(_open_text(win)),
        "plugins": len(plugins),
    }
    if picture:
        r["picture"] = base64.b64encode(picture[:MAX_PICTURE]).decode()
    return r


def render(r: dict) -> str:
    """Exactly what is sent, as the user reads it in "See what's sent" (the picture is shown below it)."""
    out = [f"BChat {r['bchat']} · {r['os']} · {r['scale']} · {r['theme']}", f"What happened: {r['kind']}"]
    if r.get("wrote"):
        out.append(f"You wrote: {r['wrote']}")
    if r.get("freeze"):
        out.append(f"Stopped responding for {r['freeze']} seconds")
    if r.get("error"):
        out += ["", "Error:", r["error"]]
    if r.get("steps"):
        out += ["", "Last steps:"] + [f"  {t}  {s}" for t, s in r["steps"]]
    out += ["", f"Open: {r['open']}", f"Plugins: {r['plugins'] or 'none'}"]
    if r.get("picture"):
        out.append(f"Picture of BChat's window: {round(len(r['picture']) * 3 / 4 / 1024)} KB (below)")
    out += ["", "Not included in this text: chat text, passwords, IP addresses,", "real nicks, channels, networks and server names."]
    if r.get("picture"):
        out.append("The picture is different: it shows the window as it is, chat included.")
    out.append(f"Size: {max(1, round(len(json.dumps(r)) / 1024))} KB")
    return "\n".join(out)


# --- sending -------------------------------------------------------------------------------------------------

class Sender(QObject):
    """POSTs a report. Answer: {"id": "BR-42", "seen": 3}. No answer: saved, sent again at the next start."""
    done = Signal(dict)       # the server's answer
    failed = Signal(str)      # why, in plain words
    BUSY = (429, 502, 503, 504, 507)
    MAX_PENDING = 10

    def __init__(self, win, url: str = "") -> None:
        super().__init__(win)
        self.win = win
        self.url = url or REPORT_URL
        self.net = QNetworkAccessManager(self)
        self.pending_dir = win.cfg_dir / "reports" / "pending"

    def send(self, report: dict, keep_on_fail: bool = True) -> QNetworkReply:
        req = QNetworkRequest(QUrl(self.url))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, f"BChat/{report.get('bchat', '?')}")
        req.setTransferTimeout(20000)
        reply = self.net.post(req, json.dumps(report).encode())
        reply.finished.connect(lambda: self._finished(reply, report, keep_on_fail))
        return reply

    def _finished(self, reply: QNetworkReply, report: dict, keep: bool) -> None:
        reply.deleteLater()
        body = bytes(reply.readAll())
        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                ans = json.loads(body.decode())
                if isinstance(ans, dict) and re.fullmatch(r"BR-\d{1,9}", str(ans.get("id", ""))):
                    self._remember(ans, report)
                    self.done.emit(ans)
                    return
            except ValueError:
                pass
            why = "The report server gave an answer BChat doesn't understand."
        else:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status in self.BUSY:          # busy or flooded by others: the report is fine, try again later
                why = "The report server is busy right now."
            elif status:
                why = "The report server didn't accept this report."
            else:
                why = "BChat couldn't reach the report server."
            if keep and (not status or status in self.BUSY):
                self.keep(report)
                why += " It's saved, and BChat sends it the next time it starts."
        self.failed.emit(why)

    def _remember(self, ans: dict, report: dict) -> None:
        mine = self.win.cfg.my_reports
        mine.append({"id": ans["id"], "sig": report.get("sig", ""), "kind": report.get("kind", ""),
                     "date": time.strftime("%Y-%m-%d")})
        del mine[:-50]
        try:
            self.win.save_config()
        except Exception:
            pass

    def keep(self, report: dict) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        waiting = sorted(self.pending_dir.glob("*.json"))
        for old in waiting[:max(0, len(waiting) - (self.MAX_PENDING - 1))]:   # never a pile: the oldest go
            try:
                old.unlink()
            except OSError:
                pass
        (self.pending_dir / f"{int(time.time() * 1000)}.json").write_text(json.dumps(report), encoding="utf-8")

    def send_pending(self) -> int:
        """Reports the user already said yes to, saved while offline."""
        n = 0
        for f in sorted(self.pending_dir.glob("*.json"))[:5] if self.pending_dir.is_dir() else []:
            try:
                report = json.loads(f.read_text(encoding="utf-8"))
                f.unlink()
            except (OSError, ValueError):
                continue
            self.send(report, keep_on_fail=True)
            n += 1
        return n


def fixed_for_me(entry: dict, my_reports: list) -> list[str]:
    """The update's "fixes" list (report ids) that are this user's own reports."""
    mine = {r.get("id") for r in my_reports or []}
    return [x for x in entry.get("fixes") or [] if isinstance(x, str) and x in mine]
