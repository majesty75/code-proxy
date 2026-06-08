# 07 — Tools reference

All CLIs run from the repo root with the project venv:
`python -m tools.<name> …` (the docs use `.venv/bin/python` where a venv is set up).

## build_layout — register an AXF
```
python -m tools.build_layout <firmware.axf> --core <H|F|M|N> [--fw-name NAME] [--out DIR]
```
Parses DWARF → types + global addresses, derives the dump segment map, parses
firmware metadata, and writes `config/layouts/<product>_<core>_<hash>.json`.
Run **once per firmware build**. Watch the one-line census; act only on
`!! REVIEW`. `--fw-name` defaults to the AXF file stem. See
[02-layout-build](02-layout-build.md).

## layout_view — read a layout (structure / values / C)
```
python -m tools.layout_view <layout.json>                     # index of all globals
python -m tools.layout_view <layout.json> <SYMBOL> [--depth N]# type tree, offsets, sizes, bank
python -m tools.layout_view <layout.json> <SYMBOL> --bin DUMP # tree + LIVE decoded values
python -m tools.layout_view <layout.json> <SYMBOL> --c        # pseudo-C struct decls
python -m tools.layout_view <layout.json> --grep TEXT         # search globals by name
```
The readable front-end over the machine layout. `--bin` overlays values decoded
from a container (same as the pipeline). `--c` emits offset-annotated structs for
cross-referencing firmware headers (types use typedef names; pointer targets by
name — for reading, not guaranteed-compilable).

## decode_cli — decode a dump offline
```
python -m tools.decode_cli <layout.json> <dump.bin> [--symbol NAME] [--flat]
                           [--max-deref-depth N] [--out FILE]
```
No infra needed. Default decodes every `HW_DUMP` global to nested JSON; `--symbol`
limits to one; `--flat` prints `section⇥key⇥value` rows (the curated input form).

## elf_to_container — build a test fixture from an AXF
```
python -m tools.elf_to_container <firmware.axf> <layout.json> <out.bin>
```
Packs the AXF's own loadable image (initialized data present, `.bss` zeroed) into
a UTAX container — a boot-time (t=0) stand-in for a real hardware dump, so you can
exercise the full decode path with no board.

## emit_practice — generate the PRACTICE dump script
```
python -m tools.emit_practice <layout.json> --slot R7S1-01 [--outdir C:/uta/dumps] > dump_M.cmm
```
Emits one `Data.SAVE.Binary` line per bank (from the layout's `segments`), with
the bank-filename contract baked in. See [09-trace32-dump](09-trace32-dump.md).

## probe — non-sensitive structural probe of an AXF
```
python -m tools.probe <firmware.axf>
```
Prints ELF class/endianness, DWARF versions, PT_LOAD segments, ALLOC sections, and
a histogram of variable location opcodes (how many globals are extractable). Emits
**no** symbol names or values — safe to share for diagnosing a new product's map.

## seed_dropzone — demo: simulate a dump (no hardware)
```
python -m tools.seed_dropzone <firmware.axf> <layout.json> --slot R7S1-01 \
       --dropzone ./dropzone [--date YYYYMMDD] [--time HHMMSS]
```
Writes per-bank `.bank` files into the dropzone exactly as PRACTICE would, so the
agent → NATS → decode_service pipeline runs end-to-end.

## make_demo_uta — demo: stand-in UTA SQLite
```
python -m tools.make_demo_uta <out.sqlite> [--board R7S1-01] [--trname …]
       [--fwname …] [--start ISO8601]
```
Creates `app_board(boardname, trname, fwname, start)` so the decode service can
resolve runtime facts without the real UTA DB.

## Typical flows

**Register + inspect a new firmware**
```
python -m tools.build_layout fw.axf --core H --fw-name "<fwname>"
python -m tools.layout_view config/layouts/<KEY>.json --grep <something>
python -m tools.layout_view config/layouts/<KEY>.json "<Some::Var>" --depth 3
```

**Decode a real dump offline**
```
python -m tools.decode_cli config/layouts/<KEY>.json dump.bin --flat | less
```

**Full local demo (no hardware)** — see [08-operations](08-operations.md).
