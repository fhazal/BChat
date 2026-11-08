"""Preferences > BChat > Updates: a status card (a progress ring around an icon, the state's one colour) over the
update options, plus the short status the About window shows. Mockup OK'd 2026-11-08: mockup-updates-page.png,
mockup-updates-about.png. Everything reads the one Updater, so the card, About and the menu bar entry agree."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import lucide
from . import updater as up

RELEASES = "https://github.com/fhazal/BChat/releases"


def _pix(name: str, colour: str, size: int, dpr: float) -> QPixmap:
    pm = QPixmap.fromImage(lucide.image(name, colour, round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    return pm


def state_colour(t, state: str) -> str:
    return {up.AVAILABLE: t.new_data, up.DOWNLOADING: t.check, up.CHECKING: t.check, up.READY: t.join,
            up.FAILED: t.marker}.get(state, t.join)


def checked_text(u: up.Updater) -> str:
    when = float(getattr(u.cfg, "update_last_check", 0) or 0)
    src = " · from GitHub" if "github" in (u.url or "") else ""
    if not when:
        return "Not checked yet" + src
    lt = time.localtime(when)
    day = "today" if time.strftime("%Y%m%d", lt) == time.strftime("%Y%m%d") else time.strftime("%d %b", lt).lstrip("0")
    return f"Checked {day} at {time.strftime('%H:%M', lt)}{src}"


def _mb(n) -> str:
    return f"{int(n) / 1_000_000:.1f} MB"


def card_text(u: up.Updater) -> dict:
    """What the card says in each state: ring, title, status, small line, button (icon, label, action name)."""
    s, e = u.state, u.entry or {}
    v = e.get("version", "")
    size = int(e.get("size") or 0)
    if s == up.AVAILABLE:
        bits = [f"You have {u.current}"] + ([_mb(size)] if size else []) + ([e["date"]] if e.get("date") else [])
        return dict(ring=1.0, icon="new-version", pct="", title=f"BChat {v} is here",
                    status="A new version is ready to download", sub=" · ".join(bits),
                    button=("download", "&Download", "download"), filled=True)
    if s == up.DOWNLOADING:
        got = f"{size * u.progress / 100 / 1_000_000:.1f} of {size / 1_000_000:.1f} MB" if size else f"{u.progress}%"
        return dict(ring=u.progress / 100, icon="", pct=f"{u.progress}%", title=f"Downloading BChat {v}",
                    status=got, sub="Signed by BajuBesi Labs · checked before it installs",
                    button=("close-light", "&Cancel", "cancel"), filled=False)
    if s == up.READY:
        return dict(ring=1.0, icon="ready", pct="", title=f"BChat {v} is ready", status="Installs when you quit BChat",
                    sub="Or install now: BChat restarts in a few seconds", button=("install", "&Install Now", "install"), filled=True)
    if s == up.FAILED:
        title = "Couldn't check for updates" if not v else f"BChat {v} didn't update"
        why = (u.reason or "Something went wrong").removeprefix("Couldn't check for updates: ")
        return dict(ring=1.0, icon="problem", pct="", title=title, status=why[:1].upper() + why[1:], sub="BChat tries again by itself in an hour",
                    button=("refresh", "&Try Again", "retry"), filled=False)
    if s == up.CHECKING:
        return dict(ring=0.25, icon="refresh", pct="", title=f"BChat {u.current}", status="Checking for updates...",
                    sub=checked_text(u), button=("refresh", "Check &Now", ""), filled=False)
    return dict(ring=1.0, icon="done", pct="", title=f"BChat {u.current}", status="You're up to date",
                sub=checked_text(u), button=("refresh", "Check &Now", "check"), filled=False)


class Ring(QWidget):
    """A progress ring around an icon or a percentage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.colour, self.track, self.frac, self.icon_name, self.pct = "#a6e3a1", "#313244", 1.0, "done", ""

    def set(self, colour: str, track: str, frac: float, icon_name: str, pct: str) -> None:
        self.colour, self.track, self.frac, self.icon_name, self.pct = colour, track, max(0.0, min(1.0, frac)), icon_name, pct
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(4, 4, 48, 48)
        p.setPen(QPen(QColor(self.track), 4))
        p.drawEllipse(r)
        pen = QPen(QColor(self.colour), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 90 * 16, -int(360 * 16 * self.frac))
        if self.icon_name:
            p.drawPixmap(16, 16, _pix(self.icon_name, self.colour, 24, self.devicePixelRatioF()))
        if self.pct:
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSize(9)
            p.setFont(f)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.pct)
        p.end()


