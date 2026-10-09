from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, TYPE_CHECKING

from .ids import IdNamespace, normalize_namespace
from .numeric import GDReal
from .object import GDObject

if TYPE_CHECKING:
    from .level import GDLevel


_MISSING = object()


class MultipleObjectsFound(LookupError):
    pass


class SelectionCardinalityError(LookupError):
    """Raised when a selection does not contain the expected number of objects."""


class ObjectCollection(Sequence[GDObject]):
    """Snapshot selection of level-owned objects with atomic batch operations."""

    def __init__(self, level: "GDLevel", objects: Iterable[GDObject] | None = None):
        self._level = level
        self._objects = list(level._objects if objects is None else objects)
        if any(obj.owner is not level for obj in self._objects):
            raise ValueError("ObjectCollection can only contain objects owned by its level")
        self.group_map: dict[int, int] = {}
        self.item_map: dict[int, int] = {}
        self.control_map: dict[int, int] = {}
        self.color_map: dict[int, int] = {}
        self.block_map: dict[int, int] = {}

    def __len__(self) -> int:
        return len(self._objects)

    def __iter__(self) -> Iterator[GDObject]:
        return iter(self._objects)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return ObjectCollection(self._level, self._objects[index])
        return self._objects[index]

    def first(self, default: Any = None) -> GDObject | Any:
        return self._objects[0] if self._objects else default

    def last(self, default: Any = None) -> GDObject | Any:
        return self._objects[-1] if self._objects else default

    def one(self) -> GDObject:
        if len(self._objects) != 1:
            raise MultipleObjectsFound(f"Expected exactly one object, found {len(self._objects)}")
        return self._objects[0]

    def expect(
        self, count: int | None = None, *,
        at_least: int | None = None, at_most: int | None = None,
    ) -> "ObjectCollection":
        """Assert the selection cardinality and return the same selection.

        This is intended for edits where selecting the wrong number of objects is
        more dangerous than failing early.  It composes naturally with mutations::

            level.find(901, target_group=42).expect(3).update(move_x=120)
        """
        values = {"count": count, "at_least": at_least, "at_most": at_most}
        for name, value in values.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")
        if count is not None and (at_least is not None or at_most is not None):
            raise ValueError("count cannot be combined with at_least/at_most")
        if at_least is not None and at_most is not None and at_least > at_most:
            raise ValueError("at_least cannot exceed at_most")

        actual = len(self._objects)
        ok = (
            actual == count if count is not None else
            (at_least is None or actual >= at_least) and (at_most is None or actual <= at_most)
        )
        if not ok:
            if count is not None:
                expected = f"exactly {count}"
            elif at_least is not None and at_most is not None:
                expected = f"between {at_least} and {at_most}"
            elif at_least is not None:
                expected = f"at least {at_least}"
            else:
                expected = f"at most {at_most}"
            raise SelectionCardinalityError(
                f"Expected {expected} selected object(s), found {actual}"
            )
        return self

    def describe(self, *, include_objects: bool = False) -> dict[str, Any]:
        """Return a JSON-serializable structural summary of this selection."""
        counts = Counter(obj.object_id for obj in self._objects)
        refs = {
            ns.value: sorted({ident for obj in self._objects for ident in obj.references(ns)})
            for ns in IdNamespace
        }
        identifiers = {
            ns.value: sorted({ident for obj in self._objects for ident in obj.identifiers(ns)})
            for ns in IdNamespace
            if any(obj.identifiers(ns) for obj in self._objects)
        }
        position_bounds = self.position_bounds()
        result: dict[str, Any] = {
            "count": len(self._objects),
            "object_counts": [
                {
                    "object_id": oid,
                    "name": (
                        self._level.catalog.get_object(oid).name
                        if self._level.catalog.get_object(oid) is not None
                        else f"OBJ_{oid}"
                    ),
                    "count": count,
                }
                for oid, count in counts.most_common()
            ],
            "membership_groups": sorted(set(self.membership_groups())),
            "references": refs,
            "identifiers": identifiers,
            "position_bounds": (
                None if position_bounds is None else [value.raw for value in position_bounds]
            ),
        }
        if include_objects:
            objects: list[dict[str, Any]] = []
            for obj in self._objects:
                x, y = obj.get("x"), obj.get("y")
                objects.append({
                    "uid": obj.uid,
                    "object_id": obj.object_id,
                    "name": obj.object_name,
                    "x": x.raw if isinstance(x, GDReal) else x,
                    "y": y.raw if isinstance(y, GDReal) else y,
                    "groups": list(obj.membership_groups()),
                })
            result["objects"] = objects
        return result

    def slice(self, start: int, count: int | None = None) -> "ObjectCollection":
        return ObjectCollection(self._level, self._objects[start:] if count is None else self._objects[start:start + count])

    @staticmethod
    def _read(obj: GDObject, field: str) -> Any:
        if field in {"id", "object_id"}:
            return obj.object_id
        if field == "uid":
            return obj.uid
        return obj.get(field, _MISSING)

    @staticmethod
    def _match(value: Any, op: str, expected: Any) -> bool:
        if value is _MISSING:
            return False
        if op == "eq":
            return value == expected
        if op == "ne":
            return value != expected
        if op == "lt":
            return value < expected
        if op == "le":
            return value <= expected
        if op == "gt":
            return value > expected
        if op == "ge":
            return value >= expected
        if op == "in":
            return value in expected
        if op == "contains":
            try:
                return expected in value
            except TypeError:
                return False
        if op == "between":
            low, high = expected
            return low <= value <= high
        raise ValueError(f"Unsupported query operator: {op}")

    def filter(
        self,
        selector: Any = None,
        *,
        where: Callable[[GDObject], bool] | None = None,
        **lookups: Any,
    ) -> "ObjectCollection":
        oid = None
        if selector is not None:
            oid = self._level.catalog.resolve_object_id(selector)
        if "id" in lookups:
            if oid is not None:
                raise ValueError("Object ID specified twice")
            oid = self._level.catalog.resolve_object_id(lookups.pop("id"))
        if "object_id" in lookups:
            if oid is not None:
                raise ValueError("Object ID specified twice")
            oid = self._level.catalog.resolve_object_id(lookups.pop("object_id"))

        parsed: list[tuple[str, str, Any]] = []
        valid_ops = {"ne", "lt", "le", "gt", "ge", "in", "contains", "between"}
        for expr, expected in lookups.items():
            if "__" in expr:
                field, op = expr.rsplit("__", 1)
                if op not in valid_ops:
                    field, op = expr, "eq"
            else:
                field, op = expr, "eq"
            parsed.append((field, op, expected))

        def predicate(obj: GDObject) -> bool:
            if oid is not None and obj.object_id != oid:
                return False
            if where is not None and not where(obj):
                return False
            return all(self._match(self._read(obj, field), op, expected) for field, op, expected in parsed)

        return ObjectCollection(self._level, (obj for obj in self._objects if predicate(obj)))

    def where(self, predicate: Callable[[GDObject], bool]) -> "ObjectCollection":
        """Explicit predicate-only filter, useful in procedural scripts."""
        if not callable(predicate):
            raise TypeError("predicate must be callable")
        return self.filter(where=predicate)

    def exclude(self, selector: Any = None, *, where=None, **lookups) -> "ObjectCollection":
        excluded = {id(obj) for obj in self.filter(selector, where=where, **lookups)}
        return ObjectCollection(self._level, (obj for obj in self._objects if id(obj) not in excluded))

    def apply(self, action: Callable[[GDObject], Any]) -> "ObjectCollection":
        with self._level.edit():
            for obj in self._objects:
                action(obj)
        return self

    def update(self, properties: Mapping[str, Any] | None = None, /, **kwargs: Any) -> "ObjectCollection":
        changes = dict(properties or {})
        changes.update(kwargs)

        def edit(obj: GDObject) -> None:
            for name, value in changes.items():
                actual = value(obj.get(name)) if callable(value) else value
                obj.set(name, actual)

        return self.apply(edit)

    def set_raw(self, key: int | str, value: Any) -> "ObjectCollection":
        return self.apply(lambda obj: obj.set_raw(key, value))

    def translate(self, dx: Any = 0, dy: Any = 0) -> "ObjectCollection":
        dxv, dyv = GDReal.from_value(dx), GDReal.from_value(dy)
        return self.apply(lambda obj: obj.translate(dxv, dyv))

    def move_to(self, *, x: Any | None = None, y: Any | None = None) -> "ObjectCollection":
        return self.apply(lambda obj: obj.move_to(x=x, y=y))

    def remap(self, namespace: str | IdNamespace, mapping: Mapping[int, int]) -> "ObjectCollection":
        ns = normalize_namespace(namespace)
        return self.apply(lambda obj: obj.remap(ns, mapping))

    def delete(self) -> int:
        count = self._level._remove(self._objects)
        self._objects.clear()
        return count

    def copy(self, *, dx: Any = 0, dy: Any = 0) -> "ObjectCollection":
        dxv, dyv = GDReal.from_value(dx), GDReal.from_value(dy)
        copies = [obj.clone() for obj in self._objects]
        for obj in copies:
            obj.translate(dxv, dyv)
        return self._level.extend(copies)

    def copy_isolated(
        self,
        *,
        dx: Any = 0,
        dy: Any = 0,
        remap_items: bool = False,
        remap_controls: bool = False,
        item_ids: Iterable[int] | None = None,
        control_ids: Iterable[int] | None = None,
    ) -> "ObjectCollection":
        dxv, dyv = GDReal.from_value(dx), GDReal.from_value(dy)
        with self._level.edit():
            group_ids = sorted({gid for obj in self._objects for gid in obj.membership_groups()})
            group_map = self._level.allocate_map(IdNamespace.GROUP, group_ids)

            def choose(ns: IdNamespace, all_refs: bool, explicit: Iterable[int] | None) -> list[int]:
                refs = sorted({ident for obj in self._objects for ident in obj.references(ns)})
                chosen = list(dict.fromkeys(explicit)) if explicit is not None else (refs if all_refs else [])
                missing = set(chosen) - set(refs)
                if missing:
                    raise ValueError(f"Requested {ns.value} IDs are not referenced by selection: {sorted(missing)}")
                return chosen

            item_map = self._level.allocate_map(IdNamespace.ITEM, choose(IdNamespace.ITEM, remap_items, item_ids))
            control_map = self._level.allocate_map(IdNamespace.CONTROL, choose(IdNamespace.CONTROL, remap_controls, control_ids))
            copies = [obj.clone() for obj in self._objects]
            for obj in copies:
                obj.translate(dxv, dyv)
                obj.remap_groups(group_map)
                obj.remap_items(item_map)
                obj.remap_controls(control_map)
            result = self._level.extend(copies)
            result.group_map = group_map
            result.item_map = item_map
            result.control_map = control_map
            return result

    def template(self):
        """Freeze this selection into a reusable :class:`ObjectTemplate`."""
        from .templates import ObjectTemplate
        return ObjectTemplate(self._objects)

    def membership_groups(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(gid for obj in self._objects for gid in obj.membership_groups()))

    def position_bounds(self) -> tuple[GDReal, GDReal, GDReal, GDReal] | None:
        """Bounds of object *positions*, not visual/collision geometry.

        Geometry-aware bounds require per-Object-ID size/hitbox knowledge and
        are intentionally left for the later spatial-knowledge layer.
        """
        points: list[tuple[GDReal, GDReal]] = []
        for obj in self._objects:
            x, y = obj.get("x"), obj.get("y")
            if isinstance(x, GDReal) and isinstance(y, GDReal):
                points.append((x, y))
        if not points:
            return None
        return (
            min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points),
        )

    def bbox(self) -> tuple[GDReal, GDReal, GDReal, GDReal] | None:
        """Compatibility alias for :meth:`position_bounds`.

        This is not an object-size or hitbox bounding box.
        """
        return self.position_bounds()

    def order_by(self, field: str, *, reverse: bool = False) -> "ObjectCollection":
        present: list[tuple[Any, GDObject]] = []
        missing: list[GDObject] = []
        for obj in self._objects:
            value = self._read(obj, field)
            if value is _MISSING or value is None:
                missing.append(obj)
            else:
                present.append((value, obj))

        def key(pair):
            value = pair[0]
            if isinstance(value, GDReal):
                return (0, value.decimal)
            if isinstance(value, (int, bool)):
                return (0, value)
            return (1, str(value))

        present.sort(key=key, reverse=reverse)
        return ObjectCollection(self._level, [obj for _, obj in present] + missing)
