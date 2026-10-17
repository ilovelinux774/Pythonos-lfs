#!/bin/bash
# Boot PythonOS in QEMU and run the in-guest self-test.
#   bash builder/test_boot.sh [timeout-seconds]
set -uo pipefail

BASE=$(cd "$(dirname "$0")/.." && pwd)
LOG="$BASE/release/boot-selftest.log"
TIMEOUT=${1:-240}

mkdir -p "$BASE/release"
rm -f "$LOG"

echo "==> booting PythonOS in QEMU (timeout ${TIMEOUT}s)"
timeout "$TIMEOUT" qemu-system-x86_64 \
    -m 512 -smp 1 -device virtio-rng-pci \
    -kernel "$BASE/.cache-dl/vmlinuz-lts" \
    -initrd "$BASE/release/initramfs-lts" \
    -append "console=ttyS0 quiet loglevel=3 rdinit=/init pythonos.selftest=1" \
    -nographic -no-reboot -monitor none \
    > "$LOG" 2>&1
STATUS=$?

echo "==> qemu exit status: $STATUS"
echo "==> last 40 lines of guest console:"
tail -n 40 "$LOG"

if grep -q "SELFTEST PASSED" "$LOG"; then
    echo
    echo "RESULT: SELFTEST PASSED"
    exit 0
fi

echo
echo "RESULT: SELFTEST FAILED OR SYSTEM DID NOT BOOT"
exit 1
