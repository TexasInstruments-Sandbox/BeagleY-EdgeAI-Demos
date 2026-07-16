#!/usr/bin/python3
"""Direct ABI smoke test for libomnicode-decoder using an 8-bit PGM image."""

import argparse
import ctypes
import json
from pathlib import Path


def read_pgm(path: Path) -> tuple[bytes, int, int]:
    with path.open("rb") as stream:
        if stream.readline().strip() != b"P5":
            raise RuntimeError("test image must be binary PGM (P5)")
        line = stream.readline()
        while line.startswith(b"#"):
            line = stream.readline()
        width, height = (int(value) for value in line.split())
        if int(stream.readline()) != 255:
            raise RuntimeError("test image must have 8-bit samples")
        pixels = stream.read()
    if len(pixels) != width * height:
        raise RuntimeError("PGM payload length is invalid")
    return pixels, width, height


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--formats", default="")
    parser.add_argument("--expect", required=True)
    args = parser.parse_args()
    pixels, width, height = read_pgm(args.image)
    library = ctypes.CDLL(str(args.library.resolve()))
    library.omnicode_decode_luma.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t,
    ]
    library.omnicode_decode_luma.restype = ctypes.c_int
    source = (ctypes.c_uint8 * len(pixels)).from_buffer_copy(pixels)
    output = ctypes.create_string_buffer(256 * 1024)
    formats = args.formats.encode() if args.formats else None
    count = library.omnicode_decode_luma(
        source, width, height, width, formats, output, len(output)
    )
    if count < 0:
        raise RuntimeError(f"decoder returned {count}")
    results = json.loads(output.value)
    if count != len(results) or not any(result["text"] == args.expect for result in results):
        raise RuntimeError(f"expected payload not found: {results}")
    print(json.dumps(results, indent=2))
    print("OMNICODE ZXING ABI TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
