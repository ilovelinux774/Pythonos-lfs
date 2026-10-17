"""PythonOS ASCII identity — pure ASCII so it renders on the VGA console."""

LOGO = r"""
 ____        _   _                  ___  ____
|  _ \ _   _| |_| |__   ___  _ __  / _ \/ ___|
| |_) | | | | __| '_ \ / _ \| '_ \| | | \___ \
|  __/| |_| | |_| | | | (_) | | | | |_| |___) |
|_|    \__, |\__|_| |_|\___/|_| |_|\___/|____/
       |___/
"""

LOGO_SMALL = r"""
  ____        _   _              ___  ____
 |  _ \ _   _| |_| |__   ___   / _ \/ ___|
 | |_) | | | | __| '_ \ / _ \ | | | \___ \
 |  __/| |_| | |_| | | | (_) || |_| |___) |
 |_|    \__, |\__|_| |_|\___/  \___/|____/
        |___/
"""


def logo_lines():
    return [line for line in LOGO.strip("\n").splitlines()]


def logo_width():
    return max(len(line) for line in logo_lines())
