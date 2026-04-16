# SYSTEM — Folder Structure

The system is composed of **independent, separately deployable services**. Each service has its own Dockerfile, dependencies, and configuration.

```
uta-analytics/
│
├── docker-compose.yml                  # Dev/staging: all services
├── docker-compose.prod.yml             # Production overrides (resource limits, replicas)
├── .env.example
├── Makefile                            # Common commands: up, down, logs, build
│
├── services/
│   │
│   ├── vector-agent/                   # Runs on each UTA server (NOT in Docker)
│   │   ├── vector.toml                 # Main config
│   │   ├── vector.toml.j2             # Jinja2 template (for Ansible)
│   │   ├── install.sh                  # Install script for UTA servers
│   │   └── README.md
│   │
│   ├── flink-job/                      # Stream processing (Flink + parsers)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── job.py                  # Flink job definition (topology)
│   │   │   ├── kafka_source.py         # Kafka source configuration
│   │   │   ├── clickhouse_sink.py      # ClickHouse sink (batch writer)
│   │   │   ├── filename_parser.py      # Log filename → metadata
│   │   │   ├── router.py               # Routes lines to correct parser
│   │   │   └── parsers/
│   │   │       ├── __init__.py         # Auto-discovery registry
│   │   │       ├── base.py             # Abstract BaseParser
│   │   │       ├── default.py          # Fallback regex parser
│   │   │       ├── ufs_qual.py         # UFS qualification parser
│   │   │       └── ...                 # Add more parsers here
│   │   ├── tests/
│   │   │   ├── test_filename_parser.py
│   │   │   ├── test_default_parser.py
│   │   │   ├── test_router.py
│   │   │   └── fixtures/               # Sample log lines for testing
│   │   │       ├── sample_ufs_qual.txt
│   │   │       └── sample_generic.txt
│   │   └── README.md
│   │
│   ├── clickhouse/                     # Database schema and config
│   │   ├── init/
│   │   │   ├── 01-database.sql         # CREATE DATABASE
│   │   │   ├── 02-tables-hot.sql       # Hot tier tables
│   │   │   ├── 03-tables-cold.sql      # Cold tier tables
│   │   │   ├── 04-materialized-views.sql
│   │   │   └── 05-ttl-policies.sql     # TTL and storage tiering
│   │   ├── migrations/                 # Schema migrations (numbered)
│   │   │   └── ...
│   │   ├── config/
│   │   │   ├── config.xml              # ClickHouse server config
│   │   │   └── users.xml               # User/profile configuration
│   │   └── README.md
│   │
│   ├── grafana/                        # Real-time dashboards
│   │   ├── provisioning/
│   │   │   ├── datasources/
│   │   │   │   └── clickhouse.yml
│   │   │   └── dashboards/
│   │   │       ├── provider.yml
│   │   │       ├── live-test-monitor.json
│   │   │       ├── error-analysis.json
│   │   │       ├── server-overview.json
│   │   │       └── firmware-comparison.json
│   │   └── README.md
│   │
│   ├── superset/                       # BI / Historical analytics
│   │   ├── Dockerfile                  # Superset + ClickHouse driver
│   │   ├── superset_config.py          # Superset configuration
│   │   ├── datasets/                   # Pre-configured dataset definitions
│   │   └── README.md
│   │
│   └── mlflow/                         # AI/ML experiment tracking (Phase 2)
│       ├── Dockerfile
│       ├── mlflow-config.yml
│       └── README.md
│
├── infra/                              # Infrastructure as Code
│   ├── ansible/
│   │   ├── inventory.yml               # UTA servers + main server
│   │   ├── playbooks/
│   │   │   ├── deploy-vector.yml       # Install/update Vector on UTA servers
│   │   │   └── deploy-stack.yml        # Deploy Docker stack on main server
│   │   └── roles/
│   │       └── vector/
│   │           ├── tasks/main.yml
│   │           └── templates/vector.toml.j2
│   │
│   └── docker/                         # Docker-specific configs
│       ├── kafka/
│       │   └── server.properties       # Kafka overrides
│       └── flink/
│           └── flink-conf.yaml         # Flink cluster config
│
├── scripts/
│   ├── start.sh                        # Full stack startup
│   ├── stop.sh
│   ├── create-topics.sh                # Kafka topic creation
│   ├── seed-test-data.py               # Generate test data
│   ├── health-check.sh                 # Verify all services
│   └── benchmark.py                    # Throughput test
│
├── docs/                               # This documentation
│   ├── README.md
│   ├── poc/
│   ├── system/
│   ├── log-naming.md
│   └── ...
│
└── tests/
    ├── integration/
    │   ├── test_end_to_end.py          # Full pipeline: Vector → Grafana
    │   ├── test_kafka_delivery.py
    │   └── test_clickhouse_queries.py
    └── load/
        └── generate_load.py            # Simulate 150K lines/sec
```

## Service Boundaries

| Service | Language | Deployable Unit | Depends On |
|---------|----------|-----------------|------------|
| vector-agent | Rust (binary) | systemd service on each UTA server | Kafka |
| flink-job | Python | Docker container (JobManager + TaskManagers) | Kafka, ClickHouse |
| clickhouse | C++ (binary) | Docker container (clustered) | Disk volumes |
| grafana | Go (binary) | Docker container | ClickHouse |
| superset | Python | Docker container | ClickHouse |
| mlflow | Python | Docker container | ClickHouse / object storage |

## Key Extension Points
- **New parser**: Add `.py` file to `services/flink-job/src/parsers/` → rebuild Flink job image.
- **New dashboard**: Add `.json` file to `services/grafana/provisioning/dashboards/`.
- **New UTA server**: Add to `infra/ansible/inventory.yml` → run playbook.
- **Schema change**: Add migration in `services/clickhouse/migrations/`.
