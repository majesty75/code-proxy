"""
MCB (Master Control Block) per-channel/block records:

  [ MCB CH 0 BLK 0 ]
  [ Format Confirm ]
  Signature : 0x46534655 (Correct!)
  1stRootCxtBlock : 8 / 1stDebugLogBlock : 16
  bIsWrittenFormatConfirm : 0x1
  FirmwareVersion : 0x90000 (P09 RC00 FW00)
  FwBuildTime : 0x10595c2

These are individually parseable; a multi-line aggregator can correlate them
into one block-level row later.
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

MCB_HEADER_RE = re.compile(r"^\[\s*MCB\s+CH\s+(?P<ch>\d+)\s+BLK\s+(?P<blk>\d+)\s*\]\s*$")
FORMAT_CONFIRM_RE = re.compile(r"^\[\s*Format\s+Confirm\s*\]\s*$")
SIGNATURE_RE = re.compile(r"^Signature\s*:\s*(?P<sig>0x[0-9a-fA-F]+)\s*\((?P<note>[^)]+)\)\s*$")
ROOT_DEBUG_RE = re.compile(r"^1stRootCxtBlock\s*:\s*(?P<root>\d+)\s*/\s*1stDebugLogBlock\s*:\s*(?P<debug>\d+)\s*$")
WRITTEN_RE = re.compile(r"^bIsWrittenFormatConfirm\s*:\s*(?P<v>\S+)\s*$")
FW_VERSION_RE = re.compile(r"^FirmwareVersion\s*:\s*(?P<hex>0x[0-9a-fA-F]+)(?:\s*\((?P<text>[^)]+)\))?\s*$")
FW_BUILD_TIME_RE = re.compile(r"^FwBuildTime\s*:\s*(?P<hex>0x[0-9a-fA-F]+)\s*$")


class McbBlockParser(BaseParser):
    parser_id = "mcb_block"
    priority = 18

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        return bool(
            MCB_HEADER_RE.match(body) or FORMAT_CONFIRM_RE.match(body)
            or SIGNATURE_RE.match(body) or ROOT_DEBUG_RE.match(body)
            or WRITTEN_RE.match(body) or FW_VERSION_RE.match(body)
            or FW_BUILD_TIME_RE.match(body)
        )

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

        if (m := MCB_HEADER_RE.match(body)):
            return {"event": "mcb", "kind": "header",
                    "channel": int(m.group("ch")), "block": int(m.group("blk"))}
        if FORMAT_CONFIRM_RE.match(body):
            return {"event": "mcb", "kind": "format_confirm"}
        if (m := SIGNATURE_RE.match(body)):
            return {"event": "mcb", "kind": "signature",
                    "signature": m.group("sig"),
                    "signature_int": int(m.group("sig"), 16),
                    "note": m.group("note")}
        if (m := ROOT_DEBUG_RE.match(body)):
            return {"event": "mcb", "kind": "block_layout",
                    "first_root_cxt_block": int(m.group("root")),
                    "first_debug_log_block": int(m.group("debug"))}
        if (m := WRITTEN_RE.match(body)):
            v = m.group("v")
            try:
                v_int = int(v, 16) if v.startswith("0x") else int(v)
            except ValueError:
                v_int = None
            return {"event": "mcb", "kind": "written_format_confirm",
                    "value": v, "value_int": v_int}
        if (m := FW_VERSION_RE.match(body)):
            return {"event": "mcb", "kind": "firmware_version",
                    "value_hex": m.group("hex"),
                    "value_int": int(m.group("hex"), 16),
                    "value_text": (m.group("text") or "").strip()}
        if (m := FW_BUILD_TIME_RE.match(body)):
            return {"event": "mcb", "kind": "fw_build_time",
                    "value_hex": m.group("hex"),
                    "value_int": int(m.group("hex"), 16)}

        return {"event": "mcb", "raw": body}
