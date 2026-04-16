import re
from typing import Any
from .base import BaseParser

# Common patterns in UTA logs
TIMESTAMP_RE = re.compile(r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
KV_RE = re.compile(r"(\w+)\s*[=:]\s*([^\s,;]+)")
TEST_CASE_RE = re.compile(r"(TC_\d+|Test_\d+|test_\d+)")
PASS_FAIL_RE = re.compile(r"\b(PASS|FAIL|PASSED|FAILED|ERROR|ABORT)\b", re.I)


class DefaultParser(BaseParser):
    parser_id = "default"

    def can_parse(self, line: str, filename: str) -> bool:
        return True  # Fallback parser, always matches

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        result: dict[str, Any] = {}

        ts_match = TIMESTAMP_RE.search(line)
        if ts_match:
            result["log_time"] = ts_match.group(1)

        for k, v in KV_RE.findall(line):
            result[k.lower()] = v

        tc_match = TEST_CASE_RE.search(line)
        if tc_match:
            result["test_case"] = tc_match.group(1)

        pf_match = PASS_FAIL_RE.search(line)
        if pf_match:
            result["result"] = pf_match.group(1).upper()

        return result
