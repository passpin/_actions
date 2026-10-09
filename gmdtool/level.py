from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .catalog import Catalog, default_catalog
from .ids import ControlId, GroupId, IdNamespace, ItemId, allocate_ids, namespace_is_allocatable, normalize_namespace
from .numeric import GDReal
from .object import GDObject
from .objects import get_object_class, resolve_object_class
from .query import ObjectCollection
from .settings import GDLevelSettings
from .structured import GDSequenceList

if TYPE_CHECKING:
    from .relations import LevelRelations
    from .scripting import BlockHandle, BuildScope, ColorHandle, GroupHandle, NewIds


class _EditContext(AbstractContextManager["GDLevel"]):
    def __init__(self, level: "GDLevel") -> None:
        self.level = level
        self.outermost = False

    def __enter__(self) -> "GDLevel":
        level = self.level
        if level._edit_depth == 0:
            self.outermost = True
            states = [
                (obj, type(obj), list(obj._pairs), obj._malformed_tail, obj._owner)
                for obj in level._objects
            ]
            level._edit_snapshot = (
                list(level._objects), list(level._layout), states,
                level._header, level.trailing_semicolon, dict(level.metadata),
                {ns: set(values) for ns, values in level._reserved.items()},
                level._dirty,
            )
        level._edit_depth += 1
        return level

    def __exit__(self, exc_type, exc, tb) -> bool:
        level = self.level
        level._edit_depth -= 1
        if exc_type is not None and self.outermost:
            level._rollback_edit_snapshot()
        if self.outermost:
            level._edit_snapshot = None
        return False


