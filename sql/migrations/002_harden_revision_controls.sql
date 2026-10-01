BEGIN IMMEDIATE;

DROP TRIGGER IF EXISTS protect_released_revision_content;
DROP TRIGGER IF EXISTS enforce_revision_lifecycle;
DROP TRIGGER IF EXISTS prevent_insert_released_revision;
DROP TRIGGER IF EXISTS prevent_copy_update_to_unreleased_revision;

CREATE TRIGGER protect_released_revision_content
BEFORE UPDATE OF document_id, revision_code, change_summary, content_uri, content_sha256, author_id
ON document_revisions
WHEN OLD.status IN ('IN_REVIEW', 'APPROVED', 'RELEASED', 'SUPERSEDED', 'OBSOLETE')
     OR EXISTS (SELECT 1 FROM revision_approvals
                WHERE revision_id = OLD.revision_id AND decision = 'APPROVED')
BEGIN
    SELECT RAISE(ABORT, 'reviewed revision content is immutable; create a new revision');
END;

CREATE TRIGGER enforce_revision_lifecycle
BEFORE UPDATE OF status ON document_revisions
WHEN NEW.status <> OLD.status AND NOT (
    (OLD.status = 'DRAFT' AND NEW.status IN ('IN_REVIEW', 'OBSOLETE')) OR
    (OLD.status = 'IN_REVIEW' AND NEW.status IN ('APPROVED', 'OBSOLETE')) OR
    (OLD.status = 'APPROVED' AND NEW.status IN ('RELEASED', 'OBSOLETE')) OR
    (OLD.status = 'RELEASED' AND NEW.status IN ('SUPERSEDED', 'OBSOLETE')) OR
    (OLD.status = 'SUPERSEDED' AND NEW.status = 'OBSOLETE')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid revision lifecycle transition; create a new revision');
END;

CREATE TRIGGER prevent_insert_released_revision
BEFORE INSERT ON document_revisions
WHEN NEW.status IN ('RELEASED', 'SUPERSEDED') OR NEW.released_at IS NOT NULL
     OR NEW.released_by IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'use scripts/release_revision.py to release revisions');
END;

CREATE TRIGGER prevent_copy_update_to_unreleased_revision
BEFORE UPDATE OF revision_id, status ON controlled_copies
WHEN (NEW.revision_id <> OLD.revision_id OR
      (OLD.status IN ('RECALLED', 'DESTROYED') AND NEW.status IN ('ISSUED', 'ACKNOWLEDGED')))
     AND (SELECT status FROM document_revisions WHERE revision_id = NEW.revision_id) IS NOT 'RELEASED'
BEGIN
    SELECT RAISE(ABORT, 'controlled copies may only use released revisions');
END;

INSERT INTO schema_versions(version, description)
VALUES (2, 'Harden revision lifecycle, reviewed content, and controlled-copy updates');

COMMIT;
