"""0.8.5 typed commands and the input box: "!" text is chat, long /msg /me /notice /say split at 512 bytes,
/topic /kick /ban with a channel, /mode #, /msg =nick (DCC), /notify -r and +nick, /ignore and /ban switches,
ignore masks per CASEMAPPING, empty input never sent, per-tab history and drafts, Tab completion (keeps the text
after the cursor, query nicks, /msg the last one who wrote), right-click Paste, Ctrl+Tab, Leave Channel on a
greyed tab, /list twice, links in brackets."""
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bchat import commands
from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import parse_line, split_urls, trim_url


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


@pytest.fixture
def ws(app, tmp_path):
    """A real main window with one session that thinks it is online; every line it would send is kept in s.out."""
    from bchat.mainwindow import MainWindow
    win = MainWindow(Config(nick="Belon", skip_network_list=True, welcome_done=True, local_find=False), tmp_path)
    win.skip_quit_prompt = True
    s = win.session_for(NetworkConfig("N", [Server("127.0.0.1", 6667)]))
    s.out = []
    s.send_raw = lambda line, secret=False, quiet=False: s.out.append(line)
    s._connect_next = lambda: None
    s._conn_gen += 1
    s._last_rx = time.time()
    s.want_connected = True
    s.state = "connected"
    s.nick = "Belon"
    feed(s, ":srv 001 Belon :Welcome", ":srv 005 Belon NETWORK=N CASEMAPPING=rfc1459 :are supported")
    win.select_buffer(s.server_buffer)
    yield win, s
    win.close()


def join(win, s, chan, *others):
    feed(s, f":Belon!u@h JOIN {chan}", f":srv 353 Belon = {chan} :@Belon {' '.join(others)}",
         f":srv 366 Belon {chan} :End")
    b = s.buffers[s.fold(chan)]
    win.select_buffer(b)
    return b


def typed(win, s, text):
    """As if typed in the box and Enter pressed."""
    s.out.clear()
    win.input.setText(text)
    win._entered()
    return list(s.out)


def run(win, s, b, text):
    s.out.clear()
    with s.typed():
        commands.run(win, s, b, text)
    return list(s.out)


def said(b):
    return [ln.text for ln in b.lines]


# --- 1. typed "!" is chat ---------------------------------------------------------------------------------------

def test_typed_bang_text_is_chat_not_a_program(ws, monkeypatch):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    started = []
    monkeypatch.setattr(commands, "start_program", lambda s, b, line, send=False: started.append(line))
    assert typed(win, s, "!seen Bob") == ["PRIVMSG #kampung :!seen Bob"]
    assert started == []


def test_bang_still_starts_a_program_from_a_user_command(ws, monkeypatch):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    started = []
    monkeypatch.setattr(commands, "start_program", lambda s, b, line, send=False: started.append(line))
    win.cfg.user_commands = [["np", "!notepad.exe"]]
    run(win, s, b, "/np")
    assert started == ["notepad.exe"]
    win._run_with("!calc.exe")                        # a menu entry with "!program"
    assert started == ["notepad.exe", "calc.exe"]


# --- 2. long /msg /me /notice /say split like plain chat ----------------------------------------------------------

LONG = "é" * 150 + "x" * 300 + "ü" * 150             # 900+ bytes, 2-byte letters at both cut points


def _bodies(lines, head):
    out = []
    for ln in lines:
        assert len(ln.encode("utf-8")) + 2 <= 512, len(ln.encode("utf-8"))
        bare = head[:-1]                                     # a one-word last parameter needs no ":"
        assert ln.startswith(head) or (ln.startswith(bare) and " " not in ln[len(bare):]), ln
        out.append(ln[len(head):] if ln.startswith(head) else ln[len(bare):])
    return out


@pytest.mark.parametrize("cmd,head", [("/msg Ali", "PRIVMSG Ali :"), ("/notice Ali", "NOTICE Ali :"),
                                      ("/say", "PRIVMSG #kampung :")])
def test_long_text_is_split_inside_512_bytes(ws, cmd, head):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    lines = run(win, s, b, f"{cmd} {LONG}")
    assert len(lines) >= 3
    assert "".join(_bodies(lines, head)) == LONG


