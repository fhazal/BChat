"""BChat settings, kept as JSON in %APPDATA%\\BChat. Passwords go to Windows Credential Manager (vault.py), not this file."""
from __future__ import annotations

import json
import os
import random
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
# --- added 2026-11-08 (user's pick). Same 26 Catppuccin role names; official colours first, and where a theme has no
# colour for a role (in-between greys, a darker sidebar shade) one is picked between its own neighbours.
# Tokyo Night, https://github.com/enkia/tokyo-night-vscode-theme themes/*.json (MIT)
TOKYO_NIGHT = dict(rosewater="#f7768e", flamingo="#ff9e64", pink="#bb9af7", mauve="#9d7cd8", red="#f7768e", maroon="#db4b4b",
                   peach="#ff9e64", yellow="#e0af68", green="#9ece6a", teal="#73daca", sky="#7dcfff", sapphire="#2ac3de",
                   blue="#7aa2f7", lavender="#9abdf5", text="#c0caf5", subtext1="#a9b1d6", subtext0="#9aa5ce", overlay2="#787c99",
                   overlay1="#646e9c", overlay0="#545c7e", surface2="#515670", surface1="#363b54", surface0="#1e202e",
                   base="#1a1b26", mantle="#16161e", crust="#101014")
TOKYO_NIGHT_LIGHT = dict(rosewater="#8c4351", flamingo="#965027", pink="#7b43ba", mauve="#65359d", red="#8c4351", maroon="#942f2f",
                         peach="#965027", yellow="#8f5e15", green="#385f0d", teal="#33635c", sky="#006c86", sapphire="#0f4b6e",
                         blue="#2959aa", lavender="#3e6396", text="#343b58", subtext1="#40434f", subtext0="#484c61", overlay2="#5c5f70",
                         overlay1="#707280", overlay0="#909296", surface2="#acb0bf", surface1="#cdced1", surface0="#dcdee3",
                         base="#e6e7ed", mantle="#d6d8df", crust="#c1c2c7")
# Nord, https://github.com/nordtheme/nord src/nord.css (MIT): nord0-15; darker sidebar shades and in-between greys picked
NORD = dict(rosewater="#d08770", flamingo="#d08770", pink="#b48ead", mauve="#b48ead", red="#bf616a", maroon="#bf616a",
            peach="#d08770", yellow="#ebcb8b", green="#a3be8c", teal="#8fbcbb", sky="#88c0d0", sapphire="#81a1c1",
            blue="#81a1c1", lavender="#88c0d0", text="#eceff4", subtext1="#e5e9f0", subtext0="#d8dee9", overlay2="#aeb6c5",
            overlay1="#8c96a9", overlay0="#6c788f", surface2="#4c566a", surface1="#434c5e", surface0="#3b4252",
            base="#2e3440", mantle="#2a2f3a", crust="#242933")
# Gruvbox, https://github.com/morhetz/gruvbox colors/gruvbox.vim (MIT/X11): bright accents on dark, faded ones on light
GRUVBOX_DARK = dict(rosewater="#d3869b", flamingo="#fe8019", pink="#d3869b", mauve="#d3869b", red="#fb4934", maroon="#cc241d",
                    peach="#fe8019", yellow="#fabd2f", green="#b8bb26", teal="#8ec07c", sky="#83a598", sapphire="#83a598",
                    blue="#83a598", lavender="#83a598", text="#ebdbb2", subtext1="#d5c4a1", subtext0="#bdae93", overlay2="#a89984",
                    overlay1="#928374", overlay0="#7c6f64", surface2="#665c54", surface1="#504945", surface0="#3c3836",
                    base="#282828", mantle="#1d2021", crust="#161819")
GRUVBOX_LIGHT = dict(rosewater="#9d0006", flamingo="#af3a03", pink="#8f3f71", mauve="#8f3f71", red="#9d0006", maroon="#cc241d",
                     peach="#af3a03", yellow="#b57614", green="#79740e", teal="#427b58", sky="#076678", sapphire="#076678",
                     blue="#076678", lavender="#076678", text="#282828", subtext1="#3c3836", subtext0="#504945", overlay2="#665c54",
                     overlay1="#7c6f64", overlay0="#928374", surface2="#a89984", surface1="#bdae93", surface0="#d5c4a1",
                     base="#fbf1c7", mantle="#f2e5bc", crust="#ebdbb2")
