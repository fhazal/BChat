"""0.8.6: BChat against a REAL ZNC bouncer (not a fake), with tests/qa_ircd.py as the IRC server behind it.

ZNC comes from a per-user Cygwin install (E:\\cygwin64-bchat, package znc; see the skip reason below). Every test
starts its own qa_ircd on 127.0.0.1 and its own ZNC with a znc.conf written here (one user, one network pointing at
that qa_ircd), in the test's tmp folder, on a free 127.0.0.1 port. BChat runs from source with throwaway settings
(test_live.make_win) and logs in with PASS user/network:password. Nothing here talks to a real IRC server.

Run by hand:  python -m pytest tests/test_086_znc.py -v
"""
import hashlib
import os
import re
import socket
import subprocess
import time
from pathlib import Path

import pytest

ZNC_EXE = Path(os.environ.get("BCHAT_ZNC_EXE", r"E:\cygwin64-bchat\bin\znc.exe"))
if not ZNC_EXE.exists():
    pytest.skip(f"no real ZNC here ({ZNC_EXE} is missing): install Cygwin per user with the znc package "
                r"(setup-x86_64.exe -q -B -n -N -d -R E:\cygwin64-bchat -P znc)", allow_module_level=True)

from PySide6.QtWidgets import QTreeWidgetItemIterator   # noqa: E402
from qa_ircd import IrcTestClient, Msg, QaIrcd, lower   # noqa: E402
from test_live import make_win, type_cmd, wait          # noqa: E402

from bchat.session import QUERY                         # noqa: E402

USER, NETWORK, ZPASS = "qauser", "qanet", "zncpass-test-only"
LOGIN = f"{USER}/{NETWORK}:{ZPASS}"
NICK = "Badaboom"                     # test_live.make_win's nick; ZNC's user has the same one


