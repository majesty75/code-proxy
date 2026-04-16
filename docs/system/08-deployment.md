# SYSTEM — Deployment

## 1. Deployment Strategy

| Environment | Orchestration | When |
|------------|---------------|------|
| Development | Docker Compose | Local testing, POC |
| Staging | Docker Compose (prod overrides) | Pre-production validation |
| Production | Docker Compose or Kubernetes | Full deployment |

> **Note**: For 10 UTA servers and 5-10 dashboard users, Docker Compose on a powerful single machine is sufficient. Kubernetes is recommended only if you scale beyond 20+ servers or need multi-machine deployment.

## 2. Hardware Requirements

### Main Server (Windows + WSL2)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 16 cores | 32 cores |
| RAM | 64 GB | 128 GB |
| SSD (Hot) | 2 TB NVMe | 4 TB NVMe |
| HDD (Cold) | 20 TB | 50 TB |
| Network | 1 Gbps | 10 Gbps |
| OS | Windows 10/11 with WSL2 | Windows Server 2022 with WSL2 |

### Memory Budget

| Service | RAM |
|---------|-----|
| Kafka (3 brokers) | 3 × 4 GB = 12 GB |
| Flink (JM + 2 TMs) | 2 + 2 × 4 = 10 GB |
| ClickHouse (3 nodes) | 3 × 8 GB = 24 GB |
| Grafana | 1 GB |
| Superset | 2 GB |
| Prometheus + Loki | 2 GB |
| **Total** | **~51 GB** |

### UTA Servers

| Component | Requirement |
|-----------|-------------|
| Vector agent | ~50 MB RAM, ~1% CPU |
| Network | TCP port 9092 outbound to main server |
| Disk | 100 MB for Vector data dir (checkpoints) |

## 3. Docker Compose Production

File: `docker-compose.prod.yml`

```yaml
version: "3.8"

networks:
  uta-net:
    driver: bridge

services:
  # ---- Kafka Cluster (3 brokers, KRaft) ----
  kafka-0:
    image: apache/kafka:latest
    container_name: uta-kafka-0
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 0
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://${MAIN_SERVER_IP}:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 0@kafka-0:9093,1@kafka-1:9093,2@kafka-2:9093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_NUM_PARTITIONS: 10
      KAFKA_DEFAULT_REPLICATION_FACTOR: 3
      KAFKA_MIN_INSYNC_REPLICAS: 2
      KAFKA_LOG_RETENTION_HOURS: 24
      KAFKA_LOG_SEGMENT_BYTES: 1073741824
      KAFKA_MESSAGE_MAX_BYTES: 1048576
      CLUSTER_ID: "uta-prod-cluster"
    volumes:
      - kafka-0-data:/var/lib/kafka/data
    networks:
      - uta-net
    deploy:
      resources:
        limits:
          memory: 4G

  kafka-1:
    image: apache/kafka:latest
    container_name: uta-kafka-1
    ports:
      - "9093:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://${MAIN_SERVER_IP}:9093
      KAFKA_CONTROLLER_QUORUM_VOTERS: 0@kafka-0:9093,1@kafka-1:9093,2@kafka-2:9093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      CLUSTER_ID: "uta-prod-cluster"
    volumes:
      - kafka-1-data:/var/lib/kafka/data
    networks:
      - uta-net
    deploy:
      resources:
        limits:
          memory: 4G

  kafka-2:
    image: apache/kafka:latest
    container_name: uta-kafka-2
    ports:
      - "9094:9092"
    environment:
      KAFKA_NODE_ID: 2
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://${MAIN_SERVER_IP}:9094
      KAFKA_CONTROLLER_QUORUM_VOTERS: 0@kafka-0:9093,1@kafka-1:9093,2@kafka-2:9093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      CLUSTER_ID: "uta-prod-cluster"
    volumes:
      - kafka-2-data:/var/lib/kafka/data
    networks:
      - uta-net
    deploy:
      resources:
        limits:
          memory: 4G

  # ---- ClickHouse Cluster ----
  clickhouse-01:
    image: clickhouse/clickhouse-server:latest
    container_name: uta-clickhouse-01
    ports:
      - "8123:8123"
      - "9000:9000"
    volumes:
      - ch-01-hot:/var/lib/clickhouse/hot
      - ch-01-cold:/var/lib/clickhouse/cold
      - ./services/clickhouse/init:/docker-entrypoint-initdb.d
      - ./services/clickhouse/config/config.xml:/etc/clickhouse-server/config.d/custom.xml
    ulimits:
      nofile: { soft: 262144, hard: 262144 }
    networks:
      - uta-net
    deploy:
      resources:
        limits:
          memory: 8G

  # ---- Flink ----
  flink-jobmanager:
    build: ./services/flink-job
    container_name: uta-flink-jm
    command: jobmanager
    environment:
      FLINK_PROPERTIES: |
        jobmanager.rpc.address: flink-jobmanager
        state.checkpoints.dir: file:///opt/flink/checkpoints
    volumes:
      - flink-checkpoints:/opt/flink/checkpoints
    networks:
      - uta-net
    deploy:
      resources:
        limits:
          memory: 2G

  flink-taskmanager:
    build: ./services/flink-job
    command: taskmanager
    environment:
      FLINK_PROPERTIES: |
        jobmanager.rpc.address: flink-jobmanager
        taskmanager.numberOfTaskSlots: 4
        taskmanager.memory.process.size: 4096m
    depends_on:
      - flink-jobmanager
    networks:
      - uta-net
    deploy:
      replicas: 2
      resources:
        limits:
          memory: 4G

  # ---- Grafana ----
  grafana:
    image: grafana/grafana-oss:latest
    container_name: uta-grafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GF_ADMIN_PASSWORD}
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
    volumes:
      - grafana-data:/var/lib/grafana
      - ./services/grafana/provisioning:/etc/grafana/provisioning
    networks:
      - uta-net

  # ---- Superset ----
  superset:
    build: ./services/superset
    container_name: uta-superset
    ports:
      - "8088:8088"
    environment:
      SUPERSET_SECRET_KEY: ${SUPERSET_SECRET_KEY}
    volumes:
      - superset-data:/app/superset_home
    networks:
      - uta-net

  # ---- Monitoring ----
  prometheus:
    image: prom/prometheus:latest
    container_name: uta-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./infra/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    networks:
      - uta-net

volumes:
  kafka-0-data:
  kafka-1-data:
  kafka-2-data:
  ch-01-hot:
    driver_opts:
      type: none
      o: bind
      device: /mnt/ssd/clickhouse   # Mount SSD volume
  ch-01-cold:
    driver_opts:
      type: none
      o: bind
      device: /mnt/hdd/clickhouse   # Mount HDD volume
  flink-checkpoints:
  grafana-data:
  superset-data:
  prometheus-data:
```

