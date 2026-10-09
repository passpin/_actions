from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

CLASS_RE = re.compile(r"^\s*class\s+(?P<name>[A-Za-z_][\w:]*)\s*(?::\s*(?P<bases>[^\{]+))?\s*\{")
PROP_RE = re.compile(r"\bproperty\s+(\d+)\b", re.IGNORECASE)
WIN_ADDR_RE = re.compile(r"\bwin\s+(0x[0-9a-fA-F]+|inline)\b")
METHOD_NAME_RE = re.compile(r"([~A-Za-z_]\w*)\s*\(")
FIELD_RE = re.compile(r"^\s*(?P<decl>[^(){}=]+?)\s+(?P<name>m_[A-Za-z_]\w*(?:\[[^\]]+\])?)\s*;\s*(?://.*)?$")


def _strip_base(base: str) -> str:
    base = base.strip()
    for prefix in ("public ", "protected ", "private "):
        if base.startswith(prefix):
            base = base[len(prefix):]
    return base.strip()


def parse_broma(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    classes: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        m = CLASS_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group("name")
        bases = [_strip_base(x) for x in (m.group("bases") or "").split(",") if x.strip()]
        start = i + 1
        depth = lines[i].count("{") - lines[i].count("}")
        i += 1
        body: list[tuple[int, str]] = []
        while i < len(lines) and depth > 0:
            line = lines[i]
            depth += line.count("{") - line.count("}")
            if depth > 0:
                body.append((i + 1, line))
            i += 1

        pending_props: list[int] = []
        props: list[dict[str, Any]] = []
        methods: dict[str, list[dict[str, Any]]] = {}
        for lineno, line in body:
            comment_props = [int(x) for x in PROP_RE.findall(line)]
            if line.lstrip().startswith("//"):
                if comment_props:
                    pending_props = comment_props
                continue

            fm = FIELD_RE.match(line)
            if fm:
                inline_props = comment_props
                keys = inline_props or pending_props
                if keys:
                    decl = fm.group("decl").strip()
                    field_name = fm.group("name")
                    for key in keys:
                        props.append({
                            "key": key,
                            "field": field_name,
                            "cpp_type": decl,
                            "declaration": line.strip(),
                            "line": lineno,
                        })
                pending_props = []
                continue

            if "(" in line and ("=" in line or line.rstrip().endswith(";")):
                mm = METHOD_NAME_RE.search(line)
                if mm:
                    method_name = mm.group(1)
                    addr_m = WIN_ADDR_RE.search(line)
                    win = addr_m.group(1) if addr_m else None
                    methods.setdefault(method_name, []).append({
                        "line": lineno,
                        "signature": line.strip(),
                        "win": win,
                    })
                pending_props = []
                continue

            if line.strip() and not line.lstrip().startswith("//"):
                pending_props = []

        classes[name] = {
            "bases": bases,
            "start_line": start,
            "properties": sorted(props, key=lambda x: (x["key"], x["line"])),
            "methods": methods,
        }

    by_key: dict[str, list[dict[str, Any]]] = {}
    for cls_name, cls in classes.items():
        for prop in cls["properties"]:
            by_key.setdefault(str(prop["key"]), []).append({"class": cls_name, **prop})

    return {
        "format": "gmdtool-broma-index-v1",
        "class_count": len(classes),
        "property_annotation_count": sum(len(c["properties"]) for c in classes.values()),
        "classes": classes,
        "properties_by_key": by_key,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract property comments and Windows function RVAs from GeometryDash.bro")
    ap.add_argument("broma", type=Path)
    ap.add_argument("--out", type=Path, default=Path("broma_index.json"))
    ns = ap.parse_args()
    result = parse_broma(ns.broma.read_text(encoding="utf-8", errors="replace"))
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"classes={result['class_count']} property_annotations={result['property_annotation_count']} -> {ns.out}")


if __name__ == "__main__":
    main()