def cyg(p: Path) -> str:
    """C:\\x\\y -> /cygdrive/c/x/y, the path form a Cygwin program reads without warnings."""
    p = Path(p).resolve()
    return "/cygdrive/" + p.drive[0].lower() + p.as_posix()[2:]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Znc:
    """One real ZNC process: own data folder, own znc.conf, foreground (-f) with debug output (-D) to znc.log."""

    def __init__(self, base: Path, upstream_port: int, channels=("#skinhead",)):
        self.base = base
        self.port = free_port()
        (base / "configs").mkdir(parents=True)
        salt = "qa-salt-not-secret-0"
        digest = hashlib.sha256((ZPASS + salt).encode()).hexdigest()   # ZNC's salted sha256: sha256(pass + salt)
        chans = "".join(f"\t\t<Chan {c}>\n\t\t</Chan>\n" for c in channels)
        (base / "configs" / "znc.conf").write_text(
            "Version = 1.10.3\n"
            "ConnectDelay = 1\n"          # retry the IRC server quickly (defaults: 5 s delay, 30 s throttle)
            "ServerThrottle = 1\n"
            "<Listener l>\n\tAllowIRC = true\n\tAllowWeb = false\n\tHost = 127.0.0.1\n\tIPv4 = true\n\tIPv6 = false\n"
            f"\tPort = {self.port}\n\tSSL = false\n</Listener>\n"
            f"<User {USER}>\n\tAdmin = true\n\tNick = {NICK}\n\tAltNick = {NICK}_\n\tIdent = bee\n\tRealName = QA\n"
            "\tBuffer = 100\n\tMultiClients = true\n"
            f"\t<Pass password>\n\t\tMethod = sha256\n\t\tHash = {digest}\n\t\tSalt = {salt}\n\t</Pass>\n"
            f"\t<Network {NETWORK}>\n\t\tServer = 127.0.0.1 {upstream_port}\n{chans}\t</Network>\n</User>\n",
            encoding="utf-8")
        self.log_path = base / "znc.log"
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen([str(ZNC_EXE), "-f", "-D", "-d", cyg(base)], stdout=self._log,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     env=dict(os.environ, HOME=cyg(base)),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        end = time.time() + 20
        while True:
            assert self.proc.poll() is None, f"ZNC exited at start:\n{self.log()}"
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                break
            except OSError:
                assert time.time() < end, f"ZNC never listened on {self.port}:\n{self.log()}"
                time.sleep(0.1)

    def log(self, tail: int = 4000) -> str:
        self._log.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")[-tail:]

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        self._log.close()


class KeyIrcd(QaIrcd):
    """qa_ircd plus what ZNC relies on and qa_ircd leaves out: channel keys (+k) are kept and checked on JOIN (475),
    and MODE #chan (324) tells members the key, as real ircds do. ZNC learns and keeps keys from that 324.
    limit: a channel limit; a JOIN past it gets 405 'You have joined too many channels' (the 0.8.3 case)."""
    limit = None

    def chan_keys(self) -> dict:
        return self.__dict__.setdefault("_chan_keys", {})

    def apply_mode(self, chan, modes, *args, by=""):
        argv, sign = list(args), "+"
        for x in modes:
            if x in "+-":
                sign = x
            elif x in "ovb":
                argv and argv.pop(0)
            elif x == "k":
                key = argv.pop(0) if argv else ""
                if sign == "+":
                    self.chan_keys()[lower(chan)] = key
                else:
                    self.chan_keys().pop(lower(chan), None)
        super().apply_mode(chan, modes, *args, by=by)

    def _cmd_MODE(self, c, m):
        ch = self.channels.get(lower(m.param(0)))
        key = self.chan_keys().get(lower(m.param(0)))
        if ch is not None and len(m.params) == 1 and key and "k" in ch.modes:
            return self._num(c, "324", ch.name, "+" + "".join(sorted(ch.modes)), key)
        return super()._cmd_MODE(c, m)

    def _cmd_JOIN(self, c, m):
        if m.param(0) == "0":
            return super()._cmd_JOIN(c, m)
        keys = m.param(1).split(",") if len(m.params) > 1 else []
        for i, name in enumerate(m.param(0).split(",")):
            given = keys[i] if i < len(keys) else ""
            inside = lower(name) in c.channels
            if not inside and self.limit is not None and name.startswith("#") and len(c.channels) >= self.limit:
                self._num(c, "405", name, "You have joined too many channels")
                continue
            want = self.chan_keys().get(lower(name))
            if not inside and want and given != want:
                self._num(c, "475", name, "Cannot join channel (+k)")
                continue
            super()._cmd_JOIN(c, Msg(m.tags, m.prefix, m.command, [name]))


class LimitIrcd(KeyIrcd):
    limit = 2


def join_rx(chan: str, key: str | None = None) -> str:
    """A JOIN line for chan, also inside ZNC's comma lists ('JOIN #a,#b key')."""
    rx = rf"(?i)^JOIN (\S+,)?{re.escape(chan)}(,\S*)?"
    return rx + (rf" (\S*,)*{re.escape(key)}(,|$)" if key else r"( |$)")


def pexpect(app, peer, pattern, since=0, timeout=10.0) -> str:
    """peer.expect while Qt runs (BChat lives on this thread: without pumping it can't send)."""
    end = time.time() + timeout
    while True:
        try:
            return peer.expect(pattern, since=since, timeout=0.02)
        except TimeoutError:
            if time.time() > end:
                raise
            app.processEvents()


@pytest.fixture
def rig(app, tmp_path):
    """qa_ircd + Peer (a plain IRC user on it, op in #skinhead, topic set) + real ZNC, ZNC already in #skinhead."""
    made = {"wins": [], "clients": []}

    def build(srv_cls=KeyIrcd, channels=("#skinhead",), peer_channels=("#skinhead",)):
        srv = srv_cls(clock=time.time, cert_dir=tmp_path / "certs")
        made["srv"] = srv
        peer = IrcTestClient("127.0.0.1", srv.port).register("Peer")
        made["clients"].append(peer)
        for ch in peer_channels:
            mk = peer.mark()
            peer.send(f"JOIN {ch}")
            peer.expect(rf" 366 Peer {ch} ", since=mk)
        if "#skinhead" in peer_channels:
            peer.send("TOPIC #skinhead :Real ZNC test topic")
            peer.expect("TOPIC #skinhead", since=0)
        znc = Znc(tmp_path / "znc", srv.port, channels)
        made["znc"] = znc
        for ch in channels:
            srv.wait_for(join_rx(ch), nick=NICK, timeout=20)
        return srv, peer, znc

    def window(autojoin="#skinhead"):
        win, net = make_win(tmp_path / "bchat", made["znc"].port, password=LOGIN)
        net.autojoin = autojoin
        made["wins"].append(win)
        return win, net

    yield build, window
    for win in made["wins"]:
        win.close()
        app.processEvents()
    for c in made["clients"]:
        c.close()
    if "znc" in made:
        made["znc"].stop()
        assert made["znc"].proc.poll() is not None, "ZNC is still running after the test"
    if "srv" in made:
        made["srv"].stop()


def outgoing(s) -> list:
    sent = []
    s.raw_line.connect(lambda text, out: sent.append(text) if out else None)
    return sent


def joins(sent) -> list:
    return [x for x in sent if x.upper().startswith("JOIN")]


def tree_names(win) -> list:
    it, names = QTreeWidgetItemIterator(win.tree), []
    while it.value():
        names.append(it.value().text(0))
        it += 1
    return names


def texts(b) -> list:
    return [ln.text for ln in b.lines]


def connect(app, win, net, chans=("#skinhead",)):
    s = win.connect_network(net)
    ok = wait(app, lambda: s.state == "connected" and all(
        s.fold(c) in s.buffers and s.buffers[s.fold(c)].joined and s.buffers[s.fold(c)].users for c in chans), 15000)
    assert ok, (s.state, [ln.text for ln in s.server_buffer.lines][-15:])
    return s


# --- connect, auto-join, names, topic, bouncer found -------------------------------------------------------------

def test_connect_autojoin_names_and_topic(app, rig):
    build, window = rig
    srv, peer, znc = build()
    win, net = window()
    sent = outgoing(win.session_for(net))
    s = connect(app, win, net)
    b = s.buffers[s.fold("#skinhead")]
    assert {u.nick for u in b.users.values()} == {NICK, "Peer"}
    assert "@" in b.users[s.fold("Peer")].prefixes
    assert wait(app, lambda: b.topic == "Real ZNC test topic", 5000), b.topic
    assert any(x.startswith("PASS ") for x in sent)                           # the login went as PASS
    assert wait(app, lambda: s.bouncer == "ZNC" and s.bouncer_version.startswith("1.10"), 8000), (s.bouncer, s.bouncer_version)
    assert wait(app, lambda: any("Connected through ZNC" in t for t in texts(s.server_buffer)), 5000)
    time.sleep(1.5)                                                           # BChat's joins wait 1 s: let them go
    app.processEvents()
    assert joins(sent) == [], "ZNC already had us in #skinhead: BChat must not ask again (0.8.3)"
    assert tree_names(win).count("#skinhead") == 1


def test_autojoin_a_channel_znc_does_not_have_goes_through(app, rig):
    build, window = rig
    srv, peer, znc = build()
    win, net = window(autojoin="#skinhead,#fresh")
    sent = outgoing(win.session_for(net))
    s = connect(app, win, net, ("#skinhead", "#fresh"))
    assert joins(sent) == ["JOIN #fresh"]
    assert NICK.lower() in srv.channels["#fresh"].members


# --- messages both ways -------------------------------------------------------------------------------------------

def test_messages_both_ways(app, rig):
    build, window = rig
    srv, peer, znc = build()
    win, net = window()
    s = connect(app, win, net)
    b = s.buffers[s.fold("#skinhead")]
    win.select_buffer(b)
    mk = peer.mark()
    type_cmd(win, "hello from bchat through znc")
    pexpect(app, peer, rf"^:{NICK}!\S+ PRIVMSG #skinhead :hello from bchat through znc", since=mk)
    peer.send("PRIVMSG #skinhead :hello back from peer")
    assert wait(app, lambda: any("hello back from peer" in t for t in texts(b)), 5000)
    peer.send(f"PRIVMSG {NICK} :a private hello")
    assert wait(app, lambda: s.fold("Peer") in s.buffers and
                any("a private hello" in t for t in texts(s.buffers[s.fold("Peer")])), 5000)
    assert s.buffers[s.fold("Peer")].kind == QUERY
    mk = peer.mark()
    win.select_buffer(s.buffers[s.fold("Peer")])
    type_cmd(win, "private reply")
    pexpect(app, peer, rf"^:{NICK}!\S+ PRIVMSG Peer :private reply", since=mk)


# --- playback after reconnecting to ZNC: no alerts, sane times --------------------------------------------------

def test_playback_makes_no_alerts_and_keeps_the_times_it_was_said(app, rig):
    build, window = rig
    srv, peer, znc = build()
    win, net = window()
    s = connect(app, win, net)
    b = s.buffers[s.fold("#skinhead")]
    s.disconnect_from_network()
    assert wait(app, lambda: s.state == "disconnected", 5000)
    time.sleep(0.5)                                                       # ZNC has seen us go
    said_at = time.time()
    peer.send("PRIVMSG #skinhead :while you were away")
    peer.send(f"PRIVMSG #skinhead :{NICK}: are you there?")                  # a highlight, normally an alert
    peer.send(f"PRIVMSG {NICK} :private while away")                        # a private message, normally an alert
    peer.send("PRIVMSG #skinhead :last one before you came back")
    srv.wait_for("last one before you came back", nick="Peer", timeout=5)
    time.sleep(2.5)                                                       # so 'now' and 'when it was said' differ
    alerts, notes = [], []
    s.alert.connect(lambda buf: alerts.append(buf.name))
    s.notify.connect(lambda buf, kind: notes.append((buf.name, kind)))
    back_at = time.time()
    s.connect_to_network()
    assert wait(app, lambda: any("last one before you came back" in t for t in texts(b))
                and s.fold("Peer") in s.buffers
                and any("private while away" in t for t in texts(s.buffers[s.fold("Peer")])), 15000), \
        (texts(b)[-10:], znc.log())
    q = s.buffers[s.fold("Peer")]
    assert wait(app, lambda: any("Now live" in t for t in texts(b)) and any("Now live" in t for t in texts(q)), 5000), \
        (texts(b)[-10:], texts(q))
    assert any("Played back by ZNC" in t for t in texts(b)), texts(b)[-10:]
    assert alerts == [], alerts
    assert not [n for n in notes if n[1] in ("chan", "priv", "hilight", "notice")], notes
    # the times are the ones the lines were said at (ZNC's server-time), not the moment of the playback
    for want in ("while you were away", "are you there?", "last one before you came back"):
        ln = next(ln for ln in b.lines if want in ln.text)
        assert said_at - 1 <= ln.ts <= said_at + 2, (want, ln.ts, said_at)
        assert ln.ts < back_at - 1, (want, ln.ts, back_at)
    ln = next(ln for ln in q.lines if "private while away" in ln.text)
    assert said_at - 1 <= ln.ts <= said_at + 2 and ln.ts < back_at - 1, (ln.ts, said_at)
    # no line of the playback shows twice
    assert sum("while you were away" in t for t in texts(b)) == 1
    # live lines after the playback still alert (the check above is not just a dead signal)
    peer.send(f"PRIVMSG #skinhead :{NICK}: live highlight")
    assert wait(app, lambda: any("live highlight" in t for t in texts(b)), 5000)
    assert wait(app, lambda: ("#skinhead", "hilight") in notes or alerts, 3000), (notes, alerts)
    ln = next(ln for ln in b.lines if "live highlight" in ln.text)
    assert abs(ln.ts - time.time()) < 5


# --- the IRC server behind ZNC goes down while BChat stays connected to ZNC -------------------------------------

def test_upstream_down_and_back_keeps_channels_and_sends_no_rejoins(app, rig):
    build, window = rig
    srv, peer, znc = build()
    win, net = window()
    s = connect(app, win, net)
    b = s.buffers[s.fold("#skinhead")]
    time.sleep(1.5)
    app.processEvents()
    sent = outgoing(s)
    users_before = {u.nick for u in b.users.values()}
    srv.refuse = "reset"                       # new connections from ZNC are reset: the server is 'down'
    mk = srv.mark()
    srv.drop(NICK)                             # ZNC's link to the server breaks (TCP reset)
    # ZNC tells BChat on *status; BChat stays connected to ZNC and must not act on those lines
    assert wait(app, lambda: s.fold("*status") in s.buffers and
                any("isconnected" in t for t in texts(s.buffers[s.fold("*status")])), 10000), \
        ([(x.name, texts(x)[-3:]) for x in s.all_buffers()], znc.log())
    srv.wait_for("", kind="refused", since=mk, timeout=10, pump=app.processEvents)            # ZNC is retrying
    t_end = time.time() + 6
    while time.time() < t_end:                                          # several of ZNC's retries go by
        app.processEvents()
        time.sleep(0.02)
    assert s.state == "connected"
    assert b.joined, "BChat greyed #skinhead from a *status line (removed in 0.8.6 on purpose)"
    assert {u.nick for u in b.users.values()} == users_before, "the name list was emptied from *status lines"
    assert joins(sent) == [], f"BChat sent joins while the server was down: {joins(sent)}"
    assert tree_names(win).count("#skinhead") == 1
    # the server comes back: ZNC reconnects and rejoins by itself
    mk = srv.mark()
    srv.refuse = ""
    srv.wait_for(join_rx("#skinhead"), nick=NICK, since=mk, timeout=20, pump=app.processEvents)
    time.sleep(1.5)
    app.processEvents()
    assert wait(app, lambda: b.joined and {u.nick for u in b.users.values()} == {NICK, "Peer"}, 8000), \
        (b.joined, list(b.users))
    assert joins(sent) == [], f"BChat sent joins of its own: {joins(sent)}"
    assert s.state == "connected" and tree_names(win).count("#skinhead") == 1
    win.select_buffer(b)
    pm = peer.mark()
    type_cmd(win, "usable again")
    pexpect(app, peer, rf"^:{NICK}!\S+ PRIVMSG #skinhead :usable again", since=pm)
    peer.send("PRIVMSG #skinhead :welcome back")
    assert wait(app, lambda: any("welcome back" in t for t in texts(b)), 5000)
    srcs = srv.received(NICK)
    assert sum(1 for x in srcs if re.search(join_rx("#skinhead"), x)) == 2, srcs    # first connect + one rejoin


# --- /znc and the *status query ---------------------------------------------------------------------------------------

def test_znc_command_goes_to_status_and_the_status_query_works(app, rig):
    build, window = rig
    srv, peer, znc = build()
    win, net = window()
    s = connect(app, win, net)
    sent = outgoing(s)
    win.select_buffer(s.buffers[s.fold("#skinhead")])
    type_cmd(win, "/znc listnetworks")
    assert wait(app, lambda: any(x.upper().startswith("ZNC LISTNETWORKS") for x in sent), 3000), sent
    assert wait(app, lambda: s.fold("*status") in s.buffers and
                any(NETWORK in t for t in texts(s.buffers[s.fold("*status")])), 8000), \
        [(x.name, texts(x)[-3:]) for x in s.all_buffers()]
    st = s.buffers[s.fold("*status")]
    assert st.kind == QUERY
    assert not any("listnetworks" in x.lower() for x in srv.received(NICK)), "the /znc command leaked upstream"
    n = len(st.lines)
    win.select_buffer(st)
    type_cmd(win, "version")
    assert wait(app, lambda: any(re.fullmatch(r"PRIVMSG \*status :?version", x) for x in sent), 3000), sent
    assert wait(app, lambda: any("ZNC 1.10" in t for t in texts(st)[n:]), 8000), texts(st)
    assert not any("PRIVMSG *status" in x for x in srv.received(NICK))
    assert tree_names(win).count("*status") == 1


# --- BChat itself disconnects and reconnects: no duplicate tabs, keys kept ----------------------------------------

def test_bchat_reconnect_makes_no_duplicate_tabs_and_keeps_keys(app, rig):
    build, window = rig
    srv, peer, znc = build(peer_channels=("#skinhead", "#locked"))
    peer.send("MODE #locked +k sekrit")
    srv.wait_handled("MODE #locked", nick="Peer", timeout=5)
    win, net = window(autojoin="#locked,#skinhead sekrit")                 # #locked gets the key (keys go from the front)
    sent = outgoing(win.session_for(net))
    s = connect(app, win, net, ("#skinhead", "#locked"))
    assert joins(sent) == ["JOIN #locked sekrit"], joins(sent)             # #skinhead: ZNC already had it
    lk = s.buffers[s.fold("#locked")]
    assert lk.key == "sekrit"
    names_before = sorted(tree_names(win))
    bufs_before = sorted(s.buffers)
    for round_ in range(2):
        s.disconnect_from_network()
        assert wait(app, lambda: s.state == "disconnected", 5000)
        assert not lk.joined                                               # our own disconnect greys, as on any server
        del sent[:]
        s.connect_to_network()
        assert wait(app, lambda: s.state == "connected" and lk.joined and lk.users
                    and s.buffers[s.fold("#skinhead")].joined, 15000), round_
        time.sleep(1.5)                                                    # past BChat's own join wait
        app.processEvents()
        assert joins(sent) == [], (round_, joins(sent))                    # ZNC put us back: nothing asked again
        assert sorted(tree_names(win)) == names_before, (round_, tree_names(win))
        assert sorted(s.buffers) == bufs_before, (round_, sorted(s.buffers))
        assert lk.key == "sekrit", round_
        assert {u.nick for u in lk.users.values()} == {NICK, "Peer"}
    # ZNC learnt the key: after a server outage it rejoins with it (KeyIrcd refuses a JOIN without it)
    mk = srv.mark()
    srv.drop(NICK)
    try:
        srv.wait_for(join_rx("#locked", "sekrit"), nick=NICK, since=mk, timeout=20, pump=app.processEvents)
    except TimeoutError:
        raise AssertionError(("ZNC rejoined #locked without its key", [x for x in srv.received(NICK) if
                                                                       x.upper().startswith("JOIN")]))
    assert wait(app, lambda: lower(NICK) in srv.channels["#locked"].members and lk.joined
                and {u.nick for u in lk.users.values()} == {NICK, "Peer"}, 10000), (lk.joined, list(lk.users))
    assert lk.key == "sekrit" and tree_names(win).count("#locked") == 1


# --- 0.8.3: the server's channel limit ('too many channels', 405) -------------------------------------------------

def test_too_many_channels_through_znc_keeps_joined_tabs(app, rig):
    build, window = rig
    srv, peer, znc = build(srv_cls=LimitIrcd, channels=("#skinhead", "#kampung"), peer_channels=("#skinhead", "#kampung"))
    win, net = window(autojoin="#skinhead,#kampung,#third")
    sent = outgoing(win.session_for(net))
    s = connect(app, win, net, ("#skinhead", "#kampung"))
    # ZNC's flood control queues the JOIN behind its own after-connect lines (about one line per 2 s): ~10 s
    assert wait(app, lambda: any("too many channels" in t for x in s.all_buffers() for t in texts(x)), 30000), \
        ([(x.name, texts(x)[-3:]) for x in s.all_buffers()], joins(sent),
         [f"{e.kind} {e.line}" for e in srv.events if "third" in e.line.lower() or " 405 " in e.line])
    assert joins(sent) == ["JOIN #third"], joins(sent)                     # not the two ZNC already joined
    for c in ("#skinhead", "#kampung"):
        b = s.buffers[s.fold(c)]
        assert b.joined and {u.nick for u in b.users.values()} == {NICK, "Peer"}, c
        assert not any("server refused the join" in t for t in texts(b)), c
    third = s.buffers.get(s.fold("#third"))
    assert third is None or not third.joined
    time.sleep(2)
    app.processEvents()
    assert joins(sent) == ["JOIN #third"], "BChat retried the refused join"
