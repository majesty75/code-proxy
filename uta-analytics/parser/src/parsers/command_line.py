"""
First line of a UTA log records the full UfsTester invocation:

  [ CommandLine: /data/UfsTester TL_FFU?Path=...,Mode=1 TL_PMC?PV TL_LotID
    -s /share/_Script_/.../FFU_Aging_NoPreTW -b --repeat-script-only --repeat=5
    --setbuf=0x10000 --on-failed=TL_Vendor_Timeout --interlude --testinfologging
    -o /share/UTA_FULL_Logs/...log -O /share/UTA_FULL_Logs/Status/...log ]
"""
from __future__ import annotations
import re
import shlex
from typing import Any
from .base import BaseParser

CMD_RE = re.compile(r"^\[\s*CommandLine\s*:\s*(?P<body>.+?)\s*\]\s*$")


class CommandLineParser(BaseParser):
    parser_id = "command_line"
    priority = 8

    def can_parse(self, line: str, filename: str) -> bool:
        body = self._strip_time(line)
        return body.startswith("[ CommandLine:") or body.startswith("[CommandLine:")

    @staticmethod
    def _strip_time(line: str) -> str:
        return re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = self._strip_time(line)
        m = CMD_RE.match(body)
        if not m:
            return {"event": "command_line", "raw": body}

        cmd = m.group("body").strip()

        # shlex respects quoted segments which are common with -O paths.
        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError:
            tokens = cmd.split()

        result: dict[str, Any] = {"event": "command_line"}
        if tokens:
            result["binary"] = tokens[0]

        # TL_* pseudo-args (test list ids)
        tl_args = [t for t in tokens if re.match(r"^TL_[A-Za-z0-9_]+", t)]
        if tl_args:
            result["test_list"] = tl_args

        # Flag pairs
        flags: dict[str, Any] = {}
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t.startswith("--") and "=" in t:
                k, v = t[2:].split("=", 1)
                flags[k] = v
            elif t.startswith("--"):
                # --interlude (boolean) or --foo bar
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    flags[t[2:]] = tokens[i + 1]
                    i += 1
                else:
                    flags[t[2:]] = True
            elif t.startswith("-") and len(t) > 1 and i + 1 < len(tokens):
                flags[t[1:]] = tokens[i + 1]
                i += 1
            i += 1
        if flags:
            result["flags"] = flags
            # Common ones surfaced as top-level for easier filtering
            if "s" in flags:
                result["script"] = flags["s"]
            if "o" in flags:
                result["output_log"] = flags["o"]
            if "O" in flags:
                result["output_status"] = flags["O"]

        return result
