"""0.8.9 Settings > File transfers > Send files: Auto / Normal / Passive.
Auto sends passive only when nobody outside can reach us. Loopback sockets only; .bin files only."""
import socket
from types import SimpleNamespace

from bchat import commands
from bchat.dcc import DccManager, home_address
from test_live import live, wait  # noqa: F401  (live is a fixture)

LOCAL = 2130706433      # 127.0.0.1 as a DCC offer writes it
HOME = "192.168.1.5"
HOME_FIELD = 3232235781  # 192.168.1.5 as a DCC offer writes it


def _offers(srv):
    return [x for x in srv.received if "DCC SEND" in x]


# --- the Auto rule ------------------------------------------------------------------------------

class _Sock:
    def __init__(self, ip):
        self.ip = ip

    def localAddress(self):
        return SimpleNamespace(toString=lambda: self.ip)


def _mgr(mode="auto", dcc_ip="", first=0, last=0, ports_open=False, upnp_on=False):
    cfg = SimpleNamespace(dcc_send_mode=mode, dcc_ip=dcc_ip, dcc_first_port=first, dcc_last_port=last, upnp_on=upnp_on)
    m = DccManager.__new__(DccManager)          # only send_passive is used: no sockets, no timers
    m.cfg = cfg
    m.win = SimpleNamespace(upnp=SimpleNamespace(ports_open=ports_open))
    return m


def test_normal_and_passive_ignore_the_address():
    s = SimpleNamespace(sock=_Sock(HOME))
    assert _mgr("passive", dcc_ip="8.8.8.8").send_passive(s) is True
    assert _mgr("normal").send_passive(s) is False


def test_auto_is_passive_only_on_a_home_network_with_nothing_open():
    home = SimpleNamespace(sock=_Sock(HOME))
    assert _mgr().send_passive(home) is True
    assert _mgr().send_passive(SimpleNamespace(sock=_Sock("10.0.0.3"))) is True
    assert _mgr().send_passive(SimpleNamespace(sock=_Sock("100.70.1.1"))) is True       # carrier NAT
    assert _mgr().send_passive(SimpleNamespace(sock=_Sock("8.8.8.8"))) is False         # a public address
    assert _mgr(ports_open=True).send_passive(home) is False                            # the router opened ports
    assert _mgr(first=5000, last=5010).send_passive(home) is False                      # a range: maybe forwarded by hand
    assert _mgr(dcc_ip="8.8.8.8").send_passive(home) is False                           # Network > Local says public
    assert _mgr(dcc_ip=HOME).send_passive(SimpleNamespace(sock=_Sock("8.8.8.8"))) is True
    assert _mgr().send_passive(SimpleNamespace(sock=_Sock("127.0.0.1"))) is False      # a bouncer on this PC
    assert _mgr().send_passive(SimpleNamespace(sock=None)) is False
    assert _mgr("something odd").send_passive(home) is True                             # unknown value = Auto


def test_auto_with_upnp_on_but_nothing_opened_is_passive():
    # QA 0.8.9 note 1: the range was for the router; it refused or wasn't found, so nobody can reach us
    home = SimpleNamespace(sock=_Sock(HOME))
    assert _mgr(first=5000, last=5010, upnp_on=True).send_passive(home) is True
    assert _mgr(first=5000, last=5010, upnp_on=True, ports_open=True).send_passive(home) is False
    assert _mgr(first=5000, last=5010, upnp_on=True).send_passive(SimpleNamespace(sock=_Sock("8.8.8.8"))) is False


def test_home_address_still_importable_from_preferences():
    from bchat.preferences import home_address as from_prefs
    assert from_prefs is home_address


# --- real offers through the fake server --------------------------------------------------------

def test_auto_on_a_home_address_sends_a_passive_offer_that_completes(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = HOME
    payload = bytes(range(256)) * 40
    src = tmp_path / "auto.bin"
    src.write_bytes(payload)
    t = win.dcc.send_file(s, "Belon", str(src))
    assert t.passive and t.token
    assert wait(app, lambda: any(f"DCC SEND auto.bin {HOME_FIELD} 0 {len(payload)} {t.token}" in x for x in srv.received)), _offers(srv)
    assert any("Offering auto.bin" in l.text and "(passive)" in l.text for b in s.buffers.values() for l in b.lines) \
        or any("(passive)" in l.text for l in s.server_buffer.lines)
    # they answer with their own port: we connect and send
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1); ls.setblocking(False)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND auto.bin {LOCAL} {ls.getsockname()[1]} {len(payload)} {t.token}\x01")
    got, conn = bytearray(), []

    def pump():
        try:
            if not conn:
                conn.append(ls.accept()[0]); conn[0].setblocking(False)
            d = conn[0].recv(65536)
            got.extend(d)
            if d:
                conn[0].send(len(got).to_bytes(4, "big"))
        except BlockingIOError:
            pass
        return t.state == "done"
    assert wait(app, pump, 5000), (t.state, t.pos, t.acked)
    assert bytes(got) == payload
    conn[0].close(); ls.close()


