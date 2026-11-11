# BChat QA baseline

The current known-good build and its measured numbers. New builds are compared against this.
Only measured values are written here; anything not measured says so.

## Current baseline: 0.6.1 release (12 Nov 2026)

Released as `v0.6.1` from commit `f68b3b8`. Numbers from QA run `20261112-030913`
(`tools/qa.py all --perf-quick`), one `perf_bench.py --quick` re-run alone, and the release checks.

| Item | Value |
| --- | --- |
| Version string | `0.6.1` (`version_info` 0.6.1.0) |
| Installer | `BChat-0.6.1-setup.exe`, 35,807,285 bytes |
| Installer SHA-256 | `baf9594efe8c1c7090528f58c8f4f41df145cfd7d573860353579660a2609a43` |
| `BChat.exe` SHA-256 | `aa871168053e34be1985451b74bcf890f0101373d783e93be55866cd404530b8` |
| VirusTotal installer | 1 / 71 (DeepInstinct, ML false positive; flags some builds and not others) |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (quick mode, one run)

| Measure | 0.6.1 | 0.6.0 |
| --- | --- | --- |
| Start to visible main window / joined | 0.64 s / 0.73 s | 0.64 s / 0.73 s |
| Idle, 3 networks: CPU / working set | 1.6 % / 108.4 MB | 1.1 % / 108.7 MB |
| Load 300 msg/s: CPU / working set | 58 % / 117.4 MB | 53 % / 117.2 MB |
| Load: marker latency / worst UI stall | 6 ms / 40 ms | 9 ms / 47 ms |
| Burst of 5000 messages: time / worst UI stall | 7.5 s / 243 ms (re-run alone: 7.3 s / 52 ms) | 5.7 s / 0.86 s |
| History 10k to 20k lines | 137.8 to 138.3 MB | 136.9 to 137.0 MB |
| All 15 tabs full / soak growth | 245.3 MB / 0.0 MB/min | 244.3 MB / 0.0 MB/min |

The burst change is on purpose: incoming lines are now handled 30 ms at a time with the event loop
in between, so the window keeps answering (worst stall 52-243 ms instead of 0.86-1.4 s). The price is
throughput: the same 5000 lines take longer (TEST3 4.8 s, TEST4 6.4 s, release 7.3-7.5 s; noisy on
this PC). Every message is still counted.

### Test results

| Check | Result |
| --- | --- |
| `pytest` (source) | 639/639 passed, 0 known deviations (FINDING-01 fixed) |
| Protocol | 88/88; conformance table 63 OK |
| `build_check.py` / `bundle_check.py` | 8/8 / 23/23 |
| `frozen_check` / `frozen_features` / `frozen_reports` / `frozen_extra` | 19/19 / 60/60 / 19/19 / 59/59 |
| Button check | 673 controls, no problems |
| Secret scan / history scan | PASS / 733 file versions, none of the 8 own secrets |
| Real servers (TEST4 exe, `build/realtest/real_test061c.py`) | 14/14: Ergo testnet, UnrealIRCd TLS, IPv6-only, `//whois` |
| Release | tag `v0.6.1` = `f68b3b8`, latest, anonymous download hash = build, signed manifest OK, updater offers 0.6.1 to 0.3.0 / 0.5.0 / 0.6.0 / 0.6.1-TEST4 |

## Previous baseline: 0.6.0 release (11 Nov 2026)

Released as `v0.6.0` from commit `ce6af76`, slim packaging (the candidate below, approved
and made the normal build in commit `a63e07f`). Numbers from QA run `20261111-230044`
(`tools/qa.py all --perf-quick`) and the release checks.

| Item | Value |
| --- | --- |
| Version string | `0.6.0` (`version_info` 0.6.0.0) |
| Build configuration | `packaging/BChat.spec` (slim filter, 126 files left out); PyInstaller 6.22.3 one-folder, no UPX, windowed; Inno Setup lzma2 solid; Python 3.12.10, PySide6 6.12.0 |
| Installer | `BChat-0.6.0-setup.exe`, 35,812,376 bytes (34.2 MiB) |
| Installer SHA-256 | `a159a0b4d24684292ab91a6b17111457d78e360903324515a57c403b779cb3f5` |
| `BChat.exe` SHA-256 | `54ca04340e36ba5ab454bd80adf65b041b4e98f6ed485ea246fad69d62dcd8f1` |
| Installed size | not re-measured for the release (slim TEST2 was 99,010,555 bytes, 209 files) |

