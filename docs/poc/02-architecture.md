# POC — Architecture

## System Context

```mermaid
flowchart LR
    subgraph UTA_SERVER["UTA Server (Linux)"]
        LOG["Log Files<br/>/uta/UTA_FULL_Logs/*.log"]
        VEC["Vector Agent"]
        LOG -->|"tail (inotify)"| VEC
    end

    subgraph MAIN_SERVER["Main Server (Windows + WSL2/Docker)"]
        KFK["Kafka<br/>(KRaft, single broker)"]
        PRS["Python Parser<br/>Service"]
        CH["ClickHouse<br/>(single node)"]
        GRF["Grafana"]
    end

    VEC -->|"Kafka protocol<br/>TCP :9092"| KFK
    KFK -->|"consumer poll"| PRS
    PRS -->|"HTTP INSERT<br/>:8123"| CH
    CH -->|"SQL datasource<br/>:8123"| GRF

    ENG["Test Engineer<br/>(Browser)"] -->|":3000"| GRF
```

## Data Flow

```mermaid
sequenceDiagram
    participant LOG as Log File
    participant VEC as Vector
    participant KFK as Kafka
    participant PRS as Parser Service
    participant CH as ClickHouse
    participant GRF as Grafana

    LOG->>VEC: New line appended
    VEC->>VEC: Enrich with filename, server_ip, timestamp
    VEC->>KFK: Publish to topic "raw-logs"
    KFK->>PRS: Consumer poll (batch)
    PRS->>PRS: Extract metadata from filename
    PRS->>PRS: Select parser → parse log line
    PRS->>CH: Batch INSERT into log_events
    GRF->>CH: SQL query (user refresh / auto-refresh)
    CH->>GRF: Result set
```

## Deployment Topology

```mermaid
flowchart TB
    subgraph UTA["UTA Server — Linux (bare metal)"]
        V["Vector<br/>systemd service"]
        LOGS["Log directory<br/>/uta/UTA_FULL_Logs/"]
    end

    subgraph WSL["Main Server — WSL2 (Docker Compose)"]
        subgraph DOCKER["Docker Network: uta-net"]
            K["kafka<br/>:9092"]
            P["parser<br/>(Python)"]
            C["clickhouse<br/>:8123 :9000"]
            G["grafana<br/>:3000"]
        end
    end

    V -->|"TCP :9092<br/>(bridged to WSL)"| K
    K --> P
    P --> C
    C --> G

    BROWSER["Engineer Browser"] -->|":3000<br/>(port forwarded)"| G
```

## Kafka Topic Design (POC)

| Topic | Partitions | Retention | Key | Value |
|-------|-----------|-----------|-----|-------|
| `raw-logs` | 1 | 24h | `server_ip:slot_id` | JSON (see below) |

### Message Schema (`raw-logs` value)
```json
{
  "server_ip": "192.168.1.10",
  "log_filename": "R7S4-12_20260414_163815_EXEC_AA2_SIRIUS_UFS_3_1_V8_TLC_1Tb_SAMSUNG_512GB_P00_RC16_FW04_Rack7_Sai_Revathi_Qual_UFS.log",
  "line": "16:38:20 [INFO] Test TC_001 started — sequential read 128K",
  "line_number": 42,
  "timestamp": "2026-04-14T16:38:20.000Z"
}
```

## Component Responsibilities

| Component | Input | Output | Failure Mode |
|-----------|-------|--------|-------------|
| **Vector** | File changes (inotify) | Kafka messages | Resumes from checkpoint on restart |
| **Kafka** | Messages from Vector | Consumer-readable log | Durable on disk (24h retention) |
| **Parser** | Kafka messages (batch) | ClickHouse rows | Commits offset only after CH write succeeds |
| **ClickHouse** | HTTP INSERT batches | Queryable tables | Data persisted in MergeTree |
| **Grafana** | SQL queries to CH | Dashboards | Stateless, reads only |

## Network Ports

| Port | Service | Protocol | Exposed To |
|------|---------|----------|-----------|
| 9092 | Kafka | TCP | UTA server (Vector), Parser container |
| 8123 | ClickHouse HTTP | TCP | Parser container, Grafana container |
| 9000 | ClickHouse Native | TCP | Internal only |
| 3000 | Grafana | HTTP | Engineer browser (Windows host) |
