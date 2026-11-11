"""A tiny scripted IRC server on localhost for tests. Runs in a thread; optional SSL."""
from __future__ import annotations

import socket
import ssl as ssl_mod
import threading
import time

NAMES = "@B3L0N[JVN] @Belon @Fhazal @J|wang @Psycho +DJSkinhead +Oracle Badaboom BeerAddict Belon_skd BesiLink Combat90 Corumn26 Dyno_skd"
AWAY = {"J|wang", "Psycho", "BeerAddict", "Combat90", "Corumn26"}


class FakeIrcd:
    def __init__(self, certfile: str | None = None, keyfile: str | None = None, taken_nicks=(), caps="", sasl_ok=True, whox=False, refuse=False, history=None, client_ca=None, starttls=None, scram_password=None, scram_bad_server=False):
        self.starttls = starttls          # 0.6.0: "ok" = answer 670 and switch to SSL, "refuse" = 691
        self.scram_password = scram_password
        self.scram_bad_server = scram_bad_server
        self._scram = None
        self._scram_stage = 0
        self._upgrade = False
        self.history = history     # [(prefix, command, text, unix time)]: a channel that keeps history (+H)
        self.refuse = refuse
        self.extra_caps = caps
        self.sasl_ok = sasl_ok
        self.whox = whox
        self.auth_blob = ""
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        self.ctx = None
        if certfile:
            self.ctx = ssl_mod.SSLContext(ssl_mod.PROTOCOL_TLS_SERVER)
            self.ctx.load_cert_chain(certfile, keyfile)
            if client_ca:                        # ask for a client certificate (SASL EXTERNAL / CertFP tests)
                self.ctx.verify_mode = ssl_mod.CERT_OPTIONAL
                self.ctx.load_verify_locations(client_ca)
        self.peer_der = b""
        self.taken = set(taken_nicks)
        self.received: list[str] = []
        self.nick = ""
        self.user_seen = False
        self.cap_open = False
        self.welcomed = False
        self.client: socket.socket | None = None
        self.stop_flag = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.srv.settimeout(0.2)
        while not self.stop_flag:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                continue
            try:
                if self.ctx and not self.starttls:
                    conn = self.ctx.wrap_socket(conn, server_side=True)
                    self.peer_der = conn.getpeercert(binary_form=True) or b""
            except (ssl_mod.SSLError, OSError):
                continue
            self.client = conn
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def send(self, line: str):
        if self.client:
            try:
                self.client.sendall(line.encode() + b"\r\n")
            except OSError:
                pass

    def _serve(self, conn):
        buf = b""
        while not self.stop_flag:
            try:
                data = conn.recv(4096)
            except OSError:
                return
            if not data:
                return
            buf += data
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                self._line(raw.decode("utf-8", "replace").rstrip("\r"))
                if self._upgrade:                       # STARTTLS: the rest of the talk is over SSL
                    self._upgrade = False
                    try:
                        conn = self.ctx.wrap_socket(conn, server_side=True)
                    except (ssl_mod.SSLError, OSError):
                        return
                    self.client = conn

    def _line(self, line: str):
        self.received.append(line)
        word = line.split(" ")
        cmd = word[0].upper()
        n = self.nick
        if self.refuse and cmd == "USER":
            self.send(":irc.znc.in 464 * :Invalid Password")
            self.client.close()
            return
        if cmd == "STARTTLS":
            if self.starttls == "ok":
                self.send(":srv 670 * :STARTTLS successful, go ahead with TLS handshake")
                self._upgrade = True
            else:
                self.send(":srv 691 * :STARTTLS failed")
            return
        if cmd == "AUTHENTICATE" and self.scram_password is not None and (word[1] == "SCRAM-SHA-256" or self._scram):
            import base64
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
            from bchat.scram import ScramServer
            if word[1] == "SCRAM-SHA-256":
                self._scram, self._scram_stage = ScramServer(self.scram_password), 0
                self.send("AUTHENTICATE +")
                return
            data = base64.b64decode(word[1]) if word[1] != "+" else b""
            if self._scram_stage == 0:
                self._scram_stage = 1
                self.send("AUTHENTICATE " + base64.b64encode(self._scram.first(data)).decode())
            elif self._scram_stage == 1:
                self._scram_stage = 2
                v = self._scram.final(data)
                if v is None:
                    self._scram = None
                    self.send(f":srv 904 {self.nick or '*'} :SASL authentication failed")
                    return
                if self.scram_bad_server:
                    v = b"v=" + base64.b64encode(b"x" * 32)
                self.send("AUTHENTICATE " + base64.b64encode(v).decode())
            else:
                self._scram = None
                self.send(f":srv 900 {self.nick or '*'} {self.nick or '*'}!u@h acct :You are now logged in as acct")
                self.send(f":srv 903 {self.nick or '*'} :SASL authentication successful")
            return
        if cmd == "CAP" and word[1] == "END":
            self.cap_open = False
            self._maybe_welcome()
        elif cmd == "CAP" and word[1] == "LS":
            self.cap_open = True
            self.send(f":srv CAP * LS :multi-prefix away-notify server-time {self.extra_caps}".rstrip())
        elif cmd == "AUTHENTICATE":
            if word[1] in ("PLAIN", "EXTERNAL"):
                self.send("AUTHENTICATE +")
            else:
                self.auth_blob = word[1]
                if self.sasl_ok:
                    self.send(f":srv 900 {self.nick} {self.nick}!u@h acct :You are now logged in as acct")
                    self.send(f":srv 903 {self.nick} :SASL authentication successful")
                else:
                    self.send(f":srv 904 {self.nick} :SASL authentication failed")
        elif cmd == "CAP" and word[1] == "REQ":
            self.send(f":srv CAP * ACK {' '.join(word[2:])}")
        elif cmd == "NICK":
            if word[1] in self.taken:
                self.send(f":srv 433 * {word[1]} :Nickname is already in use")
            else:
                self.nick = word[1]
                self._maybe_welcome()
        elif cmd == "USER":
            self.user_seen = True
            self._maybe_welcome()
        elif cmd == "JOIN":
            for ch in word[1].split(","):
                self.send(f":{n}!u@h JOIN {ch}")
                self.send(f":srv 332 {n} {ch} :Welcome to the Official Channel")
                self.send(f":srv 333 {n} {ch} Fhazal!f@h {int(time.time())}")
                self.send(f":srv 353 {n} = {ch} :{NAMES}")
                self.send(f":srv 366 {n} {ch} :End of NAMES")
        elif cmd == "MODE" and len(word) == 2:
            self.send(f":srv 324 {n} {word[1]} +nt")
        elif cmd == "WHO":
            ch = word[1]
            for item in NAMES.split():
                nick = item.lstrip("@+")
                flag = "G" if nick in AWAY else "H"
                if len(word) > 2:
                    self.send(f":srv 354 {n} 152 {ch} {nick.lower()} host.example.my srv.my {nick} {flag} acct{nick} :Whox {nick}")
                    continue
                self.send(f":srv 352 {n} {ch} {nick.lower()} host.example.my srv {nick} {flag} :0 Real {nick}")
            self.send(f":srv 315 {n} {ch} :End of WHO")
        elif cmd == "WHOIS":
            t = word[1]
            self.send(f":srv 311 {n} {t} oracle bot.bajubesi.org * :Oracle eggdrop")
            self.send(f":srv 319 {n} {t} :@#skinhead #kampung")
            self.send(f":srv 312 {n} {t} irc.bajubesi.org :SkinIRC")
            self.send(f":srv 317 {n} {t} 252 {int(time.time()) - 3600} :seconds idle, signon")
            self.send(f":srv 318 {n} {t} :End of /WHOIS list.")
        elif cmd == "CHATHISTORY" and self.history is not None:
            from datetime import datetime, timezone
            iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            sub, ch, ref, lim = word[1].upper(), word[2], word[3], int(word[4])
            rows = self.history
            if sub == "AFTER":
                after = datetime.fromisoformat(ref.split("=", 1)[1].replace("Z", "+00:00")).timestamp()
                rows = [r for r in rows if r[3] > after]
            self.send(f":srv BATCH +h1 chathistory {ch}")
            for pre, verb, text, t in rows[-lim:]:
                self.send(f"@batch=h1;time={iso(t)} :{pre} {verb} {ch} :{text}")
            self.send(":srv BATCH -h1")
        elif cmd == "PING":
            self.send(f":srv PONG srv :{word[-1].lstrip(':')}")
        elif cmd == "QUIT":
            self.client.close()

    def _maybe_welcome(self):
        if self.nick and self.user_seen and not self.cap_open and not self.welcomed:
            self.welcomed = True
            self._welcome()

    def _welcome(self):
        n = self.nick
        self.send(f":irc.fake.org 001 {n} :Welcome to the fake network {n}")
        self.send(f":srv 005 {n} PREFIX=(ohv)@%+ CHANTYPES=# CHANMODES=beI,k,l,imnpst NETWORK=Fake {'WHOX ' if self.whox else ''}{'CHATHISTORY=100 ' if self.history is not None else ''}:are supported")
        self.send(f":srv 422 {n} :MOTD File is missing")

    def stop(self):
        self.stop_flag = True
        self.srv.close()
