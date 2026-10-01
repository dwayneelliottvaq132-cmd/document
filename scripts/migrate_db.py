#!/usr/bin/env python3
"""Back up and migrate an existing document-control database."""

import argparse
import datetime as dt
import re
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "sql" / "migrations"
MIGRATION_NAME = re.compile(r"^(\d{3})_.+\.sql$")


def available_migrations() -> Dict[int, Path]:
    migrations = {}
    for path in MIGRATIONS.glob("*.sql"):
        match = MIGRATION_NAME.match(path.name)
        if match:
            migrations[int(match.group(1))] = path
    return migrations


def schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_versions").fetchone()
    except sqlite3.OperationalError as exc:
        raise ValueError("database is not a document-control database") from exc
    if row is None or row[0] is None:
        raise ValueError("database has no recorded schema version")
    return int(row[0])


def default_backup_path(database: Path, version: int) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return database.with_name(f"{database.name}.pre-v{version}-{stamp}.bak")


def migrate(database: Path, backup: bool = True) -> Tuple[int, Optional[Path]]:
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")

    migrations = available_migrations()
    latest = max(migrations, default=1)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    backup_path = None
    try:
        current = schema_version(connection)
        if current > latest:
            raise ValueError(f"database schema version {current} is newer than supported version {latest}")
        pending = list(range(current + 1, latest + 1))
        missing = [version for version in pending if version not in migrations]
        if missing:
            raise RuntimeError(f"missing migration files for versions: {missing}")
        if not pending:
            return current, None

        if backup:
            backup_path = default_backup_path(database, current)
            backup_connection = sqlite3.connect(backup_path)
            try:
                connection.backup(backup_connection)
            finally:
                backup_connection.close()

        for version in pending:
            connection.executescript(migrations[version].read_text(encoding="utf-8"))
            if schema_version(connection) != version:
                raise RuntimeError(f"migration {version} did not record its schema version")

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"post-migration validation failed: integrity={integrity}, foreign_keys={foreign_keys}"
            )
        return latest, backup_path
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--no-backup", action="store_true", help="skip the pre-migration backup")
    args = parser.parse_args()
    version, backup_path = migrate(args.database, backup=not args.no_backup)
    if backup_path:
        print(f"Migrated {args.database} to schema version {version}; backup: {backup_path}")
    else:
        print(f"Database already uses schema version {version}; no changes made")


if __name__ == "__main__":
    main()
