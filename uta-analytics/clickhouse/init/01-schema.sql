-- UTA Log Analytics — interlude-only pivot schema.
-- Master test_sessions + child tables: log_events (raw lines outside any block),
-- interlude_snapshots (one row per >>>BEGIN..>>>END TL_interlude),
-- interlude_metrics (long-form sidecar — one row per scalar variable parsed
-- from the block, so any of ~300 FW vars can be plotted without JSONExtract).

CREATE DATABASE IF NOT EXISTS uta;

-- ==============================================================
-- Master: one row per log file (i.e. per test session).
-- ==============================================================
DROP TABLE IF EXISTS uta.test_sessions;
CREATE TABLE uta.test_sessions
(
    log_filename       String,
    server_ip          String,
    slot_id            String,                       -- R7S3-09
    rack               UInt8 DEFAULT 0,
    shelf              UInt8 DEFAULT 0,
    slot               UInt8 DEFAULT 0,
    started_at         Nullable(DateTime64(3)),      -- from filename timestamp
    last_seen_at       DateTime64(3) DEFAULT now64(3),
    status             Enum8('RUNNING'=0,'PASSED'=1,'FAILED'=2,'COMPLETED'=4,'UNKNOWN'=3) DEFAULT 'RUNNING',

    -- denormalised filename metadata (every part stored — only some shown on tile)
    execution_type     LowCardinality(String) DEFAULT '',   -- RESERVATION
    project            LowCardinality(String) DEFAULT '',   -- AA2
    controller         LowCardinality(String) DEFAULT '',   -- SIRIUS  (was: platform)
    interface          LowCardinality(String) DEFAULT '',   -- UFS_3_1
    fw_arch            LowCardinality(String) DEFAULT '',   -- V8
    nand_type          LowCardinality(String) DEFAULT '',   -- TLC
    nand_density       String DEFAULT '',                   -- 512Gb
    manufacturer       LowCardinality(String) DEFAULT '',   -- GEN1
    package_density    String DEFAULT '',                   -- 256GB
    patch_version      LowCardinality(String) DEFAULT '',   -- P09  (was: production_step)
    release_candidate  String DEFAULT '',                   -- RC00
    firmware_version   String DEFAULT '',                   -- FW00
    engineers          Array(String) DEFAULT [],            -- [Sharath, Aditi]
    test_purpose       LowCardinality(String) DEFAULT '',   -- Qual
    storage_type       LowCardinality(String) DEFAULT '',   -- UFS

    snapshot_count     UInt32 DEFAULT 0,
    last_snapshot_at   Nullable(DateTime64(3))
)
ENGINE = ReplacingMergeTree(last_seen_at)
ORDER BY (server_ip, log_filename)
SETTINGS index_granularity = 8192;

-- ==============================================================
-- Child: raw log lines that did NOT land inside a recognised block.
-- Kept as raw text only; per-line parsing is gone.
-- ==============================================================
DROP TABLE IF EXISTS uta.log_events;
CREATE TABLE uta.log_events
(
    server_ip      String,
    log_filename   String,
    slot_id        String,
    line_number    UInt64,
    raw_line       String,
    log_timestamp  Nullable(DateTime64(3)),    -- session.started_at + line elapsed prefix, when derivable
    ingested_at    DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ingested_at)
ORDER BY (server_ip, log_filename, line_number)
TTL ingested_at + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;

