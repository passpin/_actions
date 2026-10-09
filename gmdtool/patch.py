from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from .ids import normalize_namespace

if TYPE_CHECKING:
    from .level import GDLevel
    from .query import ObjectCollection


_ALLOWED_SELECTOR_KEYS = {"id", "object_id", "properties", "limit", "offset"}


def _select(level: "GDLevel", spec: Mapping[str, Any] | None) -> "ObjectCollection":
    from .query import ObjectCollection

    spec = dict(spec or {})
    unknown = set(spec) - _ALLOWED_SELECTOR_KEYS
    if unknown:
        raise ValueError(f"Unknown selector key(s): {sorted(unknown)}")
    selector = spec.get("id", spec.get("object_id"))
    properties = spec.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypeError("select.properties must be an object")
    query = level.find(selector, **dict(properties))
    offset = spec.get("offset", 0)
    limit = spec.get("limit")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("select.offset must be a non-negative integer")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("select.limit must be a non-negative integer")
    return query[offset:] if limit is None else query[offset:offset + limit]


def apply_patch(level: "GDLevel", patch: Mapping[str, Any]) -> dict[str, Any]:
    if patch.get("format") not in {None, "gmdtool.patch"}:
        raise ValueError("Unsupported patch format")
    if patch.get("version", 1) != 1:
        raise ValueError("Unsupported patch version")
    operations = patch.get("operations")
    if not isinstance(operations, list):
        raise TypeError("patch.operations must be a list")

    results: list[dict[str, Any]] = []
    with level.edit():
        for index, raw_op in enumerate(operations):
            if not isinstance(raw_op, Mapping):
                raise TypeError(f"operation {index} must be an object")
            op = dict(raw_op)
            kind = op.get("op")
            if not isinstance(kind, str):
                raise ValueError(f"operation {index} is missing string 'op'")

            if kind in {"update", "set"}:
                query = _select(level, op.get("select"))
                properties = op.get("properties", op.get("set", {}))
                raw = op.get("raw", {})
                if not isinstance(properties, Mapping) or not isinstance(raw, Mapping):
                    raise TypeError("update properties/raw must be objects")
                query.update(dict(properties))
                for key, value in raw.items():
                    query.set_raw(key, value)
                results.append({"op": kind, "matched": len(query)})

            elif kind == "translate":
                query = _select(level, op.get("select"))
                query.translate(op.get("dx", 0), op.get("dy", 0))
                results.append({"op": kind, "matched": len(query)})

            elif kind == "delete":
                query = _select(level, op.get("select"))
                count = query.delete()
                results.append({"op": kind, "deleted": count})

            elif kind in {"add", "create", "trigger"}:
                if "id" not in op:
                    raise ValueError(f"{kind} operation requires id")
                properties = op.get("properties", {})
                raw = op.get("raw", {})
                if not isinstance(properties, Mapping) or not isinstance(raw, Mapping):
                    raise TypeError("add properties/raw must be objects")
                if kind == "trigger":
                    obj = level.trigger(op["id"], add=False, **dict(properties))
                else:
                    obj = level.create(op["id"], add=False, **dict(properties))
                for key, value in raw.items():
                    obj.set_raw(key, value)
                level.add(obj)
                results.append({"op": kind, "uid": obj.uid, "object_id": obj.object_id})

            elif kind == "copy":
                query = _select(level, op.get("select"))
                copied = query.copy(dx=op.get("dx", 0), dy=op.get("dy", 0))
                results.append({"op": kind, "copied": len(copied)})

            elif kind == "copy_isolated":
                query = _select(level, op.get("select"))
                copied = query.copy_isolated(
                    dx=op.get("dx", 0), dy=op.get("dy", 0),
                    remap_items=bool(op.get("remap_items", False)),
                    remap_controls=bool(op.get("remap_controls", False)),
                    item_ids=op.get("item_ids"),
                    control_ids=op.get("control_ids"),
                )
                results.append({
                    "op": kind,
                    "copied": len(copied),
                    "group_map": {str(k): v for k, v in copied.group_map.items()},
                    "item_map": {str(k): v for k, v in copied.item_map.items()},
                    "control_map": {str(k): v for k, v in copied.control_map.items()},
                })

            elif kind == "remap":
                query = _select(level, op.get("select"))
                ns = normalize_namespace(op.get("namespace", "group"))
                mapping_raw = op.get("mapping")
                if not isinstance(mapping_raw, Mapping):
                    raise TypeError("remap.mapping must be an object")
                mapping = {int(k): int(v) for k, v in mapping_raw.items()}
                query.remap(ns, mapping)
                results.append({"op": kind, "matched": len(query), "namespace": ns.value})

            elif kind == "set_raw":
                query = _select(level, op.get("select"))
                if "key" not in op or "value" not in op:
                    raise ValueError("set_raw requires key and value")
                query.set_raw(op["key"], op["value"])
                results.append({"op": kind, "matched": len(query)})

            else:
                raise ValueError(f"Unknown patch operation {kind!r}")

    return {"ok": True, "operations": results}
