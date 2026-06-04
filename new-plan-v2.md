---
name: uta-axf-analytics-plan-v2
description: Implementation-grade spec for SRAM-dump + AXF-decode analytics over NATS JetStream, alongside the existing interlude log pipeline
metadata:
  type: reference
  supersedes: new-plan.md
---

# UTA AXF Analytics — Plan v2 (implementation spec)

> **Audience:** an implementer who will copy this almost literally. Every
> section gives exact file paths, schemas, function signatures, configs, and
> acceptance criteria. Where a value is environment-specific it is marked
> `<<FILL>>`. Where a design choice is still open it is marked **OPEN**.
>
> **Golden rule for the implementer:** do NOT invent behaviour. If something
> is ambiguous, write it to `axf_decode_errors` / log it and move on — never
> guess a memory layout, a TR name, or a timestamp.

---

## 0. One-paragraph summary

A TRACE32 PRACTICE script dumps selected cores' SRAM (non-intrusively, while
the CPU runs) to `.bin` files. The UTA Django server enriches each dump with
metadata polled from its SQLite DB (TR name, firmware name, test start time),
then publishes the `.bin` to a **NATS JetStream Object Store** and a small
**metadata event** to a JetStream stream. A decode service on the analytics
server consumes each event, pulls the `.bin`, selects the matching **AXF
layout** (verified by firmware build hash), decodes **all** global variables to
nested JSON, flattens a **curated 10–50 scalars** into a long-form ClickHouse
table for Grafana, and archives the full decode for ML. The existing log
(`interlude`) pipeline keeps running unchanged, in its own tables.

---

## 1. Reuse map (existing code to copy patterns from)

| New component | Copy from | What to reuse |
|---|---|---|
| value coercion | `uta-analytics/parser/src/parsers/interlude.py` → `coerce_value()` | hex→int, unit stripping, `(value_num, value_str, unit)` triple |
| firmware-name parsing | `uta-analytics/parser/src/filename_parser.py` | regex field extraction (product/version/nand/patch/RC/FW) |
| ClickHouse batched writer | `uta-analytics/parser/src/writer.py` | batch+retry insert loop |
| file watcher | `uta-analytics/vector/watcher/watcher.py` | watchdog + `PollingObserver` (reliable on Windows) |
| long-form metric table | `uta-analytics/clickhouse/init/01-schema.sql` → `interlude_metrics` | the `(key, value_num, value_str, unit, elapsed_s)` shape |
| AXF/DWARF decode | `map_axf/process_elf.py`, `map_axf/map_bin.py` (on the Linux box — **vendor into this repo**, see §6) | `parse_dwarf_types()`, `decode_memory()`, `read_multidim_array()` |

**Action:** copy the `map_axf` Python package into
`uta-analytics/axf/decode_service/src/map_axf/` and freeze it (no runtime pip).

---

## 2. Repository layout to create

