# SYSTEM — Data Model

## 1. ClickHouse Database Schema

### 1.1 Database

```sql
CREATE DATABASE IF NOT EXISTS uta ON CLUSTER '{cluster}';
```

### 1.2 Log Events (Hot Tier)

Primary table for parsed log lines. Partitioned by day, ordered for fast slot/session queries.

```sql
CREATE TABLE IF NOT EXISTS uta.log_events ON CLUSTER '{cluster}'
(
    -- Identity
    event_id          UUID DEFAULT generateUUIDv4(),
    server_ip         LowCardinality(String),
    slot_id           LowCardinality(String),         -- R7S4-12
    log_filename      String,

    -- Content
    line_number       UInt64,
    raw_line          String                           CODEC(LZ4),
    parsed            Map(String, String),             -- Flexible KV from parser
    parser_id         LowCardinality(String),          -- Which parser produced this

    -- Classification
    severity          Enum8('UNKNOWN'=0, 'DEBUG'=1, 'INFO'=2, 'WARN'=3, 'ERROR'=4, 'FATAL'=5),
    test_case         Nullable(String),                -- TC_001, Test_042 etc.
    test_result       Nullable(Enum8('NONE'=0, 'PASS'=1, 'FAIL'=2, 'ERROR'=3, 'ABORT'=4)),

    -- Timestamps
    log_timestamp     Nullable(DateTime64(3)),          -- From log line
    ingested_at       DateTime64(3) DEFAULT now64(3),   -- When inserted

    -- Denormalized metadata (from filename, for fast filtering)
    platform          LowCardinality(String) DEFAULT '',
    firmware_version  LowCardinality(String) DEFAULT '',
    execution_type    LowCardinality(String) DEFAULT '',
    project           LowCardinality(String) DEFAULT '',
    interface_version LowCardinality(String) DEFAULT '',
    manufacturer      LowCardinality(String) DEFAULT ''
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/log_events', '{replica}')
PARTITION BY toYYYYMMDD(ingested_at)
ORDER BY (server_ip, slot_id, log_filename, line_number)
TTL ingested_at + INTERVAL 30 DAY TO VOLUME 'cold',
    ingested_at + INTERVAL 730 DAY DELETE
SETTINGS
    index_granularity = 8192,
    storage_policy = 'hot_cold';
```

### 1.3 Test Sessions

One row per log file. Updated as lines arrive. `ReplacingMergeTree` keeps latest version.

```sql
CREATE TABLE IF NOT EXISTS uta.test_sessions ON CLUSTER '{cluster}'
(
    -- Identity
    log_filename      String,
    server_ip         LowCardinality(String),

    -- Slot info
    slot_id           LowCardinality(String),
    rack              UInt8 DEFAULT 0,
    shelf             UInt8 DEFAULT 0,
    slot              UInt8 DEFAULT 0,

    -- Test metadata (from filename)
    started_at        DateTime64(3),
    execution_type    LowCardinality(String),
    project           LowCardinality(String),
    platform          LowCardinality(String),
    interface_version LowCardinality(String),
    fw_arch           LowCardinality(String),
    nand_type         LowCardinality(String),
    nand_density      String,
    manufacturer      LowCardinality(String),
    package_density   String,
    production_step   LowCardinality(String),
    release_candidate String,
    firmware_version  String,
    engineers         Array(String),
    test_purpose      LowCardinality(String),
    storage_type      LowCardinality(String),

    -- Running stats (updated by parser)
    first_seen_at     DateTime64(3) DEFAULT now64(3),
    last_seen_at      DateTime64(3) DEFAULT now64(3),
    total_lines       UInt64 DEFAULT 0,
    error_count       UInt32 DEFAULT 0,
    warn_count        UInt32 DEFAULT 0,
    status            Enum8('RUNNING'=0, 'PASSED'=1, 'FAILED'=2, 'UNKNOWN'=3) DEFAULT 'RUNNING',

    -- Version for ReplacingMergeTree
    version           UInt64 DEFAULT toUnixTimestamp64Milli(now64(3))
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/test_sessions', '{replica}', version)
ORDER BY (server_ip, log_filename)
SETTINGS index_granularity = 8192;
```

