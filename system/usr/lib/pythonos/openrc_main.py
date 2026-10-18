"""PythonOS's OpenRC service entry point.

OpenRC/BusyBox remains PID 1 in native mode. This module is deliberately a
normal service process: it prints the PythonOS identity, runs the guest
self-test when requested, and is the place where the native graphical session
will be attached. The hosted desktop is started with ``pythonos-desktop`` on
the existing operating system.
"""

from __future__ import annotations

import os
import sys
import time

# Running a file directly puts /usr/lib/pythonos on sys.path, but the package
# itself lives one directory above it. OpenRC intentionally gives services a
# minimal environment, so make the image path explicit before importing.
if "/usr/lib" not in sys.path:
    sys.path.insert(0, "/usr/lib")

from pythonos import __pretty_name__, __version__, selftest, syscalls
from pythonos.tui import ansi
from pythonos.tui.logo import logo_lines


def cmdline() -> list[str]:
    try:
        with open("/proc/cmdline", "r", encoding="utf-8") as fh:
            return fh.read().split()
    except OSError:
        return []


def has_arg(args: list[str], key: str) -> bool:
    return any(arg == key or arg.startswith(key + "=") for arg in args)


def print_report() -> None:
    color = ansi.supports_color()
    print()
    for line in logo_lines():
        print("  " + ansi.colorize(line, ansi.BOLD, ansi.CYAN, enabled=color))
    print()
    print("  " + ansi.colorize(__pretty_name__, ansi.BOLD, ansi.BRIGHT_WHITE,
                            enabled=color))
    print("  " + ansi.dim("Alpine Linux · OpenRC · Python userland"))
    print()
    print("  " + ansi.green("[  OK  ]") + " OpenRC is managing the native system")
    print("  " + ansi.green("[  OK  ]") + f" Python {sys.version.split()[0]} is ready")
    print("  " + ansi.green("[  OK  ]") + " pysh is available on tty1 and ttyS0")
    print()
    print("  " + ansi.dim("Hosted mode: install requirements.txt and run pythonos-desktop"))
    print()
    print("  " + ansi.yellow("If the GUI is not visible, run:"))
    print("    rc-service pythonos-gui start")
    print(flush=True)


def poweroff(reason: str) -> int:
    print(f"\n  {ansi.yellow('PythonOS is halting')} ({reason})", flush=True)
    try:
        syscalls.reboot(syscalls.RB_POWER_OFF)
    except OSError as exc:
        print(f"  poweroff failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


def main() -> int:
    os.environ.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    os.environ.setdefault("PYTHONPATH", "/usr/lib/pythonos:/usr/lib")
    args = cmdline()
    if has_arg(args, "pythonos.selftest=1"):
        code = selftest.main(["--guest"])
        poweroff("self-test finished")
        return code

    if has_arg(args, "pythonos.demo=1"):
        # Reuse the visual tour while OpenRC remains the real init. The demo
        # paints tty1, then exits so OpenRC's getty can own the console.
        from pythonos.init_main import run_demo
        run_demo()
        return 0

    print_report()
    # A normal service should finish; OpenRC continues with the gettys in
    # inittab. Do not hold the default runlevel open until the GUI exists.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
