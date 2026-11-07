"""What counts as a program, shared by the link check and DCC, plus two file-name safety helpers. No Qt here."""
from __future__ import annotations

import os
import re

# things that run (or open something that runs) as soon as they're opened on Windows
PROGRAM_TYPES = {"exe", "msi", "msix", "msixbundle", "bat", "cmd", "com", "scr", "pif", "ps1", "psm1", "psd1", "vbs", "vbe",
                 "js", "jse", "wsf", "wsh", "hta", "jar", "lnk", "reg", "cpl", "dll", "appx", "appxbundle", "iso", "img",
                 "vhd", "vhdx", "application", "msc", "scf", "url", "chm", "gadget", "inf", "sys"}

# characters that change which way text runs: "photo‮gpj.exe" shows as "photoexe.jpg"
_BIDI = re.compile("[؜‎‏‪-‮⁦-⁩]")


def strip_bidi(name: str) -> str:
    return _BIDI.sub("", name)


def is_program(name: str) -> bool:
    """By the real last ending, after direction tricks are removed ("song.mp3.exe" is a program)."""
    name = strip_bidi(name).strip().rstrip(". ")
    return "." in name and name.rsplit(".", 1)[-1].lower() in PROGRAM_TYPES


def mark_from_internet(path: str, source: str = "") -> bool:
    """Windows' "downloaded from the internet" mark (the Zone.Identifier stream browsers add), so SmartScreen and
    Office check the file before it runs or opens. Only on Windows NTFS; elsewhere it quietly does nothing."""
    if os.name != "nt":
        return False
    text = "[ZoneTransfer]\r\nZoneId=3\r\n" + (f"HostUrl={source}\r\n" if source else "")
    try:
        with open(path + ":Zone.Identifier", "w", encoding="ascii", errors="replace") as f:
            f.write(text)
        return True
    except OSError:
        return False
