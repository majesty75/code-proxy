"""
Reference clock log lines:

  [RefClk LOG] Prev RefClkFreq 0x2
  [RefClk LOG] RefClkFreq Changed !! Prev 0x2 -> Cur 0x1
  [RefClk LOG] Cur Reference Clock : 26MHz
  [RefClk LOG] Write Attribute RefClkFreq to 0x2
  [RefClk LOG] Changed Reference Clock : 38.4Mhz
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

PREFIX = "[RefClk LOG]"

CHANGED_RE = re.compile(r"RefClkFreq\s+Changed\s*!!\s*Prev\s+(?P<prev>\S+)\s*->\s*Cur\s+(?P<cur>\S+)")
CUR_CLOCK_RE = re.compile(r"Cur\s+Reference\s+Clock\s*:\s*(?P<freq>\S+)")
CHANGED_CLOCK_RE = re.compile(r"Changed\s+Reference\s+Clock\s*:\s*(?P<freq>\S+)")
WRITE_ATTR_RE = re.compile(r"Write\s+Attribute\s+RefClkFreq\s+to\s+(?P<value>\S+)")
PREV_FREQ_RE = re.compile(r"Prev\s+RefClkFreq\s+(?P<value>\S+)")


class RefClkParser(BaseParser):
    parser_id = "refclk"
    priority = 21

    def can_parse(self, line: str, filename: str) -> bool:
        return PREFIX in line

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        # Strip the bracket prefix
        rest = body.replace(PREFIX, "", 1).strip()

        if (m := CHANGED_RE.search(rest)):
            return {"event": "refclk", "kind": "freq_changed",
                    "prev": m.group("prev"), "cur": m.group("cur")}
        if (m := CUR_CLOCK_RE.search(rest)):
            return {"event": "refclk", "kind": "current_clock", "frequency": m.group("freq")}
        if (m := CHANGED_CLOCK_RE.search(rest)):
            return {"event": "refclk", "kind": "changed_clock", "frequency": m.group("freq")}
        if (m := WRITE_ATTR_RE.search(rest)):
            return {"event": "refclk", "kind": "write_attribute", "value": m.group("value")}
        if (m := PREV_FREQ_RE.search(rest)):
            return {"event": "refclk", "kind": "prev_frequency", "value": m.group("value")}

        return {"event": "refclk", "raw": rest}
