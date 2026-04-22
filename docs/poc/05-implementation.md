# POC — Implementation Guide

Build order: ClickHouse → Kafka → Vector → Parser → Grafana.
Each section is self-contained. Implement top-to-bottom.

---

## 1. ClickHouse Schema

File: `clickhouse/init/01-schema.sql`

```sql
CREATE DATABASE IF NOT EXISTS uta;

-- Parsed log events
CREATE TABLE IF NOT EXISTS uta.log_events
(
    event_id       UUID DEFAULT generateUUIDv4(),
    server_ip      String,
    slot_id        String,                          -- e.g. "R7S4-12"
    log_filename   String,
    line_number    UInt64,
    raw_line       String,
    parsed         Map(String, String),             -- flexible KV from parser
    severity       Enum8('UNKNOWN'=0, 'DEBUG'=1, 'INFO'=2, 'WARN'=3, 'ERROR'=4, 'FATAL'=5),
    log_timestamp  Nullable(DateTime64(3)),          -- timestamp from log line (if parseable)
    ingested_at    DateTime64(3) DEFAULT now64(3),
    -- Filename metadata (denormalized for query speed)
    platform       LowCardinality(String) DEFAULT '',
    firmware_version LowCardinality(String) DEFAULT '',
    execution_type LowCardinality(String) DEFAULT '',
    project        LowCardinality(String) DEFAULT ''
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ingested_at)
ORDER BY (server_ip, slot_id, log_filename, line_number)
TTL ingested_at + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;

-- Test session metadata (one row per log file)
CREATE TABLE IF NOT EXISTS uta.test_sessions
(
    log_filename      String,
    server_ip         String,
    slot_id           String,
    rack              UInt8 DEFAULT 0,
    shelf             UInt8 DEFAULT 0,
    slot              UInt8 DEFAULT 0,
    started_at        DateTime64(3),
    execution_type    LowCardinality(String),       -- EXEC, RETEST, DEBUG, SMOKE
    project           LowCardinality(String),       -- AA2
    platform          LowCardinality(String),       -- SIRIUS
    interface         LowCardinality(String),       -- UFS_3_1
    fw_arch           LowCardinality(String),       -- V8
    nand_type         LowCardinality(String),       -- TLC
    nand_density      String,                       -- 1Tb
    manufacturer      LowCardinality(String),       -- SAMSUNG
    package_density   String,                       -- 512GB
    production_step   LowCardinality(String),       -- P00
    release_candidate String,                       -- RC16
    firmware_version  String,                       -- FW04
    engineers         Array(String),
    test_purpose      LowCardinality(String),       -- Qual_UFS
    storage_type      LowCardinality(String),       -- UFS
    first_seen_at     DateTime64(3) DEFAULT now64(3),
    last_seen_at      DateTime64(3) DEFAULT now64(3),
    total_lines       UInt64 DEFAULT 0,
    status            Enum8('RUNNING'=0, 'PASSED'=1, 'FAILED'=2, 'UNKNOWN'=3) DEFAULT 'RUNNING'
)
ENGINE = ReplacingMergeTree(last_seen_at)
ORDER BY (server_ip, log_filename)
SETTINGS index_granularity = 8192;
```

### Why ReplacingMergeTree for test_sessions
The parser UPSERTs session rows as new lines arrive (incrementing `total_lines`, updating `last_seen_at`). `ReplacingMergeTree` keeps only the latest version per `(server_ip, log_filename)`.

---

## 2. Kafka Setup

Single broker, KRaft mode (no Zookeeper).

Topic creation script: `kafka/create-topics.sh`
```bash
#!/bin/bash
# Wait for Kafka to be ready
sleep 10
kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic raw-logs \
  --partitions 1 \
  --replication-factor 1 \
  --config retention.ms=86400000  # 24h
echo "Topic 'raw-logs' created."
```

---

## 3. Vector Configuration

File: `vector/vector.toml` — runs on UTA server (Linux, bare metal).

```toml
# ---- DATA DIRECTORY ----
data_dir = "/var/lib/vector"

# ---- SOURCE: Tail log files ----
[sources.uta_logs]
type = "file"
include = ["/uta/UTA_FULL_Logs/*.log"]
read_from = "end"                    # Only new lines (set to "beginning" for backfill)
fingerprint.strategy = "device_and_inode"
max_line_bytes = 102400              # 100KB max per line

# ---- TRANSFORM: Enrich with metadata ----
[transforms.enrich]
type = "remap"
inputs = ["uta_logs"]
source = '''
  .server_ip = get_env_var!("VECTOR_SERVER_IP")
  .log_filename = replace(strip_ansi_escape_codes(.file), "/uta/UTA_FULL_Logs/", "")
  .line = .message
  del(.message)
  del(.source_type)
  .line_number = to_int(.offset) ?? 0
'''

# ---- SINK: Kafka ----
[sinks.kafka_out]
type = "kafka"
inputs = ["enrich"]
bootstrap_servers = "${KAFKA_BOOTSTRAP_SERVERS}"   # e.g. "192.168.1.100:9092"
topic = "raw-logs"
encoding.codec = "json"
key_field = "log_filename"
compression = "lz4"
batch.max_bytes = 1048576            # 1MB batches
batch.timeout_secs = 1
```

