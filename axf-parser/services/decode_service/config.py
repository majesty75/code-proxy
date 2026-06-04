import os


class Config:
    NATS_URL        = os.environ.get("NATS_URL", "nats://nats:4222")
    NATS_STREAM     = os.environ.get("NATS_STREAM", "UTA_AXF")
    NATS_CONSUMER   = os.environ.get("NATS_CONSUMER", "AXF_DECODER")
    NATS_OBJ_BUCKET = os.environ.get("NATS_OBJ_BUCKET", "AXF_BINS")

    LAYOUTS_DIR     = os.environ.get("LAYOUTS_DIR", "/app/config/layouts")
    VARIABLES_YAML  = os.environ.get("VARIABLES_YAML", "/app/config/variables.yaml")

    # UTA SQLite, mounted read-only. If unset/missing, runtime facts come from
    # the event itself (demo mode) and are flagged when absent.
    UTA_SQLITE      = os.environ.get("UTA_SQLITE", "")

    CH_HOST = os.environ.get("CH_HOST", "clickhouse")
    CH_PORT = int(os.environ.get("CH_PORT", "8123"))
    CH_DB   = os.environ.get("CH_DB", "uta")
    CH_USER = os.environ.get("CH_USER", "default")
    CH_PASS = os.environ.get("CH_PASS", "")

    MAX_DEREF_DEPTH = int(os.environ.get("MAX_DEREF_DEPTH", "4"))
    FETCH_BATCH     = int(os.environ.get("FETCH_BATCH", "10"))
