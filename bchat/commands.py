"""Slash commands typed in the input box. Unknown commands go to the server as they are, like XChat."""
from __future__ import annotations

import re
import sys
import time
import weakref

from .protocol import lower, mirc_mask, strip_format
from .config import NetworkConfig, Server
from .session import CHANNEL, ERROR, INFO, QUERY, Buffer, Session
from . import everyday
from . import extracmds


# XChat's default user commands (src/common/xchat.c). &2 = the rest from word 2, %2 = word 2, %c channel, %n own nick
ALIASES = {
    "action": "me &2", "ame": "allchan me &2", "amsg": "allchan say &2", "anick": "allserv nick &2",
    "banlist": "quote MODE %c +b", "dialog": "query %2", "exit": "quit", "grep": "lastlog &2",
    "kill": "quote KILL %2 :&3", "m": "msg &2", "onotice": "notice @%c &2", "servhelp": "quote HELP",
    "sping": "ping", "squery": "quote SQUERY %2 :&3", "sslserver": "server -ssl &2", "umode": "mode %n &2",
    "uptime": "quote STATS u", "ver": "ctcp %2 VERSION", "version": "ctcp %2 VERSION", "wallops": "quote WALLOPS :&2",
    "wii": "whois %2", "sv": "echo BChat %n on " + "%s",
}
_BUILTIN: set[str] = set()      # filled below
_BUILTIN_SELF: dict[str, bool] = {}
COMMAND_NAMES = sorted(set(ALIASES) | {
    "allchan", "allserv", "away", "back", "ban", "clear", "close", "ctcp", "ctcps", "cycle", "dehop", "deop", "devoice", "discon",
    "chat", "dcc", "load", "reload", "send", "unload", "disconnect", "echo", "exec", "flood", "flushq", "ghost", "help", "hop", "id", "ignore", "invite", "j", "join", "kick", "kickban",
    "filter", "lastlog", "leave", "list", "mdeop", "me", "mkick", "mode", "mop", "msg", "names", "nctcp", "newserver", "nick",
    "notice", "notify", "np", "op", "part", "ping", "query", "quit", "quote", "raw", "reconnect", "say", "server", "topic", "unban",
    "sysinfo", "unignore", "url", "voice", "wallchan", "wallchop", "whois", "wi",
    "timer", "timers", "alias", "channel", "partall", "online", "motd", *everyday.NAMES, *extracmds.NAMES,
})


VERSION = "BChat"           # %v in user commands: _version() adds the real number


def _version() -> str:
    from . import full_version
    return f"BChat {full_version()}"
MACHINE = "Linux" if sys.platform.startswith("linux") else "Windows"


HELP = {
    "allchan": "ALLCHAN <cmd>: runs a command in every channel of this server",
    "allserv": "ALLSERV <cmd>: runs a command on every server",
    "away": "AWAY [<reason>]: marks you away",
    "back": "BACK: marks you back",
    "ban": "BAN [-kru<seconds>] [<channel>] <nick or mask> [<type>] [<kick message>]: bans someone from the channel (type 6, nick!*user@host, unless you give a type). -k kicks too, -r takes the ban off, -u60 takes it off after 60 seconds. BAN -a <nick> bans their account. Types: 0 *!user@host, 1 *!*user@host, 2 *!*@host, 3 *!*user@*.host, 4 *!*@*.host, 5 nick!user@host, 6 nick!*user@host, 7 nick!*@host, 8 nick!*user@*.host, 9 nick!*@*.host; 10-19 are the same, with the digits in the host turned into ? instead of a *. An address BChat doesn't know is asked from the server first",
    "clear": "CLEAR [ALL|HISTORY|<lines>]: clears this tab, every tab, the input history, or the last lines",
    "close": "CLOSE: closes this tab",
    "ctcp": "CTCP <nick> <message>: sends a CTCP",
    "cycle": "CYCLE [#channel]: leaves and rejoins the channel (same as /hop)",
    "dcc": "DCC SEND <nick> [<file>], DCC CHAT <nick>, DCC GET <nick>, DCC CLOSE <type> <nick> <file>, DCC LIST, DCC IGNORE [on|off|accept|ignore]",
    "deop": "DEOP <nick>...: takes channel operator status",
    "devoice": "DEVOICE <nick>...: takes voice",
    "discon": "DISCON: disconnects from the server",
    "echo": "ECHO <text>: prints text here, nothing is sent",
    "exec": "EXEC [-o] <program>: runs a program. Its output prints here, or goes to the channel with -o",
    "ctcps": "CTCPS [on|off]: answer CTCP requests (VERSION, PING, TIME...) or not. ACTION and DCC always work",
    "flood": "FLOOD [+c|-c] [on|off|clear] [<bytes> <maxlines> <maxmessages> <ignoretime>]: flood protection for automatic CTCP replies",
    "flushq": "FLUSHQ: drops the lines waiting to be sent",
    "ghost": "GHOST <nick> <password>: frees your nick through NickServ",
    "help": "HELP [<command>]: this help",
    "id": "ID <password>: identifies to NickServ",
    "np": "NP [-e]: shares the song playing now (turn it on in Preferences > Chatting > Now Playing). -e shows it only to you",
    "sysinfo": "SYSINFO [-e]: shares one line about your PC (OS, CPU, RAM, disks, GPU, uptime). -e shows it only to you",
    "notify": "NOTIFY [<nick> [<networks>]]: adds a friend, or takes them off if already there. NOTIFY +<nick> only adds, NOTIFY -r <nick> only takes off. Alone: opens the Friends List",
    "ignore": "IGNORE [-lrpcntikdxwhu<seconds>] <nick or address> [<type>]: hides someone on this network (-w: on every network). -p private, -c channel, -n notices, -t CTCP, -i invites, -k colours and bold taken out, -d DCC, -h never a highlight; -x never ignore this address; -u60 for 60 seconds; -r takes them off (-r alone empties the list); -l lists. No type: the nick only. A type ignores their address (asked from the server when BChat doesn't know it). Types: 0 *!user@host, 1 *!*user@host, 2 *!*@host, 3 *!*user@*.host, 4 *!*@*.host, 5 nick!user@host, 6 nick!*user@host, 7 nick!*@host, 8 nick!*user@*.host, 9 nick!*@*.host; 10-19 are the same, with the digits in the host turned into ? instead of a *. IGNORE on / IGNORE off turns the whole list on or off. See Window > Ignore List",
    "invite": "INVITE <nick> [<channel>]: invites someone",
    "join": "JOIN [-n] <channel> [<key>]: joins a channel and shows it. -n joins without switching to it",
    "kick": "KICK [<channel>] <nick> [<reason>]: kicks someone",
    "kickban": "KICKBAN [<channel>] <nick> [<type>] [<kick message>]: bans, then kicks (BAN -k; the types are BAN's). KICKBAN -a <nick> bans their account",
    "filter": "FILTER [-w] [-c] [-r] <text>: copies this tab's lines with the text into a window. -c matches case, -r takes a regular expression, -w opens a new window",
    "lastlog": "LASTLOG <text>: finds text in this tab",
    "list": "LIST [<options>]: opens the Channel List and fetches it",
    "mdeop": "MDEOP: takes ops from everyone else here",
    "me": "ME <action>: says what you're doing",
    "mkick": "MKICK [<reason>]: kicks everyone else here",
    "mode": "MODE <channel or nick> <modes>: sets modes. # alone is this channel",
    "mop": "MOP: gives ops to everyone here",
    "msg": "MSG <nick> <message>: sends a private message",
    "names": "NAMES: lists who is here",
    "nctcp": "NCTCP <nick> <message>: sends a CTCP reply",
    "newserver": "NEWSERVER [-noconnect] <host> [<port>]: connects in a new tab",
    "nick": "NICK <nick>: changes your nick",
    "notice": "NOTICE <nick or channel> <message>: sends a notice",
    "op": "OP <nick>...: gives channel operator status",
    "part": "PART [<channel>] [<reason>]: leaves a channel",
    "ping": "PING [<nick>]: checks lag to the server, or to someone",
    "query": "QUERY <nick> [<message>]: opens a private tab",
    "quit": "QUIT [<reason>]: disconnects from this server",
    "quote": "QUOTE <text>: sends text to the server as it is",
    "reconnect": "RECONNECT: connects to this server again",
    "say": "SAY <text>: sends text, even if it starts with /",
    "server": "SERVER [-ssl] <host> [<port or +port>] [<password>]: connects to a server",
    "topic": "TOPIC [<channel>] [<text>]: shows or sets the topic",
    "unban": "UNBAN <mask>...: removes bans",
    "unignore": "UNIGNORE <nick or mask>: stops hiding someone (IGNORE -r)",
    "url": "URL <address>: opens an address in the browser",
    "voice": "VOICE <nick>...: gives voice",
    "wallchan": "WALLCHAN <text>: messages this channel",
    "wallchop": "WALLCHOP <text>: messages the ops of this channel",
    "whois": "WHOIS <nick>: shows who someone is",
    "dehop": "DEHOP <nick>...: takes half-operator status",
    "disconnect": "DISCONNECT: disconnects from the server",
    "hop": "HOP [#channel]: leaves and rejoins the channel. HOP <nick>...: gives half-operator status",
    "j": "J <channel> [<key>]: joins a channel",
    "leave": "LEAVE [<channel>] [<reason>]: leaves a channel",
    "raw": "RAW <text>: sends text to the server as it is",
    "wi": "WI <nick>: shows who someone is",
    "load": "LOAD [<file>]: loads a Python plugin",
    "unload": "UNLOAD <name>: unloads a plugin",
    "reload": "RELOAD <name>: loads a plugin again",
    "send": "SEND <nick> [<file>]: offers a file",
    "chat": "CHAT <nick>: offers or accepts a direct chat",
    "timer": "TIMER [<name>] <times> <seconds> <command>: runs a command later or again and again (times 0 = until stopped). "
             "/timer <name> off stops it",
    "timers": "TIMERS [OFF]: lists this network's timers, or stops them all",
    "alias": "ALIAS [<name> [<command>]]: adds or changes a command of your own ($1 $2- $nick $chan $me $network, | for more "
             "than one). /alias <name> removes it, /alias alone lists them",
    "partall": "PARTALL [<reason>]: leaves every channel on this network (the tabs stay open)",
    "online": "ONLINE: how long you've been connected to each network, and how long BChat has been running",
    "motd": "MOTD: shows the server's welcome message (also when Preferences > General skips it)",
    "channel": "CHANNEL: opens Channel Central for this channel (topic, modes, bans, exceptions, invites)",
    **everyday.HELP,
    **extracmds.HELP,
}


