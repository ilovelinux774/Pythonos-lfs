# Changelog

All notable changes to PythonOS are documented here.

## Unreleased — modular desktop phase

The project now has two intended runtimes: a hosted desktop that runs as a
normal Python application on Linux, Windows and macOS, and a native Alpine
image that uses OpenRC.

### Added

- `requirements.txt` and `pyproject.toml` for a standard editable Python
  install (Python 3.9+).
- `pythonos-desktop`, a PySide6-Essentials hosted desktop entry point.
- PythonOS panel, taskbar, application launcher, welcome screen, terminal,
  files, settings and about applications. The taskbar tracks open windows,
  supports minimize/restore and includes host/status indicators and a clock.
- Private hosted data directory at `~/.pythonos/`.
- OpenRC in the Alpine rootfs and an explicit OpenRC runlevel configuration.
- Native `pythonos` OpenRC service and Alpine/BusyBox gettys on tty1 and
  ttyS0.
- Native guest self-test now verifies OpenRC PID 1 and the default runlevel.
- Hosted GUI offscreen smoke test and reproducible desktop screenshot.

### Changed

- Native `/init` is now a compatibility wrapper to Alpine's `/sbin/init`;
  Python is the service/framework layer rather than a replacement PID 1.
- The desktop architecture is platform-backed so the same Python application
  model can later run in hosted, native and phone modes.

## [0.1.0] — 2026-10-17 — "Constrictor"

The first bootable release. PythonOS boots on x86_64 from a 27 MB hybrid
ISO and lands in a Python shell.

### Added

- **PID 1 in Python** (`pythonos.init_main`): mounts `/dev`, `/proc`,
  `/sys`, `/dev/pts`, `/run`, `/tmp` via `mount(2)` through `ctypes`, sets
  the hostname, draws the boot splash, spawns shells on tty1 and ttyS0,
  supervises them with restart backoff, reaps orphans and powers the
  machine off on SIGTERM.
- **pysh**, a from-scratch shell: quoting-aware tokenizer, `|`, `;`, `&&`,
  `||`, `>`, `>>`, `<`, `2>`, `2>&1`, `$VAR`/`${VAR}`/`$?`/`$$` expansion,
  `~`, globbing, aliases, readline history, typo suggestions, and a `py`
  builtin for live Python evaluation.
- **~40 builtins**: `ls cat cp mv rm mkdir rmdir touch find du head tail
  wc grep ps kill free df mount uname uptime date whoami hostname env
  export unset which poweroff reboot sleep echo printf true false seq yes
  basename dirname cd pwd exit history clear alias unalias help`.
- **Applications**: `pyfetch` (system summary), `pytop` (interactive
  process monitor with per-process CPU accounting), `pyedit` (full-screen
  editor), `pkg` (package manager).
- **Package repository** with three packages: `hello`, `sysinfo`,
  `starfield`.
- **Self-test**: 22 checks, runnable inside the image
  (`pythonos.selftest=1`) — verifies PID 1 is Python, that the core
  filesystems are mounted, and drives the whole userland including a
  `pkg install → run → remove` cycle.
- **Build system**: `builder/prepare_rootfs.sh` (stage the rootfs),
  `builder/build.py` (overlay + initramfs + ISO), `builder/test_boot.sh`
  (QEMU boot assertion), `builder/demo_shots.py` (VGA screenshot capture
  driven through the QEMU monitor).
- **Docs**: architecture, build guide, userland reference, screenshots
  from real boots.

### Fixed

- Boot hangs without entropy: CPython aborts when it cannot seed its hash
  randomisation, so the image ships a `/usr/bin/python3` wrapper that
  defaults `PYTHONHASHSEED=0`.
- `pysh` adopted no `PATH` when the kernel handed it an empty
  environment; it now defaults to the standard paths.
- `2>&1` no longer consumes the following token as a redirect target.
- Forked pipeline stages flush Python buffers before exiting, so piped
  builtins no longer lose output.

### Known limitations

- Live system only — no persistence, no users besides root, no networking.
- Prebuilt Linux 6.6 LTS kernel (Alpine netboot) rather than an in-tree
  kernel build.
- x86_64 only.

[0.1.0]: https://github.com/ilovelinux774/Pythonos-lfs/releases/tag/v0.1.0
