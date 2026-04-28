"""
Operation-level durations and power actions:

  *Reset Device
  *Turn Power ON
  *Turn Power OFF
  [HWReset_Std]
  WriteBuffer Complete!! ElapsedTime : 18293 ms (FW Size 816.00KB)
  Complete FB Write (7070 ms)
  Nop Duration 449934us
  Random Sleep : 143 us
  ReadBuffer Complete!!
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

POWER_RE = re.compile(r"^\*\s*(?P<action>Turn Power (?:ON|OFF)|Reset Device)\s*$", re.IGNORECASE)
HWRESET_RE = re.compile(r"^\[HWReset_(?P<kind>\w+)\]\s*$")
WRITE_BUFFER_RE = re.compile(
    r"^(?P<op>WriteBuffer|ReadBuffer)\s+Complete!!\s*(?:ElapsedTime\s*:\s*(?P<elapsed>\d+)\s*(?P<unit>ms|us|sec|s))?\s*(?:\((?P<note>[^)]+)\))?\s*$"
)
COMPLETE_FB_RE = re.compile(r"^Complete\s+(?P<op>FB Write|FB Read|.+?)\s*\((?P<elapsed>\d+)\s*(?P<unit>ms|us|sec|s)\)\s*$")
NOP_RE = re.compile(r"^Nop\s+Duration\s+(?P<elapsed>\d+)\s*(?P<unit>us|ms|sec|s)\s*$")
SLEEP_RE = re.compile(r"^Random\s+Sleep\s*:\s*(?P<elapsed>\d+)\s*(?P<unit>us|ms|sec|s)\s*$")


def _to_us(num: int, unit: str) -> int:
    u = unit.lower()
    return num * {"us": 1, "ms": 1000, "sec": 1_000_000, "s": 1_000_000}.get(u, 1)


class ElapsedOpParser(BaseParser):
    parser_id = "elapsed_op"
    priority = 19

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        return bool(
            POWER_RE.match(body) or HWRESET_RE.match(body)
            or WRITE_BUFFER_RE.match(body) or COMPLETE_FB_RE.match(body)
            or NOP_RE.match(body) or SLEEP_RE.match(body)
        )

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

        if (m := POWER_RE.match(body)):
            action = m.group("action").lower()
            return {"event": "power_action", "action": action}
        if (m := HWRESET_RE.match(body)):
            return {"event": "hw_reset", "kind": m.group("kind")}
        if (m := WRITE_BUFFER_RE.match(body)):
            r: dict[str, Any] = {"event": "buffer_op", "op": m.group("op")}
            if m.group("elapsed"):
                r["elapsed_us"] = _to_us(int(m.group("elapsed")), m.group("unit"))
                r["raw_elapsed"] = m.group("elapsed") + (m.group("unit") or "")
            if m.group("note"):
                r["note"] = m.group("note").strip()
            return r
        if (m := COMPLETE_FB_RE.match(body)):
            return {
                "event": "operation_complete",
                "op": m.group("op").strip(),
                "elapsed_us": _to_us(int(m.group("elapsed")), m.group("unit")),
            }
        if (m := NOP_RE.match(body)):
            return {
                "event": "nop_duration",
                "elapsed_us": _to_us(int(m.group("elapsed")), m.group("unit")),
            }
        if (m := SLEEP_RE.match(body)):
            return {
                "event": "random_sleep",
                "elapsed_us": _to_us(int(m.group("elapsed")), m.group("unit")),
            }
        return {"event": "elapsed_op", "raw": body}
