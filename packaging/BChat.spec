# -*- mode: python ; coding: utf-8 -*-
# BChat freeze recipe (PyInstaller, one-folder, windowed). Build: bash build/build-test.sh (see docs/BUILD-GUIDE.md).
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "bchat", "assets"), "bchat/assets")]
datas += collect_data_files('spellchecker')
# /np: Windows media controls through Microsoft's winrt packages (a namespace package PyInstaller can't see alone)
winrt_mods = collect_submodules('winrt') + ['winrt.windows.media.control', 'winrt.windows.media', 'winrt.windows.foundation',
              'winrt.windows.foundation.collections', 'winrt.windows.storage.streams']


a = Analysis(
    [os.path.join(ROOT, "packaging", "run_bchat.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=['json', 'random', 'datetime', 'threading', 'socket', 'subprocess', 'urllib.request', 'urllib.parse', 'http.client', 'sqlite3', 'csv', 'hashlib', 'html', 'xml.etree.ElementTree', 'collections', 'itertools', 'math', 'string', 'textwrap', 'shlex', 'glob', 'tempfile', 'queue', 'cryptography.hazmat.primitives.asymmetric.ed25519', 'PySide6.QtSvg'] + winrt_mods,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Leave out Qt parts BChat never loads (validated 11 Nov 2026, docs/BUILD-GUIDE.md): Qt Quick/QML (+ Qt6OpenGL,
# only used by Quick through the virtual keyboard), Qt PDF (image plugin), Virtual Keyboard, the software OpenGL
# fallback and Qt's translation files. Installer 45.6 -> 34.2 MB, installed 140.5 -> 94.4 MB.
_DROP_FILES = {"qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll", "qt6qmlmeta.dll", "qt6qmlworkerscript.dll",
               "qt6opengl.dll", "qt6virtualkeyboard.dll", "qtvirtualkeyboardplugin.dll", "qt6pdf.dll", "qpdf.dll",
               "opengl32sw.dll"}


def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    if os.path.basename(dest) in _DROP_FILES:
        return False
    if dest.startswith("pyside6/translations/") and dest.endswith(".qm"):
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
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(ROOT, "bchat", "assets", "bchat.ico")],
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
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