# Rosé Pine, https://github.com/rose-pine/palette palette.json (MIT). It has no green: foam (its cyan) takes that place,
# as in Rosé Pine's own themes. Highlight greys and darker sidebar shades picked between its own colours.
ROSE_PINE = dict(rosewater="#ebbcba", flamingo="#ebbcba", pink="#ebbcba", mauve="#c4a7e7", red="#eb6f92", maroon="#eb6f92",
                 peach="#ea9a97", yellow="#f6c177", green="#9ccfd8", teal="#9ccfd8", sky="#9ccfd8", sapphire="#3e8fb0",
                 blue="#3e8fb0", lavender="#c4a7e7", text="#e0def4", subtext1="#b8b5d0", subtext0="#908caa", overlay2="#7f7b98",
                 overlay1="#6e6a86", overlay0="#524f67", surface2="#403d52", surface1="#26233a", surface0="#1f1d2e",
                 base="#191724", mantle="#16141f", crust="#12101a")
ROSE_PINE_DAWN = dict(rosewater="#d7827e", flamingo="#d7827e", pink="#d7827e", mauve="#907aa9", red="#b4637a", maroon="#b4637a",
                      peach="#d7827e", yellow="#ea9d34", green="#56949f", teal="#56949f", sky="#56949f", sapphire="#286983",
                      blue="#286983", lavender="#907aa9", text="#464261", subtext1="#575279", subtext0="#6e6a86", overlay2="#797593",
                      overlay1="#8a859c", overlay0="#9893a5", surface2="#cecacd", surface1="#dfdad9", surface0="#f2e9e1",
                      base="#faf4ed", mantle="#f4ede8", crust="#ebe2da")
# Solarized, https://github.com/altercation/solarized README (MIT): base03-base3 and the 8 accents, the same on dark and light
SOLARIZED_DARK = dict(rosewater="#d33682", flamingo="#cb4b16", pink="#d33682", mauve="#6c71c4", red="#dc322f", maroon="#d33682",
                      peach="#cb4b16", yellow="#b58900", green="#859900", teal="#2aa198", sky="#2aa198", sapphire="#268bd2",
                      blue="#268bd2", lavender="#6c71c4", text="#93a1a1", subtext1="#8b9b9c", subtext0="#839496", overlay2="#74898f",
                      overlay1="#657b83", overlay0="#586e75", surface2="#2d4f57", surface1="#1c4450", surface0="#073642",
                      base="#002b36", mantle="#00252e", crust="#001e26")
SOLARIZED_LIGHT = dict(rosewater="#d33682", flamingo="#cb4b16", pink="#d33682", mauve="#6c71c4", red="#dc322f", maroon="#d33682",
                       peach="#cb4b16", yellow="#b58900", green="#859900", teal="#2aa198", sky="#2aa198", sapphire="#268bd2",
                       blue="#268bd2", lavender="#6c71c4", text="#073642", subtext1="#586e75", subtext0="#657b83", overlay2="#74898f",
                       overlay1="#839496", overlay0="#93a1a1", surface2="#c7c1ad", surface1="#d9d2bd", surface0="#e6dfca",
                       base="#fdf6e3", mantle="#f5efdc", crust="#eee8d5")
# XChat Classic: XChat 2.8.8 src/fe-gtk/palette.c (GPL-2.0, like BChat): black on #f0f0f0, its own 16 IRC colours,
# selection blue #356ec1, marker red #cc1010, tab colours dark red (new data) and blue (nick mentioned)
XCHAT_CLASSIC = dict(rosewater="#c33b3b", flamingo="#c73232", pink="#b037b0", mauve="#80267f", red="#cc1010", maroon="#c73232",
                     peach="#990000", yellow="#9c6c00", green="#2a8c2a", teal="#195555", sky="#2e8c74", sapphire="#356ec1",
                     blue="#0000ff", lavender="#3535b3", text="#000000", subtext1="#333333", subtext0="#4c4c4c", overlay2="#666666",
                     overlay1="#808080", overlay0="#959595", surface2="#b0b0b0", surface1="#c4c4c4", surface0="#d6d6d6",
                     base="#f0f0f0", mantle="#e6e6e6", crust="#d9d9d9")
