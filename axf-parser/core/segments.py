"""Derive the HW-dump segment map from an AXF, coverage-driven and validated
against the actual DWARF globals.

Rule (proven across multiple products/cores):
  dump = writable PT_LOAD  u  {SRAM .bss sections holding a global}
         minus off-chip DRAM aperture.

Each global is tagged with its source of truth:
  HW_DUMP    - RW RAM / .bss          -> in the dump
  SKIP_CONST - const in flash         -> not decoded (policy)
  DRAM       - off-chip DRAM aperture -> excluded by policy
  MMIO       - peripheral register    -> never dumped (can bus-fault)

Public API:
    derive(elf, variables) -> {
        "segments":  [{"base":int,"size":int}, ...],
        "sources":   {name: "HW_DUMP"|"SKIP_CONST"|"DRAM"|"MMIO"},
        "census":    {bucket: count},
        "alarms":    [str],   # SRAM globals we had to skip (review!)
    }
"""
from collections import Counter

PF_W = 0x2
SHF_ALLOC = 0x2
DEFAULT_EXCLUDE = [(0x60000000, 0x80000000)]            # off-chip DRAM / XIP
SRAM_NIBBLES = (0x00000000, 0x20000000, 0x90000000)     # on-chip RAM apertures


def _merge(ranges):
    out = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _in(a, ranges):
    return any(s <= a < e for s, e in ranges)


def derive(elf, variables, exclude=DEFAULT_EXCLUDE):
    loads = [(s.header.p_vaddr, s.header.p_vaddr + s.header.p_memsz, s.header.p_flags)
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

    dump = _merge([(s, e) for s, e, f in loads if f & PF_W])
    census, sources, add_ranges, alarms = Counter(), {}, [], []

    for name, v in variables.items():
        a = v['address']
        if _in(a, exclude):
            sources[name] = 'DRAM'; census['DRAM'] += 1; continue
        if _in(a, dump):
            sources[name] = 'HW_DUMP'; census['HW_DUMP'] += 1; continue
        if (a & 0xF0000000) not in SRAM_NIBBLES:
            sources[name] = 'MMIO'; census['MMIO'] += 1; continue
        sec, fl = find_sec(a), load_flags(a)
        if sec and sec[2] == 'SHT_NOBITS':
            sources[name] = 'HW_DUMP'; census['HW_DUMP'] += 1
            add_ranges.append((sec[0], sec[1]))
        elif fl is not None and not (fl & PF_W):
            sources[name] = 'SKIP_CONST'; census['SKIP_CONST'] += 1
        elif sec:
            sources[name] = 'HW_DUMP'; census['HW_DUMP'] += 1
            add_ranges.append((sec[0], sec[1]))
        else:
            sources[name] = 'MMIO'; census['MMIO'] += 1
            alarms.append(f"{name} @ 0x{a:08x} (SRAM addr, no section/backing)")

    dump = [(s, e) for s, e in _merge(dump + add_ranges) if not _in(s, exclude)]
    return {
        "segments": [{"base": s, "size": e - s} for s, e in dump],
        "sources": sources,
        "census": dict(census),
        "alarms": alarms,
    }
