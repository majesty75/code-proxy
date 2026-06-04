import os
import socket


class Config:
    WATCH_DIR       = os.environ.get("WATCH_DIR", "/dropzone")
    # bank files land here as <slot>_<core>_<YYYYMMDD>_<HHMMSS>_<base08x>.bank
    # a per-group .done marker (or stable mtime) signals completeness.
    NATS_URL        = os.environ.get("NATS_URL", "nats://nats:4222")
    NATS_OBJ_BUCKET = os.environ.get("NATS_OBJ_BUCKET", "AXF_BINS")
    SERVER_IP       = os.environ.get("SERVER_IP", socket.gethostbyname(socket.gethostname()))
    POLL_SECONDS    = float(os.environ.get("POLL_SECONDS", "2"))
    STABLE_SECONDS  = float(os.environ.get("STABLE_SECONDS", "3"))   # group settle time
