"""Loads layout.json files (the AXF registry) by (product, core, build_hash).

The registry is the server's own datasource: which AXF/layout belongs to which
firmware, with all static metadata embedded. A new firmware build is a new file
(immutable, append-only); build hashes make it impossible to edit in place.
"""
import json
import os


class LayoutRegistry:
    def __init__(self, layouts_dir):
        self.dir = layouts_dir
        self.cache = {}

    def key(self, product, core, build_hash):
        return f"{product}_{core}_{build_hash}"

    def get(self, product, core, build_hash):
        """Return (layout, None) or (None, error_type) where error_type is
        NO_LAYOUT or HASH_MISMATCH."""
        k = self.key(product, core, build_hash)
        if k in self.cache:
            return self.cache[k], None
        path = os.path.join(self.dir, k + ".json")
        if not os.path.exists(path):
            return None, "NO_LAYOUT"
        layout = json.load(open(path))
        # Build-hash gate: the registry filename encodes the hash; verify the
        # embedded one matches too (defence against a mis-named file).
        if build_hash and layout.get("fw_build_hash") and layout["fw_build_hash"] != build_hash:
            return None, "HASH_MISMATCH"
        self.cache[k] = layout
        return layout, None
