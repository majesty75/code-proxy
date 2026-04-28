"""
Multi-stage FW-type detection markers:

  [_SetFwType][0. Initial Value] GEN
  [_SetFwType][1. Patch Version via Inquiry] P09 FW00 -> GEN
  [_SetFwType][2-1. Patch Number via DevInfoDesc] P09 FW00 -> GEN (0x90000)
  [_SetFwType][3-1. FW Release Date via SmartDescriptor] 0 -> GEN
  [_SetFwType][3-2. OEM ID via SmartDescriptor] 1(0x1) -> GEN
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

LINE_RE = re.compile(
    r"^\[_SetFwType\]\[(?P<stage>[\d\-]+)\.\s*(?P<step>[^\]]+?)\]\s*(?P<body>.+?)\s*$"
)
TRANSITION_RE = re.compile(r"^(?P<from>.+?)\s*->\s*(?P<to>\S+)(?:\s*\((?P<extra>[^)]+)\))?\s*$")


class SetFwTypeParser(BaseParser):
    parser_id = "set_fw_type"
    priority = 12

    def can_parse(self, line: str, filename: str) -> bool:
        return "[_SetFwType]" in line

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LINE_RE.match(body)
        if not m:
            return {"event": "set_fw_type", "raw": body}

        result: dict[str, Any] = {
            "event": "set_fw_type",
            "stage": m.group("stage"),
            "step": m.group("step").strip(),
        }
        rest = m.group("body").strip()

        t = TRANSITION_RE.match(rest)
        if t:
            result.update({
                "from": t.group("from").strip(),
                "to": t.group("to").strip(),
            })
            if t.group("extra"):
                result["extra"] = t.group("extra").strip()
        else:
            result["value"] = rest

        return result
