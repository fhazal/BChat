"""Python plugins with XChat's Python interface (xchat-python docs): a script for XChat 2 mostly just works.
Plugins run as the user with full access, so nothing loads except what the user picks or puts in the addons folder."""
from __future__ import annotations

import sys
import traceback
import types
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from . import commands
from .protocol import lower, strip_format

EAT_NONE, EAT_XCHAT, EAT_PLUGIN, EAT_ALL = 0, 1, 2, 3
PRI_HIGHEST, PRI_HIGH, PRI_NORM, PRI_LOW, PRI_LOWEST = 127, 64, 0, -64, -128


class Hook:
    def __init__(self, plugin, kind: str, name: str, cb, userdata, priority: int = 0):
        self.plugin, self.kind, self.name, self.cb, self.userdata, self.priority = plugin, kind, name, cb, userdata, priority
        self.timer: QTimer | None = None


class Plugin:
    def __init__(self, mgr, path: Path):
        self.mgr, self.path = mgr, path
        self.name, self.version, self.description = path.stem, "", ""
        self.hooks: list[Hook] = []
        self.api = self._make_api()

    def _make_api(self) -> types.ModuleType:
        api = types.ModuleType("xchat")
        mgr = self.mgr
        for key, value in (("EAT_NONE", EAT_NONE), ("EAT_XCHAT", EAT_XCHAT), ("EAT_PLUGIN", EAT_PLUGIN), ("EAT_ALL", EAT_ALL),
                           ("PRI_HIGHEST", PRI_HIGHEST), ("PRI_HIGH", PRI_HIGH), ("PRI_NORM", PRI_NORM), ("PRI_LOW", PRI_LOW), ("PRI_LOWEST", PRI_LOWEST)):
            setattr(api, key, value)

        def add(kind, name, cb, userdata=None, priority=0, **_):
            h = Hook(self, kind, lower(name), cb, userdata, priority)
            self.hooks.append(h)
            return h
        api.hook_command = lambda name, cb, userdata=None, priority=0, help=None: add("command", name, cb, userdata, priority)
        api.hook_server = lambda name, cb, userdata=None, priority=0: add("server", name, cb, userdata, priority)
        api.hook_print = lambda name, cb, userdata=None, priority=0: add("print", name, cb, userdata, priority)

        def hook_timer(ms, cb, userdata=None):
            h = add("timer", "", cb, userdata)
            h.timer = QTimer(mgr)
            h.timer.timeout.connect(lambda: mgr.fire_timer(h))
            h.timer.start(int(ms))
            return h
        api.hook_timer = hook_timer
        api.hook_unload = lambda cb, userdata=None: add("unload", "", cb, userdata)

        def unhook(h):
            if isinstance(h, Hook) and h in self.hooks:
                if h.timer is not None:
                    h.timer.stop()
                self.hooks.remove(h)
        api.unhook = unhook
        api.prnt = lambda text: mgr.prnt(str(text))
        api.command = lambda text: mgr.command(str(text))
        api.emit_print = lambda event, *args: mgr.emit_print(event, args)
        api.get_info = mgr.get_info
        api.get_prefs = lambda name: None
        api.nickcmp = lambda a, b: (lower(a) > lower(b)) - (lower(a) < lower(b))
        api.strip = lambda text, length=-1, flags=3: strip_format(text)
        api.get_list = mgr.get_list
        api.get_context = lambda: Context(mgr, mgr.win.buf)
        api.find_context = lambda server=None, channel=None: mgr.find_context(server, channel)
        return api

    def fire(self, h: Hook, *args):
        try:
            return h.cb(*args, h.userdata)
        except Exception:
            self.mgr.prnt(f"Error in {self.name}:\n{traceback.format_exc().strip()}")
            return EAT_NONE


