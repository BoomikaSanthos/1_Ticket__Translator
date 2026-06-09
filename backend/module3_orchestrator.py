"""
BACKEND MODULE 3: Orchestrator & Report Generator
===================================================
Handles:
  - Full pipeline: upload ticket → detect → translate → save (one API call)
  - Reply pipeline: engineer types reply → translate back → save
  - Export translated tickets as downloadable Markdown report
  - Batch process all unprocessed tickets

This module calls Module 1 (translator) and Module 2 (ticket manager)
internally — it's the "glue" module.

Tech: Python, Flask, requests (to call other modules)
"""

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import requests
import sqlite3
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
CORS(app)

# ── Config: URLs of the other two modules ────────────────────────────────────
MODULE1_URL = "http://127.0.0.1:5001"   # Translator
MODULE2_URL = "http://127.0.0.1:5002"   # Ticket Manager
DB_PATH = str(Path(__file__).parent.resolve() / "tickets.db")
FRONTEND_DIR = Path(__file__).parent.parent.resolve() / "frontend"


# ── HELPER ───────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── ROUTE 1: Full pipeline — process a raw ticket text ───────────────────────
@app.route("/api/pipeline/process", methods=["POST"])
def pipeline_process():
    """
    POST /api/pipeline/process
    Body: { "text": "मेरा लैपटॉप बंद हो गया...", "filename": "ticket1.txt", "ticket_id": 3 }

    Full flow:
      1. Create ticket in Module 2 (if ticket_id not provided)
      2. Detect language via Module 1
      3. Translate to English via Module 1
      4. Update ticket in Module 2 with results
    Returns fully populated ticket.
    """
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text'"}), 400

    text      = data["text"].strip()
    filename  = data.get("filename", f"ticket_{int(datetime.now().timestamp())}.txt")
    ticket_id = data.get("ticket_id")

    errors = []
    steps  = []

    try:
        # ── Step 1: Create ticket (if not using an existing one) ─────────────────
        if ticket_id is None:
            r1 = requests.post(f"{MODULE2_URL}/api/tickets", json={"original_text": text, "filename": filename})
            r1.raise_for_status()
            ticket = r1.json()["ticket"]
            ticket_id = ticket["id"]
            steps.append({"step": "created", "ticket_id": ticket_id})
        else:
            steps.append({"step": "using_existing", "ticket_id": ticket_id})

        # ── Step 2: Detect + Translate via combined endpoint ────────────────
        r2 = requests.post(f"{MODULE1_URL}/api/process-ticket-text", json={"text": text})
        r2.raise_for_status()
        result = r2.json()

        language   = result.get("language", "Unknown")
        translated = result.get("translated", text)
        steps.append({"step": "translated", "language": language})

        # ── Step 3: Update ticket with language + translation ───────────────
        r3 = requests.patch(
            f"{MODULE2_URL}/api/tickets/{ticket_id}",
            json={
                "detected_lang":   language,
                "translated_text": translated,
                "status":          "in_progress",
            },
        )
        r3.raise_for_status()
        updated_ticket = r3.json()["ticket"]
        steps.append({"step": "saved"})

        return jsonify({
            "ticket":  updated_ticket,
            "steps":   steps,
            "success": True,
        })

    except requests.exceptions.ConnectionError as e:
        return jsonify({
            "error": "Cannot connect to a backend module. Make sure Module 1 (port 5001) and Module 2 (port 5002) are running.",
            "detail": str(e),
        }), 503
    except Exception as e:
        return jsonify({"error": str(e), "steps": steps, "success": False}), 500


