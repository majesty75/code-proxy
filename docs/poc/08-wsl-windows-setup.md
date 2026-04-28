# POC — WSL2 + Windows setup

This is the canonical setup guide when the work machine is **Windows with Docker Desktop using the WSL2 backend**. The repo lives inside WSL Ubuntu; the simulator runs from Windows PowerShell against a folder of real logs.

## Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│ Windows host                                                           │
│                                                                        │
│   PowerShell ──> simulate_from_folder.py ──┐                           │
│                                            │ writes log lines into     │
│                                            ▼                           │
│   \\wsl$\Ubuntu\home\<you>\Projects\UTA\uta-analytics\vector\logs\     │
│                                                                        │
│  ┌──────────────────────── WSL2 (Ubuntu) ─────────────────────────┐    │
│  │  Docker Compose stack                                          │    │
│  │  ┌─────────┐  ┌──────┐  ┌────────┐  ┌────────────┐  ┌───────┐  │    │
│  │  │ vector  │─>│kafka │─>│ parser │─>│ clickhouse │<─│grafana│  │    │
│  │  │ + watch │  │      │  │        │  │            │  │       │  │    │
│  │  └─────────┘  └──────┘  └────────┘  └────────────┘  └───────┘  │    │
│  │       ▲                                                        │    │
│  │       └── tails ./vector/logs/*.log (bind mount)               │    │
│  └────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────┘
```

Why this layout:
- All Compose services run inside WSL → fast bind mounts, no Windows file-watch quirks.
- Vector (inside Docker) tails `./vector/logs/*.log`. That folder is a normal Linux folder inside WSL.
- The Windows-side simulator writes to that same folder via the WSL share path `\\wsl$\Ubuntu\…`. Files written there appear instantly to Vector inside Docker because they are Linux files.
- The fingerprint strategy in `vector.toml` is `device_and_inode`, which behaves correctly on the WSL filesystem.

## Prerequisites (one-time per machine)

1. **Windows 11 or 10 (build 19041+)**.
2. **WSL2** with Ubuntu 22.04 (or 24.04):
   ```powershell
   wsl --install -d Ubuntu-22.04
   ```
3. **Docker Desktop** with the **WSL2 backend** enabled (Settings → General → "Use the WSL 2 based engine"; Resources → WSL Integration → enable for your distro).
4. **Git** inside WSL (`sudo apt install -y git`).
5. **Python 3.10+ on Windows** for the simulator (any recent Python.org installer).

## First-time setup

Open **Ubuntu (WSL)** and run:

```bash
cd ~
git clone <repo-url> Projects/UTA   # adjust to your repo URL
cd Projects/UTA/uta-analytics
./scripts/wsl-bootstrap.sh
```

What `wsl-bootstrap.sh` does, in order:

1. Verifies Docker is reachable from WSL (`docker version`).
2. Copies `.env.example` → `.env` if `.env` does not exist; warns if it already does.
3. Creates `vector/logs/` if missing (this is the watched folder).
4. Pulls / builds all images (`docker compose build --pull`).
5. Starts Kafka and ClickHouse, waits for healthchecks, creates the `raw-logs` topic, applies the schema.
6. Starts parser, vector, watcher, grafana.
7. Runs `verify.sh` and prints the Grafana URL.

After it finishes, Grafana is at **http://localhost:3005** (admin / admin) — the port comes from `GF_PORT` in `.env`.

## Running the simulator from Windows

The simulator takes a **folder of real log files** on Windows and emulates real-time generation by streaming each file line-by-line into the watched folder. When a file finishes, it is moved to `completed/` to trigger the `test_completed` event.

```powershell
# From Windows PowerShell
cd C:\path\to\repo\uta-analytics

# Resolve the WSL-side watch directory (one-time, copy the printed path)
wsl wslpath -w /home/$env:USERNAME/Projects/UTA/uta-analytics/vector/logs

# Run the simulator. --source is a Windows folder full of real .log files.
python .\scripts\simulate_from_folder.py `
  --source "C:\Users\you\test-logs" `
  --target "\\wsl$\Ubuntu\home\you\Projects\UTA\uta-analytics\vector\logs" `
  --rate 150 `
  --concurrency 4
```

Flags:
- `--source` — folder containing existing `.log` files to emulate. Read-only.
- `--target` — folder where Vector watches. Must be the WSL bind-mount path.
- `--rate` — lines per second per file. Default 150 (matches single-board rate).
- `--concurrency` — how many files to stream in parallel (matches concurrent boards).
- `--rename-slot` — optional. Rewrites `R<rack>S<shelf>-<slot>` in each filename so multiple copies of the same source file simulate distinct boards. Useful when `--source` contains only one or two real logs.

The script is idempotent — re-running it overwrites `target/<filename>` with a fresh emulation. Files that have already been moved to `target/completed/` are left alone.

## Stopping / restarting

```bash
# Stop containers, keep volumes
./scripts/stop.sh

# Stop and wipe data
docker compose down -v

# Restart only the parser after editing parser code
docker compose up -d --build parser
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Vector not seeing files written from Windows | Wrong target path (Windows path passed instead of `\\wsl$\…`) | Pass the `\\wsl$\Ubuntu\…` UNC path; verify with `wsl ls -la /home/<you>/Projects/UTA/uta-analytics/vector/logs`. |
| Parser connects to ClickHouse with `password` | `.env` not loaded by Compose | Re-run from `uta-analytics/`; Compose only auto-loads `.env` from the working directory. |
| Grafana shows "datasource not configured" | `UTA_CH_USERNAME`/`UTA_CH_PASSWORD` not exported to Grafana | Already wired in `docker-compose.yml`; ensure `.env` has values, then `docker compose up -d grafana`. |
| Kafka logs grow unbounded during backfill | Backfill should not go through Kafka | Use `docker compose --profile backfill run --rm backfill` instead of writing to the watched folder. See `09-backfill-existing-logs.md`. |
| `docker compose exec kafka …` is slow on Windows | Docker Desktop CLI proxy | Run the command from inside WSL Ubuntu, not PowerShell. |
