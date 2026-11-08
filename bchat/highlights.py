"""Highlight rules, the way mIRC's Highlight list works: words (commas, wildcards) matched on the message, the nick
or both, only from the channels/nicks/networks given (empty = everywhere), each with its own colour, sound, flash
and tip. From XChat: your own nick always highlights, and "Never Highlight" nicks never do."""
from __future__ import annotations

import fnmatch

from .protocol import lower

ON = ("message", "nick", "both")
ON_TEXT = {"message": "Message", "nick": "Nick", "both": "Both"}
# sound "" = the Alerts page's highlight sound, "none" = silent, else a file
NEW_RULE = {"match": "", "on": "message", "where": "", "colour": "", "sound": "", "flash": True, "tip": True}
OWN = {"own": True, "match": "", "on": "message", "where": "", "colour": "", "sound": "", "flash": None, "tip": None}


def rule(**kw) -> dict:
    return {**NEW_RULE, **kw}


def words(text: str) -> list[str]:
    return [w.strip() for w in (text or "").split(",") if w.strip()]


def matches_nick(nick: str, patterns: str) -> bool:
    low = lower(nick)
    return any(fnmatch.fnmatchcase(low, lower(p)) for p in words(patterns))


def word_hit(text: str, word: str) -> bool:
    """mIRC/XChat: a whole word, or wildcards against each word (restart* matches restarting)."""
    low, lw = lower(text), lower(word)
    if not lw:
        return False
    if "*" in lw or "?" in lw:
        return any(fnmatch.fnmatchcase(tok, lw) for tok in low.split())
    at = low.find(lw)
    while at != -1:
        before = low[at - 1] if at else " "
        end = at + len(lw)
        after = low[end] if end < len(low) else " "
        if not (before.isalnum() or before in "_-{}|^") and not (after.isalnum() or after in "_-{}|^"):
            return True
        at = low.find(lw, at + 1)
    return False


def where_ok(r: dict, network: str, target: str, sender: str) -> bool:
    """mIRC's "From these channels/nicks", plus network names: empty means everywhere."""
    places = words(r.get("where", ""))
    if not places:
        return True
    return any(fnmatch.fnmatchcase(lower(x), lower(p)) for p in places for x in (target, sender, network) if x)


def find(cfg, own_nick: str, text: str, sender: str = "", network: str = "", target: str = "") -> dict | None:
    """The rule a line matches, or None. Never Highlight first, then the rules in order, then your own nick."""
    if sender and matches_nick(sender, cfg.hilite_no):
        return None
    if cfg.hl_on:
        for r in cfg.hl_rules:
            ws = words(r.get("match", ""))
            if not ws or not where_ok(r, network, target, sender):
                continue
            on = r.get("on", "message")
            if on in ("message", "both") and any(word_hit(text, w) for w in ws):
                return r
            if on in ("nick", "both") and sender and any(fnmatch.fnmatchcase(lower(sender), lower(w)) for w in ws):
                return r
    if own_nick and word_hit(text, own_nick):
        return OWN
    return None


def migrate(cfg) -> None:
    """XChat's three lists (also what an XChat import fills) become rules once: extra words on the message,
    always-highlight nicks on the nick. Never Highlight stays a list."""
    have = {lower(r.get("match", "")) for r in cfg.hl_rules}
    for w in words(cfg.highlight):
        if lower(w) not in have:
            cfg.hl_rules.append(rule(match=w, on="message"))
            have.add(lower(w))
    for n in words(cfg.hilite_always):
        if lower(n) not in have:
            cfg.hl_rules.append(rule(match=n, on="nick"))
            have.add(lower(n))
    cfg.highlight = cfg.hilite_always = ""