class Context:
    def __init__(self, mgr, buf):
        self.mgr, self.buf = mgr, buf

    def prnt(self, text):
        if self.buf is not None:
            self.buf.session.add(self.buf, "info", "*", str(text))

    def command(self, text):
        if self.buf is not None:
            commands.run(self.mgr.win, self.buf.session, self.buf, "/" + str(text).lstrip("/"))

    def set(self):
        self.mgr.win.select_buffer(self.buf)

    def get_info(self, name):
        return self.mgr.get_info(name, self.buf)

    def get_list(self, name):
        return self.mgr.get_list(name, self.buf)

    def emit_print(self, event, *args):
        self.mgr.emit_print(event, args, self.buf)


class _Row:
    def __init__(self, **values):
        self.__dict__.update(values)


class PluginManager(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.plugins: list[Plugin] = []
        self._busy = 0

    @property
    def folder(self) -> Path:
        return self.win.cfg_dir / "addons"

    def autoload(self) -> None:
        if self.folder.is_dir():
            for p in sorted(self.folder.glob("*.py")):
                self.load(str(p))

    def load(self, path: str) -> Plugin | None:
        p = Path(path)
        for old in self.plugins:
            if old.path == p:
                self.report(f"{p.name} is already loaded.")
                return old
        plugin = Plugin(self, p)
        scope = {"__name__": "__xchat_script__", "__file__": str(p)}
        saved = {k: sys.modules.get(k) for k in ("xchat", "bchat_api")}
        sys.modules["xchat"] = sys.modules["bchat_api"] = plugin.api
        try:
            source = p.read_bytes()
            exec(compile(source, str(p), "exec"), scope)
        except (Exception, SystemExit):
            self.report(f"Couldn't load {p.name}:\n{traceback.format_exc().strip()}")
            for h in plugin.hooks:
                if h.timer is not None:
                    h.timer.stop()
            return None
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        plugin.name = str(scope.get("__module_name__", p.stem))
        plugin.version = str(scope.get("__module_version__", ""))
        plugin.description = str(scope.get("__module_description__", ""))
        self.plugins.append(plugin)
        self.report(f"{plugin.name} {plugin.version} loaded.")
        return plugin

    def unload(self, plugin: Plugin) -> None:
        for h in list(plugin.hooks):
            if h.kind == "unload":
                plugin.fire(h)
            if h.timer is not None:
                h.timer.stop()
        plugin.hooks.clear()
        if plugin in self.plugins:
            self.plugins.remove(plugin)
        self.report(f"{plugin.name} unloaded.")

    def reload(self, plugin: Plugin) -> Plugin | None:
        path = plugin.path
        self.unload(plugin)
        return self.load(str(path))

    def find(self, name: str) -> Plugin | None:
        low = name.lower()
        for p in self.plugins:
            if p.name.lower() == low or p.path.name.lower() == low or str(p.path).lower() == low:
                return p
        return None

    def report(self, text: str) -> None:
        self.prnt(text)

    def _front(self):
        b = self.win.buf
        if b is not None:
            return b
        for s in self.win.sessions.values():
            return s.server_buffer
        return None

    def prnt(self, text: str) -> None:
        b = self._front()
        if b is not None:
            for row in text.split("\n"):
                b.session.add(b, "info", "*", row)

    def command(self, text: str) -> None:
        b = self._front()
        if b is not None:
            commands.run(self.win, b.session, b, "/" + text.lstrip("/"))

    def emit_print(self, event, args, buf=None) -> None:
        from .textevents import EVENTS, render
        b = buf or self._front()
        if b is None:
            return
        fmt = self.win.cfg.text_events.get(event) or (EVENTS[event][0] if event in EVENTS else "")
        if fmt:
            left, text = render(fmt, [str(a) for a in args])
            b.session.add(b, "info", left, text)

    def get_info(self, name: str, buf=None):
        b = buf or self._front()
        s = b.session if b is not None else None
        name = name.lower()
        values = {"version": __import__("bchat").full_version(), "xchatdir": str(self.win.cfg_dir), "xchatdirfs": str(self.win.cfg_dir),
                  "configdir": str(self.win.cfg_dir), "win_status": "active" if self.win.isActiveWindow() else "normal"}
        if s is not None:
            values.update(nick=s.nick, channel=b.name, server=s.server_name, network=s.net.name, host=s.net.name,
                          topic=b.topic, away=self.win.cfg.away_reason if s.away else None, modes=b.mode_text())
        return values.get(name)

    def get_list(self, name: str, buf=None):
        b = buf or self._front()
        name = name.lower()
        if name == "channels":
            return [_Row(channel=x.name, server=s.server_name, network=s.net.name, type={"server": 1, "channel": 2, "query": 3}[x.kind],
                         context=Context(self, x), users=len(x.users), flags=0, id=id(x))
                    for s in self.win.sessions.values() for x in s.all_buffers()]
        if name == "users" and b is not None:
            return [_Row(nick=u.nick, host=u.host, prefix=u.prefixes[:1], realname=u.realname, away=int(u.away), account=getattr(u, "account", "")) for u in b.sorted_users()]
        if name == "ignore":
            return [_Row(mask=m, flags=0) for m in self.win.cfg.ignores]
        if name == "notify":
            return [_Row(nick=n, flags=0, on=0, off=0, seen=0) for n in self.win.cfg.friends]
        if name == "dcc":
            return [_Row(nick=t.nick, file=t.name, size=t.size, pos=t.pos, status=t.state, type=t.kind) for t in self.win.dcc.items]
        return []

    def find_context(self, server=None, channel=None):
        for s in self.win.sessions.values():
            if server and lower(server) not in (lower(s.server_name or ""), lower(s.net.name)):
                continue
            if channel is None:
                return Context(self, s.server_buffer)
            b = s.buffers.get(s.fold(channel))
            if b is not None:
                return Context(self, b)
        return None

    # --- called from the rest of BChat. True means a plugin ate it ---------------------------

    def _hooks(self, kind: str, name: str) -> list[Hook]:
        name = lower(name)
        found = [h for p in self.plugins for h in p.hooks if h.kind == kind and h.name == name]
        return sorted(found, key=lambda h: -h.priority)

    @staticmethod
    def _eol(word: list[str]) -> list[str]:
        return [" ".join(word[i:]) for i in range(len(word))]

    def on_command(self, text: str) -> bool:
        word = text[1:].split()
        if not word:
            return False
        eaten = False
        for h in self._hooks("command", word[0]):
            r = h.plugin.fire(h, word, self._eol(word))
            eaten = eaten or r in (EAT_XCHAT, EAT_ALL)
            if r in (EAT_PLUGIN, EAT_ALL):
                break
        return eaten

    def on_server(self, s, raw: str, command: str) -> bool:
        hooks = self._hooks("server", command) + self._hooks("server", "raw line")
        if not hooks:
            return False
        word = raw.split()
        eol = self._eol(word)
        eaten = False
        for h in hooks:
            r = h.plugin.fire(h, word, eol)
            eaten = eaten or r in (EAT_XCHAT, EAT_ALL)
            if r in (EAT_PLUGIN, EAT_ALL):
                break
        return eaten

    def on_print(self, event: str, args) -> bool:
        hooks = self._hooks("print", event)
        if not hooks or self._busy:
            return False
        self._busy += 1
        try:
            word = [str(a) for a in args]
            eaten = False
            for h in hooks:
                r = h.plugin.fire(h, word)
                eaten = eaten or r in (EAT_XCHAT, EAT_ALL)
                if r in (EAT_PLUGIN, EAT_ALL):
                    break
            return eaten
        finally:
            self._busy -= 1

    def fire_timer(self, h: Hook) -> None:
        if not h.plugin.fire(h):
            if h.timer is not None:
                h.timer.stop()
            if h in h.plugin.hooks:
                h.plugin.hooks.remove(h)
