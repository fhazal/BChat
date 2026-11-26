"""0.9.3 (OK'd mockup "Place A + Icons 1"): the (notices) tab sits right under the network, after the folders,
and 'Private: N' counts only people. New drawn glass tree icons, (notices) gets an amber bell."""
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
    assert _rows(win) == [(0, "SkinIRC"), (1, "Channel: 1"), (2, "#skinhead"), (1, "(notices)")]
    assert (id(s), "Private") not in win.folders
    # a person opens Private: it goes between the Channel folder and (notices), and counts only the person
    srv.send(":Belon!b@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: "belon" in s.buffers)
    assert _rows(win) == [(0, "SkinIRC"), (1, "Channel: 1"), (2, "#skinhead"), (1, "Private: 1"), (2, "Belon"),
                          (1, "(notices)")]
    # Alt+1-9 / Ctrl+PageDown order follows what is shown, and every row is a tab
    assert win._switcher_order() == [s.server_buffer, s.buffers["#skinhead"], s.buffers["belon"], n]
    assert all(b is not None for b in win._switcher_order())


def test_notices_first_then_channel_and_private_folders_go_above_it(live):
    app, srv, win, s = live
    win.close_buffer(s.buffers["#skinhead"])
    assert wait(app, lambda: _rows(win) == [(0, "SkinIRC")]), _rows(win)
    _notices(app, srv, win, s)
    srv.send(":Oracle!o@h PRIVMSG Badaboom :hi")
    assert wait(app, lambda: "oracle" in s.buffers)
    assert _rows(win) == [(0, "SkinIRC"), (1, "Private: 1"), (2, "Oracle"), (1, "(notices)")]
    srv.send(":Badaboom!x@h JOIN #back")
    assert wait(app, lambda: "#back" in s.buffers)
    assert _rows(win) == [(0, "SkinIRC"), (1, "Channel: 1"), (2, "#back"), (1, "Private: 1"), (2, "Oracle"),
                          (1, "(notices)")]


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
    assert wait(app, lambda: (1, "(notices)") in _rows(win))


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


def test_glass_icons_have_their_colours():
    """Channel = blue bubble, private = green person, notices = amber bell, folder = yellow, server = blue screen."""
    from PySide6.QtCore import QSize
    st._cache.clear()

    def colours(kind):
        img = st.tree_icon(kind).pixmap(QSize(32, 32)).toImage()
        return [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height())
                if img.pixelColor(x, y).alpha() > 200]

    def share(px, test):
        return sum(1 for c in px if test(c)) / max(1, len(px))
    assert share(colours("channel"), lambda c: c.blue() > c.red() + 40) > 0.4
    assert share(colours("query"), lambda c: c.green() > c.red() + 30 and c.green() > c.blue() + 30) > 0.5
    assert share(colours("notices"), lambda c: c.red() > c.blue() + 60 and c.green() > c.blue() + 20) > 0.6
    assert share(colours("folder"), lambda c: c.red() > c.blue() + 60) > 0.6
    assert share(colours("server"), lambda c: c.blue() > c.red() + 40) > 0.3
