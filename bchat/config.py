"""BChat settings, kept as JSON in %APPDATA%\\BChat. Network passwords are stored here as plain text, same as XChat."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Catppuccin Mocha, https://catppuccin.com (MIT)
MOCHA = dict(rosewater="#f5e0dc", flamingo="#f2cdcd", pink="#f5c2e7", mauve="#cba6f7", red="#f38ba8", maroon="#eba0ac",
             peach="#fab387", yellow="#f9e2af", green="#a6e3a1", teal="#94e2d5", sky="#89dceb", sapphire="#74c7ec",
             blue="#89b4fa", lavender="#b4befe", text="#cdd6f4", subtext1="#bac2de", subtext0="#a6adc8", overlay2="#9399b2",
             overlay1="#7f849c", overlay0="#6c7086", surface2="#585b70", surface1="#45475a", surface0="#313244",
             base="#1e1e2e", mantle="#181825", crust="#11111b")
_m = MOCHA

# IRC colour codes 0-15 mapped to Mocha shades. 1 is normally black, which can't be read here, so it is a dark grey.
DEFAULT_PALETTE = [
    _m["text"], _m["surface1"], _m["blue"], _m["green"], _m["red"], _m["maroon"], _m["mauve"], _m["peach"],
    _m["yellow"], _m["teal"], _m["teal"], _m["sky"], _m["sapphire"], _m["pink"], _m["overlay1"], _m["subtext0"],
]


@dataclass
class Server:
    host: str
    port: int = 6667
    ssl: bool = False


@dataclass
class NetworkConfig:
    name: str
    servers: list[Server] = field(default_factory=list)
    nick: str = ""
    nick2: str = ""
    username: str = ""
    realname: str = ""
    password: str = ""
    nickserv: str = ""
    sasl_user: str = ""
    sasl_password: str = ""
    autojoin: str = ""
    commands: list[str] = field(default_factory=list)
    autoconnect: bool = False
    use_global: bool = True
    allow_invalid_cert: bool = True
    cycle: bool = True
    favorite: bool = False


@dataclass
class Theme:
    window: str = _m["mantle"]
    panel: str = _m["base"]
    border: str = _m["surface0"]
    text: str = _m["text"]
    chat_bg: str = _m["base"]
    chat_fg: str = _m["text"]
    nick: str = _m["lavender"]
    join: str = _m["green"]
    topic: str = _m["mauve"]
    highlight: str = _m["yellow"]
    selected: str = _m["surface2"]
    away: str = _m["overlay1"]
    stamp: str = _m["overlay0"]
    marker: str = _m["red"]
    new_data: str = _m["peach"]
    new_msg: str = _m["red"]
    new_highlight: str = _m["blue"]
    bar: str = _m["crust"]         # title bar, buttons, count box, scrollbar track
    popup: str = _m["surface0"]    # menus and button hover
    thumb: str = _m["surface1"]    # scrollbar handle
    thumb_hover: str = _m["surface2"]
    disabled: str = _m["overlay0"]
    status_off: str = _m["red"]        # status strip next to the input box
    status_connecting: str = _m["yellow"]
    status_on: str = _m["green"]
    status_op: str = _m["sapphire"]
    status_lag: str = _m["peach"]
    palette: list[str] = field(default_factory=lambda: list(DEFAULT_PALETTE))


@dataclass
class Config:
    nick: str = ""
    nick2: str = ""
    nick3: str = ""
    username: str = "bchat"
    realname: str = "BChat user"
    part_reason: str = "Leaving"
    quit_reason: str = "Leaving"
    away_reason: str = "I'm busy"
    highlight: str = ""
    chat_font: str = "Consolas"
    chat_font_size: int = 9
    timestamps: bool = True
    show_menu: bool = True
    show_topic: bool = True
    show_userlist: bool = True
    win_width: int = 960
    win_height: int = 600
    theme: Theme = field(default_factory=Theme)
    networks: list[NetworkConfig] = field(default_factory=list)
    skip_network_list: bool = False
    sts: dict = field(default_factory=dict)  # host -> {port, expires}
    imported: bool = False


def default_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "BChat"


def _from_dict(d: dict) -> Config:
    cfg = Config()
    for k, v in d.items():
        if k == "theme":
            known = Theme.__dataclass_fields__
            cfg.theme = Theme(**{a: b for a, b in v.items() if a in known})
        elif k == "networks":
            known = NetworkConfig.__dataclass_fields__
            cfg.networks = []
            for n in v:
                n = dict(n)
                servers = [Server(**s) for s in n.pop("servers", [])]
                cfg.networks.append(NetworkConfig(servers=servers, **{a: b for a, b in n.items() if a in known}))
        elif k in Config.__dataclass_fields__:
            setattr(cfg, k, v)
    return cfg


def load(directory: Path) -> Config:
    path = directory / "config.json"
    if path.exists():
        try:
            return _from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError) as e:
            # keep the broken file for inspection rather than overwriting it on next save
            path.replace(path.with_suffix(".broken.json"))
            print(f"BChat: settings could not be read, saved aside: {e}")
    return Config()


def save(cfg: Config, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / "config.json.tmp"
    tmp.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    tmp.replace(directory / "config.json")
