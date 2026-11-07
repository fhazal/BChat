"""BChat settings, kept as JSON in %APPDATA%\\BChat. Network passwords are stored here as plain text, same as XChat."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Theme palettes. Every theme is described with Catppuccin's colour names, so one mapping (make_theme) serves them all.
# Catppuccin, https://github.com/catppuccin/palette palette.json (MIT)
CATPPUCCIN = {
    "Catppuccin Mocha": dict(rosewater="#f5e0dc", flamingo="#f2cdcd", pink="#f5c2e7", mauve="#cba6f7", red="#f38ba8", maroon="#eba0ac",
                             peach="#fab387", yellow="#f9e2af", green="#a6e3a1", teal="#94e2d5", sky="#89dceb", sapphire="#74c7ec",
                             blue="#89b4fa", lavender="#b4befe", text="#cdd6f4", subtext1="#bac2de", subtext0="#a6adc8", overlay2="#9399b2",
                             overlay1="#7f849c", overlay0="#6c7086", surface2="#585b70", surface1="#45475a", surface0="#313244",
                             base="#1e1e2e", mantle="#181825", crust="#11111b"),
    "Catppuccin Macchiato": dict(rosewater="#f4dbd6", flamingo="#f0c6c6", pink="#f5bde6", mauve="#c6a0f6", red="#ed8796", maroon="#ee99a0",
                                 peach="#f5a97f", yellow="#eed49f", green="#a6da95", teal="#8bd5ca", sky="#91d7e3", sapphire="#7dc4e4",
                                 blue="#8aadf4", lavender="#b7bdf8", text="#cad3f5", subtext1="#b8c0e0", subtext0="#a5adcb", overlay2="#939ab7",
                                 overlay1="#8087a2", overlay0="#6e738d", surface2="#5b6078", surface1="#494d64", surface0="#363a4f",
                                 base="#24273a", mantle="#1e2030", crust="#181926"),
    "Catppuccin Frappé": dict(rosewater="#f2d5cf", flamingo="#eebebe", pink="#f4b8e4", mauve="#ca9ee6", red="#e78284", maroon="#ea999c",
                              peach="#ef9f76", yellow="#e5c890", green="#a6d189", teal="#81c8be", sky="#99d1db", sapphire="#85c1dc",
                              blue="#8caaee", lavender="#babbf1", text="#c6d0f5", subtext1="#b5bfe2", subtext0="#a5adce", overlay2="#949cbb",
                              overlay1="#838ba7", overlay0="#737994", surface2="#626880", surface1="#51576d", surface0="#414559",
                              base="#303446", mantle="#292c3c", crust="#232634"),
    "Catppuccin Latte": dict(rosewater="#dc8a78", flamingo="#dd7878", pink="#ea76cb", mauve="#8839ef", red="#d20f39", maroon="#e64553",
                             peach="#fe640b", yellow="#df8e1d", green="#40a02b", teal="#179299", sky="#04a5e5", sapphire="#209fb5",
                             blue="#1e66f5", lavender="#7287fd", text="#4c4f69", subtext1="#5c5f77", subtext0="#6c6f85", overlay2="#7c7f93",
                             overlay1="#8c8fa1", overlay0="#9ca0b0", surface2="#acb0be", surface1="#bcc0cc", surface0="#ccd0da",
                             base="#eff1f5", mantle="#e6e9ef", crust="#dce0e8"),
}
# One Dark Pro, https://github.com/Binaryify/OneDark-Pro themes/OneDark-Pro.json (MIT): editor, side bar, input,
# list, focus, scrollbar and line number colours, the syntax colours and the cursor blue. The in-between greys
# (subtext, overlay 1-2) are picked between its text and comment colours.
ONE_DARK_PRO = dict(rosewater="#e06c75", flamingo="#e06c75", pink="#c678dd", mauve="#c678dd", red="#e06c75", maroon="#be5046",
                    peach="#d19a66", yellow="#e5c07b", green="#98c379", teal="#56b6c2", sky="#56b6c2", sapphire="#61afef",
                    blue="#61afef", lavender="#528bff", text="#abb2bf", subtext1="#9da5b4", subtext0="#8b929e", overlay2="#7f848e",
                    overlay1="#6b717d", overlay0="#5c6370", surface2="#4e5666", surface1="#3e4452", surface0="#2c313a",
                    base="#282c34", mantle="#21252b", crust="#1d1f23")
# Dracula, https://github.com/dracula/visual-studio-code src/dracula.yml (MIT): base, ansi and UI variant colours.
# Dracula has no blue: purple takes that place, as in Dracula's own themes. The in-between greys
# (subtext, overlay 1-2) are picked between its foreground and comment colours.
DRACULA = dict(rosewater="#ff79c6", flamingo="#ff92df", pink="#ff79c6", mauve="#bd93f9", red="#ff5555", maroon="#ff6e6e",
               peach="#ffb86c", yellow="#f1fa8c", green="#50fa7b", teal="#8be9fd", sky="#a4ffff", sapphire="#8be9fd",
               blue="#bd93f9", lavender="#d6acff", text="#f8f8f2", subtext1="#e2e2dc", subtext0="#c4c5c4", overlay2="#9da7c8",
               overlay1="#7f8ab6", overlay0="#6272a4", surface2="#44475a", surface1="#424450", surface0="#343746",
               base="#282a36", mantle="#21222c", crust="#191a21")
PALETTES = {**CATPPUCCIN, "One Dark Pro": ONE_DARK_PRO, "Dracula": DRACULA}
LIGHT_THEMES = {"Catppuccin Latte"}
THEME_NAMES = list(PALETTES)
MOCHA = CATPPUCCIN["Catppuccin Mocha"]
_m = MOCHA


def blend(a: str, b: str, k: float) -> str:
    """Colour a with k of colour b mixed in."""
    ca, cb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - k) + y * k):02x}" for x, y in zip(ca, cb))


def irc_palette(p: dict) -> list[str]:
    """IRC colour codes 0-15 in the theme's own shades. 1 is normally black, which can't be read on a dark chat,
    so it is the theme's dark grey (on a light theme, a light grey, and 0 is the dark text colour)."""
    return [p["text"], p["surface1"], p["blue"], p["green"], p["red"], p["maroon"], p["mauve"], p["peach"],
            p["yellow"], p["teal"], p["teal"], p["sky"], p["sapphire"], p["pink"], p["overlay1"], p["subtext0"]]


