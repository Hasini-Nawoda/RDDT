#!/usr/bin/env python3
"""CLI for compiling the corrected normalized V4 workbook."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from v4_build_tools.config_compile import (  # noqa: E402
    DEFAULT_WORKBOOK_PATH,
    compile_workbook,
)
from v4_build_tools.config_validation import ConfigValidationError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK_PATH)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--allow-errors", action="store_true",
                        help="write artifacts and return success even when validation errors exist")
    args = parser.parse_args(argv)
    try:
        bundle = compile_workbook(args.workbook, args.output_dir, fail_on_error=not args.allow_errors)
    except ConfigValidationError as exc:
        report = exc.report.to_dict() if exc.report else {"error": str(exc)}
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({
        "output_dir": str(bundle.output_dir),
        "workbook_sha256": bundle.manifest["workbook_sha256"],
        "compiled_config_sha256": bundle.manifest["compiled_config_sha256"],
        "valid": bundle.validation_report.valid,
        "error_count": len(bundle.validation_report.errors),
        "warning_count": len(bundle.validation_report.warnings),
    }, indent=2, ensure_ascii=False))
    return 0 if bundle.validation_report.valid or args.allow_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
