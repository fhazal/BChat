"""Python plugins with XChat's Python interface (xchat-python docs): a script for XChat 2 mostly just works.
Plugins run as the user with full access, so nothing loads except what the user picks or puts in the addons folder.
0.8.0 adds mIRC's event names (bchat.on_text ...), menu items in the Popups menus, and settings a script keeps."""
from __future__ import annotations

import builtins
import json
import sys
import traceback
import types
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from . import commands
from .protocol import lower, parse_line, strip_format

EAT_NONE, EAT_XCHAT, EAT_PLUGIN, EAT_ALL = 0, 1, 2, 3
PRI_HIGHEST, PRI_HIGH, PRI_NORM, PRI_LOW, PRI_LOWEST = 127, 64, 0, -64, -128
EVENTS = ("text", "action", "notice", "join", "part", "quit", "kick", "nick", "mode", "topic", "invite", "connect",
          "disconnect", "ctcp")
MENU_KEYS = {"channel": "channel", "private chat": "query", "query": "query", "server tab": "server", "server": "server",
             "status": "server", "nick list": "nicklist", "nicklist": "nicklist", "menu bar": "menubar", "menubar": "menubar"}
API_NAMES = ("xchat", "bchat", "hexchat")


class Hook:
    def __init__(self, plugin, kind: str, name: str, cb, userdata, priority: int = 0):
        self.plugin, self.kind, self.name, self.cb, self.userdata, self.priority = plugin, kind, name, cb, userdata, priority
        self.timer: QTimer | None = None


class Event(types.SimpleNamespace):
    """What an event or menu function gets: network, channel, nick, text, me, and more for some events
    (target: who was kicked, newnick, word: what was right-clicked, nicks: the selected nicks)."""

    def __init__(self, **kw):
        base = dict(event="", network="", channel="", nick="", text="", me="", target="", newnick="", word="",
                    nicks=[], raw="", context=None)
        base.update(kw)
        super().__init__(**base)


class MenuItem:
    def __init__(self, plugin, menu: str, name: str, target):
        self.plugin, self.menu, self.name, self.target = plugin, menu, name, target


def error_line(path: Path, exc: BaseException) -> tuple[int, str]:
    """The line in the script where it went wrong (0 = not in the script itself), and a one-line message."""
    if isinstance(exc, SyntaxError) and exc.filename == str(path):
        return exc.lineno or 0, f"{type(exc).__name__}: {exc.msg}"
    line = 0
    for fr in traceback.extract_tb(exc.__traceback__):
        if fr.filename == str(path):
            line = fr.lineno or 0
    return line, f"{type(exc).__name__}: {exc}"


