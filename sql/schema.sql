PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    description TEXT NOT NULL
);

CREATE TABLE roles (
    role_id INTEGER PRIMARY KEY,
    role_name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    employee_number TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE user_roles (
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    role_id INTEGER NOT NULL REFERENCES roles(role_id),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    customer_code TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE programs (
    program_id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(customer_id),
    program_code TEXT NOT NULL UNIQUE,
    program_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE processes (
    process_id INTEGER PRIMARY KEY,
    process_code TEXT NOT NULL UNIQUE,
    process_name TEXT NOT NULL,
    nadcap_commodity TEXT,
    process_owner_id INTEGER REFERENCES users(user_id)
);

CREATE TABLE document_types (
    document_type_id INTEGER PRIMARY KEY,
    type_code TEXT NOT NULL UNIQUE,
    type_name TEXT NOT NULL,
    is_external INTEGER NOT NULL DEFAULT 0 CHECK (is_external IN (0, 1)),
    default_review_months INTEGER CHECK (default_review_months > 0),
    default_retention_years INTEGER NOT NULL CHECK (default_retention_years > 0)
);

CREATE TABLE documents (
    document_id INTEGER PRIMARY KEY,
    document_number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    document_type_id INTEGER NOT NULL REFERENCES document_types(document_type_id),
    owner_id INTEGER NOT NULL REFERENCES users(user_id),
    process_id INTEGER REFERENCES processes(process_id),
    customer_id INTEGER REFERENCES customers(customer_id),
    program_id INTEGER REFERENCES programs(program_id),
    confidentiality TEXT NOT NULL DEFAULT 'INTERNAL'
        CHECK (confidentiality IN ('PUBLIC', 'INTERNAL', 'CUSTOMER', 'EXPORT_CONTROLLED')),
    retention_years INTEGER NOT NULL CHECK (retention_years > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    current_revision_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by INTEGER NOT NULL REFERENCES users(user_id)
);

CREATE TABLE document_revisions (
    revision_id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(document_id),
    revision_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'RELEASED', 'SUPERSEDED', 'OBSOLETE')),
    change_summary TEXT NOT NULL,
    content_uri TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND
        content_sha256 NOT GLOB '*[^0-9A-Fa-f]*'
    ),
    author_id INTEGER NOT NULL REFERENCES users(user_id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    approved_at TEXT,
    released_at TEXT,
    released_by INTEGER REFERENCES users(user_id),
    effective_at TEXT,
    next_review_date TEXT,
    external_issue_date TEXT,
    external_verified_at TEXT,
    external_verified_by INTEGER REFERENCES users(user_id),
    supersedes_revision_id INTEGER REFERENCES document_revisions(revision_id),
    UNIQUE (document_id, revision_code),
    CHECK ((status NOT IN ('RELEASED', 'SUPERSEDED')) OR
           (approved_at IS NOT NULL AND released_at IS NOT NULL AND
            released_by IS NOT NULL AND effective_at IS NOT NULL))
);

CREATE UNIQUE INDEX ux_one_released_revision_per_document
    ON document_revisions(document_id) WHERE status = 'RELEASED';

CREATE TABLE revision_approvals (
    approval_id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES document_revisions(revision_id) ON DELETE CASCADE,
    approval_role TEXT NOT NULL CHECK (approval_role IN
        ('DOCUMENT_CONTROL', 'QUALITY', 'ENGINEERING', 'PROCESS_OWNER', 'CUSTOMER', 'OTHER')),
    approver_id INTEGER NOT NULL REFERENCES users(user_id),
    decision TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (decision IN ('PENDING', 'APPROVED', 'REJECTED')),
    decided_at TEXT,
    comments TEXT,
    signature_meaning TEXT NOT NULL DEFAULT 'I approve this revision for release',
    UNIQUE (revision_id, approval_role, approver_id),
    CHECK ((decision = 'PENDING' AND decided_at IS NULL) OR
           (decision <> 'PENDING' AND decided_at IS NOT NULL))
);

CREATE TABLE requirements (
    requirement_id INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN
        ('AS9100', 'NADCAP', 'CUSTOMER', 'REGULATORY', 'INTERNAL')),
    source_document TEXT NOT NULL,
    clause TEXT NOT NULL,
    revision TEXT NOT NULL,
    summary TEXT NOT NULL,
    effective_date TEXT,
    UNIQUE (source_document, clause, revision)
);

CREATE TABLE document_requirement_links (
    document_id INTEGER NOT NULL REFERENCES documents(document_id),
    requirement_id INTEGER NOT NULL REFERENCES requirements(requirement_id),
    applicability_note TEXT NOT NULL,
    PRIMARY KEY (document_id, requirement_id)
);

CREATE TABLE drawing_details (
    document_id INTEGER PRIMARY KEY REFERENCES documents(document_id),
    part_number TEXT NOT NULL,
    drawing_number TEXT NOT NULL,
    sheet_count INTEGER NOT NULL DEFAULT 1 CHECK (sheet_count > 0),
    design_authority TEXT NOT NULL,
    model_uri TEXT,
    customer_drawing_number TEXT
);

CREATE TABLE customer_spec_details (
    document_id INTEGER PRIMARY KEY REFERENCES documents(document_id),
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    source_url TEXT,
    received_at TEXT NOT NULL,
    received_by INTEGER NOT NULL REFERENCES users(user_id),
    review_due_date TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by INTEGER REFERENCES users(user_id),
    applicability TEXT CHECK (applicability IN ('PENDING', 'APPLICABLE', 'NOT_APPLICABLE')),
    flowdown_complete INTEGER NOT NULL DEFAULT 0 CHECK (flowdown_complete IN (0, 1)),
    review_notes TEXT
);

CREATE TABLE change_requests (
    change_request_id INTEGER PRIMARY KEY,
    request_number TEXT NOT NULL UNIQUE,
    document_id INTEGER NOT NULL REFERENCES documents(document_id),
    requested_by INTEGER NOT NULL REFERENCES users(user_id),
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reason TEXT NOT NULL,
    impact_assessment TEXT,
    customer_approval_required INTEGER NOT NULL DEFAULT 0 CHECK (customer_approval_required IN (0, 1)),
    customer_approval_reference TEXT,
    disposition TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (disposition IN ('OPEN', 'APPROVED', 'REJECTED', 'IMPLEMENTED')),
    disposition_by INTEGER REFERENCES users(user_id),
    disposition_at TEXT,
    implemented_revision_id INTEGER REFERENCES document_revisions(revision_id)
);

CREATE TABLE audit_findings (
    finding_id INTEGER PRIMARY KEY,
    finding_number TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL CHECK (source IN ('INTERNAL', 'CUSTOMER', 'AS9100', 'NADCAP', 'REGULATORY')),
    description TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CONTAINED', 'CLOSED')),
    closed_at TEXT
);

CREATE TABLE revision_change_links (
    revision_id INTEGER NOT NULL REFERENCES document_revisions(revision_id),
    change_request_id INTEGER REFERENCES change_requests(change_request_id),
    finding_id INTEGER REFERENCES audit_findings(finding_id),
    PRIMARY KEY (revision_id, change_request_id, finding_id),
    CHECK (change_request_id IS NOT NULL OR finding_id IS NOT NULL)
);

CREATE TABLE revision_training_requirements (
    revision_id INTEGER NOT NULL REFERENCES document_revisions(revision_id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(role_id),
    due_days INTEGER NOT NULL DEFAULT 30 CHECK (due_days >= 0),
    training_method TEXT NOT NULL DEFAULT 'READ_AND_UNDERSTAND',
    PRIMARY KEY (revision_id, role_id)
);

CREATE TABLE training_assignments (
    assignment_id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES document_revisions(revision_id),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    assigned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    due_at TEXT NOT NULL,
    completed_at TEXT,
    evidence_uri TEXT,
    UNIQUE (revision_id, user_id),
    CHECK (completed_at IS NULL OR evidence_uri IS NOT NULL)
);

CREATE TABLE controlled_copies (
    copy_id INTEGER PRIMARY KEY,
    copy_number TEXT NOT NULL UNIQUE,
    revision_id INTEGER NOT NULL REFERENCES document_revisions(revision_id),
    holder_id INTEGER REFERENCES users(user_id),
    location TEXT NOT NULL,
    medium TEXT NOT NULL CHECK (medium IN ('ELECTRONIC', 'PAPER')),
    issued_at TEXT NOT NULL,
    issued_by INTEGER NOT NULL REFERENCES users(user_id),
    acknowledged_at TEXT,
    recalled_at TEXT,
    status TEXT NOT NULL DEFAULT 'ISSUED'
        CHECK (status IN ('ISSUED', 'ACKNOWLEDGED', 'RECALLED', 'DESTROYED')),
    CHECK (status <> 'ACKNOWLEDGED' OR acknowledged_at IS NOT NULL),
    CHECK (status NOT IN ('RECALLED', 'DESTROYED') OR recalled_at IS NOT NULL)
);

CREATE TABLE event_log (
    event_id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(user_id),
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    details TEXT
);

-- Application workflow semaphore. Permissions should deny direct access in a
-- server deployment; the release script creates and removes a row atomically.
CREATE TABLE release_authorizations (
    revision_id INTEGER PRIMARY KEY REFERENCES document_revisions(revision_id),
    authorized_by INTEGER NOT NULL REFERENCES users(user_id),
    authorized_at TEXT NOT NULL
);

CREATE INDEX ix_revisions_document_status ON document_revisions(document_id, status);
CREATE INDEX ix_approvals_pending ON revision_approvals(decision, approver_id);
CREATE INDEX ix_training_open ON training_assignments(user_id, completed_at, due_at);
CREATE INDEX ix_copies_revision_status ON controlled_copies(revision_id, status);
CREATE INDEX ix_events_entity ON event_log(entity_type, entity_id, occurred_at);
CREATE INDEX ix_customer_specs_due ON customer_spec_details(review_due_date, reviewed_at);

CREATE TRIGGER prevent_self_approval
BEFORE INSERT ON revision_approvals
WHEN NEW.approver_id = (SELECT author_id FROM document_revisions WHERE revision_id = NEW.revision_id)
BEGIN
    SELECT RAISE(ABORT, 'revision author cannot approve their own work');
END;

CREATE TRIGGER prevent_self_approval_update
BEFORE UPDATE OF approver_id ON revision_approvals
WHEN NEW.approver_id = (SELECT author_id FROM document_revisions WHERE revision_id = NEW.revision_id)
BEGIN
    SELECT RAISE(ABORT, 'revision author cannot approve their own work');
END;

CREATE TRIGGER protect_released_revision_content
BEFORE UPDATE OF document_id, revision_code, change_summary, content_uri, content_sha256, author_id
ON document_revisions
WHEN OLD.status IN ('RELEASED', 'SUPERSEDED', 'OBSOLETE')
BEGIN
    SELECT RAISE(ABORT, 'released revision content is immutable; create a new revision');
END;

CREATE TRIGGER require_release_guard
BEFORE UPDATE OF status ON document_revisions
WHEN NEW.status = 'RELEASED' AND OLD.status <> 'RELEASED'
     AND NOT EXISTS (SELECT 1 FROM release_authorizations
                     WHERE revision_id = NEW.revision_id)
BEGIN
    SELECT RAISE(ABORT, 'use scripts/release_revision.py to release revisions');
END;

CREATE TRIGGER prevent_copy_of_unreleased_revision
BEFORE INSERT ON controlled_copies
WHEN (SELECT status FROM document_revisions WHERE revision_id = NEW.revision_id) <> 'RELEASED'
BEGIN
    SELECT RAISE(ABORT, 'controlled copies may only use released revisions');
END;

CREATE VIEW v_current_documents AS
SELECT d.document_id, d.document_number, d.title, dt.type_code, u.display_name AS owner,
       r.revision_id, r.revision_code, r.effective_at, r.next_review_date,
       p.process_code, c.customer_code
FROM documents d
JOIN document_types dt ON dt.document_type_id = d.document_type_id
JOIN users u ON u.user_id = d.owner_id
LEFT JOIN document_revisions r ON r.revision_id = d.current_revision_id
LEFT JOIN processes p ON p.process_id = d.process_id
LEFT JOIN customers c ON c.customer_id = d.customer_id
WHERE d.active = 1;

CREATE VIEW v_pending_approvals AS
SELECT ra.approval_id, d.document_number, r.revision_code, ra.approval_role,
       u.display_name AS approver, u.email
FROM revision_approvals ra
JOIN document_revisions r ON r.revision_id = ra.revision_id
JOIN documents d ON d.document_id = r.document_id
JOIN users u ON u.user_id = ra.approver_id
WHERE ra.decision = 'PENDING';

CREATE VIEW v_overdue_reviews AS
SELECT d.document_number, d.title, r.revision_code, r.next_review_date AS due_date,
       'PERIODIC_REVIEW' AS review_type
FROM documents d JOIN document_revisions r ON r.revision_id = d.current_revision_id
WHERE r.next_review_date IS NOT NULL AND date(r.next_review_date) <= date('now')
UNION ALL
SELECT d.document_number, d.title, r.revision_code, cs.review_due_date,
       'CUSTOMER_SPEC_REVIEW'
FROM customer_spec_details cs
JOIN documents d ON d.document_id = cs.document_id
LEFT JOIN document_revisions r ON r.revision_id = d.current_revision_id
WHERE cs.reviewed_at IS NULL AND date(cs.review_due_date) <= date('now');

CREATE VIEW v_unacknowledged_copies AS
SELECT cc.copy_number, d.document_number, r.revision_code, cc.location,
       u.display_name AS holder, cc.issued_at
FROM controlled_copies cc
JOIN document_revisions r ON r.revision_id = cc.revision_id
JOIN documents d ON d.document_id = r.document_id
LEFT JOIN users u ON u.user_id = cc.holder_id
WHERE cc.status = 'ISSUED';

CREATE VIEW v_open_training AS
SELECT ta.assignment_id, d.document_number, r.revision_code, u.display_name,
       u.email, ta.due_at,
       CASE WHEN date(ta.due_at) < date('now') THEN 1 ELSE 0 END AS overdue
FROM training_assignments ta
JOIN document_revisions r ON r.revision_id = ta.revision_id
JOIN documents d ON d.document_id = r.document_id
JOIN users u ON u.user_id = ta.user_id
WHERE ta.completed_at IS NULL;

CREATE VIEW v_revision_traceability AS
SELECT r.revision_id, d.document_number, r.revision_code,
       cr.request_number AS change_request, af.finding_number AS audit_finding
FROM document_revisions r
JOIN documents d ON d.document_id = r.document_id
LEFT JOIN revision_change_links l ON l.revision_id = r.revision_id
LEFT JOIN change_requests cr ON cr.change_request_id = l.change_request_id
LEFT JOIN audit_findings af ON af.finding_id = l.finding_id;

INSERT INTO schema_versions(version, description)
VALUES (1, 'Initial aerospace document control schema');

COMMIT;
