#!/usr/bin/env python3
"""Build a dump container from an AXF's OWN image — a test fixture standing in
for a real hardware dump (initialized data present, .bss zero-filled). Lets you
exercise the full decode path offline against real firmware structures.

    python -m tools.elf_to_container <firmware.axf> <layout.json> <out.bin>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import dwarf_layout                     # noqa: E402
from core.container import write_container        # noqa: E402


def read_image(elf, base, size):
    """Return `size` bytes starting at `base`, sourced from PT_LOAD file data
    where present, zero elsewhere (mirrors .bss zero-init at boot)."""
    buf = bytearray(size)
    for seg in elf.iter_segments():
        if seg['p_type'] != 'PT_LOAD':
            continue
        h = seg.header
        f_lo, f_hi = h.p_vaddr, h.p_vaddr + h.p_filesz   # file-backed bytes
        lo, hi = max(base, f_lo), min(base + size, f_hi)
        if lo < hi:
            data = seg.data()
            buf[lo - base:hi - base] = data[lo - h.p_vaddr:hi - h.p_vaddr]
    return bytes(buf)


def main():
    axf, layout_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    layout = json.loads(Path(layout_path).read_text())
    elf, _ = dwarf_layout.open_axf(axf)
    banks = [(s["base"], read_image(elf, s["base"], s["size"]))
             for s in layout["segments"]]
    write_container(out, layout.get("core", "M"), banks)
    total = sum(len(d) for _, d in banks)
    print(f"wrote {out}: {len(banks)} banks, {total} bytes")


if __name__ == "__main__":
    main()
