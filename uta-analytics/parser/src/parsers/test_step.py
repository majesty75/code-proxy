import re
from typing import Any
from .base import BaseParser

# >>>BEGIN TL_INIT       Apr 20 16:24:08
BEGIN_RE = re.compile(r"^>>>BEGIN\s+(?P<step>\S+?)(?:\?(?P<args>\S+))?(?:\s+(?P<wallclock>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}))?\s*$")
# >>>END TL_INIT         Apr 20 16:24:08    [PASSED]
END_RE = re.compile(r"^>>>END\s+(?P<step>\S+?)(?:\s+(?P<wallclock>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}))?\s*\[(?P<status>[A-Z]+)\]\s*$")
# >>>PROCESS 1 / 221
PROCESS_RE = re.compile(r"^>>>PROCESS\s+(?P<current>\d+)\s*/\s*(?P<total>\d+)\s*$")
# >>>ELAPSED_TIME    0000:00:00
ELAPSED_RE = re.compile(r"^>>>ELAPSED_TIME\s+(?P<elapsed>\d{4}:\d{2}:\d{2})\s*$")
# >>>SCRIPT : 63  /share/_Script_/...
SCRIPT_RE = re.compile(r"^>>>SCRIPT\s*:\s*(?P<count>\d+)\s+(?P<path>\S+)\s*$")


class TestStepParser(BaseParser):
    parser_id = "test_step"
    priority = 5

    def can_parse(self, line: str, filename: str) -> bool:
        s = self._strip_time(line)
        return s.startswith(">>>BEGIN") or s.startswith(">>>END") or \
               s.startswith(">>>PROCESS") or s.startswith(">>>ELAPSED_TIME") or \
               s.startswith(">>>SCRIPT")

    @staticmethod
    def _strip_time(line: str) -> str:
        # Lines start with `HHHH:MM:SS ` from the test framework.
        return re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        # Capture the leading log_time so dashboards can plot test-step events
        # against the session timeline. Other parsers also do this.
        m_time = re.match(r"^\s*(?P<t>\d{4}:\d{2}:\d{2})\s+", line)
        result: dict[str, Any] = {"event": "test_step"}
        if m_time:
            # log_time uses the framework's HHHH:MM:SS (relative). The consumer
            # converts it to absolute using the session started_at.
            result["log_time"] = m_time.group("t").replace("0000:", "00:", 1)
            # Preserve the raw 4-digit-hour form too; useful for very long runs.
            result["raw_log_time"] = m_time.group("t")

        body = self._strip_time(line)

        if (m := BEGIN_RE.match(body)):
            result.update({
                "kind": "begin",
                "step": m.group("step"),
                "args": m.group("args") or "",
                "wallclock": m.group("wallclock") or "",
            })
            return result
        if (m := END_RE.match(body)):
            result.update({
                "kind": "end",
                "step": m.group("step"),
                "wallclock": m.group("wallclock") or "",
                "status": m.group("status"),
                "result": m.group("status"),
            })
            return result
        if (m := PROCESS_RE.match(body)):
            result.update({
                "kind": "process",
                "current": int(m.group("current")),
                "total": int(m.group("total")),
            })
            return result
        if (m := ELAPSED_RE.match(body)):
            h, mi, s = (int(p) for p in m.group("elapsed").split(":"))
            result.update({
                "kind": "elapsed_time",
                "elapsed": m.group("elapsed"),
                "elapsed_seconds": h * 3600 + mi * 60 + s,
            })
            return result
        if (m := SCRIPT_RE.match(body)):
            result.update({
                "kind": "script",
                "count": int(m.group("count")),
                "path": m.group("path"),
            })
            return result
        return result
