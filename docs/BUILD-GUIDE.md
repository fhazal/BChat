# BChat build guide

How to run BChat from source, make test and release builds, package them, check them, and
roll back. Tests are in [TESTING.md](TESTING.md); the release steps in
[RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md).

## Requirements

- Windows 10 or 11 (64-bit).
- Python 3.11 or newer (the build PC uses 3.12.10).
- `python -m pip install -e .` (PySide6, pyspellchecker, cryptography), plus `pytest`,
  `pyinstaller` and, for `/np`, the `winrt-*` packages.
- Inno Setup 6 (`ISCC.exe`, installed per user under `%LOCALAPPDATA%\Programs\Inno Setup 6`).

## Development build (from source)

```powershell
python -m bchat                                     # normal start, real settings in %APPDATA%\BChat
python -m bchat --config-dir C:\Temp\bchat-dev      # throwaway settings
python -m bchat --config-dir C:\Temp\bchat-dev --no-autoconnect
```

Use a throwaway `--config-dir` for anything experimental. Set `BCHAT_VAULT=file` (or `memory`)
so test passwords never reach the real Credential Manager.

## Test build (`0.x.y-TESTn`)

Made only when the owner asks for it ("Build TESTn").

1. Set the version in two places:
   - `packaging/version_info.txt`: `filevers`/`prodvers` `(0, x, y, n)` and the
     `FileVersion`/`ProductVersion` strings `0.x.y-TESTn`.
   - `V=0.x.y-TESTn` at the top of the build script.
2. Run the build script (Git Bash):

   ```bash
   bash build/build-test.sh
   ```

   It writes `bchat/assets/version.txt`, runs PyInstaller with `packaging/BChat.spec`
   (work dir `build/pyi`, output `dist/BChat/`), removes `version.txt` again, then runs
   Inno Setup on `packaging/bchat.iss` with `/DMyVersion=$V`. Logs:
   `build/pyi-$V.log`, `build/iscc-$V.log`. A full build takes about one minute.
3. Validate (see "Build verification" below), then VirusTotal, then hand it over.

## Production (release) build

Same as a test build with the plain version (`0.x.y`, `version_info` `(0, x, y, 0)`), built from
the exact commit that will be tagged. The release manifest is signed after the build (see
RELEASE-CHECKLIST.md).

## Packaging

| Piece | File | Notes |
| --- | --- | --- |
| Entry point | `packaging/run_bchat.py` | what PyInstaller freezes |
| Freeze recipe | `packaging/BChat.spec` | one-folder build, unused Qt parts left out (below), no UPX, windowed, icon + version resource; hidden imports for the plugin standard library, `PySide6.QtSvg` and the winrt modules; spell-check word lists collected as data |
| Version resource | `packaging/version_info.txt` | shown in Explorer and used by the updater |
| Installer | `packaging/bchat.iss` | per-user install (`PrivilegesRequired=lowest`), lzma2 solid compression, Start menu + optional desktop shortcut, "Start BChat" at the end |
| Installer art | `packaging/wizard-*.bmp`, `make_installer_art.py` | |

**Not in git:** `build/` is in `.gitignore` (so `build/build-test.sh` is untracked), and
`dev-tools/` is excluded locally. The freeze recipe `packaging/BChat.spec` is tracked (an
exception in `.gitignore`); it uses paths relative to itself.

### Qt parts left out (since 0.6.0-TEST3)

A filter in the spec leaves out Qt parts that BChat never loads: Qt Quick/QML (+ Qt6OpenGL,
only used by Quick), Qt PDF (image plugin), Virtual Keyboard, the software OpenGL fallback
(`opengl32sw.dll`) and Qt's 115 translation files. Validated 11 Nov 2026: installed size 140.5 →
94.4 MB, installer 45.6 → 34.2 MB, no change in start time, memory, CPU or test results. The
build log prints `SLIM: dropped <n> entries`.

## Build output locations

| What | Where |
| --- | --- |
| Frozen app | `dist/BChat/` (`BChat.exe` + `_internal/`) |
| Installer | `dist/BChat-<version>-setup.exe` |
| Release manifest | `dist/bchat-update.json` |
| Release notes | `dist/release-notes-<version>.md` |
| Build logs | `build/pyi-<version>.log`, `build/iscc-<version>.log` |
| Experimental builds | their own folder under `build/` (e.g. `build/slim/`), never `dist/` |
| Test copy for the owner | the Desktop (the older TEST installer goes to the Recycle Bin) |

Installed BChat lives in `%LOCALAPPDATA%\Programs\BChat`. Builds and tests never install over
it or run its installer.

## Build verification

After every test or release build, before anyone gets it:

```powershell
python tools/qa.py all --exe dist/BChat/BChat.exe   # runs the steps below and writes qa-reports/<time>/summary.md
```

1. `sha256sum` of the installer and `dist/BChat/BChat.exe` written down.
2. Packaged-app checks in `tools/qa/` against `dist/BChat/BChat.exe`: `bundle_check.py` (23),
   `frozen_check.py` (19), `frozen_features.py` (60), `frozen_reports.py` (19),
   `frozen_extra.py` (59). See TESTING.md.
