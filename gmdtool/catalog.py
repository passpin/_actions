from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable, Mapping


_CONFIDENCE = {"confirmed", "observed", "inferred", "unknown"}
_LEGACY_TYPES = {
    "raw", "real", "int", "bool", "groups", "text", "enum",
    "group_id", "item_id", "control_id", "particle", "weighted_groups",
    "sequence", "remap_list",
}


def _wire_and_semantic(kind: str, enum_name: str | None = None) -> tuple[str, dict[str, Any] | None]:
    if kind == "group_id":
        return "int", {"kind": "reference", "namespace": "group"}
    if kind == "item_id":
        return "int", {"kind": "reference", "namespace": "item"}
    if kind == "control_id":
        return "int", {"kind": "reference", "namespace": "control"}
    if kind == "groups":
        return "groups", {"kind": "membership", "namespace": "group"}
    if kind in {"weighted_groups", "sequence", "remap_list"}:
        return kind, {"kind": "structured_reference", "namespace": "group"}
    if kind == "enum":
        return "int", {"kind": "enum", "enum": enum_name}
    return kind, None


@dataclass(frozen=True)
class PropertySchema:
    key: int
    name: str
    type: str
    wire_type: str
    semantic: Mapping[str, Any] | None
    aliases: tuple[str, ...] = ()
    enum: str | None = None
    sources: tuple[str, ...] = ()
    confidence: str = "unknown"
    constraints: Mapping[str, Any] | None = None
    variants: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, key: int | None = None) -> "PropertySchema":
        kind = str(value.get("type", "raw"))
        if kind == "str":
            kind = "raw"
        enum_name = value.get("enum")
        wire_type, inferred_semantic = _wire_and_semantic(kind, enum_name)
        semantic = value.get("semantic") or inferred_semantic
        if semantic is None and value.get("semantic_domain"):
            semantic = {"kind": "reference", "namespace": value["semantic_domain"]}
        return cls(
            key=int(value["key"] if key is None else key),
            name=str(value["name"]),
            type=kind,
            wire_type=str(value.get("wire_type", wire_type)),
            semantic=semantic,
            aliases=tuple(value.get("aliases", ())),
            enum=str(enum_name) if enum_name is not None else None,
            sources=tuple(value.get("sources", ())),
            confidence=str(value.get("confidence", "unknown")),
            constraints=(dict(value["constraints"]) if value.get("constraints") else None),
            variants=tuple(dict(v) for v in value.get("variants", ())),
            metadata=dict(value),
        )

    @property
    def namespace(self) -> str | None:
        if self.semantic and self.semantic.get("kind") in {"reference", "membership", "identifier", "structured_reference"}:
            ns = self.semantic.get("namespace")
            return str(ns) if ns is not None else None
        return None

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.metadata or {})
        out.update({
            "key": self.key,
            "name": self.name,
            "type": self.type,
            "wire_type": self.wire_type,
            "aliases": list(self.aliases),
            "sources": list(self.sources),
            "confidence": self.confidence,
        })
        if self.enum is not None:
            out["enum"] = self.enum
        if self.semantic is not None:
            out["semantic"] = dict(self.semantic)
        if self.constraints is not None:
            out["constraints"] = dict(self.constraints)
        if self.variants:
            out["variants"] = [dict(v) for v in self.variants]
        return out


@dataclass(frozen=True)
class ObjectSchema:
    id: int
    name: str
    base: str
    properties: tuple[PropertySchema, ...]
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    mixins: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    confidence: str = "unknown"
    category: str | None = None
    cpp_class: str | None = None
    complete_schema: bool = False
    metadata: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], aliases: Iterable[str] = ()) -> "ObjectSchema":
        return cls(
            id=int(value["id"]),
            name=str(value["name"]),
            base=str(value.get("base", "object")),
            properties=tuple(PropertySchema.from_dict(p) for p in value.get("properties", ())),
            aliases=tuple(aliases),
            tags=tuple(value.get("tags", ())),
            mixins=tuple(value.get("mixins", ())),
            sources=tuple(value.get("sources", ())),
            confidence=str(value.get("confidence", "unknown")),
            category=value.get("category"),
            cpp_class=value.get("cpp_class"),
            complete_schema=bool(value.get("complete_schema", False)),
            metadata=dict(value),
        )

    @property
    def schema_status(self) -> str:
        if self.complete_schema:
            return "complete"
        return "partial" if self.properties else "raw_only"

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.metadata or {})
        out["id"] = self.id
        out["name"] = self.name
        out["base"] = self.base
        out["properties"] = [p.to_dict() for p in self.properties]
        out["aliases"] = list(self.aliases)
        out["schema_status"] = self.schema_status
        return out


