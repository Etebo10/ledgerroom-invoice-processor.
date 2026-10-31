"""Flask web interface for the Invoice & Expense Processor."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import date
from werkzeug.utils import secure_filename
from flask import Flask, jsonify, render_template, request, send_file

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from main import load_config  # noqa: E402
from database import Database  # noqa: E402
from pipeline import process_inbox, SUPPORTED_EXTENSIONS  # noqa: E402
from excel_export import export_to_excel  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
CONFIG_PATH = os.environ.get("INVOICE_CONFIG", str(ROOT / "config" / "config.yaml"))
CONFIG = load_config(CONFIG_PATH)

# Keep relative paths anchored to the project even when launched by gunicorn.
os.chdir(ROOT)


def db() -> Database:
    return Database(CONFIG["paths"]["database_path"])


def money(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def serialize_profile(profile):
    return {
        "vendor": profile.vendor,
        "invoice_count": profile.invoice_count,
        "total_spend": money(profile.total_spend),
        "average_invoice": money(profile.average_invoice),
        "median_invoice": money(profile.median_invoice),
        "auto_approval_rate": round(profile.auto_approval_rate, 1),
        "last_invoice_date": profile.last_invoice_date,
        "risk_signals": profile.risk_signals,
        "rejected_count": profile.rejected_count,
        "manual_review_count": profile.manual_review_count,
    }


def dashboard_payload():
    database = db()
    records = database.fetch_all()
    pending = database.fetch_pending_approval()
    profiles = [serialize_profile(p) for p in database.fetch_vendor_profiles()]
    statuses = {}
    for item in records:
        statuses[item.get("status") or "Unknown"] = statuses.get(item.get("status") or "Unknown", 0) + 1
    total_spend = sum(money(r.get("total_amount")) for r in records if r.get("review_decision") != "rejected")
    approved = sum(1 for r in records if r.get("status") == "Auto-Approved" or r.get("review_decision") == "approved")
    flagged = sum(1 for r in records if (r.get("status") or "").startswith("Flagged"))
    amounts_by_month = {}
    for r in records:
        raw = r.get("invoice_date") or ""
        key = raw[:7] if len(raw) >= 7 else "Undated"
        amounts_by_month[key] = amounts_by_month.get(key, 0) + money(r.get("total_amount"))
    return {
        "company": CONFIG.get("company", {}).get("name", "Your business"),
        "currency_symbol": CONFIG.get("approval", {}).get("currency_symbol", "$"),
        "metrics": {
            "total_invoices": len(records), "total_spend": round(total_spend, 2),
            "pending_review": len(pending), "approved": approved, "flagged": flagged,
            "vendors": len(profiles),
        },
        "statuses": statuses,
        "monthly_spend": [{"month": k, "amount": round(v, 2)} for k, v in sorted(amounts_by_month.items())],
        "recent": records[:8],
        "pending": pending,
        "vendors": sorted(profiles, key=lambda x: x["total_spend"], reverse=True),
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def api_dashboard():
    return jsonify(dashboard_payload())


@app.get("/api/invoices")
def api_invoices():
    records = db().fetch_all()
    query = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "all")
    if status == "pending":
        records = [r for r in records if not r.get("reviewed") and r.get("status") != "Auto-Approved"]
    elif status != "all":
        records = [r for r in records if r.get("status") == status]
    if query:
        records = [r for r in records if query in " ".join(str(r.get(k) or "") for k in ("vendor", "invoice_number", "source_file", "status")).lower()]
    return jsonify({"invoices": records, "count": len(records)})


@app.post("/api/upload")
def api_upload():
    files = request.files.getlist("files")
    if not files or not any(f.filename for f in files):
        return jsonify({"error": "Choose at least one invoice or receipt to upload."}), 400
    inbox = Path(CONFIG["paths"]["inbox_dir"])
    inbox.mkdir(parents=True, exist_ok=True)
    accepted, rejected = [], []
    for file in files:
        if not file.filename:
            continue
        name = secure_filename(file.filename)
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            rejected.append(file.filename)
            continue
        destination = inbox / name
        if destination.exists():
            destination = inbox / f"{destination.stem}_{date.today().strftime('%Y%m%d')}_{os.urandom(3).hex()}{suffix}"
        file.save(destination)
        accepted.append(destination.name)
    if not accepted:
        return jsonify({"error": "No supported files found. Upload PDF, JPG, PNG, TIFF or BMP documents.", "rejected": rejected}), 400
    try:
        result = process_inbox(CONFIG)
    except Exception as exc:
        app.logger.exception("Invoice processing failed")
        return jsonify({"error": f"Processing failed: {exc}", "uploaded": accepted}), 500
    return jsonify({"message": "Documents processed.", "uploaded": accepted, "rejected": rejected, "result": result, "dashboard": dashboard_payload()})


@app.post("/api/invoices/<int:invoice_id>/review")
def api_review(invoice_id):
    payload = request.get_json(silent=True) or {}
    decision = payload.get("decision")
    if decision not in ("approved", "rejected"):
        return jsonify({"error": "Decision must be approved or rejected."}), 400
    database = db()
    record = database.get_by_id(invoice_id)
    if not record:
        return jsonify({"error": "Invoice not found."}), 404
    database.mark_reviewed(invoice_id, decision)
    export_to_excel(database.fetch_all(), CONFIG["paths"]["excel_log_path"])
    return jsonify({"message": f"Invoice {decision}.", "dashboard": dashboard_payload()})


@app.get("/api/vendors")
def api_vendors():
    profiles = [serialize_profile(p) for p in db().fetch_vendor_profiles()]
    return jsonify({"vendors": sorted(profiles, key=lambda x: x["total_spend"], reverse=True)})


@app.get("/api/export")
def api_export():
    path = Path(CONFIG["paths"]["excel_log_path"])
    if not path.exists():
        export_to_excel(db().fetch_all(), str(path))
    return send_file(path, as_attachment=True, download_name="expense_log.xlsx")


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "Upload is too large. The combined upload limit is 25 MB."}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
