"""pyfetch — system information at a glance, PythonOS style."""

import os
import sys
import time

from pythonos import __codename__, __version__
from pythonos.tui import ansi
from pythonos.tui.logo import LOGO_SMALL
from pythonos.pysh import fmt


def _read(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return default


def _cpu_model():
    for line in _read("/proc/cpuinfo").splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return os.uname().machine


def _meminfo():
    info = {}
    for line in _read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields:
            info[key.strip()] = int(fields[0])
    return info


def _uptime():
    try:
        return fmt.human_uptime(float(_read("/proc/uptime").split()[0]))
    except (OSError, ValueError):
        return "?"


def _disk():
    try:
        st = os.statvfs("/")
    except OSError:
        return "?"
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - st.f_bfree * st.f_frsize
    return f"{fmt.human_size(used)} / {fmt.human_size(total)}"


def _processes():
    try:
        return sum(1 for e in os.listdir("/proc") if e.isdigit())
    except OSError:
        return 0


def collect():
    mem = _meminfo()
    total = mem.get("MemTotal", 0) * 1024
    available = mem.get("MemAvailable", mem.get("MemFree", 0)) * 1024
    used = max(total - available, 0)
    return [
        ("OS", f"PythonOS {__version__} \"{__codename__}\" {os.uname().machine}"),
        ("Kernel", os.uname().release),
        ("Uptime", _uptime()),
        ("Shell", f"pysh {__version__}"),
        ("Python", sys.version.split()[0]),
        ("CPU", f"{_cpu_model()} ({os.cpu_count()} threads)"),
        ("Memory", f"{fmt.human_size(used)} / {fmt.human_size(total)}"),
        ("Disk /", _disk()),
        ("Processes", str(_processes())),
    ]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    plain = "--plain" in argv or not ansi.supports_color()

    if plain:
        print(f"pythonos {__version__}")
        for label, value in collect():
            print(f"{label}: {value}")
        return 0

    use_color = ansi.supports_color()
    art = [line for line in LOGO_SMALL.strip("\n").splitlines()]
    art_width = max(len(line) for line in art)

    rows_data = collect()
    user = os.environ.get("USER", "root")
    header = f"{user}@pythonos"
    cols = ansi.terminal_size()[0]
    if cols < 86:
        # VGA console friendly: logo above, facts below
        print()
        for line in art:
            print("  " + ansi.colorize(line, ansi.BOLD, ansi.CYAN, enabled=use_color))
        print()
        print("  " + ansi.colorize(header, ansi.BOLD, ansi.GREEN, enabled=use_color))
        print("  " + ansi.dim("-" * len(header), enabled=use_color))
        for label, value in rows_data:
            print("  " + ansi.colorize(f"{label}:", ansi.BOLD, ansi.CYAN,
                                       enabled=use_color) + " " + value)
        print()
        return 0
    right = [ansi.colorize(header, ansi.BOLD, ansi.GREEN, enabled=use_color),
             ansi.dim("-" * len(header), enabled=use_color)]
    for label, value in rows_data:
        right.append(ansi.colorize(f"{label}:", ansi.BOLD, ansi.CYAN, enabled=use_color)
                     + " " + value)

    print()
    for i in range(max(len(art), len(right))):
        left = art[i] if i < len(art) else ""
        left = ansi.colorize(left.ljust(art_width), ansi.BOLD, ansi.CYAN,
                             enabled=use_color)
        print(f"  {left}  {right[i] if i < len(right) else ''}")
    print()
    return 0
