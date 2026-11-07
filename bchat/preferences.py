"""Settings > Preferences, laid out like XChat 2: Categories tree on the left, one page on the right.

Built so far (mockup OK'd 2026-11-07): Text box and Colors. The other categories are greyed until each has
its own mockup. Nothing changes until OK; Cancel and the red button throw the edits away.
"""
from __future__ import annotations

from dataclasses import fields

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QFontDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox, QStackedWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .config import Config, Theme
from .widgets import FramedDialog, icon

CATEGORIES = {"Interface": ["Text box", "Input box", "User list", "Channel switcher", "Colors"],
              "Chatting": ["Alerts", "General", "Logging", "Sound"],
              "Network": ["Network setup", "File transfers"]}
BUILT = ("Text box", "Colors")
RANK_CHOICES = (("off", "Off"), ("lights", "Lights before ranked nicks"),
                ("slot", "Lights, and an empty slot for others so all text lines up"))

# Colors page: (section, [(label, Theme field), ...]); mIRC colours are the palette list
COLOUR_ROWS = [
    ("Text Colors", [("Foreground:", "chat_fg"), ("Background:", "chat_bg")]),
    ("Marking Text", [("Foreground:", "text"), ("Background:", "selected")]),
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
        reset = QPushButton("Reset to Catppuccin Mocha", page)
        reset.setAutoDefault(False)
        reset.clicked.connect(self.reset_colours)
        r = QHBoxLayout()
        r.addWidget(reset)
        r.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(r)
        lay.addStretch(1)
        return page

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

    def reset_colours(self) -> None:
        fresh = Theme()
        for f in fields(Theme):
            setattr(self.theme, f.name, list(fresh.palette) if f.name == "palette" else getattr(fresh, f.name))
        for i, sw in enumerate(self.palette_swatches):
            sw.set_colour(self.theme.palette[i])
        for field, sw in self.swatches.items():
            sw.set_colour(getattr(self.theme, field))

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
        for f in fields(Theme):   # in place: the user list and tabs hold this same Theme object
            setattr(c.theme, f.name, list(self.theme.palette) if f.name == "palette" else getattr(self.theme, f.name))
        self.win.apply_preferences()
        super().accept()
