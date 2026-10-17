#!/usr/bin/env python3
"""PythonOS image builder.

Takes the prepared Alpine minirootfs + the PythonOS system tree and
produces:

    release/initramfs-lts     the PythonOS root filesystem (cpio.gz)
    release/pythonos-0.1.iso  a bootable hybrid ISO

Usage:
    python3 builder/build.py              # full build
    python3 builder/build.py --no-iso     # initramfs only
    python3 builder/build.py --clean      # rebuild rootfs overlay from scratch
"""

import argparse
import os
import shutil
import stat
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOTFS = "/tmp/pyrootfs"
CACHE = os.path.join(BASE, ".cache-dl")
RELEASE = os.path.join(BASE, "release")
ISO_STAGE = "/tmp/pythonos-iso"
KERNEL_SRC = os.path.join(CACHE, "vmlinuz-lts")
SYSLINUX_SEARCH = (
    "/usr/lib/ISOLINUX", "/usr/lib/syslinux", "/usr/lib/syslinux/modules/bios",
    "/usr/share/syslinux", "/usr/share/syslinux/modules/bios",
)


def find_syslinux(name):
    """Locate an isolinux/syslinux file across distro layouts."""
    candidates = [os.path.join(directory, name) for directory in SYSLINUX_SEARCH]
    candidates.append(os.path.join("/usr/lib/ISOLINUX", name))
    for path in candidates:
        if os.path.isfile(path):
            return path
    base = shutil.which("isolinux.bin")
    if base:
        return base
    for root in ("/usr/lib", "/usr/share"):
        for dirpath, _dirs, files in os.walk(root):
            if name in files and "syslinux" in dirpath.lower():
                return os.path.join(dirpath, name)
    sys.exit(
        f"error: {name} not found. Install the isolinux/syslinux package:\n"
        f"  Debian/Ubuntu: sudo apt install isolinux syslinux-common\n"
        f"  Fedora:        sudo dnf install syslinux\n"
        f"  Alpine:        sudo apk add syslinux"
    )

EXECUTABLES = (
    "init",
    "usr/bin/pysh",
    "usr/bin/pyfetch",
    "usr/bin/pytop",
    "usr/bin/pyedit",
    "usr/bin/pkg",
)

ALWAYS_MKDIR = (
    "proc", "sys", "dev", "dev/pts", "tmp", "run",
    "root", "boot",
    "var", "var/lib", "var/lib/pythonos", "var/lib/pythonos/pkg",
    "usr/lib/pythonos/apps",
    "usr/share/pythonos/repo",
)


def step(title):
    print(f"\n==> {title}")


def run(cmd, **kwargs):
    printable = cmd if isinstance(cmd, str) else " ".join(cmd)
    print(f"    $ {printable}")
    subprocess.run(cmd, shell=isinstance(cmd, str), check=True, **kwargs)


def copy_tree(src, dst):
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def overlay_rootfs():
    system = os.path.join(BASE, "system")
    for entry in sorted(os.listdir(system)):
        src = os.path.join(system, entry)
        dst = os.path.join(ROOTFS, entry)
        copy_tree(src, dst)

    for relative in EXECUTABLES:
        path = os.path.join(ROOTFS, relative)
        if os.path.exists(path):
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    for relative in ALWAYS_MKDIR:
        os.makedirs(os.path.join(ROOTFS, relative), exist_ok=True)
    os.chmod(os.path.join(ROOTFS, "tmp"), 0o1777)

    for link, target in (("bin", "usr/bin"), ("sbin", "usr/sbin")):
        path = os.path.join(ROOTFS, link)
        if not os.path.exists(path):
            os.symlink(target, path)

    # The interpreter wrapper: booting from an initramfs means the kernel
    # can start us before the CRNG is seeded. CPython aborts when it cannot
    # randomise its hash seed, so give it a deterministic one by default.
    py3 = os.path.join(ROOTFS, "usr/bin/python3")
    py312_guest = "/usr/bin/python3.12"
    if os.path.lexists(py3):
        os.remove(py3)
    with open(py3, "w", encoding="utf-8") as fh:
        fh.write(
            "#!/bin/sh\n"
            "# PythonOS interpreter wrapper: deterministic hash seed because\n"
            "# PID 1 may start before the kernel CRNG has been seeded.\n"
            "PYTHONHASHSEED=${PYTHONHASHSEED:-0}\n"
            "export PYTHONHASHSEED\n"
            f'exec "{py312_guest}" "$@"\n'
        )
    os.chmod(py3, 0o755)
    py = os.path.join(ROOTFS, "usr/bin/python")
    if os.path.lexists(py):
        os.remove(py)
    os.symlink("python3", py)

    # Static device nodes so early-boot code has console/null/random even
    # before devtmpfs is mounted.
    for name, major, minor, mode in (
        ("console", 5, 1, 0o600),
        ("null", 1, 3, 0o666),
        ("zero", 1, 5, 0o666),
        ("urandom", 1, 9, 0o444),
        ("tty1", 4, 1, 0o620),
    ):
        node = os.path.join(ROOTFS, "dev", name)
        if os.path.exists(node):
            continue
        try:
            os.mknod(node, stat.S_IFCHR | mode, os.makedev(major, minor))
        except (PermissionError, FileExistsError, OSError):
            pass

    # Drop the package cache metadata; it is not useful in a live image.
    for junk in ("var/cache/apk", "usr/lib/python3.12/__pycache__"):
        path = os.path.join(ROOTFS, junk)
        if os.path.isdir(path):
            shutil.rmtree(path)

    # A tiny marker so pyfetch can tell it is running from the image.
    with open(os.path.join(ROOTFS, "etc/pythonos-release"), "w", encoding="utf-8") as fh:
        fh.write("PythonOS 0.1 Constrictor\n")