```
uta-analytics/
├── clickhouse/init/
│   └── 02-axf-schema.sql              # NEW — AXF tables (§5)
├── nats/
│   ├── nats-server.conf               # NEW — JetStream enabled (§4.1)
│   └── docker-compose.yml             # NEW — single nats-server container
├── axf/                               # NEW — runs on ANALYTICS server
│   ├── decode_service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       ├── main.py                # consumer loop (§7.1)
│   │       ├── config.py              # env config (§7.0)
│   │       ├── nats_consumer.py       # pull subscription + object fetch (§7.2)
│   │       ├── layout_registry.py     # AXF layout load/cache + hash gate (§7.3)
│   │       ├── decoder.py             # map_bin wrapper: decode all globals (§7.4)
│   │       ├── flatten.py             # nested dict → leaf scalar rows (§7.5)
│   │       ├── coerce.py              # ported coerce_value (§7.6)
│   │       ├── variable_registry.py   # curated keys per product/core (§7.7)
│   │       ├── ch_writer.py           # batched ClickHouse insert (§7.8)
│   │       ├── models.py              # row dataclasses (§7.9)
│   │       └── map_axf/               # VENDORED decode lib (§6)
│   ├── layouts/                       # generated layout JSON (gitignored, see §6.2)
│   ├── config/
│   │   ├── cores.yaml                 # which cores per product (§3.1)
│   │   └── variables.yaml            # curated keys per product/core (§7.7)
│   └── tools/
│       └── build_layout.py            # one-shot: AXF → layout.json (§6.2)
└── uta_side/                          # NEW — runs on UTA Django server
    ├── dump_watcher/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── src/
    │       ├── watcher.py             # detect new .bin (§8.1)
    │       ├── sqlite_enricher.py     # poll app_board (§8.2)
    │       ├── fw_name_parser.py      # firmware name → metadata (§8.3)
    │       ├── nats_publisher.py      # put object + publish event (§8.4)
    │       └── config.py
    └── practice/
        └── dump_cores.cmm             # TRACE32 PRACTICE dump script (§3.2)
```

---

## 3. Dump production (rack host, TRACE32)

### 3.1 `axf/config/cores.yaml` — which cores to dump per product
Cores are **not fixed per product** and **not all are parsed**. This file is
the single source of truth for both the dump script and the decoder.

```yaml
# product -> list of cores to dump + their SRAM address range to save.
# range is [start, length] in bytes (hex strings ok).
products:
  SIRIUS:
    cores:
      H: { range: ["0x20000000", "0x00100000"] }   # 1 MB
  SAPPHIRE:
    cores:
      F: { range: ["0x10000000", "0x00080000"] }
      M: { range: ["0x10100000", "0x00080000"] }
  UFS_UHP:
    cores:
      H: { range: ["0x20000000", "0x00100000"] }
      F: { range: ["0x30000000", "0x00100000"] }
      M: { range: ["0x30100000", "0x00100000"] }
      N: { range: ["0x30200000", "0x00100000"] }
# default fallback if product not listed: dump nothing, log a warning.
```

### 3.2 `uta_side/practice/dump_cores.cmm` — PRACTICE dump (skeleton)
Key requirement: **non-intrusive** save (no `Break`), and **atomic rename**
(write `.tmp`, rename to `.bin`) so the watcher never reads a partial file.

```text
; ARGS: &slot (e.g. R7S1-01)  &core (e.g. H)  &start (0x...)  &len (0x...)  &outdir
; Non-intrusive read: do NOT halt the core. Data.SAVE.Binary works while running
; over the debug access port. Verify on YOUR target that SYStem.MemAccess allows
; run-time access (e.g. SYStem.MemAccess DAP / Denied=run-time read enabled).

LOCAL &ts &tmp &final
&ts=CLOCK.DATE()+"_"+CLOCK.TIME()        ; produce YYYYMMDD_HHMMSS (format on host)
&tmp="&outdir/&slot._&core._&ts..bin.tmp"
&final="&outdir/&slot._&core._&ts..bin"

Data.SAVE.Binary &tmp &start++&len       ; non-halting region save
OS.Command ren "&tmp" "&final"           ; atomic rename → triggers watcher

ENDDO
```
**Filename contract (MUST match exactly):**
`"<slot>_<core>_<YYYYMMDD>_<HHMMSS>.bin"` e.g. `R7S1-01_H_20250603_143522.bin`.
Regex the rest of the system relies on:
`^(?P<slot>R\d+S\d+-\d+)_(?P<core>[A-Z])_(?P<date>\d{8})_(?P<time>\d{6})\.bin$`

**Cadence:** scheduled every ~160 min (acceptable; tests run 7–8 days). The
scheduler that calls this script is out of scope here — assume cron/T32 loop.

---

## 4. Transport — NATS JetStream

Chosen over Kafka: single static binary, trivial to run air-gapped on Windows,
built-in **Object Store** for the 1 MB `.bin` blobs, durable streams with
replay so a decode-server outage never loses dumps.