_DOLLAR = re.compile(r"\$(\d)(-?)|\$(nick|chan|me|network)\b")


def _dollars(word: str, s: Session, chan: str, args: list[str], query: str) -> str:
    """mIRC's alias identifiers: $1 = first word typed after the command, $2- = from the 2nd on, $nick (the other
    person in a query), $chan, $me, $network. Missing ones are empty, as in mIRC."""
    def fill(m):
        if m.group(1):
            i = int(m.group(1)) - 1
            if m.group(2):
                return " ".join(args[i:]) if i >= 0 else " ".join(args)
            return args[i] if 0 <= i < len(args) else ""
        return {"nick": query, "chan": chan, "me": s.nick, "network": s.net.name}[m.group(3)]
    return _DOLLAR.sub(fill, word)


_CODES = re.compile(r"([%&])([2-9cemnstuv])|\$\d-?|\$(?:nick|chan|me|network)\b")


def _split_bar(pattern: str) -> list[str]:
    """mIRC: | between commands. Only with spaces around it, so a | inside a word (J|wang) stays."""
    return [p.strip() for p in re.split(r"\s\|\s", pattern) if p.strip()]


def _expand(pattern: str, s: Session, chan: str, args: list[str], rest: str, query: str = "") -> str | None:
    """XChat's auto_insert. None when a value the pattern needs is missing. One pass, so typed text is never read as a code."""
    fixed = {"c": chan, "e": s.net.name, "m": MACHINE, "n": s.nick, "s": s.server_name or s.net.name, "t": time.ctime(),
             "u": s._identity("username") if hasattr(s, "_identity") else "", "v": _version()}

    def value(kind: str, code: str) -> str:
        if code.isdigit():
            i = int(code) - 2
            if kind == "%":
                return args[i] if i < len(args) else ""
            pieces = rest.split(None, i) if rest else []
            return pieces[i].strip() if i < len(pieces) else ""
        return fixed.get(code, kind + code)

    out = []
    for word in pattern.split(" "):
        missing = ""

        def fill(m):
            nonlocal missing
            if m.group(1) is None:                        # $1 $2- $nick ...: mIRC's, empty when missing
                return _dollars(m.group(0), s, chan, args, query)
            v = value(m.group(1), m.group(2))
            if not v:
                missing = m.group(1)
            return v
        word = _CODES.sub(fill, word)                     # one pass over the pattern only
        if missing == "&":
            return " ".join(out)      # "&2" with nothing typed just drops off the end
        if missing:
            return None
        out.append(word)
    return " ".join(out)


def user_commands(cfg) -> list[list[str]]:
    if cfg.user_commands is not None:
        return cfg.user_commands
    return [[n, c] for n, c in ALIASES.items()]


