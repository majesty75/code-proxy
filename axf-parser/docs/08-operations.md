# 08 — Operations

Running the stack, the per-firmware workflow, deployment notes, and
troubleshooting.

## Local dev setup

```bash
cd axf-parser
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q          # or: python tests/test_roundtrip.py
```

The library + tools + tests run with just `pyelftools` + `pyyaml` (+ `pytest`).
The services have their own pinned `requirements.txt` and run in Docker.

## Full end-to-end demo (Docker, no hardware)

Uses a TRACE32 demo AXF as stand-in firmware.

```bash
# 1. register the demo AXF
.venv/bin/python -m tools.build_layout \
  $T32/demo/arm/kernel/rtems/ticker-arm.elf --core M \
  --fw-name RTEMS_ARMCM_V1_TLC_256Gb_P01_RC00_FW00_deadbeef1_20250101

# 2. stand-in UTA SQLite + point .env at it
.venv/bin/python -m tools.make_demo_uta config/uta_demo.sqlite \
  --start "2026-06-04T11:00:00"
echo "UTA_SQLITE=/app/config/uta_demo.sqlite" > .env

# 3. bring up nats + clickhouse + grafana + services
docker compose up -d --build

# 4. simulate a dump (current-dated so it isn't TTL-evicted)
.venv/bin/python -m tools.seed_dropzone \
  $T32/demo/arm/kernel/rtems/ticker-arm.elf config/layouts/RTEMS_M_deadbeef1.json \
  --slot R7S1-01 --dropzone ./dropzone --date 20260604 --time 120000
```

Verify:
```bash
# decode_service should log: decoded … leaves=3653 curated=N status=OK
docker compose logs decode_service | tail
# rows in ClickHouse
curl -s 'http://localhost:8123/?password=uta' --data-binary \
  'SELECT key,value_num,elapsed_s FROM uta.axf_metrics FORMAT Pretty'
```

Endpoints:
| service | URL | notes |
|---|---|---|
| Grafana | http://localhost:3005 | anonymous admin; folder **AXF** → AXF Analytics |
| ClickHouse | http://localhost:8123 | `?password=uta` |
| NATS monitor | http://localhost:8222 | streams/consumers |

Stop: `docker compose down` (add `-v` to wipe data volumes).

> **TTL note:** demo dumps must be dated *near now*. The `axf_snapshots`/
> `axf_metrics` TTL is on `dump_timestamp + 90d`; a dump dated months ago is
> evicted on merge. See [05-database](05-database.md).

## The per-firmware workflow (production)

1. **New firmware build arrives** → `build_layout` registers its `layout.json`.
   Glance at the one-line census; act only on a `!! REVIEW` SRAM-loss warning.
2. `emit_practice config/layouts/<KEY>.json --slot <SLOT>` → the concrete
   `Data.SAVE.Binary` lines for the rack's PRACTICE dump.
3. Decide curated metrics in `variables.yaml` (use `layout_view`/`decode_cli` to
   find the right leaf paths) and any `transforms.py` preprocessing.
4. Everything else is automatic: dump → agent → NATS → decode → ClickHouse →
   Grafana.

## Deployment topology

- **Rack host (per board, Windows + TRACE32):** PRACTICE dump script + the
  **dump agent** (watches the dump dir, publishes to NATS). Air-gapped — vendor
  Python wheels; run agent via Docker/WSL2 or a packaged exe.
- **Analytics server:** NATS, ClickHouse, Grafana, **decode service**, the AXF
  registry (`config/layouts/`), `variables.yaml`, `transforms.py`. Reads UTA's
  SQLite read-only (shared mount or copy).

Before production:
- **NATS auth** (user/pass or nkey) + at-rest considerations — the demo has none.
- **ClickHouse password** — the demo uses `uta`; set a real secret.
- **Layout registry** — mount/persist `config/layouts/` (append-only; a new build
  is a new file, never an edit).
- **Retention/TTL** — confirm 90d/30d fit your needs (and the `dump_timestamp` vs
  `ingested_at` choice).

## Troubleshooting

| Symptom | Check | Likely fix |
|---|---|---|
| Grafana panel "No data", red triangle | panel is a *time-series* with a numeric time column | use a **Trend** panel with `xField: elapsed_s` (already fixed in the shipped dashboard) |
| `decode_service` exits on start: CH auth | empty-password default user rejected by image | set `CLICKHOUSE_PASSWORD` + `CH_PASS` (compose already does: `uta`) |
| `BucketNotFoundError` on agent | object store not created yet (startup race) | agent retries/creates it; ensure NATS is up |
| `NO_LAYOUT` errors | no registered layout for product+core+hash | run `build_layout` for that firmware; check the registry key matches |
| `ENRICH_ERROR` | UTA lookup failed | check `UTA_SQLITE` path/mount and that `app_board` has the board |
| rows vanish after insert | back-dated `dump_timestamp` past TTL | date dumps near now, or change TTL to `ingested_at` |
| config edit not taking effect | service caches at start | `docker compose restart decode_service` (config is live-mounted); `--build` only for service code changes |
| containers `Exited (255)` | Docker Desktop / machine sleep | `docker compose up -d`; data persists in volumes |
| port already in use (e.g. 3000) | host port clash | change the host side in `docker-compose.yml` (Grafana is on 3005) |

## Health checks

```bash
docker compose ps                                  # all services Up / healthy
docker compose logs -f decode_service              # live decode log
curl -s localhost:8123/ping                         # ClickHouse: "Ok."
curl -s localhost:8222/jsz?streams=1 | jq .         # NATS JetStream state
curl -s 'http://localhost:8123/?password=uta' --data-binary \
  'SELECT error_type,count() FROM uta.axf_decode_errors GROUP BY error_type'
```
