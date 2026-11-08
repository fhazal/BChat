"""/np: the song playing now, from Windows' own media controls (the box that pops up with the volume keys),
plus classic Winamp's window title. Nothing to set up. Privacy first: off until the user turns it on, music only,
only players the user allows (browsers start unticked), and only when /np is typed."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Qt, QTimer, Signal

DEFAULT_LINE = "is listening to {artist} – {title} ({album}) · {player} · {time}"
BROWSERS = ("chrome", "msedge", "edge", "firefox", "opera", "brave", "vivaldi", "browser", "arc")
NAMES = {"spotify": "Spotify", "applemusic": "Apple Music", "itunes": "iTunes", "musicbee": "MusicBee", "aimp": "AIMP",
         "foobar2000": "foobar2000", "potplayer": "PotPlayer", "vlc": "VLC", "zunemusic": "Media Player",
         "microsoft.media.player": "Media Player", "chrome": "Google Chrome", "msedge": "Microsoft Edge",
         "firefox": "Firefox", "opera": "Opera", "brave": "Brave", "tidal": "TIDAL", "deezer": "Deezer",
         "winamp": "Winamp", "mpc-hc": "Media Player Classic", "musiccube": "MusikCube", "mediamonkey": "MediaMonkey"}
WINAMP = "winamp"


@dataclass
class Track:
    player_id: str
    player: str
    artist: str = ""
    title: str = ""
    album: str = ""
    music: bool = True
    position: float = 0.0
    length: float = 0.0


def player_name(app_id: str) -> str:
    low = app_id.lower()
    for key, name in NAMES.items():
        if key in low.replace(" ", ""):
            return name
    tail = re.split(r"[!\\/]", app_id)[-1] if "!" in app_id else re.split(r"[\\/]", app_id)[-1]
    tail = re.sub(r"\.exe$", "", tail, flags=re.I)
    return tail or app_id


def is_browser(app_id: str) -> bool:
    return any(b in app_id.lower() for b in BROWSERS)


def tidy(t: Track) -> Track:
    """Apple Music puts "Artist — Album" in the artist and leaves the album empty."""
    if not t.album and " — " in t.artist:
        t.artist, _, t.album = t.artist.partition(" — ")
    t.artist, t.title, t.album = t.artist.strip(), t.title.strip(), t.album.strip()
    if t.album and t.album.lower() == t.title.lower():
        t.album = ""
    return t


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def render(template: str, t: Track) -> str:
    """Fill the line; parts with nothing in them (no album, no time) leave no empty brackets or dots behind."""
    when = ""
    if t.length > 0:
        when = f"{_clock(t.position)} / {_clock(t.length)}" if t.position > 0 else _clock(t.length)
    values = {"artist": t.artist, "title": t.title, "album": t.album, "player": t.player, "time": when}
    line = template or DEFAULT_LINE
    line = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)) if m.group(1) in values else m.group(0), line)
    line = re.sub(r"\s*\(\s*\)", "", line)                         # "()" left by an empty album
    line = re.sub(r"(\s*·\s*)+$", "", line)                    # a dot with nothing after it
    line = re.sub(r"(\s*·\s*){2,}", " · ", line)
    line = re.sub(r"\s+–\s*$", "", line).strip()
    if t.artist and t.title:                                        # bold artist and title, grey the rest after them
        line = line.replace(t.artist, f"\x02{t.artist}\x02", 1).replace(t.title, f"\x02{t.title}\x02", 1)
    return line


# --- reading what plays ------------------------------------------------------------------

def _windows_media() -> list[Track]:
    import asyncio
    from datetime import datetime, timezone
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

    async def read():
        out = []
        mgr = await M.request_async()
        for s in mgr.get_sessions():
            if int(s.get_playback_info().playback_status) != 4:         # 4 = Playing
                continue
            info = await s.try_get_media_properties_async()
            tl = s.get_timeline_properties()
            pos = tl.position.total_seconds()
            try:
                pos += (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds()   # it moved on since
            except (TypeError, ValueError):
                pass
            length = tl.end_time.total_seconds()
            app = s.source_app_user_model_id or ""
            out.append(Track(app, player_name(app), info.artist or "", info.title or "", info.album_title or "",
                             int(info.playback_type) == 1, max(0.0, min(pos, length or pos)), length))
        return out
    return asyncio.run(read())


def _winamp() -> list[Track]:
    """Classic Winamp shows "123. Artist - Title - Winamp" in its window title; paused or stopped says so."""
    import ctypes
    u = ctypes.windll.user32
    h = u.FindWindowW("Winamp v1.x", None)
    if not h:
        return []
    n = u.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, buf, n + 1)
    title = buf.value
    if not title.endswith(" - Winamp") or "[Paused]" in title or "[Stopped]" in title:
        return []
    song = re.sub(r"^\d+\.\s*", "", title[: -len(" - Winamp")])
    artist, sep, name = song.partition(" - ")
    return [Track(WINAMP, "Winamp", artist if sep else "", name if sep else song, "", True)]


def playing() -> list[Track]:
    tracks: list[Track] = []
    try:
        tracks += _windows_media()
    except Exception:          # no media controls (old Windows, missing parts): Winamp may still answer
        pass
    try:
        tracks += _winamp()
    except Exception:
        pass
    return [tidy(t) for t in tracks]


def choose(tracks: list[Track], cfg) -> tuple[Track | None, str]:
    """The track /np may share, or why there is none. Players seen are remembered for Preferences."""
    for t in tracks:
        if t.player_id not in cfg.np_players:
            cfg.np_players[t.player_id] = not is_browser(t.player_id)     # browsers start unticked
        cfg.np_names[t.player_id] = t.player
    if not tracks:
        return None, "Nothing is playing right now (or the player doesn't tell Windows)."
    allowed = [t for t in tracks if cfg.np_players.get(t.player_id)]
    if not allowed:
        return None, f"Nothing to share: {', '.join(sorted({t.player for t in tracks}))} isn't ticked in Preferences > Chatting > Now Playing."
    if cfg.np_music_only:
        music = [t for t in allowed if t.music]
        if not music:
            return None, f"Nothing to share: the only thing playing is a video ({', '.join(sorted({t.player for t in allowed}))})."
        allowed = music
    t = allowed[0]
    if not t.title:
        return None, f"Nothing to share: {t.player} doesn't say what's playing."
    return t, ""


def at(t: Track, seconds_later: float) -> Track:
    """The same track a little later: the clock moves on while the preview window is open."""
    if t.length <= 0 or t.position <= 0:
        return t
    return replace(t, position=min(t.length, t.position + max(0.0, seconds_later)))


ANNOUNCE_AFTER = 5.0           # a new song is posted once it has played this long: skipped songs never are
POLL_MS = 2000


def announce_channels(text: str) -> list[str]:
    """"Net A/#chat, #skinhead #x" -> ["Net A/#chat", "#skinhead", "#x"]: commas between entries (network names may
    have spaces), spaces only between plain channels; no doubles, as typed."""
    out: list[str] = []
    for part in (text or "").split(","):
        part = part.strip()
        for name in ([part] if "/" in part else part.split()):
            if name and name.lower() not in [n.lower() for n in out]:
                out.append(name)
    return out


def announce_targets(text: str) -> list[tuple[str, str]]:
    """"ZNC-Belon-BSN/#skinhead, #chat" -> [("ZNC-Belon-BSN", "#skinhead"), ("", "#chat")]. No network = every network."""
    out = []
    for entry in announce_channels(text):
        net, sep, chan = entry.rpartition("/")
        out.append((net if sep else "", chan if sep else entry))
    return out


def announces_in(text: str, network: str, channel: str, this_network_only: bool = False) -> bool:
    lo = str.lower
    return any(lo(c) == lo(channel) and ((not n and not this_network_only) or lo(n) == lo(network))
               for n, c in announce_targets(text))


class Announcer(QObject):
    """Announce each new song: off unless the user turned on both /np and announcing, and named the channels.
    Same rules as /np (ticked players, music only), plus: a song counts once it has played ANNOUNCE_AFTER seconds,
    and each song is posted once, however often it is paused and resumed."""
    _read = Signal(object)

    def __init__(self, cfg, post, parent=None, reader=None):
        super().__init__(parent)
        self.cfg, self.post = cfg, post            # post(track): the window sends it to the channels
        self.reader = reader or playing
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.poll)
        self._read.connect(self._seen)
        self.busy = False
        self.current = None                        # (player, artist, title) playing now
        self.since = 0.0
        self.posted = None
        self.clock = time.monotonic

    def on(self) -> bool:
        c = self.cfg
        return bool(c.np_enabled and c.np_announce and announce_channels(c.np_announce_in))

    def refresh(self) -> None:
        if self.on():
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()
            self.current = None

    def poll(self) -> None:
        if self.busy or not self.on():
            return
        self.busy = True

        def work():
            try:
                tracks = self.reader()
            except Exception:
                tracks = []
            self._read.emit(tracks)
        threading.Thread(target=work, daemon=True).start()

    def _seen(self, tracks) -> None:
        self.busy = False
        if not self.on():
            return
        t, _why = choose(tracks, self.cfg)
        key = (t.player_id, t.artist, t.title) if t is not None else None
        now = self.clock()
        if key != self.current:
            self.current, self.since = key, now
            return
        if key is not None and key != self.posted and now - self.since >= ANNOUNCE_AFTER:
            self.posted = key
            self.post(replace(t, position=0.0))    # the song's length, not "0:05 / 3:21"


class NowPlaying(QObject):
    """Reads in the background (Windows can take a moment), answers on the GUI thread."""
    found = Signal(object, str)      # Track or None, reason

    def __init__(self, cfg, parent=None, reader=None):
        super().__init__(parent)
        self.cfg = cfg
        self.reader = reader or playing

    def ask(self) -> None:
        def work():
            try:
                tracks = self.reader()
            except Exception:
                tracks = []
            t, why = choose(tracks, self.cfg)
            self.found.emit(t, why)
        threading.Thread(target=work, daemon=True).start()


def ask_dialog(win, target: str, track: Track, template: str = ""):
    """"Send this to #chan?" with the exact line, before anything is sent. The time keeps counting while it is open,
    and d.current_line() is what Send sends."""
    from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
    from .protocol import strip_format
    from .widgets import FramedDialog, icon
    t = win.cfg.theme
    d = FramedDialog("Now Playing", win)
    d.choice = ""
    d.setFixedWidth(500)
    d.body.setContentsMargins(22, 18, 22, 16)
    d.body.setSpacing(10)
    d.head = QLabel(f"Send this to {target}?")
    d.head.setTextFormat(Qt.TextFormat.PlainText)
    d.head.setStyleSheet(f"color: {t.title}; font-size: 12pt; font-weight: bold;")
    d.body.addWidget(d.head)
    card = QFrame(objectName="card")
    card.setStyleSheet(f"#card {{ border: 1px solid {t.border}; border-radius: 6px; background: {t.panel}; }}")
    cl = QVBoxLayout(card)
    cl.setContentsMargins(12, 10, 12, 10)
    opened = time.monotonic()
    d.current_line = lambda: render(template or DEFAULT_LINE, at(track, time.monotonic() - opened))
    who = win.session.nick if win.session else ""
    d.line = QLabel()
    d.line.setTextFormat(Qt.TextFormat.PlainText)

    def tick():
        d.line.setText(f"* {who} {strip_format(d.current_line())}")
    tick()
    d.clock = QTimer(d)
    d.clock.setInterval(1000)
    d.clock.timeout.connect(tick)
    d.clock.start()
    d.line.setWordWrap(True)
    cl.addWidget(d.line)
    d.body.addWidget(card)
    d.again = QCheckBox("Don't ask again")
    d.body.addWidget(d.again)
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    d.body.addWidget(sep)
    row = QHBoxLayout()
    row.addStretch(1)
    d.cancel_btn = QPushButton(icon("cancel"), "&Cancel")
    d.cancel_btn.setAutoDefault(False)
    d.cancel_btn.clicked.connect(d.reject)
    d.send_btn = QPushButton(icon("done"), "&Send")
    d.send_btn.setDefault(True)

    def send():
        d.choice = "send"
        d.accept()
    d.send_btn.clicked.connect(send)
    row.addWidget(d.cancel_btn)
    row.addWidget(d.send_btn)
    d.body.addLayout(row)
    return d
