"""Linux desktop entries for the BChat AppImage (an AppImage has no installer, so BChat writes its own):

- the app menu:  $XDG_DATA_HOME/applications/bchat.desktop (+ the icon), with the irc:// and ircs:// link types
  when 'Open irc:// and ircs:// links' is ticked, and BChat set as their default in $XDG_CONFIG_HOME/mimeapps.list
- start when I log in:  $XDG_CONFIG_HOME/autostart/bchat.desktop

Like the Windows Run value, the ticks in Preferences are the truth: every start puts the files back in line (the
AppImage may have moved). Only BChat's own files and mimeapps.list lines are ever touched. Never raises."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SUPPORTED = sys.platform.startswith("linux")
FILE = "bchat.desktop"
SCHEMES = ("x-scheme-handler/irc", "x-scheme-handler/ircs")
ICON = Path(__file__).with_name("assets") / "bchat.png"
_RESERVED = set(' \t\n"\'\\><~|&;$*?#()`')


def installed_exe() -> str | None:
    """The BChat AppImage being run (its runtime sets $APPIMAGE), or None from source: nothing stable to point at."""
    path = os.environ.get("APPIMAGE", "")
    return path if path and os.path.isfile(path) else None


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def menu_file() -> Path:
    return data_home() / "applications" / FILE


def autostart_file() -> Path:
    return config_home() / "autostart" / FILE


def icon_file() -> Path:
    return data_home() / "icons" / "hicolor" / "256x256" / "apps" / "bchat.png"


def exec_line(exe: str, url: bool) -> str:
    """The Exec= value, quoted by the Desktop Entry rules (quote, escape " ` $ \\ inside, then \\ again for the
    file's own string escapes; a literal % is %%)."""
    arg = exe
    if any(ch in _RESERVED for ch in arg):
        arg = '"' + "".join("\\" + ch if ch in '"`$\\' else ch for ch in arg) + '"'
    arg = arg.replace("\\", "\\\\").replace("%", "%%")
    return arg + (" %u" if url else "")


def entry(exe: str, links: bool, autostart: bool = False) -> str:
    lines = ["[Desktop Entry]", "Type=Application", "Name=BChat", "GenericName=IRC Chat",
             "Comment=Chat on IRC", f"Exec={exec_line(exe, links and not autostart)}", "Icon=bchat",
             "Terminal=false", "Categories=Network;Chat;IRCClient;", "StartupWMClass=BChat"]
    if links and not autostart:
        lines.append("MimeType=" + "".join(s + ";" for s in SCHEMES))
    if autostart:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _exec_of(text: str | None) -> str | None:
    for line in (text or "").splitlines():
        if line.startswith("Exec="):
            return line[5:]
    return None


def _ours(text: str | None, exe: str) -> bool:
    """The file is this BChat's: its Exec points at this very AppImage (a test copy must not remove the real one's)."""
    have = _exec_of(text)
    return have is not None and have.split(" %u")[0] == exec_line(exe, False)


def _sync_file(path: Path, on: bool, want: str, exe: str) -> str:
    have = _read(path)
    if on:
        if have == want:
            return "ok"
        _write(path, want)
        return "added" if have is None else "fixed"
    if have is None or not _ours(have, exe):
        return "ok"
    path.unlink()
    return "removed"


def set_default_links(on: bool, mimeapps: Path | None = None) -> None:
    """Makes BChat the default for irc:// and ircs:// in mimeapps.list, or takes back only BChat's own lines.
    A line-by-line edit: every other line, comment and section stays exactly as it was."""
    mimeapps = mimeapps or config_home() / "mimeapps.list"
    lines = (_read(mimeapps) or "").splitlines()
    out, section, seen_default = [], "", False
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if section == "[Default Applications]" and on:
                blanks = 0
                while out and not out[-1].strip():
                    out.pop(); blanks += 1
                out.extend(f"{k}={FILE}" for k in SCHEMES)
                out.extend([""] * blanks)
            section = s
            seen_default = seen_default or s == "[Default Applications]"
        elif section == "[Default Applications]" and "=" in s and s.split("=", 1)[0].strip() in SCHEMES:
            value = s.split("=", 1)[1].strip()
            if on or value.split(";")[0] == FILE:
                continue          # replaced below (on), or ours and taken back (off); someone else's stays when off
        out.append(line)
    if on and section == "[Default Applications]":
        out.extend(f"{k}={FILE}" for k in SCHEMES)
    elif on and not seen_default:
        if out and out[-1].strip():
            out.append("")
        out.append("[Default Applications]")
        out.extend(f"{k}={FILE}" for k in SCHEMES)
    text = "\n".join(out) + "\n" if out else ""
    if text != (_read(mimeapps) or ""):
        if text:
            _write(mimeapps, text)
        elif mimeapps.exists():
            mimeapps.unlink()


def _refresh_menu() -> None:
    """Tells the desktop the menu changed (most watch the folder anyway; this tool may not be installed)."""
    tool = shutil.which("update-desktop-database")
    if tool:
        try:
            subprocess.run([tool, str(menu_file().parent)], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def sync_menu(menu: bool, links: bool, exe: str | None) -> str:
    """App-menu entry (+ icon, + link types) matching the ticks. 'added', 'fixed', 'removed', 'ok', 'skipped'
    (not Linux, or from source) or 'failed'."""
    if exe is None or not SUPPORTED:
        return "skipped"
    try:
        links = menu and links
        before = _read(menu_file())
        result = _sync_file(menu_file(), menu, entry(exe, links), exe)
        if menu:
            if not icon_file().exists() or icon_file().read_bytes() != ICON.read_bytes():
                icon_file().parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ICON, icon_file())
        elif result == "removed" and icon_file().exists():
            icon_file().unlink()
        if menu or result == "removed" or _ours(before, exe):
            set_default_links(links)
        if result != "ok":
            _refresh_menu()
        return result
    except OSError:
        return "failed"


def sync_autostart(on: bool, exe: str | None) -> str:
    if exe is None or not SUPPORTED:
        return "skipped"
    try:
        return _sync_file(autostart_file(), on, entry(exe, False, autostart=True), exe)
    except OSError:
        return "failed"