class GDLevel:
    def __init__(self, header: str = "", *, catalog: Catalog | None = None) -> None:
        if ";" in header:
            raise ValueError("Level header cannot contain ';'")
        self.catalog = catalog or default_catalog()
        self._header = header
        self.trailing_semicolon = False
        self._objects: list[GDObject] = []
        self._layout: list[GDObject | None] = []
        self.metadata: dict[str, str] = {}
        self._metadata_tags: dict[str, str] = {}
        self._source_bytes: bytes | None = None
        self._source_xml: str | None = None
        self._source_had_bom = False
        self._original_raw: str | None = None
        self._original_metadata: dict[str, str] = {}
        self._dirty = False
        self._reserved: dict[IdNamespace, set[int]] = {
            IdNamespace.GROUP: set(),
            IdNamespace.ITEM: set(),
            IdNamespace.CONTROL: set(),
        }
        self._edit_depth = 0
        self._edit_snapshot = None

    @classmethod
    def parse(cls, raw: str, *, catalog: Catalog | None = None) -> "GDLevel":
        chunks = raw.split(";")
        trailing = raw.endswith(";")
        level = cls(chunks[0] if chunks else "", catalog=catalog)
        level.trailing_semicolon = trailing
        end = len(chunks) - (1 if trailing else 0)
        for chunk in chunks[1:end]:
            if chunk == "":
                level._layout.append(None)
                continue
            obj = GDObject.parse(chunk, catalog=level.catalog)
            object.__setattr__(obj, "_owner", level)
            level._objects.append(obj)
            level._layout.append(obj)
        level._dirty = False
        return level

    @classmethod
    def load(cls, path: str | Path, *, catalog: Catalog | None = None) -> "GDLevel":
        from .io import GMD
        return GMD.load(path, catalog=catalog)

    @property
    def header(self) -> str:
        return self._header

    @header.setter
    def header(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("header must be str")
        if ";" in value:
            raise ValueError("Level header cannot contain ';'")
        if getattr(self, "_header", None) != value:
            self._header = value
            self._mark_dirty()

    @property
    def settings(self) -> GDLevelSettings:
        return GDLevelSettings(self)

    @property
    def relations(self) -> "LevelRelations":
        """Structural relationship inspector for the current level."""
        from .relations import LevelRelations
        return LevelRelations(self)

    @property
    def objects(self) -> ObjectCollection:
        return ObjectCollection(self)

    @property
    def new(self) -> "NewIds":
        """Next-free IDs scoped to this level (for example ``level.new.group()``)."""
        from .scripting import NewIds
        return NewIds(self)

    def group(self, group_id: int) -> "GroupHandle":
        """Return a level-bound group handle without allocating a new ID."""
        from .scripting import GroupHandle
        return GroupHandle(int(group_id), self)

    def color(self, color_id: int) -> "ColorHandle":
        """Return a level-bound Color Channel handle."""
        from .scripting import ColorHandle
        return ColorHandle(int(color_id), self)

    def block(self, block_id: int) -> "BlockHandle":
        """Return a level-bound Collision Block ID handle."""
        from .scripting import BlockHandle
        return BlockHandle(int(block_id), self)

    def scope(self, *, groups=(), dx: Any = 0, dy: Any = 0) -> "BuildScope":
        """Create an explicit construction scope for repeated generation."""
        from .scripting import BuildScope
        return BuildScope(self, groups=groups, dx=dx, dy=dy)

    @property
    def raw_objects(self) -> tuple[GDObject, ...]:
        return tuple(self._objects)

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _set_source(
        self, *, source_bytes: bytes, source_xml: str,
        metadata_tags: Mapping[str, str] | None = None, had_bom: bool = False,
    ) -> None:
        self._source_bytes = bytes(source_bytes)
        self._source_xml = source_xml
        self._source_had_bom = had_bom
        self._metadata_tags = dict(metadata_tags or {})
        self._original_raw = self.to_level_string()
        self._original_metadata = dict(self.metadata)
        self._dirty = False

    @property
    def can_save_original(self) -> bool:
        return (
            self._source_bytes is not None
            and self._original_raw == self.to_level_string()
            and self._original_metadata == self.metadata
        )

    def to_level_string(self) -> str:
        text = ";".join([self._header, *(obj.to_object_string() if obj is not None else "" for obj in self._layout)])
        if self.trailing_semicolon:
            text += ";"
        return text

    def replace_raw(self, raw: str) -> "GDLevel":
        parsed = GDLevel.parse(raw, catalog=self.catalog)
        for obj in self._objects:
            object.__setattr__(obj, "_owner", None)
        self._header = parsed._header
        self.trailing_semicolon = parsed.trailing_semicolon
        self._objects[:] = parsed._objects
        self._layout[:] = parsed._layout
        for obj in self._objects:
            object.__setattr__(obj, "_owner", self)
        for values in self._reserved.values():
            values.clear()
        self._mark_dirty()
        return self

    def save(self, path: str | Path, *, validate: bool = False, check_references: bool = False) -> None:
        from .io import GMD
        GMD.save(self, path, validate=validate, check_references=check_references)

    # ---------------- object ownership ----------------

    def add(self, obj: GDObject) -> GDObject:
        self.extend([obj])
        return obj

    def extend(self, objects: Iterable[GDObject]) -> ObjectCollection:
        prepared = list(objects)
        if any(not isinstance(obj, GDObject) for obj in prepared):
            raise TypeError("level.extend() expects GDObject instances")
        if len({id(obj) for obj in prepared}) != len(prepared):
            raise ValueError("The same object instance cannot be added twice")
        existing = {id(obj) for obj in self._objects}
        for obj in prepared:
            if id(obj) in existing or obj.owner is not None:
                raise ValueError("Object already belongs to a level; clone it before adding")
        for obj in prepared:
            object.__setattr__(obj, "_owner", self)
            # If a custom catalog ever arrives, level ownership makes semantics
            # consistent rather than half-custom as in the old C# prototype.
            object.__setattr__(obj, "_catalog", self.catalog)
            self._objects.append(obj)
            self._layout.append(obj)
        if prepared:
            self._mark_dirty()
        return ObjectCollection(self, prepared)

    def _remove(self, objects: Iterable[GDObject]) -> int:
        selected = {id(obj) for obj in objects}
        if not selected:
            return 0
        removed = [obj for obj in self._objects if id(obj) in selected]
        for obj in removed:
            object.__setattr__(obj, "_owner", None)
        self._objects[:] = [obj for obj in self._objects if id(obj) not in selected]
        self._layout[:] = [obj for obj in self._layout if obj is None or id(obj) not in selected]
        if removed:
            self._mark_dirty()
        return len(removed)

    def create(self, selector: Any, *, add: bool = True, **properties: Any) -> GDObject:
        cls = resolve_object_class(selector, catalog=self.catalog)
        obj = cls(_catalog=self.catalog, **properties)
        return self.add(obj) if add else obj

    new_object = create

    def find(self, selector: Any = None, *, where=None, **lookups: Any) -> ObjectCollection:
        return self.objects.filter(selector, where=where, **lookups)

    def rect(self, x1: Any, y1: Any, x2: Any, y2: Any, selector: Any = None, **lookups: Any) -> ObjectCollection:
        xa, xb = GDReal.from_value(x1), GDReal.from_value(x2)
        ya, yb = GDReal.from_value(y1), GDReal.from_value(y2)
        low_x, high_x = (xa, xb) if xa <= xb else (xb, xa)
        low_y, high_y = (ya, yb) if ya <= yb else (yb, ya)
        return self.find(selector, x__between=(low_x, high_x), y__between=(low_y, high_y), **lookups)

    def in_group(self, group_id: int) -> ObjectCollection:
        return self.objects.filter(where=lambda obj: group_id in obj.membership_groups())

    def members(
        self, namespace: str | IdNamespace | None = None, ident: int | None = None, **kwargs: int,
    ) -> ObjectCollection:
        """Objects assigned to an ID namespace (Group, Enter Channel, Material, ...)."""
        if kwargs:
            if len(kwargs) != 1 or namespace is not None or ident is not None:
                raise TypeError("Use exactly one keyword namespace or namespace+ident")
            namespace, ident = next(iter(kwargs.items()))
        if namespace is None or ident is None:
            raise TypeError("members() needs a namespace and ID")
        ns = normalize_namespace(namespace)
        return self.objects.filter(where=lambda obj: ident in obj.memberships(ns))

    def references(
        self, namespace: str | IdNamespace | None = None, ident: int | None = None, *,
        scope: Mapping[str | IdNamespace, int] | None = None, **kwargs: int,
    ) -> ObjectCollection:
        if kwargs:
            if len(kwargs) != 1 or namespace is not None or ident is not None:
                raise TypeError("Use exactly one keyword namespace or namespace+ident")
            namespace, ident = next(iter(kwargs.items()))
        if namespace is None or ident is None:
            raise TypeError("references() needs a namespace and ID")
        ns = normalize_namespace(namespace)
        return self.objects.filter(where=lambda obj: ident in obj.references(ns, scope=scope))

    def referencing_group(self, group_id: int) -> ObjectCollection:
        return self.references(group=group_id)

    def identifiers(
        self, namespace: str | IdNamespace | None = None, ident: int | None = None, *,
        scope: Mapping[str | IdNamespace, int] | None = None, **kwargs: int,
    ) -> ObjectCollection:
        """Objects that define/identify an ID in a semantic namespace.

        This is distinct from :meth:`references`: a Collision Block defines a
        Block ID, while Collision Triggers reference that ID.
        """
        if kwargs:
            if len(kwargs) != 1 or namespace is not None or ident is not None:
                raise TypeError("Use exactly one keyword namespace or namespace+ident")
            namespace, ident = next(iter(kwargs.items()))
        if namespace is None or ident is None:
            raise TypeError("identifiers() needs a namespace and ID")
        ns = normalize_namespace(namespace)
        return self.objects.filter(where=lambda obj: ident in obj.identifiers(ns, scope=scope))

    def describe_group(self, group_id: int, *, include_objects: bool = False) -> dict[str, Any]:
        """Backward-compatible shortcut for ``level.relations.group(...)``."""
        return self.relations.group(group_id, include_objects=include_objects)

    # ---------------- transaction ----------------

    def edit(self) -> _EditContext:
        return _EditContext(self)

    def _rollback_edit_snapshot(self) -> None:
        if self._edit_snapshot is None:
            return
        objects, layout, states, header, trailing, metadata, reserved, dirty = self._edit_snapshot
        old_ids = {id(obj) for obj in objects}
        for obj in self._objects:
            if id(obj) not in old_ids and obj.owner is self:
                object.__setattr__(obj, "_owner", None)
        self._objects[:] = objects
        self._layout[:] = layout
        for obj, cls, pairs, tail, owner in states:
            try:
                obj.__class__ = cls
            except TypeError:
                pass
            obj._pairs[:] = pairs
            object.__setattr__(obj, "_malformed_tail", tail)
            object.__setattr__(obj, "_owner", owner)
        self._header = header
        self.trailing_semicolon = trailing
        self.metadata.clear()
        self.metadata.update(metadata)
        self._reserved = {ns: set(values) for ns, values in reserved.items()}
        self._dirty = dirty

    # ---------------- IDs and references ----------------

    def used_ids(self, namespace: str | IdNamespace) -> tuple[int, ...]:
        ns = normalize_namespace(namespace)
        values: set[int] = set()
        for obj in self._objects:
            values.update(obj.references(ns))
            values.update(obj.identifiers(ns))
            values.update(obj.memberships(ns))
        return tuple(sorted(values))

    def allocate_ids(
        self, namespace: str | IdNamespace, count: int = 1, *,
        start: int = 1, reuse_gaps: bool = False, avoid: Iterable[int] = (),
    ) -> list[int]:
        ns = normalize_namespace(namespace)
        if not namespace_is_allocatable(ns):
            raise ValueError(
                f"Automatic allocation for {ns.value} IDs is not defined; "
                "use an explicit ID until its allocation rules are modeled"
            )
        excluded = {int(v) for v in avoid}
        if any(v < 0 for v in excluded):
            raise ValueError("avoid IDs must be non-negative")
        used = set(self.used_ids(ns)) | self._reserved[ns] | excluded
        result = allocate_ids(used, ns, count, start=start, reuse_gaps=reuse_gaps)
        self._reserved[ns].update(result)
        return result

    def new_group(self, *, start: int = 1, reuse_gaps: bool = False) -> GroupId:
        return GroupId(self.allocate_ids(IdNamespace.GROUP, start=start, reuse_gaps=reuse_gaps)[0])

    def new_item(self, *, start: int = 1, reuse_gaps: bool = False) -> ItemId:
        return ItemId(self.allocate_ids(IdNamespace.ITEM, start=start, reuse_gaps=reuse_gaps)[0])

    def new_control(self, *, start: int = 1, reuse_gaps: bool = False) -> ControlId:
        return ControlId(self.allocate_ids(IdNamespace.CONTROL, start=start, reuse_gaps=reuse_gaps)[0])

    def allocate_map(
        self, namespace: str | IdNamespace, old_ids: Iterable[int], *, avoid: Iterable[int] = (),
    ) -> dict[int, int]:
        old = list(dict.fromkeys(int(v) for v in old_ids))
        fresh = self.allocate_ids(namespace, len(old), avoid=avoid)
        return dict(zip(old, fresh))

    def remap(self, namespace: str | IdNamespace, mapping: Mapping[int, int]) -> "GDLevel":
        self.objects.remap(namespace, mapping)
        return self

    def remap_groups(self, mapping: Mapping[int, int]) -> "GDLevel":
        self.objects.remap(IdNamespace.GROUP, mapping)
        return self

    def remap_items(self, mapping: Mapping[int, int]) -> "GDLevel":
        self.objects.remap(IdNamespace.ITEM, mapping)
        return self

    def remap_controls(self, mapping: Mapping[int, int]) -> "GDLevel":
        self.objects.remap(IdNamespace.CONTROL, mapping)
        return self

    def remap_colors(self, mapping: Mapping[int, int]) -> "GDLevel":
        self.objects.remap(IdNamespace.COLOR, mapping)
        return self

    def remap_blocks(self, mapping: Mapping[int, int]) -> "GDLevel":
        self.objects.remap(IdNamespace.BLOCK, mapping)
        return self

    # ---------------- trigger/generation convenience ----------------

    def trigger(self, selector: Any, *, at: tuple[Any, Any] | None = None, add: bool = True, **properties: Any) -> GDObject:
        oid = self.catalog.resolve_object_id(selector)
        schema = self.catalog.get_object(oid)
        if schema is None or schema.base != "trigger":
            raise TypeError(f"OBJ_{oid} is not a trigger in this level's catalog")
        cls = get_object_class(oid, catalog=self.catalog)
        if at is not None:
            properties.setdefault("x", at[0])
            properties.setdefault("y", at[1])
        obj = cls(_catalog=self.catalog, **properties)
        return self.add(obj) if add else obj

    def add_triggers(
        self, specs: Iterable[tuple[Any, Mapping[str, Any]] | GDObject], *,
        x: Any | None = None, y: Any | None = None, dx: Any = 0, dy: Any = 0,
    ) -> ObjectCollection:
        prepared: list[GDObject] = []
        dxv, dyv = GDReal.from_value(dx), GDReal.from_value(dy)
        base_x = GDReal.from_value(x) if x is not None else None
        base_y = GDReal.from_value(y) if y is not None else None
        for index, spec in enumerate(specs):
            if isinstance(spec, GDObject):
                obj = spec
                if not obj.is_trigger:
                    raise TypeError(f"{type(obj).__name__} is not a trigger")
            else:
                selector, properties = spec
                obj = self.trigger(selector, add=False, **dict(properties))
            if obj.get("x") is None and base_x is not None:
                obj.set("x", base_x + dxv * index)
            if obj.get("y") is None and base_y is not None:
                obj.set("y", base_y + dyv * index)
            prepared.append(obj)
        return self.extend(prepared)

    def repeat_trigger(
        self, selector: Any, count: int, *, each=None,
        x: Any | None = None, y: Any | None = None, dx: Any = 0, dy: Any = 0,
        **properties: Any,
    ) -> ObjectCollection:
        if count < 0:
            raise ValueError("count must be non-negative")
        specs = []
        for i in range(count):
            values = dict(properties)
            if each is not None:
                extra = each(i)
                if extra:
                    values.update(extra)
            specs.append((selector, values))
        return self.add_triggers(specs, x=x, y=y, dx=dx, dy=dy)

    def move(self, target: int, *, x: Any = 0, y: Any = 0, duration: Any = 0, at=None) -> GDObject:
        return self.trigger(901, at=at, target_group=int(target), move_x=x, move_y=y, duration=duration)

    def spawn(self, target: int, *, delay: Any = 0, at=None) -> GDObject:
        return self.trigger(1268, at=at, target_group=int(target), delay=delay)

    def toggle(self, target: int, *, active: bool = True, at=None) -> GDObject:
        return self.trigger(1049, at=at, target_group=int(target), activate_group=active)

    def alpha(self, target: int, opacity: Any, *, duration: Any = 0, at=None) -> GDObject:
        return self.trigger(1007, at=at, target_group=int(target), opacity=opacity, duration=duration)

    def rotate(self, target: int, degrees: Any, *, duration: Any = 0, center_group: int | None = None, at=None) -> GDObject:
        properties: dict[str, Any] = {"target_group": int(target), "degrees": degrees, "duration": duration}
        if center_group is not None:
            properties["center_group"] = center_group
        return self.trigger(1346, at=at, **properties)

    def follow(self, target: int, follow_group: int, *, duration: Any = 0, x_mod: Any = 1, y_mod: Any = 1, at=None) -> GDObject:
        return self.trigger(1347, at=at, target_group=int(target), follow_group=follow_group, duration=duration, x_mod=x_mod, y_mod=y_mod)

    def stop(self, target: int, *, command: int = 0, control: bool = False, at=None) -> GDObject:
        return self.trigger(1616, at=at, target_id=int(target), use_control_id=control, command=command)

    def sequence(self, entries: Iterable[tuple[int, int]], *, at=None) -> GDObject:
        raw = ".".join(str(v) for pair in entries for v in pair)
        return self.trigger(3607, at=at, sequence=GDSequenceList(raw))

    # ---------------- AI-facing inspection ----------------

    def summary(self) -> dict[str, Any]:
        counts = Counter(obj.object_id for obj in self._objects)
        return {
            "objects": len(self._objects),
            "distinct_object_ids": len(counts),
            "name": self.metadata.get("k2", ""),
            "creator": self.metadata.get("k5", ""),
            "object_counts": {str(k): v for k, v in counts.most_common()},
        }

    def explain(self, selector: Any = None, *, limit: int | None = 10, **lookups: Any) -> dict[str, Any]:
        selected = self.find(selector, **lookups)
        objects = list(selected if limit is None else selected[:limit])
        return {
            "matched": len(selected),
            "returned": len(objects),
            "objects": [obj.explain() for obj in objects],
        }

    def to_raw_json(self) -> dict[str, Any]:
        layout = []
        for obj in self._layout:
            layout.append(None if obj is None else obj.to_raw_json())
        return {
            "format": "gmdtool.raw-level",
            "version": 1,
            "header": self._header,
            "trailing_semicolon": self.trailing_semicolon,
            "layout": layout,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_raw_json(cls, payload: Mapping[str, Any], *, catalog: Catalog | None = None) -> "GDLevel":
        if payload.get("format") != "gmdtool.raw-level" or payload.get("version") != 1:
            raise ValueError("Unsupported raw-level JSON format")
        level = cls(str(payload.get("header", "")), catalog=catalog)
        level.trailing_semicolon = bool(payload.get("trailing_semicolon", False))
        level.metadata.update({str(k): str(v) for k, v in payload.get("metadata", {}).items()})
        for item in payload.get("layout", []):
            if item is None:
                level._layout.append(None)
                continue
            pairs = [(pair[0], pair[1]) for pair in item.get("pairs", [])]
            raw = ",".join(str(token) for pair in pairs for token in pair)
            if item.get("malformed_tail") is not None:
                raw += ("," if raw else "") + str(item["malformed_tail"])
            obj = GDObject.parse(raw, catalog=level.catalog)
            object.__setattr__(obj, "_owner", level)
            level._objects.append(obj)
            level._layout.append(obj)
        level._dirty = True
        return level

    # ---------------- cross-cutting services ----------------

    def validate(self, *, check_references: bool = False):
        from .validation import validate_level
        return validate_level(self, check_references=check_references)

    def diff(self, other: "GDLevel") -> dict[str, Any]:
        from .diff import diff_levels
        return diff_levels(self, other)

    def apply_patch(self, patch: Mapping[str, Any]) -> dict[str, Any]:
        from .patch import apply_patch
        return apply_patch(self, patch)

    def clone(self, *, preserve_uids: bool = True) -> "GDLevel":
        level = GDLevel(self._header, catalog=self.catalog)
        level.trailing_semicolon = self.trailing_semicolon
        level.metadata.update(self.metadata)
        mapping: dict[int, GDObject] = {}
        for obj in self._objects:
            clone = obj.clone(preserve_uid=preserve_uids)
            object.__setattr__(clone, "_owner", level)
            level._objects.append(clone)
            mapping[id(obj)] = clone
        level._layout = [None if obj is None else mapping[id(obj)] for obj in self._layout]
        level._reserved = {ns: set(values) for ns, values in self._reserved.items()}
        level._dirty = True
        return level
