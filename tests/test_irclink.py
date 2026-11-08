"""irc:// and ircs:// links: reading them, the question, joining a known or a new network, links from the browser."""
import time

from fake_ircd import FakeIrcd
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from bchat import config
from bchat.config import Config, NetworkConfig, Server
from bchat.irclink import IrcLinkDialog, parse_irc_url
from bchat.mainwindow import MainWindow
from bchat.protocol import lower, split_urls


def wait(app, cond, ms=4000):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_links_are_read_like_other_clients_do():
    a = parse_irc_url("irc://irc.libera.chat/#python")
    assert (a.host, a.port, a.tls, a.channels) == ("irc.libera.chat", 6667, False, ["#python"])
    b = parse_irc_url("ircs://irc.libera.chat/python")
    assert (b.port, b.tls, b.channels) == (6697, True, ["#python"])
    c = parse_irc_url("irc://irc.bajubesi.org:6697/%23chat")
    assert (c.port, c.tls, c.channels) == (6697, True, ["#chat"])
    d = parse_irc_url("irc://IRC.Example.net:6667/secret,needkey?key=pw")
    assert (d.host, d.channels, d.key) == ("irc.example.net", ["#secret"], "pw")
    assert parse_irc_url("irc://irc.example.net/someone,isnick").channels == []
    assert parse_irc_url("irc://irc.example.net").channels == []
    for bad in ("http://irc.example.net/#x", "irc:///#x", "irc://nodot/#x", "irc://h.net/#a\x07b", "irc://h.net:99999/#x"):
        assert parse_irc_url(bad) is None, bad
    assert split_urls("see irc://irc.libera.chat/#python, ok") == [("see ", False), ("irc://irc.libera.chat/#python", True), (", ok", False)]


def _win(tmp_path, port):
    net = NetworkConfig("BajuBesi", [Server("127.0.0.1", port, False)], autojoin="#skinhead")
    win = MainWindow(Config(nick="Badaboom", nick2="b2", networks=[net], skip_network_list=True), tmp_path)
    win.skip_quit_prompt = True
    win.show()
    return win, net


def test_known_network_asks_then_joins_in_a_new_tab(app, tmp_path):
    srv = FakeIrcd()
    win, net = _win(tmp_path, srv.port)
    s = win.connect_network(net)
    assert wait(app, lambda: "#skinhead" in s.buffers and s.buffers["#skinhead"].joined)
    d = win.open_irc_link(f"irc://127.0.0.1:{srv.port}/#chat")
    assert isinstance(d, IrcLinkDialog) and d.isVisible()
    assert d.head.text() == "Join #chat" and "You're connected here" in d.line.text()
    assert d.lock.text() == "Not encrypted" and d.join_btn.isDefault()
    assert not any(x.startswith("JOIN #chat") for x in srv.received)         # nothing before the click
    d.join_btn.click()
    assert wait(app, lambda: "#chat" in s.buffers and s.buffers["#chat"].joined)
    assert wait(app, lambda: win.buf is s.buffers["#chat"])
    assert win.open_irc_link(f"irc://127.0.0.1:{srv.port}/#chat") is None      # already in: just shows it
    d2 = win.open_irc_link(f"irc://127.0.0.1:{srv.port}/#other")
    d2.cancel_btn.click()
    wait(app, lambda: False, 300)
    assert not any("#other" in x for x in srv.received)                        # Cancel = nothing at all
    win.close(); srv.stop()


def test_new_network_gets_its_own_server_tab_and_joins(app, tmp_path):
    home, other = FakeIrcd(), FakeIrcd()
    win, net = _win(tmp_path, home.port)
    url = f"irc://localhost:{other.port}/#python"
    d = win.open_irc_link(url)
    assert "New network" in d.line.text() and "Badaboom" in d.line.text()
    d.join_btn.click()
    assert wait(app, lambda: "localhost" in win.sessions)
    s = win.sessions["localhost"]
    assert wait(app, lambda: "#python" in s.buffers and s.buffers["#python"].joined)
    assert "NICK Badaboom" in other.received and "JOIN #python" in other.received
    assert wait(app, lambda: win.buf is s.buffers["#python"])
    saved = config.load(tmp_path)
    added = next(n for n in saved.networks if n.name == "localhost")
    assert added.servers[0].port == other.port and not added.autojoin       # in the list, the channel isn't saved
    assert not any("python" in x for x in home.received)
    win.close(); home.stop(); other.stop()


def test_encrypted_link_shows_the_green_badge(app, tmp_path):
    win, _net = _win(tmp_path, 1)
    d = win.open_irc_link("ircs://irc.libera.chat/#python")
    assert d.head.text() == "Join #python" and d.lock.text() == "Encrypted"
    d.reject()
    d = win.open_irc_link("irc://irc.libera.chat")
    assert d.head.text() == "Connect to irc.libera.chat" and d.join_btn.text().replace("&", "") == "Connect"
    d.reject()
    win.close()


def test_clicking_an_irc_link_in_chat_asks(app, tmp_path):
    win, _net = _win(tmp_path, 1)
    seen = []
    win.open_irc_link = lambda u: seen.append(u)
    win.chat._open_url(QUrl("irc://irc.libera.chat/#python"))
    assert seen == ["irc://irc.libera.chat/#python"]
    win.close()


def test_link_from_the_browser_goes_to_the_running_bchat(app, tmp_path):
    from bchat.__main__ import hand_to_running, listen_for_links
    win, _net = _win(tmp_path, 1)
    seen = []
    win.open_irc_link = lambda u: seen.append(u)
    assert not hand_to_running(tmp_path / "nobody", "irc://irc.libera.chat/#python")   # nothing running there
    srv = listen_for_links(win, tmp_path)
    assert srv.isListening()
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    code = ("import sys; from pathlib import Path; from PySide6.QtCore import QCoreApplication; a = QCoreApplication([]); "
            "from bchat.__main__ import hand_to_running; sys.exit(0 if hand_to_running(Path(sys.argv[1]), sys.argv[2]) else 3)")
    p = subprocess.Popen([sys.executable, "-c", code, str(tmp_path), "irc://irc.libera.chat/#python"], cwd=root)
    assert wait(app, lambda: p.poll() is not None, 10000) and p.returncode == 0
    assert wait(app, lambda: seen == ["irc://irc.libera.chat/#python"])
    srv.close(); win.close()
