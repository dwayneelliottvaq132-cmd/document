import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
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

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
        release(self.db, 1, 3, "2000-01-01")
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

    def add_revision(self, connection):
        connection.execute(
            """INSERT INTO document_revisions
               (revision_id, document_id, revision_code, change_summary,
                content_uri, content_sha256, author_id)
               SELECT 2, document_id, 'B', 'Updated procedure',
                      'repository://B.pdf', content_sha256, author_id
               FROM document_revisions WHERE revision_id=1"""
        )

    def prepare_next_release(self, create=True):
        with self.connect() as connection:
            if create:
                self.add_revision(connection)
            connection.execute("UPDATE document_revisions SET status='IN_REVIEW' WHERE revision_id=2")
            connection.execute(
                """INSERT INTO revision_approvals
                   (revision_id, approval_role, approver_id, decision, decided_at)
                   VALUES (2, 'QUALITY', 2, 'APPROVED', '2000-01-01')"""
            )
            connection.execute(
                """UPDATE document_revisions SET status='APPROVED', approved_at='2000-01-01'
                   WHERE revision_id=2"""
            )

    def test_invalid_effective_dates_preserve_current_revision(self):
        release(self.db, 1, 3, '2000-01-01')
        self.prepare_next_release()
        for effective in ('2999-01-01', '2999-01-01T01:00:00+02:00',
                          'invalid', '2026-02-30'):
            with self.subTest(effective=effective):
                with self.assertRaises(ValueError):
                    release(self.db, 2, 3, effective)
                with self.connect() as connection:
                    self.assertEqual(connection.execute(
                        'SELECT status FROM document_revisions ORDER BY revision_id'
                    ).fetchall(), [('RELEASED',), ('APPROVED',)])
                    self.assertEqual(connection.execute(
                        'SELECT current_revision_id FROM documents'
                    ).fetchone()[0], 1)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM event_log').fetchone()[0], 1)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM release_authorizations').fetchone()[0], 0)

    def test_supersession_and_timezone_effective_date(self):
        release(self.db, 1, 3, '2000-01-01')
        self.prepare_next_release()
        release(self.db, 2, 3, '2000-01-02T01:00:00+02:00')
        with self.connect() as connection:
            self.assertEqual(connection.execute(
                'SELECT status FROM document_revisions ORDER BY revision_id'
            ).fetchall(), [('SUPERSEDED',), ('RELEASED',)])
            self.assertEqual(connection.execute('SELECT revision_id FROM v_current_documents').fetchone()[0], 2)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_reviewed_content_and_status_cannot_be_reset(self):
        with self.connect() as connection:
            self.add_revision(connection)
            # Draft content remains editable until review begins.
            connection.execute("UPDATE document_revisions SET content_uri='updated' WHERE revision_id=2")
            connection.execute("UPDATE document_revisions SET status='IN_REVIEW' WHERE revision_id=2")
            for revision_id in (1, 2):
                with self.subTest(revision_id=revision_id):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable'):
                        connection.execute(
                            "UPDATE document_revisions SET content_uri='changed' WHERE revision_id=?", (revision_id,)
                        )
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'lifecycle'):
                        connection.execute(
                            "UPDATE document_revisions SET status='DRAFT' WHERE revision_id=?", (revision_id,)
                        )

    def test_published_lifecycle_cannot_be_reopened(self):
        release(self.db, 1, 3, '2000-01-01')
        with self.connect() as connection:
            for status in ('RELEASED', 'SUPERSEDED', 'OBSOLETE'):
                connection.execute('UPDATE document_revisions SET status=? WHERE revision_id=1', (status,))
                for target in ('DRAFT', 'IN_REVIEW', 'APPROVED'):
                    with self.subTest(status=status, target=target):
                        with self.assertRaisesRegex(sqlite3.IntegrityError, 'lifecycle'):
                            connection.execute('UPDATE document_revisions SET status=? WHERE revision_id=1', (target,))
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable'):
                    connection.execute("UPDATE document_revisions SET content_uri='changed' WHERE revision_id=1")

    def test_published_revision_insert_is_blocked(self):
        with self.connect() as connection:
            for status in ('RELEASED', 'SUPERSEDED', 'OBSOLETE'):
                with self.subTest(status=status):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'release_revision'):
                        connection.execute(
                            """INSERT INTO document_revisions
                               (document_id, revision_code, status, change_summary, content_uri,
                                content_sha256, author_id, approved_at, released_at, released_by, effective_at)
                               SELECT document_id, 'B', ?, change_summary, content_uri,
                                      content_sha256, author_id, approved_at, '2000-01-01', 3, '2000-01-01'
                               FROM document_revisions WHERE revision_id=1""", (status,)
                        )

    def test_training_required_for_each_active_role_member(self):
        with self.connect() as connection:
            connection.execute('INSERT INTO user_roles(user_id, role_id) VALUES (1, 3)')
        with self.assertRaisesRegex(ValueError, 'every active affected user'):
            release(self.db, 1, 3, '2000-01-01')
        with self.connect() as connection:
            self.assertEqual(connection.execute('SELECT status FROM document_revisions').fetchone()[0], 'APPROVED')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM event_log').fetchone()[0], 0)
            connection.execute("INSERT INTO training_assignments(revision_id, user_id, due_at) VALUES (1, 1, '2000-01-01')")
        release(self.db, 1, 3, '2000-01-01')

    def test_inactive_role_member_does_not_require_assignment(self):
        with self.connect() as connection:
            connection.execute('INSERT INTO user_roles(user_id, role_id) VALUES (1, 3)')
            connection.execute('UPDATE users SET active=0 WHERE user_id=1')
        release(self.db, 1, 3, '2000-01-01')

    def test_copy_updates_reject_drafts_and_allow_recall(self):
        release(self.db, 1, 3, '2000-01-01')
        with self.connect() as connection:
            self.add_revision(connection)
            connection.execute(
                """INSERT INTO controlled_copies
                   (copy_number, revision_id, location, medium, issued_at, issued_by)
                   VALUES ('COPY-1', 1, 'Shop floor', 'PAPER', '2000-01-01', 3)"""
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'released revisions'):
                connection.execute('UPDATE controlled_copies SET revision_id=2')
        self.prepare_next_release(create=False)
        release(self.db, 2, 3, '2000-01-01')
        with self.connect() as connection:
            # Recall must work even though the old revision is now superseded.
            connection.execute("UPDATE controlled_copies SET status='RECALLED', recalled_at='2000-01-02'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'released revisions'):
                connection.execute("UPDATE controlled_copies SET status='ISSUED'")
            connection.execute("UPDATE controlled_copies SET revision_id=2, status='ISSUED'")
            self.assertEqual(connection.execute('SELECT revision_id FROM controlled_copies').fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
