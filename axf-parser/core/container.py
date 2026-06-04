"""Packaged per-core dump container: ONE .bin file carries all of a core's
non-contiguous SRAM banks plus a header describing where each bank lives.

Why: globals are scattered across banks separated by unmapped gaps, so a single
spanning dump could fault. PRACTICE dumps each bank to a temp file; the dump
agent packs them here into one object that flows through the pipeline, and the
decoder reconstructs segmented memory from the header.

Layout on disk:
    magic     4 bytes   b"UTAX"
    version   1 byte     = 1
    hlen      4 bytes    little-endian uint32, length of the JSON header
    header    hlen bytes UTF-8 JSON (see below)
    payload   concatenated bank bytes, in header order

Header JSON:
    {
      "core": "H",
      "created": "2025-06-03T14:35:22",   # optional, informational
      "segments": [
        {"base": 536870912, "size": 104888, "offset": 0},
        {"base": 1073774592, "size": 149284, "offset": 104888},
        ...
      ]
    }
  "offset" is relative to the start of the payload (after the header).
"""
import json
import struct

MAGIC = b"UTAX"
VERSION = 1


def write_container(out_path, core, banks, created=None):
    """banks: list of (base:int, data:bytes). Writes the container file."""
    segs, payload, off = [], bytearray(), 0
    for base, data in banks:
        segs.append({"base": base, "size": len(data), "offset": off})
        payload += data
        off += len(data)
    header = json.dumps({"core": core, "created": created, "segments": segs}).encode()
    with open(out_path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<B", VERSION))
        f.write(struct.pack("<I", len(header)))
        f.write(header)
        f.write(payload)


def read_container(path):
    """Return (header:dict, banks:list[(base, data)])."""
    with open(path, "rb") as f:
        raw = f.read()
    return parse_container(raw)


def parse_container(raw: bytes):
    if raw[:4] != MAGIC:
        raise ValueError("not a UTAX container (bad magic)")
    version = raw[4]
    if version != VERSION:
        raise ValueError(f"unsupported container version {version}")
    (hlen,) = struct.unpack_from("<I", raw, 5)
    hstart = 9
    header = json.loads(raw[hstart:hstart + hlen].decode())
    pstart = hstart + hlen
    banks = []
    for seg in header["segments"]:
        o = pstart + seg["offset"]
        banks.append((seg["base"], raw[o:o + seg["size"]]))
    return header, banks
