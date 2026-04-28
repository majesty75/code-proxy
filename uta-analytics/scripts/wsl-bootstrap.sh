#!/usr/bin/env bash
# One-shot bootstrap for the UTA analytics POC on WSL2 (Ubuntu) with
# Docker Desktop's WSL backend. Idempotent — safe to re-run.
set -euo pipefail

# Resolve to the repo's uta-analytics/ directory regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*" 1>&2; }

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

# ---------- 1. Sanity checks ----------
step "Checking prerequisites"

if ! command -v docker >/dev/null 2>&1; then
  red "docker not found. Enable Docker Desktop's WSL integration for this distro."
  exit 1
fi

if ! docker version >/dev/null 2>&1; then
  red "docker daemon unreachable. Start Docker Desktop and re-run."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  red "docker compose plugin missing. Update Docker Desktop."
  exit 1
fi

green "✓ Docker reachable"

# ---------- 2. .env ----------
step "Preparing .env"
if [[ ! -f .env ]]; then
  cp .env.example .env
  green "✓ Created .env from .env.example (review and adjust if needed)"
else
  yellow "• .env already exists, leaving it alone"
fi

# ---------- 3. Watch directory ----------
step "Preparing vector/logs/ watch directory"
mkdir -p vector/logs/completed
green "✓ vector/logs/ ready"

# ---------- 4. Build images ----------
step "Building images (this can take a few minutes the first time)"
docker compose build --pull parser

# ---------- 5. Start core infra ----------
step "Starting Kafka and ClickHouse"
docker compose up -d kafka clickhouse

step "Waiting for Kafka to become healthy"
for i in {1..60}; do
  if docker compose exec -T kafka /opt/kafka/bin/kafka-broker-api-versions.sh \
       --bootstrap-server localhost:9092 >/dev/null 2>&1; then
    green "✓ Kafka up"
    break
  fi
  sleep 2
  if [[ $i -eq 60 ]]; then
    red "Kafka did not become healthy in 120s"
    docker compose logs --tail=80 kafka
    exit 1
  fi
done

step "Waiting for ClickHouse to become healthy"
for i in {1..60}; do
  if docker compose exec -T clickhouse clickhouse-client --query "SELECT 1" >/dev/null 2>&1; then
    green "✓ ClickHouse up"
    break
  fi
  sleep 2
  if [[ $i -eq 60 ]]; then
    red "ClickHouse did not become healthy in 120s"
    docker compose logs --tail=80 clickhouse
    exit 1
  fi
done

# ---------- 6. Topic ----------
step "Creating raw-logs topic (if missing)"
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --create --if-not-exists \
  --topic raw-logs \
  --partitions 1 --replication-factor 1 \
  --config retention.ms=86400000 >/dev/null
green "✓ raw-logs topic ready"

# ---------- 7. Schema ----------
# init scripts under clickhouse/init are auto-applied on first container start.
# We re-apply them explicitly here so the bootstrap is safe on existing volumes.
step "Applying ClickHouse schema (idempotent)"
docker compose exec -T clickhouse \
  clickhouse-client --multiquery < clickhouse/init/01-schema.sql
green "✓ Schema applied"

# ---------- 8. App services ----------
step "Starting parser, vector, watcher, grafana"
docker compose up -d parser vector watcher grafana

# ---------- 9. Verify ----------
step "Health check"
sleep 3
"${SCRIPT_DIR}/verify.sh" || true

GF_PORT="$(grep -E '^GF_PORT=' .env | cut -d= -f2 | tr -d ' \r')"
GF_PORT="${GF_PORT:-3005}"

cat <<EOF

$(green "Bootstrap complete.")

  Grafana    : http://localhost:${GF_PORT}   (admin / admin)
  ClickHouse : http://localhost:8123

Next steps:
  • Simulate live logs from Windows:
      python .\\scripts\\simulate_from_folder.py --source <win-folder> --target \\\\wsl\$\\Ubuntu\\<wsl-watch-path>
  • Backfill existing logs:
      BACKFILL_DIR=<wsl-path> docker compose --profile backfill run --rm backfill

EOF
