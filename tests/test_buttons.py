"""XChat-style buttons: round soft look, a gap between icon and words, equal widths in a row of buttons."""
import time

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton

from bchat.config import Config, make_theme
from bchat.mainwindow import MainWindow
from bchat.widgets import BUTTON_MIN_WIDTH, FramedDialog, ICON_GAP, icon, set_icon_theme, stylesheet


def spin(app, s=0.1):
    end = time.time() + s
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _dialog(win):
    d = FramedDialog("Buttons", win)
    row = QHBoxLayout()
    row.addStretch(1)
    a, b = QPushButton(icon("cancel"), "&Cancel"), QPushButton(icon("done"), "&OK")
    row.addWidget(a); row.addWidget(b)
    mixed = QHBoxLayout()
    field, browse = QLineEdit(), QPushButton("Browse...")
    mixed.addWidget(field); mixed.addWidget(browse)
    d.body.addLayout(row); d.body.addLayout(mixed)
    return d, a, b, browse


def test_button_rows_get_equal_widths_but_rows_with_fields_dont(app, tmp_path):
    win = MainWindow(Config(nick="T", skip_network_list=True, welcome_done=True), tmp_path)
    win.skip_quit_prompt = True
    d, a, b, browse = _dialog(win)
    d.show(); spin(app)
    assert a.width() == b.width() >= BUTTON_MIN_WIDTH                  # XChat's button box: same size, 85 at least
    assert browse.minimumWidth() < BUTTON_MIN_WIDTH                    # next to a field: left as it is
    d.close(); win.close()


def test_icon_and_words_have_a_gap_and_still_follow_the_theme(app, tmp_path):
    win = MainWindow(Config(nick="T", skip_network_list=True, welcome_done=True), tmp_path)
    win.skip_quit_prompt = True
    d, a, _b, _browse = _dialog(win)
    d.show(); spin(app)
    assert a.iconSize().width() == 16 + ICON_GAP and a.iconSize().height() == 16
    pm = a.icon().pixmap(a.iconSize(), 1.0).toImage()
    assert pm.width() == 16 + ICON_GAP
    assert all(pm.pixelColor(x, y).alpha() == 0 for x in range(17, 16 + ICON_GAP) for y in range(16))   # clear gap
    before = a.icon().cacheKey()
    latte = make_theme("Catppuccin Latte")
    set_icon_theme(latte, d)                                            # theme change: the icon is redrawn
    spin(app)
    assert a.icon().cacheKey() != before and a.iconSize().width() == 16 + ICON_GAP
    set_icon_theme(make_theme("Catppuccin Mocha"), d)
    d.close(); win.close()


def test_button_look_is_round_and_soft_in_dark_and_light():
    for name in ("Catppuccin Mocha", "Catppuccin Latte"):
        t = make_theme(name)
        sheet = stylesheet(t)
        assert "border-radius: 4px" in sheet and "min-height: 17px" in sheet
        fill = t.popup if name.endswith("Mocha") else t.panel
        assert f"QPushButton {{ background: {fill};" in sheet
        assert "QPushButton#modebtn" in sheet and "QPushButton#ulbtn" in sheet and "QPushButton#compact" in sheet
