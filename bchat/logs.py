"""Chat logs on disk (0.3.0): daily or monthly files, reading them back for the Logs window, search, clean-up.

Layout: logs/<Network>/<#channel>/2026-11-09.log (every day) or logs/<Network>/<#channel>/2026-11.log (every month).
'Never' keeps XChat's one file per tab from the Log filename mask. Anything else in the logs folder is an older
log: the window shows it under 'Older logs' and the clean-up never touches it."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

SPLITS = ("day", "month", "none")           # Preferences order: Every day, Every month, Never (one file)
KEEP_DAYS = (0, 31, 183, 366)               # Delete logs older than: Never, 1 month, 6 months, 1 year
DATED = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?\.log$")
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
OLDER = "Older logs"


def dated_name(split: str, ts: float) -> str:
    return time.strftime("%Y-%m.log" if split == "month" else "%Y-%m-%d.log", time.localtime(ts))


@dataclass
class LogFile:
    path: Path
    network: str
    channel: str
    year: int = 0
    month: int = 0
    day: int = 0            # 0 for a monthly file

    @property
    def dated(self) -> bool:
        return self.year > 0

    def sort_key(self):
        return (self.year, self.month, self.day, self.path.name)

    def label(self, now: float | None = None) -> str:
        if not self.dated:
            return self.path.name
        if not self.day:
            return time.strftime("%B %Y", (self.year, self.month, 1, 0, 0, 0, 0, 1, -1))
        st = time.localtime(time.mktime((self.year, self.month, self.day, 12, 0, 0, 0, 0, -1)))
        today = time.localtime(now if now is not None else time.time())
        if st[:3] == today[:3]:
            return "Today"
        y = time.localtime(time.mktime((today.tm_year, today.tm_mon, today.tm_mday - 1, 12, 0, 0, 0, 0, -1)))
        if st[:3] == y[:3]:
            return "Yesterday"
        text = time.strftime("%a ", st) + str(st.tm_mday) + time.strftime(" %b", st)
        return text if st.tm_year == today.tm_year else f"{text} {st.tm_year}"

    def last_moment(self) -> float:
        """The end of the day or month the file covers."""
        if not self.day:
            return time.mktime((self.year, self.month + 1, 1, 0, 0, 0, 0, 0, -1))
        return time.mktime((self.year, self.month, self.day + 1, 0, 0, 0, 0, 0, -1))


def scan(root: Path) -> list[LogFile]:
    """Every log under the folder, dated ones as Network/channel/date, the rest as older logs."""
    out: list[LogFile] = []
    if not root.is_dir():
        return out
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".log", ".txt"):
            continue
        rel = path.relative_to(root).parts
        m = DATED.match(path.name)
        if m and len(rel) == 3:
            out.append(LogFile(path, rel[0], rel[1], int(m[1]), int(m[2]), int(m[3] or 0)))
        else:
            out.append(LogFile(path, OLDER, str(Path(*rel[:-1])) if len(rel) > 1 else "", ))
    out.sort(key=lambda f: (f.network.lower() if f.network != OLDER else "￿", f.channel.lower(), f.sort_key()))
    return out


def clean_up(root: Path, keep_days: int, now: float | None = None) -> int:
    """Deletes dated files that ended more than keep_days ago (0 = keep all). Older logs are never touched."""
    if keep_days <= 0:
        return 0
    limit = (now if now is not None else time.time()) - keep_days * 86400
    gone = 0
    for f in scan(root):
        if f.dated and f.last_moment() < limit:
            try:
                f.path.unlink()
                gone += 1
            except OSError:
                continue
            for folder in (f.path.parent, f.path.parent.parent):
                try:
                    folder.rmdir()          # only when empty
                except OSError:
                    break
    return gone


def parse_line(raw: str, stamp_format: str, f: LogFile | None = None) -> tuple[float, str, str]:
    """(time, left, text) from a written line: '<stamp><left>\\t<text>'. The day comes from the file name, the
    time (and the day for monthly files) from the stamp when it can be read back."""
    raw = raw.rstrip("\r\n")
    prefix, sep, text = raw.partition("\t")
    if not sep:
        prefix, text = "", raw
    m = _TIME.search(prefix)
    if m:
        cut = prefix.rfind(" ")
        left = prefix[cut + 1:] if cut >= m.end() - 1 else ""
        stamp = prefix[:len(prefix) - len(left)]
    else:
        left, stamp = prefix, ""
    if f is not None and f.dated:
        y, mo, d = f.year, f.month, f.day or 1
    else:
        lt = time.localtime(f.path.stat().st_mtime) if f is not None and f.path.exists() else time.localtime()
        y, mo, d = lt.tm_year, lt.tm_mon, lt.tm_mday
    h = mi = s = 0
    if stamp:
        try:
            st = time.strptime(stamp.strip(), stamp_format.strip())
            if re.search(r"%[bBmh]", stamp_format) and not (f is not None and f.day):
                mo = st.tm_mon
            if "%d" in stamp_format and not (f is not None and f.day):
                d = st.tm_mday
            if "%Y" in stamp_format:
                y = st.tm_year
            h, mi, s = st.tm_hour, st.tm_min, st.tm_sec
        except ValueError:
            h, mi, s = int(m[1]), int(m[2]), int(m[3] or 0)
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1)), left, text


def count(text: str, word: str) -> int:
    return text.lower().count(word.lower()) if word else 0


class TextCache:
    """File contents kept while the size and time stay the same, so search can run on every key press."""

    def __init__(self):
        self._data: dict[Path, tuple[tuple[int, float], str]] = {}

    def read(self, path: Path) -> str:
        try:
            st = path.stat()
        except OSError:
            return ""
        key = (st.st_size, st.st_mtime)
        hit = self._data.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        self._data[path] = (key, text)
        return text
