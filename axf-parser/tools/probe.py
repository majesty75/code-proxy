#!/usr/bin/env python3
"""
Non-sensitive AXF structural probe.

Prints ONLY layout/metadata needed to build the decoder's region map and to
confirm global-variable extraction will work reliably:
  - ELF class / machine / endianness
  - DWARF version(s)
  - PT_LOAD segments (address ranges the firmware occupies in RAM/flash)
  - ALLOC sections (.data/.bss/heap/stack) addresses + sizes
  - Histogram of DW_AT_location opcode forms for globals (how many are
    extractable with the current logic vs dropped), and the min/max address
    span of extractable globals.

It does NOT print any symbol names, string contents, or memory values.
Safe to share the stdout.

Usage:
    python probe.py firmware.axf
"""
import sys
import struct
from collections import Counter
from pathlib import Path

from elftools.elf.elffile import ELFFile


def seg_flags(p_flags):
    return ("R" if p_flags & 0x4 else "-") + \
           ("W" if p_flags & 0x2 else "-") + \
           ("X" if p_flags & 0x1 else "-")


def main(path):
    span_min, span_max = None, None
    with open(path, "rb") as f:
        elf = ELFFile(f)

        print("=== ELF ===")
        print(f"class       : {'ELF64' if elf.elfclass == 64 else 'ELF32'}")
        print(f"machine     : {elf['e_machine']}")
        print(f"endianness  : {'little' if elf.little_endian else 'big'}")

        print("\n=== PT_LOAD segments (vaddr .. vaddr+memsz) ===")
        print(f"{'flags':6} {'vaddr':>12} {'paddr':>12} {'memsz':>10} {'filesz':>10}")
        for seg in elf.iter_segments():
            if seg['p_type'] != 'PT_LOAD':
                continue
            h = seg.header
            print(f"{seg_flags(h.p_flags):6} "
                  f"0x{h.p_vaddr:08x}  0x{h.p_paddr:08x}  "
                  f"{h.p_memsz:>10} {h.p_filesz:>10}")

        print("\n=== ALLOC sections (addr .. addr+size) ===")
        print("  (redact NAME if codenamed; I only need addr/size/type)")
        print(f"{'name':24} {'type':14} {'addr':>12} {'size':>10}")
        for sec in elf.iter_sections():
            flags = sec['sh_flags']
            if not (flags & 0x2):  # SHF_ALLOC
                continue
            print(f"{sec.name[:24]:24} {sec['sh_type']:14} "
                  f"0x{sec['sh_addr']:08x}  {sec['sh_size']:>10}")

        if not elf.has_dwarf_info():
            print("\n!! No DWARF info found.")
            return

        dwarf = elf.get_dwarf_info()

        print("\n=== DWARF ===")
        versions = Counter()
        cu_count = 0
        loc_first_op = Counter()   # first opcode byte of DW_AT_location
        loc_len = Counter()        # length of the location expression
        n_vars_with_loc = 0
        n_decl = 0
        n_extractable = 0          # matches current process_elf.py logic
        for cu in dwarf.iter_CUs():
            cu_count += 1
            versions[cu['version']] += 1
            for die in cu.iter_DIEs():
                if die.tag != 'DW_TAG_variable':
                    continue
                if 'DW_AT_declaration' in die.attributes:
                    n_decl += 1
                if 'DW_AT_location' not in die.attributes:
                    continue
                loc = die.attributes['DW_AT_location'].value
                if not isinstance(loc, (list, tuple, bytes, bytearray)):
                    loc_first_op['<non-block (loclistptr?)>'] += 1
                    continue
                if len(loc) == 0:
                    continue
                n_vars_with_loc += 1
                first = loc[0]
                loc_first_op[f"0x{first:02x}"] += 1
                loc_len[len(loc)] += 1
                # current extraction: DW_OP_addr (0x03) + 4 or 8 bytes
                if first == 0x03 and len(loc) in (5, 9):
                    n_extractable += 1
                    addr = struct.unpack('<I' if len(loc) == 5 else '<Q',
                                         bytes(loc[1:]))[0]
                    span_min = addr if span_min is None else min(span_min, addr)
                    span_max = addr if span_max is None else max(span_max, addr)

        print(f"CU count            : {cu_count}")
        print(f"DWARF versions      : {dict(versions)}")
        print(f"vars w/ location    : {n_vars_with_loc}")
        print(f"vars w/ declaration : {n_decl}")
        print(f"extractable (now)   : {n_extractable}  "
              f"({100*n_extractable//max(n_vars_with_loc,1)}% of located)")
        print(f"location first-op   : {dict(loc_first_op)}")
        print(f"location expr lens  : {dict(sorted(loc_len.items()))}")
        if span_min is not None:
            print(f"extractable addr span: 0x{span_min:08x} .. 0x{span_max:08x}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python probe.py firmware.axf")
        sys.exit(1)
    main(Path(sys.argv[1]))
