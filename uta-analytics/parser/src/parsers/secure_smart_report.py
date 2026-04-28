"""
Secure Smart Report exception lines:

  [Secure Smart Report] Exception Top Level: 0x0 (None)
  [Secure Smart Report] Exception SubCode: 0x0 (None)
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

LINE_RE = re.compile(
    r"^\[Secure\s+Smart\s+Report\]\s+(?P<key>[A-Za-z][A-Za-z ]*?)\s*:\s*(?P<value>\S+)(?:\s*\((?P<note>[^)]+)\))?\s*$"
)


class SecureSmartReportParser(BaseParser):
    parser_id = "secure_smart_report"
    priority = 16

    def can_parse(self, line: str, filename: str) -> bool:
        return "[Secure Smart Report]" in line

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        if not m:
            return {"event": "secure_smart_report", "raw": body}
        result: dict[str, Any] = {
            "event": "secure_smart_report",
            "key": m.group("key").strip(),
            "value": m.group("value"),
        }
        v = m.group("value")
        if v.startswith(("0x", "0X")):
            try:
                result["value_int"] = int(v, 16)
            except ValueError:
                pass
        if m.group("note"):
            result["note"] = m.group("note").strip()
        return result
