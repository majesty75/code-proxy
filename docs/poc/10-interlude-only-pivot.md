# POC Pivot — Interlude-only Parser & Lab-Grid Drill-Down

Status: **READY — answers locked in**, two small follow-ups still open (see §7.B).
Owner: Yash. Opened: 2026-05-05.

## 1. Why this exists

Today the parser folder has 22 line-by-line parsers (`bracket_tag`, `channel_chip_id`, `command_line`, `default`, `elapsed_op`, `feature_set`, `hex_dump`, `io_stats`, `lu_descriptor`, `mcb_block`, `pass_fail_marker`, `pmc_dme`, `refclk`, `sample_info`, `section_banner`, `secure_smart_report`, `sense_key`, `set_fw_type`, `smart_customer_report`, `smart_device_info`, `spor_rbh`, `temperature`, `test_step`, `ufs_qual`, `utf_meta`). They produce shallow, inconsistent data; the dashboards layered on top are not useful.

We are pivoting to a **single block of interest**: the `TL_interlude` snapshot the firmware emits periodically during a test. Every other line lands in `log_events` as raw text so future parsers can be added later without re-ingesting.

```
>>>BEGIN TL_interlude   Apr 23 11:22:01
0000:00:03 ...                              ← body, repeated lines, all prefixed with elapsed HHHH:MM:SS
0000:00:03 >>>ELAPSED_TIME    0000:00:00
0000:00:03 >>>END TL_interlude  Apr 23 11:22:01  [PASSED]
```

The same block recurs many times during a test (e.g. once per power-cycle / iteration). Each occurrence is a **snapshot** of every health/profile variable the FW reports. Plotted across snapshots → a time series per variable per board.

A reference sample lives at `uta-analytics/vector/logs/interlude.txt`.

## 2. Goal

**Capture every variable inside every TL_interlude block as one snapshot row, write all other lines as raw rows in `log_events`, and rebuild the dashboards.** First view = lab grid (racks → shelves → slots, no fixed dimensions); each tile shows a configured short-name + live duration + status. Click → board detail with per-snapshot trends and tables.

The schema is **master + child**: one master row per test session, plus child rows in any number of child tables. Adding a new block parser later (e.g. `tl_profile_snapshots`) is a pure addition — no migration of existing data, no churn on the master.

## 3. What gets removed

- All parsers except `base.py` and `__init__.py`.
- `default.py` becomes a no-op fallback (`priority=999`, returns `{}`).
- Both existing dashboards (`fleet-grid.json`, `board-detail.json`) — replaced.
- `parser/src/test_parsers.py` — replaced with tests for the new parser.

The `uta.log_events` table **stays** but its row meaning changes: today it's "one row per parsed line"; tomorrow it's "one row per raw line that wasn't claimed by a block parser" — i.e. every line outside a `>>>BEGIN…>>>END` envelope. The `parsed` column is dropped (no per-line parsing any more).

Two field names are corrected throughout:
- `platform` → `controller` (e.g. SIRIUS is a controller chip, not a platform)
- `production_step` → `patch_version` (P09 is a patch level, not a pre-production step)

## 4. Parser & consumer flow

### 4.1 Block parsing under line-by-line streaming

Vector ships one Kafka message per line. Block detection happens in our Python consumer:

```
state[server_ip, log_filename] = {
    in_block: False,
    block_lines: [],
    block_start_offset: None,    # first Kafka offset of the open block
    block_started_wall_at: None,
    block_index: 0,
    last_safe_offset: -1,        # highest offset fully processed
}
```

Per incoming line:

1. If `system_event == "test_completed"` → mark session COMPLETED (existing path), commit.
2. Else, if `>>>BEGIN TL_interlude` matches → flip `in_block=True`, record start offset/wall-time, push line.
3. Else, if currently `in_block` → push line.
   - If `>>>END TL_interlude` matches → call block parser on `block_lines`, emit one row to `interlude_snapshots`, increment `block_index`, drop buffer, set `last_safe_offset = this_msg_offset`.
   - Safety cap: if buffer exceeds 50,000 lines OR open for more than 30 min wall clock → dump to `parse_errors`, drop buffer, advance `last_safe_offset`.
4. Else (outside any block) → batch into `log_events` write set, set `last_safe_offset = this_msg_offset` once the line is in the next-flushed batch.

### 4.2 Commit semantics

