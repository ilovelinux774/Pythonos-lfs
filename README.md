# PythonOS

[![build-and-boot](https://github.com/ilovelinux774/Pythonos-lfs/actions/workflows/build.yml/badge.svg)](https://github.com/ilovelinux774/Pythonos-lfs/actions/workflows/build.yml)

**A modular desktop operating system whose user-facing layer is Python.**

PythonOS has two modes:

1. **Hosted desktop** — clone the repository, install the Python requirements,
   and run `pythonos-desktop` on an existing Linux, Windows or macOS machine.
   No VM, second computer, ISO or reboot is needed.
2. **Native image** — boot Alpine Linux with OpenRC, then run the PythonOS
   native services and shell. The graphical native session will reuse the same
   Python framework built in hosted mode.

The goal is similar in spirit to Android's layered design: Linux, native
libraries and service management remain underneath; the desktop, framework
and applications users interact with are Python.

![PythonOS booting](docs/screenshots/splash.png)

---

## Run the desktop now

```sh
git clone https://github.com/ilovelinux774/Pythonos-lfs.git
cd Pythonos-lfs

python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt

pythonos-desktop
```

The first hosted desktop opens as a normal application window with:

- a PythonOS desktop and panel
- application launcher
- PythonOS terminal
- private virtual filesystem and file browser
- settings and about applications
- fullscreen mode
- the same Python application model that will be used by native mode

PySide6-Essentials supplies portable native windowing through Qt. The
PythonOS desktop logic is Python; Qt is the lower-level C++ graphics layer.
Qt uses X11/Wayland on Linux, Win32 on Windows and Cocoa on macOS, so hosted
mode does not depend on X11 being installed.

Try inside the PythonOS terminal:

```text
help
sysinfo
ls
py 6 * 7
```

Hosted files are kept safely in `~/.pythonos/files` by default. PythonOS does
not treat the host's entire filesystem as its own root.

![PythonOS hosted desktop](docs/screenshots/hosted-desktop.png)

## Architecture

```text
Hosted mode                         Native mode
─────────────                       ───────────
pythonos-desktop                    Linux kernel
      │                                  │
PySide6 / Qt                         Alpine + BusyBox
      │                                  │
PythonOS desktop                    OpenRC
      │                                  │
Python apps + services              PythonOS services
                                         │
                                   Python desktop
```

The shared boundary is platform services. Desktop code asks for operations
such as `list_processes`, `get_clipboard`, `open_file` and
`launch_application`; the hosted and native backends implement them
separately. This keeps applications portable and leaves room for a later
phone backend with touch, battery, rotation and mobile navigation.

Read the detailed design in [`docs/MODULAR.md`](docs/MODULAR.md).

## Native Alpine/OpenRC image

Alpine is intentional. Reusing Alpine's kernel-facing plumbing, musl,
BusyBox and OpenRC lets us spend time on the Python framework instead of
reimplementing a package manager, service manager and low-level Linux base.

The native boot chain is:

```text
Linux kernel
  → /init compatibility wrapper
  → Alpine BusyBox init
  → OpenRC sysinit / boot / default
  → PythonOS OpenRC service
  → pysh gettys on tty1 and ttyS0
```

OpenRC owns PID 1 service management. Python is the framework and userland
layer above it. This is more robust than replacing a production init system
with a custom Python PID 1.

## Build and test the native image

Requirements: `curl`, `cpio`, `xorriso`, `isolinux`, `syslinux-common`,
`qemu-system-x86`, `gzip` and `sudo`.

```sh
make rootfs     # download Alpine minirootfs + kernel, install Python/OpenRC
make iso        # overlay PythonOS, pack initramfs and build hybrid ISO
make test       # boot the image in QEMU and run the guest self-test
make run        # boot it interactively

# Optional native Xorg + PySide6 profile (large):
make rootfs-gui
make iso-gui
```

The produced image is in `release/`:

- `release/pythonos-0.1.iso` — bootable hybrid ISO
- `release/initramfs-lts` — Alpine + OpenRC + PythonOS filesystem

The test boots the real initramfs with OpenRC and verifies:

```text
SELFTEST PASSED — 22 passed, 0 failed
```

It checks that OpenRC owns PID 1, that OpenRC reached the default runlevel,
that core filesystems are mounted, and that PythonOS's shell, text tools,
process tools, package manager and applications work.

## Repository layout

```text
pythonos/                    portable hosted framework
├── desktop/main.py          PySide6 desktop, launcher and windows
├── desktop/platform.py      cross-platform host services
└── desktop/terminal.py      PythonOS hosted terminal

system/                      files overlaid into the native Alpine image
├── init                     /sbin/init compatibility wrapper
├── etc/init.d/pythonos      OpenRC PythonOS service
├── etc/inittab              tty1 + serial gettys
└── usr/lib/pythonos/        native tools, shell and OpenRC entry point

builder/
├── prepare_rootfs.sh        Alpine + Python + OpenRC staging
├── build.py                 overlay, OpenRC runlevels, initramfs and ISO
├── test_boot.sh             QEMU guest test
└── demo_shots.py            VGA proof capture

docs/
├── MODULAR.md               hosted/native architecture
├── OPENRC.md                native boot and service design
├── BUILD.md                 build guide
└── USERLAND.md              pysh command reference
```

## Design principles

- **Modular:** hosted and native backends share Python applications and UI
  contracts.
- **Practical:** Alpine, OpenRC, Qt and Linux are reused instead of being
  rewritten for the sake of saying everything is from scratch.
- **Portable:** hosted mode is the fastest development and demonstration
  path; native mode is the eventual independent operating system.
- **Honest:** the kernel, OpenRC, BusyBox, musl and Qt remain native code.
  The desktop and application layer users see is Python.

## Roadmap

- [x] Alpine-based bootable image
- [x] OpenRC native service management
- [x] PythonOS shell and native userland
- [x] Hosted `pythonos-desktop` launcher
- [x] Cross-platform desktop MVP with terminal, files, settings and launcher
- [ ] Shared application/plugin manifests between hosted and native modes
- [ ] Native graphical session in the Alpine image
- [ ] Python window manager/compositor integration
- [ ] Network, audio and display services
- [ ] Persistent native installation
- [ ] Phone/mobile shell
- [ ] ARM64 image

## License

MIT — see [`LICENSE`](LICENSE).
