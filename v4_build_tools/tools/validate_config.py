#!/usr/bin/env python3
"""Validate an emitted V4 compiled configuration bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from v4.config_loader import ConfigLoadError, load_compiled_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, default=None)
    parser.add_argument("--no-hash-check", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_compiled_config(args.bundle_dir, verify_hash=not args.no_hash_check)
    except ConfigLoadError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "valid": True,
        "phenotype": config.phenotype,
        "workbook_sha256": config.workbook_hash,
        "compiled_config_sha256": config.compiled_config_hash,
        "tables": {name: len(rows) for name, rows in sorted(config.tables.items())},
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
