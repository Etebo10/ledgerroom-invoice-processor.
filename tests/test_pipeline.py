"""
Test suite for the core pipeline components.

Run with: pytest tests/ -v
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database import Database, InvoiceRecord
from field_parser import parse_invoice_text
from rules_engine import (
    STATUS_AUTO_APPROVED, STATUS_FLAGGED_ANOMALY, STATUS_FLAGGED_DUPLICATE,
    STATUS_NEEDS_APPROVAL, STATUS_NEEDS_MANUAL_REVIEW, evaluate,
)

APPROVAL_CFG = {
    "auto_approve_under": 500.0,
    "duplicate_window_days": 30,
    "anomaly_zscore_threshold": 2.5,
    "anomaly_min_history": 3,
}


# ---------------------------------------------------------------------------
# Field parser
# ---------------------------------------------------------------------------

SAMPLE_INVOICE_TEXT = """
Acme Office Supplies
123 Commerce St, Suite 200

INVOICE

Invoice Number: INV-12345
Invoice Date: August 17, 2026
Bill To: Sample Co.

Description                          Amount
Printer Paper (10 reams)             $120.00
Ink Cartridges                       $85.50

Total Amount Due:                    $205.50
Payment due within 30 days.
"""

SAMPLE_RECEIPT_TEXT = """
Metro Print & Design
Receipt #: INV-99887
Date: 08/10/2026

Business Card Printing               $60.00
TOTAL:                                $60.00
Thank you for your purchase!
"""


def test_parse_extracts_all_fields_from_clean_invoice_text():
    parsed = parse_invoice_text(SAMPLE_INVOICE_TEXT, known_vendors=["Acme Office Supplies"])
    assert parsed.vendor == "Acme Office Supplies"
    assert parsed.invoice_number == "INV-12345"
    assert parsed.invoice_date == "2026-08-17"
    assert parsed.total_amount == 205.50
    assert parsed.needs_manual_review is False


def test_parse_handles_slash_date_format():
    parsed = parse_invoice_text(SAMPLE_RECEIPT_TEXT, known_vendors=["Metro Print & Design"])
    assert parsed.invoice_date == "2026-08-10"
    assert parsed.total_amount == 60.00


def test_parse_prefers_total_amount_due_over_plain_total():
    text = "Subtotal: $100.00\nTax: $8.00\nTotal Amount Due: $108.00"
    parsed = parse_invoice_text(text)
    assert parsed.total_amount == 108.00


def test_parse_handles_abbreviated_dates_us_currency_and_hash_invoice_number():
    text = """Gidevon Realtors INVOICE
# 0022
Date: Sep 3, 2026
Balance Due: US$345.00
Total: US$345.00"""
    parsed = parse_invoice_text(text)
    assert parsed.invoice_number == "0022"
    assert parsed.invoice_date == "2026-09-03"
    assert parsed.total_amount == 345.00
    assert parsed.needs_manual_review is False


def test_parse_handles_day_first_date_and_whole_dollar_total_from_ocr():
    text = """INVOICE
