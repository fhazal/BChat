"""0.8.8 UPnP: open the DCC ports on the home router, Settings > Network setup > Router.

Standard library only: an SSDP search (M-SEARCH to 239.255.255.250:1900) finds the router, its description XML
names the WANIPConnection / WANPPPConnection control URL, and SOAP calls AddPortMapping (TCP, every port of the DCC
range in Settings > Files, to this PC's LAN address) and GetExternalIPAddress. DeletePortMapping takes them off
again when the tick goes off and when BChat quits. All network work runs on one worker thread; the GUI only sees
the status line through a Qt signal."""
from __future__ import annotations

import queue
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from PySide6.QtCore import QObject, Signal

SSDP_ADDR = ("239.255.255.250", 1900)   # tests point a Manager at a local fake instead
TIMEOUT = 3.0                            # the longest a search waits for the router
MAX_PORTS = 100                          # a huge range would mean hundreds of SOAP calls
DESCRIPTION = "BChat DCC"
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2", "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")
SEARCH_FOR = ("urn:schemas-upnp-org:device:InternetGatewayDevice:1", *SERVICES[1:])

LOOKING = "Looking for the router..."
NO_ROUTER = "No router answered (UPnP)"
OPENED = "Router found · outside address"   # how a success line starts
NEED_RANGE = "Set a DCC port range in Settings › Files to open ports on the router"


class UpnpError(Exception):
    pass


class Router:
    def __init__(self, control_url: str, service: str, host: str, lan_ip: str):
        self.control_url, self.service, self.host, self.lan_ip = control_url, service, host, lan_ip


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _no_proxy():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the router is on the LAN: never a proxy


def search(target=SSDP_ADDR, timeout: float = TIMEOUT) -> list[tuple[str, str]]:
    """(responder ip, LOCATION url) for every answer to an M-SEARCH, waiting at most `timeout` seconds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    found: list[tuple[str, str]] = []
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for st in SEARCH_FOR:
            msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\nMAN: \"ssdp:discover\"\r\n"
                   f"MX: 2\r\nST: {st}\r\n\r\n")
            sock.sendto(msg.encode("ascii"), target)
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                break
            sock.settimeout(left)
            try:
                data, (ip, _port) = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                break
            m = re.search(rb"^location:\s*(\S+)", data, re.IGNORECASE | re.MULTILINE)
            if m:
                url = m.group(1).decode("ascii", "replace")
                if (ip, url) not in found:
                    found.append((ip, url))
                end = min(end, time.monotonic() + 0.3)     # a few more answers, then stop: no full wait
    finally:
        sock.close()
    return found


def _lan_ip(host: str) -> str:
    """This PC's address on the router's side: the one a UDP 'connect' toward it picks (nothing is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 1900))
        return s.getsockname()[0]
    finally:
        s.close()


def describe(ip: str, location: str) -> Router | None:
    """The WAN connection service in a router's description XML, or None."""
    u = urllib.parse.urlsplit(location)
    if u.scheme != "http" or u.hostname != ip:
        return None                                  # only the device that answered: no fetching elsewhere
    with _no_proxy().open(location, timeout=TIMEOUT) as r:
        root = ET.fromstring(r.read(200_000))
    base = next((e.text.strip() for e in root.iter() if _local(e.tag) == "URLBase" and e.text), "") or location
    best = None
    for svc in root.iter():
        if _local(svc.tag) != "service":
            continue
        kids = {_local(k.tag): (k.text or "").strip() for k in svc}
        kind, ctl = kids.get("serviceType", ""), kids.get("controlURL", "")
        if kind in SERVICES and ctl and (best is None or SERVICES.index(kind) < SERVICES.index(best[0])):
            best = (kind, ctl)
    if best is None:
        return None
    url = urllib.parse.urljoin(base, best[1])
    if urllib.parse.urlsplit(url).hostname != ip:
        return None
    return Router(url, best[0], ip, _lan_ip(ip))


def discover(target=SSDP_ADDR, timeout: float = TIMEOUT) -> Router | None:
    for ip, location in search(target, timeout):
        try:
            r = describe(ip, location)
        except (OSError, ET.ParseError, ValueError):
            continue
        if r is not None:
            return r
    return None


