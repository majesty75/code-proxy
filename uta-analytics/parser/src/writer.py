"""
ClickHouse writer.

Three insert paths now:

  * write_log_events           — raw lines outside any recognised block
  * write_interlude_snapshot   — ONE row per >>>BEGIN..>>>END TL_interlude
  * write_interlude_metrics    — N rows per snapshot (long-form sidecar)

Plus the session/error helpers retained from the previous schema, updated
for the renames (platform → controller, production_step → patch_version)
and the dropped per-line ``parsed`` column on log_events.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

import clickhouse_connect

from config import Settings


# Master columns that test_sessions accepts on insert.
SESSION_COLUMNS = [
    "log_filename", "server_ip", "slot_id",
    "rack", "shelf", "slot",
    "started_at", "last_seen_at", "status",
    "execution_type", "project", "controller", "interface",
    "fw_arch", "nand_type", "nand_density",
    "manufacturer", "package_density",
    "patch_version", "release_candidate", "firmware_version",
    "engineers", "test_purpose", "storage_type",
    "snapshot_count", "last_snapshot_at",
]

LOG_EVENT_COLUMNS = [
    "server_ip", "log_filename", "slot_id",
    "line_number", "raw_line", "log_timestamp",
]

SNAPSHOT_COLUMNS = [
    "snapshot_id", "log_filename", "server_ip", "slot_id",
    "rack", "shelf", "slot",
    "block_index", "block_started_at", "block_ended_at",
    "block_duration_s", "block_status",
    # promoted typed metrics (definite tier)
    "wai", "waf",
    "ec_slc_max", "ec_slc_min", "ec_slc_avg",
    "ec_mlc_max", "ec_mlc_min", "ec_mlc_avg",
    "init_bb", "rt_bb", "reserved_bb",
    "free_block_cnt_xlc", "free_block_cnt_slc",
    "ftl_open_count", "read_reclaim_count",
    "total_nand_write_bytes", "total_nand_erase_bytes",
    "temp_case", "temp_thermal_value", "temp_nanddts",
    "latency_max_us", "latency_avg_us", "latency_min_us",
    # promoted (probable tier)
    "io_total", "read_io", "write_io", "read_io_kb", "write_io_kb",
    "reset_count", "por_count", "pmc_count", "power_lvdf_event_count",
    "phy_gear", "phy_lanes",
    "ssr_received_pon_count", "ssr_received_spo_count", "ssr_remain_reserved_block",
    "variables",
]

METRIC_COLUMNS = [
    "snapshot_id", "log_filename", "server_ip", "slot_id",
    "block_started_at", "block_index",
    "section", "key", "value_num", "value_str", "unit",
]


class ClickHouseWriter:
    def __init__(self, settings: Settings):
        self.client = clickhouse_connect.get_client(
            host=settings.ch_host,
            port=settings.ch_port,
            database=settings.ch_database,
            username=settings.ch_username,
            password=settings.ch_password,
        )

    # ------------------------------------------------------------------
    # Sessions (master)
    # ------------------------------------------------------------------
    def upsert_session(self, session: dict[str, Any]) -> None:
        """Insert a master row using ReplacingMergeTree replacement semantics.

        ClickHouse non-nullable columns reject explicit None even when the
        column has a DEFAULT — we drop unset keys so the table-level default
        applies.
        """
        row: dict[str, Any] = {}
        for col in SESSION_COLUMNS:
            v = session.get(col)
            if v is None:
                continue  # let the schema default fill it
            row[col] = v
        if "engineers" not in row:
            row["engineers"] = []
        if "last_seen_at" not in row:
            row["last_seen_at"] = datetime.utcnow()
        if "status" not in row:
            row["status"] = "RUNNING"
        self.client.insert(
            "test_sessions",
            [list(row.values())],
            column_names=list(row.keys()),
        )

    def mark_session_completed(self, filename: str, server_ip: str) -> None:
        """Re-insert the existing master row with status=COMPLETED."""
        result = self.client.query(
            "SELECT * FROM test_sessions FINAL "
            "WHERE log_filename = {fn:String} AND server_ip = {ip:String} "
            "LIMIT 1",
            parameters={"fn": filename, "ip": server_ip},
        )
        if not result.result_rows:
            self.client.insert(
                "test_sessions",
                [[filename, server_ip, "COMPLETED", datetime.utcnow()]],
                column_names=["log_filename", "server_ip", "status", "last_seen_at"],
            )
            return

        row = dict(zip(result.column_names, result.result_rows[0]))
        row["status"] = "COMPLETED"
        row["last_seen_at"] = datetime.utcnow()
        self.client.insert(
            "test_sessions",
            [list(row.values())],
            column_names=list(row.keys()),
        )

    def bump_session_after_snapshot(
        self,
        filename: str,
        server_ip: str,
        block_started_at: Optional[datetime],
        had_failure: bool,
    ) -> None:
        """After a snapshot lands, refresh the master with new aggregates."""
        result = self.client.query(
            "SELECT * FROM test_sessions FINAL "
            "WHERE log_filename = {fn:String} AND server_ip = {ip:String} "
            "LIMIT 1",
            parameters={"fn": filename, "ip": server_ip},
        )
        if not result.result_rows:
            return  # caller should have upserted first
        row = dict(zip(result.column_names, result.result_rows[0]))
        row["last_seen_at"] = datetime.utcnow()
        if block_started_at is not None:
            row["last_snapshot_at"] = block_started_at
        try:
            row["snapshot_count"] = int(row.get("snapshot_count") or 0) + 1
        except (TypeError, ValueError):
            row["snapshot_count"] = 1
        if had_failure and row.get("status") in (None, "RUNNING", "PASSED", "UNKNOWN"):
            row["status"] = "FAILED"
        elif row.get("status") in (None, "UNKNOWN"):
            row["status"] = "RUNNING"
        self.client.insert(
            "test_sessions",
            [list(row.values())],
            column_names=list(row.keys()),
        )

    # ------------------------------------------------------------------
    # Children
    # ------------------------------------------------------------------
    def write_log_events(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        data = [[r.get(c) for c in LOG_EVENT_COLUMNS] for r in rows]
        self.client.insert("log_events", data, column_names=LOG_EVENT_COLUMNS)

    def write_interlude_snapshot(self, snapshot: dict[str, Any]) -> str:
        """Insert a snapshot row. Returns the snapshot_id (UUID) used."""
        sid = snapshot.get("snapshot_id") or str(uuid.uuid4())
        snapshot["snapshot_id"] = sid
        if "variables" in snapshot and not isinstance(snapshot["variables"], str):
            snapshot["variables"] = json.dumps(snapshot["variables"], default=_json_default)
        row = [snapshot.get(c) for c in SNAPSHOT_COLUMNS]
        self.client.insert("interlude_snapshots", [row], column_names=SNAPSHOT_COLUMNS)
        return sid

    def write_interlude_metrics(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        data = [[r.get(c) for c in METRIC_COLUMNS] for r in rows]
        self.client.insert("interlude_metrics", data, column_names=METRIC_COLUMNS)

    # ------------------------------------------------------------------
    # Forensics
    # ------------------------------------------------------------------
    def write_parse_error(
        self,
        raw_message: str,
        filename: str,
        error_type: str,
        error_message: str,
    ) -> None:
        try:
            self.client.insert(
                "parse_errors",
                [[raw_message, filename, error_type, error_message]],
                column_names=["raw_message", "filename", "error_type", "error_message"],
            )
        except Exception:
            pass


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    return str(o)
