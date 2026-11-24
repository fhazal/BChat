"""Settings > Preferences, laid out like XChat 2: Categories tree on the left, one page on the right.

Pages and options follow XChat 2.8.8's src/fe-gtk/setup.c. Every page works. Nothing changes until OK; Cancel and the red button throw the edits away.
"""
from __future__ import annotations

import html
import time
from dataclasses import fields

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFontDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox, QStackedWidget,
                               QHeaderView, QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .config import DARK_THEMES, LIGHT_THEME_ORDER, PALETTES, THEME_NAMES, Config, Theme, is_custom, make_theme
from .dcc import home_address  # noqa: F401  (tests import it from here)
from .widgets import FramedDialog, icon

CATEGORIES = {"Interface": ["Text box", "Input box", "User list", "Channel switcher", "Windows", "Colors"],
              "Chatting": ["Alerts", "Highlights", "General", "Logging", "Sound", "Now Playing", "Advanced"],
              "Network": ["Network setup", "Flood", "Local"],
              "File transfers": ["File transfers", "Trusted people"],     # 0.8.10: its own group, not a page under Network
              "BChat": ["Updates", "Lock"]}
BUILT = ("Flood", "Text box", "Input box", "User list", "Channel switcher", "Windows", "Colors", "Alerts", "Highlights", "General", "Logging", "Sound", "Now Playing", "Advanced", "Network setup", "Local", "File transfers", "Trusted people", "Updates", "Lock")
LABELS = {"File transfers": "Options"}                 # tree text where it differs from the page's name (the title)
PAGE_FIT = 0.85                                         # the dialog never takes more of the screen's height than this
SWITCHER_POS = ("Left", "Right", "Top", "Bottom", "Hidden")
_OFFER_INDEX = {0: 0, 1: 2, 2: 1, 3: 3}   # menu index <-> dcc_auto / dcc_chat_auto value (its own inverse)
PROXY_KINDS = ("none", "socks5", "http", "socks4", "socks4a")     # the Network setup Type menu, in order
# 0.8.7 Settings > Windows: (label, saved value)
SHOW_WHERE = (("Active window", "active"), ("Server tab", "server"), ("Messages tab", "messages"), ("Query, if open", "query"))
SHOW_NICKS = (("Channels shared", "shared"), ("Active window", "active"), ("Server tab", "server"))
CUSTOM = ("Custom command…", "custom")
DOUBLE = {"channel": (("Nothing", "nothing"), ("Channel modes", "modes"), ("Channel list", "list"), ("Part", "part"), CUSTOM),
          "query": (("Nothing", "nothing"), ("WHOIS", "whois"), ("Close", "close"), CUSTOM),
          "server": (("Expand/collapse", "expand"), ("Nothing", "nothing"), ("Channel list", "list"), CUSTOM),
          "chat": (("Channel modes", "modes"), ("Nothing", "nothing"), ("Channel list", "list"), CUSTOM),
          "nick": (("Same as chat area", "nothing"), ("Open query", "query"), ("WHOIS", "whois"), CUSTOM)}
UL_DOUBLE = (("Open query", "QUERY %s"), ("WHOIS", "WHOIS %s"), CUSTOM)


