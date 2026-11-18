"""0.8.3: through ZNC at the server's channel limit, BChat's own autojoin got 'too many channels' (405) back for
channels the bouncer had already put us in, and the 0.8.1 refusal rule then emptied those tabs (in #kampung, shown
outside). 405 is about us, not the channel; and channels a bouncer already joined us to aren't asked for again."""
import time

from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import parse_line
from bchat.session import Session


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def make(app, **net):
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)], **net), Config(nick="Belon", local_find=False))
    s.out = []
    s.send_raw = lambda line, secret=False, quiet=False: s.out.append(line)
    s._connect_next = lambda: None
    s._conn_gen += 1
    s._last_rx = time.time()
    s.want_connected = True
    s.state = "connected"
    s.nick = "Belon"
    return s


def joined(s, chan):
    feed(s, f":Belon!u@h JOIN {chan}", f":srv 353 Belon = {chan} :@Belon Ali", f":srv 366 Belon {chan} :End")


def joins(s):
    return [l for l in s.out if l.upper().startswith("JOIN")]


def test_too_many_channels_does_not_empty_a_channel_we_are_in(app):
    s = make(app)
    joined(s, "#kampung")
    b = s.buffers[s.fold("#kampung")]
    feed(s, ":srv 405 Belon #kampung :You have joined too many channels")
    assert b.joined and len(b.users) == 2
    assert not any("server refused the join" in ln.text for ln in b.lines)
    assert any("too many channels" in ln.text for x in s.all_buffers() for ln in x.lines)   # still said once


def test_channels_the_bouncer_already_joined_are_not_asked_for_again(app):
    s = make(app, autojoin="#skinhead,#kampung,#Penang")
    joined(s, "#skinhead")
    joined(s, "#KAMPUNG")                          # case differs: still the same channel
    s._join_all(s._conn_gen)
    assert joins(s) == ["JOIN #Penang"]


def test_all_already_joined_sends_no_join(app):
    s = make(app, autojoin="#a,#b")
    joined(s, "#a")
    joined(s, "#b")
    s._join_all(s._conn_gen)
    assert joins(s) == []


def test_plain_server_still_joins_everything_and_keys_line_up(app):
    s = make(app, autojoin="#a,#secret,#c,#k2 key1,key2")    # #a has key1, #secret key2 (keys go from the front)
    joined(s, "#a")
    s._join_all(s._conn_gen)
    assert joins(s) == ["JOIN #secret,#c,#k2 key2"]


def test_open_tabs_not_in_autojoin_rejoin_unless_already_in(app):
    s = make(app, autojoin="#a")
    joined(s, "#extra")
    joined(s, "#other")
    s.buffers[s.fold("#other")].joined = False      # the link dropped: no longer inside
    s._join_all(s._conn_gen)
    assert sorted(joins(s)) == ["JOIN #a", "JOIN #other"]
