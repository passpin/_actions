# Architecture review — Python base

This review focuses on correctness, reviewability, and scripting ergonomics. It
also compares a few existing Geometry Dash tooling approaches. The project does
not copy their implementations; it uses them as design references.

## Current structure verdict

The package is intentionally fairly flat. That is a good fit at the current
size (~4k handwritten Python lines): each module has a recognizable subject and
there is no service/repository/factory/plugin scaffolding.

The two largest files are `object.py` and `level.py`. They are larger than the
other modules, but splitting them immediately would mostly create more cross-
module navigation and circular-import pressure. Keep their internal section
boundaries clear and only extract a subsystem when it has a genuinely separate
state model or public API.

A new `scripting.py` module is justified because scripting handles are optional
convenience objects layered over the core level/object model; they should not
become raw storage responsibilities.

## Review fixes made

### 1. Semantic writes preserve shadowed duplicate keys

Raw reads and semantic reads use the last occurrence of a duplicate property.
Previously, a semantic write updated *every* duplicate occurrence. This was
inconsistent with raw `set_raw()` and changed data that was not semantically
active.

Now semantic writes update only the effective (last) occurrence and leave
shadowed duplicates intact.

### 2. Structured views can be edited repeatedly

A structured view (`GDSequenceList`, weighted groups, remaps, particles) keeps a
staleness guard so an old view cannot overwrite a newer raw value. The original
closure remembered only the raw value from initial decode, so a second valid
mutation through the *same* view falsely appeared stale.

The expected raw value is now advanced after each successful mutation. External
raw mutation still invalidates the old view as intended.

### 3. Trigger classification follows the level catalog

Generated `OBJ_<ID>` classes live in a process-global registry. A custom catalog
could classify an ID as a trigger after that ID had already been generated as a
plain object. Checking only `issubclass(cls, Trigger)` therefore made custom
catalog behavior inconsistent.

`GDLevel.trigger()` now resolves trigger-ness from the level's catalog. Python
class inheritance remains a convenience for the default catalog, not the source
of semantic truth.

### 4. ObjectCollection cannot silently contain detached/foreign objects

Batch operations are transactional with respect to their owning `GDLevel`.
Allowing callers to construct a collection containing detached objects would
make those mutations fall outside the level snapshot. The constructor now
rejects objects not owned by its level.

### 5. Object trigger semantics prefer the owning catalog

Generated `OBJ_<ID>` inheritance is a convenience from the process-global
registry; it is not semantic truth. `GDObject.is_trigger` now prefers the
object's active catalog whenever that catalog has a schema for the ID. This also
keeps `add_triggers()` correct with custom catalogs instead of leaking default-
catalog class inheritance into level semantics.

## External tool ideas considered

### gmdbuilder

Useful ideas:

- `level.new.group()` style next-free allocation;
- mutation validation/autoscan;
- direct editing plus wrappers rather than forcing one abstraction;
- Python itself remains the scripting language.

Adopted here:

- `level.new.group()`, `.groups(n)`, `.item()`, `.control()` style explicit,
  level-scoped allocation;
- `level.scope(...)` for explicit construction defaults (groups/offsets) without
  ambient context or implicit auto-append.

Not adopted yet:

- implicit `autoappend`/target contexts. They reduce keystrokes, but hidden
  ambient state is harder for an AI agent and reviewer to reason about.

Reference: https://github.com/LXtreme/gmdbuilder

### G.js

Useful ideas:

- group values behave as handles with methods (`move`, `call`, etc.);
- next-free IDs are convenient during procedural generation;
- trigger functions can make complex spawn chains compact.

Adopted here:

- `GroupHandle`, bound explicitly to one `GDLevel`, with `move`, `call`,
  `toggle`, `alpha`, `rotate`, and `follow` convenience methods.

Deliberately different:

- G.js uses substantial global/current-context state. gmdtool keeps the handle's
  owner level explicit and does not currently implement a global trigger
  context. A trigger-function/timeline abstraction should only be added after
  its GD semantics are verified against real output.

Reference: https://github.com/g-js-api/G.js

