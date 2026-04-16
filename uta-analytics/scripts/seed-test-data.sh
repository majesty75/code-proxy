#!/bin/bash
# Generate fake log data directly to Kafka for testing without a real UTA server

TOPIC="raw-logs"
BOOTSTRAP="localhost:9092"
FILENAME="R7S4-12_20260414_163815_EXEC_AA2_SIRIUS_UFS_3_1_V8_TLC_1Tb_SAMSUNG_512GB_P00_RC16_FW04_Rack7_Sai_Revathi_Qual_UFS.log"

for i in $(seq 1 100); do
  SEVERITY=$(shuf -e INFO INFO INFO INFO WARN ERROR -n 1)
  MSG="16:38:${i} [$SEVERITY] Test TC_00${i} sequential_read_128K IOPS=120000 latency_us=45"
  echo "{\"server_ip\":\"192.168.1.10\",\"log_filename\":\"${FILENAME}\",\"line\":\"${MSG}\",\"line_number\":${i}}" | \
    docker compose exec -T kafka kafka-console-producer.sh --bootstrap-server localhost:9092 --topic ${TOPIC}
  sleep 0.1
done

echo "✅ Sent 100 test messages to Kafka topic '${TOPIC}'"
