# Aerospace Document Control Database

This repository contains a deployable SQLite document-control database for internal
procedures, customer specifications, and engineering drawings. It is designed to
support an organization's AS9100D and Nadcap document-control processes; it does
not, by itself, certify compliance.

## What it controls

- Unique document numbers, owners, document types, customers, programs, and processes.
- Immutable revision records with review, approval, release, and obsolescence states.
- Approval evidence and segregation of author/approver duties.
- Customer-specification receipt, review, flow-down, and acknowledgement.
- Drawing metadata, including part number, sheet, and source/customer identifiers.
- Controlled-copy distribution, acknowledgement, recall, and point-of-use status.
- Training assignments and completion evidence for affected personnel.
- Change requests, linked audit findings, and a durable event history.
- Periodic review dates, external-document currency checks, and overdue dashboards.

## Quick start

Python 3.9+ and SQLite 3.35+ are the only requirements.

```bash
python scripts/init_db.py document_control.db
sqlite3 document_control.db < examples/sample_data.sql
python -m unittest discover -s tests -v
```

The initializer applies `sql/schema.sql`, enables foreign keys, and records the
schema version. It refuses to overwrite an existing database unless `--force` is
provided.

To upgrade an existing version-1 database in place:

```bash
python scripts/migrate_db.py document_control.db
```

The migrator creates a timestamped SQLite backup beside the database before it
changes anything, applies each pending migration in order, and checks database
integrity and foreign keys. Keep the backup until the upgraded database has been
validated in your environment. `--no-backup` is available for disposable databases.
Running the command again is safe and reports that no changes are needed.

## Local web interface

Start the browser interface against an initialized or migrated database:

```bash
python scripts/web_app.py document_control.db
```

Then open `http://127.0.0.1:8765`. The dependency-free interface provides:

- dashboard metrics and recent release activity;
- document search, master-record creation, and revision history;
- draft creation, review decisions, approval, and controlled release;
- training assignment status and completion evidence;
- controlled-copy issuance and recall.

The server listens only on the local computer and protects write forms against
cross-site requests. It does not provide user authentication or electronic
signatures. Use it for a single-user evaluation or controlled workstation. Add
central identity, authorization, TLS, session auditing, and validated signature
controls before making it available to multiple users or using it as a formal
approval system.

## Core workflow

1. Create a row in `documents` with a stable document number and named owner.
2. Add a `document_revisions` row in `DRAFT`; the revision content must have a
   SHA-256 checksum and a controlled repository location.
3. Record required reviewers/approvers in `revision_approvals`. The author cannot
   approve their own revision.
4. Record affected roles in `revision_training_requirements` where training is
   required before independent work.
5. Move the revision to `IN_REVIEW`, obtain approvals, then set it to `APPROVED`.
6. Release it with `scripts/release_revision.py`. The transactional release check
   blocks missing approvals and missing training assignments for any active member
   of an affected role, supersedes the old revision,
   and makes the released revision the document's current revision.
7. Issue controlled copies through `controlled_copies`; recall or replace them when
   a new revision is released.

Content is frozen once a revision enters `IN_REVIEW` or has an approved decision.
Create a new revision if reviewed content needs correction. States move forward
through `DRAFT`, `IN_REVIEW`, `APPROVED`, `RELEASED`, and `SUPERSEDED`; a revision
can also be retired as `OBSOLETE`. Review and release states cannot return to draft.
Triggers reject direct inserts of released revisions and validate controlled-copy
revision changes and reissuance, while allowing recall of superseded copies.

The release tool accepts an ISO 8601 effective date/time at or before the current
time. Date-only and timezone-free values use UTC. Future effective dates are
rejected without changing the current revision; run the release when the new
revision becomes effective. Scheduled activation is not implemented. Training
assignment coverage is required for release; completion remains tracked separately.

Existing databases retain their original controls until upgraded with
`scripts/migrate_db.py`. Do not use `init_db.py --force` on a populated database;
that replaces the database instead of migrating it.

## Useful views

| View | Purpose |
| --- | --- |
| `v_current_documents` | Current effective revision and ownership at a glance |
| `v_pending_approvals` | Open approval tasks |
| `v_overdue_reviews` | Periodic reviews and external currency checks due now |
| `v_unacknowledged_copies` | Issued copies not yet acknowledged |
| `v_open_training` | Training assignments still incomplete |
| `v_revision_traceability` | Revision-to-change-request and audit-finding traceability |

## Standards alignment

The schema provides evidence fields commonly used to implement AS9100D clauses
7.5 (documented information), 8.2.2/8.2.3 (customer requirements), 8.3.6 (design
changes), 8.4.3 (supplier flow-down), 9.2 (internal audit), and 10.2
(nonconformity/corrective action). Nadcap requirements vary by commodity and the
applicable Audit Criteria (AC) and Customer Task Group documents. Use
`requirements` and `document_requirement_links` to load the exact controlled
requirements applicable to your scope.

Before production use, Quality should validate the schema and operating procedure,
configure retention periods, define electronic-signature controls, restrict write
access, establish backup/restore testing, and verify the current standards and
customer-specific requirements. SQLite is appropriate for a small, controlled
team; use the same logical model on a managed server database when concurrent use,
central identity, or formal electronic signatures are required.

## Repository layout

- `sql/schema.sql` — normalized schema, constraints, indexes, triggers, and views.
- `scripts/init_db.py` — safe database bootstrap command.
- `scripts/migrate_db.py` — backup and ordered in-place schema migration command.
- `scripts/release_revision.py` — controlled, transactional revision release.
- `scripts/web_app.py` — local browser interface and workflow actions.
- `sql/migrations/` — ordered upgrades for existing databases.
- `web/static/` — interface styling.
- `examples/sample_data.sql` — fictional starter roles, users, and a procedure.
- `tests/test_database.py` — workflow and control tests.
- `docs/data-dictionary.md` — table-by-table data dictionary.
- `docs/control-matrix.md` — implementation-oriented standards mapping.

