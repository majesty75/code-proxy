"""Dump agent (rack side): watch for completed bank-file groups, package each
into one container, put it in the NATS Object Store, and publish a dump event.

Completeness: a group is processed once all its .bank files have been stable
(unmodified) for STABLE_SECONDS — no partial reads. After publishing, the bank
files are deleted.

It does NOT enrich (no UTA dependency here): the decode service does the UTA
SQLite lookup + AXF routing. The event carries only what the rack host knows.
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import nats

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.dump_agent.config import Config              # noqa: E402
from services.dump_agent.packager import scan_groups, package  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dump_agent")

STAGING = "/tmp/axf_staging"


def group_stable(group, stable_seconds):
    now = time.time()
    return all(now - path.stat().st_mtime >= stable_seconds
               for _, path in group["banks"])


async def run():
    cfg = Config
    os.makedirs(STAGING, exist_ok=True)
    nc = await nats.connect(cfg.NATS_URL, reconnect_time_wait=2, max_reconnect_attempts=-1)
    js = nc.jetstream()
    obj_store = None
    for _ in range(15):                       # tolerate startup race with decode_service
        try:
            obj_store = await js.object_store(cfg.NATS_OBJ_BUCKET)
            break
        except Exception:
            try:
                obj_store = await js.create_object_store(cfg.NATS_OBJ_BUCKET)
                break
            except Exception:
                await asyncio.sleep(2)
    if obj_store is None:
        raise RuntimeError("object store unavailable")
    log.info("dump_agent up; watching %s", cfg.WATCH_DIR)

    seen = set()
    while True:
        for gid, group in scan_groups(cfg.WATCH_DIR).items():
            if gid in seen or not group.get("banks"):
                continue
            if not group_stable(group, cfg.STABLE_SECONDS):
                continue
            try:
                object_key, out_path, meta = package(group, STAGING)
                # 1) object first, then event (consumer fetches object on event)
                await obj_store.put(object_key, out_path.read_bytes())
                event = {
                    "schema_version": 1,
                    "object_key": object_key,
                    "boardname": meta["boardname"],
                    "core": meta["core"],
                    "dump_timestamp": meta["dump_timestamp"],
                    "server_ip": cfg.SERVER_IP,
                }
                subject = f"uta.axf.dump.{meta['core']}.{meta['boardname']}"
                await js.publish(subject, json.dumps(event).encode())
                log.info("published %s (%d banks)", object_key, len(group["banks"]))
                for bp in meta["bank_paths"]:
                    try:
                        os.remove(bp)
                    except OSError:
                        pass
                out_path.unlink(missing_ok=True)
                seen.add(gid)
            except Exception:
                log.exception("failed to process group %s; will retry", gid)
        if len(seen) > 5000:
            seen.clear()
        await asyncio.sleep(cfg.POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())
