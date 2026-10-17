#!/usr/bin/env python3
"""Boot PythonOS in demo mode and capture VGA screenshots.

Boots QEMU headless (VNC-less), watches the serial log for DEMO markers,
takes a screendump at each stage and converts PPM to PNG.
"""

import os
import socket
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(BASE, "docs", "screenshots")
LOG = os.path.join(BASE, "release", "demo-serial.log")
MON = "/tmp/pythonos-monitor.sock"
PPM = "/tmp/pythonos-shot.ppm"

STAGES = [
    ("splash", "DEMO:splash"),
    ("pyfetch", "DEMO:pyfetch"),
    ("pytop", "DEMO:pytop"),
    ("selftest", "DEMO:selftest"),
    ("shell", "DEMO:shell"),   # real interactive pysh, typed via sendkey
]

KEYMAP = {" ": "spc", "\n": "ret", "-": "minus", "=": "equal", "'": "apostrophe",
          ".": "dot", "/": "slash", "\"": "shift-apostrophe"}


def send_text(sock, text):
    for ch in text:
        key = KEYMAP.get(ch, ch)
        monitor_cmd(sock, f"sendkey {key}", wait=0.09)

sys.path.insert(0, os.path.join(BASE, "builder"))
from ppm2png import read_ppm, write_png  # noqa: E402


def monitor_cmd(sock, command, wait=0.6):
    sock.sendall((command + "\n").encode())
    time.sleep(wait)
    try:
        sock.recv(65536)
    except socket.timeout:
        pass


def main():
    os.makedirs(SHOTS, exist_ok=True)
    if os.path.exists(MON):
        os.remove(MON)
    if os.path.exists(LOG):
        os.remove(LOG)

    qemu = [
        "qemu-system-x86_64",
        "-m", "512", "-smp", "1",
        "-device", "virtio-rng-pci",
        "-kernel", os.path.join(BASE, ".cache-dl", "vmlinuz-lts"),
        "-initrd", os.path.join(BASE, "release", "initramfs-lts"),
        "-append", "console=ttyS0 quiet loglevel=3 rdinit=/init pythonos.demo=1",
        "-display", "none",
        "-vga", "std",
        "-serial", f"file:{LOG}",
        "-monitor", f"unix:{MON},server,nowait",
        "-no-reboot",
    ]
    print("==> booting demo instance")
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    # wait for the monitor socket
    for _ in range(50):
        if os.path.exists(MON):
            break
        time.sleep(0.2)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2)
    for _ in range(50):
        try:
            sock.connect(MON)
            break
        except OSError:
            time.sleep(0.2)
    try:
        sock.recv(4096)
    except socket.timeout:
        pass

    deadline = time.time() + 180
    captured = set()
    try:
        while time.time() < deadline and len(captured) < len(STAGES):
            log = ""
            if os.path.exists(LOG):
                with open(LOG, "r", errors="replace") as fh:
                    log = fh.read()
            pending = [(name, marker) for name, marker in STAGES
                       if name not in captured and marker in log]
            if pending:
                name, _marker = pending[0]
                if name == "shell":
                    time.sleep(3.5)  # login banner + first prompt
                    print("==> typing into pysh: help")
                    send_text(sock, "help\n")
                    time.sleep(2.5)
                else:
                    time.sleep(2.0)  # let the screen finish painting
                print(f"==> capture: {name}")
                if os.path.exists(PPM):
                    os.remove(PPM)
                monitor_cmd(sock, f"screendump {PPM}", wait=1.2)
                if os.path.exists(PPM):
                    width, height, pixels = read_ppm(PPM)
                    out = os.path.join(SHOTS, f"{name}.png")
                    write_png(out, width, height, pixels)
                    print(f"    saved {out} ({width}x{height})")
                    captured.add(name)
                else:
                    print("    screendump produced no file")
                    captured.add(name)

                if name == "shell":
                    print("==> typing into pysh: pkg search")
                    send_text(sock, "pkg search\n")
                    time.sleep(2.5)
                    if os.path.exists(PPM):
                        os.remove(PPM)
                    monitor_cmd(sock, f"screendump {PPM}", wait=1.2)
                    if os.path.exists(PPM):
                        width, height, pixels = read_ppm(PPM)
                        out = os.path.join(SHOTS, "shell_pkg.png")
                        write_png(out, width, height, pixels)
                        print(f"    saved {out} ({width}x{height})")
            else:
                time.sleep(0.5)
        monitor_cmd(sock, "quit", wait=0.2)
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"==> captured {len(captured)}/{len(STAGES)} screens")
    return 0 if len(captured) == len(STAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