### 4.1 `nats/nats-server.conf`
```text
port: 4222
max_payload: 8MB                # event messages are tiny; objects are chunked anyway
jetstream {
  store_dir: "/data/jetstream"
  max_memory_store: 256MB
  max_file_store:   50GB        # sizing: ~46k dumps * 1MB ≈ 46GB/run; tune per retention
}
# Air-gapped: no leafnodes/gateways. Add user/pass or nkey auth before prod.
```

### 4.2 JetStream resources to create (once, via `nats` CLI)
```bash
# Event stream: one small message per dump (the metadata).
nats stream add UTA_AXF \
  --subjects "uta.axf.dump.>" \
  --storage file --retention limits --max-age 168h --max-msgs -1 --replicas 1

# Durable pull consumer for the decode service.
nats consumer add UTA_AXF AXF_DECODER \
  --pull --ack explicit --max-deliver 5 --ack-wait 120s \
  --filter "uta.axf.dump.>"

# Object store bucket for the .bin blobs.
nats object add AXF_BINS --storage file --ttl 168h
```
- **Subject convention:** `uta.axf.dump.<product>.<slot>.<core>`
- **Object key convention:** the `.bin` filename (`R7S1-01_H_20250603_143522.bin`).
- The metadata event (§4.3) carries the object key so the consumer knows what to fetch.

### 4.3 Metadata event schema (JSON published to the subject)
Produced by the UTA side (§8). This is the **complete** contract — the decoder
needs nothing else except the object itself.
```json
{
  "schema_version": 1,
  "object_key":      "R7S1-01_H_20250603_143522.bin",
  "slot_id":         "R7S1-01",
  "core":            "H",
  "dump_timestamp":  "2025-06-03T14:35:22",         // ISO8601, from filename
  "trname":          "RACK8_TRAILRUN_RAJESH",       // app_board.trname
  "fw_name":         "SAPPHIRE_SIRIUS_EVT1_UFS_3_1_V8_TLC_512Gb_ATM_512GB_P52_RC07_FW00_1ffe5b4ef_20250521.bin",
  "test_started_at": "2025-06-02T06:26:18",         // app_board.start (relative-time anchor)
  "product":         "SIRIUS",                       // parsed from fw_name
  "product_version": "V8",
  "fw_build_hash":   "1ffe5b4ef",                    // parsed from fw_name; the AXF-match key
  "nand_type":       "TLC",
  "nand_density":    "512Gb",
  "patch_version":   "P52",
  "release_candidate":"RC07",
  "firmware_version":"FW00",
  "server_ip":       "10.0.0.12"
}
```
Rule: if the UTA side **cannot** resolve `trname`, `fw_name`, or
`test_started_at` from SQLite, it still publishes but sets the field to `""`
and adds `"enrich_error": "<reason>"`. The decoder will route such dumps to
`axf_decode_errors` (no guessing).

---

## 5. ClickHouse schema — `clickhouse/init/02-axf-schema.sql`

Separate tables from `interlude_*` (explicit user decision). New dimension
`core`; full nested decode archived per snapshot for ML.

