# POC — Overview

## Goal
Prove the end-to-end log analytics pipeline works for **1 UTA server, 1 board**.
A log line written to disk on the UTA server must appear as structured, queryable data in a Grafana dashboard within seconds.

## Success Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | Log lines from a single board are tailed in real-time | `echo "test" >> /uta/UTA_FULL_Logs/sample.log` appears in Kafka within 2s |
| 2 | Log filename metadata is extracted | ClickHouse row contains `platform`, `firmware_version`, `slot_id` from filename |
| 3 | Log content is parsed by a pluggable parser | `parsed` map column contains extracted key-value pairs |
| 4 | Data is queryable in Grafana | Dashboard shows live test events, filterable by slot/platform/firmware |
| 5 | Parser is swappable without pipeline restart | Drop a new `.py` file → consumer picks it up on next restart |

## Scope

### In Scope
- Vector agent on UTA server (Linux) tailing one log directory
- Single-broker Kafka (KRaft mode) on main server (WSL2/Docker)
- Python consumer service that reads from Kafka, parses, writes to ClickHouse
- Single-node ClickHouse
- Grafana with pre-provisioned dashboard
- One default parser (regex-based, extracts timestamps + key-value pairs)
- Docker Compose deployment on WSL2

### Out of Scope (deferred to SYSTEM)
- Multi-server / multi-board scaling
- Apache Flink (replaced by simple Python consumer in POC)
- Apache Superset (BI layer)
- AI/ML (MLflow, model serving)
- Hot/cold storage tiering
- RBAC / authentication
- Log backup directory watching
- Auto-discovery of UTA servers
- CI/CD pipeline
- Monitoring / alerting (Prometheus)
- Kubernetes deployment

## Timeline Estimate
| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Infrastructure setup | 2 days | Docker Compose running all services |
| Vector + Kafka integration | 1 day | Log lines flowing into Kafka topic |
| Parser + ClickHouse | 2 days | Parsed data in ClickHouse tables |
| Grafana dashboards | 1 day | Working dashboard with filters |
| Testing + polish | 1 day | End-to-end demo |
| **Total** | **~7 days** | |

## Prerequisites
- UTA server (Linux) with network access to main server
- Main server (Windows) with WSL2 + Docker Desktop installed
- Log files present in `/uta/UTA_FULL_Logs/` on UTA server
- Network port access: Kafka (9092), ClickHouse (8123, 9000), Grafana (3000)