# mIRC Modern: mIRC's own "mIRC Modern" colour scheme (mirc.ini) on white with mIRC's standard 16 colours
MIRC_MODERN = dict(rosewater="#9c009c", flamingo="#fc7f00", pink="#9c009c", mauve="#9c009c", red="#ff0000", maroon="#7f0000",
                   peach="#fc7f00", yellow="#c86400", green="#009300", teal="#009393", sky="#009393", sapphire="#0000fc",
                   blue="#0000fc", lavender="#00007f", text="#000000", subtext1="#333333", subtext0="#555555", overlay2="#6a6a6a",
                   overlay1="#7f7f7f", overlay0="#a0a0a0", surface2="#b4b4b4", surface1="#c8c8c8", surface0="#dadada",
                   base="#ffffff", mantle="#f0f0f0", crust="#e3e3e3")

# The client themes keep their own 16 IRC colours (XChat's palette.c; mIRC's standard palette), not ones made from roles
IRC_COLOURS = {
    "XChat Classic": ["#cccccc", "#000000", "#3535b3", "#2a8c2a", "#c33b3b", "#c73232", "#80267f", "#66361f",
                      "#d9a641", "#3dcc3d", "#195555", "#2e8c74", "#4545e6", "#b037b0", "#4c4c4c", "#959595"],
    "mIRC Modern": ["#ffffff", "#000000", "#00007f", "#009300", "#ff0000", "#7f0000", "#9c009c", "#fc7f00",
                    "#ffff00", "#00fc00", "#009393", "#00ffff", "#0000fc", "#ff00ff", "#7f7f7f", "#d2d2d2"],
}
# ...and a few event colours of their own: mIRC Modern shows topics and joins green, own text black, notices maroon
THEME_FIELDS = {
    "XChat Classic": dict(nick="#000000", self_nick="#000000", self_text="#000000", marker="#cc1010", topic="#000000"),
    "mIRC Modern": dict(nick="#000000", self_nick="#000000", self_text="#000000", topic="#009300", join="#009300",
                        notice_nick="#7f0000", notice_bracket="#7f0000"),
}

DARK_THEMES = ["Catppuccin Mocha", "Catppuccin Macchiato", "Catppuccin Frappé", "One Dark Pro", "Dracula", "Tokyo Night",
               "Nord", "Gruvbox Dark", "Rosé Pine", "Solarized Dark"]
LIGHT_THEME_ORDER = ["Catppuccin Latte", "Tokyo Night Light", "Gruvbox Light", "Rosé Pine Dawn", "Solarized Light",
                     "XChat Classic", "mIRC Modern"]
PALETTES = {**CATPPUCCIN, "One Dark Pro": ONE_DARK_PRO, "Dracula": DRACULA, "Tokyo Night": TOKYO_NIGHT, "Nord": NORD,
            "Gruvbox Dark": GRUVBOX_DARK, "Rosé Pine": ROSE_PINE, "Solarized Dark": SOLARIZED_DARK,
            "Tokyo Night Light": TOKYO_NIGHT_LIGHT, "Gruvbox Light": GRUVBOX_LIGHT, "Rosé Pine Dawn": ROSE_PINE_DAWN,
            "Solarized Light": SOLARIZED_LIGHT, "XChat Classic": XCHAT_CLASSIC, "mIRC Modern": MIRC_MODERN}
