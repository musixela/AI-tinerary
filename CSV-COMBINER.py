#!/usr/bin/env python3
"""
Read every CSV under the Outputs directory (produced by the contract
processor) and concatenate them into a single file named
`master-output.csv` in the same directory.

The script:
  * looks for `*.csv` files in Outputs/
  * ignores any file whose name starts with "master" to avoid self‑inclusion
    if you re‑run the combiner multiple times
  * assumes every input file has the same header row; the header is
    written once at the top of the master file
  * preserves the order returned by sorted(glob).  You can change this
    ordering if you need chronological sorting, etc.

Usage:
    python CSV-COMBINER.py

(This is intentionally standalone and lightweight; no external
dependencies beyond the standard library.)
"""

import csv
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT_DIR / "Outputs"
MASTER_CSV = OUTPUTS_DIR / "master-output.csv"


def combine_csvs():
    if not OUTPUTS_DIR.exists():
        print(f"Outputs directory not found: {OUTPUTS_DIR}")
        return

    csv_paths = sorted(OUTPUTS_DIR.glob("*.csv"))
    if not csv_paths:
        print(f"No CSV files found in {OUTPUTS_DIR}")
        return

    with open(MASTER_CSV, "w", newline="", encoding="utf-8") as out_f:
        writer = None
        for path in csv_paths:
            # skip the master file itself if present
            if path.name.lower().startswith("master"):
                continue

            with open(path, newline="", encoding="utf-8") as in_f:
                reader = csv.reader(in_f)
                try:
                    header = next(reader)
                except StopIteration:
                    # empty file
                    continue

                if writer is None:
                    writer = csv.writer(out_f)
                    writer.writerow(header)
                # assume same header; otherwise this will duplicate or
                # misalign but that's probably fine for now
                for row in reader:
                    writer.writerow(row)
    print(f"Combined {len(csv_paths)} file(s) into {MASTER_CSV}")


if __name__ == "__main__":
    combine_csvs()
