"""0.8.8: reading messages aloud with the voices Windows already has (Qt Text to Speech: SAPI or WinRT engines).

Everything stays on this PC. Lines wait their turn (a new one never cuts off the one being read), each is cut to
about 200 characters, colour and bold codes are left out and a web address is read as "link"."""
from __future__ import annotations

import re

from .protocol import URL_RE, strip_format

ENGINE = ""                     # "" = Windows' best engine; tests set "mock" (Qt's silent test engine)
MAX_CHARS = 200
TEST_TEXT = "This is how BChat reads your messages."
UNAVAILABLE = "Speech isn't available on this PC."


def clean(text: str) -> str:
    """Plain words to read: no IRC codes, links said as "link", one space between words."""
    text = URL_RE.sub("link", strip_format(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def cap(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(" ,.;:")


def event_text(kind: str, nick: str, where: str, text: str) -> str:
    """kind: hilight | priv | notice. "ana in #chat: the server is back", "ana privately: hi", "notice from ana: text"."""
    nick, text = clean(nick), clean(text)
    if kind == "notice":
        line = f"notice from {nick}: {text}"
    elif kind == "priv":
        line = f"{nick} privately: {text}"
    else:
        line = f"{nick} in {clean(where)}: {text}"
    return cap(line)


class Speaker:
    """One per app (see speaker()). The engine is made the first time something needs it."""

    def __init__(self) -> None:
        self._tts = None
        self._tried = False
        self._default_voice = None
        self._voice = ""

    @staticmethod
    def engines() -> list[str]:
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
        except ImportError:
            return []
        names = list(QTextToSpeech.availableEngines())
        return [ENGINE] if ENGINE and ENGINE in names else [n for n in names if n != "mock"]

    def engine(self):
        if not self._tried:
            self._tried = True
            if self.engines():
                from PySide6.QtTextToSpeech import QTextToSpeech
                tts = QTextToSpeech(ENGINE) if ENGINE else QTextToSpeech()
                if tts.state() != QTextToSpeech.State.Error:
                    self._tts = tts
                    self._default_voice = tts.voice()
        return self._tts

    def available(self) -> bool:
        return self.engine() is not None

    def voices(self) -> list[str]:
        tts = self.engine()
        return [v.name() for v in tts.availableVoices()] if tts is not None else []

    def say(self, text: str, voice: str = "", rate: int = 0) -> bool:
        """Adds a line to the queue. rate: -10 (slow) .. 10 (fast), 0 = normal."""
        tts = self.engine()
        text = cap(clean(text))
        if tts is None or not text:
            return False
        if voice != self._voice:
            pick = next((v for v in tts.availableVoices() if v.name() == voice), None) if voice else None
            pick = pick or self._default_voice
            if pick is not None:
                tts.setVoice(pick)
            self._voice = voice
        tts.setRate(max(-10, min(10, int(rate))) / 10)
        if hasattr(tts, "enqueue"):
            tts.enqueue(text)
        else:                                   # Qt before 6.6 has no queue
            tts.say(text)
        return True

    def stop(self) -> None:
        if self._tts is not None:
            self._tts.stop()

    def speaking(self) -> bool:
        if self._tts is None:
            return False
        from PySide6.QtTextToSpeech import QTextToSpeech
        return self._tts.state() == QTextToSpeech.State.Speaking


_SPEAKER: Speaker | None = None


def speaker() -> Speaker:
    global _SPEAKER
    if _SPEAKER is None:
        _SPEAKER = Speaker()
    return _SPEAKER
