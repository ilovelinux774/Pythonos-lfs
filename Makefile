# PythonOS — build and test
#
#   make all        rootfs + initramfs + ISO
#   make test       boot in QEMU and assert the in-guest self-test
#   make run        boot interactively
#   make shots      capture the screenshots in docs/
#   make unittest   host-side unit tests (no root, no QEMU)
#   make clean      remove build outputs (keeps the downloaded cache)

SHELL := /bin/bash
PY := python3
KERNEL := .cache-dl/vmlinuz-lts
INITRAMFS := release/initramfs-lts
ISO := release/pythonos-0.1.iso

.PHONY: all rootfs iso initramfs test run run-iso shots unittest clean distclean

all: iso

rootfs:
	sudo builder/prepare_rootfs.sh

iso:
	sudo $(PY) builder/build.py

initramfs:
	sudo $(PY) builder/build.py --no-iso

test:
	@test -f $(INITRAMFS) || { echo "run 'make iso' first"; exit 1; }
	bash builder/test_boot.sh 300

run:
	@test -f $(ISO) || { echo "run 'make iso' first"; exit 1; }
	qemu-system-x86_64 -m 512 -smp 1 -device virtio-rng-pci \
		-cdrom $(ISO) -serial mon:stdio

run-iso:
	@test -f $(ISO) || { echo "run 'make iso' first"; exit 1; }
	qemu-system-x86_64 -m 512 -cdrom $(ISO)

run-serial:
	@test -f $(INITRAMFS) || { echo "run 'make iso' first"; exit 1; }
	qemu-system-x86_64 -m 512 -nographic \
		-kernel $(KERNEL) -initrd $(INITRAMFS) \
		-append "console=ttyS0 rdinit=/init"

shots:
	@test -f $(INITRAMFS) || { echo "run 'make iso' first"; exit 1; }
	$(PY) builder/demo_shots.py

unittest:
	PYTHONPATH=system/usr/lib/pythonos:system/usr/lib $(PY) -m unittest discover -s tests -v

clean:
	rm -rf release INCLUDE /tmp/pythonos-iso /tmp/pyrootfs

distclean: clean
	rm -rf .cache-dl
