"""
[_SetExtFeatureVal : <name>] Value Idx : N , Value : V

  [_SetExtFeatureVal : UFS ADVRPMB Value Set] Value Idx : 2 , Value : 32
  [_SetExtFeatureVal : UFS TWINFO Value Set] Value Idx : 0 , Value : 0
  [UFS NONFI TEST option Set] Value Idx : 8 , Value : 62482432
"""
from __future__ import annotations
import re
from typing import Any
from .base import BaseParser

PRIMARY_RE = re.compile(
    r"^\[(?:_SetExtFeatureVal\s*:\s*)?(?P<feature>[^\]]+?)\]\s*Value\s+Idx\s*:\s*(?P<idx>\d+)\s*,\s*Value\s*:\s*(?P<val>\S+)\s*$"
)


class FeatureSetParser(BaseParser):
    parser_id = "feature_set"
    priority = 12

    def can_parse(self, line: str, filename: str) -> bool:
        return "Value Idx :" in line and "Value :" in line and line.lstrip().startswith(("[", " ", "0"))

    def parse(self, line: str, filename: str) -> dict[str, Any]:
        body = re.sub(r"^\s*\d{4}:\d{2}:\d{2}\s+", "", line, count=1).strip()
        m = PRIMARY_RE.match(body)
        if not m:
            return {"event": "feature_set", "raw": body}

        feature = m.group("feature").strip()
        # If the feature came from the [_SetExtFeatureVal : X] form,
        # the leading "_SetExtFeatureVal :" is already consumed.
        result: dict[str, Any] = {
            "event": "feature_set",
            "feature": feature,
            "value_idx": int(m.group("idx")),
            "value_str": m.group("val"),
        }
        # Best-effort numeric coercion
        v = m.group("val")
        try:
            if v.startswith(("0x", "0X")):
                result["value_int"] = int(v, 16)
            else:
                result["value_int"] = int(v)
        except ValueError:
            pass
        return result
