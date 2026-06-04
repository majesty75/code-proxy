"""Parse a firmware name into structured metadata.

Example:
  SAPPHIRE_SIRIUS_EVT1_UFS_3_1_V8_TLC_512Gb_ATM_512GB_P52_RC07_FW00_1ffe5b4ef_20250521.bin

The build hash is the key field: it routes a dump to its AXF layout. It is the
hex token immediately before the trailing YYYYMMDD date.

Public API:
    parse_fw_name(name) -> dict   (always returns; missing fields are "")
"""
import re

_DATE = re.compile(r"(\d{8})(?:\.\w+)?$")
# build hash: a hex token (>=6 hex chars, must contain a..f to avoid matching a
# pure-decimal field) sitting right before the trailing date.
_HASH = re.compile(r"_([0-9a-fA-F]{6,})_(\d{8})(?:\.\w+)?$")

_FIELDS = (
    ("product_version", r"_(V\d+)_"),
    ("nand_type",       r"_(SLC|MLC|TLC|QLC)_"),
    ("nand_density",    r"_(\d+[KMGT]b)_"),
    ("patch_version",   r"_(P\d+)_"),
    ("release_candidate", r"_(RC\d+)_"),
    ("firmware_version", r"_(FW\d+)_"),
)


def parse_fw_name(name: str) -> dict:
    out = {
        "fw_name": name,
        "product": "",
        "product_version": "",
        "fw_build_hash": "",
        "nand_type": "",
        "nand_density": "",
        "patch_version": "",
        "release_candidate": "",
        "firmware_version": "",
        "fw_date": "",
    }
    clean = name
    tokens = clean.split("_")
    if tokens:
        out["product"] = tokens[0]                  # leading token = product family

    m = _HASH.search(clean)
    if m:
        # guard: a build hash should contain at least one a-f hex letter
        if re.search(r"[a-fA-F]", m.group(1)):
            out["fw_build_hash"] = m.group(1).lower()
        out["fw_date"] = m.group(2)
    else:
        d = _DATE.search(clean)
        if d:
            out["fw_date"] = d.group(1)

    for field, pat in _FIELDS:
        mm = re.search(pat, clean)
        if mm:
            out[field] = mm.group(1)
    return out