```sql
CREATE DATABASE IF NOT EXISTS uta;

-- Master: one row per (board, core, TR) run.
CREATE TABLE IF NOT EXISTS uta.axf_sessions
(
    trname            String,
    boardname         String,
    core              LowCardinality(String),
    product           LowCardinality(String),
    product_version   LowCardinality(String),
    fw_name           String,
    fw_build_hash     String,
    nand_type         LowCardinality(String) DEFAULT '',
    nand_density      String DEFAULT '',
    test_started_at   Nullable(DateTime64(3)),
    first_dump_at     Nullable(DateTime64(3)),
    last_dump_at      Nullable(DateTime64(3)),
    dump_count        UInt32 DEFAULT 0,
    last_seen_at      DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(last_seen_at)
ORDER BY (boardname, core, trname);

-- One row per .bin. Holds FULL nested decode (compressed) = ML source of truth.
CREATE TABLE IF NOT EXISTS uta.axf_snapshots
(
    snapshot_id      UUID DEFAULT generateUUIDv4(),
    trname           String,
    boardname        String,
    core             LowCardinality(String),
    product          LowCardinality(String),
    fw_build_hash    String,
    dump_timestamp   DateTime64(3),
    elapsed_s        Float64 DEFAULT 0,
    layout_version   String,
    object_key       String,
    decoded_json     String DEFAULT '{}',     -- CODEC(ZSTD) compresses well
    decode_status    Enum8('OK'=0,'PARTIAL'=1,'FAILED'=2) DEFAULT 'OK',
    decode_error_cnt UInt32 DEFAULT 0,
    ingested_at      DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(dump_timestamp)
ORDER BY (boardname, core, trname, elapsed_s)
TTL dump_timestamp + INTERVAL 90 DAY;

-- Long-form sidecar: curated scalars for dashboards. New keys need NO migration.
CREATE TABLE IF NOT EXISTS uta.axf_metrics
(
    snapshot_id      UUID,
    trname           String,
    boardname        String,
    core             LowCardinality(String),
    product          LowCardinality(String),
    dump_timestamp   DateTime64(3),
    elapsed_s        Float64 DEFAULT 0,
    section          LowCardinality(String) DEFAULT '',
    key              String,
    value_num        Nullable(Float64),
    value_str        String DEFAULT '',
    unit             LowCardinality(String) DEFAULT '',
    ingested_at      DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(dump_timestamp)
ORDER BY (boardname, core, key, elapsed_s)
TTL dump_timestamp + INTERVAL 90 DAY;

-- Forensic sink for mismatches / failures.
CREATE TABLE IF NOT EXISTS uta.axf_decode_errors
(
    occurred_at    DateTime64(3) DEFAULT now64(3),
    object_key     String,
    boardname      String,
    core           String,
    fw_build_hash  String,
    error_type     LowCardinality(String),   -- HASH_MISMATCH/NO_LAYOUT/DECODE_FAIL/ENRICH_ERROR/BAD_EVENT
    error_message  String
)
ENGINE = MergeTree()
ORDER BY occurred_at
TTL occurred_at + INTERVAL 30 DAY;
```

---

## 6. AXF layout registry

### 6.1 Concept
DWARF parsing is slow and must be done **once per AXF**, not per dump. When an
AXF is registered, `tools/build_layout.py` parses it to a `layout.json`
(type registry + variable addresses + the firmware **build hash**). At decode
time the service loads the cached layout by `(product, core, fw_build_hash)`.

### 6.2 `axf/tools/build_layout.py` (one-shot per AXF)
```python
# Usage: python build_layout.py <product> <core> <build_hash> <path-to.axf>
# Writes axf/layouts/<product>_<core>_<build_hash>.json
#
# Implementation: call the VENDORED map_axf.process_elf.parse_dwarf_types()
# and build_type_layout(), then dump:
# {
#   "product": "...", "core": "...", "build_hash": "...",
#   "layout_version": "<product>_<core>_<build_hash>",
#   "endianness": "little",
#   "types":     { ...DWARF type registry... },
#   "variables": { "<global_name>": {"address": 0x..., "type_id": "..."} }
# }
```
- Layout filename = layout_version = `<product>_<core>_<build_hash>.json`.
- `layouts/` is committed OR mounted as a volume; build hashes make it
  immutable/append-only (a new firmware build = a new file, never an edit).

