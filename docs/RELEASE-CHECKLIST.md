# BChat release checklist

Copy this list into the release notes draft (or the QA report) for every release and tick it
off with real results. A box is only ticked with evidence: a command output, a hash, a number.
Test builds (`0.x.y-TESTn`) use sections 1-6; releases use all of it.

Release: `0.x.y` · Commit: `<sha>` · Date: `<yyyy-mm-dd>`

## 1. Source and automated tests

- [ ] Working tree clean except the version files; the commit to be released is known.
- [ ] `python -m pytest -q`: all pass (count: ___). Known-flaky failures re-run alone and pass.
- [ ] `full_button_check.py`: no problems (controls: ___).
- [ ] New features and fixed bugs each have tests (list them).
- [ ] `secret_scan.py` on what will be committed: clean.
- [ ] Before the repository is made public or history rewritten: `history_scan.py` clean.

## 2. Build

- [ ] `packaging/version_info.txt` and the build script both say `0.x.y`.
- [ ] Build from the release commit; PyInstaller and Inno Setup logs have no errors.
- [ ] SHA-256 and size of `dist/BChat-0.x.y-setup.exe`: ___
- [ ] SHA-256 of `dist/BChat/BChat.exe`: ___

## 3. Packaged application

- [ ] `tools/qa/`: `bundle_check.py` 23/23, `frozen_check.py` 19/19, `frozen_features.py` 60/60,
      `frozen_reports.py` 19/19, `frozen_extra.py` 59/59 (expected version = `0.x.y`).
- [ ] The exe reports the right version (About window, `full_version()`).
- [ ] For packaging changes: file list and loaded DLLs compared with the previous build;
      differences explained.

## 4. Functional testing

- [ ] Automated IRC integration (fake server): connect, TLS, SASL, CAP, messages, reconnect.
- [ ] New features of this release exercised in the packaged app.
- [ ] Owner's manual test on real servers done and reported OK (date: ___).

## 5. Security

- [ ] VirusTotal: installer ___ / ___, `BChat.exe` ___ / ___ (engines that flag, by name).
      Detections are judged and documented; a new detection on the installer blocks the
      release until it is cleared or the owner decides.
- [ ] No new network destinations, no `subprocess`, no obfuscation in the diff (honesty review).
- [ ] Passwords still only in Credential Manager (vault tests pass); problem reports only on Send.

## 6. Dependencies and installer

- [ ] Dependency versions recorded (Python, PySide6, PyInstaller, cryptography,
      pyspellchecker, winrt); any change explained.
- [ ] No new dependency without the owner's OK.
- [ ] Installer size ___ MB, installed size ___ MB, compared with QA-BASELINE.md.
- [ ] Installer runs per user, the uninstaller removes the program, settings stay.
- [ ] Update from the previous release offered and installed (owner's PC or a test PC).

## 7. Performance

- [ ] Start to window, start to joined, idle RAM, idle CPU measured (5 runs, medians) and
      compared with QA-BASELINE.md. Changes over ~10 % explained.

## 8. Release approval and publishing

- [ ] **Owner's explicit approval to release** (quote it, with date).
- [ ] Release notes written (`dist/release-notes-0.x.y.md`), including the VirusTotal result.
- [ ] Manifest signed: `make_manifest.py dist/BChat-0.x.y-setup.exe 0.x.y <url> ...`;
      signature checks out, tampered copy refused.
- [ ] `git push`, then `gh release create v0.x.y` with the installer and `bchat-update.json`.
- [ ] Checked after publishing: `tag_name` is `v0.x.y`, not draft or pre-release, anonymous
      "latest" is this release, anonymous download SHA-256 equals the built one, the updater
      offers it to the previous versions and not to itself.
- [ ] Release posts (IRC, forum, download page, Discord) went out.
- [ ] QA-BASELINE.md updated with this release as the new known-good baseline.
