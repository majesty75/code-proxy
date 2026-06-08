# 05 — Database (ClickHouse)

Schema in `clickhouse/init/02-axf-schema.sql`, applied automatically on first
container start. Database `uta`, four tables. These are **separate** from the
interlude log pipeline's tables.

## The golden rule

**Adding a metric never changes the schema.** Metrics are rows in a long-form
table keyed by a `String`. Add a variable → more rows, zero DDL. See *Long-form
model* below.

## Tables

### `axf_sessions` — one row per (board, core, TR) run
`ReplacingMergeTree(last_seen_at)`, `ORDER BY (boardname, core, trname)`.
Master record: `trname, boardname, core, product, product_version, fw_name,
fw_build_hash, nand_type, nand_density, test_started_at, first_dump_at,
last_dump_at, dump_count`. Latest write wins.

### `axf_snapshots` — one row per dump (the ML source of truth)
`MergeTree`, `PARTITION BY toYYYYMMDD(dump_timestamp)`,
`ORDER BY (boardname, core, trname, elapsed_s)`, `TTL dump_timestamp + 90 DAY`.
Holds the **full nested decode**:
`decoded_json String CODEC(ZSTD(3))` plus `elapsed_s, decode_status
(OK/PARTIAL/FAILED), decode_error_cnt, layout_key, object_key`.
Every leaf is here regardless of curation — so new curated keys can be
**backfilled** from `decoded_json` without re-dumping.

### `axf_metrics` — long-form curated scalars (dashboards)
`MergeTree`, `PARTITION BY toYYYYMMDD(dump_timestamp)`,
`ORDER BY (boardname, core, key, elapsed_s)`, `TTL dump_timestamp + 90 DAY`.
Columns:
```
snapshot_id, trname, boardname, core, product, dump_timestamp,
elapsed_s, section LowCardinality, key String,
value_num Nullable(Float64), value_str String, unit LowCardinality
```
**`key` is the metric name.** A new metric is a new value in `key`.

### `axf_decode_errors` — forensic sink
`MergeTree`, `ORDER BY occurred_at`, `TTL occurred_at + 30 DAY`.
`object_key, boardname, core, fw_build_hash, error_type, error_message`.
`error_type` ∈ `BAD_EVENT / ENRICH_ERROR / NO_LAYOUT / HASH_MISMATCH / DECODE_FAIL`.

## The long-form model (why no column-per-metric)

A "wide" table (`wai Float64, waf Float64, …`) needs an `ALTER TABLE` for every
new field and can't represent thousands of per-product variables. Long-form
trades typed columns for a `(key, value_num, value_str, unit)` shape:

- **Add a field** → insert rows with a new `key`. No migration. New keys appear in
  Grafana's `key` dropdown automatically (`SELECT DISTINCT key`).
- **value_num** is the numeric value (NULL if non-numeric); **value_str** always
  holds the original token; **unit** is the optional unit (`"MB"`, `"us"`, `"C"`).
- This is the same pattern as Prometheus labels and the existing
  `interlude_metrics` table.

Trade-off: query with `WHERE key = '…'` rather than `SELECT col`. For genuinely
hot keys you *may* later promote a typed column for speed — optional, not required.

## Relative-time axis

`elapsed_s = dump_timestamp − test_started_at` (seconds). Plotting metrics on
`elapsed_s` overlays runs that started on different days at a common `t = 0`. The
Grafana metric panel is a **Trend** panel with `xField: elapsed_s` (a numeric X
axis — a normal time-series panel can't use `elapsed_s` as its time column).

## Common queries

```sql
-- one metric over elapsed time for a run
SELECT elapsed_s, value_num
FROM uta.axf_metrics
WHERE product='SIRIUS' AND core='H' AND trname='RACK8_TRAILRUN'
  AND key='smart.wai'
ORDER BY elapsed_s;

-- latest curated snapshot for a board/core
SELECT key, value_num, unit
FROM uta.axf_metrics
WHERE boardname='R7S1-01' AND core='M'
  AND dump_timestamp = (SELECT max(dump_timestamp) FROM uta.axf_metrics
                        WHERE boardname='R7S1-01' AND core='M')
ORDER BY key;

-- pull a value from the full archive (a key not currently curated)
SELECT dump_timestamp,
       JSONExtractInt(decoded_json, 'someStruct', 'someField') AS v
FROM uta.axf_snapshots
WHERE boardname='R7S1-01' AND core='M'
ORDER BY dump_timestamp;

-- decode error rate by type, last 24h
SELECT error_type, count() n
FROM uta.axf_decode_errors
WHERE occurred_at > now() - INTERVAL 24 HOUR
GROUP BY error_type ORDER BY n DESC;
```

## Retention / TTL — a gotcha to know

`axf_snapshots`/`axf_metrics` TTL is keyed on **`dump_timestamp`** (90 days). This
is correct for live data, but **back-dated dumps older than 90 days are evicted on
merge** — relevant only if you replay historical dumps. If you need retention
measured from ingest instead, change the TTL to `ingested_at + INTERVAL 90 DAY`
in `02-axf-schema.sql` and recreate the tables. `axf_sessions` has no TTL.

## Backfilling a new curated key

Because `decoded_json` holds every leaf, you don't re-dump to start tracking a new
metric historically — extract it from the archive:
```sql
INSERT INTO uta.axf_metrics (snapshot_id, trname, boardname, core, product,
                             dump_timestamp, elapsed_s, section, key, value_num, value_str)
SELECT snapshot_id, trname, boardname, core, product, dump_timestamp, elapsed_s,
       'smart', 'smart.newKey',
       JSONExtractFloat(decoded_json, 'smart', 'newKey'),
       toString(JSONExtractFloat(decoded_json, 'smart', 'newKey'))
FROM uta.axf_snapshots
WHERE product='SIRIUS';
```
(Then add it to `variables.yaml` so future dumps include it going forward.)