### Performance (`perf_bench.py --perf-quick`, one run)

Quick mode: 2 start-ups instead of 5, 0.5-minute soak instead of 5. Same build PC as below.

| Measure | 0.6.0 | 0.6.0-TEST2 (full run) |
| --- | --- | --- |
| Start to visible main window | 0.64 s | 0.64 s |
| Start to joined channel | 0.73 s | 0.74 s |
| Quit | 0.10 s | 0.09 s |
| Idle, 3 networks: CPU / working set | 1.1 % / 108.7 MB | 1.6 % / 106.1 MB |
| Load 300 msg/s: CPU / working set | 53 % / 117.2 MB | 57 % / 138.9 MB |
| Load: marker latency / worst UI stall | 9 ms / 47 ms | 8 ms / 47 ms |
| Burst of 5000 messages: time / worst UI stall | 5.7 s / 0.86 s | 10.4 s / 8.4 s |
| History 10k to 20k lines | 136.9 to 137.0 MB | 152.2 to 152.3 MB |
| All 15 tabs full | 244.3 MB | 247.3 MB |
| Soak growth | 0.0 MB/min (0.5 min) | -0.8 MB/min (5 min) |

All 13 perf checks passed (every message counted, clean quit). The burst gain is not explained
by a code change aimed at it; treat it as "not worse" until a full run repeats it.
`tools/qa/data/perf-baseline.json` still holds the TEST2 full run.

### Test results

| Check | Result |
| --- | --- |
| `pytest` (source) | 618: 617 passed + 1 known deviation (FINDING-01 CASEMAPPING, strict xfail) |
| Protocol | 86/87 + 1 known deviation; conformance table 63 OK |
| `build_check.py` / `bundle_check.py` | 8/8 / 23/23 |
| `frozen_features.py` / `frozen_reports.py` | 60/60 / 19/19 |
| `frozen_check.py` | 19/19 on re-run alone (18/19 in the full run: a stray key landed in the test window) |
| `frozen_extra.py` | 59/59 on re-run (57/59 in the full run, same stray key) |
| `full_button_check.py` | 673 controls, no problems |
| Secret scan | pass |
| Update manifest | signature OK; tampered SHA/version refused; 0.3.0, 0.4.0, 0.5.0 and 0.6.0-TEST3 are offered 0.6.0 |
| VirusTotal installer | 0 / 70 |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, seen on every BChat build; judged a false positive) |

