"""
Parser registry.

Auto-discovers BaseParser and BaseBlockParser subclasses. Block parsers go
through ``find_block_parser_for_line`` (matched against BEGIN markers); line
parsers fall through ``get_line_parser`` ordered by priority.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Optional

from .base import BaseBlockParser, BaseParser


_line_registry: list[BaseParser] = []
_block_registry: list[BaseBlockParser] = []


def _discover() -> None:
    package_dir = Path(__file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(package_dir)]):
        if module_name == "base":
            continue
        importlib.import_module(f".{module_name}", package=__package__)

    for cls in BaseParser.__subclasses__():
        _line_registry.append(cls())
    for cls in BaseBlockParser.__subclasses__():
        _block_registry.append(cls())

    _line_registry.sort(key=lambda p: (getattr(p, "priority", 50), p.parser_id))


def get_line_parser(line: str, filename: str) -> BaseParser:
    """Return the first line parser that can handle this line."""
    if not _line_registry:
        _discover()
    for parser in _line_registry:
        if parser.can_parse(line, filename):
            return parser
    raise RuntimeError("No line parser found (default parser should always match)")


def find_block_parser_for_line(line: str) -> Optional[BaseBlockParser]:
    """If this line opens a known block, return its parser; else None."""
    if not _block_registry:
        _discover()
    for bp in _block_registry:
        if bp.begin_marker.search(line):
            return bp
    return None


def block_parsers() -> list[BaseBlockParser]:
    """All registered block parsers (for END-marker matching at runtime)."""
    if not _block_registry:
        _discover()
    return list(_block_registry)
