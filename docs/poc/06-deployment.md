# POC — Deployment

## Environment Variables

File: `.env`
```bash
# ---- Network ----
# IP of the main server (Windows) as seen from UTA servers
MAIN_SERVER_IP=192.168.1.100
# IP of the UTA server being monitored
UTA_SERVER_IP=192.168.1.10

# ---- Kafka ----
KAFKA_BROKER_ID=1
KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://${MAIN_SERVER_IP}:9092
KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092

# ---- ClickHouse ----
CH_HTTP_PORT=8123
CH_NATIVE_PORT=9000

# ---- Grafana ----
GF_PORT=3000
GF_SECURITY_ADMIN_PASSWORD=admin

# ---- Parser ----
UTA_KAFKA_BOOTSTRAP_SERVERS=kafka:9092
UTA_KAFKA_TOPIC=raw-logs
UTA_CH_HOST=clickhouse
UTA_CH_PORT=8123
UTA_CH_DATABASE=uta
UTA_BATCH_SIZE=500
```

## Docker Compose

File: `docker-compose.yml`
```yaml
version: "3.8"

networks:
  uta-net:
    driver: bridge

services:
  # ---- Kafka (KRaft mode, no Zookeeper) ----
  kafka:
    image: apache/kafka:latest
    container_name: uta-kafka
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://${MAIN_SERVER_IP}:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_LOG_RETENTION_HOURS: 24
      CLUSTER_ID: "uta-poc-cluster-001"
    volumes:
      - kafka-data:/var/lib/kafka/data
    networks:
      - uta-net
    healthcheck:
      test: ["CMD-SHELL", "kafka-broker-api-versions.sh --bootstrap-server localhost:9092 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10

  # ---- ClickHouse ----
  clickhouse:
    image: clickhouse/clickhouse-server:latest
    container_name: uta-clickhouse
    ports:
      - "${CH_HTTP_PORT}:8123"
      - "${CH_NATIVE_PORT}:9000"
    volumes:
      - ch-data:/var/lib/clickhouse
      - ./clickhouse/init:/docker-entrypoint-initdb.d
    networks:
      - uta-net
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    healthcheck:
      test: ["CMD", "clickhouse-client", "--query", "SELECT 1"]
      interval: 5s
      timeout: 3s
      retries: 10

  # ---- Parser Service ----
  parser:
    build:
      context: ./parser
      dockerfile: Dockerfile
    container_name: uta-parser
    depends_on:
      kafka:
        condition: service_healthy
      clickhouse:
        condition: service_healthy
    environment:
      UTA_KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      UTA_KAFKA_TOPIC: raw-logs
      UTA_CH_HOST: clickhouse
      UTA_CH_PORT: 8123
      UTA_CH_DATABASE: uta
      UTA_BATCH_SIZE: 500
    restart: unless-stopped
    networks:
      - uta-net

  # ---- Grafana ----
  grafana:
    image: grafana/grafana-oss:latest
    container_name: uta-grafana
    ports:
      - "${GF_PORT}:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GF_SECURITY_ADMIN_PASSWORD}
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
    depends_on:
      clickhouse:
        condition: service_healthy
    networks:
      - uta-net

volumes:
  kafka-data:
  ch-data:
  grafana-data:
```

## Parser Dockerfile

File: `parser/Dockerfile`
```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./

CMD ["python", "main.py"]
```

File: `parser/requirements.txt`
```
confluent-kafka>=2.6.0
clickhouse-connect>=0.8.0
pydantic>=2.0
pydantic-settings>=2.0
structlog>=24.0
```

## Startup Procedure

File: `scripts/start.sh`
```bash
#!/bin/bash
set -e

echo "=== Starting UTA Analytics POC ==="

# 1. Start infrastructure
docker compose up -d kafka clickhouse
echo "Waiting for Kafka and ClickHouse to be healthy..."
docker compose exec kafka bash -c 'until kafka-broker-api-versions.sh --bootstrap-server localhost:9092 2>/dev/null; do sleep 2; done'

# 2. Create Kafka topic
docker compose exec kafka bash -c '
  kafka-topics.sh --bootstrap-server localhost:9092 \
    --create --if-not-exists \
    --topic raw-logs --partitions 1 --replication-factor 1 \
    --config retention.ms=86400000
'

# 3. Start parser and Grafana
docker compose up -d parser grafana

echo "=== All services started ==="
echo "Grafana:    http://localhost:3000  (admin / admin)"
echo "ClickHouse: http://localhost:8123"
echo ""
echo "Next: Install Vector on UTA server (see vector/install.sh)"
```

## Verification

File: `scripts/verify.sh`
```bash
#!/bin/bash
echo "=== Service Health Check ==="

# Kafka
docker compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list && \
  echo "✅ Kafka OK" || echo "❌ Kafka FAILED"

# ClickHouse
docker compose exec clickhouse clickhouse-client --query "SELECT count() FROM uta.log_events" && \
  echo "✅ ClickHouse OK" || echo "❌ ClickHouse FAILED"

# Parser
docker compose logs --tail=5 parser | grep -q "consumer_started" && \
  echo "✅ Parser OK" || echo "❌ Parser FAILED"

# Grafana
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/health | grep -q "200" && \
  echo "✅ Grafana OK" || echo "❌ Grafana FAILED"
```

## Testing Without Real UTA Server

File: `scripts/seed-test-data.sh`
```bash
#!/bin/bash
# Generate fake log data directly to Kafka for testing without a real UTA server

TOPIC="raw-logs"
BOOTSTRAP="localhost:9092"
FILENAME="R7S4-12_20260414_163815_EXEC_AA2_SIRIUS_UFS_3_1_V8_TLC_1Tb_SAMSUNG_512GB_P00_RC16_FW04_Rack7_Sai_Revathi_Qual_UFS.log"

for i in $(seq 1 100); do
  SEVERITY=$(shuf -e INFO INFO INFO INFO WARN ERROR -n 1)
  MSG="16:38:${i} [$SEVERITY] Test TC_00${i} sequential_read_128K IOPS=120000 latency_us=45"
  echo "{\"server_ip\":\"192.168.1.10\",\"log_filename\":\"${FILENAME}\",\"line\":\"${MSG}\",\"line_number\":${i}}" | \
    docker compose exec -T kafka kafka-console-producer.sh --bootstrap-server localhost:9092 --topic ${TOPIC}
  sleep 0.1
done

echo "✅ Sent 100 test messages to Kafka topic '${TOPIC}'"
```

## WSL2 Networking Notes

1. **Port forwarding**: By default, Docker Desktop on WSL2 forwards container ports to `localhost` on the Windows host. Grafana at `:3000` is accessible from `http://localhost:3000` on Windows.

2. **External access from UTA servers**: The UTA server needs to reach Kafka on `MAIN_SERVER_IP:9092`. Set `KAFKA_ADVERTISED_LISTENERS` to the Windows host IP visible to UTA servers. If using WSL2 with Docker Desktop, Docker Desktop handles the port binding to the Windows host network.

3. **Firewall**: Ensure Windows Firewall allows inbound TCP on port 9092 from the UTA server subnet.
