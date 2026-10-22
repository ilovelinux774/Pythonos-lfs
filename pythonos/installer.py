"""Safe PythonOS disk installer backend.

The installer is intentionally usable from both the native Qt desktop and a
plain tty. Detection and planning are read-only. Disk writes require an
explicit confirmation flag in the CLI or a second confirmation dialog in the
GUI.

Supported install modes:

* ``wipe``: create a fresh GPT/MBR layout on a selected disk;
* ``manual``: install to partitions prepared by the user;
* ``dualboot``: preserve detected operating systems and install into a
  pre-created free Linux partition. It does not silently resize or erase an
  existing OS.

Automatic partition resizing/shrinking is not implemented by this first
installer. Users who need that path must use the advanced guide and prepare
free space with the partition editor of their choice before returning here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


# OpenRC may start the GUI with a reduced PATH.  Installer utilities are
# intentionally split across /sbin and /usr/sbin in Alpine.
os.environ["PATH"] = ":".join(
    part for part in ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin", os.environ.get("PATH", "")) if part
)


INSTALLER_ROOT = Path("/mnt/pythonos-installer")
ISO_MOUNT = INSTALLER_ROOT / "iso"
ROOT_MOUNT = INSTALLER_ROOT / "target"
SKIP_ROOT = {"proc", "sys", "dev", "run", "tmp", "mnt", "media", "boot"}


class InstallerError(RuntimeError):
    """A safe, user-facing installer error."""


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command without invoking a shell."""
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise InstallerError(f"Required command is missing: {command[0]}") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise InstallerError(f"{' '.join(command)} failed: {detail or result.returncode}")
    return result


def _require_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise InstallerError("The installer must run as root. Use sudo on a tty.")


