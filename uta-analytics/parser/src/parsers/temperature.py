"""
Temperature notification block:

  Temperature Notification
  DeviceCaseRoughTemperature\t=\t\t27
  DeviceTooHighTempBoundary\t=\t\t85
  DeviceTooLowTempBoundary\t=\t\t-25
  ShutDownNotiLevel\t\t=\t\t0
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

KNOWN_KEYS = {
    "DeviceCaseRoughTemperature",
    "DeviceTooHighTempBoundary",
    "DeviceTooLowTempBoundary",
    "ShutDownNotiLevel",
}
LINE_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_]*?)\s*=\s*(?P<value>-?\d+)\s*$")
HEADER_RE = re.compile(r"^Temperature\s+Notification\s*$")


class TemperatureParser(BaseParser):
    parser_id = "temperature"
    priority = 25

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        if HEADER_RE.match(body):
            return True
        m = LINE_RE.match(body)
        return bool(m and m.group("key") in KNOWN_KEYS)

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        if HEADER_RE.match(body):
            return {"event": "temperature", "kind": "header"}
        if (m := LINE_RE.match(body)):
            return {
                "event": "temperature",
                "kind": "field",
                "key": m.group("key"),
                "value": int(m.group("value")),
            }
        return {"event": "temperature", "raw": body}
