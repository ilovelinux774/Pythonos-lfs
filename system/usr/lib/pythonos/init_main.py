"""Legacy Python boot/session helpers.

Native mode now uses Alpine's BusyBox init and OpenRC. This module remains
for the console demo and for compatibility with the first Python-PID1
prototype; the production boot entry point is ``openrc_main.py``.

Boot arguments honoured by the demo include ``pythonos.selftest=1`` and
``pythonos.demo=1``. The hosted graphical entry point is
``pythonos-desktop``.
"""

import fcntl
import os
import signal
import sys
import termios
import time
import traceback

from pythonos import __pretty_name__, boot, syscalls
from pythonos.tui import ansi

SHELL_CMD = [sys.executable, "-m", "pysh.shell", "--login"]
CONSOLES = ("/dev/tty1", "/dev/ttyS0")


def log(msg):
    print(f"  {ansi.dim('init:')} {msg}", flush=True)


def parse_cmdline():
    try:
        with open("/proc/cmdline", "r", encoding="utf-8") as fh:
            return fh.read().split()
    except OSError:
        return []


def cmdline_get(args, key, default=None):
    prefix = key + "="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return default


def shutdown(reason="system halt"):
    print(f"\n  {ansi.yellow('PythonOS is halting')} ({reason}). Goodbye.\n", flush=True)
    try:
        syscalls.reboot(syscalls.RB_POWER_OFF)
    except OSError as exc:
        log(f"poweroff failed ({exc}); trying halt")
        try:
            syscalls.reboot(syscalls.RB_HALT_SYSTEM)
        except OSError:
            log("halt failed; spinning forever")
            while True:
                time.sleep(3600)


def _signal_poweroff(signum, frame):  # noqa: ARG001
    shutdown(f"received {signal.Signals(signum).name}")


def install_signal_handlers():
    signal.signal(signal.SIGTERM, _signal_poweroff)
    signal.signal(signal.SIGINT, _signal_poweroff)
    # PID 1 otherwise ignores SIGCHLD, which still leaves zombies; we reap
    # explicitly in the supervisor loop below.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)


def child_env():
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
        "USER": "root",
        "LOGNAME": "root",
        "SHELL": sys.executable,
        "TERM": "linux",
        "HOSTNAME": "pythonos",
        "LANG": "C.UTF-8",
        "PYTHONPATH": "/usr/lib/pythonos:/usr/lib",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONOS": "1",  # marker for tools that care
    }
    return env


def spawn_shell(console):
    """Fork a login shell on *console*; return its pid."""
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.setsid()
            fd = os.open(console, os.O_RDWR)
            fcntl.ioctl(fd, termios.TIOCSCTTY, 0)
            os.dup2(fd, 0)
            os.dup2(fd, 1)
            os.dup2(fd, 2)
            if fd > 2:
                os.close(fd)
            os.chdir("/root")
            os.execve(sys.executable, SHELL_CMD, child_env())
        except Exception:  # noqa: BLE001 - never return into init's loop
            traceback.print_exc()
        os._exit(127)
    return pid


def available_consoles():
    found = []
    for path in CONSOLES:
        if os.path.exists(path):
            found.append(path)
    if not found and os.path.exists("/dev/console"):
        found.append("/dev/console")
    return found


def run_shells(quiet=False):
    consoles = available_consoles()
    children = {}
    for console in consoles:
        try:
            pid = spawn_shell(console)
            children[pid] = console
        except OSError as exc:
            log(f"cannot start shell on {console}: {exc}")

    if quiet:
        return children

    print(f"  {ansi.green('[  OK  ]')} Started pysh on {', '.join(children.values())}")
    print(f"  {ansi.green('[  OK  ]')} Reached target Multi-User (Python)")
    print()
    return children


def _with_tty(path, fn):
    """Run *fn* with stdout pointed at a specific console (for demo mode)."""
    try:
        fd = os.open(path, os.O_WRONLY)
    except OSError:
        return False
    saved = os.dup(1)
    try:
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        os.dup2(fd, 1)
        fn()
        sys.stdout.flush()
    finally:
        os.dup2(saved, 1)
        os.close(saved)
        os.close(fd)
    return True


