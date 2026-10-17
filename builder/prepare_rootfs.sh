#!/bin/sh
# Stage 1 of the PythonOS build: assemble a minimal glibc-free root
# filesystem with Python and Alpine's OpenRC service manager inside it.
#
#   sudo builder/prepare_rootfs.sh
#
# This downloads Alpine's minirootfs, unpacks it to /tmp/pyrootfs (scratch
# space, regenerated freely) and installs Python 3 into it with apk.
# No other package manager is involved, and after this step nothing but
# PythonOS code runs on top.
set -eu

BASE=$(cd "$(dirname "$0")/.." && pwd)
CACHE="$BASE/.cache-dl"
ROOTFS=${PYTHONOS_ROOTFS:-/tmp/pyrootfs}
ALPINE_VERSION=3.20.3
ALPINE_URL="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-minirootfs-${ALPINE_VERSION}-x86_64.tar.gz"

if [ "$(id -u)" -ne 0 ]; then
    echo "prepare_rootfs.sh needs root (chroot). Re-run with sudo." >&2
    exit 1
fi

mkdir -p "$CACHE"
if [ ! -f "$CACHE/minirootfs.tar.gz" ]; then
    echo "==> downloading Alpine minirootfs"
    curl -#L -o "$CACHE/minirootfs.tar.gz" "$ALPINE_URL"
fi
if [ ! -f "$CACHE/vmlinuz-lts" ]; then
    echo "==> downloading Alpine kernel"
    curl -#L -o "$CACHE/vmlinuz-lts" \
        "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/netboot/vmlinuz-lts"
fi

echo "==> unpacking rootfs to $ROOTFS"
rm -rf "$ROOTFS"
mkdir -p "$ROOTFS"
tar -xzf "$CACHE/minirootfs.tar.gz" -C "$ROOTFS"
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"

echo "==> installing Python and OpenRC into the rootfs (apk)"
# Alpine gives us the kernel-facing C plumbing and a production service
# manager. PythonOS owns the framework and desktop above it.
chroot "$ROOTFS" /sbin/apk add --no-cache python3 openrc

# The hosted desktop is the portable graphical development target. A native
# Xorg/PySide6 image is an optional profile because Alpine's complete Qt
# bindings pull hundreds of megabytes of native libraries.
if [ "${PYTHONOS_NATIVE_GUI:-0}" = "1" ]; then
    echo "==> installing optional native graphical profile"
    chroot "$ROOTFS" /sbin/apk add --no-cache \
        py3-pyside6 xorg-server xinit xf86-video-fbdev xf86-input-libinput \
        font-dejavu
else
    echo "==> native graphical profile disabled (use PYTHONOS_NATIVE_GUI=1)"
fi

echo "==> rootfs ready: $(du -sh "$ROOTFS" | cut -f1)"