def ul_double_choice(text: str) -> int:
    """User list > Execute command as a Windows > Nick list choice: 0 Open query, 1 WHOIS, 2 Custom."""
    pattern = text.strip().lstrip("/")
    word = pattern.lower().split(" ")
    return 0 if pattern.lower() == "query %s" else 1 if word[0] == "whois" or " ".join(word[:2]) == "quote whois" else 2
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
                ki = QTreeWidgetItem([LABELS.get(k, k)])
                ki.setData(0, Qt.ItemDataRole.UserRole, k)      # the page's name: a group can share it (File transfers)
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
        self.page_of["Text box"] = self.pages.addWidget(self._scrolled(self._text_page()))
        self.page_of["Colors"] = self.pages.addWidget(self._scrolled(self._colors_page()))
        for name, build in (("File transfers", self._files_page), ("Trusted people", self._trusted_page), ("Channel switcher", self._switcher_page), ("Input box", self._input_page), ("User list", self._userlist_page), ("Windows", self._windows_page), ("Alerts", self._alerts_page), ("Highlights", self._highlights_page),
                            ("General", self._general_page), ("Logging", self._logging_page), ("Sound", self._sound_page), ("Now Playing", self._np_page),
                            ("Advanced", self._advanced_page), ("Network setup", self._network_page), ("Flood", self._flood_page), ("Local", self._local_page), ("Updates", self._updates_page), ("Lock", self._lock_page)):
            self.page_of[name] = self.pages.addWidget(self._scrolled(build()))
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
        self._fit_screen()

    def _page_area(self) -> QWidget:
        """A new scroll area in the page stack, for the page about to be built; returns the parent
        to build the page in. Every page scrolls on its own, so a small or scaled screen gets a
        scroll bar, never a dialog that runs off the bottom with OK out of reach. Pages are made
        where they will live: moving a built page restyles every control on it, and 20 pages of
        that made Preferences slow to open."""
        area = QScrollArea(self.pages)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area.viewport()

    def _scrolled(self, page: QWidget) -> QScrollArea:
        """The scroll area the page was built in (_page_area), with the page set in it."""
        area = page.parentWidget().parentWidget()
        area.setWidget(page)
        return area

    def page_widget(self, name: str) -> QWidget:
        """The page itself (inside its scroll area)."""
        return self.pages.widget(self.page_of[name]).widget()

    def _fit_screen(self) -> None:
        """Tall enough that no page scrolls, but never more than PAGE_FIT of the screen.
        Each page area stays as wide as its page (and a scroll bar), so nothing scrolls sideways."""
        self.ensurePolished()
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        for i in range(self.pages.count()):
            area = self.pages.widget(i)
            area.widget().ensurePolished()
            area.setMinimumWidth(area.widget().minimumSizeHint().width() + bar)
        need = max(self.pages.widget(i).widget().sizeHint().height() for i in range(self.pages.count()))
        chrome = self.sizeHint().height() - self.pages.sizeHint().height()
        screen = self.screen() or QApplication.primaryScreen()
        most = int(screen.availableGeometry().height() * PAGE_FIT) if screen else 600
        self.resize(max(720, self.minimumSizeHint().width()), max(420, min(need + chrome + 2, most)))

    def _show(self, item, _prev=None) -> None:
        name = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if name in self.page_of:
            self.pages.setCurrentIndex(self.page_of[name])
            self.title.setText(name)

    def show_page(self, name: str) -> None:
        self.tree.setCurrentItem(self._items[name])

    # --- Text box ---------------------------------------------------------------------

    def _text_page(self) -> QWidget:
        c = self.cfg
        page = QWidget(self._page_area())
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
        self.shade_lines = self._check(lay, "Shade every other line", c.shade_lines)
        self.line_rules = self._check(lay, "Line between each message", c.line_rules)
        lay.addStretch(1)
        return page

    def _browse(self, edit: QLineEdit, title: str, pattern: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, edit.text(), pattern)
        if path:
            edit.setText(path)

    # small helpers so each page reads like XChat's table in setup.c

    def _new_page(self):
        page = QWidget(self._page_area())
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

    # --- Windows (0.8.7) -------------------------------------------------------------------

    def _choice(self, grid: QGridLayout, row: int, label: str, items, value: str, tip: str = "") -> QComboBox:
        """A drop-down whose items carry the saved value; an unknown value shows the first item."""
        box = self._menu(grid, row, label, [t for t, _ in items], 0)
        for i, (_, v) in enumerate(items):
            box.setItemData(i, v)
        box.setCurrentIndex(max(0, box.findData(value)))
        if tip:
            box.setToolTip(tip)
        return box

    def _custom_edit(self, grid: QGridLayout, row: int, box: QComboBox, text: str) -> QLineEdit:
        """The Custom command line next to its drop-down, shown only while Custom is picked."""
        edit = QLineEdit(text)
        edit.setPlaceholderText("/command  ($nick, $chan, $network)")
        edit.setToolTip("Runs like typed input. $nick, $chan and $network are filled in")
        grid.addWidget(edit, row, 2)
        last = box.count() - 1
        edit.setVisible(box.currentIndex() == last)
        box.currentIndexChanged.connect(lambda i: edit.setVisible(i == last))
        return edit

    def _windows_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Where events show"))
        g = QGridLayout()
        self.show_whois = self._choice(g, 0, "WHOIS replies:", SHOW_WHERE, c.show_whois,
                                       "Active window: the tab the /whois was typed in")
        self.show_notices = self._choice(g, 1, "Notices:", SHOW_WHERE, c.show_notices,
                                         "Private notices from people. Notices to a channel stay in that channel; server "
                                         "notices follow Channel switcher > Open an extra tab for server notices")
        self.show_ctcp = self._choice(g, 2, "CTCP requests:", SHOW_WHERE, c.show_ctcp)
        self.show_away = self._choice(g, 3, "Away replies:", SHOW_WHERE, c.show_away,
                                      "The 'is away' answer when you message someone who is away")
        self.show_nicks = self._choice(g, 4, "Nick changes:", SHOW_NICKS, c.show_nicks)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("Double-click does"))
        g = QGridLayout()
        ul = ul_double_choice(c.ul_double)
        self.dbl_ul = self._menu(g, 0, "Nick list:", [t for t, _ in UL_DOUBLE], ul)
        self.dbl_ul.setToolTip("The same setting as User list > Action Upon Double Click")
        self.dbl_ul_cmd = self._custom_edit(g, 0, self.dbl_ul, c.ul_double if ul == 2 else "")
        self.dbl_ul_cmd.setPlaceholderText("/command  (%s or $nick, $chan, $network)")
        self.dbl_ul.currentIndexChanged.connect(self._ul_choice_changed)
        self.dbl_ul_cmd.textChanged.connect(self._ul_choice_changed)
        self.ul_double.textChanged.connect(self._ul_entry_changed)
        rows = (("channel", "Channel tab / tree item:"), ("query", "Query tab / tree item:"),
                ("server", "Server tab / tree item:"), ("chat", "Empty chat area:"), ("nick", "Nick in chat text:"))
        self.dbl, self.dbl_cmd = {}, {}
        for r, (kind, label) in enumerate(rows, 1):
            self.dbl[kind] = self._choice(g, r, label, DOUBLE[kind], getattr(c, "dbl_" + kind))
            self.dbl_cmd[kind] = self._custom_edit(g, r, self.dbl[kind], getattr(c, f"dbl_{kind}_cmd"))
        self.dbl["chat"].setToolTip("Channel modes only works in a channel. A #channel word always joins it")
        self.dbl["nick"].setToolTip("A nick from the nick list, double-clicked in the text")
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addStretch(1)
        return page

    def _ul_choice_changed(self, *_a) -> None:
        """Windows > Nick list -> User list > Execute command (the one that is saved)."""
        if getattr(self, "_ul_sync", False):
            return
        i = self.dbl_ul.currentIndex()
        if i == ul_double_choice(self.ul_double.text()) and i != 2:
            return                       # already that choice: keep the user's own form (QUOTE WHOIS %s %s)
        text = self.dbl_ul_cmd.text().strip() if i == 2 else UL_DOUBLE[i][1]
        if not text:
            return
        self._ul_sync = True
        try:
            self.ul_double.setText(text)
        finally:
            self._ul_sync = False

    def _ul_entry_changed(self, text: str) -> None:
        """User list > Execute command -> Windows > Nick list."""
        if getattr(self, "_ul_sync", False):
            return
        i = ul_double_choice(text)
        self._ul_sync = True
        try:
            self.dbl_ul.setCurrentIndex(i)
            if i == 2:
                self.dbl_ul_cmd.setText(text.strip())
        finally:
            self._ul_sync = False

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
                                 "Your nick always highlights. This turns the rules below on or off.")
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
        self.single_msg = self._check(lay, "Put all private messages in one Messages tab", c.single_msg_window,
                                      "One (messages) tab per network. Reply with /msg nick; /query still opens a private chat")
        self.single_friends = self._check(lay, "Still open a private chat for nicks on my Friends list", c.single_msg_friends)
        self.single_copy = self._check(lay, "Copy the conversation into the private chat when I open one", c.single_msg_copy)
        for w in (self.single_friends, self.single_copy):
            w.setStyleSheet("margin-left: 20px;")
            self.single_msg.toggled.connect(w.setEnabled)
            w.setEnabled(c.single_msg_window)
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

    # --- Lock (0.6.0) -------------------------------------------------------------------------

    def _lock_page(self) -> QWidget:
        from . import lock
        c = self.cfg
        page, lay = self._new_page()
        self.lock_d = lock.read(self.win.cfg_dir)
        self.lock_open = self.lock_d is None          # an existing lock needs its password before changes
        self.lock_new_pw = ""
        lay.addWidget(_heading("Start"))
        self.lock_on = self._check(lay, "Ask for a password when BChat starts", self.lock_d is not None)
        self.lock_on.toggled.connect(self._lock_toggled)
        row = QHBoxLayout()
        self.lock_pw_btn = QPushButton(icon("edit"), "Set Password...")
        self.lock_pw_btn.setAutoDefault(False)
        self.lock_pw_btn.clicked.connect(self._lock_set_password)
        self.lock_unlock_btn = QPushButton(icon("preferences"), "Change Lock Settings...")
        self.lock_unlock_btn.setAutoDefault(False)
        self.lock_unlock_btn.clicked.connect(self._lock_unlock)
        row.addWidget(self.lock_pw_btn)
        row.addWidget(self.lock_unlock_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_heading("Limits while Lock is on"))
        d = self.lock_d or {}
        self.lock_no_dcc = self._check(lay, "No file transfers or direct chats", bool(d.get("no_dcc")))
        self.lock_no_priv = self._check(lay, "No new private chats (they show in the server tab)", bool(d.get("no_private")))
        g = QGridLayout()
        self.lock_only = QCheckBox("Only these channels:")
        self.lock_only.setChecked(bool(d.get("only_channels")))
        self.lock_chans = QLineEdit(d.get("only_channels", ""))
        self.lock_chans.setPlaceholderText("#chat, #BChat")
        g.addWidget(self.lock_only, 0, 0)
        g.addWidget(self.lock_chans, 0, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        note = QLabel("For a shared or family PC. With a lock, this page needs the password to change. Forgot it? "
                      "Delete lock.json in BChat's settings folder (anyone with the PC can, so it is a house rule, not a safe).")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(note)
        self.lock_removed = QLabel("")
        self.lock_removed.setWordWrap(True)
        if c.lock_removed_at and self.lock_d is None:
            when = time.strftime("%d-%m at %H:%M", time.localtime(c.lock_removed_at))
            self.lock_removed.setText(f"The lock was removed on {when} (lock.json was deleted).")
            self.lock_removed.setStyleSheet(f"color: {c.theme.status_lag};")
        lay.addWidget(self.lock_removed)
        lay.addStretch(1)
        self._lock_state()
        return page

    def _lock_state(self) -> None:
        editable = self.lock_open
        for w in (self.lock_on, self.lock_no_dcc, self.lock_no_priv, self.lock_only, self.lock_chans):
            w.setEnabled(editable)
        self.lock_pw_btn.setEnabled(editable and self.lock_on.isChecked())
        self.lock_unlock_btn.setVisible(not editable)

    def _lock_unlock(self) -> None:
        from . import lock
        key = lock.ask_password(self, self.win.cfg_dir, self.lock_d, "BChat: Lock Settings",
                                "Password to change the Lock settings:", "&Cancel")
        if key is not None:
            self.lock_open = True
            self.lock_key = key
            self._lock_state()

    def _lock_toggled(self, on: bool) -> None:
        if on and self.lock_d is None and not self.lock_new_pw:
            self._lock_set_password()
            if not self.lock_new_pw:
                self.lock_on.setChecked(False)
        self._lock_state()

    def _lock_set_password(self, pw: str | None = None) -> None:
        if pw is None:
            pw = new_password(self)
        if pw:
            self.lock_new_pw = pw

    def _apply_lock(self) -> None:
        from . import config as config_mod, lock
        if not self.lock_open:
            return
        c = self.cfg
        limits = {"no_dcc": self.lock_no_dcc.isChecked(), "no_private": self.lock_no_priv.isChecked(),
                  "only_channels": self.lock_chans.text().strip() if self.lock_only.isChecked() else ""}
        if self.lock_on.isChecked() and (self.lock_new_pw or self.lock_d is not None):
            if self.lock_new_pw:
                d, key = lock.make(self.lock_new_pw, limits)
                config_mod.LOCK_KEY = key
            else:
                d = dict(self.lock_d)
                d.update(lock.limits_only(limits))
            lock.write(self.win.cfg_dir, d)
            c.lock_was_on, c.lock_removed_at = True, 0.0
            c.lock_limits = lock.limits_only(d)
        else:
            lock.remove(self.win.cfg_dir)
            c.lock_was_on, c.lock_removed_at = False, 0.0
            c.lock_limits = None
            config_mod.LOCK_KEY = None

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
        from PySide6.QtWidgets import QSlider
        from . import sound, speech
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Sound"))
        lay.addWidget(QLabel("Pick a .wav, .mp3 or .ogg file for any event. Leave it empty for no sound."))
        g = QGridLayout()
        self.sound_edits: dict[str, QLineEdit] = {}
        for row, (key, label) in enumerate(SOUND_EVENTS):
            edit = self._entry(g, row, label + ":", c.sounds.get(key, ""))
            self.sound_edits[key] = edit
            browse = QPushButton("Browse...")
            browse.setAutoDefault(False)
            browse.clicked.connect(lambda _=False, e=edit: self._browse(e, "Sound file", sound.FILTER))
            g.addWidget(browse, row, 2)
            play = QPushButton("Play")
            play.setAutoDefault(False)
            play.clicked.connect(lambda _=False, e=edit: self._try_sound(e.text()))
            g.addWidget(play, row, 3)
        # 0.8.8: one volume for every sound (100 % = as before)
        row = len(SOUND_EVENTS)
        g.addWidget(QLabel("Volume:"), row, 0, Qt.AlignmentFlag.AlignRight)
        self.sound_volume = QSlider(Qt.Orientation.Horizontal)
        self.sound_volume.setRange(0, 100)
        self.sound_volume.setPageStep(10)
        self.sound_volume.setValue(max(0, min(100, int(c.sound_volume))))
        self.sound_volume.setToolTip("For every sound BChat plays")
        g.addWidget(self.sound_volume, row, 1)
        self.sound_volume_text = QLabel()
        self.sound_volume.valueChanged.connect(lambda v: self.sound_volume_text.setText(f"{v} %"))
        self.sound_volume_text.setText(f"{self.sound_volume.value()} %")
        g.addWidget(self.sound_volume_text, row, 2)
        lay.addLayout(g)
        # 0.8.8 Speech: hidden when this PC has no speech engine (nothing to use)
        self.speech_box = QWidget(page)                    # a parent, so showing it never opens a window of its own
        sl = QVBoxLayout(self.speech_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(_heading("Speech"))
        ticks = QGridLayout()
        self.speak_hilights = QCheckBox("Read highlights aloud")
        self.speak_private = QCheckBox("Read private messages")
        self.speak_notices = QCheckBox("Read notices")
        for i, (box, on) in enumerate(((self.speak_hilights, c.speak_hilights), (self.speak_private, c.speak_private),
                                       (self.speak_notices, c.speak_notices))):
            box.setChecked(bool(on))
            ticks.addWidget(box, i // 2, i % 2)
        ticks.setColumnStretch(2, 1)
        sl.addLayout(ticks)
        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("Voice:"))
        self.speak_voice = QComboBox()
        self.speak_voice.addItem("Windows default", "")
        talker = speech.speaker()
        available = talker.available()
        for name in talker.voices() if available else []:
            self.speak_voice.addItem(name, name)
        self.speak_voice.setCurrentIndex(max(0, self.speak_voice.findData(c.speak_voice)))
        vrow.addWidget(self.speak_voice)
        vrow.addSpacing(12)
        vrow.addWidget(QLabel("Speed:"))
        self.speak_rate = QSlider(Qt.Orientation.Horizontal)
        self.speak_rate.setRange(-10, 10)
        self.speak_rate.setPageStep(2)
        self.speak_rate.setValue(max(-10, min(10, int(c.speak_rate))))
        self.speak_rate.setToolTip("Slower to the left, faster to the right. The middle is normal")
        self.speak_rate.setMinimumWidth(110)
        vrow.addWidget(self.speak_rate)
        self.speak_test = QPushButton("Test")
        self.speak_test.setAutoDefault(False)
        self.speak_test.clicked.connect(self._try_speech)
        vrow.addWidget(self.speak_test)
        vrow.addStretch(1)
        sl.addLayout(vrow)
        self.speak_only_away = QCheckBox("Only when BChat is not the active window")
        self.speak_only_away.setChecked(bool(c.speak_only_away))
        sl.addWidget(self.speak_only_away)
        lay.addWidget(self.speech_box)
        self.speech_box.setHidden(not available)
        lay.addStretch(1)
        return page

    def _try_sound(self, path: str) -> None:
        if path:
            from . import sound
            sound.play(path, self.sound_volume.value())

    def _try_speech(self) -> None:
        from . import speech
        talker = speech.speaker()
        talker.stop()
        talker.say(speech.TEST_TEXT, self.speak_voice.currentData() or "", self.speak_rate.value())

    # --- Advanced -----------------------------------------------------------------------

    def _advanced_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Connecting"))      # 0.8.5 mockup E
        g = QGridLayout()
        self.reconnect = self._number(g, 0, "Auto reconnect delay:", c.reconnect_delay, 1, 9999, " seconds")
        self.connect_retries = self._number(g, 1, "Retry:", c.connect_retries, 0, 999, " times")
        g.addWidget(QLabel("0 = keep trying"), 1, 2)
        self.connect_timeout = self._number(g, 2, "Connect time-out:", max(5, c.connect_timeout), 5, 300, " seconds")
        self.server_timeout = self._number(g, 3, "Server time-out:", c.server_timeout, 60, 600, " seconds")
        g.setColumnStretch(3, 1)
        lay.addLayout(g)
        self.invisible = self._check(lay, "Invisible mode (+i): only people who share a channel or know your nick can find you",
                                     c.invisible)
        self.move_top = self._check(lay, "Move a server to the top of its network's list when I connect to it", c.move_to_top,
                                    "Next time, the server that worked is tried first")
        lay.addWidget(_heading("CTCP"))            # 0.8.7: the same setting as /ctcps on|off
        self.ctcp_reply = self._check(lay, "Reply to CTCP requests", c.ctcp_reply_enabled,
                                      "Off: VERSION, PING, TIME, FINGER, CLIENTINFO get no answer. /me actions and file "
                                      "transfers still work, and requests are still shown. Same as /ctcps on|off")
        lay.addWidget(_heading("Advanced Settings"))
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
            path = QFileDialog.getExistingDirectory(self, label.rstrip(":"), edit.text() or edit.placeholderText())
            if path:
                edit.setText(path)
        pick.clicked.connect(lambda _=False: choose())
        g.addWidget(pick, row, 2)
        return edit

    # --- Flood (0.6.0) ------------------------------------------------------------------------

    FLOOD_DEFAULTS = {"pace": 1, "on": True, "ctcp_on": True, "bytes": 400, "lines": 10, "per_user": 2, "ignore": 30,
                      "queries": 5, "whois": 3}

    def _flood_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Sending"))
        g = QGridLayout()
        paces = ("careful", "normal", "fast")
        self.flood_pace = self._menu(g, 0, "Pace:", ("Careful (slow servers)", "Normal", "Fast (your own server or bouncer)"),
                                     paces.index(c.flood_pace) if c.flood_pace in paces else 1)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        tip = QLabel("How quickly BChat sends lines, so the server never throws you out for flooding. "
                     "Your own messages always go before automatic ones.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addWidget(_heading("Flood Protection"))
        self.flood_on = self._check(lay, "Turn on flood protection", c.flood_on)
        self.flood_ctcp_on = self._check(lay, "Also for CTCP replies (version, ping, time)", c.flood_ctcp_on)
        g = QGridLayout()
        rows = (("flood_bytes", "Check after:", c.flood_bytes, 0, 99999, "bytes waiting to go out"),
                ("flood_lines", "Buffer size:", c.flood_lines, 1, 999, "lines, the rest are dropped"),
                ("flood_per_user", "Lines per person:", c.flood_per_user, 1, 99, "in the buffer"),
                ("flood_ignore", "Ignore that person for:", c.flood_ignore, 0, 9999, "seconds (0 = don't ignore)"))
        for r, (attr, label, value, low, high, rest) in enumerate(rows):
            box = self._number(g, r, label, value, low, high)
            g.addWidget(QLabel(rest), r, 2)
            setattr(self, attr, box)
        g.setColumnStretch(3, 1)
        lay.addLayout(g)
        guard = [self.flood_ctcp_on] + [getattr(self, a) for a, *_ in rows]

        def flood_toggle(on: bool) -> None:
            for w in guard:
                w.setEnabled(on)
        self.flood_on.toggled.connect(flood_toggle)
        flood_toggle(c.flood_on)
        lay.addWidget(_heading("Private Chats"))
        g = QGridLayout()
        self.flood_queries = self._number(g, 0, "New private chats:", c.flood_queries, 0, 99)
        g.addWidget(QLabel("a minute, more go to the server tab"), 0, 2)
        self.flood_whois = self._number(g, 1, "WhoIs on new private chats:", c.flood_whois, 0, 99)
        g.addWidget(QLabel("a minute"), 1, 2)
        g.setColumnStretch(3, 1)
        lay.addLayout(g)
        lay.addWidget(QLabel("0 = never. When a limit is hit, BChat says so once in the server tab."))
        row = QHBoxLayout()
        row.addStretch(1)
        back = QPushButton(icon("revert"), "Back to Normal")
        back.setAutoDefault(False)
        back.clicked.connect(self._flood_defaults)
        row.addWidget(back)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _flood_defaults(self) -> None:
        d = self.FLOOD_DEFAULTS
        self.flood_pace.setCurrentIndex(d["pace"])
        self.flood_on.setChecked(d["on"])
        self.flood_ctcp_on.setChecked(d["ctcp_on"])
        for key in ("bytes", "lines", "per_user", "ignore", "queries", "whois"):
            getattr(self, "flood_" + key).setValue(d[key])

    # --- File transfers: trusted people (0.6.0) -------------------------------------------------

    def _trust_fill(self, keep: int | None = None) -> None:
        self.trust_list.clear()
        for e in self.trusted:
            self.trust_list.addTopLevelItem(QTreeWidgetItem([e.get("nick", ""), e.get("mask", ""), e.get("net", "") or "All networks"]))
        if keep is not None and 0 <= keep < self.trust_list.topLevelItemCount():
            self.trust_list.setCurrentItem(self.trust_list.topLevelItem(keep))

    def _trust_row(self) -> int:
        it = self.trust_list.currentItem()
        return self.trust_list.indexOfTopLevelItem(it) if it is not None else -1

    def _trust_dialog(self, entry: dict | None):
        from .dcc import TrustDialog
        d = TrustDialog(self, entry or {}, [n.name for n in self.cfg.networks])
        self.trust_dialog = d
        return d

    def _trust_add(self) -> None:
        d = self._trust_dialog(None)

        def done(code):
            if code:
                self.trusted.append(d.entry())
                self._trust_fill(len(self.trusted) - 1)
        d.finished.connect(done)
        d.open()

    def _trust_edit(self) -> None:
        i = self._trust_row()
        if i < 0:
            return
        d = self._trust_dialog(self.trusted[i])

        def done(code):
            if code:
                self.trusted[i] = d.entry()
                self._trust_fill(i)
        d.finished.connect(done)
        d.open()

    def _trust_remove(self) -> None:
        i = self._trust_row()
        if i >= 0:
            del self.trusted[i]
            self._trust_fill(min(i, len(self.trusted) - 1))

    def _trusted_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Trusted People"))
        lay.addWidget(QLabel("Files and direct chats from these people are accepted by themselves\n"
                             "when Options sets File offers or Direct chat offers to \"Accept from trusted people\"."))
        self.trusted = [dict(e) for e in c.dcc_trusted]
        self.trust_list = QTreeWidget()
        self.trust_list.setHeaderLabels(["Nick", "Address", "Network"])
        self.trust_list.setRootIsDecorated(False)
        self.trust_list.setColumnWidth(0, 110)
        self.trust_list.setColumnWidth(1, 210)
        self.trust_list.setMinimumHeight(120)
        self.trust_list.itemDoubleClicked.connect(lambda *_: self._trust_edit())
        lay.addWidget(self.trust_list, 1)
        row = QHBoxLayout()
        for label, ic, slot in (("Add...", "add", self._trust_add), ("Edit...", "edit", self._trust_edit), ("Remove", "remove", self._trust_remove)):
            btn = QPushButton(icon(ic), label)
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._trust_fill()
        note = QLabel("Programs always ask. A nick alone is never enough: the address must match.")
        lay.addWidget(note)
        return page

    def _files_page(self) -> QWidget:
        c = self.cfg
        page, lay = self._new_page()
        lay.addWidget(_heading("Files and Directories"))
        g = QGridLayout()
        how = ("Ask me", "Accept from trusted people", "Accept from everyone", "Ignore them")   # 0.8.10: + chats, Ignore
        self.dcc_auto = self._menu(g, 0, "File offers:", how, _OFFER_INDEX.get(c.dcc_auto, 0))
        self.chat_auto = self._menu(g, 1, "Direct chat offers:", how, _OFFER_INDEX.get(c.dcc_chat_auto, 0))
        self.dcc_dir = self._folder_row(g, 2, "Download files to:", c.dcc_dir)
        self.dcc_done = self._folder_row(g, 3, "Move completed files to:", c.dcc_done_dir)
        self.dcc_dir.setPlaceholderText(str(self.win.cfg_dir / "downloads"))   # 0.8.6: empty showed no folder at all
        self.dcc_done.setPlaceholderText("Leave them where they were downloaded")
        lay.addLayout(g)
        self.dcc_nick = self._check(lay, "Save nick name in filenames", c.dcc_with_nick)
        lay.addWidget(_heading("Sending Files"))   # 0.8.9 QA note 2: before Ports, which Passive leaves unused
        g = QGridLayout()                      # 0.8.9: passive DCC for people behind a router
        modes = ("auto", "normal", "passive")
        self.dcc_send_mode = self._menu(g, 0, "Send files:", ("Auto", "Normal", "Passive"),
                                        modes.index(c.dcc_send_mode) if c.dcc_send_mode in modes else 0)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        how = QLabel("Auto: passive when people can't reach you (home-network address and the router doesn't open a "
                     "port). Passive: the other person opens the port and you connect to them.")
        how.setWordWrap(True)
        how.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(how)
        lay.addWidget(_heading("Ports"))
        g = QGridLayout()                      # one row: first and last port side by side
        self.dcc_first = self._number(g, 0, "First DCC send port:", c.dcc_first_port, 0, 65535)
        right = QGridLayout()
        self.dcc_last = self._number(right, 0, "Last:", c.dcc_last_port, 0, 65535)
        g.addLayout(right, 0, 2)
        g.setColumnMinimumWidth(1, 120)
        g.setColumnStretch(3, 1)
        lay.addLayout(g)
        where = QLabel("The address file offers carry is on Network > Local.")
        where.setStyleSheet(f"color: {c.theme.muted};")
        lay.addWidget(where)
        lay.addWidget(_heading("Maximum File Transfer Speeds (KB/s, 0 = no limit)"))
        g = QGridLayout()                      # two columns: uploads left, downloads right (room for Trusted people)
        self.dcc_up = self._number(g, 0, "One upload:", c.dcc_max_send, 0, 999999)
        self.dcc_up_all = self._number(g, 1, "All uploads:", c.dcc_max_send_all, 0, 999999)
        right = QGridLayout()
        self.dcc_down = self._number(right, 0, "One download:", c.dcc_max_get, 0, 999999)
        self.dcc_down_all = self._number(right, 1, "All downloads:", c.dcc_max_get_all, 0, 999999)
        g.addLayout(right, 0, 2, 2, 1)
        g.setColumnMinimumWidth(1, 120)
        g.setColumnStretch(3, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("Time-outs (seconds, 0 = wait for ever)"))
        g = QGridLayout()
        self.dcc_offer_wait = self._number(g, 0, "An offer waits for an answer:", c.dcc_offer_timeout, 0, 99999)
        self.dcc_idle_wait = self._number(g, 1, "A transfer gets nothing for:", c.dcc_idle_timeout, 0, 99999)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("If the File Already Exists"))
        g = QGridLayout()
        exists = ("ask", "resume", "overwrite")
        self.dcc_exists = self._menu(g, 0, "When a file is accepted on its own:", ("Ask me", "Resume", "Overwrite"),
                                     exists.index(c.dcc_exists) if c.dcc_exists in exists else 0)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        lay.addWidget(_heading("File Types"))
        self.dcc_ignore_on = self._check(lay, "Use the file type list", c.dcc_ignore_on)
        row = QHBoxLayout()
        self.dcc_ignore_group = QButtonGroup(page)
        self.dcc_never = QRadioButton("Never accept these")
        self.dcc_only = QRadioButton("Only accept these")
        for b in (self.dcc_never, self.dcc_only):
            self.dcc_ignore_group.addButton(b)
            row.addWidget(b)
        (self.dcc_only if c.dcc_ignore_mode == "accept" else self.dcc_never).setChecked(True)
        row.addStretch(1)
        lay.addLayout(row)
        self.dcc_exts = QLineEdit(" ".join(c.dcc_ignore_exts))
        self.dcc_exts.setToolTip("Masks with spaces between, like *.exe *.scr")
        lay.addWidget(self.dcc_exts)

        def types_on(on: bool) -> None:
            for w in (self.dcc_never, self.dcc_only, self.dcc_exts):
                w.setEnabled(on)
        self.dcc_ignore_on.toggled.connect(types_on)
        types_on(c.dcc_ignore_on)
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
        modes = ("auto", "ipv4", "ipv6")
        self.ip_mode = self._menu(g, 1, "Internet:", ("Automatic", "IPv4 only", "IPv6 only"),
                                  modes.index(c.ip_mode) if c.ip_mode in modes else 0)
        lay.addLayout(g)
        self.bind_strict = self._check(lay, "If this address is gone (VPN off), don't connect at all", c.bind_strict)
        self.dcc_ipv6 = self._check(lay, "Use IPv6 for file transfers and direct chats when you have it", c.dcc_ipv6)
        lay.addWidget(QLabel("Only useful for computers with multiple addresses. Without the tick BChat uses\n"
                             "your normal address when the bind address is missing."))
        lay.addWidget(_heading("Proxy Server"))
        g = QGridLayout()
        kinds = PROXY_KINDS               # 0.8.8: Socks4 / Socks4a added at the end, older indexes unchanged
        self.proxy_type = self._menu(g, 0, "Type:", ("(Disabled)", "Socks5", "HTTP", "Socks4", "Socks4a"),
                                     kinds.index(c.proxy_type) if c.proxy_type in kinds else 0)
        self.proxy_host = self._entry(g, 1, "Hostname:", c.proxy_host)
        self.proxy_port = self._number(g, 2, "Port:", c.proxy_port, 0, 65535)
        self.proxy_skip = self._entry(g, 3, "Not for:", c.proxy_skip)                        # 0.8.10
        self.proxy_skip.setPlaceholderText("localhost, 127.0.0.1, *.lan")
        hint = QLabel("These servers connect directly. Commas between names; * stands for any part.")
        hint.setStyleSheet(f"color: {c.theme.muted};")
        hint.setWordWrap(True)
        g.addWidget(hint, 4, 1)
        g.setColumnStretch(1, 1)                       # the Type menu stays left when the rows below hide
        g.setColumnMinimumWidth(0, max(g.itemAtPosition(r, 0).widget().sizeHint().width() for r in range(3)))
        lay.addLayout(g)                               # ...and does not shift right when they show
        self._proxy_grid = g
        self.proxy_auth = self._check(lay, "Use a login", c.proxy_auth)
        g = QGridLayout()
        g.setContentsMargins(18, 0, 0, 0)
        self.proxy_user = self._entry(g, 0, "Username:", c.proxy_user)
        self.proxy_pass = self._entry(g, 1, "Password:", c.proxy_password, secret=True)
        self.proxy_no_pass = QLabel("Socks4 has no password")
        self.proxy_no_pass.setStyleSheet(f"color: {c.theme.muted};")
        g.addWidget(self.proxy_no_pass, 0, 2)
        lay.addLayout(g)
        self._login_grid = g
        self.proxy_type.currentIndexChanged.connect(self._proxy_rows)
        self.proxy_auth.toggled.connect(self._proxy_rows)
        lay.addWidget(_heading("Ident <span style='font-weight: normal'>(identification)</span>"))   # 0.8.8
        self.identd_on = self._check(lay, "Answer ident requests while connecting", c.identd_on,
                                     "Port 113, only from the moment BChat connects until the server welcomes you.")
        g = QGridLayout()
        g.setContentsMargins(18, 0, 0, 0)
        self.identd_user = self._entry(g, 0, "User ID:", c.identd_user)
        self.identd_user.setPlaceholderText(c.username or "bchat")
        lay.addLayout(g)
        self._ident_label = g.itemAtPosition(0, 0).widget()
        self.identd_on.toggled.connect(self._ident_rows)
        lay.addWidget(_heading("Router <span style='font-weight: normal'>(UPnP)</span>"))           # 0.8.8
        self.upnp_on = self._check(lay, "Open file-transfer ports on my router automatically", c.upnp_on,
                                   "Asks your router (UPnP) to forward the file-transfer ports while BChat runs.")
        self.upnp_status = QLabel()
        self.upnp_status.setContentsMargins(18, 0, 0, 0)
        lay.addWidget(self.upnp_status)
        self._upnp_status_changed(getattr(getattr(self.win, "upnp", None), "status", ""))
        if getattr(self.win, "upnp", None) is not None:
            self.win.upnp.changed.connect(self._upnp_status_changed)
        self.upnp_on.toggled.connect(lambda _=False: self._upnp_status_changed(self._upnp_text))
        self._proxy_rows()
        self._ident_rows()
        lay.addStretch(1)
        return page

    def _proxy_rows(self, *_) -> None:
        """Only the rows that this proxy type uses are shown: none without a proxy, User ID alone for Socks4."""
        kind = PROXY_KINDS[self.proxy_type.currentIndex()]
        on, socks4 = kind != "none", kind in ("socks4", "socks4a")
        for row in (1, 2, 3, 4):
            for col in (0, 1):
                item = self._proxy_grid.itemAtPosition(row, col)
                if item is not None:                   # the hint row has no label
                    item.widget().setVisible(on)
        self.proxy_auth.setVisible(on and not socks4)
        login = on and (socks4 or self.proxy_auth.isChecked())
        self._login_grid.itemAtPosition(0, 0).widget().setText("User ID:" if socks4 else "Username:")
        for row, col in ((0, 0), (0, 1)):
            self._login_grid.itemAtPosition(row, col).widget().setVisible(login)
        for col in (0, 1):
            self._login_grid.itemAtPosition(1, col).widget().setVisible(login and not socks4)
        self.proxy_no_pass.setVisible(login and socks4)

    def _ident_rows(self, *_) -> None:
        on = self.identd_on.isChecked()
        self.identd_user.setEnabled(on)
        self._ident_label.setEnabled(on)

    _upnp_text = ""

    def _upnp_status_changed(self, text: str) -> None:
        """Router status with a coloured dot: green open, red refused, muted for anything else. Hidden when off."""
        self._upnp_text = text
        try:
            t = self.cfg.theme
            if text.startswith("Router found ·"):
                dot, colour = "●", t.status_on
            elif text.startswith("Router found"):
                dot, colour = "●", t.status_off
            else:
                dot, colour = "○", t.muted
            self.upnp_status.setText(f"<span style='color: {colour}'>{dot}</span> "
                                     f"<span style='color: {t.muted}'>{html.escape(text)}</span>" if text else "")
            self.upnp_status.setVisible(bool(text) and self.upnp_on.isChecked())
        except RuntimeError:                               # the dialog is gone
            pass

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
        page = QWidget(self._page_area())
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
        c.shade_lines, c.line_rules = self.shade_lines.isChecked(), self.line_rules.isChecked()
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
        c.single_msg_window = self.single_msg.isChecked()
        c.single_msg_friends, c.single_msg_copy = self.single_friends.isChecked(), self.single_copy.isChecked()
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
        c.sound_volume = self.sound_volume.value()                  # 0.8.8 volume and Speech
        c.speak_hilights, c.speak_private = self.speak_hilights.isChecked(), self.speak_private.isChecked()
        c.speak_notices, c.speak_only_away = self.speak_notices.isChecked(), self.speak_only_away.isChecked()
        c.speak_voice, c.speak_rate = self.speak_voice.currentData() or "", self.speak_rate.value()
        c.reconnect_delay = self.reconnect.value()
        c.server_timeout = self.server_timeout.value()
        c.connect_retries = self.connect_retries.value()
        c.connect_timeout = self.connect_timeout.value()
        c.invisible = self.invisible.isChecked()
        c.move_to_top = self.move_top.isChecked()
        c.dcc_auto = _OFFER_INDEX[self.dcc_auto.currentIndex()]
        c.dcc_chat_auto = _OFFER_INDEX[self.chat_auto.currentIndex()]
        c.proxy_skip = self.proxy_skip.text().strip()
        c.dcc_trusted = [dict(e) for e in self.trusted]
        c.flood_pace = ("careful", "normal", "fast")[self.flood_pace.currentIndex()]
        c.flood_on, c.flood_ctcp_on = self.flood_on.isChecked(), self.flood_ctcp_on.isChecked()
        c.flood_bytes, c.flood_lines = self.flood_bytes.value(), self.flood_lines.value()
        c.flood_per_user, c.flood_ignore = self.flood_per_user.value(), self.flood_ignore.value()
        c.flood_queries, c.flood_whois = self.flood_queries.value(), self.flood_whois.value()
        c.dcc_dir, c.dcc_done_dir = self.dcc_dir.text().strip(), self.dcc_done.text().strip()
        c.dcc_with_nick = self.dcc_nick.isChecked()
        c.dcc_offer_timeout, c.dcc_idle_timeout = self.dcc_offer_wait.value(), self.dcc_idle_wait.value()
        c.dcc_send_mode = ("auto", "normal", "passive")[self.dcc_send_mode.currentIndex()]
        c.dcc_exists = ("ask", "resume", "overwrite")[self.dcc_exists.currentIndex()]
        c.dcc_ignore_on = self.dcc_ignore_on.isChecked()
        c.dcc_ignore_mode = "accept" if self.dcc_only.isChecked() else "ignore"
        c.dcc_ignore_exts = [m for m in self.dcc_exts.text().replace(",", " ").split() if m]
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
        self._apply_lock()
        c.ip_mode = ("auto", "ipv4", "ipv6")[self.ip_mode.currentIndex()]
        c.bind_strict, c.dcc_ipv6 = self.bind_strict.isChecked(), self.dcc_ipv6.isChecked()
        c.proxy_port = self.proxy_port.value()
        c.proxy_type = PROXY_KINDS[self.proxy_type.currentIndex()]
        c.identd_on, c.identd_user = self.identd_on.isChecked(), self.identd_user.text().strip()
        c.upnp_on = self.upnp_on.isChecked()
        c.proxy_auth, c.proxy_user, c.proxy_password = self.proxy_auth.isChecked(), self.proxy_user.text().strip(), self.proxy_pass.text()
        # 0.8.7: Settings > Windows (the nick list's choice is saved above, as User list > Execute command) + CTCP
        c.show_whois, c.show_notices = self.show_whois.currentData(), self.show_notices.currentData()
        c.show_ctcp, c.show_away, c.show_nicks = self.show_ctcp.currentData(), self.show_away.currentData(), self.show_nicks.currentData()
        for kind, box in self.dbl.items():
            setattr(c, "dbl_" + kind, box.currentData())
            setattr(c, f"dbl_{kind}_cmd", self.dbl_cmd[kind].text().strip())
        c.ctcp_reply_enabled = self.ctcp_reply.isChecked()
        for f in fields(Theme):   # in place: the user list and tabs hold this same Theme object
            setattr(c.theme, f.name, list(self.theme.palette) if f.name == "palette" else getattr(self.theme, f.name))
        self.win.apply_preferences()
        super().accept()


def new_password(parent) -> str:
    """Lock > Set Password: typed twice, at least 4 characters. '' = cancelled."""
    from .widgets import FramedDialog, run_dialog
    dlg = FramedDialog("BChat: Lock Password", parent)
    g = QGridLayout()
    one, two = QLineEdit(), QLineEdit()
    for i, (label, e) in enumerate((("Password:", one), ("Again:", two))):
        e.setEchoMode(QLineEdit.EchoMode.Password)
        g.addWidget(QLabel(label), i, 0, Qt.AlignmentFlag.AlignRight)
        g.addWidget(e, i, 1)
    dlg.body.addLayout(g)
    why = QLabel("")
    dlg.body.addWidget(why)
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton(icon("close-light"), "&Cancel")
    cancel.setAutoDefault(False)
    cancel.clicked.connect(dlg.reject)
    ok = QPushButton(icon("save"), "&OK")
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    dlg.body.addLayout(row)

    def check():
        good = len(one.text()) >= 4 and one.text() == two.text()
        ok.setEnabled(good)
        why.setText("" if good or not one.text() else "At least 4 characters, the same twice.")
    one.textChanged.connect(lambda _: check())
    two.textChanged.connect(lambda _: check())
    check()
    dlg.resize(320, 0)
    return one.text() if run_dialog(dlg) else ""
