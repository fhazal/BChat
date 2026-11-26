"""0.9.2: Settings > General can close a channel's tab when I leave it or am kicked (keep_on_part, keep_on_kick)."""
import json

from bchat import config
from bchat.preferences import PreferencesDialog
from test_060 import joined
from test_live import live_with, make_win, wait


def server_texts(s):
    return [l.text for l in s.server_buffer.lines]


def test_defaults_keep_the_tab_and_old_config_loads_them(tmp_path):
    cfg = config.Config()
    assert cfg.keep_on_kick is True and cfg.keep_on_part is True
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "rejoin_on_kick": True}), encoding="utf-8")
    old = config.load(tmp_path)
    assert old.keep_on_kick is True and old.keep_on_part is True
    (tmp_path / "config.json").write_text(json.dumps({"nick": "x", "keep_on_part": False}), encoding="utf-8")
    assert config.load(tmp_path).keep_on_part is False


def test_own_part_closes_the_tab_when_not_kept(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    win.cfg.keep_on_part = False
    srv.send(":Badaboom!u@h PART #skinhead")
    assert wait(app, lambda: "#skinhead" not in s.buffers)
    assert any("#skinhead" in t for t in server_texts(s))
    assert "#skinhead" not in [b.name for b in s.all_buffers()]
    assert win.buf is not None and win.buf.name != "#skinhead"
    assert s._left                                   # left on purpose: a reconnect doesn't join it again
    assert not [x for x in srv.received if x.startswith("PART")]
    win.close(); srv.stop()


def test_own_part_keeps_the_tab_by_default(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    srv.send(":Badaboom!u@h PART #skinhead")
    assert wait(app, lambda: not b.joined)
    assert s.buffers.get("#skinhead") is b
    assert any("You have left" in l.text or "#skinhead" in l.text for l in b.lines[-1:])
    win.close(); srv.stop()


def test_closing_the_tab_with_x_then_part_echo_is_quiet(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.cfg.keep_on_part = False
    win.close_buffer(b)
    assert "#skinhead" not in s.buffers
    assert wait(app, lambda: any(x.startswith("PART") for x in srv.received))
    before = len(s.server_buffer.lines)
    srv.send(":Badaboom!u@h PART #skinhead")
    wait(app, lambda: False, 300)
    assert len(s.server_buffer.lines) == before and "#skinhead" not in s.buffers
    assert sum(x.startswith("PART") for x in srv.received) == 1
    win.close(); srv.stop()


def test_kick_closes_the_tab_when_not_kept(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    joined(app, srv, s)
    win.cfg.keep_on_kick = False
    srv.send(":Belon!b@h KICK #skinhead Badaboom :behave")
    assert wait(app, lambda: "#skinhead" not in s.buffers)
    assert any("Belon" in t and "behave" in t for t in server_texts(s))
    assert win.buf is not None and win.buf.name != "#skinhead"
    win.close(); srv.stop()


def test_kick_keeps_the_tab_by_default(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    srv.send(":Belon!b@h KICK #skinhead Badaboom :behave")
    assert wait(app, lambda: not b.joined)
    assert s.buffers.get("#skinhead") is b
    assert any("behave" in l.text for l in b.lines)
    win.close(); srv.stop()


def test_rejoin_on_kick_wins_over_closing(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.cfg.keep_on_kick, win.cfg.rejoin_on_kick = False, True
    n = sum(x.startswith("JOIN") for x in srv.received)
    srv.send(":Belon!b@h KICK #skinhead Badaboom :behave")
    assert wait(app, lambda: not b.joined)
    assert s.buffers.get("#skinhead") is b
    assert wait(app, lambda: sum(x.startswith("JOIN") for x in srv.received) > n, 6000)
    win.close(); srv.stop()


def test_other_peoples_part_and_kick_leave_the_tab(app, tmp_path):
    srv, win, net, s = live_with(app, tmp_path)
    b = joined(app, srv, s)
    win.cfg.keep_on_kick = win.cfg.keep_on_part = False
    srv.send(":Belon!b@h PART #skinhead")
    srv.send(":Op!o@h KICK #skinhead Wira :out")
    assert wait(app, lambda: "wira" not in b.users and "belon" not in b.users)
    assert s.buffers.get("#skinhead") is b and b.joined
    win.close(); srv.stop()


def test_settings_checkboxes(app, tmp_path):
    win, _net = make_win(tmp_path, 9)
    d = PreferencesDialog(win, "General")
    assert d.keep_kick.text() == "Keep the channel tab open when I'm kicked"
    assert d.keep_part.text() == "Keep the channel tab open when I leave it"
    assert d.keep_kick.isChecked() and d.keep_part.isChecked() and d.keep_kick.isEnabled()
    d.rejoin_kick.setChecked(True)
    assert not d.keep_kick.isEnabled() and "Rejoin" in d.keep_kick.toolTip()
    d.rejoin_kick.setChecked(False)
    assert d.keep_kick.isEnabled() and d.keep_kick.toolTip().startswith("Off:")
    d.keep_kick.setChecked(False)
    d.keep_part.setChecked(False)
    d.accept(); d.deleteLater()
    assert win.cfg.keep_on_kick is False and win.cfg.keep_on_part is False
    d = PreferencesDialog(win, "General")
    assert not d.keep_kick.isChecked() and not d.keep_part.isChecked()
    d.deleteLater()
    win.close()


def test_greyed_keep_on_kick_shows_ticked_and_keeps_own_choice(app, tmp_path):
    """QA 0.9.2: while Rejoin is on the tab IS kept, so the greyed box shows a tick; the own choice comes back."""
    win, _net = make_win(tmp_path, 9)
    win.cfg.keep_on_kick, win.cfg.rejoin_on_kick = False, False
    d = PreferencesDialog(win, "General")
    assert not d.keep_kick.isChecked() and d.keep_kick.isEnabled()
    d.rejoin_kick.setChecked(True)
    assert d.keep_kick.isChecked() and not d.keep_kick.isEnabled()
    d.rejoin_kick.setChecked(False)
    assert not d.keep_kick.isChecked() and d.keep_kick.isEnabled()
    d.rejoin_kick.setChecked(True)
    d.accept(); d.deleteLater()
    assert win.cfg.keep_on_kick is False and win.cfg.rejoin_on_kick is True
    d = PreferencesDialog(win, "General")                # opened with Rejoin on: ticked, greyed, saves the own choice
    assert d.keep_kick.isChecked() and not d.keep_kick.isEnabled()
    d.accept(); d.deleteLater()
    assert win.cfg.keep_on_kick is False
    d = PreferencesDialog(win, "General")
    d.rejoin_kick.setChecked(False)
    assert not d.keep_kick.isChecked()
    d.deleteLater()
    win.close()


def test_greyed_options_read_greyed():
    from bchat.config import make_theme
    from bchat.widgets import _sheet
    for name in ("Catppuccin Mocha", "Catppuccin Latte"):
        t = make_theme(name)
        assert f"QCheckBox:disabled, QRadioButton:disabled {{ color: {t.disabled}; }}" in _sheet(t)


def test_kicked_autojoin_channel_is_joined_again_after_a_reconnect(app):
    """QA 0.9.2 bug 1: a kick is not leaving on purpose, so a closed kicked tab still autojoins after an outage."""
    from test_085_reconnect import back, drop, feed, joined as joined_raw, joins, make
    for keep in (False, True):
        s = make(app, autojoin="#qa,#a")
        s.cfg.keep_on_kick, s.cfg.rejoin_on_kick = keep, False
        joined_raw(s, "#qa")
        joined_raw(s, "#a")
        feed(s, ":Op!o@h KICK #qa Belon :out", ":Belon!u@h PART #a")
        assert ("#qa" in s.buffers) is keep
        drop(s)
        back(s)
        s._join_all(s._conn_gen)
        assert joins(s) == ["JOIN #qa"]              # the parted #a stays out
