"""
SmartDeviceInformation lines (parallel to SmartCustomerReport):

  SmartDeviceInformation FWVersion         = 0x90000
  SmartDeviceInformation RomCodeVersion    = 0x10000
  SmartDeviceInformation ControllerVersion = 0x4b4a5801
  SmartDeviceInformation.ControllerEfuse0  = 0x773e4628
  SmartDeviceInformation.ControllerEfuse1  = 0x69001c54
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

LINE_RE = re.compile(
    r"^SmartDeviceInformation[\.\s]+(?P<key>[A-Za-z][\w]*?)\s*=\s*(?P<value>.+?)\s*$"
)


class SmartDeviceInfoParser(BaseParser):
    parser_id = "smart_device_info"
    priority = 16

    def can_parse(self, line: str, filename: str) -> bool:
        return "SmartDeviceInformation" in line

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        if not m:
            return {"event": "smart_device_info", "raw": body}

        key = m.group("key")
        value_str = m.group("value").strip()
        result: dict[str, Any] = {
            "event": "smart_device_info",
            "key": key,
            "value": value_str,
        }
        if value_str.startswith(("0x", "0X")):
            try:
                result["value_int"] = int(value_str.split()[0], 16)
            except ValueError:
                pass
        elif value_str.isdigit():
            result["value_int"] = int(value_str)
        return result
