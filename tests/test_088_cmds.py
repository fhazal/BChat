"""0.8.8 design option A, item 7: /userhost, /flush, /linesep, /font (a font for one window, kept in tab options),
Settings > Text "Shade every other line" and "Line between each message" (Mocha and Latte, after a trim, with
hidden lines, with find marks, after a theme change), the new settings saved and read back, older settings files,
and the Settings pages with the 0.8.8 rows still fitting. No server: the session thinks it is online and every line
it would send is kept in s.out."""
import json
import re
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from bchat import commands, config, extracmds, tabopts
from bchat.chatview import LINESEP
from bchat.config import Config, NetworkConfig, Server, make_theme
from bchat.protocol import parse_line
from bchat.session import ERROR, INFO, MSG

NET = NetworkConfig("N", [Server("127.0.0.1", 6667)])


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def settle(app, ms=30):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def online(win):
    s = win.session_for(NET)
    s.out = []
    s.send_raw = lambda line, secret=False, quiet=False: s.out.append(line)
    s._connect_next = lambda: None
    s._conn_gen += 1
    s._last_rx = time.time()
    s.want_connected = True
    s.state = "connected"
    s.nick = "Belon"
    feed(s, ":srv 001 Belon :Welcome", ":srv 005 Belon NETWORK=N CASEMAPPING=rfc1459 :are supported")
    return s


def new_win(tmp_path, cfg=None):
    from bchat.mainwindow import MainWindow
    win = MainWindow(cfg or Config(nick="Belon", skip_network_list=True, welcome_done=True, local_find=False), tmp_path)
    win.skip_quit_prompt = True
    win.upnp.target, win.upnp.timeout = ("127.0.0.1", 9), 0.2      # never the real router
    return win


@pytest.fixture
def ws(app, tmp_path):
    win = new_win(tmp_path)
    win.resize(900, 600)
    win.show()
    s = online(win)
    win.select_buffer(s.server_buffer)
    settle(app)
    yield win, s
    win.cfg.theme = make_theme("Catppuccin Mocha")          # the app's palette is shared by later tests
    win.apply_preferences()
    win.close()


def join(app, win, s, chan="#c", *others):
    feed(s, f":Belon!u@h JOIN {chan}", f":srv 353 Belon = {chan} :@Belon {' '.join(others)}",
         f":srv 366 Belon {chan} :End")
    b = s.buffers[s.fold(chan)]
    win.select_buffer(b)
    settle(app)
    return b


def run(win, s, b, text):
    s.out.clear()
    with s.typed():
        commands.run(win, s, b, text)
    return list(s.out)


def last(b):
    return b.lines[-1]


# --- /userhost -----------------------------------------------------------------------------------------------------

def test_userhost_asks_and_prints_here_away_and_operator(app, ws):
    win, s = ws
    b = join(app, win, s)
    assert run(win, s, b, "/userhost ana bob") == ["USERHOST ana bob"]
    feed(s, ":srv 302 Belon :ana=+ana@host bob*=-~bob@10.0.0.2")
    ln = last(b)
    assert ln.kind == INFO and ln.text == "ana is ana@host (here), bob is ~bob@10.0.0.2 (away) (IRC operator)"


def test_userhost_names_a_nick_that_is_not_on_irc(app, ws):
    win, s = ws
    b = join(app, win, s)
    run(win, s, b, "/userhost ana ghost")
    feed(s, ":srv 302 Belon :ana=+ana@host")
    assert last(b).text == "ana is ana@host (here), ghost isn't on IRC"
    run(win, s, b, "/userhost ghost")
    feed(s, ":srv 302 Belon :")
    assert last(b).text == "ghost isn't on IRC"


def test_userhost_takes_five_and_says_so(app, ws):
    win, s = ws
    b = join(app, win, s)
    out = run(win, s, b, "/userhost a b c d e f g")
    assert out == ["USERHOST a b c d e"]
    assert any(ln.text == "Servers answer for 5 nicks at a time, so only the first 5 were asked about." for ln in b.lines)


