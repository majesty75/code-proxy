# 01 — Architecture

## Problem

UFS-flash test boards run firmware for 7–8 days. The legacy observability is text
logs that only show progress. We want **structured internal state** — firmware
counters, health descriptors, queues, wear stats — sampled over the run, for
dashboards, anomaly detection, and ML.

The firmware's internal variables live in SRAM. TRACE32 can read SRAM
**non-intrusively** (no CPU halt) over the debug port. The firmware's AXF
(ELF + DWARF debug info) tells us *where* each global lives and *what type* it is.
So: dump SRAM → decode against the AXF → structured JSON → metrics.

## Components and data flow

```
 RACK HOST (per board, TRACE32)              ANALYTICS SERVER
 ┌───────────────────────┐                  ┌──────────────────────────────┐
 │ dump_cores.cmm        │  bank .bin files │                              │
 │ (PRACTICE, non-       │─────────────────▶│  dump_agent                  │
 │  intrusive SRAM save) │                  │  • group banks by slot/core  │
 └───────────────────────┘                  │  • pack one UTAX container    │
                                            │  • put object + publish event │
                                            └───────────────┬──────────────┘
                                                            │
                                                  ┌─────────▼─────────┐
                                                  │  NATS JetStream    │
                                                  │  • stream UTA_AXF   │
                                                  │  • object AXF_BINS  │
                                                  └─────────┬─────────┘
                ┌──────────────┐  read-only                 │ pull
                │  UTA SQLite  │◀──────────┐                 ▼
                │  app_board   │           │   ┌────────────────────────────┐
                │ trname/fw/   │           └───┤  decode_service            │
                │ start        │               │  • UTA lookup (runtime)    │
                └──────────────┘               │  • route by build hash     │
                ┌──────────────────┐  read     │  • decode_all → JSON       │
                │ config/layouts/  │◀──────────┤  • flatten + curate+xform  │
                │ *.json (registry)│           │  • write ClickHouse        │
                └──────────────────┘           └───────────────┬────────────┘
                                                               │ insert
                                                     ┌─────────▼─────────┐
                                                     │  ClickHouse        │
                                                     │  axf_sessions      │
                                                     │  axf_snapshots     │
                                                     │  axf_metrics       │
                                                     │  axf_decode_errors │
                                                     └─────────┬─────────┘
                                                               │ query
                                                       ┌───────▼───────┐
                                                       │   Grafana      │
                                                       └───────────────┘
```

There are **two clocks** of work:

- **Offline, once per firmware build:** `build_layout` turns an AXF into a
  `layout.json` in the registry. Slow (DWARF parsing); done once, reused forever.
- **Runtime, once per dump:** everything in the diagram above. No DWARF parsing,
  no human in the loop.

## What lives where

| Concern | Owner | Why |
|---|---|---|
| Type layout + addresses + dump segment map | `config/layouts/<product>_<core>_<hash>.json` | AXF is the source of truth; built once |
| Firmware static metadata (product, nand, …) | the layout file (parsed from fw name at registration) | server's own registry — no UTA dependency for it |
| Runtime facts: TR name, firmware name, **test start time** | UTA SQLite (`app_board`) | only UTA knows which board runs what, and when the test started |
| Which 10–50 metrics to dashboard | `config/variables.yaml` | curation is an analytics decision, editable without code |
| Per-field preprocessing | `config/transforms.py` | unit/derived logic is firmware-specific Python |
| Raw nested decode (ML source of truth) | `axf_snapshots.decoded_json` | faithful, compressed, re-derivable |
| Curated time-series | `axf_metrics` | long-form, dashboard-friendly |

## Key design decisions (and the trade-offs)

### 1. Long-form metrics, not column-per-metric
`axf_metrics` stores `key String, value_num, value_str, unit`. A new metric is a
new **value in the `key` column** → more rows, never a schema change. The
alternative (one typed column per metric) needs an `ALTER TABLE` per field and
can't cope with thousands of per-product variables. Cost: you query with
`WHERE key='…'`. See [05-database](05-database.md).

### 2. The layout is a type *graph*, not a flattened address map
`layout.json` keeps DWARF types as referenced nodes (deduped, lossless). This is
what makes **pointer-following** possible — a pointer's target address is only
known at runtime, so the decoder must read it and then jump to the target's type.
A pre-flattened `(addr,size)` map can't reconstruct a linked queue. Cost: not
human-readable directly — so we render views (`layout_view`) instead. See
[02-layout-build](02-layout-build.md) and [03-decode](03-decode.md).

### 3. The dump set is derived from the AXF and coverage-checked
We dump **writable PT_LOAD + SRAM `.bss` that holds a global, minus off-chip
DRAM**, and cross-check every global so nothing is silently dropped. No
hardcoded `bin_base`. See [02-layout-build](02-layout-build.md).

### 4. One container per core
Globals are scattered across non-contiguous SRAM banks (a single spanning dump
would cross unmapped memory and can bus-fault). PRACTICE dumps each bank; the
agent packs them into **one** `.bin` with a header describing each bank's base.
See [03-decode](03-decode.md) and [09-trace32-dump](09-trace32-dump.md).

### 5. Routing by build hash; runtime facts from UTA
The firmware **build hash** (parsed from the firmware name) pins the exact
binary → exact memory addresses. The server's registry maps hash → layout +
metadata. UTA provides only the per-board runtime facts (TR name, firmware name,
start time). See [04-pipeline](04-pipeline.md).

### 6. Decode raw; preprocess on a separate layer
`decode_all` is faithful and archived. Unit conversion / derived metrics happen
only when building curated `axf_metrics` rows, via pluggable Python transforms,
so the archive stays re-derivable. See [06-configuration](06-configuration.md).

## Reliability properties (what "reliable" concretely means)

| Property | Mechanism | Doc |
|---|---|---|
| Wrong AXF can't produce plausible garbage | build-hash gate (`NO_LAYOUT`/`HASH_MISMATCH`) | 04 |
| Out-of-dump address never read as offset-0 | segmented memory → `{"__error__":"not in dump"}` | 03 |
| Torn / short dumps rejected | container per-bank length validated vs manifest | 03 |
| No silent loss of globals | coverage census + `!! REVIEW` SRAM-loss alarm at build time | 02 |
| Pointer-following can't explode | depth cap + cycle guard + must-be-in-dump gate | 03 |
| One bad field doesn't sink a dump | per-leaf null + `decode_status=PARTIAL`; transform errors skipped | 03, 06 |

## Repository map

```
core/        reusable library (dwarf_layout, segments, container, decode,
             flatten, fw_name, coerce, transforms)
tools/       CLIs: build_layout, decode_cli, layout_view, emit_practice,
             elf_to_container, seed_dropzone, make_demo_uta, probe
services/
  decode_service/  NATS consumer → decode → ClickHouse
  dump_agent/      watch bank files → package → publish to NATS
clickhouse/init/   02-axf-schema.sql
nats/              nats-server.conf
grafana/           provisioning + starter dashboard
config/            variables.yaml, transforms.py, layouts/ (registry)
practice/          dump_cores.cmm (TRACE32)
tests/             offline decode round-trip
docs/              this documentation
scratch/           original POC + analysis (superseded)
```