3. The version shown by the exe (About, `full_version()`) is the one built.
4. VirusTotal on the installer and on `BChat.exe`.
5. For packaging changes: compare the file list and loaded DLLs with the previous build.

## Recovery and rollback

- **Keep known-good builds.** Old installers stay in `dist/` with their SHA-256 recorded in
  QA-BASELINE.md or the release notes; experiments live in their own folders.
- **Bad test build:** delete it from the Desktop, rebuild from the last good commit. Nothing
  else changes, because test builds are not installed by the build process.
- **Bad release:** published releases are not deleted. Publish a fixed version (`0.x.y+1`);
  the updater only offers newer versions. If a release must be pulled, mark it as a
  pre-release on GitHub so the updater stops offering it (`updater.from_github` skips drafts
  always, and pre-releases unless the user runs a TEST version or chose "test versions" in
  Preferences).
- **Packaging change gone wrong:** rebuild with the previous `packaging/BChat.spec`
  from git.
- **Settings:** BChat ignores unknown keys, so older versions can read newer settings files.


## Linux AppImage (0.9.0+)

The Windows build above is unchanged; the Linux build is separate and never touches `packaging/BChat.spec`,
`build/build-test.sh`, `dist/BChat` or the installer.

**Where:** an Ubuntu 22.04 system (the oldest glibc BChat supports, so the AppImage runs on Ubuntu 22.04+, Fedora
and other current distros). On the Fedora PC this is a podman container; WSL Ubuntu 22.04 works the same way.

**Needs:** Python 3.12 (deadsnakes PPA on 22.04) in a venv with `PySide6==6.12.0`, pyspellchecker, cryptography,
jeepney, secretstorage, pytest and `pyinstaller==6.22.3`; `patchelf file binutils desktop-file-utils xdg-utils`;
Qt's runtime libraries (libgl1, libegl1, libxkbcommon-x11-0, the libxcb-* set, libwayland-*, libfontconfig1,
libdbus-1-3, libpulse0, libspeechd2); and `appimagetool` (AppImage project, GitHub "continuous" release).

**Build:** from a copy of the source (git-tracked files plus `packaging/BChat-linux.spec`, which `*.spec` in
`.gitignore` hides, so add it with `git add -f`):

    BCHAT_PY=/opt/bchat-venv/bin/python bash packaging/build-linux.sh <version> [out-dir]

It writes `bchat/assets/version.txt` for the build and removes it after, freezes with
`packaging/BChat-linux.spec` (drops Qt parts BChat doesn't use and the libraries every desktop already has), builds
the AppDir (AppRun, `bchat.desktop` with irc/ircs links, icon) and runs appimagetool. Output:
`<out-dir>/BChat-<version>-x86_64.AppImage` plus its SHA-256. Work files go to `build/linux/` (git-ignored).

**Check:** `python tools/qa.py packaged --exe <AppImage> --expect <version>` on Linux runs `tools/qa/frozen_linux.py`
in its own D-Bus session: bundle, X11 (Xvfb), Wayland (weston headless), keyring (gnome-keyring), portable mode,
a DCC file, speech and sound. Run it as a normal user, not root (gnome-keyring refuses root in a container). On
Linux `build-check` and `perf` are SKIP: they are Windows tools and run in the Windows QA. Before a release, the
QA runs on Ubuntu 22.04, Ubuntu 24.04 and Fedora, and once on a real desktop.

**Linux-only startup guards** (`bchat/linuxdesk.py`, no effect on Windows): programs BChat starts get the
desktop's own `LD_LIBRARY_PATH`, not the bundle's (else Fedora's speech-dispatcher and xdg-open crash on the older
bundled glib); and without PipeWire's `client.conf` BChat tells Qt to use its PulseAudio sound backend (Qt's
PipeWire backend crashes there).

**Updates (Linux):** the AppImage updates itself (`bchat/updater.py`, Linux only): it reads its own
`bchat-update-linux.json` from the GitHub release (Windows keeps `bchat-update.json`), and that signature also
covers the word `linux`, so neither system ever accepts the other's file. Install = the AppImage file is replaced
in place under the same name (menu entries, autostart and shortcuts keep working), then BChat starts again once the
old one has quit. Check it with a real TEST-to-TEST update (local server, throwaway key, nothing online):

    dbus-run-session -- python3 tools/qa/update_linux.py --exe <TEST1.AppImage> --new <TEST2.AppImage> --out <dir>

(add `--desktop` to run it on a real desktop, where the AppImage is FUSE-mounted as users get it).

**Release (Linux), next to the Windows files:**

1. Upload the AppImage under the version-free name **`BChat-x86_64.AppImage`** (the build's versioned file,
   renamed): an update keeps the file name, so the name must not carry a version.
2. Sign it: `python dev-tools/make_manifest.py --linux BChat-x86_64.AppImage <version> <url of that asset> [--test]`
   (same release key; writes `dist/bchat-update-linux.json` and `dist/latest-linux.json`, never the Windows files).
3. Upload `bchat-update-linux.json` to the same release.

**Every release:** VirusTotal on the AppImage too; never distribute an AppImage built on a newer distro (Fedora
builds only run on that Fedora version or newer).