class Catalog:
    """Validated runtime view of the compiled Geometry Dash knowledge catalog.

    The catalog interprets raw data. It never decides whether a raw key is
    allowed to exist in a level.
    """

    def __init__(self, payload: Mapping[str, Any]):
        self.payload = dict(payload)
        if int(self.payload.get("compiled_format_version", 0)) != 1:
            raise ValueError("Unsupported compiled catalog format")

        alias_payload = {str(k): int(v) for k, v in self.payload.get("aliases", {}).items()}
        aliases_by_id: dict[int, list[str]] = {}
        for name, oid in alias_payload.items():
            aliases_by_id.setdefault(oid, []).append(name)

        self.objects: dict[int, ObjectSchema] = {
            int(o["id"]): ObjectSchema.from_dict(o, aliases_by_id.get(int(o["id"]), ()))
            for o in self.payload.get("objects", ())
        }
        self.known_object_ids: tuple[int, ...] = tuple(
            sorted(set(int(v) for v in self.payload.get("known_object_ids", ())) | set(self.objects))
        )
        self.known_objects: dict[int, dict[str, Any]] = {
            int(oid): dict(spec) for oid, spec in self.payload.get("known_objects", {}).items()
        }
        self.aliases = alias_payload
        self.enums: dict[str, dict[str, int]] = {
            str(name): {str(k): int(v) for k, v in members.items()}
            for name, members in self.payload.get("enums", {}).items()
        }
        self.sources: dict[str, Any] = dict(self.payload.get("sources", {}))
        self.reference_namespaces: dict[str, dict[str, Any]] = {
            str(name): dict(spec)
            for name, spec in self.payload.get("reference_namespaces", {}).items()
        }
        self.references: dict[str, dict[int, tuple[int, ...]]] = {
            str(ns): {int(oid): tuple(int(k) for k in keys) for oid, keys in mapping.items()}
            for ns, mapping in self.payload.get("references", {}).items()
        }
        self.global_properties: dict[int, PropertySchema] = {
            int(key): PropertySchema.from_dict(spec, key=int(key))
            for key, spec in self.payload.get("properties", {}).items()
        }
        self._universal_semantics: dict[tuple[str, str], tuple[PropertySchema, ...]] = {}
        universal_index: dict[tuple[str, str], list[PropertySchema]] = {}
        for prop in self.global_properties.values():
            if not (prop.metadata or {}).get("universal_semantic") or not prop.semantic:
                continue
            ns = prop.semantic.get("namespace")
            kind = prop.semantic.get("kind")
            if isinstance(ns, str) and isinstance(kind, str):
                universal_index.setdefault((ns, kind), []).append(prop)
        self._universal_semantics = {key: tuple(value) for key, value in universal_index.items()}
        self.base_properties: dict[str, tuple[PropertySchema, ...]] = {
            str(base): tuple(PropertySchema.from_dict(p) for p in props)
            for base, props in self.payload.get("base_properties", {}).items()
        }

        self._effective: dict[int, tuple[PropertySchema, ...]] = {}
        self._by_name: dict[int, dict[str, PropertySchema]] = {}
        for oid in self.known_object_ids:
            obj = self.objects.get(oid)
            pieces: list[PropertySchema] = []
            if obj is not None:
                pieces.extend(obj.properties)
                pieces.extend(self.base_properties.get(obj.base, ()))
            pieces.extend(self.base_properties.get("object", ()))
            seen: set[int] = set()
            effective: list[PropertySchema] = []
            for prop in pieces:
                if prop.key in seen:
                    continue
                seen.add(prop.key)
                effective.append(prop)
            self._effective[oid] = tuple(effective)
            names: dict[str, PropertySchema] = {}
            for prop in effective:
                for name in (prop.name, *prop.aliases):
                    names.setdefault(name, prop)
            self._by_name[oid] = names

        self._object_names: dict[str, int] = {}
        for oid, obj in self.objects.items():
            self._object_names.setdefault(obj.name, oid)
            self._object_names.setdefault(obj.name.casefold(), oid)
            self._object_names.setdefault(f"OBJ_{oid}", oid)
        for oid, info in self.known_objects.items():
            name = info.get("name")
            if isinstance(name, str) and name:
                self._object_names.setdefault(name, oid)
                self._object_names.setdefault(name.casefold(), oid)
            self._object_names.setdefault(f"OBJ_{oid}", oid)
        for name, oid in self.aliases.items():
            self._object_names[name] = oid
            self._object_names[name.casefold()] = oid

        errors = self.validate()
        if errors:
            raise ValueError("Invalid catalog: " + "; ".join(errors[:20]))

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def default(cls) -> "Catalog":
        return default_catalog()

    def get_object(self, object_id: int | None) -> ObjectSchema | None:
        return None if object_id is None else self.objects.get(int(object_id))

    def known_object(self, object_id: int | None) -> Mapping[str, Any] | None:
        return None if object_id is None else self.known_objects.get(int(object_id))

    def object_display_name(self, object_id: int | None) -> str | None:
        if object_id is None:
            return None
        schema = self.get_object(object_id)
        if schema is not None:
            return schema.name
        info = self.known_object(object_id) or {}
        name = info.get("name")
        if isinstance(name, str) and name:
            return name
        cpp = info.get("cpp_class")
        if isinstance(cpp, str) and cpp and cpp != "GameObject":
            return f"{cpp} {int(object_id)}"
        return f"Object {int(object_id)}"

    def resolve_object_id(self, value: int | str | type) -> int:
        if isinstance(value, bool):
            raise TypeError("bool is not an Object ID")
        if isinstance(value, int):
            return value
        if isinstance(value, type) and hasattr(value, "OBJECT_ID"):
            oid = getattr(value, "OBJECT_ID")
            if isinstance(oid, int):
                return oid
        text = str(value)
        try:
            return int(text)
        except ValueError:
            pass
        for key in (text, text.casefold()):
            if key in self._object_names:
                return self._object_names[key]
        raise KeyError(f"Unknown object selector: {value!r}")

    def properties_for(self, object_id: int | None) -> tuple[PropertySchema, ...]:
        if object_id is None:
            return self.base_properties.get("object", ())
        return self._effective.get(int(object_id), self.base_properties.get("object", ()))

    def find_property(self, object_id: int | None, name_or_key: int | str) -> PropertySchema | None:
        if isinstance(name_or_key, bool):
            return None
        if isinstance(name_or_key, int):
            key = name_or_key
            return next((p for p in self.properties_for(object_id) if p.key == key), None)
        text = str(name_or_key)
        try:
            key = int(text)
        except ValueError:
            key = None
        if key is not None:
            return next((p for p in self.properties_for(object_id) if p.key == key), None)
        if object_id is not None:
            return self._by_name.get(int(object_id), {}).get(text)
        return next(
            (p for p in self.base_properties.get("object", ()) if text == p.name or text in p.aliases),
            None,
        )

    def global_property(self, key: int) -> PropertySchema | None:
        return self.global_properties.get(int(key))

    def universal_semantic_properties(
        self, namespace: str, kinds: Iterable[str],
    ) -> tuple[PropertySchema, ...]:
        out: list[PropertySchema] = []
        for kind in kinds:
            out.extend(self._universal_semantics.get((str(namespace), str(kind)), ()))
        return tuple(out)

    def reference_keys(self, namespace: str, object_id: int | None) -> tuple[int, ...]:
        if object_id is None:
            return ()
        return self.references.get(namespace, {}).get(int(object_id), ())

    def enum_value(self, enum_name: str, value: str | int) -> int:
        if isinstance(value, bool):
            raise TypeError("bool is not an enum integer")
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return self.enums[enum_name][value]
        except KeyError as exc:
            raise KeyError(f"Unknown {enum_name} value {value!r}") from exc

    def enum_name(self, enum_name: str, value: int) -> str | None:
        for name, number in self.enums.get(enum_name, {}).items():
            if number == value:
                return name
        return None

    @staticmethod
    def _validate_property_variants(prop: PropertySchema, context: str) -> list[str]:
        errors: list[str] = []
        defaults = 0
        for index, variant in enumerate(prop.variants):
            if not isinstance(variant, Mapping):
                errors.append(f"{context} variant {index} is not an object")
                continue
            is_default = variant.get("default") is True
            when = variant.get("when")
            if is_default:
                defaults += 1
                if when is not None:
                    errors.append(f"{context} variant {index} cannot have both default and when")
            else:
                if not isinstance(when, Mapping) or not isinstance(when.get("property"), str) or "equals" not in when:
                    errors.append(f"{context} variant {index} needs when.property and when.equals")
            semantic = variant.get("semantic")
            if not isinstance(semantic, Mapping):
                errors.append(f"{context} variant {index} needs semantic")
                continue
            namespace = semantic.get("namespace")
            if semantic.get("kind") in {"reference", "membership", "identifier", "structured_reference"} and not isinstance(namespace, str):
                errors.append(f"{context} variant {index} needs a semantic namespace")
        if defaults > 1:
            errors.append(f"{context} has more than one default variant")
        return errors

    def validate(self) -> list[str]:
        errors: list[str] = []
        for oid, obj in self.objects.items():
            if obj.base not in {"object", "trigger"}:
                errors.append(f"Object {oid} has invalid base {obj.base!r}")
            if obj.confidence not in _CONFIDENCE:
                errors.append(f"Object {oid} has invalid confidence {obj.confidence!r}")
            names: set[str] = set()
            keys: set[int] = set()
            for p in obj.properties:
                if p.type not in _LEGACY_TYPES:
                    errors.append(f"Object {oid} property {p.key} has invalid type {p.type!r}")
                if p.confidence not in _CONFIDENCE:
                    errors.append(f"Object {oid} property {p.key} has invalid confidence {p.confidence!r}")
                if p.key in keys:
                    errors.append(f"Object {oid} repeats property key {p.key}")
                keys.add(p.key)
                for name in (p.name, *p.aliases):
                    if name in names:
                        errors.append(f"Object {oid} repeats property name {name!r}")
                    names.add(name)
                if p.enum and p.enum not in self.enums:
                    errors.append(f"Object {oid} property {p.key} references missing enum {p.enum!r}")
                if p.namespace is not None and p.namespace not in self.reference_namespaces:
                    errors.append(
                        f"Object {oid} property {p.key} references missing ID namespace {p.namespace!r}"
                    )
                if p.constraints is not None:
                    unknown = set(p.constraints) - {"min", "max"}
                    if unknown:
                        errors.append(f"Object {oid} property {p.key} has unsupported constraints {sorted(unknown)}")
                    low = p.constraints.get("min")
                    high = p.constraints.get("max")
                    if low is not None and high is not None and low > high:
                        errors.append(f"Object {oid} property {p.key} constraint min exceeds max")
                errors.extend(self._validate_property_variants(p, f"Object {oid} property {p.key}"))
                for variant in p.variants:
                    semantic = variant.get("semantic", {})
                    namespace = semantic.get("namespace") if isinstance(semantic, Mapping) else None
                    if namespace is not None and namespace not in self.reference_namespaces:
                        errors.append(
                            f"Object {oid} property {p.key} variant references missing ID namespace {namespace!r}"
                        )
                for source in p.sources:
                    if source not in self.sources:
                        errors.append(f"Object {oid} property {p.key} references missing source {source!r}")
            for source in obj.sources:
                if source not in self.sources:
                    errors.append(f"Object {oid} references missing source {source!r}")
        for base, props in self.base_properties.items():
            for p in props:
                if p.namespace is not None and p.namespace not in self.reference_namespaces:
                    errors.append(
                        f"Base {base!r} property {p.key} references missing ID namespace {p.namespace!r}"
                    )
                if p.constraints is not None:
                    unknown = set(p.constraints) - {"min", "max"}
                    if unknown:
                        errors.append(f"Base {base!r} property {p.key} has unsupported constraints {sorted(unknown)}")
                    low = p.constraints.get("min")
                    high = p.constraints.get("max")
                    if low is not None and high is not None and low > high:
                        errors.append(f"Base {base!r} property {p.key} constraint min exceeds max")
                errors.extend(self._validate_property_variants(p, f"Base {base!r} property {p.key}"))
                for variant in p.variants:
                    semantic = variant.get("semantic", {})
                    namespace = semantic.get("namespace") if isinstance(semantic, Mapping) else None
                    if namespace is not None and namespace not in self.reference_namespaces:
                        errors.append(
                            f"Base {base!r} property {p.key} variant references missing ID namespace {namespace!r}"
                        )
        for namespace in self.references:
            if namespace not in self.reference_namespaces:
                errors.append(f"Reference map uses missing ID namespace {namespace!r}")
        for alias, oid in self.aliases.items():
            if oid not in self.objects:
                errors.append(f"Alias {alias!r} targets missing object {oid}")
        return errors

    def coverage(self, known_ids: Iterable[int] | None = None) -> dict[str, Any]:
        ids = sorted(set(self.known_object_ids if known_ids is None else map(int, known_ids)) | set(self.objects))
        confidence = {name: 0 for name in _CONFIDENCE}
        for obj in self.objects.values():
            for prop in obj.properties:
                confidence[prop.confidence] = confidence.get(prop.confidence, 0) + 1
        raw_only = [oid for oid in ids if oid not in self.objects]
        incomplete = [oid for oid, obj in self.objects.items() if not obj.complete_schema]
        return {
            "total_known_object_ids": len(ids),
            "explicit_schemas": len(self.objects),
            "raw_only_ids": raw_only,
            "raw_only_count": len(raw_only),
            "properties_by_confidence": confidence,
            "objects_with_incomplete_schemas": sorted(incomplete),
            "incomplete_schema_count": len(incomplete),
            "global_property_keys": len(self.global_properties),
            "common_typed_properties": len(self.base_properties.get("object", ())),
        }


@lru_cache(maxsize=1)
def default_catalog() -> Catalog:
    path = files("gmdtool.data").joinpath("catalog.normalized.json")
    with path.open("r", encoding="utf-8") as handle:
        return Catalog(json.load(handle))
