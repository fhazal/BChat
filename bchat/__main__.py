"""Start BChat. --config-dir and --no-autoconnect exist so tests never touch real settings or servers."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

from . import __version__, config, xchat_import
from .mainwindow import MainWindow


def link_pipe(config_dir: Path) -> str:
    """The name a running BChat listens on for irc:// links (one per settings folder)."""
    import hashlib
    return "BChat-links-" + hashlib.sha1(str(Path(config_dir).resolve()).lower().encode()).hexdigest()[:12]


def hand_to_running(config_dir: Path, link: str) -> bool:
    """A browser started a second BChat for a link: give it to the one already open and stop here."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(link_pipe(config_dir))
    if not sock.waitForConnected(500):
        return False
    sock.write(link.encode("utf-8")[:2000] + b"\n")
    sock.waitForBytesWritten(1000)
    sock.waitForDisconnected(3000)        # the running BChat hangs up once it has read the link
    return True


def listen_for_links(win, config_dir: Path):
    from PySide6.QtNetwork import QLocalServer
    srv = QLocalServer(win)
    name = link_pipe(config_dir)
    srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)     # only this Windows user can send links
    if not srv.listen(name):
        QLocalServer.removeServer(name)
        srv.listen(name)

    def arrived():
        while srv.hasPendingConnections():
            c = srv.nextPendingConnection()

            def read(c=c):
                if c.canReadLine():
                    text = bytes(c.readLine()).decode("utf-8", "replace").strip()
                    c.disconnectFromServer()
                    if text.lower().startswith(("irc://", "ircs://")):
                        win.open_irc_link(text)
            c.readyRead.connect(read)
            c.disconnected.connect(c.deleteLater)
            read()
    srv.newConnection.connect(arrived)
    return srv


def portable_dir(flag: bool) -> Path | None:
    """0.6.0 portable BChat: -portable, or a file named portable.txt next to BChat.exe ->
    settings, logs and downloads in BChat-data next to it."""
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    if flag or (exe_dir / "portable.txt").exists():
        return exe_dir / "BChat-data"
    return None


def start_network(win, server: str, join: str, nick: str):
    """0.6.0 start options: -s server (a saved network's name, or host/port like the network list), -j, -n."""
    from .config import NetworkConfig
    from .protocol import lower
    from .xchat_import import parse_server
    saved = next((n for n in win.cfg.networks if lower(n.name) == lower(server)), None)
    if saved is not None:
        s = win.session_for(saved)
    else:
        sv = parse_server(server.replace(":", "/", 1) if "/" not in server and server.count(":") == 1 else server, False)
        s = win.session_for(NetworkConfig(sv.host, [sv], cycle=False))
        s.typed_by_hand = True
    if nick:
        s.net.nick, s.net.use_global = nick, False
    chans = []
    if join:
        chans = [c.strip() for c in join.replace(" ", ",").split(",") if c.strip()]
        chans = [c if c[0] in "#&+!" else "#" + c for c in chans]
        s.join_once += [(c, "") for c in chans if (c, "") not in s.join_once]
    win.select_buffer(s.server_buffer)
    if s.state == "disconnected":
        s.connect_to_network()
    elif chans and s.state == "connected":
        s.send("JOIN", ",".join(chans))
    return s


def check_lock(win, folder: Path, cfg) -> bool:
    """0.6.0 Lock: the password before anything shows. False = the user quit. Notes a removed lock."""
    from . import config as config_mod, lock
    d = lock.read(folder)
    if d is None:
        if cfg.lock_was_on:                          # lock.json was there last time and is gone now
            cfg.lock_was_on, cfg.lock_removed_at = False, time.time()
            config_mod.save(cfg, folder)
        cfg.lock_limits = None
        return True
    key = lock.ask_password(win, folder, d)
    if key is None:
        return False
    config_mod.LOCK_KEY = key
    if getattr(cfg, "secret_box", ""):
        config_mod.open_locked(cfg, key)
    cfg.lock_limits = lock.limits_only(d)
    if not cfg.lock_was_on:
        cfg.lock_was_on = True
        config_mod.save(cfg, folder)
    return True


class AlwaysUnderline(QProxyStyle):
    """Windows hides menu underlines until Alt is pressed; XChat always shows them."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_UnderlineShortcut:
            return 1
        return super().styleHint(hint, option, widget, returnData)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bchat")
    ap.add_argument("--config-dir", type=Path, default=config.default_dir())
    ap.add_argument("--no-autoconnect", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-s", "--server", default="", help="connect: a saved network's name, or host/port (host/+port for SSL)")
    ap.add_argument("-j", "--join", default="", help="channels to join on that server: #chat,#BChat")
    ap.add_argument("-n", "--nick", default="", help="the nick for that server")
    ap.add_argument("-portable", "--portable", action="store_true",
                    help="keep settings, logs and downloads in BChat-data next to BChat.exe")
    ap.add_argument("link", nargs="?", default="", help="an irc:// or ircs:// link to open")
    args = ap.parse_args(argv)
    port_dir = portable_dir(args.portable)
    if port_dir is not None and "--config-dir" not in " ".join(argv if argv is not None else sys.argv):
        args.config_dir = port_dir
        config.PORTABLE = True
    link = args.link if args.link.lower().startswith(("irc://", "ircs://")) else ""

    app = QApplication(sys.argv[:1])
    if link and hand_to_running(args.config_dir, link):
        return 0
    app.setStyle(AlwaysUnderline("Fusion"))
    app.setApplicationName("BChat")
    app.setOrganizationName("BajuBesi Labs")
    cfg = config.load(args.config_dir)
    if not cfg.imported and not cfg.networks:
        sources = xchat_import.default_sources()
        if sources:
            xchat_import.import_into(cfg, sources)
            config.save(cfg, args.config_dir)
    # problem reports (0.3.0): crash file, errors inside clicks, freezes, last clicked buttons
    from . import reports
    report_dir = args.config_dir / "reports"
    crash = reports.CrashFile(report_dir)
    steps = reports.StepWatcher(app)
    app.installEventFilter(steps)
    win = MainWindow(cfg, args.config_dir)
    if not check_lock(win, args.config_dir, cfg):
        crash.close()
        return 0
    catcher = reports.ErrorCatcher(win)
    catcher.caught.connect(lambda text, sig: win.offer_report("BChat hit a problem just now.", "Something else", text, sig))
    watchdog = reports.Watchdog(report_dir, win)
    watchdog.recovered.connect(lambda secs, stack: win.offer_report(
        f"BChat stopped responding for {round(secs)} seconds.", "Slow", stack, reports.fingerprint(stack), secs))
    # the window can be hidden in the tray while a tool window closes, and that must not end the program
    app.setQuitOnLastWindowClosed(False)
    win.quit_requested.connect(app.quit)
    win.link_server = listen_for_links(win, args.config_dir)
    if cfg.start_in_tray and win.tray is not None:
        win._was_maximized = cfg.win_maximized          # the tray click brings it back as it was
    elif cfg.start_minimized:
        win.showMinimized()
    elif cfg.win_maximized:
        win.showMaximized()
    else:
        win.show()

    def start():
        if getattr(cfg, "vault_missing", False):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(win, "BChat: saved passwords", "BChat couldn't read your saved network passwords from "
                                "Windows Credential Manager. Please enter them again in the Network List.")
        win.updater.start()
        win.check_autostart()
        if not args.no_autoconnect:
            win.autoconnect()
        from .welcome import first_start_action, run_welcome
        action = first_start_action(cfg, bool(win.sessions))
        if action == "welcome":
            run_welcome(win)
        elif action == "netlist" and not link:
            win.open_network_list()
        if link:
            win.open_irc_link(link)
        if args.server:
            start_network(win, args.server, args.join, args.nick)
        stuck = reports.leftover_freeze(report_dir)
        if crash.previous:
            win.offer_report("BChat closed unexpectedly last time.", "Crashed", crash.previous, reports.fingerprint(crash.previous))
        elif stuck:
            win.offer_report("BChat stopped responding last time and was closed.", "Slow", stuck[1], reports.fingerprint(stuck[1]), stuck[0])
        reports.Sender(win).send_pending()

    QTimer.singleShot(0, start)
    code = app.exec()
    watchdog.stop()
    catcher.close()
    crash.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
