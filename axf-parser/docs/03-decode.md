# 03 — Decode (bin → JSON)

How a packaged dump becomes nested JSON, and the reliability guarantees that come
from the memory model. Implemented in `core/container.py`, `core/decode.py`,
`core/flatten.py`.

## The container format (one file per core)

Globals are scattered across non-contiguous SRAM banks separated by unmapped
gaps, so a single spanning dump could fault. PRACTICE dumps each bank; the dump
agent packs them into **one** `.bin` with a header describing each bank's base.

```
offset  field
0       magic     b"UTAX"        (4 bytes)
4       version   1              (1 byte)
5       hlen      uint32 LE      (length of the JSON header)
9       header    UTF-8 JSON     (hlen bytes)
9+hlen  payload   concatenated bank bytes, in header order
```

Header JSON:
```json
{ "core": "H", "created": "2025-06-03T14:35:22",
  "segments": [ {"base": 536870912, "size": 104888, "offset": 0},
                {"base": 1073774592, "size": 149284, "offset": 104888} ] }
```
`offset` is relative to the start of `payload`. `core/container.py` provides
`write_container`, `read_container`, `parse_container`.

Why per-bank-with-header rather than one flat blob: each bank self-validates by
length, and the decoder reconstructs exact `(base → bytes)` mapping.

## Segmented memory

`core/decode.Memory` holds the banks as `[(base, data)]` and answers two things:

- `covers(addr, n)` — are `n` bytes at `addr` fully inside one bank?
- `read(addr, n)` — those bytes, or `None` if not fully covered (it never
  stitches across a gap).

This is the reliability core: an address that falls outside every bank yields
`None`, which the decoder turns into a visible error, **never** offset-0 bytes.

Construct it from a container:
```python
from core.decode import Memory
mem = Memory.from_container("dump.bin")          # from a file
mem = Memory.from_container_bytes(raw)           # from bytes (the service)
```

## The decode algorithm

`decode_all(layout, mem, sources=None, max_depth=4)` returns
`(decoded: dict, error_cnt: int, status)` where status is `OK` / `PARTIAL` /
`FAILED`. For each global tagged `HW_DUMP` (when `sources` is given), it walks the
type at the variable's address:

| type | behaviour |
|---|---|
| `base` | `read(size)` then `struct.unpack` per `(size, encoding)` — int/uint/float/bool/char |
| `pointer` | read the address; if non-zero, in-dump, within depth, and not already visited → follow into the target type, emitting `{"@": "0x…", "->": <target>}`; else show the raw address |
| `array` | recurse per element across all dimensions |
| `struct`/`union` | recurse each member at `addr + member.offset`; unions get `"_union": true` (all members shown — the active one is unknowable statically) |
| `enum` | read the value, map to the enumerator name if known |
| `alias` | transparently resolve to the underlying type |
| bitfield member | mask/shift from its storage unit (DWARF4 `data_bit_offset`, or DWARF2/3 `bit_offset`) |
| out of dump | `{"__error__": "not in dump", "addr": "0x…"}`, `error_cnt += 1` |

### Pointer-following bounds
Three independent guards prevent blow-up or fabrication:
1. **depth** — `max_depth` (default 4) caps nesting.
2. **cycle** — a per-path visited-set stops `a→b→a`.
3. **in-dump** — `mem.covers(ptr)` must be true; a pointer into memory we didn't
   dump is shown as a bare address, not invented structure.

This is what lets dynamically-allocated queue entries be reconstructed *when their
pool is in the dump*, without ever inventing them when it isn't.

### Status semantics
- `OK` — at least one variable decoded, zero per-leaf errors.
- `PARTIAL` — decoded, but some leaves were out-of-dump (or no elapsed anchor).
- `FAILED` — nothing decoded (empty/garbage dump) → routed to `DECODE_FAIL`.

A single bad variable never raises; only a wholly unreadable dump fails.

## Flatten (nested → leaf rows)

`core/flatten.flatten(decoded)` walks the nested decode into a flat list of
`{section, key, value}`:

- `section` = the top-level global name; `key` = the full dotted path.
- arrays use the index: `counters[0].value → counters.0.value`.
- pointer wrappers are followed transparently (`"->"` target is descended).
- decode-error leaves (`__error__`) are **dropped** (absent, not zero).
- bools become `0/1`.

Flatten output feeds curated selection (see [06-configuration](06-configuration.md)).
The full nested decode (not the flattened form) is what gets archived in
`axf_snapshots.decoded_json`.

## Reliability guarantees, restated

| Guarantee | Where it comes from |
|---|---|
| Out-of-dump address ⇒ visible error, never wrong bytes | `Memory.read` returns `None` → `{"__error__":"not in dump"}` |
| Torn / short dump ⇒ rejected | container bank length validated vs manifest (service load) |
| Pointer chase can't explode or fabricate | depth + cycle + in-dump gates |
| One bad field ⇒ dump still ingested | per-leaf null + `decode_status=PARTIAL` |
| Endianness correct | from the layout (`little`) used in every `unpack` |

## Offline use

```bash
# decode every HW_DUMP global to nested JSON
python -m tools.decode_cli config/layouts/<KEY>.json dump.bin

# one variable, flattened to rows
python -m tools.decode_cli config/layouts/<KEY>.json dump.bin --symbol Configuration --flat

# build a container straight from an AXF image (a t=0 fixture, no hardware)
python -m tools.elf_to_container firmware.axf config/layouts/<KEY>.json fixture.bin
```

See [07-tools](07-tools.md) for full CLI options and
[tests/test_roundtrip.py](../tests/test_roundtrip.py) for a minimal worked example
(struct + array + enum + not-in-dump).
