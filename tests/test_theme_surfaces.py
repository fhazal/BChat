"""Things BChat paints itself must sit on the surface around them, in every theme (TEST24: the update entry
in the menu bar painted a dark box of its own)."""
from dataclasses import fields
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor

from bchat import updater as up
from bchat.config import THEME_NAMES, Config, Theme, make_theme
from bchat.mainwindow import MainWindow


def set_theme(win, name):
    fresh = make_theme(name)
    for f in fields(Theme):
        setattr(win.cfg.theme, f.name, list(fresh.palette) if f.name == "palette" else getattr(fresh, f.name))
    win.apply_preferences()


@pytest.mark.parametrize("name", THEME_NAMES)
def test_update_entry_has_the_menu_bars_own_background(app, tmp_path, name):
    win = MainWindow(Config(nick="x", skip_network_list=True), tmp_path)
    win.skip_quit_prompt = True
    win.resize(900, 500)
    win.show()
    set_theme(win, name)
    win.updater._set(up.FAILED, "x")
    for _ in range(5):
        app.processEvents()
    bar = win.menubar_
    img = bar.grab().toImage()
    g = bar.actionGeometry(win.update_act)
    assert g.isValid() and g.width() > 20
    dpr = img.devicePixelRatio()
    badge = QColor(img.pixel(int((g.right() - 2) * dpr), int((g.top() + 2) * dpr)))     # inside the entry, off the text
    empty = QColor(img.pixel(int((bar.width() - 6) * dpr), int((g.top() + 2) * dpr)))   # bare menu bar on the right
    assert badge.name() == empty.name() == QColor(win.cfg.theme.window).name(), name
    win.close()
