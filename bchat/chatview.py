"""The chat area, inline like XChat with the column off / AdiIRC: stamp, nick or marker, text. No column, no line.
Wrapped lines continue under the line's own text."""
from __future__ import annotations

import time

import re

import zlib

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QImage, QPainter, QPen, QTextBlockFormat,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextFormat, QTextImageFormat)
from PySide6.QtWidgets import QTextBrowser

from .config import Config
from .protocol import colour_of, parse_format, readable, split_urls
from .session import (ACTION, CONNECT, ERROR, HILITE, INFO, JOIN, MSG, NOTICE, NOW_TALKING, PART, SELF, SERVER, TOPIC,
                      WHOIS, Buffer, Line)
from .widgets import ASSETS


class ChatView(QTextBrowser):
    channel_double_clicked = Signal(str)
    central_requested = Signal(object)    # mIRC: double-click in a channel's text opens Channel Central (the buffer)
    menu_provider = None  # set by the main window; builds the right-click menu
    colour_rule = None    # set by the main window: (buffer, nick) -> colour from Nick Colours / Address Book, or None
    reply_jump = None     # set by the main window: a click on a reply's quote line (buffer, msgid)

    PICTURES = {WHOIS: "info", JOIN: "te-join", NOW_TALKING: "te-join", PART: "te-part", ACTION: "te-action"}
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
        self.fm = fm

    def _new_doc(self) -> QTextDocument:
        d = QTextDocument(self)
        d.setDefaultFont(self.chat_font)
        d.setUndoRedoEnabled(False)
        d.setDocumentMargin(3)
        d.setMaximumBlockCount(max(100, self.cfg.max_lines or self.MAX_BLOCKS))
        blank = QImage(4, 4, QImage.Format.Format_ARGB32)
        blank.fill(0)
        d.addResource(QTextDocument.ResourceType.ImageResource, QUrl("bchat:blank"), blank)
        return d

    def doc_for(self, b: Buffer) -> QTextDocument:
        d = self.docs.get(id(b))
        if d is None:
            d = self._new_doc()
            self.docs[id(b)] = d
            for ln in b.lines:
                self._render(d, b, ln)
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
        d.setDefaultFont(self.chat_font)  # setDocument hands the document the widget's UI font
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

    def reload_all(self) -> None:
        """Rebuild every tab, e.g. after Preferences: the shown one now, the others when next shown."""
        cur = self.current
        self.current = None
        self.setDocument(self._empty)
        for key in list(self.docs):
            self.docs.pop(key).deleteLater()
        if cur is not None:
            self.show_buffer(cur)

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
        self._render(d, b, ln)
        if at_end and b is self.current:
            sb.setValue(sb.maximum())

    # --- drawing a line ------------------------------------------------------

    def _kind_colours(self, kind: str) -> tuple[str, str]:
        t = self.cfg.theme
        return {
            MSG: (t.nick, t.chat_fg),
            SELF: (t.self_nick, t.self_text),
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
            CONNECT: (t.connect, t.connect),
        }.get(kind, (t.nick, t.chat_fg))

    def _render(self, d: QTextDocument, b: Buffer, ln: Line) -> None:
        self._render_flow(d, ln, server=b.kind == SERVER, b=b)

    def _left_parts(self, ln: Line, colour: str) -> list[tuple[str, str]]:
        """XChat's text events colour the brackets apart from the name (textevents.in):
        >nick< you sent: green brackets, plain name; -nick- notices: blue dashes, pink name."""
        t, left = self.cfg.theme, ln.left
        if len(left) > 2 and left[0] == ">" and left[-1] == "<":
            return [(">", t.send_bracket), (left[1:-1], t.chat_fg), ("<", t.send_bracket)]  # /msg target: plain
        if ln.kind == NOTICE and len(left) > 2 and left[0] == "-" and left[-1] == "-":
            return [("-", t.notice_bracket), (left[1:-1], t.notice_nick), ("-", t.notice_bracket)]
        return [(left, colour)]

    @staticmethod
    def _put_parts(cur: QTextCursor, parts: list[tuple[str, str]]) -> None:
        for text, colour in parts:
            cf = QTextCharFormat()
            cf.setForeground(QColor(colour))
            cur.insertText(text, cf)

    def _render_flow(self, d: QTextDocument, ln: Line, server: bool, b: Buffer | None = None) -> None:
        """Stamp, one space, nick or marker, one space, text (AdiIRC spacing). Wrapped lines continue under the
        text: on the server tab right after the marker column, elsewhere under this line's own text."""
        t = self.cfg.theme
        cur = QTextCursor(d)
        cur.movePosition(QTextCursor.MoveOperation.End)
        left_col, text_col = self._kind_colours(ln.kind)
        if ln.kind == HILITE and ln.colour:              # a highlight rule's own colour
            left_col = text_col = ln.colour
        stamp = self._stamp(ln.ts)
        pic = self.PICTURES.get(ln.kind)
        side = self.fm.height() - 2
        light = self._light_slot(ln, server)   # None, "" (empty slot) or a light name
        slot = (self.LIGHT + self.fm.horizontalAdvance(" ")) if light is not None else 0
        if server:
            indent = self.fm.horizontalAdvance(stamp + "* ")
        elif pic:
            indent = self.fm.horizontalAdvance(stamp + " ") + side
        else:
            indent = self.fm.horizontalAdvance(stamp + (ln.left + " " if ln.left else "")) + slot
        bf = QTextBlockFormat()
        bf.setLeftMargin(indent)
        bf.setTextIndent(-indent)
        bf.setLineHeight(max(100, self.cfg.line_spacing), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        if ln.msgid:
            bf.setProperty(self.MSGID, ln.msgid)          # Reply finds the line's message id here
        if ln.reply_to:
            bf.setProperty(self.QUOTE, ln.reply_to)       # a click on a quote line jumps to what it quotes
        if d.isEmpty():
            cur.setBlockFormat(bf)
        else:
            cur.insertBlock(bf)
        if stamp:
            cf = QTextCharFormat()
            cf.setForeground(QColor(t.stamp))
            cur.insertText(stamp, cf)
        if ln.left == "-":
            mark, text_col = t.motd_mark, t.motd_text
        else:
            mark = {"*": t.server_mark if ln.kind in (INFO, CONNECT) else left_col, "SSL": t.ssl_mark}.get(ln.left, left_col)
        cf = QTextCharFormat()
        cf.setForeground(QColor(mark))
        if pic:
            img = QTextImageFormat()
            img.setName(self._picture(d, pic, side))
            img.setWidth(side)
            img.setHeight(side)
            cur.insertImage(img)
            cur.insertText(" ", cf)
        elif ln.left:
            if light is not None:
                self._put_light(cur, light)
            if ln.kind == MSG and not server:
                rule = self.colour_rule(b, ln.left) if self.colour_rule is not None and b is not None else None
                if rule:
                    mark = rule
                elif self.cfg.color_nicks:
                    mark = self.nick_colour(ln.left)
            self._put_parts(cur, self._left_parts(ln, mark) + [(" ", mark)])
        self._insert_text(cur, ln.text, text_col)

    LIGHT = 7   # logical px, same as the user list
    MSGID = QTextFormat.Property.UserProperty + 1
    QUOTE = QTextFormat.Property.UserProperty + 2

    def line_at(self, pos) -> tuple[str, str]:
        """(msgid, quoted msgid) of the line under the mouse."""
        block = self.cursorForPosition(pos).block()
        f = block.blockFormat()
        return str(f.property(self.MSGID) or ""), str(f.property(self.QUOTE) or "")

    def block_of(self, msgid: str):
        d = self.document()
        block = d.lastBlock()
        while block.isValid():
            if str(block.blockFormat().property(self.MSGID) or "") == msgid:
                return block
            block = block.previous()
        return None

    def flash_block(self, block) -> None:
        """Scrolls to a line and lights it up for a moment (a reply's quote was clicked)."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QTextEdit
        cur = QTextCursor(block)
        self.setTextCursor(cur)
        self.ensureCursorVisible()
        sel = QTextEdit.ExtraSelection()
        sel.cursor = QTextCursor(block)
        sel.cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        sel.format.setBackground(QColor(self.cfg.theme.selected))
        self.setExtraSelections([sel])
        QTimer.singleShot(1200, lambda: self.setExtraSelections([]))
    NICK_COLOURS = ("flamingo", "pink", "mauve", "maroon", "peach", "yellow", "green", "teal", "sky", "sapphire", "blue")

    def _stamp(self, ts: float) -> str:
        if not self.cfg.timestamps:
            return ""
        try:
            return time.strftime(self.cfg.stamp_format or "[%H:%M]", time.localtime(ts)) + " "
        except (ValueError, TypeError):
            return time.strftime("[%H:%M]", time.localtime(ts)) + " "

    def _light_slot(self, ln: Line, server: bool) -> str | None:
        """Preferences > Text box > rank light: None (no light), a light name, or "" for an empty slot."""
        mode = self.cfg.rank_lights
        if server or mode not in ("lights", "slot") or ln.kind not in (MSG, SELF, HILITE) or not ln.left:
            return None
        if ln.left[0] in "<>-":
            return None
        if ln.rank:
            return ln.rank
        return "" if mode == "slot" else None

    def _picture(self, d: QTextDocument, pic: str, side: int) -> str:
        """A Lucide picture in the colour of what the line is (join, part, info, action), drawn once per document."""
        from . import lucide
        t = self.cfg.theme
        colour = {"te-join": t.join, "te-part": t.marker, "info": t.new_highlight, "te-action": t.highlight}.get(pic, t.text)
        px = max(16, round(side * self.devicePixelRatioF()))
        url = QUrl(f"bchat:pic/{pic}/{colour[1:]}/{px}")
        if d.resource(QTextDocument.ResourceType.ImageResource, url) is None:
            img = lucide.image(pic, colour, px)
            img.setDevicePixelRatio(px / side)
            d.addResource(QTextDocument.ResourceType.ImageResource, url, img)
        return url.toString()

    def _put_light(self, cur: QTextCursor, name: str) -> None:
        img = QTextImageFormat()
        if name:
            from .userlist import LIGHT_SIZES
            px = min(LIGHT_SIZES, key=lambda s: abs(s - self.LIGHT * self.devicePixelRatioF()))
            img.setName((ASSETS / "lights" / f"{name}-{px}.png").as_uri())
        else:
            img.setName("bchat:blank")
        img.setWidth(self.LIGHT)
        img.setHeight(self.LIGHT)
        img.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignMiddle)
        cur.insertImage(img)
        cur.insertText(" ", QTextCharFormat())

    def nick_colour(self, nick: str) -> str:
        from .config import MOCHA, PALETTES
        shades = PALETTES.get(self.cfg.theme.name, MOCHA)     # the theme's own shades; a Custom theme keeps its base's
        return shades[self.NICK_COLOURS[zlib.crc32(nick.lower().encode()) % len(self.NICK_COLOURS)]]

    def _insert_text(self, cur: QTextCursor, text: str, default_fg: str) -> None:
        t = self.cfg.theme
        strip = self.cfg.strip_colors
        for sp in parse_format(text):
            cf = QTextCharFormat()
            # 0-15 follow the theme, 16-98 are the fixed mIRC colours, hex (\x04) as sent; 99 = default
            fgc = None if strip else colour_of(sp.fg, t.palette)
            bgc = None if strip else colour_of(sp.bg, t.palette)
            if fgc and not self.cfg.colors_exact and not (isinstance(sp.fg, int) and sp.fg <= 15):
                # fixed and hex text colours: nudged just enough to read on the background they sit on
                # (the theme's 0-15 are made for it; backgrounds are never changed)
                fgc = readable(fgc, bgc or t.chat_bg)
            fg = QColor(fgc) if fgc else QColor(default_fg)
            bg = QColor(bgc) if bgc else None
            if sp.reverse and not strip:
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
            if sp.strike:
                cf.setFontStrikeOut(True)
            if sp.mono:
                cf.setFontFamilies(["Consolas", "Courier New", "monospace"])
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
        """A click on a link: the window checks it first (safety.link_risk) and says who posted it."""
        if url.scheme().lower() in ("irc", "ircs"):
            opener = getattr(self.window(), "open_irc_link", None)
            if opener is not None:
                opener(url.toString())
            return
        if url.scheme().lower() not in ("http", "https", "ftp"):
            return
        who, where = self.who_posted(url.toString())
        opener = getattr(self.window(), "open_url", None)
        if opener is not None:
            opener(url.toString(), who, where)
        else:
            QDesktopServices.openUrl(url)

    def who_posted(self, url: str) -> tuple[str, str]:
        """The newest line in this tab with that link: its nick, and the tab's name."""
        b = self.current
        if b is None:
            return "", ""
        bare = url.split("://", 1)[-1].rstrip("/")
        for ln in reversed(b.lines[-500:]):
            if bare in ln.text:
                nick = ln.text.split(" ", 1)[0] if ln.left == "*" else ln.left.strip("<>*")
                return nick, b.name
        return "", b.name

    def word_at(self, pos) -> str:
        cur = self.cursorForPosition(pos)
        line, i = cur.block().text(), cur.positionInBlock()
        start, end = i, i
        while start > 0 and not line[start - 1].isspace():
            start -= 1
        while end < len(line) and not line[end].isspace():
            end += 1
        return re.sub(r"^[\[\](){}<>,.:;!?'\"@+%~&-]+|[\[\](){}<>,.:;!?'\"]+$", "", line[start:end])

    def contextMenuEvent(self, ev):
        menu = self.menu_provider(ev.pos()) if self.menu_provider else None
        if menu is not None:
            menu.exec(ev.globalPos())
            menu.deleteLater()

    def mouseDoubleClickEvent(self, ev):
        word = self.word_at(ev.position().toPoint())
        if word.startswith(("#", "&")) and len(word) > 1:
            self.channel_double_clicked.emit(word)
            ev.accept()
            return
        b = self.current
        if b is not None and getattr(b, "kind", "") == "channel" and not self.anchorAt(ev.position().toPoint()):
            self.central_requested.emit(b)     # like mIRC; words still copy by dragging over them
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if self.textCursor().hasSelection():
            self.copy()  # selecting copies, as in XChat
        elif ev.button() == Qt.MouseButton.LeftButton and self.reply_jump is not None and self.current is not None:
            _mid, quoted = self.line_at(ev.position().toPoint())
            if quoted:
                self.reply_jump(self.current, quoted)

    # --- unread marker ----------------------------------------------------------

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self.viewport())
        t = self.cfg.theme
        b = self.current
        if b is not None and b.marker is not None and self.cfg.marker_line:
            block = self.document().findBlockByNumber(b.marker)
            if block.isValid() and block.next().isValid():
                rect = self.document().documentLayout().blockBoundingRect(block)
                y = int(rect.bottom()) - self.verticalScrollBar().value()
                p.setPen(QPen(QColor(t.marker), 1))
                p.drawLine(0, y, self.viewport().width(), y)
