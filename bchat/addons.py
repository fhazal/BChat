"""Settings > Add-ons (0.9.3): one place to turn the built-in add-ons on or off. Mockup: mockups/mockup-addons.png.

While an add-on is off its menus stay hidden and nothing of it runs. Today: Channel Protection (off on a new
install) and Oper tools (on, but it only shows while the server says you're an IRC operator).
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QPushButton, QVBoxLayout

from .protection import _muted
from .widgets import FramedDialog, icon


def oper_networks(win) -> list[str]:
    """The networks where the server says you're an IRC operator.
    HOOK for Oper tools: it sets `Session.is_oper` (RPL_YOUREOPER / user mode +o); until then this is always empty."""
    return [s.net.name for s in win.sessions.values() if getattr(s, "is_oper", False)]


def oper_status(win) -> str:
    """The italic "Now: ..." line of the Oper tools row."""
    nets = oper_networks(win)
    if not nets:
        return "not an operator on any network, so nothing shows."
    return f"you're an operator on {', '.join(nets)}, so the Oper menu is on."


class AddonsDialog(FramedDialog):
    """Two rows: a bold tick, one muted line, and "Settings..." (hidden but keeping its room while the add-on is off)."""

    def __init__(self, win):
        super().__init__("BChat: Add-ons", win)
        self.win = win
        t = win.cfg.theme
        self.setFixedWidth(560)
        self.body.setContentsMargins(20, 16, 20, 14)
        self.body.setSpacing(10)
        self.body.addWidget(_muted(t, "Extra tools that come with BChat. While one is off, its menus stay hidden.", False))
        self.protection, self.protection_btn = self._row(
            "Channel Protection", win.cfg.addon_protection,
            "Kicks or bans flooders, repeaters, caps and colour spam in channels where you have @.")
        self.oper, self.oper_btn = self._row(
            "Oper tools", win.cfg.addon_oper,
            "An Oper menu and server notices tab, shown only while the server says you're an IRC operator.",
            f"<i>Now: {oper_status(win)}</i>")
        self.protection.toggled.connect(lambda on: self._set("addon_protection", on, self.protection_btn))
        self.oper.toggled.connect(lambda on: self._set("addon_oper", on, self.oper_btn))
        self.protection_btn.clicked.connect(lambda: win.open_protection())
        self.oper_btn.clicked.connect(lambda: win.open_oper_tools())
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(icon("close"), "&Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.body.addLayout(row)
        self.setFixedHeight(self.sizeHint().height())

    def _row(self, title: str, on: bool, text: str, status: str | None = None):
        t = self.win.cfg.theme
        box = QFrame(objectName="addon")
        box.setStyleSheet(f"#addon {{ border: 1px solid {t.border}; }}")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(3)
        top = QHBoxLayout()
        cb = QCheckBox(title)
        cb.setChecked(on)
        f = cb.font()
        f.setBold(True)
        cb.setFont(f)
        top.addWidget(cb)
        top.addStretch(1)
        btn = QPushButton("Settings...")
        btn.setAutoDefault(False)
        sp = btn.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        btn.setSizePolicy(sp)
        btn.setVisible(on)
        top.addWidget(btn)
        v.addLayout(top)
        for line in (text, status):
            if line:
                lb = _muted(t, line, False)
                lb.setContentsMargins(22, 0, 0, 0)
                v.addWidget(lb)
        self.body.addWidget(box)
        return cb, btn

    def _set(self, key: str, on: bool, btn: QPushButton) -> None:
        setattr(self.win.cfg, key, on)
        btn.setVisible(on)
        self.win.save_config()
        self.win.addons_changed()
