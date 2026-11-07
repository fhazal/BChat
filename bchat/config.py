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
    check: str = _m["sapphire"]        # ticked checkbox: this box with a dark tick (was only a lighter grey)
    marking_fg: str = "#ffffff"        # selected text
    self_nick: str = _m["teal"]        # your own nick, no brackets (user's pick)
    self_text: str = "#bcdaeb"         # your own text: text with a light teal tint (30 % teal)
    server_mark: str = _m["mauve"]     # server tab: "*" before server lines (XChat %C22 purple)
    connect: str = _m["mauve"]         # Connecting / Connected lines, whole line (XChat %C22)
    send_bracket: str = _m["green"]    # >nick< you sent (XChat %C19)
    notice_bracket: str = _m["blue"]   # -nick- notice dashes (XChat %C28)
    notice_nick: str = _m["pink"]      # -nick- notice name (XChat %C29)
    motd_mark: str = _m["overlay0"]    # server tab: "-" before MOTD lines
    motd_text: str = _m["subtext1"]
    ssl_mark: str = _m["sapphire"]     # server tab: "SSL" before certificate lines
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
    stamp_format: str = "[%H:%M]"
    line_spacing: int = 112        # percent
    max_lines: int = 5000          # scrollback per tab
    marker_line: bool = True       # red "read up to here" line
    rank_lights: str = "off"       # off | lights | slot (lights + empty slot so text lines up)
    color_nicks: bool = False      # each nick a fixed colour, XChat's "Colored nick names"
    strip_colors: bool = False     # drop mIRC colours from what people say
    chat_bg_image: str = ""        # Text box: background image
    # Input box
    input_chat_font: bool = False
    auto_complete: bool = False    # "nic: hi" becomes "nickname: hi" on Enter, without Tab
    nick_suffix: str = ":"
    complete_sort: str = "alpha"   # alpha | recent
    spell_check: bool = False      # English only
    spell_words: list[str] = field(default_factory=list)
    percent_ascii: bool = False    # %065 becomes A
    percent_codes: bool = False    # %B %C %U %O %R become format codes
    # User list
    ul_hosts: bool = False
    ul_chat_font: bool = False
    ul_sort: int = 0               # 0 A-Z ops first, 1 A-Z, 2 Z-A ops last, 3 Z-A, 4 unsorted
    ul_side: str = "right"         # right | left
    away_track: bool = True
    away_limit: int = 300          # channels bigger than this aren't polled
    ul_double: str = "QUOTE WHOIS %s %s"
    # Alerts: each list is [channel message, private message, highlighted]
    alert_balloon: list[bool] = field(default_factory=lambda: [False, False, False])
    alert_tray: list[bool] = field(default_factory=lambda: [False, True, True])
    alert_flash: list[bool] = field(default_factory=lambda: [False, True, True])
    alert_beep: list[bool] = field(default_factory=lambda: [False, False, False])
    tray_icon: bool = False
    hilite_no: str = ""            # nicks never highlighted
    hilite_always: str = ""        # nicks always highlighted
    # General
    announce_away: bool = False
    away_once: bool = True
    auto_unaway: bool = False
    # Logging
    text_replay: bool = False      # show the last session's scrollback when a tab opens
    log_all: bool = False
    log_mask: str = "%n-%c.log"
    log_stamps: bool = True
    log_stamp_format: str = "%b %d %H:%M:%S "
    # Sound: event -> .wav file
    sounds: dict = field(default_factory=dict)
    # Network setup
    bind_host: str = ""
    proxy_type: str = "none"       # none | socks5 | http
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_auth: bool = False
    proxy_user: str = ""
    proxy_password: str = ""
    # File transfers
    dcc_auto: int = 0              # 0 ask, 1 auto accept (never for programs)
    dcc_dir: str = ""
    dcc_done_dir: str = ""
    dcc_with_nick: bool = False
    dcc_fill_spaces: bool = True
    dcc_ip: str = ""
    dcc_ip_from_server: bool = True
    dcc_first_port: int = 0
    dcc_last_port: int = 0
    dcc_max_send: int = 0          # KB/s, 0 = no limit
    dcc_max_get: int = 0
    dcc_max_send_all: int = 0
    dcc_max_get_all: int = 0
    dcc_open_send: bool = True
    dcc_open_recv: bool = True
    dcc_open_chat: bool = True
    # Channel switcher
    tab_layout: str = "tree"       # tree | tabs
    tab_pos: str = "left"          # left | right | top | bottom | hidden
    tab_sort: bool = False
    tab_small: bool = False
    tab_trunc: int = 0             # shorten labels to this many letters, 0 = never
    tab_focus: int = 2             # new tabs take the front: 0 never, 1 always, 2 only requested
    notices_tab: bool = False      # server notices in their own tab
    auto_dialog: bool = True       # a new tab on a private message
    dialogs_in_windows: bool = False
    # Interface extras
    meters: int = 0                # 0 off, 1 graph, 2 text, 3 both
    opacity: int = 100
    start_with_windows: bool = False
    start_minimized: bool = False
    close_to_tray: bool = False
    # Settings > Advanced lists. None means the defaults, until the user saves their own
    user_commands: list | None = None
    auto_replace: list | None = None
    ctcp_replies: list | None = None
    url_handlers: list | None = None
    dlg_buttons: list | None = None
    ul_buttons: list | None = None
    ul_popup: list | None = None
    text_events: dict = field(default_factory=dict)     # event -> format, only where it differs from the default
    keys: dict = field(default_factory=dict)            # menu command -> key, only where it differs
    key_commands: list = field(default_factory=list)    # [key, command]
    show_ul_buttons: bool = False
    show_mode_buttons: bool = False
    # Tool windows
    ignore_kinds: dict = field(default_factory=dict)   # mask -> letters of C P N T D I U; missing means C P N T D I
    friends: list[str] = field(default_factory=list)
    friend_nets: dict = field(default_factory=dict)    # nick -> "net1,net2", empty for all
    whois_on_notify: bool = False
    notify_timeout: int = 120
    url_grabber: bool = True
    url_limit: int = 100
    # Advanced
    reconnect_delay: int = 10
    raw_modes: bool = False
    hide_joinpart: bool = False
    nick_width: int = 0  # unused since 0.1.0-TEST9 (no nick column); kept so older settings load
    win_x: int = -1
    win_y: int = -1
    win_maximized: bool = False
    pane_left: int = 104
    pane_right: int = 124
    ignores: list[str] = field(default_factory=list)
    log_tabs: list[str] = field(default_factory=list)
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
