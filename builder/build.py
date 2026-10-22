#!/usr/bin/env python3
"""PythonOS image builder.

Takes the prepared Alpine minirootfs + the PythonOS system tree and
produces:

    release/initramfs-lts          the live PythonOS root filesystem (cpio.gz)
    release/initramfs-installed    the small disk-root initramfs
    release/pythonos-0.1.iso       a bootable hybrid ISO

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
ROOTFS = os.environ.get("PYTHONOS_ROOTFS", "/tmp/pyrootfs")
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
    "etc/init.d/pythonos",
    "etc/init.d/pythonos-gui",
    "usr/bin/pythonos-gui",
    "usr/bin/pysh",
    "usr/bin/pyfetch",
    "usr/bin/pytop",
    "usr/bin/pyedit",
    "usr/bin/pkg",
    "usr/bin/pythonos-installer",
)

ALWAYS_MKDIR = (
    "proc", "sys", "dev", "dev/pts", "tmp", "run",
    "root", "boot",
    "var", "var/lib", "var/lib/pythonos", "var/lib/pythonos/pkg",
    "usr/lib/pythonos/apps",
    "usr/share/pythonos/repo",
    "etc/runlevels/sysinit", "etc/runlevels/boot", "etc/runlevels/default",
    "etc/runlevels/shutdown",
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


def configure_openrc():
    """Create Alpine/OpenRC runlevel links in the staged image.

    The minirootfs intentionally has empty runlevels. Keeping this explicit
    makes the image reproducible and avoids depending on the host's rc-update
    command or on package post-install scripts running outside a real boot.
    """
    default_services = ["pythonos"]
    if os.path.exists(os.path.join(ROOTFS, "usr/bin/startx")):
        default_services.append("pythonos-gui")

    sysinit_services = ["devfs", "procfs", "sysfs"]
    boot_services = ["hostname", "bootmisc", "localmount"]
    # The GUI profile includes eudev so Xorg/libinput can discover hotplugged
    # VirtualBox and USB mouse devices. Keep the console-only profile free of
    # the extra daemon and only link services that are actually installed.
    if os.path.exists(os.path.join(ROOTFS, "etc/init.d/udev")):
        sysinit_services.append("udev")
    if os.path.exists(os.path.join(ROOTFS, "etc/init.d/udev-trigger")):
        boot_services.append("udev-trigger")
    if os.path.exists(os.path.join(ROOTFS, "etc/init.d/udev-settle")):
        boot_services.append("udev-settle")

    runlevels = {
        "sysinit": tuple(sysinit_services),
        "boot": tuple(boot_services),
        "default": tuple(default_services),
        "shutdown": ("killprocs", "mount-ro"),
    }
    for level, services in runlevels.items():
        directory = os.path.join(ROOTFS, "etc/runlevels", level)
        os.makedirs(directory, exist_ok=True)
        for service in services:
            link = os.path.join(directory, service)
            if os.path.lexists(link):
                os.remove(link)
            target = f"/etc/init.d/{service}"
            os.symlink(target, link)


def overlay_rootfs():
    system = os.path.join(BASE, "system")
    for entry in sorted(os.listdir(system)):
        src = os.path.join(system, entry)
        dst = os.path.join(ROOTFS, entry)
        copy_tree(src, dst)

    # The hosted desktop is the canonical graphical framework. Merge only its
    # desktop package into the native PythonOS package; keep the native shell,
    # boot helpers and tools from system/ alongside it.
    hosted_desktop = os.path.join(BASE, "pythonos", "desktop")
    native_desktop = os.path.join(ROOTFS, "usr/lib/pythonos/desktop")
    copy_tree(hosted_desktop, native_desktop)

    # The installer backend is shared by the hosted source tree and the
    # native image. Keep it beside the native PythonOS package so both the Qt
    # installer and the tty CLI use exactly the same safety checks.
    installer_backend = os.path.join(BASE, "pythonos", "installer.py")
    copy_tree(installer_backend, os.path.join(ROOTFS, "usr/lib/pythonos/installer.py"))

    for relative in EXECUTABLES:
        path = os.path.join(ROOTFS, relative)
        if os.path.exists(path):
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    for relative in ALWAYS_MKDIR:
        os.makedirs(os.path.join(ROOTFS, relative), exist_ok=True)
    os.chmod(os.path.join(ROOTFS, "tmp"), 0o1777)

    configure_openrc()

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
        fh.write("PythonOS 0.1 Constrictor · Alpine · OpenRC\n")


PYTHONOS_INITRAMFS_PREFIX = r'''#!/bin/sh
# PythonOS additions to Alpine's mkinitfs initramfs-init.
#
# The normal boot path below is kept from Alpine so root discovery, UUIDs,
# storage modules and switch_root stay compatible with the kernel package.
# This prefix adds an explicit recovery shell before that path starts.

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PS1='[pythonos-initramfs] # '

pythonos_cmdline_has()
{
    [ -r /proc/cmdline ] || {
        mkdir -p /proc
        mount -t proc -o nosuid,nodev,noexec proc /proc 2>/dev/null || true
    }
    for pythonos_arg in $(cat /proc/cmdline 2>/dev/null); do
        [ "$pythonos_arg" = "$1" ] && return 0
    done
    return 1
}

pythonos_recovery_mounts()
{
    mkdir -p /dev /dev/pts /proc /sys /run /tmp /newroot
    mount -t devtmpfs -o nosuid,mode=0755 devtmpfs /dev 2>/dev/null || true
    mount -t proc -o nosuid,nodev,noexec proc /proc 2>/dev/null || true
    mount -t sysfs -o nosuid,nodev,noexec sysfs /sys 2>/dev/null || true
    mount -t devpts -o nosuid,noexec,gid=5,mode=0620 devpts /dev/pts 2>/dev/null || true
    mount -t tmpfs -o nosuid,nodev,mode=0755 tmpfs /run 2>/dev/null || true
    mdev -s 2>/dev/null || true
}

pythonos_debug_shell()
{
    pythonos_recovery_mounts
    echo
    echo "PythonOS initramfs emergency shell"
    echo "The normal boot will continue when you type 'exit'."
    echo "Useful commands: dmesg, ls /dev, blkid, lsblk, modprobe, mount, fsck"
    echo "The installed root is not modified automatically."
    echo
    /bin/busybox sh
    # Return control to Alpine's normal init script with its expected clean
    # mount namespace. User-created mounts elsewhere are left untouched.
    umount -l /dev/pts /run /sys /proc /dev 2>/dev/null || true
}

if pythonos_cmdline_has pythonos.debug=1 || pythonos_cmdline_has pythonos.emergency=1; then
    pythonos_debug_shell
fi
'''


def build_installed_initramfs():
    """Build the small disk-root initramfs used after installation.

    The live image is intentionally a complete PythonOS root filesystem. An
    installed machine must not boot that image as its root, so use Alpine's
    mkinitfs to collect only the early-boot tools, storage/filesystem module
    families, and Alpine's proven UUID mount + switch_root implementation.
    """
    os.makedirs(RELEASE, exist_ok=True)
    modules_dir = os.path.join(ROOTFS, "lib", "modules")
    versions = sorted(
        name for name in os.listdir(modules_dir) if os.path.isdir(os.path.join(modules_dir, name))
    ) if os.path.isdir(modules_dir) else []
    mkinitfs = os.path.join(ROOTFS, "sbin", "mkinitfs")
    default_init = os.path.join(ROOTFS, "usr", "share", "mkinitfs", "initramfs-init")
    out = os.path.join(RELEASE, "initramfs-installed")
    generated_inside = "/tmp/pythonos-initramfs-installed"

    if not os.path.isfile(mkinitfs) or not os.path.isfile(default_init):
        raise RuntimeError(
            "Cannot build the installed initramfs: mkinitfs is missing from the staged rootfs"
        )

    # The GUI profile has a matching linux-lts module tree. The small console
    # profile deliberately has no kernel package, so ask mkinitfs for a
    # no-module image there instead of silently reusing the large live image.
    # The console profile continues to use Alpine's netboot kernel, whose
    # common storage/filesystem drivers are built in or supplied by its normal
    # boot path; the authoritative installed image is the GUI profile.
    version = versions[0] if versions else None
    custom_init = os.path.join(ROOTFS, "tmp", "pythonos-initramfs-init")
    config = os.path.join(ROOTFS, "tmp", "pythonos-mkinitfs.conf")
    recovery_feature = os.path.join(
        ROOTFS, "etc", "mkinitfs", "features.d", "pythonos-recovery.files"
    )
    switch_root_path = os.path.join(ROOTFS, "sbin", "switch_root")
    switch_root_backup = os.path.join(ROOTFS, "tmp", "pythonos-switch-root-real")
    switch_root_replaced = False
    switch_root_had_original = os.path.lexists(switch_root_path)
    os.makedirs(os.path.dirname(custom_init), exist_ok=True)
    os.makedirs(os.path.dirname(recovery_feature), exist_ok=True)
    # Alpine's initramfs-init uses the BusyBox switch_root applet's -c
    # console option. util-linux also ships a different switch_root binary;
    # temporarily expose the expected applet at the path used in the image.
    if switch_root_had_original:
        os.rename(switch_root_path, switch_root_backup)
    os.symlink("/bin/busybox", switch_root_path)
    switch_root_replaced = True
    with open(custom_init, "w", encoding="utf-8") as fh:
        fh.write(PYTHONOS_INITRAMFS_PREFIX)
        fh.write("\n")
        with open(default_init, "r", encoding="utf-8") as source:
            fh.write(source.read())
    os.chmod(custom_init, 0o755)
    with open(recovery_feature, "w", encoding="utf-8") as fh:
        # Alpine's base feature intentionally contains only the files needed
        # for its normal path. The debug shell should be useful, so add the
        # BusyBox applet links plus safe inspection/mount/fsck utilities.
        fh.write(
            "\n".join([
                "/bin/*",
                "/usr/bin/awk",
                "/usr/bin/readlink",
                "/usr/bin/sort",
                "/usr/bin/which",
                "/sbin/blkid",
                "/sbin/e2fsck",
                "/sbin/findfs",
                "/sbin/fsck",
                "/sbin/fsck.ext2",
                "/sbin/fsck.ext3",
                "/sbin/fsck.ext4",
                "/sbin/mdev",
                "/sbin/nlplug-findfs",
                "/sbin/switch_root",
                "",
            ])
        )
    with open(config, "w", encoding="utf-8") as fh:
        fh.write(
            'features="base ata btrfs ext2 ext3 ext4 f2fs mmc nvme scsi usb virtio xfs pythonos-recovery"\n'
        )

    try:
        mkinitfs_command = [
            "chroot", ROOTFS, "/sbin/mkinitfs",
            "-c", "/tmp/pythonos-mkinitfs.conf",
            "-i", "/tmp/pythonos-initramfs-init",
            "-o", generated_inside,
        ]
        if version:
            mkinitfs_command.append(version)
        else:
            mkinitfs_command.insert(3, "-n")
        run(mkinitfs_command)
        shutil.copy2(os.path.join(ROOTFS, generated_inside.lstrip("/")), out)
        os.chmod(out, 0o644)
    finally:
        for path in (
            custom_init,
            config,
            recovery_feature,
            os.path.join(ROOTFS, generated_inside.lstrip("/")),
        ):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        if switch_root_replaced:
            try:
                os.unlink(switch_root_path)
            except FileNotFoundError:
                pass
            if switch_root_had_original:
                os.rename(switch_root_backup, switch_root_path)
    return out


def build_initramfs():
    os.makedirs(RELEASE, exist_ok=True)
    out = os.path.join(RELEASE, "initramfs-lts")
    cmd = (f"cd {ROOTFS} && find . "
           f"-path './boot/vmlinuz-lts' -prune -o "
           f"-path './boot/initramfs-lts' -prune -o "
           f"-path './boot/initramfs-installed' -prune -o "
           f"-path './boot/System.map-*' -prune -o "
           f"-path './boot/config-*' -prune -o -print0 | "
           f"LC_ALL=C sort -z | cpio --null -o -H newc 2>/dev/null | "
           f"gzip -9 > {out}")
    run(cmd)
    return out


def kernel_source():
    """Return the kernel matching the staged rootfs when one is present.

    The native GUI profile installs Alpine's ``linux-lts`` package so its
    DRM/input modules match the kernel. The small console profile has no
    modules and continues to use the cached netboot kernel.
    """
    staged = os.path.join(ROOTFS, "boot", "vmlinuz-lts")
    return staged if os.path.isfile(staged) else KERNEL_SRC


def build_iso(initramfs, installed_initramfs):
    kernel = kernel_source()
    if not os.path.exists(kernel):
        sys.exit(f"error: kernel missing at {kernel}\n"
                 f"       run builder/prepare_rootfs.sh first (it downloads it)")
    if not os.path.exists(installed_initramfs):
        sys.exit(f"error: installed initramfs missing at {installed_initramfs}")
    step("Assembling ISO tree")
    if os.path.isdir(ISO_STAGE):
        shutil.rmtree(ISO_STAGE)
    boot_dir = os.path.join(ISO_STAGE, "boot")
    isolinux_dir = os.path.join(ISO_STAGE, "isolinux")
    os.makedirs(boot_dir)
    os.makedirs(isolinux_dir)

    shutil.copy2(kernel, os.path.join(boot_dir, "vmlinuz-lts"))
    shutil.copy2(initramfs, os.path.join(boot_dir, "initramfs-lts"))
    # The live initramfs is deliberately not used by a disk installation.
    # Ship the small storage/root-mount image as installer input only; it is
    # copied to the target /boot by pythonos-installer.
    shutil.copy2(installed_initramfs, os.path.join(boot_dir, "initramfs-installed"))
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
            "  qemu-system-x86_64 -m 768 -cdrom pythonos-0.1.iso\n\n"
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
    installed_initramfs = None
    if not args.no_initramfs:
        step("Packing live initramfs")
        installed_initramfs = build_installed_initramfs()
        initramfs = build_initramfs()
        print(f"    {initramfs}  ({human(initramfs)})")
        print(f"    {installed_initramfs}  ({human(installed_initramfs)})")
    elif not args.no_iso:
        initramfs = os.path.join(RELEASE, "initramfs-lts")
        installed_initramfs = os.path.join(RELEASE, "initramfs-installed")
        if not os.path.exists(initramfs) or not os.path.exists(installed_initramfs):
            sys.exit("error: --no-initramfs requires existing live and installed initramfs files")

    iso = None
    if not args.no_iso and initramfs:
        iso = build_iso(initramfs, installed_initramfs)

    hand_back_ownership()

    elapsed = time.time() - started
    print("\nBuild complete in %.1fs" % elapsed)
    if initramfs:
        print(f"  initramfs : {initramfs}  ({human(initramfs)})")
    if iso:
        print(f"  ISO       : {iso}  ({human(iso)})")
    print("\n  Boot it:  qemu-system-x86_64 -m 768 -cdrom "
          f"{iso or 'release/pythonos-0.1.iso'}")


if __name__ == "__main__":
    main()
