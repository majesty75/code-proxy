# 02 — Layout build (AXF → layout.json)

Run **once per firmware build**. Turns an AXF into a `layout.json` the decoder
reuses for every dump. Implemented by `tools/build_layout.py` over
`core/dwarf_layout.py` + `core/segments.py` + `core/fw_name.py`.

```bash
python -m tools.build_layout <firmware.axf> --core <H|F|M|N> --fw-name "<fwname>"
# -> config/layouts/<product>_<core>_<build_hash>.json
```

The one-line output is the only thing to watch; act only on a `!! REVIEW` line.

```
ticker-arm.elf: 176 globals | dump 4.14 MiB in 3 banks | HW_DUMP 176 SKIP_CONST 0 DRAM 0 MMIO 0
  registry key: RTEMS_M_deadbeef1
  -> config/layouts/RTEMS_M_deadbeef1.json
```

## What's in a layout.json

```jsonc
{
  "types":      { "<die_offset>": { ...type node... }, ... },  // the type graph
  "variables":  { "<qualified name>": { "address": int, "type_id": "<die_offset>" } },
  "segments":   [ { "base": int, "size": int }, ... ],         // banks to dump
  "sources":    { "<var name>": "HW_DUMP|SKIP_CONST|DRAM|MMIO" },
  "core": "M", "endianness": "little",
  "product": "...", "fw_build_hash": "...", "fw_name": "...",
  "product_version": "...", "nand_type": "...", "nand_density": "...",
  "patch_version": "...", "release_candidate": "...", "firmware_version": "..."
}
```

Keys you'll care about: `variables` (what can be decoded), `segments` (what must
be dumped), `fw_build_hash` (the routing key, also encoded in the filename).

## Step 1 — DWARF → type registry + global addresses

`core/dwarf_layout.parse_dwarf(dwarf)` walks the DWARF graph into a flat
**type registry** keyed by DIE offset. Each node has a `tag`:

| tag | fields | meaning |
|---|---|---|
| `base` | `name`, `size`, `encoding` | int/float/char/bool primitive |
| `pointer` | `size`, `target_id` | pointer; target decoded at runtime |
| `struct` / `union` | `size`, `members{name:{offset,type_id[,bit_size,…]}}`, `name?` | aggregate |
| `array` | `element_type_id`, `dimensions[]` | multi-dim array |
| `enum` | `size`, `enumerators{value:name}`, `name?` | enumeration |
| `alias` | `target_id`, `name?` | typedef / const / volatile |
| `unknown` | `size` | anything not modeled (e.g. function types) |

Cycles (e.g. `struct node *next`) are handled by a "processing" placeholder so a
self-referential type resolves to its own id instead of recursing forever.

### Which variables become globals
A DWARF `DW_TAG_variable` is collected as a decodable global iff:
- it is **not** a `DW_AT_declaration` (extern decl), and
- its `DW_AT_location` is a **`DW_OP_addr`** expression (a fixed absolute
  address), 5 bytes (32-bit) or 9 bytes (64-bit), non-zero.

Locals (`DW_OP_fbreg`), register vars (`DW_OP_regN`), and location-list vars are
intentionally skipped — they have no fixed SRAM address to dump.

### C++ namespace / class-scoped globals
A C++ variable like `UHP::CEXEType::gstCexeContext` is emitted as a definition
DIE that has a `DW_AT_location` but **no `DW_AT_name`** — the name lives on a
declaration DIE referenced by `DW_AT_specification`. `collect_variables`:
1. follows `DW_AT_specification` / `DW_AT_abstract_origin` to get the name + type;
2. rebuilds the **fully-qualified name** by walking the enclosing
   `DW_TAG_namespace` / class / struct scopes — matching what TRACE32 shows.

So C globals keep their plain names; C++ globals get `Namespace::Class::name`.
(Edge case: if the declaration lives in a *different* compilation unit — rare —
the scope walk falls back to the short name; the variable is still captured.)

## Step 2 — derive the dump segment map

`core/segments.derive(elf, variables)` decides **which SRAM ranges to dump**, and
classifies every global. The rule (validated across multiple products/cores):

> **dump = writable `PT_LOAD` segments ∪ SRAM `.bss` sections that hold a global,
> minus the off-chip DRAM aperture.**

Per-global source of truth (`sources` in the layout, and the build census):

| bucket | meaning | dumped? |
|---|---|---|
| `HW_DUMP` | RW RAM / `.bss` / on-chip pool | **yes** |
| `SKIP_CONST` | `const` in read-only flash | no (never changes; not decoded) |
| `DRAM` | off-chip DRAM aperture (`0x60000000–0x80000000`) | no (excluded by policy) |
| `MMIO` | peripheral register aperture (`0x40…`, `0x4c…`, `0xe0…`) | no (a non-intrusive read can bus-fault) |

On-chip SRAM apertures are the top-nibbles `0x0`, `0x2`, `0x9`
(`SRAM_NIBBLES` in `core/segments.py`). The DRAM aperture is `DEFAULT_EXCLUDE`.
If your product's memory map differs, those two constants are the tuning points.

### Why not just "writable PT_LOAD"?
Some `.bss` is placed by the linker just outside the obvious writable segment
(seen on real products). "Writable PT_LOAD" alone silently dropped real SRAM
structs. So the rule **adds the section of any SRAM global that isn't already
covered** — coverage is checked against the actual globals, not assumed.

### The `!! REVIEW` alarm
If a global sits in an SRAM aperture but has no section/PT_LOAD backing (a bare
linker symbol, usually), it's reported:

```
  !! REVIEW — SRAM globals skipped (possible loss):
       someSymbol @ 0x20001234 (SRAM addr, no section/backing)
```

Empty alarm ⇒ the dump set provably covers every SRAM global. Non-empty ⇒ inspect
those addresses; widen `segments` if they're real.

## Step 3 — firmware metadata + write

`core/fw_name.parse_fw_name` extracts metadata from the firmware name, e.g.:

```
SAPPHIRE_SIRIUS_..._P52_RC07_FW00_1ffe5b4ef_20250521.bin
                                  ^^^^^^^^^ build hash (hex token before the date)
```

Fields: `product` (leading token), `product_version` (`V\d+`), `nand_type`,
`nand_density`, `patch_version` (`P\d+`), `release_candidate` (`RC\d+`),
`firmware_version` (`FW\d+`), and **`fw_build_hash`** (the hex token immediately
before the trailing `YYYYMMDD`, required to contain at least one `a–f` so a
pure-decimal field isn't mistaken for it).

The file is written as `config/layouts/<product>_<core>_<build_hash>.json` — this
filename **is** the registry key the decode service looks up.

## Inspecting a layout

Use `layout_view` (see [07-tools](07-tools.md)) — never read the raw graph:

```bash
python -m tools.layout_view config/layouts/<KEY>.json                 # index of globals
python -m tools.layout_view config/layouts/<KEY>.json Configuration   # type tree
python -m tools.layout_view config/layouts/<KEY>.json --grep gstCexe  # search
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `no build hash parsed` | firmware name doesn't match the pattern | pass the real `--fw-name`; check `core/fw_name.py` regex |
| A C++ variable missing | declaration in another CU, or not `DW_OP_addr` | confirm it has a fixed address; check `--grep` |
| `MMIO` count high | many peripheral-register globals (normal) | expected; they can't be dumped |
| `!! REVIEW` lists real structs | SRAM `.bss` with no backing section | add an explicit range to `segments`, or adjust `SRAM_NIBBLES` |
| Dump size too big | DRAM/pool included, or all banks | confirm DRAM excluded; consider scoping cores |
