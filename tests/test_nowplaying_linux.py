"""/np on Linux: MPRIS players on the session D-Bus. The parsing runs anywhere; a fake player runs where D-Bus does."""
from __future__ import annotations

import os
import shutil
import sys
import threading

import pytest

from bchat import nowplaying as np


def meta(**kw):
    return {k.replace("_", ":", 1): v for k, v in kw.items()}


def test_track_from_mpris_properties():
    player = {"PlaybackStatus": ("s", "Playing"), "Position": ("x", 83_000_000),
              "Metadata": ("a{sv}", meta(xesam_artist=("as", ["Daft Punk", "Pharrell"]), xesam_title=("s", "Get Lucky"),
                                         xesam_album=("s", "Random Access Memories"), mpris_length=("x", 248_000_000),
                                         xesam_url=("s", "file:///home/me/Music/lucky.flac")))}
    t = np.mpris_track("org.mpris.MediaPlayer2.spotify", "Spotify", player)
    assert (t.player_id, t.player, t.artist, t.title, t.album) == ("spotify", "Spotify", "Daft Punk, Pharrell",
                                                                    "Get Lucky", "Random Access Memories")
    assert t.music and (t.position, t.length) == (83.0, 248.0)


def test_paused_players_and_odd_values():
    assert np.mpris_track("org.mpris.MediaPlayer2.vlc", "VLC", {"PlaybackStatus": ("s", "Paused")}) is None
    assert np.mpris_track("org.mpris.MediaPlayer2.vlc", "VLC", {}) is None
    # a browser tab: instance number dropped, a video is not music, a single artist string still works, junk length
    t = np.mpris_track("org.mpris.MediaPlayer2.firefox.instance_1_84", "", {
        "PlaybackStatus": "Playing", "Metadata": {"xesam:artist": "Someone", "xesam:title": "Clip",
                                                  "xesam:url": "https://x.test/v.webm?t=3", "mpris:length": "junk"}})
    assert (t.player_id, t.player, t.artist, t.music, t.length) == ("firefox", "Firefox", "Someone", False, 0.0)
    assert np.is_browser(t.player_id) and np.is_browser("chromium")


def test_position_never_past_the_end():
    t = np.mpris_track("org.mpris.MediaPlayer2.x", "X", {"PlaybackStatus": "Playing", "Position": 500_000_000,
                                                        "Metadata": {"xesam:title": "T", "mpris:length": 100_000_000}})
    assert t.position == 100.0


def test_no_session_bus_means_nothing_playing(monkeypatch):
    monkeypatch.setattr(np.sys, "platform", "linux")
    monkeypatch.setattr(np, "_mpris", lambda: (_ for _ in ()).throw(ConnectionError("no bus")))
    assert np.playing() == []


ON_DBUS = pytest.mark.skipif(not sys.platform.startswith("linux") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
                             or shutil.which("dbus-daemon") is None, reason="needs a Linux session D-Bus")


def fake_player(name, status, ready, stop):
    """A tiny MPRIS player: answers GetAll(Player) and Get(Identity), then waits to be stopped."""
    from jeepney import HeaderFields, MessageType, message_bus, new_error, new_method_call, new_method_return
    from jeepney.io.blocking import open_dbus_connection
    with open_dbus_connection(bus="SESSION") as conn:
        conn.send_and_get_reply(new_method_call(message_bus, "RequestName", "su", (name, 0)))
        ready.set()
        while not stop.is_set():
            try:
                msg = conn.receive(timeout=0.2)
            except TimeoutError:
                continue
            if msg.header.message_type != MessageType.method_call:
                continue
            member = msg.header.fields.get(HeaderFields.member)
            iface = msg.body[0] if msg.body else ""
            if member == "GetAll" and iface.endswith("Player"):
                body = {"PlaybackStatus": ("s", status), "Position": ("x", 10_000_000),
                        "Metadata": ("a{sv}", {"xesam:artist": ("as", ["Artist"]), "xesam:title": ("s", "Song"),
                                               "mpris:length": ("x", 200_000_000)})}
                conn.send(new_method_return(msg, "a{sv}", (body,)))
            elif member == "Get" and msg.body[1] == "Identity":
                conn.send(new_method_return(msg, "v", (("s", "Fake Player"),)))
            else:
                conn.send(new_error(msg, "org.freedesktop.DBus.Error.UnknownMethod"))


@ON_DBUS
def test_real_session_bus_with_a_fake_player():
    stop, threads = threading.Event(), []
    for name, status in (("org.mpris.MediaPlayer2.fakeplay", "Playing"), ("org.mpris.MediaPlayer2.fakepause", "Paused")):
        ready = threading.Event()
        th = threading.Thread(target=fake_player, args=(name, status, ready, stop), daemon=True)
        th.start(); threads.append(th)
        assert ready.wait(5)
    try:
        tracks = [t for t in np.playing() if t.player_id.startswith("fake")]
        assert [(t.player_id, t.player, t.artist, t.title, t.position, t.length) for t in tracks] == \
               [("fakeplay", "Fake Player", "Artist", "Song", 10.0, 200.0)]
    finally:
        stop.set()
        for th in threads:
            th.join(2)
