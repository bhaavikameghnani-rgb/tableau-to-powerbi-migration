#!/usr/bin/env python3
"""One-command Tableau -> Power BI visual validation.

Usage:
    python scripts/validate_tableau_powerbi.py workbook.twbx ReportDir -o validation.json

The Tableau workbook is first parsed with the repository's existing parse_tableau.py, preserving
its migration-spec contract. The new PBIR extractor then reads the generated Power BI report and
the comparator validates the two normalized representations.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from compare_tableau_powerbi import validate, render


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tableau", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--migration-spec", type=Path, help="Reuse an existing migration-spec.json")
    parser.add_argument("--keep-spec", action="store_true", help="Keep the generated migration-spec next to the output")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    if args.migration_spec:
        spec_path = args.migration_spec.resolve()
    else:
        if not args.tableau.exists():
            parser.error(f"Tableau file not found: {args.tableau}")
        if args.keep_spec:
            spec_path = args.output.with_name("migration-spec.json")
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            temp_context = None
        else:
            temp_context = tempfile.TemporaryDirectory(prefix="tableau-pbi-validation-")
            spec_path = Path(temp_context.name) / "migration-spec.json"
        cmd = [sys.executable, str(Path(__file__).with_name("parse_tableau.py")), str(args.tableau), "-o", str(spec_path)]
        completed = subprocess.run(cmd, text=True)
        if completed.returncode != 0:
            return completed.returncode

    result = validate(spec_path, args.report.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(render(result))
    if result["status"] == "FAIL" and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
