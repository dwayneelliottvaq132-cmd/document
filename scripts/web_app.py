#!/usr/bin/env python3
"""Run the dependency-free local document-control web interface."""

import argparse
import datetime as dt
import html
import secrets
import sqlite3
from contextlib import closing
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

try:
    from scripts.release_revision import release
except ModuleNotFoundError:  # Direct execution: python scripts/web_app.py
    from release_revision import release


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def page(title: str, body: str, notice: str = "", error: str = "") -> bytes:
    message = ""
    if notice:
        message = f'<div class="notice">{esc(notice)}</div>'
    if error:
        message = f'<div class="error">{esc(error)}</div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · AeroDocs</title><link rel="stylesheet" href="/static/app.css"></head>
<body><header><a class="brand" href="/"><span>AD</span>AeroDocs</a><nav>
<a href="/">Dashboard</a><a href="/documents">Documents</a><a href="/training">Training</a><a href="/copies">Controlled copies</a>
</nav></header><main>{message}{body}</main><footer>Local document-control workspace · AS9100 / Nadcap support</footer></body></html>""".encode()


class DocumentControlHandler(BaseHTTPRequestHandler):
    server_version = "AeroDocs/1.0"

    @property
    def database(self) -> Path:
        return self.server.database

    def connect(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def send_html(self, title, body, status=HTTPStatus.OK, notice="", error=""):
        content = page(title, body, notice, error)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, location, notice=""):
        if notice:
            separator = "&" if "?" in location else "?"
            location += separator + "notice=" + quote(notice)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def form(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("form is too large")
        values = {key: items[0] for key, items in parse_qs(
            self.rfile.read(length).decode("utf-8"), keep_blank_values=True
        ).items()}
        if not secrets.compare_digest(values.pop("csrf", ""), self.server.csrf_token):
            raise ValueError("form expired; reload the page and try again")
        return values

    def csrf(self):
        return f'<input type="hidden" name="csrf" value="{self.server.csrf_token}">'

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/static/app.css":
                return self.serve_css()
            if parsed.path == "/":
                return self.dashboard(parsed)
            if parsed.path == "/documents":
                return self.documents(parsed)
            if parsed.path == "/documents/new":
                return self.new_document()
            if parsed.path == "/copies":
                return self.copies(parsed)
            if parsed.path == "/training":
                return self.training(parsed)
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "documents":
                return self.document(int(parts[1]), parsed)
            if len(parts) == 4 and parts[0] == "documents" and parts[2:] == ["revisions", "new"]:
                return self.new_revision(int(parts[1]))
            return self.not_found()
        except (ValueError, sqlite3.Error) as exc:
            self.send_html("Request error", "<h1>Request could not be completed</h1>", HTTPStatus.BAD_REQUEST, error=str(exc))

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            values = self.form()
            if parsed.path == "/documents/new":
                return self.create_document(values)
            if parsed.path == "/copies":
                return self.issue_copy(values)
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "documents" and parts[2:] == ["revisions", "new"]:
                return self.create_revision(int(parts[1]), values)
            if len(parts) == 3 and parts[0] == "revisions":
                revision_id = int(parts[1])
                action = parts[2]
                if action == "submit":
                    return self.submit_revision(revision_id)
                if action == "approval":
                    return self.record_approval(revision_id, values)
                if action == "approve":
                    return self.approve_revision(revision_id)
                if action == "release":
                    return self.release_revision(revision_id, values)
            if len(parts) == 3 and parts[0] == "copies" and parts[2] == "recall":
                return self.recall_copy(int(parts[1]))
            if len(parts) == 3 and parts[0] == "training" and parts[2] == "complete":
                return self.complete_training(int(parts[1]), values)
            return self.not_found()
        except (ValueError, sqlite3.Error) as exc:
            self.send_html("Action failed", "<h1>Action failed</h1><p>No changes were applied.</p>", HTTPStatus.BAD_REQUEST, error=str(exc))

    def serve_css(self):
        content = (STATIC / "app.css").read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def dashboard(self, parsed):
        with closing(self.connect()) as connection:
            counts = {
                "Active documents": connection.execute("SELECT COUNT(*) FROM documents WHERE active=1").fetchone()[0],
                "Pending approvals": connection.execute("SELECT COUNT(*) FROM v_pending_approvals").fetchone()[0],
                "Open training": connection.execute("SELECT COUNT(*) FROM v_open_training").fetchone()[0],
                "Reviews due": connection.execute("SELECT COUNT(*) FROM v_overdue_reviews").fetchone()[0],
                "Copies awaiting acknowledgement": connection.execute("SELECT COUNT(*) FROM v_unacknowledged_copies").fetchone()[0],
            }
            recent = connection.execute(
                """SELECT d.document_id, d.document_number, d.title, r.revision_code,
                          r.status, r.next_review_date
                   FROM documents d LEFT JOIN document_revisions r
                     ON r.revision_id=d.current_revision_id
                   WHERE d.active=1 ORDER BY d.document_number LIMIT 10"""
            ).fetchall()
            events = connection.execute(
                """SELECT action, entity_type, entity_id, occurred_at, details
                   FROM event_log ORDER BY event_id DESC LIMIT 8"""
            ).fetchall()
        cards = "".join(f'<article class="metric"><strong>{value}</strong><span>{esc(label)}</span></article>' for label, value in counts.items())
        rows = "".join(f'<tr><td><a href="/documents/{r["document_id"]}">{esc(r["document_number"])}</a></td><td>{esc(r["title"])}</td><td>{esc(r["revision_code"] or "—")}</td><td><span class="status {esc((r["status"] or "none").lower())}">{esc(r["status"] or "No release")}</span></td><td>{esc(r["next_review_date"] or "—")}</td></tr>' for r in recent)
        timeline = "".join(f'<li><b>{esc(e["action"])}</b> · {esc(e["entity_type"])} {e["entity_id"]}<small>{esc(e["occurred_at"])} · {esc(e["details"] or "")}</small></li>' for e in events) or "<li>No workflow events yet.</li>"
        body = f'<section class="hero"><div><p class="eyebrow">CONTROL CENTER</p><h1>Document assurance at a glance</h1><p>Current releases, approvals, training, and point-of-use copies in one workspace.</p></div><a class="button" href="/documents/new">New document</a></section><section class="metrics">{cards}</section><section class="grid"><article class="panel wide"><div class="panel-title"><h2>Controlled documents</h2><a href="/documents">View all</a></div><div class="table-wrap"><table><thead><tr><th>Number</th><th>Title</th><th>Rev</th><th>Status</th><th>Next review</th></tr></thead><tbody>{rows}</tbody></table></div></article><article class="panel"><h2>Recent activity</h2><ol class="timeline">{timeline}</ol></article></section>'
        notice = parse_qs(parsed.query).get("notice", [""])[0]
        self.send_html("Dashboard", body, notice=notice)

    def documents(self, parsed):
        query = parse_qs(parsed.query).get("q", [""])[0].strip()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """SELECT d.document_id, d.document_number, d.title, dt.type_code,
                          u.display_name owner, r.revision_code, r.status
                   FROM documents d JOIN document_types dt USING(document_type_id)
                   JOIN users u ON u.user_id=d.owner_id
                   LEFT JOIN document_revisions r ON r.revision_id=d.current_revision_id
                   WHERE (?='' OR d.document_number LIKE ? OR d.title LIKE ?)
                   ORDER BY d.document_number""", (query, f"%{query}%", f"%{query}%")
            ).fetchall()
        rows_html = "".join(f'<tr><td><a href="/documents/{r["document_id"]}">{esc(r["document_number"])}</a></td><td>{esc(r["title"])}</td><td>{esc(r["type_code"])}</td><td>{esc(r["owner"])}</td><td>{esc(r["revision_code"] or "—")}</td><td><span class="status {esc((r["status"] or "none").lower())}">{esc(r["status"] or "No release")}</span></td></tr>' for r in rows)
        body = f'<section class="page-title"><div><p class="eyebrow">LIBRARY</p><h1>Documents</h1></div><a class="button" href="/documents/new">New document</a></section><form class="search" method="get"><input name="q" value="{esc(query)}" placeholder="Search number or title"><button>Search</button></form><article class="panel"><div class="table-wrap"><table><thead><tr><th>Number</th><th>Title</th><th>Type</th><th>Owner</th><th>Current rev</th><th>Status</th></tr></thead><tbody>{rows_html}</tbody></table></div></article>'
        self.send_html("Documents", body)

    def new_document(self):
        with closing(self.connect()) as connection:
            users = connection.execute("SELECT user_id, display_name FROM users WHERE active=1 ORDER BY display_name").fetchall()
            types = connection.execute("SELECT document_type_id, type_code, type_name, default_retention_years FROM document_types ORDER BY type_code").fetchall()
        user_options = "".join(f'<option value="{u[0]}">{esc(u[1])}</option>' for u in users)
        type_options = "".join(f'<option value="{t[0]}" data-retention="{t[3]}">{esc(t[1])} — {esc(t[2])}</option>' for t in types)
        body = f'<section class="page-title"><div><p class="eyebrow">NEW RECORD</p><h1>Create document</h1></div></section><form class="panel form" method="post">{self.csrf()}<div class="fields"><label>Document number<input name="document_number" required></label><label>Title<input name="title" required></label><label>Type<select name="document_type_id" required>{type_options}</select></label><label>Owner<select name="owner_id" required>{user_options}</select></label><label>Retention years<input name="retention_years" type="number" min="1" value="10" required></label><label>Confidentiality<select name="confidentiality"><option>INTERNAL</option><option>PUBLIC</option><option>CUSTOMER</option><option>EXPORT_CONTROLLED</option></select></label></div><button class="button">Create document</button></form>'
        self.send_html("New document", body)

    def create_document(self, values):
        required = ("document_number", "title", "document_type_id", "owner_id", "retention_years")
        if any(not values.get(key, "").strip() for key in required):
            raise ValueError("all required fields must be completed")
        with closing(self.connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """INSERT INTO documents(document_number,title,document_type_id,owner_id,
                              confidentiality,retention_years,created_by)
                       VALUES(?,?,?,?,?,?,?)""",
                    (values["document_number"].strip(), values["title"].strip(), int(values["document_type_id"]),
                     int(values["owner_id"]), values.get("confidentiality", "INTERNAL"),
                     int(values["retention_years"]), int(values["owner_id"])),
                )
                document_id = cursor.lastrowid
        self.redirect(f"/documents/{document_id}", "Document created")

    def document(self, document_id, parsed):
        with closing(self.connect()) as connection:
            document = connection.execute(
                """SELECT d.*, dt.type_code, dt.type_name, u.display_name owner
                   FROM documents d JOIN document_types dt USING(document_type_id)
                   JOIN users u ON u.user_id=d.owner_id WHERE document_id=?""", (document_id,)
            ).fetchone()
            if not document:
                return self.not_found()
            revisions = connection.execute(
                """SELECT r.*, u.display_name author FROM document_revisions r
                   JOIN users u ON u.user_id=r.author_id WHERE document_id=?
                   ORDER BY revision_id DESC""", (document_id,)
            ).fetchall()
            users = connection.execute("SELECT user_id, display_name FROM users WHERE active=1 ORDER BY display_name").fetchall()
            approvals = connection.execute(
                """SELECT ra.*, u.display_name FROM revision_approvals ra
                   JOIN users u ON u.user_id=ra.approver_id
                   JOIN document_revisions r USING(revision_id)
                   WHERE r.document_id=? ORDER BY ra.approval_id""", (document_id,)
            ).fetchall()
        user_options = "".join(f'<option value="{u[0]}">{esc(u[1])}</option>' for u in users)
        approval_by_revision = {}
        for approval in approvals:
            approval_by_revision.setdefault(approval["revision_id"], []).append(approval)
        blocks = []
        for revision in revisions:
            evidence = approval_by_revision.get(revision["revision_id"], [])
            evidence_html = "".join(f'<li><span>{esc(a["approval_role"])} · {esc(a["display_name"])}</span><span class="status {esc(a["decision"].lower())}">{esc(a["decision"])}</span></li>' for a in evidence) or "<li>No approval evidence recorded.</li>"
            actions = ""
            rid = revision["revision_id"]
            if revision["status"] == "DRAFT":
                actions = f'<form method="post" action="/revisions/{rid}/submit">{self.csrf()}<button>Submit for review</button></form>'
            elif revision["status"] == "IN_REVIEW":
                actions = f'<form class="inline-form" method="post" action="/revisions/{rid}/approval">{self.csrf()}<select name="approval_role"><option>QUALITY</option><option>DOCUMENT_CONTROL</option><option>ENGINEERING</option><option>PROCESS_OWNER</option><option>CUSTOMER</option><option>OTHER</option></select><select name="approver_id">{user_options}</select><select name="decision"><option>APPROVED</option><option>REJECTED</option><option>PENDING</option></select><button>Record decision</button></form><form method="post" action="/revisions/{rid}/approve">{self.csrf()}<button>Mark approved</button></form>'
            elif revision["status"] == "APPROVED":
                actions = f'<form class="inline-form" method="post" action="/revisions/{rid}/release">{self.csrf()}<select name="releaser_id">{user_options}</select><input type="date" name="effective_at" value="{dt.date.today().isoformat()}" required><button>Release revision</button></form>'
            blocks.append(f'<article class="revision"><div class="revision-head"><div><h3>Revision {esc(revision["revision_code"])}</h3><p>{esc(revision["change_summary"])}</p></div><span class="status {esc(revision["status"].lower())}">{esc(revision["status"])}</span></div><dl><div><dt>Author</dt><dd>{esc(revision["author"])}</dd></div><div><dt>Content URI</dt><dd>{esc(revision["content_uri"])}</dd></div><div><dt>Effective</dt><dd>{esc(revision["effective_at"] or "—")}</dd></div><div><dt>Next review</dt><dd>{esc(revision["next_review_date"] or "—")}</dd></div></dl><h4>Approval evidence</h4><ul class="evidence">{evidence_html}</ul><div class="actions">{actions}</div></article>')
        revisions_html = "".join(blocks) or '<div class="empty">No revisions yet. Create the first draft.</div>'
        body = f'<section class="page-title"><div><p class="eyebrow">{esc(document["type_code"])}</p><h1>{esc(document["document_number"])} · {esc(document["title"])}</h1><p>Owner: {esc(document["owner"])} · Retention: {document["retention_years"]} years · {esc(document["confidentiality"])}</p></div><a class="button" href="/documents/{document_id}/revisions/new">New revision</a></section><section class="revision-list">{revisions_html}</section>'
        notice = parse_qs(parsed.query).get("notice", [""])[0]
        self.send_html(document["document_number"], body, notice=notice)

    def new_revision(self, document_id):
        with closing(self.connect()) as connection:
            document = connection.execute("SELECT document_number,title,owner_id FROM documents WHERE document_id=?", (document_id,)).fetchone()
            users = connection.execute("SELECT user_id,display_name FROM users WHERE active=1 ORDER BY display_name").fetchall()
        if not document:
            return self.not_found()
        options = "".join(f'<option value="{u[0]}" {"selected" if u[0] == document["owner_id"] else ""}>{esc(u[1])}</option>' for u in users)
        body = f'<section class="page-title"><div><p class="eyebrow">NEW REVISION</p><h1>{esc(document["document_number"])} · {esc(document["title"])}</h1></div></section><form class="panel form" method="post">{self.csrf()}<div class="fields"><label>Revision code<input name="revision_code" required></label><label>Author<select name="author_id">{options}</select></label><label class="span-2">Change summary<textarea name="change_summary" required></textarea></label><label class="span-2">Controlled content URI<input name="content_uri" placeholder="repository://procedures/document.pdf" required></label><label class="span-2">SHA-256<input name="content_sha256" minlength="64" maxlength="64" pattern="[0-9A-Fa-f]{{64}}" required></label><label>Next review date<input type="date" name="next_review_date"></label></div><button class="button">Create draft</button></form>'
        self.send_html("New revision", body)

    def create_revision(self, document_id, values):
        required = ("revision_code", "author_id", "change_summary", "content_uri", "content_sha256")
        if any(not values.get(key, "").strip() for key in required):
            raise ValueError("all required fields must be completed")
        digest = values["content_sha256"].strip()
        if len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
            raise ValueError("SHA-256 must contain exactly 64 hexadecimal characters")
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """INSERT INTO document_revisions(document_id,revision_code,change_summary,
                              content_uri,content_sha256,author_id,next_review_date)
                       VALUES(?,?,?,?,?,?,NULLIF(?,''))""",
                    (document_id, values["revision_code"].strip(), values["change_summary"].strip(),
                     values["content_uri"].strip(), digest.lower(), int(values["author_id"]),
                     values.get("next_review_date", "")),
                )
        self.redirect(f"/documents/{document_id}", "Draft revision created")

    def revision_document(self, connection, revision_id):
        row = connection.execute("SELECT document_id FROM document_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if not row:
            raise ValueError("revision does not exist")
        return row[0]

    def submit_revision(self, revision_id):
        with closing(self.connect()) as connection:
            document_id = self.revision_document(connection, revision_id)
            with connection:
                connection.execute("UPDATE document_revisions SET status='IN_REVIEW' WHERE revision_id=? AND status='DRAFT'", (revision_id,))
                if not connection.total_changes:
                    raise ValueError("only draft revisions can be submitted")
        self.redirect(f"/documents/{document_id}", "Revision submitted for review")

    def record_approval(self, revision_id, values):
        decision = values.get("decision", "")
        if decision not in ("PENDING", "APPROVED", "REJECTED"):
            raise ValueError("invalid approval decision")
        decided_at = None if decision == "PENDING" else utc_now()
        with closing(self.connect()) as connection:
            document_id = self.revision_document(connection, revision_id)
            status = connection.execute("SELECT status FROM document_revisions WHERE revision_id=?", (revision_id,)).fetchone()[0]
            if status != "IN_REVIEW":
                raise ValueError("approval decisions can only be recorded during review")
            with connection:
                connection.execute(
                    """INSERT INTO revision_approvals(revision_id,approval_role,approver_id,decision,decided_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(revision_id,approval_role,approver_id)
                       DO UPDATE SET decision=excluded.decision, decided_at=excluded.decided_at""",
                    (revision_id, values["approval_role"], int(values["approver_id"]), decision, decided_at),
                )
        self.redirect(f"/documents/{document_id}", "Approval decision recorded")

    def approve_revision(self, revision_id):
        with closing(self.connect()) as connection:
            document_id = self.revision_document(connection, revision_id)
            decisions = connection.execute("SELECT decision FROM revision_approvals WHERE revision_id=?", (revision_id,)).fetchall()
            if not decisions or any(row[0] != "APPROVED" for row in decisions):
                raise ValueError("every recorded approval must be approved")
            with connection:
                cursor = connection.execute("UPDATE document_revisions SET status='APPROVED', approved_at=? WHERE revision_id=? AND status='IN_REVIEW'", (utc_now(), revision_id))
                if not cursor.rowcount:
                    raise ValueError("revision is not in review")
        self.redirect(f"/documents/{document_id}", "Revision marked approved")

    def release_revision(self, revision_id, values):
        with closing(self.connect()) as connection:
            document_id = self.revision_document(connection, revision_id)
        release(self.database, revision_id, int(values["releaser_id"]), values["effective_at"])
        self.redirect(f"/documents/{document_id}", "Revision released")

    def copies(self, parsed):
        with closing(self.connect()) as connection:
            copies = connection.execute(
                """SELECT cc.*, d.document_number, r.revision_code, u.display_name holder
                   FROM controlled_copies cc JOIN document_revisions r USING(revision_id)
                   JOIN documents d USING(document_id) LEFT JOIN users u ON u.user_id=cc.holder_id
                   ORDER BY cc.copy_id DESC"""
            ).fetchall()
            revisions = connection.execute(
                """SELECT r.revision_id,d.document_number,r.revision_code FROM document_revisions r
                   JOIN documents d USING(document_id) WHERE r.status='RELEASED' ORDER BY d.document_number"""
            ).fetchall()
            users = connection.execute("SELECT user_id,display_name FROM users WHERE active=1 ORDER BY display_name").fetchall()
        rev_options = "".join(f'<option value="{r[0]}">{esc(r[1])} rev {esc(r[2])}</option>' for r in revisions)
        user_options = "".join(f'<option value="{u[0]}">{esc(u[1])}</option>' for u in users)
        copy_rows = []
        for copy in copies:
            action = "—"
            if copy["status"] not in ("RECALLED", "DESTROYED"):
                action = (
                    f'<form method="post" action="/copies/{copy["copy_id"]}/recall">'
                    f'{self.csrf()}<button>Recall</button></form>'
                )
            copy_rows.append(
                f'<tr><td>{esc(copy["copy_number"])}</td>'
                f'<td>{esc(copy["document_number"])} rev {esc(copy["revision_code"])}</td>'
                f'<td>{esc(copy["location"])}</td><td>{esc(copy["holder"] or "—")}</td>'
                f'<td><span class="status {esc(copy["status"].lower())}">{esc(copy["status"])}</span></td>'
                f'<td>{action}</td></tr>'
            )
        rows = "".join(copy_rows)
        body = f'<section class="page-title"><div><p class="eyebrow">POINT OF USE</p><h1>Controlled copies</h1></div></section><section class="grid"><article class="panel wide"><div class="table-wrap"><table><thead><tr><th>Copy</th><th>Document</th><th>Location</th><th>Holder</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></article><form class="panel form compact" method="post">{self.csrf()}<h2>Issue copy</h2><label>Copy number<input name="copy_number" required></label><label>Released revision<select name="revision_id" required>{rev_options}</select></label><label>Location<input name="location" required></label><label>Medium<select name="medium"><option>ELECTRONIC</option><option>PAPER</option></select></label><label>Holder<select name="holder_id"><option value="">Unassigned</option>{user_options}</select></label><label>Issued by<select name="issued_by">{user_options}</select></label><button class="button">Issue controlled copy</button></form></section>'
        notice = parse_qs(parsed.query).get("notice", [""])[0]
        self.send_html("Controlled copies", body, notice=notice)

    def issue_copy(self, values):
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """INSERT INTO controlled_copies(copy_number,revision_id,holder_id,location,
                              medium,issued_at,issued_by) VALUES(?,?,NULLIF(?,''),?,?,?,?)""",
                    (values["copy_number"].strip(), int(values["revision_id"]), values.get("holder_id", ""),
                     values["location"].strip(), values["medium"], utc_now(), int(values["issued_by"])),
                )
        self.redirect("/copies", "Controlled copy issued")

    def recall_copy(self, copy_id):
        with closing(self.connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """UPDATE controlled_copies SET status='RECALLED', recalled_at=?
                       WHERE copy_id=? AND status NOT IN ('RECALLED','DESTROYED')""", (utc_now(), copy_id)
                )
                if not cursor.rowcount:
                    raise ValueError("copy is already recalled or does not exist")
        self.redirect("/copies", "Controlled copy recalled")

    def training(self, parsed):
        with closing(self.connect()) as connection:
            assignments = connection.execute(
                """SELECT ta.assignment_id, d.document_number, r.revision_code,
                          u.display_name, ta.assigned_at, ta.due_at, ta.completed_at,
                          ta.evidence_uri
                   FROM training_assignments ta
                   JOIN document_revisions r USING(revision_id)
                   JOIN documents d USING(document_id)
                   JOIN users u USING(user_id)
                   ORDER BY ta.completed_at IS NOT NULL, ta.due_at, d.document_number"""
            ).fetchall()
        rows = []
        for assignment in assignments:
            if assignment["completed_at"]:
                status = '<span class="status approved">COMPLETED</span>'
                action = esc(assignment["evidence_uri"])
            else:
                status = '<span class="status pending">OPEN</span>'
                action = (
                    f'<form class="inline-form" method="post" action="/training/{assignment["assignment_id"]}/complete">'
                    f'{self.csrf()}<input name="evidence_uri" placeholder="Evidence URI" required>'
                    '<button>Complete</button></form>'
                )
            rows.append(
                f'<tr><td>{esc(assignment["document_number"])} rev {esc(assignment["revision_code"])}</td>'
                f'<td>{esc(assignment["display_name"])}</td><td>{esc(assignment["due_at"])}</td>'
                f'<td>{status}</td><td>{action}</td></tr>'
            )
        body = f'<section class="page-title"><div><p class="eyebrow">COMPETENCE</p><h1>Training assignments</h1></div></section><article class="panel"><div class="table-wrap"><table><thead><tr><th>Revision</th><th>Assigned to</th><th>Due</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></article>'
        notice = parse_qs(parsed.query).get("notice", [""])[0]
        self.send_html("Training", body, notice=notice)

    def complete_training(self, assignment_id, values):
        evidence_uri = values.get("evidence_uri", "").strip()
        if not evidence_uri:
            raise ValueError("training evidence URI is required")
        with closing(self.connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """UPDATE training_assignments SET completed_at=?, evidence_uri=?
                       WHERE assignment_id=? AND completed_at IS NULL""",
                    (utc_now(), evidence_uri, assignment_id),
                )
                if not cursor.rowcount:
                    raise ValueError("training assignment is already complete or does not exist")
        self.redirect("/training", "Training completion recorded")

    def not_found(self):
        self.send_html("Not found", "<h1>Page not found</h1><p><a href='/'>Return to dashboard</a></p>", HTTPStatus.NOT_FOUND)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def build_server(database: Path, port: int = 8765) -> ThreadingHTTPServer:
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")
    server = ThreadingHTTPServer(("127.0.0.1", port), DocumentControlHandler)
    server.database = database.resolve()
    server.csrf_token = secrets.token_urlsafe(32)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = build_server(args.database, args.port)
    print(f"AeroDocs is available at http://127.0.0.1:{server.server_port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
