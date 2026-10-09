# Geometry Dash 2.2081 research tools

These scripts are development tooling. The C# product embeds the normalized JSON
catalog and never starts Python or these tools.

The completed factory analysis maps every one of the fixture's 4,073 distinct IDs
to its C++ class using actual executable instructions and PE RTTI. Broma provides
608 class definitions and 523 member/property annotations. Parser access evidence
and serializer evidence are committed under `evidence/`; their claim scope and
confidence are explicit. An unknown property surviving serialization establishes
only persistence, not implementation support.

Primary bindings snapshot:
https://github.com/geode-sdk/bindings/blob/5c8d88305bfe2e1e1189cfed73b494b8bfdd3a4e/bindings/2.2081/GeometryDash.bro

## Build and validate the runtime catalog

```powershell
python -B tools/reverse/build_catalog.py
python -B tools/reverse/build_catalog.py --check
```

This uses the standard library only and replaces the retired runtime catalog
compiler. Source is `data/`; the embedded artifact is
`data/compiled/catalog.normalized.json`.

## Reproduce executable evidence

The analyzer requires development-only `pefile` and `capstone`:

```powershell
python -m pip install pefile capstone
python -B tools/reverse/extract_broma.py tools/reverse/evidence/GeometryDash-2.2081.bro --out tools/reverse/evidence/broma-2.2081.json
python -B tools/reverse/analyze_executable.py 'path/to/GeometryDash.exe' tools/reverse/evidence/broma-2.2081.json data/known_object_ids.json --out tools/reverse/evidence/executable-2.2081.json
python -B tools/reverse/verify_write_sets.py 'path/to/GeometryDash.exe' --evidence tools/reverse/evidence/executable-2.2081.json --broma tools/reverse/evidence/broma-2.2081.json --out tools/reverse/evidence/write-sets-2.2081.json
python -B tools/reverse/expand_implementation_catalog.py
python -B tools/reverse/build_catalog.py
python -B tools/reverse/export_maps.py
```

The reviewed executable SHA256 is
`fc5a16c292278bc2e8e078fb1d5023c2bd658322dd72712767ea70c2dd9ec6d0`.
Its version was independently corroborated by installed Geode logs. The analyzer
rejects a different executable because factory and serializer RVAs are version
specific. The executable itself is not distributed with this repository.

The factory integer dispatch is evaluated without executing game code. RTTI-backed
vtable assignments and Broma constructor calls establish the class. Four terminal
allocation paths were reviewed explicitly. Frame-name lookup/allocation success
is assumed; observed fixture membership corroborates each ID. Chained PE unwind
ranges are merged so optimized function fragments are analyzed together.

Parser read keys come from actual presence-vector accesses (`key * 8` on Windows
x64). Serializer immediate integer candidates initially carry inferred confidence;
verified write sets record token and field dataflow separately. All 44 serializer
methods' imported fmt::BasicWriter insertions are now fully classified, with header
string keys separate from numeric object keys. A class-level read
set is the union across conditional branches, and does not assert that every Object
ID handled by a shared class accepts every key. Field-store candidates retain their
instruction and offset; candidates are never silently treated as confirmed facts.

## Reproduce completed Ghidra decompilation

For source-level inspection, install Ghidra and Java 25. The scripts work in GUI
and headless mode:

```powershell
analyzeHeadless.bat research gd2081 -import 'path/to/GeometryDash.exe' -scriptPath tools/reverse/ghidra -preScript ImportGDBromaFacts.java tools/reverse/evidence/broma-2.2081.json -postScript DumpGDPropertyFunctions.java research/ghidra-dump.json
python -B tools/reverse/analyze_ghidra_dump.py research/ghidra-dump.json --out research/ghidra-analysis.json
```

The import script applies the exact Broma Windows RVAs before analysis. The dump
includes `customObjectSetup`, `getSaveString`, `GameObject::createWithKey` and
`GameObject::objectFromVector`. Its small constant list is a research aid, not a
property-support oracle. Heuristic ID/class matches from decompiled C stay candidates
until inspected; the PE factory map is recorded independently.

The committed `evidence/ghidra-dump-2.2081.json` was generated with Ghidra 12.1.4
and Java 25 against the reviewed executable. It contains 88 targeted functions,
all with nonempty decompiled C. `evidence/ghidra-analysis-2.2081.json` is its
candidate analysis. Verified map claims come from Broma and the independently
audited binary dataflow, rather than automatically promoting decompiler constants.

See `docs/REVERSE_ENGINEERING.md` for generated outputs, verified scope, conflicts
and remaining schema uncertainty. Prefer actual 2.2081 implementation over catalog
claims when a verified disagreement exists.
