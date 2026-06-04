"""Coerce a decoded scalar into the (value_num, value_str, unit) triple used by
the long-form metrics table. Decoded leaves are already real Python scalars, so
this is mostly: numbers -> value_num; strings -> best-effort numeric parse.

Public API:
    coerce_value(v) -> (value_num: float|None, value_str: str, unit: str)
"""
import re

_NUM_UNIT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([A-Za-z%/]+)?\s*$")
_HEX = re.compile(r"^\s*0x[0-9a-fA-F]+\s*$")


def coerce_value(v):
    if isinstance(v, bool):
        return (float(v), str(int(v)), "")
    if isinstance(v, (int, float)):
        return (float(v), str(v), "")
    s = "" if v is None else str(v)
    if _HEX.match(s):
        try:
            return (float(int(s, 16)), s, "")
        except ValueError:
            return (None, s, "")
    m = _NUM_UNIT.match(s)
    if m:
        try:
            return (float(m.group(1)), s, m.group(2) or "")
        except ValueError:
            pass
    return (None, s, "")
