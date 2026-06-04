"""Selects the curated 10-50 keys per (product, core) that get promoted to the
long-form axf_metrics table for dashboards. Everything else is decoded and kept
in axf_snapshots.decoded_json; a new curated key can be backfilled from there
with no schema change.
"""
import yaml

from core.coerce import coerce_value


class VariableRegistry:
    def __init__(self, path):
        with open(path) as f:
            self.map = yaml.safe_load(f) or {}

    def wanted(self, product, core):
        entries = (self.map.get(product, {}) or {}).get(core, []) or []
        return {e["key"] if isinstance(e, dict) else e for e in entries}

    def select(self, product, core, leaves):
        wanted = self.wanted(product, core)
        if not wanted:
            return []
        out = []
        for leaf in leaves:
            if leaf["key"] in wanted:
                vnum, vstr, unit = coerce_value(leaf["value"])
                out.append({
                    "section": leaf["section"], "key": leaf["key"],
                    "value_num": vnum, "value_str": vstr, "unit": unit,
                })
        return out