class Plugin:
    def __init__(self, mgr, path: Path):
        self.mgr, self.path = mgr, path
        self.name, self.version, self.description = path.stem, "", ""
        self.hooks: list[Hook] = []
        self.menu_items: list[MenuItem] = []
        self.errors_seen: set = set()
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

        # 0.8.0: mIRC's events, menu items, settings a script keeps between starts
        def on(event, cb, userdata=None):
            name = str(event).lower()
            name = name[3:] if name.startswith("on_") else name
            if name not in EVENTS:
                raise ValueError(f"there is no event called {event!r}; there are: {', '.join(EVENTS)}")
            return add("event", name, cb, userdata)
        api.on = on
        for ev in EVENTS:
            setattr(api, "on_" + ev, lambda cb, userdata=None, ev=ev: on(ev, cb, userdata))

        def add_menu_item(menu, name, target):
            key = MENU_KEYS.get(str(menu).lower())
            if key is None:
                raise ValueError(f"there is no menu called {menu!r}; there are: Channel, Private chat, Server tab, Nick list, Menu bar")
            item = MenuItem(self, key, str(name), target)
            self.menu_items.append(item)
            mgr.menus_changed(key)
            return item
        api.add_menu_item = add_menu_item

        def del_menu_item(item):
            if item in self.menu_items:
                self.menu_items.remove(item)
                mgr.menus_changed(item.menu)
        api.del_menu_item = del_menu_item
        api.set_pluginpref = lambda name, value: mgr.set_pref(self, str(name), value)
        api.get_pluginpref = lambda name: mgr.get_pref(self, str(name))
        api.del_pluginpref = lambda name: mgr.del_pref(self, str(name))
        api.list_pluginpref = lambda: mgr.list_pref(self)

        def rest_of_bchat(name):
            """`import bchat` gives a script this API; `from bchat import config` (BChat's own modules) still works."""
            import importlib
            pkg = importlib.import_module("bchat")
            if name.startswith("__"):
                raise AttributeError(name)
            try:
                return getattr(pkg, name)
            except AttributeError:
                try:
                    return importlib.import_module(f"bchat.{name}")
                except ImportError:
                    raise AttributeError(f"bchat has no {name!r}") from None
        api.__getattr__ = rest_of_bchat
        return api

    def fire(self, h: Hook, *args):
        try:
            return h.cb(*args, h.userdata)
        except Exception as e:
            self.report_error(e)
            return EAT_NONE

    def call(self, fn, *args):
        """A function of the script's own (event, menu item); errors reported the same way."""
        try:
            return fn(*args)
        except Exception as e:
            self.report_error(e)
            return None

    def report_error(self, exc: BaseException) -> None:
        """Once per line and message, in the server tab, with a link that opens the Scripts window there."""
        line, msg = error_line(self.path, exc)
        if (line, msg) in self.errors_seen:
            return
        self.errors_seen.add((line, msg))
        self.mgr.script_error(self, line, msg)


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
        self._prefs: dict | None = None
        self._states: dict = {}
        self.last_error: tuple[Path, int, str] | None = None     # the newest load error, for the Scripts window

    @property
    def folder(self) -> Path:
        return self.win.cfg_dir / "addons"

    @property
    def menu_items(self) -> list[MenuItem]:
        return [x for p in self.plugins for x in p.menu_items]

    def autoload(self) -> None:
        off = {n.lower() for n in getattr(self.win.cfg, "scripts_off", [])}
        if self.folder.is_dir():
            for p in sorted(self.folder.glob("*.py")):
                if p.name.lower() not in off:
                    self.load(str(p))

    def _exec(self, p: Path) -> Plugin | None:
        """Run the file as a new Plugin, not yet in the list. None (and last_error set) when it doesn't load."""
        plugin = Plugin(self, p)
        real_import = builtins.__import__

        def script_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and name in API_NAMES:
                return plugin.api                      # import bchat / import xchat: this script's own API
            return real_import(name, globals, locals, fromlist, level)
        scope = {"__name__": "__xchat_script__", "__file__": str(p),
                 "__builtins__": dict(builtins.__dict__, __import__=script_import)}
        saved = {k: sys.modules.get(k) for k in ("xchat", "bchat_api")}
        sys.modules["xchat"] = sys.modules["bchat_api"] = plugin.api
        try:
            exec(compile(p.read_bytes(), str(p), "exec"), scope)
        except (Exception, SystemExit) as e:
            line, msg = error_line(p, e)
            self.last_error = (p, line, msg)
            for h in plugin.hooks:
                if h.timer is not None:
                    h.timer.stop()
            plugin.hooks.clear()
            plugin.menu_items.clear()
            return None
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.last_error = None
        plugin.name = str(scope.get("__module_name__", p.stem))
        plugin.version = str(scope.get("__module_version__", ""))
        plugin.description = str(scope.get("__module_description__", ""))
        return plugin

    def _start(self, plugin: Plugin) -> None:
        self.plugins.append(plugin)
        for k in {x.menu for x in plugin.menu_items}:
            self.menus_changed(k)

    def load(self, path: str) -> Plugin | None:
        p = Path(path)
        for old in self.plugins:
            if old.path == p:
                self.report(f"{p.name} is already loaded.")
                return old
        plugin = self._exec(p)
        if plugin is None:
            _p, line, msg = self.last_error
            self.report(f"Couldn't load {p.name}" + (f", line {line}" if line else "") + f": {msg}")
            return None
        self._start(plugin)
        self.report(f"{plugin.name} {plugin.version} loaded.")
        return plugin

    def unload(self, plugin: Plugin, quiet: bool = False) -> None:
        for h in list(plugin.hooks):
            if h.kind == "unload":
                plugin.fire(h)
            if h.timer is not None:
                h.timer.stop()
        plugin.hooks.clear()
        menus = {x.menu for x in plugin.menu_items}
        plugin.menu_items.clear()
        if plugin in self.plugins:
            self.plugins.remove(plugin)
        for k in menus:
            self.menus_changed(k)
        if not quiet:
            self.report(f"{plugin.name} unloaded.")

    def reload(self, plugin: Plugin) -> Plugin | None:
        path = plugin.path
        self.unload(plugin)
        return self.load(str(path))

    def replace(self, path: Path) -> tuple[Plugin | None, int, str]:
        """Scripts window Save: the file runs again. The new version starts first; only when it loads does the old one
        stop, so a mistake never takes down the running version. Returns (what runs now, error line, error message)."""
        path = Path(path)
        old = next((x for x in self.plugins if x.path == path), None)
        new = self._exec(path)
        if new is None:
            _p, line, msg = self.last_error
            return old, line, msg
        if old is not None:
            self.unload(old, quiet=True)
        self._start(new)
        self.report(f"{new.name} {new.version} " + ("reloaded." if old is not None else "loaded."))
        return new, 0, ""

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

    def script_error(self, plugin: Plugin, line: int, msg: str) -> None:
        b = self._front()
        if b is None:
            return
        target = b.session.server_buffer
        where = f", line {line}" if line else ""
        target.session.add(target, "error", "*", f"Script {plugin.path.name}{where}: {msg}  "
                                                  f"bchat-script://{plugin.path.name}/{line}")

    def command(self, text: str) -> None:
        b = self._front()
        if b is not None:
            commands.run(self.win, b.session, b, "/" + text.lstrip("/"))

    def emit_print(self, event, args, buf=None) -> None:
        from .textevents import EVENTS as TEXT_EVENTS, render
        b = buf or self._front()
        if b is None:
            return
        fmt = self.win.cfg.text_events.get(event) or (TEXT_EVENTS[event][0] if event in TEXT_EVENTS else "")
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

    # --- 0.8.0: menu items and settings ----------------------------------------------------------------------

    def menus_changed(self, key: str) -> None:
        if key == "menubar" and hasattr(self.win, "menubar_"):
            from .popups import sync_menubar
            sync_menubar(self.win)

    def run_menu_item(self, item: MenuItem, b, word: str = "", nicks: list[str] | None = None) -> None:
        if b is None:
            return
        if isinstance(item.target, str):
            from .popups import run_item
            run_item(self.win, b, item.target, nicks, word)
            return
        s = b.session
        e = Event(event="menu", network=s.net.name, channel=b.name if b.kind == "channel" else "", me=s.nick,
                  nick=(nicks[0] if nicks else (b.name if b.kind == "query" else "")), nicks=list(nicks or []),
                  word=word, context=Context(self, b))
        item.plugin.call(item.target, e)

    @property
    def _prefs_file(self) -> Path:
        return self.win.cfg_dir / "scriptprefs.json"

    def _all_prefs(self) -> dict:
        if self._prefs is None:
            try:
                self._prefs = json.loads(self._prefs_file.read_text("utf-8"))
            except (OSError, ValueError):
                self._prefs = {}
        return self._prefs

    def _save_prefs(self) -> None:
        try:
            self._prefs_file.parent.mkdir(parents=True, exist_ok=True)
            self._prefs_file.write_text(json.dumps(self._prefs, indent=1, ensure_ascii=False), "utf-8")
        except OSError:
            pass

    def set_pref(self, plugin: Plugin, name: str, value) -> bool:
        if not isinstance(value, (str, int, float, bool)):
            value = str(value)
        self._all_prefs().setdefault(plugin.name, {})[name] = value
        self._save_prefs()
        return True

    def get_pref(self, plugin: Plugin, name: str):
        return self._all_prefs().get(plugin.name, {}).get(name)

    def del_pref(self, plugin: Plugin, name: str) -> bool:
        mine = self._all_prefs().get(plugin.name, {})
        if name in mine:
            del mine[name]
            self._save_prefs()
        return True

    def list_pref(self, plugin: Plugin) -> list[str]:
        return list(self._all_prefs().get(plugin.name, {}))

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
        eaten = False
        if hooks:
            word = raw.split()
            eol = self._eol(word)
            for h in hooks:
                r = h.plugin.fire(h, word, eol)
                eaten = eaten or r in (EAT_XCHAT, EAT_ALL)
                if r in (EAT_PLUGIN, EAT_ALL):
                    break
        if any(h.kind == "event" for p in self.plugins for h in p.hooks):
            self._server_event(s, raw)
        return eaten

    def _fire_event(self, name: str, s, **kw) -> None:
        hooks = self._hooks("event", name)
        if not hooks:
            return
        chan = kw.get("channel", "")
        b = (s.buffers.get(s.fold(chan)) if chan else None) or s.server_buffer
        e = Event(event=name, network=s.net.name, me=s.nick, context=Context(self, b), **kw)
        for h in hooks:
            if h.userdata is None:
                h.plugin.call(h.cb, e)
            else:
                h.plugin.call(h.cb, e, h.userdata)

    def _server_event(self, s, raw: str) -> None:
        """mIRC's events from the line the server sent. A private message has channel ''."""
        m = parse_line(raw)
        cmd, nick = m.command.upper(), m.nick
        first = m.param(0)
        chan = first if first and s.is_channel(first) else ""
        text = m.param(-1) if len(m.params) > 1 else ""
        if cmd in ("PRIVMSG", "NOTICE"):
            if text.startswith("\x01"):
                body = text.strip("\x01")
                kind, _, rest = body.partition(" ")
                if cmd == "PRIVMSG" and kind.upper() == "ACTION":
                    self._fire_event("action", s, nick=nick, channel=chan, text=rest, raw=raw)
                elif cmd == "PRIVMSG":
                    self._fire_event("ctcp", s, nick=nick, channel=chan, text=body, raw=raw)
                return
            self._fire_event("text" if cmd == "PRIVMSG" else "notice", s, nick=nick, channel=chan, text=text, raw=raw)
        elif cmd == "JOIN":
            self._fire_event("join", s, nick=nick, channel=first, raw=raw)
        elif cmd == "PART":
            self._fire_event("part", s, nick=nick, channel=first, text=text, raw=raw)
        elif cmd == "QUIT":
            self._fire_event("quit", s, nick=nick, text=m.param(0), raw=raw)
        elif cmd == "KICK":
            self._fire_event("kick", s, nick=nick, channel=first, target=m.param(1), text=m.param(2), raw=raw)
        elif cmd == "NICK":
            self._fire_event("nick", s, nick=nick, newnick=first, raw=raw)
        elif cmd == "MODE":
            self._fire_event("mode", s, nick=nick, channel=chan, target=first, text=" ".join(m.params[1:]), raw=raw)
        elif cmd == "TOPIC":
            self._fire_event("topic", s, nick=nick, channel=first, text=m.param(1), raw=raw)
        elif cmd == "INVITE":
            self._fire_event("invite", s, nick=nick, channel=m.param(1), target=first, raw=raw)

    def on_state(self, s) -> None:
        """connect / disconnect, from the session's state."""
        before = self._states.get(id(s))
        now = s.state
        self._states[id(s)] = now
        if now == before:
            return
        if now == "connected":
            self._fire_event("connect", s, nick=s.nick)
        elif now == "disconnected" and before == "connected":
            self._fire_event("disconnect", s, nick=s.nick)

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
