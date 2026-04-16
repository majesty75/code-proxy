# SYSTEM — Parser Framework

## 1. Design Goals

| Goal | How Achieved |
|------|-------------|
| **Plug-and-play** | Drop a `.py` file into `parsers/` directory → auto-discovered |
| **No pipeline restart** | Flink job reload on redeploy; parser code is internal to the job |
| **Priority routing** | Parsers declare `can_parse()` → first match wins; `default` is always last |
| **Graceful degradation** | Unparseable lines stored as-is with `parser_id='default'` and `severity='UNKNOWN'` |
| **Testable** | Each parser is a plain Python class; unit-testable without Kafka/Flink |

## 2. Parser Interface

```python
# services/flink-job/src/parsers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParseResult:
    """Output from a parser for a single log line."""
    fields: dict[str, str]             # Extracted key-value pairs → goes to Map(String, String)
    severity: str = "UNKNOWN"          # DEBUG, INFO, WARN, ERROR, FATAL, UNKNOWN
    test_case: Optional[str] = None    # TC_001, Test_042, etc.
    test_result: Optional[str] = None  # PASS, FAIL, ERROR, ABORT, or None
    log_timestamp: Optional[str] = None  # Timestamp extracted from the line (ISO or HH:MM:SS)


class BaseParser(ABC):
    """
    All custom parsers MUST extend this class and implement all abstract methods.
    Place the file in services/flink-job/src/parsers/ directory.
    The parser is auto-discovered via __subclasses__().
    """

    @property
    @abstractmethod
    def parser_id(self) -> str:
        """Unique string identifier, e.g. 'ufs_qual', 'emmc_stress'."""
        ...

    @property
    def priority(self) -> int:
        """Lower = higher priority. Default parser should be 999."""
        return 100

    @abstractmethod
    def can_parse(self, line: str, filename: str) -> bool:
        """
        Return True if this parser should handle this line.
        Called for every line — keep this FAST (simple string checks, not regex).
        The filename is the full log filename (not path).
        """
        ...

    @abstractmethod
    def parse(self, line: str, filename: str) -> ParseResult:
        """
        Parse a single log line into structured fields.
        MUST NOT raise exceptions — return empty ParseResult on failure.
        MUST NOT do I/O (no file reads, no network calls).
        """
        ...
```

## 3. Parser Registry

```python
# services/flink-job/src/parsers/__init__.py

import importlib
import pkgutil
from pathlib import Path
from .base import BaseParser, ParseResult

_registry: list[BaseParser] = []
_initialized = False


def _discover():
    global _initialized
    if _initialized:
        return
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if name == "base":
            continue
        importlib.import_module(f".{name}", package=__package__)
    for cls in BaseParser.__subclasses__():
        _registry.append(cls())
    _registry.sort(key=lambda p: p.priority)
    _initialized = True


def get_parser(line: str, filename: str) -> BaseParser:
    """Return first parser whose can_parse() returns True."""
    _discover()
    for parser in _registry:
        if parser.can_parse(line, filename):
            return parser
    # Should never reach here if default parser exists
    return _registry[-1]


def list_parsers() -> list[str]:
    """Return list of registered parser IDs."""
    _discover()
    return [p.parser_id for p in _registry]
```

## 4. Router (Flink Integration)

```python
# services/flink-job/src/router.py

from parsers import get_parser
from parsers.base import ParseResult
from filename_parser import parse_filename


def process_message(msg: dict) -> dict:
    """
    Called by Flink FlatMap function for each Kafka message.
    Input: raw Kafka message dict.
    Output: dict ready for ClickHouse INSERT.
    """
    line = msg.get("line", "")
    filename = msg.get("log_filename", "")
    server_ip = msg.get("server_ip", "")

    # Parse filename metadata
    meta = parse_filename(filename)

    # Route to appropriate parser
    parser = get_parser(line, filename)
    result: ParseResult = parser.parse(line, filename)

    return {
        "server_ip": server_ip,
        "slot_id": meta.get("slot_id", ""),
        "log_filename": filename,
        "line_number": msg.get("line_number", 0),
        "raw_line": line,
        "parsed": result.fields,
        "parser_id": parser.parser_id,
        "severity": result.severity,
        "test_case": result.test_case,
        "test_result": result.test_result,
        "log_timestamp": result.log_timestamp,
        "ingested_at": None,  # Let ClickHouse default
        "platform": meta.get("platform", ""),
        "firmware_version": meta.get("firmware_version", ""),
        "execution_type": meta.get("execution_type", ""),
        "project": meta.get("project", ""),
        "interface_version": meta.get("interface", ""),
        "manufacturer": meta.get("manufacturer", ""),
    }
```

