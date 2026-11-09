"""Slash commands typed in the input box. Unknown commands go to the server as they are, like XChat."""
from __future__ import annotations

import re
import time

from .protocol import lower, strip_format
from .config import NetworkConfig, Server
from .session import CHANNEL, ERROR, INFO, QUERY, Buffer, Session


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
    "allchan", "allserv", "away", "back", "ban", "clear", "close", "ctcp", "cycle", "dehop", "deop", "devoice", "discon",
    "chat", "dcc", "load", "reload", "send", "unload", "disconnect", "echo", "exec", "flushq", "ghost", "help", "hop", "id", "ignore", "invite", "j", "join", "kick", "kickban",
    "lastlog", "leave", "list", "mdeop", "me", "mkick", "mode", "mop", "msg", "names", "nctcp", "newserver", "nick",
    "notice", "notify", "np", "op", "part", "ping", "query", "quit", "quote", "raw", "reconnect", "say", "server", "topic", "unban",
    "sysinfo", "unignore", "url", "voice", "wallchan", "wallchop", "whois", "wi",
    "timer", "timers", "alias", "channel",
})


VERSION = "BChat 0.1"
MACHINE = "Windows"


HELP = {
    "allchan": "ALLCHAN <cmd>: runs a command in every channel of this server",
    "allserv": "ALLSERV <cmd>: runs a command on every server",
    "away": "AWAY [<reason>]: marks you away",
    "back": "BACK: marks you back",
    "ban": "BAN <mask or nick> [<type>]: bans someone from the channel. Types 0-3 pick how wide the mask is",
    "clear": "CLEAR [ALL|HISTORY|<lines>]: clears this tab, every tab, the input history, or the last lines",
    "close": "CLOSE: closes this tab",
    "ctcp": "CTCP <nick> <message>: sends a CTCP",
    "cycle": "CYCLE [#channel]: leaves and rejoins the channel (same as /hop)",
    "dcc": "DCC SEND <nick> [<file>], DCC CHAT <nick>, DCC GET <nick>, DCC CLOSE <type> <nick> <file>, DCC LIST",
    "deop": "DEOP <nick>...: takes channel operator status",
    "devoice": "DEVOICE <nick>...: takes voice",
    "discon": "DISCON: disconnects from the server",
    "echo": "ECHO <text>: prints text here, nothing is sent",
    "exec": "EXEC [-o] <program>: runs a program. Its output prints here, or goes to the channel with -o",
    "flushq": "FLUSHQ: drops the lines waiting to be sent",
    "ghost": "GHOST <nick> <password>: frees your nick through NickServ",
    "help": "HELP [<command>]: this help",
    "id": "ID <password>: identifies to NickServ",
    "np": "NP [-e]: shares the song playing now (turn it on in Preferences > Chatting > Now Playing). -e shows it only to you",
    "sysinfo": "SYSINFO [-e]: shares one line about your PC (OS, CPU, RAM, disks, GPU, uptime). -e shows it only to you",
    "notify": "NOTIFY [<nick> [<networks>]]: adds a friend, or takes them off if already there. Alone: opens the Friends List",
    "ignore": "IGNORE <mask> [CHAN PRIV NOTI CTCP DCC INVI ALL UNIGNORE]: hides someone. See Window > Ignore List",
    "invite": "INVITE <nick> [<channel>]: invites someone",
    "join": "JOIN <channel> [<key>]: joins a channel",
    "kick": "KICK <nick> [<reason>]: kicks someone",
    "kickban": "KICKBAN <nick> [<type>]: bans, then kicks",
    "lastlog": "LASTLOG <text>: finds text in this tab",
    "list": "LIST [<options>]: opens the Channel List and fetches it",
    "mdeop": "MDEOP: takes ops from everyone else here",
    "me": "ME <action>: says what you're doing",
    "mkick": "MKICK [<reason>]: kicks everyone else here",
    "mode": "MODE <channel or nick> <modes>: sets modes",
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
    "topic": "TOPIC [<text>]: shows or sets the topic",
    "unban": "UNBAN <mask>...: removes bans",
    "unignore": "UNIGNORE <mask>: stops hiding someone",
    "url": "URL <address>: opens an address in the browser",
    "voice": "VOICE <nick>...: gives voice",
    "wallchan": "WALLCHAN <text>: messages this channel",
    "wallchop": "WALLCHOP <text>: messages the ops of this channel",
    "whois": "WHOIS <nick>: shows who someone is",
    "dehop": "DEHOP <nick>...: takes half-operator status",
    "disconnect": "DISCONNECT: disconnects from the server",
    "hop": "HOP [#channel]: leaves and rejoins the channel (as in mIRC). HOP <nick>...: gives half-operator status",
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
    "channel": "CHANNEL: opens Channel Central for this channel (topic, modes, bans, exceptions, invites)",
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
             "u": s._identity("username") if hasattr(s, "_identity") else "", "v": VERSION}

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
            ui.send_file_dialog(s, [args[1]], verb == "psend")
        else:
            dcc.send_file(s, args[1], path, verb == "psend")
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
    elif verb == "list":
        if not dcc.items:
            s.add(b, INFO, "*", "No active DCCs.")
        for t in dcc.items:
            s.add(b, INFO, "*", f"{t.kind:5} {t.state:10} {t.nick:15} {t.percent():3}% {t.name}")
    else:
        s.add(b, ERROR, "*", HELP["dcc"])


