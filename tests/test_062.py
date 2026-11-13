"""0.6.2: BR-4, a full tab dropped one old line per new line and Qt laid the whole tab out again every time
(3 ms a line at 5000 lines, 13 ms at 20000). Now old lines go in batches; marker and reading place follow."""
import time
from bchat.chatview import ChatView
from bchat.config import Config
from bchat.session import MSG, Buffer, Line


def view(app, cap):
    cv = ChatView(Config(nick="me", max_lines=cap))
    cv.resize(800, 400)
    return cv


def add(cv, b, i, cap):
    ln = Line(MSG, f"n{i % 7}", f"line {i} " + "text " * 20, time.time(), msgid=f"id{i}")
    b.lines.append(ln)
    del b.lines[:-cap]
    cv.add_line(b, ln)


def test_full_tab_trims_in_batches_and_keeps_newest(app):
    cap = 200
    cv, b = view(app, cap), Buffer(None, "#a", "channel")
    cv.show_buffer(b)
    for i in range(cap * 5):
        add(cv, b, i, cap)
        d = cv.docs[id(b)]
        assert d.blockCount() <= cap + max(50, cap // 10)
    assert d.maximumBlockCount() == 0                       # Qt's own one-by-one cap is off
    assert d.lastBlock().text().split("line ", 1)[1].startswith(f"{cap * 5 - 1} ")
    first = d.firstBlock()
    n = int(first.text().split("line ", 1)[1].split()[0])
    assert first.blockFormat().property(cv.MSGID) == f"id{n}"   # the first kept line keeps its own id and indent
    assert first.blockFormat().leftMargin() > 0
    assert abs(first.blockFormat().textIndent() + first.blockFormat().leftMargin()) < 0.01


def test_marker_stays_on_its_line_after_trim(app):
    cap = 200
    cv, b, other = view(app, cap), Buffer(None, "#a", "channel"), Buffer(None, "#b", "channel")
    cv.show_buffer(other)
    cv.show_buffer(b)
    for i in range(cap):
        add(cv, b, i, cap)
    cv.show_buffer(other)                                    # leaving #a marks where you stopped reading
    d, m = cv.docs[id(b)], b.marker
    text = d.findBlockByNumber(m).text()
    for i in range(cap, cap + 120):                          # enough for one batch trim, not past the marker
        add(cv, b, i, cap)
    assert b.marker is not None and b.marker < m
    assert d.findBlockByNumber(b.marker).text() == text
    for i in range(cap + 120, cap * 4):                      # the marked line itself drops out: no marker
        add(cv, b, i, cap)
    assert b.marker is None


def test_report_keeps_own_words_when_a_nick_is_line_or_ctrl():
    from bchat.reports import Redactor
    red = Redactor(nicks={"line", "Ctrl", "Belon"}, channels={"#secret"})
    trace = 'File "bchat\chatview.py", line 153, in _render\n  File "bchat\session.py", line 1777, in _irc_quit'
    assert red(trace) == trace                                    # the trace stays readable
    assert red("Paste Ctrl+V") == "Paste Ctrl+V"
    assert red("Ctrl+Shift+V") == "Ctrl+Shift+V"
    out = red("Belon said line is here in #secret, ask Ctrl")       # real names are still hidden
    assert "Belon" not in out and "#secret" not in out and " line " not in out and "Ctrl" not in out
    assert red("line 4") != "line 4" and red('x.py", line 2, in f') == 'x.py", line 2, in f'
