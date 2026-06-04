#!/usr/bin/env python3
"""
Decode SRAM dumps into JSON using a layout (process_elf.py) + segment map
(regions.py). Reliable successor to map_bin.py.

Memory model
------------
The dump is a SET of segments, each a contiguous byte range at a known base
(no single hardcoded bin_base). A variable at absolute address A is read from
the segment that covers [A, A+size). If no segment covers it, the field is
reported as {"__error__": "not in dump", ...} -- never silently read from the
wrong place. This is what turns "confident garbage" into a visible gap.

Dump packaging contract (per core, produced by the PRACTICE dump script)
------------------------------------------------------------------------
  <core>.regions.json        segment map [{base,size},...]  (from regions.py)
  <core>_<base:08x>.bin       raw bytes for each segment, len == size

Every .bin length is validated against the manifest before decoding; a torn
or short dump is rejected loudly instead of decoded.

Usage
-----
  python decode.py <layout.json> <regions.json> <bindir> <symbol|--all> \
      [--core CORE] [--max-deref-depth N] [--out out.json]
"""
import argparse
import json
import struct
import sys
from pathlib import Path

ENDIAN = '<'


# --------------------------------------------------------------------------
# Segmented memory
# --------------------------------------------------------------------------
class Memory:
    def __init__(self, segments):
        # segments: list of (base, data: bytes). Kept sorted by base.
        self.segs = sorted(segments, key=lambda s: s[0])

    def _seg_for(self, addr):
        for base, data in self.segs:
            if base <= addr < base + len(data):
                return base, data
        return None

    def covers(self, addr, n=1):
        s = self._seg_for(addr)
        if not s:
            return False
        base, data = s
        return addr + n <= base + len(data)

    def read(self, addr, n):
        """Return exactly n bytes at addr, or None if not fully covered by
        a single segment (we never stitch across a gap)."""
        s = self._seg_for(addr)
        if not s:
            return None
        base, data = s
        off = addr - base
        if off + n > len(data):
            return None
        return data[off:off + n]

    @classmethod
    def from_layout(cls, layout, bindir, core=None):
        stem = core or layout.get('core', 'core')
        segs, errors = [], []
        for seg in layout['segments']:
            base, size = seg['base'], seg['size']
            f = Path(bindir) / f"{stem}_{base:08x}.bin"
            if not f.exists():
                errors.append(f"missing segment file {f.name}")
                continue
            data = f.read_bytes()
            if len(data) != size:
                errors.append(
                    f"{f.name}: length {len(data)} != manifest size {size} "
                    f"(torn/short dump)")
                continue
            segs.append((base, data))
        return cls(segs), errors


# --------------------------------------------------------------------------
# Type sizing
# --------------------------------------------------------------------------
def get_type_size(type_id, types):
    if not type_id or type_id not in types:
        return 0
    t = types[type_id]
    if t['tag'] == 'alias':
        return get_type_size(t.get('target_id'), types)
    if t['tag'] == 'array':
        elem = get_type_size(t.get('element_type_id'), types)
        count = 1
        for d in t.get('dimensions', []):
            count *= d
        return count * elem
    return t.get('size', 0)


# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------
def read_array(elem_tid, dims, addr, ctx, depth):
    if not dims:
        return decode(elem_tid, addr, ctx, depth)
    count, sub = dims[0], dims[1:]
    elem_size = get_type_size(elem_tid, ctx['types'])
    for d in sub:
        elem_size *= d
    return [read_array(elem_tid, sub, addr + i * elem_size, ctx, depth)
            for i in range(count)]


