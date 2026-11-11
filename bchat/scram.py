"""SASL SCRAM-SHA-256 (RFC 5802 / RFC 7677), client side. Standard library only.

The password never crosses the network: the server gets a proof that we know it, and must send back a proof that it
knows it too (verified before the login counts)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def _name(text: str) -> str:
    return text.replace("=", "=3D").replace(",", "=2C")


class Scram:
    def __init__(self, user: str, password: str, nonce: str | None = None):
        self.user, self.password = user, password
        self.nonce = nonce or base64.b64encode(secrets.token_bytes(18)).decode()
        self.stage = 0
        self.verified = False
        self._server_sig = b""
        self._first_bare = ""

    def step(self, server: bytes) -> bytes | None:
        """The next message to send, or None when nothing is left to send. Raises ValueError on a bad server."""
        if self.stage == 0:                                   # client-first
            self.stage = 1
            self._first_bare = f"n={_name(self.user)},r={self.nonce}"
            return ("n,," + self._first_bare).encode()
        if self.stage == 1:                                   # server-first -> client-final
            text = server.decode("utf-8", "replace")
            parts = dict(p.split("=", 1) for p in text.split(",") if "=" in p)
            if "e" in parts:
                raise ValueError(f"the server said {parts['e']}")
            r, salt, it = parts.get("r", ""), parts.get("s", ""), parts.get("i", "")
            if not r.startswith(self.nonce) or not salt or not it.isdigit() or int(it) < 4096 or int(it) > 1_000_000:
                raise ValueError("the server's answer doesn't fit")
            salted = hashlib.pbkdf2_hmac("sha256", self.password.encode("utf-8"), base64.b64decode(salt), int(it))
            client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
            stored = hashlib.sha256(client_key).digest()
            final_bare = f"c=biws,r={r}"
            auth = f"{self._first_bare},{text},{final_bare}".encode()
            sig = hmac.new(stored, auth, hashlib.sha256).digest()
            proof = bytes(a ^ b for a, b in zip(client_key, sig))
            server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
            self._server_sig = hmac.new(server_key, auth, hashlib.sha256).digest()
            self.stage = 2
            return f"{final_bare},p={base64.b64encode(proof).decode()}".encode()
        if self.stage == 2:                                   # server-final: check its proof
            text = server.decode("utf-8", "replace")
            parts = dict(p.split("=", 1) for p in text.split(",") if "=" in p)
            if "e" in parts:
                raise ValueError(f"the server said {parts['e']}")
            if not hmac.compare_digest(base64.b64decode(parts.get("v", "")), self._server_sig):
                raise ValueError("the server couldn't prove it knows your password")
            self.verified = True
            self.stage = 3
            return None
        return None


class ScramServer:
    """Only for tests: the other side, with a known password."""

    def __init__(self, password: str, salt: bytes = b"bchat-test-salt!", iterations: int = 4096):
        self.salt, self.iterations = salt, iterations
        self.salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        self.nonce = ""
        self.first_bare = ""
        self.server_first = ""

    def first(self, client_first: bytes) -> bytes:
        text = client_first.decode()
        self.first_bare = text.split(",", 2)[2]
        cnonce = dict(p.split("=", 1) for p in self.first_bare.split(","))["r"]
        self.nonce = cnonce + "srvnonce"
        self.server_first = f"r={self.nonce},s={base64.b64encode(self.salt).decode()},i={self.iterations}"
        return self.server_first.encode()

    def final(self, client_final: bytes) -> bytes | None:
        text = client_final.decode()
        bare, _, proof = text.rpartition(",p=")
        auth = f"{self.first_bare},{self.server_first},{bare}".encode()
        client_key_check = hmac.new(self.salted, b"Client Key", hashlib.sha256).digest()
        stored = hashlib.sha256(client_key_check).digest()
        sig = hmac.new(stored, auth, hashlib.sha256).digest()
        client_key = bytes(a ^ b for a, b in zip(base64.b64decode(proof), sig))
        if hashlib.sha256(client_key).digest() != stored:
            return None
        server_key = hmac.new(self.salted, b"Server Key", hashlib.sha256).digest()
        return b"v=" + base64.b64encode(hmac.new(server_key, auth, hashlib.sha256).digest())
