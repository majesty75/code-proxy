"""
Section separator banners:

  =================================
  *************************TL_SAMPLE_INFORMATION**************************
  ***************************************************
  ---------------------------------------------------
  -----------------------------------------------
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

PURE_BANNER_RE = re.compile(r"^[=\*\-]{5,}$")
LABELED_BANNER_RE = re.compile(r"^(?P<lead>[=\*\-]{2,})(?P<label>[A-Z_][A-Z0-9_]*)(?P<trail>[=\*\-]{2,})$")


class SectionBannerParser(BaseParser):
    parser_id = "section_banner"
    priority = 32

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        return bool(PURE_BANNER_RE.match(body) or LABELED_BANNER_RE.match(body))

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        if PURE_BANNER_RE.match(body):
            return {"event": "banner", "char": body[0], "width": len(body)}
        if (m := LABELED_BANNER_RE.match(body)):
            return {"event": "banner", "char": m.group("lead")[0], "label": m.group("label")}
        return {"event": "banner", "raw": body}
