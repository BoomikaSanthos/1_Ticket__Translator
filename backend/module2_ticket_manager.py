"""
BACKEND MODULE 2: Ticket Manager
=================================
Handles:
  - Create, Read, Update, Delete tickets (SQLite)
  - Upload ticket files (.txt)
  - Store original + translated + reply versions
  - Ticket status tracking (new / in_progress / resolved)
  - Filter & search tickets

Tech: Python, Flask, SQLite (built-in), Werkzeug (file upload)
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# ── CONFIG ────────────────────────────────────────────────────────────────────
DB_PATH = str(Path(__file__).parent.resolve() / "tickets.db")
UPLOAD_FOLDER = str(Path(__file__).parent.resolve() / "uploads")
ALLOWED_EXTENSIONS = {"txt"}

Path(UPLOAD_FOLDER).mkdir(exist_ok=True)


# ── DATABASE SETUP ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tickets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filename        TEXT,
            original_text   TEXT    NOT NULL,
            detected_lang   TEXT    DEFAULT '',
            translated_text TEXT    DEFAULT '',
            reply_english   TEXT    DEFAULT '',
            reply_original  TEXT    DEFAULT '',
            status          TEXT    DEFAULT 'new',
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id   INTEGER,
            action      TEXT,
            detail      TEXT,
            timestamp   TEXT
        );
    """)
    conn.commit()
    conn.close()
    print("[OK] Database initialized.")


init_db()


# ── HELPERS ───────────────────────────────────────────────────────────────────
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def log_action(ticket_id, action, detail=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_log (ticket_id, action, detail, timestamp) VALUES (?, ?, ?, ?)",
        (ticket_id, action, detail, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def row_to_dict(row):
    return dict(row) if row else None


# ── ROUTE: Create ticket (manual text input) ──────────────────────────────────
@app.route("/api/tickets", methods=["POST"])
def create_ticket():
    """
    POST /api/tickets
    Body: { "original_text": "...", "filename": "optional_name.txt" }
    Returns: { "ticket": {...}, "success": true }
    """
    data = request.get_json()
    if not data or "original_text" not in data:
        return jsonify({"error": "Missing 'original_text'"}), 400

    now = datetime.now().isoformat()
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO tickets
           (filename, original_text, status, created_at, updated_at)
           VALUES (?, ?, 'new', ?, ?)""",
        (
            data.get("filename", f"ticket_{int(datetime.now().timestamp())}.txt"),
            data["original_text"].strip(),
            now, now,
        ),
    )
    ticket_id = cursor.lastrowid
    conn.commit()

    ticket = row_to_dict(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())
    conn.close()

    log_action(ticket_id, "created", "Ticket created via API")
    return jsonify({"ticket": ticket, "success": True}), 201


# ── ROUTE: Upload .txt file as ticket ─────────────────────────────────────────
@app.route("/api/tickets/upload", methods=["POST"])
def upload_ticket():
    """
    POST /api/tickets/upload  (multipart/form-data, field: 'file')
    Returns: { "ticket": {...}, "success": true }
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Use field name 'file'"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Only .txt files are allowed"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)

    text = Path(save_path).read_text(encoding="utf-8").strip()
    now = datetime.now().isoformat()

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO tickets (filename, original_text, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (filename, text, "new", now, now),
    )
    ticket_id = cursor.lastrowid
    conn.commit()
    ticket = row_to_dict(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())
    conn.close()

    log_action(ticket_id, "uploaded", f"File: {filename}")
    return jsonify({"ticket": ticket, "success": True}), 201


# ── ROUTE: Get all tickets (with optional filter) ─────────────────────────────
@app.route("/api/tickets", methods=["GET"])
def get_tickets():
    """
    GET /api/tickets?status=new&lang=Tamil
    Returns: { "tickets": [...], "total": N }
    """
    status = request.args.get("status")
    lang   = request.args.get("lang")

    query  = "SELECT * FROM tickets WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if lang:
        query += " AND detected_lang LIKE ?"
        params.append(f"%{lang}%")

    query += " ORDER BY created_at DESC"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    tickets = [row_to_dict(r) for r in rows]
    return jsonify({"tickets": tickets, "total": len(tickets)})


# ── ROUTE: Get single ticket ──────────────────────────────────────────────────
@app.route("/api/tickets/<int:ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    conn = get_db()
    ticket = row_to_dict(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())
    conn.close()
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    return jsonify({"ticket": ticket, "success": True})


# ── ROUTE: Update ticket (save translation + reply) ───────────────────────────
@app.route("/api/tickets/<int:ticket_id>", methods=["PATCH"])
def update_ticket(ticket_id):
    """
    PATCH /api/tickets/3
    Body: { "detected_lang": "Tamil", "translated_text": "...", "status": "in_progress" }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed_fields = {
        "detected_lang", "translated_text", "reply_english",
        "reply_original", "status"
    }
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    updates["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join([f"{k} = ?" for k in updates])
    values = list(updates.values()) + [ticket_id]

    conn = get_db()
    conn.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", values)
    conn.commit()
    ticket = row_to_dict(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())
    conn.close()

    log_action(ticket_id, "updated", f"Fields: {list(updates.keys())}")
    return jsonify({"ticket": ticket, "success": True})


# ── ROUTE: Delete ticket ──────────────────────────────────────────────────────
@app.route("/api/tickets/<int:ticket_id>", methods=["DELETE"])
def delete_ticket(ticket_id):
    conn = get_db()
    existing = conn.execute("SELECT id FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404
    conn.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Ticket {ticket_id} deleted", "success": True})


# ── ROUTE: Get dashboard stats ────────────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Returns counts for dashboard: total, by status, by language."""
    conn = get_db()
    total      = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    by_status  = conn.execute(
        "SELECT status, COUNT(*) as count FROM tickets GROUP BY status"
    ).fetchall()
    by_language = conn.execute(
        "SELECT detected_lang, COUNT(*) as count FROM tickets WHERE detected_lang != '' GROUP BY detected_lang ORDER BY count DESC LIMIT 10"
    ).fetchall()
    conn.close()

    return jsonify({
        "total": total,
        "by_status":   {r["status"]: r["count"] for r in by_status},
        "by_language": {r["detected_lang"]: r["count"] for r in by_language},
        "success": True,
    })


# ── ROUTE: Get audit log ──────────────────────────────────────────────────────
@app.route("/api/tickets/<int:ticket_id>/log", methods=["GET"])
def get_audit_log(ticket_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE ticket_id=? ORDER BY timestamp DESC", (ticket_id,)
    ).fetchall()
    conn.close()
    return jsonify({"log": [row_to_dict(r) for r in rows], "success": True})


# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "module": "ticket_manager"})


if __name__ == "__main__":
    print("Module 2 - Ticket Manager running on http://localhost:5002")
    app.run(port=5002, debug=True)