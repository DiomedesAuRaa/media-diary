#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"

EXPORTS = {
    "movies": DATA_DIR / "movies.csv",
    "books": DATA_DIR / "books.csv",
    "tv": DATA_DIR / "tv.csv",
}


def export_csv(name: str, csv_path: Path) -> int:
    if not csv_path.exists():
        return 0

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    output = DOCS_DIR / f"{name}.json"
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"entries": rows}, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {output.relative_to(REPO_ROOT)}")
    return len(rows)


def main() -> int:
    total = 0
    for name, path in EXPORTS.items():
        total += export_csv(name, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
