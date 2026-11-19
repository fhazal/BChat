"""0.7.0 Everyday commands: the ones mIRC users type every day that BChat didn't have yet.

commands.run() hands these over by name; each one prints one short line that says what happened."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QTimer

from . import filetypes, tabopts
from .protocol import lower, strip_format
from .session import ACTION, CHANNEL, ERROR, HILITE, INFO, MSG, QUERY, SELF, Buffer, Session

NAMES = ("describe", "omsg", "qmsg", "qme", "ctcpreply", "tnick", "mnick", "fullname", "autojoin", "perform",
         "clearall", "markasread", "savebuf", "loadbuf", "strip", "timestamp", "log", "titlebar", "dns", "links", "uwho",
         "aop", "avoice", "abook", "cnick", "beep", "flash", "splay", "donotdisturb", "play", "run",
         "speak")

HELP = {
    "describe": "DESCRIBE <nick or #channel> <action>: an action (/me) to someone else's tab, without switching to it",
    "omsg": "OMSG [#channel] <text>: a message only the ops of the channel see (when the server can)",
    "qmsg": "QMSG <text>: says it in every open private chat on this network",
    "qme": "QME <action>: an action in every open private chat on this network",
    "ctcpreply": "CTCPREPLY <nick> <what> [<text>]: answers a CTCP by hand",
    "tnick": "TNICK <nick>: changes your nick for now; the saved nick stays",
    "mnick": "MNICK <nick>: changes your saved nick, and your nick now when connected",
    "fullname": "FULLNAME <name>: changes your saved real name (used the next time you connect)",
    "autojoin": "AUTOJOIN [-r] [#channel [key]]: adds a channel to this network's join list, or takes it off with -r. "
                "Alone: lists them",
    "perform": "PERFORM [-r] [<command>]: adds a command this network runs after connecting, or takes it off with -r "
               "(the text or its number). Alone: lists them",
    "clearall": "CLEARALL [-a]: clears every tab on this network, or on all networks with -a",
    "markasread": "MARKASREAD [-a]: takes the unread colour off this tab, or off every tab with -a",
    "savebuf": "SAVEBUF [<file>]: saves this tab's text to a file (Documents\\BChat when no folder is given)",
    "loadbuf": "LOADBUF <file>: shows a text file in this tab. Nothing is sent",
    "strip": "STRIP [on|off]: strips colours and bold in this tab (on), or shows them (off). Alone: says which",
    "timestamp": "TIMESTAMP [on|off]: timestamps in this tab. Alone: says which",
    "log": "LOG [on|off]: saves this tab to disk (the tab menu's Log to Disk). Alone: says which",
    "titlebar": "TITLEBAR [<text>]: adds text to the window title. Alone: back to normal",
    "dns": "DNS <nick or host>: looks up an address (or the name of an IP)",
    "links": "LINKS: lists the servers of this network",
    "uwho": "UWHO <nick>: shows the person's info card and asks the server who they are",
    "aop": "AOP [-r] <nick or mask> [#channel]: adds someone to Auto-Op & Protect, or takes them off with -r. Alone: "
           "opens the list",
    "avoice": "AVOICE [-r] <nick or mask> [#channel]: the same for Auto-Voice",
    "abook": "ABOOK [<nick>]: opens the Address Book (at that person's card)",
    "cnick": "CNICK <nick> [<colour>|-r]: gives a nick its own colour, or takes it off with -r. Alone with a nick: "
             "lists the colours",
    "beep": "BEEP [<times>]: beeps",
    "flash": "FLASH: flashes BChat's taskbar button",
    "splay": "SPLAY <file.wav, .mp3 or .ogg> | STOP: plays a sound, only on this PC",
    "speak": "SPEAK <text> | OFF: reads the text aloud, only on this PC. SPEAK OFF stops reading now",
    "donotdisturb": "DONOTDISTURB [on|off]: no sounds, flashes or pop-up cards until it is off again. Alone: says which",
    "play": "PLAY [-e] [#channel or nick] <file.txt> [<ms between lines>]: sends a text file line by line. "
            "-e shows it only to you. PLAY STOP stops",
    "run": "RUN <file, folder or link>: opens it with its Windows program. Asks first before starting a program",
}

# these work without a server (a tab made with /newserver -noconnect, or before the first connect)
LOCAL = ("clearall", "markasread", "savebuf", "loadbuf", "strip", "timestamp", "log", "titlebar", "abook", "cnick",
         "beep", "flash", "splay", "donotdisturb", "run", "aop", "avoice", "speak")

ON = ("on", "yes", "1", "true")
OFF = ("off", "no", "0", "false")
PAUSE_MS = {"careful": 3000, "normal": 2000, "fast": 1000}   # /play: a line every 2 s by default (Flood > pace)
PLAY_MAX = 2000              # lines one /play sends at most
LOAD_MAX = 5000              # lines /loadbuf shows at most


def _err(s, b, text):
    s.add(b, ERROR, "*", text)


def _info(s, b, text):
    s.add(b, INFO, "*", text)


def _switch(word: str):
    w = word.lower()
    return True if w in ON else False if w in OFF else None


def _tail(rest: str, n: int) -> str:
    """The text after the first n words, as typed (spaces kept)."""
    parts = rest.split(None, n)
    return parts[n] if len(parts) > n else ""


def _saved(ui, s) -> bool:
    return s.net in ui.cfg.networks


def find_user(s: Session, nick: str):
    """The person's User from any channel tab on this network (the one with the most known about them)."""
    best = None
    for x in s.buffers.values():
        if x.kind == CHANNEL:
            u = x.users.get(s.fold(nick))
            if u is not None and (best is None or (u.host and not best.host) or (u.account and not best.account)):
                best = u
    return best


