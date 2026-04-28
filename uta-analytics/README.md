# UTA Log Analytics POC

Distributed, on-premises log analytics platform for UTA test logs. The POC pipeline:

**Vector (agent) ➔ Kafka (broker) ➔ Python parser ➔ ClickHouse ➔ Grafana**

For the operating context and active plan, see [`docs/poc/07-plan-and-decisions.md`](../docs/poc/07-plan-and-decisions.md).

## Prerequisites

- **Windows host with Docker Desktop using the WSL2 backend.**
- WSL2 Ubuntu 22.04+ with Docker Desktop integration enabled.
- Python 3.10+ on Windows (only needed to run the simulator from Windows).
- ≥ 4 GB free RAM allocated to Docker.

> Running on a plain Linux host? The same instructions work; just skip the Windows-specific bits in the simulator section.

## 1. First-time bootstrap (WSL Ubuntu)

```bash
git clone <repo-url> ~/Projects/UTA
cd ~/Projects/UTA/uta-analytics
./scripts/wsl-bootstrap.sh
```

`wsl-bootstrap.sh` is idempotent: it copies `.env.example → .env` if missing, builds images, brings up Kafka + ClickHouse, creates the `raw-logs` topic, applies the schema, then starts parser, Vector, watcher, and Grafana, and runs a health check.

After it finishes:
- Grafana — http://localhost:3005 (`admin` / `admin`)
- ClickHouse HTTP — http://localhost:8123

Full topology and troubleshooting: [`docs/poc/08-wsl-windows-setup.md`](../docs/poc/08-wsl-windows-setup.md).

## 2. Simulating real-time logs from Windows

The simulator takes a **folder of real `.log` files** on Windows and emulates real-time generation by streaming each file line-by-line into the WSL-side watch folder. When a file finishes, it is moved to `completed/` to fire the `test_completed` event.

```powershell
# From Windows PowerShell
cd C:\path\to\repo\uta-analytics

python .\scripts\simulate_from_folder.py `
  --source "C:\Users\you\test-logs" `
  --target "\\wsl$\Ubuntu\home\you\Projects\UTA\uta-analytics\vector\logs" `
  --rate 150 `
  --concurrency 4
```

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--source` | required | Windows folder full of existing `.log` files |
| `--target` | required | WSL path Vector watches (use the `\\wsl$\…` UNC path) |
| `--rate` | 150 | Lines/second per file (≈ one board) |
| `--concurrency` | 4 | Number of files to stream in parallel |
| `--rename-slot` | off | Rewrite `R<r>S<s>-<n>` so duplicates of one source file simulate distinct boards |
| `--shuffle-lines` | off | Random small jitter in line spacing for realism |

The script is pure Python and runs equally from PowerShell or WSL.

## 3. Backfilling existing GBs of logs

The target server is rarely fresh — it usually already has historical logs. Don't pump those through Kafka. Run the backfill instead:

```bash
# From WSL
cd uta-analytics
docker compose up -d clickhouse

BACKFILL_DIR=/path/in/wsl/to/historical/logs \
  docker compose --profile backfill run --rm backfill \
    --workers 8 --batch-size 1000
```

The backfill reuses the same parser modules and writes directly to ClickHouse. It's idempotent — re-running on the same folder skips files already imported as `COMPLETED`. Details: [`docs/poc/09-backfill-existing-logs.md`](../docs/poc/09-backfill-existing-logs.md).

## 4. Verifying the pipeline

```bash
./scripts/verify.sh
```

Should print `✅` for Kafka, ClickHouse, parser, and Grafana.

To smoke-test without files, push a few synthetic messages straight into Kafka:

```bash
./scripts/seed-test-data.sh
```

## 5. Operations

```bash
./scripts/stop.sh                       # stop containers, keep data
docker compose down -v                  # stop and wipe data
docker compose logs -f parser           # tail parser logs
docker compose up -d --build parser     # rebuild parser after editing code
```

## 6. Adding a custom parser

1. Drop a `.py` file in `parser/src/parsers/` that subclasses `BaseParser`.
2. Implement `parser_id`, `can_parse`, and `parse`.
3. Restart parser: `docker compose up -d --build parser`.

The roadmap of high-value parsers (test_step, io_stats, pass_fail_marker, sample_info, script_header) is in [`docs/poc/07-plan-and-decisions.md`](../docs/poc/07-plan-and-decisions.md).

## 7. Configuration reference

All parser/runtime knobs are in `.env` (copied from `.env.example`):

| Var | Default | Purpose |
|---|---|---|
| `UTA_KAFKA_OFFSET_RESET` | `earliest` | First-run behaviour: `earliest` replays backlog, `latest` skips it. |
| `UTA_CH_USERNAME` / `UTA_CH_PASSWORD` | `default` / `password` | ClickHouse creds; injected into ClickHouse, parser, and Grafana. |
| `UTA_BATCH_SIZE` | 500 | Rows per ClickHouse insert. |
| `UTA_FLUSH_MAX_RETRIES` | 5 | Retries before parser exits and Docker restarts it. |
| `UTA_FLUSH_RETRY_MAX_SLEEP` | 30 | Cap (seconds) on exponential backoff. |
| `GF_PORT` | 3005 | Grafana published port. |

## 8. Failure model (cheat sheet)

| Failure | What happens | Recovery |
|---|---|---|
| Bad JSON in Kafka message | Logged + written to `uta.parse_errors` | Inspect with `SELECT * FROM uta.parse_errors ORDER BY occurred_at DESC` |
| ClickHouse unreachable mid-batch | 5 retries with exponential backoff (1s→30s); then process exits 1 | Docker restarts parser; Kafka redelivers from last committed offset |
| Vector restart | Resumes from on-disk checkpoint | None |
| Watcher misses a file move | `test_sessions.status` stays `RUNNING` | Re-emit by moving the file again, or run a one-off `INSERT … status='COMPLETED'` |
