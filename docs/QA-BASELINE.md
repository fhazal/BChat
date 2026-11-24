# BChat QA baseline

The current known-good build and its measured numbers. New builds are compared against this.
Only measured values are written here; anything not measured says so.

## Current baseline: 0.8.10 release (24 Nov 2026)

Released as `v0.8.10` from commit `2aec568` (File transfers gets its own Settings group with Options and Trusted
people; *File offers* and *Direct chat offers* menus: Ask me / Accept from trusted people / Accept from everyone /
Ignore them, also `/sreq` and `/creq`; proxy "Not for:" list; `/updatenl`, `/queryrn`, `/timerN`). Numbers from QA
run `20261124-131848` on the release build (`build-check audit packaged ui perf`, full perf mode); source stages
from TEST2 run `20261124-123301` (same code apart from the version number).

| Item | Value |
| --- | --- |
| Version string | `0.8.10` (`version_info` 0.8.10.0) |
| Installer | `BChat-0.8.10-setup.exe`, 43,434,564 bytes |
| Installer SHA-256 | `7b8c63e718159155094a05584bbdd4df966714dbd282f0a091552350192d1599` |
| `BChat.exe` SHA-256 | `016f006167aa290fa34f981e7d10dde4546dcc174c7766cc549f73f909b608e0` |
| Packaged files | 225 |
| VirusTotal installer | 1 / 69 (DeepInstinct, new; false-positive report sent 24 Nov) |
| VirusTotal `BChat.exe` | 2 / 70 (APEX and Zillya, as on 0.8.9) |

### Performance (full mode)

| Measure | 0.8.10 |
| --- | --- |
| Start to window | 0.57 s |
| Start to joined (15 channels) | 1.6 s |
| Idle working set | 110.0 MB |
| Load 300 msg/s: CPU / worst UI stall | 66.7 % / 50 ms |
| Burst of 5000 messages: time / worst UI stall | 5.5 s / 49 ms |
| History 10k lines / all 15 tabs full | 176.5 / 294.8 MB |
| 5-minute soak, all tabs full | -0.5 MB/min (no growth) |

### Test results

pytest 1245 collected, all passed (TEST2 run); release build: build-check, secret scan, packaged 5/5, ui 824
controls no problems, perf PASS. Separate QA chat: QA PASSED 0.8.10. Published release checked: tag `v0.8.10`,
latest, not draft/pre-release, anonymous download SHA-256 matches, the published update file is byte-identical to
the signed one, 0.8.9 and 0.8.10-TEST2 are offered 0.8.10, 0.8.10 is not.

## Previous baseline: 0.8.9 release (23 Nov 2026)

Released as `v0.8.9` from commit `95954b4` (passive file sends: *Send files* Normal / Passive / Auto, Auto sends
passive when UPnP opened nothing; closed dialogs are freed instead of staying hidden until quit). Numbers from QA
run `20261123-212718` on the release build (`build-check audit packaged ui perf`, full perf mode); source stages
from TEST1 run `20261123-204556` (same code apart from the version number).

| Item | Value |
| --- | --- |
| Version string | `0.8.9` (`version_info` 0.8.9.0) |
| Installer | `BChat-0.8.9-setup.exe`, 43,440,951 bytes |
| Installer SHA-256 | `7bec5c851c6f54780249dc118f29a834a19f55a36e48f3e2aa446f3d7b66beff` |
| `BChat.exe` SHA-256 | `26bb3c171403fef17b448e250c142b0a719f38a1bd920f5215bea1d959ac571e` |
| Packaged files | 225 |
| VirusTotal installer | 0 / 69 |
| VirusTotal `BChat.exe` | 2 / 70 (APEX and Zillya, as on 0.8.8) |

### Performance (full mode)

| Measure | 0.8.9 |
| --- | --- |
| Start to window | 0.53 s |
| Start to joined (15 channels) | 1.6 s |
| Idle working set | 109.7 MB |
| Load 300 msg/s: CPU / worst UI stall | 60.7 % / 50 ms |
| Burst of 5000 messages: time / worst UI stall | 4.3 s / 50 ms |
| History 10k lines / all 15 tabs full | 177.7 / 300.6 MB |
| 5-minute soak, all tabs full | -0.3 MB/min (no growth) |

### Test results

