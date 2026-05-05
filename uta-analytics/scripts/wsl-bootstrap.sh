#!/usr/bin/env bash
# Bootstrap UTA analytics on WSL2 (Ubuntu) with Docker Desktop's WSL backend.
# Idempotent — safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*" 1>&2; }
step()   { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

# ---------- 1. Sanity checks ----------
step "Checking prerequisites"
command -v docker >/dev/null || { red "docker not found"; exit 1; }
docker version >/dev/null 2>&1 || { red "docker daemon unreachable"; exit 1; }
docker compose version >/dev/null 2>&1 || { red "docker compose plugin missing"; exit 1; }
green "✓ Docker reachable"

# ---------- 2. .env ----------
step "Preparing .env"
if [[ ! -f .env ]]; then
  cp .env.example .env
  green "✓ Created .env (review)"
else
  yellow "• .env already present"
fi

# ---------- 3. Watch dir (kept for future Vector wiring) ----------
mkdir -p vector/logs/completed

# ---------- 4. Build parser image ----------
step "Building parser image"
docker compose build parser

# ---------- 5. Start core infra ----------
step "Starting Kafka and ClickHouse"
docker compose up -d kafka clickhouse

step "Waiting for Kafka"
for i in {1..60}; do
  if docker compose exec -T kafka /opt/kafka/bin/kafka-broker-api-versions.sh \
       --bootstrap-server localhost:9092 >/dev/null 2>&1; then
    green "✓ Kafka up"; break
  fi
  sleep 2
  [[ $i -eq 60 ]] && { red "Kafka did not become healthy in 120s"; docker compose logs --tail=80 kafka; exit 1; }
done

step "Waiting for ClickHouse"
for i in {1..60}; do
  if docker compose exec -T clickhouse clickhouse-client --query "SELECT 1" >/dev/null 2>&1; then
    green "✓ ClickHouse up"; break
  fi
  sleep 2
  [[ $i -eq 60 ]] && { red "ClickHouse did not become healthy in 120s"; docker compose logs --tail=80 clickhouse; exit 1; }
done

# ---------- 6. Topic ----------
step "Creating raw-logs topic (if missing)"
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic raw-logs \
  --partitions 3 --replication-factor 1 >/dev/null
green "✓ raw-logs topic ready"

# ---------- 7. Schema (idempotent re-apply) ----------
step "Applying ClickHouse schema"
docker compose exec -T clickhouse \
  clickhouse-client --user=default --password=password --multiquery \
  < clickhouse/init/01-schema.sql
green "✓ Schema applied"

# ---------- 8. Parser + Grafana ----------
step "Starting parser and Grafana"
docker compose up -d parser grafana
sleep 4

# ---------- 9. Health summary ----------
step "Status"
docker compose ps

GF_PORT="$(grep -E '^GF_PORT=' .env | cut -d= -f2 | tr -d ' \r' || echo 3005)"
GF_PORT="${GF_PORT:-3005}"

cat <<EOF

$(green "Bootstrap complete.")

  Grafana     : http://localhost:${GF_PORT}   (admin / admin)
    Lab Grid    → http://localhost:${GF_PORT}/d/uta-lab-grid-v1/
    Board Detail → http://localhost:${GF_PORT}/d/uta-board-detail-v1/
  ClickHouse  : http://localhost:8123          (default / password)
  Kafka       : localhost:9092                 (raw-logs topic)

Next steps:
  • Seed demo data (direct ClickHouse insert, fastest):
      python3 scripts/demo_seed.py
  • Stream a single board through the live pipeline (Kafka → parser → ClickHouse):
      docker run --rm --network uta-analytics_uta-net \\
        -v "\$(pwd)":/work -w /work uta-analytics-parser \\
        python scripts/demo_kafka_producer.py --bootstrap kafka:9092 \\
        --blocks 4 --rate 600 --rack 9 --shelf 1 --slot 1
  • Tail the parser:
      docker compose logs -f parser

EOF
