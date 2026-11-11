"""Second check on the built BChat.exe: everything added for TEST14 that the normal tests can't prove from source.
Temp settings and local sockets only. A probe plugin in the temp addons folder opens every window from inside the exe,
so this also proves plugins load in the frozen app, and a real DCC file comes in over a local socket."""
import json, os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path

from qa_common import ROOT, finish, parse_args
sys.path.insert(0, str(ROOT / "tests"))
from fake_ircd import FakeIrcd

ARGS = parse_args("Packaged app: a probe plugin inside the exe opens every window and checks what source tests can't prove.")
EXE = ARGS.exe
tmp = Path(tempfile.mkdtemp())
srv = FakeIrcd()
cfgdir = tmp / "cfg"
(cfgdir / "addons").mkdir(parents=True)
inbox = tmp / "in"
report = tmp / "report.json"
(cfgdir / "config.json").write_text(json.dumps({
    "nick": "Badaboom", "imported": True, "skip_network_list": True, "dcc_auto": 1, "dcc_dir": str(inbox),
    "networks": [{"name": "SkinIRC", "servers": [{"host": "127.0.0.1", "port": srv.port}], "autojoin": "#skinhead", "autoconnect": True}]}))

PROBE = r'''
__module_name__ = "probe"
__module_version__ = "1"
__module_description__ = "frozen check"
import xchat, json, importlib, traceback
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
results = {}
REPORT = %r
def note(name, fn):
    try:
        results[name] = bool(fn())
    except Exception:
        results[name] = False
        results[name + " (error)"] = traceback.format_exc()[-400:]
def run(userdata):
    from bchat.mainwindow import MainWindow, speller
    from bchat.preferences import BUILT, CATEGORIES, PreferencesDialog
    win = [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)][0]
    s = win.session
    note("spell word list loads", lambda: speller() is not None and speller().known(["hello"]) and not speller().known(["helo"]))
    def spell_marks():
        win.cfg.spell_check = True
        win.input.setText("helo there ")
        win.input.mark_spelling()
        ok = [win.input.text()[a:z] for a, z in win.input.bad_words] == ["helo"]
        win.input.clear()
        win.cfg.spell_check = False
        return ok
    note("spell marks a word", spell_marks)
    for key in ("chart", "friends", "ignore", "urls", "plugins"):
        note("window " + key, lambda k=key: win.open_tool(k).isVisible())
    note("window channel list", lambda: win.open_channel_list(s, download=False).isVisible())
    win.select_buffer(s.buffers["#skinhead"])
    note("window ban list", lambda: win.open_ban_list().isVisible())
    note("window file transfers", lambda: win.open_transfers().isVisible())
    note("window direct chat", lambda: win.open_chats().isVisible())
    note("window help", lambda: win.open_help().isVisible())
    for key in ("replace", "ctcp", "commands", "url", "dialog", "ulbuttons", "popup", "events", "keys"):
        def ed(k=key):
            d = win.open_editor(k)
            ok = d.isVisible()
            d.reject()
            return ok
        note("editor " + key, ed)
    def pages():
        d = PreferencesDialog(win)
        names = [p for g in CATEGORIES.values() for p in g]
        for n in names:
            d.show_page(n)
        d.reject()
        return set(names) == set(BUILT)
    note("all preferences pages", pages)
    note("no disabled menu items", lambda: all(a.isEnabled() for a in win.named_actions().values()))
    def detach():
        b = s.buffers["#skinhead"]
        win.detach(b)
        ok = win.detached[id(b)].isVisible()
        win.attach(b)
        return ok and id(b) not in win.detached
    note("detach and attach", detach)
    def tabs():
        win.set_tab_layout("tabs")
        ok = win.tabbar.isVisible() and win.tabbar.count() == 2
        win.set_tab_layout("tree")
        return ok and win.tree.isVisible()
    note("tabs and tree", tabs)
    def tree():
        rows = win._buffer_rows()
        f = win.items[id(s.buffers["#skinhead"])].parent()
        return f.text(0).startswith("Channel: ") and not f.flags() & Qt.ItemFlag.ItemIsSelectable and len(rows) >= 2 and all(not r.icon(0).isNull() for r in rows)
    note("tree folders and icons", tree)
    def tray_setup():
        win.cfg.minimize_to_tray = True
        win._sync_tray()
        return win.tray is not None and win.tray.isVisible()
    note("tray icon comes by itself", tray_setup)
    def sound():
        win.cfg.sounds["x"] = r"C:\Windows\Media\ding.wav"
        win._play_sound("x")
        del win.cfg.sounds["x"]
        return True
    note("sound call doesn't fail", sound)
    note("autostart skipped from no crash", lambda: callable(win.set_autostart))
    # TEST3 (0.3.0): Start with Windows self-repair, on a throwaway key; the real Run value is never changed here
    def autostart_check():
        import winreg
        from bchat import autostart as a
        real = a.current()
        k = r"Software\BChatFrozenCheck\Run"
        exe = a.installed_exe()
        ok = exe is not None and exe.lower().endswith("bchat.exe")
        ok = ok and a.sync(True, exe, k) == "added" and a.current(k) == a.command(exe) and a.sync(False, exe, k) == "removed"
        for sub in (k, r"Software\BChatFrozenCheck"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
        return ok and win.check_autostart() == "ok" and a.current() == real   # unticked fresh settings: real entry left alone
    note("Start with Windows repairs itself (real entry untouched)", autostart_check)
    # TEST17: version, About with the bee, signature check inside the exe, update entry + window
    from bchat import full_version, updater as up
    SIGNED = %%SIGNED%%
    EXPECT = %%EXPECT%%
    note("full version is " + EXPECT, lambda: full_version() == EXPECT)
    def about():
        d = win._about_box()
        ok = d.values["Version"].text() == EXPECT and d.values["Built"].text() not in ("source", "unknown")
        ok = ok and not d.logo.pixmap().isNull() and d.logo.width() == 120 and "bajubesi.org" in d.link.text()
        return ok
    note("about window: version, build date, bee, link", about)
    note("release signature checks out in the exe", lambda: up.signature_ok(SIGNED))
    note("tampered release refused in the exe", lambda: not up.signature_ok(dict(SIGNED, version="9.9.9")))
    note("update entry hidden when nothing to do", lambda: not win.update_act.isVisible())
    def upd_window():
        win.check_updates()
        d = win.update_window
        ok = d is not None and d.isVisible() and "api.github.com/repos/fhazal/BChat/releases" in up.UPDATE_URL
        d.close()
        return ok
    note("check for updates window opens", upd_window)
    note("updater can install from the exe", lambda: win.updater.can_install is True)
    # TEST25: the update entry sits on the menu bar's own colour (TEST17-24 painted a dark box)
    def badge_bg():
        from bchat import updater as _up
        from PySide6.QtGui import QColor
        old = (win.updater.state, win.updater.entry)
        win.updater._set(_up.FAILED, "probe")
        for _ in range(5):
            QApplication.processEvents()
        bar = win.menubar_
        img = bar.grab().toImage(); dpr = img.devicePixelRatio()
        g = bar.actionGeometry(win.update_act)
        a = QColor(img.pixel(int((g.right() - 2) * dpr), int((g.top() + 2) * dpr))).name()
        b = QColor(img.pixel(int((bar.width() - 6) * dpr), int((g.top() + 2) * dpr))).name()
        win.updater.entry = old[1]; win.updater._set(old[0])
        return g.isValid() and a == b
    note("update entry has the menu bar's background", badge_bg)
    # TEST24: Preferences > BChat > Updates card, About status, Help icon
    def updates_page():
        from bchat.preferences import PreferencesDialog
        from bchat import updater as _up
        d = PreferencesDialog(win, "Updates"); d.show()
        u = win.updater
        old = (u.state, u.entry)
        u.entry = {"version": "9.9.9", "size": 1000000, "notes": ["probe"]}; u._set(_up.AVAILABLE)
        ok = d.title.text() == "Updates" and "9.9.9" in d.upd_card.title.text() and not d.upd_card.button.icon().isNull()
        ok = ok and d.upd_card.news.isVisible() and d.upd_card.ring.icon_name == "new-version"
        a = win._about_box(); ok = ok and "9.9.9 is here" in a.update_status.text(); a.close()
        u.entry = old[1]; u._set(old[0]); d.reject()
        hm = next(x.menu() for x in win.menubar_.actions() if x.menu() and "Help" in x.text())
        return ok and all(not x.icon().isNull() for x in hm.actions() if not x.isSeparator())
    note("Updates page card, About status and Help icons in the exe", updates_page)
    # TEST22: welcome window (first start) and the Ko-fi line
    def welcome_win():
        from bchat.welcome import WelcomeDialog, first_start_action
        from bchat.config import Config
        d = WelcomeDialog(win); d.show()
        ok = (not d.bee.pixmap().isNull() and len(d.cards) == 3 and d.chosen()[0] == "BajuBesi Community"
              and d.connect_btn.isEnabled() and first_start_action(Config(), False) == "welcome")
        d.close()
        return ok
    note("welcome window: bee, three networks, BajuBesi first", welcome_win)
    def kofi():
        d = win._about_box()
        ok = "ko-fi.com/bajubesi" in d.support.text() and any("Ko-fi" in x.text() for a in win.menubar_.actions() if a.menu() for x in a.menu().actions())
        d.close()
        return ok
    note("Ko-fi line in About and Help menu", kofi)
    def themes():
        from dataclasses import fields
        from bchat.config import THEME_NAMES, Theme, make_theme
        keep = make_theme(win.cfg.theme.name)
        ok = len(THEME_NAMES) == 17
        for name in THEME_NAMES:
            fresh = make_theme(name)
            for f in fields(Theme):
                setattr(win.cfg.theme, f.name, list(fresh.palette) if f.name == "palette" else getattr(fresh, f.name))
            win.apply_preferences()
            ok = ok and win.cfg.theme.chat_bg in win.styleSheet()
        for f in fields(Theme):
            setattr(win.cfg.theme, f.name, list(keep.palette) if f.name == "palette" else getattr(keep, f.name))
        win.apply_preferences()
        return ok
    note("all 17 themes apply in the exe", themes)
    # TEST30: /np reads Windows' media controls inside the exe (winrt bundled), /sysinfo reads this PC
    def media():
        import winrt.windows.media.control  # noqa: F401  (fails if PyInstaller left winrt out)
        import asyncio
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
        from bchat import nowplaying
        async def ask():
            mgr = await M.request_async()
            return mgr is not None and isinstance(list(mgr.get_sessions()), list)
        # the manager itself answers (an empty list alone also passed before, even with winrt broken in a thread)
        return asyncio.run(ask()) and isinstance(nowplaying._windows_media(), list) and hasattr(nowplaying, "Announcer")
    note("/np: Windows media controls answer inside the exe", media)
    def sysline():
        from bchat import full_version, sysinfo
        i = sysinfo.collect(full_version())
        return i["os"].startswith("Windows") and i["cpu"] != "?" and "free of" in i["ram"] and i["bchat"] == full_version()
    note("/sysinfo reads this PC inside the exe", sysline)
    def icons():
        from bchat import lucide
        from bchat.widgets import icon
        img = icon("quit").pixmap(24, 24).toImage()
        drawn = sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 200)
        return drawn > 20 and all(not icon(n).isNull() for n in lucide.NAMES)
    note("Lucide icons draw in the exe", icons)
    def topic_hides():
        bar = win.topic
        bar.set_allowed(False, "x")
        hidden = not any(b.isVisibleTo(bar) for b in [*bar.buttons.values(), bar.set_btn])
        bar.set_allowed(True)
        return hidden and all(b.isVisibleTo(bar) for b in [*bar.buttons.values(), bar.set_btn])
    note("topic buttons hide when not allowed", topic_hides)
    def cards():
        n = win.notifier
        n.busy = lambda: False
        n.notify("priv", None, "probe", "Probe", "private", "hello from the exe")
        ok = len(n.cards) == 1 and n.cards[0].isVisible()
        n.clear()
        return ok
    note("notification card shows in the exe", cards)
    def vault_real():
        from pathlib import Path as P
        from bchat import vault
        f = P(r"C:\BChatVaultSelfTest-exe-not-a-folder")
        ok = vault.put(f, "probe-secret") and vault.get(f) == "probe-secret"
        vault.clear(f)
        return ok and vault.get(f) is None
    note("real Credential Manager works in the exe (and is cleaned up)", vault_real)
    def vault_temp_rule():
        import os as _os, tempfile as _tf
        from pathlib import Path as P
        from bchat import vault
        was = _os.environ.pop("BCHAT_VAULT", None)
        try:
            real = not vault._memory_mode(P(_tf.gettempdir()) / "bchat-welcome")    # TEST22 bug: was True
        finally:
            if was is not None:
                _os.environ["BCHAT_VAULT"] = was
        return real and vault._memory_mode(P(_tf.gettempdir()) / "x") == (was == "file")
    note("installed exe never keeps passwords in a temp-folder file", vault_temp_rule)
    def passwords_not_in_file():
        from bchat import config as cfgmod
        net = win.cfg.networks[0]
        net.password = "probe-pass-7731"
        cfgmod.save(win.cfg, win.cfg_dir)
        text = (win.cfg_dir / "config.json").read_text(encoding="utf-8")
        back = cfgmod.load(win.cfg_dir).networks[0].password
        net.password = ""
        cfgmod.save(win.cfg, win.cfg_dir)
        return "probe-pass-7731" not in text and back == "probe-pass-7731"
    note("passwords kept out of config.json in the exe", passwords_not_in_file)
    def safety_windows():
        from bchat.safety import CertDialog, link_risk
        d = CertDialog(win, {"host": "h", "network": "n", "fingerprint": "ab" * 32, "self_signed": True})
        ok = d.no_btn.isDefault()
        d.close()
        return ok and link_risk("https://x.example/a.exe") and not link_risk("https://skinhead.com.my")
    note("certificate window and link check in the exe", safety_windows)
    def cert_login_parts():
        from bchat import certs
        from bchat.chanserv import commands as cs
        p = certs.make(win.cfg_dir / "certs" / "probe.pem", "probe")
        info = certs.describe(str(p))
        return info is not None and len(info[2].split(":")) == 32 and cs("anope", "#c", "W", "voice", "none") == ["VOP #c ADD W"]
    note("0.4.0 certificate made + read and ChanServ commands in the exe", cert_login_parts)
    missing = []
    for mod in ("json", "re", "os", "time", "random", "datetime", "threading", "socket", "subprocess", "urllib.request", "urllib.parse", "http.client",
                "sqlite3", "csv", "hashlib", "html", "xml.etree.ElementTree", "collections", "itertools", "math", "string", "textwrap", "shlex", "glob", "tempfile", "queue"):
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)
    results["plugin imports all there"] = not missing
    if missing:
        results["plugin imports missing"] = str(missing)
    xchat.command("say plugin says hi")
    results["get_info works"] = xchat.get_info("network") == "SkinIRC"
    with open(REPORT, "w") as f:
        json.dump(results, f)
    return False
xchat.hook_timer(3000, run)
''' % str(report)
# A real release signature: the published 0.5.0 entry (public). Before 11-11-2026 this check signed a fresh
# entry with the private release key; the published entry proves the same thing without touching that key.
_pub = json.loads((Path(__file__).with_name("data") / "signed-release-entry.json").read_text())
_signed = {k: _pub[k] for k in ("version", "sha256", "sig")}
PROBE = PROBE.replace("%SIGNED%", repr(_signed)).replace("%EXPECT%", repr(ARGS.expect))   # the % formatting above turned %%SIGNED%% into %SIGNED%
(cfgdir / "addons" / "probe.py").write_text(PROBE)

