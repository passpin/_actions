from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def cpp_kind(cpp_type: str) -> str:
    t = cpp_type.replace("const", "").strip()
    if "<" in t or "[" in t or "*" in t:
        return "unknown"
    if "bool" in t:
        return "bool"
    if "float" in t or "double" in t:
        return "real"
    if "gd::string" in t or "std::string" in t:
        return "string"
    if "CCPoint" in t:
        return "point"
    if "HSV" in t:
        return "hsv"
    if "int" in t or "short" in t or "enum" in t or (t and t[0].isupper() and "*" not in t):
        return "int_or_enum"
    return "unknown"


def catalog_kind(prop_type: str) -> str:
    if prop_type in {"group_id", "item_id", "control_id", "int", "enum"}:
        return "int_or_enum"
    if prop_type == "real":
        return "real"
    if prop_type == "bool":
        return "bool"
    if prop_type == "text":
        return "string"
    return prop_type


def compatible(broma: str, catalog: str) -> bool:
    if broma == "unknown" or broma == "point" or broma == "hsv":
        return True
    if broma == "string" and catalog in {"string", "raw", "particle", "weighted_groups", "sequence", "remap_list", "groups"}:
        return True
    return broma == catalog


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare Broma property field types with gmdtool's normalized catalog")
    ap.add_argument("broma_index", type=Path)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("--out", type=Path, default=Path("broma_catalog_report.json"))
    ns = ap.parse_args()

    broma = json.loads(ns.broma_index.read_text(encoding="utf-8"))
    catalog = json.loads(ns.catalog.read_text(encoding="utf-8"))

    catalog_by_key: dict[int, list[dict[str, Any]]] = {}
    for obj in catalog.get("objects", []):
        for p in obj.get("properties", []):
            catalog_by_key.setdefault(int(p["key"]), []).append({
                "object_id": obj["id"], "object_name": obj["name"], "name": p["name"], "type": p["type"]
            })

    conflicts: list[dict[str, Any]] = []
    broma_keys: dict[int, list[dict[str, Any]]] = {}
    for cls_name, cls in broma["classes"].items():
        for p in cls["properties"]:
            key = int(p["key"])
            bk = cpp_kind(p["cpp_type"])
            row = {"class": cls_name, "field": p["field"], "cpp_type": p["cpp_type"], "broma_kind": bk, "line": p["line"]}
            broma_keys.setdefault(key, []).append(row)
            for cp in catalog_by_key.get(key, []):
                ck = catalog_kind(cp["type"])
                if not compatible(bk, ck):
                    conflicts.append({"key": key, "broma": row, "catalog": {**cp, "catalog_kind": ck}})

    report = {
        "format": "gmdtool-broma-catalog-report-v1",
        "broma_property_keys": len(broma_keys),
        "catalog_property_keys": len(catalog_by_key),
        "type_conflict_count": len(conflicts),
        "type_conflicts": conflicts,
        "broma_keys": {str(k): v for k, v in sorted(broma_keys.items())},
    }
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"broma_keys={len(broma_keys)} conflicts={len(conflicts)} -> {ns.out}")


if __name__ == "__main__":
    main()
