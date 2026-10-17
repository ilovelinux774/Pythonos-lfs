"""PythonOS self-test.

Boot the ISO with ``pythonos.selftest=1`` (or run ``python selftest``
inside a running system) and every core subsystem is exercised: mounts,
pysh parsing, pipelines, redirection, the userland tools and the package
manager. Exit status 0 means the OS is healthy.
"""

import os
import subprocess
import sys
import tempfile

from pythonos import __version__
from pythonos.tui import ansi

CHECKS = []
FAILURES = []

# Where this package lives: .../usr/lib/pythonos -> PYTHONPATH .../usr/lib
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.dirname(_PKG_DIR)
PYTHONPATH = f"{_PKG_DIR}:{_LIB_DIR}"


def check(name, guest_only=False):
    def register(fn):
        CHECKS.append((name, fn, guest_only))
        return fn
    return register


def run_pysh(command, timeout=30):
    env = dict(os.environ)
    env["PYTHONPATH"] = PYTHONPATH
    env.setdefault("TERM", "dumb")
    return subprocess.run(
        [sys.executable, "-m", "pysh.shell", "-c", command],
        capture_output=True, text=True, timeout=timeout, env=env, cwd="/",
    )


def expect_ok(command, contains=None):
    proc = run_pysh(command)
    if proc.returncode != 0:
        raise AssertionError(f"exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    if contains is not None and contains not in proc.stdout:
        raise AssertionError(f"output missing {contains!r}: {proc.stdout.strip()[:200]}")


# --- boot ------------------------------------------------------------------
@check("running as PID 1", guest_only=True)
def _pid1():
    if os.getpid() != 1:
        raise AssertionError(f"pid is {os.getpid()}")



@check("PID 1 command line is Python", guest_only=True)
def _pid1_python():
    with open("/proc/1/cmdline", "rb") as fh:
        cmdline = fh.read().replace(b"\x00", b" ").decode()
    if "python" not in cmdline:
        raise AssertionError(cmdline[:120])


@check("core filesystems mounted", guest_only=True)
def _mounts():
    for target in ("/proc", "/sys", "/dev", "/tmp"):
        if not os.path.ismount(target):
            raise AssertionError(f"{target} not mounted")


@check("Python runtime is modern", )
def _python_version():
    if sys.version_info < (3, 10):
        raise AssertionError(sys.version)


@check("/tmp is writable")
def _tmp_writable():
    with tempfile.NamedTemporaryFile(dir="/tmp", prefix="pyos-", delete=True) as fh:
        fh.write(b"ok")
        fh.flush()


# --- pysh ------------------------------------------------------------------
@check("pysh: echo")
def _echo():
    expect_ok("echo hello pythonos", contains="hello pythonos")


@check("pysh: pipelines work")
def _pipeline():
    expect_ok("echo alpha | wc -l", contains="1")


@check("pysh: output redirection")
def _redirect():
    expect_ok("echo redirected > /tmp/pyos_r.txt; cat /tmp/pyos_r.txt",
              contains="redirected")


@check("pysh: globbing")
def _glob():
    expect_ok("touch /tmp/pyos_g1 /tmp/pyos_g2; ls /tmp/pyos_g*", contains="pyos_g2")


@check("pysh: file round-trip (mkdir/cp/mv/rm)")
def _files():
    expect_ok(
        "mkdir -p /tmp/pyos_dir && echo data > /tmp/pyos_dir/a.txt && "
        "cp /tmp/pyos_dir/a.txt /tmp/pyos_dir/b.txt && "
        "mv /tmp/pyos_dir/b.txt /tmp/pyos_dir/c.txt && "
        "cat /tmp/pyos_dir/c.txt && rm -r /tmp/pyos_dir",
        contains="data")


@check("pysh: grep with regex")
def _grep():
    expect_ok("echo 'needle in haystack' > /tmp/pyos_grep.txt; "
              "grep needle /tmp/pyos_grep.txt", contains="needle")


@check("pysh: exit status tracking")
def _status():
    expect_ok("false; echo code=$?", contains="code=1")


@check("pysh: python builtin")
def _py():
    expect_ok("py 'print(6 * 7)'", contains="42")


@check("pysh: find")
def _find():
    expect_ok("mkdir -p /tmp/pyos_find && touch /tmp/pyos_find/target.txt; "
              "find /tmp/pyos_find -name '*.txt'", contains="target.txt")


@check("pysh: text tools (head/tail/wc)")
def _text():
    expect_ok("seq 1 5 > /tmp/pyos_n.txt; head -n 2 /tmp/pyos_n.txt | tail -n 1",
              contains="2")


@check("pysh: aliases")
def _alias():
    expect_ok("alias ll='ls -l'; ll /", contains="bin")


# --- system tools ----------------------------------------------------------
@check("system: uname/df/free/ps/uptime")
def _system_tools():
    expect_ok("uname; df; free; ps; uptime")


@check("system: mount table readable")
def _mounts_tool():
    expect_ok("mount", contains="/proc")


@check("pyfetch produces a report")
def _pyfetch():
    expect_ok("pyfetch --plain", contains="PythonOS")


@check("pytop renders a snapshot")
def _pytop():
    expect_ok("pytop --once", contains="PID")


# --- package manager -------------------------------------------------------
@check("pkg: repository is reachable")
def _pkg_search():
    expect_ok("pkg search", contains="hello")


@check("pkg: install / run / remove", guest_only=True)
def _pkg_roundtrip():
    expect_ok("pkg install hello", contains="installed")
    proc = run_pysh("hello PythonOS")
    if "Hello, PythonOS" not in proc.stdout:
        raise AssertionError(proc.stdout[:200] or proc.stderr[:200])
    expect_ok("pkg remove hello", contains="removed")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    guest = os.getpid() == 1 or "--guest" in argv
    use_color = ansi.supports_color()

    print()
    print(f"  {ansi.bold('PythonOS self-test')} {ansi.dim('v' + __version__)}")
    print(f"  {ansi.dim('guest mode' if guest else 'host mode')}")
    print()

    passed = failed = skipped = 0
    for name, fn, guest_only in CHECKS:
        if guest_only and not guest:
            print(f"  {ansi.yellow('[SKIP]')} {name}")
            skipped += 1
            continue
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  {ansi.red('[FAIL]')} {name}")
            print(f"         {ansi.dim(str(exc)[:300])}")
            FAILURES.append((name, str(exc)))
            failed += 1
        else:
            print(f"  {ansi.green('[PASS]')} {name}")
            passed += 1

    print()
    summary = f"{passed} passed, {failed} failed"
    if skipped:
        summary += f", {skipped} skipped"
    if failed:
        print(f"  {ansi.red(ansi.bold('SELFTEST FAILED'))} — {summary}")
    else:
        print(f"  {ansi.green(ansi.bold('SELFTEST PASSED'))} — {summary}")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
