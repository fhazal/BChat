# BChat testing

What is tested, how to run it, what is known to be weak, and what still needs a person.
Numbers here are from 11 Nov 2026 (0.6.0 batch C); current results go in
[QA-BASELINE.md](QA-BASELINE.md).

## The QA runner

One command runs the stages and writes one report:

```powershell
python tools/qa.py --list                              # the stages
python tools/qa.py tests                               # full source test suite
python tools/qa.py packaged --exe dist/BChat/BChat.exe # the built app
python tools/qa.py tests packaged                      # several stages
python tools/qa.py all                                 # everything (~20 min)
```

| Stage | Runs | Mandatory | Heavy |
| --- | --- | --- | --- |
| `build-check` | `tools/qa/build_check.py` | yes | |
| `tests` | `pytest tests` | yes | |
| `protocol` | `pytest` on the protocol files (SKIP when `tests` runs too: same files) | yes | |
| `irc` | `pytest` on the fake-server integration files (SKIP when `tests` runs too) | yes | |
| `audit` | `dev-tools/secret_scan.py` (dependency/packaging audit comes with item G) | yes | |
| `packaged` | `tools/qa/bundle_check, frozen_check, frozen_features, frozen_reports, frozen_extra` | yes | yes |
| `ui` | `dev-tools/full_button_check.py` | yes | yes |
| `perf` | not built yet: always SKIP (item F) | no | yes |

Rules the runner keeps:

- It only orchestrates: each stage is an independent tool run as a child process; stdout,
  stderr, exit code and time are kept per step.
