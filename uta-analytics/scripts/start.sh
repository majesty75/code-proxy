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
