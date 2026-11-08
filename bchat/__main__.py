"""Start BChat. --config-dir and --no-autoconnect exist so tests never touch real settings or servers."""
from __future__ import annotations

import argparse
import sys
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
    ap.add_argument("link", nargs="?", default="", help="an irc:// or ircs:// link to open")
    args = ap.parse_args(argv)
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
    win = MainWindow(cfg, args.config_dir)
    # the window can be hidden in the tray while a tool window closes, and that must not end the program
    app.setQuitOnLastWindowClosed(False)
    win.quit_requested.connect(app.quit)
    win.link_server = listen_for_links(win, args.config_dir)
    if cfg.start_minimized:
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

    QTimer.singleShot(0, start)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