def run(ui, s: Session, b: Buffer, text: str, depth: int = 0) -> None:
    if text.startswith("!") :
        start_program(s, b, text[1:])
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
        else:
            s.say(b.name, msg)
        return
    cmd, _, rest = text[1:].partition(" ")
    cmd = cmd.lower()
    rest = rest.strip()
    if not s.net.servers and cmd not in ("server", "newserver", "clear", "close", "help", "echo", "allserv"):
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
        ui.input.history.clear()
        ui.input.pos_ = 0
    elif cmd == "clear":
        n = int(args[0]) if args and args[0].isdigit() else 0
        if n and n < len(b.lines):
            del b.lines[-n:]
        else:
            b.lines.clear()
        b.marker = None
        ui.reload_buffer(b)
    elif cmd in ("join", "j"):
        if args:
            name = args[0] if s.is_channel(args[0]) or "," in args[0] else "#" + args[0]  # as XChat does
            existing = s.buffers.get(lower(name))
            if existing is not None:
                ui.select_buffer(existing)
            else:
                s.focus_next = lower(name)
            s.send("JOIN", name, *args[1:2])
            if b.placeholder:      # the empty tab becomes this channel
                s.focus_next = lower(name)
                ui.close_buffer(b)
    elif cmd in ("part", "leave"):
        target = args[0] if args and s.is_channel(args[0]) else chan
        reason = " ".join(args[1:]) if args and s.is_channel(args[0]) else rest
        if target:
            s.send("PART", target, reason or s.cfg.part_reason)
    elif cmd == "msg" and len(args) >= 2:
        s.msg(args[0], rest.partition(" ")[2])
    elif cmd == "query" and args:
        ui.select_buffer(s.buffer(args[0]))
        if len(args) > 1:
            s.say(args[0], rest.partition(" ")[2])
    elif cmd == "me":
        if b.name.startswith("="):
            s.say(b.name, f"\x01ACTION {rest}\x01")
        elif b.kind != "server":
            s.action(b.name, rest)
        else:
            s.add(b, ERROR, "*", "/me needs a channel or private tab.")
    elif cmd == "nick" and args:
        s.send("NICK", args[0])
    elif cmd in ("whois", "wi") and args:
        s.whois(args[0])
    elif cmd == "topic":
        if need_channel():
            s.send("TOPIC", chan, rest) if rest else s.send("TOPIC", chan)
    elif cmd == "notice" and len(args) >= 2:
        s.send("NOTICE", args[0], rest.partition(" ")[2])
        s.add(b, "notice", f">{args[0]}<", rest.partition(" ")[2])
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
        if need_channel() and args:
            s.send("KICK", chan, args[0], rest.partition(" ")[2] or s.cfg.part_reason)
    elif cmd == "ban":
        if need_channel() and args:
            if "!" in args[0] or "@" in args[0]:  # already a mask
                s.send("MODE", chan, "+b", args[0])
            else:
                kind = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
                s.ban(b, args[0], kind)
    elif cmd == "kickban":
        if need_channel() and args:
            kind = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
            s.ban(b, args[0], kind, kick=True)
    elif cmd == "mode":
        s.send("MODE", *(args or [chan or s.nick]))
    elif cmd == "invite" and args:
        s.send("INVITE", args[0], args[1] if len(args) > 1 else chan)
    elif cmd == "away":
        s.set_away(True, rest)
    elif cmd == "back":
        s.set_away(False)
    elif cmd in ("quote", "raw"):
        s.send_raw(rest)
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
        elif lower(args[0]) in [lower(n) for n in s.cfg.friends]:
            ui.remove_friend(args[0])
            s.add(b, INFO, "*", f"{args[0]} taken off your Friends List.")
        else:
            ui.add_friend(args[0], " ".join(args[1:]), say=True)
    elif cmd == "ignore":
        if not args:
            s.add(b, INFO, "*", "Ignore list: " + (", ".join(s.cfg.ignores) or "empty"))
        else:
            mask = args[0] if "!" in args[0] or "@" in args[0] else f"{args[0]}!*@*"
            if mask not in s.cfg.ignores:
                s.cfg.ignores.append(mask)
            # XChat's form: /ignore mask CHAN PRIV NOTI CTCP DCC INVI ALL UNIGNORE
            words = {"CHAN": "C", "PRIV": "P", "NOTI": "N", "CTCP": "T", "DCC": "D", "INVI": "I", "UNIGNORE": "U", "ALL": "CPNTDI"}
            picked = "".join(words.get(w.upper(), "") for w in args[1:] if w.upper() != "QUIET")
            if picked:
                s.cfg.ignore_kinds[mask] = "".join(dict.fromkeys(picked))
            s.add(b, INFO, "*", f"Now ignoring {mask}")
    elif cmd == "unignore" and args:
        mask = args[0] if "!" in args[0] or "@" in args[0] else f"{args[0]}!*@*"
        if mask in s.cfg.ignores:
            s.cfg.ignores.remove(mask)
            s.cfg.ignore_kinds.pop(mask, None)
            s.add(b, INFO, "*", f"No longer ignoring {mask}")
        else:
            s.add(b, ERROR, "*", f"{mask} isn't on the ignore list.")
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
    elif cmd in ("timer", "timers"):
        from . import timers
        timers.command(ui, s, b, cmd, args, rest)
    elif cmd == "alias":
        alias_command(ui, s, b, args, rest)
    elif cmd == "channel":
        if need_channel():
            ui.open_channel_central(b)
    elif cmd == "help" and args:
        about = HELP.get(args[0].lstrip("/").lower())
        s.add(b, INFO, "*", about or f"No help for {args[0]}. Help > Contents lists every command.")
    elif cmd == "help":
        s.add(b, INFO, "*", "Commands: /join /part /msg /query /me /nick /whois /topic /notice /op /deop /voice "
                            "/devoice /kick /ban /unban /kickban /mode /invite /away /back /quote /ctcp /ping /clear /close "
                            "/server /newserver /say /echo /names /list /id /ghost /cycle /allchan /allserv /lastlog /reconnect /discon /quit "
                            "/ignore /unignore /nctcp /url /flushq /mop /mdeop /mkick /wallchan /wallchop "
                            + " ".join("/" + a for a in sorted(ALIASES)))
    else:
        s.send_raw(text[1:])
