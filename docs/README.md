# UTA Test-Log Analytics — Documentation Index

## Documentation Structure

### [`poc/`](./poc/) — Proof of Concept
Minimal viable pipeline: **1 server, 1 board → structured data in Grafana**.
Target: build in 1–2 weeks. Same tech foundations as production system.

| Chapter | Description |
|---------|-------------|
| [01-overview](./poc/01-overview.md) | Scope, success criteria, deferred items |
| [02-architecture](./poc/02-architecture.md) | Diagrams, data flow, component interaction |
| [03-tech-stack](./poc/03-tech-stack.md) | Technologies, versions, licenses |
| [04-folder-structure](./poc/04-folder-structure.md) | Repository layout with file descriptions |
| [05-implementation](./poc/05-implementation.md) | Component-by-component build guide with code/config |
| [06-deployment](./poc/06-deployment.md) | Docker Compose, startup, verification |
| [07-plan-and-decisions](./poc/07-plan-and-decisions.md) | Active plan: §5 fixes landed, parser roadmap, monitoring tiers, ML staging |
| [08-wsl-windows-setup](./poc/08-wsl-windows-setup.md) | WSL2 + Windows topology, bootstrap, simulator usage |
| [09-backfill-existing-logs](./poc/09-backfill-existing-logs.md) | One-shot import of historical GBs without going through Kafka |

### [`system/`](./system/) — Production System
Full distributed system: **10+ servers, 150+ boards, hot/cold storage, AI/ML-ready**.

| Chapter | Description |
|---------|-------------|
| [01-srs](./system/01-srs.md) | Software Requirements Specification |
| [02-architecture](./system/02-architecture.md) | System diagrams (context, data flow, deployment) |
| [03-tech-stack](./system/03-tech-stack.md) | Full tech stack with justifications |
| [04-folder-structure](./system/04-folder-structure.md) | Multi-service repository layout |
| [05-data-model](./system/05-data-model.md) | ClickHouse schemas, Kafka topics, data dictionary |
| [06-parser-framework](./system/06-parser-framework.md) | Plug-and-play parser plugin architecture |
| [07-implementation](./system/07-implementation.md) | Flink jobs, multi-server orchestration |
| [08-deployment](./system/08-deployment.md) | Kubernetes / Docker Swarm deployment |
| [09-storage-strategy](./system/09-storage-strategy.md) | Hot/cold tiered storage design |
| [10-observability](./system/10-observability.md) | Monitoring, alerting, health checks |

### Legacy Reference
| File | Description |
|------|-------------|
| [plan.md](./plan.md) | Original project plan (reference only) |
| [architecture.md](./architecture.md) | Original architecture notes (reference only) |
| [system.md](./system.md) | Original system description (reference only) |
| [log-naming.md](./log-naming.md) | Log filename convention (active reference) |

## Key Principle
**POC is a strict subset of SYSTEM.** All POC code is designed to be extended into the full system without rewrite. The parser interface, data model, and folder structure are forward-compatible.
