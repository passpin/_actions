from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .catalog import default_catalog
from .io import GMD
from .level import GDLevel


def _load_json(path: str | Path) -> Any:
    # JSON numbers with a decimal point become strings so a patch never loses
    # decimal spelling through Python float before GDReal sees the value.
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle, parse_float=str)


def _dump(value: Any, *, compact: bool = False) -> None:
    if compact:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _selector_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", type=int, dest="object_id", help="Object ID")
    parser.add_argument("--where", action="append", default=[], metavar="NAME=VALUE",
                        help="Semantic property equality; repeatable")


def _coerce_cli_value(text: str) -> Any:
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null" or lowered == "none":
        return None
    try:
        return int(text)
    except ValueError:
        return text


def _where(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--where expects NAME=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError("--where property name cannot be empty")
        result[key] = _coerce_cli_value(value)
    return result


def cmd_inspect(args: argparse.Namespace) -> int:
    level = GMD.load(args.file)
    payload = level.summary()
    coverage = default_catalog().coverage()
    payload["catalog"] = {
        "total_known_object_ids": coverage["total_known_object_ids"],
        "explicit_schemas": coverage["explicit_schemas"],
        "raw_only_count": coverage["raw_only_count"],
    }
    _dump(payload, compact=args.compact)
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    level = GMD.load(args.file)
    result = level.explain(args.object_id, limit=args.limit, **_where(args.where))
    _dump(result, compact=args.compact)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    level = GMD.load(args.file)
    report = level.validate(check_references=args.references)
    if args.json:
        _dump(report.to_dict(), compact=args.compact)
    else:
        print(report.to_text(limit=args.limit))
    return 0 if report.ok else 2


def cmd_raw_export(args: argparse.Namespace) -> int:
    level = GMD.load(args.file)
    payload = level.to_raw_json()
    text = json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2, default=str)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def cmd_raw_import(args: argparse.Namespace) -> int:
    payload = _load_json(args.raw_json)
    level = GDLevel.from_raw_json(payload)
    GMD.save(level, args.output, validate=args.validate)
    return 0


def cmd_patch(args: argparse.Namespace) -> int:
    level = GMD.load(args.file)
    patch = _load_json(args.patch)
    result = level.apply_patch(patch)
    if args.validate:
        report = level.validate(check_references=args.references)
        result["validation"] = report.to_dict()
        report.raise_for_errors()
    GMD.save(level, args.output)
    _dump(result, compact=args.compact)
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    catalog = default_catalog()
    oid = catalog.resolve_object_id(args.object)
    schema = catalog.get_object(oid)
    properties = catalog.properties_for(oid)
    payload = {
        "object_id": oid,
        "known": oid in catalog.known_object_ids,
        "explicit_schema": schema is not None,
        "name": schema.name if schema else None,
        "base": schema.base if schema else None,
        "confidence": schema.confidence if schema else "unknown",
        "complete_schema": schema.complete_schema if schema else False,
        "aliases": list(schema.aliases) if schema else [],
        "properties": [
            {
                "key": p.key,
                "name": p.name,
                "aliases": list(p.aliases),
                "type": p.type,
                "wire_type": p.wire_type,
                "semantic": p.semantic,
                "confidence": p.confidence,
                "sources": list(p.sources),
            }
            for p in properties
        ],
    }
    _dump(payload, compact=args.compact)
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    catalog = default_catalog()
    errors = catalog.validate() if args.validate else []
    payload = catalog.coverage()
    if args.validate:
        payload["valid"] = not errors
        payload["errors"] = errors
    _dump(payload, compact=args.compact)
    return 0 if not errors else 2


