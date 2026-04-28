"""
One-shot backfill of historical .log files directly into ClickHouse.

Reuses the live parser pipeline (filename_parser, parsers/*, writer) so rows
are byte-identical to what live ingest would produce. Bypasses Kafka entirely
to avoid overloading the broker with GBs of historical data.

Run via:
    docker compose --profile backfill run --rm backfill --source-dir /backfill

Idempotent at file granularity: files already present in test_sessions FINAL
with status='COMPLETED' are skipped unless --force is passed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import structlog

from config import Settings
from filename_parser import parse_filename
from parsers import get_parser
from writer import ClickHouseWriter

log = structlog.get_logger()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source-dir", default="/backfill", help="Folder of .log files (mounted into the container)")
    p.add_argument("--glob", default="*.log", help="Filename pattern (default *.log)")
    p.add_argument("--workers", type=int, default=4, help="Parallel files (default 4)")
    p.add_argument("--batch-size", type=int, default=0, help="Override UTA_BATCH_SIZE")
    p.add_argument("--dry-run", action="store_true", help="Parse but skip inserts; print counts only")
    p.add_argument("--force", action="store_true", help="Re-import files already marked COMPLETED")
    return p.parse_args()


def already_imported(writer: ClickHouseWriter, filename: str) -> bool:
    """Cheap idempotence guard."""
    res = writer.client.query(
        "SELECT count() FROM test_sessions FINAL "
        "WHERE log_filename = {fn:String} AND status = 'COMPLETED'",
        parameters={"fn": filename},
    )
    return bool(res.result_rows) and res.result_rows[0][0] > 0


def build_row(value_line: str, line_no: int, filename: str, meta: dict, server_ip: str) -> dict:
    parser = get_parser(value_line, filename)
    parsed = parser.parse(value_line, filename)

    log_timestamp = None
    log_time_str = parsed.get("log_time")
    if log_time_str and "started_at" in meta:
        try:
            parts = log_time_str.split(":")
            if len(parts) == 3:
                hours, minutes, seconds = parts
                delta = dt.timedelta(hours=int(hours), minutes=int(minutes), seconds=float(seconds))
                log_timestamp = meta["started_at"] + delta
        except Exception:
            pass

    return {
        "server_ip": server_ip,
        "slot_id": meta.get("slot_id", ""),
        "log_filename": filename,
        "line_number": line_no,
        "raw_line": value_line,
        "parsed": parsed,
        "log_timestamp": log_timestamp,
        "platform": meta.get("platform", ""),
        "firmware_version": meta.get("firmware_version", ""),
        "execution_type": meta.get("execution_type", ""),
        "project": meta.get("project", ""),
        "interface": meta.get("interface", ""),
        "fw_arch": meta.get("fw_arch", ""),
        "nand_type": meta.get("nand_type", ""),
        "nand_density": meta.get("nand_density", ""),
        "manufacturer": meta.get("manufacturer", ""),
        "package_density": meta.get("package_density", ""),
        "production_step": meta.get("production_step", ""),
        "release_candidate": meta.get("release_candidate", ""),
        "rack": meta.get("rack", 0),
        "test_purpose": meta.get("test_purpose", ""),
        "storage_type": meta.get("storage_type", ""),
    }


def process_file(
    path: Path,
    settings: Settings,
    batch_size: int,
    dry_run: bool,
    force: bool,
) -> tuple[Path, int, str]:
    """Parse one file, write it to ClickHouse. Returns (path, lines_written, status)."""
    writer = ClickHouseWriter(settings)
    filename = path.name

    if not force and already_imported(writer, filename):
        return path, 0, "skipped"

    meta = parse_filename(filename)
    server_ip = "backfill"  # historical files don't have an originating live IP
    meta["server_ip"] = server_ip

    if not dry_run:
        try:
            writer.upsert_session(meta)
        except Exception as exc:
            log.warning("upsert_session_failed", filename=filename, error=str(exc))

    batch: list[dict] = []
    total = 0

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n")
            try:
                row = build_row(line, line_no, filename, meta, server_ip)
            except Exception as exc:
                if not dry_run:
                    writer.write_parse_error(
                        raw_message=line,
                        filename=filename,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                continue

            batch.append(row)
            if len(batch) >= batch_size:
                if not dry_run:
                    writer.write_events(batch)
                total += len(batch)
                batch.clear()

    if batch:
        if not dry_run:
            writer.write_events(batch)
        total += len(batch)

    if not dry_run:
        writer.mark_session_completed(filename, server_ip)

    return path, total, "imported"


def main() -> int:
    args = parse_args()
    settings = Settings()
    batch_size = args.batch_size if args.batch_size > 0 else settings.batch_size

    source = Path(args.source_dir)
    if not source.is_dir():
        print(f"ERROR: --source-dir {source} is not a directory", file=sys.stderr)
        return 2

    files = sorted(source.glob(args.glob))
    if not files:
        print(f"ERROR: no files matching {args.glob} in {source}", file=sys.stderr)
        return 2

    print(f"Source     : {source}")
    print(f"Files      : {len(files)} (glob={args.glob})")
    print(f"Workers    : {args.workers}")
    print(f"Batch size : {batch_size}")
    print(f"Dry run    : {args.dry_run}")
    print(f"Force      : {args.force}")
    print()

    started = time.monotonic()
    imported = 0
    skipped = 0
    failed: list[tuple[Path, str]] = []
    total_lines = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_file, p, settings, batch_size, args.dry_run, args.force): p
            for p in files
        }
        for fut in as_completed(futures):
            path = futures[fut]
            try:
                _, n, status = fut.result()
            except Exception as exc:
                failed.append((path, str(exc)))
                print(f"  [{path.name}] FAILED: {exc}", file=sys.stderr, flush=True)
                continue

            if status == "skipped":
                skipped += 1
                print(f"  [{path.name}] skipped (already imported)", flush=True)
            else:
                imported += 1
                total_lines += n
                print(f"  [{path.name}] imported {n} lines", flush=True)

    elapsed = time.monotonic() - started
    print()
    print(
        f"Done in {elapsed:.1f}s — imported={imported}, skipped={skipped}, "
        f"failed={len(failed)}, total_lines={total_lines} "
        f"({(total_lines / elapsed) if elapsed else 0:.0f} lines/s aggregate)."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
