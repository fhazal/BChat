"""Settings > Preferences, laid out like XChat 2: Categories tree on the left, one page on the right.

Pages and options follow XChat 2.8.8's src/fe-gtk/setup.c. Every page works. Nothing changes until OK; Cancel and the red button throw the edits away.
"""
from __future__ import annotations

from dataclasses import fields

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFontDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox, QStackedWidget,
                               QHeaderView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .config import DARK_THEMES, LIGHT_THEME_ORDER, PALETTES, THEME_NAMES, Config, Theme, is_custom, make_theme
from .widgets import FramedDialog, icon

CATEGORIES = {"Interface": ["Text box", "Input box", "User list", "Channel switcher", "Colors"],
              "Chatting": ["Alerts", "Highlights", "General", "Logging", "Sound", "Now Playing", "Advanced"],
              "Network": ["Network setup", "Local", "File transfers"],
              "BChat": ["Updates"]}
BUILT = ("Text box", "Input box", "User list", "Channel switcher", "Colors", "Alerts", "Highlights", "General", "Logging", "Sound", "Now Playing", "Advanced", "Network setup", "Local", "File transfers", "Updates")
SWITCHER_POS = ("Left", "Right", "Top", "Bottom", "Hidden")
SORTS = ("A-Z, Ops first", "A-Z", "Z-A, Ops last", "Z-A", "Unsorted")
# Sound page: session notify event -> the name XChat's Sound page uses
SOUND_EVENTS = (("chan", "Channel Message"), ("hilight", "Channel Msg Hilight"), ("priv", "Private Message"), ("notice", "Notice"),
                ("join", "Join"), ("part", "Part"), ("kick", "Kick"), ("invite", "Invited"), ("connect", "Connected"), ("disconnect", "Disconnected"),
                ("friend", "Friend Online/Offline"))
RANK_CHOICES = (("off", "Off"), ("lights", "Lights before ranked nicks"),
                ("slot", "Lights, and an empty slot for others so all text lines up"))

# Colors page: (section, [(label, Theme field), ...]); mIRC colours are the palette list
COLOUR_ROWS = [
    ("Text Colors", [("Foreground:", "chat_fg"), ("Background:", "chat_bg")]),
    ("Marking Text", [("Foreground:", "marking_fg"), ("Background:", "selected")]),
    ("Your Lines", [("Your nick:", "self_nick"), ("Your text:", "self_text")]),
    ("Chat", [("Nick names:", "nick"), ("Mention:", "highlight"), ("Time stamps:", "stamp"), ("Join / part:", "join"),
              ("Topic, * lines:", "topic"), ("Notice -nick-:", "notice_nick"), ("Sent >nick<:", "send_bracket"),
              ("Connecting:", "connect")]),
    ("Interface Colors", [("New data:", "new_data"), ("Marker line:", "marker"), ("New message:", "new_msg"),
                          ("Away user:", "away"), ("Highlight:", "new_highlight")]),
]


def home_address(ip: str) -> bool:
    """192.168.x, 10.x, 172.16-31.x, 127.x, 100.64-127.x (carrier NAT): people on the internet can't reach it."""
    from ipaddress import ip_address
    try:
        a = ip_address(ip.strip())
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local or (a.version == 4 and a in __import__("ipaddress").ip_network("100.64.0.0/10"))


def _heading(text: str) -> QLabel:
    lab = QLabel(f"<b>{text}</b>")
    lab.setContentsMargins(0, 8, 0, 2)
    return lab


def _ink(colour: str) -> str:
    """Dark or light number text on a swatch, whichever reads."""
    return "#11111b" if QColor(colour).lightness() > 140 else "#cdd6f4"


class Swatch(QPushButton):
    def __init__(self, colour: str, label: str = "", parent=None):
        super().__init__(label, parent)
        self.setFixedSize(26, 22)
        self.setAutoDefault(False)
        self.set_colour(colour)

    def set_colour(self, colour: str) -> None:
        self.colour = QColor(colour).name()
        self.setToolTip(self.colour)
        self.setStyleSheet(f"QPushButton {{ background: {self.colour}; color: {_ink(self.colour)}; border: 1px solid "
                           f"#45475a; border-radius: 3px; font-size: 7pt; padding: 0; min-height: 0; }}"
                           f"QPushButton:hover {{ border: 1px solid #cdd6f4; }}")


