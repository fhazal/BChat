"""Build check: is this build what it claims to be, and did the build finish cleanly?

packaging/version_info.txt = exe version resource = expected version; the installer for that version exists
and is newer than the exe; PyInstaller log has no ERROR/WARNING lines; Inno Setup reported a successful compile.
Records sizes and SHA-256 of exe and installer and the hash of the freeze recipe (build configuration).

    python tools/qa/build_check.py [--exe dist/BChat/BChat.exe] [--installer X] [--pyi-log X] [--iscc-log X]

Defaults follow build/build-test.sh: dist/BChat-<version>-setup.exe, build/pyi-<version>.log,
build/iscc-<version>.log. A log or installer that isn't there is reported as SKIP with the reason (never OK).
"""
import re
from pathlib import Path

from qa_common import ROOT, exe_version, finish, parse_args, sha256


def _extra(ap):
    ap.add_argument("--installer", default="")
    ap.add_argument("--pyi-log", default="")
    ap.add_argument("--iscc-log", default="")
    ap.add_argument("--spec", default=str(ROOT / "packaging" / "BChat.spec"))


ARGS = parse_args(__doc__.splitlines()[0], _extra)
ver = exe_version(ARGS.exe)
res, skips, info = {}, {}, {}


def skip(name, why):
    res[name] = None
    skips[name] = why


# version in three places
vi = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
m = re.search(r"StringStruct\('ProductVersion',\s*'([^']+)'\)", vi)
vi_ver = m.group(1) if m else ""
res["exe has a version resource"] = bool(ver)
res[f"exe version {ver!r} = expected {ARGS.expect!r}"] = bool(ver) and ver == ARGS.expect
if Path(ARGS.exe).is_relative_to(ROOT / "dist"):
    res[f"packaging/version_info.txt says the same ({vi_ver!r})"] = vi_ver == ver
else:
    skip("packaging/version_info.txt says the same", "exe is not the dist/ build (experimental builds may differ)")

# installer
inst = Path(ARGS.installer) if ARGS.installer else ROOT / "dist" / f"BChat-{ver}-setup.exe"
if inst.exists():
    res["installer exists"] = True
    res["installer is newer than the exe"] = inst.stat().st_mtime >= Path(ARGS.exe).stat().st_mtime - 1
    info["installer"] = str(inst)
    info["installer bytes"] = inst.stat().st_size
    info["installer sha256"] = sha256(inst)
else:
    skip("installer exists", f"not found: {inst}")

# build logs
pyi = Path(ARGS.pyi_log) if ARGS.pyi_log else ROOT / "build" / f"pyi-{ver}.log"
if pyi.exists():
    bad = [ln.strip()[:160] for ln in pyi.read_text(encoding="utf-8", errors="replace").splitlines()
           if re.search(r"\b(ERROR|WARNING):", ln)]
    res["PyInstaller log has no ERROR/WARNING lines"] = not bad
    if bad:
        info["PyInstaller problems"] = bad[:10]
    res["PyInstaller log belongs to this build (within 10 min of the exe)"] = abs(pyi.stat().st_mtime - Path(ARGS.exe).stat().st_mtime) <= 600
else:
    skip("PyInstaller log has no ERROR/WARNING lines", f"not found: {pyi}")
iscc = Path(ARGS.iscc_log) if ARGS.iscc_log else ROOT / "build" / f"iscc-{ver}.log"
if iscc.exists():
    res["Inno Setup log says 'Successful compile'"] = "Successful compile" in iscc.read_text(encoding="utf-8", errors="replace")
else:
    skip("Inno Setup log says 'Successful compile'", f"not found: {iscc}")

# build configuration (recorded, not judged)
spec = Path(ARGS.spec)
info["freeze recipe"] = str(spec) if spec.exists() else f"not found: {spec}"
if spec.exists():
    info["freeze recipe sha256"] = sha256(spec)
info["exe bytes"] = Path(ARGS.exe).stat().st_size
info["version_info.txt ProductVersion"] = vi_ver
res.update(info)
finish("build_check", ARGS, res, skips)
