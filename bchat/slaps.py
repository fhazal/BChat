"""Slap! in the nick menu: one random line from the user's slap list, sent as an action (/me).
Lines are kept with $nick for the person and %B %C %U %O %R for formatting, so they stay readable in the editor."""
from __future__ import annotations

import random
import re

# the owner's own collection (11-09); the rainbow trout got its colour codes back (they were lost in a copy-paste)
DEFAULT_SLAPS = [
    "slaps $nick with a large, smelly, %C4r%C7a%C8i%C9n%C11b%C6o%C13w%C trout.",
    "pelts $nick with a wet burrito.",
    "bats $nick over the head with a stale baguette.",
    "throws a slice of plastic cheese directly onto $nick's face.",
    "drops a 10-ton anvil on $nick's head, cartoon-style.",
    "puts on a white glove, challenges $nick to a duel, and slaps them.",
    "kicks $nick in the left shin.",
    "hits $nick over the head with a massive foam finger.",
    "rolls up a newspaper and taps $nick on the nose. \"No! Bad chatter!\"",
    "slaps $nick with a broken Commodore 64 manual.",
    "pelt-strikes $nick with an obsolete IDE cable.",
    "hits $nick with a stack of unread documentation.",
    "drops an active server rack onto $nick's foot.",
    "sneaks up behind $nick and puts gum in their hair.",
    "runs past and pantses $nick.",
    "pushes $nick into a giant pit of very confused snakes.",
    "shakes $nick's boat vigorously.",
]

CODES = {"B": "\x02", "C": "\x03", "U": "\x1f", "O": "\x0f", "R": "\x16", "%": "%"}


def lines_of(rows) -> list[str]:
    """Editor rows ([text] each) -> the usable lines."""
    return [r[0].strip() for r in rows if r and r[0].strip()]


def render(line: str, nick: str) -> str:
    line = line.strip()
    if line.lower().startswith("/me "):          # pasted with /me in front: the menu sends it as /me anyway
        line = line[4:].lstrip()
    line = re.sub(r"%([BCUOR%])", lambda m: CODES[m.group(1)], line)
    return line.replace("$nick", nick)


def pick(lines: list[str], nick: str, rng=random) -> str:
    return render(rng.choice(lines), nick) if lines else ""
