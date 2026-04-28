from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    """All custom parsers must extend this class."""

    # Lower runs first. Specific parsers should set ~10, generic ~90,
    # the default catch-all = 999. Override at the class level.
    priority: int = 50

    @property
    @abstractmethod
    def parser_id(self) -> str:
        """Unique identifier for this parser, e.g. 'default', 'ufs_qual'."""
        ...

    @abstractmethod
    def can_parse(self, line: str, filename: str) -> bool:
        """Return True if this parser can handle the given line/filename."""
        ...

    @abstractmethod
    def parse(self, line: str, filename: str) -> dict[str, Any]:
        """
        Parse a single log line into a dict of extracted fields.
        Keys and values can be of any type (nested dicts, lists, ints, floats).
        This will be serialized to JSON and stored in ClickHouse.
        Return empty dict if nothing extractable.
        """
        ...