### gmdkit

Useful ideas:

- direct object-list operations and callable transforms are simple and Pythonic.

gmdtool already has comparable `ObjectCollection.filter/where/apply/update`
operations, but keeps its ordered raw-pair representation because preserving
unknown/duplicate data is a primary requirement.

Reference: https://github.com/UHDanke/gmdkit

### gmd_api

Useful idea:

- fluent object transforms make generated code readable.

gmdtool already returns `self` from mutators such as `set`, `set_raw`,
`translate`, `move_to`, and group mutation, so fluent construction can be used
without introducing a parallel object model.

Reference: https://github.com/veprogames/gmd_api

### gdparse

Useful idea for later:

- explicit level-format/version detection can be valuable when supporting old
  level formats.

It is not needed for the present 2.2-focused base and should not complicate the
core until real fixtures require it.

Reference: https://github.com/kuzheren/gdparse

### GDShare / GMD-API

Useful format boundary:

- current `.gmd` is level data wrapped in the GDShare plist/container format;
- `.lvl` and `.gmd2` use different container/encoding paths and should not be
  silently treated as aliases of `.gmd`;
- support for those formats belongs in the IO/container layer if real fixtures
  make it useful.

This reinforces keeping `io.py` independent from the semantic object model.
The current base intentionally targets `.gmd` only.

Reference: https://github.com/HJfod/GMD-API

## Boundary rules going forward

- `object.py`: one object's raw state + semantic view; do not add level-global
  services here.
- `level.py`: ownership, layout, transactions, IDs, file-independent level
  operations. Keep only a small set of universally useful trigger helpers.
- `scripting.py`: optional level-bound ergonomic handles/builders; no source of
  truth and no process-global current level.
- `catalog.py`: immutable runtime knowledge lookup; raw existence is never
  gated by the catalog.
- `query.py`: snapshot selections of level-owned objects and atomic batch
  mutation.
- `io.py`: container/plist/base64/gzip and atomic file writes only.
- `validation.py`, `diff.py`, `patch.py`: cross-cutting services kept separate
  from storage.

## What not to add yet

- global current-level state;
- implicit autoappend;
- a JSON/Python replacement scripting language;
- a generic plugin/factory/service architecture;
- trigger-function context emulation before real-GD verification;
- performance caches that can become stale after raw escape-hatch mutation.

The raw escape hatch makes correctness-sensitive caches especially risky. Add
caching only when benchmarks show a real bottleneck and invalidation rules are
proven.

## 2026-10-08 follow-up: ID relations and reusable templates

Further comparison with G.js/SPWN/NeditGD/Geometron reinforced two useful
boundaries:

1. **IDs are domain values, not plain integers.** G.js/SPWN treat group, color,
   and collision-block IDs as distinct values. gmdtool now models confirmed
   Color and Block semantics, while keeping automatic allocation limited to
   namespaces whose allocation rules are actually known.
2. **Reuse does not require an execution-context DSL.** A frozen
   `ObjectTemplate` can isolate internal groups and accept explicit ID bindings
   without adopting G.js-style global/current trigger context.

Existing-level understanding is kept in `relations.py`. It reports structural
references with property evidence and deliberately avoids labeling every group
edge as runtime control flow. This keeps the knowledge claims no stronger than
what the catalog actually knows.


## 2026-10-08 follow-up: catalog-driven constraints and variants

The knowledge layer now executes two pieces that were already present in the
design specification rather than adding more Object-ID-specific Python branches.

- Simple numeric `constraints` (currently `min` / `max`) live on source property
  definitions and are applied by the generic validator. Cross-property behavioral
  rules remain Python code because they are behavior, not a scalar fact.
- Conditional semantic `variants` resolve against the current object state. The
  Stop Trigger's target switches between Group and Control semantics according to
  `use_control_id`; references, typed reads, explain output, remapping, and generated
  stubs all consume the same resolved semantic.

This keeps Geometry Dash facts in the catalog while leaving Python responsible for
execution and object manipulation. New conditional mappings should be added only
when the mode/value relationship is actually verified.
