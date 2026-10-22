# PythonOS architecture

PythonOS is a modular Python desktop environment with a native Alpine Linux
runtime. The same application and UI contracts are intended to work in both
modes.

## Two runtimes

```text
                         PythonOS framework
                 ┌──────────────┴──────────────┐
                 │                             │
          hosted platform                 native platform
                 │                             │
      Qt on Linux/Windows/macOS       Alpine + OpenRC + Linux
                 │                             │
             PythonOS desktop             PythonOS desktop
```

### Hosted platform

`pythonos-desktop` runs as an ordinary application. PySide6-Essentials
provides the portable native window and graphics layer. Qt selects the host's
X11/Wayland, Win32 or Cocoa backend. Desktop logic, application windows,
launcher, terminal and settings remain Python.

Hosted mode is designed to make development possible on one computer. It
does not require a VM, a second machine, an ISO or a reboot.

### Native platform

The native image uses Alpine's kernel-facing base and OpenRC:

```text
Linux kernel
  → /init compatibility wrapper
  → BusyBox init (PID 1)
  → OpenRC sysinit / boot / default
  → /etc/init.d/pythonos
  → pysh gettys on tty1 and ttyS0
```

`system/etc/init.d/pythonos` runs `openrc_main.py`. With
`pythonos.selftest=1`, it runs the guest self-test and powers off. In normal
mode it prints the system report and exits; Alpine getty then gives the user
a `pysh` login shell.

OpenRC deliberately owns PID 1 service management. Python is the framework,
service layer and userland above it. Reusing Alpine avoids spending the
project on a replacement init system.

### Live versus installed boot

The ISO boots the full `release/initramfs-lts` because the live desktop,
installer and recovery tools all run from RAM. A disk installation instead
uses `release/initramfs-installed`, generated with Alpine's `mkinitfs`. That
image contains storage/filesystem support, BusyBox diagnostics, root UUID
lookup, and `switch_root`; it does not contain PythonOS, Qt, Xorg, or the live
package tree. After `switch_root`, the installed root partition starts the
normal kernel/OpenRC chain above.

The installed initramfs enters a BusyBox shell automatically if it cannot
find/mount the root or complete `switch_root`. `pythonos.debug=1` and the
GRUB emergency entry enter that shell deliberately; typing `exit` returns to
the normal Alpine initramfs flow.

## Layers

### Native C and kernel layer

* Linux kernel and drivers
* musl C library
* BusyBox init, getty and low-level utilities
* OpenRC service manager
* Qt's native graphics implementation in hosted mode

### Python framework layer

* platform service contracts
* desktop window and panel model
* app lifecycle and manifests
* configuration and permissions
* terminal command model
* package/application APIs

### Python user-facing layer

* desktop shell
* launcher
* terminal
* files application
* settings
* system information/about screen
* future native window manager and services

## Repository mapping

```text
pythonos/
└── desktop/
    ├── main.py          desktop window, panel, launcher and apps
    ├── platform.py      private hosted paths and platform facts
    └── terminal.py      portable PythonOS terminal

system/
├── init                 OpenRC compatibility wrapper
├── etc/init.d/pythonos OpenRC service
└── usr/lib/pythonos/    native shell, tools and OpenRC entry point

builder/
├── prepare_rootfs.sh    Alpine + Python + OpenRC
├── build.py             overlay + OpenRC runlevels + initramfs + ISO
└── test_boot.sh         QEMU guest test
```

The native package currently contains the proven command-line userland from
the first prototype. The hosted package is the first graphical desktop
milestone. Native graphical mode will use the same app contracts rather than
becoming a separate codebase.

## Platform services

Applications must use a platform object instead of assuming Linux:

```python
class Platform:
    def open_file(self, path): ...
    def get_clipboard(self): ...
    def list_processes(self): ...
    def launch_application(self, app): ...
```

Hosted mode stores data in `~/.pythonos` and uses Qt/host APIs. Native mode
will map the same calls to Linux filesystems, `/proc`, devices and OpenRC
services. A phone backend can later implement touch, rotation, battery and
mobile navigation without rewriting applications.

## Hosted filesystem

Hosted mode defaults to a private virtual home:

```text
~/.pythonos/
├── files/
├── apps/
├── config/
└── cache/
```

The boundary is intentional. PythonOS apps should not silently treat the
host's real root or home directory as their own. Explicit host filesystem
access can be exposed later through permissions.

## Boot and build pipeline

```text
make rootfs
  curl Alpine minirootfs + LTS kernel
  chroot apk add python3 openrc

make iso
  copy system/ into /tmp/pyrootfs
  configure OpenRC runlevel links
  install PythonOS interpreter wrapper
  mkinitfs + Alpine initramfs-init → release/initramfs-installed
  cpio + gzip → release/initramfs-lts (live desktop)
  xorriso + isolinux → release/pythonos-0.1.iso

make test
  QEMU → live BusyBox init → OpenRC → pythonos service
  selftest --guest → reboot(2)

make test-installed
  QEMU → installed initramfs → root UUID mount → switch_root
  OpenRC → pythonos service → selftest --guest → reboot(2)
```

The interpreter wrapper defaults `PYTHONHASHSEED=0` because an initramfs can
start before the kernel's random number generator is seeded. This protects
early Python startup even though Python is no longer PID 1.