The Kafka commit point is `min(last_log_events_flushed_offset, last_block_END_offset)`. Practically: we never advance the commit cursor past the BEGIN line of any open block. If the consumer crashes mid-block, Kafka redelivers from BEGIN and we re-buffer cleanly. We may double-write a `log_events` row if the crash is between `write_events` and commit — log_events is a plain `MergeTree` and that's acceptable for the POC.

### 4.3 Parser API

We add `BaseBlockParser`. Existing `BaseParser` (line-based) stays, but the only line parser is the no-op default. Future block parsers subclass `BaseBlockParser`:

```python
class BaseBlockParser(ABC):
    block_id: str                         # e.g. "interlude"
    begin_marker: re.Pattern              # matches a single line that opens the block
    end_marker: re.Pattern                # matches a single line that closes it
    target_table: str                     # "interlude_snapshots", "tl_profile_snapshots", …

    def parse(self, lines: list[str], filename: str, meta: dict) -> dict: ...
```

The consumer asks the registry "any block parser whose `begin_marker` matches this line?" — first match wins. Registry is auto-discovered like today.

### 4.4 What the interlude block parser extracts

Same coverage as the previous draft (top-level typed metrics + nested groups + raw_extra fallback). Output dict shape:

```python
{
  "block_status": "PASSED",
  "block_started_wall_at": "2026-04-23T11:22:01",
  "block_ended_wall_at":   "2026-04-23T11:22:01",
  "block_duration_s": 3.0,
  "fw_elapsed_time": "0000:00:00",
  "host_type": {"id": 11, "name": "Root"},
  "profile_vector": [191, 74, 163, 159, 41, 64, 34, 0, 15099, 0, 5, 0, 0, 1030479, 997282, 0, 14136, 963],
  "device_info":  ["PSJ039.24.30.55", "PSL131.18.30.124", "PSJ039.24.23.55", "PSJ243.08.33.125"],

  # promoted (typed columns)
  "wai": 1, "waf": 1,
  "ec": {"slc": {"max":191,"min":74,"avg":163,"max_minus_min":117},
         "mlc": {"max":159,"min":41,"avg":64,"max_minus_min":118}},
  "bb": {"init":34,"rt":0,"reserved":126},
  "free_block_cnt_xlc": 175, "free_block_cnt_slc": 0,
  "ftl_open_count": 15099,
  "read_reclaim_count": 5,
  "total_nand_write_bytes": 12820385304576,
  "total_nand_erase_bytes": 19615569149952,
  "temp": {"case": 25, "thermal_value": 34, "nanddts": 37,
           "too_high": 85, "too_low": -25, "shutdown_level": 0},
  "io_summary": {"reset":0,"por":0,"pmc":1,"io":187,"read_io":105,"read_kb":1002,
                 "write_io":5,"write_kb":2,"latency_max_us":35694,"latency_avg_us":1554,"latency_min_us":9},
  "phy": {"connected_rx":2,"connected_tx":2,"max_rx_hs_gear":4,"lanes":2,"gear":4,"mode":17},
  "secure_smart": {"top_level":"0x0","top_level_text":"…","subcode":"0x39","subcode_text":"HIL_TMF"},

  # everything else — JSON-only
  "ssr": {…},                    # every SmartCustomerReport key
  "sdi": {…},                    # every SmartDeviceInformation key
  "lus": [{…}, {…}],             # array of LU descriptors
  "bad_blocks": [{…}, …],        # Bad List[…]
  "plane_bb":   [{…}, …],        # CH[…] WAY[…] DIE[…] Plane[…]
  "mcb_blocks": [{…}, …],
  "tw": {…},                     # TurboWrite Flush stats
  "dtt": {…},                    # DTT parameter table
  "raw_extra": {…}
}
```

If a key appears multiple times in one block (the sample shows three `WAI : 1, WAF : 1` repeats), **last value wins** at the top level; all occurrences live under `raw_extra.<key>__history`.

## 5. ClickHouse schema (master + child)

### 5.1 `uta.test_sessions` — master (one row per file)

