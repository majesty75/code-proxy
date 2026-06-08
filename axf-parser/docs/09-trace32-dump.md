# 09 — TRACE32 dump production

The rack side: how SRAM banks are dumped and named so the dump agent can package
them. Reference script: `practice/dump_cores.cmm`; generator: `tools/emit_practice.py`.

## Principles

1. **Non-intrusive.** Do **not** halt the core. `Data.SAVE.Binary` reads over the
   debug access port while the CPU runs. Verify `SYStem.MemAccess` permits
   run-time reads on your target (e.g. `SYStem.MemAccess DAP`). The CPU keeps
   running, so the snapshot is a slightly-inconsistent but live sample — acceptable
   given the 7–8 day test and ~160 min cadence.
2. **One file per bank.** A core's globals span non-contiguous SRAM banks with
   unmapped gaps between them; a single spanning save could touch unmapped memory
   and fault. Dump each bank from the layout's `segments` separately.
3. **Atomic publish.** Write each bank to `.tmp`, then rename to `.bank`, so the
   watcher never reads a partially-written file.

## Which banks to dump

The banks are exactly the layout's `segments` (writable SRAM, coverage-checked,
DRAM excluded — see [02-layout-build](02-layout-build.md)). Generate the concrete
script from a registered layout:

```bash
python -m tools.emit_practice config/layouts/<KEY>.json --slot R7S1-01 \
       --outdir C:/uta/dumps > dump_M.cmm
```

That emits, per bank, a non-halting save + atomic rename with the exact filename
the agent expects.

## Filename contract

Each bank file **must** be named:
```
<slot>_<core>_<YYYYMMDD>_<HHMMSS>_<base08x>.bank
e.g.  R7S1-01_M_20250101_120000_20000000.bank
```
- `slot` — board slot, `R\d+S\d+-\d+` (e.g. `R7S1-01`).
- `core` — single tag matching the layout's `core` (`H`/`F`/`M`/`N`/…).
- `YYYYMMDD_HHMMSS` — dump time; all banks of one dump share it (that's how the
  agent groups them).
- `base08x` — the bank's base address, 8 lowercase hex digits, no `0x`.

The agent parses this with `BANK_RE` in `services/dump_agent/packager.py`; the
timestamp also becomes the event's `dump_timestamp` (and the relative-time anchor
after subtracting the test start).

## Reference skeleton (`practice/dump_cores.cmm`)

```text
; ARGS: &slot &core &outdir
&date=FORMAT.UnixTime("%Y%m%d",CLOCK.UnixTime(),0)
&time=FORMAT.UnixTime("%H%M%S",CLOCK.UnixTime(),0)

; one GOSUB per bank (base,len) from emit_practice / the layout's segments:
GOSUB DUMP_BANK &slot &core &date &time 0x20000000 0x00019988
; ...

DUMP_BANK:
  ENTRY &slot &core &date &time &base &len
  &b8=FORMAT.HEX(8,&base)
  &tmp="&outdir/&slot._&core._&date._&time._&b8..bank.tmp"
  &fin="&outdir/&slot._&core._&date._&time._&b8..bank"
  Data.SAVE.Binary &tmp &base++&len      ; non-halting region save
  OS.Command ren "&tmp" "&fin"           ; atomic -> agent picks it up
  RETURN
```

> `emit_practice.py` produces a ready-to-run version with one explicit
> `Data.SAVE.Binary <tmp> <base>++<len>` + `ren` per bank, so PRACTICE does no
> file parsing. Use it rather than hand-maintaining ranges.

## Cadence & scheduling

Dumps run on a schedule (~160 min is fine; the test runs days). The scheduler that
invokes the `.cmm` (cron, a T32 loop, or the host automation) is out of scope here.

## What the agent does next

The dump agent (see [04-pipeline](04-pipeline.md)) groups a dump's `.bank` files,
waits for them to be stable, packs them into one UTAX container, puts the object in
NATS, publishes the event, and deletes the banks. No layout or AXF is needed on the
rack — only the bank files and their names.
