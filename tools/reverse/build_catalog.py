"""Build the runtime JSON knowledge resource using Python's standard library only.

This is a development tool; the executable neither invokes nor imports Python.
"""
from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TYPES = {"raw", "real", "int", "bool", "groups", "text", "enum", "group_id", "item_id", "control_id", "particle", "weighted_groups", "sequence", "remap_list"}
CONFIDENCE = {"confirmed", "observed", "inferred", "unknown"}


def build(data: Path) -> dict:
    def read(relative: str) -> dict:
        path = (data / relative).resolve()
        if not path.is_relative_to(data.resolve()):
            raise ValueError(f"catalog path escapes data/: {relative}")
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("schema_version") != 1:
            raise ValueError(f"unsupported schema version: {relative}")
        return result

    def provenance(value: dict, defaults: tuple = ([], "unknown")) -> tuple:
        sources = value.get("sources", value.get("source", defaults[0]))
        if isinstance(sources, str):
            sources = [sources]
        confidence = value.get("confidence", defaults[1])
        if not isinstance(sources, list) or not all(isinstance(s, str) and s for s in sources) or len(set(sources)) != len(sources):
            raise ValueError("sources must be unique nonempty strings")
        if confidence not in CONFIDENCE:
            raise ValueError(f"invalid confidence: {confidence}")
        if set(sources) - known_sources:
            raise ValueError(f"unknown sources: {sorted(set(sources) - known_sources)}")
        return deepcopy(sources), confidence

    def property_spec(spec: dict, defaults: tuple, names: set | None = None) -> dict:
        p = deepcopy(spec)
        # Historical global lookup used Python's "str" label for wire values
        # with no implemented typed codec. The runtime vocabulary calls this raw.
        if p.get("type") == "str":
            p["type"] = "raw"
        if type(p.get("key")) is not int or not isinstance(p.get("name"), str) or not p["name"]:
            raise ValueError(f"invalid property: {p}")
        if p.get("type") not in TYPES:
            raise ValueError(f"unsupported property type: {p}")
        aliases = p.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a for a in aliases) or len(set(aliases)) != len(aliases):
            raise ValueError(f"invalid property aliases: {p}")
        if p["name"] in aliases:
            raise ValueError(f"canonical name repeated as alias: {p}")
        if names is not None:
            declared = {p["name"], *aliases}
            if names & declared:
                raise ValueError(f"duplicate property names: {names & declared}")
            names.update(declared)
        if p["type"] == "enum" and p.get("enum") not in enums:
            raise ValueError(f"unknown enum: {p}")
        variants = p.get("variants", [])
        if not isinstance(variants, list):
            raise ValueError(f"property variants must be an array: {p}")
        default_variants = 0
        for variant in variants:
            if not isinstance(variant, dict) or not isinstance(variant.get("semantic"), dict):
                raise ValueError(f"invalid property variant: {p}")
            if variant.get("default") is True:
                default_variants += 1
                if "when" in variant:
                    raise ValueError(f"property variant cannot have both default and when: {p}")
            else:
                when = variant.get("when")
                if not isinstance(when, dict) or not isinstance(when.get("property"), str) or "equals" not in when:
                    raise ValueError(f"property variant needs when.property and when.equals: {p}")
            semantic = variant["semantic"]
            if semantic.get("kind") not in {"reference", "membership", "identifier", "structured_reference"}:
                raise ValueError(f"unsupported variant semantic: {p}")
            if not isinstance(semantic.get("namespace"), str) or not semantic["namespace"]:
                raise ValueError(f"variant semantic needs namespace: {p}")
        if default_variants > 1:
            raise ValueError(f"property has more than one default variant: {p}")

        constraints = p.get("constraints")
        if constraints is not None:
            if not isinstance(constraints, dict):
                raise ValueError(f"property constraints must be an object: {p}")
            unknown_constraints = set(constraints) - {"min", "max"}
            if unknown_constraints:
                raise ValueError(f"unsupported property constraints {sorted(unknown_constraints)}: {p}")
            for name in ("min", "max"):
                value = constraints.get(name)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                    raise ValueError(f"constraint {name} must be numeric: {p}")
            if "min" in constraints and "max" in constraints and constraints["min"] > constraints["max"]:
                raise ValueError(f"constraint min exceeds max: {p}")
        p["aliases"] = aliases
        p["sources"], p["confidence"] = provenance(p, defaults)
        p.pop("source", None)
        return p

    sources = read("sources.json")["sources"]
    known_sources = set(sources)
    for name, source in sources.items():
        if not name or not source.get("title") or not source.get("kind"):
            raise ValueError(f"invalid source definition: {name}")
    enums = read("enums.json")["enums"]
    for name, members in enums.items():
        if not isinstance(members, dict) or not all(type(v) is int for v in members.values()):
            raise ValueError(f"invalid enum definition: {name}")
    raw_properties = read("properties.json")
    properties = {}
    for key, spec in raw_properties["properties"].items():
        int(key)
        p = deepcopy(spec)
        if p.get("type") == "str":
            p["type"] = "raw"
        if p.get("type", "raw") not in TYPES:
            raise ValueError(f"unsupported global property type: {key}")
        p["sources"], p["confidence"] = provenance(p, provenance(raw_properties))
        p.pop("source", None)
        properties[key] = p

    raw_fragments = read("fragments.json")
    fragments = {}
    for name, fragment in raw_fragments["fragments"].items():
        defaults = provenance(fragment, provenance(raw_fragments))
        names = set()
        fragments[name] = [property_spec(p, defaults, names) for p in fragment["properties"]]
    objects = []
    seen_ids = set()
    stored = 0
    for relative in read("catalog.json")["object_files"]:
        payload = read(relative)
        for raw in payload["objects"]:
            oid = raw.get("id")
            if type(oid) is not int or oid in seen_ids:
                raise ValueError(f"invalid or duplicate object ID: {oid}")
            seen_ids.add(oid)
            if not raw.get("name") or raw.get("base") not in {"object", "trigger"}:
                raise ValueError(f"invalid object schema: {oid}")
            defaults = provenance(raw, provenance(payload))
            names = set()
            expanded = []
            for mixin in raw.get("mixins", []):
                if mixin not in fragments:
                    raise ValueError(f"unknown mixin {mixin} on object {oid}")
                for p in fragments[mixin]:
                    expanded.append(property_spec(p, defaults, names))
            for raw_prop in raw.get("properties", []):
                candidate = deepcopy(raw_prop)
                override = bool(candidate.pop("override", False))
                if override:
                    key = candidate.get("key")
                    matches = [p for p in expanded if p.get("key") == key]
                    if not matches:
                        raise ValueError(f"override property key {key} not found on object {oid}")
                    expanded = [p for p in expanded if p.get("key") != key]
                    names = {n for p in expanded for n in (p["name"], *p.get("aliases", []))}
                expanded.append(property_spec(candidate, defaults, names))
            stored += len(raw.get("properties", []))
            obj = {"id": oid, "name": raw["name"], "base": raw["base"], "mixins": raw.get("mixins", []), "tags": raw.get("tags", []),
                   "category": payload.get("category"), "properties": expanded, "sources": defaults[0], "confidence": defaults[1]}
            for extra in ("cpp_class", "complete_schema", "implementation_sources", "notes"):
                if extra in raw:
                    obj[extra] = deepcopy(raw[extra])
            objects.append(obj)
    objects.sort(key=lambda o: o["id"])
    aliases = read("aliases.json")["aliases"]
    if any(not name.isidentifier() or type(oid) is not int or oid not in seen_ids for name, oid in aliases.items()):
        raise ValueError("invalid object alias or missing target")
    reference_payload = read("references.json")
    reference_namespaces = reference_payload.get("namespaces", {})
    if not isinstance(reference_namespaces, dict) or not reference_namespaces:
        raise ValueError("references.json must define ID namespaces")
    for name, spec in reference_namespaces.items():
        if not isinstance(name, str) or not name or not isinstance(spec, dict) or not spec.get("description"):
            raise ValueError(f"invalid reference namespace: {name!r}")
        if "allocatable" in spec and not isinstance(spec["allocatable"], bool):
            raise ValueError(f"invalid allocatable flag for reference namespace {name!r}")
    references = reference_payload["references"]
    if set(references) - set(reference_namespaces):
        raise ValueError("reference map uses an undefined namespace")
    for domain, mapping in references.items():
        for oid, keys in mapping.items():
            if int(oid) not in seen_ids or not isinstance(keys, list) or not all(type(k) is int for k in keys):
                raise ValueError(f"invalid {domain} references: {oid}")
    base_properties = {}
    base_path = data / "base_properties.json"
    if base_path.exists():
        raw_base = read("base_properties.json")
        for base, specs in raw_base["base_properties"].items():
            names = set()
            base_properties[base] = [property_spec(p, provenance(raw_base), names) for p in specs]
    known_path = data / "known_object_ids.json"
    known_ids = read("known_object_ids.json")["object_ids"] if known_path.exists() else []
    if not isinstance(known_ids, list) or not all(type(oid) is int for oid in known_ids):
        raise ValueError("known object IDs must be integers")

    known_objects: dict[str, dict] = {}
    known_objects_path = data / "known_objects.json"
    if known_objects_path.exists():
        payload = read("known_objects.json")
        raw_known = payload.get("objects", {})
        if not isinstance(raw_known, dict):
            raise ValueError("known_objects.json objects must be an object")
        default_source = payload.get("source")
        for oid_text, spec in raw_known.items():
            oid = int(oid_text)
            if oid not in set(known_ids) | seen_ids:
                raise ValueError(f"known object metadata references unknown Object ID {oid}")
            if not isinstance(spec, dict):
                raise ValueError(f"invalid known object metadata: {oid}")
            name_sources = spec.get("name_sources", [])
            if isinstance(name_sources, str):
                name_sources = [name_sources]
            if not isinstance(name_sources, list) or any(src not in sources for src in name_sources):
                raise ValueError(f"invalid known-object name sources: {oid}")
            name_confidence = spec.get("name_confidence")
            if name_confidence is not None and name_confidence not in CONFIDENCE:
                raise ValueError(f"invalid known-object name confidence: {oid}")
            entry = deepcopy(spec)
            entry_sources = entry.get("sources")
            if entry_sources is None and default_source:
                entry_sources = [default_source]
            elif isinstance(entry_sources, str):
                entry_sources = [entry_sources]
            if entry_sources is None:
                entry_sources = []
            if set(entry_sources) - known_sources:
                raise ValueError(f"unknown known-object sources: {sorted(set(entry_sources)-known_sources)}")
            entry["sources"] = entry_sources
            if entry.get("confidence", "unknown") not in CONFIDENCE:
                raise ValueError(f"invalid known-object confidence: {oid}")
            known_objects[str(oid)] = entry
    confidence = {name: 0 for name in CONFIDENCE}
    for obj in objects:
        for p in obj["properties"]:
            confidence[p["confidence"]] += 1
    summary = {"objects": len(objects), "object_properties": sum(len(o["properties"]) for o in objects),
               "property_aliases": sum(len(p["aliases"]) for o in objects for p in o["properties"]), "stored_object_properties": stored,
               "schema_fragments": len(fragments), "fragment_properties": sum(len(f) for f in fragments.values()), "aliases": len(aliases),
               "global_properties": len(properties), "enums": len(enums), "reference_domains": len(reference_namespaces), "sources": len(sources),
               "confirmed_properties": confidence["confirmed"], "observed_properties": confidence["observed"],
               "inferred_properties": confidence["inferred"], "unknown_confidence_properties": confidence["unknown"]}
    return {"compiled_format_version": 1, "source_schema_version": 1, "summary": summary, "objects": objects, "aliases": aliases,
            "enums": enums, "properties": properties, "reference_namespaces": reference_namespaces, "references": references, "fragments": fragments, "sources": sources,
            "base_properties": base_properties, "known_object_ids": sorted(set(known_ids) | seen_ids),
            "known_objects": known_objects}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if the committed runtime artifact is stale")
    args = parser.parse_args()
    target = args.out or args.data / "compiled/catalog.normalized.json"
    result = build(args.data)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if args.check:
        if not target.exists() or target.read_bytes() != encoded:
            raise SystemExit("normalized catalog is stale; run python -B tools/reverse/build_catalog.py")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
