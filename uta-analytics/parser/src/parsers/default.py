"""
Default parser — the lowest-priority catchall. Pulls a leading log_time
(if present) and best-effort extracts key/value pairs and PASS/FAIL hints.

Claimed:
  Send Nop
  nCurrentLun : 0
  Lun: 0
  _hpb 0, _hpbver 0, gnHpbSpecType 0
  _advrpmb_support : 0 / _advrpmb_testmode : 0 / ...
  Last _lu32Check 8
  _sbsize 1113587712 _sbsize_slc 371195904 _sbpage 262144
  Statistic RunTimeBadBlock = 0
  Free Block Cnt  = xLC 260 / SLC 0
  TurboWriteBufferLifeTimeEst[7] : 0 / 0 (= Selector 0 / 1)
  Random Sleep : 143 us       (also caught by elapsed_op when matching)
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

TIMESTAMP_RE = re.compile(r"^\s*(\d{4}:\d{2}:\d{2}(?:\.\d+)?)")
KV_COLON_RE = re.compile(r"(\w+)\s*:\s*([^\s,;/]+)")
KV_EQUALS_RE = re.compile(r"(\w+)\s*=\s*([^\s,;/]+)")
SLASH_KV_RE = re.compile(r"(\w+)\s*[:=]\s*([^\s,;/]+)\s*/")
TEST_CASE_RE = re.compile(r"\b(TC_\d+|Test_\d+|test_\d+)\b")
PASS_FAIL_RE = re.compile(r"\b(PASS|FAIL|PASSED|FAILED|ERROR|ABORT)\b", re.IGNORECASE)


class DefaultParser(BaseParser):
    parser_id = "default"
    priority = 999  # Always last.

    def can_parse(self, line: str, filename: str) -> bool:
        return True

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        result: dict[str, Any] = {"event": "default"}

        m = TIMESTAMP_RE.search(line)
        if m:
            result["log_time"] = m.group(1)

        body = TIMESTAMP_RE.sub("", line, count=1).strip()
        if not body:
            return result

        kv: dict[str, str] = {}
        # Slash-separated K:V groups (common in feature dumps)
        for k, v in SLASH_KV_RE.findall(body):
            kv[k.lower()] = v
        # Generic K=V and K:V
        for k, v in KV_EQUALS_RE.findall(body):
            kv.setdefault(k.lower(), v)
        for k, v in KV_COLON_RE.findall(body):
            kv.setdefault(k.lower(), v)
        if kv:
            result["fields"] = kv

        if (tc := TEST_CASE_RE.search(body)):
            result["test_case"] = tc.group(1)

        if (pf := PASS_FAIL_RE.search(body)):
            result["result"] = pf.group(1).upper()

        return result
