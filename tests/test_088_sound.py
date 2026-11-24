"""0.8.8 option A (OK'd): sounds in .wav, .mp3 and .ogg at one volume, and Speech (reading highlights, private
messages and notices aloud) on Settings > Sound, plus /speak. Players run muted and the speech engine is Qt's silent
"mock" one (conftest.py), so nothing is heard. Loopback sockets only."""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog

import conftest
from bchat import config, sound, speech
from bchat.config import Config
from bchat.protocol import strip_format
from test_live import live, make_win, prefs, wait  # noqa: F401  (live is a fixture)

DEFAULT_VOICE = "System default" if sys.platform.startswith("linux") else "Windows default"

DATA = Path(__file__).with_name("data")
NEW_FIELDS = ("sound_volume", "speak_hilights", "speak_private", "speak_notices", "speak_voice", "speak_rate",
              "speak_only_away")


def _settle(app, ms=200):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture
def player(app):
    """A fresh player that writes what it reports into a list."""
    p = sound.Player()
    said = []
    p.report = said.append
    yield p, said
    p.stop()


class Talker:
    """Stands in for the speech engine: records what would be read aloud."""

    def __init__(self, ok=True):
        self.ok, self.said, self.stopped = ok, [], 0

    def available(self):
        return self.ok

    def voices(self):
        return ["Ana", "Ben"] if self.ok else []

    def say(self, text, voice="", rate=0):
        if not self.ok:
            return False
        self.said.append((speech.cap(speech.clean(text)), voice, rate))
        return True

    def stop(self):
        self.stopped += 1


@pytest.fixture
def talker(monkeypatch):
    t = Talker()
    monkeypatch.setattr(speech, "_SPEAKER", t)
    return t


# --- config ----------------------------------------------------------------------------------------------------------

def test_defaults():
    c = Config()
    assert c.sound_volume == 100
    assert (c.speak_hilights, c.speak_private, c.speak_notices) == (False, False, False)
    assert c.speak_voice == "" and c.speak_rate == 0 and c.speak_only_away is True


def test_old_config_without_new_fields_gets_defaults(tmp_path):
    config.save(Config(nick="Old", sounds={"hilight": r"C:\x.wav"}), tmp_path)
    p = tmp_path / "config.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for k in NEW_FIELDS:
        d.pop(k, None)
    p.write_text(json.dumps(d), encoding="utf-8")
    c = config.load(tmp_path)
    fresh = Config()
    assert all(getattr(c, k) == getattr(fresh, k) for k in NEW_FIELDS)
    assert c.nick == "Old" and c.sounds == {"hilight": r"C:\x.wav"}


def test_settings_save_and_reload(app, tmp_path, talker):
    win, _ = make_win(tmp_path, 1)

    def change(d):
        d.sound_volume.setValue(35)
        d.speak_hilights.setChecked(True)
        d.speak_notices.setChecked(True)
        d.speak_only_away.setChecked(False)
        d.speak_voice.setCurrentIndex(d.speak_voice.findData("Ben"))
        d.speak_rate.setValue(-4)
        d.sound_edits["hilight"].setText(str(DATA / "tone.ogg"))
    prefs(win, change)
    c = win.cfg
    assert (c.sound_volume, c.speak_hilights, c.speak_private, c.speak_notices, c.speak_only_away) == (35, True, False, True, False)
    assert (c.speak_voice, c.speak_rate) == ("Ben", -4) and c.sounds["hilight"].endswith("tone.ogg")
    config.save(c, tmp_path)
    back = config.load(tmp_path)
    assert all(getattr(back, k) == getattr(c, k) for k in NEW_FIELDS)
    from bchat.preferences import PreferencesDialog               # the page shows the saved values again
    d = PreferencesDialog(win)
    assert d.sound_volume.value() == 35 and d.sound_volume_text.text() == "35 %"
    assert d.speak_hilights.isChecked() and not d.speak_private.isChecked() and d.speak_notices.isChecked()
    assert not d.speak_only_away.isChecked() and d.speak_voice.currentText() == "Ben" and d.speak_rate.value() == -4
    assert d.speak_voice.itemText(0) == DEFAULT_VOICE and d.speak_voice.itemData(0) == ""
    d.reject(); win.close()


# --- sounds ----------------------------------------------------------------------------------------------------------

