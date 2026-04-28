import json
from datetime import datetime
import clickhouse_connect
from config import Settings


class ClickHouseWriter:
    def __init__(self, settings: Settings):
        self.client = clickhouse_connect.get_client(
            host=settings.ch_host,
            port=settings.ch_port,
            database=settings.ch_database,
            username=settings.ch_username,
            password=settings.ch_password,
        )

    def write_events(self, rows: list[dict]) -> None:
        """Batch insert parsed log events."""
        if not rows:
            return
        columns = [
            "server_ip", "slot_id", "log_filename", "line_number",
            "raw_line", "parsed", "log_timestamp",
            "platform", "firmware_version", "execution_type", "project",
            "interface", "fw_arch", "nand_type", "nand_density",
            "manufacturer", "package_density", "production_step",
            "release_candidate", "rack", "test_purpose", "storage_type"
        ]
        data = [[row.get(c) if c != "parsed" else json.dumps(row.get(c, {})) for c in columns] for row in rows]
        self.client.insert("log_events", data, column_names=columns)

    def upsert_session(self, session: dict) -> None:
        """Insert/update test session metadata."""
        columns = list(session.keys())
        data = [list(session.values())]
        self.client.insert("test_sessions", data, column_names=columns)

    def mark_session_completed(self, filename: str, server_ip: str) -> None:
        """
        Mark a session as completed by writing a new row to test_sessions.
        Relies on ReplacingMergeTree(last_seen_at) semantics: dashboards
        querying with FINAL see the row with the highest last_seen_at.
        Reads existing metadata first so the replacement row is complete
        (otherwise the merged row would lose platform/fw_version/etc.).
        """
        # Parameterised query — no string interpolation.
        result = self.client.query(
            "SELECT * FROM test_sessions FINAL "
            "WHERE log_filename = {fn:String} AND server_ip = {ip:String} "
            "LIMIT 1",
            parameters={"fn": filename, "ip": server_ip},
        )
        if not result.result_rows:
            # Completion arrived before any line was processed for this file.
            # Insert a minimal row so the completion isn't lost.
            self.client.insert(
                "test_sessions",
                [[filename, server_ip, "COMPLETED", datetime.now()]],
                column_names=["log_filename", "server_ip", "status", "last_seen_at"],
            )
            return

        row = dict(zip(result.column_names, result.result_rows[0]))
        row["status"] = "COMPLETED"
        row["last_seen_at"] = datetime.now()
        self.client.insert(
            "test_sessions",
            [list(row.values())],
            column_names=list(row.keys()),
        )

    def write_parse_error(self, raw_message: str, filename: str, error_type: str, error_message: str) -> None:
        """Best-effort recording of a line that the parser could not handle."""
        try:
            self.client.insert(
                "parse_errors",
                [[raw_message, filename, error_type, error_message]],
                column_names=["raw_message", "filename", "error_type", "error_message"],
            )
        except Exception:
            # Swallow — we don't want diagnostic writes to crash the consumer loop.
            pass
