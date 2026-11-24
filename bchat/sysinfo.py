"""/sysinfo: one line about this PC, like AdiIRC's. Read straight from Windows (registry and system calls), or on
Linux from /etc/os-release, /proc and /sys. Never the IP address, PC name or user name."""
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
    if gb >= 1024:                        # 1003 GB stays "1003 GB", not "0.98 TB"
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


# --- Linux: /etc/os-release, /proc and /sys (0.9.0) ---------------------------------------------------------------
# Same words, same look. Read as plain files so a test can point _ROOT at a fake tree. Never the host or user name.

from pathlib import Path

_ROOT = Path("/")
_REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "jfs", "reiserfs", "zfs", "bcachefs", "vfat", "exfat",
            "ntfs", "ntfs3", "fuseblk"}
_GPU_VENDORS = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}
_VIRTUAL_GPU = {"1af4", "15ad", "1234", "1414", "80ee"}        # virtio, VMware, QEMU, Hyper-V, VirtualBox


def _text(rel: str) -> str:
    try:
        return (_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _fields(text: str, sep: str = ":") -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        key, s, value = line.partition(sep)
        if s:
            out.append((key.strip(), value.strip()))
    return out


def linux_os_text() -> str:
    info = dict(_fields(_text("etc/os-release"), "="))
    name = (info.get("PRETTY_NAME") or info.get("NAME") or "Linux").strip('"\'')
    bits = "64-bit" if sys.maxsize > 2 ** 32 else "32-bit"
    kernel = _text("proc/sys/kernel/osrelease").strip().split("-")[0]
    return f"{name} {bits}" + (f" (kernel {kernel})" if kernel else "")


def _cpu_entries() -> list[dict]:
    cpus, cur = [], {}
    for line in _text("proc/cpuinfo").splitlines() + [""]:
        if not line.strip():
            if cur:
                cpus.append(cur)
            cur = {}
            continue
        key, _, value = line.partition(":")
        cur[key.strip()] = value.strip()
    return cpus


def linux_physical_cores() -> int:
    """One core per (physical id, core id) pair; 0 when the kernel doesn't say (some VMs and ARM boards)."""
    pairs = {(c.get("physical id", "0"), c["core id"]) for c in _cpu_entries() if "core id" in c}
    return len(pairs)


def _linux_ghz() -> float:
    """The base clock where the kernel has it, else the top clock; the 'cpu MHz' of /proc/cpuinfo last (it moves)."""
    for rel in ("sys/devices/system/cpu/cpu0/cpufreq/base_frequency", "sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"):
        khz = _text(rel).strip()
        if khz.isdigit() and int(khz) > 0:
            return int(khz) / 1_000_000
    cpus = _cpu_entries()
    try:
        return float(cpus[0].get("cpu MHz", "0")) / 1000 if cpus else 0.0
    except ValueError:
        return 0.0


def linux_cpu_text() -> str:
    cpus = _cpu_entries()
    first = cpus[0] if cpus else {}
    name = " ".join((first.get("model name") or first.get("Hardware") or first.get("cpu model") or "Unknown CPU").split())
    name = re.sub(r"\s*\d+-Core Processor$", "", name)
    threads = sum(1 for c in cpus if "processor" in c) or len(cpus)
    cores = linux_physical_cores()
    parts = [name]
    if cores and threads:
        parts.append(f"{cores} cores / {threads} threads" if cores != threads else f"{cores} cores")
    elif threads:
        parts.append(f"{threads} threads")
    ghz = _linux_ghz()
    return ", ".join(parts) + (f" @ {ghz:.1f} GHz" if ghz > 0 else "")


def linux_cores_text() -> str:
    import os
    return str(linux_physical_cores() or os.cpu_count() or "?")


def linux_ram_text() -> str:
    mem = {k: v.split()[0] for k, v in _fields(_text("proc/meminfo")) if v}
    total, free = mem.get("MemTotal", ""), mem.get("MemAvailable", mem.get("MemFree", ""))
    if not total.isdigit() or not free.isdigit():
        return "?"
    return f"{_size(int(free) * 1024)} free of {_size(int(total) * 1024)}"


def _disk_usage(mount: str):
    import shutil
    return shutil.disk_usage(mount)


def linux_disks_text() -> str:
    """Every disk filesystem together, once each (the same disk is often mounted twice): free of total.
    Not snaps and other loop images, not RAM disks, not network or Windows-shared drives."""
    total = free = 0
    seen = set()
    for line in _text("proc/mounts").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mount, fs = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fs not in _REAL_FS or not dev.startswith("/dev/") or dev.startswith(("/dev/loop", "/dev/zram", "/dev/ram")):
            continue
        if dev in seen:
            continue
        try:
            u = _disk_usage(mount)
        except OSError:
            continue
        seen.add(dev)
        total += u.total
        free += u.free
    return f"{_size(free)} free of {_size(total)}" if total else "?"


def _pci_name(vendor: str, device: str) -> str:
    """The model from the system's PCI name list (pciutils/hwdata), "" when it isn't installed or doesn't know."""
    for rel in ("usr/share/hwdata/pci.ids", "usr/share/misc/pci.ids", "usr/share/pci.ids"):
        try:
            f = (_ROOT / rel).open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with f:
            inside = False
            for line in f:
                if not line.startswith("\t") and not line.startswith("#"):
                    if inside:
                        return ""
                    inside = line[:4].lower() == vendor
                elif inside and line.startswith("\t") and not line.startswith("\t\t") and line[1:5].lower() == device:
                    name = line[5:].strip()
                    m = re.search(r"\[(.+)\]", name)
                    return m.group(1) if m else name
        return ""
    return ""


def linux_gpu_text() -> str:
    """Graphics cards the kernel lists, named from the PCI list (the NVIDIA driver names its own), with memory where
    the driver says it."""
    found = []
    nv = {}
    try:
        for info in sorted((_ROOT / "proc/driver/nvidia/gpus").glob("*/information")):
            fields = dict(_fields(info.read_text(encoding="utf-8", errors="replace")))
            if fields.get("Model"):
                nv[info.parent.name.lower()] = fields["Model"]
    except OSError:
        pass
    try:
        cards = sorted(p for p in (_ROOT / "sys/class/drm").glob("card*") if re.fullmatch(r"card\d+", p.name))
    except OSError:
        cards = []
    for card in cards:
        dev = card / "device"
        vendor = _text(str((dev / "vendor").relative_to(_ROOT))).strip().lower().removeprefix("0x")
        device = _text(str((dev / "device").relative_to(_ROOT))).strip().lower().removeprefix("0x")
        if not vendor or vendor in _VIRTUAL_GPU:
            continue
        brand = _GPU_VENDORS.get(vendor, "")
        slot = ""
        try:
            slot = dev.resolve().name.lower()
        except OSError:
            pass
        name = nv.get(slot) or _pci_name(vendor, device)
        if name and brand and not name.lower().startswith(brand.lower()) and not (brand == "NVIDIA" and slot in nv):
            name = f"{brand} {name}"
        name = name or (f"{brand} graphics" if brand else "")
        if not name:
            continue
        vram = _text(str((dev / "mem_info_vram_total").relative_to(_ROOT))).strip()
        text = name + (f", {round(int(vram) / 1024 ** 3)} GB" if vram.isdigit() and int(vram) >= 1024 ** 3 else "")
        if text not in found:
            found.append(text)
    if not found:
        found = list(dict.fromkeys(nv.values()))
    return " + ".join(found) or "?"


def linux_uptime_text() -> str:
    try:
        s = int(float(_text("proc/uptime").split()[0]))
    except (IndexError, ValueError):
        return "?"
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return (f"{d}d " if d else "") + f"{h}h {m}m"


if sys.platform.startswith("linux"):
    os_text, physical_cores, cpu_text, cores_text = linux_os_text, linux_physical_cores, linux_cpu_text, linux_cores_text
    ram_text, disks_text, gpu_text, uptime_text = linux_ram_text, linux_disks_text, linux_gpu_text, linux_uptime_text


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