- Status per stage: **PASS**, **FAIL**, **SKIP** (deliberately not run, with the reason) or
  **NOT RUN** (couldn't run: missing exe, tool or Python package, heavy-job lock, interruption).
  SKIP and NOT RUN never count as passed; a run where nothing ran is **NO RESULT**.
- Overall PASS (exit 0) only when every mandatory stage that was asked for passed. FAIL or NO
  RESULT exit 1, bad arguments 2, Ctrl+C / Ctrl+Break 130 (**INTERRUPTED**; the running child
  and its BChat are killed). `report.json` is written as **INCOMPLETE** at the start and after
  every step, so a crashed or killed run never leaves a PASS.
- A tool's JSON or JUnit result overrides a zero exit code when it lists failures; a result file
  left over from an earlier run is deleted first and never read as this run's.
- No retries. Known flaky tests (`tools/qa/data/known-flaky.json`) are labelled when they fail,
  and the failure still counts.
- Heavy stages (`packaged`, `ui`, `perf`) take a lock (`qa-reports/.heavy.lock`, freed by Windows
  if the runner dies) and refuse to start while another BChat test instance runs (the installed
  copy doesn't count).
- Fewer checks than `tools/qa/data/baseline.json` gives a warning: coverage may have been lost.

Report folder `qa-reports/<yyyymmdd-hhmmss>/` (git-ignored): `summary.md` (readable),
`report.json` (source commit and uncommitted-file count, exe path/version/SHA-256, build recipe
SHA-256, PyInstaller/PySide6/cryptography/pytest versions, Python, Windows, CPU, RAM, GPU,
every stage and step with status, reason, exit code, time, counts, failed and skipped checks,
log paths), `logs/<stage>/<step>.stdout.log` / `.stderr.log`, `results/` (each tool's own JSON,
JUnit XML, screenshots).

## Quick reference

| Level | Command | Count | Time |
| --- | --- | --- | --- |
| Source tests (unit + integration + UI) | `python -m pytest -q` | 523 | ~4 min |
| Every control in every window | `python dev-tools/full_button_check.py <out-dir>` | 673 controls | ~3 min |
| Packaged app: files in the bundle (static) | `python tools/qa/bundle_check.py [--exe EXE] [--out DIR]` | 23 checks | seconds |
| Packaged app: start, SSL, real window | `python tools/qa/frozen_check.py [--exe EXE] [--out DIR]` | 19 checks | ~1 min |
| Packaged app: features from inside the exe | `python tools/qa/frozen_features.py [--exe EXE] [--out DIR]` | 60 checks | ~1 min |
| Packaged app: problem reports | `python tools/qa/frozen_reports.py [--exe EXE] [--out DIR]` | 19 checks | ~1 min |
| Packaged app: networks, IRCv3, reconnect, images, needed DLLs, settings, clean quit | `python tools/qa/frozen_extra.py [--exe EXE] [--out DIR] [--mode clean] [--env K=V]` | 59 checks | ~2 min |
| Secret scan of what git would commit | `python dev-tools/secret_scan.py` | — | seconds |

The `tools/qa/` tools all take the same options: `--exe` (default `dist/BChat/BChat.exe`),
`--out` (default a new temp folder), `--expect` (default: the exe's own version resource, or
`BCHAT_EXPECT`). Each prints `OK`/`FAIL`/`SKIP` lines, writes `<out>/<tool>.json` (exe hash,
version, Python, Windows, time, results) and exits 1 when anything failed.
`dev-tools/` (button check, secret scan for now; private release tools for good) stays
outside git.

## Isolation rules (every test)

`tests/conftest.py` makes sure no test touches the real world:

- `QT_QPA_PLATFORM=offscreen` (no windows on screen unless a test asks for real ones).
- `BCHAT_VAULT=memory`: passwords never reach Windows Credential Manager.
- `BCHAT_REPORT_URL` points at a dead local port: no problem report leaves the PC.
- `bchat.updater.UPDATE_URL = ""`: no request to GitHub.
- `winsound.PlaySound` is replaced: no sounds.
- Every test gets its own temporary settings folder (`tmp_path`).

Packaged-app checks start `BChat.exe --config-dir <temp>` with `BCHAT_VAULT=file` and talk only
to local sockets (fake IRC server, fake release server, fake report receiver).

## Unit tests

Pure functions without a network: IRC line parsing, mIRC formatting and colours
(`test_core.py`), `irc://` links (`test_irclink.py`), highlight rules (`test_next3.py`), the
SCRAM client against a SCRAM server (`test_060.py`), Lock key, seal and limits
(`test_060c.py`), update version ordering and manifest signatures (`test_updates.py`), vault
behaviour (`test_vault.py`).

## Integration tests (IRC)

`tests/fake_ircd.py` is a scripted IRC server on `127.0.0.1` (random port, optional TLS with a
throwaway certificate). It answers `CAP LS/REQ/END` (extra capabilities on request), `NICK`,
`USER`, `JOIN`, `MODE` queries, `WHO`/WHOX, `WHOIS`, `CHATHISTORY`, `PING`, `QUIT`, `STARTTLS`
(ok or refuse), and SASL `PLAIN`, `EXTERNAL` (client certificate) and `SCRAM-SHA-256` (good or
bad server proof). Anything else can be pushed with `srv.send(line)` and everything BChat sends
is in `srv.received`.

### The deterministic simulator: `tests/qa_ircd.py`

A second, richer test server (QA item A, 11 Nov 2026). `fake_ircd.py` stays as it is for the tests
written against it; new integration tests use `qa_ircd.py`. It is a testing simulator, not a
complete IRC or IRCv3 server.

- **Server:** many clients at once, any number of independent servers (own name, network,
  port, capabilities, ISUPPORT, MOTD, accounts, server password), plain or TLS (throwaway
  certificate for `localhost`/`127.0.0.1`/`::1`), IPv4 or IPv6 loopback. Listens on localhost
  unless told otherwise. Server time is deterministic by default (fixed start + 1 s per stamp)
  or from an injected clock.
- **Protocol:** PASS/NICK/USER registration (431/432/433/451/462/464), 001-005 + MOTD or 422,
  PING/PONG, CAP LS (302 values, multi-line) / REQ (all-or-nothing ACK/NAK) / LIST / END,
  SASL PLAIN and EXTERNAL (900/903/904/906/908), JOIN/PART/NAMES (multi-prefix,
  userhost-in-names, extended-join)/TOPIC, PRIVMSG/NOTICE/TAGMSG with echo-message,
  server-time, account-tag and client `+tags`, AWAY + away-notify, WHO + WHOX, WHOIS, USERHOST,
  ISON, channel and user MODE with operator checks (482), bans incl. `~a:` account bans,
  KICK, NICK changes, QUIT, account-notify, chghost.
- **Scenarios:** `disconnect` (ERROR + close), `drop` (TCP reset), `refuse` new connections
  (reset or ERROR), `delay`, `silent`, `answer_ping=False`, `sasl_result`, `deny_op`,
  `send_raw` (anything, also broken bytes), `numeric` / `server_error`, `change_nick`,
  `give_op` / `take_op` / `apply_mode` / `kick`, `set_account`, `set_host`, `inject` messages
  from anyone, `burst` numbered messages, `add_ghosts` (big nick lists of scripted users).
- **Synchronisation:** every line in or out is an event; tests wait with `wait_for(...)`,
  `wait_handled(...)` (after the server has applied a line), `wait_registered`,
  `wait_clients`, `mark()` + `since=`. `pump=app.processEvents` keeps a Qt client running
  while a test waits.
- **Cleanup:** the `qa_server` fixture (`tests/conftest.py`) stops every server after its test
  and fails the test if a simulator thread is still alive; `stop_all()` runs at exit.
- **Tests of the simulator itself:** `tests/test_qa_ircd.py` (28, part of the `irc` stage),
  including two with real BChat windows (two clients talking; reconnect after a drop).

`test_live.py` (167 tests) drives a real `MainWindow` + `Session` against it: login, nick
collisions, TLS with valid/invalid certificates, SASL success and failure, user lists, WHOIS,
the nick menu, every enabled menu item. Version files (`test_040.py`, `test_050.py`,
`test_060.py`, `test_060c.py`, `test_batch4.py`, `test_comfort.py`, `test_welcome.py`) add the
features of each release against the same server.

## IRC protocol coverage (honest status)

**Superseded by [PROTOCOL-CONFORMANCE.md](PROTOCOL-CONFORMANCE.md)** (QA item B, generated from
`tools/qa/data/conformance.json` and real test results by `python tools/qa.py protocol`). The table
below is the first hand-written survey of 11 Nov 2026, kept for history.

| Area | Status | Where |
| --- | --- | --- |
| Line parsing, tags, prefixes, CTCP, mIRC formatting | Implemented, tested | `test_core.py` |
| Registration, nick in use, 001/005 ISUPPORT (PREFIX, CHANMODES, EXTBAN, NETWORK, WHOX, MONITOR, WATCH) | Implemented, tested | `test_live.py`, `test_060c.py` |
| CAP negotiation (LS 302 multi-line, REQ/ACK/NAK, NEW/DEL), per-network capabilities off | Implemented, tested | `test_live.py`, `test_060c.py` |
| server-time, message-tags, account-tag, extended-join, account-notify, away-notify, multi-prefix, userhost-in-names, invite-notify, batch, labeled-response | Implemented; server-time, tags, labeled-response, account tracking tested | `test_060.py`, `test_060c.py`, `test_batch4.py`, `test_live.py` |
| chghost, setname | Implemented (requested when offered); **no test of their own** | — |
| +typing / +reply client tags | Implemented, tested | `test_batch4.py` |
| draft/chathistory playback, bouncer playback (ZNC/soju) | Implemented, tested | `test_040.py` |
| SASL PLAIN (TLS only), EXTERNAL, SCRAM-SHA-256 | Implemented, tested | `test_live.py`, `test_040.py`, `test_060.py` |
| TLS, certificate trust (ask/once/always/changed), STARTTLS (never falls back) | Implemented, tested | `test_safety.py`, `test_060.py` |
| WebSocket transport (`wss://` only) | Implemented, tested with a local WebSocket server; checked once against a public test network (11 Nov 2026) | `test_060c.py` |
| MONITOR, WATCH fallback | Implemented, tested | `test_060c.py` |
| DCC SEND / CHAT, trust list | Implemented, tested (real local transfer) | `test_060.py`, `frozen_features.py` |
| Channel modes, bans, extbans `~a:`/`$a:` | Implemented; bans and account bans tested, other modes partly | `test_060c.py`, Channel Central tests |
| Reconnect after a drop, rejoin channels | Implemented, tested (one source test, packaged-app extra check, real server once) | `test_live.py::test_reconnects_after_drop` |
| Malformed lines from the server | Implemented defensively; **one test only** (garbage doesn't crash) | `test_live.py::test_garbage_from_server_does_not_crash` |
| Connection timeouts (server silent, no PONG) | Implemented (keep-alive); **not tested** | — |
| STS (strict transport security) | Implemented; tested: upgrade to TLS and refusing a bad certificate | `test_live.py::test_sts_moves_to_ssl_and_refuses_a_bad_certificate` |
| draft/multiline, draft/metadata, webpush, account registration, read markers | **Not supported** | — |
| IPv6 connections | Implemented, tested on loopback only; **no real IPv6 network on the build PC** | `test_060c.py` |

BChat makes no claim of full IRCv3 compliance.

## UI tests

- Source tests build real widgets offscreen and check what they show (themes, buttons,
  Preferences pages, notification cards, tray menu, URL Grabber, Lock pages).
- `full_button_check.py` opens every window on real, visible widgets, clicks every button and
  toggles every control, with stubs answering blocking dialogs, and saves a screenshot of each
  window. It fails on exceptions, unbuilt pages and disabled menu items.
- `test_theme_surfaces.py` checks painted surfaces in all themes.

## Packaged application tests

Source tests can't prove the frozen app has every DLL, plugin and asset. `tools/qa/` checks the
real `BChat.exe` (any path with `--exe`, never the installed copy):

- `bundle_check.py` (static, nothing started): every file of `bchat/assets` is bundled with the
  same bytes, `version.txt` = exe version resource = expected version, the Python/VC++ runtime,
  Qt core/GUI/widgets/network/SVG/WebSockets, the Windows platform plugin, the Schannel TLS
  backend, SVG/ICO/JPEG/GIF plugins and the spell-check word list are on disk.

- `frozen_check.py`: starts the exe against the fake server over TLS, clicks its real window,
  menus and buttons, checks the window title, scale and that nothing sends QUIT by accident.
- `frozen_features.py`: a probe plugin inside the exe opens every window, all Preferences
  pages, all 17 themes, spell check, notification cards, the tray, the real Credential Manager
  (cleaned up after), Windows media controls, the updater signature check, plugin imports; a
  real DCC file comes in over a local socket.
- `frozen_reports.py`: crash and freeze reports inside the exe, to a local receiver.

- `frozen_extra.py`: two networks at once (plain + TLS), IRCv3 server-time,
channel and private messages both ways, reconnect after a drop, PNG/ICO/SVG/JPEG/BMP reading,
the Qt files BChat needs really loaded (platform plugin, TLS backend, SVG/ICO/JPEG plugins),
settings kept after a restart, clean quit, and the loaded DLL list. It can run in normal, "clean"
(PATH = System32 only, empty APPDATA), forced software/desktop OpenGL and 2x scale modes.

## Regression testing

Every fixed bug gets a test in the file of the version that fixed it, named after what broke.
The full suite runs before every test build and every commit; nothing is handed over with a
failing test.

## Performance testing

Two tools (QA item F+C, 11 Nov 2026), both on local simulator servers only:

- `tools/qa/loadgen.py`: the load generator. On its own it starts local servers, writes a BChat
  settings folder for them and runs one scenario once BChat has joined:
  `python tools/qa/loadgen.py --networks 2 --channels 5 --nicks 2000 --scenario flood --rate 200 --duration 30`
  (then start BChat with the `--config-dir` it prints). Scenarios: `flood` (messages at a steady
  rate over every channel), `storm` (join/part/nick/quit of scripted users), `burst` (N messages at
  once), `history` (N lines into one channel), `soak` (low steady traffic). Deterministic text.
- `tools/qa/perf_bench.py` (runner stage `perf`): the packaged exe with throwaway settings and a
  probe plugin inside it that counts every channel message (`hook_print`), measures event-loop
  stalls with a 20 ms timer and quits on request. Phases: start-up x5 (window, joined, quit),
  one session with 3 networks x 5 channels and 2000 scripted users: idle, load (300 msg/s + 20
  events/s for 60 s), burst (5000 at once), history (20000 lines; tabs keep 5000), soak
  (`--soak-min`, default 5), idle again, quit. `--quick` is a smoke run, not for comparisons.
  Fails on: the app died or hung, a message lost, a marker never shown. Everything else is a
  measurement compared with `tools/qa/data/perf-baseline.json` (set only with `--save-baseline`);
  changes over 15 % are warnings. Results and the baseline are in QA-BASELINE.md.

Limitations: one desktop PC (numbers on a slower PC will differ); CPU and memory are sampled
from outside every few seconds (Windows process counters); the probe plugin itself costs a
little; the simulator runs in the same machine and competes for CPU; real-network effects
(latency, TLS overhead to remote servers) are not part of it.

## Known flaky tests

| Test | Symptom | Cause | Handling |
| --- | --- | --- | --- |
| `test_040.py::test_skip_motd_and_motd_command` | fails now and then when the PC is busy (e.g. a packaged-app check running at the same time) | timing: waits for the MOTD with a fixed timeout | re-run alone; it passed alone every time (11 Nov 2026) |

## Manual testing (needs the owner)

Automated tests can't cover these; each test build comes with a list:

- Real IRC networks and bouncers (the owner's servers, ZNC), real IPv6, real VPN on/off.
- How things look and feel: layout, wording, themes on the owner's screen and scaling.
- Windows integration: real notifications, tray behaviour, Start with Windows after a reboot,
  installer and uninstaller, updating from the previous version.
- Other PCs: clean Windows, virtual machines, Remote Desktop, other graphics drivers
  (the build PC has none of Windows Sandbox, Hyper-V, Remote Desktop or VM software enabled).

## Gaps and plan

Found while writing this (11 Nov 2026); the plan to close them is proposed separately:

- `dev-tools/` and `build/` are outside git, so the QA and build tools have no history and
  can't be reproduced from the repository.
- ~~The fake server serves one client at a time and can't script timeouts, silent servers or
  operator replies~~: done with `tests/qa_ircd.py` (item A). BChat's own behaviour against it
  (protocol conformance) is item B.
- No high-volume / long-running test, no automated performance comparison.
- No single QA entry point and no saved QA report per build.
