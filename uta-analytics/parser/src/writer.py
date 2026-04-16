import clickhouse_connect
import json
from config import Settings


class ClickHouseWriter:
    def __init__(self, settings: Settings):
        self.client = clickhouse_connect.get_client(
            host=settings.ch_host,
            port=settings.ch_port,
            database=settings.ch_database,
        )

    def write_events(self, rows: list[dict]) -> None:
        """Batch insert parsed log events."""
        if not rows:
            return
        columns = [
            "server_ip", "slot_id", "log_filename", "line_number",
            "raw_line", "parsed", "log_timestamp",
            "platform", "firmware_version", "execution_type", "project",
        ]
        data = [[row.get(c) if c != "parsed" else json.dumps(row.get(c, {})) for c in columns] for row in rows]
        self.client.insert("log_events", data, column_names=columns)

    def upsert_session(self, session: dict) -> None:
        """Insert/update test session metadata."""
        columns = list(session.keys())
        data = [list(session.values())]
        self.client.insert("test_sessions", data, column_names=columns)
