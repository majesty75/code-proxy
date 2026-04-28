"""
TL_SAMPLE_INFORMATION block fields (after the banner):

  *************************TL_SAMPLE_INFORMATION**************************
  DEVICE_DENSITY: 256GB
  DEVICE_NAND_TYPE: V8_TLC_512Gb_4P
  PRODUCT_TYPE: Sirius 3.1 Gen
  FIRMWARE_VERSION: P09 RC00 FW00
  EVT: 2
  WAFER_TYPE : HAN/MX Wafer
  ***************************************************
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

KNOWN_KEYS = {
    "DEVICE_DENSITY", "DEVICE_NAND_TYPE", "PRODUCT_TYPE",
    "FIRMWARE_VERSION", "EVT", "WAFER_TYPE",
}
LINE_RE = re.compile(r"^(?P<key>[A-Z_][A-Z0-9_]+)\s*:\s*(?P<value>.+?)\s*$")


class SampleInfoParser(BaseParser):
    parser_id = "sample_info"
    priority = 15

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        return bool(m and m.group("key") in KNOWN_KEYS)

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        if not m:
            return {"event": "sample_info", "raw": body}
        return {
            "event": "sample_info",
            "key": m.group("key"),
            "value": m.group("value").strip(),
        }
