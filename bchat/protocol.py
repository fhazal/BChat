"""IRC line parsing and mIRC formatting. No Qt here, so it is easy to test."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Message:
    command: str
    params: list[str] = field(default_factory=list)
    prefix: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def nick(self) -> str:
        return self.prefix.split("!", 1)[0]

    @property
    def userhost(self) -> str:
        return self.prefix.split("!", 1)[1] if "!" in self.prefix else ""

    def param(self, i: int, default: str = "") -> str:
        return self.params[i] if 0 <= i < len(self.params) or -len(self.params) <= i < 0 else default


_TAG_ESC = {":": ";", "s": " ", "\\": "\\", "r": "\r", "n": "\n"}


def _unescape_tag(v: str) -> str:
    return re.sub(r"\\(.?)", lambda m: _TAG_ESC.get(m.group(1), m.group(1)), v)


def parse_line(line: str) -> Message:
    line = line.rstrip("\r\n")
    tags: dict[str, str] = {}
    if line.startswith("@"):
        raw, _, line = line.partition(" ")
        for item in raw[1:].split(";"):
            k, _, v = item.partition("=")
            tags[k] = _unescape_tag(v)
        line = line.lstrip(" ")
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
        line = line.lstrip(" ")
    head, sep, trailing = line.partition(" :")
    parts = head.split()
    if line.startswith(":"):
        parts, trailing, sep = [], line[1:], " :"
    if not parts:
        return Message("", [], prefix, tags)
    params = parts[1:]
    if sep:
        params.append(trailing)
    return Message(parts[0].upper(), params, prefix, tags)


def build_line(command: str, *params: str) -> str:
    if not params:
        return command
    head, last = list(params[:-1]), params[-1]
    if last == "" or " " in last or last.startswith(":"):
        last = ":" + last
    return " ".join([command, *head, last])


def lower(s: str) -> str:
    """rfc1459 case folding, used for all nick and channel lookups."""
    return s.lower().replace("[", "{").replace("]", "}").replace("\\", "|").replace("~", "^")


# --- mIRC formatting ---------------------------------------------------------

@dataclass
class Span:
    text: str
    fg: int | None = None
    bg: int | None = None
    bold: bool = False
    underline: bool = False
    italic: bool = False
    reverse: bool = False


_COLOR = re.compile(r"(\d{1,2})(?:,(\d{1,2}))?")


def parse_format(text: str) -> list[Span]:
    spans: list[Span] = []
    cur = Span("")
    buf: list[str] = []

    def flush():
        nonlocal cur
        if buf:
            spans.append(Span("".join(buf), cur.fg, cur.bg, cur.bold, cur.underline, cur.italic, cur.reverse))
            buf.clear()

    i = 0
    while i < len(text):
        c = text[i]
        if c == "\x02":
            flush(); cur.bold = not cur.bold
        elif c == "\x1f":
            flush(); cur.underline = not cur.underline
        elif c == "\x1d":
            flush(); cur.italic = not cur.italic
        elif c == "\x16":
            flush(); cur.reverse = not cur.reverse
        elif c == "\x0f":
            flush(); cur = Span("")
        elif c == "\x03":
            flush()
            m = _COLOR.match(text, i + 1)
            if m:
                cur.fg = int(m.group(1))
                if m.group(2) is not None:
                    cur.bg = int(m.group(2))
                i = m.end() - 1
            else:
                cur.fg = cur.bg = None
        elif c in "\x07\x11\x1e":
            pass
        else:
            buf.append(c)
        i += 1
    flush()
    return spans


def strip_format(text: str) -> str:
    return "".join(s.text for s in parse_format(text))


URL_RE = re.compile(r"\b(?:https?://|ftp://|www\.)[^\s<>\"'\x00-\x1f]+", re.I)


def split_urls(text: str) -> list[tuple[str, bool]]:
    """Split plain text into (piece, is_url), leaving closing punctuation out of the link."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:!?)]}")
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((url, True))
        pos = m.start() + len(url)
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def mask_ban(nick: str, userhost: str, kind: int) -> str:
    """XChat's four ban types: 0 *!*@*.host, 1 *!*@domain, 2 *!*user@*.host, 3 *!*user@domain."""
    user, _, host = userhost.partition("@")
    if not host:
        return f"{nick}!*@*"
    user = user.lstrip("~")
    is_ip = bool(re.fullmatch(r"[\d.]+", host))
    pieces = host.split(".")
    if is_ip and len(pieces) == 4:
        wild = ".".join(pieces[:3]) + ".*"
    elif len(pieces) > 2:
        wild = "*." + ".".join(pieces[1:])
    else:
        wild = host
    return {
        0: f"*!*@{wild}",
        1: f"*!*@{host}",
        2: f"*!*{user}@{wild}",
        3: f"*!*{user}@{host}",
    }.get(kind, f"*!*@{wild}")