def documents() -> Path:
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
    return Path(base) / "BChat"


def _file(word: str) -> Path:
    p = Path(word.strip('"')).expanduser()
    return p if p.is_absolute() else documents() / p


# --- autojoin: the Network List's "#a,#b keyA,keyB" field ---------------------------------------------------

def parse_autojoin(text: str) -> list[tuple[str, str]]:
    chans, _, keys = text.strip().partition(" ")
    names = [c for c in chans.split(",") if c]
    ks = keys.strip().split(",") if keys.strip() else []
    return [(c, ks[i] if i < len(ks) else "") for i, c in enumerate(names)]


def build_autojoin(rows: list[tuple[str, str]]) -> str:
    keyed = [k for _c, k in rows]
    while keyed and not keyed[-1]:
        keyed.pop()
    out = ",".join(c for c, _k in rows)
    if keyed:
        # keys line up with the first channels, so channels with a key go first
        rows = sorted(rows, key=lambda r: not r[1])
        out = ",".join(c for c, _k in rows) + " " + ",".join(k for _c, k in rows if k)
    return out


# --- /play: a text file line by line, at the Flood pace ----------------------------------------------------

class Player:
    def __init__(self, s: Session, b: Buffer, target: str, lines: list[str], pause_ms: int, only_me: bool, name: str):
        self.s, self.b, self.target, self.lines, self.only_me, self.name = s, b, target, lines, only_me, name
        self.sent = 0
        self.timer = QTimer(s)
        self.timer.setInterval(pause_ms)
        self.timer.timeout.connect(self.step)

    def start(self) -> None:
        self.step()
        if self.lines:
            self.timer.start()

    def step(self) -> None:
        s = self.s
        if not self.only_me and s.state != "connected":
            self.stop("stopped: not connected")
            return
        if not self.lines:
            self.stop("done")
            return
        line = self.lines.pop(0)
        if self.only_me:
            s.add(s.buffer(self.target) if self.target else self.b, INFO, "*", line)
        else:
            s.say(self.target, line)
        self.sent += 1
        if not self.lines:
            self.stop("done")

    def stop(self, why: str) -> None:
        self.timer.stop()
        if getattr(self.s, "player", None) is self:
            self.s.player = None
            _info(self.s, self.b, f"Play {self.name}: {why} ({self.sent} line{'' if self.sent == 1 else 's'}).")


