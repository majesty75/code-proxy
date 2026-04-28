"""
UTF / framework metadata lines:

  >>>UTF V8_META_SIRIUS_20_APR_26_FCN_P09_RC00-2-g07ca291-dirty
  >>>UTF Commit Hash  : 07ca2915449fa701ab8afb5ba1b5045b27c73c82
  >>>UTF Commit Date  : 2026-04-20 15:40:59
  >>>UTF Commit Branch : master
  >>>Tester Build Date: 2026-04-20 19:37:27
  >>>UFS 0x20001
  >>>HostType 11 (Root)
  >>>Profile 1,0,0,1,0,0,25,0,5,0,0,0,0,0,0,0,2,3
  >>>DeviceInfo PSJ039.24.34.59.\\PSL131.18.32.127.\\...
  >>>PARAMETERS[0] Path = /share/...
"""
import re
from typing import Any
from .base import BaseParser

KV_LINE = re.compile(r"^>>>(?P<bucket>[A-Za-z]+)\s+(?P<key>[A-Za-z][\w ]*?)\s*[:=]\s*(?P<value>.+?)\s*$")
PARAMS_RE = re.compile(r"^>>>PARAMETERS\[(?P<idx>\d+)\]\s+(?P<key>\S+)\s*=\s*(?P<value>.+?)\s*$")


class UtfMetaParser(BaseParser):
    parser_id = "utf_meta"
    priority = 6

    def can_parse(self, line: str, filename: str) -> bool:
        s = self._strip_time(line)
        if not s.startswith(">>>"):
            return False
        # Skip the ones owned by test_step (priority 5 already claimed those).
        return not (
            s.startswith(">>>BEGIN") or s.startswith(">>>END")
            or s.startswith(">>>PROCESS") or s.startswith(">>>ELAPSED_TIME")
            or s.startswith(">>>SCRIPT")
        )

    @staticmethod
    def _strip_time(line: str) -> str:
        return re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        result: dict[str, Any] = {"event": "utf_meta"}
        m_time = re.match(r"^\s*(?P<t>\d{4}:\d{2}:\d{2})\s+", line)
        if m_time:
            result["log_time"] = m_time.group("t").replace("0000:", "00:", 1)

        body = self._strip_time(line)

        if (m := PARAMS_RE.match(body)):
            result.update({
                "kind": "parameter",
                "index": int(m.group("idx")),
                "key": m.group("key"),
                "value": m.group("value"),
            })
            return result

        # Profile bitmap
        if body.startswith(">>>Profile "):
            digits = body[len(">>>Profile "):].strip()
            try:
                result.update({
                    "kind": "profile",
                    "values": [int(x) for x in digits.split(",") if x.strip()],
                })
            except ValueError:
                result.update({"kind": "profile", "raw": digits})
            return result

        if body.startswith(">>>HostType "):
            rest = body[len(">>>HostType "):].strip()
            m_host = re.match(r"^(\d+)\s*\((.+)\)\s*$", rest)
            if m_host:
                result.update({"kind": "host_type", "id": int(m_host.group(1)), "name": m_host.group(2)})
            else:
                result.update({"kind": "host_type", "raw": rest})
            return result

        if body.startswith(">>>DeviceInfo "):
            result.update({"kind": "device_info", "raw": body[len(">>>DeviceInfo "):].strip()})
            return result

        if body.startswith(">>>UFS "):
            result.update({"kind": "ufs_spec", "raw": body[len(">>>UFS "):].strip()})
            return result

        # Tester build line — has a colon.
        if body.startswith(">>>Tester Build Date:"):
            result.update({
                "kind": "tester_build_date",
                "value": body.split(":", 1)[1].strip(),
            })
            return result

        # Generic >>>UTF X : Y or >>>UTF freeform
        if (m := KV_LINE.match(body)):
            result.update({
                "kind": m.group("bucket").lower(),
                "key": m.group("key").strip(),
                "value": m.group("value").strip(),
            })
            return result

        # >>>UTF V8_META_... (no colon)
        if body.startswith(">>>UTF "):
            result.update({"kind": "utf_version", "value": body[len(">>>UTF "):].strip()})
            return result

        result["raw"] = body
        return result
