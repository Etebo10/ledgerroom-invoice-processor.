"""
pipeline.py
-----------
Orchestrates a full processing run: scan the inbox folder -> extract text
from each document -> parse fields -> run approval/duplicate/anomaly rules
-> store in the database -> move the file to processed/failed -> export the
Excel log -> optionally email a pending-approval summary.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from database import Database, InvoiceRecord
from document_reader import DocumentReadError, extract_text
from emailer import send_approval_summary
from excel_export import export_to_excel
from field_parser import parse_invoice_text
from rules_engine import STATUS_AUTO_APPROVED, evaluate

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".bmp"}


def process_inbox(config: dict) -> dict:
    paths_cfg = config["paths"]
    ocr_cfg = config["ocr"]
    approval_cfg = config["approval"]

    inbox = Path(paths_cfg["inbox_dir"])
    processed_dir = Path(paths_cfg["processed_dir"])
    failed_dir = Path(paths_cfg.get("failed_dir", "data/failed"))
    processed_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    db = Database(paths_cfg["database_path"])
    known_vendors = config.get("sample_data", {}).get("vendors", [])

    files = sorted(
        f for f in inbox.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    logger.info("Found %d document(s) in inbox to process.", len(files))

    results = {"processed": 0, "failed": 0, "flagged": 0, "auto_approved": 0}

    for file_path in files:
        try:
            doc = extract_text(
                str(file_path), ocr_dpi=ocr_cfg["dpi"], ocr_lang=ocr_cfg["language"],
                tesseract_cmd=ocr_cfg.get("tesseract_cmd"),
            )
            parsed = parse_invoice_text(doc.text, known_vendors=known_vendors)
            rule_result = evaluate(parsed, db, approval_cfg)

            record = InvoiceRecord(
                source_file=file_path.name,
                vendor=parsed.vendor,
                invoice_number=parsed.invoice_number,
                invoice_date=parsed.invoice_date,
                total_amount=parsed.total_amount,
                extraction_method=doc.extraction_method,
                status=rule_result.status,
                flag_reasons=rule_result.reasons,
                raw_text=parsed.raw_text,
                processed_at=datetime.now().isoformat(timespec="seconds"),
            )
            invoice_id = db.insert_invoice(record)

            shutil.move(str(file_path), str(processed_dir / file_path.name))
            results["processed"] += 1
            if rule_result.status == STATUS_AUTO_APPROVED:
                results["auto_approved"] += 1
            else:
                results["flagged"] += 1

            logger.info("Processed %s -> id=%d, status=%s", file_path.name, invoice_id, rule_result.status)

        except DocumentReadError as e:
            logger.error("Failed to read %s: %s", file_path.name, e)
            shutil.move(str(file_path), str(failed_dir / file_path.name))
            results["failed"] += 1

    # Export the full log every run so the spreadsheet always reflects current state
    all_records = db.fetch_all()
    export_to_excel(all_records, paths_cfg["excel_log_path"])

    # Email pending approvals if configured
    email_cfg = config.get("email", {})
    pending = db.fetch_pending_approval()
    if email_cfg.get("enabled") and pending:
        subject = email_cfg["subject_template"].format(
            count=len(pending), date=datetime.now().date().isoformat()
        )
        send_approval_summary(
            recipients=email_cfg["recipients"], subject=subject,
            pending=pending, excel_attachment_path=paths_cfg["excel_log_path"],
        )
        results["emailed"] = True
    else:
        results["emailed"] = False

    results["pending_approval_count"] = len(pending)
    results["excel_log_path"] = paths_cfg["excel_log_path"]

    logger.info(
        "=== Run complete: %d processed (%d auto-approved, %d flagged), %d failed ===",
        results["processed"], results["auto_approved"], results["flagged"], results["failed"],
    )
    return results