def _play(ui, s, b, args, rest) -> None:
    if args and args[0].lower() == "stop":
        p = getattr(s, "player", None)
        if p is None:
            _info(s, b, "Nothing is playing.")
        else:
            p.stop("stopped")
        return
    from PySide6.QtCore import QProcess
    words = QProcess.splitCommand(rest)
    only_me = bool(words) and words[0].lower() == "-e"
    if only_me:
        words = words[1:]
    pause = 0
    if len(words) >= 2 and words[-1].isdigit():
        pause = int(words.pop())
    target = ""
    if len(words) >= 2:
        target = words.pop(0)
    if len(words) != 1:
        _err(s, b, HELP["play"])
        return
    if not target:
        if b.kind not in (CHANNEL, QUERY) and not only_me:
            _err(s, b, "/play needs a channel or private tab, or a #channel or nick before the file.")
            return
        target = b.name if b.kind in (CHANNEL, QUERY) else ""
    path = _file(words[0])
    if not path.is_file():
        _err(s, b, f"No such file: {path}")
        return
    if getattr(s, "player", None) is not None:
        _err(s, b, f"Already playing {s.player.name}. /play stop stops it.")
        return
    try:
        text = path.read_text("utf-8", errors="replace")
    except OSError as e:
        _err(s, b, f"Couldn't read {path}: {e.strerror or e}")
        return
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        _info(s, b, f"{path.name} is empty.")
        return
    cut = len(lines) > PLAY_MAX
    lines = lines[:PLAY_MAX]
    pause = max(pause or PAUSE_MS.get(s.cfg.flood_pace, 2000), 500)   # never faster than 2 lines a second
    to = "you only" if only_me else target
    _info(s, b, f"Playing {path.name} to {to}: {len(lines)} lines, one every {pause / 1000:g} s"
                + (f" (first {PLAY_MAX} only)" if cut else "") + ". /play stop stops.")
    s.player = Player(s, b, target, lines, pause, only_me, path.name)
    s.player.start()


# --- /run ---------------------------------------------------------------------------------------------------