payload = bytes(range(256)) * 2000
ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1)
acks = {"n": 0}


def serve():
    c, _ = ls.accept()
    c.sendall(payload)
    c.settimeout(5)
    try:
        while acks["n"] < len(payload):
            d = c.recv(4096)
            if not d:
                break
            acks["n"] = int.from_bytes(d[-4:], "big")
    except OSError:
        pass
    c.close()


threading.Thread(target=serve, daemon=True).start()
p = subprocess.Popen([EXE, "--config-dir", str(cfgdir)], env=dict(os.environ, BCHAT_VAULT="file"))   # throwaway settings: stand-in vault


def wait(cond, sec=30):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


out = {}
try:
    out["joined the fake server"] = wait(lambda: "JOIN #skinhead" in srv.received)
    time.sleep(1)
    srv.send(f":Belon!b@h PRIVMSG Badaboom :\x01DCC SEND song.mp3 2130706433 {ls.getsockname()[1]} {len(payload)}\x01")
    done = inbox / "song.mp3"
    out["DCC file arrives, exact bytes"] = wait(lambda: done.exists() and done.read_bytes() == payload and acks["n"] == len(payload))
    srv.send(":Belon!b@h PRIVMSG Badaboom :\x01PING 12345\x01")
    out["CTCP reply goes through the list"] = wait(lambda: any("PING 12345" in x for x in srv.received))
    out["probe plugin finished"] = wait(lambda: report.exists(), 40)
    if report.exists():
        for k, v in json.loads(report.read_text()).items():
            out[k] = v
    out["plugin's command reached the server"] = wait(lambda: any("plugin says hi" in x for x in srv.received), 5)
    out["still running at the end"] = p.poll() is None
finally:
    p.kill()
    srv.stop()
finish("frozen_features", ARGS, out)
