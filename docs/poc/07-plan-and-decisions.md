# POC — Plan & Decisions (rolling)

This doc captures concrete decisions and the active plan for the next iteration of the POC. It supersedes informal conversation notes.

## Operating context

| Dimension | Decision |
|---|---|
| Phase | POC (1 board, 1 server) — extended to handle realistic existing-server case |
| Volume | ~100–200 lines/sec/board sustained |
| Deploy | Docker Compose only (no k8s, no Swarm) |
| Host | Windows + Docker Desktop with **WSL2 backend**; the repo lives inside WSL |
| Simulator | Cross-platform Python, runnable from **Windows PowerShell** against a folder of real logs |
| Existing data | The target server is **not fresh** — it has GBs of historical logs; ingest those without flooding Kafka |
| Retention | `log_events` 30 days TTL; `parse_errors` 7 days TTL |
| Storage of `parsed` | JSON blob (intentional — feature columns will follow once parsers stabilise) |
| Multi-line records | Yes — IO statistics, `[ MCB CH x BLK y ]` blocks, banner sections |
| ML / RBAC / Alerting | ML in scope (Phase 2+). RBAC and alerting deferred. |

## §5 fixes — landed

| # | Issue | Fix |
|---|---|---|
| 1 | SQL injection in `mark_session_completed` | Removed `ALTER … UPDATE` entirely; replaced with INSERT into the existing `ReplacingMergeTree(last_seen_at)`. Reads current row first via parameterised query so the replacement row is complete. |
| 2 | Hardcoded ClickHouse credentials | Now read from `Settings` (`UTA_CH_USERNAME`, `UTA_CH_PASSWORD`); compose injects them into both ClickHouse, parser, and Grafana containers. |
| 3 | `auto.offset.reset = latest` | Now configurable via `UTA_KAFKA_OFFSET_RESET`; default switched to `earliest` so first start does not silently skip backlog. |
| 4 | Parse failures silently dropped; CH write failures lost the in-flight batch | Parse failures are written to a new `uta.parse_errors` table for forensic inspection. Flush retries with exponential backoff (1s→30s, 5 attempts); on permanent failure the consumer process exits non-zero so Docker restarts it and Kafka redelivers from the last committed offset. |
| 5 | `ALTER … UPDATE` per file move (async, expensive at fleet scale) | Replaced by INSERT (see #1). Dashboards already query `test_sessions` with `FINAL`, so no query changes were needed. |

## Parser roadmap (proposed; not yet built)

Ranked by dashboard / ML value. See `10-parser-roadmap.md`.

1. `test_step.py` — `>>>BEGIN`/`>>>END`/`>>>PROCESS`/`>>>ELAPSED_TIME` with `[PASSED]`/`[FAILED]` markers. Drives every pass/fail and elapsed-time dashboard.
2. `io_stats.py` — multi-line IO statistics block (Reset/POR/PMC counts, Read/Write IO counts and lengths, Max/Avg/Min latency).
3. `pass_fail_marker.py` — `[PASS][CH x][BLK y]` lines with `Expect`/`Actual` values.
4. `sample_info.py` — multi-line `***… TL_SAMPLE_INFORMATION …***` block.
5. `script_header.py` — `>>>UTF` commit hash / branch / build date for git-bisect.
6. Improve `default.py` — better tagged-line and inline-K=V handling.

### Multi-line parsing

Add `MultilineParser` ABC alongside `BaseParser`: `start_match(line, filename) -> bool`, `accumulate(line) -> bool` (returns False to terminate), `flush() -> dict`. Consumer keeps a per-`(server_ip, log_filename)` open multi-line parser; lines still go to `log_events.raw_line` so nothing is dropped.

## Monitoring (deferred — pick before next sprint)

- **Tier A (lightweight, recommended for current POC):** parser writes a `pipeline_health` row to ClickHouse every 30s (messages_consumed, parse_errors, flush_failures, batch_size_avg, consumer_lag). One new Grafana dashboard. No new containers.
- **Tier B (forward-compatible to system phase):** Prometheus + kafka-exporter + `prometheus_client` in parser. Three new services in compose, but matches the system-phase target.

Decision pending. Default plan: Tier A now, Tier B at the start of the system phase.

## AI/ML readiness

Stage 1 — feature views over `log_events` once parsers #1 and #2 land (`mv_step_results`, `mv_latency_metrics`, `mv_failure_signatures`).
Stage 2 — batch ML jobs (failure prediction per FW build, latency anomaly, failure clustering) writing back into a `predictions` table.
Stage 3 — streaming inference: a second Kafka consumer parallel to the parser.
Stage 4 — log embeddings in ClickHouse `Array(Float32)` for similarity search ("show me past runs that look like this failure").

No ML code is written yet. The current decisions that protect ML readiness are: keep `parsed` rich JSON, build parsers #1 and #2 first, retain raw lines.

## Existing-server backfill strategy

The target server is **not** fresh — it has GBs of historical logs. We do **not** stream those through Kafka (broker would be overloaded for hours). Instead:

- Vector keeps `read_from = "end"` so newly appended lines start streaming from the install moment forward.
- A one-shot **backfill** runs inside the parser image (`docker compose --profile backfill run --rm backfill`) that reads files from a mounted directory, parses with the same parsers, and bulk-inserts directly into ClickHouse. It marks each session `COMPLETED`. Idempotent: skips files already present in `test_sessions FINAL` with `status='COMPLETED'`.

Full instructions in `08-backfill-existing-logs.md`.
