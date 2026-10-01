#!/usr/bin/env python3
"""Release an approved document revision using enforced workflow checks."""

import argparse
import datetime as dt
import sqlite3
from pathlib import Path


def release(database: Path, revision_id: int, releaser_id: int, effective_at: str) -> None:
    # Date-only and naive date/time inputs are interpreted in UTC.
    try:
        effective = dt.datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("effective date must be a valid ISO 8601 date/time") from exc
    if effective.tzinfo is None:
        effective = effective.replace(tzinfo=dt.timezone.utc)
    if effective > dt.datetime.now(dt.timezone.utc):
        raise ValueError("future effective dates are not supported; release when effective")
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT document_id, status FROM document_revisions WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"revision {revision_id} does not exist")
        document_id, status = row
        if status != "APPROVED":
            raise ValueError(f"revision must be APPROVED, not {status}")

        pending = connection.execute(
            "SELECT COUNT(*) FROM revision_approvals WHERE revision_id = ? AND decision <> 'APPROVED'",
            (revision_id,),
        ).fetchone()[0]
        approvals = connection.execute(
            "SELECT COUNT(*) FROM revision_approvals WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()[0]
        if approvals == 0 or pending:
            raise ValueError("all required approvals must be recorded and approved")

        required_roles = connection.execute(
            "SELECT COUNT(*) FROM revision_training_requirements WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()[0]
        if required_roles:
            assignments = connection.execute(
                """SELECT COUNT(*) FROM revision_training_requirements rr
                   JOIN user_roles ur ON ur.role_id = rr.role_id
                   JOIN users u ON u.user_id = ur.user_id AND u.active = 1
                   WHERE rr.revision_id = ? AND NOT EXISTS (
                     SELECT 1 FROM training_assignments ta
                     WHERE ta.user_id = ur.user_id AND ta.revision_id = rr.revision_id
                   )""",
                (revision_id,),
            ).fetchone()[0]
            if assignments:
                raise ValueError("training assignments are required for every active affected user")

        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        connection.execute(
            "INSERT INTO release_authorizations VALUES (?, ?, ?)",
            (revision_id, releaser_id, now),
        )
        connection.execute(
            """UPDATE document_revisions SET status = 'SUPERSEDED'
               WHERE document_id = ? AND status = 'RELEASED'""",
            (document_id,),
        )
        connection.execute(
            """UPDATE document_revisions
               SET status = 'RELEASED', released_at = ?, released_by = ?, effective_at = ?
               WHERE revision_id = ?""",
            (now, releaser_id, effective_at, revision_id),
        )
        connection.execute(
            "UPDATE documents SET current_revision_id = ? WHERE document_id = ?",
            (revision_id, document_id),
        )
        connection.execute(
            """INSERT INTO event_log(entity_type, entity_id, action, actor_id, details)
               VALUES ('REVISION', ?, 'RELEASED', ?, ?)""",
            (revision_id, releaser_id, f"effective_at={effective_at}"),
        )
        connection.execute(
            "DELETE FROM release_authorizations WHERE revision_id = ?", (revision_id,)
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("revision_id", type=int)
    parser.add_argument("releaser_id", type=int)
    parser.add_argument("--effective", required=True,
                        help="ISO 8601 date/time, not in the future (naive values use UTC)")
    args = parser.parse_args()
    release(args.database, args.revision_id, args.releaser_id, args.effective)
    print(f"Released revision {args.revision_id}")


if __name__ == "__main__":
    main()
