"""
Power-Mode Change (PMC) and DME (Device Management Entity) negotiation lines:

  PMC_Result= 0 Lanes= 0x1, Gear= 0x1, Mode= 0x55, Series= 0
  DmeGetResult= 0, DmeMibPA_PWRMode= 0x55
  DmePeerGetResult= 0, DmeMibPA_PWRMode= 0x55
  DmeMibPA_ConnectedRxDataLanes = 2
  DmeMibPA_ConnectedTxDataLanes = 2
  DmeMibPA_MaxRxPWMGear = 1
  Peer DmeMibPA_MaxRxPWMGear = 1
  ## Set to gear 1 / lane 1
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

PMC_RE = re.compile(r"^PMC_Result\s*=\s*(?P<rest>.+?)\s*$")
DME_GET_RE = re.compile(r"^Dme(?P<which>(?:Peer)?Get)Result\s*=\s*(?P<rest>.+?)\s*$")
DME_MIB_RE = re.compile(r"^(?P<peer>Peer\s+)?DmeMibPA_(?P<key>\w+)\s*=\s*(?P<value>\S+)\s*$")
GEAR_LANE_RE = re.compile(r"^##\s*Set\s+to\s+gear\s+(?P<gear>\d+)\s*/\s*lane\s+(?P<lane>\d+)\s*$")


def _kv(rest: str) -> dict[str, Any]:
    """Split 'k= v, k= v' / 'k= v k= v' into a dict."""
    out: dict[str, Any] = {}
    # Allow either ',' or whitespace as separator after a value.
    for k, v in re.findall(r"(\w+)\s*=\s*(\S+)", rest):
        v = v.rstrip(",")
        out[k] = v
        try:
            if v.startswith(("0x", "0X")):
                out[f"{k}_int"] = int(v, 16)
            else:
                out[f"{k}_int"] = int(v)
        except ValueError:
            pass
    return out


class PmcDmeParser(BaseParser):
    parser_id = "pmc_dme"
    priority = 22

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        return bool(
            PMC_RE.match(body) or DME_GET_RE.match(body)
            or DME_MIB_RE.match(body) or GEAR_LANE_RE.match(body)
        )

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

        if (m := PMC_RE.match(body)):
            return {"event": "pmc_result", **_kv("PMC_Result= " + m.group("rest"))}
        if (m := DME_GET_RE.match(body)):
            return {"event": "dme_get",
                    "side": "peer" if "Peer" in m.group("which") else "self",
                    **_kv(m.group("rest"))}
        if (m := DME_MIB_RE.match(body)):
            return {
                "event": "dme_mib",
                "side": "peer" if m.group("peer") else "self",
                "key": m.group("key"),
                "value": m.group("value"),
            }
        if (m := GEAR_LANE_RE.match(body)):
            return {"event": "gear_lane_set",
                    "gear": int(m.group("gear")),
                    "lane": int(m.group("lane"))}

        return {"event": "pmc_dme", "raw": body}
