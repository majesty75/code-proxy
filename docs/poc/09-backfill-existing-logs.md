# POC — Backfilling existing logs

The target server is **not** fresh. It has GBs of `.log` files in `/uta/UTA_FULL_Logs/` (or equivalent) before this analytics stack is installed. The default Vector configuration uses `read_from = "end"` so it only picks up *new* lines — historical files would otherwise be invisible.

This doc covers the **one-shot backfill** that imports those files directly into ClickHouse, bypassing Kafka.

## Why bypass Kafka

If the parser were fed all historical data through Kafka, the broker would need to buffer GBs of messages. With single-broker, single-partition POC topology and 24h retention, that means either:
- bumping retention and disk allocation just for the backfill window, or
- accepting hours of consumer lag and a real risk of data loss if the broker hits its disk cap.

A direct **file → parser → ClickHouse** path avoids all of that. The backfill reuses the same parser modules so the resulting rows are byte-identical to what a live ingest would have produced.

## What gets written

For each `.log` file processed:

1. One row in `uta.test_sessions` with full filename metadata and `status = 'COMPLETED'` (file is historical → already finished).
2. N rows in `uta.log_events` (one per line), inserted in batches of `UTA_BATCH_SIZE`.
3. Any line that fails to parse goes to `uta.parse_errors` — same as live flow.

## Idempotence

The backfill script is **idempotent at file granularity**. Before processing a file it queries:

```sql
SELECT count() FROM uta.test_sessions FINAL
WHERE log_filename = {fn:String} AND status = 'COMPLETED'
```

Non-zero → skip. So re-running the backfill on the same folder is safe (and cheap, only metadata reads).

If you need to **force re-import** of a specific file (e.g., parser logic changed), delete its rows first:

```sql
ALTER TABLE uta.log_events    DELETE WHERE log_filename = '<filename>';
ALTER TABLE uta.test_sessions DELETE WHERE log_filename = '<filename>';
```

## Running it

The backfill runs as a one-shot Compose service that uses the parser's image (so it ships with the same parsers and ClickHouse client):

```bash
# From inside WSL Ubuntu, repo root
cd uta-analytics

# Make sure ClickHouse is up
docker compose up -d clickhouse

# Run the backfill against a folder. The folder is bind-mounted read-only.
BACKFILL_DIR=/path/in/wsl/to/historical/logs \
  docker compose --profile backfill run --rm backfill
```

Flags exposed via the script:

| Flag | Default | Meaning |
|---|---|---|
| `--source-dir` | `/backfill` (mounted) | Folder of `.log` files |
| `--glob` | `*.log` | Filename pattern |
| `--batch-size` | from `UTA_BATCH_SIZE` | Rows per ClickHouse insert |
| `--workers` | 4 | Parallel files |
| `--dry-run` | off | Parse but skip the inserts; prints counts |
| `--force` | off | Re-import even if `test_sessions` already has the file |

### Concrete example

```bash
BACKFILL_DIR=/mnt/uta-archive/2026-Q1 \
  docker compose --profile backfill run --rm backfill \
    --workers 8 --batch-size 1000
```

## Capacity planning

Rough sizing for the backfill (PoC numbers, validate before promising):
- Parsing throughput per worker: ~25–40k lines/sec on a modern dev laptop.
- ClickHouse insert: batches of 500–1000 rows, ~10–30 MB/s sustained on local SSD.
- 1 GB of log text ≈ 5–10M lines depending on average line length.
- Expect **a few minutes per GB** on 4 workers.

If the historical archive is on a slow share, the bottleneck will be I/O, not parsing.

## After backfill: enabling live ingest

Once the backfill finishes:

1. Install Vector on the UTA server (or on this same machine, pointing at `/uta/UTA_FULL_Logs/`) with `read_from = "end"` (the default in `vector.toml`). New lines stream into Kafka.
2. Vector will *not* re-read the historical files because its checkpoint records the size at first observation.
3. The watcher container detects file moves into `completed/` and emits the `test_completed` event for newly finished sessions.

Historical sessions show up in dashboards with `status = 'COMPLETED'` and the `started_at` parsed from the filename.

## Caveats and known limits

- **Multi-line records during backfill** behave the same as live flow once `MultilineParser` lands. Until then, the multi-line blocks (IO statistics, MCB blocks) are split across rows just as in live mode.
- **Filename-only metadata** is the same as live: if the historical file deviates from the strict naming convention, `parse_filename` falls back to relaxed extraction. Result: partial metadata, never a hard error.
- **Concurrent live + backfill on the same files** is undefined — don't backfill a folder while Vector is also tailing it. Either backfill before installing Vector, or backfill from an archive folder Vector does not watch.
