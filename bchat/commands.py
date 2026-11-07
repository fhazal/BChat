"""Slash commands typed in the input box. Unknown commands go to the server as they are, like XChat."""
from __future__ import annotations

import time

from .protocol import lower, strip_format
from .config import NetworkConfig, Server
from .session import CHANNEL, ERROR, INFO, Buffer, Session


# XChat's default user commands (src/common/xchat.c). &2 = the rest from word 2, %2 = word 2, %c channel, %n own nick
ALIASES = {
    "action": "me &2", "ame": "allchan me &2", "amsg": "allchan say &2", "anick": "allserv nick &2",
    "banlist": "quote MODE %c +b", "dialog": "query %2", "exit": "quit", "grep": "lastlog &2",
    "kill": "quote KILL %2 :&3", "m": "msg &2", "onotice": "notice @%c &2", "servhelp": "quote HELP",
    "sping": "ping", "squery": "quote SQUERY %2 :&3", "sslserver": "server -ssl &2", "umode": "mode %n &2",
    "uptime": "quote STATS u", "ver": "ctcp %2 VERSION", "version": "ctcp %2 VERSION", "wallops": "quote WALLOPS :&2",
    "wii": "whois %2", "sv": "echo BChat %n on " + "%s",
}
COMMAND_NAMES = sorted(set(ALIASES) | {
    "allchan", "allserv", "away", "back", "ban", "clear", "close", "ctcp", "cycle", "dehop", "deop", "devoice", "discon",
    "disconnect", "echo", "flushq", "ghost", "help", "hop", "id", "ignore", "invite", "j", "join", "kick", "kickban",
    "lastlog", "leave", "list", "mdeop", "me", "mkick", "mode", "mop", "msg", "names", "nctcp", "newserver", "nick",
    "notice", "op", "part", "ping", "query", "quit", "quote", "raw", "reconnect", "say", "server", "topic", "unban",
    "unignore", "url", "voice", "wallchan", "wallchop", "whois", "wi",
})


def _expand(pattern: str, s: Session, chan: str, args: list[str], rest: str) -> str | None:
    """None when a value the pattern needs is missing."""
    tail = rest.partition(" ")[2].strip()
    values = {"&2": rest, "&3": tail, "%2": args[0] if args else "", "%c": chan, "%n": s.nick, "%s": s.server_name or s.net.name}
    out = []
    for word in pattern.split(" "):
        for key, value in values.items():
            if key in word:
                if not value:
                    return None if key != "&2" else " ".join(out)
                word = word.replace(key, value)
        out.append(word)
    return " ".join(out)


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


def run(ui, s: Session, b: Buffer, text: str) -> None:
    if not text.startswith("/") or text.startswith("//"):
        msg = text[1:] if text.startswith("//") else text
        if not s.net.servers:
            s.add(b, ERROR, "*", "This tab has no server yet. Type /server <host> [port or +port for SSL].")
        elif b.kind == "server":
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
    if cmd in ALIASES:
        expanded = _expand(ALIASES[cmd], s, chan, args, rest)
        if expanded is None:
            s.add(b, ERROR, "*", f"/{cmd} needs more: {ALIASES[cmd]}")
        else:
            run(ui, s, b, "/" + expanded)
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
        if b.kind != "server":
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
        s.send("AWAY", rest or s.cfg.away_reason)
    elif cmd == "back":
        s.send("AWAY")
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
    elif cmd == "ignore":
        if not args:
            s.add(b, INFO, "*", "Ignore list: " + (", ".join(s.cfg.ignores) or "empty"))
        else:
            mask = args[0] if "!" in args[0] or "@" in args[0] else f"{args[0]}!*@*"
            if mask not in s.cfg.ignores:
                s.cfg.ignores.append(mask)
            s.add(b, INFO, "*", f"Now ignoring {mask}")
    elif cmd == "unignore" and args:
        mask = args[0] if "!" in args[0] or "@" in args[0] else f"{args[0]}!*@*"
        if mask in s.cfg.ignores:
            s.cfg.ignores.remove(mask)
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
    elif cmd == "url" and args:
        ui.open_url(args[0])
    elif cmd in ("dcc", "send", "chat"):
        s.add(b, ERROR, "*", "File transfers and direct chat aren't in BChat yet.")
    elif cmd == "say":
        s.say(b.name, rest) if b.kind != "server" else s.add(b, ERROR, "*", "No channel joined.")
    elif cmd == "echo":
        s.add(b, INFO, "*", rest)
    elif cmd == "names":
        s.send("NAMES", args[0] if args else chan)
    elif cmd == "list":
        s.send("LIST", *args)
    elif cmd == "id" and args:
        s.send_raw(f"PRIVMSG NickServ :IDENTIFY {rest}", secret=True)
    elif cmd == "ghost" and args:
        s.send_raw(f"PRIVMSG NickServ :GHOST {rest}", secret=True)
    elif cmd == "unban":
        if need_channel() and args:
            s.send("MODE", chan, "-" + "b" * len(args), *args)
    elif cmd == "cycle":
        if need_channel():
            s.send("PART", chan, s.cfg.part_reason)
            s.send("JOIN", chan)
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
    elif cmd == "help":
        s.add(b, INFO, "*", "Commands: /join /part /msg /query /me /nick /whois /topic /notice /op /deop /voice "
                            "/devoice /kick /ban /unban /kickban /mode /invite /away /back /quote /ctcp /ping /clear /close "
                            "/server /newserver /say /echo /names /list /id /ghost /cycle /allchan /allserv /lastlog /reconnect /discon /quit "
                            "/ignore /unignore /nctcp /url /flushq /mop /mdeop /mkick /wallchan /wallchop "
                            + " ".join("/" + a for a in sorted(ALIASES)))
    else:
        s.send_raw(text[1:])
