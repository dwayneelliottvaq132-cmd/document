# AS9100 and Nadcap control matrix

This matrix is an implementation aid, not a reproduction of either standard and
not a declaration of conformity. Confirm the current revision and contractually
applicable clauses with your certification body, PRI/Nadcap resources, customers,
and Quality organization.

| Control objective | Database evidence | Operating responsibility |
| --- | --- | --- |
| Identify and describe documented information | `documents`, `document_types`, `document_revisions` | Document Control assigns unique numbers and metadata. |
| Review and approve before release | `revision_approvals`; author self-approval trigger; release command | Quality defines the approval matrix; independent approvers record decisions. |
| Control changes and revision status | `change_requests`, `revision_change_links`, immutable released revisions | Owner assesses impact; Document Control releases a new revision. |
| Make the correct version available at point of use | `current_revision_id`, `controlled_copies`, dashboard views | Copy holders acknowledge; Document Control recalls superseded copies. |
| Protect integrity and prevent unintended use | SHA-256 checksum, status constraints, access-controlled content URI | IT controls storage and access; users do not alter released records. |
| Retain and dispose records | `retention_years`, timestamps, superseded history | Quality approves a retention schedule and documented disposal. |
| Control external/customer documents | `customer_spec_details`, external document type, overdue view | Contract/Quality reviews changes, applicability, and flow-down. |
| Communicate requirements to suppliers | `requirements` and traceable document links | Purchasing uses released requirements in supplier flow-down. |
| Ensure competence after change | role requirements, assignments, evidence URI, open-training view | Supervisors assign and verify training before independent work. |
| Audit and corrective-action traceability | `audit_findings`, revision links, event history | Quality links corrective changes to their initiating finding. |
| Nadcap procedure currency and objective evidence | process commodity, exact requirement revision/link, approval and distribution history | Each special-process owner maintains the applicable AC/checklist mapping. |

## Required local procedures

The organization should document at least: numbering and classification; drafting;
technical/quality/customer approval; electronic signature; emergency/temporary
change; external specification monitoring; distribution and recall; shop-floor
verification; training; retention/disposal; backup/recovery; access review; and
periodic system validation. Commodity-specific Nadcap checklists may add controls
such as frozen processes, customer approval, specification precedence, or operator
qualification that should be represented as requirements and linked records.

