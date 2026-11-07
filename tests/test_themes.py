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


def test_six_themes_in_the_users_order():
    assert THEME_NAMES == ["Catppuccin Mocha", "Catppuccin Macchiato", "Catppuccin Frappé", "Catppuccin Latte", "One Dark Pro", "Dracula"]


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
    assert d.theme_box.currentText() == "Catppuccin Mocha" and d.theme_box.count() == 6
    d.theme_box.setCurrentIndex(THEME_NAMES.index("Dracula"))
    d.theme_box.activated.emit(THEME_NAMES.index("Dracula"))
    assert d.swatches["chat_bg"].colour == "#282a36" and d.palette_swatches[4].colour == "#ff5555"
    d.set_colour("chat_bg", "#000000")
    assert d.theme_box.currentText() == "Custom (based on Dracula)" and d.theme_box.count() == 7
    d.reset_colours()
    assert d.theme_box.currentText() == "Dracula" and d.theme_box.count() == 6 and d.swatches["chat_bg"].colour == "#282a36"
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
    d.theme_box.activated.emit(THEME_NAMES.index("Catppuccin Latte"))
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