def test_userhost_without_nicks_or_offline_sends_nothing(app, ws):
    win, s = ws
    b = join(app, win, s)
    assert run(win, s, b, "/userhost") == []
    assert last(b).kind == ERROR and last(b).text == extracmds.HELP["userhost"]
    s.state = "disconnected"
    assert run(win, s, b, "/userhost ana") == []
    assert last(b).kind == ERROR and "Not connected" in last(b).text


# --- /flush --------------------------------------------------------------------------------------------------------

def test_flush_drops_waiting_lines_and_says_how_many(app, ws):
    win, s = ws
    b = join(app, win, s)
    s._queue.extend(["PRIVMSG #c :one", "PRIVMSG #c :two"])
    s._flood_lines["#c"] = __import__("collections").deque(["PRIVMSG #c :three"])
    s._flood_order.append("#c")
    run(win, s, b, "/flush")
    assert last(b).text == "Dropped 3 lines that were waiting to be sent."
    assert not s._queue and not s._flood_lines and not s._flood_order
    run(win, s, b, "/flush")
    assert last(b).text == "Nothing waiting to be sent."
    s._queue.append("PRIVMSG #c :x")
    run(win, s, b, "/flush")
    assert last(b).text == "Dropped 1 line that was waiting to be sent."


def test_flush_works_offline(app, ws):
    win, s = ws
    b = join(app, win, s)
    s.state = "disconnected"
    run(win, s, b, "/flush")
    assert last(b).text == "Nothing waiting to be sent."


# --- /linesep ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("theme", ["Catppuccin Mocha", "Catppuccin Latte"])
def test_linesep_draws_a_dim_row(app, ws, theme):
    win, s = ws
    win.cfg.theme = make_theme(theme)
    win.apply_preferences()
    b = join(app, win, s)
    s.add(b, MSG, "ana", "before")
    run(win, s, b, "/linesep")
    assert last(b).kind == LINESEP and s.out == []
    d = win.chat.view_of(b).docs[id(b)]
    block = d.lastBlock()
    assert block.text() and set(block.text()) == {"─"}            # no time stamp, nothing but the line
    fmt = block.begin().fragment().charFormat()
    assert fmt.foreground().color() == QColor(win.cfg.theme.stamp)
    win.reload_buffer(b)                                           # drawn again the same way after a rebuild
    assert set(win.chat.view_of(b).docs[id(b)].lastBlock().text()) == {"─"}


# --- /font ---------------------------------------------------------------------------------------------------------

FAMILY = "Quiet Mono"


@pytest.fixture(autouse=True)
def fonts(monkeypatch):
    """The offscreen test platform knows no fonts: these are the ones 'installed' for /font."""
    monkeypatch.setattr(extracmds, "QFontDatabase", SimpleNamespace(families=lambda: ["Arial", FAMILY]))


def a_family(cfg):
    return FAMILY


def doc_font(win, b):
    return win.chat.view_of(b).docs[id(b)].defaultFont()


def test_font_sets_shows_and_resets_one_window(app, ws):
    win, s = ws
    cfg = win.cfg
    fam = a_family(cfg)
    b = join(app, win, s)
    other = join(app, win, s, "#other")
    win.select_buffer(b)
    run(win, s, b, "/font")
    assert last(b).text == f"{b.name} uses {cfg.chat_font} {cfg.chat_font_size} pt (the chat font)."
    run(win, s, b, f"/font 15 {fam}")
    assert last(b).text == f"{b.name} uses {fam} 15 pt now."
    assert tabopts.get(cfg, b, "font") == f"{fam}|15"
    f = doc_font(win, b)
    assert f.family() == fam and f.pointSize() == 15
    assert doc_font(win, other).pointSize() == cfg.chat_font_size          # only this window
    run(win, s, b, "/font 11")                                             # size only: the family stays
    assert tabopts.get(cfg, b, "font") == f"{fam}|11" and doc_font(win, b).pointSize() == 11
    run(win, s, b, "/font")
    assert last(b).text == f"{b.name} uses {fam} 11 pt (its own). /font -d goes back to the chat font."
    run(win, s, b, "/font -d")
    assert last(b).text == f"{b.name} uses the chat font again ({cfg.chat_font} {cfg.chat_font_size} pt)."
    assert not tabopts.has_own(cfg, b, "font") and doc_font(win, b).pointSize() == cfg.chat_font_size
    assert s.out == []


