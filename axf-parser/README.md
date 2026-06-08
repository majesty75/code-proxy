# UTA AXF Analytics

Decode SRAM dumps from UFS-flash test boards into structured metrics, using each
firmware's AXF debug info. A TRACE32 PRACTICE script dumps a core's SRAM banks
(non-intrusively, while the CPU runs); a **dump agent** packages them into one
container and publishes to **NATS JetStream**; a **decode service** picks the
matching AXF layout, decodes every global to JSON, promotes a curated set of
scalars into **ClickHouse**, and **Grafana** plots them against test-elapsed
time. The full nested decode is archived per dump for ML.

This runs *alongside* the existing interlude log pipeline, in its own tables.

> **Detailed documentation lives in [`docs/`](docs/README.md)** — architecture,
> decode internals, the pipeline, database, configuration, tools, operations, and
> the TRACE32 dump. This README is the quickstart; `docs/` is the reference.

## Architecture

```
 rack host (TRACE32)          analytics server
 ┌──────────────┐   .bank   ┌───────────┐  event+object  ┌────────────────┐
 │ dump_cores   ├──────────►│ dump_agent├───────────────►│  NATS JetStream│
 │ .cmm (PRACTICE)│  banks  │ (package) │   uta.axf.dump  │ stream + objstore│
 └──────────────┘           └───────────┘                └───────┬────────┘
                                                                  │ pull
                              ┌──────────────┐  read-only         ▼
                              │  UTA SQLite  │◄────────┐  ┌────────────────┐
                              │ (trname,fw,  │         └──┤ decode_service │
                              │  start)      │            │  layout match  │
                              └──────────────┘            │  decode_all    │
                                                          │  flatten+curate│
                                  ┌────────────┐  insert  └───────┬────────┘
                                  │ ClickHouse │◄─────────────────┘
                                  │ axf_* tables│
                                  └─────┬──────┘
                                        │  query
                                  ┌─────▼──────┐
                                  │  Grafana   │
                                  └────────────┘
```

## Layout

| Path | What |
|---|---|
| `core/` | reusable library: `dwarf_layout`, `segments`, `container`, `decode`, `flatten`, `fw_name`, `coerce` |
| `tools/` | `build_layout` (register an AXF), `decode_cli` (offline decode), `emit_practice`, demo seeders, `probe` |
| `services/decode_service/` | NATS consumer → decode → ClickHouse |
| `services/dump_agent/` | watch bank files → package container → publish to NATS |
| `clickhouse/init/02-axf-schema.sql` | the four `axf_*` tables |
| `config/layouts/` | the AXF registry: one `layout.json` per firmware build (keyed by build hash) |
| `config/variables.yaml` | curated keys promoted to `axf_metrics`, per product/core |
| `nats/`, `grafana/`, `practice/` | infra config + the PRACTICE dump script |
| `tests/` | offline decode round-trip |
| `scratch/` | original POC scripts + analysis notes (superseded by `core/`) |

## Key design points

- **One container per core.** Globals are scattered across non-contiguous SRAM
  banks, so PRACTICE dumps each bank and the agent packs them into one `.bin`
  with a header (`core/container.py`) — one object per core through the pipeline.
- **Coverage-driven dump set.** `build_layout` derives the banks to dump from the
  AXF (writable PT_LOAD + SRAM `.bss`, minus off-chip DRAM) and cross-checks every
  global, so nothing is silently lost. See `core/segments.py`.
- **No confident garbage.** A variable whose address isn't in the dump becomes
  `{"__error__":"not in dump"}` — never a wrong number read from offset 0.
- **AXF routing by build hash.** The decode service maps a dump to its layout via
  the firmware build hash (parsed from UTA's `fwname`). Content-based routing can
  be added later if firmware exposes a fixed-address build-info block.
- **Curated vs archived.** 10–50 keys per product/core go to `axf_metrics` for
  dashboards; the full decode lives in `axf_snapshots.decoded_json` for ML and
  can backfill new curated keys with no migration.

## Quick start (offline, no infra)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. register an AXF -> layout.json (run once per firmware build)
.venv/bin/python -m tools.build_layout firmware.axf --core M --fw-name "<fwname>"

# 2. decode a packaged dump against it
.venv/bin/python -m tools.decode_cli config/layouts/<KEY>.json dump.bin --flat

# run the offline round-trip test
.venv/bin/python -m pytest tests/ -q
```

## End-to-end demo (Docker)

Uses a TRACE32 demo AXF as stand-in firmware; no hardware needed.

```bash
# register the demo AXF (RTEMS ARM Cortex-M)
.venv/bin/python -m tools.build_layout \
  $T32/demo/arm/kernel/rtems/ticker-arm.elf --core M \
  --fw-name RTEMS_ARMCM_V1_TLC_256Gb_P01_RC00_FW00_deadbeef1_20250101

# stand-in UTA SQLite (trname / fwname / start)
.venv/bin/python -m tools.make_demo_uta uta_demo.sqlite
echo "UTA_SQLITE=/uta/uta_demo.sqlite" > .env     # mount path inside container

# bring up nats + clickhouse + grafana + services
docker compose up -d --build

# simulate a dump: write per-bank files into ./dropzone (agent picks them up)
.venv/bin/python -m tools.seed_dropzone \
  $T32/demo/arm/kernel/rtems/ticker-arm.elf config/layouts/RTEMS_M_deadbeef1.json \
  --slot R7S1-01 --dropzone ./dropzone
```

Then open Grafana at <http://localhost:3000> (anonymous admin) → **AXF Analytics**,
or query ClickHouse:

```bash
curl 'http://localhost:8123/?query=SELECT key,value_num FROM uta.axf_metrics FORMAT Pretty'
```

> The demo mounts `uta_demo.sqlite`; in production point `UTA_SQLITE` at the real
> UTA SQLite (read-only) or wire `services/decode_service/uta_lookup.py` to an API.

## Per-firmware workflow (production)

1. New firmware build arrives → `build_layout` registers its `layout.json`
   (glance at the one-line output; act only on a `!! REVIEW` SRAM-loss warning).
2. `emit_practice config/layouts/<KEY>.json --slot <SLOT>` generates the concrete
   `Data.SAVE.Binary` lines for the rack's PRACTICE dump.
3. Everything else is automatic: dump → agent → NATS → decode → ClickHouse → Grafana.
```
