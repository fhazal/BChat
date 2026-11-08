"""BChat problem-report receiver (runs on the BajuBesi VPS behind nginx at https://bajubesi.org/bchat/report).

Python standard library only. Stores each report in SQLite, groups the same bug by its fingerprint, answers
{"id": "BR-42", "seen": 3}, and posts each report to a private Discord channel through a webhook, pinging the
owner. Several reports of the same bug in a short time post an extra "crash wave" alarm. Buzz (the IRC helper
on the homelab) reads new reports from /bchat/new over the WireGuard tunnel and messages the owner on IRC.

Everything a user sent is treated as untrusted: sizes and types are checked, text goes into Discord inside code
blocks (no links, no mentions), and only the owner can ever be pinged.

Settings (environment):
  BCHAT_RR_DB            sqlite file              (default ./reports.db)
  BCHAT_RR_PICTURES      folder for pictures      (default ./pictures)
  BCHAT_RR_BIND / PORT   where to listen          (default 127.0.0.1:8765)
  BCHAT_RR_WEBHOOK_FILE  file holding the Discord webhook URL (empty = no Discord)
  BCHAT_RR_DISCORD_USER  Discord user id to ping
  BCHAT_RR_TRUST_PROXY   1 = take the visitor's address from X-Real-IP when the request comes from 127.0.0.1
  BCHAT_RR_INTERNAL      comma list of address prefixes allowed to read /bchat/new (default 127.,10.10.10.)
  BCHAT_RR_KEEP_DAYS     reports older than this are deleted (default 90); pictures go after a third of it
  BCHAT_RR_PICTURES_MB   pictures folder cap: above it, new reports are kept without their picture (default 200)
  BCHAT_RR_DB_MB         database cap: above it, new reports are refused with 507 (default 300)

Flood defence: nginx limits each address at the door (limit_req), then this program: 10 reports per sender an
hour, 300 an hour in all, the size caps above, old reports deleted, Discord 30 posts an hour.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KINDS = ("Crashed", "Won't connect", "Looks wrong", "Slow", "Something else")
MAX_BODY = 3_600_000
MAX_PICTURE = 2_000_000
PER_IP_HOUR = 10
ALL_HOUR = 300
DISCORD_HOUR = 30
WAVE_COUNT, WAVE_MINUTES = 5, 30
MB = 1024 * 1024


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Full(Exception):
    """The database is at its cap: the report is refused (BChat keeps it and tries again later)."""


class Store:
    def __init__(self, db: str, pictures: str, keep_days: float = 90, pictures_mb: float = 200, db_mb: float = 300) -> None:
        self.lock = threading.Lock()
        self.path = Path(db)
        self.keep_days, self.pictures_max, self.db_max = keep_days, pictures_mb * MB, db_mb * MB
        self.db = sqlite3.connect(db, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS reports (
            n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, who TEXT, sig TEXT, kind TEXT, bchat TEXT,
            data TEXT, picture TEXT, fixed_in TEXT DEFAULT '')""")
        self.db.execute("CREATE INDEX IF NOT EXISTS by_sig ON reports(sig)")
        self.db.commit()
        self.pictures = Path(pictures)
        self.pictures.mkdir(parents=True, exist_ok=True)
        self.picture_bytes = sum(f.stat().st_size for f in self.pictures.glob("*.png"))

    def db_bytes(self) -> int:
        try:
            size = self.path.stat().st_size
        except OSError:
            return 0
        free = self.db.execute("PRAGMA freelist_count").fetchone()[0] * self.db.execute("PRAGMA page_size").fetchone()[0]
        return max(0, size - free)          # pages freed by prune() are used again before the file grows

    def prune(self, now: float | None = None) -> tuple[int, int]:
        """Deletes reports older than keep_days and pictures older than a third of that. (rows, pictures) gone."""
        now = now if now is not None else time.time()
        rows = pics = 0
        with self.lock:
            for n, name in self.db.execute("SELECT n, picture FROM reports WHERE picture!='' AND ts<?",
                                           (now - self.keep_days / 3 * 86400,)).fetchall():
                f = self.pictures / name
                try:
                    size = f.stat().st_size
                    f.unlink()
                    self.picture_bytes -= size
                    pics += 1
                except OSError:
                    pass
                self.db.execute("UPDATE reports SET picture='' WHERE n=?", (n,))
            rows = self.db.execute("DELETE FROM reports WHERE ts<?", (now - self.keep_days * 86400,)).rowcount
            self.db.commit()
        return rows, pics

    def add(self, who: str, r: dict, picture: bytes) -> tuple[int, int]:
        with self.lock:
            if self.db_bytes() > self.db_max:
                raise Full()
            if picture and self.picture_bytes + len(picture) > self.pictures_max:
                picture = b""                                  # keep the report, drop the picture
                r["picture_dropped"] = 1
            cur = self.db.execute("INSERT INTO reports (ts, who, sig, kind, bchat, data, picture) VALUES (?,?,?,?,?,?,?)",
                                  (time.time(), who, r["sig"], r["kind"], r["bchat"], json.dumps(r), ""))
            n = cur.lastrowid
            if picture:
                name = f"BR-{n}.png"
                (self.pictures / name).write_bytes(picture)
                self.picture_bytes += len(picture)
                self.db.execute("UPDATE reports SET picture=? WHERE n=?", (name, n))
            seen = 1
            if r["sig"]:
                seen = self.db.execute("SELECT COUNT(DISTINCT who) FROM reports WHERE sig=?", (r["sig"],)).fetchone()[0]
            self.db.commit()
            return n, seen

    def recent_same(self, sig: str, minutes: int) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM reports WHERE sig=? AND ts>?", (sig, time.time() - minutes * 60)).fetchone()[0]

    def after(self, n: int, limit: int = 50) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT n, ts, sig, kind, bchat, data FROM reports WHERE n>? ORDER BY n LIMIT ?", (n, limit)).fetchall()
        out = []
        for n_, ts, sig, kind, bchat, data in rows:
            d = json.loads(data)
            out.append({"id": f"BR-{n_}", "n": n_, "ts": ts, "sig": sig, "kind": kind, "bchat": bchat,
                        "wrote": d.get("wrote", "")[:200], "error_last": (d.get("error", "").strip().splitlines() or [""])[-1][:200],
                        "seen": self.seen(sig)})
        return out

    def seen(self, sig: str) -> int:
        if not sig:
            return 1
        with self.lock:
            return self.db.execute("SELECT COUNT(DISTINCT who) FROM reports WHERE sig=?", (sig,)).fetchone()[0]


