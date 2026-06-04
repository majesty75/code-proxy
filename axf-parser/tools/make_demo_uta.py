#!/usr/bin/env python3
"""Create a tiny stand-in for UTA's SQLite so the demo can resolve trname /
fwname / start without the real UTA DB. Mirrors the one column set the decode
service reads: app_board(boardname, trname, fwname, start).

    python -m tools.make_demo_uta uta_demo.sqlite \
        --board R7S1-01 --trname DEMO_TR \
        --fwname RTEMS_ARMCM_V1_TLC_256Gb_P01_RC00_FW00_deadbeef1_20250101 \
        --start "2025-01-01T11:00:00"
"""
import argparse
import sqlite3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--board", default="R7S1-01")
    ap.add_argument("--trname", default="DEMO_TR")
    ap.add_argument("--fwname",
                    default="RTEMS_ARMCM_V1_TLC_256Gb_P01_RC00_FW00_deadbeef1_20250101")
    ap.add_argument("--start", default="2025-01-01T11:00:00")
    args = ap.parse_args()

    con = sqlite3.connect(args.path)
    con.execute("CREATE TABLE IF NOT EXISTS app_board "
                "(boardname TEXT PRIMARY KEY, trname TEXT, fwname TEXT, start TEXT)")
    con.execute("INSERT OR REPLACE INTO app_board VALUES (?,?,?,?)",
                (args.board, args.trname, args.fwname, args.start))
    con.commit()
    con.close()
    print(f"wrote {args.path}: {args.board} -> {args.trname} / {args.fwname}")


if __name__ == "__main__":
    main()