# ── ROUTE 2: Reply pipeline ───────────────────────────────────────────────────
@app.route("/api/pipeline/reply", methods=["POST"])
def pipeline_reply():
    """
    POST /api/pipeline/reply
    Body: { "ticket_id": 3, "reply_english": "Please restart your laptop and try again." }

    Flow:
      1. Get ticket language from Module 2
      2. Translate reply via Module 1
      3. Save both versions to Module 2
    """
    data = request.get_json()
    if not data or "ticket_id" not in data or "reply_english" not in data:
        return jsonify({"error": "Missing 'ticket_id' or 'reply_english'"}), 400

    ticket_id = data["ticket_id"]
    reply_en  = data["reply_english"].strip()

    try:
        # ── Step 1: Get ticket to find language ─────────────────────────────
        r1 = requests.get(f"{MODULE2_URL}/api/tickets/{ticket_id}")
        if r1.status_code == 404:
            return jsonify({"error": f"Ticket {ticket_id} not found"}), 404
        r1.raise_for_status()
        ticket = r1.json()["ticket"]
        language = ticket.get("detected_lang", "English")

        # ── Step 2: Translate reply back ────────────────────────────────────
        r2 = requests.post(
            f"{MODULE1_URL}/api/translate-reply",
            json={"reply": reply_en, "target_language": language},
        )
        r2.raise_for_status()
        reply_original = r2.json().get("translated_reply", reply_en)

        # ── Step 3: Save to ticket ──────────────────────────────────────────
        r3 = requests.patch(
            f"{MODULE2_URL}/api/tickets/{ticket_id}",
            json={
                "reply_english":  reply_en,
                "reply_original": reply_original,
                "status":         "resolved",
            },
        )
        r3.raise_for_status()
        updated = r3.json()["ticket"]

        return jsonify({
            "ticket":          updated,
            "reply_english":   reply_en,
            "reply_original":  reply_original,
            "language":        language,
            "success":         True,
        })

    except requests.exceptions.ConnectionError as e:
        return jsonify({"error": "Cannot connect to backend modules.", "detail": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── ROUTE 3: Batch process all unprocessed tickets ────────────────────────────
@app.route("/api/pipeline/batch", methods=["POST"])
def batch_process():
    """
    POST /api/pipeline/batch
    Processes all tickets with status='new' that have no detected_lang yet.
    Returns summary of how many were processed.
    """
    try:
        r = requests.get(f"{MODULE2_URL}/api/tickets?status=new")
        r.raise_for_status()
        tickets = r.json()["tickets"]
        unprocessed = [t for t in tickets if not t.get("detected_lang")]

        results = []
        for ticket in unprocessed:
            try:
                resp = requests.post(
                    "http://localhost:5003/api/pipeline/process",
                    json={"text": ticket["original_text"], "filename": ticket["filename"], "ticket_id": ticket["id"]},
                )
                resp.raise_for_status()
                res_json = resp.json()
                if not res_json.get("success"):
                    raise Exception(res_json.get("error", "Failed processing ticket"))
                results.append({"ticket_id": ticket["id"], "status": "processed"})
            except Exception as ex:
                results.append({"ticket_id": ticket["id"], "status": "failed", "error": str(ex)})

        return jsonify({
            "processed": len(results),
            "results":   results,
            "success":   True,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── ROUTE 4: Export Markdown report ──────────────────────────────────────────
@app.route("/api/export/markdown", methods=["GET"])
def export_markdown():
    """
    GET /api/export/markdown
    Downloads a full Markdown report of all tickets.
    """
    conn = get_db()
    rows = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
    conn.close()

    lines = [
        "# SD-04 Multilingual Ticket Report",
        f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
        f"**Total Tickets:** {len(rows)}\n",
        "---\n",
    ]

    for row in rows:
        r = dict(row)
        lines += [
            f"## Ticket #{r['id']} — {r['filename']}",
            f"- **Status:** {r['status']}",
            f"- **Language:** {r['detected_lang'] or 'Unknown'}",
            f"- **Date:** {r['created_at']}\n",
            "### Original Text",
            f"```\n{r['original_text']}\n```\n",
            "### English Translation",
            f"```\n{r['translated_text'] or '(not translated yet)'}\n```\n",
        ]
        if r.get("reply_english"):
            lines += [
                "### Engineer Reply (English)",
                f"```\n{r['reply_english']}\n```\n",
                f"### Reply in {r['detected_lang'] or 'Original Language'}",
                f"```\n{r['reply_original'] or '(not translated)'}\n```\n",
            ]
        lines.append("---\n")

    content = "\n".join(lines)
    return Response(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition": "attachment; filename=ticket_report.md"},
    )


# ── ROUTE 5: Export JSON ──────────────────────────────────────────────────────
@app.route("/api/export/json", methods=["GET"])
def export_json():
    """GET /api/export/json — Download all tickets as JSON."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
    conn.close()
    tickets = [dict(r) for r in rows]
    return Response(
        __import__("json").dumps({"tickets": tickets, "exported_at": datetime.now().isoformat()}, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=tickets.json"},
    )


# ── Health ────────────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    """Check all 3 modules' health."""
    statuses = {}
    for name, url, port in [("translator", MODULE1_URL, 5001), ("ticket_manager", MODULE2_URL, 5002)]:
        try:
            r = requests.get(f"{url}/api/health", timeout=3)
            statuses[name] = "ok" if r.status_code == 200 else "error"
        except Exception:
            statuses[name] = f"offline (start on port {port})"

    statuses["orchestrator"] = "ok"
    return jsonify({"modules": statuses, "success": True})


# ── Frontend Static Router ──────────────────────────────────────────────────
@app.route("/")
def index():
    """Serve the submit page as the home page."""
    return send_from_directory(str(FRONTEND_DIR), "module1_submit.html")

@app.route("/<filename>")
def serve_frontend(filename):
    """Serve specific dashboard/submit/reply frontend HTML files."""
    if filename in ["module1_submit.html", "module2_dashboard.html", "module3_reply.html"]:
        return send_from_directory(str(FRONTEND_DIR), filename)
    return "Not Found", 404


if __name__ == "__main__":
    print("Module 3 - Orchestrator running on http://localhost:5003")
    app.run(port=5003, debug=True)