### 6.3 Build-hash gate (the #1 correctness rule)
Before decoding, the service checks:
`event.fw_build_hash == layout.build_hash`. If no layout file exists for that
triple, or hash differs → write `axf_decode_errors(error_type='NO_LAYOUT'|'HASH_MISMATCH')`
and **ack the message** (don't redeliver forever). Never decode against a
mismatched layout — that yields confident garbage.

---

## 7. Decode service (analytics server) — module-by-module

### 7.0 `config.py` — environment
```python
import os
NATS_URL          = os.environ["NATS_URL"]                 # nats://analytics:4222
NATS_STREAM       = "UTA_AXF"
NATS_CONSUMER     = "AXF_DECODER"
NATS_OBJ_BUCKET   = "AXF_BINS"
LAYOUTS_DIR       = os.environ.get("LAYOUTS_DIR", "/app/layouts")
VARIABLES_YAML    = os.environ.get("VARIABLES_YAML", "/app/config/variables.yaml")
CORES_YAML        = os.environ.get("CORES_YAML", "/app/config/cores.yaml")
CH_HOST           = os.environ.get("UTA_CH_HOST", "clickhouse")
CH_PORT           = int(os.environ.get("UTA_CH_PORT", "8123"))
CH_DB             = os.environ.get("UTA_CH_DATABASE", "uta")
CH_USER           = os.environ.get("UTA_CH_USERNAME", "default")
CH_PASS           = os.environ.get("UTA_CH_PASSWORD", "password")
BATCH_SIZE        = int(os.environ.get("AXF_BATCH_SIZE", "200"))
BIN_ARCHIVE_DIR   = os.environ.get("AXF_BIN_ARCHIVE", "/app/bin_archive")  # OPEN-C retention
```

### 7.1 `main.py` — top-level loop (pseudocode, explicit)
```python
async def run():
    cfg = load_config()
    nc  = await connect_nats(cfg)                  # nats_consumer.connect
    js  = nc.jetstream()
    obj = await js.object_store(cfg.NATS_OBJ_BUCKET)
    sub = await js.pull_subscribe_bind(cfg.NATS_CONSUMER, cfg.NATS_STREAM)
    layouts = LayoutRegistry(cfg.LAYOUTS_DIR)
    varreg  = VariableRegistry(cfg.VARIABLES_YAML)
    writer  = ClickHouseWriter(cfg)

    while True:
        msgs = await sub.fetch(batch=10, timeout=5)
        for msg in msgs:
            try:
                process_one(msg, obj, layouts, varreg, writer)
                await msg.ack()
            except RetryableError:
                await msg.nak()                    # redeliver (transient: CH down, obj not ready)
            except FatalError as e:
                writer.write_error(...);  await msg.ack()   # bad data: don't redeliver
        writer.flush_if_due()
```
`process_one` steps (in order, no skipping):
1. Parse event JSON. If invalid → `BAD_EVENT` error, ack.
2. If `enrich_error` set or any required field empty → `ENRICH_ERROR`, ack.
3. `layout = layouts.get(product, core, fw_build_hash)`; None → `NO_LAYOUT`, ack.
4. Fetch object bytes by `object_key` from the Object Store. Not found → NAK (retryable; maybe object lands after event).
5. `decoded = decode_all(bin_bytes, layout)` (§7.4). Hard failure → `DECODE_FAIL`, ack.
6. `elapsed_s = (dump_timestamp - test_started_at).total_seconds()`; if negative or `test_started_at` empty → set 0 and `decode_status=PARTIAL`.
7. `leaves = flatten(decoded)` (§7.5).
8. `curated = varreg.select(product, core, leaves)` (§7.7).
9. Build rows (`models.py`) and hand to `writer` (snapshots + metrics + session upsert).
10. Archive `.bin` to `BIN_ARCHIVE_DIR` (OPEN-C) or rely on Object Store TTL.

### 7.2 `nats_consumer.py`
- `connect(cfg)` → `nats.connect(cfg.NATS_URL, reconnect_time_wait=2, max_reconnect_attempts=-1)`.
- Helpers to fetch an object: `await obj.get(object_key)` → bytes.
- Use `nats-py` ≥ 2.x (vendored wheel for air-gap).

### 7.3 `layout_registry.py`
```python
class LayoutRegistry:
    def __init__(self, layouts_dir): self.dir=layouts_dir; self.cache={}
    def get(self, product, core, build_hash):
        key=f"{product}_{core}_{build_hash}"
        if key in self.cache: return self.cache[key]
        path=os.path.join(self.dir, key+".json")
        if not os.path.exists(path): return None      # caller -> NO_LAYOUT
        layout=json.load(open(path))
        if layout["build_hash"]!=build_hash: return None  # caller -> HASH_MISMATCH
        self.cache[key]=layout
        return layout
```

### 7.4 `decoder.py` — decode ALL globals
```python
def decode_all(bin_bytes: bytes, layout: dict) -> dict:
    """
    Returns nested dict: { "<global_var>": <decoded value/struct/array>, ... }
    Wraps the VENDORED map_axf.map_bin logic. For EACH variable in
    layout["variables"], call decode_memory(addr, type_id, types, bin_bytes,
    base_addr, endianness). Unresolvable pointers / out-of-range addrs -> the
    leaf is set to null AND error_cnt incremented (do NOT raise).
    Returns (decoded_dict, error_cnt, status) where status is OK/PARTIAL.
    """
```
Robustness rules (copy into the wrapper):
- Address outside dumped range → leaf = `null`, `error_cnt += 1` (PARTIAL).
- Union → decode every member (can't know active member); keep all, prefix the
  group with `"_union": true`. **Curated keys must avoid union-ambiguous fields.**
- Circular pointer → stop at first repeat (the vendored lib already does this).
- Never throw for a single bad variable — only throw if the whole `.bin` is
  unreadable/truncated (→ `DECODE_FAIL`).

### 7.5 `flatten.py` — nested → leaf scalar rows
```python
def flatten(decoded: dict, sep=".") -> list[dict]:
    """
    Walk the nested decode; emit one entry per SCALAR leaf:
      {"section": <top-level group>, "key": "<dotted.path>", "raw": <python scalar/str>}
    Arrays use index in the path: counters[0].value -> "counters.0.value".
    Bools -> 0/1. Strings kept as-is (coerce decides value_num).
    Skip leaves whose value is None? NO — emit with raw="" so absence is visible
    only via curated selection; flatten emits everything (full fidelity for the
    JSON archive path is separate; flatten output feeds curated selection).
    """
```
The first path segment is `section`; the full dotted path is `key` (mirrors
`interlude.py`’s `section` + `full_key`).

### 7.6 `coerce.py`
Port `coerce_value(s) -> (value_num: float|None, value_str: str, unit: str)`
verbatim from `interlude.py` (§1). Same semantics so AXF and log metrics are
comparable token-for-token.

### 7.7 `variable_registry.py` + `axf/config/variables.yaml`
Only **10–50 curated keys** per product/core go to `axf_metrics`. Thousands are
decoded but only these are promoted (the rest live in `decoded_json`).
```yaml
# variables.yaml — curated keys per product+core. Editable WITHOUT code change.
# Promoting a new key later can be backfilled from axf_snapshots.decoded_json.
SIRIUS:
  H:
    - key: "smart.wai"          ; section: "smart"
    - key: "smart.waf"
    - key: "ec.slc.max"
    - key: "ec.slc.avg"
    - key: "bad_block.init_bb"
    - key: "bad_block.rt_bb"
    - key: "temp.case"
    - key: "io.total"
    # ... up to ~50; starting set = the interlude promoted columns (§ below)
SAPPHIRE:
  F: [ ... ]
  M: [ ... ]
```
```python
class VariableRegistry:
    def __init__(self, path): self.map=yaml.safe_load(open(path))
    def select(self, product, core, leaves):
        wanted={e["key"] for e in self.map.get(product,{}).get(core,[])}
        out=[]
        for leaf in leaves:
            if leaf["key"] in wanted:
                vnum,vstr,unit = coerce_value(str(leaf["raw"]))
                out.append({"section":leaf["section"],"key":leaf["key"],
                            "value_num":vnum,"value_str":vstr,"unit":unit})
        return out
```
**Starting curated set** (port the `interlude` promoted list as the default
candidate keys): `wai, waf, ec_slc_{max,min,avg}, ec_mlc_{max,min,avg},
init_bb, rt_bb, reserved_bb, free_block_cnt_{xlc,slc}, ftl_open_count,
read_reclaim_count, total_nand_{write,erase}_bytes, temp_{case,thermal_value,
nanddts}, latency_{max,avg,min}_us, io_total, read_io, write_io,
reset_count, por_count, pmc_count, ssr_*`. **OPEN-D:** confirm exact memory
paths per product with the FW team.

### 7.8 `ch_writer.py`
Port `parser/src/writer.py`. Three insert targets, batched:
`axf_sessions` (ReplacingMergeTree upsert — just insert a fresh row),
`axf_snapshots`, `axf_metrics`, plus `write_error()` → `axf_decode_errors`.
Use the `clickhouse-connect` HTTP client (already used by the parser).

### 7.9 `models.py` — dataclasses mapping 1:1 to the columns in §5.
One dataclass per table; `asdict()` rows feed the writer.

---

## 8. UTA-side enricher (UTA Django server)

### 8.1 `watcher.py`
Reuse `vector/watcher/watcher.py`. Watch the dump output dir; trigger on a
**fully-written `.bin`** (the atomic rename in §3.2 guarantees completeness;
also gate on `.bin` suffix and ignore `.tmp`).

### 8.2 `sqlite_enricher.py`
```python
def enrich(slot_id: str) -> dict:
    """
    Open the UTA SQLite READ-ONLY. Return {trname, fw_name, test_started_at}.
    Query: SELECT trname, fwname, start FROM app_board WHERE boardname=?
    On miss / NULL -> return field as "" and set enrich_error.
    NEVER block the watcher: short timeout, read-only connection.
    """
```
Open SQLite with `file:...?mode=ro&immutable=1` to avoid locking the live DB.

### 8.3 `fw_name_parser.py`
Parse `fwname` into `{product, product_version, fw_build_hash, nand_type,
nand_density, patch_version, release_candidate, firmware_version}` using the
field order documented in `new-plan.md` §"Firmware filename parsing"
(`SAPPHIRE_SIRIUS_..._V8_TLC_512Gb_..._P52_RC07_FW00_1ffe5b4ef_20250521.bin`).
**`fw_build_hash` = the hex token before the trailing date** (`1ffe5b4ef`).
Mirror the relaxed-fallback style of `filename_parser.py`.

### 8.4 `nats_publisher.py`
```python
# 1) put the bin into the object store (key = filename)
await obj.put(filename, open(bin_path,"rb").read())
# 2) publish the metadata event (§4.3) to subject uta.axf.dump.<product>.<slot>.<core>
await js.publish(f"uta.axf.dump.{product}.{slot}.{core}", json.dumps(event).encode())
# 3) on success, optionally move/delete the local .bin per local retention policy
```
Ordering: **put object first, then publish event** (consumer fetches object on
event; if object missing it NAKs and retries — see §7.1 step 4).

---

## 9. Visualization

### 9.1 Grafana (reuse existing patterns)
- Datasource: existing ClickHouse datasource.
- Panels query `axf_metrics` filtered by `product/core/trname/key`, X axis =
  `elapsed_s` (run-vs-run overlay at t=0), exactly like the interlude
  dashboards. Provision JSON under `grafana/provisioning/dashboards/axf-*.json`.
- One **pipeline-health** row: decode lag, `axf_decode_errors` rate by type,
  dumps/hour per rack.

### 9.2 Drill-down viewer
Extend `observe_ufs.py` (FastAPI) to read `axf_snapshots.decoded_json` for a
chosen `(boardname, core, elapsed_s)` and render/diff the full nested tree.
Grafana panels deep-link to it. (Grafana never renders the nested JSON.)

---

## 10. Residual risks + required handling
1. **Torn (non-atomic) live reads.** Trust FW version/sequence fields where
   present; optionally read critical regions twice and compare; **cross-check
   any curated key that ALSO appears in `interlude_metrics`** (same `key`
   naming makes this a free validator). Track disagreements on the pipeline
   dashboard.
2. **Garbage leaves from decode-all** (unions, dangling pointers). Only curated
   keys are trusted; set `decode_status=PARTIAL` + `decode_error_cnt`.
3. **FW variable drift across versions.** Long-form table needs no migration;
   curated YAML is per-product/core; ML trained per (product, version).
4. **Air-gapped Windows.** Vendor ALL wheels (`nats-py`, `clickhouse-connect`,
   `pyelftools`, `pyyaml`, `watchdog`); ClickHouse + NATS via Docker/WSL2 images
   pre-pulled; reuse the "bake into image" approach already used for Grafana.
5. **Pipeline observability** is a first-class deliverable (M6), not optional.

---

## 11. Milestones (each independently verifiable)

| M | Deliverable | Acceptance test |
|---|---|---|
| **M1** | DDL `02-axf-schema.sql` applied | All 4 tables exist; `SELECT` returns empty sets |
| **M2** | `build_layout.py` + one `layout.json` for SIRIUS/H | layout file has `>0` variables and a build hash |
| **M3** | `decode_all` + `flatten` over a sample `.bin` (offline, no NATS) | produces nested JSON + ≥1 curated scalar; bad addr → null + error_cnt |
| **M4** | NATS up; `nats_publisher` puts object + event; `decode_service` consumes → rows land in CH | one hand-made dump appears in `axf_snapshots` + `axf_metrics` with correct `elapsed_s` |
| **M5** | UTA-side `watcher`+`sqlite_enricher`+`fw_name_parser` real end-to-end | dropping a real `.bin` on the rack host lands curated metrics in CH within seconds |
| **M6** | Build-hash gate + `axf_decode_errors` wired | a deliberately mismatched hash → row in errors, NOT in snapshots |
| **M7** | Grafana `axf-*` dashboards + pipeline-health row | curated keys plot vs `elapsed_s`; error rate visible |
| **M8** | Drill-down viewer reads `decoded_json` | open one snapshot, see full nested tree + diff vs previous |
| **M9** | Cross-validation AXF vs interlude for shared keys | disagreement count panel populated |
| **M10** | ML feature export from `decoded_json`/`axf_metrics` | a notebook pulls a (board,core) time-series matrix |

---

## 12. Open decisions (decide before/at the relevant milestone)
- **OPEN-A** — store every leaf in a `axf_metrics_full` table for ML, or
  re-extract from `decoded_json` on demand? Default: re-extract (lower volume).
- **OPEN-B** — `.bin` retention: rely on NATS Object Store TTL (168h above) vs
  archive to `BIN_ARCHIVE_DIR` long-term for reprocessing. Default: TTL + opt-in archive.
- **OPEN-C** — NATS auth (nkey/user-pass) + at-rest encryption for the air-gapped lab.
- **OPEN-D** — exact curated key → memory-path mapping per product/core (FW team).
- **OPEN-E** — SRAM address ranges in `cores.yaml` per product (FW/T32 team).

---

## 13. Related
- Supersedes the design half of [[uta-system-reference]] (`new-plan.md`); that
  file remains the source for UTA DB schema + firmware-name field meanings.
- Reused code: `parser/src/parsers/interlude.py`, `filename_parser.py`,
  `writer.py`, `vector/watcher/watcher.py`, `clickhouse/init/01-schema.sql`.