## 5. Example Parsers

### 5a. Default Parser (always matches, lowest priority)

```python
# services/flink-job/src/parsers/default.py

import re
from .base import BaseParser, ParseResult

TIMESTAMP_RE = re.compile(r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
KV_RE = re.compile(r"(\w+)\s*[=:]\s*([^\s,;]+)")
RESULT_RE = re.compile(r"\b(PASS(?:ED)?|FAIL(?:ED)?|ERROR|ABORT)\b", re.I)
TEST_RE = re.compile(r"\b(TC_\d+|Test_\d+|test_\d+)\b")


class DefaultParser(BaseParser):
    parser_id = "default"
    priority = 999  # Always last

    def can_parse(self, line: str, filename: str) -> bool:
        return True

    def parse(self, line: str, filename: str) -> ParseResult:
        fields = {}

        # Extract all key=value or key: value pairs
        for k, v in KV_RE.findall(line):
            fields[k.lower()] = v

        # Timestamp
        ts = TIMESTAMP_RE.search(line)
        log_ts = ts.group(1) if ts else None

        # Test case
        tc = TEST_RE.search(line)
        test_case = tc.group(1) if tc else None

        # Result
        res = RESULT_RE.search(line)
        test_result = res.group(1).upper().replace("PASSED", "PASS").replace("FAILED", "FAIL") if res else None

        # Severity
        upper = line.upper()
        severity = "UNKNOWN"
        for level in ("FATAL", "ERROR", "WARN", "INFO", "DEBUG"):
            if level in upper:
                severity = level
                break

        return ParseResult(
            fields=fields,
            severity=severity,
            test_case=test_case,
            test_result=test_result,
            log_timestamp=log_ts,
        )
```

### 5b. UFS Qualification Parser (example domain-specific parser)

```python
# services/flink-job/src/parsers/ufs_qual.py

import re
from .base import BaseParser, ParseResult

IOPS_RE = re.compile(r"IOPS[=:\s]+(\d+)", re.I)
THROUGHPUT_RE = re.compile(r"(?:throughput|BW)[=:\s]+([\d.]+)\s*(MB/s|GB/s|KB/s)", re.I)
LATENCY_RE = re.compile(r"latency[_]?(?:us|ms)?[=:\s]+([\d.]+)", re.I)
TEMP_RE = re.compile(r"(?:temp|temperature)[=:\s]+([\d.]+)\s*[°]?C?", re.I)
POWER_RE = re.compile(r"power[=:\s]+([\d.]+)\s*(?:mW|W)", re.I)


class UfsQualParser(BaseParser):
    parser_id = "ufs_qual"
    priority = 10  # High priority

    def can_parse(self, line: str, filename: str) -> bool:
        return "Qual_UFS" in filename or "Qual_eMMC" in filename

    def parse(self, line: str, filename: str) -> ParseResult:
        fields = {}

        m = IOPS_RE.search(line)
        if m:
            fields["iops"] = m.group(1)

        m = THROUGHPUT_RE.search(line)
        if m:
            fields["throughput"] = m.group(1)
            fields["throughput_unit"] = m.group(2)

        m = LATENCY_RE.search(line)
        if m:
            fields["latency_us"] = m.group(1)

        m = TEMP_RE.search(line)
        if m:
            fields["temperature_c"] = m.group(1)

        m = POWER_RE.search(line)
        if m:
            fields["power_mw"] = m.group(1)

        # Severity detection
        upper = line.upper()
        severity = "UNKNOWN"
        for level in ("FATAL", "ERROR", "WARN", "INFO", "DEBUG"):
            if level in upper:
                severity = level
                break

        return ParseResult(fields=fields, severity=severity)
```

## 6. Adding a New Parser — Checklist

1. **Create** `services/flink-job/src/parsers/<name>.py`
2. **Extend** `BaseParser`, implement `parser_id`, `can_parse()`, `parse()`
3. **Set priority** (lower = checked earlier; default is 100)
4. **Write tests** in `services/flink-job/tests/test_<name>_parser.py`
5. **Rebuild** Flink job image: `docker compose build flink-job`
6. **Redeploy**: `docker compose up -d flink-job` (Flink restart picks up new parser)

No configuration files to edit. No registry to update. The `__init__.py` auto-discovers all `BaseParser` subclasses.
