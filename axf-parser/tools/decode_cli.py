#!/usr/bin/env python3
"""Offline decode of a packaged dump container against a layout. No infra.

    python -m tools.decode_cli <layout.json> <dump.bin> [--symbol NAME] [--flat] [--out FILE]

--symbol NAME : decode just one global (default: all HW_DUMP globals)
--flat        : print flattened (section, key, value) rows instead of nested JSON
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.decode import Memory, decode_all, decode_variable   # noqa: E402
from core.flatten import flatten                               # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("dump", help="packaged .bin container (UTAX)")
    ap.add_argument("--symbol")
    ap.add_argument("--flat", action="store_true")
    ap.add_argument("--max-deref-depth", type=int, default=4)
    ap.add_argument("--out")
    args = ap.parse_args()

    layout = json.loads(Path(args.layout).read_text())
    mem = Memory.from_container(args.dump)

    if args.symbol:
        decoded, errors = decode_variable(layout, mem, args.symbol, args.max_deref_depth)
        result = {args.symbol: decoded}
        status = "OK" if not errors else "PARTIAL"
    else:
        result, errors, status = decode_all(
            layout, mem, layout.get("sources"), args.max_deref_depth)

    if args.flat:
        rows = flatten(result)
        text = "\n".join(f"{r['section']}\t{r['key']}\t{r['value']}" for r in rows)
        summary = f"# {len(rows)} leaves | status={status} errors={errors}"
    else:
        text = json.dumps(result, indent=2)
        summary = f"# status={status} errors={errors} vars={len(result)}"

    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"{summary}\n  -> {args.out}")
    else:
        print(summary)
        print(text)


if __name__ == "__main__":
    main()
