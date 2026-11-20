"""0.8.5 DCC fixes: close and ack checks (also past 4 GB), passive resume with two offers, empty files, offer
offers always arriving (unless ignored), timeouts, the DCC ignore list, direct chat line limits and encodings, and the 'a (1).txt' rename.
Loopback sockets only; .txt and .bin files only."""
import socket
import struct
import time
from pathlib import Path

import pytest

from bchat import dcc as dccmod
from bchat.dcc import Transfer, _unique_name, decode_line
from test_live import _sender, live, wait  # noqa: F401  (live is a fixture)

LOCAL = 2130706433      # 127.0.0.1 as a DCC offer writes it


def _everything(s):
    return [l.text for b in s.buffers.values() for l in b.lines] + [l.text for l in s.server_buffer.lines]


def _peer_reads(app, t, ack_with, close_when_done=True, ms=8000):
    """Connect to our send offer, read every byte, answer each read with ack_with(total_read), then close."""
    c = socket.create_connection(("127.0.0.1", t.port))
    c.setblocking(False)
    got = bytearray()

    def pump():
        try:
            while True:
                d = c.recv(65536)
                if not d:
                    break
                got.extend(d)
                c.send(struct.pack(">I", ack_with(len(got)) & 0xFFFFFFFF))
        except BlockingIOError:
            pass
        return len(got) >= t.size and t.pos >= t.size
    assert wait(app, pump, ms), (len(got), t.pos, t.state)
    for _ in range(20):          # let our side read the acks first
        app.processEvents()
        time.sleep(0.005)
    if close_when_done:
        c.close()
    return c, got


# --- 1. a close is only "complete" when the acks say so -------------------------------------------------

