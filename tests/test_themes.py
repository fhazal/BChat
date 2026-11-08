"""Themes: the six presets, the picker in Preferences > Colors, Custom, older settings, and the light theme's buttons and icons."""
import json
import time
from dataclasses import asdict, fields

import pytest
from PySide6.QtGui import QColor

from bchat import config
from bchat.config import PALETTES, THEME_NAMES, Config, Theme, is_custom, make_theme


def wait(app, cond, ms=3000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


def lum(hex_colour):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    c = QColor(hex_colour)
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_themes_dark_then_light():
    assert THEME_NAMES == ["Catppuccin Mocha", "Catppuccin Macchiato", "Catppuccin Frappé", "One Dark Pro", "Dracula",
                           "Tokyo Night", "Nord", "Gruvbox Dark", "Rosé Pine", "Solarized Dark",
                           "Catppuccin Latte", "Tokyo Night Light", "Gruvbox Light", "Rosé Pine Dawn", "Solarized Light",
                           "XChat Classic", "mIRC Modern"]
    from bchat.widgets import is_light
    for name in THEME_NAMES:                           # BChat's light-theme fixes follow the list it is in
        assert is_light(make_theme(name)) == (name in config.LIGHT_THEMES), name


def test_mocha_preset_is_exactly_the_old_default():
    assert asdict(make_theme("Catppuccin Mocha")) == asdict(Theme())
    assert not is_custom(Theme())


@pytest.mark.parametrize("name", THEME_NAMES)
def test_every_theme_is_complete_and_readable(name):
    p = PALETTES[name]
    assert len(p) == 26 and all(QColor(v).isValid() and len(v) == 7 for v in p.values())
    t = make_theme(name)
    for f in fields(Theme):
        v = getattr(t, f.name)
        if f.name == "palette":
            assert len(v) == 16 and all(QColor(c).isValid() for c in v)
        elif f.name != "name":
            assert QColor(v).isValid(), f.name
    # chat text, your text, nicks and the menu text all readable on their backgrounds (WCAG AA 4.5 for body text)
    assert contrast(t.chat_fg, t.chat_bg) >= 4.5
    assert contrast(t.self_text, t.chat_bg) >= 4.5
    assert contrast(t.text, t.window) >= 4.5
    assert contrast(t.marking_fg, t.selected) >= 3.0
    assert not is_custom(t)


def test_official_colours_where_they_come_from():
    assert PALETTES["Catppuccin Latte"]["base"] == "#eff1f5" and PALETTES["Catppuccin Frappé"]["base"] == "#303446"
    assert PALETTES["Catppuccin Macchiato"]["base"] == "#24273a"
    od = PALETTES["One Dark Pro"]
    assert (od["base"], od["text"], od["red"], od["green"], od["blue"]) == ("#282c34", "#abb2bf", "#e06c75", "#98c379", "#61afef")
    dr = PALETTES["Dracula"]
    assert (dr["base"], dr["text"], dr["pink"], dr["green"], dr["mauve"]) == ("#282a36", "#f8f8f2", "#ff79c6", "#50fa7b", "#bd93f9")
    tn = PALETTES["Tokyo Night"]
    assert (tn["base"], tn["red"], tn["blue"], tn["green"]) == ("#1a1b26", "#f7768e", "#7aa2f7", "#9ece6a")
    assert PALETTES["Tokyo Night Light"]["base"] == "#e6e7ed" and PALETTES["Tokyo Night Light"]["blue"] == "#2959aa"
    nd = PALETTES["Nord"]
    assert (nd["base"], nd["surface0"], nd["red"], nd["green"], nd["sky"]) == ("#2e3440", "#3b4252", "#bf616a", "#a3be8c", "#88c0d0")
    assert (PALETTES["Gruvbox Dark"]["base"], PALETTES["Gruvbox Dark"]["red"]) == ("#282828", "#fb4934")
    assert (PALETTES["Gruvbox Light"]["base"], PALETTES["Gruvbox Light"]["red"]) == ("#fbf1c7", "#9d0006")
    assert (PALETTES["Rosé Pine"]["base"], PALETTES["Rosé Pine"]["red"], PALETTES["Rosé Pine"]["mauve"]) == ("#191724", "#eb6f92", "#c4a7e7")
    assert (PALETTES["Rosé Pine Dawn"]["base"], PALETTES["Rosé Pine Dawn"]["text"]) == ("#faf4ed", "#464261")
    assert (PALETTES["Solarized Dark"]["base"], PALETTES["Solarized Light"]["base"], PALETTES["Solarized Dark"]["blue"]) ==         ("#002b36", "#fdf6e3", "#268bd2")
    xc, mm = make_theme("XChat Classic"), make_theme("mIRC Modern")
    assert xc.palette[2] == "#3535b3" and xc.chat_bg == "#f0f0f0" and xc.marker == "#cc1010"       # XChat 2.8.8 palette.c
    assert mm.palette[:5] == ["#ffffff", "#000000", "#00007f", "#009300", "#ff0000"] and mm.topic == "#009300"


def test_older_settings_load_as_mocha_or_custom(tmp_path):
    plain = asdict(Theme())
    plain.pop("name")          # settings from before themes had no name
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "theme": plain}), encoding="utf-8")
    cfg = config.load(tmp_path)
    assert cfg.theme.name == "Catppuccin Mocha" and not is_custom(cfg.theme)
    plain["chat_bg"] = "#000000"
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "theme": plain}), encoding="utf-8")
    assert is_custom(config.load(tmp_path).theme)


