"""Slash commands typed in the input box. Unknown commands go to the server as they are, like XChat."""
from __future__ import annotations

from .protocol import lower, strip_format
from .config import NetworkConfig, Server
from .session import CHANNEL, ERROR, INFO, Buffer, Session


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
            existing = s.buffers.get(lower(args[0]))
            if existing is not None:
                ui.select_buffer(existing)
            else:
                s.focus_next = lower(args[0])
            s.send("JOIN", *args[:2])
    elif cmd in ("part", "leave"):
        target = args[0] if args and s.is_channel(args[0]) else chan
        reason = " ".join(args[1:]) if args and s.is_channel(args[0]) else rest
        if target:
            s.send("PART", target, reason or s.cfg.part_reason)
    elif cmd == "msg" and len(args) >= 2:
        s.say(args[0], rest.partition(" ")[2])
    elif cmd == "query" and args:
        ui.select_buffer(s.buffer(args[0]))
        if len(args) > 1:
            s.say(args[0], rest.partition(" ")[2])
    elif cmd == "me":
        if b.kind != "server":
            s.action(b.name, rest)
    elif cmd == "nick" and args:
        s.send("NICK", args[0])
    elif cmd in ("whois", "wi") and args:
        s.whois(args[0])
    elif cmd == "topic":
        if need_channel():
            s.send("TOPIC", chan, rest) if rest else s.send("TOPIC", chan)
    elif cmd == "notice" and len(args) >= 2:
        s.send("NOTICE", args[0], rest.partition(" ")[2])
    elif cmd in ("op", "deop", "voice", "devoice", "hop", "dehop"):
        if need_channel() and args:
            letter = {"op": "+o", "deop": "-o", "voice": "+v", "devoice": "-v", "hop": "+h", "dehop": "-h"}[cmd]
            s.set_mode_for(b, letter, args)
    elif cmd == "kick":
        if need_channel() and args:
            s.send("KICK", chan, args[0], rest.partition(" ")[2] or s.cfg.part_reason)
    elif cmd == "ban":
        if need_channel() and args:
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
    elif cmd == "ping" and args:
        import time
        s.send("PRIVMSG", args[0], f"\x01PING {int(time.time())}\x01")
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
                run(ui, s, x, rest)
    elif cmd == "allserv" and rest:
        for other in list(ui.sessions.values()):
            run(ui, other, other.server_buffer, rest)
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
                            "/server /newserver /say /echo /names /list /id /ghost /cycle /allchan /allserv /lastlog /reconnect /discon /quit")
    else:
        s.send_raw(text[1:])
