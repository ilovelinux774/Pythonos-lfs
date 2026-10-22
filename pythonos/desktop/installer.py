"""Qt installer front-end shared by hosted and native PythonOS desktops."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pythonos import installer as backend


MODE_LABELS = (
    "Wipe and install",
    "Partition manually",
    "Detect OS and install alongside it",
    "Advanced manual guide",
)


class InstallerWidget(QWidget):
    """Conservative graphical front end for the shared installer backend."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Install PythonOS")
        self._disks: list[dict[str, Any]] = []
        self._systems: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QLabel("Install PythonOS")
        title.setObjectName("hero")
        layout.addWidget(title)
        warning = QLabel(
            "Back up important data first. Wipe mode erases the selected disk. "
            "Dual boot preserves detected Windows and Linux installations and "
            "uses only free, user-prepared partitions."
        )
        warning.setWordWrap(True)
        warning.setObjectName("muted")
        layout.addWidget(warning)

        mode_group = QGroupBox("Choose an installation path")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_select = QComboBox()
        self.mode_select.addItems(MODE_LABELS)
        self.mode_select.currentIndexChanged.connect(self._mode_changed)
        mode_layout.addWidget(self.mode_select)
        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        self.mode_description.setObjectName("muted")
        mode_layout.addWidget(self.mode_description)
        layout.addWidget(mode_group)

        self.options_group = QGroupBox("Installation details")
        form = QFormLayout(self.options_group)
        self.disk_select = QComboBox()
        self.root_select = QComboBox()
        self.esp_select = QComboBox()
        self.esp_select.addItem("No EFI partition (legacy BIOS)", "")
        self.boot_select = QComboBox()
        self.boot_select.addItem("Detect firmware mode", "auto")
        self.boot_select.addItem("UEFI", "uefi")
        self.boot_select.addItem("Legacy BIOS", "bios")
        self.format_root = QCheckBox("Format the selected root partition as ext4")
        form.addRow("Install disk", self.disk_select)
        form.addRow("Linux root partition", self.root_select)
        form.addRow("EFI System Partition", self.esp_select)
        form.addRow("Boot mode", self.boot_select)
        form.addRow("Manual option", self.format_root)
        layout.addWidget(self.options_group)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh disks and OS detection")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(170)
        layout.addWidget(self.details, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        self.install_button = QPushButton("Review and install")
        self.install_button.setDefault(True)
        self.install_button.clicked.connect(self.install)
        actions.addWidget(self.install_button)
        layout.addLayout(actions)
        self._mode_changed(0)

    @staticmethod
    def _label(item: dict[str, Any]) -> str:
        details = " ".join(
            value for value in (item.get("fstype"), item.get("label"), item.get("partlabel")) if value
        )
        suffix = f" — {details}" if details else ""
        return f"{item.get('path', '?')}  {item.get('size_human', '?')}{suffix}"

    def refresh(self) -> None:
        try:
            self._disks = backend.detect_disks()
            self._systems = backend.detect_operating_systems(self._disks)
        except backend.InstallerError as exc:
            self._disks = []
            self._systems = []
            self.details.setPlainText(f"Disk detection is unavailable: {exc}")
        self.disk_select.clear()
        self.root_select.clear()
        self.esp_select.clear()
        self.esp_select.addItem("No EFI partition (legacy BIOS)", "")
        for disk in self._disks:
            self.disk_select.addItem(self._label(disk), disk.get("path", ""))
        detected_paths = {item.get("path") for item in self._systems}
        partitions: list[dict[str, Any]] = []
        for disk in self._disks:
            partitions.extend(disk.get("children", []))
        for part in partitions:
            path = part.get("path", "")
            if not path or part.get("mountpoints"):
                continue
            fstype = str(part.get("fstype", "")).lower()
            if path not in detected_paths and fstype in {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", ""}:
                self.root_select.addItem(self._label(part), path)
            if fstype in {"vfat", "fat32"}:
                self.esp_select.addItem(self._label(part), path)
        self._update_details()

    def _mode_changed(self, index: int) -> None:
        descriptions = (
            "Create a fresh layout and format the selected disk. This is destructive.",
            "Use partitions you prepared in a partition editor. Formatting is opt-in.",
            "Choose a free Linux root partition and, for UEFI, an EFI partition. "
            "Detected operating systems are not resized, formatted, or erased.",
            "Read the advanced guide and perform partitioning, copying, and GRUB setup manually.",
        )
        self.mode_description.setText(descriptions[index])
        advanced = index == 3
        self.options_group.setVisible(not advanced)
        self.refresh_button.setVisible(not advanced)
        self.install_button.setVisible(not advanced)
        if advanced:
            self.details.setPlainText(
                "Automatic partition shrinking/resizing is not implemented. Prepare free space manually.\n\n"
                + backend.guide_text()
            )
        else:
            self._update_details()

    def _selected(self, combo: QComboBox) -> str:
        return str(combo.currentData() or "")

    def _update_details(self) -> None:
        if not hasattr(self, "details") or self.mode_select.currentIndex() == 3:
            return
        lines = [f"Mode: {MODE_LABELS[self.mode_select.currentIndex()]}"]
        if self._systems:
            lines.append("Detected operating systems:")
            lines.extend(f"  {item['kind']}: {item['path']} — {item['description']}" for item in self._systems)
        else:
            lines.append("No Windows or Linux installation was detected.")
        lines += ["", "Automatic partition shrinking is not implemented. Prepare free space first."]
        self.details.setPlainText("\n".join(lines))

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.warning(
            self,
            "Confirm disk operation",
            text,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def install(self) -> None:
        mode_index = self.mode_select.currentIndex()
        if mode_index == 3:
            return
        disk = self._selected(self.disk_select)
        root = self._selected(self.root_select)
        esp = self._selected(self.esp_select)
        boot_mode = self._selected(self.boot_select) or "auto"
        if mode_index == 0 and not disk:
            QMessageBox.warning(self, "No disk selected", "Select the whole disk to erase and install.")
            return
        if mode_index in {1, 2} and not root:
            QMessageBox.warning(self, "No root partition selected", "Select a prepared Linux root partition.")
            return
        if boot_mode == "uefi" and not esp:
            QMessageBox.warning(self, "EFI partition required", "UEFI needs a prepared FAT32 EFI System Partition.")
            return
        if boot_mode == "bios":
            esp = ""
        if mode_index == 2:
            try:
                backend.validate_dualboot_target(root, self._systems)
            except backend.InstallerError as exc:
                QMessageBox.warning(self, "Unsafe dual-boot target", str(exc))
                return
        if mode_index == 0:
            text = f"This will erase and repartition {disk}. All data and operating systems on it will be lost."
        elif mode_index == 2:
            text = f"Install PythonOS into {root} alongside detected operating systems? Existing OS partitions will not be resized or formatted."
        else:
            text = f"Install PythonOS into the prepared partition {root}?"
        if self.format_root.isChecked() and mode_index in {1, 2}:
            text += "\n\nThe selected root partition will also be formatted as ext4."
        if not self._confirm(text):
            return
        try:
            effective_boot = boot_mode
            if effective_boot == "auto":
                from pathlib import Path
                effective_boot = "uefi" if Path("/sys/firmware/efi").exists() else "bios"
            if mode_index == 0:
                root, esp = backend._wipe_and_partition(disk, effective_boot)
                backend.install_to_partitions(root, esp, disk=disk, boot_mode=effective_boot)
            else:
                if self.format_root.isChecked():
                    backend._format_partition(root, "ext4")
                systems = self._systems if mode_index == 2 else None
                backend.install_to_partitions(
                    root,
                    esp or None,
                    disk=disk or None,
                    boot_mode=boot_mode,
                    preserve_existing=mode_index == 2,
                    detected_systems=systems,
                )
        except backend.InstallerError as exc:
            QMessageBox.critical(self, "Installation failed safely", str(exc))
            return
        QMessageBox.information(self, "Installation complete", "PythonOS was installed. Remove the ISO and reboot.")


InstallerWindow = InstallerWidget
