# UTA Log Analytics POC

This repository contains the Proof of Concept (POC) for the distributed, on-premises Log Analytics platform designed for UTA, specifically tuned for processing raw, unstructured Linux system logs and arbitrary unstructured test log formats.

## Architecture

The data pipeline follows this path:
**Vector (Agent) ➔ Kafka (Broker) ➔ Python Parser (ETL) ➔ ClickHouse (DB) ➔ Grafana (Viz)**

## Prerequisites

- Docker and Docker Compose installed (compatible with Linux or WSL2).
- At least 4GB of free RAM dedicated to Docker to safely run Kafka + ClickHouse.

## 1. Quick Setup

1. **Clone & Configure Environment:**
   ```bash
   # Navigate to the analytics directory if you aren't already there
   cd uta-analytics
   
   # Setup your environment parameters
   cp .env.example .env
   ```
   *(Ensure you update `.env` with actual IPs if deploying the Vector edge agent outside of your local network)*

2. **Start the Infrastructure:**
   ```bash
   ./scripts/start.sh
   ```
   This script will:
   - Boot up Kafka (KRaft mode) and ClickHouse.
   - Automatically initialize the ClickHouse `uta` database schema.
   - Create the internal `raw-logs` Kafka topic.
   - Build your Python Parser Docker image and boot it alongside Grafana.

3. **Verify the Health of Services:**
   ```bash
   ./scripts/verify.sh
   ```
   You should see `✅` checkmarks indicating Kafka, ClickHouse, Parser container, and Grafana are all successfully passing health checks natively.

## 2. Test the Pipeline

You don't need a real UTA server running to test the logic. We have provided a script that seeds simulated system-level logs directly into the Kafka topic.

```bash
./scripts/seed-test-data.sh
```

**Check the data:**
1. Log into **Grafana** at [http://localhost:3000](http://localhost:3000) using credentials `admin` / `admin`.
2. Connect to the Clickhouse data source (Auto-provisioned).
3. The logs have traversed the entire system and sit comfortably within the ClickHouse database's `uta.log_events` table natively queryable as arbitrary stringified JSON!

## 3. Shutting Down & Cleanup

To stop and tear down the infrastructure while keeping your data volumes intact:
```bash
./scripts/stop.sh
```

If you wish to completely wipe your log data and start completely fresh, use docker specifically:
```bash
docker compose down -v
```

## 4. Expanding the Parser (Flexible JSON Support)

By default, the Python parser doesn't constrain your application logs to formal Severities (`INFO`/`WARN`). Any format or shape that is extracted is inherently stored into Clickhouse stringified JSON columns.

To add custom parsing patterns (e.g. for a custom memory dump or boot trace):
1. Navigate to `parser/src/parsers`.
2. Create a new `.py` file inheriting from `BaseParser`.
3. Provide your logic in the `parse()` method which returns **any type of arbitrarily nested python dictionary**:
   
   ```python
   # Example: parse() returning heavy nested arbitrary types
   def parse(self, line: str, filename: str) -> dict[str, Any]:
       # ... custom logic ...
       return {
           "hardware_status": "OK",
           "faults": {"memory": False, "cpu": False},
           "sub_traces": [10, 202, 59]
       }
   ```
4. Restart the parser: `docker compose restart parser`

## 5. Setting up Edge UTA Servers (Vector)

When deploying to a real external UTA machine emitting files, you will deploy the Vector Agent natively using Docker.

1. Navigate to the `vector` directory on the UTA machine:
   ```bash
   cd vector
   ```
2. Modify the `.env` parameters generated inside `install.sh` to point `KAFKA_BOOTSTRAP_SERVERS` towards the IP address of your Main Server.
3. Run the installation script which brings up the container:
   ```bash
   ./install.sh
   ```
   *(This script automatically creates the `.env` and runs `docker compose up -d`)*

To view the agent logs:
```bash
docker compose logs -f
```