pytest 1232 collected, all passed (TEST1 run); release build: build-check, secret scan, packaged 5/5, ui 816
controls no problems, perf PASS. Separate QA chat: QA PASSED 0.8.9. Published release checked: tag `v0.8.9`,
latest, not draft/pre-release, anonymous download SHA-256 matches, the published update file is byte-identical to
the signed one, its signature verifies and a copy with a changed checksum is refused, 0.8.8 and 0.8.9-TEST1 are
offered 0.8.9, 0.8.9 is not.

## Previous baseline: 0.8.8 release (20 Nov 2026)

Released as `v0.8.8` from commit `52c9405` (0.8.7 + 0.8.8 work: find bar that lights every match, sound, speech,
router (UPnP) and ident support, Preferences pages that fit the screen, new commands such as /font /flush
/userhost; release fixes: the last DCC acknowledgement goes out before the file is moved, and closing an update
check while it runs no longer shows a late or doubled answer). Numbers from QA run `20261120-105810` on the
release build (`build-check audit packaged ui perf`, full perf mode); source stages from TEST4 run
`20261120-100023` (same code apart from the version number).

| Item | Value |
| --- | --- |
| Version string | `0.8.8` (`version_info` 0.8.8.0) |
| Installer | `BChat-0.8.8-setup.exe`, 43,438,091 bytes |
| Installer SHA-256 | `712f3d8d3979cb6654a1d9aae671dae301019916139343dd63b46a42d34c7614` |
| `BChat.exe` SHA-256 | `2183faaf0f2a6fb1719507f198ed522d16e90f2ffc19ba07547ce2cd4f5a830f` |
| Packaged files | 225 |
| VirusTotal installer | 0 / 70 |
| VirusTotal `BChat.exe` | 2 / 71 (APEX, as on every build, and Zillya) |

### Performance (full mode)

| Measure | 0.8.8 |
| --- | --- |
| Start to window | 0.54 s |
| Start to joined (15 channels) | 1.6 s |
| Idle working set | 109.9 MB |
| Load 300 msg/s: CPU / worst UI stall | 53.4 % / 35 ms |
| Burst of 5000 messages: time / worst UI stall | 3.4 s / 48 ms |
| History 10k lines / all 15 tabs full | 176.0 / 297.9 MB |

### Test results

pytest 1217 collected, all passed (TEST4 run); release build: build-check, secret scan, packaged 5/5, ui 813
controls no problems, perf PASS. Separate QA chat: QA PASSED 0.8.8. Published release checked: tag `v0.8.8`,
latest, not draft/pre-release, anonymous download SHA-256 matches, signed update file verifies and copies with a
changed version or checksum are refused, 0.8.6 and 0.8.8-TEST4 are offered 0.8.8, 0.8.8 is not.

## Previous baseline: 0.8.6 release (19 Nov 2026)

Released as `v0.8.6` from commit `1631846` (0.8.4 + 0.8.5 + 0.8.6 work: one Messages tab for private messages,
reconnect / flood protection / DCC / commands behave as IRC users expect, theme-coloured spin boxes; tests in
`58c3a09`). Numbers from QA run `20261119-141307` on the release build (`build-check audit packaged ui perf`,
full perf mode).

| Item | Value |
| --- | --- |
| Version string | `0.8.6` (`version_info` 0.8.6.0) |
| Installer | `BChat-0.8.6-setup.exe`, 35,943,285 bytes |
| Installer SHA-256 | `eb03bce82a8b2bb9ce9a68649c30109330442607af3d3dde3591ea60a1ddc709` |
| `BChat.exe` SHA-256 | `2e290c3ac563b6987a3be61151dbc32f056ddc39d1630c1969aaa9b35397a65d` |
| Packaged files | 209 |
| VirusTotal installer | 1 / 69 (DeepInstinct, machine-learning guess) |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (full mode)

| Measure | 0.8.6 |
| --- | --- |
| Start to window | 0.50 s |
| Start to joined (15 channels) | 1.6 s |
| Idle working set | 102.6 MB |
| Load 300 msg/s: CPU / worst UI stall | 61.3 % / 50 ms |
| Burst of 5000 messages: time / worst UI stall | 4.1 s / 59 ms |
| History 10k lines / all 15 tabs full | 170.7 / 288.0 MB |

