# Building PythonOS

PythonOS has a hosted desktop and a native Alpine image. The hosted desktop
is the fast development path; the native image proves the Alpine/OpenRC
system path.

## Hosted desktop

Python 3.9 or newer is supported.

Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
pythonos-desktop
```

Windows PowerShell:

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pythonos-desktop
```

Activation is optional on Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pythonos.desktop.main
```

The requirements file installs PySide6-Essentials and the repository in
editable mode, which provides the `pythonos-desktop` command. To run without
installing the console script:

```sh
python -m pythonos.desktop.main
```

Headless/CI smoke test:

```sh
QT_QPA_PLATFORM=offscreen python -m pythonos.desktop.main --smoke-test
make desktop-shot
```

## Ready-made ISO for end users

Contributors are not required to build the distribution just to run it.
Download `pythonos-0.1.iso` from the
[latest GitHub Release](https://github.com/ilovelinux774/Pythonos-lfs/releases/latest).
It already contains Alpine, OpenRC, PythonOS, Xorg, PySide6, the matching
kernel and the native desktop runtime.

```sh
qemu-system-x86_64 -m 768 -smp 1 -vga std -cdrom pythonos-0.1.iso
```

VirtualBox users should allocate at least 768 MB RAM and 128 MB video memory,
select the `VMSVGA` graphics controller, and disable 3D Acceleration for the
first boot. The GUI profile keeps `vmwgfx` and `vboxvideo` kernel modules, enables
eudev/libinput mouse hotplug discovery, the Xorg vmmouse fallback for
VirtualBox's PS/2 pointer, and Xorg VMware/VESA fallbacks in addition to the
QEMU graphics path.

The workflow also publishes the same ISO as a downloadable artifact on every
successful `main` build. The contributor build instructions below are only
needed when changing or reproducing the image.

## Native disk installer

The GUI profile includes an **Install PythonOS** desktop application and the
`pythonos-installer` tty command. Both expose wipe-and-install, manual
partitioning, detected-OS dual-boot, and an advanced guide. Detection is
read-only and disk writes require confirmation.

Dual-boot mode preserves Windows/Linux partitions and uses a pre-created free
Linux partition plus an EFI System Partition when booted in UEFI mode. It does
not automatically shrink an existing OS in this first safe implementation.
Automatic partition resizing remains unimplemented; prepare free space with a
trusted partition editor before starting the installer.
Review before writing:

```sh
sudo pythonos-installer disks
sudo pythonos-installer detect
sudo pythonos-installer plan --mode dualboot --root /dev/sda3 --esp /dev/sda1
sudo pythonos-installer install --mode dualboot --root /dev/sda3 --esp /dev/sda1 --yes
```

For a blank disk, replace the final commands with
`sudo pythonos-installer install --mode wipe --disk /dev/sda --yes`.
Back up important data before changing partitions.

## Native Alpine image

### Requirements

* x86_64 Linux host
* `curl`, `cpio`, `gzip`, `xorriso`, `isolinux`, `syslinux-common`
* `qemu-system-x86`
* `sudo` for the one-time rootfs chroot

Debian/Ubuntu:

```sh
sudo apt install qemu-system-x86 cpio xorriso curl gzip isolinux syslinux-common
```

### 1. Stage Alpine, Python and OpenRC

```sh
sudo builder/prepare_rootfs.sh
```

This downloads Alpine's x86_64 minirootfs and LTS kernel into `.cache-dl/`,
unpacks the rootfs to `/tmp/pyrootfs`, and installs `python3 openrc` with
Alpine's `apk`. Alpine supplies the low-level C plumbing and service manager;
PythonOS supplies the framework and userland.

The normal image stays console-first and is useful on systems without a
GUI profile. To stage the native Xorg + PySide6 profile, use:

```sh
make rootfs-gui    # clean Alpine GUI rootfs in .build/pyrootfs
make iso-gui       # matching-kernel initramfs and hybrid ISO
make test          # OpenRC/PythonOS guest self-test
make run-iso       # graphical QEMU boot (use -vga std when invoking QEMU directly)
```

The GUI profile installs Alpine's `linux-lts`, then removes firmware and
unneeded Qt/PySide6/developer payload while retaining the DRM, AGP/TTM,
virtio, input and HID module families. The builder selects
`.build/pyrootfs/boot/vmlinuz-lts` for this profile, preventing a kernel/module
release mismatch. The builder enables `pythonos-gui` automatically when
`startx` is present; OpenRC still leaves the tty1 and serial getty fallback
available if Xorg or the desktop needs debugging. The
`PYTHONOS_ROOTFS` environment variable can also point both scripts at a
larger disk-backed staging directory.

### 2. Build the initramfs and ISO

```sh
sudo python3 builder/build.py
```

The builder overlays `system/`, installs the early-boot Python interpreter
wrapper, creates OpenRC runlevel links, packs the initramfs and assembles a
hybrid ISO with isolinux.

Useful flags:

```sh
sudo python3 builder/build.py --no-iso       # initramfs only
sudo python3 builder/build.py --no-initramfs # reuse existing initramfs
```

Builds run in about eight seconds after the rootfs is staged.

### 3. Boot and test

```sh
make test
```

The harness boots with:

```text
console=ttyS0 rdinit=/init pythonos.selftest=1
```

`/init` is a compatibility shell wrapper that execs Alpine's `/sbin/init`.
BusyBox init starts OpenRC; OpenRC starts the `pythonos` service; the service
runs the self-test and powers off. The test expects:

```text
SELFTEST PASSED — 22 passed, 0 failed
```

The log is written to `release/boot-selftest.log`.

### 4. Run the native image interactively

```sh
make run
```

The normal console profile prints the PythonOS report, then OpenRC's getty
presents a login prompt on the serial console and tty1. The root login shell
is `pysh`. In a GUI-profile image, OpenRC also starts `pythonos-gui` and the
shared Python desktop; the two gettys remain available as a fallback.

To boot the ISO in a graphical QEMU window:

```sh
make run-iso
```

### 5. Capture proof screens

```sh
make shots
```

The QEMU monitor captures the native console tour. The hosted desktop image
can be regenerated independently with `make desktop-shot`.

## USB image

```sh
sudo dd if=release/pythonos-0.1.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Double-check `/dev/sdX` before running this command.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pythonos-desktop: command not found` | hosted package not installed | run `python -m pip install -r requirements.txt` |
| Qt platform plugin error | no host display | use a graphical session or `QT_QPA_PLATFORM=offscreen ... --smoke-test` |
| `openrc: not found` in the image | old rootfs staged before OpenRC support | run `sudo builder/prepare_rootfs.sh` again |
| `SELFTEST FAILED` | native service or filesystem issue | inspect `release/boot-selftest.log`; boot with `rdinit=/bin/sh` |
| kernel missing | cache was removed | run `make rootfs` |

Debug shell:

```sh
qemu-system-x86_64 -m 768 -nographic \
  -kernel .build/pyrootfs/boot/vmlinuz-lts \
  -initrd release/initramfs-lts \
  -append "console=ttyS0 rdinit=/bin/sh"
```