```sql
CREATE TABLE uta.test_sessions
(
    log_filename       String,
    server_ip          String,
    slot_id            String,                       -- R7S3-09
    rack               UInt8,
    shelf              UInt8,
    slot               UInt8,
    started_at         DateTime64(3),                -- from filename timestamp
    last_seen_at       DateTime64(3) DEFAULT now64(3),
    status             Enum8('RUNNING'=0,'PASSED'=1,'FAILED'=2,'COMPLETED'=4,'UNKNOWN'=3),
    -- denormalised filename metadata (every part stored — only some are shown on tile)
    execution_type     LowCardinality(String),       -- RESERVATION
    project            LowCardinality(String),       -- AA2
    controller         LowCardinality(String),       -- SIRIUS  (was: platform)
    interface          LowCardinality(String),       -- UFS_3_1
    fw_arch            LowCardinality(String),       -- V8
    nand_type          LowCardinality(String),       -- TLC
    nand_density       String,                       -- 512Gb
    manufacturer       LowCardinality(String),       -- GEN1
    package_density    String,                       -- 256GB
    patch_version      LowCardinality(String),       -- P09     (was: production_step)
    release_candidate  String,                       -- RC00
    firmware_version   String,                       -- FW00
    engineers          Array(String),                -- [Sharath, Aditi]
    test_purpose       LowCardinality(String),       -- Qual
    storage_type       LowCardinality(String),       -- UFS
    -- aggregates updated as snapshots arrive
    snapshot_count     UInt32 DEFAULT 0,
    last_snapshot_at   Nullable(DateTime64(3))
)
ENGINE = ReplacingMergeTree(last_seen_at)
ORDER BY (server_ip, log_filename);
```

### 5.2 `uta.interlude_snapshots` — child (one row per TL_interlude block)

```sql
CREATE TABLE uta.interlude_snapshots
(
    snapshot_id        UUID DEFAULT generateUUIDv4(),
    log_filename       String,
    server_ip          String,
    slot_id            String,
    rack               UInt8,
    shelf              UInt8,
    slot               UInt8,

    block_index        UInt32,                       -- 0,1,2… per file
    block_started_at   DateTime64(3),                -- wall clock from BEGIN marker
    block_ended_at     DateTime64(3),
    block_duration_s   Float64,
    block_status       LowCardinality(String),       -- PASSED/FAILED/UNKNOWN

    -- promoted typed metrics
    wai                Nullable(UInt32),
    waf                Nullable(UInt32),
    ec_slc_max         Nullable(UInt32),
    ec_slc_min         Nullable(UInt32),
    ec_slc_avg         Nullable(UInt32),
    ec_mlc_max         Nullable(UInt32),
    ec_mlc_min         Nullable(UInt32),
    ec_mlc_avg         Nullable(UInt32),
    init_bb            Nullable(UInt32),
    rt_bb              Nullable(UInt32),
    reserved_bb        Nullable(UInt32),
    free_block_cnt_xlc Nullable(UInt32),
    free_block_cnt_slc Nullable(UInt32),
    ftl_open_count     Nullable(UInt64),
    read_reclaim_count Nullable(UInt32),
    total_nand_write_bytes Nullable(UInt64),
    total_nand_erase_bytes Nullable(UInt64),
    temp_case          Nullable(Int16),
    temp_thermal_value Nullable(Int16),
    temp_nanddts       Nullable(Int16),
    latency_max_us     Nullable(UInt64),
    latency_avg_us     Nullable(UInt64),
    latency_min_us     Nullable(UInt64),
    io_total           Nullable(UInt64),
    read_io            Nullable(UInt64),
    write_io           Nullable(UInt64),
    read_io_kb         Nullable(UInt64),
    write_io_kb        Nullable(UInt64),
    reset_count        Nullable(UInt32),
    por_count          Nullable(UInt32),
    pmc_count          Nullable(UInt32),
    power_lvdf_event_count Nullable(UInt32),
    phy_gear           Nullable(UInt8),
    phy_lanes          Nullable(UInt8),
    ssr_received_pon_count    Nullable(UInt32),
    ssr_received_spo_count    Nullable(UInt32),
    ssr_remain_reserved_block Nullable(UInt32),

    -- everything else as JSON
    variables          String,
    ingested_at        DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(block_started_at)
ORDER BY (slot_id, log_filename, block_started_at, block_index)
TTL block_started_at + INTERVAL 60 DAY;
```

### 5.3 `uta.log_events` — child (one row per raw line outside any block)

```sql
CREATE TABLE uta.log_events
(
    server_ip      String,
    log_filename   String,
    slot_id        String,
    line_number    UInt64,
    raw_line       String,
    log_timestamp  Nullable(DateTime64(3)),    -- absolute time, derived from session.started_at + line elapsed prefix
    ingested_at    DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ingested_at)
ORDER BY (server_ip, log_filename, line_number)
TTL ingested_at + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;
```

(`parsed` column dropped; the `parsers/` folder no longer touches per-line text.)

### 5.4 `uta.parse_errors` — unchanged

### 5.5 Adding a new block parser later