def _size(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def format_bytes(value: int) -> str:
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{value} B"


def _mountpoints(item: dict[str, Any]) -> list[str]:
    value = item.get("mountpoints") or item.get("mountpoint") or []
    if isinstance(value, str):
        return [value] if value else []
    return [str(path) for path in value if path]


def _normalise_block(item: dict[str, Any]) -> dict[str, Any]:
    path = item.get("path") or (f"/dev/{item.get('name')}" if item.get("name") else "")
    children = [_normalise_block(child) for child in item.get("children", []) or []]
    return {
        "name": item.get("name", Path(path).name),
        "path": path,
        "type": item.get("type", ""),
        "size": _size(item.get("size")),
        "size_human": format_bytes(_size(item.get("size"))),
        "fstype": item.get("fstype") or "",
        "label": item.get("label") or "",
        "partlabel": item.get("partlabel") or "",
        "mountpoints": _mountpoints(item),
        "model": item.get("model") or "",
        "rm": bool(item.get("rm")),
        "ro": bool(item.get("ro")),
        "children": children,
    }


def detect_disks() -> list[dict[str, Any]]:
    """Return disks and partitions using util-linux lsblk JSON output."""
    result = _run(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--paths",
            "--output",
            "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,PARTLABEL,MOUNTPOINTS,MODEL,RM,RO",
        ]
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise InstallerError("lsblk returned invalid JSON") from exc
    return [_normalise_block(item) for item in data.get("blockdevices", []) if item.get("type") == "disk"]


def _partitions(disks: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for disk in disks if disks is not None else detect_disks():
        result.extend(disk.get("children", []))
    return result


def _parse_os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def _filesystem_os(partition: dict[str, Any]) -> dict[str, str] | None:
    """Read /etc/os-release from a Linux partition without modifying it."""
    path = partition.get("path", "")
    if not path or not os.geteuid() == 0:
        return None
    mount_parent = "/run" if Path("/run").is_dir() else "/tmp"
    mount_dir = Path(tempfile.mkdtemp(prefix="pythonos-os-", dir=mount_parent))
    mounted = False
    try:
        result = _run(["mount", "-o", "ro,nosuid,nodev,noexec", path, str(mount_dir)], check=False)
        if result.returncode:
            return None
        mounted = True
        release = mount_dir / "etc/os-release"
        if not release.exists():
            return None
        return _parse_os_release(release.read_text(encoding="utf-8", errors="replace"))
    finally:
        if mounted:
            _run(["umount", "-l", str(mount_dir)], check=False)
        shutil.rmtree(mount_dir, ignore_errors=True)


def detect_operating_systems(disks: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Detect common Windows and Linux installations without writing disks."""
    found: list[dict[str, Any]] = []
    for partition in _partitions(disks):
        fstype = partition.get("fstype", "").lower()
        label = f"{partition.get('label', '')} {partition.get('partlabel', '')}".lower()
        path = partition.get("path", "")
        if not path or fstype in {"swap", "vfat", "fat32"}:
            continue
        if fstype in {"ntfs", "ntfs3", "exfat", "fuseblk"} or any(
            word in label for word in ("windows", "microsoft", "basic data", "recovery")
        ):
            found.append({
                "kind": "Windows",
                "path": path,
                "description": f"Windows or Microsoft data ({partition.get('size_human', '?')})",
            })
            continue
        if fstype in {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs"}:
            release = _filesystem_os(partition) or {}
            linux_label = any(
                word in label
                for word in ("linux", "root", "ubuntu", "debian", "fedora", "arch", "alpine", "mint", "manjaro")
            )
            # A blank, unmounted ext4 partition is the supported dual-boot
            # target and must not be mistaken for an installed Linux system.
            # Root detection normally reads os-release; labels provide a
            # useful fallback when a partition is not mountable right now.
            if not release and not linux_label:
                continue
            name = release.get("PRETTY_NAME") or release.get("NAME") or "Linux installation"
            found.append({
                "kind": "Linux",
                "path": path,
                "description": f"{name} ({partition.get('size_human', '?')})",
            })
    return found


def _find_partition(path: str, disks: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    for partition in _partitions(disks):
        if partition.get("path") == path:
            return partition
    return None


def validate_dualboot_target(
    root_device: str,
    detected_systems: list[dict[str, str]],
    *,
    disks: list[dict[str, Any]] | None = None,
) -> None:
    """Refuse to use a detected OS partition as a dual-boot target.

    Dual boot is deliberately limited to a user-prepared, unmounted Linux
    partition. There is no safe way to infer that an existing Linux root may
    be overwritten merely because the user selected the dual-boot button.
    """
    partition = _find_partition(root_device, disks)
    if partition is None:
        raise InstallerError(f"Dual-boot root partition was not found: {root_device}")
    if root_device in {item.get("path") for item in detected_systems}:
        raise InstallerError(
            f"Refusing to overwrite the detected operating system on {root_device}; "
            "prepare a separate free Linux partition first"
        )
    if _mounted(partition):
        raise InstallerError(f"Refusing to use a mounted dual-boot target: {root_device}")
    fstype = str(partition.get("fstype", "")).lower()
    if fstype not in {"", "ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs"}:
        raise InstallerError(
            f"Dual-boot needs a prepared Linux filesystem on {root_device}; found {fstype or 'unknown'}"
        )


def _validate_device(path: str, *, disk: bool = False) -> str:
    if not path.startswith("/dev/") or any(char in path for char in "\n\r\t "):
        raise InstallerError(f"Invalid device path: {path!r}")
    real_path = os.path.realpath(path)
    if not real_path.startswith("/dev/") or real_path == "/dev":
        raise InstallerError(f"Invalid device path: {path!r}")
    device = Path(real_path)
    if device.exists():
        if not stat.S_ISBLK(device.stat().st_mode):
            raise InstallerError(f"Not a block device: {path}")
    elif not (Path("/sys/class/block") / device.name / "dev").exists():
        raise InstallerError(f"Device does not exist: {path}")
    if disk and device.name.startswith(("sr", "loop", "dm-", "md")):
        raise InstallerError("That device is not a whole install disk")
    return path


def _mounted(partition: dict[str, Any] | None) -> bool:
    return bool(partition and partition.get("mountpoints"))


def _wait_for_partitions(disk: str | None = None) -> None:
    if disk:
        _run(["blockdev", "--rereadpt", disk], check=False)
        _run(["partx", "--add", disk], check=False)
    _run(["partprobe"], check=False)
    if disk:
        _run(["partx", "--add", disk], check=False)
    _run(["udevadm", "trigger", "--subsystem-match=block"], check=False)
    _run(["udevadm", "settle"], check=False)
    time.sleep(1)


def _load_installer_modules() -> None:
    """Load filesystems used by the installer when they are modular."""
    for module in ("ext4", "vfat", "fat", "ntfs3", "isofs", "sr_mod"):
        _run(["modprobe", module], check=False)


def _ensure_block_device(path: str) -> None:
    """Create a missing udev node from the kernel's authoritative sysfs entry."""
    device = Path(path)
    if device.exists():
        return
    sys_device = Path("/sys/class/block") / device.name / "dev"
    try:
        major, minor = (int(value) for value in sys_device.read_text(encoding="ascii").strip().split(":", 1))
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise InstallerError(f"The kernel did not expose a device node for {path}") from exc
    try:
        os.mknod(device, stat.S_IFBLK | 0o660, os.makedev(major, minor))
    except FileExistsError:
        pass
    except OSError as exc:
        raise InstallerError(f"Could not create the device node for {path}: {exc}") from exc


def _disk_partitions(path: str) -> list[dict[str, Any]]:
    for disk in detect_disks():
        if disk.get("path") == path:
            return disk.get("children", [])
    return []


def _choose_created_partitions(disk: str, boot_mode: str) -> tuple[str, str | None]:
    parts = _disk_partitions(disk)
    if not parts:
        raise InstallerError("The partition table did not produce any partitions")
    esp = next((p["path"] for p in parts if p.get("fstype") in {"vfat", "fat32"} or "efi" in p.get("partlabel", "").lower()), None)
    if boot_mode == "uefi" and not esp:
        raise InstallerError("The new UEFI layout has no EFI system partition")
    roots = [p["path"] for p in parts if p["path"] != esp]
    if not roots:
        raise InstallerError("The new layout has no root partition")
    return roots[-1], esp


def _format_partition(path: str, fstype: str) -> None:
    _validate_device(path)
    _ensure_block_device(path)
    partition = _find_partition(path)
    if partition is None:
        raise InstallerError(f"Refusing to format a device that is not a discovered partition: {path}")
    if _mounted(partition):
        raise InstallerError(f"Refusing to format a mounted partition: {path}")
    if fstype == "vfat":
        _run(["mkfs.vfat", "-F", "32", "-n", "PYTHONOS", path])
    elif fstype == "ext4":
        _run(["mkfs.ext4", "-F", "-L", "PYTHONOS", path])
    else:
        raise InstallerError(f"Unsupported filesystem format: {fstype}")
    _ensure_block_device(path)


def _wipe_and_partition(disk: str, boot_mode: str) -> tuple[str, str | None]:
    _require_root()
    _validate_device(disk, disk=True)
    disk_entry = next((item for item in detect_disks() if item.get("path") == disk), None)
    if disk_entry is None:
        raise InstallerError(f"Whole disk was not found: {disk}")
    mounted = [
        (partition.get("path"), mountpoint)
        for partition in disk_entry.get("children", [])
        for mountpoint in partition.get("mountpoints", [])
    ]
    if mounted:
        details = ", ".join(f"{path} at {mountpoint}" for path, mountpoint in mounted)
        raise InstallerError(f"Refusing to wipe a disk with mounted partitions: {details}")
    if boot_mode == "uefi":
        # Use explicit GPT type GUIDs instead of fdisk's optional shortcuts;
        # this works consistently with util-linux versions in Alpine and on
        # real UEFI hardware.
        script = (
            "label: gpt\n"
            ",512M,C12A7328-F81F-11D2-BA4B-00A0C93EC93B\n"
            ",,0FC63DAF-8483-4772-8E79-3D69D8477DE4\n"
        )
    else:
        script = "label: dos\n,,83,*\n"
    result = subprocess.run(
        ["sfdisk", "--wipe", "always", disk],
        input=script,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise InstallerError(f"Partitioning failed: {(result.stderr or result.stdout).strip()}")
    _wait_for_partitions(disk)
    parts = _disk_partitions(disk)
    for part in parts:
        _ensure_block_device(part["path"])
    if boot_mode == "uefi":
        if len(parts) < 2:
            raise InstallerError("Partitioning did not create EFI and root partitions")
        esp, root = parts[0]["path"], parts[-1]["path"]
        _format_partition(esp, "vfat")
        _format_partition(root, "ext4")
        return root, esp
    root = parts[-1]["path"]
    _format_partition(root, "ext4")
    return root, None


def _locate_install_media() -> tuple[Path, Path | None]:
    """Find the boot files on the live ISO, mounting the optical drive if needed."""
    candidates = [Path(value) for value in os.environ.get("PYTHONOS_INSTALLER_ISO", "").split(":") if value]
    candidates += [Path("/media/pythonos-iso"), Path("/run/media/pythonos-iso"), ISO_MOUNT]
    for candidate in candidates:
        if (candidate / "boot/vmlinuz-lts").exists() and (candidate / "boot/initramfs-lts").exists():
            return candidate, None
    _require_root()
    ISO_MOUNT.mkdir(parents=True, exist_ok=True)
    for device in sorted(Path("/dev").glob("sr*")):
        result = _run(["mount", "-o", "ro", str(device), str(ISO_MOUNT)], check=False)
        if result.returncode == 0 and (ISO_MOUNT / "boot/vmlinuz-lts").exists():
            return ISO_MOUNT, ISO_MOUNT
        _run(["umount", "-l", str(ISO_MOUNT)], check=False)
    raise InstallerError("The installation ISO is not mounted. Keep the PythonOS ISO inserted and try again.")


def _copy_live_root(source: Path, target: Path) -> None:
    """Copy the live system without descending into runtime pseudo-filesystems."""
    target.mkdir(parents=True, exist_ok=True)
    for name in source.iterdir():
        if name.name in SKIP_ROOT or name.name == "lost+found":
            continue
        destination = target / name.name
        # Use the native cp implementation for the large tree.  It preserves
        # symlinks and modes while avoiding Python's very slow per-file loop on
        # the live ISO's Qt and Python trees.
        _run(["cp", "-a", "--", str(name), str(destination)])


def _uuid(path: str) -> str:
    result = _run(["blkid", "-s", "UUID", "-o", "value", path], check=False)
    value = result.stdout.strip()
    if not value:
        raise InstallerError(f"Could not read the filesystem UUID for {path}")
    return value


def _write_fstab(
    root: Path,
    root_device: str,
    esp_device: str | None,
    root_fstype: str = "ext4",
) -> None:
    lines = [f"UUID={_uuid(root_device)} / {root_fstype} defaults 0 1"]
    if esp_device:
        lines.append(f"UUID={_uuid(esp_device)} /boot/efi vfat umask=0077 0 2")
    (root / "etc").mkdir(parents=True, exist_ok=True)
    (root / "etc/fstab").write_text("# Generated by the PythonOS installer.\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _existing_os_entries(
    systems: list[dict[str, str]],
    esp_uuid: str | None,
    boot_mode: str,
) -> list[str]:
    """Build chainloader/configfile entries without rewriting other OSes."""
    if not systems:
        return []
    entries: list[str] = []
    for system in systems:
        path = system.get("path", "")
        kind = system.get("kind", "Existing OS")
        if not path:
            continue
        if kind == "Windows" and boot_mode == "uefi" and esp_uuid:
            # The selected ESP is never reformatted in dual-boot mode. GRUB
            # gets a private PythonOS directory there and chainloads the
            # existing Microsoft boot manager in place.
            entries.extend([
                "menuentry 'Existing Windows' {",
                f"    search --no-floppy --fs-uuid --set=esp {esp_uuid}",
                "    chainloader (esp)/EFI/Microsoft/Boot/bootmgfw.efi",
                "}",
                "",
            ])
            continue
        try:
            uuid = _uuid(path)
        except InstallerError:
            # A stale detection result must not make the new PythonOS entry
            # unusable. The existing partition is still left untouched.
            continue
        if kind == "Linux":
            entries.extend([
                f"menuentry 'Existing Linux ({path})' {{",
                f"    search --no-floppy --fs-uuid --set=linuxroot {uuid}",
                "    configfile ($linuxroot)/boot/grub/grub.cfg",
                "}",
                "",
            ])
        else:
            entries.extend([
                f"menuentry 'Existing OS ({path})' {{",
                f"    search --no-floppy --fs-uuid --set=other {uuid}",
                "    chainloader +1",
                "}",
                "",
            ])
    return entries


def _write_grub_config(
    root: Path,
    root_device: str,
    esp_device: str | None = None,
    *,
    boot_mode: str = "bios",
    detected_systems: list[dict[str, str]] | None = None,
) -> None:
    root_uuid = _uuid(root_device)
    esp_uuid = _uuid(esp_device) if esp_device else None
    grub = root / "boot/grub"
    grub.mkdir(parents=True, exist_ok=True)
    lines = [
        "set timeout=5",
        "set default=0",
        "",
        "menuentry 'PythonOS' {",
        f"    search --no-floppy --fs-uuid --set=root {root_uuid}",
        "    linux /boot/vmlinuz-lts console=tty0 quiet loglevel=3",
        "    initrd /boot/initramfs-lts",
        "}",
        "",
    ]
    lines.extend(_existing_os_entries(detected_systems or [], esp_uuid, boot_mode))
    (grub / "grub.cfg").write_text("\n".join(lines), encoding="utf-8")


def _parent_disk(path: str) -> str | None:
    result = _run(["lsblk", "-no", "PKNAME", path], check=False)
    name = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    return f"/dev/{name}" if name else None


def _partition_number(path: str) -> str | None:
    result = _run(["lsblk", "-no", "PARTN", path], check=False)
    value = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    return value or None


def _register_uefi_entry(disk: str, esp_device: str) -> None:
    if not Path("/sys/firmware/efi").exists() or not shutil.which("efibootmgr"):
        return
    number = _partition_number(esp_device)
    if not number:
        raise InstallerError("Could not determine the EFI partition number for efibootmgr")
    result = _run([
        "efibootmgr", "--create", "--disk", disk, "--part", number,
        "--label", "PythonOS", "--loader", r"\EFI\PythonOS\grubx64.efi",
    ], check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise InstallerError(f"PythonOS was copied, but the UEFI boot entry could not be registered: {detail}")


def _install_bootloader(
    root: Path,
    esp: Path | None,
    disk: str,
    boot_mode: str,
    *,
    preserve_existing: bool = False,
) -> None:
    if not shutil.which("grub-install"):
        raise InstallerError("grub-install is missing; install the GUI profile or use the advanced manual guide")
    boot_dir = root / "boot"
    if boot_mode == "uefi":
        if esp is None:
            raise InstallerError("UEFI installation requires an EFI system partition")
        command = [
            "grub-install", "--target=x86_64-efi", "--efi-directory", str(esp),
            "--boot-directory", str(boot_dir), "--bootloader-id=PythonOS",
            "--no-nvram",
        ]
        # Only a wipe install may claim the removable-media fallback path;
        # dual-boot/manual installs get their own EFI/PythonOS directory.
        if not preserve_existing:
            command.insert(-1, "--removable")
        _run(command)
        if preserve_existing:
            _register_uefi_entry(disk, str(esp))
    else:
        _run(["grub-install", "--target=i386-pc", "--boot-directory", str(boot_dir), disk])


def install_to_partitions(
    root_device: str,
    esp_device: str | None = None,
    *,
    disk: str | None = None,
    boot_mode: str = "auto",
    preserve_existing: bool = False,
    detected_systems: list[dict[str, str]] | None = None,
) -> None:
    """Install the live PythonOS image into prepared partitions."""
    _require_root()
    _validate_device(root_device)
    if esp_device:
        _validate_device(esp_device)
    disks = detect_disks()
    root_partition = _find_partition(root_device, disks)
    esp_partition = _find_partition(esp_device, disks) if esp_device else None
    systems_to_preserve = detected_systems
    if preserve_existing and systems_to_preserve is None:
        systems_to_preserve = detect_operating_systems(disks)
    if root_partition is None:
        raise InstallerError(f"Root partition was not found: {root_device}")
    if preserve_existing:
        validate_dualboot_target(root_device, systems_to_preserve or [], disks=disks)
    if _mounted(root_partition):
        raise InstallerError("The selected root partition is already mounted")
    root_fstype = str(root_partition.get("fstype") or "ext4").lower()
    if root_fstype not in {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs"}:
        raise InstallerError(f"Unsupported Linux root filesystem: {root_fstype}")
    if boot_mode == "auto":
        boot_mode = "uefi" if esp_device else "bios"
    if boot_mode == "uefi" and not esp_device:
        raise InstallerError("UEFI installation requires an EFI System Partition")
    if boot_mode == "bios" and esp_device:
        raise InstallerError("Do not pass --esp for a legacy BIOS installation")
    if esp_device and (esp_partition is None or _mounted(esp_partition)):
        raise InstallerError("The selected EFI partition is missing or already mounted")
    if esp_partition and esp_partition.get("fstype", "").lower() not in {"vfat", "fat32"}:
        raise InstallerError("The EFI partition must be FAT32/vfat")

    root_disk = _parent_disk(root_device)
    esp_disk = _parent_disk(esp_device) if esp_device else None
    if root_disk and esp_disk and os.path.realpath(root_disk) != os.path.realpath(esp_disk):
        raise InstallerError("The root and EFI partitions must be on the same disk")
    if disk:
        _validate_device(disk, disk=True)
        if root_disk and os.path.realpath(disk) != os.path.realpath(root_disk):
            raise InstallerError("The selected install disk does not contain the root partition")
    install_disk = disk or root_disk or esp_disk
    if not install_disk:
        raise InstallerError("Could not determine the whole disk for bootloader installation")

    _load_installer_modules()
    _ensure_block_device(root_device)
    if esp_device:
        _ensure_block_device(esp_device)
    iso_root, mounted_iso = _locate_install_media()
    root_mount = ROOT_MOUNT
    esp_mount = root_mount / "boot/efi"
    root_mount.mkdir(parents=True, exist_ok=True)
    mounted_root = mounted_esp = False
    try:
        _ensure_block_device(root_device)
        _run(["mount", "-t", root_fstype, root_device, str(root_mount)])
        mounted_root = True
        esp_path: Path | None = None
        if esp_device:
            esp_mount.mkdir(parents=True, exist_ok=True)
            _run(["mount", "-t", "vfat", esp_device, str(esp_mount)])
            mounted_esp = True
            esp_path = esp_mount
        _copy_live_root(Path("/"), root_mount)
        (root_mount / "boot").mkdir(parents=True, exist_ok=True)
        shutil.copy2(iso_root / "boot/vmlinuz-lts", root_mount / "boot/vmlinuz-lts")
        shutil.copy2(iso_root / "boot/initramfs-lts", root_mount / "boot/initramfs-lts")
        _write_fstab(root_mount, root_device, esp_device, root_fstype)
        _write_grub_config(
            root_mount,
            root_device,
            esp_device,
            boot_mode=boot_mode,
            detected_systems=systems_to_preserve if preserve_existing else None,
        )
        _install_bootloader(
            root_mount,
            esp_path,
            install_disk,
            boot_mode,
            preserve_existing=preserve_existing,
        )
    finally:
        if mounted_esp:
            _run(["umount", "-l", str(esp_mount)], check=False)
        if mounted_root:
            _run(["umount", "-l", str(root_mount)], check=False)
        if mounted_iso is not None:
            _run(["umount", "-l", str(mounted_iso)], check=False)


def guide_text() -> str:
    return """PythonOS installer guide

1. Back up important data before changing partitions.
2. Use `pythonos-installer detect` to identify Windows and Linux installs.
3. Choose one of:
   - Wipe and install: erases the selected disk.
   - Partition manually: prepare an ext4 root partition and, for UEFI, a
     512 MiB FAT32 EFI System Partition.
   - Install alongside detected OS: select pre-created free space. Existing
     operating systems are preserved; this installer does not silently shrink
     them.
4. Use `pythonos-installer plan ...` before any write.
5. Only then run the matching `install` command with `--yes`.

UEFI example after preparing partitions manually:
  sudo pythonos-installer install --mode manual --root /dev/sda3 --esp /dev/sda1 --yes

Legacy BIOS example:
  sudo pythonos-installer install --mode manual --root /dev/sda3 --disk /dev/sda --boot-mode bios --yes

The graphical installer exposes the same four paths and requires a second
confirmation before writing a disk.
"""


def _print_disks(disks: list[dict[str, Any]]) -> None:
    for disk in disks:
        model = f" — {disk['model']}" if disk.get("model") else ""
        print(f"{disk['path']}  {disk['size_human']}{model}")
        for part in disk.get("children", []):
            details = " ".join(filter(None, [part.get("fstype"), part.get("label"), part.get("partlabel")]))
            mounts = ",".join(part.get("mountpoints", []))
            print(f"  {part['path']}  {part['size_human']}  {details}  {mounts}".rstrip())


def _plan(args: argparse.Namespace) -> int:
    print(f"mode: {args.mode}")
    if args.mode == "wipe":
        if not args.disk:
            raise InstallerError("--disk is required for wipe mode")
        print(f"would erase and repartition: {args.disk}")
        print(f"boot mode: {args.boot_mode}")
    else:
        if not args.root:
            raise InstallerError("--root is required for manual and dualboot modes")
        print(f"would install into root: {args.root}")
        print(f"EFI partition: {args.esp or 'none (legacy BIOS)'}")
        print("existing partitions would be preserved")
    return 0


def _install_command(args: argparse.Namespace) -> int:
    if not args.yes:
        raise InstallerError("No disk was changed. Add --yes only after reviewing `plan` output.")
    if args.mode == "wipe":
        if not args.disk:
            raise InstallerError("--disk is required for wipe mode")
        boot_mode = args.boot_mode
        if boot_mode == "auto":
            boot_mode = "uefi" if Path("/sys/firmware/efi").exists() else "bios"
        root, esp = _wipe_and_partition(args.disk, boot_mode)
        install_to_partitions(root, esp, disk=args.disk, boot_mode=boot_mode)
    else:
        if not args.root:
            raise InstallerError("--root is required for manual and dualboot modes")
        systems = detect_operating_systems() if args.mode == "dualboot" else None
        if args.mode == "dualboot":
            validate_dualboot_target(args.root, systems or [])
        if args.format_root:
            _format_partition(args.root, "ext4")
        install_to_partitions(
            args.root,
            args.esp,
            disk=args.disk,
            boot_mode=args.boot_mode,
            preserve_existing=args.mode == "dualboot",
            detected_systems=systems,
        )
    print("Installation completed. Remove the ISO and reboot.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pythonos-installer", description="Safe PythonOS disk installer")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("guide", help="show the manual installation guide")
    sub.add_parser("disks", help="list disks and partitions")
    sub.add_parser("detect", help="detect installed operating systems")
    plan = sub.add_parser("plan", help="show a read-only installation plan")
    install = sub.add_parser("install", help="write an installation after explicit confirmation")
    for command in (plan, install):
        command.add_argument("--mode", choices=("wipe", "manual", "dualboot"), required=True)
        command.add_argument("--disk", help="whole disk, for example /dev/sda")
        command.add_argument("--root", help="prepared Linux root partition")
        command.add_argument("--esp", help="EFI System Partition")
        command.add_argument("--boot-mode", choices=("auto", "uefi", "bios"), default="auto")
    install.add_argument("--format-root", action="store_true", help="format the selected root partition as ext4")
    install.add_argument("--yes", action="store_true", help="confirm the reviewed plan")
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "guide"):
            print(guide_text())
        elif args.command == "disks":
            _print_disks(detect_disks())
        elif args.command == "detect":
            systems = detect_operating_systems()
            if not systems:
                print("No Windows or Linux installation detected.")
            for system in systems:
                print(f"{system['kind']}: {system['path']} — {system['description']}")
        elif args.command == "plan":
            return _plan(args)
        elif args.command == "install":
            return _install_command(args)
        return 0
    except InstallerError as exc:
        print(f"installer: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
