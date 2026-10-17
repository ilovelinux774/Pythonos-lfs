"""Boot sequence: mount the world, detect hardware, draw the splash.

Runs as PID 1 from the initramfs before any shell exists.
"""

import os
import platform
import time

from . import syscalls
from .tui import ansi
from .tui.logo import logo_lines
from .version import banner_subtitle


def read_meminfo():
    info = {}
    try:
        with open("/proc/meminfo", "r", encoding="ascii", errors="replace") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                info[key.strip()] = int(rest.split()[0]) if rest.split() else 0
    except OSError:
        pass
    return info


def cpu_model():
    try:
        with open("/proc/cpuinfo", "r", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown CPU"


def human_kb(kb):
    value = kb / 1024.0
    if value >= 1024:
        return f"{value / 1024.0:.1f} GiB"
    return f"{value:.0f} MiB"


class BootSequence:
    """Performs early boot and records the result of each step."""

    def __init__(self, quiet=False):
        self.quiet = quiet
        self.results = []

    def _record(self, label, fn, fatal=False):
        try:
            fn()
            self.results.append((label, True, ""))
        except Exception as exc:  # noqa: BLE001 - boot must keep going
            self.results.append((label, False, str(exc)))
            if fatal:
                raise

    def _mounts(self):
        # devtmpfs gives us /dev/console, tty1 and ttyS0.
        if not os.path.ismount("/dev"):
            syscalls.mount("devtmpfs", "/dev", "devtmpfs",
                           syscalls.MS_NOSUID | syscalls.MS_RELATIME)
        for target, fstype, flags, source in (
            ("/proc", "proc", syscalls.MS_NOSUID | syscalls.MS_NODEV | syscalls.MS_NOEXEC, "proc"),
            ("/sys", "sysfs", syscalls.MS_NOSUID | syscalls.MS_NODEV | syscalls.MS_NOEXEC, "sysfs"),
            ("/dev/pts", "devpts", syscalls.MS_NOSUID | syscalls.MS_NOEXEC, "devpts"),
            ("/run", "tmpfs", syscalls.MS_NOSUID | syscalls.MS_NODEV, "tmpfs"),
            ("/tmp", "tmpfs", syscalls.MS_NOSUID | syscalls.MS_NODEV, "tmpfs"),
        ):
            if os.path.ismount(target):
                continue
            data = "mode=0755,size=64m" if fstype == "tmpfs" and target == "/tmp" else None
            syscalls.mount(source, target, fstype, flags, data)

    def _tmp_permissions(self):
        os.chmod("/tmp", 0o1777)

    def _hostname(self):
        name = "pythonos"
        try:
            with open("/etc/hostname", "r", encoding="utf-8") as fh:
                candidate = fh.read().strip()
                if candidate:
                    name = candidate
        except OSError:
            pass
        syscalls.sethostname(name)

    def run(self):
        self._record("Mounted /dev, /proc, /sys, /run, /tmp", self._mounts, fatal=True)
        self._record("Set permissions on /tmp", self._tmp_permissions)
        self._record("Set hostname to pythonos", self._hostname)
        return self.results

    # -- presentation ------------------------------------------------------
    def print_report(self):
        for label, ok, detail in self.results:
            if ok:
                status = ansi.green("[  OK  ]")
            else:
                status = ansi.red("[FAILED]")
            print(f"  {status} {label}")
            if not ok and detail:
                print(f"           {ansi.dim(detail)}")
        print()


def splash(quiet=False, delay=0.0):
    """Draw the PythonOS identity block."""
    use_color = ansi.supports_color()
    print()
    ansi.hide_cursor()
    for line in logo_lines():
        print("  " + ansi.colorize(line, ansi.BOLD, ansi.CYAN, enabled=use_color))
        if delay and not quiet:
            time.sleep(delay)
    print()
    print("  " + ansi.colorize(banner_subtitle(), ansi.BOLD, ansi.BRIGHT_WHITE, enabled=use_color))
    print()
    ansi.show_cursor()


def hardware_summary():
    mem = read_meminfo()
    total = mem.get("MemTotal", 0)
    cpus = os.cpu_count() or 1
    return {
        "cpu": cpu_model(),
        "cpus": cpus,
        "mem_kb": total,
        "mem_human": human_kb(total) if total else "unknown",
        "kernel": platform.release(),
    }


def boot_line(title):
    print(f"  {ansi.yellow('[*]')} {title}")