def test_font_family_alone_follows_the_chat_size(app, ws):
    win, s = ws
    fam = a_family(win.cfg)
    b = join(app, win, s)
    run(win, s, b, f"/font {fam.lower()}")                                # any case: spelled the way Qt knows it
    assert tabopts.get(win.cfg, b, "font") == f"{fam}|"
    assert doc_font(win, b).family() == fam and doc_font(win, b).pointSize() == win.cfg.chat_font_size


@pytest.mark.parametrize("text, said", [
    ("/font 3", "Font size must be 4–72."),
    ("/font 73 Arial", "Font size must be 4–72."),
    ("/font 12 No Such Font Anywhere", "No font named \"No Such Font Anywhere\" on this PC. Example: /font 12 Consolas"),
])
def test_font_refuses_bad_size_and_family(app, ws, text, said):
    win, s = ws
    b = join(app, win, s)
    run(win, s, b, text)
    assert last(b).kind == ERROR and last(b).text == said
    assert not tabopts.has_own(win.cfg, b, "font")


def test_font_in_a_window_without_a_network(app, ws):
    win, s = ws
    from bchat.session import Buffer
    lone = Buffer(None, "lone", "server")
    run(win, s, lone, "/font 14")
    assert lone.lines[-1].text == "Only server, channel and private windows can have their own font."


def test_font_survives_reconnect_rejoin_and_restart(app, ws, tmp_path):
    win, s = ws
    fam = a_family(win.cfg)
    b = join(app, win, s)
    run(win, s, b, f"/font 13 {fam}")
    s.state = "disconnected"                                             # reconnect: same tab, same font
    s.state = "connected"
    feed(s, ":srv 001 Belon :Welcome")
    b = join(app, win, s)
    assert doc_font(win, b).family() == fam and doc_font(win, b).pointSize() == 13
    win.close_buffer(b)                                                  # a new tab for the same channel
    settle(app)
    b2 = join(app, win, s)
    assert b2 is not b and doc_font(win, b2).pointSize() == 13
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["tab_opts"]["n/#c"]["font"] == f"{fam}|13"
    win2 = new_win(tmp_path, config.load(tmp_path))                     # restart
    win2.show()
    try:
        s2 = online(win2)
        b3 = join(app, win2, s2)
        assert doc_font(win2, b3).family() == fam and doc_font(win2, b3).pointSize() == 13
    finally:
        win2.close()


def test_new_commands_are_in_help_and_command_lists(app, ws):
    win, s = ws
    for name in ("userhost", "flush", "linesep", "font"):
        assert name in commands.COMMAND_NAMES and commands.HELP[name] == extracmds.HELP[name]
    b = join(app, win, s)
    run(win, s, b, "/help")
    text = " ".join(ln.text for ln in b.lines[-5:])
    for name in ("/userhost", "/flush", "/linesep", "/font"):
        assert name in text


# --- shading and rules ---------------------------------------------------------------------------------------------

def blend(bg, fg, a=14):
    bg, fg = QColor(bg), QColor(fg)
    mix = lambda x, y: round(x + (y - x) * a / 255)                      # noqa: E731
    return mix(bg.red(), fg.red()), mix(bg.green(), fg.green()), mix(bg.blue(), fg.blue())


def near(c, rgb, tol=2):
    return all(abs(x - y) <= tol for x, y in zip((c.red(), c.green(), c.blue()), rgb))


