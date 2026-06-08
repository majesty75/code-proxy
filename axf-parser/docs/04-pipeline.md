# 04 — Pipeline & transport

The runtime path: bank files → dump agent → NATS JetStream → decode service →
ClickHouse. Implemented in `services/dump_agent/` and `services/decode_service/`.

## Dump agent (rack side)

`services/dump_agent/main.py` + `packager.py`. Watches `WATCH_DIR` for bank files
written by PRACTICE.

**Bank filename contract** (`packager.BANK_RE`):
```
<slot>_<core>_<YYYYMMDD>_<HHMMSS>_<base08x>.bank
e.g.  R7S1-01_M_20250101_120000_20000000.bank
```

Flow:
1. **Group** banks by `(slot, core, date, time)` — all banks of one dump.
2. **Wait for stability** — every bank unmodified for `STABLE_SECONDS` (no partial
   reads). PRACTICE's atomic `.tmp → .bank` rename guarantees whole files.
3. **Package** into one UTAX container (bases come from the filenames; no layout
   needed on the rack side).
4. **Put object first, then publish event** (the consumer fetches the object on
   the event; if it published first, the consumer could miss the object → retry).
5. Delete the bank files; remember the group so it isn't reprocessed.

The agent does **no enrichment** — it only knows what the rack host knows. The
decode service resolves the rest.

### Event schema (agent → NATS)
Published to subject `uta.axf.dump.<core>.<boardname>`:
```json
{ "schema_version": 1,
  "object_key": "R7S1-01_M_20250101_120000.bin",
  "boardname":  "R7S1-01",
  "core":       "M",
  "dump_timestamp": "2025-01-01T12:00:00",
  "server_ip":  "10.0.0.12" }
```
The object (the container) is stored separately in the JetStream Object Store
under `object_key`.

## NATS JetStream

Chosen over Kafka: a single static binary (air-gapped-Windows friendly), built-in
**Object Store** for the ~MB containers, and durable streams with replay so a
decode-service outage never loses dumps.

Resources (created idempotently on startup by `decode_service.ensure_jetstream`):

| resource | name | purpose |
|---|---|---|
| stream | `UTA_AXF` | subjects `uta.axf.dump.>`, file storage |
| durable pull consumer | `AXF_DECODER` | explicit ack, `max_deliver=5`, `ack_wait=120s` |
| object store bucket | `AXF_BINS` | the container blobs |

Config in `nats/nats-server.conf` (JetStream on, file store). Monitoring UI on
:8222. **Add auth (user/pass or nkey) before production** — the demo has none.

## Decode service (analytics server)

`services/decode_service/main.py`. Pull-fetches a batch, runs `process_one` per
message, acks/naks. Fatal data problems are written to `axf_decode_errors` and
acked (no poison-message loop); transient problems (CH down, object not yet
present) are nak'd for redelivery.

### process_one, step by step
1. **Parse event JSON.** Missing `object_key`/`boardname`/`core` → `BAD_EVENT`.
2. **Fetch the container** from the Object Store by `object_key`. Not present yet
   → **NAK** (retryable; the object may land just after the event).
3. **UTA lookup** (`uta_lookup.py`) — read-only SQLite query by `boardname` for
   `trname, fwname, start`. Missing/empty → `ENRICH_ERROR`. (Demo fallback: take
   `trname`/`fw_name` from the event if present.)
4. **Route by build hash** — `parse_fw_name(fwname)` → `product`, `build_hash`;
   `LayoutRegistry.get(product, core, build_hash)` opens
   `<product>_<core>_<build_hash>.json`. Missing file → `NO_LAYOUT`; embedded
   hash mismatch → `HASH_MISMATCH`. **Never decode against a non-matching layout.**
5. **Decode** — `decode_all` over the container. Empty result → `DECODE_FAIL`.
6. **Elapsed** — `elapsed_s = dump_timestamp − test_started_at` (clamped ≥ 0). No
   start time → `0` and `decode_status=PARTIAL`.
7. **Curate + transform** — `flatten` then `VariableRegistry.select`
   (per-field Python transforms; see [06-configuration](06-configuration.md)).
8. **Write** — `axf_snapshots` (full decode + status), `axf_metrics` (curated),
   `axf_sessions` (upsert), then **ack**.

### Error taxonomy (`axf_decode_errors.error_type`)
| type | meaning | redelivered? |
|---|---|---|
| `BAD_EVENT` | malformed event JSON / missing fields | no (acked) |
| `ENRICH_ERROR` | UTA lookup failed / empty trname or fwname | no |
| `NO_LAYOUT` | no registered layout for product+core+hash | no |
| `HASH_MISMATCH` | layout's embedded hash ≠ fwname hash | no |
| `DECODE_FAIL` | whole dump unreadable / nothing decoded | no |
| (transient) | CH down, object not yet present | **yes** (nak) |

## Build-hash routing in detail

The build hash is the linchpin (see also [02-layout-build](02-layout-build.md)):

```
UTA: board R7S1-01 runs fwname X
  → parse_fw_name(X).fw_build_hash = "1ffe5b4ef"
  → registry key = "<product>_<core>_1ffe5b4ef"
  → open config/layouts/<product>_<core>_1ffe5b4ef.json
  → verify layout.fw_build_hash == "1ffe5b4ef"   (else HASH_MISMATCH)
```

The hash pins the exact compiled binary → exact addresses. P/RC/FW labels can be
reused across rebuilds; the hash can't. **Current limit:** this trusts that UTA's
`fwname` is correct. The stronger check — read a build-hash *global from the dump*
and compare — is a clean drop-in in `layout_registry` once firmware exposes a
fixed-address build-info block. See [10? / future] note in
[06-configuration](06-configuration.md).

## Where UTA fits

The decode service needs three runtime facts only UTA knows:
`trname`, `fwname`, `test start time`. It reads them **read-only**
(`file:…?mode=ro&immutable=1`) so it never locks the live DB. Everything else —
product, nand, version, and the layout — comes from the server's own registry, so
the analytics side doesn't depend on UTA for firmware metadata.