def test_send_closed_with_short_acks_is_not_complete(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    src = tmp_path / "big.bin"
    src.write_bytes(bytes(range(256)) * 2400)          # 600 KB, many chunks
    t = win.dcc.send_file(s, "Belon", str(src))
    _peer_reads(app, t, lambda n: min(n, 100))         # they read it all but only ever say 100 bytes, then cancel
    assert wait(app, lambda: t.state != "active", 4000)
    assert t.state == "failed" and t.error == "Connection closed before the end", (t.state, t.acked)
    assert not any('"big.bin" complete' in x for x in _everything(s))


def test_send_closed_missing_only_the_last_ack_is_complete(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    src = tmp_path / "last.bin"
    payload = bytes(range(256)) * 2400
    src.write_bytes(payload)
    size = len(payload)
    t = win.dcc.send_file(s, "Belon", str(src))
    _peer_reads(app, t, lambda n: min(n, size - 3000))   # an old client that drops its last ack
    assert wait(app, lambda: t.state == "done", 4000), (t.state, t.error, t.acked)


# --- 2. acks past 4 GB -------------------------------------------------------------------------------------

class _FakeSock:
    def __init__(self):
        self.data = b""
        self.closed = False

    def readAll(self):
        d, self.data = self.data, b""
        return d

    def bytesAvailable(self):
        return len(self.data)

    def bytesToWrite(self):
        return 0

    def flush(self):
        return True

    def disconnectFromHost(self):
        self.closed = True

    def blockSignals(self, _b):
        pass

    def abort(self):
        pass


def test_acks_past_4gb_count_the_wraps(live):
    app, srv, win, s = live
    size = (1 << 32) + 1000                           # 4 GB and a bit
    t = Transfer(win.dcc, s, "send", "Belon", "huge.bin", size)
    t.state, t.sock = "active", _FakeSock()
    t.pos = size                                      # everything is written; the acks lag behind
    t.sock.data = struct.pack(">I", 2000)             # really 2000 bytes so far (the low 32 bits of the size are 1000)
    t._readable()
    assert t.state == "active" and t.acked == 2000
    t.sock.data = struct.pack(">I", 0xFFFFFF00)       # just before the wrap
    t._readable()
    assert t.state == "active" and t.acked == 0xFFFFFF00
    t.sock.data = struct.pack(">I", 500)              # wrapped once: 4 GB + 500
    t._readable()
    assert t.state == "active" and t.acked == (1 << 32) + 500
    t.sock.data = struct.pack(">I", 1000)[:2]         # an ack in two pieces
    t._readable()
    assert t.state == "active"
    t.sock.data = struct.pack(">I", 1000)[2:]
    t._readable()
    assert t.acked == size and t.state == "done" and t.sock.closed


def test_acks_while_sending_past_4gb(live):
    """The acks follow the bytes as they go: every wrap is counted, done only at the real end."""
    app, srv, win, s = live
    size = (3 << 32) + 7
    t = Transfer(win.dcc, s, "send", "Belon", "huge.bin", size)
    t.state, t.sock = "active", _FakeSock()
    step = 1 << 30
    for total in range(step, size, step):
        t.pos = min(size, total + step)               # we are ahead of the acks
        t.sock.data = struct.pack(">I", total & 0xFFFFFFFF)
        t._readable()
        assert t.acked == total and t.state == "active"
    t.pos = size
    t.sock.data = struct.pack(">I", size & 0xFFFFFFFF)
    t._readable()
    assert t.acked == size and t.state == "done"


# --- 3. passive resume with two offers to the same nick ------------------------------------------------------

def test_passive_resume_two_sends_to_one_nick_picks_the_right_one(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"A" * 1000)
    pb = bytes(range(200)) * 10
    b.write_bytes(pb)
    t1 = win.dcc.send_file(s, "Belon", str(a), passive=True)
    t2 = win.dcc.send_file(s, "Belon", str(b), passive=True)
    assert t1.token != t2.token
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC RESUME b.bin 0 500 {t2.token}\x01")
    assert wait(app, lambda: any(f"DCC ACCEPT b.bin 0 500 {t2.token}" in x for x in srv.received)), \
        [x for x in srv.received if "DCC" in x]
    assert t2.pos == 500 and t1.pos == 0
    assert not any("DCC ACCEPT a.bin" in x for x in srv.received)
    # their passive answer, with b's token: only b connects, from 500 on
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1); ls.setblocking(False)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND b.bin {LOCAL} {ls.getsockname()[1]} {len(pb)} {t2.token}\x01")
    got, conn = bytearray(), []

    def pump():
        try:
            if not conn:
                conn.append(ls.accept()[0]); conn[0].setblocking(False)
            d = conn[0].recv(65536)
            got.extend(d)
            if d:
                conn[0].send((500 + len(got)).to_bytes(4, "big"))
        except BlockingIOError:
            pass
        return t2.state == "done"
    assert wait(app, pump, 5000), (t2.state, t2.pos, t2.acked)
    assert bytes(got) == pb[500:] and t1.state == "queued" and t1.pos == 0
    conn[0].close(); ls.close()


def test_passive_resume_two_receives_from_one_nick_picks_the_right_one(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    win.cfg.dcc_dir = str(tmp_path)
    payload = bytes(range(250)) * 4
    (tmp_path / "p1.bin").write_bytes(b"1" * 100)
    (tmp_path / "p2.bin").write_bytes(payload[:100])
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND p1.bin {LOCAL} 0 1000 11\x01")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND p2.bin {LOCAL} 0 1000 22\x01")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    t1, t2 = win.dcc.items
    win.dcc.resume(t1)
    win.dcc.resume(t2)
    assert wait(app, lambda: any("DCC RESUME p2.bin 0 100 22" in x for x in srv.received)), \
        [x for x in srv.received if "DCC" in x]
    assert any("DCC RESUME p1.bin 0 100 11" in x for x in srv.received)
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01DCC ACCEPT p2.bin 0 100 22\x01")
    assert wait(app, lambda: t2.server is not None and t2.port)
    assert t1.server is None and t1.state == "queued"
    assert wait(app, lambda: any(f"DCC SEND p2.bin {LOCAL} {t2.port} 1000 22" in x for x in srv.received))
    c = socket.create_connection(("127.0.0.1", t2.port))
    c.sendall(payload[100:])
    assert wait(app, lambda: t2.state == "done", 5000), (t2.state, t2.pos, t2.error)
    c.close()
    assert (tmp_path / "p2.bin").read_bytes() == payload
    assert (tmp_path / "p1.bin").read_bytes() == b"1" * 100 and t1.state == "queued"


# --- 4. empty files --------------------------------------------------------------------------------------------

def test_empty_file_receive_completes_at_once(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    port, got = _sender(b"")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND empty.txt {LOCAL} {port} 0\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    win.dcc.accept(t)
    assert wait(app, lambda: t.state != "connecting" and t.state != "queued", 2000)
    assert t.state == "done", (t.state, t.error)
    assert (tmp_path / "empty.txt").is_file() and (tmp_path / "empty.txt").stat().st_size == 0
    assert any('"empty.txt" complete, 0 bytes' in x for x in _everything(s))


def test_empty_file_passive_receive_completes_at_once(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    win.cfg.dcc_dir = str(tmp_path)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND none.bin {LOCAL} 0 0 45\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    win.dcc.accept(t)
    assert wait(app, lambda: t.port and t.server is not None)
    c = socket.create_connection(("127.0.0.1", t.port))
    assert wait(app, lambda: t.state == "done", 2000), (t.state, t.error)
    c.close()
    assert (tmp_path / "none.bin").stat().st_size == 0


def test_empty_file_send_completes_at_once(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    src = tmp_path / "zero.txt"
    src.write_bytes(b"")
    t = win.dcc.send_file(s, "Belon", str(src))
    c = socket.create_connection(("127.0.0.1", t.port))
    assert wait(app, lambda: t.state == "done", 2000), (t.state, t.error)
    c.settimeout(2)
    assert c.recv(10) == b""          # nothing sent, and closed
    c.close()


# --- 5. offers are never flood-limited; only an ignore for DCC (or for everything) drops one ----------------------

def _marker(app, srv, s, text):
    srv.send(f":Marker!m@h PRIVMSG #skinhead :{text}")
    assert wait(app, lambda: text in _everything(s))


def test_every_offer_reaches_the_user_even_past_the_ctcp_flood_limit(live, tmp_path):
    """The CTCP flood guard limits our answers, not offers: five offers in a row all arrive."""
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_open_recv = False
    win.cfg.flood_ctcp, win.cfg.flood_ctcp_person = 10, 2
    srv.send(":Spam!s@h PRIVMSG Badaboom :VERSION")
    for i in range(4):
        srv.send(f":Spam!s@h PRIVMSG Badaboom :DCC SEND f{i}.txt {LOCAL} 1 10")
    srv.send(f":Spam!s@h PRIVMSG Badaboom :DCC CHAT chat {LOCAL} 1")
    _marker(app, srv, s, "marker1")
    assert [t.name for t in win.dcc.items if t.nick == "Spam"] == ["f0.txt", "f1.txt", "f2.txt", "f3.txt", "chat"]


@pytest.mark.parametrize("kinds", ["D", None, "CPNTDI"])
def test_an_offer_from_someone_ignored_for_dcc_is_dropped(live, tmp_path, kinds):
    """Ignored with type DCC, or with no type (= everything): no offer, no item."""
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.ignores.append("Spam!*@*")
    if kinds is not None:
        win.cfg.ignore_kinds["Spam!*@*"] = kinds
    srv.send(f":Spam!s@h PRIVMSG Badaboom :DCC SEND f.txt {LOCAL} 1 10")
    srv.send(f":Spam!s@h PRIVMSG Badaboom :DCC CHAT chat {LOCAL} 1")
    srv.send(f":Ann!a@h PRIVMSG Badaboom :DCC SEND ann.txt {LOCAL} 1 10")
    assert wait(app, lambda: any(t.nick == "Ann" for t in win.dcc.items))
    _marker(app, srv, s, "marker1")
    assert [t.nick for t in win.dcc.items] == ["Ann"]


def test_an_ignore_for_other_types_lets_offers_through(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_open_recv = False
    win.cfg.ignores.append("Spam!*@*")
    win.cfg.ignore_kinds["Spam!*@*"] = "CPNT"
    srv.send(f":Spam!s@h PRIVMSG Badaboom :DCC SEND f.txt {LOCAL} 1 10")
    assert wait(app, lambda: [t.name for t in win.dcc.items] == ["f.txt"])


def test_the_manager_itself_drops_an_offer_from_someone_ignored_for_dcc(live, tmp_path):
    """The safety net in the manager, even if an offer got past the session's own check."""
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.ignores.append("Spam!*@*")
    win.cfg.ignore_kinds["Spam!*@*"] = "D"
    s.last_ctcp_prefix = "Spam!s@h"
    win.dcc.incoming(s, "Spam", f"SEND f.txt {LOCAL} 1 10")
    win.dcc.incoming(s, "Spam", f"CHAT chat {LOCAL} 1")
    assert not win.dcc.items
    s.last_ctcp_prefix = "Ann!a@h"
    win.dcc.incoming(s, "Ann", f"SEND ann.txt {LOCAL} 1 10")
    assert [t.nick for t in win.dcc.items] == ["Ann"]


# --- 6. timeouts -----------------------------------------------------------------------------------------------------

def test_an_offer_nobody_accepts_expires_after_2_minutes(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND later.txt {LOCAL} 1 10\x01")
    srv.send(f":Oracle!o@h PRIVMSG Badaboom :\x01DCC CHAT chat {LOCAL} 1\x01")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    f, c = win.dcc.items
    for t in (f, c):
        t.created -= 110
        t.tick()
        assert t.state == "queued"
        t.created -= 15
        t.tick()
        assert t.state == "failed" and t.error == "Offer expired", (t.state, t.error)


def test_the_two_timeouts_are_settings(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    assert (win.cfg.dcc_offer_timeout, win.cfg.dcc_idle_timeout) == (120, 300)
    win.cfg.dcc_offer_timeout = 30
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND a.txt {LOCAL} 1 10\x01")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND b.txt {LOCAL} 1 10\x01")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    a, b = win.dcc.items
    a.created -= 31
    a.tick()
    assert a.state == "failed" and a.error == "Offer expired"
    win.cfg.dcc_offer_timeout = 0                       # wait for ever
    b.created -= 100000
    b.tick()
    assert b.state == "queued"
    b.abort()


def test_passive_and_chat_offers_count_as_offers(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    win.cfg.dcc_dir = str(tmp_path)
    src = tmp_path / "p.txt"; src.write_bytes(b"x" * 10)
    ours = win.dcc.send_file(s, "Belon", str(src), passive=True)      # waits for their answer
    chat = win.dcc.start_chat(s, "Belon")                              # waits for them to connect
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND theirs.bin {LOCAL} 0 10 99\x01")
    assert wait(app, lambda: any(t.kind == "recv" for t in win.dcc.items))
    theirs = next(t for t in win.dcc.items if t.kind == "recv")
    win.dcc.accept(theirs)                                             # we listen, they never connect
    assert theirs.server is not None
    for t in (ours, chat, theirs):
        t.created -= 110
        t.listening_since -= 110
        t.tick()
        assert t.state == "queued"
        t.created -= 15
        t.listening_since -= 15
        t.tick()
        assert t.state == "failed" and t.error == "Nobody connected in time", (t.kind, t.state, t.error)
    # an ordinary (active) send offer of ours is a transfer nobody sends anything to: the idle timeout, 5 minutes
    plain = win.dcc.send_file(s, "Belon", str(src))
    plain.created -= 290
    plain.tick()
    assert plain.state == "queued"
    plain.created -= 15
    plain.tick()
    assert plain.state == "failed" and plain.error == "Nobody connected in time"


def test_a_transfer_with_no_data_for_5_minutes_times_out(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1); ls.setblocking(False)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND slow.bin {LOCAL} {ls.getsockname()[1]} 5000\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    win.dcc.accept(t)
    conn = []

    def pump():
        try:
            if not conn:
                conn.append(ls.accept()[0])
                conn[0].sendall(b"s" * 1000)          # then nothing more
        except BlockingIOError:
            pass
        return t.pos == 1000
    assert wait(app, pump, 4000), (t.state, t.pos)
    t.last_data -= 290
    t.tick()
    assert t.state == "active"
    t.last_data -= 15
    t.tick()
    assert t.state == "failed" and t.error == "Transfer timed out"
    conn[0].close(); ls.close()


def test_an_idle_direct_chat_never_times_out(live):
    app, srv, win, s = live
    win.cfg.dcc_ip = "127.0.0.1"
    t = win.dcc.start_chat(s, "Belon")
    c = socket.create_connection(("127.0.0.1", t.port))
    assert wait(app, lambda: t.state == "active")
    t.last_data -= 3600
    t.created -= 3600
    t.tick()
    assert t.state == "active"
    c.close()


# --- 7. the DCC ignore list: those offers never reach the user; programs are still never auto accepted -------------

IGNORE_MSG = "DCC Send of {} from Belon ignored (file type is on the DCC ignore list)"


def test_the_dcc_ignore_list_default():
    from bchat.config import Config
    assert Config().dcc_ignore_exts == ["*.exe", "*.com", "*.bat", "*.dll", "*.ini", "*.mrc", "*.vbs", "*.js", "*.pif",
                                        "*.scr", "*.lnk", "*.pl", "*.shs", "*.htm", "*.html"]
    assert Config().dcc_ignore_exts is not Config().dcc_ignore_exts


@pytest.mark.parametrize("name", ["a.exe", "b.com", "c.bat", "d.dll", "e.ini", "f.mrc", "g.vbs", "h.js", "i.pif",
                                  "j.scr", "k.lnk", "l.pl", "m.shs", "n.htm", "o.html", "P.HTML", "q.exe.", "r‮gpj.exe"])
def test_an_offer_on_the_dcc_ignore_list_is_ignored_with_one_line(live, tmp_path, name):
    """Only the name is offered: no file is made or sent."""
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_auto = 1
    win.cfg.dcc_open_recv = False
    srv.send(f":Belon!b@h PRIVMSG Badaboom :DCC SEND {name} {LOCAL} 1 10")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :DCC SEND ok.txt {LOCAL} 1 10")
    assert wait(app, lambda: [t.name for t in win.dcc.items] == ["ok.txt"])
    shown = dccmod.safe_name(name)
    server = [l.text for l in s.server_buffer.lines]
    assert server.count(IGNORE_MSG.format(shown)) == 1, server
    assert not any(shown in t for b in s.buffers.values() for t in (l.text for l in b.lines))
    assert not any(p.name != "ok.txt" for p in tmp_path.iterdir())


def test_the_dcc_ignore_list_is_a_setting(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_open_recv = False
    win.cfg.dcc_ignore_exts = ["*.txt", "zip", "secret?.bin"]
    for name in ("a.txt", "b.ZIP", "secret1.bin", "c.ini", "secret10.bin"):
        srv.send(f":Belon!b@h PRIVMSG Badaboom :DCC SEND {name} {LOCAL} 1 10")
    assert wait(app, lambda: [t.name for t in win.dcc.items] == ["c.ini", "secret10.bin"])
    server = [l.text for l in s.server_buffer.lines]
    for name in ("a.txt", "b.ZIP", "secret1.bin"):
        assert IGNORE_MSG.format(name) in server
    win.cfg.dcc_ignore_exts = []                 # an empty list ignores nothing
    srv.send(f":Belon!b@h PRIVMSG Badaboom :DCC SEND d.txt {LOCAL} 1 10")
    assert wait(app, lambda: len(win.dcc.items) == 3)


@pytest.mark.parametrize("name", ["a.msix", "b.hta", "c.exe"])
def test_programs_off_the_list_are_still_never_auto_accepted(live, tmp_path, name):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_auto = 1
    win.cfg.dcc_open_recv = False
    win.cfg.dcc_ignore_exts = []
    port, _ = _sender(b"fine")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :DCC SEND {name} {LOCAL} 1 10")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :DCC SEND ok.txt {LOCAL} {port} 4")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    risky, ok = win.dcc.items
    assert wait(app, lambda: ok.state == "done", 4000)
    assert risky.name == name and risky.state == "queued", (risky.name, risky.state)


# --- /dcc ignore [on|off|accept|ignore] --------------------------------------------------------------------------------

def _offer_names(app, srv, win, names):
    before = len(win.dcc.items)
    for n in names:
        srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND {n} {LOCAL} 1 10\x01")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND end.bin {LOCAL} 1 10\x01")   # .bin: never on these lists
    assert wait(app, lambda: any(t.name == "end.bin" for t in win.dcc.items[before:]))
    got = [t.name for t in win.dcc.items[before:]]
    return got[:-1]


def test_dcc_ignore_defaults_on_and_ignore():
    from bchat.config import Config
    c = Config()
    assert c.dcc_ignore_on is True and c.dcc_ignore_mode == "ignore"


def test_dcc_ignore_off_lets_every_offer_in_and_on_turns_it_back(live, tmp_path):
    from test_live import type_cmd
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_open_recv = False
    type_cmd(win, "/dcc ignore off")
    assert win.cfg.dcc_ignore_on is False
    assert any("DCC ignore is off" in l.text for l in s.server_buffer.lines + s.buffers["#skinhead"].lines)
    assert _offer_names(app, srv, win, ["a.ini", "b.txt"]) == ["a.ini", "b.txt"]
    type_cmd(win, "/dcc ignore on")
    assert win.cfg.dcc_ignore_on is True
    assert _offer_names(app, srv, win, ["c.ini", "d.txt"]) == ["d.txt"]


def test_dcc_ignore_accept_mode_lets_only_the_listed_types_in(live, tmp_path):
    from test_live import type_cmd
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_open_recv = False
    win.cfg.dcc_ignore_exts = ["*.txt", "*.bin", "*.exe"]
    type_cmd(win, "/dcc ignore accept")
    assert win.cfg.dcc_ignore_mode == "accept"
    assert _offer_names(app, srv, win, ["a.txt", "b.zip", "c.exe"]) == ["a.txt", "c.exe"]
    assert "DCC Send of b.zip from Belon ignored (file type is not on the DCC accept list)" in \
        [l.text for l in s.server_buffer.lines]
    win.cfg.dcc_ignore_exts = ["*.txt"]          # end.bin, the last offer, must come in either way
    type_cmd(win, "/dcc ignore ignore")
    assert win.cfg.dcc_ignore_mode == "ignore"
    assert _offer_names(app, srv, win, ["d.txt", "e.zip"]) == ["e.zip"]


def test_dcc_ignore_accept_mode_never_auto_accepts_a_program(live, tmp_path):
    """Even when the accept list names a program type, it waits for the user's own Accept."""
    from test_live import type_cmd
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_auto = 1
    win.cfg.dcc_open_recv = False
    win.cfg.dcc_ignore_exts = ["*.exe", "*.txt"]
    type_cmd(win, "/dcc ignore accept")
    port, _ = _sender(b"fine")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND p.exe {LOCAL} 1 10\x01")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND ok.txt {LOCAL} {port} 4\x01")
    assert wait(app, lambda: len(win.dcc.items) == 2)
    prog, ok = win.dcc.items
    assert wait(app, lambda: ok.state == "done", 4000)
    assert prog.name == "p.exe" and prog.state == "queued"


def test_dcc_ignore_without_a_word_shows_how_it_is_and_a_wrong_word_shows_usage(live):
    from test_live import type_cmd
    app, srv, win, s = live
    type_cmd(win, "/dcc ignore")
    type_cmd(win, "/dcc ignore maybe")
    text = [l.text for b in s.all_buffers() for l in b.lines]
    assert any(t.startswith("DCC ignore is on: these file types are ignored: *.exe *.com") for t in text)
    assert "Usage: DCC IGNORE [on|off|accept|ignore]" in text
    assert win.cfg.dcc_ignore_on is True and win.cfg.dcc_ignore_mode == "ignore"


# --- 8 and 9. direct chat: long lines, older encodings ----------------------------------------------------------------

def _chat(app, srv, win, s):
    win.cfg.dcc_ip = "127.0.0.1"
    t = win.dcc.start_chat(s, "Belon")
    c = socket.create_connection(("127.0.0.1", t.port))
    assert wait(app, lambda: "=belon" in s.buffers and t.state == "active")
    return t, c, s.buffers["=belon"]


def test_chat_line_without_end_is_cut_at_16kb(live):
    app, srv, win, s = live
    t, c, q = _chat(app, srv, win, s)
    c.sendall(b"x" * 40000)
    assert wait(app, lambda: any(l.text.startswith("xxx") for l in q.lines))
    assert len(t._rx) <= 16 * 1024
    c.sendall(b"y" * 30000)                       # still the same line: dropped
    c.sendall(b"zz\nnext line\n")
    assert wait(app, lambda: any(l.text == "next line" for l in q.lines))
    texts = [l.text for l in q.lines if l.left == "Belon"]
    assert texts == ["x" * 16384, "next line"], [x[:20] + f"...({len(x)})" for x in texts]
    assert t._rx == b"" and t.state == "active"
    # a whole line that is too long arrives at once: cut too
    c.sendall(b"w" * 20000 + b"\nafter\n")
    assert wait(app, lambda: any(l.text == "after" for l in q.lines))
    assert max(len(l.text) for l in q.lines) <= 16384
    c.close()


def test_chat_line_in_windows_1252_shows_its_letters(live):
    app, srv, win, s = live
    t, c, q = _chat(app, srv, win, s)
    c.sendall(b"caf\xe9 cr\xe8me \x80 5\r\n")
    c.sendall("utf-8 still works: café\n".encode("utf-8"))
    assert wait(app, lambda: any(l.text.startswith("utf-8") for l in q.lines))
    texts = [l.text for l in q.lines if l.left == "Belon"]
    assert texts == ["café crème € 5", "utf-8 still works: café"]
    assert not any("�" in x for x in texts)
    c.close()


def test_decode_line_rules():
    assert decode_line(b"plain") == "plain"
    assert decode_line("é€".encode()) == "é€"
    assert decode_line(b"caf\xe9") == "café"                      # not a cut UTF-8 letter
    assert decode_line("ab€".encode()[:-1], cut=True) == "ab"      # a line cut at 16 KB mid-letter


# --- 10. a name that is taken gets ' (1)' before the ending -----------------------------------------------------------

def test_unique_name_keeps_the_ending(tmp_path):
    assert _unique_name(tmp_path / "a.txt") == tmp_path / "a.txt"
    (tmp_path / "a.txt").write_text("1")
    assert _unique_name(tmp_path / "a.txt") == tmp_path / "a (1).txt"
    (tmp_path / "a (1).txt").write_text("2")
    assert _unique_name(tmp_path / "a.txt") == tmp_path / "a (2).txt"
    (tmp_path / "README").write_text("r")
    assert _unique_name(tmp_path / "README") == tmp_path / "README (1)"
    (tmp_path / "x.tar.bin").write_text("t")
    assert _unique_name(tmp_path / "x.tar.bin") == tmp_path / "x.tar (1).bin"


def test_receive_over_an_existing_file_saves_name_1_ext(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_dir = str(tmp_path)
    (tmp_path / "notes.txt").write_text("keep me")
    port, _ = _sender(b"new notes")
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND notes.txt {LOCAL} {port} 9\x01")
    assert wait(app, lambda: win.dcc.items)
    t = win.dcc.items[0]
    win.dcc.on_exists = None                     # nobody to ask: both files are kept
    win.dcc.accept(t)
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
    assert t.name == "notes (1).txt" and Path(t.path) == tmp_path / "notes (1).txt"
    assert (tmp_path / "notes (1).txt").read_bytes() == b"new notes"
    assert (tmp_path / "notes.txt").read_text() == "keep me"
    assert not (tmp_path / "notes.txt.1").exists()


# --- the file is already there: Overwrite / Resume / Rename / Cancel ------------------------------------------------

def _offer_onto(app, srv, win, tmp_path, old: bytes, payload: bytes, name="notes.txt"):
    """Their offer of name, with old already in the folder. Returns the transfer, the sender and what was asked."""
    win.cfg.dcc_dir = str(tmp_path)
    win.cfg.dcc_open_recv = False
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_bytes(old)
    asked = []
    win.dcc.on_exists = lambda t, free: asked.append((t, free))
    port, got = _sender(payload)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND {name} {LOCAL} {port} {len(payload)}\x01")
    assert wait(app, lambda: win.dcc.items)
    return win.dcc.items[0], port, got, asked


def test_file_exists_asks_first_and_starts_nothing(live, tmp_path):
    app, srv, win, s = live
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, b"old", b"new notes")
    (tmp_path / "notes (1).txt").write_bytes(b"taken too")
    win.dcc.accept(t)
    assert asked == [(t, "notes (2).txt")]        # Rename starts with the first free name
    for _ in range(20):
        app.processEvents()
        time.sleep(0.005)
    assert t.state == "queued" and t.sock is None and t.name == "notes.txt"
    assert (tmp_path / "notes.txt").read_bytes() == b"old"
    t.abort()


def test_file_exists_overwrite_gets_the_whole_file_again(live, tmp_path):
    app, srv, win, s = live
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, b"an older and longer file", b"new notes")
    win.dcc.accept(t)
    win.dcc.accept(t, "overwrite")
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
    assert t.name == "notes.txt" and (tmp_path / "notes.txt").read_bytes() == b"new notes"
    assert not (tmp_path / "notes (1).txt").exists()


def test_file_exists_resume_asks_them_for_the_rest(live, tmp_path):
    app, srv, win, s = live
    payload = b"0123456789abcdef"
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, payload[:6], payload)
    win.dcc.accept(t)
    win.dcc.accept(t, "resume")
    assert wait(app, lambda: any(f"DCC RESUME notes.txt {port} 6" in x for x in srv.received)), \
        [x for x in srv.received if "DCC" in x]
    assert t.state == "queued"
    got["start"] = 6
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC ACCEPT notes.txt {port} 6\x01")
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
    assert (tmp_path / "notes.txt").read_bytes() == payload and t.name == "notes.txt"


def test_file_exists_resume_needs_a_shorter_file(live, tmp_path):
    app, srv, win, s = live
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, b"as long or longer", b"short")
    assert not win.dcc.can_resume(t)
    win.dcc.accept(t, "resume")
    assert t.state == "queued" and not any("DCC RESUME" in x for x in srv.received)
    assert (tmp_path / "notes.txt").read_bytes() == b"as long or longer"
    t.abort()


def test_file_exists_rename_saves_under_the_new_name(live, tmp_path):
    app, srv, win, s = live
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, b"old", b"new notes")
    (tmp_path / "mine.txt").write_bytes(b"also taken")
    win.dcc.accept(t)
    win.dcc.accept(t, "rename", "mine.txt")       # a taken name: never overwritten either
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
    assert t.name == "mine (1).txt" and (tmp_path / "mine (1).txt").read_bytes() == b"new notes"
    assert (tmp_path / "notes.txt").read_bytes() == b"old" and (tmp_path / "mine.txt").read_bytes() == b"also taken"


def test_file_exists_rename_cannot_leave_the_folder(live, tmp_path):
    app, srv, win, s = live
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path / "in", b"old", b"new notes")
    win.dcc.accept(t, "rename", "..\\..\\out.txt")
    assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
    assert Path(t.path).parent == tmp_path / "in"
    assert not (tmp_path / "out.txt").exists()


