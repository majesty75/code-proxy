"""
Hex memory dumps:

  0000000000: 01 00 00 00 00 00 ee 58 00 0c 02 00 00 00 00 00  .......X........
  0000000010: 00 00 00 00 00 00 00 00 00 00                    ..........
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

LINE_RE = re.compile(
    r"^(?P<offset>[0-9a-fA-F]{8,16}):\s+(?P<hex>(?:[0-9a-fA-F]{2}\s+){1,16})\s*(?P<ascii>\S.*)?$"
)


class HexDumpParser(BaseParser):
    parser_id = "hex_dump"
    priority = 30

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1)
        return bool(LINE_RE.match(body.strip()))

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        if not m:
            return {"event": "hex_dump", "raw": body}
        hex_bytes = m.group("hex").split()
        return {
            "event": "hex_dump",
            "offset_hex": m.group("offset"),
            "offset": int(m.group("offset"), 16),
            "byte_count": len(hex_bytes),
            "ascii": (m.group("ascii") or "").strip(),
        }
