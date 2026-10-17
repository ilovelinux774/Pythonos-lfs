"""ANSI escape-code helpers.

Works on the Linux VGA console, serial terminals and any ANSI-capable
terminal.  Colours degrade to plain text when the output is not a TTY or
TERM is 'dumb'.
"""

import os
import re
import shutil
import sys

ESC = "\x1b"

# --- SGR attributes -------------------------------------------------------
RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"
DIM = f"{ESC}[2m"
ITALIC = f"{ESC}[3m"
UNDERLINE = f"{ESC}[4m"
BLINK = f"{ESC}[5m"
REVERSE = f"{ESC}[7m"

BLACK = f"{ESC}[30m"
RED = f"{ESC}[31m"
GREEN = f"{ESC}[32m"
YELLOW = f"{ESC}[33m"
BLUE = f"{ESC}[34m"
MAGENTA = f"{ESC}[35m"
CYAN = f"{ESC}[36m"
WHITE = f"{ESC}[37m"

BRIGHT_BLACK = f"{ESC}[90m"
BRIGHT_RED = f"{ESC}[91m"
BRIGHT_GREEN = f"{ESC}[92m"
BRIGHT_YELLOW = f"{ESC}[93m"
BRIGHT_BLUE = f"{ESC}[94m"
BRIGHT_MAGENTA = f"{ESC}[95m"
BRIGHT_CYAN = f"{ESC}[96m"
BRIGHT_WHITE = f"{ESC}[97m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _isatty(stream=None):
    stream = stream or sys.stdout
    try:
        return stream.isatty()
    except Exception:
        return False


def supports_color(stream=None):
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("PYTHONOS_FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    return _isatty(stream)


def colorize(text, *codes, stream=None, enabled=None):
    """Wrap *text* in SGR codes when colour is supported."""
    if enabled is None:
        enabled = supports_color(stream)
    if not enabled or not codes:
        return text
    return "".join(codes) + str(text) + RESET


# Convenience colour wrappers ---------------------------------------------
def red(t, **kw):
    return colorize(t, RED, **kw)


def green(t, **kw):
    return colorize(t, GREEN, **kw)


def yellow(t, **kw):
    return colorize(t, YELLOW, **kw)


def blue(t, **kw):
    return colorize(t, BLUE, **kw)


def magenta(t, **kw):
    return colorize(t, MAGENTA, **kw)


def cyan(t, **kw):
    return colorize(t, CYAN, **kw)


def bold(t, **kw):
    return colorize(t, BOLD, **kw)


def dim(t, **kw):
    return colorize(t, DIM, **kw)


def strip(text):
    """Remove ANSI sequences so display width can be measured."""
    return _ANSI_RE.sub("", text)


def width(text):
    return len(strip(text))


def terminal_size(fallback=(80, 24)):
    try:
        size = shutil.get_terminal_size(fallback=fallback)
        return size.columns, size.lines
    except Exception:
        return fallback


# --- screen control -------------------------------------------------------
def clear():
    sys.stdout.write(f"{ESC}[2J{ESC}[H")
    sys.stdout.flush()


def home():
    sys.stdout.write(f"{ESC}[H")


def move(row, col):
    """1-based cursor addressing."""
    sys.stdout.write(f"{ESC}[{row};{col}H")


def clear_line():
    sys.stdout.write(f"{ESC}[2K")


def hide_cursor():
    sys.stdout.write(f"{ESC}[?25l")


def show_cursor():
    sys.stdout.write(f"{ESC}[?25h")


def enter_alt_screen():
    sys.stdout.write(f"{ESC}[?1049h")


def exit_alt_screen():
    sys.stdout.write(f"{ESC}[?1049l")
