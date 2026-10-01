#!/usr/bin/env python3
"""Initialize the document-control SQLite database."""

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def initialize(path: Path, force: bool = False) -> None:
    if path.exists():
        if not force:
            raise FileExistsError(f"{path} already exists (use --force to replace it)")
        path.unlink()

    path.parent.mkdir(parents=True, exist_ok=True)
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    connection = sqlite3.connect(path)
    try:
        connection.executescript(schema)
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"database integrity check failed: {result}")
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="path of the database to create")
    parser.add_argument("--force", action="store_true", help="replace an existing database")
    args = parser.parse_args()
    initialize(args.database, args.force)
    print(f"Initialized document-control database at {args.database}")


if __name__ == "__main__":
    main()
