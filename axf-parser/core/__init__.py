"""Reusable AXF-decode library for the UTA analytics pipeline.

Modules:
  dwarf_layout  - parse an AXF's DWARF into a type registry + global addresses
  segments      - derive the HW-dump segment map (coverage-driven)
  container     - the packaged per-core .bin format (header + bank payloads)
  decode        - segmented memory + decode globals to nested JSON
  flatten       - nested decode -> flat (section, key, value) leaf rows
  fw_name       - parse a firmware name into product/version/build-hash/...
"""