-- ==============================================================
-- Child: one row per >>>BEGIN..>>>END TL_interlude block.
-- Headline metrics promoted to typed columns; everything else
-- (nested groups, arrays) lives in the JSON variables blob.
-- ==============================================================
DROP TABLE IF EXISTS uta.interlude_snapshots;
CREATE TABLE uta.interlude_snapshots
(
    snapshot_id        UUID DEFAULT generateUUIDv4(),
    log_filename       String,
    server_ip          String,
    slot_id            String,
    rack               UInt8 DEFAULT 0,
    shelf              UInt8 DEFAULT 0,
    slot               UInt8 DEFAULT 0,

    block_index        UInt32 DEFAULT 0,                  -- 0,1,2 … per file
    block_started_at   DateTime64(3),                      -- wall clock from BEGIN marker
    block_ended_at     Nullable(DateTime64(3)),
    block_duration_s   Nullable(Float64),
    block_status       LowCardinality(String) DEFAULT '',  -- PASSED/FAILED/UNKNOWN

    -- Promoted typed metrics (the 'Definite' tier — graphed directly).
    wai                    Nullable(Float64),
    waf                    Nullable(Float64),
    ec_slc_max             Nullable(UInt32),
    ec_slc_min             Nullable(UInt32),
    ec_slc_avg             Nullable(UInt32),
    ec_mlc_max             Nullable(UInt32),
    ec_mlc_min             Nullable(UInt32),
    ec_mlc_avg             Nullable(UInt32),
    init_bb                Nullable(UInt32),
    rt_bb                  Nullable(UInt32),
    reserved_bb            Nullable(UInt32),
    free_block_cnt_xlc     Nullable(UInt32),
    free_block_cnt_slc     Nullable(UInt32),
    ftl_open_count         Nullable(UInt64),
    read_reclaim_count     Nullable(UInt32),
    total_nand_write_bytes Nullable(UInt64),
    total_nand_erase_bytes Nullable(UInt64),
    temp_case              Nullable(Int32),
    temp_thermal_value     Nullable(Int32),
    temp_nanddts           Nullable(Int32),
    latency_max_us         Nullable(UInt64),
    latency_avg_us         Nullable(UInt64),
    latency_min_us         Nullable(UInt64),

    -- Promoted typed metrics (the 'Probable' tier — also queried often).
    io_total                  Nullable(UInt64),
    read_io                   Nullable(UInt64),
    write_io                  Nullable(UInt64),
    read_io_kb                Nullable(UInt64),
    write_io_kb               Nullable(UInt64),
    reset_count               Nullable(UInt32),
    por_count                 Nullable(UInt32),
    pmc_count                 Nullable(UInt32),
    power_lvdf_event_count    Nullable(UInt32),
    phy_gear                  Nullable(UInt8),
    phy_lanes                 Nullable(UInt8),
    ssr_received_pon_count    Nullable(UInt32),
    ssr_received_spo_count    Nullable(UInt32),
    ssr_remain_reserved_block Nullable(UInt32),

    -- Everything else as JSON (nested groups, arrays, anything we didn't promote).
    variables          String DEFAULT '{}',
    ingested_at        DateTime64(3) DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(block_started_at)
ORDER BY (slot_id, log_filename, block_started_at, block_index)
TTL block_started_at + INTERVAL 60 DAY
SETTINGS index_granularity = 8192;

-- ==============================================================
-- Child: long-form sidecar — every scalar variable parsed from the
-- interlude block, one row per (snapshot, key). Lets Grafana plot
-- any of ~300 FW vars without JSONExtract.
-- ==============================================================
DROP TABLE IF EXISTS uta.interlude_metrics;
CREATE TABLE uta.interlude_metrics
(
    snapshot_id      UUID,
    log_filename     String,
    server_ip        String,
    slot_id          String,
    block_started_at DateTime64(3),
    block_index      UInt32 DEFAULT 0,
    section          LowCardinality(String) DEFAULT '',  -- e.g. "smart_report", "health_descriptor"
    key              String,                              -- e.g. "ssr.ReceivedPonCount"
    value_num        Nullable(Float64),                   -- pre-decoded (hex→int, suffix stripped)
    value_str        String DEFAULT '',                   -- original raw token (always set)
    unit             LowCardinality(String) DEFAULT ''    -- "MB", "us", "KB", "" when none
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(block_started_at)
ORDER BY (slot_id, key, block_started_at)
TTL block_started_at + INTERVAL 60 DAY
SETTINGS index_granularity = 8192;

-- ==============================================================
-- Forensic sink for parser failures. Unchanged.
-- ==============================================================
DROP TABLE IF EXISTS uta.parse_errors;
CREATE TABLE uta.parse_errors
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