def soap(router: Router, action: str, args: list[tuple[str, str]]) -> dict:
    """One SOAP call; the answer's fields by name. A router's refusal raises UpnpError with its reason."""
    body = ('<?xml version="1.0"?>\r\n<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{router.service}">'
            + "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args)
            + f"</u:{action}></s:Body></s:Envelope>")
    req = urllib.request.Request(router.control_url, data=body.encode("utf-8"), method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{router.service}#{action}"'})
    try:
        with _no_proxy().open(req, timeout=TIMEOUT) as r:
            root = ET.fromstring(r.read(200_000))
    except urllib.error.HTTPError as e:
        why = f"HTTP {e.code}"
        try:
            fault = ET.fromstring(e.read(200_000))
            desc = next((x.text for x in fault.iter() if _local(x.tag) == "errorDescription" and x.text), "")
            code = next((x.text for x in fault.iter() if _local(x.tag) == "errorCode" and x.text), "")
            why = f"{desc} ({code})" if desc else why
        except (ET.ParseError, OSError):
            pass
        raise UpnpError(why) from None
    out = {}
    for e in root.iter():
        if _local(e.tag) == action + "Response":
            out = {_local(k.tag): (k.text or "").strip() for k in e}
    return out


def add_mapping(router: Router, port: int) -> None:
    soap(router, "AddPortMapping", [
        ("NewRemoteHost", ""), ("NewExternalPort", port), ("NewProtocol", "TCP"), ("NewInternalPort", port),
        ("NewInternalClient", router.lan_ip), ("NewEnabled", 1), ("NewPortMappingDescription", DESCRIPTION),
        ("NewLeaseDuration", 0)])


def delete_mapping(router: Router, port: int) -> None:
    soap(router, "DeletePortMapping", [("NewRemoteHost", ""), ("NewExternalPort", port), ("NewProtocol", "TCP")])


def external_address(router: Router) -> str:
    return soap(router, "GetExternalIPAddress", []).get("NewExternalIPAddress", "")


def ports_text(first: int, last: int) -> str:
    return f"port {first}" if first == last else f"ports {first}–{last}"


class Manager(QObject):
    """The main window's one UPnP helper. apply(cfg) after Settings; shutdown() when BChat quits."""
    changed = Signal(str)         # the status line for Settings
    _result = Signal(object)      # worker thread -> GUI thread

    def __init__(self, parent=None, target=SSDP_ADDR, timeout: float = TIMEOUT):
        super().__init__(parent)
        self.target, self.timeout = target, timeout
        self.status = ""
        self.external_ip = ""     # the router's outside address while ports are open: the DCC address
        self.ports_open = False   # 0.8.9: the router opened the DCC port range (Auto sending stays normal)
        self._want = None         # GUI side: (first, last) asked for, () = no range, None = off
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._router: Router | None = None   # worker thread only
        self.mapped: list[int] = []           # worker thread only (tests read it once idle)
        self._result.connect(self._on_result)

    # --- GUI side ------------------------------------------------------------------------

    def apply(self, cfg) -> None:
        want = None
        if cfg.upnp_on:
            first, last = int(cfg.dcc_first_port or 0), int(cfg.dcc_last_port or 0)
            want = (first, max(first, last)) if first else ()
        if want == self._want:
            return
        self._want = want
        self.external_ip = ""
        self.ports_open = False
        if want is None:
            self._set("")
            self._put(("unmap",))
        elif not want:
            self._set(NEED_RANGE)
            self._put(("unmap",))
        else:
            self._set(LOOKING)
            self._put(("map", want))

    def shutdown(self, wait: float = 2.0) -> None:
        """BChat is quitting: take the ports off the router (waits a moment for it, never long)."""
        self._want = None
        self.external_ip = ""
        self.ports_open = False
        if self._thread is None or not self._thread.is_alive():
            return
        self._q.put(("unmap",))
        self._q.put(None)
        self._thread.join(wait)

    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._q.unfinished_tasks > 0

    def _set(self, text: str) -> None:
        if text != self.status:
            self.status = text
            self.changed.emit(text)

    def _put(self, job) -> None:
        self._q.put(job)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._work, name="bchat-upnp", daemon=True)
            self._thread.start()

    def _on_result(self, res) -> None:
        want, ip, text = res
        if want != self._want:
            return                          # the tick changed while the router was asked: old news
        self.external_ip = ip
        self.ports_open = text.startswith(OPENED)
        self._set(text)

    # --- worker thread -------------------------------------------------------------------

    def _work(self) -> None:
        while True:
            job = self._q.get()
            try:
                if job is None:
                    return
                if job[0] == "unmap":
                    self._unmap()
                else:
                    self._result.emit(self._map(job[1]))
            except Exception as e:          # a worker thread must never die with jobs queued behind it
                if job and job[0] == "map":
                    self._result.emit((job[1], "", f"Router error: {e}"))
            finally:
                self._q.task_done()

    def _unmap(self) -> None:
        r, ports, self.mapped = self._router, self.mapped, []
        for p in ports:
            try:
                delete_mapping(r, p)
            except (OSError, UpnpError, ET.ParseError):
                pass

    def _map(self, want: tuple[int, int]):
        first, last = want
        last = min(last, first + MAX_PORTS - 1)
        if self.mapped and (self.mapped[0], self.mapped[-1]) != (first, last):
            self._unmap()
        if self._router is None:
            self._router = discover(self.target, self.timeout)
        r = self._router
        if r is None:
            return want, "", NO_ROUTER
        try:
            for p in range(first, last + 1):
                if p not in self.mapped:
                    add_mapping(r, p)
                    self.mapped.append(p)
            outside = external_address(r)
        except (OSError, UpnpError, ET.ParseError) as e:
            self._unmap()
            self._router = None             # look again next time: the router may have changed
            return want, "", f"Router found, but it refused to open the ports ({e})"
        shown = outside or "unknown"
        return want, outside, f"{OPENED} {shown} · {ports_text(first, last)} open"
