# Serializer write-set verification

`verify_write_sets.py` reads the Geometry Dash 2.2081 executable and verifies
`getSaveString` writes from the actual imported `fmt::BasicWriter` operations.
It is a development tool; the distributable C# executable does not require it,
Python, Capstone, or pefile.

Run after `analyze_executable.py` has produced PE function bounds and class maps:

```powershell
python -m pip install pefile capstone
python tools/reverse/verify_write_sets.py "C:/path/GeometryDash.exe" `
  --evidence tools/reverse/evidence/executable-2.2081.json `
  --broma tools/reverse/evidence/broma-2.2081.json `
  --out tools/reverse/evidence/write-sets-2.2081.json
```

The executable must have the same SHA-256 as the input evidence. The checked-in
evidence describes 2.2081 with SHA-256
`fc5a16c292278bc2e8e078fb1d5023c2bd658322dd72712767ea70c2dd9ec6d0`.

## What is confirmed

The executable imports separate writer overloads for a string reference,
integer, and double. A numeric key is confirmed when the same writer receives
an actual comma, the key integer, another actual comma, and an actual value.
The initial property `1` is also recognized without a leading comma. Constant
values, including boolean `1`, are consumed as values and cannot become keys.
This resolves the ambiguity of collecting every integer immediate before a
writer call. Constant keys formed with `lea` are tracked too.

Value flow follows control flow to the real writer call. MSVC tail-merges many
float insertion blocks; inspecting instructions only in address order misses
these writes and associates values with the wrong key. The verifier follows
each pending value through jumps and conversions and records its member loads.

Group memberships use a second writer to construct period-separated integer
lists. The verifier traces that writer's text through the reviewed
`std::string(data,length)` helper at RVA `0x3a930`, then through the imported
`BasicStringRef` constructor into the outer property's value. It retains string
provenance across branches that initialize the same temporary to empty. These
inner integers are group values rather than additional property keys.

Derived serializers append their base serializer's result. Those string
insertions are classified using the Broma-bound `getSaveString` call, and the
effective class write set follows actual base serializer calls. Level settings
keys such as `kA2` and `kS38` are recorded in `header_write_set`, separately from
object integer keys.

For the checked-in executable, all writer insertions in all 44 serializers are
classified: 728 numeric key-write sites across 539 distinct keys, and 46 header
key-write sites. Each record keeps the key/value call RVAs, value provenance,
member offsets, and corresponding parser store sites where available.

## Meaning of completeness

`complete` means that imported writer insertions in the PE-bounded method have
all been classified. `complete_static_numeric_key_classification` additionally
reports the numeric-key audit. Unresolved insertions are retained in the output
and make completeness false rather than silently disappearing.

`schema_complete` remains false. A class-wide write set is a union of conditional
serializer branches. For example, different IDs share `EffectGameObject` while
using different parts of its parser and serializer. This output confirms actual
write operations; it does not prove that every ID using that class supports
every key in that union. Unknown raw properties are preserved independently.

The field records distinguish the serializer's physical member offset from a
Broma member name and C++ type. The named fields come from Broma annotations.
An unnamed offset or an imported numeric writer does not by itself justify
inventing a semantic property name or changing an integer into a boolean.
