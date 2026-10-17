"""sysinfo — plain-text system facts."""

import os
import platform
import sys


def read(path, default="?"):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return default


def main(argv=None):
    import sys as _sys
    sys.path.insert(0, "/usr/lib")
    sys.path.insert(0, "/usr/lib/pythonos")
    from pythonos.tools import pyfetch

    print("PythonOS system information")
    print("=" * 40)
    for label, value in pyfetch.collect():
        print(f"{label:<10} {value}")
    print(f"{'Machine':<10} {platform.machine()}")
    print(f"{'Hostname':<10} {os.uname().nodename}")
    print(f"{'Boot args':<10} {read('/proc/cmdline')[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
