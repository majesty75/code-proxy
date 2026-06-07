"""User-defined per-field preprocessing for the curated metrics.

Edit this file to add transforms; reference them by name in variables.yaml
(transform: <name>). Each gets (value, ctx): the raw decoded value of the
field, and a dict of ALL decoded leaves for the dump so you can combine fields.
Return a scalar, or a (value_num, value_str, unit) triple, or None to drop it.

core/transforms.py already ships generic built-ins: hex, kib, mib.
"""
from core.transforms import register


# --- examples (used by the RTEMS demo in variables.yaml) --------------------
@register("workspace_kib")
def workspace_kib(value, ctx):
    """Derived metric: RTEMS workspace size in KiB."""
    v = ctx.get("Configuration.work_space_size")
    if v is None:
        return None
    return (v / 1024, f"{v/1024:.1f}", "KiB")


@register("tick_hz")
def tick_hz(value, ctx):
    """Derived: tick frequency (Hz) from microseconds_per_tick."""
    us = ctx.get("Configuration.microseconds_per_tick")
    return (1_000_000 / us) if us else None


# --- patterns you'll likely need for real SSD firmware ----------------------
# @register("temp_to_celsius")
# def temp_to_celsius(value, ctx):
#     return value - 273                      # raw kelvin code -> Celsius
#
# @register("u64_from_hilo")
# def u64_from_hilo(value, ctx):              # combine two 32-bit halves
#     hi = ctx.get("counters.bytes_written_hi") or 0
#     lo = ctx.get("counters.bytes_written_lo") or 0
#     return (hi << 32) | lo
#
# @register("flag_bit3")
# def flag_bit3(value, ctx):
#     return (value >> 3) & 1                  # extract a status bit
