#!/usr/bin/env python3
"""Demo: synthesize per-bank .bank files in the dropzone from an AXF image,
exactly as PRACTICE would, so the dump_agent -> NATS -> decode_service pipeline
runs with no hardware.

    python -m tools.seed_dropzone <firmware.axf> <layout.json> \
        --slot R7S1-01 --dropzone ./dropzone
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import dwarf_layout                       # noqa: E402
from tools.elf_to_container import read_image       # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("axf")
    ap.add_argument("layout")
    ap.add_argument("--slot", default="R7S1-01")
    ap.add_argument("--dropzone", default="./dropzone")
    ap.add_argument("--date", default="20250101")
    ap.add_argument("--time", default="120000")
    args = ap.parse_args()

    layout = json.loads(Path(args.layout).read_text())
    core = layout.get("core", "M")
    elf, _ = dwarf_layout.open_axf(args.axf)
    dz = Path(args.dropzone)
    dz.mkdir(parents=True, exist_ok=True)
    for s in layout["segments"]:
        data = read_image(elf, s["base"], s["size"])
        name = f"{args.slot}_{core}_{args.date}_{args.time}_{s['base']:08x}.bank"
        (dz / name).write_bytes(data)
        print(f"wrote {name} ({len(data)} B)")
    print(f"\nseeded {len(layout['segments'])} banks into {dz}/ for slot {args.slot} core {core}")


if __name__ == "__main__":
    main()
