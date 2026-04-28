import importlib
import pkgutil
from pathlib import Path
from .base import BaseParser

_registry: list[BaseParser] = []


def _discover_parsers():
    """Auto-discover all BaseParser subclasses in this package."""
    package_dir = Path(__file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(package_dir)]):
        if module_name == "base":
            continue
        importlib.import_module(f".{module_name}", package=__package__)

    for cls in BaseParser.__subclasses__():
        _registry.append(cls())

    # Sort by explicit priority (lower runs first), then by parser_id for
    # deterministic ordering within the same priority. The default parser
    # uses priority=999 so it always falls through last.
    _registry.sort(key=lambda p: (getattr(p, "priority", 50), p.parser_id))


def get_parser(line: str, filename: str) -> BaseParser:
    """Return the first parser that can handle this line."""
    if not _registry:
        _discover_parsers()
    for parser in _registry:
        if parser.can_parse(line, filename):
            return parser
    raise RuntimeError("No parser found (default parser should always match)")
