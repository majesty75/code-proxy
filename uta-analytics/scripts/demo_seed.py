"""
Local demo seeder.

Populates ClickHouse with simulated test sessions, parsing the real
interlude.txt fixture per snapshot but jittering the headline metrics so
the time-series dashboards look like a live test bench. Skips Kafka and
the parser container — direct ClickHouse inserts so the demo is one step.

Run:
    python3 scripts/demo_seed.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sys
import uuid
from pathlib import Path

# Make parser/src importable
SRC = Path(__file__).resolve().parents[1] / "parser" / "src"
sys.path.insert(0, str(SRC))

import clickhouse_connect  # type: ignore

from filename_parser import parse_filename
from parsers.interlude import InterludeBlockParser


# --------------------------------------------------------------------
# Simulated board fleet — 3 racks × 2 shelves × 3 slots = 18 boards.
# --------------------------------------------------------------------
RACKS  = [7, 8]
SHELVES = [1, 2, 3]
SLOTS   = [3, 6, 9]
ENGINEERS = ["Sharath_Aditi", "Pavan_Kiran", "Ravi_Suresh"]
TEST_PURPOSE_CHOICES = ["Qual", "Rel", "Stress"]
EXEC_TYPES = ["EXEC", "RESERVATION", "RETEST"]


def filename_for(rack: int, shelf: int, slot: int, started: dt.datetime, eng_idx: int, tp_idx: int, exec_idx: int) -> str:
    return (
        f"R{rack}S{shelf}-{slot:02d}_{started.strftime('%Y%m%d_%H%M%S')}_"
        f"{EXEC_TYPES[exec_idx]}_AA2_SIRIUS_UFS_3_1_V8_TLC_512Gb_GEN1_256GB_"
        f"P09_RC00_FW00_Rack{rack}_{ENGINEERS[eng_idx]}_{TEST_PURPOSE_CHOICES[tp_idx]}_UFS"
    )


def jitter(lines: list[str], seed: int) -> list[str]:
    """Slight pseudo-random tweaks to numeric values so the time-series moves."""
    rng = random.Random(seed)
    out = []
    for line in lines:
        new = line
        # Bump WAI/WAF occasionally
        new = new.replace("WAI : 1, WAF : 1", f"WAI : {rng.randint(1, 3)}, WAF : {rng.randint(1, 4)}")
        # Bump SLC EC values
        if "EC SLC Max : 191, Min : 74, Avg : 163" in new:
            new = new.replace(
                "EC SLC Max : 191, Min : 74, Avg : 163",
                f"EC SLC Max : {191 + rng.randint(0, 12)}, Min : {74 + rng.randint(-3, 3)}, Avg : {163 + rng.randint(-5, 8)}",
            )
        if "EC MLC Max : 159, Min : 41, Avg : 64" in new:
            new = new.replace(
                "EC MLC Max : 159, Min : 41, Avg : 64",
                f"EC MLC Max : {159 + rng.randint(0, 10)}, Min : {41 + rng.randint(-2, 2)}, Avg : {64 + rng.randint(-3, 6)}",
            )
        # Wiggle temperature
        if "DeviceCaseRoughTemperature\t=\t\t25" in new:
            t = 25 + rng.randint(-2, 18)
            new = new.replace("DeviceCaseRoughTemperature\t=\t\t25", f"DeviceCaseRoughTemperature\t=\t\t{t}")
        if "ThermalValue =      34(22)" in new:
            tv = 34 + rng.randint(-2, 14)
            new = new.replace("ThermalValue =      34(22)", f"ThermalValue =      {tv}({tv-12})")
        # Bump latency
        if "Maximum Latency Time: 35694 usec" in new:
            new = new.replace(
                "Maximum Latency Time: 35694 usec",
                f"Maximum Latency Time: {35694 + rng.randint(-5000, 12000)} usec",
            )
        if "Average Latency Time: 1554 usec" in new:
            new = new.replace(
                "Average Latency Time: 1554 usec",
                f"Average Latency Time: {1554 + rng.randint(-200, 800)} usec",
            )
        out.append(new)
    return out


def fake_status(rng: random.Random, idx: int, total: int) -> str:
    """Most snapshots PASS; occasional FAIL to give the dashboards colour."""
    if idx == total - 1 and rng.random() < 0.15:
        return "FAILED"
    return "PASSED"


def patch_status(lines: list[str], status: str) -> list[str]:
    return [
        line.replace("[PASSED]", f"[{status}]") if ">>>END TL_interlude" in line else line
        for line in lines
    ]


def main() -> int:
    fixture = Path(__file__).resolve().parents[1] / "vector" / "logs" / "interlude.txt"
    if not fixture.exists():
        print(f"missing fixture: {fixture}", file=sys.stderr)
        return 1

    base_lines = fixture.read_text(encoding="utf-8", errors="replace").splitlines()
    parser = InterludeBlockParser()

    client = clickhouse_connect.get_client(
        host=os.getenv("CH_HOST", "localhost"),
        port=int(os.getenv("CH_PORT", "8123")),
        username=os.getenv("CH_USER", "default"),
        password=os.getenv("CH_PASSWORD", "password"),
        database="uta",
    )

    # Wipe existing demo rows so reruns are idempotent.
    for table in ("interlude_metrics", "interlude_snapshots", "log_events", "test_sessions"):
        client.command(f"TRUNCATE TABLE uta.{table}")

    print("Seeding 18 boards × ~6 snapshots each …")
    rng = random.Random(42)
    now = dt.datetime.utcnow()
    sessions = 0
    snapshots_total = 0
    metrics_total = 0
    log_events_total = 0

    for r_idx, rack in enumerate(RACKS):
        for s_idx, shelf in enumerate(SHELVES):
            for sl_idx, slot in enumerate(SLOTS):
                # Test started 30-90 min ago
                started = now - dt.timedelta(minutes=rng.randint(30, 90))
                eng_idx  = rng.randrange(len(ENGINEERS))
                tp_idx   = rng.randrange(len(TEST_PURPOSE_CHOICES))
                exec_idx = rng.randrange(len(EXEC_TYPES))
                filename = filename_for(rack, shelf, slot, started, eng_idx, tp_idx, exec_idx)
                meta = parse_filename(filename)
                meta["server_ip"] = "demo"

                # Upsert the master session.
                client.insert(
                    "test_sessions",
                    [[
                        filename, "demo", meta["slot_id"], meta["rack"], meta["shelf"], meta["slot"],
                        meta.get("started_at"), now, "RUNNING",
                        meta.get("execution_type", ""), meta.get("project", ""), meta.get("controller", ""),
                        meta.get("interface", ""), meta.get("fw_arch", ""), meta.get("nand_type", ""),
                        meta.get("nand_density", ""), meta.get("manufacturer", ""), meta.get("package_density", ""),
                        meta.get("patch_version", ""), meta.get("release_candidate", ""), meta.get("firmware_version", ""),
                        meta.get("engineers", []), meta.get("test_purpose", ""), meta.get("storage_type", ""),
                        0, None,
                    ]],
                    column_names=[
                        "log_filename","server_ip","slot_id","rack","shelf","slot",
                        "started_at","last_seen_at","status",
                        "execution_type","project","controller","interface","fw_arch","nand_type",
                        "nand_density","manufacturer","package_density","patch_version","release_candidate",
                        "firmware_version","engineers","test_purpose","storage_type",
                        "snapshot_count","last_snapshot_at",
                    ],
                )
                sessions += 1

                # Emit ~6 snapshots spaced over the test duration.
                snap_count = rng.randint(4, 8)
                last_status = "RUNNING"
                last_snap_at = started
                for snap_idx in range(snap_count):
                    snap_offset = dt.timedelta(minutes=(snap_idx + 1) * 5)
                    snap_at = started + snap_offset
                    if snap_at > now:
                        break

                    status = fake_status(rng, snap_idx, snap_count)
                    seed = (rack * 100 + shelf * 10 + slot) * 100 + snap_idx
                    lines = patch_status(jitter(base_lines, seed), status)
                    result = parser.parse(lines, filename, meta)

                    s = result["snapshot"]
                    s["snapshot_id"]     = str(uuid.uuid4())
                    s["log_filename"]    = filename
                    s["server_ip"]       = "demo"
                    s["slot_id"]         = meta["slot_id"]
                    s["rack"]            = meta["rack"]
                    s["shelf"]           = meta["shelf"]
                    s["slot"]            = meta["slot"]
                    s["block_index"]     = snap_idx
                    s["block_started_at"] = snap_at  # override fixture's date with our timeline
                    if s.get("block_ended_at") is not None:
                        s["block_ended_at"] = snap_at + dt.timedelta(seconds=int(s.get("block_duration_s") or 3))

                    snapshot_columns = [
                        "snapshot_id","log_filename","server_ip","slot_id","rack","shelf","slot",
                        "block_index","block_started_at","block_ended_at","block_duration_s","block_status",
                        "wai","waf","ec_slc_max","ec_slc_min","ec_slc_avg","ec_mlc_max","ec_mlc_min","ec_mlc_avg",
                        "init_bb","rt_bb","reserved_bb","free_block_cnt_xlc","free_block_cnt_slc",
                        "ftl_open_count","read_reclaim_count","total_nand_write_bytes","total_nand_erase_bytes",
                        "temp_case","temp_thermal_value","temp_nanddts",
                        "latency_max_us","latency_avg_us","latency_min_us",
                        "io_total","read_io","write_io","read_io_kb","write_io_kb",
                        "reset_count","por_count","pmc_count","power_lvdf_event_count",
                        "phy_gear","phy_lanes",
                        "ssr_received_pon_count","ssr_received_spo_count","ssr_remain_reserved_block",
                        "variables",
                    ]
                    s_row = [s.get(c) for c in snapshot_columns]
                    s_row[snapshot_columns.index("variables")] = json.dumps(s.get("variables") or {}, default=str)
                    client.insert("interlude_snapshots", [s_row], column_names=snapshot_columns)
                    snapshots_total += 1
                    last_status = status
                    last_snap_at = snap_at

                    metric_rows = [[
                        s["snapshot_id"], filename, "demo", meta["slot_id"], snap_at, snap_idx,
                        m.get("section",""), m.get("key",""), m.get("value_num"),
                        m.get("value_str",""), m.get("unit",""),
                    ] for m in result["metrics"]]
                    if metric_rows:
                        client.insert(
                            "interlude_metrics", metric_rows,
                            column_names=[
                                "snapshot_id","log_filename","server_ip","slot_id","block_started_at","block_index",
                                "section","key","value_num","value_str","unit",
                            ],
                        )
                        metrics_total += len(metric_rows)

                # A handful of raw outside-block lines so the log_events panel
                # has something to show.
                noise = [
                    "Send Nop",
                    "Lun: 0",
                    "[LOG] Reclaim Count : 0",
                    "_advrpmb_support : 0 / _advrpmb_testmode : 0",
                ]
                log_rows = []
                for ln, txt in enumerate(noise, start=1):
                    log_rows.append([
                        "demo", filename, meta["slot_id"], ln, txt,
                        meta.get("started_at"),
                    ])
                client.insert(
                    "log_events", log_rows,
                    column_names=["server_ip","log_filename","slot_id","line_number","raw_line","log_timestamp"],
                )
                log_events_total += len(log_rows)

                # Re-upsert master with fresh aggregates / final status.
                final_status = "FAILED" if last_status == "FAILED" else "RUNNING"
                # 1-in-4 chance the test already finished in the demo window
                if rng.random() < 0.25 and final_status != "FAILED":
                    final_status = "COMPLETED"
                client.insert(
                    "test_sessions",
                    [[
                        filename, "demo", meta["slot_id"], meta["rack"], meta["shelf"], meta["slot"],
                        meta.get("started_at"), now, final_status,
                        meta.get("execution_type", ""), meta.get("project", ""), meta.get("controller", ""),
                        meta.get("interface", ""), meta.get("fw_arch", ""), meta.get("nand_type", ""),
                        meta.get("nand_density", ""), meta.get("manufacturer", ""), meta.get("package_density", ""),
                        meta.get("patch_version", ""), meta.get("release_candidate", ""), meta.get("firmware_version", ""),
                        meta.get("engineers", []), meta.get("test_purpose", ""), meta.get("storage_type", ""),
                        snap_count, last_snap_at,
                    ]],
                    column_names=[
                        "log_filename","server_ip","slot_id","rack","shelf","slot",
                        "started_at","last_seen_at","status",
                        "execution_type","project","controller","interface","fw_arch","nand_type",
                        "nand_density","manufacturer","package_density","patch_version","release_candidate",
                        "firmware_version","engineers","test_purpose","storage_type",
                        "snapshot_count","last_snapshot_at",
                    ],
                )

    print()
    print(f"  sessions   : {sessions}")
    print(f"  snapshots  : {snapshots_total}")
    print(f"  metrics    : {metrics_total}")
    print(f"  log_events : {log_events_total}")
    print()
    print("Open Grafana → http://localhost:3005  (admin / admin)")
    print("Lab Grid   →  http://localhost:3005/d/uta-lab-grid-v1/")
    print("Board Detail → http://localhost:3005/d/uta-board-detail-v1/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
