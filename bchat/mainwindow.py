"""BChat main window, classic XChat 2 layout, dark."""
from __future__ import annotations

import html
import fnmatch
import json
import re
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QInputMethodEvent, QTextCharFormat, QTextCursor, QActionGroup, QShortcut, QAction, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence, QPixmap, QTextDocument
from PySide6.QtWidgets import (QBoxLayout, QProgressBar, QTabBar, QToolButton, QApplication, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QSystemTrayIcon, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetAction)

from . import __version__, commands, config
from .chatview import ChatView
from .config import Config, NetworkConfig, Server
from .protocol import URL_RE, lower, strip_format
from .session import CHANNEL, INFO, QUERY, SERVER, Buffer, Line, Session, User
from .countries import country_of
from .userlist import UserList, icon_name, light_pixmap
from .widgets import ASSETS, FramedDialog, FramelessWindow, add_menu_title, icon, install_button_look, set_icon_theme, set_light_palette, stylesheet
from . import xchat_import
from .topicbar import TopicBar, emoji_popup
from .editors import rows_for
from .about import AboutDialog
from .notify import Notifier
from .filetypes import is_program
from .safety import CertDialog, LinkDialog, ProgramDialog, link_risk
from .updater import READY, Updater
from .updatewindow import UpdateBadge, UpdateDialog
from .switchertree import SwitcherTree, tree_icon
from .quitdialog import QuitDialog
from .dcc import DccManager
from .plugins import PluginManager


class _CopyLabel(QLabel):
    """A value in the nick info panel. Plain text only; a click copies it, as XChat does."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.value = ""

    def set_value(self, v: str) -> None:
        self.value = v
        self.setText(v or "Unknown")
        f = self.font()
        f.setItalic(not v)
        self.setFont(f)

    def mousePressEvent(self, ev):
        if self.value:
            QApplication.clipboard().setText(self.value)


_SPELLER = None


def speller():
    """Loaded the first time it's needed: its word list takes a moment."""
    global _SPELLER
    if _SPELLER is None:
        try:
            from spellchecker import SpellChecker
            _SPELLER = SpellChecker()
        except Exception:      # no word list: typing must go on without marks
            return None
    return _SPELLER