### Test results

pytest 1061 collected, all passed (24 real-socket tests: SASL EXTERNAL certificate login over TLS, IPv6 DCC,
transfers past 4 GB, and a real ZNC 1.10.3 bouncer); release build: build-check, secret scan, packaged 5/5,
ui 748 controls no problems, perf PASS. Separate QA chat: QA PASSED 0.8.6. Published release checked: tag
`v0.8.6`, latest, not draft/pre-release, anonymous download SHA-256 matches, signed update file verifies and a
tampered copy is refused, 0.8.3 and 0.8.6-TEST2 are offered 0.8.6, 0.8.6 is not.

## Previous baseline: 0.8.3 release (18 Nov 2026)

Released as `v0.8.3` from commit `6be690c` (bug fix `2b1cd59`: through ZNC at a server's channel limit, 0.8.2's
joins asked again for channels the bouncer had already joined, the server answered 405 "too many channels" and
every tab emptied; 405 no longer empties a tab and joined channels are not asked for again). Numbers from QA run
`20261118-090332` on the release build (`build-check audit packaged ui perf`, full perf mode); source stages from
run `20261118-083533`, TEST1 build checks `20261118-085053`.

| Item | Value |
| --- | --- |
| Version string | `0.8.3` (`version_info` 0.8.3.0) |
| Installer | `BChat-0.8.3-setup.exe`, 35,897,214 bytes |
| Installer SHA-256 | `1c06d46d1e3654010de0d7fe4b5a5d3c6f88d12b92f333f419ed521883736327` |
| `BChat.exe` SHA-256 | `80291bbbacbc60ae7022b39fbb00edcc3403efc118fec2b5aeefd123afdd1fcc` |
| Packaged files | 209 |
| VirusTotal installer | 0 / 69 |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (full mode)

| Measure | 0.8.3 |
| --- | --- |
| Start to window | 0.53 s |
| Start to joined (15 channels) | 1.6 s (by design, as 0.8.2) |
| Idle working set | 106.1 MB |
| Load 300 msg/s: CPU / worst UI stall | 54.7 % / 51 ms |
| Burst of 5000 messages: time / worst UI stall | 4.3 s / 48 ms |
| History 10k lines / all 15 tabs full | 172.3 / 293.8 MB |

### Test results

pytest 708 (+5 `test_083`) all passed, protocol PASS; release build: build-check, secret scan, packaged 5/5,
ui 731 controls no problems, perf PASS. A fake-ZNC socket check (bouncer replays channels, server answers 405)
kept every tab full. The user confirmed 0.8.3-TEST1 works on Wixchat through ZNC.

## Previous baseline: 0.8.2 release (18 Nov 2026)

Released as `v0.8.2` from commit `85418c3` (connect and disconnect fixes `ba3d5b8`: joins wait 1 s after the
welcome text and optionally for the NickServ login, 5 s reconnects with numbered tries, no reconnect after a KILL,
ban retries every 60 s, server time-out setting). Numbers from QA run `20261118-044537` on the release build
(`build-check audit packaged ui perf`, full perf mode); the source stages ran on the same code for 0.8.2-TEST1
(runs `20261118-041745`, `20261118-043544`).

| Item | Value |
| --- | --- |
| Version string | `0.8.2` (`version_info` 0.8.2.0) |
| Installer | `BChat-0.8.2-setup.exe`, 35,900,121 bytes |
| Installer SHA-256 | `42e87abab6d1b4c8c329a3cede187558660dea7b09bf6cb0730f5ff72a225c1e` |
| `BChat.exe` SHA-256 | `ec941ce3e9b92ff066920cb84e1c86219542a688ca3f28badfd3a4971b0466e4` |
| Packaged files | 209 |
| VirusTotal installer | 0 / 69 |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (full mode)

| Measure | 0.8.2 |
| --- | --- |
| Start to window | 0.52 s |
| Start to joined (15 channels) | 1.6 s (by design: joins wait 1 s after the welcome text; 0.7 s before) |
| Idle working set | 105.9 MB |
| Load 300 msg/s: CPU / worst UI stall | 54.4 % / 46 ms |
| Burst of 5000 messages: time / worst UI stall | 5.2 s / 49 ms |
| History 10k lines / all 15 tabs full | 173.2 / 296.3 MB |