### Install Vector on UTA Server
```bash
# vector/install.sh
curl --proto '=https' --tlsv1.2 -sSfL https://sh.vector.dev | bash
# Copy config
sudo cp vector.toml /etc/vector/vector.toml
# Set environment
echo 'VECTOR_SERVER_IP=192.168.1.10' | sudo tee /etc/default/vector
echo 'KAFKA_BOOTSTRAP_SERVERS=192.168.1.100:9092' | sudo tee -a /etc/default/vector
# Enable service
sudo systemctl enable --now vector
```

---

## 4. Parser Service

### 4a. Base Parser Interface

File: `parser/src/parsers/base.py`
```python
from abc import ABC, abstractmethod
from typing import Optional


class BaseParser(ABC):
    """All custom parsers must extend this class."""

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
    def parse(self, line: str, filename: str) -> dict[str, str]:
        """
        Parse a single log line into a flat dict of extracted fields.
        Keys and values must be strings (stored in ClickHouse Map(String, String)).
        Return empty dict if nothing extractable.
        """
        ...

    def detect_severity(self, line: str) -> str:
        """Optional: override to customize severity detection."""
        upper = line.upper()
        for level in ("FATAL", "ERROR", "WARN", "INFO", "DEBUG"):
            if level in upper:
                return level
        return "UNKNOWN"
```

### 4b. Default Parser

File: `parser/src/parsers/default.py`
```python
import re
from .base import BaseParser

# Common patterns in UTA logs
TIMESTAMP_RE = re.compile(r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
KV_RE = re.compile(r"(\w+)\s*[=:]\s*([^\s,;]+)")
TEST_CASE_RE = re.compile(r"(TC_\d+|Test_\d+|test_\d+)")
PASS_FAIL_RE = re.compile(r"\b(PASS|FAIL|PASSED|FAILED|ERROR|ABORT)\b", re.I)


class DefaultParser(BaseParser):
    parser_id = "default"

    def can_parse(self, line: str, filename: str) -> bool:
        return True  # Fallback parser, always matches

    def parse(self, line: str, filename: str) -> dict[str, str]:
        result = {}

        ts_match = TIMESTAMP_RE.search(line)
        if ts_match:
            result["log_time"] = ts_match.group(1)

        for k, v in KV_RE.findall(line):
            result[k.lower()] = v

        tc_match = TEST_CASE_RE.search(line)
        if tc_match:
            result["test_case"] = tc_match.group(1)

        pf_match = PASS_FAIL_RE.search(line)
        if pf_match:
            result["result"] = pf_match.group(1).upper()

        return result
```

### 4c. Parser Registry

File: `parser/src/parsers/__init__.py`
```python
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

    # Sort: specific parsers first, 'default' last
    _registry.sort(key=lambda p: (p.parser_id == "default", p.parser_id))


def get_parser(line: str, filename: str) -> BaseParser:
    """Return the first parser that can handle this line."""
    if not _registry:
        _discover_parsers()
    for parser in _registry:
        if parser.can_parse(line, filename):
            return parser
    raise RuntimeError("No parser found (default parser should always match)")
```

### 4d. Filename Parser