def test_long_me_is_split_inside_512_bytes(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    lines = run(win, s, b, f"/me {LONG}")
    assert len(lines) >= 3
    bodies = _bodies(lines, "PRIVMSG #kampung :\x01ACTION ")
    assert all(x.endswith("\x01") for x in bodies)
    assert "".join(x[:-1] for x in bodies) == LONG


# --- 3. /topic /kick /ban with a channel, /mode # -------------------------------------------------------------------

def test_topic_kick_ban_take_a_channel_and_mode_hash_is_this_channel(ws):
    win, s = ws
    other = join(win, s, "#other", "Ali")
    b = join(win, s, "#kampung", "Ali")
    other.users[s.fold("Ali")].host = "~ali@cust.isp.my"
    assert run(win, s, b, "/topic #other new topic here") == ["TOPIC #other :new topic here"]
    assert run(win, s, b, "/topic hello all") == ["TOPIC #kampung :hello all"]
    assert run(win, s, b, "/kick #other Ali go away") == ["KICK #other Ali :go away"]
    assert run(win, s, b, "/kick Ali bye") == ["KICK #kampung Ali bye"]
    assert run(win, s, b, "/ban #other Ali") == ["MODE #other +b Ali!*ali@cust.isp.my"]
    assert run(win, s, b, "/mode # +m") == ["MODE #kampung +m"]
    assert run(win, s, b, "/mode #other +n") == ["MODE #other +n"]


# --- 4. /msg =nick goes over DCC ------------------------------------------------------------------------------------

def test_msg_to_equals_nick_goes_over_dcc_chat(ws):
    win, s = ws
    got = []
    s.dcc_say = lambda sess, target, text: got.append((target, text)) or True
    assert run(win, s, s.server_buffer, "/msg =Bob hello there") == []
    assert got == [("=Bob", "hello there")]


# --- 5a. /notify -r and +nick ---------------------------------------------------------------------------------------

def test_notify_minus_r_removes_and_plus_only_adds(ws):
    win, s = ws
    run(win, s, s.server_buffer, "/notify +Wira")
    assert "Wira" in win.cfg.friends and "+Wira" not in win.cfg.friends
    run(win, s, s.server_buffer, "/notify +Wira")          # + never takes off
    assert "Wira" in win.cfg.friends
    run(win, s, s.server_buffer, "/notify -r Wira")
    assert "Wira" not in win.cfg.friends and "-r" not in win.cfg.friends
    run(win, s, s.server_buffer, "/notify -r Wira")          # not there: said, nothing added
    assert "Wira" not in win.cfg.friends
    assert any("isn't on your Friends List" in t for t in said(s.server_buffer))


# --- 5b. /ignore switches -------------------------------------------------------------------------------------------

def test_ignore_kind_switches_and_no_junk_masks(ws):
    win, s = ws
    b = s.server_buffer
    run(win, s, b, "/ignore -pn Bob")
    assert win.cfg.ignores == ["Bob!*@*"]
    assert win.cfg.ignore_kinds["Bob!*@*"] == "PN"
    assert s.ignored("Bob!x@y", "P") and s.ignored("Bob!x@y", "N") and not s.ignored("Bob!x@y", "C")
    run(win, s, b, "/ignore -cti Ali")
    assert win.cfg.ignore_kinds["Ali!*@*"] == "CTI"
    run(win, s, b, "/ignore -kd Joe")
    assert win.cfg.ignore_kinds["Joe!*@*"] == "KD"
    run(win, s, b, "/ignore -q Zed")                         # unknown switch: usage, no entry
    assert not any(m.startswith(("-", "Zed")) for m in win.cfg.ignores)
    assert any("Usage: IGNORE" in t for t in said(b))


def test_ignore_timed_is_taken_off_when_the_time_is_up(ws):
    win, s = ws
    run(win, s, s.server_buffer, "/ignore -u60 Bob")
    assert win.cfg.ignores == ["Bob!*@*"]
    assert any("for 60 seconds" in t for t in said(s.server_buffer))
    timer = commands._IGNORE_TIMERS[s][s.fold("Bob!*@*")]
    assert timer.isActive() and timer.interval() == 60000
    timer.timeout.emit()
    assert win.cfg.ignores == []


def test_ignore_remove_list_exclude_and_clear(ws):
    win, s = ws
    b = s.server_buffer
    run(win, s, b, "/ignore Bob")
    run(win, s, b, "/ignore Ali")
    run(win, s, b, "/ignore -l")
    assert any("Bob!*@*" in t and "Ali!*@*" in t for t in said(b))
    run(win, s, b, "/ignore -r bob")
    assert win.cfg.ignores == ["Ali!*@*"]
    run(win, s, b, "/ignore -x *!*@friend.my")
    assert win.cfg.ignore_kinds["*!*@friend.my"] == "U"
    run(win, s, b, "/ignore *!*@*.my")
    assert s.ignored("Ali!a@x.my", "C") and not s.ignored("Zed!z@friend.my", "C")    # -x: never ignored
    run(win, s, b, "/ignore -r")                             # -r alone: the whole list
    assert win.cfg.ignores == [] and win.cfg.ignore_kinds == {}


def test_ignore_with_a_type_ignores_the_address(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    b.users[s.fold("Ali")].host = "~ali@cust.isp.my"
    run(win, s, b, "/ignore Ali 3")
    assert win.cfg.ignores == ["*!*ali@*.isp.my"]


def test_private_message_from_an_open_query_is_not_ignored(ws):
    win, s = ws
    run(win, s, s.server_buffer, "/ignore Bob")
    assert s.ignored("Bob!b@h", "P")
    s.buffer("Bob")                                          # the query tab is open
    assert not s.ignored("Bob!b@h", "P")
    assert s.ignored("Bob!b@h", "C")                         # channel lines still hidden


# --- 5c. /unignore any case -----------------------------------------------------------------------------------------

def test_unignore_any_case(ws):
    win, s = ws
    run(win, s, s.server_buffer, "/ignore Bob")
    run(win, s, s.server_buffer, "/unignore BOB")
    assert win.cfg.ignores == []


# --- 5d. ignore masks per CASEMAPPING -------------------------------------------------------------------------------

def test_ignore_mask_brackets_are_letters_under_ascii(ws):
    win, s = ws
    feed(s, ":srv 005 Belon CASEMAPPING=ascii :are supported")
    win.cfg.ignores[:] = ["Foo[a]!*@*"]
    assert s.ignored("foo[a]!u@h")
    assert not s.ignored("fooa!u@h")                         # [a] is not a set of letters
    assert not s.ignored("foo{a}!u@h")                       # ascii: { is not [


def test_ignore_mask_brackets_fold_under_rfc1459(ws):
    win, s = ws
    win.cfg.ignores[:] = ["Foo[a]\\!*@*"]
    assert s.ignored("foo{a}|!u@h")
    assert s.ignored("FOO[A]\\!u@h")
    assert not s.ignored("fooa!u@h")


# --- /ban switches ----------------------------------------------------------------------------------------------------

def test_ban_switches_kick_remove_timed_and_default_mask(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    b.users[s.fold("Ali")].host = "~ali@cust.isp.my"
    assert run(win, s, b, "/ban Ali") == ["MODE #kampung +b Ali!*ali@cust.isp.my"]
    assert run(win, s, b, "/ban Ali 1") == ["MODE #kampung +b *!*ali@cust.isp.my"]
    assert run(win, s, b, "/ban -k Ali enough now") == ["MODE #kampung +b Ali!*ali@cust.isp.my",
                                                       "KICK #kampung Ali :enough now"]
    assert run(win, s, b, "/ban -k #kampung Ali 3 bye") == ["MODE #kampung +b *!*ali@*.isp.my", "KICK #kampung Ali bye"]
    assert run(win, s, b, "/ban -r Ali") == ["MODE #kampung -b Ali!*ali@cust.isp.my"]
    assert run(win, s, b, "/ban -u30 Ali") == ["MODE #kampung +b Ali!*ali@cust.isp.my"]
    assert run(win, s, b, "/kickban Ali go") == ["MODE #kampung +b Ali!*ali@cust.isp.my", "KICK #kampung Ali go"]
    assert run(win, s, b, "/ban -x Ali") == []
    assert any("Usage: BAN" in t for t in said(b))


def test_ban_timed_comes_off_by_itself(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    b.users[s.fold("Ali")].host = "~ali@cust.isp.my"
    run(win, s, b, "/ban -u1 Ali")
    s.out.clear()
    QTest.qWait(1300)
    assert s.out == ["MODE #kampung -b Ali!*ali@cust.isp.my"]


# --- 6. nothing to send ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["/ hello", "/", "   ", "/   "])
def test_empty_or_nameless_command_is_not_sent(ws, text):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    assert run(win, s, b, text) == []


# --- 7a. per-tab history and draft ----------------------------------------------------------------------------------

def test_each_tab_has_its_own_history_and_draft(ws):
    win, s = ws
    one = join(win, s, "#one", "Ali")
    typed(win, s, "hello one")
    two = join(win, s, "#two", "Ali")
    typed(win, s, "hello two")
    win.input.setText("half typed")
    win.select_buffer(one)
    assert win.input.text() == ""                            # #two's draft stayed in #two
    QTest.keyClick(win.input, Qt.Key.Key_Up)
    assert win.input.text() == "hello one"
    QTest.keyClick(win.input, Qt.Key.Key_Up)
    assert win.input.text() == "hello one"                   # no "hello two" here
    win.input.clear()
    win.select_buffer(two)
    assert win.input.text() == "half typed"
    QTest.keyClick(win.input, Qt.Key.Key_Up)
    assert win.input.text() == "hello two"
    run(win, s, two, "/clear history")
    win.select_buffer(one)
    QTest.keyClick(win.input, Qt.Key.Key_Up)
    assert win.input.text() == ""                            # /clear history: every tab


# --- 7b. Tab completion -----------------------------------------------------------------------------------------------

def test_tab_completion_keeps_the_text_after_the_cursor(ws):
    win, s = ws
    join(win, s, "#kampung", "Oracle", "Ali")
    win.input.setText("Orhow are you")
    win.input.setCursorPosition(2)
    QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text() == "Oracle" + win.cfg.nick_suffix + " how are you"
    assert win.input.cursorPosition() == len("Oracle" + win.cfg.nick_suffix + " ")


def test_tab_completes_query_nicks(ws):
    win, s = ws
    s.buffer("Zainal")                                       # an open dialog, not in this channel
    join(win, s, "#kampung", "Ali")
    win.input.setText("hi Zai")
    QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text() == "hi Zainal "


def test_tab_in_empty_box_messages_the_last_ones_who_wrote(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    feed(s, ":Wira!w@h PRIVMSG Belon :hi", ":Jamal!j@h PRIVMSG Belon :yo")
    win.select_buffer(b)
    win.input.clear()
    QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text() == "/msg Jamal "
    QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text() == "/msg Wira "
    QTest.keyClick(win.input, Qt.Key.Key_Tab)
    assert win.input.text() == "/msg Jamal "


# --- 7c. right-click Paste --------------------------------------------------------------------------------------------

def test_right_click_paste_of_several_lines_goes_like_ctrl_v(ws, monkeypatch):
    win, s = ws
    join(win, s, "#kampung", "Ali")
    got = []
    monkeypatch.setattr(win, "paste_lines", lambda text, buf=None: got.append(text))
    QApplication.clipboard().setText("line one\nline two")
    menu = win.input.build_menu(0)
    paste = next(a for a in menu.actions() if a.text().replace("&", "").startswith("Paste"))
    paste.trigger()
    assert got == ["line one\nline two"]
    assert win.input.text() == ""
    QApplication.clipboard().setText("just one")
    win.input.build_menu(0)
    next(a for a in win.input.build_menu(0).actions() if a.text().replace("&", "").startswith("Paste")).trigger()
    assert win.input.text() == "just one" and got == ["line one\nline two"]


# --- 7d. Ctrl+Tab -----------------------------------------------------------------------------------------------------

def test_ctrl_tab_moves_through_the_tabs(ws):
    win, s = ws
    one = join(win, s, "#one", "Ali")
    two = join(win, s, "#two", "Ali")
    win.select_buffer(one)
    win.show()
    win.input.setFocus()
    QTest.keyClick(win.input, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    assert win.buf is two
    QTest.keyClick(win.input, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    QApplication.processEvents()
    assert win.buf is one
    assert win.input.text() == ""                            # no completion happened


# --- 7e. Leave Channel on a greyed tab --------------------------------------------------------------------------------

def test_leave_channel_on_a_greyed_tab_closes_it_without_part(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    feed(s, ":Op!o@h KICK #kampung Belon :out")
    assert not b.joined
    s.out.clear()
    menu = win._switcher_menu(b)
    next(a for a in menu.actions() if a.text() == "Leave Channel").trigger()
    QApplication.processEvents()
    assert not any(l.startswith("PART") for l in s.out)
    assert s.fold("#kampung") not in s.buffers


def test_leave_channel_on_a_joined_tab_parts(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    s.out.clear()
    menu = win._switcher_menu(b)
    with s.typed():
        next(a for a in menu.actions() if a.text() == "Leave Channel").trigger()
    assert any(l.startswith("PART #kampung") for l in s.out)


# --- 7f. /list twice --------------------------------------------------------------------------------------------------

def test_list_with_arguments_twice_has_no_repeated_rows(ws):
    win, s = ws
    for _ in range(2):
        run(win, s, s.server_buffer, "/list >400")
        feed(s, ":srv 321 Belon Channel :Users Name", ":srv 322 Belon #big 500 :big one",
             ":srv 322 Belon #bigger 900 :bigger", ":srv 323 Belon :End of /LIST")
        w = win.tools[("list", id(s))]
        w._flush()
    assert sorted(r[0] for r in w.rows) == ["#big", "#bigger"]
    assert w.view.topLevelItemCount() == 2


# --- 8. links in brackets ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,url", [
    ("see https://en.wikipedia.org/wiki/Foo_(bar) now", "https://en.wikipedia.org/wiki/Foo_(bar)"),
    ("(see https://example.com/page)", "https://example.com/page"),
    ("(https://en.wikipedia.org/wiki/Foo_(bar))", "https://en.wikipedia.org/wiki/Foo_(bar)"),
    ("go to https://example.com/a.", "https://example.com/a"),
    ("[https://example.com/x]", "https://example.com/x"),
])
def test_links_keep_their_own_brackets_only(text, url):
    assert [p for p, is_url in split_urls(text) if is_url] == [url]
    assert trim_url(url + ").,") == url


def test_url_grabber_keeps_a_links_own_closing_bracket(ws):
    win, s = ws
    win.cfg.url_grabber = True
    b = join(win, s, "#kampung", "Ali")
    feed(s, ":Ali!a@h PRIVMSG #kampung :read https://en.wikipedia.org/wiki/Foo_(bar) and (https://example.com/p)")
    urls = [u[0] if isinstance(u, (list, tuple)) else getattr(u, "url", u) for u in win.urls]
    assert "https://en.wikipedia.org/wiki/Foo_(bar)" in urls and "https://example.com/p" in urls


# --- round 2: typed mask types 0-19, address lookup, per-network ignores, -k -h -s -y, /ignore on|off ----------------

from bchat.protocol import mirc_mask                           # noqa: E402
from bchat.session import ACTION, HILITE, MSG                  # noqa: E402


@pytest.mark.parametrize("kind, mask", [
    (0, "*!~ali@cust.isp.my"), (1, "*!*ali@cust.isp.my"), (2, "*!*@cust.isp.my"), (3, "*!*ali@*.isp.my"),
    (4, "*!*@*.isp.my"), (5, "Ali!~ali@cust.isp.my"), (6, "Ali!*ali@cust.isp.my"), (7, "Ali!*@cust.isp.my"),
    (8, "Ali!*ali@*.isp.my"), (9, "Ali!*@*.isp.my"),
])
def test_typed_mask_types_0_to_9(kind, mask):
    assert mirc_mask("Ali", "~ali@cust.isp.my", kind) == mask


@pytest.mark.parametrize("kind, mask", [
    (10, "*!~ali@cust??.isp?.my"), (12, "*!*@cust??.isp?.my"), (13, "*!*ali@cust??.isp?.my"),
    (15, "Ali!~ali@cust??.isp?.my"), (19, "Ali!*@cust??.isp?.my"),
])
def test_typed_mask_types_10_to_19_turn_host_digits_into_question_marks(kind, mask):
    assert mirc_mask("Ali", "~ali@cust12.isp3.my", kind) == mask


def test_typed_mask_types_on_an_ip_address():
    assert mirc_mask("Ali", "ali@1.2.3.4", 4) == "*!*@1.2.3.*"
    assert mirc_mask("Ali", "ali@1.2.3.4", 14) == "*!*@?.?.?.?"


def test_ban_with_unknown_address_asks_the_server_first(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    assert run(win, s, b, "/ban Ali 2") == ["USERHOST Ali"]
    assert not any("+b" in ln for ln in s.out)
    s.out.clear()
    feed(s, ":srv 302 Belon :Ali=+~ali@cust.isp.my")
    assert s.out == ["MODE #kampung +b *!*@cust.isp.my"]


def test_kickban_with_unknown_address_kicks_after_the_answer(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    assert run(win, s, b, "/kickban Ali go") == ["USERHOST Ali"]
    s.out.clear()
    feed(s, ":srv 302 Belon :Ali=+~ali@cust.isp.my")
    assert s.out == ["MODE #kampung +b Ali!*ali@cust.isp.my", "KICK #kampung Ali go"]


def test_ignore_with_unknown_address_asks_the_server_first(ws):
    win, s = ws
    b = s.server_buffer
    assert run(win, s, b, "/ignore Ali 5") == ["USERHOST Ali"]
    assert win.cfg.ignores == []
    feed(s, ":srv 302 Belon :Ali=+~ali@cust.isp.my")
    assert win.cfg.ignores == ["Ali!~ali@cust.isp.my"]


def test_no_address_in_the_answer_bans_nothing_and_says_so(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    assert run(win, s, b, "/ban Zed 2") == ["USERHOST Zed"]
    s.out.clear()
    feed(s, ":srv 302 Belon :")                               # USERHOST's answer when Zed isn't on IRC
    assert s.out == []                                        # never nick!*@*
    assert any("Zed isn't on IRC now" in t for t in said(b))
    run(win, s, s.server_buffer, "/ignore Zed 2")
    feed(s, ":srv 302 Belon :")
    assert win.cfg.ignores == []
    assert not s._addr_waiting                                # nothing left waiting


def test_userhost_answer_with_oper_and_away_marks_still_bans(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    run(win, s, b, "/ban Ali 2")
    s.out.clear()
    feed(s, ":srv 302 Belon :ali*=-~ali@cust.isp.my")         # oper, away, other case
    assert s.out == ["MODE #kampung +b *!*@cust.isp.my"]


def test_disconnect_while_waiting_bans_nothing_and_says_so(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    run(win, s, b, "/ban Zed 2")
    s.out.clear()
    s._on_disconnected()
    assert not s._addr_waiting
    assert any("Disconnected before the server gave Zed's address" in t for t in said(b))
    assert not any("+b" in ln for ln in s.out)


def test_dns_still_gets_its_own_userhost_answer(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali")
    run(win, s, b, "/ban Ali 2")
    s.dns_waiting[s.fold("Bob")] = (b, "Bob")
    s.out.clear()
    feed(s, ":srv 302 Belon :Bob=+bob@b.example")             # not ours: /dns keeps it
    assert s._addr_waiting == [s.fold("Ali")]
    assert not any("+b" in ln for ln in s.out)


def test_ignore_without_w_is_for_this_network_only(ws):
    win, s = ws
    b = s.server_buffer
    win.cfg.ignores.append("Old!*@*")                         # saved before 0.8.5: no network, so every network
    run(win, s, b, "/ignore Bob")
    run(win, s, b, "/ignore -w Joe")
    assert win.cfg.ignore_nets == {"Bob!*@*": "N"}
    assert any("Now ignoring Bob!*@* on N" in t for t in said(b))
    assert any("Now ignoring Joe!*@* on every network" in t for t in said(b))
    assert s.ignored("Bob!b@h", "C") and s.ignored("Joe!j@h", "C") and s.ignored("Old!o@h", "C")
    s.net.name = "Other"
    assert not s.ignored("Bob!b@h", "C")
    assert s.ignored("Joe!j@h", "C") and s.ignored("Old!o@h", "C")
    run(win, s, b, "/ignore Bob")                             # now on both
    assert win.cfg.ignore_nets["Bob!*@*"] == "N,Other" and s.ignored("Bob!b@h", "C")
    run(win, s, b, "/ignore -r Bob")                          # off here only
    assert win.cfg.ignores.count("Bob!*@*") == 1 and win.cfg.ignore_nets["Bob!*@*"] == "N"
    assert not s.ignored("Bob!b@h", "C")
    run(win, s, b, "/ignore -r Joe")
    assert "Joe!*@*" not in win.cfg.ignores


def test_ignore_k_takes_their_colours_and_bold_out(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali", "Bob")
    run(win, s, b, "/ignore -k Ali")
    feed(s, ":Ali!a@h PRIVMSG #kampung :\x02loud\x02 \x0304red\x03 text",
         ":Ali!a@h PRIVMSG #kampung :\x01ACTION waves \x1fhard\x1f\x01",
         ":Bob!b@h PRIVMSG #kampung :\x02bold\x02 stays")
    texts = said(b)
    assert "loud red text" in texts
    assert "Ali waves hard" in texts
    assert "\x02bold\x02 stays" in texts
    feed(s, ":Ali!a@h NOTICE #kampung :\x0304tinted\x03")
    assert "tinted" in said(b)


def test_ignore_h_means_never_a_highlight_or_alert(ws):
    win, s = ws
    b = join(win, s, "#kampung", "Ali", "Bob")
    got = []
    s.notify.connect(lambda buf, kind: got.append(kind))
    run(win, s, b, "/ignore -h Ali")
    feed(s, ":Bob!b@h PRIVMSG #kampung :hey Belon")
    assert b.lines[-1].kind == HILITE and got == ["hilight"]
    got.clear()
    feed(s, ":Ali!a@h PRIVMSG #kampung :hey Belon", ":Ali!a@h PRIVMSG #kampung :\x01ACTION pokes Belon\x01")
    assert [ln.kind for ln in b.lines[-2:]] == [MSG, ACTION]
    assert "hey Belon" in said(b)                             # still shown
    assert got == []
    feed(s, ":Ali!a@h NOTICE #kampung :Belon look")
    assert got == []


def test_ignore_s_and_y_are_accepted_and_do_nothing(ws):
    win, s = ws
    b = s.server_buffer
    run(win, s, b, "/ignore -sy Ali")
    assert win.cfg.ignores == []
    assert not any("Usage" in t for t in said(b))
    run(win, s, b, "/ignore -ps Bob")
    assert win.cfg.ignore_kinds["Bob!*@*"] == "P"


def test_ignore_on_and_off_switch_the_whole_list(ws):
    win, s = ws
    b = s.server_buffer
    assert win.cfg.ignore_on is True
    run(win, s, b, "/ignore Bob")
    run(win, s, b, "/ignore off")
    assert win.cfg.ignore_on is False and not s.ignored("Bob!b@h", "C")
    assert win.cfg.ignores == ["Bob!*@*"]                      # the list itself is kept
    run(win, s, b, "/ignore on")
    assert win.cfg.ignore_on is True and s.ignored("Bob!b@h", "C")


def test_ignore_list_window_keeps_k_h_and_the_network_on_edits(ws):
    from bchat.tools import IgnoreWindow
    win, s = ws
    win.cfg.ignores[:] = ["Bob!*@*"]
    win.cfg.ignore_kinds = {"Bob!*@*": "CPKH"}
    win.cfg.ignore_nets = {"Bob!*@*": "N"}
    w = IgnoreWindow(win)
    try:
        it = w.view.topLevelItem(0)
        it.setCheckState(3, Qt.CheckState.Checked)            # tick Notice
        assert sorted(win.cfg.ignore_kinds["Bob!*@*"]) == sorted("CPNKH")
        it.setText(0, "Bob!*@cust.my")                         # rename: the network goes with it
        assert win.cfg.ignore_nets == {"Bob!*@cust.my": "N"}
        assert sorted(win.cfg.ignore_kinds["Bob!*@cust.my"]) == sorted("CPNKH")
        w.view.setCurrentItem(w.view.topLevelItem(0))
        w.delete_selected()
        assert win.cfg.ignore_nets == {} and win.cfg.ignores == []
    finally:
        w.close()