def build_initramfs():
    os.makedirs(RELEASE, exist_ok=True)
    out = os.path.join(RELEASE, "initramfs-lts")
    cmd = (f"cd {ROOTFS} && find . -print0 | LC_ALL=C sort -z | "
           f"cpio --null -o -H newc 2>/dev/null | gzip -9 > {out}")
    run(cmd)
    return out


def build_iso(initramfs):
    if not os.path.exists(KERNEL_SRC):
        sys.exit(f"error: kernel missing at {KERNEL_SRC}\n"
                 f"       run builder/prepare_rootfs.sh first (it downloads it)")
    step("Assembling ISO tree")
    if os.path.isdir(ISO_STAGE):
        shutil.rmtree(ISO_STAGE)
    boot_dir = os.path.join(ISO_STAGE, "boot")
    isolinux_dir = os.path.join(ISO_STAGE, "isolinux")
    os.makedirs(boot_dir)
    os.makedirs(isolinux_dir)

    shutil.copy2(KERNEL_SRC, os.path.join(boot_dir, "vmlinuz-lts"))
    shutil.copy2(initramfs, os.path.join(boot_dir, "initramfs-lts"))
    shutil.copy2(find_syslinux("isolinux.bin"), os.path.join(isolinux_dir, "isolinux.bin"))
    shutil.copy2(find_syslinux("ldlinux.c32"), os.path.join(isolinux_dir, "ldlinux.c32"))
    isohdpfx = find_syslinux("isohdpfx.bin")

    with open(os.path.join(isolinux_dir, "isolinux.cfg"), "w", encoding="utf-8") as fh:
        fh.write(
            "DEFAULT pythonos\n"
            "PROMPT 1\n"
            "TIMEOUT 10\n"
            "TOTALTIMEOUT 60\n"
            "\n"
            "LABEL pythonos\n"
            "  MENU LABEL PythonOS 0.1 (Constrictor)\n"
            "  KERNEL /boot/vmlinuz-lts\n"
            "  INITRD /boot/initramfs-lts\n"
            "  APPEND console=tty0 console=ttyS0,115200 quiet loglevel=3\n"
            "\n"
            "LABEL selftest\n"
            "  MENU LABEL PythonOS self-test (serial console)\n"
            "  KERNEL /boot/vmlinuz-lts\n"
            "  INITRD /boot/initramfs-lts\n"
            "  APPEND console=ttyS0,115200 quiet loglevel=3 pythonos.selftest=1\n"
            "\n"
            "LABEL demo\n"
            "  MENU LABEL PythonOS guided demo\n"
            "  KERNEL /boot/vmlinuz-lts\n"
            "  INITRD /boot/initramfs-lts\n"
            "  APPEND console=tty0 console=ttyS0,115200 quiet loglevel=3 pythonos.demo=1\n"
        )

    with open(os.path.join(ISO_STAGE, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(
            "PythonOS 0.1 \"Constrictor\"\n"
            "A Linux distribution whose userland is Python.\n\n"
            "Boot it in QEMU:\n"
            "  qemu-system-x86_64 -m 512 -cdrom pythonos-0.1.iso\n\n"
            "Boot it on real hardware: write the ISO to a USB stick\n"
            "  dd if=pythonos-0.1.iso of=/dev/sdX bs=4M status=progress\n"
        )

    step("Building ISO with xorriso")
    iso_path = os.path.join(RELEASE, "pythonos-0.1.iso")
    run([
        "xorriso", "-as", "mkisofs",
        "-o", iso_path,
        "-isohybrid-mbr", isohdpfx,
        "-c", "isolinux/boot.cat",
        "-b", "isolinux/isolinux.bin",
        "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
        "-J", "-R", "-V", "PYTHONOS_01",
        ISO_STAGE,
    ])
    return iso_path


def hand_back_ownership():
    """Builds run under sudo; make the artefacts owned by the caller."""
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")
    if not sudo_uid:
        return
    try:
        uid, gid = int(sudo_uid), int(sudo_gid)
    except (TypeError, ValueError):
        return
    for name in os.listdir(RELEASE):
        path = os.path.join(RELEASE, name)
        try:
            os.chown(path, uid, gid)
        except OSError:
            pass
    try:
        os.chown(RELEASE, uid, gid)
    except OSError:
        pass


def human(path):
    size = os.path.getsize(path)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-iso", action="store_true")
    parser.add_argument("--no-initramfs", action="store_true")
    args = parser.parse_args()

    started = time.time()
    print("PythonOS build")
    print(f"  tree:   {BASE}")
    print(f"  rootfs: {ROOTFS}")

    if not os.path.isdir(ROOTFS):
        sys.exit("error: run builder/prepare_rootfs.sh first (needs sudo)")
    if not os.path.exists(os.path.join(ROOTFS, "usr/bin/python3")):
        sys.exit("error: Python is missing from the rootfs")

    step("Overlaying PythonOS onto the rootfs")
    overlay_rootfs()

    initramfs = None
    if not args.no_initramfs:
        step("Packing initramfs")
        initramfs = build_initramfs()
        print(f"    {initramfs}  ({human(initramfs)})")

    iso = None
    if not args.no_iso and initramfs:
        iso = build_iso(initramfs)

    hand_back_ownership()

    elapsed = time.time() - started
    print("\nBuild complete in %.1fs" % elapsed)
    if initramfs:
        print(f"  initramfs : {initramfs}  ({human(initramfs)})")
    if iso:
        print(f"  ISO       : {iso}  ({human(iso)})")
    print("\n  Boot it:  qemu-system-x86_64 -m 512 -cdrom "
          f"{iso or 'release/pythonos-0.1.iso'}")


if __name__ == "__main__":
    main()
