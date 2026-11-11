"""BChat's pop-up notifications: look, place, and the flood rules, including a real flood from the fake server."""
import time

import pytest
from fake_ircd import FakeIrcd
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFontMetrics, QFont, QGuiApplication

from bchat import notify as nt
from bchat.config import Config, NetworkConfig, Server, Theme


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def notifier(app):
    n = nt.Notifier(Theme())
    n.busy = lambda: False
    yield n
    n.clear()
    app.processEvents()


def test_clean_drops_colours_controls_and_long_tails():
    assert nt.clean("\x0304,01red\x03 \x02bold\x02 \x1funder\x1f  spaced\tout") == "red bold under spaced out"
    assert len(nt.clean("x" * 5000)) == nt.MAX_CHARS


def test_long_message_two_lines_then_cut(app, notifier):
    notifier.notify("priv", None, "k", "Belon", "private · SkinIRC", "word " * 200)
    c = notifier.cards[0]
    lines = c.lines(QFontMetrics(QFont("Segoe UI", 9)), 240)
    assert len(lines) == 2 and lines[1].endswith("…")


def test_same_person_updates_one_card_with_a_count(app, notifier):
    for i in range(5):
        notifier.notify("priv", None, ("s", "belon"), "Belon", "private · SkinIRC", f"line {i}")
    assert len(notifier.cards) == 1 and notifier.cards[0].count == 4 and notifier.cards[0].text == "line 4"
    assert notifier.summary is None


def test_more_than_three_people_or_too_fast_goes_into_one_summary(app, notifier):
    for i in range(3):
        notifier.last_new = 0           # pretend each came more than a second apart
        notifier.notify("priv", None, ("s", f"n{i}"), f"N{i}", "private", "hi")
    assert len(notifier.cards) == 3
    for i in range(3, 10):
        notifier.last_new = 0
        notifier.notify("priv", None, ("s", f"n{i}"), f"N{i}", "private", "hi")
    assert len(notifier.cards) == 3 and notifier.summary is not None
    assert notifier.summary.nick == "7 more messages" and notifier.summary.where == "from 7 people"
    # too fast: a 4th person a moment after a new card is held even with room
    notifier.clear(); app.processEvents()
    notifier.notify("priv", None, "a", "A", "private", "1")
    notifier.notify("priv", None, "b", "B", "private", "2")
    assert len(notifier.cards) == 1 and notifier.held == 1


def test_busy_windows_means_nothing_pops_up(app, notifier):
    notifier.busy = lambda: True
    notifier.notify("priv", None, "k", "Belon", "private", "hi")
    assert not notifier.cards and notifier.summary is None


def test_place_like_adiirc_and_never_takes_focus(app, notifier):
    notifier.notify("priv", None, "a", "A", "private", "1")
    notifier.last_new = 0
    notifier.notify("hilight", None, "b", "B", "#skinhead", "2")
    area = QGuiApplication.primaryScreen().availableGeometry()
    first, second = notifier.cards
    vis = lambda c: (c.x() + nt.PAD, c.y() + nt.PAD, c.x() + nt.PAD + nt.W, c.y() + nt.PAD + nt.H)
    l, t, r, b = vis(first)
    assert r == area.right() + 1 - nt.RIGHT and b == area.bottom() + 1 - nt.BOTTOM
    assert vis(second)[3] == t - nt.GAP          # stacked upwards, 8 points apart
    flags = first.windowFlags()
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus and flags & Qt.WindowType.WindowStaysOnTopHint
    assert first.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert QGuiApplication.focusWindow() is None or QGuiApplication.focusWindow() is not first.windowHandle()


def test_hover_keeps_it_click_opens_x_closes(app, notifier):
    opened = []
    notifier.open_requested.connect(opened.append)
    notifier.notify("priv", "BUF", "k", "Belon", "private", "hi")
    c = notifier.cards[0]
    c.enterEvent(None)
    assert not c.timer.isActive() and c.hover
    c.leaveEvent(None)
    assert c.timer.isActive()
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    press = lambda pos: c.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton,
                                                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    press(QPointF(nt.PAD + 60, nt.PAD + 40))
    assert opened == ["BUF"] and not notifier.cards
    notifier.last_new = 0
    notifier.notify("priv", "BUF2", "k2", "Belon", "private", "hi")
    press2 = notifier.cards[0]
    box = press2._close_box().center()
    press2.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, box, box, Qt.MouseButton.LeftButton,
                                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert opened == ["BUF"] and not notifier.cards


