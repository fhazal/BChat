# BChat QA baseline

The current known-good build and its measured numbers. New builds are compared against this.
Only measured values are written here; anything not measured says so.

## Current baseline: 0.6.0-TEST2 (11 Nov 2026)

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

## Candidate under review: slim packaging (same 0.6.0-TEST2 code)

Validated 11 Nov 2026, **not yet approved**. Leaves out unused Qt parts (Quick/QML,
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

## Last release: 0.5.0 (11 Nov 2026)

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
