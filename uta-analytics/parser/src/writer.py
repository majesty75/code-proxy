import clickhouse_connect
import json
from config import Settings


class ClickHouseWriter:
    def __init__(self, settings: Settings):
        self.client = clickhouse_connect.get_client(
            host=settings.ch_host,
            port=settings.ch_port,
            database=settings.ch_database,
            username="default",
            password="password",
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
        """Mark a session as completed when the file is moved."""
        query = f"ALTER TABLE uta.test_sessions UPDATE status = 'COMPLETED' WHERE log_filename = '{filename}' AND server_ip = '{server_ip}'"
        self.client.command(query)
