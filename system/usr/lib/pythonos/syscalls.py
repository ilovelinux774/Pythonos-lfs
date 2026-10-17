"""Thin ctypes bindings for the handful of Linux syscalls PythonOS needs.

Using libc directly keeps early boot independent of external binaries:
PID 1 mounts its own filesystems and powers the machine off without
shelling out to util-linux.
"""

import ctypes
import ctypes.util
import os
import platform

try:
    # These bindings are used by the Alpine/OpenRC native runtime. The
    # hosted shell tests can still import the native userland on Windows and
    # macOS, where there is no Linux libc exposing mount(2) and reboot(2).
    _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
except (AttributeError, OSError):
    _libc = None

# mount(2) flags
MS_RDONLY = 1
MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8
MS_SYNCHRONOUS = 16
MS_REMOUNT = 32
MS_NOATIME = 1024
MS_RELATIME = 1 << 21
MS_STRICTATIME = 1 << 24
MS_NOSYMFOLLOW = 256

# reboot(2) commands
RB_AUTOBOOT = 0x01234567
RB_POWER_OFF = 0x4321FEDC
RB_HALT_SYSTEM = 0xCdef0123

PR_SET_CHILD_SUBREAPER = 36

if _libc is not None and hasattr(_libc, "mount"):
    _libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                            ctypes.c_ulong, ctypes.c_char_p]
    _libc.mount.restype = ctypes.c_int
else:
    _libc = None


def errno_name():
    err = ctypes.get_errno()
    return os.strerror(err)


def mount(source, target, fstype="", flags=0, data=None):
    """mount(2). Returns 0 on success, raises OSError on failure."""
    if _libc is None:
        raise OSError(38, "mount(2) is unavailable on this host", target)
    os.makedirs(target, exist_ok=True)
    src = source.encode() if source else None
    tgt = target.encode()
    fst = fstype.encode() if fstype else None
    dat = data.encode() if data else None
    rv = _libc.mount(src, tgt, fst, flags, dat)
    if rv != 0:
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()), target)
    return 0


def reboot(cmd=RB_POWER_OFF):
    """Synchronise disks, then reboot(2). Does not return on success."""
    if _libc is None:
        raise OSError(38, "reboot(2) is unavailable on this host")
    try:
        os.sync()
    except Exception:
        pass
    _libc.reboot(ctypes.c_int(cmd), None)
    raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))


def sethostname(name):
    if _libc is None:
        raise OSError(38, "sethostname(2) is unavailable on this host")
    _libc.sethostname(name.encode(), len(name.encode()))


def setsid():
    return os.setsid() if hasattr(os, "setsid") else 0


def getpid():
    return os.getpid()


def is_uefi():
    return os.path.isdir("/sys/firmware/efi")


def machine():
    return platform.machine()
