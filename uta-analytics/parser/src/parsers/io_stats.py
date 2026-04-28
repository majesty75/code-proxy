"""
Per-line IO statistics. The block is multi-line in the source log but each
line is independently parseable, so we emit one parsed row per line. A future
multi-line aggregator can stitch them into a single block-level row.

  Reset Count: 0
  POR Count: 0
  PMC Count: 0
  Io Count: 297
  Read Io Count: 34
  Read Io Length: 94 KB
  Write Io Count: 2
  Write Io Length: 0 KB
  Maximum Latency Time: 53346 usec
  Average Latency Time: 946 usec
  Minimum Latency Time: 356 usec
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

# Map "raw key" -> (canonical_key, kind)
KEYS = {
    "Reset Count":          ("reset_count",          "count"),
    "POR Count":            ("por_count",            "count"),
    "PMC Count":            ("pmc_count",            "count"),
    "Io Count":             ("io_count",             "count"),
    "Read Io Count":        ("read_io_count",        "count"),
    "Read Io Length":       ("read_io_bytes",        "size"),
    "Write Io Count":       ("write_io_count",       "count"),
    "Write Io Length":      ("write_io_bytes",       "size"),
    "Maximum Latency Time": ("max_latency_us",       "latency"),
    "Average Latency Time": ("avg_latency_us",       "latency"),
    "Minimum Latency Time": ("min_latency_us",       "latency"),
}

LINE_RE = re.compile(r"^(?P<key>[A-Z][A-Za-z ]+?)\s*:\s*(?P<rest>.+?)\s*$")
SIZE_RE = re.compile(r"^(?P<num>\d+)\s*(?P<unit>KB|MB|GB|B)?\s*$")
LAT_RE = re.compile(r"^(?P<num>\d+)\s*(?P<unit>usec|us|ms|s)?\s*$")
COUNT_RE = re.compile(r"^(?P<num>\d+)\s*$")


def _to_bytes(num: int, unit: str | None) -> int:
    u = (unit or "B").upper()
    return num * {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}.get(u, 1)


def _to_us(num: int, unit: str | None) -> int:
    u = (unit or "us").lower()
    return num * {"us": 1, "usec": 1, "ms": 1000, "s": 1_000_000}.get(u, 1)


class IoStatsParser(BaseParser):
    parser_id = "io_stats"
    priority = 14

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        for k in KEYS:
            if body.startswith(k + ":"):
                return True
        return False

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        if not m:
            return {"event": "io_stat", "raw": body}

        key_raw = m.group("key").strip()
        rest = m.group("rest").strip()
        canonical, kind = KEYS.get(key_raw, (key_raw.lower().replace(" ", "_"), "count"))

        result: dict[str, Any] = {"event": "io_stat", "metric": canonical, "raw_value": rest}

        if kind == "count":
            mc = COUNT_RE.match(rest)
            if mc:
                result["value"] = int(mc.group("num"))
        elif kind == "size":
            ms = SIZE_RE.match(rest)
            if ms:
                num = int(ms.group("num"))
                unit = ms.group("unit") or "B"
                result["value"] = _to_bytes(num, unit)
                result["unit"] = "B"
                result["raw_unit"] = unit
        elif kind == "latency":
            ml = LAT_RE.match(rest)
            if ml:
                num = int(ml.group("num"))
                unit = ml.group("unit") or "us"
                result["value"] = _to_us(num, unit)
                result["unit"] = "us"
                result["raw_unit"] = unit

        return result