Just (a) add a new child table `uta.<block>_snapshots`, (b) write a `BaseBlockParser` subclass with new BEGIN/END markers, (c) bump dashboard. The master `test_sessions` is untouched, and old data isn't migrated. This is the "extendable" property you asked about.

## 6. Dashboards

### 6.1 Lab Grid (`uta-lab-grid`)

A grid that mimics the physical lab. **No fixed dimensions** — the grid is data-driven from `test_sessions` rows.

Layout choice: **Grafana repeating panels**, repeated by `slot` within a `(rack, shelf)` row, then the row itself repeated by `(rack, shelf)`. One stat panel per slot. Idle (no current session) slots render as gray "Idle" tiles.

Tile face — three lines:

```
┌──────────────────────────────────────────────────┐
│ R7S3-09                                 RUNNING  │  ← coloured background
│ SIRIUS  UFS 3.1  P09 RC00 FW00  TLC 512Gb 256GB  │  ← short name (per Q5)
│ ⏱ 02h 14m   ·   snap #18                          │
└──────────────────────────────────────────────────┘
```

The middle line is built from `controller`, `interface` (formatted `UFS_3_1` → `UFS 3.1`), `patch_version`, `release_candidate`, `firmware_version`, `nand_type`, `nand_density`, `package_density`. Every other filename field is in the master row but not displayed here — exposed in the Board Detail header.

Colours: RUNNING = blue, PASSED = green, FAILED = red, COMPLETED = dark green, UNKNOWN = gray, Idle = gray (different shade, italic label).

Top-of-dashboard: filters (rack, controller, fw_version, test_purpose) + KPIs (active sessions, failed in window, snapshots/min, slots in use).

Click any tile → opens **Board Detail** with `var-slot_id=<R…>` and `var-log_filename=<latest>`.

**Status rule for tiles**:
- If a `test_completed` event has fired → COMPLETED.
- Else if any snapshot in this run has `block_status='FAILED'` → FAILED.
- Else if last snapshot is `PASSED` and last_seen_at is more than 5 min stale → PASSED.
- Else → RUNNING.

### 6.2 Board Detail (`uta-board-detail`)

For the selected `slot_id` (and optional `log_filename`):

- **Header**: filename, slot, rack/shelf/slot, started_at, current status, total elapsed, snapshot count. Plus the *full* decoded filename grid (every field from §5.1) so engineers see all 17 segments.
- **Per-snapshot trend graphs** — one data point per snapshot, x-axis = `block_started_at`:
  - WAI, WAF
  - EC SLC max/min/avg, EC MLC max/min/avg (two panels or overlaid — TBD with you)
  - Bad-block counts (init, rt, reserved)
  - Free Block Count (xLC, SLC)
  - Total NAND write/erase bytes (cumulative)
  - Temperature (case, thermal, NANDDTS) overlaid
  - IO latency max/avg/min overlaid
  - FTL Open Count, Read Reclaim Count
  - PON / SPO counts
- **Latest-snapshot tables**:
  - LU descriptors
  - Plane Bad-Block table (CH × WAY × DIE × Plane heatmap of `InitBB+RTBB`)
  - Bad List (CH/Way/Die/BLK/Plane)
  - Smart Customer Report all keys
  - Smart Device Info all keys
  - DTT parameter table
  - TurboWrite block
- **Snapshot timeline**: state-timeline of `block_status` per snapshot.
- **Raw variables JSON viewer**: latest `variables` blob for forensics.
- **Raw log lines panel**: last N rows from `log_events` for this slot/file (so engineers can still see context lines around the time of an interesting snapshot).

Decision deferred (per Q6): whether each metric gets its own panel or several overlay onto one. Default: one panel per logical group (EC together, latency together, temp together).

## 7. Decisions & follow-ups

### 7.A Resolved

| # | Question | Answer |
|---|----------|--------|
| 1 | Block parser feasible with line-by-line streaming? | Yes — buffered in the consumer; commit semantics in §4.2. |
| 2 | Schema model? | Master `test_sessions` + children `interlude_snapshots`, `log_events`. Future blocks add new child tables. |
| 3 | Lab grid sizing | No limits; data-driven from `test_sessions`. |
| 4 | Idle slots | Gray "Idle" tile. |
| 5 | Tile name | `SIRIUS UFS 3.1 P09 RC00 FW00 TLC 512Gb 256GB`. Stored every part of filename in master; only this line shown on tile. Renames: `platform→controller`, `production_step→patch_version`. |
| 6 | Multiple snapshots per test? | Yes, one row per block in `interlude_snapshots`. Per-variable time series falls out for free. Overlay vs. per-panel layout: decide later in dashboard polish pass. |
| 7 | Hot metrics elaborated | See response in chat; promotion list locked in §5.2 unless you reject "Probable" tier. |
| 8 | Synthetic test fixture | Not yet — using real logs only. |
| 9 | Outside-block lines | Land in `log_events` raw. |
| 10 | Backfill | **Out of scope for this pivot.** `parser/src/backfill.py` will be left untouched; it will break under the new schema and that's accepted. We'll revisit if/when needed. |