def test_all_three_formats_in_every_file_picker(app, tmp_path, monkeypatch):
    assert sound.EXTENSIONS == (".wav", ".mp3", ".ogg")
    for ext in ("*.wav", "*.mp3", "*.ogg"):
        assert ext in sound.FILTER
    asked = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a: (asked.append(a[3]), ("", ""))[1]))
    win, _ = make_win(tmp_path, 1)
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    d.show_page("Sound")
    from PySide6.QtWidgets import QPushButton
    browse = [b for b in d.pages.currentWidget().findChildren(QPushButton) if b.text() == "Browse..."]
    assert len(browse) == len(d.sound_edits)
    plays = [b for b in d.pages.currentWidget().findChildren(QPushButton) if b.text() == "Play"]
    assert len(plays) == len(d.sound_edits)                       # every event row has its preview button
    browse[0].click()
    assert asked == [sound.FILTER]
    d.reject()
    from bchat import frienddialog, highlightdialog                # the friend and highlight pickers use the same list
    for mod in (frienddialog, highlightdialog):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "from .sound import FILTER" in src and "*.wav)" not in src, mod.__name__
    win.close()


@pytest.mark.parametrize("name, volume", [("tone.mp3", 100), ("tone.ogg", 100), ("tone.wav", 60)])
def test_each_format_plays_to_the_end(app, player, name, volume):
    p, said = player
    assert p.play(str(DATA / name), volume) is True
    assert p.playing() == 1
    pl, out = p._playing[0]
    assert out.isMuted() and abs(out.volume() - volume / 100) < 0.01
    assert wait(app, lambda: p.playing() == 0, 8000), "never reached the end"
    assert said == []


def test_wav_at_full_volume_plays_as_before(app, player):
    p, said = player
    conftest.SOUNDS_PLAYED.clear()
    assert p.play(str(DATA / "tone.wav"), 100) is True
    on_qt = 0 if os.name == "nt" else 1      # Windows: the quick .wav path; Linux: the Qt player, like other files
    assert conftest.SOUNDS_PLAYED == [str(DATA / "tone.wav")] and p.playing() == on_qt and said == []


def test_volume_is_applied_everywhere(app, tmp_path, monkeypatch):
    win, _ = make_win(tmp_path, 1)
    got = []
    monkeypatch.setattr(sound, "play", lambda path, volume=100: got.append((Path(path).name, volume)) or True)
    win.cfg.sound_volume = 30
    win.cfg.sounds["hilight"] = str(DATA / "tone.mp3")
    win._last_sound = -100.0
    assert win._play_sound("hilight") is True
    win._last_chime = -100.0
    win.play_soft_chime(wanted=True)
    from bchat.preferences import PreferencesDialog
    d = PreferencesDialog(win)
    d.sound_volume.setValue(70)
    d._try_sound(str(DATA / "tone.ogg"))
    d.reject()
    assert got[0] == ("tone.mp3", 30) and got[-1] == ("tone.ogg", 70)
    assert len(got) == 3 and got[1][1] == 30                      # the soft chime too
    win.close()


def test_volume_zero_is_silent_and_counts_as_played(app, player):
    p, said = player
    assert p.play(str(DATA / "tone.mp3"), 0) is True and p.playing() == 0 and said == []


def test_overlapping_sounds_never_pile_up(app, player):
    p, said = player
    for i in range(10):
        assert p.play(str(DATA / ("tone.mp3" if i % 2 else "tone.ogg")), 50)
        assert p.playing() <= sound.MAX_AT_ONCE
    _settle(app)
    assert wait(app, lambda: p.playing() == 0, 8000) and said == []


def test_bad_or_missing_file_reported_once(app, player, tmp_path):
    p, said = player
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"this is not a sound" * 50)
    for _ in range(3):
        p.play(str(bad), 80)
    assert wait(app, lambda: p.playing() == 0, 8000)
    _settle(app)
    assert len(said) == 1 and "broken.mp3" in said[0] and "couldn't be played" in said[0]
    gone = tmp_path / "gone.ogg"
    assert p.play(str(gone)) is False and p.play(str(gone)) is False
    assert len(said) == 2 and "isn't there any more" in said[1]
    txt = tmp_path / "notes.txt"
    txt.write_text("x")
    assert p.play(str(txt)) is False and "isn't a .wav, .mp3 or .ogg file" in said[2]
    assert p.play("") is False and len(said) == 3


