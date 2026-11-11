# BChat development guide

How BChat is put together and how work on it is done. For building see
[BUILD-GUIDE.md](BUILD-GUIDE.md), for tests [TESTING.md](TESTING.md), for releases
[RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md). The user guide is [GUIDE.md](GUIDE.md).

## What BChat is

A Windows IRC client in the classic XChat 2 layout, with mIRC-style tools added where they
help. The guiding idea: modernise the experience, not the soul of IRC. Calm, consistent UI;
anything that can't be used right now is hidden rather than greyed out.

## Technology stack

| Part | What | Version on the build PC (11 Nov 2026) |
| --- | --- | --- |
| Language | Python | 3.12.10 (`requires-python >= 3.11`) |
| UI and networking | PySide6 / Qt 6 (Widgets, Network, Svg, WebSockets) | 6.12.0 |
| Crypto | cryptography | 50.0.2 |
| Spell check | pyspellchecker | 0.9.1 |
| Windows media (/np) | winrt-* packages | 4.1.0 / 10.0.28000 |
| Tests | pytest | 9.2.0 |
| Freezing | PyInstaller | 6.22.3 |
| Installer | Inno Setup 6 | 6.x |

No web engine and no Qt Quick/QML: the UI is plain Qt Widgets drawn with Qt's raster engine.

## Architecture

```
packaging/run_bchat.py ──> bchat/__main__.py  (arguments, lock check, QApplication, Fusion style)
                                │
                                ▼
                      bchat/mainwindow.py  MainWindow: tree/tabs, chat view, nick list, input, menus, tray
                         │            │             │
                         ▼            ▼             ▼
                 session.py      chatview.py     tools.py, preferences.py, networklist.py, ... (windows)
                 one network:    QTextBrowser     dialogs built on widgets.py (theme, frameless base)
                 socket, CAP,    rendering of
                 SASL, buffers   Buffer lines
                    │
                    ├── protocol.py   parsing + mIRC formatting (no Qt, pure functions)
                    ├── wsock.py      WebSocket transport (wss:// only)
                    ├── scram.py      SASL SCRAM-SHA-256 (standard library)
                    ├── dcc.py        DCC SEND/CHAT
                    └── commands.py   slash commands -> session calls / raw lines
```

Main rules the code follows:

- **`protocol.py` has no Qt.** Parsing and formatting are pure functions, tested directly.
- **`session.py` has no widgets.** It owns one connection (TCP, TLS, STARTTLS or WebSocket),
  capability negotiation, login, reconnects and the buffers (channel, private, server). Tests
  drive a real `Session` against `tests/fake_ircd.py`.
- **`mainwindow.py` wires sessions to the UI.** Buffers are data (`Buffer`, `Line`, `User` in
  `session.py`); `chatview.py` draws them.
- **Settings** are one `Config` dataclass (`config.py`) saved as JSON in `%APPDATA%\BChat`
  (or `BChat-data` next to the exe in portable mode). Unknown keys are ignored on load, so old
  and new settings files both load. Passwords never go into the JSON: `vault.py` keeps them in
  Windows Credential Manager (portable mode seals them with the Lock key or does not keep them).
- **Plugins** (`plugins.py`) get XChat's Python interface (`import xchat`), so XChat 2 scripts
  mostly work.
- **Updates** (`updater.py`) read the GitHub releases list, and install only a file whose
  SHA-256 and Ed25519 signature match the release manifest. The private signing key never
  leaves the owner's PC.

Module overview (lines of code, 11 Nov 2026; 21,800 lines in `bchat/`): the largest are
`mainwindow.py` (3,463), `session.py` (2,436), `preferences.py` (1,549), `tools.py` (957),
`dcc.py` (765), `commands.py` (663), `config.py` (655), `networklist.py` (618). Every module
starts with a one-line docstring that says what it is.

## Coding conventions

- Plain Python with type hints where they help; dataclasses for data.
- Each module starts with a docstring saying what it is and, for UI, which mockup it follows.
- Comments explain *why* (IRC quirks, Windows quirks, safety reasons), not what the next line does.
- UI text is short and plain. The app never says it works "like" another client.
- One icon style (Lucide outline), one theme system (`widgets.py`, 17 themes).
- New features carry a version mark in comments (`# 0.6.0: ...`) so the history is readable.

## Dependencies

- Runtime dependencies are listed in `pyproject.toml` (`PySide6`, `pyspellchecker`,
  `cryptography`); the winrt packages are optional (only `/np` uses them).
- **A new dependency needs a reason** that the standard library or Qt can't cover, and the
  owner's OK. SCRAM and the Lock use only `hashlib`/`hmac`; WebSockets use Qt's own module.
- Qt parts BChat does not use (Qt Quick/QML, PDF, Virtual Keyboard, software OpenGL,
  translations) are candidates to leave out of the package. See BUILD-GUIDE.md.
- `pyproject.toml` still says `version = "0.1.0"`; the real version comes from
  `packaging/version_info.txt` at build time.

## Development workflow

1. **Idea or bug** → a mockup or written plan first. No code before the owner says OK.
2. **Build it in source**, with tests next to it (`tests/test_<version>.py` or the matching file).
3. **Development validation** (stage 1): the full test suite, the button check, and for anything
   touching packaging or start-up, the packaged-app checks. See TESTING.md.
4. **Test build** (stage 2, only on the owner's word): `0.x.y-TESTn` installer, validated,
   VirusTotal-checked, then handed over with a manual test list.
5. **Release** (stage 3, only on the owner's word): commit, push, tag, publish. See
   RELEASE-CHECKLIST.md.

Nothing is committed, pushed, tagged or published without the owner's explicit approval.
Unrelated changes go in separate commits (for example networking vs packaging).

## Architectural principles

- Never surprise the user: nothing joins, accepts a file, opens a link or sends a report by itself.
- Safe defaults: certificates are checked, STARTTLS never falls back to plain text, `ws://` is
  refused, SASL PLAIN only over TLS, programs received by DCC always ask.
- Classic IRC first; IRCv3 features are used when the server offers them and stay invisible
  otherwise.
- Keep the code honestly clean: no obfuscation, no hidden network calls, no `subprocess`
  tricks. Antivirus false alarms are reported to the vendor, never "fixed" by hiding behaviour.

## Performance expectations

Measured numbers are kept in [QA-BASELINE.md](QA-BASELINE.md). Expectations:

- Start to visible main window well under 1 s on the build PC (measured: 0.64 s).
- Idle CPU under 1 % of one core with connected networks (measured: ~0.4 %).
- No memory growth while idle; working set ~110 MB with one network (measured: 108.6 MB).
- A change that moves any of these by more than ~10 % needs an explanation before release.

## Security expectations

- Passwords: Credential Manager or nothing; never in `config.json`, logs or reports.
- Problem reports go out only after the user presses Send, and show exactly what is sent.
- Updates: checksum + Ed25519 signature, tampered manifests refused.
- Every test build: secret scan of the source, VirusTotal on installer and `BChat.exe`.
- Tests never touch the real Credential Manager, report server, update server, sounds or
  settings (`tests/conftest.py`).