def test_normal_sends_the_usual_offer_even_at_home(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = HOME
    win.cfg.dcc_send_mode = "normal"
    src = tmp_path / "plain.bin"
    src.write_bytes(b"x" * 100)
    t = win.dcc.send_file(s, "Belon", str(src))
    assert not t.passive and t.port
    assert wait(app, lambda: any(f"DCC SEND plain.bin {HOME_FIELD} {t.port} 100" in x for x in srv.received)), _offers(srv)


def test_dcc_send_follows_the_setting_and_psend_is_always_passive(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "8.8.8.8"                     # public: Auto sends the usual way
    src = tmp_path / "cmd.bin"
    src.write_bytes(b"y" * 10)
    b = s.server_buffer
    with s.typed():
        commands.run(win, s, b, f"/dcc send Belon {src}")
    assert wait(app, lambda: any("DCC SEND cmd.bin 134744072 " in x and not x.rstrip("\x01").endswith(" 0 10") for x in srv.received)), _offers(srv)
    normal = [t for t in win.dcc.items if t.kind == "send"][-1]
    assert not normal.passive
    win.cfg.dcc_send_mode = "normal"
    with s.typed():
        commands.run(win, s, b, f"/dcc psend Belon {src}")
    passive = [t for t in win.dcc.items if t.kind == "send"][-1]
    assert passive.passive and passive is not normal
    assert wait(app, lambda: any(f"DCC SEND cmd.bin 134744072 0 10 {passive.token}" in x for x in srv.received)), _offers(srv)
    win.cfg.dcc_send_mode = "passive"
    with s.typed():
        commands.run(win, s, b, f"/dcc send Belon {src}")
    assert [t for t in win.dcc.items if t.kind == "send"][-1].passive


def test_nick_menu_send_follows_the_setting(live, tmp_path, monkeypatch):
    app, srv, win, s = live
    from PySide6.QtWidgets import QFileDialog
    src = tmp_path / "menu.bin"
    src.write_bytes(b"z" * 5)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(src)], "")))
    win.cfg.dcc_ip = HOME
    win.send_file_dialog(s, ["Belon"])
    assert [t for t in win.dcc.items if t.kind == "send"][-1].passive
    win.cfg.dcc_send_mode = "normal"
    win.send_file_dialog(s, ["Belon"])
    assert not [t for t in win.dcc.items if t.kind == "send"][-1].passive


# --- Settings ----------------------------------------------------------------------------------

def test_settings_row_shows_and_saves_the_choice(app, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer
    from bchat.preferences import PreferencesDialog
    from test_live import make_win
    win, _ = make_win(tmp_path, 1)
    win.cfg.dcc_send_mode = "passive"
    d = PreferencesDialog(win, "File transfers")
    d.show()
    loop = QEventLoop(); QTimer.singleShot(30, loop.quit); loop.exec()
    box = d.dcc_send_mode
    assert [box.itemText(i) for i in range(box.count())] == ["Auto", "Normal", "Passive"]
    assert box.currentText() == "Passive" and box.isVisible()
    # QA note 2: its own "Sending Files" heading, above Ports (Passive leaves the ports unused)
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QLabel
    ys = {l.text(): l.mapTo(d, QPoint(0, 0)).y() for l in d.findChildren(QLabel) if l.isVisible()}
    box_y = box.mapTo(d, QPoint(0, 0)).y()
    assert ys["<b>Files and Directories</b>"] < ys["<b>Sending Files</b>"] < box_y < ys["<b>Ports</b>"]
    box.setCurrentIndex(1)
    d.accept()
    assert win.cfg.dcc_send_mode == "normal"
    win.close()


def test_new_config_starts_on_auto():
    from bchat.config import Config
    assert Config().dcc_send_mode == "auto"


# --- UPnP tells Auto when the ports are open ----------------------------------------------------

def test_upnp_result_sets_ports_open(app):
    from bchat import upnp
    m = upnp.Manager()
    m._want = (5000, 5001)
    m._on_result(((5000, 5001), "1.2.3.4", f"{upnp.OPENED} 1.2.3.4 · ports 5000-5001 open"))
    assert m.ports_open and m.external_ip == "1.2.3.4"
    m._on_result(((5000, 5001), "", upnp.NO_ROUTER))
    assert not m.ports_open
    m._on_result(((5000, 5001), "", "Router found, but it refused to open the ports (x)"))
    assert not m.ports_open