### Test results

pytest 703 (+21 `test_082`) all passed, protocol PASS (TEST1 runs); release build: build-check, secret scan,
packaged 5/5, ui 731 controls no problems, perf 13/13 PASS. Live run against a local server through a fault
proxy (drop, silence, K-line, KILL, `-s`) behaved as designed. The user confirmed 0.8.2-TEST1 works.

## Previous baseline: 0.8.1 release (17 Nov 2026)

Released as `v0.8.1` from commit `3607ca7` (bug fix: ZNC ghost channel after a server restart, `3d1bf3a`).
Numbers from QA run `20261117-070952` (`tools/qa.py all`, full perf mode, not quick: perf times are not
directly comparable with 0.8.0's quick-mode numbers).

| Item | Value |
| --- | --- |
| Version string | `0.8.1` (`version_info` 0.8.1.0) |
| Installer | `BChat-0.8.1-setup.exe`, 35,897,244 bytes |
| Installer SHA-256 | `19af4b37e03cef9b301bfaec7143b0369715776982bd8e0c4508043b13785720` |
| `BChat.exe` SHA-256 | `2dcea3c9d518dc39e7dd19934c815a89288c63e274c0e2c984243bdb40cce53c` |
| Packaged files | 209 |
| VirusTotal installer | 1 / 68 (DeepInstinct) |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (full mode, full QA run)

| Measure | 0.8.1 |
| --- | --- |
| Start to window | 0.54 s |
| Idle working set | 106.2 MB |
| Load 300 msg/s: CPU / worst UI stall | 60.3 % / 54 ms |
| Burst of 5000 messages: time / worst UI stall | 5.4 s / 47 ms |
| History 10k lines / all 15 tabs full | 173.3 / 296.3 MB |

### Test results

pytest 682 (+7 `test_081`), 681 passed + 1 known flaky (`test_040::test_skip_motd_and_motd_command`, listed in
`known-flaky.json`; passed alone 3/3), protocol PASS, packaged 5/5 PASS, ui 728 controls no problems, perf PASS.
The user confirmed the fix on 0.8.1-TEST1 (ghost channel gone).

## Previous baseline: 0.8.0 release (16 Nov 2026)

Released as `v0.8.0` from commit `84dcbba` (Popups for five menus + Paste mIRC popups, Scripts window, mIRC events,
add_menu_item and pluginprefs for scripts). Numbers from QA run `20261116-003730` (`tools/qa.py all --perf-quick`).

| Item | Value |
| --- | --- |
| Version string | `0.8.0` (`version_info` 0.8.0.0) |
| Installer | `BChat-0.8.0-setup.exe`, 35,892,198 bytes |
| Installer SHA-256 | `328fba334c91936f8d2f91d41b726b62d1bc024f06b47e25f57b396af367e5ab` |
| `BChat.exe` SHA-256 | `532337bb1cea735ae451e3d9f9127810c80ddc2bbce613c688e6c4daca0675d2` |
| Packaged files | 209 |
| VirusTotal installer | 1 / 71 (DeepInstinct) |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (quick mode, full QA run)

| Measure | 0.8.0 |
| --- | --- |
| Start to window | 0.53 s |
| Idle working set | 103.9 MB |
| Load 300 msg/s: CPU / worst UI stall | 54.4 % / 39 ms |
| Burst of 5000 messages: time / worst UI stall | 3.5 s / 42 ms |
| History 10k lines / all 15 tabs full | 149.7 / 259.4 MB |

### Test results

pytest 675 (+12 `test_080`), protocol PASS, packaged 5/5 PASS, ui 728 controls no problems (+55: Popups pages,
Paste mIRC popups, Scripts window), perf PASS. The first 0.8.0-TEST1 build failed 3 packaged checks: their probe
scripts use `from bchat import ...`, which the new `import bchat` API hid; fixed in `fa4e3eb` before release.

## Previous baseline: 0.7.0 release (15 Nov 2026)

Released as `v0.7.0` from commit `e9a35dc` (Everyday commands: 31 commands, Do not disturb, strip colours per
tab). Numbers from QA run `20261115-221738` (`tools/qa.py all --perf-quick`) and the re-check of the rebuilt
installer `20261115-223506`.

| Item | Value |
| --- | --- |
| Version string | `0.7.0` (`version_info` 0.7.0.0) |
| Installer | `BChat-0.7.0-setup.exe`, 35,851,308 bytes |
| Installer SHA-256 | `2cd6f53e9a24ec510233308b2cf8b5ad3b94816b89d478f6bf6ff6fd58e5637a` |
| `BChat.exe` SHA-256 | `9b64b930c87f16d0512f10c6cba18af5da51dc8c9c534fee1178190de97d84bf` |
| Packaged files | 209 |
| VirusTotal installer | 1 / 71 (DeepInstinct). The first build of the same commit was 2 / 68 (Microsoft `Wacatac.B!ml` + DeepInstinct); rebuilt, same `BChat.exe` |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (quick mode, full QA run)

| Measure | 0.7.0 |
| --- | --- |
| Start to window | 0.52 s |
| Idle working set | 105.6 MB |
| Load 300 msg/s: CPU / worst UI stall | 48.5 % / 29 ms |
| Burst of 5000 messages: time / worst UI stall | 3.1 s / 38 ms |
| History 10k lines / all 15 tabs full | 151.6 / 261.5 MB |

Against 0.6.4 the same day (TEST1, busy PC, two rounds): load CPU 51 / 58 % vs 59 / 71 %, burst and memory the same.

### Test results

pytest 663 (+13 `test_070`), protocol PASS, packaged 5/5 PASS in the full run, ui 673 controls no problems, perf PASS.
Timing flakes seen in packaged checks today (each 19/19 or 59/59 when re-run alone): `frozen_check` status strip
and `/server`, `frozen_extra` sent channel/private message (checked without waiting).

## Earlier release: 0.6.4 (15 Nov 2026)

Released as `v0.6.4` from commit `b957848`. Numbers from QA run `20261115-210636`
(`tools/qa.py all --perf-quick`) and a same-day comparison with 0.6.3 on an idle PC
(`perf_bench.py --quick`, two rounds each).

| Item | Value |
| --- | --- |
| Version string | `0.6.4` (`version_info` 0.6.4.0) |
| Installer | `BChat-0.6.4-setup.exe`, 35,825,872 bytes |
| Installer SHA-256 | `dbe15df5cbfc0acb38d2028fba1772aa81d83a57c7b9b563643bbb141dc1c15f` |
| `BChat.exe` SHA-256 | `09ef000d3f32b7ff3e12c076dfff33d2aada004ea277b7f4c30eba8c60154c05` |
| Packaged files | 209 (the spec now leaves out `api-ms-win-*` and `ucrtbase.dll`: a JDK on PATH had added 44) |
| VirusTotal installer | 1 / 71 (DeepInstinct, as on earlier builds) |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (quick mode, idle PC, same day)

| Measure | 0.6.4 | 0.6.3 |
| --- | --- | --- |
| Load 300 msg/s: CPU (two rounds) | 37.8 / 45.9 % | 45.4 / 45.8 % |
| Load: worst UI stall | 31 / 43 ms | 39 / 29 ms |
| Burst of 5000 messages | 3.2 / 5.1 s (second round noisy) | 3.1 / 3.2 s |

Full QA run: idle 106.1 MB, load 39.5 % CPU / 44 ms, burst 4.1 s / 102 ms, history 10k 152.8 MB.

### Test results

pytest 650, protocol PASS, packaged 5/5 PASS (`frozen_check` failed 2 status-strip timing checks in the
full run; 19/19 twice when re-run alone on the same exe), ui PASS, perf PASS.

## Previous baseline: 0.6.3 release (15 Nov 2026)

Released as `v0.6.3` from commit `7b0ac79`. Numbers from QA run `20261115-150057`
(`tools/qa.py all`), the installer re-check `20261115-152449` and a same-day perf comparison
(`perf_bench.py --quick`, 0.6.2 built from its tag on the same PC, one run each).

| Item | Value |
| --- | --- |
| Version string | `0.6.3` (`version_info` 0.6.3.0) |
| Installer | `BChat-0.6.3-setup.exe`, 35,822,826 bytes |
| Installer SHA-256 | `ee824df86a69be162821b022738de980fee4972bb2cb4c79a47916bd7a2fa063` |
| `BChat.exe` SHA-256 | `718d1d61b6d65072842f5142e10837869685536311577a4b1a32555ecd8658b4` |
| VirusTotal installer | 0 / 70 (the first build of the same commit: 2 / 70, Microsoft `Wacatac.C!ml` + DeepInstinct; rebuilt, same `BChat.exe`) |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (quick mode, same PC, same day)

| Measure | 0.6.3 | 0.6.2 |
| --- | --- | --- |
| Idle working set | 108.0 MB | 105.9 MB |
| Load 300 msg/s: CPU / worst UI stall | 60 % / 43 ms | 50 % / 46 ms |
| Burst of 5000 messages: time / worst UI stall | 4.0 s / 60 ms | 3.9 s / 50 ms |
| History 10k lines / all 15 tabs full | 153.9 / 267.3 MB | 151.4 / 263.6 MB |
| Tab switch, 5000-line tabs (real screen) | 27 ms avg | 110 ms avg |

The full QA run's own perf numbers (filled 300.8 MB, burst 4.4 s) were higher than the 0.6.2 baseline
for both versions that day: the same-day comparison above is the fair one. One chat view per tab costs
CPU when many hidden tabs are busy (load 50 -> 60 %); fixed after the release (hidden views skip the
scroll work), not in 0.6.3.

### Test results

pytest 649 (1 known flaky: `test_040` skip_motd), protocol PASS, packaged 5/5 PASS, ui PASS, perf 13/13.

## Previous baseline: 0.6.2 release (14 Nov 2026)

Released as `v0.6.2` from commit `ab80c2d`. Numbers from QA run `20261114-065639`
(`tools/qa.py all --perf-quick`, one run) and the release checks.

| Item | Value |
| --- | --- |
| Version string | `0.6.2` (`version_info` 0.6.2.0) |
| Installer | `BChat-0.6.2-setup.exe`, 35,820,924 bytes |
| Installer SHA-256 | `26305621a34f35e1ffe0dcb5e4e9d6282a695db0b0b1f4529def635254759069` |
| `BChat.exe` SHA-256 | `75d296612d711bae94620d32538e302d651fad96e5298728cf511e10f4209784` |
| VirusTotal installer | 0 / 69 |
| VirusTotal `BChat.exe` | 1 / 71 (APEX, as on every build) |

### Performance (quick mode, one run)

| Measure | 0.6.2 | 0.6.1 |
| --- | --- | --- |
| Start to visible main window / joined | 0.63 s / 0.71 s | 0.64 s / 0.73 s |
| Idle, 3 networks: CPU / working set | 1.5 % / 108.4 MB | 1.6 % / 108.4 MB |
| Load 300 msg/s: CPU / working set | 48 % / 117.2 MB | 58 % / 117.4 MB |
| Load: marker latency / worst UI stall | 5 ms / 32 ms | 6 ms / 40 ms |
| Burst of 5000 messages: time / worst UI stall | 3.1 s / 61 ms | 7.5 s / 243 ms (re-run alone: 7.3 s / 52 ms) |
| History 10k to 20k lines | 154.6 to 160.6 MB | 137.8 to 138.3 MB |
| All 15 tabs full / soak growth | 264.7 MB / 0.0 MB/min | 245.3 MB / 0.0 MB/min |

BR-4: a full tab no longer drops one line per new line (Qt laid the whole tab out again each time);
old lines go in batches when a tab is 10 % over Scrollback. That is why the burst is more than twice
as fast and the load CPU lower. The price is memory: a tab can hold up to 10 % more lines between
batches, so full tabs and long history use about 15-20 MB more. Soak growth stays 0.

### Test results

| Check | Result |
| --- | --- |
| `pytest` (source) | 642/642 passed (+3 BR-4 tests) |
| Protocol | 88/88 |
| `build_check.py` / packaged checks | PASS / bundle, frozen_check, frozen_features, frozen_reports, frozen_extra all PASS |
| Button check | 673 controls, no problems |
| Secret scan | PASS |
| Release | tag `v0.6.2` = `ab80c2d`, latest, anonymous download hash = build, signed manifest OK, updater offers 0.6.2 to 0.3.0 / 0.5.0 / 0.6.1 / 0.6.2-TEST1 and nothing to 0.6.2 |

## Previous baseline: 0.6.1 release (12 Nov 2026)

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
