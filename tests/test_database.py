import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.init_db import initialize
from scripts.release_revision import release


ROOT = Path(__file__).resolve().parents[1]


class DocumentControlTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "control.db"
        initialize(self.db)
        connection = sqlite3.connect(self.db)
        connection.executescript((ROOT / "examples" / "sample_data.sql").read_text())
        connection.close()

    def tearDown(self):
        self.tempdir.cleanup()

    def connect(self):
        connection = sqlite3.connect(self.db)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def test_schema_and_sample_load(self):
        with self.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)

    def test_author_cannot_approve_own_revision(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot approve"):
            with self.connect() as connection:
                connection.execute(
                    """INSERT INTO revision_approvals
                       (revision_id, approval_role, approver_id) VALUES (1, 'ENGINEERING', 1)"""
                )

    def test_direct_release_is_blocked(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "release_revision"):
            with self.connect() as connection:
                connection.execute(
                    """UPDATE document_revisions SET status='RELEASED',
                       released_at='2026-09-30T13:00:00Z', released_by=3,
                       effective_at='2026-10-01' WHERE revision_id=1"""
                )

    def test_controlled_release_and_immutable_content(self):
        release(self.db, 1, 3, "2026-10-01")
        with self.connect() as connection:
            status = connection.execute(
                "SELECT status FROM document_revisions WHERE revision_id=1"
            ).fetchone()[0]
            current = connection.execute(
                "SELECT current_revision_id FROM documents WHERE document_id=1"
            ).fetchone()[0]
            self.assertEqual((status, current), ("RELEASED", 1))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM event_log").fetchone()[0], 1)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE document_revisions SET content_uri='changed' WHERE revision_id=1"
                )

    def test_unreleased_revision_cannot_be_distributed(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "released revisions"):
            with self.connect() as connection:
                connection.execute(
                    """INSERT INTO controlled_copies
                       (copy_number, revision_id, location, medium, issued_at, issued_by)
                       VALUES ('COPY-1', 1, 'Shop floor', 'PAPER', '2026-09-30', 3)"""
                )


if __name__ == "__main__":
    unittest.main()
