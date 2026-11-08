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
    fg: int | str | None = None     # mIRC colour number 0-98, or "#rrggbb" from a hex code (\x04)
    bg: int | str | None = None
    bold: bool = False
    underline: bool = False
    italic: bool = False
    reverse: bool = False
    strike: bool = False            # \x1e
    mono: bool = False              # \x11


_COLOR = re.compile(r"(\d{1,2})(?:,(\d{1,2}))?")
_HEX = re.compile(r"([0-9A-Fa-f]{6})(?:,([0-9A-Fa-f]{6}))?")

# Colours 16-98 are the same fixed colours in every client (modern.ircdocs.horse/formatting); only 0-15 follow the theme.
EXTENDED = (
    "470000 472100 474700 324700 004700 00472c 004747 002747 000047 2e0047 470047 47002a "
    "740000 743a00 747400 517400 007400 007449 007474 004074 000074 4b0074 740074 740045 "
    "b50000 b56300 b5b500 7db500 00b500 00b571 00b5b5 0063b5 0000b5 7500b5 b500b5 b5006b "
    "ff0000 ff8c00 ffff00 b2ff00 00ff00 00ffa0 00ffff 008cff 0000ff a500ff ff00ff ff0098 "
    "ff5959 ffb459 ffff71 cfff60 6fff6f 65ffc9 6dffff 59b4ff 5959ff c459ff ff66ff ff59bc "
    "ff9c9c ffd39c ffff9c e2ff9c 9cff9c 9cffdb 9cffff 9cd3ff 9c9cff dc9cff ff9cff ff94d3 "
    "000000 131313 282828 363636 4d4d4d 656565 818181 9f9f9f bcbcbc e2e2e2 ffffff").split()


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two "#rrggbb" colours, 1 to 21."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def readable(fg: str, bg: str, need: float = 3.0) -> str:
    """fg, or the nearest shade of the same hue that reads on bg: lighter on a dark background, darker on a light
    one, in small steps, stopping as soon as it reaches the contrast needed. Colours that already read are returned
    unchanged, so most messages look exactly as sent."""
    if contrast(fg, bg) >= need:
        return fg
    import colorsys
    h = fg.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    up = _luminance(bg) < 0.18                       # dark background: go lighter
    best = fg
    for step in range(1, 41):
        l2 = min(1.0, light + step * 0.025) if up else max(0.0, light - step * 0.025)
        rr, gg, bb = colorsys.hls_to_rgb(hue, l2, sat)
        best = "#%02x%02x%02x" % (round(rr * 255), round(gg * 255), round(bb * 255))
        if contrast(best, bg) >= need:
            return best
    return best


def colour_of(c: "int | str | None", palette: list) -> "str | None":
    """The colour to draw: 0-15 from the theme's palette, 16-98 fixed, "#rrggbb" as sent, 99 or None = default."""
    if c is None:
        return None
    if isinstance(c, str):
        return c
    if 0 <= c <= 15:
        return palette[c]
    if 16 <= c <= 98:
        return "#" + EXTENDED[c - 16]
    return None


def parse_format(text: str) -> list[Span]:
    spans: list[Span] = []
    cur = Span("")
    buf: list[str] = []

    def flush():
        nonlocal cur
        if buf:
            spans.append(Span("".join(buf), cur.fg, cur.bg, cur.bold, cur.underline, cur.italic, cur.reverse,
                              cur.strike, cur.mono))
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
        elif c == "\x04":                     # hex colour: \x04RRGGBB[,RRGGBB]; a bare \x04 turns colours off
            flush()
            m = _HEX.match(text, i + 1)
            if m:
                cur.fg = "#" + m.group(1).lower()
                if m.group(2) is not None:
                    cur.bg = "#" + m.group(2).lower()
                i = m.end() - 1
            else:
                cur.fg = cur.bg = None
        elif c == "\x1e":
            flush(); cur.strike = not cur.strike
        elif c == "\x11":
            flush(); cur.mono = not cur.mono
        elif c == "\x07":
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
