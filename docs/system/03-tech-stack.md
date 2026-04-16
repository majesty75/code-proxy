# SYSTEM — Tech Stack

## Component Matrix

| Layer | Component | Technology | Version | License | Justification |
|-------|-----------|-----------|---------|---------|---------------|
| **Edge** | Log Collector | Vector | latest stable | MPL-2.0 | Lowest CPU/memory of all collectors; native Kafka sink; disk-backed buffer; single static binary |
| **Ingestion** | Message Broker | Apache Kafka (KRaft) | latest stable | Apache-2.0 | Log-based durable broker; partition-per-server ordering; replay for reprocessing; exactly-once support |
| **Processing** | Stream Processor | Apache Flink (PyFlink) | latest stable | Apache-2.0 | Exactly-once semantics; windowing; watermarks; checkpointed state; Python API for parser plugins |
| **Processing** | Parser Runtime | Python | 3.12+ | PSF | Parser plugins in Python; data science ecosystem; team familiarity |
| **Storage** | Analytical DB | ClickHouse | latest LTS | Apache-2.0 | 10-100x faster than PostgreSQL for analytics; native columnar compression; Map type for flexible schema; tiered storage |
| **Visualization** | Real-time Dashboards | Grafana OSS | latest stable | AGPL-3.0 | Auto-refresh, alerting, ClickHouse plugin, templating |
| **Visualization** | BI / Historical | Apache Superset | latest stable | Apache-2.0 | SQL Lab, chart builder, drill-down, scheduled reports |
| **AI/ML** | Experiment Tracking | MLflow | latest stable | Apache-2.0 | Model registry, experiment comparison, artifact storage |
| **AI/ML** | Model Serving | BentoML | latest stable | Apache-2.0 | Simpler than Seldon; Python-native; REST API serving |
| **Monitoring** | Metrics | Prometheus | latest stable | Apache-2.0 | Pull-based metrics; native Docker/K8s integration |
| **Monitoring** | Log Aggregation | Grafana Loki | latest stable | AGPL-3.0 | Lightweight log aggregation for system logs (not test logs) |
| **Orchestration** | Container Runtime | Docker Compose / K8s | latest stable | Apache-2.0 | Docker Compose for initial; K8s for scale |

## Python Dependencies (Flink Job)

| Package | Purpose |
|---------|---------|
| `apache-flink` | Flink Python API |
| `confluent-kafka` | Kafka consumer (used by Flink's Kafka connector) |
| `clickhouse-connect` | ClickHouse writer |
| `pydantic` | Message validation |
| `structlog` | Structured logging |

## Technology Decisions

### Why Flink over Spark Structured Streaming
- **Lower latency**: True event-at-a-time processing vs micro-batching.
- **Exactly-once**: Native Kafka-to-sink exactly-once with checkpointing.
- **Lighter**: Flink TaskManagers use less memory than Spark executors.
- **Python support**: PyFlink is mature enough for our parser plugins.

### Why ClickHouse over alternatives

| Alternative | Why Not |
|-------------|---------|
| PostgreSQL + TimescaleDB | 10-50x slower for analytical aggregations; row-oriented |
| Elasticsearch | JSON parsing overhead; complex cluster management; licensed features (X-Pack) |
| Apache Druid | More complex ingestion; weaker SQL support |
| DuckDB | Single-node only; no clustering |

### Why Vector over alternatives

| Alternative | Why Not |
|-------------|---------|
| Filebeat | Higher resource usage; requires Logstash for transforms |
| Fluentd | Ruby-based; higher memory; plugin ecosystem less reliable |
| rsyslog | Poor Kafka integration; config syntax arcane |
| Custom script | No checkpointing; no backpressure; maintenance burden |

### Why BentoML over Seldon (AI/ML phase)
- **Simpler**: No K8s CRDs or Istio dependency.
- **Python-native**: Model wraps directly in Python, no YAML manifests.
- **Open-source**: Fully Apache-2.0 licensed.
