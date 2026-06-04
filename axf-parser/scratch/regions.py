#!/usr/bin/env python3
"""
Derive a COVERAGE-DRIVEN dump set + decoder segment map from an AXF.

Rule (proven against multiple products/cores):
  dump = writable PT_LOAD
       u {section of every extracted global that is runtime RAM & PT_LOAD-backed}

Per global, the source of truth is one of three buckets:
  HW_DUMP   - RW RAM / .bss / heap / DRAM, OR a .bss the linker placed in an
              R-X/odd segment. Changes at runtime -> must be dumped from HW.
  AXF_CONST - PROGBITS in a read-only PT_LOAD (const in flash). Never changes
              -> read the bytes straight from the AXF, no HW dump needed.
  MMIO_SKIP - in NO PT_LOAD (memory-mapped peripheral register) -> skip.

The tool prints the final dump ranges (what PRACTICE must Data.SAVE.Binary and
what the decoder uses as its segment map) and a per-bucket global census so you
can confirm zero silent loss.

Usage:
    python regions.py firmware.axf [--json out.json]
"""
import argparse
import json
import struct
from bisect import bisect_right
from collections import Counter
from pathlib import Path

from elftools.elf.elffile import ELFFile

PF_X, PF_W, PF_R = 0x1, 0x2, 0x4
SHF_WRITE, SHF_ALLOC = 0x1, 0x2

# Off-chip DRAM / XIP aperture. Queue entries live in on-chip SRAM pools, not
# here, so we don't dump it. Override with --include-dram.
DEFAULT_EXCLUDE = [(0x60000000, 0x80000000)]


def merge(ranges):
    out = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def in_ranges(a, ranges):
    return any(s <= a < e for s, e in ranges)


