#!/bin/bash
# Vector Edge Docker Installation Script

echo "Configuring Vector Edge Agent..."
cat <<EOF > .env
VECTOR_SERVER_IP=192.168.1.10
KAFKA_BOOTSTRAP_SERVERS=192.168.1.100:9092
EOF

echo "Starting Vector via Docker Compose..."
docker compose up -d

echo "Vector Edge Agent is now running."
