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
    parsed         String,                          -- JSON string for arbitrary data structures
    log_timestamp  Nullable(DateTime64(3)),          -- timestamp from log line (if parseable)
    ingested_at    DateTime64(3) DEFAULT now64(3),
    -- Filename metadata (denormalized for query speed)
    platform       LowCardinality(String) DEFAULT '',
    firmware_version LowCardinality(String) DEFAULT '',
    execution_type LowCardinality(String) DEFAULT '',
    project        LowCardinality(String) DEFAULT '',
    interface      LowCardinality(String) DEFAULT '',
    fw_arch        LowCardinality(String) DEFAULT '',
    nand_type      LowCardinality(String) DEFAULT '',
    nand_density   LowCardinality(String) DEFAULT '',
    manufacturer   LowCardinality(String) DEFAULT '',
    package_density LowCardinality(String) DEFAULT '',
    production_step LowCardinality(String) DEFAULT '',
    release_candidate LowCardinality(String) DEFAULT '',
    rack           UInt8 DEFAULT 0,
    test_purpose   LowCardinality(String) DEFAULT '',
    storage_type   LowCardinality(String) DEFAULT ''
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
    status            Enum8('RUNNING'=0, 'PASSED'=1, 'FAILED'=2, 'UNKNOWN'=3, 'COMPLETED'=4) DEFAULT 'RUNNING'
)
ENGINE = ReplacingMergeTree(last_seen_at)
ORDER BY (server_ip, log_filename)
SETTINGS index_granularity = 8192;

-- Parse-error sink: lines the consumer could not process land here for
-- forensic inspection instead of being silently dropped. 7-day TTL.
CREATE TABLE IF NOT EXISTS uta.parse_errors
(
    occurred_at    DateTime64(3) DEFAULT now64(3),
    raw_message    String,
    filename       String,
    error_type     LowCardinality(String),
    error_message  String
)
ENGINE = MergeTree()
ORDER BY occurred_at
TTL occurred_at + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;
