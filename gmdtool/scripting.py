from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .ids import BlockId, ColorId, ControlId, GroupId, IdNamespace, ItemId
from .numeric import GDReal

if TYPE_CHECKING:
    from .level import GDLevel
    from .object import GDObject
    from .query import ObjectCollection


class GroupHandle(GroupId):
    """A level-bound Group ID with small, explicit trigger conveniences.

    It remains an ``int``/``GroupId`` value, so it can be passed anywhere a
    normal group ID is accepted.  The attached level is only used by the
    convenience methods; it is never serialized into the `.gmd` data.
    """

    def __new__(cls, value: int, level: "GDLevel") -> "GroupHandle":
        obj = super().__new__(cls, int(value))
        obj._level = level
        return obj

    @property
    def level(self) -> "GDLevel":
        return self._level

    @property
    def objects(self) -> "ObjectCollection":
        """Objects that belong to this group."""
        return self._level.in_group(int(self))

    @property
    def references(self) -> "ObjectCollection":
        """Objects that semantically reference this group."""
        return self._level.references(group=int(self))

    def add(self, *objects: "GDObject") -> "GroupHandle":
        """Add this group membership to objects without auto-adding them to a level."""
        for obj in objects:
            if obj.owner is not None and obj.owner is not self._level:
                raise ValueError("Cannot apply a level-bound group handle to an object owned by another level")
            obj.add_group(int(self))
        return self

    def move(self, *, x: Any = 0, y: Any = 0, duration: Any = 0, at=None) -> "GDObject":
        return self._level.move(int(self), x=x, y=y, duration=duration, at=at)

    def call(self, *, delay: Any = 0, at=None) -> "GDObject":
        """Spawn/call this group using a Spawn Trigger."""
        return self._level.spawn(int(self), delay=delay, at=at)

    spawn = call

    def toggle(self, active: bool = True, *, at=None) -> "GDObject":
        return self._level.toggle(int(self), active=active, at=at)

    def alpha(self, opacity: Any, *, duration: Any = 0, at=None) -> "GDObject":
        return self._level.alpha(int(self), opacity, duration=duration, at=at)

    def rotate(
        self, degrees: Any, *, duration: Any = 0,
        center_group: int | GroupId | None = None, at=None,
    ) -> "GDObject":
        return self._level.rotate(
            int(self), degrees, duration=duration,
            center_group=None if center_group is None else int(center_group), at=at,
        )

    def follow(
        self, follow_group: int | GroupId, *, duration: Any = 0,
        x_mod: Any = 1, y_mod: Any = 1, at=None,
    ) -> "GDObject":
        return self._level.follow(
            int(self), int(follow_group), duration=duration,
            x_mod=x_mod, y_mod=y_mod, at=at,
        )

    def describe(self, *, include_objects: bool = False) -> dict[str, Any]:
        """Describe this group's members and structural references."""
        return self._level.describe_group(int(self), include_objects=include_objects)

    def copy_isolated(self, **kwargs: Any) -> "ObjectCollection":
        """Copy this group's members while remapping its internal IDs."""
        return self.objects.copy_isolated(**kwargs)

    def template(self):
        """Freeze this group's current members into a reusable template."""
        return self.objects.template()


class ColorHandle(ColorId):
    """Level-bound Color Channel ID with explicit inspection/generation helpers."""

    def __new__(cls, value: int, level: "GDLevel") -> "ColorHandle":
        obj = super().__new__(cls, int(value))
        obj._level = level
        return obj

    @property
    def level(self) -> "GDLevel":
        return self._level

    @property
    def references(self) -> "ObjectCollection":
        return self._level.references(color=int(self))

    def describe(self, *, include_objects: bool = False) -> dict[str, Any]:
        return self._level.relations.id("color", int(self), include_objects=include_objects)

    def trigger(self, *, at=None, **properties: Any) -> "GDObject":
        """Create a Color Trigger targeting this channel."""
        if "target_color" in properties or "target_color_id" in properties:
            raise TypeError("ColorHandle.trigger() supplies target_color automatically")
        return self._level.trigger(899, at=at, target_color=int(self), **properties)

    change = trigger


