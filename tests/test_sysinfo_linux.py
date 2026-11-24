"""/sysinfo on Linux: read from /etc/os-release, /proc and /sys. A fake tree stands in, so this runs anywhere."""
from __future__ import annotations

import os
import sys
from collections import namedtuple

import pytest

from bchat import sysinfo

CPUINFO = "".join(f"processor\t: {i}\nmodel name\t: AMD Ryzen 9 5950X 16-Core Processor\nphysical id\t: 0\n"
                  f"core id\t\t: {i % 16}\ncpu MHz\t\t: 2200.000\n\n" for i in range(32))
MOUNTS = """/dev/nvme0n1p2 / ext4 rw,relatime 0 0
/dev/nvme0n1p2 /var/snap ext4 rw 0 0
/dev/nvme0n1p1 /boot/efi vfat rw 0 0
/dev/sda1 /mnt/My\\040Games ntfs3 rw 0 0
/dev/loop3 /snap/core22/1 squashfs ro 0 0
tmpfs /run tmpfs rw 0 0
//nas/share /mnt/nas cifs rw 0 0
C:\134 /mnt/c 9p rw 0 0
"""
PCI_IDS = """# comment
10de  NVIDIA Corporation
\t2484  GA104 [GeForce RTX 3070]
\t\t1043 87b8  subsystem line
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t73bf  Navi 21 [Radeon RX 6800/6800 XT / 6900 XT]
8086  Intel Corporation
\t4680  AlderLake-S GT1
"""
SEEN: list[str] = []


