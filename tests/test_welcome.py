"""First-start welcome window: nick rules, choices, real connects against the fake server, shown only once."""
import time

import pytest
from fake_ircd import FakeIrcd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from bchat import config, welcome
from bchat.config import Config, NetworkConfig, Server
from bchat.mainwindow import MainWindow


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def fresh(app, tmp_path):
    win = MainWindow(Config(), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    yield win
    for s in list(win.sessions.values()):
        s.disconnect_from_network()
    win.close()


@pytest.fixture
def local(monkeypatch):
    """The welcome choices point at the local fake server (plain, no SSL) instead of the real networks."""
    srv = FakeIrcd()
    monkeypatch.setattr(welcome, "Server", lambda host, port, ssl: Server("127.0.0.1", srv.port, False))
    yield srv
    srv.stop()


def test_nick_rules():
    assert welcome.nick_problem("Bee4821") == ""
    assert welcome.nick_problem("[Belon]_|^") == ""
    assert welcome.nick_problem("") == "Type a nickname."
    assert "spaces" in welcome.nick_problem("bee bee")
    assert "letter" in welcome.nick_problem("4bee")
    assert "letter" in welcome.nick_problem("-bee")
    assert "only" in welcome.nick_problem("bee!")
    assert "long" in welcome.nick_problem("b" * 31)
    for _ in range(50):
        n = welcome.random_nick()
        assert welcome.nick_problem(n) == "" and n.startswith("Bee") and len(n) == 7


def test_first_start_decides_welcome_netlist_or_nothing():
    assert welcome.first_start_action(Config(), False) == "welcome"
    assert welcome.first_start_action(Config(welcome_done=True), False) == "netlist"
    old_user = Config(networks=[NetworkConfig("SkinIRC")])          # existing users never see the welcome
    assert welcome.first_start_action(old_user, False) == "netlist"
    assert welcome.first_start_action(old_user, True) == ""
    assert welcome.first_start_action(Config(networks=[NetworkConfig("X")], skip_network_list=True), False) == ""


def test_window_defaults_and_nick_check(app, fresh):
    d = welcome.run_welcome(fresh)
    assert wait(app, d.isVisible)
    assert d.windowTitle() == "Welcome to BChat" and not d.bee.pixmap().isNull()
    assert welcome.nick_problem(d.nick.text()) == "" and d.connect_btn.isEnabled() and d.connect_btn.isDefault()
    assert not d.connect_btn.icon().isNull() and not d.own_btn.icon().isNull()     # same icons as the Network List
    assert [c.choice[0] for c in d.cards] == ["BajuBesi Community", "Libera.Chat", "OFTC"]
    assert d.chosen()[0] == "BajuBesi Community" and d.cards[0].radio.isChecked()
    assert d.chosen()[3] == "#BChat,#chat" and "joins #BChat and #chat" in d.chosen()[4]
    assert all(c.choice[2] == 6697 for c in d.cards)                 # every choice is an encrypted port
    d.nick.setText("4 bad")
    assert not d.connect_btn.isEnabled() and "spaces" in d.hint.text()
    d.connect_btn.click()
    assert d.isVisible()                                              # nothing happens with a bad nick
    d.nick.setText("Kestrel")
    assert d.connect_btn.isEnabled() and "/nick" in d.hint.text()
    QTest.mouseClick(d.cards[2], Qt.MouseButton.LeftButton, pos=QPoint(200, 10))   # click anywhere on a card
    assert d.chosen()[0] == "OFTC" and not d.cards[0].radio.isChecked()
    d.reject()


def test_bajubesi_connects_joins_bchat_and_chat_with_bchat_in_front(app, fresh, local, tmp_path):
    d = welcome.run_welcome(fresh)
    d.nick.setText("Kestrel")
    d.connect_btn.click()
    cfg = fresh.cfg
    assert cfg.welcome_done and cfg.nick == "Kestrel" and cfg.nick2 == "Kestrel_"
    net = cfg.networks[0]
    assert net.name == "BajuBesi Community" and net.autojoin == "#BChat,#chat" and net.autoconnect
    s = fresh.sessions[net.name]
    assert wait(app, lambda: "#bchat" in {k.lower() for k in s.buffers} and "#chat" in {k.lower() for k in s.buffers})
    assert "NICK Kestrel" in local.received and "JOIN #BChat,#chat" in local.received
    assert wait(app, lambda: fresh.buf is not None and fresh.buf.name.lower() == "#bchat")
    back = config.load(tmp_path)                                      # saved: next start goes straight in
    assert back.welcome_done and back.nick == "Kestrel" and back.networks[0].autoconnect
    assert welcome.first_start_action(back, False) == "netlist"


def test_bchat_stays_in_front_when_the_server_joins_chat_first(app, fresh, local):
    d = welcome.run_welcome(fresh)
    d.connect_btn.click()
    s = next(iter(fresh.sessions.values()))
    assert wait(app, lambda: s.state == "connected")
    local.send(f":{s.nick}!u@h JOIN #chat")                           # what the server's own auto-join looks like
    assert wait(app, lambda: "#bchat" in {k.lower() for k in s.buffers})
    assert wait(app, lambda: fresh.buf is not None and fresh.buf.name.lower() == "#bchat")


def test_network_without_channels_asks_which_to_join(app, fresh, local):
    d = welcome.run_welcome(fresh)
    d.cards[1].radio.setChecked(True)
    d.connect_btn.click()
    net = fresh.cfg.networks[0]
    assert net.name == "Libera.Chat" and net.autojoin == ""
    s = fresh.sessions[net.name]
    assert wait(app, lambda: getattr(fresh, "join_ask", None) is not None and fresh.join_ask.isVisible())
    assert any("You're in!" in ln.text for ln in s.server_buffer.lines)
    fresh.join_ask.setTextValue("#python")
    fresh.join_ask.accept()
    assert wait(app, lambda: "JOIN #python" in local.received)
    assert wait(app, lambda: "#python" in s.buffers)


def test_existing_network_of_the_same_name_is_reused(app, fresh, local):
    mine = NetworkConfig("BajuBesi Community", [Server("127.0.0.1", local.port)], autojoin="#mine")
    fresh.cfg.networks.append(mine)
    d = welcome.run_welcome(fresh)
    d.connect_btn.click()
    assert fresh.cfg.networks == [mine] and mine.autojoin == "#mine"


def test_set_up_my_own_opens_the_network_list(app, fresh, monkeypatch):
    opened = []
    monkeypatch.setattr(fresh, "open_network_list", lambda: opened.append(1))
    d = welcome.run_welcome(fresh)
    d.own_btn.click()
    assert wait(app, lambda: opened == [1])
    assert fresh.cfg.welcome_done and fresh.cfg.networks == [] and not fresh.sessions


def test_closing_it_is_an_answer_too(app, fresh, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(fresh, "open_network_list", lambda: opened.append(1))
    d = welcome.run_welcome(fresh)
    d.titlebar.close_clicked.emit()
    app.processEvents()
    assert fresh.cfg.welcome_done and not fresh.sessions and opened == []
    assert config.load(tmp_path).welcome_done


def test_themes_light_and_dark(app, fresh):
    from dataclasses import fields
    from bchat.config import Theme, make_theme
    for name in ("Catppuccin Latte", "Dracula"):
        t = make_theme(name)
        for f in fields(Theme):
            setattr(fresh.cfg.theme, f.name, list(t.palette) if f.name == "palette" else getattr(t, f.name))
        d = welcome.run_welcome(fresh)
        assert wait(app, d.isVisible)
        assert t.check in d.cards[0].styleSheet() and t.border in d.cards[1].styleSheet()
        d.reject()


def test_new_user_gets_a_bee_nick_and_bee_ident(tmp_path):
    from bchat import config
    cfg = config.load(tmp_path)                      # no settings yet: first start
    assert welcome.nick_problem(cfg.nick) == "" and cfg.nick.startswith("Bee") and len(cfg.nick) == 7
    assert cfg.nick2 == cfg.nick + "_" and cfg.nick3 == cfg.nick + "__"
    assert cfg.username == "bee" and cfg.realname == "BChat user"
    assert config.load(tmp_path).nick != "T"


def test_welcome_nick_change_moves_the_spare_nicks_along(app, fresh, local):
    fresh.cfg.nick, fresh.cfg.nick2, fresh.cfg.nick3 = "Bee1234", "Bee1234_", "Bee1234__"   # first-start bee
    d = welcome.run_welcome(fresh)
    assert d.nick.text() == "Bee1234"
    d.nick.setText("Kestrel")
    d.connect_btn.click()
    assert (fresh.cfg.nick, fresh.cfg.nick2, fresh.cfg.nick3) == ("Kestrel", "Kestrel_", "Kestrel__")