@pytest.fixture
def win(app, tmp_path):
    from bchat.mainwindow import MainWindow
    w = MainWindow(Config(nick="x", skip_network_list=True), tmp_path / "cfg")
    w.skip_quit_prompt = True
    w.show()
    wait(app, lambda: False, 100)
    yield w
    from bchat import widgets
    widgets.set_icon_theme(Theme())        # leave the white icons white for other tests
    w.hide()


def test_picker_sets_everything_then_custom_then_reset(app, win):
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win, "Colors")
    presets = len(THEME_NAMES) + 2                     # plus the Dark and Light headings
    assert d.theme_box.currentText() == "Catppuccin Mocha" and d.theme_box.count() == presets
    assert d.theme_box.itemText(0) == "Dark" and d.theme_box.itemText(len(config.DARK_THEMES) + 1) == "Light"
    assert not d.theme_box.model().item(0).isEnabled()  # headings can't be picked
    i = d.theme_box.findData("Dracula")
    d.theme_box.setCurrentIndex(i)
    d.theme_box.activated.emit(i)
    assert d.swatches["chat_bg"].colour == "#282a36" and d.palette_swatches[4].colour == "#ff5555"
    d.set_colour("chat_bg", "#000000")
    assert d.theme_box.currentText() == "Custom (based on Dracula)" and d.theme_box.count() == presets + 1
    d.reset_colours()
    assert d.theme_box.currentText() == "Dracula" and d.theme_box.count() == presets and d.swatches["chat_bg"].colour == "#282a36"
    d.set_colour("nick", "#123456")
    d.accept()
    t = win.cfg.theme
    assert t.name == "Dracula" and is_custom(t) and t.chat_bg == "#282a36" and t.nick == "#123456"
    saved = json.loads((win.cfg_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["theme"]["name"] == "Dracula"
    d2 = PreferencesDialog(win, "Colors")
    assert d2.theme_box.currentText() == "Custom (based on Dracula)"
    d2.reject()


def test_light_theme_buttons_icons_and_tree(app, win):
    from bchat.preferences import PreferencesDialog
    from bchat.widgets import icon
    menu_close = [a for a in win.findChildren(type(win.update_act)) if a.text() == "&Close"][0]
    d = PreferencesDialog(win, "Colors")
    d.theme_box.activated.emit(d.theme_box.findData("Catppuccin Latte"))
    d.accept()
    wait(app, lambda: False, 100)
    t = win.cfg.theme
    assert t.name == "Catppuccin Latte" and t.chat_bg == "#eff1f5" and t.marking_fg == t.text
    # the white close icon is tinted dark, also on the menu item that existed before the switch
    img = icon("close-light").pixmap(20, 20).toImage()
    inked = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 200]
    assert inked and all(c.lightness() < 120 for c in inked)
    assert menu_close.icon().cacheKey() == icon("close-light").cacheKey()
    # format and emoji buttons take theme colours, not Qt's fixed dark grey
    b = win.topic.buttons["bold"]
    assert t.thumb in b.styleSheet() and t.text in b.styleSheet()
    assert t.thumb in win.emoji_btn.styleSheet()
    img = b.grab().toImage()
    assert QColor(img.pixelColor(img.width() // 2, 3)).lightness() > 150
    # tree lines follow the theme
    assert win.tree.theme.tree_line == PALETTES["Catppuccin Latte"]["surface2"]


def test_coloured_nicks_use_the_theme(app, win):
    win.cfg.theme.name = "Dracula"
    c = win.chat.nick_colour("Belon")
    assert c in PALETTES["Dracula"].values()
    win.cfg.theme.name = "Catppuccin Mocha"
    assert win.chat.nick_colour("Belon") in PALETTES["Catppuccin Mocha"].values()


def test_light_fixes_only_touch_light_themes(app):
    """Spin boxes, frame lines and Qt's own colours: Latte gets theme colours, dark themes keep what they had."""
    from PySide6.QtGui import QPalette
    from bchat import widgets
    before = QPalette(app.palette())
    for name in THEME_NAMES:
        t = make_theme(name)
        sheet = widgets.stylesheet(t)
        light = name in config.LIGHT_THEMES
        assert ("QAbstractSpinBox" in sheet) == light and ('frameShape="4"' in sheet) == light
        assert sheet.startswith(widgets._sheet(t))
        widgets.set_light_palette(t)
        base = app.palette().color(QPalette.ColorRole.Base).name()
        if light:
            assert base == t.panel and app.palette().color(QPalette.ColorRole.Button).name() == t.popup
        else:
            assert app.palette() == widgets._os_palette    # exactly what Windows gave before
    widgets.set_light_palette(make_theme("Catppuccin Mocha"))
    assert app.palette() == before


def test_topic_buttons_hide_when_you_cant_change_the_topic(app, win):
    bar = win.topic
    every = [*bar.buttons.values(), bar.set_btn]
    bar.set_allowed(False, "Only channel operators can change the topic here (+t)")
    assert not any(b.isVisibleTo(bar) for b in every) and bar.edit.isReadOnly() and "+t" in bar.edit.toolTip()
    bar.set_allowed(True)
    assert all(b.isVisibleTo(bar) for b in every) and not bar.edit.isReadOnly() and bar.edit.toolTip() == ""
    # no channel in front (the server tab here): nothing to change, so no buttons
    win._refresh_all()
    assert not any(b.isVisibleTo(bar) for b in every)


def test_lucide_icons_are_all_there_and_follow_the_theme(app, win):
    """Every icon name BChat asks for is a bundled Lucide SVG, drawn in the theme's text colour,
    and menu items already showing one change colour with the theme."""
    from bchat import lucide
    from bchat.preferences import PreferencesDialog
    from bchat.widgets import ASSETS, icon
    for name, svg in lucide.NAMES.items():
        assert (ASSETS / "lucide" / f"{svg}.svg").is_file(), name
    for extra in ("message-circle", "triangle-alert", "monitor", "folder", "hash"):
        assert (ASSETS / "lucide" / f"{extra}.svg").is_file()
    assert "ISC" in (ASSETS / "lucide" / "LICENSE.txt").read_text(encoding="utf-8")
    assert not (ASSETS / "stock").exists()            # the old XChat pictures are gone

    def ink(ic):
        img = ic.pixmap(24, 24).toImage()
        cols = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 220]
        return cols
    quit_act = [a for a in win.findChildren(type(win.update_act)) if a.text() == "&Quit"][0]
    cols = ink(icon("quit"))
    assert cols and all(abs(c.lightness() - QColor(win.cfg.theme.text).lightness()) < 20 for c in cols)
    d = PreferencesDialog(win, "Colors")
    d.theme_box.activated.emit(d.theme_box.findData("Catppuccin Latte"))
    d.accept()
    cols = ink(quit_act.icon())
    assert cols and all(c.lightness() < 120 for c in cols)     # Latte's dark text colour, on the existing menu item
    from bchat.about import AboutDialog
    assert "Icons: Lucide (ISC)." in AboutDialog(win.cfg.theme, win).text()


def test_support_link_is_quiet_and_in_two_places(app, win, monkeypatch):
    """About has one calm line with the Ko-fi link, Help has one menu item; nothing else ever asks for money."""
    from PySide6.QtGui import QDesktopServices
    from bchat.about import SUPPORT
    assert SUPPORT == "https://ko-fi.com/bajubesi"
    d = win._about_box()
    assert "BChat is free and has no ads." in d.support.text() and f'href="{SUPPORT}"' in d.support.text()
    assert d.support.openExternalLinks() and not d.heart.pixmap().isNull()
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: opened.append(u.toString()) or True))
    help_menu = [a for a in win.menubar_.actions() if a.text() == "&Help"][0].menu()
    names = [a.text() for a in help_menu.actions() if not a.isSeparator()]
    assert names.index("&Support BChat on Ko-fi...") == names.index("&About") - 1
    [a for a in help_menu.actions() if a.text() == "&Support BChat on Ko-fi..."][0].trigger()
    assert opened == [SUPPORT]
