"""
Tests for the interlude-only pivot.

Covers:
  * filename_parser renames  (platform→controller, production_step→patch_version)
  * value coercion           (hex→int, parens, units, mixed)
  * end-to-end block parse   against vector/logs/interlude.txt

Run inside the parser image:
    docker compose run --rm --entrypoint python parser test_parsers.py

Or locally:
    cd uta-analytics/parser/src && python -m unittest test_parsers
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Allow direct invocation by adding parser/src to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from filename_parser import parse_filename
from parsers.interlude import (
    InterludeBlockParser,
    coerce_value,
    _slug,
)


FIXTURE_FILENAME = (
    "R7S3-09_20260423_112201_EXEC_AA2_SIRIUS_UFS_3_1_V8_TLC_512Gb_GEN1_256GB_"
    "P09_RC00_FW00_Rack7_Sharath_Aditi_Qual_UFS"
)
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "vector" / "logs" / "interlude.txt"


class FilenameParserTests(unittest.TestCase):
    def test_strict_rename(self):
        meta = parse_filename(FIXTURE_FILENAME)
        self.assertEqual(meta["controller"], "SIRIUS")
        self.assertEqual(meta["patch_version"], "P09")
        self.assertNotIn("platform", meta)
        self.assertNotIn("production_step", meta)
        self.assertEqual(meta["slot_id"], "R7S3-09")
        self.assertEqual(meta["rack"], 7)
        self.assertEqual(meta["shelf"], 3)
        self.assertEqual(meta["slot"], 9)
        self.assertEqual(meta["release_candidate"], "RC00")
        self.assertEqual(meta["firmware_version"], "FW00")
        self.assertEqual(meta["nand_type"], "TLC")
        self.assertEqual(meta["nand_density"], "512Gb")
        self.assertEqual(meta["package_density"], "256GB")
        self.assertEqual(meta["test_purpose"], "Qual")
        self.assertEqual(meta["storage_type"], "UFS")
        self.assertEqual(meta["engineers"], ["Sharath", "Aditi"])
        self.assertEqual(meta["started_at"].year, 2026)

    def test_relaxed(self):
        meta = parse_filename("R8S2-04_random_garbage_V9_blah_P11_RC03_FW02_other.log")
        self.assertEqual(meta["slot_id"], "R8S2-04")
        self.assertEqual(meta["rack"], 8)
        self.assertEqual(meta["shelf"], 2)
        self.assertEqual(meta["slot"], 4)
        self.assertEqual(meta["fw_arch"], "V9")
        self.assertEqual(meta["patch_version"], "P11")
        self.assertEqual(meta["release_candidate"], "RC03")
        self.assertEqual(meta["firmware_version"], "FW02")


class CoerceValueTests(unittest.TestCase):
    def assertNumEq(self, raw, num, unit=""):
        v_num, v_str, v_unit = coerce_value(raw)
        self.assertEqual(v_str, raw.strip())
        self.assertIsNotNone(v_num, f"expected numeric for {raw!r}")
        self.assertAlmostEqual(v_num, num, msg=f"raw={raw!r}")
        self.assertEqual(v_unit, unit, msg=f"raw={raw!r}")

    def test_pure_hex(self):
        self.assertNumEq("0x91600", 595456)
        self.assertNumEq("0x9", 9)
        self.assertNumEq("0xffffffc0", 4294967232)

    def test_pure_int(self):
        self.assertNumEq("191", 191)
        self.assertNumEq("-25", -25)
        self.assertNumEq("0", 0)

    def test_pure_float(self):
        self.assertNumEq("223356.000", 223356.0)

    def test_number_with_unit(self):
        self.assertNumEq("4096MB", 4096, "MB")
        self.assertNumEq("35694 usec", 35694, "us")
        self.assertNumEq("256 GB", 256, "GB")

    def test_paren_with_unit(self):
        v_num, _, v_unit = coerce_value("0xda1f, 0x3687c00 (223356.000 MB)")
        self.assertAlmostEqual(v_num, 223356.0)
        self.assertEqual(v_unit, "MB")

    def test_hex_paren_dec(self):
        v_num, _, v_unit = coerce_value("0x91600 (595456) 2326MB")
        self.assertAlmostEqual(v_num, 595456.0)
        self.assertEqual(v_unit, "MB")

    def test_paren_text(self):
        v_num, _, _ = coerce_value("0x39 (HIL_TMF)")
        self.assertAlmostEqual(v_num, 57)

    def test_paren_inner_hex(self):
        v_num, _, _ = coerce_value("Update Host Meta(0x2)")
        self.assertAlmostEqual(v_num, 2)

    def test_pure_string(self):
        v_num, v_str, _ = coerce_value("PASSED")
        self.assertIsNone(v_num)
        self.assertEqual(v_str, "PASSED")


class InterludeBlockParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FIXTURE_PATH.exists():
            raise unittest.SkipTest(f"fixture missing: {FIXTURE_PATH}")
        with FIXTURE_PATH.open("r", encoding="utf-8", errors="replace") as f:
            cls.lines = [line.rstrip("\n") for line in f]
        cls.meta = parse_filename(FIXTURE_FILENAME)
        parser = InterludeBlockParser()
        cls.result = parser.parse(cls.lines, FIXTURE_FILENAME, cls.meta)
        cls.snapshot = cls.result["snapshot"]
        cls.metrics = cls.result["metrics"]

    def test_block_envelope(self):
        s = self.snapshot
        self.assertEqual(s["block_status"], "PASSED")
        self.assertIsNotNone(s["block_started_at"])
        self.assertIsNotNone(s["block_ended_at"])
        self.assertIsNotNone(s["block_duration_s"])

    def test_promoted_definite_metrics(self):
        s = self.snapshot
        self.assertEqual(s["wai"], 1)
        self.assertEqual(s["waf"], 1)
        self.assertEqual(s["ec_slc_max"], 191)
        self.assertEqual(s["ec_slc_min"], 74)
        self.assertEqual(s["ec_slc_avg"], 163)
        self.assertEqual(s["ec_mlc_max"], 159)
        self.assertEqual(s["ec_mlc_min"], 41)
        self.assertEqual(s["ec_mlc_avg"], 64)
        self.assertEqual(s["init_bb"], 34)
        self.assertEqual(s["rt_bb"], 0)
        self.assertEqual(s["reserved_bb"], 126)
        self.assertEqual(s["free_block_cnt_xlc"], 175)
        self.assertEqual(s["free_block_cnt_slc"], 0)
        self.assertEqual(s["ftl_open_count"], 15099)
        self.assertEqual(s["read_reclaim_count"], 5)
        self.assertEqual(s["total_nand_write_bytes"], 12820385304576)
        self.assertEqual(s["total_nand_erase_bytes"], 19615569149952)

    def test_promoted_io_and_latency(self):
        s = self.snapshot
        self.assertEqual(s["io_total"], 187)
        self.assertEqual(s["read_io"], 105)
        self.assertEqual(s["write_io"], 5)
        self.assertEqual(s["read_io_kb"], 1002)
        self.assertEqual(s["write_io_kb"], 2)
        self.assertEqual(s["latency_max_us"], 35694)
        self.assertEqual(s["latency_avg_us"], 1554)
        self.assertEqual(s["latency_min_us"], 9)
        self.assertEqual(s["reset_count"], 0)
        self.assertEqual(s["por_count"], 0)
        self.assertEqual(s["pmc_count"], 1)

    def test_promoted_phy(self):
        s = self.snapshot
        self.assertEqual(s["phy_lanes"], 2)
        self.assertEqual(s["phy_gear"], 4)

    def test_promoted_ssr(self):
        s = self.snapshot
        self.assertEqual(s["ssr_received_pon_count"], 14136)
        self.assertEqual(s["ssr_received_spo_count"], 963)
        self.assertEqual(s["ssr_remain_reserved_block"], 126)

    def test_temperature(self):
        s = self.snapshot
        self.assertEqual(s["temp_case"], 25)
        self.assertEqual(s["temp_thermal_value"], 34)
        self.assertEqual(s["temp_nanddts"], 37)

    def test_groups_in_variables(self):
        v = self.snapshot["variables"]
        self.assertIsInstance(v["lus"], list)
        self.assertGreater(len(v["lus"]), 0)
        self.assertIsInstance(v["bad_blocks"], list)
        self.assertGreater(len(v["bad_blocks"]), 10)
        self.assertIsInstance(v["plane_bb"], list)
        self.assertGreaterEqual(len(v["plane_bb"]), 16)
        self.assertIsInstance(v["mcb_blocks"], list)
        self.assertGreaterEqual(len(v["mcb_blocks"]), 4)
        self.assertEqual(len(v["profile_vector"]), 18)
        self.assertEqual(v["profile_vector"][0], 191)
        self.assertEqual(v["host_type"]["id"], 11)

    def test_sidecar_metric_count(self):
        self.assertGreater(len(self.metrics), 100, f"only {len(self.metrics)} metrics extracted")

    def test_sidecar_has_ssr(self):
        ssr_keys = [m for m in self.metrics if m["section"] == "ssr"]
        self.assertGreater(len(ssr_keys), 30, f"only {len(ssr_keys)} ssr keys")

    def test_sidecar_has_health(self):
        keys = [m for m in self.metrics if "health_descriptor" in m["section"]]
        self.assertGreater(len(keys), 5)

    def test_sidecar_value_num_set_for_numerics(self):
        nums = [m for m in self.metrics if m["value_num"] is not None]
        self.assertGreaterEqual(len(nums) / max(len(self.metrics), 1), 0.8)


class SlugTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_slug("Check Smart Report"), "check_smart_report")
        self.assertEqual(_slug("TL_INFO"), "tl_info")
        self.assertEqual(_slug("DTT Parameter Read"), "dtt_parameter_read")


if __name__ == "__main__":
    unittest.main()