class UpdateCard(QFrame):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win, self.up, self.t = win, win.updater, win.cfg.theme
        t = self.t
        self.setObjectName("updcard")
        self.setStyleSheet(f"#updcard {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 10px; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.ring = Ring(self)
        top.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel()
        self.title.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {t.text};")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.sub = QLabel()
        self.sub.setStyleSheet(f"color: {t.muted}; font-size: 8pt;")
        col.addStretch(1)
        for w in (self.title, self.status, self.sub):
            col.addWidget(w)
        col.addStretch(1)
        top.addLayout(col, 1)
        self.button = QPushButton()
        self.button.setAutoDefault(False)
        self.button.clicked.connect(self._clicked)
        top.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(top)
        self.news = QWidget(self)
        nl = QVBoxLayout(self.news)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(6)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {t.border};")
        nl.addWidget(line)
        head = QLabel("What's new")
        head.setStyleSheet(f"font-weight: bold; color: {t.text};")
        nl.addWidget(head)
        self.notes = QVBoxLayout()
        self.notes.setSpacing(4)
        nl.addLayout(self.notes)
        self.notes_link = QLabel()
        self.notes_link.setOpenExternalLinks(True)
        nl.addWidget(self.notes_link)
        outer.addWidget(self.news)
        self.action = ""
        self.up.changed.connect(self.sync)
        self.sync()

    def _clicked(self) -> None:
        a = self.action
        if a == "check":
            self.up.check(manual=True)
        elif a == "download":
            self.up.download()
        elif a == "cancel":
            self.up.cancel()
        elif a == "install":
            self.up.install_now()
        elif a == "retry":
            self.up.retry()

    def sync(self) -> None:
        t, u = self.t, self.up
        c = card_text(u)
        colour = state_colour(t, u.state)
        self.ring.set(colour, t.border, c["ring"], c["icon"], c["pct"])
        self.title.setText(c["title"])
        self.status.setText(c["status"])
        self.status.setStyleSheet(f"color: {colour};")
        self.sub.setText(c["sub"])
        ico, label, action = c["button"]
        self.action = action
        self.button.setText(label)
        self.button.setEnabled(bool(action))
        ink = t.panel if c["filled"] else t.text
        self.button.setIcon(QIcon(_pix(ico, ink, 16, self.devicePixelRatioF())))
        self.button.setStyleSheet(
            f"QPushButton {{ background: {colour}; color: {t.panel}; border: none; border-radius: 4px; padding: 5px 12px; font-weight: bold; }}"
            if c["filled"] else "")
        # what's new: only while there's a new version to talk about
        while self.notes.count():
            item = self.notes.takeAt(0)
            if item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        e = u.entry or {}
        notes = [str(n) for n in (e.get("notes") or [])][:6]
        for n in notes:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("•")
            dot.setStyleSheet(f"color: {colour};")
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            lab = QLabel(n)
            lab.setTextFormat(Qt.TextFormat.PlainText)          # release text is data, never markup
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color: {t.muted};")
            row.addWidget(lab, 1)
            self.notes.addLayout(row)
        link = e.get("notes_url") or e.get("page") or ""
        if link.startswith("https://"):
            self.notes_link.setText(f'<a style="color: {t.check};" href="{_esc(link)}">Full release notes on GitHub</a>')
        self.notes_link.setVisible(link.startswith("https://"))
        self.news.setVisible(u.state == up.AVAILABLE and bool(notes or link))


def updates_page(prefs, lay) -> None:
    """Fills the Updates page: the card, then the three options (kept as prefs.upd_* for Save)."""
    win, c, t = prefs.win, prefs.cfg, prefs.cfg.theme
    prefs.upd_card = UpdateCard(win, prefs)
    lay.addWidget(prefs.upd_card)
    lay.addSpacing(10)

    def option(text: str, on: bool, desc: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(on)
        lay.addWidget(box)
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {t.muted}; font-size: 8pt; margin-left: 26px;")
        lay.addWidget(d)
        return box
    prefs.upd_check = option("Check for updates when BChat starts and once a day", c.update_check,
                             "BChat asks GitHub for its newest release. Nothing about you is sent.")
    prefs.upd_auto = option("Download updates by themselves", c.update_auto_download,
                            "A downloaded update waits and installs when you quit BChat. Your settings, networks and logs stay.")
    prefs.upd_test = option("Include test versions", c.update_test_versions,
                            "Try fixes before everyone else. TEST builds always follow test versions.")
    lay.addSpacing(8)
    trust = QLabel(f'<span style="color:{t.muted};">Every update is signed by BajuBesi Labs and checked before it runs.</span>'
                   f'&nbsp;&nbsp;<a style="color: {t.check};" href="{RELEASES}">All release notes</a>')
    trust.setOpenExternalLinks(True)
    trust.setWordWrap(True)
    lay.addWidget(trust)
    lay.addStretch(1)


def about_parts(u: up.Updater, t) -> tuple[str, str, str] | None:
    """The few words after the version in About: (icon name, colour, rich text), or None when there is nothing to say.
    The icon is shown by its own label (see AboutDialog), so it is drawn sharp at the screen's scale and centred
    with the words; a rich-text <img> was shrunk without smoothing and sat on the text's baseline."""
    s = u.state
    v = (u.entry or {}).get("version", "")
    colour = state_colour(t, s)
    if s == up.AVAILABLE:
        words, ico, link = f"{_esc(v)} is here", "new-version", "Update"
    elif s == up.DOWNLOADING:
        words, ico, link = f"Downloading {_esc(v)} · {u.progress}%", "download", ""
    elif s == up.READY:
        words, ico, link = f"{_esc(v)} is ready", "ready", "Install"
    elif s == up.FAILED:
        words, ico, link = "Couldn't check", "problem", "Details"
    elif s == up.CHECKING:
        words, ico, link = "Checking...", "refresh", ""
    elif getattr(u.cfg, "update_last_check", 0):
        words, ico, link = "Up to date", "done", ""
    else:
        return None
    more = f' · <a style="color:{t.check};" href="bchat:update">{link}</a>' if link else ""
    return ico, colour, f'<span style="color:{colour};">{words}</span>{more}'


def about_status(u: up.Updater, t) -> str:
    """Just the words of about_parts (rich text), "" when there is nothing to say."""
    parts = about_parts(u, t)
    return parts[2] if parts else ""


def icon_pixmap(name: str, colour: str, size: int, dpr: float) -> QPixmap:
    """A Lucide icon drawn at the screen's real pixel size, so it stays sharp at 125 and 150 %."""
    pm = QPixmap.fromImage(lucide.image(name, colour, max(1, round(size * dpr))))
    pm.setDevicePixelRatio(dpr)
    return pm


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
