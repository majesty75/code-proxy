"""
TL_interlude block parser.

The firmware emits a recurring snapshot of every health/profile variable it
tracks. Each emission is delimited by:

    >>>BEGIN TL_interlude   Apr 23 11:22:01
    0000:00:03 …                                 ← body
    0000:00:03 >>>END TL_interlude  Apr 23 11:22:01  [PASSED]

We capture EVERY scalar variable in the body — not just a handpicked few:
  * promoted typed metrics  → typed columns on uta.interlude_snapshots
  * sidecar metric rows     → uta.interlude_metrics (one per scalar key)
  * structured groups       → JSON blob in interlude_snapshots.variables
                              (LU descriptors, Bad List, plane bad-blocks, MCB blocks)

Hex literals are decoded to ints; numeric values with parens or units are
captured into a ``value_num`` column with the unit set when present, while
the original token is preserved in ``value_str`` for traceability.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from .base import BaseBlockParser


# ----------------------------------------------------------------------
# Line-level patterns
# ----------------------------------------------------------------------
LINE_PREFIX = re.compile(r"^(\d{4}:\d{2}:\d{2}(?:\.\d+)?)\s")
BEGIN_RE    = re.compile(r">>>BEGIN TL_interlude\s+([A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})")
END_RE      = re.compile(r">>>END TL_interlude\s+([A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})(?:\s+\[([A-Z]+)\])?")
SECTION_RE  = re.compile(r"^###\s+(.+?)\s*$")

PROFILE_RE     = re.compile(r"^>>>Profile\s+(.+)$")
HOST_TYPE_RE   = re.compile(r"^>>>HostType\s+(\S+)\s*\(([^)]+)\)")
DEVICE_INFO_RE = re.compile(r"^>>>DeviceInfo\s+(.+?)\s*,?\s*$")
ELAPSED_RE     = re.compile(r"^>>>ELAPSED_TIME\s+(\S+)")

BAD_LIST_RE = re.compile(
    r"^Bad List\[(\d+)\]\s+CH\s+(\d+)\s+Way\s+(\d+)\s+Die\s+(\d+)\s+BLK\s+(\d+)\s+"
    r"BadType\s+(\d+)\s+\(([^)]+)\)\s+Actual Plane\s+(\d+)\s+Borrowed Plane\s+(\d+)"
)
PLANE_BB_RE = re.compile(
    r"^CH\[(\d+)\]\s+WAY\[(\d+)\]\s+DIE\[(\d+)\]\s+Plane\[(\d+)\]\s+"
    r"InitBB\[(\d+)\]\s+RTBB\[(\d+)\]\s+Delayed\[(\d+)\]\s+EOLRatio\[(\d+)\]"
)
LU_OPEN_RE  = re.compile(r"^(?:LEGACY RPMB\s+)?LU\[([^\]]+)\]\s*$")
MCB_OPEN_RE = re.compile(r"^\[\s*MCB\s+CH\s+(\d+)\s+BLK\s+(\d+)\s*\]\s*$")

# Inline summary patterns (these recur multiple times and carry the headline
# values we promote to typed columns).
WAI_WAF_RE      = re.compile(r"WAI\s*:\s*(\d+)\s*,\s*WAF\s*:\s*(\d+)")
EC_SUMMARY_RE   = re.compile(r"EC\s+(SLC|MLC)\s+Max\s*:\s*(\d+),\s*Min\s*:\s*(\d+),\s*Avg\s*:\s*(\d+)")
BB_SUMMARY_RE   = re.compile(r"InitBB\s*:\s*(\d+)\s*,\s*RTBB\s*:\s*(\d+)\s*,\s*RB\s*:\s*(\d+)")
FREE_BLOCK_RE   = re.compile(r"Free Block Cnt\s*=\s*xLC\s+(\d+)\s*/\s*SLC\s+(\d+)")
TEMP_FULL_RE    = re.compile(
    r"DeviceCaseRoughTemperature\s*=\s*(-?\d+).*?ThermalValue\s*=\s*(-?\d+)\((-?\d+)\)"
    r"(?:\s*,\s*NANDDTS\s*=\s*(-?\d+))?"
)
PMC_RESULT_RE   = re.compile(
    r"PMC_Result=\s*(\d+)\s+Lanes=\s*(\S+),\s*Gear=\s*(\S+),\s*Mode=\s*(\S+),\s*Series=\s*(\S+)"
)

# Bracketed and generic K-V (used last)
KV_BRACKETED_RE = re.compile(r"^([A-Za-z][\w \.\(\)\[\]\-/]*?)\s*:\s*\[([^\]]*)\]\s*$")
KV_EQUALS_RE    = re.compile(r"^([A-Za-z][\w \.\(\)/\-]*?)\s*=\s*(.+?)\s*$")
KV_COLON_RE     = re.compile(r"^([A-Za-z][\w \.\(\)/\-]*?)\s*:\s*(.+?)\s*$")

# Bracket-prefix lines like "[LOG] foo : bar" — strip the prefix, keep the rest.
BRACKET_PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s+(.+)$")

# Hex / number recognisers for value coercion.
HEX_FULL    = re.compile(r"^(0x[0-9a-fA-F]+)$")
INT_FULL    = re.compile(r"^(-?\d+)$")
FLOAT_FULL  = re.compile(r"^(-?\d+\.\d+)$")
NUM_UNIT    = re.compile(r"^(-?\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*$")
HEX_PAREN_DEC = re.compile(
    r"^(0x[0-9a-fA-F]+)\s*\(\s*(-?\d+(?:\.\d+)?)\s*\)\s*(\d*(?:\.\d+)?\s*[A-Za-z]+)?\s*$"
)
PAREN_NUM   = re.compile(r"\(\s*(0x[0-9a-fA-F]+|-?\d+(?:\.\d+)?)\s*([A-Za-z]+)?\s*\)")
ANY_HEX     = re.compile(r"\b(0x[0-9a-fA-F]+)\b")
ANY_INT     = re.compile(r"-?\d+")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s


def _normalize_unit(u: str) -> str:
    if not u:
        return ""
    u = u.strip()
    return {"usec": "us", "msec": "ms", "sec": "s", "Usec": "us"}.get(u, u)


def _parse_int_maybe_hex(s: str) -> Optional[int]:
    s = s.strip()
    if HEX_FULL.match(s):
        return int(s, 16)
    if INT_FULL.match(s):
        return int(s)
    return None


def coerce_value(s: str) -> tuple[Optional[float], str, str]:
    """
    Decode a raw value token into ``(value_num, value_str, unit)``.

    Order of attempts:
      1. pure hex      → 0x91600 → 595456
      2. pure int      → -25     → -25
      3. pure float    → 1.5     → 1.5
      4. number+unit   → 4096MB  → 4096, unit=MB
      5. hex+(decimal)+unit → 0x91600 (595456) 2326MB → 595456, MB
      6. parenthesised numeric value with optional unit
      7. fallback: any hex anywhere → its decoded value
      8. fallback: any int anywhere
      9. otherwise pure string → value_num=None
    The original token is always preserved as ``value_str``.
    """
    s = (s or "").strip()
    if not s:
        return None, "", ""

    if HEX_FULL.match(s):
        return float(int(s, 16)), s, ""
    if INT_FULL.match(s):
        return float(int(s)), s, ""
    if FLOAT_FULL.match(s):
        return float(s), s, ""

    if (m := NUM_UNIT.match(s)):
        return float(m.group(1)), s, _normalize_unit(m.group(2))

    if (m := HEX_PAREN_DEC.match(s)):
        unit = ""
        trail = m.group(3)
        if trail:
            um = re.search(r"([A-Za-z]+)$", trail)
            if um:
                unit = _normalize_unit(um.group(1))
        return float(m.group(2)), s, unit

    if (m := PAREN_NUM.search(s)):
        raw = m.group(1)
        try:
            num = float(int(raw, 16) if raw.startswith("0x") else float(raw))
        except ValueError:
            num = None
        unit = ""
        if m.group(2):
            unit = _normalize_unit(m.group(2))
        else:
            tm = re.search(r"\)\s*\d*(?:\.\d+)?\s*([A-Za-z]+)\s*$", s)
            if tm:
                unit = _normalize_unit(tm.group(1))
        if num is not None:
            return num, s, unit

    if (m := ANY_HEX.search(s)):
        return float(int(m.group(1), 16)), s, ""

    if (m := ANY_INT.search(s)):
        try:
            return float(int(m.group(0))), s, ""
        except ValueError:
            pass

    return None, s, ""


def _parse_marker_time(ts_str: str, meta: dict[str, Any]) -> Optional[datetime]:
    """Marker stamps are 'Apr 23 11:22:01' — year is inferred from session."""
    if not ts_str:
        return None
    started_at = meta.get("started_at")
    year = started_at.year if isinstance(started_at, datetime) else datetime.utcnow().year
    cleaned = re.sub(r"\s+", " ", ts_str.strip())
    try:
        return datetime.strptime(f"{year} {cleaned}", "%Y %b %d %H:%M:%S")
    except ValueError:
        return None


def _elapsed_to_seconds(ts: str) -> Optional[float]:
    m = re.match(r"^(\d+):(\d+):(\d+)(?:\.(\d+))?$", ts.strip())
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    frac = float("0." + m.group(4)) if m.group(4) else 0.0
    return h * 3600 + mi * 60 + s + frac


# ----------------------------------------------------------------------
# Promotion table — maps recognised inline summary metrics to typed cols.
# Anything not listed here is still captured into interlude_metrics.
# ----------------------------------------------------------------------
SSR_PROMOTIONS = {
    "ReceivedPonCount":    "ssr_received_pon_count",
    "ReceivedSpoCount":    "ssr_received_spo_count",
    "RemainReservedBlock": "ssr_remain_reserved_block",
}

PROMOTED_COLS = {
    "wai", "waf",
    "ec_slc_max", "ec_slc_min", "ec_slc_avg",
    "ec_mlc_max", "ec_mlc_min", "ec_mlc_avg",
    "init_bb", "rt_bb", "reserved_bb",
    "free_block_cnt_xlc", "free_block_cnt_slc",
    "ftl_open_count", "read_reclaim_count",
    "total_nand_write_bytes", "total_nand_erase_bytes",
    "temp_case", "temp_thermal_value", "temp_nanddts",
    "latency_max_us", "latency_avg_us", "latency_min_us",
    "io_total", "read_io", "write_io", "read_io_kb", "write_io_kb",
    "reset_count", "por_count", "pmc_count", "power_lvdf_event_count",
    "phy_gear", "phy_lanes",
    "ssr_received_pon_count", "ssr_received_spo_count", "ssr_remain_reserved_block",
}


# ----------------------------------------------------------------------
# Block parser
# ----------------------------------------------------------------------
class InterludeBlockParser(BaseBlockParser):
    block_id = "interlude"
    target_table = "interlude_snapshots"
    begin_marker = re.compile(r">>>BEGIN TL_interlude")
    end_marker   = re.compile(r">>>END TL_interlude")

    def parse(
        self,
        lines: list[str],
        filename: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "block_status": "",
            "block_started_at": None,
            "block_ended_at": None,
            "block_duration_s": None,
        }
        promoted: dict[str, Any] = {}
        metrics_dict: dict[tuple[str, str], dict[str, Any]] = {}

        bad_blocks: list[dict[str, Any]] = []
        plane_bb:   list[dict[str, Any]] = []
        lus:        list[dict[str, Any]] = []
        mcb_blocks: list[dict[str, Any]] = []
        host_type:  Optional[dict[str, Any]] = None
        profile_vector: Optional[list[int]] = None
        device_info: Optional[list[str]] = None
        fw_elapsed: Optional[str] = None
        max_body_elapsed_s: float = 0.0

        current_lu: Optional[dict[str, Any]] = None
        current_mcb: Optional[dict[str, Any]] = None
        section_slug: str = ""

        def emit(section: str, key: str, raw: str) -> tuple[Optional[float], str, str]:
            v_num, v_str, unit = coerce_value(raw)
            full_key = f"{section}.{key}" if section else key
            metrics_dict[(section, full_key)] = {
                "section": section,
                "key": full_key,
                "value_num": v_num,
                "value_str": v_str,
                "unit": unit,
            }
            return v_num, v_str, unit

        for raw_line in lines:
            # Strip elapsed prefix (track max for block duration fallback)
            mp = LINE_PREFIX.match(raw_line)
            if mp:
                elapsed_s = _elapsed_to_seconds(mp.group(1))
                if elapsed_s is not None and elapsed_s > max_body_elapsed_s:
                    max_body_elapsed_s = elapsed_s
                body = raw_line[mp.end():]
            else:
                body = raw_line
            body = body.rstrip("\r\n").rstrip()

            if not body:
                continue

            # BEGIN / END markers
            if (m := BEGIN_RE.search(body)):
                snapshot["block_started_at"] = _parse_marker_time(m.group(1), meta)
                continue
            if (m := END_RE.search(body)):
                snapshot["block_ended_at"] = _parse_marker_time(m.group(1), meta)
                snapshot["block_status"] = (m.group(2) or "UNKNOWN").upper()
                continue

            # >>> markers
            if (m := PROFILE_RE.match(body)):
                try:
                    profile_vector = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
                except ValueError:
                    profile_vector = None
                continue
            if (m := HOST_TYPE_RE.match(body)):
                hid = _parse_int_maybe_hex(m.group(1))
                host_type = {"id": hid, "name": m.group(2).strip()}
                if hid is not None:
                    emit("host", "type_id", str(hid))
                continue
            if (m := DEVICE_INFO_RE.match(body)):
                raw = m.group(1).rstrip(",")
                parts = [p for p in re.split(r"\\\\?", raw) if p]
                device_info = parts
                continue
            if (m := ELAPSED_RE.match(body)):
                fw_elapsed = m.group(1)
                continue

            # Section heading flips the namespace
            if (m := SECTION_RE.match(body)):
                section_slug = _slug(m.group(1))
                current_lu = None
                current_mcb = None
                continue

            # Multi-row groups (open MCB / LU before bracket-stripping)
            if (m := MCB_OPEN_RE.match(body)):
                current_mcb = {"ch": int(m.group(1)), "blk": int(m.group(2))}
                mcb_blocks.append(current_mcb)
                current_lu = None
                continue
            if (m := LU_OPEN_RE.match(body)):
                lu_id_raw = m.group(1)
                current_lu = {"id": lu_id_raw}
                lus.append(current_lu)
                current_mcb = None
                continue
            if (m := BAD_LIST_RE.match(body)):
                bad_blocks.append({
                    "idx": int(m.group(1)),
                    "ch": int(m.group(2)),
                    "way": int(m.group(3)),
                    "die": int(m.group(4)),
                    "blk": int(m.group(5)),
                    "bad_type": int(m.group(6)),
                    "bad_class": m.group(7),
                    "actual_plane": int(m.group(8)),
                    "borrowed_plane": int(m.group(9)),
                })
                continue
            if (m := PLANE_BB_RE.match(body)):
                plane_bb.append({
                    "ch": int(m.group(1)), "way": int(m.group(2)),
                    "die": int(m.group(3)), "plane": int(m.group(4)),
                    "init_bb": int(m.group(5)), "rt_bb": int(m.group(6)),
                    "delayed": int(m.group(7)), "eol_ratio": int(m.group(8)),
                })
                continue

            # Inline summary — promoted metrics (last value wins)
            handled = False
            if (m := WAI_WAF_RE.search(body)):
                promoted["wai"] = int(m.group(1))
                promoted["waf"] = int(m.group(2))
                emit("summary", "WAI", m.group(1))
                emit("summary", "WAF", m.group(2))
                handled = True
            if (m := EC_SUMMARY_RE.search(body)):
                tier = m.group(1).lower()
                mx, mn, av = int(m.group(2)), int(m.group(3)), int(m.group(4))
                promoted[f"ec_{tier}_max"] = mx
                promoted[f"ec_{tier}_min"] = mn
                promoted[f"ec_{tier}_avg"] = av
                emit("summary", f"EC.{tier.upper()}.Max", str(mx))
                emit("summary", f"EC.{tier.upper()}.Min", str(mn))
                emit("summary", f"EC.{tier.upper()}.Avg", str(av))
                handled = True
            if (m := BB_SUMMARY_RE.search(body)):
                init, rt, rb = int(m.group(1)), int(m.group(2)), int(m.group(3))
                promoted["init_bb"] = init
                promoted["rt_bb"] = rt
                promoted["reserved_bb"] = rb
                emit("summary", "InitBB", str(init))
                emit("summary", "RTBB", str(rt))
                emit("summary", "RB", str(rb))
                handled = True
            if (m := FREE_BLOCK_RE.search(body)):
                xlc, slc = int(m.group(1)), int(m.group(2))
                promoted["free_block_cnt_xlc"] = xlc
                promoted["free_block_cnt_slc"] = slc
                emit("summary", "FreeBlockCnt.xLC", str(xlc))
                emit("summary", "FreeBlockCnt.SLC", str(slc))
                handled = True
            if (m := TEMP_FULL_RE.search(body)):
                tcase = int(m.group(1))
                tval  = int(m.group(2))
                tdts  = int(m.group(4)) if m.group(4) else None
                promoted["temp_case"] = tcase
                promoted["temp_thermal_value"] = tval
                if tdts is not None:
                    promoted["temp_nanddts"] = tdts
                emit("temperature", "DeviceCaseRoughTemperature", str(tcase))
                emit("temperature", "ThermalValue", str(tval))
                if tdts is not None:
                    emit("temperature", "NANDDTS", str(tdts))
                handled = True
            if (m := PMC_RESULT_RE.search(body)):
                lanes = _parse_int_maybe_hex(m.group(2))
                gear  = _parse_int_maybe_hex(m.group(3))
                if lanes is not None: promoted["phy_lanes"] = lanes
                if gear  is not None: promoted["phy_gear"]  = gear
                emit("phy", "PMC_Result", m.group(1))
                emit("phy", "Lanes", m.group(2))
                emit("phy", "Gear",  m.group(3))
                emit("phy", "Mode",  m.group(4))
                emit("phy", "Series", m.group(5))
                handled = True
            if handled:
                continue

            # Single-key promotions
            if (m := re.match(r"^TotalNandWriteBytes\s*:\s*(\d+)", body)):
                promoted["total_nand_write_bytes"] = int(m.group(1))
                emit("summary", "TotalNandWriteBytes", m.group(1))
                continue
            if (m := re.match(r"^TotalNandEraseBytes\s*:\s*(\d+)", body)):
                promoted["total_nand_erase_bytes"] = int(m.group(1))
                emit("summary", "TotalNandEraseBytes", m.group(1))
                continue
            if (m := re.match(r"^FTLOpenCount\s*:\s*(\d+)", body)):
                promoted["ftl_open_count"] = int(m.group(1))
                emit("summary", "FTLOpenCount", m.group(1))
                continue
            if (m := re.match(r"^ReadReclaimCount\s*:\s*(\d+)", body)):
                promoted["read_reclaim_count"] = int(m.group(1))
                emit("summary", "ReadReclaimCount", m.group(1))
                continue

            # IO counter block at end of block (Reset Count: 0, Io Count: 187, …)
            if (m := re.match(r"^Reset Count\s*:\s*(\d+)", body)):
                promoted["reset_count"] = int(m.group(1)); emit("io", "ResetCount", m.group(1)); continue
            if (m := re.match(r"^POR Count\s*:\s*(\d+)", body)):
                promoted["por_count"] = int(m.group(1)); emit("io", "PORCount", m.group(1)); continue
            if (m := re.match(r"^PMC Count\s*:\s*(\d+)", body)):
                promoted["pmc_count"] = int(m.group(1)); emit("io", "PMCCount", m.group(1)); continue
            if (m := re.match(r"^Io Count\s*:\s*(\d+)", body)):
                promoted["io_total"] = int(m.group(1)); emit("io", "IoCount", m.group(1)); continue
            if (m := re.match(r"^Read Io Count\s*:\s*(\d+)", body)):
                promoted["read_io"] = int(m.group(1)); emit("io", "ReadIoCount", m.group(1)); continue
            if (m := re.match(r"^Write Io Count\s*:\s*(\d+)", body)):
                promoted["write_io"] = int(m.group(1)); emit("io", "WriteIoCount", m.group(1)); continue
            if (m := re.match(r"^Read Io Length\s*:\s*(\d+)\s*KB", body)):
                promoted["read_io_kb"] = int(m.group(1)); emit("io", "ReadIoLengthKB", m.group(1)); continue
            if (m := re.match(r"^Write Io Length\s*:\s*(\d+)\s*KB", body)):
                promoted["write_io_kb"] = int(m.group(1)); emit("io", "WriteIoLengthKB", m.group(1)); continue
            if (m := re.match(r"^Maximum Latency Time\s*:\s*(\d+)", body)):
                promoted["latency_max_us"] = int(m.group(1)); emit("io", "MaxLatencyUs", m.group(1)); continue
            if (m := re.match(r"^Average Latency Time\s*:\s*(\d+)", body)):
                promoted["latency_avg_us"] = int(m.group(1)); emit("io", "AvgLatencyUs", m.group(1)); continue
            if (m := re.match(r"^Minimum Latency Time\s*:\s*(\d+)", body)):
                promoted["latency_min_us"] = int(m.group(1)); emit("io", "MinLatencyUs", m.group(1)); continue
            if (m := re.match(r"^PowerLvdfEventCount\s+(\d+)", body)):
                promoted["power_lvdf_event_count"] = int(m.group(1))
                emit("power", "PowerLvdfEventCount", m.group(1))
                continue

            # SmartCustomerReport key = value
            if (m := re.match(r"^SmartCustomerReport\s+(.+?)\s*=\s*(.+?)\s*$", body)):
                key = re.sub(r"\s+", "_", m.group(1).strip())
                v_num, _, _ = emit("ssr", key, m.group(2))
                col = SSR_PROMOTIONS.get(key)
                if col and v_num is not None:
                    promoted[col] = int(v_num)
                continue

            # SmartDeviceInformation [.|space] key = value
            if (m := re.match(r"^SmartDeviceInformation[\s.]+(.+?)\s*=\s*(.+?)\s*$", body)):
                key = re.sub(r"\s+", "_", m.group(1).strip().rstrip("."))
                emit("sdi", key, m.group(2))
                continue

            # Statistic key : [val] or Statistic key = val
            if (m := re.match(r"^Statistic\s+(.+?)\s*:\s*\[([^\]]*)\]\s*$", body)):
                emit("stat", re.sub(r"\s+", "_", m.group(1).strip()), m.group(2))
                continue
            if (m := re.match(r"^Statistic\s+(.+?)\s*=\s*(.+?)\s*$", body)):
                emit("stat", re.sub(r"\s+", "_", m.group(1).strip()), m.group(2))
                continue

            # MCB body lines (until next [...] block or section change)
            if current_mcb is not None and (m := re.match(r"^([A-Za-z][\w\s]*?)\s*:\s*(.+?)\s*$", body)):
                key = re.sub(r"\s+", "_", m.group(1).strip())
                current_mcb[key] = m.group(2).strip()
                emit(f"mcb.ch{current_mcb['ch']}_blk{current_mcb['blk']}", key, m.group(2))
                continue

            # LU body lines (until next LU[…] or section change)
            if current_lu is not None and (m := re.match(r"^([A-Za-z][\w\s]*?)\s*=\s*(.+?)\s*$", body)):
                key = re.sub(r"\s+", "_", m.group(1).strip())
                current_lu[key] = m.group(2).strip()
                emit(f"lu_{_slug(str(current_lu['id']))}", key, m.group(2))
                continue

            # Strip a leading bracket-prefix like "[LOG] foo : 3" so the
            # generic K-V matchers below can still capture it.
            stripped_body = body
            ns = section_slug
            bm = BRACKET_PREFIX_RE.match(body)
            if bm:
                ns_candidate = _slug(bm.group(1))
                if ns_candidate:
                    ns = f"{section_slug}.{ns_candidate}" if section_slug else ns_candidate
                stripped_body = bm.group(2)

            # Generic bracketed: "<key> : [<val>]"
            if (m := KV_BRACKETED_RE.match(stripped_body)):
                emit(ns, re.sub(r"\s+", "_", m.group(1).strip()), m.group(2))
                continue

            # Generic K = V
            if (m := KV_EQUALS_RE.match(stripped_body)):
                key = re.sub(r"\s+", "_", m.group(1).strip())
                if key:
                    emit(ns, key, m.group(2))
                    continue

            # Generic K : V
            if (m := KV_COLON_RE.match(stripped_body)):
                key = re.sub(r"\s+", "_", m.group(1).strip())
                if key:
                    emit(ns, key, m.group(2))
                    continue

            # Unmatched line — silently ignored for now.

        # Block duration: take whichever of wall-clock and body-elapsed is
        # larger. Wall delta is sometimes 0 because BEGIN and END share the
        # same MMM-DD-HH:MM:SS second; the body's elapsed prefix is finer.
        started = snapshot["block_started_at"]
        ended   = snapshot["block_ended_at"]
        wall_dur = (ended - started).total_seconds() if (started and ended) else None
        candidates = [d for d in (wall_dur, max_body_elapsed_s) if d is not None]
        snapshot["block_duration_s"] = max(candidates) if candidates else None

        # Pack everything that didn't go into a typed column into the JSON blob.
        snapshot["variables"] = {
            "host_type":      host_type,
            "profile_vector": profile_vector,
            "device_info":    device_info,
            "fw_elapsed_time": fw_elapsed,
            "lus":            lus,
            "bad_blocks":     bad_blocks,
            "plane_bb":       plane_bb,
            "mcb_blocks":     mcb_blocks,
        }
        # Apply promoted typed values (only known columns make it through).
        for k, v in promoted.items():
            if k in PROMOTED_COLS:
                snapshot[k] = v

        return {
            "snapshot": snapshot,
            "metrics":  list(metrics_dict.values()),
        }