class PreferencesDialog(FramedDialog):
    def __init__(self, win, start: str = "Text box"):
        super().__init__("BChat: Preferences", win)
        self.win = win
        self.cfg: Config = win.cfg
        self.theme = Theme(**{f.name: getattr(self.cfg.theme, f.name) for f in fields(Theme)})   # edited copy
        self.theme.palette = list(self.cfg.theme.palette)
        self.font_family, self.font_size = self.cfg.chat_font, self.cfg.chat_font_size
        self.resize(720, 580)
        row = QHBoxLayout()
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabel("Categories")
        self.tree.setFixedWidth(170)
        self.pages = QStackedWidget(self)
        self.page_of: dict[str, int] = {}
        self._items: dict[str, QTreeWidgetItem] = {}
        for top, kids in CATEGORIES.items():
            ti = QTreeWidgetItem([top])
            ti.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(ti)
            for k in kids:
                ki = QTreeWidgetItem([k])
                if k not in BUILT:
                    ki.setFlags(Qt.ItemFlag.NoItemFlags)    # greyed until it has a mockup, like the menus
                    ki.setToolTip(0, "Not built yet")
                ti.addChild(ki)
                self._items[k] = ki
            ti.setExpanded(True)
        right = QFrame(self)
        right.setFrameShape(QFrame.Shape.StyledPanel)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(self)
        self.title.setFixedHeight(30)
        self.title.setStyleSheet(f"background: {self.cfg.theme.bar}; border-bottom: 1px solid {self.cfg.theme.border};"
                                 f" padding-left: 6px; font-size: 11pt; font-weight: bold;")
        rl.addWidget(self.title)
        rl.addWidget(self.pages, 1)
        self.page_of["Text box"] = self.pages.addWidget(self._text_page())
        self.page_of["Colors"] = self.pages.addWidget(self._colors_page())
        for name, build in (("File transfers", self._files_page), ("Channel switcher", self._switcher_page), ("Input box", self._input_page), ("User list", self._userlist_page), ("Alerts", self._alerts_page), ("Highlights", self._highlights_page),
                            ("General", self._general_page), ("Logging", self._logging_page), ("Sound", self._sound_page), ("Now Playing", self._np_page),
                            ("Advanced", self._advanced_page), ("Network setup", self._network_page), ("Local", self._local_page), ("Updates", self._updates_page)):
            self.page_of[name] = self.pages.addWidget(build())
        row.addWidget(self.tree)
        row.addWidget(right, 1)
        self.body.addLayout(row, 1)
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        self.body.addWidget(line)
        bl = QHBoxLayout()
        bl.addStretch(1)
        cancel = QPushButton(icon("close-light"), "&Cancel", self)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(icon("save"), "&OK", self)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        bl.addWidget(cancel)
        bl.addWidget(ok)
        self.body.addLayout(bl)
        self.tree.currentItemChanged.connect(self._show)
        self.tree.setCurrentItem(self._items[start if start in BUILT else "Text box"])

    def _show(self, item, _prev=None) -> None:
        name = item.text(0) if item else ""
        if name in self.page_of:
            self.pages.setCurrentIndex(self.page_of[name])
            self.title.setText(name)

    def show_page(self, name: str) -> None:
        self.tree.setCurrentItem(self._items[name])

    # --- Text box ---------------------------------------------------------------------

    def _text_page(self) -> QWidget:
        c = self.cfg
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.addWidget(_heading("Text Box Appearance"))
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.addWidget(QLabel("Font:"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self.font_edit = QLineEdit(f"{self.font_family} {self.font_size}", page)
        self.font_edit.setReadOnly(True)
        g.addWidget(self.font_edit, 0, 1)
        browse = QPushButton("Browse...", page)
        browse.setAutoDefault(False)
        browse.clicked.connect(self._pick_font)
        g.addWidget(browse, 0, 2)
        g.addWidget(QLabel("Line spacing:"), 1, 0, Qt.AlignmentFlag.AlignRight)
        self.spacing = QSpinBox(page)
        self.spacing.setRange(100, 160)
        self.spacing.setSuffix(" %")
        self.spacing.setValue(c.line_spacing)
        g.addWidget(self.spacing, 1, 1, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(QLabel("Scrollback lines:"), 2, 0, Qt.AlignmentFlag.AlignRight)
        self.scrollback = QSpinBox(page)
        self.scrollback.setRange(100, 100000)
        self.scrollback.setSingleStep(500)
        self.scrollback.setValue(c.max_lines)
        g.addWidget(self.scrollback, 2, 1, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(QLabel("Background image:"), 3, 0, Qt.AlignmentFlag.AlignRight)
        self.bg_image = QLineEdit(c.chat_bg_image, page)
        g.addWidget(self.bg_image, 3, 1)
        pick = QPushButton("Browse...", page)
        pick.setAutoDefault(False)
        pick.clicked.connect(lambda: self._browse(self.bg_image, "Background image", "Images (*.png *.jpg *.jpeg *.bmp)"))
        g.addWidget(pick, 3, 2)
        lay.addLayout(g)
        lay.addWidget(_heading("Time Stamps"))
        h = QHBoxLayout()
        self.stamps = QCheckBox("Enable time stamps", page)
        self.stamps.setChecked(c.timestamps)
        h.addWidget(self.stamps)
        h.addSpacing(16)
        h.addWidget(QLabel("Format:"))
        self.stamp_fmt = QLineEdit(c.stamp_format, page)
        self.stamp_fmt.setFixedWidth(110)
        self.stamp_fmt.setToolTip("strftime codes: %H hour, %M minute, %S second, %d day, %m month")
        h.addWidget(self.stamp_fmt)
        h.addStretch(1)
        lay.addLayout(h)
        lay.addWidget(_heading("Marker Line"))
        self.marker = QCheckBox("Show marker line (where you stopped reading)   Ctrl+M clears it", page)
        self.marker.setChecked(c.marker_line)
        lay.addWidget(self.marker)
        lay.addWidget(_heading("Nick Names"))
        lay.addWidget(QLabel("Rank light before nicks in chat:"))
        self.rank_group = QButtonGroup(page)
        self.rank_buttons: dict[str, QRadioButton] = {}
        for key, text in RANK_CHOICES:
            r = QRadioButton(text, page)
            r.setChecked(c.rank_lights == key)
            self.rank_group.addButton(r)
            self.rank_buttons[key] = r
            w = QHBoxLayout()
            w.addSpacing(18)
            w.addWidget(r)
            w.addStretch(1)
            lay.addLayout(w)
        self.color_nicks = QCheckBox("Colored nick names (each person always gets the same colour)", page)
        self.color_nicks.setChecked(c.color_nicks)
        lay.addWidget(self.color_nicks)
        lay.addWidget(_heading("Text"))
        self.strip = QCheckBox("Strip mIRC colours from what people say", page)
        self.strip.setChecked(c.strip_colors)
        lay.addWidget(self.strip)
        self.colors_exact = QCheckBox("Show colours exactly as sent, even when hard to read", page)
        self.colors_exact.setToolTip("Off: BChat makes faint text colours (mIRC colours 16-98 and hex) just light or "
                                     "dark enough to read on your theme, keeping their hue. Backgrounds never change.")
        self.colors_exact.setChecked(c.colors_exact)
        self.colors_exact.setEnabled(not c.strip_colors)        # nothing to show when colours are stripped
        self.strip.toggled.connect(lambda on: self.colors_exact.setEnabled(not on))
        lay.addWidget(self.colors_exact)
        self.short_joins = self._check(lay, "Short join and part lines", c.short_joins,
                                       "Leaves out the address. Hover a nick in the nick list to see it.")
        lay.addStretch(1)
        return page

    def _browse(self, edit: QLineEdit, title: str, pattern: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, edit.text(), pattern)
        if path:
            edit.setText(path)

    # small helpers so each page reads like XChat's table in setup.c

    def _new_page(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 6, 14, 6)
        return page, lay

    def _check(self, lay, text: str, on: bool, tip: str = "") -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(on)
        if tip:
            box.setToolTip(tip)
        lay.addWidget(box)
        return box

    def _entry(self, grid: QGridLayout, row: int, label: str, value: str, secret: bool = False) -> QLineEdit:
        grid.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        edit = QLineEdit(value)
        if secret:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(edit, row, 1)
        return edit

    def _number(self, grid: QGridLayout, row: int, label: str, value: int, low: int, high: int, suffix: str = "") -> QSpinBox:
        grid.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(suffix)
        grid.addWidget(spin, row, 1, Qt.AlignmentFlag.AlignLeft)
        return spin

    def _menu(self, grid: QGridLayout, row: int, label: str, items, value: int) -> QComboBox:
        grid.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        box = QComboBox()
        box.addItems(list(items))
        box.setCurrentIndex(value)
        grid.addWidget(box, row, 1, Qt.AlignmentFlag.AlignLeft)
        return box

    # --- Input box ----------------------------------------------------------------------

    def _input_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Input box"))
        self.input_font = self._check(lay, "Use the Text box font", c.input_chat_font)
        self.spell = self._check(lay, "Spell checking (English)", c.spell_check, "Right-click a marked word for suggestions")
        self.send_typing = self._check(lay, "Let others see when I'm typing", c.send_typing,
                                       "Only on servers that support it (IRCv3 +typing). Never in the server tab.")
        lay.addWidget(_heading("Nick Completion"))
        self.auto_complete = self._check(lay, "Automatic nick completion (without TAB key)", c.auto_complete,
                                         'Typing "fha: hi" sends "Fhazal: hi" when only one nick fits')
        g = QGridLayout()
        self.suffix = self._entry(g, 0, "Nick completion suffix:", c.nick_suffix)
        self.suffix.setFixedWidth(60)
        g.setAlignment(self.suffix, Qt.AlignmentFlag.AlignLeft)
        self.comp_sort = self._menu(g, 1, "Nick completion sorted:", ("A-Z", "Last-spoke order"), 1 if c.complete_sort == "recent" else 0)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("Input Box Codes"))
        self.pct_ascii = self._check(lay, "Interpret %nnn as an ASCII value", c.percent_ascii)
        self.pct_codes = self._check(lay, "Interpret %C, %B as Color, Bold etc", c.percent_codes)
        lay.addStretch(1)
        return page

    # --- User list ----------------------------------------------------------------------

    def _userlist_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("User List"))
        self.ul_hosts = self._check(lay, "Show hostnames in user list", c.ul_hosts)
        self.ul_font = self._check(lay, "Use the Text box font", c.ul_chat_font)
        g = QGridLayout()
        self.ul_sort = self._menu(g, 0, "User list sorted by:", SORTS, c.ul_sort)
        self.ul_side = self._menu(g, 1, "Show user list at:", ("Right", "Left"), 1 if c.ul_side == "left" else 0)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("Away tracking"))
        self.away_track = self._check(lay, "Track the Away status of users and mark them in a different color", c.away_track)
        g = QGridLayout()
        self.away_limit = self._number(g, 0, "On channels smaller than:", c.away_limit, 1, 100000)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("Action Upon Double Click"))
        g = QGridLayout()
        self.ul_double = self._entry(g, 0, "Execute command:", c.ul_double)
        lay.addLayout(g)
        lay.addStretch(1)
        return page

    # --- Channel switcher ---------------------------------------------------------------

    def _switcher_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Channel Switcher"))
        g = QGridLayout()
        self.sw_type = self._menu(g, 0, "Switcher type:", ("Tree", "Tabs"), 1 if c.tab_layout == "tabs" else 0)
        self.sw_pos = self._menu(g, 1, "Show channel switcher at:", SWITCHER_POS, [p.lower() for p in SWITCHER_POS].index(c.tab_pos))
        self.sw_focus = self._menu(g, 2, "Focus new tabs:", ("Never", "Always", "Only requested tabs"), c.tab_focus)
        self.sw_trunc = self._number(g, 3, "Shorten tab labels to:", c.tab_trunc, 0, 99, " letters")
        self.sw_trunc.setSpecialValueText("Never")
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        self.sw_notices = self._check(lay, "Open an extra tab for server notices", c.notices_tab)
        self.sw_dialog = self._check(lay, "Open a new tab when you receive a private message", c.auto_dialog)
        self.sw_sort = self._check(lay, "Sort tabs in alphabetical order", c.tab_sort)
        self.sw_small = self._check(lay, "Smaller text", c.tab_small)
        lay.addWidget(_heading("Tabs or Windows"))
        g = QGridLayout()
        self.sw_windows = self._menu(g, 0, "Open dialogs in:", ("Tabs", "Windows"), 1 if c.dialogs_in_windows else 0)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addStretch(1)
        return page

    # --- Alerts -------------------------------------------------------------------------

    def _alerts_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Alerts"))
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        for col, head in enumerate(("Channel Message", "Private Message", "Highlighted Message"), 1):
            g.addWidget(QLabel(head), 0, col, Qt.AlignmentFlag.AlignCenter)
        self.alert_boxes = {}
        for row, (key, label) in enumerate((("alert_popup", "Show pop-up notifications on:"), ("alert_tray", "Blink tray icon on:"),
                                            ("alert_flash", "Blink task bar on:"), ("alert_beep", "Make a beep sound on:")), 1):
            g.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
            boxes = []
            for col in range(3):
                box = QCheckBox()
                box.setChecked(getattr(c, key)[col])
                g.addWidget(box, row, col + 1, Qt.AlignmentFlag.AlignCenter)
                boxes.append(box)
            self.alert_boxes[key] = boxes
        g.setColumnStretch(4, 1)
        lay.addLayout(g)
        hint = QLabel("Words and nicks to highlight are on Chatting > Highlights.")
        hint.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(hint)
        from .config import POPUP_MORE, POPUP_TIMES
        lay.addWidget(_heading("Also show a pop-up when"))
        self.popup_more = {}
        for key, label in POPUP_MORE:
            self.popup_more[key] = self._check(lay, label, c.popup_more.get(key, False))
        g2 = QGridLayout()
        g2.setHorizontalSpacing(8)
        secs = [s for s, _ in POPUP_TIMES]
        self.popup_time = self._menu(g2, 0, "Keep pop-ups on screen for:", [t for _, t in POPUP_TIMES],
                                     secs.index(c.popup_seconds) if c.popup_seconds in secs else 1)
        g2.setColumnStretch(2, 1)
        lay.addLayout(g2)
        row = QHBoxLayout()
        row.addWidget(QLabel("Sound with pop-ups:"))
        self.popup_sound = QComboBox()
        self.popup_sound.addItems(["None", "Soft chime", "Bee buzz"])
        self.popup_sound.setCurrentIndex(0 if not c.popup_sound else 2 if c.popup_sound_name == "bee" else 1)
        self.popup_sound.setToolTip("One short sound, at most once every 10 seconds. Quiet during full-screen games "
                                    "and Do Not Disturb. A sound you picked on the Sound page plays instead.")
        row.addWidget(self.popup_sound)
        self.popup_sound_try = QPushButton(icon("play"), "", objectName="compact")
        self.popup_sound_try.setToolTip("Play it now")
        self.popup_sound_try.setAutoDefault(False)
        self.popup_sound_try.clicked.connect(
            lambda: self.win.play_soft_chime(force=True, name="bee" if self.popup_sound.currentIndex() == 2 else "soft"))
        row.addWidget(self.popup_sound_try)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_heading("Tray icon"))
        self.tray_icon = self._check(lay, "Enable system tray icon", c.tray_icon)
        g3 = QGridLayout()
        g3.setHorizontalSpacing(8)
        self.tray_click = self._menu(g3, 0, "Open BChat with:", ["One click", "Double-click"], 1 if c.tray_click == "double" else 0)
        g3.setColumnStretch(2, 1)
        lay.addLayout(g3)
        self.tray_list = self._check(lay, "List my channels and private chats in the tray menu", c.tray_list,
                                     "Bold with a number = unread lines, @ = your nick was said")
        lay.addStretch(1)
        return page

    # --- Highlights (mIRC's Highlight list) -------------------------------------------------

    def _highlights_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Highlight Rules"))
        self.hl_on = self._check(lay, "Enable highlighting", c.hl_on,
                                 "Your nick always highlights. This turns the rules below on or off, as in mIRC")
        self.hl_rules = [dict(r) for r in c.hl_rules]
        self.hl_list = QTreeWidget()
        self.hl_list.setRootIsDecorated(False)
        self.hl_list.setHeaderLabels(["Highlight", "Match on", "From", "Colour", "Sound"])
        for col, w in ((0, 128), (1, 62), (2, 100), (3, 46)):
            self.hl_list.setColumnWidth(col, w)
        self.hl_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hl_list.setFixedHeight(160)
        self.hl_list.itemDoubleClicked.connect(lambda *_: self._hl_edit())
        row = QHBoxLayout()
        row.addWidget(self.hl_list, 1)
        col = QVBoxLayout()
        self.hl_add = QPushButton(icon("new"), "Add...", objectName="compact")
        self.hl_add.clicked.connect(lambda: self._hl_edit(new=True))
        self.hl_edit = QPushButton(icon("edit"), "Edit...", objectName="compact")
        self.hl_edit.clicked.connect(lambda: self._hl_edit())
        self.hl_remove = QPushButton(icon("close-light"), "Remove", objectName="compact")
        self.hl_remove.clicked.connect(self._hl_remove)
        self.hl_up = QPushButton(icon("up"), "Up", objectName="compact")
        self.hl_up.clicked.connect(lambda: self._hl_move(-1))
        self.hl_down = QPushButton(icon("down"), "Down", objectName="compact")
        self.hl_down.clicked.connect(lambda: self._hl_move(1))
        for b in (self.hl_add, self.hl_edit, self.hl_remove, self.hl_up, self.hl_down):
            col.addWidget(b)
        col.addStretch(1)
        row.addLayout(col)
        lay.addLayout(row)
        self.hl_list.currentItemChanged.connect(lambda *_: self._hl_buttons())
        self._hl_fill()
        hint = QLabel("Your nick always highlights. Wildcards: restart* matches restarting. The first rule that matches wins.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(hint)
        lay.addWidget(_heading("Never Highlight"))
        g = QGridLayout()
        self.hl_no = self._entry(g, 0, "Nick names:", c.hilite_no)
        self.hl_no.setPlaceholderText("*Serv, Global")
        lay.addLayout(g)
        n = QLabel("Messages from these nicks never highlight you, not even your nick. Commas between, wildcards work.")
        n.setWordWrap(True)
        n.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(n)
        lay.addStretch(1)
        return page

    def _hl_fill(self, select: int = -1) -> None:
        from .highlightdialog import rule_row, swatch
        self.hl_list.clear()
        for r in self.hl_rules:
            it = QTreeWidgetItem(rule_row(self.cfg.theme, r))
            it.setIcon(3, swatch(self.cfg.theme, r.get("colour", "")))
            self.hl_list.addTopLevelItem(it)
        s = getattr(self.win, "session", None)
        own = QTreeWidgetItem([f"{s.nick if s is not None else self.cfg.nick} (your nick)", "Message", "Everywhere", "", "Default"])
        own.setIcon(3, swatch(self.cfg.theme, ""))
        own.setFlags(Qt.ItemFlag.ItemIsEnabled)
        for i in range(5):
            own.setForeground(i, QColor(self.cfg.theme.muted))
        own.setToolTip(0, "Always a highlight. Its sound and alerts are on the Alerts and Sound pages")
        self.hl_list.addTopLevelItem(own)
        if 0 <= select < len(self.hl_rules):
            self.hl_list.setCurrentItem(self.hl_list.topLevelItem(select))
        self._hl_buttons()

    def _hl_index(self) -> int:
        it = self.hl_list.currentItem()
        i = self.hl_list.indexOfTopLevelItem(it) if it is not None else -1
        return i if 0 <= i < len(self.hl_rules) else -1

    def _hl_buttons(self) -> None:
        i = self._hl_index()
        self.hl_edit.setEnabled(i >= 0)
        self.hl_remove.setEnabled(i >= 0)
        self.hl_up.setEnabled(i > 0)
        self.hl_down.setEnabled(0 <= i < len(self.hl_rules) - 1)

    def _hl_edit(self, new: bool = False) -> None:
        from .highlightdialog import HighlightDialog
        i = -1 if new else self._hl_index()
        if not new and i < 0:
            return
        d = HighlightDialog(self, self.cfg.theme, None if new else self.hl_rules[i])
        self.hl_dialog = d

        def done(code: int) -> None:
            if not code:
                return
            r = d.result_rule()
            if new:
                self.hl_rules.append(r)
                self._hl_fill(len(self.hl_rules) - 1)
            else:
                self.hl_rules[i] = r
                self._hl_fill(i)
        d.finished.connect(done)
        d.open()

    def _hl_remove(self) -> None:
        i = self._hl_index()
        if i >= 0:
            del self.hl_rules[i]
            self._hl_fill(min(i, len(self.hl_rules) - 1))

    def _hl_move(self, step: int) -> None:
        i = self._hl_index()
        j = i + step
        if i >= 0 and 0 <= j < len(self.hl_rules):
            self.hl_rules[i], self.hl_rules[j] = self.hl_rules[j], self.hl_rules[i]
            self._hl_fill(j)

    # --- General ------------------------------------------------------------------------

    def _general_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Default Messages"))
        g = QGridLayout()
        self.quit_msg = self._entry(g, 0, "Quit:", c.quit_reason)
        self.part_msg = self._entry(g, 1, "Leave channel:", c.part_reason)
        self.away_msg = self._entry(g, 2, "Away:", c.away_reason)
        lay.addLayout(g)
        lay.addWidget(_heading("Away"))
        self.announce = self._check(lay, "Announce away messages", c.announce_away, "Tell every channel you're in when you go away and come back")
        self.away_once = self._check(lay, "Show away once", c.away_once, "Show identical away messages only once")
        self.auto_unaway = self._check(lay, "Automatically unmark away", c.auto_unaway, "Unmark yourself as away before sending messages")
        lay.addWidget(_heading("Channels and Private Chats"))
        self.rejoin_kick = self._check(lay, "Rejoin a channel when I'm kicked", c.rejoin_on_kick,
                                       "Waits 3 seconds and tries once, so a kick loop can't flood the channel")
        self.whois_query = self._check(lay, "Show who someone is when they start a private chat with me", c.whois_on_query,
                                       "A short WHOIS at the top of the new tab: their host, channels and idle time")
        lay.addWidget(_heading("Connecting"))
        self.skip_motd = self._check(lay, "Skip the server's welcome message (MOTD)", c.skip_motd,
                                     "Type /motd to read it any time")
        lay.addWidget(_heading("Starting and Closing"))
        self.start_win = self._check(lay, "Start with Windows", c.start_with_windows, "Only for the installed BChat")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        self.start_how = self._menu(g, 0, "When BChat starts:", ["Show the window", "Minimized", "In the tray"],
                                    2 if c.start_in_tray else 1 if c.start_minimized else 0)
        self.start_how.setToolTip("In the tray: BChat connects and stays out of sight; click the tray icon to open it")
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        self.ask_quit = self._check(lay, "Ask before quitting while connected", c.ask_on_quit)
        self.report_offer = self._check(lay, "Offer to send a problem report after a crash or freeze", c.report_offer,
                                        "A bar above the input box asks first; nothing is ever sent by itself. Help > Report a Problem... works any time.")
        self.min_tray = self._check(lay, "Minimize button sends BChat to the tray", c.minimize_to_tray)
        self.close_tray = self._check(lay, "Close button sends BChat to the tray", c.close_to_tray, "To really quit: right-click the tray icon > Quit, or BChat > Quit (Ctrl+Q)")
        lay.addWidget(QLabel("Either tray option shows the tray icon by itself."))
        lay.addStretch(1)
        return page

    # --- Updates (BChat > Updates) -------------------------------------------------------

    def _updates_page(self) -> QWidget:
        from .updatepage import updates_page
        page, lay = self._new_page()
        lay.setContentsMargins(14, 12, 14, 6)
        lay.setSpacing(6)
        updates_page(self, lay)
        return page

    # --- Logging ------------------------------------------------------------------------

    def _logging_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Logging"))
        self.replay = self._check(lay, "Display scrollback from previous session", c.text_replay)
        self.log_all = self._check(lay, "Enable logging of conversations to disk", c.log_all, 'Single tabs: right-click the tab, "Log to Disk"')
        from . import logs
        g = QGridLayout()
        split = logs.SPLITS.index(c.log_split) if c.log_split in logs.SPLITS else 0
        self.log_split = self._menu(g, 0, "Start a new file:", ("Every day", "Every month", "Never (one file)"), split)
        keep = logs.KEEP_DAYS.index(c.log_keep_days) if c.log_keep_days in logs.KEEP_DAYS else 0
        self.log_keep = self._menu(g, 1, "Delete logs older than:", ("Never", "1 month", "6 months", "1 year"), keep)
        self.log_mask_label = QLabel("Log filename:")
        g.addWidget(self.log_mask_label, 2, 0, Qt.AlignmentFlag.AlignRight)
        self.log_mask = QLineEdit(c.log_mask)
        g.addWidget(self.log_mask, 2, 1, 1, 2)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        self.log_mask_hint = QLabel("%s=Server %c=Channel %n=Network. A / makes a folder.")
        lay.addWidget(self.log_mask_hint)
        self.log_saved = QLabel()
        self.log_saved.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(self.log_saved)
        row = QHBoxLayout()
        view = QPushButton(icon("find"), "View Logs...")
        view.setAutoDefault(False)
        view.clicked.connect(self._view_logs)
        folder = QPushButton(icon("open"), "Open Logs Folder")
        folder.setAutoDefault(False)
        folder.clicked.connect(lambda: self.win.open_logs_folder())
        row.addWidget(view)
        row.addWidget(folder)
        row.addStretch(1)
        lay.addLayout(row)
        self.log_split.currentIndexChanged.connect(lambda _i: self._log_split_changed())
        self._log_answered = False
        self.log_all.toggled.connect(self._log_all_toggled)
        self.log_mask.textChanged.connect(lambda _t: self._log_split_changed())
        self._log_split_changed()
        lay.addWidget(_heading("Time Stamps"))
        self.log_stamps = self._check(lay, "Insert timestamps in logs", c.log_stamps)
        g = QGridLayout()
        self.log_fmt = self._entry(g, 0, "Log timestamp format:", c.log_stamp_format)
        lay.addLayout(g)
        lay.addWidget(QLabel("%H hour, %M minute, %S second, %d day, %b month name."))
        lay.addStretch(1)
        return page

    def _log_all_toggled(self, on: bool) -> None:
        """First time logging goes on: the one-time question. Its answer counts only when Preferences is saved."""
        from . import logs
        if not on or self._log_answered or not hasattr(self.win, "needs_log_question") or not self.win.needs_log_question():
            return
        keep = self.win.ask_logging("your chats", self)
        if keep is None:
            self.log_all.blockSignals(True)
            self.log_all.setChecked(False)
            self.log_all.blockSignals(False)
            return
        self._log_answered = True
        self.log_keep.setCurrentIndex(logs.KEEP_DAYS.index(keep))

    def _view_logs(self) -> None:
        """Preferences is modal, so it saves and closes first; then the Logs window can be used."""
        from PySide6.QtCore import QTimer
        self.accept()
        QTimer.singleShot(0, self.win.open_logs)

    def _log_split_changed(self) -> None:
        """The filename mask only matters for one file per tab; the Saved as line shows where today's lines go."""
        import time as _time
        from . import logs
        split = logs.SPLITS[self.log_split.currentIndex()]
        one = split == "none"
        for w in (self.log_mask_label, self.log_mask, self.log_mask_hint):
            w.setVisible(one)
        b = getattr(self.win, "buf", None)
        clean = getattr(self.win, "_clean", lambda x: x)
        net = clean(b.session.net.name) if b is not None and b.session is not None else "Network"
        chan = clean(b.name) if b is not None and b.kind != "server" else "#channel"
        if one:
            mask = self.log_mask.text().strip() or "%n-%c.log"
            name = mask.replace("%n", net).replace("%s", net).replace("%c", chan).replace("/", "\\")
        else:
            name = f"{net}\\{chan}\\{logs.dated_name(split, _time.time())}"
        self.log_saved.setText(f"Saved as: logs\\{name}")

    # --- Sound --------------------------------------------------------------------------

    def _sound_page(self) -> QWidget:
        page, lay = self._new_page()
        lay.addWidget(_heading("Sound"))
        lay.addWidget(QLabel("Pick a .wav file for any event. Leave it empty for no sound."))
        g = QGridLayout()
        self.sound_edits: dict[str, QLineEdit] = {}
        for row, (key, label) in enumerate(SOUND_EVENTS):
            edit = self._entry(g, row, label + ":", self.cfg.sounds.get(key, ""))
            self.sound_edits[key] = edit
            browse = QPushButton("Browse...")
            browse.setAutoDefault(False)
            browse.clicked.connect(lambda _=False, e=edit: self._browse(e, "Sound file", "Sound files (*.wav)"))
            g.addWidget(browse, row, 2)
            play = QPushButton("Play")
            play.setAutoDefault(False)
            play.clicked.connect(lambda _=False, e=edit: self._try_sound(e.text()))
            g.addWidget(play, row, 3)
        lay.addLayout(g)
        lay.addStretch(1)
        return page

    def _try_sound(self, path: str) -> None:
        if path:
            self.win.cfg.sounds["__try"] = path
            self.win._play_sound("__try")
            del self.win.cfg.sounds["__try"]

    # --- Advanced -----------------------------------------------------------------------

    def _advanced_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Advanced Settings"))
        g = QGridLayout()
        self.reconnect = self._number(g, 0, "Auto reconnect delay:", c.reconnect_delay, 1, 9999, " seconds")
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        self.raw_modes = self._check(lay, "Display MODEs in raw form", c.raw_modes)
        self.hide_jp = self._check(lay, "Hide join and part messages", c.hide_joinpart, "Hide channel join/part messages by default")
        self.notify_whois = self._check(lay, "Whois on notify", c.whois_on_notify, "Sends a /WHOIS when a friend comes online")
        self.url_grab = self._check(lay, "Grab URLs for the URL Grabber", c.url_grabber)
        g = QGridLayout()
        self.url_limit = self._number(g, 0, "URLs to keep:", c.url_limit, 1, 9999)
        self.opacity = self._number(g, 1, "Window opacity:", c.opacity, 30, 100, " %")
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        from . import nowplaying, sysinfo
        lay.addWidget(_heading("System Info (/sysinfo)"))
        g = QGridLayout()
        self.sys_line = self._entry(g, 0, "Line:", c.sysinfo_line or sysinfo.DEFAULT_LINE)
        self.sys_line.setToolTip("Words you can use: " + " ".join("{%s}" % w for w in sysinfo.WORDS)
                                 + ". Delete any you don't want to share. Your IP address, PC name and user name are never included.")
        lay.addLayout(g)
        lay.addStretch(1)
        return page

    # --- Now Playing ----------------------------------------------------------------------

    def _np_page(self) -> QWidget:
        """/np and announcing, on their own page (0.2.0). Announce channels are network + channel, added from the
        chat's right click > Share so names can't be mistyped; a plain #channel (older settings) means every network."""
        from . import nowplaying
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Share with /np"))
        self.np_on = self._check(lay, "Let /np share what I'm listening to", c.np_enabled,
                                 "Off when BChat is new. Nothing is ever shared on its own: only when you type /np")
        self.np_music = self._check(lay, "Only music: skip videos and anything not marked as music", c.np_music_only)
        self.np_boxes = {}
        if c.np_players:
            row = QHBoxLayout()
            row.addWidget(QLabel("Players /np may read:"))
            for pid in sorted(c.np_players, key=lambda p: c.np_names.get(p, p).lower()):
                box = QCheckBox(c.np_names.get(pid, nowplaying.player_name(pid)))
                box.setChecked(bool(c.np_players[pid]))
                box.setToolTip(pid)
                self.np_boxes[pid] = box
                row.addWidget(box)
            row.addStretch(1)
            lay.addLayout(row)
        else:
            lay.addWidget(QLabel("Players show up here once /np has seen them play. Browsers start unticked."))
        self.np_ask = self._check(lay, "Show me the line before it's sent", c.np_ask)
        g = QGridLayout()
        self.np_line = self._entry(g, 0, "Line:", c.np_line or nowplaying.DEFAULT_LINE)
        self.np_line.setToolTip("Words you can use: {artist} {title} {album} {player} {time}")
        lay.addLayout(g)
        lay.addWidget(_heading("Announce each new song"))
        self.np_ann = self._check(lay, "Post every new song on its own", c.np_announce,
                                  "Off when BChat is new. Only in the channels listed below")
        box = QHBoxLayout()
        box.setContentsMargins(20, 0, 0, 0)
        self.np_ann_list = QTreeWidget()
        self.np_ann_list.setHeaderLabels(["Network", "Channel"])
        self.np_ann_list.setRootIsDecorated(False)
        self.np_ann_list.setFixedHeight(96)
        self.np_ann_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for net, chan in nowplaying.announce_targets(c.np_announce_in):
            it = QTreeWidgetItem([net or "Every network", chan])
            it.setData(0, Qt.ItemDataRole.UserRole, f"{net}/{chan}" if net else chan)
            self.np_ann_list.addTopLevelItem(it)
        box.addWidget(self.np_ann_list, 1)
        col = QVBoxLayout()
        self.np_ann_remove = QPushButton(icon("close-light"), "Remove", objectName="compact")
        self.np_ann_remove.clicked.connect(lambda: [self.np_ann_list.takeTopLevelItem(self.np_ann_list.indexOfTopLevelItem(i))
                                                    for i in self.np_ann_list.selectedItems()])
        self.np_ann_add = QPushButton(icon("new"), "Add...", objectName="compact")
        self.np_ann_add.clicked.connect(self._np_add_channel)
        col.addWidget(self.np_ann_add)
        col.addWidget(self.np_ann_remove)
        col.addStretch(1)
        box.addLayout(col)
        lay.addLayout(box)
        self.np_ann_hint = QLabel("Or right click in a channel > Share > Announce Songs Here.")
        self.np_ann_hint.setStyleSheet(f"color: {c.theme.muted}; margin-left: 20px;")
        lay.addWidget(self.np_ann_hint)
        self.np_ann_note = QLabel(f"Only these channels, once a song has played {int(nowplaying.ANNOUNCE_AFTER)} seconds.")
        self.np_ann_note.setToolTip("Each song is posted once. Paused or skipped songs are never sent.")
        self.np_ann_note.setStyleSheet(f"color: {c.theme.muted}; margin-left: 20px;")
        lay.addWidget(self.np_ann_note)
        for w in (self.np_music, self.np_ask, self.np_line, self.np_ann, self.np_ann_list, self.np_ann_add, self.np_ann_remove, self.np_ann_hint, self.np_ann_note, *self.np_boxes.values()):
            w.setEnabled(c.np_enabled)
            self.np_on.toggled.connect(w.setEnabled)
        lay.addStretch(1)
        return page

    def _np_channels_of(self, network: str) -> list[str]:
        """Channels to offer for a network: the ones open there now, then its auto-join list."""
        seen: list[str] = []
        def add(name):
            if name and name.lower() not in [n.lower() for n in seen]:
                seen.append(name)
        for s in getattr(self.win, "sessions", {}).values():
            if not network or s.net.name.lower() == network.lower():
                for b in s.buffers.values():
                    if b.kind == "channel":
                        add(b.name)
        for n in self.cfg.networks:
            if not network or n.name.lower() == network.lower():
                for ch in n.autojoin.split(" ", 1)[0].split(","):
                    add(ch.strip())
        return seen

    def _np_add_channel(self) -> None:
        """Add...: pick the network (or every network) and the channel; the channel list follows the network."""
        d = FramedDialog("Announce Songs In", self)
        d.setFixedWidth(380)
        g = QGridLayout()
        g.setVerticalSpacing(8)
        d.net = QComboBox()
        names = ["Every network"]
        live = [s.net.name for s in getattr(self.win, "sessions", {}).values() if s.state == "connected"]
        for n in live or [n.name for n in self.cfg.networks if n.servers]:   # connected ones; saved ones only if none
            if n and n not in names:
                names.append(n)
        d.net.addItems(names)
        cur = getattr(self.win, "session", None)
        if cur is not None and cur.net.name in names:
            d.net.setCurrentText(cur.net.name)
        d.chan = QComboBox()
        d.chan.setEditable(True)

        def fill():
            net = "" if d.net.currentIndex() == 0 else d.net.currentText()
            d.chan.clear()
            d.chan.addItems(self._np_channels_of(net))
        d.net.currentIndexChanged.connect(fill)
        fill()
        g.addWidget(QLabel("Network:"), 0, 0)
        g.addWidget(d.net, 0, 1)
        g.addWidget(QLabel("Channel:"), 1, 0)
        g.addWidget(d.chan, 1, 1)
        g.setColumnStretch(1, 1)
        d.body.addLayout(g)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        d.body.addWidget(line)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(icon("cancel"), "&Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(d.reject)
        ok = QPushButton(icon("done"), "&Add")
        ok.setDefault(True)
        ok.clicked.connect(d.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        d.body.addLayout(row)

        def done(code: int) -> None:
            chan = d.chan.currentText().strip()
            if not code or not chan:
                return
            if chan[0] not in "#&!+":
                chan = "#" + chan
            net = "" if d.net.currentIndex() == 0 else d.net.currentText()
            entry = f"{net}/{chan}" if net else chan
            for i in range(self.np_ann_list.topLevelItemCount()):
                if self.np_ann_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole).lower() == entry.lower():
                    return
            it = QTreeWidgetItem([net or "Every network", chan])
            it.setData(0, Qt.ItemDataRole.UserRole, entry)
            self.np_ann_list.addTopLevelItem(it)
            self.np_ann_list.setCurrentItem(it)
        d.finished.connect(done)
        self.np_add_dialog = d
        d.open()

    # --- File transfers -----------------------------------------------------------------

    def _folder_row(self, g: QGridLayout, row: int, label: str, value: str) -> QLineEdit:
        edit = self._entry(g, row, label, value)
        pick = QPushButton("Browse...")
        pick.setAutoDefault(False)

        def choose():
            path = QFileDialog.getExistingDirectory(self, label.rstrip(":"), edit.text())
            if path:
                edit.setText(path)
        pick.clicked.connect(lambda _=False: choose())
        g.addWidget(pick, row, 2)
        return edit

    def _files_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Files and Directories"))
        g = QGridLayout()
        self.dcc_auto = self._menu(g, 0, "Auto accept file offers:", ("No, ask me", "Yes"), c.dcc_auto)
        self.dcc_dir = self._folder_row(g, 1, "Download files to:", c.dcc_dir)
        self.dcc_done = self._folder_row(g, 2, "Move completed files to:", c.dcc_done_dir)
        lay.addLayout(g)
        lay.addWidget(QLabel("Programs (.exe and the like) are never auto accepted."))
        self.dcc_nick = self._check(lay, "Save nick name in filenames", c.dcc_with_nick)
        lay.addWidget(_heading("Ports"))
        g = QGridLayout()
        self.dcc_first = self._number(g, 0, "First DCC send port:", c.dcc_first_port, 0, 65535)
        self.dcc_last = self._number(g, 1, "Last DCC send port:", c.dcc_last_port, 0, 65535)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        where = QLabel("The address file offers carry is on Network > Local.")
        where.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(where)
        lay.addWidget(_heading("Maximum File Transfer Speeds (KB/s, 0 = no limit)"))
        g = QGridLayout()
        self.dcc_up = self._number(g, 0, "One upload:", c.dcc_max_send, 0, 999999)
        self.dcc_down = self._number(g, 1, "One download:", c.dcc_max_get, 0, 999999)
        self.dcc_up_all = self._number(g, 2, "All uploads combined:", c.dcc_max_send_all, 0, 999999)
        self.dcc_down_all = self._number(g, 3, "All downloads combined:", c.dcc_max_get_all, 0, 999999)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("Auto Open DCC Windows"))
        row = QHBoxLayout()
        self.dcc_open_send = self._check(row, "Send window", c.dcc_open_send)
        self.dcc_open_recv = self._check(row, "Receive window", c.dcc_open_recv)
        self.dcc_open_chat = self._check(row, "Chat window", c.dcc_open_chat)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    # --- Local (mIRC's Connect > Local) -----------------------------------------------------

    def _local_page(self) -> QWidget:
        """Where the address that file offers (DCC) carry comes from, and the Local host line on connect."""
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("On Connect"))
        self.local_find = self._check(lay, "Find my address when I connect", c.local_find)
        self.local_show = self._check(lay, "Show it in the server tab (Local host: ...)", c.local_show,
                                      "Only you see it, but it shows your IP in screenshots")
        self.local_show.setStyleSheet("margin-left: 20px;")
        self.local_find.toggled.connect(self.local_show.setEnabled)
        self.local_show.setEnabled(c.local_find)
        lay.addWidget(_heading("Lookup Method"))
        group = QButtonGroup(page)
        self.local_ways = {}
        for key, text in (("normal", "This PC (Normal)"), ("server", "The IRC server (Server)")):
            r = QRadioButton(text)
            group.addButton(r)
            lay.addWidget(r)
            self.local_ways[key] = r
        row = QHBoxLayout()
        r = QRadioButton("A website:")
        group.addButton(r)
        self.local_ways["website"] = r
        row.addWidget(r)
        self.local_site = QLineEdit(c.local_site or "icanhazip.com")
        self.local_site.setFixedWidth(220)
        row.addWidget(self.local_site)
        row.addStretch(1)
        lay.addLayout(row)
        self.local_ways.get(c.local_lookup, self.local_ways["server"]).setChecked(True)
        note = QLabel("A website gives your real internet address, but BChat has to ask that site. Off unless you pick it.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {c.theme.muted}; margin-left: 20px;")
        lay.addWidget(note)
        lay.addWidget(_heading("Your Address"))
        g = QGridLayout()
        self.local_host = self._entry(g, 0, "Host name:", c.local_host)
        self.local_host.setPlaceholderText("Found when you connect")
        self.dcc_ip = self._entry(g, 1, "IP address:", c.dcc_ip)
        self.dcc_ip.setPlaceholderText("Found when you connect")
        lay.addLayout(g)
        s = getattr(self.win, "session", None)
        found = ""
        if s is not None and s.external_ip:
            found = f"Found now: <b>{s.local_name or 'unknown'} ({s.external_ip})</b> from {s.net.name}"
        self.local_found = QLabel("Type one only to always use it." + (" " + found if found else ""))
        self.local_found.setWordWrap(True)
        self.local_found.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(self.local_found)
        self.local_warn = QLabel()
        self.local_warn.setWordWrap(True)
        warn = c.theme.palette[7]
        self.local_warn.setStyleSheet(f"color: {warn}; border: 1px solid {warn}; border-radius: 4px; padding: 6px 8px;")
        ip = c.dcc_ip.strip() or (s.external_ip if s is not None else "")
        self.local_warn.setVisible(home_address(ip))
        if home_address(ip):
            self.local_warn.setText(f"⚠  {ip} is a home-network address: people outside your network can't reach it for "
                                    "file sends. Pick A website, or send with passive DCC.")
        lay.addWidget(self.local_warn)
        lay.addStretch(1)
        return page

    # --- Network setup ------------------------------------------------------------------

    def _network_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Your Address"))
        g = QGridLayout()
        self.bind = self._entry(g, 0, "Bind to:", c.bind_host)
        lay.addLayout(g)
        lay.addWidget(QLabel("Only useful for computers with multiple addresses."))
        lay.addWidget(_heading("Proxy Server"))
        g = QGridLayout()
        self.proxy_host = self._entry(g, 0, "Hostname:", c.proxy_host)
        self.proxy_port = self._number(g, 1, "Port:", c.proxy_port, 0, 65535)
        kinds = ("none", "socks5", "http")
        self.proxy_type = self._menu(g, 2, "Type:", ("(Disabled)", "Socks5", "HTTP"), kinds.index(c.proxy_type) if c.proxy_type in kinds else 0)
        lay.addLayout(g)
        lay.addWidget(_heading("Proxy Authentication"))
        self.proxy_auth = self._check(lay, "Use Authentication (HTTP or Socks5 only)", c.proxy_auth)
        g = QGridLayout()
        self.proxy_user = self._entry(g, 0, "Username:", c.proxy_user)
        self.proxy_pass = self._entry(g, 1, "Password:", c.proxy_password, secret=True)
        lay.addLayout(g)
        lay.addStretch(1)
        return page

    def _pick_font(self) -> None:
        ok, f = QFontDialog.getFont(QFont(self.font_family, self.font_size), self, "Chat font",
                                    QFontDialog.FontDialogOption.MonospacedFonts)
        if ok:
            self.set_font(f.family(), f.pointSize())

    def set_font(self, family: str, size: int) -> None:
        self.font_family, self.font_size = family, max(6, size)
        self.font_edit.setText(f"{self.font_family} {self.font_size}")

    # --- Colors -------------------------------------------------------------------------

    def _colors_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 6, 14, 6)
        self.swatches: dict[str, Swatch] = {}
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme:"))
        self.theme_box = QComboBox(page)
        self._fill_theme_box()
        self.theme_box.setMinimumWidth(240)
        self.theme_box.activated.connect(self._theme_picked)
        row.addWidget(self.theme_box)
        row.addStretch(1)
        self.theme_box.setToolTip("Picking a theme sets every colour below. Change any of them and it becomes Custom.")
        lay.addSpacing(4)
        lay.addLayout(row)
        lay.addWidget(_heading("Text Colors"))
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(6)
        g.addWidget(QLabel("mIRC colors:"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self.palette_swatches: list[Swatch] = []
        for i in range(16):
            sw = Swatch(self.theme.palette[i], str(i), page)
            sw.clicked.connect(lambda _=False, i=i: self._pick(("palette", i)))
            g.addWidget(sw, 0 if i < 8 else 1, 1 + i % 8)
            self.palette_swatches.append(sw)
        g.setColumnStretch(9, 1)
        lay.addLayout(g)
        for n, (section, rows) in enumerate(COLOUR_ROWS):
            if n:
                lay.addWidget(_heading(section))
            g = QGridLayout()
            g.setHorizontalSpacing(10)
            g.setVerticalSpacing(6)
            for i, (label, field) in enumerate(rows):
                r, col = divmod(i, 2)
                g.addWidget(QLabel(label), r, col * 2, Qt.AlignmentFlag.AlignRight)
                sw = Swatch(getattr(self.theme, field), "", page)
                sw.clicked.connect(lambda _=False, f=field: self._pick(f))
                g.addWidget(sw, r, col * 2 + 1)
                self.swatches[field] = sw
            g.setColumnStretch(4, 1)
            lay.addLayout(g)
        reset = QPushButton("Reset to Theme", page)
        reset.setToolTip("Back to the colours of the theme picked above")
        reset.setAutoDefault(False)
        reset.clicked.connect(self.reset_colours)
        r = QHBoxLayout()
        r.addWidget(reset)
        r.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(r)
        lay.addStretch(1)
        self._sync_theme_box()
        return page

    def _fill_theme_box(self) -> None:
        """The presets under two headings, Dark and Light. Each preset keeps its name as item data; headings have none."""
        box = self.theme_box
        model = box.model()
        for heading, names in (("Dark", DARK_THEMES), ("Light", LIGHT_THEME_ORDER)):
            box.addItem(heading)
            head = model.item(box.count() - 1)
            head.setEnabled(False)                       # a heading, not a choice
            f = head.font(); f.setBold(True); head.setFont(f)
            for n in names:
                box.addItem(n, n)
        self._preset_count = box.count()

    def _sync_theme_box(self) -> None:
        """Shows the preset, or "Custom (based on ...)" as an extra last entry once a colour differs from it."""
        box = self.theme_box
        while box.count() > self._preset_count:
            box.removeItem(box.count() - 1)
        base = self.theme.name if self.theme.name in PALETTES else THEME_NAMES[0]
        if is_custom(self.theme):
            box.addItem(f"Custom (based on {base})")
            box.setCurrentIndex(box.count() - 1)
        else:
            box.setCurrentIndex(box.findData(base))

    def _theme_picked(self, index: int) -> None:
        name = self.theme_box.itemData(index)
        if name in PALETTES:
            self.load_theme(make_theme(name))

    def load_theme(self, fresh: Theme) -> None:
        for f in fields(Theme):
            setattr(self.theme, f.name, list(fresh.palette) if f.name == "palette" else getattr(fresh, f.name))
        for i, sw in enumerate(self.palette_swatches):
            sw.set_colour(self.theme.palette[i])
        for field, sw in self.swatches.items():
            sw.set_colour(getattr(self.theme, field))
        self._sync_theme_box()

    def _pick(self, key) -> None:
        now = self.theme.palette[key[1]] if isinstance(key, tuple) else getattr(self.theme, key)
        col = QColorDialog.getColor(QColor(now), self, "Pick a colour")
        if col.isValid():
            self.set_colour(key, col.name())

    def set_colour(self, key, colour: str) -> None:
        """key: a Theme field name, or ("palette", n) for mIRC colour n."""
        if isinstance(key, tuple):
            self.theme.palette[key[1]] = colour
            self.palette_swatches[key[1]].set_colour(colour)
        else:
            setattr(self.theme, key, colour)
            self.swatches[key].set_colour(colour)
        self._sync_theme_box()

    def reset_colours(self) -> None:
        self.load_theme(make_theme(self.theme.name if self.theme.name in PALETTES else THEME_NAMES[0]))

    # --- OK -----------------------------------------------------------------------------

    def accept(self) -> None:
        c = self.cfg
        c.chat_font, c.chat_font_size = self.font_family, self.font_size
        c.line_spacing, c.max_lines = self.spacing.value(), self.scrollback.value()
        c.timestamps = self.stamps.isChecked()
        c.stamp_format = self.stamp_fmt.text().strip() or "[%H:%M]"
        c.marker_line = self.marker.isChecked()
        c.rank_lights = next((k for k, r in self.rank_buttons.items() if r.isChecked()), "off")
        c.color_nicks = self.color_nicks.isChecked()
        c.strip_colors = self.strip.isChecked()
        c.colors_exact = self.colors_exact.isChecked()
        c.chat_bg_image = self.bg_image.text().strip()
        c.input_chat_font, c.auto_complete = self.input_font.isChecked(), self.auto_complete.isChecked()
        c.spell_check = self.spell.isChecked()
        c.nick_suffix = self.suffix.text()
        c.complete_sort = "recent" if self.comp_sort.currentIndex() == 1 else "alpha"
        c.percent_ascii, c.percent_codes = self.pct_ascii.isChecked(), self.pct_codes.isChecked()
        c.send_typing = self.send_typing.isChecked()
        c.ul_hosts, c.ul_chat_font = self.ul_hosts.isChecked(), self.ul_font.isChecked()
        c.ul_sort = self.ul_sort.currentIndex()
        c.ul_side = "left" if self.ul_side.currentIndex() == 1 else "right"
        c.away_track, c.away_limit = self.away_track.isChecked(), self.away_limit.value()
        c.ul_double = self.ul_double.text().strip()
        for key, boxes in self.alert_boxes.items():
            setattr(c, key, [b.isChecked() for b in boxes])
        c.tray_icon = self.tray_icon.isChecked()
        from .config import POPUP_TIMES
        c.popup_more = {k: b.isChecked() for k, b in self.popup_more.items()}
        c.popup_seconds = POPUP_TIMES[self.popup_time.currentIndex()][0]
        c.popup_sound = self.popup_sound.currentIndex() > 0
        if c.popup_sound:
            c.popup_sound_name = "bee" if self.popup_sound.currentIndex() == 2 else "soft"
        c.tray_click = "double" if self.tray_click.currentIndex() == 1 else "one"
        c.tray_list = self.tray_list.isChecked()
        c.hilite_no = self.hl_no.text().strip()
        c.hl_on, c.hl_rules = self.hl_on.isChecked(), [dict(r) for r in self.hl_rules]
        c.quit_reason = self.quit_msg.text() or "Leaving"
        c.part_reason = self.part_msg.text() or "Leaving"
        c.away_reason = self.away_msg.text() or "I'm busy"
        c.announce_away, c.away_once, c.auto_unaway = self.announce.isChecked(), self.away_once.isChecked(), self.auto_unaway.isChecked()
        c.rejoin_on_kick, c.whois_on_query = self.rejoin_kick.isChecked(), self.whois_query.isChecked()
        c.skip_motd, c.short_joins = self.skip_motd.isChecked(), self.short_joins.isChecked()
        c.text_replay, c.log_all = self.replay.isChecked(), self.log_all.isChecked()
        c.log_mask = self.log_mask.text().strip() or "%n-%c.log"
        from . import logs
        c.log_split = logs.SPLITS[self.log_split.currentIndex()]
        c.log_keep_days = logs.KEEP_DAYS[self.log_keep.currentIndex()]
        if self._log_answered:
            c.log_asked = True
        c.log_stamps, c.log_stamp_format = self.log_stamps.isChecked(), self.log_fmt.text()
        c.sounds = {k: e.text().strip() for k, e in self.sound_edits.items() if e.text().strip()}
        c.reconnect_delay = self.reconnect.value()
        c.dcc_auto = self.dcc_auto.currentIndex()
        c.dcc_dir, c.dcc_done_dir = self.dcc_dir.text().strip(), self.dcc_done.text().strip()
        c.dcc_with_nick = self.dcc_nick.isChecked()
        c.dcc_first_port, c.dcc_last_port = self.dcc_first.value(), self.dcc_last.value()
        c.local_find, c.local_show = self.local_find.isChecked(), self.local_show.isChecked()
        c.local_lookup = next(k for k, r in self.local_ways.items() if r.isChecked())
        c.local_site = self.local_site.text().strip() or "icanhazip.com"
        c.local_host, c.dcc_ip = self.local_host.text().strip(), self.dcc_ip.text().strip()
        c.dcc_ip_from_server = c.local_lookup == "server"        # kept in step for older builds
        c.dcc_max_send, c.dcc_max_get = self.dcc_up.value(), self.dcc_down.value()
        c.dcc_max_send_all, c.dcc_max_get_all = self.dcc_up_all.value(), self.dcc_down_all.value()
        c.dcc_open_send, c.dcc_open_recv, c.dcc_open_chat = self.dcc_open_send.isChecked(), self.dcc_open_recv.isChecked(), self.dcc_open_chat.isChecked()
        c.tab_layout = "tabs" if self.sw_type.currentIndex() == 1 else "tree"
        c.tab_pos = SWITCHER_POS[self.sw_pos.currentIndex()].lower()
        c.tab_focus, c.tab_trunc = self.sw_focus.currentIndex(), self.sw_trunc.value()
        c.notices_tab, c.auto_dialog, c.tab_sort, c.tab_small = self.sw_notices.isChecked(), self.sw_dialog.isChecked(), self.sw_sort.isChecked(), self.sw_small.isChecked()
        c.dialogs_in_windows = self.sw_windows.currentIndex() == 1
        if self.start_win.isChecked() != c.start_with_windows:
            self.win.set_autostart(self.start_win.isChecked())
        c.start_with_windows, c.close_to_tray = self.start_win.isChecked(), self.close_tray.isChecked()
        c.start_minimized, c.start_in_tray = self.start_how.currentIndex() == 1, self.start_how.currentIndex() == 2
        c.minimize_to_tray, c.ask_on_quit = self.min_tray.isChecked(), self.ask_quit.isChecked()
        c.report_offer = self.report_offer.isChecked()
        c.update_check, c.update_auto_download, c.update_test_versions = self.upd_check.isChecked(), self.upd_auto.isChecked(), self.upd_test.isChecked()
        if not c.update_check:
            self.win.updater.timer.stop()
        elif not self.win.updater.timer.isActive():
            self.win.updater.start()
        c.whois_on_notify, c.url_grabber = self.notify_whois.isChecked(), self.url_grab.isChecked()
        from . import nowplaying, sysinfo
        line = self.sys_line.text().strip()
        c.sysinfo_line = "" if line == sysinfo.DEFAULT_LINE else line
        c.np_enabled, c.np_music_only, c.np_ask = self.np_on.isChecked(), self.np_music.isChecked(), self.np_ask.isChecked()
        line = self.np_line.text().strip()
        c.np_line = "" if line == nowplaying.DEFAULT_LINE else line
        for pid, box in self.np_boxes.items():
            c.np_players[pid] = box.isChecked()
        c.np_announce = self.np_ann.isChecked()
        c.np_announce_in = ", ".join(self.np_ann_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                                     for i in range(self.np_ann_list.topLevelItemCount()))
        c.url_limit, c.opacity = self.url_limit.value(), self.opacity.value()
        c.raw_modes, c.hide_joinpart = self.raw_modes.isChecked(), self.hide_jp.isChecked()
        c.bind_host, c.proxy_host = self.bind.text().strip(), self.proxy_host.text().strip()
        c.proxy_port = self.proxy_port.value()
        c.proxy_type = ("none", "socks5", "http")[self.proxy_type.currentIndex()]
        c.proxy_auth, c.proxy_user, c.proxy_password = self.proxy_auth.isChecked(), self.proxy_user.text().strip(), self.proxy_pass.text()
        for f in fields(Theme):   # in place: the user list and tabs hold this same Theme object
            setattr(c.theme, f.name, list(self.theme.palette) if f.name == "palette" else getattr(self.theme, f.name))
        self.win.apply_preferences()
        super().accept()
