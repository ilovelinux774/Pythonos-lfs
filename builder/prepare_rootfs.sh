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
        xf86-video-vesa xf86-input-libinput xf86-input-evdev \
        xf86-input-vmmouse eudev eudev-openrc udev-init-scripts-openrc \
        font-dejavu linux-lts util-linux parted e2fsprogs dosfstools \
        grub grub-bios grub-efi efibootmgr os-prober ntfs-3g mtools

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
    # the controller does not expose a usable modesetting device. eudev is
    # included so libinput receives the kernel's hotplugged mouse devices;
    # xf86-input-vmmouse covers VirtualBox's legacy i8042 PS/2 pointer path.
    chroot "$ROOTFS" /bin/sh -c '
        rm -rf /lib/firmware /boot/initramfs-lts /boot/System.map-* /boot/config-*
        rm -rf /usr/share/qt6 /usr/share/PySide6 /usr/share/mime
        KVER=$(ls -1 /lib/modules 2>/dev/null | head -n 1)
        if [ -n "$KVER" ]; then
            MODULES=/lib/modules/$KVER/kernel
            find "$MODULES" -type f ! \( \
                -path "$MODULES/drivers/gpu/drm/*" \
                -o -path "$MODULES/drivers/char/agp/*" \
                -o -path "$MODULES/drivers/virtio/*" \
                -o -path "$MODULES/drivers/block/*" \
                -o -path "$MODULES/drivers/ata/*" \
                -o -path "$MODULES/drivers/nvme/*" \
                -o -path "$MODULES/drivers/scsi/*" \
                -o -path "$MODULES/drivers/md/*" \
                -o -path "$MODULES/drivers/mmc/*" \
                -o -path "$MODULES/drivers/input/*" \
                -o -path "$MODULES/drivers/hid/*" \
                -o -path "$MODULES/drivers/crypto/*" \
                -o -path "$MODULES/arch/x86/crypto/*" \
                -o -path "$MODULES/crypto/*" \
                -o -path "$MODULES/lib/*" \
                -o -path "$MODULES/fs/*" \
                -o -path "$MODULES/fs/ext4/*" \
                -o -path "$MODULES/fs/jbd2/*" \
                -o -path "$MODULES/fs/mbcache*" \
                -o -path "$MODULES/fs/fat/*" \
                -o -path "$MODULES/fs/vfat/*" \
                -o -path "$MODULES/fs/exfat/*" \
                -o -path "$MODULES/fs/ntfs3/*" \
                -o -path "$MODULES/fs/fuse/*" \
                -o -path "$MODULES/fs/btrfs/*" \
                -o -path "$MODULES/fs/xfs/*" \
                -o -path "$MODULES/fs/isofs/*" \
                -o -path "$MODULES/fs/udf/*" \
                -o -path "$MODULES/fs/efivarfs/*" \
            \) -delete
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

        # py3-pyside6 pulls optional QtQuick, WebEngine, multimedia and GTK
        # payload. PythonOS uses only QtCore/QtGui/QtWidgets over XCB. Keep
        # the XCB platform plugin and remove the optional bindings/plugins so
        # the GUI ISO still boots comfortably with the documented 768 MiB
        # QEMU/VirtualBox memory target.
        rm -rf /usr/lib/qt6/plugins/assetimporters \
            /usr/lib/qt6/plugins/designer \
            /usr/lib/qt6/plugins/egldeviceintegrations \
            /usr/lib/qt6/plugins/geometryloaders \
            /usr/lib/qt6/plugins/multimedia \
            /usr/lib/qt6/plugins/networkinformation \
            /usr/lib/qt6/plugins/platforminputcontexts \
            /usr/lib/qt6/plugins/platformthemes \
            /usr/lib/qt6/plugins/position \
            /usr/lib/qt6/plugins/printsupport \
            /usr/lib/qt6/plugins/qmllint \
            /usr/lib/qt6/plugins/qmltooling \
            /usr/lib/qt6/plugins/renderers \
            /usr/lib/qt6/plugins/renderplugins \
            /usr/lib/qt6/plugins/sceneparsers \
            /usr/lib/qt6/plugins/scxmldatamodel \
            /usr/lib/qt6/plugins/sensors \
            /usr/lib/qt6/plugins/texttospeech \
            /usr/lib/qt6/plugins/tls \
            /usr/lib/qt6/plugins/wayland-decoration-client \
            /usr/lib/qt6/plugins/wayland-graphics-integration-client \
            /usr/lib/qt6/plugins/wayland-graphics-integration-server \
            /usr/lib/qt6/plugins/wayland-shell-integration
        rm -f /usr/lib/qt6/plugins/platforms/libqeglfs.so \
            /usr/lib/qt6/plugins/platforms/libqwayland-egl.so \
            /usr/lib/qt6/plugins/platforms/libqwayland-generic.so
        rm -rf /usr/lib/qt6/plugins/imageformats
        rm -f /usr/lib/python3.12/site-packages/PySide6/*.pyi
        rm -f /usr/share/misc/magic.mgc
        rm -f /usr/lib/libgtk-3.so* /usr/lib/libgdk-3.so* \
            /usr/lib/libgdk_pixbuf-2.0.so* /usr/lib/libatk-1.0.so* \
            /usr/lib/libatk-bridge-2.0.so* /usr/lib/libcairo*.so* \
            /usr/lib/libpango*.so*
        rm -f /usr/lib/libflite*.so* /usr/lib/libassimp*.so* \
            /usr/lib/libOpenEXR*.so* /usr/lib/libImath*.so* \
            /usr/lib/libimath*.so* /usr/lib/libjxl*.so* \
            /usr/lib/libdav1d*.so* /usr/lib/librav1e*.so*
        rm -f /usr/lib/libgio-2.0.so*
        rm -rf /usr/lib/girepository-1.0 /usr/lib/pulseaudio \
            /usr/share/gtk-3.0 /usr/share/icons \
            /usr/share/themes /usr/share/fonts/misc /usr/share/fonts/encodings
        rm -rf /usr/lib/python3.12/ensurepip \
            /usr/lib/python3.12/lib2to3 \
            /usr/lib/python3.12/pydoc_data \
            /usr/lib/python3.12/turtle.py \
            /usr/lib/python3.12/turtledemo \
            /usr/lib/python3.12/venv
    '
else
    echo "==> native graphical profile disabled (use PYTHONOS_NATIVE_GUI=1)"
fi

echo "==> rootfs ready: $(du -sh "$ROOTFS" | cut -f1)"