Known limitations listed under 0.6.0-TEST2 below still apply, except that FINDING-02
(friends tracking started before the server's feature list) is fixed in 0.6.0.

## Previous baseline: 0.6.0-TEST2 (11 Nov 2026)

This is a **test build**, not a release. It is the newest build that passed every check below,
including a real-server run on servers the owner authorised (the owner's own manual test of
TEST2 is still to come). Its source is commit `332b9ca` (0.6.0 batch B) plus
0.6.0 batch C, which was not yet committed when measured.

| Item | Value |
| --- | --- |
| Version string | `0.6.0-TEST2` (`version_info` 0.6.0.2) |
| Build configuration | PyInstaller 6.22.3 one-folder, no UPX, windowed; Inno Setup lzma2 solid; Python 3.12.10, PySide6 6.12.0 |
| Installer | `BChat-0.6.0-TEST2-setup.exe`, 47,828,901 bytes (45.6 MiB) |
| Installer SHA-256 | `a077ba4f09d097410cd48511440071689914f6ef1cf50a906d791bf6eae7ad6b` |
| `BChat.exe` SHA-256 | `afa655d17035c987508411c2386adc601f63fb81297eec886f2f38647f1aa91a` |
| Installed size | 147,335,381 bytes (140.5 MiB), 335 files |
| DLLs loaded (all main windows open) | 142 |

### Performance (build PC, 5 runs each, medians, min-max)

Measured with throwaway settings and one local network; build PC = Windows 11,
AMD Ryzen 9 5950X (16 cores), 32 GB RAM, NVIDIA RTX 5080. Values from other PCs will differ; compare like with like.

| Measure | Median | Range |
| --- | --- | --- |
| Start to visible main window | 0.64 s | 0.63-0.68 s |
| Start to joined channel (local server) | 0.73 s | 0.72-0.77 s |
| Idle working set (20 s settle, 60 s idle) | 108.6 MB | 107.2-108.7 MB |
| Idle private memory | 54.2 MB | 53.9-54.2 MB |
| Idle CPU (60 s, % of one core) | 0.39 % | 0.05-0.47 % |
| Working set with all main windows open, two networks | 133.6 MB | one run |

Not measured yet: CPU and memory under heavy message traffic, memory after long sessions,
shutdown time, connection time to real servers (real-server lag over 5 minutes: 0-31 ms plain,
1-10 ms TLS on the owner's LAN server).

### Test results

| Check | Result |
| --- | --- |
| `pytest` (source) | 523 tests: 522 passed + 1 known-flaky (`test_skip_motd_and_motd_command`), passed when re-run alone |
| `full_button_check.py` | 673 controls, no problems |
| `frozen_check.py` | 19/19 |
| `frozen_features.py` | 60/60 |
| `frozen_reports.py` | 19/19 |
| Packaged extra check (two networks, TLS, IRCv3, messages, reconnect, images, settings, clean quit) | all pass |
| Real servers (owner-authorised LAN server plain + TLS, public WebSocket test network) | 12 areas pass; real IPv6 and multi-port fallback not testable |
| VirusTotal installer | 0 / 70 |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, seen on every BChat build; judged a false positive) |

### Known limitations

- `BChat.exe` and the installer are not code-signed; APEX flags `BChat.exe` on every build,
  DeepInstinct has flagged some installers (0.5.0, a test build) and not others.
- Bouncer detection reports "soju" on servers that offer `soju.im/` or `znc.in/` capabilities
  themselves (seen on Ergo). Present since 0.4.0.
- In "IPv6 only" mode a server without IPv6 shows "Host not found" (true, but could say "no
  IPv6 address").
- The build PC has no IPv6, no Windows Sandbox, no Hyper-V/VM and no Remote Desktop, so those
  environments are only tested by the owner.
- `pyproject.toml` version is out of date (0.1.0); the build uses `version_info.txt`.

## Slim packaging check (same 0.6.0-TEST2 code)

Validated 11 Nov 2026, approved and used from 0.6.0-TEST3 on. Leaves out unused Qt parts (Quick/QML,
Qt6OpenGL, PDF, Virtual Keyboard, software OpenGL, translations).

| Item | Baseline | Slim |
| --- | --- | --- |
| Installer | 47,828,901 B | 35,812,024 B |
| Installed | 147,335,381 B, 335 files | 99,010,555 B, 209 files |
| Start to window (median) | 0.64 s | 0.67 s |
| Idle working set (median) | 108.6 MB | 108.7 MB |
| Idle CPU (median) | 0.39 % | 0.21 % |
| DLLs loaded | 142 | 140 (Qt6Pdf + qpdf not present) |
| Tests | as above | same results |
| VirusTotal installer | 0 / 70 | 1 / 70 (DeepInstinct, judged a false positive) |
| Installer SHA-256 | — | `95433fd4bd410c29e60dc138b48dd165e451ced6e7eb5978f9c8a4d37b277bc8` |

Start time and CPU differences are within run-to-run noise.

## Earlier release: 0.5.0 (11 Nov 2026)

| Item | Value |
| --- | --- |
| Installer | 47,674,777 bytes, SHA-256 `fa3cda46dbbb5a63272eee66ab380d6d72c23f4c97831a036abdbae471897a5f` |
| Tests at release | full pytest passed; frozen_check 19, frozen_features 60, frozen_reports 19 |
| VirusTotal | 1 / 68 (DeepInstinct, reported to the vendor) |
| Performance | not measured |

## History

| Date | Build | Change to the baseline |
| --- | --- | --- |
| 2026-11-11 | 0.6.0-TEST2 | First recorded baseline |
| 2026-11-11 | 0.6.0 | Release; slim packaging; quick perf run |
