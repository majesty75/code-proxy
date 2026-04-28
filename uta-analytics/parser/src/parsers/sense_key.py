"""
SCSI sense key reports:

  Sense Key = 0x5, ASC = 0x24, Rom Code!! Read Buffer Command doesn't work!
  Sensekey 0x5 ASC 0 ASCQ 0
  [DEBUG] Sensekey 0x5 ASC 0 ASCQ 0
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

LONG_RE = re.compile(
    r"Sense\s*Key\s*=\s*(?P<sk>\S+?)\s*,\s*ASC\s*=\s*(?P<asc>\S+?)(?:\s*,\s*ASCQ\s*=\s*(?P<ascq>\S+?))?\s*(?:,(?P<note>.*))?$"
)
SHORT_RE = re.compile(
    r"Sensekey\s+(?P<sk>\S+)\s+ASC\s+(?P<asc>\S+)(?:\s+ASCQ\s+(?P<ascq>\S+))?\s*$"
)


def _to_int(v: str) -> int | None:
    try:
        return int(v, 16) if v.startswith(("0x", "0X")) else int(v)
    except ValueError:
        return None


class SenseKeyParser(BaseParser):
    parser_id = "sense_key"
    priority = 23

    def can_parse(self, line: str, filename: str) -> bool:
        body = line.strip()
        return ("Sense Key" in body) or ("Sensekey" in body)

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = LONG_RE.search(body) or SHORT_RE.search(body)
        if not m:
            return {"event": "sense_key", "raw": body}
        d = m.groupdict()
        result: dict[str, Any] = {
            "event": "sense_key",
            "sense_key": d["sk"],
            "asc": d.get("asc"),
        }
        if d.get("ascq"):
            result["ascq"] = d["ascq"]
        if (note := d.get("note")) and note.strip():
            result["note"] = note.strip()
        for k in ("sense_key", "asc", "ascq"):
            v = result.get(k)
            if isinstance(v, str):
                iv = _to_int(v)
                if iv is not None:
                    result[f"{k}_int"] = iv
        return result
