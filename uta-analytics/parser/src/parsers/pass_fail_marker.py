"""
Bracketed PASS/FAIL markers, with optional channel/block locator and
expected/actual values:

  [PASS][CH 0][BLK 0] Patch Header Signature (Expect : 0x55465348, Actual : 0x55465348)
  [FAIL][CH 1][BLK 2] ECC Mismatch (Expect : 0x10, Actual : 0x12)
  [PASS] Some short description
  OPEN /dev/ufs0 [PASS]
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

# Recognises both leading and trailing [PASS]/[FAIL]
HEAD_RE = re.compile(
    r"^\[(?P<status>PASS|PASSED|FAIL|FAILED|ERROR|ABORT)\](?P<locators>(?:\[[^\]]+\])*)\s*(?P<rest>.*)$"
)
TRAIL_RE = re.compile(r"^(?P<rest>.*?)\s*\[(?P<status>PASS|PASSED|FAIL|FAILED|ERROR|ABORT)\]\s*$")
LOCATOR_RE = re.compile(r"\[\s*([A-Z]{2,4})\s+(\d+)\s*\]")
EXPECT_ACTUAL_RE = re.compile(
    r"\((?:Expect|EXPECT)\s*:\s*(?P<expect>\S+?)\s*,\s*(?:Actual|ACTUAL)\s*:\s*(?P<actual>\S+?)\)"
)


class PassFailMarkerParser(BaseParser):
    parser_id = "pass_fail_marker"
    priority = 10

    def can_parse(self, line: str, filename: str) -> bool:
        body = self._strip_time(line)
        return bool(HEAD_RE.match(body) or TRAIL_RE.match(body))

    @staticmethod
    def _strip_time(line: str) -> str:
        return re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = self._strip_time(line)
        result: dict[str, Any] = {"event": "pass_fail"}

        m = HEAD_RE.match(body)
        if m:
            status = m.group("status").upper()
            normalised = "PASSED" if status in ("PASS", "PASSED") else \
                         "FAILED" if status in ("FAIL", "FAILED") else status
            result.update({"status": normalised, "raw_status": status})
            locators = m.group("locators") or ""
            for ltype, lval in LOCATOR_RE.findall(locators):
                result[f"loc_{ltype.lower()}"] = int(lval)
            rest = m.group("rest").strip()
        else:
            mt = TRAIL_RE.match(body)
            if not mt:
                return result
            status = mt.group("status").upper()
            result.update({
                "status": "PASSED" if status in ("PASS", "PASSED") else
                          "FAILED" if status in ("FAIL", "FAILED") else status,
                "raw_status": status,
            })
            rest = mt.group("rest").strip()

        if rest:
            ea = EXPECT_ACTUAL_RE.search(rest)
            if ea:
                result["expect"] = ea.group("expect")
                result["actual"] = ea.group("actual")
                rest = EXPECT_ACTUAL_RE.sub("", rest).strip()
            result["description"] = rest.rstrip(" ()")

        return result