def confirm_program(ui, path: Path) -> bool:
    """A program asks first, once per file (like a DCC file that is a program). Tests replace this."""
    from PySide6.QtWidgets import QMessageBox
    answer = QMessageBox.question(ui, "Run a program?",
                                  f"{path.name} is a program. Start it?\n\n{path}\n\nBChat won't ask again for this file.",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def open_path(path: Path) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _run(ui, s, b, rest) -> None:
    what = rest.strip().strip('"')
    if not what:
        _err(s, b, HELP["run"])
        return
    if "://" in what or what.lower().startswith("www."):
        ui.open_url(what if "://" in what else "https://" + what)
        return
    path = _file(what)                           # no folder given: Documents\BChat, like /play and /savebuf
    if not path.exists():
        _err(s, b, f"No such file or folder: {path}")
        return
    path = path.resolve()
    if path.is_file() and filetypes.is_program(path.name):
        known = [lower(p) for p in ui.cfg.run_allowed]
        if lower(str(path)) not in known:
            if not confirm_program(ui, path):
                _info(s, b, f"Not started: {path.name}")
                return
            ui.cfg.run_allowed.append(str(path))
            ui.save_config()
    if not open_path(path):
        _err(s, b, f"Windows couldn't open {path}")


# --- /dns -------------------------------------------------------------------------------------------------

def _resolve(s, b, host: str, who: str = "") -> None:
    from PySide6.QtNetwork import QHostAddress, QHostInfo
    label = f"{who} ({host})" if who else host
    _info(s, b, f"Looking up {label}...")
    is_ip = not QHostAddress(host).isNull()

    def done(info) -> None:
        if info.error() != QHostInfo.HostInfoError.NoError:
            _err(s, b, f"Couldn't look up {label}: {info.errorString()}")
        elif is_ip:
            name = info.hostName()
            _info(s, b, f"{label} is {name}" if name and name != host else f"{label} has no name.")
        else:
            ips = [a.toString() for a in info.addresses()]
            _info(s, b, f"{label} is {', '.join(ips)}" if ips else f"No address found for {label}.")
    QHostInfo.lookupHost(host, done)


def _dns(ui, s, b, args) -> None:
    if not args:
        _err(s, b, HELP["dns"])
        return
    word = args[0]
    u = find_user(s, word)
    if u is not None and u.host:
        _resolve(s, b, u.host.split("@")[-1], u.nick)
    elif "." in word or ":" in word:
        _resolve(s, b, word)
    elif s.state == "connected":
        s.dns_waiting[s.fold(word)] = (b, word)  # the USERHOST answer (302) brings the address
        s.send_raw(f"USERHOST {word}", quiet=True)
    else:
        _resolve(s, b, word)                     # not connected: it can only be a host name


def userhost_answer(s, m) -> bool:
    """302 for a /dns: nick*=+user@host. True when it was ours (then nothing else prints it). USERHOST answers
    nothing for someone who isn't on IRC: then the word is looked up as a host name (like 'localhost')."""
    items = m.param(-1).split()
    mine = False
    for item in items:
        nick, _, host = item.partition("=")
        waiting = s.dns_waiting.pop(s.fold(nick.rstrip("*")), None)
        if waiting is not None:
            mine = True
            _resolve(s, waiting[0], host.lstrip("+-").split("@")[-1], nick.rstrip("*"))
    if not items and s.dns_waiting:
        key = next(iter(s.dns_waiting))
        b, word = s.dns_waiting.pop(key)
        _info(s, b, f"{word} isn't on IRC now; looking it up as a host name.")
        _resolve(s, b, word)
        return True
    return mine


# --- Auto-Op / Auto-Voice ----------------------------------------------------------------------------------

def _control(ui, s, b, cmd, args) -> None:
    from . import control
    if not args:
        ui.open_control()
        return
    remove = args[0].lower() == "-r"
    args = args[1:] if remove else args
    if not args:
        _err(s, b, HELP[cmd])
        return
    give = "@" if cmd == "aop" else "+"
    word_of = "Auto-Op" if give == "@" else "Auto-Voice"
    word = args[0]
    chans = " ".join(a for a in args[1:] if s.is_channel(a))
    u = None if "!" in word or "@" in word else find_user(s, word)
    rules = ui.cfg.control_rules
    if remove:
        names = {lower(control.tidy_mask(word)), lower(word)}
        if u is not None:
            names |= {lower(u.account)} if u.account else set()
            names |= {lower(f"*!*@{u.host.split('@')[-1]}")} if u.host else set()
        same = [r for r in rules if r.get("give") == give and lower(r.get("who", "")) in names]
        if not same:
            _err(s, b, f"{word} isn't on the {word_of} list.")
            return
        for r in same:
            rules.remove(r)
        _info(s, b, f"{', '.join(r['who'] for r in same)} taken off the {word_of} list.")
    else:
        if u is None and ("!" in word or "@" in word):
            rule = {"who": control.tidy_mask(word), "by": "mask"}
            if control.nick_only(rule["who"]):
                _err(s, b, f"{word} only looks at the nick, and anyone can take a nick. Use an address: *!*@host")
                return
        elif u is not None and u.account:
            rule = {"who": u.account, "by": "account"}
        elif u is not None and u.host:
            rule = {"who": f"*!*@{u.host.split('@')[-1]}", "by": "mask"}
        else:
            _err(s, b, f"Can't see {word} in your channels, so BChat doesn't know their account or address. "
                       "Use a mask: *!*@host")
            return
        where = f"{chans or 'every channel'} on {s.net.name}"
        same = [r for r in rules if r.get("give") == give and lower(r.get("who", "")) == lower(rule["who"])]
        if same:
            same[0]["channels"], same[0]["network"] = chans, s.net.name
            _info(s, b, f"{rule['who']} was already on the {word_of} list; now for {where}.")
        else:
            rules.append({**rule, "give": give, "protect": False, "channels": chans, "network": s.net.name})
            _info(s, b, f"{word_of}: {rule['who']}{' (account)' if rule['by'] == 'account' else ''} in {where}. "
                        "Window > Auto-Op & Protect has the list.")
    ui.save_config()
    w = ui.tools.get("control")
    if w is not None and w.isVisible():
        w.fill()


# --- the rest ------------------------------------------------------------------------------------------------

def _on_off(ui, s, b, cmd, args, now: bool, label: str, set_) -> None:
    if not args:
        _info(s, b, f"{label}: {'on' if now else 'off'}.")
        return
    want = _switch(args[0])
    if want is None:
        _err(s, b, HELP[cmd])
        return
    set_(want)
    _info(s, b, f"{label}: {'on' if want else 'off'}.")


def _tab_only(s, b, cmd) -> bool:
    if b.kind not in (CHANNEL, QUERY) or b.name.startswith("="):
        _err(s, b, f"/{cmd} works in a channel or private tab.")
        return False
    return True


def _save_buffer(ui, s, b, rest) -> None:
    word = rest.strip().strip('"')
    if word:
        path = _file(word)
    else:
        name = ui._clean(b.name) if b.kind != "server" else ui._clean(s.net.name)
        path = documents() / f"{ui._clean(s.net.name)}-{name}-{time.strftime('%Y-%m-%d-%H%M')}.txt"
    stamp = ui.cfg.log_stamp_format or "%b %d %H:%M:%S "
    rows = []
    for ln in b.lines:
        if ln.hidden:
            continue
        left = strip_format(ln.left)
        who = f"<{left}>" if ln.kind in (MSG, SELF, HILITE) and left not in ("*", "") else left
        rows.append(f"{time.strftime(stamp, time.localtime(ln.ts))}{who} {strip_format(ln.text)}".rstrip())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(rows) + "\n", "utf-8")
    except OSError as e:
        _err(s, b, f"Couldn't save {path}: {e.strerror or e}")
        return
    _info(s, b, f"Saved {len(rows)} line{'' if len(rows) == 1 else 's'} to {path}")


