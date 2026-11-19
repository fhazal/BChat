"""0.8.8 commands: /userhost, /flush, /linesep and /font.

commands.run() hands these over by name, like everyday.py; each one prints one short line that says what happened."""
from __future__ import annotations

from PySide6.QtGui import QFontDatabase

from . import tabopts
from .chatview import LINESEP
from .session import ERROR, INFO, Buffer, Session

NAMES = ("userhost", "flush", "linesep", "font")
LOCAL = ("flush", "linesep", "font")          # work without a server

HELP = {
    "userhost": "USERHOST <nick> [<nick>...]: shows the address of up to 5 nicks, and whether they're away",
    "flush": "FLUSH: drops the lines still waiting to be sent (flood protection holds them back)",
    "linesep": "LINESEP: draws a dim line across this window, to mark a spot",
    "font": "FONT [<size>] [<family>]: a font for this window only. /font -d: back to the chat font. "
            "Alone: shows the font",
}

USERHOST_MAX = 5
SIZES = (4, 72)


def _err(s, b, text):
    s.add(b, ERROR, "*", text)


def _info(s, b, text):
    s.add(b, INFO, "*", text)


def _family(name: str) -> str:
    """The installed family spelled the way Qt knows it, or '' when there is none by that name."""
    want = name.strip().lower()
    return next((f for f in QFontDatabase.families() if f.lower() == want), "")


def _spec(cfg, b) -> tuple[str, str]:
    """(family, size) this window set with /font; '' = follows the chat font."""
    family, _, size = str(tabopts.get(cfg, b, "font") or "").partition("|")
    return family, size


def _describe(cfg, b) -> str:
    family, size = _spec(cfg, b)
    return f"{family or cfg.chat_font} {size or cfg.chat_font_size} pt"


def _refresh(ui, b) -> None:
    """Build the window again in its new font: the main window's view, and its own window when detached."""
    ui.reload_buffer(b)
    w = getattr(ui, "detached", {}).get(id(b))
    if w is not None and getattr(w, "chat", None) is not None:
        w.chat.reload(b)


def run(ui, s: Session, b: Buffer, cmd: str, args: list[str], rest: str) -> None:
    cfg = ui.cfg
    if cmd == "userhost":
        if not args:
            _err(s, b, HELP["userhost"])
        elif s.state != "connected":
            _err(s, b, "Not connected. Use Server > Reconnect.")
        else:
            if len(args) > USERHOST_MAX:
                _info(s, b, f"Servers answer for {USERHOST_MAX} nicks at a time, so only the first {USERHOST_MAX} were asked about.")
            s.userhost_typed(b, args[:USERHOST_MAX])
    elif cmd == "flush":
        n = s.flush_queue()
        if n:
            _info(s, b, f"Dropped {n} line{'' if n == 1 else 's'} that {'was' if n == 1 else 'were'} waiting to be sent.")
        else:
            _info(s, b, "Nothing waiting to be sent.")
    elif cmd == "linesep":
        s.add(b, LINESEP, "", "─" * 40)
    elif cmd == "font":
        if getattr(b, "session", None) is None:
            _err(s, b, "Only server, channel and private windows can have their own font.")
        elif not args:
            own = tabopts.has_own(cfg, b, "font")
            _info(s, b, f"{b.name} uses {_describe(cfg, b)}"
                        + (" (its own). /font -d goes back to the chat font." if own else " (the chat font)."))
        elif args[0].lower() in ("-d", "-default"):
            tabopts.set_(cfg, b, "font", "")
            ui.save_config()
            _refresh(ui, b)
            _info(s, b, f"{b.name} uses the chat font again ({_describe(cfg, b)}).")
        else:
            family, size = _spec(cfg, b)
            words = list(args)
            if words[0].isdigit():
                n = int(words.pop(0))
                if not SIZES[0] <= n <= SIZES[1]:
                    _err(s, b, f"Font size must be {SIZES[0]}–{SIZES[1]}.")
                    return
                size = str(n)
            if words:
                name = " ".join(words)
                found = _family(name)
                if not found:
                    _err(s, b, f"No font named \"{name}\" on this PC. Example: /font 12 Consolas")
                    return
                family = found
            spec = f"{family}|{size}"
            tabopts.set_(cfg, b, "font", "" if spec == "|" else spec)
            ui.save_config()
            _refresh(ui, b)
            _info(s, b, f"{b.name} uses {_describe(cfg, b)} now.")
