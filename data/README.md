# Geometry Dash knowledge catalog

C# implements behavior. These editable JSON files describe Geometry Dash facts.
The binary embeds `compiled/catalog.normalized.json`; it requires neither this
directory nor Python at runtime.

| File | Meaning |
| --- | --- |
| `objects/*.json` | Object schemas and their evidence |
| `base_properties.json` | Common object and trigger typed views |
| `known_object_ids.json` | 4,073 IDs observed in the Object IDs fixture, without asserting property support |
| `fragments.json` | Reusable schema fragments |
| `properties.json` | Global key labels; these never grant an unknown object a typed schema |
| `enums.json`, `aliases.json` | Enum values and object aliases |
| `references.json` | Group, Item and Control namespaces |
| `sources.json` | Evidence source registry |
| `catalog.json` | Ordered source shard list |
| `schema/*.schema.json` | Source format validation |
| `compiled/catalog.normalized.json` | Deterministic generated runtime resource |

After changing source data, run:

```powershell
python -B tools/reverse/build_catalog.py
python -B tools/reverse/build_catalog.py --check
dotnet run --project tests/GmdTool.Tests
```

The development compiler uses only Python's standard library and has no imports
from a Python runtime package. It expands fragments, validates aliases, types,
references and source IDs, resolves provenance defaults, and writes deterministic
JSON. The `--check` command fails when source data and the committed resource differ.
Historical global `str` labels normalize to `raw`; there is no implicit string codec.

Supported types are `raw`, `real`, `int`, `bool`, `groups`, `text`, `enum`,
`group_id`, `item_id`, `control_id`, `particle`, `weighted_groups`, `sequence`
and `remap_list`. Property aliases are strings in an `aliases` array. ID namespaces
must come from an object-specific semantic type or the reference table; a reused
global integer key is insufficient evidence.

Each object and property keeps `sources` and `confidence`: `confirmed`, `observed`,
`inferred`, or `unknown`. Missing provenance stays unknown. A class field annotation
can establish a field/type mapping without establishing that every Object ID in
the class supports that property. Conditional parser branches must be reviewed
before expanding shared trigger schemas.

`objects/implementation_objects.json` adds 208 schemas from actual 2.2081 factory
dispatch and five reviewed class parsers. Its names are C++ class labels, not
guessed editor display names. Every typed field has a Broma annotation and direct
parser access; complex or conditional fields remain raw. All schemas remain marked
incomplete until their full implementation is established.

Use `gmdtool catalog coverage --json` for counts and the raw-only ID list. Confidence
counts are expanded object-specific property declarations, including fragment
expansion, excluding inherited common properties. The same key used by several
objects therefore contributes several declarations. `complete_schema: false`
means partial knowledge, and is independent of the confidence of individual fields.
