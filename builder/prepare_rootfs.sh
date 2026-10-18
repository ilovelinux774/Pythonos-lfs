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
        py3-pyside6 xorg-server xinit xf86-video-fbdev xf86-video-vmware \
        xf86-video-vesa xf86-input-libinput font-dejavu linux-lts

    # The GUI profile uses the matching Alpine kernel modules for QEMU and
    # real hardware graphics/input. Firmware is intentionally removed from
    # this small desktop image; it is not needed for the generic QEMU VGA
    # device and can otherwise add more than a gigabyte to the ISO.
    #
    # Keep the kernel's graphics stack as a coherent module family. In
    # particular, bochs-drm -> TTM -> AGP is a real dependency chain; pruning
    # only the DRM directories makes modprobe report unresolved agp_* symbols
    # and leaves Xorg with no screen. The input/HID and virtio families cover
    # QEMU, while vmwgfx/vboxvideo cover VirtualBox's VMSVGA and VBoxSVGA
    # controllers. The Xorg VMware and VESA drivers provide fallbacks when
    # the controller does not expose a usable modesetting device.
    chroot "$ROOTFS" /bin/sh -c '
        rm -rf /lib/firmware /boot/initramfs-lts /boot/System.map-* /boot/config-*
        rm -rf /usr/share/qt6 /usr/share/PySide6 /usr/share/mime
        KVER=$(ls -1 /lib/modules 2>/dev/null | head -n 1)
        if [ -n "$KVER" ]; then
            MODULES=/lib/modules/$KVER/kernel
            find "$MODULES" -type f ! \( -path "$MODULES/drivers/gpu/drm/*" -o -path "$MODULES/drivers/char/agp/*" -o -path "$MODULES/drivers/virtio/*" -o -path "$MODULES/drivers/input/*" -o -path "$MODULES/drivers/hid/*" \) -delete
            find "$MODULES" -type d -empty -delete
            depmod -a "$KVER" 2>/dev/null || true
        fi

        # py3-pyside6 is an intentionally broad Alpine package. The shared
        # PythonOS desktop currently needs only QtCore, QtGui and QtWidgets;
        # remove the optional bindings and Qt development payload after apk
        # has installed the runtime dependencies. Keep the XCB platform
        # plugin and its small runtime library set for the native X session.
        PYSIDE6=/usr/lib/python3.12/site-packages/PySide6
        find "$PYSIDE6" -type f \( -name "Qt*.abi3.so" -o -name "Qt*.pyi" \) ! \
            -name "QtCore.abi3.so" ! -name "QtCore.pyi" \
            ! -name "QtGui.abi3.so" ! -name "QtGui.pyi" \
            ! -name "QtWidgets.abi3.so" ! -name "QtWidgets.pyi" -delete
        rm -rf /usr/lib/qt6/bin /usr/lib/qt6/libexec /usr/lib/qt6/metatypes \
            /usr/lib/qt6/modules /usr/lib/qt6/qml /usr/lib/llvm17
        find /usr/lib -maxdepth 1 \( -type f -o -type l \) -name "libQt6*.so*" ! \
            -name "libQt6Core.so*" ! -name "libQt6DBus.so*" \
            ! -name "libQt6Gui.so*" ! -name "libQt6Widgets.so*" \
            ! -name "libQt6XcbQpa.so*" -delete
        rm -f /usr/lib/libLLVM*.so* /usr/lib/libav*.so* /usr/lib/libSvt*.so* \
            /usr/lib/libaom*.so* /usr/lib/libx264*.so* /usr/lib/libx265*.so* \
            /usr/lib/libxvid*.so* /usr/lib/libvpx*.so* /usr/lib/libopenmpt*.so* \
            /usr/lib/libbluray*.so* /usr/lib/libmpg123*.so* /usr/lib/librist*.so* \
            /usr/lib/libsrt*.so*
        rm -f /usr/lib/qt6/plugins/designer/libqwebengineview.so
    '
else
    echo "==> native graphical profile disabled (use PYTHONOS_NATIVE_GUI=1)"
fi

echo "==> rootfs ready: $(du -sh "$ROOTFS" | cut -f1)"
