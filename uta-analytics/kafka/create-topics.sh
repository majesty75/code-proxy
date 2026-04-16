#!/bin/bash
# Wait for Kafka to be ready
sleep 10
kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic raw-logs \
  --partitions 1 \
  --replication-factor 1 \
  --config retention.ms=86400000  # 24h
echo "Topic 'raw-logs' created."
