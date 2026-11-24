"""0.8.8 commands: /userhost, /flush, /linesep and /font. 0.8.10: /creq, /sreq, /updatenl, /queryrn.

commands.run() hands these over by name, like everyday.py; each one prints one short line that says what happened."""
from __future__ import annotations

from PySide6.QtGui import QFontDatabase

from . import tabopts
from .chatview import LINESEP
from .session import CHANNEL, ERROR, INFO, QUERY, Buffer, Session

NAMES = ("userhost", "flush", "linesep", "font", "creq", "sreq", "updatenl", "queryrn")
LOCAL = ("flush", "linesep", "font", "creq", "sreq")          # work without a server

# Settings > File transfers: what /creq and /sreq set (the same values as the menus)
OFFER_WORDS = {"ask": 0, "auto": 1, "trusted": 2, "ignore": 3}
OFFER_SHOWN = {0: "Ask me", 1: "Accept from everyone", 2: "Accept from trusted people", 3: "Ignore them"}

HELP = {
    "userhost": "USERHOST <nick> [<nick>...]: shows the address of up to 5 nicks, and whether they're away",
    "flush": "FLUSH: drops the lines still waiting to be sent (flood protection holds them back)",
    "linesep": "LINESEP: draws a dim line across this window, to mark a spot",
    "font": "FONT [<size>] [<family>]: a font for this window only. /font -d: back to the chat font. "
            "Alone: shows the font",
    "creq": "CREQ ask|auto|trusted|ignore: what happens to direct chat offers (auto = accept from everyone). "
            "Alone: shows it",
    "sreq": "SREQ ask|auto|trusted|ignore: what happens to file offers (auto = accept from everyone). Alone: shows it",
    "updatenl": "UPDATENL: asks the server for this channel's names again and rebuilds the nick list",
    "queryrn": "QUERYRN <nick> <newnick>: renames a private tab, for when a nick change wasn't seen",
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
    if cmd in ("creq", "sreq"):
        field_, what = ("dcc_chat_auto", "Direct chat offers") if cmd == "creq" else ("dcc_auto", "File offers")
        if not args:
            _info(s, b, f"{what}: {OFFER_SHOWN.get(getattr(cfg, field_), 'Ask me')}.")
        elif args[0].lower() not in OFFER_WORDS:
            _err(s, b, "Use: " + HELP[cmd].split(":")[0].lower().replace(cmd, "/" + cmd, 1))
        else:
            setattr(cfg, field_, OFFER_WORDS[args[0].lower()])
            ui.save_config()
            _info(s, b, f"{what}: {OFFER_SHOWN[getattr(cfg, field_)]}. (Settings > File transfers > Options)")
    elif cmd == "updatenl":
        chan = args[0] if args else (b.name if b.kind == CHANNEL else "")
        if not chan:
            _err(s, b, "/updatenl needs a channel tab.")
        elif s.state != "connected":
            _err(s, b, "Not connected. Use Server > Reconnect.")
        else:
            s.rebuild_nicklist(chan)
    elif cmd == "queryrn":
        if len(args) != 2:
            _err(s, b, "Use: /queryrn <nick> <newnick>")
            return
        found = s.buffers.get(s.fold(args[0]))
        if found is None or found.kind != QUERY:
            _err(s, b, f"No private tab called {args[0]}.")
        elif s.fold(args[1]) in s.buffers and s.fold(args[1]) != s.fold(args[0]):
            _err(s, b, f"There is already a tab called {args[1]}.")
        else:
            old = found.name
            s.buffers.pop(s.fold(old), None)
            found.name = args[1]
            s.buffers[s.fold(args[1])] = found
            s.buffer_changed.emit(found)
            _info(s, found, f"Private tab {old} is now {args[1]}.")
    elif cmd == "userhost":
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
