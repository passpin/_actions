#!/usr/bin/env python3
from __future__ import annotations

import argparse
import keyword
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Allow running directly from a checkout without installation.
import sys
sys.path.insert(0, str(ROOT))

from gmdtool.catalog import Catalog  # noqa: E402

SOURCE_CATALOG = ROOT / "data" / "compiled" / "catalog.normalized.json"
DESTINATION = ROOT / "gmdtool" / "objects.pyi"


def _annotation(prop) -> str:
    namespace_types = {
        "group": "GroupId",
        "item": "ItemId",
        "control": "ControlId",
        "color": "ColorId",
        "block": "BlockId",
    }
    namespaces: list[str] = []
    if prop.namespace is not None:
        namespaces.append(prop.namespace)
    for variant in prop.variants:
        semantic = variant.get("semantic", {})
        namespace = semantic.get("namespace") if isinstance(semantic, dict) else None
        if namespace is not None and namespace not in namespaces:
            namespaces.append(namespace)
    id_types = [namespace_types[ns] for ns in namespaces if ns in namespace_types]
    if id_types and prop.type not in {"groups", "weighted_groups", "sequence", "remap_list"}:
        return " | ".join(["int", *id_types])
    return {
        "bool": "bool",
        "int": "int",
        "group_id": "int | GroupId",
        "item_id": "int | ItemId",
        "control_id": "int | ControlId",
        "real": "int | str | GDReal",
        "enum": "int | str",
        "groups": "str | Iterable[int]",
        "text": "str",
        "string": "str",
    }.get(prop.type, "Any")


def render_stubs(catalog: Catalog) -> str:
    lines = [
        "from __future__ import annotations",
        "from collections.abc import Iterable",
        "from typing import Any",
        "from .ids import BlockId, ColorId, ControlId, GroupId, ItemId",
        "from .numeric import GDReal",
        "from .object import GDObject",
        "from .objects import Trigger",
        "",
    ]

    for oid in catalog.known_object_ids:
        schema = catalog.get_object(oid)
        base = "Trigger" if schema is not None and schema.base == "trigger" else "GDObject"
        props = catalog.properties_for(oid) if schema is not None else ()
        valid = []
        seen: set[str] = set()
        for prop in props:
            name = prop.name
            if not name.isidentifier() or keyword.iskeyword(name) or name.startswith("_") or name in seen:
                continue
            seen.add(name)
            valid.append((name, _annotation(prop)))
        lines.append(f"class OBJ_{oid}({base}):")
        if valid:
            params = ["self", "*", *(f"{name}: {ann} = ..." for name, ann in valid), "**properties: Any"]
            lines.append(f"    def __init__({', '.join(params)}) -> None: ...")
        else:
            lines.append("    def __init__(self, **properties: Any) -> None: ...")
        lines.append("")

    aliases: list[tuple[str, int]] = []
    for name, oid in sorted(catalog.aliases.items()):
        if name.isidentifier() and not keyword.iskeyword(name) and not name.startswith("OBJ_"):
            aliases.append((name, oid))
    if aliases:
        lines.append("# Catalog aliases")
        for name, oid in aliases:
            lines.append(f"{name} = OBJ_{oid}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate OBJ_<ID> typing stubs from the compiled source catalog")
    parser.add_argument("--check", action="store_true", help="fail instead of writing when objects.pyi is stale")
    args = parser.parse_args(argv)

    if not SOURCE_CATALOG.exists():
        parser.error(f"missing compiled catalog: {SOURCE_CATALOG}")
    catalog = Catalog.load(SOURCE_CATALOG)
    rendered = render_stubs(catalog)

    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text(encoding="utf-8") != rendered:
            print(f"stale: {DESTINATION.relative_to(ROOT)}")
            return 1
        print(f"up to date: {DESTINATION.relative_to(ROOT)} ({len(catalog.known_object_ids)} OBJ classes)")
        return 0

    DESTINATION.write_text(rendered, encoding="utf-8")
    print(f"generated {DESTINATION.relative_to(ROOT)} ({len(catalog.known_object_ids)} OBJ classes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
