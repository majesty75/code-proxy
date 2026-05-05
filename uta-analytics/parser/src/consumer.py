"""
Kafka → ClickHouse consumer with TL_interlude block buffering.

Vector ships one Kafka message per log line. Per (server_ip, log_filename)
state holds an in-flight buffer between BEGIN/END markers; lines outside
the buffer go to log_events as raw text. On END the buffer is handed to
the block parser and the result is written to interlude_snapshots +
interlude_metrics.

Crash safety: we never advance the Kafka commit cursor past the BEGIN line
of an open block, so a mid-block crash replays cleanly. A safety cap on
buffer size / wall age prevents an unmatched BEGIN from holding offsets
forever.
"""
from __future__ import annotations

import datetime as dt
import json
import signal
import sys
import time
import uuid
from typing import Any, Optional

import structlog
from confluent_kafka import Consumer, KafkaError, TopicPartition

from config import Settings
from filename_parser import parse_filename
from parsers import block_parsers
from writer import ClickHouseWriter

log = structlog.get_logger()

MAX_BLOCK_LINES = 50_000
MAX_BLOCK_AGE_S = 30 * 60  # 30 min


class _BlockBuffer:
    __slots__ = ("parser", "lines", "first_offset", "first_partition", "opened_at_wall")

    def __init__(self, parser: Any, offset: int, partition: int):
        self.parser = parser
        self.lines: list[str] = []
        self.first_offset = offset
        self.first_partition = partition
        self.opened_at_wall = time.monotonic()


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

        # filename → cached session metadata (filename_parser output + server_ip)
        self._session_cache: dict[str, dict[str, Any]] = {}
        # (server_ip, log_filename) → open block buffer (if any)
        self._blocks: dict[tuple[str, str], _BlockBuffer] = {}
        # (server_ip, log_filename) → next block_index to assign
        self._block_index: dict[tuple[str, str], int] = {}

        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT,  self._shutdown)

    def _shutdown(self, *_):
        self.running = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self):
        log.info("consumer_started", topic=self.settings.kafka_topic)
        # batch of (msg, log_event_row) for flushing to log_events together
        log_event_batch: list[dict[str, Any]] = []
        # last fully-processed (msg) per partition — what we'll commit
        commit_msgs: dict[int, Any] = {}

        while self.running:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None:
                if log_event_batch:
                    self._flush_log_events(log_event_batch, commit_msgs)
                    log_event_batch = []
                self._gc_stale_blocks()
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("kafka_error", error=str(msg.error()))
                continue

            try:
                self._handle_message(msg, log_event_batch, commit_msgs)
            except Exception as exc:
                log.exception("message_handler_error")
                self._record_error(msg, type(exc).__name__, str(exc))

            if len(log_event_batch) >= self.settings.batch_size:
                self._flush_log_events(log_event_batch, commit_msgs)
                log_event_batch = []

        if log_event_batch:
            self._flush_log_events(log_event_batch, commit_msgs)
        self.consumer.close()
        log.info("consumer_stopped")

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------
    def _handle_message(self, msg, log_event_batch, commit_msgs):
        raw_bytes = msg.value()
        if raw_bytes is None:
            return
        try:
            value = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            self._record_error(msg, type(exc).__name__, str(exc))
            return

        # Watcher's "test_completed" event — closes the session.
        if value.get("system_event") == "test_completed":
            filename  = value.get("filename", "")
            server_ip = value.get("server_ip", "")
            if filename:
                # Drop any half-open block — the file is gone.
                self._blocks.pop((server_ip, filename), None)
                self.writer.mark_session_completed(filename, server_ip)
            self._track_commit(msg, commit_msgs)
            return

        filename  = value.get("log_filename", "")
        server_ip = value.get("server_ip", "")
        line      = value.get("line", "")
        line_no   = value.get("line_number", 0)
        if not filename:
            self._track_commit(msg, commit_msgs)
            return

        meta = self._meta_for(filename, server_ip)
        key  = (server_ip, filename)

        # Currently inside a block?
        buf = self._blocks.get(key)
        if buf is not None:
            buf.lines.append(line)
            if buf.parser.end_marker.search(line):
                self._finalise_block(buf, key, meta, msg, commit_msgs)
            elif (
                len(buf.lines) > MAX_BLOCK_LINES
                or (time.monotonic() - buf.opened_at_wall) > MAX_BLOCK_AGE_S
            ):
                self._record_error(
                    msg, "BlockBufferOverflow",
                    f"block exceeded cap ({len(buf.lines)} lines)",
                )
                self._blocks.pop(key, None)
                self._track_commit(msg, commit_msgs)
            # While the block is open we do NOT advance the commit cursor
            # past it — the BEGIN's offset is the floor.
            return

        # Not in a block — does this line OPEN one?
        opener = _find_block_opener(line)
        if opener is not None:
            buf = _BlockBuffer(opener, msg.offset(), msg.partition())
            buf.lines.append(line)
            self._blocks[key] = buf
            # Don't advance commit past this point until END is seen.
            return

        # Plain outside-block line → log_events
        log_event_batch.append({
            "server_ip":     server_ip,
            "log_filename":  filename,
            "slot_id":       meta.get("slot_id", ""),
            "line_number":   line_no,
            "raw_line":      line,
            "log_timestamp": _absolute_log_time(line, meta),
            "_msg":          msg,
        })

    # ------------------------------------------------------------------
    # Block lifecycle
    # ------------------------------------------------------------------
    def _finalise_block(self, buf: _BlockBuffer, key: tuple[str, str], meta: dict, msg, commit_msgs):
        try:
            result = buf.parser.parse(buf.lines, key[1], meta)
        except Exception as exc:
            log.exception("block_parse_error", file=key[1])
            self._record_error(msg, type(exc).__name__, str(exc))
            self._blocks.pop(key, None)
            self._track_commit(msg, commit_msgs)
            return

        snapshot = result.get("snapshot") or {}
        metrics  = result.get("metrics") or []

        idx = self._block_index.get(key, 0)
        self._block_index[key] = idx + 1

        # Pad in identifiers + denormalised filename metadata before insert.
        snapshot.setdefault("snapshot_id", str(uuid.uuid4()))
        snapshot["log_filename"] = key[1]
        snapshot["server_ip"]    = key[0]
        snapshot["slot_id"]      = meta.get("slot_id", "")
        snapshot["rack"]         = meta.get("rack", 0)
        snapshot["shelf"]        = meta.get("shelf", 0)
        snapshot["slot"]         = meta.get("slot", 0)
        snapshot["block_index"]  = idx
        if snapshot.get("block_started_at") is None:
            snapshot["block_started_at"] = meta.get("started_at") or dt.datetime.utcnow()

        try:
            self.writer.write_interlude_snapshot(snapshot)
        except Exception as exc:
            log.exception("snapshot_insert_error")
            self._record_error(msg, type(exc).__name__, str(exc))
            self._blocks.pop(key, None)
            self._track_commit(msg, commit_msgs)
            return

        # Sidecar metrics — fan out the long-form rows.
        if metrics:
            metric_rows = [
                {
                    "snapshot_id":      snapshot["snapshot_id"],
                    "log_filename":     key[1],
                    "server_ip":        key[0],
                    "slot_id":          meta.get("slot_id", ""),
                    "block_started_at": snapshot["block_started_at"],
                    "block_index":      idx,
                    "section":          m.get("section", ""),
                    "key":              m.get("key", ""),
                    "value_num":        m.get("value_num"),
                    "value_str":        m.get("value_str", ""),
                    "unit":             m.get("unit", ""),
                }
                for m in metrics
            ]
            try:
                self.writer.write_interlude_metrics(metric_rows)
            except Exception:
                log.exception("metrics_insert_error")

        # Refresh master row aggregates.
        try:
            self.writer.bump_session_after_snapshot(
                key[1], key[0],
                block_started_at=snapshot["block_started_at"],
                had_failure=(snapshot.get("block_status") == "FAILED"),
            )
        except Exception:
            log.exception("session_bump_error")

        self._blocks.pop(key, None)
        self._track_commit(msg, commit_msgs)
        # END's offset is now safe — but commit happens after the next
        # log_events flush so partition cursors stay consistent.
        self._safe_commit(commit_msgs)

    def _gc_stale_blocks(self):
        """Drop block buffers whose openers are older than the safety cap."""
        now = time.monotonic()
        for key, buf in list(self._blocks.items()):
            if (now - buf.opened_at_wall) > MAX_BLOCK_AGE_S:
                log.warning("block_buffer_gc", file=key[1], lines=len(buf.lines))
                self._blocks.pop(key, None)

    # ------------------------------------------------------------------
    # Session metadata helper
    # ------------------------------------------------------------------
    def _meta_for(self, filename: str, server_ip: str) -> dict[str, Any]:
        if filename in self._session_cache:
            return self._session_cache[filename]
        meta = parse_filename(filename)
        meta["server_ip"] = server_ip
        try:
            self.writer.upsert_session(meta)
        except Exception:
            log.exception("upsert_session_failed", file=filename)
        self._session_cache[filename] = meta
        return meta

    # ------------------------------------------------------------------
    # Flush / commit
    # ------------------------------------------------------------------
    def _flush_log_events(self, batch: list[dict[str, Any]], commit_msgs: dict[int, Any]):
        max_retries = self.settings.flush_max_retries
        max_sleep   = self.settings.flush_retry_max_sleep
        rows = [{k: v for k, v in r.items() if k != "_msg"} for r in batch]
        for attempt in range(1, max_retries + 1):
            try:
                self.writer.write_log_events(rows)
                # Track commit floor per partition (highest fully-processed)
                for r in batch:
                    self._track_commit(r["_msg"], commit_msgs)
                self._safe_commit(commit_msgs)
                log.info("log_events_flushed", count=len(batch))
                return
            except Exception as exc:
                if attempt >= max_retries:
                    log.error(
                        "log_events_flush_failed",
                        count=len(batch), attempts=attempt, error=str(exc),
                    )
                    sys.exit(1)
                sleep_secs = min(2 ** (attempt - 1), max_sleep)
                log.warning("log_events_flush_retry", attempt=attempt, sleep_secs=sleep_secs, error=str(exc))
                time.sleep(sleep_secs)

    def _track_commit(self, msg, commit_msgs):
        commit_msgs[msg.partition()] = msg

    def _safe_commit(self, commit_msgs: dict[int, Any]):
        """
        Commit the highest fully-processed offset per partition. We must NOT
        advance past the BEGIN of any partition that still has an open block.
        """
        if not commit_msgs:
            return
        floors: dict[int, int] = {}
        for buf in self._blocks.values():
            cur = floors.get(buf.first_partition)
            if cur is None or buf.first_offset < cur:
                floors[buf.first_partition] = buf.first_offset

        tps: list[TopicPartition] = []
        for part, msg in commit_msgs.items():
            offset = msg.offset() + 1
            floor = floors.get(part)
            if floor is not None and offset > floor:
                offset = floor
            tps.append(TopicPartition(msg.topic(), part, offset))

        try:
            self.consumer.commit(offsets=tps, asynchronous=False)
        except Exception:
            log.exception("kafka_commit_failed")

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------
    def _record_error(self, msg, error_type: str, error_message: str):
        raw = msg.value().decode("utf-8", errors="replace") if msg.value() else ""
        filename = ""
        try:
            filename = json.loads(raw).get("log_filename", "")
        except Exception:
            pass
        self.writer.write_parse_error(
            raw_message=raw,
            filename=filename,
            error_type=error_type,
            error_message=error_message,
        )


def _find_block_opener(line: str):
    for bp in block_parsers():
        if bp.begin_marker.search(line):
            return bp
    return None


def _absolute_log_time(line: str, meta: dict[str, Any]) -> Optional[dt.datetime]:
    """Convert a leading 'HHHH:MM:SS ' prefix into an absolute timestamp."""
    started = meta.get("started_at")
    if not isinstance(started, dt.datetime):
        return None
    import re
    m = re.match(r"^\s*(\d+):(\d{2}):(\d{2})(?:\.(\d+))?\s", line)
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    frac = float("0." + m.group(4)) if m.group(4) else 0.0
    return started + dt.timedelta(hours=h, minutes=mi, seconds=s + frac)
