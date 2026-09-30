PRAGMA foreign_keys = ON;
BEGIN;

INSERT INTO roles(role_id, role_name, description) VALUES
  (1, 'Document Control', 'Maintains the controlled document system'),
  (2, 'Quality Engineering', 'Reviews quality-system requirements'),
  (3, 'Special Process Operator', 'Performs approved special processes');

INSERT INTO users(user_id, employee_number, display_name, email) VALUES
  (1, 'E1001', 'Alex Author', 'alex.author@example.invalid'),
  (2, 'E1002', 'Quinn Quality', 'quinn.quality@example.invalid'),
  (3, 'E1003', 'Dana Control', 'dana.control@example.invalid'),
  (4, 'E1004', 'Sam Operator', 'sam.operator@example.invalid');

INSERT INTO user_roles(user_id, role_id) VALUES (3, 1), (2, 2), (4, 3);

INSERT INTO document_types(type_code, type_name, is_external, default_review_months, default_retention_years) VALUES
  ('PROC', 'Internal Procedure', 0, 24, 10),
  ('CSPEC', 'Customer Specification', 1, 12, 15),
  ('DWG', 'Engineering Drawing', 0, 24, 15);

INSERT INTO processes(process_id, process_code, process_name, nadcap_commodity, process_owner_id)
VALUES (1, 'HT', 'Heat Treatment', 'Heat Treating', 2);

INSERT INTO documents(document_id, document_number, title, document_type_id,
                      owner_id, process_id, retention_years, created_by)
VALUES (1, 'QP-001', 'Control of Documented Information', 1, 3, 1, 10, 1);

INSERT INTO document_revisions(revision_id, document_id, revision_code, status,
                               change_summary, content_uri, content_sha256, author_id,
                               approved_at, next_review_date)
VALUES (1, 1, 'A', 'APPROVED', 'Initial controlled release',
        'repository://procedures/QP-001-A.pdf',
        '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
        1, '2026-09-30T12:00:00Z', '2028-09-30');

INSERT INTO revision_approvals(revision_id, approval_role, approver_id, decision, decided_at, comments) VALUES
  (1, 'QUALITY', 2, 'APPROVED', '2026-09-30T11:00:00Z', 'Requirements verified'),
  (1, 'DOCUMENT_CONTROL', 3, 'APPROVED', '2026-09-30T12:00:00Z', 'Format and metadata verified');

INSERT INTO revision_training_requirements(revision_id, role_id, due_days)
VALUES (1, 3, 14);
INSERT INTO training_assignments(revision_id, user_id, due_at)
VALUES (1, 4, '2026-10-14T00:00:00Z');

INSERT INTO requirements(source, source_document, clause, revision, summary)
VALUES ('AS9100', 'AS9100D', '7.5', 'D', 'Control documented information throughout its lifecycle');
INSERT INTO document_requirement_links(document_id, requirement_id, applicability_note)
VALUES (1, 1, 'Primary documented-information control procedure');

COMMIT;
