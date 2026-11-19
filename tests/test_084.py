"""0.8.4: a real ZNC (1.7+) sends *status lines as *status!status@znc.in, not !znc@znc.in. 0.8.1 only took the
old form, so when the bouncer lost the IRC server the channels kept everyone, ourselves included."""
from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import parse_line
from bchat.session import Session

REAL = "*status!status@znc.in"          # ZNC 1.10 Client.cpp PutModule
OLD = "*status!znc@znc.in"              # ZNC 1.6 and older


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def inside():
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)]), Config(nick="Fhazal"))
    s.nick = "Fhazal"
    for ch in ("#skinhead", "#chat"):
        feed(s, f":Fhazal!u@h JOIN {ch}", f":srv 353 Fhazal = {ch} :Fhazal Psycho Bombus",
             f":srv 366 Fhazal {ch} :End of /NAMES list.")
    return s, [s.buffers[s.fold(c)] for c in ("#skinhead", "#chat")]


def test_rejoin_after_the_server_comes_back_shows_only_who_is_there(app):
    s, bufs = inside()
    feed(s, f":{REAL} PRIVMSG Fhazal :IRC connection timed out.  Reconnecting...",
         ":Fhazal!u@h JOIN #skinhead", ":srv 353 Fhazal = #skinhead :Fhazal Psycho", ":srv 366 Fhazal #skinhead :End")
    b = bufs[0]
    assert b.joined and sorted(u.nick for u in b.users.values()) == ["Fhazal", "Psycho"]


def test_every_real_znc_wording_leaves_the_channels_as_they_are(app):
    # 0.8.5: BChat no longer reads ZNC's *status lines; a bouncer is treated as a normal server
    for text in ("Disconnected from IRC. Reconnecting...",
                 "Disconnected from IRC (Connection reset by peer). Reconnecting...",
                 "Cannot connect to IRC (Connection timed out). Retrying...",
                 "IRC connection timed out.  Reconnecting...",
                 "Connection Refused.  Reconnecting...",
                 "Error from server: Closing link"):
        for who in (REAL, OLD):
            s, bufs = inside()
            feed(s, f":{who} PRIVMSG Fhazal :{text}")
            for b in bufs:
                assert b.joined and len(b.users) == 3, (who, text)
