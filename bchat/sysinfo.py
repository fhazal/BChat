"""/sysinfo: one line about this PC, like AdiIRC's. Read straight from Windows (registry and system calls).
Never the IP address, PC name or Windows user name."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import string
import sys

DEFAULT_LINE = "OS {os} · CPU {cpu} · RAM {ram} · Disks {disks} · GPU {gpu} · Uptime {uptime} · BChat {bchat}"
WORDS = ("os", "cpu", "cores", "ram", "disks", "gpu", "uptime", "bchat")


def _reg(path: str, name: str, root=None):
    import winreg
    try:
        with winreg.OpenKey(root or winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _size(nbytes: float) -> str:
    gb = nbytes / 1024 ** 3
    if gb >= 1000:
        return f"{gb / 1024:.2f} TB"
    return f"{gb:.1f} GB" if gb < 100 else f"{gb:.0f} GB"


def os_text() -> str:
    cv = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    name = _reg(cv, "ProductName") or "Windows"
    build = str(_reg(cv, "CurrentBuild") or "")
    if build.isdigit() and int(build) >= 22000:
        name = name.replace("Windows 10", "Windows 11")      # Windows 11 still says 10 in ProductName
    bits = "64-bit" if sys.maxsize > 2 ** 32 or "64" in (_reg(r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "PROCESSOR_ARCHITECTURE") or "") else "32-bit"
    return f"{name} {bits}" + (f" ({build})" if build else "")


def physical_cores() -> int:
    """GetLogicalProcessorInformation: entries with Relationship 0 (RelationProcessorCore) are cores."""
    k = ctypes.windll.kernel32
    size = wt.DWORD(0)
    k.GetLogicalProcessorInformation(None, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not k.GetLogicalProcessorInformation(buf, ctypes.byref(size)):
        return 0
    entry = 32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24     # SYSTEM_LOGICAL_PROCESSOR_INFORMATION
    rel_at = ctypes.sizeof(ctypes.c_void_p)
    return sum(1 for off in range(0, size.value, entry) if buf.raw[off + rel_at] == 0)


def cpu_text() -> str:
    key = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    name = " ".join(str(_reg(key, "ProcessorNameString") or "Unknown CPU").split())
    name = re.sub(r"\s*\d+-Core Processor$", "", name)
    mhz = _reg(key, "~MHz")
    import os
    threads = os.cpu_count() or 0
    try:
        cores = physical_cores()
    except (OSError, AttributeError):
        cores = 0
    parts = [name]
    if cores and threads:
        parts.append(f"{cores} cores / {threads} threads" if cores != threads else f"{cores} cores")
    out = ", ".join(parts)
    return out + (f" @ {mhz / 1000:.1f} GHz" if isinstance(mhz, int) and mhz > 0 else "")


def cores_text() -> str:
    import os
    try:
        return str(physical_cores() or os.cpu_count() or "?")
    except (OSError, AttributeError):
        return str(os.cpu_count() or "?")


class _Mem(ctypes.Structure):
    _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ram_text() -> str:
    m = _Mem()
    m.dwLength = ctypes.sizeof(_Mem)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return "?"
    return f"{_size(m.ullAvailPhys)} free of {_size(m.ullTotalPhys)}"


def disks_text() -> str:
    """Every fixed drive together, like AdiIRC: free of total."""
    import shutil
    k = ctypes.windll.kernel32
    mask = k.GetLogicalDrives()
    total = free = 0
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i) and k.GetDriveTypeW(f"{letter}:\\") == 3:      # DRIVE_FIXED
            try:
                u = shutil.disk_usage(f"{letter}:\\")
            except OSError:
                continue
            total += u.total
            free += u.free
    return f"{_size(free)} free of {_size(total)}" if total else "?"


def gpu_text() -> str:
    """The display adapters Windows lists, with their memory where the driver says it."""
    import winreg
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                desc = _reg(base + "\\" + sub, "DriverDesc")
                if not desc or "basic display" in desc.lower() or "remote" in desc.lower() or "virtual" in desc.lower():
                    continue
                mem = _reg(base + "\\" + sub, "HardwareInformation.qwMemorySize")
                if isinstance(mem, bytes):
                    mem = int.from_bytes(mem[:8], "little")
                text = desc + (f", {round(mem / 1024 ** 3)} GB" if isinstance(mem, int) and mem >= 1024 ** 3 else "")
                if text not in found:
                    found.append(text)
    except OSError:
        pass
    return " + ".join(found) or "?"


def uptime_text() -> str:
    ms = ctypes.windll.kernel32.GetTickCount64
    ms.restype = ctypes.c_ulonglong
    s = ms() // 1000
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return (f"{d}d " if d else "") + f"{h}h {m}m"


def collect(version: str) -> dict:
    out = {"bchat": version}
    for key, fn in (("os", os_text), ("cpu", cpu_text), ("cores", cores_text), ("ram", ram_text), ("disks", disks_text),
                    ("gpu", gpu_text), ("uptime", uptime_text)):
        try:
            out[key] = fn()
        except Exception:          # one odd part must never stop the line
            out[key] = "?"
    return out


def render(template: str, info: dict) -> str:
    """Fill the words in. Labels before a word turn bold, the dots grey, and the BChat part goes quiet."""
    line = (template or DEFAULT_LINE).strip()
    line = re.sub(r"BChat \{bchat\}", "\x0314BChat {bchat}\x03", line)
    line = re.sub(r"(?<![\w\x02])([A-Za-z][\w/]*) \{(" + "|".join(WORDS) + r")\}", "\x02\\1\x02 {\\2}", line)
    line = line.replace(" · ", " \x0314·\x03 ")
    return re.sub(r"\{(\w+)\}", lambda m: str(info.get(m.group(1), m.group(0))), line)
