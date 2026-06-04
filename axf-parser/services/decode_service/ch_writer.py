"""Batched ClickHouse writer for the four AXF tables."""
import time

import clickhouse_connect


class ClickHouseWriter:
    def __init__(self, cfg, retries=30):
        last = None
        for _ in range(retries):
            try:
                self.client = clickhouse_connect.get_client(
                    host=cfg.CH_HOST, port=cfg.CH_PORT, database=cfg.CH_DB,
                    username=cfg.CH_USER, password=cfg.CH_PASS,
                )
                return
            except Exception as e:        # CH still warming up
                last = e
                time.sleep(2)
        raise last

    def write_snapshot(self, snap):
        self.client.insert(
            "uta.axf_snapshots",
            [[snap["snapshot_id"], snap["trname"], snap["boardname"], snap["core"],
              snap["product"], snap["fw_build_hash"], snap["dump_timestamp"],
              snap["elapsed_s"], snap["layout_key"], snap["object_key"],
              snap["decoded_json"], snap["decode_status"], snap["decode_error_cnt"]]],
            column_names=["snapshot_id", "trname", "boardname", "core", "product",
                          "fw_build_hash", "dump_timestamp", "elapsed_s", "layout_key",
                          "object_key", "decoded_json", "decode_status", "decode_error_cnt"],
        )

    def write_metrics(self, snap, rows):
        if not rows:
            return
        cols = ["snapshot_id", "trname", "boardname", "core", "product",
                "dump_timestamp", "elapsed_s", "section", "key", "value_num",
                "value_str", "unit"]
        data = [[snap["snapshot_id"], snap["trname"], snap["boardname"], snap["core"],
                 snap["product"], snap["dump_timestamp"], snap["elapsed_s"],
                 r["section"], r["key"], r["value_num"], r["value_str"], r["unit"]]
                for r in rows]
        self.client.insert("uta.axf_metrics", data, column_names=cols)

    def upsert_session(self, snap):
        self.client.insert(
            "uta.axf_sessions",
            [[snap["trname"], snap["boardname"], snap["core"], snap["product"],
              snap["product_version"], snap["fw_name"], snap["fw_build_hash"],
              snap["nand_type"], snap["nand_density"], snap["test_started_at"],
              snap["dump_timestamp"], snap["dump_timestamp"], 1]],
            column_names=["trname", "boardname", "core", "product", "product_version",
                          "fw_name", "fw_build_hash", "nand_type", "nand_density",
                          "test_started_at", "first_dump_at", "last_dump_at", "dump_count"],
        )

    def write_error(self, object_key, boardname, core, build_hash, error_type, msg):
        self.client.insert(
            "uta.axf_decode_errors",
            [[object_key, boardname, core, build_hash, error_type, msg[:2000]]],
            column_names=["object_key", "boardname", "core", "fw_build_hash",
                          "error_type", "error_message"],
        )