LIGHT_THEMES = set(LIGHT_THEME_ORDER)
THEME_NAMES = DARK_THEMES + LIGHT_THEME_ORDER      # the picker shows them under "Dark" and "Light"
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
    allow_invalid_cert: bool = False   # new networks check certificates; older settings keep what they had
    cert_pins: list[str] = field(default_factory=list)   # SHA-256 of certificates the user chose to trust
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
    values = dict(
        name=name, window=p["mantle"], panel=p["base"], border=p["surface0"], text=p["text"], chat_bg=p["base"], chat_fg=p["text"],
        nick=p["lavender"], join=p["green"], topic=p["mauve"], highlight=p["yellow"], selected=p["surface2"], away=p["overlay1"],
        stamp=p["overlay0"], marker=p["red"], new_data=p["peach"], new_msg=p["red"], new_highlight=p["blue"], bar=p["crust"],
        popup=p["surface0"], thumb=p["surface1"], thumb_hover=p["surface2"], disabled=p["overlay0"], status_off=p["red"],
        status_connecting=p["yellow"], status_on=p["green"], status_op=p["sapphire"], status_lag=p["peach"], check=p["sapphire"],
        marking_fg=p["text"] if light else "#ffffff", self_nick=p["teal"], self_text=blend(p["text"], p["teal"], 0.3),
        server_mark=p["mauve"], connect=p["mauve"], send_bracket=p["green"], notice_bracket=p["blue"], notice_nick=p["pink"],
        motd_mark=p["overlay0"], motd_text=p["subtext1"], ssl_mark=p["sapphire"], title=p["pink"], muted=p["subtext0"],
        tree_line=p["surface2"], tree_box=p["overlay1"],
        palette=list(IRC_COLOURS.get(name) or irc_palette(p)))
    values.update(THEME_FIELDS.get(name, {}))       # the client themes' own event colours
    return Theme(**values)


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
    username: str = "bee"
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
    colors_exact: bool = False     # fixed (16-98) and hex text colours exactly as sent, even when hard to read
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
    alert_popup: list[bool] = field(default_factory=lambda: [False, True, True])   # BChat's own pop-up cards
    alert_tray: list[bool] = field(default_factory=lambda: [False, True, True])
    alert_flash: list[bool] = field(default_factory=lambda: [False, True, True])
    alert_beep: list[bool] = field(default_factory=lambda: [False, False, False])
    tray_icon: bool = False
    hilite_no: str = ""            # nicks never highlighted
    hilite_always: str = ""        # nicks always highlighted (old XChat list: moved into hl_rules on load)
    hl_on: bool = True             # mIRC's "Enable highlighting": the rules (your nick always highlights, as in XChat)
    hl_rules: list = field(default_factory=list)   # highlights.NEW_RULE dicts: match, on, where, colour, sound, flash, tip
    fav_notes: dict = field(default_factory=dict)  # Favourite Channels: "network/#chan" -> note
    fav_saved: list = field(default_factory=list)  # Favourite Channels not joined on connect: "network/#chan key"
    # Network > Local (mIRC's Connect > Local): the address DCC offers carry. dcc_ip is the typed IP.
    local_find: bool = True        # find it on connect
    local_show: bool = True        # print "Local host: name (ip)" in the server tab
    local_lookup: str = "server"   # normal (this PC) | server (USERIP/USERHOST) | website
    local_site: str = "icanhazip.com"
    local_host: str = ""           # typed host name, used to find the IP
    netlist_open: dict = field(default_factory=dict)   # Network List groups folded open: "mine", "popular"
    # General
    announce_away: bool = False
    away_once: bool = True
    auto_unaway: bool = False
    rejoin_on_kick: bool = False       # once, after 3 seconds
    whois_on_query: bool = True        # who someone is, at the top of a private chat they open
    # Logging
    text_replay: bool = False      # show the last session's scrollback when a tab opens
    log_all: bool = False
    log_mask: str = "%n-%c.log"
    log_split: str = "day"            # 0.3.0: "day", "month" or "none" (one file from log_mask)
    log_keep_days: int = 0            # delete dated logs older than this (0 = never)
    log_asked: bool = False           # the one-time "BChat will save your chats" question was answered
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
    slaps: list | None = None       # Slap! lines ([text] rows); None = the built-in list
    report_offer: bool = True       # offer a problem report after a crash, an error or a freeze
    my_reports: list = field(default_factory=list)   # reports this PC sent: {id, sig, kind, date}
    text_events: dict = field(default_factory=dict)     # event -> format, only where it differs from the default
    keys: dict = field(default_factory=dict)            # menu command -> key, only where it differs
    key_commands: list = field(default_factory=list)    # [key, command]
    show_ul_buttons: bool = False
    show_mode_buttons: bool = False
    # Tool windows
    ignore_kinds: dict = field(default_factory=dict)   # mask -> letters of C P N T D I U; missing means C P N T D I
    friends: list[str] = field(default_factory=list)
    friend_nets: dict = field(default_factory=dict)    # nick -> "net1,net2", empty for all
    sysinfo_line: str = ""             # /sysinfo template; empty = sysinfo.DEFAULT_LINE
    np_enabled: bool = False           # /np shares nothing until the user turns it on
    np_music_only: bool = True         # skip videos and anything Windows doesn't call music
    np_ask: bool = True                # show the line before it's sent
    np_line: str = ""                  # /np template; empty = nowplaying.DEFAULT_LINE
    np_players: dict = field(default_factory=dict)     # player id -> allowed (browsers start False)
    np_names: dict = field(default_factory=dict)       # player id -> name shown in Preferences
    np_announce: bool = False          # post each new song on its own, only in np_announce_in
    np_announce_in: str = ""           # "SkinIRC/#skinhead, #chat": the only channels announce posts to (no network = all)
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
    welcome_done: bool = False   # the first-start welcome window was answered (only shown with no networks)


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


