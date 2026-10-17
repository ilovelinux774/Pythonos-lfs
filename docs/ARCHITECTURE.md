# Architecture

PythonOS is one idea enforced strictly: the userspace is Python. This
document explains what runs at each stage of boot, what is not Python and
why, and how the pieces fit together.

## The boot chain

```
 firmware (SeaBIOS/UEFI)
   │
   ├─ ISO (isolinux, 27 MB)  or  USB stick (isohybrid)
   │
 Linux kernel 6.6 LTS  (prebuilt, from Alpine netboot)
   │  argv: console=tty0 console=ttyS0 quiet loglevel=3
   │  rdinit=/init
   │
 /init  ── shebang: #!/usr/bin/python3      ← Python becomes PID 1
   │
 pythonos.init_main.main()
   ├─ os.chdir("/"), umask, PATH/HOME/TERM defaults
   ├─ signal handlers (TERM/INT → poweroff)
   ├─ boot.splash()                      logo + version block
   ├─ boot.BootSequence.run()
   │    ├─ mount devtmpfs → /dev
   │    ├─ mount proc      → /proc
   │    ├─ mount sysfs     → /sys
   │    ├─ mount devpts    → /dev/pts
   │    ├─ mount tmpfs     → /run, /tmp
   │    └─ sethostname("pythonos")
   ├─ hardware summary (CPU model, RAM from /proc/meminfo)
   ├─ spawn pysh on /dev/tty1 and /dev/ttyS0
   │     fork → setsid → open(console) → TIOCSCTTY → dup2 → execve
   └─ supervise()
         waitpid(-1) forever
           ├─ unknown pid → orphan, already reaped, continue
           ├─ shell exit 0 → leave that console quiet
           └─ shell crash  → respawn with capped backoff
```

Everything in that tree after the kernel is Python. The kernel is the only
native code involved in booting.

## Filesystem layout

The image is a single initramfs (cpio.gz, ~15 MB) unpacked into a tmpfs
root by the kernel. Nothing is written to disk: PythonOS 0.1 is a live
system.

```
/init                      PID 1 script
/etc                       os-release, hostname, hosts, passwd, motd
/usr/bin/python3           wrapper → /usr/bin/python3.12 with PYTHONHASHSEED
/usr/bin/pysh              shell launcher
/usr/bin/{pyfetch,pytop,pyedit,pkg}
/usr/lib/pythonos/         the OS itself (this is where the code runs from)
/usr/share/pythonos/repo/  on-disk package repository
/var/lib/pythonos/pkg/     installed-package database (installed.json)
/root                       HOME; pysh history is written here
```

`/proc`, `/sys`, `/dev`, `/run` and `/tmp` are mounted by PID 1 at boot.

## What is Python, and what is not

| Component | Language | Why |
|---|---|---|
| init / PID 1 | Python | the point of the project |
| shell, all builtins | Python | `` |
| pyfetch, pytop, pyedit, pkg | Python | `` |
| the 3 repo packages | Python | `` |
| Linux kernel | C | we do not recompile kernels yet (roadmap) |
| `/usr/bin/python3.12` | C | CPython interpreter |
| busybox | C | Alpine's `sh` + core apps; present but unused by PythonOS |

The honest summary: **we stand on a kernel and an interpreter, and build
everything a usable system needs on top**. The roadmap's last item is
replacing the borrowed kernel with an in-tree build; until then the
kernel provenance is documented in `builder/prepare_rootfs.sh`.

## pysh internals

`pysh/shell.py` is a small, conventional implementation:

1. **Tokenize** (`tokenize`) — splits on whitespace while tracking single
   and double quotes and backslash escapes, keeps `|`, `;`, `&&`, `||`,
   `>`, `>>`, `2>`, `2>&1`, `<` as operator tokens.
2. **Alias expansion** (`_expand_aliases`) — rewrites the first word of
   each simple command, capped at 25 expansions to survive `alias ls='ls -l'`.
3. **Parse** (`parse`) — groups tokens into jobs (`Segment` objects) with
   their redirect targets.
4. **Expand** (`expand_word`) — quotes, `~`, `$VAR` / `${VAR}` / `$?` /
   `$$`, then globbing via `glob.glob` for unquoted `* ? [`.
5. **Execute** (`run_pipeline`) — single segment runs a builtin in-process
   (with fd save/restore around redirects) or forks for external binaries;
   multi-segment pipelines fork every stage and wire `os.pipe()` between
   them, then `waitpid` each.

Builtins live in `pysh/builtins.py`, registered by decorator into one
`COMMANDS` dict that is also `help`'s data source. Each builtin is a plain
function taking `(shell, args)` and returning an exit status.

## Why PYTHONHASHSEED=0

When the kernel starts `/init` from an initramfs it can happen before the
CRNG has been seeded. CPython's startup then calls `getrandom()` and
**aborts** (`Fatal Python error: _Py_HashRandomization_Init`), which as PID 1
means a kernel panic. `builder/build.py` therefore installs a three-line
`/usr/bin/python3` wrapper:

```sh
#!/bin/sh
PYTHONHASHSEED=${PYTHONHASHSEED:-0}
export PYTHONHASHSEED
exec /usr/bin/python3.12 "$@"
```

Deterministic hashing has no downside for a live system with no untrusted
input, and it makes boot work on any VM. Once entropy exists, nothing else
in the OS depends on it.

## Package manager

`pkg` operates on directories:

```
/usr/share/pythonos/repo/<name>/
├── app.json     {"name", "version", "description", "entry"}
└── main.py      the program
```

`pkg install NAME` copies the directory to `/usr/lib/pythonos/apps/NAME`,
writes a launcher into `/usr/bin/<entry>` and records it in
`/var/lib/pythonos/pkg/installed.json`. No network, no signing yet —
the repository is in the image and is itself part of the source tree.

## Build pipeline

```
builder/prepare_rootfs.sh   (sudo, once)
  curl alpine-minirootfs.tar.gz → /tmp/pyrootfs
  chroot apk add python3
        │
builder/build.py            (sudo, every build)
  copy system/ over /tmp/pyrootfs
  install python3 wrapper + static /dev nodes
  cpio | gzip → release/initramfs-lts
  isolinux + kernel + initramfs → release/pythonos-0.1.iso
        │
builder/test_boot.sh
  qemu -kernel -initrd pythonos.selftest=1 → expect "SELFTEST PASSED"
        │
builder/demo_shots.py
  qemu + monitor socket → screendump → PNG
```

Builds are incremental and take ~8 seconds; boot tests take ~30; screenshot
capture about a minute (it types into the console).

## Boot arguments

| Argument | Effect |
|---|---|
| `pythonos.selftest=1` | run the 22 checks, print results, power off |
| `pythonos.demo=1` | cycle splash → pyfetch → pytop → selftest, then start shells |
| `pythonos.quiet=1` | skip the splash animation |

## Known limits

* x86_64 only; single-user (root); no networking; no persistent storage.
* `pysh` implements a deliberate subset of POSIX shell: no `$(...)`
  substitution or job control (`&` is parsed but not backgrounded).
* `pyedit` is small on purpose: no search, no undo (yet).
* The kernel is borrowed from Alpine. Reproducing it in-tree is roadmap
  item 7.
