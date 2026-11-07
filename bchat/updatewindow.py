"""The update entry after Help (light + words, hidden when there's nothing to do) and the update window.
Mockups OK'd 2026-11-07: mockup-update-states.png, mockup-updates.png."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFontMetrics, QPainter
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QMenuBar, QProgressBar, QPushButton, QWidget

from . import updater as up
from .widgets import FramedDialog, icon

def colours(t) -> dict:
    """Amber, blue, green, orange in the theme's own shades."""
    return {up.AVAILABLE: t.highlight, up.DOWNLOADING: t.new_highlight, up.READY: t.status_on, up.FAILED: t.status_lag,
            up.UPTODATE: t.status_on, up.CHECKING: t.new_highlight}
DOT_ROOM = 22      # pixels before the words: the light


class UpdateBadge(QWidget):
    """Paints the light and coloured words over a real menu bar action, so clicks and keyboard still work."""

    def __init__(self, bar: QMenuBar, action: QAction, updater: up.Updater, theme):
        super().__init__(bar)
        self.bar, self.action, self.up, self.theme = bar, action, updater, theme
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bar.installEventFilter(self)
        bar.hovered.connect(lambda _a: self.update())
        updater.changed.connect(self.sync)
        self.sync()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest, QEvent.Type.Leave,
                         QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._place()
        return False

    def sync(self) -> None:
        on = self.up.visible()
        text = self.up.label()
        # the action holds blank room the width of light + words, so the bar lays it out right after Help
        fm = QFontMetrics(self.bar.font())
        spaces = max(1, round((DOT_ROOM + fm.horizontalAdvance(text)) / max(1, fm.horizontalAdvance(" "))))
        self.action.setText(" " * spaces)
        self.action.setToolTip(self.up.tooltip())
        self.action.setVisible(on)
        self.setToolTip(self.up.tooltip())
        self.setVisible(on)
        self._place()

    def _place(self) -> None:
        if not self.action.isVisible():
            return
        g = self.bar.actionGeometry(self.action)
        if g.isValid():
            self.setGeometry(g)
            self.raise_()
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hot = self.bar.activeAction() is self.action
        p.fillRect(self.rect(), QColor(self.theme.popup if hot else self.theme.bar))
        c = QColor(colours(self.theme).get(self.up.state, self.theme.text))
        fm = QFontMetrics(self.bar.font())
        x0 = max(4, (self.width() - DOT_ROOM - fm.horizontalAdvance(self.up.label())) // 2)
        mid = self.height() / 2
        glow = QColor(c)
        glow.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(x0 + 7, mid), 5, 5)
        p.setBrush(c)
        p.drawEllipse(QPointF(x0 + 7, mid), 3.3, 3.3)
        p.setPen(c)
        p.setFont(self.bar.font())
        p.drawText(QRectF(x0 + DOT_ROOM - 4, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignVCenter, self.up.label())


class UpdateDialog(FramedDialog):
    """One window for every state: checking, up to date, available, downloading, ready, failed."""

    def __init__(self, win, updater: up.Updater):
        super().__init__("BChat Update", win)
        self.win, self.up = win, updater
        self.setFixedWidth(470)
        self.body.setContentsMargins(20, 16, 20, 14)
        self.body.setSpacing(8)
        self.head = QLabel()
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.news = QLabel()
        self.news.setWordWrap(True)
        self.news.setOpenExternalLinks(True)
        self.news.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.news.setStyleSheet(f"background: {win.cfg.theme.bar}; border: 1px solid {win.cfg.theme.border}; padding: 8px;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(f"QProgressBar {{ background: {win.cfg.theme.bar}; border: 1px solid {win.cfg.theme.border}; border-radius: 3px; }}"
                               f"QProgressBar::chunk {{ background: {win.cfg.theme.new_highlight}; border-radius: 2px; }}")
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {win.cfg.theme.muted};")
        self.auto = QCheckBox("Download updates by themselves")
        self.auto.setChecked(win.cfg.update_auto_download)
        self.auto.toggled.connect(self._auto_toggled)
        for w in (self.head, self.info, self.news, self.bar, self.note, self.auto):
            self.body.addWidget(w)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {win.cfg.theme.border};")
        self.body.addWidget(line)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.later = QPushButton("&Later")
        self.page = QPushButton("&Download")
        self.retry = QPushButton("&Try Again")
        self.stop = QPushButton("&Cancel Download")
        self.on_quit = QPushButton("Install When I &Quit")
        self.now = QPushButton("Install &Now")
        self.close_btn = QPushButton(icon("close-light"), "&Close")
        row.addWidget(self.later)
        row.addStretch(1)
        for b in (self.stop, self.page, self.retry, self.on_quit, self.now, self.close_btn):
            row.addWidget(b)
        self.body.addLayout(row)
        self.later.clicked.connect(self.reject)
        self.close_btn.clicked.connect(self.reject)
        self.page.clicked.connect(self._open_page)
        self.retry.clicked.connect(self._retry)
        self.stop.clicked.connect(self.up.cancel)
        self.on_quit.clicked.connect(self._install_on_quit)
        self.now.clicked.connect(self.up.install_now)
        self.up.changed.connect(self.sync)
        self.rejected.connect(self.up.dismiss)
        self.sync()

    def _auto_toggled(self, on: bool) -> None:
        self.win.cfg.update_auto_download = on
        self.win.save_config()

    def _open_page(self) -> None:
        url = self.up.download_page()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _retry(self) -> None:
        self.up.retry()

    def _install_on_quit(self) -> None:
        self.up.download()
        self.accept()

    def sync(self) -> None:
        u, s = self.up, self.up.state
        e = u.entry or {}
        v = e.get("version", "")
        colour = colours(self.win.cfg.theme).get(s, self.win.cfg.theme.text)
        heads = {up.CHECKING: "Checking for updates...", up.UPTODATE: "BChat is up to date",
                 up.AVAILABLE: f"BChat {v} is available", up.DOWNLOADING: f"Downloading BChat {v}",
                 up.READY: f"BChat {v} is ready", up.FAILED: "Update failed", up.NONE: "BChat is up to date"}
        self.head.setText(heads.get(s, ""))
        self.head.setStyleSheet(f"color: {colour}; font-size: 14pt; font-weight: bold;")
        size = f", {round(int(e['size']) / 1_000_000)} MB" if e.get("size") else ""
        date = f" Released {e['date']}{size}." if e.get("date") else (f" {size[2:]}." if size else "")
        info = {up.CHECKING: f"You have {u.current}.",
                up.UPTODATE: f"You have {u.current}, the newest version.",
                up.NONE: f"You have {u.current}, the newest version.",
                up.AVAILABLE: f"You have {u.current}.{date}",
                up.DOWNLOADING: _got(e, u.progress),
                up.READY: f"Downloaded and checked. It installs when you quit BChat.",
                up.FAILED: u.reason}
        self.info.setText(info.get(s, ""))
        notes = e.get("notes") or []
        link = e.get("notes_url")
        if notes or link:
            items = "".join(f"<br>• {_esc(n)}" for n in notes)
            more = f'<br><a style="color: {self.win.cfg.theme.check};" href="{_esc(link)}">Full release notes</a>' if link else ""
            self.news.setText(f"<b>What's new</b>{items}{more}")
        self.news.setVisible(bool(notes or link) and s in (up.AVAILABLE, up.DOWNLOADING, up.READY))
        self.bar.setValue(u.progress)
        self.bar.setVisible(s == up.DOWNLOADING)
        self.note.setText("Install Now closes BChat, updates it and opens it again. "
                          "Networks set to connect on start reconnect by themselves.")
        self.note.setVisible(s in (up.AVAILABLE, up.DOWNLOADING, up.READY))
        self.auto.setVisible(s in (up.AVAILABLE, up.UPTODATE, up.NONE))
        self.later.setVisible(s in (up.AVAILABLE, up.DOWNLOADING, up.READY))
        self.later.setText("&Hide" if s == up.DOWNLOADING else "&Later")
        self.stop.setVisible(s == up.DOWNLOADING)
        self.page.setVisible(s == up.FAILED and bool(u.download_page()))
        self.retry.setVisible(s == up.FAILED)
        self.on_quit.setVisible(s == up.AVAILABLE)
        self.now.setVisible(s in (up.AVAILABLE, up.READY) or (s == up.DOWNLOADING and not u.install_after))
        self.close_btn.setVisible(s in (up.CHECKING, up.UPTODATE, up.NONE, up.FAILED))
        default = {up.AVAILABLE: self.on_quit, up.READY: self.now, up.FAILED: self.retry}.get(s, self.close_btn if self.close_btn.isVisible() else self.later)
        for b in (self.later, self.page, self.retry, self.stop, self.on_quit, self.now, self.close_btn):
            b.setAutoDefault(False)
            b.setDefault(b is default)
        self.adjustSize()


def _got(e: dict, pct: int) -> str:
    size = int(e.get("size") or 0)
    if size:
        return f"{round(size * pct / 100 / 1_000_000)} of {round(size / 1_000_000)} MB · {pct}%"
    return f"{pct}%"


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
