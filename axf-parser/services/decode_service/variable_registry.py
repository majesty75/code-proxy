"""Selects the curated 10-50 keys per (product, core) that get promoted to the
long-form axf_metrics table for dashboards, applying optional per-field Python
preprocessing (transforms) on the way in.

variables.yaml entry forms (all under PRODUCT -> CORE -> list):
    - smart.wai                              # plain key, raw value
    - key: temp.case                         # key + transform + unit override
      transform: temp_to_celsius
      unit: C
    - derived: wear_ratio                     # computed metric (no source field)
      transform: wear_ratio
      section: smart

A transform (see core/transforms.py) gets (raw_value, ctx) where ctx is every
decoded leaf for the dump, so it can combine fields. Returns a scalar or a
(value_num, value_str, unit) triple; None drops the metric.
"""
import logging

import yaml

from core.coerce import coerce_value

log = logging.getLogger("decode_service")


class VariableRegistry:
    def __init__(self, path, transforms=None):
        with open(path) as f:
            self.map = yaml.safe_load(f) or {}
        self.transforms = transforms or {}

    def _entries(self, product, core):
        entries = (self.map.get(product, {}) or {}).get(core, []) or []
        for e in entries:
            yield {"key": e} if isinstance(e, str) else dict(e)

    def select(self, product, core, leaves):
        entries = list(self._entries(product, core))
        if not entries:
            return []
        ctx = {leaf["key"]: leaf["value"] for leaf in leaves}
        sect = {leaf["key"]: leaf["section"] for leaf in leaves}

        out = []
        for e in entries:
            derived = e.get("derived")
            key = e.get("key")
            if derived:
                out_key, section, src = derived, e.get("section", "derived"), None
            else:
                if key not in ctx:                 # not present in this dump
                    continue
                out_key, section, src = key, sect.get(key, ""), ctx[key]

            result = src
            tname = e.get("transform")
            if tname:
                fn = self.transforms.get(tname)
                if fn is None:
                    log.warning("unknown transform '%s' for key %s", tname, out_key)
                    continue
                try:
                    result = fn(src, ctx)
                except Exception as ex:
                    log.warning("transform '%s' failed on %s: %s", tname, out_key, ex)
                    continue
            if result is None:
                continue

            if isinstance(result, tuple) and len(result) == 3:
                vnum, vstr, unit = result
            else:
                vnum, vstr, unit = coerce_value(result)
            if e.get("unit"):
                unit = e["unit"]
            out.append({"section": section, "key": out_key,
                        "value_num": vnum, "value_str": vstr, "unit": unit})
        return out
