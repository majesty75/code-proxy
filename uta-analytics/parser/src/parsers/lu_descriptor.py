"""
Logical Unit (LU) descriptor lines from TL_INFO and similar steps:

  LU[0]
  Type                      = MLC / TLC
  BootLunId                 = 0
  LogicalBlockSize          = 0x1000
  Length                    = 0xee58, 0x3b96000 (244064.000 MB)
  Provisioning              = 0x2
  Data Reliability          = 0
  Write Protect             = 0

  LU[0x1]
  ...

  LEGACY RPMB LU[0xc4]
  LogicalBlockSize          = 0x100
  Length                    = 0x10000 (16.000 MB)
  RPMB Region0 Size         = 12288KB (0xc000)
  RPMB Region 0 WriteCounter = 0
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

LU_HEADER_RE = re.compile(r"^(?P<prefix>(?:LEGACY\s+RPMB\s+)?)LU\[(?P<id>0x[0-9a-fA-F]+|\d+)\]\s*$")
LU_FIELD_KEYS = {
    "Type", "BootLunId", "LogicalBlockSize", "Length",
    "Provisioning", "Data Reliability", "Write Protect",
    "RPMB Region0 Size", "RPMB Region3 Size",
    "RPMB Region 0 WriteCounter", "RPMB Region 3 WriteCounter",
}
FIELD_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9 ]+?)\s*=\s*(?P<value>.+?)\s*$")


class LuDescriptorParser(BaseParser):
    parser_id = "lu_descriptor"
    priority = 24

    def can_parse(self, line: str, filename: str) -> bool:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        if LU_HEADER_RE.match(body):
            return True
        m = FIELD_RE.match(body)
        return bool(m and m.group("key").strip() in LU_FIELD_KEYS)

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

        if (m := LU_HEADER_RE.match(body)):
            id_str = m.group("id")
            try:
                id_int = int(id_str, 16) if id_str.startswith("0x") else int(id_str)
            except ValueError:
                id_int = None
            return {
                "event": "lu_descriptor",
                "kind": "header",
                "lu_id": id_str,
                "lu_id_int": id_int,
                "is_rpmb": bool(m.group("prefix").strip()),
            }

        if (m := FIELD_RE.match(body)):
            key = m.group("key").strip()
            value = m.group("value").strip()
            return {
                "event": "lu_descriptor",
                "kind": "field",
                "key": key,
                "value": value,
            }

        return {"event": "lu_descriptor", "raw": body}