def _load_buffer(ui, s, b, rest) -> None:
    word = rest.strip().strip('"')
    if not word:
        _err(s, b, HELP["loadbuf"])
        return
    path = _file(word)
    try:
        text = path.read_text("utf-8", errors="replace")
    except OSError as e:
        _err(s, b, f"Couldn't read {path}: {e.strerror or e}")
        return
    rows = text.splitlines()
    cut = len(rows) > LOAD_MAX
    _info(s, b, f"--- {path.name}" + (f" (last {LOAD_MAX} of {len(rows)} lines)" if cut else ""))
    for row in rows[-LOAD_MAX:]:
        s.add(b, INFO, "", row)
    _info(s, b, f"--- end of {path.name}")


def _cnick(ui, s, b, args) -> None:
    from . import people
    if not args:
        _err(s, b, HELP["cnick"])
        return
    nick = args[0]
    if len(args) == 1:
        now = people.colour_name(ui.cfg, s.net.name, nick)
        _info(s, b, f"{nick}: {now or 'no colour of their own'}. Colours: {', '.join(people.COLOURS)}")
        return
    word = args[1].lower()
    if word in ("-r", "none", "off"):
        before = len(ui.cfg.nick_colours)
        ui.cfg.nick_colours = [r for r in ui.cfg.nick_colours
                               if not (lower(r.get("mask", "")) == lower(nick) and not r.get("net"))]
        if len(ui.cfg.nick_colours) == before:
            _err(s, b, f"{nick} has no colour of their own.")
            return
        _info(s, b, f"{nick}: back to the normal colour.")
    elif word in people.COLOURS:
        people.set_rule(ui.cfg, nick, word, "")
        _info(s, b, f"{nick} is {word} now (Settings > Advanced > Nick Colours has the list).")
    else:
        _err(s, b, f"No colour called {args[1]}. Colours: {', '.join(people.COLOURS)}")
        return
    ui.nick_colours_changed()