def alias_command(ui, s: Session, b: Buffer, args: list[str], rest: str) -> None:
    """mIRC's /alias, kept in XChat's User Commands (Settings > Advanced > User Commands): one list, one editor."""
    cfg = ui.cfg
    if not args:
        rows = user_commands(cfg)
        s.add(b, INFO, "*", f"Your commands ({len(rows)}): " + ", ".join(sorted({"/" + n for n, _c in rows})))
        return
    name = args[0].lstrip("/").lower()
    body = rest.split(None, 1)[1].strip() if len(rest.split(None, 1)) > 1 else ""
    if not re.fullmatch(r"[\w-]{1,30}", name):
        s.add(b, ERROR, "*", "An alias name is one word: letters, numbers, - or _.")
        return
    rows = [list(r) for r in user_commands(cfg)]
    had = any(n.lower() == name for n, _c in rows)
    rows = [r for r in rows if r[0].lower() != name]
    if body:
        rows.append([name, body.lstrip("/")])
        s.add(b, INFO, "*", f"Alias /{name} {'changed' if had else 'added'} (Settings > Advanced > User Commands).")
    elif had:
        s.add(b, INFO, "*", f"Alias /{name} removed.")
    else:
        s.add(b, ERROR, "*", f"No alias called /{name}.")
        return
    cfg.user_commands = rows
    ui.save_config()


def online_command(ui, b: Buffer) -> None:
    """mIRC's Online Timer as one command: time connected per network, then how long BChat has run."""
    from .session import duration
    s = b.session
    rows = [(x.net.name, x.online_text()) for x in ui.sessions.values()]
    for name, text in rows:
        s.add(b, INFO, "*", f"Online on {name}: {text}" if text else f"Not connected to {name}.")
    s.add(b, INFO, "*", f"BChat running: {duration(time.time() - ui.started_at)}")


def command_names(cfg) -> list[str]:
    return sorted({n.lower() for n, _ in user_commands(cfg)} | set(COMMAND_NAMES) - (set(ALIASES) if cfg.user_commands is not None else set()))


def start_program(s: Session, b: Buffer, line: str, send: bool = False) -> None:
    """/exec and !commands: no shell in between, so a nick like J|wang can't become part of a command line."""
    from PySide6.QtCore import QProcess
    args = QProcess.splitCommand(line)
    if not args:
        return
    p = QProcess(s)
    p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

    def output():
        for row in bytes(p.readAll()).decode("utf-8", "replace").splitlines():
            if not row:
                continue
            if send and b.kind != "server":
                s.say(b.name, row)
            else:
                s.add(b, INFO, "*", row)
    p.readyRead.connect(output)
    p.finished.connect(lambda *_: p.deleteLater())
    p.errorOccurred.connect(lambda _e: s.add(b, ERROR, "*", f"Couldn't run {args[0]}: {p.errorString()}"))
    p.start(args[0], args[1:])


def parse_server(args: list[str]) -> tuple[str, int, bool, str] | None:
    """XChat's form: [-ssl|-nossl] host [port|+port] [password]. host/+port also works, like the Network List."""
    ssl = False
    words = []
    for a in args:
        if a.lower() == "-ssl":
            ssl = True
        elif a.lower() == "-nossl":
            ssl = False
        else:
            words.append(a)
    if not words:
        return None
    host, _, inline = words[0].partition("/")
    rest = words[1:]
    port_text = inline or (rest.pop(0) if rest and rest[0].lstrip("+").isdigit() else "")
    if port_text.startswith("+"):
        ssl = True
    digits = port_text.lstrip("+")
    port = int(digits) if digits.isdigit() else (6697 if ssl else 6667)
    return host, port, ssl, rest[0] if rest else ""


def new_server(ui, args: list[str]) -> None:
    """/newserver, and /server when no tab is open: a new tab that isn't saved to the Network List."""
    connect = "-noconnect" not in [a.lower() for a in args]
    parsed = parse_server([a for a in args if a.lower() != "-noconnect"])
    if parsed is None:
        return
    host, port, ssl, password = parsed
    name = host
    n = 2
    while name in ui.sessions:
        name = f"{host} ({n})"
        n += 1
    net = NetworkConfig(name, [Server(host, port, ssl)], password=password, cycle=False)
    s = ui.session_for(net)
    s.typed_by_hand = True
    ui.select_buffer(s.server_buffer)
    if connect:
        s.connect_to_network()


def _dcc_command(ui, s: Session, b: Buffer, args: list[str], rest: str) -> None:
    """XChat's /DCC: SEND PSEND CHAT GET CLOSE LIST."""
    verb = args[0].lower() if args else "list"
    dcc = ui.dcc
    if verb in ("send", "psend") and len(args) >= 2:
        path = rest.split(None, 2)[2].strip('"') if len(args) > 2 else ""
        if not path:
            ui.send_file_dialog(s, [args[1]], True if verb == "psend" else None)
        else:
            dcc.send_file(s, args[1], path, True if verb == "psend" else None)
    elif verb == "chat" and len(args) >= 2:
        waiting = [t for t in dcc.items if t.kind == "chat" and t.state == "queued" and t.ip and t.nick.lower() == args[1].lower()]
        if waiting:
            dcc.accept(waiting[0])
        else:
            dcc.start_chat(s, args[1])
    elif verb == "get" and len(args) >= 2:
        waiting = [t for t in dcc.items if t.kind == "recv" and t.state == "queued" and t.nick.lower() == args[1].lower()
                   and (len(args) < 3 or t.name == args[2])]
        if waiting:
            ui.accept_transfer(waiting[0])
        else:
            s.add(b, ERROR, "*", f"No file offered by {args[1]}.")
    elif verb == "close" and len(args) >= 3:
        kind = {"send": "send", "get": "recv", "chat": "chat"}.get(args[1].lower())
        hits = [t for t in dcc.items if t.kind == kind and t.active and t.nick.lower() == args[2].lower() and (len(args) < 4 or t.name == args[3])]
        if hits:
            hits[0].abort()
        else:
            s.add(b, ERROR, "*", f"No such DCC: {' '.join(args[1:])}")
    elif verb == "ignore":                             # 0.8.5: /dcc ignore [on|off|accept|ignore]
        dcc.ignore_command(s, b, args[1:])
    elif verb == "list":
        if not dcc.items:
            s.add(b, INFO, "*", "No active DCCs.")
        for t in dcc.items:
            s.add(b, INFO, "*", f"{t.kind:5} {t.state:10} {t.nick:15} {t.percent():3}% {t.name}")
    else:
        s.add(b, ERROR, "*", HELP["dcc"])


def _pieces(text: str, limit: int = 400) -> list[str]:
    """0.8.5: long text in pieces inside the 512-byte IRC line, cut between characters, never inside one
    (the same cut as plain chat, Session.say)."""
    out = []
    while text:
        raw = text.encode("utf-8")
        if len(raw) <= limit:
            out.append(text)
            break
        piece = raw[:limit].decode("utf-8", "ignore")
        out.append(piece)
        text = text[len(piece):]
    return out


