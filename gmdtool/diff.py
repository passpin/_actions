from __future__ import annotations

from collections import defaultdict
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .level import GDLevel
    from .object import GDObject


def _property_state(obj: "GDObject") -> dict[str, list[str]]:
    values: dict[str, list[str]] = defaultdict(list)
    for pair in obj.raw_pairs:
        values[pair.key].append(pair.value)
    return dict(values)


def _label(obj: "GDObject", raw_key: str) -> str:
    try:
        key = int(raw_key)
    except ValueError:
        return raw_key
    schema = obj.catalog.find_property(obj.object_id, key)
    if schema is None:
        schema = obj.catalog.global_property(key)
    return schema.name if schema is not None else f"raw_{raw_key}"


def _object_change(before: "GDObject", after: "GDObject", index_before: int, index_after: int) -> dict[str, Any] | None:
    if before.to_object_string() == after.to_object_string():
        return None
    old, new = _property_state(before), _property_state(after)
    changes: list[dict[str, Any]] = []
    keys = list(dict.fromkeys([*(p.key for p in before.raw_pairs), *(p.key for p in after.raw_pairs)]))
    for key in keys:
        if old.get(key, []) == new.get(key, []):
            continue
        changes.append({
            "key": int(key) if key.lstrip("+-").isdigit() else key,
            "name": _label(after, key),
            "before": old.get(key, []),
            "after": new.get(key, []),
        })
    if before.malformed_tail != after.malformed_tail:
        changes.append({
            "key": "<malformed_tail>",
            "name": "malformed_tail",
            "before": before.malformed_tail,
            "after": after.malformed_tail,
        })
    return {
        "uid": before.uid if before.uid == after.uid else None,
        "index_before": index_before,
        "index_after": index_after,
        "object_id_before": before.object_id,
        "object_id_after": after.object_id,
        "properties": changes,
    }


def diff_levels(before: "GDLevel", after: "GDLevel") -> dict[str, Any]:
    """Return a JSON-serializable semantic/raw diff.

    In-memory clones preserve UIDs and are matched by UID. Independently loaded
    levels fall back to position matching; that mode is intentionally simple and
    does not pretend to solve general object identity.
    """
    before_by_uid = {obj.uid: (i, obj) for i, obj in enumerate(before._objects)}
    after_by_uid = {obj.uid: (i, obj) for i, obj in enumerate(after._objects)}
    common = before_by_uid.keys() & after_by_uid.keys()

    changed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []

    if common:
        for uid in sorted(common, key=lambda u: before_by_uid[u][0]):
            bi, b = before_by_uid[uid]
            ai, a = after_by_uid[uid]
            change = _object_change(b, a, bi, ai)
            if change is not None:
                changed.append(change)
        for uid, (i, obj) in before_by_uid.items():
            if uid not in common:
                removed.append({"uid": uid, "index": i, "object_id": obj.object_id, "raw": obj.to_object_string()})
        for uid, (i, obj) in after_by_uid.items():
            if uid not in common:
                added.append({"uid": uid, "index": i, "object_id": obj.object_id, "raw": obj.to_object_string()})
        match_mode = "uid"
    else:
        count = min(len(before._objects), len(after._objects))
        for i in range(count):
            change = _object_change(before._objects[i], after._objects[i], i, i)
            if change is not None:
                changed.append(change)
        for i, obj in enumerate(before._objects[count:], count):
            removed.append({"index": i, "object_id": obj.object_id, "raw": obj.to_object_string()})
        for i, obj in enumerate(after._objects[count:], count):
            added.append({"index": i, "object_id": obj.object_id, "raw": obj.to_object_string()})
        match_mode = "position"

    header_changed = before.header != after.header
    metadata_changes: dict[str, dict[str, str | None]] = {}
    for key in sorted(set(before.metadata) | set(after.metadata)):
        old, new = before.metadata.get(key), after.metadata.get(key)
        if old != new:
            metadata_changes[key] = {"before": old, "after": new}

    return {
        "format": "gmdtool.diff",
        "version": 1,
        "match_mode": match_mode,
        "changed": changed,
        "added": added,
        "removed": removed,
        "header": {"before": before.header, "after": after.header} if header_changed else None,
        "metadata": metadata_changes,
        "summary": {
            "changed": len(changed),
            "added": len(added),
            "removed": len(removed),
            "metadata_changed": len(metadata_changes),
            "header_changed": header_changed,
        },
    }