def decode(type_id, addr, ctx, depth=0, ptr_hist=None):
    if ptr_hist is None:
        ptr_hist = set()
    types = ctx['types']
    if not type_id or type_id not in types:
        return {"__error__": "unknown type"}

    layout = types[type_id]
    tag = layout['tag']
    if tag == 'alias':
        return decode(layout.get('target_id'), addr, ctx, depth, ptr_hist)

    size = get_type_size(type_id, types)
    mem = ctx['mem']

    if tag == 'base':
        chunk = mem.read(addr, size)
        if chunk is None:
            return {"__error__": "not in dump", "addr": f"0x{addr:08x}"}
        enc = layout.get('encoding', 0)
        if size == 4 and enc == 4:
            fmt = 'f'
        elif size == 8 and enc == 4:
            fmt = 'd'
        elif size == 1:
            fmt = '?' if enc == 2 else ('b' if enc == 5 else 'B')
        elif size == 2:
            fmt = 'h' if enc == 5 else 'H'
        elif size == 4:
            fmt = 'i' if enc == 5 else 'I'
        elif size == 8:
            fmt = 'q' if enc == 5 else 'Q'
        else:
            return chunk.hex()
        try:
            return struct.unpack(ENDIAN + fmt, chunk)[0]
        except Exception:
            return chunk.hex()

    if tag == 'pointer':
        chunk = mem.read(addr, size)
        if chunk is None:
            return {"__error__": "not in dump", "addr": f"0x{addr:08x}"}
        ptr = struct.unpack(ENDIAN + ('I' if size == 4 else 'Q'), chunk)[0]
        ptr_str = f"0x{ptr:08x}"
        tgt = layout.get('target_id')
        if (ptr != 0 and tgt and depth < ctx['max_depth']
                and ptr not in ptr_hist and mem.covers(ptr)):
            ptr_hist.add(ptr)
            deref = decode(tgt, ptr, ctx, depth + 1, ptr_hist)
            ptr_hist.discard(ptr)
            return {"@": ptr_str, "->": deref}
        return ptr_str

    if tag == 'array':
        return read_array(layout.get('element_type_id'),
                          layout.get('dimensions', []), addr, ctx, depth)

    if tag in ('struct', 'union'):
        result = {}
        for name, m in layout.get('members', {}).items():
            maddr = addr + m.get('offset', 0)
            if 'bit_size' in m:
                result[name] = decode_bitfield(m, maddr, ctx)
            else:
                result[name] = decode(m.get('type_id'), maddr, ctx, depth, ptr_hist)
        return result

    if tag == 'enum':
        chunk = mem.read(addr, size)
        if chunk is None:
            return {"__error__": "not in dump", "addr": f"0x{addr:08x}"}
        val = struct.unpack(ENDIAN + ('I' if size == 4 else 'B'), chunk)[0] \
            if size in (1, 4) else int.from_bytes(chunk, 'little')
        return layout.get('enumerators', {}).get(str(val), val)

    chunk = mem.read(addr, size) if size else None
    return chunk.hex() if chunk else {"__error__": "undecodable", "tag": tag}


def decode_bitfield(m, addr, ctx):
    m_size = get_type_size(m.get('type_id'), ctx['types']) or 4
    chunk = ctx['mem'].read(addr, m_size)
    if chunk is None:
        return {"__error__": "not in dump", "addr": f"0x{addr:08x}"}
    fmt = {1: 'B', 2: 'H', 4: 'I', 8: 'Q'}.get(m_size, 'I')
    raw = struct.unpack(ENDIAN + fmt, chunk)[0]
    bits = m['bit_size']
    if 'data_bit_offset' in m:                       # DWARF4+
        return (raw >> m['data_bit_offset']) & ((1 << bits) - 1)
    if 'bit_offset' in m:                            # DWARF2/3 (big-endian numbering)
        shift = m_size * 8 - m['bit_offset'] - bits
        return (raw >> shift) & ((1 << bits) - 1)
    return raw


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('layout', help="layout.json from build_layout.py")
    ap.add_argument('bindir')
    ap.add_argument('symbol', help="symbol name, or --all")
    ap.add_argument('--core')
    ap.add_argument('--max-deref-depth', type=int, default=4)
    ap.add_argument('--out')
    args = ap.parse_args()

    layout = json.loads(Path(args.layout).read_text())
    mem, errors = Memory.from_layout(layout, args.bindir, args.core)
    if errors:
        for e in errors:
            print(f"!! {e}", file=sys.stderr)
        if not mem.segs:
            sys.exit("no usable segments; aborting")

    ctx = {'types': layout['types'], 'mem': mem,
           'max_depth': args.max_deref_depth}

    variables = layout['variables']
    targets = list(variables) if args.symbol == '--all' else [args.symbol]

    out = {}
    for name in targets:
        if name not in variables:
            out[name] = {"__error__": "symbol not in layout"}
            continue
        v = variables[name]
        if not mem.covers(v['address']):
            out[name] = {"__error__": "not in dump", "addr": f"0x{v['address']:08x}"}
            continue
        out[name] = decode(v['type_id'], v['address'], ctx)

    result = out if args.symbol == '--all' else out[args.symbol]
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
