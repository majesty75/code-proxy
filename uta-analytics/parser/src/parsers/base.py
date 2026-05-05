"""
Parser base classes.

Two flavours:
  - BaseParser:        line-based (kept only for the no-op default fallback).
  - BaseBlockParser:   block-based — owns BEGIN/END markers, receives the
                       full buffered line list, returns a structured dict.

The interlude block parser is the only real BaseBlockParser today, but the
contract is intentionally generic so future blocks (TL_Profile, etc.) drop
into the same machinery without consumer-side changes.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    """Line-based parser. Lower priority runs first; default catch-all = 999."""

    priority: int = 50

    @property
    @abstractmethod
    def parser_id(self) -> str: ...

    @abstractmethod
    def can_parse(self, line: str, filename: str) -> bool: ...

    @abstractmethod
    def parse(self, line: str, filename: str) -> dict[str, Any]: ...


class BaseBlockParser(ABC):
    """
    Block-based parser.

    The consumer detects the BEGIN marker, buffers all subsequent lines for
    that file (server_ip, log_filename), and on END hands the full list of
    raw lines to ``parse``. Adding a new block type = subclass + new
    BEGIN/END regexes + target table; the consumer doesn't change.
    """

    block_id: str                  # e.g. "interlude"
    target_table: str              # e.g. "interlude_snapshots"
    begin_marker: re.Pattern       # matches the line that opens the block
    end_marker: re.Pattern         # matches the line that closes the block

    @abstractmethod
    def parse(
        self,
        lines: list[str],
        filename: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Parse a buffered block.

        ``lines`` includes both BEGIN and END marker lines. ``meta`` is the
        filename-derived session metadata (slot_id, started_at, …) — used
        e.g. to convert MMM-DD timestamps in the BEGIN marker into a full
        datetime by inferring the year from session.started_at.

        Return shape (consumer expects these keys):
          - "snapshot": dict that maps onto interlude_snapshots typed columns
                        + a "variables" sub-dict that becomes the JSON blob.
          - "metrics":  list[dict] for the long-form sidecar table.
                        Each: {section, key, value_num, value_str, unit}.
        """
        ...
