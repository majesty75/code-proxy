# POC — Folder Structure

```
uta-analytics/
├── docker-compose.yml              # Orchestrates all services on WSL2
├── .env                             # Environment variables (IPs, ports, credentials)
├── .env.example                     # Template for .env
│
├── vector/
│   ├── vector.toml                  # Vector agent config (runs on UTA server, NOT in Docker)
│   └── install.sh                   # Script to install Vector on UTA server
│
├── kafka/
│   └── create-topics.sh             # Post-startup topic creation script
│
├── parser/
│   ├── Dockerfile                   # Python 3.12 slim image
│   ├── requirements.txt             # Python dependencies
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                  # Entry point: starts consumer loop
│   │   ├── config.py                # Configuration from env vars (pydantic-settings)
│   │   ├── consumer.py              # Kafka consumer: poll → parse → write
│   │   ├── writer.py                # ClickHouse batch writer
│   │   ├── filename_parser.py       # Extracts metadata from log filename
│   │   └── parsers/
│   │       ├── __init__.py          # Parser registry (auto-discovers parsers)
│   │       ├── base.py              # Abstract base parser class
│   │       └── default.py           # Default regex-based parser
│   └── tests/
│       ├── test_filename_parser.py
│       ├── test_default_parser.py
│       └── test_consumer.py
│
├── clickhouse/
│   └── init/
│       └── 01-schema.sql            # DDL: creates database + tables (mounted as init script)
│
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       │   └── clickhouse.yml       # Auto-provisions ClickHouse datasource
│       └── dashboards/
│           ├── dashboard.yml        # Dashboard provider config
│           └── test-monitor.json    # Pre-built dashboard JSON
│
├── scripts/
│   ├── start.sh                     # docker compose up + wait for healthy + create topics
│   ├── stop.sh                      # docker compose down
│   ├── seed-test-data.sh            # Generates fake log lines for testing
│   └── verify.sh                    # Checks all services are healthy
│
└── docs/                            # This documentation (symlink or copy)
```

## Key Files Explained

| File | What It Does | When It Changes |
|------|-------------|----------------|
| `docker-compose.yml` | Defines Kafka, Parser, ClickHouse, Grafana containers and networking | When adding services or changing ports |
| `vector/vector.toml` | Configures file tailing source + Kafka sink; runs on UTA server directly | When changing log paths or Kafka address |
| `parser/src/main.py` | Creates consumer, starts polling loop with graceful shutdown | Rarely |
| `parser/src/consumer.py` | Core loop: poll Kafka → call parser → batch write to CH | When changing batch size or error handling |
| `parser/src/parsers/base.py` | Abstract class defining parser interface (`parse(line) → dict`) | Only if interface changes |
| `parser/src/parsers/default.py` | Regex parser for common log patterns; extracts timestamps, KV pairs | When tuning parsing rules |
| `parser/src/filename_parser.py` | Parses log filename into structured metadata (slot, platform, FW, etc.) | When filename convention changes |
| `clickhouse/init/01-schema.sql` | `CREATE TABLE` statements for `log_events` and `test_sessions` | When schema changes |

## Notes
- **Vector runs on the UTA server**, not in Docker Compose. It's installed as a systemd service.
- **All other services** run in Docker Compose on the main server (WSL2).
- The `parser/src/parsers/` directory is the **extension point** — add new `.py` files here to handle different log formats.
