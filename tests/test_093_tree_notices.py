"""0.9.3: the (notices) tab is the first row under the network, above the folders (owner's pick "Line A": its tree
line is one short step), and 'Private: N' counts only people. Tree icons are Lucide outlines in theme colours
(owner's pick "+ Lucide"), (notices) is a bell."""
from PySide6.QtCore import Qt

from bchat import switchertree as st
from test_live import _rows, live, wait  # noqa: F401  (live is a fixture)


def _notices(app, srv, win, s):
    win.cfg.notices_tab = True
    srv.send(":irc.fake.org NOTICE Badaboom :server says hi")
    assert wait(app, lambda: "(notices)" in s.buffers)
    return s.buffers["(notices)"]


def test_notices_sits_under_the_network_not_in_private(live):
    app, srv, win, s = live
    n = _notices(app, srv, win, s)
    top = win.items[id(s.server_buffer)]
    assert win.items[id(n)].parent() is top
    assert _rows(win) == [(0, "SkinIRC"), (1, "(notices)"), (1, "Channel: 1"), (2, "#skinhead")]
    assert (id(s), "Private") not in win.folders
    # a person opens Private: it goes after the Channel folder, and counts only the person
    srv.send(":Belon!b@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: "belon" in s.buffers)
    assert _rows(win) == [(0, "SkinIRC"), (1, "(notices)"), (1, "Channel: 1"), (2, "#skinhead"), (1, "Private: 1"),
                          (2, "Belon")]
    # Alt+1-9 / Ctrl+PageDown order follows what is shown, and every row is a tab
    assert win._switcher_order() == [s.server_buffer, n, s.buffers["#skinhead"], s.buffers["belon"]]
    assert all(b is not None for b in win._switcher_order())


def test_notices_first_then_channel_and_private_folders_go_below_it(live):
    app, srv, win, s = live
    win.close_buffer(s.buffers["#skinhead"])
    assert wait(app, lambda: _rows(win) == [(0, "SkinIRC")]), _rows(win)
    _notices(app, srv, win, s)
    srv.send(":Oracle!o@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: "oracle" in s.buffers)
    assert _rows(win) == [(0, "SkinIRC"), (1, "(notices)"), (1, "Private: 1"), (2, "Oracle")]
    srv.send(":Badaboom!x@h JOIN #back")
    assert wait(app, lambda: "#back" in s.buffers)
    assert _rows(win) == [(0, "SkinIRC"), (1, "(notices)"), (1, "Channel: 1"), (2, "#back"), (1, "Private: 1"),
                          (2, "Oracle")]


def test_closing_notices_leaves_the_folders_alone(live):
    app, srv, win, s = live
    n = _notices(app, srv, win, s)
    win.select_buffer(n)
    win.close_buffer(n)
    assert wait(app, lambda: "(notices)" not in s.buffers)
    assert _rows(win) == [(0, "SkinIRC"), (1, "Channel: 1"), (2, "#skinhead")]
    assert (id(s), "Channel") in win.folders
    # it comes back in the same place
    srv.send(":irc.fake.org NOTICE Badaboom :again")
    assert wait(app, lambda: _rows(win)[:2] == [(0, "SkinIRC"), (1, "(notices)")])


def test_notices_row_has_the_bell_and_is_a_real_tab(live):
    app, srv, win, s = live
    n = _notices(app, srv, win, s)
    it = win.items[id(n)]
    assert it.data(0, Qt.ItemDataRole.UserRole) is n
    assert it.data(0, Qt.ItemDataRole.UserRole + 1) is None          # not a folder
    assert it.icon(0).cacheKey() == st.tree_icon("notices").cacheKey()
    win.tree.setCurrentItem(it)
    assert wait(app, lambda: win.buf is n)


def test_messages_tab_stays_in_private(live):
    app, srv, win, s = live
    m = s.buffer(s.MESSAGES)
    assert wait(app, lambda: id(m) in win.items)
    assert win.items[id(m)].parent().text(0) == "Private: 1"


def test_lucide_icons_take_the_theme_colours():
    """Server = blue monitor, folder = yellow, channel = text-coloured #, private = green person, notices = yellow bell."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor
    from bchat.config import make_theme
    st._cache.clear()

    def ink(kind):
        img = st.tree_icon(kind).pixmap(QSize(32, 32)).toImage()
        px = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height())
              if img.pixelColor(x, y).alpha() > 230]
        assert px, kind
        return max({c.name() for c in px}, key=lambda n: sum(1 for c in px if c.name() == n))
    try:
        for name in ("Catppuccin Mocha", "Catppuccin Latte"):
            t = make_theme(name)
            st.set_tree_theme(t)
            for kind, field in (("server", "new_highlight"), ("folder", "highlight"), ("channel", "text"),
                                ("query", "join"), ("notices", "highlight")):
                assert ink(kind) == QColor(getattr(t, field)).name(), (name, kind)
        # a theme change gives new icons, not the cached ones
        st.set_tree_theme(make_theme("Catppuccin Mocha"))
        dark = st.tree_icon("channel").cacheKey()
        st.set_tree_theme(make_theme("Catppuccin Latte"))
        assert st.tree_icon("channel").cacheKey() != dark
    finally:
        st.set_tree_theme(None)


def test_preferences_theme_change_recolours_the_tree(live):
    from dataclasses import fields
    from bchat.config import Theme, make_theme
    app, srv, win, s = live
    latte = make_theme("Catppuccin Latte")
    for f in fields(Theme):
        setattr(win.cfg.theme, f.name, getattr(latte, f.name))
    win.apply_preferences()
    st.set_tree_theme(latte)
    assert win.items[id(s.server_buffer)].icon(0).cacheKey() == st.tree_icon("server").cacheKey()
    assert win.items[id(s.buffers["#skinhead"])].icon(0).cacheKey() == st.tree_icon("channel").cacheKey()
