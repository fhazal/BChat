"""Start BChat. --config-dir and --no-autoconnect exist so tests never touch real settings or servers."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

from . import __version__, config, xchat_import
from .mainwindow import MainWindow


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
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
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
        elif action == "netlist":
            win.open_network_list()

    QTimer.singleShot(0, start)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
