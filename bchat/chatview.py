"""The chat area: stamp, right-aligned nick column, separator line, text that wraps past the separator."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPen, QTextBlockFormat,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextImageFormat, QTextOption)
from PySide6.QtWidgets import QTextBrowser

from .config import Config
from .protocol import parse_format, split_urls
from .session import (ACTION, ERROR, HILITE, INFO, JOIN, MSG, NOTICE, NOW_TALKING, PART, SELF, TOPIC, WHOIS, Buffer,
                      Line)
from .widgets import ASSETS


class ChatView(QTextBrowser):
    NICK_CHARS = 13
    MAX_BLOCKS = 5000

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.docs: dict[int, QTextDocument] = {}
        self.current: Buffer | None = None
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._open_url)
        self.setFrameShape(self.Shape.StyledPanel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setUndoRedoEnabled(False)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.apply_font()
        self._empty = self._new_doc()
        self.setDocument(self._empty)

    def apply_font(self) -> None:
        self.chat_font = QFont(self.cfg.chat_font, self.cfg.chat_font_size)
        self.chat_font.setStyleHint(QFont.StyleHint.Monospace)
        fm = QFontMetrics(self.chat_font)
        self.char_w = fm.horizontalAdvance("0")
        self.stamp_w = (self.char_w * 8) if self.cfg.timestamps else 0
        self.nick_w = self.char_w * self.NICK_CHARS
        self.sep_x = self.stamp_w + self.nick_w + self.char_w // 2
        self.text_x = self.sep_x + self.char_w // 2 + 2
        self.fm = fm

    def _new_doc(self) -> QTextDocument:
        d = QTextDocument(self)
        d.setDefaultFont(self.chat_font)
        d.setUndoRedoEnabled(False)
        d.setDocumentMargin(3)
        d.setMaximumBlockCount(self.MAX_BLOCKS)
        return d

    def doc_for(self, b: Buffer) -> QTextDocument:
        d = self.docs.get(id(b))
        if d is None:
            d = self._new_doc()
            self.docs[id(b)] = d
            for ln in b.lines:
                self._render(d, ln)
        return d

    def forget(self, b: Buffer) -> None:
        d = self.docs.pop(id(b), None)
        if self.current is b:
            self.current = None
            self.setDocument(self._empty)
        if d is not None:
            d.deleteLater()

    def show_buffer(self, b: Buffer | None) -> None:
        if self.current is not None and self.current is not b:
            old = self.docs.get(id(self.current))
            if old is not None:
                self.current.marker = old.blockCount() - 1
        self.current = b
        d = self.doc_for(b) if b is not None else self._empty
        self.setDocument(d)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        self.viewport().update()

    def reload(self, b: Buffer) -> None:
        """Rebuild after /clear or a font change."""
        d = self.docs.pop(id(b), None)
        if self.current is b:
            self.current = None
            self.show_buffer(b)
        if d is not None:
            d.deleteLater()

    def reset_marker(self) -> None:
        if self.current is not None:
            self.current.marker = None
            self.viewport().update()

    def add_line(self, b: Buffer, ln: Line) -> None:
        d = self.docs.get(id(b))
        if d is None:
            return
        sb = self.verticalScrollBar()
        at_end = b is not self.current or sb.value() >= sb.maximum() - 4
        self._render(d, ln)
        if at_end and b is self.current:
            sb.setValue(sb.maximum())

    # --- drawing a line ------------------------------------------------------

    def _kind_colours(self, kind: str) -> tuple[str, str]:
        t = self.cfg.theme
        return {
            MSG: (t.nick, t.chat_fg),
            SELF: (t.nick, t.chat_fg),
            ACTION: (t.topic, t.topic),
            JOIN: (t.join, t.join),
            PART: (t.marker, t.join),
            TOPIC: (t.topic, t.topic),
            INFO: (t.topic, t.chat_fg),
            WHOIS: (t.nick, t.chat_fg),
            NOW_TALKING: (t.join, t.join),
            HILITE: (t.highlight, t.highlight),
            NOTICE: (t.highlight, t.chat_fg),
            ERROR: (t.marker, t.chat_fg),
        }.get(kind, (t.nick, t.chat_fg))

    def _render(self, d: QTextDocument, ln: Line) -> None:
        cur = QTextCursor(d)
        cur.movePosition(QTextCursor.MoveOperation.End)
        bf = QTextBlockFormat()
        bf.setLeftMargin(self.text_x)
        bf.setTextIndent(-self.text_x)
        bf.setTabPositions([
            QTextOption.Tab(self.stamp_w + self.nick_w, QTextOption.TabType.RightTab),
            QTextOption.Tab(self.text_x, QTextOption.TabType.LeftTab),
        ])
        if d.isEmpty():
            cur.setBlockFormat(bf)
        else:
            cur.insertBlock(bf)
        left_col, text_col = self._kind_colours(ln.kind)
        t = self.cfg.theme
        cf = QTextCharFormat()
        if self.cfg.timestamps:
            cf.setForeground(QColor(t.stamp))
            cur.insertText(time.strftime("[%H:%M]", time.localtime(ln.ts)), cf)
        cf = QTextCharFormat()
        cf.setForeground(QColor(left_col))
        cur.insertText("\t", cf)
        pic = {WHOIS: "info", JOIN: "te-join", NOW_TALKING: "te-join", PART: "te-part", ACTION: "te-action"}.get(ln.kind)
        if pic:
            img = QTextImageFormat()
            img.setName((ASSETS / f"{pic}.png").as_uri())
            side = self.fm.height() - 2
            img.setWidth(side)
            img.setHeight(side)
            cur.insertImage(img)
        else:
            cur.insertText(self.fm.elidedText(ln.left, Qt.TextElideMode.ElideRight, self.nick_w), cf)
        cur.insertText("\t", cf)
        self._insert_text(cur, ln.text, text_col)

    def _insert_text(self, cur: QTextCursor, text: str, default_fg: str) -> None:
        t = self.cfg.theme
        for sp in parse_format(text):
            cf = QTextCharFormat()
            fg = QColor(t.palette[sp.fg % 16]) if sp.fg is not None and sp.fg < 99 else QColor(default_fg)
            bg = QColor(t.palette[sp.bg % 16]) if sp.bg is not None and sp.bg < 99 else None
            if sp.reverse:
                fg, bg = QColor(t.chat_bg), fg
            cf.setForeground(fg)
            if bg is not None:
                cf.setBackground(bg)
            if sp.bold:
                cf.setFontWeight(QFont.Weight.Bold)
            if sp.italic:
                cf.setFontItalic(True)
            if sp.underline:
                cf.setFontUnderline(True)
            for piece, is_url in split_urls(sp.text):
                if is_url:
                    link = QTextCharFormat(cf)
                    link.setAnchor(True)
                    link.setAnchorHref(piece if "://" in piece else "http://" + piece)
                    link.setFontUnderline(True)
                    cur.insertText(piece, link)
                else:
                    cur.insertText(piece, cf)

    def _open_url(self, url: QUrl) -> None:
        if url.scheme().lower() in ("http", "https", "ftp"):
            QDesktopServices.openUrl(url)

    # --- separator and marker ---------------------------------------------------

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self.viewport())
        t = self.cfg.theme
        x = int(self.sep_x + self.document().documentMargin())
        p.setPen(QPen(QColor(t.border), 1))
        p.drawLine(x, 0, x, self.viewport().height())
        b = self.current
        if b is not None and b.marker is not None:
            block = self.document().findBlockByNumber(b.marker)
            if block.isValid() and block.next().isValid():
                rect = self.document().documentLayout().blockBoundingRect(block)
                y = int(rect.bottom()) - self.verticalScrollBar().value()
                p.setPen(QPen(QColor(t.marker), 1))
                p.drawLine(0, y, self.viewport().width(), y)
