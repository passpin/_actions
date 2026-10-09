# Python base implementation status

## Implemented

- `.gmd` plist/base64/gzip load and save
- clean-source byte-identical save path
- ordered raw object pairs
- duplicate/unknown property preservation
- malformed-tail preservation
- first-class raw get/set/append/remove API
- catalog-backed semantic property view
- catalog-backed constraints and conditional semantic variants
- strict typed decoding with raw fallback
- exact `GDReal`
- structured values (particle, weighted groups, sequence, group remap)
- 15 semantic ID namespaces (Group/Item/Control/Color/Block plus Force, channel, effect, material, gradient and scoped SFX IDs)
- all known `OBJ_<ID>` runtime classes generated from the catalog
- generated `.pyi` object stubs
- query/filter/update/translate/delete/copy
- selection cardinality assertions and structural selection summaries
- isolated group/item/control copy/remap
- reentrant atomic transactions
- trigger convenience builders
- level-bound GroupHandle inspection and explicit BuildScope generation helper
- level-bound `GroupHandle` scripting helpers (`move`, `call`, `toggle`, `alpha`, `rotate`, `follow`)
- `level.new.group()/groups()/item()/control()` next-free allocation facade
- references/identifier lookup and structural relation inspection
- validation
- explain/inspection JSON
- raw-level JSON import/export
- atomic patch JSON
- semantic/raw diff
- CLI
- installable wheel packaging

## Catalog baseline

At the time this base was built:

- known Object IDs: 4,073
- explicit object schemas: 385
- raw-only known IDs: 3,688
- globally known property keys: 539
- semantic ID namespaces: 15
- known-object factory metadata: 4,073 / 4,073 IDs

The runtime currently loads the existing validated `catalog.normalized.json` and adapts its legacy property `type` field into the new runtime concepts (`wire_type` + semantic metadata).

This is intentional. Migrating the source knowledge JSON to the new design is a separate data migration and should not be coupled to rewriting the runtime.

## Regression checks

The automated suite currently checks:

- all 4,073 known classes instantiate and parse back as the same `OBJ_<ID>` class
- exact number semantics
- raw/semantic shared state, including duplicate-key minimal-write behavior
- repeated structured-view mutation + stale-view protection
- duplicate and unknown raw properties
- strict bool validation with raw fallback
- query/edit behavior
- transaction rollback
- namespace allocation/reference/remap
- isolated copy
- trigger builders
- raw JSON roundtrip
- patch atomicity
- diff
- real 22,638-object fixture clean byte-identical save
- 8,677-object / 4,073-ID fixture coverage
- dirty save/reload with unknown raw data
- new `.gmd` creation
- custom-catalog trigger classification independent of global generated-class inheritance
- detached/foreign collection ownership rejection

## Deliberate next steps, not blockers for the base

1. Migrate source knowledge JSON to the new specification in `docs/design/03_JSON_KNOWLEDGE_SPEC.md`.
2. Continue scripting ergonomics work only where semantics are verified; basic gmdbuilder/G.js-inspired ID/group handles are already present.
3. Continue expanding reverse-engineered schemas beyond the current 385 explicit objects, prioritizing relationships and frequently used object families.
4. Improve independently-loaded-file object matching in semantic diff if needed.
5. Add a Geode/Geometry Dash oracle only when useful; it is not a runtime dependency.
6. Add normalization mode only after its exact semantics are justified.

## Performance note

A simple local synthetic benchmark with 100,000 minimal objects measured roughly:

- parse: 0.69 s
- one semantic query: 0.58 s
- serialize to level string: 0.04 s

This is only a development-environment sanity check, not a formal benchmark. Optimization should remain measurement-driven.

## 2026-10-08 tooling/understanding pass

The Python base was extended using ideas selectively taken from existing GD
scripting tools without adopting their ambient/global execution contexts.

- semantic ID support now includes 15 namespaces: Group / Item / Control / Color / Block / Force / Song Channel / Trigger Channel / Material / Gradient / Area Effect / Enter Effect / Enter Channel / SFX Group / scoped SFX Unique;
- source `references.json` declares ID namespaces as knowledge, rather than
  leaving namespace knowledge only in Python;
- Collision Block definitions are distinguished from trigger references;
- `GDObject.reference_details()` exposes the property evidence behind an ID
  relationship;
- `level.relations` provides namespace overviews, per-ID inspection, and
  evidence-bearing structural group tracing;
- `level.color()` / `level.block()` provide explicit level-bound handles;
- `ObjectCollection.template()` snapshots a selection for reusable generation,
  automatically isolating internal membership groups while requiring explicit
  bindings for external IDs;
- Color/Block IDs are deliberately not auto-allocated yet because their editor
  allocation/reserved-ID rules have not been modeled with enough confidence.

These additions keep Python as the execution/editing surface and JSON as the GD
knowledge layer. They do not introduce a separate scripting language or global
current-level/timeline state.

Catalog semantics were also moved further toward the design specification:

- simple numeric range facts are stored as property `constraints` and executed by
  the generic validator instead of being duplicated as Object-ID conditionals;
- property `variants` can change a property's semantic namespace from another
  property on the same object; the Stop Trigger now uses this for its
  Group-vs-Control target instead of a Python special case;
- generated stubs reflect all confirmed variant namespaces, so the Stop target is
  exposed as `int | GroupId | ControlId`.

## 2026-10-09 knowledge expansion pass

- all 4,073 known Object IDs now carry executable-factory implementation metadata;
- explicit schemas increased to 385 and global property knowledge to 539 keys;
- explicit-schema and global property confidence now have no `unknown` entries in the compiled catalog;
- Area and Enter Effect IDs are modeled as separate namespaces;
- Pulse target semantics switch between Color and Group through catalog variants;
- SFX Unique IDs are scoped by SFX Group and scoped lookup is supported;
- Force, Song/Trigger Channel, Material, Gradient and Enter Channel relationships are represented semantically;
- raw-only object explain output includes C++ implementation class/evidence;
- TeleportPortalObject and SpecialAnimGameObject families gained reverse-verified partial schemas;
- regression suite is 52 tests; both real fixtures validate with zero errors/warnings.

## 2026-10-09 Geode bridge CLI validation

- A Windows-first Geode mod and a Python `GeodeBridge` client are present.
- Python CLI now exposes `gmdtool geode --session FILE {ping,status,items,snapshot,input,reset}`.
- Native request timeouts attempt to skip not-yet-started queued game actions.
- All 63 Python tests pass, including mock-loopback protocol and CLI checks.
- Building and testing the Geode mod inside an actual Windows GD installation remains necessary.
- Frame scheduling, macro playback, screenshots, and trigger tracing are NOT implemented yet.
