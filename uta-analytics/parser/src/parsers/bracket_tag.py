"""
Generic catch-all for tagged log lines that no more specific parser claimed.

  [Test_Info] Set fDeviceInit Enter!
  [DBG] _deviceStatus.bDeviceReset : 0 , _gBootlun_A : 0xb0
  [DEBUG] _turboWrite_enable 0 _turboWriteBufferSize = 0x0, ...
  [LOG] Check Support Reset Flush (_ResetAutoFlush 0 , ...)
  [Stack] Get Stack Size Cur -1, Max -1
  [Boot Info] _gBootenableId : 1  _gBootlun_A : 0x1  _gBootlun_B : 0x2
  [Vcc Boot] Check Device Spec Version : 0x310 _gInitialized 0
  [3.0 Boot] Set VCC 2.5 Change Power  !!!
  [RPMB Mode] Legacy RPMB Mode
  [RPMB Test Option] RPMB TEST LEGACY ONLY
  [TL_SETFIELD] Enable RTBB Hang for Debugging
  [Allblock Erase] 0x1 Mode FFU SetField All Block Erase!
  [Firmware OEM] GEN FW
  [Geometry Variables]
  [UFS Feature Variables]
  [Flag] fStreamIdIdn : 0x15  fCommandHistoryRecordEnIdn : 0x12
  [Attribute] dDefragOperation : 0x20 ...
  [DDP Policy] No DDP
  [Get_DeviceDensity] Density : 256 GB
  [GetMaxSlotCount] MaxSlotCount : 32 (Host : 32, Device : 32)
  [!][Update ExtFeatures][Descriptor Read with Selector 0]
  [Prev] _hpb 0, _hpbver 0, gnHpbSpecType 0 [Cur] _hpb 0, _hpbver 0, gnHpbSpecType 0
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

# Capture one or more leading [tag] groups followed by free-form remainder.
TAG_RE = re.compile(r"^(?P<tags>(?:\[[^\]]+\])+)\s*(?P<rest>.*?)\s*$")
KV_COLON_RE = re.compile(r"(\w+)\s*:\s*([^\s,;]+)")
KV_EQUALS_RE = re.compile(r"(\w+)\s*=\s*([^\s,;]+)")


class BracketTagParser(BaseParser):
    parser_id = "bracket_tag"
    priority = 80

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        return body.startswith("[") and TAG_RE.match(body) is not None

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = TAG_RE.match(body)
        if not m:
            return {"event": "tagged", "raw": body}

        tags = re.findall(r"\[([^\]]+)\]", m.group("tags"))
        result: dict[str, Any] = {
            "event": "tagged",
            "tags": tags,
            "primary_tag": tags[0] if tags else None,
        }
        rest = (m.group("rest") or "").strip()
        if rest:
            result["message"] = rest
            kv = {}
            kv.update(dict(KV_EQUALS_RE.findall(rest)))
            kv.update(dict(KV_COLON_RE.findall(rest)))
            if kv:
                result["fields"] = kv
        return result