_IGNORE_TIMERS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()   # session -> {folded mask: QTimer}
_IGNORE_SWITCHES = {"p": "P", "n": "N", "c": "C", "t": "T", "i": "I", "d": "D", "k": "K", "x": "U", "h": "H"}
_LOOKUPS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()   # session -> {folded nick: [waiting]}


def _find_ignore(s: Session, mask: str) -> str | None:
    """The ignore list's own spelling of a mask, compared without case (the server's CASEMAPPING)."""
    key = s.fold(mask)
    return next((m for m in s.cfg.ignores if s.fold(m) == key), None)


def _drop_ignore(s: Session, mask: str) -> bool:
    timer = _IGNORE_TIMERS.get(s, {}).pop(s.fold(mask), None)
    if timer is not None:
        timer.stop()
        timer.deleteLater()
    found = _find_ignore(s, mask)
    if found is None:
        return False
    s.cfg.ignores.remove(found)
    s.cfg.ignore_kinds.pop(found, None)
    s.cfg.ignore_nets.pop(found, None)
    return True


def _nets(s: Session, mask: str) -> list[str]:
    """The networks an ignore entry is for; empty: every network."""
    return [x.strip() for x in s.cfg.ignore_nets.get(mask, "").split(",") if x.strip()]


def _with_address(s: Session, b: Buffer, where: Buffer | None, nick: str, then) -> None:
    """then(user@host) now when BChat knows the address, else once the server says it (0.8.5: a /userhost
    lookup, as mIRC does; the server always answers it). No address in the answer: nothing is done, and it says so."""
    u = _known_user(s, where, nick)
    host = u.host if u is not None and "@" in (u.host or "") else s.whois_cache.get(s.fold(nick), {}).get("user", "")
    if "@" in host:
        then(host)
        return
    if s.state != "connected":
        s.add(b, ERROR, "*", f"BChat doesn't know {nick}'s address and can't ask the server while offline.")
        return
    waits = _LOOKUPS.get(s)
    if waits is None:
        waits = _LOOKUPS[s] = {}

        def answered(name: str, found: str, s=s) -> None:
            for b2, nick2, then2 in _LOOKUPS.get(s, {}).pop(s.fold(name), []):
                if "@" in found:
                    with s.typed():                # the user's own /ban or /ignore: sent at once, not paced
                        then2(found)
                elif s.state != "connected":
                    s.add(b2, ERROR, "*", f"Disconnected before the server gave {nick2}'s address, so nothing was done.")
                else:
                    s.add(b2, ERROR, "*", f"{nick2} isn't on IRC now, so BChat can't get their address. Nothing was done.")
        s.address_found.connect(answered)
    waits.setdefault(s.fold(nick), []).append((b, nick, then))
    s.add(b, INFO, "*", f"Asking the server for {nick}'s address...")
    s.userhost_lookup(nick)


def _ignore_command(s: Session, b: Buffer, args: list[str]) -> None:
    """/ignore [-lrpcntikdxwhsyu<seconds>] <nick or address> [type] [CHAN PRIV NOTI CTCP DCC INVI ALL UNIGNORE].
    p private, c channel, n notices, t CTCP, i invites, k control codes, d DCC, h highlights; x never ignore this
    address; r takes the entry off (alone: empties the list); l lists; u60 takes it off after 60 seconds;
    w any network (else this network only); s and y (speech, tips) have nothing in BChat to act on.
    No type: the nick only (nick!*@*); a type 0-19: their address (looked up when unknown). on / off: the whole list."""
    words = list(args)
    switches, secs, bad = _switches(words, "lrpcntikdxwhsyu")
    if bad:
        s.add(b, ERROR, "*", "Usage: " + HELP["ignore"])
        return
    if not switches and len(words) == 1 and words[0].lower() in ("on", "off"):
        s.cfg.ignore_on = words[0].lower() == "on"
        s.add(b, INFO, "*", "Ignoring is " + ("on." if s.cfg.ignore_on else "off: nobody is hidden until /ignore on."))
        return
    if "l" in switches or not words and not switches:
        shown = [m + (f" ({', '.join(_nets(s, m))})" if _nets(s, m) else "") for m in s.cfg.ignores]
        s.add(b, INFO, "*", "Ignore list: " + (", ".join(shown) or "empty") + ("" if s.cfg.ignore_on else " (ignoring is off)"))
        return
    if "r" in switches:
        if not words:                              # -r alone: the whole list
            for mask in list(s.cfg.ignores):
                _drop_ignore(s, mask)
            s.add(b, INFO, "*", "Ignore list emptied.")
            return
        mask = words[0] if "!" in words[0] or "@" in words[0] else f"{words[0]}!*@*"
        found = _find_ignore(s, mask)
        if found is None:
            s.add(b, ERROR, "*", f"{mask} isn't on the ignore list.")
            return
        nets = _nets(s, found)
        others = [n for n in nets if s.fold(n) != s.fold(s.net.name)]
        if "w" not in switches and others and len(others) < len(nets):
            s.cfg.ignore_nets[found] = ",".join(others)     # still ignored on the other networks it was for
            s.add(b, INFO, "*", f"No longer ignoring {found} on {s.net.name}")
            return
        _drop_ignore(s, found)
        s.add(b, INFO, "*", f"No longer ignoring {found}")
        return
    if not words:
        s.add(b, ERROR, "*", "Usage: " + HELP["ignore"])
        return
    who = words[0]
    kinds_asked = set(switches) & set("pcntikdxhsy")
    if kinds_asked and kinds_asked <= {"s", "y"}:      # speech and tips only: BChat has neither, so nothing to hide
        s.add(b, INFO, "*", f"Nothing to ignore for {who}: BChat has no speech or tips.")
        return
    if "!" in who or "@" in who:
        _add_ignore(s, b, who, switches, secs, words[1:])
    elif len(words) > 1 and words[1].isdigit():    # a type: their address
        kind = int(words[1])
        if kind > 19:
            s.add(b, ERROR, "*", "Usage: " + HELP["ignore"])
            return
        rest = words[2:]
        _with_address(s, b, None, who, lambda uh: _add_ignore(s, b, mirc_mask(who, uh, kind), switches, secs, rest))
    else:
        _add_ignore(s, b, f"{who}!*@*", switches, secs, words[1:])


