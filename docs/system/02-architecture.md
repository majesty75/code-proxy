# SYSTEM — Architecture

## 1. System Context Diagram

```mermaid
flowchart LR
    subgraph EDGE["Edge Layer (10 UTA Servers — Linux)"]
        direction TB
        UTA1["UTA Server 1<br/>15 boards"]
        UTA2["UTA Server 2<br/>15 boards"]
        UTAN["UTA Server N<br/>15 boards"]
        V1["Vector Agent"]
        V2["Vector Agent"]
        VN["Vector Agent"]
        UTA1 --- V1
        UTA2 --- V2
        UTAN --- VN
    end

    subgraph CORE["Core Layer (Main Server — Windows/WSL2/Docker)"]
        direction TB
        subgraph INGEST["Ingestion"]
            KFK["Kafka Cluster<br/>3 brokers (KRaft)"]
        end
        subgraph PROCESS["Processing"]
            FLINK["Apache Flink<br/>(PyFlink)"]
            PARSERS["Parser Plugins<br/>(Python)"]
            FLINK --- PARSERS
        end
        subgraph STORE["Storage"]
            CH_HOT["ClickHouse Cluster<br/>Hot Tier (SSD)"]
            CH_COLD["ClickHouse<br/>Cold Tier (HDD)"]
        end
        subgraph SERVE["Serving"]
            GRF["Grafana<br/>Real-time"]
            SUP["Superset<br/>BI / Analytics"]
        end
        subgraph AI["AI/ML (Phase 2)"]
            MLF["MLflow"]
            MODEL["Model Serving"]
        end
    end

    V1 & V2 & VN -->|"Kafka protocol<br/>TCP :9092"| KFK
    KFK --> FLINK
    FLINK -->|"batch INSERT"| CH_HOT
    CH_HOT -->|"TTL move"| CH_COLD
    CH_HOT --> GRF
    CH_HOT & CH_COLD --> SUP
    CH_HOT --> MLF
    MLF --> MODEL

    ENG["Test Engineers"] --> GRF & SUP
    MGR["Managers"] --> SUP
```

## 2. Data Flow Diagram

```mermaid
flowchart TD
    A["Log file written<br/>(board test execution)"] --> B["Vector tails file<br/>(inotify, checkpointed)"]
    B --> C{"Enrich with metadata"}
    C --> D["Publish to Kafka<br/>topic: raw-logs<br/>key: server_ip<br/>partition: by server"]
    D --> E["Flink consumes<br/>(consumer group: uta-flink)"]
    E --> F{"Parse filename<br/>(extract metadata)"}
    F --> G{"Route to parser<br/>(plugin matching)"}
    G --> H["Parser extracts<br/>structured fields"]
    H --> I{"Detect severity<br/>+ test result"}
    I --> J["Batch INSERT<br/>→ ClickHouse"]
    J --> K["log_events table<br/>(MergeTree, partitioned by day)"]
    J --> L["test_sessions table<br/>(ReplacingMergeTree)"]
    K --> M["Grafana dashboards<br/>(auto-refresh 5s)"]
    K & L --> N["Superset BI<br/>(on-demand queries)"]
    K --> O["Feature export<br/>→ MLflow (Phase 2)"]
```

## 3. Deployment Diagram

```mermaid
flowchart TB
    subgraph UTA1["UTA Server 1 (Linux)"]
        V1_SVC["vector.service<br/>(systemd)"]
        LOGS1["/uta/UTA_FULL_Logs/<br/>15 concurrent log files"]
        V1_SVC -->|tail| LOGS1
    end

    subgraph UTA2["UTA Server 2 (Linux)"]
        V2_SVC["vector.service"]
        LOGS2["/uta/UTA_FULL_Logs/"]
        V2_SVC -->|tail| LOGS2
    end

    subgraph MAIN["Main Server (Windows + WSL2)"]
        subgraph DOCKER["Docker / K8s"]
            K1["kafka-0"]
            K2["kafka-1"]
            K3["kafka-2"]
            FL1["flink-jm<br/>(JobManager)"]
            FL2["flink-tm-1<br/>(TaskManager)"]
            FL3["flink-tm-2<br/>(TaskManager)"]
            CH1["clickhouse-01<br/>(shard 1, replica 1)"]
            CH2["clickhouse-02<br/>(shard 1, replica 2)"]
            CH3["clickhouse-03<br/>(shard 2, replica 1)"]
            GRF["grafana"]
            SUP["superset"]
            PROM["prometheus"]
        end

        subgraph STORAGE["Disk Volumes"]
            SSD["SSD Volume<br/>(Hot: 30 days)"]
            HDD["HDD Volume<br/>(Cold: 30d–2y)"]
        end

        CH1 & CH2 --> SSD
        CH3 --> HDD
    end

    V1_SVC & V2_SVC -->|TCP :9092| K1
    K1 & K2 & K3 --> FL1
    FL1 --> FL2 & FL3
    FL2 & FL3 --> CH1 & CH2
```

## 4. Component Interaction

```mermaid
sequenceDiagram
    participant LOG as Log File (UTA)
    participant VEC as Vector Agent
    participant KFK as Kafka Cluster
    participant FJM as Flink JobManager
    participant FTM as Flink TaskManager
    participant PRS as Parser Plugin
    participant CH as ClickHouse
    participant GRF as Grafana

    LOG->>VEC: inotify: new bytes
    VEC->>VEC: Read lines, enrich metadata
    VEC->>KFK: Produce (topic=raw-logs, key=server_ip)
    KFK->>FJM: Consumer group assignment
    FJM->>FTM: Distribute partitions
    FTM->>FTM: Deserialize message
    FTM->>PRS: filename_parser.parse(filename)
    FTM->>PRS: router.get_parser(line, filename)
    PRS->>FTM: Parsed fields dict
    FTM->>FTM: Build ClickHouse row
    FTM->>CH: Batch INSERT (every 1s or 1000 rows)
    Note over FTM,KFK: Checkpoint: commit Kafka offset
    GRF->>CH: SQL query (auto-refresh)
    CH->>GRF: Result set
```

## 5. Kafka Topic Architecture

| Topic | Partitions | Key | Replication | Retention | Purpose |
|-------|-----------|-----|-------------|-----------|---------|
| `raw-logs` | 10 (one per server) | `server_ip` | 3 | 24h | Raw log lines from Vector |
| `parsed-events` (optional) | 10 | `server_ip` | 3 | 12h | Parsed output from Flink (for debugging / alternative consumers) |
| `dead-letter` | 1 | — | 3 | 7d | Messages that failed parsing |

## 6. Failure Handling

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Vector agent crash | systemd auto-restart | Resumes from file checkpoint |
| Network loss (UTA → Kafka) | Vector internal buffer (disk-backed) | Drains buffer when network restored |
| Kafka broker failure | KRaft consensus (2/3 majority) | Automatic leader election |
| Flink TaskManager crash | Flink restarts task | Resumes from last Kafka checkpoint |
| ClickHouse node failure | Replica takes over reads | Automatic replication catch-up |
| Grafana crash | Stateless, Docker restart | Instant recovery |