def test_bad_file_goes_to_the_server_tab(live, tmp_path):
    app, srv, win, s = live
    bad = tmp_path / "broken.ogg"
    bad.write_bytes(b"\0" * 4000)
    win.cfg.sounds["priv"] = str(bad)
    old = sound.player()._failed.copy()
    for _ in range(2):
        win._last_sound = -100.0
        win._play_sound("priv")
        wait(app, lambda: sound.player().playing() == 0, 8000)
    _settle(app)
    lines = [strip_format(l.text) for l in s.server_buffer.lines if "broken.ogg" in l.text]
    assert len(lines) == 1 and "couldn't be played" in lines[0]
    sound.player()._failed = old


def test_splay_plays_all_three_and_stops(live, monkeypatch):
    app, srv, win, s = live
    got = []
    monkeypatch.setattr(sound, "play", lambda path, volume=100: got.append((Path(path).suffix, volume)) or True)
    stopped = []
    monkeypatch.setattr(sound.player(), "stop", lambda: stopped.append(1))
    win.cfg.sound_volume = 55
    for name in ("tone.wav", "tone.mp3", "tone.ogg"):
        win.run_command(s, f'/splay "{DATA / name}"')
    assert got == [(".wav", 55), (".mp3", 55), (".ogg", 55)]
    win.run_command(s, "/splay stop")
    assert stopped == [1]
    win.run_command(s, f"/splay {Path(__file__)}")
    assert any("/splay plays .wav, .mp3 and .ogg files." in l.text for l in win.buf.lines)


# --- speech ----------------------------------------------------------------------------------------------------------

def test_spoken_text_format():
    assert speech.event_text("hilight", "ana", "#chat", "the server is back") == "ana in #chat: the server is back"
    assert speech.event_text("priv", "ana", "ana", "hi") == "ana privately: hi"
    assert speech.event_text("notice", "ana", "#chat", "text") == "notice from ana: text"
    assert speech.clean("\x02bold\x02 \x0304red\x03 see https://example.org/a?b=1 now") == "bold red see link now"
    assert speech.clean("www.example.org   and   \x1funder\x1f") == "link and under"
    long = speech.event_text("priv", "ana", "ana", "word " * 100)
    assert len(long) <= speech.MAX_CHARS and long.startswith("ana privately: word") and not long.endswith(" ")


def test_mock_engine_queues_and_stops(app):
    t = speech.Speaker()
    assert speech.ENGINE == "mock" and t.engines() == ["mock"] and t.available()
    assert t.say("first line") and t.say("second line", rate=5)
    assert t.engine().rate() == pytest.approx(0.5)
    t.stop()
    assert not t.say("")


def _hear(app, srv, line, talker, n):
    srv.send(line)
    return wait(app, lambda: len(talker.said) >= n, 3000)


def test_triggers_only_when_ticked_and_not_looking(live, talker, monkeypatch):
    app, srv, win, s = live
    active = [False]
    monkeypatch.setattr(win, "isActiveWindow", lambda: active[0])
    c = win.cfg
    hl = ":carol!c@h PRIVMSG #skinhead :Badaboom, \x02look\x02 at https://example.org"
    pm = ":dave!d@h PRIVMSG Badaboom :hi there"
    nt = ":erin!e@h NOTICE Badaboom :server is back"
    for line in (hl, pm, nt):                                     # all off (the default): nothing is read
        srv.send(line)
    _settle(app, 400)
    assert talker.said == []
    c.speak_hilights = c.speak_private = c.speak_notices = True
    active[0] = True                                              # BChat in front: still nothing
    for line in (hl, pm, nt):
        srv.send(line)
    _settle(app, 400)
    assert talker.said == []
    active[0] = False
    c.speak_voice, c.speak_rate = "Ana", 3
    assert _hear(app, srv, hl, talker, 1)
    assert _hear(app, srv, pm, talker, 2)
    assert _hear(app, srv, nt, talker, 3)
    assert [x[0] for x in talker.said] == ["carol in #skinhead: Badaboom, look at link", "dave privately: hi there",
                                           "notice from erin: server is back"]
    assert all(x[1:] == ("Ana", 3) for x in talker.said)
    c.speak_only_away = False                                     # untick "only when not active": read while looking
    active[0] = True
    assert _hear(app, srv, ":dave!d@h PRIVMSG Badaboom :again", talker, 4)
    assert talker.said[-1][0] == "dave privately: again"
    c.speak_private = False                                       # each tick on its own
    srv.send(":dave!d@h PRIVMSG Badaboom :quiet")
    assert _hear(app, srv, ":erin!e@h NOTICE Badaboom :still on", talker, 5)
    _settle(app, 200)
    assert [x[0] for x in talker.said[4:]] == ["notice from erin: still on"]


