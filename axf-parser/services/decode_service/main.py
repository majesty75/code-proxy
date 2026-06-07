"""Decode service: consume dump events from NATS JetStream, decode against the
matching AXF layout, write results to ClickHouse.

Per message (no step skipped):
  1. parse event JSON               -> BAD_EVENT
  2. fetch the container object      -> NAK (retry; object may land after event)
  3. UTA lookup trname/fwname/start  -> ENRICH_ERROR
  4. parse fwname -> product+hash; registry.get -> NO_LAYOUT / HASH_MISMATCH
  5. decode_all                      -> DECODE_FAIL (whole bin unreadable)
  6. elapsed_s = dump_ts - start
  7. flatten + curated select
  8. write snapshot + metrics + session, then ack
Fatal data problems are written to axf_decode_errors and acked (no poison loop).
"""
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

import nats

sys.path.insert(0, "/app")          # core + services importable in the container
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.decode import Memory, decode_all              # noqa: E402
from core.flatten import flatten                        # noqa: E402
from core.fw_name import parse_fw_name                  # noqa: E402
from services.decode_service.config import Config       # noqa: E402
from services.decode_service.layout_registry import LayoutRegistry   # noqa: E402
from services.decode_service.uta_lookup import UtaLookup            # noqa: E402
from services.decode_service.variable_registry import VariableRegistry  # noqa: E402
from services.decode_service.ch_writer import ClickHouseWriter         # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("decode_service")


class Fatal(Exception):
    def __init__(self, error_type, msg):
        self.error_type, self.msg = error_type, msg


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


async def process_one(msg, obj_store, registry, uta, varreg, writer, cfg):
    try:
        ev = json.loads(msg.data.decode())
    except Exception as e:
        raise Fatal("BAD_EVENT", f"json: {e}")
    object_key = ev.get("object_key", "")
    boardname = ev.get("boardname", "")
    core = ev.get("core", "")
    if not object_key or not boardname or not core:
        raise Fatal("BAD_EVENT", f"missing fields: {ev}")

    # 2. fetch object (retry if not yet present)
    try:
        res = await obj_store.get(object_key)
        raw = res.data
    except Exception as e:
        log.warning("object %s not ready (%s); NAK", object_key, e)
        await msg.nak()
        return

    # 3. UTA runtime facts
    facts, err = uta.get(boardname)
    if err:
        # demo fallback: allow facts in the event itself
        if ev.get("trname") and ev.get("fw_name"):
            facts = {"trname": ev["trname"], "fw_name": ev["fw_name"],
                     "test_started_at": ev.get("test_started_at")}
        else:
            raise Fatal("ENRICH_ERROR", err)

    fw = parse_fw_name(facts["fw_name"])
    product, build_hash = fw["product"], fw["fw_build_hash"]
    if not build_hash:
        raise Fatal("ENRICH_ERROR", f"no build hash in fwname {facts['fw_name']}")

    # 4. layout
    layout, lerr = registry.get(product, core, build_hash)
    if lerr:
        raise Fatal(lerr, f"{product}_{core}_{build_hash}")

    # 5. decode
    mem = Memory.from_container_bytes(raw)
    decoded, errors, status = decode_all(layout, mem, layout.get("sources"),
                                         cfg.MAX_DEREF_DEPTH)
    if status == "FAILED":
        raise Fatal("DECODE_FAIL", "no variables decoded (bad/empty dump)")

    # 6. elapsed
    dump_dt = _parse_dt(ev.get("dump_timestamp"))
    start_dt = _parse_dt(facts.get("test_started_at"))
    elapsed = 0.0
    if dump_dt and start_dt:
        elapsed = max(0.0, (dump_dt - start_dt).total_seconds())
    elif status == "OK":
        status = "PARTIAL"

    # 7. curated
    leaves = flatten(decoded)
    curated = varreg.select(product, core, leaves)

    snap = {
        "snapshot_id": str(uuid.uuid4()),
        "trname": facts["trname"], "boardname": boardname, "core": core,
        "product": product, "product_version": fw["product_version"],
        "fw_name": facts["fw_name"], "fw_build_hash": build_hash,
        "nand_type": fw["nand_type"], "nand_density": fw["nand_density"],
        "dump_timestamp": dump_dt or datetime.utcnow(),
        "test_started_at": start_dt,
        "elapsed_s": elapsed,
        "layout_key": registry.key(product, core, build_hash),
        "object_key": object_key,
        "decoded_json": json.dumps(decoded, separators=(",", ":")),
        "decode_status": status, "decode_error_cnt": errors,
    }

    # 8. write
    writer.write_snapshot(snap)
    writer.write_metrics(snap, curated)
    writer.upsert_session(snap)
    await msg.ack()
    log.info("decoded %s board=%s core=%s leaves=%d curated=%d status=%s elapsed=%.0fs",
             object_key, boardname, core, len(leaves), len(curated), status, elapsed)


async def ensure_jetstream(js, cfg):
    """Create stream, durable pull consumer, and object store if absent."""
    from nats.js.api import ConsumerConfig, AckPolicy
    try:
        await js.add_stream(name=cfg.NATS_STREAM, subjects=["uta.axf.dump.>"])
    except Exception as e:
        log.info("stream: %s", e)
    try:
        await js.add_consumer(cfg.NATS_STREAM, ConsumerConfig(
            durable_name=cfg.NATS_CONSUMER, ack_policy=AckPolicy.EXPLICIT,
            ack_wait=120, max_deliver=5, filter_subject="uta.axf.dump.>"))
    except Exception as e:
        log.info("consumer: %s", e)
    try:
        await js.create_object_store(cfg.NATS_OBJ_BUCKET)
    except Exception as e:
        log.info("objstore: %s", e)


async def run():
    cfg = Config
    from core.transforms import load as load_transforms
    registry = LayoutRegistry(cfg.LAYOUTS_DIR)
    uta = UtaLookup(cfg.UTA_SQLITE)
    transforms = load_transforms(cfg.TRANSFORMS_PY)
    varreg = VariableRegistry(cfg.VARIABLES_YAML, transforms)
    log.info("loaded %d transforms", len(transforms))
    writer = ClickHouseWriter(cfg)

    nc = await nats.connect(cfg.NATS_URL, reconnect_time_wait=2,
                            max_reconnect_attempts=-1)
    js = nc.jetstream()
    await ensure_jetstream(js, cfg)
    obj_store = await js.object_store(cfg.NATS_OBJ_BUCKET)
    sub = await js.pull_subscribe_bind(cfg.NATS_CONSUMER, stream=cfg.NATS_STREAM)
    log.info("decode_service up; consuming %s/%s", cfg.NATS_STREAM, cfg.NATS_CONSUMER)

    while True:
        try:
            msgs = await sub.fetch(batch=cfg.FETCH_BATCH, timeout=5)
        except (nats.errors.TimeoutError, asyncio.TimeoutError):
            continue
        for msg in msgs:
            try:
                await process_one(msg, obj_store, registry, uta, varreg, writer, cfg)
            except Fatal as f:
                log.error("fatal %s: %s", f.error_type, f.msg)
                try:
                    ev = json.loads(msg.data.decode())
                except Exception:
                    ev = {}
                writer.write_error(ev.get("object_key", ""), ev.get("boardname", ""),
                                   ev.get("core", ""), "", f.error_type, f.msg)
                await msg.ack()
            except Exception as e:
                log.exception("transient error; NAK: %s", e)
                await msg.nak()


if __name__ == "__main__":
    asyncio.run(run())
