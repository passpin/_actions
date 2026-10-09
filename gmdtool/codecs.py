from __future__ import annotations

import base64
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .catalog import Catalog, PropertySchema
from .ids import ControlId, GroupId, ItemId, semantic_id
from .numeric import GDReal
from .structured import GDGroupRemapList, GDParticleSettings, GDSequenceList, GDWeightedGroupList


def raw_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, GDReal):
        return value.raw
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if value is None:
        raise TypeError("None is not a raw token; remove the property instead")
    return str(value)


def _decode_bool(raw: str) -> bool:
    if raw == "0":
        return False
    if raw == "1":
        return True
    raise ValueError(f"GD bool must be 0 or 1, got {raw!r}")


def _decode_text(raw: str) -> str:
    if raw == "":
        return ""
    try:
        padding = "=" * ((4 - len(raw) % 4) % 4)
        data = base64.b64decode(raw + padding, validate=True)
        return data.decode("utf-8")
    except (ValueError, UnicodeError):
        # Some real/community levels contain non-UTF8 or non-base64 property-31
        # payloads. Text is a semantic convenience; preserving the raw token is
        # more important than rejecting the object.
        return raw


def _encode_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("text property expects str")
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _encode_int(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Expected int, got {type(value).__name__}")
    return str(int(value))


def _encode_groups(value: Any) -> str:
    if isinstance(value, bool):
        raise TypeError("groups must contain integer IDs")
    if isinstance(value, int):
        values = [value]
    elif isinstance(value, (str, bytes)):
        raise TypeError("groups must be an int or iterable of ints")
    else:
        values = list(value)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise TypeError("groups must contain integer IDs")
    return ".".join(str(int(v)) for v in values)


def decode_property(
    schema: PropertySchema, raw: str, *, catalog: Catalog,
    on_change=None, semantic: Mapping[str, Any] | None = None,
) -> Any:
    kind = schema.type
    active_semantic = schema.semantic if semantic is None else semantic
    namespace = None
    if active_semantic and active_semantic.get("kind") in {"reference", "membership", "identifier", "structured_reference"}:
        raw_namespace = active_semantic.get("namespace")
        namespace = str(raw_namespace) if raw_namespace is not None else None
    if kind == "real":
        return GDReal(raw)
    if kind == "int":
        if namespace is not None:
            try:
                return semantic_id(namespace, int(raw))
            except ValueError:
                # Knowledge catalogs may grow namespaces before the runtime gets
                # a dedicated Python ID class.  In that case the integer remains
                # fully usable instead of making the property undecodable.
                pass
        return int(raw)
    if kind == "enum":
        return int(raw)
    if kind == "group_id":
        return GroupId(int(raw))
    if kind == "item_id":
        return ItemId(int(raw))
    if kind == "control_id":
        return ControlId(int(raw))
    if kind == "bool":
        return _decode_bool(raw)
    if kind == "groups":
        if raw == "":
            return ()
        return tuple(GroupId(int(v)) for v in raw.split("."))
    if kind == "text":
        return _decode_text(raw)
    if kind == "particle":
        return GDParticleSettings(raw, on_change)
    if kind == "weighted_groups":
        return GDWeightedGroupList(raw, on_change)
    if kind == "sequence":
        return GDSequenceList(raw, on_change)
    if kind == "remap_list":
        return GDGroupRemapList(raw, on_change)
    return raw


def encode_property(schema: PropertySchema, value: Any, *, catalog: Catalog) -> str:
    kind = schema.type
    if kind == "real":
        return GDReal.from_value(value).raw
    if kind in {"int", "group_id", "item_id", "control_id"}:
        return _encode_int(value)
    if kind == "enum":
        if isinstance(value, str) and schema.enum:
            return str(catalog.enum_value(schema.enum, value))
        return _encode_int(value)
    if kind == "bool":
        if not isinstance(value, bool):
            raise TypeError("bool property expects bool")
        return "1" if value else "0"
    if kind == "groups":
        return _encode_groups(value)
    if kind == "text":
        return _encode_text(value)
    if kind == "particle":
        if isinstance(value, GDParticleSettings):
            return value.to_raw_string()
        if isinstance(value, str):
            return value
        raise TypeError("particle property expects GDParticleSettings or raw str")
    if kind == "weighted_groups":
        if isinstance(value, GDWeightedGroupList):
            return value.to_raw_string()
        if isinstance(value, str):
            GDWeightedGroupList(value)
            return value
        raise TypeError("weighted_groups expects GDWeightedGroupList or raw str")
    if kind == "sequence":
        if isinstance(value, GDSequenceList):
            return value.to_raw_string()
        if isinstance(value, str):
            GDSequenceList(value)
            return value
        raise TypeError("sequence expects GDSequenceList or raw str")
    if kind == "remap_list":
        if isinstance(value, GDGroupRemapList):
            return value.to_raw_string()
        if isinstance(value, str):
            GDGroupRemapList(value)
            return value
        raise TypeError("remap_list expects GDGroupRemapList or raw str")
    return raw_value(value)
