from __future__ import annotations

from collections import Counter, deque
from typing import Any, TYPE_CHECKING

from .ids import IdNamespace, normalize_namespace

if TYPE_CHECKING:
    from .level import GDLevel


class LevelRelations:
    """Structural ID/reference inspection for an existing level.

    This module deliberately models *data relationships*, not Geometry Dash's
    runtime execution order.  A Spawn/Move reference may be relevant to control
    flow, while another group reference may only be a target/center.  Keeping
    that distinction honest makes the output useful to agents without inventing
    semantics the catalog does not know yet.
    """

    def __init__(self, level: "GDLevel") -> None:
        self._level = level

    @property
    def level(self) -> "GDLevel":
        return self._level

    def id(
        self, namespace: str | IdNamespace, ident: int, *,
        scope: dict[str | IdNamespace, int] | None = None,
        include_objects: bool = False,
    ) -> dict[str, Any]:
        ns = normalize_namespace(namespace)
        ident = int(ident)
        references = self._level.references(ns, ident, scope=scope)
        identifiers = self._level.identifiers(ns, ident, scope=scope)
        result: dict[str, Any] = {
            "namespace": ns.value,
            "id": ident,
            **({"scope": {normalize_namespace(k).value: int(v) for k, v in scope.items()}} if scope else {}),
            "referenced_by": references.describe(include_objects=include_objects),
            "identified_by": identifiers.describe(include_objects=include_objects),
        }
        members = self._level.members(ns, ident)
        if len(members):
            result["members"] = members.describe(include_objects=include_objects)
        return result

    def overview(self, namespace: str | IdNamespace) -> dict[str, Any]:
        """Compact usage counts for every known ID in one namespace."""
        ns = normalize_namespace(namespace)
        refs: Counter[int] = Counter()
        defs: Counter[int] = Counter()
        memberships: Counter[int] = Counter()
        for obj in self._level._objects:
            refs.update(obj.references(ns))
            defs.update(obj.identifiers(ns))
            memberships.update(obj.memberships(ns))
        ids = sorted(set(refs) | set(defs) | set(memberships))
        return {
            "namespace": ns.value,
            "id_count": len(ids),
            "ids": [
                {
                    "id": ident,
                    "references": refs[ident],
                    "identifiers": defs[ident],
                    **({"members": memberships[ident]} if memberships[ident] else {}),
                }
                for ident in ids
            ],
        }

    def group(self, group_id: int, *, include_objects: bool = False) -> dict[str, Any]:
        group_id = int(group_id)
        members = self._level.in_group(group_id)
        referenced_by = self._level.references(group=group_id)
        outgoing = sorted({
            ident
            for obj in members
            for ident in obj.group_references()
            if ident != group_id
        })
        co_memberships = sorted({
            ident
            for obj in members
            for ident in obj.membership_groups()
            if ident != group_id
        })
        incoming_groups = sorted({
            source
            for obj in referenced_by
            for source in obj.membership_groups()
            if source != group_id
        })
        return {
            "group": group_id,
            "members": members.describe(include_objects=include_objects),
            "referenced_by": referenced_by.describe(include_objects=include_objects),
            "outgoing_group_references": outgoing,
            "incoming_member_groups": incoming_groups,
            "co_memberships": co_memberships,
        }

    def group_edges(
        self, *, groups: set[int] | None = None, include_ungrouped: bool = False,
    ) -> list[dict[str, Any]]:
        """Return evidence-bearing structural edges between member groups.

        One object can belong to multiple groups and reference multiple groups,
        so an object may produce several edges.  ``key``/``property`` are kept on
        each edge so callers can distinguish a Move target from a Spawn target
        without reparsing the object.
        """
        wanted = None if groups is None else {int(v) for v in groups}
        edges: list[dict[str, Any]] = []
        for obj in self._level._objects:
            sources = tuple(obj.membership_groups())
            details = obj.reference_details(IdNamespace.GROUP)
            if not details:
                continue
            if not sources:
                if not include_ungrouped:
                    continue
                sources = (None,)
            for detail in details:
                target = int(detail["value"])
                for source in sources:
                    if wanted is not None and source not in wanted and target not in wanted:
                        continue
                    edge = {
                        "source_group": source,
                        "target_group": target,
                        "object_uid": obj.uid,
                        "object_id": obj.object_id,
                        "object_name": obj.object_name,
                        "key": detail.get("key"),
                        "property": detail.get("property"),
                        "reference_kind": detail.get("kind"),
                    }
                    if "role" in detail:
                        edge["role"] = detail["role"]
                    if "index" in detail:
                        edge["index"] = detail["index"]
                    edges.append(edge)
        return edges

    def trace_group(
        self, group_id: int, *, depth: int = 1, direction: str = "both",
    ) -> dict[str, Any]:
        """Trace nearby group relationships without claiming execution flow."""
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise ValueError("depth must be a non-negative integer")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction must be 'outgoing', 'incoming', or 'both'")
        root = int(group_id)
        all_edges = self.group_edges(include_ungrouped=False)
        outgoing: dict[int, list[dict[str, Any]]] = {}
        incoming: dict[int, list[dict[str, Any]]] = {}
        for edge in all_edges:
            source, target = edge["source_group"], edge["target_group"]
            if source is not None:
                outgoing.setdefault(source, []).append(edge)
            incoming.setdefault(target, []).append(edge)

        reached = {root}
        frontier = deque([(root, 0)])
        selected: list[dict[str, Any]] = []
        seen_edge_ids: set[tuple[Any, ...]] = set()
        while frontier:
            current, distance = frontier.popleft()
            if distance >= depth:
                continue
            candidates: list[tuple[dict[str, Any], int | None]] = []
            if direction in {"outgoing", "both"}:
                candidates.extend((edge, edge["target_group"]) for edge in outgoing.get(current, ()))
            if direction in {"incoming", "both"}:
                candidates.extend((edge, edge["source_group"]) for edge in incoming.get(current, ()))
            for edge, next_group in candidates:
                if next_group is None:
                    continue
                signature = (
                    edge["source_group"], edge["target_group"], edge["object_uid"],
                    edge.get("key"), edge.get("index"), edge.get("role"),
                )
                if signature not in seen_edge_ids:
                    seen_edge_ids.add(signature)
                    selected.append(edge)
                if next_group not in reached:
                    reached.add(next_group)
                    frontier.append((next_group, distance + 1))
        return {
            "root_group": root,
            "depth": depth,
            "direction": direction,
            "groups": sorted(reached),
            "edges": selected,
        }
