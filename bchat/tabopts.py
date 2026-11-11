"""Per-tab settings (0.6.0): a few Preferences that one channel or private chat can change for itself.

Stored in cfg.tab_opts["network/#channel"] = {name: value}; a name that isn't there follows Preferences."""
from __future__ import annotations

from .protocol import lower

# name -> (label, the Preferences value it overrides)
NAMES = ("timestamps", "color_nicks", "joins", "beep", "flash", "popups")
JOINS = ("show", "short", "hide")
HIDEABLE = ("Join", "Part", "Part with Reason", "Quit")


def key(b) -> str:
    return f"{lower(b.session.net.name)}/{lower(b.name)}"


def default(cfg, name: str, b=None):
    """What Preferences says for this tab (alert ticks: the column for its kind of tab)."""
    which = 1 if b is not None and b.kind == "query" else 0
    return {"timestamps": cfg.timestamps, "color_nicks": cfg.color_nicks,
            "joins": "short" if cfg.short_joins else "show",
            "beep": bool(cfg.alert_beep[which]), "flash": bool(cfg.alert_flash[which]),
            "popups": bool(cfg.alert_popup[which])}[name]


def get(cfg, b, name: str):
    if b is None or getattr(b, "session", None) is None:
        return default(cfg, name, b)
    own = cfg.tab_opts.get(key(b), {})
    return own[name] if name in own else default(cfg, name, b)


def has_own(cfg, b, name: str) -> bool:
    return name in cfg.tab_opts.get(key(b), {})


def set_(cfg, b, name: str, value) -> None:
    """Keeps only what differs from Preferences, so a tab put back by hand follows Preferences again."""
    k = key(b)
    own = dict(cfg.tab_opts.get(k, {}))
    if value == default(cfg, name, b):
        own.pop(name, None)
    else:
        own[name] = value
    if own:
        cfg.tab_opts[k] = own
    else:
        cfg.tab_opts.pop(k, None)


def clear(cfg, b) -> None:
    cfg.tab_opts.pop(key(b), None)