class Limits:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.per: dict[str, deque] = {}
        self.all: deque = deque()

    def allow(self, who: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.per.setdefault(who, deque())
            for d in (q, self.all):
                while d and now - d[0] > 3600:
                    d.popleft()
            if len(q) >= PER_IP_HOUR or len(self.all) >= ALL_HOUR:
                return False
            q.append(now)
            self.all.append(now)
            return True


def _s(v, n: int) -> str:
    return v[:n] if isinstance(v, str) else ""


def clean(raw) -> tuple[dict, bytes]:
    """Only the fields BChat sends, each checked. Raises ValueError for anything else."""
    if not isinstance(raw, dict) or raw.get("v") != 1:
        raise ValueError("not a BChat report")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    steps = raw.get("steps") or []
    if not isinstance(steps, list) or len(steps) > 20:
        raise ValueError("steps")
    r = {"v": 1, "kind": kind, "bchat": _s(raw.get("bchat"), 40), "os": _s(raw.get("os"), 120), "scale": _s(raw.get("scale"), 12),
         "theme": _s(raw.get("theme"), 60), "wrote": _s(raw.get("wrote"), 4000), "error": _s(raw.get("error"), 4000),
         "sig": re.sub(r"[^0-9a-f]", "", _s(raw.get("sig"), 40)), "freeze": int(raw.get("freeze") or 0) if str(raw.get("freeze") or 0).isdigit() else 0,
         "steps": [[_s(a, 10), _s(b, 80)] for a, b in (s if isinstance(s, list) and len(s) == 2 else ("", "") for s in steps)],
         "open": _s(raw.get("open"), 200), "plugins": raw.get("plugins") if isinstance(raw.get("plugins"), int) else 0}
    if not r["bchat"]:
        raise ValueError("no version")
    picture = b""
    if raw.get("picture"):
        try:
            picture = base64.b64decode(raw["picture"], validate=True)
        except (ValueError, TypeError):
            raise ValueError("picture")
        if len(picture) > MAX_PICTURE or not picture.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("picture")
    return r, picture


def _block(text: str, n: int) -> str:
    """User text in a code block: Discord shows it as plain text (no links, no mentions, no formatting)."""
    text = (text or "").replace("```", "'''")[:n]
    return f"```\n{text}\n```" if text else "-"


class Discord:
    def __init__(self, url: str, user: str) -> None:
        self.url, self.user = url, user
        self.sent: deque = deque()
        self.held = 0
        self.waves: dict[str, float] = {}
        self.lock = threading.Lock()

    def _post(self, payload: dict) -> None:
        if not self.url:
            return
        payload["allowed_mentions"] = {"users": [self.user] if self.user else []}
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "BChat-report-receiver"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:      # Discord down never loses a report: it is already stored
            print("discord:", type(e).__name__, flush=True)

    def _room(self) -> bool:
        now = time.time()
        with self.lock:
            while self.sent and now - self.sent[0] > 3600:
                self.sent.popleft()
            if len(self.sent) >= DISCORD_HOUR:
                self.held += 1
                return False
            self.sent.append(now)
            return True

    def report(self, n: int, r: dict, seen: int, picture: bool) -> None:
        if not self._room():
            return
        ping = f"<@{self.user}> " if self.user else ""
        held, self.held = self.held, 0
        extra = f" ({held} more reports arrived while the channel was paused)" if held else ""
        steps = "\n".join(f"{t} {s}" for t, s in r["steps"][-8:])
        fields = [{"name": "Seen by", "value": f"{seen} {'person' if seen == 1 else 'people'}", "inline": True},
                  {"name": "System", "value": _block(f"{r['os']} · {r['scale']} · {r['theme']}", 200), "inline": True}]
        if r["freeze"]:
            fields.append({"name": "Stopped responding", "value": f"{r['freeze']} seconds", "inline": True})
        if steps:
            fields.append({"name": "Last steps", "value": _block(steps, 900), "inline": False})
        fields.append({"name": "Open", "value": _block(r["open"], 200), "inline": False})
        if picture:
            fields.append({"name": "Picture", "value": f"BR-{n}.png on the server", "inline": True})
        desc = ""
        if r["wrote"]:
            desc += "**They wrote:**\n" + _block(r["wrote"], 600) + "\n"
        if r["error"]:
            desc += "**Error:**\n" + _block("\n".join(r["error"].strip().splitlines()[-6:]), 1200)
        colour = {"Crashed": 0xF38BA8, "Slow": 0xFAB387, "Won't connect": 0x89B4FA, "Looks wrong": 0xCBA6F7}.get(r["kind"], 0xA6ADC8)
        self._post({"username": "BChat Reports", "content": f"{ping}🐞 **BR-{n} · {r['kind']}** · BChat {r['bchat']}{extra}",
                    "embeds": [{"title": f"BR-{n} · {r['kind']}", "color": colour, "description": desc[:4000] or "-",
                                "fields": fields, "footer": {"text": f"fingerprint {r['sig'] or 'none'}"}}]})

    def wave(self, r: dict, count: int) -> None:
        now = time.time()
        if now - self.waves.get(r["sig"], 0) < 3600:
            return
        self.waves[r["sig"]] = now
        ping = f"<@{self.user}> " if self.user else ""
        self._post({"username": "BChat Reports",
                    "content": f"{ping}🚨 **Crash wave:** {count} reports of the same problem in {WAVE_MINUTES} minutes "
                               f"(BChat {r['bchat']}, {r['kind']}, fingerprint `{r['sig']}`). Check when you can."})


def make_handler(store: Store, limits: Limits, discord: Discord, trust_proxy: bool, internal: tuple[str, ...]):
    class H(BaseHTTPRequestHandler):
        server_version = "BChatReports/1"
        sys_version = ""
        timeout = 20                            # a client that stops sending halfway is dropped

        def log_message(self, fmt, *args):      # no visitor addresses in the logs
            pass

        def who(self) -> str:
            ip = self.client_address[0]
            if trust_proxy and ip == "127.0.0.1":
                ip = (self.headers.get("X-Real-IP") or ip).strip()
            return ip

        def reply(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            if code in (429, 507):
                self.send_header("Retry-After", "3600")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/bchat/report/health":
                return self.reply(200, {"ok": True})
            if u.path == "/bchat/new" and self.client_address[0].startswith(internal) and not self.headers.get("X-Real-IP"):
                after = int((parse_qs(u.query).get("after") or ["0"])[0] or 0)
                return self.reply(200, {"reports": store.after(after)})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path != "/bchat/report":
                return self.reply(404, {"error": "not found"})
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > MAX_BODY:
                return self.reply(413, {"error": "too big"})
            who = hashlib.sha256(("bchat-rr|" + self.who()).encode()).hexdigest()[:16]   # never stored as an address
            if not limits.allow(who):
                self.rfile.read(size)
                return self.reply(429, {"error": "too many reports, try later"})
            try:
                r, picture = clean(json.loads(self.rfile.read(size).decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                return self.reply(400, {"error": "not a BChat report"})
            try:
                n, seen = store.add(who, r, picture)
            except Full:
                return self.reply(507, {"error": "report storage full, try later"})
            if r.get("picture_dropped"):
                picture = b""
            self.reply(200, {"id": f"BR-{n}", "seen": seen})

            def notify():
                discord.report(n, r, seen, bool(picture))
                if r["sig"]:
                    same = store.recent_same(r["sig"], WAVE_MINUTES)
                    if same >= WAVE_COUNT:
                        discord.wave(r, same)
            threading.Thread(target=notify, daemon=True).start()
    return H


def serve(port: int | None = None, ready=None) -> ThreadingHTTPServer:
    url = ""
    wf = env("BCHAT_RR_WEBHOOK_FILE")
    if wf and Path(wf).is_file():
        url = Path(wf).read_text(encoding="utf-8").strip()
    store = Store(env("BCHAT_RR_DB", "reports.db"), env("BCHAT_RR_PICTURES", "pictures"), float(env("BCHAT_RR_KEEP_DAYS", "90")),
                  float(env("BCHAT_RR_PICTURES_MB", "200")), float(env("BCHAT_RR_DB_MB", "300")))
    handler = make_handler(store, Limits(), Discord(url, env("BCHAT_RR_DISCORD_USER")), env("BCHAT_RR_TRUST_PROXY") == "1",
                           tuple(x for x in env("BCHAT_RR_INTERNAL", "127.,10.10.10.").split(",") if x))
    httpd = ThreadingHTTPServer((env("BCHAT_RR_BIND", "127.0.0.1"), port if port is not None else int(env("BCHAT_RR_PORT", "8765"))), handler)
    httpd.store = store
    if ready:
        ready(httpd)
    return httpd


def internal_listener(main: ThreadingHTTPServer, where: str) -> ThreadingHTTPServer | None:
    """A second listener for Buzz on the private tunnel address (BCHAT_RR_INTERNAL_BIND=10.10.10.1:8766).
    Same handler and store; never on a public address. A missing tunnel never stops the public receiver."""
    if not where:
        return None
    host, _, port = where.rpartition(":")
    try:
        inner = ThreadingHTTPServer((host, int(port)), main.RequestHandlerClass)
    except OSError as e:
        print("internal listener not started:", e, flush=True)
        return None
    threading.Thread(target=inner.serve_forever, name="internal", daemon=True).start()
    print("BChat report receiver (internal) on", inner.server_address, flush=True)
    return inner


def prune_loop(store: Store, every: float = 3600) -> None:
    while True:
        try:
            rows, pics = store.prune()
            if rows or pics:
                print(f"pruned {rows} old reports, {pics} old pictures", flush=True)
        except Exception as e:
            print("prune:", type(e).__name__, e, flush=True)
        time.sleep(every)


if __name__ == "__main__":
    s = serve()
    threading.Thread(target=prune_loop, args=(s.store,), name="prune", daemon=True).start()
    internal_listener(s, env("BCHAT_RR_INTERNAL_BIND"))
    print("BChat report receiver on", s.server_address, flush=True)
    s.serve_forever()