def cmd_geode(args: argparse.Namespace) -> int:
    """Use the optional running-GD bridge; ordinary file operations remain offline."""
    from .geode_bridge import GeodeBridge

    bridge = GeodeBridge.from_session_file(args.session, timeout=args.timeout)
    operation = args.runtime_command
    if operation == "ping":
        result = bridge.ping()
    elif operation == "status":
        result = bridge.status()
    elif operation == "bridge-health":
        result = bridge.bridge_health()
    elif operation == "items":
        result = {"values": bridge.items(*args.item_ids)}
    elif operation == "snapshot":
        result = bridge.snapshot(*args.item_ids)
    elif operation == "reset":
        result = bridge.reset_level()
    elif operation == "input":
        result = bridge.input(down=args.down, button=args.button, player=args.player)
    elif operation == "queue-status":
        result = bridge.input_queue_status()
    elif operation == "clear-inputs":
        result = bridge.clear_inputs()
    elif operation == "schedule":
        result = bridge.schedule_inputs(_load_json(args.events_json))
    else:
        raise ValueError(f"unknown Geode operation: {operation}")
    _dump(result, compact=args.compact)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmdtool",
        description="AI-first, data-driven Geometry Dash .gmd toolkit",
    )
    parser.add_argument("--version", action="version", version="gmdtool 0.4.0.dev0")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="Show level summary")
    p.add_argument("file")
    p.add_argument("--compact", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("explain", help="Explain selected objects semantically")
    p.add_argument("file")
    _selector_args(p)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--compact", action="store_true")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("validate", help="Validate raw/semantic object data")
    p.add_argument("file")
    p.add_argument("--references", action="store_true", help="Check group reference membership")
    p.add_argument("--json", action="store_true", help="Emit structured JSON report")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--compact", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("raw-export", help="Export lossless structured raw-level JSON")
    p.add_argument("file")
    p.add_argument("-o", "--output")
    p.add_argument("--compact", action="store_true")
    p.set_defaults(func=cmd_raw_export)

    p = sub.add_parser("raw-import", help="Create a .gmd from raw-level JSON")
    p.add_argument("raw_json")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--validate", action="store_true")
    p.set_defaults(func=cmd_raw_import)

    p = sub.add_parser("patch", help="Apply an atomic JSON patch")
    p.add_argument("file")
    p.add_argument("patch")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--validate", action="store_true")
    p.add_argument("--references", action="store_true")
    p.add_argument("--compact", action="store_true")
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("schema", help="Show catalog schema for one Object ID or alias")
    p.add_argument("object")
    p.add_argument("--compact", action="store_true")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("catalog", help="Show catalog coverage / validate catalog")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--compact", action="store_true")
    p.set_defaults(func=cmd_catalog)

    geode = sub.add_parser("geode", help="Talk to an optional running Geometry Dash / Geode bridge")
    geode.add_argument("--session", required=True, metavar="FILE",
                       help="bridge-session.json path shown in the Geode log")
    geode.add_argument("--timeout", type=float, default=5.0,
                       help="TCP request timeout in seconds (default 5)")
    geode.add_argument("--compact", action="store_true")
    operations = geode.add_subparsers(dest="runtime_command", required=True)
    for name in ("queue-status", "clear-inputs"):
        operations.add_parser(name).set_defaults(func=cmd_geode)
    operation = operations.add_parser("schedule", help="Queue transitions by postUpdate callback index")
    operation.add_argument("events_json", help="JSON file with list of input events")
    operation.set_defaults(func=cmd_geode)
    for name in ("ping", "status", "bridge-health", "reset"):
        operations.add_parser(name).set_defaults(func=cmd_geode)
    for name in ("items", "snapshot"):
        operation = operations.add_parser(name)
        operation.add_argument("item_ids", type=int, nargs="+" if name == "items" else "*",
                               metavar="ID", help="Item ID (1..9999, up to 128)")
        operation.set_defaults(func=cmd_geode)
    operation = operations.add_parser("input", help="Immediate input transition (not frame-scheduled)")
    state = operation.add_mutually_exclusive_group(required=True)
    state.add_argument("--down", action="store_const", const=True, dest="down", help="press button")
    state.add_argument("--up", action="store_const", const=False, dest="down", help="release button")
    operation.add_argument("--button", type=int, choices=(1, 2, 3), default=1)
    operation.add_argument("--player", type=int, choices=(1, 2), default=1)
    operation.set_defaults(func=cmd_geode)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(f"gmdtool: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"gmdtool: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
