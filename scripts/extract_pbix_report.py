#!/usr/bin/env python3
"""
Extract the PBIR Report definition from a .pbix file.

Usage:
    python scripts/extract_pbix_report.py "path\Report.pbix" -o "path\Report.Report"

The output folder contains:
    <output>\
        definition\
            report.json
            version.json
            pages\
            ...

Only files under Report/definition/ are extracted because the
Tableau-vs-Power BI structural validator only needs the PBIR definition.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile, BadZipFile


def extract_report_definition(pbix_path: Path, output_dir: Path) -> int:
    if not pbix_path.is_file():
        raise FileNotFoundError(f"PBIX file not found: {pbix_path}")

    if pbix_path.suffix.lower() != ".pbix":
        raise ValueError(f"Expected a .pbix file, got: {pbix_path.name}")

    report_prefix = "Report/definition/"
    output_dir = output_dir.resolve()

    try:
        with ZipFile(pbix_path, "r") as zf:
            members = [
                name for name in zf.namelist()
                if name.startswith(report_prefix)
                and not name.endswith("/")
            ]

            if not members:
                raise RuntimeError(
                    "No Report/definition files were found inside the PBIX. "
                    "This file may not contain a PBIR definition."
                )

            output_dir.mkdir(parents=True, exist_ok=True)

            extracted = 0
            for member in members:
                relative = Path(member[len(report_prefix):])

                # Prevent zip path traversal.
                destination = (output_dir / "definition" / relative).resolve()
                definition_root = (output_dir / "definition").resolve()

                if destination != definition_root and definition_root not in destination.parents:
                    raise RuntimeError(f"Unsafe path in PBIX: {member}")

                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, destination.open("wb") as target:
                    target.write(source.read())

                extracted += 1

    except BadZipFile as exc:
        raise RuntimeError(f"{pbix_path} is not a valid ZIP/PBIX file.") from exc

    print(f"Extracted {extracted} PBIR definition files.")
    print(f"PBIX:    {pbix_path}")
    print(f"Output:  {output_dir}")
    print("")
    print("PBIR report definition is ready for validation.")
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Report/definition from a Power BI .pbix file."
    )
    parser.add_argument("pbix", help="Path to the .pbix file")
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .Report directory",
    )
    args = parser.parse_args()

    extract_report_definition(
        Path(args.pbix),
        Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
