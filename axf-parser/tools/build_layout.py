#!/usr/bin/env python3
"""Register an AXF into the layout registry. Run ONCE per firmware build.

Parses DWARF -> types + global addresses, derives the HW-dump segment map,
parses firmware metadata from the AXF name (or --fw-name), and writes one
self-contained layout.json keyed by build hash into config/layouts/.

    python -m tools.build_layout firmware.axf --core H [--fw-name NAME] [--out DIR]

The output file name is the registry key:
    <product>_<core>_<build_hash>.json
The decode service loads layouts by exactly this triple.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import dwarf_layout, segments          # noqa: E402
from core.fw_name import parse_fw_name            # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "config" / "layouts"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("axf")
    ap.add_argument("--core", required=True, help="core tag, e.g. H F M N")
    ap.add_argument("--fw-name", help="firmware name (defaults to the AXF file stem)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    axf = Path(args.axf)
    fw = parse_fw_name(args.fw_name or axf.stem)
    if not fw["fw_build_hash"]:
        print(f"!! no build hash parsed from '{args.fw_name or axf.stem}'. "
              f"Pass --fw-name with the real firmware name.", file=sys.stderr)

    elf, dwarf = dwarf_layout.open_axf(str(axf))
    layout = dwarf_layout.parse_dwarf(dwarf)        # {types, variables}
    seg = segments.derive(elf, layout["variables"])

    layout.update({
        "core": args.core,
        "endianness": "little",
        "product": fw["product"],
        "product_version": fw["product_version"],
        "fw_name": fw["fw_name"],
        "fw_build_hash": fw["fw_build_hash"],
        "nand_type": fw["nand_type"],
        "nand_density": fw["nand_density"],
        "patch_version": fw["patch_version"],
        "release_candidate": fw["release_candidate"],
        "firmware_version": fw["firmware_version"],
        "segments": seg["segments"],
        "sources": seg["sources"],
    })

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = f"{fw['product'] or 'UNKNOWN'}_{args.core}_{fw['fw_build_hash'] or 'NOHASH'}"
    out = out_dir / f"{key}.json"
    out.write_text(json.dumps(layout, indent=2))

    total = sum(s["size"] for s in seg["segments"])
    c = seg["census"]
    print(f"{axf.name}: {len(layout['variables'])} globals | "
          f"dump {total/1048576:.2f} MiB in {len(seg['segments'])} banks | "
          f"HW_DUMP {c.get('HW_DUMP',0)} SKIP_CONST {c.get('SKIP_CONST',0)} "
          f"DRAM {c.get('DRAM',0)} MMIO {c.get('MMIO',0)}")
    print(f"  registry key: {key}")
    print(f"  -> {out}")
    if seg["alarms"]:
        print("  !! REVIEW — SRAM globals skipped (possible loss):")
        for a in seg["alarms"][:20]:
            print(f"       {a}")


if __name__ == "__main__":
    main()
