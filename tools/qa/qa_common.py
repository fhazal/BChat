"""Shared bits for the QA tools: the same command line, the exe's own version, one JSON result per tool.

Every tool in tools/qa runs on its own (python tools/qa/<tool>.py --help). Result values:
True = pass, False = fail, None = skipped (with a reason under "skips"), anything else = information.
Exit code 0 only when nothing failed.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "dist" / "BChat" / "BChat.exe"


def exe_version(exe: str | os.PathLike) -> str:
    """ProductVersion from the exe's version resource (what packaging/version_info.txt put there)."""
    v = ctypes.windll.version
    size = v.GetFileVersionInfoSizeW(str(exe), None)
    if not size:
        return ""
    buf = ctypes.create_string_buffer(size)
    if not v.GetFileVersionInfoW(str(exe), 0, size, buf):
        return ""
    trans, n = ctypes.c_void_p(), ctypes.c_uint()
    if not v.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(trans), ctypes.byref(n)) or not n.value:
        return ""
    lang = ctypes.cast(trans, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    val, n2 = ctypes.c_wchar_p(), ctypes.c_uint()
    key = rf"\StringFileInfo\{lang[0]:04x}{lang[1]:04x}\ProductVersion"
    if not v.VerQueryValueW(buf, key, ctypes.byref(val), ctypes.byref(n2)):
        return ""
    return val.value or ""


def sha256(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def parse_args(description: str, extra=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--exe", default=str(DEFAULT_EXE), help="the built BChat.exe to check (default: dist/BChat/BChat.exe)")
    ap.add_argument("--out", default="", help="folder for the JSON result, screenshots and logs (default: a new temp folder)")
    ap.add_argument("--expect", default="", help="version the exe must report (default: the exe's own version resource)")
    if extra:
        extra(ap)
    a = ap.parse_args()
    a.exe = str(Path(a.exe).resolve())
    if not Path(a.exe).exists():
        ap.error(f"no such exe: {a.exe}")
    a.out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="bchat-qa-"))
    a.out.mkdir(parents=True, exist_ok=True)
    a.expect = a.expect or os.environ.get("BCHAT_EXPECT", "") or exe_version(a.exe)
    a.started = time.time()
    return a


def finish(tool: str, args: argparse.Namespace, results: dict, skips: dict | None = None, extra: dict | None = None) -> None:
    """Print the results the same way every tool does, write <out>/<tool>.json, exit 0 / 1."""
    skips = skips or {}
    ok = sum(1 for v in results.values() if v is True)
    fail = [k for k, v in results.items() if v is False]
    skipped = [k for k, v in results.items() if v is None]
    for k, v in results.items():
        if v is True:
            print("OK  ", k)
        elif v is False:
            print("FAIL", k)
        elif v is None:
            print("SKIP", k, "-", skips.get(k, ""))
        else:
            print("    ", k, ":", str(v)[:300])
    print(f"--- {ok} OK, {len(fail)} FAIL, {len(skipped)} SKIP")
    doc = {"tool": tool, "exe": args.exe, "exe_sha256": sha256(args.exe), "exe_version": exe_version(args.exe),
           "expect": args.expect, "python": platform.python_version(), "windows": platform.platform(),
           "seconds": round(time.time() - args.started, 1), "ok": ok, "fail": len(fail), "skip": len(skipped),
           "failed": fail, "skipped": {k: skips.get(k, "") for k in skipped}, "results": results}
    doc.update(extra or {})
    (args.out / f"{tool}.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    print("result:", args.out / f"{tool}.json")
    sys.exit(1 if fail else 0)


def wait(cond, sec: float = 30, step: float = 0.1) -> bool:
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def self_signed_cert(folder: Path, cn: str = "fake") -> tuple[str, str]:
    """A throwaway certificate + key for a local TLS test server (cryptography, no openssl.exe needed)."""
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(hours=1))
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    crt, k = folder / "c.pem", folder / "k.pem"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    return str(crt), str(k)


def process_modules(pid: int) -> list[str]:
    """File names of every DLL/module loaded in a running process (PowerShell, no extra packages)."""
    import subprocess
    ps = f"(Get-Process -Id {pid}).Modules | ForEach-Object {{ $_.FileName }}"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return sorted({Path(x.strip()).name for x in r.stdout.splitlines() if x.strip()}, key=str.lower)


def process_memory_cpu(pid: int) -> tuple[int, int, float]:
    """(working set bytes, private bytes, total CPU seconds) of a running process."""
    import subprocess
    ps = f"$p=Get-Process -Id {pid}; '{{0}} {{1}} {{2}}' -f $p.WorkingSet64, $p.PrivateMemorySize64, $p.TotalProcessorTime.TotalSeconds"
    a, b, c = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split()
    return int(a), int(b), float(c.replace(",", "."))
