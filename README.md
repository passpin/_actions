# gmdtool

`gmdtool` is an **AI-first, data-driven Python toolkit** for inspecting, editing, validating, and procedurally generating Geometry Dash `.gmd` levels without hiding the underlying raw object data.

The project is organized around a simple AI-facing split:

- **JSON is the Geometry Dash knowledge database**: Object IDs, properties, ID namespaces, constraints, variants, provenance, and implementation evidence;
- **Python objects are the normal analysis/editing/generation surface**;
- raw object properties remain available as an escape hatch when knowledge is incomplete;
- schema knowledge helps interpretation but is **not a whitelist**;
- existing levels can be inspected structurally through semantic relationships without inventing runtime behavior the catalog does not know.

The detailed design documents are under `docs/design/`.

## Current base

The included catalog currently contains:

- 4,073 known Object IDs, all with executable-factory implementation metadata;
- 385 explicit object schemas plus raw-only classes for every remaining known ID;
- 539 globally known serialized property keys;
- 15 semantic ID namespaces;
- 6 reusable schema fragments;
- provenance/confidence on every compiled explicit-schema property (no `unknown` confidence remains in the current compiled object schemas).

The runtime generates `OBJ_<ID>` classes for every known Object ID. Objects without a detailed schema are still fully raw-editable.

## Install for development

From a source checkout, install the package in editable mode before running the
examples or CLI:

```bash
python -m pip install -e .
python examples/procedural_level.py
```

A built wheel can instead be installed with `python -m pip install <wheel>`.

## Quick start

```python
from gmdtool import GDLevel, OBJ_1, OBJ_901

level = GDLevel.load("input.gmd")

# Semantic edit: catalog-backed property name.
for move in level.objects.filter(901, target_group=42):
    move.move_x = 120

# Raw edit: schema knowledge is not required.
obj = level.objects.first()
obj.set_raw(9999, "123456789")

# Procedural generation uses ordinary Python.
for i in range(100):
    level.add(OBJ_1(x=i * 30, y=300))

# Convenience trigger helper.
level.move(target=42, x=90, duration="0.5", at=(300, 300))

report = level.validate()
report.raise_for_errors()
level.save("output.gmd")
```

## Raw and semantic views

An object keeps its ordered raw pairs, including duplicate and unknown keys:

```python
obj.get_raw(28)
obj.get_all_raw(28)
obj.set_raw(28, "120")
obj.append_raw(9999, "abc")
obj.raw_pairs
```

Catalog-backed access is layered on the same pairs:

```python
obj.move_x = 120
assert obj.get_raw(28) == "120"

obj.set_raw(28, "45")
assert str(obj.move_x) == "45"
```

## Query and batch edit

```python
moves = level.objects.filter(901, target_group=42)
moves.update(move_x=120)
moves.translate(30, 0)

# Python callables can transform current values.
moves.update(move_x=lambda value: value + 30)
```

For edits where selecting the wrong objects would be dangerous, assert the
selection before mutating it:

```python
moves = level.objects.filter(901, target_group=42).expect(at_most=12)
print(moves.describe())
moves.update(move_x=120)
```

`describe()` returns JSON-serializable structural information: object counts,
position bounds, group memberships, and semantic ID references. Color Channel and
Collision Block IDs are first-class alongside Group/Item/Control IDs where the
knowledge catalog has confirmed semantics.

## IDs and references

ID namespaces are semantically distinct. The catalog currently models Group, Item,
Control, Color, Collision Block, Force, Song Channel, Trigger Channel, Material,
Gradient, Area Effect, Enter Effect, Enter Channel, SFX Group, and scoped SFX Unique
IDs. Group, Item, and Control support next-free allocation; other namespaces are
understood for typing/relationships/remapping but are not generically auto-allocated
until their editor allocation rules are modeled explicitly.

```python
# Existing low-level allocators remain available.
group_id = level.new_group()
item = level.new_item()
control = level.new_control()

# Scripting-friendly allocator/handle. The handle is still a GroupId/int.
group = level.new.group()
group.move(x=30, duration="0.5")
group.alpha("0.5", duration="0.2")
group.call(delay="0.1")

users = level.references(group=42)
level.remap_groups({42: 100})

# Level-bound handles also inspect existing structure.
info = level.group(42).describe()
color_info = level.color(12).describe()
block_info = level.block(5).describe()

# Definitions and references are distinct for namespaces that need it.
block_definitions = level.identifiers(block=5)
block_users = level.references(block=5)

# Scoped IDs keep their context. SFX Unique ID 1 in group 5 is distinct
# from Unique ID 1 in group 6.
sfx = level.references("sfx_unique", 1, scope={"sfx_group": 5})
```

## Scripting ergonomics

The small scripting layer is intentionally level-bound rather than global:

```python
group = level.new.group()   # next-free ID + level-bound GroupHandle
block = level.add(OBJ_1(x=0, y=0))
group.add(block)

group.move(x=90, duration="0.5")
group.toggle(True)
group.call(delay="0.2")
```

`GroupHandle` is a subclass of `GroupId`, so it remains usable anywhere a
normal integer group ID is accepted. It does **not** hide a global current
level or trigger context. Bulk allocation is also explicit:

