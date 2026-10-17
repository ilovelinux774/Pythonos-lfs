# Building PythonOS

## Requirements

* x86_64 Linux host (Debian/Ubuntu and Alpine both work)
* `gcc`, `curl`, `cpio`, `gzip`, `xorriso`, `qemu-system-x86_64`
* `sudo` — used once, to chroot into the staged root filesystem

```sh
sudo apt install qemu-system-x86 cpio xorriso curl
```

## One-shot build

```sh
make all        # rootfs + overlay + initramfs + ISO
```

Output:

```
release/initramfs-lts       15 MB   the PythonOS filesystem
release/pythonos-0.1.iso    27 MB   bootable hybrid ISO
```

## Step by step

### 1. Stage the root filesystem (once)

```sh
sudo builder/prepare_rootfs.sh
```

Downloads Alpine's minirootfs and kernel into `.cache-dl/` (git-ignored),
unpacks the rootfs to `/tmp/pyrootfs`, and installs Python 3.12 with
`apk` inside a chroot. This is the only package-manager step in the
entire build; it exists purely to obtain an interpreter and the kernel.

### 2. Overlay PythonOS and pack

```sh
sudo python3 builder/build.py
```

* copies `system/` over `/tmp/pyrootfs`
* installs the `PYTHONHASHSEED` interpreter wrapper and static `/dev` nodes
* packs the tree: `find . | cpio -o -H newc | gzip -9`
* builds the ISO with `xorriso` (isolinux + isohybrid MBR)

Useful flags:

```sh
sudo python3 builder/build.py --no-iso          # initramfs only, fast loop
sudo python3 builder/build.py --no-initramfs    # reuse existing initramfs
```

### 3. Boot it

```sh
make run
# or, without make:
qemu-system-x86_64 -m 512 -cdrom release/pythonos-0.1.iso
```

Serial console instead of a window:

```sh
qemu-system-x86_64 -m 512 -nographic \
  -kernel .cache-dl/vmlinuz-lts \
  -initrd release/initramfs-lts \
  -append "console=ttyS0 rdinit=/init"
```

### 4. Test it

```sh
make test       # ~30 s: boots the initramfs, expects SELFTEST PASSED
```

The log is kept at `release/boot-selftest.log`. A failing check shows the
assertion, so you can fix and rebuild in under a minute.

### 5. Screenshots

```sh
make shots      # boots with pythonos.demo=1, types into the shell, saves PNGs
```

`builder/demo_shots.py` talks to QEMU's monitor socket: it watches the
serial log for demo markers, issues `screendump`, and converts the PPM to
PNG with a pure-stdlib converter (`builder/ppm2png.py`).

## Host-side tests

No root, no QEMU:

```sh
make unittest
```

Runs `tests/test_pysh.py` — tokenizer, expansion, pipelines, redirects and
builtins — against the source tree in `system/`.

## Writing to a USB stick

```sh
sudo dd if=release/pythonos-0.1.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

The ISO is isohybrid: it boots as a CD image or as a raw disk image.
Booting from USB works on BIOS and (via the isolinux image) on most UEFI
setups with CSM; native UEFI boot is on the roadmap.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Fatal Python error: _Py_HashRandomization_Init` | interpreter wrapper missing | rebuild: `sudo python3 builder/build.py` |
| `Kernel panic … Attempted to kill init` | `/init` crashed | boot with `rdinit=/bin/sh`, check `/init`, `python3 -m pythonos.init_main` |
| Blank screen, no serial output | wrong console args | add `console=ttyS0` and run QEMU with `-nographic` |
| `prepare_rootfs.sh needs root` | chroot requires root | re-run with `sudo` |

To debug interactively:

```sh
qemu-system-x86_64 -m 512 -nographic \
  -kernel .cache-dl/vmlinuz-lts \
  -initrd release/initramfs-lts \
  -append "console=ttyS0 rdinit=/bin/sh"
```
