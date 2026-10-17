"""Host-platform services used by the portable desktop.

This module deliberately exposes a small, boring interface. The desktop and
its apps do not need to know whether they are running on Linux, Windows, or
macOS. A later native backend can implement the same contracts using Linux
services and devices inside the Alpine image.
"""

from __future__ import annotations

import datetime as _datetime
import os
import platform as _platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HostPaths:
    """The private, portable PythonOS home on the host."""

    root: Path
    files: Path
    apps: Path
    config: Path
    cache: Path

    @classmethod
    def create(cls) -> "HostPaths":
        override = os.environ.get("PYTHONOS_HOME")
        root = Path(override).expanduser() if override else Path.home() / ".pythonos"
        paths = cls(root=root, files=root / "files", apps=root / "apps",
                    config=root / "config", cache=root / "cache")
        for path in (paths.root, paths.files, paths.apps, paths.config, paths.cache):
            path.mkdir(parents=True, exist_ok=True)
        return paths


class HostPlatform:
    """Portable services for hosted mode.

    The default filesystem is a PythonOS-owned directory. It prevents an app
    written for the hosted desktop from assuming that the host has Linux's
    ``/proc`` or from accidentally treating the user's entire home as the
    PythonOS root.
    """

    def __init__(self) -> None:
        self.paths = HostPaths.create()
        self.cwd = self.paths.files

    @property
    def system(self) -> str:
        return _platform.system() or "Unknown"

    @property
    def release(self) -> str:
        return _platform.release()

    @property
    def python(self) -> str:
        return _platform.python_version()

    @property
    def machine(self) -> str:
        return _platform.machine() or "unknown"

    def display_name(self) -> str:
        return f"{self.system} {self.release} ({self.machine})"

    def now(self) -> str:
        return _datetime.datetime.now().strftime("%H:%M")

    def virtual_path(self, text: str | os.PathLike[str] = ".") -> Path:
        """Resolve a user path without allowing it outside the virtual home."""
        raw = str(text)
        if raw in ("", "."):
            candidate = self.cwd
        elif raw == "~" or raw.startswith("~/"):
            candidate = self.paths.files / raw[2:]
        else:
            path = Path(raw)
            candidate = path if path.is_absolute() else self.cwd / path
        candidate = candidate.resolve()
        root = self.paths.files.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("hosted mode keeps files inside ~/.pythonos/files")
        return candidate

    def list_files(self, path: str = ".") -> list[Path]:
        target = self.virtual_path(path)
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_dir():
            return [target]
        return sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))

    def disk_summary(self) -> tuple[str, str]:
        usage = shutil.disk_usage(self.paths.root)
        used = usage.total - usage.free
        def fmt(value: int) -> str:
            units = ("B", "KB", "MB", "GB", "TB")
            number = float(value)
            for unit in units:
                if number < 1024 or unit == units[-1]:
                    return f"{number:.1f} {unit}"
                number /= 1024
            return str(value)
        return fmt(used), fmt(usage.total)

    def info(self) -> dict[str, str]:
        used, total = self.disk_summary()
        return {
            "OS": self.display_name(),
            "Python": sys.version.split()[0],
            "Machine": self.machine,
            "PythonOS home": str(self.paths.root),
            "Storage": f"{used} / {total}",
        }
