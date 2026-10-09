# AI code review checklist

Use this checklist before accepting substantial AI-generated changes to gmdtool.
Passing tests is necessary but not sufficient; the architecture relies on a few
state and preservation invariants that are easy to accidentally bypass.

## 1. Raw/semantic state

- Is ordered raw pair data still the single source of truth?
- Does a semantic write immediately change the corresponding raw value?
- Does a raw write immediately change the semantic view?
- Are duplicate/shadowed raw keys preserved unless the operation explicitly
  targets them?
- Do unknown keys and unknown Object IDs survive unrelated edits?
- Does structured-value fallback preserve undecodable raw text?

## 2. Ownership and transactions

- Can every batch-mutated object be proven to belong to the target `GDLevel`?
- Does a failing batch edit roll back the full operation?
- Do nested edits reuse the outer transaction instead of repeatedly cloning the
  whole level?
- Does moving/copying an object between levels require an explicit clone or
  ownership transition?

## 3. Catalog semantics

- Is semantic truth taken from the active catalog rather than generated Python
  class inheritance or a hard-coded property table?
- Does a new GD fact belong in source JSON instead of Python?
- If a raw representation is genuinely new, is the codec small and generic?
- Are confidence/source fields preserved instead of upgrading guesses to facts?
- Are generated `catalog.normalized.json` and `objects.pyi` changed only through
  their generators?

## 4. Scripting API

- Does the API reduce code without hiding important state?
- Is the owning level explicit? Avoid a process-global current level.
- Can the same result still be constructed through `OBJ_<ID>` and/or raw access?
- Is Python control flow being used instead of inventing another DSL?
- Is a helper common enough to justify permanent public API surface?

## 5. IO and preservation

- Does an unchanged real fixture still clean-roundtrip?
- Does the change preserve metadata/header/layout/empty slots it did not touch?
- Is container logic kept out of the semantic object model?
- Are `.gmd`, `.lvl`, `.gmd2`, or other formats kept as explicit IO concerns
  rather than silently conflated?

## 6. Reviewability

- Did the change introduce a Manager/Service/Factory/plugin layer without a real
  state boundary? If so, remove it.
- Is a new module separating a genuinely independent responsibility, or only
  making navigation harder?
- Is there duplicated state, duplicated schema knowledge, or a cache with unclear
  invalidation?
- Are broad `except` blocks hiding data corruption or programming errors?
- Are public names intentional, documented, and tested?

## 7. Regression tests

For changes touching core behavior, prefer tests that cover the full path:

```text
raw or real .gmd
  -> parse
  -> semantic/raw mutation
  -> serialize/save
  -> reload
  -> raw + semantic assertion
```

Also run:

```bash
python -m pytest -q
python -m compileall -q gmdtool tests
python tools/validate_catalog.py
python tools/sync_catalog.py --check
python tools/generate_stubs.py --check
```

## 8. Performance

Do not add complexity because an operation *might* be slow. Benchmark a realistic
large level first. Any cache must remain correct after the raw escape hatch is
used; if that invalidation rule is unclear, prefer the uncached implementation.
