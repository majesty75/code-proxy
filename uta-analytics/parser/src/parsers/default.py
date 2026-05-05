"""
No-op fallback line parser.

Per the interlude-only pivot, we no longer parse individual lines — every
line outside a recognised block lands in uta.log_events as raw text. This
parser exists so the line-parser registry has a guaranteed last-match
catch-all if anything calls it.
"""
from __future__ import annotations

from typing import Any

from .base import BaseParser


class DefaultParser(BaseParser):
    parser_id = "default"
    priority = 999

    def can_parse(self, line: str, filename: str) -> bool:
        return True

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        return {}
