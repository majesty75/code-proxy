"""Flatten a nested decode into flat leaf rows for the long-form metrics table.

Each scalar leaf becomes {"section": <top-level group>, "key": "<dotted.path>",
"value": <python scalar>}. Arrays use the index in the path
(counters[0].value -> "counters.0.value"). Pointer wrappers ({"@":..,"->":..})
are transparently followed. Decode-error leaves ({"__error__":..}) are dropped.

Public API:
    flatten(decoded) -> list[{"section","key","value"}]
"""


def _walk(node, prefix, section, out):
    if isinstance(node, dict):
        if "__error__" in node:
            return                                  # not-in-dump / undecodable
        if "->" in node and "@" in node:            # pointer wrapper -> follow target
            _walk(node["->"], prefix, section, out)
            return
        for k, v in node.items():
            if k in ("_union",):
                continue
            key = f"{prefix}.{k}" if prefix else k
            _walk(v, key, section or k, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            key = f"{prefix}.{i}" if prefix else str(i)
            _walk(v, key, section, out)
    else:
        if isinstance(node, bool):
            node = int(node)
        out.append({"section": section or "", "key": prefix, "value": node})


def flatten(decoded):
    out = []
    for name, value in decoded.items():
        _walk(value, name, name, out)
    return out
