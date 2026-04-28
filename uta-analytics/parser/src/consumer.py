import json
import signal
import sys
import time
import structlog
from confluent_kafka import Consumer, KafkaError
from parsers import get_parser
from filename_parser import parse_filename
from writer import ClickHouseWriter
from config import Settings

log = structlog.get_logger()


class LogConsumer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.running = True
        self.writer = ClickHouseWriter(settings)
        self.consumer = Consumer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": "uta-parser",
            "auto.offset.reset": settings.kafka_offset_reset,
            "enable.auto.commit": False,
            "max.poll.interval.ms": 300000,
        })
        self.consumer.subscribe([settings.kafka_topic])
        self._session_cache: dict[str, dict] = {}
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, *_):
        self.running = False

    def run(self):
        log.info("consumer_started", topic=self.settings.kafka_topic)
        batch: list[dict] = []
        while self.running:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None:
                if batch:
                    self._flush(batch)
                    batch = []
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("kafka_error", error=str(msg.error()))
                continue

            raw_bytes = msg.value()
            value: dict | None = None
            try:
                value = json.loads(raw_bytes.decode("utf-8"))

                if value.get("system_event") == "test_completed":
                    filename = value.get("filename", "")
                    server_ip = value.get("server_ip", "")
                    if filename:
                        log.info("test_completed_event", filename=filename)
                        self.writer.mark_session_completed(filename, server_ip)
                    continue

                row = self._process(value)
                batch.append(row)
            except Exception as exc:
                log.exception("parse_error")
                raw_str = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""
                filename = value.get("log_filename", "") if isinstance(value, dict) else ""
                self.writer.write_parse_error(
                    raw_message=raw_str,
                    filename=filename,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

            if len(batch) >= self.settings.batch_size:
                self._flush(batch)
                batch = []

        # Final flush
        if batch:
            self._flush(batch)
        self.consumer.close()
        log.info("consumer_stopped")

    def _process(self, msg: dict) -> dict:
        filename = msg.get("log_filename", "")
        line = msg.get("line", "")
        server_ip = msg.get("server_ip", "")

        # Parse filename metadata (cached per filename)
        if filename not in self._session_cache:
            meta = parse_filename(filename)
            meta["server_ip"] = server_ip
            self._session_cache[filename] = meta
            self.writer.upsert_session(meta)

        meta = self._session_cache[filename]

        # Select parser and parse line
        parser = get_parser(line, filename)
        parsed = parser.parse(line, filename)

        # Convert relative time to absolute time
        log_time_str = parsed.get("log_time")
        log_timestamp = None
        if log_time_str and "started_at" in meta:
            try:
                parts = log_time_str.split(":")
                if len(parts) == 3:
                    import datetime
                    hours, minutes, seconds = parts
                    delta = datetime.timedelta(hours=int(hours), minutes=int(minutes), seconds=float(seconds))
                    log_timestamp = meta["started_at"] + delta
            except Exception:
                pass

        return {
            "server_ip": server_ip,
            "slot_id": meta.get("slot_id", ""),
            "log_filename": filename,
            "line_number": msg.get("line_number", 0),
            "raw_line": line,
            "parsed": parsed,
            "log_timestamp": log_timestamp,
            "platform": meta.get("platform", ""),
            "firmware_version": meta.get("firmware_version", ""),
            "execution_type": meta.get("execution_type", ""),
            "project": meta.get("project", ""),
            "interface": meta.get("interface", ""),
            "fw_arch": meta.get("fw_arch", ""),
            "nand_type": meta.get("nand_type", ""),
            "nand_density": meta.get("nand_density", ""),
            "manufacturer": meta.get("manufacturer", ""),
            "package_density": meta.get("package_density", ""),
            "production_step": meta.get("production_step", ""),
            "release_candidate": meta.get("release_candidate", ""),
            "rack": meta.get("rack", 0),
            "test_purpose": meta.get("test_purpose", ""),
            "storage_type": meta.get("storage_type", ""),
        }

    def _flush(self, batch: list[dict]):
        """
        Write a batch to ClickHouse and commit Kafka offsets only on success.
        Retries with exponential backoff. On permanent failure, exits the
        process so Docker restarts it and Kafka replays the unflushed batch
        from the last committed offset.
        """
        max_retries = self.settings.flush_max_retries
        max_sleep = self.settings.flush_retry_max_sleep
        for attempt in range(1, max_retries + 1):
            try:
                self.writer.write_events(batch)
                self.consumer.commit()
                log.info("batch_flushed", count=len(batch))
                return
            except Exception as exc:
                if attempt >= max_retries:
                    log.error(
                        "flush_failed_giving_up",
                        count=len(batch),
                        attempts=attempt,
                        error=str(exc),
                    )
                    # Exit non-zero so Docker `restart: unless-stopped` brings us
                    # back. Kafka will redeliver from the last committed offset.
                    sys.exit(1)
                sleep_secs = min(2 ** (attempt - 1), max_sleep)
                log.warning(
                    "flush_retry",
                    attempt=attempt,
                    sleep_secs=sleep_secs,
                    error=str(exc),
                )
                time.sleep(sleep_secs)