### 7.B Final answers (locked)

| Q | Answer |
|---|--------|
| Storage strategy | **Option D — Hybrid.** ~40 typed columns on `interlude_snapshots` + a long-form sidecar `interlude_metrics(snapshot_id, key, value_num, value_str, unit)` that gets every other scalar parsed from the block. Arrays / nested groups (LUs, Bad List, plane bb, DTT array, MCB blocks, correction-fail algorithm tree) live in the JSON `variables` blob on `interlude_snapshots` because they don't flatten cleanly. |
| Extraction policy | **Aggressive.** Parse every `name : value` and `name = value` we can find in the block, scoped by section (`### …`). Use the section heading as namespace prefix in `interlude_metrics.key`. |
| Value coercion | Hex literals → integer (`0x91600` → `595456`). Decimal floats → float. Numbers with `(secondary)` suffix like `34(22)` → primary number to `value_num`, raw to `value_str`. Numbers with unit suffix like `4096MB` → `value_num=4096`, `unit='MB'`. Pure strings → `value_str` only. Original raw token always preserved in `value_str` so nothing is lost. |
| Tile click | **New tab.** Lab grid stays up as a permanent overview. |

### 7.C New table — `interlude_metrics`

```sql
CREATE TABLE uta.interlude_metrics
(
    snapshot_id      UUID,                 -- FK to interlude_snapshots.snapshot_id
    log_filename     String,               -- denormalised for fast slot/file filtering without joins
    slot_id          String,
    block_started_at DateTime64(3),        -- denormalised for time-axis queries
    section          LowCardinality(String),  -- e.g. "smart_report", "health_descriptor", "turbowrite", ""
    key              LowCardinality(String),  -- e.g. "ssr.ReceivedPonCount", "health.PreEOLInfo"
    value_num        Nullable(Float64),    -- if numeric (int or float, hex pre-decoded)
    value_str        String,               -- always set: original raw token
    unit             LowCardinality(String) DEFAULT ''  -- "MB", "us", "KB", etc., extracted when present
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(block_started_at)
ORDER BY (slot_id, key, block_started_at)
TTL block_started_at + INTERVAL 60 DAY;
```

Grafana plotting any field becomes a one-liner:
```sql
SELECT block_started_at AS time, value_num
FROM uta.interlude_metrics
WHERE slot_id = '${slot_id}' AND key = '${metric:raw}'
ORDER BY block_started_at
```

## 8. Implementation order

1. Replace `clickhouse/init/01-schema.sql` (new master + two children + parse_errors). Drop+recreate all four tables since there's no production data.
2. Update `parser/src/filename_parser.py` to emit `controller` and `patch_version` (renames).
3. Add `BaseBlockParser` abstract class in `parser/src/parsers/base.py`. Keep `BaseParser` for forward-compat; everything still wires through `parsers/__init__.py` registry.
4. Delete the 22 line parsers; leave a minimal no-op `default.py` (priority=999, returns `{}`).
5. Add `parser/src/parsers/interlude.py` — the block parser.
6. Rewrite `parser/src/consumer.py` to do block buffering + dual-write (log_events for outside-block lines, interlude_snapshots on END) and the commit semantics of §4.2.
7. Replace `parser/src/writer.py` methods (`write_events`, `write_snapshot`, `upsert_session`, `mark_session_completed`).
8. Leave `parser/src/backfill.py` alone — out of scope, will be broken until revisited.
9. Rewrite `parser/src/test_parsers.py` — fixtures parse `vector/logs/interlude.txt`, asserts on the dict shape, asserts every field from §4.4 is populated.
10. Replace `grafana/provisioning/dashboards/fleet-grid.json` → `lab-grid.json`.
11. Replace `grafana/provisioning/dashboards/board-detail.json`.
12. End-to-end smoke: bring up stack, generate a synthetic `R7S3-09_*.log` containing the interlude block + surrounding noise, watch the tile turn blue, click in, see the WAI/WAF/EC/temp curves and the LU/bad-block tables.

I start step 1 once §7.B is settled.