def test_services_server_notices_and_do_not_disturb_stay_quiet(live, talker, monkeypatch):
    app, srv, win, s = live
    monkeypatch.setattr(win, "isActiveWindow", lambda: False)
    c = win.cfg
    c.speak_hilights = c.speak_private = c.speak_notices = True
    srv.send(":NickServ!s@services. NOTICE Badaboom :This nickname is registered")
    srv.send(":irc.example.org NOTICE Badaboom :*** server notice")
    _settle(app, 400)
    assert talker.said == []
    c.do_not_disturb = True
    srv.send(":dave!d@h PRIVMSG Badaboom :psst")
    _settle(app, 400)
    assert talker.said == []
    c.do_not_disturb = False


def test_speak_command(live, talker):
    app, srv, win, s = live
    win.cfg.speak_voice, win.cfg.speak_rate = "Ben", -2
    win.run_command(s, "/speak hello \x02world\x02")
    assert talker.said == [("hello world", "Ben", -2)]
    win.run_command(s, "/speak off")
    assert talker.stopped == 1 and len(talker.said) == 1
    win.run_command(s, "/speak")
    assert any("SPEAK <text> | OFF" in l.text for l in win.buf.lines)
    assert srv.received[-1:] != ["SPEAK hello world"]
    from bchat import commands, everyday
    assert "speak" in commands.COMMAND_NAMES and "speak" in everyday.LOCAL and "speak" in commands.HELP


def test_speak_without_engine(live, monkeypatch):
    app, srv, win, s = live
    t = Talker(ok=False)
    monkeypatch.setattr(speech, "_SPEAKER", t)
    win.run_command(s, "/speak hello")
    assert any(speech.UNAVAILABLE in l.text for l in win.buf.lines) and t.said == []


def test_speech_group_hidden_without_engine(app, tmp_path, monkeypatch):
    from bchat.preferences import PreferencesDialog
    win, _ = make_win(tmp_path, 1)
    monkeypatch.setattr(speech, "_SPEAKER", Talker(ok=False))
    d = PreferencesDialog(win, "Sound"); d.show()
    _settle(app, 50)
    assert d.speech_box.isHidden() and d.sound_volume.isVisible()
    d.accept()                                                    # saving still works with the group hidden
    assert win.cfg.speak_hilights is False
    monkeypatch.setattr(speech, "_SPEAKER", Talker())
    d = PreferencesDialog(win, "Sound"); d.show()
    _settle(app, 50)
    assert d.speech_box.isVisible() and [d.speak_voice.itemText(i) for i in range(3)] == [DEFAULT_VOICE, "Ana", "Ben"]
    d.reject(); win.close()


def test_test_button_reads_with_the_picked_voice_and_speed(app, tmp_path, talker):
    from bchat.preferences import PreferencesDialog
    win, _ = make_win(tmp_path, 1)
    d = PreferencesDialog(win, "Sound")
    d.speak_voice.setCurrentIndex(2)
    d.speak_rate.setValue(6)
    d.speak_test.click()
    assert talker.said == [(speech.TEST_TEXT, "Ben", 6)] and talker.stopped == 1
    d.reject(); win.close()


@pytest.mark.parametrize("theme", ["Catppuccin Mocha", "Catppuccin Latte"])
def test_sound_page_fits_in_both_themes(app, tmp_path, talker, theme):
    from bchat.config import make_theme
    from bchat.preferences import PreferencesDialog
    win, _ = make_win(tmp_path, 1)
    win.cfg.theme = make_theme(theme)
    win.apply_preferences()
    d = PreferencesDialog(win, "Sound"); d.show()
    _settle(app, 50)
    area = d.pages.currentWidget()
    assert area.widget().minimumSizeHint().width() <= area.viewport().width()     # no sideways scrolling
    for w in (d.sound_volume, d.speak_hilights, d.speak_voice, d.speak_rate, d.speak_test, d.speak_only_away):
        area.ensureWidgetVisible(w); _settle(app, 10)
        assert w.isVisible() and w.visibleRegion().boundingRect().size() == w.size(), w   # nothing cut off
    d.reject()
    win.cfg.theme = make_theme("Catppuccin Mocha")                # the app's palette is shared by later tests
    win.apply_preferences()
    win.close()
