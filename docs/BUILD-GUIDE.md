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
