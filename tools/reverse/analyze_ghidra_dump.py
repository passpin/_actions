from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CASE_RE = re.compile(r"\bcase\s+(\d+)\s*:")
CLASS_CALL_RE = re.compile(r"\b([A-Za-z_]\w*(?:GameObject|TriggerObject))::(?:create|createWithFrame|createWithKey)\b")


def extract_create_with_key_candidates(text: str) -> dict[int, list[str]]:
    lines = text.splitlines()
    current_cases: list[int] = []
    result: dict[int, list[str]] = {}
    for line in lines:
        m = CASE_RE.search(line)
        if m:
            current_cases.append(int(m.group(1)))
        calls = CLASS_CALL_RE.findall(line)
        if calls and current_cases:
            for obj_id in current_cases:
                result.setdefault(obj_id, [])
                for cls in calls:
                    if cls not in result[obj_id]:
                        result[obj_id].append(cls)
            current_cases = []
        if "break;" in line or "return" in line:
            if not calls:
                current_cases = []
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze DumpGDPropertyFunctions.java JSON output")
    ap.add_argument("dump", type=Path)
    ap.add_argument("--out", type=Path, default=Path("ghidra_analysis.json"))
    ns = ap.parse_args()
    data = json.loads(ns.dump.read_text(encoding="utf-8"))
    create_map: dict[int, list[str]] = {}
    functions = data.get("functions", [])
    for fn in functions:
        if fn.get("name", "").endswith("GameObject::createWithKey") or fn.get("short_name") == "createWithKey":
            create_map.update(extract_create_with_key_candidates(fn.get("decompiled", "")))
    result = {
        "format": "gmdtool-ghidra-analysis-v1",
        "function_count": len(functions),
        "object_id_class_candidates": {str(k): v for k, v in sorted(create_map.items())},
    }
    ns.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"functions={len(functions)} object_id_candidates={len(create_map)} -> {ns.out}")


if __name__ == "__main__":
    main()