```python
a, b, c = level.new.groups(3)
items = level.new.items(20)
```

The design borrows useful ergonomics from existing GD scripting tools while
keeping state local to each `GDLevel`. See `docs/ARCHITECTURE_REVIEW.md`.


## Structural relationships

For understanding an existing level, relationship inspection stays separate
from runtime/control-flow claims:

```python
# Compact usage counts for IDs in one namespace.
groups = level.relations.overview("group")
blocks = level.relations.overview("block")
enter_channels = level.relations.overview("enter_channel")

# Inspect one ID and the objects that define/reference it.
info = level.relations.id("block", 5)

# Follow structural group-to-group references with property evidence.
trace = level.relations.trace_group(42, depth=2)
```

Edges report the object, property key/name, and source/target groups that
produced them. They are deliberately described as structural relationships,
not automatically interpreted as Geometry Dash execution order.

## Reusable object templates

Selections can be frozen into reusable snapshots without introducing a custom
scripting language or hidden trigger context:

```python
template = level.in_group(42).template()

copy_a = template.instantiate(level, dx=300)
copy_b = template.instantiate(
    level,
    dx=600,
    bind_groups={99: 500},
    bind_colors={12: 22},
)
```

Membership Group IDs inside the snapshot are isolated automatically on every
instantiation. External IDs remain unchanged unless the caller explicitly
binds them.

## Explicit construction scopes

For repeated procedural generation, `BuildScope` applies common group
memberships and coordinate offsets without a process-global current level or
implicit auto-append state:

```python
group = level.new.group()
build = level.scope(groups=[group], dx=300)

build.create(1, x=0, y=0)
build.trigger(901, at=(30, 0), target_group=group, move_x=90)
```

## AI-facing inspection

```python
level.summary()
obj.explain()
level.explain(901, target_group=42)
level.to_raw_json()
```

These results are JSON-serializable so an agent can inspect data and construct edits without parsing Python reprs.

## Patch / diff

Simple declarative edits can use patch JSON:

```python
result = level.apply_patch({
    "format": "gmdtool.patch",
    "version": 1,
    "operations": [
        {
            "op": "update",
            "select": {
                "object_id": 901,
                "properties": {"target_group": 42}
            },
            "set": {"move_x": 120}
        }
    ]
})
```

For loops, conditions, math, and procedural generation, use normal Python rather than extending the patch format into another programming language.

```python
before = level.clone()
# ... mutate level ...
diff = before.diff(level)
```

## CLI

```bash
gmdtool inspect "level.gmd"
gmdtool explain "level.gmd" --id 901 --limit 5
gmdtool validate "level.gmd"
gmdtool raw-export "level.gmd" -o level.raw.json
gmdtool patch "level.gmd" patch.json -o edited.gmd
gmdtool catalog --validate
```

All machine-readable CLI output can be emitted as JSON.

## Catalog architecture

The runtime currently consumes `gmdtool/data/catalog.normalized.json`, copied from the validated catalog produced by the previous implementation. The source catalog remains under `data/` and the reverse-engineering tools remain under `tools/reverse/`.

A later data migration can reshape the source files to the new knowledge specification in `docs/design/03_JSON_KNOWLEDGE_SPEC.md` without changing the fundamental runtime model.

## Optional Geode runtime bridge (experimental)

A Windows-first Geode mod (`geode/gmdtool_bridge/`) and Python client
(`gmdtool/geode_bridge.py`) communicate over authenticated local TCP.
They expose game state, selected Item values, reset, immediate button input,
and an experimental callback-indexed input queue. This queue uses counts of
`PlayLayer::postUpdate` callbacks **not** GD physics ticks or GDR/GDR2 frames.
Core `.gmd` editing remains independent of Geode.

```shell
gmdtool geode --session path/to/bridge-session.json ping
gmdtool geode --session path/to/bridge-session.json status
gmdtool geode --session path/to/bridge-session.json items 1 2 3
gmdtool geode --session path/to/bridge-session.json queue-status
```

**The native mod has not yet been built/tested inside actual Geometry Dash.**
See [docs/GEODE_BRIDGE.md](docs/GEODE_BRIDGE.md) for installation instructions,
API examples, known limitations and the next steps toward tick-accurate replay,
trigger tracing, controlled execution, and screenshots.

## Development

```bash
python -m pytest
python tools/validate_catalog.py
python tools/sync_catalog.py --check
python tools/generate_stubs.py --check
```

The regression suite uses real exported levels, especially `2048 game preview.gmd` and `Object_IDs.gmd.txt`, rather than relying only on synthetic objects.


### Geode mod packaging (passpin)

The C++ mod author is `passpin`. See `geode/gmdtool_bridge/BUILD.md`. The repository includes a Windows GitHub Actions build workflow at `.github/workflows/build-geode.yml`; no precompiled `.geode` is bundled.

### Geode runtime connectivity diagnostics

`ping` only verifies the transport (no main-thread involvement).
Use `gmdtool geode --session <path> bridge-health` to inspect main-thread
dispatch counters if `status` / `items` returns a timeout. See
`docs/RUNTIME_BRIDGE_DIAGNOSTICS.md`.