def _beep(args) -> None:
    from PySide6.QtWidgets import QApplication
    n = min(int(args[0]), 10) if args and args[0].isdigit() else 1
    for i in range(max(n, 1)):
        QTimer.singleShot(i * 350, QApplication.beep)


def _splay(ui, s, b, rest) -> None:
    from . import sound
    word = rest.strip().strip('"')
    if word.lower() == "stop":
        sound.player().stop()
        return
    if not word:
        _err(s, b, HELP["splay"])
        return
    path = _file(word)
    if not path.is_file():
        _err(s, b, f"No such file: {path}")
        return
    if path.suffix.lower() not in sound.EXTENSIONS:
        _err(s, b, "/splay plays .wav, .mp3 and .ogg files.")
        return
    if not sound.play(str(path), ui.cfg.sound_volume):
        _err(s, b, f"Couldn't play {path.name}.")


def _speak(ui, s, b, rest) -> None:
    """0.8.8: /speak <text> reads it aloud (after anything already being read); /speak off stops now."""
    from . import speech
    text = rest.strip()
    if not text:
        _err(s, b, HELP["speak"])
        return
    talker = speech.speaker()
    if text.lower() in ("off", "stop"):
        talker.stop()
        return
    if not talker.available():
        _err(s, b, speech.UNAVAILABLE)
        return
    talker.say(text, ui.cfg.speak_voice, ui.cfg.speak_rate)


def _uwho(ui, s, b, args) -> None:
    if not args:
        _err(s, b, HELP["uwho"])
        return
    nick = args[0]
    if s.state == "connected":
        s.whois(nick)
    chan = b if b.kind == CHANNEL and s.fold(nick) in b.users else next(
        (x for x in s.buffers.values() if x.kind == CHANNEL and s.fold(nick) in x.users), None)
    if chan is None:
        return
    from PySide6.QtWidgets import QMenu
    from .widgets import add_menu_title
    menu = QMenu(ui)
    add_menu_title(menu, nick)
    ui._info_panel(menu, s, chan, chan.users[s.fold(nick)])
    menu.aboutToHide.connect(menu.deleteLater)
    ui.uwho_menu = menu                         # tests look at it
    from PySide6.QtCore import QPoint
    menu.popup(ui.input.mapToGlobal(QPoint(0, -menu.sizeHint().height())))   # just above the input box