File: `parser/src/filename_parser.py`
```python
import re
from datetime import datetime

# Pattern matching the log naming convention from docs/log-naming.md
FILENAME_RE = re.compile(
    r"^(?P<slot_id>R\d+S\d+-\d+)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})_"
    r"(?P<exec_type>EXEC|RETEST|DEBUG|SMOKE)_"
    r"(?P<project>\w+?)_"
    r"(?P<platform>[A-Z]+)_"
    r"(?P<interface>UFS_\d+_\d+|eMMC_\d+_\d+)_"
    r"(?P<fw_arch>V\d+)_"
    r"(?P<nand_type>\w+?)_"
    r"(?P<nand_density>\d+\w+?)_"
    r"(?P<manufacturer>\w+?)_"
    r"(?P<package_density>\d+\w+?)_"
    r"(?P<prod_step>P\d+)_"
    r"(?P<release_candidate>RC\d+)_"
    r"(?P<firmware>FW\d+)_"
    r"(?P<rack>Rack\d+)_"
    r"(?P<engineers>.+?)_"
    r"(?P<test_purpose>\w+?)_"
    r"(?P<storage_type>\w+)"
    r"(?:\.log)?$"
)


def parse_filename(filename: str) -> dict:
    """
    Parse log filename into structured metadata.
    Returns dict with keys matching ClickHouse test_sessions columns.
    Returns partial dict if regex doesn't fully match (graceful degradation).
    """
    result = {"log_filename": filename}

    m = FILENAME_RE.match(filename)
    if not m:
        # Graceful fallback: extract what we can
        parts = filename.replace(".log", "").split("_")
        if parts:
            result["slot_id"] = parts[0] if parts[0].startswith("R") else ""
        return result

    d = m.groupdict()
    result.update({
        "slot_id": d["slot_id"],
        "started_at": datetime.strptime(f"{d['date']}_{d['time']}", "%Y%m%d_%H%M%S"),
        "execution_type": d["exec_type"],
        "project": d["project"],
        "platform": d["platform"],
        "interface": d["interface"],
        "fw_arch": d["fw_arch"],
        "nand_type": d["nand_type"],
        "nand_density": d["nand_density"],
        "manufacturer": d["manufacturer"],
        "package_density": d["package_density"],
        "production_step": d["prod_step"],
        "release_candidate": d["release_candidate"],
        "firmware_version": d["firmware"],
        "engineers": [e for e in d["engineers"].split("_") if e],
        "test_purpose": d["test_purpose"],
        "storage_type": d["storage_type"],
    })

    # Parse rack/shelf/slot numbers
    slot_m = re.match(r"R(\d+)S(\d+)-(\d+)", d["slot_id"])
    if slot_m:
        result["rack"] = int(slot_m.group(1))
        result["shelf"] = int(slot_m.group(2))
        result["slot"] = int(slot_m.group(3))

    return result
```

### 4e. ClickHouse Writer

File: `parser/src/writer.py`
```python
import clickhouse_connect
from config import Settings


class ClickHouseWriter:
    def __init__(self, settings: Settings):
        self.client = clickhouse_connect.get_client(
            host=settings.ch_host,
            port=settings.ch_port,
            database=settings.ch_database,
        )

    def write_events(self, rows: list[dict]) -> None:
        """Batch insert parsed log events."""
        if not rows:
            return
        columns = [
            "server_ip", "slot_id", "log_filename", "line_number",
            "raw_line", "parsed", "severity", "log_timestamp",
            "platform", "firmware_version", "execution_type", "project",
        ]
        data = [[row.get(c) for c in columns] for row in rows]
        self.client.insert("log_events", data, column_names=columns)

    def upsert_session(self, session: dict) -> None:
        """Insert/update test session metadata."""
        columns = list(session.keys())
        data = [list(session.values())]
        self.client.insert("test_sessions", data, column_names=columns)
```

### 4f. Consumer Loop

File: `parser/src/consumer.py`
```python
import json
import signal
import structlog
from confluent_kafka import Consumer, KafkaError
from parsers import get_parser
from filename_parser import parse_filename
from writer import ClickHouseWriter
from config import Settings

log = structlog.get_logger()


class LogConsumer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.running = True
        self.writer = ClickHouseWriter(settings)
        self.consumer = Consumer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": "uta-parser",
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
            "max.poll.interval.ms": 300000,
        })
        self.consumer.subscribe([settings.kafka_topic])
        self._session_cache: dict[str, dict] = {}
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, *_):
        self.running = False

    def run(self):
        log.info("consumer_started", topic=self.settings.kafka_topic)
        batch: list[dict] = []
        while self.running:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None:
                if batch:
                    self._flush(batch)
                    batch = []
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("kafka_error", error=str(msg.error()))
                continue

            try:
                value = json.loads(msg.value().decode("utf-8"))
                row = self._process(value)
                batch.append(row)
            except Exception:
                log.exception("parse_error", raw=msg.value())

            if len(batch) >= self.settings.batch_size:
                self._flush(batch)
                batch = []

        # Final flush
        if batch:
            self._flush(batch)
        self.consumer.close()
        log.info("consumer_stopped")

    def _process(self, msg: dict) -> dict:
        filename = msg.get("log_filename", "")
        line = msg.get("line", "")
        server_ip = msg.get("server_ip", "")

        # Parse filename metadata (cached per filename)
        if filename not in self._session_cache:
            meta = parse_filename(filename)
            meta["server_ip"] = server_ip
            self._session_cache[filename] = meta
            self.writer.upsert_session(meta)

        meta = self._session_cache[filename]

        # Select parser and parse line
        parser = get_parser(line, filename)
        parsed = parser.parse(line, filename)
        severity = parser.detect_severity(line)

        return {
            "server_ip": server_ip,
            "slot_id": meta.get("slot_id", ""),
            "log_filename": filename,
            "line_number": msg.get("line_number", 0),
            "raw_line": line,
            "parsed": parsed,
            "severity": severity,
            "log_timestamp": parsed.get("log_time"),
            "platform": meta.get("platform", ""),
            "firmware_version": meta.get("firmware_version", ""),
            "execution_type": meta.get("execution_type", ""),
            "project": meta.get("project", ""),
        }

    def _flush(self, batch: list[dict]):
        try:
            self.writer.write_events(batch)
            self.consumer.commit()
            log.info("batch_flushed", count=len(batch))
        except Exception:
            log.exception("flush_error", count=len(batch))
```