def rows(app, view):
    """(block, colour at the right edge, picture, x) for every whole line on show."""
    view.viewport().update()
    settle(app, 20)
    img = view.viewport().grab().toImage()
    x, out = img.width() - 3, []
    for block, y0, y1 in view._visible_blocks():
        if y0 >= 0 and y1 <= img.height():
            out.append((block, img.pixelColor(x, int((y0 + y1) / 2)), y1))
    return out, img, x


def shaded(win, c):
    t = win.cfg.theme
    if near(c, QColor(t.chat_bg).getRgb()[:3]):
        return False
    assert near(c, blend(t.chat_bg, t.chat_fg)), (c.name(), t.chat_bg)
    return True


def fill(s, b, n, start=0):
    for i in range(start, start + n):
        s.add(b, MSG, "ana", f"line {i}")


def number(block):
    m = re.search(r"line (\d+)", block.text())
    return int(m.group(1)) if m else None


@pytest.mark.parametrize("theme", ["Catppuccin Mocha", "Catppuccin Latte"])
def test_shading_every_other_line_in_both_themes(app, ws, theme):
    win, s = ws
    win.cfg.theme = make_theme(theme)
    win.cfg.shade_lines = True
    win.apply_preferences()
    b = join(app, win, s)
    fill(s, b, 40)
    view = win.chat.view_of(b)
    got, _img, _x = rows(app, view)
    marks = [shaded(win, c) for _b, c, _y in got]
    assert len(marks) > 6 and True in marks and False in marks
    assert all(m != n for m, n in zip(marks, marks[1:]))                 # stripes: every other line
    d = view.docs[id(b)]
    blk = d.begin()
    while blk.isValid():                                                 # painted, never stored in the text
        assert blk.blockFormat().background().style() == Qt.BrushStyle.NoBrush
        blk = blk.next()


def test_shading_off_by_default_and_rules_in_the_border_colour(app, ws):
    win, s = ws
    assert not Config().shade_lines and not Config().line_rules
    b = join(app, win, s)
    fill(s, b, 30)
    view = win.chat.view_of(b)
    got, img, x = rows(app, view)
    assert not any(shaded(win, c) for _b, c, _y in got)
    border = QColor(win.cfg.theme.border).getRgb()[:3]
    on_rule = lambda y1: any(near(img.pixelColor(x, int(y1) + k), border, 0) for k in (-1, 0, 1))  # noqa: E731
    assert not any(on_rule(y1) for _b, _c, y1 in got[:-1])
    win.cfg.line_rules = True
    win.apply_preferences()
    view = win.chat.view_of(b)
    got, img, x = rows(app, view)
    assert len(got) > 5 and all(on_rule(y1) for _b, _c, y1 in got[:-1])


def test_shading_keeps_its_stripes_through_a_trim(app, ws):
    win, s = ws
    win.cfg.shade_lines, win.cfg.max_lines = True, 100
    win.apply_preferences()
    b = join(app, win, s)
    view = win.chat.view_of(b)
    d = view.docs[id(b)]
    fill(s, b, 140)
    assert d.blockCount() <= 150 and not d.property("bchat_dropped")
    before = {number(blk): shaded(win, c) for blk, c, _y in rows(app, view)[0] if number(blk) is not None}
    fill(s, b, 25, start=140)                                            # past 150 lines: 51 dropped, an odd number
    assert d.property("bchat_dropped") == 51 and d.blockCount() < 150
    got = rows(app, view)[0]
    after = {number(blk): shaded(win, c) for blk, c, _y in got if number(blk) is not None}
    marks = [shaded(win, c) for _b, c, _y in got]
    assert all(m != n for m, n in zip(marks, marks[1:]))
    odd = {n % 2: v for n, v in before.items()}                          # line N is shaded iff N has one parity
    assert len(odd) == 2 and odd[0] != odd[1]
    assert all(v == odd[n % 2] for n, v in after.items()), (odd, after)


