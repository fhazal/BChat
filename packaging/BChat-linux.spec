# -*- mode: python ; coding: utf-8 -*-
# BChat freeze recipe for Linux (PyInstaller, one-folder). It becomes the inside of the AppImage:
# bash packaging/build-linux.sh <version>, run in Ubuntu 22.04 (the oldest glibc BChat supports). The Windows recipe
# is BChat.spec; the two share the same idea and are kept apart so a Linux change can never touch the Windows build.
import os
from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "bchat", "assets"), "bchat/assets")]
datas += collect_data_files('spellchecker')

a = Analysis(
    [os.path.join(ROOT, "packaging", "run_bchat.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=['json', 'random', 'datetime', 'threading', 'socket', 'subprocess', 'urllib.request', 'urllib.parse',
                   'http.client', 'sqlite3', 'csv', 'hashlib', 'html', 'xml.etree.ElementTree', 'collections',
                   'itertools', 'math', 'string', 'textwrap', 'shlex', 'glob', 'tempfile', 'queue',
                   'cryptography.hazmat.primitives.asymmetric.ed25519', 'PySide6.QtSvg', 'PySide6.QtMultimedia',
                   'PySide6.QtTextToSpeech',
                   # Linux: passwords in the desktop's keyring (Secret Service) and /np over MPRIS, both through D-Bus
                   'secretstorage', 'jeepney', 'jeepney.io.blocking'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['winrt', 'winsound', 'winreg'],
    noarchive=False,
    optimize=0,
)

# Leave out the Qt parts BChat never loads, as on Windows: Qt Quick/QML, Qt PDF, the Virtual Keyboard and Qt's
# translation files.
_DROP_PREFIXES = ("libqt6quick", "libqt6qml", "libqt6pdf", "libqt6virtualkeyboard", "libqtvirtualkeyboard",
                  "libqpdf")
# ...except the five Qt Quick/QML libraries Linux's FFmpeg sound plugin is linked against: without them .mp3 and
# .ogg sounds can't play (found by tools/qa/frozen_linux.py). The Windows plugin doesn't need them.
_FFMPEG_NEEDS = ("libqt6quick.so.6", "libqt6qml.so.6", "libqt6qmlmeta.so.6", "libqt6qmlmodels.so.6",
                 "libqt6qmlworkerscript.so.6")


# Libraries every Linux desktop has and that must match the rest of the system: a bundled copy older than the
# host's breaks the host's graphics drivers (C++ runtime), fonts or the session bus. Same idea as AppImage's
# excludelist. GTK comes in only through Qt's GTK theme plugin, which BChat doesn't use (it draws its own theme).
_HOST_LIBS = ("libstdc++.so", "libgcc_s.so", "libfontconfig.so", "libfreetype.so", "libharfbuzz.so", "libdbus-1.so",
              "libx11.so", "libx11-xcb.so", "libxau.so", "libxdmcp.so", "libxext.so", "libxrender.so", "libxfixes.so",
              "libxi.so", "libxrandr.so", "libxcursor.so", "libxinerama.so", "libxcomposite.so", "libxdamage.so",
              "libgtk-3.so", "libgdk-3.so", "libgdk_pixbuf-2.0.so", "libatk-1.0.so", "libatk-bridge-2.0.so",
              "libatspi.so", "libcairo.so", "libcairo-gobject.so", "libpango-1.0.so", "libpangocairo-1.0.so",
              "libpangoft2-1.0.so", "libepoxy.so", "libpixman-1.so", "libthai.so", "libdatrie.so", "libfribidi.so",
              "libgraphite2.so", "libsystemd.so", "libapparmor.so", "libselinux.so", "libmount.so", "libblkid.so",
              "libgcrypt.so", "libgpg-error.so", "libcom_err.so", "libkrb5.so", "libk5crypto.so", "libkrb5support.so",
              "libgssapi_krb5.so", "libkeyutils.so", "libpulse.so", "libpulsecommon-")
# Qt platforms and input plugins for embedded screens (framebuffer, EGLFS, VNC, evdev): a desktop app never uses them.
# BChat keeps X11 (xcb), Wayland and offscreen (the tests).
_DROP_PLUGINS = ("/platforms/libqeglfs", "/platforms/libqlinuxfb", "/platforms/libqminimal", "/platforms/libqvnc",
                 "/platforms/libqvkkhrdisplay", "/egldeviceintegrations/", "/generic/", "/platformthemes/libqgtk3")


def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    base = os.path.basename(dest)
    if base in _FFMPEG_NEEDS:
        return True
    if base.startswith(_DROP_PREFIXES) or base.startswith(_HOST_LIBS) or base.startswith("libqt6eglfs"):
        return False
    if any(p in dest for p in _DROP_PLUGINS):
        return False
    if "/translations/" in dest and dest.endswith(".qm"):
        return False
    return True


_before = len(a.binaries) + len(a.datas)
a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]
print("SLIM: dropped", _before - len(a.binaries) - len(a.datas), "entries")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BChat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BChat',
)
