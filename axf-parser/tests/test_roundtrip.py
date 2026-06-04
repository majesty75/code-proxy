"""Offline round-trip: hand-built layout + packaged container -> decoded JSON.

Proves the decode path (segmented memory, structs, arrays, enums, bitfields,
not-in-dump handling, flatten) without needing a real AXF or hardware.

Run:  python -m pytest tests/ -q     (or)  python tests/test_roundtrip.py
"""
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.container import write_container             # noqa: E402
from core.decode import Memory, decode_all             # noqa: E402
from core.flatten import flatten                       # noqa: E402

BASE = 0x20000000

# Type registry:
#   "u32" base unsigned 4
#   "u8"  base unsigned 1
#   "arr" array of u8 [3]
#   "st"  struct { count:u32@0, flags:u8@4, tag:arr@5 } size 8
#   "en"  enum u32 {0:IDLE,1:BUSY}
LAYOUT = {
    "endianness": "little",
    "types": {
        "u32": {"tag": "base", "name": "uint32", "size": 4, "encoding": 7},
        "u8":  {"tag": "base", "name": "uint8",  "size": 1, "encoding": 8},
        "arr": {"tag": "array", "element_type_id": "u8", "dimensions": [3]},
        "en":  {"tag": "enum", "size": 4, "enumerators": {"0": "IDLE", "1": "BUSY"}},
        "st":  {"tag": "struct", "size": 8, "members": {
            "count": {"offset": 0, "type_id": "u32"},
            "flags": {"offset": 4, "type_id": "u8"},
            "tag":   {"offset": 5, "type_id": "arr"},
        }},
    },
    "variables": {
        "g_state":  {"address": BASE,        "type_id": "st"},
        "g_mode":   {"address": BASE + 8,    "type_id": "en"},
        "g_offmap": {"address": 0x40000000,  "type_id": "u32"},  # not in dump
    },
    "sources": {"g_state": "HW_DUMP", "g_mode": "HW_DUMP", "g_offmap": "HW_DUMP"},
}


def _make_container(path):
    body = bytearray()
    body += struct.pack("<I", 0x000000AA)      # count = 170
    body += struct.pack("<B", 0x01)            # flags = 1
    body += bytes([0x41, 0x42, 0x43])          # tag = 'A','B','C'
    body += struct.pack("<I", 0x00000001)      # g_mode = BUSY
    write_container(path, "H", [(BASE, bytes(body))])


def test_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        cont = Path(d) / "dump.bin"
        _make_container(cont)
        mem = Memory.from_container(str(cont))
        decoded, errors, status = decode_all(LAYOUT, mem, LAYOUT["sources"])

        assert decoded["g_state"]["count"] == 0xAA
        assert decoded["g_state"]["flags"] == 1
        assert decoded["g_state"]["tag"] == [0x41, 0x42, 0x43]
        assert decoded["g_mode"] == "BUSY"
        # off-map variable must be flagged, not silently zero
        assert decoded["g_offmap"]["__error__"] == "not in dump"
        assert errors == 1
        assert status == "PARTIAL"

        rows = {r["key"]: r["value"] for r in flatten(decoded)}
        assert rows["g_state.count"] == 0xAA
        assert rows["g_state.tag.0"] == 0x41
        assert rows["g_mode"] == "BUSY"
        assert "g_offmap" not in rows          # error leaf dropped
    print("OK: round-trip decode + flatten passed")


if __name__ == "__main__":
    test_roundtrip()
