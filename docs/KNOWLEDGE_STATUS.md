# Knowledge status

`gmdtool` treats Geometry Dash facts as data with explicit provenance. The runtime
should execute/inspect the catalog rather than accumulating Object-ID-specific
facts in Python branches.

## Current layers

1. **Known Object IDs** — 4,073 IDs from the in-game/object fixture.
2. **Implementation identity** — factory/static-analysis metadata maps every known
   ID to its observed C++ implementation class.
3. **Global property knowledge** — 539 serialized keys with names/types and
   provenance; safe context-independent semantics are marked explicitly.
4. **Explicit object schemas** — 385 higher-confidence per-object schemas plus
   reusable class/family fragments.
5. **Semantic relationships** — 15 ID namespaces with membership, definition,
   reference, structured-reference, variants, and scoped-ID metadata.
6. **Human naming** — explicit schemas carry stable names; a small number of
   raw-only objects also carry separately sourced display names. Human naming is
   deliberately kept separate from claiming a detailed schema.

## Evidence priority

When sources conflict, implementation evidence should generally outrank a
community table for serialized structure:

1. verified parser/serializer writes and executable factory dispatch
2. Broma/Geode member bindings
3. real exported fixtures
4. editor/community documentation for user-facing meaning and constraints
5. inference only when clearly labelled as such

A C++ field proving that a key exists does not by itself prove every semantic
interpretation of that field for every Object ID. Confidence is therefore raised
conservatively.

## Current high-value gaps

- human-readable names are still incomplete for raw-only IDs;
- more 2.2 object families need explicit semantic schemas;
- several mode-dependent fields can be converted to catalog `variants` once their
  conditions are independently verified;
- runtime behavior/control flow is not inferred merely from structural references;
- spatial knowledge (visual bounds, hitbox existence/size, anchors, collision type,
  transforms, and object-to-object spatial relations) is a future knowledge layer,
  not yet modeled.

The long-term spatial layer should remain data-driven so an AI can reason about
actual occupied space and gameplay collision rather than treating every object as
only an `(x, y)` point.