BORCELLE
Invoice No: 01234
Date: 31/10/2023
SUBTOTAL TOTAL $550"""
    parsed = parse_invoice_text(text)
    assert parsed.invoice_number == "01234"
    assert parsed.invoice_date == "2023-10-31"
    assert parsed.total_amount == 550.0
    assert parsed.needs_manual_review is False


def test_parse_flags_manual_review_when_total_missing():
    parsed = parse_invoice_text("Some vendor\nNo total anywhere in here.")
    assert parsed.needs_manual_review is True
    assert any("total" in r.lower() for r in parsed.review_reasons)


def test_parse_flags_manual_review_when_text_is_garbage():
    parsed = parse_invoice_text("asdkj 23lkj4 !!! ???")
    assert parsed.needs_manual_review is True


# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def _parsed(vendor="Acme", amount=100.0, inv_date="2026-08-01", needs_review=False):
    from field_parser import ParsedInvoice
    return ParsedInvoice(
        vendor=vendor, invoice_number="INV-1", invoice_date=inv_date,
        total_amount=amount, raw_text="", needs_manual_review=needs_review, review_reasons=[],
    )


def test_small_amount_auto_approved(temp_db):
    result = evaluate(_parsed(amount=100.0), temp_db, APPROVAL_CFG)
    assert result.status == STATUS_AUTO_APPROVED


def test_large_amount_needs_approval(temp_db):
    result = evaluate(_parsed(amount=999.0), temp_db, APPROVAL_CFG)
    assert result.status == STATUS_NEEDS_APPROVAL


def test_extraction_incomplete_forces_manual_review(temp_db):
    result = evaluate(_parsed(needs_review=True), temp_db, APPROVAL_CFG)
    assert result.status == STATUS_NEEDS_MANUAL_REVIEW


def test_duplicate_same_vendor_amount_and_close_date_is_flagged(temp_db):
    temp_db.insert_invoice(InvoiceRecord(
        source_file="a.pdf", vendor="Acme", invoice_number="INV-1", invoice_date="2026-08-01",
        total_amount=100.0, extraction_method="pdf_text", status=STATUS_AUTO_APPROVED,
        processed_at="2026-08-01T00:00:00",
    ))
    result = evaluate(_parsed(vendor="Acme", amount=100.0, inv_date="2026-08-05"), temp_db, APPROVAL_CFG)
    assert result.status == STATUS_FLAGGED_DUPLICATE


def test_duplicate_not_flagged_if_outside_window(temp_db):
    temp_db.insert_invoice(InvoiceRecord(
        source_file="a.pdf", vendor="Acme", invoice_number="INV-1", invoice_date="2026-01-01",
        total_amount=100.0, extraction_method="pdf_text", status=STATUS_AUTO_APPROVED,
        processed_at="2026-01-01T00:00:00",
    ))
    result = evaluate(_parsed(vendor="Acme", amount=100.0, inv_date="2026-08-05"), temp_db, APPROVAL_CFG)
    assert result.status != STATUS_FLAGGED_DUPLICATE


def test_anomaly_flagged_when_amount_far_above_vendor_history(temp_db):
    # Seed consistent history: 3 invoices around $100
    for i, amt in enumerate([95.0, 105.0, 100.0]):
        temp_db.insert_invoice(InvoiceRecord(
            source_file=f"a{i}.pdf", vendor="Acme", invoice_number=f"INV-{i}",
            invoice_date="2026-07-0" + str(i + 1), total_amount=amt,
            extraction_method="pdf_text", status=STATUS_AUTO_APPROVED,
            processed_at="2026-07-01T00:00:00",
        ))
    # A wildly larger invoice from the same vendor should be flagged as anomalous
    result = evaluate(_parsed(vendor="Acme", amount=5000.0, inv_date="2026-08-01"), temp_db, APPROVAL_CFG)
    assert result.status == STATUS_FLAGGED_ANOMALY


def test_anomaly_not_flagged_with_insufficient_history(temp_db):
    # Only 1 prior invoice -- below anomaly_min_history of 3, so no anomaly check runs
    temp_db.insert_invoice(InvoiceRecord(
        source_file="a.pdf", vendor="Acme", invoice_number="INV-1", invoice_date="2026-07-01",
        total_amount=100.0, extraction_method="pdf_text", status=STATUS_AUTO_APPROVED,
        processed_at="2026-07-01T00:00:00",
    ))
    result = evaluate(_parsed(vendor="Acme", amount=5000.0, inv_date="2026-08-01"), temp_db, APPROVAL_CFG)
    # Still flagged, but for being over threshold -- NOT specifically as an anomaly
    assert result.status == STATUS_NEEDS_APPROVAL


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def test_insert_and_fetch_pending_approval(temp_db):
    temp_db.insert_invoice(InvoiceRecord(
        source_file="a.pdf", vendor="Acme", invoice_number="INV-1", invoice_date="2026-08-01",
        total_amount=999.0, extraction_method="pdf_text", status=STATUS_NEEDS_APPROVAL,
        processed_at="2026-08-01T00:00:00",
    ))
    temp_db.insert_invoice(InvoiceRecord(
        source_file="b.pdf", vendor="Acme", invoice_number="INV-2", invoice_date="2026-08-01",
        total_amount=50.0, extraction_method="pdf_text", status=STATUS_AUTO_APPROVED,
        processed_at="2026-08-01T00:00:00",
    ))
    pending = temp_db.fetch_pending_approval()
    assert len(pending) == 1
    assert pending[0]["status"] == STATUS_NEEDS_APPROVAL


def test_mark_reviewed_removes_from_pending(temp_db):
    invoice_id = temp_db.insert_invoice(InvoiceRecord(
        source_file="a.pdf", vendor="Acme", invoice_number="INV-1", invoice_date="2026-08-01",
        total_amount=999.0, extraction_method="pdf_text", status=STATUS_NEEDS_APPROVAL,
        processed_at="2026-08-01T00:00:00",
    ))
    temp_db.mark_reviewed(invoice_id, "approved")
    assert temp_db.fetch_pending_approval() == []
    record = temp_db.get_by_id(invoice_id)
    assert record["reviewed"] == 1
    assert record["review_decision"] == "approved"


# ---------------------------------------------------------------------------
# Vendor intelligence
# ---------------------------------------------------------------------------

def test_vendor_profile_summarizes_spend_reviews_and_risk(temp_db):
    for index, amount in enumerate([100.0, 300.0, 900.0]):
        temp_db.insert_invoice(InvoiceRecord(
            source_file=f"invoice-{index}.pdf", vendor="Acme", invoice_number=f"INV-{index}",
            invoice_date=f"2026-08-0{index + 1}", total_amount=amount,
            extraction_method="ocr" if index else "pdf_text",
            status=STATUS_AUTO_APPROVED if index == 0 else STATUS_NEEDS_APPROVAL,
            processed_at="2026-08-01", reviewed=index > 0,
            review_decision="rejected" if index == 2 else None,
        ))

    profile = temp_db.fetch_vendor_profile("Acme")

    assert profile.invoice_count == 3
    assert profile.total_spend == 1300.0
    assert profile.average_invoice == pytest.approx(433.33, abs=0.01)
    assert profile.median_invoice == 300.0
    assert profile.reviewed_count == 2
    assert profile.rejected_count == 1
    assert profile.auto_approval_rate == pytest.approx(33.33, abs=0.01)
    assert profile.last_invoice_date == "2026-08-03"
    assert profile.dominant_extraction_method == "ocr"
    assert "1 rejected invoice(s)" in profile.risk_signals
    assert "mostly OCR-derived documents" in profile.risk_signals


def test_vendor_profile_list_contains_unique_vendors(temp_db):
    for vendor in ("Zeta", "Acme", "Acme"):
        temp_db.insert_invoice(InvoiceRecord(
            source_file=f"{vendor}.pdf", vendor=vendor, invoice_number="INV-1",
            invoice_date="2026-08-01", total_amount=10.0,
            extraction_method="pdf_text", status=STATUS_AUTO_APPROVED,
            processed_at="2026-08-01",
        ))

    assert temp_db.fetch_vendor_names() == ["Acme", "Zeta"]
