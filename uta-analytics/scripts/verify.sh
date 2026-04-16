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