SECRET_FIELDS = ("password", "sasl_password", "nickserv")


def _net_keys(networks) -> list[str]:
    """A key per network for its passwords: the name, with #2, #3 for repeated names."""
    seen: dict[str, int] = {}
    keys = []
    for n in networks:
        name = n["name"].lower() if isinstance(n, dict) else n.name.lower()
        seen[name] = seen.get(name, 0) + 1
        keys.append(name if seen[name] == 1 else f"{name}#{seen[name]}")
    return keys


def load(directory: Path) -> Config:
    path = directory / "config.json"
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            cfg = _from_dict(d)
            if "local_lookup" not in d and not cfg.dcc_ip_from_server:
                cfg.local_lookup = "normal"          # older settings: "Get my address from the IRC server" off
            from .highlights import migrate
            migrate(cfg)
        except (ValueError, TypeError) as e:
            # keep the broken file for inspection rather than overwriting it on next save
            path.replace(path.with_suffix(".broken.json"))
            print(f"BChat: settings could not be read, saved aside: {e}")
            return fresh_config()
        if d.get("secrets") == "vault":
            from . import vault
            text = vault.get(directory)
            if text is None:
                cfg.vault_missing = True      # the window says so: passwords need typing in again
            else:
                s = json.loads(text)
                for key, n in zip(_net_keys(cfg.networks), cfg.networks):
                    for f in SECRET_FIELDS:
                        setattr(n, f, s.get("networks", {}).get(key, {}).get(f, ""))
                cfg.proxy_password = s.get("proxy_password", "")
        return cfg
    return fresh_config()


def random_nick() -> str:
    """A new user's nickname until they pick one: Bee4821."""
    return f"Bee{random.randint(1000, 9999)}"


def fresh_config() -> Config:
    """First start: a random bee nick with its second and third choices (an XChat import may replace them)."""
    nick = random_nick()
    return Config(nick=nick, nick2=nick + "_", nick3=nick + "__")


def save(cfg: Config, directory: Path) -> None:
    """Settings to config.json, passwords to Windows Credential Manager. If Windows won't store them,
    they stay in the file as before rather than being lost."""
    from . import vault
    directory.mkdir(parents=True, exist_ok=True)
    d = asdict(cfg)
    secrets = {"networks": {}, "proxy_password": d.get("proxy_password", "")}
    for key, n in zip(_net_keys(d["networks"]), d["networks"]):
        found = {f: n.get(f, "") for f in SECRET_FIELDS if n.get(f)}
        if found:
            secrets["networks"][key] = found
    if not secrets["networks"] and not secrets["proxy_password"]:
        vault.clear(directory)              # nothing secret: no empty entry left in Credential Manager
        d["secrets"] = "none"
    elif vault.put(directory, json.dumps(secrets)):
        for n in d["networks"]:
            for f in SECRET_FIELDS:
                n[f] = ""
        d["proxy_password"] = ""
        d["secrets"] = "vault"
    else:
        d["secrets"] = "file"
    tmp = directory / "config.json.tmp"
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(directory / "config.json")