### 4g. Entry Point

File: `parser/src/main.py`
```python
from consumer import LogConsumer
from config import Settings


def main():
    settings = Settings()
    consumer = LogConsumer(settings)
    consumer.run()


if __name__ == "__main__":
    main()
```

### 4h. Configuration

File: `parser/src/config.py`
```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic: str = "raw-logs"
    ch_host: str = "clickhouse"
    ch_port: int = 8123
    ch_database: str = "uta"
    batch_size: int = 500
    log_level: str = "INFO"

    class Config:
        env_prefix = "UTA_"
```

---

## 5. Grafana Provisioning

### 5a. Datasource

File: `grafana/provisioning/datasources/clickhouse.yml`

> ⚠️ **Plugin v4+ Breaking Change**: Do NOT use the top-level `url:` field. The grafana-clickhouse-datasource v4+ plugin parses `url` separately from jsonData and produces a `http://http://` double-prefix error. Use `server` + `port` inside `jsonData` instead.

```yaml
apiVersion: 1
datasources:
  - name: ClickHouse
    type: grafana-clickhouse-datasource
    access: proxy
    isDefault: true
    editable: true
    jsonData:
      server: clickhouse        # Docker service name on uta-net
      port: 8123
      protocol: http            # 'http' (port 8123) or 'native' (port 9000)
      username: default
      defaultDatabase: uta
    secureJsonData:
      password: password        # Must match CLICKHOUSE_PASSWORD in docker-compose.yml
```

> **Note**: The ClickHouse Grafana plugin must be installed. Add `GF_INSTALL_PLUGINS=grafana-clickhouse-datasource` to Grafana env in Docker Compose. Allow **2–5 minutes** on first boot for the plugin to download and install before testing the datasource connection.

### 5b. Dashboard Provider

File: `grafana/provisioning/dashboards/dashboard.yml`
```yaml
apiVersion: 1
providers:
  - name: UTA
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: false
```

### 5c. Dashboard Panels (key queries)

The `test-monitor.json` dashboard should include these panels:

**Panel 1: Live Log Event Rate** (Time series)
```sql
SELECT
    toStartOfMinute(ingested_at) AS time,
    count() AS events_per_minute
FROM uta.log_events
WHERE ingested_at >= now() - INTERVAL 1 HOUR
GROUP BY time
ORDER BY time
```

**Panel 2: Events by Severity** (Pie chart)
```sql
SELECT severity, count() AS cnt
FROM uta.log_events
WHERE ingested_at >= now() - INTERVAL 1 HOUR
GROUP BY severity
ORDER BY cnt DESC
```

**Panel 3: Active Test Sessions** (Table)
```sql
SELECT
    slot_id, platform, firmware_version, execution_type,
    test_purpose, status, total_lines,
    dateDiff('minute', started_at, now()) AS running_minutes
FROM uta.test_sessions FINAL
WHERE status = 'RUNNING'
ORDER BY started_at DESC
```

**Panel 4: Error Lines** (Logs panel)
```sql
SELECT ingested_at AS time, raw_line, slot_id, log_filename
FROM uta.log_events
WHERE severity IN ('ERROR', 'FATAL')
  AND ingested_at >= now() - INTERVAL 1 HOUR
ORDER BY ingested_at DESC
LIMIT 100
```

---

## 6. Adding a New Parser

To add a custom parser (e.g., for a specific test suite):

1. Create `parser/src/parsers/ufs_qual.py`:
```python
from .base import BaseParser

class UfsQualParser(BaseParser):
    parser_id = "ufs_qual"

    def can_parse(self, line: str, filename: str) -> bool:
        return "Qual_UFS" in filename

    def parse(self, line: str, filename: str) -> dict[str, str]:
        result = {}
        # Custom extraction logic here
        if "IOPS" in line:
            # Example: "Sequential Read IOPS: 120000"
            parts = line.split(":")
            if len(parts) == 2:
                result["metric"] = parts[0].strip()
                result["value"] = parts[1].strip()
        return result
```

2. Restart the parser container: `docker compose restart parser`
3. The registry auto-discovers the new parser. Lines from `Qual_UFS` test files now use `UfsQualParser`.
