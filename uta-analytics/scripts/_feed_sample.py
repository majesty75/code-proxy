import json
from kafka import KafkaProducer
LOG_PATH = "/sample.log"
FILENAME = "R7S3-09_20260420_195330_RESERVATION_AA2_SIRIUS_UFS_3_1_V8_TLC_512Gb_GEN1_256GB_P09_RC00_FW00_Rack7_Sharath_Aditi_Qual_UFS.log"
producer = KafkaProducer(bootstrap_servers="kafka:9092",
                        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                        linger_ms=100)
n = 0
with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
    for i, line in enumerate(f, start=1):
        line = line.rstrip("\n")
        if not line.strip():
            continue
        producer.send("raw-logs", value={"server_ip": "192.168.1.10",
                                         "log_filename": FILENAME,
                                         "line": line,
                                         "line_number": i})
        n += 1
producer.send("raw-logs", value={"system_event": "test_completed",
                                  "filename": FILENAME,
                                  "server_ip": "192.168.1.10"})
producer.flush()
producer.close()
print(f"Sent {n} log lines + 1 completion event")