## 4. WSL2 Networking Considerations

| Concern | Solution |
|---------|----------|
| UTA servers can't reach WSL2 directly | Docker Desktop binds container ports to Windows host NIC. Use Windows host IP. |
| WSL2 IP changes on reboot | Use Docker Desktop (not raw WSL2 Docker) — it handles port forwarding transparently. |
| Firewall | Allow inbound TCP 9092-9094 (Kafka), 3000 (Grafana), 8088 (Superset) in Windows Firewall. |
| DNS | UTA servers use the Windows host IP directly (e.g., `192.168.1.100`). No DNS needed. |

## 5. Startup Order

```bash
#!/bin/bash
# scripts/start.sh

set -e

echo "1/6 Starting Kafka cluster..."
docker compose -f docker-compose.prod.yml up -d kafka-0 kafka-1 kafka-2
sleep 15  # Wait for KRaft consensus

echo "2/6 Creating Kafka topics..."
docker compose exec kafka-0 kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --if-not-exists --topic raw-logs \
  --partitions 10 --replication-factor 3 \
  --config retention.ms=86400000

docker compose exec kafka-0 kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --if-not-exists --topic dead-letter \
  --partitions 1 --replication-factor 3 \
  --config retention.ms=604800000

echo "3/6 Starting ClickHouse..."
docker compose -f docker-compose.prod.yml up -d clickhouse-01
sleep 10

echo "4/6 Starting Flink..."
docker compose -f docker-compose.prod.yml up -d flink-jobmanager flink-taskmanager
sleep 10

echo "5/6 Starting visualization..."
docker compose -f docker-compose.prod.yml up -d grafana superset

echo "6/6 Starting monitoring..."
docker compose -f docker-compose.prod.yml up -d prometheus

echo "✅ All services started. Deploy Vector to UTA servers next."
echo "   Grafana:    http://localhost:3000"
echo "   Superset:   http://localhost:8088"
echo "   Prometheus: http://localhost:9090"
```
