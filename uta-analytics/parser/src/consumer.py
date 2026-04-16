import json
import signal
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
            "auto.offset.reset": "latest",
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

            try:
                value = json.loads(msg.value().decode("utf-8"))
                row = self._process(value)
                batch.append(row)
            except Exception:
                log.exception("parse_error", raw=msg.value())

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

        return {
            "server_ip": server_ip,
            "slot_id": meta.get("slot_id", ""),
            "log_filename": filename,
            "line_number": msg.get("line_number", 0),
            "raw_line": line,
            "parsed": parsed,
            "log_timestamp": parsed.get("log_time"),
            "platform": meta.get("platform", ""),
            "firmware_version": meta.get("firmware_version", ""),
            "execution_type": meta.get("execution_type", ""),
            "project": meta.get("project", ""),
        }

    def _flush(self, batch: list[dict]):
        try:
            self.writer.write_events(batch)
            self.consumer.commit()
            log.info("batch_flushed", count=len(batch))
        except Exception:
            log.exception("flush_error", count=len(batch))
