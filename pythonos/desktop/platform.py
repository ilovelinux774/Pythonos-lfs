"""Host-platform services used by the portable desktop.

This module deliberately exposes a small, boring interface. The desktop and
its apps do not need to know whether they are running on Linux, Windows, or
macOS. A later native backend can implement the same contracts using Linux
services and devices inside the Alpine image.
"""

from __future__ import annotations

import configparser
import datetime as _datetime
import os
import platform as _platform
import shlex
import shutil
import subprocess
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


@dataclass(frozen=True)
class HostApp:
    """A launchable application discovered from the host OS."""

    name: str
    target: str
    kind: str
    command: tuple[str, ...] = ()


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

    # --- host applications -------------------------------------------------

    def list_host_apps(self, limit: int = 120) -> list[HostApp]:
        """Discover applications registered by the current operating system."""
        if self.system == "Windows":
            apps = self._windows_apps()
        elif self.system == "Darwin":
            apps = self._macos_apps()
        else:
            apps = self._linux_apps()
        unique: dict[tuple[str, str], HostApp] = {}
        for app in apps:
            unique.setdefault((app.name.casefold(), app.target), app)
        return sorted(unique.values(), key=lambda app: app.name.casefold())[:limit]

    def launch_host_app(self, app: HostApp) -> None:
        """Launch one application discovered by ``list_host_apps``."""
        if app.command:
            self.launch_command(list(app.command))
            return
        self.open_host_path(app.target)

    def launch_command(self, args: list[str]) -> None:
        """Launch a host command without invoking a shell."""
        if not args:
            raise ValueError("a command is required")
        kwargs = {"cwd": str(self.cwd), "start_new_session": True}
        if self.system == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(args, **kwargs)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"host command not found: {args[0]}") from exc

    def open_host_path(self, target: str | os.PathLike[str]) -> None:
        """Open a host path with the operating system's default application."""
        path = str(target)
        if self.system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif self.system == "Darwin":
            subprocess.Popen(["open", path], start_new_session=True)
        else:
            self.launch_command(["xdg-open", path])

    def _windows_apps(self) -> list[HostApp]:
        roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        apps: list[HostApp] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.suffix.lower() in (".lnk", ".url", ".exe"):
                    apps.append(HostApp(path.stem, str(path), path.suffix.lower()[1:]))
        return apps

    def _macos_apps(self) -> list[HostApp]:
        roots = [Path("/Applications"), Path.home() / "Applications"]
        apps: list[HostApp] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.glob("*.app"):
                apps.append(HostApp(path.stem, str(path), "app"))
        return apps

    def _linux_apps(self) -> list[HostApp]:
        roots = [
            Path.home() / ".local/share/applications",
            Path("/usr/local/share/applications"),
            Path("/usr/share/applications"),
        ]
        apps: list[HostApp] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.glob("*.desktop"):
                app = self._read_desktop_file(path)
                if app is not None:
                    apps.append(app)
        return apps

    @staticmethod
    def _read_desktop_file(path: Path) -> HostApp | None:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding="utf-8")
            entry = parser["Desktop Entry"]
        except (OSError, KeyError, configparser.Error):
            return None
        if entry.get("Type", "Application") != "Application":
            return None
        if entry.getboolean("NoDisplay", fallback=False) or entry.getboolean("Hidden", fallback=False):
            return None
        raw_exec = entry.get("Exec", "").strip()
        if not raw_exec:
            return None
        try:
            command = tuple(part for part in shlex.split(raw_exec)
                            if not part.startswith("%"))
        except ValueError:
            return None
        if not command:
            return None
        executable = command[0]
        if not (os.path.isabs(executable) and os.path.exists(executable)):
            if shutil.which(executable) is None:
                return None
        return HostApp(entry.get("Name", path.stem), str(path), "desktop", command)
