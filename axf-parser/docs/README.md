# AXF Analytics — Documentation

Decode SRAM dumps from UFS-flash test boards into structured, queryable metrics
using each firmware's AXF (ELF + DWARF) debug info — then archive, dashboard, and
feed ML, alongside the existing interlude log pipeline.

This folder is the detailed reference. Start with **Architecture**, then read the
chapter for whatever you're doing.

## Table of contents

| # | Doc | Read it when you… |
|---|-----|-------------------|
| 01 | [Architecture](01-architecture.md) | want the whole picture: components, data flow, design decisions |
| 02 | [Layout build (AXF → layout.json)](02-layout-build.md) | register firmware, debug missing globals, tune the dump set |
| 03 | [Decode (bin → JSON)](03-decode.md) | understand the container format, the decoder, reliability guarantees |
| 04 | [Pipeline & transport](04-pipeline.md) | work on the services, NATS, routing, error handling |
| 05 | [Database](05-database.md) | query ClickHouse, understand the long-form model, retention |
| 06 | [Configuration](06-configuration.md) | add metrics, write transforms, set env vars |
| 07 | [Tools reference](07-tools.md) | use the CLIs (build_layout, decode_cli, layout_view, …) |
| 08 | [Operations](08-operations.md) | run it locally, deploy, follow the per-firmware workflow, troubleshoot |
| 09 | [TRACE32 dump production](09-trace32-dump.md) | write/adjust the PRACTICE dump, understand the filename contract |

## The 30-second version

1. **Once per firmware build:** `build_layout` parses the AXF's DWARF into a
   `layout.json` (type registry + global addresses + a coverage-checked dump
   segment map), keyed by firmware **build hash**.
2. **Every ~160 min on the rack:** a PRACTICE script dumps the selected core's
   SRAM banks non-intrusively; the **dump agent** packs them into one container
   and publishes to **NATS JetStream** (object + small event).
3. **On the analytics server:** the **decode service** pulls the event, looks up
   the matching layout by build hash, decodes **all** globals to nested JSON,
   promotes a curated 10–50 scalars (with optional per-field Python transforms)
   to **ClickHouse**, and archives the full decode for ML.
4. **Grafana** plots curated metrics against test-elapsed time.

## Core principles

- **No confident garbage.** A variable whose address isn't in the dump is
  flagged (`{"__error__":"not in dump"}`), never read from the wrong place.
- **Schema never moves for a new field.** Metrics are rows in a long-form table,
  not columns. Add a variable → more rows, zero DDL.
- **Decode stays raw; preprocessing is a separate layer.** The archived decode is
  faithful; unit conversions / derived metrics happen only on the curated path.
- **Everything is derived from the AXF.** The dump set, addresses, and types come
  from the firmware's own debug info — nothing hardcoded per product.