class BlockHandle(BlockId):
    """Level-bound Collision Block ID for inspecting definitions and users."""

    def __new__(cls, value: int, level: "GDLevel") -> "BlockHandle":
        obj = super().__new__(cls, int(value))
        obj._level = level
        return obj

    @property
    def level(self) -> "GDLevel":
        return self._level

    @property
    def objects(self) -> "ObjectCollection":
        """Collision Block objects that define this Block ID."""
        return self._level.identifiers(block=int(self))

    @property
    def references(self) -> "ObjectCollection":
        """Objects that reference this Block ID."""
        return self._level.references(block=int(self))

    def describe(self, *, include_objects: bool = False) -> dict[str, Any]:
        return self._level.relations.id("block", int(self), include_objects=include_objects)


class BuildScope:
    """Explicit, level-bound construction defaults for procedural scripts.

    This borrows the useful part of context-based GD builders without ambient
    global state: callers keep the scope in an ordinary Python variable.
    """

    def __init__(
        self, level: "GDLevel", *, groups=(), dx: Any = 0, dy: Any = 0,
    ) -> None:
        self._level = level
        self._groups = tuple(GroupId(group) for group in groups)
        self._dx = GDReal.from_value(dx)
        self._dy = GDReal.from_value(dy)

    @property
    def level(self) -> "GDLevel":
        return self._level

    @property
    def groups(self) -> tuple[GroupId, ...]:
        return self._groups

    def _prepare(self, obj: "GDObject") -> "GDObject":
        if obj.owner is not None:
            raise ValueError("BuildScope expects a detached object")
        if self._dx.decimal != 0 or self._dy.decimal != 0:
            obj.translate(self._dx, self._dy)
        for group in self._groups:
            obj.add_group(int(group))
        return obj

    def add(self, obj: "GDObject") -> "GDObject":
        """Apply this scope to a detached object and add it to the level."""
        return self._level.add(self._prepare(obj))

    def create(self, selector: Any, **properties: Any) -> "GDObject":
        obj = self._level.create(selector, add=False, **properties)
        return self.add(obj)

    new_object = create

    def trigger(self, selector: Any, *, at=None, **properties: Any) -> "GDObject":
        obj = self._level.trigger(selector, add=False, at=at, **properties)
        return self.add(obj)


class NewIds:
    """Level-bound next-free ID allocator.

    This is intentionally a thin facade over ``GDLevel.allocate_ids``.  It
    keeps allocation state on the level instead of in process-global scripting
    state, which makes generated scripts easier to review and compose.
    """

    def __init__(self, level: "GDLevel") -> None:
        self._level = level

    def group(self, *, start: int = 1, reuse_gaps: bool = False) -> GroupHandle:
        ident = self._level.new_group(start=start, reuse_gaps=reuse_gaps)
        return GroupHandle(int(ident), self._level)

    def groups(
        self, count: int, *, start: int = 1, reuse_gaps: bool = False,
    ) -> tuple[GroupHandle, ...]:
        ids = self._level.allocate_ids(
            IdNamespace.GROUP, count, start=start, reuse_gaps=reuse_gaps,
        )
        return tuple(GroupHandle(ident, self._level) for ident in ids)

    def item(self, *, start: int = 1, reuse_gaps: bool = False) -> ItemId:
        return self._level.new_item(start=start, reuse_gaps=reuse_gaps)

    def items(
        self, count: int, *, start: int = 1, reuse_gaps: bool = False,
    ) -> tuple[ItemId, ...]:
        return tuple(
            ItemId(v) for v in self._level.allocate_ids(
                IdNamespace.ITEM, count, start=start, reuse_gaps=reuse_gaps,
            )
        )

    def control(self, *, start: int = 1, reuse_gaps: bool = False) -> ControlId:
        return self._level.new_control(start=start, reuse_gaps=reuse_gaps)

    def controls(
        self, count: int, *, start: int = 1, reuse_gaps: bool = False,
    ) -> tuple[ControlId, ...]:
        return tuple(
            ControlId(v) for v in self._level.allocate_ids(
                IdNamespace.CONTROL, count, start=start, reuse_gaps=reuse_gaps,
            )
        )
