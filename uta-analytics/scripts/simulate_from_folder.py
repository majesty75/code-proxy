#!/usr/bin/env python3
"""
Real-time log simulator.

Given a folder of existing .log files, emulate live generation by streaming
each file line-by-line into a target folder that Vector watches. When a file
finishes, it is moved into target/completed/ to fire the test_completed event.

Cross-platform pure Python — runs equally from Windows PowerShell and WSL.

Usage:
    python simulate_from_folder.py \\
        --source "C:\\Users\\you\\test-logs" \\
        --target "\\\\wsl$\\Ubuntu\\home\\you\\Projects\\UTA\\uta-analytics\\vector\\logs" \\
        --rate 150 \\
        --concurrency 4
"""
from __future__ import annotations

import argparse
import random
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SLOT_RE = re.compile(r"R(\d+)S(\d+)-(\d+)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Folder of existing .log files to emulate")
    p.add_argument("--target", required=True, help="Folder Vector watches (use \\\\wsl$\\... from Windows)")
    p.add_argument("--rate", type=float, default=150.0, help="Lines/second per file (default 150)")
    p.add_argument("--concurrency", type=int, default=4, help="Number of files to stream in parallel")
    p.add_argument("--glob", default="*.log", help="Filename pattern in --source (default *.log)")
    p.add_argument(
        "--rename-slot",
        action="store_true",
        help="Rewrite slot id (R<r>S<s>-<n>) per file so duplicates simulate distinct boards",
    )
    p.add_argument(
        "--shuffle-lines",
        action="store_true",
        help="Add small random jitter (±20%%) to inter-line spacing for realism",
    )
    p.add_argument(
        "--no-complete",
        action="store_true",
        help="Don't move files into completed/ after streaming (skip the test_completed event)",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="If >0, only emulate the first N files in --source (debugging)",
    )
    return p.parse_args()


def rename_slot(stem: str, index: int) -> str:
    """Rewrite the first R<r>S<s>-<n> match so each emulated file looks distinct."""
    new_slot = f"R7S{(index % 9) + 1}-{(index % 99) + 1:02d}"
    return SLOT_RE.sub(new_slot, stem, count=1)


def stream_one(
    src: Path,
    target_dir: Path,
    rate: float,
    shuffle: bool,
    move_on_done: bool,
    rename_idx: int | None,
    log_lock: threading.Lock,
) -> tuple[Path, int]:
    """Stream a single file at `rate` lines/sec into target_dir/<name>."""
    if rename_idx is not None:
        new_name = rename_slot(src.name, rename_idx)
    else:
        new_name = src.name

    out_path = target_dir / new_name
    completed_path = target_dir / "completed" / new_name
    completed_path.parent.mkdir(parents=True, exist_ok=True)

    # Truncate any prior emulation of the same file.
    out_path.write_text("", encoding="utf-8", errors="replace")

    sleep_per_line = 1.0 / rate if rate > 0 else 0.0
    lines_written = 0
    next_log_at = time.monotonic() + 5.0

    with src.open("r", encoding="utf-8", errors="replace") as f_in, \
         out_path.open("a", encoding="utf-8", errors="replace") as f_out:
        for line in f_in:
            f_out.write(line)
            f_out.flush()
            lines_written += 1
            if sleep_per_line > 0:
                if shuffle:
                    time.sleep(sleep_per_line * random.uniform(0.8, 1.2))
                else:
                    time.sleep(sleep_per_line)

            if time.monotonic() >= next_log_at:
                with log_lock:
                    print(f"  [{new_name}] {lines_written} lines streamed", flush=True)
                next_log_at = time.monotonic() + 5.0

    if move_on_done:
        # Use shutil.move to handle cross-volume moves (Windows → WSL share).
        shutil.move(str(out_path), str(completed_path))
        with log_lock:
            print(f"  [{new_name}] done ({lines_written} lines), moved to completed/", flush=True)
    else:
        with log_lock:
            print(f"  [{new_name}] done ({lines_written} lines), left in place", flush=True)

    return out_path, lines_written


def main() -> int:
    args = parse_args()

    source = Path(args.source)
    target = Path(args.target)

    if not source.is_dir():
        print(f"ERROR: --source {source} is not a directory", file=sys.stderr)
        return 2

    target.mkdir(parents=True, exist_ok=True)
    (target / "completed").mkdir(parents=True, exist_ok=True)

    files = sorted(source.glob(args.glob))
    if not files:
        print(f"ERROR: no files matching {args.glob} in {source}", file=sys.stderr)
        return 2
    if args.max_files > 0:
        files = files[: args.max_files]

    print(f"Source     : {source}")
    print(f"Target     : {target}")
    print(f"Files      : {len(files)} (glob={args.glob})")
    print(f"Rate       : {args.rate} lines/sec/file")
    print(f"Concurrency: {args.concurrency}")
    print(f"Rename slot: {args.rename_slot}")
    print()

    log_lock = threading.Lock()

    started = time.monotonic()
    total_lines = 0
    failed: list[tuple[Path, str]] = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        for i, src in enumerate(files):
            rename_idx = i if args.rename_slot else None
            fut = pool.submit(
                stream_one,
                src,
                target,
                args.rate,
                args.shuffle_lines,
                not args.no_complete,
                rename_idx,
                log_lock,
            )
            futures[fut] = src

        try:
            for fut in as_completed(futures):
                src = futures[fut]
                try:
                    _, n = fut.result()
                    total_lines += n
                except Exception as exc:
                    failed.append((src, str(exc)))
                    print(f"  [{src.name}] FAILED: {exc}", file=sys.stderr, flush=True)
        except KeyboardInterrupt:
            print("\nInterrupted — waiting for in-flight files to flush…", flush=True)
            for fut in futures:
                fut.cancel()

    elapsed = time.monotonic() - started
    print()
    print(f"Done. {total_lines} lines across {len(files) - len(failed)} files in {elapsed:.1f}s "
          f"({total_lines / elapsed:.0f} lines/s aggregate).")
    if failed:
        print(f"{len(failed)} file(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
