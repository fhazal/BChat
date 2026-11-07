__version__ = "0.1.0"


def full_version() -> str:
    """The version this build calls itself, TEST number included (assets/version.txt, written at build time).
    Running from source it's plain __version__."""
    from pathlib import Path
    try:
        v = (Path(__file__).parent / "assets" / "version.txt").read_text(encoding="utf-8").strip()
        return v or __version__
    except OSError:
        return __version__
