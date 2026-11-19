"""0.8.1: a channel the server won't let us back into must not keep its old nick list (ZNC + an oper-only channel
after a server restart showed us, as op, in a channel we weren't in)."""
import time
from datetime import datetime, timezone

from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import parse_line
from bchat.session import Session

ZNC = "*status!znc@znc.in"


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def inside(app):
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)]), Config(nick="Fhazal"))
    s.nick = "Fhazal"
    feed(s, ":Fhazal!u@h JOIN #opers", ":srv 353 Fhazal = #opers :@Fhazal @Belon @ChanServ J|wang",
         ":srv 366 Fhazal #opers :End of /NAMES list.")
    b = s.buffers[s.fold("#opers")]
    assert b.joined and len(b.users) == 4
    return s, b


def test_znc_lost_server_lines_change_nothing_live_or_mid_playback(app):
    # 0.8.5: a bouncer is a normal server; ZNC losing IRC is ZNC's business, the tab stays as it is
    for collect in (False, True):
        s, b = inside(app)
        if collect:
            s._znc_collect = ("#opers", [], time.time())
        feed(s, f":{ZNC} PRIVMSG Fhazal :Disconnected from IRC. Reconnecting...",
             f":{ZNC} PRIVMSG Fhazal :IRC connection timed out.  Reconnecting...")
        assert b.joined and len(b.users) == 4


def test_oper_only_refusal_empties_a_stale_tab(app):
    s, b = inside(app)
    feed(s, ":srv 520 Fhazal #opers :Cannot join channel (+O)")
    assert not b.joined and not b.users
    assert any("server refused the join" in ln.text for ln in b.lines)
    assert any("Cannot join channel (+O)" in ln.text for x in s.all_buffers() for ln in x.lines)   # still says why


def test_every_join_refusal_empties_the_tab_and_still_says_why(app):
    for n in (471, 473, 474, 475, 477, 489, 520):     # not 405: see test_083
        s, b = inside(app)
        feed(s, f":srv {n} Fhazal #opers :Cannot join channel")
        assert not b.joined and not b.users, n


def test_refusal_for_a_channel_without_a_tab_opens_none(app):
    s, _b = inside(app)
    feed(s, ":srv 520 Fhazal #secret :Cannot join channel (+O)")
    assert s.fold("#secret") not in s.buffers


def test_after_the_refusal_a_real_join_fills_it_again(app):
    s, b = inside(app)
    feed(s, ":srv 520 Fhazal #opers :Cannot join channel (+O)",
         ":Fhazal!u@h JOIN #opers", ":srv 353 Fhazal = #opers :@Fhazal @Belon", ":srv 366 Fhazal #opers :End")
    assert b.joined and sorted(u.nick for u in b.users.values()) == ["Belon", "Fhazal"]
