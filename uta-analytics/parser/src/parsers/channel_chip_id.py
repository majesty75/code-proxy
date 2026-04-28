"""
NAND chip-ID hex dump per channel/way/die:

  [CH0 WAY0 DIE0] ec, 5e, a8, 3f, 88, cf
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

LINE_RE = re.compile(
    r"^\[CH(?P<ch>\d+)\s+WAY(?P<way>\d+)\s+DIE(?P<die>\d+)\]\s+(?P<bytes>(?:[0-9a-fA-F]{1,2}\s*,?\s*)+)\s*$"
)


class ChannelChipIdParser(BaseParser):
    parser_id = "channel_chip_id"
    priority = 17

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        return bool(LINE_RE.match(body))

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        if not m:
            return {"event": "chip_id", "raw": body}
        bytes_str = m.group("bytes")
        chip_bytes = [b.strip() for b in bytes_str.split(",") if b.strip()]
        return {
            "event": "chip_id",
            "channel": int(m.group("ch")),
            "way": int(m.group("way")),
            "die": int(m.group("die")),
            "id_bytes": chip_bytes,
            "id_hex": "".join(b.zfill(2) for b in chip_bytes),
        }