class InputBox(QLineEdit):
    """History on up/down, nick completion on Tab."""

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.fixed: Buffer | None = None     # a detached window's own tab
        self.history: list[str] = []
        self.pos_ = 0
        self._cycle: list[str] = []
        self._cycle_i = 0
        self._cycle_start = 0
        self._cycle_text = ""
        self._spell_timer = QTimer(self, singleShot=True, interval=250, timeout=self.mark_spelling)
        self.textChanged.connect(lambda _: self._spell_timer.start() if self.win.cfg.spell_check or self.bad_words else None)
        self.bad_words: list[tuple[int, int]] = []

    # --- spell checking: red marks through the same call an input method uses, so the text itself stays plain ---

    SPELL_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")

    def _spell_ok(self, word: str) -> bool:
        cfg = self.win.cfg
        low = word.lower()
        if len(word) < 2 or low in (w.lower() for w in cfg.spell_words):
            return True
        b = self.fixed or self.win.buf
        if b is not None and lower(word) in b.users:      # nicks aren't typos
            return True
        return speller().known([low]) != set()

    def mark_spelling(self) -> None:
        text = self.text()
        bad: list[tuple[int, int]] = []
        checker = speller() if self.win.cfg.spell_check else None
        if checker is not None and not text.startswith("/"):
            links = [m.span() for m in URL_RE.finditer(text)]
            for m in self.SPELL_WORD.finditer(text):
                # the word still being typed isn't judged until it ends
                if m.end() == len(text) and self.hasFocus():
                    continue
                if any(a <= m.start() < z for a, z in links):
                    continue
                if not self._spell_ok(m.group(0)):
                    bad.append(m.span())
        self.bad_words = bad
        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        fmt.setUnderlineColor(QColor("#f38ba8"))    # Mocha red: a typo mark, whatever the theme's colours are
        at = self.cursorPosition()
        attrs = [QInputMethodEvent.Attribute(QInputMethodEvent.AttributeType.TextFormat, a - at, z - a, fmt) for a, z in bad]
        QApplication.sendEvent(self, QInputMethodEvent("", attrs))

    def word_at_x(self, x: int) -> tuple[int, int] | None:
        pos = self.cursorPositionAt(QPoint(x, self.height() // 2))
        for a, z in self.bad_words:
            if a <= pos <= z:
                return a, z
        return None

    def contextMenuEvent(self, ev):
        menu = self.createStandardContextMenu()
        span = self.word_at_x(ev.pos().x())
        self.fill_spell_menu(menu, span)
        menu.exec(ev.globalPos())
        menu.deleteLater()

    def fill_spell_menu(self, menu: QMenu, span) -> None:
        if span is None:
            return
        word = self.text()[span[0]:span[1]]
        first = menu.actions()[0] if menu.actions() else None
        tips = sorted(speller().candidates(word.lower()) or [])[:8]
        for tip in tips:
            act = QAction(tip, menu)
            act.triggered.connect(lambda _=False, t=tip: self._replace_word(span, t))
            menu.insertAction(first, act)
        add = QAction(f'Add "{word}" to dictionary', menu)
        add.triggered.connect(lambda _=False: self._learn(word))
        menu.insertAction(first, add)
        menu.insertSeparator(first)

    def _replace_word(self, span, word: str) -> None:
        text = self.text()
        self.setText(text[:span[0]] + word + text[span[1]:])

    def _learn(self, word: str) -> None:
        self.win.cfg.spell_words.append(word)
        self.win.save_config()
        self.mark_spelling()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.mark_spelling()

    def event(self, ev):
        if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Tab:
            self._complete()
            return True
        return super().event(ev)

    # bold, colour, underline, reset, and like mIRC: Ctrl+R reverse, Ctrl+E strikethrough
    FORMAT_KEYS = {Qt.Key.Key_B: "\x02", Qt.Key.Key_K: "\x03", Qt.Key.Key_U: "\x1f", Qt.Key.Key_O: "\x0f",
                   Qt.Key.Key_R: "\x16", Qt.Key.Key_E: "\x1e"}
    WRAPS = ("\x02", "\x1f", "\x16", "\x1e", "\x1d")   # with text selected these go round it, as in mIRC
    ITALIC = "\x1d"   # Ctrl+Shift+I: Ctrl+I stays Detach (user's choice, 11-08)

    def apply_auto_replace(self) -> None:
        """Settings > Auto Replace: the word just finished, as space or Enter is pressed."""
        text = self.text()
        at = self.cursorPosition()
        if not text or text.startswith("/") or at != len(text):
            return
        head, sep, word = text.rpartition(" ")
        for find, repl in rows_for(self.win.cfg, "auto_replace"):
            if word == find and find:
                self.setText(head + sep + repl)
                return

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        bar = self.win.chat.verticalScrollBar()
        if ev.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
            self.apply_auto_replace()
        if ev.matches(QKeySequence.StandardKey.Paste):
            pasted = QApplication.clipboard().text()
            if "\n" in pasted.strip():
                self.win.paste_lines(pasted)
                return
        if ev.key() in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and mods == Qt.KeyboardModifier.NoModifier:
            bar.setValue(bar.value() + (bar.pageStep() if ev.key() == Qt.Key.Key_PageDown else -bar.pageStep()))
        elif mods == Qt.KeyboardModifier.ShiftModifier and ev.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            bar.setValue(bar.value() + (bar.singleStep() if ev.key() == Qt.Key.Key_Down else -bar.singleStep()))
        elif mods == Qt.KeyboardModifier.ControlModifier and ev.key() in self.FORMAT_KEYS:
            self._format_key(self.FORMAT_KEYS[ev.key()])
        elif mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) and ev.key() == Qt.Key.Key_I:
            self._format_key(self.ITALIC)
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods & Qt.KeyboardModifier.ShiftModifier:
            at = self.cursorPosition()                     # Shift+Enter: a new line, the box grows
            text = self.text()
            self.expand(text[:at] + "\n" + text[at:], at + 1)
        elif ev.key() == Qt.Key.Key_Up and self.history:
            self.pos_ = max(0, self.pos_ - 1)
            self._show_history(self.history[self.pos_])
        elif ev.key() == Qt.Key.Key_Down:
            self.pos_ = min(len(self.history), self.pos_ + 1)
            self._show_history(self.history[self.pos_] if self.pos_ < len(self.history) else "")
        else:
            self._cycle = []
            super().keyPressEvent(ev)

    def _show_history(self, text: str) -> None:
        if "\n" in text:
            self.expand(text, len(text))
        else:
            self.setText(text)

    # --- several lines: Shift+Enter swaps this box for a growing one, and back when it is one line again ---

    multi = None

    def _layout(self):
        par = self.parentWidget()
        for lay in [par.layout(), *par.findChildren(QBoxLayout)]:
            if lay is not None and lay.indexOf(self) != -1:
                return lay
        return None

    def expand(self, text: str, cursor: int) -> None:
        if self.multi is None:
            self.multi = MultiInput(self)
        lay = self._layout()
        if lay is None:
            return
        lay.replaceWidget(self, self.multi)
        self.hide()
        self.multi.show_text(text, cursor)

    def collapse(self, text: str, cursor: int) -> None:
        m = self.multi
        lay = None
        par = m.parentWidget()
        for l in [par.layout(), *par.findChildren(QBoxLayout)]:
            if l is not None and l.indexOf(m) != -1:
                lay = l
        if lay is not None:
            lay.replaceWidget(m, self)
        m.hide()
        self.show()
        self.setText(text)
        self.setCursorPosition(min(cursor, len(text)))
        self.setFocus()

    def is_multi(self) -> bool:
        return self.multi is not None and self.multi.isVisible()

    def send_multi(self) -> None:
        """Enter in the big box: every line goes as a message (paced, the paste window over 5 lines)."""
        text = self.multi.toPlainText()
        self.collapse("", 0)
        if not text.strip():
            return
        self.remember(text)
        self.win.paste_lines(text, self.fixed)

    def _format_key(self, code: str) -> None:
        """Insert a format code; with text selected, bold/underline/reverse/strike/italic go round it."""
        if code in self.WRAPS and self.hasSelectedText():
            self.insert(code + self.selectedText() + code)
        else:
            self.insert(code)

    def remember(self, text: str) -> None:
        self.history.append(text)
        del self.history[:-200]
        self.pos_ = len(self.history)

    def _candidates(self, word: str, at_start: bool) -> list[str]:
        b = self.fixed or self.win.buf
        s = b.session
        low = lower(word)
        if at_start and word.startswith("/"):
            return ["/" + c for c in commands.command_names(self.win.cfg) if c.startswith(low[1:])]
        if s.is_channel(word):
            return [x.name for x in s.buffers.values() if x.kind == CHANNEL and lower(x.name).startswith(low)]
        matches = [u for u in b.sorted_users() if lower(u.nick).startswith(low)]
        if self.win.cfg.complete_sort == "recent":   # last to speak first
            matches.sort(key=lambda u: -u.last_msg)
        else:
            matches.sort(key=lambda u: lower(u.nick))
        names = [u.nick for u in matches]
        if b.kind == QUERY and lower(b.name).startswith(low):
            names.append(b.name)
        return names

    def _complete(self) -> None:
        b = self.fixed or self.win.buf
        if b is None:
            return
        text = self.text()
        # the text changed since the last Tab (typing, history), so this is a new completion
        if text != self._cycle_text:
            self._cycle = []
        if not self._cycle:
            cur = self.cursorPosition()
            self._cycle_start = text.rfind(" ", 0, cur) + 1
            word = text[self._cycle_start:cur]
            if not word:
                return
            self._cycle = self._candidates(word, self._cycle_start == 0)
            self._cycle_i = 0
            if not self._cycle:
                return
        item = self._cycle[self._cycle_i % len(self._cycle)]
        self._cycle_i += 1
        is_nick = not item.startswith("/") and not b.session.is_channel(item)
        suffix = self.win.cfg.nick_suffix if is_nick and self._cycle_start == 0 else ""
        self.setText(text[: self._cycle_start] + item + suffix + " ")
        self._cycle_text = self.text()


class MultiInput(QPlainTextEdit):
    """The input box with several lines (Shift+Enter). Grows to MAX_LINES, then scrolls. Enter sends them all,
    Tab completes, Ctrl+B and the other format keys work; back to one line, it gives the text back to the line box."""
    MAX_LINES = 5

    def __init__(self, owner: InputBox):
        super().__init__(owner.parentWidget())
        self.owner = owner
        self.setObjectName("multiinput")
        self.setFont(owner.font())
        self.setTabChangesFocus(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.document().setDocumentMargin(2)
        self.textChanged.connect(self._changed)
        self._cycle: list[str] = []
        self._cycle_i = 0
        self._cycle_start = 0
        self._cycle_text = ""

    def show_text(self, text: str, cursor: int) -> None:
        self.blockSignals(True)
        self.setPlainText(text)
        self.blockSignals(False)
        c = self.textCursor()
        c.setPosition(min(cursor, len(text)))
        self.setTextCursor(c)
        self.show()
        self.fit()
        self.setFocus()

    def lines_shown(self) -> int:
        n = 0
        block = self.document().begin()
        while block.isValid():
            n += max(1, block.layout().lineCount()) if block.layout() is not None else 1
            block = block.next()
        return n

    def fit(self) -> None:
        n = max(2, min(self.MAX_LINES, self.lines_shown()))
        h = n * self.fontMetrics().lineSpacing() + 2 * int(self.document().documentMargin()) + 2 * self.frameWidth() + 2
        self.setFixedHeight(h)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if self.lines_shown() > self.MAX_LINES
                                        else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _changed(self) -> None:
        if self.document().blockCount() == 1:              # one line again: back to the line box
            self.owner.collapse(self.toPlainText(), self.textCursor().position())
            return
        self.fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.isVisible():
            QTimer.singleShot(0, self.fit)

    def event(self, ev):
        if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Tab:
            self._complete()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.insertPlainText("\n")
            else:
                self.owner.send_multi()
            return
        if mods == Qt.KeyboardModifier.ControlModifier and ev.key() in InputBox.FORMAT_KEYS:
            self._format_key(InputBox.FORMAT_KEYS[ev.key()])
            return
        if mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) and ev.key() == Qt.Key.Key_I:
            self._format_key(InputBox.ITALIC)
            return
        self._cycle = []
        super().keyPressEvent(ev)

    def _format_key(self, code: str) -> None:
        c = self.textCursor()
        if code in InputBox.WRAPS and c.hasSelection():
            c.insertText(code + c.selectedText() + code)
        else:
            c.insertText(code)

    def _complete(self) -> None:
        """Tab: the same nick, channel and command completion as the line box, on the word before the cursor."""
        b = self.owner.fixed or self.owner.win.buf
        if b is None:
            return
        text = self.toPlainText()
        if text != self._cycle_text:
            self._cycle = []
        c = self.textCursor()
        if not self._cycle:
            cur = c.position()
            line_start = text.rfind("\n", 0, cur) + 1
            self._cycle_start = max(line_start, text.rfind(" ", 0, cur) + 1)
            word = text[self._cycle_start:cur]
            if not word:
                return
            self._cycle = self.owner._candidates(word, self._cycle_start == 0)
            self._cycle_i = 0
            self._cycle_end = cur
            if not self._cycle:
                return
        item = self._cycle[self._cycle_i % len(self._cycle)]
        self._cycle_i += 1
        is_nick = not item.startswith("/") and not b.session.is_channel(item)
        suffix = self.owner.win.cfg.nick_suffix if is_nick and self._cycle_start == text.rfind("\n", 0, self._cycle_start) + 1 else ""
        c.setPosition(self._cycle_start)
        c.setPosition(self._cycle_end if self._cycle_i == 1 else self._last_end, QTextCursor.MoveMode.KeepAnchor)
        c.insertText(item + suffix + " ")
        self._last_end = c.position()
        self.setTextCursor(c)
        self._cycle_text = self.toPlainText()


class MainWindow(FramelessWindow):
    quit_requested = Signal()

    def __init__(self, cfg: Config, cfg_dir: Path):
        super().__init__()
        self.cfg = cfg
        self.cfg_dir = cfg_dir
        self.sessions: dict[str, Session] = {}
        self.started_at = time.time()                  # /online: how long BChat has been running
        from .highlights import migrate
        migrate(cfg)                                    # XChat's highlight lists -> rules, however cfg was made
        from .nowplaying import Announcer
        self.announcer = Announcer(cfg, self._announce, self)     # off unless /np and announcing are both on
        self.announcer.refresh()
        self.buf: Buffer | None = None
        self.items: dict[int, QTreeWidgetItem] = {}
        self.folders: dict[tuple[int, str], QTreeWidgetItem] = {}
        self._was_maximized = False
        self._tray_now = False       # the quit popup's Minimize to Tray, with no tray option on
        self.raw_log: QPlainTextEdit | None = None
        self.raw_lines: list[str] = []
        self.setWindowIcon(QIcon(str(ASSETS / "bchat.ico")))
        set_icon_theme(cfg.theme)        # before any button is made: a light theme tints the white icons
        set_light_palette(cfg.theme)
        install_button_look()
        self.setStyleSheet(stylesheet(cfg.theme))
        self.resize(cfg.win_width, cfg.win_height)
        if cfg.win_x >= 0 and QGuiApplication.screenAt(QPoint(cfg.win_x + 50, cfg.win_y + 10)) is not None:
            self.move(cfg.win_x, cfg.win_y)
        self.tray: QSystemTrayIcon | None = None
        self._tray_blink = False
        self._replayed: set[int] = set()
        self.tools: dict = {}
        self.urls: list[str] = []
        self.detached: dict = {}
        self.dcc = DccManager(self)
        self.plugins = PluginManager(self)
        self._tabs_busy = False
        self.updater = Updater(cfg, cfg_dir, self)
        self.notifier = Notifier(cfg.theme, self)
        self.notifier.open_requested.connect(self._open_from_notice)
        self._last_sound = 0.0
        self._last_chime = -100.0
        self.updater.install_requested.connect(self._install_update_now)
        self._update_restart = False
        self.update_window: UpdateDialog | None = None
        self._build()
        self._build_menus()
        self.default_keys = {name: a.shortcut().toString() for name, a in self.named_actions().items()}
        self._key_shortcuts: list = []
        self._apply_widget_prefs()
        self.lists_changed(save=False)
        self._refresh_all()
        self.plugins.autoload()

    # --- layout ---------------------------------------------------------------

    def _build(self) -> None:
        self.menubar_ = self.menuBar()
        self.menubar_.setNativeMenuBar(False)
        self.outer.addWidget(self.menubar_)

        body = QWidget(self.root)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)
        self.split = QSplitter(Qt.Orientation.Horizontal, body)
        self.split.setHandleWidth(3)
        self.split.setChildrenCollapsible(False)

        self.tree = SwitcherTree(self.cfg.theme, self.split)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.itemDoubleClicked.connect(self._tree_double_clicked)
        self.tree.viewport().installEventFilter(self)   # a network's tooltip: bouncer + online time, fresh on each hover
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._tree_selected)
        self.tabbar = QTabBar(body)
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabbar.customContextMenuRequested.connect(self._tab_menu)
        self.tabbar.currentChanged.connect(self._tab_selected)

        mid = QWidget(self.split)
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(3)
        self.topic = TopicBar(self.cfg.theme, mid)
        self.topic.edit.exact = self.cfg.colors_exact
        self.topic.submitted.connect(self._topic_entered)
        top_row = QHBoxLayout()
        top_row.setSpacing(3)
        top_row.addWidget(self.topic, 1)
        self.mode_bar = QWidget(mid)
        mbl = QHBoxLayout(self.mode_bar)
        mbl.setContentsMargins(0, 0, 0, 0)
        mbl.setSpacing(1)
        self.mode_buttons: dict[str, QPushButton] = {}
        for letter in "tnsipmblk":
            btn = QPushButton(letter, self.mode_bar, objectName="modebtn")
            btn.setCheckable(True)
            btn.setFixedSize(20, 20)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip({"t": "Topic protection", "n": "No outside messages", "s": "Secret", "i": "Invite only", "p": "Private",
                            "m": "Moderated", "b": "Ban List", "l": "User limit", "k": "Keyword"}[letter])
            btn.clicked.connect(lambda _=False, c=letter: self._mode_clicked(c))
            mbl.addWidget(btn)
            self.mode_buttons[letter] = btn
        top_row.addWidget(self.mode_bar)
        self.dialog_bar = QWidget(mid)
        self.dialog_lay = QHBoxLayout(self.dialog_bar)
        self.dialog_lay.setContentsMargins(0, 0, 0, 0)
        self.dialog_lay.setSpacing(2)
        top_row.addWidget(self.dialog_bar)
        ml.addLayout(top_row)
        self.chat = ChatView(self.cfg, mid)
        self.chat.menu_provider = self._chat_menu
        self.chat.colour_rule = self.chat_colour_rule
        self.chat.reply_jump = self.reply_jump
        self.chat.channel_double_clicked.connect(self._join_clicked)
        self.chat.central_requested.connect(self.open_channel_central)
        ml.addWidget(self.chat, 1)
        self.typing_label = QLabel(mid, objectName="typing")       # 0.3.0 +typing: "Aiman is typing..."
        self.typing_label.setTextFormat(Qt.TextFormat.PlainText)
        self.typing_label.setStyleSheet(f"color: {self.cfg.theme.muted}; font-style: italic; padding: 1px 6px;")
        self.typing_label.hide()
        ml.addWidget(self.typing_label)

        right = QWidget(self.split)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(3)
        self.count = QLabel(right, objectName="count")
        self.count.setTextFormat(Qt.TextFormat.PlainText)
        rl.addWidget(self.count)
        self.userlist = UserList(self.cfg.theme, right, self.cfg)
        self.userlist.itemDelegate().colour_rule = self.list_colour_rule
        self.userlist.doubleClicked.connect(self._nick_double)
        self.userlist.customContextMenuRequested.connect(self._nick_menu)
        rl.addWidget(self.userlist, 1)
        self.ul_button_box = QWidget(right)
        self.ul_button_grid = QGridLayout(self.ul_button_box)
        self.ul_button_grid.setContentsMargins(0, 0, 0, 0)
        self.ul_button_grid.setSpacing(1)
        rl.addWidget(self.ul_button_box)
        self.right_panel = right

        self.split.addWidget(self.tree)
        self.split.addWidget(mid)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        if not self.cfg.tree_widened:      # once only, so a narrower width the user drags later is kept
            self.cfg.pane_left = max(self.cfg.pane_left, 180)
            self.cfg.tree_widened = True
        self.split.setSizes([self.cfg.pane_left, 720, self.cfg.pane_right])
        lay.addWidget(self.split, 1)
        self.body_lay = lay
        self.mid_panel = mid

        bottom = QHBoxLayout()
        bottom.setSpacing(3)
        self.own_light = QLabel(body)
        self.own_light.setFixedSize(8, 19)  # one spare pixel, as 7 px at 150 % is really 7.33
        self.own_light.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom.addSpacing(4)
        bottom.addWidget(self.own_light)
        self.nick_label = QLabel(body, objectName="nicklabel")
        self.nick_label.installEventFilter(self)
        self.nick_label.setToolTip("Click to change your nick")
        self.nick_label.setTextFormat(Qt.TextFormat.PlainText)
        bottom.addWidget(self.nick_label)
        self.input = InputBox(self)
        self.input.returnPressed.connect(self._entered)
        bottom.addWidget(self.input, 1)
        self.meter_text = QLabel(body)
        self.lag_bar = QProgressBar(body)
        self.queue_bar = QProgressBar(body)
        for bar, tip in ((self.lag_bar, "Lag"), (self.queue_bar, "Lines waiting to be sent")):
            bar.setTextVisible(False)
            bar.setRange(0, 100)
            bar.setFixedSize(44, 8)
            bar.setToolTip(tip)
        self.meter_text.setToolTip("Lag, and lines waiting to be sent")
        bottom.addWidget(self.meter_text)
        meters = QVBoxLayout()
        meters.setSpacing(2)
        meters.addWidget(self.lag_bar)
        meters.addWidget(self.queue_bar)
        bottom.addLayout(meters)
        self.emoji_btn = QToolButton(body)
        self.emoji_btn.setText("\U0001F642")
        self.emoji_btn.setToolTip("Emoji (Windows: Win + . for all of them)")
        self._style_emoji_btn()
        self.emoji_btn.clicked.connect(self._emoji_for_input)
        bottom.addWidget(self.emoji_btn)
        self.status_strip = QLabel(body)
        self.status_strip.setFixedWidth(3)
        self._status_colour = ""
        bottom.addWidget(self.status_strip)
        # lag grows while a ping goes unanswered, with no event to react to
        self._status_timer = QTimer(self, interval=1000, timeout=self._refresh_status)
        self._status_timer.start()
        self._blink_timer = QTimer(self, interval=500, timeout=self._blink_tray)
        # 0.3.0: Delete logs older than ..., a moment after start and every 6 hours
        self._log_clean_timer = QTimer(self, interval=6 * 3600 * 1000, timeout=self.clean_old_logs)
        self._log_clean_timer.start()
        QTimer.singleShot(5000, self.clean_old_logs)
        from .invitebar import InviteBar
        self.invite_bar = InviteBar(self, body)
        lay.addWidget(self.invite_bar)
        from .reportwindow import ProblemBar
        self.report_bar = ProblemBar(self, body)       # after a crash, an error or a freeze (0.3.0)
        lay.addWidget(self.report_bar)
        self.reply_bar = QWidget(body, objectName="replybar")    # 0.3.0 +reply: what you are answering
        rb = QHBoxLayout(self.reply_bar)
        rb.setContentsMargins(8, 2, 4, 2)
        self.reply_text = QLabel(self.reply_bar)
        self.reply_text.setTextFormat(Qt.TextFormat.RichText)
        rb.addWidget(self.reply_text, 1)
        self.reply_close = QToolButton(self.reply_bar)
        self.reply_close.setIcon(icon("close-light"))
        self.reply_close.setToolTip("Cancel the reply (Esc)")
        self.reply_close.clicked.connect(self.cancel_reply)
        rb.addWidget(self.reply_close)
        self.reply_bar.setStyleSheet(f"#replybar {{ background: {self.cfg.theme.bar}; border-top: 1px solid {self.cfg.theme.border}; }}")
        self.reply_bar.hide()
        self.replying: tuple | None = None          # (buffer, msgid, nick)
        lay.addWidget(self.reply_bar)
        lay.addLayout(bottom)
        self.input.installEventFilter(self)          # Esc in the input box cancels a reply (nowhere else)
        QShortcut(QKeySequence("Alt+R"), self, self.reply_to_last)
        self._typing_sent = 0.0                     # when we last told the channel we're typing
        self._typing_to: tuple | None = None
        self.input.textChanged.connect(self._input_typing)
        self.outer.addWidget(body, 1)

        self.topic.setVisible(self.cfg.show_topic)
        self.menubar_.setVisible(self.cfg.show_menu)

    def _act(self, menu: QMenu, text: str, slot=None, shortcut: str = "", ico: str = "", checkable=False, checked=False) -> QAction:
        a = QAction(text, self)
        if ico:
            a.setIcon(icon(ico))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if checkable:
            a.setCheckable(True)
            a.setChecked(checked)
        if slot is not None:
            (a.toggled if checkable else a.triggered).connect(slot)
        else:
            a.setEnabled(False)
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_menus(self) -> None:
        m = self.menubar_
        x = m.addMenu("&BChat")
        self._act(x, "Network Li&st...", self.open_network_list, "Ctrl+S", "book")
        new = x.addMenu(icon("new"), "&New")
        self._act(new, "Server Tab...", self.new_server_tab, "Ctrl+T")
        self._act(new, "Channel Tab...", self.new_channel_tab)
        self._act(new, "Server Window...", lambda: self.detach(self.new_server_tab().server_buffer))
        self._act(new, "Channel Window...", lambda: self.detach(self.new_channel_tab()))
        x.addSeparator()
        self._act(x, "&Load Plugin or Script...", self.load_plugin_dialog, "", "revert")
        self._act(x, "&Import XChat Settings...", self._import_settings, "", "open")
        x.addSeparator()
        self._act(x, "&Detach", lambda: self.detach(self.buf), "Ctrl+I", "dialog")
        self._act(x, "&Close", lambda: self.close_buffer(self.buf), "Ctrl+W", "close-light")
        x.addSeparator()
        self._act(x, "&Quit", self._quit_for_real, "Ctrl+Q", "quit")

        v = m.addMenu("&View")
        self._act(v, "&Menu Bar", self._toggle_menu, "Ctrl+F9", checkable=True, checked=self.cfg.show_menu)
        self._act(v, "&Topic Bar", self._toggle_topic, checkable=True, checked=self.cfg.show_topic)
        self._act(v, "&User List", self._toggle_userlist, "Ctrl+F7", checkable=True, checked=self.cfg.show_userlist)
        self._act(v, "U&serlist Buttons", self._toggle_ul_buttons, checkable=True, checked=self.cfg.show_ul_buttons)
        self._act(v, "M&ode Buttons", self._toggle_mode_buttons, checkable=True, checked=self.cfg.show_mode_buttons)
        v.addSeparator()
        cs = v.addMenu("&Channel Switcher")
        self.layout_group = QActionGroup(self)
        self.tabs_act = self._act(cs, "&Tabs", lambda on: on and self.set_tab_layout("tabs"), checkable=True, checked=self.cfg.tab_layout == "tabs")
        self.tree_act = self._act(cs, "T&ree", lambda on: on and self.set_tab_layout("tree"), checkable=True, checked=self.cfg.tab_layout == "tree")
        self.layout_group.addAction(self.tabs_act)
        self.layout_group.addAction(self.tree_act)
        nm = v.addMenu("&Network Meters")
        self.meter_group = QActionGroup(self)
        for i, name in enumerate(("Off", "Graph", "Text", "Both")):
            self.meter_group.addAction(self._act(nm, name, lambda on, i=i: on and self.set_meters(i), checkable=True, checked=self.cfg.meters == i))

        s = m.addMenu("&Server")
        self._act(s, "&Disconnect", lambda: self.session and self.session.disconnect_from_network(), "", "disconnect")
        self._act(s, "&Reconnect", lambda: self.session and self.session.reconnect(), "", "connect")
        self._act(s, "Join a Channel...", self._join_dialog, "", "jump")
        self._act(s, "Favourite Channels...", self.open_favourites, "", "favourite")
        self._act(s, "List of Channels...", lambda: self.session and self.open_channel_list(self.session), "", "justify")
        s.addSeparator()
        self.away_act = self._act(s, "Marked Away", self._toggle_away, "Alt+A", checkable=True)

        st = m.addMenu("S&ettings")
        self._act(st, "&Preferences", self.open_preferences, "", "preferences")
        adv = st.addMenu(icon("justify"), "Advanced")
        for name, key in (("Auto Replace...", "replace"), ("CTCP Replies...", "ctcp"), ("Dialog Buttons...", "dialog"),
                          ("Keyboard Shortcuts...", "keys"), ("Slaps...", "slaps"), ("Text Events...", "events"), ("URL Handlers...", "url"),
                          ("User Commands...", "commands"), ("Userlist Buttons...", "ulbuttons"), ("Userlist Popup...", "popup")):
            self._act(adv, name, lambda _=False, k=key: self.open_editor(k))
        self._act(adv, "Nick Colours...", self.open_nick_colours)

        w = m.addMenu("&Window")
        self._act(w, "Address Book...", lambda: self.open_address_book(), "", "book")
        self._act(w, "Auto-Op && Protect...", lambda: self.open_control())
        self._act(w, "Ban List...", self.open_ban_list)
        self._act(w, "Character Chart...", lambda: self.open_tool("chart"))
        self._act(w, "Direct Chat...", self.open_chats)
        self._act(w, "File Transfers...", self.open_transfers)
        self._act(w, "Friends List...", lambda: self.open_tool("friends"))
        self._act(w, "Ignore List...", lambda: self.open_tool("ignore"))
        self._act(w, "Logs...", lambda: self.open_logs(), "", "find")
        self._act(w, "Plugins and Scripts...", lambda: self.open_tool("plugins"))
        self._act(w, "Raw Log...", self._open_raw_log)
        self._act(w, "URL Grabber...", lambda: self.open_tool("urls"))
        w.addSeparator()
        self._act(w, "Reset Marker Line", self.chat.reset_marker, "Ctrl+M")
        self._act(w, "C&lear Text", self._clear_current, "Ctrl+L", "clear")
        self._act(w, "Search Text...", self._search, "Ctrl+F", "find")
        self._act(w, "Save Text...", self._save_text, "", "save")

        h = m.addMenu("&Help")
        self._act(h, "&Contents", self.open_help, "F1", "help")
        self._act(h, "Report a &Problem...", lambda: self.report_problem(), "", "report")
        self._act(h, "Check for &Updates...", self.check_updates, "", "refresh")
        self._act(h, "&Support BChat on Ko-fi...", self.open_support, "", "support")
        self._act(h, "&About", self._about, "", "about")
        # after Help: shows only while an update waits, downloads, is ready or failed
        self.update_act = QAction(" ", self)
        self.update_act.triggered.connect(self.open_update_window)
        m.addAction(self.update_act)
        self.update_badge = UpdateBadge(m, self.update_act, self.updater, self.cfg.theme)

        for key, delta in (("Ctrl+PgUp", -1), ("Ctrl+PgDown", 1)):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, d=delta: self._change_page(delta=d))
            self.addAction(a)
        for n in range(1, 10):
            a = QAction(self)
            a.setShortcut(QKeySequence(f"Alt+{n}"))
            a.triggered.connect(lambda _=False, i=n: self._change_page(number=i))
            self.addAction(a)

    # --- sessions -------------------------------------------------------------

    @property
    def session(self) -> Session | None:
        return self.buf.session if self.buf is not None else None

    def session_for(self, net: NetworkConfig) -> Session:
        s = self.sessions.get(net.name)
        if s is None:
            s = Session(net, self.cfg, self)
            self.sessions[net.name] = s
            s.buffer_added.connect(self._buffer_added)
            s.buffer_removed.connect(self._buffer_removed)
            s.buffer_changed.connect(self._buffer_changed)
            s.users_changed.connect(self._users_changed)
            s.line_added.connect(self.chat.add_line)
            s.lines_inserted.connect(self.chat.reload)
            s.invited.connect(lambda sess, chan, nick: self.invite_bar.add(sess, chan, nick))
            s.typing_changed.connect(lambda b: self.show_typing() if b is self.buf else None)
            s.line_added.connect(self._log_line)
            s.line_added.connect(self._grab_urls)
            s.friends_changed.connect(self._friends_changed)
            s.notify.connect(self._on_notify)
            s.cert_question.connect(lambda info, s=s: self._cert_question(s, info))
            s.pins_changed.connect(self.save_config)
            s.on_command = self.run_command
            s.on_dcc = self.dcc.incoming
            s.dcc_say = self.dcc.say
            s.server_hook = self.plugins.on_server
            s.print_hook = self.plugins.on_print
            s.state_changed.connect(self._state_changed)
            s.raw_line.connect(self._raw)
            self._buffer_added(s.server_buffer)
        return s

    def connect_network(self, net: NetworkConfig) -> Session:
        s = self.session_for(net)
        if s.state == "disconnected":
            s.connect_to_network()
        self.select_buffer(s.server_buffer)
        return s

    def server_command(self, s: Session, host: str, port: int, ssl: bool, password: str) -> None:
        """/server: this tab now belongs to the new host, so the Network List can still open the old network later."""
        for key, value in list(self.sessions.items()):
            if value is s:
                del self.sessions[key]
        name = host
        n = 2
        while name in self.sessions:
            name = f"{host} ({n})"
            n += 1
        s.connect_manual(host, port, ssl, password)
        self.sessions[name] = s
        self.select_buffer(s.server_buffer)

    def new_server_tab(self) -> Session:
        """An empty tab with no server yet, like XChat's: the user types /server in it."""
        name = "<none>"
        n = 2
        while name in self.sessions:
            name = f"<none> ({n})"
            n += 1
        s = self.session_for(NetworkConfig(name))
        s.add(s.server_buffer, INFO, "*", "Type /server <host> [port or +port for SSL] to connect, for example /server irc.bajubesi.org +6697")
        self.select_buffer(s.server_buffer)
        self.input.setFocus()
        return s

    def autoconnect(self) -> None:
        first = True
        for net in self.cfg.networks:
            if net.autoconnect:
                s = self.session_for(net)
                s.connect_to_network()
                if first:
                    self.select_buffer(s.server_buffer)
                    first = False

    # --- buffers and tree -------------------------------------------------------

    def _buffer_added(self, b: Buffer) -> None:
        it = QTreeWidgetItem()
        it.setText(0, b.name)
        it.setData(0, Qt.ItemDataRole.UserRole, b)
        self.items[id(b)] = it
        self._load_replay(b)
        self.chat.doc_for(b)
        if b.kind == SERVER:
            it.setIcon(0, tree_icon("server"))
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)
        else:
            self._file_item(b)
            # a new tab only takes the front when nothing is being read, or the user asked for it
            asked = lower(b.name) == b.session.focus_next
            reading_server = self.buf is None or (self.buf.kind == SERVER and self.buf.session is b.session)
            focus = self.cfg.tab_focus
            if asked:
                b.session.focus_next = ""
            if focus == 1 or (focus == 2 and (asked or (b.kind == CHANNEL and reading_server))) or (focus == 0 and self.buf is None):
                self.select_buffer(b)
            if b.kind == QUERY and self.cfg.dialogs_in_windows and b.name != "(notices)":
                self.detach(b)
        self._rebuild_tabs()

    def _buffer_removed(self, b: Buffer) -> None:
        w = self.detached.pop(id(b), None)
        if w is not None:
            w.unhook()
            w.hide()
            w.deleteLater()
        it = self.items.pop(id(b), None)
        if it is not None:
            folder = it.parent()
            (folder or self.tree.invisibleRootItem()).removeChild(it)
            if folder is not None:
                self._folder_changed(b.session, folder)
        self.chat.forget(b)
        if self.buf is b:
            self.buf = None
            self.select_buffer(b.session.server_buffer)
        self._rebuild_tabs()

    def _buffer_changed(self, b: Buffer) -> None:
        self.tray_tip()
        if b is self.buf:
            self._sync_button_bars()
        it = self.items.get(id(b))
        if it is not None:
            renamed = it.text(0) != self._short_name(b)
            it.setText(0, self._short_name(b))
            if renamed and self.cfg.tab_sort and it.parent() is not None:
                it.parent().sortChildren(0, Qt.SortOrder.AscendingOrder)
            it.setToolTip(0, self.buffer_tip(b))
            t = self.cfg.theme
            colour = {0: t.text, 1: t.new_data, 2: t.new_msg, 3: t.new_highlight}.get(b.activity, t.text)
            if b.kind == CHANNEL and not b.joined:
                colour = t.away
            it.setForeground(0, QColor(colour))
            self._rebuild_tabs()
        if b is self.buf:
            self.topic.set_topic(b.topic)
            self._topic_permission()
            self._refresh_title()
            if not b.lines:
                self.chat.reload(b)

    def _users_changed(self, b: Buffer) -> None:
        if b is self.buf:
            self._topic_permission()   # own op/deop changes who may set the topic
            self.userlist.set_buffer(b)
            self._refresh_count()
            self._refresh_title()

    def _state_changed(self) -> None:
        self._refresh_title()
        s = self.session
        if s is not None:
            self.away_act.blockSignals(True)
            self.away_act.setChecked(s.away)
            self.away_act.blockSignals(False)

    def select_buffer(self, b: Buffer | None) -> None:
        if b is None:
            return
        w = self.detached.get(id(b))
        if w is not None:
            w.show()
            w.raise_()
            w.activateWindow()
            return
        it = self.items.get(id(b))
        if it is not None and self.tree.currentItem() is not it:
            self.tree.setCurrentItem(it)
        elif it is not None:
            self._show(b)

    def _tree_selected(self, cur, prev) -> None:
        if cur is None:
            return
        b = cur.data(0, Qt.ItemDataRole.UserRole)
        if b is None:      # a folder row
            return
        if id(b) in self.detached:      # it lives in its own window: raise that, the main window keeps its tab
            self.select_buffer(b)
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(prev)
            self.tree.blockSignals(False)
            return
        self._show(b)

    # --- channel switcher: Tabs or Tree, and where it sits ---------------------------------

    def _short_name(self, b: Buffer) -> str:
        n = self.cfg.tab_trunc
        return b.name[:n] + ".." if n and len(b.name) > n + 2 else b.name

    def _tree_clicked(self, it, _col=0) -> None:
        if it.data(0, Qt.ItemDataRole.UserRole) is None:     # a folder row opens and closes
            it.setExpanded(not it.isExpanded())

    def _tree_double_clicked(self, it, _col=0) -> None:
        b = it.data(0, Qt.ItemDataRole.UserRole)
        if b is not None and b.kind == SERVER:
            it.setExpanded(not it.isExpanded())

    def _file_item(self, b: Buffer) -> None:
        """Puts a tab in its server's Channel or Private folder, making the folder when it's the first one."""
        s = b.session
        it = self.items[id(b)]
        kind = "Channel" if b.kind == CHANNEL else "Private"
        key = (id(s), kind)
        folder = self.folders.get(key)
        if folder is None:
            folder = self.folders[key] = QTreeWidgetItem()
            folder.setIcon(0, tree_icon("folder"))
            folder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            folder.setData(0, Qt.ItemDataRole.UserRole, None)
            folder.setData(0, Qt.ItemDataRole.UserRole + 1, kind)
            top = self.items[id(s.server_buffer)]
            top.insertChild(0 if kind == "Channel" else top.childCount(), folder)
            top.setExpanded(True)
        old = it.parent()
        if old is folder:
            return
        if old is not None:
            old.removeChild(it)
            self._folder_changed(s, old)
        folder.addChild(it)
        it.setIcon(0, tree_icon("channel" if b.kind == CHANNEL else "query"))
        folder.setExpanded(True)
        self._folder_changed(s, folder)

    def _folder_changed(self, s: Session, folder: QTreeWidgetItem) -> None:
        kind = folder.data(0, Qt.ItemDataRole.UserRole + 1)
        if not folder.childCount():
            top = folder.parent()
            if top is not None:
                top.removeChild(folder)
            self.folders.pop((id(s), kind), None)
            return
        folder.setText(0, f"{kind}: {folder.childCount()}")
        if self.cfg.tab_sort:
            folder.sortChildren(0, Qt.SortOrder.AscendingOrder)

    def _buffer_rows(self) -> list[QTreeWidgetItem]:
        """Every row that is a tab, in the order shown: folders don't count for Alt+1-9 or Ctrl+PageUp/Down."""
        order = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            order.append(top)
            for j in range(top.childCount()):
                folder = top.child(j)
                order.extend(folder.child(n) for n in range(folder.childCount()))
        return order

    def _switcher_order(self) -> list[Buffer]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self._buffer_rows()]

    def _rebuild_tabs(self) -> None:
        if self.cfg.tab_layout != "tabs":
            return
        self._tabs_busy = True
        order = self._switcher_order()
        t = self.cfg.theme
        while self.tabbar.count() > len(order):
            self.tabbar.removeTab(self.tabbar.count() - 1)
        while self.tabbar.count() < len(order):
            self.tabbar.addTab("")
        for i, b in enumerate(order):
            self.tabbar.setTabText(i, self._short_name(b).replace("&", "&&"))
            self.tabbar.setTabData(i, b)
            self.tabbar.setTabToolTip(i, self.buffer_tip(b))
            colour = {0: t.text, 1: t.new_data, 2: t.new_msg, 3: t.new_highlight}.get(b.activity, t.text)
            if b.kind == CHANNEL and not b.joined:
                colour = t.away
            self.tabbar.setTabTextColor(i, QColor(colour))
            if b is self.buf:
                self.tabbar.setCurrentIndex(i)
        self._tabs_busy = False

    def _tab_selected(self, index: int) -> None:
        if self._tabs_busy or index < 0:
            return
        b = self.tabbar.tabData(index)
        if b is not None:
            self.select_buffer(b)
            self._rebuild_tabs()

    def _tab_menu(self, pos) -> None:
        i = self.tabbar.tabAt(pos)
        if i >= 0:
            self._switcher_menu(self.tabbar.tabData(i)).exec(self.tabbar.mapToGlobal(pos))

    def set_tab_layout(self, kind: str) -> None:
        self.cfg.tab_layout = kind
        self._place_panes()
        self._rebuild_tabs()
        self.save_config()

    def set_meters(self, mode: int) -> None:
        self.cfg.meters = mode
        self._refresh_meters()
        self.save_config()

    def _place_panes(self) -> None:
        """Order in the splitter: switcher and user list each on their side, the chat always wins the stretch."""
        c = self.cfg
        tabs = c.tab_layout == "tabs"
        pos = c.tab_pos
        for act, on in ((self.tabs_act, tabs), (self.tree_act, not tabs)):
            act.blockSignals(True)
            act.setChecked(on)
            act.blockSignals(False)
        sw = self.tabbar if tabs else self.tree
        other = self.tree if tabs else self.tabbar
        other.setVisible(False)
        other.setParent(self.body_lay.parentWidget())
        other.setVisible(False)
        self.body_lay.removeWidget(self.tabbar)
        self.body_lay.removeWidget(self.tree)
        self.tree.setMaximumHeight(16777215)
        order: list[QWidget] = []
        if pos == "left":
            order.append(sw)
        if c.ul_side == "left":
            order.append(self.right_panel)
        order.append(self.mid_panel)
        if c.ul_side != "left":
            order.append(self.right_panel)
        if pos == "right":
            order.append(sw)
        for i, w in enumerate(order):
            self.split.insertWidget(i, w)
            self.split.setStretchFactor(i, 1 if w is self.mid_panel else 0)
        if pos in ("top", "bottom"):
            sw.setParent(self.body_lay.parentWidget())
            if sw is self.tree:
                sw.setMaximumHeight(110)
            at = self.body_lay.indexOf(self.split)
            self.body_lay.insertWidget(at if pos == "top" else at + 1, sw)
        sw.setVisible(pos != "hidden")
        if tabs:
            self.tabbar.setShape({"left": QTabBar.Shape.RoundedWest, "right": QTabBar.Shape.RoundedEast,
                                  "bottom": QTabBar.Shape.RoundedSouth}.get(pos, QTabBar.Shape.RoundedNorth))
        small = "font-size: 8pt;" if c.tab_small else ""
        self.tree.setStyleSheet(f"QTreeWidget {{ {small} }}" if small else "")
        self.tabbar.setStyleSheet(f"QTabBar {{ {small} }}" if small else "")
        if c.tab_sort:
            for folder in self.folders.values():
                folder.sortChildren(0, Qt.SortOrder.AscendingOrder)

    def _refresh_meters(self) -> None:
        mode = self.cfg.meters
        self.lag_bar.setVisible(mode in (1, 3))
        self.queue_bar.setVisible(mode in (1, 3))
        self.meter_text.setVisible(mode in (2, 3))
        if not mode:
            return
        s = self.session
        measured = s.current_lag_ms() if s is not None and s.state == "connected" else None
        lag = measured or 0
        waiting = len(s._queue) if s is not None else 0
        full = s.LAG_FULL_MS if s is not None else 1000
        value = min(100, lag * 100 // max(1, full))
        if measured is not None:
            value = max(value, 4)          # a thin sliver: measured and small, not dead
        self.lag_bar.setValue(value)
        self.queue_bar.setValue(min(100, waiting * 10))
        self.meter_text.setText(f"{lag} ms  {waiting}q")
        tip = (f"Lag {lag} ms" if measured is not None else "Lag: not measured yet") +               f" · {waiting} line{'s' if waiting != 1 else ''} waiting to be sent"
        for w in (self.lag_bar, self.queue_bar, self.meter_text):
            w.setToolTip(tip)

    # --- detach -------------------------------------------------------------------------

    def detach(self, b: Buffer | None) -> None:
        from .detach import DetachedWindow
        if b is None or id(b) in self.detached:
            return
        w = DetachedWindow(self, b)
        if self.buf is b:
            others = [x for x in self._switcher_order() if x is not b and id(x) not in self.detached]
            self.detached[id(b)] = w
            if others:
                self.select_buffer(others[0])
            else:
                self.buf = None
                self.chat.show_buffer(None)
                self._refresh_all()
        else:
            self.detached[id(b)] = w
        self.chat.docs.pop(id(b), None)
        w.show()
        w.input.setFocus()

    def attach(self, b: Buffer) -> None:
        w = self.detached.pop(id(b), None)
        if w is None:
            return
        w.unhook()
        w.hide()
        w.deleteLater()
        self.chat.doc_for(b)
        self.select_buffer(b)

    def new_channel_tab(self) -> Buffer | None:
        """An empty tab, like XChat's: /join in it turns it into that channel."""
        s = self.session
        if s is None:
            s = self.new_server_tab()
        name = "<none>"
        n = 2
        while lower(name) in s.buffers:
            name = f"<none> ({n})"
            n += 1
        b = s.buffer(name)
        b.kind = CHANNEL
        b.placeholder = True
        self._file_item(b)      # it was filed before it became a channel tab
        s.add(b, INFO, "*", "Type /join #channel to use this tab.")
        self.select_buffer(b)
        return b

    def open_help(self):
        from .tools import HelpWindow
        w = self.tools.get("help")
        if w is None:
            w = self.tools["help"] = HelpWindow(self)
        w.show()
        w.raise_()
        return w

    def set_autostart(self, on: bool) -> None:
        """Start with Windows, for the installed BChat only: a run from source has nothing stable to point at."""
        from . import autostart
        autostart.sync(on, autostart.installed_exe())

    def check_autostart(self) -> str:
        """At every start: Windows' startup entry put back in line with the tick (it can vanish on its own)."""
        from . import autostart
        return autostart.sync(self.cfg.start_with_windows, autostart.installed_exe())

    def _show(self, b: Buffer) -> None:
        if self.replying is not None and self.replying[0] is not b:
            self.cancel_reply()                 # a reply belongs to the tab it was started in
        self.buf = b
        b.session.current = b
        b.unread, b.mentioned = 0, False
        if b.activity:
            b.activity = 0
            self._buffer_changed(b)
        self.chat.show_buffer(b)
        self._refresh_all()
        self._rebuild_tabs()
        self.input.setFocus()

    def reload_buffer(self, b: Buffer) -> None:
        self.chat.reload(b)

    def close_buffer(self, b: Buffer | None) -> None:
        if b is None:
            return
        s = b.session
        if b.kind == SERVER:
            others = len(s.buffers)
            if others and not getattr(self, "skip_quit_prompt", False):
                r = QMessageBox.question(self, "Close server tab", f"This server still has {others} channels or dialogs associated with it. Close them all?")
                if r != QMessageBox.StandardButton.Yes:
                    return
            s.disconnect_from_network()
            for other in list(s.buffers.values()):
                s.close_buffer(other)
            self._buffer_removed_server(s)
        else:
            s.close_buffer(b)

    def _buffer_removed_server(self, s: Session) -> None:
        b = s.server_buffer
        it = self.items.pop(id(b), None)
        if it is not None:
            self.tree.invisibleRootItem().removeChild(it)
        for key in [k for k in self.folders if k[0] == id(s)]:
            del self.folders[key]
        self.chat.forget(b)
        self.sessions.pop(s.net.name, None)
        s.deleteLater()
        if self.buf is b:
            self.buf = None
            first = self.tree.topLevelItem(0)
            if first is not None:
                self.tree.setCurrentItem(first)
            else:
                self.chat.show_buffer(None)
                self._refresh_all()

    def _decide_userlist(self) -> None:
        """XChat's mg_decide_userlist: only channel tabs have a nick list, so server and private tabs get the full width."""
        self.right_panel.setVisible(self.cfg.show_userlist and self.buf is not None and self.buf.kind == CHANNEL)
        self._sync_button_bars()

    def _refresh_all(self) -> None:
        b = self.buf
        self._decide_userlist()
        self.topic.edit.clearFocus()
        self.topic.set_topic(b.topic if b else "")
        self.topic.setEnabled(bool(b and b.kind == CHANNEL))
        self._topic_permission()
        self.userlist.set_buffer(b if b and b.kind == CHANNEL else None)
        self._refresh_count()
        self._refresh_title()

    def _refresh_count(self) -> None:
        b = self.buf
        if b is not None and b.kind == CHANNEL:
            ops, total = b.counts()
            self.count.setText(f"{ops} ops, {total} total")
        else:
            self.count.setText("")

    def _refresh_nick(self) -> None:
        s = self.session
        self.nick_label.setText(s.nick if s else (self.cfg.nick or "BChat"))
        # greyed while away, as in XChat
        self.nick_label.setStyleSheet(f"color: {self.cfg.theme.away};" if s and s.away and s.state == "connected" else "")
        name = icon_name(s.prefix_order, s.own_rank(self.buf)) if s and self.buf.kind == CHANNEL else None
        self.own_light.setPixmap(light_pixmap(name, self.devicePixelRatioF()) or QPixmap())

    def status_info(self) -> tuple[str, str]:
        """The strip's meaning: (state, plain tooltip text). The strip follows the tab being read."""
        s = self.session
        if s is None:
            return "off", "Not connected"
        where = s.server_name or (s.net.servers[s.server_index].host if s.net.servers and s.server_index >= 0 else s.net.name)
        if s.state in ("connecting", "registering"):
            return "connecting", f"Connecting · {where}"
        if s.state != "connected":
            return "off", f"Not connected · {s.net.name}" if s.net.servers else "Not connected"
        parts = ["Connected", where]
        if getattr(s, "_tls_now", False):
            parts.append("SSL")
        lag = s.current_lag_ms()
        if lag is not None:
            parts.append(f"lag {lag} ms")
        order = s.prefix_order
        rank = s.own_rank(self.buf) if self.buf.kind == CHANNEL else ""
        is_op = bool(rank) and "@" in order and order.index(rank) <= order.index("@")
        if is_op:
            parts.append(f"op in {self.buf.name}")
        state = "lag" if lag is not None and lag > s.LAG_WARN_MS else ("op" if is_op else "on")
        return state, " · ".join(parts)

    def _refresh_status(self) -> None:
        self._refresh_meters()
        self.show_typing()
        state, tip = self.status_info()
        t = self.cfg.theme
        colour = {"off": t.status_off, "connecting": t.status_connecting, "on": t.status_on,
                  "op": t.status_op, "lag": t.status_lag}[state]
        if colour != self._status_colour:
            self._status_colour = colour
            self.status_strip.setStyleSheet(f"background: {colour};")
        # server and channel names come from the network, and tooltips would otherwise read them as markup
        self.status_strip.setToolTip("<qt>" + html.escape(tip) + "</qt>")

    def _refresh_title(self) -> None:
        self._refresh_nick()
        self._refresh_status()
        b = self.buf
        if b is None:
            self.setWindowTitle("BChat")
            return
        s = b.session
        if not s.net.servers:
            self.setWindowTitle("BChat")
            return
        host = s.server_name or s.net.name
        if b.kind == CHANNEL:
            modes = b.mode_text()
            inside = " ".join(x for x in (modes, str(len(b.users)) if b.users else "") if x)
            tail = f" ({inside})" if inside else ""
            self.setWindowTitle(f"BChat: {s.nick} @ {host} / {b.name}{tail}")
        elif b.kind == QUERY:
            self.setWindowTitle(f"BChat: {s.nick} @ {host} / {b.name}")
        else:
            self.setWindowTitle(f"BChat: {s.nick} @ {host}" if s.state != "disconnected" else f"BChat: {host} (not connected)")

    # --- input ------------------------------------------------------------------

    def _entered(self) -> None:
        text = self.input.text()
        replying = self.replying
        self._typing_to = None                     # the message itself says we stopped typing
        self.input.clear()
        if not text:
            return
        if replying is not None and replying[0] is self.buf and not text.startswith("/") and self.buf is not None:
            self.cancel_reply()
            self.input.remember(text)
            self.buf.session.say_reply(self.buf.name, self.expand_input(text), replying[1])
            return
        self.input.remember(text)
        from .reports import command_step
        command_step(text)                    # the command's name only, for a problem report's last steps
        if self.buf is None:
            word = text.split()
            if word[0].lower() in ("/server", "/newserver"):
                commands.new_server(self, word[1:])
            else:
                self.open_network_list()
            return
        commands.run(self, self.buf.session, self.buf, self.expand_input(text))

    def expand_input(self, text: str, buf: Buffer | None = None) -> str:
        """Input box settings: %B-style codes, %nnn values and completing "nic: hi" without Tab."""
        c = self.cfg
        if c.percent_ascii:
            text = re.sub(r"%(\d{3})", lambda m: chr(int(m.group(1))) if 0 < int(m.group(1)) < 256 else m.group(0), text)
        if c.percent_codes:
            codes = {"B": "\x02", "C": "\x03", "U": "\x1f", "O": "\x0f", "R": "\x16", "%": "%"}
            text = re.sub(r"%([BCUOR%])", lambda m: codes[m.group(1)], text)
        b = buf or self.buf
        if c.auto_complete and c.nick_suffix and not text.startswith("/") and b is not None:
            head, sep, rest = text.partition(c.nick_suffix)
            if sep and head and " " not in head and (rest == "" or rest.startswith(" ")):
                found = [u.nick for u in b.users.values() if lower(u.nick).startswith(lower(head))]
                if len(found) == 1:
                    text = found[0] + sep + rest
        return text

    def _topic_entered(self, text: str) -> None:
        b = self.buf
        if b is not None and b.kind == CHANNEL:
            b.session.send("TOPIC", b.name, text)
            self.input.setFocus()

    def _emoji_for_input(self) -> None:
        p = emoji_popup(self.cfg.theme, self)
        p.picked.connect(lambda e: (self.input.insert(e), self.input.setFocus()))
        p.show_below(self.emoji_btn)
        self._emoji_popup = p

    def _topic_permission(self) -> None:
        """+t channels: only halfop and up may set the topic (Unreal and InspIRCd allow % too)."""
        b = self.buf
        if b is None or b.kind != CHANNEL:
            self.topic.set_allowed(False, "")       # server tab or private chat: no topic to change
            return
        s = b.session
        order = s.prefix_order or "@+"
        rank = s.own_rank(b)
        top = order.index("%") if "%" in order else (order.index("@") if "@" in order else -1)
        ok = "t" not in b.modes or (rank != "" and order.index(rank) <= top)
        self.topic.set_allowed(ok, "Only channel operators can change the topic here (+t)")

    # --- nick list actions ---------------------------------------------------------

    def _nick_double(self, index) -> None:
        u: User = index.data(Qt.ItemDataRole.UserRole)
        s = self.session
        pattern = self.cfg.ul_double.strip()
        word = pattern.lstrip("/").split(" ")
        if lower(" ".join(word[:2])) == "quote whois" or lower(word[0]) == "whois":
            s.whois(u.nick)      # keeps the answer in this tab
        elif pattern:
            commands.run(self, s, self.buf, "/" + pattern.lstrip("/").replace("%s", u.nick))

    def _nick_menu(self, pos) -> None:
        b = self.buf
        if b is None:
            return
        idx = self.userlist.indexAt(pos)
        if idx.isValid() and not self.userlist.selectionModel().isSelected(idx):
            self.userlist.setCurrentIndex(idx)
        users = self.userlist.selected_users()
        if users:
            self.build_nick_menu(b, users).exec(self.userlist.viewport().mapToGlobal(pos))

    def build_nick_menu(self, b: Buffer, users: list[User]) -> QMenu:
        s = b.session
        menu = QMenu(self)
        nicks = [u.nick for u in users]
        one = users[0]
        if len(users) == 1:
            head = menu.addMenu(one.nick)
            self._info_panel(head, s, b, one)
        else:
            head = add_menu_title(menu, f"{len(users)} nicks selected")
        menu.addSeparator()
        menu.addAction(icon("dialog"), "Open Dialog Window", lambda: [self.select_buffer(s.buffer(n)) for n in nicks])
        menu.addAction(icon("save"), "Send a File", lambda: self.send_file_dialog(s, nicks))
        menu.addAction(icon("info"), "User Info (WhoIs)", lambda: [s.whois(n) for n in nicks])
        menu.addAction(icon("add"), "Add to Friends List", lambda: self.ask_friend(nicks[0] if len(nicks) == 1 else " ".join(nicks)))
        if len(users) == 1:                             # 0.3.0: mIRC's Address Book and Nick Colors, for one person
            menu.addAction(icon("book"), "Address Book...", lambda: self.open_address_book(one.nick, one.realname))
            from . import people
            now = people.colour_name(self.cfg, s.net.name, one.nick, one.host)
            menu.addAction(people.swatch(self.cfg, now) if now else icon("edit"), "Nick Colour...",
                           lambda: self.quick_nick_colour(s, one.nick))
            from .dcc import is_trusted
            trust = menu.addAction("Trust for Files and Chats")     # 0.6.0: Preferences > File transfers > Trusted people
            trust.setCheckable(True)
            prefix = f"{one.nick}!{one.host}" if "@" in one.host else ""
            trust.setChecked(bool(prefix) and is_trusted(self.cfg, s.net.name, prefix))
            trust.setEnabled(bool(prefix))
            if not prefix:
                trust.setToolTip("Their address isn't known yet")
            trust.toggled.connect(lambda on: self.trust_user(s, one, on))
        ign = menu.addAction("Ignore")                 # mIRC's Control > Ignore / Unignore as one tick
        ign.setCheckable(True)
        ign.setChecked(all(self._is_ignored(s, u) for u in users))
        ign.toggled.connect(lambda on: self.ignore_users(s, users, on))
        menu.addSeparator()
        ops = menu.addMenu("Operator Actions")
        ops.addAction("Give Ops", lambda: s.set_mode_for(b, "+o", nicks))
        ops.addAction("Take Ops", lambda: s.set_mode_for(b, "-o", nicks))
        ops.addSeparator()
        ops.addAction("Give Voice", lambda: s.set_mode_for(b, "+v", nicks))
        ops.addAction("Take Voice", lambda: s.set_mode_for(b, "-v", nicks))
        if len(users) == 1 and b.kind == CHANNEL:      # 0.4.0: AOP / VOP through ChanServ, one person at a time
            from .chanserv import can_manage
            ops.addSeparator()
            acc = ops.addAction("ChanServ Access...", lambda: self.open_chanserv_access(b, one))
            if not can_manage(s, b) or s.state != "connected":
                acc.setEnabled(False)
                acc.setText(f"ChanServ Access... (you need @ in {b.name})".replace("&", "&&"))
            ops.addAction("Auto-Op / Auto-Voice...", lambda: self.open_control(one, s, b))
        ops.addSeparator()
        ops.addAction("Kick", lambda: self._kick(b, nicks))
        ops.addAction("Kick with Reason...", lambda: self.kick_with_reason(b, nicks))
        kb = ops.addMenu("Kick/Ban")
        kb.addAction("Kick", lambda: self._kick(b, nicks))
        kb.addAction("Ban", lambda: [s.ban(b, n, 0) for n in nicks])
        kb.addSeparator()
        masks = ("*!*@*.host", "*!*@domain", "*!*user@*.host", "*!*user@domain")
        for i, mask in enumerate(masks):
            kb.addAction(f"Ban {mask}", lambda i=i: [s.ban(b, n, i) for n in nicks])
        kb.addSeparator()
        for i, mask in enumerate(masks):
            kb.addAction(f"KickBan {mask}", lambda i=i: [s.ban(b, n, i, kick=True) for n in nicks])
        ctcp = menu.addMenu("CTCP")                     # mIRC's CTCP menu; the answers show in the current tab
        ctcp.addAction("Ping", lambda: [self._run_with(f"ping {n}") for n in nicks])
        ctcp.addAction("Time", lambda: [self._run_with(f"ctcp {n} TIME") for n in nicks])
        ctcp.addAction("Version", lambda: [self._run_with(f"ctcp {n} VERSION") for n in nicks])
        if len(users) == 1 and b.kind == CHANNEL:      # one nick only: never ten slaps at once
            menu.addSeparator()
            menu.addAction("Slap!", lambda: self.slap(b, one.nick))
        self._add_popup_items(menu, nicks)
        return menu

    def open_chanserv_access(self, b: Buffer, u: User) -> None:
        from .chanserv import ChanServAccess
        self.chanserv_window = ChanServAccess(self, b, u)
        self.chanserv_window.show()

    @staticmethod
    def _prefix(u: User) -> str:
        return f"{u.nick}!{u.host}" if "@" in u.host else f"{u.nick}!*@*"

    def _is_ignored(self, s: Session, u: User) -> bool:
        return s.ignored(self._prefix(u))

    def ignore_users(self, s: Session, users: list[User], on: bool) -> None:
        """Ignore tick: on = /ignore *!*@host ALL (nick!*@* while the host is unknown); off = /unignore every mask that hides them."""
        for u in users:
            if on:
                host = u.host.partition("@")[2]
                self._run_with(f"ignore {'*!*@' + host if host else u.nick + '!*@*'} ALL")
            else:
                pre = lower(self._prefix(u))
                for mask in [m for m in s.cfg.ignores if fnmatch.fnmatchcase(pre, lower(m)) and "U" not in s.cfg.ignore_kinds.get(m, "")]:
                    self._run_with(f"unignore {mask}")
        config.save(self.cfg, self.cfg_dir)

    def kick_with_reason(self, b: Buffer, nicks: list[str]) -> None:
        who = nicks[0] if len(nicks) == 1 else f"{len(nicks)} nicks"
        reason, ok = QInputDialog.getText(self, "Kick", f"Enter reason to kick {who}:")   # XChat's own question
        if ok:
            for n in nicks:
                b.session.send("KICK", b.name, n, reason.strip() or self.cfg.part_reason)

    def slap(self, b: Buffer, nick: str) -> None:
        from . import slaps
        line = slaps.pick(slaps.lines_of(rows_for(self.cfg, "slaps")), nick)
        if line:
            b.session.action(b.name, line)

    def _info_panel(self, head: QMenu, s: Session, b: Buffer, u: User) -> None:
        """XChat's nick submenu: click a row to copy it. Text comes from the network, so it is always shown as plain text."""
        box = QWidget(head)
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 6, 12, 6)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        mono = QFont("Consolas", 9)
        mono.setBold(True)
        labels: dict[str, _CopyLabel] = {}
        for i, key in enumerate(("Real Name:", "User:", "Country:", "Server:", "Last Msg:", "Away Msg:")):
            kl = QLabel(key, box)
            kl.setFont(mono)
            kl.setTextFormat(Qt.TextFormat.PlainText)
            vl = _CopyLabel(box)
            grid.addWidget(kl, i, 0)
            grid.addWidget(vl, i, 1)
            labels[key] = vl
            labels[key + "key"] = kl

        def fill() -> None:
            mins = int((time.time() - u.last_msg) // 60) if u.last_msg else None
            values = {"Real Name:": strip_format(u.realname), "User:": u.host, "Country:": u.country or (country_of(u.host) if u.host else ""),
                      "Server:": u.server, "Last Msg:": f"{mins} minutes ago" if mins is not None else ""}
            for key, v in values.items():
                labels[key].set_value(v)
            show_away = u.away
            labels["Away Msg:"].set_value(strip_format(u.away_reason))
            labels["Away Msg:"].setVisible(show_away)
            labels["Away Msg:key"].setVisible(show_away)

        fill()
        act = QWidgetAction(head)
        act.setDefaultWidget(box)
        head.addAction(act)

        def fresh(nick: str) -> None:
            if lower(nick) == lower(u.nick):
                fill()
                box.adjustSize()
                head.adjustSize()

        def shown() -> None:
            # only ask the server when something is really missing, like XChat
            if not (u.host and u.realname and u.server) or (u.away and not u.away_reason):
                s.silent_whois(u.nick)
        head.aboutToShow.connect(shown)
        s.user_info.connect(fresh)
        head.destroyed.connect(lambda: self._safe_disconnect(s, fresh))

    @staticmethod
    def _safe_disconnect(s: Session, slot) -> None:
        try:
            s.user_info.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def _kick(self, b: Buffer, nicks: list[str]) -> None:
        for n in nicks:
            b.session.send("KICK", b.name, n, self.cfg.part_reason)

    def _tree_menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        if it is not None and it.data(0, Qt.ItemDataRole.UserRole) is not None:
            self._switcher_menu(it.data(0, Qt.ItemDataRole.UserRole)).exec(self.tree.viewport().mapToGlobal(pos))

    def _switcher_menu(self, b: Buffer) -> QMenu:
        s = b.session
        menu = QMenu(self)
        add_menu_title(menu, b.name)
        menu.addSeparator()
        if b.kind == CHANNEL:
            menu.addAction("Leave Channel", lambda: s.send("PART", b.name, self.cfg.part_reason))
        if b.kind != SERVER:
            menu.addAction("Rejoin Channel" if b.kind == CHANNEL else "WhoIs",
                           (lambda: s.send("JOIN", b.name)) if b.kind == CHANNEL else (lambda: s.whois(b.name)))
        else:
            menu.addAction("Join Channel...", self._join_dialog)
            menu.addAction("Reconnect", s.reconnect)
            menu.addAction("Disconnect", s.disconnect_from_network)
            menu.addAction("Server Links", lambda: s.send("LINKS"))
            menu.addSeparator()
            if s.net in self.cfg.networks:   # AdiIRC: Edit Network once it is saved, Add Network before
                menu.addAction("Edit Network...", lambda: self.edit_network(s.net))
            elif s.net.servers:
                menu.addAction(icon("connect"), "Add Network", lambda: self.add_network_from(s))
        if b.kind == CHANNEL and s.net in self.cfg.networks:
            from . import favourites
            fav = favourites.find(favourites.entries(self.cfg), s.net.name, b.name)
            auto = menu.addAction("Join on Connect")
            auto.setCheckable(True)
            auto.setChecked(fav is not None and fav.join)
            auto.toggled.connect(lambda on: self.join_on_connect(b, on))
        menu.addAction(icon("favourite"), "Favourite Channels...", self.open_favourites)
        if b.kind == CHANNEL:
            menu.addAction(icon("preferences"), "Channel Central...", lambda: self.open_channel_central(b))
        menu.addSeparator()
        if b.kind in (CHANNEL, QUERY):
            self._tab_settings_menu(menu, b)       # 0.6.0: this tab's own settings, Log to Disk among them
        else:
            log = menu.addAction("Log to Disk")
            log.setCheckable(True)
            log.setChecked(self._log_key(b) in self.cfg.log_tabs)
            log.toggled.connect(lambda on: self._log_to_disk(b, on))
        if self.logs_of(b):          # only once there is something to read
            menu.addAction(icon("find"), "View Log", lambda: self.open_logs(b))
        menu.addSeparator()
        if id(b) in self.detached:
            menu.addAction("Attach", lambda: self.attach(b))
        else:
            menu.addAction(icon("dialog"), "Detach", lambda: self.detach(b))
        menu.addAction(icon("close-light"), "Close", lambda: self.close_buffer(b))
        return menu

    def _tab_settings_menu(self, menu: QMenu, b: Buffer) -> QMenu:
        """Settings for #chan: ticks that only change this tab. One that differs from Preferences shows bold."""
        from . import tabopts
        sub = menu.addMenu(icon("justify"), f"Settings for {b.name}")
        bold = QFont()
        bold.setBold(True)

        def tick(label: str, name: str) -> None:
            a = sub.addAction(label)
            a.setCheckable(True)
            a.setChecked(bool(tabopts.get(self.cfg, b, name)))
            if tabopts.has_own(self.cfg, b, name):
                a.setFont(bold)
            a.toggled.connect(lambda on, n=name: self.set_tab_opt(b, n, on))
        tick("Timestamps", "timestamps")
        tick("Colored nick names", "color_nicks")
        jp = sub.addMenu("Join and part lines")
        if tabopts.has_own(self.cfg, b, "joins"):
            jp.menuAction().setFont(bold)
        group = QActionGroup(jp)
        now = tabopts.get(self.cfg, b, "joins")
        base = tabopts.default(self.cfg, "joins", b)
        for value, label in (("show", "Show"), ("short", "Short"), ("hide", "Hide")):
            a = jp.addAction(label + (" (default)" if value == base else ""))
            a.setCheckable(True)
            a.setChecked(value == now)
            group.addAction(a)
            a.triggered.connect(lambda _=False, v=value: self.set_tab_opt(b, "joins", v))
        sub.addSeparator()
        tick("Beep on new message", "beep")
        tick("Flash the taskbar", "flash")
        tick("Pop-up cards", "popups")
        log = sub.addAction("Log to Disk")
        log.setCheckable(True)
        log.setChecked(self._log_key(b) in self.cfg.log_tabs)
        log.toggled.connect(lambda on: self._log_to_disk(b, on))
        sub.addSeparator()
        reset = sub.addAction(icon("revert"), "Use the defaults again", lambda: self.clear_tab_opts(b))
        reset.setEnabled(tabopts.key(b) in self.cfg.tab_opts)
        return sub

    def set_tab_opt(self, b: Buffer, name: str, value) -> None:
        from . import tabopts
        tabopts.set_(self.cfg, b, name, value)
        self.save_config()
        if name in ("timestamps", "color_nicks"):
            self.reload_buffer(b)

    def clear_tab_opts(self, b: Buffer) -> None:
        from . import tabopts
        tabopts.clear(self.cfg, b)
        self.save_config()
        self.reload_buffer(b)

    # --- menu actions --------------------------------------------------------------

    def _change_page(self, delta: int = 0, number: int = 0) -> None:
        """Ctrl+PageUp/Down and Alt+1-9 move through the tree in order, like XChat's default keys."""
        order = self._buffer_rows()
        if not order:
            return
        if number:
            if number <= len(order):
                self.tree.setCurrentItem(order[number - 1])
            return
        cur = self.tree.currentItem()
        at = order.index(cur) if cur in order else 0
        self.tree.setCurrentItem(order[(at + delta) % len(order)])

    # --- chat clicks ---------------------------------------------------------------

    def open_url(self, url: str, who: str = "", where: str = "") -> None:
        """Ordinary links open straight away. Risky ones (programs, look-alike names, bare addresses, name@ tricks)
        get a second look first, with Cancel as the default."""
        link = QUrl(url if "://" in url else "http://" + url)
        if link.scheme().lower() not in ("http", "https", "ftp"):
            return
        reason = link_risk(url)
        if not reason:
            QDesktopServices.openUrl(link)
            return
        d = LinkDialog(self, url, reason, who, where)
        self.link_dialog = d
        d.finished.connect(lambda _r: QDesktopServices.openUrl(link) if d.choice == "open" else None)
        d.open()

    def accept_transfer(self, t) -> None:
        """Every Accept goes through here (File Transfers, /dcc get): a program gets a second look first."""
        if t.kind != "recv" or not is_program(t.name):
            self.dcc.accept(t)
            return
        net = getattr(getattr(t.session, "net", None), "name", "")
        d = ProgramDialog(self, t.name, t.size, t.nick, net)
        self.program_dialog = d
        d.finished.connect(lambda _r: self.dcc.accept(t) if d.choice == "accept" else None)
        d.open()

    def _cert_question(self, s, info: dict) -> None:
        """Asked without stopping the rest of BChat: other networks keep chatting while this window is up."""
        d = CertDialog(self, info)
        self.cert_dialog = d
        d.finished.connect(lambda _r: s.answer_certificate(info.get("fingerprint", ""), d.choice or "no"))
        d.open()

    def _join_clicked(self, name: str) -> None:
        s = self.session
        if s is None or not s.is_channel(name):
            return
        existing = s.buffers.get(lower(name))
        if existing is not None:
            self.select_buffer(existing)
        else:
            s.focus_next = lower(name)
        s.send("JOIN", name)

    # --- irc:// links ------------------------------------------------------------------

    def _network_for_host(self, host: str):
        """(network, session) already known for this server name: open sessions first, then the Network List."""
        host = host.lower()
        for s in self.sessions.values():
            names = {sv.host.lower() for sv in s.net.servers} | {s.server_name.lower()}
            if host in names:
                return s.net, s
        for n in self.cfg.networks:
            if host in {sv.host.lower() for sv in n.servers}:
                return n, self.sessions.get(n.name)
        return None, None

    def open_irc_link(self, url: str):
        """An irc:// or ircs:// link (from chat or the browser): always asks first, never joins on its own."""
        from .irclink import IrcLinkDialog, parse_irc_url
        link = parse_irc_url(url)
        if link is None:
            return None
        net, s = self._network_for_host(link.host)
        chan = link.channels[0] if link.channels else ""
        if s is not None and s.state == "connected" and chan:
            b = s.buffers.get(lower(chan))
            if b is not None and b.joined:          # already there: just show it
                self.select_buffer(b)
                self.bring_to_front()
                return None
        nick = (net.nick if net is not None and not net.use_global and net.nick else "") or self.cfg.nick
        if net is None:
            name, line = link.host, f"New network: opens its own server tab, connects as {nick}, then joins." if chan else                 f"New network: opens its own server tab and connects as {nick}."
        elif s is not None and s.state == "connected":
            name, line = net.name, f"You're connected here: {chan} opens in a new tab." if chan else "You're already connected here."
        else:
            name, line = net.name, "In your Network List: connects, then joins." if chan else "In your Network List: connects."
        d = IrcLinkDialog(self, link, name, line)
        self.irc_link_dialog = d
        d.finished.connect(lambda _r: self._irc_link_go(link, net) if d.choice == "join" else None)
        self.bring_to_front()
        d.open()
        return d

    def _irc_link_go(self, link, net) -> None:
        chan = link.channels[0] if link.channels else ""
        if net is None:                              # new network: into the Network List, its own server tab
            name = link.host
            net = NetworkConfig(name, [Server(link.host, link.port, link.tls)])
            self.cfg.networks.append(net)
            config.save(self.cfg, self.cfg_dir)
        s = self.session_for(net)
        if s.state == "connected":
            if chan:
                s.focus_next = lower(chan)
                s.send("JOIN", chan, *([link.key] if link.key else []))
            else:
                self.select_buffer(s.server_buffer)
            return
        if chan:
            s.join_once.append((chan, link.key))
        self.connect_network(net)

    def bring_to_front(self) -> None:
        """For a link from the browser: BChat comes forward, out of the tray or the taskbar if need be."""
        if self.isMinimized() or not self.isVisible():
            self._restore_from_tray()
        else:
            self.raise_()
            self.activateWindow()

    def url_menu(self, url: str) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Open Link in Browser", lambda: self.open_url(url))
        menu.addAction("Copy Link", lambda: QApplication.clipboard().setText(url))
        handlers = rows_for(self.cfg, "url_handlers")
        if handlers:
            menu.addSeparator()
        for name, cmd in handlers:
            menu.addAction(name, lambda c=cmd: self._run_with(c.replace("%s", url)))
        return menu

    def _run_with(self, cmd: str) -> None:
        s = self.session
        if s is not None:
            self.run_command(s, cmd if cmd.startswith(("!", "/")) else "/" + cmd)

    def nick_command(self, cmd: str, nicks: list[str]) -> None:
        """XChat's nick_command_parse: %a is every selected nick at once, %s runs once per nick."""
        b = self.buf
        if b is None:
            return
        chan = b.name if b.kind == CHANNEL else ""
        cmd = cmd.replace("%c", chan).replace("%n", b.session.nick).replace("%e", b.session.net.name)
        if "%a" in cmd:
            self._run_with(cmd.replace("%a", " ".join(nicks)))
        elif "%s" in cmd:
            for n in nicks:
                self._run_with(cmd.replace("%s", n))
        else:
            self._run_with(cmd)

    def _add_popup_items(self, menu: QMenu, nicks: list[str]) -> None:
        stack = [menu]
        for name, cmd in rows_for(self.cfg, "ul_popup"):
            word = name.upper()
            if word == "SEP":
                stack[-1].addSeparator()
            elif word == "SUB":
                stack.append(stack[-1].addMenu(cmd))
            elif word == "ENDSUB":
                if len(stack) > 1:
                    stack.pop()
            else:
                stack[-1].addAction(name, lambda c=cmd: self.nick_command(c, nicks))

    # --- buttons under the list, on the topic row -------------------------------------

    def _toggle_ul_buttons(self, on: bool) -> None:
        self.cfg.show_ul_buttons = on
        self._sync_button_bars()
        self.save_config()

    def _toggle_mode_buttons(self, on: bool) -> None:
        self.cfg.show_mode_buttons = on
        self._sync_button_bars()
        self.save_config()

    def _rebuild_buttons(self) -> None:
        for lay in (self.ul_button_grid, self.dialog_lay):
            while lay.count():
                lay.takeAt(0).widget().deleteLater()
        for i, (name, cmd) in enumerate(rows_for(self.cfg, "ul_buttons")):
            b = QPushButton(name, self.ul_button_box, objectName="ulbtn")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, c=cmd: self.nick_command(c, [u.nick for u in self.userlist.selected_users()]))
            self.ul_button_grid.addWidget(b, i // 2, i % 2)
        for name, cmd in rows_for(self.cfg, "dlg_buttons"):
            b = QPushButton(name, self.dialog_bar, objectName="ulbtn")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, c=cmd: self.nick_command(c, [self.buf.name]))
            self.dialog_lay.addWidget(b)

    def _sync_button_bars(self) -> None:
        b = self.buf
        chan = b is not None and b.kind == CHANNEL
        self.ul_button_box.setVisible(self.cfg.show_ul_buttons)
        self.mode_bar.setVisible(self.cfg.show_mode_buttons and chan)
        self.dialog_bar.setVisible(b is not None and b.kind == QUERY)
        if chan:
            for letter, btn in self.mode_buttons.items():
                btn.setChecked(letter in b.modes and letter != "b")

    def _mode_clicked(self, letter: str) -> None:
        b = self.buf
        self._sync_button_bars()         # the server decides: the button shows what comes back
        if b is None or b.kind != CHANNEL:
            return
        if letter == "b":
            self.open_ban_list()
            return
        on = letter in b.modes
        if not on and letter in "lk":
            ask = "Enter new channel limit:" if letter == "l" else "Enter new channel key:"
            value, ok = QInputDialog.getText(self, b.name, ask)
            if ok and value.strip():
                b.session.send("MODE", b.name, "+" + letter, value.strip())
            return
        if on and letter == "k":
            b.session.send("MODE", b.name, "-k", b.mode_args.get("k", "*"))
            return
        b.session.send("MODE", b.name, ("-" if on else "+") + letter)

    # --- Settings > Advanced -----------------------------------------------------------

    def named_actions(self) -> dict:
        out = {}
        for menu in self.menubar_.findChildren(QMenu):
            for a in menu.actions():
                if a.isSeparator() or a.menu() is not None or not a.text():
                    continue
                out[f"{menu.title().replace('&', '')}: {a.text().replace('&', '').rstrip('.')}"] = a
        return out

    def open_editor(self, key: str):
        from .editors import EditListDialog, KeysDialog, TextEventsDialog
        d = KeysDialog(self) if key == "keys" else TextEventsDialog(self) if key == "events" else EditListDialog(self, key)
        d.show()
        return d

    def lists_changed(self, save: bool = True) -> None:
        """After any editor's Save, and at start."""
        self._rebuild_buttons()
        self._sync_button_bars()
        for name, act in self.named_actions().items():
            act.setShortcut(QKeySequence(self.cfg.keys.get(name, self.default_keys.get(name, ""))))
        for sc in self._key_shortcuts:
            sc.setParent(None)
            sc.deleteLater()
        self._key_shortcuts = []
        for key, cmd in self.cfg.key_commands:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda c=cmd: self._run_with(c))
            self._key_shortcuts.append(sc)
        if save:
            self.save_config()

    def _chat_menu(self, pos, chat=None, buf=None) -> QMenu:
        """Right click in the chat: on a link, a nick or a channel it offers those, as in XChat."""
        chat = chat or self.chat
        b = buf or self.buf
        s = b.session if b is not None else None
        href = chat.anchorAt(pos)
        word = chat.word_at(pos)
        user = b.users.get(lower(word)) if b is not None and word else None
        msgid, _quoted = chat.line_at(pos)
        can_reply = bool(msgid) and b is not None and s is not None and b.kind in (CHANNEL, QUERY) and s.client_tag_ok("+draft/reply")
        if user is not None and not href:
            menu = self.build_nick_menu(b, [user])
            if can_reply:
                first = menu.actions()[0] if menu.actions() else None
                act = QAction(icon("send"), "Reply", menu)
                act.triggered.connect(lambda: self.start_reply(b, msgid))
                menu.insertAction(first, act)
                menu.insertSeparator(first)
            return menu
        menu = QMenu(self)
        if can_reply and not href:
            menu.addAction(icon("send"), "Reply", lambda: self.start_reply(b, msgid))
            menu.addSeparator()
        if href:
            for act in self.url_menu(href).actions():
                menu.addAction(act)
            menu.addSeparator()
        elif s is not None and word and s.is_channel(word):
            menu.addAction(f"Join {word}", lambda: self._join_clicked(word))
            menu.addSeparator()
        if b is not None and s is not None and b.kind in (CHANNEL, QUERY) and not href:
            self._share_menu(menu, s, b)
            menu.addSeparator()
        copy = menu.addAction(icon("copy"), "Copy Selection", self.chat.copy)
        copy.setEnabled(self.chat.textCursor().hasSelection())
        menu.addAction("Select All", self.chat.selectAll)
        menu.addSeparator()
        menu.addAction(icon("clear"), "Clear Text", self._clear_current)
        menu.addAction(icon("find"), "Search Text...", self._search)
        return menu

    def _share_menu(self, menu: QMenu, s, b) -> QMenu:
        """AdiIRC's System Info and Now Playing, under Share. Announce only for channels, and only once /np is on."""
        from . import commands
        from .nowplaying import announces_in
        share = menu.addMenu("Share")
        share.setToolTipsVisible(True)
        share.addAction("System Info", lambda: commands.run(self, s, b, "/sysinfo"))
        share.addAction("Now Playing", lambda: self.now_playing(s, b))
        if b.kind == CHANNEL:
            share.addSeparator()
            ann = share.addAction("Announce Songs Here")
            ann.setCheckable(True)
            mine = self.cfg.np_announce and announces_in(self.cfg.np_announce_in, s.net.name, b.name, this_network_only=True)
            ann.setChecked(mine)
            ann.setEnabled(self.cfg.np_enabled)
            if not self.cfg.np_enabled:
                ann.setToolTip("Turn on Now Playing in Preferences > Chatting > Now Playing first")
            elif not mine and self.cfg.np_announce and announces_in(self.cfg.np_announce_in, s.net.name, b.name):
                ann.setToolTip(f"Now announced in {b.name} on every network. Tick to announce only on {s.net.name}")
            ann.toggled.connect(lambda on: self.announce_here(b, on))
        return share

    def buffer_tip(self, b: Buffer) -> str:
        """Tab/tree tooltip. A network row also says which bouncer it goes through and how long it's been online."""
        name = html.escape(b.name)
        if b.kind != SERVER:
            return name
        s = b.session
        rows = [f"<b>{name}</b>"]
        if s.bouncer and s.state == "connected":
            rows.append(f"Through {html.escape(s.bouncer_text())}")
        online = s.online_text()
        if online:
            rows.append(f"Online {html.escape(online.split(' (')[0])}")
        if s.bouncer and s.state == "connected":
            rows.append(f"<span style='color:{self.cfg.theme.muted}'>You stay online when BChat closes</span>")
        return "<qt>" + "<br>".join(rows) + "</qt>"

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.ToolTip and obj is getattr(getattr(self, "tree", None), "viewport", lambda: None)():
            it = self.tree.itemAt(ev.pos())
            b = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
            if b is not None:
                it.setToolTip(0, self.buffer_tip(b))       # the online time moves on: fill it in now
            return False
        if obj is getattr(self, "input", None) and ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape                 and getattr(self, "replying", None) is not None:
            self.cancel_reply()
            return True
        if obj is getattr(self, "nick_label", None) and ev.type() == QEvent.Type.MouseButtonPress:
            s = self.session
            if s is not None and s.state == "connected":
                nick, ok = QInputDialog.getText(self, "Change nick", "Enter new nickname:", text=s.nick)
                if ok and nick.strip():
                    s.send("NICK", nick.strip().split()[0])
            return True
        return super().eventFilter(obj, ev)

    # --- alerts: XChat's Alerts page, and its Sound page ------------------------------

    MORE_CARDS = {"kicked": "kick", "disconnect": "disconnect", "friend": "friend", "invite": "invite", "dcc": "dcc",
                  "notice": "notice"}

    def _on_notify(self, b: Buffer, kind: str) -> None:
        if kind in ("friend", "friend_off"):
            name = getattr(b.session, "last_friend", "")
            opts = self.cfg.friend_opts.get(name.lower(), {})
            played = False
            if opts.get("sound"):                          # per friend (0.5.0): their file, the Sound page's, or the chime
                played = (self._play_sound("friend", path=opts.get("sound_file", "")) if opts.get("sound_file")
                          else self._play_sound("friend") or self.play_soft_chime(wanted=True))
            if kind == "friend":
                self._more_card(b, kind, played or opts.get("sound") is False)   # sound ticked off for them: no chime
            return
        rule = getattr(b.session, "last_hilite", None) if kind == "hilight" else None
        sound = (rule or {}).get("sound", "") or ""
        played = sound == "none"                           # a silent highlight rule: no chime either
        if sound and sound != "none":
            played = self._play_sound(kind, path=sound)    # the rule's own sound
        elif not sound:
            played = self._play_sound(kind)
        if kind in self.MORE_CARDS:
            self._more_card(b, kind, played)
            if kind != "dcc":
                return
        which = {"chan": 0, "priv": 1, "hilight": 2, "dcc": 1}.get(kind)
        if which is None or self.isActiveWindow():
            return
        c = self.cfg
        flash = rule.get("flash") if rule and rule.get("flash") is not None else c.alert_flash[which]
        tip = rule.get("tip") if rule and rule.get("tip") is not None else c.alert_popup[which]
        tip = tip and kind != "dcc"                        # a file offer already has its own card
        beep = c.alert_beep[which]
        if b.kind in (CHANNEL, QUERY) and b.session is not None:
            from . import tabopts                          # 0.6.0: this tab's own beep / flash / pop-up ticks win
            if tabopts.has_own(c, b, "flash"):
                flash = tabopts.get(c, b, "flash")
            if tabopts.has_own(c, b, "beep"):
                beep = tabopts.get(c, b, "beep")
            if tabopts.has_own(c, b, "popups") and kind != "dcc":
                tip = tabopts.get(c, b, "popups")
        if flash:
            QApplication.alert(self)
        if beep:
            QApplication.beep()
        if tip and b.lines and self._pop_up(b, kind) == "new" and not played:
            self.play_soft_chime()
        if self.tray is not None:
            if c.alert_tray[which] and not self._blink_timer.isActive():
                self._blink_timer.start()

    def _more_card(self, b: Buffer, kind: str, played: bool) -> None:
        """0.5.0: pop-up cards for being kicked, a lost connection, a friend coming online, an invite, a file offer
        and (off by default) a notice. Same cards and flood rules as messages; only while you're not looking."""
        s = b.session
        if self.isActiveWindow() or s is None or not self.cfg.popup_more.get(self.MORE_CARDS[kind], False):
            return
        net = s.net.name
        last = b.lines[-1] if b.lines else None
        text = last.text if last is not None else ""
        if kind == "kicked":
            title, where = "You were kicked", f"{b.name} \u00b7 {net}"
        elif kind == "disconnect":
            if not s.want_connected:
                return                                     # you quit or disconnected yourself
            title, where, text = "Disconnected", net, f"BChat will reconnect in {self.cfg.reconnect_delay} s."
        elif kind == "friend":
            name = getattr(s, "last_friend", "")
            opts = self.cfg.friend_opts.get(name.lower(), {})
            if not name or not opts.get("popup", True):
                return
            title, where, text = f"{name} is online", net, "Your friend just came online"
        elif kind == "invite":
            chan, nick = getattr(s, "last_invite", ("", ""))
            title, where, text = f"{nick} invites you", f"{chan} \u00b7 {net}", "Click to see the invite bar"
        elif kind == "dcc":
            nick = getattr(s, "last_dcc", "")
            title, where = f"{nick} sends a file", net
            if getattr(s, "last_dcc_trusted", False):
                text = "Accepted (trusted)"            # so you always know it happened
        else:                                              # notice: people only, never services or servers
            from .control import SERVICES
            nick = (last.left if last is not None else "").strip("-")
            if not nick or "." in nick or nick.lower() in SERVICES or b is s.server_buffer:
                return
            title, where = f"-{nick}-", f"notice \u00b7 {net}"
        target = ("dcc", b) if kind == "dcc" else b
        if self.notifier.notify(kind, target, (id(s), kind, title.lower()), title, where, text) == "new" and not played:
            self.play_soft_chime()

    def play_soft_chime(self, force: bool = False, wanted: bool = False, name: str = "") -> bool:
        """BChat's one soft pop-up sound (packaging/make_chime.py): at most once every 10 seconds, never during
        full-screen games, presentations or Do Not Disturb. force = the Play button in Preferences."""
        from .notify import windows_busy
        now = time.monotonic()
        if not force and ((not self.cfg.popup_sound and not wanted) or now - self._last_chime < 10 or windows_busy()):
            return False
        self._last_chime = now
        name = name or ("bee" if self.cfg.popup_sound_name == "bee" else "soft")
        path = Path(__file__).resolve().parent / "assets" / "sounds" / f"{name}.wav"
        try:
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except (ImportError, RuntimeError):
            return False
        return True

    def _pop_up(self, b: Buffer, kind: str) -> str:
        """A card above the taskbar for the line that just came in (notify.py does the flood rules)."""
        line = b.lines[-1]
        left, text = line.left, line.text
        if left == "*":                                   # /me: "* nick does something"
            nick, _, text = text.partition(" ")
        elif left.startswith("*") and left.endswith("*") and len(left) > 2:
            nick = left.strip("*")                        # a private message shown in the current tab
        else:
            nick = left
        net = b.session.net.name
        where = f"private \u00b7 {net}" if kind == "priv" else f"{b.name} \u00b7 {net}"
        return self.notifier.notify(kind, b, (id(b.session), b.name.lower(), nick.lower()), nick, where, text)

    def _open_from_notice(self, b) -> None:
        if self.isHidden() or self.isMinimized():
            self._restore_from_tray()
        self.raise_()
        self.activateWindow()
        if isinstance(b, tuple):                          # a file offer card opens File Transfers too
            self.open_transfers()
            b = b[1]
        if b is not None and any(b in s.all_buffers() for s in self.sessions.values()):
            self.select_buffer(b)

    def _play_sound(self, kind: str, path: str = "") -> bool:
        """The .wav picked for this event on the Sound page. True when one played (then no chime as well)."""
        path = path or self.cfg.sounds.get(kind)
        if not path:
            return False
        now = time.monotonic()
        if now - self._last_sound < 2:                    # a flood plays one sound, not hundreds
            return True
        self._last_sound = now
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except (ImportError, RuntimeError):
            return False
        return True

    def _sync_tray(self) -> None:
        wanted = (self.cfg.tray_icon or self.cfg.minimize_to_tray or self.cfg.close_to_tray or self.cfg.start_in_tray
                  or self._tray_now)
        if wanted and self.tray is None and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray_menu = QMenu(self)
            self.tray_menu.aboutToShow.connect(lambda: self.fill_tray_menu(self.tray_menu))
            self.fill_tray_menu(self.tray_menu)
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self._tray_clicked)
            self.tray_tip()
            self.tray.show()
        elif not wanted and self.tray is not None:
            self._stop_blink()
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def _tray_clicked(self, why) -> None:
        R = QSystemTrayIcon.ActivationReason
        if why == R.DoubleClick or (why == R.Trigger and self.cfg.tray_click != "double"):
            self._restore_from_tray()

    def tray_entries(self) -> list:
        """[(network, [(tab, label, mark)])] for the tray menu: open channels and private chats, in tree order.
        mark: '@' when your nick was said, else the unread count, else ''."""
        out = []
        for s in self.sessions.values():
            rows = []
            for b in s.all_buffers():
                if b.kind not in (CHANNEL, QUERY) or b.placeholder:
                    continue
                mark = "@" if b.mentioned else (str(b.unread) if b.unread else "")
                rows.append((b, b.name, mark))
            if rows:
                out.append((s.net.name, rows))
        return out

    TRAY_MAX = 20

    def fill_tray_menu(self, menu: QMenu) -> None:
        """Right-click on the tray icon (0.5.0): Show BChat, your tabs by network (bold + a number = unread,
        '@' = your nick was said), Away, Preferences, Quit. No colours or dots (zen)."""
        from .widgets import add_menu_title
        menu.clear()
        add_menu_title(menu, "BChat")
        menu.addSeparator()
        menu.addAction(icon("dialog"), "Show BChat", self._restore_from_tray)
        entries = self.tray_entries() if self.cfg.tray_list else []
        if entries:
            menu.addSeparator()
            total = sum(len(rows) for _, rows in entries)
            more = None
            for net, rows in entries:
                h = menu.addAction(net.replace("&", "&&"))
                h.setEnabled(False)
                for b, label, mark in rows:
                    target = menu
                    if total > self.TRAY_MAX and not mark and b.kind == CHANNEL:
                        if more is None:
                            more = QMenu("More...", menu)
                        target = more                       # quiet channels fold away when there are many tabs
                    a = target.addAction(icon("jump") if b.kind == CHANNEL else icon("private"),
                                         label.replace("&", "&&") + (f"\t{mark}" if mark else ""))
                    a.triggered.connect(lambda _=False, b=b: self._open_from_tray(b))
                    if mark:
                        f = a.font()
                        f.setBold(True)
                        a.setFont(f)
            if more is not None:
                menu.addMenu(more)
        menu.addSeparator()
        away = menu.addAction("Away")
        away.setCheckable(True)
        live = [s for s in self.sessions.values() if s.state == "connected"]
        away.setChecked(bool(live) and all(s.away for s in live))
        away.setEnabled(bool(live))
        away.toggled.connect(self.set_away_everywhere)
        menu.addAction(icon("preferences"), "Preferences...", self._prefs_from_tray)
        menu.addSeparator()
        menu.addAction(icon("quit"), "Quit", self._quit_for_real)

    def _prefs_from_tray(self) -> None:
        self._restore_from_tray()
        self.open_preferences()

    def _open_from_tray(self, b: Buffer) -> None:
        self._restore_from_tray()
        if any(b in s.all_buffers() for s in self.sessions.values()):
            self.select_buffer(b)

    def set_away_everywhere(self, away: bool) -> None:
        for s in self.sessions.values():
            if s.state == "connected" and s.away != away:
                s.set_away(away)

    def tray_tip(self) -> None:
        """The tray icon's tooltip: 'BChat: 4 unread, 1 private' (or just BChat)."""
        if self.tray is None:
            return
        unread = private = 0
        for s in self.sessions.values():
            for b in s.all_buffers():
                if b.kind in (CHANNEL, QUERY) and b.unread:
                    unread += b.unread
                    private += b.kind == QUERY
        parts = ([f"{unread} unread"] if unread else []) + ([f"{private} private"] if private else [])
        self.tray.setToolTip("BChat: " + ", ".join(parts) if parts else "BChat")

    def _quit_for_real(self) -> None:
        self.really_quit = True
        self.close()
        self.really_quit = False     # still here means the user answered No to the quit question

    def _restore_from_tray(self) -> None:
        if self.isMinimized() or self._was_maximized:
            self.showMaximized() if self._was_maximized else self.showNormal()
        else:
            self.show()
        self._was_maximized = False
        self._tray_now = False
        self._sync_tray()         # the popup's one-time tray icon goes again, unless an option wants it
        self.raise_()
        self.activateWindow()
        self._stop_blink()

    def _blink_tray(self) -> None:
        if self.tray is None:
            self._blink_timer.stop()
            return
        self._tray_blink = not self._tray_blink
        self.tray.setIcon(self._tray_message_icon() if self._tray_blink else self.windowIcon())

    def _tray_message_icon(self) -> QIcon:
        """The blinking "new message" picture: Lucide's speech bubble in the theme's highlight colour."""
        from . import lucide
        ic = QIcon()
        for px in (16, 20, 24, 32, 48):
            ic.addPixmap(QPixmap.fromImage(lucide.image("message-circle", self.cfg.theme.highlight, px)))
        return ic

    def _stop_blink(self) -> None:
        self._blink_timer.stop()
        self._tray_blink = False
        if self.tray is not None:
            self.tray.setIcon(self.windowIcon())

    def changeEvent(self, ev):
        if ev.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._stop_blink()
            self.notifier.clear()          # you're looking at BChat now
        elif ev.type() == QEvent.Type.WindowStateChange and self.isMinimized() and self.cfg.minimize_to_tray and self.tray is not None:
            self._was_maximized = bool(ev.oldState() & Qt.WindowState.WindowMaximized)
            QTimer.singleShot(0, self._hide_if_minimized)     # hiding inside the state change itself leaves a taskbar ghost
        super().changeEvent(ev)

    def _hide_if_minimized(self) -> None:
        # Windows can report one minimize twice, and a late report must not hide a window that has come back since
        if self.isMinimized() and self.cfg.minimize_to_tray and self.tray is not None:
            self.hide()

    # --- logging: per tab, from the tab's right-click menu ----------------------------

    @staticmethod
    def _log_key(b: Buffer) -> str:
        return f"{lower(b.session.net.name)}/{lower(b.name)}"

    def needs_log_question(self) -> bool:
        """The first time logging is turned on, BChat says what it does. People already logging chose it before."""
        c = self.cfg
        return not (c.log_asked or c.log_all or c.log_tabs)

    def ask_logging(self, where: str, parent=None) -> int | None:
        """'BChat will save <where> to this PC' + Keep logs for. The days to keep, or None for Cancel."""
        from .logwindow import LogQuestion
        d = LogQuestion(parent or self, where, self.cfg.theme)
        self.log_question = d                    # tests and the button check answer it
        try:
            return d.keep_days() if d.exec() else None
        finally:
            self.log_question = None
            d.deleteLater()

    def _log_to_disk(self, b: Buffer, on: bool) -> None:
        """The tab menu's Log to Disk tick."""
        if on and self.needs_log_question():
            keep = self.ask_logging(b.name)
            if keep is None:
                return                           # Cancel: nothing saved, the tick is off next time the menu opens
            self.cfg.log_keep_days, self.cfg.log_asked = keep, True
        self._set_logging(b, on)

    def _set_logging(self, b: Buffer, on: bool) -> None:
        key = self._log_key(b)
        if on and key not in self.cfg.log_tabs:
            self.cfg.log_tabs.append(key)
        elif not on and key in self.cfg.log_tabs:
            self.cfg.log_tabs.remove(key)
        config.save(self.cfg, self.cfg_dir)

    @staticmethod
    def _clean(name: str) -> str:
        # names come from the network, so nothing in them may reach outside our folders
        return re.sub(r"[^\w#&+-]", "_", name) or "_"

    def logs_dir(self) -> Path:
        return self.cfg_dir / "logs"

    def log_path(self, b: Buffer, ts: float | None = None) -> Path:
        """Every day / every month: logs/Network/#channel/2026-11-09.log. Never (one file): the Log filename mask
        from Preferences, %n network, %s server, %c channel; a / in the mask makes a folder."""
        from . import logs
        s = b.session
        split = self.cfg.log_split if self.cfg.log_split in logs.SPLITS else "day"
        if split != "none":
            name = logs.dated_name(split, ts if ts is not None else time.time())
            return self.logs_dir() / self._clean(s.net.name) / self._clean(b.name) / name
        values = {"%n": self._clean(s.net.name), "%s": self._clean(s.server_name or s.net.name), "%c": self._clean(b.name)}
        parts = []
        for part in re.split(r"[/\\]", self.cfg.log_mask or "%n-%c.log"):
            for key, value in values.items():
                part = part.replace(key, value)
            part = re.sub(r'[<>:"|?*]', "_", part)
            if part and part not in (".", ".."):
                parts.append(part)
        return self.logs_dir().joinpath(*(parts or ["bchat.log"]))

    def logs_of(self, b: Buffer) -> list:
        """This tab's dated log files (View Log on the tab menu)."""
        from . import logs
        net, chan = self._clean(b.session.net.name), self._clean(b.name)
        return [f for f in logs.scan(self.logs_dir()) if f.network == net and f.channel == chan]

    def open_logs(self, b: Buffer | None = None):
        from .logwindow import LogsWindow
        w = self.tools.get("logs")
        if w is None:
            w = self.tools["logs"] = LogsWindow(self)
        if b is not None:
            w.show_for(self._clean(b.session.net.name), self._clean(b.name))
        else:
            w.show_for()
        w.show()
        w.raise_()
        return w

    def open_logs_folder(self) -> None:
        d = self.logs_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def clean_old_logs(self) -> int:
        from . import logs
        return logs.clean_up(self.logs_dir(), self.cfg.log_keep_days)

    def _log_line(self, b: Buffer, ln) -> None:
        self._save_replay(b, ln)
        c = self.cfg
        if not c.log_all and self._log_key(b) not in c.log_tabs:
            return
        path = self.log_path(b, ln.ts)
        stamp = ""
        if c.log_stamps:
            try:
                stamp = time.strftime(c.log_stamp_format, time.localtime(ln.ts))
            except ValueError:
                stamp = ""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(f"{stamp}{strip_format(ln.left)}\t{strip_format(ln.text)}\n")
        except OSError as e:
            b.session.add(b.session.server_buffer, "error", "*", f"Couldn't write the log: {e}")
            c.log_all = False
            if self._log_key(b) in c.log_tabs:
                c.log_tabs.remove(self._log_key(b))

    # --- "Display scrollback from previous session" -------------------------------------

    def _replay_path(self, b: Buffer) -> Path:
        return self.cfg_dir / "scrollback" / self._clean(b.session.net.name) / f"{self._clean(b.name)}.jsonl"

    def _save_replay(self, b: Buffer, ln) -> None:
        if not self.cfg.text_replay or b.kind == SERVER or not b.session.net.servers:
            return
        path = self._replay_path(b)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps([ln.ts, ln.kind, ln.left, ln.text]) + "\n")
        except OSError:
            pass

    def _load_replay(self, b: Buffer) -> None:
        if not self.cfg.text_replay or b.kind == SERVER or id(b) in self._replayed:
            return
        self._replayed.add(id(b))
        path = self._replay_path(b)
        if not path.exists():
            return
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        keep = rows[-min(self.cfg.max_lines, 500):]
        for row in keep:
            try:
                ts, kind, left, text = json.loads(row)
            except (ValueError, TypeError):
                continue
            b.lines.append(Line(kind, left, text, ts))
        if len(rows) > len(keep) * 2:     # keep the file from growing forever
            path.write_text("\n".join(keep) + "\n", encoding="utf-8")

    def paste_lines(self, text: str, buf: Buffer | None = None) -> None:
        """Multi-line paste (or the multi-line box): each line goes as a message. Never run as commands,
        so a paste can't /quit."""
        lines = [l for l in text.splitlines() if l.strip()]
        b = buf or self.buf
        if b is None or not lines:
            return
        if b.kind == SERVER:
            b.session.add(b, "error", "*", "No channel joined. Try /join #channel")
            return
        if len(lines) > 5 and not getattr(self, "skip_quit_prompt", False):
            from .pastedialog import PasteDialog
            d = PasteDialog(self, b.name, lines)
            self.paste_dialog = d
            d.finished.connect(lambda _r: self._send_paste(b, lines, d.choice))
            d.open()
            return
        self._send_paste(b, lines, "lines")

    def _send_paste(self, b, lines: list[str], choice: str) -> None:
        if choice == "one":
            b.session.say(b.name, " ".join(l.strip() for l in lines))
        elif choice == "lines":
            for line in lines:
                b.session.say(b.name, line)

    def _toggle_menu(self, on: bool) -> None:
        self.cfg.show_menu = on
        self.menubar_.setVisible(on)

    def _toggle_topic(self, on: bool) -> None:
        self.cfg.show_topic = on
        self.topic.setVisible(on)

    def _toggle_userlist(self, on: bool) -> None:
        self.cfg.show_userlist = on
        self._decide_userlist()

    def _toggle_away(self, on: bool) -> None:
        if self.session:
            self.session.set_away(on)

    def _join_dialog(self) -> None:
        s = self.session
        if s is None:
            self.open_network_list()
            return
        name, ok = QInputDialog.getText(self, "Join a Channel", "Channel:", text="#")
        if ok and len(name.strip()) > 1:
            s.send("JOIN", name.strip())

    def _clear_current(self) -> None:
        if self.buf is not None:
            self.buf.session.clear_buffer(self.buf)
            self.chat.reload(self.buf)

    def _search(self) -> None:
        text, ok = QInputDialog.getText(self, "Search Text", "Find:")
        if ok and text:
            if not self.chat.find(text, QTextDocument.FindFlag.FindBackward):
                self.chat.moveCursor(self.chat.textCursor().MoveOperation.End)
                self.chat.find(text, QTextDocument.FindFlag.FindBackward)

    def _save_text(self) -> None:
        if self.buf is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Text", f"{self.buf.name}.txt", "Text files (*.txt)")
        if path:
            lines = [f"{time.strftime('%H:%M', time.localtime(l.ts))} {l.left}\t{strip_format(l.text)}" for l in self.buf.lines]
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _raw(self, text: str, outgoing: bool) -> None:
        line = ("<< " if outgoing else ">> ") + text
        self.raw_lines.append(line)
        del self.raw_lines[:-2000]
        if self.raw_log is not None:
            self.raw_log.appendPlainText(line)

    def _open_raw_log(self) -> None:
        d = FramedDialog("BChat: Raw Log", self)
        d.resize(640, 400)
        view = QPlainTextEdit(d)
        view.setReadOnly(True)
        view.setFont(QFont(self.cfg.chat_font, self.cfg.chat_font_size))
        view.setPlainText("\n".join(self.raw_lines))
        d.body.addWidget(view)
        self.raw_log = view
        d.finished.connect(lambda _: setattr(self, "raw_log", None))
        d.show()

    def _about_box(self) -> AboutDialog:
        d = AboutDialog(self.cfg.theme, self, getattr(self, "updater", None))
        d.update_status.linkActivated.connect(lambda _l: (d.accept(), self.open_update_window()))
        return d

    def open_support(self) -> None:
        from .about import SUPPORT
        QDesktopServices.openUrl(QUrl(SUPPORT))

    def _about(self) -> None:
        self._about_box().exec()

    # --- updates ------------------------------------------------------------------

    def open_update_window(self) -> UpdateDialog:
        if self.update_window is None:
            self.update_window = UpdateDialog(self, self.updater)
            self.update_window.finished.connect(lambda _r: setattr(self, "update_window", None))
            self.update_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.update_window.sync()
        self.update_window.show()
        self.update_window.raise_()
        return self.update_window

    def check_updates(self) -> None:
        self.updater.check(manual=True)
        self.open_update_window()

    def _install_update_now(self) -> None:
        """Install Now: close BChat the normal way (settings saved, networks told), the installer opens it again."""
        self._update_restart = True
        keep = getattr(self, "skip_quit_prompt", False)
        self.skip_quit_prompt = True
        self._quit_for_real()
        self.skip_quit_prompt = keep
        self._update_restart = False

    def _import_settings(self) -> None:
        sources = xchat_import.default_sources()
        if not sources:
            QMessageBox.information(self, "Import XChat Settings", "No XChat settings folder found.")
            return
        report = xchat_import.import_into(self.cfg, sources)
        config.save(self.cfg, self.cfg_dir)
        QMessageBox.information(self, "Import XChat Settings", "\n".join(report))

    def _rekey(self, s: Session, name: str) -> None:
        """Sessions are filed by network name; keep that in step when a tab gets a new name."""
        for key, value in list(self.sessions.items()):
            if value is s:
                del self.sessions[key]
        self.sessions[name] = s

    def rename_network(self, net: NetworkConfig, new: str) -> bool:
        """Network List: click the selected name to rename it, as in XChat. False when the name is empty or taken."""
        new = new.strip()
        old = net.name
        if not new or (lower(new) != lower(old) and any(lower(n.name) == lower(new) for n in self.cfg.networks)):
            return False
        if new == old:
            return True
        net.name = new
        prefix_old, prefix_new = f"{lower(old)}/", f"{lower(new)}/"
        self.cfg.log_tabs = [prefix_new + k[len(prefix_old):] if k.startswith(prefix_old) else k for k in self.cfg.log_tabs]
        for s in list(self.sessions.values()):
            if s.net is net:
                self._rekey(s, new)
                s.server_buffer.name = new    # whatever the tab was called before (a server address, the old name)
                self._buffer_changed(s.server_buffer)
        config.save(self.cfg, self.cfg_dir)
        return True

    def edit_network(self, net: NetworkConfig) -> None:
        """Server tab menu > Edit Network: the Network List's Edit window for this network, saved on OK."""
        from .networklist import NetworkEditDialog
        if NetworkEditDialog(net, self).exec():
            config.save(self.cfg, self.cfg_dir)

    def add_network_from(self, s: Session) -> NetworkConfig:
        """AdiIRC's one-click save: this /server connection becomes a network in the Network List."""
        base = s.network_token or s.net.servers[0].host
        taken = {lower(n.name) for n in self.cfg.networks}
        name, i = base, 0
        while lower(name) in taken:
            i += 1
            name = f"{base}({i})"
        chans = [b.name for b in s.buffers.values() if b.kind == CHANNEL and b.joined]
        net = NetworkConfig(name, [Server(sv.host, sv.port, sv.ssl) for sv in s.net.servers],
                            password=s.net.password, autojoin=",".join(chans),
                            allow_invalid_cert=s.net.allow_invalid_cert, cert_pins=list(s.net.cert_pins))   # a certificate trusted on this tab stays trusted
        if s.nick and lower(s.nick) != lower(self.cfg.nick):
            net.nick, net.use_global = s.nick, False
        self.cfg.networks.append(net)
        config.save(self.cfg, self.cfg_dir)
        s.net, s.typed_by_hand = net, False   # this tab now is that network (no second save, reconnect uses it)
        self._rekey(s, name)
        s.server_buffer.name = name           # the tree shows the network's name now, not the server address
        self._buffer_changed(s.server_buffer)
        what = f"channels {' '.join(chans)}" if chans else "no channels"
        s.add(s.server_buffer, INFO, "*", f"Saved as network {name} in the Network List (server, nick, {what}).")
        if not getattr(self, "skip_dialogs", False):
            from .networklist import NetworkListDialog
            d = NetworkListDialog(self)
            for row in range(d.list.count()):
                if d.list.item(row).data(Qt.ItemDataRole.UserRole) is net:
                    d.list.setCurrentRow(row)
            d.exec()
        return net

    def open_preferences(self, page: str = "Text box") -> None:
        from .preferences import PreferencesDialog
        PreferencesDialog(self, page).exec()

    def _style_emoji_btn(self) -> None:
        t = self.cfg.theme
        self.emoji_btn.setStyleSheet(f"QToolButton {{ font-family: 'Segoe UI Emoji'; background: {t.thumb}; border: 1px solid {t.bar};"
                                     f" border-radius: 2px; }} QToolButton:hover {{ background: {t.thumb_hover}; }}")

    def apply_preferences(self) -> None:
        """After Preferences > OK: new colours everywhere, chat redrawn with the new font and text settings."""
        self.setStyleSheet(stylesheet(self.cfg.theme))
        self._apply_widget_prefs()   # first: a widget style sheet resets the font of the document showing
        self.chat.apply_font()
        self.chat.reload_all()
        self.topic.edit.exact = self.cfg.colors_exact
        if self.buf is not None:
            self.topic.edit.set_topic(self.topic.edit.raw)   # redraw the topic with the colour setting
        self.userlist.set_buffer(self.buf if self.buf is not None and self.buf.kind == CHANNEL else None)
        self.userlist.viewport().update()
        self.tree.viewport().update()          # tree lines and boxes come from the theme
        self.update_badge.update()
        self.topic.restyle()
        self._style_emoji_btn()
        set_icon_theme(self.cfg.theme, self)
        set_light_palette(self.cfg.theme)
        for b in [b for s in self.sessions.values() for b in s.all_buffers()]:
            self._buffer_changed(b)
        self.announcer.refresh()
        config.save(self.cfg, self.cfg_dir)

    def _apply_widget_prefs(self) -> None:
        """The settings that live on widgets: fonts, background image, list side, tray."""
        c = self.cfg
        font = f"font-family: '{c.chat_font}'; font-size: {c.chat_font_size}pt;"
        def restyle(widget, sheet):
            if widget.styleSheet() != sheet:
                widget.setStyleSheet(sheet)
        restyle(self.input, f"QLineEdit {{ {font} }}" if c.input_chat_font else "")
        restyle(self.userlist, f"QListView {{ {font} }}" if c.ul_chat_font else "")
        image = Path(c.chat_bg_image).as_posix() if c.chat_bg_image else ""
        restyle(self.chat, f"QTextBrowser {{ background-image: url('{image}'); background-position: center; background-repeat: no-repeat; }}" if image else "")
        self._place_panes()
        for w in self.detached.values():
            w.chat.apply_font()
            w.chat.reload_all()
        self._rebuild_tabs()
        self._refresh_meters()
        self.setWindowOpacity(max(30, c.opacity) / 100)
        self.notifier.show_ms = c.popup_seconds * 1000      # 0 = cards stay until closed
        self._sync_tray()

    # --- tool windows ---------------------------------------------------------------

    def report_problem(self, kind: str = "", error: str = "", sig: str = "", freeze: float = 0.0) -> None:
        from .reportwindow import ReportDialog
        self.report_dialog = ReportDialog(self, kind, error, sig, freeze)
        self.report_dialog.exec()

    def offer_report(self, headline: str, kind: str = "Crashed", error: str = "", sig: str = "", freeze: float = 0.0) -> None:
        self.report_bar.show_offer(headline, kind, error, sig, freeze)

    def run_command(self, s: Session, text: str) -> None:
        commands.run(self, s, self.buf if self.buf is not None and self.buf.session is s else s.server_buffer, text)

    # --- 0.3.0: nick colours + address book ------------------------------------------------

    def trust_user(self, s: Session, u: User, on: bool) -> None:
        """Nick menu tick: trust = *!user@host on this network; untrust = every entry that matches them."""
        import fnmatch
        prefix = f"{u.nick}!{u.host}"
        if on:
            user, _, host = u.host.partition("@")
            mask = f"*!{user.lstrip('~')}@{host}" if user else f"*!*@{host}"
            if user.startswith("~"):
                mask = f"*!*{user.lstrip('~')}@{host}"
            self.cfg.dcc_trusted.append({"nick": u.nick, "mask": mask, "net": s.net.name})
            self._say_here(f"{u.nick} is trusted now: files and direct chats from {mask} are accepted by themselves "
                           "(Preferences > File transfers).")
        else:
            keep = []
            for e in self.cfg.dcc_trusted:
                m = e.get("mask", "")
                m = m if "!" in m else "*!" + m
                hit = fnmatch.fnmatchcase(lower(prefix), lower(m)) and (not e.get("net") or lower(e["net"]) == lower(s.net.name))
                if not hit:
                    keep.append(e)
            self.cfg.dcc_trusted = keep
            self._say_here(f"{u.nick} isn't trusted any more.")
        self.save_config()

    def chat_colour_rule(self, b: Buffer, nick: str) -> str | None:
        from . import people
        s = b.session
        if s is None or not (self.cfg.nick_colours or self.cfg.address_book):
            return None
        u = b.users.get(lower(nick))
        return people.colour_for(self.cfg, s.net.name, nick, u.host if u is not None else "")

    def list_colour_rule(self, s: Session, nick: str, host: str) -> str | None:
        from . import people
        if s is None or not (self.cfg.nick_colours or self.cfg.address_book):
            return None
        return people.colour_for(self.cfg, s.net.name, nick, host)

    def nick_colours_changed(self) -> None:
        self.save_config()
        self.chat.reload_all()
        for w in self.detached.values():
            w.chat.reload_all()
        self.userlist.viewport().update()
        for key in ("nickcolours", "addressbook"):
            w = self.tools.get(key)
            if w is not None and w.isVisible() and key == "nickcolours":
                w.fill(w._row())

    def open_nick_colours(self):
        from .people import NickColoursWindow
        w = self.tools.get("nickcolours")
        if w is None:
            w = self.tools["nickcolours"] = NickColoursWindow(self)
        else:
            w.auto.setChecked(self.cfg.color_nicks)
            w.fill()
        w.show()
        w.raise_()
        return w

    def open_control(self, u: User | None = None, s: Session | None = None, b: Buffer | None = None):
        """Window > Auto-Op & Protect (0.5.0); from the nick menu the Add dialog opens filled in for that person."""
        from .control import ControlWindow
        w = self.tools.get("control")
        if w is None:
            w = self.tools["control"] = ControlWindow(self)
        else:
            w.fill()
        w.show()
        w.raise_()
        if u is not None:
            w.add(nick=u.nick, account=u.account, host=u.host, network=s.net.name if s else "",
                  channel=b.name if b is not None and b.kind == CHANNEL else "")
        return w

    def open_address_book(self, nick: str = "", real: str = ""):
        from .people import AddressBookWindow
        w = self.tools.get("addressbook")
        if w is None:
            w = self.tools["addressbook"] = AddressBookWindow(self)
        if nick:
            w.open_card(nick, real)
        else:
            w.fill()
        w.show()
        w.raise_()
        return w

    def quick_nick_colour(self, s: Session, nick: str):
        """Nick menu > Nick Colour...: a rule for this nick (on every network), at the top so it wins."""
        from . import people
        now = people.colour_name(self.cfg, s.net.name, nick) or "mauve"
        d = people.RuleDialog(self, {"mask": nick, "colour": now, "net": ""})
        self.rule_dialog = d

        def done(code: int) -> None:
            if code:
                r = d.rule()
                people.set_rule(self.cfg, r["mask"], r["colour"], r["net"])
                self.nick_colours_changed()
        d.finished.connect(done)
        d.open()
        return d

    # --- 0.3.0: Channel Central ---------------------------------------------------------------

    def open_channel_central(self, b: Buffer | None = None):
        from .central import ChannelCentral
        b = b or self.buf
        if b is None or b.kind != CHANNEL:
            return None
        key = ("central", id(b.session), lower(b.name))
        w = self.tools.get(key)
        if w is None:
            w = self.tools[key] = ChannelCentral(self, b.session, b)
        else:
            w.fill()
        w.show()
        w.raise_()
        w.refresh_lists()
        return w

    # --- 0.3.0: +typing and +reply ------------------------------------------------------------

    def show_typing(self) -> None:
        b = self.buf
        s = b.session if b is not None else None
        nicks = s.typing_now(b) if s is not None and b.kind in (CHANNEL, QUERY) else []
        if not nicks:
            self.typing_label.hide()
            return
        if len(nicks) == 1:
            text = f"{nicks[0]} is typing…"
        elif len(nicks) <= 3:
            text = f"{', '.join(nicks[:-1])} and {nicks[-1]} are typing…"
        else:
            text = f"{len(nicks)} people are typing…"
        self.typing_label.setText(text)
        self.typing_label.show()

    def _input_typing(self, text: str) -> None:
        """Let others see when I'm typing: active at most every 3 s; done when the box is emptied without sending."""
        b = self.buf
        if not self.cfg.send_typing or b is None or b.kind not in (CHANNEL, QUERY) or text.startswith("/"):
            return
        s = b.session
        now = time.time()
        if text:
            if self._typing_to != (id(b), b.name) or now - self._typing_sent >= 3:
                if s.send_typing(b.name, "active"):
                    self._typing_sent, self._typing_to = now, (id(b), b.name)
        elif self._typing_to == (id(b), b.name):
            s.send_typing(b.name, "done")
            self._typing_to = None

    def start_reply(self, b: Buffer, msgid: str) -> None:
        ln = next((x for x in reversed(b.lines) if x.msgid == msgid), None)
        if ln is None:
            return
        nick = ln.left if ln.left not in ("*", "") else ""
        text = strip_format(ln.text)
        short = html.escape(text if len(text) <= 60 else text[:59] + "…")
        muted = self.cfg.theme.muted
        self.reply_text.setText(f"<span style='color:{muted}'>↪ Replying to</span> <b>{html.escape(nick)}</b>"
                                f"<span style='color:{muted}'>: {short}</span>")
        self.replying = (b, msgid, nick)
        self.reply_bar.show()
        if b is not self.buf:
            self.select_buffer(b)
        if nick and lower(nick) != lower(b.session.nick):
            prefix = f"{nick}{self.cfg.nick_suffix or ':'} "
            if not self.input.text().startswith(prefix):
                self.input.setText(prefix + self.input.text())      # people on other clients still see who you answer
        self.input.setFocus()
        self.input.setCursorPosition(len(self.input.text()))

    def cancel_reply(self) -> None:
        self.replying = None
        self.reply_bar.hide()

    def _escape_reply(self) -> None:
        if self.replying is not None:
            self.cancel_reply()

    def reply_to_last(self) -> None:
        """Alt+R: answer the newest line someone else wrote here."""
        b = self.buf
        if b is None or b.kind not in (CHANNEL, QUERY) or not b.session.client_tag_ok("+draft/reply"):
            return
        me = lower(b.session.nick)
        ln = next((x for x in reversed(b.lines) if x.msgid and x.left and lower(x.left) != me and x.left not in ("*", "")), None)
        if ln is not None:
            self.start_reply(b, ln.msgid)

    def reply_jump(self, b: Buffer, msgid: str) -> None:
        chat = self.detached[id(b)].chat if id(b) in self.detached else self.chat
        block = chat.block_of(msgid)
        if block is not None:
            chat.flash_block(block)

    def save_config(self) -> None:
        config.save(self.cfg, self.cfg_dir)

    def open_tool(self, name: str):
        from . import tools
        w = self.tools.get(name)
        if w is None:
            make = {"plugins": tools.PluginsWindow, "chart": tools.CharChartWindow, "friends": tools.FriendsWindow, "ignore": tools.IgnoreWindow, "urls": tools.UrlGrabberWindow}[name]
            w = self.tools[name] = make(self)
        elif hasattr(w, "fill"):
            w.fill()
        w.show()
        w.raise_()
        return w

    def open_channel_list(self, s: Session, download: bool | None = None):
        from .tools import ChannelListWindow
        key = ("list", id(s))
        w = self.tools.get(key)
        if w is None:
            w = self.tools[key] = ChannelListWindow(self, s)
        w.show()
        w.raise_()
        if download or (download is None and not w.rows and not w.loading):
            w.download()
        elif download is False:
            s.list_sink = w
        return w

    def open_ban_list(self):
        from .tools import BanListWindow
        b = self.buf
        if b is None or b.kind != CHANNEL:
            QMessageBox.information(self, "Ban List", "You can only open the Ban List window while in a channel tab.")
            return None
        key = ("ban", id(b.session), lower(b.name))
        w = self.tools.get(key)
        if w is None:
            w = self.tools[key] = BanListWindow(self, b.session, b.name)
        w.show()
        w.raise_()
        w.refresh()
        return w

    def open_transfers(self):
        from .tools import TransfersWindow
        w = self.tools.get("transfers")
        if w is None:
            w = self.tools["transfers"] = TransfersWindow(self)
        w.fill()
        w.show()
        return w

    def open_chats(self):
        from .tools import DirectChatWindow
        w = self.tools.get("chats")
        if w is None:
            w = self.tools["chats"] = DirectChatWindow(self)
        w.fill()
        w.show()
        return w

    def send_file_dialog(self, s: Session, nicks: list[str], passive: bool = False) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, f"Send file to {', '.join(nicks)}")
        for nick in nicks:
            for p in paths:
                self.dcc.send_file(s, nick, p, passive)

    def load_plugin_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Plugin or Script", str(self.plugins.folder), "Python scripts (*.py)")
        if path:
            self.plugins.load(path)

    def ask_friend(self, nick: str = "", nets: str = "", edit: bool = False):
        """XChat's notify window: the nick filled in, ALL networks, then OK adds and says so where you are.
        edit = Friends List > Edit... (0.5.0): networks, note and what happens when they come online or leave."""
        from . import people
        from .frienddialog import FriendDialog
        note = (people.card_for(self.cfg, nick) or {}).get("notes", "") if nick else ""
        if edit:
            nets = self.cfg.friend_nets.get(next((n for n in self.cfg.friends if lower(n) == lower(nick)), nick), "")
        d = FriendDialog(self, nick, nets, edit=edit, note=" ".join(note.split()),
                         opts=self.cfg.friend_opts.get(lower(nick)) if nick else None)
        self.friend_dialog = d

        def done(code: int) -> None:
            if not code:
                return
            name, where = d.result_values()
            for n in name.split():
                if edit:
                    real = next((f for f in self.cfg.friends if lower(f) == lower(n)), n)
                    if where:
                        self.cfg.friend_nets[real] = where
                    else:
                        self.cfg.friend_nets.pop(real, None)
                else:
                    self.add_friend(n, where, say=True)
                self.set_friend_extras(n, d.options(), d.note_text())
            if edit:
                self._restart_friends()
            else:
                self.save_config()
        d.finished.connect(done)
        d.open()
        return d

    def set_friend_extras(self, nick: str, opts: dict, note: str) -> None:
        """Per-friend pop-up / sound / WHOIS, and the note, which lives on their Address Book card (one note)."""
        from . import people
        from .frienddialog import friend_defaults
        if opts == friend_defaults(self.cfg):
            self.cfg.friend_opts.pop(lower(nick), None)
        else:
            self.cfg.friend_opts[lower(nick)] = dict(opts)
        card = people.card_for(self.cfg, nick)
        if card is not None:
            if " ".join(card.get("notes", "").split()) != note:
                card["notes"] = note
        elif note:
            self.cfg.address_book.append({"nick": nick, "other": "", "real": "", "email": "", "web": "", "notes": note,
                                          "colour": ""})
        w = self.tools.get("addressbook")
        if w is not None and w.isVisible():
            w.fill()

    def add_friend(self, nick: str, nets: str = "", say: bool = False) -> bool:
        from .frienddialog import nets_from_text
        nick = nick.strip()
        nets = nets_from_text(nets)
        if not nick:
            return False
        if lower(nick) in [lower(n) for n in self.cfg.friends]:
            if say:
                self._say_here(f"{nick} is already in your Friends List.")
            return False
        self.cfg.friends.append(nick)
        if nets:
            self.cfg.friend_nets[nick] = nets
        self._restart_friends()
        if say:
            self._say_here(f"{nick} added to your Friends List ({nets or 'all networks'}). "
                           "You'll see when they come online; Window > Friends List shows them all.")
        return True

    # --- /np ------------------------------------------------------------------------------

    np_reader = None          # tests put a stand-in here

    def now_playing(self, s, b, only_me: bool = False) -> None:
        if not self.cfg.np_enabled:
            s.add(b, INFO, "*", "Now playing is off. Turn it on in Preferences > Chatting > Now Playing.")
            return
        from .nowplaying import NowPlaying
        np = NowPlaying(self.cfg, self, reader=self.np_reader)
        self._np = np
        np.found.connect(lambda t, why: self._np_found(s, b, t, why, only_me))
        np.ask()

    def _np_found(self, s, b, t, why: str, only_me: bool) -> None:
        from .nowplaying import DEFAULT_LINE, ask_dialog, render
        self.save_config()                         # players seen go into Preferences
        if t is None:
            s.add(b, INFO, "*", why)
            return
        line = render(self.cfg.np_line or DEFAULT_LINE, t)
        if only_me or b.kind not in (CHANNEL, QUERY):
            s.add(b, INFO, "*", f"{s.nick} {line}")
            if not only_me:
                s.add(b, INFO, "*", "Shown only to you: /np sends to a channel or a private chat.")
            return
        if not self.cfg.np_ask:
            s.action(b.name, line)
            return
        d = ask_dialog(self, b.name, t, self.cfg.np_line)
        self.np_dialog = d

        def done(_code: int) -> None:
            d.clock.stop()
            if d.choice == "send":
                if d.again.isChecked():
                    self.cfg.np_ask = False
                    self.save_config()
                s.action(b.name, d.current_line())      # the time as it is when Send is pressed
        d.finished.connect(done)
        d.open()

    def _announce(self, t) -> None:
        """A new song (announcer rules already met): one /me line in each listed channel that is open and joined."""
        from .nowplaying import DEFAULT_LINE, announces_in, render
        line = render(self.cfg.np_line or DEFAULT_LINE, t)
        for s in list(self.sessions.values()):
            if s.state != "connected":
                continue
            for b in list(s.buffers.values()):
                if b.kind == CHANNEL and b.joined and announces_in(self.cfg.np_announce_in, s.net.name, b.name):
                    s.action(b.name, line)
        self.save_config()                         # players seen go into Preferences

    def announce_here(self, b, on: bool) -> None:
        """Right click > Share > Announce Songs Here: adds or takes this network's channel off the announce list
        (an old plain "#chan" entry for every network goes too, so the tick always means just this tab)."""
        from .nowplaying import announce_channels
        here = f"{b.session.net.name}/{b.name}"
        names = [n for n in announce_channels(self.cfg.np_announce_in) if lower(n) not in (lower(here), lower(b.name))]
        if on:
            names.append(here)
            self.cfg.np_announce = True
        self.cfg.np_announce_in = ", ".join(names)
        self.save_config()
        self.announcer.refresh()
        b.session.add(b, INFO, "*", f"Announcing new songs in {b.name}." if on else f"Stopped announcing songs in {b.name}.")

    # --- Favourite Channels ----------------------------------------------------------------

    def open_favourites(self) -> None:
        from .favourites import FavouritesDialog
        d = getattr(self, "fav_dialog", None)
        if d is None or not d.isVisible():
            d = FavouritesDialog(self)
            self.fav_dialog = d
        d.show()
        d.raise_()

    def join_on_connect(self, b, on: bool) -> None:
        """Tab menu > Join on Connect: this channel joins (with its key) whenever this network connects."""
        from . import favourites
        s = b.session
        favourites.set_join(self.cfg, s.net.name, b.name, b.mode_args.get("k", ""), on)
        self.save_config()
        d = getattr(self, "fav_dialog", None)
        if d is not None and d.isVisible():
            d.favs = favourites.entries(self.cfg)
            d.fill()
        s.add(b, INFO, "*", f"{b.name} will be joined when you connect to {s.net.name}." if on
              else f"{b.name} won't be joined on connect any more (still in Favourite Channels).")

    def join_favourite(self, f) -> None:
        """Join a favourite: right away if its network is connected, else connect it and join after login."""
        net = next((n for n in self.cfg.networks if n.name == f.network), None)
        if net is None:
            return
        s = self.session_for(net)
        if s.state == "connected":
            s.focus_next = lower(f.channel)
            s.send("JOIN", f.channel, *([f.key] if f.key else []))
            return
        s.join_once.append((f.channel, f.key))
        self.connect_network(net)

    def _say_here(self, text: str) -> None:
        b = self.buf
        if b is not None:
            b.session.add(b, INFO, "*", text)

    def remove_friend(self, nick: str) -> None:
        name = next((n for n in self.cfg.friends if lower(n) == lower(nick)), nick)
        self.cfg.friends = [n for n in self.cfg.friends if n != name]
        self.cfg.friend_nets.pop(name, None)
        self.cfg.friend_opts.pop(lower(name), None)          # the Address Book card (and its note) stays
        self._restart_friends()

    def _restart_friends(self) -> None:
        for s in self.sessions.values():
            s.start_friends()
        self.save_config()
        self._friends_changed()

    def _friends_changed(self) -> None:
        w = self.tools.get("friends")
        if w is not None and w.isVisible():
            w.fill()

    def _grab_urls(self, b: Buffer, ln) -> None:
        """XChat's url_check_line: every link anyone shows, newest last, no repeats."""
        if not self.cfg.url_grabber or "." not in ln.text:
            return
        changed = False
        for m in URL_RE.finditer(strip_format(ln.text)):
            url = m.group(0).rstrip(".,);:!?'\"")
            if url in self.urls:
                continue
            self.urls.append(url)
            del self.urls[:-max(1, self.cfg.url_limit)]
            changed = True
        w = self.tools.get("urls")
        if changed and w is not None and w.isVisible():
            w.fill()

    def open_network_list(self) -> None:
        from .networklist import NetworkListDialog
        NetworkListDialog(self).exec()

    def closeEvent(self, ev):
        if self.cfg.close_to_tray and self.tray is not None and not getattr(self, "really_quit", False):
            self.hide()
            ev.ignore()
            return
        live = [s for s in self.sessions.values() if s.state == "connected"]
        if live and self.cfg.ask_on_quit and not getattr(self, "skip_quit_prompt", False):
            choice, dont_ask = QuitDialog(self, len(live), [(s.net.name, s.bouncer) for s in live if s.bouncer]).ask()
            if choice == "cancel":
                ev.ignore()
                return
            if choice == "tray":
                # ticked: from now on the close button does this by itself
                self.cfg.close_to_tray = self.cfg.close_to_tray or dont_ask
                self._tray_now = True
                self._sync_tray()
                if dont_ask:
                    self.save_config()
                self.hide()
                ev.ignore()
                return
            if dont_ask:
                self.cfg.ask_on_quit = False
        self.notifier.clear()
        self.dcc.shutdown()
        for s in self.sessions.values():
            s.disconnect_from_network()
        self.cfg.win_maximized = self.isMaximized()
        if not self.isMaximized():
            self.cfg.win_width, self.cfg.win_height = self.width(), self.height()
            self.cfg.win_x, self.cfg.win_y = self.x(), self.y()
        sizes = self.split.sizes()
        at = self.split.indexOf(self.tree)
        left, right = (sizes[at] if at >= 0 else 0), sizes[self.split.indexOf(self.right_panel)]
        if left > 0:
            self.cfg.pane_left = left
        if right > 0:
            self.cfg.pane_right = right
        config.save(self.cfg, self.cfg_dir)
        if self.updater.state == READY:
            self.updater.install(restart=self._update_restart)
        super().closeEvent(ev)
        self.quit_requested.emit()
