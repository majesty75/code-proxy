"""Per-field preprocessing hooks for the ingestion layer.

Decoding stays raw (the decoded_json archive is the faithful ML source). These
transforms run only on the CURATED metrics on their way into axf_metrics, so you
can convert units, decode bitfields, map codes to labels, or compute derived
metrics from several fields — without changing the decoder or the schema.

Define functions in config/transforms.py and reference them by name in
variables.yaml (transform: <name>). Signature:

    from core.transforms import register

    @register("temp_to_celsius")
    def temp_to_celsius(value, ctx):
        # value = the raw decoded value of this field
        # ctx   = dict of ALL decoded leaves for this dump {key: value}
        return value - 273

    @register("wear_ratio")
    def wear_ratio(value, ctx):           # derived metric (no source field)
        waf, wai = ctx.get("smart.waf"), ctx.get("smart.wai")
        return waf / wai if wai else None

A transform returns either a scalar (then coerce decides value_num/unit) or a
(value_num, value_str, unit) triple for full control. Return None to drop it.
"""
import importlib.util
import os

_REGISTRY = {}


def register(name):
    def deco(fn):
        _REGISTRY[name] = fn
        return fn
    return deco


# --- a few generic built-ins (available without a user file) ----------------
@register("hex")
def _hex(value, ctx):
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else value


@register("kib")
def _kib(value, ctx):
    return value / 1024 if isinstance(value, (int, float)) else None


@register("mib")
def _mib(value, ctx):
    return value / (1024 * 1024) if isinstance(value, (int, float)) else None


def load(path=None):
    """Import a user transforms file (it calls @register at import time) and
    return the name->fn registry. Missing path -> just the built-ins."""
    if path and os.path.exists(path):
        spec = importlib.util.spec_from_file_location("uta_user_transforms", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return dict(_REGISTRY)