def run_demo():
    """Paint a tour of the system on tty1 for screenshots, then continue."""
    from pythonos import selftest
    from pythonos.tools import pyfetch, pytop

    tty = "/dev/tty1"
    hw = boot.hardware_summary()

    def show_splash():
        ansi.clear()
        boot.splash(quiet=True)
        seq = boot.BootSequence()
        for label, ok, detail in (
            ("Mounted /dev, /proc, /sys, /run, /tmp", True, ""),
            ("Set permissions on /tmp", True, ""),
            ("Set hostname to pythonos", True, ""),
        ):
            print(f"  {ansi.green('[  OK  ]')} {label}")
        print()
        print(f"  {ansi.dim('Python')} {sys.version.split()[0]}"
              f"   {ansi.dim('·')}   {ansi.dim('kernel')} {hw['kernel']}"
              f"   {ansi.dim('·')}   {hw['cpus']} CPU"
              f"   {ansi.dim('·')}   {hw['mem_human']} RAM")
        print()
        print(f"  {ansi.green('[  OK  ]')} Started pysh on /dev/tty1")
        print(f"  {ansi.green('[  OK  ]')} Reached target Multi-User (Python)")
        print()
        ansi.hide_cursor()

    def show_fetch():
        ansi.clear()
        pyfetch.main([])

    def show_top():
        ansi.clear()
        state = pytop.snapshot()
        state = pytop.snapshot(prev_cpu=state["cpu_raw"],
                               prev_procs=state["raw"], interval=0.2)
        print("\n".join(ansi.strip(line) for line in pytop.render(state)))

    def show_test():
        ansi.clear()
        # The demo is a guest boot even though OpenRC runs this service as a
        # normal process rather than PID 1; request the guest checks explicitly.
        selftest.main(["--guest"])
        ansi.show_cursor()

    try:
        log("DEMO:splash")
        _with_tty(tty, show_splash)
        time.sleep(9)
        log("DEMO:pyfetch")
        _with_tty(tty, show_fetch)
        time.sleep(9)
        log("DEMO:pytop")
        _with_tty(tty, show_top)
        time.sleep(9)
        log("DEMO:selftest")
        _with_tty(tty, show_test)
        time.sleep(10)
        log("DEMO:shell")
    except Exception as exc:  # noqa: BLE001 - a demo must never break boot
        log(f"demo failed: {exc}")


def run_selftest():
    from pythonos import selftest

    code = selftest.main()
    shutdown("self-test finished")
    return code


def supervise(children):
    """Reap children forever and respawn shells that die."""
    started = {pid: time.monotonic() for pid in children}
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
        except ChildProcessError:
            time.sleep(1)
            continue
        except InterruptedError:
            continue

        if pid not in children:
            continue  # reaped an orphan reparented to us

        console = children.pop(pid)
        uptime = time.monotonic() - started.get(pid, 0)
        code = os.waitstatus_to_exitcode(status)
        log(f"shell on {console} exited (status {code})")

        if code == 0:
            continue  # a clean exit: leave that console quiet

        # Crash-loop guard: back off if the shell dies immediately.
        time.sleep(min(3.0, 0.25 + uptime))
        try:
            new_pid = spawn_shell(console)
            children[new_pid] = console
            started[new_pid] = time.monotonic()
            log(f"restarted shell on {console} (pid {new_pid})")
        except OSError as exc:
            log(f"cannot restart shell on {console}: {exc}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    os.chdir("/")
    os.umask(0o022)
    os.environ.setdefault("PATH",
                          "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    os.environ.setdefault("HOME", "/root")
    os.environ.setdefault("TERM", "linux")
    os.environ.setdefault("LANG", "C.UTF-8")
    install_signal_handlers()

    # /proc is not mounted yet, so the real cmdline is read after boot
    # setup below; this early peek only catches `quiet` on dev boots.
    args = parse_cmdline()
    quiet = cmdline_get(args, "pythonos.quiet") == "1"

    if os.getpid() != 1:
        print("init: not running as PID 1 — refusing to boot", file=sys.stderr)
        return 1

    try:
        boot.splash(quiet=quiet, delay=0.02)

        seq = boot.BootSequence(quiet=quiet)
        seq.run()
        seq.print_report()

        args = parse_cmdline()
        quiet = cmdline_get(args, "pythonos.quiet") == "1"
        hw = boot.hardware_summary()
        print(f"  {ansi.dim('Python')} {sys.version.split()[0]}"
              f"   {ansi.dim('·')}   {ansi.dim('kernel')} {hw['kernel']}"
              f"   {ansi.dim('·')}   {hw['cpus']} CPU"
              f"   {ansi.dim('·')}   {hw['mem_human']} RAM")
        print()

    except Exception:  # noqa: BLE001
        traceback.print_exc()
        log("boot failed — dropping to emergency shell")
        try:
            pid = spawn_shell("/dev/console")
            supervise({pid: "/dev/console"})
        except Exception:  # noqa: BLE001
            pass
        while True:
            time.sleep(3600)

    if cmdline_get(args, "pythonos.selftest") == "1":
        return run_selftest()

    if cmdline_get(args, "pythonos.demo") == "1":
        run_demo()

    children = run_shells(quiet=quiet)
    if not children:
        log("no console available — sleeping forever")
        while True:
            time.sleep(3600)
    supervise(children)
    return 0


if __name__ == "__main__":
    sys.exit(main())
