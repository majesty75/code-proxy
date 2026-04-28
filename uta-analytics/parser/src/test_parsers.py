"""
Parser test harness.

Run inside the parser image:
    docker compose run --rm --entrypoint python parser test_parsers.py
or:
    docker compose run --rm --entrypoint python parser test_parsers.py --log /backfill/<file>.log

What it does:
1. Asserts representative lines route to the expected parser_id and produce
   the expected fields.
2. If a log file path is given (or /backfill/* exists), runs the full registry
   over every line and prints coverage stats: parser_id histogram, lines with
   empty parsed dict, top-10 examples per parser.

Exits 0 on success, non-zero if any assertion fails.
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from parsers import get_parser, _discover_parsers, _registry  # noqa: F401
from parsers.base import BaseParser

# ---------------------------------------------------------------------------
# 1. Targeted assertions
# ---------------------------------------------------------------------------

# (line, expected_parser_id, expected_subset_of_parsed_dict)
CASES: list[tuple[str, str, dict]] = [
    # ---- test_step ----
    ("0000:00:37 >>>BEGIN TL_INIT \tApr 20 16:24:08\t\t\t",
     "test_step", {"kind": "begin", "step": "TL_INIT"}),
    ("0000:00:38 >>>END TL_INIT \tApr 20 16:24:08\t[PASSED]",
     "test_step", {"kind": "end", "step": "TL_INIT", "status": "PASSED"}),
    ("0000:00:38 >>>PROCESS 2 / 221", "test_step",
     {"kind": "process", "current": 2, "total": 221}),
    ("0000:00:38 >>>ELAPSED_TIME\t0000:00:01", "test_step",
     {"kind": "elapsed_time", "elapsed": "0000:00:01", "elapsed_seconds": 1}),
    ("0000:00:37 >>>SCRIPT : 63  /share/_Script_/foo", "test_step",
     {"kind": "script", "count": 63, "path": "/share/_Script_/foo"}),

    # ---- utf_meta ----
    ("0000:00:37 >>>UTF Commit Hash  : 07ca2915449fa701ab8afb5ba1b5045b27c73c82",
     "utf_meta", {"kind": "utf", "key": "Commit Hash"}),
    ("0000:00:37 >>>HostType 11 (Root)", "utf_meta",
     {"kind": "host_type", "id": 11, "name": "Root"}),
    ("0000:00:38 >>>Profile 1,0,0,0,0,0,25,0,1,0,0,0,0,0,0,0,1,0",
     "utf_meta", {"kind": "profile"}),
    ("0000:00:38 >>>PARAMETERS[1] Mode\t= 1",
     "utf_meta", {"kind": "parameter", "index": 1, "key": "Mode", "value": "1"}),

    # ---- command_line ----
    ("0000:00:37 [ CommandLine: /data/UfsTester TL_FFU?Path=/x.bin,Mode=1 -s /share/_Script_/foo -o /share/UTA_FULL_Logs/x.log ]",
     "command_line", {"binary": "/data/UfsTester"}),

    # ---- pass_fail_marker ----
    ("0000:00:37 [PASS][CH 0][BLK 0] Patch Header Signature (Expect : 0x55465348, Actual : 0x55465348)",
     "pass_fail_marker",
     {"status": "PASSED", "loc_ch": 0, "loc_blk": 0,
      "expect": "0x55465348", "actual": "0x55465348"}),

    # ---- set_fw_type ----
    ("0000:00:37 [_SetFwType][2-1. Patch Number via DevInfoDesc] P09 FW00 -> GEN (0x90000)",
     "set_fw_type",
     {"stage": "2-1", "step": "Patch Number via DevInfoDesc",
      "from": "P09 FW00", "to": "GEN", "extra": "0x90000"}),

    # ---- feature_set ----
    ("0000:00:37 [_SetExtFeatureVal : UFS ADVRPMB Value Set] Value Idx : 2 , Value : 32",
     "feature_set",
     {"feature": "UFS ADVRPMB Value Set", "value_idx": 2, "value_int": 32}),
    ("0000:00:37 [UFS NONFI TEST option Set] Value Idx : 8 , Value : 62482432",
     "feature_set",
     {"feature": "UFS NONFI TEST option Set", "value_idx": 8, "value_int": 62482432}),

    # ---- io_stats ----
    ("0000:00:37 Reset Count: 0", "io_stats",
     {"metric": "reset_count", "value": 0}),
    ("0000:00:37 Maximum Latency Time: 53346 usec", "io_stats",
     {"metric": "max_latency_us", "value": 53346, "unit": "us"}),
    ("0000:00:37 Read Io Length: 94 KB", "io_stats",
     {"metric": "read_io_bytes", "value": 94 * 1024, "unit": "B"}),

    # ---- sample_info ----
    ("0000:00:38 DEVICE_DENSITY: 256GB", "sample_info",
     {"key": "DEVICE_DENSITY", "value": "256GB"}),
    ("0000:00:38 FIRMWARE_VERSION: P09 RC00 FW00", "sample_info",
     {"key": "FIRMWARE_VERSION", "value": "P09 RC00 FW00"}),

    # ---- smart_device_info ----
    ("0000:00:38 SmartDeviceInformation FWVersion         = 0x90000",
     "smart_device_info",
     {"key": "FWVersion", "value": "0x90000", "value_int": 0x90000}),
    ("0000:00:38 SmartDeviceInformation.ControllerEfuse0  = 0x773e4628",
     "smart_device_info",
     {"key": "ControllerEfuse0", "value_int": 0x773e4628}),

    # ---- smart_customer_report ----
    ("0000:00:37 SmartCustomerReport SLC EC = Max 1 / Min 0 / Avg 0",
     "smart_customer_report",
     {"report_key": "SLC EC", "report_sub_values": {"Max": 1, "Min": 0, "Avg": 0}}),
    ("0000:00:37 SmartCustomerReport FWExceptionTopLevel = 0x0 (None)",
     "smart_customer_report",
     {"report_key": "FWExceptionTopLevel", "report_value_int": 0}),

    # ---- channel_chip_id ----
    ("0000:00:37 [CH0 WAY1 DIE0] ec, 5e, a8, 3f, 88, cf",
     "channel_chip_id",
     {"channel": 0, "way": 1, "die": 0, "id_bytes": ["ec", "5e", "a8", "3f", "88", "cf"]}),

    # ---- mcb_block ----
    ("0000:00:38 [ MCB CH 1 BLK 0 ]", "mcb_block",
     {"kind": "header", "channel": 1, "block": 0}),
    ("0000:00:38 Signature : 0x46534655 (Correct!)", "mcb_block",
     {"kind": "signature", "signature": "0x46534655", "note": "Correct!"}),
    ("0000:00:38 FirmwareVersion : 0x90000 (P09 RC00 FW00)", "mcb_block",
     {"kind": "firmware_version", "value_int": 0x90000, "value_text": "P09 RC00 FW00"}),

    # ---- elapsed_op ----
    ("0000:00:38 *Reset Device", "elapsed_op",
     {"event": "power_action", "action": "reset device"}),
    ("0000:00:38 [HWReset_Std]", "elapsed_op",
     {"event": "hw_reset", "kind": "Std"}),
    ("0000:00:56 WriteBuffer Complete!! ElapsedTime : 18293 ms (FW Size 816.00KB)",
     "elapsed_op",
     {"event": "buffer_op", "op": "WriteBuffer", "elapsed_us": 18293 * 1000}),
    ("0000:00:57 Nop Duration 449934us", "elapsed_op",
     {"event": "nop_duration", "elapsed_us": 449934}),
    ("0000:01:06 Complete FB Write (7070 ms)", "elapsed_op",
     {"event": "operation_complete", "elapsed_us": 7070 * 1000}),
    ("0000:00:57 Random Sleep : 143 us", "elapsed_op",
     {"event": "random_sleep", "elapsed_us": 143}),

    # ---- spor_rbh ----
    ("0000:00:37 SPOR Count 0 for RBH Logging (Dumb File Path: /data/data/abc_0000.txt)",
     "spor_rbh",
     {"event": "spor_cycle", "count": 0, "dump_path": "/data/data/abc_0000.txt"}),
    ("0000:00:57 RBH Logging Scan Count - 0", "spor_rbh",
     {"event": "rbh_scan_count", "count": 0}),
    ("0000:00:57 < RBH Logging Context >", "spor_rbh",
     {"event": "rbh_context_begin"}),

    # ---- refclk ----
    ("0000:00:57 [RefClk LOG] RefClkFreq Changed !! Prev 0x2 -> Cur 0x1",
     "refclk", {"kind": "freq_changed", "prev": "0x2", "cur": "0x1"}),
    ("0000:00:58 [RefClk LOG] Changed Reference Clock : 38.4Mhz",
     "refclk", {"kind": "changed_clock", "frequency": "38.4Mhz"}),

    # ---- hex_dump ----
    ("0000:00:58 0000000000: 01 00 00 00 00 00 ee 58 00 0c 02 00 00 00 00 00  .......X........",
     "hex_dump", {"offset": 0, "byte_count": 16, "ascii": ".......X........"}),

    # ---- section_banner ----
    ("0000:00:37 =================================", "section_banner",
     {"event": "banner", "char": "="}),
    ("0000:00:38 *************************TL_SAMPLE_INFORMATION**************************",
     "section_banner",
     {"event": "banner", "char": "*", "label": "TL_SAMPLE_INFORMATION"}),

    # ---- pmc_dme ----
    ("0000:00:58 PMC_Result= 0 Lanes= 0x1, Gear= 0x1, Mode= 0x55, Series= 0",
     "pmc_dme", {"event": "pmc_result"}),
    ("0000:00:58 DmeMibPA_ConnectedRxDataLanes = 2", "pmc_dme",
     {"event": "dme_mib", "key": "ConnectedRxDataLanes", "value": "2", "side": "self"}),
    ("0000:00:58 ## Set to gear 1 / lane 1", "pmc_dme",
     {"event": "gear_lane_set", "gear": 1, "lane": 1}),

    # ---- sense_key ----
    ("0000:00:56 Sense Key = 0x5, ASC = 0x24, Rom Code!! Read Buffer Command doesn't work!",
     "sense_key", {"sense_key": "0x5", "asc": "0x24", "sense_key_int": 5, "asc_int": 0x24}),
    ("0000:00:57 [DEBUG] Sensekey 0x5 ASC 0 ASCQ 0", "sense_key",
     {"sense_key": "0x5", "asc": "0", "ascq": "0"}),

    # ---- lu_descriptor ----
    ("0000:00:37 LU[0]", "lu_descriptor",
     {"kind": "header", "lu_id_int": 0, "is_rpmb": False}),
    ("0000:00:37 LU[0x1]", "lu_descriptor",
     {"kind": "header", "lu_id_int": 1}),
    ("0000:00:37 LEGACY RPMB LU[0xc4]", "lu_descriptor",
     {"kind": "header", "is_rpmb": True, "lu_id_int": 0xc4}),
    ("0000:00:37 BootLunId                 = 0", "lu_descriptor",
     {"kind": "field", "key": "BootLunId", "value": "0"}),
    ("0000:00:37 Length                    = 0xee58, 0x3b96000 (244064.000 MB)",
     "lu_descriptor",
     {"kind": "field", "key": "Length"}),

    # ---- temperature ----
    ("0000:00:38 Temperature Notification", "temperature", {"kind": "header"}),
    ("0000:00:38 DeviceCaseRoughTemperature\t=\t\t27", "temperature",
     {"key": "DeviceCaseRoughTemperature", "value": 27}),
    ("0000:00:38 DeviceTooLowTempBoundary\t=\t\t-25", "temperature",
     {"key": "DeviceTooLowTempBoundary", "value": -25}),

    # ---- secure_smart_report ----
    ("0000:00:38 [Secure Smart Report] Exception Top Level: 0x0 (None)",
     "secure_smart_report",
     {"key": "Exception Top Level", "value": "0x0", "value_int": 0, "note": "None"}),

    # ---- bracket_tag (catchall for tagged lines) ----
    ("0000:00:37 [Test_Info] Set fDeviceInit Enter!", "bracket_tag",
     {"primary_tag": "Test_Info", "message": "Set fDeviceInit Enter!"}),
    ("0000:00:37 [DBG] _deviceStatus.bDeviceReset : 0 , _gBootlun_A : 0xb0",
     "bracket_tag",
     {"primary_tag": "DBG"}),
    ("0000:00:37 [Boot Info] _gBootenableId : 1  _gBootlun_A : 0x1  _gBootlun_B : 0x2",
     "bracket_tag",
     {"primary_tag": "Boot Info"}),
    ("0000:00:37 [!][Update ExtFeatures][Descriptor Read with Selector 0]",
     "bracket_tag",
     {"primary_tag": "!"}),

    # ---- default (fallthrough) ----
    ("0000:00:37 Send Nop", "default", {}),
    ("0000:00:37 _hpb 0, _hpbver 0, gnHpbSpecType 0", "default", {}),
]


def assertions() -> tuple[int, int]:
    """Run the targeted assertions. Returns (passed, total)."""
    passed = 0
    failed: list[tuple[str, str, str]] = []  # (line, expected_id, reason)
    for line, expected_id, expected_subset in CASES:
        # Cheaper than constructing again: hit get_parser and parse.
        parser = get_parser(line, "test.log")
        if parser.parser_id != expected_id:
            failed.append((line, expected_id, f"got parser_id={parser.parser_id}"))
            continue
        parsed = parser.parse(line, "test.log")
        missing = [k for k in expected_subset
                   if k not in parsed or parsed[k] != expected_subset[k]]
        if missing:
            failed.append((
                line, expected_id,
                f"missing/wrong keys: {missing}; got={json.dumps(parsed, default=str)}",
            ))
            continue
        passed += 1

    total = len(CASES)
    print(f"\nAssertions: {passed}/{total} passed")
    if failed:
        print("\nFAILURES:")
        for line, exp, reason in failed[:20]:
            print(f"  - {exp!r}: {reason}")
            print(f"    line: {line[:140]}")
    return passed, total


# ---------------------------------------------------------------------------
# 2. Coverage report against a real log file
# ---------------------------------------------------------------------------

def coverage(log_path: Path) -> None:
    if not log_path.exists():
        print(f"\n(no real log at {log_path}, skipping coverage report)")
        return

    by_parser: Counter[str] = Counter()
    empty_parsed: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    blank_lines = 0
    total = 0

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                blank_lines += 1
                continue
            total += 1
            parser = get_parser(line, log_path.name)
            by_parser[parser.parser_id] += 1
            parsed = parser.parse(line, log_path.name)
            if not parsed:
                empty_parsed[parser.parser_id] += 1
            if len(examples[parser.parser_id]) < 3:
                examples[parser.parser_id].append(line[:140])

    print(f"\nCoverage on {log_path.name}: {total} non-blank lines ({blank_lines} blank)")
    print(f"{'parser_id':<25} {'count':>8} {'pct':>7}  empty")
    for pid, n in by_parser.most_common():
        pct = (n / total) * 100 if total else 0
        print(f"{pid:<25} {n:>8} {pct:>6.1f}%  {empty_parsed[pid]:>5}")

    print("\nExample lines per parser:")
    for pid, lines in examples.items():
        print(f"  [{pid}]")
        for l in lines:
            print(f"    {l}")


# ---------------------------------------------------------------------------
# 3. Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--log", default="/backfill/sample.log",
                   help="Path to a real log file for the coverage report")
    args = p.parse_args()

    print("Discovered parsers (priority asc):")
    if not _registry:
        _discover_parsers()
    for pp in _registry:
        print(f"  {pp.priority:>4}  {pp.parser_id}")

    passed, total = assertions()

    coverage(Path(args.log))

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