def extract_global_addrs(dwarf):
    addrs = []
    for cu in dwarf.iter_CUs():
        for die in cu.iter_DIEs():
            if die.tag != 'DW_TAG_variable':
                continue
            if 'DW_AT_location' not in die.attributes:
                continue
            if 'DW_AT_declaration' in die.attributes:
                continue
            loc = die.attributes['DW_AT_location'].value
            if not isinstance(loc, (list, tuple, bytes, bytearray)):
                continue
            if len(loc) in (5, 9) and loc[0] == 0x03:
                a = struct.unpack('<I' if len(loc) == 5 else '<Q', bytes(loc[1:]))[0]
                if a != 0:
                    addrs.append(a)
    return addrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('axf')
    ap.add_argument('--json', help='write segment map JSON here')
    ap.add_argument('--include-dram', action='store_true',
                    help='also dump the off-chip DRAM/XIP aperture')
    args = ap.parse_args()

    exclude = [] if args.include_dram else DEFAULT_EXCLUDE

    with open(args.axf, 'rb') as f:
        elf = ELFFile(f)

        # PT_LOAD segments with flags.
        loads = []
        for seg in elf.iter_segments():
            if seg['p_type'] != 'PT_LOAD':
                continue
            h = seg.header
            if h.p_memsz:
                loads.append((h.p_vaddr, h.p_vaddr + h.p_memsz, h.p_flags))

        def load_flags(a):
            """OR of flags of PT_LOAD segments covering a, or None if unbacked."""
            fl, hit = 0, False
            for s, e, f in loads:
                if s <= a < e:
                    fl |= f
                    hit = True
            return fl if hit else None

        # ALLOC sections, sorted by addr for containment lookup.
        secs = []
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & SHF_ALLOC) and sec['sh_size']:
                secs.append((sec['sh_addr'], sec['sh_addr'] + sec['sh_size'],
                             sec['sh_type'], sec.name))
        secs.sort()
        sec_starts = [s for s, _, _, _ in secs]

        def find_sec(a):
            i = bisect_right(sec_starts, a) - 1
            if 0 <= i < len(secs) and secs[i][0] <= a < secs[i][1]:
                return secs[i]
            return None

        # Base dump = writable PT_LOAD.
        dump = merge([(s, e) for s, e, f in loads if f & PF_W])

        def in_dump(a):
            for s, e in dump:
                if s <= a < e:
                    return True
            return False

        # Classify every extracted global; grow the dump for HW_DUMP gaps.
        census = Counter()
        # Per-bucket histogram of address aperture (top 12 bits) so we can SEE
        # whether a "skip" bucket is dropping SRAM (0x00/0x20/0x90) by mistake
        # vs genuine peripherals (0x40/0x4c/0xe0) or DRAM (0x60).
        breakdown = {}
        add_ranges = []

        def note(bucket, a):
            census[bucket] += 1
            breakdown.setdefault(bucket, Counter())[a & 0xFFF00000] += 1

        # On-chip SRAM apertures (RAM-capable). Anything outside these that is
        # not already in the writable dump is peripheral (0x40/0x4c/0xe0) or
        # off-chip DRAM (0x60) and must NOT be dumped (a non-intrusive read of
        # a peripheral aperture can bus-fault).
        SRAM_NIBBLES = (0x00000000, 0x20000000, 0x90000000)

        if elf.has_dwarf_info():
            for a in extract_global_addrs(elf.get_dwarf_info()):
                if in_ranges(a, exclude):
                    note('EXCLUDED_DRAM', a)
                    continue
                if in_dump(a):
                    note('HW_DUMP', a)
                    continue
                if (a & 0xF0000000) not in SRAM_NIBBLES:
                    note('MMIO_SKIP', a)               # peripheral aperture
                    continue
                # In an SRAM aperture but not yet dumped. Section type decides:
                #   NOBITS  -> runtime .bss RAM            -> dump it
                #   PROGBITS read-only -> const in flash   -> skip (per policy)
                #   writable gap        -> dump it
                sec = find_sec(a)
                fl = load_flags(a)
                if sec and sec[2] == 'SHT_NOBITS':
                    note('HW_DUMP (gap fixed)', a)
                    add_ranges.append((sec[0], sec[1]))
                elif fl is not None and not (fl & PF_W):
                    note('SKIP_CONST', a)              # const in flash, not decoded
                elif sec:
                    note('HW_DUMP (gap fixed)', a)     # writable PROGBITS gap
                    add_ranges.append((sec[0], sec[1]))
                else:
                    note('MMIO_SKIP', a)               # SRAM addr, no section/backing

        # Final dump = (writable PT_LOAD u gap-fixes) minus excluded apertures.
        dump = [(s, e) for s, e in merge(list(dump) + add_ranges)
                if not in_ranges(s, exclude)]
        total = sum(e - s for s, e in dump)

    print(f"=== {Path(args.axf).name} ===")
    print(f"Dump set: {len(dump)} ranges, {total} B / {total/1048576:.2f} MiB")
    for s, e in dump:
        print(f"  0x{s:08x} .. 0x{e:08x}   {e - s:>9} B")
    print("\nGlobal census (source of truth per global):")
    for k in ('HW_DUMP', 'HW_DUMP (gap fixed)', 'SKIP_CONST',
              'EXCLUDED_DRAM', 'MMIO_SKIP'):
        if census.get(k):
            apertures = ' '.join(f"0x{r:08x}:{n}"
                                 for r, n in sorted(breakdown[k].items()))
            print(f"  {k:22} : {census[k]:4}   [{apertures}]")
    hw = sum(v for k, v in census.items() if k.startswith('HW_DUMP'))
    print(f"\n=> {hw} globals covered by dump, "
          f"{census.get('SKIP_CONST', 0)} const skipped, "
          f"{census.get('EXCLUDED_DRAM', 0)} in excluded DRAM, "
          f"{census.get('MMIO_SKIP', 0)} MMIO skipped.")
    # Reliability alarm: any skipped/excluded global in an on-chip SRAM aperture
    # is a potential real loss, not a peripheral.
    SRAM_APERTURES = (0x00000000, 0x20000000, 0x90000000)
    alarms = []
    for k in ('MMIO_SKIP', 'SKIP_CONST', 'EXCLUDED_DRAM'):
        for r, n in breakdown.get(k, {}).items():
            if (r & 0xF0000000) in SRAM_APERTURES:
                alarms.append(f"{n} {k} globals at 0x{r:08x}")
    if alarms:
        print("\n!! REVIEW — globals skipped in an SRAM aperture (possible loss):")
        for a in alarms:
            print(f"     {a}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"segments": [{"base": s, "size": e - s} for s, e in dump],
             "endianness": "little"}, indent=2))
        print(f"\nWrote segment map -> {args.json}")


if __name__ == "__main__":
    main()
