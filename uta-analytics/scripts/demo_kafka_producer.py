"""
Kafka producer that simulates Vector.

Streams interlude.txt line-by-line into the raw-logs topic for one synthetic
board. Each message uses the same JSON envelope Vector emits, so the parser
container ingests it via the real pipeline.

Run:
    python3 scripts/demo_kafka_producer.py [--blocks 3] [--rate 50]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from confluent_kafka import Producer  # type: ignore


FIXTURE = Path(__file__).resolve().parents[1] / "vector" / "logs" / "interlude.txt"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bootstrap", default="localhost:9092")
    p.add_argument("--topic",     default="raw-logs")
    p.add_argument("--blocks",    type=int, default=3, help="repeat the interlude block N times")
    p.add_argument("--rate",      type=int, default=200, help="lines per second")
    p.add_argument("--rack",      type=int, default=9)
    p.add_argument("--shelf",     type=int, default=1)
    p.add_argument("--slot",      type=int, default=1)
    args = p.parse_args()

    if not FIXTURE.exists():
        print(f"missing fixture: {FIXTURE}", file=sys.stderr)
        return 1

    started = dt.datetime.utcnow()
    filename = (
        f"R{args.rack}S{args.shelf}-{args.slot:02d}_{started.strftime('%Y%m%d_%H%M%S')}_"
        f"EXEC_AA2_SIRIUS_UFS_3_1_V8_TLC_512Gb_GEN1_256GB_"
        f"P09_RC00_FW00_Rack{args.rack}_Live_Demo_Qual_UFS"
    )
    server_ip = "live-demo"

    body_lines = [
        l for l in FIXTURE.read_text(encoding="utf-8", errors="replace").splitlines()
    ]

    producer = Producer({"bootstrap.servers": args.bootstrap})

    print(f"Producing → {args.bootstrap}/{args.topic}")
    print(f"  filename : {filename}")
    print(f"  blocks   : {args.blocks}")
    print(f"  rate     : {args.rate} lines/s")
    print()

    line_no = 0
    sleep_per_line = 1.0 / max(args.rate, 1)

    # A few outside-block "noise" lines to populate log_events.
    for noise in [
        "Send Nop",
        "Lun: 0",
        "[LOG] Reclaim Count : 0",
        "_advrpmb_support : 0 / _advrpmb_testmode : 0",
    ]:
        line_no += 1
        msg = {
            "log_filename": filename,
            "server_ip":    server_ip,
            "line":         noise,
            "line_number":  line_no,
        }
        producer.produce(args.topic, json.dumps(msg).encode("utf-8"), key=filename.encode("utf-8"))
        time.sleep(sleep_per_line)

    for block_idx in range(args.blocks):
        block_start = dt.datetime.utcnow().strftime("%b %d %H:%M:%S")
        for raw in body_lines:
            line_no += 1
            # Substitute the block timestamp into BEGIN/END markers so each
            # block has a unique wall clock.
            line = raw
            if ">>>BEGIN TL_interlude" in line:
                # Replace the trailing date with our current one
                line = line.split("\t")[0] + "\t" + block_start + "\t\t\t"
            elif ">>>END TL_interlude" in line:
                # Same; re-attach the [STATUS] marker
                status = "[FAILED]" if (block_idx == args.blocks - 1 and args.blocks >= 3) else "[PASSED]"
                # Rip off any existing trailing "\tApr 23 11:22:01\t[PASSED]"
                head = line.split(">>>END TL_interlude")[0]
                line = f"{head}>>>END TL_interlude \t{block_start}\t{status}"
            msg = {
                "log_filename": filename,
                "server_ip":    server_ip,
                "line":         line,
                "line_number":  line_no,
            }
            producer.produce(args.topic, json.dumps(msg).encode("utf-8"), key=filename.encode("utf-8"))
            time.sleep(sleep_per_line)

        producer.flush()
        print(f"  [block {block_idx+1}/{args.blocks}] sent {len(body_lines)} lines (block_start={block_start})")
        # Pause between blocks to space the snapshot timestamps apart
        if block_idx < args.blocks - 1:
            time.sleep(2)

    # Closing test_completed event
    msg = {
        "system_event": "test_completed",
        "filename":     filename,
        "server_ip":    server_ip,
    }
    producer.produce(args.topic, json.dumps(msg).encode("utf-8"), key=filename.encode("utf-8"))
    producer.flush()
    print()
    print("All blocks sent + test_completed event. Watch the parser & lab grid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
