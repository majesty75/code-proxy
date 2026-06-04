#!/usr/bin/env python3
"""Render a layout.json as a human-readable type tree — structure, and
optionally live values from a dump and/or C struct declarations.

The layout is a machine artifact (a type graph keyed by DWARF id) optimized for
decoding; this tool projects it into something you can read.

    python -m tools.layout_view <layout.json>                       # index of globals
    python -m tools.layout_view <layout.json> Configuration         # type tree
    python -m tools.layout_view <layout.json> Configuration --bin dump.bin   # + live values
    python -m tools.layout_view <layout.json> Configuration --c     # C struct decls
    python -m tools.layout_view <layout.json> --grep temp           # search by name
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load(path):
    return json.loads(Path(path).read_text())


def resolve(types, tid):
    seen = set()
    while tid in types and types[tid].get("tag") == "alias" and tid not in seen:
        seen.add(tid)
        tid = types[tid].get("target_id")
    return tid, types.get(tid, {})


def typename(types, tid):
    node = types.get(tid, {})
    if node.get("tag") == "alias":
        return node["name"] if node.get("name") else typename(types, node.get("target_id"))
    tag = node.get("tag")
    if tag == "base":
        return node.get("name", "?")
    if tag == "pointer":
        tgt = node.get("target_id")
        inner = typename(types, tgt) if tgt and types.get(tgt, {}).get("tag") != "unknown" else "void"
        return inner + "*"
    if tag == "array":
        dims = "".join(f"[{d}]" for d in node.get("dimensions", []))
        return typename(types, node.get("element_type_id")) + dims
    if tag in ("struct", "union"):
        return node.get("name") or f"anon_{tag}"
    if tag == "enum":
        return node.get("name") or "anon_enum"
    return tag or "?"


def total_size(types, tid):
    _, n = resolve(types, tid)
    if n.get("tag") == "array":
        elem = total_size(types, n.get("element_type_id"))
        cnt = 1
        for d in n.get("dimensions", []):
            cnt *= d
        return cnt * elem
    return n.get("size", 0)


# ---------------------------------------------------------------- value overlay
def val_str(v):
    """Concise rendering of a decoded leaf value."""
    if isinstance(v, dict):
        if "__error__" in v:
            return f"<{v['__error__']}>"
        if "@" in v:                       # pointer wrapper
            return f"-> {v['@']}"
        return "{...}"
    if isinstance(v, list):
        head = ", ".join(val_str(x) for x in v[:6])
        return f"[{head}{', …' if len(v) > 6 else ''}]"
    return str(v)


# ---------------------------------------------------------------- tree renderer
def render(types, tid, val, depth, max_depth, indent, lines):
    rtid, node = resolve(types, tid)
    if node.get("tag") not in ("struct", "union") or depth >= max_depth:
        return
    pad = "  " * indent
    for mname, m in node.get("members", {}).items():
        if mname == "_union":
            continue
        mtid = m.get("type_id")
        tn = typename(types, mtid)
        sz = total_size(types, mtid)
        off = m.get("offset", 0)
        bits = f" :{m['bit_size']}" if "bit_size" in m else ""
        mval = val.get(mname) if isinstance(val, dict) else None
        vtxt = f"  = {val_str(mval)}" if val is not None and mval is not None else ""
        lines.append(f"{pad}  +{off:<4} {mname:28} {tn}{bits}  ({sz} B){vtxt}")
        cr_tid, cr = resolve(types, mtid)
        if cr.get("tag") == "array":
            cr_tid, cr = resolve(types, cr.get("element_type_id"))
            mval = None                    # don't thread per-element values into the tree
        if cr.get("tag") in ("struct", "union"):
            render(types, cr_tid, mval, depth + 1, max_depth, indent + 1, lines)


def show_variable(L, name, max_depth, bin_path=None):
    types = L["types"]
    v = L["variables"].get(name)
    if not v:
        print(f"no such variable: {name}")
        return
    addr = v["address"]
    tn, sz = typename(types, v["type_id"]), total_size(types, v["type_id"])
    src = L.get("sources", {}).get(name, "?")
    bank = next((s for s in L["segments"] if s["base"] <= addr < s["base"] + s["size"]), None)
    bank_s = f"bank 0x{bank['base']:08x}" if bank else "NOT in any dump bank"

    val = None
    if bin_path:
        from core.decode import Memory, decode_variable
        mem = Memory.from_container(bin_path)
        val, _ = decode_variable(L, mem, name, max_depth)

    print(f"{name} @ 0x{addr:08x} : {tn}  ({sz} B)   source={src}  [{bank_s}]"
          + ("   [+live values]" if bin_path else ""))
    lines = []
    render(types, v["type_id"], val, 0, max_depth, 0, lines)
    print("\n".join(lines) if lines else "  (scalar — no members)")


# ---------------------------------------------------------------- C emitter
def _decl(types, mtid, mname, bits):
    disp = typename(types, mtid)
    if disp.endswith("*"):
        d = f"{disp[:-1].rstrip()} *{mname}"
    elif "[" in disp:
        i = disp.index("[")
        d = f"{disp[:i]} {mname}{disp[i:]}"
    else:
        d = f"{disp} {mname}"
    if bits is not None:
        d += f" : {bits}"
    return d


def emit_c(L, name):
    """Best-effort pseudo-C struct declarations for a variable's type and the
    named structs it inlines. For cross-referencing firmware headers, not
    guaranteed-compilable (types use typedef names; pointer targets are by name)."""
    types = L["types"]
    v = L["variables"].get(name)
    if not v:
        print(f"no such variable: {name}")
        return
    # Recover typedef names for anonymous structs (typedef struct {..} Name;).
    typedef_names = {}
    for tid, node in types.items():
        if node.get("tag") == "alias" and node.get("name"):
            rtid, _ = resolve(types, tid)
            typedef_names.setdefault(rtid, node["name"])

    def sname(rtid, node):
        return node.get("name") or typedef_names.get(rtid) or "anon"

    emitted, order = set(), []

    def visit(tid):
        rtid, node = resolve(types, tid)
        tag = node.get("tag")
        if tag == "array":
            return visit(node.get("element_type_id"))
        if tag not in ("struct", "union") or rtid in emitted:
            return
        emitted.add(rtid)
        # define inlined named struct members first (post-order)
        for m in node.get("members", {}).values():
            cr_tid, cr = resolve(types, m.get("type_id"))
            if cr.get("tag") == "array":
                cr_tid, cr = resolve(types, cr.get("element_type_id"))
            if cr.get("tag") in ("struct", "union") and cr.get("name"):
                visit(cr_tid)
        order.append((rtid, node))

    visit(v["type_id"])
    print(f"// pseudo-C for {name} — cross-reference only, types use typedef names\n")
    for rtid, node in order:
        kw = "union" if node.get("tag") == "union" else "struct"
        print(f"{kw} {sname(rtid, node)} {{    // {node.get('size',0)} bytes")
        for mname, m in node.get("members", {}).items():
            if mname == "_union":
                continue
            print(f"    {_decl(types, m.get('type_id'), mname, m.get('bit_size')):44};"
                  f"  // +{m.get('offset',0)}")
        print("};\n")


def show_index(L, grep=None):
    types = L["types"]
    print(f"# {L.get('product')}/{L.get('core')} build {L.get('fw_build_hash')} "
          f"— {len(L['variables'])} globals")
    rows = [(n, v["address"], typename(types, v["type_id"]), total_size(types, v["type_id"]))
            for n, v in L["variables"].items()
            if not grep or grep.lower() in n.lower()]
    for n, addr, tn, sz in sorted(rows, key=lambda r: r[1]):
        print(f"  0x{addr:08x}  {n:34} {tn:24} {sz:>7} B")
    print(f"# {len(rows)} shown")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--grep")
    ap.add_argument("--bin", help="container dump to overlay live values")
    ap.add_argument("--c", action="store_true", help="emit pseudo-C struct decls")
    ap.add_argument("--depth", type=int, default=3)
    args = ap.parse_args()
    L = load(args.layout)
    if args.symbol and args.c:
        emit_c(L, args.symbol)
    elif args.symbol:
        show_variable(L, args.symbol, args.depth, args.bin)
    else:
        show_index(L, args.grep)


if __name__ == "__main__":
    main()
