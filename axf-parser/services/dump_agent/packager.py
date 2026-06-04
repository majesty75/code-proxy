"""Group a core's per-bank dump files into one container object.

PRACTICE writes each bank to:  <slot>_<core>_<YYYYMMDD>_<HHMMSS>_<base08x>.bank
This groups by (slot, core, timestamp), reads each bank's base from its filename,
and packs them into one UTAX container. No layout is needed on the rack side.
"""
import re
from collections import defaultdict
from pathlib import Path

from core.container import write_container

BANK_RE = re.compile(
    r"^(?P<slot>R\d+S\d+-\d+)_(?P<core>[A-Za-z0-9]+)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})_(?P<base>[0-9a-fA-F]{8})\.bank$"
)


def scan_groups(watch_dir):
    """Return {group_id: {slot, core, date, time, banks:[(base,path)]}}."""
    groups = defaultdict(lambda: {"banks": []})
    for p in Path(watch_dir).glob("*.bank"):
        m = BANK_RE.match(p.name)
        if not m:
            continue
        gid = f"{m['slot']}_{m['core']}_{m['date']}_{m['time']}"
        g = groups[gid]
        g.update(slot=m["slot"], core=m["core"], date=m["date"], time=m["time"])
        g["banks"].append((int(m["base"], 16), p))
    return groups


def package(group, out_dir):
    """Write one container for a group; return (object_key, out_path, meta)."""
    slot, core = group["slot"], group["core"]
    date, time = group["date"], group["time"]
    banks = sorted(group["banks"])
    payload = [(base, path.read_bytes()) for base, path in banks]
    object_key = f"{slot}_{core}_{date}_{time}.bin"
    out_path = Path(out_dir) / object_key
    ts = f"{date[0:4]}-{date[4:6]}-{date[6:8]}T{time[0:2]}:{time[2:4]}:{time[4:6]}"
    write_container(str(out_path), core, payload, created=ts)
    meta = {
        "object_key": object_key,
        "boardname": slot,
        "core": core,
        "dump_timestamp": ts,
        "bank_paths": [str(path) for _, path in banks],
    }
    return object_key, out_path, meta
