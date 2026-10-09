from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, TYPE_CHECKING

from .ids import IdNamespace, validate_mapping
from .numeric import GDReal
from .object import GDObject

if TYPE_CHECKING:
    from .level import GDLevel
    from .query import ObjectCollection


class ObjectTemplate:
    """Reusable snapshot of a group of GD objects.

    The template is intentionally data-oriented: it does not emulate G.js/SPWN
    execution contexts or timelines.  Internal Group IDs (membership groups)
    are isolated on each instantiation, while external IDs only change when the
    caller explicitly binds them.
    """

    def __init__(self, objects: Iterable[GDObject]) -> None:
        source = list(objects)
        if any(not isinstance(obj, GDObject) for obj in source):
            raise TypeError("ObjectTemplate expects GDObject instances")
        # Clone immediately so later edits/deletes of the source level cannot
        # silently change the meaning of a previously-created template.
        self._objects = tuple(obj.clone() for obj in source)

    def __len__(self) -> int:
        return len(self._objects)

    @property
    def internal_groups(self) -> tuple[int, ...]:
        return tuple(sorted({gid for obj in self._objects for gid in obj.membership_groups()}))

    def _ids(self, namespace: IdNamespace) -> set[int]:
        values: set[int] = set()
        for obj in self._objects:
            values.update(obj.references(namespace))
            values.update(obj.identifiers(namespace))
            if namespace is IdNamespace.GROUP:
                values.update(obj.membership_groups())
        return values

    def describe(self) -> dict[str, Any]:
        counts = Counter(obj.object_id for obj in self._objects)
        points: list[tuple[GDReal, GDReal]] = []
        for obj in self._objects:
            x, y = obj.get("x"), obj.get("y")
            if isinstance(x, GDReal) and isinstance(y, GDReal):
                points.append((x, y))
        bbox = None
        if points:
            bbox = [
                min(p[0] for p in points).raw,
                min(p[1] for p in points).raw,
                max(p[0] for p in points).raw,
                max(p[1] for p in points).raw,
            ]
        return {
            "object_count": len(self._objects),
            "object_counts": [
                {"object_id": oid, "count": count}
                for oid, count in counts.most_common()
            ],
            "position_bounds": bbox,
            "internal_groups": list(self.internal_groups),
            "references": {
                ns.value: sorted({ident for obj in self._objects for ident in obj.references(ns)})
                for ns in IdNamespace
            },
            "identifiers": {
                ns.value: sorted({ident for obj in self._objects for ident in obj.identifiers(ns)})
                for ns in IdNamespace
                if any(obj.identifiers(ns) for obj in self._objects)
            },
        }

    @staticmethod
    def _binding(
        namespace: IdNamespace,
        mapping: Mapping[int, int] | None,
        available: set[int],
    ) -> dict[int, int]:
        result = validate_mapping(namespace, mapping or {})
        missing = set(result) - available
        if missing:
            raise ValueError(
                f"Template does not contain {namespace.value} ID(s): {sorted(missing)}"
            )
        return result

    def instantiate(
        self,
        level: "GDLevel",
        *,
        dx: Any = 0,
        dy: Any = 0,
        bind_groups: Mapping[int, int] | None = None,
        bind_items: Mapping[int, int] | None = None,
        bind_controls: Mapping[int, int] | None = None,
        bind_colors: Mapping[int, int] | None = None,
        bind_blocks: Mapping[int, int] | None = None,
    ) -> "ObjectCollection":
        """Instantiate this snapshot into ``level`` with explicit ID bindings.

        Every unbound membership Group ID is allocated freshly, preventing two
        instances from accidentally sharing internal group state.  Other ID
        namespaces are never guessed: they keep their original values unless a
        binding is explicitly supplied.
        """
        bindings = {
            IdNamespace.GROUP: self._binding(IdNamespace.GROUP, bind_groups, self._ids(IdNamespace.GROUP)),
            IdNamespace.ITEM: self._binding(IdNamespace.ITEM, bind_items, self._ids(IdNamespace.ITEM)),
            IdNamespace.CONTROL: self._binding(IdNamespace.CONTROL, bind_controls, self._ids(IdNamespace.CONTROL)),
            IdNamespace.COLOR: self._binding(IdNamespace.COLOR, bind_colors, self._ids(IdNamespace.COLOR)),
            IdNamespace.BLOCK: self._binding(IdNamespace.BLOCK, bind_blocks, self._ids(IdNamespace.BLOCK)),
        }

        internal = set(self.internal_groups)
        unbound_internal = sorted(internal - set(bindings[IdNamespace.GROUP]))
        dxv, dyv = GDReal.from_value(dx), GDReal.from_value(dy)

        with level.edit():
            # Allocation lives inside the same transaction as object insertion so
            # a failed instantiation cannot leak reserved IDs into later builds.
            auto_groups = level.allocate_map(
                IdNamespace.GROUP,
                unbound_internal,
                avoid=bindings[IdNamespace.GROUP].values(),
            )
            group_map = {**auto_groups, **bindings[IdNamespace.GROUP]}
            copies = [obj.clone() for obj in self._objects]
            for obj in copies:
                obj.translate(dxv, dyv)
                if group_map:
                    obj.remap_groups(group_map)
                if bindings[IdNamespace.ITEM]:
                    obj.remap_items(bindings[IdNamespace.ITEM])
                if bindings[IdNamespace.CONTROL]:
                    obj.remap_controls(bindings[IdNamespace.CONTROL])
                if bindings[IdNamespace.COLOR]:
                    obj.remap_colors(bindings[IdNamespace.COLOR])
                if bindings[IdNamespace.BLOCK]:
                    obj.remap_blocks(bindings[IdNamespace.BLOCK])
            result = level.extend(copies)
            result.group_map = group_map
            result.item_map = bindings[IdNamespace.ITEM]
            result.control_map = bindings[IdNamespace.CONTROL]
            result.color_map = bindings[IdNamespace.COLOR]
            result.block_map = bindings[IdNamespace.BLOCK]
            return result
