"""Popular networks for the Network List (like mIRC's and XChat's built-in lists, but current).

Every entry was checked live on 2026-11-09 (TLS handshake only, no login):
  ok   = encrypted with a valid certificate
  ask  = encrypted, but the certificate is self-signed or for another name: BChat's "Check this server" asks once
  none = no encryption offered at all (port 6697 didn't answer), plain 6667
freenode is left out on purpose: its communities moved to Libera.Chat after the 2021 takeover."""
from __future__ import annotations

from dataclasses import dataclass

from .config import NetworkConfig, Server


@dataclass(frozen=True)
class Popular:
    name: str
    host: str
    port: int
    tls: str          # ok | ask | none
    about: str
    autojoin: str = ""

    @property
    def ssl(self) -> bool:
        return self.tls != "none"


POPULAR = (
    Popular("BajuBesi Community", "irc.bajubesi.org", 6697, "ok", "BChat's home: #BChat, #chat", "#BChat,#chat"),
    Popular("Libera.Chat", "irc.libera.chat", 6697, "ok", "open source projects"),
    Popular("OFTC", "irc.oftc.net", 6697, "ok", "open source, Debian"),
    Popular("DALnet", "irc.dal.net", 6697, "ok", "chat, since 1994"),
    Popular("Rizon", "irc.rizon.net", 6697, "ok", "anime, gaming"),
    Popular("EsperNet", "irc.esper.net", 6697, "ok", "Minecraft, gaming"),
    Popular("hackint", "irc.hackint.org", 6697, "ok", "hackers, makers"),
    Popular("Snoonet", "irc.snoonet.org", 6697, "ok", "communities, Reddit"),
    Popular("SwiftIRC", "irc.swiftirc.net", 6697, "ok", "gaming, RuneScape"),
    Popular("AfterNET", "irc.afternet.org", 6697, "ok", "chat"),
    Popular("DarkMyst", "irc.darkmyst.org", 6697, "ok", "role-playing"),
    Popular("Abjects", "irc.abjects.net", 6697, "ok", "chat, file sharing"),
    Popular("Furnet", "irc.furnet.org", 6697, "ok", "furry community"),
    Popular("tilde.chat", "irc.tilde.chat", 6697, "ok", "tilde servers"),
    Popular("Ergo", "irc.ergo.chat", 6697, "ok", "modern IRC, Ergo server"),
    Popular("IRCNow", "irc.ircnow.org", 6697, "ok", "free shell and bouncer"),
    Popular("EFnet", "irc.efnet.org", 6697, "ask", "the oldest, since 1990"),
    Popular("IRCnet", "open.ircnet.net", 6697, "ask", "Europe, since 1996"),
    Popular("GameSurge", "irc.gamesurge.net", 6697, "ask", "gaming"),
    Popular("Undernet", "irc.undernet.org", 6667, "none", "chat, since 1992"),
    Popular("QuakeNet", "irc.quakenet.org", 6667, "none", "gaming, esports"),
)

TLS_TIP = {"ok": "Encrypted, certificate checked",
           "ask": "Encrypted, but the certificate is self-signed or for another name: BChat asks you once",
           "none": "This network offers no encryption"}


def find_saved(cfg, p: Popular) -> NetworkConfig | None:
    """A network you already have for it: same name, or one of its servers is this host."""
    for n in cfg.networks:
        if n.name.lower() == p.name.lower() or any(s.host.lower() == p.host for s in n.servers):
            return n
    return None


def add(cfg, p: Popular) -> NetworkConfig:
    """Copy it into My Networks (once); your own networks are never changed."""
    have = find_saved(cfg, p)
    if have is not None:
        return have
    n = NetworkConfig(p.name, [Server(p.host, p.port, p.ssl)], autojoin=p.autojoin)
    cfg.networks.append(n)
    return n