def run(ui, s: Session, b: Buffer, cmd: str, args: list[str], rest: str) -> None:
    chan = b.name if b.kind == CHANNEL else ""
    cfg = ui.cfg
    if cmd == "describe":
        if len(args) < 2:
            _err(s, b, HELP["describe"])
        elif s.state != "connected":
            _err(s, b, "Not connected. Use Server > Reconnect.")
        else:
            target, text = args[0], _tail(rest, 1)
            tab = s.buffers.get(s.fold(target))
            s.send("PRIVMSG", target, f"\x01ACTION {text}\x01")
            if tab is not None:
                s.add(tab, ACTION, "*", f"{s.nick} {text}")
            if tab is not b:
                s.add(b, ACTION, f">{target}<", f"{s.nick} {text}")
    elif cmd == "omsg":
        target = args[0] if args and s.is_channel(args[0]) else chan
        text = _tail(rest, 1) if args and s.is_channel(args[0]) else rest
        if not target:
            _err(s, b, "/omsg needs a channel tab, or a #channel first.")
        elif not text:
            _err(s, b, HELP["omsg"])
        elif "@" not in s.statusmsg:
            _err(s, b, "This server can't send a message to the ops only.")
        elif s.state != "connected":
            _err(s, b, "Not connected. Use Server > Reconnect.")
        else:
            s.send("PRIVMSG", "@" + target, text)
            if "echo-message" not in s._cap_active:
                s.add(s.buffer(target), SELF, f"@{target}", text)
    elif cmd in ("qmsg", "qme"):
        chats = [x for x in s.buffers.values() if x.kind == QUERY and not x.name.startswith("=") and not x.placeholder]
        if not rest:
            _err(s, b, HELP[cmd])
        elif not chats:
            _info(s, b, f"No private chats open on {s.net.name}.")
        else:
            for x in chats:
                (s.say if cmd == "qmsg" else s.action)(x.name, rest)
            if b not in chats:
                _info(s, b, f"Sent to {len(chats)} private chat{'' if len(chats) == 1 else 's'}: "
                            + ", ".join(x.name for x in chats))
    elif cmd == "ctcpreply":
        if len(args) < 2:
            _err(s, b, HELP["ctcpreply"])
        else:
            body = " ".join([args[1].upper(), _tail(rest, 2)]).strip()
            s.send("NOTICE", args[0], f"\x01{body}\x01")
            _info(s, b, f"CTCP reply sent to {args[0]}: {body}")
    elif cmd == "tnick":
        if not args:
            _err(s, b, HELP["tnick"])
        else:
            s.send("NICK", args[0])
    elif cmd in ("mnick", "fullname"):
        value = args[0] if cmd == "mnick" else rest
        if not value:
            _err(s, b, HELP[cmd])
            return
        field_ = "nick" if cmd == "mnick" else "realname"
        own = not s.net.use_global and bool(getattr(s.net, field_)) and _saved(ui, s)
        setattr(s.net if own else cfg, field_, value)
        ui.save_config()
        where = f"for {s.net.name}" if own else "(Network List > User Information)"
        if cmd == "mnick":
            _info(s, b, f"Saved nick {where}: {value}")
            if s.state == "connected" and lower(value) != lower(s.nick):
                s.send("NICK", value)
        else:
            _info(s, b, f"Saved real name {where}: {value}. It is used the next time you connect.")
    elif cmd == "autojoin":
        remove = bool(args) and args[0].lower() == "-r"
        words = args[1:] if remove else args
        rows = parse_autojoin(s.net.autojoin)
        if not words and not remove:
            _info(s, b, f"Joins on {s.net.name}: " + (" ".join(c for c, _k in rows) or "none") + ".")
            return
        name = words[0] if words else chan
        if not name:
            _err(s, b, HELP["autojoin"])
            return
        if not s.is_channel(name):
            name = "#" + name
        if not _saved(ui, s):
            _err(s, b, f"{s.net.name} isn't in the Network List, so it has no join list. Add it there first.")
            return
        have = [r for r in rows if lower(r[0]) == lower(name)]
        if remove:
            if not have:
                _err(s, b, f"{name} isn't on the join list of {s.net.name}.")
                return
            rows = [r for r in rows if lower(r[0]) != lower(name)]
            _info(s, b, f"{name} taken off the join list of {s.net.name}.")
        else:
            key = words[1] if len(words) > 1 else (b.mode_args.get("k", "") if b.kind == CHANNEL and lower(b.name) == lower(name) else "")
            rows = [r for r in rows if lower(r[0]) != lower(name)] + [(have[0][0] if have else name, key)]
            _info(s, b, f"{name} {'is already on' if have else 'added to'} the join list of {s.net.name}.")
        s.net.autojoin = build_autojoin(rows)
        ui.save_config()
    elif cmd == "perform":
        remove = bool(args) and args[0].lower() == "-r"
        line = _tail(rest, 1) if remove else rest
        if not args:
            if not s.net.commands:
                _info(s, b, f"No commands run after connecting to {s.net.name}.")
            for i, c in enumerate(s.net.commands, 1):
                _info(s, b, f"{i}. /{c.lstrip('/')}")
            return
        if not _saved(ui, s):
            _err(s, b, f"{s.net.name} isn't in the Network List. Add it there first.")
            return
        cmds = s.net.commands
        if remove:
            hit = None
            if line.isdigit() and 1 <= int(line) <= len(cmds):
                hit = int(line) - 1
            else:
                hit = next((i for i, c in enumerate(cmds) if c.lstrip("/").lower() == line.lstrip("/").lower()), None)
            if hit is None:
                _err(s, b, f"Not on the list: {line}. /perform alone shows it.")
                return
            gone = cmds.pop(hit)
            _info(s, b, f"Taken off: /{gone.lstrip('/')}")
        else:
            cmds.append(line.lstrip("/"))
            _info(s, b, f"Runs after connecting to {s.net.name}: /{line.lstrip('/')}")
        ui.save_config()
    elif cmd == "clearall":
        sessions = list(ui.sessions.values()) if args[:1] == ["-a"] else [s]
        for one in sessions:
            for x in one.all_buffers():
                x.lines.clear()
                x.marker = None
                ui.reload_buffer(x)
    elif cmd == "markasread":
        tabs = [x for one in ui.sessions.values() for x in one.all_buffers()] if args[:1] == ["-a"] else [b]
        for x in tabs:
            if x.activity or x.unread or x.mentioned:
                x.activity, x.unread, x.mentioned = 0, 0, False
                ui._buffer_changed(x)
        ui._rebuild_tabs()
    elif cmd == "savebuf":
        _save_buffer(ui, s, b, rest)
    elif cmd == "loadbuf":
        _load_buffer(ui, s, b, rest)
    elif cmd in ("strip", "timestamp"):
        if _tab_only(s, b, cmd):
            name = "strip" if cmd == "strip" else "timestamps"
            label = "Colours stripped" if cmd == "strip" else "Timestamps"
            _on_off(ui, s, b, cmd, args, bool(tabopts.get(cfg, b, name)), f"{label} in {b.name}",
                    lambda on: ui.set_tab_opt(b, name, on))
    elif cmd == "log":
        if _tab_only(s, b, cmd):
            _on_off(ui, s, b, cmd, args, cfg.log_all or ui._log_key(b) in cfg.log_tabs, f"Log to Disk for {b.name}",
                    lambda on: ui._log_to_disk(b, on))
            if cfg.log_all and args and _switch(args[0]) is False:
                _info(s, b, "Preferences > Logging saves every tab; turn that off there to stop this one.")
    elif cmd == "titlebar":
        ui.title_extra = rest
        ui._refresh_title()
    elif cmd == "dns":
        _dns(ui, s, b, args)
    elif cmd == "links":
        if s.state != "connected":
            _err(s, b, "Not connected. Use Server > Reconnect.")
        else:
            s.send("LINKS", *args[:2])
            if b is not s.server_buffer:
                _info(s, b, f"The server list shows in the {s.net.name} tab.")
    elif cmd == "uwho":
        _uwho(ui, s, b, args)
    elif cmd in ("aop", "avoice"):
        _control(ui, s, b, cmd, args)
    elif cmd == "abook":
        u = find_user(s, args[0]) if args else None
        ui.open_address_book(args[0] if args else "", u.realname if u is not None else "")
    elif cmd == "cnick":
        _cnick(ui, s, b, args)
    elif cmd == "beep":
        _beep(args)
    elif cmd == "flash":
        from PySide6.QtWidgets import QApplication
        QApplication.alert(ui)
    elif cmd == "splay":
        _splay(ui, s, b, rest)
    elif cmd == "speak":
        _speak(ui, s, b, rest)
    elif cmd == "donotdisturb":
        _on_off(ui, s, b, cmd, args, cfg.do_not_disturb, "Do not disturb", lambda on: ui.set_do_not_disturb(on))
    elif cmd == "play":
        _play(ui, s, b, args, rest)
    elif cmd == "run":
        _run(ui, s, b, rest)
