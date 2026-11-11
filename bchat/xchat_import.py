"""Read settings from XChat 2 (%APPDATA%\\X-Chat 2) and XChat-SE (%APPDATA%\\XChat-SE)."""
from __future__ import annotations

import os
from pathlib import Path

from .config import Config, NetworkConfig, Server

FLAG_CYCLE = 1
FLAG_GLOBAL = 2
FLAG_SSL = 4
FLAG_AUTO = 8
FLAG_INVALID = 32


def default_sources() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    return [p for p in (appdata / "XChat-SE", appdata / "X-Chat 2") if p.is_dir()]


def _read(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def parse_server(entry: str, net_ssl: bool) -> Server:
    """host/port, host/+port (SSL), host/*port (STARTTLS), host/+6697,7000 (several ports), wss://host[:port]/path."""
    low = entry.lower()
    if low.startswith(("wss://", "ws://")):
        plain = low.startswith("ws://")
        rest = entry.split("://", 1)[1]
        hostport, slash, path = rest.partition("/")
        if hostport.startswith("["):                     # [2001:db8::1]:8097
            host, _, after = hostport[1:].partition("]")
            port = after.lstrip(":")
        else:
            host, _, port = hostport.partition(":")
        return Server(host, int(port) if port.isdigit() else (80 if plain else 443), not plain, False, [],
                      "/" + path if slash else "/", plain)
    host, _, rest = entry.partition("/")
    ssl = net_ssl
    starttls = False
    ports: list[int] = []
    if rest:
        if rest.startswith("+"):
            ssl = True
            rest = rest[1:]
        elif rest.startswith("*"):               # a plain port, switched to SSL first (STARTTLS)
            ssl, starttls = False, True
            rest = rest[1:]
        for part in rest.split(","):
            part = part.strip()
            if part.isdigit() and 0 < int(part) < 65536 and int(part) not in ports:
                ports.append(int(part))
    port = ports[0] if ports else (6697 if ssl else 6667)
    return Server(host, port, ssl, starttls, ports[1:])


def parse_servlist(lines: list[str]) -> list[NetworkConfig]:
    nets: list[NetworkConfig] = []
    net: NetworkConfig | None = None
    for line in lines:
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key == "N":
            net = NetworkConfig(value)
            nets.append(net)
        elif net is None:
            continue
        elif key == "I":
            net.nick = value
        elif key == "i":
            net.nick2 = value
        elif key == "U":
            net.username = value
        elif key == "R":
            net.realname = value
        elif key == "P":
            net.password = value
        elif key == "B":
            net.nickserv = value
        elif key == "J":
            net.autojoin = value
        elif key == "C":
            net.commands.append(value)
        elif key == "F" and value.isdigit():
            f = int(value)
            net.cycle = bool(f & FLAG_CYCLE)
            net.use_global = bool(f & FLAG_GLOBAL)
            net.autoconnect = bool(f & FLAG_AUTO)
            net.allow_invalid_cert = bool(f & FLAG_INVALID)
            net.__dict__["_ssl"] = bool(f & FLAG_SSL)
        elif key == "S":
            net.__dict__.setdefault("_raw", []).append(value)
    for n in nets:
        ssl = n.__dict__.pop("_ssl", False)
        n.servers = [parse_server(e, ssl) for e in n.__dict__.pop("_raw", [])]
    return nets


def parse_conf(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines:
        k, sep, v = line.partition(" = ")
        if sep:
            out[k.strip()] = v
    return out


def _hex(v: str) -> str | None:
    parts = v.split()
    if len(parts) != 3:
        return None
    try:
        return "#" + "".join(f"{int(p, 16) >> 8:02x}" for p in parts)
    except ValueError:
        return None


def _is_light(lines: list[str]) -> bool:
    bg = _hex(parse_conf(lines).get("color_259", ""))
    if bg is None:
        return False
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b > 128


def apply_colors(cfg: Config, lines: list[str]) -> None:
    for k, v in parse_conf(lines).items():
        if not k.startswith("color_"):
            continue
        try:
            idx = int(k[6:])
        except ValueError:
            continue
        col = _hex(v)
        if col is None:
            continue
        if 0 <= idx < 16:
            cfg.theme.palette[idx] = col
        elif idx == 258:
            cfg.theme.chat_fg = col
        elif idx == 259:
            cfg.theme.chat_bg = col
        elif idx == 260:
            cfg.theme.marker = col
        elif idx == 261:
            cfg.theme.new_data = col
        elif idx == 262:
            cfg.theme.new_highlight = col
        elif idx == 263:
            cfg.theme.new_msg = col
        elif idx == 264:
            cfg.theme.away = col


def import_into(cfg: Config, sources: list[Path], colors: bool = False) -> list[str]:
    """Merge the sources into cfg, in order. Returns a human-readable report (never includes secrets)."""
    report = []
    have = {n.name.lower() for n in cfg.networks}
    custom: list[NetworkConfig] = []
    stock: list[NetworkConfig] = []
    for src in sources:
        conf = parse_conf(_read(src / "xchat.conf"))
        if conf.get("irc_nick1"):
            cfg.nick = conf["irc_nick1"]
            cfg.nick2 = conf.get("irc_nick2", cfg.nick2)
            cfg.nick3 = conf.get("irc_nick3", cfg.nick3)
            cfg.username = conf.get("irc_user_name") or cfg.username
            cfg.realname = conf.get("irc_real_name") or cfg.realname
            cfg.part_reason = conf.get("irc_part_reason") or cfg.part_reason
            cfg.quit_reason = conf.get("irc_quit_reason") or cfg.quit_reason
            cfg.away_reason = conf.get("away_reason") or cfg.away_reason
            cfg.highlight = conf.get("irc_extra_hilight", cfg.highlight)
            cfg.hilite_always = conf.get("irc_nick_hilight", cfg.hilite_always)
            cfg.hilite_no = conf.get("irc_no_hilight", cfg.hilite_no)
            from .highlights import migrate
            migrate(cfg)
        if colors and (src / "colors.conf").exists():
            lines = _read(src / "colors.conf")
            if _is_light(lines):
                # BChat is dark by design, and a light palette is unreadable on it
                report.append(f"Colours from {src.name} skipped (light theme)")
            else:
                apply_colors(cfg, lines)
                report.append(f"Colours from {src.name}")
        servlist = src / "servlist.conf"
        if not servlist.exists():
            servlist = src / "servlist_.conf"
        added = 0
        for net in parse_servlist(_read(servlist)):
            if net.name.lower() in have:
                continue
            have.add(net.name.lower())
            # networks the user set up go first, the long stock list after
            (custom if net.autoconnect or net.password or net.username else stock).append(net)
            added += 1
        report.append(f"{added} networks from {src.name}")
    cfg.networks[:0] = custom
    cfg.networks.extend(stock)
    cfg.imported = True
    return report