### 1.4 Materialized Views

**Hourly event aggregates** — pre-computed for dashboard performance.

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS uta.mv_hourly_stats
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMMDD(hour)
ORDER BY (server_ip, slot_id, platform, firmware_version, severity, hour)
AS SELECT
    toStartOfHour(ingested_at) AS hour,
    server_ip,
    slot_id,
    platform,
    firmware_version,
    severity,
    count() AS event_count,
    uniqExact(log_filename) AS active_sessions
FROM uta.log_events
GROUP BY hour, server_ip, slot_id, platform, firmware_version, severity;
```

**Error density per session** — for anomaly detection.

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS uta.mv_session_error_rate
ENGINE = AggregatingMergeTree()
ORDER BY (server_ip, log_filename)
AS SELECT
    server_ip,
    log_filename,
    platform,
    firmware_version,
    countState() AS total_lines,
    countIfState(severity IN ('ERROR', 'FATAL')) AS error_lines
FROM uta.log_events
GROUP BY server_ip, log_filename, platform, firmware_version;
```

---

## 2. Kafka Message Schemas

### 2.1 Topic: `raw-logs`

JSON-encoded. One message per log line.

```json
{
  "server_ip": "192.168.1.10",
  "log_filename": "R7S4-12_20260414_163815_EXEC_AA2_SIRIUS_UFS_3_1_V8_TLC_1Tb_SAMSUNG_512GB_P00_RC16_FW04_Rack7_Sai_Revathi_Qual_UFS.log",
  "line": "16:38:20 [INFO] Test TC_001 started — sequential read 128K",
  "line_number": 42,
  "offset": 8192,
  "timestamp": "2026-04-14T16:38:20.000Z"
}
```

**Key**: `server_ip` (ensures all lines from one server go to the same partition for ordering).

### 2.2 Topic: `dead-letter`

Messages that failed parsing after 3 retries.

```json
{
  "original_message": { ... },
  "error": "ParserError: No regex match",
  "parser_id": "ufs_qual",
  "failed_at": "2026-04-14T16:38:25.000Z",
  "retry_count": 3
}
```

---

## 3. Data Dictionary

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `server_ip` | String | Vector env var | IP address of the UTA server |
| `slot_id` | String | Filename parse | Physical location: `R{rack}S{shelf}-{slot}` |
| `log_filename` | String | Vector file path | Full log filename without path |
| `line_number` | UInt64 | Vector offset | Byte offset in file (approximate line number) |
| `raw_line` | String | Vector message | Original log line text |
| `parsed` | Map(String, String) | Parser output | Flexible key-value pairs extracted by parser |
| `parser_id` | String | Parser registry | Which parser processed this line |
| `severity` | Enum8 | Parser detection | Log level: DEBUG, INFO, WARN, ERROR, FATAL, UNKNOWN |
| `test_case` | String | Parser extraction | Test case identifier if found (TC_001) |
| `test_result` | Enum8 | Parser extraction | PASS, FAIL, ERROR, ABORT, NONE |
| `log_timestamp` | DateTime64 | Parser extraction | Timestamp from within the log line |
| `ingested_at` | DateTime64 | ClickHouse | When the row was inserted |
| `platform` | String | Filename parse | Product platform (SIRIUS, etc.) |
| `firmware_version` | String | Filename parse | FW build (FW04, etc.) |
| `execution_type` | String | Filename parse | EXEC, RETEST, DEBUG, SMOKE |
| `project` | String | Filename parse | Test group/phase (AA2, etc.) |

---

## 4. Storage Policy (ClickHouse)

```xml
<!-- clickhouse config.xml addition -->
<storage_configuration>
    <disks>
        <hot>
            <path>/var/lib/clickhouse/hot/</path>
        </hot>
        <cold>
            <path>/var/lib/clickhouse/cold/</path>
        </cold>
    </disks>
    <policies>
        <hot_cold>
            <volumes>
                <hot>
                    <disk>hot</disk>
                </hot>
                <cold>
                    <disk>cold</disk>
                </cold>
            </volumes>
            <move_factor>0.1</move_factor>
        </hot_cold>
    </policies>
</storage_configuration>
```