def test_file_exists_cancel_starts_nothing(live, tmp_path):
    app, srv, win, s = live
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, b"old", b"new notes")
    win.dcc.accept(t)
    win.dcc.accept(t, "cancel")
    for _ in range(20):
        app.processEvents()
        time.sleep(0.005)
    assert t.state == "queued" and t.sock is None
    assert (tmp_path / "notes.txt").read_bytes() == b"old" and not (tmp_path / "notes (1).txt").exists()
    t.abort()


@pytest.mark.parametrize("choice", ["ask", "resume", "overwrite"])
def test_auto_accept_onto_an_existing_file_follows_the_setting(live, tmp_path, choice):
    app, srv, win, s = live
    win.cfg.dcc_auto = 1
    win.cfg.dcc_exists = choice
    payload = b"0123456789"
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, payload[:4], payload)
    if choice == "ask":
        assert wait(app, lambda: asked) and asked[0][0] is t
        assert t.state == "queued" and (tmp_path / "notes.txt").read_bytes() == payload[:4]
        t.abort()
    elif choice == "resume":
        assert wait(app, lambda: any(f"DCC RESUME notes.txt {port} 4" in x for x in srv.received))
        assert not asked
        t.abort()
    else:
        assert wait(app, lambda: t.state == "done", 5000), (t.state, t.error)
        assert not asked and (tmp_path / "notes.txt").read_bytes() == payload


def test_auto_accept_resume_setting_asks_when_it_cannot_resume(live, tmp_path):
    app, srv, win, s = live
    win.cfg.dcc_auto = 1
    win.cfg.dcc_exists = "resume"
    t, port, got, asked = _offer_onto(app, srv, win, tmp_path, b"longer than the offer", b"short")
    assert wait(app, lambda: asked)
    assert t.state == "queued" and (tmp_path / "notes.txt").read_bytes() == b"longer than the offer"
    t.abort()
