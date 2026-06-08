# 06 — Configuration

What you edit day to day: which metrics to curate, how to preprocess them, and the
service environment. None of this requires a code rebuild — only a service
restart (the `config/` directory is live-mounted).

## `config/variables.yaml` — curated metrics

Selects the 10–50 keys per `(product, core)` promoted to `axf_metrics`. Everything
else stays in `axf_snapshots.decoded_json`. Keys are the **dotted leaf paths**
from `core.flatten` (the same paths `decode_cli --flat` and `layout_view` show).

```yaml
PRODUCT:
  CORE:
    # 1. plain key — raw value, coerced to number/unit automatically
    - smart.wai

    # 2. key + transform + unit override
    - key: temp.case
      transform: temp_to_celsius
      unit: C

    # 3. derived metric — no source field; computed from other leaves
    - derived: wear_ratio
      transform: wear_ratio
      section: smart
```

For C++ products the key is the **fully-qualified** path, e.g.
`UHP::CEXEType::gstCexeContext.someField` — the same string TRACE32 and
`layout_view` show.

Entry forms:
| form | meaning |
|---|---|
| `- some.key` | curate the raw value |
| `- {key, transform?, unit?}` | curate a field, optionally preprocess / set unit |
| `- {derived, transform, section?, unit?}` | a computed metric with no direct source field |

## `config/transforms.py` — per-field preprocessing

Custom Python applied **only on the curated path** into `axf_metrics`. The raw
decode and `decoded_json` archive are untouched (faithful / re-derivable).

```python
from core.transforms import register

@register("temp_to_celsius")
def temp_to_celsius(value, ctx):
    # value = this field's raw decoded value
    # ctx   = dict of ALL decoded leaves for this dump {key: value}
    return value - 273

@register("wear_ratio")
def wear_ratio(value, ctx):            # derived: value is None
    waf, wai = ctx.get("smart.waf"), ctx.get("smart.wai")
    return waf / wai if wai else None
```

Contract:
- **Signature:** `fn(value, ctx)`. `value` is the field's raw value (`None` for a
  `derived` entry). `ctx` is every decoded leaf, so transforms can combine fields.
- **Return:** a scalar (then `coerce_value` decides `value_num`/`unit`), or a
  `(value_num, value_str, unit)` triple for full control, or `None` to drop it.
- **Errors are caught.** A throwing transform is logged and the metric skipped —
  one bad field never sinks the dump.

Built-ins (in `core/transforms.py`, always available): `hex`, `kib`, `mib`.

### Common real-firmware patterns
```python
@register("u64_from_hilo")            # combine two 32-bit halves
def u64_from_hilo(value, ctx):
    hi = ctx.get("ctr.bytes_written_hi") or 0
    lo = ctx.get("ctr.bytes_written_lo") or 0
    return (hi << 32) | lo

@register("flag_bit3")                # extract a status bit
def flag_bit3(value, ctx):
    return (value >> 3) & 1

@register("state_label")              # map an enum code to a label string
def state_label(value, ctx):
    return {0: "IDLE", 1: "BUSY", 2: "ERR"}.get(value, str(value))
```

### Edit/reload loop
`config/` is mounted into the decode service. After editing `variables.yaml` or
`transforms.py`: `docker compose restart decode_service`. (A *first-time* change
to the service's own Python wiring needs `--build`; editing config does not.)

## Service environment (`services/decode_service/config.py`)

| var | default | meaning |
|---|---|---|
| `NATS_URL` | `nats://nats:4222` | JetStream connection |
| `NATS_STREAM` / `NATS_CONSUMER` / `NATS_OBJ_BUCKET` | `UTA_AXF` / `AXF_DECODER` / `AXF_BINS` | JetStream resources |
| `LAYOUTS_DIR` | `/app/config/layouts` | the AXF registry |
| `VARIABLES_YAML` | `/app/config/variables.yaml` | curated keys |
| `TRANSFORMS_PY` | `/app/config/transforms.py` | preprocessing functions |
| `UTA_SQLITE` | `""` | path to UTA's SQLite (read-only); empty ⇒ demo fallback to event fields |
| `CH_HOST/PORT/DB/USER/PASS` | `clickhouse/8123/uta/default/…` | ClickHouse |
| `MAX_DEREF_DEPTH` | `4` | pointer-follow depth cap |
| `FETCH_BATCH` | `10` | messages pulled per fetch |

Dump agent (`services/dump_agent/config.py`): `WATCH_DIR` (`/dropzone`),
`NATS_URL`, `NATS_OBJ_BUCKET`, `SERVER_IP`, `POLL_SECONDS`, `STABLE_SECONDS`
(group settle time before packaging).

`docker-compose.yml` reads `UTA_SQLITE` from `.env` (see `.env.example`).

## Tuning the dump set (per product)

In `core/segments.py`:
- `SRAM_NIBBLES = (0x00000000, 0x20000000, 0x90000000)` — on-chip RAM apertures.
  Add a nibble if your product places SRAM elsewhere.
- `DEFAULT_EXCLUDE = [(0x60000000, 0x80000000)]` — off-chip DRAM aperture skipped.
  Adjust if a needed pool lives there (or pass behaviour through if you make it
  configurable).

After changing these, re-run `build_layout` and re-check the census / `!! REVIEW`.

## Future: content-based AXF routing

Routing currently uses the build hash from UTA's `fwname`. When firmware exposes a
**fixed-address build-info block** (magic + product + version + hash) readable
without a layout, add a step in `layout_registry`/`decode_service` to read that
block from the container and verify it against the routed layout — closing the
loop so a wrong AXF is rejected from the *dump content*, not just the paperwork.
The architecture leaves a clean seam for this.