def _add_ignore(s: Session, b: Buffer, mask: str, switches: str, secs: int, names: list[str]) -> None:
    picked = "".join(_IGNORE_SWITCHES[c] for c in switches if c in _IGNORE_SWITCHES)
    found = _find_ignore(s, mask)
    mask = found or mask
    if found is None:
        s.cfg.ignores.append(mask)
        if "w" not in switches:
            s.cfg.ignore_nets[mask] = s.net.name
    elif "w" in switches:
        s.cfg.ignore_nets.pop(mask, None)
    elif _nets(s, mask) and s.fold(s.net.name) not in [s.fold(n) for n in _nets(s, mask)]:
        s.cfg.ignore_nets[mask] = ",".join([*_nets(s, mask), s.net.name])
    # the older form: /ignore mask CHAN PRIV NOTI CTCP DCC INVI ALL UNIGNORE
    names_to = {"CHAN": "C", "PRIV": "P", "NOTI": "N", "CTCP": "T", "DCC": "D", "INVI": "I", "UNIGNORE": "U", "ALL": "CPNTDI"}
    picked += "".join(names_to.get(w.upper(), "") for w in names if w.upper() != "QUIET")
    if picked:
        s.cfg.ignore_kinds[mask] = "".join(dict.fromkeys(picked))
    timers = _IGNORE_TIMERS.setdefault(s, {})
    old = timers.pop(s.fold(mask), None)
    if old is not None:
        old.stop()
        old.deleteLater()
    if secs:
        from PySide6.QtCore import QTimer
        t = QTimer(s)
        t.setSingleShot(True)
        t.setInterval(secs * 1000)
        t.timeout.connect(lambda: _drop_ignore(s, mask))
        timers[s.fold(mask)] = t
        t.start()
    verb = "Never ignoring" if s.cfg.ignore_kinds.get(mask) == "U" else "Now ignoring"     # -x: an exception
    nets = _nets(s, mask)
    s.add(b, INFO, "*", f"{verb} {mask}" + (f" on {', '.join(nets)}" if nets else " on every network")
          + (f" for {secs} seconds" if secs else ""))


def _switches(words: list[str], letters: str) -> tuple[str, int, bool]:
    """Leading -xyz words: (letters picked, seconds from u<N>, bad). Letters may be run together: -ku60."""
    picked, secs = "", 0
    while words and words[0].startswith("-") and len(words[0]) > 1 and not words[0][1:].isdigit():
        sw = words.pop(0)[1:].lower()
        i = 0
        while i < len(sw):
            ch = sw[i]
            if ch == "u" and "u" in letters:
                j = i + 1
                while j < len(sw) and sw[j].isdigit():
                    j += 1
                if j == i + 1 or int(sw[i + 1:j]) <= 0:
                    return picked, secs, True
                secs, i = int(sw[i + 1:j]), j
            elif ch in letters and ch != "u":
                picked += ch
                i += 1
            else:
                return picked, secs, True
    return picked, secs, False


def _known_user(s: Session, where: Buffer | None, nick: str):
    """What we know of a nick: from this channel first, then any other tab of the network."""
    key = s.fold(nick)
    if where is not None and key in where.users:
        return where.users[key]
    return next((x.users[key] for x in s.buffers.values() if key in x.users), None)


def _ban_command(s: Session, b: Buffer, chan: str, rest: str, kick: bool = False, cmd: str = "ban") -> None:
    """/ban [-kruN] [-a] [#channel] <nick|address> [type] [kick message]. -k kicks too, -r takes the ban off,
    -u60 takes it off after 60 seconds, -a bans the account. /kickban is /ban -k."""
    words = rest.split()
    picked, secs, bad = _switches(words, "krua")
    if bad:
        s.add(b, ERROR, "*", "Usage: " + HELP[cmd])
        return
    kick = kick or "k" in picked
    if words and s.is_channel(words[0]):
        target = words.pop(0)
    elif chan:
        target = chan
    else:
        s.add(b, ERROR, "*", f"/{cmd} needs a channel tab.")
        return
    if not words:
        s.add(b, ERROR, "*", "Usage: " + HELP[cmd])
        return
    where = b if chan and s.fold(target) == s.fold(chan) else s.buffer(target, create=False)
    who = words.pop(0)
    kind = int(words.pop(0)) if words and words[0].isdigit() and int(words[0]) <= 19 else None
    # the kick message is the rest of the typed text after the words used up above, spaces kept
    head = len(rest.split()) - len(words)
    reason = rest.strip().split(None, head)[head] if words else ""
    is_mask = "!" in who or "@" in who
    if "a" in picked and not is_mask:              # 0.6.0: ban the account, not the host
        u = _known_user(s, where, who)
        if where is not None and "r" not in picked and not secs:
            s.account_ban(where, who, kick=kick)
            return
        pre, types = s.extban
        if not pre or "a" not in types:
            s.add(b, ERROR, "*", "This server has no account bans (EXTBAN a). Use /ban nick instead.")
            return
        if u is None or not u.account:
            s.add(b, ERROR, "*", f"BChat doesn't know {who}'s account (not logged in, or the server doesn't say). "
                                 "Use /ban nick instead.")
            return
        _ban_mask(s, target, f"{pre}a:{u.account}", picked, secs, kick, who, reason)
    elif is_mask:
        _ban_mask(s, target, who, picked, secs, False, who, reason)
    else:                                          # no type: type 6, nick!*user@host
        _with_address(s, b, where, who, lambda uh: _ban_mask(
            s, target, mirc_mask(who, uh, 6 if kind is None else kind), picked, secs, kick, who, reason))


def _ban_mask(s: Session, target: str, mask: str, picked: str, secs: int, kick: bool, who: str, reason: str) -> None:
    if "r" in picked:
        s.send("MODE", target, "-b", mask)
        return
    s.send("MODE", target, "+b", mask)
    if kick:
        s.send("KICK", target, who, reason.strip() or s.cfg.part_reason)
    if secs:
        from PySide6.QtCore import QTimer
        gen = s._conn_gen
        QTimer.singleShot(secs * 1000, s, lambda: s._conn_gen == gen and s.state == "connected"
                          and s.send("MODE", target, "-b", mask))


def _flood_command(ui, s: Session, b: Buffer, args: list[str]) -> None:
    """0.8.5 /flood [+c|-c] [on|off|clear] <bytes> <maxlines> <maxmessages> <ignoretime>: flood protection for automatic
    CTCP replies (Session._ctcp_reply). With nothing after it, shows the settings."""
    c = s.cfg
    words = list(args)
    if words and words[0].lower() in ("+c", "-c"):
        c.flood_ctcp_on = words.pop(0).lower() == "+c"
    if words and words[0].lower() in ("on", "off"):
        c.flood_on = words.pop(0).lower() == "on"
    elif words and words[0].lower() == "clear":
        words.pop(0)
        dropped = s.flood_clear()
        s.add(b, INFO, "*", f"Flood buffer cleared ({dropped} held repl{'y' if dropped == 1 else 'ies'} dropped).")
    if words:
        if len(words) != 4 or not all(w.isdigit() for w in words):
            s.add(b, ERROR, "*", "Usage: " + HELP["flood"])
            return
        c.flood_bytes, c.flood_lines, c.flood_per_user, c.flood_ignore = (int(w) for w in words)
    if args and args[0].lower() != "clear" or len(args) > 1:
        save = getattr(ui, "save_config", None)
        if callable(save):
            save()
    s.add(b, INFO, "*", f"Flood protection is {'on' if c.flood_on else 'off'}, CTCP replies {'included' if c.flood_ctcp_on else 'left out'}: "
                        f"after {c.flood_bytes} bytes, {c.flood_lines} lines, {c.flood_per_user} per user, ignore for {c.flood_ignore} s.")


