#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "compiled" / "catalog.normalized.json"
DEST = ROOT / "gmdtool" / "data" / "catalog.normalized.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync the compiled catalog into the Python package")
    parser.add_argument("--check", action="store_true", help="fail instead of writing when the packaged copy is stale")
    args = parser.parse_args(argv)

    if not SOURCE.exists():
        parser.error(f"missing compiled catalog: {SOURCE}")

    source_bytes = SOURCE.read_bytes()
    if args.check:
        if not DEST.exists() or DEST.read_bytes() != source_bytes:
            print(f"stale: {DEST.relative_to(ROOT)} does not match {SOURCE.relative_to(ROOT)}")
            return 1
        print(f"up to date: {DEST.relative_to(ROOT)}")
        return 0

    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, DEST)
    print(f"synced {SOURCE.relative_to(ROOT)} -> {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
