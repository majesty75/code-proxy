# SYSTEM — Observability

## 1. Monitoring Stack

```mermaid
flowchart LR
    subgraph TARGETS["Monitored Services"]
        K["Kafka<br/>JMX exporter :9404"]
        F["Flink<br/>metrics :9249"]
        CH["ClickHouse<br/>/metrics :8123"]
        V["Vector<br/>internal metrics"]
    end

    PROM["Prometheus<br/>:9090"] -->|scrape| K & F & CH
    V -->|push (remote_write)| PROM

    PROM --> GRF_MON["Grafana<br/>(monitoring dashboards)"]
    LOKI["Loki<br/>:3100"] --> GRF_MON
    K & F & CH -->|"logs (stdout)"| LOKI
```

## 2. Key Metrics

### Kafka

| Metric | Source | Alert Threshold |
|--------|--------|----------------|
| `kafka_server_brokertopicmetrics_messagesin_total` | JMX | < 1000/sec (data stopped flowing) |
| `kafka_consumer_group_lag` | JMX / Burrow | > 100,000 (parser can't keep up) |
| `kafka_log_size_bytes` | JMX | > 80% disk usage |

### Flink

| Metric | Source | Alert Threshold |
|--------|--------|----------------|
| `flink_taskmanager_job_task_numRecordsInPerSecond` | Flink REST | < 1000 (processing stalled) |
| `flink_taskmanager_job_task_numRecordsOutPerSecond` | Flink REST | < 1000 |
| `flink_jobmanager_job_lastCheckpointDuration` | Flink REST | > 30s (checkpoint slow) |
| `flink_jobmanager_job_numberOfFailedCheckpoints` | Flink REST | > 0 |

### ClickHouse

| Metric | Source | Alert Threshold |
|--------|--------|----------------|
| `ClickHouseProfileEvents_InsertedRows` | `/metrics` | < 1000/sec (inserts stopped) |
| `ClickHouseMetrics_Query` | `/metrics` | > 50 concurrent queries |
| `ClickHouseAsyncMetrics_MaxPartCountForPartition` | `/metrics` | > 300 (too many parts, merge lag) |
| Disk usage | `system.disks` query | > 85% |

### Vector

| Metric | Source | Alert Threshold |
|--------|--------|----------------|
| `vector_events_in_total` | Internal metrics | 0 for > 5 min (file watching stopped) |
| `vector_events_out_total` | Internal metrics | 0 for > 5 min |
| `vector_buffer_events` | Internal metrics | > 10,000 (backpressure) |

## 3. Prometheus Configuration

File: `infra/prometheus/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'clickhouse'
    static_configs:
      - targets: ['clickhouse-01:8123']
    metrics_path: /metrics

  - job_name: 'kafka'
    static_configs:
      - targets: ['kafka-0:9404', 'kafka-1:9404', 'kafka-2:9404']

  - job_name: 'flink'
    static_configs:
      - targets: ['flink-jobmanager:9249']

  - job_name: 'grafana'
    static_configs:
      - targets: ['grafana:3000']
    metrics_path: /metrics
```

## 4. Alert Rules

File: `infra/prometheus/alert-rules.yml`

```yaml
groups:
  - name: uta-pipeline
    rules:
      - alert: KafkaConsumerLagHigh
        expr: kafka_consumer_group_lag > 100000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Kafka consumer lag is high ({{ $value }})"

      - alert: FlinkProcessingStopped
        expr: rate(flink_taskmanager_job_task_numRecordsInPerSecond[5m]) == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Flink is not processing any records"

      - alert: ClickHouseInsertsStopped
        expr: rate(ClickHouseProfileEvents_InsertedRows[5m]) == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "ClickHouse inserts have stopped"

      - alert: ClickHouseDiskFull
        expr: ClickHouseAsyncMetrics_DiskUsed_default / ClickHouseAsyncMetrics_DiskTotal_default > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "ClickHouse disk usage above 85%"

      - alert: VectorBackpressure
        expr: vector_buffer_events > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Vector buffer is backing up on {{ $labels.instance }}"
```

## 5. Health Check Endpoints

| Service | Health Check | Method |
|---------|-------------|--------|
| Kafka | `kafka-broker-api-versions.sh --bootstrap-server localhost:9092` | CLI |
| ClickHouse | `GET http://localhost:8123/ping` → `Ok.` | HTTP |
| Flink | `GET http://localhost:8081/overview` | HTTP |
| Grafana | `GET http://localhost:3000/api/health` → `{"database":"ok"}` | HTTP |
| Superset | `GET http://localhost:8088/health` | HTTP |
| Vector | `vector top` (CLI) or internal metrics API | CLI |

## 6. Monitoring Dashboards (in Grafana)

Separate from test-log dashboards. These monitor the **pipeline infrastructure** itself.

| Dashboard | Panels |
|-----------|--------|
| **Pipeline Overview** | Ingestion rate, processing rate, insert rate, end-to-end latency |
| **Kafka Health** | Broker status, partition lag, disk usage, topic sizes |
| **Flink Jobs** | Job status, checkpoint duration, throughput, backpressure |
| **ClickHouse Performance** | Query latency, merge activity, part count, disk usage per tier |
| **Vector Agents** | Per-server: events in/out, buffer size, errors |
