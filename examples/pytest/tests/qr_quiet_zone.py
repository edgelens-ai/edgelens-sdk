"""Measure the white margin around a QR symbol in a PNG.

A QR carries a quiet zone — four modules of light on every side — and
it is part of the symbol rather than packaging around it. A decoder
locates a code by its three finder patterns, and a finder that runs to
the edge of the image has nothing to be isolated against.

This exists because the suite pinned the quantity that was not the
binding constraint. The module count and the pixels-per-module targets
are asserted; the quiet zone, which is what decided two device windows,
was measured nowhere.

Scope, deliberately narrow:

* **PNG candidates only, never a capture.** Reading pixels out of a PNG
  is ``zlib`` plus the specification's unfilter loop, both standard
  library. A JPEG pixel path is entropy coding and a DCT, and it is not
  admitted here — the capture is measured by eye, from the artifact.
* **A control over a fixture chosen once**, not a per-run measurement.
* Nothing in the demo's run path imports this.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

_SOF_FILTERS = (0, 1, 2, 3, 4)
LIGHT_THRESHOLD = 128


@dataclass(frozen=True)
class QuietZone:
    """Margins in modules, and what they were derived from."""

    width: int
    height: int
    span_px: int
    module_px: float
    modules: int
    left: float
    right: float
    top: float
    bottom: float

    @property
    def square(self) -> bool:
        return self.width == self.height

    @property
    def smallest(self) -> float:
        return min(self.left, self.right, self.top, self.bottom)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(data: bytes, stride: int, height: int, bpp: int) -> list[bytes]:
    rows: list[bytes] = []
    pos = 0
    prev = bytearray(stride)
    for _ in range(height):
        kind = data[pos]
        if kind not in _SOF_FILTERS:
            raise ValueError(f"unknown PNG row filter {kind}")
        line = bytearray(data[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + b) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif kind == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        rows.append(bytes(line))
        prev = line
    return rows


def dark_mask(png: bytes) -> tuple[int, int, list[list[bool]]]:
    """(width, height, rows of "this pixel is dark")."""
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    header, palette, idat = b"", None, b""
    i = 8
    while i < len(png):
        size = int.from_bytes(png[i:i + 4], "big")
        kind = png[i + 4:i + 8]
        body = png[i + 8:i + 8 + size]
        if kind == b"IHDR":
            header = body
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
        i += 12 + size

    width = int.from_bytes(header[0:4], "big")
    height = int.from_bytes(header[4:8], "big")
    depth, colour, interlace = header[8], header[9], header[12]
    if interlace:
        raise ValueError("interlaced PNG not supported")
    if depth not in (1, 8):
        raise ValueError(f"bit depth {depth} not supported")

    samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    stride = (width * samples * depth + 7) // 8
    rows = _unfilter(zlib.decompress(idat), stride, height, max(1, samples * depth // 8))

    def luma(row: bytes, x: int) -> int:
        if depth == 1:
            bit = (row[x >> 3] >> (7 - (x & 7))) & 1
            if colour == 3 and palette:
                return palette[bit * 3]
            return 255 if bit else 0
        if colour == 3 and palette:
            return palette[row[x] * 3]
        if colour == 0:
            return row[x]
        if colour == 4:
            return row[x * 2]
        o = x * (4 if colour == 6 else 3)
        return (row[o] * 299 + row[o + 1] * 587 + row[o + 2] * 114) // 1000

    mask = [
        [luma(row, x) < LIGHT_THRESHOLD for x in range(width)] for row in rows
    ]
    return width, height, mask


def measure(png: bytes) -> QuietZone:
    """The symbol's margins, in modules, on each of the four sides.

    The module size comes from the top-left finder pattern, whose outer
    row is seven modules of solid dark by construction. Deriving it from
    the symbol's own geometry rather than from a module count supplied
    by the caller is what makes this a measurement: a wrong count would
    otherwise be reported back as a confident margin.
    """
    width, height, mask = dark_mask(png)
    xs = [x for x in range(width) if any(row[x] for row in mask)]
    ys = [y for y in range(height) if any(mask[y])]
    if not xs or not ys:
        raise ValueError("no dark pixels: this is not a code")

    left, right = xs[0], width - 1 - xs[-1]
    top, bottom = ys[0], height - 1 - ys[-1]
    span = xs[-1] - xs[0] + 1

    run = 0
    while xs[0] + run < width and mask[ys[0]][xs[0] + run]:
        run += 1
    if run < 3:
        raise ValueError(
            f"the symbol's first dark row runs {run}px, which is too short "
            f"to be a finder pattern: the module size cannot be derived"
        )
    module = run / 7

    return QuietZone(
        width=width,
        height=height,
        span_px=span,
        module_px=module,
        modules=round(span / module),
        left=left / module,
        right=right / module,
        top=top / module,
        bottom=bottom / module,
    )
