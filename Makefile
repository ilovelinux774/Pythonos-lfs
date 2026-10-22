# PythonOS — build, test and run
#
#   make all             Alpine rootfs + OpenRC + initramfs + ISO
#   make rootfs-gui      optional native Xorg + PySide6 rootfs
#   make desktop-install install hosted desktop dependencies
#   make desktop         run the hosted PythonOS desktop
#   make test            boot the live native Alpine image in QEMU
#   make test-installed  boot a disposable installed root and test recovery
#   make unittest        host-side tests (no root, GUI optional)

SHELL := /bin/bash
PY := python3
QEMU_MEMORY ?= 768
KERNEL := $(if $(wildcard .build/pyrootfs/boot/vmlinuz-lts),.build/pyrootfs/boot/vmlinuz-lts,.cache-dl/vmlinuz-lts)
INITRAMFS := release/initramfs-lts
ISO := release/pythonos-0.1.iso

.PHONY: all rootfs rootfs-gui iso iso-gui initramfs test test-installed run run-iso run-serial shots \
        desktop-install desktop desktop-shot unittest clean distclean

all: iso

rootfs:
	sudo builder/prepare_rootfs.sh

rootfs-gui:
	mkdir -p .build
	sudo PYTHONOS_NATIVE_GUI=1 PYTHONOS_ROOTFS=$(CURDIR)/.build/pyrootfs builder/prepare_rootfs.sh

iso:
	sudo $(PY) builder/build.py

iso-gui:
	sudo PYTHONOS_ROOTFS=$(CURDIR)/.build/pyrootfs $(PY) builder/build.py

initramfs:
	sudo $(PY) builder/build.py --no-iso

desktop-install:
	$(PY) -m pip install -r requirements.txt

desktop:
	$(PY) -m pythonos.desktop.main

desktop-shot:
	QT_QPA_PLATFORM=offscreen $(PY) builder/desktop_shot.py

test:
	@test -f $(INITRAMFS) || { echo "run 'make iso' first"; exit 1; }
	bash builder/test_boot.sh 300

test-installed:
	@test -f release/initramfs-installed || { echo "run 'make iso-gui' first"; exit 1; }
	@test -d .build/pyrootfs || { echo "run 'make rootfs-gui' first"; exit 1; }
	sudo builder/test_installed_boot.sh 300

run:
	@test -f $(ISO) || { echo "run 'make iso' first"; exit 1; }
	qemu-system-x86_64 -m $(QEMU_MEMORY) -smp 1 -device virtio-rng-pci \
		-cdrom $(ISO) -serial mon:stdio

run-iso:
	@test -f $(ISO) || { echo "run 'make iso' first"; exit 1; }
	qemu-system-x86_64 -m $(QEMU_MEMORY) -cdrom $(ISO)

run-serial:
	@test -f $(INITRAMFS) || { echo "run 'make iso' first"; exit 1; }
	qemu-system-x86_64 -m $(QEMU_MEMORY) -nographic \
		-kernel $(KERNEL) -initrd $(INITRAMFS) \
		-append "console=ttyS0 rdinit=/init"

shots:
	@test -f $(INITRAMFS) || { echo "run 'make iso' first"; exit 1; }
	$(PY) builder/demo_shots.py

unittest:
	PYTHONPATH=system/usr/lib/pythonos:system/usr/lib $(PY) -m unittest discover -s tests -v

clean:
	rm -rf release /tmp/pythonos-iso /tmp/pyrootfs .build

distclean: clean
	rm -rf .cache-dl