DEFAULT_PALETTE = irc_palette(MOCHA)


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
    name: str = "Catppuccin Mocha"   # the preset these colours came from (Custom when they differ)
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
    title: str = _m["pink"]            # big titles: About's BChat
    muted: str = _m["subtext0"]        # quiet text: taglines, notes
    tree_line: str = _m["surface2"]    # tree connector lines
    tree_box: str = _m["overlay1"]     # tree +/- boxes
    palette: list[str] = field(default_factory=lambda: list(DEFAULT_PALETTE))


def make_theme(name: str) -> Theme:
    """A preset theme. Mocha gives exactly the Theme() defaults, so older settings stay Mocha, not Custom."""
    p = PALETTES[name]
    light = name in LIGHT_THEMES
    return Theme(
        name=name, window=p["mantle"], panel=p["base"], border=p["surface0"], text=p["text"], chat_bg=p["base"], chat_fg=p["text"],
        nick=p["lavender"], join=p["green"], topic=p["mauve"], highlight=p["yellow"], selected=p["surface2"], away=p["overlay1"],
        stamp=p["overlay0"], marker=p["red"], new_data=p["peach"], new_msg=p["red"], new_highlight=p["blue"], bar=p["crust"],
        popup=p["surface0"], thumb=p["surface1"], thumb_hover=p["surface2"], disabled=p["overlay0"], status_off=p["red"],
        status_connecting=p["yellow"], status_on=p["green"], status_op=p["sapphire"], status_lag=p["peach"], check=p["sapphire"],
        marking_fg=p["text"] if light else "#ffffff", self_nick=p["teal"], self_text=blend(p["text"], p["teal"], 0.3),
        server_mark=p["mauve"], connect=p["mauve"], send_bracket=p["green"], notice_bracket=p["blue"], notice_nick=p["pink"],
        motd_mark=p["overlay0"], motd_text=p["subtext1"], ssl_mark=p["sapphire"], title=p["pink"], muted=p["subtext0"],
        tree_line=p["surface2"], tree_box=p["overlay1"], palette=irc_palette(p))


def theme_values(t: Theme) -> dict:
    d = asdict(t)
    d.pop("name")
    return d


def is_custom(t: Theme) -> bool:
    """True when the colours differ from the preset the theme is named after."""
    return t.name not in PALETTES or theme_values(t) != theme_values(make_theme(t.name))


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
    minimize_to_tray: bool = False
    ask_on_quit: bool = True
    # Updates
    update_check: bool = True          # at start-up, then once a day
    update_auto_download: bool = False
    update_test_versions: bool = False  # a TEST build always looks at test versions too
    update_last_check: float = 0.0
    update_ready_file: str = ""        # a checked download waiting to be installed
    update_ready_entry: dict | None = None
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
    pane_left: int = 180
    tree_widened: bool = False     # the folder tree needs more room: an old narrow width is widened once
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