def test_cards_go_by_themselves(app, notifier, monkeypatch):
    monkeypatch.setattr(nt, "SHOW_MS", 150)
    notifier.notify("priv", None, "k", "Belon", "private", "hi")
    assert wait(app, lambda: not notifier.cards, 2000)


# --- the real thing: BChat in the tray, a flood from the fake server --------------------------------------

def make(app, tmp_path):
    srv = FakeIrcd()
    net = NetworkConfig("SkinIRC", [Server("127.0.0.1", srv.port)], autojoin="#skinhead")
    from bchat.mainwindow import MainWindow
    win = MainWindow(Config(nick="Badaboom", networks=[net]), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers)
    win.notifier.busy = lambda: False
    win.isActiveWindow = lambda: False       # BChat is in the tray / behind another window
    return srv, win, s


def test_private_message_pops_up_by_default_and_click_opens_that_chat(app, tmp_path):
    srv, win, s = make(app, tmp_path)
    assert win.cfg.alert_popup == [False, True, True]
    srv.send(":Belon!b@h PRIVMSG Badaboom :ada ok ok")
    assert wait(app, lambda: win.notifier.cards)
    c = win.notifier.cards[0]
    assert (c.kind, c.nick, c.where, c.text) == ("priv", "Belon", "private · SkinIRC", "ada ok ok")
    win.select_buffer(s.buffers["#skinhead"])
    win.notifier._clicked(c)
    assert win.buf is s.buffers["belon"]
    # a channel message stays quiet by default, a mention pops up
    win.notifier.last_new = 0
    srv.send(":Fhazal!f@h PRIVMSG #skinhead :just talking")
    srv.send(":Fhazal!f@h PRIVMSG #skinhead :Badaboom check this")
    assert wait(app, lambda: any(x.kind == "hilight" for x in win.notifier.cards))
    assert not any(x.kind == "chan" for x in win.notifier.cards)
    win.notifier.clear(); win.close(); srv.stop()


def test_flood_stays_calm_and_bchat_stays_responsive(app, tmp_path):
    srv, win, s = make(app, tmp_path)
    win.cfg.flood_queries = 99                 # this test is about the cards; the new-private-chat limit has its own
    srv.send(":Badaboom!b@h PRIVMSG Badaboom :warm up")
    # 600 private lines from 20 people, plus 200 from one spammer with colour junk and huge lines
    lines = [f":User{i % 20}!u@h PRIVMSG Badaboom :message {i}" for i in range(600)]
    lines += [f":Spammer!s@h PRIVMSG Badaboom :\x0304,01" + ("BUY NOW " * 400) for _ in range(200)]
    import threading
    t0 = time.perf_counter()
    threading.Thread(target=lambda: [srv.send(ln) for ln in lines], daemon=True).start()   # BChat keeps reading meanwhile
    assert wait(app, lambda: "spammer" in s.buffers and len(s.buffers["spammer"].lines) >= 200, 30000)
    spent = time.perf_counter() - t0
    n = win.notifier
    shown = [c for c in n.cards if c.isVisible()]
    assert len(shown) <= nt.MAX_CARDS
    assert n.summary is not None and n.summary.isVisible()
    held = int(n.summary.nick.split()[0])
    counted = sum(c.count + 1 for c in shown)
    assert held + counted == 800                          # every message accounted for, none shown twice
    assert all(len(c.text) <= nt.MAX_CHARS for c in shown)
    # BChat still answers: a timer fires on time while the cards are up
    fired = []
    from PySide6.QtCore import QTimer
    QTimer.singleShot(50, lambda: fired.append(time.perf_counter()))
    start = time.perf_counter()
    assert wait(app, lambda: fired, 2000) and fired[0] - start < 0.5
    print(f"flood of 800 handled in {spent:.2f}s, {len(shown)} cards + summary of {held}")
    n.clear(); win.close(); srv.stop()
