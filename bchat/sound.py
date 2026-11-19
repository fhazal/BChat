"""0.8.8: event sounds in .wav, .mp3 or .ogg at one volume (Settings > Sound).

A .wav at full volume plays the way it always did (Windows' own player), so nothing changes for anyone who never
touches the Volume slider. Everything else goes through Qt Multimedia (its FFmpeg backend decodes mp3 and ogg).
Several sounds can play at once; a missing or broken file is reported once, never as a dialog."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

EXTENSIONS = (".wav", ".mp3", ".ogg")
FILTER = "Sound files (*.wav *.mp3 *.ogg)"
MAX_AT_ONCE = 4                 # a burst of sounds: the oldest one stops, they never pile up
MUTED = False                   # tests set this: the real players run, but nothing comes out of the speakers


class Player:
    """One per app (see player()). report(text) tells the user about a file that can't play, once per file."""

    def __init__(self) -> None:
        self.report: Callable[[str], None] | None = None
        self._playing: list = []          # (QMediaPlayer, QAudioOutput), oldest first
        self._failed: set[str] = set()

    def play(self, path: str, volume: int = 100) -> bool:
        """True when it started. A file that can't play is reported (once) and gives False."""
        path = str(path or "").strip()
        if not path:
            return False
        p = Path(path)
        if not p.is_file():
            self._fail(path, "isn't there any more")
            return False
        if p.suffix.lower() not in EXTENSIONS:
            self._fail(path, "isn't a .wav, .mp3 or .ogg file")
            return False
        volume = max(0, min(100, int(volume)))
        if volume == 0:
            return True                   # turned all the way down: nothing to play, but no chime either
        if p.suffix.lower() == ".wav" and volume >= 100 and self._winsound(str(p)):
            return True
        return self._media(p, volume)

    def stop(self) -> None:
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except (ImportError, RuntimeError):
            pass
        for pl, _out in list(self._playing):
            pl.stop()
            self._done(pl)

    def playing(self) -> int:
        return len(self._playing)

    # --- the two ways to play -----------------------------------------------------------------------

    def _winsound(self, path: str) -> bool:
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except ImportError:
            return False
        except RuntimeError:
            self._fail(path, "couldn't be played")
            return False
        return True

    def _media(self, p: Path, volume: int) -> bool:
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            self._fail(str(p), "can't play: sound support is missing")
            return False
        while len(self._playing) >= MAX_AT_ONCE:
            old = self._playing[0][0]
            old.stop()
            self._done(old)
        out = QAudioOutput()
        out.setVolume(volume / 100)
        out.setMuted(MUTED)
        pl = QMediaPlayer()
        pl.setAudioOutput(out)
        path = str(p)
        pl.errorOccurred.connect(lambda _e, _t, pl=pl, path=path: self._error(pl, path))
        pl.mediaStatusChanged.connect(lambda st, pl=pl, path=path: self._status(pl, path, st))
        self._playing.append((pl, out))
        pl.setSource(QUrl.fromLocalFile(path))
        pl.play()
        return True

    def _status(self, pl, path: str, st) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        if st == QMediaPlayer.MediaStatus.EndOfMedia:
            self._done(pl)
        elif st == QMediaPlayer.MediaStatus.InvalidMedia:
            self._error(pl, path)

    def _error(self, pl, path: str) -> None:
        if any(x is pl for x, _ in self._playing):
            self._fail(path, "couldn't be played (not a sound file BChat can read)")
            self._done(pl)

    def _done(self, pl) -> None:
        for i, (x, out) in enumerate(self._playing):
            if x is pl:
                del self._playing[i]
                x.deleteLater()
                out.deleteLater()
                return

    def _fail(self, path: str, why: str) -> None:
        key = path.lower()
        if key in self._failed:
            return
        self._failed.add(key)
        text = f"Sound {Path(path).name} {why}: {path}"
        if self.report is not None:
            try:
                self.report(text)
                return
            except RuntimeError:          # the window it reports to is gone
                pass
        import logging
        logging.getLogger("bchat").warning(text)


_PLAYER: Player | None = None


def player() -> Player:
    global _PLAYER
    if _PLAYER is None:
        _PLAYER = Player()
    return _PLAYER


def play(path: str, volume: int = 100) -> bool:
    return player().play(path, volume)
