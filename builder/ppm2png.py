#!/usr/bin/env python3
"""Convert a binary PPM (P6) to PNG using only the standard library."""

import struct
import sys
import zlib


def read_ppm(path):
    data = open(path, "rb").read()
    if not data.startswith(b"P6"):
        raise ValueError("not a P6 PPM")
    fields, pos = [], 2
    while len(fields) < 3:
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            while data[pos:pos + 1] != b"\n":
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(int(data[start:pos]))
    pos += 1
    width, height, maxval = fields
    if maxval != 255:
        raise ValueError("only 8-bit PPM supported")
    pixels = data[pos:pos + width * height * 3]
    return width, height, pixels


def png_chunk(tag, payload):
    chunk = tag + payload
    return struct.pack(">I", len(payload)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def write_png(path, width, height, pixels):
    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)  # filter: none
        raw += pixels[row * stride:(row + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + png_chunk(b"IEND", b""))
    open(path, "wb").write(blob)


def main(argv):
    if len(argv) < 3:
        print("usage: ppm2png.py in.ppm out.png")
        return 2
    width, height, pixels = read_ppm(argv[1])
    write_png(argv[2], width, height, pixels)
    print(f"{argv[2]}: {width}x{height}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
