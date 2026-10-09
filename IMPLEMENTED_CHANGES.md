# Implemented changes — knowledge/understanding pass

This pass expands Geometry Dash knowledge first, then connects that knowledge to
Python inspection/editing APIs. It keeps JSON as the knowledge layer and normal
Python objects as the main work surface.

## Knowledge coverage

Current compiled catalog:

- 4,073 known Object IDs
- 385 explicit object schemas
- 539 global serialized property definitions
- 15 semantic ID namespaces
- 6 reusable schema fragments
- 8 registered knowledge/evidence sources
- 4,455 expanded explicit-schema properties
- 0 explicit-schema properties with `unknown` confidence
- 0 global property definitions with `unknown` confidence

`known_objects.json` records factory-derived implementation metadata for all 4,073
known IDs, including the C++ implementation class and executable evidence. Raw-only
objects therefore still expose a useful implementation classification in
`object_name` / `explain()`.

## ID and relationship knowledge

The semantic namespaces are:

- Group, Item, Control
- Color Channel, Collision Block
- Force, Song Channel, Trigger Channel, Material, Gradient
- Area Effect, Enter Effect, Enter Channel
- SFX Group and scoped SFX Unique ID

The runtime distinguishes membership, identifier/definition, and reference roles.
Examples include Force-block membership, Song-channel definition/reference,
Gradient IDs plus Group vertices, and separate Area/Enter Effect ID spaces.

SFX Unique IDs are explicitly scoped by SFX Group. `references()` and
`identifiers()` accept `scope={"sfx_group": ...}`, and relationship details carry
that scope evidence instead of pretending the Unique ID is globally unique.

## Conditional semantics

Catalog `variants` now drive context-sensitive meanings rather than Python
Object-ID special cases where possible:

- Stop target: Group vs Control ID
- Pulse target: Color Channel vs Group

Area/Enter effect families use distinct ID namespaces. Pre-made Enter Effect
objects 22–28 and 55–59 now have explicit names/schemas and Enter Channel
references.

## Reverse-engineered class knowledge

Local Geometry Dash 2.2081 Broma/executable evidence was used to raise provenance
for serializer/parser-backed properties and fragments. In addition to existing
trigger families, this pass adds partial schemas for:

- Unlinked Orange/Blue Teleport Portals (17 TeleportPortalObject properties)
- Fireball Particle Animation 1/2 and Explosion Animation
  (`SpecialAnimGameObject` animation-shine property)

Objects whose special implementation class has no distinct serialized properties
remain raw-only instead of receiving a fake schema. A small set of such objects
now has community-corroborated human names without changing schema status.

## Existing-level understanding APIs

- `ObjectCollection.expect()` and `describe()` for safe selection inspection
- `level.relations` for namespace usage, per-ID inspection, and group relation tracing
- `GDObject.reference_details()` with property/key evidence and scoped-ID context
- `GDObject.identifier_details()` for definition evidence and scoped-ID context
- generic `members()` for Group, Enter Channel, Material, Force, SFX Group, etc.
- raw-only `explain()` now exposes factory `cpp_class`, implementation sources, and
  implementation evidence

Universal semantics are pre-indexed in the catalog so raw-only objects can
participate in safe common relationships (for example Group membership and Color
references) without scanning the full global property table for every object.

## Generation/tooling ergonomics retained

- explicit `level.scope(...)` construction helper
- level-bound Group/Color/Block handles
- reusable frozen `ObjectTemplate`
- no global current-level/timeline state and no second scripting language

## Verification

- 52 pytest tests pass
- catalog build/check, sync check, generated-stub check, and `compileall` pass
- 4,073 generated `OBJ_<ID>` classes remain available
- real `2048 game preview` fixture: 22,638 objects / 28 IDs / 0 errors / 0 warnings
- real Object IDs fixture: 8,677 objects / 4,073 IDs / 0 errors / 0 warnings
