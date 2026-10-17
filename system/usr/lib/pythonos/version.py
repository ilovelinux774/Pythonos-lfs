"""Version strings shared by the boot splash, MOTD and tools."""

from . import __codename__, __version__


def banner_subtitle():
    return f"version {__version__}  ·  codename \"{__codename__}\"  ·  Alpine/OpenRC with a Python userland"


def short_version():
    return f"{__version__} ({__codename__})"
