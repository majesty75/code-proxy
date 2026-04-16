# UTA Test-Log Analytics & Visualization Architecture

Based on your requirements and the provided architecture document, I can see that the architecture.md is highly relevant to your use case. Let me summarize how it addresses your specific needs:

---

## ✅ How the Architecture Meets Your Requirements

### 1. Real-Time Test Monitoring

The system uses **Vector** as a file watcher on each UTA server that tails logs in real-time from `\\server_ip\uta\UTA_FULL_Logs\*.log` and sends chunks to Kafka. This enables live monitoring of tests as they run. [architecture.md - Section 2]

### 2. Big Data Capabilities & Historical Comparison

The architecture uses **ClickHouse** as the analytical store - a columnar, time-series database optimized for ad-hoc analytics on billions of rows. This allows you to:

- Compare current test results with previous FW versions
- Compare across different products
- Run complex queries on historical data [architecture.md - Section 5]

### 3. Handling Large Log Files

Since you cannot send entire logs over the internet, the system sends **log chunks** in real-time via Vector. The logs are parsed on the main server, and only structured data (not raw logs) is stored in ClickHouse. This dramatically reduces bandwidth requirements. [architecture.md - Section 2, Section 4]

### 4. Unstructured Log Parsing

The architecture includes a **plug-and-play Python parser layer** that can handle heterogeneous, unstructured logs. You can create different parsers for different log formats without rewriting the pipeline. [architecture.md - Section 3]

---

## 📊 Proposed System Architecture

```
+-------------------+     +--------------+     +----------------+     +----------------+
|  Vector (edge)    | --> |   Kafka      | --> |   Flink (Py)   | --> | ClickHouse      |
|  (file watcher)   |     | (raw logs)   |     | (parser)       |     | (structured)    |
+-------------------+     +--------------+     +----------------+     +----------------+
                                           |
                                           v
                                    +--------------+
                                    |   Grafana    |  <-- Real-time dashboards
                                    +--------------+
                              +-------------------+
                              |   Superset (BI)   |  <-- Historical analysis
                              +-------------------+
                              |
                              ▼
                         MLflow / Seldon (AI)
```

---

## 🔑 Key Components

| Component                  | Purpose                    | Why It's Suitable                                                                                |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------ |
| **Vector**                 | File watcher on UTA server | Low-CPU, runs as Windows service, sends chunks in real-time [architecture.md - Section 2]        |
| **Apache Kafka**           | Message broker             | Durable, ordered, at-least-once delivery, partitioned by server_ip [architecture.md - Section 2] |
| **Apache Flink (PyFlink)** | Stream processor & parser  | Exactly-once semantics, dynamic parser loading [architecture.md - Section 3, 4]                  |
| **ClickHouse**             | Analytical database        | Columnar, time-series optimized, handles billions of rows [architecture.md - Section 5]          |
| **Grafana**                | Real-time visualization    | Live dashboards for test status [architecture.md - Section 6.1]                                  |
| **Superset**               | Historical BI              | Drill-down, multi-FW comparison [architecture.md - Section 6.2]                                  |
| **MLflow + Seldon**        | AI/ML                      | Anomaly detection, failure prediction [architecture.md - Section 7]                              |

---

## 📁 Log Naming Convention

Based on the test_log_naming_convention.md, your log files follow a structured naming pattern like:

```
R7S4-12_20260414_163815_EXEC_AA2_SIRIUS_UFS_3_1_V8_TLC_1Tb_SAMSUNG_512GB_P00_RC16_FW04_Rack7_Sai_Revathi_Qual_UFS
```

This includes:

- **Slot Identifier**: R7S4-12 (Rack 7, Shelf 4, Slot 12)
- **Timestamp**: 20260414_163815
- **Execution Type**: EXEC, RETEST, DEBUG, SMOKE
- **Product/Platform**: SIRIUS
- **Interface**: UFS_3_1
- **Firmware**: V8, RC16, FW04
- **Engineers**: Sai_Revathi
- **Test Purpose**: Qual_UFS

This structured naming can be leveraged in the parser to extract metadata automatically! [test_log_naming_convention.md]

---

## 🚀 Next Steps

Would you like me to provide any of the following?

1. **Full Dockerfile** for the Flink job (including parser package)
2. **Example Grafana dashboard** JSON export
3. **Terraform scripts** for the whole stack
4. **Vector configuration** specific to your Windows UTA servers
5. **ClickHouse table schema** optimized for your log format

Let me know which artifact you need, and I'll provide the exact code! 🚀