def test_shading_with_hidden_lines_find_marks_and_a_theme_change(app, ws):
    win, s = ws
    win.cfg.shade_lines = True
    win.apply_preferences()
    b = join(app, win, s)
    for i in range(30):
        s.add(b, MSG, "ana", f"line {i}")
        if i % 3 == 0:
            s.add(b, INFO, "*", f"hidden {i}", hidden=True)               # a join/part line hidden in this tab
    view = win.chat.view_of(b)
    d = view.docs[id(b)]
    assert "hidden" not in d.toPlainText()
    marks = [shaded(win, c) for _b, c, _y in rows(app, view)[0]]
    assert len(marks) > 6 and all(m != n for m, n in zip(marks, marks[1:]))
    win.search_action.trigger()                                          # find marks on every line
    win.find_bar.edit.setText("line")
    settle(app, 400)
    assert view.extraSelections()
    marks = [shaded(win, c) for _b, c, _y in rows(app, view)[0]]
    assert all(m != n for m, n in zip(marks, marks[1:])) and True in marks
    win.find_bar.close_bar() if hasattr(win.find_bar, "close_bar") else win.find_bar.hide()
    win.cfg.theme = make_theme("Catppuccin Latte")                      # the shade follows the new theme
    win.apply_preferences()
    view = win.chat.view_of(b)
    marks = [shaded(win, c) for _b, c, _y in rows(app, view)[0]]
    assert True in marks and all(m != n for m, n in zip(marks, marks[1:]))


# --- settings -------------------------------------------------------------------------------------------------------

def test_new_settings_save_and_read_back(app, ws, tmp_path):
    win, s = ws
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    d.shade_lines.setChecked(True)
    d.line_rules.setChecked(True)
    d.identd_on.setChecked(True)
    d.identd_user.setText("  belon  ")
    d.upnp_on.setChecked(True)
    d.accept()
    d.deleteLater()
    c = config.load(tmp_path)
    assert (c.shade_lines, c.line_rules, c.identd_on, c.identd_user, c.upnp_on) == (True, True, True, "belon", True)
    d = PreferencesDialog(win)                                            # and Settings shows them again
    assert d.shade_lines.isChecked() and d.line_rules.isChecked() and d.identd_on.isChecked()
    assert d.identd_user.text() == "belon" and d.upnp_on.isChecked()
    d.upnp_on.setChecked(False)
    d.accept()
    d.deleteLater()
    assert not config.load(tmp_path).upnp_on


def test_older_settings_file_gets_the_defaults(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "tab_opts": {"n/#c": {"timestamps": False}}}),
                                          encoding="utf-8")
    c = config.load(tmp_path)
    assert (c.shade_lines, c.line_rules, c.identd_on, c.identd_user, c.upnp_on) == (False, False, False, "", False)
    assert "font" not in c.tab_opts["n/#c"]


@pytest.mark.parametrize("theme", ["Catppuccin Mocha", "Catppuccin Latte"])
@pytest.mark.parametrize("page", ["Text box", "Network setup"])
def test_settings_pages_with_the_new_rows_still_fit(app, ws, theme, page):
    win, s = ws
    from bchat.preferences import PreferencesDialog
    win.cfg.theme = make_theme(theme)
    win.apply_preferences()
    d = PreferencesDialog(win, page)
    d.show()
    settle(app, 50)
    if page == "Network setup":                                          # show the login rows too
        d.proxy_type.setCurrentIndex(1); d.proxy_auth.setChecked(True); settle(app, 20)
    area, here = d.pages.currentWidget(), d.page_widget(page)
    assert here.minimumSizeHint().width() <= area.viewport().width()     # no sideways scrolling
    rows_ = {"Text box": (d.shade_lines, d.line_rules),
             "Network setup": (d.proxy_type, d.proxy_user, d.identd_on, d.identd_user, d.upnp_on)}[page]
    for w in rows_:
        area.ensureWidgetVisible(w); settle(app, 10)
        assert w.isVisible() and w.visibleRegion().boundingRect().size() == w.size(), w   # nothing cut off
    d.reject()
