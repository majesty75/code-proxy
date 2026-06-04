#!/usr/bin/env python3
"""
ONE-SHOT: AXF -> layout.json (types + variable addresses + segment map).

Run this ONCE per firmware build. The output layout.json is everything the
decoder needs; you never run a separate regions step. The dump server then
runs decode.py automatically against each .bin dump with no human involved.

  python build_layout.py firmware.axf [--core H] [--out layout.json]

What it does, in order:
  1. Parse DWARF -> type registry + global variable addresses (process_elf).
  2. Derive the HW dump segment map (writable PT_LOAD + SRAM .bss gaps,
     minus off-chip DRAM), the same coverage-driven rule we validated.
  3. Tag every variable with its source: HW_DUMP / SKIP_CONST / MMIO / DRAM.
  4. Print a one-line census and LOUDLY warn if any SRAM global is dropped.

It is a hard error to silently lose an SRAM global, so step 4 is the only
thing worth glancing at on each new firmware.
"""
import argparse
import json
from pathlib import Path
from collections import Counter

from elftools.elf.elffile import ELFFile

from process_elf import parse_dwarf_types

PF_W = 0x2
SHF_ALLOC = 0x2
DEFAULT_EXCLUDE = [(0x60000000, 0x80000000)]   # off-chip DRAM / XIP
SRAM_NIBBLES = (0x00000000, 0x20000000, 0x90000000)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('axf')
    ap.add_argument('--core', help='core tag stored in layout (e.g. H, F, M, N)')
    ap.add_argument('--out')
    args = ap.parse_args()

    axf = Path(args.axf)
    with open(axf, 'rb') as f:
        elf = ELFFile(f)
        dwarf = elf.get_dwarf_info()
        layout = parse_dwarf_types(dwarf)        # {types, variables}

        loads = [(s.header.p_vaddr, s.header.p_vaddr + s.header.p_memsz,
                  s.header.p_flags)
                 for s in elf.iter_segments()
                 if s['p_type'] == 'PT_LOAD' and s.header.p_memsz]
        secs = sorted((x['sh_addr'], x['sh_addr'] + x['sh_size'], x['sh_type'])
                      for x in elf.iter_sections()
                      if (x['sh_flags'] & SHF_ALLOC) and x['sh_size'])

    def load_flags(a):
        fl, hit = 0, False
        for s, e, f in loads:
            if s <= a < e:
                fl |= f
                hit = True
        return fl if hit else None

    def find_sec(a):
        for s, e, t in secs:
            if s <= a < e:
                return (s, e, t)
        return None

    dump = merge([(s, e) for s, e, f in loads if f & PF_W])

    def in_dump(a):
        return in_ranges(a, dump)

    census = Counter()
    breakdown = {}
    add_ranges = []

    def note(bucket, a):
        census[bucket] += 1
        breakdown.setdefault(bucket, Counter())[a & 0xFFF00000] += 1

    for name, v in layout['variables'].items():
        a = v['address']
        if in_ranges(a, DEFAULT_EXCLUDE):
            v['source'] = 'DRAM'; note('EXCLUDED_DRAM', a); continue
        if in_dump(a):
            v['source'] = 'HW_DUMP'; note('HW_DUMP', a); continue
        if (a & 0xF0000000) not in SRAM_NIBBLES:
            v['source'] = 'MMIO'; note('MMIO_SKIP', a); continue
        sec = find_sec(a); fl = load_flags(a)
        if sec and sec[2] == 'SHT_NOBITS':
            v['source'] = 'HW_DUMP'; note('HW_DUMP (gap fixed)', a)
            add_ranges.append((sec[0], sec[1]))
        elif fl is not None and not (fl & PF_W):
            v['source'] = 'SKIP_CONST'; note('SKIP_CONST', a)
        elif sec:
            v['source'] = 'HW_DUMP'; note('HW_DUMP (gap fixed)', a)
            add_ranges.append((sec[0], sec[1]))
        else:
            v['source'] = 'MMIO'; note('MMIO_SKIP', a)

    dump = [(s, e) for s, e in merge(dump + add_ranges)
            if not in_ranges(s, DEFAULT_EXCLUDE)]
    total = sum(e - s for s, e in dump)

    layout['core'] = args.core or axf.stem
    layout['endianness'] = 'little'
    layout['segments'] = [{"base": s, "size": e - s} for s, e in dump]
    layout['build_id'] = None      # filled once we wire the build-hash gate

    out = Path(args.out) if args.out else axf.with_suffix('.layout.json')
    out.write_text(json.dumps(layout, indent=2))

    hw = sum(v for k, v in census.items() if k.startswith('HW_DUMP'))
    print(f"{axf.name}: {len(layout['variables'])} globals | "
          f"dump {total/1048576:.2f} MiB in {len(dump)} ranges | "
          f"HW_DUMP {hw}  SKIP_CONST {census.get('SKIP_CONST',0)}  "
          f"DRAM {census.get('EXCLUDED_DRAM',0)}  MMIO {census.get('MMIO_SKIP',0)}")
    print(f"  -> {out}")

    # The ONLY thing worth reviewing: SRAM globals that got skipped.
    alarms = [(k, r, n)
              for k in ('MMIO_SKIP', 'SKIP_CONST')
              for r, n in breakdown.get(k, {}).items()
              if (r & 0xF0000000) in SRAM_NIBBLES and k == 'MMIO_SKIP']
    if alarms:
        print("  !! REVIEW — SRAM globals skipped (possible loss):")
        for k, r, n in alarms:
            print(f"       {n} at 0x{r:08x}")


if __name__ == "__main__":
    main()
