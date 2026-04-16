# POC — Tech Stack

## Core Components

| Component | Technology | Docker Image | License | Role |
|-----------|-----------|-------------|---------|------|
| Log Collector | Vector | `timberio/vector:latest-alpine` | MPL-2.0 | Tails log files on UTA server, publishes to Kafka |
| Message Broker | Apache Kafka (KRaft) | `apache/kafka:latest` | Apache-2.0 | Decouples ingestion from processing; durable buffer |
| Stream Parser | Python 3.12 | Custom `Dockerfile` | — | Consumes Kafka, parses logs, writes to ClickHouse |
| Analytical DB | ClickHouse | `clickhouse/clickhouse-server:latest` | Apache-2.0 | Columnar storage, fast aggregation queries |
| Visualization | Grafana OSS | `grafana/grafana-oss:latest` | AGPL-3.0 | Real-time dashboards |

## Python Dependencies (Parser Service)

| Package | Version | Purpose |
|---------|---------|---------|
| `confluent-kafka` | `>=2.6` | High-performance Kafka consumer (librdkafka-based) |
| `clickhouse-connect` | `>=0.8` | Official ClickHouse Python client (HTTP protocol) |
| `pydantic` | `>=2.0` | Message validation and structured parsing output |
| `structlog` | `>=24.0` | Structured logging for the parser service itself |

## Why These Choices

| Decision | Rationale |
|----------|-----------|
| **Vector over Filebeat** | Lower resource usage, built-in Kafka sink, single binary, VRL transforms |
| **Kafka over RabbitMQ** | Durable log-based broker; replay capability; partitioning for future scale |
| **KRaft over Zookeeper** | Eliminates Zookeeper dependency; simpler single-broker setup; production-ready since Kafka 3.7 |
| **Python consumer over Flink** | Dramatically simpler for POC; same parser logic migrates to PyFlink in SYSTEM |
| **ClickHouse over TimescaleDB** | 10-100x faster for analytical queries; native columnar compression; Map column type for flexible parsed fields |
| **Grafana over Superset** | Lighter, faster setup; real-time auto-refresh; sufficient for POC dashboards |

## Upgrade Path to SYSTEM

| POC Component | SYSTEM Replacement | Migration Effort |
|---------------|-------------------|-----------------|
| Python consumer | Apache Flink (PyFlink) | Parser code reused; consumer loop replaced by Flink topology |
| Single Kafka broker | 3-broker Kafka cluster | Config change only |
| Single ClickHouse node | ClickHouse cluster (3 nodes) | Schema unchanged; add replication + sharding |
| Grafana only | Grafana + Superset | Additive; Grafana stays |
| No monitoring | Prometheus + Grafana monitoring | Additive |
