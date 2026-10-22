import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pythonos import installer as installer_module
from pythonos.installer import (
    InstallerError,
    _parse_os_release,
    _write_fstab,
    _write_grub_config,
    detect_operating_systems,
    format_bytes,
    guide_text,
    validate_dualboot_target,
)


class InstallerUtilityTests(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0.0 B")
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MiB")

    def test_parse_os_release(self):
        values = _parse_os_release('NAME="Ubuntu"\nID=ubuntu\n# comment\n')
        self.assertEqual(values["NAME"], "Ubuntu")
        self.assertEqual(values["ID"], "ubuntu")

    def test_guide_warns_about_existing_systems(self):
        guide = guide_text()
        self.assertIn("does not silently shrink", guide)
        self.assertIn("--yes", guide)

    def test_detection_distinguishes_free_linux_space(self):
        disks = [{
            "path": "/dev/vda",
            "children": [
                {"path": "/dev/vda1", "fstype": "vfat", "mountpoints": []},
                {"path": "/dev/vda2", "fstype": "ntfs", "label": "Windows", "mountpoints": []},
                {"path": "/dev/vda3", "fstype": "ext4", "mountpoints": []},
                {"path": "/dev/vda4", "fstype": "ext4", "mountpoints": []},
            ],
        }]
        with patch.object(installer_module, "_filesystem_os", side_effect=lambda part: {
            "PRETTY_NAME": "Ubuntu"
        } if part["path"] == "/dev/vda3" else None):
            systems = detect_operating_systems(disks)
        self.assertEqual([item["kind"] for item in systems], ["Windows", "Linux"])
        validate_dualboot_target("/dev/vda4", systems, disks=disks)

    def test_dualboot_rejects_detected_root(self):
        disks = [{
            "path": "/dev/vda",
            "children": [{"path": "/dev/vda2", "fstype": "ext4", "mountpoints": []}],
        }]
        systems = [{"kind": "Linux", "path": "/dev/vda2", "description": "Ubuntu"}]
        with self.assertRaisesRegex(InstallerError, "detected operating system"):
            validate_dualboot_target("/dev/vda2", systems, disks=disks)

    def test_guide_documents_installed_recovery_shell(self):
        guide = guide_text()
        self.assertIn("small storage-only initramfs", guide)
        self.assertIn("pythonos.debug=1", guide)
        self.assertIn("initramfs emergency shell", guide)

    def test_grub_uses_disk_root_and_small_initramfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(installer_module, "_uuid", return_value="root-uuid"):
                _write_grub_config(
                    root,
                    "/dev/vda2",
                    "/dev/vda1",
                    boot_mode="uefi",
                    root_fstype="ext4",
                )
            config = (root / "boot/grub/grub.cfg").read_text(encoding="utf-8")
        self.assertIn("root=UUID=root-uuid rootfstype=ext4 rootwait", config)
        self.assertIn("initrd /boot/initramfs-installed", config)
        self.assertIn("pythonos.debug=1", config)
        self.assertNotIn("initrd /boot/initramfs-lts", config)

    def test_installed_fstab_mounts_runtime_tmpfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(installer_module, "_uuid", side_effect=("root-uuid", "esp-uuid")):
                _write_fstab(root, "/dev/vda2", "/dev/vda1", "ext4")
            fstab = (root / "etc/fstab").read_text(encoding="utf-8")
        self.assertIn("UUID=root-uuid / ext4", fstab)
        self.assertIn("UUID=esp-uuid /boot/efi", fstab)
        self.assertIn("tmpfs /run", fstab)
        self.assertIn("tmpfs /tmp", fstab)


if __name__ == "__main__":
    unittest.main()