def put(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def card(root, n, vendor, device, slot, vram=None):
    dev = root / "sys" / "devices" / "pci0000:00" / slot
    put(dev, "vendor", f"0x{vendor}\n")
    put(dev, "device", f"0x{device}\n")
    if vram:
        put(dev, "mem_info_vram_total", f"{vram}\n")
    link = root / "sys" / "class" / "drm" / f"card{n}"      # like the kernel: cardN/device -> the PCI slot folder
    link.mkdir(parents=True)
    try:
        (link / "device").symlink_to(dev, target_is_directory=True)
    except OSError:                       # Windows without symlink rights: a copy of the files does the same here
        (link / "device").mkdir()
        for f in dev.iterdir():
            (link / "device" / f.name).write_text(f.read_text())


@pytest.fixture
def tree(tmp_path, monkeypatch):
    put(tmp_path, "etc/os-release", 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\nVERSION_ID="24.04"\n')
    put(tmp_path, "proc/sys/kernel/osrelease", "6.8.0-49-generic\n")
    put(tmp_path, "proc/cpuinfo", CPUINFO)
    put(tmp_path, "sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "5083000\n")
    put(tmp_path, "proc/meminfo", "MemTotal:       32768000 kB\nMemFree:  1000 kB\nMemAvailable:   16384000 kB\n")
    put(tmp_path, "proc/uptime", "200000.55 1000.0\n")
    put(tmp_path, "proc/mounts", MOUNTS)
    put(tmp_path, "usr/share/misc/pci.ids", PCI_IDS)
    monkeypatch.setattr(sysinfo, "_ROOT", tmp_path)
    Usage = namedtuple("Usage", "total used free")
    sizes = {"/": (500, 200), "/boot/efi": (1, 1), "/mnt/My Games": (1000, 400)}
    SEEN.clear()

    def usage(mount):
        SEEN.append(mount)
        total, free = sizes[mount]
        return Usage(total * 1024 ** 3, (total - free) * 1024 ** 3, free * 1024 ** 3)
    monkeypatch.setattr(sysinfo, "_disk_usage", usage)
    return tmp_path


def test_os_cpu_ram_uptime(tree):
    assert sysinfo.linux_os_text() == "Ubuntu 24.04.1 LTS 64-bit (kernel 6.8.0)"
    assert sysinfo.linux_cpu_text() == "AMD Ryzen 9 5950X, 16 cores / 32 threads @ 5.1 GHz"
    assert sysinfo.linux_cores_text() == "16"
    assert sysinfo.linux_ram_text() == "15.6 GB free of 31.2 GB"
    assert sysinfo.linux_uptime_text() == "2d 7h 33m"


def test_cpu_without_core_ids_or_clock(tree):
    sysinfo_root = tree
    put(sysinfo_root, "proc/cpuinfo", "processor\t: 0\nHardware\t: BCM2835\n\nprocessor\t: 1\nHardware\t: BCM2835\n\n")
    (sysinfo_root / "sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq").unlink()
    assert sysinfo.linux_cpu_text() == "BCM2835, 2 threads"
    put(sysinfo_root, "sys/devices/system/cpu/cpu0/cpufreq/base_frequency", "3400000\n")
    assert sysinfo.linux_cpu_text() == "BCM2835, 2 threads @ 3.4 GHz"


def test_disks_count_each_real_disk_once(tree):
    # / and /var/snap are the same partition; snaps, tmpfs, network and Windows-shared drives don't count
    assert sysinfo.linux_disks_text() == "601 GB free of 1.47 TB"
    assert sorted(SEEN) == ["/", "/boot/efi", "/mnt/My Games"]


def test_size_never_says_under_one_tb():
    assert sysinfo._size(1003 * 1024 ** 3) == "1003 GB"
    assert sysinfo._size(2048 * 1024 ** 3) == "2.00 TB"
    assert sysinfo._size(50.25 * 1024 ** 3) == "50.2 GB"


LINUX_PATHS = pytest.mark.skipif(os.name == "nt", reason="PCI slot folders have colons, which Windows can't name")


@LINUX_PATHS
def test_gpu_names_from_pci_list(tree):
    card(tree, 0, "10de", "2484", "0000:01:00.0")
    card(tree, 1, "1002", "73bf", "0000:03:00.0", vram=16 * 1024 ** 3)
    card(tree, 2, "1af4", "1050", "0000:05:00.0")              # a virtual screen: left out
    (tree / "sys/class/drm/card0-DP-1").mkdir()                 # a connector, not a card
    assert sysinfo.linux_gpu_text() == "NVIDIA GeForce RTX 3070 + AMD Radeon RX 6800/6800 XT / 6900 XT, 16 GB"


@LINUX_PATHS
def test_gpu_nvidia_driver_name_and_no_list(tree):
    (tree / "usr/share/misc/pci.ids").unlink()
    card(tree, 0, "8086", "4680", "0000:00:02.0")
    assert sysinfo.linux_gpu_text() == "Intel graphics"
    card(tree, 1, "10de", "2484", "0000:01:00.0")
    put(tree, "proc/driver/nvidia/gpus/0000:01:00.0/information", "Model: \t\t NVIDIA GeForce RTX 3070\nIRQ: 1\n")
    assert sysinfo.linux_gpu_text() == "Intel graphics + NVIDIA GeForce RTX 3070"


def test_nothing_readable_gives_question_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(sysinfo, "_ROOT", tmp_path)
    assert sysinfo.linux_os_text() == "Linux 64-bit"
    assert sysinfo.linux_cpu_text() == "Unknown CPU"
    for fn in (sysinfo.linux_ram_text, sysinfo.linux_disks_text, sysinfo.linux_gpu_text, sysinfo.linux_uptime_text):
        assert fn() == "?"


def test_line_never_names_the_pc_or_user(tree):
    put(tree, "etc/hostname", "my-secret-box\n")
    line = sysinfo.render(sysinfo.DEFAULT_LINE, {k: f() for k, f in (
        ("os", sysinfo.linux_os_text), ("cpu", sysinfo.linux_cpu_text), ("ram", sysinfo.linux_ram_text),
        ("disks", sysinfo.linux_disks_text), ("gpu", sysinfo.linux_gpu_text), ("uptime", sysinfo.linux_uptime_text))}
        | {"bchat": "0.9.0"})
    assert "my-secret-box" not in line
    for word in filter(None, (os.environ.get("USER"), os.environ.get("USERNAME"))):
        assert word not in line


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the real /proc")
def test_this_linux_pc():
    info = sysinfo.collect("0.9.0")
    assert info["os"] != "?" and "64-bit" in info["os"]
    assert info["cpu"] != "?" and info["ram"].endswith("GB") and info["uptime"] != "?"
    assert sysinfo.cpu_text is sysinfo.linux_cpu_text
