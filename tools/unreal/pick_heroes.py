#!/usr/bin/env python3
"""Pick mid + max-luma PNG heroes from an MRQ sequence directory (stdlib only)."""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path


def png_max_rgb(path: Path) -> int:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return -1
    i = 8
    idat = b""
    width = height = color = None
    while i < len(data):
        ln = struct.unpack(">I", data[i : i + 4])[0]
        i += 4
        typ = data[i : i + 4]
        i += 4
        chunk = data[i : i + ln]
        i += ln + 4
        if typ == b"IHDR":
            width, height, _bit, color = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    if not width or color not in (2, 6):
        return -1
    raw = zlib.decompress(idat)
    bpp = 4 if color == 6 else 3
    stride = width * bpp
    mx = 0
    o = 0
    prev = bytearray(stride)
    step_y = max(1, height // 40)
    for y in range(height):
        f = raw[o]
        o += 1
        row = bytearray(raw[o : o + stride])
        o += stride
        if f == 1:
            for x in range(stride):
                row[x] = (row[x] + (row[x - bpp] if x >= bpp else 0)) & 255
        elif f == 2:
            for x in range(stride):
                row[x] = (row[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                left = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + ((left + prev[x]) // 2)) & 255
        elif f == 4:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[x] = (row[x] + pr) & 255
        elif f != 0:
            return -1
        if y % step_y == 0:
            for x in range(0, width, max(1, width // 40)):
                r = row[x * bpp]
                g = row[x * bpp + 1]
                bch = row[x * bpp + 2]
                mx = max(mx, r, g, bch)
        prev = row
    return mx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sequence_dir")
    ap.add_argument("--min-rgb", type=int, default=8)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()
    root = Path(args.sequence_dir)
    frames = sorted(root.rglob("*.png"))
    if not frames:
        frames = sorted(root.rglob("*.jpg"))
    if not frames:
        raise SystemExit(f"no_frames:{root}")

    scored = []
    for p in frames:
        mx = png_max_rgb(p) if p.suffix.lower() == ".png" else max(0, p.stat().st_size // 1000)
        scored.append((mx, p))

    mid = frames[len(frames) // 2]
    mid_rgb = next(s[0] for s in scored if s[1] == mid)
    peak = max(scored, key=lambda t: t[0])
    heroes = []
    if mid_rgb >= args.min_rgb:
        heroes.append({"role": "mid", "path": str(mid), "max_rgb": mid_rgb})
    if peak[0] >= args.min_rgb and peak[1] != mid:
        heroes.append({"role": "max_luma", "path": str(peak[1]), "max_rgb": peak[0]})
    elif peak[0] >= args.min_rgb and not heroes:
        heroes.append({"role": "max_luma", "path": str(peak[1]), "max_rgb": peak[0]})

    payload = {
        "sequence_dir": str(root),
        "frame_count": len(frames),
        "peak_rgb": peak[0],
        "heroes": heroes,
        "ok": bool(heroes),
        "error": None if heroes else f"still_pure_black:peak_rgb={peak[0]}",
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
