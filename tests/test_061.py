"""0.6.1: FINDING-01, nicks and channel names folded the way each server says (ISUPPORT CASEMAPPING)."""
from bchat.config import Config, NetworkConfig, Server
from bchat.protocol import folder, lower, parse_line
from bchat.session import Session


def feed(s, *raw):
    for r in raw:
        s._handle(parse_line(r))


def session(app):
    s = Session(NetworkConfig("N", [Server("127.0.0.1", 6667)]), Config(nick="me"))
    s.nick = "me"
    return s


def test_fold_functions_per_casemapping():
    assert folder("ascii")("A[B]\\~Z") == "a[b]\\~z"
    assert folder("rfc1459")("A[B]\\~") == "a{b}|^"
    assert folder("strict-rfc1459")("A[B]\\~") == "a{b}|~"
    assert folder("RFC8265")("ÄB") == "äb"
    assert folder("")("[x]") == folder("something-new")("[x]") == lower("[x]") == "{x}"
    assert folder("ascii")("É") == "É"            # ascii folds A-Z only


def test_ascii_server_keeps_bracket_nicks_apart(app):
    s = session(app)
    feed(s, ":srv 005 me CASEMAPPING=ascii CHANTYPES=# :are supported",
         ":me!u@h JOIN #Chan", ":a[b!u@h JOIN #chan", ":a{b!u@h JOIN #CHAN")
    b = s.buffers[s.fold("#chan")]
    assert s.casemapping == "ascii"
    assert sorted(u.nick for u in b.users.values()) == ["a[b", "a{b", "me"]
    feed(s, ":a[b!u@h PART #chan")
    assert [u.nick for u in b.users.values() if u.nick.startswith("a")] == ["a{b"]


def test_rfc1459_server_still_treats_brackets_as_one(app):
    s = session(app)
    feed(s, ":srv 005 me CASEMAPPING=rfc1459 :are supported", ":me!u@h JOIN #c", ":a[b!u@h JOIN #c", ":A{B!u@h JOIN #c")
    assert len(s.buffers["#c"].users) == 2


def test_names_held_before_005_are_rekeyed(app):
    s = session(app)
    feed(s, ":me!u@h JOIN #x[1]", ":Bob[m]!u@h JOIN #x[1]", ":Bob[m]!u@h PRIVMSG me :hi")
    assert set(s.buffers) == {"#x{1}", "bob{m}"}                 # rfc1459 until the server says otherwise
    feed(s, ":srv 005 me CASEMAPPING=ascii :are supported")
    assert set(s.buffers) == {"#x[1]", "bob[m]"}
    assert "bob[m]" in s.buffers["#x[1]"].users
    feed(s, ":Bob{m}!u@h PRIVMSG me :other person")              # a different user now: own query
    assert set(s.buffers) == {"#x[1]", "bob[m]", "bob{m}"}
    feed(s, ":Bob[m]!u@h NICK Bob2")
    assert "bob2" in s.buffers and "bob[m]" not in s.buffers


def test_no_casemapping_token_keeps_the_current_one(app):
    s = session(app)
    feed(s, ":srv 005 me CASEMAPPING=ascii :are supported", ":srv 005 me NICKLEN=30 :are supported")
    assert s.casemapping == "ascii"