def _ctcps_command(ui, s: Session, b: Buffer, args: list[str]) -> None:
    """0.8.7 /ctcps [on|off]: the same setting as Settings > Advanced > Reply to CTCP requests."""
    c = s.cfg
    word = args[0].lower() if args else ""
    if not word:
        s.add(b, INFO, "*", f"CTCP replies: {'on' if c.ctcp_reply_enabled else 'off'}")
        return
    if word not in ("on", "off"):
        s.add(b, ERROR, "*", "Usage: " + HELP["ctcps"])
        return
    c.ctcp_reply_enabled = word == "on"
    save = getattr(ui, "save_config", None)
    if callable(save):
        save()
    if c.ctcp_reply_enabled:
        s.add(b, INFO, "*", "CTCP replies are on.")
    else:
        s.add(b, INFO, "*", "CTCP replies are off: VERSION, PING, TIME, FINGER, CLIENTINFO get no answer.")


def run(ui, s: Session, b: Buffer, text: str, depth: int = 0) -> None:
    # 0.8.5: typed "!seen Bob" is chat, as in any client; "!" runs a program only from user commands and aliases.
    # Nothing, spaces only, or "/ hello" (no command name) is never sent.
    if not text.strip() or (text.startswith("/") and not text.startswith("//") and not text[1:].split(" ", 1)[0]):
        return
    if text.startswith("//") and text.lstrip("/")[:1].strip():       # ///typo too: never chat
        # 0.6.1 (user: 'mIRC way'): //command runs the command, as in mIRC. Before, it was XChat's 'say this as
        # chat', so '//ns identify nick password' in a channel went to everyone. Text that starts with / : /say
        run(ui, s, b, "/" + text.lstrip("/"), depth)
        return
    if text.startswith("/") and not text.startswith("//") and ui.plugins.on_command(text):
        return
    if not text.startswith("/") or text.startswith("//"):
        msg = text[1:] if text.startswith("//") else text
        if not s.net.servers:
            s.add(b, ERROR, "*", "This tab has no server yet. Type /server <host> [port or +port for SSL].")
        elif b.name.startswith("="):
            s.say(b.name, msg)
        elif b.kind == "server" or b.placeholder or b.name == "(notices)":
            s.add(b, ERROR, "*", "No channel joined. Try /join #channel")
        elif b.name == s.MESSAGES:
            s.add(b, ERROR, "*", "Reply with /msg nick message (Tab picks the nick)")
        else:
            s.say(b.name, msg)
        return
    cmd, _, rest = text[1:].partition(" ")
    cmd = cmd.lower()
    rest = rest.strip()
    if not s.net.servers and cmd not in ("server", "newserver", "clear", "close", "help", "echo", "allserv", *everyday.LOCAL,
                                         *extracmds.LOCAL):
        s.add(b, ERROR, "*", "This tab has no server yet. Type /server <host> [port or +port for SSL].")
        return
    args = rest.split()
    chan = b.name if b.kind == CHANNEL else ""
    matches = [c for n, c in user_commands(ui.cfg) if n.lower() == cmd]
    if matches and not (depth and cmd in _BUILTIN and _BUILTIN_SELF.get(cmd)):
        if depth >= 10:
            s.add(b, ERROR, "*", "Too many recursive user commands, stopped.")
            return
        query = b.name if b.kind == QUERY else ""
        for pattern in matches:
            for piece in _split_bar(pattern):
                expanded = _expand(piece, s, chan, args, rest, query)
                if expanded is None:
                    s.add(b, ERROR, "*", f"/{cmd} needs more: {pattern}")
                    break
                elif expanded.startswith("!"):
                    start_program(s, b, expanded[1:])
                else:
                    run(ui, s, b, "/" + expanded.lstrip("/"), depth + 1)
        return

    def need_channel() -> bool:
        if not chan:
            s.add(b, ERROR, "*", f"/{cmd} needs a channel tab.")
        return bool(chan)

    if cmd == "clear" and args and args[0].lower() == "all":
        for x in s.all_buffers():
            x.lines.clear()
            x.marker = None
            ui.reload_buffer(x)
    elif cmd == "clear" and args and args[0].lower() == "history":
        ui.input.clear_history()                 # 0.8.5: every tab's history
    elif cmd == "clear":
        n = int(args[0]) if args and args[0].isdigit() else 0
        if n and n < len(b.lines):
            del b.lines[-n:]
        else:
            b.lines.clear()
        b.marker = None
        ui.reload_buffer(b)
    elif cmd in ("join", "j"):
        flags = [a.lower() for a in args if a.lower() in ("-n", "-x")]
        args = [a for a in args if a.lower() not in ("-n", "-x")]
        stay = "-n" in flags and "-x" not in flags      # mIRC: -n = don't switch to it, -x = do (the default)
        if args:
            name = args[0] if s.is_channel(args[0]) or "," in args[0] else "#" + args[0]  # as XChat does
            existing = s.buffers.get(s.fold(name))
            if stay:
                s.stay_back = s.fold(name)
            elif existing is not None:
                ui.select_buffer(existing)
            else:
                s.focus_next = s.fold(name)
            s.send("JOIN", name, *args[1:2])
            if b.placeholder:      # the empty tab becomes this channel
                s.focus_next = s.fold(name)
                ui.close_buffer(b)
    elif cmd in ("part", "leave"):
        target = args[0] if args and s.is_channel(args[0]) else chan
        reason = " ".join(args[1:]) if args and s.is_channel(args[0]) else rest
        if target:
            s.send("PART", target, reason or s.cfg.part_reason)
    elif cmd == "msg" and len(args) >= 2:
        if args[0].startswith("="):               # =nick: the DCC chat with them
            s.say(args[0], rest.partition(" ")[2])
        else:
            for piece in _pieces(rest.partition(" ")[2]):
                s.msg(args[0], piece)
    elif cmd == "query" and args:
        ui.select_buffer(s.buffer(args[0]))
        if len(args) > 1:
            s.say(args[0], rest.partition(" ")[2])
    elif cmd == "me":
        if b.name.startswith("="):
            s.say(b.name, f"\x01ACTION {rest}\x01")
        elif b.name == s.MESSAGES:      # QA BUG-2 (0.8.6): never PRIVMSG "(messages)"
            s.add(b, ERROR, "*", "Reply with /msg nick message (Tab picks the nick)")
        elif b.name == "(notices)" or b.placeholder:
            s.add(b, ERROR, "*", "/me needs a channel or private tab.")
        elif b.kind != "server":
            for piece in _pieces(rest, 400 - len("\x01ACTION \x01")) or [rest]:
                s.action(b.name, piece)
        else:
            s.add(b, ERROR, "*", "/me needs a channel or private tab.")
    elif cmd == "nick" and args:
        s.send("NICK", args[0])
    elif cmd in ("whois", "wi") and args:
        s.whois(args[0])
    elif cmd == "topic":
        target, words = (args[0], rest.partition(" ")[2].lstrip()) if args and s.is_channel(args[0]) else (chan, rest)
        if target or need_channel():
            s.send("TOPIC", target, words) if words else s.send("TOPIC", target)
    elif cmd == "notice" and len(args) >= 2:
        for piece in _pieces(rest.partition(" ")[2]):
            s.send("NOTICE", args[0], piece)
            s.add(b, "notice", f">{args[0]}<", piece)
    elif cmd == "cycle" or (cmd == "hop" and (not args or args[0][:1] in s.chantypes)):
        # /hop alone (or /hop #channel) leaves and rejoins, as in mIRC; /hop nick still gives half-op (XChat)
        target = args[0] if args and args[0][:1] in s.chantypes else chan
        if not target:
            need_channel()
        else:
            tb = s.buffer(target, create=False)
            key = tb.mode_args.get("k", "") if tb is not None else ""
            s.send("PART", target, s.cfg.part_reason)
            s.send("JOIN", target, key) if key else s.send("JOIN", target)   # a +k channel needs its key back
    elif cmd in ("op", "deop", "voice", "devoice", "hop", "dehop"):
        if need_channel() and args:
            letter = {"op": "+o", "deop": "-o", "voice": "+v", "devoice": "-v", "hop": "+h", "dehop": "-h"}[cmd]
            s.set_mode_for(b, letter, args)
    elif cmd == "kick":
        # 0.8.5: /kick #channel nick [reason] too; without a channel, this tab's
        target, words = (args[0], rest.partition(" ")[2].strip()) if args and s.is_channel(args[0]) else (chan, rest)
        if (target or need_channel()) and words:
            nick, _, reason = words.partition(" ")
            s.send("KICK", target, nick, reason.strip() or s.cfg.part_reason)
    elif cmd in ("ban", "kickban"):
        _ban_command(s, b, chan, rest, kick=cmd == "kickban", cmd=cmd)    # 0.8.5: /kickban is /ban -k
    elif cmd == "mode":
        if args[:1] == ["#"]:                       # 0.8.5: # alone is this channel
            if need_channel():
                s.send("MODE", chan, *args[1:])
        else:
            s.send("MODE", *(args or [chan or s.nick]))
    elif cmd == "invite" and args:
        s.send("INVITE", args[0], args[1] if len(args) > 1 else chan)
    elif cmd == "away":
        s.set_away(True, rest)
    elif cmd == "back":
        s.set_away(False)
    elif cmd in ("quote", "raw"):
        s.send_labeled(b, rest)                  # labeled-response: the answer comes back to this tab
    elif cmd == "ctcp" and len(args) >= 2:
        s.send("PRIVMSG", args[0], "\x01" + rest.partition(" ")[2] + "\x01")
        s.add(b, INFO, "*", f"CTCP sent to {args[0]}: {rest.partition(' ')[2]}")
    elif cmd == "nctcp" and len(args) >= 2:
        s.send("NOTICE", args[0], "\x01" + rest.partition(" ")[2] + "\x01")
    elif cmd == "ping":
        if args:
            s.send("PRIVMSG", args[0], f"\x01PING {int(time.time())}\x01")
        else:
            lag = s.current_lag_ms()
            s._tick()
            s.add(b, INFO, "*", f"Lag to server: {lag} ms" if lag is not None else "Checking the server, see the strip's tooltip.")
    elif cmd == "sysinfo":
        from . import full_version, sysinfo
        line = sysinfo.render(s.cfg.sysinfo_line or sysinfo.DEFAULT_LINE, sysinfo.collect(full_version()))
        if args and args[0].lower() == "-e" or b.kind not in (CHANNEL, QUERY):
            s.add(b, INFO, "*", line)
            if b.kind not in (CHANNEL, QUERY) and not (args and args[0].lower() == "-e"):
                s.add(b, INFO, "*", "Shown only to you: /sysinfo sends to a channel or a private chat.")
        else:
            s.say(b.name, line)
    elif cmd == "np":
        ui.now_playing(s, b, only_me=bool(args and args[0].lower() == "-e"))
    elif cmd == "notify":
        if not args:
            ui.open_tool("friends") if hasattr(ui, "open_tool") else None
        elif args[0].lower() == "-r":               # 0.8.5: /notify -r nick takes them off
            if len(args) > 1:
                nick = args[1].lstrip("+")
                if lower(nick) in [lower(n) for n in s.cfg.friends]:
                    ui.remove_friend(nick)
                    s.add(b, INFO, "*", f"{nick} taken off your Friends List.")
                else:
                    s.add(b, ERROR, "*", f"{nick} isn't on your Friends List.")
        elif args[0].startswith("+"):               # /notify +nick only ever adds
            if args[0].lstrip("+"):
                ui.add_friend(args[0].lstrip("+"), " ".join(args[1:]), say=True)
        elif lower(args[0]) in [lower(n) for n in s.cfg.friends]:
            ui.remove_friend(args[0])
            s.add(b, INFO, "*", f"{args[0]} taken off your Friends List.")
        else:
            ui.add_friend(args[0], " ".join(args[1:]), say=True)
    elif cmd == "ignore":
        _ignore_command(s, b, args)
    elif cmd == "unignore" and args:
        _ignore_command(s, b, ["-r", *args[:1]])     # 0.8.5: /ignore -r, any case, as the server folds nicks
    elif cmd in ("mop", "mdeop"):
        if need_channel():
            want_op = cmd == "mop"
            nicks = [u.nick for u in b.users.values() if ("@" in u.prefixes) != want_op and lower(u.nick) != lower(s.nick)]
            if nicks:
                s.set_mode_for(b, "+o" if want_op else "-o", nicks)
    elif cmd == "mkick":
        if need_channel():
            for u in list(b.users.values()):
                if lower(u.nick) != lower(s.nick):
                    s.send("KICK", chan, u.nick, rest or s.cfg.part_reason)
    elif cmd in ("wallchan", "wallchop"):
        if need_channel() and rest:
            if cmd == "wallchan":
                s.send("PRIVMSG", chan, rest)
            else:
                s.send("NOTICE", "@" + chan, rest)
    elif cmd == "flood":
        _flood_command(ui, s, b, args)
    elif cmd == "ctcps":
        _ctcps_command(ui, s, b, args)
    elif cmd == "flushq":
        waiting = len(s._queue)
        s._queue.clear()
        s.add(b, INFO, "*", f"Cleared {waiting} waiting line(s).")
    elif cmd == "exec":
        send = args[:1] == ["-o"]
        line = rest.partition(" ")[2] if send else rest
        if line:
            start_program(s, b, line, send)
    elif cmd == "url" and args:
        ui.open_url(args[0])
    elif cmd == "load":
        if rest:
            ui.plugins.load(rest.strip('"'))
        else:
            ui.load_plugin_dialog()
    elif cmd == "unload" and rest:
        found = ui.plugins.find(rest.strip('"'))
        if found:
            ui.plugins.unload(found)
        else:
            s.add(b, ERROR, "*", f"No such plugin: {rest}")
    elif cmd == "reload" and rest:
        found = ui.plugins.find(rest.strip('"'))
        if found:
            ui.plugins.reload(found)
        else:
            s.add(b, ERROR, "*", f"No such plugin: {rest}")
    elif cmd == "dcc":
        _dcc_command(ui, s, b, args, rest)
    elif cmd == "send":
        _dcc_command(ui, s, b, ["send", *args], "send " + rest)
    elif cmd == "chat":
        _dcc_command(ui, s, b, ["chat", *args], "chat " + rest)
    elif cmd == "say":
        s.say(b.name, rest) if b.kind != "server" else s.add(b, ERROR, "*", "No channel joined.")
    elif cmd == "echo":
        s.add(b, INFO, "*", rest)
    elif cmd == "names":
        s.send("NAMES", args[0] if args else chan)
    elif cmd == "list":
        ui.open_channel_list(s, download=not args)
        if args:
            s.send("LIST", *args)
    elif cmd == "id" and args:
        s.send_raw(f"PRIVMSG NickServ :IDENTIFY {rest}", secret=True)
    elif cmd == "ghost" and args:
        s.send_raw(f"PRIVMSG NickServ :GHOST {rest}", secret=True)
    elif cmd == "unban":
        if need_channel() and args:
            s.send("MODE", chan, "-" + "b" * len(args), *args)
    elif cmd == "allchan" and rest:
        for x in list(s.buffers.values()):
            if x.kind == CHANNEL:
                run(ui, s, x, "/" + rest.lstrip("/"))
    elif cmd == "allserv" and rest:
        for other in list(ui.sessions.values()):
            run(ui, other, other.server_buffer, "/" + rest.lstrip("/"))
    elif cmd == "filter":                      # 0.8.7: the tab's matching lines in a window of their own
        words = rest.split()
        picked, _secs, bad = _switches(words, "wcr")
        n = len(rest.split()) - len(words)
        text_ = rest.split(None, n)[n].strip() if n and words else ("" if n else rest)
        if bad or not text_:
            s.add(b, ERROR, "*", "Usage: " + HELP["filter"])
        else:
            from .findbar import compile_pattern
            try:
                pat = compile_pattern(text_, "c" in picked, "r" in picked)
            except re.error as e:
                s.add(b, ERROR, "*", f"/filter: bad pattern: {e}")
            else:
                ui.open_filter(b, text_, pat, new="w" in picked)
    elif cmd == "lastlog" and rest:
        hits = [l for l in b.lines if rest.lower() in strip_format(l.text).lower()]
        s.add(b, INFO, "*", f"--- Search for {rest}: {len(hits)} found")
        for l in hits[-50:]:
            s.add(b, INFO, l.left, l.text)
    elif cmd in ("discon",):
        s.disconnect_from_network()
    elif cmd == "server":
        parsed = parse_server(args)
        if parsed is None:
            s.add(b, ERROR, "*", "Usage: /server [-ssl] <host> [<port>|+<port>] [<password>]")
        else:
            ui.server_command(s, *parsed)
    elif cmd == "newserver":
        new_server(ui, args)
    elif cmd == "reconnect":
        s.reconnect()
    elif cmd == "disconnect":
        s.disconnect_from_network()
    elif cmd == "quit":
        s.disconnect_from_network(rest or None)
    elif cmd == "close":
        ui.close_buffer(b)
    elif cmd in ("timer", "timers") or cmd.startswith("timer") and cmd[5:].isalnum():   # 0.8.10: /timer5, /timernews
        from . import timers
        timers.command(ui, s, b, cmd, args, rest)
    elif cmd == "alias":
        alias_command(ui, s, b, args, rest)
    elif cmd == "partall":
        chans = [x.name for x in s.buffers.values() if x.kind == CHANNEL and x.joined]
        if not chans:
            s.add(b, INFO, "*", f"You're not in any channel on {s.net.name}.")
        else:
            s.add(b, INFO, "*", f"Leaving {len(chans)} channel{'' if len(chans) == 1 else 's'} on {s.net.name}: {' '.join(chans)}")
            s.send("PART", ",".join(chans), rest or s.cfg.part_reason)
    elif cmd == "online":
        online_command(ui, b)
    elif cmd == "motd":
        s.motd_asked = True
        s.send("MOTD", *args[:1])
    elif cmd == "channel":
        if need_channel():
            ui.open_channel_central(b)
    elif cmd in everyday.NAMES:
        everyday.run(ui, s, b, cmd, args, rest)
    elif cmd in extracmds.NAMES:
        extracmds.run(ui, s, b, cmd, args, rest)
    elif cmd == "help" and args:
        about = HELP.get(args[0].lstrip("/").lower())
        s.add(b, INFO, "*", about or f"No help for {args[0]}. Help > Contents lists every command.")
    elif cmd == "help":
        s.add(b, INFO, "*", "Commands: /join /part /msg /query /me /nick /whois /topic /notice /op /deop /voice "
                            "/devoice /kick /ban /unban /kickban /mode /invite /away /back /quote /ctcp /ping /clear /close "
                            "/server /newserver /say /echo /names /list /id /ghost /cycle /allchan /allserv /lastlog /filter /reconnect /discon /quit "
                            "/ignore /unignore /nctcp /url /flood /flushq /mop /mdeop /mkick /wallchan /wallchop "
                            + " ".join("/" + n for n in everyday.NAMES) + " "
                            + " ".join("/" + n for n in extracmds.NAMES) + " "
                            + " ".join("/" + a for a in sorted(ALIASES)))
    else:
        s.send_labeled(b, text[1:])
