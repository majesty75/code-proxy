"""
SPOR (Sudden Power-Off Recovery) cycle markers and RBH logging:

  SPOR Count 0 for RBH Logging (Dumb File Path: /data/data/abc_0000.txt)
  RBH Logging Scan Count - 0
  < RBH Logging Context >
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

SPOR_RE = re.compile(
    r"^SPOR\s+Count\s+(?P<count>\d+)\s+for\s+RBH\s+Logging\s*\((?:Dumb\s+File\s+Path\s*:\s*(?P<path>[^)]+))?\)\s*$"
)
RBH_SCAN_RE = re.compile(r"^RBH\s+Logging\s+Scan\s+Count\s*-\s*(?P<count>\d+)\s*$")
RBH_CONTEXT_RE = re.compile(r"^<\s*RBH\s+Logging\s+Context\s*>\s*$")


class SporRbhParser(BaseParser):
    parser_id = "spor_rbh"
    priority = 20

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        return bool(SPOR_RE.match(body) or RBH_SCAN_RE.match(body) or RBH_CONTEXT_RE.match(body))

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        if (m := SPOR_RE.match(body)):
            r: dict[str, Any] = {"event": "spor_cycle", "count": int(m.group("count"))}
            if m.group("path"):
                r["dump_path"] = m.group("path").strip()
            return r
        if (m := RBH_SCAN_RE.match(body)):
            return {"event": "rbh_scan_count", "count": int(m.group("count"))}
        if RBH_CONTEXT_RE.match(body):
            return {"event": "rbh_context_begin"}
        return {"event": "spor_rbh", "raw": body}
