"""Segmented-memory decoder: turn a packaged dump + layout into nested JSON.

A variable resolves to whichever segment covers its address; anything outside
every segment becomes {"__error__": "not in dump"} instead of silently reading
the wrong bytes. This is the core reliability property.

Public API:
    Memory.from_banks([(base, data)])      -> Memory
    Memory.from_container(path)            -> Memory
    decode_all(layout, mem, sources=None)  -> (decoded:dict, error_cnt, status)
"""
import struct

from .container import read_container

ENDIAN = "<"


class Memory:
    def __init__(self, banks):
        self.banks = sorted(banks, key=lambda b: b[0])   # [(base, data)]

    @classmethod
    def from_banks(cls, banks):
        return cls(list(banks))

    @classmethod
    def from_container(cls, path):
        _, banks = read_container(path)
        return cls(banks)

    @classmethod
    def from_container_bytes(cls, raw):
        from .container import parse_container
        _, banks = parse_container(raw)
        return cls(banks)

    def _bank(self, addr):
        for base, data in self.banks:
            if base <= addr < base + len(data):
                return base, data
        return None

    def covers(self, addr, n=1):
        b = self._bank(addr)
        return bool(b) and addr + n <= b[0] + len(b[1])

    def read(self, addr, n):
        b = self._bank(addr)
        if not b:
            return None
        off = addr - b[0]
        if off + n > len(b[1]):
            return None
        return b[1][off:off + n]


def _size(type_id, types):
    if not type_id or type_id not in types:
        return 0
    t = types[type_id]
    if t['tag'] == 'alias':
        return _size(t.get('target_id'), types)
    if t['tag'] == 'array':
        elem = _size(t.get('element_type_id'), types)
        n = 1
        for d in t.get('dimensions', []):
            n *= d
        return n * elem
    return t.get('size', 0)


class _Ctx:
    __slots__ = ("types", "mem", "max_depth", "errors")

    def __init__(self, types, mem, max_depth):
        self.types = types
        self.mem = mem
        self.max_depth = max_depth
        self.errors = 0


def _not_in_dump(ctx, addr):
    ctx.errors += 1
    return {"__error__": "not in dump", "addr": f"0x{addr:08x}"}


def _array(elem_tid, dims, addr, ctx, depth):
    if not dims:
        return _decode(elem_tid, addr, ctx, depth)
    count, sub = dims[0], dims[1:]
    elem = _size(elem_tid, ctx.types)
    for d in sub:
        elem *= d
    return [_array(elem_tid, sub, addr + i * elem, ctx, depth) for i in range(count)]


def _bitfield(m, addr, ctx):
    msize = _size(m.get('type_id'), ctx.types) or 4
    chunk = ctx.mem.read(addr, msize)
    if chunk is None:
        return _not_in_dump(ctx, addr)
    fmt = {1: 'B', 2: 'H', 4: 'I', 8: 'Q'}.get(msize, 'I')
    raw = struct.unpack(ENDIAN + fmt, chunk)[0]
    bits = m['bit_size']
    if 'data_bit_offset' in m:                      # DWARF4+
        return (raw >> m['data_bit_offset']) & ((1 << bits) - 1)
    if 'bit_offset' in m:                           # DWARF2/3 (big-endian numbering)
        shift = msize * 8 - m['bit_offset'] - bits
        return (raw >> shift) & ((1 << bits) - 1)
    return raw


def _decode(type_id, addr, ctx, depth=0, ptr_hist=None):
    if ptr_hist is None:
        ptr_hist = set()
    types = ctx.types
    if not type_id or type_id not in types:
        return {"__error__": "unknown type"}
    layout = types[type_id]
    tag = layout['tag']
    if tag == 'alias':
        return _decode(layout.get('target_id'), addr, ctx, depth, ptr_hist)
    size = _size(type_id, types)
    mem = ctx.mem

    if tag == 'base':
        chunk = mem.read(addr, size)
        if chunk is None:
            return _not_in_dump(ctx, addr)
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
            return _not_in_dump(ctx, addr)
        ptr = struct.unpack(ENDIAN + ('I' if size == 4 else 'Q'), chunk)[0]
        ptr_str = f"0x{ptr:08x}"
        tgt = layout.get('target_id')
        if ptr and tgt and depth < ctx.max_depth and ptr not in ptr_hist and mem.covers(ptr):
            ptr_hist.add(ptr)
            deref = _decode(tgt, ptr, ctx, depth + 1, ptr_hist)
            ptr_hist.discard(ptr)
            return {"@": ptr_str, "->": deref}
        return ptr_str

    if tag == 'array':
        return _array(layout.get('element_type_id'), layout.get('dimensions', []), addr, ctx, depth)

    if tag in ('struct', 'union'):
        out = {}
        if tag == 'union':
            out['_union'] = True
        for name, m in layout.get('members', {}).items():
            maddr = addr + m.get('offset', 0)
            out[name] = _bitfield(m, maddr, ctx) if 'bit_size' in m \
                else _decode(m.get('type_id'), maddr, ctx, depth, ptr_hist)
        return out

    if tag == 'enum':
        chunk = mem.read(addr, size)
        if chunk is None:
            return _not_in_dump(ctx, addr)
        val = struct.unpack(ENDIAN + ('I' if size == 4 else 'B'), chunk)[0] \
            if size in (1, 4) else int.from_bytes(chunk, 'little')
        return layout.get('enumerators', {}).get(str(val), val)

    chunk = mem.read(addr, size) if size else None
    return chunk.hex() if chunk else {"__error__": "undecodable", "tag": tag}


def decode_variable(layout, mem, name, max_depth=4):
    types = layout['types']
    v = layout['variables'].get(name)
    if not v:
        return {"__error__": "symbol not in layout"}, 0
    ctx = _Ctx(types, mem, max_depth)
    if not mem.covers(v['address']):
        return _not_in_dump(ctx, v['address']), ctx.errors
    return _decode(v['type_id'], v['address'], ctx), ctx.errors


def decode_all(layout, mem, sources=None, max_depth=4):
    """Decode every HW_DUMP global to nested JSON.

    sources: optional {name: source} from segments.derive; if given, only
    variables tagged HW_DUMP are decoded (const/MMIO/DRAM are skipped). If None,
    every variable in the layout is attempted.

    Returns (decoded:dict, error_cnt:int, status:str) where status is
    OK / PARTIAL / FAILED.
    """
    types = layout['types']
    ctx = _Ctx(types, mem, max_depth)
    out = {}
    decoded_any = False
    for name, v in layout['variables'].items():
        if sources is not None and sources.get(name) != 'HW_DUMP':
            continue
        if not mem.covers(v['address']):
            out[name] = _not_in_dump(ctx, v['address'])
            continue
        out[name] = _decode(v['type_id'], v['address'], ctx)
        decoded_any = True
    if not decoded_any:
        return out, ctx.errors, "FAILED"
    return out, ctx.errors, ("PARTIAL" if ctx.errors else "OK")
