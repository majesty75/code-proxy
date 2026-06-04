-- AXF SRAM-decode analytics. Separate tables from the interlude log pipeline.
-- Dimension `core` is new. Full nested decode archived per snapshot for ML;
-- curated scalars promoted to a long-form table for Grafana.

CREATE DATABASE IF NOT EXISTS uta;

-- Master: one row per (board, core, TR) run. Latest wins.
CREATE TABLE IF NOT EXISTS uta.axf_sessions
(
    trname            String,
    boardname         String,
    core              LowCardinality(String),
    product           LowCardinality(String),
    product_version   LowCardinality(String) DEFAULT '',
    fw_name           String DEFAULT '',
    fw_build_hash     String DEFAULT '',
    nand_type         LowCardinality(String) DEFAULT '',
    nand_density      String DEFAULT '',
    test_started_at   Nullable(DateTime64(3)),
    first_dump_at     Nullable(DateTime64(3)),
    last_dump_at      Nullable(DateTime64(3)),
    dump_count        UInt32 DEFAULT 0,
    last_seen_at      DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(last_seen_at)
ORDER BY (boardname, core, trname);

-- One row per dump. Holds the FULL nested decode (ZSTD) = ML source of truth.
CREATE TABLE IF NOT EXISTS uta.axf_snapshots
(
    snapshot_id      UUID DEFAULT generateUUIDv4(),
    trname           String,
    boardname        String,
    core             LowCardinality(String),
    product          LowCardinality(String),
    fw_build_hash    String,
    dump_timestamp   DateTime64(3),
    elapsed_s        Float64 DEFAULT 0,
    layout_key       String DEFAULT '',
    object_key       String DEFAULT '',
    decoded_json     String DEFAULT '{}' CODEC(ZSTD(3)),
    decode_status    Enum8('OK'=0,'PARTIAL'=1,'FAILED'=2) DEFAULT 'OK',
    decode_error_cnt UInt32 DEFAULT 0,
    ingested_at      DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(dump_timestamp)
ORDER BY (boardname, core, trname, elapsed_s)
TTL toDateTime(dump_timestamp) + INTERVAL 90 DAY;

-- Long-form sidecar: curated scalars for dashboards. New keys need NO migration.
CREATE TABLE IF NOT EXISTS uta.axf_metrics
(
    snapshot_id      UUID,
    trname           String,
    boardname        String,
    core             LowCardinality(String),
    product          LowCardinality(String),
    dump_timestamp   DateTime64(3),
    elapsed_s        Float64 DEFAULT 0,
    section          LowCardinality(String) DEFAULT '',
    key              String,
    value_num        Nullable(Float64),
    value_str        String DEFAULT '',
    unit             LowCardinality(String) DEFAULT '',
    ingested_at      DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(dump_timestamp)
ORDER BY (boardname, core, key, elapsed_s)
TTL toDateTime(dump_timestamp) + INTERVAL 90 DAY;

-- Forensic sink for mismatches / failures.
CREATE TABLE IF NOT EXISTS uta.axf_decode_errors
(
    occurred_at    DateTime64(3) DEFAULT now64(3),
    object_key     String,
    boardname      String,
    core           String,
    fw_build_hash  String,
    error_type     LowCardinality(String),   -- BAD_EVENT/ENRICH_ERROR/NO_LAYOUT/HASH_MISMATCH/DECODE_FAIL
    error_message  String
)
ENGINE = MergeTree()
ORDER BY occurred_at
TTL toDateTime(occurred_at) + INTERVAL 30 DAY;
